"""Ingredients, lots, and supplier cascades: enum membership, computed
remaining_kg, lot QC gating, and the suspension cascade onto lots and
production (PRD §2.7, §2.8, §3.2, §3.4)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, create_ingredient_payload, create_supplier_payload,
    create_ingredient_lot_payload,
    create_ingredient, create_qualified_supplier, create_ingredient_lot,
    create_qc_passed_lot, create_active_formula,
    create_planned_batch, set_clock,
)


class TestIngredientEnum:
    def test_invalid_category_rejected(self, api, users):
        """PRD §3.2: ingredient categories "come from a closed category
        vocabulary: `DAIRY_BASE`, `VEGETABLE_OIL`, `VITAMIN_PREMIX`,
        `MINERAL_PREMIX`, `PROBIOTIC`, `CARBOHYDRATE`, `NUCLEOTIDE`, `OTHER`."
        PRD §2.8 lists "enum membership" among the field shape rules; the
        catalogue's enum error is `ERR_INVALID_ENUM` (HTTP 422, PRD §5).

        Design: Corner/entities/invalid_enum_value_returns_error
        """
        res = api.create_ingredient(
            create_ingredient_payload(
                ingredient_code="BAD-ENUM", category="INVALID_CATEGORY"),
            users["qm"]["headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_ENUM)


class TestIngredientLotComputedFields:
    def test_remaining_kg_initialized_to_quantity(self, api, users):
        """PRD §3.2: "The system tracks `remaining_kg` separately from
        `quantity_kg`: `remaining_kg` starts equal to `quantity_kg`, is
        decremented as production consumes the lot, and is restored if a
        consuming batch is later rejected." and "Lots begin in `PENDING_QC`."

        Design: Corner/entities/ingredient_lot_computed_remaining_kg
        """
        supplier = validate_success(api.create_supplier(
            create_supplier_payload(supplier_code="SUP-COMP"),
            users["qm"]["headers"]), 201)
        ing = create_ingredient(users, "ING-COMP", "Computed Ingredient",
                                "DAIRY_BASE", "HIGH_RISK", "REFRIGERATED")
        lot = validate_success(api.create_ingredient_lot(
            create_ingredient_lot_payload(
                ingredient_id=ing["id"], supplier_id=supplier["id"],
                lot_number="LOT-COMP-001", quantity_kg=250.500),
            users["scp"]["headers"]), 201)
        assert lot["remaining_kg"] == 250.500, (
            f"remaining_kg must initialize to quantity_kg, got {lot['remaining_kg']}")
        assert lot["qc_status"] == "PENDING_QC"


class TestLotQcGating:
    def test_qc_pass_rejected_for_expired_lot(self, api, users):
        """PRD §3.2: the QC-pass transition "is refused with `ERR_LOT_EXPIRED`
        (HTTP 422) if the lot's `expiry_date` is not strictly after the current
        logical timestamp".

        Design: Corner/errors/err_lot_expired_on_qc_pass
        """
        set_clock(users, "2026-08-01T00:00:00Z")
        supplier = create_qualified_supplier(
            users, "SUP-EXPLOT", ["DAIRY_BASE"], score=90.00)
        ing = create_ingredient(users, "WPC-EXPLOT", "WPC Expired Lot",
                                "DAIRY_BASE", "HIGH_RISK", "REFRIGERATED")
        lot = create_ingredient_lot(
            users, ing["id"], supplier["id"], "LOT-EXP-OLD",
            quantity_kg=100.000,
            received_date="2025-01-15T00:00:00Z",
            expiry_date="2026-01-15T00:00:00Z")
        res = api.qc_pass_lot(lot["id"], users["qa"]["headers"])
        validate_error(res, ApiErrorId.ERR_LOT_EXPIRED)

    def test_qc_pass_rejected_when_supplier_pending_audit(self, api, users):
        """PRD §3.2: the QC-pass transition "is refused with
        `ERR_SUPPLIER_NOT_QUALIFIED` (HTTP 422) if the lot's supplier is not
        currently `QUALIFIED`" — a PENDING_AUDIT supplier is not QUALIFIED.

        Design: Difficulty/cross_entity_state_dependency/ingredient_lot_qc_pass_requires_supplier_qualified
        """
        set_clock(users)
        supplier = validate_success(api.create_supplier(
            create_supplier_payload(supplier_code="SUP-PEND"),
            users["qm"]["headers"]), 201)
        ing = create_ingredient(users, "WPC-PEND", "WPC Pending Test",
                                "DAIRY_BASE", "HIGH_RISK", "REFRIGERATED")
        lot = create_ingredient_lot(
            users, ing["id"], supplier["id"], "LOT-PEND-001",
            quantity_kg=100.000)
        res = api.qc_pass_lot(lot["id"], users["qa"]["headers"])
        validate_error(res, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIED)

    def test_qc_pass_rejected_when_supplier_suspended(self, api, users):
        """PRD §3.2: the QC-pass transition "is refused with
        `ERR_SUPPLIER_NOT_QUALIFIED` (HTTP 422) if the lot's supplier is not
        currently `QUALIFIED`" — a SUSPENDED supplier is not QUALIFIED.
        Suspension itself is defined in PRD §3.2: "A `QUALITY_ANALYST` may
        suspend a `QUALIFIED` supplier by providing a `reason`".

        Design: Difficulty/cross_entity_state_dependency/ingredient_lot_qc_pass_requires_supplier_qualified
        """
        set_clock(users)
        supplier = create_qualified_supplier(
            users, "SUP-SUSP", ["DAIRY_BASE"], score=90.00)
        ing = create_ingredient(users, "WPC-SUSP", "WPC Suspended Test",
                                "DAIRY_BASE", "HIGH_RISK", "REFRIGERATED")
        lot = create_ingredient_lot(
            users, ing["id"], supplier["id"], "LOT-SUSP-001",
            quantity_kg=100.000)
        validate_success(api.suspend_supplier(
            supplier["id"], {"reason": "Environmental swab failure"},
            users["qa"]["headers"]))
        res = api.qc_pass_lot(lot["id"], users["qa"]["headers"])
        validate_error(res, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIED)


class TestSupplierSuspensionCascade:
    def test_suspend_quarantines_qc_passed_lots(self, api, users):
        """PRD §2.7: "Suspending a `QUALIFIED` supplier flips every lot from
        that supplier currently in `QC_PASSED` to `QUARANTINED`." and "the
        cascade happens immediately and atomically, and every affected resource
        has its `version` incremented and `updated_at` refreshed."

        Design: Difficulty/transitive_cascade/supplier_suspend_cascades_to_lots_then_blocks_batch
        """
        set_clock(users)
        supplier = create_qualified_supplier(
            users, "SUP-CASC", ["DAIRY_BASE"], score=90.00)
        ing = create_ingredient(users, "ING-CASC", "Cascade Ingredient",
                                "DAIRY_BASE", "HIGH_RISK", "REFRIGERATED")
        lot = create_qc_passed_lot(
            users, ing["id"], supplier["id"], "LOT-CASC-001",
            quantity_kg=200.000)
        suspended = validate_success(api.suspend_supplier(
            supplier["id"], {"reason": "Pathogen found in facility environmental swab"},
            users["qa"]["headers"]))
        assert suspended["qualification_status"] == "SUSPENDED"
        lot_after = validate_success(api.get_ingredient_lot(
            lot["id"], users["qa"]["headers"]))
        assert lot_after["qc_status"] == "QUARANTINED", (
            f"Lot must be QUARANTINED after supplier suspension, "
            f"got {lot_after['qc_status']}")
        assert lot_after["version"] == lot["version"] + 1, (
            "Cascade must increment the affected lot's version")

    def test_quarantined_lot_blocks_production_start(self, api, users):
        """PRD §3.4: starting production enforces "that every ingredient lot
        the recipe will consume currently has `qc_status` equal to `QC_PASSED`
        (else `ERR_LOT_NOT_QC_PASSED`, HTTP 422)". Once the supplier suspension
        cascade (PRD §2.7) has quarantined the only eligible lots, the check
        fires. PRD §2.8: "Validation is applied in a fixed priority order
        across all endpoints. ... then segregation-of-duties and domain safety
        rules (lot QC, supplier qualification, validation currency, lot expiry,
        escalation warrant, batch test outcome)" — lot QC precedes supplier
        qualification, so `ERR_LOT_NOT_QC_PASSED` surfaces.

        Design: Difficulty/transitive_cascade/supplier_suspend_cascades_to_lots_then_blocks_batch
        """
        set_clock(users)
        scenario = create_active_formula(users, formula_code="IF-CASC-1")
        supplier = create_qualified_supplier(
            users, "SUP-CASC2", ["DAIRY_BASE", "CARBOHYDRATE"], score=90.00)
        create_qc_passed_lot(users, scenario["ing_a"]["id"], supplier["id"],
                             "LOT-CASC2-A", quantity_kg=500.000)
        create_qc_passed_lot(users, scenario["ing_b"]["id"], supplier["id"],
                             "LOT-CASC2-B", quantity_kg=300.000)
        validate_success(api.suspend_supplier(
            supplier["id"], {"reason": "Facility sanitation failure"},
            users["qa"]["headers"]))
        batch = create_planned_batch(users, scenario["formula"]["id"])
        res = api.start_production(batch["id"], users["ps"]["headers"])
        validate_error(res, ApiErrorId.ERR_LOT_NOT_QC_PASSED)
