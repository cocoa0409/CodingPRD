"""Fitting appointments: tiered/combinatorial fee calculation, the fitter pairwise
buffer, past-date guard, and terminal-state lockdown."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_member_headers, make_staff_headers,
    fixtures as fx,
)
import test_helpers.factories as f


def _store_fitter_member(api, tier=None):
    fx.set_clock(api, "2026-07-01T00:00:00Z")
    store = fx.new_store(api)
    fitter = fx.new_staff(api, store["id"], role_type="FITTER")
    member = fx.new_member(api)
    if tier is not None:
        sub = fx.new_subscription(api, member["id"], member["version"], tier=tier)
        from test_helpers import get_success_data
        get_success_data(api.activate_subscription(sub["id"], make_member_headers(member["id"])))
        member = fx.get_member(api, member["id"])
    return store, fitter, member


def test_included_fitting_is_free_and_consumes_allowance(api):
    """PRD §3.3: "If the member holds an `ACTIVE` subscription and has not yet used
    their full monthly allowance — that is, `fittings_used_this_period` is strictly
    less than `included_fittings_per_month` — the fitting is free (`fee_cents` is 0)
    and counts as an included fitting: completion increments that subscription's
    `fittings_used_this_period` by one."

    Design: Difficulty/combinatorial_formula/fitting_fee_nonlinear_nonincluded_mode_a
    """
    store, fitter, member = _store_fitter_member(api, tier="CLUB_BASIC")
    a1 = fx.new_appointment(api, member["id"], fitter["id"], service_type="GAIT_ANALYSIS",
                            start_at="2026-07-10T10:00:00Z", end_at="2026-07-10T10:30:00Z")
    completed = fx.complete_appointment(api, a1["id"], fitter["id"], gait_result={"pronation": "NEUTRAL"})
    assert completed["fee_cents"] == 0


def test_fitting_after_allowance_exhausted_applies_capped_discount(api):
    """PRD §3.3: "Otherwise, if the member holds an `ACTIVE` subscription but the
    included allowance is exhausted, a discount applies: the subscription's training
    discount for its tier (10% for `CLUB_BASIC`, 20% for `CLUB_PRO`) is added to the
    member's loyalty discount (0% at `BRONZE`, 5% at `SILVER`, 10% at `GOLD`, 15% at
    `PLATINUM`), the sum is capped at 30%, and `fee_cents` is the base fee multiplied
    by one minus that capped discount, rounded half-up to whole cents; this branch
    does not consume an included fitting."

    Design: Difficulty/combinatorial_formula/fitting_fee_nonlinear_nonincluded_mode_a
    """
    store, fitter, member = _store_fitter_member(api, tier="CLUB_BASIC")
    a1 = fx.new_appointment(api, member["id"], fitter["id"], service_type="GAIT_ANALYSIS",
                            start_at="2026-07-10T10:00:00Z", end_at="2026-07-10T10:30:00Z")
    fx.complete_appointment(api, a1["id"], fitter["id"])
    a2 = fx.new_appointment(api, member["id"], fitter["id"], service_type="GAIT_ANALYSIS",
                            start_at="2026-07-10T12:00:00Z", end_at="2026-07-10T12:30:00Z")
    completed = fx.complete_appointment(api, a2["id"], fitter["id"], gait_result={"pronation": "OVER"})
    assert completed["fee_cents"] == 5400


def test_fitting_no_subscription_charges_full_base(api):
    """PRD §3.3: "If the member has no `ACTIVE` subscription (none at all, or one
    that is `PENDING`, `PAST_DUE`, or `CANCELLED`), the full base fee is charged with
    no discount."

    Design: Corner/calculations/fitting_fee_no_subscription_full_base_price
    """
    store, fitter, member = _store_fitter_member(api)
    a = fx.new_appointment(api, member["id"], fitter["id"], service_type="SHOE_FITTING",
                           start_at="2026-07-10T14:00:00Z", end_at="2026-07-10T14:30:00Z")
    completed = fx.complete_appointment(api, a["id"], fitter["id"], gait_result={"pronation": "UNDER"})
    assert completed["fee_cents"] == 3000


def test_fitter_buffer_conflict_within_15_minutes_rejected(api):
    """PRD §3.3: "Concretely, a conflict exists when the requested start is earlier
    than the other appointment's end extended forward by 15 minutes, and
    simultaneously the other appointment's start is earlier than the requested end
    extended forward by 15 minutes; when both conditions hold the booking is rejected
    with `ERR_FITTER_UNAVAILABLE` (409)."

    Design: Difficulty/resource_temporal_overlap/fitting_pairwise_buffer_conflict_on_fitter
    """
    store, fitter, member = _store_fitter_member(api)
    fx.new_appointment(api, member["id"], fitter["id"], service_type="SHOE_FITTING",
                       start_at="2026-07-10T10:00:00Z", end_at="2026-07-10T10:30:00Z")
    resp = api.create_appointment(
        f.create_appointment_payload(member["id"], fitter["id"], service_type="SHOE_FITTING",
                                     start_at="2026-07-10T10:40:00Z", end_at="2026-07-10T11:10:00Z"),
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FITTER_UNAVAILABLE, 409)


def test_fitter_booking_exactly_15_minutes_apart_allowed(api):
    """PRD §3.3: "Two windows that sit exactly 15 minutes or more apart do not
    conflict."

    Design: Difficulty/resource_temporal_overlap/fitting_pairwise_buffer_conflict_on_fitter
    """
    store, fitter, member = _store_fitter_member(api)
    fx.new_appointment(api, member["id"], fitter["id"], service_type="SHOE_FITTING",
                       start_at="2026-07-10T10:00:00Z", end_at="2026-07-10T10:30:00Z")
    # Second window starts exactly 15 minutes after the first ends (10:30 + 15 = 10:45).
    data = validate_success(
        api.create_appointment(
            f.create_appointment_payload(member["id"], fitter["id"], service_type="SHOE_FITTING",
                                         start_at="2026-07-10T10:45:00Z", end_at="2026-07-10T11:15:00Z"),
            make_member_headers(member["id"]),
        ),
        201,
    )
    assert data["status"] == "SCHEDULED"


def test_book_appointment_in_past_rejected(api):
    """PRD §3.3: "First, no appointment may be booked in the past: `start_at` must be
    at or after the current logical clock, and an earlier `start_at` is rejected with
    `ERR_APPOINTMENT_IN_PAST` (422)."

    Design: Corner/validations/appointment_in_past_returns_error
    """
    store, fitter, member = _store_fitter_member(api)
    resp = api.create_appointment(
        f.create_appointment_payload(member["id"], fitter["id"], service_type="GAIT_ANALYSIS",
                                     start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T10:30:00Z"),
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_IN_PAST, 422)


def test_cancel_completed_appointment_rejected(api):
    """PRD §3.3: "Completing or cancelling an appointment that is not `SCHEDULED`
    yields `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/cancel_completed_appointment_returns_invalid_state
    """
    store, fitter, member = _store_fitter_member(api)
    a = fx.new_appointment(api, member["id"], fitter["id"], service_type="FOLLOWUP",
                           start_at="2026-07-10T10:00:00Z", end_at="2026-07-10T10:30:00Z")
    fx.complete_appointment(api, a["id"], fitter["id"])
    resp = api.cancel_appointment(a["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
