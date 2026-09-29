"""
Input and cross-entity validations of the servicing-rights transfer desk.

This module pins the desk's refusals: the uniqueness rules that scope a loan
number to one pool and an approval prerequisite to one
(agreement, approver type, agency) triple, the side-of-trade integrity check
that reads `role_type` off the counterparty a request merely names, the market
prerequisite that no valuation or hedge may be struck without an active rate
curve, the statutory calendar that governs the settlement transfer date, the
borrower notice, the reopen window on an error case and the holdback release
date, and the bidder risk floor that keeps a thinly capitalised acquirer out of
the auction. Each test also checks that the refused call left the desk exactly
as it found it.
"""

from test_helpers import (
    C,
    F,
    U,
    ApiClient,
    ERR_BIDDER_NOT_ELIGIBLE,
    ERR_BIDDER_RISK_TIER_TOO_HIGH,
    ERR_COUNTERPARTY_ROLE_MISMATCH,
    ERR_DUPLICATE_APPROVAL_REQUEST,
    ERR_DUPLICATE_LOAN_NUMBER,
    ERR_HOLDBACK_EXHAUSTED,
    ERR_HOLDBACK_NOT_ELIGIBLE,
    ERR_LOAN_NOT_ON_TAPE,
    ERR_NOTICE_EFFECTIVE_DATE_MISMATCH,
    ERR_NO_ACTIVE_RATE_CURVE,
    ERR_REOPEN_WINDOW_EXPIRED,
    ERR_TRANSFER_DATE_TOO_SOON,
    JsonDict,
    assert_dimensions,
    assert_holdback_split,
    assert_readiness,
    assert_status,
    build_awarded_trade,
    build_attested_notices,
    build_completed_transfer,
    build_live_bid,
    build_published_package,
    build_settled_trade,
    build_stratified_package,
    data_of,
    refresh_agreement,
    refresh_package,
    rows_of,
    validate_error,
    validate_success,
)

# The acquirer of the risk-floor scenarios: ACTIVE, holding the pool's own FNMA
# approval, but rated TIER_3 on a balance sheet under five million dollars.
THIN_BUYER = {
    "legal_name": "Charlie Subservicing Corp",
    "role_type": "BUYER",
    "net_worth_cents": 200000000,
    "servicer_rating": "TIER_3",
    "agency_approvals": ["FNMA"],
}


def _locked_pool_without_a_curve(api: ApiClient) -> JsonDict:
    """
    A staffed desk carrying a locked single-loan pool, assembled without ever
    publishing a rate curve snapshot, so the market-state table stays empty.
    """
    F.set_clock(api, C.CLOCK_DEFAULT)
    seller = F.create_counterparty(api, C.SELLER_ALPHA)
    assumptions = F.create_assumption_set(api, C.ASSUMPTION_DESK_BASE)
    portfolio = F.create_portfolio(api, seller["id"], name="Pool-Z")
    F.add_loans(api, portfolio["id"], seller["id"], C.LOANS_M)
    portfolio = F.lock_tape(api, portfolio["id"], seller["id"])
    return {
        "seller_id": seller["id"],
        "assumption_set_id": assumptions["id"],
        "portfolio_id": portfolio["id"],
        "portfolio_version": portfolio["version"],
    }


def test_duplicate_loan_number_is_refused_inside_the_pool_only(api, desk):
    """
    A repeated loan number is refused within one pool yet accepted in a sibling
    pool of the same seller, and the refusal moves no portfolio aggregate.

    PRD: "Each loan carries a `loan_number` (non-blank, 1 to 32 characters, unique within its portfolio — a repeat is `ERR_DUPLICATE_LOAN_NUMBER`, HTTP 409), an unpaid principal balance `upb_cents` of at least 1, a `note_rate_pct` greater than 0 and at most 25 expressed in percent with at most 4 decimals, and a contractual `servicing_fee_bps` strip between 1 and 100 basis points of unpaid balance per annum."

    Design: Corner/validations/duplicate_loan_number_within_a_portfolio_is_rejected
    """
    seller_headers = desk["seller_headers"]
    pool = F.create_portfolio(api, desk["seller_id"], name="Pool-T")
    F.add_loan(api, pool["id"], desk["seller_id"], C.LOANS_T[0])
    sibling = F.create_portfolio(api, desk["seller_id"], name="Pool-T2")

    before = F.read_portfolio(api, pool["id"])
    assert before["loan_count"] == 1
    assert before["total_upb_cents"] == 10000050

    repeat = dict(
        C.LOANS_T[0],
        upb_cents=20000000,
        note_rate_pct=7.0,
        escrow_balance_cents=0,
        suspense_balance_cents=0,
        state_code="TX",
    )
    validate_error(
        api.create_loan(pool["id"], repeat, seller_headers),
        ERR_DUPLICATE_LOAN_NUMBER,
    )

    after = F.read_portfolio(api, pool["id"])
    assert after["loan_count"] == 1
    assert after["total_upb_cents"] == 10000050
    assert after["version"] == before["version"]

    # The uniqueness scope is the portfolio, so the identical body is admitted
    # by a sibling pool of the very same seller.
    accepted = data_of(
        api.create_loan(sibling["id"], repeat, seller_headers), 201
    )
    assert accepted["loan_number"] == "T-0001"
    assert accepted["upb_cents"] == 20000000


def test_portfolio_naming_a_buyer_as_its_seller_is_refused(api, desk):
    """
    Opening a pool whose named seller is registered on the buy side is refused
    for side-of-trade integrity even when the actor is that counterparty.

    PRD: "The named counterparty must have `role_type` `SELLER`; naming a buyer as a seller, or a seller as a bidder, is refused with `ERR_COUNTERPARTY_ROLE_MISMATCH` (HTTP 422)."

    Design: Corner/validations/portfolio_seller_with_the_buyer_role_is_rejected
    """
    body = {
        "seller_id": desk["buyer_id"],
        "portfolio_name": "Wrong-Side Pool",
        "agency_type": "FNMA",
    }
    # The acting identity IS the named counterparty, so the ownership check one
    # priority earlier is satisfied and only the role check can fire.
    validate_error(
        api.create_portfolio(body, U.make_seller_headers(desk["buyer_id"])),
        ERR_COUNTERPARTY_ROLE_MISMATCH,
    )

    on_the_buy_side = rows_of(
        api.list_portfolios(U.MANAGER, {"seller_id": desk["buyer_id"]})
    )
    assert on_the_buy_side == []

    accepted = data_of(
        api.create_portfolio(
            dict(body, seller_id=desk["seller_id"]),
            U.make_seller_headers(desk["seller_id"]),
        ),
        201,
    )
    assert accepted["seller_id"] == desk["seller_id"]
    assert_status(accepted, "DRAFT")


def test_bid_naming_the_selling_counterparty_as_bidder_is_refused(
        api, published_package):
    """
    The same side-of-trade rule fires from the other direction: a bid that names
    the sell-side institution as its bidder is refused.

    PRD: "The named counterparty must have `role_type` `SELLER`; naming a buyer as a seller, or a seller as a bidder, is refused with `ERR_COUNTERPARTY_ROLE_MISMATCH` (HTTP 422)."

    Design: Corner/validations/portfolio_seller_with_the_buyer_role_is_rejected
    """
    env = published_package
    body = {
        "bidder_id": env["seller_id"],
        "price_bps": 118,
        "holdback_pct": 6,
        "expected_bid_package_version": env["package_version"],
    }
    validate_error(
        api.create_bid(env["package_id"], body, U.MANAGER),
        ERR_COUNTERPARTY_ROLE_MISMATCH,
    )

    package = refresh_package(api, env)
    assert package["bid_count"] == 0
    assert rows_of(api.list_bids(U.MANAGER,
                                 {"bid_package_id": env["package_id"]})) == []


def test_valuation_and_hedge_are_refused_while_no_curve_is_active(api):
    """
    Before any rate curve has ever been published there is no market rate to
    price against, so both a valuation run and a hedge are refused.

    PRD: "When no snapshot is `ACTIVE` at all, the operations that need one — running a valuation, opening a hedge, and closing a hedge — fail with `ERR_NO_ACTIVE_RATE_CURVE` (HTTP 409)."

    Design: Corner/validations/valuation_with_no_rate_curve_ever_published_is_rejected
    """
    env = _locked_pool_without_a_curve(api)
    run_body = {
        "assumption_set_id": env["assumption_set_id"],
        "method": "DETERMINISTIC_STATIC",
        "expected_portfolio_version": env["portfolio_version"],
    }
    validate_error(
        api.create_valuation_run(env["portfolio_id"], run_body, U.ANALYST),
        ERR_NO_ACTIVE_RATE_CURVE,
    )
    validate_error(
        api.create_hedge_position(
            {
                "portfolio_id": env["portfolio_id"],
                "instrument": "TBA_LONG",
                "notional_cents": 260000,
                "hedge_ratio_pct": 60,
            },
            U.HEDGE,
        ),
        ERR_NO_ACTIVE_RATE_CURVE,
    )

    assert rows_of(
        api.list_valuation_runs(U.ANALYST,
                                {"portfolio_id": env["portfolio_id"]})
    ) == []
    portfolio = F.read_portfolio(api, env["portfolio_id"])
    assert portfolio["valuation_freshness"] == "NONE"
    assert portfolio["version"] == env["portfolio_version"]

    # Publishing the opening snapshot supplies the missing market rate, and the
    # very same request then prices the single loan.
    F.create_rate_curve(api, C.CURVE_C1)
    run = F.run_valuation(api, env["portfolio_id"], env["assumption_set_id"],
                          env["portfolio_version"])
    assert run["value_cents"] == 42894
    assert_status(run, "COMPLETED")


def test_duplicate_approval_request_triple_is_refused(api, awarded_trade):
    """
    A second (AGENCY, FNMA) prerequisite on one agreement is refused, while the
    investor consent — a different approver type — is admitted alongside it.

    PRD: "At most one request may exist per combination of agreement, `approver_type` and `agency_type`, and a repeat is refused with `ERR_DUPLICATE_APPROVAL_REQUEST` (HTTP 409)."

    Design: Corner/validations/duplicate_approval_request_triple_is_rejected
    """
    env = awarded_trade
    agency = F.create_approval_request(api, env["agreement_id"],
                                       approver_type="AGENCY",
                                       agency_type="FNMA")
    assert_status(agency, "PENDING")
    before = refresh_agreement(api, env)

    validate_error(
        api.create_approval_request(
            env["agreement_id"],
            {"approver_type": "AGENCY", "agency_type": "FNMA"},
            U.MANAGER,
        ),
        ERR_DUPLICATE_APPROVAL_REQUEST,
    )

    on_file = rows_of(api.list_approval_requests(env["agreement_id"], U.MANAGER))
    assert len(on_file) == 1
    assert on_file[0]["id"] == agency["id"]
    after = refresh_agreement(api, env)
    assert after["version"] == before["version"]

    # The agency hat and the investor hat are separate approvals, so the triple
    # differs and the second prerequisite is accepted.
    investor = F.create_approval_request(api, env["agreement_id"],
                                         approver_type="INVESTOR",
                                         agency_type=None)
    assert investor["approver_type"] == "INVESTOR"
    assert len(
        rows_of(api.list_approval_requests(env["agreement_id"], U.MANAGER))
    ) == 2


def test_settlement_fourteen_days_out_is_refused(api, approved_agreement):
    """
    A transfer date only fourteen days after the clock date is inside the
    statutory minimum and settlement is refused, changing nothing.

    PRD: "The transfer date must be at least 15 days after the current logical clock date, and the sale date must not be after the transfer date; either violation is `ERR_TRANSFER_DATE_TOO_SOON` (HTTP 422)."

    Design: Corner/validations/transfer_date_inside_the_statutory_minimum_is_rejected
    """
    env = approved_agreement
    before = refresh_agreement(api, env)
    assert_status(before, "APPROVED")

    validate_error(
        api.settle_agreement(
            env["agreement_id"],
            {"sale_date": "2026-08-05", "transfer_date": "2026-08-15"},
            U.MANAGER,
        ),
        ERR_TRANSFER_DATE_TOO_SOON,
    )

    after = refresh_agreement(api, env)
    assert_status(after, "APPROVED")
    assert after["transfer_date"] is None
    assert after["holdback_release_eligible_at"] is None
    assert after["version"] == before["version"]
    assert rows_of(api.list_servicing_transfers(U.MANAGER)) == []


def test_settlement_with_a_sale_date_after_the_transfer_date_is_refused(
        api, approved_agreement):
    """
    The ordering half of the same rule: a sale date later than the transfer date
    is refused with the identical error even when the lead time is ample.

    PRD: "The transfer date must be at least 15 days after the current logical clock date, and the sale date must not be after the transfer date; either violation is `ERR_TRANSFER_DATE_TOO_SOON` (HTTP 422)."

    Design: Corner/validations/transfer_date_inside_the_statutory_minimum_is_rejected
    """
    env = approved_agreement
    before = refresh_agreement(api, env)

    validate_error(
        api.settle_agreement(
            env["agreement_id"],
            {"sale_date": "2026-09-02", "transfer_date": "2026-09-01"},
            U.MANAGER,
        ),
        ERR_TRANSFER_DATE_TOO_SOON,
    )

    after = refresh_agreement(api, env)
    assert_status(after, "APPROVED")
    assert after["sale_date"] is None
    assert after["transfer_date"] is None
    assert after["version"] == before["version"]
    assert rows_of(api.list_servicing_transfers(U.MANAGER)) == []


def test_settlement_at_exactly_fifteen_days_lead_is_admitted(api,
                                                            approved_agreement):
    """
    The positive side of the boundary: a transfer date exactly fifteen days out
    settles and derives the whole downstream calendar from that date.

    PRD: "Settlement stamps `sale_date` and `transfer_date` on the agreement, computes `holdback_release_eligible_at` as the transfer date advanced by `rep_warrant_days` calendar days (the expiry of the representations and warranties), sets `holdback_retained_cents` to `holdback_cents` with `holdback_released_cents` and `holdback_applied_cents` at 0, moves the agreement to `SETTLED`, and increments its `version` by 1."

    Design: Corner/validations/transfer_date_at_exactly_fifteen_days_settles
    """
    env = approved_agreement
    agreement = F.settle(api, env["agreement_id"], sale_date="2026-08-05",
                         transfer_date="2026-08-16")

    assert_status(agreement, "SETTLED")
    assert agreement["sale_date"] == "2026-08-05"
    assert agreement["transfer_date"] == "2026-08-16"
    # rep_warrant_days is 30 on this trade, so 2026-08-16 + 30 days.
    assert agreement["holdback_release_eligible_at"] == "2026-09-15"
    assert agreement["purchase_price_cents"] == 472004
    assert agreement["holdback_cents"] == 28320
    assert agreement["settlement_wire_cents"] == 443684
    assert_holdback_split(agreement, retained=28320, released=0, applied=0)

    transfers = rows_of(
        api.list_servicing_transfers(
            U.MANAGER, {"purchase_agreement_id": env["agreement_id"]})
    )
    assert len(transfers) == 1
    assert_status(transfers[0], "IN_PROGRESS")
    assert transfers[0]["transfer_date"] == "2026-08-16"
    assert_readiness(transfers[0], "NOT_READY")

    portfolio = F.read_portfolio(api, env["portfolio_id"])
    assert_status(portfolio, "UNDER_CONTRACT")


def test_notice_effective_date_must_equal_the_transfer_date(api, settled_trade):
    """
    A disclosed effective date one day off the agreement's transfer date is
    refused before any lead-day arithmetic runs.

    PRD: "Next, the disclosed `effective_date` must equal the agreement's `transfer_date` exactly, else `ERR_NOTICE_EFFECTIVE_DATE_MISMATCH` (HTTP 422)."

    Design: Corner/validations/notice_effective_date_that_differs_from_the_transfer_date_is_rejected
    """
    env = settled_trade
    assert env["agreement"]["transfer_date"] == "2026-09-01"

    # A 2026-09-02 effective date would have carried a 32-day lead and been
    # comfortably compliant, yet it never reaches the lead-day test.
    validate_error(
        api.create_notice(
            env["transfer_id"],
            {
                "notice_type": "TRANSFEROR_15DAY",
                "loan_id": env["loan_ids"][0],
                "effective_date": "2026-09-02",
            },
            U.make_seller_headers(env["seller_id"]),
        ),
        ERR_NOTICE_EFFECTIVE_DATE_MISMATCH,
    )

    transfer = F.read_transfer(api, env["transfer_id"])
    assert transfer["notice_count"] == 0
    assert_dimensions(transfer, notice="NOT_STARTED")
    assert rows_of(
        api.list_transfer_notices(env["transfer_id"], U.MANAGER)
    ) == []

    notice = F.send_notice(api, env["transfer_id"], env["loan_ids"][0],
                           env["seller_id"], effective_date="2026-09-01")
    assert notice["lead_days"] == 31
    assert notice["compliance_status"] == "COMPLIANT"
    assert len(
        rows_of(api.list_transfer_notices(env["transfer_id"], U.MANAGER))
    ) == 1


def _settled_trade_without_the_fourth_line(api: ApiClient) -> JsonDict:
    """
    Pool T marketed and settled with its fourth loan pulled off the tape before
    publication, so the trade carries only three of the seller's four loans.
    """
    env = build_stratified_package(api)
    assert env["package"]["stratum_count"] == 4
    excluded_loan_id = env["loan_ids"][3]
    line = next(row for row in env["tape_lines"]
                if row["loan_id"] == excluded_loan_id)
    F.set_tape_line_inclusion(api, line["id"], False,
                              exclusion_reason="DOCUMENT_DEFECT")
    env["tape_lines"] = F.list_tape_lines(api, env["package_id"])
    env["included_loan_ids"] = [row["loan_id"] for row in env["tape_lines"]
                               if row["included"]]
    env["excluded_loan_id"] = excluded_loan_id
    env["excluded_line_id"] = line["id"]

    build_published_package(api, env)
    build_live_bid(api, env)
    build_awarded_trade(api, env)
    build_settled_trade(api, env)
    return env


def test_notice_and_error_case_for_a_loan_off_the_tape_are_refused(api):
    """
    A live loan of the same pool that was excluded from the awarded tape can
    neither be noticed nor complained about, and stays ACTIVE throughout.

    PRD: "Then the named loan must actually be on the awarded tape with its line `included`, else `ERR_LOAN_NOT_ON_TAPE` (HTTP 422) — the same rule, and the same code, guards the error cases of §3.8."

    Design: Corner/validations/notice_for_a_loan_off_the_tape_is_rejected
    """
    env = _settled_trade_without_the_fourth_line(api)
    off_tape = env["excluded_loan_id"]

    assert data_of(
        api.get_tape_line(env["excluded_line_id"], U.ANALYST)
    )["included"] is False
    assert env["package"]["tape_loan_count"] == 3
    assert env["package"]["tape_upb_cents"] == 30000150
    assert env["package"]["reserve_price_cents"] == 122248
    assert env["bid"]["bid_value_cents"] == 354002
    assert env["agreement"]["purchase_price_cents"] == 354003

    validate_error(
        api.create_notice(
            env["transfer_id"],
            {
                "notice_type": "TRANSFEROR_15DAY",
                "loan_id": off_tape,
                "effective_date": "2026-09-01",
            },
            U.make_seller_headers(env["seller_id"]),
        ),
        ERR_LOAN_NOT_ON_TAPE,
    )
    validate_error(
        api.create_error_case(
            env["transfer_id"],
            {
                "loan_id": off_tape,
                "category": "ESCROW",
                "description": "escrow disbursement missed after transfer",
            },
            U.COMPLIANCE,
        ),
        ERR_LOAN_NOT_ON_TAPE,
    )

    # Exclusion is a fact about the tape line, never a loan state.
    assert_status(F.read_loan(api, off_tape), "ACTIVE")
    transfer = F.read_transfer(api, env["transfer_id"])
    assert transfer["notice_count"] == 0
    assert rows_of(api.list_error_cases(
        U.COMPLIANCE, {"servicing_transfer_id": env["transfer_id"]})) == []


def test_attestation_closes_on_the_three_loan_tape_alone(api):
    """
    The included tape defines the notice universe too: noticing the three tape
    loans is enough for attestation, with nothing owed on the excluded loan.

    PRD: "Attestation has two gates, reported in this order: every loan with an included tape line must have at least one `TRANSFEROR_15DAY` or `COMBINED` notice on this transfer, else `ERR_NOTICE_COMPLIANCE_INCOMPLETE` (HTTP 409); and `late_notice_count` must be exactly 0, else `ERR_NOTICE_LATE` (HTTP 409)."

    Design: Corner/validations/notice_for_a_loan_off_the_tape_is_rejected
    """
    env = _settled_trade_without_the_fourth_line(api)
    assert len(env["included_loan_ids"]) == 3
    assert env["excluded_loan_id"] not in env["included_loan_ids"]

    build_attested_notices(api, env)
    transfer = F.read_transfer(api, env["transfer_id"])
    assert transfer["notice_count"] == 3
    assert transfer["late_notice_count"] == 0
    assert_dimensions(transfer, notice="NOTICES_ATTESTED")
    assert_status(F.read_loan(api, env["excluded_loan_id"]), "ACTIVE")


def _case_resolved_on_september_tenth(api: ApiClient) -> JsonDict:
    """
    A completed transfer carrying one case opened 2026-09-05, acknowledged the
    same day and resolved on 2026-09-10 with no remediation.
    """
    env = build_completed_transfer(api)
    F.set_clock(api, "2026-09-05T00:00:00Z")
    case = F.open_error_case(
        api, env["transfer_id"], env["included_loan_ids"][0],
        category="LOSS_MIT",
        description="trial modification plan not honoured by the new servicer")
    F.acknowledge_case(api, case["id"], env["buyer_id"])
    F.set_clock(api, "2026-09-10T00:00:00Z")
    env["case"] = F.resolve_case(
        api, case["id"], env["buyer_id"], remediation_cents=0,
        resolution_note="plan reinstated with the original terms")
    env["case_id"] = case["id"]
    return env


def test_reopen_sixty_one_days_after_resolution_is_refused(api):
    """
    A reopen filed one day past the sixty-day window is refused and the case
    stays exactly as it was resolved.

    PRD: "A `ComplianceOfficer` may reopen a `RESOLVED` case only within 60 calendar days of its `resolved_at`; later than that the attempt is refused with `ERR_REOPEN_WINDOW_EXPIRED` (HTTP 422)."

    Design: Corner/validations/reopen_after_the_sixty_day_window_is_rejected
    """
    env = _case_resolved_on_september_tenth(api)
    resolved = env["case"]
    assert resolved["resolved_at"] == "2026-09-10T00:00:00.000Z"
    assert_status(resolved, "RESOLVED")
    assert resolved["reopen_count"] == 0
    # The window is measured from resolved_at, and this case met its statutory
    # deadlines, so the refusal cannot be a knock-on of an SLA breach.
    assert resolved["ack_breached"] is False
    assert resolved["resolution_breached"] is False

    F.set_clock(api, "2026-11-10T00:00:00Z")
    validate_error(
        api.reopen_error_case(
            env["case_id"],
            {"reason": "borrower says the plan lapsed again in November"},
            U.COMPLIANCE,
        ),
        ERR_REOPEN_WINDOW_EXPIRED,
    )

    after = F.read_error_case(api, env["case_id"])
    assert_status(after, "RESOLVED")
    assert after["reopen_count"] == 0
    assert after["resolved_at"] == "2026-09-10T00:00:00.000Z"
    assert after["version"] == resolved["version"]


def test_reopen_at_exactly_sixty_days_is_admitted(api):
    """
    The inclusive edge of the same window: a reopen on day sixty cycles the case
    back to REOPENED and clears its acknowledgement and resolution stamps.

    PRD: "Inside the window, a reopen supplies a `reason`, increments `reopen_count` by 1, clears `acknowledged_at` and `resolved_at` back to null while leaving both breach flags at their worst observed values, and moves the case `RESOLVED → REOPENED`; the buyer then acknowledges again, this time measured against the unchanged `ack_deadline_at`, so a second pass through the loop will usually set `ack_breached`."

    Design: Corner/validations/reopen_after_the_sixty_day_window_is_rejected
    """
    env = _case_resolved_on_september_tenth(api)

    F.set_clock(api, "2026-11-09T00:00:00Z")
    reopened = F.reopen_case(
        api, env["case_id"],
        reason="borrower says the plan lapsed again in November")

    assert_status(reopened, "REOPENED")
    assert reopened["reopen_count"] == 1
    assert reopened["acknowledged_at"] is None
    assert reopened["resolved_at"] is None


def test_holdback_release_one_day_before_eligibility_is_refused(
        api, completed_transfer):
    """
    The representation-and-warranty date gates the release: one day early the
    call is refused even though the version token supplied is current.

    PRD: "The money must be eligible: the bound servicing transfer must be `COMPLETED` and the current logical clock date must have reached `holdback_release_eligible_at`, else `ERR_HOLDBACK_NOT_ELIGIBLE` (HTTP 409)."

    Design: Corner/validations/holdback_release_before_the_eligibility_date_is_rejected
    """
    env = completed_transfer
    F.set_clock(api, "2026-09-30T00:00:00Z")
    before = refresh_agreement(api, env)
    assert_status(before, "SETTLED")
    # transfer_date 2026-09-01 advanced by rep_warrant_days 30.
    assert before["holdback_release_eligible_at"] == "2026-10-01"
    assert before["holdback_retained_cents"] == 28320

    validate_error(
        api.create_holdback_release(
            env["agreement_id"],
            {"expected_purchase_agreement_version": before["version"]},
            U.COMPLIANCE_2,
        ),
        ERR_HOLDBACK_NOT_ELIGIBLE,
    )

    after = refresh_agreement(api, env)
    assert_status(after, "SETTLED")
    assert after["version"] == before["version"]
    assert_holdback_split(after, retained=28320, released=0, applied=0)


def test_holdback_release_on_the_eligibility_date_then_exhausts(
        api, completed_transfer):
    """
    On the eligibility date an unblemished transfer releases the whole holdback,
    landing in HOLDBACK_RELEASED, after which a second release has nothing left.

    PRD: "And there must be something left to release: `holdback_retained_cents` must be greater than 0, else `ERR_HOLDBACK_EXHAUSTED` (HTTP 409)."

    Design: Corner/validations/holdback_release_before_the_eligibility_date_is_rejected
    """
    env = completed_transfer
    F.set_clock(api, "2026-10-01T00:00:00Z")
    before = refresh_agreement(api, env)
    assert before["holdback_cents"] == 28320

    released = F.release_holdback(api, env["agreement_id"], before["version"])
    # No error case was ever logged, so the concentration ratio is 0.00 and the
    # tier releases the full retained balance with no remediation charge.
    assert_holdback_split(released, retained=0, released=28320, applied=0)
    # The indemnification period runs to 2026-10-16, so closure is not reached.
    assert_status(released, "HOLDBACK_RELEASED")

    exhausted = refresh_agreement(api, env)
    validate_error(
        api.create_holdback_release(
            env["agreement_id"],
            {"expected_purchase_agreement_version": exhausted["version"]},
            U.COMPLIANCE_2,
        ),
        ERR_HOLDBACK_EXHAUSTED,
    )

    final = refresh_agreement(api, env)
    assert_status(final, "HOLDBACK_RELEASED")
    assert_holdback_split(final, retained=0, released=28320, applied=0)
    assert final["holdback_cents"] == 28320


def test_bidder_scoring_below_the_risk_floor_is_refused(api, published_package):
    """
    An otherwise eligible bidder scoring 37 out of 100 is refused on risk alone,
    and the refused bid leaves the package untouched.

    PRD: "That last band is also a hard gate: a bid whose named bidder scores below 40 under `PRE_AWARD` is refused with `ERR_BIDDER_RISK_TIER_TOO_HIGH` (HTTP 422)."

    Design: Corner/validations/bidder_below_the_minimum_risk_score_is_rejected
    """
    env = published_package
    version_at_publication = env["package"]["version"]
    charlie = F.create_counterparty(api, THIN_BUYER)

    score = validate_success(
        api.get_risk_score(charlie["id"], U.MANAGER, {"variant": "PRE_AWARD"})
    )
    assert score["rating_penalty"] == 25
    assert score["capital_penalty"] == 30
    assert score["approval_penalty"] == 8
    assert score["complaint_penalty"] == 0
    assert score["sla_penalty"] == 0
    assert score["score"] == 37
    assert score["tier"] == "HIGH"

    # Charlie is ACTIVE and holds the pool's own FNMA approval, so eligibility
    # passes and only the score gate can fire.
    validate_error(
        api.create_bid(
            env["package_id"],
            {
                "bidder_id": charlie["id"],
                "price_bps": 118,
                "holdback_pct": 6,
                "expected_bid_package_version": env["package_version"],
            },
            U.make_buyer_headers(charlie["id"]),
        ),
        ERR_BIDDER_RISK_TIER_TOO_HIGH,
    )

    package = refresh_package(api, env)
    assert package["bid_count"] == 0
    assert package["version"] == version_at_publication


def test_suspension_reports_eligibility_ahead_of_the_risk_floor(
        api, published_package):
    """
    Suspending the same thin bidder swaps the refusal to eligibility, while the
    well-capitalised acquirer clears both gates on the identical package.

    PRD: "The bidder must be eligible — `ACTIVE` and holding the agency approval matching the portfolio's `agency_type` — else `ERR_BIDDER_NOT_ELIGIBLE`; and its `PRE_AWARD` risk score must be at least 40, else `ERR_BIDDER_RISK_TIER_TOO_HIGH`."

    Design: Corner/validations/bidder_below_the_minimum_risk_score_is_rejected
    """
    env = published_package
    charlie = F.create_counterparty(api, THIN_BUYER)
    F.suspend_counterparty(api, charlie["id"])

    validate_error(
        api.create_bid(
            env["package_id"],
            {
                "bidder_id": charlie["id"],
                "price_bps": 118,
                "holdback_pct": 6,
                "expected_bid_package_version": env["package_version"],
            },
            U.make_buyer_headers(charlie["id"]),
        ),
        ERR_BIDDER_NOT_ELIGIBLE,
    )

    bravo_score = validate_success(
        api.get_risk_score(env["buyer_id"], U.MANAGER)
    )
    assert bravo_score["score"] == 92
    assert bravo_score["tier"] == "LOW"

    package = refresh_package(api, env)
    bid = F.submit_bid(api, env["package_id"], env["buyer_id"],
                       package["version"])
    assert_status(bid, "SUBMITTED")
    assert bid["bid_value_cents"] == 472002
