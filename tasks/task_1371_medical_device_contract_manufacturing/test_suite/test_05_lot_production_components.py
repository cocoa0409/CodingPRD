"""Lot production: sampling tiers, component genealogy, quantity buckets."""
from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    add_component,
    assert_part_mass_balance,
    complete_lot,
    create_completed_lot,
    create_lot,
    create_lot_payload,
    create_component_payload,
    create_part,
    create_qualified_supplier,
    create_released_lot,
    create_validated_stack,
    disposition_ncr,
    contain_ncr,
    create_ncr,
    get_lot,
    get_part,
    po,
    qe,
    validate_error,
    validate_success,
    validate_paginated,
    api_client,
)


def _sampling_stack():
    """Validated stack + qualified supplier with a non-critical and a critical
    part, plus three released priming lots to reach process maturity."""
    stack = create_validated_stack("DEV-S", claim_months=20)
    qs = create_qualified_supplier("SUP-S", "Sterile Parts Co")
    part = create_part(qs["supplier"]["id"], "PN-S", description="seal", receive_qty=1000)
    part_critical = create_part(
        qs["supplier"]["id"], "PN-SC", critical=True, description="valve", receive_qty=1000
    )
    priming = []
    for i in (1, 2, 3):
        priming.append(
            create_released_lot(
                stack, part,
                lot_number=f"LT-S{i}", quantity=10,
                manufactured_at="2026-08-02T00:00:00Z",
                supplier_lot_number=f"SL-S{i}",
            )
        )
    return stack, part, part_critical, priming


class TestSterileSampleQtyTieredMaturity:
    def test_immature_process_samples_full_quantity_then_tier_applies(self, api):
        """PRD section 3.6: "Process maturity decides the regime: when fewer than
        three sibling lots under the same validation protocol have reached
        `RELEASED` or `RECALLED`, the process is immature and `sample_qty` equals
        the entire `quantity` — a 100% inspection. Once at least three such
        siblings exist, a tiered base applies instead: ... 151 to 1,200 samples
        32" and "The final `sample_qty` is the smaller of the lot's `quantity`
        and the computed base, and `releasable_qty` is `quantity` minus
        `sample_qty`."

        Design: Difficulty/combinatorial_formula/sterile_sample_qty_tiered_maturity
        """
        stack, part, _critical, priming = _sampling_stack()
        assert priming[0]["lot"]["sample_qty"] == 10, (
            f"immature process must 100%-sample, got {priming[0]['lot']['sample_qty']}"
        )

        lot4 = create_lot(
            "LT-S4", stack["dmr"]["id"], stack["protocol"]["id"], quantity=151,
            manufactured_at="2026-08-02T00:00:00Z",
        )
        add_component(lot4["id"], part["id"], quantity_used=151, supplier_lot_number="SL-S4")
        completed = complete_lot(lot4["id"])
        assert completed["sample_qty"] == 32, (
            f"tier 151..1200 samples 32 once mature, got {completed['sample_qty']}"
        )
        assert completed["releasable_qty"] == 119

    def test_critical_component_multiplies_sample_base(self, api):
        """PRD section 3.6: "If any recorded component of the lot references a
        part flagged `critical`, that base is multiplied by one and a half and
        rounded up to the next whole unit — a single ceiling with no intermediate
        rounding." — ceil(32 * 1.5) == 48.

        Design: Difficulty/combinatorial_formula/sterile_sample_qty_tiered_maturity
        """
        stack, _part, part_critical, _priming = _sampling_stack()
        lot5 = create_lot(
            "LT-S5", stack["dmr"]["id"], stack["protocol"]["id"], quantity=151,
            manufactured_at="2026-08-02T00:00:00Z",
        )
        add_component(
            lot5["id"], part_critical["id"], quantity_used=151, supplier_lot_number="SL-S5"
        )
        completed = complete_lot(lot5["id"])
        assert completed["sample_qty"] == 48, (
            f"critical multiplier: ceil(32*1.5)=48, got {completed['sample_qty']}"
        )
        assert completed["releasable_qty"] == 151 - 48


class TestPartQuantityMassBalance:
    def _setup(self):
        stack = create_validated_stack("DEV-MB", claim_months=20)
        qs = create_qualified_supplier("SUP-MB", "MassBalance")
        part = create_part(qs["supplier"]["id"], "PN-MB", description="chip", receive_qty=1000)
        return stack, qs, part

    def test_commit_and_release_move_units_between_buckets(self, api):
        """PRD section 3.5: "From there, `quantity_remaining` holds uncommitted
        stock; recording a component into a lot moves units into
        `quantity_committed` (and removing the component moves them back);
        releasing a lot moves its consumed units from `quantity_committed` into
        `quantity_in_released_lots`".

        Design: Difficulty/compensating_invariant/part_quantity_mass_balance
        """
        stack, _qs, part = self._setup()
        lot1 = create_lot("LT-MB1", stack["dmr"]["id"], stack["protocol"]["id"])
        add_component(lot1["id"], part["id"], quantity_used=100, supplier_lot_number="SL-MB1")
        lot2 = create_lot("LT-MB2", stack["dmr"]["id"], stack["protocol"]["id"])
        add_component(lot2["id"], part["id"], quantity_used=200, supplier_lot_number="SL-MB2")

        reloaded = get_part(part["id"])
        assert reloaded["quantity_received"] == 1000
        assert reloaded["quantity_remaining"] == 700
        assert reloaded["quantity_committed"] == 300
        assert_part_mass_balance(reloaded)

        complete_lot(lot2["id"])
        from test_helpers import record_sterility, create_label, approve_label, print_label, release_lot

        record_sterility(lot2["id"], "PASSED")
        label = create_label(lot2["id"])
        approve_label(label["id"])
        print_label(label["id"])
        release_lot(lot2["id"])

        reloaded = get_part(part["id"])
        assert reloaded["quantity_committed"] == 100
        assert reloaded["quantity_in_released_lots"] == 200
        assert_part_mass_balance(reloaded)

    def test_full_cycle_conserves_component_units(self, api):
        """PRD section 3.5: "recording a component into a lot moves units into
        `quantity_committed` (and removing the component moves them back);
        releasing a lot moves its consumed units from `quantity_committed` into
        `quantity_in_released_lots`; scrapping a lot moves them into
        `quantity_in_scrapped_lots` instead."

        Design: Difficulty/compensating_invariant/part_quantity_mass_balance
        """
        from test_helpers import record_sterility, create_label, approve_label, print_label, release_lot

        stack, _qs, part = self._setup()
        lot1 = create_lot("LT-MB1", stack["dmr"]["id"], stack["protocol"]["id"])
        comp1 = add_component(lot1["id"], part["id"], quantity_used=100, supplier_lot_number="SL-MB1")
        lot2 = create_lot("LT-MB2", stack["dmr"]["id"], stack["protocol"]["id"])
        add_component(lot2["id"], part["id"], quantity_used=200, supplier_lot_number="SL-MB2")

        complete_lot(lot2["id"])
        record_sterility(lot2["id"], "PASSED")
        label = create_label(lot2["id"])
        approve_label(label["id"])
        print_label(label["id"])
        release_lot(lot2["id"])

        resp = api.delete_component(comp1["id"], po())
        assert resp.status_code == 204, (
            f"PRD section 4: the removal of a lot component returns 204 No Content, got {resp.status_code}"
        )
        add_component(lot1["id"], part["id"], quantity_used=50, supplier_lot_number="SL-MB1B")
        validate_success(api.scrap_lot(lot1["id"], qe()))

        reloaded = get_part(part["id"])
        assert reloaded["quantity_received"] == 1000
        assert reloaded["quantity_remaining"] == 750
        assert reloaded["quantity_committed"] == 0
        assert reloaded["quantity_in_released_lots"] == 200
        assert reloaded["quantity_in_scrapped_lots"] == 50
        assert_part_mass_balance(reloaded)


class TestLotCreateExistence:
    def test_lot_create_unknown_dmr_not_found(self, api):
        """PRD section 2.10 step 4: "body-referenced foreign keys — `dmr_id`,
        `line_id`, `supplier_part_id`, `lot_id`, `validation_protocol_id`,
        `source_complaint_id`, `source_ncr_id`, `reason_complaint_id` — are
        resolved (`ERR_NOT_FOUND`)."

        Design: Corner/entities/lot_create_unknown_dmr_not_found
        """
        resp = api.create_lot(
            create_lot_payload(UNKNOWN_UUID, UNKNOWN_UUID, lot_number="LT-NF"), po()
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_shape_failure_precedes_existence(self, api):
        """PRD section 2.10: "a failure at any step masks all later checks" and
        step 3 "integer ranges are respected (quantities strictly positive where
        required ...)" runs before step 4 existence (`ERR_NOT_FOUND`).

        Design: Corner/validations/shape_failure_precedes_existence
        """
        resp = api.create_lot(
            create_lot_payload(UNKNOWN_UUID, UNKNOWN_UUID, lot_number="LT-PE", quantity=0),
            po(),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestComponentConstraints:
    def test_component_commit_exceeding_remaining_rejected(self, api):
        """PRD section 3.6: "`quantity_used` may not exceed the part's
        `quantity_remaining` (`ERR_INSUFFICIENT_PART_QUANTITY`)".

        Design: Corner/endpoints/component_commit_exceeding_remaining_rejected
        """
        stack = create_validated_stack("DEV-IQ")
        qs = create_qualified_supplier("SUP-IQ", "IQ Co")
        part = create_part(qs["supplier"]["id"], "PN-IQ", description="screw", receive_qty=5)
        lot = create_lot("LT-IQ", stack["dmr"]["id"], stack["protocol"]["id"])

        resp = api.create_component(
            lot["id"],
            create_component_payload(part["id"], quantity_used=10, supplier_lot_number="SL-IQ"),
            po(),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PART_QUANTITY)
        reloaded = get_part(part["id"])
        assert reloaded["quantity_committed"] == 0
        page, _meta = validate_paginated(api.list_components(qe(), params={"lot_id": lot["id"]}))
        assert page == []

    def test_component_commit_blocked_when_part_on_hold(self, api):
        """PRD section 3.6: "The referenced part must be `QUALIFIED` and its
        supplier must be `QUALIFIED` (`ERR_PART_NOT_QUALIFIED`)".

        Design: Corner/endpoints/component_commit_blocked_when_part_on_hold
        """
        stack = create_validated_stack("DEV-PH")
        qs = create_qualified_supplier("SUP-PH", "PH Co")
        part = create_part(qs["supplier"]["id"], "PN-PH", description="tube", receive_qty=100)
        ncr = create_ncr(
            ncr_code="NCR-PH", severity="MINOR", description="kink",
            supplier_part_id=part["id"],
        )
        contain_ncr(ncr["id"])
        disposition_ncr(ncr["id"], "RETURN_TO_SUPPLIER", "SUPPLIER")
        held = get_part(part["id"])
        assert held["status"] == "ON_HOLD"

        lot = create_lot("LT-PH", stack["dmr"]["id"], stack["protocol"]["id"])
        resp = api.create_component(
            lot["id"],
            create_component_payload(part["id"], quantity_used=10, supplier_lot_number="SL-PH"),
            po(),
        )
        validate_error(resp, ApiErrorId.ERR_PART_NOT_QUALIFIED)
        page, _meta = validate_paginated(api.list_components(qe(), params={"lot_id": lot["id"]}))
        assert page == []

    def test_component_duplicate_supplier_lot_rejected(self, api):
        """PRD section 3.6: "the triple of lot, part, and supplier lot number
        must be unique (`ERR_DUPLICATE_COMPONENT_LOT`)".

        Design: Corner/endpoints/component_duplicate_supplier_lot_rejected
        """
        stack = create_validated_stack("DEV-DL")
        qs = create_qualified_supplier("SUP-DL", "DL Co")
        part = create_part(qs["supplier"]["id"], "PN-DL", description="clip", receive_qty=100)
        lot = create_lot("LT-DL", stack["dmr"]["id"], stack["protocol"]["id"])
        add_component(lot["id"], part["id"], quantity_used=5, supplier_lot_number="SL-DL")

        resp = api.create_component(
            lot["id"],
            create_component_payload(part["id"], quantity_used=5, supplier_lot_number="SL-DL"),
            po(),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_COMPONENT_LOT)
        reloaded = get_part(part["id"])
        assert reloaded["quantity_committed"] == 5

    def test_component_delete_on_completed_lot_rejected(self, api):
        """PRD section 3.6: "removing a component — permitted only while its lot
        is still `IN_PRODUCTION`, and answered with a 204 No Content on success —
        moves the same units back" — on a `COMPLETED` lot the removal is a state
        failure (`ERR_INVALID_STATE_TRANSITION`).

        Design: Corner/endpoints/component_delete_on_completed_lot_rejected
        """
        stack = create_validated_stack("DEV-CD")
        qs = create_qualified_supplier("SUP-CD", "CD Co")
        part = create_part(qs["supplier"]["id"], "PN-CD", description="plate", receive_qty=100)
        lot = create_lot("LT-CD", stack["dmr"]["id"], stack["protocol"]["id"])
        comp = add_component(lot["id"], part["id"], quantity_used=10, supplier_lot_number="SL-CD")
        complete_lot(lot["id"])

        resp = api.delete_component(comp["id"], po())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        reloaded = get_part(part["id"])
        assert reloaded["quantity_committed"] == 10
