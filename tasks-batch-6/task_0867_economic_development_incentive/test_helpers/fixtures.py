"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared endpoints
(the harness restarts the server against an empty DB before each test). Setup calls use
get_success_data() (lenient) so a broken precondition surfaces as a clear "Setup failed".

The dominant preamble across the suite is: create program -> create parcel -> create
application -> submit -> start-review -> approve -> execute agreement -> (activate). The
builders below expose that chain at several stopping points, plus follow-on helpers for
covenants, compliance reports, disbursements, default/recapture, and disclosures.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client as api
from .test_users import (
    TEST_USERS, make_applicant_headers, make_analyst_headers, make_director_headers,
)
from .factories import (
    create_program_payload, create_parcel_payload, create_application_payload,
    create_agreement_payload, create_covenant_payload, create_compliance_report_payload,
    create_disbursement_payload, create_disclosure_payload,
)

APPLICANT = TEST_USERS["applicant_headers"]
ANALYST = TEST_USERS["analyst_headers"]
DIRECTOR = TEST_USERS["director_headers"]
OFFICER = TEST_USERS["officer_headers"]
PUBLIC = TEST_USERS["public_headers"]


# --- Primitives -------------------------------------------------------------

def create_program(**overrides):
    return get_success_data(api.create_program(create_program_payload(**overrides), DIRECTOR))


def create_parcel(**overrides):
    return get_success_data(api.create_parcel(create_parcel_payload(**overrides), DIRECTOR))


def create_application(program_id, applicant_user_id="applicant-1", **overrides):
    payload = create_application_payload(program_id, applicant_user_id=applicant_user_id, **overrides)
    return get_success_data(api.create_application(payload, make_applicant_headers(applicant_user_id)))


def submit_application(app_id, applicant_user_id="applicant-1"):
    return get_success_data(api.submit_application(app_id, make_applicant_headers(applicant_user_id)))


def start_review(app_id, reviewer_user_id="analyst-1", **payload):
    return get_success_data(api.start_review(app_id, make_analyst_headers(reviewer_user_id), payload or None))


def approve_application(app_id, director_user_id="director-1"):
    return get_success_data(api.approve_application(app_id, make_director_headers(director_user_id)))


def execute_agreement(application_id, parcel_id, **overrides):
    payload = create_agreement_payload(application_id, parcel_id, **overrides)
    return get_success_data(api.create_agreement(payload, DIRECTOR))


def activate_agreement(agr_id):
    return get_success_data(api.activate_agreement(agr_id, DIRECTOR))


def agreement_version(agr_id):
    return get_success_data(api.get_agreement(agr_id, DIRECTOR))["version"]


def add_covenant(agr_id, **overrides):
    return get_success_data(api.create_covenant(agr_id, create_covenant_payload(**overrides), DIRECTOR))


def submit_report(agr_id, applicant_user_id="applicant-1", **overrides):
    payload = create_compliance_report_payload(**overrides)
    return get_success_data(api.create_compliance_report(agr_id, payload, make_applicant_headers(applicant_user_id)))


def accept_report(rep_id):
    return get_success_data(api.accept_report(rep_id, ANALYST))


def create_disbursement(agr_id, rep_id, version=None):
    if version is None:
        version = agreement_version(agr_id)
    payload = create_disbursement_payload(agr_id, rep_id, version)
    return get_success_data(api.create_disbursement(payload, OFFICER))


def pay_disbursement_full(disb_id):
    get_success_data(api.approve_disbursement(disb_id, OFFICER))
    return get_success_data(api.pay_disbursement(disb_id, OFFICER))


def declare_default(agr_id, severity="PARTIAL", reason="breach"):
    return get_success_data(api.declare_default(agr_id, DIRECTOR, {"severity": severity, "reason": reason}))


def recapture_for_agreement(agr_id):
    rows = get_success_data(api.list_recapture_assessments(OFFICER, params={"agreement_id": agr_id}))
    assert rows, f"Setup failed: no recapture assessment for agreement {agr_id}"
    return rows[0]


def create_disclosure(agr_id, disclosure_year=2027):
    return get_success_data(api.create_disclosure(agr_id, create_disclosure_payload(disclosure_year), OFFICER))


# --- Composite builders -----------------------------------------------------

def setup_approved_application(program_overrides=None, app_overrides=None,
                               applicant_user_id="applicant-1", reviewer_user_id="analyst-1",
                               director_user_id="director-1", with_parcel=True):
    """Create program (+parcel) -> application -> submit -> start-review -> approve.
    Returns dict with program, parcel (or None), application, review."""
    program = create_program(**(program_overrides or {}))
    parcel = create_parcel() if with_parcel else None
    app = create_application(program["id"], applicant_user_id=applicant_user_id, **(app_overrides or {}))
    submit_application(app["id"], applicant_user_id)
    review = start_review(app["id"], reviewer_user_id)
    approve_application(app["id"], director_user_id)
    return {"program": program, "parcel": parcel, "application": app, "review": review}


def setup_executed_agreement(program_overrides=None, app_overrides=None, agreement_overrides=None,
                             applicant_user_id="applicant-1"):
    """Approved application -> execute agreement (EXECUTED, not activated).
    Returns dict with program, parcel, application, review, agreement."""
    ctx = setup_approved_application(program_overrides=program_overrides, app_overrides=app_overrides,
                                     applicant_user_id=applicant_user_id)
    agr = execute_agreement(ctx["application"]["id"], ctx["parcel"]["id"], **(agreement_overrides or {}))
    ctx["agreement"] = agr
    return ctx


def setup_active_agreement(program_overrides=None, app_overrides=None, agreement_overrides=None,
                           applicant_user_id="applicant-1"):
    """Approved application -> execute -> activate (ACTIVE). Returns the same context dict."""
    ctx = setup_executed_agreement(program_overrides=program_overrides, app_overrides=app_overrides,
                                   agreement_overrides=agreement_overrides, applicant_user_id=applicant_user_id)
    activate_agreement(ctx["agreement"]["id"])
    ctx["agreement"] = get_success_data(api.get_agreement(ctx["agreement"]["id"], DIRECTOR))
    return ctx


def setup_active_grant_with_accepted_report(actual_jobs=80, actual_investment_cents=150_000_000,
                                            agreement_overrides=None):
    """Active GRANT agreement with one ACCEPTED compliance report (no covenants).
    Returns dict adding report to the active-agreement context."""
    ctx = setup_active_agreement(agreement_overrides=agreement_overrides,
                                 app_overrides={"but_for_attested": True})
    rep = submit_report(ctx["agreement"]["id"], actual_jobs=actual_jobs,
                        actual_investment_cents=actual_investment_cents, attestation=True)
    accept_report(rep["id"])
    ctx["report"] = rep
    return ctx


def setup_paid_grant_disbursement(actual_jobs=100, agreement_overrides=None):
    """Active GRANT agreement, one ACCEPTED report, one PAID disbursement.
    Returns context dict adding report, disbursement."""
    ctx = setup_active_grant_with_accepted_report(actual_jobs=actual_jobs,
                                                  agreement_overrides=agreement_overrides)
    agr_id = ctx["agreement"]["id"]
    disb = create_disbursement(agr_id, ctx["report"]["id"])
    pay_disbursement_full(disb["id"])
    ctx["disbursement"] = get_success_data(api.get_disbursement(disb["id"], OFFICER))
    ctx["agreement"] = get_success_data(api.get_agreement(agr_id, DIRECTOR))
    return ctx
