"""The appeal machine admits exactly one call per state."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_total_count
from test_helpers.constants import (
    APPEAL_SUBMITTED,
    APPEAL_UNDER_REVIEW,
    RATING_GREEN,
    RATING_RED,
    RATING_YELLOW,
)
from test_helpers.fixtures import content_item, new_creator
from test_helpers.test_users import REVIEWER, REVIEWER_ALT, make_creator_headers


def _monetized_clip(api):
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    item = content_item(
        api, creator["id"], title="Launch Vlog", published_at="2026-08-01T00:00:00Z"
    )
    return creator, item


def _demonetized_clip(api):
    creator, item = _monetized_clip(api)
    get_success_data(
        api.rate_content_item(item["id"], fac.rate_payload(RATING_RED), REVIEWER)
    )
    return creator, item


def _open_appeal(api):
    creator, item = _demonetized_clip(api)
    appeal = get_success_data(
        api.create_appeal(
            fac.appeal_payload(
                item["id"],
                requested_rating=RATING_GREEN,
                statement_text="Educational commentary.",
            ),
            make_creator_headers(creator["id"]),
        )
    )
    return creator, item, appeal


def test_a_monetized_clip_has_nothing_to_appeal(api):
    """Only a limited or demonetized clip is appealable at all.

    Design: Corner/state_machines/appeal_on_monetized_content_item_rejected_as_not_appealable
    """
    creator, item = _monetized_clip(api)

    validate_error(
        api.create_appeal(
            fac.appeal_payload(
                item["id"],
                requested_rating=RATING_GREEN,
                statement_text="Pre-emptive appeal.",
            ),
            make_creator_headers(creator["id"]),
        ),
        err.ERR_CONTENT_NOT_APPEALABLE,
        409,
    )
    assert_total_count(api.list_appeals(REVIEWER), 0)
    assert validate_success(api.get_content_item(item["id"], REVIEWER))[
        "open_appeal_count"
    ] == 0


def test_only_one_appeal_may_be_in_flight_per_clip(api):
    """A second appeal on the same clip is refused while the first is live.

    Design: Corner/state_machines/second_appeal_while_one_is_open_rejected
    """
    creator, item, _appeal = _open_appeal(api)

    validate_error(
        api.create_appeal(
            fac.appeal_payload(
                item["id"],
                requested_rating=RATING_YELLOW,
                statement_text="Second attempt.",
            ),
            make_creator_headers(creator["id"]),
        ),
        err.ERR_APPEAL_ALREADY_OPEN,
        409,
    )
    assert_total_count(api.list_appeals(REVIEWER), 1)
    assert validate_success(api.get_content_item(item["id"], REVIEWER))[
        "open_appeal_count"
    ] == 1


def test_review_cannot_be_started_twice(api):
    """Entering review requires the appeal to be awaiting review.

    Design: Corner/state_machines/start_review_on_appeal_already_under_review_rejected
    """
    _creator, _item, appeal = _open_appeal(api)
    get_success_data(api.start_appeal_review(appeal["id"], REVIEWER_ALT))

    validate_error(
        api.start_appeal_review(appeal["id"], REVIEWER_ALT),
        err.ERR_APPEAL_NOT_SUBMITTED,
        409,
    )
    assert validate_success(api.get_appeal(appeal["id"], REVIEWER_ALT))["state"] == (
        APPEAL_UNDER_REVIEW
    )


def test_information_cannot_be_requested_before_review_begins(api):
    """An information request belongs to a review that has started.

    Design: Corner/state_machines/request_info_on_submitted_appeal_rejected
    """
    _creator, _item, appeal = _open_appeal(api)

    validate_error(
        api.request_appeal_info(
            appeal["id"],
            fac.request_info_payload(
                info_request="Please supply the licence for the archival clip."
            ),
            REVIEWER_ALT,
        ),
        err.ERR_APPEAL_NOT_UNDER_REVIEW,
        409,
    )
    reloaded = validate_success(api.get_appeal(appeal["id"], REVIEWER_ALT))
    assert reloaded["state"] == APPEAL_SUBMITTED
    assert reloaded["info_request"] is None


def test_an_appeal_cannot_be_decided_before_review_begins(api):
    """The decision is refused and the clip keeps its rating.

    Design: Corner/state_machines/decide_submitted_appeal_rejected_before_review_starts
    """
    _creator, item, appeal = _open_appeal(api)

    validate_error(
        api.decide_appeal(
            appeal["id"],
            fac.decide_appeal_payload("UPHELD", rationale="Restoring immediately."),
            REVIEWER_ALT,
        ),
        err.ERR_APPEAL_NOT_UNDER_REVIEW,
        409,
    )
    assert validate_success(api.get_appeal(appeal["id"], REVIEWER_ALT))["state"] == (
        APPEAL_SUBMITTED
    )
    assert validate_success(api.get_content_item(item["id"], REVIEWER))[
        "suitability_rating"
    ] == RATING_RED


def test_a_channel_cannot_respond_until_information_is_requested(api):
    """A response is only admissible against an outstanding request.

    Design: Corner/state_machines/respond_to_under_review_appeal_rejected
    """
    creator, _item, appeal = _open_appeal(api)
    get_success_data(api.start_appeal_review(appeal["id"], REVIEWER_ALT))

    validate_error(
        api.respond_to_appeal(
            appeal["id"],
            fac.respond_payload(response_statement="Attaching the licence now."),
            make_creator_headers(creator["id"]),
        ),
        err.ERR_APPEAL_NOT_INFO_REQUESTED,
        409,
    )
    reloaded = validate_success(api.get_appeal(appeal["id"], REVIEWER_ALT))
    assert reloaded["state"] == APPEAL_UNDER_REVIEW
    assert reloaded["revision_round"] == 0


def test_one_information_round_trip_costs_exactly_one_revision_round(api):
    """Responding returns the appeal for review and counts the round once.

    The second entry into review is legal and does not advance the round again.

    Design: Corner/state_machines/appeal_info_request_round_trip_increments_revision_round_once
    """
    creator, _item, appeal = _open_appeal(api)
    get_success_data(api.start_appeal_review(appeal["id"], REVIEWER_ALT))
    get_success_data(
        api.request_appeal_info(
            appeal["id"],
            fac.request_info_payload(
                info_request="Please supply the licence for the archival clip."
            ),
            REVIEWER_ALT,
        )
    )

    responded = validate_success(
        api.respond_to_appeal(
            appeal["id"],
            fac.respond_payload(
                response_statement="Licence PDF reference LIC-2026-0042."
            ),
            make_creator_headers(creator["id"]),
        )
    )
    assert responded["state"] == APPEAL_SUBMITTED
    assert responded["revision_round"] == 1
    assert responded["response_statement"] == "Licence PDF reference LIC-2026-0042."

    resumed = validate_success(api.start_appeal_review(appeal["id"], REVIEWER_ALT), 200)
    assert resumed["state"] == APPEAL_UNDER_REVIEW
    assert resumed["revision_round"] == 1
