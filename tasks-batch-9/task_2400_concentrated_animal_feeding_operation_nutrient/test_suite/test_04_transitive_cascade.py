"""Single writes whose effects travel several entities deep: a freeboard reading
and a notice of violation.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_client
from test_helpers.assertions import (
    assert_budget_ledger,
    assert_immutable_register,
    assert_posture,
    assert_quantity,
    assert_state,
)
from test_helpers.fixtures import (
    conduct_inspection,
    file_storage_inspection,
    initiate_transfer,
    schedule_inspection,
    setup_ready_operation,
)
from test_helpers.test_users import REVIEWER_HEADERS


def _freeboard_deficit_filed():
    """A ready operation whose lagoon has just been measured 6 inches short of
    its required freeboard."""
    ctx = setup_ready_operation()
    ctx["storage_inspection"] = file_storage_inspection(
        ctx["operation"]["id"],
        ctx["storage"]["id"],
        ctx["operator_headers"],
        inspected_on="2026-07-25T00:00:00Z",
        inspector_name="R. Vance",
        measured_freeboard_in=18,
        visual_condition="NORMAL",
    )
    return ctx


def _nov_ready_operation():
    """A ready operation with an outstanding 200,000-gallon transfer and an
    inspection conducted with two deficiencies."""
    ctx = setup_ready_operation(with_hauler=True, hauler={"license_number": "HL-4417"})
    ctx["transfer"] = initiate_transfer(
        ctx["operation"]["id"],
        ctx["storage"]["id"],
        ctx["hauler"]["id"],
        ctx["operator_headers"],
        transferred_on="2026-07-28T00:00:00Z",
        gallons_transferred=200000,
    )
    inspection = schedule_inspection(
        ctx["operation"]["id"], ctx["permit"]["id"], REVIEWER_HEADERS
    )
    ctx["inspection"] = conduct_inspection(
        inspection["id"],
        2,
        REVIEWER_HEADERS,
        deficiency_categories=["RECORDKEEPING", "TRANSFER_DOCUMENTATION"],
    )
    return ctx


def test_freeboard_reading_reconciles_the_volume_balance_and_alerts_the_structure():
    """The measured freeboard is converted back to a volume, the reconciliation
    term absorbs the difference, and the structure moves to FREEBOARD_ALERT.

    PRD: "Liquid depth is `total_depth_in` less `measured_freeboard_in`; `measured_volume_gallons` is `surface_area_sqft` multiplied by that liquid depth divided by 12, multiplied by 7.4805, rounded half up to 2 decimal places."
    PRD: "The reconciliation term is then rewritten: `precipitation_adjustment_gallons` becomes `measured_volume_gallons` less `cumulative_intake_gallons` plus `cumulative_outflow_gallons`, rounded half up to 2 decimal places, which is precisely the value that makes the volume-balance invariant exact against what the inspector measured."
    PRD: "Otherwise, when there is a freeboard deficit at all, meaning `freeboard_deficit_in` is greater than 0 while `measured_freeboard_in` remains above 6 inches, a structure in `IN_SERVICE` moves to `FREEBOARD_ALERT` and the operation's posture is recomputed to `RESTRICTED`."

    Design: Difficulty/transitive_cascade/freeboard_alert_cascades_to_plan_revision_and_budget_lock
    """
    ctx = _freeboard_deficit_filed()
    record = ctx["storage_inspection"]

    assert_immutable_register(record, "storage inspection")
    assert_quantity(record["measured_volume_gallons"], 4712715.00, "measured_volume_gallons")
    assert_quantity(record["freeboard_deficit_in"], 6.00, "freeboard_deficit_in")
    assert record["alert_raised"] is True, (
        "a freeboard deficit raises the alert flag"
    )

    storage = validate_success(
        api_client.get_manure_storage(ctx["storage"]["id"], ctx["operator_headers"]),
        200,
    )
    assert_state(storage, "storage_status", "FREEBOARD_ALERT")
    assert_quantity(
        storage["precipitation_adjustment_gallons"],
        3712715.00,
        "precipitation_adjustment_gallons",
    )
    assert_quantity(storage["current_volume_gallons"], 4712715.00, "current_volume_gallons")
    assert storage["days_of_storage_available"] == 0, (
        "a structure with no headroom left reports zero days of storage, got "
        f"{storage['days_of_storage_available']}"
    )
    assert storage["last_inspected_on"].startswith("2026-07-25"), (
        f"last_inspected_on: expected 25 July 2026, got {storage['last_inspected_on']}"
    )


def test_freeboard_alert_revises_the_approved_plan_and_locks_its_budget_ledger():
    """The restricted posture drives the approved plan to REVISION_REQUIRED and
    locks its budget without touching any of the three ledger figures, and it
    does so without writing the permit's compliance dimension.

    PRD: "Every nutrient management plan of the operation whose `plan_status` is `APPROVED` transitions `APPROVED → REVISION_REQUIRED`, which increments that plan's `revision_count` by 1 and locks every field nutrient budget belonging to it."
    PRD: "Locking a budget never disturbs any of the three values — a locked budget simply refuses new applications while preserving its history."
    PRD: "The compliance dimension cycles among `IN_GOOD_STANDING`, `NOTICE_ISSUED` and `CORRECTIVE_ACTION`, and is driven solely by inspection activity on the same operation, as described in §3.8."

    Design: Difficulty/transitive_cascade/freeboard_alert_cascades_to_plan_revision_and_budget_lock
    """
    ctx = _freeboard_deficit_filed()
    headers = ctx["operator_headers"]

    operation = validate_success(
        api_client.get_operation(ctx["operation"]["id"], headers), 200
    )
    assert_posture(operation, "RESTRICTED", findings=0)

    plan = validate_success(
        api_client.get_nutrient_plan(ctx["plan"]["id"], headers), 200
    )
    assert_state(plan, "plan_status", "REVISION_REQUIRED")
    assert plan["revision_count"] == 1, (
        f"revision_count: expected 1, got {plan['revision_count']}"
    )

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], headers), 200
    )
    assert_state(budget, "budget_status", "LOCKED")
    assert_budget_ledger(budget, applied=0.00, remaining=414396, total=414396)

    permit = validate_success(api_client.get_permit(ctx["permit"]["id"], headers), 200)
    assert_state(permit, "compliance_status", "IN_GOOD_STANDING")
    assert_state(permit, "coverage_status", "COVERED")


def test_notice_of_violation_puts_the_permit_on_notice_and_restricts_the_operation():
    """One notice of violation counts the finding, moves the permit's compliance
    dimension only, restricts the operation and revises its approved plan.

    PRD: "Issuance stamps `response_due_on` as `conducted_on` plus 30 days — so an inspection conducted at the start of 1 August 2026 and served with a notice is due a response by the start of 31 August 2026 — increments the operation's `open_finding_count`, and starts the compliance cascade."
    PRD: "Because a `compliance_status` of `NOTICE_ISSUED` is a restricting condition, the operation's `compliance_posture` is recomputed and becomes `RESTRICTED`."
    PRD: "That in turn drives every `APPROVED` plan of the operation to `REVISION_REQUIRED`, incrementing each plan's `revision_count` and locking every one of its field nutrient budgets."

    Design: Difficulty/transitive_cascade/nov_cascades_to_permit_notice_posture_and_transfer_suspension
    """
    ctx = _nov_ready_operation()
    headers = ctx["operator_headers"]

    inspection = validate_success(
        api_client.issue_nov(ctx["inspection"]["id"], REVIEWER_HEADERS), 200
    )
    assert_state(inspection, "inspection_status", "NOV_ISSUED")

    permit = validate_success(api_client.get_permit(ctx["permit"]["id"], headers), 200)
    assert_state(permit, "compliance_status", "NOTICE_ISSUED")
    assert_state(permit, "coverage_status", "COVERED")

    operation = validate_success(
        api_client.get_operation(ctx["operation"]["id"], headers), 200
    )
    assert_posture(operation, "RESTRICTED", findings=1)

    plan = validate_success(
        api_client.get_nutrient_plan(ctx["plan"]["id"], headers), 200
    )
    assert_state(plan, "plan_status", "REVISION_REQUIRED")
    assert plan["revision_count"] == 1, (
        f"revision_count: expected 1, got {plan['revision_count']}"
    )

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], headers), 200
    )
    assert_state(budget, "budget_status", "LOCKED")


def test_notice_of_violation_suspends_the_outstanding_transfer_and_frees_its_commitment():
    """The last hop of the chain releases the suspended transfer's committed
    volume, which visibly restores the structure's headroom while its contents
    and its outflow total stay exactly where they were.

    PRD: "The compliance cascade of §2.9 drives every `INITIATED` transfer of a restricted or suspended operation to `SUSPENDED`, taking them in ascending `created_at` order, and each suspension releases that transfer's `gallons_transferred` from the structure's `committed_outflow_gallons`, after which `available_capacity_gallons` and `days_of_storage_available` are recomputed — so a compliance event visibly frees storage headroom."
    PRD: "`recipient_p2o5_lbs` is `gallons_transferred` divided by 1,000, multiplied by the manure phosphate concentration for the group — 10 for dairy, 16 for beef, 28 for swine, 45 for layer — rounded half up to 2 decimal places."

    Design: Difficulty/transitive_cascade/nov_cascades_to_permit_notice_posture_and_transfer_suspension
    """
    ctx = _nov_ready_operation()
    headers = ctx["operator_headers"]

    validate_success(api_client.issue_nov(ctx["inspection"]["id"], REVIEWER_HEADERS), 200)

    transfer = validate_success(
        api_client.get_manure_transfer(ctx["transfer"]["id"], headers), 200
    )
    assert_state(transfer, "transfer_status", "SUSPENDED")
    assert_quantity(transfer["recipient_n_lbs"], 4800.00, "recipient_n_lbs")
    assert_quantity(transfer["recipient_p2o5_lbs"], 2000.00, "recipient_p2o5_lbs")

    storage = validate_success(
        api_client.get_manure_storage(ctx["storage"]["id"], headers), 200
    )
    assert_quantity(storage["committed_outflow_gallons"], 0.00, "committed_outflow_gallons")
    assert_quantity(
        storage["available_capacity_gallons"], 3488300.00, "available_capacity_gallons"
    )
    assert_quantity(storage["current_volume_gallons"], 1000000.00, "current_volume_gallons")
    assert_quantity(
        storage["cumulative_outflow_gallons"], 0.00, "cumulative_outflow_gallons"
    )
    assert_state(storage, "storage_status", "IN_SERVICE")
