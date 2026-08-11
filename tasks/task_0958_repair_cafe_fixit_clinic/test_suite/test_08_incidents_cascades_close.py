"""Safety incidents, suspension/cancel cascades, event close checkpoint and
the event report snapshot (PRD §3.6, §3.7)."""
import pytest

from test_helpers import (
    validate_success, validate_error, TEST_USERS, ApiErrorId,
    make_safety_officer_headers, make_coordinator_headers,
    set_logical_clock, create_event, create_station, register_fixer,
    add_skill, sign_up_shift, confirm_shift, check_in_shift, publish_event,
    open_station, open_intake, begin_repairs, report_incident,
    setup_intake_open_event, setup_published_event_with_checked_in_fixer,
    progress_item_to_assigned,
    progress_item_to_in_repair, progress_item_to_verified,
    progress_item_to_queued, make_part_stock, reserve_part,
)

COORD = TEST_USERS["coordinator_headers"]


# ─── incident suspension cascade (depth 4) ──────────────────────────────────

def test_incident_suspension_cascade_depth4(api):
    """PRD §3.6: "A `SUSPENSION` resolution — or a direct suspension of a fixer
    by a `SafetyOfficer` (`ACTIVE → SUSPENDED`) — triggers the system's deepest
    cascade, four hops deep. Hop 1: the `FixerProfile` becomes `SUSPENDED`.
    Hop 2: every non-terminal `FixerShift` of that fixer becomes `CANCELLED`.
    Hop 3: each of those shifts that was `CHECKED_IN` decrements its station's
    `checked_in_fixer_count`. Hop 4: any station whose count thereby reaches
    zero auto-transitions from `OPEN` to `PAUSED`, recomputing event posture.
    In the same cascade, every item assigned to that fixer in `ASSIGNED` or
    `IN_REPAIR` returns to `QUEUED` with its assigned fields cleared."

    Design: Difficulty/transitive_cascade/incident_suspension_cascade_depth4
    """
    ctx = setup_intake_open_event(event_name="Cafe Eta")
    item = progress_item_to_in_repair(ctx, description="Drill sparks",
                                      weight_kg_estimated=2.0, severity=4,
                                      estimated_difficulty=2,
                                      diagnosis="brushes")
    incident = report_incident(ctx["event"]["id"], severity="HIGH",
                               description="shock from drill",
                               item_id=item["id"],
                               fixer_id=ctx["fixer"]["id"],
                               headers=make_coordinator_headers("coord-1"))

    resolved = validate_success(api.resolve_incident(
        incident["id"], "SUSPENSION", make_safety_officer_headers("so-1")), 200)
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution_action"] == "SUSPENSION"

    fixer = validate_success(
        api.get_fixer_profile(ctx["fixer"]["id"], COORD), 200)
    assert fixer["status"] == "SUSPENDED", "hop 1: fixer suspended"

    shift = validate_success(api.get_fixer_shift(ctx["shift"]["id"], COORD), 200)
    assert shift["status"] == "CANCELLED", "hop 2: non-terminal shift cancelled"

    station = validate_success(api.get_station(ctx["station"]["id"], COORD), 200)
    assert station["checked_in_fixer_count"] == 0, (
        "hop 3: the checked-in shift's cancellation releases the seat")
    assert station["status"] == "PAUSED", (
        "hop 4: count reaching zero auto-pauses the OPEN station")

    item_after = validate_success(api.get_repair_item(item["id"], COORD), 200)
    assert item_after["status"] == "QUEUED"
    assert item_after["assigned_fixer_id"] is None
    assert item_after["assigned_station_id"] is None


def test_suspension_resolution_requires_subject_fixer(api):
    """PRD §3.6: "Resolving records a `resolution_action` of `NONE`,
    `WARNING`, or `SUSPENSION` (null until resolution); choosing `SUSPENSION`
    requires the incident's `fixer_id` to be set, and its absence fails with
    `ERR_VALIDATION`."

    Design: Difficulty/transitive_cascade/incident_suspension_cascade_depth4
    """
    set_logical_clock()
    event = create_event(name="Cafe Eta-2")
    # Incident with no subject fixer: SUSPENSION has nothing to act on.
    incident = report_incident(event["id"], severity="MEDIUM",
                               description="cluttered walkway",
                               headers=make_coordinator_headers("coord-1"))
    res = api.resolve_incident(incident["id"], "SUSPENSION",
                               make_safety_officer_headers("so-1"))
    validate_error(res, ApiErrorId.ERR_VALIDATION)
    incident_after = validate_success(
        api.get_safety_incident(incident["id"], COORD), 200)
    assert incident_after["status"] == "REPORTED"


# ─── event cancel cascade (depth 3) ─────────────────────────────────────────

def test_event_cancel_cascade_releases_reservations(api):
    """PRD §3.7: "Cancellation (`→ CANCELLED`) is available from every
    non-terminal event state — `DRAFT`, `PUBLISHED`, `INTAKE_OPEN`,
    `REPAIR_ACTIVE`, and `CLOSED` — and runs a full teardown cascade: every
    item of the event becomes `WITHDRAWN`; every `RESERVED` reservation on
    those items becomes `RELEASED` with stock figures recomputed; every station
    becomes `CLOSED`; and every non-terminal shift becomes `CANCELLED`."

    Design: Difficulty/transitive_cascade/event_cancel_cascade_depth3
    """
    ctx = setup_intake_open_event(event_name="Cafe Theta")
    item = progress_item_to_assigned(ctx, description="Kettle",
                                     weight_kg_estimated=1.5)
    stock = make_part_stock(sku="ELT-2KW", name="2kW element",
                            unit_cost_cents=900, quantity_on_hand=5)
    reservation = reserve_part(stock["id"], item["id"], 2, ctx["fixer"]["id"])

    validate_success(api.cancel_event(ctx["event"]["id"], COORD), 200)

    item_after = validate_success(api.get_repair_item(item["id"], COORD), 200)
    assert item_after["status"] == "WITHDRAWN", (
        "hop 1: every item of the event becomes WITHDRAWN")

    reservation_after = validate_success(
        api.get_part_reservation(reservation["id"], COORD), 200)
    assert reservation_after["status"] == "RELEASED", (
        "hop 2: RESERVED reservations on those items become RELEASED")

    stock_after = validate_success(api.get_part_stock(stock["id"], COORD), 200)
    assert stock_after["quantity_reserved"] == 0
    assert stock_after["quantity_on_hand"] == 5, (
        "hop 3: reserve+release conserves physical on-hand stock")

    station = validate_success(api.get_station(ctx["station"]["id"], COORD), 200)
    assert station["status"] == "CLOSED"
    shift = validate_success(api.get_fixer_shift(ctx["shift"]["id"], COORD), 200)
    assert shift["status"] == "CANCELLED"


def test_event_cancel_from_published_cascades(api):
    """PRD §3.7: "Cancellation (`→ CANCELLED`) is available from every
    non-terminal event state — `DRAFT`, `PUBLISHED`, `INTAKE_OPEN`,
    `REPAIR_ACTIVE`, and `CLOSED` — and runs a full teardown cascade: every
    item of the event becomes `WITHDRAWN`; every `RESERVED` reservation on
    those items becomes `RELEASED` with stock figures recomputed; every station
    becomes `CLOSED`; and every non-terminal shift becomes `CANCELLED`."

    Design: Difficulty/transitive_cascade/event_cancel_cascade_depth3
    """
    ctx = setup_published_event_with_checked_in_fixer(event_name="Cafe Theta-2")

    cancelled = validate_success(api.cancel_event(ctx["event"]["id"], COORD), 200)
    assert cancelled["status"] == "CANCELLED", (
        "cancellation is available from PUBLISHED, a non-terminal state")

    station = validate_success(api.get_station(ctx["station"]["id"], COORD), 200)
    assert station["status"] == "CLOSED"
    # The CHECKED_IN shift is non-terminal, so the cascade cancels it too.
    shift = validate_success(api.get_fixer_shift(ctx["shift"]["id"], COORD), 200)
    assert shift["status"] == "CANCELLED"


# ─── incident segregation of duties ─────────────────────────────────────────

def test_incident_resolve_segregation_of_duties(api):
    """PRD §3.6: "Resolution is the exclusive province of a `SafetyOfficer`,
    and segregation of duties applies: the resolver must not be the reporter,
    on pain of `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/state_machines/incident_resolve_segregation_of_duties
    """
    set_logical_clock()
    event = create_event(name="Cafe Gimel")
    incident = report_incident(event["id"], severity="LOW",
                               description="trailing cable",
                               headers=make_safety_officer_headers("so-1"))

    # The reporting SafetyOfficer cannot resolve their own incident.
    res = api.resolve_incident(incident["id"], "WARNING",
                               make_safety_officer_headers("so-1"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    # A different SafetyOfficer may resolve it.
    resolved = validate_success(api.resolve_incident(
        incident["id"], "WARNING", make_safety_officer_headers("so-2")), 200)
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution_action"] == "WARNING"


# ─── event close checkpoint: reliability penalties ─────────────────────────

def test_reliability_no_show_and_left_early_penalties_at_close(api):
    """PRD §3.7: "The checkpoint sweeps the whole event in one atomic act:
    every shift still `CONFIRMED` becomes `NO_SHOW` and its fixer loses 15
    reliability points; every shift still `CHECKED_IN` becomes `LEFT_EARLY`
    and loses 5; every part reservation still `RESERVED` on an item of the
    event becomes `EXPIRED`, with stock `quantity_reserved` recomputed; and
    every station in `SETUP`, `OPEN`, or `PAUSED` becomes `CLOSED`."
    PRD §3.1: "A new `FixerProfile` starts `ACTIVE` with a `reliability_score`
    of 100."

    Design: Corner/calculations/reliability_no_show_and_left_early_penalties_at_close
    """
    set_logical_clock()
    event = create_event(name="Cafe He")
    station1 = create_station(event["id"], category="BIKE", label="B1")
    station2 = create_station(event["id"], category="BIKE", label="B2")
    fixer_n = register_fixer(display_name="Fixer N")
    fixer_l = register_fixer(display_name="Fixer L")
    add_skill(fixer_l["id"], category="BIKE", level=3)
    shift_n = sign_up_shift(fixer_n["id"], station2["id"], event["id"])
    shift_l = sign_up_shift(fixer_l["id"], station1["id"], event["id"])
    publish_event(event["id"])
    confirm_shift(shift_n["id"])   # never checks in -> NO_SHOW at close
    confirm_shift(shift_l["id"])
    check_in_shift(shift_l["id"], fixer_l["id"])  # -> LEFT_EARLY at close
    open_station(station1["id"])
    open_intake(event["id"])
    begin_repairs(event["id"])

    closed = validate_success(api.close_event(event["id"], COORD), 200)
    assert closed["status"] == "CLOSED"

    shift_n_after = validate_success(
        api.get_fixer_shift(shift_n["id"], COORD), 200)
    assert shift_n_after["status"] == "NO_SHOW"
    fixer_n_after = validate_success(
        api.get_fixer_profile(fixer_n["id"], COORD), 200)
    assert fixer_n_after["reliability_score"] == 85, "100 - 15 no-show penalty"

    shift_l_after = validate_success(
        api.get_fixer_shift(shift_l["id"], COORD), 200)
    assert shift_l_after["status"] == "LEFT_EARLY"
    fixer_l_after = validate_success(
        api.get_fixer_profile(fixer_l["id"], COORD), 200)
    assert fixer_l_after["reliability_score"] == 95, "100 - 5 left-early penalty"


# ─── event close precondition ───────────────────────────────────────────────

def test_event_close_with_nonterminal_items_rejected(api):
    """PRD §3.7: "Closing an event (`REPAIR_ACTIVE → CLOSED`) is the ops-run
    checkpoint and is allowed only when every item of the event is terminal —
    `VERIFIED` or `WITHDRAWN` — otherwise `ERR_EVENT_NOT_CLOSABLE`."

    Design: Corner/state_machines/event_close_with_nonterminal_items_rejected
    """
    ctx = setup_intake_open_event(event_name="Cafe Bet")
    progress_item_to_queued(ctx, description="Mixer", weight_kg_estimated=2.2,
                            severity=2, estimated_difficulty=1,
                            diagnosis="gear")
    begin_repairs(ctx["event"]["id"])
    res = api.close_event(ctx["event"]["id"], COORD)
    validate_error(res, ApiErrorId.ERR_EVENT_NOT_CLOSABLE)
    event = validate_success(api.get_repair_event(ctx["event"]["id"], COORD), 200)
    assert event["status"] == "REPAIR_ACTIVE"


# ─── event report snapshot ──────────────────────────────────────────────────

def test_event_report_snapshot_strict_vs_lenient(api):
    """PRD §3.7: "Only a `CLOSED` event can be reported (`CLOSED → REPORTED`, a
    terminal state), and only once — a second report attempt fails with
    `ERR_INVALID_EVENT_STATE`."
    PRD §3.7: "Every metric is computed at that instant and frozen:
    `items_total` counts the event's items holding a `VERIFIED` outcome;
    `items_fixed`, `items_partially_fixed`, and `items_not_repairable` break
    that count down by `outcome`. Two success rates follow, each rounded
    half-up to four decimal places and each defined as 0 when `items_total` is
    0: `success_rate_strict` divides `items_fixed` by `items_total`, while
    `success_rate_lenient` adds half of `items_partially_fixed` to the
    numerator before dividing. The report also snapshots
    `diversion_kg_verified` and `diversion_kg_projected` from the event,
    records the event's committed parts spend as `parts_cost_total_cents`, and
    aggregates donations: `donations_receipt_total_cents` sums
    `receipt_value_cents` over the event's donations in `RECEIPTED` status,
    while `donations_campaign_total_cents` sums `campaign_value_cents` over
    donations in `RECEIVED` or `RECEIPTED`."

    Design: Corner/calculations/event_report_snapshot_strict_vs_lenient
    """
    ctx = setup_intake_open_event(event_name="Cafe Het")
    progress_item_to_verified(ctx, outcome="FIXED", weight_kg_actual=3.2,
                              description="Toaster", weight_kg_estimated=3.0,
                              severity=3, estimated_difficulty=2,
                              diagnosis="fuse")
    progress_item_to_verified(ctx, outcome="PARTIALLY_FIXED",
                              weight_kg_actual=2.0, description="Radio",
                              weight_kg_estimated=2.5, severity=2,
                              estimated_difficulty=1, diagnosis="wire")
    begin_repairs(ctx["event"]["id"])
    closed = validate_success(api.close_event(ctx["event"]["id"], COORD), 200)
    assert closed["status"] == "CLOSED"

    report = validate_success(api.report_event(ctx["event"]["id"], COORD), 201)
    assert report["event_id"] == ctx["event"]["id"]
    assert report["items_total"] == 2
    assert report["items_fixed"] == 1
    assert report["items_partially_fixed"] == 1
    assert report["items_not_repairable"] == 0
    assert report["success_rate_strict"] == pytest.approx(0.5, abs=1e-9)
    assert report["success_rate_lenient"] == pytest.approx(0.75, abs=1e-9)
    # Verified diversion: 3.2 + 0.5 * 2.0 = 4.2 kg, snapshotted at generation.
    assert report["diversion_kg_verified"] == pytest.approx(4.2, abs=0.01)

    event = validate_success(api.get_repair_event(ctx["event"]["id"], COORD), 200)
    assert event["status"] == "REPORTED"
