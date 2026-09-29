"""Missing fields, enum membership, numeric ranges and text bounds."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_total_count
from test_helpers.constants import (
    FORM_W9,
    PRODUCT_TYPE_SUBSCRIPTIONS,
)
from test_helpers.fixtures import august_period, new_creator, subs_product
from test_helpers.test_users import ADMIN, FINANCE, make_creator_headers


def test_a_registration_without_a_country_is_refused(api):
    """A required field left out is reported before anything is stored.

    Design: Corner/entities/create_creator_missing_country_code_is_missing_required_field
    """
    validate_error(
        api.create_creator(
            fac.creator_payload(
                display_name="No Country",
                country_code=fac.OMIT,
                follower_count=50000,
                watch_time_minutes_365d=300000,
            ),
            ADMIN,
        ),
        err.ERR_MISSING_REQUIRED_FIELD,
        422,
    )
    assert_total_count(api.list_creators(ADMIN), 0)


def test_an_ingestion_without_an_attribution_instant_is_refused(api):
    """The attribution instant is required even when every reference resolves.

    Design: Corner/entities/create_revenue_event_missing_occurred_at_is_missing_required_field
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    validate_success(api.evaluate_creator(creator["id"], FINANCE))
    august_period(api)
    product = subs_product(api, name="Memberships")

    validate_error(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"],
                product["id"],
                gross_amount_cents=1000000,
                occurred_at=fac.OMIT,
            ),
            FINANCE,
        ),
        err.ERR_MISSING_REQUIRED_FIELD,
        422,
    )
    assert_total_count(api.list_revenue_events(FINANCE), 0)


def test_a_tax_document_without_the_expected_version_is_refused(api):
    """The expected channel version is a required input, not an option.

    The channel's version is untouched and no document is stored.

    Design: Corner/entities/tax_profile_create_missing_expected_creator_version_is_missing_required_field
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")

    validate_error(
        api.create_tax_profile(
            fac.tax_profile_payload(
                creator["id"],
                fac.OMIT,
                form_type=FORM_W9,
                country_code="US",
                tin_provided=True,
                treaty_claimed=False,
            ),
            make_creator_headers(creator["id"]),
        ),
        err.ERR_MISSING_REQUIRED_FIELD,
        422,
    )
    assert validate_success(api.get_creator(creator["id"], FINANCE))["version"] == 1
    assert_total_count(api.list_tax_profiles(FINANCE), 0)


def test_a_country_outside_the_supported_set_is_refused(api):
    """An unsupported country is an enum violation, not a range violation.

    Design: Corner/entities/create_creator_invalid_country_code_enum_rejected
    """
    validate_error(
        api.create_creator(
            fac.creator_payload(
                display_name="Frank France",
                country_code="FR",
                follower_count=50000,
                watch_time_minutes_365d=300000,
            ),
            ADMIN,
        ),
        err.ERR_INVALID_FIELD_VALUE,
        422,
    )
    assert_total_count(api.list_creators(ADMIN), 0)


def test_a_negative_audience_count_is_out_of_range(api):
    """A follower count below zero is a range violation.

    Design: Corner/entities/create_creator_negative_follower_count_out_of_range
    """
    validate_error(
        api.create_creator(
            fac.creator_payload(
                display_name="Negative Nel",
                country_code="US",
                follower_count=-1,
                watch_time_minutes_365d=300000,
            ),
            ADMIN,
        ),
        err.ERR_FIELD_OUT_OF_RANGE,
        422,
    )


def test_a_share_above_the_declared_ceiling_is_out_of_range(api):
    """A creator share of 9500 basis points exceeds its inclusive ceiling.

    The split still closes to the whole, so the refusal can only come from the
    range check, and no surface is stored.

    Design: Corner/entities/create_revenue_product_creator_share_above_max_out_of_range
    """
    validate_error(
        api.create_product(
            fac.product_payload(
                product_type=PRODUCT_TYPE_SUBSCRIPTIONS,
                name="Greedy Split",
                creator_share_bps=9500,
                platform_fee_bps=500,
            ),
            ADMIN,
        ),
        err.ERR_FIELD_OUT_OF_RANGE,
        422,
    )
    assert_total_count(api.list_products(ADMIN), 0)


def test_an_unparseable_window_start_is_refused(api):
    """A start instant that is not a parseable timestamp is an invalid value.

    Design: Corner/entities/create_earnings_period_unparseable_timestamp_rejected
    """
    validate_error(
        api.create_period(
            fac.period_payload(
                label="Bad Window",
                period_start="2026-13-45",
                period_end="2026-09-01T00:00:00Z",
            ),
            ADMIN,
        ),
        err.ERR_INVALID_FIELD_VALUE,
        422,
    )


def test_a_blank_display_name_is_refused(api):
    """The name must be non-blank, so the empty string is an invalid value.

    Design: Corner/entities/create_creator_text_bound_violation_on_display_name
    """
    validate_error(
        api.create_creator(
            fac.creator_payload(
                display_name="",
                country_code="US",
                follower_count=50000,
                watch_time_minutes_365d=300000,
            ),
            ADMIN,
        ),
        err.ERR_INVALID_FIELD_VALUE,
        422,
    )
