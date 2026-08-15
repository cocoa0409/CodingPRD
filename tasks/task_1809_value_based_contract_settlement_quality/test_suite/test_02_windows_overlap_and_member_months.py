"""Year/span window semantics, overlap rules, member-months mid-month rule."""
from test_helpers import (
    ApiErrorId, MANAGER, add_record, build_pipeline, compute_run,
    create_claim_payload, create_span_payload, create_year_payload,
    make_contract, make_draft_run, make_member, make_program, make_span,
    make_year, setup_org, validate_error, validate_paginated, validate_success,
)


def test_performance_year_half_open_adjacency_allowed(api, payer_admin_headers):
    """PRD §3.4: "Two years of the same contract may not have intersecting windows; adjacency is permitted, so a new year whose `period_start` equals an existing year's `period_end` is allowed. An intersecting create is rejected with `ERR_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/performance_year_half_open_adjacency_allowed
    """
    org = setup_org(member_specs=[], practice_count=0)
    contract = make_contract(
        org["program"]["id"], org["group"]["id"], effective_end="2028-01-01"
    )
    y1 = make_year(contract["id"], year_label=2026)
    assert y1["year_status"] == "SETUP"

    adjacent = api.create_performance_year(
        create_year_payload(
            contract["id"], year_label=2027,
            period_start="2027-01-01", period_end="2028-01-01",
        ),
        payer_admin_headers,
    )
    adj_data = validate_success(adjacent, 201)
    assert adj_data["year_status"] == "SETUP", (
        "start == existing period_end shares no instant of the half-open window"
    )

    interior = api.create_performance_year(
        create_year_payload(
            contract["id"], year_label=2028,
            period_start="2026-06-01", period_end="2027-06-01",
        ),
        payer_admin_headers,
    )
    validate_error(interior, ApiErrorId.ERR_PERIOD_OVERLAP)


def test_performance_year_tail_overlap_rejected(api, payer_admin_headers):
    """PRD §3.4: "Two years of the same contract may not have intersecting windows; adjacency is permitted, so a new year whose `period_start` equals an existing year's `period_end` is allowed. An intersecting create is rejected with `ERR_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/performance_year_half_open_adjacency_allowed
    """
    org = setup_org(member_specs=[], practice_count=0)
    contract = make_contract(
        org["program"]["id"], org["group"]["id"], effective_end="2028-01-01"
    )
    make_year(contract["id"], year_label=2026)

    tail_adjacent = api.create_performance_year(
        create_year_payload(
            contract["id"], year_label=2027,
            period_start="2027-01-01", period_end="2028-01-01",
        ),
        payer_admin_headers,
    )
    validate_success(tail_adjacent, 201)

    tail_overlap = api.create_performance_year(
        create_year_payload(
            contract["id"], year_label=2028,
            period_start="2026-12-15", period_end="2027-12-15",
        ),
        payer_admin_headers,
    )
    validate_error(tail_overlap, ApiErrorId.ERR_PERIOD_OVERLAP)


def test_eligibility_span_closed_interval_touching_rejected(api, payer_admin_headers):
    """PRD §3.2: "Because the interval is closed, two spans of the same member may not share even a single calendar date; an overlapping create is rejected with `ERR_SPAN_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/eligibility_span_closed_interval_touching_rejected
    """
    program = make_program()
    member = make_member(program["id"])
    make_span(member["id"], start_date="2026-01-01", end_date="2026-06-30")

    touching = api.create_eligibility_span(
        create_span_payload(member["id"], start_date="2026-06-30", end_date="2026-12-31"),
        payer_admin_headers,
    )
    validate_error(touching, ApiErrorId.ERR_SPAN_OVERLAP)

    disjoint = api.create_eligibility_span(
        create_span_payload(member["id"], start_date="2026-07-01", end_date="2026-12-31"),
        payer_admin_headers,
    )
    validate_success(disjoint, 201)


def test_eligibility_span_touching_prior_start_rejected(api, payer_admin_headers):
    """PRD §3.2: "Because the interval is closed, two spans of the same member may not share even a single calendar date; an overlapping create is rejected with `ERR_SPAN_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/eligibility_span_closed_interval_touching_rejected
    """
    program = make_program()
    member = make_member(program["id"])
    make_span(member["id"], start_date="2026-01-01", end_date="2026-06-30")

    touching_before = api.create_eligibility_span(
        create_span_payload(member["id"], start_date="2025-12-15", end_date="2026-01-01"),
        payer_admin_headers,
    )
    validate_error(touching_before, ApiErrorId.ERR_SPAN_OVERLAP)

    disjoint_before = api.create_eligibility_span(
        create_span_payload(member["id"], start_date="2025-12-15", end_date="2025-12-31"),
        payer_admin_headers,
    )
    validate_success(disjoint_before, 201)


def test_year_open_requires_contract_active(api, payer_admin_headers):
    """PRD §3.4: "From `SETUP` the admin opens attribution (`SETUP → ATTRIBUTION_OPEN`); this requires the contract to be in `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`) and the year window to be contained within the contract term — `period_start` on or after `effective_start` and `period_end` on or before `effective_end` (`ERR_YEAR_OUTSIDE_TERM`)."

    Design: Difficulty/cross_entity_state_dependency/year_open_requires_contract_active
    """
    org = setup_org(member_specs=[], practice_count=0)
    contract = make_contract(org["program"]["id"], org["group"]["id"], activate=False)
    year = make_year(contract["id"])

    blocked = api.open_attribution(year["id"], payer_admin_headers)
    validate_error(blocked, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    validate_success(api.activate_contract(contract["id"], MANAGER))
    opened = api.open_attribution(year["id"], payer_admin_headers)
    assert validate_success(opened)["year_status"] == "ATTRIBUTION_OPEN"


def test_year_open_rejected_after_contract_terminated(api, payer_admin_headers):
    """PRD §3.4: "From `SETUP` the admin opens attribution (`SETUP → ATTRIBUTION_OPEN`); this requires the contract to be in `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`) and the year window to be contained within the contract term — `period_start` on or after `effective_start` and `period_end` on or before `effective_end` (`ERR_YEAR_OUTSIDE_TERM`)."
    PRD §3.3: "Termination (`ACTIVE → TERMINATED`) requires that no performance year of the contract is currently in any of `ATTRIBUTION_OPEN`, `ATTRIBUTION_LOCKED`, `MEASURING`, `RECONCILING`, or `SETTLED`; an in-flight year produces `ERR_YEARS_IN_FLIGHT`."

    Design: Difficulty/cross_entity_state_dependency/year_open_requires_contract_active
    """
    org = setup_org(member_specs=[], practice_count=0)
    contract = make_contract(org["program"]["id"], org["group"]["id"])
    year = make_year(contract["id"])

    # The year is in SETUP (not in-flight), so termination succeeds, and the
    # subsequent open-attribution still fails: the contract is not ACTIVE.
    terminated = api.terminate_contract(contract["id"], MANAGER)
    assert validate_success(terminated)["contract_status"] == "TERMINATED"
    blocked = api.open_attribution(year["id"], payer_admin_headers)
    validate_error(blocked, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)


def test_claim_service_date_period_end_boundary(api, claims_processor_headers):
    """PRD §3.7: "The `service_date` must lie on or after the year's `period_start` and strictly before its `period_end` (`ERR_CLAIM_OUTSIDE_PERIOD`)."

    Design: Corner/validations/claim_service_date_period_end_boundary
    """
    org = setup_org(member_specs=[("M-001", 1980, "2026-01-01", "2026-12-31")], practice_count=1)
    contract = make_contract(org["program"]["id"], org["group"]["id"])
    year = make_year(contract["id"])
    member_id = org["members"][0]["id"]

    last_day = api.create_claim(
        create_claim_payload(
            year["id"], member_id, claim_ref="CL-IN",
            service_date="2026-12-31", paid_amount_cents=1000,
        ),
        claims_processor_headers,
    )
    validate_success(last_day, 201)

    at_period_end = api.create_claim(
        create_claim_payload(
            year["id"], member_id, claim_ref="CL-OUT",
            service_date="2027-01-01", paid_amount_cents=1000,
        ),
        claims_processor_headers,
    )
    validate_error(at_period_end, ApiErrorId.ERR_CLAIM_OUTSIDE_PERIOD)


def test_year_open_outside_contract_term_rejected(api, payer_admin_headers):
    """PRD §3.4: "From `SETUP` the admin opens attribution (`SETUP → ATTRIBUTION_OPEN`); this requires the contract to be in `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`) and the year window to be contained within the contract term — `period_start` on or after `effective_start` and `period_end` on or before `effective_end` (`ERR_YEAR_OUTSIDE_TERM`)."

    Design: Corner/validations/year_open_outside_contract_term_rejected
    """
    org = setup_org(member_specs=[], practice_count=0)
    contract = make_contract(org["program"]["id"], org["group"]["id"])
    year = make_year(
        contract["id"], year_label=2027,
        period_start="2027-01-01", period_end="2028-01-01",
    )
    resp = api.open_attribution(year["id"], payer_admin_headers)
    validate_error(resp, ApiErrorId.ERR_YEAR_OUTSIDE_TERM)


def test_member_months_mid_month_boundary(api, attribution_analyst_headers):
    """PRD §3.5: "For each calendar month intersecting the half-open year window, the system looks at the 15th of that month (the mid-month day). If the 15th lies on or after `period_start` and strictly before `period_end`, and if the member has at least one `ACTIVE` `EligibilitySpan` whose inclusive `start_date` is on or before the 15th and whose inclusive `end_date` is on or after the 15th, the month counts as one member-month."
    PRD §3.5: "Compute re-evaluates `member_months` for every record per the mid-month rule, transitions every record from `PROVISIONAL` to `CONFIRMED` (a `PROVISIONAL → CONFIRMED` transition on each record), and stamps `attributed_member_count` with the number of `CONFIRMED` records."

    Design: Corner/entities/member_months_mid_month_boundary
    """
    org = setup_org(
        member_specs=[
            ("M-A", 1980, "2026-01-15", "2026-12-31"),
            ("M-B", 1975, "2026-01-16", "2026-12-31"),
        ],
        practice_count=1,
    )
    pipe = build_pipeline(org, stage="OPEN")
    year_id = pipe["year"]["id"]
    run = make_draft_run(year_id)
    rec_a = add_record(run["id"], org["members"][0]["id"], org["practices"][0]["id"])
    rec_b = add_record(run["id"], org["members"][1]["id"], org["practices"][0]["id"])
    assert rec_a["record_status"] == "PROVISIONAL"
    assert rec_b["record_status"] == "PROVISIONAL"
    computed = compute_run(run["id"])
    assert computed["attributed_member_count"] == 2

    data, _meta = validate_paginated(api.list_attribution_records(attribution_analyst_headers))
    by_member = {r["member_id"]: r for r in data}
    ma = by_member[org["members"][0]["id"]]
    mb = by_member[org["members"][1]["id"]]
    assert ma["member_months"] == 12, (
        f"span starting on the 15th covers Jan 15 -> 12 months, got {ma['member_months']}"
    )
    assert mb["member_months"] == 11, (
        f"span starting on the 16th misses Jan 15 -> 11 months, got {mb['member_months']}"
    )
    assert ma["record_status"] == "CONFIRMED"
    assert mb["record_status"] == "CONFIRMED"


def test_attribution_record_no_eligible_months_rejected(api, attribution_analyst_headers):
    """PRD §3.5: "Record creation enforces a five-part referential check in cascade order — the practice must belong to the contract's group (`ERR_PRACTICE_GROUP_MISMATCH`), the practice must be in `ACTIVE` (`ERR_PRACTICE_INACTIVE`), the member must belong to the contract's program (`ERR_MEMBER_PROGRAM_MISMATCH`), the member must be in `ELIGIBLE` (`ERR_MEMBER_DISENROLLED`), and the member must have at least one mid-month-eligible month within the year window (`ERR_MEMBER_NO_ELIGIBLE_MONTHS`)."

    Design: Corner/entities/attribution_record_no_eligible_months_rejected
    """
    org = setup_org(
        member_specs=[("M-C", 1980, "2026-01-16", "2026-01-31")], practice_count=1
    )
    pipe = build_pipeline(org, stage="OPEN")
    run = make_draft_run(pipe["year"]["id"])
    resp = api.create_attribution_record(
        run["id"],
        {"member_id": org["members"][0]["id"], "practice_id": org["practices"][0]["id"]},
        attribution_analyst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_NO_ELIGIBLE_MONTHS)
