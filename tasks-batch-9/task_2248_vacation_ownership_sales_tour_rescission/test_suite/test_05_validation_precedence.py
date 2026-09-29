"""One request breaking two rules at once: the earlier rule must be the one reported."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_instant_equals,
    make_sales_representative_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers import factories as fac
from test_helpers import fixtures as fx

CLOCK_START = "2026-08-01T00:00:00Z"
POS_DELIVERED_AT = "2026-08-10T10:00:00Z"

GALLERY = TEST_USERS["gallery_manager_headers"]
MARKETING = TEST_USERS["marketing_manager_headers"]
OFFICER_ALPHA = TEST_USERS["compliance_officer_headers"]
FUNDER = TEST_USERS["contract_admin_funder_headers"]


# ---------------------------------------------------------------------------
# Funding: the state gate (priority 9) outranks the amount gate (priority 37)
# ---------------------------------------------------------------------------


def _agreement_with_approved_financing_still_inside_its_window():
    fx.pin_clock(CLOCK_START)
    return fx.setup_approved_financing(issue_incentive_gift=False)


def test_open_rescission_window_is_reported_before_a_wrong_collected_amount():
    """A 999-cent funding call on an OPEN contract reports the window, not the money.

    The PRD states: "Requests are validated in a single fixed precedence, and the
    *first* failing check determines the response."

    Design: Difficulty/priority_pair_validation_conflict/funding_state_gate_precedes_fiscal_amount_mismatch
    """
    scene = _agreement_with_approved_financing_still_inside_its_window()
    agreement_id = scene["agreement"]["id"]

    application = scene["financing_application"]
    assert application["status"] == "APPROVED"
    assert application["approved_amount_cents"] == 3019980
    assert application["monthly_payment_cents"] == 41583

    assert fx.read_agreement(agreement_id)["rescission_status"] == "OPEN"

    refused = api.fund_purchase_agreement(
        agreement_id, fac.fund_payload(999, funding_reference="FND-0001"), FUNDER
    )
    validate_error(refused, ApiErrorId.ERR_RESCISSION_PERIOD_ACTIVE.value, 409)

    untouched = fx.read_agreement(agreement_id)
    assert untouched["fulfillment_status"] == "AWAITING_FUNDING"
    assert untouched["funded_at"] is None
    assert untouched["total_collected_cents"] == 0


def test_the_same_funding_payload_reports_the_amount_once_the_window_has_expired():
    """Removing the state failure lets the priority-37 fiscal rule surface.

    The PRD states: "Finally, `collected_amount_cents` must equal
    `financed_amount_cents` exactly — which means 0 for an all-cash agreement —
    otherwise `ERR_FUNDING_AMOUNT_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/funding_state_gate_precedes_fiscal_amount_mismatch
    """
    scene = _agreement_with_approved_financing_still_inside_its_window()
    agreement_id = scene["agreement"]["id"]

    fx.setup_expired_agreement(scene=scene)
    assert scene["sweep"]["swept_count"] == 1
    assert scene["agreement"]["rescission_status"] == "EXPIRED"

    mismatched = api.fund_purchase_agreement(
        agreement_id, fac.fund_payload(999, funding_reference="FND-0001"), FUNDER
    )
    validate_error(mismatched, ApiErrorId.ERR_FUNDING_AMOUNT_MISMATCH.value, 422)

    funded = validate_success(
        api.fund_purchase_agreement(
            agreement_id,
            fac.fund_payload(3019980, funding_reference="FND-0001"),
            FUNDER,
        )
    )
    assert funded["fulfillment_status"] == "FUNDED"
    assert funded["total_collected_cents"] == 3339980


# ---------------------------------------------------------------------------
# Execution: the safety gate (priority 17) outranks the referential gate (19)
# ---------------------------------------------------------------------------


def _unreviewed_presentation_and_another_household_s_agreement():
    """Two prospects on one gallery: one cleared with a contract, one unreviewed."""
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    fx.create_representatives(gallery["id"], 2)
    channel = fx.create_channel()
    first_prospect = fx.create_prospect()
    other_prospect = fx.create_prospect(
        household_name="Bergstrom Household",
        primary_age=52,
        household_income_cents=12_000_000,
        marital_status="MARRIED",
    )
    other_booking = fx.create_booking(
        channel["id"], other_prospect["id"], gallery["id"]
    )
    booking = fx.create_booking(channel["id"], first_prospect["id"], gallery["id"])

    fx.pin_clock("2026-08-14T07:00:00Z")
    other_rep_id = fx.check_in(other_booking["id"], False)["assigned_rep_id"]
    rep_id = fx.check_in(booking["id"], False)["assigned_rep_id"]

    other_presentation = fx.open_presentation(
        other_booking["id"], other_rep_id, recorded_ack_reference="REC-OTHER-1"
    )
    fx.acknowledge_required_disclosures(other_presentation["id"], other_rep_id)
    fx.review_presentation(other_presentation["id"], "CLEAR", OFFICER_ALPHA)
    other_agreement = fx.execute_agreement(
        other_presentation["id"],
        other_rep_id,
        state_code="FL",
        product_type="DEEDED_INTEREST",
        pos_delivered_at=POS_DELIVERED_AT,
    )

    presentation = fx.open_presentation(
        booking["id"], rep_id, recorded_ack_reference="REC-0001"
    )
    fx.acknowledge_required_disclosures(presentation["id"], rep_id)
    return {
        "other_prospect": other_prospect,
        "other_agreement": other_agreement,
        "presentation": fx.read_presentation(presentation["id"]),
        "rep_id": rep_id,
    }


def _upgrade_payload(scene):
    return fac.create_purchase_agreement_payload(
        scene["presentation"]["id"],
        product_type="RIGHT_TO_USE",
        state_code="FL",
        purchase_price_cents=3_200_000,
        down_payment_cents=320_000,
        pos_delivered_at=POS_DELIVERED_AT,
        traded_in_agreement_id=scene["other_agreement"]["id"],
    )


def test_an_unreviewed_presentation_is_reported_before_a_foreign_trade_in():
    """The compliance gate fires first even though the trade-in is also wrong.

    The PRD states: "its `review_status` must be `CLEARED`, otherwise
    `ERR_PRESENTATION_NOT_CLEARED`."

    Design: Difficulty/priority_pair_validation_conflict/presentation_safety_gate_precedes_referential_trade_in_mismatch
    """
    scene = _unreviewed_presentation_and_another_household_s_agreement()
    assert scene["presentation"]["disclosure_status"] == "COMPLETE"
    assert scene["presentation"]["review_status"] == "UNREVIEWED"

    refused = api.create_purchase_agreement(
        _upgrade_payload(scene), make_sales_representative_headers(scene["rep_id"])
    )
    validate_error(refused, ApiErrorId.ERR_PRESENTATION_NOT_CLEARED.value, 422)

    _rows, meta = validate_paginated(
        api.list_purchase_agreements(
            GALLERY, params={"presentation_id": scene["presentation"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_clearing_the_presentation_exposes_the_trade_in_owner_mismatch():
    """With the safety gate satisfied the referential gate reports instead.

    The PRD states: "The surrendered agreement's `prospect_id` must equal the new
    agreement's `prospect_id`, otherwise `ERR_TRADE_IN_OWNER_MISMATCH`; and the
    surrendered agreement must sit in `fulfillment_status` `DOCS_DELIVERED` with
    `rescission_status` `EXPIRED`, otherwise `ERR_TRADE_IN_NOT_ELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/presentation_safety_gate_precedes_referential_trade_in_mismatch
    """
    scene = _unreviewed_presentation_and_another_household_s_agreement()

    cleared = fx.review_presentation(
        scene["presentation"]["id"], "CLEAR", OFFICER_ALPHA
    )
    assert cleared["review_status"] == "CLEARED"

    refused = api.create_purchase_agreement(
        _upgrade_payload(scene), make_sales_representative_headers(scene["rep_id"])
    )
    validate_error(refused, ApiErrorId.ERR_TRADE_IN_OWNER_MISMATCH.value, 422)

    other = fx.read_agreement(scene["other_agreement"]["id"])
    assert other["prospect_id"] == scene["other_prospect"]["id"]
    assert other["fulfillment_status"] == "AWAITING_FUNDING"

    _rows, meta = validate_paginated(
        api.list_purchase_agreements(
            GALLERY, params={"presentation_id": scene["presentation"]["id"]}
        )
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Booking: the lead-time gate (priority 21) outranks capacity (priority 29)
# ---------------------------------------------------------------------------


def _capacity_one_gallery_with_its_only_slot_taken():
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery(
        name="Kissimmee Sales Gallery",
        site_code="KISGAL",
        concurrent_tour_capacity=1,
    )
    fx.create_representatives(gallery["id"], 1)
    channel = fx.create_channel()
    prospect = fx.create_prospect()
    fx.create_booking(
        channel["id"],
        prospect["id"],
        gallery["id"],
        scheduled_start_utc="2026-08-14T09:00:00Z",
    )
    fx.pin_clock("2026-08-14T08:30:00Z")
    return {"gallery": gallery, "channel": channel, "prospect": prospect}


def _booking_attempt(scene, scheduled_start_utc):
    return api.create_tour_booking(
        fac.create_tour_booking_payload(
            scene["channel"]["id"],
            scene["prospect"]["id"],
            scene["gallery"]["id"],
            scheduled_start_utc=scheduled_start_utc,
        ),
        MARKETING,
    )


def test_a_slot_inside_the_lead_time_is_reported_before_the_capacity_clash():
    """A 09:00 request from an 08:30 clock reports lead time, not the collision.

    The PRD states: "The requested start must be at least 60 minutes — one full
    hour — after the logical clock, otherwise the request is rejected with
    `ERR_TOUR_SLOT_IN_PAST`."

    Design: Difficulty/priority_pair_validation_conflict/booking_temporal_gate_precedes_capacity_constraint
    """
    scene = _capacity_one_gallery_with_its_only_slot_taken()

    refused = _booking_attempt(scene, "2026-08-14T09:00:00Z")
    validate_error(refused, ApiErrorId.ERR_TOUR_SLOT_IN_PAST.value, 422)

    assert fx.read_channel(scene["channel"]["id"])["booked_count"] == 1
    assert fx.read_gallery(scene["gallery"]["id"])["booked_slot_count"] == 1


def test_clearing_the_lead_time_exposes_the_capacity_conflict():
    """A 10:00 start passes the hour of lead time and then collides on capacity.

    The PRD states: "If the number of overlapping occupying bookings has reached
    the gallery's `concurrent_tour_capacity`, the request is rejected with
    `ERR_GALLERY_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/booking_temporal_gate_precedes_capacity_constraint
    """
    scene = _capacity_one_gallery_with_its_only_slot_taken()

    validate_error(
        _booking_attempt(scene, "2026-08-14T10:00:00Z"),
        ApiErrorId.ERR_GALLERY_CAPACITY_EXCEEDED.value,
        409,
    )

    accepted = validate_success(
        _booking_attempt(scene, "2026-08-14T14:00:00Z"), 201
    )
    assert_instant_equals(
        accepted["scheduled_start_utc"], "2026-08-14T14:00:00Z", "scheduled_start_utc"
    )
    assert_instant_equals(
        accepted["scheduled_end_utc"], "2026-08-14T16:00:00Z", "scheduled_end_utc"
    )

    assert fx.read_channel(scene["channel"]["id"])["booked_count"] == 2
    assert fx.read_gallery(scene["gallery"]["id"])["booked_slot_count"] == 2
