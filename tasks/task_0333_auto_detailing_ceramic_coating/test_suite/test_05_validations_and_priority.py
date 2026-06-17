"""Booking validations, validation-priority conflicts, OCC stale-version
checks, the guarantee window and no-credit boundaries, and cross-entity state
dependencies (bay maintenance, rework-original-not-released).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_customer_headers,
    set_clock, seed_package, seed_vehicle_size_rate,
    create_customer, create_service_bay, create_mobile_unit,
    create_active_membership,
    book_shop_appointment, book_mobile_appointment,
    complete_ceramic_shop_to_released, file_rework_claim,
    setup_released_ceramic_with_in_window_claim,
    advance_to_ready_non_ceramic, pay_full,
)
from test_helpers.factories import create_appointment_payload
from test_helpers.test_users import TEST_USERS

DETAILER = TEST_USERS["detailer_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]


# ──────────────────────────────────────────────────────────────────────
# Difficulty / priority_pair_validation_conflict /
#   stale_bay_version_beats_time_conflict_referential_vs_temporal
# ──────────────────────────────────────────────────────────────────────

def test_stale_bay_version_beats_time_conflict():
    """PRD §2.9: "then the bay version (`ERR_STALE_BAY_VERSION`) which is evaluated before any overlap arithmetic, then resource availability (`ERR_RESOURCE_UNAVAILABLE`), then the bay time-overlap check (`ERR_BAY_TIME_CONFLICT`)."
    PRD §2.7: "the booking was composed against a stale view of the bay and is rejected with `ERR_STALE_BAY_VERSION` (HTTP 412), before any overlap arithmetic is attempted."

    Design: Difficulty/priority_pair_validation_conflict/stale_bay_version_beats_time_conflict_referential_vs_temporal
    """
    set_clock("2026-06-15T07:00:00Z")
    seed_package(tier="CERAMIC")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="rita@x.com", full_name="Rita W")
    bay = create_service_bay(bay_code="B7", supports_ceramic=True)
    bay_v0 = bay["version"]
    # Existing CERAMIC occupancy 08:00..(next day)12:45; this booking bumps bay version.
    book_shop_appointment(
        cust["id"], bay, tier="CERAMIC", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T08:00:00Z",
    )
    # Second booking carries the STALE bay_v0 AND time-conflicts at 10:00.
    payload = create_appointment_payload(
        cust["id"], tier="CERAMIC", vehicle_size="SEDAN", location_mode="SHOP",
        scheduled_start_utc="2026-06-15T10:00:00Z", service_bay_id=bay["id"],
        expected_service_bay_version=bay_v0,
    )
    res = api_client.create_appointment(payload, make_customer_headers(cust["id"]))
    validate_error(res, "ERR_STALE_BAY_VERSION", 412)


def test_stale_bay_version_alone_rejected_without_time_conflict():
    """PRD §2.7: "If a prior write has advanced the bay's `version` since the client last read it — for instance by flipping the bay into maintenance or booking another slot on it — the booking was composed against a stale view of the bay and is rejected with `ERR_STALE_BAY_VERSION` (HTTP 412), before any overlap arithmetic is attempted."

    Design: Difficulty/priority_pair_validation_conflict/stale_bay_version_beats_time_conflict_referential_vs_temporal
    """
    set_clock("2026-06-15T07:00:00Z")
    seed_package(tier="CERAMIC")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="rita2@x.com", full_name="Rita W2")
    bay = create_service_bay(bay_code="B7b", supports_ceramic=True)
    bay_v0 = bay["version"]
    # Flip the bay status to advance its version; no existing appointment, so no
    # time conflict is possible. The stale captured version alone is rejected.
    get_success_data(api_client.set_bay_status(bay["id"], {"status": "AVAILABLE"}, SCHEDULER))
    payload = create_appointment_payload(
        cust["id"], tier="CERAMIC", vehicle_size="SEDAN", location_mode="SHOP",
        scheduled_start_utc="2026-06-15T10:00:00Z", service_bay_id=bay["id"],
        expected_service_bay_version=bay_v0,
    )
    res = api_client.create_appointment(payload, make_customer_headers(cust["id"]))
    validate_error(res, "ERR_STALE_BAY_VERSION", 412)


# ──────────────────────────────────────────────────────────────────────
# Difficulty / priority_pair_validation_conflict /
#   invalid_state_beats_balance_outstanding_state_vs_fiscal
# ──────────────────────────────────────────────────────────────────────

def test_invalid_state_beats_balance_outstanding_on_release():
    """PRD §2.8: "A request to drive either axis along a transition that is not legal from the appointment's current state on that axis is rejected with `ERR_INVALID_STATE`."
    PRD §3.4: "Release is permitted only when the appointment is `READY` and either it is fully paid — its `payment_status` is `PAID`, equivalently its `outstanding_balance_cents` is zero — or it is a rework-spawned appointment (its `spawned_from_rework_claim_id` is non-null)."
    PRD §2.9: "Business rules specific to each operation run after these gates, in the order described alongside each workflow in §3."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_balance_outstanding_state_vs_fiscal
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="sid@x.com", full_name="Sid X")
    unit = create_mobile_unit(unit_code="M2", travel_buffer_minutes=30)
    appt = book_mobile_appointment(
        cust["id"], unit["id"], tier="FULL", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T10:00:00Z",
    )
    # Freshly BOOKED + UNPAID; release attempted (not READY).
    res = api_client.release(appt["id"], DETAILER)
    validate_error(res, "ERR_INVALID_STATE", 409)


def test_balance_outstanding_fires_once_state_valid():
    """PRD §3.4: "An attempt to release a non-rework appointment that still owes money is rejected with `ERR_BALANCE_OUTSTANDING`."
    PRD §3.4: "Release is permitted only when the appointment is `READY` and either it is fully paid — its `payment_status` is `PAID`, equivalently its `outstanding_balance_cents` is zero — or it is a rework-spawned appointment"

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_balance_outstanding_state_vs_fiscal
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="sid2@x.com", full_name="Sid X2")
    unit = create_mobile_unit(unit_code="M2b", travel_buffer_minutes=30)
    appt = book_mobile_appointment(
        cust["id"], unit["id"], tier="FULL", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T09:00:00Z",
    )
    # Drive to READY (the state precondition now passes) but leave it UNPAID, so
    # the fiscal check is the one that fires rather than ERR_INVALID_STATE.
    advance_to_ready_non_ceramic(appt["id"])
    res = api_client.release(appt["id"], DETAILER)
    validate_error(res, "ERR_BALANCE_OUTSTANDING", 409)


# ──────────────────────────────────────────────────────────────────────
# Difficulty / boundary_precision_check /
#   guarantee_window_strict_less_than_boundary_on_rework_claim
# ──────────────────────────────────────────────────────────────────────

def test_rework_claim_at_window_end_rejected():
    """PRD §3.8: "the guarantee window ends at the original appointment's `vehicle_release_utc` advanced by the original tier's `guarantee_days`, and the claim counts as within window only if the claim's `created_at` is strictly before that window end. A claim filed exactly at the window end is out of window."
    PRD §3.8: "only when `filed_within_window` is true (otherwise the approval is rejected with `ERR_GUARANTEE_EXPIRED`)"

    Design: Difficulty/boundary_precision_check/guarantee_window_strict_less_than_boundary_on_rework_claim
    """
    set_clock("2026-03-01T08:00:00Z")
    seed_package(tier="CERAMIC")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="tom@x.com", full_name="Tom Y")
    bay = create_service_bay(bay_code="B8", supports_ceramic=True)
    orig = complete_ceramic_shop_to_released(
        cust["id"], bay, booking_start="2026-03-01T08:00:00Z",
        release_utc="2026-03-02T12:45:00Z",
    )
    # release 2026-03-02T12:45 + 90 days = 2026-05-31T12:45 window end (strict).
    # Filing AT the window end succeeds (PRD §3.8: "A claim begins in SUBMITTED
    # status") but records filed_within_window=False; the guarantee-expired
    # rejection (ERR_GUARANTEE_EXPIRED) fires on APPROVE, the endpoint the PRD
    # pins it to ("otherwise the approval is rejected with ERR_GUARANTEE_EXPIRED").
    set_clock("2026-05-31T12:45:00Z")
    from test_helpers.factories import create_rework_claim_payload
    claim = validate_success(
        api_client.create_rework_claim(
            create_rework_claim_payload(orig["id"], reason="fading"),
            make_customer_headers(cust["id"]),
        ),
        201,
    )
    assert claim["filed_within_window"] is False
    res = api_client.approve_rework_claim(
        claim["id"], {"expected_claim_version": claim["version"]}, SCHEDULER
    )
    validate_error(res, "ERR_GUARANTEE_EXPIRED", 409)


def test_rework_claim_one_minute_before_window_end_within_window():
    """PRD §3.8: "the claim counts as within window only if the claim's `created_at` is strictly before that window end. A claim filed exactly at the window end is out of window."
    PRD §3.8: "A claim begins in `SUBMITTED` status with no `rework_appointment_id`."

    Design: Difficulty/boundary_precision_check/guarantee_window_strict_less_than_boundary_on_rework_claim
    """
    set_clock("2026-03-01T08:00:00Z")
    seed_package(tier="CERAMIC")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="tom2@x.com", full_name="Tom Y2")
    bay = create_service_bay(bay_code="B8b", supports_ceramic=True)
    orig = complete_ceramic_shop_to_released(
        cust["id"], bay, booking_start="2026-03-01T08:00:00Z",
        release_utc="2026-03-02T12:45:00Z",
    )
    # One minute before the 2026-05-31T12:45 window end -> strictly before -> in window.
    set_clock("2026-05-31T12:44:00Z")
    from test_helpers.factories import create_rework_claim_payload
    claim = validate_success(
        api_client.create_rework_claim(
            create_rework_claim_payload(orig["id"], reason="haze"),
            make_customer_headers(cust["id"]),
        ),
        201,
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["filed_within_window"] is True


# ──────────────────────────────────────────────────────────────────────
# Difficulty / boundary_precision_check /
#   no_credit_available_zero_credits_remaining_boundary
# ──────────────────────────────────────────────────────────────────────

def test_second_credit_booking_rejected_when_zero_remaining():
    """PRD §3.2: "A credit may be applied only when the customer has an `ACTIVE` membership with `credits_remaining` greater than zero; if `use_membership_credit` is true but the membership is not `ACTIVE` or has no credits remaining, the booking is rejected with `ERR_NO_CREDIT_AVAILABLE`."
    PRD §3.5: "When a booking legitimately applies a credit, `credits_consumed_total` increases by one and `credits_remaining` is recomputed."

    Design: Difficulty/boundary_precision_check/no_credit_available_zero_credits_remaining_boundary
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_package(tier="WASH")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="uma@x.com", full_name="Uma Z")
    mem = create_active_membership(cust["id"], default_vehicle_size="SEDAN")
    unit = create_mobile_unit(unit_code="M3", travel_buffer_minutes=30)
    # First booking consumes the single credit.
    book_mobile_appointment(
        cust["id"], unit["id"], tier="FULL", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T09:00:00Z", use_membership_credit=True,
    )
    mem_after = validate_success(
        api_client.get_membership(mem["id"], make_customer_headers(cust["id"])), 200
    )
    assert mem_after["credits_remaining"] == 0
    # Second booking with use_membership_credit -> rejected.
    payload = create_appointment_payload(
        cust["id"], tier="FULL", vehicle_size="SEDAN", location_mode="MOBILE",
        scheduled_start_utc="2026-06-15T15:00:00Z", mobile_unit_id=unit["id"],
        use_membership_credit=True,
    )
    res = api_client.create_appointment(payload, make_customer_headers(cust["id"]))
    validate_error(res, "ERR_NO_CREDIT_AVAILABLE", 409)


def test_first_credit_booking_consumes_credit_to_zero():
    """PRD §3.2: "A credit may be applied only when the customer has an `ACTIVE` membership with `credits_remaining` greater than zero"
    PRD §3.5: "When a booking legitimately applies a credit, `credits_consumed_total` increases by one and `credits_remaining` is recomputed."

    Design: Difficulty/boundary_precision_check/no_credit_available_zero_credits_remaining_boundary
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_package(tier="WASH")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="uma2@x.com", full_name="Uma Z2")
    mem = create_active_membership(cust["id"], default_vehicle_size="SEDAN")
    unit = create_mobile_unit(unit_code="M3b", travel_buffer_minutes=30)
    # Membership starts with credits_remaining == 1 (> 0); first credit booking
    # is legitimate and drives the remaining count to 0.
    book_mobile_appointment(
        cust["id"], unit["id"], tier="FULL", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T09:00:00Z", use_membership_credit=True,
    )
    mem_after = validate_success(
        api_client.get_membership(mem["id"], make_customer_headers(cust["id"])), 200
    )
    assert mem_after["credits_consumed_total"] == 1
    assert mem_after["credits_remaining"] == 0


# ──────────────────────────────────────────────────────────────────────
# Difficulty / cross_entity_state_dependency /
#   appointment_booking_blocked_by_bay_maintenance_state
# ──────────────────────────────────────────────────────────────────────

def test_booking_blocked_by_bay_maintenance():
    """PRD §3.2: "The chosen resource must be usable — a bay or unit sitting in `MAINTENANCE` causes `ERR_RESOURCE_UNAVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/appointment_booking_blocked_by_bay_maintenance_state
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="val@x.com", full_name="Val A")
    bay = create_service_bay(bay_code="B9", supports_ceramic=False)
    bay_in_maint = validate_success(
        api_client.set_bay_status(bay["id"], {"status": "MAINTENANCE"}, SCHEDULER), 200
    )
    payload = create_appointment_payload(
        cust["id"], tier="FULL", vehicle_size="SEDAN", location_mode="SHOP",
        scheduled_start_utc="2026-06-15T10:00:00Z", service_bay_id=bay["id"],
        expected_service_bay_version=bay_in_maint["version"],
    )
    res = api_client.create_appointment(payload, make_customer_headers(cust["id"]))
    validate_error(res, "ERR_RESOURCE_UNAVAILABLE", 409)


def test_booking_against_available_bay_succeeds():
    """PRD §3.2: "The chosen resource must be usable — a bay or unit sitting in `MAINTENANCE` causes `ERR_RESOURCE_UNAVAILABLE`."
    PRD §3.1: "a bay's `status` begins `AVAILABLE` and may later be flipped between `AVAILABLE` and `MAINTENANCE`."

    Design: Difficulty/cross_entity_state_dependency/appointment_booking_blocked_by_bay_maintenance_state
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="val2@x.com", full_name="Val A2")
    bay = create_service_bay(bay_code="B9b", supports_ceramic=False)
    # Bay is AVAILABLE on creation -> booking is accepted.
    appt = book_shop_appointment(
        cust["id"], bay, tier="FULL", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T10:00:00Z",
    )
    assert appt["work_status"] == "BOOKED"


def test_rework_approve_succeeds_when_original_released():
    """PRD §3.8: "Approval is permitted only from `SUBMITTED`, only when `filed_within_window` is true (otherwise the approval is rejected with `ERR_GUARANTEE_EXPIRED`), and only when the original appointment is `RELEASED`."
    PRD §3.8: "Approving moves the claim to `APPROVED` and runs the rework-spawn cascade"

    Design: Difficulty/cross_entity_state_dependency/rework_approve_blocked_when_original_appointment_not_released
    """
    cust, bay, orig, claim = setup_released_ceramic_with_in_window_claim(email="wes2@x.com")
    # Original is RELEASED here, so approve is permitted on the state precondition.
    res = validate_success(
        api_client.approve_rework_claim(
            claim["id"], {"expected_claim_version": claim["version"]}, SCHEDULER
        ),
        200,
    )
    assert res["status"] == "APPROVED"


# ──────────────────────────────────────────────────────────────────────
# Corner / errors / stale_claim_version_on_double_approve
# ──────────────────────────────────────────────────────────────────────

def test_double_approve_with_stale_claim_version_rejected():
    """PRD §2.7: "The approval cascade legitimately mutates the claim — it records the spawned appointment's id and bumps the claim's `version` — so a second approval still carrying the pre-approval version is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412), which prevents a duplicate free appointment from being spawned."

    Design: Corner/errors/stale_claim_version_on_double_approve
    """
    cust, bay, orig, claim = setup_released_ceramic_with_in_window_claim(email="sc1@x.com")
    # First approve succeeds, bumping the claim version.
    get_success_data(
        api_client.approve_rework_claim(
            claim["id"], {"expected_claim_version": claim["version"]}, SCHEDULER
        )
    )
    # Second approve still carries the pre-spawn version.
    res = api_client.approve_rework_claim(
        claim["id"], {"expected_claim_version": claim["version"]}, SCHEDULER
    )
    validate_error(res, "ERR_STALE_CLAIM_VERSION", 412)


# ──────────────────────────────────────────────────────────────────────
# Corner / cross_cutting_complexity_layers /
#   occ_correct_bay_version_succeeds_and_increments
# ──────────────────────────────────────────────────────────────────────

def test_correct_bay_version_booking_succeeds_and_bumps_version():
    """PRD §2.7: "A request to book an appointment in `SHOP` mode must carry `expected_service_bay_version`, and that value must equal the chosen `ServiceBay`'s current `version`."
    PRD §3.1: "Flipping a bay's status increments the bay's `version"
    PRD §3.2: "For shop bookings, the request also carries `expected_service_bay_version` for the stale-bay check described in §2.7."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_bay_version_succeeds_and_increments
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="CERAMIC")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="ok1@x.com", full_name="Ok One")
    bay = create_service_bay(bay_code="OK1", supports_ceramic=True)
    appt = book_shop_appointment(
        cust["id"], bay, tier="CERAMIC", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T09:00:00Z",
    )
    assert appt["work_status"] == "BOOKED"
    bay_after = validate_success(
        api_client.get_service_bay(bay["id"], make_customer_headers(cust["id"])), 200
    )
    assert bay_after["version"] == 2


# ──────────────────────────────────────────────────────────────────────
# Corner / validations / shop_appointment_without_bay_returns_mode_mismatch
# ──────────────────────────────────────────────────────────────────────

def test_shop_without_bay_returns_mode_mismatch():
    """PRD §3.2: "Location coherence is strict: a `SHOP` booking must name a `service_bay_id` and leave `mobile_unit_id` null, while a `MOBILE` booking must name a `mobile_unit_id` and leave `service_bay_id` null; any other combination is rejected with `ERR_RESOURCE_MODE_MISMATCH`."

    Design: Corner/validations/shop_appointment_without_bay_returns_mode_mismatch
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="mm1@x.com", full_name="Mm One")
    payload = create_appointment_payload(
        cust["id"], tier="FULL", vehicle_size="SEDAN", location_mode="SHOP",
        scheduled_start_utc="2026-06-15T10:00:00Z",
    )
    res = api_client.create_appointment(payload, make_customer_headers(cust["id"]))
    validate_error(res, "ERR_RESOURCE_MODE_MISMATCH", 422)


# ──────────────────────────────────────────────────────────────────────
# Corner / errors / appointment_resource_mode_mismatch_mobile_with_bay
# ──────────────────────────────────────────────────────────────────────

def test_mobile_with_bay_returns_mode_mismatch():
    """PRD §3.2: "Location coherence is strict: a `SHOP` booking must name a `service_bay_id` and leave `mobile_unit_id` null, while a `MOBILE` booking must name a `mobile_unit_id` and leave `service_bay_id` null; any other combination is rejected with `ERR_RESOURCE_MODE_MISMATCH`."

    Design: Corner/errors/appointment_resource_mode_mismatch_mobile_with_bay
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="rm1@x.com", full_name="Rm One")
    bay = create_service_bay(bay_code="RM1", supports_ceramic=False)
    payload = create_appointment_payload(
        cust["id"], tier="FULL", vehicle_size="SEDAN", location_mode="MOBILE",
        scheduled_start_utc="2026-06-15T10:00:00Z", service_bay_id=bay["id"],
        expected_service_bay_version=bay["version"],
    )
    res = api_client.create_appointment(payload, make_customer_headers(cust["id"]))
    validate_error(res, "ERR_RESOURCE_MODE_MISMATCH", 422)


# ──────────────────────────────────────────────────────────────────────
# Corner / validations / ceramic_in_non_ceramic_bay_returns_bay_no_ceramic
# ──────────────────────────────────────────────────────────────────────

def test_ceramic_in_non_ceramic_bay_rejected():
    """PRD §3.2: "A `CERAMIC` job booked in `SHOP` mode additionally requires that the chosen bay's `supports_ceramic` be true, otherwise the booking is rejected with `ERR_BAY_NO_CERAMIC`."

    Design: Corner/validations/ceramic_in_non_ceramic_bay_returns_bay_no_ceramic
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="CERAMIC")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="nc1@x.com", full_name="Nc One")
    bay = create_service_bay(bay_code="NC1", supports_ceramic=False)
    payload = create_appointment_payload(
        cust["id"], tier="CERAMIC", vehicle_size="SEDAN", location_mode="SHOP",
        scheduled_start_utc="2026-06-15T10:00:00Z", service_bay_id=bay["id"],
        expected_service_bay_version=bay["version"],
    )
    res = api_client.create_appointment(payload, make_customer_headers(cust["id"]))
    validate_error(res, "ERR_BAY_NO_CERAMIC", 422)


# ──────────────────────────────────────────────────────────────────────
# Corner / validations / deposit_wrong_amount_returns_payment_amount_mismatch
# ──────────────────────────────────────────────────────────────────────

def test_deposit_wrong_amount_rejected():
    """PRD §3.7: "The request carries `deposit_cents`, which must equal the provisional total multiplied by the deposit rate of two thousand basis points, divided by ten thousand, rounded half up; a mismatch is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/deposit_wrong_amount_returns_payment_amount_mismatch
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="CERAMIC")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="dp1@x.com", full_name="Dp One")
    bay = create_service_bay(bay_code="DP1", supports_ceramic=True)
    appt = book_shop_appointment(
        cust["id"], bay, tier="CERAMIC", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T09:00:00Z",
    )
    # Required deposit = round_half_up(50000*0.2)=10000; send 9999.
    res = api_client.capture_deposit(
        appt["id"], {"deposit_cents": 9999}, make_customer_headers(cust["id"])
    )
    validate_error(res, "ERR_PAYMENT_AMOUNT_MISMATCH", 422)


# ──────────────────────────────────────────────────────────────────────
# Corner / validations / release_with_outstanding_balance_returns_balance_outstanding
# ──────────────────────────────────────────────────────────────────────

def test_release_ready_unpaid_returns_balance_outstanding():
    """PRD §3.4: "An attempt to release a non-rework appointment that still owes money is rejected with `ERR_BALANCE_OUTSTANDING`."
    PRD §3.4: "Release is permitted only when the appointment is `READY` and either it is fully paid — its `payment_status` is `PAID`, equivalently its `outstanding_balance_cents` is zero — or it is a rework-spawned appointment"

    Design: Corner/validations/release_with_outstanding_balance_returns_balance_outstanding
    """
    set_clock("2026-06-15T08:00:00Z")
    seed_package(tier="FULL")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email="bo1@x.com", full_name="Bo One")
    unit = create_mobile_unit(unit_code="BO1", travel_buffer_minutes=30)
    appt = book_mobile_appointment(
        cust["id"], unit["id"], tier="FULL", vehicle_size="SEDAN",
        scheduled_start_utc="2026-06-15T09:00:00Z",
    )
    advance_to_ready_non_ceramic(appt["id"])  # READY but UNPAID, outstanding 12000
    res = api_client.release(appt["id"], DETAILER)
    validate_error(res, "ERR_BALANCE_OUTSTANDING", 409)
