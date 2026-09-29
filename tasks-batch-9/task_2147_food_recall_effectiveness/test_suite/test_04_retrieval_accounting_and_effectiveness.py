"""Retrieval accounting, the two effectiveness bases and disposition custody."""
from test_helpers import (
    ApiErrorId,
    RecallCase,
    assert_disposition_order,
    assert_effectiveness_payload,
    assert_retrieval_receipt,
    case_in_retrieval_accounting,
    case_with_confirmed_shipment,
    classified_case,
    create_retrieval_receipt_payload,
    make_coordinator_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = make_coordinator_headers("coord-1")


def _usda_case_with_five_hundred_units_in_custody():
    """USDA recall in retrieval accounting with one VERIFIED 500-unit receipt."""
    case = case_in_retrieval_accounting(agency="USDA", quantity_shipped=1000)
    receipt = case.file_receipt(case.c1_id, quantity_returned=500)
    case.verify_receipt(receipt["id"], "VERIFY")
    return case


def test_cumulative_receipt_quantity_may_not_exceed_reconciled_shipped_units(api):
    """PRD §3.7: "And the arithmetic must not exceed what was shipped: take the cumulative sum of `quantity_returned`, `quantity_destroyed_onsite`, `quantity_held_segregated` and `quantity_unrecoverable` across that consignee's existing receipts in `REPORTED` or `VERIFIED` — receipts in `DISPUTED` are excluded from that running total — add the same four-way sum for the incoming receipt, and the result must not exceed the sum of `effective_quantity` over that consignee's `CONFIRMED` and `CORRECTED` distribution records on this recall."
    PRD §3.7: "Exceeding it is `ERR_QUANTITY_EXCEEDS_SHIPPED`."

    Design: Corner/validations/cumulative_receipt_quantity_over_reconciled_shipped_returns_fiscal_error
    """
    case = case_with_confirmed_shipment(quantity_shipped=600)
    case.notify(case.c1_id, method="EMAIL")
    first_receipt = case.file_receipt(case.c1_id, quantity_returned=400)

    response = api.create_retrieval_receipt(
        case.recall_id,
        create_retrieval_receipt_payload(case.c1_id, quantity_returned=300),
        case.officer,
    )
    validate_error(response, ApiErrorId.ERR_QUANTITY_EXCEEDS_SHIPPED.value)
    assert response.status_code == 422

    rows, meta = validate_paginated(
        api.list_consignee_retrieval_receipts(case.c1_id, COORDINATOR)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first_receipt["id"]
    assert rows[0]["accounted_units"] == 400
    assert rows[0]["status"] == "REPORTED"
    assert case.read_recall()["accounted_units"] == 0


def test_effectiveness_review_opens_at_exactly_ninety_five_percent(api):
    """PRD §3.7: "The recall automatically advances `RETRIEVAL_ACCOUNTING → EFFECTIVENESS_REVIEW` as soon as `official_effectiveness_pct` reaches 95.00 or more; that check is evaluated at the end of a receipt verification and during a checkpoint, and — importantly — it is *not* re-evaluated when a termination decision is made, so a denied termination leaves the recall parked in `RETRIEVAL_ACCOUNTING` until the next verification or checkpoint."
    PRD §3.7: "Then `quantity_effectiveness_pct` is 0.00 when `shipped_units` is zero; otherwise it is the smaller of `accounted_units` and `shipped_units`, divided by `shipped_units`, multiplied by 100, rounded half up to two decimal places."

    Design: Corner/cross_cutting_complexity_layers/quantity_effectiveness_target_fires_at_exactly_ninety_five_percent
    """
    case = case_in_retrieval_accounting(agency="USDA", quantity_shipped=1000)
    receipt_a = case.file_receipt(case.c1_id, quantity_returned=949)
    receipt_b = case.file_receipt(case.c1_id, quantity_returned=1)

    case.verify_receipt(receipt_a["id"], "VERIFY")
    below = case.read_recall()
    assert below["quantity_effectiveness_pct"] == 94.90
    assert below["status"] == "RETRIEVAL_ACCOUNTING"

    case.verify_receipt(receipt_b["id"], "VERIFY")
    at_edge = case.read_recall()
    assert at_edge["quantity_effectiveness_pct"] == 95.00
    assert at_edge["status"] == "EFFECTIVENESS_REVIEW"
    assert at_edge["accounted_units"] == 950
    assert at_edge["units_awaiting_disposition"] == 950

    reports = case.status_reports()
    final_reports = [r for r in reports if r["report_kind"] == "FINAL_EFFECTIVENESS"]
    assert len(final_reports) == 1


def test_executing_a_proposed_order_before_authorization_is_rejected(api):
    """PRD §3.7: "Any authorize, execute or verify against an order in the wrong `status` is `ERR_INVALID_DISPOSITION_STATE`."
    PRD §3.7: "The firm then executes, advancing `AUTHORIZED → EXECUTED`, supplying a `certificate_reference` that must be a non-empty string (an empty or missing one is `ERR_INVALID_REQUEST`), stamping `executed_at` from the clock, and moving the order's `quantity` out of `units_awaiting_disposition` and into `units_pending_verification`."

    Design: Corner/state_machines/disposition_execute_before_authorize_returns_invalid_disposition_state
    """
    case = _usda_case_with_five_hundred_units_in_custody()
    order = case.propose_disposition(
        400, method="REWORK", facility_name="Northvale Rework Line 2"
    )

    response = api.execute_disposition_order(
        order["id"], {"certificate_reference": "COD-00001"}, case.officer
    )
    validate_error(response, ApiErrorId.ERR_INVALID_DISPOSITION_STATE.value)
    assert response.status_code == 409

    rows, _ = validate_paginated(
        api.list_disposition_orders(case.recall_id, COORDINATOR)
    )
    assert rows[0]["status"] == "PROPOSED"
    assert rows[0]["certificate_reference"] is None
    assert rows[0]["executed_at"] is None

    recall = case.read_recall()
    assert recall["units_awaiting_disposition"] == 500
    assert recall["units_pending_verification"] == 0


def test_rejecting_an_executed_disposition_restores_the_custody_ledger(api):
    """PRD §3.7: "Finally a `FieldInvestigator` supplies a `decision`: `VERIFY` advances `EXECUTED → VERIFIED`, stamps `witness_user_id`, and moves the `quantity` out of `units_pending_verification` and into `units_disposed_verified`; `REJECT` sends the order back along `EXECUTED → AUTHORIZED`, increments `reject_count`, clears both `certificate_reference` and `executed_at` back to null, and moves the `quantity` out of `units_pending_verification` and back into `units_awaiting_disposition`, so an execute-then-reject pair restores the custody ledger exactly."
    PRD §2.8: "A third, narrower compensation applies to custody: executing a disposition order and then having that execution rejected restores the units awaiting disposition exactly."

    Design: Corner/state_machines/disposition_verify_reject_returns_units_to_awaiting_disposition
    """
    case = _usda_case_with_five_hundred_units_in_custody()
    order = case.propose_disposition(400)
    case.authorize_disposition(order["id"])
    case.execute_disposition(order["id"], certificate_reference="COD-00042")

    mid = case.read_recall()
    assert mid["units_awaiting_disposition"] == 100
    assert mid["units_pending_verification"] == 400

    rejected = case.verify_disposition(
        order["id"], "REJECT", verification_note="Certificate does not match the lot."
    )
    assert_disposition_order(rejected)
    assert rejected["status"] == "AUTHORIZED"
    assert rejected["reject_count"] == 1
    assert rejected["certificate_reference"] is None
    assert rejected["executed_at"] is None

    after = case.read_recall()
    assert after["units_awaiting_disposition"] == 500
    assert after["units_pending_verification"] == 0
    assert after["units_disposed_verified"] == 0


def test_firm_officer_may_not_authorize_a_disposition_order(api):
    """PRD §2.1: "If both headers are well formed but the acting role does not appear in the authorized-role list published for the endpoint in §4, the rejection is `ERR_ROLE_NOT_PERMITTED` with HTTP 403."
    PRD §3.7: "A `RecallCoordinator` authorizes it, advancing `PROPOSED → AUTHORIZED` and stamping `authorized_by_user_id`; authorization requires the recall to be in `RETRIEVAL_ACCOUNTING` or `EFFECTIVENESS_REVIEW`, and it requires the order's `quantity` to be no greater than the recall's `units_awaiting_disposition` at that moment — an order for more product than the firm actually holds is refused with `ERR_DISPOSITION_EXCEEDS_ACCOUNTED_UNITS`."

    Design: Corner/rbac/firm_officer_cannot_authorize_a_disposition_order
    """
    case = _usda_case_with_five_hundred_units_in_custody()
    order = case.propose_disposition(200)

    response = api.authorize_disposition_order(order["id"], case.officer)
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)
    assert response.status_code == 403

    rows, _ = validate_paginated(
        api.list_disposition_orders(case.recall_id, COORDINATOR)
    )
    assert rows[0]["status"] == "PROPOSED"
    assert rows[0]["authorized_by_user_id"] is None
    assert case.read_recall()["units_awaiting_disposition"] == 500


class TestEffectivenessBasesDiverge:
    """One recall, two measurement philosophies, two different numbers."""

    @staticmethod
    def _fda_case_with_two_consignees_and_one_verified_receipt():
        case = classified_case(agency="FDA", clock="2026-09-01T00:00:00Z")
        c1 = case.add_consignee("Metro Distributors", "DISTRIBUTOR")
        c2 = case.add_consignee("Harbor Grocery", "RETAILER")
        case.confirmed_shipment(c1["id"], 600)
        case.confirmed_shipment(c2["id"], 400, ship_date="2026-08-21T00:00:00Z")
        case.notify_delivered_and_acknowledged(c1["id"])
        case.notify_delivered_and_acknowledged(c2["id"])
        receipt = case.file_receipt(
            c1["id"], quantity_returned=500, quantity_destroyed_onsite=50,
            quantity_unrecoverable=50,
        )
        case.verify_receipt(receipt["id"], "VERIFY")
        case.c1_id = c1["id"]
        case.c2_id = c2["id"]
        return case

    def test_contact_and_quantity_bases_report_different_numbers(self, api):
        """PRD §3.7: "Then `contact_effectiveness_pct` is 100.00 when `required_sample_size` is zero; otherwise it is the smaller of `responded_count` and `required_sample_size`, divided by `required_sample_size`, multiplied by 100, rounded half up to two decimal places."
        PRD §3.7: "Then `quantity_effectiveness_pct` is 0.00 when `shipped_units` is zero; otherwise it is the smaller of `accounted_units` and `shipped_units`, divided by `shipped_units`, multiplied by 100, rounded half up to two decimal places."
        PRD §3.7: "The receipt's `accounted_units` is the sum of exactly the first three of those; `quantity_unrecoverable` is deliberately excluded, because product that reached consumers is precisely what the recall failed to capture."

        Design: Difficulty/dual_variant_calc/effectiveness_contact_basis_diverges_from_quantity_basis_on_one_recall
        """
        case = self._fda_case_with_two_consignees_and_one_verified_receipt()
        payload = validate_success(api.get_effectiveness(case.recall_id, COORDINATOR))
        assert_effectiveness_payload(payload)
        assert payload["contact_effectiveness_pct"] == 100.00
        assert payload["quantity_effectiveness_pct"] == 55.00
        assert payload["contact_effectiveness_pct"] != payload["quantity_effectiveness_pct"]

    def test_the_owning_agency_selects_which_basis_is_official(self, api):
        """PRD §3.7: "When `agency` is `FDA` the `official_basis` is `CONTACT` and `official_effectiveness_pct` is `contact_effectiveness_pct`; when `agency` is `USDA` the `official_basis` is `QUANTITY` and `official_effectiveness_pct` is `quantity_effectiveness_pct`."
        PRD §3.7: "`shipped_units` is the sum of `effective_quantity` over this recall's distribution records in `CONFIRMED` or `CORRECTED` — records in `DECLARED`, `DISPUTED` or `VOIDED` contribute nothing — and `accounted_units` is the sum of `accounted_units` over this recall's receipts in `VERIFIED`, with `REPORTED` and `DISPUTED` receipts contributing nothing."

        Design: Difficulty/dual_variant_calc/effectiveness_contact_basis_diverges_from_quantity_basis_on_one_recall
        """
        case = self._fda_case_with_two_consignees_and_one_verified_receipt()
        payload = validate_success(api.get_effectiveness(case.recall_id, COORDINATOR))
        assert payload["official_basis"] == "CONTACT"
        assert payload["official_effectiveness_pct"] == 100.00
        assert payload["required_sample_size"] == 2
        assert payload["responded_count"] == 2
        assert payload["shipped_units"] == 1000
        assert payload["accounted_units"] == 550


class TestReceiptVerificationCascade:
    """Verifying a receipt raises accounted units, which trips the target,
    which opens effectiveness review and mints the final report."""

    @staticmethod
    def _usda_case_with_a_reported_receipt():
        case = case_in_retrieval_accounting(
            agency="USDA", quantity_shipped=1000, clock="2026-09-01T00:00:00Z"
        )
        case.pending_receipt = case.file_receipt(
            case.c1_id, quantity_returned=960, quantity_unrecoverable=40
        )
        set_clock("2026-09-05T00:00:00Z")
        return case

    def test_verification_raises_accounted_units_and_opens_review(self, api):
        """PRD §3.7: "Hop one stamps `verified_by_user_id`, re-sums the recall's `accounted_units` over its receipts in `VERIFIED`, and adds this receipt's `quantity_returned` plus its `quantity_held_segregated` to the recall's `units_awaiting_disposition` — the two buckets of product that are still physically somewhere and still need a disposition decision, as distinct from product already destroyed at the consignee."
        PRD §3.7: "A `decision` of `VERIFY` advances `REPORTED → VERIFIED` and opens **Cascade B**."
        PRD §3.7: "The recall automatically advances `RETRIEVAL_ACCOUNTING → EFFECTIVENESS_REVIEW` as soon as `official_effectiveness_pct` reaches 95.00 or more; that check is evaluated at the end of a receipt verification and during a checkpoint, and — importantly — it is *not* re-evaluated when a termination decision is made, so a denied termination leaves the recall parked in `RETRIEVAL_ACCOUNTING` until the next verification or checkpoint."

        Design: Difficulty/transitive_cascade/receipt_verify_cascade_enters_review_and_mints_final_effectiveness_report
        """
        case = self._usda_case_with_a_reported_receipt()
        assert case.pending_receipt["accounted_units"] == 960
        assert_retrieval_receipt(case.pending_receipt)

        verified = case.verify_receipt(
            case.pending_receipt["id"], "VERIFY", verification_note="Counted on site."
        )
        assert verified["status"] == "VERIFIED"

        recall = case.read_recall()
        assert recall["accounted_units"] == 960
        assert recall["quantity_effectiveness_pct"] == 96.00
        assert recall["official_effectiveness_pct"] == 96.00
        assert recall["contact_effectiveness_pct"] == 100.00
        assert recall["status"] == "EFFECTIVENESS_REVIEW"
        assert recall["units_awaiting_disposition"] == 960

    def test_entering_review_mints_the_final_effectiveness_report(self, api):
        """PRD §3.7: "Hop two, if the effectiveness threshold is now met, advances the recall `RETRIEVAL_ACCOUNTING → EFFECTIVENESS_REVIEW`, and hop three follows from that entry: every consignee of this recall whose `response_state` is `AWAITING` or `NO_RESPONSE` has `closed_without_response` set to true, and the server mints a status report with `report_kind` `FINAL_EFFECTIVENESS`, a `period_index` one greater than the largest existing index on the recall, `period_start` at the current logical instant, `period_end` and `due_at` three days later, and `status` `PENDING`."

        Design: Difficulty/transitive_cascade/receipt_verify_cascade_enters_review_and_mints_final_effectiveness_report
        """
        case = self._usda_case_with_a_reported_receipt()
        case.verify_receipt(case.pending_receipt["id"], "VERIFY")

        reports = case.status_reports()
        final_reports = [r for r in reports if r["report_kind"] == "FINAL_EFFECTIVENESS"]
        assert len(final_reports) == 1
        final_report = final_reports[0]
        assert final_report["period_index"] == 2
        assert final_report["status"] == "PENDING"
        assert final_report["due_at"] == "2026-09-08T00:00:00.000Z"


class TestEmptyCollectionBoundaries:
    """An empty effectiveness sample and zero shipped units resolve opposite
    ways."""

    @staticmethod
    def _empty_usda_class_three_case():
        case = RecallCase(
            agency="USDA", product_description="Ground beef 5lb",
            initiation_type="AGENCY_REQUESTED", lot_codes=["L-42B"],
        )
        evaluation = case.file_evaluation(
            probability_of_adverse_health="LOW", severity_tier=1,
            exposure_population=0, vulnerable_population=False,
            evidence_strength="CONFIRMED",
        )
        case.preliminary_score = case.submit_evaluation(evaluation["id"])["hazard_score"]
        case.decide_evaluation(evaluation["id"], "RATIFY")
        case.classify("CLASS_III")
        return case

    def test_an_empty_effectiveness_sample_scores_one_hundred(self, api):
        """PRD §3.7: "Then `contact_effectiveness_pct` is 100.00 when `required_sample_size` is zero; otherwise it is the smaller of `responded_count` and `required_sample_size`, divided by `required_sample_size`, multiplied by 100, rounded half up to two decimal places."
        PRD §3.3: "The `required_sample_size` is zero when there are no eligible consignees at all; otherwise it is the eligible count multiplied by the level percentage — 100 percent for level `A`, 50 percent for level `B`, 10 percent for level `C` and 2 percent for level `D` — rounded up to a whole number, and then floored at 1 so that a non-empty eligible set always demands at least one response."

        Design: Difficulty/boundary_precision_check/empty_sample_and_zero_shipped_units_resolve_to_opposite_percentages
        """
        case = self._empty_usda_class_three_case()
        assert case.preliminary_score == 8.40

        payload = validate_success(api.get_effectiveness(case.recall_id, COORDINATOR))
        assert payload["required_sample_size"] == 0
        assert payload["contact_effectiveness_pct"] == 100.00
        assert payload["eligible_consignee_count"] == 0
        assert payload["effectiveness_check_level"] == "D"
        assert payload["sample_tier_scope"] == 1

    def test_zero_shipped_units_scores_zero_and_usda_makes_it_official(self, api):
        """PRD §3.7: "Both numerators are clamped by that "smaller of" so neither percentage can ever exceed 100.00, and the two empty-set boundaries deliberately disagree: an empty required sample scores 100.00 while zero shipped units scores 0.00."
        PRD §3.7: "When `agency` is `FDA` the `official_basis` is `CONTACT` and `official_effectiveness_pct` is `contact_effectiveness_pct`; when `agency` is `USDA` the `official_basis` is `QUANTITY` and `official_effectiveness_pct` is `quantity_effectiveness_pct`."

        Design: Difficulty/boundary_precision_check/empty_sample_and_zero_shipped_units_resolve_to_opposite_percentages
        """
        case = self._empty_usda_class_three_case()
        payload = validate_success(api.get_effectiveness(case.recall_id, COORDINATOR))
        assert_effectiveness_payload(payload)
        assert payload["shipped_units"] == 0
        assert payload["quantity_effectiveness_pct"] == 0.00
        assert payload["official_basis"] == "QUANTITY"
        assert payload["official_effectiveness_pct"] == 0.00


class TestDispositionBoundedByCustody:
    """Authorization is bounded by what sibling receipts moved into custody."""

    def test_authorizing_more_than_the_units_in_custody_is_refused(self, api):
        """PRD §3.7: "A `RecallCoordinator` authorizes it, advancing `PROPOSED → AUTHORIZED` and stamping `authorized_by_user_id`; authorization requires the recall to be in `RETRIEVAL_ACCOUNTING` or `EFFECTIVENESS_REVIEW`, and it requires the order's `quantity` to be no greater than the recall's `units_awaiting_disposition` at that moment — an order for more product than the firm actually holds is refused with `ERR_DISPOSITION_EXCEEDS_ACCOUNTED_UNITS`."

        Design: Difficulty/cross_entity_state_dependency/disposition_authorization_bounded_by_verified_retrieval_units
        """
        case = _usda_case_with_five_hundred_units_in_custody()
        order = case.propose_disposition(600)

        response = api.authorize_disposition_order(order["id"], COORDINATOR)
        validate_error(
            response, ApiErrorId.ERR_DISPOSITION_EXCEEDS_ACCOUNTED_UNITS.value
        )
        assert response.status_code == 422

        rows, _ = validate_paginated(
            api.list_disposition_orders(case.recall_id, COORDINATOR)
        )
        assert rows[0]["status"] == "PROPOSED"
        assert rows[0]["authorized_by_user_id"] is None

    def test_a_refused_authorization_leaves_the_custody_ledger_untouched(self, api):
        """PRD §3.7: "Hop one stamps `verified_by_user_id`, re-sums the recall's `accounted_units` over its receipts in `VERIFIED`, and adds this receipt's `quantity_returned` plus its `quantity_held_segregated` to the recall's `units_awaiting_disposition` — the two buckets of product that are still physically somewhere and still need a disposition decision, as distinct from product already destroyed at the consignee."
        PRD §3.7: "Then `quantity_effectiveness_pct` is 0.00 when `shipped_units` is zero; otherwise it is the smaller of `accounted_units` and `shipped_units`, divided by `shipped_units`, multiplied by 100, rounded half up to two decimal places."

        Design: Difficulty/cross_entity_state_dependency/disposition_authorization_bounded_by_verified_retrieval_units
        """
        case = _usda_case_with_five_hundred_units_in_custody()
        order = case.propose_disposition(600)
        response = api.authorize_disposition_order(order["id"], COORDINATOR)
        validate_error(
            response, ApiErrorId.ERR_DISPOSITION_EXCEEDS_ACCOUNTED_UNITS.value
        )

        recall = case.read_recall()
        assert recall["units_awaiting_disposition"] == 500
        assert recall["units_pending_verification"] == 0
        assert recall["quantity_effectiveness_pct"] == 50.00
        assert recall["status"] == "RETRIEVAL_ACCOUNTING"


class TestReceiptGateOrdering:
    """The referential gate on a receipt is reported before the fiscal one."""

    @staticmethod
    def _case_with_one_disputed_consignee():
        case = classified_case(agency="FDA")
        c1 = case.add_consignee("Metro Distributors", "DISTRIBUTOR")
        c2 = case.add_consignee("Harbor Grocery", "RETAILER")
        case.confirmed_shipment(c1["id"], 600)
        disputed_line = case.add_shipment(
            c2["id"], 400, ship_date="2026-08-21T00:00:00Z"
        )
        case.reconcile(disputed_line["id"], "DISPUTE")
        case.notify(c1["id"], method="EMAIL")
        case.c1_id = c1["id"]
        case.c2_id = c2["id"]
        return case

    def test_unlisted_consignee_yields_the_referential_error(self, api):
        """PRD §3.7: "The named consignee must appear on the reconciled distribution list — it must have at least one distribution record on this recall in `CONFIRMED` or `CORRECTED` — and otherwise the filing is refused with `ERR_CONSIGNEE_NOT_ON_DISTRIBUTION_LIST`."
        PRD §2.6: "Checks are evaluated strictly in the ascending order listed below; the first violated rung wins and short-circuits every later rung."

        Design: Difficulty/priority_pair_validation_conflict/receipt_for_unlisted_consignee_over_quantity_returns_referential_error_not_fiscal_error
        """
        case = self._case_with_one_disputed_consignee()

        response = api.create_retrieval_receipt(
            case.recall_id,
            create_retrieval_receipt_payload(case.c2_id, quantity_returned=10),
            case.officer,
        )
        error = validate_error(
            response, ApiErrorId.ERR_CONSIGNEE_NOT_ON_DISTRIBUTION_LIST.value
        )
        assert response.status_code == 422
        assert error["error_id"] != ApiErrorId.ERR_QUANTITY_EXCEEDS_SHIPPED.value

    def test_the_refused_receipt_is_not_persisted(self, api):
        """PRD §3.7: "The named consignee must appear on the reconciled distribution list — it must have at least one distribution record on this recall in `CONFIRMED` or `CORRECTED` — and otherwise the filing is refused with `ERR_CONSIGNEE_NOT_ON_DISTRIBUTION_LIST`."
        PRD §3.4: "`DISPUTE` moves `DECLARED → DISPUTED`, `CONFIRMED → DISPUTED` or `CORRECTED → DISPUTED` and sets `effective_quantity` to 0."

        Design: Difficulty/priority_pair_validation_conflict/receipt_for_unlisted_consignee_over_quantity_returns_referential_error_not_fiscal_error
        """
        case = self._case_with_one_disputed_consignee()
        response = api.create_retrieval_receipt(
            case.recall_id,
            create_retrieval_receipt_payload(case.c2_id, quantity_returned=10),
            case.officer,
        )
        validate_error(
            response, ApiErrorId.ERR_CONSIGNEE_NOT_ON_DISTRIBUTION_LIST.value
        )

        rows, meta = validate_paginated(
            api.list_consignee_retrieval_receipts(case.c2_id, COORDINATOR)
        )
        assert rows == []
        assert meta["total_count"] == 0
        assert case.read_recall()["total_shipped_units"] == 600
