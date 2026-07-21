"""Composite setup helpers.

These encapsulate the multi-step preambles the interesting claims require:
program + income limit + funding source + applicant + property + education +
application + award + allocation + closing, walked to a target lifecycle stage.

Every helper accepts the live ApiClient as its first argument and returns a
context dict (`ctx`) whose keys hold the created resource objects and their
ids, so callers can thread ids into follow-up trigger calls.

All applicant actions are threaded through make_applicant_headers(applicant_id)
because the Applicant role is entity-backed (PRD Section 2.1): the acting
X-User-ID must equal the applicant's own id or the ownership check rejects it.
Setup calls use get_success_data() so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing downstream assertion.
"""
from prd_bench_local_runner.testing import get_success_data
from .factories import (
    create_program_payload,
    create_income_limit_payload,
    create_applicant_payload,
    create_property_payload,
    create_application_payload,
    create_education_session_payload,
    create_funding_source_payload,
    create_funding_allocation_payload,
    create_closing_payload,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_case_manager_headers,
)

PROGRAM_ADMIN = TEST_USERS["program_admin_headers"]
CASE_MANAGER = TEST_USERS["case_manager_headers"]
CLOSING_COORDINATOR = TEST_USERS["closing_coordinator_headers"]
SERVICER = TEST_USERS["servicer_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


# --- Logical clock ----------------------------------------------------------
def set_clock(api, to_iso8601: str):
    """Advance the server logical clock (PRD Section 2.6)."""
    return get_success_data(api.set_clock(to_iso8601, PROGRAM_ADMIN))


# --- Primitives -------------------------------------------------------------
def new_program(api, **overrides) -> dict:
    return get_success_data(api.create_program(create_program_payload(**overrides), PROGRAM_ADMIN))


def new_income_limit(api, program_id, **overrides) -> dict:
    return get_success_data(
        api.create_income_limit(program_id, create_income_limit_payload(**overrides), PROGRAM_ADMIN)
    )


def new_funding_source(api, **overrides) -> dict:
    return get_success_data(api.create_funding_source(create_funding_source_payload(**overrides), PROGRAM_ADMIN))


def new_applicant(api, **overrides) -> dict:
    return get_success_data(api.create_applicant(create_applicant_payload(**overrides), ANONYMOUS))


def new_property(api, **overrides) -> dict:
    return get_success_data(api.create_property(create_property_payload(**overrides), CASE_MANAGER))


def record_appraisal(api, property_id, appraised_value_cents) -> dict:
    return get_success_data(
        api.record_appraisal(property_id, {"appraised_value_cents": appraised_value_cents}, CASE_MANAGER)
    )


def new_education_session(api, program_id, **overrides) -> dict:
    payload = create_education_session_payload(program_id=program_id, **overrides)
    return get_success_data(api.create_education_session(payload, PROGRAM_ADMIN))


def enroll(api, session_id, applicant_id) -> dict:
    return get_success_data(
        api.create_enrollment(session_id, {"applicant_id": applicant_id}, make_applicant_headers(applicant_id))
    )


def attend(api, enrollment_id) -> dict:
    return get_success_data(api.attend_enrollment(enrollment_id, PROGRAM_ADMIN))


def new_application(api, applicant_id, program_id, property_id, **overrides) -> dict:
    payload = create_application_payload(
        applicant_id=applicant_id, program_id=program_id, property_id=property_id, **overrides
    )
    return get_success_data(api.create_application(payload, CASE_MANAGER))


def submit(api, application_id, applicant_id) -> dict:
    return get_success_data(api.submit_application(application_id, make_applicant_headers(applicant_id)))


def review(api, application_id, decision, reviewer_id, review_notes=None) -> dict:
    payload = {"decision": decision}
    if review_notes is not None:
        payload["review_notes"] = review_notes
    return get_success_data(
        api.review_application(application_id, payload, make_case_manager_headers(reviewer_id))
    )


def review_to_eligible(api, application_id, reviewer_id="cm_reviewer") -> dict:
    review(api, application_id, "START", reviewer_id)
    return review(api, application_id, "ELIGIBLE", reviewer_id)


def new_award(api, application_id, assistance_type="SHARED_APPRECIATION", cm_id="cm_creator") -> dict:
    return get_success_data(
        api.create_award(application_id, {"assistance_type": assistance_type}, make_case_manager_headers(cm_id))
    )


def approve(api, award_id, approver_id="cm_approver") -> dict:
    return get_success_data(api.approve_award(award_id, make_case_manager_headers(approver_id)))


def allocate(api, award_id, funding_source_id, amount_cents, lien_position, expected_version) -> dict:
    payload = create_funding_allocation_payload(
        award_id=award_id,
        funding_source_id=funding_source_id,
        amount_cents=amount_cents,
        lien_position=lien_position,
        expected_funding_source_version=expected_version,
    )
    return get_success_data(api.create_funding_allocation(payload, CASE_MANAGER))


def schedule_closing(api, award_id, property_id, **overrides) -> dict:
    payload = create_closing_payload(property_id=property_id, **overrides)
    return get_success_data(api.schedule_closing(award_id, payload, CLOSING_COORDINATOR))


def docs_pending(api, closing_id) -> dict:
    return get_success_data(api.closing_docs_pending(closing_id, CLOSING_COORDINATOR))


def complete_closing(api, closing_id, final_purchase_price_cents, final_first_mortgage_cents) -> dict:
    payload = {
        "final_purchase_price_cents": final_purchase_price_cents,
        "final_first_mortgage_cents": final_first_mortgage_cents,
    }
    return get_success_data(api.complete_closing(closing_id, payload, CLOSING_COORDINATOR))


def servicing_by_award(api, award_id) -> dict:
    resp = api.list_servicing_accounts(SERVICER, params={"award_id": award_id})
    data = get_success_data(resp)
    accounts = data if isinstance(data, list) else data.get("data") or data
    assert accounts, f"Setup failed: no servicing account for award {award_id}"
    return accounts[0]


# --- Composite: an ELIGIBLE application, no education yet --------------------
def setup_eligible_application(api, *, with_education=True, reviewer_id="cm_reviewer",
                               attend_clock="2026-07-02T13:00:00Z", **cfg) -> dict:
    """Program + income limit + applicant + property + (optionally education &
    certificate) + application driven to ELIGIBLE. Returns the full ctx."""
    program = new_program(
        api,
        ami_limit_pct=cfg.get("ami_limit_pct", 80),
        max_assistance_cents=cfg.get("max_assistance_cents", 5_000_000),
        recapture_model=cfg.get("recapture_model", "SHARED_APPRECIATION"),
        **{k: cfg[k] for k in ("recapture_term_months", "appreciation_share_pct") if k in cfg},
    )
    income_limit = new_income_limit(
        api, program["id"],
        household_size=cfg.get("household_size", 4),
        ami_100_income_cents=cfg.get("ami_100_income_cents", 10_000_000),
    )
    applicant = new_applicant(
        api,
        household_size=cfg.get("household_size", 4),
        annual_income_cents=cfg.get("annual_income_cents", 8_000_000),
    )
    prop = new_property(api, purchase_price_cents=cfg.get("purchase_price_cents", 30_000_000))

    certificate = None
    enrollment = None
    session = None
    if with_education:
        session = new_education_session(api, program["id"])
        enrollment = enroll(api, session["id"], applicant["id"])
        set_clock(api, attend_clock)
        attend(api, enrollment["id"])

    application = new_application(
        api, applicant["id"], program["id"], prop["id"],
        first_mortgage_amount_cents=cfg.get("first_mortgage_amount_cents", 24_000_000),
        buyer_contribution_cents=cfg.get("buyer_contribution_cents", 500_000),
    )
    submit(api, application["id"], applicant["id"])
    application = review_to_eligible(api, application["id"], reviewer_id)

    return {
        "program": program,
        "income_limit": income_limit,
        "applicant": applicant,
        "property": prop,
        "session": session,
        "enrollment": enrollment,
        "certificate": certificate,
        "application": application,
        "reviewer_id": reviewer_id,
    }


# --- Composite: an APPROVED award (with funding source available) -----------
def setup_approved_award(api, *, assistance_type="SHARED_APPRECIATION",
                         approver_id="cm_approver", with_funding_source=True,
                         total_appropriation_cents=10_000_000, priority=1, **cfg) -> dict:
    ctx = setup_eligible_application(api, **cfg)
    award = new_award(api, ctx["application"]["id"], assistance_type, cm_id="cm_creator")
    award = approve(api, award["id"], approver_id)
    ctx["award"] = award
    if with_funding_source:
        ctx["funding_source"] = new_funding_source(
            api, priority=priority, total_appropriation_cents=total_appropriation_cents
        )
    return ctx


# --- Composite: a FUNDED award (fully reserved from one source) -------------
def setup_funded_award(api, *, alloc_amount=5_000_000, **cfg) -> dict:
    ctx = setup_approved_award(api, **cfg)
    fs = ctx["funding_source"]
    allocation = allocate(api, ctx["award"]["id"], fs["id"], alloc_amount, 1, fs["version"])
    ctx["allocation"] = allocation
    return ctx


# --- Composite: an ACTIVE servicing account (closing completed) -------------
def setup_servicing_account(api, *, appraised_value_cents=31_000_000,
                            scheduled_date="2026-08-01T00:00:00Z", window_days=7,
                            final_purchase_price_cents=30_000_000,
                            final_first_mortgage_cents=24_000_000,
                            complete_clock=None, alloc_amount=5_000_000, **cfg) -> dict:
    ctx = setup_approved_award(api, **cfg)
    prop = ctx["property"]
    record_appraisal(api, prop["id"], appraised_value_cents)
    fs = ctx["funding_source"]
    ctx["allocation"] = allocate(api, ctx["award"]["id"], fs["id"], alloc_amount, 1, fs["version"])
    closing = schedule_closing(
        api, ctx["award"]["id"], prop["id"], scheduled_date=scheduled_date, window_days=window_days
    )
    docs_pending(api, closing["id"])
    if complete_clock is not None:
        set_clock(api, complete_clock)
    complete_closing(api, closing["id"], final_purchase_price_cents, final_first_mortgage_cents)
    ctx["closing"] = closing
    ctx["servicing_account"] = servicing_by_award(api, ctx["award"]["id"])
    return ctx
