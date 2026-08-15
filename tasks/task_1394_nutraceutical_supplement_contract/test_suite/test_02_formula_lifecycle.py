"""Formula drafting, approval completeness, tier-set shape, revisions, OCC, overage."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_formula,
    create_customer,
    create_formula,
    create_formula_line_payload,
    create_raw_material,
    get_formula,
    list_formula_lines,
    make_brandrep_headers,
    revise_formula,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["production_planner_headers"]
QA = TEST_USERS["qa_manager_headers"]
CHEMIST = TEST_USERS["qa_chemist_headers"]


def _standard_formula(customer_id, material_id, **overrides):
    return create_formula(customer_id, material_id, **overrides)


class TestApprovalCompleteness:
    def test_approve_formula_without_lines_rejected_incomplete(self, api):
        """PRD §3.1: "an empty tier set, a missing line set, or a label-claim-line
        count other than one is rejected with `ERR_FORMULA_INCOMPLETE`, while a
        malformed non-empty tier set is rejected with `ERR_INVALID_TIER_SET`."

        Design: Corner/state_machines/formula_approve_without_lines_rejected_incomplete
        """
        customer = create_customer("Acme")
        formula = create_formula(
            customer["id"],
            lines=[],
            price_tiers=[{"min_qty": 1000, "unit_price_cents": 120}],
        )
        resp = api.approve_formula(formula["id"], {}, QA)
        validate_error(resp, ApiErrorId.ERR_FORMULA_INCOMPLETE)
        assert resp.status_code == 409
        assert get_formula(formula["id"])["status"] == "DRAFT"

    def test_approve_formula_with_two_label_claim_lines_rejected(self, api):
        """PRD §3.1: "exactly one line must carry `is_label_claim_line` set to true"
        and "an empty tier set, a missing line set, or a label-claim-line count
        other than one is rejected with `ERR_FORMULA_INCOMPLETE`, while a malformed
        non-empty tier set is rejected with `ERR_INVALID_TIER_SET`."

        Design: Corner/state_machines/formula_approve_with_two_label_claim_lines_rejected
        """
        customer = create_customer("Acme")
        material = create_raw_material("VitC", "NONE")
        lines = [
            create_formula_line_payload(material["id"]),
            create_formula_line_payload(
                material["id"],
                theoretical_qty_mg_per_unit=100,
                overage_pct=0,
                is_label_claim_line=True,
                label_claim_mg_per_unit=100,
            ),
        ]
        formula = create_formula(customer["id"], lines=lines)
        resp = api.approve_formula(formula["id"], {}, QA)
        validate_error(resp, ApiErrorId.ERR_FORMULA_INCOMPLETE)
        assert resp.status_code == 409

    def test_approve_formula_twice_rejected_formula_state(self, api):
        """PRD §3.1: "The formula must be in `DRAFT` (`ERR_FORMULA_STATE` otherwise)".

        Design: Corner/state_machines/formula_approve_twice_rejected
        """
        customer = create_customer("Acme")
        material = create_raw_material("VitC", "NONE")
        formula = _standard_formula(customer["id"], material["id"])
        approve_formula(formula["id"])
        resp = api.approve_formula(formula["id"], {}, QA)
        validate_error(resp, ApiErrorId.ERR_FORMULA_STATE)
        assert resp.status_code == 409


class TestDraftEditRules:
    def test_update_approved_formula_rejected_despite_current_version(self, api):
        """PRD §3.1: "A `ProductionPlanner` may edit a formula in place only while
        it remains in `DRAFT`; editing an `APPROVED` or `SUPERSEDED` formula is
        rejected with `ERR_FORMULA_STATE`."

        Design: Corner/state_machines/formula_update_after_approve_rejected
        """
        customer = create_customer("Acme")
        material = create_raw_material("VitC", "NONE")
        formula = _standard_formula(customer["id"], material["id"])
        approved = approve_formula(formula["id"])
        current_version = approved["version"]

        resp = api.update_formula(
            formula["id"],
            {"expected_formula_version": current_version, "name": "C500-Renamed"},
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_FORMULA_STATE)
        assert resp.status_code == 409, (
            "state check must reject the edit even though the OCC version matched"
        )
        assert get_formula(formula["id"])["name"] == approved["name"]

    def test_sequential_draft_edits_enforce_stale_version(self, api):
        """PRD §2.8: "An in-place update of a draft formula must carry
        `expected_formula_version` holding the caller's last-observed `version` of
        that formula; if another writer has advanced the formula's version since —
        legitimately superseding the caller's view of the draft, which replaces line
        and tier sets wholesale — the update is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §3.1: "A successful edit increments the formula's `version` by one."

        Design: Corner/cross_cutting_layers/formula_update_stale_version_412
        """
        customer = create_customer("Acme")
        material = create_raw_material("VitC", "NONE")
        formula = _standard_formula(customer["id"], material["id"])
        base_version = formula["version"]

        first = api.update_formula(
            formula["id"],
            {"expected_formula_version": base_version, "name": "C500-v1.1"},
            PLANNER,
        )
        first_data = validate_success(first, 200)
        assert first_data["version"] == base_version + 1, (
            "a successful edit increments the formula's version by one"
        )

        second = api.update_formula(
            formula["id"],
            {"expected_formula_version": base_version, "name": "C500-v1.2"},
            PLANNER,
        )
        validate_error(second, ApiErrorId.ERR_STALE_VERSION)
        assert second.status_code == 412

        assert get_formula(formula["id"])["name"] == "C500-v1.1", (
            "the first write stands after the stale second write is rejected"
        )


class TestTierSetShape:
    def test_malformed_tier_sets_rejected_at_create(self, api):
        """PRD §3.1: "Whenever a non-empty `price_tiers` array is supplied — at
        creation or at update — the first tier's `min_qty` must equal the formula's
        `min_order_qty`, the `min_qty` values must be strictly increasing across the
        array, and the `unit_price_cents` values must be strictly decreasing; a
        malformed non-empty set is rejected with `ERR_INVALID_TIER_SET` (HTTP 400)."

        Design: Corner/validations/invalid_tier_set_rejected_at_create
        """
        customer = create_customer("Acme")
        material = create_raw_material("VitC", "NONE")
        lines = [create_formula_line_payload(material["id"])]

        duplicate_min_qty = api.create_formula(
            customer["id"],
            {
                "name": "BadTiers1",
                "dosage_form": "TABLET",
                "allergen_class": "NONE",
                "min_order_qty": 1000,
                "batch_size_units": 10000,
                "shelf_life_months": 24,
                "overage_basis": "THEORETICAL",
                "lines": lines,
                "price_tiers": [
                    {"min_qty": 1000, "unit_price_cents": 120},
                    {"min_qty": 1000, "unit_price_cents": 100},
                ],
            },
            PLANNER,
        )
        validate_error(duplicate_min_qty, ApiErrorId.ERR_INVALID_TIER_SET)
        assert duplicate_min_qty.status_code == 400

        first_min_not_moq = api.create_formula(
            customer["id"],
            {
                "name": "BadTiers2",
                "dosage_form": "TABLET",
                "allergen_class": "NONE",
                "min_order_qty": 1000,
                "batch_size_units": 10000,
                "shelf_life_months": 24,
                "overage_basis": "THEORETICAL",
                "lines": lines,
                "price_tiers": [{"min_qty": 500, "unit_price_cents": 120}],
            },
            PLANNER,
        )
        validate_error(first_min_not_moq, ApiErrorId.ERR_INVALID_TIER_SET)
        assert first_min_not_moq.status_code == 400


class TestRevisionSupersede:
    def test_approving_revision_supersedes_prior_approved_formula(self, api):
        """PRD §3.1: "A `ProductionPlanner` may request a revision of an `APPROVED`
        formula — revising a formula in any other status is rejected with
        `ERR_FORMULA_STATE` — which produces a brand-new formula in `DRAFT` whose
        `revised_from_formula_id` references the source, with lines and price tiers
        copied across."
        PRD §3.1: "an approval that completes against a formula whose
        `revised_from_formula_id` references a still-`APPROVED` predecessor
        automatically moves that predecessor from `APPROVED` to `SUPERSEDED`."
        PRD §3.3: "the named formula must be `APPROVED` at placement time
        (`ERR_FORMULA_STATE`)."

        Design: Corner/state_machines/formula_revision_supersedes_prior_on_approve
        """
        customer = create_customer("Acme")
        material = create_raw_material("VitC", "NONE")
        f1 = _standard_formula(customer["id"], material["id"])
        approve_formula(f1["id"])

        f2 = revise_formula(f1["id"])
        assert f2["status"] == "DRAFT"
        assert f2["revised_from_formula_id"] == f1["id"]

        approve_formula(f2["id"])
        assert get_formula(f1["id"])["status"] == "SUPERSEDED"
        assert get_formula(f2["id"])["status"] == "APPROVED"

        stale_order = api.create_manufacturing_order(
            {"customer_id": customer["id"], "formula_id": f1["id"], "ordered_qty": 1000},
            make_brandrep_headers(customer["id"]),
        )
        validate_error(stale_order, ApiErrorId.ERR_FORMULA_STATE)
        assert stale_order.status_code == 409

        fresh_order = api.create_manufacturing_order(
            {"customer_id": customer["id"], "formula_id": f2["id"], "ordered_qty": 1000},
            make_brandrep_headers(customer["id"]),
        )
        order_data = validate_success(fresh_order, 201)
        assert order_data["status"] == "PLACED"


class TestPlannedOverageBasis:
    def test_theoretical_basis_plans_overage_from_theoretical_qty(self, api):
        """PRD §3.1: "The overage base is chosen by the formula's `overage_basis`:
        under `THEORETICAL` the base is the line's `theoretical_qty_mg_per_unit`,
        which may already embed formulation excess".
        PRD §3.1: "The per-unit planned quantity is the base multiplied by one plus
        the line's `overage_pct` divided by one hundred, rounded half-up to two
        decimal places; the line's `planned_weigh_qty_mg` is then that rounded
        per-unit figure multiplied by the formula's `batch_size_units`, with the
        product itself rounded half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/overage_theoretical_vs_label_claim_basis
        """
        customer = create_customer("Acme")
        material = create_raw_material("VitC", "NONE")
        formula = create_formula(
            customer["id"],
            material["id"],
            min_order_qty=1000,
            batch_size_units=1000,
            overage_basis="THEORETICAL",
        )
        approve_formula(formula["id"])

        lines = list_formula_lines(formula["id"])
        assert len(lines) == 1
        planned = lines[0]["planned_weigh_qty_mg"]
        # round_half_up(500 * 1.10, 2) = 550.00 per unit; 550.00 x 1000 = 550000.00
        assert planned == 550000.0, (
            f"THEORETICAL basis must plan from theoretical qty, got {planned}"
        )

    def test_label_claim_basis_yields_smaller_planned_qty(self, api):
        """PRD §3.1: "under `LABEL_CLAIM` the base is the line's
        `label_claim_mg_per_unit`, producing a smaller planned quantity whenever
        the theoretical content exceeds the label claim."

        Design: Difficulty/dual_variant_calc/overage_theoretical_vs_label_claim_basis
        """
        customer = create_customer("Acme")
        material = create_raw_material("VitC", "NONE")
        f_theoretical = create_formula(
            customer["id"], material["id"], name="C500-T",
            min_order_qty=1000, batch_size_units=1000, overage_basis="THEORETICAL",
        )
        f_label = create_formula(
            customer["id"], material["id"], name="C500-L",
            min_order_qty=1000, batch_size_units=1000, overage_basis="LABEL_CLAIM",
        )
        approve_formula(f_theoretical["id"])
        approve_formula(f_label["id"])

        planned_theoretical = list_formula_lines(f_theoretical["id"])[0][
            "planned_weigh_qty_mg"
        ]
        planned_label = list_formula_lines(f_label["id"])[0]["planned_weigh_qty_mg"]
        # round_half_up(450 * 1.10, 2) = 495.00 per unit; 495.00 x 1000 = 495000.00
        assert planned_label == 495000.0, (
            f"LABEL_CLAIM basis must plan from the label claim, got {planned_label}"
        )
        assert planned_theoretical == 550000.0
        assert planned_label != planned_theoretical, (
            "identical line numbers must diverge across the two overage bases"
        )


class TestPlannedOverageRoundingOrder:
    def test_overage_rounds_per_unit_before_multiplying(self, api):
        """PRD §3.1: "This rounding order is pinned — round per-unit first, then
        multiply, then round the product".

        Design: Difficulty/combinatorial_formula/overage_nested_rounding_order
        """
        customer = create_customer("Acme")
        material = create_raw_material("BotanicalExt", "NONE")
        formula = create_formula(
            customer["id"],
            material["id"],
            name="B100",
            dosage_form="CAPSULE",
            min_order_qty=100,
            batch_size_units=100,
            shelf_life_months=12,
            overage_basis="THEORETICAL",
            lines=[
                create_formula_line_payload(
                    material["id"],
                    theoretical_qty_mg_per_unit=100.25,
                    overage_pct=10,
                    label_claim_mg_per_unit=100,
                )
            ],
            price_tiers=[{"min_qty": 100, "unit_price_cents": 50}],
        )
        approve_formula(formula["id"])

        planned = list_formula_lines(formula["id"])[0]["planned_weigh_qty_mg"]
        # Pinned order: round_half_up(100.25 * 1.10, 2) = 110.28, then 110.28 * 100.
        assert planned == 11028.0, (
            f"per-unit-first rounding must yield 11028.00, got {planned}"
        )
        assert planned != 11027.5, (
            "multiply-first reading (100.25 x 100 x 1.10 = 11027.50) is rejected"
        )

    def test_overage_rounding_order_second_datapoint(self, api):
        """PRD §3.1: "The per-unit planned quantity is the base multiplied by one
        plus the line's `overage_pct` divided by one hundred, rounded half-up to two
        decimal places; the line's `planned_weigh_qty_mg` is then that rounded
        per-unit figure multiplied by the formula's `batch_size_units`, with the
        product itself rounded half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/overage_nested_rounding_order
        """
        customer = create_customer("Acme")
        material = create_raw_material("BotanicalExt", "NONE")
        formula = create_formula(
            customer["id"],
            material["id"],
            name="B101",
            dosage_form="CAPSULE",
            min_order_qty=100,
            batch_size_units=100,
            shelf_life_months=12,
            overage_basis="THEORETICAL",
            lines=[
                create_formula_line_payload(
                    material["id"],
                    theoretical_qty_mg_per_unit=100.75,
                    overage_pct=10,
                    label_claim_mg_per_unit=100,
                )
            ],
            price_tiers=[{"min_qty": 100, "unit_price_cents": 50}],
        )
        approve_formula(formula["id"])

        planned = list_formula_lines(formula["id"])[0]["planned_weigh_qty_mg"]
        # Pinned order: round_half_up(100.75 * 1.10, 2) = 110.83, then 110.83 * 100.
        assert planned == 11083.0, (
            f"per-unit-first rounding must yield 11083.00, got {planned}"
        )
        assert planned != 11082.5, (
            "multiply-first reading (100.75 x 100 x 1.10 = 11082.50) is rejected"
        )
