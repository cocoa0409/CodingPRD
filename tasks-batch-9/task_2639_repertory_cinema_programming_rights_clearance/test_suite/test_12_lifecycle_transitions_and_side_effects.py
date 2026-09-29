"""Lifecycle transitions and their declared side effects.

Every row lands in a declared initial state, and every transition that the
service admits carries a documented set of consequences: the audit subject it
records, the counters it moves, the sibling rows it rewrites and the version it
increments. A transition whose precondition has lapsed carries none of them.
"""
from datetime import datetime, timedelta

from test_helpers import (
    EXECUTIVE_DIRECTOR,
    EXECUTIVE_DIRECTOR_USER_ID,
    PROGRAMMER,
    PROGRAMMER_USER_ID,
    RIGHTS_MANAGER_TWO,
    RIGHTS_MANAGER_TWO_USER_ID,
    RIGHTS_MANAGER_USER_ID,
    TECHNICAL_MANAGER,
    ApiErrorId,
    api_client,
    assert_booking,
    assert_booking_offer,
    assert_clearance,
    assert_dcp_asset,
    enrol_member,
    read_asset,
    read_booking,
    set_logical_clock,
    setup_programming_baseline,
    validate_error,
    validate_paginated,
    validate_success,
)

ISO_WITH_MILLIS = "%Y-%m-%dT%H:%M:%S.%fZ"


class TestDeclaredInitialStates:
    """Nothing in this service is ever born as a draft."""

    def test_new_rows_land_in_their_declared_initial_states(self):
        """An engagement, its opening round, a licence, a package and a card, fresh.

        PRD: "Creation lands the engagement directly in `OFFERED` and simultaneously
        lodges negotiation round 1. That first round is a **BookingOffer** whose
        `booking_id` points back at the engagement, whose `round_index` is 1, whose
        `proposed_by` is `CINEMA`, and whose `proposed_house_nut_cents`,
        `proposed_distributor_share_pct`, `proposed_min_run_days` and
        `proposed_guarantee_cents` mirror the opening terms just stated."

        PRD: "Creation *is* submission: the licence appears directly in `SUBMITTED`, its
        `submitted_by_user_id` recorded from the acting `X-User-ID` as the
        segregation-of-duties subject, its `screenings_used` at 0 and its
        `screenings_remaining` equal to `max_screenings`, with `cleared_by_user_id`,
        `change_request_note` and `revoked_reason` all null."

        PRD: "The asset is created in `REQUESTED` with `received_at` and `ingested_at`
        both null."

        Design: Corner/state_machines/every_new_row_lands_in_its_declared_initial_state
        """
        world = setup_programming_baseline(confirm=False, clear=False)
        member = enrol_member()

        booking = world["booking"]
        assert booking["status"] == "OFFERED", "an engagement begins as an offer"
        assert booking["version"] == 1
        assert booking["round_count"] == 1
        assert booking["scheduled_showtime_count"] == 0
        assert booking["confirmed_by_user_id"] is None
        assert_booking(booking)

        rounds, meta = validate_paginated(
            api_client.list_booking_offers(booking["id"], PROGRAMMER)
        )
        assert meta["total_count"] == 1, "creation lodges exactly one round"
        assert rounds[0]["round_index"] == 1
        assert rounds[0]["proposed_by"] == "CINEMA"
        assert rounds[0]["outcome"] == "PENDING"
        assert rounds[0]["version"] == 1
        assert_booking_offer(rounds[0])

        clearance = world["clearance"]
        assert clearance["status"] == "SUBMITTED", "creation is submission"
        assert clearance["version"] == 1
        assert clearance["cleared_by_user_id"] is None
        assert clearance["screenings_used"] == 0
        assert clearance["screenings_remaining"] == clearance["max_screenings"]
        assert_clearance(clearance)

        asset = world["asset"]
        assert asset["status"] == "REQUESTED"
        assert asset["version"] == 1
        assert asset["received_at"] is None
        assert asset["ingested_at"] is None
        assert_dcp_asset(asset)

        assert member["status"] == "PENDING", "a membership card starts pending"
        assert member["donations"] == []


class TestClearanceAndPrintTraffic:
    """Clearing a licence is a two-person act; print traffic is strictly linear."""

    def test_licence_clearance_records_the_second_operator_and_bumps_the_version(self):
        """A different rights manager clears the licence submitted by the first.

        PRD: "Clearance itself moves the licence `SUBMITTED → CLEARED` and is available
        to a `RightsManager` or an `ExecutiveDirector`, subject to two conditions beyond
        the from-state. The acting `X-User-ID` must differ from the recorded
        `submitted_by_user_id`, or the request is refused with
        `ERR_SEGREGATION_OF_DUTIES`. And the logical clock's venue-local date must be no
        later than `window_end_date`; a licence whose window has already run out can no
        longer be cleared and the attempt is refused with
        `ERR_CLEARANCE_INVALID_STATE` (HTTP 409). On success `cleared_by_user_id` is
        recorded from the acting `X-User-ID`."

        Design: Corner/state_machines/clearance_submitted_to_cleared_is_a_valid_transition
        """
        world = setup_programming_baseline(clear=False)
        lodged = world["clearance"]
        assert lodged["submitted_by_user_id"] == RIGHTS_MANAGER_USER_ID

        response = api_client.clear_clearance(lodged["id"], RIGHTS_MANAGER_TWO)
        data = validate_success(response, expected_status=200)

        assert data["status"] == "CLEARED"
        assert data["submitted_by_user_id"] == RIGHTS_MANAGER_USER_ID, (
            "the segregation subject is not rewritten by clearing"
        )
        assert data["cleared_by_user_id"] == RIGHTS_MANAGER_TWO_USER_ID
        assert data["screenings_used"] == 0, "clearing draws nothing down"
        assert data["screenings_remaining"] == 6
        assert data["version"] == 2, "exactly one mutation since creation"
        assert_clearance(data)

    def test_package_traffic_update_skipping_a_step_is_refused(self):
        """A REQUESTED package cannot jump straight to INGESTING.

        PRD: "Print traffic then advances one declared step at a time, each step
        supplied as a `new_status`, and the chain is strictly linear: `REQUESTED →
        IN_TRANSIT → RECEIVED → INGESTING → INGESTED → RETURNED`. Asking for anything
        other than the single next step from the asset's current status is refused with
        `ERR_DCP_ASSET_INVALID_STATE`."

        Design: Corner/state_machines/dcp_asset_traffic_update_skipping_a_step_returns_invalid_state
        """
        world = setup_programming_baseline()
        asset = world["asset"]
        assert asset["status"] == "REQUESTED"

        response = api_client.traffic_update_dcp_asset(
            asset["id"], {"new_status": "INGESTING"}, TECHNICAL_MANAGER
        )
        validate_error(
            response,
            ApiErrorId.ERR_DCP_ASSET_INVALID_STATE.value,
            expected_status=409,
        )

        after = read_asset(asset["id"])
        assert after["status"] == "REQUESTED", "the refused step moved nothing"
        assert after["received_at"] is None, "RECEIVED was never reached"
        assert after["ingested_at"] is None, "INGESTED was never reached"
        assert after["version"] == 1, "a refused transition is not a mutation"
        assert_dcp_asset(after)


class TestEngagementSignOff:
    """Sign-off accepts the pending round; a lapsed round cannot be accepted at all."""

    def test_engagement_confirmation_executes_every_declared_side_effect(self):
        """Confirming accepts round 1, copies its figures across and records the signer.

        PRD: "When all three hold, the round's `outcome` becomes `ACCEPTED`, its four
        proposed figures overwrite the engagement's `house_nut_cents`,
        `distributor_share_pct`, `min_run_days` and `guarantee_cents` — so the negotiated
        result, not the opening ask, is what settlement will later be priced from —
        `confirmed_by_user_id` is recorded from the acting `X-User-ID`, and the
        engagement moves `OFFERED → CONFIRMED` or `COUNTERED → CONFIRMED` depending on
        which side lodged the accepted round."

        Design: Corner/state_machines/booking_confirm_executes_every_declared_side_effect
        """
        world = setup_programming_baseline(confirm=False, clear=False)
        booking_id = world["booking"]["id"]

        response = api_client.confirm_booking(booking_id, EXECUTIVE_DIRECTOR)
        data = validate_success(response, expected_status=200)

        assert data["status"] == "CONFIRMED"
        assert data["confirmed_by_user_id"] == EXECUTIVE_DIRECTOR_USER_ID
        assert data["created_by_user_id"] == PROGRAMMER_USER_ID, (
            "sign-off does not rewrite who opened the engagement"
        )
        assert data["house_nut_cents"] == 12500
        assert data["distributor_share_pct"] == 0.35
        assert data["min_run_days"] == 4
        assert data["guarantee_cents"] == 3000
        assert data["round_count"] == 1, "accepting a round does not lodge a new one"
        assert data["scheduled_showtime_count"] == 0
        assert_booking(data)

        rounds, meta = validate_paginated(
            api_client.list_booking_offers(booking_id, PROGRAMMER)
        )
        assert meta["total_count"] == 1
        assert rounds[0]["round_index"] == 1
        assert rounds[0]["outcome"] == "ACCEPTED", "the accepted round records the fact"

    def test_engagement_confirmation_after_the_round_lapses_expires_the_offer(self):
        """Seventy-two hours on, the pending round is expired and sign-off is refused.

        PRD: "Its `outcome` starts at `PENDING` and its `expires_at` is set to its own
        `created_at` plus 72 hours of offer validity."

        PRD: "The logical clock must not be later than that round's `expires_at`; if it
        is, the round's `outcome` is moved to `EXPIRED` and the confirmation is refused
        with `ERR_OFFER_EXPIRED`."

        Design: Corner/state_machines/booking_confirm_after_the_offer_lapses_violates_its_precondition
        """
        world = setup_programming_baseline(confirm=False, clear=False)
        booking_id = world["booking"]["id"]

        opening_rounds, _ = validate_paginated(
            api_client.list_booking_offers(booking_id, PROGRAMMER)
        )
        opening = opening_rounds[0]
        created = datetime.strptime(opening["created_at"], ISO_WITH_MILLIS)
        expires = datetime.strptime(opening["expires_at"], ISO_WITH_MILLIS)
        assert expires - created == timedelta(hours=72), (
            "the opening round is valid for exactly 72 hours from its own creation"
        )

        set_logical_clock("2026-08-05T00:00:00Z")

        response = api_client.confirm_booking(booking_id, EXECUTIVE_DIRECTOR)
        validate_error(
            response, ApiErrorId.ERR_OFFER_EXPIRED.value, expected_status=422
        )

        booking = read_booking(booking_id)
        assert booking["status"] == "OFFERED", "the refused sign-off moved no state"
        assert booking["confirmed_by_user_id"] is None
        assert booking["house_nut_cents"] == 12500, (
            "no proposed figure was copied across"
        )

        rounds, meta = validate_paginated(
            api_client.list_booking_offers(booking_id, PROGRAMMER)
        )
        assert meta["total_count"] == 1, "no further round was lodged"
        assert rounds[0]["id"] == opening["id"]
        assert rounds[0]["outcome"] == "EXPIRED", (
            "the lapsed round's outcome is moved to EXPIRED by the refused attempt"
        )
        assert rounds[0]["expires_at"] == opening["expires_at"], (
            "the expiry instant itself is not rewritten"
        )
