"""Root-cause tasks: lifecycle, segregation of duties, recurrence monitoring (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    create_task_payload,
    get_scorecard,
    get_task,
    get_auto_task_for_denial,
    make_denial,
    make_scorecard,
    make_verified_task,
    manager_headers,
    set_clock,
    setup_catalog,
    triage_denial,
    upstream_owner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

VERIFY_CITE = (
    'PRD §3.7: "A successful verification stamps `verified_at` from the logical clock, sets '
    '`monitoring_until_date` to the verified date plus 90 days, and moves the task to '
    '`VERIFIED`."'
)


def _verified_task_scenario(api, catalog, scorecard):
    """CLM-502 preventable triage -> auto task -> ack/implement (uo-1) -> verify (mgr-1)
    at clock 2026-08-10; then intake CLM-503 at clock 2026-08-12. Returns ids."""
    denial1 = make_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-502", denied_amount_cents=100000, billed_amount_cents=120000,
    )
    triage_denial(denial1["id"], preventable_flag=True)
    task = get_auto_task_for_denial(denial1["id"])
    validate_success(api.acknowledge_task(task["id"], upstream_owner_headers("uo-1")))
    validate_success(
        api.implement_fix(task["id"], {"fix_summary": "Corrected modifier mapping in encoder"},
                          upstream_owner_headers("uo-1"))
    )
    set_clock("2026-08-10T00:00:00Z")
    verified = validate_success(api.verify_task(task["id"], manager_headers("mgr-1")))
    set_clock("2026-08-12T00:00:00Z")
    denial2 = make_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-503", denied_amount_cents=60000, billed_amount_cents=70000,
        service_date="2026-07-15", remittance_received_date="2026-08-12",
    )
    return denial1["id"], denial2["id"], verified


def test_task_reopen_cycle_verify_then_recurrence(api):
    """PRD §3.7: "A successful verification stamps `verified_at` from the logical clock, sets
    `monitoring_until_date` to the verified date plus 90 days, and moves the task to
    `VERIFIED`."
    PRD §3.7: "the triage recurrence sweep flips the single best-matching task `VERIFIED` →
    `REOPENED`: best match means the earliest `verified_at`, with ties broken by the earlier
    `created_at`. The reopen increments `reopened_count` by one and clears `verified_at` and
    `monitoring_until_date` to null."

    Design: Difficulty/non_linear_state_machine/root_cause_task_reopen_cycle
    """
    catalog = setup_catalog(levels=())
    make_scorecard(period_end_date="2027-01-01")
    _, denial2_id, verified = _verified_task_scenario(api, catalog, None)
    assert verified["status"] == "VERIFIED"
    assert verified["monitoring_until_date"] == "2026-11-08"  # verified 2026-08-10 + 90 days
    triage_denial(denial2_id, preventable_flag=False)
    task = get_task(verified["id"])
    assert task["status"] == "REOPENED"
    assert task["reopened_count"] == 1
    assert task["verified_at"] is None
    assert task["monitoring_until_date"] is None


def test_task_reopen_cycle_reacknowledge_and_scorecard(api):
    """PRD §3.7: "An `UpstreamOwner` acknowledges a task, moving `OPEN` → `ACKNOWLEDGED` or
    `REOPENED` → `ACKNOWLEDGED` — from any other state, `ERR_TASK_INVALID_STATE`."
    PRD §3.7: "On the scorecard, `verified_fix_count` decreases by one,
    `verified_linked_denied_cents` decreases by that task's denial's denied amount,
    `recurrence_count` increases by one, `recurrence_linked_denied_cents` increases by the
    *new* denial's denied amount, and `open_task_count` increases by one; the `TASK_REOPENED`
    event attaches to the new denial."

    Design: Difficulty/non_linear_state_machine/root_cause_task_reopen_cycle
    """
    catalog = setup_catalog(levels=())
    scorecard = make_scorecard(period_end_date="2027-01-01")
    _, denial2_id, verified = _verified_task_scenario(api, catalog, scorecard)
    triage_denial(denial2_id, preventable_flag=False)
    reack = validate_success(
        api.acknowledge_task(verified["id"], upstream_owner_headers("uo-2"))
    )
    assert reack["status"] == "ACKNOWLEDGED"
    sc = get_scorecard(scorecard["id"])
    assert sc["verified_fix_count"] == 0
    assert sc["recurrence_count"] == 1
    assert sc["open_task_count"] == 1


def test_verified_fix_conservation_counters(api, manager_headers):
    """PRD §2.9: "A verification adds one to the count and adds the linked denial's denied
    amount to `verified_linked_denied_cents`; a recurrence reopen subtracts one and subtracts
    that same amount. The pair must leave both figures identical to their pre-pair values.
    The recurrence counters — `recurrence_count` and `recurrence_linked_denied_cents` —
    accumulate separately and are not part of the conserved quantity."

    Design: Difficulty/compensating_invariant/verified_fix_count_verify_reopen
    """
    catalog = setup_catalog(levels=())
    scorecard = make_scorecard(period_end_date="2027-01-01")
    scenario = make_verified_task(
        catalog["payer"]["id"], catalog["code"]["id"], "CLM-1701",
        denied_amount_cents=100000, verify_clock="2026-08-10T00:00:00Z",
    )
    pre = get_scorecard(scorecard["id"])
    assert pre["verified_fix_count"] == 1
    assert pre["verified_linked_denied_cents"] == 100000
    set_clock("2026-08-12T00:00:00Z")
    denial2 = make_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-1702", denied_amount_cents=60000, billed_amount_cents=70000,
        service_date="2026-07-15", remittance_received_date="2026-08-12",
    )
    triage_denial(denial2["id"], preventable_flag=False)
    post = get_scorecard(scorecard["id"])
    assert post["verified_fix_count"] == 0, "verify/reopen pair restores the pre-pair count"
    assert post["verified_linked_denied_cents"] == 0
    assert post["recurrence_count"] == 1
    assert post["recurrence_linked_denied_cents"] == 60000, "the NEW denial's denied amount"


def test_verified_fix_conservation_live_count_matches(api, manager_headers):
    """PRD §2.9: "A scorecard's `verified_fix_count` always equals the number of the
    department's root-cause tasks that are currently `VERIFIED` and whose verification event
    date falls inside the scorecard period."

    Design: Difficulty/compensating_invariant/verified_fix_count_verify_reopen
    """
    catalog = setup_catalog(levels=())
    scorecard = make_scorecard(period_end_date="2027-01-01")
    make_verified_task(
        catalog["payer"]["id"], catalog["code"]["id"], "CLM-1701",
        denied_amount_cents=100000, verify_clock="2026-08-10T00:00:00Z",
    )
    set_clock("2026-08-12T00:00:00Z")
    denial2 = make_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-1702", denied_amount_cents=60000, billed_amount_cents=70000,
        service_date="2026-07-15", remittance_received_date="2026-08-12",
    )
    triage_denial(denial2["id"], preventable_flag=False)
    rows, meta = validate_paginated(
        api.list_root_cause_tasks(
            manager_headers, params={"department": "CODING", "status": "VERIFIED"},
        )
    )
    assert rows == []
    sc = get_scorecard(scorecard["id"])
    assert sc["verified_fix_count"] == 0, "matches the live count of VERIFIED tasks"


def test_task_close_within_monitoring_rejected(api, manager_headers):
    """PRD §3.7: "Once monitoring has fully elapsed, a `DenialsManager` closes the task: from
    `VERIFIED` only (else `ERR_TASK_INVALID_STATE`), and only when today is later than
    `monitoring_until_date` — closing on or before that date fails with
    `ERR_MONITORING_WINDOW_ACTIVE`. `CLOSED` is terminal."

    Design: Corner/state_machines/task_close_within_monitoring_rejected
    """
    catalog = setup_catalog(levels=())
    scenario = make_verified_task(
        catalog["payer"]["id"], catalog["code"]["id"], "CLM-2106",
        verify_clock="2026-08-10T00:00:00Z",
    )
    task = scenario["task"]
    assert task["monitoring_until_date"] == "2026-11-08"
    set_clock("2026-08-20T00:00:00Z")
    resp = api.close_task(task["id"], manager_headers)
    validate_error(resp, ApiErrorId.ERR_MONITORING_WINDOW_ACTIVE, expected_status=409)
    set_clock("2026-11-09T00:00:00Z")  # one day past the monitoring horizon
    closed = validate_success(api.close_task(task["id"], manager_headers))
    assert closed["status"] == "CLOSED"


def test_task_verify_by_implementer_rejected(api):
    """PRD §3.7: "Verification belongs to a `DenialsManager` and enforces segregation of
    duties: the task must be `FIX_IMPLEMENTED` (else `ERR_TASK_INVALID_STATE`) and the
    verifier's `X-User-ID` must differ from `implemented_by_user_id` (else
    `ERR_SEGREGATION_OF_DUTIES`)."

    Design: Corner/state_machines/task_verify_by_implementer_rejected
    """
    catalog = setup_catalog(levels=())
    denial = make_denial(catalog["payer"]["id"], catalog["code"]["id"],
                         claim_number="CLM-2107", denied_amount_cents=100000,
                         billed_amount_cents=120000)
    triage_denial(denial["id"], preventable_flag=True)
    task = get_auto_task_for_denial(denial["id"])
    validate_success(api.acknowledge_task(task["id"], upstream_owner_headers("uo-1")))
    validate_success(
        api.implement_fix(task["id"], {"fix_summary": "Fixed encoder mapping"},
                          upstream_owner_headers("uo-1"))
    )
    # Manager role but the same user id that implemented the fix.
    resp = api.verify_task(task["id"], manager_headers("uo-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    after = get_task(task["id"])
    assert after["status"] == "FIX_IMPLEMENTED"


def test_recurrence_link_requires_verified_same_department(api, manager_headers):
    """PRD §3.7: "A supplied recurrence link must resolve — an unresolvable reference is a
    404 under reference resolution — and must then point at a `VERIFIED` task in the same
    department and never at the new task itself; a self-referential, non-`VERIFIED`, or
    cross-department link is rejected with `ERR_INVALID_RECURRENCE_LINK`."

    Design: Corner/validations/recurrence_link_requires_verified_same_department
    """
    catalog = setup_catalog(levels=())
    denial1 = make_denial(catalog["payer"]["id"], catalog["code"]["id"],
                          claim_number="CLM-2308", denied_amount_cents=100000,
                          billed_amount_cents=120000)
    triage_denial(denial1["id"], preventable_flag=True)
    task1 = get_auto_task_for_denial(denial1["id"])  # still OPEN, not VERIFIED
    denial2 = make_denial(catalog["payer"]["id"], catalog["code"]["id"],
                          claim_number="CLM-2309", denied_amount_cents=100000,
                          billed_amount_cents=120000, service_date="2026-07-12",
                          remittance_received_date="2026-08-02")
    triage_denial(denial2["id"], preventable_flag=False)
    resp = api.create_root_cause_task(
        create_task_payload(
            denial2["id"], task_type="TRAINING", description="Recurrence follow-up",
            due_date="2026-08-20", recurrence_of_task_id=task1["id"],
        ),
        manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_RECURRENCE_LINK, expected_status=422)


def test_upstream_owner_cannot_verify_task(api):
    """PRD §2.8: "**Authorization.** The authenticated role must appear in the endpoint's
    authorized role list, else `ERR_FORBIDDEN` (403). Applies to every endpoint."
    PRD §4: "| POST | `/rcm/root-cause-tasks/{id}/verify` | Verify an implemented fix
    (verifier must differ from implementer) | DenialsManager |"

    Design: Corner/rbac/upstream_owner_cannot_verify_task
    """
    catalog = setup_catalog(levels=())
    denial = make_denial(catalog["payer"]["id"], catalog["code"]["id"],
                         claim_number="CLM-2501", denied_amount_cents=100000,
                         billed_amount_cents=120000)
    triage_denial(denial["id"], preventable_flag=True)
    task = get_auto_task_for_denial(denial["id"])
    validate_success(api.acknowledge_task(task["id"], upstream_owner_headers("uo-1")))
    validate_success(
        api.implement_fix(task["id"], {"fix_summary": "Encoder mapping corrected"},
                          upstream_owner_headers("uo-1"))
    )
    resp = api.verify_task(task["id"], upstream_owner_headers("uo-2"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    after = get_task(task["id"])
    assert after["status"] == "FIX_IMPLEMENTED"
