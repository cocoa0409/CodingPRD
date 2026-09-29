"""Calls whose outcome is owned by the state of a different entity entirely."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers import factories as fac
from test_helpers import fixtures as fx

CLOCK_START = "2026-08-01T00:00:00Z"
CHECK_IN_UTC = "2026-08-14T07:00:00Z"
EXECUTION_UTC = "2026-08-14T09:00:00Z"

GALLERY = TEST_USERS["gallery_manager_headers"]
MARKETING = TEST_USERS["marketing_manager_headers"]
OFFICER_ALPHA = TEST_USERS["compliance_officer_headers"]
FUNDER = TEST_USERS["contract_admin_funder_headers"]


# ---------------------------------------------------------------------------
# Funding reads the financing application, not the agreement
# ---------------------------------------------------------------------------


def _expired_agreement_awaiting_funding():
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_executed_agreement(
        rep_count=1,
        issue_incentive_gift=False,
        check_in_at=CHECK_IN_UTC,
        execute_at=EXECUTION_UTC,
    )
    fx.setup_expired_agreement(scene=scene)
    assert scene["agreement"]["rescission_status"] == "EXPIRED"
    return scene


def _funding_attempt(agreement_id):
    return api.fund_purchase_agreement(
        agreement_id, fac.fund_payload(3_019_980, funding_reference="FND-0001"), FUNDER
    )


def test_funding_is_refused_while_no_approved_application_exists_anywhere():
    """The same payload fails twice: with no application, and with a SUBMITTED one.

    The PRD states: "When the agreement's `financed_amount_cents` is above 0, an
    `APPROVED` financing application must exist for it, otherwise
    `ERR_FINANCING_NOT_APPROVED`; and when such an application exists, its
    `approved_amount_cents` must be at least the agreement's
    `financed_amount_cents`, otherwise `ERR_FINANCING_AMOUNT_SHORTFALL`."

    Design: Difficulty/cross_entity_state_dependency/funding_requires_approved_financing_application_on_other_entity
    """
    scene = _expired_agreement_awaiting_funding()
    agreement_id = scene["agreement"]["id"]

    validate_error(
        _funding_attempt(agreement_id),
        ApiErrorId.ERR_FINANCING_NOT_APPROVED.value,
        409,
    )

    application = fx.submit_financing(
        agreement_id,
        scene["assigned_rep_id"],
        fx.read_agreement(agreement_id)["version"],
        applicant_fico=700,
    )
    assert application["status"] == "SUBMITTED"

    validate_error(
        _funding_attempt(agreement_id),
        ApiErrorId.ERR_FINANCING_NOT_APPROVED.value,
        409,
    )

    unchanged = fx.read_agreement(agreement_id)
    assert unchanged["fulfillment_status"] == "AWAITING_FUNDING"
    assert unchanged["funded_at"] is None


def test_an_approved_but_capped_application_shortfalls_until_a_better_one_supersedes():
    """A 0.90 LTV cap of 3005982 blocks a 3019980 draw until a 0.95 tier approves.

    The PRD states: "`approved_amount_cents` is the smaller of
    `requested_amount_cents` and `ltv_cap_cents`."

    Design: Difficulty/cross_entity_state_dependency/funding_requires_approved_financing_application_on_other_entity
    """
    scene = _expired_agreement_awaiting_funding()
    agreement_id = scene["agreement"]["id"]

    capped = fx.submit_financing(
        agreement_id,
        scene["assigned_rep_id"],
        fx.read_agreement(agreement_id)["version"],
        applicant_fico=700,
    )
    capped = fx.decide_financing(capped["id"], "APPROVE")
    assert capped["apr_bps"] == 1399
    assert capped["ltv_cap_cents"] == 3_005_982
    assert capped["approved_amount_cents"] == 3_005_982
    assert capped["monthly_payment_cents"] == 46_655

    validate_error(
        _funding_attempt(agreement_id),
        ApiErrorId.ERR_FINANCING_AMOUNT_SHORTFALL.value,
        422,
    )

    superseding = fx.submit_financing(
        agreement_id,
        scene["assigned_rep_id"],
        fx.read_agreement(agreement_id)["version"],
        applicant_fico=760,
    )
    assert fx.read_financing_application(capped["id"])["status"] == "WITHDRAWN"
    assert superseding["status"] == "SUBMITTED"

    approved = fx.decide_financing(superseding["id"], "APPROVE")
    assert approved["apr_bps"] == 1099
    assert approved["ltv_cap_cents"] == 3_172_981
    assert approved["approved_amount_cents"] == 3_019_980
    assert approved["monthly_payment_cents"] == 41_583

    funded = validate_success(_funding_attempt(agreement_id))
    assert funded["fulfillment_status"] == "FUNDED"
    assert funded["total_collected_cents"] == 3_339_980

    rows, meta = validate_paginated(
        api.list_closing_packages(FUNDER, params={"agreement_id": agreement_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "AWAITING_RECORDING"
    assert rows[0]["instrument_type"] == "DEED"


# ---------------------------------------------------------------------------
# Booking reads the channel's posture before it scores the household
# ---------------------------------------------------------------------------


def _channel_suspended_by_its_own_no_show():
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    fx.create_representatives(gallery["id"], 1)
    channel = fx.create_channel()
    prospect = fx.create_prospect()
    bookings = [
        fx.create_booking(
            channel["id"],
            prospect["id"],
            gallery["id"],
            scheduled_start_utc="2026-08-16T07:00:00Z",
        )
        for _ in range(4)
    ]
    fx.pin_clock("2026-08-16T07:00:00Z")
    fx.mark_no_show(bookings[0]["id"])
    return {
        "gallery": gallery,
        "channel": channel,
        "prospect": prospect,
        "bookings": bookings,
    }


def _replay_booking(scene):
    return api.create_tour_booking(
        fac.create_tour_booking_payload(
            scene["channel"]["id"],
            scene["prospect"]["id"],
            scene["gallery"]["id"],
            scheduled_start_utc="2026-08-16T10:00:00Z",
        ),
        MARKETING,
    )


def test_a_suspended_channel_refuses_the_booking_before_the_score_is_judged():
    """The channel's posture is reported even though the score would also fail.

    The PRD states: "A suspended channel refuses new bookings, refuses check-in,
    and refuses a reschedule commit, each with `ERR_CHANNEL_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/booking_creation_gated_by_channel_status_and_reinstatement
    """
    scene = _channel_suspended_by_its_own_no_show()

    channel = fx.read_channel(scene["channel"]["id"])
    assert channel["status"] == "SUSPENDED"
    assert channel["no_show_count"] == 1
    assert channel["toured_count"] == 0
    assert channel["historical_no_show_rate"] == 1.0

    for booking in scene["bookings"][1:]:
        cancelled = fx.read_booking(booking["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "CHANNEL_SUSPENDED"

    validate_error(
        _replay_booking(scene), ApiErrorId.ERR_CHANNEL_SUSPENDED.value, 409
    )


def test_reinstatement_clears_the_rate_but_keeps_the_lifetime_sample_armed():
    """The replayed payload succeeds at a score of 80 while booked_count keeps rising.

    The PRD states: "`booked_count` is deliberately *not* reset, so the sample gate
    stays armed and a channel that misbehaves again re-suspends as soon as its
    post-reinstatement rate reaches the threshold."

    Design: Difficulty/cross_entity_state_dependency/booking_creation_gated_by_channel_status_and_reinstatement
    """
    scene = _channel_suspended_by_its_own_no_show()

    reinstated = fx.reinstate_channel(scene["channel"]["id"])
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["no_show_count"] == 0
    assert reinstated["toured_count"] == 0
    assert reinstated["historical_no_show_rate"] == 0.0
    assert reinstated["booked_count"] == 4

    accepted = validate_success(_replay_booking(scene), 201)
    assert accepted["qualification_score"] == 80
    assert accepted["qualification_penalty_points"] == 0

    assert fx.read_channel(scene["channel"]["id"])["booked_count"] == 5


# ---------------------------------------------------------------------------
# Gallery posture is owned by the roster, three entities away
# ---------------------------------------------------------------------------


def _sole_representative_pulled_into_retraining():
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    representative = fx.create_representative(gallery["id"])
    channel = fx.create_channel()
    prospect = fx.create_prospect()
    assert fx.read_gallery(gallery["id"])["available_rep_count"] == 1
    assert fx.read_gallery(gallery["id"])["status"] == "OPEN"

    assignment = fx.assign_retraining(
        representative["id"],
        representative["version"],
        "DISCLOSURE_GAP",
        required_module_count=2,
    )
    started = fx.start_retraining(assignment["id"])
    return {
        "gallery": gallery,
        "representative": representative,
        "channel": channel,
        "prospect": prospect,
        "assignment": started,
    }


def _booking_attempt(scene):
    return api.create_tour_booking(
        fac.create_tour_booking_payload(
            scene["channel"]["id"],
            scene["prospect"]["id"],
            scene["gallery"]["id"],
            scheduled_start_utc="2026-08-16T07:00:00Z",
        ),
        MARKETING,
    )


def test_starting_a_retraining_restricts_the_gallery_and_stops_new_bookings():
    """The assignment moves the rep, the rep moves the posture, the posture refuses.

    The PRD states: "Both `RESTRICTED` and `CLOSED` refuse booking creation,
    check-in and reschedule commits with `ERR_GALLERY_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/gallery_reopen_posture_derived_from_representative_availability
    """
    scene = _sole_representative_pulled_into_retraining()

    assert scene["assignment"]["status"] == "IN_PROGRESS"
    assert fx.read_representative(scene["representative"]["id"])["status"] == "RETRAINING"

    gallery = fx.read_gallery(scene["gallery"]["id"])
    assert gallery["available_rep_count"] == 0
    assert gallery["status"] == "RESTRICTED"

    validate_error(
        _booking_attempt(scene), ApiErrorId.ERR_GALLERY_NOT_OPEN.value, 409
    )


def test_requesting_open_re_derives_the_posture_instead_of_obeying_it():
    """A CLOSED gallery asked to open lands on RESTRICTED until the roster refills.

    The PRD states: "Requesting `OPEN` from `CLOSED` re-derives rather than obeys:
    with at least one available representative the gallery lands on `OPEN`, and
    with no available representatives it lands on `RESTRICTED`."

    Design: Difficulty/cross_entity_state_dependency/gallery_reopen_posture_derived_from_representative_availability
    """
    scene = _sole_representative_pulled_into_retraining()
    gallery_id = scene["gallery"]["id"]

    assert fx.set_gallery_status(gallery_id, "CLOSED")["status"] == "CLOSED"
    assert fx.set_gallery_status(gallery_id, "OPEN")["status"] == "RESTRICTED"

    fx.create_representative(
        gallery_id,
        full_name="Marco Iyer",
        license_number="FL-SL-410078",
        rotation_position=2,
    )
    reopened = fx.read_gallery(gallery_id)
    assert reopened["available_rep_count"] == 1
    assert reopened["status"] == "OPEN"

    booking = validate_success(_booking_attempt(scene), 201)
    assert booking["qualification_score"] == 80

    fx.close_retraining(scene["assignment"]["id"], "COMPLETE", 2)
    restored = fx.read_representative(scene["representative"]["id"])
    assert restored["status"] == "ACTIVE"
    assert restored["compliance_strike_count"] == 0
    assert fx.read_gallery(gallery_id)["available_rep_count"] == 2
