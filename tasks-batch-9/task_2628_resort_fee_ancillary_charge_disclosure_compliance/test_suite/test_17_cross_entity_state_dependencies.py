"""States a request cannot set itself: a parent's stay progress and a derived posture."""
from test_helpers import (
    ApiErrorId,
    ARRIVAL_DATE,
    CLOCK_START,
    DEPARTURE_DATE,
    FOLIO_TOTAL_CENTS,
    SINGLE_FEE_INCLUSIONS,
    assert_stamped_at_clock,
    add_fee,
    add_inclusion,
    create_fee_program_payload,
    create_remediation_payload,
    create_resort_fee_payload,
    move_clock_to,
    read_booking,
    read_fee_program,
    read_folio,
    read_property,
    remediate_profile,
    setup_itemized_folio,
    setup_single_fee_published_program,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import AGENT, COMPLIANCE, REVENUE, deploy_profile, add_draft_profile


def test_posting_is_refused_while_the_guest_is_still_in_house(api):
    """The folio's own state is legal; the parent booking is what blocks the post.

    PRD 3.5: "Posting is a `GuestServicesAgent` action and has two entry edges.
    From `ITEMIZED` it requires the folio to be `ITEMIZED` with
    `itemization_complete` true and the booking to be in `stay_status`
    `CHECKED_OUT` — a booking still in house is rejected with
    `ERR_BOOKING_NOT_CHECKED_OUT` (HTTP 409)." PRD 3.5 on the sibling
    transition: "Itemisation is a `GuestServicesAgent` action from `OPEN` to
    `ITEMIZED`. It requires the folio to be `OPEN`, the booking's `stay_status`
    to be `IN_HOUSE` or `CHECKED_OUT`".

    Design: Difficulty/cross_entity_state_dependency/folio_post_requires_booking_checked_out_while_itemize_accepts_in_house
    """
    env = setup_itemized_folio()
    folio_before = read_folio(env["folio"]["id"])
    booking_before = read_booking(env["booking"]["id"])

    # Itemisation already succeeded from IN_HOUSE, which is the whole contrast.
    assert booking_before["stay_status"] == "IN_HOUSE"
    assert folio_before["status"] == "ITEMIZED"
    assert folio_before["itemization_complete"] is True
    assert folio_before["line_count"] == 4
    assert folio_before["posted_at"] is None

    response = api.post_folio(env["folio"]["id"], AGENT)

    error = validate_error(response, ApiErrorId.ERR_BOOKING_NOT_CHECKED_OUT, 409)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE

    folio_after = read_folio(env["folio"]["id"])
    assert folio_after["status"] == "ITEMIZED"
    assert folio_after["posted_at"] is None
    assert folio_after["version"] == folio_before["version"]


def test_the_same_post_succeeds_once_departure_is_reached_and_checkout_taken(api):
    """Check-out is itself gated by the clock, and only then may the folio post.

    PRD 3.4: "Check-out advances `stay_status` from `IN_HOUSE` to `CHECKED_OUT`,
    again as a `GuestServicesAgent` action, and requires the logical clock to be
    at or after the `arrival_date` advanced by `nights` whole days, with
    equality permitted; an early attempt is rejected with
    `ERR_DEPARTURE_NOT_REACHED` (HTTP 409)." PRD 3.5: "Either edge sets
    `posted_at` to the logical clock and increments the folio's `version`."

    Design: Difficulty/cross_entity_state_dependency/folio_post_requires_booking_checked_out_while_itemize_accepts_in_house
    """
    env = setup_itemized_folio()
    assert_stamped_at_clock(
        env["booking"]["arrival_date"], ARRIVAL_DATE, "arrival_date"
    )
    assert env["booking"]["nights"] == 4

    validate_error(
        api.check_out_booking(env["booking"]["id"], AGENT),
        ApiErrorId.ERR_DEPARTURE_NOT_REACHED,
        409,
    )

    move_clock_to(DEPARTURE_DATE)
    checked_out = validate_success(api.check_out_booking(env["booking"]["id"], AGENT))
    assert checked_out["stay_status"] == "CHECKED_OUT"

    posted = validate_success(api.post_folio(env["folio"]["id"], AGENT))
    assert posted["status"] == "POSTED"
    assert_stamped_at_clock(posted["posted_at"], DEPARTURE_DATE, "posted_at")
    assert posted["folio_total_cents"] == FOLIO_TOTAL_CENTS

    booking = read_booking(env["booking"]["id"])
    assert booking["guest_out_of_pocket_cents"] == FOLIO_TOTAL_CENTS


NO_TOTAL_MANDATE = {"jurisdiction_overrides": {"first_quote_total_required": False}}
UNDER_FLOOR_PROFILE = {
    "first_quote_shows_total": False,
    "itemized_at_first_quote": True,
    "disclosure_placement": "RATE_DETAILS",
}
LATER_WINDOW = {
    "version_label": "FY27-Q1",
    "effective_from": "2026-12-01T00:00:00Z",
    "effective_to": "2027-03-01T00:00:00Z",
}


def _frozen_property_with_a_waiting_program(api):
    """A flagged path freezes the property while a later-window program waits."""
    env = setup_single_fee_published_program(**NO_TOTAL_MANDATE)
    env["profile"] = add_draft_profile(env, **UNDER_FLOOR_PROFILE)
    env["profile"] = deploy_profile(env)
    env["profile"] = validate_success(api.audit_profile(env["profile"]["id"], COMPLIANCE))

    successor = validate_success(
        api.create_fee_program(
            create_fee_program_payload(
                env["property"]["id"],
                read_property(env["property"]["id"])["version"],
                **LATER_WINDOW,
            ),
            REVENUE,
        ),
        201,
    )
    fee = add_fee(successor["id"], create_resort_fee_payload())
    add_inclusion(fee["id"], SINGLE_FEE_INCLUSIONS["RESORT"])
    env["successor"] = validate_success(
        api.submit_fee_program_for_review(successor["id"], REVENUE)
    )
    return env


def test_publication_is_frozen_by_a_posture_no_request_ever_wrote(api):
    """The successor program cannot publish while a third entity's flag stands.

    PRD 3.2: "the property's `disclosure_posture` must not be `NON_COMPLIANT`,
    failing with `ERR_PROPERTY_DISCLOSURE_FROZEN` (HTTP 409) — the operator must
    repair its flagged booking paths before it may publish anything new." PRD
    3.3: "Within the candidate set each profile contributes an effective score:
    0 if the profile is `FLAGGED`, regardless of its stored `disclosure_score`,
    because being flagged is itself a total disclosure failure, and its stored
    score otherwise. The property's `min_channel_disclosure_score` is the
    minimum of those effective scores."

    Design: Difficulty/cross_entity_state_dependency/fee_program_publish_blocked_while_property_posture_is_non_compliant
    """
    env = _frozen_property_with_a_waiting_program(api)

    assert env["profile"]["status"] == "FLAGGED"
    assert env["profile"]["disclosure_score"] == 50
    frozen = read_property(env["property"]["id"])
    assert frozen["min_channel_disclosure_score"] == 0
    assert frozen["disclosure_posture"] == "NON_COMPLIANT"
    assert frozen["published_fee_program_count"] == 1

    successor = read_fee_program(env["successor"]["id"])
    assert successor["status"] == "UNDER_REVIEW"
    assert successor["mandatory_fee_count"] == 1
    assert successor["published_at"] is None

    validate_error(
        api.publish_fee_program(
            successor["id"], "Attesting the successor inventory.", COMPLIANCE
        ),
        ApiErrorId.ERR_PROPERTY_DISCLOSURE_FROZEN,
        409,
    )

    after = read_fee_program(successor["id"])
    assert after["status"] == "UNDER_REVIEW"
    assert after["published_at"] is None
    assert read_property(env["property"]["id"])["published_fee_program_count"] == 1


def test_clearing_the_freeze_means_repairing_the_path_not_the_program(api):
    """Only a profile-side repair lifts the posture, and then the publish lands.

    PRD 3.3: "Remediation moves a profile `FLAGGED → REMEDIATED` and may be
    performed by the owning `ChannelOperator` or by a `RevenueManager` acting on
    the channel's behalf ... On success the profile's
    `confirmed_undisclosed_count` is reset to 0 — the repaired path is not made
    to carry the sins of the path it replaced — its `remediation_round`
    increments by 1, its `disclosure_score` is recomputed from the new switches,
    and its `last_audited_at` is stamped".
    PRD 3.2: "the program's half-open effective interval must not overlap the
    interval of any other `PUBLISHED` program of the same property ... failing
    with `ERR_FEE_PROGRAM_PERIOD_OVERLAP`."

    Design: Difficulty/cross_entity_state_dependency/fee_program_publish_blocked_while_property_posture_is_non_compliant
    """
    env = _frozen_property_with_a_waiting_program(api)

    repaired = remediate_profile(env, create_remediation_payload())
    assert repaired["status"] == "REMEDIATED"
    assert repaired["disclosure_score"] == 100

    thawed = read_property(env["property"]["id"])
    assert thawed["min_channel_disclosure_score"] == 100
    assert thawed["disclosure_posture"] == "COMPLIANT"

    published = validate_success(
        api.publish_fee_program(
            env["successor"]["id"], "Attesting the successor inventory.", COMPLIANCE
        )
    )
    assert published["status"] == "PUBLISHED"
    assert published["mandatory_fee_count"] == 1
    assert_stamped_at_clock(published["published_at"], CLOCK_START, "published_at")

    # The two windows touch at 2026-12-01 without overlapping, so both stand.
    assert read_property(env["property"]["id"])["published_fee_program_count"] == 2
