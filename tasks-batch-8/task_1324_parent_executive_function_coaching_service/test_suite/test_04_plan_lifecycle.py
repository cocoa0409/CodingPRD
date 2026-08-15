"""Coaching plan lifecycle: supersession, completion gates, discharge, posture,
and OCC on plan creation (PRD §3.3, §2.7)."""
from test_helpers import (
    ApiErrorId,
    accept_plan,
    create_approved_intake,
    create_coach,
    create_plan_for_client,
    create_plan_payload,
    draft_plan_with_goal,
    get_success_data,
    make_coach_headers,
    make_family_headers,
    propose_plan,
    purchase_package,
    schedule_session_ok,
    setup_active_plan_scenario,
    transition_family,
    validate_error,
    validate_success,
    add_client,
    activate_family,
    create_family,
)


def test_goal_carry_forward_on_plan_supersede(api, admin_headers):
    """PRD §3.3: "If the client already has another plan in `ACTIVE`, that plan
    is moved to `SUPERSEDED`; its goals still in `SET` or `IN_PROGRESS` are
    moved to `CARRIED_FORWARD` with `carried_to_plan_id` pointing at the newly
    accepted plan and `resolved_at` stamped"
    PRD §3.3: "The new plan starts in `DRAFT` and is stamped with a
    `revision_number` equal to one plus the count of pre-existing plans for the
    client."

    Design: Corner/state_machines/goal_carry_forward_on_plan_supersede
    """
    ctx = setup_active_plan_scenario(account_name="Fam CF", primary_email="cf@example.com")
    client, coach, intake = ctx["clients"][0], ctx["coach"], ctx["intakes"][0]
    plan1 = ctx["plans"][0]
    fam_h = make_family_headers(ctx["family"]["id"])
    add_goal_resp = get_success_data(api.list_goals(plan1["id"], admin_headers))
    assert len(add_goal_resp) == 1
    # A second non-terminal goal on plan 1.
    g2 = get_success_data(
        api.create_goal(plan1["id"], {"title": "G2", "target_date": "2026-09-15"},
                        make_coach_headers(coach["id"]))
    )

    plan2 = create_plan_for_client(client["id"], coach["id"], intake["id"], "BIWEEKLY")
    assert plan2["revision_number"] == 2
    get_success_data(
        api.create_goal(plan2["id"], {"title": "G3", "target_date": "2026-10-01"},
                        make_coach_headers(coach["id"]))
    )
    propose_plan(plan2["id"], coach["id"])
    accepted = validate_success(api.transition_plan(plan2["id"], "ACTIVE", fam_h))
    assert accepted["status"] == "ACTIVE"

    plan1_after = validate_success(api.get_plan(plan1["id"], admin_headers))
    assert plan1_after["status"] == "SUPERSEDED"
    goals = validate_success(api.list_goals(plan1["id"], admin_headers))
    by_id = {g["id"]: g for g in goals}
    for goal in goals:
        assert goal["status"] == "CARRIED_FORWARD"
        assert goal["carried_to_plan_id"] == plan2["id"]
        assert goal["resolved_at"] is not None
    assert g2["id"] in by_id


def test_plan_complete_with_unresolved_goals_rejected(api):
    """PRD §3.3: "A coach may move an `ACTIVE` plan to `COMPLETED` provided the
    acting coach is the plan's `coach_id` (`ERR_FORBIDDEN_SCOPE`), every goal
    of the plan has reached a terminal state — `ACHIEVED`, `DROPPED`, or
    `CARRIED_FORWARD` — else `ERR_GOALS_NOT_RESOLVED`, and no session remains
    in `SCHEDULED` attendance, else `ERR_PLAN_HAS_OPEN_SESSIONS`."

    Design: Corner/state_machines/plan_complete_with_unresolved_goals_rejected
    """
    ctx = setup_active_plan_scenario(account_name="Fam GR", primary_email="gr@example.com")
    plan, coach = ctx["plans"][0], ctx["coach"]
    resp = api.transition_plan(plan["id"], "COMPLETED", make_coach_headers(coach["id"]))
    validate_error(resp, ApiErrorId.ERR_GOALS_NOT_RESOLVED)


def test_plan_complete_with_open_sessions_rejected(api, admin_headers):
    """PRD §3.3: "every goal of the plan has reached a terminal state —
    `ACHIEVED`, `DROPPED`, or `CARRIED_FORWARD` — else
    `ERR_GOALS_NOT_RESOLVED`, and no session remains in `SCHEDULED` attendance,
    else `ERR_PLAN_HAS_OPEN_SESSIONS`."

    Design: Corner/state_machines/plan_complete_with_open_sessions_rejected
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam OS",
        primary_email="os@example.com",
        package={"track": "INDIVIDUAL", "credits_total": 1},
    )
    plan, coach, goal = ctx["plans"][0], ctx["coach"], ctx["goals"][0]
    package = ctx["packages"][0]
    get_success_data(
        api.transition_goal(goal["id"], "ACHIEVED", make_coach_headers(coach["id"]))
    )
    schedule_session_ok(plan["id"], coach["id"], package["id"],
                        "2026-08-05T15:00:00Z", "2026-08-05T16:00:00Z")
    resp = api.transition_plan(plan["id"], "COMPLETED", make_coach_headers(coach["id"]))
    validate_error(resp, ApiErrorId.ERR_PLAN_HAS_OPEN_SESSIONS)


def test_client_discharge_blocked_with_active_plan(api, admin_headers):
    """PRD §3.1: "Discharge, moving a client from `ACTIVE` or `PAUSED` to the
    terminal `DISCHARGED`, is refused while any plan of the client remains
    `ACTIVE` (`ERR_CLIENT_HAS_ACTIVE_PLAN`)"

    Design: Corner/state_machines/client_discharge_blocked_with_active_plan
    """
    ctx = setup_active_plan_scenario(account_name="Fam DC", primary_email="dc@example.com")
    client, plan = ctx["clients"][0], ctx["plans"][0]
    fam_h = make_family_headers(ctx["family"]["id"])

    resp = api.transition_client(client["id"], "DISCHARGED", admin_headers)
    validate_error(resp, ApiErrorId.ERR_CLIENT_HAS_ACTIVE_PLAN)

    terminated = validate_success(api.transition_plan(plan["id"], "TERMINATED", fam_h))
    assert terminated["status"] == "TERMINATED"
    discharged = validate_success(
        api.transition_client(client["id"], "DISCHARGED", admin_headers)
    )
    assert discharged["status"] == "DISCHARGED"


def test_plan_posture_recovers_after_family_reactivation(api, admin_headers):
    """PRD §3.3: "The plan's `posture` is a computed field with two values: the
    plan is `SCHEDULABLE`, or it is `SCHEDULING_BLOCKED` when any of four
    conditions holds — the family is not `ACTIVE`, the client is not `ACTIVE`,
    the plan's coach is `INACTIVE`, or the family holds no package of track
    `INDIVIDUAL` in `ACTIVE` status whose `credits_remaining` minus
    `reserved_count` is at least 1."
    PRD §3.1: "an administrator may suspend the family (moving it to
    `SUSPENDED`), which forces a posture recompute that drives every `ACTIVE`
    plan of every client of the family to `SCHEDULING_BLOCKED`" and
    reinstatement "recomputes the posture of all `ACTIVE` plans of the family's
    clients."

    Design: Corner/cross_cutting_complexity_layers/plan_posture_recovers_after_family_reactivation
    """
    ctx = setup_active_plan_scenario(
        account_name="Fam PO",
        primary_email="po@example.com",
        package={"track": "INDIVIDUAL", "credits_total": 1},
    )
    plan = ctx["plans"][0]
    family_id = ctx["family"]["id"]

    posture0 = validate_success(api.get_plan(plan["id"], admin_headers))["posture"]
    assert posture0 == "SCHEDULABLE"

    transition_family(family_id, "SUSPENDED")
    posture1 = validate_success(api.get_plan(plan["id"], admin_headers))["posture"]
    assert posture1 == "SCHEDULING_BLOCKED"

    transition_family(family_id, "ACTIVE")
    posture2 = validate_success(api.get_plan(plan["id"], admin_headers))["posture"]
    assert posture2 == "SCHEDULABLE"


def test_occ_plan_create_stale_client_version(api, admin_headers):
    """PRD §2.7: "Creating a coaching plan for a client requires the request
    body to carry `expected_client_version`, holding the `version` of the
    Client as the caller last observed it. If another writer has advanced the
    client's `version` since that observation — for any reason — the create is
    rejected with `ERR_STALE_CLIENT_VERSION` (HTTP 412)."
    PRD §3.3: "any existing plan of the client in `DRAFT` or `PROPOSED` is
    moved to `SUPERSEDED` by the system"

    Design: Corner/cross_cutting_complexity_layers/occ_plan_create_stale_client_version
    """
    family = create_family("Fam OC", "oc2@example.com")
    client = add_client(family["id"], full_name="Kid OC", date_of_birth="2015-09-15")
    activate_family(family["id"])
    coach = create_coach("CERTIFIED", full_name="Coach OC")
    intake = create_approved_intake(client["id"], family["id"], coach["id"])
    coach_h = make_coach_headers(coach["id"])

    stale_version = client["version"]
    plan1 = get_success_data(
        api.create_plan(
            client["id"],
            create_plan_payload(coach["id"], intake["id"], stale_version),
            coach_h,
        )
    )
    # The first create advanced Client.version; replaying the stale view fails.
    resp = api.create_plan(
        client["id"],
        create_plan_payload(coach["id"], intake["id"], stale_version,
                            cadence="BIWEEKLY"),
        coach_h,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CLIENT_VERSION)

    fresh_version = validate_success(api.get_client(client["id"], admin_headers))["version"]
    plan2 = validate_success(
        api.create_plan(
            client["id"],
            create_plan_payload(coach["id"], intake["id"], fresh_version,
                                cadence="BIWEEKLY"),
            coach_h,
        ),
        expected_status=201,
    )
    assert plan2["revision_number"] == 2
    plan1_after = validate_success(api.get_plan(plan1["id"], admin_headers))
    assert plan1_after["status"] == "SUPERSEDED"
