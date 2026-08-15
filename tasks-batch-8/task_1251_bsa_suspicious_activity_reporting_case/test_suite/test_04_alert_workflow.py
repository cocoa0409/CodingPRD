"""Alert workflow: triage, dismiss/reopen conservation, staleness sweep,
terminal lockdown, linking, pagination (PRD §2.5, §3.3)."""
from test_helpers import (
    DEFAULT_FIRING_DEPOSITS,
    ApiErrorId,
    assert_alert,
    create_case,
    create_customer,
    create_staff,
    dismiss_alert_payload,
    link_alert_payload,
    run_sweep,
    set_clock,
    setup_alert_scenario,
    triage_alert,
    validate_error,
    validate_paginated,
    validate_success,
)


def _three_alert_setup(staff):
    return setup_alert_scenario(
        staff,
        deposits_per_account=[list(DEFAULT_FIRING_DEPOSITS) for _ in range(3)],
    )


def test_dismiss_moves_alert_to_dismissed(api):
    """PRD §3.3: "From `UNDER_TRIAGE` the analyst may dismiss the alert;
    dismissal requires a non-empty `dismissal_rationale` in the payload,
    records `dismissed_at`, and lands the alert in `DISMISSED`."

    The scenario's alert population is conserved by the move: three generated
    alerts before and after, one re-bucketed from UNDER_TRIAGE to DISMISSED.

    Design: Difficulty/compensating_invariant/alert_dismiss_reopen_disposition_conservation
    """
    staff = create_staff()
    built = _three_alert_setup(staff)
    al1, al2, al3 = (a["id"] for a in built.alerts)
    triage_alert(staff, al1)

    dismissed = validate_success(api.dismiss_alert(
        al1, dismiss_alert_payload(), staff.analyst), 200)
    assert_alert(dismissed)
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["dismissed_at"] is not None
    assert dismissed["dismissal_rationale"] == "Matches known payroll pattern"

    other1 = validate_success(api.get_alert(al2, staff.analyst), 200)
    other2 = validate_success(api.get_alert(al3, staff.analyst), 200)
    assert other1["status"] == "NEW" and other2["status"] == "NEW", (
        "dismissing one alert must not disturb the others"
    )
    _data, meta = validate_paginated(api.list_alerts(
        staff.analyst, params={"scenario_id": built.scenario["id"]}))
    assert meta["total_count"] == 3, "no alert may be created or destroyed"


def test_reopen_restores_triage_and_clears_dismissal(api):
    """PRD §3.3: "A dismissed alert may be reopened, which returns it to
    `UNDER_TRIAGE` and clears both `dismissed_at` and `dismissal_rationale`."

    The dismiss/reopen pair nets to zero drift: the alert population is still
    exactly the three generated alerts, with the probed one back under triage.

    Design: Difficulty/compensating_invariant/alert_dismiss_reopen_disposition_conservation
    """
    staff = create_staff()
    built = _three_alert_setup(staff)
    al1 = built.alerts[0]["id"]
    triage_alert(staff, al1)
    dismiss = validate_success(api.dismiss_alert(
        al1, dismiss_alert_payload(), staff.analyst), 200)
    assert dismiss["status"] == "DISMISSED"

    reopened = validate_success(api.reopen_alert(al1, staff.analyst), 200)
    assert_alert(reopened)
    assert reopened["status"] == "UNDER_TRIAGE"
    assert reopened["dismissed_at"] is None
    assert reopened["dismissal_rationale"] is None

    _data, meta = validate_paginated(api.list_alerts(
        staff.analyst, params={"scenario_id": built.scenario["id"]}))
    assert meta["total_count"] == 3, "the compensating pair conserves the total"


def test_dismiss_new_alert_rejected(api):
    """PRD §3.3: "From `UNDER_TRIAGE` the analyst may dismiss the alert;
    dismissal requires a non-empty `dismissal_rationale` in the payload,
    records `dismissed_at`, and lands the alert in `DISMISSED`."
    PRD §2.10: "then state-machine legality (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/dismiss_new_alert_rejected
    """
    staff = create_staff()
    built = setup_alert_scenario(staff)
    alert = built.alerts[0]
    assert alert["status"] == "NEW"

    res = api.dismiss_alert(
        alert["id"],
        dismiss_alert_payload(dismissal_rationale="Premature dismissal attempt"),
        staff.analyst)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert res.status_code == 409
    after = validate_success(api.get_alert(alert["id"], staff.analyst), 200)
    assert after["status"] == "NEW"
    assert after["dismissal_rationale"] is None
    assert after["dismissed_at"] is None


def test_auto_closed_alert_is_terminal(api):
    """PRD §2.5: "it auto-closes every `Alert` whose status is `NEW` or
    `UNDER_TRIAGE` and whose age exceeds the generating scenario's
    `stale_alert_days` (the comparison is strictly greater), recording
    `closure_reason` `STALE_EXPIRY`".
    PRD §2.10: "then state-machine legality (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/auto_closed_alert_terminal_lockdown_rejected
    """
    staff = create_staff()
    built = setup_alert_scenario(staff, scenario_overrides={"stale_alert_days": 30})
    alert = built.alerts[0]

    set_clock(staff, "2026-06-01T00:00:00Z")  # age 31 days > stale_alert_days 30
    sweep = run_sweep(staff)
    assert sweep["alerts_auto_closed"] == 1
    closed = validate_success(api.get_alert(alert["id"], staff.analyst), 200)
    assert closed["status"] == "AUTO_CLOSED"
    assert closed["closure_reason"] == "STALE_EXPIRY"

    res = api.triage_alert(alert["id"], staff.analyst)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert res.status_code == 409
    after = validate_success(api.get_alert(alert["id"], staff.analyst), 200)
    assert after["status"] == "AUTO_CLOSED"


def test_stale_alert_sweep_strictly_greater_age(api):
    """PRD §2.5: "it auto-closes every `Alert` whose status is `NEW` or
    `UNDER_TRIAGE` and whose age exceeds the generating scenario's
    `stale_alert_days` (the comparison is strictly greater), recording
    `closure_reason` `STALE_EXPIRY`".

    At an age of exactly 30 days the alert survives; at 30 days plus one
    second it is auto-closed.

    Design: Corner/calculations/stale_alert_sweep_strict_age_boundary
    """
    staff = create_staff()
    built = setup_alert_scenario(staff, scenario_overrides={"stale_alert_days": 30})
    alert = built.alerts[0]  # created at the default clock 2026-05-01T00:00:00Z

    set_clock(staff, "2026-05-31T00:00:00Z")  # exactly 30 days of age
    sweep = run_sweep(staff)
    assert sweep["alerts_auto_closed"] == 0, "strictly-greater comparison"
    mid = validate_success(api.get_alert(alert["id"], staff.analyst), 200)
    assert mid["status"] == "NEW"

    set_clock(staff, "2026-05-31T00:00:01Z")  # 30 days + 1 second
    sweep = run_sweep(staff)
    assert sweep["alerts_auto_closed"] == 1
    end = validate_success(api.get_alert(alert["id"], staff.analyst), 200)
    assert end["status"] == "AUTO_CLOSED"
    assert end["closure_reason"] == "STALE_EXPIRY"


def test_alerts_pagination_and_status_filter(api):
    """PRD §2.3: "List endpoints accept optional `limit` and `offset` query
    parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of
    100; `offset` defaults to 0."
    PRD §2.3: "The pagination fields `limit`, `offset`, `total_count`, and
    `has_more` appear in the response `meta` block on every list endpoint."

    Design: Corner/endpoints/alerts_list_pagination_interaction
    """
    staff = create_staff()
    built = _three_alert_setup(staff)
    customer_id = built.customer["id"]

    page1, meta1 = validate_paginated(api.list_alerts(
        staff.analyst, params={"customer_id": customer_id, "limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_alerts(
        staff.analyst, params={"customer_id": customer_id, "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    filtered, meta3 = validate_paginated(api.list_alerts(
        staff.analyst, params={"customer_id": customer_id, "status": "DISMISSED"}))
    assert filtered == [] and meta3["total_count"] == 0 and meta3["has_more"] is False


def test_link_alert_to_other_customers_case_rejected(api):
    """PRD §3.3: "an analyst may link an `UNDER_TRIAGE` alert to an existing
    case by supplying a `case_id` — provided the case is in `OPEN`, `ASSIGNED`,
    or `INVESTIGATING` (otherwise `ERR_INVALID_STATE`) and the alert's customer
    matches the case's customer (otherwise `ERR_SUBJECT_MISMATCH`)."

    Design: Corner/errors/link_alert_subject_mismatch_rejected
    """
    staff = create_staff()
    built = setup_alert_scenario(staff)  # alert belongs to built.customer
    other_customer = create_customer(staff, full_name="Bob B")
    other_case = create_case(staff, other_customer["id"])
    alert = triage_alert(staff, built.alerts[0]["id"])

    res = api.link_alert_to_case(alert["id"], link_alert_payload(other_case["id"]),
                                 staff.analyst)
    validate_error(res, ApiErrorId.ERR_SUBJECT_MISMATCH)
    assert res.status_code == 422
    after = validate_success(api.get_alert(alert["id"], staff.analyst), 200)
    assert after["status"] == "UNDER_TRIAGE"
    assert after["case_id"] is None


def test_retire_scenario_with_open_alert_rejected(api):
    """PRD §3.2: "either `ACTIVE` or `SUSPENDED` may be retired into the
    terminal `RETIRED` state — but retirement is blocked with
    `ERR_SCENARIO_HAS_OPEN_ALERTS` while any alert of the scenario sits in
    `NEW` or `UNDER_TRIAGE`."

    Design: Corner/errors/retire_scenario_with_open_alert_rejected
    """
    staff = create_staff()
    built = setup_alert_scenario(staff)
    assert built.alerts[0]["status"] == "NEW"

    res = api.retire_scenario(built.scenario["id"], staff.manager)
    validate_error(res, ApiErrorId.ERR_SCENARIO_HAS_OPEN_ALERTS)
    assert res.status_code == 409
    scenario = validate_success(api.get_scenario(built.scenario["id"], staff.admin), 200)
    assert scenario["status"] == "ACTIVE"


def test_qa_reviewer_cannot_triage_alert(api):
    """PRD §4: POST /alerts/{id}/triage is authorized for `BSAAnalyst` only.
    PRD §2.1: "A request whose role is not listed among the endpoint's
    permitted roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)".

    Design: Corner/rbac/qa_reviewer_cannot_triage_alert_returns_403
    """
    staff = create_staff()
    built = setup_alert_scenario(staff)
    alert = built.alerts[0]

    res = api.triage_alert(alert["id"], staff.qa)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert res.status_code == 403
    after = validate_success(api.get_alert(alert["id"], staff.analyst), 200)
    assert after["status"] == "NEW"

