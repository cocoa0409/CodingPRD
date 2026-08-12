"""Validation rules: date ordering, evidence/marking evidence gates, hash
format, grant expiry window, email uniqueness, policy publish, counterparty
state gate, classification ceiling, forensic review window (PRD §2.12, §3)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_counterparty,
    create_active_nda,
    create_nda_payload,
    create_registered_asset,
    add_verified_measure,
    create_measure_payload,
    create_employee_record,
    create_active_employee,
    create_grant_payload,
    create_disclosure_payload,
    create_forensic_review_payload,
    create_evidence_item_payload,
    create_exit_interview_payload,
    create_certified_interview,
    create_employee_payload,
    create_submitted_disclosure,
    create_under_review_disclosure,
    make_employee_headers,
    make_counterparty_rep_headers,
    make_ip_counsel_headers,
    get_pending_ack_id,
    sign_employee_ack,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]
HR = TEST_USERS["hr_partner_headers"]
SEC = TEST_USERS["security_officer_headers"]


class TestDateOrderValidation:
    def test_nda_expiry_before_effective_rejected(self, api):
        """PRD §3.2: "The expiry must fall strictly after the effective date,
        otherwise `ERR_DATE_ORDER`."

        Design: Corner/validations/nda_expiry_before_effective_rejected
        """
        cp = create_counterparty(legal_name="Phi Courier", counterparty_type="VENDOR")
        resp = api.create_nda(
            create_nda_payload(
                cp["id"], template_version="t18", governing_law="ID",
                effective_date="2026-12-31T00:00:00Z", expiry_date="2026-01-01T00:00:00Z",
                survival_months=3, classification_ceiling="INTERNAL",
            ), IP
        )
        validate_error(resp, ApiErrorId.ERR_DATE_ORDER)


class TestMeasureEvidenceGate:
    def test_measure_implement_without_evidence_rejected(self, api):
        """PRD §3.1: "Marking a measure implemented — `PLANNED → IMPLEMENTED` —
        requires a non-empty `evidence_uri`, otherwise
        `ERR_MEASURE_EVIDENCE_REQUIRED`."

        Design: Corner/validations/measure_implement_without_evidence_rejected
        """
        resp = api.create_asset(
            {"title": "Ev probe", "description": "x", "classification": "INTERNAL",
             "owner_department": "ENG", "exposure_estimate_cents": 10}, IP
        )
        asset = validate_success(resp, expected_status=201)
        resp = api.create_measure(
            {"asset_id": asset["id"], "measure_type": "POLICY",
             "title": "No evidence yet"}, SEC
        )
        measure = validate_success(resp, expected_status=201)
        resp = api.transition_measure(measure["id"], {"to_status": "IMPLEMENTED"}, SEC)
        validate_error(resp, ApiErrorId.ERR_MEASURE_EVIDENCE_REQUIRED)
        data = validate_success(api.get_measure(measure["id"], IP))
        assert data["status"] == "PLANNED"


def _setup_approved_disclosure_low_risk(api):
    """APPROVED disclosure: INTERNAL asset, LOW-tier counterparty, ORAL
    protocol (final 10 < 80, no endorsement needed)."""
    cp = create_counterparty(legal_name="Chi Promo", counterparty_type="CUSTOMER")
    nda = create_active_nda(
        cp["id"], template_version="t19", governing_law="ID",
        effective_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z",
        survival_months=3, classification_ceiling="INTERNAL",
    )
    asset = create_registered_asset(
        title="Brand guide", description="x", classification="INTERNAL",
        owner_department="MKT", exposure_estimate_cents=100,
    )
    add_verified_measure(asset["id"], "TECHNICAL", title="t", evidence_uri="s3://ev/t.pdf")
    add_verified_measure(asset["id"], "PHYSICAL", title="p", evidence_uri="s3://ev/p.pdf")
    emp = create_employee_record(
        full_name="Fred Mark", email="fred@x.com", department="MKT",
        role_title="Designer", access_clearance="STANDARD",
        hired_at="2026-05-01T00:00:00Z",
    )
    disc = create_under_review_disclosure(
        emp["id"], asset["id"], nda["id"],
        purpose="p", marking_protocol="ORAL_WITH_FOLLOWUP",
        planned_disclosure_date="2026-06-01T00:00:00Z",
    )
    data = validate_success(api.transition_disclosure(
        disc["id"], {"to_status": "APPROVED"}, make_ip_counsel_headers("counsel_1")
    ))
    return data


class TestMarkingEvidenceGate:
    def test_disclosure_execute_without_marking_rejected(self, api):
        """PRD §3.5: "Moving `APPROVED → EXECUTED` requires a non-empty
        `marking_evidence_uri` and a `marking_sha256` of exactly 64 lowercase
        hexadecimal characters, otherwise `ERR_MARKING_EVIDENCE_REQUIRED`."

        Design: Corner/validations/disclosure_execute_without_marking_rejected
        """
        disc = _setup_approved_disclosure_low_risk(api)
        resp = api.transition_disclosure(disc["id"], {"to_status": "EXECUTED"}, IP)
        validate_error(resp, ApiErrorId.ERR_MARKING_EVIDENCE_REQUIRED)
        data = validate_success(api.get_disclosure(disc["id"], IP))
        assert data["status"] == "APPROVED"


class TestEvidenceHashFormat:
    def test_evidence_bad_hash_rejected(self, api):
        """PRD §3.8: "The hash must be exactly 64 lowercase hexadecimal
        characters, otherwise `ERR_INVALID_HASH`."

        Design: Corner/validations/evidence_bad_hash_rejected
        """
        emp = create_active_employee(
            complete_training=False, full_name="Gus Proof", email="gus@x.com",
            department="ENG", role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        resp = api.create_forensic_review(
            create_forensic_review_payload(emp["id"], trigger_reason="POLICY"), IP
        )
        review = validate_success(resp, expected_status=201)
        resp = api.create_evidence_item(
            {"review_id": review["id"], "source": "ACCESS_LOG",
             "sha256": "ZZZ-not-hex", "byte_size": 10}, SEC
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_HASH)


class TestGrantExpiryWindow:
    def test_grant_expiry_beyond_365_days_rejected(self, api):
        """PRD §3.4: "The expiry must fall later than the current clock and no
        more than 365 days out, otherwise `ERR_EXPIRY_IN_PAST`."

        Design: Corner/validations/grant_expiry_beyond_365_days_rejected
        """
        emp = create_active_employee(
            complete_training=False, full_name="Hank Long", email="hank2@x.com",
            department="ENG", role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        asset = create_registered_asset(
            title="Long probe", description="x", classification="INTERNAL",
            owner_department="ENG", exposure_estimate_cents=10,
        )
        resp = api.create_grant(
            create_grant_payload(emp["id"], asset["id"], justification="too long",
                                 expires_at="2027-06-01T00:00:00Z"),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EXPIRY_IN_PAST)


class TestEmployeeEmailUniqueness:
    def test_duplicate_employee_email_rejected(self, api):
        """PRD §3.3: "Email is unique across employees; a duplicate is rejected
        with `ERR_DUPLICATE_EMAIL`."

        Design: Corner/validations/duplicate_employee_email_rejected
        """
        validate_success(api.create_employee(
            create_employee_payload(full_name="First Dup", email="dup@x.com"), HR
        ), expected_status=201)
        resp = api.create_employee(
            create_employee_payload(full_name="Second Dup", email="dup@x.com"), HR
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL)


class TestPolicyPublishValidation:
    def test_publish_same_policy_version_rejected(self, api):
        """PRD §3.3: "Publishing requires a `new_version` that differs from the
        `current_policy_version`, otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/validations/publish_same_policy_version_rejected
        """
        resp = api.publish_policy({"new_version": "v1"}, IP)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestSuspendedCounterpartyGate:
    def test_suspended_counterparty_blocks_nda_create(self, api):
        """PRD §3.2: "Suspending a counterparty (`ACTIVE → SUSPENDED`) blocks
        the drafting of new NDAs for it and blocks new disclosure requests
        referencing it."
        PRD §3.2: "Drafting also requires the counterparty to be `ACTIVE`,
        otherwise `ERR_COUNTERPARTY_NOT_ACTIVE`."

        Design: Corner/validations/suspended_counterparty_blocks_nda_create
        """
        cp = create_counterparty(legal_name="Psi Haulers", counterparty_type="VENDOR")
        validate_success(api.transition_counterparty(cp["id"], {"to_status": "SUSPENDED"}, IP))
        resp = api.create_nda(
            create_nda_payload(
                cp["id"], template_version="t20", governing_law="ID",
                effective_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z",
                survival_months=3, classification_ceiling="INTERNAL",
            ), IP
        )
        validate_error(resp, ApiErrorId.ERR_COUNTERPARTY_NOT_ACTIVE)


class TestClassificationCeilingGate:
    def test_classification_ceiling_gate_at_review(self, api):
        """PRD §3.5: "the NDA's `classification_ceiling` is at least as
        sensitive as the asset's classification on the ascending
        `INTERNAL`-to-`CROWN_JEWEL` scale, otherwise
        `ERR_CLASSIFICATION_CEILING_EXCEEDED`."

        Design: Corner/validations/classification_ceiling_gate_at_review
        """
        cp = create_counterparty(legal_name="Omega Print", counterparty_type="VENDOR")
        nda = create_active_nda(
            cp["id"], template_version="t21", governing_law="ID",
            effective_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z",
            survival_months=3, classification_ceiling="CONFIDENTIAL",
        )
        asset = create_registered_asset(
            title="Ceiling probe", description="x", classification="RESTRICTED",
            owner_department="ENG", exposure_estimate_cents=1000,
        )
        emp = create_employee_record(
            full_name="Ivy Ceil", email="ivy2@x.com", department="ENG",
            role_title="SDE", access_clearance="ELEVATED",
            hired_at="2026-05-01T00:00:00Z",
        )
        disc = create_submitted_disclosure(
            emp["id"], asset["id"], nda["id"],
            purpose="p", marking_protocol="STAMPED_CONFIDENTIAL",
            planned_disclosure_date="2026-07-01T00:00:00Z",
        )
        resp = api.transition_disclosure(disc["id"], {"to_status": "UNDER_REVIEW"}, IP)
        validate_error(resp, ApiErrorId.ERR_CLASSIFICATION_CEILING_EXCEEDED)
        data = validate_success(api.get_disclosure(disc["id"], IP))
        assert data["status"] == "SUBMITTED"


class TestReviewWindowExpiry:
    def test_review_open_after_90_days_rejected(self, api):
        """PRD §3.6: "Manual opening is allowed while the employee is `ACTIVE`
        or `NOTICE`, or after departure within a ninety-day window: if the
        employee is `DEPARTED` and the clock has moved more than 90 days past
        `departed_at`, creation is rejected with `ERR_REVIEW_WINDOW_EXPIRED`."

        Design: Corner/validations/review_open_after_90_days_rejected
        """
        emp = create_active_employee(
            complete_training=False, full_name="Jude Gone", email="jude@x.com",
            department="ENG", role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        create_certified_interview(
            emp["id"],
            scheduled_start="2026-05-09T10:00:00Z",
            scheduled_end="2026-05-09T11:00:00Z",
        )
        validate_success(api.transition_employee(
            emp["id"], {"to_status": "NOTICE", "departure_type": "VOLUNTARY"}, HR
        ))
        api.set_clock({"to_iso8601": "2026-05-10T00:00:00Z"}, IP)
        validate_success(api.transition_employee(emp["id"], {"to_status": "DEPARTED"}, HR))

        # Exactly 90 days after departed_at (2026-05-10 + 90d = 2026-08-08): allowed
        api.set_clock({"to_iso8601": "2026-08-08T00:00:00Z"}, IP)
        resp = api.create_forensic_review(
            create_forensic_review_payload(emp["id"], trigger_reason="POLICY"), IP
        )
        validate_success(resp, expected_status=201)

        # 91 days: rejected
        api.set_clock({"to_iso8601": "2026-08-09T00:00:00Z"}, IP)
        resp = api.create_forensic_review(
            create_forensic_review_payload(emp["id"], trigger_reason="LITIGATION"), IP
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_WINDOW_EXPIRED)
