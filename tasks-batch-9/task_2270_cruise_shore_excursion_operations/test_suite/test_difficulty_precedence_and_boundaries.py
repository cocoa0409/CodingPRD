"""Which objection speaks when a request breaks several rules at once, and how the
service behaves exactly on the frontier of a band, a rounding step and a zero denominator.
"""

from datetime import datetime

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant so instants compare by value, not by spelling."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ==========================================================================
# Authority (priority 2) versus existence (priority 7)
# ==========================================================================

def test_desk_reading_an_unknown_operator_is_refused_as_unauthorized(api):
    """PRD §2.1: "Once identity is resolved, the declared role must appear in the operation's authorised role list; if it does not, the request is refused with `ERR_UNAUTHORIZED` (403), and that refusal precedes any existence check so that a wrong-role caller cannot use 404s to probe which identifiers exist."

    Design: Difficulty/priority_pair_validation_conflict/operator_read_by_desk_role_returns_unauthorized_and_not_the_operator_not_found
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")

    resp = api.get_operator(NON_EXISTENT_UUID, TEST_USERS["desk_headers"])

    error = validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_OPERATOR_NOT_FOUND.value


def test_desk_reading_a_stored_operator_is_refused_with_the_same_code(api):
    """PRD §2.1: "Once identity is resolved, the declared role must appear in the operation's authorised role list; if it does not, the request is refused with `ERR_UNAUTHORIZED` (403), and that refusal precedes any existence check so that a wrong-role caller cannot use 404s to probe which identifiers exist."

    PRD §2.8: "When a request violates several rules at once, exactly one error is returned: the one belonging to the lowest-numbered rule in the ladder below."

    Design: Difficulty/priority_pair_validation_conflict/operator_read_by_desk_role_returns_unauthorized_and_not_the_operator_not_found
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    port = fixtures.create_port(api)
    operator = fixtures.create_operator(api, port["id"])

    resp = api.get_operator(operator["id"], TEST_USERS["desk_headers"])

    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_authorized_role_reading_an_unknown_operator_gets_the_operator_not_found(api):
    """PRD §2.8: "7: every identifier in the URL path resolves to a stored row, else that entity's own 404 code."

    PRD §2.9: "Each entity answers with its own code, all of them 404: `ERR_PORT_NOT_FOUND`, `ERR_MEETING_POINT_NOT_FOUND`, `ERR_PORT_CALL_NOT_FOUND`, `ERR_TENDER_WAVE_NOT_FOUND`, `ERR_OPERATOR_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_EXCURSION_NOT_FOUND`, `ERR_DEPARTURE_NOT_FOUND`, `ERR_GUEST_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND` and `ERR_STATEMENT_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/operator_read_by_desk_role_returns_unauthorized_and_not_the_operator_not_found
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")

    resp = api.get_operator(NON_EXISTENT_UUID, TEST_USERS["manager_headers"])

    validate_error(resp, ApiErrorId.ERR_OPERATOR_NOT_FOUND.value, 404)


# ==========================================================================
# Request shape (priority 6) versus body-reference existence (priority 8)
# ==========================================================================

def test_bad_price_tier_enum_beats_the_missing_operator_reference(api):
    """PRD §2.8: "Shape validation deliberately runs before existence, because a missing or mistyped identifier cannot be looked up: a request that both omits a required field and names a nonexistent path identifier returns `ERR_VALIDATION`, not a 404."

    PRD §3.3: "Commercially, `base_price_cents` is the per-guest list price before any adjustment and must be at least 100, and `price_tier` is one of `VALUE`, `STANDARD`, `PREMIUM` or `SIGNATURE`."

    Design: Difficulty/priority_pair_validation_conflict/excursion_create_with_invalid_price_tier_enum_rejects_before_the_missing_operator_lookup
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    port = fixtures.create_port(api)

    payload = factories.create_excursion_payload(
        port["id"], NON_EXISTENT_UUID, title="Ghost Tour", price_tier="DIAMOND",
    )
    resp = api.create_excursion(payload, TEST_USERS["manager_headers"])

    error = validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)
    assert error["error_id"] != ApiErrorId.ERR_OPERATOR_NOT_FOUND.value

    listed = api.list_excursions(TEST_USERS["manager_headers"])
    _, meta = validate_paginated(listed)
    assert meta["total_count"] == 0


def test_a_well_shaped_body_naming_a_missing_operator_gets_the_404(api):
    """PRD §2.8: "8: every foreign key in the request body resolves to a stored row, else the referenced entity's own 404 code."

    PRD §2.9: "Body foreign keys are resolved after the whole path, in the order the fields are declared for that operation."

    Design: Difficulty/priority_pair_validation_conflict/excursion_create_with_invalid_price_tier_enum_rejects_before_the_missing_operator_lookup
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    port = fixtures.create_port(api)

    payload = factories.create_excursion_payload(
        port["id"], NON_EXISTENT_UUID, title="Ghost Tour", price_tier="PREMIUM",
    )
    resp = api.create_excursion(payload, TEST_USERS["manager_headers"])

    validate_error(resp, ApiErrorId.ERR_OPERATOR_NOT_FOUND.value, 404)


# ==========================================================================
# Stale read (priority 12) versus departure state (priority 18)
# ==========================================================================

def test_stale_departure_version_beats_the_cancelled_departure_state(api):
    """PRD §2.7: "If that value does not equal the departure's current `version`, the create is rejected with `ERR_STALE_DEPARTURE_VERSION` (412)."

    PRD §2.8: "Placing the stale-version check above every state and business rule means a caller holding a stale read is told to re-read, rather than being told why the write was otherwise unacceptable."

    Design: Difficulty/priority_pair_validation_conflict/booking_create_on_a_cancelled_departure_with_a_stale_version_returns_the_stale_version_error
    """
    world = fixtures.setup_selling_departure(api, clock="2026-08-01T00:00:00Z")
    guest = fixtures.create_guest(
        api, voyage_code=world.port_call["voyage_code"], loyalty_tier="GOLD",
    )
    stale_version = fixtures.get_departure_version(api, world.departure["id"])

    cancelled = fixtures.cancel_departure(
        api, world.departure["id"], "WEATHER", note="Storm swell.",
    )
    assert cancelled["status"] == "CANCELLED_WEATHER"
    assert cancelled["version"] > stale_version

    resp = api.create_booking(
        factories.create_booking_payload(
            world.departure["id"], guest["id"], stale_version,
            party_size=2, channel="PRE_CRUISE", language_choice="EN",
        ),
        TEST_USERS["desk_headers"],
    )

    error = validate_error(resp, ApiErrorId.ERR_STALE_DEPARTURE_VERSION.value, 412)
    assert error["error_id"] != ApiErrorId.ERR_DEPARTURE_NOT_SELLING.value

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["precruise_sold_seats"] == 0
    _, meta = validate_paginated(api.list_bookings(TEST_USERS["desk_headers"]))
    assert meta["total_count"] == 0


def test_a_current_version_on_a_cancelled_departure_reports_the_state_instead(api):
    """PRD §2.8: "18: a new booking names a departure whose `status` is `SELLING`, else `ERR_DEPARTURE_NOT_SELLING`; the ticketing action additionally accepts a `CLOSED` departure so guests booked before the cutoff can still be ticketed."

    Design: Difficulty/priority_pair_validation_conflict/booking_create_on_a_cancelled_departure_with_a_stale_version_returns_the_stale_version_error
    """
    world = fixtures.setup_selling_departure(api, clock="2026-08-01T00:00:00Z")
    guest = fixtures.create_guest(
        api, voyage_code=world.port_call["voyage_code"], loyalty_tier="GOLD",
    )
    fixtures.cancel_departure(api, world.departure["id"], "WEATHER", note="Storm swell.")
    current_version = fixtures.get_departure_version(api, world.departure["id"])

    resp = api.create_booking(
        factories.create_booking_payload(
            world.departure["id"], guest["id"], current_version,
            party_size=2, channel="PRE_CRUISE", language_choice="EN",
        ),
        TEST_USERS["desk_headers"],
    )

    validate_error(resp, ApiErrorId.ERR_DEPARTURE_NOT_SELLING.value, 422)


# ==========================================================================
# Guest safety (priority 29) versus seat arithmetic (priority 47)
# ==========================================================================

def _sold_out_precruise_world(api):
    """A SELLING departure of a min_age 18 excursion whose whole 4-seat pre-cruise
    bucket is already taken by one adult party."""
    world = fixtures.setup_selling_departure(
        api,
        clock="2026-08-01T00:00:00Z",
        departure={"total_capacity": 4, "precruise_allocation": 4,
                   "onboard_allocation": 0},
    )
    adult = fixtures.create_guest(
        api, voyage_code=world.port_call["voyage_code"], loyalty_tier="GOLD",
    )
    fixtures.create_booking(
        api, world.departure["id"], adult["id"], party_size=4, channel="PRE_CRUISE",
        language_choice="EN",
    )
    return world


def test_minor_guest_is_refused_for_age_before_the_exhausted_precruise_bucket(api):
    """PRD §3.5: "If it is below the excursion's `min_age`, or if the excursion declares a `max_age` and the age exceeds it, the booking is refused with `ERR_AGE_RESTRICTION`; both bounds are inclusive."

    PRD §2.8: "Priority 47 is the floor of the ladder on purpose: every safety, temporal and constraint objection is reported before the seat count is even consulted."

    Design: Difficulty/priority_pair_validation_conflict/minor_guest_booking_on_a_sold_out_precruise_bucket_reports_the_age_restriction_first
    """
    world = _sold_out_precruise_world(api)
    minor = fixtures.create_guest(
        api, full_name="Theo Reyes", birth_date="2009-06-15T00:00:00Z",
        voyage_code=world.port_call["voyage_code"], loyalty_tier="GOLD",
    )
    version = fixtures.get_departure_version(api, world.departure["id"])

    resp = api.create_booking(
        factories.create_booking_payload(
            world.departure["id"], minor["id"], version,
            party_size=1, channel="PRE_CRUISE", language_choice="EN",
        ),
        TEST_USERS["desk_headers"],
    )

    error = validate_error(resp, ApiErrorId.ERR_AGE_RESTRICTION.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_CHANNEL_ALLOCATION_EXHAUSTED.value

    departure = fixtures.get_departure(api, world.departure["id"])
    assertions.assert_field_values(
        departure, precruise_sold_seats=4, seats_available_total=0,
        effective_precruise_available=0,
    )


def test_an_eligible_adult_on_the_same_departure_hits_the_seat_objection(api):
    """PRD §3.5: "A booking is admitted only when its `party_size` is at most the effective available seats of its own `channel`; otherwise it is refused with `ERR_CHANNEL_ALLOCATION_EXHAUSTED`."

    PRD §2.8: "47: a booking's `party_size` fits inside the effective available seats of its own channel, else `ERR_CHANNEL_ALLOCATION_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/minor_guest_booking_on_a_sold_out_precruise_bucket_reports_the_age_restriction_first
    """
    world = _sold_out_precruise_world(api)
    second_adult = fixtures.create_guest(
        api, full_name="Iris Reyes", birth_date="1979-11-30T00:00:00Z",
        voyage_code=world.port_call["voyage_code"], loyalty_tier="GOLD",
    )
    version = fixtures.get_departure_version(api, world.departure["id"])

    resp = api.create_booking(
        factories.create_booking_payload(
            world.departure["id"], second_adult["id"], version,
            party_size=1, channel="PRE_CRUISE", language_choice="EN",
        ),
        TEST_USERS["desk_headers"],
    )

    validate_error(resp, ApiErrorId.ERR_CHANNEL_ALLOCATION_EXHAUSTED.value, 422)


# ==========================================================================
# The AMBER / RED frontier on the actual-basis slack
# ==========================================================================

def test_a_seventy_four_minute_delay_leaves_one_minute_of_slack_and_an_amber_band(api):
    """PRD §3.4: "So when a wave is assigned, the start is the later of `meeting_time_utc` and the wave's `window_end_utc` advanced by the call's `delay_minutes`; when no wave is assigned, the start is `meeting_time_utc` advanced by `delay_minutes`."

    PRD §3.4: "`projected_return_actual_utc` is that start advanced by the same ashore leg, and `slack_minutes_actual` is the minutes from it to `all_aboard_utc`, less `risk_buffer_minutes`."

    PRD §3.4: "Both slack figures are banded identically into `timing_risk_band_scheduled` and `timing_risk_band_actual`: a slack of 0 or fewer minutes is `RED`, a slack of 45 or fewer minutes but more than 0 is `AMBER`, and anything above 45 minutes is `GREEN`."

    Design: Difficulty/boundary_precision_check/timing_risk_amber_red_frontier_is_one_minute_wide
    """
    world = fixtures.setup_selling_departure(api, clock="2026-08-01T00:00:00Z",
                                             tender=True)

    port_call = fixtures.record_delay(api, world.port_call["id"], 74,
                                      reason_code="PILOT_UNAVAILABLE")

    assert port_call["delay_minutes"] == 74
    assert _instant(port_call["effective_arrival_utc"]) == _instant(
        "2026-09-15T09:14:00Z"
    )

    departure = fixtures.get_departure(api, world.departure["id"])
    assert _instant(departure["projected_return_actual_utc"]) == _instant(
        "2026-09-15T15:59:00Z"
    )
    assert departure["slack_minutes_actual"] == 1
    assert departure["timing_risk_band_actual"] == "AMBER"
    assert departure["timing_risk_band_actual"] != "RED"
    assert departure["status"] == "SELLING"


def test_one_more_minute_of_delay_takes_the_actual_slack_to_zero_and_red(api):
    """PRD §3.4: "Both slack figures are banded identically into `timing_risk_band_scheduled` and `timing_risk_band_actual`: a slack of 0 or fewer minutes is `RED`, a slack of 45 or fewer minutes but more than 0 is `AMBER`, and anything above 45 minutes is `GREEN`."

    PRD §3.1: "Every departure on the call has its actual-basis projection and `timing_risk_band_actual` recomputed on the spot, and the recomputation can cascade: each departure that is `SELLING` and whose `timing_risk_band_actual` has just become `RED` moves `SELLING → CLOSED`, and each of that departure's never-charged bookings — those still in `BOOKED` with `financial_status` `AUTHORIZED` — moves to `CANCELLED_BY_LINE` with `financial_status` `VOIDED`, an `AUTH_VOID` ledger entry of `amount_cents` 0 on the `LINE_CANCELLED_OPERATIONAL` `basis`, and its seats returned to its own channel bucket."

    Design: Difficulty/boundary_precision_check/timing_risk_amber_red_frontier_is_one_minute_wide
    """
    world = fixtures.setup_selling_departure(api, clock="2026-08-01T00:00:00Z",
                                             tender=True)

    port_call = fixtures.record_delay(api, world.port_call["id"], 75,
                                      reason_code="PILOT_UNAVAILABLE")
    assert port_call["delay_minutes"] == 75

    departure = fixtures.get_departure(api, world.departure["id"])
    assert _instant(departure["projected_return_actual_utc"]) == _instant(
        "2026-09-15T16:00:00Z"
    )
    assert departure["slack_minutes_actual"] == 0
    assert departure["timing_risk_band_actual"] == "RED"
    assert departure["status"] == "CLOSED"


def test_delay_reported_in_two_instalments_accumulates_to_the_same_amber_frontier(api):
    """PRD §3.1: "Each report adds to `delay_minutes`, which may never be negative, and `effective_arrival_utc` is recomputed as `arrival_utc` shifted later by `delay_minutes`."

    PRD §3.4: "Both slack figures are banded identically into `timing_risk_band_scheduled` and `timing_risk_band_actual`: a slack of 0 or fewer minutes is `RED`, a slack of 45 or fewer minutes but more than 0 is `AMBER`, and anything above 45 minutes is `GREEN`."

    Design: Difficulty/boundary_precision_check/timing_risk_amber_red_frontier_is_one_minute_wide
    """
    world = fixtures.setup_selling_departure(api, clock="2026-08-01T00:00:00Z",
                                             tender=True)

    fixtures.record_delay(api, world.port_call["id"], 34)
    port_call = fixtures.record_delay(api, world.port_call["id"], 40)

    assert port_call["delay_minutes"] == 74
    assert _instant(port_call["effective_arrival_utc"]) == _instant(
        "2026-09-15T09:14:00Z"
    )

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["slack_minutes_actual"] == 1
    assert departure["timing_risk_band_actual"] == "AMBER"


# ==========================================================================
# The safety-score floor: 59.6 rounds up to exactly 60
# ==========================================================================

def _operator_with_two_clean_audits(api, first_raw, second_raw):
    """An operator carrying two clean audits — the older one first — left in DRAFT."""
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    port = fixtures.create_port(api)
    operator = fixtures.create_operator(api, port["id"])
    fixtures.record_safety_audit(
        api, operator["id"], auditor_user_id="u_aud_1", audit_type="INITIAL",
        conducted_on="2026-06-01T00:00:00Z", raw_score=first_raw,
        critical_finding_count=0,
    )
    fixtures.record_safety_audit(
        api, operator["id"], auditor_user_id="u_aud_1", audit_type="ANNUAL",
        conducted_on="2026-07-01T00:00:00Z", raw_score=second_raw,
        critical_finding_count=0,
    )
    return operator


def test_a_weighted_fifty_nine_point_six_rounds_to_sixty_and_the_operator_stays_approved(api):
    """PRD §3.2: "Assign base weights of 0.5, 0.3 and 0.2 to the audits in that order, truncated to however many audits are in the window, then divide each base weight by the sum of the base weights actually used, so that with three audits the weights stay 0.5, 0.3 and 0.2, with two they become 0.625 and 0.375, and with one it becomes 1.0."

    PRD §3.2: "From that average subtract 8 points for every critical finding, counting `critical_finding_count` summed across the audits in the window only, and subtract a further 5 points for every liability claim against this operator whose `status` is `ADJUDICATED_UPHELD` or `SETTLED`."

    PRD §3.2: "All of that arithmetic is exact; the result is then rounded half up to a whole number exactly once and clamped into the range 0 to 100, and the clamped figure is `safety_score`."

    PRD §3.2: "The system suspends automatically when a recomputed `safety_score` lands below 60 — whether the recomputation followed a new safety audit or an upheld liability claim."

    Design: Difficulty/boundary_precision_check/safety_score_rounds_up_to_exactly_sixty_and_leaves_the_operator_approved
    """
    operator = _operator_with_two_clean_audits(api, 64, 66)
    fixtures.vetting_action(api, operator["id"], "SUBMIT")
    approved = fixtures.vetting_action(api, operator["id"], "APPROVE")
    assert approved["safety_score"] == 65
    assert approved["vetting_status"] == "APPROVED"

    fixtures.record_safety_audit(
        api, operator["id"], auditor_user_id="u_aud_3",
        audit_type="INCIDENT_TRIGGERED", conducted_on="2026-07-20T00:00:00Z",
        raw_score=70, critical_finding_count=1,
    )

    rescored = fixtures.get_operator(api, operator["id"])
    assert rescored["safety_score"] == 60
    assert rescored["safety_score"] != 59
    assert rescored["vetting_status"] == "APPROVED"


def test_a_weighted_fifty_nine_point_one_rounds_to_fifty_nine_and_suspends_the_operator(api):
    """PRD §3.2: "All of that arithmetic is exact; the result is then rounded half up to a whole number exactly once and clamped into the range 0 to 100, and the clamped figure is `safety_score`."

    PRD §3.2: "The system suspends automatically when a recomputed `safety_score` lands below 60 — whether the recomputation followed a new safety audit or an upheld liability claim."

    Design: Difficulty/boundary_precision_check/safety_score_rounds_up_to_exactly_sixty_and_leaves_the_operator_approved
    """
    operator = _operator_with_two_clean_audits(api, 64, 66)
    fixtures.vetting_action(api, operator["id"], "SUBMIT")
    fixtures.vetting_action(api, operator["id"], "APPROVE")

    fixtures.record_safety_audit(
        api, operator["id"], auditor_user_id="u_aud_3",
        audit_type="INCIDENT_TRIGGERED", conducted_on="2026-07-20T00:00:00Z",
        raw_score=69, critical_finding_count=1,
    )

    rescored = fixtures.get_operator(api, operator["id"])
    assert rescored["safety_score"] == 59
    assert rescored["vetting_status"] == "SUSPENDED"


def test_a_score_that_rounds_up_to_exactly_sixty_clears_the_approval_floor(api):
    """PRD §2.8: "26: `safety_score` is at least 60 before approval or reinstatement, else `ERR_SAFETY_SCORE_BELOW_FLOOR` — exactly 60 satisfies the floor and 59 does not."

    PRD §3.2: "All of that arithmetic is exact; the result is then rounded half up to a whole number exactly once and clamped into the range 0 to 100, and the clamped figure is `safety_score`."

    Design: Difficulty/boundary_precision_check/safety_score_rounds_up_to_exactly_sixty_and_leaves_the_operator_approved
    """
    operator = _operator_with_two_clean_audits(api, 57, 61)
    submitted = fixtures.vetting_action(api, operator["id"], "SUBMIT")
    assert submitted["safety_score"] == 60

    approved = fixtures.vetting_action(api, operator["id"], "APPROVE")

    assert approved["vetting_status"] == "APPROVED"
    assert approved["safety_score"] == 60


def test_a_score_that_rounds_down_to_fifty_nine_is_refused_at_the_approval_floor(api):
    """PRD §2.8: "26: `safety_score` is at least 60 before approval or reinstatement, else `ERR_SAFETY_SCORE_BELOW_FLOOR` — exactly 60 satisfies the floor and 59 does not."

    PRD §3.2: "A score of exactly 60 passes."

    Design: Difficulty/boundary_precision_check/safety_score_rounds_up_to_exactly_sixty_and_leaves_the_operator_approved
    """
    operator = _operator_with_two_clean_audits(api, 56, 61)
    submitted = fixtures.vetting_action(api, operator["id"], "SUBMIT")
    assert submitted["safety_score"] == 59

    resp = api.vetting_action(
        operator["id"], {"action": "APPROVE"}, TEST_USERS["vetting_officer_headers"],
    )

    validate_error(resp, ApiErrorId.ERR_SAFETY_SCORE_BELOW_FLOOR.value, 422)
    still_submitted = fixtures.get_operator(api, operator["id"])
    assert still_submitted["vetting_status"] == "SUBMITTED"
    assert still_submitted["safety_score"] == 59


# ==========================================================================
# The service fee at an exact half cent
# ==========================================================================

def test_service_fee_on_a_raw_four_hundred_and_twenty_seven_point_five_rounds_to_four_hundred_and_twenty_eight(api):
    """PRD §2.6: "Applying a rate means multiplying the amount by the basis points, dividing by ten thousand, and rounding the result half up to a whole number of cents — a value whose fractional part is exactly one half rounds away from zero, so a raw 427.5 becomes 428 and never 427."

    PRD §3.5: "`service_fee_cents` is the smaller of 1500 cents and 300 basis points of `quoted_total_cents` rounded half up; it is retained by the line and is never commissionable."

    PRD §3.5: "`charge_total_cents` is `quoted_total_cents` plus `service_fee_cents`, and it is the amount authorised at booking and captured at ticketing."

    PRD §3.5: "A `PRE_CRUISE` booking earns a reduction of 500 basis points only when the booking is made at least a full week ahead: take the number of minutes from the logical clock to the departure's `meeting_time_utc`, divide by 1440 and discard the remainder to get whole days to the meeting, and apply the reduction only when that whole-day figure is 7 or more; below 7 the pre-cruise adjustment is zero."

    Design: Difficulty/boundary_precision_check/booking_service_fee_rounds_half_up_at_an_exact_half_cent
    """
    world = fixtures.setup_selling_departure(
        api,
        clock="2026-09-05T09:00:00Z",
        excursion={"title": "Downtown Walking Tour", "base_price_cents": 15000,
                   "price_tier": "STANDARD", "languages": ["EN"]},
    )
    guest = fixtures.create_guest(
        api, full_name="Nils Haugen", birth_date="1975-03-11T00:00:00Z",
        voyage_code=world.port_call["voyage_code"],
    )

    booking = fixtures.create_booking(
        api, world.departure["id"], guest["id"], party_size=1, channel="PRE_CRUISE",
        language_choice="EN",
    )

    assertions.assert_field_values(
        booking, party_size=1, age_at_meeting=51, per_guest_price_cents=14250,
        quoted_total_cents=14250, service_fee_cents=428, charge_total_cents=14678,
    )
    assert booking["service_fee_cents"] != 427
    assertions.assert_charge_total_is_quote_plus_fee(booking)
    assertions.assert_quote_is_per_guest_times_party(booking)


def test_service_fee_on_a_raw_four_hundred_and_twenty_four_point_five_rounds_away_from_zero(api):
    """PRD §2.6: "Applying a rate means multiplying the amount by the basis points, dividing by ten thousand, and rounding the result half up to a whole number of cents — a value whose fractional part is exactly one half rounds away from zero, so a raw 427.5 becomes 428 and never 427."

    PRD §3.5: "The channel price is the list price multiplied by ten thousand plus the adjustment in basis points, divided by ten thousand, rounded half up."

    PRD §3.5: "`service_fee_cents` is the smaller of 1500 cents and 300 basis points of `quoted_total_cents` rounded half up; it is retained by the line and is never commissionable."

    Design: Difficulty/boundary_precision_check/booking_service_fee_rounds_half_up_at_an_exact_half_cent
    """
    world = fixtures.setup_selling_departure(
        api,
        clock="2026-09-05T09:00:00Z",
        excursion={"title": "Harbour Stroll", "base_price_cents": 14895,
                   "price_tier": "STANDARD", "languages": ["EN"]},
    )
    guest = fixtures.create_guest(
        api, full_name="Nils Haugen", birth_date="1975-03-11T00:00:00Z",
        voyage_code=world.port_call["voyage_code"],
    )

    booking = fixtures.create_booking(
        api, world.departure["id"], guest["id"], party_size=1, channel="PRE_CRUISE",
        language_choice="EN",
    )

    assertions.assert_field_values(
        booking, per_guest_price_cents=14150, quoted_total_cents=14150,
        service_fee_cents=425, charge_total_cents=14575,
    )
    assert booking["service_fee_cents"] != 424
    assertions.assert_charge_total_is_quote_plus_fee(booking)


# ==========================================================================
# The zero denominator in the per-port revenue report
# ==========================================================================

def test_revenue_report_for_a_port_that_never_traded_reports_zero_ratios(api):
    """PRD §3.9: "Both are guarded: when `booking_count` is zero both ratios report 0, never an error and never a null, so a port that has never traded still reports cleanly with every money figure at 0."

    PRD §3.9: "The report echoes `port_id` and the `voyage_code` filter, reports `port_call_count` as the number of calls in scope, and `booking_count` as the count of every booking ever taken in scope — nothing is excluded from that denominator."

    PRD §3.9: "Three counts complete the picture: `cancelled_booking_count` over bookings whose `fulfillment_status` is `CANCELLED_BY_GUEST` or `CANCELLED_BY_LINE`, `completed_booking_count` over those in `COMPLETED`, and `no_show_booking_count` over those in `NO_SHOW`."

    PRD §3.9: "`net_line_revenue_cents` is then `gross_ticket_cents` plus `service_fee_cents`, less `refunds_cents`, less `goodwill_cents`, less `operator_payable_cents`; it may legitimately be negative when the line refunded everything and paid goodwill on top."

    Design: Difficulty/boundary_precision_check/revenue_report_for_a_port_with_no_bookings_returns_zero_ratios_and_not_a_division_error
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    port = fixtures.create_port(api, port_code="PGO", name="Progreso")

    resp = api.get_port_revenue_report(port["id"], TEST_USERS["finance_headers"])

    validate_success(resp, 200)
    report = get_success_data(resp)
    assertions.assert_field_values(
        report,
        port_id=port["id"],
        port_call_count=0,
        booking_count=0,
        completed_booking_count=0,
        cancelled_booking_count=0,
        no_show_booking_count=0,
        gross_ticket_cents=0,
        service_fee_cents=0,
        refunds_cents=0,
        goodwill_cents=0,
        line_commission_cents=0,
        operator_payable_cents=0,
        net_line_revenue_cents=0,
        cancellation_rate_bps=0,
        no_show_rate_bps=0,
    )


def test_revenue_report_for_a_call_with_no_bookings_still_reports_zero_ratios(api):
    """PRD §3.9: "Both are guarded: when `booking_count` is zero both ratios report 0, never an error and never a null, so a port that has never traded still reports cleanly with every money figure at 0."

    PRD §3.9: "The scope is every port call at the named port, filtered by that voyage code when supplied, and every booking on those calls' departures."

    PRD §3.9: "From them come two ratios: `cancellation_rate_bps` is the cancelled count multiplied by ten thousand, divided by `booking_count`, rounded half up, and `no_show_rate_bps` is the same computation on the no-show count."

    Design: Difficulty/boundary_precision_check/revenue_report_for_a_port_with_no_bookings_returns_zero_ratios_and_not_a_division_error
    """
    world = fixtures.setup_selling_departure(api, clock="2026-08-01T00:00:00Z")

    resp = api.get_port_revenue_report(world.port["id"], TEST_USERS["finance_headers"])

    validate_success(resp, 200)
    report = get_success_data(resp)
    assertions.assert_field_values(
        report,
        port_id=world.port["id"],
        port_call_count=1,
        booking_count=0,
        completed_booking_count=0,
        cancelled_booking_count=0,
        no_show_booking_count=0,
        gross_ticket_cents=0,
        service_fee_cents=0,
        refunds_cents=0,
        goodwill_cents=0,
        line_commission_cents=0,
        operator_payable_cents=0,
        net_line_revenue_cents=0,
        cancellation_rate_bps=0,
        no_show_rate_bps=0,
    )
