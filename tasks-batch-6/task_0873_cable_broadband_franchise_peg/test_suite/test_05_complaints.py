"""Customer complaints: the cyclic lifecycle, escalation, and the compliance cascade."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_complaint,
    TEST_USERS, make_operator_headers, make_resident_headers,
)
from test_helpers import (
    create_active_franchise, file_complaint, resolve_complaint,
    file_transfer_application, set_clock, escalate_complaint, get_franchise,
)

AUTHORITY = TEST_USERS["authority_headers"]


# ---- Difficulty: complaint_resolve_reopen_cycle ----
def test_resolve_reopen_cycle_returns_to_resolved(api):
    """PRD 3.6: "An operator resolves a complaint from `OPEN`, `REOPENED`, or
    `ESCALATED` by supplying a `resolution_note`; resolution moves it to
    `RESOLVED`".
    PRD 3.6: "The original resident may reopen a resolved complaint, moving it
    from `RESOLVED` to `REOPENED`".

    Design: Difficulty/non_linear_state_machine/complaint_resolve_reopen_cycle
    """
    fr = create_active_franchise(api)
    c = file_complaint(api, fr["id"], complainant_id="res-1", category="BILLING",
                       description="Overcharged on last bill")
    op = make_operator_headers(fr["id"])
    res = make_resident_headers("res-1")
    validate_success(api.resolve_complaint(c["id"], {"resolution_note": "Credit applied"}, op), 200)
    validate_success(api.reopen_complaint(c["id"], res), 200)
    data = validate_success(api.resolve_complaint(c["id"], {"resolution_note": "Credit re-applied"}, op), 200)
    assert_complaint(data)
    assert data["status"] == "RESOLVED"


def test_version_increments_each_cycle_hop(api):
    """PRD 2.4: "The `version` begins at 1 when the resource is created; every
    state-changing mutation of that resource increments its `version` by exactly
    1 and refreshes `updated_at`."

    Design: Difficulty/non_linear_state_machine/complaint_resolve_reopen_cycle
    """
    fr = create_active_franchise(api)
    c = file_complaint(api, fr["id"], complainant_id="res-1", category="BILLING",
                       description="Overcharged on last bill")
    op = make_operator_headers(fr["id"])
    res = make_resident_headers("res-1")
    api.resolve_complaint(c["id"], {"resolution_note": "Credit applied"}, op)
    api.reopen_complaint(c["id"], res)
    data = validate_success(api.resolve_complaint(c["id"], {"resolution_note": "Credit re-applied"}, op), 200)
    # created (1) -> resolve (2) -> reopen (3) -> resolve (4).
    assert data["version"] == 4


# ---- Difficulty: complaint_escalation_depth2_cascade ----
def _setup_one_escalated_and_pending_second(api):
    """ACTIVE franchise, a SUBMITTED TRANSFER app, two SERVICE_INTERRUPTION
    complaints, clock past SLA, complaint #1 already ESCALATED (count 1).
    Returns (franchise, app, c1, c2).
    """
    fr = create_active_franchise(api)
    app = file_transfer_application(api, fr["id"], transferee_name="NewCo")
    c1 = file_complaint(api, fr["id"], complainant_id="res-1",
                        category="SERVICE_INTERRUPTION", description="Outage block A")
    c2 = file_complaint(api, fr["id"], complainant_id="res-2",
                        category="SERVICE_INTERRUPTION", description="Outage block B")
    set_clock(api, "2026-05-03T00:00:00Z")
    escalate_complaint(api, c1["id"])
    return fr, app, c1, c2


def test_second_escalation_flips_compliance(api):
    """PRD 3.6: "A successful escalation moves the complaint to `ESCALATED`,
    stamps `escalated_at` from the clock, and increments the franchise's
    `unresolved_complaint_count` by 1. If that count reaches at least 2 escalated
    complaints, the franchise's compliance flips to `IN_VIOLATION`".

    Design: Difficulty/transitive_cascade/complaint_escalation_depth2_cascade
    """
    fr, app, c1, c2 = _setup_one_escalated_and_pending_second(api)
    validate_success(api.escalate_complaint(c2["id"], AUTHORITY), 200)
    franchise = get_franchise(api, fr["id"])
    assert franchise["unresolved_complaint_count"] == 2
    assert franchise["compliance_status"] == "IN_VIOLATION"


def test_violation_holds_submitted_application(api):
    """PRD 3.6: "If that count reaches at least 2 escalated complaints, the
    franchise's compliance flips to `IN_VIOLATION` — which itself holds every
    `SUBMITTED` application on the franchise."

    Design: Difficulty/transitive_cascade/complaint_escalation_depth2_cascade
    """
    fr, app, c1, c2 = _setup_one_escalated_and_pending_second(api)
    validate_success(api.escalate_complaint(c2["id"], AUTHORITY), 200)
    after = validate_success(api.get_application(app["id"], AUTHORITY), 200)
    assert after["status"] == "HELD"


# ---- Difficulty: complaint_escalate_at_exact_deadline_refused ----
def test_escalate_at_exact_deadline_refused(api):
    """PRD 3.6: "An authority may escalate a complaint from `OPEN` or `REOPENED`,
    but only once its SLA has actually been breached — the clock must be strictly
    past `sla_deadline`. Escalation attempted at or before the deadline is
    rejected with `ERR_SLA_NOT_BREACHED`."

    Design: Difficulty/boundary_precision_check/complaint_escalate_at_exact_deadline_refused
    """
    fr = create_active_franchise(api)
    # Filed at default clock 2026-05-01; SERVICE_INTERRUPTION SLA 24h -> deadline 2026-05-02T00:00:00Z.
    c = file_complaint(api, fr["id"], complainant_id="res-1",
                       category="SERVICE_INTERRUPTION", description="No service since morning")
    set_clock(api, "2026-05-02T00:00:00Z")  # exactly equal to sla_deadline
    resp = api.escalate_complaint(c["id"], AUTHORITY)
    validate_error(resp, ApiErrorId.ERR_SLA_NOT_BREACHED.value, 409)


def test_escalate_at_deadline_leaves_open(api):
    """PRD 3.6: "Escalation attempted at or before the deadline is rejected with
    `ERR_SLA_NOT_BREACHED`."

    Design: Difficulty/boundary_precision_check/complaint_escalate_at_exact_deadline_refused
    """
    fr = create_active_franchise(api)
    c = file_complaint(api, fr["id"], complainant_id="res-1",
                       category="SERVICE_INTERRUPTION", description="No service since morning")
    set_clock(api, "2026-05-02T00:00:00Z")
    api.escalate_complaint(c["id"], AUTHORITY)
    after = validate_success(api.get_complaint(c["id"], AUTHORITY), 200)
    assert after["status"] == "OPEN"


# ---- Corner: reopen_open_complaint_returns_invalid_state ----
def test_reopen_open_complaint_returns_invalid_state(api):
    """PRD 3.6: "reopening is defined only from `RESOLVED` and only for the caller
    whose `X-User-ID` equals the stored `complainant_id`."

    Design: Corner/state_machines/reopen_open_complaint_returns_invalid_state
    """
    fr = create_active_franchise(api)
    c = file_complaint(api, fr["id"], complainant_id="res-1", category="OTHER",
                       description="General question")
    resp = api.reopen_complaint(c["id"], make_resident_headers("res-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ---- Corner (rbac): resident_cannot_resolve_complaint_unauthorized ----
def test_resident_cannot_resolve_complaint_unauthorized(api):
    """PRD 2.1: "If the header is present and valid but the role is not permitted
    to invoke the requested operation (per the authorization matrix in Section
    4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/resident_cannot_resolve_complaint_unauthorized
    """
    fr = create_active_franchise(api)
    c = file_complaint(api, fr["id"], complainant_id="res-1", category="OTHER", description="x")
    resp = api.resolve_complaint(c["id"], {"resolution_note": "not allowed"}, make_resident_headers("res-1"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
