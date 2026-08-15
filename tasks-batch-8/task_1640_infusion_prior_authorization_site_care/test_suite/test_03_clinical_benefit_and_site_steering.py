"""Clinical criteria review, benefit verification routing, submission gates,
and the site-of-care steering score."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_benefit_investigation,
    add_criteria_submission,
    create_auth_request_payload,
    create_criteria_payload,
    create_draft_request,
    create_patient,
    create_policy,
    create_site_determination_payload,
    get_request,
    review_criteria_payload,
    review_criteria_submission,
    run_site_determination,
    setup_submittable_request,
    verify_benefit_investigation,
    validate_error,
    validate_success,
    AUTH_COORDINATOR_HEADERS,
    FINANCE_SPECIALIST_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
)


class TestCriteriaReviewRbac:
    def test_finance_specialist_cannot_review_criteria(self, api):
        """PRD §2.1: "A well-formed request whose role is not listed among the
        endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."
        PRD §4: POST /infusion/criteria-submissions/{id}/reviews is authorized
        for MedicalDirector only.

        Design: Corner/rbac/finance_specialist_cannot_review_criteria
        """
        policy = create_policy(drug_code="J9172", regimen_name="RBAC3")
        patient = create_patient(member_id="M1172", full_name="RB3 P")
        auth = create_draft_request(patient["id"], policy["id"])
        criterion = add_criteria_submission(auth["id"])

        resp = api.review_criteria_submission(
            criterion["id"], review_criteria_payload("ACCEPTED"),
            FINANCE_SPECIALIST_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        listed = validate_success(
            api.list_criteria_submissions(auth["id"], MEDICAL_DIRECTOR_HEADERS))
        assert listed[0]["status"] == "SUBMITTED", (
            "A denied review leaves the criterion SUBMITTED")


class TestBenefitRouting:
    def test_pharmacy_verification_rejected_on_buy_and_bill_policy(self, api):
        """PRD §3.3: "When the governing policy's `buy_and_bill_required` is
        true, a `PHARMACY` verification is rejected with
        `ERR_ROUTING_VIOLATION` (422) — the drug must be procured buy-and-bill
        under the medical benefit."
        PRD §3.3: "Successful verification stamps `VERIFIED` (a terminal
        state), derives the `routing` as `BUY_AND_BILL` for a medical channel
        or `SPECIALTY_PHARMACY` for a pharmacy channel, and records the
        specialist in `verified_by_user_id`."

        Design: Corner/validations/routing_violation_pharmacy_on_buy_and_bill_required
        """
        policy = create_policy(drug_code="J9143", regimen_name="BnB",
                               benefit_channel="EITHER",
                               buy_and_bill_required=True)
        patient = create_patient(member_id="M1143", full_name="BnB P")
        auth = create_draft_request(patient["id"], policy["id"])
        bi_pharmacy = add_benefit_investigation(auth["id"])
        bi_medical = add_benefit_investigation(auth["id"])

        resp = api.verify_benefit_investigation(
            bi_pharmacy["id"], {"determined_channel": "PHARMACY"},
            FINANCE_SPECIALIST_HEADERS)
        validate_error(resp, ApiErrorId.ERR_ROUTING_VIOLATION)

        listed = validate_success(api.list_benefit_investigations(
            auth["id"], FINANCE_SPECIALIST_HEADERS))
        by_id = {b["id"]: b for b in listed}
        assert by_id[bi_pharmacy["id"]]["status"] == "INITIATED", (
            "The refused verification leaves the investigation INITIATED")

        verified = validate_success(api.verify_benefit_investigation(
            bi_medical["id"], {"determined_channel": "MEDICAL"},
            FINANCE_SPECIALIST_HEADERS))
        assert verified["status"] == "VERIFIED"
        assert verified["routing"] == "BUY_AND_BILL"
        assert verified["verified_by_user_id"] == "fin-1"


class TestSubmissionGates:
    def test_submit_without_verified_benefit_rejected(self, api):
        """PRD §3.4: "Submitting a `DRAFT` request moves it to `SUBMITTED` and
        passes three gates, evaluated in this order: at least one benefit
        investigation of the request must be `VERIFIED` (otherwise
        `ERR_BENEFIT_NOT_VERIFIED`), at least one criteria submission must be
        `ACCEPTED` (otherwise `ERR_MISSING_REQUIRED_CRITERIA`), and at least one
        site-of-care determination must exist (otherwise
        `ERR_SITE_DETERMINATION_MISSING`)."

        Design: Corner/validations/submit_without_benefit_returns_benefit_not_verified
        """
        policy = create_policy(drug_code="J9144", regimen_name="NoBen")
        patient = create_patient(member_id="M1144", full_name="NB P")
        auth = create_draft_request(patient["id"], policy["id"])
        criterion = add_criteria_submission(auth["id"])
        review_criteria_submission(criterion["id"], "ACCEPTED")
        run_site_determination(auth["id"])

        resp = api.submit_authorization_request(
            auth["id"], AUTH_COORDINATOR_HEADERS)
        validate_error(resp, ApiErrorId.ERR_BENEFIT_NOT_VERIFIED)
        assert get_request(auth["id"])["status"] == "DRAFT"

    def test_submit_without_accepted_criteria_rejected(self, api):
        """PRD §3.4: "Submitting a `DRAFT` request moves it to `SUBMITTED` and
        passes three gates, evaluated in this order: at least one benefit
        investigation of the request must be `VERIFIED` (otherwise
        `ERR_BENEFIT_NOT_VERIFIED`), at least one criteria submission must be
        `ACCEPTED` (otherwise `ERR_MISSING_REQUIRED_CRITERIA`), and at least one
        site-of-care determination must exist (otherwise
        `ERR_SITE_DETERMINATION_MISSING`)."

        Design: Corner/validations/submit_without_accepted_criteria
        """
        policy = create_policy(drug_code="J9145", regimen_name="NoCrit")
        patient = create_patient(member_id="M1145", full_name="NC P")
        auth = create_draft_request(patient["id"], policy["id"])
        benefit = add_benefit_investigation(auth["id"])
        verify_benefit_investigation(benefit["id"], "MEDICAL")
        criterion = add_criteria_submission(
            auth["id"], response_value="incomplete")
        review_criteria_submission(criterion["id"], "REJECTED")
        run_site_determination(auth["id"])

        resp = api.submit_authorization_request(
            auth["id"], AUTH_COORDINATOR_HEADERS)
        validate_error(resp, ApiErrorId.ERR_MISSING_REQUIRED_CRITERIA)
        assert get_request(auth["id"])["status"] == "DRAFT"

    def test_submit_without_site_determination_rejected(self, api):
        """PRD §3.4: "Submitting a `DRAFT` request moves it to `SUBMITTED` and
        passes three gates, evaluated in this order: at least one benefit
        investigation of the request must be `VERIFIED` (otherwise
        `ERR_BENEFIT_NOT_VERIFIED`), at least one criteria submission must be
        `ACCEPTED` (otherwise `ERR_MISSING_REQUIRED_CRITERIA`), and at least one
        site-of-care determination must exist (otherwise
        `ERR_SITE_DETERMINATION_MISSING`)."

        Design: Corner/validations/submit_without_site_determination
        """
        policy = create_policy(drug_code="J9146", regimen_name="NoSite")
        patient = create_patient(member_id="M1146", full_name="ND P")
        auth = create_draft_request(patient["id"], policy["id"])
        benefit = add_benefit_investigation(auth["id"])
        verify_benefit_investigation(benefit["id"], "MEDICAL")
        criterion = add_criteria_submission(auth["id"])
        review_criteria_submission(criterion["id"], "ACCEPTED")

        resp = api.submit_authorization_request(
            auth["id"], AUTH_COORDINATOR_HEADERS)
        validate_error(resp, ApiErrorId.ERR_SITE_DETERMINATION_MISSING)
        assert get_request(auth["id"])["status"] == "DRAFT"


class TestSiteSteeringScore:
    def test_score_variants_diverge_on_identical_inputs(self, api):
        """PRD §3.3: "For a non-rural patient (`rural_resident` false), the
        `COST_RATIO` variant divides `hospital_allowed_cents` by
        `home_allowed_cents`, and the `steer_score` is that ratio at full
        weight plus the burden index at half weight, rounded half-up to three
        decimal places."
        PRD §3.3: "For a rural resident, the `TRAVEL_BURDEN` variant instead
        divides `hospital_billed_cents` by `home_billed_cents`, and the score
        is that ratio plus the burden index — both terms at full weight —
        again rounded half-up to three decimal places; identical inputs
        therefore yield a different `steer_score` under the two variants."
        PRD §3.3: "Under a steering posture, a `steer_score` at or above the
        policy's `steer_threshold` pushes the recommendation to the policy's
        target — `HOME` under `STEER_TO_HOME`, `OFFICE` under
        `STEER_TO_OFFICE` — and `steered` is true exactly when that
        recommendation differs from the requested site."

        Design: Difficulty/dual_variant_calc/site_score_cost_ratio_vs_travel_burden_variant
        """
        policy = create_policy(drug_code="J9003", regimen_name="DrugA q4w",
                               site_policy="STEER_TO_HOME", steer_threshold=1.50)
        urban = create_patient(member_id="M200U", full_name="Urban U",
                               rural_resident=False,
                               travel_minutes_to_hospital=30)
        rural = create_patient(member_id="M200R", full_name="Rural R",
                               rural_resident=True,
                               travel_minutes_to_hospital=30)
        auth_u = create_draft_request(
            urban["id"], policy["id"],
            requested_site_type="HOSPITAL_OUTPATIENT")
        auth_r = create_draft_request(
            rural["id"], policy["id"],
            requested_site_type="HOSPITAL_OUTPATIENT")

        det_u = validate_success(api.create_site_of_care_determination(
            auth_u["id"], create_site_determination_payload(),
            MEDICAL_DIRECTOR_HEADERS), 201)
        det_r = validate_success(api.create_site_of_care_determination(
            auth_r["id"], create_site_determination_payload(),
            MEDICAL_DIRECTOR_HEADERS), 201)

        # burden index = 30/120 = 0.25 in both cases.
        assert det_u["score_variant"] == "COST_RATIO"
        assert det_u["steer_score"] == pytest.approx(3.125), (
            "3.0 * 1.0 + 0.25 * 0.5 = 3.125")
        assert det_r["score_variant"] == "TRAVEL_BURDEN"
        assert det_r["steer_score"] == pytest.approx(3.250), (
            "3.0 * 1.0 + 0.25 * 1.0 = 3.250")
        assert det_u["steer_score"] != det_r["steer_score"], (
            "Identical cost inputs yield different scores across variants")
        for det in (det_u, det_r):
            assert det["recommended_site_type"] == "HOME"
            assert det["steered"] is True

    def test_burden_index_capped_at_two_hours(self, api):
        """PRD §3.3: "The computation first derives a burden index from the
        patient's `travel_minutes_to_hospital`, capped at two hours (120
        minutes) and expressed as a fraction of that cap — a patient forty-five
        minutes from the hospital contributes 0.375."
        PRD §3.3: "For a rural resident, the `TRAVEL_BURDEN` variant instead
        divides `hospital_billed_cents` by `home_billed_cents`, and the score
        is that ratio plus the burden index — both terms at full weight —
        again rounded half-up to three decimal places; identical inputs
        therefore yield a different `steer_score` under the two variants."

        Design: Difficulty/dual_variant_calc/site_score_cost_ratio_vs_travel_burden_variant
        """
        policy = create_policy(drug_code="J9004", regimen_name="CapBurden",
                               site_policy="STEER_TO_HOME", steer_threshold=1.50)
        urban = create_patient(member_id="M201U", full_name="Urban Far",
                               rural_resident=False,
                               travel_minutes_to_hospital=200)
        rural = create_patient(member_id="M201R", full_name="Rural Far",
                               rural_resident=True,
                               travel_minutes_to_hospital=200)
        auth_u = create_draft_request(
            urban["id"], policy["id"],
            requested_site_type="HOSPITAL_OUTPATIENT")
        auth_r = create_draft_request(
            rural["id"], policy["id"],
            requested_site_type="HOSPITAL_OUTPATIENT")

        det_u = validate_success(api.create_site_of_care_determination(
            auth_u["id"], create_site_determination_payload(),
            MEDICAL_DIRECTOR_HEADERS), 201)
        det_r = validate_success(api.create_site_of_care_determination(
            auth_r["id"], create_site_determination_payload(),
            MEDICAL_DIRECTOR_HEADERS), 201)

        # Travel 200 minutes is capped at 120 -> burden index 1.0.
        assert det_u["steer_score"] == pytest.approx(3.5), (
            "3.0 * 1.0 + 1.0 * 0.5 = 3.500")
        assert det_r["steer_score"] == pytest.approx(4.0), (
            "3.0 * 1.0 + 1.0 * 1.0 = 4.000")
        assert det_u["score_variant"] == "COST_RATIO"
        assert det_r["score_variant"] == "TRAVEL_BURDEN"

    def test_score_below_threshold_keeps_requested_site(self, api):
        """PRD §3.3: "Below the threshold, the recommendation falls back to
        the requested site with `steered` false."
        PRD §3.3: "For a non-rural patient (`rural_resident` false), the
        `COST_RATIO` variant divides `hospital_allowed_cents` by
        `home_allowed_cents`, and the `steer_score` is that ratio at full
        weight plus the burden index at half weight, rounded half-up to three
        decimal places."

        Design: Corner/calculations/site_score_below_threshold_allows_requested
        """
        policy = create_policy(drug_code="J9123", regimen_name="Below",
                               site_policy="STEER_TO_HOME", steer_threshold=1.50)
        patient = create_patient(member_id="M1123", full_name="BL P",
                                 rural_resident=False,
                                 travel_minutes_to_hospital=0)
        auth = create_draft_request(
            patient["id"], policy["id"],
            requested_site_type="HOSPITAL_OUTPATIENT")

        det = validate_success(api.create_site_of_care_determination(
            auth["id"],
            create_site_determination_payload(
                home_allowed_cents=290000, hospital_allowed_cents=300000,
                home_billed_cents=340000, hospital_billed_cents=360000),
            MEDICAL_DIRECTOR_HEADERS), 201)
        # 300000/290000 = 1.0344827... -> 1.034 half-up to three decimals.
        assert det["steer_score"] == pytest.approx(1.034)
        assert det["recommended_site_type"] == "HOSPITAL_OUTPATIENT"
        assert det["steered"] is False
