"""Timing results, packet pickup, finishing, and cross-entity state dependencies.

Covers difficulty rules cross_entity_state_dependency and
priority_pair_validation_conflict (state vs temporal), and corner instances under
sections calculations, state_machines, validations, and endpoints.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_participant_headers, assert_result_record,
)
from test_helpers import fixtures as fx
from test_helpers.factories import registration_payload, result_payload, pledge_payload

RD = TEST_USERS["race_director_headers"]
TO = TEST_USERS["timing_official_headers"]
PS = TEST_USERS["packet_staff_headers"]


# ---------------------------------------------------------------------------
# Timing computation (corner: calculations)
# ---------------------------------------------------------------------------
def test_timing_result_gun_chip_pace_computed(api):
    """PRD §3.8: "the gun time, used for official placement, is the finish clock minus
    the gun-start clock; the chip time, the personal net time, is the finish clock
    minus the mat-crossing clock. These populate `gun_time_seconds` and
    `chip_time_seconds`. The pace, stored in `pace_seconds_per_km`, is the chip time
    divided by the distance's `distance_km`, rounded half-up to a whole number of
    seconds."

    Design: Corner/calculations/timing_result_gun_chip_pace_computed_correctly
    """
    # 5.0km, gun_start 0, mat_cross 130, finish 12130:
    # gun_time 12130, chip_time 12000, pace round_half_up(12000/5.0)=2400.
    event, distance, wave, participant, reg, bib = fx.setup_results_posted_with_bib(capacity_total=50)
    resp = api.create_result(
        result_payload(reg["id"], distance["id"], 0, 130, 12130), TO)
    res = validate_success(resp, expected_status=201)
    assert_result_record(res)
    assert res["gun_time_seconds"] == 12130, f"gun_time expected 12130, got {res['gun_time_seconds']}"
    assert res["chip_time_seconds"] == 12000, f"chip_time expected 12000, got {res['chip_time_seconds']}"
    assert res["pace_seconds_per_km"] == 2400, f"pace expected 2400, got {res['pace_seconds_per_km']}"


def test_result_invalid_timing_rejected(api):
    """PRD §3.8: "The clocks must be well-ordered — the mat crossing at or after the
    gun start, and the finish strictly after the mat crossing — and any other ordering
    is rejected with `ERR_INVALID_TIMING`."

    Design: Corner/validations/result_invalid_timing_rejected
    """
    event, distance, wave, participant, reg, bib = fx.setup_results_posted_with_bib(capacity_total=50)
    # finish (150) <= mat_cross (200) violates well-ordering.
    resp = api.create_result(
        result_payload(reg["id"], distance["id"], 0, 200, 150), TO)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIMING.value)


def test_result_disqualify_from_official_branch(api):
    """PRD §3.8: "A result in either `PROVISIONAL` or `OFFICIAL` may instead be
    disqualified to terminal `DQ` on protest, which excludes it from rankings and
    prevents the linked registration from being marked finished."

    Design: Corner/state_machines/result_disqualify_from_official_branch
    """
    event, distance, wave, participant, reg, bib = fx.setup_results_posted_with_bib(capacity_total=50)
    res = fx.post_result(reg, distance)
    validate_success(api.finalize_result(res["id"], TO))  # PROVISIONAL -> OFFICIAL
    resp = api.disqualify_result(res["id"], TO)            # OFFICIAL -> DQ
    dq = validate_success(resp)
    assert dq["status"] == "DQ", f"OFFICIAL result must be disqualifiable to DQ, got {dq['status']}"


# ---------------------------------------------------------------------------
# Cross-entity state dependency (difficulty: cross_entity_state_dependency)
# ---------------------------------------------------------------------------
def test_confirm_payment_blocked_after_event_closed(api):
    """PRD §3.3: "The owning event must be `OPEN`".
    PRD §3.1: "The director can later move an `OPEN` event to `CLOSED`, which rejects
    any new registration creation with `ERR_REGISTRATION_CLOSED`".

    Design: Difficulty/cross_entity_state_dependency/registration_confirm_requires_event_open
    """
    event, distance, wave = fx.setup_open_event(capacity_total=50)
    participant = fx.create_participant()
    headers = make_participant_headers(participant["id"])
    reg = fx.create_registration(event, distance, wave, participant)
    dv = fx.distance_version(distance["id"], headers)
    fx.get_event_close(event["id"])  # OPEN -> CLOSED
    resp = api.confirm_payment(reg["id"], {"expected_distance_version": dv}, headers)
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_CLOSED.value)
    assert fx.get_registration_data(reg["id"])["status"] == "PENDING_PAYMENT"


def test_confirm_payment_succeeds_while_event_open(api):
    """PRD §3.3: "The owning event must be `OPEN`, and the request must carry
    `expected_distance_version` matching the distance's current `version`".
    PRD §3.3: "If the distance has room ... the registration advances from
    `PENDING_PAYMENT` to `CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/registration_confirm_requires_event_open
    """
    # The complementary direction of the Registration->Event dependency: while the
    # event is OPEN the same confirm that fails after CLOSED here succeeds.
    event, distance, wave = fx.setup_open_event(capacity_total=50)
    participant = fx.create_participant()
    headers = make_participant_headers(participant["id"])
    reg = fx.create_registration(event, distance, wave, participant)
    dv = fx.distance_version(distance["id"], headers)
    resp = api.confirm_payment(reg["id"], {"expected_distance_version": dv}, headers)
    confirmed = validate_success(resp)
    assert confirmed["status"] == "CONFIRMED", \
        f"confirm while event OPEN must reach CONFIRMED, got {confirmed['status']}"


def test_finish_requires_official_result(api):
    """PRD §3.8: "a timing official marks a bib-assigned registration as finished,
    advancing it from `BIB_ASSIGNED` to terminal `FINISHED`; this is permitted only
    when the registration is `BIB_ASSIGNED`, the owning event is `CLOSED` or
    `RESULTS_POSTED`, and an `OFFICIAL` result record exists for the registration."

    Design: Difficulty/cross_entity_state_dependency/registration_finish_requires_official_result
    """
    # BIB_ASSIGNED registration, event RESULTS_POSTED, only a PROVISIONAL result.
    event, distance, wave, participant, reg, bib = fx.setup_results_posted_with_bib(capacity_total=50)
    fx.post_result(reg, distance)  # PROVISIONAL, not finalized
    resp = api.finish_registration(reg["id"], TO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert fx.get_registration_data(reg["id"])["status"] == "BIB_ASSIGNED"


def test_finish_succeeds_after_result_finalized_official(api):
    """PRD §3.8: "a timing official marks a bib-assigned registration as finished,
    advancing it from `BIB_ASSIGNED` to terminal `FINISHED`; this is permitted only
    when the registration is `BIB_ASSIGNED`, the owning event is `CLOSED` or
    `RESULTS_POSTED`, and an `OFFICIAL` result record exists for the registration."
    PRD §3.8: "A provisional result is finalized to `OFFICIAL` by a timing official,
    which is permitted only while the owning event is `RESULTS_POSTED` and the linked
    registration is `BIB_ASSIGNED`".

    Design: Difficulty/cross_entity_state_dependency/registration_finish_requires_official_result
    """
    # The complementary direction: once the ResultRecord is OFFICIAL, finish succeeds.
    event, distance, wave, participant, reg, bib = fx.setup_results_posted_with_bib(capacity_total=50)
    res = fx.post_result(reg, distance)
    validate_success(api.finalize_result(res["id"], TO))  # PROVISIONAL -> OFFICIAL
    resp = api.finish_registration(reg["id"], TO)
    finished = validate_success(resp)
    assert finished["status"] == "FINISHED", \
        f"finish must succeed once an OFFICIAL result exists, got {finished['status']}"


# ---------------------------------------------------------------------------
# Priority pair: state outranks temporal (difficulty: priority_pair_validation_conflict)
# ---------------------------------------------------------------------------
def test_state_error_outranks_temporal_on_confirm(api):
    """PRD §2.10: "then whether the target resource is in a valid state for the
    requested transition (`ERR_INVALID_STATE`). Only after all of these pass does the
    system evaluate the domain-specific business rules described throughout §3 —
    temporal windows ...".
    PRD §3.3: "Confirmation is only valid from `PENDING_PAYMENT`; attempting it from
    any other status is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_cancelled_reg_after_window_closed
    """
    # Registration CANCELLED (terminal), event later CLOSED, clock past the window.
    # The state check (ERR_INVALID_STATE) precedes the temporal window check.
    event, distance, wave = fx.setup_open_event(capacity_total=50)
    participant = fx.create_participant()
    headers = make_participant_headers(participant["id"])
    reg = fx.create_registration(event, distance, wave, participant)
    dv = fx.distance_version(distance["id"], headers)
    fx.api_cancel(reg, participant)            # CANCELLED
    fx.get_event_close(event["id"])            # OPEN -> CLOSED
    fx.set_clock("2026-07-02T00:00:00Z")       # past registration_closes_utc
    resp = api.confirm_payment(reg["id"], {"expected_distance_version": dv}, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_temporal_error_fires_when_state_valid_but_event_closed(api):
    """PRD §3.3: "The owning event must be `OPEN`".
    PRD §3.1: "The director can later move an `OPEN` event to `CLOSED`, which rejects
    any new registration creation with `ERR_REGISTRATION_CLOSED` but still allows
    existing confirmed registrations to be assigned bibs and to pick up packets".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_cancelled_reg_after_window_closed
    """
    # State is valid (PENDING_PAYMENT) but the event is CLOSED: with the state check
    # passing, the temporal window check is what fires — the lower-priority error of
    # the pair surfaces only in isolation.
    event, distance, wave = fx.setup_open_event(capacity_total=50)
    participant = fx.create_participant()
    headers = make_participant_headers(participant["id"])
    reg = fx.create_registration(event, distance, wave, participant)  # PENDING_PAYMENT
    dv = fx.distance_version(distance["id"], headers)
    fx.get_event_close(event["id"])  # OPEN -> CLOSED
    resp = api.confirm_payment(reg["id"], {"expected_distance_version": dv}, headers)
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_CLOSED.value)


# ---------------------------------------------------------------------------
# Registration window temporal bound (corner: validations)
# ---------------------------------------------------------------------------
def test_registration_create_rejected_at_close_instant(api):
    """PRD §3.2: "Creation is only permitted while the owning event is `OPEN` and the
    current clock falls within the registration window — at or after
    `registration_opens_utc` and strictly before `registration_closes_utc`, the upper
    bound being exclusive; outside that window the creation is rejected with
    `ERR_REGISTRATION_CLOSED`."

    Design: Corner/validations/registration_closed_after_window_close_instant
    """
    event, distance, wave = fx.setup_open_event(capacity_total=50)
    participant = fx.create_participant()
    headers = make_participant_headers(participant["id"])
    fx.set_clock("2026-07-01T00:00:00Z")  # exactly registration_closes_utc (exclusive)
    resp = api.create_registration(
        registration_payload(event["id"], distance["id"], wave["id"], participant["id"]),
        headers)
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_CLOSED.value)


# ---------------------------------------------------------------------------
# Relationship consistency (corner: validations)
# ---------------------------------------------------------------------------
def test_relation_mismatch_wave_not_in_distance(api):
    """PRD §2.9: "When a registration is created, the requested `wave_id` must belong
    to the requested `distance_id`, and that distance must belong to the requested
    `event_id` ... A violation of any of these relationship rules is rejected with
    `ERR_RELATION_MISMATCH` (HTTP 422)."

    Design: Corner/validations/relation_mismatch_wave_not_in_distance
    """
    event, distA, _ = fx.setup_open_event(capacity_total=50)
    # A second distance B with its own wave; register against A but with B's wave.
    distB = fx.create_distance(event["id"], label="MARATHON", distance_km=42.195)
    waveB = fx.create_wave(distB["id"])
    fx.create_pricing_tier(distB["id"])
    participant = fx.create_participant()
    headers = make_participant_headers(participant["id"])
    resp = api.create_registration(
        registration_payload(event["id"], distA["id"], waveB["id"], participant["id"]),
        headers)
    validate_error(resp, ApiErrorId.ERR_RELATION_MISMATCH.value)


def test_pledge_against_standard_registration_rejected(api):
    """PRD §3.5: "A pledge may only target a charity registration; pledging against a
    standard entry is a relationship violation rejected with `ERR_RELATION_MISMATCH`."

    Design: Corner/validations/pledge_target_not_charity_rejected
    """
    event, distance, wave, participant, reg = fx.setup_confirmed_registration(capacity_total=50)
    headers = make_participant_headers(participant["id"])
    resp = api.create_pledge(pledge_payload(reg["id"], amount_cents=1000, donor_name="X"), headers)
    validate_error(resp, ApiErrorId.ERR_RELATION_MISMATCH.value)


# ---------------------------------------------------------------------------
# Packet pickup eligibility (corner: endpoints)
# ---------------------------------------------------------------------------
def test_packet_pickup_for_pending_registration_not_eligible(api):
    """PRD §3.7: "Pickup is only eligible when the registration is `CONFIRMED` or
    `BIB_ASSIGNED`; any other status is rejected with `ERR_PACKET_NOT_ELIGIBLE`."

    Design: Corner/endpoints/packet_pickup_for_pending_registration_not_eligible
    """
    event, distance, wave = fx.setup_open_event(capacity_total=50)
    participant = fx.create_participant()
    reg = fx.create_registration(event, distance, wave, participant)  # PENDING_PAYMENT
    resp = api.create_packet_pickup(
        {"registration_id": reg["id"], "picked_up_by_name": "Self"}, PS)
    validate_error(resp, ApiErrorId.ERR_PACKET_NOT_ELIGIBLE.value)


def test_packet_pickup_second_issue_blocked(api):
    """PRD §3.7: "A registration may hold at most one `ISSUED` packet pickup at a time,
    so attempting to issue a second while one is still issued is rejected with
    `ERR_PACKET_ALREADY_ISSUED`."

    Design: Corner/endpoints/packet_pickup_second_issue_blocked
    """
    event, distance, wave, participant, reg = fx.setup_confirmed_registration(capacity_total=50)
    validate_success(api.create_packet_pickup(
        {"registration_id": reg["id"], "picked_up_by_name": "Self", "id_verified": True}, PS),
        expected_status=201)
    resp = api.create_packet_pickup(
        {"registration_id": reg["id"], "picked_up_by_name": "Self Again"}, PS)
    validate_error(resp, ApiErrorId.ERR_PACKET_ALREADY_ISSUED.value)
