"""Composite setup helpers.

Each test starts against an empty store, so every precondition below is built
from scratch through the documented endpoints. Setup calls use the lenient
`get_success_data()` validator so that a broken precondition reports itself as a
setup failure rather than as a confusing assertion failure.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import SCENARIO_CLOCK_UTC
from . import factories as f
from .test_users import (
    ADMIN_USER_ID,
    OFFICER_USER_ID,
    OFFICER_USER_ID_ALT,
    SPECIALIST_USER_ID,
    TEST_USERS,
    make_authorized_officer_headers,
    make_outfitter_representative_headers,
    make_permit_specialist_headers,
    make_program_administrator_headers,
)

ADMIN = TEST_USERS["program_administrator_headers"]
SPECIALIST = TEST_USERS["permit_specialist_headers"]
OFFICER = TEST_USERS["authorized_officer_headers"]
OFFICER_ALT = TEST_USERS["authorized_officer_alt_headers"]


# --- Tier 0: operations ------------------------------------------------------

def set_clock(to_iso8601: str = SCENARIO_CLOCK_UTC) -> dict:
    """Reposition the logical clock. Writes no entity rows."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_sweep() -> dict:
    """Run the nightly compliance batch against the current logical clock."""
    return get_success_data(api_client.run_daily_compliance_sweep(ADMIN))


# --- Tier 1: single records --------------------------------------------------

def create_use_area(**overrides) -> dict:
    return get_success_data(
        api_client.create_use_area(f.use_area_payload(**overrides), ADMIN)
    )


def read_use_area(use_area_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_use_area(use_area_id, headers or ADMIN))


def read_allocation_summary(use_area_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_allocation_summary(use_area_id, headers or ADMIN)
    )


def create_outfitter(**overrides) -> dict:
    return get_success_data(
        api_client.create_outfitter(f.outfitter_payload(**overrides), SPECIALIST)
    )


def read_outfitter(outfitter_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_outfitter(outfitter_id, headers or SPECIALIST))


def verify_prequalification(outfitter_id: str, verified: bool = True) -> dict:
    return get_success_data(
        api_client.record_prequalification(
            outfitter_id, {"verified": verified}, SPECIALIST
        )
    )


def create_needs_assessment(use_area_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_needs_assessment(
            use_area_id, f.needs_assessment_payload(**overrides), SPECIALIST
        )
    )


def publish_needs_assessment(assessment_id: str) -> dict:
    return get_success_data(
        api_client.publish_needs_assessment(assessment_id, OFFICER)
    )


def create_published_assessment(use_area_id: str, **overrides) -> dict:
    """Draft an assessment against the area and publish it, so that the area's
    season year has a governing public-need finding."""
    assessment = create_needs_assessment(use_area_id, **overrides)
    return publish_needs_assessment(assessment["id"])


def read_needs_assessment_list(use_area_id: str, params=None) -> tuple:
    response = api_client.list_needs_assessments(use_area_id, ADMIN, params=params)
    body = response.json()
    return body["data"], body["meta"]


# --- Tier 2: applications ----------------------------------------------------

def create_application(outfitter_id: str, use_area_id: str, **overrides) -> dict:
    """Draft an application. Drafting holds no service days."""
    return get_success_data(
        api_client.create_permit_application(
            f.permit_application_payload(outfitter_id, use_area_id, **overrides),
            make_outfitter_representative_headers(outfitter_id),
        )
    )


def submit_application(application_id: str, outfitter_id: str) -> dict:
    return get_success_data(
        api_client.submit_permit_application(
            application_id, make_outfitter_representative_headers(outfitter_id)
        )
    )


def screen_application(application_id: str, specialist_user_id: str = SPECIALIST_USER_ID) -> dict:
    return get_success_data(
        api_client.screen_permit_application(
            application_id, make_permit_specialist_headers(specialist_user_id)
        )
    )


def create_submitted_application(outfitter_id: str, use_area_id: str, **overrides) -> dict:
    application = create_application(outfitter_id, use_area_id, **overrides)
    return submit_application(application["id"], outfitter_id)


def create_screened_application(outfitter_id: str, use_area_id: str, **overrides) -> dict:
    """Draft, submit and screen — the application now carries a service-day hold
    and a routing decision."""
    application = create_submitted_application(outfitter_id, use_area_id, **overrides)
    return screen_application(application["id"])


def read_application(application_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_permit_application(application_id, headers or ADMIN)
    )


# --- Tier 3: permits ---------------------------------------------------------

def issue_permit(application_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.issue_permit(application_id, f.issue_permit_payload(**overrides), OFFICER)
    )


def read_permit(permit_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_permit(permit_id, headers or ADMIN))


def setup_issued_permit(
    area_overrides: Optional[dict] = None,
    outfitter_overrides: Optional[dict] = None,
    assessment_overrides: Optional[dict] = None,
    application_overrides: Optional[dict] = None,
    permit_overrides: Optional[dict] = None,
    clock: Optional[str] = SCENARIO_CLOCK_UTC,
) -> dict:
    """Walk the intake pipeline to a permit standing in ISSUED.

    Opens a use area, publishes its public-need finding, registers an outfitter,
    drafts, submits and screens an application, then issues the permit.
    Returns a context dict with every record created along the way.
    """
    if clock:
        set_clock(clock)
    use_area = create_use_area(**(area_overrides or {}))
    assessment = create_published_assessment(use_area["id"], **(assessment_overrides or {}))
    outfitter = create_outfitter(**(outfitter_overrides or {}))
    application = create_screened_application(
        outfitter["id"], use_area["id"], **(application_overrides or {})
    )
    permit = issue_permit(application["id"], **(permit_overrides or {}))
    # Issuance moves the application on, so the context carries the record as it
    # stands after the cascade rather than the pre-issuance snapshot.
    application = read_application(application["id"])
    return {
        "use_area": use_area,
        "needs_assessment": assessment,
        "outfitter": outfitter,
        "application": application,
        "permit": permit,
        "holder_headers": make_outfitter_representative_headers(outfitter["id"]),
    }


# --- Tier 3: guides and roster authorizations --------------------------------

def create_guide(outfitter_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_guide(
            outfitter_id, f.guide_payload(**overrides),
            make_outfitter_representative_headers(outfitter_id),
        )
    )


def qualify_guide(guide_id: str) -> dict:
    return get_success_data(api_client.qualify_guide(guide_id, SPECIALIST))


def create_qualified_guide(outfitter_id: str, **overrides) -> dict:
    """Add a guide to the roster and qualify the certification."""
    guide = create_guide(outfitter_id, **overrides)
    return qualify_guide(guide["id"])


def read_guide(guide_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_guide(guide_id, headers or ADMIN))


def refile_certification(guide_id: str, outfitter_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.record_guide_certification(
            guide_id, f.certification_payload(**overrides),
            make_outfitter_representative_headers(outfitter_id),
        )
    )


def authorize_guide(permit_id: str, guide_id: str, outfitter_id: str) -> dict:
    return get_success_data(
        api_client.create_guide_authorization(
            permit_id, f.guide_authorization_payload(guide_id),
            make_outfitter_representative_headers(outfitter_id),
        )
    )


def revoke_authorization(authorization_id: str, outfitter_id: str,
                         reason_code: str = "HOLDER_REQUEST") -> dict:
    return get_success_data(
        api_client.revoke_guide_authorization(
            authorization_id, {"revocation_reason_code": reason_code},
            make_outfitter_representative_headers(outfitter_id),
        )
    )


def list_permit_authorizations(permit_id: str, params=None) -> tuple:
    response = api_client.list_permit_guide_authorizations(permit_id, ADMIN, params=params)
    body = response.json()
    return body["data"], body["meta"]


LEAD_WFR_GUIDE = {
    "full_name": "Rita Long",
    "qualification_level": "LEAD",
    "first_aid_cert_type": "WFR",
    "first_aid_expires_on": "2030-06-30",
    "seasons_experience": 7,
}

ASSISTANT_BASIC_GUIDE = {
    "full_name": "Ben Cruz",
    "qualification_level": "ASSISTANT",
    "first_aid_cert_type": "BASIC_FIRST_AID",
    "first_aid_expires_on": "2030-06-30",
    "seasons_experience": 2,
}


def staff_roster_to_party_size(context: dict) -> list:
    """Authorize enough guides that the permit's frozen capacity total reaches
    the area's maximum party size — the client-to-guide gate on activation.

    A LEAD guide holding a wilderness first responder certification and seven
    seasons carries a base capacity of ten, frozen at the area's per-guide
    maximum of eight; an ASSISTANT holding basic first aid carries four. The two
    together total twelve.
    """
    permit_id = context["permit"]["id"]
    outfitter_id = context["outfitter"]["id"]
    lead = create_qualified_guide(outfitter_id, **LEAD_WFR_GUIDE)
    assistant = create_qualified_guide(outfitter_id, **ASSISTANT_BASIC_GUIDE)
    return [
        authorize_guide(permit_id, lead["id"], outfitter_id),
        authorize_guide(permit_id, assistant["id"], outfitter_id),
    ], [lead, assistant]


# --- Tier 3: operating plans -------------------------------------------------

def create_operating_plan(permit_id: str, outfitter_id: str, plan_year: int = 2027,
                          **overrides) -> dict:
    return get_success_data(
        api_client.create_operating_plan(
            permit_id, f.operating_plan_payload(plan_year, **overrides),
            make_outfitter_representative_headers(outfitter_id),
        )
    )


def submit_operating_plan(plan_id: str, outfitter_id: str) -> dict:
    return get_success_data(
        api_client.submit_operating_plan(
            plan_id, make_outfitter_representative_headers(outfitter_id)
        )
    )


def start_plan_review(plan_id: str, reviewer_user_id: str = SPECIALIST_USER_ID) -> dict:
    return get_success_data(
        api_client.start_operating_plan_review(
            plan_id, make_permit_specialist_headers(reviewer_user_id)
        )
    )


def approve_operating_plan(plan_id: str, approver_user_id: str = OFFICER_USER_ID) -> dict:
    return get_success_data(
        api_client.approve_operating_plan(
            plan_id, make_authorized_officer_headers(approver_user_id)
        )
    )


def read_operating_plan(plan_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_operating_plan(plan_id, headers or ADMIN))


def create_approved_operating_plan(permit_id: str, outfitter_id: str,
                                   plan_year: int = 2027,
                                   reviewer_user_id: str = SPECIALIST_USER_ID,
                                   approver_user_id: str = OFFICER_USER_ID) -> dict:
    """File a complete plan and walk it to APPROVED. The approver is a different
    acting user from the reviewer, as the duty separation requires."""
    plan = create_operating_plan(permit_id, outfitter_id, plan_year)
    submit_operating_plan(plan["id"], outfitter_id)
    start_plan_review(plan["id"], reviewer_user_id)
    return approve_operating_plan(plan["id"], approver_user_id)


# --- Tier 3: insurance and bonding evidence ----------------------------------

def file_insurance_certificate(permit_id: str, outfitter_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_insurance_certificate(
            permit_id, f.insurance_certificate_payload(**overrides),
            make_outfitter_representative_headers(outfitter_id),
        )
    )


def file_bond(permit_id: str, outfitter_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_bond(
            permit_id, f.bond_payload(**overrides),
            make_outfitter_representative_headers(outfitter_id),
        )
    )


def list_insurance_certificates(permit_id: str, params=None) -> tuple:
    response = api_client.list_insurance_certificates(permit_id, ADMIN, params=params)
    body = response.json()
    return body["data"], body["meta"]


def list_bonds(permit_id: str, params=None) -> tuple:
    response = api_client.list_bonds(permit_id, ADMIN, params=params)
    body = response.json()
    return body["data"], body["meta"]


# --- Tier 4: activation ------------------------------------------------------

def satisfy_activation_gates(context: dict, plan_year: int = 2027,
                             coverage_amount_cents: Optional[int] = None,
                             bond_amount_cents: Optional[int] = None) -> dict:
    """Put every activation precondition in place without activating: a staffed
    roster reaching the area's maximum party size, an approved plan for the
    calendar year the term opens in, an endorsed general liability certificate
    covering the whole term and an active bond meeting the frozen requirement."""
    permit = context["permit"]
    outfitter_id = context["outfitter"]["id"]
    authorizations, guides = staff_roster_to_party_size(context)
    plan = create_approved_operating_plan(permit["id"], outfitter_id, plan_year)
    certificate = file_insurance_certificate(
        permit["id"], outfitter_id,
        coverage_amount_cents=(
            coverage_amount_cents
            if coverage_amount_cents is not None
            else context["use_area"]["min_liability_coverage_cents"]
        ),
        effective_date=permit["term_start_date"],
        expiration_date=permit["term_end_date"],
    )
    bond = file_bond(
        permit["id"], outfitter_id,
        bond_amount_cents=(
            bond_amount_cents
            if bond_amount_cents is not None
            else permit["authorized_service_days"] * 5_000
        ),
        effective_date=permit["term_start_date"],
        expiration_date=permit["term_end_date"],
    )
    context.update({
        "authorizations": authorizations,
        "guides": guides,
        "operating_plan": plan,
        "insurance_certificate": certificate,
        "bond": bond,
    })
    return context


def activate_permit(permit_id: str, officer_user_id: str = OFFICER_USER_ID) -> dict:
    return get_success_data(
        api_client.activate_permit(permit_id, make_authorized_officer_headers(officer_user_id))
    )


def setup_active_permit(**kwargs) -> dict:
    """Walk all the way to an ACTIVE permit with a staffed roster, an approved
    plan, endorsed liability coverage and an active bond."""
    plan_year = kwargs.pop("plan_year", 2027)
    context = setup_issued_permit(**kwargs)
    satisfy_activation_gates(context, plan_year=plan_year)
    context["permit"] = activate_permit(context["permit"]["id"])
    return context


# --- Tier 4: actual use and fees ---------------------------------------------

def file_use_report(permit_id: str, outfitter_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_trip_use_report(
            permit_id, f.trip_use_report_payload(**overrides),
            make_outfitter_representative_headers(outfitter_id),
        )
    )


def accept_use_report(report_id: str) -> dict:
    return get_success_data(api_client.accept_trip_use_report(report_id, SPECIALIST))


def file_and_accept_use_report(permit_id: str, outfitter_id: str, **overrides) -> dict:
    report = file_use_report(permit_id, outfitter_id, **overrides)
    return accept_use_report(report["id"])


def read_use_report(report_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_trip_use_report(report_id, headers or ADMIN))


def list_use_reports(params=None) -> tuple:
    response = api_client.list_trip_use_reports(ADMIN, params=params)
    body = response.json()
    return body["data"], body["meta"]


def list_fee_assessments(permit_id: str, params=None) -> tuple:
    response = api_client.list_fee_assessments(permit_id, ADMIN, params=params)
    body = response.json()
    return body["data"], body["meta"]


def sole_fee_assessment(permit_id: str) -> dict:
    """The assessment for the permit's only reported season. Assessments are
    discoverable only through the permit's own listing."""
    rows, _meta = list_fee_assessments(permit_id)
    assert len(rows) == 1, f"expected exactly one fee assessment, found {len(rows)}"
    return rows[0]


def read_fee_assessment(assessment_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_fee_assessment(assessment_id, headers or ADMIN))


def finalize_fee_assessment(assessment_id: str) -> dict:
    return get_success_data(api_client.finalize_fee_assessment(assessment_id, SPECIALIST))


def pay_fee_assessment(assessment_id: str, outfitter_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.create_fee_payment(
            assessment_id, f.payment_payload(amount_cents),
            make_outfitter_representative_headers(outfitter_id),
        )
    )


def amend_use_report(report_id: str, outfitter_id: str, expected_permit_version: int,
                     **overrides) -> dict:
    return get_success_data(
        api_client.amend_trip_use_report(
            report_id,
            f.amend_report_payload(expected_permit_version, **overrides),
            make_outfitter_representative_headers(outfitter_id),
        )
    )


# --- Tier 4: performance and enforcement -------------------------------------

def file_performance_evaluation(permit_id: str, evaluation_year: int = 2027,
                                officer_user_id: str = OFFICER_USER_ID,
                                **overrides) -> dict:
    return get_success_data(
        api_client.create_performance_evaluation(
            permit_id, f.performance_evaluation_payload(evaluation_year, **overrides),
            make_authorized_officer_headers(officer_user_id),
        )
    )


def issue_noncompliance_action(permit_id: str, officer_user_id: str = OFFICER_USER_ID,
                               **overrides) -> dict:
    return get_success_data(
        api_client.create_noncompliance_action(
            permit_id, f.noncompliance_action_payload(**overrides),
            make_authorized_officer_headers(officer_user_id),
        )
    )


def cure_action(action_id: str, outfitter_id: str, summary: str = "Corrected on site") -> dict:
    return get_success_data(
        api_client.cure_noncompliance_action(
            action_id, {"corrective_summary": summary},
            make_outfitter_representative_headers(outfitter_id),
        )
    )


def appeal_action(action_id: str, outfitter_id: str, basis: str = "Facts disputed") -> dict:
    return get_success_data(
        api_client.appeal_noncompliance_action(
            action_id, {"appeal_basis": basis},
            make_outfitter_representative_headers(outfitter_id),
        )
    )


def decide_appeal(action_id: str, decision: str,
                  officer_user_id: str = OFFICER_USER_ID_ALT) -> dict:
    return get_success_data(
        api_client.decide_noncompliance_appeal(
            action_id, {"decision": decision},
            make_authorized_officer_headers(officer_user_id),
        )
    )


def list_noncompliance_actions(permit_id: str, params=None) -> tuple:
    response = api_client.list_noncompliance_actions(permit_id, ADMIN, params=params)
    body = response.json()
    return body["data"], body["meta"]


# --- Tier 5: competitive solicitation ----------------------------------------

def create_prospectus(use_area_id: str, needs_assessment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_prospectus(
            f.prospectus_payload(use_area_id, needs_assessment_id, **overrides), SPECIALIST
        )
    )


def read_prospectus(prospectus_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_prospectus(prospectus_id, headers or ADMIN))


def respond_to_prospectus(prospectus_id: str, application_id: str, outfitter_id: str) -> dict:
    return get_success_data(
        api_client.create_prospectus_response(
            prospectus_id, f.prospectus_response_payload(application_id),
            make_outfitter_representative_headers(outfitter_id),
        )
    )


def close_prospectus_submissions(prospectus_id: str) -> dict:
    return get_success_data(
        api_client.close_prospectus_submissions(prospectus_id, SPECIALIST)
    )


def award_prospectus(prospectus_id: str, expected_use_area_version: int,
                     officer_user_id: str = OFFICER_USER_ID) -> dict:
    return get_success_data(
        api_client.award_prospectus(
            prospectus_id, {"expected_use_area_version": expected_use_area_version},
            make_authorized_officer_headers(officer_user_id),
        )
    )


def cancel_prospectus(prospectus_id: str, reason_code: str = "PROGRAM_WITHDRAWN") -> dict:
    return get_success_data(
        api_client.cancel_prospectus(
            prospectus_id, {"cancellation_reason_code": reason_code}, OFFICER
        )
    )


# A constrained area: three hundred total days less a hundred held back for
# administrative use leaves two hundred allocatable, so a larger request cannot
# be routed directly.
CONSTRAINED_AREA = {
    "area_code": "BRW-02",
    "name": "Bear River Canyon",
    "total_allocated_service_days": 300,
    "reserved_admin_service_days": 100,
}


def setup_queued_application(requested_service_days: int = 250,
                             area_overrides: Optional[dict] = None,
                             outfitter_overrides: Optional[dict] = None,
                             clock: Optional[str] = SCENARIO_CLOCK_UTC) -> dict:
    """Screen an application that asks for more days than the area can allocate,
    so the screen routes it to solicitation and parks it in PROSPECTUS_QUEUED."""
    if clock:
        set_clock(clock)
    area_payload = dict(CONSTRAINED_AREA)
    area_payload.update(area_overrides or {})
    use_area = create_use_area(**area_payload)
    assessment = create_published_assessment(
        use_area["id"],
        determined_capacity_service_days=use_area["allocatable_service_days"],
    )
    outfitter = create_outfitter(**(outfitter_overrides or {}))
    application = create_screened_application(
        outfitter["id"], use_area["id"],
        requested_service_days=requested_service_days,
    )
    return {
        "use_area": use_area,
        "needs_assessment": assessment,
        "outfitter": outfitter,
        "application": application,
        "holder_headers": make_outfitter_representative_headers(outfitter["id"]),
    }


def setup_prospectus_with_response(offered_service_days: int = 300,
                                   requested_service_days: int = 250,
                                   submission_deadline_date: str = "2027-03-31",
                                   with_guide: bool = True) -> dict:
    """A solicitation in EVALUATING with one scored response, ready to award."""
    context = setup_queued_application(requested_service_days=requested_service_days)
    if with_guide:
        context["guide"] = create_qualified_guide(
            context["outfitter"]["id"], **LEAD_WFR_GUIDE
        )
    prospectus = create_prospectus(
        context["use_area"]["id"], context["needs_assessment"]["id"],
        offered_service_days=offered_service_days,
        submission_deadline_date=submission_deadline_date,
    )
    respond_to_prospectus(
        prospectus["id"], context["application"]["id"], context["outfitter"]["id"]
    )
    context["prospectus"] = close_prospectus_submissions(prospectus["id"])
    return context


def current_use_area_version(use_area_id: str) -> int:
    """The concurrency token an award must echo."""
    return read_use_area(use_area_id)["version"]


def current_permit_version(permit_id: str) -> int:
    """The concurrency token an amendment must echo."""
    return read_permit(permit_id)["version"]
