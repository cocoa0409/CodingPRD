"""Composite setup helpers.

Every helper builds its preconditions from scratch via PRD-declared
endpoints; each pytest test runs against a freshly restarted server, so no
state carries over. Setup calls use the lenient get_success_data validator
so failures surface as setup errors, not assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_admin_event_payload,
    create_agency_payload,
    create_authorization_payload,
    create_bed_assignment_payload,
    create_behavior_plan_payload,
    create_claim_payload,
    create_evv_visit_payload,
    create_home_payload,
    create_incident_payload,
    create_individual_payload,
    create_isp_payload,
    create_medication_order_payload,
    create_shift_payload,
    create_staff_payload,
    create_transport_leg_payload,
    create_transport_trip_payload,
)
from .test_users import (
    TEST_USERS,
    make_case_manager_headers,
    make_qidp_headers,
    make_dsp_headers,
    make_billing_headers,
)

ADMIN = TEST_USERS["agency_admin_headers"]
ANY = TEST_USERS["any_headers"]
BILL1 = TEST_USERS["billing_headers"]
BILL2 = TEST_USERS["billing2_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ---------------------------------------------------------------------------
# Tier 1: basic agency / staff / individual setup
# ---------------------------------------------------------------------------

def setup_agency(name=TEST_DEFAULTS["AGENCY_NAME"], **overrides):
    """Create a provider agency. Returns the agency dict."""
    payload = create_agency_payload(name=name, **overrides)
    return get_success_data(api_client.create_agency(payload, ADMIN))


def setup_staff(agency_id, staff_role="CASE_MANAGER", full_name=None, certifications=None):
    """Hire one staff member. Returns the staff dict."""
    payload = create_staff_payload(
        agency_id,
        staff_role=staff_role,
        full_name=full_name or f"Staff {staff_role}",
        certifications=certifications if certifications is not None else ["CPR"],
    )
    return get_success_data(api_client.create_staff(payload, ADMIN))


def setup_agency_with_core_staff():
    """Agency + CASE_MANAGER (cm) + QIDP (q). Returns dict of the three."""
    agency = setup_agency()
    cm = setup_staff(agency["id"], "CASE_MANAGER", full_name="Casey Manager")
    q = setup_staff(agency["id"], "QIDP", full_name="Quinn Qidp")
    return {"agency": agency, "cm": cm, "q": q}


def setup_agency_with_clinical_staff():
    """Agency + cm + q + DSP with MED_CERT (d1). Returns dict."""
    base = setup_agency_with_core_staff()
    d1 = setup_staff(
        base["agency"]["id"], "DSP",
        full_name="Dee Spone", certifications=["MED_CERT", "CPR"],
    )
    base["d1"] = d1
    return base


def setup_enrolled_individual(agency, cm, q, **overrides):
    """Register an individual and enroll them. Returns the ENROLLED individual."""
    ind = get_success_data(api_client.create_individual(
        create_individual_payload(agency["id"], **overrides),
        make_case_manager_headers(cm["id"]),
    ))
    ind = get_success_data(api_client.enroll_individual(
        ind["id"], make_qidp_headers(q["id"]),
    ))
    return ind


def set_clock(to_iso8601):
    """Advance the logical clock."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: ISP lifecycle
# ---------------------------------------------------------------------------

def create_isp_draft(individual, cm):
    """Create a DRAFT ISP for the individual (OCC version from the individual)."""
    payload = create_isp_payload(
        individual["id"], individual["version"],
    )
    return get_success_data(api_client.create_isp(
        payload, make_case_manager_headers(cm["id"]),
    ))


def create_active_isp(individual, cm, q, plan_year_start=None, plan_year_end=None):
    """Walk an ISP create -> submit -> approve -> activate. Returns ACTIVE ISP."""
    overrides = {}
    if plan_year_start is not None:
        overrides["plan_year_start"] = plan_year_start
    if plan_year_end is not None:
        overrides["plan_year_end"] = plan_year_end
    payload = create_isp_payload(individual["id"], individual["version"], **overrides)
    isp = get_success_data(api_client.create_isp(
        payload, make_case_manager_headers(cm["id"]),
    ))
    isp = get_success_data(api_client.submit_isp_review(
        isp["id"], make_case_manager_headers(cm["id"]),
    ))
    isp = get_success_data(api_client.approve_isp(
        isp["id"], make_qidp_headers(q["id"]),
    ))
    isp = get_success_data(api_client.activate_isp(
        isp["id"], make_qidp_headers(q["id"]),
    ))
    return isp


# ---------------------------------------------------------------------------
# Tier 2: authorization lifecycle
# ---------------------------------------------------------------------------

def create_active_authorization(individual, isp, cm, q, **overrides):
    """Create + approve an authorization; today inside the span makes it ACTIVE."""
    payload = create_authorization_payload(individual["id"], isp["id"], **overrides)
    auth = get_success_data(api_client.create_authorization(
        payload, make_case_manager_headers(cm["id"]),
    ))
    auth = get_success_data(api_client.approve_authorization(
        auth["id"], make_qidp_headers(q["id"]),
    ))
    return auth


# ---------------------------------------------------------------------------
# Tier 3: home + resident setup
# ---------------------------------------------------------------------------

def setup_home(agency, certified_bed_count=2, **overrides):
    """Create a group home. Returns the home dict."""
    payload = create_home_payload(
        agency["id"], certified_bed_count=certified_bed_count, **overrides,
    )
    return get_success_data(api_client.create_home(payload, ADMIN))


def admit_resident(home, individual, cm, q, bed_label="R1", move_in_date="2026-06-01"):
    """Create + move-in a bed assignment. Returns the ACTIVE assignment."""
    ba = get_success_data(api_client.create_bed_assignment(
        create_bed_assignment_payload(
            home["id"], bed_label, individual["id"], move_in_date=move_in_date,
        ),
        make_case_manager_headers(cm["id"]),
    ))
    ba = get_success_data(api_client.move_in_bed_assignment(
        ba["id"], make_qidp_headers(q["id"]),
    ))
    return ba


def setup_billable_pipeline(clock_iso=TEST_DEFAULTS["BASE_CLOCK"], **auth_overrides):
    """Agency + cm/q/d1 + ENROLLED individual + ACTIVE ISP + ACTIVE authorization.

    Sets the clock to clock_iso. Returns a dict with all pieces and headers.
    `plan_year_start` / `plan_year_end` overrides route to the ISP (they are
    ISP fields, not authorization fields); everything else routes to the
    authorization payload.
    """
    base = setup_agency_with_clinical_staff()
    agency, cm, q, d1 = base["agency"], base["cm"], base["q"], base["d1"]
    ind = setup_enrolled_individual(agency, cm, q)
    set_clock(clock_iso)
    isp_overrides = {}
    for key in ("plan_year_start", "plan_year_end"):
        if key in auth_overrides:
            isp_overrides[key] = auth_overrides.pop(key)
    isp = create_active_isp(ind, cm, q, **isp_overrides)
    auth = create_active_authorization(ind, isp, cm, q, **auth_overrides)
    return {
        "agency": agency, "cm": cm, "q": q, "d1": d1,
        "individual": ind, "isp": isp, "auth": auth,
        "cm_headers": make_case_manager_headers(cm["id"]),
        "q_headers": make_qidp_headers(q["id"]),
        "d1_headers": make_dsp_headers(d1["id"]),
    }


def create_and_verify_visit(ctx, check_in_at, check_out_at, service_date="2026-06-02",
                            auth=None, **overrides):
    """Create an EVV visit as d1 and verify it as q. Returns the VERIFIED visit."""
    auth = auth or ctx["auth"]
    visit = get_success_data(api_client.create_evv_visit(
        create_evv_visit_payload(
            ctx["individual"]["id"], auth["id"],
            service_date=service_date,
            check_in_at=check_in_at, check_out_at=check_out_at,
            **overrides,
        ),
        ctx["d1_headers"],
    ))
    visit = get_success_data(api_client.verify_evv_visit(
        visit["id"], ctx["q_headers"],
    ))
    return visit


def setup_claim_for_individual(ctx, period_start="2026-06-02", period_end="2026-06-02"):
    """Generate a DRAFT claim sweeping verified unbilled visits in the period."""
    return get_success_data(api_client.create_claim(
        create_claim_payload(
            ctx["individual"]["id"],
            service_period_start=period_start,
            service_period_end=period_end,
        ),
        BILL1,
    ))


def submit_claim_as(claim_id, user_id):
    return get_success_data(api_client.submit_claim(
        claim_id, make_billing_headers(user_id),
    ))


def setup_submitted_claim(ctx, period_start="2026-06-02", period_end="2026-06-02",
                          submitter="bill-1"):
    """Generate + submit a claim. Returns the SUBMITTED claim."""
    claim = setup_claim_for_individual(ctx, period_start, period_end)
    return submit_claim_as(claim["id"], submitter)
