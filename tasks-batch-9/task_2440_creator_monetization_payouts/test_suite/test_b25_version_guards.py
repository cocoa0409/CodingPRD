"""Expected-version guards and the version counter that backs them."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_total_count
from test_helpers.constants import (
    ALLOCATION_ACTIVE,
    ALLOCATION_VOIDED,
    FUND_ALLOCATED,
    TAX_DRAFT,
)
from test_helpers.fixtures import (
    august_period,
    eligible_creator,
    new_creator,
    refresh_creator,
)
from test_helpers.test_users import ADMIN, AUDITOR, FINANCE, make_creator_headers


def test_a_tax_document_must_quote_the_channels_current_version(api):
    """The pre-evaluation version is stale; the post-evaluation one is accepted.

    Design: Corner/cross_cutting_complexity_layers/tax_profile_occ_accepts_the_current_creator_version
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    first_version = creator["version"]
    evaluated = get_success_data(api.evaluate_creator(creator["id"], FINANCE))
    owner = make_creator_headers(creator["id"])

    validate_error(
        api.create_tax_profile(
            fac.tax_profile_payload(creator["id"], first_version), owner
        ),
        err.ERR_STALE_CREATOR_VERSION,
        412,
    )

    collected = validate_success(
        api.create_tax_profile(
            fac.tax_profile_payload(creator["id"], evaluated["version"]), owner
        ),
        201,
    )
    assert collected["status"] == TAX_DRAFT
    assert collected["creator_id"] == creator["id"]

    assert refresh_creator(api, creator["id"])["version"] == evaluated["version"] + 1
    assert_total_count(
        api.list_tax_profiles(FINANCE, {"creator_id": creator["id"]}), 1
    )


def test_a_second_allocation_run_must_quote_the_post_allocation_version(api):
    """The version the first run consumed cannot authorize the supersede.

    Design: Corner/cross_cutting_complexity_layers/fund_allocate_occ_rejects_the_pre_allocation_version_on_a_supersede_run
    """
    eligible_creator(
        api,
        display_name="Top Creator",
        country_code="US",
        watch_time_minutes_365d=800000,
    )
    eligible_creator(
        api,
        display_name="Next Creator",
        country_code="GB",
        watch_time_minutes_365d=240000,
    )
    period = august_period(api)
    fund = get_success_data(
        api.create_fund(
            fac.fund_payload(
                period["id"], name="August Boost", total_pool_cents=104000
            ),
            ADMIN,
        )
    )
    first_run = get_success_data(
        api.allocate_fund(fund["id"], fac.allocate_payload(fund["version"]), FINANCE)
    )

    validate_error(
        api.allocate_fund(fund["id"], fac.allocate_payload(fund["version"]), FINANCE),
        err.ERR_STALE_FUND_VERSION,
        412,
    )
    assert validate_success(api.get_fund(fund["id"], FINANCE))[
        "allocation_run_count"
    ] == 1

    superseded = validate_success(
        api.allocate_fund(
            fund["id"], fac.allocate_payload(first_run["version"]), FINANCE
        )
    )
    assert superseded["status"] == FUND_ALLOCATED
    assert superseded["allocation_run_count"] == 2
    assert superseded["recipient_count"] == 2
    assert superseded["allocated_cents"] == 104000
    assert superseded["unallocated_remainder_cents"] == 0

    assert_total_count(
        api.list_fund_allocations(fund["id"], FINANCE, {"status": ALLOCATION_VOIDED}), 2
    )
    assert_total_count(
        api.list_fund_allocations(fund["id"], FINANCE, {"status": ALLOCATION_ACTIVE}), 2
    )


def test_only_a_write_moves_the_version_forward(api):
    """Two reads leave it where it stood; three writes each add one.

    Design: Corner/cross_cutting_complexity_layers/version_advances_on_every_write_and_never_on_a_plain_read
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    baseline = creator["version"]

    assert validate_success(api.get_creator(creator["id"], FINANCE))["version"] == (
        baseline
    )

    evaluated = validate_success(api.evaluate_creator(creator["id"], FINANCE))
    assert evaluated["version"] == baseline + 1

    patched = validate_success(
        api.patch_creator_metrics(
            creator["id"], fac.metrics_payload(follower_count=60000), ADMIN
        )
    )
    assert patched["version"] == baseline + 2

    assert validate_success(api.get_creator(creator["id"], AUDITOR))["version"] == (
        baseline + 2
    )

    configured = validate_success(
        api.set_payout_settings(
            creator["id"],
            fac.payout_settings_payload(
                payout_threshold_cents=5000, payout_method=fac.OMIT
            ),
            FINANCE,
        )
    )
    assert configured["version"] == baseline + 3
    assert configured["payout_threshold_cents"] == 5000
    assert configured["follower_count"] == 60000
