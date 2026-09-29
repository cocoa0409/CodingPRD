"""One write, many links: rescission voiding, channel suspension, strike suspension."""

from test_helpers import (
    TEST_USERS,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers import fixtures as fx

CLOCK_START = "2026-08-01T00:00:00Z"
FIRST_TOUR_UTC = "2026-08-14T07:00:00Z"
SECOND_TOUR_UTC = "2026-08-14T09:16:00Z"
POS_DELIVERED_AT = "2026-08-10T10:00:00Z"

GALLERY = TEST_USERS["gallery_manager_headers"]
MARKETING = TEST_USERS["marketing_manager_headers"]
OFFICER_ALPHA = TEST_USERS["compliance_officer_headers"]
OFFICER_BRAVO = TEST_USERS["compliance_officer_bravo_headers"]


# ---------------------------------------------------------------------------
# A validated cancellation notice, five links deep
# ---------------------------------------------------------------------------


def _one_representative_two_agreements():
    """A sole representative with two in-window FL agreements and one loan request."""
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_tour_scene(
        rep_count=1, booking_overrides={"scheduled_start_utc": FIRST_TOUR_UTC}
    )
    second_booking = fx.create_booking(
        scene["channel"]["id"],
        scene["prospect"]["id"],
        scene["gallery"]["id"],
        scheduled_start_utc=SECOND_TOUR_UTC,
    )

    agreements = []
    for index, (booking_id, tour_utc) in enumerate(
        ((scene["booking"]["id"], FIRST_TOUR_UTC), (second_booking["id"], SECOND_TOUR_UTC))
    ):
        fx.pin_clock(tour_utc)
        checked_in = fx.check_in(booking_id, False)
        rep_id = checked_in["assigned_rep_id"]
        presentation = fx.open_presentation(
            booking_id, rep_id, recorded_ack_reference=f"REC-000{index + 1}"
        )
        fx.acknowledge_required_disclosures(presentation["id"], rep_id)
        fx.review_presentation(presentation["id"], "CLEAR", OFFICER_ALPHA)
        fx.complete_presentation(presentation["id"], rep_id)
        agreements.append(
            fx.execute_agreement(
                presentation["id"],
                rep_id,
                state_code="FL",
                product_type="DEEDED_INTEREST",
                pos_delivered_at=POS_DELIVERED_AT,
            )
        )

    rep_id = scene["reps"][0]["id"]
    first, second = agreements
    application = fx.submit_financing(
        first["id"], rep_id, fx.read_agreement(first["id"])["version"]
    )
    request = fx.intake_rescission(first["id"], "HAND_DELIVERED")
    return {
        "gallery_id": scene["gallery"]["id"],
        "rep_id": rep_id,
        "first_agreement": first,
        "second_agreement": second,
        "application": application,
        "request": request,
    }


def test_validated_cancellation_pushes_the_rate_over_the_retraining_threshold():
    """Voiding one of two agreements lands the rate on 0.5000 and opens retraining.

    The PRD states: "Third, when that recomputed analysis shows at least 2
    in-window executed agreements and a rate that has reached at least `0.5000`, a
    compliance retraining assignment is created for the representative with
    `trigger_reason` `CANCELLATION_RATE_BREACH`, `status` `ASSIGNED`,
    `required_module_count` 4 and `cancellation_rate_at_assignment` snapshotting
    the recomputed rate, and the representative moves to `RETRAINING`."

    Design: Difficulty/transitive_cascade/rescission_validation_cascades_to_retraining_and_gallery_restriction
    """
    scene = _one_representative_two_agreements()

    adjudicated = fx.adjudicate_rescission(scene["request"]["id"])
    assert adjudicated["status"] == "VALIDATED"

    voided = fx.read_agreement(scene["first_agreement"]["id"])
    assert voided["rescission_status"] == "RESCINDED"
    assert voided["fulfillment_status"] == "VOIDED"

    representative = fx.read_representative(scene["rep_id"])
    assert representative["executed_agreement_count"] == 2
    assert representative["rescinded_agreement_count"] == 1
    assert representative["cancellation_rate"] == 0.5
    assert representative["status"] == "RETRAINING"

    rows, _meta = validate_paginated(
        api.list_retraining_assignments(GALLERY, params={"rep_id": scene["rep_id"]})
    )
    assert len(rows) == 1
    assignment = rows[0]
    assert assignment["trigger_reason"] == "CANCELLATION_RATE_BREACH"
    assert assignment["status"] == "ASSIGNED"
    assert assignment["required_module_count"] == 4
    assert assignment["cancellation_rate_at_assignment"] == 0.5
    assert assignment["cycle_index"] == 1

    gallery = fx.read_gallery(scene["gallery_id"])
    assert gallery["available_rep_count"] == 0
    assert gallery["status"] == "RESTRICTED"


def test_voiding_an_agreement_cancels_its_loan_request_and_spares_its_sibling():
    """The financing fan-out is separate from the chain and touches only this contract.

    The PRD states: "Separately from that chain, every financing application on
    the voided agreement sitting in `SUBMITTED` or `APPROVED` moves to
    `CANCELLED`, processed in `created_at` ascending order."

    Design: Difficulty/transitive_cascade/rescission_validation_cascades_to_retraining_and_gallery_restriction
    """
    scene = _one_representative_two_agreements()
    assert scene["application"]["status"] == "SUBMITTED"

    fx.adjudicate_rescission(scene["request"]["id"])

    assert fx.read_financing_application(scene["application"]["id"])["status"] == "CANCELLED"

    untouched = fx.read_agreement(scene["second_agreement"]["id"])
    assert untouched["rescission_status"] == "OPEN"
    assert untouched["fulfillment_status"] == "AWAITING_FUNDING"

    analysis = validate_success(api.get_rescission_analysis(scene["rep_id"], GALLERY))
    assert analysis["executed_count"] == 2
    assert analysis["rescinded_count"] == 1
    assert analysis["cancellation_rate"] == 0.5
    assert analysis["min_sample"] == 2
    assert analysis["retraining_required"] is True


# ---------------------------------------------------------------------------
# A single no-show, five links deep
# ---------------------------------------------------------------------------


def _channel_at_the_sample_gate():
    """A telemarketing channel carrying exactly four bookings on four days."""
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    fx.create_representatives(gallery["id"], 1)
    channel = fx.create_channel(
        name="Outbound Telemarketing",
        channel_code="TELEMARKETING",
        incentive_gift_value_cents=9500,
        min_age=18,
        min_household_income_cents=0,
        min_qualification_score=55,
    )
    prospect = fx.create_prospect()
    bookings = [
        fx.create_booking(
            channel["id"],
            prospect["id"],
            gallery["id"],
            scheduled_start_utc=start,
        )
        for start in (
            "2026-08-14T07:00:00Z",
            "2026-08-15T07:00:00Z",
            "2026-08-16T07:00:00Z",
            "2026-08-17T07:00:00Z",
        )
    ]
    fx.pin_clock("2026-08-14T07:00:00Z")
    return {"gallery": gallery, "channel": channel, "bookings": bookings}


def test_one_no_show_suspends_the_channel_and_cancels_its_remaining_tours():
    """The suspension fans out over the three sibling bookings still scheduled.

    The PRD states: "Every booking on the suspended channel whose `status` is
    `SCHEDULED` or `RESCHEDULE_PENDING` is transitioned to `CANCELLED` with
    `cancel_reason` set to the literal string `CHANNEL_SUSPENDED`, processed in
    `created_at` ascending order; then, for every gallery touched by those
    cancellations, `booked_slot_count` is recomputed."

    Design: Difficulty/transitive_cascade/channel_no_show_suspension_cascades_to_bulk_cancellation_and_slot_ledger
    """
    scene = _channel_at_the_sample_gate()
    assert fx.read_gallery(scene["gallery"]["id"])["booked_slot_count"] == 4

    no_show = fx.mark_no_show(scene["bookings"][0]["id"])
    assert no_show["status"] == "NO_SHOW"

    channel = fx.read_channel(scene["channel"]["id"])
    assert channel["status"] == "SUSPENDED"
    assert channel["booked_count"] == 4

    for booking in scene["bookings"][1:]:
        cancelled = fx.read_booking(booking["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "CHANNEL_SUSPENDED"

    assert fx.read_gallery(scene["gallery"]["id"])["booked_slot_count"] == 0


def test_the_no_show_rate_is_recomputed_before_the_probation_gate_is_read():
    """no_show_count 1 over a denominator of 1 gives the 1.0000 that trips probation.

    The PRD states: "Immediately after a no-show pushes `no_show_count` up and the
    rate is recomputed, the system checks three conditions together: `booked_count`
    has reached at least 4, the recomputed `historical_no_show_rate` has reached at
    least `0.5000`, and the channel is currently `ACTIVE`."

    Design: Difficulty/transitive_cascade/channel_no_show_suspension_cascades_to_bulk_cancellation_and_slot_ledger
    """
    scene = _channel_at_the_sample_gate()
    fx.mark_no_show(scene["bookings"][0]["id"])

    channel = fx.read_channel(scene["channel"]["id"])
    assert channel["no_show_count"] == 1
    assert channel["toured_count"] == 0
    assert channel["historical_no_show_rate"] == 1.0
    assert channel["gift_liability_cents"] == 0

    summary = validate_success(
        api.get_channel_no_show_summary(scene["channel"]["id"], MARKETING)
    )
    assert summary["denominator"] == 1
    assert summary["historical_no_show_rate"] == 1.0
    assert summary["suspend_threshold_met"] is True


# ---------------------------------------------------------------------------
# A single egregious finding, four links deep
# ---------------------------------------------------------------------------


def _second_tour_after_a_first_strike():
    """A sole representative already carrying one strike, mid-way through tour two."""
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_tour_scene(
        rep_count=1, booking_overrides={"scheduled_start_utc": FIRST_TOUR_UTC}
    )
    second_booking = fx.create_booking(
        scene["channel"]["id"],
        scene["prospect"]["id"],
        scene["gallery"]["id"],
        scheduled_start_utc=SECOND_TOUR_UTC,
    )

    fx.pin_clock(FIRST_TOUR_UTC)
    first_checked_in = fx.check_in(scene["booking"]["id"], False)
    rep_id = first_checked_in["assigned_rep_id"]
    first_presentation = fx.open_presentation(
        scene["booking"]["id"], rep_id, recorded_ack_reference="REC-0001"
    )
    fx.acknowledge_required_disclosures(first_presentation["id"], rep_id)
    fx.review_presentation(first_presentation["id"], "FLAG", OFFICER_ALPHA)
    fx.complete_presentation(first_presentation["id"], rep_id)

    fx.pin_clock(SECOND_TOUR_UTC)
    fx.check_in(second_booking["id"], False)
    second_presentation = fx.open_presentation(
        second_booking["id"], rep_id, recorded_ack_reference="REC-0002"
    )
    fx.acknowledge_required_disclosures(second_presentation["id"], rep_id)
    return {
        "gallery_id": scene["gallery"]["id"],
        "rep_id": rep_id,
        "first_presentation": first_presentation,
        "presentation": fx.read_presentation(second_presentation["id"]),
    }


def test_an_egregious_finding_flags_on_its_own_clause_not_on_the_score_floor():
    """A score of 60 and the EGREGIOUS clause both hold, and the record flags.

    The PRD states: "The score is auto-flagged when either of two conditions
    holds: the score has fallen below 70, or any finding on the presentation
    carries `severity` `EGREGIOUS`."

    Design: Difficulty/transitive_cascade/egregious_claim_finding_cascades_to_suspension_and_gallery_restriction
    """
    scene = _second_tour_after_a_first_strike()

    finding = fx.file_claim_finding(
        scene["presentation"]["id"],
        "EGREGIOUS",
        scene["presentation"]["version"],
        claim_code="GUARANTEED_APPRECIATION",
        headers=OFFICER_BRAVO,
    )
    assert finding["penalty_points"] == 40
    assert finding["reported_by_user_id"] == "officer-bravo"

    flagged = fx.read_presentation(scene["presentation"]["id"])
    assert flagged["prohibited_claim_points"] == 40
    assert flagged["compliance_score"] == 60
    assert flagged["review_status"] == "FLAGGED"
    assert flagged["flag_count"] == 1
    assert flagged["disclosure_status"] == "COMPLETE"
    assert flagged["disclosure_ack_count"] == 3

    first = fx.read_presentation(scene["first_presentation"]["id"])
    assert first["review_status"] == "FLAGGED"
    assert first["flag_count"] == 1


def test_the_second_strike_suspends_the_representative_and_restricts_the_gallery():
    """The strike counter carries the cascade from the presentation to the site.

    The PRD states: "Second, when that strike count has reached 2, the
    representative moves to `SUSPENDED` *and* a compliance retraining assignment
    is created for them with `trigger_reason` `PROHIBITED_CLAIM_POINTS`, `status`
    `ASSIGNED`, `required_module_count` 4, and `strike_count_at_assignment`
    snapshotting the representative's strike count."

    Design: Difficulty/transitive_cascade/egregious_claim_finding_cascades_to_suspension_and_gallery_restriction
    """
    scene = _second_tour_after_a_first_strike()
    assert fx.read_representative(scene["rep_id"])["compliance_strike_count"] == 1

    fx.file_claim_finding(
        scene["presentation"]["id"],
        "EGREGIOUS",
        scene["presentation"]["version"],
        claim_code="GUARANTEED_APPRECIATION",
        headers=OFFICER_BRAVO,
    )

    representative = fx.read_representative(scene["rep_id"])
    assert representative["compliance_strike_count"] == 2
    assert representative["status"] == "SUSPENDED"

    rows, _meta = validate_paginated(
        api.list_retraining_assignments(GALLERY, params={"rep_id": scene["rep_id"]})
    )
    assert len(rows) == 1
    assignment = rows[0]
    assert assignment["trigger_reason"] == "PROHIBITED_CLAIM_POINTS"
    assert assignment["status"] == "ASSIGNED"
    assert assignment["required_module_count"] == 4
    assert assignment["strike_count_at_assignment"] == 2
    assert assignment["cycle_index"] == 1

    gallery = fx.read_gallery(scene["gallery_id"])
    assert gallery["available_rep_count"] == 0
    assert gallery["status"] == "RESTRICTED"
