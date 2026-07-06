"""Multi-entity cascades: VA replacement, client close, and the conservation
invariants those cascades must preserve.

Translates the difficulty transitive_cascade instances (escalation replace 4.A,
client close 4.B) and the compensating_invariant instances (hour-bank 9.A,
engagement-count 9.B), plus the corner resolve-escalation and duplicate-email
instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_skill_tag_payload, create_virtual_assistant_payload,
    create_client_payload, scope_client_payload, create_engagement_payload,
    activate_engagement_payload, create_escalation_payload, replace_escalation_payload,
    create_task_payload, create_time_entry_payload, unique_email,
    setup_active_client_engagement, create_assigned_task, create_in_progress_task,
    log_time, log_and_approve_time, open_cycle_for_client, open_escalation,
    assert_escalation,
    TEST_USERS, make_client_headers, make_va_headers,
)

SM = TEST_USERS["staffing_manager_headers"]


def _two_va_active_client(api, skill_code):
    """Active client on E1 with VA-old, plus a second AVAILABLE VA-new for
    replacement, plus an OPEN escalation. Returns a context dict."""
    from test_helpers import set_clock, create_skill_tag, create_sla_policy, create_va, \
        create_client, scope_client
    set_clock()
    skill = create_skill_tag(skill_code)
    create_sla_policy()
    va_old = create_va([skill["id"]], full_name="Va Old")
    va_new = create_va([skill["id"]], full_name="Va New")
    client = create_client()
    scope_client(client["id"], [skill["id"]])
    eng = validate_success(api.create_engagement(
        create_engagement_payload(client["id"], va_old["id"]), SM), 201)
    validate_success(api.accept_engagement(eng["id"], make_client_headers(client["id"])), 200)
    validate_success(api.activate_engagement(
        eng["id"], activate_engagement_payload(True), SM), 200)
    return {"skill": skill, "va_old": va_old, "va_new": va_new, "client": client,
            "engagement": eng, "client_headers": make_client_headers(client["id"]),
            "va_old_headers": make_va_headers(va_old["id"])}


# ─── Escalation replace three-hop cascade (difficulty 4.A) ──────────────────
def test_escalation_replace_three_hop_cascade(api):
    """PRD §3.7: "First, the system mints a brand-new engagement in `ACTIVE` status for the same client with the replacement VA, points the client's `active_engagement_id` at it, and increments the new VA's `active_engagement_count` by 1. Second — because that new engagement is now active — the original engagement is moved to `ENDED`: the old VA's `active_engagement_count` is decremented and the old VA returns to `AVAILABLE` if it reaches 0, and the original engagement's `superseded_by_engagement_id` is set to the new engagement's id. Third — as the engagement-end side effect fires — the original engagement's non-terminal tasks are re-pointed to the new `engagement_id".

    Design: Difficulty/transitive_cascade/escalation_replace_three_hop_cascade
    """
    ctx = _two_va_active_client(api, "GENERAL_ADMIN")
    task = create_assigned_task(
        {"client": ctx["client"], "skill": ctx["skill"],
         "client_headers": ctx["client_headers"], "va_headers": ctx["va_old_headers"]})
    esc = open_escalation({"client": ctx["client"]}, reason="QUALITY")
    res = api.replace_escalation(
        esc["id"], replace_escalation_payload(ctx["va_new"]["id"]), SM)
    replaced = validate_success(res, 200)
    assert replaced["status"] == "REPLACED"
    rep_eng = replaced["replacement_engagement_id"]
    assert rep_eng is not None
    e1 = validate_success(api.get_engagement(ctx["engagement"]["id"], SM), 200)
    assert e1["status"] == "ENDED"
    assert e1["superseded_by_engagement_id"] == rep_eng
    task_after = validate_success(api.get_task(task["id"], SM), 200)
    assert task_after["engagement_id"] == rep_eng
    va_old = validate_success(api.get_virtual_assistant(ctx["va_old"]["id"], SM), 200)
    va_new = validate_success(api.get_virtual_assistant(ctx["va_new"]["id"], SM), 200)
    assert va_old["active_engagement_count"] == 0
    assert va_new["active_engagement_count"] == 1


def test_escalation_replace_mints_active_replacement_engagement(api):
    """PRD §3.7: "the system mints a brand-new engagement in `ACTIVE` status for the same client with the replacement VA, points the client's `active_engagement_id` at it".
    PRD §3.7: "Finally the escalation's `replacement_engagement_id` is set to the new engagement's id and the escalation itself rests in `REPLACED"

    Design: Difficulty/transitive_cascade/escalation_replace_three_hop_cascade
    """
    ctx = _two_va_active_client(api, "GENERAL_ADMIN2")
    esc = open_escalation({"client": ctx["client"]}, reason="QUALITY")
    replaced = validate_success(api.replace_escalation(
        esc["id"], replace_escalation_payload(ctx["va_new"]["id"]), SM), 200)
    rep_eng_id = replaced["replacement_engagement_id"]
    assert rep_eng_id is not None
    rep_eng = validate_success(api.get_engagement(rep_eng_id, SM), 200)
    assert rep_eng["status"] == "ACTIVE"
    assert rep_eng["client_id"] == ctx["client"]["id"]
    assert rep_eng["va_id"] == ctx["va_new"]["id"]
    client = validate_success(api.get_client(ctx["client"]["id"], SM), 200)
    assert client["active_engagement_id"] == rep_eng_id


# ─── Engagement-count conservation across replacement (difficulty 9.B) ──────
def test_replacement_conserves_total_active_engagement_count(api):
    """PRD §3.7: "the system mints a brand-new engagement in `ACTIVE` status for the same client with the replacement VA, points the client's `active_engagement_id` at it, and increments the new VA's `active_engagement_count` by 1"
    PRD §3.7: "the original engagement is moved to `ENDED`: the old VA's `active_engagement_count` is decremented and the old VA returns to `AVAILABLE` if it reaches 0".

    Design: Difficulty/compensating_invariant/replacement_conserves_total_active_engagement_count
    """
    ctx = _two_va_active_client(api, "OPS_ADMIN")
    esc = open_escalation({"client": ctx["client"]}, reason="AVAILABILITY")
    replaced = validate_success(api.replace_escalation(
        esc["id"], replace_escalation_payload(ctx["va_new"]["id"]), SM), 200)
    rep_eng = replaced["replacement_engagement_id"]
    va_old = validate_success(api.get_virtual_assistant(ctx["va_old"]["id"], SM), 200)
    va_new = validate_success(api.get_virtual_assistant(ctx["va_new"]["id"], SM), 200)
    client = validate_success(api.get_client(ctx["client"]["id"], SM), 200)
    e1 = validate_success(api.get_engagement(ctx["engagement"]["id"], SM), 200)
    # Total ACTIVE headcount conserved at 1: old 0 + new 1.
    assert va_old["active_engagement_count"] == 0
    assert va_new["active_engagement_count"] == 1
    assert client["active_engagement_id"] == rep_eng
    assert e1["status"] == "ENDED"


def test_replacement_frees_old_va_to_available(api):
    """PRD §3.7: "the original engagement is moved to `ENDED`: the old VA's `active_engagement_count` is decremented and the old VA returns to `AVAILABLE` if it reaches 0".

    Design: Difficulty/compensating_invariant/replacement_conserves_total_active_engagement_count
    """
    ctx = _two_va_active_client(api, "OPS_ADMIN2")
    esc = open_escalation({"client": ctx["client"]}, reason="AVAILABILITY")
    validate_success(api.replace_escalation(
        esc["id"], replace_escalation_payload(ctx["va_new"]["id"]), SM), 200)
    va_old = validate_success(api.get_virtual_assistant(ctx["va_old"]["id"], SM), 200)
    # Old VA's only engagement ended -> count 0 -> back to AVAILABLE.
    assert va_old["active_engagement_count"] == 0
    assert va_old["status"] == "AVAILABLE"


# ─── Resolve escalation leaves engagement running (corner) ──────────────────
def test_resolve_escalation_keeps_engagement_running(api):
    """PRD §3.7: "The StaffingManager either **resolves** it (`OPEN → RESOLVED`), leaving the original engagement running unchanged, or **replaces** the VA (`OPEN → REPLACED"

    Design: Corner/state_machines/resolve_escalation_keeps_engagement_running
    """
    ctx = setup_active_client_engagement(skill_code="ESC_SK")
    esc = open_escalation(ctx, reason="OTHER")
    res = api.resolve_escalation(esc["id"], SM)
    data = validate_success(res, 200)
    assert_escalation(data)
    assert data["status"] == "RESOLVED"
    eng = validate_success(api.get_engagement(ctx["engagement"]["id"], SM), 200)
    assert eng["status"] == "ACTIVE"


# ─── Client close two-hop cascade (difficulty 4.B) ──────────────────────────
def test_client_close_two_hop_cascade_tasks_then_entries(api):
    """PRD §3.2: "First, every non-terminal task of the client (anything not already `DONE` or `CANCELLED`) is moved to `CANCELLED`. Second — as a consequence of each of those task cancellations — every `LOGGED` time entry on those tasks is moved to `REJECTED`, so it never charges a cycle"

    Design: Difficulty/transitive_cascade/client_close_two_hop_cascade_tasks_then_entries
    """
    ctx = setup_active_client_engagement(skill_code="FILING")
    task = create_assigned_task(ctx)  # ASSIGNED, not IN_PROGRESS (close precondition)
    entry = log_time(ctx, task["id"], 90)  # LOGGED
    closed = validate_success(api.close_client(ctx["client"]["id"], SM), 200)
    assert closed["status"] == "CLOSED"
    task_after = validate_success(api.get_task(task["id"], SM), 200)
    assert task_after["status"] == "CANCELLED"
    entry_after = validate_success(api.get_time_entry(entry["id"], SM), 200)
    assert entry_after["status"] == "REJECTED"


def test_client_close_cancels_non_terminal_task(api):
    """PRD §3.2: "First, every non-terminal task of the client (anything not already `DONE` or `CANCELLED`) is moved to `CANCELLED"
    PRD §3.2: "A client may be **closed** from `SCOPED`, `ACTIVE`, or `SUSPENDED`, but only when none of its tasks is currently `IN_PROGRESS".

    Design: Difficulty/transitive_cascade/client_close_two_hop_cascade_tasks_then_entries
    """
    ctx = setup_active_client_engagement(skill_code="FILING2")
    task = create_assigned_task(ctx)  # ASSIGNED (not IN_PROGRESS)
    validate_success(api.close_client(ctx["client"]["id"], SM), 200)
    task_after = validate_success(api.get_task(task["id"], SM), 200)
    assert task_after["status"] == "CANCELLED"


# ─── Hour-bank conservation under cancel (difficulty 9.A) ───────────────────
def test_cancel_rejects_logged_entry_leaves_consumed_hours_invariant(api):
    """PRD §3.4: "cancellation moves the task's `LOGGED` time entries to `REJECTED` so they never charge a cycle, and recomputes `open_task_count"
    PRD §3.5: "The cycle balance is an aggregation over **only** the `APPROVED` entries pinned to that cycle (`LOGGED` and `REJECTED` entries are excluded): `consumed_hours` is the sum of those entries' `billable_hours".

    Design: Difficulty/compensating_invariant/cancel_rejects_logged_entry_leaves_consumed_hours_invariant
    """
    ctx = setup_active_client_engagement(skill_code="ACCOUNTS_PAYABLE", monthly_retainer_hours=10)
    task = create_in_progress_task(ctx, estimated_hours=6)
    appr = log_and_approve_time(ctx, task["id"], 240)  # APPROVED 4.0h
    logged = log_time(ctx, task["id"], 120)            # LOGGED 2.0h
    cyc = open_cycle_for_client(ctx["client"]["id"])
    validate_success(api.cancel_task(task["id"], SM), 200)
    logged_after = validate_success(api.get_time_entry(logged["id"], SM), 200)
    appr_after = validate_success(api.get_time_entry(appr["id"], SM), 200)
    cyc_after = validate_success(api.get_cycle(cyc["id"], SM), 200)
    assert logged_after["status"] == "REJECTED"
    assert appr_after["status"] == "APPROVED"
    assert cyc_after["consumed_hours"] == pytest.approx(4.0, abs=1e-9)
    assert cyc_after["available_hours"] == pytest.approx(6.0, abs=1e-9)


def test_cancel_only_logged_entry_leaves_consumed_hours_at_zero(api):
    """PRD §3.4: "cancellation moves the task's `LOGGED` time entries to `REJECTED` so they never charge a cycle".
    PRD §3.5: "The cycle balance is an aggregation over **only** the `APPROVED` entries pinned to that cycle (`LOGGED` and `REJECTED` entries are excluded".

    Design: Difficulty/compensating_invariant/cancel_rejects_logged_entry_leaves_consumed_hours_invariant
    """
    ctx = setup_active_client_engagement(skill_code="ACCOUNTS_PAYABLE2", monthly_retainer_hours=10)
    task = create_in_progress_task(ctx, estimated_hours=2)
    logged = log_time(ctx, task["id"], 120)  # LOGGED 2.0h, never approved
    cyc = open_cycle_for_client(ctx["client"]["id"])
    validate_success(api.cancel_task(task["id"], SM), 200)
    logged_after = validate_success(api.get_time_entry(logged["id"], SM), 200)
    cyc_after = validate_success(api.get_cycle(cyc["id"], SM), 200)
    assert logged_after["status"] == "REJECTED"
    # No APPROVED entry ever charged: consumed stays 0, full bank available.
    assert cyc_after["consumed_hours"] == pytest.approx(0.0, abs=1e-9)
    assert cyc_after["available_hours"] == pytest.approx(10.0, abs=1e-9)


# NOTE — SKIPPED: Corner/validations/replace_with_benched_va_returns_replacement_ineligible
# The recipe supplies a never-created UUID (00000000-...-aa) as the replacement va_id and
# asserts ERR_REPLACEMENT_INELIGIBLE. Under faithful PRD semantics this is not
# uniquely-derivable: PRD §2.6/§2.7 validate body foreign keys at priority 4 — a va_id
# referencing no VirtualAssistant yields ERR_REFERENCED_ENTITY_NOT_FOUND (422), which
# precedes the priority-21 eligibility gate (ERR_REPLACEMENT_INELIGIBLE). Two PRD-only
# implementers would disagree on the outcome, so no test is emitted.


# ─── Duplicate email (corner) ────────────────────────────────────────────────
def test_duplicate_client_email_returns_duplicate(api):
    """PRD §3.2: "A client enters the platform through intake, supplying a `company_name` and a `contact_email` (unique across all clients; a collision is `ERR_DUPLICATE"

    Design: Corner/validations/duplicate_client_email_returns_duplicate
    """
    email = unique_email("dup")
    validate_success(api.create_client(
        create_client_payload(company_name="First", contact_email=email), SM), 201)
    res = api.create_client(create_client_payload(company_name="Second", contact_email=email), SM)
    validate_error(res, "ERR_DUPLICATE", expected_status=409)
