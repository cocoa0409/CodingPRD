"""Extension negotiations: the proposed/countered cycle and round cap, terminal decline,
OCC on the assignment version, supersede-on-accept, the term limit, and license re-resolution."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_clinician_headers,
    create_extension_payload,
)
from test_helpers.fixtures import provision, get_assignment_data

RECRUITER = TEST_USERS["recruiter_headers"]


def _open_extension(api, ctx, additional_weeks=13, pay=5300, bill=14200, headers=RECRUITER):
    v = get_assignment_data(api, ctx.asg_id)["version"]
    resp = api.create_extension(ctx.asg_id, create_extension_payload(v, additional_weeks, pay, bill), headers)
    return validate_success(resp, 201)


# --- Difficulty: proposed/countered cycle until the round cap ---
def test_counter_cycle_returns_to_proposed(api):
    """PRD §3.8: "A COUNTER flips the request between PROPOSED and COUNTERED, replaces the
    proposed_* terms with the counter terms, increments round_count, and updates
    last_actor_role; it is legal only while round_count is below three, else
    ERR_NEGOTIATION_ROUNDS_EXHAUSTED. This proposed–countered alternation continues until
    three negotiation rounds are used."

    Design: Difficulty/non_linear_state_machine/extension_negotiation_cycles_proposed_countered_until_round_cap
    """
    ctx = provision(api, contract_stage="executed")
    ext = _open_extension(api, ctx)
    clin = make_clinician_headers(ctx.clin_id)
    c1 = validate_success(api.respond_extension(ext["id"], {
        "action": "COUNTER", "proposed_additional_weeks": 13,
        "proposed_pay_rate_cents_per_hour": 5600, "proposed_bill_rate_cents_per_hour": 14200}, clin), 200)
    assert c1["status"] == "COUNTERED" and c1["round_count"] == 2
    assert c1["last_actor_role"] == "Clinician" and c1["proposed_pay_rate_cents_per_hour"] == 5600
    c2 = validate_success(api.respond_extension(ext["id"], {
        "action": "COUNTER", "proposed_additional_weeks": 13,
        "proposed_pay_rate_cents_per_hour": 5450, "proposed_bill_rate_cents_per_hour": 14200}, RECRUITER), 200)
    assert c2["status"] == "PROPOSED" and c2["round_count"] == 3
    assert c2["last_actor_role"] == "Recruiter" and c2["proposed_pay_rate_cents_per_hour"] == 5450


def test_third_counter_rejected_rounds_exhausted(api):
    """PRD §3.8: "it is legal only while round_count is below three, else
    ERR_NEGOTIATION_ROUNDS_EXHAUSTED."

    Design: Difficulty/non_linear_state_machine/extension_negotiation_cycles_proposed_countered_until_round_cap
    """
    ctx = provision(api, contract_stage="executed")
    ext = _open_extension(api, ctx)
    clin = make_clinician_headers(ctx.clin_id)
    validate_success(api.respond_extension(ext["id"], {
        "action": "COUNTER", "proposed_additional_weeks": 13,
        "proposed_pay_rate_cents_per_hour": 5600, "proposed_bill_rate_cents_per_hour": 14200}, clin), 200)
    validate_success(api.respond_extension(ext["id"], {
        "action": "COUNTER", "proposed_additional_weeks": 13,
        "proposed_pay_rate_cents_per_hour": 5450, "proposed_bill_rate_cents_per_hour": 14200}, RECRUITER), 200)
    validate_error(api.respond_extension(ext["id"], {
        "action": "COUNTER", "proposed_additional_weeks": 13,
        "proposed_pay_rate_cents_per_hour": 5550, "proposed_bill_rate_cents_per_hour": 14200}, clin),
        ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value)
    exts, _ = validate_paginated(api.list_assignment_extensions(ctx.asg_id, RECRUITER))
    assert exts[0]["round_count"] == 3 and exts[0]["proposed_pay_rate_cents_per_hour"] == 5450


def test_extension_declined_is_terminal(api):
    """PRD §3.8: "A DECLINE moves the request to DECLINED and stamps resolved_at."
    PRD §2.8: "7. State admissibility — the target's current state admits the requested
    transition, else ERR_INVALID_TRANSITION"

    Design: Corner/state_machines/corner_extension_declined_is_terminal_and_second_response_rejected
    """
    ctx = provision(api, clock="2026-05-15", contract_stage="executed")
    ext = _open_extension(api, ctx)
    clin = make_clinician_headers(ctx.clin_id)
    declined = validate_success(api.respond_extension(ext["id"], {"action": "DECLINE"}, clin), 200)
    assert declined["status"] == "DECLINED" and declined["last_actor_role"] == "Clinician"
    assert declined["resolved_at"] == "2026-05-15T00:00:00.000Z"
    validate_error(api.respond_extension(ext["id"], {"action": "ACCEPT"}, RECRUITER),
                   ApiErrorId.ERR_INVALID_TRANSITION.value)
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["term_weeks"] == 13 and asg["end_date"] == "2026-09-05" and asg["extension_round_count"] == 0


def test_occ_stale_assignment_version_blocks_second_open(api):
    """PRD §2.6: "if expected_assignment_version does not equal the assignment's current
    version, the request is rejected with ERR_STALE_ASSIGNMENT_VERSION (HTTP 412)."
    PRD §3.8: "any prior extension request on the same assignment whose status is PROPOSED
    or COUNTERED is superseded and set to WITHDRAWN, each stamping resolved_at, and the
    assignment's version increments."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_assignment_version_blocks_second_extension_open
    """
    ctx = provision(api, contract_stage="executed")
    v_stale = get_assignment_data(api, ctx.asg_id)["version"]
    first = validate_success(api.create_extension(
        ctx.asg_id, create_extension_payload(v_stale, 13, 5300, 14200), RECRUITER), 201)
    assert first["status"] == "PROPOSED" and first["round_count"] == 1
    assert first["initiated_by_role"] == "Recruiter" and first["last_actor_role"] == "Recruiter"
    assert get_assignment_data(api, ctx.asg_id)["version"] == v_stale + 1
    validate_error(api.create_extension(
        ctx.asg_id, create_extension_payload(v_stale, 8, 5250, 14100), RECRUITER),
        ApiErrorId.ERR_STALE_ASSIGNMENT_VERSION.value)
    v_fresh = get_assignment_data(api, ctx.asg_id)["version"]
    second = validate_success(api.create_extension(
        ctx.asg_id, create_extension_payload(v_fresh, 8, 5250, 14100), RECRUITER), 201)
    assert second["status"] == "PROPOSED"
    exts, meta = validate_paginated(api.list_assignment_extensions(ctx.asg_id, RECRUITER))
    assert meta["total_count"] == 2
    first_now = next(e for e in exts if e["id"] == first["id"])
    assert first_now["status"] == "WITHDRAWN" and first_now["resolved_at"] is not None


def test_extension_accept_supersedes_prior_and_extends_term_and_hours(api):
    """PRD §3.8: "Accepting a request (from PROPOSED or COUNTERED) requires that the
    assignment's staffing_status is PENDING_START or ACTIVE, that the assignment's
    term_weeks plus proposed_additional_weeks does not exceed 26 (else
    ERR_TERM_LIMIT_EXCEEDED) ... On acceptance the request moves to ACCEPTED and stamps
    resolved_at; the assignment's term_weeks increases by proposed_additional_weeks, its
    end_date is recomputed, and its extension_round_count increments. The assignment's
    guaranteed_hours_total and guaranteed_hours_remaining each increase by the contract's
    weekly_guaranteed_hours multiplied by proposed_additional_weeks."

    Design: Corner/cross_cutting_complexity_layers/corner_extension_accept_supersedes_prior_request_and_extends_term_and_hours
    """
    ctx = provision(api, contract_stage="executed")
    clin = make_clinician_headers(ctx.clin_id)
    ext_long = _open_extension(api, ctx, additional_weeks=14, pay=5300, bill=14200)
    validate_error(api.respond_extension(ext_long["id"], {"action": "ACCEPT"}, clin),
                   ApiErrorId.ERR_TERM_LIMIT_EXCEEDED.value)
    exts, _ = validate_paginated(api.list_assignment_extensions(ctx.asg_id, RECRUITER))
    assert next(e for e in exts if e["id"] == ext_long["id"])["status"] == "PROPOSED"
    assert get_assignment_data(api, ctx.asg_id)["term_weeks"] == 13

    ext_ok = _open_extension(api, ctx, additional_weeks=13, pay=5300, bill=14200)
    exts2, _ = validate_paginated(api.list_assignment_extensions(ctx.asg_id, RECRUITER))
    assert next(e for e in exts2 if e["id"] == ext_long["id"])["status"] == "WITHDRAWN"
    accepted = validate_success(api.respond_extension(ext_ok["id"], {"action": "ACCEPT"}, clin), 200)
    assert accepted["status"] == "ACCEPTED" and accepted["resolved_at"] is not None
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["term_weeks"] == 26 and asg["end_date"] == "2026-12-05" and asg["extension_round_count"] == 1
    assert asg["guaranteed_hours_total"] == 936 and asg["guaranteed_hours_remaining"] == 936
    assert asg["guaranteed_hours_consumed"] == 0 and asg["guaranteed_hours_waived"] == 0
    assert asg["projected_gross_bill_cents"] == 13291200
    assert asg["projected_pay_cost_cents"] == 10046348
    assert asg["projected_margin_cents"] == 3244852 and asg["projected_margin_pct"] == 0.2441
    assert asg["covering_license_id"] == ctx.lic_id
    contracts, _ = validate_paginated(api.list_assignment_contracts(ctx.asg_id, RECRUITER))
    assert contracts[0]["term_weeks"] == 26
    assert contracts[0]["base_pay_rate_cents_per_hour"] == 5300
    assert contracts[0]["bill_rate_cents_per_hour"] == 14200


def test_extension_accept_rejected_when_license_lapses_before_new_end_date(api):
    """PRD §3.8: "and that license coverage still resolves over the assignment's start date
    through its new, longer end date (else ERR_LICENSE_COVERAGE_MISSING)."
    PRD §3.2: "its expires_on is on or after the coverage end date (an inclusive
    comparison) ... The coverage end date is the assignment's end_date, except when an
    extension is being accepted, in which case it is the new, longer end_date."

    Design: Corner/cross_cutting_complexity_layers/corner_extension_accept_rejected_when_license_lapses_before_new_end_date
    """
    ctx = provision(api, contract_stage="executed", license_overrides={"expires_on": "2026-10-31"})
    assert get_assignment_data(api, ctx.asg_id)["covering_license_id"] == ctx.lic_id
    clin = make_clinician_headers(ctx.clin_id)
    ext = _open_extension(api, ctx, additional_weeks=13, pay=5300, bill=14200)
    validate_error(api.respond_extension(ext["id"], {"action": "ACCEPT"}, clin),
                   ApiErrorId.ERR_LICENSE_COVERAGE_MISSING.value)
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["term_weeks"] == 13 and asg["end_date"] == "2026-09-05"
    assert asg["guaranteed_hours_total"] == 468 and asg["extension_round_count"] == 0
    exts, _ = validate_paginated(api.list_assignment_extensions(ctx.asg_id, RECRUITER))
    e = next(e for e in exts if e["id"] == ext["id"])
    assert e["status"] == "PROPOSED" and e["resolved_at"] is None
    contracts, _ = validate_paginated(api.list_assignment_contracts(ctx.asg_id, RECRUITER))
    assert contracts[0]["base_pay_rate_cents_per_hour"] == 5200
    assert contracts[0]["bill_rate_cents_per_hour"] == 14000
