"""Temporary services billing, patrol visit windows, the patrol-miss breach
cascade, the generator pool, and the SECURED -> BREACH_HOLD -> ON_SITE ->
SECURED job cycle."""
from test_helpers import (
    assert_same_instant,
    create_service,
    deactivate_service,
    extend_secured_job,
    get_job,
    make_subcontractor_headers,
    schedule_visit,
    set_clock,
    setup_network,
    setup_secured_job,
    submit_assessment,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_secured_with_patrol(patrol_window=("2026-05-02T08:00:00Z", "2026-05-02T20:00:00Z"),
                               service_window=("2026-05-02T00:00:00Z", "2026-05-04T00:00:00Z"),
                               with_lighting=False):
    """SECURED P3 job + PATROL service + one scheduled visit; optionally a
    LIGHTING sibling service. Clock left at the default unless changed by caller."""
    ctx = setup_secured_job(priority="P3", incident_type="STORM")
    patrol = create_service(ctx["job"]["id"], "PATROL", service_window[0], service_window[1])
    ctx["patrol_service"] = patrol
    if with_lighting:
        ctx["lighting_service"] = create_service(
            ctx["job"]["id"], "LIGHTING", service_window[0], service_window[1])
    ctx["visit"] = schedule_visit(patrol["id"], patrol_window[0], patrol_window[1])
    return ctx


def test_service_billable_days_ceiling(api, dispatcher_headers):
    """PRD §3.6: "Billing is computed at that moment: the billable span runs from
    `starts_at` to whichever comes earlier of `ends_at` and `deactivated_at`; the
    span is converted to `billable_days` by rounding any partial day up to a
    whole day, with a hard floor of one day — exactly 24 hours bills one day, 25
    hours bills two."
    PRD §3.6: "Power and lighting services snapshot their `daily_rate_cents` from
    the market's `temp_power_daily_rate_cents` or `temp_lighting_daily_rate_cents`
    at creation"

    Design: Corner/calculations/service_billable_days_ceiling
    """
    ctx = setup_secured_job(priority="P3", incident_type="FIRE")
    svc = create_service(ctx["job"]["id"], "POWER",
                         "2026-05-02T00:00:00Z", "2026-05-06T00:00:00Z",
                         generator_units=1)
    assert svc["daily_rate_cents"] == 18000, "rate snapshot from the market at creation"

    set_clock("2026-05-03T01:00:00Z")  # 25 hours after starts_at
    done = deactivate_service(svc["id"])
    assert done["status"] == "COMPLETED"
    assert done["billable_days"] == 2, "25 hours rounds up to 2 days"
    assert done["service_total_cents"] == 36000


def test_paused_service_deactivate_allowed(api, dispatcher_headers):
    """PRD §3.6: "A `Dispatcher` deactivates a service from either `ACTIVE` or
    `PAUSED`, moving it to the terminal `COMPLETED` state and stamping
    `deactivated_at`."
    PRD §3.6: "patrol services carry a `daily_rate_cents` of 0 because patrols
    bill per visit instead."

    Design: Corner/state_machines/paused_service_deactivate_allowed
    """
    ctx = _setup_secured_with_patrol()
    set_clock("2026-05-02T21:00:00Z")  # past the visit window
    res = api.check_in_patrol_visit(ctx["visit"]["id"], {"outcome": "MISSED"},
                                    make_subcontractor_headers(ctx["assignee"]["id"]))
    validate_success(res, 200)
    paused = validate_success(
        api.get_temporary_service(ctx["patrol_service"]["id"], dispatcher_headers), 200)
    assert paused["status"] == "PAUSED"

    done = deactivate_service(ctx["patrol_service"]["id"])
    assert done["status"] == "COMPLETED", "PAUSED -> COMPLETED must be allowed"
    assert done["service_total_cents"] == 0, "PATROL bills per visit, never per day"


def test_patrol_visit_scheduling_validation_errors(api, dispatcher_headers):
    """PRD §3.6: "are scheduled against a patrol service only — the new visit
    records the parent service's `temporary_service_id`, and scheduling one
    against a power or lighting service is rejected with `ERR_SERVICE_NOT_PATROL`."
    PRD §3.6: "the end must be strictly after the start and strictly after the
    current clock at scheduling time, or the request is rejected with
    `ERR_VISIT_WINDOW_PAST`."

    Design: Corner/endpoints/patrol_visit_scheduling_validation_errors
    """
    ctx = setup_secured_job(priority="P3", incident_type="STORM")
    power = create_service(ctx["job"]["id"], "POWER",
                           "2026-05-02T00:00:00Z", "2026-05-04T00:00:00Z",
                           generator_units=1)
    patrol = create_service(ctx["job"]["id"], "PATROL",
                            "2026-05-02T00:00:00Z", "2026-05-04T00:00:00Z")

    res = api.create_patrol_visit(
        power["id"],
        {"window_start": "2026-05-02T08:00:00Z", "window_end": "2026-05-02T20:00:00Z"},
        dispatcher_headers)
    validate_error(res, "ERR_SERVICE_NOT_PATROL")

    # Clock is at the default 2026-05-01T00:00:00Z; this window already ended.
    res = api.create_patrol_visit(
        patrol["id"],
        {"window_start": "2026-04-29T08:00:00Z", "window_end": "2026-04-30T20:00:00Z"},
        dispatcher_headers)
    validate_error(res, "ERR_VISIT_WINDOW_PAST")


def test_patrol_checkin_window_errors(api, dispatcher_headers):
    """PRD §3.6: "An `outcome` of `CHECKED_IN` is accepted only while the clock
    is inside the window — at or after `window_start` and strictly before
    `window_end` — and stamps `checked_in_at`; outside that window the call fails
    with `ERR_VISIT_NOT_DUE`. An `outcome` of `MISSED` is accepted only once the
    clock has reached or passed `window_end`, failing with `ERR_VISIT_NOT_DUE`
    before that."

    Design: Corner/endpoints/patrol_checkin_window_errors
    """
    ctx = _setup_secured_with_patrol()
    assignee = ctx["assignee"]
    # Clock held at the default 2026-05-01T00:00:00Z, before the window.
    res = api.check_in_patrol_visit(ctx["visit"]["id"], {"outcome": "CHECKED_IN"},
                                    make_subcontractor_headers(assignee["id"]))
    validate_error(res, "ERR_VISIT_NOT_DUE")
    res = api.check_in_patrol_visit(ctx["visit"]["id"], {"outcome": "MISSED"},
                                    make_subcontractor_headers(assignee["id"]))
    validate_error(res, "ERR_VISIT_NOT_DUE")

    visits, _ = validate_paginated(
        api.list_patrol_visits(ctx["patrol_service"]["id"], dispatcher_headers))
    assert [v["status"] for v in visits] == ["SCHEDULED"], (
        "rejected check-ins leave the visit untouched")


def test_patrol_window_adjacency_allowed_straddle_rejected(api, dispatcher_headers):
    """PRD §3.6: "Windows on the same service may not overlap: because the
    intervals are half-open, a new visit whose window merely touches an existing
    one — starting exactly when the other ends — is allowed, while any true
    overlap is rejected with `ERR_OVERLAP_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/patrol_window_adjacency_semantics
    """
    ctx = setup_secured_job(priority="P3", incident_type="STORM")
    svc = create_service(ctx["job"]["id"], "PATROL",
                         "2026-05-02T00:00:00Z", "2026-05-06T00:00:00Z")
    visit_a = schedule_visit(svc["id"], "2026-05-02T08:00:00Z", "2026-05-02T10:00:00Z")
    assert visit_a["status"] == "SCHEDULED"

    # Adjacent: [10:00, 12:00) touches A's end — allowed under half-open semantics.
    visit_b = schedule_visit(svc["id"], "2026-05-02T10:00:00Z", "2026-05-02T12:00:00Z")
    assert visit_b["status"] == "SCHEDULED"

    # Straddling 10:00 truly overlaps both — rejected.
    res = api.create_patrol_visit(
        svc["id"],
        {"window_start": "2026-05-02T09:30:00Z", "window_end": "2026-05-02T11:00:00Z"},
        dispatcher_headers)
    validate_error(res, "ERR_OVERLAP_CONFLICT")

    visits, meta = validate_paginated(api.list_patrol_visits(svc["id"], dispatcher_headers))
    assert meta["total_count"] == 2, "the rejected straddle must not persist"


def test_patrol_window_left_adjacency_and_containment(api, dispatcher_headers):
    """PRD §3.6: "Windows on the same service may not overlap: because the
    intervals are half-open, a new visit whose window merely touches an existing
    one — starting exactly when the other ends — is allowed, while any true
    overlap is rejected with `ERR_OVERLAP_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/patrol_window_adjacency_semantics
    """
    ctx = setup_secured_job(priority="P3", incident_type="STORM")
    svc = create_service(ctx["job"]["id"], "PATROL",
                         "2026-05-02T00:00:00Z", "2026-05-06T00:00:00Z")
    schedule_visit(svc["id"], "2026-05-02T08:00:00Z", "2026-05-02T10:00:00Z")

    # Left-adjacent: ends exactly when the existing visit starts — allowed.
    left = schedule_visit(svc["id"], "2026-05-02T06:00:00Z", "2026-05-02T08:00:00Z")
    assert left["status"] == "SCHEDULED"

    # Fully contained inside the existing window — a true overlap.
    res = api.create_patrol_visit(
        svc["id"],
        {"window_start": "2026-05-02T08:30:00Z", "window_end": "2026-05-02T09:30:00Z"},
        dispatcher_headers)
    validate_error(res, "ERR_OVERLAP_CONFLICT")

    _, meta = validate_paginated(api.list_patrol_visits(svc["id"], dispatcher_headers))
    assert meta["total_count"] == 2


def test_generator_pool_aggregate_capacity(api, dispatcher_headers):
    """PRD §3.6: "A `POWER` service draws `generator_units` — defaulting to 1 when
    omitted — from the market's generator pool: the sum of `generator_units`
    across all of the market's `POWER` services in `ACTIVE` or `PAUSED` status
    may never exceed the market's `generator_pool_units`, or creation is rejected
    with `ERR_GENERATOR_POOL_EXHAUSTED`."

    Design: Difficulty/resource_temporal_overlap/generator_pool_aggregate_capacity
    """
    net = setup_network(max_concurrent_jobs=5)
    ctx1 = extend_secured_job(net, priority="P3", incident_type="FIRE")
    ctx2 = extend_secured_job(net, priority="P3", incident_type="STORM")
    ctx3 = extend_secured_job(net, priority="P3", incident_type="VANDALISM")

    # Market default pool is 2 units; these overlap in time and share the market.
    p1 = create_service(ctx1["job"]["id"], "POWER",
                        "2026-05-02T00:00:00Z", "2026-05-04T00:00:00Z", generator_units=1)
    p2 = create_service(ctx2["job"]["id"], "POWER",
                        "2026-05-03T00:00:00Z", "2026-05-05T00:00:00Z", generator_units=1)
    assert p1["status"] == "ACTIVE" and p2["status"] == "ACTIVE", (
        "two overlapping units fit the pool of 2")

    res = api.create_temporary_service(
        ctx3["job"]["id"],
        {"kind": "POWER", "starts_at": "2026-05-03T12:00:00Z",
         "ends_at": "2026-05-04T12:00:00Z", "generator_units": 1},
        dispatcher_headers)
    validate_error(res, "ERR_GENERATOR_POOL_EXHAUSTED")

    _, meta = validate_paginated(
        api.list_temporary_services(ctx3["job"]["id"], dispatcher_headers))
    assert meta["total_count"] == 0, "the rejected service must not persist"


def test_generator_pool_freed_on_deactivation(api, dispatcher_headers):
    """PRD §3.6: "the sum of `generator_units` across all of the market's `POWER`
    services in `ACTIVE` or `PAUSED` status may never exceed the market's
    `generator_pool_units`, or creation is rejected with
    `ERR_GENERATOR_POOL_EXHAUSTED`."
    PRD §3.6: "A `Dispatcher` deactivates a service from either `ACTIVE` or
    `PAUSED`, moving it to the terminal `COMPLETED` state"

    Design: Difficulty/resource_temporal_overlap/generator_pool_aggregate_capacity
    """
    net = setup_network(max_concurrent_jobs=5)
    ctx1 = extend_secured_job(net, priority="P3", incident_type="FIRE")
    ctx2 = extend_secured_job(net, priority="P3", incident_type="STORM")
    ctx3 = extend_secured_job(net, priority="P3", incident_type="VANDALISM")

    p1 = create_service(ctx1["job"]["id"], "POWER",
                        "2026-05-02T00:00:00Z", "2026-05-04T00:00:00Z", generator_units=1)
    create_service(ctx2["job"]["id"], "POWER",
                   "2026-05-03T00:00:00Z", "2026-05-05T00:00:00Z", generator_units=1)

    # Completing p1 frees its unit: the third job's overlapping POWER now fits.
    deactivate_service(p1["id"])
    p3 = create_service(ctx3["job"]["id"], "POWER",
                        "2026-05-03T12:00:00Z", "2026-05-04T12:00:00Z", generator_units=1)
    assert p3["status"] == "ACTIVE", "a COMPLETED service releases its pool units"

    # Pool is full again (p2 + p3): any further overlapping POWER is rejected.
    res = api.create_temporary_service(
        ctx1["job"]["id"],
        {"kind": "POWER", "starts_at": "2026-05-03T12:00:00Z",
         "ends_at": "2026-05-04T12:00:00Z", "generator_units": 1},
        dispatcher_headers)
    validate_error(res, "ERR_GENERATOR_POOL_EXHAUSTED")


def test_patrol_missed_three_hop_cascade(api, dispatcher_headers):
    """PRD §3.6: "A missed visit starts the three-hop breach cascade: first the
    parent service moves `ACTIVE` → `PAUSED`; that pause drives the job `SECURED`
    → `BREACH_HOLD` and resets the job's `safety_cleared` to false, meaning a
    fresh safety assessment is required before the property can be re-secured;
    then every other service of the job still `ACTIVE` is paused as well."

    Design: Difficulty/transitive_cascade/patrol_missed_three_hop_cascade
    """
    ctx = _setup_secured_with_patrol(with_lighting=True)
    set_clock("2026-05-02T21:00:00Z")  # past the visit's window_end
    res = api.check_in_patrol_visit(ctx["visit"]["id"], {"outcome": "MISSED"},
                                    make_subcontractor_headers(ctx["assignee"]["id"]))
    missed = validate_success(res, 200)
    assert missed["status"] == "MISSED"

    patrol_after = validate_success(
        api.get_temporary_service(ctx["patrol_service"]["id"], dispatcher_headers), 200)
    assert patrol_after["status"] == "PAUSED", "hop 1: own service pauses"

    job_after = get_job(ctx["job"]["id"])
    assert job_after["work_status"] == "BREACH_HOLD", "hop 2: job drops to BREACH_HOLD"
    assert job_after["safety_cleared"] is False

    lighting_after = validate_success(
        api.get_temporary_service(ctx["lighting_service"]["id"], dispatcher_headers), 200)
    assert lighting_after["status"] == "PAUSED", (
        "hop 3: sibling ACTIVE service paused by the job transition")


def test_patrol_missed_spawns_replacement_visit(api, dispatcher_headers):
    """PRD §3.6: "The platform also immediately spawns a replacement visit in
    `SCHEDULED` status whose window is the missed window shifted 24 hours later —
    both bounds moved by exactly one day — with its fee recomputed at creation."

    Design: Difficulty/transitive_cascade/patrol_missed_three_hop_cascade
    """
    ctx = _setup_secured_with_patrol()
    set_clock("2026-05-02T21:00:00Z")
    res = api.check_in_patrol_visit(ctx["visit"]["id"], {"outcome": "MISSED"},
                                    make_subcontractor_headers(ctx["assignee"]["id"]))
    validate_success(res, 200)

    visits, meta = validate_paginated(
        api.list_patrol_visits(ctx["patrol_service"]["id"], dispatcher_headers))
    assert meta["total_count"] == 2, "a replacement visit must be spawned"
    replacement = visits[1]
    assert replacement["status"] == "SCHEDULED"
    assert_same_instant(replacement["window_start"], "2026-05-03T08:00:00Z"), "+24h shift"
    assert_same_instant(replacement["window_end"], "2026-05-03T20:00:00Z")
    assert replacement["fee_cents"] == ctx["visit"]["fee_cents"], (
        "same fee recomputed at creation")


def test_job_secured_breach_resecure_cycle(api, dispatcher_headers):
    """PRD §3.6: "The cycle closes when the crew re-completes securing: that
    transition resumes every `PAUSED` service of the job back to `ACTIVE`."
    PRD §3.4: "if the job was sitting in `BREACH_HOLD`, that clearance is
    precisely what returns it `BREACH_HOLD` → `ON_SITE`."

    Design: Difficulty/non_linear_state_machine/job_secured_breach_resecure_cycle
    """
    ctx = _setup_secured_with_patrol()
    assignee = ctx["assignee"]
    assessor = ctx["assessor"]

    set_clock("2026-05-02T21:00:00Z")
    res = api.check_in_patrol_visit(ctx["visit"]["id"], {"outcome": "MISSED"},
                                    make_subcontractor_headers(assignee["id"]))
    validate_success(res, 200)
    assert get_job(ctx["job"]["id"])["work_status"] == "BREACH_HOLD"

    # Fresh cleared assessment returns the job to ON_SITE.
    submit_assessment(ctx["job"]["id"], assessor["id"], ["WATER"])
    assert get_job(ctx["job"]["id"])["work_status"] == "ON_SITE"

    # Re-securing completes the full SECURED -> BREACH_HOLD -> ON_SITE -> SECURED loop.
    res = api.complete_securing(ctx["job"]["id"], make_subcontractor_headers(assignee["id"]))
    secured = validate_success(res, 200)
    assert secured["work_status"] == "SECURED"

    svc_after = validate_success(
        api.get_temporary_service(ctx["patrol_service"]["id"], dispatcher_headers), 200)
    assert svc_after["status"] == "ACTIVE", "PAUSED service resumes on re-securing"


def test_breach_resets_safety_cleared_flag(api, dispatcher_headers):
    """PRD §3.6: "that pause drives the job `SECURED` → `BREACH_HOLD` and resets
    the job's `safety_cleared` to false, meaning a fresh safety assessment is
    required before the property can be re-secured"
    PRD §3.5: "the job's `safety_cleared` flag must be true, meaning a cleared
    assessment is on file (`ERR_HAZARD_NOT_MITIGATED`)"

    Design: Difficulty/non_linear_state_machine/job_secured_breach_resecure_cycle
    """
    ctx = _setup_secured_with_patrol()
    assignee = ctx["assignee"]
    assessor = ctx["assessor"]
    assert get_job(ctx["job"]["id"])["safety_cleared"] is True

    set_clock("2026-05-02T21:00:00Z")
    res = api.check_in_patrol_visit(ctx["visit"]["id"], {"outcome": "MISSED"},
                                    make_subcontractor_headers(assignee["id"]))
    validate_success(res, 200)
    job_after = get_job(ctx["job"]["id"])
    assert job_after["safety_cleared"] is False, "breach resets the clearance latch"
    assert job_after["work_status"] == "BREACH_HOLD"

    # The stale pre-breach clearance no longer counts: only a fresh CLEARED
    # assessment re-arms the latch and returns the job to ON_SITE.
    submit_assessment(ctx["job"]["id"], assessor["id"], ["WATER"])
    job = get_job(ctx["job"]["id"])
    assert job["work_status"] == "ON_SITE"
    assert job["safety_cleared"] is True
