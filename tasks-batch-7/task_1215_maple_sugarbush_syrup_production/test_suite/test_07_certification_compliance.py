"""Certification audits and compliance gates: 14-day spacing, audit due date,
organic-audit lease gate, organic-grader gate, segregation of duties
(PRD §3.4, §3.8, §3.10)."""
from test_helpers import (
    ApiErrorId,
    activate_line,
    begin_tapping,
    collect_confirmed_run,
    create_bush,
    create_filling_batch,
    create_flavor_evaluation_payload,
    create_lease_on_bush,
    create_line,
    declare_window,
    draw_from_run,
    finish_batch,
    get_only_syrup_lot,
    go_live,
    hire_active_crew,
    make_sugarmaker_headers,
    open_window,
    record_cert_result,
    schedule_cert_audit,
    setup_live_operation,
    setup_open_season,
    setup_organic_audit_outcome,
    start_boil,
    submit_lease,
    validate_error,
    validate_success,
)


def test_audit_13_days_apart_rejected(api, manager_headers, inspector_headers):
    """PRD §3.10: "the date must be at least 14 days away from any other audit
    on the same bush (otherwise `ERR_AUDIT_TOO_CLOSE`)."

    Design: Difficulty/resource_temporal_overlap/cert_audit_fourteen_day_buffer
    """
    season = setup_open_season(clock="2027-02-01T00:00:00Z")
    bush = create_bush(season["id"])
    schedule_cert_audit(bush["id"], "ORGANIC", "2027-02-10")

    res = api.create_cert_audit(
        bush["id"], {"audit_type": "WOODS", "scheduled_for": "2027-02-23"},
        inspector_headers)
    validate_error(res, ApiErrorId.ERR_AUDIT_TOO_CLOSE)


def test_audit_14_days_apart_accepted(api, manager_headers, inspector_headers):
    """PRD §3.10: "the date must be at least 14 days away from any other audit
    on the same bush (otherwise `ERR_AUDIT_TOO_CLOSE`)." — exactly 14 days
    satisfies "at least 14 days".

    Design: Difficulty/resource_temporal_overlap/cert_audit_fourteen_day_buffer
    """
    season = setup_open_season(clock="2027-02-01T00:00:00Z")
    bush = create_bush(season["id"])
    schedule_cert_audit(bush["id"], "ORGANIC", "2027-02-10")

    second = validate_success(
        api.create_cert_audit(
            bush["id"], {"audit_type": "WOODS", "scheduled_for": "2027-02-24"},
            inspector_headers),
        201)
    assert second["status"] == "SCHEDULED"


def test_audit_record_before_scheduled_rejected(api, manager_headers, inspector_headers):
    """PRD §3.10: "Recording the result — the exclusive province of the
    `CertInspector` — takes the `result` of `PASS` or `FAIL` and requires the
    logical clock date to be on or after `scheduled_for` (otherwise
    `ERR_AUDIT_NOT_DUE`), moving the audit `SCHEDULED → RECORDED`."

    Design: Corner/errors/audit_record_before_scheduled_rejected
    """
    season = setup_open_season()
    bush = create_bush(season["id"])
    audit = schedule_cert_audit(bush["id"], "WOODS", "2027-03-01")

    res = api.record_cert_audit_result(audit["id"], {"result": "PASS"}, inspector_headers)
    validate_error(res, ApiErrorId.ERR_AUDIT_NOT_DUE)

    recorded = record_cert_result(audit["id"], "PASS", clock="2027-03-01T00:00:00Z")
    assert recorded["status"] == "RECORDED"


def test_lease_activation_rejected_with_failing_organic_audit(api, manager_headers):
    """PRD §3.4: "when `certified_organic_required` is true — requires that the
    bush's latest `ORGANIC` audit (ordered by `scheduled_for`, ties broken by
    `created_at`) be in `RECORDED` status with `result` equal to `PASS`
    (otherwise `ERR_ORGANIC_AUDIT_REQUIRED`)"
    PRD §3.10: "it is true exactly when the latest `RECORDED` `ORGANIC` audit
    on the bush (ordered by `scheduled_for`, ties broken by `created_at`) has
    `result` `PASS`, and false when no such recorded audit exists."

    Design: Difficulty/cross_entity_state_dependency/lease_activation_requires_organic_audit
    """
    ctx = setup_organic_audit_outcome("FAIL")
    bush = validate_success(api.get_sugarbush(ctx["bush"]["id"], manager_headers), 200)
    assert bush["organic_certified"] is False

    lease = create_lease_on_bush(ctx["bush"]["id"], per_tap_cents=300,
                                 certified_organic_required=True)
    submit_lease(lease["id"])
    res = api.activate_lease(lease["id"], manager_headers)
    validate_error(res, ApiErrorId.ERR_ORGANIC_AUDIT_REQUIRED)


def test_lease_activation_succeeds_after_later_pass_audit(api, manager_headers):
    """PRD §3.4: "when `certified_organic_required` is true — requires that the
    bush's latest `ORGANIC` audit (ordered by `scheduled_for`, ties broken by
    `created_at`) be in `RECORDED` status with `result` equal to `PASS`
    (otherwise `ERR_ORGANIC_AUDIT_REQUIRED`)"

    Design: Difficulty/cross_entity_state_dependency/lease_activation_requires_organic_audit
    """
    ctx = setup_organic_audit_outcome("FAIL")  # latest ORGANIC audit: FAIL
    lease = create_lease_on_bush(ctx["bush"]["id"], per_tap_cents=300,
                                 certified_organic_required=True)
    submit_lease(lease["id"])
    validate_error(api.activate_lease(lease["id"], manager_headers),
                   ApiErrorId.ERR_ORGANIC_AUDIT_REQUIRED)

    # A later RECORDED PASS supersedes the FAIL as the bush's latest audit.
    audit2 = schedule_cert_audit(ctx["bush"]["id"], "ORGANIC", "2027-03-01")
    record_cert_result(audit2["id"], "PASS", clock="2027-03-01T00:00:00Z")

    bush = validate_success(api.get_sugarbush(ctx["bush"]["id"], manager_headers), 200)
    assert bush["organic_certified"] is True

    activated = validate_success(api.activate_lease(lease["id"], manager_headers), 200)
    assert activated["status"] == "ACTIVE"


def test_grader_not_certified_for_organic_lot(api, manager_headers):
    """PRD §3.8: "Organic handling: when the lot's batch drew from a bush that
    is `organic_certified`, the evaluator must have `cert_organic_handler` true
    (otherwise `ERR_GRADER_NOT_CERTIFIED`)."

    Design: Corner/errors/grader_not_certified_for_organic_lot
    """
    base = setup_organic_audit_outcome("PASS")
    season, bush = base["season"], base["bush"]
    begin_tapping(bush["id"])
    line = activate_line(create_line(bush["id"])["id"])
    bush = go_live(bush["id"])
    bush = validate_success(api.get_sugarbush(bush["id"], manager_headers), 200)
    assert bush["organic_certified"] is True

    window = declare_window(season["id"], season["version"])
    tapper = hire_active_crew(season["id"], "Tammy Tapper", "TAPPER")
    boiler = hire_active_crew(season["id"], "Bob Boiler", "BOILER")
    grader = hire_active_crew(season["id"], "Gail Grader", "GRADER",
                              cert_organic_handler=False)
    window = open_window(window["id"], "2027-03-02T08:00:00Z")
    ctx = {"season": season, "bush": bush, "line": line, "window": window,
           "tapper": tapper, "boiler": boiler, "grader": grader}

    run = collect_confirmed_run(ctx, 10.0, 2.0)
    batch = create_filling_batch(ctx, capacity=50)
    draw_from_run(ctx, batch["id"], run["id"], 10.0)
    batch = start_boil(ctx, batch["id"])
    finish_batch(ctx, batch["id"], 66.5, 0.22)
    lot = get_only_syrup_lot()

    res = api.create_flavor_evaluation(
        lot["id"], create_flavor_evaluation_payload(grader["id"], 80),
        make_sugarmaker_headers(grader["id"]))
    validate_error(res, ApiErrorId.ERR_GRADER_NOT_CERTIFIED)


def test_segregation_of_duties_boiler_grades_own_lot(api, manager_headers):
    """PRD §3.8: "Segregation of duties: the evaluator may not be the same crew
    member as the batch's `boiled_by` — a boiler never grades their own syrup,
    and a violation is `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.6: "the `boiled_by` crew member (who must be `ACTIVE`; any
    `crew_role` may boil)"

    Design: Corner/errors/segregation_of_duties_boiler_grades_own_lot
    """
    ctx = setup_live_operation(with_grader=True)
    grader = ctx["grader"]

    run = collect_confirmed_run(ctx, 10.0, 2.0)
    # The GRADER runs the boil (any crew_role may boil), so boiled_by == grader.
    # PRD §2.1: a SugarMaker operating a batch must act as its boiled_by, so
    # every batch operation below is performed with the grader's identity.
    ctx["boiler"] = grader
    batch = create_filling_batch(ctx, capacity=50, boiler=grader)
    draw_from_run(ctx, batch["id"], run["id"], 10.0)
    batch = start_boil(ctx, batch["id"])
    finish_batch(ctx, batch["id"], 66.5, 0.22)
    lot = get_only_syrup_lot()

    res = api.create_flavor_evaluation(
        lot["id"], create_flavor_evaluation_payload(grader["id"], 80),
        make_sugarmaker_headers(grader["id"]))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
