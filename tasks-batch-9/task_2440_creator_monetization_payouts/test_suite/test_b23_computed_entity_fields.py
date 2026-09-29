"""Fields the service derives for itself rather than accepting from a caller."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_success,
)

from test_helpers import factories as fac
from test_helpers.constants import (
    APPEAL_DENIED,
    DEMONETIZED,
    LIMITED,
    PERIOD_CLOSED,
    PERIOD_FINALIZED,
    PRODUCT_ACTIVE,
    PRODUCT_TYPE_ADVERTISING,
    PRODUCT_TYPE_TIPS,
    RATING_RED,
    RATING_SOURCE_AUTOMATED,
    RATING_SOURCE_MANUAL,
    RATING_YELLOW,
    STATEMENT_FINALIZED,
)
from test_helpers.fixtures import (
    august_period,
    content_item,
    new_creator,
    payable_creator,
    post_event,
    statement_for,
    subs_product,
)
from test_helpers.test_users import ADMIN, FINANCE, REVIEWER, make_creator_headers, make_reviewer_headers


def test_only_an_advertising_surface_is_suitability_sensitive(api):
    """The flag follows the surface kind and is never supplied by the caller.

    Design: Corner/entities/revenue_product_computes_suitability_sensitive_from_product_type
    """
    tips = validate_success(
        api.create_product(
            fac.product_payload(
                product_type=PRODUCT_TYPE_TIPS,
                name="Fan Tips",
                creator_share_bps=8000,
                platform_fee_bps=2000,
                min_payable_cents=fac.OMIT,
            ),
            ADMIN,
        ),
        201,
    )
    ads = validate_success(
        api.create_product(
            fac.product_payload(
                product_type=PRODUCT_TYPE_ADVERTISING,
                name="Pre-roll Ads",
                creator_share_bps=5000,
                platform_fee_bps=5000,
                min_payable_cents=fac.OMIT,
            ),
            ADMIN,
        ),
        201,
    )

    assert ads["suitability_sensitive"] is True
    assert tips["suitability_sensitive"] is False
    assert ads["status"] == PRODUCT_ACTIVE
    assert ads["retired_at"] is None


def test_the_monetization_state_follows_the_suitability_rating(api):
    """A cautionary rating limits the clip; a refusing rating demonetizes it.

    Design: Corner/entities/content_item_monetization_state_is_derived_from_suitability_rating
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    item = content_item(
        api, creator["id"], title="Launch Vlog", published_at="2026-08-01T00:00:00Z"
    )

    limited = validate_success(
        api.rate_content_item(
            item["id"],
            fac.rate_payload(RATING_YELLOW, rating_source=RATING_SOURCE_AUTOMATED),
            REVIEWER,
        )
    )
    assert limited["suitability_rating"] == RATING_YELLOW
    assert limited["monetization_state"] == LIMITED
    assert limited["rating_source"] == RATING_SOURCE_AUTOMATED
    assert limited["last_rated_by_user_id"] == "reviewer-r1"

    demonetized = validate_success(
        api.rate_content_item(
            item["id"],
            fac.rate_payload(RATING_RED, rating_source=RATING_SOURCE_MANUAL),
            REVIEWER,
        )
    )
    assert demonetized["suitability_rating"] == RATING_RED
    assert demonetized["monetization_state"] == DEMONETIZED
    assert demonetized["rating_source"] == RATING_SOURCE_MANUAL


def test_a_decided_appeal_no_longer_counts_as_open(api):
    """The counter drops back to zero the instant the decision lands.

    Design: Corner/entities/content_item_open_appeal_count_excludes_decided_appeals
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    item = content_item(
        api, creator["id"], title="Launch Vlog", published_at="2026-08-01T00:00:00Z"
    )
    get_success_data(
        api.rate_content_item(
            item["id"],
            fac.rate_payload(RATING_RED, rating_source=RATING_SOURCE_MANUAL),
            REVIEWER,
        )
    )
    appeal = get_success_data(
        api.create_appeal(
            fac.appeal_payload(
                item["id"],
                statement_text="The clip is educational commentary.",
            ),
            make_creator_headers(creator["id"]),
        )
    )
    decider = make_reviewer_headers("reviewer-d2")
    get_success_data(api.start_appeal_review(appeal["id"], decider))

    while_open = validate_success(api.get_content_item(item["id"], decider))
    assert while_open["open_appeal_count"] == 1

    decided = validate_success(
        api.decide_appeal(
            appeal["id"],
            fac.decide_appeal_payload(
                "DENIED",
                rationale="Footage violates the advertiser-friendly guideline.",
            ),
            decider,
        )
    )
    assert decided["state"] == APPEAL_DENIED
    assert decided["decided_by_user_id"] == "reviewer-d2"

    after = validate_success(api.get_content_item(item["id"], decider))
    assert after["open_appeal_count"] == 0
    assert after["suitability_rating"] == RATING_RED
    assert after["monetization_state"] == DEMONETIZED


def test_the_window_counts_its_own_statements(api):
    """Closing counts the children and finalizing the last one closes the window.

    Design: Corner/entities/earnings_period_statement_counters_derive_from_children
    """
    creator, _profile = payable_creator(api, display_name="Ada Ads")
    period = august_period(api)
    product = subs_product(api, name="Memberships")
    post_event(
        api,
        creator["id"],
        product["id"],
        gross_amount_cents=1000000,
        occurred_at="2026-08-05T00:00:00Z",
    )
    get_success_data(api.close_period(period["id"], FINANCE))
    statement = statement_for(api, creator["id"], period["id"])

    closed = validate_success(api.get_period(period["id"], FINANCE))
    assert closed["status"] == PERIOD_CLOSED
    assert closed["statement_count"] == 1
    assert closed["finalized_statement_count"] == 0

    finalized_statement = validate_success(
        api.finalize_statement(statement["id"], FINANCE)
    )
    assert finalized_statement["status"] == STATEMENT_FINALIZED
    assert finalized_statement["net_payable_cents"] == 700000

    reloaded = validate_success(api.get_period(period["id"], FINANCE))
    assert reloaded["status"] == PERIOD_FINALIZED
    assert reloaded["statement_count"] == 1
    assert reloaded["finalized_statement_count"] == 1
