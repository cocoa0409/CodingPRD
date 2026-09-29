"""Finance stays out of policy, and a channel stays inside its own subtree."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_total_count
from test_helpers.constants import (
    APPEAL_SUBMITTED,
    PRODUCT_TYPE_TIPS,
    RATING_GREEN,
    RATING_RED,
    RATING_SOURCE_MANUAL,
    STATEMENT_PROVISIONAL,
)
from test_helpers.fixtures import (
    august_period,
    content_item,
    eligible_creator,
    new_creator,
    post_event,
    refresh_creator,
    statement_for,
    subs_product,
    tips_product,
)
from test_helpers.test_users import ADMIN, FINANCE, REVIEWER, make_creator_headers


def test_finance_may_not_rate_investigate_or_configure(api):
    """Policy work and catalogue configuration are both closed to finance.

    Design: Corner/rbac/finance_operator_cannot_perform_policy_or_configuration_operations
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    item = content_item(
        api, creator["id"], title="Launch Vlog", published_at="2026-08-01T00:00:00Z"
    )

    validate_error(
        api.rate_content_item(
            item["id"],
            fac.rate_payload(RATING_RED, rating_source=RATING_SOURCE_MANUAL),
            FINANCE,
        ),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Finance-opened review",
                violation_window_start="2026-07-01T00:00:00Z",
                violation_window_end="2026-07-02T00:00:00Z",
            ),
            FINANCE,
        ),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_product(
            fac.product_payload(
                name="Memberships",
                creator_share_bps=7000,
                platform_fee_bps=3000,
                min_payable_cents=fac.OMIT,
            ),
            FINANCE,
        ),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_period(
            fac.period_payload(
                label="2026-08",
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-09-01T00:00:00Z",
            ),
            FINANCE,
        ),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.set_clock(fac.clock_payload("2026-08-20T00:00:00Z"), FINANCE),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    assert validate_success(api.get_content_item(item["id"], REVIEWER))[
        "suitability_rating"
    ] == RATING_GREEN
    assert_total_count(api.list_products(ADMIN), 0)
    assert_total_count(api.list_periods(ADMIN), 0)
    assert_total_count(api.list_investigations(REVIEWER), 0)


def test_a_channel_may_not_rate_its_own_clip_or_judge_its_own_appeal(api):
    """Rating and appeal adjudication both belong to policy review.

    Design: Corner/rbac/creator_cannot_rate_content_or_decide_its_own_appeal
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    item = get_success_data(
        api.create_content_item(
            fac.content_item_payload(
                creator["id"],
                title="Launch Vlog",
                published_at="2026-08-01T00:00:00Z",
            ),
            make_creator_headers(creator["id"]),
        )
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
                requested_rating=RATING_GREEN,
                statement_text="The footage is licensed and I hold the invoice.",
            ),
            make_creator_headers(creator["id"]),
        )
    )

    validate_error(
        api.rate_content_item(
            item["id"],
            fac.rate_payload(RATING_GREEN, rating_source=RATING_SOURCE_MANUAL),
            make_creator_headers(creator["id"]),
        ),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.start_appeal_review(appeal["id"], make_creator_headers(creator["id"])),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.decide_appeal(
            appeal["id"],
            fac.decide_appeal_payload("UPHELD", rationale="I am right"),
            make_creator_headers(creator["id"]),
        ),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    reloaded_item = validate_success(api.get_content_item(item["id"], REVIEWER))
    assert reloaded_item["suitability_rating"] == RATING_RED
    assert reloaded_item["last_rated_by_user_id"] == "reviewer-r1"
    reloaded_appeal = validate_success(api.get_appeal(appeal["id"], REVIEWER))
    assert reloaded_appeal["state"] == APPEAL_SUBMITTED
    # PRD 3.4 declares no reviewer-assignment field on an appeal; the refused
    # decision is observable through the decision fields staying null.
    assert reloaded_appeal["decided_by_user_id"] is None
    assert reloaded_appeal["decided_at"] is None


def test_a_channel_may_not_finalize_or_adjudicate_its_own_statement(api):
    """Finalization and dispute resolution are both finance decisions.

    Design: Corner/rbac/creator_cannot_finalize_close_or_settle
    """
    creator = eligible_creator(api, display_name="Ada Ads", country_code="US")
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

    validate_error(
        api.finalize_statement(statement["id"], make_creator_headers(creator["id"])),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.resolve_dispute(
            statement["id"],
            fac.resolve_dispute_payload("UPHELD", 1000),
            make_creator_headers(creator["id"]),
        ),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    reloaded = validate_success(api.get_statement(statement["id"], FINANCE))
    assert reloaded["status"] == STATEMENT_PROVISIONAL
    assert reloaded["dispute_adjustment_cents"] == 0
    assert refresh_creator(api, creator["id"])["available_balance_cents"] == 0


def test_a_channel_may_not_reach_into_another_channels_records(api):
    """Reads and writes aimed at a stranger's subtree are refused as ownership.

    Design: Corner/rbac/creator_cannot_touch_another_creators_resources
    """
    owner = eligible_creator(api, display_name="Ada Ads", country_code="US")
    stranger = new_creator(api, display_name="Bea Bytes", country_code="GB")
    period = august_period(api)
    product = subs_product(api, name="Memberships")
    post_event(
        api,
        owner["id"],
        product["id"],
        gross_amount_cents=1000000,
        occurred_at="2026-08-05T00:00:00Z",
    )
    get_success_data(api.close_period(period["id"], FINANCE))
    statement = statement_for(api, owner["id"], period["id"])
    intruder = make_creator_headers(stranger["id"])

    validate_error(
        api.get_statement(statement["id"], intruder), err.ERR_NOT_RESOURCE_OWNER, 403
    )
    validate_error(
        api.get_creator(owner["id"], intruder), err.ERR_NOT_RESOURCE_OWNER, 403
    )
    validate_error(
        api.create_tax_profile(
            fac.tax_profile_payload(owner["id"], stranger["version"]), intruder
        ),
        err.ERR_NOT_RESOURCE_OWNER,
        403,
    )

    assert_total_count(api.list_tax_profiles(FINANCE), 0)
    assert validate_success(api.get_statement(statement["id"], FINANCE))[
        "creator_id"
    ] == owner["id"]


def test_a_channels_collection_reads_are_narrowed_rather_than_denied(api):
    """Own-subtree collections come back filtered; shared catalogues do not.

    Design: Corner/rbac/creator_list_reads_are_silently_narrowed_not_denied
    """
    first = eligible_creator(api, display_name="Ada Ads", country_code="US")
    second = eligible_creator(api, display_name="Bea Bytes", country_code="GB")
    period = august_period(api)
    product = subs_product(api, name="Memberships")
    tips_product(
        api,
        product_type=PRODUCT_TYPE_TIPS,
        name="Tip Jar",
        creator_share_bps=9000,
        platform_fee_bps=1000,
    )
    post_event(
        api,
        first["id"],
        product["id"],
        gross_amount_cents=1000000,
        occurred_at="2026-08-05T00:00:00Z",
    )
    post_event(
        api,
        second["id"],
        product["id"],
        gross_amount_cents=500000,
        occurred_at="2026-08-06T00:00:00Z",
    )
    get_success_data(api.close_period(period["id"], FINANCE))
    owner = make_creator_headers(first["id"])

    channels = assert_total_count(api.list_creators(owner), 1)
    assert channels[0]["id"] == first["id"]

    statements = assert_total_count(api.list_statements(owner), 1)
    assert statements[0]["creator_id"] == first["id"]

    events = assert_total_count(api.list_revenue_events(owner), 1)
    assert events[0]["creator_id"] == first["id"]
    assert events[0]["gross_amount_cents"] == 1000000

    assert_total_count(api.list_products(owner), 2)

    periods = assert_total_count(api.list_periods(owner), 1)
    assert periods[0]["id"] == period["id"]
