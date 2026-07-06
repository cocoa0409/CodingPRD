"""Composite setup helpers.

Every test starts against an empty database, so these helpers rebuild all
preconditions from scratch using only PRD-declared endpoints. Setup calls go
through get_success_data() (lenient) so a broken precondition surfaces as a
clear "Setup failed" rather than a confusing assertion failure.

Most business operations are driven as Admin, which the PRD authorizes to
perform any peer-role operation (Section 2.1). Ownership-specific behavior is
exercised directly in the RBAC tests with make_sales_rep_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_appointment_payload,
    create_crew_payload,
    create_financing_plan_payload,
    create_lead_payload,
    create_product_payload,
    create_quote_payload,
    create_referral_payload,
    create_sales_rep_payload,
    create_warranty_claim_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]


def _data(resp):
    return get_success_data(resp)


# --------------------------------------------------------------------------- #
# Catalog / workforce
# --------------------------------------------------------------------------- #
def create_product(headers=ADMIN, **overrides) -> dict:
    return _data(api_client.create_product(create_product_payload(**overrides), headers))


def create_sales_rep(headers=ADMIN, **overrides) -> dict:
    return _data(api_client.create_sales_rep(create_sales_rep_payload(**overrides), headers))


def create_crew(headers=ADMIN, **overrides) -> dict:
    return _data(api_client.create_crew(create_crew_payload(**overrides), headers))


# --------------------------------------------------------------------------- #
# Leads / appointments
# --------------------------------------------------------------------------- #
def create_lead(sales_rep_id, headers=ADMIN, **overrides) -> dict:
    return _data(
        api_client.create_lead(create_lead_payload(sales_rep_id, **overrides), headers)
    )


def get_lead_version(lead_id, headers=ADMIN) -> int:
    return _data(api_client.get_lead(lead_id, headers))["version"]


def create_appointment(lead_id, sales_rep_id, headers=ADMIN, **overrides) -> dict:
    return _data(
        api_client.create_appointment(
            create_appointment_payload(lead_id, sales_rep_id, **overrides), headers
        )
    )


def transition_appointment(appointment_id, to_status, headers=ADMIN, **extra) -> dict:
    payload = {"to_status": to_status}
    payload.update(extra)
    return _data(api_client.transition_appointment(appointment_id, payload, headers))


def complete_appointment(appointment_id, measured_linear_feet, headers=ADMIN,
                         via_confirmed=False) -> dict:
    if via_confirmed:
        api_client.transition_appointment(
            appointment_id, {"to_status": "CONFIRMED"}, headers
        )
    return _data(
        api_client.transition_appointment(
            appointment_id,
            {"to_status": "COMPLETED", "measured_linear_feet": measured_linear_feet},
            headers,
        )
    )


# --------------------------------------------------------------------------- #
# Quotes
# --------------------------------------------------------------------------- #
def create_quote(lead_id, appointment_id, sales_rep_id, product_id, color,
                 estimated_linear_feet, headers=ADMIN, expected_lead_version=None,
                 **overrides) -> dict:
    """Create a quote, auto-fetching the lead's current version unless a caller
    passes expected_lead_version explicitly (used by the OCC tests)."""
    if expected_lead_version is None:
        expected_lead_version = get_lead_version(lead_id, headers)
    payload = create_quote_payload(
        lead_id, appointment_id, sales_rep_id, product_id, color,
        estimated_linear_feet, expected_lead_version, **overrides
    )
    return _data(api_client.create_quote(payload, headers))


def present_quote(quote_id, headers=ADMIN) -> dict:
    return _data(api_client.present_quote(quote_id, headers))


def accept_quote(quote_id, headers=ADMIN) -> dict:
    return _data(
        api_client.transition_quote(quote_id, {"to_status": "ACCEPTED"}, headers)
    )


# --------------------------------------------------------------------------- #
# Financing
# --------------------------------------------------------------------------- #
def create_financing_plan(quote_id, plan_type, apr_bps, term_months, headers=ADMIN,
                          **overrides) -> dict:
    return _data(
        api_client.create_financing_plan(
            create_financing_plan_payload(
                quote_id, plan_type, apr_bps, term_months, **overrides
            ),
            headers,
        )
    )


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #
def get_job_for_quote(quote_id, headers=ADMIN) -> dict:
    resp = api_client.list_jobs(headers, params={"quote_id": quote_id})
    jobs = _data(resp)
    assert jobs, f"Setup failed: no job found for quote {quote_id}"
    return jobs[0]


def schedule_job(job_id, crew_id, install_date, headers=ADMIN) -> dict:
    return _data(
        api_client.schedule_job(
            job_id, {"crew_id": crew_id, "install_date": install_date}, headers
        )
    )


def transition_job(job_id, to_status, headers=ADMIN, **extra) -> dict:
    payload = {"to_status": to_status}
    payload.update(extra)
    return _data(api_client.transition_job(job_id, payload, headers))


# --------------------------------------------------------------------------- #
# Warranty claims
# --------------------------------------------------------------------------- #
def create_warranty_claim(job_id, issue_type, headers=ADMIN) -> dict:
    return _data(
        api_client.create_warranty_claim(
            create_warranty_claim_payload(job_id, issue_type), headers
        )
    )


def transition_warranty_claim(claim_id, to_status, headers=ADMIN, **extra) -> dict:
    payload = {"to_status": to_status}
    payload.update(extra)
    return _data(api_client.transition_warranty_claim(claim_id, payload, headers))


# --------------------------------------------------------------------------- #
# Referrals
# --------------------------------------------------------------------------- #
def create_referral(referrer_lead_id, referee_lead_id, headers=ADMIN) -> dict:
    return _data(
        api_client.create_referral(
            create_referral_payload(referrer_lead_id, referee_lead_id), headers
        )
    )


# --------------------------------------------------------------------------- #
# Control planes
# --------------------------------------------------------------------------- #
def set_clock(iso8601, headers=ADMIN):
    return api_client.set_clock({"to_iso8601": iso8601}, headers)


def set_forecast(install_date, condition, headers=ADMIN):
    return api_client.set_forecast(
        {"install_date": install_date, "condition": condition}, headers
    )


# --------------------------------------------------------------------------- #
# Composite scenarios
# --------------------------------------------------------------------------- #
def setup_draft_quote(estimated_linear_feet=200, color="WHITE", measured_linear_feet=200,
                      downspout_count=0, discount_pct=0, complete_appt=True,
                      appt_via_confirmed=False, product_overrides=None,
                      headers=ADMIN) -> dict:
    """Product + rep + lead + appointment (+ optional COMPLETED) + a DRAFT quote.

    Returns {product, rep, lead, appointment, quote}. The quote is priced
    provisionally from estimated_linear_feet.
    """
    product = create_product(headers, **(product_overrides or {}))
    rep = create_sales_rep(headers)
    lead = create_lead(rep["id"], headers)
    appointment = create_appointment(lead["id"], rep["id"], headers)
    if complete_appt:
        complete_appointment(
            appointment["id"], measured_linear_feet, headers,
            via_confirmed=appt_via_confirmed,
        )
    quote = create_quote(
        lead["id"], appointment["id"], rep["id"], product["id"], color,
        estimated_linear_feet, headers,
        downspout_count=downspout_count, discount_pct=discount_pct,
    )
    return {
        "product": product, "rep": rep, "lead": lead,
        "appointment": appointment, "quote": quote,
    }


def setup_presented_quote(**kwargs) -> dict:
    """A DRAFT quote advanced to PRESENTED (final pricing from measured feet)."""
    scenario = setup_draft_quote(**kwargs)
    scenario["quote"] = present_quote(scenario["quote"]["id"])
    return scenario


def setup_accepted_quote(**kwargs) -> dict:
    """A PRESENTED quote accepted; the resulting PENDING Job is attached."""
    scenario = setup_presented_quote(**kwargs)
    scenario["quote"] = accept_quote(scenario["quote"]["id"])
    scenario["job"] = get_job_for_quote(scenario["quote"]["id"])
    return scenario


def setup_scheduled_job(install_date="2026-06-10", crew_certified=True,
                        measured_linear_feet=210, estimated_linear_feet=None,
                        color="WHITE", **kwargs) -> dict:
    """Full chain through a SCHEDULED Job on a fresh crew. Adds {crew}."""
    if estimated_linear_feet is None:
        estimated_linear_feet = measured_linear_feet
    scenario = setup_accepted_quote(
        estimated_linear_feet=estimated_linear_feet, color=color,
        measured_linear_feet=measured_linear_feet, **kwargs
    )
    crew = create_crew(is_certified_leaf_guard=crew_certified)
    scenario["crew"] = crew
    scenario["job"] = schedule_job(scenario["job"]["id"], crew["id"], install_date)
    return scenario


def setup_completed_job(install_date="2026-06-10",
                        in_progress_clock="2026-06-10T08:00:00Z",
                        measured_linear_feet=210, **kwargs) -> dict:
    """Full chain through a COMPLETED Job (ready for warranty claims)."""
    scenario = setup_scheduled_job(
        install_date=install_date, measured_linear_feet=measured_linear_feet, **kwargs
    )
    set_clock(in_progress_clock)
    transition_job(scenario["job"]["id"], "IN_PROGRESS")
    scenario["job"] = transition_job(scenario["job"]["id"], "COMPLETED")
    return scenario


def setup_two_jobs_same_crew(job1_feet=210, job2_feet=140,
                             job1_install_date="2026-06-10", crew_certified=True) -> dict:
    """Two accepted jobs on ONE crew: job1 already SCHEDULED on job1_install_date,
    job2 left PENDING. Their homeowners use non-overlapping measure windows.
    Returns {product, rep, crew, lead1, job1, lead2, job2}."""
    product = create_product()
    rep = create_sales_rep()
    crew = create_crew(is_certified_leaf_guard=crew_certified)

    lead1 = create_lead(rep["id"], full_name="HO Job1", address="1 Job St", phone="555-0301")
    appt1 = create_appointment(
        lead1["id"], rep["id"],
        scheduled_start="2026-06-01T10:00:00Z", scheduled_end="2026-06-01T11:00:00Z",
    )
    complete_appointment(appt1["id"], job1_feet)
    q1 = create_quote(lead1["id"], appt1["id"], rep["id"], product["id"], "WHITE", job1_feet)
    present_quote(q1["id"])
    accept_quote(q1["id"])
    job1 = get_job_for_quote(q1["id"])
    job1 = schedule_job(job1["id"], crew["id"], job1_install_date)

    lead2 = create_lead(rep["id"], full_name="HO Job2", address="2 Job St", phone="555-0302")
    appt2 = create_appointment(
        lead2["id"], rep["id"],
        scheduled_start="2026-06-03T10:00:00Z", scheduled_end="2026-06-03T11:00:00Z",
    )
    complete_appointment(appt2["id"], job2_feet)
    q2 = create_quote(lead2["id"], appt2["id"], rep["id"], product["id"], "WHITE", job2_feet)
    present_quote(q2["id"])
    accept_quote(q2["id"])
    job2 = get_job_for_quote(q2["id"])

    return {
        "product": product, "rep": rep, "crew": crew,
        "lead1": lead1, "job1": job1, "lead2": lead2, "job2": job2,
    }


def setup_referral_pending(measured_linear_feet=200, estimated_linear_feet=200,
                           color="WHITE") -> dict:
    """Referrer + referee leads, a PENDING Referral, and the referee's PRESENTED
    quote (ready to accept). Returns
    {product, rep, referrer, referee, referral, appointment, quote}."""
    product = create_product()
    rep = create_sales_rep()
    referrer = create_lead(
        rep["id"], full_name="Referrer R", address="10 Referrer Rd", phone="555-0200"
    )
    referee = create_lead(
        rep["id"], full_name="Referee E", address="11 Referee Rd", phone="555-0201"
    )
    referral = create_referral(referrer["id"], referee["id"])
    appointment = create_appointment(referee["id"], rep["id"])
    complete_appointment(appointment["id"], measured_linear_feet)
    quote = create_quote(
        referee["id"], appointment["id"], rep["id"], product["id"], color,
        estimated_linear_feet,
    )
    quote = present_quote(quote["id"])
    return {
        "product": product, "rep": rep, "referrer": referrer, "referee": referee,
        "referral": referral, "appointment": appointment, "quote": quote,
    }
