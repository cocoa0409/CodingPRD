"""Entitlement lifecycle: freeze/thaw parallel dimensions, auto-renew via the ops sweep,
rollover capping, expiry, freeze-ceiling enforcement, and intro eligibility.

Translates difficulty instance `entitlement_parallel_lifecycle_x_freeze_dimensions` and
corner instances from sections `calculations`, `validations`, `errors`, and
`cross_cutting_complexity_layers`.

NOTE: the difficulty instance `renewal_proration_round_per_segment_then_sum` is intentionally
not translated — PRD §3.8 describes the per-segment proration math but exposes no input pathway
to supply the price segments (segment_days / monthly_rate_cents) and no observable output field
carrying the renewal charge, so the asserted 9266-cent value is not PRD-derivable or observable.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_member_headers,
    set_clock, run_ops, create_room, create_teacher, create_member,
    create_active_entitlement, create_published_session, book_reservation,
    create_intro_offer, make_member_established,
)

MGR = TEST_USERS["studio_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: entitlement_parallel_lifecycle_x_freeze_dimensions
# ---------------------------------------------------------------------------
def _setup_active_membership_march():
    """Member with an ACTIVE MEMBERSHIP, cycle_start 2026-03-01 (cycle_end 2026-03-31).
    Clock at 2026-03-01. Returns (member, entitlement)."""
    set_clock("2026-03-01T00:00:00Z")
    member = create_member(email="f@x.com", full_name="Fae")
    ent = create_active_entitlement(member["id"], kind="MEMBERSHIP", price_cents=10000,
                                    credits_total=-1, cycle_start_utc="2026-03-01T00:00:00Z")
    return member, ent


def test_freeze_flips_freeze_status_without_touching_lifecycle(api):
    """PRD §3.4: "A member may freeze an `ACTIVE`, `UNFROZEN` entitlement, which keeps
    `lifecycle_status` at `ACTIVE` but flips `freeze_status` to `FROZEN`."

    Design: Difficulty/non_linear_state_machine/entitlement_parallel_lifecycle_x_freeze_dimensions
    """
    member, ent = _setup_active_membership_march()
    set_clock("2026-03-05T00:00:00Z")
    resp = api.freeze_entitlement(ent["id"], make_member_headers(member["id"]))
    data = validate_success(resp, 200)
    assert data["freeze_status"] == "FROZEN"
    assert data["lifecycle_status"] == "ACTIVE", "lifecycle axis unchanged by a freeze"


def test_thaw_extends_cycle_end_by_ceil_frozen_days(api):
    """PRD §3.4: "On thaw of an `ACTIVE`, `FROZEN` entitlement, the system computes the frozen
    duration as the number of days elapsed between `frozen_at_utc` and the current clock, rounded
    up to a whole number of days, and then capped so that the new `frozen_days_consumed` does not
    exceed the 21-day per-cycle ceiling. That number of days is added to `cycle_end_utc`, the same
    number is added to `frozen_days_consumed`, `freeze_status` returns to `UNFROZEN`, and
    `frozen_at_utc` is cleared to null."

    Design: Difficulty/non_linear_state_machine/entitlement_parallel_lifecycle_x_freeze_dimensions
    """
    member, ent = _setup_active_membership_march()
    set_clock("2026-03-05T00:00:00Z")
    api.freeze_entitlement(ent["id"], make_member_headers(member["id"]))
    set_clock("2026-03-08T12:00:00Z")  # 3.5 days frozen -> ceil = 4
    resp = api.thaw_entitlement(ent["id"], make_member_headers(member["id"]))
    data = validate_success(resp, 200)
    assert data["freeze_status"] == "UNFROZEN"
    assert data["lifecycle_status"] == "ACTIVE"
    assert data["frozen_days_consumed"] == 4
    # cycle_end 2026-03-31 + 4 days -> 2026-04-04.
    assert data["cycle_end_utc"].startswith("2026-04-04"), \
        f"cycle_end extended by 4 days, got {data['cycle_end_utc']}"


# ---------------------------------------------------------------------------
# Corner: auto-renew, rollover, expiry
# ---------------------------------------------------------------------------
def test_single_segment_auto_renew_membership_stays_active(api):
    """PRD §3.3: "When instead the entitlement is an `ACTIVE`, `UNFROZEN` `MEMBERSHIP` with
    `auto_renew` true and the clock has reached `cycle_end_utc`, the sweep renews it in place (the
    lifecycle stays `ACTIVE`): the new `cycle_start_utc` becomes the old `cycle_end_utc`, the new
    `cycle_end_utc` becomes that new start plus 30 days, the rollover described below is applied,
    and `frozen_days_consumed` resets to 0 for the fresh cycle."

    Design: Corner/calculations/single_segment_renewal_correct_charge
    """
    set_clock("2026-02-01T00:00:00Z")
    member = create_member(email="sr@x.com", full_name="Sr")
    ent = create_active_entitlement(member["id"], kind="MEMBERSHIP", price_cents=8000,
                                    credits_total=-1, cycle_start_utc="2026-02-01T00:00:00Z",
                                    auto_renew=True, rollover_cap=0)
    set_clock("2026-03-03T01:00:00Z")  # past cycle_end (2026-03-03)
    run_ops()
    data = validate_success(api.get_entitlement(ent["id"], MGR), 200)
    assert data["lifecycle_status"] == "ACTIVE", "auto-renew membership renews, does not expire"


def test_rollover_caps_carried_credits(api):
    """PRD §3.3: "Rollover on renewal carries the lesser of the entitlement's `credits_remaining`
    and its `rollover_cap` into the new cycle. After carrying, `credits_used` is reset so that
    `credits_remaining` equals `credits_total` plus the carried amount; any credits beyond the cap
    are forfeited."

    Design: Corner/calculations/rollover_caps_carried_credits
    """
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    member = create_member(email="ro@x.com", full_name="Ro")
    ent = create_active_entitlement(member["id"], kind="MEMBERSHIP", price_cents=5000,
                                    credits_total=5, cycle_start_utc="2026-02-01T00:00:00Z",
                                    auto_renew=True, rollover_cap=2)
    session = create_published_session(room["id"], teacher["id"], discipline="VINYASA",
                                       start_utc="2026-02-10T10:00:00Z",
                                       end_utc="2026-02-10T11:00:00Z", published_capacity=10)
    book_reservation(member["id"], session["id"], ent["id"])  # 1 used, 4 remaining
    set_clock("2026-03-03T01:00:00Z")
    run_ops()
    data = validate_success(api.get_entitlement(ent["id"], MGR), 200)
    assert data["lifecycle_status"] == "ACTIVE"
    # carried = min(4, 2) = 2; new credits_remaining = credits_total(5) + carried(2) = 7.
    assert data["credits_remaining"] == 7


def test_entitlement_expiry_via_ops_run(api):
    """PRD §3.3: "When the sweep finds the logical clock at or past an entitlement's
    `cycle_end_utc` while the entitlement is `ACTIVE` and `UNFROZEN`, and the entitlement is either
    not a membership or not set to auto-renew, the entitlement moves from `ACTIVE` to `EXPIRED` and
    its unused finite credits are forfeited."

    Design: Corner/cross_cutting_complexity_layers/entitlement_expiry_via_ops_run
    """
    set_clock("2026-02-01T00:00:00Z")
    member = create_member(email="ex@x.com", full_name="Ex")
    ent = create_active_entitlement(member["id"], kind="CLASS_PACK", price_cents=5000,
                                    credits_total=5, cycle_start_utc="2026-02-01T00:00:00Z",
                                    auto_renew=False)
    set_clock("2026-03-03T01:00:00Z")  # past cycle_end
    run_ops()
    data = validate_success(api.get_entitlement(ent["id"], MGR), 200)
    assert data["lifecycle_status"] == "EXPIRED"


# ---------------------------------------------------------------------------
# Corner: freeze ceiling + double-freeze + intro eligibility
# ---------------------------------------------------------------------------
def test_freeze_limit_reached_rejected(api):
    """PRD §3.4: "A freeze is permitted only while `frozen_days_consumed` is strictly below the
    per-cycle freeze ceiling of 21 days; a freeze attempted at or above that ceiling is rejected
    with `ERR_FREEZE_LIMIT_REACHED` (HTTP 409)."

    Design: Corner/validations/freeze_limit_reached_rejected
    """
    set_clock("2026-03-01T00:00:00Z")
    member = create_member(email="fl@x.com", full_name="Fl")
    ent = create_active_entitlement(member["id"], kind="MEMBERSHIP", price_cents=10000,
                                    credits_total=-1, cycle_start_utc="2026-03-01T00:00:00Z")
    api.freeze_entitlement(ent["id"], make_member_headers(member["id"]))
    # Thaw after a span >= 21 days so frozen_days_consumed reaches the ceiling.
    set_clock("2026-03-25T00:00:00Z")
    api.thaw_entitlement(ent["id"], make_member_headers(member["id"]))
    resp = api.freeze_entitlement(ent["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_FREEZE_LIMIT_REACHED.value, 409)


def test_entitlement_double_freeze_returns_error(api):
    """PRD §3.4: "Attempting to freeze an entitlement that is already `FROZEN` (or to thaw one
    that is already `UNFROZEN`) is rejected with `ERR_ENTITLEMENT_FROZEN` (HTTP 409)."

    Design: Corner/errors/entitlement_double_freeze_returns_error
    """
    set_clock("2026-03-01T00:00:00Z")
    member = create_member(email="df@x.com", full_name="Df")
    ent = create_active_entitlement(member["id"], kind="MEMBERSHIP", price_cents=10000,
                                    credits_total=-1, cycle_start_utc="2026-03-01T00:00:00Z")
    api.freeze_entitlement(ent["id"], make_member_headers(member["id"]))
    resp = api.freeze_entitlement(ent["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_FROZEN.value, 409)


def test_intro_offer_not_eligible_for_established_member(api):
    """PRD §3.3: "the buying member must currently have `is_new_student` true, the referenced
    `intro_offer_id` must name an `ACTIVE` `IntroOffer`, and the member must not already hold an
    `INTRO` entitlement (at most one per member). Any violation is rejected with
    `ERR_INTRO_NOT_ELIGIBLE` (HTTP 409)."

    Design: Corner/validations/intro_offer_not_eligible_for_established_member
    """
    set_clock("2026-02-01T00:00:00Z")
    room = create_room(room_type="MAT", station_capacity=10)
    teacher = create_teacher(full_name="Tia", certifications=["VINYASA"])
    offer = create_intro_offer(name="Two Weeks Unlimited", price_cents=3000,
                               credits_total=-1, window_days=14)
    member = create_member(email="ie@x.com", full_name="Ie")
    ent = create_active_entitlement(member["id"], kind="MEMBERSHIP", price_cents=10000, credits_total=-1)
    # Establish the member (attend one) so is_new_student becomes false.
    make_member_established(member["id"], room["id"], teacher["id"], ent["id"],
                           discipline="VINYASA",
                           start_utc="2026-02-05T10:00:00Z", end_utc="2026-02-05T11:00:00Z")
    resp = api.create_entitlement(
        {"member_id": member["id"], "kind": "INTRO", "price_cents": 3000, "credits_total": -1,
         "cycle_start_utc": "2026-02-06T00:00:00Z", "intro_offer_id": offer["id"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INTRO_NOT_ELIGIBLE.value, 409)
