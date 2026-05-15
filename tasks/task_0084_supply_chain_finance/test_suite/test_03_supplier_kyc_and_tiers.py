"""Supplier onboarding, KYC/AML, multi-tier topology (PRD §3.2).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_aml_in_range,
    assert_supplier,
    create_supplier_payload,
    is_iso8601_timestamp,
    kyc_pass_supplier,
    kyc_supplier_payload,
    register_supplier,
    setup_active_supplier,
    validate_error,
    validate_success,
)


def test_onboard_tier1_supplier_starts_active_kyc_not_run(
    api, platform_admin_headers,
):
    """PRD §3.2: "A new supplier starts with status of ACTIVE,
    kyc_status of NOT_RUN, kyc_completed_at of null, and aml_risk_score
    of 0.00."
    """
    res = api.create_supplier(create_supplier_payload(tier_to_core=1),
                              platform_admin_headers)
    supplier = validate_success(res, expected_status=201)
    assert_supplier(supplier)
    assert supplier["status"] == "ACTIVE"
    assert supplier["kyc_status"] == "NOT_RUN"
    assert supplier.get("kyc_completed_at") in (None, "")
    assert float(supplier["aml_risk_score"]) == 0.00
    assert supplier["tier_to_core"] == 1


def test_tier1_supplier_has_null_parent(
    api, platform_admin_headers,
):
    """PRD §3.2: "Tier-1 suppliers carry a null parent."
    """
    res = api.create_supplier(create_supplier_payload(tier_to_core=1),
                              platform_admin_headers)
    supplier = validate_success(res, expected_status=201)
    assert supplier.get("parent_supplier_id") in (None, "")


def test_tier2_supplier_requires_parent(api, platform_admin_headers):
    """PRD §3.2: "A supplier with tier_to_core of 2 or more must declare
    a parent_supplier_id pointing to the upstream supplier whose
    extended credit ultimately unlocks the descendant."
    """
    payload = create_supplier_payload(tier_to_core=2)
    payload.pop("parent_supplier_id", None)
    res = api.create_supplier(payload, platform_admin_headers)
    # Two-reader test: a faithful implementer could report this as an
    # invalid request via ERR_REFERENCED_NOT_FOUND (since a missing
    # parent id is referentially invalid). Per PRD §2.4 the validation
    # ladder runs existence after auth; here the body field is missing
    # which is closer to a request-shape problem. PRD does not pin a
    # specific error_id for this case, so we accept any 4xx.
    assert res.status_code >= 400, (
        "Tier-2 supplier without parent_supplier_id must not be accepted "
        "per PRD §3.2 'must declare a parent_supplier_id'."
    )


def test_tier_above_max_extension_tier_rejected(
    api, platform_admin_headers,
):
    """PRD §3.2: "the maximum allowed tier is the MAX_EXTENSION_TIER
    system constant, which is currently four."
    """
    parent = register_supplier(tier_to_core=1)
    payload = create_supplier_payload(tier_to_core=5,
                                      parent_supplier_id=parent["id"])
    res = api.create_supplier(payload, platform_admin_headers)
    # PRD §5 catalogues ERR_TIER_TOO_DEEP. Two-reader test: a faithful
    # implementer may treat this as either an at-creation block or a
    # later upload-time block. We assert that creation either fails
    # with ERR_TIER_TOO_DEEP or that the resulting row is unusable; the
    # safest stricter form is to require ERR_TIER_TOO_DEEP at creation
    # because PRD §3.3 says the upload uses the supplier's stored tier
    # and "currently four" is the cap.
    validate_error(res, ApiErrorId.ERR_TIER_TOO_DEEP.value)


def test_kyc_pass_updates_status_and_stamps_completed_at(
    api, compliance_officer_headers,
):
    """PRD §3.2: "A successful pass updates kyc_status to PASSED and
    stamps kyc_completed_at with the current UTC timestamp."
    """
    s = register_supplier(tier_to_core=1)
    res = api.kyc_supplier(
        s["id"], kyc_supplier_payload("PASSED", 0.05),
        compliance_officer_headers,
    )
    updated = validate_success(res)
    assert updated["kyc_status"] == "PASSED"
    assert is_iso8601_timestamp(updated.get("kyc_completed_at", "")), (
        "kyc_completed_at must be stamped on PASS"
    )
    assert abs(float(updated["aml_risk_score"]) - 0.05) < 1e-9


def test_kyc_failed_cascades_supplier_to_blacklisted(
    api, compliance_officer_headers,
):
    """PRD §3.2: "If the recorded kyc_status is FAILED ... the
    supplier's status is cascaded to BLACKLISTED."
    """
    s = register_supplier(tier_to_core=1)
    res = api.kyc_supplier(
        s["id"], kyc_supplier_payload("FAILED", 0.10),
        compliance_officer_headers,
    )
    updated = validate_success(res)
    assert updated["kyc_status"] == "FAILED"
    assert updated["status"] == "BLACKLISTED"


def test_blacklisted_supplier_cannot_register_receivable(api):
    """PRD §3.2: "A blacklisted supplier is rejected with
    ERR_SUPPLIER_BLACKLISTED on any further mutating endpoint."

    Cause the blacklist by recording KYC FAILED, then attempt a
    receivable registration (an entity-backed mutating endpoint for
    SupplierUser).
    """
    from test_helpers import (
        create_receivable_payload,
        make_supplier_headers,
        register_supplier,
        setup_confirmed_payable_confirmation,
    )
    bundle = setup_confirmed_payable_confirmation()
    # KYC fail the bundle's supplier.
    fail_res = api.kyc_supplier(
        bundle["supplier"]["id"], kyc_supplier_payload("FAILED", 0.10),
        compliance_officer_headers,
    ) if False else None  # placeholder: use the real ComplianceOfficer
    # Use the ComplianceOfficer headers from TEST_USERS — opaque so the
    # shared constant is canonical (PRD §2.1).
    from test_helpers import TEST_USERS
    fail_res = api.kyc_supplier(
        bundle["supplier"]["id"], kyc_supplier_payload("FAILED", 0.10),
        TEST_USERS["compliance_officer_headers"],
    )
    blacklisted = validate_success(fail_res)
    assert blacklisted["status"] == "BLACKLISTED"
    # Now try registering a receivable as the (now blacklisted) supplier.
    payload = create_receivable_payload(
        confirmation_id=bundle["confirmation"]["id"],
    )
    res = api.create_receivable(
        payload, make_supplier_headers(bundle["supplier"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_SUPPLIER_BLACKLISTED.value)


def test_kyc_completed_at_is_initially_null_then_set_on_pass(
    api, compliance_officer_headers,
):
    """PRD §3.2: "kyc_completed_at of null ... A successful pass updates
    kyc_status to PASSED and stamps kyc_completed_at with the current
    UTC timestamp."
    """
    s = register_supplier(tier_to_core=1)
    assert s.get("kyc_completed_at") in (None, "")
    updated = kyc_pass_supplier(s, aml_risk_score=0.10)
    assert is_iso8601_timestamp(updated["kyc_completed_at"])


def test_aml_risk_score_clamped_to_unit_interval(
    api, compliance_officer_headers,
):
    """PRD §3.2: "aml_risk_score (a continuous value in the closed
    interval from 0.00 to 1.00, rounded to two decimal places)."
    """
    s = register_supplier(tier_to_core=1)
    res = api.kyc_supplier(
        s["id"], kyc_supplier_payload("PASSED", 0.50),
        compliance_officer_headers,
    )
    updated = validate_success(res)
    assert_aml_in_range(updated)
