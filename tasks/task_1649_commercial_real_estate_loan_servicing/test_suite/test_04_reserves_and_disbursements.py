"""Reserve accounts, the draw lifecycle (submit/review/fund/cancel/release),
the retainage waterfall, and reserve optimistic concurrency."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_draw,
    assert_reserve_invariants,
    cancel_draw,
    complete_inspection,
    create_borrower,
    create_disbursement_payload,
    create_draw,
    create_inspector,
    create_loan,
    create_property,
    create_reserve_account,
    create_reserve_account_payload,
    deposit_reserve,
    fund_draw,
    get_draw_by_id,
    get_loan,
    get_reserve,
    get_success_data,
    is_iso8601_timestamp,
    list_draws,
    make_borrower_headers,
    reject_draw,
    schedule_inspection,
    setup_special_servicing_loan,
    setup_watchlist_via_dscr_breach,
    validate_error,
    validate_success,
)

MS = TEST_USERS["master_servicer_headers"]
SS = TEST_USERS["special_servicer_headers"]


def _loan_with_reserve(tax_id, loan_number, deposit_cents, account_type="TI_LC",
                       target_balance_cents=0, **loan_overrides):
    borrower = create_borrower(tax_id=tax_id, legal_name=f"{tax_id} Co",
                               contact_email=f"{tax_id.lower()}@x.com")
    loan = create_loan(borrower["id"], loan_number=loan_number, **loan_overrides)
    reserve = create_reserve_account(loan["id"], account_type=account_type,
                                     target_balance_cents=target_balance_cents)
    if deposit_cents:
        reserve = deposit_reserve(reserve["id"], deposit_cents)
    return borrower, loan, reserve


class TestReserveCreationRules:
    def test_duplicate_reserve_account_type_rejected(self, api):
        """PRD §3.3: "A `MasterServicer` opens reserve accounts beneath a loan —
        at most one account per `account_type`, where the type is `TI_LC` or
        `REPLACEMENT`; a second account of a type the loan already holds is
        refused with `ERR_DUPLICATE_RESERVE_ACCOUNT`."

        Design: Corner/validations/duplicate_reserve_account_type_rejected
        """
        borrower = create_borrower(legal_name="Res Co", tax_id="TX-RSV",
                                   contact_email="rsv@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-RSV",
                           original_principal_cents=100_000_000, note_rate=0.05)
        get_success_data(api.create_reserve_account(
            loan["id"], create_reserve_account_payload(account_type="TI_LC"), MS))
        dup = api.create_reserve_account(
            loan["id"], create_reserve_account_payload(account_type="TI_LC"), MS)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_RESERVE_ACCOUNT)
        other = api.create_reserve_account(
            loan["id"], create_reserve_account_payload(account_type="REPLACEMENT"), MS)
        validate_success(other, 201)

    def test_disbursement_create_empty_line_items_returns_400(self, api):
        """PRD §3.3: "a non-empty `line_items` array in which each entry pairs a
        `description` with a strictly positive `amount_cents`"
        PRD §2.10: "Request schema: required fields present, types valid, enum
        members valid, ranges valid (amounts strictly positive where required,
        fractions between 0 and 1, ends not before starts, non-empty line items)
        — else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/disbursement_create_empty_line_items_returns_400
        """
        borrower, _loan, reserve = _loan_with_reserve(
            "TX-LIN", "LN-LIN", 0, original_principal_cents=100_000_000,
            note_rate=0.05)
        resp = api.create_disbursement_request(
            reserve["id"],
            create_disbursement_payload("CAPITAL_REPAIR", [], reserve["version"]),
            make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestReserveOptimisticConcurrency:
    def test_occ_disbursement_create_stale_version_returns_412(self, api):
        """PRD §2.8: "`POST /reserve-accounts/{reserve_account_id}/disbursement-requests`
        requires the non-optional field `expected_reserve_account_version`, carrying
        the reserve account's `version` as last observed. A mismatch with the
        reserve's current `version` — advanced, for instance, by a deposit or a
        funded draw changing its balances — is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_disbursement_create_stale_version_returns_412
        """
        borrower, _loan, reserve = _loan_with_reserve(
            "TX-OCR", "LN-OCR", 0, original_principal_cents=100_000_000,
            note_rate=0.05)
        stale_version = reserve["version"]
        deposit_reserve(reserve["id"], 1_000_000)  # deposit advances the version

        stale = api.create_disbursement_request(
            reserve["id"],
            create_disbursement_payload(
                "CAPITAL_REPAIR", [{"description": "stale", "amount_cents": 5000}],
                stale_version),
            make_borrower_headers(borrower["id"]))
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert list_draws(reserve["id"]) == [], "nothing is persisted on a stale create"

        fresh_version = get_reserve(reserve["id"])["version"]
        ok = api.create_disbursement_request(
            reserve["id"],
            create_disbursement_payload(
                "CAPITAL_REPAIR", [{"description": "fresh", "amount_cents": 5000}],
                fresh_version),
            make_borrower_headers(borrower["id"]))
        draw = validate_success(ok, 201)
        assert draw["status"] == "SUBMITTED"


class TestDrawReviewAndFunding:
    def test_fund_submitted_request_rejected(self, api):
        """PRD §3.3: "Funding an `APPROVED` request — again either servicer role —
        re-verifies the fiscal gate with one twist: the request's own hold counts
        as available to itself"
        PRD §2.10: "Generic state-machine precondition for the requested
        transition — else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/fund_submitted_request_rejected
        """
        borrower, _loan, reserve = _loan_with_reserve(
            "TX-SKP", "LN-SKP", 1_000_000,
            original_principal_cents=100_000_000, note_rate=0.05)
        draw = create_draw(reserve["id"], borrower["id"], "CAPITAL_REPAIR",
                           [{"description": "paint", "amount_cents": 100_000}])
        resp = api.fund_disbursement(draw["id"], MS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        reserve_after = get_reserve(reserve["id"])
        assert reserve_after["balance_cents"] == 1_000_000
        assert reserve_after["held_cents"] == 0

    def test_draw_equal_to_available_approves(self, api):
        """PRD §3.3: "Approval requires the request to be `SUBMITTED` (anything
        else earns `ERR_INVALID_STATE`), the reserve unfrozen (a frozen reserve
        answers `ERR_RESERVE_DISBURSEMENTS_FROZEN`), and the request's
        `amount_cents` no greater than the reserve's `available_cents` — equality
        is acceptable — with shortfalls rejected as
        `ERR_INSUFFICIENT_RESERVE_FUNDS` (HTTP 422)."
        PRD §3.3: "Approval places a hold: the reserve's `held_cents` grows by the
        request's `amount_cents` and its `version` advances."

        Design: Difficulty/boundary_precision_check/disbursement_amount_equals_available_balance
        """
        borrower, _loan, reserve = _loan_with_reserve(
            "TX-BC1", "LN-BC1", 5_000_000)
        draw = create_draw(reserve["id"], borrower["id"], "LEASING_COMMISSION",
                           [{"description": "broker fee", "amount_cents": 5_000_000}])
        approved = approve_draw(draw["id"])
        assert approved["status"] == "APPROVED", (
            "amount exactly equal to available approves (inclusive boundary)")
        reserve_after = get_reserve(reserve["id"])
        assert reserve_after["held_cents"] == 5_000_000
        assert_reserve_invariants(reserve_after)
        assert reserve_after["available_cents"] == 0

    def test_draw_one_cent_over_available_rejected(self, api):
        """PRD §3.3: "the request's `amount_cents` no greater than the reserve's
        `available_cents` — equality is acceptable — with shortfalls rejected as
        `ERR_INSUFFICIENT_RESERVE_FUNDS` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/disbursement_amount_equals_available_balance
        """
        borrower, _loan, reserve = _loan_with_reserve(
            "TX-BC2", "LN-BC2", 5_000_000)
        draw1 = create_draw(reserve["id"], borrower["id"], "LEASING_COMMISSION",
                            [{"description": "broker fee", "amount_cents": 5_000_000}])
        approve_draw(draw1["id"])  # consumes the entire available balance

        draw2 = create_draw(reserve["id"], borrower["id"], "CAPITAL_REPAIR",
                            [{"description": "one cent", "amount_cents": 1}])
        resp = api.review_disbursement(draw2["id"], "APPROVE", MS)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_RESERVE_FUNDS)
        assert get_draw_by_id(reserve["id"], draw2["id"])["status"] == "SUBMITTED"


class TestReviewDecisionPriority:
    def test_second_review_reports_invalid_state_not_fiscal(self, api):
        """PRD §2.10: "An approve decision attempted on a draw request that is no
        longer `SUBMITTED`, against a frozen reserve, and for more than the
        available funds reports `ERR_INVALID_STATE`, because the state check
        (step 7) precedes the frozen check (step 11) and the fiscal check
        (step 34)."

        Design: Difficulty/priority_pair_validation_conflict/review_decision_state_beats_fiscal
        """
        borrower, _loan, reserve = _loan_with_reserve(
            "TX-PR1", "LN-PR1", 1_000_000)
        draw = create_draw(reserve["id"], borrower["id"], "TENANT_IMPROVEMENT",
                           [{"description": "buildout", "amount_cents": 5_000_000}])
        reject_draw(draw["id"])  # REJECTED; the 5,000,000 shortfall stays latent

        resp = api.review_disbursement(draw["id"], "APPROVE", MS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        body = resp.json()
        assert body["data"]["error_id"] != "ERR_INSUFFICIENT_RESERVE_FUNDS", (
            "the state failure is reported before the still-latent fiscal failure")

    def test_reject_decision_carries_no_fiscal_check(self, api):
        """PRD §3.3: "Rejection carries no fiscal check — even an unaffordable
        request may be rejected — and leaves the reserve untouched."

        Design: Difficulty/priority_pair_validation_conflict/review_decision_state_beats_fiscal
        """
        borrower, _loan, reserve = _loan_with_reserve(
            "TX-PR1B", "LN-PR1B", 1_000_000)
        draw = create_draw(reserve["id"], borrower["id"], "TENANT_IMPROVEMENT",
                           [{"description": "buildout", "amount_cents": 5_000_000}])
        rejected = reject_draw(draw["id"])
        assert rejected["status"] == "REJECTED", (
            "a 5,000,000 draw against 1,000,000 available may still be rejected")
        reserve_after = get_reserve(reserve["id"])
        assert reserve_after["balance_cents"] == 1_000_000
        assert reserve_after["held_cents"] == 0, "rejection places no hold"


class TestDisbursementWaterfall:
    def test_funding_rounds_retainage_per_line_then_sums(self, api):
        """PRD §3.3: "Retainage is computed line by line: each line's withheld
        amount is that line's `amount_cents` multiplied by the effective fraction,
        rounded half-up to whole cents, and the line's disbursed amount is what
        remains."
        PRD §3.3: "The request's `funded_cents` is the sum of the per-line
        disbursed amounts and its `retained_cents` the sum of the per-line
        withholdings — rounding each line first and then summing is mandatory,
        because summing first and rounding once yields different totals."

        Design: Difficulty/combinatorial_formula/disbursement_retainage_per_line_rounding
        """
        borrower, _loan, reserve = _loan_with_reserve(
            "TX-WF", "LN-WF", 10_000_000)
        draw = create_draw(
            reserve["id"], borrower["id"], "CAPITAL_REPAIR",
            [{"description": "roof membrane", "amount_cents": 3333},
             {"description": "deck repair", "amount_cents": 3333},
             {"description": "drainage", "amount_cents": 3333}],
            retainage_pct=0.10)
        approve_draw(draw["id"])
        funded = fund_draw(draw["id"])
        # Per line: round_half_up(3333 x 0.10) = 333 retained, 3000 disbursed.
        assert funded["status"] == "FUNDED"
        assert funded["funded_cents"] == 9000
        assert funded["retained_cents"] == 999, (
            "sum-then-round would yield 1000; per-line rounding yields 999")
        assert is_iso8601_timestamp(funded["funded_at"]), (
            "funded_at stamps the clock time of funding")

    def test_funding_waterfall_updates_reserve_counters(self, api):
        """PRD §3.3: "The reserve's `held_cents` falls by the request's full
        `amount_cents`, its `balance_cents` falls by `funded_cents`, its
        `retained_cents` grows by the withheld total, its `version` advances, and
        the request's `funded_at` stamps the clock time of funding."
        PRD §3.3: "The derived `available_cents` is always the balance minus the
        held amount, an invariant that must never go negative."

        Design: Difficulty/combinatorial_formula/disbursement_retainage_per_line_rounding
        """
        borrower, _loan, reserve = _loan_with_reserve(
            "TX-WF2", "LN-WF2", 10_000_000)
        draw = create_draw(
            reserve["id"], borrower["id"], "CAPITAL_REPAIR",
            [{"description": "roof membrane", "amount_cents": 3333},
             {"description": "deck repair", "amount_cents": 3333},
             {"description": "drainage", "amount_cents": 3333}],
            retainage_pct=0.10)
        approve_draw(draw["id"])
        fund_draw(draw["id"])
        reserve_after = get_reserve(reserve["id"])
        assert reserve_after["balance_cents"] == 10_000_000 - 9000
        assert reserve_after["held_cents"] == 0
        assert reserve_after["retained_cents"] == 999
        assert_reserve_invariants(reserve_after)

    def test_elevated_retainage_floor_applied_when_watchlist(self, api):
        """PRD §3.3: "When the reserve's `elevated_retainage` flag is set, the
        effective retainage fraction is the greater of the request's
        `retainage_pct` and a floor of 0.20; otherwise the requested fraction
        applies as given."
        PRD §3.6: "the moment any covenant assessment stands `OPEN` or any
        watchlist entry stands `ACTIVE`, a `PERFORMING` loan moves to `WATCHLIST`
        and every reserve of the loan flips `elevated_retainage` on"

        Design: Corner/calculations/elevated_retainage_floor_applied_when_watchlist
        """
        ctx = setup_watchlist_via_dscr_breach(
            tax_id="TX-FLR", dscr_threshold=1.20, noi_cents=15_000_000,
            reserve={"account_type": "TI_LC", "deposit_cents": 1_000_000})
        reserve = ctx["reserve"]
        assert reserve["elevated_retainage"] is True, (
            "the WATCHLIST cascade elevated the reserve before funding")
        draw = create_draw(reserve["id"], ctx["borrower"]["id"], "CAPITAL_REPAIR",
                           [{"description": "hvac", "amount_cents": 100_000}],
                           retainage_pct=0.05)
        approve_draw(draw["id"])
        funded = fund_draw(draw["id"])
        assert funded["retained_cents"] == 20_000, (
            "the 0.20 floor overrides the requested 0.05 while elevated")
        assert funded["funded_cents"] == 80_000
        reserve_after = get_reserve(reserve["id"])
        assert reserve_after["balance_cents"] == 920_000


class TestApproveCancelInvariant:
    def test_approve_holds_without_moving_cash(self, api):
        """PRD §3.3: "Approval places a hold: the reserve's `held_cents` grows by
        the request's `amount_cents` and its `version` advances."
        PRD §3.3: "The derived `available_cents` is always the balance minus the
        held amount, an invariant that must never go negative."

        Design: Difficulty/compensating_invariant/approve_then_cancel_conserves_reserve_cash
        """
        borrower, _loan, reserve = _loan_with_reserve(
            "TX-IV1", "LN-IV1", 8_000_000)
        draw = create_draw(reserve["id"], borrower["id"], "TENANT_IMPROVEMENT",
                           [{"description": "suite 400 buildout",
                             "amount_cents": 3_000_000}])
        approve_draw(draw["id"])
        mid = get_reserve(reserve["id"])
        assert mid["held_cents"] == 3_000_000
        assert mid["balance_cents"] == 8_000_000, "approval holds, never moves cash"
        assert mid["available_cents"] == 5_000_000

    def test_cancel_releases_hold_conserving_cash(self, api):
        """PRD §3.3: "The borrower may cancel its own request while `SUBMITTED`
        with no side effects, or while `APPROVED`, which releases the hold by
        reducing the reserve's `held_cents` by the request's `amount_cents` and
        advancing the reserve's `version`"
        PRD §3.3: "The derived `available_cents` is always the balance minus the
        held amount, an invariant that must never go negative."

        Design: Difficulty/compensating_invariant/approve_then_cancel_conserves_reserve_cash
        """
        borrower, _loan, reserve = _loan_with_reserve(
            "TX-IV1B", "LN-IV1B", 8_000_000)
        draw = create_draw(reserve["id"], borrower["id"], "TENANT_IMPROVEMENT",
                           [{"description": "suite 400 buildout",
                             "amount_cents": 3_000_000}])
        approve_draw(draw["id"])
        cancelled = cancel_draw(draw["id"], borrower["id"])
        assert cancelled["status"] == "CANCELLED"
        final = get_reserve(reserve["id"])
        assert final["held_cents"] == 0
        assert final["balance_cents"] == 8_000_000
        assert final["available_cents"] == 8_000_000, (
            "approve + cancel conserve reserve cash with zero drift")


class TestRetainageRelease:
    def test_retainage_release_blocked_then_allowed(self, api):
        """PRD §3.3: "Withheld retainage is released by a `MasterServicer` only
        after proof of completed work: the request must stand `FUNDED` with
        `retained_cents` still positive (otherwise `ERR_INVALID_STATE`), and at
        least one property of the same loan must have a `COMPLETED` inspection
        whose `completed_at` is on or after the request's `funded_at` — lacking
        one, the release is refused with `ERR_RETAINAGE_RELEASE_BLOCKED`."
        PRD §3.3: "On release the reserve's `balance_cents` falls by the retained
        amount, its `retained_cents` falls by the same amount, the request's own
        `retained_cents` returns to zero, and the reserve's `version` advances."

        Design: Corner/endpoints/retainage_release_blocked_then_allowed
        """
        borrower = create_borrower(legal_name="Rel Co", tax_id="TX-REL",
                                   contact_email="rel@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-REL",
                           original_principal_cents=100_000_000, note_rate=0.05)
        prop = create_property(loan["id"], address="1 Rel St")
        reserve = create_reserve_account(loan["id"])
        reserve = deposit_reserve(reserve["id"], 1_000_000)
        draw = create_draw(reserve["id"], borrower["id"], "CAPITAL_REPAIR",
                           [{"description": "roof", "amount_cents": 100_000}],
                           retainage_pct=0.10)
        approve_draw(draw["id"])
        fund_draw(draw["id"])

        blocked = api.release_retainage(draw["id"], MS)
        validate_error(blocked, ApiErrorId.ERR_RETAINAGE_RELEASE_BLOCKED)

        inspector = create_inspector(full_name="Rel Spect", license_no="LIC-REL")
        insp = schedule_inspection(prop["id"], inspector["id"],
                                   scheduled_start="2026-08-01T12:00:00Z",
                                   scheduled_end="2026-08-01T13:00:00Z")
        complete_inspection(insp["id"], inspector["id"], "GOOD")

        released = validate_success(api.release_retainage(draw["id"], MS))
        assert released["retained_cents"] == 0
        reserve_after = get_reserve(reserve["id"])
        assert reserve_after["balance_cents"] == 900_000, (
            "1,000,000 - 90,000 funded - 10,000 released retainage")
        assert reserve_after["retained_cents"] == 0


class TestFrozenReserve:
    def test_frozen_reserve_blocks_draw_approval(self, api):
        """PRD §3.6: "every reserve account of the loan sets
        `disbursement_frozen` to true while `elevated_retainage` stays on"
        PRD §3.3: "Approval requires the request to be `SUBMITTED` (anything else
        earns `ERR_INVALID_STATE`), the reserve unfrozen (a frozen reserve answers
        `ERR_RESERVE_DISBURSEMENTS_FROZEN`)"

        Design: Corner/validations/frozen_reserve_blocks_draw_approval
        """
        ctx = setup_special_servicing_loan(tax_id="TX-FRZ",
                                           reserve_deposit_cents=1_000_000)
        reserve = get_reserve(ctx["reserve"]["id"])
        assert reserve["disbursement_frozen"] is True
        assert get_loan(ctx["loan"]["id"])["servicing_status"] == "SPECIAL_SERVICING"

        # Draw creation itself remains allowed; the freeze bites at review.
        draw = create_draw(reserve["id"], ctx["borrower"]["id"], "CAPITAL_REPAIR",
                           [{"description": "emergency", "amount_cents": 50_000}],
                           expected_version=reserve["version"])
        assert draw["status"] == "SUBMITTED"

        resp = api.review_disbursement(draw["id"], "APPROVE", SS)
        validate_error(resp, ApiErrorId.ERR_RESERVE_DISBURSEMENTS_FROZEN)
        reserve_after = get_reserve(reserve["id"])
        assert reserve_after["balance_cents"] == 1_000_000
        assert reserve_after["held_cents"] == 0
