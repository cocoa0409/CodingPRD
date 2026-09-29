"""Issuing serial ranges: the pinned fee waterfall, serial-interval rules and the version guard."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    DEFAULT_SERIAL_START,
    assert_tag_lot,
    create_active_premises,
    create_approved_supplier,
    create_tag_lot_payload,
    issue_lot,
    make_program_admin_headers,
    make_supplier_rep_headers,
    read_supplier,
    read_tag_lot,
    register_producer,
    setup_lot_scenario,
    setup_supplier_with_defects,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_program_admin_headers("admin-reg")


class TestIssuanceFeeWaterfall:
    def test_volume_discount_tier_is_selected_from_the_pre_surcharge_subtotal(self, api):
        """PRD §3.3: "The lot's `quantity` is derived as `serial_end` minus `serial_start` plus one."
        PRD §3.3: "Step two forms a pre-discount subtotal of a flat base charge of 25,000 cents plus 42 cents for every device in the lot."
        PRD §3.3: "Step three selects the volume discount percentage **from that pre-surcharge subtotal, never from the post-surcharge total**: 0 percent when the subtotal is below 50,000 cents; 5 percent when the subtotal is at least 50,000 cents but below 150,000 cents; 12 percent when the subtotal is at least 150,000 cents but below 400,000 cents; and 18 percent when the subtotal is 400,000 cents or more."
        PRD §3.3: "Step four multiplies the subtotal by that percentage and rounds half up to whole cents to give the discount. Step five subtracts the discount from the subtotal to give the discounted total. Step six computes the surcharge: if — and only if — the supplier's `probation` flag is true, the surcharge is 4 percent of the **discounted** total, rounded half up to whole cents; otherwise the surcharge is 0. Step seven sets `fee_cents` to the discounted total plus the surcharge, records the surcharge in `surcharge_cents`, and records the selected percentage in `discount_pct_applied`."

        Design: Difficulty/combinatorial_formula/issuance_fee_discount_tier_keyed_on_subtotal_then_surcharge
        """
        scenario = setup_supplier_with_defects(
            lot_quantity=4000, defect_count=6, premises_capacity=500
        )
        first_lot = read_tag_lot(scenario["lot"]["id"])

        assert first_lot["quantity"] == 4000
        # subtotal 25000 + 42 * 4000 = 193000 -> 12 percent -> discount 23160 -> 169840
        assert first_lot["surcharge_cents"] == 0, (
            "the supplier was off probation when this lot was priced"
        )
        assert first_lot["fee_cents"] == 169840

        assert scenario["supplier_after_defects"]["conformance_score"] == 82.00
        assert scenario["supplier_after_defects"]["probation"] is True
        assert scenario["supplier_after_defects"]["issuance_cap"] == 2000

    def test_probation_surcharge_is_four_percent_of_the_discounted_total(self, api):
        """PRD §3.3: "Step three selects the volume discount percentage **from that pre-surcharge subtotal, never from the post-surcharge total**: 0 percent when the subtotal is below 50,000 cents; 5 percent when the subtotal is at least 50,000 cents but below 150,000 cents; 12 percent when the subtotal is at least 150,000 cents but below 400,000 cents; and 18 percent when the subtotal is 400,000 cents or more."
        PRD §3.3: "Step four multiplies the subtotal by that percentage and rounds half up to whole cents to give the discount. Step five subtracts the discount from the subtotal to give the discounted total. Step six computes the surcharge: if — and only if — the supplier's `probation` flag is true, the surcharge is 4 percent of the **discounted** total, rounded half up to whole cents; otherwise the surcharge is 0. Step seven sets `fee_cents` to the discounted total plus the surcharge, records the surcharge in `surcharge_cents`, and records the selected percentage in `discount_pct_applied`."
        PRD §3.3: "Both the surcharge decision and the cap check read the supplier exactly as it stood **before** this lot was counted into `issued_tag_count`. A lot whose `quantity` exceeds the supplier's current `issuance_cap` is refused with `ERR_ISSUANCE_CAP_EXCEEDED`, which is why a supplier sitting at a zero cap cannot issue anything at all until its conformance recovers."

        Design: Difficulty/combinatorial_formula/issuance_fee_discount_tier_keyed_on_subtotal_then_surcharge
        """
        scenario = setup_supplier_with_defects(
            lot_quantity=4000, defect_count=6, premises_capacity=500
        )
        supplier_id = scenario["supplier"]["id"]

        second_lot = issue_lot(
            supplier_id, scenario["premises"]["id"], DEFAULT_SERIAL_START + 4000, 2000
        )
        assert_tag_lot(second_lot)
        assert second_lot["quantity"] == 2000, "the cap boundary of 2000 devices is admitted"
        # subtotal 25000 + 42 * 2000 = 109000 -> 5 percent -> discount 5450 -> discounted 103550
        assert second_lot["surcharge_cents"] == 4142, "4 percent of the discounted 103550 cents"
        assert second_lot["fee_cents"] == 107692, "103550 discounted plus the 4142 surcharge"

        supplier_after = read_supplier(supplier_id)
        assert supplier_after["issued_tag_count"] == 6000
        assert supplier_after["conformance_score"] == 88.00, "100.00 - 12.0 * (6 / 6.0)"
        assert supplier_after["probation"] is False
        assert supplier_after["issuance_cap"] == 5000

        frozen = read_tag_lot(second_lot["id"])
        assert frozen["surcharge_cents"] == 4142, (
            "the fee froze the pre-request probation state and never re-prices"
        )

    def test_lot_quantity_and_fee_are_derived_from_the_serial_range_alone(self, api):
        """PRD §3.3: "The lot's `quantity` is derived as `serial_end` minus `serial_start` plus one."
        PRD §3.3: "Step two forms a pre-discount subtotal of a flat base charge of 25,000 cents plus 42 cents for every device in the lot."
        PRD §3.3: "The lot's `unapplied_count` is always its `quantity` less its `applied_count`, `retired_count`, `replaced_count` and `voided_count` — the never-materialised remainder of the range."
        PRD §3.3: "A successful issuance creates the lot in status `ISSUED`, increments the supplier's `version` by one, and re-derives the supplier's `issued_tag_count`, `conformance_score`, `probation` and `issuance_cap`."

        Design: Corner/entities/tag_lot_quantity_and_fee_are_computed_not_client_supplied
        """
        scenario = setup_lot_scenario(
            operation_type="FEEDLOT", capacity=600, quantity=500, legal_name="Computed Co"
        )
        lot = scenario["lot"]
        assert_tag_lot(lot)
        assert lot["quantity"] == 500
        assert lot["fee_cents"] == 46000, "25000 + 42 * 500, with no discount below 50,000 cents"
        assert lot["discount_pct_applied"] == 0, "the subtotal sits below the first discount tier"
        assert lot["surcharge_cents"] == 0
        assert lot["unapplied_count"] == 500
        assert lot["applied_count"] == 0
        assert lot["status"] == "ISSUED"


class TestSerialIntervalRules:
    def test_abutting_serial_ranges_are_accepted(self, api):
        """PRD §3.3: "A new lot's closed serial interval may not intersect the interval of any existing non-voided lot belonging to the same supplier; abutting ranges — where the previous lot's `serial_end` plus one equals the new `serial_start` — are explicitly permitted, while any true intersection is refused with `ERR_SERIAL_RANGE_OVERLAP`."
        PRD §3.3: "The lot's `quantity` is derived as `serial_end` minus `serial_start` plus one."

        Design: Difficulty/resource_temporal_overlap/serial_ranges_abut_ok_but_intersect_rejected
        """
        scenario = setup_lot_scenario(
            operation_type="FEEDLOT", capacity=900, quantity=4000, legal_name="Llano Cattle"
        )
        first = scenario["lot"]
        assert first["serial_end"] == DEFAULT_SERIAL_START + 3999

        second = issue_lot(
            scenario["supplier"]["id"],
            scenario["premises"]["id"],
            first["serial_end"] + 1,
            2000,
        )
        assert second["quantity"] == 2000, (
            "a range starting one past the previous serial_end merely abuts and is permitted"
        )
        assert second["status"] == "ISSUED"

    def test_serial_range_sharing_one_endpoint_with_an_existing_lot_is_rejected(self, api):
        """PRD §3.3: "A new lot's closed serial interval may not intersect the interval of any existing non-voided lot belonging to the same supplier; abutting ranges — where the previous lot's `serial_end` plus one equals the new `serial_start` — are explicitly permitted, while any true intersection is refused with `ERR_SERIAL_RANGE_OVERLAP`."
        PRD §3.2: "The `issued_tag_count` sums the `quantity` of every lot belonging to the supplier whose status is `ISSUED`, `ACTIVE`, `DEPLETED` or `RECALLED`; voided lots are excluded entirely."

        Design: Difficulty/resource_temporal_overlap/serial_ranges_abut_ok_but_intersect_rejected
        """
        scenario = setup_lot_scenario(
            operation_type="FEEDLOT", capacity=900, quantity=4000, legal_name="Llano Cattle"
        )
        supplier_id = scenario["supplier"]["id"]
        first = scenario["lot"]
        issue_lot(supplier_id, scenario["premises"]["id"], first["serial_end"] + 1, 2000)

        payload = create_tag_lot_payload(
            supplier_id,
            scenario["premises"]["id"],
            read_supplier(supplier_id)["version"],
            serial_start=first["serial_end"],
            quantity=501,
        )
        resp = api.create_tag_lot(payload, make_supplier_rep_headers(supplier_id))
        validate_error(resp, ApiErrorId.ERR_SERIAL_RANGE_OVERLAP, expected_status=409)

        assert read_supplier(supplier_id)["issued_tag_count"] == 6000, (
            "the rejected range must not be counted into the supplier's issued devices"
        )


class TestIssuanceRulePrecedence:
    def test_serial_overlap_is_reported_ahead_of_the_issuance_cap(self, api):
        """PRD §2.5: "Guards `POST /premises`, `POST /device-suppliers`, `POST /tag-lots`, `POST /tag-lots/{id}/apply-tag`, `POST /tags/{id}/replace`, `POST /movement-events`, `POST /movement-events/{id}/correct`, `POST /hold-orders/{id}/appeal` and `POST /incentive-awards`, yielding `ERR_DUPLICATE_PIN`, `ERR_DUPLICATE_SUPPLIER_CODE`, `ERR_DUPLICATE_AIN`, `ERR_SERIAL_RANGE_OVERLAP`, `ERR_CORRECTION_LIMIT_EXCEEDED`, `ERR_APPEAL_LIMIT_EXCEEDED`, `ERR_RESIDENCY_OVERLAP` or `ERR_AWARD_PERIOD_DUPLICATE`."
        PRD §2.5: "Guards `POST /tag-lots`, `POST /tag-lots/{id}/apply-tag`, `POST /tags/{id}/replace` and `POST /movement-events/{id}/receive`, yielding `ERR_ISSUANCE_CAP_EXCEEDED`, `ERR_LOT_EXHAUSTED` or `ERR_PREMISES_AT_CAPACITY`."
        PRD §2.5: "Rules are evaluated **strictly in ascending priority order**, the first failing rule alone decides the response, and no side effect of any kind is applied once a rule has failed."

        Design: Difficulty/priority_pair_validation_conflict/constraint_serial_overlap_beats_fiscal_issuance_cap
        """
        scenario = setup_supplier_with_defects(
            lot_quantity=4000, defect_count=6, premises_capacity=500
        )
        supplier_id = scenario["supplier"]["id"]
        assert scenario["supplier_after_defects"]["issuance_cap"] == 2000

        # 3001 devices exceeds the 2000 cap AND intersects the existing 1..4000 lot.
        payload = create_tag_lot_payload(
            supplier_id,
            scenario["premises"]["id"],
            read_supplier(supplier_id)["version"],
            serial_start=DEFAULT_SERIAL_START + 2999,
            quantity=3001,
        )
        resp = api.create_tag_lot(payload, make_supplier_rep_headers(supplier_id))
        validate_error(resp, ApiErrorId.ERR_SERIAL_RANGE_OVERLAP, expected_status=409)

    def test_lot_rejected_for_overlap_is_not_counted_into_the_supplier(self, api):
        """PRD §2.5: "Because band 16 reads the state as it stood before the request, a lot can never widen the very issuance cap that admits it, and an animal can never be counted into the destination premises it is trying to enter."
        PRD §3.2: "The `issued_tag_count` sums the `quantity` of every lot belonging to the supplier whose status is `ISSUED`, `ACTIVE`, `DEPLETED` or `RECALLED`; voided lots are excluded entirely."
        PRD §3.2: "`issuance_cap` — the largest `quantity` permitted on a single new lot — is 10000 when the score is at least 95.00, 5000 when the score is at least 85.00 but below 95.00, 2000 when the score is at least 70.00 but below 85.00, and 0 when the score is below 70.00."

        Design: Difficulty/priority_pair_validation_conflict/constraint_serial_overlap_beats_fiscal_issuance_cap
        """
        scenario = setup_supplier_with_defects(
            lot_quantity=4000, defect_count=6, premises_capacity=500
        )
        supplier_id = scenario["supplier"]["id"]

        payload = create_tag_lot_payload(
            supplier_id,
            scenario["premises"]["id"],
            read_supplier(supplier_id)["version"],
            serial_start=DEFAULT_SERIAL_START + 2999,
            quantity=3001,
        )
        resp = api.create_tag_lot(payload, make_supplier_rep_headers(supplier_id))
        validate_error(resp, ApiErrorId.ERR_SERIAL_RANGE_OVERLAP, expected_status=409)

        after = read_supplier(supplier_id)
        assert after["issuance_cap"] == 2000
        assert after["issued_tag_count"] == 4000, "the rejected lot was never counted"

        rows, meta = validate_paginated(
            api.list_tag_lots(ADMIN, params={"supplier_id": supplier_id})
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1


class TestIssuanceGuards:
    def test_lot_naming_an_unknown_premises_is_a_body_reference_failure(self, api):
        """PRD §2.5: "Every foreign key supplied in the request body resolves, yielding `ERR_PRODUCER_NOT_FOUND`, `ERR_PREMISES_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_TAG_LOT_NOT_FOUND` or `ERR_TRACE_REQUEST_NOT_FOUND` as appropriate."
        PRD §2.5: "Rules are evaluated **strictly in ascending priority order**, the first failing rule alone decides the response, and no side effect of any kind is applied once a rule has failed."

        Design: Corner/entities/tag_lot_creation_with_unknown_premises_returns_premises_not_found
        """
        supplier = create_approved_supplier(company_name="AllFlex North")
        payload = create_tag_lot_payload(
            supplier["id"],
            NON_EXISTENT_UUID,
            supplier["version"],
            serial_start=DEFAULT_SERIAL_START,
            quantity=10,
        )
        resp = api.create_tag_lot(payload, make_supplier_rep_headers(supplier["id"]))
        validate_error(resp, ApiErrorId.ERR_PREMISES_NOT_FOUND, expected_status=404)

        after = read_supplier(supplier["id"])
        assert after["issued_tag_count"] == 0
        assert after["version"] == supplier["version"], "no side effect on a rejected request"

    def test_reusing_a_stale_supplier_version_on_a_second_lot_is_rejected(self, api):
        """PRD §2.6: "A `POST /tag-lots` request must carry `expected_supplier_version` matching the current `version` of the `DeviceSupplier` named by `supplier_id`. If the supplier's version has advanced since the client read it, the request is rejected with `ERR_STALE_VERSION` and HTTP 412."
        PRD §3.3: "A successful issuance creates the lot in status `ISSUED`, increments the supplier's `version` by one, and re-derives the supplier's `issued_tag_count`, `conformance_score`, `probation` and `issuance_cap`."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_supplier_version_on_lot_create
        """
        producer = register_producer(legal_name="Stale Co")
        premises = create_active_premises(
            producer["id"], operation_type="FEEDLOT", state_code="CO", capacity=500
        )
        supplier = create_approved_supplier(company_name="AllFlex North")
        observed_version = supplier["version"]

        first_payload = create_tag_lot_payload(
            supplier["id"],
            premises["id"],
            observed_version,
            serial_start=DEFAULT_SERIAL_START,
            quantity=100,
        )
        first_lot = validate_success(
            api.create_tag_lot(first_payload, make_supplier_rep_headers(supplier["id"])),
            expected_status=201,
        )

        stale_payload = create_tag_lot_payload(
            supplier["id"],
            premises["id"],
            observed_version,
            serial_start=DEFAULT_SERIAL_START + 100,
            quantity=100,
        )
        resp = api.create_tag_lot(stale_payload, make_supplier_rep_headers(supplier["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        assert read_supplier(supplier["id"])["issued_tag_count"] == 100
        rows, meta = validate_paginated(
            api.list_tag_lots(ADMIN, params={"supplier_id": supplier["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first_lot["id"]
