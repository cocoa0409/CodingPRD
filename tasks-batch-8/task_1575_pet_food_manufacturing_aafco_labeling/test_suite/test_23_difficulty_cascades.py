"""Difficulty: transitive cascades — recall initiation (depth 3) and pairing
revocation demotion (depth 2) (PRD §3.2, §3.8)."""
from test_helpers import (
    add_ingredient_line,
    create_brand_owner,
    create_formula,
    create_ingredient,
    create_pairing,
    create_supplier,
    get_batch,
    get_brand,
    get_formula,
    get_lot_by_id,
    get_supplier,
    initiate_recall,
    setup_batch_in_state,
    validate_success,
)


class TestRecallInitiationThreeHopCascade:
    def test_recall_recalls_in_scope_batch_and_lots(self, api):
        """PRD §3.8: "Otherwise initiation cascades: every in-scope batch in
        `COMPLETED` or `ON_HOLD` moves to `RECALLED`; every lot of an in-scope
        batch in `ACTIVE`, `QUARANTINED`, or `RELEASED` moves to `RECALLED`; the
        recall's `affected_lot_count` records how many lots moved"

        Design: Difficulty/transitive_cascade/recall_initiation_three_hop_cascade
        """
        ctx = setup_batch_in_state("COMPLETED", planned_kg=500.0, line_id="LINE-B",
                                   with_lot=True)
        recall = initiate_recall(
            ctx["formula"]["id"], [ctx["batch"]["id"]],
            recall_class="CLASS_I", reason="Salmonella confirmed",
        )
        assert recall["affected_lot_count"] == 1
        assert get_batch(ctx["batch"]["id"])["status"] == "RECALLED"
        lot = get_lot_by_id(ctx["batch"]["id"], ctx["lot"]["id"])
        assert lot["status"] == "RECALLED"

    def test_recall_sets_formula_flag_and_brand_count(self, api):
        """PRD §3.8: "the formula's `open_recall_flag` is set true; and the
        brand's `open_recall_count` increases by one."
        PRD §2.8: "Recall activity maintains the formula's `open_recall_flag` and
        the brand owner's `open_recall_count`."

        Design: Difficulty/transitive_cascade/recall_initiation_three_hop_cascade
        """
        ctx = setup_batch_in_state("COMPLETED", planned_kg=500.0, line_id="LINE-B",
                                   with_lot=True)
        assert get_formula(ctx["formula"]["id"])["open_recall_flag"] is False
        assert get_brand(ctx["brand"]["id"])["open_recall_count"] == 0

        initiate_recall(
            ctx["formula"]["id"], [ctx["batch"]["id"]],
            recall_class="CLASS_I", reason="Salmonella confirmed",
        )
        assert get_formula(ctx["formula"]["id"])["open_recall_flag"] is True
        assert get_brand(ctx["brand"]["id"])["open_recall_count"] == 1


class TestPairingRevocationTwoHopFormulaDemotion:
    def _setup_uncovered_review_formula(self, api):
        """APPROVED pairing is the sole coverage for the formula's only
        ingredient; the formula sits in NUTRIENT_REVIEW at revision 1."""
        brand = create_brand_owner()
        supplier = create_supplier(approve=True)
        ingredient = create_ingredient()
        pairing = create_pairing(supplier["id"], ingredient["id"], approve=True)
        formula = create_formula(brand["id"])
        add_ingredient_line(formula["id"], ingredient["id"])
        from test_helpers import TEST_USERS

        submitted = validate_success(
            api.submit_nutrient_review(
                formula["id"], TEST_USERS["formulation_scientist_headers"]
            )
        )
        assert submitted["status"] == "NUTRIENT_REVIEW"
        assert submitted["revision_number"] == 1
        return brand, supplier, ingredient, pairing, submitted

    def test_revoke_recomputes_supplier_approved_count(self, api, qa_approver_headers):
        """PRD §3.2: "A `QAApprover` may revoke a pairing currently in `APPROVED`,
        moving it to `REVOKED`; the decision stamps `decided_by` and
        `decided_at`, recomputes the supplier's `approved_ingredient_count`"

        Design: Difficulty/transitive_cascade/pairing_revocation_two_hop_formula_demotion
        """
        _brand, supplier, _ingredient, pairing, _formula = (
            self._setup_uncovered_review_formula(api)
        )
        assert get_supplier(supplier["id"])["approved_ingredient_count"] == 1

        revoked = validate_success(api.revoke_pairing(pairing["id"], qa_approver_headers))
        assert revoked["approval_state"] == "REVOKED"
        assert get_supplier(supplier["id"])["approved_ingredient_count"] == 0

    def test_revoke_demotes_uncovered_nutrient_review_formula(self, api, qa_approver_headers):
        """PRD §3.2: "every formula sitting in `NUTRIENT_REVIEW` that includes
        the revoked ingredient and is now left without any `APPROVED` pairing
        covering that ingredient is pushed back to `DRAFT`, with its
        `revision_number` incremented by one and its `version` advanced."

        Design: Difficulty/transitive_cascade/pairing_revocation_two_hop_formula_demotion
        """
        _brand, _supplier, _ingredient, pairing, formula = (
            self._setup_uncovered_review_formula(api)
        )
        validate_success(api.revoke_pairing(pairing["id"], qa_approver_headers))
        demoted = get_formula(formula["id"])
        assert demoted["status"] == "DRAFT"
        assert demoted["revision_number"] == 2
