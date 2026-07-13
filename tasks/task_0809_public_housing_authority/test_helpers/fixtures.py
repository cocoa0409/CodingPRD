"""Composite setup helpers for the PHA API.

Every helper takes the `api` client as its first argument and drives the empty,
freshly-restarted database into a described precondition using only PRD-declared
endpoints. Setup calls use get_success_data() (lenient) so a broken precondition
surfaces as a clear "Setup failed" rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data
from . import factories as f
from .test_users import TEST_USERS, make_applicant_headers
from .constants import FAR_FUTURE_EXPIRY, HIGH_INCOME_LIMIT_CENTS

IC = TEST_USERS["intake_clerk_headers"]
HS = TEST_USERS["housing_specialist_headers"]
PM = TEST_USERS["property_manager_headers"]


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------
def set_clock(api, iso: str):
    return get_success_data(api.set_clock({"to_iso8601": iso}, IC))


def create_applicant(api, household_name="Household"):
    return get_success_data(api.create_applicant(f.applicant_payload(household_name), IC))


def add_member(api, applicant_id, full_name="Head", relationship="HEAD", **overrides):
    payload = f.member_payload(full_name=full_name, relationship=relationship, **overrides)
    return get_success_data(api.add_member(applicant_id, payload, IC))


def claim_preference(api, applicant_id, preference_type="VETERAN"):
    return get_success_data(
        api.create_preference_claim(applicant_id, f.preference_claim_payload(preference_type), IC)
    )


def verify_claim(api, claim_id, decision="VERIFY"):
    return get_success_data(api.verify_preference_claim(claim_id, {"decision": decision}, IC))


def revoke_claim(api, claim_id):
    return get_success_data(api.revoke_preference_claim(claim_id, IC))


def create_waitlist(api, bedroom_size=2, site_name="Site A", status=None):
    payload = f.waitlist_payload(site_name=site_name, bedroom_size=bedroom_size)
    if status is not None:
        payload["status"] = status
    return get_success_data(api.create_waitlist(payload, IC))


def enroll(api, waitlist_id, applicant_id):
    return get_success_data(api.create_entry(waitlist_id, {"applicant_id": applicant_id}, IC))


def draw(api, waitlist_id):
    return get_success_data(api.lottery_draw(waitlist_id, IC))


def create_unit(api, bedroom_size=2, income_limit_cents=HIGH_INCOME_LIMIT_CENTS,
                utility_allowance_cents=0, address_label="Unit"):
    payload = f.unit_payload(
        address_label=address_label,
        bedroom_size=bedroom_size,
        income_limit_cents=income_limit_cents,
        utility_allowance_cents=utility_allowance_cents,
    )
    return get_success_data(api.create_unit(payload, PM))


def create_offer(api, entry_id, unit_id, expires_at=FAR_FUTURE_EXPIRY):
    return get_success_data(api.create_offer(f.offer_payload(entry_id, unit_id, expires_at), HS))


def accept_offer(api, offer_id, applicant_id):
    return get_success_data(api.accept_offer(offer_id, make_applicant_headers(applicant_id)))


def refuse_offer(api, offer_id, applicant_id):
    return get_success_data(api.refuse_offer(offer_id, make_applicant_headers(applicant_id)))


def create_certification(api, tenancy_id, cert_type, effective_date, expected_tenancy_version,
                         **deductions):
    payload = f.certification_payload(cert_type, effective_date, expected_tenancy_version, **deductions)
    return get_success_data(api.create_certification(tenancy_id, payload, HS))


def finalize_certification(api, cert_id):
    return get_success_data(api.finalize_certification(cert_id, HS))


def report_interim_change(api, tenancy_id, applicant_id, change_type, effective_date):
    payload = f.interim_change_payload(change_type, effective_date)
    return get_success_data(api.create_interim_change(tenancy_id, payload, make_applicant_headers(applicant_id)))


def process_interim_change(api, interim_change_id, decision="PROCESS"):
    return get_success_data(api.process_interim_change(interim_change_id, {"decision": decision}, HS))


def file_grievance(api, tenancy_id, grievance_type, reason="cause", *, as_applicant=None):
    payload = f.grievance_payload(grievance_type, reason)
    headers = make_applicant_headers(as_applicant) if as_applicant else PM
    return get_success_data(api.create_grievance(tenancy_id, payload, headers))


def decide_grievance(api, grievance_id, outcome):
    return get_success_data(api.decide_grievance(grievance_id, {"outcome": outcome}, PM))


def get_initial_certification(api, tenancy_id):
    """Return the sole INITIAL certification created by an accept cascade."""
    data, _meta = _list(api.list_certifications(HS, params={"tenancy_id": tenancy_id}))
    return data[0]


def get_certification_by_source_interim(api, interim_change_id):
    data, _meta = _list(api.list_certifications(HS, params={"source_interim_change_id": interim_change_id}))
    return data[0]


def _list(response):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)


# ---------------------------------------------------------------------------
# Composite: drawn ACTIVE entry (no offer yet)
# ---------------------------------------------------------------------------
def setup_drawn_active_entry(api, *, bedroom_size=2, member_income=2400000,
                             applicant_name="Household", site_name="Site A"):
    """One applicant with a single HEAD member on a freshly drawn waitlist, whose
    entry is now ACTIVE. Returns dict with applicant, waitlist, entry_id."""
    app = create_applicant(api, applicant_name)
    add_member(api, app["id"], full_name="Head", relationship="HEAD",
               annual_income_cents=member_income)
    wl = create_waitlist(api, bedroom_size=bedroom_size, site_name=site_name)
    entry = enroll(api, wl["id"], app["id"])
    draw(api, wl["id"])
    return {"applicant": app, "waitlist": wl, "entry_id": entry["id"]}


# ---------------------------------------------------------------------------
# Composite: ACTIVE tenancy (accepted offer)
# ---------------------------------------------------------------------------
def setup_active_tenancy(api, *, members=None, bedroom_size=2,
                         income_limit_cents=HIGH_INCOME_LIMIT_CENTS,
                         utility_allowance_cents=0, expires_at=FAR_FUTURE_EXPIRY,
                         applicant_name="Household"):
    """Full preamble: applicant + members -> waitlist -> entry -> draw -> unit ->
    offer -> accept. Returns dict with applicant, entry_id, unit, offer, tenancy.
    `members` is a list of member_payload override dicts; defaults to one HEAD
    member with 2,400,000 recurring income."""
    if members is None:
        members = [{"full_name": "Head", "relationship": "HEAD", "annual_income_cents": 2400000}]
    app = create_applicant(api, applicant_name)
    for spec in members:
        add_member(api, app["id"], **spec)
    wl = create_waitlist(api, bedroom_size=bedroom_size)
    entry = enroll(api, wl["id"], app["id"])
    draw(api, wl["id"])
    unit = create_unit(api, bedroom_size=bedroom_size, income_limit_cents=income_limit_cents,
                       utility_allowance_cents=utility_allowance_cents)
    offer = create_offer(api, entry["id"], unit["id"], expires_at)
    tenancy = accept_offer(api, offer["id"], app["id"])
    return {
        "applicant": app,
        "waitlist": wl,
        "entry_id": entry["id"],
        "unit": unit,
        "offer": offer,
        "tenancy": tenancy,
    }


# ---------------------------------------------------------------------------
# Composite: ACTIVE tenancy with one finalized EFFECTIVE ANNUAL cert
# ---------------------------------------------------------------------------
def setup_finalized_annual_cert(api, *, members=None, bedroom_size=2,
                                income_limit_cents=HIGH_INCOME_LIMIT_CENTS,
                                utility_allowance_cents=0,
                                effective_date="2026-04-01T00:00:00Z",
                                childcare_expenses_annual_cents=None,
                                medical_expenses_annual_cents=None):
    """setup_active_tenancy, then create + finalize one ANNUAL cert to EFFECTIVE.
    Returns dict augmented with `cert` (the EFFECTIVE certification) and the
    post-finalize `tenancy` re-read."""
    ctx = setup_active_tenancy(api, members=members, bedroom_size=bedroom_size,
                               income_limit_cents=income_limit_cents,
                               utility_allowance_cents=utility_allowance_cents)
    tenancy = ctx["tenancy"]
    deductions = {}
    if childcare_expenses_annual_cents is not None:
        deductions["childcare_expenses_annual_cents"] = childcare_expenses_annual_cents
    if medical_expenses_annual_cents is not None:
        deductions["medical_expenses_annual_cents"] = medical_expenses_annual_cents
    cert = create_certification(api, tenancy["id"], "ANNUAL", effective_date,
                                tenancy["version"], **deductions)
    cert = finalize_certification(api, cert["id"])
    ctx["cert"] = cert
    ctx["tenancy"] = get_success_data(api.get_tenancy(tenancy["id"], HS))
    return ctx


# ---------------------------------------------------------------------------
# Composite: TERMINATED tenancy (via overruled eviction)
# ---------------------------------------------------------------------------
def setup_terminated_tenancy(api, *, bedroom_size=2):
    """ACTIVE tenancy then EVICTION filed and OVERRULED -> tenancy TERMINATED,
    unit AVAILABLE with last_lease_end_date set. Returns the setup_active_tenancy
    context plus `grievance` and a re-read `tenancy`/`unit`."""
    ctx = setup_active_tenancy(api, bedroom_size=bedroom_size)
    griev = file_grievance(api, ctx["tenancy"]["id"], "EVICTION", "chronic nonpayment")
    decide_grievance(api, griev["id"], "OVERRULED")
    ctx["grievance"] = griev
    ctx["tenancy"] = get_success_data(api.get_tenancy(ctx["tenancy"]["id"], HS))
    ctx["unit"] = get_success_data(api.get_unit(ctx["unit"]["id"], HS))
    return ctx
