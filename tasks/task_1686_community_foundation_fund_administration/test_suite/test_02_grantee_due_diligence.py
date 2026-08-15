"""Grantee registration, due-diligence freshness, and the 12-month window."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    create_grantee_payload,
    create_active_fund,
    create_grant_in_review,
    make_officer_headers,
    set_logical_clock,
    assert_grantee,
    ApiErrorId,
    TEST_USERS,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_grantee_tax_id_unique(api):
    """PRD §3.6: "Legal names and tax identifiers are each unique; a malformed
    or duplicated registration is rejected with `ERR_FIELD_CONSTRAINT` or
    `ERR_UNIQUENESS_VIOLATION` respectively."

    Design: Corner/entities/grantee_tax_id_uniqueness_enforced
    """
    validate_success(
        api.create_grantee(create_grantee_payload(tax_id="111222333"), COMPLIANCE), 201
    )
    resp = api.create_grantee(
        create_grantee_payload(tax_id="111222333", irs_subsection="GOVERNMENT"),
        COMPLIANCE,
    )
    validate_error(resp, ApiErrorId.ERR_UNIQUENESS_VIOLATION)


def test_grantee_expenditure_responsibility_flag(api):
    """PRD §3.6: "Registration computes `expenditure_responsibility_required`,
    which is true whenever the subsection is neither `C3_501` nor `GOVERNMENT`,
    and starts the grantee at `due_diligence_status` `UNVETTED`."

    Design: Corner/entities/grantee_er_flag_computed_from_subsection
    """
    pf = validate_success(
        api.create_grantee(
            create_grantee_payload(irs_subsection="C3_PRIVATE_FOUNDATION"), COMPLIANCE
        ),
        201,
    )
    pc = validate_success(
        api.create_grantee(create_grantee_payload(irs_subsection="C3_501"), COMPLIANCE),
        201,
    )
    assert_grantee(pf)
    assert pf["expenditure_responsibility_required"] is True
    assert pc["expenditure_responsibility_required"] is False
    assert pf["due_diligence_status"] == "UNVETTED"


def _setup_clearance_window(api):
    """Fund ACTIVE with 50000 cash; grantee CLEARED at 2026-01-15; grant of
    1000.00 in COMPLIANCE_REVIEW claimed by officer co-1."""
    set_logical_clock("2026-01-15T00:00:00Z")
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=50000.00)
    fund_id = bundle["fund"]["id"]
    grantee = validate_success(
        api.create_grantee(create_grantee_payload(), COMPLIANCE), 201
    )
    validate_success(api.begin_grantee_review(grantee["id"], COMPLIANCE))
    grantee = validate_success(api.clear_grantee(grantee["id"], COMPLIANCE))
    grant = create_grant_in_review(
        fund_id=fund_id, grantee_id=grantee["id"], amount=1000.00, claimer_id="co-1"
    )
    return fund_id, grantee, grant


def test_approve_succeeds_one_second_before_clearance_expiry(api):
    """PRD §3.6: "Clearance is perishable: when a clock advance carries the
    current time to twelve months or more past `cleared_at`, the grantee lapses
    automatically from `CLEARED` to `EXPIRED`, and an expired grantee must pass
    through review again before it can receive anything."

    Design: Difficulty/resource_temporal_overlap/grantee_clearance_12month_expiry_window
    """
    _, grantee, grant = _setup_clearance_window(api)
    # One second before the twelve-month mark: clearance still fresh.
    set_logical_clock("2027-01-14T23:59:59Z")
    resp = api.approve_grant(
        grant["id"], {}, make_officer_headers("ComplianceOfficer", "co-2")
    )
    data = validate_success(resp, 200)
    assert data["status"] == "APPROVED"
    refreshed = validate_success(api.get_grantee(grantee["id"], COMPLIANCE))
    assert refreshed["due_diligence_status"] == "CLEARED"


def test_grantee_expires_at_twelve_month_mark_and_grant_untouched(api):
    """PRD §3.6: "Clearance is perishable: when a clock advance carries the
    current time to twelve months or more past `cleared_at`, the grantee lapses
    automatically from `CLEARED` to `EXPIRED`, and an expired grantee must pass
    through review again before it can receive anything."
    PRD §3.6: "Approval moves the grant to `APPROVED`, stamps `decided_at`, and
    records the approving officer's identity for the downstream segregation
    check."

    Design: Difficulty/resource_temporal_overlap/grantee_clearance_12month_expiry_window
    """
    _, grantee, grant = _setup_clearance_window(api)
    set_logical_clock("2027-01-14T23:59:59Z")
    approved = validate_success(
        api.approve_grant(
            grant["id"], {}, make_officer_headers("ComplianceOfficer", "co-2")
        ),
        200,
    )
    assert approved["status"] == "APPROVED"
    # Past the exact twelve-month mark the grantee auto-expires...
    set_logical_clock("2027-01-15T00:00:01Z")
    expired = validate_success(api.get_grantee(grantee["id"], COMPLIANCE))
    assert expired["due_diligence_status"] == "EXPIRED"
    # ...while the already-approved grant is not mutated by the expiry.
    grant_after = validate_success(api.get_grant(grant["id"], COMPLIANCE))
    assert grant_after["status"] == "APPROVED"
