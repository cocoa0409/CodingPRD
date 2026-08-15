"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty database) before
every test. Helpers use get_success_data() so setup failures surface as
clear errors rather than assertion noise.

Identity threading: entity-backed roles (Landlord, Applicant) always use
make_landlord_headers(entity["id"]) / make_applicant_headers(entity["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCKS, CRITERIA_WINDOW, TEST_DEFAULTS
from .factories import (
    create_applicant_payload,
    create_application_payload,
    create_criteria_payload,
    create_guarantor_payload,
    create_income_verification_payload,
    create_jurisdiction_rule_payload,
    create_landlord_payload,
    evaluate_guarantor_payload,
    record_searches_payload,
    resolve_income_verified_payload,
    verify_identity_payload,
)
from .test_users import TEST_USERS, make_applicant_headers, make_landlord_headers, make_screener_headers

ADMIN = TEST_USERS["admin_headers"]
SCREENER = TEST_USERS["screener_headers"]
SCR1 = TEST_USERS["screener_1_headers"]
SCR2 = TEST_USERS["screener_2_headers"]


def set_clock(to_iso8601=CLOCKS["START"]):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp)


def create_landlord(name="Test Landlord", **overrides):
    payload = create_landlord_payload(name=name, **overrides)
    resp = api_client.create_landlord(payload, ADMIN)
    return get_success_data(resp)


def create_jurisdiction_rule(**overrides):
    resp = api_client.create_jurisdiction_rule(create_jurisdiction_rule_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_applicant(**overrides):
    resp = api_client.create_applicant(create_applicant_payload(**overrides), SCREENER)
    return get_success_data(resp)


def create_published_criteria(landlord, **overrides):
    """Create + publish a criteria set for the landlord. Returns the criteria."""
    ll_headers = make_landlord_headers(landlord["id"])
    resp = api_client.create_criteria(create_criteria_payload(**overrides), ll_headers)
    criteria = get_success_data(resp)
    resp = api_client.publish_criteria(
        criteria["id"], {"expected_landlord_version": landlord["version"]}, ll_headers
    )
    return get_success_data(resp)


def create_application(landlord, applicant, **overrides):
    payload = create_application_payload(applicant_id=applicant["id"], **overrides)
    resp = api_client.create_application(payload, make_landlord_headers(landlord["id"]))
    return get_success_data(resp)


def consent_application(application, applicant):
    resp = api_client.consent_application(application["id"], make_applicant_headers(applicant["id"]))
    return get_success_data(resp)


def verify_identity(application, evidence_score=85, method="KNOWLEDGE_BASED"):
    resp = api_client.verify_identity(application["id"], verify_identity_payload(method, evidence_score), SCREENER)
    return get_success_data(resp)


def submit_application(application, landlord):
    resp = api_client.submit_application(application["id"], make_landlord_headers(landlord["id"]))
    return get_success_data(resp)


def run_record_searches(application, credit_score=TEST_DEFAULTS["CREDIT_SCORE"], records=None, screener_headers=None):
    resp = api_client.record_searches(
        application["id"],
        record_searches_payload(credit_score, records),
        screener_headers or SCREENER,
    )
    return get_success_data(resp)


def create_and_resolve_income_verification(application, verified_amount=TEST_DEFAULTS["INCOME_CENTS"]):
    resp = api_client.create_income_verification(
        application["id"], create_income_verification_payload(), SCREENER
    )
    iv = get_success_data(resp)
    resp = api_client.resolve_income_verification(
        iv["id"], resolve_income_verified_payload(verified_amount), SCREENER
    )
    return get_success_data(resp)


def score_application(application):
    resp = api_client.score_application(application["id"], SCREENER)
    return get_success_data(resp)


def deliver_report(report, screener_headers=None):
    resp = api_client.deliver_report(report["id"], screener_headers or SCREENER)
    return get_success_data(resp)


def get_application(application_id):
    return get_success_data(api_client.get_application(application_id, ADMIN))


def get_report(report_id):
    return get_success_data(api_client.get_report(report_id, ADMIN))


def get_record(record_id):
    return get_success_data(api_client.get_record(record_id, ADMIN))


def get_landlord(landlord_id):
    return get_success_data(api_client.get_landlord(landlord_id, ADMIN))


def list_records(report_id):
    return get_success_data(api_client.list_records(ADMIN, params={"report_id": report_id}))


def list_notices(application_id):
    return get_success_data(api_client.list_notices(ADMIN, params={"application_id": application_id}))


def get_dispute(dispute_id):
    return get_success_data(api_client.get_dispute(dispute_id, ADMIN))


def get_guarantor(guarantor_id):
    return get_success_data(api_client.get_guarantor(guarantor_id, ADMIN))


def get_criteria(criteria_id):
    return get_success_data(api_client.get_criteria(criteria_id, ADMIN))


def get_income_verification(verification_id):
    return get_success_data(api_client.get_income_verification(verification_id, ADMIN))


# ---------------------------------------------------------------------------
# Composite fixtures
# ---------------------------------------------------------------------------

def setup_landlord_with_criteria(clock=CLOCKS["START"], jurisdiction_rule=None, criteria_overrides=None):
    """Clock set, optional jurisdiction rule, landlord + PUBLISHED criteria.

    Returns (landlord, criteria). The landlord dict is refreshed after publish
    so landlord["version"] reflects the post-publish increment.
    """
    set_clock(clock)
    if jurisdiction_rule is not None:
        create_jurisdiction_rule(**jurisdiction_rule)
    landlord = create_landlord()
    criteria = create_published_criteria(landlord, **(criteria_overrides or {}))
    landlord = get_landlord(landlord["id"])
    return landlord, criteria


def setup_application_flow(
    landlord=None,
    applicant=None,
    records=None,
    credit_score=TEST_DEFAULTS["CREDIT_SCORE"],
    verified_income=TEST_DEFAULTS["INCOME_CENTS"],
    screener_headers=None,
    **application_overrides,
):
    """Walk an application to SCORED with a delivered report.

    Expects a landlord that already has a PUBLISHED criteria. Returns a dict
    with keys: application, report, records, income_verification.
    """
    applicant = applicant or create_applicant()
    app = create_application(landlord, applicant, **application_overrides)
    consent_application(app, applicant)
    verify_identity(app)
    app = submit_application(app, landlord)
    report = run_record_searches(app, credit_score=credit_score, records=records,
                                 screener_headers=screener_headers)
    iv = create_and_resolve_income_verification(app, verified_income)
    app = score_application(app)
    report = deliver_report(report)
    recs = list_records(report["id"])
    return {
        "application": get_application(app["id"]),
        "applicant": applicant,
        "report": report,
        "records": recs,
        "income_verification": iv,
    }


def setup_submitted_application(landlord, applicant=None, **application_overrides):
    """Consent + verify + submit. Returns (application, applicant)."""
    applicant = applicant or create_applicant()
    app = create_application(landlord, applicant, **application_overrides)
    consent_application(app, applicant)
    verify_identity(app)
    app = submit_application(app, landlord)
    return get_application(app["id"]), applicant


def setup_draft_application(landlord, applicant=None, **application_overrides):
    """Just a DRAFT application (no consent, no identity)."""
    applicant = applicant or create_applicant()
    app = create_application(landlord, applicant, **application_overrides)
    return get_application(app["id"]), applicant
