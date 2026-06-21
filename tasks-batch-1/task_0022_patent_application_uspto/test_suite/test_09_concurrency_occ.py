"""Optimistic concurrency on the two version-guarded endpoints (PRD §2.8):
pay-issue-fee and convert-provisional-to-utility. A mismatched
expected_application_version is rejected with ERR_STALE_VERSION (412).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_applicant_headers,
    set_clock,
    setup_application_in_allowed, setup_provisional_filed,
    get_application,
    create_pay_issue_fee_payload, create_convert_provisional_payload,
    issue_fee_cents,
)


# =============================================================================
# Corner / cross_cutting_complexity_layers / occ_stale_version_pay_issue_fee_rejected
# =============================================================================

def test_pay_issue_fee_stale_version_rejected(api):
    """Pay-issue-fee with expected_application_version off-by-one (stale)
    returns ERR_STALE_VERSION (HTTP 412); nothing is mutated.

    PRD §2.8: "Each request body must include `expected_application_version`
    as a non-optional integer field, and if that value does not equal the
    target application's current `version` at the moment the server
    evaluates the request, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412) and no row is mutated."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_pay_issue_fee_rejected
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application = setup_application_in_allowed(
        entity_size="LARGE", application_type="UTILITY",
    )
    correct_version = get_application(application["id"], applicant)["version"]
    stale_version = correct_version - 1

    res = api.pay_issue_fee(
        application["id"],
        create_pay_issue_fee_payload(
            amount_cents=issue_fee_cents("UTILITY", "LARGE"),  # 120000
            expected_application_version=stale_version,
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)

    # PRD §2.8 explicitly: "no row is mutated".
    app_after = get_application(application["id"], applicant)
    assert app_after["status"] == "ALLOWED", (
        f"Application status must remain ALLOWED after stale-version rejection, "
        f"got {app_after['status']}"
    )
    assert app_after["version"] == correct_version, (
        f"Application.version must be unchanged after rejected pay-issue-fee, "
        f"was {correct_version}, now {app_after['version']}"
    )


# =============================================================================
# Corner / cross_cutting_complexity_layers / occ_stale_version_convert_provisional_rejected
# =============================================================================

def test_convert_provisional_stale_version_rejected(api):
    """Convert-provisional-to-utility with expected_application_version
    off-by-one returns ERR_STALE_VERSION (HTTP 412); nothing is mutated.

    PRD §2.8: "Each request body must include `expected_application_version`
    as a non-optional integer field, and if that value does not equal the
    target application's current `version` at the moment the server
    evaluates the request, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412) and no row is mutated."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_convert_provisional_rejected
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, prov = setup_provisional_filed(entity_size="LARGE")
    correct_version = prov["version"]
    stale_version = correct_version - 1

    res = api.convert_provisional(
        prov["id"],
        create_convert_provisional_payload(
            title="Stale conv", claim_count=15, independent_claim_count=3,
            expected_application_version=stale_version,
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)

    src_after = get_application(prov["id"], applicant)
    assert src_after["status"] == "FILED", (
        f"Provisional must remain FILED after rejected conversion, "
        f"got {src_after['status']}"
    )
    assert src_after["version"] == correct_version
