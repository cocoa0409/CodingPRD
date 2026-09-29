"""Unresolvable path identifiers and unresolvable body references."""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_total_count
from test_helpers.constants import (
    METHODOLOGY_GUARANTEED_FLOOR,
    PRODUCT_ACTIVE,
)
from test_helpers.fixtures import august_period, new_creator, tips_product
from test_helpers.test_users import ADMIN, FINANCE, REVIEWER


def test_an_unknown_channel_identifier_is_not_found(api):
    """A read for an identifier no channel owns names the channel type.

    Design: Corner/entities/get_creator_unknown_id_returns_creator_not_found
    """
    new_creator(api, display_name="Ada Ads", country_code="US")

    validate_error(
        api.get_creator(NON_EXISTENT_UUID, FINANCE), err.ERR_CREATOR_NOT_FOUND, 404
    )


def test_an_unknown_tax_document_identifier_is_not_found(api):
    """A read for an identifier no tax document owns names that type.

    Design: Corner/entities/get_tax_profile_unknown_id_returns_tax_profile_not_found
    """
    new_creator(api, display_name="Ada Ads", country_code="US")

    validate_error(
        api.get_tax_profile(NON_EXISTENT_UUID, FINANCE),
        err.ERR_TAX_PROFILE_NOT_FOUND,
        404,
    )


def test_an_unknown_clip_identifier_is_not_found(api):
    """A read for an identifier no clip owns names the clip type.

    Design: Corner/entities/get_content_item_unknown_id_returns_content_item_not_found
    """
    new_creator(api, display_name="Ada Ads", country_code="US")

    validate_error(
        api.get_content_item(NON_EXISTENT_UUID, REVIEWER),
        err.ERR_CONTENT_ITEM_NOT_FOUND,
        404,
    )


def test_an_unknown_appeal_identifier_is_not_found(api):
    """A read for an identifier no appeal owns names the appeal type.

    Design: Corner/entities/get_appeal_unknown_id_returns_appeal_not_found
    """
    new_creator(api, display_name="Ada Ads", country_code="US")

    validate_error(
        api.get_appeal(NON_EXISTENT_UUID, REVIEWER), err.ERR_APPEAL_NOT_FOUND, 404
    )


def test_an_unknown_period_identifier_is_not_found(api):
    """A read for an identifier no accounting window owns names that type.

    Design: Corner/entities/get_earnings_period_unknown_id_returns_period_not_found
    """
    august_period(api)

    validate_error(
        api.get_period(NON_EXISTENT_UUID, FINANCE), err.ERR_PERIOD_NOT_FOUND, 404
    )


def test_an_unknown_statement_identifier_is_not_found(api):
    """A read for an identifier no statement owns names the statement type.

    Design: Corner/entities/get_earnings_statement_unknown_id_returns_statement_not_found
    """
    new_creator(api, display_name="Ada Ads", country_code="US")

    validate_error(
        api.get_statement(NON_EXISTENT_UUID, FINANCE), err.ERR_STATEMENT_NOT_FOUND, 404
    )


def test_an_unknown_disbursement_identifier_is_not_found(api):
    """A read for an identifier no disbursement owns names that type.

    Design: Corner/entities/get_payout_unknown_id_returns_payout_not_found
    """
    new_creator(api, display_name="Ada Ads", country_code="US")

    validate_error(
        api.get_payout(NON_EXISTENT_UUID, FINANCE), err.ERR_PAYOUT_NOT_FOUND, 404
    )


def test_an_unknown_case_identifier_is_not_found(api):
    """A read for an identifier no case owns names the case type.

    Design: Corner/entities/get_investigation_unknown_id_returns_investigation_not_found
    """
    new_creator(api, display_name="Ada Ads", country_code="US")

    validate_error(
        api.get_investigation(NON_EXISTENT_UUID, REVIEWER),
        err.ERR_INVESTIGATION_NOT_FOUND,
        404,
    )


def test_an_unknown_fund_identifier_is_not_found(api):
    """A read for an identifier no fund owns names the fund type.

    Design: Corner/entities/get_creator_fund_unknown_id_returns_fund_not_found
    """
    august_period(api)

    validate_error(
        api.get_fund(NON_EXISTENT_UUID, FINANCE), err.ERR_FUND_NOT_FOUND, 404
    )


def test_retiring_an_unknown_surface_touches_nothing(api):
    """The path identifier is resolved before any retirement is attempted.

    The surface that does exist keeps its active status.

    Design: Corner/entities/retire_unknown_revenue_product_returns_product_not_found
    """
    product = tips_product(
        api, name="Fan Tips", creator_share_bps=8000, platform_fee_bps=2000
    )

    validate_error(
        api.retire_product(NON_EXISTENT_UUID, ADMIN), err.ERR_PRODUCT_NOT_FOUND, 404
    )
    rows = assert_total_count(api.list_products(ADMIN), 1)
    assert rows[0]["id"] == product["id"]
    assert rows[0]["status"] == PRODUCT_ACTIVE


def test_publishing_against_an_unknown_owner_stores_no_clip(api):
    """A body reference to a channel that does not exist is a not-found.

    Design: Corner/entities/create_content_item_for_unknown_creator_is_body_fk_404
    """
    new_creator(api, display_name="Ada Ads", country_code="US")

    validate_error(
        api.create_content_item(
            fac.content_item_payload(
                NON_EXISTENT_UUID,
                title="Ghost Vlog",
                published_at="2026-08-01T00:00:00Z",
            ),
            ADMIN,
        ),
        err.ERR_CREATOR_NOT_FOUND,
        404,
    )
    assert_total_count(api.list_content_items(ADMIN), 0)


def test_declaring_a_fund_against_an_unknown_window_stores_no_fund(api):
    """The body reference is resolved before the fund's own constraints.

    A per-recipient cap below the guaranteed floor would be refused too, but the
    unresolvable window is reported instead and no fund is stored.

    Design: Corner/entities/create_creator_fund_for_unknown_period_is_body_fk_404
    """
    august_period(api)

    validate_error(
        api.create_fund(
            fac.fund_payload(
                NON_EXISTENT_UUID,
                name="Ghost Fund",
                methodology=METHODOLOGY_GUARANTEED_FLOOR,
                max_allocation_cents=4000,
            ),
            ADMIN,
        ),
        err.ERR_PERIOD_NOT_FOUND,
        404,
    )
    assert_total_count(api.list_funds(ADMIN), 0)


def test_an_unresolvable_surface_reference_accrues_nothing(api):
    """Ingestion resolves the channel then the surface before computing.

    The channel exists and is eligible, so the refusal names the surface, and
    the channel's ledger balance stays at zero.

    Design: Corner/entities/revenue_event_body_foreign_keys_are_all_integrity_checked
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    validate_success(api.evaluate_creator(creator["id"], FINANCE))
    august_period(api)
    tips_product(api, name="Memberships")

    validate_error(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"],
                NON_EXISTENT_UUID,
                gross_amount_cents=1000000,
                occurred_at="2026-08-05T00:00:00Z",
            ),
            FINANCE,
        ),
        err.ERR_PRODUCT_NOT_FOUND,
        404,
    )
    assert validate_success(api.get_creator(creator["id"], FINANCE))[
        "ledger_balance_cents"
    ] == 0
