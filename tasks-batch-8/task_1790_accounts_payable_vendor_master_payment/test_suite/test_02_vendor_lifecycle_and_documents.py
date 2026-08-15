"""Vendor lifecycle (submit/approve/suspend/dormancy/deactivate/merge) and
compliance document rules."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_vendor,
    assert_timestamp_equals,
    create_vendor,
    attach_document,
    onboard_vendor_to_active,
    get_vendor,
    set_clock,
    run_vendor_sweep,
    create_watchlist_entry,
    create_invoice_payload,
)

VS1 = TEST_USERS["vendor_specialist_headers"]
VS2 = TEST_USERS["vendor_specialist_2_headers"]
VM1 = TEST_USERS["vendor_manager_headers"]
VM2 = TEST_USERS["vendor_manager_2_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CLERK = TEST_USERS["ap_clerk_headers"]
AUD = TEST_USERS["auditor_headers"]


class TestDocumentWindows:
    def test_document_overlap_shared_endpoint_day_rejected(self, api):
        """Closed-interval semantics: sharing the day 2026-12-31 is an overlap.

        PRD §3.1: "For a given vendor and a given `doc_type`, two documents' windows must not overlap, and because the intervals are closed, even sharing a single endpoint day counts as an overlap, rejected with `ERR_DOCUMENT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/vendor_document_closed_interval_overlap
        """
        vendor = create_vendor(legal_name="Doc Holdings", tax_id="10-0000013")
        attach_document(vendor["id"], doc_type="W9",
                        valid_from="2026-01-01", valid_until="2026-12-31")
        resp = api.create_document(vendor["id"], {
            "doc_type": "W9", "valid_from": "2026-12-31",
            "valid_until": "2027-06-30"}, VS1)
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_PERIOD_OVERLAP.value)

    def test_document_non_overlapping_successor_and_other_doc_type_allowed(self, api):
        """The first legal successor starts the day after valid_until; the overlap
        gate is scoped per (vendor, doc_type).

        PRD §3.1: "For a given vendor and a given `doc_type`, two documents' windows must not overlap, and because the intervals are closed, even sharing a single endpoint day counts as an overlap, rejected with `ERR_DOCUMENT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/vendor_document_closed_interval_overlap
        """
        vendor = create_vendor(legal_name="Doc Holdings", tax_id="10-0000013")
        attach_document(vendor["id"], doc_type="W9",
                        valid_from="2026-01-01", valid_until="2026-12-31")
        successor = validate_success(api.create_document(vendor["id"], {
            "doc_type": "W9", "valid_from": "2027-01-01",
            "valid_until": "2027-12-31"}, VS1), expected_status=201)
        assert successor["status"] == "VALID"
        other_type = validate_success(api.create_document(vendor["id"], {
            "doc_type": "INSURANCE_CERT", "valid_from": "2026-06-01",
            "valid_until": "2026-12-31"}, VS1), expected_status=201)
        assert other_type["doc_type"] == "INSURANCE_CERT"

    def test_vendor_submit_without_w9_rejected(self, api):
        """An INSURANCE_CERT is not a W9: submit with no W9 on file fails.

        PRD §3.1: "The submit gate requires at least one live-valid `W9` on file at the current logical date; when no live-valid W9 exists — whether none was ever filed or every W9's window has closed — the submission is rejected with `ERR_REQUIRED_DOCUMENT_MISSING`."

        Design: Corner/validations/vendor_submit_without_w9_rejected
        """
        vendor = create_vendor(legal_name="No W9 Nook", tax_id="20-0000035")
        attach_document(vendor["id"], doc_type="INSURANCE_CERT",
                        valid_from="2026-01-01", valid_until="2027-12-31")
        resp = api.submit_vendor(vendor["id"], VS1)
        validate_error(resp, ApiErrorId.ERR_REQUIRED_DOCUMENT_MISSING.value)
        assert get_vendor(vendor["id"])["status"] == "DRAFT"

    def test_document_expired_by_sweep_at_inclusive_boundary(self, api):
        """valid_until is inclusive: the sweep stamps EXPIRED only once the
        logical date has passed valid_until.

        PRD §3.1: "A document is born `VALID`; a `VendorSpecialist` may supersede it, moving it from `VALID` to `SUPERSEDED` with a `STATUS_CHANGE` audit event, and the vendor sweep stamps `VALID` rows `EXPIRED` once the logical date has passed their `valid_until`."
        PRD §3.1: "A document passes live evaluation when its status is `VALID` and the current logical date falls on or after `valid_from` and on or before `valid_until` — both bounds inclusive — so a row still cached as `VALID` whose window has already closed fails live checks."

        Design: Corner/state_machines/document_expired_by_sweep_at_inclusive_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        vendor = create_vendor(legal_name="Doc Date", tax_id="20-0000015")
        doc = attach_document(vendor["id"], doc_type="W9",
                              valid_from="2026-01-01", valid_until="2026-08-01")

        counters = run_vendor_sweep()
        assert counters["documents_expired"] == 0, "valid_until day itself is still valid"
        docs, _ = validate_paginated(api.list_documents(vendor["id"], AUD))
        assert docs[0]["status"] == "VALID"

        set_clock("2026-08-02T00:00:00Z")
        counters = run_vendor_sweep()
        assert counters["documents_expired"] == 1
        docs, _ = validate_paginated(api.list_documents(vendor["id"], AUD))
        assert docs[0]["id"] == doc["id"]
        assert docs[0]["status"] == "EXPIRED"


class TestVendorApprovalAndBlocking:
    def test_sod_vendor_creator_cannot_approve(self, api):
        """A VendorManager who created the vendor cannot approve it (SoD-1); a
        different manager can.

        PRD §2.6: "The `VendorManager` approving a vendor must not be the operator recorded as that vendor's `created_by_user_id`."
        PRD §2.6: "A self-approval attempt is rejected with `ERR_SOD_VENDOR_CREATOR_CANNOT_APPROVE`."

        Design: Corner/validations/sod_vendor_creator_cannot_approve_forbidden
        """
        vendor = create_vendor(legal_name="Self Approve Co", tax_id="20-0000029",
                               headers=VM1)
        attach_document(vendor["id"])
        get_success_data(api.submit_vendor(vendor["id"], VM1))

        resp = api.approve_vendor(vendor["id"], VM1)
        validate_error(resp, ApiErrorId.ERR_SOD_VENDOR_CREATOR_CANNOT_APPROVE.value)
        assert get_vendor(vendor["id"])["status"] == "PENDING_APPROVAL"

        approved = validate_success(api.approve_vendor(vendor["id"], VM2))
        assert approved["status"] == "ACTIVE"

    def test_exact_block_watchlist_hit_routes_approve_to_blocked(self, api):
        """Exact normalized-name equality with a BLOCK entry routes approval to
        HIT and the vendor to BLOCKED; the score is pinned at 1.0000.

        PRD §3.2: "If the best score is exactly 1.0000 and that entry's `severity` is `BLOCK`, the result is `HIT`; if the best score is exactly 1.0000 with severity `REVIEW`, the result is `REVIEW`; if the best score is at least 0.8000 without reaching exact equality, the result is `REVIEW`; otherwise the result is `CLEAR`."
        PRD §3.2: "When the result is `HIT`, the vendor becomes `BLOCKED` and the screening row is persisted."
        PRD §2.10: "Normalization takes a single raw name string and applies four steps in order: first, uppercase the string; second, replace every character that is not a letter or digit with a space; third, split on whitespace and discard any token that is a corporate suffix — `INC`, `LLC`, `CORP`, `CORPORATION`, `COMPANY`, `CO`, `LTD`, `LP`, `LLP`, `PLLC`, or `PC`; fourth, concatenate the surviving tokens with no separator."

        Design: Corner/calculations/exact_block_watchlist_hit_rejects_at_approve
        """
        create_watchlist_entry("Vortex Trading", severity="BLOCK")
        vendor = create_vendor(legal_name="Vortex Trading, Inc.", tax_id="20-0000026")
        attach_document(vendor["id"])
        get_success_data(api.submit_vendor(vendor["id"], VS1))
        blocked = validate_success(api.approve_vendor(vendor["id"], VM1))
        assert blocked["status"] == "BLOCKED"

        checks, meta = validate_paginated(api.list_screening_checks(
            AUD, params={"vendor_id": vendor["id"]}))
        assert meta["total_count"] == 1
        assert checks[0]["result"] == "HIT"
        assert checks[0]["match_score"] == pytest.approx(1.0, abs=1e-9)

    def test_vendor_blocked_blocks_invoice_create(self, api):
        """A BLOCKED vendor cannot take new invoices.

        PRD §3.5: "The vendor gates fire before the invoice exists: a `BLOCKED` vendor rejects the intake with `ERR_VENDOR_BLOCKED`, a vendor in any status other than `ACTIVE` rejects it with `ERR_VENDOR_NOT_ACTIVE`, and an `invoice_number` already present on that vendor among invoices not in `CANCELLED` status rejects it with `ERR_DUPLICATE_INVOICE_NUMBER` — a cancelled invoice's number is free to be reused."

        Design: Corner/errors/vendor_blocked_blocks_invoice_create
        """
        create_watchlist_entry("Vortex Trading", severity="BLOCK")
        vendor = create_vendor(legal_name="Vortex Trading", tax_id="20-0000052")
        attach_document(vendor["id"])
        get_success_data(api.submit_vendor(vendor["id"], VS1))
        get_success_data(api.approve_vendor(vendor["id"], VM1))
        assert get_vendor(vendor["id"])["status"] == "BLOCKED"

        resp = api.create_invoice(create_invoice_payload(
            vendor_id=vendor["id"], invoice_number="INV-9005",
            amount_cents=100000, cost_center="CC-100",
            received_date="2026-08-01"), CLERK)
        validate_error(resp, ApiErrorId.ERR_VENDOR_BLOCKED.value)


class TestSuspendDormancyDeactivation:
    def test_vendor_suspend_reinstate_round_trip(self, api):
        """ACTIVE -> SUSPENDED -> ACTIVE on one vendor row.

        PRD §3.4: "A `VendorManager` or `ComplianceOfficer` may suspend an `ACTIVE` vendor, supplying a `reason`."
        PRD §3.4: "Reinstatement by a `VendorManager` moves a `SUSPENDED` vendor back to `ACTIVE`, but only while no sanctions review case in `OPEN` status references the vendor; otherwise the reinstatement is rejected with `ERR_VENDOR_HAS_OPEN_CASE`."

        Design: Difficulty/non_linear_state_machine/vendor_active_suspended_dormant_cycle
        """
        set_clock("2026-01-01T00:00:00Z")
        vendor = onboard_vendor_to_active(
            legal_name="Cycle Parts", tax_id="10-0000004")
        suspended = validate_success(api.suspend_vendor(
            vendor["id"], {"reason": "audit"}, VM1))
        assert suspended["status"] == "SUSPENDED"
        reinstated = validate_success(api.reinstate_vendor(vendor["id"], VM1))
        assert reinstated["status"] == "ACTIVE"

    def test_vendor_dormant_sweep_and_reactivate(self, api):
        """The sweep moves a 212-day-idle ACTIVE vendor to DORMANT; reactivation
        with a CLEAR screening restores ACTIVE and clears dormant_since_at.

        PRD §3.4: "When that reference is set, at least 180 days have elapsed between it and the current logical time — a vendor exactly 180 days along is eligible — and the vendor holds no invoices in the five open statuses listed above, the vendor moves from `ACTIVE` to `DORMANT` with `dormant_since_at` stamped at the logical time and a `STATUS_CHANGE` audit event."
        PRD §3.4: "A `VendorManager` may instead bring a `DORMANT` vendor back through reactivation, which re-runs the setup screening variant and routes on its result: `CLEAR` restores the vendor to `ACTIVE` and clears `dormant_since_at` to null; `REVIEW` moves it to `SUSPENDED` and opens a review case unless one is already `OPEN`; `HIT` moves it to `BLOCKED`."

        Design: Difficulty/non_linear_state_machine/vendor_active_suspended_dormant_cycle
        """
        set_clock("2026-01-01T00:00:00Z")
        vendor = onboard_vendor_to_active(
            legal_name="Cycle Parts", tax_id="10-0000004")

        set_clock("2026-08-01T00:00:00Z")
        counters = run_vendor_sweep()
        assert counters["vendors_marked_dormant"] == 1
        dormant = get_vendor(vendor["id"])
        assert dormant["status"] == "DORMANT"
        assert_timestamp_equals(dormant["dormant_since_at"], "2026-08-01T00:00:00Z",
                                "dormant_since_at must be stamped at the logical time")

        reactivated = validate_success(api.reactivate_vendor(vendor["id"], VM1))
        assert reactivated["status"] == "ACTIVE"
        assert reactivated["dormant_since_at"] is None

    def test_dormancy_exactly_180_days_boundary(self, api):
        """A vendor exactly 180 days along is dormancy-eligible (>= semantics);
        179 days is not.

        PRD §3.4: "When that reference is set, at least 180 days have elapsed between it and the current logical time — a vendor exactly 180 days along is eligible — and the vendor holds no invoices in the five open statuses listed above, the vendor moves from `ACTIVE` to `DORMANT` with `dormant_since_at` stamped at the logical time and a `STATUS_CHANGE` audit event."

        Design: Corner/calculations/dormancy_exactly_180_days_boundary
        """
        set_clock("2026-02-02T00:00:00Z")
        old = onboard_vendor_to_active(legal_name="Old Owl", tax_id="20-0000022")
        set_clock("2026-02-03T00:00:00Z")
        new = onboard_vendor_to_active(legal_name="Newt Newt", tax_id="20-0000023")

        set_clock("2026-08-01T00:00:00Z")
        counters = run_vendor_sweep()
        assert counters["vendors_marked_dormant"] == 1
        assert get_vendor(old["id"])["status"] == "DORMANT", "exactly 180 days is eligible"
        assert get_vendor(new["id"])["status"] == "ACTIVE", "179 days is not eligible"

    def test_dormant_vendor_deactivated_after_90_days(self, api):
        """Second sweep leg: DORMANT for exactly 90 days -> DEACTIVATED.

        PRD §3.4: "In a second pass, each `DORMANT` vendor for whom at least 90 days have elapsed since `dormant_since_at`, again with no open invoices, moves to `DEACTIVATED`."

        Design: Corner/state_machines/dormant_vendor_deactivated_after_90_days
        """
        set_clock("2026-01-01T00:00:00Z")
        vendor = onboard_vendor_to_active(
            legal_name="Silent Springs", tax_id="20-0000017")
        set_clock("2026-08-01T00:00:00Z")
        counters = run_vendor_sweep()
        assert counters["vendors_marked_dormant"] == 1

        set_clock("2026-10-30T00:00:00Z")  # dormant_since 2026-08-01 + exactly 90 days
        counters = run_vendor_sweep()
        assert counters["vendors_deactivated"] == 1
        assert get_vendor(vendor["id"])["status"] == "DEACTIVATED"

    def test_vendor_sweep_second_run_is_noop(self, api):
        """The sweep is an epoch checkpoint: a second run at the same logical
        instant transitions nothing.

        PRD §2.4: "The sweep answers with four counters — `vendors_marked_dormant`, `vendors_deactivated`, `documents_expired`, and `callback_verifications_expired` — reporting what each pass did."

        Design: Corner/cross_cutting_layers/ops_run_sweep_idempotent_second_run_noop
        """
        set_clock("2026-01-01T00:00:00Z")
        onboard_vendor_to_active(legal_name="Idle Ibis", tax_id="20-0000063")
        set_clock("2026-08-01T00:00:00Z")
        first = run_vendor_sweep()
        assert first["vendors_marked_dormant"] == 1

        second = run_vendor_sweep()
        assert second["vendors_marked_dormant"] == 0
        assert second["vendors_deactivated"] == 0
        assert second["documents_expired"] == 0
        assert second["callback_verifications_expired"] == 0

    def test_deactivate_with_open_invoices_rejected(self, api):
        """A single RECEIVED invoice blocks deactivation.

        PRD §3.4: "Two gates apply: the vendor must hold no invoices in `RECEIVED`, `PENDING_APPROVAL`, `APPROVED`, `IN_PAYMENT_RUN`, or `ON_HOLD` — a violation is rejected with `ERR_VENDOR_HAS_OPEN_INVOICES` — and the vendor must have no payments still in `PENDING` or `RELEASED`."

        Design: Corner/validations/deactivate_with_open_invoices_rejected
        """
        vendor = onboard_vendor_to_active(
            legal_name="Open Oasis", tax_id="20-0000040")
        get_success_data(api.create_invoice(create_invoice_payload(
            vendor_id=vendor["id"], invoice_number="INV-9990",
            amount_cents=100000, cost_center="CC-100",
            received_date="2026-08-01"), CLERK))
        resp = api.deactivate_vendor(vendor["id"], VM1)
        validate_error(resp, ApiErrorId.ERR_VENDOR_HAS_OPEN_INVOICES.value)
        assert get_vendor(vendor["id"])["status"] == "ACTIVE"


class TestMergedVendorLockdown:
    def test_merged_vendor_terminal_lockdown(self, api):
        """MERGED is terminal: a suspend attempt on the absorbed vendor fails.

        PRD §3.4: "A successful merge moves the source vendor to the terminal `MERGED` status with its `merged_into_vendor_id` set to the survivor, re-points every invoice of the source whose status is neither `PAID` nor `CANCELLED` to the survivor, disables the source's bank accounts in `PENDING_VERIFICATION` or `VERIFIED` — each moving to `DISABLED` — while the survivor's primary account is left unchanged, and increments the survivor's `version` by one."
        PRD §2.11: "State legality follows — a transition whose source state does not permit it, an edit outside its allowed status window, or an acknowledgement aimed at an already-terminal resource is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409), with the more specific state guards `ERR_CALLBACK_LOCKED`, `ERR_CALLBACK_EXPIRED`, and `ERR_PAYMENT_ALREADY_TERMINAL` applied where they exist."

        Design: Corner/state_machines/merged_vendor_terminal_lockdown
        """
        survivor = onboard_vendor_to_active(
            legal_name="Terminal Tom", tax_id="20-0000010")
        duplicate = create_vendor(legal_name="Terminal Tom Copy",
                                  tax_id="20-0000011",
                                  duplicate_acknowledged=True)
        get_success_data(api.merge_vendor(survivor["id"], {
            "duplicate_vendor_id": duplicate["id"],
            "expected_vendor_version": get_vendor(survivor["id"])["version"]}, VM1))
        assert get_vendor(duplicate["id"])["status"] == "MERGED"

        resp = api.suspend_vendor(duplicate["id"], {"reason": "should fail"}, VM1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
