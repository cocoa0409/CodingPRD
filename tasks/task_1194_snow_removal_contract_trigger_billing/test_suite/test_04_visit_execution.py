"""Visit execution: state gates, photo gate/window, gap buffer, billing dimensions."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    create_visit_payload, create_photo_payload,
    setup_active_per_push, setup_storm_event, schedule_visit, set_clock,
    post_observation, verify_event, setup_completed_visit, setup_billable_visit,
    upload_photo, accept_photo,
)

DISPATCH = TEST_USERS["ops_dispatcher_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
CREW = TEST_USERS["crew_lead_headers"]


def test_visit_complete_from_scheduled_returns_invalid_state(api):
    """PRD §3.5: "Completing a visit moves `IN_PROGRESS` to `COMPLETED`."
    PRD §2.8: "Fifth, state legality: the target resource's state machine must allow the requested transition, failing as `ERR_INVALID_STATE`"
    PRD §3.5: "Starting a visit moves `SCHEDULED` to `IN_PROGRESS` and stamps `actual_start_at` from the logical clock." — without a start, actual_start_at stays null.

    Design: Corner/state_machines/visit_complete_from_scheduled_returns_invalid_state
    """
    ctx = setup_active_per_push(client_name="Bad Trans Co", require_photo_verification=False)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    visit = schedule_visit(event["id"], ctx["contract_site"]["id"])

    validate_error(api.complete_visit(visit["id"], CREW),
                   ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_visit(visit["id"], DISPATCH), 200)
    assert after["execution_status"] == "SCHEDULED"
    assert after.get("actual_start_at") is None


def test_completion_without_accepted_photo_returns_photo_required(api):
    """PRD §3.5: "When the contract's `require_photo_verification` is true, at least one `AFTER` photo of the visit with `review_status` `ACCEPTED` must exist, failing as `ERR_PHOTO_REQUIRED`."

    Design: Corner/validations/completion_without_accepted_photo_returns_photo_required
    """
    ctx = setup_active_per_push(client_name="Photo Gate Co",
                                require_photo_verification=True)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    visit = schedule_visit(event["id"], ctx["contract_site"]["id"])
    get_success_data(api.start_visit(visit["id"], CREW))
    upload_photo(visit["id"], "AFTER", "s3://proof/after.jpg")  # stays UPLOADED

    validate_error(api.complete_visit(visit["id"], CREW),
                   ApiErrorId.ERR_PHOTO_REQUIRED)


def test_visit_site_gap_buffer_conflict_rejected(api):
    """PRD §3.5: "for the same site — regardless of contract — a new visit conflicts with any existing non-`CANCELLED` visit unless the new `scheduled_start` is at least ninety minutes after the existing visit's `scheduled_end`, or the new `scheduled_end` is at least ninety minutes before the existing visit's `scheduled_start`; a gap of exactly ninety minutes is legal on either side, and a violation is rejected with `ERR_VISIT_GAP_CONFLICT`."

    Design: Corner/validations/visit_site_gap_buffer_conflict_rejected
    """
    ctx = setup_active_per_push(client_name="Gap Co", require_photo_verification=False)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    schedule_visit(event["id"], ctx["contract_site"]["id"],
                   scheduled_start="2026-12-10T09:00:00Z",
                   scheduled_end="2026-12-10T10:00:00Z")

    # 60-minute gap after the first visit's 10:00 end -> conflict.
    validate_error(api.create_visit(
        create_visit_payload(event["id"], ctx["contract_site"]["id"],
                             scheduled_start="2026-12-10T11:00:00Z",
                             scheduled_end="2026-12-10T12:00:00Z"),
        DISPATCH), ApiErrorId.ERR_VISIT_GAP_CONFLICT)

    # Exactly 90 minutes (10:00 -> 11:30) is legal.
    visit2 = validate_success(api.create_visit(
        create_visit_payload(event["id"], ctx["contract_site"]["id"],
                             scheduled_start="2026-12-10T11:30:00Z",
                             scheduled_end="2026-12-10T12:30:00Z"),
        DISPATCH), 201)
    assert visit2["execution_status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / trigger_depth_equality_boundary
# ---------------------------------------------------------------------------

def _verify_with_equal_readings(event_id, day, inches):
    post_observation(event_id, "NOAA", f"{day}T07:00:00Z", inches)
    post_observation(event_id, "DTN", f"{day}T07:30:00Z", inches)
    return verify_event(event_id)


def test_trigger_depth_just_below_trigger_stays_non_billable(api):
    """PRD §3.7: "A visit's `billing_status` moves from `PENDING` to `BILLABLE_CONFIRMED` when execution is `COMPLETED` and the event's `verified_accumulation_inches` is at least the applicable trigger depth"
    PRD §3.7: "When the trigger is not met, or execution ends anywhere other than `COMPLETED`, the visit falls to `NON_BILLABLE`."

    Design: Difficulty/boundary_precision_check/trigger_depth_equality_boundary
    """
    ctx = setup_active_per_push(client_name="Boundary Estates Low",
                                trigger_depth_inches=2.0, per_push_rate_cents=45_000)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event(reported_accumulation_inches=2.1)
    visit = setup_completed_visit(ctx, event)
    verified = _verify_with_equal_readings(event["id"], "2026-12-10", 1.99)
    assert verified["verified_accumulation_inches"] == 1.99

    visit_after = validate_success(api.get_visit(visit["id"], DISPATCH), 200)
    assert visit_after["billing_status"] == "NON_BILLABLE", "1.99 < 2.00 trigger"

    contract = validate_success(api.get_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert contract["season_billable_push_count"] == 0


def test_trigger_depth_exactly_equal_is_billable(api):
    """PRD §3.7: "with the comparison inclusive, so accumulation exactly equal to the trigger is billable"
    PRD §3.7: "For `PER_PUSH`, the visit's `billable_amount_cents` is simply the frozen `applied_per_push_rate_cents`."
    PRD §3.7: "`season_billable_push_count` counts the contract's visits with billing in `BILLABLE_CONFIRMED`, `INVOICED`, `DISPUTED`, or `SETTLED`"

    Design: Difficulty/boundary_precision_check/trigger_depth_equality_boundary
    """
    ctx = setup_active_per_push(client_name="Boundary Estates Eq",
                                trigger_depth_inches=2.0, per_push_rate_cents=45_000)
    set_clock("2026-12-11T07:00:00Z")
    event = setup_storm_event(window_start="2026-12-11T00:00:00Z",
                              window_end="2026-12-11T08:00:00Z",
                              reported_accumulation_inches=2.0)
    visit = setup_completed_visit(
        ctx, event, scheduled_start="2026-12-11T09:00:00Z",
        scheduled_end="2026-12-11T10:00:00Z",
        start_at="2026-12-11T09:05:00Z", complete_at="2026-12-11T10:00:00Z")
    verified = _verify_with_equal_readings(event["id"], "2026-12-11", 2.0)
    assert verified["verified_accumulation_inches"] == 2.0

    visit_after = validate_success(api.get_visit(visit["id"], DISPATCH), 200)
    assert visit_after["billing_status"] == "BILLABLE_CONFIRMED"
    assert visit_after["billable_amount_cents"] == 45_000

    contract = validate_success(api.get_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert contract["season_billable_push_count"] == 1


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / photo_accept_window_equality_boundary
# ---------------------------------------------------------------------------

def _setup_photo_window_scenario(api):
    """Photo-verified contract; visit with three AFTER photos; pA accepted while
    IN_PROGRESS so completion succeeds; visit completes at exactly 10:30."""
    ctx = setup_active_per_push(client_name="Photo Finish Inc",
                                trigger_depth_inches=1.0,
                                require_photo_verification=True)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    visit = schedule_visit(event["id"], ctx["contract_site"]["id"],
                           scheduled_start="2026-12-10T09:00:00Z",
                           scheduled_end="2026-12-10T11:00:00Z")
    set_clock("2026-12-10T09:05:00Z")
    get_success_data(api.start_visit(visit["id"], CREW))
    p_a = upload_photo(visit["id"], "AFTER", "s3://proof/vP-after-1.jpg")
    p_b = upload_photo(visit["id"], "AFTER", "s3://proof/vP-after-2.jpg")
    p_c = upload_photo(visit["id"], "AFTER", "s3://proof/vP-after-3.jpg")
    accept_photo(p_a["id"])
    set_clock("2026-12-10T10:30:00Z")
    completed = get_success_data(api.complete_visit(visit["id"], CREW))
    assert completed["execution_status"] == "COMPLETED"
    return ctx, visit, p_b, p_c


def test_photo_accept_at_exact_window_end_inclusive(api):
    """PRD §3.6: "Once the parent visit is `COMPLETED`, an `AFTER` photo remains acceptable only while the logical clock is no later than six hours after `completed_at`, inclusive — beyond that the accept attempt fails as `ERR_PHOTO_WINDOW_EXPIRED`."

    Design: Difficulty/boundary_precision_check/photo_accept_window_equality_boundary
    """
    _, visit, p_b, _ = _setup_photo_window_scenario(api)
    # completed at 10:30 -> 10:30 + 360 min == 16:30 exactly: inclusive, allowed.
    set_clock("2026-12-10T16:30:00Z")
    accepted = validate_success(api.accept_photo(p_b["id"], DISPATCH), 200)
    assert accepted["review_status"] == "ACCEPTED"


def test_photo_accept_one_minute_past_window_rejected(api):
    """PRD §3.6: "Once the parent visit is `COMPLETED`, an `AFTER` photo remains acceptable only while the logical clock is no later than six hours after `completed_at`, inclusive — beyond that the accept attempt fails as `ERR_PHOTO_WINDOW_EXPIRED`."

    Design: Difficulty/boundary_precision_check/photo_accept_window_equality_boundary
    """
    _, visit, _, p_c = _setup_photo_window_scenario(api)
    # 16:31 is one minute past completed_at + 360 min.
    set_clock("2026-12-10T16:31:00Z")
    validate_error(api.accept_photo(p_c["id"], DISPATCH),
                   ApiErrorId.ERR_PHOTO_WINDOW_EXPIRED)

    photos, _ = validate_paginated(api.list_visit_photos(visit["id"], DISPATCH))
    by_id = {p["id"]: p for p in photos}
    assert by_id[p_c["id"]]["review_status"] == "UPLOADED", (
        "a rejected accept leaves the photo untouched")


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / visit_dual_state_dimensions_independent_then_coupled
# ---------------------------------------------------------------------------

def test_visit_execution_and_billing_dimensions_independent_until_verification(api):
    """PRD §3.7: "Every visit carries a billing lifecycle independent of its execution until the coupling rules fire."
    PRD §3.5: "When the storm event is already `VERIFIED` or `CLOSED`, billing evaluates immediately at completion — the visit moves from `PENDING` to `BILLABLE_CONFIRMED` or `NON_BILLABLE`"
    PRD §3.3: "At the first level, every completed visit under the event re-evaluates its billing, moving from `PENDING` to `BILLABLE_CONFIRMED` or `NON_BILLABLE` per the trigger rule of §3.7."

    Design: Difficulty/non_linear_state_machine/visit_dual_state_dimensions_independent_then_coupled
    """
    ctx = setup_active_per_push(client_name="Greenfield Malls",
                                trigger_depth_inches=1.0, per_push_rate_cents=45_000)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    visit = schedule_visit(event["id"], ctx["contract_site"]["id"])
    assert visit["execution_status"] == "SCHEDULED"
    assert visit["billing_status"] == "PENDING"

    set_clock("2026-12-10T09:05:00Z")
    started = validate_success(api.start_visit(visit["id"], CREW), 200)
    assert started["execution_status"] == "IN_PROGRESS"
    assert started["billing_status"] == "PENDING"

    set_clock("2026-12-10T10:00:00Z")
    completed = validate_success(api.complete_visit(visit["id"], CREW), 200)
    assert completed["execution_status"] == "COMPLETED"
    assert completed["billing_status"] == "PENDING", (
        "event still REPORTED -> execution completion does not force billing")

    post_observation(event["id"], "NOAA", "2026-12-10T07:30:00Z", 2.0)
    post_observation(event["id"], "DTN", "2026-12-10T08:00:00Z", 2.1)
    verify_event(event["id"])

    after = validate_success(api.get_visit(visit["id"], DISPATCH), 200)
    assert after["execution_status"] == "COMPLETED"
    assert after["billing_status"] == "BILLABLE_CONFIRMED"
    assert after["billable_amount_cents"] == 45_000


def test_visit_void_couples_billing_to_non_billable_with_compensation(api):
    """PRD §3.5: "voiding forces billing to `NON_BILLABLE`, voids every `RECORDED` material row of the visit so `material_cost_cents` returns to zero, recomputes the contract's `season_billable_push_count`, `season_billable_minutes`, and `unbilled_billable_cents`"
    PRD §3.7: "`season_billable_push_count` counts the contract's visits with billing in `BILLABLE_CONFIRMED`, `INVOICED`, `DISPUTED`, or `SETTLED`"

    Design: Difficulty/non_linear_state_machine/visit_dual_state_dimensions_independent_then_coupled
    """
    ctx = setup_active_per_push(client_name="Greenfield Malls Void",
                                trigger_depth_inches=1.0, per_push_rate_cents=45_000)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    visit, _ = setup_billable_visit(ctx, event, [
        ("NOAA", "2026-12-10T07:30:00Z", 2.0),
        ("DTN", "2026-12-10T08:00:00Z", 2.1),
    ])
    assert visit["billing_status"] == "BILLABLE_CONFIRMED"

    voided = validate_success(api.void_visit(visit["id"], DISPATCH), 200)
    assert voided["execution_status"] == "VOIDED"
    assert voided["billing_status"] == "NON_BILLABLE"

    contract = validate_success(api.get_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert contract["season_billable_push_count"] == 0


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / push_count_conserved_by_complete_then_void
# ---------------------------------------------------------------------------

def test_verified_push_accumulates_count_and_unbilled_cents(api):
    """PRD §3.7: "`season_billable_push_count` counts the contract's visits with billing in `BILLABLE_CONFIRMED`, `INVOICED`, `DISPUTED`, or `SETTLED`"
    PRD §3.7: "`unbilled_billable_cents` sums `billable_amount_cents` plus `material_cost_cents` over visits sitting in `BILLABLE_CONFIRMED`"

    Design: Difficulty/compensating_invariant/push_count_conserved_by_complete_then_void
    """
    ctx = setup_active_per_push(client_name="Conserve Corp",
                                trigger_depth_inches=1.0, per_push_rate_cents=45_000)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    visit, _ = setup_billable_visit(ctx, event, [
        ("NOAA", "2026-12-10T07:30:00Z", 2.0),
        ("DTN", "2026-12-10T08:00:00Z", 2.1),
    ])
    assert visit["billing_status"] == "BILLABLE_CONFIRMED"

    contract = validate_success(api.get_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert contract["season_billable_push_count"] == 1
    assert contract["unbilled_billable_cents"] == 45_000


def test_complete_then_void_restores_push_accumulators_to_zero(api):
    """PRD §3.5: "voiding forces billing to `NON_BILLABLE`, voids every `RECORDED` material row of the visit so `material_cost_cents` returns to zero, recomputes the contract's `season_billable_push_count`, `season_billable_minutes`, and `unbilled_billable_cents`"
    PRD §2.9: "recomputed immediately whenever an underlying fact changes; consistency is immediate, never deferred."

    Design: Difficulty/compensating_invariant/push_count_conserved_by_complete_then_void
    """
    ctx = setup_active_per_push(client_name="Conserve Corp Void",
                                trigger_depth_inches=1.0, per_push_rate_cents=45_000)
    set_clock("2026-12-10T07:00:00Z")
    event = setup_storm_event()
    visit, _ = setup_billable_visit(ctx, event, [
        ("NOAA", "2026-12-10T07:30:00Z", 2.0),
        ("DTN", "2026-12-10T08:00:00Z", 2.1),
    ])

    get_success_data(api.void_visit(visit["id"], DISPATCH))

    contract = validate_success(api.get_contract(ctx["contract"]["id"], DISPATCH), 200)
    assert contract["season_billable_push_count"] == 0, (
        "compensating void returns the accumulator to its pre-action value")
    assert contract["unbilled_billable_cents"] == 0
