"""Service catalog: item uniqueness, OCC-guarded patches, guarded retirement,
and the price-maintenance cascade."""
from test_helpers import (
    ApiErrorId,
    certify_list,
    create_active_contract,
    create_charge_record,
    create_cycle,
    create_facility,
    create_payer,
    create_rate,
    create_service_item,
    create_shoppable_list,
    get_success_data,
    setup_open_cycle_with_record,
    shoppable_entry,
    validate_error,
    validate_paginated,
    validate_record,
)
from test_helpers.fixtures import MANAGER, OFFICER


class TestServiceItemUniqueness:
    def test_service_item_duplicate_code_within_facility_rejected(self, api):
        """PRD section 3.2: "A `TransparencyOfficer` registers each billable service with its owning `facility_id`, a billing `code` (unique within the facility — a duplicate is rejected with `ERR_DUPLICATE_ITEM_CODE`), a `code_type` of `CPT`, `HCPCS`, `MS_DRG`, or `REVENUE_CODE`, a plain-language `description`, a `service_class` of `SHOPPABLE`, `ANCILLARY`, `SUPPLY`, `DRUG`, or `FACILITY_FEE`, the chargemaster price `gross_charge_cents` (zero or more), and optionally `medicare_base_cents` (zero or more, required in practice by percent-of-Medicare rates), an `ancillary_inclusion` posture of `ALWAYS_BUNDLED`, `CONDITIONALLY_INCLUDED`, or `SEPARATELY_PRICED` (default `SEPARATELY_PRICED`), and the `cms_shoppable_mandated` flag (default false) marking the CMS-specified shoppable services."

        Design: Corner/entities/service_item_duplicate_code_within_facility_rejected
        """
        f1 = create_facility(name="F1", cms_certification_number="CCN-E3A",
                             bed_count=50)
        f2 = create_facility(name="F2", cms_certification_number="CCN-E3B",
                             bed_count=50)
        create_service_item(f1["id"], code="70551", description="MRI",
                            gross_charge_cents=100000)
        resp = api.create_service_item(
            {"facility_id": f1["id"], "code": "70551", "code_type": "CPT",
             "description": "MRI dup", "service_class": "SHOPPABLE",
             "gross_charge_cents": 110000}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ITEM_CODE)
        # Uniqueness is scoped to the facility: the same code at F2 succeeds.
        other = create_service_item(f2["id"], code="70551",
                                    description="MRI other facility",
                                    gross_charge_cents=90000)
        assert other["id"]


class TestServiceItemOcc:
    def test_occ_service_item_patch_stale_version_rejected(self, api):
        """PRD section 2.6: "A request to update a `ServiceItem` must carry `expected_service_item_version`, holding the item `version` the client last observed."
        PRD section 2.6: "If another writer has advanced the item's version since that observation — for example by changing its gross charge or retiring it, both of which legitimately succeed under product semantics — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting an item state it has not seen."

        Design: Corner/cross_cutting_layers/occ_service_item_patch_stale_version_rejected
        """
        fac = create_facility(name="F", cms_certification_number="CCN-X1L",
                              bed_count=50)
        item = create_service_item(fac["id"], code="70551",
                                   description="MRI", gross_charge_cents=100000)
        observed_version = item["version"]
        # First patch with the fresh version succeeds.
        updated = get_success_data(api.patch_service_item(
            item["id"], {"gross_charge_cents": 110000,
                         "expected_service_item_version": observed_version},
            OFFICER))
        assert updated["gross_charge_cents"] == 110000
        assert updated["version"] == observed_version + 1
        # Second patch still carrying the pre-first-patch version is stale.
        resp = api.patch_service_item(
            item["id"], {"gross_charge_cents": 120000,
                         "expected_service_item_version": observed_version},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412
        # The losing write left no trace.
        items, _ = validate_paginated(
            api.list_service_items(fac["id"], OFFICER))
        assert len(items) == 1
        assert items[0]["gross_charge_cents"] == 110000
        assert items[0]["version"] == observed_version + 1


class TestRetirementGuard:
    def test_service_item_retire_blocked_by_certified_list(self, api):
        """PRD section 3.8: "The same endpoint retires the item: passing a `status` of `RETIRED` moves the item `ACTIVE → RETIRED`, provided no `CERTIFIED` or `PUBLISHED` shoppable list of the same facility still references the item in an entry — a guarded retirement that fails with `ERR_ITEM_IN_CERTIFIED_LIST`."

        Design: Difficulty/cross_entity_state_dependency/service_item_retire_blocked_by_certified_list
        """
        fac = create_facility(name="F", cms_certification_number="CCN-X2",
                              bed_count=100, shoppable_min_entries=1,
                              mandated_min_entries=1)
        si1 = create_service_item(fac["id"], code="70551", description="MRI",
                                  gross_charge_cents=100000,
                                  cms_shoppable_mandated=True)
        l1 = create_shoppable_list(
            fac["id"], [shoppable_entry(si1["id"], display_name="MRI")])
        certify_list(l1["id"])  # L1 is now CERTIFIED and references SI1
        resp = api.patch_service_item(
            si1["id"], {"status": "RETIRED",
                        "expected_service_item_version": si1["version"]},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_ITEM_IN_CERTIFIED_LIST)
        assert resp.status_code == 409
        items, _ = validate_paginated(
            api.list_service_items(fac["id"], OFFICER))
        by_id = {i["id"]: i for i in items}
        assert by_id[si1["id"]]["status"] == "ACTIVE", \
            "SI1 remains ACTIVE after the rejected retire"

    def test_service_item_retire_allowed_with_draft_list_only(self, api):
        """PRD section 3.8: "The same endpoint retires the item: passing a `status` of `RETIRED` moves the item `ACTIVE → RETIRED`, provided no `CERTIFIED` or `PUBLISHED` shoppable list of the same facility still references the item in an entry — a guarded retirement that fails with `ERR_ITEM_IN_CERTIFIED_LIST`."

        Design: Difficulty/cross_entity_state_dependency/service_item_retire_blocked_by_certified_list
        """
        fac = create_facility(name="F", cms_certification_number="CCN-X2",
                              bed_count=100, shoppable_min_entries=1,
                              mandated_min_entries=1)
        si2 = create_service_item(fac["id"], code="70450",
                                  description="CT head",
                                  gross_charge_cents=80000)
        # L2 stays DRAFT, so the certified-list guard does not engage.
        create_shoppable_list(
            fac["id"], [shoppable_entry(si2["id"], display_name="CT")])
        retired = get_success_data(api.patch_service_item(
            si2["id"], {"status": "RETIRED",
                        "expected_service_item_version": si2["version"]},
            OFFICER))
        assert retired["status"] == "RETIRED"


class TestGrossPatchCascade:
    def _setup(self, api):
        """Facility + ACTIVE DISCLOSE contract with a 40% rate + OPEN cycle
        with one VALIDATED record (cash 50000, min/max/derived 40000)."""
        ctx = setup_open_cycle_with_record(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-C1",
                                "bed_count": 100},
            item_overrides={"code": "70551", "description": "MRI",
                            "gross_charge_cents": 100000})
        ctx["record"] = validate_record(ctx["record"]["id"])
        return ctx

    def test_gross_patch_cascades_to_rate_and_record(self, api):
        """PRD section 2.8: "Any event that perturbs one link recomputes every dependent link downstream — patching an item's price re-derives rates, records, and cycle aggregates; activating, renegotiating, terminating, or expiring a contract re-derives the same chain under a different rate inclusion set."
        PRD section 3.2: "A `PERCENT_OF_GROSS` rate materializes to the item's current `gross_charge_cents` multiplied by `rate_percent` and divided by 100, truncated down to a whole cent."
        PRD section 3.3: "At creation the record snapshots the item's current `gross_charge_cents` and computes three derived figures."

        Design: Difficulty/transitive_cascade/gross_patch_cascades_to_cycle_rollup
        """
        ctx = self._setup(api)
        record_before = get_success_data(
            api.get_charge_record(ctx["record"]["id"], OFFICER))
        assert record_before["min_negotiated_cents"] == 40000
        assert record_before["derived_disclosure_cents"] == 40000
        assert record_before["gross_charge_cents"] == 100000
        # Link 1: the item patch re-materializes the rate.
        get_success_data(api.patch_service_item(
            ctx["item"]["id"],
            {"gross_charge_cents": 200000,
             "expected_service_item_version": ctx["item"]["version"]},
            OFFICER))
        rate = get_success_data(api.get_rate(ctx["rate"]["id"], OFFICER))
        assert rate["negotiated_amount_cents"] == 80000  # floor(200000*40/100)
        # Link 2: the VALIDATED record recomputes under the new rate while its
        # gross snapshot stays at the creation-time value.
        record = get_success_data(
            api.get_charge_record(ctx["record"]["id"], OFFICER))
        assert record["min_negotiated_cents"] == 80000
        assert record["max_negotiated_cents"] == 80000
        assert record["derived_disclosure_cents"] == 80000
        assert record["gross_charge_cents"] == 100000

    def test_gross_patch_cascades_to_cycle_rollup(self, api):
        """PRD section 2.8: "Each recomputation is a real mutation: an affected cycle refreshes its `updated_at` and increments its `version`, as does every mutated rate, record, list, or file."
        PRD section 3.3: "On success the record transitions `DRAFT → VALIDATED`, both the record's and the cycle's `version` increment, and the cycle's aggregates recompute: `validated_record_count` counts the cycle's records in `VALIDATED`, `PUBLISHED`, or `FLAGGED`; `total_gross_cents` sums their `gross_charge_cents`; and `derived_rollup_cents` sums their `derived_disclosure_cents`, with records whose disclosure figure is null contributing zero."

        Design: Difficulty/transitive_cascade/gross_patch_cascades_to_cycle_rollup
        """
        ctx = self._setup(api)
        cycle_pre = get_success_data(api.get_cycle(ctx["cycle"]["id"], OFFICER))
        assert cycle_pre["derived_rollup_cents"] == 40000
        assert cycle_pre["total_gross_cents"] == 100000
        # cycle create (1) -> record create increments (2) -> validate (3)
        assert cycle_pre["version"] == 3
        get_success_data(api.patch_service_item(
            ctx["item"]["id"],
            {"gross_charge_cents": 200000,
             "expected_service_item_version": ctx["item"]["version"]},
            OFFICER))
        # Link 3: the cycle rollup recomputes and the cycle version bumps.
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], OFFICER))
        assert cycle["derived_rollup_cents"] == 80000
        assert cycle["total_gross_cents"] == 100000  # snapshot: unchanged
        assert cycle["version"] == 4
