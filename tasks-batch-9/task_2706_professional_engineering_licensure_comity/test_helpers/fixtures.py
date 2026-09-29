"""Composite setup helpers that drive the API to a named starting state.

Every helper here goes through the public API only and uses the lenient
``get_success_data`` reader, so a setup failure surfaces as a readable error
rather than as a confusing assertion inside the test body. Identity is threaded
through the ``make_*_headers`` builders: an entity-backed caller always presents
the id of the row it acts for.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import (
    BOARD_INVESTIGATOR_2_HEADERS,
    BOARD_INVESTIGATOR_HEADERS,
    BOARD_LICENSING_OFFICER_2_HEADERS,
    BOARD_LICENSING_OFFICER_HEADERS,
    BOARD_REVIEWER_2_HEADERS,
    BOARD_REVIEWER_HEADERS,
    BOARD_SECRETARY_HEADERS,
    TESTING_SERVICE_HEADERS,
    make_applicant_headers,
    make_firm_admin_headers,
    make_licensee_headers,
    make_supervising_engineer_headers,
)

# ---------------------------------------------------------------------------
# Primitive steps
# ---------------------------------------------------------------------------


def set_clock(api, to_iso8601):
    """Move the logical board clock forward and return the sweep summary."""
    return get_success_data(
        api.set_current_utc(factories.clock_payload(to_iso8601), BOARD_SECRETARY_HEADERS)
    )


def create_engineer(api, **overrides):
    return get_success_data(
        api.create_engineer(factories.engineer_payload(**overrides), BOARD_SECRETARY_HEADERS)
    )


def issue_license(api, engineer_id, **overrides):
    return get_success_data(
        api.create_license(
            factories.license_payload(engineer_id, **overrides),
            BOARD_LICENSING_OFFICER_HEADERS,
        )
    )


def create_licensed_engineer(api, license_overrides=None, **engineer_overrides):
    """Roster an engineer and hand them one ACTIVE licence."""
    engineer = create_engineer(api, **engineer_overrides)
    license_ = issue_license(api, engineer["id"], **(license_overrides or {}))
    return engineer, license_


def create_test_center(api, **overrides):
    return get_success_data(
        api.create_test_center(
            factories.test_center_payload(**overrides), BOARD_SECRETARY_HEADERS
        )
    )


def create_application(api, engineer_id, **overrides):
    return get_success_data(
        api.create_application(
            factories.application_payload(engineer_id, **overrides),
            make_applicant_headers(engineer_id),
        )
    )


def evaluate_education(api, application_id, **overrides):
    return get_success_data(
        api.evaluate_education(
            application_id,
            factories.education_evaluation_payload(**overrides),
            BOARD_REVIEWER_HEADERS,
        )
    )


def transmit_ncees_packet(api, application_id, **overrides):
    return get_success_data(
        api.transmit_ncees_verification(
            application_id,
            factories.ncees_verification_payload(**overrides),
            TESTING_SERVICE_HEADERS,
        )
    )


def add_experience_record(api, application_id, engineer_id, **overrides):
    return get_success_data(
        api.create_experience_record(
            application_id,
            factories.experience_record_payload(**overrides),
            make_applicant_headers(engineer_id),
        )
    )


def request_reference(api, experience_record_id, engineer_id, referee_engineer_id, **overrides):
    return get_success_data(
        api.create_reference(
            experience_record_id,
            factories.reference_payload(referee_engineer_id, **overrides),
            make_applicant_headers(engineer_id),
        )
    )


def pay_assessed_fee(api, application_id, engineer_id, amount_cents=None):
    """Remit exactly the assessed fee unless an explicit amount is given."""
    headers = make_applicant_headers(engineer_id)
    if amount_cents is None:
        application = get_success_data(api.get_application(application_id, headers))
        amount_cents = application["fee_assessment_cents"]
    return get_success_data(
        api.pay_application(
            application_id, factories.payment_payload(amount_cents), headers
        )
    )


def submit_application(api, application_id, engineer_id):
    return get_success_data(
        api.submit_application(application_id, make_applicant_headers(engineer_id))
    )


def submit_reference(api, reference_id, referee_engineer_id, **overrides):
    return get_success_data(
        api.submit_reference(
            reference_id,
            factories.reference_submission_payload(**overrides),
            make_supervising_engineer_headers(referee_engineer_id),
        )
    )


def start_review(api, application_id, headers=None):
    return get_success_data(
        api.start_review(application_id, headers or BOARD_REVIEWER_HEADERS)
    )


def evaluate_reference(api, reference_id, decision="ACCEPT", headers=None):
    return get_success_data(
        api.evaluate_reference(
            reference_id, {"decision": decision}, headers or BOARD_REVIEWER_HEADERS
        )
    )


def recant_reference(api, reference_id, referee_engineer_id, recant_reason="Withdrawn."):
    return get_success_data(
        api.recant_reference(
            reference_id,
            {"recant_reason": recant_reason},
            make_supervising_engineer_headers(referee_engineer_id),
        )
    )


def raise_deficiency(api, application_id, headers=None, **overrides):
    return get_success_data(
        api.raise_deficiency(
            application_id,
            factories.deficiency_payload(**overrides),
            headers or BOARD_REVIEWER_HEADERS,
        )
    )


def respond_deficiency(api, application_id, engineer_id, **overrides):
    return get_success_data(
        api.respond_deficiency(
            application_id,
            factories.deficiency_response_payload(**overrides),
            make_applicant_headers(engineer_id),
        )
    )


def determine_credit(api, application_id, headers=None):
    return get_success_data(
        api.determine_credit(application_id, headers or BOARD_LICENSING_OFFICER_HEADERS)
    )


def approve_exam(api, application_id, headers=None):
    return get_success_data(
        api.approve_exam(application_id, headers or BOARD_LICENSING_OFFICER_2_HEADERS)
    )


def issue_license_from_application(api, application_id, headers=None):
    return get_success_data(
        api.issue_license(application_id, headers or BOARD_LICENSING_OFFICER_2_HEADERS)
    )


def book_appointment(api, exam_authorization_id, test_center_id, engineer_id, **overrides):
    return get_success_data(
        api.create_exam_appointment(
            factories.exam_appointment_payload(
                exam_authorization_id, test_center_id, **overrides
            ),
            make_applicant_headers(engineer_id),
        )
    )


def cancel_appointment(api, exam_appointment_id, engineer_id, **payload):
    return get_success_data(
        api.cancel_exam_appointment(
            exam_appointment_id, make_applicant_headers(engineer_id), payload or None
        )
    )


def score_exam(api, exam_authorization_id, **overrides):
    return get_success_data(
        api.score_exam(
            exam_authorization_id,
            factories.score_payload(**overrides),
            TESTING_SERVICE_HEADERS,
        )
    )


def retake_exam(api, exam_authorization_id, engineer_id):
    return get_success_data(
        api.retake_exam(exam_authorization_id, make_applicant_headers(engineer_id))
    )


# ---------------------------------------------------------------------------
# Firms, plan sets, competency and enforcement primitives
# ---------------------------------------------------------------------------


def create_firm(api, responsible_charge_license_id, **overrides):
    return get_success_data(
        api.create_firm_registration(
            factories.firm_registration_payload(responsible_charge_license_id, **overrides),
            BOARD_LICENSING_OFFICER_HEADERS,
        )
    )


def nominate_responsible_charge(api, firm_registration_id, license_id):
    return get_success_data(
        api.nominate_responsible_charge(
            firm_registration_id,
            {"responsible_charge_license_id": license_id},
            make_firm_admin_headers(firm_registration_id),
        )
    )


def create_plan_submission(api, firm_registration_id, **overrides):
    return get_success_data(
        api.create_plan_submission(
            factories.plan_submission_payload(firm_registration_id, **overrides),
            make_firm_admin_headers(firm_registration_id),
        )
    )


def seal_plan(api, plan_submission_id, sealing_license_id, engineer_id, **overrides):
    return get_success_data(
        api.seal_plan_submission(
            plan_submission_id,
            factories.seal_payload(sealing_license_id, **overrides),
            make_licensee_headers(engineer_id),
        )
    )


def flag_plan(api, plan_submission_id, reason="Suspect stamping.", headers=None):
    return get_success_data(
        api.flag_plan_submission(
            plan_submission_id, headers or BOARD_INVESTIGATOR_HEADERS, {"reason": reason}
        )
    )


def create_cpc_report(api, license_id, engineer_id, expected_license_version, **overrides):
    return get_success_data(
        api.create_cpc_report(
            factories.cpc_report_payload(license_id, expected_license_version, **overrides),
            make_licensee_headers(engineer_id),
        )
    )


def add_pdh_record(api, cpc_report_id, engineer_id, **overrides):
    return get_success_data(
        api.create_pdh_record(
            cpc_report_id,
            factories.pdh_record_payload(**overrides),
            make_licensee_headers(engineer_id),
        )
    )


def review_pdh_documentation(api, pdh_record_id, decision="ACCEPT", headers=None):
    return get_success_data(
        api.review_pdh_documentation(
            pdh_record_id, {"decision": decision}, headers or BOARD_REVIEWER_HEADERS
        )
    )


def accept_cpc_report(api, cpc_report_id, headers=None):
    return get_success_data(
        api.accept_cpc_report(cpc_report_id, headers or BOARD_REVIEWER_HEADERS)
    )


def draw_audit(api, headers=None, **overrides):
    return get_success_data(
        api.create_cpc_audit(
            factories.cpc_audit_payload(**overrides), headers or BOARD_REVIEWER_HEADERS
        )
    )


def decide_audit(api, cpc_report_id, decision="CLEAR", headers=None):
    return get_success_data(
        api.audit_decision(
            cpc_report_id, {"decision": decision}, headers or BOARD_REVIEWER_2_HEADERS
        )
    )


def renew_license(api, license_id, engineer_id):
    return get_success_data(
        api.renew_license(license_id, make_licensee_headers(engineer_id))
    )


def reinstate_license(api, license_id, **overrides):
    return get_success_data(
        api.reinstate_license(
            license_id,
            factories.reinstate_payload(**overrides),
            BOARD_LICENSING_OFFICER_HEADERS,
        )
    )


def create_case(api, headers=None, **overrides):
    return get_success_data(
        api.create_case(
            factories.case_payload(**overrides), headers or BOARD_INVESTIGATOR_HEADERS
        )
    )


def open_investigation(api, case_id, headers=None):
    return get_success_data(
        api.open_investigation(case_id, headers or BOARD_INVESTIGATOR_HEADERS)
    )


def record_finding(api, case_id, headers=None, **overrides):
    return get_success_data(
        api.record_finding(
            case_id,
            factories.finding_payload(**overrides),
            headers or BOARD_INVESTIGATOR_HEADERS,
        )
    )


def propose_consent_order(api, case_id, expected_case_version, headers=None, **overrides):
    return get_success_data(
        api.create_consent_order(
            factories.consent_order_payload(case_id, expected_case_version, **overrides),
            headers or BOARD_INVESTIGATOR_HEADERS,
        )
    )


def execute_consent_order(api, consent_order_id, headers=None, **overrides):
    return get_success_data(
        api.execute_consent_order(
            consent_order_id,
            factories.execute_payload(**overrides),
            headers or BOARD_LICENSING_OFFICER_HEADERS,
        )
    )


def refer_hearing(api, case_id, headers=None):
    return get_success_data(api.refer_hearing(case_id, headers or BOARD_INVESTIGATOR_HEADERS))


def close_case(api, case_id, headers=None):
    return get_success_data(api.close_case(case_id, headers or BOARD_INVESTIGATOR_HEADERS))


# ---------------------------------------------------------------------------
# Composite tracks
# ---------------------------------------------------------------------------

EXAM_TRACK_STAGES = (
    "application",
    "education_evaluated",
    "experience_added",
    "reference_requested",
    "paid",
    "submitted",
    "reference_submitted",
    "under_review",
    "reference_accepted",
    "credit_determined",
    "exam_approved",
)


def setup_exam_track(
    api,
    stop_after="exam_approved",
    application_overrides=None,
    education_overrides=None,
    experience_overrides=None,
    reference_overrides=None,
    submission_overrides=None,
    credit_headers=None,
    approve_headers=None,
    applicant_overrides=None,
    referee_overrides=None,
):
    """Drive one examination-route file forward and stop at a named stage.

    Returns a dict holding every row created along the way. Later keys are
    ``None`` when the requested stage is reached before they exist.
    """
    if stop_after not in EXAM_TRACK_STAGES:
        raise ValueError(f"unknown stage {stop_after!r}; expected one of {EXAM_TRACK_STAGES}")
    stages = EXAM_TRACK_STAGES
    reached = stages.index(stop_after)

    def wants(stage):
        return reached >= stages.index(stage)

    state = {
        "engineer": None,
        "referee": None,
        "referee_license": None,
        "application": None,
        "experience_record": None,
        "reference": None,
        "authorization": None,
    }

    engineer = create_engineer(api, **(applicant_overrides or {}))
    referee, referee_license = create_licensed_engineer(api, **(referee_overrides or {}))
    state["engineer"] = engineer
    state["referee"] = referee
    state["referee_license"] = referee_license

    application = create_application(api, engineer["id"], **(application_overrides or {}))
    state["application"] = application
    if not wants("education_evaluated"):
        return state

    state["application"] = evaluate_education(
        api, application["id"], **(education_overrides or {})
    )
    if not wants("experience_added"):
        return state

    state["experience_record"] = add_experience_record(
        api, application["id"], engineer["id"], **(experience_overrides or {})
    )
    if not wants("reference_requested"):
        return state

    state["reference"] = request_reference(
        api,
        state["experience_record"]["id"],
        engineer["id"],
        referee["id"],
        **(reference_overrides or {}),
    )
    if not wants("paid"):
        return state

    pay_assessed_fee(api, application["id"], engineer["id"])
    if not wants("submitted"):
        state["application"] = get_success_data(
            api.get_application(application["id"], make_applicant_headers(engineer["id"]))
        )
        return state

    state["application"] = submit_application(api, application["id"], engineer["id"])
    if not wants("reference_submitted"):
        return state

    state["reference"] = submit_reference(
        api, state["reference"]["id"], referee["id"], **(submission_overrides or {})
    )
    if not wants("under_review"):
        return state

    state["application"] = start_review(api, application["id"])
    if not wants("reference_accepted"):
        return state

    state["reference"] = evaluate_reference(api, state["reference"]["id"], "ACCEPT")
    if not wants("credit_determined"):
        return state

    state["application"] = determine_credit(api, application["id"], credit_headers)
    if not wants("exam_approved"):
        return state

    state["authorization"] = approve_exam(api, application["id"], approve_headers)
    state["application"] = get_success_data(
        api.get_application(application["id"], make_applicant_headers(engineer["id"]))
    )
    return state


def setup_scheduled_appointment(api, center_overrides=None, appointment_overrides=None, **kwargs):
    """An examination file approved to sit, with one seat booked at a centre."""
    track = setup_exam_track(api, stop_after="exam_approved", **kwargs)
    center = create_test_center(api, **(center_overrides or {}))
    appointment = book_appointment(
        api,
        track["authorization"]["id"],
        center["id"],
        track["engineer"]["id"],
        **(appointment_overrides or {}),
    )
    track["test_center"] = center
    track["appointment"] = appointment
    return track


def setup_cpc_report(
    api,
    license_overrides=None,
    report_overrides=None,
    engineer_overrides=None,
):
    """A licensee with one SUBMITTED competency report against their licence."""
    engineer, license_ = create_licensed_engineer(
        api, license_overrides=license_overrides, **(engineer_overrides or {})
    )
    report = create_cpc_report(
        api,
        license_["id"],
        engineer["id"],
        license_["version"],
        period_start=license_["current_period_start"],
        period_end=license_["current_period_end"],
        **(report_overrides or {}),
    )
    return {"engineer": engineer, "license": license_, "report": report}


def setup_cleared_cpc_report(api, **kwargs):
    """A competency report ACCEPTED with a shortfall of exactly 0.

    Thirty course hours are logged, two of them carrying ethics content, so both
    the hour requirement and the separate two-hour ethics floor are satisfied.
    """
    setup = setup_cpc_report(api, report_overrides={"self_certified_pdh": 30}, **kwargs)
    report = setup["report"]
    engineer_id = setup["engineer"]["id"]
    completed_on = setup["license"]["current_period_start"]
    add_pdh_record(
        api,
        report["id"],
        engineer_id,
        activity_type="COURSE",
        pdh_hours=28,
        completed_on=completed_on,
    )
    add_pdh_record(
        api,
        report["id"],
        engineer_id,
        activity_type="COURSE",
        pdh_hours=2,
        completed_on=completed_on,
        ethics_flag=True,
    )
    setup["report"] = accept_cpc_report(api, report["id"])
    return setup


def setup_firm_with_draft_plan(api, plan_overrides=None, **kwargs):
    """A registered firm behind an ACTIVE licence, holding one DRAFT plan set."""
    engineer, license_ = create_licensed_engineer(api, **kwargs)
    firm = create_firm(api, license_["id"])
    plan = create_plan_submission(api, firm["id"], **(plan_overrides or {}))
    return {"engineer": engineer, "license": license_, "firm": firm, "plan": plan}


def setup_case_at_probable_cause(api, case_overrides=None, finding_overrides=None):
    """A complaint investigated to PROBABLE_CAUSE with its penalty assessed."""
    engineer, license_ = create_licensed_engineer(api)
    case = create_case(
        api, respondent_license_id=license_["id"], **(case_overrides or {})
    )
    open_investigation(api, case["id"])
    case = record_finding(api, case["id"], **(finding_overrides or {}))
    return {"engineer": engineer, "license": license_, "case": case}
