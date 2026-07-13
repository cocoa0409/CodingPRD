"""Booking eligibility: windows, caps, quotas, reciprocity, certification, fiscal
gates, validation precedence, and temporal-overlap semantics.

Translates queue B (Corner) `validations` instances plus queue A (Difficulty)
instances for priority-pair conflict and resource/temporal overlap.
"""
import test_helpers as th
from test_helpers import validate_success, validate_error, ApiErrorId


def _two_basic_members_one_boat():
    """Two ACTIVE BASIC SAIL members at one dock served by a single PONTOON boat."""
    th.make_tier("SAIL")
    dock = th.make_dock()["id"]
    b1 = th.make_boat(dock, "PONTOON")["id"]
    m1 = th.make_member("SAIL", dock, "M1", "m1@x.com")["id"]
    th.certify_orientation(m1, dock)
    th.certify_basic(m1, dock)
    m2 = th.make_member("SAIL", dock, "M2", "m2@x.com")["id"]
    th.certify_orientation(m2, dock)
    th.certify_basic(m2, dock)
    return dock, b1, m1, m2


def _request_then_confirm(api, member_hdr, member_id, dock_id, boat_type, start, end):
    """Request and (if created) confirm; return whichever Response first errors.

    The rotation-eligible-boat rule (PRD §3.4: requesting and confirming are both
    subject to it) may surface a no-boat rejection at either step.
    """
    resp = api.create_reservation(
        th.create_reservation_payload(member_id, dock_id, boat_type, start, end), member_hdr(member_id)
    )
    if resp.status_code < 400:
        rid = resp.json()["data"]["id"]
        resp = api.confirm_reservation(rid, member_hdr(member_id))
    return resp


# --------------------------------------------------------------------------- #
# validations (queue B)
# --------------------------------------------------------------------------- #
def test_booking_window_exceeded_returns_error(api, member_hdr):
    """PRD §3.4: "the tier's `advance_booking_days_max` is the maximum number of days
    beyond the current clock that a `start_time` may fall. A `start_time` in the past
    or beyond that horizon is rejected with `ERR_BOOKING_WINDOW` (HTTP 409)."

    Design: Corner/validations/booking_window_exceeded_returns_error
    """
    ctx = th.setup_active_basic_member("SAIL")
    m = ctx["member_id"]
    resp = api.create_reservation(
        th.create_reservation_payload(m, ctx["dock_id"], "PONTOON", "2026-06-10T10:00:00Z", "2026-06-10T12:00:00Z"),
        member_hdr(m),
    )
    validate_error(resp, ApiErrorId.ERR_BOOKING_WINDOW)


def test_max_active_reservations_exceeded_returns_error(api, member_hdr):
    """PRD §3.4: "A member may hold only up to their tier's `max_active_reservations`
    reservations concurrently, counting those in `REQUESTED`, `CONFIRMED`, or
    `CHECKED_OUT`; exceeding that cap is rejected with `ERR_MAX_ACTIVE_RESERVATIONS`
    (HTTP 409)."

    Design: Corner/validations/max_active_reservations_exceeded_returns_error
    """
    ctx = th.setup_active_basic_member("SAIL", tier_overrides={"max_active_reservations": 1})
    m = ctx["member_id"]
    th.request_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    resp = api.create_reservation(
        th.create_reservation_payload(m, ctx["dock_id"], "PONTOON", "2026-05-06T10:00:00Z", "2026-05-06T12:00:00Z"),
        member_hdr(m),
    )
    validate_error(resp, ApiErrorId.ERR_MAX_ACTIVE_RESERVATIONS)


def test_weekly_quota_exceeded_on_confirm(api, member_hdr):
    """PRD §3.4: "A confirm that would push used past the weekly allowance is rejected
    with `ERR_WEEKLY_QUOTA_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/weekly_quota_exceeded_on_confirm
    """
    ctx = th.setup_active_basic_member(
        "SAIL", tier_overrides={"reservations_per_week": 1, "max_active_reservations": 3},
        boats=("PONTOON", "PONTOON"),
    )
    m = ctx["member_id"]
    th.set_clock("2026-05-04T08:00:00Z")
    th.create_confirmed_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    r2 = th.request_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-06T10:00:00Z", "2026-05-06T12:00:00Z")
    resp = api.confirm_reservation(r2["id"], member_hdr(m))
    validate_error(resp, ApiErrorId.ERR_WEEKLY_QUOTA_EXCEEDED)


def test_reciprocal_access_allowed_success(api, member_hdr):
    """PRD §3.4: "A member whose tier does not allow reciprocal access may not reserve
    a boat at a dock whose `is_reciprocal` flag is true; such an attempt is rejected
    with `ERR_RECIPROCAL_NOT_ALLOWED` (HTTP 422)."

    Design: Corner/validations/reciprocal_access_allowed_success
    """
    ctx = th.setup_active_basic_member("SAIL")  # SAIL allows reciprocal access
    m = ctx["member_id"]
    rd = th.make_dock(is_reciprocal=True)["id"]
    th.make_boat(rd, "PONTOON")
    resp = api.create_reservation(
        th.create_reservation_payload(m, rd, "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z"),
        member_hdr(m),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "REQUESTED"
    assert data["dock_id"] == rd


def test_reciprocal_access_denied_returns_error(api, member_hdr):
    """PRD §3.4: "A member whose tier does not allow reciprocal access may not reserve
    a boat at a dock whose `is_reciprocal` flag is true; such an attempt is rejected
    with `ERR_RECIPROCAL_NOT_ALLOWED` (HTTP 422)."

    Design: Corner/validations/reciprocal_access_denied_pure_constraint
    """
    ctx = th.setup_active_basic_member("CRUISE")  # CRUISE has no reciprocal access
    m = ctx["member_id"]
    rd = th.make_dock(is_reciprocal=True)["id"]
    th.make_boat(rd, "PONTOON")
    resp = api.create_reservation(
        th.create_reservation_payload(m, rd, "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z"),
        member_hdr(m),
    )
    validate_error(resp, ApiErrorId.ERR_RECIPROCAL_NOT_ALLOWED)


def test_center_console_requires_advanced_cert(api, member_hdr):
    """PRD §3.1: "a `CENTER_CONSOLE` requires `ADVANCED`, while a `PONTOON`,
    `BOWRIDER`, or `DECK_BOAT` requires at least `BASIC`. A booking whose requested
    type outstrips the member's certification is rejected with `ERR_CERT_INSUFFICIENT`
    (HTTP 422)".

    Design: Corner/validations/reservation_center_console_requires_advanced_cert
    """
    ctx = th.setup_active_basic_member("SAIL", boats=("CENTER_CONSOLE",))
    m = ctx["member_id"]
    resp = api.create_reservation(
        th.create_reservation_payload(m, ctx["dock_id"], "CENTER_CONSOLE", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z"),
        member_hdr(m),
    )
    validate_error(resp, ApiErrorId.ERR_CERT_INSUFFICIENT)


def test_reinstate_with_outstanding_fees_rejected(api, admin):
    """PRD §3.1: "reinstatement is permitted only when the member's
    `outstanding_fees_cents` is exactly zero (every fee either paid or waived), and is
    otherwise rejected with `ERR_OUTSTANDING_FEES` (HTTP 402)."

    Design: Corner/validations/reinstate_with_outstanding_fees_rejected
    """
    ctx = th.setup_active_basic_member("SAIL")
    m, b1 = ctx["member_id"], ctx["boat_ids"][0]
    r = th.request_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    th.assessed_damage_fee(r["id"], b1, "MODERATE", 30000)  # 30000 ASSESSED DAMAGE fee
    th.suspend_member(m)
    resp = api.reinstate_member(m, admin)
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_FEES)
    assert th.get_member(m)["status"] == "SUSPENDED"


# --------------------------------------------------------------------------- #
# priority_pair_validation_conflict (queue A) — safety beats fiscal
# --------------------------------------------------------------------------- #
def _safety_and_fiscal_conflict_member():
    """A CRUISE ACTIVE BASIC member with outstanding fees over the block limit and a
    CENTER_CONSOLE boat available — so a CENTER_CONSOLE request trips BOTH cert (tier 7)
    and fiscal (tier 10)."""
    ctx = th.setup_active_basic_member("CRUISE", tier_overrides={"max_active_reservations": 2},
                                       boats=("PONTOON", "CENTER_CONSOLE"))
    m, b1 = ctx["member_id"], ctx["boat_ids"][0]
    r0 = th.request_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T08:00:00Z", "2026-05-05T09:00:00Z")
    th.assessed_damage_fee(r0["id"], b1, "SEVERE", 60000)  # 60000 > FEE_BLOCK_LIMIT 50000
    return ctx


def test_safety_beats_fiscal_returns_cert_error(api, member_hdr):
    """PRD §2.8: "Seventh, safety and certification prerequisites." ... "Tenth, fiscal
    blocks. ... When two checks in different tiers could both fail, the lower-numbered
    tier's error is the one returned."
    PRD §3.1: "A booking whose requested type outstrips the member's certification is
    rejected with `ERR_CERT_INSUFFICIENT` (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/pc_safety_beats_fiscal_on_request
    """
    ctx = _safety_and_fiscal_conflict_member()
    m = ctx["member_id"]
    resp = api.create_reservation(
        th.create_reservation_payload(m, ctx["dock_id"], "CENTER_CONSOLE", "2026-05-06T10:00:00Z", "2026-05-06T12:00:00Z"),
        member_hdr(m),
    )
    validate_error(resp, ApiErrorId.ERR_CERT_INSUFFICIENT)


def test_safety_beats_fiscal_does_not_return_fiscal_error(api, member_hdr):
    """PRD §2.8: "When two checks in different tiers could both fail, the lower-numbered
    tier's error is the one returned."
    PRD §3.4: "a new reservation is refused when the member's `outstanding_fees_cents`
    exceeds the 50,000-cent reservation block limit, rejected with `ERR_OUTSTANDING_FEES`"

    Design: Difficulty/priority_pair_validation_conflict/pc_safety_beats_fiscal_on_request
    """
    ctx = _safety_and_fiscal_conflict_member()
    m = ctx["member_id"]
    # The fiscal violation is genuinely present (outstanding over the block limit)...
    assert th.get_member(m)["outstanding_fees_cents"] == 60000
    resp = api.create_reservation(
        th.create_reservation_payload(m, ctx["dock_id"], "CENTER_CONSOLE", "2026-05-06T10:00:00Z", "2026-05-06T12:00:00Z"),
        member_hdr(m),
    )
    # ...yet the lower-numbered safety tier wins, so the fiscal error is NOT returned.
    err = validate_error(resp, ApiErrorId.ERR_CERT_INSUFFICIENT)
    assert err["error_id"] != "ERR_OUTSTANDING_FEES"


# --------------------------------------------------------------------------- #
# resource_temporal_overlap (queue A)
# --------------------------------------------------------------------------- #
def test_boat_overlap_rejected_no_boat_available(api, member_hdr):
    """PRD §3.2: "its window overlaps the new reservation's window under half-open
    semantics — that is, the new reservation's `start_time` is strictly before the
    other's `end_time` and the other's `start_time` is strictly before the new
    reservation's `end_time`."
    PRD §3.2: "If no candidate survives, confirmation is rejected with
    `ERR_NO_BOAT_AVAILABLE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/to_boat_halfopen_adjacency_allowed
    """
    dock, b1, m1, m2 = _two_basic_members_one_boat()
    th.create_confirmed_reservation(m1, dock, "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    # r_b (11:00-13:00) strictly overlaps r_a on the only boat -> no candidate survives.
    resp = _request_then_confirm(api, member_hdr, m2, dock, "PONTOON", "2026-05-05T11:00:00Z", "2026-05-05T13:00:00Z")
    validate_error(resp, ApiErrorId.ERR_NO_BOAT_AVAILABLE)


def test_boat_adjacent_window_confirmed(api, member_hdr):
    """PRD §3.2: "its window overlaps the new reservation's window under half-open
    semantics — that is, the new reservation's `start_time` is strictly before the
    other's `end_time` and the other's `start_time` is strictly before the new
    reservation's `end_time`."

    Design: Difficulty/resource_temporal_overlap/to_boat_halfopen_adjacency_allowed
    """
    dock, b1, m1, m2 = _two_basic_members_one_boat()
    th.create_confirmed_reservation(m1, dock, "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    # r_d starts exactly at r_a's end -> half-open [start,end) means no overlap; b1 is eligible.
    r_d = th.request_reservation(m2, dock, "PONTOON", "2026-05-05T12:00:00Z", "2026-05-05T14:00:00Z")
    resp = api.confirm_reservation(r_d["id"], member_hdr(m2))
    data = validate_success(resp, 200)
    assert data["status"] == "CONFIRMED"
    assert data["boat_id"] == b1


def test_member_turnaround_gap_too_small_rejected(api, member_hdr):
    """PRD §3.4: "A member must also leave a turnaround gap of at least 60 minutes
    between this reservation and any of their other non-terminal reservations; a
    request that sits closer than that 60-minute turnaround to an existing booking is
    rejected with `ERR_MEMBER_SCHEDULE_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/to_member_buffer_60min_gap
    """
    ctx = th.setup_active_basic_member("SAIL")
    m = ctx["member_id"]
    th.request_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    # 12:30 start sits 30 minutes after the 12:00 end -> under the 60-minute turnaround.
    resp = api.create_reservation(
        th.create_reservation_payload(m, ctx["dock_id"], "PONTOON", "2026-05-05T12:30:00Z", "2026-05-05T14:00:00Z"),
        member_hdr(m),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_SCHEDULE_CONFLICT)


def test_member_turnaround_gap_sufficient_accepted(api, member_hdr):
    """PRD §3.4: "A member must also leave a turnaround gap of at least 60 minutes
    between this reservation and any of their other non-terminal reservations; a
    request that sits closer than that 60-minute turnaround to an existing booking is
    rejected with `ERR_MEMBER_SCHEDULE_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/to_member_buffer_60min_gap
    """
    ctx = th.setup_active_basic_member("SAIL")
    m = ctx["member_id"]
    th.request_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    # 13:30 start sits 90 minutes after the 12:00 end -> beyond the 60-minute turnaround.
    resp = api.create_reservation(
        th.create_reservation_payload(m, ctx["dock_id"], "PONTOON", "2026-05-05T13:30:00Z", "2026-05-05T15:00:00Z"),
        member_hdr(m),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "REQUESTED"
