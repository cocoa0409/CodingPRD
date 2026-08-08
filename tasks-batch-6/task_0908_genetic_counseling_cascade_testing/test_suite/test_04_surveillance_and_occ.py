"""Manual surveillance-plan creation under optimistic concurrency, and referral closure.

Translates queue-B corner instances from the cross_cutting_complexity_layers and
state_machines sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, make_counselor_headers,
    create_surveillance_plan_payload, create_referral_payload,
    setup_disclosed_case, create_family, create_counselor, create_case_payload,
)


def _disclosed_vus_moderate():
    """Proband disclosed VUS with prior 0.15 (MODERATE); case stays DISCLOSED since
    VUS is not actionable (no auto plan)."""
    return setup_disclosed_case(
        members=[{"relationship": "SIBLING", "degree": 1, "affected": True,
                  "age_of_onset": 45}],
        classification="VUS", ancestry="EUROPEAN", covered_sessions=2)


def test_occ_surveillance_plan_supersede_success(api):
    """PRD 2.10: "A request to create a surveillance plan must carry
    expected_counseling_case_version, a non-optional field holding the version of the
    CounselingCase the client last observed." PRD 3.9: "The plan copies the case's
    risk_tier, derives screening_interval_months from that tier (6 months for HIGH, 12
    for MODERATE, 24 for LOW), and is created ACTIVE." PRD 3.6: "A VUS result does not
    change management, so the residual risk equals the case's prior_risk_pct unchanged."

    Design: Corner/cross_cutting_complexity_layers/occ_surveillance_plan_supersede_success
    """
    ctx = _disclosed_vus_moderate()
    hdr = make_counselor_headers(ctx["counselor_id"])
    assert ctx["case"]["residual_risk_pct"] == pytest.approx(0.15, abs=1e-6)
    res = api.create_surveillance_plan(
        create_surveillance_plan_payload(ctx["case_id"], ctx["case"]["version"],
                                         modalities=["BREAST_MRI"]), hdr)
    plan = validate_success(res, 201)
    assert plan["status"] == "ACTIVE"
    assert plan["risk_tier"] == "MODERATE"
    assert plan["screening_interval_months"] == 12


def test_occ_surveillance_plan_stale_version_rejected(api):
    """PRD 2.10: "If that value does not equal the case's current version, the create
    is rejected with ERR_STALE_VERSION and HTTP 412." PRD 3.9: "Creating a new active
    plan supersedes the prior active plan for the same case, moving that earlier plan
    from ACTIVE to SUPERSEDED, and the case advances from DISCLOSED to SURVEILLANCE ...
    and increments the case version."

    Design: Corner/cross_cutting_complexity_layers/occ_surveillance_plan_stale_version_rejected
    """
    ctx = _disclosed_vus_moderate()
    hdr = make_counselor_headers(ctx["counselor_id"])
    stale_version = ctx["case"]["version"]
    # First create succeeds and bumps the case version.
    validate_success(
        api.create_surveillance_plan(
            create_surveillance_plan_payload(ctx["case_id"], stale_version,
                                             modalities=["BREAST_MRI"]), hdr), 201)
    # Second create still carries the pre-bump version.
    res = api.create_surveillance_plan(
        create_surveillance_plan_payload(ctx["case_id"], stale_version,
                                         modalities=["COLONOSCOPY"]), hdr)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_referral_manual_create_then_close_completed(api):
    """PRD 3.9: "A counselor creates a referral by naming the counseling_case_id, the
    specialty ... and the reason ... It is created PENDING. Closing a pending referral
    with an outcome moves it to COMPLETED or CANCELLED".

    Design: Corner/state_machines/referral_manual_create_then_close_completed
    """
    fam = create_family(name="Kindred O")
    gc = create_counselor()
    hdr = make_counselor_headers(gc["id"])
    case = validate_success(
        api.create_case(create_case_payload(fam["id"], gc["id"], covered_sessions=1), hdr), 201)
    ref = validate_success(
        api.create_referral(
            create_referral_payload(case["id"], specialty="BREAST_SURGERY",
                                    reason="Prophylactic consult"), hdr), 201)
    assert ref["status"] == "PENDING"
    closed = validate_success(api.close_referral(ref["id"], {"outcome": "COMPLETED"}, hdr), 200)
    assert closed["status"] == "COMPLETED"
