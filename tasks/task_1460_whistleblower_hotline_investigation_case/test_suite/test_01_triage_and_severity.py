"""Triage, severity scoring bands, rejection paths, and immediate consistency."""
from test_helpers import (
    ApiErrorId,
    create_case,
    create_case_payload,
    create_staff,
    create_triage_payload,
    make_admin_headers,
    make_intake_headers,
    make_investigator_headers,
    make_reporter_headers,
    setup_case_triaged,
    setup_standard_staff,
    triage_case,
    validate_error,
    validate_success,
    api_client,
)


class TestSeverityScoreBandEdge:
    """Difficulty: severity_score_band_edge_mode_a — boundary at 75 (CRITICAL vs HIGH)."""

    def test_score_75_hits_critical_band_with_sla_30(self, api):
        """PRD §3.3: "The integer score maps to a band: at least 75 is `CRITICAL`;
        55 through 74 inclusive is `HIGH`" and "`CRITICAL` 30 days, `HIGH` 60 days".

        Design: Difficulty/combinatorial_formula/severity_score_band_edge_mode_a
        """
        staff = setup_standard_staff()
        case, _ = create_case()
        # FRAUD(30) + EXECUTIVE(25) + HIGH_1M(20) + NONE(0) == 75 -> CRITICAL
        resp = api.triage_case(case["id"], create_triage_payload(
            confirmed_category="FRAUD", subject_seniority="EXECUTIVE",
            financial_exposure_band="HIGH_1M", reporter_vulnerability="NONE",
            triage_decision="PROCEED",
        ), staff["h_int"])
        data = validate_success(resp)
        assert data["severity"] == "CRITICAL", f"score 75 must be CRITICAL, got {data['severity']}"
        assert data["sla_days"] == 30, f"CRITICAL SLA must be 30, got {data['sla_days']}"

    def test_score_70_stays_high_band_with_sla_60(self, api):
        """PRD §3.3: "at least 75 is `CRITICAL`; 55 through 74 inclusive is `HIGH`"
        and "`HIGH` 60 days".

        Design: Difficulty/combinatorial_formula/severity_score_band_edge_mode_a
        """
        staff = setup_standard_staff()
        case, _ = create_case(channel="PHONE", category="SAFETY",
                              description="Allegation of unsafe loading dock practice",
                              region="SOUTH")
        # SAFETY(25) + EXECUTIVE(25) + HIGH_1M(20) + NONE(0) == 70 -> HIGH
        resp = api.triage_case(case["id"], create_triage_payload(
            confirmed_category="SAFETY", subject_seniority="EXECUTIVE",
            financial_exposure_band="HIGH_1M", reporter_vulnerability="NONE",
            triage_decision="PROCEED",
        ), staff["h_int"])
        data = validate_success(resp)
        assert data["severity"] == "HIGH", f"score 70 must be HIGH, got {data['severity']}"
        assert data["sla_days"] == 60, f"HIGH SLA must be 60, got {data['sla_days']}"


class TestSeverityInteriorBands:
    def test_fraud_staff_none_none_is_medium_sla_90(self, api):
        """PRD §3.3: "35 through 54 inclusive is `MEDIUM`" and "`MEDIUM` 90 days".
        FRAUD(30)+STAFF(5)+NONE(0)+NONE(0)=35.

        Design: Corner/calculations/severity_medium_and_low_bands
        """
        staff = setup_standard_staff()
        case, _ = create_case()
        resp = api.triage_case(case["id"], create_triage_payload(), staff["h_int"])
        data = validate_success(resp)
        assert data["severity"] == "MEDIUM"
        assert data["sla_days"] == 90

    def test_other_staff_none_none_is_low_sla_120(self, api):
        """PRD §3.3: "34 or less is `LOW`" and "`LOW` 120 days".
        OTHER(10)+STAFF(5)+NONE(0)+NONE(0)=15.

        Design: Corner/calculations/severity_medium_and_low_bands
        """
        staff = setup_standard_staff()
        case, _ = create_case(channel="PHONE", category="OTHER",
                              description="Allegation of minor policy lapse",
                              region="SOUTH")
        resp = api.triage_case(case["id"], create_triage_payload(confirmed_category="OTHER"), staff["h_int"])
        data = validate_success(resp)
        assert data["severity"] == "LOW"
        assert data["sla_days"] == 120


class TestImmediateConsistency:
    def test_triage_response_carries_computed_severity(self, api):
        """PRD §2.4: "every mutation in this system is applied atomically within the
        request that triggered it". PRD §3.3: "at least 75 is `CRITICAL`".

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        staff = setup_standard_staff()
        case, _ = create_case()
        resp = api.triage_case(case["id"], create_triage_payload(
            confirmed_category="FRAUD", subject_seniority="EXECUTIVE",
            financial_exposure_band="HIGH_1M", reporter_vulnerability="NONE",
        ), staff["h_int"])
        data = validate_success(resp)
        assert data["severity"] == "CRITICAL"
        assert data["sla_days"] == 30

    def test_reread_matches_mutation_response(self, api):
        """PRD §2.4: "every mutation in this system is applied atomically within the
        request that triggered it, and deferred time-driven effects are applied
        synchronously by the clock sweep".

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        staff = setup_standard_staff()
        case, _ = create_case()
        resp = api.triage_case(case["id"], create_triage_payload(
            confirmed_category="FRAUD", subject_seniority="EXECUTIVE",
            financial_exposure_band="HIGH_1M", reporter_vulnerability="NONE",
        ), staff["h_int"])
        first = validate_success(resp)
        resp2 = api.get_case(case["id"], staff["h_int"])
        second = validate_success(resp2)
        assert second["severity"] == first["severity"]
        assert second["sla_days"] == first["sla_days"]


class TestTriageRejectAsDuplicate:
    def test_reject_with_duplicate_link_stores_target(self, api):
        """PRD §3.3: "When the rejection is because the report duplicates an existing
        case, the payload supplies `duplicate_of_case_id`, which is stored on the
        rejected case".

        Design: Corner/state_machines/triage_reject_as_duplicate_links_cases
        """
        staff = setup_standard_staff()
        case1, _ = create_case(description="Allegation of expense fraud case one")
        triage_case(case1["id"], staff["h_int"])
        case2, _ = create_case(channel="PHONE", description="Same fraud reported a second time")
        resp = api.triage_case(case2["id"], create_triage_payload(
            triage_decision="REJECT", reject_reason="Duplicate of earlier report",
            duplicate_of_case_id=case1["id"],
        ), staff["h_int"])
        data = validate_success(resp)
        assert data["status"] == "REJECTED"
        assert data["duplicate_of_case_id"] == case1["id"]

    def test_reject_leaves_severity_null(self, api):
        """PRD §3.3: "Until triage, both `severity` and `confirmed_category` are null."
        and "On `REJECT`, the case moves to `REJECTED`" (no severity computation).

        Design: Corner/state_machines/triage_reject_as_duplicate_links_cases
        """
        staff = setup_standard_staff()
        case1, _ = create_case()
        triage_case(case1["id"], staff["h_int"])
        case2, _ = create_case(channel="PHONE", description="Same fraud reported a second time")
        resp = api.triage_case(case2["id"], create_triage_payload(
            triage_decision="REJECT", reject_reason="Duplicate of earlier report",
            duplicate_of_case_id=case1["id"],
        ), staff["h_int"])
        data = validate_success(resp)
        assert data["severity"] is None, "REJECT path must not compute severity"

    def test_duplicate_target_terminal_rejected(self, api):
        """PRD §3.3: "the referenced case must exist and must not be in a terminal
        state (`CLOSED`, `REJECTED`, or `WITHDRAWN`), otherwise the request fails
        with `ERR_DUPLICATE_TARGET_INVALID`".

        Design: Corner/state_machines/triage_reject_duplicate_terminal_target_rejected
        """
        staff = setup_standard_staff()
        case_a, _ = create_case(category="OTHER", description="Out of scope complaint about payroll",
                                region="WEST")
        triage_case(case_a["id"], staff["h_int"], confirmed_category="OTHER",
                    subject_seniority="UNKNOWN", triage_decision="REJECT",
                    reject_reason="Out of scope")
        case_b, _ = create_case(channel="PHONE", category="OTHER",
                                description="Repeat of the same payroll complaint", region="WEST")
        resp = api.triage_case(case_b["id"], create_triage_payload(
            confirmed_category="OTHER", subject_seniority="UNKNOWN",
            triage_decision="REJECT", reject_reason="Duplicate",
            duplicate_of_case_id=case_a["id"],
        ), staff["h_int"])
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TARGET_INVALID)


class TestTriageErrors:
    def test_triage_twice_returns_case_not_received(self, api):
        """PRD §3.3: "triaging a case in any other state is rejected with
        `ERR_CASE_NOT_RECEIVED`".

        Design: Corner/errors/triage_twice_returns_not_received
        """
        staff = setup_standard_staff()
        case, _ = create_case()
        triage_case(case["id"], staff["h_int"])
        resp = api.triage_case(case["id"], create_triage_payload(), staff["h_int"])
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_RECEIVED)

    def test_investigator_cannot_triage(self, api):
        """PRD §2.1: "If the role is valid but not permitted for the target endpoint,
        the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: triage is authorized for IntakeSpecialist only.

        Design: Corner/rbac/investigator_cannot_triage
        """
        s_inv = create_staff("Ian Vest", "investigator@corp.example", ["INVESTIGATION"])
        case, _ = create_case()
        resp = api.triage_case(case["id"], create_triage_payload(), make_investigator_headers(s_inv["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_admin_cannot_triage(self, api):
        """PRD §2.1: "If the role is valid but not permitted for the target endpoint,
        the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        (PRD §4 endpoint table authorizes only IntakeSpecialist for triage.)

        Design: Corner/rbac/admin_cannot_triage
        """
        case, _ = create_case()
        resp = api.triage_case(case["id"], create_triage_payload(), make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
