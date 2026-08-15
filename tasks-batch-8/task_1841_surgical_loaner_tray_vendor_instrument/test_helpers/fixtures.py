"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test) and against the logical clock's default instant, so these
helpers build complete precondition chains out of PRD-declared endpoints
only.

Identity threading: VendorRep calls are entity-backed — every rep action
uses make_vendor_rep_headers(rep["id"]). Coordinator personas coord-1 /
coord-2 / coord-3 exist so segregation-of-duties scenarios can separate the
check-in verifier from the reconciler or waver.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    DECON_MIN_MINUTES,
    DEFAULT_CASE_END,
    DEFAULT_CASE_START,
    DEFAULT_CREDENTIAL_EXPIRES,
)
from .factories import (
    approve_credential_payload,
    check_in_line,
    create_access_pass_payload,
    create_case_payload,
    create_check_in_payload,
    create_or_room_payload,
    create_pickup_payload,
    create_rep_payload,
    create_request_payload,
    create_sterilizer_unit_payload,
    create_tray_payload,
    create_vendor_payload,
    decide_request_payload,
    pickup_line,
    start_cycle_payload,
    verify_check_in_payload,
)
from .test_users import (
    COORD_1,
    COORD_2,
    make_coordinator_headers,
    make_nurse_headers,
    make_scheduler_headers,
    make_tech_headers,
    make_vendor_rep_headers,
)

SCHEDULER = make_scheduler_headers()
TECH = make_tech_headers()
NURSE = make_nurse_headers()


def coordinator(user_id=COORD_1):
    return make_coordinator_headers(user_id)


def rep_headers(rep):
    """Entity-backed VendorRep headers for the given rep entity."""
    return make_vendor_rep_headers(rep["id"])


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, coordinator()))


def create_vendor(**overrides):
    """Create a vendor (born ACTIVE, rollups zero)."""
    return get_success_data(
        api_client.create_vendor(create_vendor_payload(**overrides),
                                 coordinator()), 201)


def create_rep(vendor_id, **overrides):
    """Register a rep under a vendor (born PENDING_VERIFICATION)."""
    return get_success_data(
        api_client.create_rep(vendor_id, create_rep_payload(**overrides),
                              coordinator()), 201)


def credential_rep(rep_id, expires=DEFAULT_CREDENTIAL_EXPIRES,
                   or_access_level="OBSERVER"):
    """Approve / renew / extend a rep credential -> ACTIVE."""
    return get_success_data(
        api_client.approve_credential(
            rep_id,
            approve_credential_payload(credential_expires_at=expires,
                                       or_access_level=or_access_level),
            coordinator()))


def create_credentialed_rep(vendor_id, expires=DEFAULT_CREDENTIAL_EXPIRES,
                            or_access_level="OBSERVER", **rep_overrides):
    rep = create_rep(vendor_id, **rep_overrides)
    return credential_rep(rep["id"], expires, or_access_level)


def create_room(name="OR-1", buffer_minutes=30):
    return get_success_data(
        api_client.create_or_room(
            create_or_room_payload(room_name=name,
                                   turnover_buffer_minutes=buffer_minutes),
            SCHEDULER), 201)


def create_sterilizer(name="ST-1", slot_capacity=2, cycle_minutes=60,
                      cooldown_minutes=30):
    return get_success_data(
        api_client.create_sterilizer_unit(
            create_sterilizer_unit_payload(
                unit_name=name, slot_capacity=slot_capacity,
                cycle_minutes=cycle_minutes, cooldown_minutes=cooldown_minutes),
            TECH), 201)


def create_case(room_id, **overrides):
    """Create a case (born SCHEDULED)."""
    return get_success_data(
        api_client.create_case(create_case_payload(room_id, **overrides),
                               SCHEDULER), 201)


def create_request(case_id, vendor_id, priority_class="URGENT"):
    """Create a loaner request (born DRAFT, readiness NOT_READY)."""
    return get_success_data(
        api_client.create_request(
            create_request_payload(case_id, vendor_id,
                                   priority_class=priority_class),
            SCHEDULER), 201)


def add_tray(request_id, **overrides):
    """Add a tray to a DRAFT request (born EXPECTED)."""
    return get_success_data(
        api_client.add_tray(request_id, create_tray_payload(**overrides),
                            SCHEDULER), 201)


def submit_request(request_id):
    return get_success_data(api_client.submit_request(request_id, SCHEDULER))


def approve_request(request_id):
    return get_success_data(
        api_client.decide_request(request_id, decide_request_payload("APPROVE"),
                                  coordinator()))


# ---------------------------------------------------------------------------
# Tier 2: the standard world (vendor + rep + room + sterilizer + case +
# request + trays), submitted and approved.
# ---------------------------------------------------------------------------

def setup_approved_request(*, priority_class="URGENT",
                           case_start=DEFAULT_CASE_START,
                           case_end=DEFAULT_CASE_END,
                           case_number="C-1001",
                           tray_specs=None,
                           vendor_overrides=None,
                           credential_expires_at=DEFAULT_CREDENTIAL_EXPIRES,
                           with_sterilizer=True):
    """Vendor ACTIVE + rep credentialed + room OR-1 (buffer 30) + sterilizer
    ST-1 (2 slots, 60/30) + case + request with trays, SUBMITTED then
    APPROVED. Returns a world dict of entity payloads."""
    vendor = create_vendor(**(vendor_overrides or {}))
    rep = create_credentialed_rep(vendor["id"],
                                  expires=credential_expires_at)
    room = create_room()
    sterilizer = create_sterilizer() if with_sterilizer else None
    case = create_case(room["id"], case_number=case_number,
                       scheduled_start_at=case_start,
                       scheduled_end_at=case_end)
    request = create_request(case["id"], vendor["id"], priority_class)
    specs = tray_specs or [dict(tray_code="TK-1", declared_instrument_count=50,
                                replacement_value_cents=300000)]
    trays = [add_tray(request["id"], **spec) for spec in specs]
    request = submit_request(request["id"])
    request = approve_request(request["id"])
    return {
        "vendor": vendor,
        "rep": rep,
        "room": room,
        "sterilizer": sterilizer,
        "case": case,
        "request": request,
        "trays": trays,
    }


# ---------------------------------------------------------------------------
# Tier 3: delivery and verification
# ---------------------------------------------------------------------------

def check_in(world, *, at=None, lines=None, extra_payload=None):
    """Rep check-in covering the given lines (default: every tray of the
    request at its full declared count). Sets the clock first when `at` is
    given. Returns the SUBMITTED check-in event."""
    if at is not None:
        set_clock(at)
    if lines is None:
        lines = [check_in_line(t["id"], t["declared_instrument_count"])
                 for t in world["trays"]]
    payload = create_check_in_payload(lines, **(extra_payload or {}))
    return get_success_data(
        api_client.create_check_in(world["request"]["id"], payload,
                                   rep_headers(world["rep"])), 201)


def verify(world, check_in, *, dispositions=None, verifier_id=COORD_1):
    """Coordinator verifies a check-in (default: ACCEPT every line on the
    check-in's count sheet). `check_in` may be the event dict or its id."""
    if isinstance(check_in, dict):
        check_in_id = check_in["id"]
        default_lines = check_in.get("lines", [])
    else:
        check_in_id = check_in
        default_lines = []
    if dispositions is None:
        dispositions = [
            {"tray_id": line["tray_id"], "disposition": "ACCEPT"}
            for line in default_lines
        ]
    return get_success_data(
        api_client.verify_check_in(check_in_id,
                                   verify_check_in_payload(dispositions),
                                   coordinator(verifier_id)))


def deliver_and_verify(world, *, at=None, lines=None, dispositions=None,
                       verifier_id=COORD_1, extra_payload=None):
    """Full delivery: clock -> check-in -> verify. Returns the verified
    check-in event (trays move DELIVERY_PENDING -> per-line state)."""
    ci = check_in(world, at=at, lines=lines, extra_payload=extra_payload)
    return verify(world, ci, dispositions=dispositions,
                  verifier_id=verifier_id)


# ---------------------------------------------------------------------------
# Tier 3: sterilization pipeline
# ---------------------------------------------------------------------------

def open_turn(tray_id):
    """Open a sterilization turn on a CHECKED_IN tray (turn DECONTAMINATING,
    tray PROCESSING)."""
    return get_success_data(api_client.create_turn(tray_id, TECH), 201)


def start_cycle_at(world, turn_id, at):
    """Advance the clock and start the cycle on the world's sterilizer."""
    set_clock(at)
    return get_success_data(
        api_client.start_cycle(turn_id,
                               start_cycle_payload(world["sterilizer"]["id"]),
                               TECH))


def release_turn_at(turn_id, at):
    """Advance the clock (sweeping the finished cycle into COOLDOWN) and
    release the turn (QA pass; tray -> STERILE_READY)."""
    set_clock(at)
    return get_success_data(api_client.release_turn(turn_id, TECH))


def sterilize_tray(world, tray_id, *, decon_at=None, cycle_at, release_at):
    """Turn create -> start-cycle -> clock sweep -> release. Returns the
    RELEASED turn; the tray ends STERILE_READY."""
    if decon_at is not None:
        set_clock(decon_at)
    turn = open_turn(tray_id)
    start_cycle_at(world, turn["id"], cycle_at)
    release_turn_at(turn["id"], release_at)
    return get_success_data(api_client.get_turn(turn["id"], TECH))


def stage(world, tray_id):
    return get_success_data(api_client.stage_tray(tray_id, NURSE))


def sterilize_and_stage(world, tray_id, *, decon_at=None,
                        cycle_at="2026-08-02T08:35:00Z",
                        release_at="2026-08-02T10:10:00Z"):
    """Standard pipeline for the standard ST-1 (60-cycle/30-cooldown) unit:
    cycle starts 08:35, ends 09:35, cooldown over 10:05, release at 10:10.
    The tray ends STAGED and the request READY."""
    sterilize_tray(world, tray_id, decon_at=decon_at, cycle_at=cycle_at,
                  release_at=release_at)
    return stage(world, tray_id)


# ---------------------------------------------------------------------------
# Tier 3: case lifecycle
# ---------------------------------------------------------------------------

def start_case_at(world, at, payload=None):
    set_clock(at)
    return get_success_data(
        api_client.start_case(world["case"]["id"], payload or {}, SCHEDULER))


def complete_case_at(world, at):
    set_clock(at)
    return get_success_data(api_client.complete_case(world["case"]["id"],
                                                     SCHEDULER))


def run_case(world, *, start_at="2026-08-03T09:00:00Z",
             complete_at="2026-08-03T12:30:00Z", start_payload=None):
    """Start then complete the world's case. Returns the completed case."""
    start_case_at(world, start_at, start_payload)
    return complete_case_at(world, complete_at)


# ---------------------------------------------------------------------------
# Tier 3: pickup and reconciliation
# ---------------------------------------------------------------------------

def create_pickup(world, lines, *, at=None):
    """Rep pickup for the given lines. Returns the SUBMITTED pickup."""
    if at is not None:
        set_clock(at)
    return get_success_data(
        api_client.create_pickup(world["request"]["id"],
                                 create_pickup_payload(lines),
                                 rep_headers(world["rep"])), 201)


def reconcile(world, pickup_id, *, reconciler_id=COORD_2):
    return get_success_data(
        api_client.reconcile_pickup(pickup_id, coordinator(reconciler_id)))


def list_claims_of_request(request_id, **extra_params):
    params = {"request_id": request_id}
    params.update(extra_params)
    data, _meta = validate_paginated(
        api_client.list_claims(coordinator(), params=params))
    return data


def list_penalties_of_request(request_id, **extra_params):
    params = {"request_id": request_id}
    params.update(extra_params)
    data, _meta = validate_paginated(
        api_client.list_penalties(coordinator(), params=params))
    return data


def list_escalations_of_request(request_id, **extra_params):
    params = {"request_id": request_id}
    params.update(extra_params)
    data, _meta = validate_paginated(
        api_client.list_escalations(coordinator(), params=params))
    return data


# ---------------------------------------------------------------------------
# Tier 4: full-lifecycle composites
# ---------------------------------------------------------------------------

def _parse_iso(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _fmt_iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def setup_case_completed_world(*, tray_specs=None,
                               deliver_at="2026-08-02T08:00:00Z",
                               cycle_at="2026-08-02T08:35:00Z",
                               release_at="2026-08-02T10:10:00Z",
                               verifier_id=COORD_1,
                               start_at="2026-08-03T09:00:00Z",
                               complete_at="2026-08-03T12:30:00Z",
                               start_payload=None,
                               priority_class="URGENT",
                               case_start=DEFAULT_CASE_START,
                               case_end=DEFAULT_CASE_END):
    """Standard world driven through: approve -> deliver/verify -> sterilize
    -> stage -> case start -> complete. Trays end AWAITING_PICKUP.

    `deliver_at` sets the clock for the check-in and verification. The
    sterilization times (turn opened right after verification, cycle started
    at `cycle_at`, released at `release_at`) must move the logical clock
    forward monotonically; late-delivery scenarios pass later times.

    Multi-tray worlds stagger the given cycle/release pair per tray: tray i's
    pair is shifted by i * (pair span + DECON minimum + 5 minutes), so each
    tray's turn opens at the previous tray's release instant and still
    satisfies the 30-minute decontamination minimum before its cycle starts.
    """
    world = setup_approved_request(priority_class=priority_class,
                                   case_start=case_start, case_end=case_end,
                                   tray_specs=tray_specs)
    deliver_and_verify(world, at=deliver_at, verifier_id=verifier_id)
    cycle_dt = _parse_iso(cycle_at)
    release_dt = _parse_iso(release_at)
    step = (release_dt - cycle_dt) + timedelta(
        minutes=DECON_MIN_MINUTES + 5)
    for idx, tray in enumerate(world["trays"]):
        sterilize_and_stage(world, tray["id"],
                            cycle_at=_fmt_iso(cycle_dt + idx * step),
                            release_at=_fmt_iso(release_dt + idx * step))
    world["case"] = run_case(world, start_at=start_at,
                             complete_at=complete_at,
                             start_payload=start_payload)
    return world


def setup_auto_loss_claim(*, returned=47, declared=50, value=300000):
    """Full lifecycle with a shortage at pickup: tray delivered `declared`,
    returned `returned`, reconciled by coord-2 (verifier was coord-1).
    Returns (world, claim) where claim is the auto-created FILED LOSS claim
    discovered via the claims list filtered by request_id."""
    world = setup_case_completed_world(
        tray_specs=[dict(tray_code="TK-1", declared_instrument_count=declared,
                         replacement_value_cents=value)])
    tray = world["trays"][0]
    pickup = create_pickup(world, [pickup_line(tray["id"], returned, "OK")])
    reconcile(world, pickup["id"], reconciler_id=COORD_2)
    claims = list_claims_of_request(world["request"]["id"])
    assert len(claims) == 1, f"expected exactly one auto claim, got {len(claims)}"
    return world, claims[0]


def setup_assessed_penalty(*, deliver_at="2026-08-02T10:15:00Z",
                           verifier_id=COORD_1, assessor_id=COORD_1):
    """Late-delivery lifecycle through penalty ASSESSED: URGENT request
    (required_delivery_by 2026-08-02T09:00) delivered 75 minutes late
    (10:15), tray sterilized/staged (turn 10:15, cycle 10:50, release 12:20),
    case run on time (no vendor delay), penalty assessed after completion.
    Returns (world, penalty)."""
    world = setup_case_completed_world(deliver_at=deliver_at,
                                       cycle_at="2026-08-02T10:50:00Z",
                                       release_at="2026-08-02T12:20:00Z",
                                       verifier_id=verifier_id)
    penalties = list_penalties_of_request(world["request"]["id"])
    assert len(penalties) == 1, \
        f"expected exactly one accruing penalty, got {len(penalties)}"
    penalty = get_success_data(
        api_client.assess_penalty(penalties[0]["id"],
                                  coordinator(assessor_id)))
    return world, penalty
