"""Stale-version guards, the checkpointed hold sweep and read-after-write agreement."""

from datetime import datetime, timezone

from test_helpers import (
    ANALYST_ONE,
    BALLROOM_B,
    BALLROOM_C,
    SALES_MANAGER,
    VENUE_ADMIN,
    ApiErrorId,
    accept_amendment,
    amend_license,
    append_line_item,
    make_analyst_headers,
    place_hold_with_version,
    read_booking,
    read_hold,
    read_license,
    read_settlement,
    read_space,
    set_clock,
    setup_event_lifecycle,
    validate_error,
    validate_paginated,
    validate_success,
)

BOAT_SHOW_DATES = {
    "event_name": "Sunbelt Boat Show",
    "move_in_start_date": "2027-06-08",
    "show_start_date": "2027-06-10",
    "show_end_date": "2027-06-12",
    "move_out_end_date": "2027-06-13",
}

BOAT_SHOW_DATES_TIGHT_MOVE_IN = {
    "event_name": "Sunbelt Boat Show",
    "move_in_start_date": "2027-06-09",
    "show_start_date": "2027-06-10",
    "show_end_date": "2027-06-12",
    "move_out_end_date": "2027-06-13",
}


def _instant(value):
    """Parse an ISO 8601 UTC stamp so two spellings of one instant compare equal."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_amendment_with_a_stale_expected_license_version_is_refused(api):
    """PRD §2.8: "If any writer has advanced that license's `version` since the client last read it, the amendment is refused with `ERR_STALE_LICENSE_VERSION` and HTTP 412, and the client must re-read the license before it may open the next round."

    One amendment round has already been opened and accepted, so the version the
    client observed before that round no longer describes the row. Re-presenting
    it is refused and leaves the negotiation state untouched; re-reading the
    license makes the identical call succeed.

    Design: Corner/cross_cutting_complexity_layers/license_amendment_with_a_stale_expected_version_rejected
    """
    world = setup_event_lifecycle(api, stage="license_executed", deposit_cents=200_000)
    license_id = world["license"]["id"]
    client_id = world["client"]["id"]

    stale_version = read_license(api, license_id)["version"]
    amend_license(api, license_id, "add a second loading dock slot")
    accept_amendment(api, license_id, client_id)

    refused = api.create_amendment(
        license_id,
        expected_license_version=stale_version,
        amendment_note="extend move-out by four hours",
        headers=SALES_MANAGER,
    )
    validate_error(refused, ApiErrorId.STALE_LICENSE_VERSION.value)

    after_refusal = read_license(api, license_id)
    assert after_refusal["status"] == "EXECUTED"
    assert after_refusal["amendment_round"] == 1
    assert after_refusal["pending_amendment_note"] is None

    fresh_version = after_refusal["version"]
    assert fresh_version > stale_version, (
        f"expected a version beyond the stale {stale_version}, got {fresh_version}"
    )
    accepted = validate_success(
        api.create_amendment(
            license_id,
            expected_license_version=fresh_version,
            amendment_note="extend move-out by four hours",
            headers=SALES_MANAGER,
        ),
        200,
    )
    assert accepted["status"] == "AMENDMENT_PENDING"


def test_hold_placement_with_a_stale_expected_booking_version_is_refused(api):
    """PRD §2.8: "Its value must equal the target `EventBooking`'s current `version`. A mismatch is refused with `ERR_STALE_BOOKING_VERSION` and HTTP 412."

    Placing a hold is itself a write to the parent booking, so the version that
    authorised the first hold is already stale for the second. The refusal must
    not consume the booking's remaining hold slot.

    Design: Corner/cross_cutting_complexity_layers/hold_creation_with_a_stale_expected_booking_version_rejected
    """
    world = setup_event_lifecycle(
        api, stage="booking", space=BALLROOM_B, booking=BOAT_SHOW_DATES
    )
    booking_id = world["booking"]["id"]
    stale_version = world["booking"]["version"]

    first_hold = validate_success(
        place_hold_with_version(api, booking_id, stale_version), 201
    )

    refused = place_hold_with_version(api, booking_id, stale_version)
    validate_error(refused, ApiErrorId.STALE_BOOKING_VERSION.value)

    after_refusal = read_booking(api, booking_id)
    assert after_refusal["hold_count"] == 1
    assert after_refusal["status"] == "TENTATIVE"

    _, meta = validate_paginated(api.list_holds(headers=VENUE_ADMIN, booking_id=booking_id))
    assert meta["total_count"] == 1

    surviving = read_hold(api, first_hold["id"])
    assert surviving["hold_rank"] == 1
    assert surviving["status"] == "ACTIVE"

    fresh_version = after_refusal["version"]
    assert fresh_version > stale_version, (
        f"expected a version beyond the stale {stale_version}, got {fresh_version}"
    )
    second_hold = validate_success(
        place_hold_with_version(api, booking_id, fresh_version), 201
    )
    assert second_hold["hold_rank"] == 2


def test_hold_sweep_rerun_at_the_same_clock_reports_every_counter_at_zero(api):
    """PRD §3.3: "Every hold whose `status` is `CHALLENGED` and whose `challenge_deadline_utc` has strictly passed moves `CHALLENGED → RELEASED`; every hold whose `status` is `ACTIVE` and whose `release_deadline_utc` has strictly passed likewise moves to `RELEASED`."

    The sweep is checkpointed against recorded work rather than recomputed from
    the clock, so the first run past a release deadline reports the released hold
    and the released booking and an immediate second run at the identical clock
    reports nothing left to do.

    Design: Corner/cross_cutting_complexity_layers/hold_sweep_reruns_with_all_counters_at_zero
    """
    world = setup_event_lifecycle(api, stage="hold", space=BALLROOM_B, booking=BOAT_SHOW_DATES)
    booking_id = world["booking"]["id"]
    hold_id = world["hold"]["id"]
    space_id = world["space"]["id"]

    set_clock(api, "2027-03-11T00:00:00Z")

    first_sweep = validate_success(api.run_hold_sweep(headers=VENUE_ADMIN), 200)
    assert first_sweep["expired_challenge_count"] == 0
    assert first_sweep["released_hold_count"] == 1
    assert first_sweep["promoted_hold_count"] == 0
    assert first_sweep["released_booking_count"] == 1

    second_sweep = validate_success(api.run_hold_sweep(headers=VENUE_ADMIN), 200)
    assert second_sweep["expired_challenge_count"] == 0
    assert second_sweep["released_hold_count"] == 0
    assert second_sweep["promoted_hold_count"] == 0
    assert second_sweep["released_booking_count"] == 0

    assert read_hold(api, hold_id)["status"] == "RELEASED"

    booking = read_booking(api, booking_id)
    assert booking["status"] == "RELEASED"
    assert booking["hold_count"] == 0

    assert read_space(api, space_id)["committed_space_days"] == 0


def test_settlement_issue_response_already_carries_the_fee_and_grand_total(api):
    """PRD §3.9: "On either path the totals are recomputed, `issued_by_user_id` is set to the acting `X-User-ID`, `issued_at_utc` is stamped with the logical clock instant, and `dispute_deadline_utc` is set to that instant plus 240 hours — ten days."

    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    The draft settlement still reports zeros; the issuing call's own body already
    carries the recomputed facility service fee and grand total, and the
    follow-up read agrees to the cent.

    Design: Corner/consistency_model/settlement_issue_response_carries_the_fee_and_total_in_the_same_request
    """
    world = setup_event_lifecycle(
        api,
        stage="settlement_draft",
        space=BALLROOM_C,
        deposit_cents=1_300_000,
        booking=BOAT_SHOW_DATES_TIGHT_MOVE_IN,
        open_show_at="2027-06-09T08:00:00Z",
        close_at="2027-06-14T09:00:00Z",
        settlement_basis="CONTRACTED",
    )
    settlement_id = world["settlement"]["id"]
    assert world["settlement"]["facility_service_fee_cents"] == 0
    assert world["settlement"]["grand_total_cents"] == 0

    append_line_item(api, settlement_id, "RENTAL", 5_000_000, memo="contracted rental")

    issued = validate_success(
        api.issue_settlement(settlement_id, headers=make_analyst_headers(ANALYST_ONE)), 200
    )
    assert issued["facility_service_fee_cents"] == 350_000
    assert issued["grand_total_cents"] == 5_350_000
    assert issued["line_subtotal_cents"] == 5_000_000
    assert issued["status"] == "ISSUED"
    assert _instant(issued["dispute_deadline_utc"]) == _instant("2027-06-24T09:00:00Z")

    reread = read_settlement(api, settlement_id)
    assert reread["facility_service_fee_cents"] == 350_000
    assert reread["grand_total_cents"] == 5_350_000
    assert reread["deposit_applied_cents"] == 0


def test_license_issue_response_and_client_read_agree_on_the_escrowed_deposit(api):
    """PRD §3.4: "On success `deposit_held_cents` is set to `deposit_required_cents`, the client's `credit_balance_cents` is decreased by exactly that amount, and `issued_at_utc` is stamped with the logical clock instant."

    Issuing moves money between two aggregates in one request: the write's own
    body already shows the escrow and an immediate read of the client already
    shows the reduced credit, with the lifetime paid-to-date figure untouched.

    Design: Corner/consistency_model/license_issue_response_and_client_read_agree_on_credit_balance
    """
    world = setup_event_lifecycle(api, stage="license_draft", deposit_cents=200_000)
    license_id = world["license"]["id"]
    client_id = world["client"]["id"]
    credit_before = world["client"]["credit_balance_cents"]
    assert credit_before == 200_000

    issued = validate_success(api.issue_license(license_id, headers=SALES_MANAGER), 200)
    escrow_at_issue = issued["deposit_held_cents"]
    assert escrow_at_issue == 90_900
    assert issued["status"] == "ISSUED"
    assert _instant(issued["issued_at_utc"]) == _instant("2026-08-01T00:00:00Z")

    client = validate_success(api.get_client(client_id, headers=SALES_MANAGER), 200)
    credit_after = client["credit_balance_cents"]
    assert credit_after == 109_100
    assert client["total_deposits_paid_cents"] == 200_000
    assert credit_after + escrow_at_issue == credit_before
    assert client["booking_standing"] == "GOOD"
