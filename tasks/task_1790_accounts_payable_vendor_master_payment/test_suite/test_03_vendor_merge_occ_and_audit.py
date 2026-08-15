"""Vendor merge paths, optimistic concurrency on the vendor master, the audit
trail, nested-path existence, and read-after-write consistency."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_vendor,
    assert_merge_record,
    assert_audit_event,
    create_vendor,
    attach_document,
    onboard_vendor_to_active,
    get_vendor,
    create_invoice,
    submit_invoice,
    approve_invoice_fully,
    create_matrix_rule,
)

VS1 = TEST_USERS["vendor_specialist_headers"]
VS2 = TEST_USERS["vendor_specialist_2_headers"]
VM1 = TEST_USERS["vendor_manager_headers"]
CLERK = TEST_USERS["ap_clerk_headers"]
AUD = TEST_USERS["auditor_headers"]


def _merge(api, survivor_id, duplicate_id, version):
    return api.merge_vendor(survivor_id, {
        "duplicate_vendor_id": duplicate_id,
        "expected_vendor_version": version}, VM1)


class TestMergePaths:
    def test_merged_vendor_reachable_via_fk_filters(self, api):
        """The MERGED source is reachable via the survivor FK filter and the
        merge record via its survivor filter.

        PRD §3.1: "Accounts payable staff can browse the vendor register with optional filters: `status` isolates a lifecycle stage, `name_contains` matches against vendor names, `merged_into_vendor_id` finds everything absorbed into a given survivor, and `primary_bank_account_id` locates the vendor currently paying through a given account."
        PRD §3.4: "The merge persists a `VendorMergeRecord` capturing `survivor_vendor_id`, `merged_vendor_id`, the `match_score` between the two legal names at merge time at four decimal places, the `invoices_repointed_count`, the `bank_accounts_disabled_count`, and the `merged_by_user_id`, and appends a `MERGE` audit event on both vendors."

        Design: Corner/entities/merged_vendor_reachable_via_fk_filters
        """
        survivor = onboard_vendor_to_active(
            legal_name="Survivor Stone", tax_id="20-0000008")
        duplicate = create_vendor(legal_name="Survivor Stone Duplicate",
                                  tax_id="20-0000009", duplicate_acknowledged=True)

        record = validate_success(_merge(
            api, survivor["id"], duplicate["id"],
            get_vendor(survivor["id"])["version"]))
        assert_merge_record(record)
        assert record["survivor_vendor_id"] == survivor["id"]
        assert record["merged_vendor_id"] == duplicate["id"]
        assert record["invoices_repointed_count"] == 0
        assert record["bank_accounts_disabled_count"] == 0
        # Dice('Survivor Stone', 'Survivor Stone Duplicate') = 22/31 -> 0.7097.
        assert record["match_score"] == pytest.approx(0.7097, abs=1e-6)
        assert record["merged_by_user_id"] == "u-vm-01"

        absorbed, meta = validate_paginated(api.list_vendors(
            AUD, params={"merged_into_vendor_id": survivor["id"]}))
        assert meta["total_count"] == 1
        assert absorbed[0]["id"] == duplicate["id"]
        assert absorbed[0]["status"] == "MERGED"
        assert absorbed[0]["merged_into_vendor_id"] == survivor["id"]

        records, meta = validate_paginated(api.list_merge_records(
            AUD, params={"survivor_vendor_id": survivor["id"]}))
        assert meta["total_count"] == 1
        assert_merge_record(records[0])
        assert records[0]["id"] == record["id"]

    def test_merge_invoice_number_collision_gate(self, api):
        """Re-pointing must not collide an invoice_number on the survivor; after
        the colliding source invoice is cancelled the merge succeeds and
        re-points only the non-terminal remainder.

        PRD §3.4: "The merge gate rejects with `ERR_VENDOR_NOT_MERGEABLE` unless all of the following hold: the source vendor is in `DRAFT`, `PENDING_APPROVAL`, `ACTIVE`, `SUSPENDED`, or `DORMANT`; the survivor is `ACTIVE`; source and survivor are different vendors; neither vendor has payments in `PENDING` or `RELEASED`; neither vendor has an `OPEN` sanctions review case; and re-pointing the source's invoices would not collide an `invoice_number` already present on the survivor."
        PRD §3.4: "A successful merge moves the source vendor to the terminal `MERGED` status with its `merged_into_vendor_id` set to the survivor, re-points every invoice of the source whose status is neither `PAID` nor `CANCELLED` to the survivor, disables the source's bank accounts in `PENDING_VERIFICATION` or `VERIFIED` — each moving to `DISABLED` — while the survivor's primary account is left unchanged, and increments the survivor's `version` by one."

        Design: Corner/validations/merge_invoice_number_collision_gate
        """
        create_matrix_rule(cost_center="GLOBAL", min_amount_cents=0,
                           max_amount_cents=500000, tier=1)
        survivor = onboard_vendor_to_active(
            legal_name="Merge Master", tax_id="20-0000045")
        s_inv = create_invoice(survivor["id"], amount_cents=100000,
                               invoice_number="DUP-9", received_date="2026-08-01")
        submit_invoice(s_inv["id"])
        approve_invoice_fully(s_inv["id"])

        source = onboard_vendor_to_active(
            legal_name="Merge Duplicate", tax_id="20-0000046")
        dup_inv = create_invoice(source["id"], amount_cents=50000,
                                 invoice_number="DUP-9", received_date="2026-08-01")
        uniq_inv = create_invoice(source["id"], amount_cents=60000,
                                  invoice_number="UNIQ-5", received_date="2026-08-01")
        submit_invoice(uniq_inv["id"])
        approve_invoice_fully(uniq_inv["id"])

        version = get_vendor(survivor["id"])["version"]
        resp = _merge(api, survivor["id"], source["id"], version)
        validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_MERGEABLE.value)

        get_success_data(api.cancel_invoice(dup_inv["id"], {"reason": "clearing merge collision"}, CLERK))
        record = validate_success(_merge(api, survivor["id"], source["id"], version))
        assert_merge_record(record)
        assert record["invoices_repointed_count"] == 1, "only UNIQ-5 re-points; CANCELLED is excluded"
        assert record["bank_accounts_disabled_count"] == 0

        repointed = get_success_data(api.get_invoice(uniq_inv["id"], AUD))
        assert repointed["vendor_id"] == survivor["id"]
        assert get_vendor(source["id"])["status"] == "MERGED"


class TestOptimisticConcurrency:
    def test_occ_vendor_patch_stale_version(self, api):
        """A PATCH replaying an already-superseded vendor version is refused 412;
        re-reading and retrying succeeds.

        PRD §2.8: "If `expected_vendor_version` does not equal the vendor's current `version`, the client's view of the vendor is stale — another write has legitimately advanced the record since the client last read it — and the request is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than being silently layered over the newer state."
        PRD §2.5: "`version` (integer): a system-managed integer that increments by one on every mutation of the resource."

        Design: Corner/cross_cutting_layers/occ_vendor_patch_stale_version
        """
        vendor = create_vendor(legal_name="Occ Olive", tax_id="20-0000058")
        v0 = vendor["version"]

        patched = validate_success(api.patch_vendor(
            vendor["id"], {"phone": "+1-555-7000",
                           "expected_vendor_version": v0}, VS1))
        assert patched["version"] == v0 + 1, "version increments by one per mutation"

        stale = api.patch_vendor(vendor["id"], {
            "city": "Shelbyville", "expected_vendor_version": v0}, VS1)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)
        unchanged = get_vendor(vendor["id"])
        assert unchanged["city"] == "Springfield"
        assert unchanged["version"] == v0 + 1

        retried = validate_success(api.patch_vendor(
            vendor["id"], {"city": "Shelbyville",
                           "expected_vendor_version": unchanged["version"]}, VS1))
        assert retried["city"] == "Shelbyville"
        assert retried["version"] == v0 + 2

    def test_occ_vendor_merge_stale_version(self, api):
        """The merge OCC check applies to the survivor: a second merge carrying
        the pre-merge observation is refused 412 and the duplicate stays DRAFT.

        PRD §2.8: "Three write operations on the vendor master require the client to state which version of the vendor it last observed, carried in the non-optional request field `expected_vendor_version`: editing a vendor's master data, adding a bank account to a vendor, and merging a duplicate vendor into a survivor (in the merge case the check applies to the survivor vendor's version)."
        PRD §2.5: "Certain cross-resource mutations also increment a related resource's `version` even though the client wrote to a different resource."

        Design: Corner/cross_cutting_layers/occ_vendor_merge_stale_version
        """
        survivor = onboard_vendor_to_active(
            legal_name="Merge Hub", tax_id="20-0000059")
        dup_a = create_vendor(legal_name="Zephyr Receivables One", tax_id="20-0000060")
        dup_b = create_vendor(legal_name="Quantum Receivables Two", tax_id="20-0000061")
        v0 = get_vendor(survivor["id"])["version"]

        validate_success(_merge(api, survivor["id"], dup_a["id"], v0))

        stale = _merge(api, survivor["id"], dup_b["id"], v0)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)
        assert get_vendor(dup_b["id"])["status"] == "DRAFT"

        fresh_version = get_vendor(survivor["id"])["version"]
        assert fresh_version == v0 + 1, "the first merge incremented the survivor version"
        validate_success(_merge(api, survivor["id"], dup_b["id"], fresh_version))
        merged = get_vendor(dup_b["id"])
        assert merged["status"] == "MERGED"
        assert merged["merged_into_vendor_id"] == survivor["id"]


class TestAuditTrailExistenceAndConsistency:
    def test_audit_trail_records_master_data_changes(self, api):
        """Create then PATCH writes CREATE + one UPDATE audit event carrying
        field_name, old/new values, and actor identity.

        PRD §2.7: "Editing a vendor's master data writes one `UPDATE` audit event per changed field, so a single edit that touches three fields appends three events."
        PRD §2.7: "For `UPDATE` and `STATUS_CHANGE` events the record also carries `field_name`, with the prior and replacement values stringified into `old_value` and `new_value`."
        PRD §2.7: "Every event stamps `actor_user_id` and `actor_role` from the caller's headers."

        Design: Corner/entities/audit_trail_records_master_data_changes
        """
        vendor = create_vendor(legal_name="Audit Alley", tax_id="20-0000006",
                               phone="+1-555-2006")
        v0 = vendor["version"]
        patched = validate_success(api.patch_vendor(
            vendor["id"], {"phone": "+1-555-9999",
                           "expected_vendor_version": v0}, VS2))
        assert patched["version"] == v0 + 1

        events, meta = validate_paginated(api.list_audit_events(
            AUD, params={"entity_type": "Vendor", "entity_id": vendor["id"]}))
        assert meta["total_count"] == 2
        for event in events:
            assert_audit_event(event)
        create_event = [e for e in events if e["event_type"] == "CREATE"]
        update_event = [e for e in events if e["event_type"] == "UPDATE"]
        assert len(create_event) == 1
        assert create_event[0]["actor_user_id"] == "u-vs-01"
        assert create_event[0]["actor_role"] == "VendorSpecialist"
        assert len(update_event) == 1, "one changed field -> exactly one UPDATE event"
        assert update_event[0]["field_name"] == "phone"
        assert update_event[0]["old_value"] == "+1-555-2006"
        assert update_event[0]["new_value"] == "+1-555-9999"
        assert update_event[0]["actor_user_id"] == "u-vs-02"
        assert update_event[0]["actor_role"] == "VendorSpecialist"

    def test_nested_path_with_missing_parent_returns_not_found(self, api):
        """Nested path existence validates left to right: a document create under
        a non-existent vendor 404s on the parent.

        PRD §2.11: "Only then are path identifiers resolved: endpoints that address nested resources validate the path strictly left to right, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) for the first identifier that does not correspond to an existing resource — a request targeting a bank account under a non-existent vendor fails on the vendor before the account is ever sought."

        Design: Corner/errors/nested_path_with_missing_parent_returns_not_found
        """
        resp = api.create_document(NON_EXISTENT_UUID, {
            "doc_type": "W9", "valid_from": "2026-01-01",
            "valid_until": "2027-12-31"}, VS1)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_immediate_read_after_write_consistency(self, api):
        """The PATCH response itself carries the new values and incremented
        version, and a subsequent GET agrees.

        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §2.5: "`version` (integer): a system-managed integer that increments by one on every mutation of the resource."

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        vendor = create_vendor(legal_name="Consistent Crane", tax_id="20-0000064")
        v0 = vendor["version"]
        patched = validate_success(api.patch_vendor(
            vendor["id"], {"remit_email": "new@cc4.com",
                           "expected_vendor_version": v0}, VS1))
        assert patched["remit_email"] == "new@cc4.com"
        assert patched["version"] == v0 + 1

        fetched = get_vendor(vendor["id"])
        assert fetched["remit_email"] == "new@cc4.com"
        assert fetched["version"] == patched["version"]
