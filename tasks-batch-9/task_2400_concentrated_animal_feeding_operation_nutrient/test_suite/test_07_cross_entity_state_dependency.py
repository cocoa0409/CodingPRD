"""Writes whose admissibility is decided by the state of a neighbouring entity —
a permit, a hauler licence — rather than by their own payload.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_budget_ledger,
    assert_null,
    assert_posture,
    assert_quantity,
    assert_state,
)
from test_helpers.factories import application_event_payload
from test_helpers.fixtures import (
    add_budget,
    certify_plan,
    cover_permit,
    create_plan,
    draft_permit,
    file_soil_test,
    initiate_transfer,
    issue_coverage,
    record_application,
    record_intake,
    register_field,
    register_hauler,
    register_operation,
    register_storage,
    set_clock,
    setup_ready_operation,
    submit_permit,
)
from test_helpers.test_users import (
    PLANNER_HEADERS,
    REVIEWER_HEADERS,
    make_hauler_headers,
    make_operator_headers,
)


def _two_haulers_and_two_transfers():
    """A covered operation with a million gallons stored, one hauler whose
    licence is about to lapse and one whose licence runs for years, each holding
    a transfer."""
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    storage = register_storage(operation_id, operator_headers)
    cover_permit(operation_id, operator_headers, REVIEWER_HEADERS)
    record_intake(operation_id, storage["id"], 1000000, operator_headers)

    hauler_a = register_hauler(
        business_name="Shortline Hauling",
        license_number="HL-1102",
        license_expires_on="2026-08-15T00:00:00Z",
    )
    hauler_b = register_hauler(
        business_name="Prairie Pumping LLC",
        license_number="HL-4417",
        license_expires_on="2027-12-31T00:00:00Z",
    )
    transfer_a = initiate_transfer(
        operation_id,
        storage["id"],
        hauler_a["id"],
        operator_headers,
        transferred_on="2026-07-28T00:00:00Z",
        gallons_transferred=200000,
    )
    set_clock("2026-09-01T00:00:00Z")
    transfer_b = initiate_transfer(
        operation_id,
        storage["id"],
        hauler_b["id"],
        operator_headers,
        transferred_on="2026-08-20T00:00:00Z",
        gallons_transferred=100000,
    )
    return {
        "operation": operation,
        "operator_headers": operator_headers,
        "storage": storage,
        "hauler_a": hauler_a,
        "hauler_b": hauler_b,
        "transfer_a": transfer_a,
        "transfer_b": transfer_b,
    }


def _plan_awaiting_coverage():
    """A drafted plan with one budget, filed under a permit that has not even
    been submitted yet."""
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    register_storage(operation_id, operator_headers)
    permit = draft_permit(operation_id, operator_headers)
    field = register_field(operation_id)
    soil_test = file_soil_test(field["id"])
    plan = create_plan(operation_id, permit["id"])
    budget = add_budget(plan["id"], field["id"], soil_test["id"])
    return {
        "operation": operation,
        "operator_headers": operator_headers,
        "permit": permit,
        "plan": plan,
        "budget": budget,
    }


def test_application_is_recorded_while_coverage_is_in_force():
    """With the permit COVERED the same application payload is accepted, and
    advancing the clock past the term expires the permit through the checkpoint.

    PRD: "When the logical clock is set to an instant at or after a permit's `expiration_on`, that permit moves to `EXPIRED` from either `COVERED` or `RENEWAL_PENDING` — an unfinished renewal does not extend coverage."
    PRD: "The count of permits moved this way is what the clock response reports as `permits_expired_count`."

    Design: Difficulty/cross_entity_state_dependency/application_event_depends_on_permit_coverage_state
    """
    ctx = setup_ready_operation()
    headers = ctx["operator_headers"]

    event = record_application(
        ctx["operation"]["id"],
        ctx["plan"]["id"],
        ctx["budget"]["id"],
        ctx["storage"]["id"],
        headers,
        applied_on="2026-07-20T00:00:00Z",
    )
    assert_state(event, "event_status", "RECORDED")
    assert_quantity(event["n_applied_lbs"], 4680.00, "n_applied_lbs")

    checkpoints = set_clock("2031-04-01T00:00:00Z")
    assert checkpoints["permits_expired_count"] == 1, (
        f"permits_expired_count: expected 1, got {checkpoints['permits_expired_count']}"
    )

    permit = validate_success(api_client.get_permit(ctx["permit"]["id"], headers), 200)
    assert_state(permit, "coverage_status", "EXPIRED")


def test_expired_coverage_blocks_the_application_even_though_the_plan_is_still_approved():
    """The plan and its budget are untouched by expiry, so the refusal has to
    come from the permit's coverage state.

    PRD: "Recording a land application and initiating a transfer both require that the operation's permit is not `EXPIRED`, refusing with `ERR_PERMIT_COVERAGE_EXPIRED`."
    PRD: "The operation's permit must not be `EXPIRED`, or the record is refused with `ERR_PERMIT_COVERAGE_EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/application_event_depends_on_permit_coverage_state
    """
    ctx = setup_ready_operation()
    headers = ctx["operator_headers"]
    record_application(
        ctx["operation"]["id"],
        ctx["plan"]["id"],
        ctx["budget"]["id"],
        ctx["storage"]["id"],
        headers,
        applied_on="2026-07-20T00:00:00Z",
    )
    set_clock("2031-04-01T00:00:00Z")

    response = api_client.create_application_event(
        application_event_payload(
            ctx["plan"]["id"],
            ctx["budget"]["id"],
            ctx["storage"]["id"],
            applied_on="2031-03-20T00:00:00Z",
            gallons_applied=100000,
            acres_treated=10,
        ),
        headers,
    )
    validate_error(response, ApiErrorId.ERR_PERMIT_COVERAGE_EXPIRED)
    assert response.status_code == 409, (
        f"expected HTTP 409, got {response.status_code}"
    )

    plan = validate_success(
        api_client.get_nutrient_plan(ctx["plan"]["id"], headers), 200
    )
    assert_state(plan, "plan_status", "APPROVED")

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], headers), 200
    )
    assert_state(budget, "budget_status", "ACTIVE")
    assert_budget_ledger(budget, applied=300000.00, remaining=114396, total=414396)

    operation = validate_success(
        api_client.get_operation(ctx["operation"]["id"], headers), 200
    )
    assert_posture(operation, "OPEN")


def test_a_hauler_whose_licence_lapsed_cannot_acknowledge_its_transfer():
    """The hauler's derived status flips on the clock alone, and the transfer it
    is holding cannot be acknowledged once it has.

    PRD: "A hauler's `hauler_status` is derived, not supplied: it is `ACTIVE` while the logical clock is at or before `license_expires_on` and `LAPSED` thereafter, and it is re-evaluated on every read and again whenever the logical clock is set — the clock response reports how many lapsed as `haulers_lapsed_count`."
    PRD: "The transfer is written with `transfer_status` of `INITIATED` and `recipient_ack_signed_at` null, and `gallons_transferred` is added to the source structure's `committed_outflow_gallons`, after which `available_capacity_gallons` and `days_of_storage_available` are recomputed."

    Design: Difficulty/cross_entity_state_dependency/transfer_acknowledge_depends_on_hauler_license_state
    """
    ctx = _two_haulers_and_two_transfers()

    hauler_a = validate_success(
        api_client.get_hauler(ctx["hauler_a"]["id"], ctx["operator_headers"]), 200
    )
    assert_state(hauler_a, "hauler_status", "LAPSED")

    response = api_client.acknowledge_manure_transfer(
        ctx["transfer_a"]["id"], make_hauler_headers(ctx["hauler_a"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_HAULER_LICENSE_LAPSED)
    assert response.status_code == 422, (
        f"expected HTTP 422, got {response.status_code}"
    )

    transfer = validate_success(
        api_client.get_manure_transfer(
            ctx["transfer_a"]["id"], ctx["operator_headers"]
        ),
        200,
    )
    assert_state(transfer, "transfer_status", "INITIATED")
    assert_null(transfer, "recipient_ack_signed_at")


def test_a_current_licence_lets_the_acknowledgement_move_the_volume():
    """The second hauler is still ACTIVE, so acknowledging its load turns the
    reservation into actual outflow while the lapsed hauler's commitment stays
    reserved.

    PRD: "Acknowledgement stamps `recipient_ack_signed_at` from the logical clock and moves the volume from reservation to fact: `gallons_transferred` is released from the structure's `committed_outflow_gallons` and added to its `cumulative_outflow_gallons`, after which `current_volume_gallons` and `available_capacity_gallons` are recomputed."
    PRD: "Committing rather than immediately debiting is what stops two pending loads from overselling the same tank."

    Design: Difficulty/cross_entity_state_dependency/transfer_acknowledge_depends_on_hauler_license_state
    """
    ctx = _two_haulers_and_two_transfers()

    hauler_b = validate_success(
        api_client.get_hauler(ctx["hauler_b"]["id"], ctx["operator_headers"]), 200
    )
    assert_state(hauler_b, "hauler_status", "ACTIVE")

    transfer = validate_success(
        api_client.acknowledge_manure_transfer(
            ctx["transfer_b"]["id"], make_hauler_headers(ctx["hauler_b"]["id"])
        ),
        200,
    )
    assert_state(transfer, "transfer_status", "ACKNOWLEDGED")
    assert transfer["recipient_ack_signed_at"].startswith("2026-09-01T00:00:00"), (
        f"recipient_ack_signed_at: expected 1 September 2026, "
        f"got {transfer['recipient_ack_signed_at']}"
    )

    storage = validate_success(
        api_client.get_manure_storage(ctx["storage"]["id"], ctx["operator_headers"]),
        200,
    )
    assert_quantity(
        storage["committed_outflow_gallons"], 200000.00, "committed_outflow_gallons"
    )
    assert_quantity(
        storage["cumulative_outflow_gallons"], 100000.00, "cumulative_outflow_gallons"
    )
    assert_quantity(storage["current_volume_gallons"], 900000.00, "current_volume_gallons")


def test_certification_is_refused_while_the_coverage_application_is_still_a_draft():
    """The plan itself is complete, but the permit it is filed under has not been
    granted, so certification cannot proceed.

    PRD: "Certifying a plan and conducting an inspection both require the referenced permit to be in `COVERED` or `RENEWAL_PENDING`, and refuse with `ERR_PERMIT_COVERAGE_REQUIRED` otherwise."
    PRD: "A freshly drafted application is born with `coverage_status` of `DRAFT_APPLICATION` and, on the independent compliance dimension, `compliance_status` of `IN_GOOD_STANDING`."

    Design: Difficulty/cross_entity_state_dependency/plan_certify_depends_on_permit_coverage_being_granted
    """
    ctx = _plan_awaiting_coverage()

    assert_state(ctx["permit"], "coverage_status", "DRAFT_APPLICATION")

    response = api_client.certify_nutrient_plan(ctx["plan"]["id"], PLANNER_HEADERS)
    validate_error(response, ApiErrorId.ERR_PERMIT_COVERAGE_REQUIRED)
    assert response.status_code == 409, (
        f"expected HTTP 409, got {response.status_code}"
    )

    plan = validate_success(
        api_client.get_nutrient_plan(ctx["plan"]["id"], ctx["operator_headers"]), 200
    )
    assert_state(plan, "plan_status", "DRAFT")
    assert_null(plan, "certified_at")


def test_granting_coverage_unblocks_certification_without_activating_the_budget():
    """Once coverage is issued the same certification succeeds, but certifying is
    not approving, so the budget stays locked.

    PRD: "Every budget is born with `budget_status` of `LOCKED`, and that is true even when it is filed against a plan that is already `APPROVED`."
    PRD: "Only plan approval activates budgets, so a budget added after approval remains `LOCKED` until the plan has been revised and approved again."

    Design: Difficulty/cross_entity_state_dependency/plan_certify_depends_on_permit_coverage_being_granted
    """
    ctx = _plan_awaiting_coverage()
    operation_id = ctx["operation"]["id"]

    submit_permit(operation_id, ctx["permit"]["id"], ctx["operator_headers"])
    permit = issue_coverage(ctx["permit"]["id"], REVIEWER_HEADERS)
    assert_state(permit, "coverage_status", "COVERED")
    assert permit["expiration_on"].startswith("2031-01-01"), (
        f"expiration_on: expected 1 January 2031, got {permit['expiration_on']}"
    )

    plan = certify_plan(ctx["plan"]["id"], PLANNER_HEADERS)
    assert_state(plan, "plan_status", "CERTIFIED")
    assert plan["certifying_planner_user_id"] == "planner-1", (
        f"certifying_planner_user_id: expected planner-1, "
        f"got {plan['certifying_planner_user_id']}"
    )

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], ctx["operator_headers"]), 200
    )
    assert_state(budget, "budget_status", "LOCKED")
