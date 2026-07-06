"""Role-based access control: unauthenticated rejection, role-surface denial,
and SalesRep resource ownership.
"""
from test_helpers import (
    ApiErrorId,
    create_appointment,
    create_crew,
    create_lead,
    create_product,
    create_quote_payload,
    create_sales_rep,
    get_lead_version,
    make_sales_rep_headers,
    setup_accepted_quote,
    validate_error,
)


def test_get_lead_without_role_header_returns_401(api, no_role_headers):
    """PRD §2.1: "If `X-User-Role` is absent or is not one of the four recognized
    roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/get_lead_unauthenticated_returns_401
    """
    rep = create_sales_rep()
    lead = create_lead(rep["id"], full_name="HO21", address="21 St", phone="555-0021")
    resp = api.get_lead(lead["id"], no_role_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_scheduler_cannot_create_quote_returns_403(api, scheduler_headers):
    """PRD §2.1: "When a syntactically valid, authenticated request asks for an
    operation the acting role is not permitted to perform, the response is
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/scheduler_cannot_create_quote_returns_403
    """
    product = create_product()
    rep = create_sales_rep()
    lead = create_lead(rep["id"], full_name="HO22", address="22 St", phone="555-0022")
    appt = create_appointment(lead["id"], rep["id"])
    lv = get_lead_version(lead["id"])
    payload = create_quote_payload(
        lead["id"], appt["id"], rep["id"], product["id"], "WHITE", 100, lv,
        downspout_count=0, discount_pct=0,
    )
    resp = api.create_quote(payload, scheduler_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_salesrep_cannot_schedule_job_returns_403(api):
    """PRD §2.1: "When a syntactically valid, authenticated request asks for an
    operation the acting role is not permitted to perform, the response is
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/salesrep_cannot_schedule_job_returns_403
    """
    scenario = setup_accepted_quote(estimated_linear_feet=210, measured_linear_feet=210)
    crew = create_crew()
    rep_headers = make_sales_rep_headers(scenario["rep"]["id"])
    resp = api.schedule_job(
        scenario["job"]["id"],
        {"crew_id": crew["id"], "install_date": "2026-06-10"},
        rep_headers,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_salesrep_cannot_transition_other_reps_lead_returns_403(api):
    """PRD §2.1: "Ownership is enforced: a sales rep may act only on a `Lead` — and
    on the appointments and quotes belonging to that lead — whose `sales_rep_id`
    equals the acting `X-User-ID`. A sales rep attempting to act on another rep's
    lead (or on that lead's appointments or quotes) is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/salesrep_cannot_act_on_other_reps_lead_returns_403
    """
    rep_a = create_sales_rep(full_name="Rep A")
    rep_b = create_sales_rep(full_name="Rep B")
    lead = create_lead(rep_b["id"], full_name="HO24", address="24 St", phone="555-0024")
    headers_a = make_sales_rep_headers(rep_a["id"])
    resp = api.transition_lead(lead["id"], {"to_status": "CONTACTED"}, headers_a)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
