"""Chargebacks: provisional vs final amounts, per-line rounding, the dispute
loop, balance accounting, and event precondition ordering."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    chargeback_line,
    complete_as_technician,
    create_work_order,
    dispatch_in_house,
    get_chargeback,
    get_chargebacks_for_work_order,
    get_resident,
    make_resident_headers,
    setup_billed_chargeback,
    setup_completed_work_order,
    setup_property_resident_technician,
    sign_off,
    start_as_technician,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]


def _damage_completed(api, property_name, unit, estimate):
    """Completed work order with resident-caused damage; returns bundle with the
    PENDING chargeback at bundle['chargeback']."""
    bundle = setup_completed_work_order(
        property_name=property_name, unit_number=unit,
        damage_reported=True, estimated_damage_cost_cents=estimate,
    )
    assert len(bundle["chargebacks"]) == 1
    bundle["chargeback"] = bundle["chargebacks"][0]
    assert bundle["chargeback"]["status"] == "PENDING"
    return bundle


class TestProvisionalVsFinalAmount:
    def test_bill_computes_final_amount_from_lines(self, api):
        """PRD §3.9: "The billed amount, `final_amount_cents`, is computed per line and then summed: each line's amount is its quantity times its unit cost times its resident share, rounded half-up to the nearest cent, and the rounded line amounts are added together."
        PRD §3.4: "with `provisional_amount_cents` set to the raw `estimated_damage_cost_cents` from the completion payload — the technician's unrounded field estimate, captured as-is with no rounding applied."

        Design: Difficulty/dual_variant_calc/chargeback_provisional_vs_final_amount
        """
        bundle = _damage_completed(api, "CB Property", "102", 4999)
        cb_id = bundle["chargeback"]["id"]
        data = validate_success(
            api.chargeback_event(
                cb_id,
                {"event_type": "BILL",
                 "line_items": [chargeback_line(
                     description="Drywall patch", quantity=3,
                     unit_cost_cents=3333, resident_share_pct=0.5)]},
                MANAGER,
            ),
            200,
        )
        assert data["provisional_amount_cents"] == 4999, "raw estimate preserved as-is"
        # round_half_up(3 * 3333 * 0.5) == round_half_up(4999.5) == 5000.
        assert data["final_amount_cents"] == 5000
        assert data["provisional_amount_cents"] != data["final_amount_cents"]

    def test_bill_raises_resident_balance_by_final_amount(self, api):
        """PRD §3.9: "Billing moves the chargeback from `PENDING` to `BILLED`, stores the lines, and recomputes the resident's `chargeback_balance_cents`, which rises by the new final amount."

        Design: Difficulty/dual_variant_calc/chargeback_provisional_vs_final_amount
        """
        bundle = _damage_completed(api, "CB Property", "102", 4999)
        validate_success(
            api.chargeback_event(
                bundle["chargeback"]["id"],
                {"event_type": "BILL",
                 "line_items": [chargeback_line(
                     description="Drywall patch", quantity=3,
                     unit_cost_cents=3333, resident_share_pct=0.5)]},
                MANAGER,
            ),
            200,
        )
        resident = get_resident(bundle["resident"]["id"])
        assert resident["chargeback_balance_cents"] == 5000


class TestPerLineRoundThenSum:
    def test_rounding_applies_per_line_before_summing(self, api):
        """PRD §3.9: "The billed amount, `final_amount_cents`, is computed per line and then summed: each line's amount is its quantity times its unit cost times its resident share, rounded half-up to the nearest cent, and the rounded line amounts are added together."
        PRD §3.9: "The per-line-then-sum order is the rule — summing raw amounts and rounding once at the end is not used."

        Design: Difficulty/combinatorial_formula/chargeback_per_line_round_then_sum
        """
        bundle = _damage_completed(api, "Round Property", "104", 9999)
        lines = [
            chargeback_line(description="Patch A", quantity=3,
                            unit_cost_cents=3333, resident_share_pct=0.5),
            chargeback_line(description="Patch B", quantity=3,
                            unit_cost_cents=3333, resident_share_pct=0.5),
        ]
        data = validate_success(
            api.chargeback_event(
                bundle["chargeback"]["id"],
                {"event_type": "BILL", "line_items": lines},
                MANAGER,
            ),
            200,
        )
        # Each line rounds 4999.5 up to 5000; the rounded lines then sum to 10000.
        assert data["final_amount_cents"] == 10000

    def test_sum_then_round_alternative_not_used(self, api):
        """PRD §3.9: "The per-line-then-sum order is the rule — summing raw amounts and rounding once at the end is not used."
        PRD §3.9: "Billing moves the chargeback from `PENDING` to `BILLED`, stores the lines, and recomputes the resident's `chargeback_balance_cents`, which rises by the new final amount."

        Design: Difficulty/combinatorial_formula/chargeback_per_line_round_then_sum
        """
        bundle = _damage_completed(api, "Round Property", "104", 9999)
        lines = [
            chargeback_line(description="Patch A", quantity=3,
                            unit_cost_cents=3333, resident_share_pct=0.5),
            chargeback_line(description="Patch B", quantity=3,
                            unit_cost_cents=3333, resident_share_pct=0.5),
        ]
        data = validate_success(
            api.chargeback_event(
                bundle["chargeback"]["id"],
                {"event_type": "BILL", "line_items": lines},
                MANAGER,
            ),
            200,
        )
        # Sum-then-round would give round_half_up(9999.0) == 9999; that order is not used.
        assert data["final_amount_cents"] != 9999
        resident = get_resident(bundle["resident"]["id"])
        assert resident["chargeback_balance_cents"] == data["final_amount_cents"]


class TestDisputeLoop:
    def _setup_billed(self, api):
        bundle = setup_billed_chargeback(
            [chargeback_line(description="Cabinet", quantity=1,
                             unit_cost_cents=10000, resident_share_pct=1.0)],
            estimated_damage_cost_cents=10000,
            property_name="Loop Property", unit_number="106",
        )
        assert bundle["chargeback"]["status"] == "BILLED"
        assert bundle["chargeback"]["final_amount_cents"] == 10000
        return bundle

    def test_dispute_keeps_balance_and_uphold_returns_to_billed(self, api):
        """PRD §3.9: "The charged resident — matching `X-User-ID` against the chargeback's `resident_id` — may dispute it, supplying a `dispute_reason`; the status moves to `DISPUTED` and the balance does not change, because a disputed amount is still owed. A PropertyManager may uphold a dispute, moving `DISPUTED` back to `BILLED` with the balance again unchanged."

        Design: Difficulty/non_linear_state_machine/chargeback_dispute_loop
        """
        bundle = self._setup_billed(api)
        cb_id = bundle["chargeback"]["id"]
        res_id = bundle["resident"]["id"]

        disputed = validate_success(
            api.chargeback_event(
                cb_id,
                {"event_type": "DISPUTE", "dispute_reason": "pre-existing damage"},
                make_resident_headers(res_id),
            ),
            200,
        )
        assert disputed["status"] == "DISPUTED"
        assert get_resident(res_id)["chargeback_balance_cents"] == 10000, (
            "a disputed amount is still owed"
        )

        upheld = validate_success(
            api.chargeback_event(cb_id, {"event_type": "UPHOLD"}, MANAGER), 200
        )
        assert upheld["status"] == "BILLED", "cycle DISPUTED -> BILLED traversed"
        assert get_resident(res_id)["chargeback_balance_cents"] == 10000

    def test_second_dispute_then_waive_zeroes_balance(self, api):
        """PRD §3.9: "A PropertyManager may waive the chargeback from either `BILLED` or `DISPUTED`, moving it to `WAIVED` and recomputing the balance, which falls by the final amount."
        PRD §3.9: "`PAID` and `WAIVED` are terminal; `PENDING` is never part of the balance either. Formally, a resident's `chargeback_balance_cents` is the sum of `final_amount_cents` over all their chargebacks in `BILLED` or `DISPUTED` status — nothing more, nothing less — and is recomputed on every bill, waive, and pay event."

        Design: Difficulty/non_linear_state_machine/chargeback_dispute_loop
        """
        bundle = self._setup_billed(api)
        cb_id = bundle["chargeback"]["id"]
        res_id = bundle["resident"]["id"]
        res_headers = make_resident_headers(res_id)

        # Full loop: DISPUTE -> UPHOLD -> DISPUTE again from BILLED.
        validate_success(
            api.chargeback_event(
                cb_id, {"event_type": "DISPUTE", "dispute_reason": "first"}, res_headers
            ),
            200,
        )
        validate_success(
            api.chargeback_event(cb_id, {"event_type": "UPHOLD"}, MANAGER), 200
        )
        second = validate_success(
            api.chargeback_event(
                cb_id, {"event_type": "DISPUTE", "dispute_reason": "second dispute"},
                res_headers,
            ),
            200,
        )
        assert second["status"] == "DISPUTED", "the dispute loop repeats from BILLED"

        waived = validate_success(
            api.chargeback_event(cb_id, {"event_type": "WAIVE"}, MANAGER), 200
        )
        assert waived["status"] == "WAIVED"
        assert get_resident(res_id)["chargeback_balance_cents"] == 0


class TestBillWaiveBalanceInvariant:
    def _setup_pending(self, api):
        return _damage_completed(api, "Fiscal Property", "118", 10000)

    def test_bill_raises_balance_to_final_amount(self, api):
        """PRD §3.9: "Formally, a resident's `chargeback_balance_cents` is the sum of `final_amount_cents` over all their chargebacks in `BILLED` or `DISPUTED` status — nothing more, nothing less — and is recomputed on every bill, waive, and pay event."

        Design: Difficulty/compensating_invariant/chargeback_bill_waive_conserves_balance
        """
        bundle = self._setup_pending(api)
        assert get_resident(bundle["resident"]["id"])["chargeback_balance_cents"] == 0
        validate_success(
            api.chargeback_event(
                bundle["chargeback"]["id"],
                {"event_type": "BILL",
                 "line_items": [chargeback_line(
                     description="Door", quantity=1,
                     unit_cost_cents=10000, resident_share_pct=1.0)]},
                MANAGER,
            ),
            200,
        )
        assert get_resident(bundle["resident"]["id"])["chargeback_balance_cents"] == 10000

    def test_waive_restores_pre_bill_balance(self, api):
        """PRD §3.9: "A PropertyManager may waive the chargeback from either `BILLED` or `DISPUTED`, moving it to `WAIVED` and recomputing the balance, which falls by the final amount."

        Design: Difficulty/compensating_invariant/chargeback_bill_waive_conserves_balance
        """
        bundle = self._setup_pending(api)
        cb_id = bundle["chargeback"]["id"]
        validate_success(
            api.chargeback_event(
                cb_id,
                {"event_type": "BILL",
                 "line_items": [chargeback_line(
                     description="Door", quantity=1,
                     unit_cost_cents=10000, resident_share_pct=1.0)]},
                MANAGER,
            ),
            200,
        )
        assert get_resident(bundle["resident"]["id"])["chargeback_balance_cents"] == 10000
        waived = validate_success(
            api.chargeback_event(cb_id, {"event_type": "WAIVE"}, MANAGER), 200
        )
        assert waived["status"] == "WAIVED"
        # The BILL/WAIVE pair conserves the balance at its pre-BILL value.
        assert get_resident(bundle["resident"]["id"])["chargeback_balance_cents"] == 0


class TestBillPreconditions:
    def test_bill_without_line_items_rejected(self, api):
        """PRD §3.9: "Billing without lines, or with an invalid line, is rejected with `ERR_CHARGEBACK_LINES_REQUIRED` (HTTP 422)."

        Design: Corner/validations/bill_without_line_items_rejected
        """
        bundle = _damage_completed(api, "Bill Property", "414", 4000)
        cb_id = bundle["chargeback"]["id"]
        resp = api.chargeback_event(cb_id, {"event_type": "BILL"}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_CHARGEBACK_LINES_REQUIRED)
        after = get_chargeback(cb_id)
        assert after["status"] == "PENDING"
        assert get_resident(bundle["resident"]["id"])["chargeback_balance_cents"] == 0


class TestStateBeatsFiscalOnBill:
    def _setup_disputed(self, api):
        bundle = setup_billed_chargeback(
            [chargeback_line(description="Floor", quantity=1,
                             unit_cost_cents=10000, resident_share_pct=1.0)],
            estimated_damage_cost_cents=10000,
            property_name="Prio Property", unit_number="109",
        )
        cb_id = bundle["chargeback"]["id"]
        validate_success(
            api.chargeback_event(
                cb_id,
                {"event_type": "DISPUTE", "dispute_reason": "not mine"},
                make_resident_headers(bundle["resident"]["id"]),
            ),
            200,
        )
        return bundle

    def test_bill_on_disputed_without_lines_yields_invalid_state(self, api):
        """PRD §2.1: "The precedence among all validation categories — authentication, authorization, ownership, existence, concurrency, state, business safety, business temporal, business constraint, business fiscal, and finally general shape validation — is honored across every endpoint: an unauthenticated request is rejected before a forbidden one, a forbidden one before a non-owner one, and so on, with malformed-payload errors of the general `ERR_VALIDATION` category evaluated last."
        PRD §3.9: "Billing moves the chargeback from `PENDING` to `BILLED`, stores the lines, and recomputes the resident's `chargeback_balance_cents`, which rises by the new final amount."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_chargeback_bill
        """
        bundle = self._setup_disputed(api)
        cb_id = bundle["chargeback"]["id"]
        # BILL is only defined from PENDING, and the payload also omits the
        # line_items the fiscal rule demands; the state category outranks the
        # business-fiscal category, so ERR_INVALID_STATE (409) wins.
        resp = api.chargeback_event(cb_id, {"event_type": "BILL"}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_chargeback(cb_id)["status"] == "DISPUTED"

    def test_bill_on_billed_with_valid_lines_yields_invalid_state(self, api):
        """PRD §3.9: "Billing moves the chargeback from `PENDING` to `BILLED`, stores the lines, and recomputes the resident's `chargeback_balance_cents`, which rises by the new final amount."
        PRD §3.5: "Attempting any transition from a status that does not allow it — reopening an `IN_PROGRESS` order, closing a `TRIAGED` one, cancelling a `COMPLETED` one, and so on — is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_chargeback_bill
        """
        bundle = setup_billed_chargeback(
            [chargeback_line(description="Floor", quantity=1,
                             unit_cost_cents=10000, resident_share_pct=1.0)],
            estimated_damage_cost_cents=10000,
            property_name="Prio Property", unit_number="109",
        )
        cb_id = bundle["chargeback"]["id"]
        # Isolated state leg: the fiscal payload is well-formed, but BILL is not
        # defined from BILLED.
        resp = api.chargeback_event(
            cb_id,
            {"event_type": "BILL",
             "line_items": [chargeback_line(description="Again", quantity=1,
                                            unit_cost_cents=100,
                                            resident_share_pct=1.0)]},
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_chargeback(cb_id)["status"] == "BILLED"


class TestBalanceInputSet:
    def test_balance_counts_billed_and_disputed_only(self, api):
        """PRD §3.9: "Formally, a resident's `chargeback_balance_cents` is the sum of `final_amount_cents` over all their chargebacks in `BILLED` or `DISPUTED` status — nothing more, nothing less — and is recomputed on every bill, waive, and pay event."
        PRD §3.9: "`PAID` and `WAIVED` are terminal; `PENDING` is never part of the balance either."

        Design: Corner/calculations/chargeback_balance_counts_billed_and_disputed_only
        """
        bundle = setup_property_resident_technician("Bal Property", unit_number="304")
        prop_id = bundle["property"]["id"]
        res_id = bundle["resident"]["id"]
        tech_id = bundle["technician"]["id"]

        # Work order 1: completed with damage (estimate 5000); its chargeback is
        # BILLED at 5000 and enters the balance.
        wo1 = create_work_order(prop_id, res_id, description="Damage 1")
        dispatch_in_house(wo1["id"], tech_id,
                          scheduled_start_at="2026-08-01T10:00:00Z",
                          scheduled_end_at="2026-08-01T12:00:00Z")
        start_as_technician(wo1["id"], tech_id)
        sign_off(wo1["id"], res_id)
        complete_as_technician(wo1["id"], tech_id,
                               photo_urls=["https://x/n1.jpg"],
                               damage_reported=True,
                               estimated_damage_cost_cents=5000)
        cb1 = get_chargebacks_for_work_order(wo1["id"])[0]
        validate_success(
            api.chargeback_event(
                cb1["id"],
                {"event_type": "BILL",
                 "line_items": [chargeback_line(
                     description="Repair", quantity=1,
                     unit_cost_cents=5000, resident_share_pct=1.0)]},
                MANAGER,
            ),
            200,
        )

        # Work order 2: completed with damage (estimate 7000); its chargeback is
        # left PENDING and must contribute nothing to the balance.
        wo2 = create_work_order(prop_id, res_id, description="Damage 2")
        dispatch_in_house(wo2["id"], tech_id,
                          scheduled_start_at="2026-08-01T14:00:00Z",
                          scheduled_end_at="2026-08-01T16:00:00Z")
        start_as_technician(wo2["id"], tech_id)
        sign_off(wo2["id"], res_id)
        complete_as_technician(wo2["id"], tech_id,
                               photo_urls=["https://x/n2.jpg"],
                               damage_reported=True,
                               estimated_damage_cost_cents=7000)

        resident = get_resident(res_id)
        assert resident["chargeback_balance_cents"] == 5000, (
            "only the BILLED chargeback contributes; PENDING is excluded"
        )
        data, meta = validate_paginated(
            api.list_chargebacks(MANAGER, params={"resident_id": res_id})
        )
        assert meta["total_count"] == 2
