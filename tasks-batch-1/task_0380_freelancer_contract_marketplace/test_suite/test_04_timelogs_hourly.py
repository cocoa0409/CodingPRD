"""Hourly time-tracking: per-log floor-then-sum cap, the zero-verified submit block,
the same-milestone half-open overlap check, the cross-contract daily aggregate cap, and
timelog rejection.

Queue A: combinatorial_formula / combinatorial_hourly_round_per_log_then_sum;
         boundary_precision_check / boundary_zero_verified_timelogs_block_submit;
         resource_temporal_overlap / overlap_same_milestone_halfopen_interval;
         resource_temporal_overlap / overlap_cross_contract_daily_aggregate_cap.
Queue B: endpoints / timelog_reject_sets_rejected.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    create_timelog_payload,
    make_client_headers, make_freelancer_headers,
    create_active_hourly_contract, add_hourly_milestone, add_timelog, verify_timelog,
    create_active_contract, fund_milestone,
)


# ─── Round-per-log then sum (HOURLY milestone cap) ────────────────────
def test_hourly_cap_rounds_per_log_then_sums(api):
    """PRD §3.4: "for each VERIFIED time log on the milestone the per-log cents are the
    billable minutes divided by sixty, multiplied by the contract's agreed hourly rate,
    and floored to a whole cent; the milestone's amount_cents is the sum of those per-log
    figures. Because each log is floored independently before summing, the order of
    summation does not matter."

    Two logs of 50 and 55 minutes at rate 5000 cents/hr:
    floor(50/60*5000)=4166, floor(55/60*5000)=4583, sum = 8749 (not floor(105/60*5000)=8750).

    Design: Difficulty/combinatorial_formula/combinatorial_hourly_round_per_log_then_sum
    """
    ctx = create_active_hourly_contract(rate_cents=5000, skills=("sql",), hourly_cap_hours=8)
    m = add_hourly_milestone(ctx, ordinal=1)
    t1 = add_timelog(ctx, m["id"], "2026-03-02", 540, 590, "log a")   # 50 min
    t2 = add_timelog(ctx, m["id"], "2026-03-02", 600, 655, "log b")   # 55 min
    verify_timelog(ctx, t1["id"])
    verify_timelog(ctx, t2["id"])
    milestone = validate_success(
        api.get_milestone_in_contract(ctx["contract"]["id"], m["id"], ctx["client_headers"]), 200)
    assert milestone["amount_cents"] == 8749


def test_hourly_cap_single_log_floored(api):
    """PRD §3.4: "the per-log cents are the billable minutes divided by sixty, multiplied
    by the contract's agreed hourly rate, and floored to a whole cent".

    One log of 50 minutes at rate 5000 cents/hr: floor(50/60*5000) = floor(4166.66..) = 4166.

    Design: Difficulty/combinatorial_formula/combinatorial_hourly_round_per_log_then_sum
    """
    ctx = create_active_hourly_contract(rate_cents=5000, skills=("sql",), hourly_cap_hours=8)
    m = add_hourly_milestone(ctx, ordinal=1)
    t1 = add_timelog(ctx, m["id"], "2026-03-07", 540, 590, "one log")  # 50 min
    verify_timelog(ctx, t1["id"])
    milestone = validate_success(
        api.get_milestone_in_contract(ctx["contract"]["id"], m["id"], ctx["client_headers"]), 200)
    assert milestone["amount_cents"] == 4166


# ─── Zero verified timelogs blocks submit ─────────────────────────────
def test_submit_blocked_with_only_logged_timelog(api):
    """PRD §3.4: "If the milestone has no VERIFIED logs at all, its amount_cents is zero,
    and a milestone with zero verified time cannot be submitted."
    PRD §3.5: "for an hourly milestone it additionally requires that at least one VERIFIED
    time log exists for the milestone; a submission attempt on an hourly milestone with no
    verified logs is rejected with ERR_NO_VERIFIED_TIMELOGS."

    Design: Difficulty/boundary_precision_check/boundary_zero_verified_timelogs_block_submit
    """
    ctx = create_active_hourly_contract(rate_cents=4000, skills=("x",), hourly_cap_hours=8)
    m = add_hourly_milestone(ctx, ordinal=1)
    add_timelog(ctx, m["id"], "2026-03-03", 540, 600, "unverified")  # LOGGED, never verified
    # PRD §3.5: submission "is permitted only when the milestone is FUNDED and the contract
    # is ACTIVE, and for an hourly milestone it additionally requires" a VERIFIED log. The
    # FUNDED precondition is primary; fund first so the verified-timelog gate is the one tested.
    fund_milestone(ctx, m["id"])
    res = api.submit_milestone(ctx["contract"]["id"], m["id"], ctx["freelancer_headers"])
    validate_error(res, "ERR_NO_VERIFIED_TIMELOGS", expected_status=409)
    milestone = validate_success(
        api.get_milestone_in_contract(ctx["contract"]["id"], m["id"], ctx["client_headers"]), 200)
    assert milestone["amount_cents"] == 0


def test_submit_blocked_with_no_timelogs_at_all(api):
    """PRD §3.4: "If the milestone has no VERIFIED logs at all, its amount_cents is zero,
    and a milestone with zero verified time cannot be submitted."
    PRD §3.5: a submission on an hourly milestone with no verified logs "is rejected with
    ERR_NO_VERIFIED_TIMELOGS."

    Design: Difficulty/boundary_precision_check/boundary_zero_verified_timelogs_block_submit
    """
    ctx = create_active_hourly_contract(rate_cents=4000, skills=("x",), hourly_cap_hours=8)
    m = add_hourly_milestone(ctx, ordinal=1)
    # PRD §3.5: the FUNDED precondition is primary ("permitted only when the milestone is
    # FUNDED ... additionally requires" a VERIFIED log). Fund first so the verified-timelog
    # gate — with zero logs of any kind — is the operative check.
    fund_milestone(ctx, m["id"])
    res = api.submit_milestone(ctx["contract"]["id"], m["id"], ctx["freelancer_headers"])
    validate_error(res, "ERR_NO_VERIFIED_TIMELOGS", expected_status=409)
    milestone = validate_success(
        api.get_milestone_in_contract(ctx["contract"]["id"], m["id"], ctx["client_headers"]), 200)
    assert milestone["amount_cents"] == 0


# ─── Same-milestone half-open overlap ─────────────────────────────────
def test_overlapping_interval_same_milestone_rejected(api):
    """PRD §3.4: "the new half-open interval on work_date must not intersect any existing
    LOGGED or VERIFIED interval on the same milestone and the same date ... A violation is
    rejected with ERR_TIMELOG_OVERLAP."

    A new [570,630) interval intersects an existing [540,600) (570 < 600).

    Design: Difficulty/resource_temporal_overlap/overlap_same_milestone_halfopen_interval
    """
    ctx = create_active_hourly_contract(rate_cents=4000, skills=("x",), hourly_cap_hours=10)
    m = add_hourly_milestone(ctx, ordinal=1)
    add_timelog(ctx, m["id"], "2026-03-04", 540, 600, "first")
    res = api.create_timelog(
        ctx["contract"]["id"],
        create_timelog_payload(m["id"], "2026-03-04", 570, 630, "overlap"),
        ctx["freelancer_headers"])
    validate_error(res, "ERR_TIMELOG_OVERLAP", expected_status=409)


def test_adjacent_interval_same_milestone_allowed(api):
    """PRD §3.4: "Adjacency is explicitly allowed — an interval ending at minute 120 and
    another beginning at minute 120 do not overlap, because touching endpoints are
    permitted."

    An existing [540,600) and a new [600,660) touch at 600 and must both be accepted.

    Design: Difficulty/resource_temporal_overlap/overlap_same_milestone_halfopen_interval
    """
    ctx = create_active_hourly_contract(rate_cents=4000, skills=("x",), hourly_cap_hours=10)
    m = add_hourly_milestone(ctx, ordinal=1)
    add_timelog(ctx, m["id"], "2026-03-08", 540, 600, "first")
    res = api.create_timelog(
        ctx["contract"]["id"],
        create_timelog_payload(m["id"], "2026-03-08", 600, 660, "adjacent"),
        ctx["freelancer_headers"])
    second = validate_success(res, 201)
    assert second["status"] == "LOGGED"
    assert second["billable_minutes"] == 60


# ─── Cross-contract daily aggregate cap ───────────────────────────────
def test_cross_contract_daily_cap_exceeded(api):
    """PRD §3.4: "summing the freelancer's VERIFIED and LOGGED billable minutes across all
    of that freelancer's contracts on the same work_date, plus the minutes of the new
    interval, must not exceed the global daily ceiling of 720 minutes, which is twelve
    hours ... a breach is rejected with ERR_DAILY_HOURS_CAP_EXCEEDED."

    660 existing minutes on contract C1 + a new 90-minute log on C2 = 750 > 720.

    Design: Difficulty/resource_temporal_overlap/overlap_cross_contract_daily_aggregate_cap
    """
    from test_helpers import (
        create_client, create_freelancer, create_job_posting_payload,
        create_proposal_payload, accept_payload, activate_contract_payload,
        create_milestone_payload,
    )
    client = create_client()
    ch = make_client_headers(client["id"])
    freelancer = create_freelancer(skills=["x"], tax_id_on_file=True)
    fh = make_freelancer_headers(freelancer["id"])

    def build_active_hourly():
        posting = validate_success(api.create_job_posting(
            create_job_posting_payload(client["id"], billing_type="HOURLY",
                                       budget_cents=8000, required_skills=["x"]), ch), 201)
        proposal = validate_success(api.create_proposal(
            create_proposal_payload(posting["id"], freelancer["id"], bid_amount_cents=4000), fh), 201)
        validate_success(api.accept_proposal(proposal["id"], accept_payload("CLIENT"), ch), 200)
        contracts = validate_success(api.list_client_contracts(client["id"], ch), 200)
        contract = contracts[-1]
        contract = validate_success(api.activate_contract(
            contract["id"], activate_contract_payload(sow_text="hourly", hourly_cap_hours=24), ch), 200)
        m = validate_success(api.create_milestone(
            contract["id"], create_milestone_payload(amount_cents=100, ordinal=1), ch), 201)
        return contract, m

    c1, m1 = build_active_hourly()
    # 360 + 300 = 660 minutes on C1, all on 2026-03-05.
    validate_success(api.create_timelog(c1["id"],
        create_timelog_payload(m1["id"], "2026-03-05", 0, 360, "block1"), fh), 201)
    validate_success(api.create_timelog(c1["id"],
        create_timelog_payload(m1["id"], "2026-03-05", 360, 660, "block2"), fh), 201)

    c2, m2 = build_active_hourly()
    res = api.create_timelog(c2["id"],
        create_timelog_payload(m2["id"], "2026-03-05", 700, 790, "90 more"), fh)
    validate_error(res, "ERR_DAILY_HOURS_CAP_EXCEEDED", expected_status=409)


def test_cross_contract_daily_cap_at_boundary_allowed(api):
    """PRD §3.4: the freelancer's summed LOGGED+VERIFIED minutes for the date plus the new
    interval "must not exceed the global daily ceiling of 720 minutes". Exactly 720 is at
    the ceiling and must be permitted (the breach is on exceeding, not reaching, 720).

    660 existing minutes on C1 + a new 60-minute log on C2 = exactly 720.

    Design: Difficulty/resource_temporal_overlap/overlap_cross_contract_daily_aggregate_cap
    """
    from test_helpers import (
        create_client, create_freelancer, create_job_posting_payload,
        create_proposal_payload, accept_payload, activate_contract_payload,
        create_milestone_payload,
    )
    client = create_client()
    ch = make_client_headers(client["id"])
    freelancer = create_freelancer(skills=["x"], tax_id_on_file=True)
    fh = make_freelancer_headers(freelancer["id"])

    def build_active_hourly():
        posting = validate_success(api.create_job_posting(
            create_job_posting_payload(client["id"], billing_type="HOURLY",
                                       budget_cents=8000, required_skills=["x"]), ch), 201)
        proposal = validate_success(api.create_proposal(
            create_proposal_payload(posting["id"], freelancer["id"], bid_amount_cents=4000), fh), 201)
        validate_success(api.accept_proposal(proposal["id"], accept_payload("CLIENT"), ch), 200)
        contracts = validate_success(api.list_client_contracts(client["id"], ch), 200)
        contract = contracts[-1]
        contract = validate_success(api.activate_contract(
            contract["id"], activate_contract_payload(sow_text="hourly", hourly_cap_hours=24), ch), 200)
        m = validate_success(api.create_milestone(
            contract["id"], create_milestone_payload(amount_cents=100, ordinal=1), ch), 201)
        return contract, m

    c1, m1 = build_active_hourly()
    validate_success(api.create_timelog(c1["id"],
        create_timelog_payload(m1["id"], "2026-03-09", 0, 360, "block1"), fh), 201)
    validate_success(api.create_timelog(c1["id"],
        create_timelog_payload(m1["id"], "2026-03-09", 360, 660, "block2"), fh), 201)

    c2, m2 = build_active_hourly()
    res = api.create_timelog(c2["id"],
        create_timelog_payload(m2["id"], "2026-03-09", 700, 760, "exactly 60 more"), fh)
    created = validate_success(res, 201)
    assert created["billable_minutes"] == 60


# ─── Timelog reject ───────────────────────────────────────────────────
def test_timelog_reject_sets_rejected(api):
    """PRD §3.4: "Rejecting a log requires it to be in LOGGED, moves it to REJECTED, and
    has no further effect".
    PRD §3.4: the milestone amount sums "for each VERIFIED time log on the milestone" — a
    REJECTED log is excluded, so amount_cents stays zero.

    Design: Corner/endpoints/timelog_reject_sets_rejected
    """
    ctx = create_active_hourly_contract(rate_cents=4000, skills=("x",), hourly_cap_hours=8)
    m = add_hourly_milestone(ctx, ordinal=1)
    t = add_timelog(ctx, m["id"], "2026-03-06", 540, 600, "log")
    rejected = validate_success(api.reject_timelog(ctx["contract"]["id"], t["id"], ctx["client_headers"]), 200)
    assert rejected["status"] == "REJECTED"
    milestone = validate_success(
        api.get_milestone_in_contract(ctx["contract"]["id"], m["id"], ctx["client_headers"]), 200)
    assert milestone["amount_cents"] == 0
