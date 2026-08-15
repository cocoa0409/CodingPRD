"""Monitors, outages and noise events: reclassify and terminal-state limits,
ingestion gating on decommissioned stations, the DNL computed read, the uptime
verification floor, and the classification cascade onto correlated complaints."""
import pytest

from test_helpers import (
    ApiErrorId,
    begin_review,
    begin_screening,
    classify_event,
    correlate_complaint,
    create_complaint,
    create_complainant,
    create_event,
    create_monitor,
    create_operated_flight,
    create_operator,
    record_outage,
    make_complainant_headers,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["noise_office_admin_headers"]
ANALYST = TEST_USERS["noise_analyst_headers"]
LIAISON = TEST_USERS["community_liaison_headers"]


def _monitor_with_screening_event(api, station_suffix="A", **event_overrides):
    monitor = create_monitor(station_code=f"M{station_suffix}")
    event = create_event(monitor["id"], **event_overrides)
    begin_screening(event["id"])
    return monitor, event


def test_event_third_reclassify_rejected(api):
    """PRD 3.3: "Moving an event backward is also possible: reclassification returns
    any classified event to `SCREENING`, clears its `flight_id`, increments
    `reclassify_count` (at most two reclassifications are permitted — a third attempt
    is rejected with `ERR_RECLASSIFY_LIMIT_REACHED`), decrements the previously linked
    flight's `linked_event_count` as compensation when one was attached, and
    recomputes correlated complaints' confidence *without* the corroboration bonus."

    Design: Corner/state_machines/event_third_reclassify_rejected
    """
    _monitor, event = _monitor_with_screening_event(api, "R1")

    for _round in range(2):
        classify_event(event["id"], "COMMUNITY")
        reclassified = validate_success(
            api.reclassify_event(event["id"], {}, ANALYST), 200
        )
        assert reclassified["status"] == "SCREENING"

    classified = classify_event(event["id"], "COMMUNITY")
    assert classified["reclassify_count"] == 2

    third = api.reclassify_event(event["id"], {}, ANALYST)
    validate_error(third, ApiErrorId.ERR_RECLASSIFY_LIMIT_REACHED)


def test_event_classify_after_discard_rejected(api):
    """PRD 3.3: "An event still in `SCREENING` may instead be discarded with a
    `reason`, moving it to `DISCARDED`. Both `VERIFIED` and `DISCARDED` are terminal,
    and any transition attempted from an impermissible state is rejected with
    `ERR_INVALID_EVENT_STATE`."

    Design: Corner/state_machines/event_classify_after_discard_rejected
    """
    _monitor, event = _monitor_with_screening_event(api, "R2")

    discarded = validate_success(
        api.discard_event(event["id"], {"reason": "ambient"}, ANALYST), 200
    )
    assert discarded["status"] == "DISCARDED"

    response = api.classify_event(event["id"], {"classification": "COMMUNITY"}, ANALYST)
    validate_error(response, ApiErrorId.ERR_INVALID_EVENT_STATE)


def test_event_ingest_on_decommissioned_monitor_rejected(api):
    """PRD 3.3: "decommissioning moves a monitor to `DECOMMISSIONED`, is only valid
    from `ONLINE`, and otherwise fails with `ERR_MONITOR_NOT_ONLINE` — the same error
    that rejects event ingestion into a decommissioned station."

    Design: Corner/state_machines/event_ingest_on_decommissioned_monitor_rejected
    """
    monitor = create_monitor(station_code="MD1")
    retired = validate_success(api.decommission_monitor(monitor["id"], {}, ADMIN), 200)
    assert retired["status"] == "DECOMMISSIONED"

    response = api.ingest_event(
        monitor["id"],
        {
            "started_at": "2026-07-20T10:00:00Z",
            "duration_seconds": 40,
            "lmax_db": 72.0,
            "sel_db": 90.0,
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_MONITOR_NOT_ONLINE)


def test_dnl_rollup_inclusion_set_and_night_penalty(api):
    """PRD 3.3: "The inclusion set is the monitor's events whose `started_at` falls
    inside that calendar date and whose status is `CLASSIFIED_AIRCRAFT`,
    `CLASSIFIED_MIXED`, or `VERIFIED`; `CAPTURED`, `SCREENING`,
    `CLASSIFIED_COMMUNITY`, and `DISCARDED` events are excluded."
    PRD 3.3: "A night event — one whose `started_at` hour falls from 22:00 up to
    midnight or from midnight up to but not including 07:00 UTC — contributes its
    `sel_db` plus a 10 dB penalty; day events contribute `sel_db` unadjusted."

    Design: Corner/calculations/dnl_rollup_inclusion_set_and_night_penalty
    """
    monitor = create_monitor(station_code="MDN")
    operator = create_operator(name="Air Dnl")
    flight = create_operated_flight(
        operator["id"], "2026-07-20T10:00:00Z",
        scheduled_at="2026-07-20T09:55:00Z", zone_code="Z1",
    )

    day_event = create_event(
        monitor["id"], started_at="2026-07-20T10:00:30Z", lmax_db=75.0, sel_db=100.0
    )
    community = create_event(
        monitor["id"], started_at="2026-07-20T11:00:00Z", lmax_db=80.0, sel_db=110.0
    )
    screening = create_event(
        monitor["id"], started_at="2026-07-20T12:00:00Z", lmax_db=85.0, sel_db=120.0
    )
    night_event = create_event(
        monitor["id"], started_at="2026-07-20T23:30:00Z", lmax_db=70.0, sel_db=90.0
    )
    for event in (day_event, community, screening, night_event):
        begin_screening(event["id"])
    classify_event(day_event["id"], "AIRCRAFT", flight_id=flight["id"])
    classify_event(community["id"], "COMMUNITY")
    classify_event(night_event["id"], "AIRCRAFT", flight_id=flight["id"])
    # `screening` deliberately left unclassified.

    data = validate_success(
        api.get_monitor_dnl(monitor["id"], ANALYST, params={"date": "2026-07-20"})
    )
    # Included: day SEL 100 and night SEL 90+10=100. DNL = 10*log10(2*10^10/86400).
    assert data["dnl_db"] == pytest.approx(53.6, abs=1e-6)
    assert data["day_event_count"] == 1
    assert data["night_event_count"] == 1


def _uptime_monitor(api, station_code, outage_minutes):
    """Monitor with one outage of `outage_minutes` inside the trailing 30-day
    window of the startup clock, plus one COMMUNITY-classified event outside it."""
    monitor = create_monitor(station_code=station_code)
    end_minute = outage_minutes  # outage starts 2026-07-02T00:00:00Z (window edge)
    hours, minutes = divmod(end_minute, 60)
    days, hours = divmod(hours, 24)
    record_outage(
        monitor["id"],
        start_at="2026-07-02T00:00:00Z",
        end_at=f"2026-07-{2 + days:02d}T{hours:02d}:{minutes:02d}:00Z",
        outage_type="MAINTENANCE",
    )
    event = create_event(monitor["id"], started_at="2026-07-20T10:00:00Z")
    begin_screening(event["id"])
    classified = classify_event(event["id"], "COMMUNITY")
    # 40 + (72.0-65.0)*2 + 20 (duration >= 30) = 74.0.
    assert classified["classification_confidence"] == pytest.approx(74.0, abs=1e-6)
    return monitor, event


def test_uptime_floor_80_0_passes_verification(api):
    """PRD 3.3: "the capturing monitor's `uptime_pct_30d` is at least 80.0 percent,
    boundary inclusive (else `ERR_UPTIME_BELOW_FLOOR`)".
    PRD 3.3: "over the trailing 30-day window — 43,200 minutes, half-open from
    thirty days ago up to now — the system sums each outage's overlap with that
    window, clipped to the window's edges, subtracts the total from 43,200, divides
    by 43,200, and multiplies by 100, rounding half-up to one decimal place."

    Design: Difficulty/boundary_precision_check/uptime_floor_80_0_passes_79_9_rejected
    """
    monitor, event = _uptime_monitor(api, "MU1", 8640)

    reread = validate_success(api.get_monitor(monitor["id"], ANALYST))
    # (43200 - 8640) / 43200 * 100 = 80.0 exactly at the inclusive floor.
    assert reread["uptime_pct_30d"] == pytest.approx(80.0, abs=1e-6)

    verified = validate_success(api.verify_event(event["id"], {}, ANALYST), 200)
    assert verified["status"] == "VERIFIED"


def test_uptime_floor_79_9_rejects_verification(api):
    """PRD 3.3: "from any of the three classified states an analyst may verify the
    event, moving it to `VERIFIED`, but only when its `classification_confidence` is
    at least 70.0 (else `ERR_CONFIDENCE_BELOW_THRESHOLD`) and the capturing monitor's
    `uptime_pct_30d` is at least 80.0 percent, boundary inclusive (else
    `ERR_UPTIME_BELOW_FLOOR`)."

    Design: Difficulty/boundary_precision_check/uptime_floor_80_0_passes_79_9_rejected
    """
    monitor, event = _uptime_monitor(api, "MU2", 8700)

    reread = validate_success(api.get_monitor(monitor["id"], ANALYST))
    # (43200 - 8700) / 43200 * 100 = 79.861... rounds half-up to 79.9 < 80.0.
    assert reread["uptime_pct_30d"] == pytest.approx(79.9, abs=1e-6)

    response = api.verify_event(event["id"], {}, ANALYST)
    validate_error(response, ApiErrorId.ERR_UPTIME_BELOW_FLOOR)


def _setup_corroboration_scenario(api):
    """Complaint (zone Z1) CORRELATED to a flight (zone Z2) and an event E1 that
    is CLASSIFIED_MIXED: STRICT score 100 - 40*(240/300) - 10 = 58.0, no bonus.
    E2 and E3 sit in SCREENING. Returns the scenario context."""
    monitor = create_monitor(station_code="M1", zone_code="Z2")
    operator = create_operator(name="Air Five")
    flight = create_operated_flight(
        operator["id"], "2026-07-20T12:00:00Z",
        scheduled_at="2026-07-20T11:55:00Z", zone_code="Z2",
    )
    complainant = create_complainant(full_name="Ev One", email="ev1@x.com", zone_code="Z1")
    e1 = create_event(monitor["id"], started_at="2026-07-20T12:00:30Z")
    e2 = create_event(monitor["id"], started_at="2026-07-20T12:01:00Z", lmax_db=70.0)
    e3 = create_event(monitor["id"], started_at="2026-07-20T12:01:30Z", lmax_db=71.0)
    for event in (e1, e2, e3):
        begin_screening(event["id"])
    classify_event(e1["id"], "MIXED", flight_id=flight["id"])

    complaint = create_complaint(complainant["id"], "2026-07-20T12:04:00Z",
                                 disturbance_type="LOUD_EVENT")
    version = begin_review(complaint["id"])
    correlated = correlate_complaint(
        complaint["id"], version, flight_id=flight["id"], event_id=e1["id"]
    )
    return {
        "monitor": monitor,
        "operator": operator,
        "flight": flight,
        "complainant": complainant,
        "e1": e1,
        "e2": e2,
        "e3": e3,
        "complaint": complaint,
        "correlated": correlated,
    }


def test_classification_cascade_recomputes_confidence_with_bonus(api):
    """PRD 3.3: "Second, every complaint currently holding this event as its
    correlated evidence and sitting in `CORRELATED` recomputes its
    `correlation_confidence` *with* the event-corroboration bonus of §3.4 applied,
    refreshing `substantiation_eligible` accordingly."
    PRD 3.4: "adds a 15-point bonus when a linked event is `CLASSIFIED_AIRCRAFT`
    or `VERIFIED`".

    Design: Difficulty/transitive_cascade/event_classification_cascade_corroboration_and_auto_notification
    """
    ctx = _setup_corroboration_scenario(api)
    # MIXED supplies no corroboration bonus: 100 - 32 - 10 = 58.0.
    assert ctx["correlated"]["correlation_confidence"] == pytest.approx(58.0, abs=1e-6)
    assert ctx["correlated"]["substantiation_eligible"] is False

    validate_success(api.reclassify_event(ctx["e1"]["id"], {}, ANALYST), 200)
    classify_event(ctx["e1"]["id"], "AIRCRAFT", flight_id=ctx["flight"]["id"])

    reread = validate_success(api.get_complaint(ctx["complaint"]["id"], ANALYST))
    # Hop two: +15 corroboration bonus flips 58.0 -> 73.0, now substantiable.
    assert reread["correlation_confidence"] == pytest.approx(73.0, abs=1e-6)
    assert reread["substantiation_eligible"] is True


def test_classification_cascade_third_event_drafts_advisory_notification(api):
    """PRD 3.3: "First, the linked flight's `linked_event_count` increments by one."
    PRD 3.3: "Third, if the flight's event count crosses the threshold of three —
    reaching three from below — the system drafts an advisory operator notification
    to the flight's operator."
    PRD 3.3: "decrements the previously linked flight's `linked_event_count` as
    compensation when one was attached".

    Design: Difficulty/transitive_cascade/event_classification_cascade_corroboration_and_auto_notification
    """
    ctx = _setup_corroboration_scenario(api)
    # MIXED classify already incremented the count to 1.
    validate_success(api.reclassify_event(ctx["e1"]["id"], {}, ANALYST), 200)
    classify_event(ctx["e1"]["id"], "AIRCRAFT", flight_id=ctx["flight"]["id"])
    classify_event(ctx["e2"]["id"], "AIRCRAFT", flight_id=ctx["flight"]["id"])
    classify_event(ctx["e3"]["id"], "AIRCRAFT", flight_id=ctx["flight"]["id"])

    flight = validate_success(api.get_flight(ctx["flight"]["id"], ANALYST))
    # 1 (MIXED) - 1 (reclassify compensation) + 1 + 1 + 1 = 3.
    assert flight["linked_event_count"] == 3

    notifications, meta = validate_paginated(
        api.list_operator_notifications(ctx["operator"]["id"], ANALYST)
    )
    assert meta["total_count"] == 1
    assert notifications[0]["status"] == "DRAFT"
    assert notifications[0]["severity"] == "ADVISORY"
