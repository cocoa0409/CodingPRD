"""Coach certification lifecycle: the CERTIFIED -> SUSPENDED -> CERTIFIED and
CERTIFIED -> LAPSED -> CERTIFIED loops, and the depth-3 stall cascade
(PRD §3.5, §2.4)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_candidate_coach,
    create_case,
    create_certified_coach,
    create_coaching_case_payload,
    create_deposit_payload,
    create_participant,
    get_success_data,
    set_clock,
    setup_active_enrollment,
    validate_error,
    validate_success,
)


def test_coach_suspend_reinstate_cycle_closes(api, admin_headers):
    """PRD §3.5: "Suspension is explicit. A `ProgramAdmin` suspends a coach —
    only from `CERTIFIED`, otherwise `ERR_INVALID_STATE` — moving them to
    `SUSPENDED`". PRD §3.5: "A `ProgramAdmin` may reinstate a coach from either
    `SUSPENDED` or `LAPSED` — from any other state the call fails with
    `ERR_INVALID_STATE` — returning them to `CERTIFIED`".

    Design: Difficulty/non_linear_state_machine/coach_certification_cycle_loops
    """
    coach = create_candidate_coach(admin_headers, full_name="K Five",
                                   email="k5@test.org", max_caseload=5)
    certified = validate_success(api.certify_coach(coach["id"], admin_headers))
    assert certified["status"] == "CERTIFIED"
    suspended = validate_success(api.suspend_coach(coach["id"], admin_headers))
    assert suspended["status"] == "SUSPENDED"
    reinstated = validate_success(api.reinstate_coach(coach["id"], admin_headers))
    assert reinstated["status"] == "CERTIFIED"


def test_coach_lapse_and_recertification_cycle_closes(api, admin_headers):
    """PRD §3.5: "Certification decays: the first read or write of the coach
    record at or after that expiry lazily sweeps the coach from `CERTIFIED` to
    `LAPSED`". PRD §3.5: "A `ProgramAdmin` may reinstate a coach from either
    `SUSPENDED` or `LAPSED` — from any other state the call fails with
    `ERR_INVALID_STATE` — returning them to `CERTIFIED` with
    `certification_expires_at` refreshed to 365 days after the current
    logical-clock reading."

    Design: Difficulty/non_linear_state_machine/coach_certification_cycle_loops
    """
    coach = create_candidate_coach(admin_headers, full_name="K Five B",
                                   email="k5b@test.org", max_caseload=5)
    validate_success(api.certify_coach(coach["id"], admin_headers))
    # Certified at logical 2026-08-01: expires 2027-08-01. Advance past it.
    set_clock("2027-08-02T00:00:00Z", admin_headers)
    swept = validate_success(api.get_coach(coach["id"], admin_headers))
    assert swept["status"] == "LAPSED", (
        f"coach read at/after certification expiry must be lazily swept to LAPSED; "
        f"got {swept['status']}"
    )
    reinstated = validate_success(api.reinstate_coach(coach["id"], admin_headers))
    assert reinstated["status"] == "CERTIFIED"


def test_suspend_cascade_stalls_case_freezes_plan_pauses_enrollment(api, admin_headers):
    """PRD §3.5: "Link 1: every coaching case assigned to this coach in
    `INTAKE`, `PLAN_DRAFT`, or `PLAN_ACTIVE` transitions to `PLAN_STALLED`.
    Link 2: each case entering `PLAN_STALLED` freezes its `ACTIVE` goal plan to
    `FROZEN`. Link 3: each plan entering `FROZEN` pauses the match enrollment
    linked to it by `goal_plan_id` while that enrollment is `ACTIVE`, moving it
    to `MATCH_PAUSED`".

    Design: Difficulty/transitive_cascade/coach_suspend_stalls_case_plan_enrollment
    """
    ctx = setup_active_enrollment(
        admin_headers,
        pool_overrides=dict(name="Pool B", total_funded_cents=1000000,
                            income_threshold_cents=3000000,
                            match_ratio_below=0.5, match_ratio_above=0.25,
                            per_participant_cap_cents=100000),
        savings_goal_cents=500000,
    )
    validate_success(api.suspend_coach(ctx["coach"]["id"], admin_headers))
    case = validate_success(api.get_coaching_case(ctx["case"]["id"], admin_headers))
    plan = validate_success(api.get_goal_plan(ctx["plan"]["id"], admin_headers))
    enr = validate_success(api.get_match_enrollment(ctx["enrollment"]["id"], admin_headers))
    assert case["status"] == "PLAN_STALLED"
    assert plan["status"] == "FROZEN"
    assert enr["status"] == "MATCH_PAUSED"


def test_suspend_cascade_drops_caseload_and_pauses_deposits(api, admin_headers):
    """PRD §3.5: "Finally the coach's `active_caseload` is recomputed; because
    `PLAN_STALLED` is excluded from the caseload count, it drops by exactly the
    number of stalled cases." PRD §3.5: "and deposits against a paused
    enrollment are rejected with `ERR_ENROLLMENT_NOT_ACTIVE` until it resumes."

    Design: Difficulty/transitive_cascade/coach_suspend_stalls_case_plan_enrollment
    """
    ctx = setup_active_enrollment(
        admin_headers,
        pool_overrides=dict(name="Pool B", total_funded_cents=1000000,
                            income_threshold_cents=3000000,
                            match_ratio_below=0.5, match_ratio_above=0.25,
                            per_participant_cap_cents=100000),
        savings_goal_cents=500000,
    )
    validate_success(api.suspend_coach(ctx["coach"]["id"], admin_headers))
    coach = validate_success(api.get_coach(ctx["coach"]["id"], admin_headers))
    assert coach["active_caseload"] == 0, (
        f"stalled cases are excluded from active_caseload; got {coach['active_caseload']}"
    )
    resp = api.create_deposit(
        ctx["enrollment"]["id"], create_deposit_payload(10000), admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)


def test_case_open_rejected_for_candidate_coach(api, admin_headers):
    """PRD §3.4: "Three business guards apply in order: the assigned coach must
    be `CERTIFIED` (`ERR_COACH_NOT_CERTIFIED`)".

    Design: Difficulty/cross_entity_state_dependency/case_open_requires_certified_coach
    """
    coach = create_candidate_coach(admin_headers, full_name="K Thirteen",
                                   email="k13@test.org", max_caseload=10)
    participant = create_participant(admin_headers)
    resp = api.create_coaching_case(
        create_coaching_case_payload(participant["id"], coach["id"],
                                     intake_date="2026-08-01"),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_COACH_NOT_CERTIFIED)


def test_case_open_succeeds_after_certification(api, admin_headers):
    """PRD §3.4: "Three business guards apply in order: the assigned coach must
    be `CERTIFIED` (`ERR_COACH_NOT_CERTIFIED`)". PRD §3.5: "A `ProgramAdmin`
    certifies a coach — only from `CANDIDATE`, otherwise `ERR_INVALID_STATE` —
    moving them to `CERTIFIED`".

    Design: Difficulty/cross_entity_state_dependency/case_open_requires_certified_coach
    """
    coach = create_candidate_coach(admin_headers, full_name="K Thirteen B",
                                   email="k13b@test.org", max_caseload=10)
    participant = create_participant(admin_headers)
    validate_success(api.certify_coach(coach["id"], admin_headers))
    case = validate_success(
        api.create_coaching_case(
            create_coaching_case_payload(participant["id"], coach["id"],
                                         intake_date="2026-08-01"),
            admin_headers,
        ),
        expected_status=201,
    )
    assert case["status"] == "INTAKE"


def test_caseload_full_rejected(api, admin_headers):
    """PRD §3.4: "and the coach's `active_caseload` must be strictly below
    their `max_caseload` (`ERR_CASELOAD_FULL`)."

    Design: Corner/validations/caseload_full_rejected
    """
    coach = create_certified_coach(admin_headers, full_name="CCF",
                                   email="ccf@test.org", max_caseload=1)
    p1 = create_participant(admin_headers, full_name="PCF1", email="pcf1@test.org")
    p2 = create_participant(admin_headers, full_name="PCF2", email="pcf2@test.org")
    create_case(p1["id"], coach["id"], admin_headers, intake_date="2026-08-01")
    resp = api.create_coaching_case(
        create_coaching_case_payload(p2["id"], coach["id"], intake_date="2026-08-01"),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CASELOAD_FULL)
    coach_after = validate_success(api.get_coach(coach["id"], admin_headers))
    assert coach_after["active_caseload"] == 1


def test_coach_cannot_suspend_coach_returns_403(api, admin_headers):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint
    — or that fails an entity-backed ownership check — is rejected with
    `ERR_FORBIDDEN` (HTTP 403)." PRD §2.1: "it alone may create and retire
    curriculum modules, create coaches and drive certification, suspension,
    and reinstatement".

    Design: Corner/rbac/coach_cannot_suspend_coach_returns_403
    """
    from test_helpers import make_coach_headers

    c1 = create_certified_coach(admin_headers, full_name="CK1", email="ck1@test.org")
    c2 = create_certified_coach(admin_headers, full_name="CK2", email="ck2@test.org")
    resp = api.suspend_coach(c2["id"], make_coach_headers(c1["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
