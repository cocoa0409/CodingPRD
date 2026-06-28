"""Custody/billing state machines, cross-entity dependencies, and cascades.

Covers the parallel-axis, cooler-cycle, transitive-cascade, and cross-entity
state-dependency difficulty instances plus the state-machine corner instances.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    validate_paginated, ApiErrorId,
    setup_private_case_cremated, setup_private_case_invoiced,
    setup_received_case_with_cooler, setup_case_ready_for_return,
    setup_communal_batch_fired, stage_load_fire_private,
    create_owner, create_retort, create_case, create_batch,
    drive_case_to_received, store_case, set_clock, get_case_version,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]


def _case(case_id):
    return get_success_data(api_client.get_case(case_id, ADMIN))


# =========================================================================== #
# non_linear_state_machine
# =========================================================================== #
def test_case_custody_cremated_while_billing_still_billable(api):
    """PRD §3.3: "as a system side effect the case's billing moves from `NOT_BILLABLE` to
    `BILLABLE`, recognizing the case as eligible for invoicing."
    PRD §2.4 / §3.2: "The two case axes — `custody_status` and `billing_status` — evolve
    independently."
    PRD §3.10: "Issuing the invoice moves the case's billing from `BILLABLE` to
    `INVOICED`"

    Design: Difficulty/non_linear_state_machine/nonlinear_case_parallel_custody_x_billing
    """
    ctx = setup_private_case_cremated(clock="2026-03-08T00:00:00Z", weight_lbs=30,
                                      bill_to="OWNER")
    case = _case(ctx["case"]["id"])
    assert case["custody_status"] == "CREMATED"
    assert case["billing_status"] == "BILLABLE", "billing not yet INVOICED at cremation"


def test_cooler_cycles_full_then_back_to_available_on_stage_out(api):
    """PRD §3.1: "the status therefore cycles `AVAILABLE` → `FULL` as a body enters that
    brings occupancy up to capacity, and back `FULL` → `AVAILABLE` as a slot frees."
    PRD §3.5: "If the case was `IN_COOLER` at the time it is staged, the system also clears
    its `cooler_id`, decrements the holding cooler's `occupied_count`, recomputes that
    cooler's `available_capacity` and `status` (flipping `FULL` → `AVAILABLE` when a slot
    frees)"

    Design: Difficulty/non_linear_state_machine/nonlinear_cooler_cyclic_full_to_available
    """
    ctx = setup_received_case_with_cooler(clock="2026-03-09T00:00:00Z", capacity=1)
    cooler_id = ctx["cooler"]["id"]
    case_id = ctx["case"]["id"]
    store_case(case_id, cooler_id)
    full = get_success_data(api_client.get_cooler(cooler_id, ADMIN))
    assert full["status"] == "FULL", "cap-1 cooler goes FULL on store"

    batch = create_batch(ctx["retort"]["id"], "PRIVATE",
                         "2026-03-09T08:00:00Z", "2026-03-09T10:00:00Z")
    get_success_data(api_client.assign_case(batch["id"], case_id, OPERATOR))

    cooler = get_success_data(api_client.get_cooler(cooler_id, ADMIN))
    assert cooler["status"] == "AVAILABLE", "slot frees when case is staged out"
    assert cooler["occupied_count"] == 0
    assert _case(case_id)["cooler_id"] is None


# =========================================================================== #
# transitive_cascade
# =========================================================================== #
def test_invoice_pay_cascades_to_case_settled_and_clinic_balance(api):
    """PRD §3.11: "Payment cascades the case's billing from `INVOICED` to `SETTLED`. When
    the paid invoice is account-billed, the clinic's `outstanding_balance_cents` is
    decreased by the invoice's `total_cents` and its `account_status` is recomputed
    (returning from `DELINQUENT` to `CURRENT` if the balance falls to or below the credit
    limit)."

    Design: Difficulty/transitive_cascade/cascade_invoice_pay_to_case_to_clinic_depth3
    """
    ctx = setup_private_case_invoiced(clock="2026-04-02T00:00:00Z", weight_lbs=50,
                                      bill_to="CLINIC_ACCOUNT")
    inv_id = ctx["invoice"]["id"]
    clinic_id = ctx["clinic_id"]

    invoice = validate_success(api_client.pay_invoice(inv_id, ADMIN))
    assert invoice["status"] == "PAID"
    assert _case(ctx["case"]["id"])["billing_status"] == "SETTLED"
    clinic = get_success_data(api_client.get_clinic(clinic_id, ADMIN))
    assert clinic["outstanding_balance_cents"] == 0
    assert clinic["account_status"] == "CURRENT"


def test_batch_complete_cascades_case_cremated_and_issues_certificate(api):
    """PRD §3.6: "Completion cascades into every member case that is in the `STAGED`
    custody state, driving each from `STAGED` to `CREMATED`: for each such case the system
    appends a `CREMATED` custody event (custodian being the operator) and issues a
    certificate record in the `ISSUED` status bearing the next sequential
    `certificate_number`."

    Design: Difficulty/transitive_cascade/cascade_batch_complete_to_case_to_certificate_depth2
    """
    set_clock("2026-03-10T00:00:00Z")
    retort = create_retort(max_load_lbs=300)
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=40,
                       bill_to="OWNER", pickup_kind="HOME")
    drive_case_to_received(case["id"])
    batch = stage_load_fire_private(case["id"], retort["id"],
                                    "2026-03-10T08:00:00Z", "2026-03-10T10:00:00Z")
    get_success_data(api_client.complete_batch(batch, OPERATOR))

    assert _case(case["id"])["custody_status"] == "CREMATED"
    certs, _ = validate_paginated(api_client.list_certificates(case["id"], OPERATOR))
    assert len(certs) >= 1
    assert certs[0]["status"] == "ISSUED"


# =========================================================================== #
# cross_entity_state_dependency
# =========================================================================== #
def test_staged_case_stays_staged_while_batch_firing(api):
    """PRD §3.6: "Completing the firing moves the batch from `FIRING` to `COMPLETED`.
    Completion cascades into every member case that is in the `STAGED` custody state,
    driving each from `STAGED` to `CREMATED`"

    Design: Difficulty/cross_entity_state_dependency/cross_case_staged_requires_batch_completed
    """
    set_clock("2026-03-14T00:00:00Z")
    retort = create_retort(max_load_lbs=300)
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=30,
                       bill_to="OWNER", pickup_kind="HOME")
    drive_case_to_received(case["id"])
    batch_id = stage_load_fire_private(case["id"], retort["id"],
                                       "2026-03-14T08:00:00Z", "2026-03-14T10:00:00Z")
    # Batch is FIRING (not completed) — case must remain STAGED.
    assert _case(case["id"])["custody_status"] == "STAGED"
    assert get_success_data(api_client.get_batch(batch_id, ADMIN))["status"] == "FIRING"


def test_return_route_dispatch_requires_case_ready_for_return(api):
    """PRD §3.8: "The operator dispatches a planned route, moving it `PLANNED` →
    `DISPATCHED`, which requires both that the route be `PLANNED` and that its owning case
    be in `READY_FOR_RETURN`."

    Design: Difficulty/cross_entity_state_dependency/cross_returnroute_dispatch_requires_case_ready
    """
    ctx = setup_case_ready_for_return(clock="2026-03-15T00:00:00Z",
                                      return_method="COURIER_TO_HOME",
                                      destination_label="4 St")
    route = validate_success(api_client.dispatch_return_route(ctx["route"]["id"], OPERATOR))
    assert route["status"] == "DISPATCHED"
    assert _case(ctx["case"]["id"])["custody_status"] == "READY_FOR_RETURN"


# =========================================================================== #
# Corner: state_machines
# =========================================================================== #
def test_case_new_starts_intake_pending_not_billable(api):
    """PRD §3.2: "On creation the case begins in custody `INTAKE_PENDING` and billing
    `NOT_BILLABLE`"

    Design: Corner/state_machines/sm_initial_state_case_intake_pending
    """
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=40,
                       bill_to="OWNER", pickup_kind="HOME")
    fetched = _case(case["id"])
    assert fetched["custody_status"] == "INTAKE_PENDING"
    assert fetched["billing_status"] == "NOT_BILLABLE"


def test_receive_from_intake_pending_invalid_state(api):
    """PRD §3.3: "Receiving the body at the facility moves the case from `IN_TRANSIT` to
    `RECEIVED`."
    PRD §3.8: "Any custody transition attempted from a state that does not permit it is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/sm_receive_from_intake_pending_invalid_state
    """
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=40,
                       bill_to="OWNER", pickup_kind="HOME")
    validate_error(api_client.receive_case(case["id"], OPERATOR),
                   ApiErrorId.ERR_INVALID_STATE.value)
    assert _case(case["id"])["custody_status"] == "INTAKE_PENDING"


def test_cancel_returned_case_terminal_lockdown(api):
    """PRD §3.13: "Cancellation is permitted only while the case is in `INTAKE_PENDING`,
    `IN_TRANSIT`, `RECEIVED`, `IN_COOLER`, or `STAGED` ... An attempt to cancel a case
    outside these custody states is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/sm_cancel_after_returned_terminal_lockdown
    """
    from test_helpers import setup_case_returned
    ctx = setup_case_returned(clock="2026-05-01T00:00:00Z")
    case_id = ctx["case"]["id"]
    assert _case(case_id)["custody_status"] == "RETURNED"
    validate_error(api_client.cancel_case(case_id, OPERATOR),
                   ApiErrorId.ERR_INVALID_STATE.value)
    assert _case(case_id)["custody_status"] == "RETURNED"


def test_load_batch_twice_second_call_invalid_state(api):
    """PRD §3.6: "First the batch is loaded, moving it from `OPEN` to `LOADED`. Loading
    requires that the batch be `OPEN`"
    PRD §3.8: "Any custody transition attempted from a state that does not permit it is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/sm_load_batch_twice_idempotency_rejected
    """
    set_clock("2026-05-02T00:00:00Z")
    retort = create_retort(max_load_lbs=300)
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=30,
                       bill_to="OWNER", pickup_kind="HOME")
    drive_case_to_received(case["id"])
    batch = create_batch(retort["id"], "PRIVATE",
                         "2026-05-02T08:00:00Z", "2026-05-02T10:00:00Z")
    get_success_data(api_client.assign_case(batch["id"], case["id"], OPERATOR))
    get_success_data(api_client.load_batch(batch["id"], OPERATOR))

    validate_error(api_client.load_batch(batch["id"], OPERATOR),
                   ApiErrorId.ERR_INVALID_STATE.value)
    assert get_success_data(api_client.get_batch(batch["id"], ADMIN))["status"] == "LOADED"


def test_private_batch_second_assign_rejected(api):
    """PRD §3.5: "A case whose service type differs from the batch's, or an attempt to add
    a second member to a `PRIVATE` batch that already holds one, is rejected with
    `ERR_SERVICE_TYPE_MISMATCH` (HTTP 409)."

    Design: Corner/state_machines/sm_private_batch_second_assign_rejected
    """
    set_clock("2026-05-04T00:00:00Z")
    retort = create_retort(max_load_lbs=400)
    owner = create_owner()
    p1 = create_case(owner["id"], service_type="PRIVATE", weight_lbs=30,
                     bill_to="OWNER", pickup_kind="HOME")
    drive_case_to_received(p1["id"])
    p2 = create_case(owner["id"], service_type="PRIVATE", weight_lbs=30,
                     bill_to="OWNER", pickup_kind="HOME")
    drive_case_to_received(p2["id"])
    batch = create_batch(retort["id"], "PRIVATE",
                         "2026-05-04T08:00:00Z", "2026-05-04T10:00:00Z")
    get_success_data(api_client.assign_case(batch["id"], p1["id"], OPERATOR))

    validate_error(api_client.assign_case(batch["id"], p2["id"], OPERATOR),
                   ApiErrorId.ERR_SERVICE_TYPE_MISMATCH.value)
    assert _case(p2["id"])["custody_status"] == "RECEIVED"


def test_communal_reconcile_disposes_member_and_closes_chain(api):
    """PRD §3.7: "For a `COMMUNAL` batch, reconciliation is the disposition point: every
    member case still in `CREMATED` receives a `DISPOSED_COMMUNAL` custody event and has
    its `custody_chain_open` flag set to false, closing its chain since communal remains
    are pooled and not returned."

    Design: Corner/state_machines/sm_communal_reconcile_disposes_members
    """
    ctx = setup_communal_batch_fired("2026-05-05T00:00:00Z", [10],
                                     scheduled_start="2026-05-05T08:00:00Z",
                                     scheduled_end="2026-05-05T10:00:00Z")
    batch_id = ctx["batch_id"]
    case_id = ctx["case_ids"][0]
    get_success_data(api_client.complete_batch(batch_id, OPERATOR))
    validate_success(api_client.reconcile_batch(batch_id, ADMIN))

    assert get_success_data(api_client.get_batch(batch_id, ADMIN))["status"] == "RECONCILED"
    assert _case(case_id)["custody_chain_open"] is False


def test_keepsake_cancel_after_invoice_line_item_locked(api):
    """PRD §3.12: "A keepsake order may be cancelled from `ORDERED` or `IN_PRODUCTION`, but
    only while the case has no issued invoice; cancelling a priced line item after the case
    has been invoiced is rejected with `ERR_LINE_ITEM_LOCKED` (HTTP 409)."

    Design: Corner/state_machines/sm_keepsake_cancel_after_invoice_locked
    """
    set_clock("2026-05-03T00:00:00Z")
    retort = create_retort(max_load_lbs=300)
    owner = create_owner()
    case = create_case(owner["id"], service_type="PRIVATE", weight_lbs=30,
                       bill_to="OWNER", pickup_kind="HOME")
    keepsake = get_success_data(api_client.create_keepsake(case["id"], "PAW_PRINT", OPERATOR))
    drive_case_to_received(case["id"])
    batch = stage_load_fire_private(case["id"], retort["id"],
                                    "2026-05-03T08:00:00Z", "2026-05-03T10:00:00Z")
    get_success_data(api_client.complete_batch(batch, OPERATOR))
    version = get_case_version(case["id"])
    get_success_data(api_client.create_invoice(case["id"], version, ADMIN))

    validate_error(api_client.patch_keepsake(keepsake["id"], "CANCELLED", OPERATOR),
                   ApiErrorId.ERR_LINE_ITEM_LOCKED.value)
    keep, _ = validate_paginated(api_client.list_keepsakes(case["id"], ADMIN))
    assert keep[0]["status"] == "ORDERED"
