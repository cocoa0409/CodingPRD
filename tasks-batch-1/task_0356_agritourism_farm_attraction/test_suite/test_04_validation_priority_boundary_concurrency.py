"""Validation precedence, boundary precision, temporal overlap, and OCC.

Covers the two priority-pair conflicts (farm-not-open before sold-out; pass
validity before waiver on the confirm path), the pumpkin breakpoint and window
seat boundaries, the buffered window / half-open pass overlap rules, and the two
stale-window-version OCC paths.
"""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.test_users import make_visitor_headers, make_group_leader_headers
from test_helpers.factories import create_reservation_payload, create_admission_window_payload, create_season_pass_payload
from test_helpers.api_client import api_client

GATE = fx.GATE
MANAGER = fx.MANAGER


# ===========================================================================
# Queue A — priority_pair_validation_conflict / farm-not-open beats sold-out
# ===========================================================================

def test_farm_not_open_reported_over_sold_out(api):
    """PRD §3.3: "the checks are evaluated in a fixed order so that the most
    fundamental failure is the one reported."
    PRD §3.3: "The farm must be `OPEN`: a create attempted while the owning farm
    is on a weather hold or closed is rejected with `ERR_FARM_NOT_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/farm_not_open_beats_window_sold_out
    """
    fx.set_clock("2026-10-10T12:00:00Z")
    farm = fx.create_farm(name="Conflict Farm")
    fx.create_active_policy(farm["id"])
    # Window far in the future (survives a closure that targets an earlier span).
    window = fx.create_window(farm["id"], capacity=1,
                              starts_at="2026-10-20T14:00:00Z", ends_at="2026-10-20T16:00:00Z")
    v1 = fx.create_visitor(email="c1@x.com", full_name="Cara One")
    v2 = fx.create_visitor(email="c2@x.com", full_name="Cody Two")

    # Exhaust the window (capacity 1) so a second create is sold out.
    res1 = fx.create_pending_reservation(window["id"], v1["id"], window["version"],
                                         adult_count=1, child_count=0)
    fx.confirm_reservation(res1["id"], v1["id"])
    # Close the farm via a CLOSURE on a DIFFERENT span so the future window survives
    # but the farm posture is CLOSED.
    fx.declare_closure(farm["id"], affected_span_start="2026-10-11T00:00:00Z",
                       affected_span_end="2026-10-12T00:00:00Z",
                       note="Storm elsewhere; the 10-20 window survives")

    v_now = fx.window_version(window["id"])
    resp = api.create_reservation(
        create_reservation_payload(window["id"], v2["id"], v_now, adult_count=1, child_count=0),
        make_visitor_headers(v2["id"]))
    validate_error(resp, ApiErrorId.ERR_FARM_NOT_OPEN.value)


def test_reservation_create_blocked_when_farm_closed(api):
    """PRD §3.3: "The farm must be `OPEN`: a create attempted while the owning
    farm is on a weather hold or closed is rejected with `ERR_FARM_NOT_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/farm_not_open_beats_window_sold_out
    """
    fx.set_clock("2026-10-10T12:00:00Z")
    farm = fx.create_farm(name="Closed Create Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=5,
                              starts_at="2026-10-20T14:00:00Z", ends_at="2026-10-20T16:00:00Z")
    visitor = fx.create_visitor(email="cc@x.com", full_name="Cleo Closed")
    fx.declare_closure(farm["id"], affected_span_start="2026-10-11T00:00:00Z",
                       affected_span_end="2026-10-12T00:00:00Z", note="Closure elsewhere")

    v_now = fx.window_version(window["id"])
    resp = api.create_reservation(
        create_reservation_payload(window["id"], visitor["id"], v_now, adult_count=1, child_count=0),
        make_visitor_headers(visitor["id"]))
    validate_error(resp, ApiErrorId.ERR_FARM_NOT_OPEN.value)


# ===========================================================================
# Queue A — priority_pair_validation_conflict / pass validity beats waiver
# ===========================================================================

def test_confirm_revoked_pass_reports_pass_not_valid(api):
    """PRD §3.3: "Confirmation is permitted only on a `PENDING` reservation whose
    owning farm is `OPEN` and whose window is not `CANCELLED`, and — if the
    reservation redeems a pass — only when that pass is `ACTIVE` and its validity
    covers the window start (the same `ERR_PASS_NOT_VALID` guard applies)."

    Design: Difficulty/priority_pair_validation_conflict/pass_not_valid_beats_waiver_incomplete
    """
    fx.set_clock("2026-10-10T12:00:00Z")
    farm = fx.create_farm(name="Pass Conflict Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=5,
                              starts_at="2026-10-20T14:00:00Z", ends_at="2026-10-20T16:00:00Z")
    visitor = fx.create_visitor(email="pv@x.com", full_name="Penny Valid")
    season_pass = fx.create_season_pass(farm["id"], visitor["id"],
                                        valid_from="2026-10-01T00:00:00Z",
                                        valid_until="2026-11-01T00:00:00Z")
    res = fx.create_pending_reservation(window["id"], visitor["id"], window["version"],
                                        adult_count=1, child_count=0, season_pass_id=season_pass["id"])
    # Revoke the pass after the (PENDING) reservation was created; no waivers signed.
    validate_success(api.revoke_season_pass(season_pass["id"], MANAGER))

    resp = api.confirm_reservation(res["id"], make_visitor_headers(visitor["id"]))
    validate_error(resp, ApiErrorId.ERR_PASS_NOT_VALID.value)


def test_confirm_active_pass_succeeds(api):
    """PRD §3.3: "Confirmation moves the reservation `PENDING → CONFIRMED`,
    subtracts `participant_count` from the window's `seats_held` and adds it to
    `seats_committed`, recomputes `seats_available`, flips the window to
    `SOLD_OUT` if availability reaches 0, re-pins the provisional
    `admission_charge_cents`, and — when a pass is redeemed — increments that
    pass's `visits_used` by one."

    Design: Difficulty/priority_pair_validation_conflict/pass_not_valid_beats_waiver_incomplete
    """
    fx.set_clock("2026-10-10T12:00:00Z")
    farm = fx.create_farm(name="Pass OK Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=5,
                              starts_at="2026-10-20T14:00:00Z", ends_at="2026-10-20T16:00:00Z")
    visitor = fx.create_visitor(email="pok@x.com", full_name="Polly OK")
    season_pass = fx.create_season_pass(farm["id"], visitor["id"],
                                        valid_from="2026-10-01T00:00:00Z",
                                        valid_until="2026-11-01T00:00:00Z")
    res = fx.create_pending_reservation(window["id"], visitor["id"], window["version"],
                                        adult_count=1, child_count=0, season_pass_id=season_pass["id"])

    confirmed = validate_success(
        api.confirm_reservation(res["id"], make_visitor_headers(visitor["id"])))
    assert confirmed["status"] == "CONFIRMED", "confirm must succeed with an ACTIVE pass"


# ===========================================================================
# Queue A — boundary_precision_check / pumpkin breakpoint
# ===========================================================================

def test_pumpkin_exactly_at_breakpoint_is_flat_each(api):
    """PRD §3.5: "The comparison is inclusive at the breakpoint — a pumpkin
    weighing exactly `heavy_pumpkin_lb` is flat-each, not per-pound."
    PRD §3.5: "a pumpkin whose weight is at or above the breakpoint is a heavy
    pumpkin and is charged the flat `pumpkin_flat_each_cents` regardless of exact
    weight".

    Design: Difficulty/boundary_precision_check/pumpkin_breakpoint_exactly_20lb_is_flat
    """
    s = fx.setup_checked_in(capacity=10, adult_count=1, child_count=0)
    res = s["reservation"]
    pk20 = fx.add_pumpkin(res["id"], s["visitor"]["id"], estimated_weight_lb=20)
    weighed = fx.weigh_out(pk20["id"], scale_weight_lb=20)
    # exactly 20 == breakpoint -> flat 2500 (NOT per-lb 3000).
    assert weighed["charge_cents"] == 2500, (
        f"20.0 lb (== breakpoint) must be flat-each 2500, got {weighed['charge_cents']}"
    )


def test_pumpkin_just_below_breakpoint_is_per_lb(api):
    """PRD §3.5: "a pumpkin below the breakpoint is charged per pound, its weight
    multiplied by `pumpkin_per_lb_cents` and rounded half-up to whole cents."

    Design: Difficulty/boundary_precision_check/pumpkin_breakpoint_exactly_20lb_is_flat
    """
    s = fx.setup_checked_in(capacity=10, adult_count=1, child_count=0)
    res = s["reservation"]
    pk19 = fx.add_pumpkin(res["id"], s["visitor"]["id"], estimated_weight_lb=19)
    weighed = fx.weigh_out(pk19["id"], scale_weight_lb=19)
    # 19 < 20 -> round_half_up(19 * 150) = 2850.
    assert weighed["charge_cents"] == 2850, (
        f"19.0 lb (< breakpoint) must be per-lb 2850, got {weighed['charge_cents']}"
    )


# ===========================================================================
# Queue A — boundary_precision_check / window seats exact fit
# ===========================================================================

def test_window_seats_exact_fit_succeeds(api):
    """PRD §3.3: "The window must have at least `participant_count` seats
    available before the hold is placed, or the create is rejected with
    `ERR_WINDOW_SOLD_OUT`."
    PRD §3.3: "A successful create lands the reservation in `PENDING` status,
    places a hold by adding `participant_count` to the window's `seats_held`".

    Design: Difficulty/boundary_precision_check/window_seats_exact_fit_succeeds_one_over_rejects
    """
    s = fx.setup_farm_with_visitor(capacity=3, visitor_email="f1@x.com")
    # participant_count 3 == seats_available 3 -> succeeds (>= holds at equality).
    res = fx.create_pending_reservation(s["window"]["id"], s["visitor"]["id"],
                                        s["window"]["version"], adult_count=2, child_count=1)
    assert res["participant_count"] == 3
    assert res["status"] == "PENDING"

    win_after = validate_success(api.get_admission_window(s["window"]["id"], MANAGER))
    assert win_after["seats_available"] == 0, "exact-fit reservation must exhaust the window"


def test_window_seats_one_over_capacity_rejected(api):
    """PRD §3.3: "The window must have at least `participant_count` seats
    available before the hold is placed, or the create is rejected with
    `ERR_WINDOW_SOLD_OUT`."

    Design: Difficulty/boundary_precision_check/window_seats_exact_fit_succeeds_one_over_rejects
    """
    s = fx.setup_farm_with_visitor(capacity=3, visitor_email="f2@x.com")
    # participant_count 4 > seats_available 3 -> ERR_WINDOW_SOLD_OUT.
    resp = api.create_reservation(
        create_reservation_payload(s["window"]["id"], s["visitor"]["id"], s["window"]["version"],
                                   adult_count=4, child_count=0),
        make_visitor_headers(s["visitor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_WINDOW_SOLD_OUT.value)


# ===========================================================================
# Queue A — resource_temporal_overlap / buffered window overlap
# ===========================================================================

def test_window_within_buffer_rejected(api):
    """PRD §3.1: "A gap of exactly `window_buffer_minutes` is allowed; any gap
    shorter than the buffer — including overlap and back-to-back scheduling — is
    a collision rejected with `ERR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/window_overlap_within_buffer_rejected
    """
    farm = fx.create_farm(name="Buffer Farm", window_buffer_minutes=30)
    fx.create_window(farm["id"], capacity=10,
                     starts_at="2026-10-11T14:00:00Z", ends_at="2026-10-11T16:00:00Z")
    w_ok = fx.create_window(farm["id"], capacity=10,
                            starts_at="2026-10-11T16:30:00Z", ends_at="2026-10-11T18:00:00Z")

    # New window 16:15-18:30 overlaps the 16:30 window and is < 30 min from the
    # 14:00-16:00 window's end -> collision.
    resp = api.create_admission_window(
        farm["id"],
        create_admission_window_payload(starts_at="2026-10-11T16:15:00Z",
                                        ends_at="2026-10-11T18:30:00Z", capacity=10),
        MANAGER)
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP.value)

    ok_after = validate_success(api.get_admission_window(w_ok["id"], MANAGER))
    assert ok_after["status"] == "SCHEDULED"


def test_window_gap_exactly_buffer_allowed(api):
    """PRD §3.1: "A gap of exactly `window_buffer_minutes` is allowed".

    Design: Difficulty/resource_temporal_overlap/window_overlap_within_buffer_rejected
    """
    farm = fx.create_farm(name="Buffer OK Farm", window_buffer_minutes=30)
    fx.create_window(farm["id"], capacity=10,
                     starts_at="2026-10-11T14:00:00Z", ends_at="2026-10-11T16:00:00Z")
    # 16:30 starts exactly 30 minutes after 16:00 end -> allowed.
    ok = validate_success(api.create_admission_window(
        farm["id"],
        create_admission_window_payload(starts_at="2026-10-11T16:30:00Z",
                                        ends_at="2026-10-11T18:00:00Z", capacity=10),
        MANAGER), 201)
    assert ok["status"] == "SCHEDULED", "a gap of exactly the buffer must be accepted"


# ===========================================================================
# Queue A — resource_temporal_overlap / half-open pass validity overlap
# ===========================================================================

def test_season_pass_validity_overlap_rejected(api):
    """PRD §3.2: "a new pass collides with an existing `ACTIVE` pass for the same
    visitor and farm unless one's `valid_until` is at or before the other's
    `valid_from`."
    PRD §3.2: "A genuine overlap is rejected with `ERR_PASS_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/season_pass_validity_overlap_rejected_adjacency_ok
    """
    farm = fx.create_farm(name="Pass Overlap Farm")
    fx.create_active_policy(farm["id"])
    visitor = fx.create_visitor(email="ov@x.com", full_name="Ollie Overlap")
    fx.create_season_pass(farm["id"], visitor["id"],
                          valid_from="2026-10-01T00:00:00Z", valid_until="2026-10-15T00:00:00Z")
    pass2 = fx.create_season_pass(farm["id"], visitor["id"],
                                  valid_from="2026-10-15T00:00:00Z", valid_until="2026-11-01T00:00:00Z")

    # 2026-10-10..2026-10-20 overlaps both existing passes -> rejected.
    resp = api.create_season_pass(
        farm["id"],
        create_season_pass_payload(visitor["id"], valid_from="2026-10-10T00:00:00Z",
                                   valid_until="2026-10-20T00:00:00Z"),
        MANAGER)
    validate_error(resp, ApiErrorId.ERR_PASS_OVERLAP.value)

    pass2_after = validate_success(api.get_season_pass(pass2["id"], MANAGER))
    assert pass2_after["status"] == "ACTIVE"


def test_season_pass_back_to_back_adjacency_allowed(api):
    """PRD §3.2: "Back-to-back passes where one's `valid_until` exactly equals the
    next's `valid_from` leave no gap yet do not collide, because the intervals
    are half-open."

    Design: Difficulty/resource_temporal_overlap/season_pass_validity_overlap_rejected_adjacency_ok
    """
    farm = fx.create_farm(name="Pass Adjacency Farm")
    fx.create_active_policy(farm["id"])
    visitor = fx.create_visitor(email="adj@x.com", full_name="Ada Adjacent")
    fx.create_season_pass(farm["id"], visitor["id"],
                          valid_from="2026-10-01T00:00:00Z", valid_until="2026-10-15T00:00:00Z")

    # valid_from == prior valid_until (zero gap) -> allowed.
    pass2 = validate_success(api.create_season_pass(
        farm["id"],
        create_season_pass_payload(visitor["id"], valid_from="2026-10-15T00:00:00Z",
                                   valid_until="2026-11-01T00:00:00Z"),
        MANAGER), 201)
    assert pass2["status"] == "ACTIVE", "adjacency (half-open) must not collide"


# ===========================================================================
# Queue B — cross_cutting_complexity_layers / OCC reservation create
# ===========================================================================

def test_reservation_create_stale_window_version_rejected(api):
    """PRD §2.8: "A request to create a reservation must carry
    `expected_window_version` matching the target window's current `version`; if
    another writer has advanced the window's `version` since the client last read
    it — for instance by placing a competing hold that legitimately consumed
    inventory — the create is rejected with `ERR_WINDOW_VERSION_STALE`".

    Design: Corner/cross_cutting_complexity_layers/reservation_create_stale_window_version_412
    """
    s = fx.setup_farm_with_visitor(capacity=10, visitor_email="o1@x.com")
    v2 = fx.create_visitor(email="o2@x.com", full_name="Oz Two")
    stale_version = s["window"]["version"]

    # First create advances the window version.
    fx.create_pending_reservation(s["window"]["id"], s["visitor"]["id"], stale_version,
                                  adult_count=1, child_count=0)

    # Second create reuses the now-stale version -> 412.
    resp = api.create_reservation(
        create_reservation_payload(s["window"]["id"], v2["id"], stale_version,
                                   adult_count=1, child_count=0),
        make_visitor_headers(v2["id"]))
    validate_error(resp, ApiErrorId.ERR_WINDOW_VERSION_STALE.value)


# ===========================================================================
# Queue B — cross_cutting_complexity_layers / OCC group confirm
# ===========================================================================

def test_group_confirm_stale_window_version_rejected(api):
    """PRD §2.8: "The second guarded path is group-booking confirmation, which
    commits a whole block of seats at once: that request also carries
    `expected_window_version`, and if the window's `version` has advanced since
    the leader last requoted, the confirm is rejected with
    `ERR_WINDOW_VERSION_STALE`."

    Design: Corner/cross_cutting_complexity_layers/group_confirm_stale_window_version_412
    """
    farm = fx.create_farm(name="Group OCC Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=20)
    leader = fx.create_visitor(email="gocl@x.com", full_name="Gus Lead")
    indiv = fx.create_visitor(email="goci@x.com", full_name="Gwen Indiv")
    group = fx.create_group(farm["id"], window["id"], leader["id"], "FIELD_TRIP",
                            adult_count=4, child_count=6)
    stale_version = window["version"]

    # A reservation create advances the window version, staling the leader's view.
    fx.create_pending_reservation(window["id"], indiv["id"], stale_version,
                                  adult_count=1, child_count=0)

    resp = api.confirm_group_booking(
        group["id"], {"expected_window_version": stale_version},
        make_group_leader_headers(leader["id"]))
    validate_error(resp, ApiErrorId.ERR_WINDOW_VERSION_STALE.value)

    group_after = validate_success(api.get_group_booking(group["id"], make_group_leader_headers(leader["id"])))
    assert group_after["status"] == "QUOTED", "group must stay QUOTED after a stale-version reject"
