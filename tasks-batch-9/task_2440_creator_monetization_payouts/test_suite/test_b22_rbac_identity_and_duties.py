"""Authentication runs first, and no reviewer may judge their own work."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_total_count
from test_helpers.constants import (
    APPEAL_UNDER_REVIEW,
    APPEAL_UPHELD,
    INVESTIGATION_CLEARED,
    PAYOUT_PENDING,
    PAYOUT_STATE_ACCRUING,
    RATING_GREEN,
    RATING_RED,
    RATING_SOURCE_APPEAL,
    RATING_SOURCE_MANUAL,
)
from test_helpers.fixtures import (
    august_period,
    content_item,
    new_creator,
    payable_creator,
    post_event,
    refresh_creator,
    statement_for,
    subs_product,
)
from test_helpers.test_users import (
    ADMIN,
    BLANK_AUTH_HEADERS,
    FINANCE,
    REVIEWER,
    REVIEWER_ALT,
    UNKNOWN_ROLE_HEADERS,
    make_creator_headers,
    make_reviewer_headers,
)


def test_a_request_without_credentials_is_refused_before_anything_else(api):
    """Neither a malformed body nor a bad page size is examined first.

    Design: Corner/rbac/blank_auth_headers_are_rejected_before_anything_else
    """
    validate_error(
        api.create_creator({"display_name": ""}, BLANK_AUTH_HEADERS),
        err.ERR_MISSING_AUTH_HEADERS,
        401,
    )
    validate_error(
        api.list_creators(BLANK_AUTH_HEADERS, {"limit": 0}),
        err.ERR_MISSING_AUTH_HEADERS,
        401,
    )


def test_an_unrecognized_role_is_refused_before_the_permission_check(api):
    """An unknown role fails authentication; a known one fails authorization.

    Design: Corner/rbac/unknown_role_header_is_rejected_at_priority_two
    """
    payload = fac.creator_payload(
        display_name="Ada Ads",
        country_code="US",
        follower_count=50000,
        watch_time_minutes_365d=300000,
    )

    validate_error(
        api.create_creator(payload, UNKNOWN_ROLE_HEADERS), err.ERR_UNKNOWN_ROLE, 401
    )
    assert_total_count(api.list_creators(ADMIN), 0)


def test_a_channel_identity_must_name_an_existing_channel(api):
    """An identifier that matches no record fails authentication.

    Design: Corner/rbac/creator_identity_must_resolve_to_an_existing_creator_row
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    ghost = make_creator_headers(NON_EXISTENT_UUID)

    validate_error(
        api.get_creator(creator["id"], ghost), err.ERR_CREATOR_IDENTITY_UNKNOWN, 401
    )
    validate_error(
        api.list_creators(ghost), err.ERR_CREATOR_IDENTITY_UNKNOWN, 401
    )


def test_the_role_gate_answers_before_the_ownership_gate(api):
    """A channel reaching for a stranger's disbursement is refused on its role.

    Design: Corner/rbac/role_gate_outranks_creator_ownership
    """
    owner, _profile = payable_creator(api, display_name="Ada Ads")
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
    get_success_data(api.finalize_statement(statement["id"], FINANCE))
    payout = get_success_data(
        api.create_payout(fac.payout_payload(owner["id"]), FINANCE)
    )

    validate_error(
        api.submit_payout(payout["id"], make_creator_headers(stranger["id"])),
        err.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    reloaded = validate_success(api.get_payout(payout["id"], FINANCE))
    assert reloaded["state"] == PAYOUT_PENDING
    assert reloaded["submitted_at"] is None


def test_the_reviewer_who_opened_a_case_may_not_resolve_it(api):
    """Both resolutions are refused for the opener and granted to a colleague.

    Design: Corner/rbac/investigation_opener_cannot_clear_their_own_investigation
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    investigation = get_success_data(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Licensed footage reuse",
                violation_window_start="2026-07-01T00:00:00Z",
                violation_window_end="2026-07-02T00:00:00Z",
                hold_payouts=True,
            ),
            REVIEWER,
        )
    )

    validate_error(
        api.clear_investigation(
            investigation["id"],
            fac.clear_payload(finding="I opened it and I say it is fine"),
            REVIEWER,
        ),
        err.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    validate_error(
        api.substantiate_investigation(
            investigation["id"],
            fac.substantiate_payload(finding="I opened it and I say it is bad"),
            REVIEWER,
        ),
        err.ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    cleared = validate_success(
        api.clear_investigation(
            investigation["id"],
            fac.clear_payload(finding="Independent review found no violation"),
            REVIEWER_ALT,
        )
    )
    assert cleared["state"] == INVESTIGATION_CLEARED
    assert cleared["resolved_by_user_id"] == "reviewer-r2"

    reloaded = refresh_creator(api, creator["id"])
    assert reloaded["active_strike_count"] == 0
    assert reloaded["payout_state"] == PAYOUT_STATE_ACCRUING


def test_the_reviewer_who_rated_a_clip_may_not_decide_its_appeal(api):
    """The rater is refused and a colleague's decision restores the clip.

    Design: Corner/rbac/last_rater_cannot_decide_the_appeal_of_that_rating
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
                requested_rating=RATING_GREEN,
                statement_text="The footage is licensed and I hold the invoice.",
            ),
            make_creator_headers(creator["id"]),
        )
    )
    get_success_data(api.start_appeal_review(appeal["id"], REVIEWER))

    validate_error(
        api.decide_appeal(
            appeal["id"],
            fac.decide_appeal_payload("UPHELD", rationale="My own rating was wrong"),
            REVIEWER,
        ),
        err.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    assert validate_success(api.get_appeal(appeal["id"], REVIEWER))["state"] == (
        APPEAL_UNDER_REVIEW
    )

    decided = validate_success(
        api.decide_appeal(
            appeal["id"],
            fac.decide_appeal_payload(
                "UPHELD", rationale="Licence evidence is sufficient"
            ),
            make_reviewer_headers("reviewer-d2"),
        )
    )
    assert decided["state"] == APPEAL_UPHELD
    assert decided["decided_by_user_id"] == "reviewer-d2"

    reloaded = validate_success(api.get_content_item(item["id"], REVIEWER))
    assert reloaded["suitability_rating"] == RATING_GREEN
    assert reloaded["rating_source"] == RATING_SOURCE_APPEAL
    assert reloaded["last_rated_by_user_id"] is None
