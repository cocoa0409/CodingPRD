"""State-machine claims: spawn fan-out, terminal lockdown, invalid transitions,
the unreachable retry loop, cancellation cascades, and delivery bookkeeping."""
from test_helpers import (
    ApiErrorId,
    ESTOPPEL_PAYOFF,
    FINDINGS_EMPTY,
    UTILITY_ONLY_DEPARTMENTS,
    create_association,
    create_search_order,
    file_discrepancy,
    get_delivery,
    get_discrepancy,
    get_estoppel,
    get_order,
    get_task,
    identify_order,
    list_order_estoppels,
    make_qa_reviewer_headers,
    make_research_analyst_headers,
    make_title_agent_headers,
    patch_order_payload,
    place_estoppel,
    receive_estoppel,
    setup_config_a,
    setup_identified_order,
    setup_with_ready_delivery,
    validate_error,
    validate_success,
)

AGENT = make_title_agent_headers("agent_1")
ANALYST = make_research_analyst_headers("analyst_1")
QA = make_qa_reviewer_headers("qa_1")


def test_identify_spawns_pending_tasks_and_draft_estoppel(api):
    """PRD 3.3: "A successful identification moves the order from `INTAKE` to
    `RESEARCH_IN_PROGRESS`, writes the `jurisdiction_id`, pins the covering statute
    into `statute_id` for the life of the order, and advances the order's `version`
    by 1. It then spawns one research task in `PENDING` for each `ACTIVE`
    department of the jurisdiction, created in department `created_at` ascending
    order so the task list is deterministic; each task snapshots the department's
    current `research_fee_cents` into `fee_base_cents` and `rush_surcharge_cents`
    into `fee_rush_surcharge_cents`, copies the `dept_type`, and records its
    `search_order_id` and `department_id`. When an association is attached, an
    estoppel order is also spawned in `DRAFT` against that association."

    Design: Corner/state_machines/spawned_children_start_in_initial_states
    """
    ctx = setup_identified_order(
        "P-I1", departments=UTILITY_ONLY_DEPARTMENTS, with_association=True
    )
    order = ctx["order"]
    assert order["status"] == "RESEARCH_IN_PROGRESS"
    assert order["statute_id"] == ctx["statute"]["id"]
    assert order["jurisdiction_id"] == ctx["jurisdiction"]["id"]

    tasks = ctx["tasks"]
    assert len(tasks) == 1, f"Expected exactly 1 spawned task, got {len(tasks)}"
    task = tasks[0]
    assert task["status"] == "PENDING"
    assert task["department_id"] == ctx["departments"][0]["id"]
    assert task["fee_base_cents"] == 5000
    assert task["fee_rush_surcharge_cents"] == 2500

    estoppels = ctx["estoppels"]
    assert len(estoppels) == 1, (
        f"Expected exactly 1 spawned estoppel, got {len(estoppels)}"
    )
    assert estoppels[0]["status"] == "DRAFT"
    assert estoppels[0]["association_id"] == ctx["association"]["id"]


def test_cancelled_order_rejects_identify(api):
    """PRD 3.7: "`CANCELLED` is terminal: no further transition out of it is
    permitted, and the same terminal lockdown applies to `CANCELLED` tasks and
    estoppels and to deliveries that have reached `ACKNOWLEDGED`, `SUPERSEDED`,
    or `VOIDED`."
    PRD 2.8: "fourth, whether the target resource sits in a state that permits
    the requested transition, including the blanket refusal of any transition out
    of a terminal state and the deliverability gate on delivery
    (`ERR_INVALID_STATE_TRANSITION` or `ERR_ORDER_NOT_DELIVERABLE` as applicable)"

    Design: Corner/state_machines/cancelled_order_rejects_identify
    """
    ctx = setup_config_a(departments=UTILITY_ONLY_DEPARTMENTS, with_association=False)
    order = create_search_order("P-T3", property_address="3 T St")
    validate_success(api.cancel_search_order(order["id"], AGENT))

    response = api.identify_jurisdiction(
        order["id"], {"jurisdiction_id": ctx["jurisdiction"]["id"]}, ANALYST
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    assert get_order(order["id"])["status"] == "CANCELLED"


def test_complete_task_from_pending_rejected(api):
    """PRD 3.4: "Completing a task — allowed only once findings have been
    recorded — moves it from `IN_PROGRESS` to `COMPLETED`, records the caller in
    `completed_by_user_id`, and fixes `fee_charged_cents` as the snapshotted
    `fee_base_cents` plus, when the owning order is `RUSH`, the snapshotted
    `fee_rush_surcharge_cents`."

    Design: Corner/state_machines/complete_from_pending_returns_invalid_state
    """
    ctx = setup_identified_order(
        "P-U1", departments=UTILITY_ONLY_DEPARTMENTS, with_association=False
    )
    task = ctx["tasks"][0]
    response = api.complete_task(task["id"], ANALYST)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    assert get_task(task["id"])["status"] == "PENDING"


def test_place_received_estoppel_rejected(api):
    """PRD 3.5: "Placement moves the estoppel from `DRAFT` to `ORDERED`, stamps
    `ordered_at` with the clock, and computes `statutory_due_at` as the ordered
    date plus the statute's `estoppel_response_days` calendar days, fixed at
    23:59:59.000Z on the resulting date."
    PRD 3.5: "An expired letter can be renewed by placing it again"

    Design: Corner/state_machines/place_from_received_returns_invalid_state
    """
    ctx = setup_identified_order("P-W1", departments=UTILITY_ONLY_DEPARTMENTS)
    estoppel = ctx["estoppels"][0]
    place_estoppel(estoppel["id"], 10000)
    receive_estoppel(estoppel["id"], ESTOPPEL_PAYOFF)

    response = api.place_estoppel(
        estoppel["id"], {"fee_quoted_cents": 9000}, ANALYST
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    current = get_estoppel(estoppel["id"])
    assert current["status"] == "RECEIVED"
    assert current["fee_quoted_cents"] == 10000


def test_resolve_open_discrepancy_rejected(api):
    """PRD 3.8: "A `QAReviewer` picks the claim up by starting review, moving it
    from `OPEN` to `UNDER_REVIEW`, and later resolves it — moving it to
    `RESOLVED`, its terminal state — with a `resolution_outcome` of
    `CONFIRMED_CORRECTION`, `REJECTED_INVALID`, or `VOID_ORDER_CANCELLED`."

    Design: Corner/state_machines/resolve_from_open_returns_invalid_state
    """
    ctx = setup_identified_order(
        "P-D6", departments=UTILITY_ONLY_DEPARTMENTS, with_association=False
    )
    task = ctx["tasks"][0]
    discrepancy = file_discrepancy(
        ctx["order"]["id"], "RESEARCH_TASK", task["id"],
        "BALANCE_MISMATCH", 5000, "looks wrong",
    )
    assert discrepancy["status"] == "OPEN"

    response = api.resolve_discrepancy(
        discrepancy["id"], {"resolution_outcome": "REJECTED_INVALID"}, QA
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    assert get_discrepancy(discrepancy["id"])["status"] == "OPEN"
    assert get_order(ctx["order"]["id"])["pending_claims_cents"] == 5000


def test_acknowledge_ready_delivery_rejected(api):
    """PRD 3.6: "The owning `TitleAgent` then acknowledges receipt, moving the
    delivery from `DELIVERED` to `ACKNOWLEDGED`; anyone else is refused with
    `ERR_NOT_ORDER_OWNER`."

    Design: Corner/state_machines/acknowledge_ready_delivery_returns_invalid_state
    """
    ctx = setup_with_ready_delivery(
        "P-A7",
        departments=UTILITY_ONLY_DEPARTMENTS,
        findings_per_task=[FINDINGS_EMPTY],
    )
    delivery = ctx["delivery"]
    assert delivery["status"] == "READY"

    response = api.acknowledge_delivery(delivery["id"], AGENT)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    assert get_delivery(delivery["id"])["status"] == "READY"


def test_unreachable_then_retry_restores_task(api):
    """PRD 3.4: "A task that cannot reach its department can instead be moved to
    `UNABLE_TO_REACH` from either `PENDING` or `IN_PROGRESS` with a `reason`
    stored as `unreachable_reason`; such a task contributes nothing to order
    totals until it is retried and completed."
    PRD 3.4: "the same call against an `UNABLE_TO_REACH` task retries it,
    clearing the recorded `unreachable_reason` and returning it to `IN_PROGRESS`"

    Design: Corner/state_machines/unreachable_retry_cycle_restores_task
    """
    ctx = setup_identified_order(
        "P-B8", departments=UTILITY_ONLY_DEPARTMENTS, with_association=False
    )
    task = ctx["tasks"][0]

    response = api.mark_unreachable(
        task["id"], {"reason": "utility portal offline"}, ANALYST
    )
    unreachable = validate_success(response, 200)
    assert unreachable["status"] == "UNABLE_TO_REACH"
    assert unreachable["unreachable_reason"] == "utility portal offline"

    fresh = get_task(task["id"], ANALYST)
    response = api.record_findings(
        task["id"],
        {
            "expected_research_task_version": fresh["version"],
            "findings": [{"finding_kind": "UNPAID_UTILITY", "amount_cents": 12000}],
        },
        ANALYST,
    )
    retried = validate_success(response, 200)
    assert retried["status"] == "IN_PROGRESS"
    assert retried.get("unreachable_reason") is None
    assert retried["unpaid_balance_cents"] == 12000


def test_cancel_cascades_to_task_estoppel_and_discrepancy(api):
    """PRD 3.7: "Cancelling from a research-stage state additionally cascades:
    research tasks in `PENDING`, `IN_PROGRESS`, or `UNABLE_TO_REACH` move to
    `CANCELLED`, while `COMPLETED` tasks keep their fees; estoppels in `DRAFT`,
    `ORDERED`, or `OVERDUE` move to `CANCELLED`, while `RECEIVED` and `EXPIRED`
    estoppels keep their `lifetime_fees_cents` in the order's totals"
    PRD 3.7: "Across all cancellation paths, every `OPEN` or `UNDER_REVIEW`
    discrepancy of the order is force-resolved with `resolution_outcome` set to
    `VOID_ORDER_CANCELLED`, and the order's `pending_claims_cents` is decremented
    by each released claim."

    Design: Corner/state_machines/cancel_cascades_to_children_and_discrepancies
    """
    ctx = setup_identified_order("P-C9", departments=UTILITY_ONLY_DEPARTMENTS)
    task = ctx["tasks"][0]
    estoppel = ctx["estoppels"][0]
    place_estoppel(estoppel["id"], 10000)
    discrepancy = file_discrepancy(
        ctx["order"]["id"], "RESEARCH_TASK", task["id"],
        "BALANCE_MISMATCH", 5000, "wrong balance",
    )
    assert get_order(ctx["order"]["id"])["pending_claims_cents"] == 5000

    validate_success(api.cancel_search_order(ctx["order"]["id"], AGENT))

    assert get_task(task["id"])["status"] == "CANCELLED"
    assert get_estoppel(estoppel["id"])["status"] == "CANCELLED"
    resolved = get_discrepancy(discrepancy["id"])
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution_outcome"] == "VOID_ORDER_CANCELLED"
    assert get_order(ctx["order"]["id"])["pending_claims_cents"] == 0


def test_deliver_freezes_snapshot_and_acknowledge_completes(api):
    """PRD 3.6: "At the moment of release the delivery freezes its evidence:
    `snapshot_payoff_cents` and `snapshot_fees_cents` copy the order's totals, the
    liability-cap algorithm runs and its results are frozen into
    `coverage_fee_cents` and `liability_cap_cents`, `delivered_at` is stamped,
    `delivered_to_agent_id` copies the order's `title_agent_id`, and the order
    itself moves from `READY_FOR_DELIVERY` to `DELIVERED`."
    PRD 3.6: "Step two derives the provisional cap: ten times the base, clamped
    below by a floor of 25000 cents and above by a ceiling of 100000 cents — that
    is, the larger of the floor and the smaller of ten-times-base and the
    ceiling."
    PRD 3.6: "The owning `TitleAgent` then acknowledges receipt, moving the
    delivery from `DELIVERED` to `ACKNOWLEDGED`; anyone else is refused with
    `ERR_NOT_ORDER_OWNER`."

    Design: Corner/state_machines/deliver_freezes_snapshots_and_acknowledge_completes
    """
    ctx = setup_with_ready_delivery(
        "P-E10",
        departments=UTILITY_ONLY_DEPARTMENTS,
        findings_per_task=[[{"finding_kind": "UNPAID_UTILITY", "amount_cents": 300000}]],
    )
    # Base: task fee 5000 + estoppel fee 10000 = 15000 fees; payoff 345000.
    delivery = validate_success(api.deliver_delivery(ctx["delivery"]["id"], QA), 200)
    assert delivery["status"] == "DELIVERED"
    assert delivery["snapshot_payoff_cents"] == 345000
    assert delivery["snapshot_fees_cents"] == 15000
    assert delivery["coverage_fee_cents"] == 0
    # clamp(10 x 15000) = clamp(150000) -> capped at the 100000 ceiling.
    assert delivery["liability_cap_cents"] == 100000
    assert delivery["delivered_to_agent_id"] == "agent_1"
    assert get_order(ctx["order"]["id"])["status"] == "DELIVERED"

    ack = validate_success(api.acknowledge_delivery(delivery["id"], AGENT), 200)
    assert ack["status"] == "ACKNOWLEDGED"


def test_patch_association_swaps_estoppel_draft(api):
    """PRD 3.7: "Changing the `association_id` cancels every `DRAFT`, `ORDERED`,
    or `OVERDUE` estoppel of the old association and spawns a fresh `DRAFT`
    estoppel for the new one; the change is rejected with
    `ERR_INVALID_STATE_TRANSITION` when any estoppel has already been `RECEIVED`"
    PRD 2.3: "Items are always returned in `created_at` ascending order; because
    the logical clock can assign identical timestamps to several resources, ties
    are broken by insertion order — the order in which the server accepted the
    creates."

    Design: Corner/state_machines/patch_association_swaps_estoppel_draft
    """
    ctx = setup_config_a(departments=UTILITY_ONLY_DEPARTMENTS, with_association=True)
    first = ctx["association"]
    second = create_association(
        ctx["jurisdiction"]["id"],
        name="Palm HOA",
        management_company="Palm Mgmt",
        estoppel_fee_cents=9000,
        estoppel_validity_days=45,
    )
    order = create_search_order("P-F2", association_id=first["id"])
    identify_order(order["id"], ctx["jurisdiction"]["id"])
    old_estoppel = list_order_estoppels(order["id"])[0]
    current = get_order(order["id"], AGENT)

    response = api.patch_search_order(
        order["id"],
        patch_order_payload(current["version"], association_id=second["id"]),
        AGENT,
    )
    patched = validate_success(response, 200)
    assert patched["association_id"] == second["id"]

    estoppels = list_order_estoppels(order["id"])
    assert len(estoppels) == 2, f"Expected old + new estoppel, got {len(estoppels)}"
    assert estoppels[0]["id"] == old_estoppel["id"]
    assert estoppels[0]["status"] == "CANCELLED"
    assert estoppels[0]["association_id"] == first["id"]
    assert estoppels[1]["status"] == "DRAFT"
    assert estoppels[1]["association_id"] == second["id"]
