"""Ticket intake and SLA deadline computation (PRD §3.2, §3.4, §3.6, §2.8):
creation defaults, clock-mode variants, surge multiplier, intake guards, and
breach evaluation boundaries."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    make_employee_headers,
    make_helpdesk_agent_headers,
    assert_ticket,
    assert_instant_equals,
    make_team,
    make_agent,
    make_category,
    make_sla_policy,
    make_employee,
    make_window,
    create_ticket_for,
    create_ticket_payload,
    create_sla_policy_payload,
    set_clock_to,
    triage_ticket,
    respond_ticket,
    get_ticket,
    CLOCK_STARTUP_DEFAULT,
)

ADMIN = TEST_USERS["admin_headers"]


def test_ticket_creation_defaults(api):
    """PRD §3.4: "When self-service fails, the employee opens a ticket with the
    `employee_id` of the requester — which must equal the caller's `X-User-ID` — the
    target `category_id`, a one-line `subject`, a full `description`, and an optional
    `priority` that defaults to `P3`."
    PRD §3.4: "On acceptance the server fixes the ticket's scaffolding: `sensitive`
    is copied from the category's `is_sensitive` and is immutable thereafter; `tier`
    starts at `T1`; `workflow_status` opens at `NEW`; `sla_status` opens at
    `ON_TRACK`; `escalation_count` and `reopen_count` start at zero;
    `assigned_agent_id`, `source_article_id`, `resolution_article_id`,
    `resolution_summary`, `first_responded_at`, `resolved_at`, and `closed_at` all
    start null."
    PRD §3.4: "Under `WALL_CLOCK`, `first_response_due_at` and `resolution_due_at`
    are simply the creation instant plus the effective minutes."

    Design: Corner/entities/ticket_creation_defaults
    """
    team = make_team("Def Team")
    category = make_category(team["id"], code="DEF", name="Default Cat")
    make_sla_policy(category["id"], first_response_minutes=60, resolution_minutes=240)
    employee = make_employee(employee_number="E005", full_name="Tim Ticket", email="tim@x.com")

    data = validate_success(
        api.create_ticket(
            create_ticket_payload(employee["id"], category["id"], subject="q", description="d"),
            make_employee_headers(employee["id"]),
        ),
        expected_status=201,
    )
    assert_ticket(data)
    assert data["priority"] == "P3"
    assert data["workflow_status"] == "NEW"
    assert data["sla_status"] == "ON_TRACK"
    assert data["tier"] == "T1"
    assert data["sensitive"] is False
    assert data["escalation_count"] == 0
    assert data["reopen_count"] == 0
    assert data["source_article_id"] is None
    assert data["assigned_agent_id"] is None
    assert_instant_equals(data["first_response_due_at"], "2026-08-01T01:00:00Z")
    assert_instant_equals(data["resolution_due_at"], "2026-08-01T04:00:00Z")


def _wall_and_biz_categories(api):
    team = make_team("Tier2 Support")
    c_wall = make_category(team["id"], code="BEN-W", name="Benefits Wall")
    c_biz = make_category(team["id"], code="BEN-B", name="Benefits Biz")
    make_sla_policy(c_wall["id"], first_response_minutes=60, resolution_minutes=240,
                    clock_mode="WALL_CLOCK")
    make_sla_policy(c_biz["id"], first_response_minutes=60, resolution_minutes=240,
                    clock_mode="BUSINESS_HOURS")
    employee = make_employee(employee_number="E100", full_name="Wanda Wall", email="wanda@x.com")
    return c_wall, c_biz, employee


def test_sla_deadline_wall_clock_counts_every_minute(api):
    """PRD §2.8: "Under `WALL_CLOCK` every elapsed minute counts, nights and
    weekends included."
    PRD §3.4: "Under `WALL_CLOCK`, `first_response_due_at` and `resolution_due_at`
    are simply the creation instant plus the effective minutes."
    PRD §2.5: "Nothing in this API consults the wall clock. All deadlines, expiries,
    and scheduled transitions evaluate against a server-side logical clock whose
    startup default — before any explicit set — is exactly 2026-08-01T00:00:00Z."

    Design: Difficulty/dual_variant_calc/sla_deadline_wall_vs_business_clock
    """
    c_wall, _c_biz, employee = _wall_and_biz_categories(api)

    t_wall = create_ticket_for(employee["id"], c_wall["id"], subject="wall ticket")
    assert_instant_equals(t_wall["created_at"], CLOCK_STARTUP_DEFAULT)
    assert_instant_equals(t_wall["first_response_due_at"], "2026-08-01T01:00:00Z")
    assert_instant_equals(t_wall["resolution_due_at"], "2026-08-01T04:00:00Z")


def test_sla_deadline_business_hours_skips_weekend(api):
    """PRD §2.8: "Under `BUSINESS_HOURS` only minutes inside 09:00–17:00 UTC on
    Monday through Friday count; Saturday and Sunday contribute zero, and deadline
    computation walks forward from the anchor instant consuming business minutes
    until the budgeted count is exhausted."
    PRD §3.4: "Under `BUSINESS_HOURS`, the computation walks forward from creation
    consuming only minutes inside 09:00–17:00 UTC Monday through Friday — weekends
    contribute zero — so an identical creation instant yields a strictly later
    deadline whenever the span touches non-business time."

    Design: Difficulty/dual_variant_calc/sla_deadline_wall_vs_business_clock
    """
    c_wall, c_biz, employee = _wall_and_biz_categories(api)

    t_wall = create_ticket_for(employee["id"], c_wall["id"], subject="wall ticket")
    t_biz = create_ticket_for(employee["id"], c_biz["id"], subject="biz ticket")

    # 2026-08-01 is a Saturday: zero business minutes until Monday 09:00 UTC.
    assert_instant_equals(t_biz["first_response_due_at"], "2026-08-03T10:00:00Z")
    assert_instant_equals(t_biz["resolution_due_at"], "2026-08-03T13:00:00Z")
    assert t_biz["resolution_due_at"] != t_wall["resolution_due_at"], (
        "identical instant and base minutes must diverge purely from the clock mode"
    )


def test_surge_multiplier_extends_deadlines(api):
    """PRD §3.4: "The policy row for the ticket's category and priority supplies the
    base minutes; then a surge multiplier is determined — normally 1.0, but if the
    category's specialist team has an `ACTIVE` staffing window whose inclusive bounds
    cover the creation instant, that window's `sla_multiplier` applies instead (the
    window overlap rule of §3.9 guarantees at most one such active window per team).
    Each budget is multiplied by the surge and rounded up to a whole number of
    minutes."
    PRD §3.9: "It is born `PLANNED` — or immediately `ACTIVE` when the creation
    instant already falls inside the window — moves `PLANNED` to `ACTIVE` when the
    clock reaches `window_start`, and `ACTIVE` to `COMPLETED` once the clock passes
    `window_end`."

    Design: Corner/calculations/surge_multiplier_extends_deadline
    """
    team = make_team("Surge Team")
    window = make_window(
        team["id"],
        window_start="2026-07-31T00:00:00Z",
        window_end="2026-08-31T00:00:00Z",
        required_t1_hours=0,
        required_t2_hours=0,
        sla_multiplier=1.5,
        name="OE Surge",
    )
    assert window["status"] == "ACTIVE", (
        "window whose bounds cover the creation instant is born ACTIVE"
    )
    category = make_category(team["id"], code="SRG", name="Surge Cat")
    make_sla_policy(category["id"], first_response_minutes=60, resolution_minutes=240)
    employee = make_employee(employee_number="E207", full_name="Surge Sam", email="surge@x.com")

    ticket = create_ticket_for(employee["id"], category["id"], subject="q")
    # ceil(60 * 1.5) = 90 minutes; ceil(240 * 1.5) = 360 minutes.
    assert_instant_equals(ticket["first_response_due_at"], "2026-08-01T01:30:00Z")
    assert_instant_equals(ticket["resolution_due_at"], "2026-08-01T06:00:00Z")


def test_category_inactive_intake_rejected(api):
    """PRD §3.2: "Retiring a category stops new intake — submitting a ticket into an
    inactive category fails with `ERR_CATEGORY_INACTIVE` — while tickets already in
    flight are unaffected."

    Design: Corner/validations/category_inactive_intake_rejected
    """
    team = make_team("INACT Team")
    category = make_category(team["id"], code="INA", name="Inactive", active=False)
    make_sla_policy(category["id"], first_response_minutes=60, resolution_minutes=240)
    employee = make_employee(employee_number="E312", full_name="Ina Ctive", email="ina@x.com")

    resp = api.create_ticket(
        create_ticket_payload(employee["id"], category["id"], subject="s", description="d"),
        make_employee_headers(employee["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CATEGORY_INACTIVE.value)


def test_sla_policy_missing_intake_rejected(api):
    """PRD §3.2: "Intake depends on this catalog: if no row exists for the ticket's
    category and priority, the ticket is not created and the request fails with
    `ERR_SLA_POLICY_NOT_FOUND`."

    Design: Corner/validations/sla_policy_missing_intake_rejected
    """
    team = make_team("NOP Team")
    category = make_category(team["id"], code="NOP", name="No Policy")
    employee = make_employee(employee_number="E313", full_name="No Polly", email="nop@x.com")

    resp = api.create_ticket(
        create_ticket_payload(employee["id"], category["id"], subject="s", description="d"),
        make_employee_headers(employee["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SLA_POLICY_NOT_FOUND.value)

    _data, meta = validate_paginated(
        api.list_tickets(ADMIN, params={"employee_id": employee["id"]})
    )
    assert meta["total_count"] == 0, "no ticket may be persisted when the policy row is missing"


def test_duplicate_sla_policy_rejected(api):
    """PRD §3.2: "Only one row may exist for a given (`category_id`, `priority`)
    pair; a second insert is rejected with `ERR_SLA_POLICY_DUPLICATE`."

    Design: Corner/validations/duplicate_sla_policy_rejected
    """
    team = make_team("DP Team")
    category = make_category(team["id"], code="DUP", name="Dup")
    make_sla_policy(category["id"], priority="P3", first_response_minutes=60,
                    resolution_minutes=240)

    resp = api.create_sla_policy(
        create_sla_policy_payload(category["id"], priority="P3",
                                  first_response_minutes=30, resolution_minutes=120),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_SLA_POLICY_DUPLICATE.value)


def test_ticket_create_missing_required_field(api):
    """PRD §2.10: "When several checks could reject the same request, they are
    evaluated in the following fixed order, and the earliest failing tier determines
    the response:"
    PRD §2.10: "3. **Request shape.** Required fields present, enum values inside
    their declared sets, types valid, and the sub-fields of a data change request's
    `new_values` complete for its `change_type`. Failures: `ERR_VALIDATION` or
    `ERR_INVALID_ENUM` (400)."
    PRD §2.10: "4. **Existence.** Path identifiers resolve left to right, then body
    foreign keys resolve — `employee_id`, `category_id`, `agent_id`, `article_id`,
    `team_id`, `staffing_window_id`, `ticket_id` as applicable."

    Design: Corner/validations/ticket_create_missing_required_field
    """
    employee = make_employee(employee_number="E301", full_name="Val Ida", email="val@x.com")

    resp = api.create_ticket(
        {"employee_id": employee["id"], "category_id": NON_EXISTENT_UUID, "description": "d"},
        make_employee_headers(employee["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_ticket_create_invalid_enum(api):
    """PRD §2.10: "3. **Request shape.** Required fields present, enum values inside
    their declared sets, types valid, and the sub-fields of a data change request's
    `new_values` complete for its `change_type`. Failures: `ERR_VALIDATION` or
    `ERR_INVALID_ENUM` (400)."
    PRD §3.4: "When self-service fails, the employee opens a ticket with the
    `employee_id` of the requester — which must equal the caller's `X-User-ID` — the
    target `category_id`, a one-line `subject`, a full `description`, and an optional
    `priority` that defaults to `P3`."

    Design: Corner/validations/ticket_create_invalid_enum
    """
    employee = make_employee(employee_number="E302", full_name="Enum Emma", email="emma@x.com")

    payload = create_ticket_payload(employee["id"], NON_EXISTENT_UUID,
                                    subject="s", description="d", priority="P9")
    resp = api.create_ticket(payload, make_employee_headers(employee["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)


def test_sensitive_intake_auto_assigns_cleared_agent(api):
    """PRD §3.4: "A ticket in a sensitive category gets one more piece of automation
    at intake: the system attempts an immediate assignment, selecting among agents
    who are active, hold `SENSITIVE` clearance, and are under capacity —
    `assigned_open_count` strictly below `capacity_max` — ranked by
    `assigned_open_count` ascending with ties broken by the earlier agent
    `created_at`. The winner becomes the `assigned_agent_id` while the ticket remains
    `NEW`, which is why `NEW` tickets contribute to an agent's
    `assigned_open_count`."

    Design: Corner/endpoints/sensitive_intake_auto_assigns_cleared_agent
    """
    team = make_team("AA Team")
    make_agent(team["id"], tier="T1", clearance="STANDARD",
               display_name="Std", email="std2@x.com")
    sen = make_agent(team["id"], tier="T1", clearance="SENSITIVE",
                     display_name="Sen", email="sen2@x.com")
    category = make_category(team["id"], code="SAA", name="Sensitive AA", is_sensitive=True)
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    employee = make_employee(employee_number="E406", full_name="Auto Assign", email="aa@x.com")

    ticket = create_ticket_for(employee["id"], category["id"], subject="sensitive intake")
    assert ticket["sensitive"] is True
    assert ticket["assigned_agent_id"] == sen["id"], (
        "the only eligible SENSITIVE-clearance agent must win the intake selector"
    )
    assert ticket["workflow_status"] == "NEW", "auto-assign does not triage"

    agent = validate_success(api.get_agent(sen["id"], ADMIN))
    assert agent["assigned_open_count"] == 1


def _at_risk_queue(api):
    """Category with a 480/480 WALL_CLOCK P3 policy; one NEW ticket at 00:00."""
    team = make_team("SLA Team")
    category = make_category(team["id"], code="SLA", name="SLA Cat")
    make_sla_policy(category["id"], first_response_minutes=480, resolution_minutes=480)
    employee = make_employee(employee_number="E110", full_name="Ada Risk", email="ada@x.com")
    ticket = create_ticket_for(employee["id"], category["id"], subject="risk")
    assert_instant_equals(ticket["first_response_due_at"], "2026-08-01T08:00:00Z")
    assert_instant_equals(ticket["resolution_due_at"], "2026-08-01T08:00:00Z")
    return ticket


def test_sla_status_on_track_just_below_at_risk_fraction(api):
    """PRD §3.6: "Two boundary rules are exact. A consumed fraction of exactly 0.75
    flips the ticket to `AT_RISK` — the threshold is inclusive — while the current
    time landing exactly on a deadline is not a breach, because breaching requires
    the deadline to be strictly in the past."
    PRD §3.6: "otherwise, if the fraction of the resolution budget already consumed —
    elapsed time since creation divided by the full span from creation to
    `resolution_due_at` — has reached three-quarters, the ticket moves to `AT_RISK`;
    otherwise it remains `ON_TRACK`."

    Design: Difficulty/boundary_precision_check/sla_at_risk_exactly_75_percent_elapsed
    """
    ticket = _at_risk_queue(api)

    # 359 of 480 minutes elapsed: fraction 0.7479..., below the threshold.
    set_clock_to("2026-08-01T05:59:00Z")
    data = get_ticket(ticket["id"])
    assert data["sla_status"] == "ON_TRACK", (
        f"359/480 < 0.75 must stay ON_TRACK, got {data['sla_status']}"
    )
    assert_instant_equals(data["first_response_due_at"], "2026-08-01T08:00:00Z")


def test_sla_status_at_risk_at_exactly_three_quarters(api):
    """PRD §3.6: "Two boundary rules are exact. A consumed fraction of exactly 0.75
    flips the ticket to `AT_RISK` — the threshold is inclusive — while the current
    time landing exactly on a deadline is not a breach, because breaching requires
    the deadline to be strictly in the past."
    PRD §2.5: "Independently of these sweeps, several reads evaluate lazily: every
    ticket read re-evaluates its `sla_status` against the current logical time, a
    staffing window read recomputes its coverage figures, and the satisfaction metric
    recomputes on read."

    Design: Difficulty/boundary_precision_check/sla_at_risk_exactly_75_percent_elapsed
    """
    ticket = _at_risk_queue(api)

    # Exactly 360 of 480 minutes elapsed: fraction == 0.75, the inclusive boundary.
    set_clock_to("2026-08-01T06:00:00Z")
    data = get_ticket(ticket["id"])
    assert data["sla_status"] == "AT_RISK", (
        f"360/480 == 0.75 exactly must flip to AT_RISK, got {data['sla_status']}"
    )
    assert_instant_equals(data["first_response_due_at"], "2026-08-01T08:00:00Z")
    assert_instant_equals(data["resolution_due_at"], "2026-08-01T08:00:00Z")


def test_breached_response_sticky_after_late_respond(api):
    """PRD §3.5: "The first response stamps `first_responded_at` — later responses
    leave it untouched — and a `BREACHED_RESPONSE` status, once latched, is not
    cleared by responding."
    PRD §3.6: "Severity never heals backwards: the clock can move a ticket from
    `ON_TRACK` or `AT_RISK` into `BREACHED_RESPONSE`, and from `ON_TRACK`,
    `AT_RISK`, or `BREACHED_RESPONSE` into `BREACHED_RESOLUTION`, but never in
    reverse."

    Design: Corner/calculations/breached_response_sticky_after_late_respond
    """
    team = make_team("BR Team")
    agent = make_agent(team["id"], tier="T1", email="br@x.com")
    category = make_category(team["id"], code="BR", name="Breach")
    make_sla_policy(category["id"], first_response_minutes=60, resolution_minutes=4800)
    employee = make_employee(employee_number="E208", full_name="Bre Ach", email="bre@x.com")
    ticket = create_ticket_for(employee["id"], category["id"], subject="q")
    triage_ticket(ticket["id"], agent["id"])

    # 01:01 is strictly past the 01:00 first-response deadline with no response yet.
    set_clock_to("2026-08-01T01:01:00Z")
    pre = get_ticket(ticket["id"])
    assert pre["sla_status"] == "BREACHED_RESPONSE", (
        f"expected BREACHED_RESPONSE once the first-response deadline passes, got {pre['sla_status']}"
    )

    post = respond_ticket(ticket["id"], agent["id"], body="working on it")
    assert_instant_equals(post["first_responded_at"], "2026-08-01T01:01:00Z")
    assert post["sla_status"] == "BREACHED_RESPONSE", (
        "responding late must not heal a latched BREACHED_RESPONSE"
    )
