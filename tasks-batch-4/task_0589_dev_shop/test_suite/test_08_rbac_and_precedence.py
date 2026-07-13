"""Authentication, role authorisation, client scope confinement, segregation of
duties, and the fixed precedence chain that decides which of several simultaneous
violations is the one reported."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_client_contact_headers,
    make_engineer_headers,
    make_delivery_lead_headers,
    fixtures,
    factories as F,
)

AM = TEST_USERS["account_manager_headers"]
DL = TEST_USERS["delivery_lead_headers"]  # pm-001
ENG = TEST_USERS["engineer_headers"]  # eng-001
ENG2 = TEST_USERS["engineer_2_headers"]  # eng-002

TIGHT = {
    "contract_value": 2000.00,
    "budget_hours_cap": 10,
    "standard_hourly_rate": 200.00,
}


def test_engineer_cannot_create_a_milestone(api):
    """PRD 2.1: "If the headers are well-formed but the named role is not among the roles authorised for the endpoint being called (see the authorisation column of the endpoint table in §4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 3.2: "Milestones are the fixed-fee billing skeleton of the engagement. A delivery lead adds one to an active engagement by supplying the `engagement_id`, a `sequence` (an ordering index of at least 1, unique among that engagement's milestones), a `title`, an `amount` strictly greater than zero at 2 decimal places, and a target `due_date`."

    Design: Corner/rbac/engineer_cannot_create_a_milestone_forbidden_role
    """
    ctx = fixtures.setup_active_engagement(
        billing_model="FIXED", contract_value=50000.00, budget_hours_cap=200
    )
    engagement_id = ctx["engagement"]["id"]

    resp = api.create_milestone(
        F.create_milestone_payload(
            engagement_id=engagement_id, sequence=1, title="Phase 1", amount=5000.00
        ),
        ENG,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    milestones = validate_success(
        api.list_milestones(DL, params={"engagement_id": engagement_id})
    )
    assert len(milestones) == 0, "the forbidden call must not create a milestone"


def test_client_contact_cannot_read_another_clients_engagement(api):
    """PRD 2.6: "When a `ClientContact` reaches for a resource belonging to a different client, the request is rejected with `ERR_CLIENT_SCOPE_VIOLATION` (HTTP 403)."
    PRD 2.1: "When `X-User-Role` is `ClientContact`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's client foreign key — directly on a retainer, or transitively through the engagement for an engagement, release, change request, invoice, or support incident — to `X-User-ID`."

    Design: Corner/rbac/client_contact_cannot_read_another_clients_engagement
    """
    client_a = fixtures.create_client(name="Client A", billing_email="ap@a.test")
    client_b = fixtures.create_client(name="Client B", billing_email="ap@b.test")
    engagement_b = fixtures.create_lead(client_b["id"], title="B Project", source_channel="INBOUND")

    resp = api.get_engagement(engagement_b["id"], make_client_contact_headers(client_a["id"]))
    validate_error(resp, ApiErrorId.ERR_CLIENT_SCOPE_VIOLATION.value)

    own = validate_success(
        api.get_engagement(engagement_b["id"], make_client_contact_headers(client_b["id"]))
    )
    assert own["id"] == engagement_b["id"], "the owning client reads its own engagement"


def test_request_without_auth_headers_is_unauthenticated(api):
    """PRD 2.1: "Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role that user is acting under. If either header is absent, or if `X-User-Role` is not one of the six roles the platform recognises, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_x_user_role_header_returns_unauthenticated
    """
    resp = api.create_client(
        F.create_client_payload(name="Ghostco", billing_email="ap@ghostco.test"), {}
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_delivery_lead_cannot_review_their_own_time_entry(api):
    """PRD 2.10: "A delivery lead may not review a time entry whose `employee_user_id` equals their own `X-User-ID`. And the actor who signs a ticket off — moving it from `IN_QA` to `DONE` — may not be the ticket's `assignee_user_id`. Both comparisons are made against the opaque `X-User-ID` header, and both rejections carry `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

    Design: Corner/rbac/delivery_lead_cannot_review_their_own_time_entry_segregation_of_duties
    """
    ctx = fixtures.setup_ticket_in_progress(
        ticket_overrides={"title": "PM does some code", "estimated_hours": 4},
        assignee="pm-001",
    )
    entry = fixtures.log_time(ctx["ticket"]["id"], 2.0, employee="pm-001")

    self_review = api.review_time_entry(
        entry["id"], "APPROVE", make_delivery_lead_headers("pm-001")
    )
    validate_error(self_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert validate_success(api.get_time_entry(entry["id"], DL))["status"] == "SUBMITTED"

    approved = validate_success(
        api.review_time_entry(entry["id"], "APPROVE", make_delivery_lead_headers("pm-002"))
    )
    assert approved["status"] == "APPROVED", "a second pair of eyes may approve the entry"
    assert approved["reviewed_by_user_id"] == "pm-002"

    engagement = validate_success(api.get_engagement(ctx["engagement"]["id"], DL))
    assert engagement["approved_hours"] == 2.0


def test_assignee_cannot_sign_off_their_own_ticket(api):
    """PRD 2.10: "A delivery lead may not review a time entry whose `employee_user_id` equals their own `X-User-ID`. And the actor who signs a ticket off — moving it from `IN_QA` to `DONE` — may not be the ticket's `assignee_user_id`. Both comparisons are made against the opaque `X-User-ID` header, and both rejections carry `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
    PRD 2.10: "Note the asymmetry: an engineer *may* freely move their own ticket through `TODO`, `IN_PROGRESS`, `IN_QA` and `REWORK`; it is only the final sign-off that requires a second pair of eyes."

    Design: Corner/rbac/assignee_cannot_sign_off_their_own_ticket_segregation_of_duties
    """
    ctx = fixtures.setup_ticket_in_progress(
        ticket_overrides={"title": "Payment webhook", "estimated_hours": 6}
    )
    ticket_id = ctx["ticket"]["id"]
    validate_success(api.transition_ticket(ticket_id, "IN_QA", ENG))

    self_signoff = api.transition_ticket(ticket_id, "DONE", make_engineer_headers("eng-001"))
    validate_error(self_signoff, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert validate_success(api.get_ticket(ticket_id, DL))["status"] == "IN_QA"

    signed_off = validate_success(api.transition_ticket(ticket_id, "DONE", ENG2))
    assert signed_off["status"] == "DONE", "another engineer may sign the ticket off"


# ---------------------------------------------------------------------------
# Precedence: the sprint-state gate outranks the fiscal cap
# ---------------------------------------------------------------------------
def test_closed_sprint_is_reported_before_the_budget_hour_cap(api):
    """PRD 2.5: "Because a single request can violate several rules at once, the order in which checks are applied is fixed, and the first failing check is the one reported."
    PRD 2.5: "**Parent-state gates** — the engagement must be `ACTIVE` where the operation demands it (`ERR_ENGAGEMENT_NOT_ACTIVE`), then the sprint-state gates (`ERR_SPRINT_NOT_ACTIVE`), then the transition-legality check (`ERR_INVALID_TRANSITION`), then the milestone-completion gate on issuing (`ERR_MILESTONE_NOT_COMPLETED`), then the active-sprint gate on engagement closure (`ERR_ENGAGEMENT_HAS_ACTIVE_SPRINT`)."
    PRD 2.5: "**Fiscal caps** — the budget hour cap (`ERR_BUDGET_HOURS_EXCEEDED`), the daily hour cap (`ERR_DAILY_HOURS_EXCEEDED`), the milestone-sum cap (`ERR_MILESTONE_AMOUNT_EXCEEDS_CONTRACT`), and the exact-payment rule (`ERR_PAYMENT_AMOUNT_MISMATCH`)."

    Design: Difficulty/priority_pair_validation_conflict/sprint_not_active_state_error_beats_budget_hours_fiscal_error
    """
    ctx = fixtures.setup_ticket_in_progress(
        engagement_overrides={
            "contract_value": 2000.00,
            "budget_hours_cap": 5,
            "standard_hourly_rate": 200.00,
        },
        ticket_overrides={"title": "Memory implants", "estimated_hours": 8},
    )
    entry = fixtures.log_time(ctx["ticket"]["id"], 9.0)  # approving 9.0 would breach the 5h cap
    fixtures.close_sprint(ctx["sprint"]["id"])  # ... and the sprint is no longer ACTIVE

    resp = api.review_time_entry(entry["id"], "APPROVE", DL)
    validate_error(resp, ApiErrorId.ERR_SPRINT_NOT_ACTIVE.value)


def test_the_losing_budget_cap_violation_leaves_the_ledger_untouched(api):
    """PRD 3.4: "Review is a delivery lead's job. It carries a `decision` and an optional `note`, and the reviewer's `X-User-ID` must differ from the entry's `employee_user_id`. The entry's sprint must be `ACTIVE` at review time."
    PRD 3.4: "Approval carries one further guard, and it fires before the cascade runs: **only for a billable entry**, the engagement's current `approved_hours` plus the entry's `hours` must not exceed the engagement's `budget_hours_cap`. A billable approval that would push the ledger past the cap is refused with `ERR_BUDGET_HOURS_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/sprint_not_active_state_error_beats_budget_hours_fiscal_error
    """
    ctx = fixtures.setup_ticket_in_progress(
        engagement_overrides={
            "contract_value": 2000.00,
            "budget_hours_cap": 5,
            "standard_hourly_rate": 200.00,
        },
        ticket_overrides={"title": "Memory implants", "estimated_hours": 8},
    )
    entry = fixtures.log_time(ctx["ticket"]["id"], 9.0)
    fixtures.close_sprint(ctx["sprint"]["id"])

    validate_error(
        api.review_time_entry(entry["id"], "APPROVE", DL),
        ApiErrorId.ERR_SPRINT_NOT_ACTIVE.value,
    )

    after = validate_success(api.get_time_entry(entry["id"], DL))
    assert after["status"] == "SUBMITTED", "the refused review leaves the entry unreviewed"
    engagement = validate_success(api.get_engagement(ctx["engagement"]["id"], DL))
    assert engagement["approved_hours"] == 0, "no hours entered the ledger"
    assert engagement["budget_posture"] == "HEALTHY"


# ---------------------------------------------------------------------------
# Precedence: the referential rule outranks the temporal rule
# ---------------------------------------------------------------------------
def test_not_the_assignee_is_reported_before_the_out_of_window_work_date(api):
    """PRD 2.5: "**Referential business rules** — ticket assignee ownership (`ERR_NOT_TICKET_ASSIGNEE`), then blocker-graph acyclicity (`ERR_TICKET_CYCLE`), then milestone-to-engagement consistency (`ERR_MILESTONE_ENGAGEMENT_MISMATCH`)."
    PRD 2.5: "**Temporal rules** — work-date containment (`ERR_WORK_DATE_OUT_OF_SPRINT`), then sprint-window overlap (`ERR_SPRINT_OVERLAP`), then retainer-window collision (`ERR_RETAINER_WINDOW_CONFLICT`), then retainer-coverage activity (`ERR_RETAINER_WINDOW_INACTIVE`)."
    PRD 3.4: "The server stamps `employee_user_id` from the acting `X-User-ID`; if that identifier does not equal the ticket's `assignee_user_id`, the entry is refused with `ERR_NOT_TICKET_ASSIGNEE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/not_ticket_assignee_referential_error_beats_work_date_temporal_error
    """
    ctx = fixtures.setup_ticket_in_progress(
        sprint_overrides={"start_date": "2026-05-04", "end_date": "2026-05-18"},
        ticket_overrides={"title": "Inventory sync"},
        assignee="eng-001",
    )

    # eng-002 is not the assignee AND 2026-06-01 is outside the sprint window.
    resp = api.create_time_entry(
        F.create_time_entry_payload(
            ticket_id=ctx["ticket"]["id"], work_date="2026-06-01", hours=3.0
        ),
        make_engineer_headers("eng-002"),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_TICKET_ASSIGNEE.value)


def test_the_losing_work_date_violation_creates_no_time_entry(api):
    """PRD 3.4: "The `work_date` must fall inside the owning sprint's half-open window — on or after the sprint's `start_date` and strictly before its `end_date` — and an entry dated outside it is rejected with `ERR_WORK_DATE_OUT_OF_SPRINT` (HTTP 422)."
    PRD 2.5: "Because a single request can violate several rules at once, the order in which checks are applied is fixed, and the first failing check is the one reported."

    Design: Difficulty/priority_pair_validation_conflict/not_ticket_assignee_referential_error_beats_work_date_temporal_error
    """
    ctx = fixtures.setup_ticket_in_progress(
        sprint_overrides={"start_date": "2026-05-04", "end_date": "2026-05-18"},
        ticket_overrides={"title": "Inventory sync"},
        assignee="eng-001",
    )
    ticket_id = ctx["ticket"]["id"]

    validate_error(
        api.create_time_entry(
            F.create_time_entry_payload(ticket_id=ticket_id, work_date="2026-06-01", hours=3.0),
            make_engineer_headers("eng-002"),
        ),
        ApiErrorId.ERR_NOT_TICKET_ASSIGNEE.value,
    )

    entries = validate_success(api.list_time_entries(DL, params={"ticket_id": ticket_id}))
    assert len(entries) == 0, "the rejected log must not persist a time entry"
