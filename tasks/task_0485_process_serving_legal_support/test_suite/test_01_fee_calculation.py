"""Fee composition: quoted vs final variants, tiered attempts, rush labor uplift,
round-per-line-then-sum precision, and the invoice-line breakdown.

All money is whole cents (PRD section 2.7 / 3.12). Expected values are computed
against the PRD constants: BASE 7500, PER_PAGE 25, RUSH 5000, SKIP_TRACE 9000,
FREE_ATTEMPTS 1, TIER1_MAX 3, ATTEMPT_RATE1 2500, ATTEMPT_RATE2 4000,
STAKEOUT 12000, RUSH_LABOR_MULT 1.5.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    make_server_headers,
    make_notary_headers,
    find_lines,
    setup_reference_data,
    create_submitted_request,
    offer_to_server,
    log_attempt,
    create_filing,
    get_request,
    get_invoice_lines,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _drive_dual_variant_request(api):
    """Non-rush 3-page request: submit (quoted), then 4 attempts on 4 distinct
    days + 1 stakeout + PERSONAL service + notarized affidavit + accepted filing.
    Returns the sr id. Mirrors the difficulty recipe exactly.
    """
    county, server, client = setup_reference_data(
        deposit_cents=100_000,
        county_overrides={
            "name": "Alameda", "state_code": "CA", "e_file_enabled": True,
            "min_diligent_attempts": 3, "filing_fee_cents": 4000,
            "max_concurrent_filings": 2,
        },
    )
    sr = create_submitted_request(
        client["id"], county["id"],
        documents=[{"doc_type": "SUMMONS", "page_count": 3}],
        recipient_name="John Doe", rush=False, skip_trace_requested=False,
    )
    sid = sr["id"]
    svr = make_server_headers(server["id"])
    asg = offer_to_server(sid, server["id"], sr["version"])
    get_success_data(api.accept_assignment(asg["id"], svr))
    log_attempt(asg["id"], server["id"], "2026-01-01T09:00:00Z", "NO_ANSWER")
    log_attempt(asg["id"], server["id"], "2026-01-02T09:00:00Z", "EVADED")
    log_attempt(asg["id"], server["id"], "2026-01-03T09:00:00Z", "NO_ANSWER")
    log_attempt(asg["id"], server["id"], "2026-01-04T09:00:00Z", "CONTACT_MADE")
    get_success_data(
        api.create_stakeout(
            asg["id"],
            {"window_start_utc": "2026-01-05T06:00:00Z", "window_end_utc": "2026-01-05T10:00:00Z"},
            svr,
        )
    )
    get_success_data(
        api.record_service(
            sid,
            {"assignment_id": asg["id"], "service_type": "PERSONAL", "served_at_utc": "2026-01-04T09:05:00Z"},
            svr,
        )
    )
    aff = get_success_data(api.list_request_affidavits(sid, svr))[0]
    get_success_data(api.sign_affidavit(aff["id"], svr))
    get_success_data(api.notarize_affidavit(aff["id"], make_notary_headers("notary-1")))
    filing = create_filing(sid, aff["id"], "2026-01-06T00:00:00Z", "2026-01-06T01:00:00Z")
    get_success_data(api.set_filing_state(filing["id"], {"to_status": "SUBMITTED"}, DISPATCHER))
    get_success_data(api.set_filing_state(filing["id"], {"to_status": "ACCEPTED"}, DISPATCHER))
    return sid


def test_quoted_fee_three_page_non_rush(api):
    """PRD 3.2: "the provisional `quoted_fee_cents` is computed using the quoted
    variant of the fee calculation (Section 3.8)."
    PRD 3.12: "The base line is a flat 75 dollars (7,500 cents). The printing line
    is the total page count across all of the request's documents multiplied by
    25 cents per page, rounded up to whole cents."
    PRD 3.12: "its billable attempt count is fixed at 0 (no attempts exist yet at
    submission), and its stakeout and filing lines are absent."

    Design: Difficulty/dual_variant_calc/service_fee_quoted_vs_final_diverge_on_servicerequest
    """
    sid = _drive_dual_variant_request(api)
    sr = get_request(sid)
    assert sr["quoted_fee_cents"] == 7575, f"expected quoted 7575, got {sr['quoted_fee_cents']}"


def test_final_fee_diverges_from_quoted_after_realized_activity(api):
    """PRD 3.12: "The **final** variant is recomputed into `final_fee_cents` on
    every billable side effect and frozen at completion: its billable attempt
    count is the number of attempts whose `superseded` flag is false under the
    request's non-superseded assignments, regardless of outcome; its stakeout
    line covers each stakeout whose status is `SCHEDULED` or `COMPLETED`...; and
    its filing line covers the non-voided `FILING` lines."
    PRD 3.12: "the count of attempts billed at the first rate is the count of
    attempts up to and including the third, less the one free attempt, but never
    below zero; the count billed at the second rate is the count of attempts
    beyond the third, never below zero."

    Design: Difficulty/dual_variant_calc/service_fee_quoted_vs_final_diverge_on_servicerequest
    """
    sid = _drive_dual_variant_request(api)
    sr = get_request(sid)
    # BASE 7500 + PRINTING 75 + attempt(2*2500 + 1*4000 = 9000) + stakeout 12000 + filing 4000.
    assert sr["final_fee_cents"] == 32575, f"expected final 32575, got {sr['final_fee_cents']}"
    assert sr["final_fee_cents"] != sr["quoted_fee_cents"], "final must diverge from quoted"


def test_tiered_attempts_with_rush_labor_uplift(api):
    """PRD 3.12: "Per-attempt labor is tiered. ... The first 1 billable attempt is
    free. The next tier ... is charged at 25 dollars (2,500 cents) each. Attempts
    beyond the third are charged at 40 dollars (4,000 cents) each."
    PRD 3.12: "a rush uplift is applied as an explicit ordered step, and only when
    the request is `rush`: it applies solely to the labor lines — the attempt line
    plus the stakeout line — at a multiplier of 1.5. The uplift is the labor total
    multiplied by 0.5 ..., rounded up to whole cents, and is added to the subtotal.
    This rush uplift is computed after tiering, never before."

    Design: Difficulty/combinatorial_formula/service_fee_tiered_attempt_plus_rush_labor_uplift_mode_a
    """
    county, server, client = setup_reference_data(
        deposit_cents=100_000,
        county_overrides={
            "name": "Napa", "state_code": "CA", "e_file_enabled": True,
            "min_diligent_attempts": 1, "filing_fee_cents": 4000, "max_concurrent_filings": 2,
        },
    )
    sr = create_submitted_request(
        client["id"], county["id"],
        documents=[{"doc_type": "SUBPOENA", "page_count": 4}],
        rush=True, skip_trace_requested=True,
    )
    sid = sr["id"]
    svr = make_server_headers(server["id"])
    asg = offer_to_server(sid, server["id"], sr["version"])
    get_success_data(api.accept_assignment(asg["id"], svr))
    log_attempt(asg["id"], server["id"], "2026-01-01T08:00:00Z", "NO_ANSWER")
    log_attempt(asg["id"], server["id"], "2026-01-01T20:00:00Z", "CONTACT_MADE")
    get_success_data(
        api.record_service(
            sid,
            {"assignment_id": asg["id"], "service_type": "PERSONAL", "served_at_utc": "2026-01-01T20:05:00Z"},
            svr,
        )
    )
    aff = get_success_data(api.list_request_affidavits(sid, svr))[0]
    get_success_data(api.sign_affidavit(aff["id"], svr))
    get_success_data(api.notarize_affidavit(aff["id"], make_notary_headers("notary-7")))
    filing = create_filing(sid, aff["id"], "2026-01-01T22:00:00Z", "2026-01-01T23:00:00Z")
    get_success_data(api.set_filing_state(filing["id"], {"to_status": "SUBMITTED"}, DISPATCHER))
    get_success_data(api.set_filing_state(filing["id"], {"to_status": "ACCEPTED"}, DISPATCHER))
    sr_final = get_request(sid)
    # 7500 + 100 + RUSH 5000 + SKIP 9000 + attempt 2500 + filing 4000 = 28100; uplift ceil(2500*0.5)=1250.
    assert sr_final["final_fee_cents"] == 29350, f"expected 29350, got {sr_final['final_fee_cents']}"


def test_round_per_line_then_sum_via_invoice_breakdown(api):
    """PRD 2.7: "The pinned rounding order is round-per-line-then-sum: each line
    amount is rounded up to a whole number of cents using the ceiling function at
    the line level, and the rounded line amounts are then summed."
    PRD 3.12: "an `amount_cents` already rounded to whole cents at the line level".

    Design: Difficulty/combinatorial_formula/service_fee_round_per_line_then_sum_mode_b
    """
    county, server, client = setup_reference_data(
        deposit_cents=100_000,
        county_overrides={
            "name": "Sonoma", "state_code": "CA", "e_file_enabled": True,
            "min_diligent_attempts": 1, "filing_fee_cents": 4000, "max_concurrent_filings": 2,
        },
    )
    sr = create_submitted_request(
        client["id"], county["id"],
        documents=[{"doc_type": "SUBPOENA", "page_count": 4}],
        rush=True, skip_trace_requested=True,
    )
    sid = sr["id"]
    svr = make_server_headers(server["id"])
    asg = offer_to_server(sid, server["id"], sr["version"])
    get_success_data(api.accept_assignment(asg["id"], svr))
    log_attempt(asg["id"], server["id"], "2026-01-01T08:00:00Z", "NO_ANSWER")
    log_attempt(asg["id"], server["id"], "2026-01-01T20:00:00Z", "CONTACT_MADE")
    get_success_data(
        api.record_service(
            sid,
            {"assignment_id": asg["id"], "service_type": "PERSONAL", "served_at_utc": "2026-01-01T20:05:00Z"},
            svr,
        )
    )
    sr_final = get_request(sid)
    # No filing this time: 7500+100+5000+9000+2500 = 24100; uplift ceil(2500*0.5)=1250 => 25350.
    assert sr_final["final_fee_cents"] == 25350, f"expected 25350, got {sr_final['final_fee_cents']}"
    lines = get_invoice_lines(sid)
    printing = find_lines(lines, "PRINTING")
    assert len(printing) == 1 and printing[0]["amount_cents"] == 100, "PRINTING line must be ceil(4*25)=100"
    attempt = find_lines(lines, "ATTEMPT")
    assert len(attempt) == 1 and attempt[0]["amount_cents"] == 2500, "ATTEMPT line must be 2500"
    base = find_lines(lines, "BASE")
    assert len(base) == 1 and base[0]["amount_cents"] == 7500, "BASE line must be 7500"


def test_quoted_fee_is_server_computed_not_client_supplied(api):
    """PRD 2.4: "`version` — an integer that begins at its initial value..." (system
    field); PRD 3.2: "the provisional `quoted_fee_cents` is computed using the
    quoted variant of the fee calculation". The 3-page non-rush quote is 7575.

    Design: Corner/entities/servicerequest_quoted_fee_computed_input_ignored
    """
    county = get_success_data(
        api.create_county({"name": "Merced", "state_code": "CA", "min_diligent_attempts": 1}, TEST_USERS["admin_headers"])
    )
    client = get_success_data(
        api.create_client({"firm_name": "Cmp Law", "email": "p@law.com"}, TEST_USERS["admin_headers"])
    )
    sr = get_success_data(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "R",
             "service_address": "5 St", "service_lat": 37.3, "service_lng": -120.5}, DISPATCHER
        )
    )
    get_success_data(api.create_document(sr["id"], {"doc_type": "SUMMONS", "page_count": 3}, DISPATCHER))
    submitted = validate_success(api.submit_request(sr["id"], DISPATCHER), 200)
    assert submitted["quoted_fee_cents"] == 7575, f"expected 7575, got {submitted['quoted_fee_cents']}"


def test_invoice_lines_breakdown_after_submit(api):
    """PRD 3.2: "the initial invoice lines are generated — a `BASE` line, a
    `PRINTING` line covering the documents' pages..."
    PRD 3.12: "The base line is a flat 75 dollars (7,500 cents). The printing line
    is the total page count across all of the request's documents multiplied by 25
    cents per page, rounded up to whole cents."

    Design: Corner/endpoints/invoice_lines_computed_read_breakdown
    """
    county = get_success_data(
        api.create_county({"name": "Inv County", "state_code": "CA", "min_diligent_attempts": 1}, TEST_USERS["admin_headers"])
    )
    client = get_success_data(
        api.create_client({"firm_name": "Iv Law", "email": "iv@law.com"}, TEST_USERS["admin_headers"])
    )
    sr = get_success_data(
        api.create_service_request(
            {"client_id": client["id"], "county_id": county["id"], "recipient_name": "R",
             "service_address": "1 St", "service_lat": 36.0, "service_lng": -119.0}, DISPATCHER
        )
    )
    get_success_data(api.create_document(sr["id"], {"doc_type": "SUMMONS", "page_count": 2}, DISPATCHER))
    submitted = validate_success(api.submit_request(sr["id"], DISPATCHER), 200)
    assert submitted["quoted_fee_cents"] == 7550, f"expected 7550, got {submitted['quoted_fee_cents']}"
    lines = validate_success(api.list_invoice_lines(sr["id"], DISPATCHER))
    base = find_lines(lines, "BASE")
    assert len(base) == 1 and base[0]["amount_cents"] == 7500
    printing = find_lines(lines, "PRINTING")
    assert len(printing) == 1 and printing[0]["amount_cents"] == 50, "2 pages * 25 = 50"


def test_first_attempt_is_free_and_fee_visible_immediately(api):
    """PRD 3.12: "The first 1 billable attempt is free."
    PRD 3.4: "Every attempt log recomputes the request's `distinct_attempt_days`
    and its `final_fee_cents`."
    PRD 2.10: each cascade effect is immediate; the recomputed `final_fee_cents`
    is visible on the next read.

    Design: Corner/consistency_model/immediate_consistency_final_fee_visible_in_same_flow
    """
    county, server, client, sr, asg = _setup_active_one_page(api)
    log_attempt(asg["id"], server["id"], "2026-01-01T09:00:00Z", "NO_ANSWER")
    out = get_request(sr["id"])
    assert out["distinct_attempt_days"] == 1
    # BASE 7500 + PRINTING 25 (1 page); the single attempt is free => 7525.
    assert out["final_fee_cents"] == 7525, f"expected 7525, got {out['final_fee_cents']}"


def _setup_active_one_page(api):
    county, server, client = setup_reference_data(
        deposit_cents=100_000, county_overrides={"min_diligent_attempts": 1}
    )
    sr = create_submitted_request(
        client["id"], county["id"], documents=[{"doc_type": "SUMMONS", "page_count": 1}]
    )
    asg = offer_to_server(sr["id"], server["id"], sr["version"])
    get_success_data(api.accept_assignment(asg["id"], make_server_headers(server["id"])))
    return county, server, client, sr, asg


def test_mode_a_quoted_fee_includes_rush_and_skip_trace_lines(api):
    """PRD 3.12: "The rush line is 50 dollars (5,000 cents) when the request is
    `rush`, otherwise zero. The skip-trace line is 90 dollars (9,000 cents) when a
    skip-trace was requested, otherwise zero."
    PRD 3.12: the quoted variant "billable attempt count is fixed at 0 ... and its
    stakeout and filing lines are absent." For a rush + skip-trace 4-page request
    the quote is BASE 7500 + PRINTING 100 + RUSH 5000 + SKIP 9000 = 21600.

    Design: Difficulty/combinatorial_formula/service_fee_tiered_attempt_plus_rush_labor_uplift_mode_a
    """
    county, server, client = setup_reference_data(
        deposit_cents=100_000,
        county_overrides={
            "name": "NapaQ", "state_code": "CA", "e_file_enabled": True,
            "min_diligent_attempts": 1, "filing_fee_cents": 4000, "max_concurrent_filings": 2,
        },
    )
    sr = create_submitted_request(
        client["id"], county["id"],
        documents=[{"doc_type": "SUBPOENA", "page_count": 4}],
        rush=True, skip_trace_requested=True,
    )
    submitted = get_request(sr["id"])
    assert submitted["quoted_fee_cents"] == 21600, f"expected 21600, got {submitted['quoted_fee_cents']}"


def test_mode_b_rush_and_skip_trace_invoice_lines_present(api):
    """PRD 3.2: "the initial invoice lines are generated — a `BASE` line, a
    `PRINTING` line ..., a `RUSH` line if and only if `rush` is true, and a
    `SKIP_TRACE` line if and only if `skip_trace_requested` is true."
    PRD 3.12: "The rush line is 50 dollars (5,000 cents) ... The skip-trace line is
    90 dollars (9,000 cents)". Verified via the per-line breakdown.

    Design: Difficulty/combinatorial_formula/service_fee_round_per_line_then_sum_mode_b
    """
    county, server, client = setup_reference_data(
        deposit_cents=100_000,
        county_overrides={
            "name": "SonomaQ", "state_code": "CA", "e_file_enabled": True,
            "min_diligent_attempts": 1, "filing_fee_cents": 4000, "max_concurrent_filings": 2,
        },
    )
    sr = create_submitted_request(
        client["id"], county["id"],
        documents=[{"doc_type": "SUBPOENA", "page_count": 4}],
        rush=True, skip_trace_requested=True,
    )
    lines = get_invoice_lines(sr["id"])
    rush = find_lines(lines, "RUSH")
    assert len(rush) == 1 and rush[0]["amount_cents"] == 5000, "RUSH line must be 5000"
    skip = find_lines(lines, "SKIP_TRACE")
    assert len(skip) == 1 and skip[0]["amount_cents"] == 9000, "SKIP_TRACE line must be 9000"
