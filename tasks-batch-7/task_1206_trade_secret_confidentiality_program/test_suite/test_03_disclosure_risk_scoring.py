"""Disclosure risk scoring: provisional vs final variants, tier multiplier,
clamp, endorsement routing, and the too-high rejection (PRD §3.5)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_counterparty,
    create_active_nda,
    create_obligation_payload,
    create_registered_asset,
    add_verified_measure,
    create_employee_record,
    create_submitted_disclosure,
    make_employee_headers,
    make_ip_counsel_headers,
    make_senior_counsel_headers,
    make_obligations_overdue,
    escalate_obligations,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]
SENIOR = TEST_USERS["senior_counsel_headers"]


def _drive_counterparty_to_medium(api, cp, nda):
    """Two escalated obligations -> trailing 50 -> MEDIUM tier."""
    ids = []
    for otype in ["NON_DISCLOSURE", "NON_USE"]:
        resp = api.create_obligation(
            create_obligation_payload(nda["id"], obligation_type=otype,
                                      due_at="2026-05-10T00:00:00Z"), IP
        )
        ids.append(validate_success(resp, expected_status=201)["id"])
    api.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, IP)
    api.run_sweep(IP)
    escalate_obligations(ids)


def _setup_medium_tier_disclosure(api):
    """CROWN_JEWEL asset with ADEQUATE posture (45), MEDIUM counterparty,
    ACTIVE NDA with CROWN_JEWEL ceiling, disclosure ENCRYPTED_DELIVERY SUBMITTED."""
    cp = create_counterparty(legal_name="Beta Dynamics", counterparty_type="PARTNER")
    nda = create_active_nda(
        cp["id"], template_version="t2", governing_law="CA",
        effective_date="2026-01-01T00:00:00Z", expiry_date="2027-12-31T00:00:00Z",
        survival_months=24, classification_ceiling="CROWN_JEWEL",
    )
    _drive_counterparty_to_medium(api, cp, nda)
    asset = create_registered_asset(
        title="Training-data recipe", description="model pipeline",
        classification="CROWN_JEWEL", owner_department="AI",
        exposure_estimate_cents=9000000,
    )
    add_verified_measure(asset["id"], "TECHNICAL", title="Enclave", evidence_uri="s3://ev/enc.pdf")
    add_verified_measure(asset["id"], "CONTRACTUAL", title="MSA clauses", evidence_uri="s3://ev/msa.pdf")
    emp = create_employee_record(
        full_name="Eli Researcher", email="eli@x.com", department="AI",
        role_title="Researcher", access_clearance="PRIVILEGED",
        hired_at="2026-05-01T00:00:00Z",
    )
    disc = create_submitted_disclosure(
        emp["id"], asset["id"], nda["id"],
        purpose="Co-development", marking_protocol="ENCRYPTED_DELIVERY",
        planned_disclosure_date="2026-06-01T00:00:00Z",
    )
    return cp, asset, nda, emp, disc


class TestDisclosureRiskProvisionalVsFinal:
    def test_provisional_excludes_tier_multiplier(self, api):
        """PRD §3.5: "The provisional score is the classification base — 10 for
        `INTERNAL`, 30 for `CONFIDENTIAL`, 60 for `RESTRICTED`, 90 for
        `CROWN_JEWEL` — minus the marking credit for the chosen protocol: 10 for
        `STAMPED_CONFIDENTIAL`, 0 for `ORAL_WITH_FOLLOWUP`, 20 for
        `ENCRYPTED_DELIVERY`. No counterparty tier multiplier applies at this
        stage; the result is rounded half-up to one decimal place."

        Design: Difficulty/dual_variant_calc/disclosure_risk_provisional_vs_final
        """
        _cp, _asset, _nda, _emp, disc = _setup_medium_tier_disclosure(api)
        data = validate_success(api.get_disclosure(disc["id"], IP))
        assert data["risk_score_provisional"] == pytest.approx(70.0, abs=0.01), \
            f"expected 70 (90 - 20, no tier multiplier), got {data['risk_score_provisional']}"

    def test_final_applies_multiplier_and_endorsement_gate(self, api):
        """PRD §3.5: "Approval also computes `risk_score_final`, the enforcement
        value: the classification base multiplied by the counterparty's current
        tier multiplier — 1.0 for `LOW`, 1.25 for `MEDIUM`, 1.5 for `HIGH` —
        minus the marking credit, clamped to the range 0 through 100, and
        rounded half-up to one decimal place."
        PRD §3.5: "a final score of 80 or more requires `senior_endorsed` to be
        true, otherwise `ERR_ENDORSEMENT_REQUIRED`."

        Design: Difficulty/dual_variant_calc/disclosure_risk_provisional_vs_final
        """
        _cp, _asset, _nda, _emp, disc = _setup_medium_tier_disclosure(api)
        validate_success(api.transition_disclosure(disc["id"], {"to_status": "UNDER_REVIEW"}, IP))
        err_resp = api.transition_disclosure(
            disc["id"], {"to_status": "APPROVED"}, make_ip_counsel_headers("counsel_1")
        )
        validate_error(err_resp, ApiErrorId.ERR_ENDORSEMENT_REQUIRED)
        validate_success(api.endorse_disclosure(disc["id"], make_senior_counsel_headers("senior_1")))
        data = validate_success(api.transition_disclosure(
            disc["id"], {"to_status": "APPROVED"}, make_ip_counsel_headers("counsel_1")
        ))
        assert data["status"] == "APPROVED"
        assert data["risk_score_final"] == pytest.approx(92.5, abs=0.01), \
            f"expected 92.5 (90 x 1.25 - 20), got {data['risk_score_final']}"
        assert data["risk_score_provisional"] != data["risk_score_final"]


def _setup_high_tier_disclosure(api):
    """Counterparty at trailing exactly 60 (HIGH): two ESCALATED + one
    OVERDUE-now. CROWN_JEWEL asset, ORAL_WITH_FOLLOWUP protocol."""
    cp = create_counterparty(legal_name="Gamma Sourcing", counterparty_type="CONSULTANT")
    nda = create_active_nda(
        cp["id"], template_version="t3", governing_law="NY",
        effective_date="2026-01-01T00:00:00Z", expiry_date="2027-12-31T00:00:00Z",
        survival_months=12, classification_ceiling="CROWN_JEWEL",
    )
    ids = []
    for otype in ["NON_DISCLOSURE", "NON_USE", "AUDIT_RIGHT"]:
        resp = api.create_obligation(
            create_obligation_payload(nda["id"], obligation_type=otype,
                                      due_at="2026-05-10T00:00:00Z"), IP
        )
        ids.append(validate_success(resp, expected_status=201)["id"])
    api.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, IP)
    api.run_sweep(IP)
    escalate_obligations(ids[:2])  # 2 escalated (25+25) + 1 overdue-now (10) = 60

    asset = create_registered_asset(
        title="Diffusion weights delta", description="checkpoint diff",
        classification="CROWN_JEWEL", owner_department="AI",
        exposure_estimate_cents=4000000,
    )
    add_verified_measure(asset["id"], "TECHNICAL", title="Vault storage", evidence_uri="s3://ev/v.pdf")
    add_verified_measure(asset["id"], "CONTRACTUAL", title="Consultant NDA", evidence_uri="s3://ev/c.pdf")
    emp = create_employee_record(
        full_name="Fay Scientist", email="fay@x.com", department="AI",
        role_title="Scientist", access_clearance="PRIVILEGED",
        hired_at="2026-05-01T00:00:00Z",
    )
    disc = create_submitted_disclosure(
        emp["id"], asset["id"], nda["id"],
        purpose="Audit support", marking_protocol="ORAL_WITH_FOLLOWUP",
        planned_disclosure_date="2026-06-01T00:00:00Z",
    )
    validate_success(api.transition_disclosure(disc["id"], {"to_status": "UNDER_REVIEW"}, IP))
    validate_success(api.endorse_disclosure(disc["id"], make_senior_counsel_headers("senior_1")))
    return cp, asset, nda, emp, disc


class TestDisclosureRiskClampBranch:
    def test_high_tier_counterparty_at_exactly_60(self, api):
        """PRD §2.8: "The `risk_tier` derives from the trailing variant alone:
        `LOW` below 30 points, `MEDIUM` from 30 up to but not including 60, and
        `HIGH` at 60 or more — so an index of exactly 30 is `MEDIUM` and exactly
        60 is `HIGH`."

        Design: Difficulty/combinatorial_formula/disclosure_risk_tier_multiplier_clamp_branch
        """
        cp, _asset, _nda, _emp, _disc = _setup_high_tier_disclosure(api)
        data = validate_success(api.get_counterparty(cp["id"], IP))
        assert data["exposure_index_trailing"] == 60, \
            f"expected 25+25+10 = 60, got {data['exposure_index_trailing']}"
        assert data["risk_tier"] == "HIGH", "exactly 60 must be HIGH (boundary inclusive)"

    def test_final_score_at_95_or_more_forbids_approval(self, api):
        """PRD §3.5: "a final score of 95 or more forbids approval outright with
        `ERR_DISCLOSURE_RISK_TOO_HIGH`."
        PRD §3.5: "the classification base multiplied by the counterparty's
        current tier multiplier — 1.0 for `LOW`, 1.25 for `MEDIUM`, 1.5 for
        `HIGH` — minus the marking credit, clamped to the range 0 through 100."

        Design: Difficulty/combinatorial_formula/disclosure_risk_tier_multiplier_clamp_branch
        """
        _cp, _asset, _nda, _emp, disc = _setup_high_tier_disclosure(api)
        resp = api.transition_disclosure(
            disc["id"], {"to_status": "APPROVED"}, make_ip_counsel_headers("counsel_1")
        )
        validate_error(resp, ApiErrorId.ERR_DISCLOSURE_RISK_TOO_HIGH)
        data = validate_success(api.get_disclosure(disc["id"], IP))
        assert data["status"] == "UNDER_REVIEW", \
            "clamp(90 x 1.5 - 0, 0, 100) == 100 >= 95 forbids approval despite endorsement"
