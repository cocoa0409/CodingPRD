"""Birth values, declared defaults and server-owned fields."""

from prd_bench_local_runner.testing import get_success_data, validate_paginated, validate_success

from test_helpers import factories as fac
from test_helpers.assertions import (
    assert_append_only_shape,
    assert_array_envelope,
    assert_instant,
    assert_object_envelope,
    assert_total_count,
)
from test_helpers.constants import (
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_PENDING_REVIEW,
    ENTRY_ACCRUAL,
    EVENT_ACCRUED,
    EVENT_BELOW_MINIMUM,
    FUND_DRAFT,
    INVESTIGATION_OPEN,
    MONETIZED,
    PAYOUT_METHOD_BANK_TRANSFER,
    PAYOUT_STATE_ACCRUING,
    PAYOUT_STATE_HOLD,
    PRODUCT_ACTIVE,
    PRODUCT_TYPE_COMMERCE,
    RATING_GREEN,
    RATING_SOURCE_DEFAULT,
    SOURCE_REVENUE_EVENT,
)
from test_helpers.fixtures import (
    august_period,
    eligible_creator,
    new_creator,
    post_event,
    subs_product,
)
from test_helpers.test_users import ADMIN, AUDITOR, FINANCE, REVIEWER, make_creator_headers


def test_creating_a_channel_returns_the_full_field_envelope(api):
    """Registration echoes the submitted profile at its birth state.

    The channel is born awaiting review with an accruing disbursement state at
    version one, inside a single-object envelope.

    Design: Corner/entities/creator_create_returns_201_with_full_field_envelope
    """
    response = api.create_creator(
        fac.creator_payload(
            display_name="Ada Ads",
            country_code="US",
            follower_count=50000,
            watch_time_minutes_365d=300000,
        ),
        ADMIN,
    )
    creator = assert_object_envelope(response, 201)

    assert creator["display_name"] == "Ada Ads"
    assert creator["country_code"] == "US"
    assert creator["follower_count"] == 50000
    assert creator["watch_time_minutes_365d"] == 300000
    assert creator["eligibility_status"] == ELIGIBILITY_PENDING_REVIEW
    assert creator["payout_state"] == PAYOUT_STATE_ACCRUING
    assert creator["version"] == 1


def test_a_new_channel_carries_the_declared_defaults(api):
    """Omitted optional settings fall back to their documented values.

    The disbursement threshold is 10000 cents by bank transfer, and every
    counter and balance starts empty with no failed criteria recorded.

    Design: Corner/entities/creator_create_applies_declared_defaults
    """
    creator = new_creator(
        api,
        display_name="Default Dana",
        country_code="GB",
        follower_count=0,
        watch_time_minutes_365d=0,
    )

    assert creator["payout_threshold_cents"] == 10000
    assert creator["payout_method"] == PAYOUT_METHOD_BANK_TRANSFER
    assert creator["active_strike_count"] == 0
    assert creator["consecutive_payment_failures"] == 0
    assert creator["fund_credit_balance_cents"] == 0
    assert creator["outstanding_clawback_cents"] == 0
    assert creator["last_evaluation_failed_criteria"] == []


def test_a_new_channel_owns_its_counters_and_stamps(api):
    """Identifiers, stamps and lifetime counters are written by the server.

    Both stamps are the current instant, the channel has never been evaluated
    or struck, and nothing has been paid out yet.

    Design: Corner/entities/creator_system_counters_are_server_owned_at_creation
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")

    assert isinstance(creator["id"], str) and creator["id"].strip()
    assert_instant(creator["created_at"], "2026-08-01T00:00:00Z")
    assert_instant(creator["updated_at"], "2026-08-01T00:00:00Z")
    assert creator["evaluation_count"] == 0
    assert creator["last_evaluated_at"] is None
    assert creator["last_strike_at"] is None
    assert creator["lifetime_paid_cents"] == 0


def test_a_new_product_defaults_its_minimum_and_terms_version(api):
    """A catalogue entry starts payable from the first cent at version one.

    Design: Corner/entities/revenue_product_defaults_min_payable_and_terms_version
    """
    product = get_success_data(
        api.create_product(
            fac.product_payload(
                product_type=PRODUCT_TYPE_COMMERCE,
                name="Merch Store",
                creator_share_bps=6000,
                platform_fee_bps=4000,
                min_payable_cents=fac.OMIT,
            ),
            ADMIN,
        )
    )

    assert product["min_payable_cents"] == 0
    assert product["terms_version"] == 1
    assert product["status"] == PRODUCT_ACTIVE


def test_an_investigation_holds_disbursements_unless_told_otherwise(api):
    """The hold flag defaults to true and immediately gates the channel.

    The case opens against the reviewer who filed it with nothing yet held in
    cash, and the channel moves straight into the hold state.

    Design: Corner/entities/investigation_create_defaults_hold_payouts_true
    """
    creator = new_creator(api, display_name="Holdy Hal", country_code="US")

    investigation = validate_success(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Suspected reused third-party footage",
                violation_window_start="2026-08-01T00:00:00Z",
                violation_window_end="2026-08-10T00:00:00Z",
            ),
            REVIEWER,
        ),
        201,
    )

    assert investigation["hold_payouts"] is True
    assert investigation["state"] == INVESTIGATION_OPEN
    assert investigation["hold_amount_cents"] == 0
    assert investigation["opened_by_user_id"] == "reviewer-r1"
    assert validate_success(api.get_creator(creator["id"], FINANCE))[
        "payout_state"
    ] == PAYOUT_STATE_HOLD


def test_a_new_fund_defaults_its_floor_and_per_recipient_cap(api):
    """A declared fund starts as an undistributed draft.

    The candidate floor is zero and the per-recipient cap 2000000 cents, with
    the whole pool still unallocated and no runs recorded.

    Design: Corner/entities/creator_fund_create_defaults_min_watch_and_max_allocation
    """
    period = august_period(api)

    fund = validate_success(
        api.create_fund(
            fac.fund_payload(
                period["id"],
                name="August Boost",
                min_watch_time_minutes=fac.OMIT,
            ),
            ADMIN,
        ),
        201,
    )

    assert fund["min_watch_time_minutes"] == 0
    assert fund["max_allocation_cents"] == 2000000
    assert fund["status"] == FUND_DRAFT
    assert fund["allocated_cents"] == 0
    assert fund["unallocated_remainder_cents"] == 100000
    assert fund["recipient_count"] == 0
    assert fund["allocation_run_count"] == 0


def test_a_new_clip_is_green_by_system_provenance(api):
    """Rating provenance is server owned and nobody has rated the clip yet.

    The clip is monetized on the default provenance with no rater and no rating
    stamp, so no appeal is admissible against it.

    Design: Corner/entities/content_item_rating_provenance_fields_are_system_owned
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")

    item = validate_success(
        api.create_content_item(
            fac.content_item_payload(
                creator["id"],
                title="Launch Vlog",
                published_at="2026-08-01T00:00:00Z",
            ),
            make_creator_headers(creator["id"]),
        ),
        201,
    )

    assert item["suitability_rating"] == RATING_GREEN
    assert item["rating_source"] == RATING_SOURCE_DEFAULT
    assert item["last_rated_by_user_id"] is None
    assert item["last_rated_at"] is None
    assert item["monetization_state"] == MONETIZED
    assert item["open_appeal_count"] == 0


def test_a_ledger_row_is_append_only(api):
    """Ledger rows carry a creation stamp and no revision fields.

    The single accrual records its amount, its running balance and the event it
    came from, and exposes neither an update stamp nor a version.

    Design: Corner/entities/ledger_entry_rows_are_append_only_with_no_version_field
    """
    creator = eligible_creator(api, display_name="Ada Ads", country_code="US")
    product = subs_product(api, name="Memberships", min_payable_cents=0)
    august_period(api)
    event = post_event(
        api,
        creator["id"],
        product["id"],
        gross_amount_cents=1000000,
        occurred_at="2026-08-05T00:00:00Z",
    )

    rows, meta = assert_array_envelope(api.list_ledger_entries(creator["id"], FINANCE))
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["entry_type"] == ENTRY_ACCRUAL
    assert rows[0]["amount_cents"] == 700000
    assert rows[0]["balance_after_cents"] == 700000
    assert rows[0]["source_entity"] == SOURCE_REVENUE_EVENT
    assert rows[0]["source_id"] == event["id"]
    assert_append_only_shape(rows[0])


def test_reading_a_fresh_channel_shows_four_empty_balances(api):
    """Every derived balance of an untouched channel is zero.

    Design: Corner/entities/get_creator_returns_stored_row_with_zero_derived_balances
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")

    fetched = assert_object_envelope(api.get_creator(creator["id"], AUDITOR))
    assert fetched["id"] == creator["id"]
    assert fetched["ledger_balance_cents"] == 0
    assert fetched["held_cents"] == 0
    assert fetched["statement_payable_cents"] == 0
    assert fetched["available_balance_cents"] == 0


def test_the_channel_list_paginates_and_filters_by_eligibility(api):
    """A page of two of three reports more to come, and the filter narrows it.

    Design: Corner/entities/list_creators_pagination_envelope_and_status_filter
    """
    first = new_creator(api, display_name="Creator One", country_code="US")
    new_creator(
        api,
        display_name="Creator Two",
        country_code="GB",
        follower_count=20,
        watch_time_minutes_365d=20,
    )
    new_creator(
        api,
        display_name="Creator Three",
        country_code="DE",
        follower_count=30,
        watch_time_minutes_365d=30,
    )
    get_success_data(api.evaluate_creator(first["id"], FINANCE))

    page, meta = validate_paginated(
        api.list_creators(ADMIN, {"limit": 2, "offset": 0})
    )
    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    filtered, filtered_meta = validate_paginated(
        api.list_creators(ADMIN, {"eligibility_status": ELIGIBILITY_ELIGIBLE})
    )
    assert len(filtered) == 1
    assert filtered_meta["total_count"] == 1
    assert filtered_meta["has_more"] is False
    assert filtered[0]["id"] == first["id"]
    assert filtered[0]["eligibility_status"] == ELIGIBILITY_ELIGIBLE


def test_revenue_events_can_be_filtered_by_channel_and_status(api):
    """The suppressed event is retrievable by its own status.

    The filter returns only the below-minimum event with its zeroed share while
    the accrued event keeps its 250-cent share.

    Design: Corner/entities/list_revenue_events_filtered_by_status_and_creator
    """
    creator = eligible_creator(api, display_name="Ada Ads", country_code="US")
    august_period(api)
    product = subs_product(
        api, name="Memberships", creator_share_bps=5000, platform_fee_bps=5000,
        min_payable_cents=250,
    )
    accrued = post_event(
        api, creator["id"], product["id"], gross_amount_cents=500,
        occurred_at="2026-08-05T00:00:00Z",
    )
    suppressed = post_event(
        api, creator["id"], product["id"], gross_amount_cents=498,
        occurred_at="2026-08-06T00:00:00Z",
    )

    rows = assert_total_count(
        api.list_revenue_events(
            FINANCE, {"creator_id": creator["id"], "status": EVENT_BELOW_MINIMUM}
        ),
        1,
    )
    assert len(rows) == 1
    assert rows[0]["id"] == suppressed["id"]
    assert rows[0]["creator_share_cents"] == 0
    assert accrued["status"] == EVENT_ACCRUED
    assert accrued["creator_share_cents"] == 250
