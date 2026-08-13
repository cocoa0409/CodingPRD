"""Coach caseload caps and supervision governance (PRD §2.9)."""
from test_helpers import (
    ApiErrorId,
    accept_plan,
    create_coach,
    create_supervision_record,
    create_verified_supervision,
    make_family_headers,
    setup_caseload_cap_boundary,
    setup_deficit_scenario,
    validate_error,
    validate_success,
    verify_supervision_record,
)


def test_supervision_deficit_blocks_third_acceptance(api, admin_headers):
    """PRD §2.9: "First the system counts `active_caseload`; then it derives
    `required_supervision_hours` as the whole-hour floor of the caseload
    divided by the credential's divisor — 2 for an `ASSOCIATE`, 4 for a
    `CERTIFIED` coach, 6 for a `SUPERVISOR`"
    PRD §2.9: "When the verified hours are strictly less than the required
    hours, an `AVAILABLE` coach flips to `SUPERVISION_DEFICIT`; when the
    deficit clears, a `SUPERVISION_DEFICIT` coach returns to `AVAILABLE`."
    PRD §2.9: "Acceptance of a new plan while the coach sits in
    `SUPERVISION_DEFICIT` is rejected with `ERR_COACH_SUPERVISION_DEFICIT`"

    Design: Difficulty/combinatorial_formula/supervision_deficit_pinned_evaluation_order
    """
    ctx = setup_deficit_scenario()
    coach = ctx["coach"]
    plan3 = ctx["plans"][2]

    mid = validate_success(api.get_coach(coach["id"], admin_headers))
    assert mid["active_caseload"] == 2
    assert mid["required_supervision_hours"] == 1  # floor(2/2)
    assert mid["verified_supervision_hours_30d"] == 0
    # The deficit is computed AFTER acceptance #2, so #2 succeeded.
    assert mid["status"] == "SUPERVISION_DEFICIT"

    resp = api.transition_plan(
        plan3["id"], "ACTIVE", make_family_headers(ctx["family"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_COACH_SUPERVISION_DEFICIT)


def test_verified_hour_clears_deficit_and_acceptance_succeeds(api, admin_headers):
    """PRD §2.9: "when the deficit clears, a `SUPERVISION_DEFICIT` coach
    returns to `AVAILABLE`."
    PRD §2.9: "the deficit gates only new plan acceptance: plans already
    `ACTIVE` under a deficit coach keep running, and posture recomputation
    never blocks scheduling on the deficit alone."
    PRD §3.11: verification moves the record "to the terminal `VERIFIED` state,
    stamping `verified_at`, recomputing the coach's
    `verified_supervision_hours_30d`, and re-running the supervision requirement"

    Design: Difficulty/combinatorial_formula/supervision_deficit_pinned_evaluation_order
    """
    ctx = setup_deficit_scenario()
    coach, supervisor = ctx["coach"], ctx["reviewer"]
    plan3 = ctx["plans"][2]

    deficit = validate_success(api.get_coach(coach["id"], admin_headers))
    assert deficit["status"] == "SUPERVISION_DEFICIT"

    record = create_supervision_record(coach["id"], supervisor["id"], hours=1.0)
    verify_supervision_record(record["id"], supervisor["id"])

    cleared = validate_success(api.get_coach(coach["id"], admin_headers))
    assert cleared["status"] == "AVAILABLE", "1 verified hour >= 1 required hour"

    accepted = validate_success(
        api.transition_plan(
            plan3["id"], "ACTIVE", make_family_headers(ctx["family"]["id"])
        )
    )
    assert accepted["status"] == "ACTIVE"
    final = validate_success(api.get_coach(coach["id"], admin_headers))
    assert final["active_caseload"] == 3
    assert final["required_supervision_hours"] == 1  # floor(3/2)


def test_caseload_cap_twelve_boundary(api, admin_headers):
    """PRD §2.9: "A coach's `caseload_cap` is 12 for an `ASSOCIATE`, 20 for a
    `CERTIFIED` coach, and 28 for a `SUPERVISOR`."
    PRD §2.9: "acceptance when the coach's `active_caseload` has reached or
    exceeded the `caseload_cap` is rejected with `ERR_CASELOAD_CAP_REACHED` —
    at exactly the cap is a rejection, since the caseload must be strictly
    below the cap."

    Design: Corner/cross_cutting_complexity_layers/caseload_cap_twelve_boundary
    """
    ctx = setup_caseload_cap_boundary()
    coach = ctx["coach"]
    plan13 = ctx["plans"][12]

    mid = validate_success(api.get_coach(coach["id"], admin_headers))
    assert mid["active_caseload"] == 12, "acceptances 1..12 all succeeded (11 < 12)"
    assert mid["required_supervision_hours"] == 6  # floor(12/2)
    # 6 verified hours keep the coach AVAILABLE, isolating the cap gate.
    assert mid["status"] == "AVAILABLE"

    resp = api.transition_plan(
        plan13["id"], "ACTIVE", make_family_headers(ctx["family"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CASELOAD_CAP_REACHED)


def test_self_supervision_rejected(api, admin_headers):
    """PRD §2.9: "A supervision record names a `supervisor_coach_id` that must
    differ from the supervisee's `coach_id` — an attempt to make a coach their
    own supervisor is rejected with `ERR_SELF_SUPERVISION`"

    Design: Corner/validations/self_supervision_rejected
    """
    coach = create_coach("SUPERVISOR", full_name="Coach SS")
    resp = api.create_supervision_record(
        coach["id"],
        {"supervisor_coach_id": coach["id"],
         "scheduled_at": "2026-08-05T10:00:00Z", "hours": 1.0},
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SELF_SUPERVISION)


def test_non_supervisor_credential_rejected_for_supervision(api, admin_headers):
    """PRD §2.9: "the named supervisor must hold `credential_level`
    `SUPERVISOR`, otherwise the creation is rejected with
    `ERR_CREDENTIAL_INSUFFICIENT`."

    Design: Corner/validations/non_supervisor_credential_rejected_for_supervision
    """
    supervisee = create_coach("ASSOCIATE", full_name="Coach Jun")
    non_supervisor = create_coach("CERTIFIED", full_name="Coach Mid")
    resp = api.create_supervision_record(
        supervisee["id"],
        {"supervisor_coach_id": non_supervisor["id"],
         "scheduled_at": "2026-08-05T10:00:00Z", "hours": 1.0},
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_INSUFFICIENT)


def test_coach_caseload_cap_computed_from_credential(api, admin_headers):
    """PRD §2.9: "A coach's `caseload_cap` is 12 for an `ASSOCIATE`, 20 for a
    `CERTIFIED` coach, and 28 for a `SUPERVISOR`."
    PRD §4: "| POST | `/api/coaches` | Create a coach in `AVAILABLE` | PracticeAdmin |"

    Design: Corner/entities/coach_caseload_cap_computed_from_credential
    """
    associate = create_coach("ASSOCIATE", full_name="Coach A")
    supervisor = create_coach("SUPERVISOR", full_name="Coach S")
    certified = create_coach("CERTIFIED", full_name="Coach C")
    assert associate["caseload_cap"] == 12
    assert certified["caseload_cap"] == 20
    assert supervisor["caseload_cap"] == 28
    assert associate["active_caseload"] == 0
    assert associate["status"] == "AVAILABLE"
