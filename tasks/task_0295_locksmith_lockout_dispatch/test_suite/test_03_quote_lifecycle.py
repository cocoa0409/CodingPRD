"""On-site quote lifecycle: the SUBMITTED->DRAFTED revision loop, the parallel
job/payment axes, the cross-entity submit-requires-ON_SITE gate, and the
invalid-state / already-approved / ownership corner cases.

Difficulty queue: non_linear_state_machine (revision cycle, parallel axes),
cross_entity_state_dependency (quote submit requires ON_SITE).
Corner queue: state_machines (approve drafted, reopen non-rejected, second approve),
rbac (non-owner approve), consistency_model (amount_due visible after approve).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    make_technician_headers,
    make_customer_headers,
    setup_drafted_quote,
    setup_submitted_quote,
    create_quote_payload,
    create_job,
    create_technician,
    dispatch_job,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_agent_headers"]


# ─── non_linear_state_machine / quote_revision_cycle_submitted_to_drafted ──────
def test_request_revision_returns_quote_to_drafted(api):
    """PRD §3.9: "Requesting a revision sends the quote back from SUBMITTED to DRAFTED,
    reopening the revision loop so the technician can adjust labor and parts and submit
    again."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_submitted_to_drafted
    """
    job, tech, quote = setup_submitted_quote(customer_user_id="cust-rev1")
    assert quote["status"] == "SUBMITTED"
    revised = validate_success(
        api.request_quote_revision(quote["id"], make_customer_headers("cust-rev1")), 200
    )
    assert revised["status"] == "DRAFTED"


def test_quote_resubmittable_after_revision_cycle(api):
    """PRD §3.9: "Requesting a revision sends the quote back from SUBMITTED to DRAFTED,
    reopening the revision loop so the technician can adjust labor and parts and submit
    again."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_submitted_to_drafted
    """
    job, tech, quote = setup_submitted_quote(customer_user_id="cust-rev2")
    tech_h = make_technician_headers(tech["id"])
    get_success_data(api.request_quote_revision(quote["id"], make_customer_headers("cust-rev2")))
    resubmitted = validate_success(api.submit_quote(quote["id"], tech_h), 200)
    assert resubmitted["status"] == "SUBMITTED"


# ─── non_linear_state_machine / servicejob_parallel_axes_job_vs_payment ────────
def test_payment_advances_money_axis_while_job_axis_stays_on_site(api):
    """PRD §3.12: "if it brings net_paid_cents exactly equal to amount_due_cents, the
    payment_status becomes PAID."
    PRD §3.1: "a job's progress on one axis does not imply anything about the other."

    Design: Difficulty/non_linear_state_machine/servicejob_parallel_axes_job_vs_payment
    """
    job, tech, quote = setup_submitted_quote(customer_user_id="cust-par1")
    get_success_data(api.approve_quote(quote["id"], make_customer_headers("cust-par1")))
    get_success_data(
        api.capture_payment(job["id"], {"captured_amount_cents": 8000}, BILLING)
    )
    refreshed = validate_success(api.get_service_job(job["id"], DISPATCHER), 200)
    assert refreshed["payment_status"] == "PAID"
    assert refreshed["job_status"] == "ON_SITE", (
        "money axis advancing to PAID must not move the operational axis off ON_SITE"
    )


def test_job_axis_stays_on_site_before_any_payment(api):
    """PRD §3.1: "The operational axis, job_status, moves through INTAKE, DISPATCHED,
    ON_SITE, WORK_COMPLETE, and terminally CLOSED, or terminally CANCELLED. The money
    axis, payment_status, moves through UNPAID, PARTIALLY_PAID, PAID, and terminally
    REFUNDED."

    Design: Difficulty/non_linear_state_machine/servicejob_parallel_axes_job_vs_payment
    """
    job, tech, quote = setup_submitted_quote(customer_user_id="cust-par2")
    get_success_data(api.approve_quote(quote["id"], make_customer_headers("cust-par2")))
    refreshed = validate_success(api.get_service_job(job["id"], DISPATCHER), 200)
    # approving sets amount_due but leaves money axis UNPAID and job axis ON_SITE
    assert refreshed["job_status"] == "ON_SITE"
    assert refreshed["payment_status"] == "UNPAID"


# ─── cross_entity_state_dependency / quote_submit_requires_job_on_site ─────────
def test_submit_quote_requires_job_on_site(api):
    """PRD §3.5: "Submission requires the parent job to be in ON_SITE — a submit when
    the job is not on site is rejected with ERR_JOB_NOT_ON_SITE — and requires both
    labor_hours and part_lines to be present on the quote, failing which the submit is
    rejected with ERR_QUOTE_INCOMPLETE."

    Design: Difficulty/cross_entity_state_dependency/quote_submit_requires_job_on_site
    """
    # Job left DISPATCHED (dispatched but not arrived). Draft has no job-state gate.
    tech = create_technician(certified_for=["REKEY"], base_travel_minutes=20)
    tech_h = make_technician_headers(tech["id"])
    job = create_job(customer_user_id="cust-os1", service_type="REKEY",
                     requested_at_minute=600)
    dispatch_job(job["id"], tech["id"], 605, 650)
    quote = get_success_data(
        api.create_quote(job["id"], create_quote_payload(labor_hours=1.0, part_lines=[]), tech_h)
    )
    res = api.submit_quote(quote["id"], tech_h)
    validate_error(res, "ERR_JOB_NOT_ON_SITE", expected_status=409)


def test_submit_quote_leaves_status_drafted_when_job_not_on_site(api):
    """PRD §3.5: "Submission requires the parent job to be in ON_SITE — a submit when
    the job is not on site is rejected with ERR_JOB_NOT_ON_SITE — and requires both
    labor_hours and part_lines to be present on the quote, failing which the submit is
    rejected with ERR_QUOTE_INCOMPLETE."

    Design: Difficulty/cross_entity_state_dependency/quote_submit_requires_job_on_site
    """
    tech = create_technician(certified_for=["REKEY"], base_travel_minutes=20)
    tech_h = make_technician_headers(tech["id"])
    job = create_job(customer_user_id="cust-os2", service_type="REKEY",
                     requested_at_minute=600)
    dispatch_job(job["id"], tech["id"], 605, 650)
    quote = get_success_data(
        api.create_quote(job["id"], create_quote_payload(labor_hours=1.0, part_lines=[]), tech_h)
    )
    api.submit_quote(quote["id"], tech_h)
    refreshed = validate_success(api.get_quote(quote["id"], tech_h), 200)
    assert refreshed["status"] == "DRAFTED", "a rejected submit must not move the quote"


# ─── Corner: state_machines / approve_drafted_quote_invalid_state ──────────────
def test_approve_drafted_quote_invalid_state(api):
    """PRD §3.9: "Any quote transition attempted from an incompatible status —
    approving a draft, reopening a quote that is not rejected, and the like — is
    rejected with ERR_QUOTE_INVALID_STATE."

    Design: Corner/state_machines/approve_drafted_quote_invalid_state
    """
    job, tech, quote = setup_drafted_quote(customer_user_id="cust-ad")
    res = api.approve_quote(quote["id"], make_customer_headers("cust-ad"))
    validate_error(res, "ERR_QUOTE_INVALID_STATE", expected_status=409)
    refreshed = validate_success(api.get_quote(quote["id"], DISPATCHER), 200)
    assert refreshed["status"] == "DRAFTED"


# ─── Corner: state_machines / reopen_non_rejected_quote_invalid_state ──────────
def test_reopen_submitted_quote_invalid_state(api):
    """PRD §3.9: "Any quote transition attempted from an incompatible status —
    approving a draft, reopening a quote that is not rejected, and the like — is
    rejected with ERR_QUOTE_INVALID_STATE."

    Design: Corner/state_machines/reopen_non_rejected_quote_invalid_state
    """
    job, tech, quote = setup_submitted_quote(customer_user_id="cust-ro")
    res = api.reopen_quote(quote["id"], make_technician_headers(tech["id"]))
    validate_error(res, "ERR_QUOTE_INVALID_STATE", expected_status=409)


# ─── Corner: state_machines / second_quote_approve_already_approved ────────────
def test_second_quote_approve_already_approved(api):
    """PRD §3.9: "A job may have only one approved quote at a time; approving a second
    when one is already approved on the job is rejected with ERR_QUOTE_ALREADY_APPROVED."

    Design: Corner/state_machines/second_quote_approve_already_approved
    """
    job, tech, quote1 = setup_submitted_quote(customer_user_id="cust-2nd")
    cust_h = make_customer_headers("cust-2nd")
    tech_h = make_technician_headers(tech["id"])
    get_success_data(api.approve_quote(quote1["id"], cust_h))
    quote2 = get_success_data(
        api.create_quote(job["id"], create_quote_payload(labor_hours=2.0, part_lines=[]), tech_h)
    )
    get_success_data(api.submit_quote(quote2["id"], tech_h))
    res = api.approve_quote(quote2["id"], cust_h)
    validate_error(res, "ERR_QUOTE_ALREADY_APPROVED", expected_status=409)


# ─── Corner: rbac / customer_not_owner_cannot_approve_quote ────────────────────
def test_non_owner_customer_cannot_approve_quote(api):
    """PRD §2.1: "A Customer acting on a quote or warranty claim whose parent job's
    customer_user_id does not equal the caller's X-User-ID is rejected with
    ERR_NOT_JOB_OWNER."

    Design: Corner/rbac/customer_not_owner_cannot_approve_quote
    """
    job, tech, quote = setup_submitted_quote(customer_user_id="cust-own")
    res = api.approve_quote(quote["id"], make_customer_headers("cust-intruder"))
    validate_error(res, "ERR_NOT_JOB_OWNER", expected_status=403)
    refreshed = validate_success(api.get_quote(quote["id"], DISPATCHER), 200)
    assert refreshed["status"] == "SUBMITTED"


# ─── Corner: consistency_model / immediate_amount_due_visible_after_approve ────
def test_amount_due_visible_immediately_after_approve(api):
    """PRD §3.9: "Approval moves the quote from SUBMITTED to APPROVED and, as a side
    effect, sets the parent job's amount_due_cents to the quote's final_total_cents,
    fixing the amount the customer owes."

    Design: Corner/consistency_model/immediate_amount_due_visible_after_approve
    """
    job, tech, quote = setup_submitted_quote(customer_user_id="cust-im", labor_hours=1.0)
    # daytime REKEY labor 1.0 -> final 8000
    assert quote["final_total_cents"] == 8000
    get_success_data(api.approve_quote(quote["id"], make_customer_headers("cust-im")))
    refreshed = validate_success(api.get_service_job(job["id"], DISPATCHER), 200)
    assert refreshed["amount_due_cents"] == 8000
