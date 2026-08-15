"""Cross-entity state dependency tests (Difficulty rule 7)."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    make_investigator_headers,
    make_legal_counsel_headers,
    setup_intake_channel,
    setup_employee,
    setup_investigator,
    setup_investigating_case,
    schedule_interview,
    log_evidence,
    set_clock,
    run_case_to_closed,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
)


class TestEvidenceRequiresCaseInvestigating:
    def test_begin_review_rejected_when_case_on_hold(self):
        """PRD §3.3: "Evidence enters the file through the assigned investigator
        while the case is `INVESTIGATING` or in `FINDINGS_DRAFT`; at any other
        case status the logging request is rejected as an invalid state."
        PRD §3.3: "Moving an item from `LOGGED` to `UNDER_REVIEW` is permitted
        to the case's assigned investigator while the case is `INVESTIGATING`
        or in `FINDINGS_DRAFT`."

        Design: Difficulty/cross_entity_state_dependency/evidence_begin_review_requires_case_investigating_or_findings_draft
        """
        set_clock("2026-08-05T00:00:00Z")
        channel = setup_intake_channel(
            channel_code="MANAGER_REFERRAL", display_name="Mgr Ref H",
            default_category="SAFETY", default_severity="MEDIUM",
            sla_business_days=15,
        )
        reporter = setup_employee(location_code="DAL")
        subject = setup_employee(location_code="DAL")
        _, inv1 = setup_investigator()
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="SAFETY", severity="MEDIUM",
        )
        ev = log_evidence(case["id"], inv1["id"], reporter["id"], evidence_type="PHOTO")
        # Hold the case
        api_client.hold_case(
            case["id"],
            {"hold_reason": "Cross-entity gate test hold; pausing the investigation entirely."},
            TEST_USERS["er_manager_headers"],
        )
        # begin-review should now fail
        resp = api_client.begin_review(ev["id"], make_investigator_headers(inv1["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        # Item remains LOGGED
        ev_after = get_success_data(api_client.get_evidence_item(ev["id"], TEST_USERS["er_manager_headers"]))
        assert ev_after["status"] == "LOGGED"

    def test_begin_review_accepted_when_case_investigating(self):
        """PRD §3.3: "Moving an item from `LOGGED` to `UNDER_REVIEW` is
        permitted to the case's assigned investigator while the case is
        `INVESTIGATING` or in `FINDINGS_DRAFT`, and it writes the acting
        investigator into the item's `reviewed_by_investigator_id`."

        Design: Difficulty/cross_entity_state_dependency/evidence_begin_review_requires_case_investigating_or_findings_draft
        """
        channel = setup_intake_channel(
            channel_code="MANAGER_REFERRAL", display_name="Mgr Ref H",
            default_category="SAFETY", default_severity="MEDIUM",
            sla_business_days=15,
        )
        reporter = setup_employee(location_code="DAL")
        subject = setup_employee(location_code="DAL")
        _, inv1 = setup_investigator()
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="SAFETY", severity="MEDIUM",
        )
        ev = log_evidence(case["id"], inv1["id"], reporter["id"], evidence_type="PHOTO")
        resp = api_client.begin_review(ev["id"], make_investigator_headers(inv1["id"]))
        result = validate_success(resp, 200)
        assert result["status"] == "UNDER_REVIEW"
        assert result["reviewed_by_investigator_id"] == inv1["id"]


class TestPackageRequiresClosedCaseWithHold:
    def test_package_creation_rejected_when_litigation_hold_false(self):
        """PRD §3.8: "Assembly may begin only on a case that is `CLOSED` with
        its `litigation_hold` set to true."

        A CLOSED case with litigation_hold == false cannot host a package.

        Design: Difficulty/cross_entity_state_dependency/package_creation_requires_case_closed_with_hold
        """
        channel = setup_intake_channel(
            channel_code="HR_DIRECT", display_name="HR Direct M",
            default_category="RETALIATION", default_severity="HIGH",
            sla_business_days=20,
        )
        reporter = setup_employee(location_code="CHI")
        subject = setup_employee(location_code="CHI")
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        _, inv3 = setup_investigator()
        case, _, _, _, _ = run_case_to_closed(
            channel["id"], subject["id"], inv1, inv2, inv3,
            reporter_employee_id=reporter["id"],
            category="RETALIATION", severity="HIGH",
            action_type="FINAL_WARNING", severity_points=55,
            substantiation_outcome="SUBSTANTIATED",
            assessment_kwargs={"corroboration_count": 4, "contradiction_count": 0,
                                "account_age_days": 2},
        )
        assert case["status"] == "CLOSED"
        assert case["litigation_hold"] is False
        resp = api_client.create_litigation_package(case["id"], make_legal_counsel_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_package_creation_succeeds_when_closed_with_hold(self):
        """PRD §3.8: "Assembly may begin only on a case that is `CLOSED` with
        its `litigation_hold` set to true; the package is tied to that case
        through `case_id`, is born in `ASSEMBLING` status."

        Design: Difficulty/cross_entity_state_dependency/package_creation_requires_case_closed_with_hold
        """
        channel = setup_intake_channel(
            channel_code="ANONYMOUS_LETTER", display_name="Anon P",
            default_category="HARASSMENT", default_severity="HIGH",
            sla_business_days=20,
        )
        subject = setup_employee(location_code="SF")
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        _, inv3 = setup_investigator()
        case, _, _, _, _ = run_case_to_closed(
            channel["id"], subject["id"], inv1, inv2, inv3,
            category="HARASSMENT", severity="HIGH",
            action_type="SUSPENSION", severity_points=70,
            substantiation_outcome="SUBSTANTIATED",
            assessment_kwargs={"corroboration_count": 4, "contradiction_count": 0,
                                "account_age_days": 2},
        )
        assert case["status"] == "CLOSED"
        # Set litigation_hold on the CLOSED case
        patch_resp = api_client.patch_case(
            case["id"], {"litigation_hold": True}, TEST_USERS["er_manager_headers"]
        )
        get_success_data(patch_resp)
        # Now create the package
        resp = api_client.create_litigation_package(case["id"], make_legal_counsel_headers())
        pkg = validate_success(resp, 201)
        assert pkg["status"] == "ASSEMBLING"
        assert pkg["case_id"] == case["id"]
        assert pkg["package_version"] == 1
