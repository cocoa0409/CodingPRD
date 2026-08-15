"""Composite setup helpers.

Every test runs against a freshly restarted server with an empty database, so
each helper builds its preconditions from scratch using only endpoints the PRD
declares. Setup calls use the lenient get_success_data validator so a broken
precondition surfaces as a clear "Setup step failed" instead of a confusing
assertion failure later.
"""
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_EVENT_DATE, PASSING_WEIGHT_KG
from .factories import (
    create_adjudication_payload,
    create_booking_payload,
    create_class_payload,
    create_driver_payload,
    create_entry_payload,
    create_event_payload,
    create_incident_payload,
    create_inspection_payload,
    create_kart_payload,
    create_results_payload,
    create_season_payload,
    create_session_payload,
)
from .test_users import TEST_USERS, make_driver_headers

ADMIN = TEST_USERS["league_admin_headers"]
RACE_DIRECTOR = TEST_USERS["race_director_headers"]
STEWARD = TEST_USERS["steward_headers"]

__all__ = [
    "ADMIN",
    "RACE_DIRECTOR",
    "STEWARD",
    "create_season",
    "add_class",
    "activate_season",
    "setup_active_season",
    "register_driver",
    "activate_driver",
    "register_active_driver",
    "suspend_driver",
    "add_kart",
    "create_event",
    "open_registration",
    "setup_open_event",
    "enter_driver",
    "pay_entry",
    "withdraw_entry",
    "record_inspection",
    "start_event",
    "lock_grid",
    "create_session",
    "transition_session",
    "submit_results",
    "score_session",
    "complete_event",
    "finalize_event",
    "finalize_season",
    "conclude_awards",
    "get_season",
    "get_entry",
    "get_event",
    "get_incident",
    "get_booking",
    "list_session_results",
    "report_incident",
    "open_incident_review",
    "adjudicate_incident",
    "appeal_incident",
    "book_practice",
    "check_in_booking",
    "complete_booking",
    "cancel_booking",
    "setup_grid_locked_event",
    "run_scored_session",
    "setup_scored_event",
    "setup_completed_event",
    "setup_event_with_reported_incident",
    "setup_championship",
    "run_completed_round",
]


# ---------------------------------------------------------------------------
# Primitive single-call steps
# ---------------------------------------------------------------------------


def create_season(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_season(create_season_payload(**overrides), ADMIN), 201
    )


def add_class(season_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_class(season_id, create_class_payload(**overrides), ADMIN), 201
    )


def activate_season(season_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.activate_season(season_id, ADMIN))


def setup_active_season(
    season_overrides: Optional[Dict] = None, class_overrides: Optional[Dict] = None
) -> Dict[str, Any]:
    """Season + one class, season activated (PRD 3.1: activation requires a class)."""
    season = create_season(**(season_overrides or {}))
    race_class = add_class(season["id"], **(class_overrides or {}))
    season = activate_season(season["id"])
    return {"season": season, "race_class": race_class}


def register_driver(**overrides) -> Dict[str, Any]:
    """LeagueAdmin registers a driver on their behalf; the driver starts PENDING."""
    return get_success_data(
        api_client.create_driver(create_driver_payload(**overrides), ADMIN), 201
    )


def activate_driver(driver_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.update_driver(driver_id, {"status": "ACTIVE"}, ADMIN))


def register_active_driver(**overrides) -> Dict[str, Any]:
    driver = register_driver(**overrides)
    return activate_driver(driver["id"])


def suspend_driver(driver_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.update_driver(driver_id, {"status": "SUSPENDED"}, ADMIN)
    )


def add_kart(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_kart(create_kart_payload(**overrides), ADMIN), 201
    )


def create_event(season_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_event(season_id, create_event_payload(**overrides), ADMIN), 201
    )


def open_registration(event_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.open_registration(event_id, ADMIN))


def setup_open_event(
    season_overrides: Optional[Dict] = None,
    class_overrides: Optional[Dict] = None,
    event_overrides: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Active season + class + event in REGISTRATION_OPEN (no drivers yet)."""
    ctx = setup_active_season(season_overrides, class_overrides)
    event = create_event(ctx["season"]["id"], **(event_overrides or {}))
    event = open_registration(event["id"])
    ctx["event"] = event
    return ctx


def enter_driver(
    event_id: str,
    driver_id: str,
    class_id: str,
    entry_type: str = "OWNER_DRIVER",
    kart_id: Optional[str] = None,
    pay: bool = False,
    inspect_weight: Optional[float] = None,
) -> Dict[str, Any]:
    """Create an entry, optionally pay its fee and record a passing weigh-in."""
    payload = create_entry_payload(
        driver_id, class_id, entry_type=entry_type, kart_id=kart_id
    )
    entry = get_success_data(api_client.create_entry(event_id, payload, ADMIN), 201)
    if pay:
        entry = pay_entry(entry["id"])
    if inspect_weight is not None:
        record_inspection(entry["id"], inspect_weight)
        entry = get_success_data(api_client.get_entry(entry["id"], ADMIN))
    return entry


def pay_entry(entry_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.pay_entry(entry_id, ADMIN))


def withdraw_entry(entry_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api_client.withdraw_entry(entry_id, headers or ADMIN))


def record_inspection(
    entry_id: str, weight_kg: float = PASSING_WEIGHT_KG, notes: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_inspection(
            entry_id, create_inspection_payload(weight_kg, notes=notes), RACE_DIRECTOR
        ),
        201,
    )


def start_event(event_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.start_event(event_id, RACE_DIRECTOR))


def lock_grid(event_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.lock_grid(event_id, RACE_DIRECTOR))


def create_session(
    event_id: str,
    expected_event_version: int,
    session_type: str = "MAIN",
    sequence: int = 1,
) -> Dict[str, Any]:
    payload = create_session_payload(session_type, sequence, expected_event_version)
    return get_success_data(api_client.create_session(event_id, payload, RACE_DIRECTOR), 201)


def transition_session(session_id: str, status: str) -> Dict[str, Any]:
    return get_success_data(api_client.update_session(session_id, {"status": status}, RACE_DIRECTOR))


def submit_results(
    session_id: str, expected_session_version: int, rows: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    payload = create_results_payload(rows, expected_session_version)
    return get_success_data(
        api_client.submit_results(session_id, payload, RACE_DIRECTOR), 201
    )


def score_session(session_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.score_session(session_id, RACE_DIRECTOR))


def complete_event(event_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.complete_event(event_id, RACE_DIRECTOR))


def finalize_event(event_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.finalize_event(event_id, RACE_DIRECTOR))


def finalize_season(season_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.finalize_season(season_id, ADMIN))


def conclude_awards(season_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.conclude_awards(season_id, ADMIN))


def get_season(season_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_season(season_id, ADMIN))


def get_entry(entry_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_entry(entry_id, ADMIN))


def get_event(event_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_event(event_id, ADMIN))


def get_incident(incident_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_incident(incident_id, ADMIN))


def get_booking(booking_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_booking(booking_id, ADMIN))


def list_session_results(session_id: str) -> List[Dict[str, Any]]:
    return get_success_data(api_client.list_session_results(session_id, ADMIN))


def report_incident(
    event_id: str,
    entry_id: str,
    session_id: str,
    description: str = "On-track contact",
    reporter_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_incident(
            event_id,
            create_incident_payload(entry_id, session_id, description),
            reporter_headers or RACE_DIRECTOR,
        ),
        201,
    )


def open_incident_review(incident_id: str, steward_headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.open_incident_review(incident_id, steward_headers or STEWARD)
    )


def adjudicate_incident(
    incident_id: str,
    decision: str,
    penalty_kind: Optional[str] = None,
    penalty_seconds: Optional[int] = None,
    steward_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.adjudicate_incident(
            incident_id,
            create_adjudication_payload(decision, penalty_kind, penalty_seconds),
            steward_headers or STEWARD,
        )
    )


def appeal_incident(incident_id: str, driver_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.appeal_incident(incident_id, make_driver_headers(driver_id))
    )


# ---------------------------------------------------------------------------
# Practice bookings (Driver is entity-backed: identity is the Driver id)
# ---------------------------------------------------------------------------


def book_practice(
    driver_id: str,
    kart_id: str,
    start_time: str,
    end_time: str,
    pricing_mode: str = "FLAT",
) -> Dict[str, Any]:
    payload = create_booking_payload(driver_id, kart_id, start_time, end_time, pricing_mode)
    return get_success_data(
        api_client.create_booking(payload, make_driver_headers(driver_id)), 201
    )


def check_in_booking(booking_id: str, driver_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.check_in_booking(booking_id, make_driver_headers(driver_id))
    )


def complete_booking(booking_id: str, driver_id: str) -> Dict[str, Any]:
    """Check in then check out, leaving the booking COMPLETED and billed."""
    check_in_booking(booking_id, driver_id)
    return get_success_data(
        api_client.check_out_booking(booking_id, make_driver_headers(driver_id))
    )


def cancel_booking(booking_id: str, driver_id: Optional[str] = None) -> Dict[str, Any]:
    headers = make_driver_headers(driver_id) if driver_id else ADMIN
    return get_success_data(api_client.cancel_booking(booking_id, headers))


# ---------------------------------------------------------------------------
# Composite race-weekend builders
# ---------------------------------------------------------------------------


def setup_grid_locked_event(
    num_drivers: int = 2,
    season_overrides: Optional[Dict] = None,
    class_overrides: Optional[Dict] = None,
    event_overrides: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Active season + class; event IN_PROGRESS; every entry PAID and
    TECH_PASSED; grid locked. Returns a ctx dict with season, race_class,
    event (fresh copy), drivers and entries lists."""
    ctx = setup_active_season(season_overrides, class_overrides)
    event = create_event(ctx["season"]["id"], **(event_overrides or {}))
    open_registration(event["id"])
    drivers, entries = [], []
    for i in range(num_drivers):
        driver = register_active_driver(
            full_name=f"Driver {chr(ord('A') + i)}",
            date_of_birth=f"199{i}-01-0{i + 1}",
        )
        entry = enter_driver(
            event["id"],
            driver["id"],
            ctx["race_class"]["id"],
            pay=True,
            inspect_weight=PASSING_WEIGHT_KG + i,
        )
        drivers.append(driver)
        entries.append(entry)
    start_event(event["id"])
    event = lock_grid(event["id"])
    entries = [get_entry(e["id"]) for e in entries]
    ctx.update(event=event, drivers=drivers, entries=entries)
    return ctx


def run_scored_session(
    ctx: Dict[str, Any],
    rows: List[Tuple[Dict[str, Any], int, int, int]],
    session_type: str = "MAIN",
    sequence: int = 1,
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """Create a session on ctx's event, walk it OPEN -> CLOSED, submit the
    result batch and score it (CLOSED -> SCORED).

    rows: list of (entry, finish_position, best_lap_ms, total_time_ms).
    Returns (session, results keyed by entry_id).
    """
    event = ctx["event"]
    session = create_session(event["id"], event["version"], session_type, sequence)
    # Session creation advances the event's version (PRD 2.6); refresh ctx.
    ctx["event"] = get_event(event["id"])
    transition_session(session["id"], "OPEN")
    session = transition_session(session["id"], "CLOSED")
    payload_rows = [
        {
            "entry_id": entry["id"],
            "finish_position": finish_position,
            "best_lap_ms": best_lap_ms,
            "total_time_ms": total_time_ms,
        }
        for (entry, finish_position, best_lap_ms, total_time_ms) in rows
    ]
    results = submit_results(session["id"], session["version"], payload_rows)
    session = score_session(session["id"])
    # Points and is_fastest_lap are assigned at scoring time (PRD 3.5), so the
    # submit-time response rows are stale: re-read the scored results.
    results = list_session_results(session["id"])
    return session, {r["entry_id"]: r for r in results}


def setup_scored_event(
    rows_spec: List[Tuple[str, int, int, int]],
    season_overrides: Optional[Dict] = None,
    class_overrides: Optional[Dict] = None,
    event_overrides: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Full chain through a SCORED session on an IN_PROGRESS event.

    rows_spec: list of (driver_label, finish_position, best_lap_ms,
    total_time_ms); one driver is created per label, in order. Returns a ctx
    dict with season, race_class, event, session, results (keyed by entry id),
    drivers_by_label and entries_by_label.
    """
    labels = [spec[0] for spec in rows_spec]
    ctx = setup_grid_locked_event(
        num_drivers=len(labels),
        season_overrides=season_overrides,
        class_overrides=class_overrides,
        event_overrides=event_overrides,
    )
    by_label = {
        label: (driver, entry)
        for label, driver, entry in zip(labels, ctx["drivers"], ctx["entries"])
    }
    rows = [
        (by_label[label][1], finish_position, best_lap_ms, total_time_ms)
        for (label, finish_position, best_lap_ms, total_time_ms) in rows_spec
    ]
    session, results = run_scored_session(ctx, rows)
    ctx.update(
        session=session,
        results=results,
        drivers_by_label={label: pair[0] for label, pair in by_label.items()},
        entries_by_label={label: pair[1] for label, pair in by_label.items()},
    )
    return ctx


def setup_completed_event(
    rows_spec: List[Tuple[str, int, int, int]],
    season_overrides: Optional[Dict] = None,
    class_overrides: Optional[Dict] = None,
    event_overrides: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Full chain through a SCORED session and event COMPLETED (PRD 3.3:
    completion requires every child session SCORED)."""
    ctx = setup_scored_event(
        rows_spec,
        season_overrides=season_overrides,
        class_overrides=class_overrides,
        event_overrides=event_overrides,
    )
    ctx["event"] = complete_event(ctx["event"]["id"])
    return ctx


def setup_event_with_reported_incident(
    rows_spec: List[Tuple[str, int, int, int]],
    description: str = "On-track contact",
    reporter_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Scored session plus one REPORTED incident against the first row's entry."""
    ctx = setup_scored_event(rows_spec)
    first_label = rows_spec[0][0]
    incident = report_incident(
        ctx["event"]["id"],
        ctx["entries_by_label"][first_label]["id"],
        ctx["session"]["id"],
        description,
        reporter_headers,
    )
    ctx["incident"] = incident
    return ctx


# ---------------------------------------------------------------------------
# Multi-round championship builders (standings tests)
# ---------------------------------------------------------------------------


def setup_championship(
    num_drivers: int = 2,
    season_overrides: Optional[Dict] = None,
    class_overrides: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Active season + class + N ACTIVE drivers, ready to run rounds."""
    ctx = setup_active_season(season_overrides, class_overrides)
    drivers = [
        register_active_driver(
            full_name=f"Driver {chr(ord('A') + i)}",
            date_of_birth=f"199{i}-01-0{i + 1}",
        )
        for i in range(num_drivers)
    ]
    ctx["drivers"] = drivers
    return ctx


def run_completed_round(
    ctx: Dict[str, Any],
    round_number: int,
    rows_spec: List[Tuple[int, int, int, int]],
    event_date: str = DEFAULT_EVENT_DATE,
) -> Dict[str, Any]:
    """Run one full round of ctx's championship through COMPLETED.

    rows_spec: list of (driver_index, finish_position, best_lap_ms,
    total_time_ms) referencing ctx["drivers"]. Every listed driver is entered,
    paid, weighed in and grid-locked before the MAIN session is scored.
    """
    event = create_event(
        ctx["season"]["id"], round_number=round_number, event_date=event_date
    )
    open_registration(event["id"])
    entries: Dict[int, Dict[str, Any]] = {}
    for i, driver in enumerate(ctx["drivers"]):
        entries[i] = enter_driver(
            event["id"],
            driver["id"],
            ctx["race_class"]["id"],
            pay=True,
            inspect_weight=PASSING_WEIGHT_KG + i,
        )
    start_event(event["id"])
    event = lock_grid(event["id"])
    sub_ctx = {"event": event}
    rows = [
        (entries[i], finish_position, best_lap_ms, total_time_ms)
        for (i, finish_position, best_lap_ms, total_time_ms) in rows_spec
    ]
    session, results = run_scored_session(sub_ctx, rows)
    event = complete_event(event["id"])
    return {"event": event, "session": session, "entries": entries, "results": results}
