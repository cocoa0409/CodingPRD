"""Pagination, shape and version checks run ahead of everything else."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_total_count
from test_helpers.constants import FORM_W8BEN, PERIOD_OPEN, PRODUCT_RETIRED
from test_helpers.fixtures import new_creator, subs_product
from test_helpers.test_users import ADMIN, FINANCE, make_creator_headers


def test_a_page_size_outside_its_bounds_is_refused(api):
    """Zero and one above the maximum are refused; the maximum itself is not.

    Design: Corner/validations/pagination_limit_of_zero_is_rejected
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")

    validate_error(
        api.list_creators(ADMIN, {"limit": 0}), err.ERR_INVALID_PAGINATION, 400
    )
    validate_error(
        api.list_creators(ADMIN, {"limit": 101}), err.ERR_INVALID_PAGINATION, 400
    )

    rows, meta = validate_paginated(
        api.list_creators(ADMIN, {"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(rows) == 1
    assert rows[0]["id"] == creator["id"]


def test_the_page_size_check_runs_before_the_path_lookup(api):
    """A bad page size on an unknown channel still reports the page size.

    Design: Corner/validations/pagination_check_outranks_unknown_path_id_resolution
    """
    validate_error(
        api.list_ledger_entries(NON_EXISTENT_UUID, FINANCE, {"limit": 0}),
        err.ERR_INVALID_PAGINATION,
        400,
    )


def test_a_missing_field_is_reported_before_an_unknown_reference(api):
    """The absent timestamp outranks the unknown channel in the same body.

    Design: Corner/validations/missing_required_field_outranks_unknown_body_foreign_key
    """
    product = subs_product(api, name="Memberships")

    validate_error(
        api.create_revenue_event(
            fac.revenue_event_payload(
                NON_EXISTENT_UUID,
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


def test_a_malformed_field_is_reported_before_the_retired_state(api):
    """A quoted number is refused on shape, not on the surface's state.

    Design: Corner/validations/field_shape_check_outranks_retired_product_state
    """
    product = subs_product(api, name="Memberships")
    get_success_data(api.retire_product(product["id"], ADMIN))

    validate_error(
        api.patch_product(product["id"], {"creator_share_bps": "6000"}, ADMIN),
        err.ERR_INVALID_FIELD_VALUE,
        422,
    )
    rows = get_success_data(api.list_products(ADMIN))
    assert rows[0]["status"] == PRODUCT_RETIRED
    assert rows[0]["creator_share_bps"] == 7000


def test_a_stale_version_is_reported_before_a_country_mismatch(api):
    """The optimistic check runs ahead of the cross-field country rule.

    Design: Corner/validations/stale_creator_version_outranks_tax_country_mismatch
    """
    creator = new_creator(api, display_name="Ada Ads", country_code="US")
    evaluated = validate_success(api.evaluate_creator(creator["id"], FINANCE))

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
        err.ERR_STALE_CREATOR_VERSION,
        412,
    )
    assert validate_success(api.get_creator(creator["id"], FINANCE))["version"] == (
        evaluated["version"]
    )
    assert_total_count(
        api.list_tax_profiles(FINANCE, {"creator_id": creator["id"]}), 0
    )


def test_an_accounting_window_must_have_positive_length(api):
    """Degenerate and reversed windows are refused; one second is enough.

    Design: Corner/validations/zero_length_earnings_period_window_is_rejected
    """
    validate_error(
        api.create_period(
            fac.period_payload(
                label="2026-08-degenerate",
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-08-01T00:00:00Z",
            ),
            ADMIN,
        ),
        err.ERR_PERIOD_WINDOW_INVALID,
        422,
    )
    validate_error(
        api.create_period(
            fac.period_payload(
                label="2026-08-reversed",
                period_start="2026-09-01T00:00:00Z",
                period_end="2026-08-01T00:00:00Z",
            ),
            ADMIN,
        ),
        err.ERR_PERIOD_WINDOW_INVALID,
        422,
    )

    accepted = validate_success(
        api.create_period(
            fac.period_payload(
                label="2026-08-onesecond",
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-08-01T00:00:01Z",
            ),
            ADMIN,
        ),
        201,
    )
    assert accepted["status"] == PERIOD_OPEN
    assert accepted["label"] == "2026-08-onesecond"
    assert_total_count(api.list_periods(ADMIN), 1)
