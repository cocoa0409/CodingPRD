"""Validation rules, validation-priority conflicts, cross-entity state dependency,
and the fare-week calendar-containment interval.

Covers Corner queue (B) validations instances and Difficulty queue (A) rules
priority_pair_validation_conflict, cross_entity_state_dependency, and
resource_temporal_overlap (the FareWeek-containment instance).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_tap_payload, create_reduced_fare_card_payload, verify_payload,
    TEST_USERS, make_rider_headers,
    set_clock, make_fare_product, register_rider, add_funding_source, load_balance,
    open_week, record_tap, setup_funded_rider,
    ApiErrorId,
)

MISSING_FS_UUID = "00000000-0000-4000-8000-000000000000"


# ─── Corner: validations section ──────────────────────────────────────────

def test_tap_out_of_range_date_returns_week_mismatch(api):
    """PRD §2.8: "A tap accrues into a fare week only when the tap's fare day falls
    on or after `week_start_date` and on or before the sixth day after
    `week_start_date` ... a tap that violates either condition is rejected with
    `ERR_TAP_WEEK_MISMATCH` (HTTP 422)."

    Design: Corner/validations/tap_week_mismatch_zone_differs
    """
    world = setup_funded_rider(clock="2026-06-09T12:00:00Z", week_start="2026-06-01")
    res = api.create_tap(
        create_tap_payload(world["rider"]["id"], world["week"]["id"],
                           world["funding_source"]["id"], "2026-06-09T09:00:00Z"),
        make_rider_headers(world["rider"]["id"]))
    validate_error(res, ApiErrorId.ERR_TAP_WEEK_MISMATCH.value, expected_status=422)


def test_verify_card_bad_token_returns_422(api):
    """PRD §3.4: "To move a card from `PENDING_VERIFICATION` to `VERIFIED`, the admin
    must echo back the exact `verification_token` the server issued; a mismatched
    token is rejected with `ERR_BAD_VERIFICATION_TOKEN` (HTTP 422)."

    Design: Corner/validations/verify_card_bad_token_returns_422
    """
    make_fare_product(zone_code="ZONEX")
    set_clock("2026-06-01T12:00:00Z")
    rider = register_rider(home_zone_code="ZONEX", email="rt@x.com")
    card = validate_success(api.create_reduced_fare_card(
        create_reduced_fare_card_payload(rider["id"], program_code="SENIOR"),
        make_rider_headers(rider["id"])), 201)
    res = api.verify_reduced_fare_card(
        card["id"], verify_payload("WRONG-TOKEN"), TEST_USERS["fare_admin_headers"])
    validate_error(res, ApiErrorId.ERR_BAD_VERIFICATION_TOKEN.value, expected_status=422)
    fetched = validate_success(api.get_reduced_fare_card(
        card["id"], TEST_USERS["fare_admin_headers"]), 200)
    assert fetched["status"] == "PENDING_VERIFICATION"


def test_verify_expired_card_returns_card_expired(api):
    """PRD §3.4: "The card's `expires_on` must also be on or after the current fare
    day, otherwise verification is rejected with `ERR_CARD_EXPIRED` (HTTP 409)."

    Design: Corner/validations/verify_expired_card_returns_card_expired
    """
    make_fare_product(zone_code="ZONEX")
    set_clock("2026-06-20T12:00:00Z")
    rider = register_rider(home_zone_code="ZONEX", email="re@x.com")
    card = validate_success(api.create_reduced_fare_card(
        create_reduced_fare_card_payload(rider["id"], program_code="SENIOR",
                                         expires_on="2026-06-10"),
        make_rider_headers(rider["id"])), 201)
    res = api.verify_reduced_fare_card(
        card["id"], verify_payload(card["verification_token"]),
        TEST_USERS["fare_admin_headers"])
    validate_error(res, ApiErrorId.ERR_CARD_EXPIRED.value, expected_status=409)


# ─── Difficulty rule priority_pair_validation_conflict ────────────────────
#   instance: closed_week_beats_insufficient_funds_state_vs_fiscal
#
# NOTE: test_closed_week_beats_insufficient_funds was DELETED. PRD §3.11 states
# "Closing is permitted only when no tap in `PENDING` status references the week;
# any pending tap must first be settled or the close is refused." Settle is defined
# only out of `PENDING` (§3.7). Therefore a settleable (PENDING) tap can never
# coexist with a CLOSED week, making the asserted ERR_WEEK_CLOSED-beats-
# ERR_INSUFFICIENT_FUNDS precedence unconstructible under any PRD-faithful
# implementation (the close step itself is refused). The OPEN-week control below
# remains and exercises the ERR_INSUFFICIENT_FUNDS path.

def test_settle_open_week_underfunded_returns_insufficient_funds(api):
    """PRD §3.7: "If instead the computed `charge_cents` exceeds the funding source's
    `prepaid_balance_cents` — insufficient funds — the tap takes the divergent
    branch ... The HTTP response in this case is `ERR_INSUFFICIENT_FUNDS` (HTTP
    402)". Isolated control: with the week left OPEN, the same underfunded settle
    surfaces the fiscal error rather than the week-state error.

    Design: Difficulty/priority_pair_validation_conflict/closed_week_beats_insufficient_funds_state_vs_fiscal
    """
    world = setup_funded_rider(balance=100)
    tap = record_tap(world["rider"]["id"], world["week"]["id"],
                     world["funding_source"]["id"], "2026-06-01T09:00:00Z")
    res = api.settle_tap(tap["id"], TEST_USERS["payment_gateway_headers"])
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value, expected_status=402)


# ─── Difficulty rule priority_pair_validation_conflict ────────────────────
#   instance: not_found_beats_tap_week_mismatch_existence_vs_referential

def test_not_found_beats_tap_week_mismatch(api):
    """PRD §2.9: "Existence comes fourth: every path id and every foreign-key
    reference in the body is checked left-to-right, and the first that does not
    resolve yields `ERR_NOT_FOUND` (HTTP 404)."
    PRD §2.9: "Only after these five layers pass does the system evaluate
    state-machine legality, week-open status, and the domain-specific business rules
    described in §3."

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_tap_week_mismatch_existence_vs_referential
    """
    make_fare_product(zone_code="ZONEX")
    set_clock("2026-06-09T12:00:00Z")
    rider = register_rider(home_zone_code="ZONEX", email="rpp@x.com")
    week = open_week(rider["id"], zone_code="ZONEX")
    # funding_source_id does not resolve AND tapped_at is out of the week range.
    res = api.create_tap(
        create_tap_payload(rider["id"], week["id"], MISSING_FS_UUID,
                           "2026-06-09T09:00:00Z"),
        make_rider_headers(rider["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_tap_week_mismatch_alone_when_refs_resolve(api):
    """PRD §2.8: "a tap that violates either condition is rejected with
    `ERR_TAP_WEEK_MISMATCH` (HTTP 422)." Isolated control: with every reference
    resolving, the out-of-range date alone surfaces the referential error rather
    than NOT_FOUND.

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_tap_week_mismatch_existence_vs_referential
    """
    world = setup_funded_rider(clock="2026-06-09T12:00:00Z", week_start="2026-06-01")
    res = api.create_tap(
        create_tap_payload(world["rider"]["id"], world["week"]["id"],
                           world["funding_source"]["id"], "2026-06-09T09:00:00Z"),
        make_rider_headers(world["rider"]["id"]))
    validate_error(res, ApiErrorId.ERR_TAP_WEEK_MISMATCH.value, expected_status=422)


# ─── Difficulty rule cross_entity_state_dependency ────────────────────────
#   instance: tap_create_requires_fareweek_open_pair_tap_fareweek

def test_tap_create_against_closed_week_rejected(api):
    """PRD §3.6: "At creation the system enforces that the cited week is `OPEN`,
    rejecting a tap against a `CLOSED` week with `ERR_WEEK_CLOSED` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/tap_create_requires_fareweek_open_pair_tap_fareweek
    """
    world = setup_funded_rider(balance=100000)
    validate_success(api.close_fare_week(
        world["week"]["id"], TEST_USERS["fare_admin_headers"]), 200)
    res = api.create_tap(
        create_tap_payload(world["rider"]["id"], world["week"]["id"],
                           world["funding_source"]["id"], "2026-06-01T09:00:00Z"),
        make_rider_headers(world["rider"]["id"]))
    validate_error(res, ApiErrorId.ERR_WEEK_CLOSED.value, expected_status=409)


def test_tap_create_against_open_week_succeeds(api):
    """PRD §3.6: "The new week is `OPEN` with `charged_total_cents` of 0." and "A tap
    is created in `PENDING` status". Positive control for the OPEN-week dependency:
    the same tap creation succeeds while the week remains `OPEN`.

    Design: Difficulty/cross_entity_state_dependency/tap_create_requires_fareweek_open_pair_tap_fareweek
    """
    world = setup_funded_rider(balance=100000)
    res = api.create_tap(
        create_tap_payload(world["rider"]["id"], world["week"]["id"],
                           world["funding_source"]["id"], "2026-06-01T09:00:00Z"),
        make_rider_headers(world["rider"]["id"]))
    tap = validate_success(res, 201)
    assert tap["status"] == "PENDING"


# ─── Difficulty rule resource_temporal_overlap ────────────────────────────
#   instance: fareweek_closed_calendar_containment_rejects_out_of_range_tap

def test_tap_outside_week_window_rejected(api):
    """PRD §2.8: "A fare week opens on a Monday given by `week_start_date` and spans
    seven calendar days, that Monday through the following Sunday inclusive."
    PRD §2.8: "A tap accrues into a fare week only when the tap's fare day falls on
    or after `week_start_date` and on or before the sixth day after
    `week_start_date` ... a tap that violates either condition is rejected with
    `ERR_TAP_WEEK_MISMATCH` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/fareweek_closed_calendar_containment_rejects_out_of_range_tap
    """
    world = setup_funded_rider(clock="2026-06-08T12:00:00Z", week_start="2026-06-01")
    # 2026-06-08 is the eighth day, outside [2026-06-01, 2026-06-07].
    res = api.create_tap(
        create_tap_payload(world["rider"]["id"], world["week"]["id"],
                           world["funding_source"]["id"], "2026-06-08T09:00:00Z"),
        make_rider_headers(world["rider"]["id"]))
    validate_error(res, ApiErrorId.ERR_TAP_WEEK_MISMATCH.value, expected_status=422)


def test_tap_on_last_day_of_week_window_accepted(api):
    """PRD §2.8: "A tap accrues into a fare week only when the tap's fare day falls
    on or after `week_start_date` and on or before the sixth day after
    `week_start_date`". Inclusive upper-bound control: a tap on the sixth day after
    the Monday start (the Sunday) is inside the containment interval and is accepted.

    Design: Difficulty/resource_temporal_overlap/fareweek_closed_calendar_containment_rejects_out_of_range_tap
    """
    world = setup_funded_rider(clock="2026-06-07T12:00:00Z", week_start="2026-06-01")
    # 2026-06-07 is the sixth day after 2026-06-01 (inclusive Sunday).
    res = api.create_tap(
        create_tap_payload(world["rider"]["id"], world["week"]["id"],
                           world["funding_source"]["id"], "2026-06-07T09:00:00Z"),
        make_rider_headers(world["rider"]["id"]))
    tap = validate_success(res, 201)
    assert tap["status"] == "PENDING"
