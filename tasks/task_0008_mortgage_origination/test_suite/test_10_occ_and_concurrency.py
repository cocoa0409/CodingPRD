"""Optimistic Concurrency Control on the two endpoints that take
`expected_application_version`: POST /rate-locks and POST /disclosures.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_rate_lock_payload,
    create_disclosure_payload,
    setup_prequalified_loan_application,
    TEST_USERS,
    ApiErrorId,
)


# =============================================================================
# Queue B — Corner
# =============================================================================

def test_occ_stale_application_version_blocks_ratelock_create(api, lo_headers):
    """PRD §2.5: "Creating a new rate lock against a loan application requires
    the request body to carry `expected_application_version` as a non-optional
    field, set to the `version` the client last observed on the loan
    application. If the loan application's current `version` has advanced —
    for example, because another writer created a different rate lock that
    legitimately superseded the prior `ACTIVE` lock and thereby bumped the
    application's `version` — the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_application_version_blocks_ratelock_create
    """
    applicant, app = setup_prequalified_loan_application(
        applicant_overrides={
            "full_name": "OC",
            "email": "oc.rl@test.com",
            "ssn_last4": "1400",
            "annual_income_cents": 7_726_104,
        },
    )
    stale_version = app["version"]

    # First create succeeds and bumps the application version.
    validate_success(
        api.create_rate_lock(
            create_rate_lock_payload(
                app["id"], stale_version, locked_rate_bps=625, lock_term_days=30
            ),
            lo_headers,
        ),
        201,
    )
    # Second create with the SAME (now stale) expected version → 412.
    res = api.create_rate_lock(
        create_rate_lock_payload(
            app["id"], stale_version, locked_rate_bps=650, lock_term_days=30
        ),
        lo_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)


def test_occ_stale_application_version_blocks_disclosure_create(api, lo_headers):
    """PRD §2.5: "Likewise, creating a new disclosure requires
    `expected_application_version` to match the loan application's current
    `version`; a stale value yields the same `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_application_version_blocks_disclosure_create
    """
    applicant, app = setup_prequalified_loan_application(
        applicant_overrides={
            "full_name": "OD",
            "email": "od.disc@test.com",
            "ssn_last4": "1410",
            "annual_income_cents": 7_726_104,
        },
    )
    stale_version = app["version"]

    # Create a rate lock to bump application version.
    validate_success(
        api.create_rate_lock(
            create_rate_lock_payload(
                app["id"], stale_version, locked_rate_bps=687, lock_term_days=30
            ),
            lo_headers,
        ),
        201,
    )

    # Disclosure create with the stale version → 412.
    res = api.create_disclosure(
        create_disclosure_payload(app["id"], "LOAN_ESTIMATE", stale_version),
        lo_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)
