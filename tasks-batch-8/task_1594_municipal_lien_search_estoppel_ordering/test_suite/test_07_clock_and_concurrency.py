"""Clock-sweep scheduling, optimistic concurrency, and immediate-consistency
claims."""
from test_helpers import (
    ApiErrorId,
    UTILITY_ONLY_DEPARTMENTS,
    complete_task,
    create_search_order,
    get_estoppel,
    get_order,
    get_task,
    make_qa_reviewer_headers,
    make_research_analyst_headers,
    make_title_agent_headers,
    patch_order_payload,
    place_estoppel,
    record_findings,
    set_clock,
    setup_identified_order,
    validate_error,
    validate_success,
)

AGENT = make_title_agent_headers("agent_1")
ANALYST = make_research_analyst_headers("analyst_1")
ANALYST2 = make_research_analyst_headers("analyst_2")
QA = make_qa_reviewer_headers("qa_1")


def test_patch_with_stale_version_rejected(api):
    """PRD 2.7: "Updating a search order requires the request to carry
    `expected_search_order_version` holding the caller's last observed `version`
    of that order. If the order's current `version` has advanced since — because
    another accepted write, including a cascaded mutation from task completion,
    estoppel receipt, or an expiry sweep, moved it forward — the update is
    rejected with `ERR_STALE_VERSION` (HTTP 412), since the caller's
    `closing_date` or `association_id` edit rests on a stale view."

    Design: Corner/complexity_layers/patch_order_stale_version_rejected
    """
    set_clock()
    order = create_search_order("P-AF1")
    observed_version = order["version"]

    first = validate_success(
        api.patch_search_order(
            order["id"],
            patch_order_payload(observed_version, closing_date="2026-08-25"),
            AGENT,
        ),
        200,
    )
    assert first["version"] == observed_version + 1

    response = api.patch_search_order(
        order["id"],
        patch_order_payload(observed_version, closing_date="2026-08-26"),
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)
    assert get_order(order["id"])["closing_date"] == "2026-08-25"


def test_record_findings_with_stale_version_rejected(api):
    """PRD 2.7: "Recording findings on a research task likewise requires
    `expected_research_task_version` matching the task's current `version`.
    Because findings use overwrite semantics, a write based on an older version
    would silently discard an update it never saw, so the mismatch is rejected
    with `ERR_STALE_VERSION` (HTTP 412) and the writer must re-read the task and
    resubmit."

    Design: Corner/complexity_layers/record_findings_stale_version_rejected
    """
    ctx = setup_identified_order(
        "P-AG2", departments=UTILITY_ONLY_DEPARTMENTS, with_association=False
    )
    task = ctx["tasks"][0]
    stale_version = task["version"]

    first = record_findings(
        task, [{"finding_kind": "UNPAID_UTILITY", "amount_cents": 100000}]
    )
    assert first["version"] == stale_version + 1
    assert first["unpaid_balance_cents"] == 100000

    response = api.record_findings(
        task["id"],
        {
            "expected_research_task_version": stale_version,
            "findings": [{"finding_kind": "UNPAID_UTILITY", "amount_cents": 200000}],
        },
        ANALYST2,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)
    assert get_task(task["id"])["unpaid_balance_cents"] == 100000


def test_clock_sweep_marks_estoppel_overdue_after_due_date(api):
    """PRD 3.5: "Placement moves the estoppel from `DRAFT` to `ORDERED`, stamps
    `ordered_at` with the clock, and computes `statutory_due_at` as the ordered
    date plus the statute's `estoppel_response_days` calendar days, fixed at
    23:59:59.000Z on the resulting date."
    PRD 2.4: "Setting the clock triggers the estoppel sweep: every estoppel
    order still awaiting its letter whose statutory due date has passed
    transitions from `ORDERED` to `OVERDUE`"
    PRD 3.5: "An estoppel is late exactly when its received date is after its
    statutory due date."

    Design: Corner/complexity_layers/clock_sweep_marks_estoppel_overdue
    """
    ctx = setup_identified_order(
        "P-AH3",
        departments=UTILITY_ONLY_DEPARTMENTS,
        order_overrides={"closing_date": "2026-09-20"},
    )
    estoppel = ctx["estoppels"][0]
    place_estoppel(estoppel["id"], 10000)

    # Ordered 2026-08-01 + 10 statutory days -> due at end of 2026-08-11.
    set_clock("2026-08-11T10:00:00Z")
    on_due_date = get_estoppel(estoppel["id"])
    assert on_due_date["statutory_due_at"] == "2026-08-11T23:59:59.000Z"
    assert on_due_date["status"] == "ORDERED", (
        "On the due date itself the deadline has not passed; still ORDERED"
    )

    set_clock("2026-08-12T10:00:00Z")
    past_due = get_estoppel(estoppel["id"])
    assert past_due["status"] == "OVERDUE"


def test_mutation_results_visible_in_response(api):
    """PRD 2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD 3.4: "The task's `unpaid_balance_cents` is recomputed on every findings
    write"
    PRD 3.4: "Completing a task — allowed only once findings have been
    recorded — moves it from `IN_PROGRESS` to `COMPLETED`, records the caller in
    `completed_by_user_id`, and fixes `fee_charged_cents` as the snapshotted
    `fee_base_cents` plus, when the owning order is `RUSH`, the snapshotted
    `fee_rush_surcharge_cents`."

    Design: Corner/consistency_model/immediate_visibility_of_mutation_in_same_response
    """
    ctx = setup_identified_order(
        "P-AI4", departments=UTILITY_ONLY_DEPARTMENTS, with_association=False
    )
    task = ctx["tasks"][0]

    response = api.record_findings(
        task["id"],
        {
            "expected_research_task_version": task["version"],
            "findings": [{"finding_kind": "UNPAID_UTILITY", "amount_cents": 300000}],
        },
        ANALYST,
    )
    recorded = validate_success(response, 200)
    assert recorded["status"] == "IN_PROGRESS"
    assert recorded["unpaid_balance_cents"] == 300000

    completed = validate_success(api.complete_task(task["id"], ANALYST), 200)
    assert completed["status"] == "COMPLETED"
    assert completed["fee_charged_cents"] == 5000
