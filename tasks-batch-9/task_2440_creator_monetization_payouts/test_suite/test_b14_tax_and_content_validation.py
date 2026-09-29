"""Conditional and temporal rules on documents, ratings and appeals."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_total_count
from test_helpers.constants import (
    FORM_W8BEN,
    RATING_GREEN,
    RATING_RED,
    RATING_SOURCE_DEFAULT,
    RATING_SOURCE_MANUAL,
    RATING_YELLOW,
    TAX_SUBMITTED,
)
from test_helpers.fixtures import content_item, new_creator
from test_helpers.test_users import ADMIN, FINANCE, REVIEWER, make_creator_headers


def test_a_document_country_must_match_the_channel_country(api):
    """A mismatched country is refused and stores no document.

    Design: Corner/validations/tax_profile_country_must_equal_creator_country
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")

    validate_error(
        api.create_tax_profile(
            fac.tax_profile_payload(
                creator["id"],
                creator["version"],
                form_type=FORM_W8BEN,
                country_code="GB",
                tin_provided=False,
            ),
            make_creator_headers(creator["id"]),
        ),
        err.ERR_TAX_COUNTRY_MISMATCH,
        422,
    )
    assert validate_success(api.get_creator(creator["id"], FINANCE))["version"] == (
        creator["version"]
    )
    assert_total_count(
        api.list_tax_profiles(FINANCE, {"creator_id": creator["id"]}), 0
    )


def test_the_domestic_form_is_only_valid_for_the_domestic_country(api):
    """A foreign channel cannot file the domestic form.

    Design: Corner/validations/w9_form_requires_a_us_country_code
    """
    creator = new_creator(api, display_name="Bea Bytes", country_code="GB")

    validate_error(
        api.create_tax_profile(
            fac.tax_profile_payload(
                creator["id"], creator["version"], country_code="GB"
            ),
            make_creator_headers(creator["id"]),
        ),
        err.ERR_TAX_FORM_COUNTRY_INVALID,
        422,
    )
    assert_total_count(
        api.list_tax_profiles(FINANCE, {"creator_id": creator["id"]}), 0
    )


def test_a_treaty_claim_must_carry_a_rate(api):
    """Claiming a treaty without naming the rate is refused.

    Design: Corner/validations/treaty_claim_without_a_rate_is_rejected
    """
    creator = new_creator(api, display_name="Bea Bytes", country_code="GB")

    validate_error(
        api.create_tax_profile(
            fac.tax_profile_payload(
                creator["id"],
                creator["version"],
                form_type=FORM_W8BEN,
                country_code="GB",
                tin_provided=False,
                treaty_claimed=True,
            ),
            make_creator_headers(creator["id"]),
        ),
        err.ERR_TREATY_RATE_REQUIRED,
        422,
    )
    assert_total_count(
        api.list_tax_profiles(FINANCE, {"creator_id": creator["id"]}), 0
    )


def test_a_treaty_rate_without_a_claim_is_refused(api):
    """The rate is only admissible alongside the claim itself.

    Design: Corner/validations/treaty_rate_supplied_without_a_claim_is_rejected
    """
    creator = new_creator(api, display_name="Bea Bytes", country_code="GB")

    validate_error(
        api.create_tax_profile(
            fac.tax_profile_payload(
                creator["id"],
                creator["version"],
                form_type=FORM_W8BEN,
                country_code="GB",
                tin_provided=False,
                treaty_claimed=False,
                treaty_rate_bps=1000,
            ),
            make_creator_headers(creator["id"]),
        ),
        err.ERR_TREATY_RATE_FORBIDDEN,
        422,
    )
    assert_total_count(
        api.list_tax_profiles(FINANCE, {"creator_id": creator["id"]}), 0
    )


def _submitted_profile(api):
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    profile = get_success_data(
        api.create_tax_profile(
            fac.tax_profile_payload(creator["id"], creator["version"]),
            make_creator_headers(creator["id"]),
        )
    )
    get_success_data(
        api.submit_tax_profile(profile["id"], make_creator_headers(creator["id"]))
    )
    return creator, profile


def test_a_rejection_decision_must_state_its_reason(api):
    """The reasonless rejection is refused and the document stays submitted.

    Design: Corner/validations/verify_with_reject_decision_requires_a_rejection_reason
    """
    _creator, profile = _submitted_profile(api)

    validate_error(
        api.verify_tax_profile(profile["id"], {"decision": "REJECT"}, FINANCE),
        err.ERR_REJECTION_REASON_REQUIRED,
        422,
    )
    reloaded = validate_success(api.get_tax_profile(profile["id"], FINANCE))
    assert reloaded["status"] == TAX_SUBMITTED
    assert reloaded["rejection_reason"] is None


def test_an_approval_may_not_carry_a_rejection_reason(api):
    """A contradictory decision is refused and stamps nothing.

    Design: Corner/validations/verify_with_verify_decision_forbids_a_rejection_reason
    """
    _creator, profile = _submitted_profile(api)

    validate_error(
        api.verify_tax_profile(
            profile["id"],
            fac.verify_payload(
                rejection_reason="Looks fine but here is a reason anyway"
            ),
            FINANCE,
        ),
        err.ERR_REJECTION_REASON_FORBIDDEN,
        422,
    )
    reloaded = validate_success(api.get_tax_profile(profile["id"], FINANCE))
    assert reloaded["status"] == TAX_SUBMITTED
    assert reloaded["verified_at"] is None
    assert reloaded["expires_at"] is None


def test_a_reviewer_cannot_claim_the_reserved_provenance(api):
    """The reserved provenance belongs to the system, not to a rater.

    Design: Corner/validations/rate_with_reserved_default_source_is_rejected
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    item = content_item(
        api, creator["id"], title="Launch Vlog", published_at="2026-08-01T00:00:00Z"
    )

    validate_error(
        api.rate_content_item(
            item["id"],
            fac.rate_payload(RATING_YELLOW, rating_source=RATING_SOURCE_DEFAULT),
            REVIEWER,
        ),
        err.ERR_RATING_SOURCE_RESERVED,
        422,
    )
    reloaded = validate_success(api.get_content_item(item["id"], REVIEWER))
    assert reloaded["suitability_rating"] == RATING_GREEN
    assert reloaded["rating_source"] == RATING_SOURCE_DEFAULT
    assert reloaded["last_rated_by_user_id"] is None


def test_an_appeal_must_ask_for_a_less_restrictive_rating(api):
    """Asking for a harsher rating is refused and opens no appeal.

    Design: Corner/validations/appeal_requested_rating_must_be_strictly_less_restrictive
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    item = content_item(
        api, creator["id"], title="Launch Vlog", published_at="2026-08-01T00:00:00Z"
    )
    get_success_data(
        api.rate_content_item(
            item["id"],
            fac.rate_payload(RATING_YELLOW, rating_source=RATING_SOURCE_MANUAL),
            REVIEWER,
        )
    )

    # PRD 3.4 fixes `requested_rating` to `GREEN` or `YELLOW`, so a harsher ask
    # is expressed as a `YELLOW` item requesting `YELLOW`: "a `YELLOW` item
    # admits only `GREEN`; anything else is rejected".
    validate_error(
        api.create_appeal(
            fac.appeal_payload(
                item["id"],
                requested_rating=RATING_YELLOW,
                statement_text="Please leave this clip limited as it stands.",
            ),
            make_creator_headers(creator["id"]),
        ),
        err.ERR_APPEAL_RATING_NOT_IMPROVEMENT,
        422,
    )
    assert validate_success(api.get_content_item(item["id"], REVIEWER))[
        "open_appeal_count"
    ] == 0
    assert_total_count(api.list_appeals(REVIEWER, {"content_item_id": item["id"]}), 0)


def test_a_clip_cannot_be_published_after_the_current_instant(api):
    """A future publication date is refused and stores no clip.

    Design: Corner/validations/content_item_published_after_the_logical_clock_is_rejected
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")

    validate_error(
        api.create_content_item(
            fac.content_item_payload(
                creator["id"],
                title="Tomorrow's Vlog",
                published_at="2026-08-02T00:00:00Z",
            ),
            ADMIN,
        ),
        err.ERR_PUBLISHED_IN_FUTURE,
        422,
    )
    assert_total_count(
        api.list_content_items(ADMIN, {"creator_id": creator["id"]}), 0
    )


def test_the_clock_only_moves_forward(api):
    """A backwards move is refused while a repeat of the current instant is not.

    Design: Corner/validations/logical_clock_cannot_be_moved_backwards
    """
    get_success_data(api.set_clock(fac.clock_payload("2026-08-10T00:00:00Z"), ADMIN))

    validate_error(
        api.set_clock(fac.clock_payload("2026-08-09T23:59:59Z"), ADMIN),
        err.ERR_CLOCK_NOT_MONOTONIC,
        422,
    )
    validate_success(api.set_clock(fac.clock_payload("2026-08-10T00:00:00Z"), ADMIN))
