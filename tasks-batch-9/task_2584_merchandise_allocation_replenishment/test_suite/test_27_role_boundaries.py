"""Role-boundary corners for the merchandise allocation and replenishment API.

Three boundaries are probed here: the exclusive operations each role owns and the
header check that outranks the role check; the store operator's confinement to its
own store, separated from the operations closed to it outright; and segregation of
duties, which binds whoever authored a decision rather than whoever executes it.
"""
import pytest

from test_helpers import (
    ALLOCATOR_USER_ID,
    ApiErrorId,
    api_client,
    build_user_headers,
    create_item_payload,
    create_program_payload,
    create_proposed_run,
    create_receipt,
    create_receipt_payload,
    create_run,
    create_snapshot_payload,
    create_transfer_payload,
    current_position_version,
    line_for_store,
    make_allocation_manager_headers,
    make_allocator_headers,
    make_planning_admin_headers,
    make_store_operator_headers,
    propose_transfer,
    reset_clock,
    setup_executed_consolidation,
    setup_network,
    setup_proposed_transfer,
    setup_rebalance_network,
    size_map,
    validate_error,
    validate_success,
)

PLANNER = make_planning_admin_headers()
ALLOCATOR = make_allocator_headers()
MANAGER = make_allocation_manager_headers()

# A headers dict carrying neither X-User-ID nor X-User-Role.
NO_IDENTITY_HEADERS = {"Content-Type": "application/json"}

RBAC_STORE_SPECS = [
    {
        "store_code": "0101",
        "grade": "A",
        "grade_index_bp": 13000,
        "cluster_code": "URBAN",
        "freight_flat_usd": 41.00,
        "historical_sell_through_bp": 6500,
    },
    {
        "store_code": "0102",
        "grade": "B",
        "grade_index_bp": 10000,
        "cluster_code": "URBAN",
        "freight_flat_usd": 38.00,
        "historical_sell_through_bp": 5800,
    },
]
RBAC_FIXTURE_SPECS = {
    "0101": {
        "fixture_count": 4,
        "facings_per_fixture": 3,
        "units_per_facing": 4,
        "presentation_min_units": 6,
    },
    "0102": {
        "fixture_count": 2,
        "facings_per_fixture": 3,
        "units_per_facing": 4,
        "presentation_min_units": 2,
    },
}
RBAC_POSITION_SPECS = {
    "0101": {
        "on_hand_units": 6,
        "size_on_hand": [
            {"size_code": "M", "units": 4},
            {"size_code": "L", "units": 2},
        ],
        "min_units": 12,
        "max_units": 48,
        "weekly_forecast_units": 9,
        "trailing_4wk_sales_units": 30,
    },
    "0102": {
        "on_hand_units": 30,
        "size_on_hand": [
            {"size_code": "S", "units": 8},
            {"size_code": "M", "units": 10},
            {"size_code": "L", "units": 8},
            {"size_code": "XL", "units": 4},
        ],
        "min_units": 8,
        "max_units": 24,
        "weekly_forecast_units": 5,
        "trailing_4wk_sales_units": 16,
    },
}
RECEIPT_THIRTY = {"S": 6, "M": 11, "L": 9, "XL": 4}


def _rbac_network():
    """Two ACTIVE URBAN stores with shelf plans and positions for one SEASONAL SKU,
    where 0101 needs 30 units for its four-week cover and 0102 needs none."""
    reset_clock()
    return setup_network(
        store_specs=RBAC_STORE_SPECS,
        fixture_specs=RBAC_FIXTURE_SPECS,
        position_specs=RBAC_POSITION_SPECS,
    )


@pytest.fixture
def role_matrix_scenario():
    """The two-store network plus a 30-unit receipt and one PROPOSED spread, so
    every role-exclusive operation in the workflow has a real subject to aim at."""
    scenario = _rbac_network()
    scenario["receipt"] = create_receipt(
        scenario["program"]["id"],
        scenario["item"]["id"],
        reference="ASN-R101",
        units_received=30,
        size_received=size_map(RECEIPT_THIRTY),
    )
    scenario["run"] = create_proposed_run(scenario["receipt"]["id"])
    scenario["line"] = line_for_store(
        scenario["run"]["id"], scenario["stores"]["0101"]["id"]
    )
    return scenario


def _allocator_registers_a_program(api, s):
    return api.create_program(create_program_payload(name="FA26 Intruder"), ALLOCATOR)


def _manager_creates_a_sku(api, s):
    return api.create_item(
        create_item_payload(
            s["program"]["id"],
            s["size_profile"]["id"],
            sku_code="SKU-3001",
            style_code="ST-300",
        ),
        MANAGER,
    )


def _manager_drives_a_store_lifecycle(api, s):
    return api.set_store_status(
        s["stores"]["0101"]["id"], {"target_status": "REMODEL"}, MANAGER
    )


def _manager_opens_an_allocation_run(api, s):
    return api.create_allocation_run(
        s["receipt"]["id"],
        {
            "method": "DEMAND_DRIVEN",
            "need_basis": "FORWARD_LOOKING",
            "expected_receipt_version": s["receipt"]["version"],
        },
        MANAGER,
    )


def _planner_proposes_a_spread(api, s):
    return api.propose_run(s["run"]["id"], PLANNER)


def _allocator_commits_a_spread(api, s):
    return api.commit_run(s["run"]["id"], ALLOCATOR)


def _planner_locks_the_program(api, s):
    return api.lock_program(s["program"]["id"], PLANNER, {"reason": "month-end freeze"})


def _manager_confirms_a_store_receipt(api, s):
    return api.confirm_line_receipt(s["line"]["id"], MANAGER)


def _store_operator_proposes_a_transfer(api, s):
    return api.create_transfer_recommendation(
        create_transfer_payload(
            s["program"]["id"],
            s["stores"]["0102"]["id"],
            s["stores"]["0101"]["id"],
            s["item"]["id"],
            6,
            current_position_version(s["positions"]["0102"]["id"]),
        ),
        make_store_operator_headers(s["stores"]["0101"]["id"]),
    )


def _manager_drives_the_logical_clock(api, s):
    return api.set_current_utc({"current_utc": "2026-08-05T00:00:00Z"}, MANAGER)


def _store_operator_sweeps_transfer_expiry(api, s):
    return api.run_transfer_expiry(
        {"program_id": s["program"]["id"]},
        make_store_operator_headers(s["stores"]["0101"]["id"]),
    )


ROLE_PROBES = [
    ("allocator_cannot_register_a_program", _allocator_registers_a_program),
    ("manager_cannot_create_a_sku", _manager_creates_a_sku),
    ("manager_cannot_drive_a_store_lifecycle", _manager_drives_a_store_lifecycle),
    ("manager_cannot_open_an_allocation_run", _manager_opens_an_allocation_run),
    ("planner_cannot_propose_a_spread", _planner_proposes_a_spread),
    ("allocator_cannot_commit_a_spread", _allocator_commits_a_spread),
    ("planner_cannot_lock_the_program", _planner_locks_the_program),
    ("manager_cannot_confirm_a_store_receipt", _manager_confirms_a_store_receipt),
    ("store_operator_cannot_propose_a_transfer", _store_operator_proposes_a_transfer),
    ("manager_cannot_drive_the_logical_clock", _manager_drives_the_logical_clock),
    ("store_operator_cannot_sweep_transfer_expiry", _store_operator_sweeps_transfer_expiry),
]


PARTIAL_IDENTITY_HEADERS = [
    ("no_identity_headers_at_all", dict(NO_IDENTITY_HEADERS)),
    (
        "only_the_operator_id_is_supplied",
        {"Content-Type": "application/json", "X-User-ID": MANAGER["X-User-ID"]},
    ),
    (
        "only_the_role_is_supplied",
        {"Content-Type": "application/json", "X-User-Role": "AllocationManager"},
    ),
]


@pytest.mark.parametrize(
    "probe", [p[1] for p in ROLE_PROBES], ids=[p[0] for p in ROLE_PROBES]
)
def test_role_exclusive_operations_refuse_every_other_role(
    api, role_matrix_scenario, probe
):
    """Each of the eleven probes carries well-formed headers for a real role that
    the endpoint does not authorise, so each must be refused on the role rung.

    PRD: "When both headers are well formed but the named role is not one of the
    roles authorised for the endpoint (see the Authorized Role(s) column in §4),
    the rejection is `ERR_FORBIDDEN_ROLE` with HTTP 403."

    PRD: "A `StoreOperator` has no other capabilities at all: list endpoints,
    program administration, allocation decisions and transfer decisions are all
    closed to it, and attempting them yields `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/each_role_cannot_reach_another_roles_exclusive_operation_and_unauthenticated_outranks_forbidden
    """
    response = probe(api, role_matrix_scenario)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)


@pytest.mark.parametrize(
    "headers",
    [h[1] for h in PARTIAL_IDENTITY_HEADERS],
    ids=[h[0] for h in PARTIAL_IDENTITY_HEADERS],
)
def test_a_missing_identity_header_outranks_the_role_check(
    api, role_matrix_scenario, headers
):
    """Locking the program is closed to every role but `AllocationManager`, yet an
    incomplete identity is reported before the role is ever considered.

    PRD: "If either header is absent, or if `X-User-Role` is not one of the four
    role names below, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP
    401 before anything else is examined."

    PRD: "later checks are never reached, so a request that violates three rules
    always reports the lowest-numbered one"

    Design: Corner/rbac/each_role_cannot_reach_another_roles_exclusive_operation_and_unauthenticated_outranks_forbidden
    """
    response = api.lock_program(
        role_matrix_scenario["program"]["id"], headers, {"reason": "month-end freeze"}
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


@pytest.mark.parametrize("role_name", ["Auditor", "allocationmanager", "ALLOCATOR", ""])
def test_an_unrecognised_role_name_is_unauthenticated_rather_than_forbidden(
    api, role_matrix_scenario, role_name
):
    """A stranger role and a miscapitalised one alike fail the header rung, not the
    authorisation rung.

    PRD: "The service recognises exactly four roles, spelled exactly as follows."

    PRD: "If either header is absent, or if `X-User-Role` is not one of the four
    role names below, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP
    401 before anything else is examined."

    PRD: "1. Headers present and `X-User-Role` recognised — `ERR_UNAUTHENTICATED`, 401."

    Design: Corner/rbac/each_role_cannot_reach_another_roles_exclusive_operation_and_unauthenticated_outranks_forbidden
    """
    headers = build_user_headers(MANAGER["X-User-ID"], role_name)
    response = api.lock_program(
        role_matrix_scenario["program"]["id"], headers, {"reason": "month-end freeze"}
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_a_refused_role_probe_leaves_the_season_exactly_as_it_was(
    api, role_matrix_scenario
):
    """The role rung sits second in the ladder, so a wrong-role request never reaches
    the work it asked for: the store keeps its status, the program keeps its lock
    fields null, and the spread stays `PROPOSED`.

    PRD: "2. Role authorised for the endpoint — `ERR_FORBIDDEN_ROLE`, 403."

    PRD: "later checks are never reached, so a request that violates three rules
    always reports the lowest-numbered one"

    Design: Corner/rbac/each_role_cannot_reach_another_roles_exclusive_operation_and_unauthenticated_outranks_forbidden
    """
    store = role_matrix_scenario["stores"]["0101"]
    program = role_matrix_scenario["program"]
    run = role_matrix_scenario["run"]

    validate_error(
        _manager_drives_a_store_lifecycle(api, role_matrix_scenario),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
    )
    validate_error(
        _planner_locks_the_program(api, role_matrix_scenario),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
    )
    validate_error(
        _allocator_commits_a_spread(api, role_matrix_scenario),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
    )

    after_store = validate_success(api.get_store(store["id"], PLANNER))
    assert after_store["status"] == "ACTIVE"
    assert after_store["version"] == store["version"]

    after_program = validate_success(api.get_program(program["id"], PLANNER))
    assert after_program["status"] == "ACTIVE"
    assert after_program["lock_reason"] is None
    assert after_program["locked_at"] is None

    after_run = validate_success(api.get_allocation_run(run["id"], ALLOCATOR))
    assert after_run["status"] == "PROPOSED"
    assert after_run["committed_by_user_id"] is None


def test_the_authorised_roles_perform_the_very_same_operations(
    api, role_matrix_scenario
):
    """Every operation refused above succeeds for the role §4 names, which is what
    makes the refusals a boundary rather than a blanket denial.

    PRD: "An `AllocationManager` may take the program `ACTIVE → LOCKED`, supplying a
    `reason` that is stored as `lock_reason` while `locked_at` records the current
    logical clock; the reverse transition `LOCKED → ACTIVE` clears both fields back
    to null."

    PRD: "Reading a single store requires that the store's own identifier equal
    `X-User-ID`."

    Design: Corner/rbac/each_role_cannot_reach_another_roles_exclusive_operation_and_unauthenticated_outranks_forbidden
    """
    store = role_matrix_scenario["stores"]["0101"]
    program = role_matrix_scenario["program"]
    run = role_matrix_scenario["run"]

    locked = validate_success(
        api.lock_program(program["id"], MANAGER, {"reason": "month-end freeze"})
    )
    assert locked["status"] == "LOCKED"
    assert locked["lock_reason"] == "month-end freeze"

    unlocked = validate_success(api.unlock_program(program["id"], MANAGER))
    assert unlocked["status"] == "ACTIVE"
    assert unlocked["lock_reason"] is None
    assert unlocked["locked_at"] is None

    committed = validate_success(api.commit_run(run["id"], MANAGER))
    assert committed["status"] == "COMMITTED"
    assert committed["committed_by_user_id"] == MANAGER["X-User-ID"]

    own = validate_success(
        api.get_store(store["id"], make_store_operator_headers(store["id"]))
    )
    assert own["id"] == store["id"]

    remodelled = validate_success(
        api.set_store_status(store["id"], {"target_status": "REMODEL"}, PLANNER)
    )
    assert remodelled["status"] == "REMODEL"


@pytest.fixture
def store_scope_scenario():
    """The two-store network carried far enough that all four store-scoped operations
    have a live subject: 0101 holds a `SHIPPED` allocation line and is the receiver of
    a `DISPATCHED` transfer from 0102."""
    scenario = _rbac_network()
    scenario["receipt"] = create_receipt(
        scenario["program"]["id"],
        scenario["item"]["id"],
        reference="ASN-R201",
        units_received=30,
        size_received=size_map(RECEIPT_THIRTY),
    )
    run = create_proposed_run(scenario["receipt"]["id"])
    validate_success(api_client.commit_run(run["id"], MANAGER))
    line = line_for_store(run["id"], scenario["stores"]["0101"]["id"])
    scenario["run"] = run
    scenario["line"] = validate_success(api_client.ship_line(line["id"], MANAGER))
    scenario["transfer"] = propose_transfer(scenario, "0102", "0101", 6)
    validate_success(api_client.approve_transfer(scenario["transfer"]["id"], MANAGER))
    scenario["transfer"] = validate_success(
        api_client.dispatch_transfer(scenario["transfer"]["id"], MANAGER)
    )
    return scenario


def _reads_another_stores_record(api, s):
    return api.get_store(
        s["stores"]["0102"]["id"],
        make_store_operator_headers(s["stores"]["0101"]["id"]),
    )


def _reads_another_stores_position(api, s):
    return api.get_store_position(
        s["positions"]["0102"]["id"],
        make_store_operator_headers(s["stores"]["0101"]["id"]),
    )


def _confirms_another_stores_line(api, s):
    return api.confirm_line_receipt(
        s["line"]["id"], make_store_operator_headers(s["stores"]["0102"]["id"])
    )


def _receives_another_stores_transfer(api, s):
    return api.receive_transfer(
        s["transfer"]["id"], make_store_operator_headers(s["stores"]["0102"]["id"])
    )


SCOPED_OPERATIONS = [
    ("reading_a_single_store", _reads_another_stores_record),
    ("reading_a_single_position", _reads_another_stores_position),
    ("confirming_receipt_of_a_line", _confirms_another_stores_line),
    ("receiving_a_dispatched_transfer", _receives_another_stores_transfer),
]


def _lists_stores(api, s):
    return api.list_stores(make_store_operator_headers(s["stores"]["0101"]["id"]))


def _lists_positions(api, s):
    return api.list_store_positions(
        make_store_operator_headers(s["stores"]["0101"]["id"])
    )


def _reads_one_allocation_line(api, s):
    return api.get_allocation_line(
        s["line"]["id"], make_store_operator_headers(s["stores"]["0101"]["id"])
    )


CLOSED_OPERATIONS = [
    ("listing_stores", _lists_stores),
    ("listing_store_positions", _lists_positions),
    ("reading_one_allocation_line", _reads_one_allocation_line),
]


@pytest.mark.parametrize(
    "operation",
    [o[1] for o in SCOPED_OPERATIONS],
    ids=[o[0] for o in SCOPED_OPERATIONS],
)
def test_a_store_operator_may_not_reach_across_to_another_store(
    api, store_scope_scenario, operation
):
    """All four scoped operations compare the resource's store-referencing field to
    `X-User-ID`, and every one of these probes acts on a store that is not the caller.

    PRD: "Four operations enforce that store scoping, and all four reject with
    `ERR_STORE_SCOPE_VIOLATION` and HTTP 403 when the comparison fails. Reading a
    single store requires that the store's own identifier equal `X-User-ID`. Reading
    a single position requires that the position's `store_id` equal `X-User-ID`.
    Confirming physical receipt of an allocation line requires that the line's
    `store_id` equal `X-User-ID`. Receiving a dispatched transfer requires that the
    recommendation's `to_store_id` equal `X-User-ID`."

    Design: Corner/rbac/store_operator_is_scoped_to_its_own_store_while_shared_writes_accept_both_planner_roles
    """
    response = operation(api, store_scope_scenario)
    validate_error(response, ApiErrorId.ERR_STORE_SCOPE_VIOLATION)


@pytest.mark.parametrize(
    "operation",
    [o[1] for o in CLOSED_OPERATIONS],
    ids=[o[0] for o in CLOSED_OPERATIONS],
)
def test_operations_closed_to_a_store_operator_report_the_role_refusal_instead(
    api, store_scope_scenario, operation
):
    """The list views and the single-line read are not scoped operations at all, so
    even the owning store is turned away one rung earlier, on the role check.

    PRD: "A `StoreOperator` has no other capabilities at all: list endpoints, program
    administration, allocation decisions and transfer decisions are all closed to it,
    and attempting them yields `ERR_FORBIDDEN_ROLE`."

    PRD: "3. `StoreOperator` acting within its own store, on the four scoped
    operations listed in §2.1 — `ERR_STORE_SCOPE_VIOLATION`, 403."

    Design: Corner/rbac/store_operator_is_scoped_to_its_own_store_while_shared_writes_accept_both_planner_roles
    """
    response = operation(api, store_scope_scenario)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_a_store_operator_reads_its_own_store_and_its_own_position(
    api, store_scope_scenario
):
    """The same two reads that were refused across the aisle succeed when the acting
    identity is the resource's own store.

    PRD: "Reading a single store requires that the store's own identifier equal
    `X-User-ID`."

    PRD: "Reading a single position requires that the position's `store_id` equal
    `X-User-ID`."

    Design: Corner/rbac/store_operator_is_scoped_to_its_own_store_while_shared_writes_accept_both_planner_roles
    """
    own_store = store_scope_scenario["stores"]["0101"]
    own_position = store_scope_scenario["positions"]["0101"]
    operator = make_store_operator_headers(own_store["id"])

    store = validate_success(api.get_store(own_store["id"], operator))
    assert store["id"] == own_store["id"]
    assert store["store_code"] == "0101"

    position = validate_success(api.get_store_position(own_position["id"], operator))
    assert position["id"] == own_position["id"]
    assert position["store_id"] == own_store["id"]


def test_the_owning_store_confirms_its_line_and_receives_its_transfer(
    api, store_scope_scenario
):
    """Both write-side scoped operations succeed for the store named on the resource,
    which is what the two refusals above are a boundary against.

    PRD: "A `StoreOperator` confirms physical receipt of a line, taking it `SHIPPED →
    RECEIVED`, and the acting `X-User-ID` must equal the line's `store_id` or the
    request is refused with `ERR_STORE_SCOPE_VIOLATION`."

    PRD: "A `StoreOperator` whose `X-User-ID` equals the recommendation's
    `to_store_id` — any other operator is refused with `ERR_STORE_SCOPE_VIOLATION` —
    takes the recommendation `DISPATCHED → RECEIVED`, which is terminal."

    Design: Corner/rbac/store_operator_is_scoped_to_its_own_store_while_shared_writes_accept_both_planner_roles
    """
    own_store = store_scope_scenario["stores"]["0101"]
    operator = make_store_operator_headers(own_store["id"])

    line = validate_success(
        api.confirm_line_receipt(store_scope_scenario["line"]["id"], operator)
    )
    assert line["fulfillment_status"] == "RECEIVED"
    assert line["store_id"] == own_store["id"]

    transfer = validate_success(
        api.receive_transfer(store_scope_scenario["transfer"]["id"], operator)
    )
    assert transfer["status"] == "RECEIVED"
    assert transfer["to_store_id"] == own_store["id"]


@pytest.fixture
def shared_write_scenario():
    """The bare two-store network, enough to exercise the writes that two roles share."""
    return _rbac_network()


def test_position_and_receipt_writes_accept_both_the_planner_and_the_allocator(
    api, shared_write_scenario
):
    """Position adjustment, receipt booking and receipt recount are shared, so neither
    of the two authorised roles may be turned away from them.

    PRD: "Position creation and adjustment, receipt booking and receipt recounts are
    shared between `PlanningAdmin` and `Allocator`; run cancellation, the assortment
    detection sweep and cluster snapshot creation are shared between `Allocator` and
    `AllocationManager`"

    Design: Corner/rbac/store_operator_is_scoped_to_its_own_store_while_shared_writes_accept_both_planner_roles
    """
    position = shared_write_scenario["positions"]["0101"]

    by_planner = validate_success(
        api.patch_store_position(position["id"], {"min_units": 10}, PLANNER)
    )
    assert by_planner["min_units"] == 10

    by_allocator = validate_success(
        api.patch_store_position(position["id"], {"weekly_forecast_units": 8}, ALLOCATOR)
    )
    assert by_allocator["weekly_forecast_units"] == 8

    booked = validate_success(
        api.create_receipt(
            create_receipt_payload(
                shared_write_scenario["program"]["id"],
                shared_write_scenario["item"]["id"],
                reference="ASN-R301",
                units_received=12,
                size_received=size_map({"M": 12}),
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    assert booked["units_received"] == 12

    recounted = validate_success(
        api.adjust_receipt(
            booked["id"],
            {
                "units_received": 10,
                "size_received": size_map({"M": 10}),
                "adjustment_reason": "DC recount",
            },
            ALLOCATOR,
        )
    )
    assert recounted["units_received"] == 10
    assert recounted["units_unallocated"] == 10


def test_run_cancellation_detection_and_snapshots_accept_both_the_allocator_and_the_manager(
    api, shared_write_scenario
):
    """The three operations shared between the analyst and the authoriser succeed for
    each of them in turn.

    PRD: "Position creation and adjustment, receipt booking and receipt recounts are
    shared between `PlanningAdmin` and `Allocator`; run cancellation, the assortment
    detection sweep and cluster snapshot creation are shared between `Allocator` and
    `AllocationManager`"

    PRD: "Either an `Allocator` or an `AllocationManager` may run a detection sweep
    over one program, supplying the `program_id`"

    PRD: a cluster performance snapshot is created "by supplying a `program_id` and a
    `cluster_code`, optionally naming a `basis` of `SIMPLE_AVERAGE` or `UNIT_WEIGHTED`"

    Design: Corner/rbac/store_operator_is_scoped_to_its_own_store_while_shared_writes_accept_both_planner_roles
    """
    program_id = shared_write_scenario["program"]["id"]
    receipt = create_receipt(
        program_id,
        shared_write_scenario["item"]["id"],
        reference="ASN-R302",
        units_received=12,
        size_received=size_map({"M": 12}),
    )
    run = create_run(receipt["id"], headers=ALLOCATOR)
    assert run["status"] == "DRAFT"

    cancelled = validate_success(api.cancel_run(run["id"], MANAGER))
    assert cancelled["status"] == "CANCELLED"

    by_allocator = validate_success(
        api.run_assortment_detection({"program_id": program_id}, ALLOCATOR)
    )
    assert isinstance(by_allocator, list)
    by_manager = validate_success(
        api.run_assortment_detection({"program_id": program_id}, MANAGER)
    )
    assert isinstance(by_manager, list)

    allocator_snapshot = validate_success(
        api.create_performance_snapshot(
            create_snapshot_payload(program_id, "URBAN"), ALLOCATOR
        ),
        expected_status=201,
    )
    assert allocator_snapshot["cluster_code"] == "URBAN"
    manager_snapshot = validate_success(
        api.create_performance_snapshot(
            create_snapshot_payload(program_id, "URBAN"), MANAGER
        ),
        expected_status=201,
    )
    assert manager_snapshot["cluster_code"] == "URBAN"


@pytest.fixture
def self_commit_scenario():
    """A three-store network with a 39-unit receipt already spread by `u-alloc-1`, so
    the proposal's author is known and can be impersonated at the commit."""
    reset_clock()
    scenario = setup_rebalance_network()
    scenario["receipt"] = create_receipt(
        scenario["program"]["id"],
        scenario["item"]["id"],
        reference="ASN-R401",
        units_received=39,
        size_received=size_map({"S": 8, "M": 14, "L": 11, "XL": 6}),
    )
    scenario["run"] = create_proposed_run(scenario["receipt"]["id"])
    return scenario


def test_committing_a_spread_you_proposed_yourself_is_refused(
    api, self_commit_scenario
):
    """The same operator identity that proposed the run comes back wearing the
    authoriser's role; the check compares identities, not roles, so it is refused and
    the run keeps its `PROPOSED` status.

    PRD: "Second the acting `X-User-ID` must differ from the run's
    `proposed_by_user_id`, or the request is refused with `ERR_SEGREGATION_OF_DUTIES`"

    PRD: "an operator may never commit its own spread, and this check precedes the two
    merchandising checks"

    Design: Corner/rbac/segregation_of_duties_binds_the_author_not_the_executor_and_spares_system_proposals
    """
    run = self_commit_scenario["run"]
    assert run["proposed_by_user_id"] == ALLOCATOR_USER_ID

    response = api.commit_run(
        run["id"], make_allocation_manager_headers(ALLOCATOR_USER_ID)
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    after = validate_success(api.get_allocation_run(run["id"], ALLOCATOR))
    assert after["status"] == "PROPOSED"
    assert after["committed_by_user_id"] is None
    assert after["version"] == run["version"]


def test_a_locked_program_outranks_the_self_commit_refusal(api, self_commit_scenario):
    """The program check sits at rung 9 and segregation of duties at rung 12, so the
    self-committer sees the lock rather than its own conflict of interest.

    PRD: "9. The program is `ACTIVE`, for the decision endpoints listed in §2.6 —
    `ERR_PROGRAM_LOCKED`, 409."

    PRD: "12. Segregation of duties on the two authorisation steps —
    `ERR_SEGREGATION_OF_DUTIES`, 409."

    PRD: "First the program must be `ACTIVE`, or the request is refused with
    `ERR_PROGRAM_LOCKED`."

    Design: Corner/rbac/segregation_of_duties_binds_the_author_not_the_executor_and_spares_system_proposals
    """
    run = self_commit_scenario["run"]
    locked = validate_success(
        api.lock_program(
            self_commit_scenario["program"]["id"], MANAGER, {"reason": "quarter close"}
        )
    )
    assert locked["status"] == "LOCKED"

    response = api.commit_run(
        run["id"], make_allocation_manager_headers(ALLOCATOR_USER_ID)
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_LOCKED)


def test_an_already_committed_run_outranks_the_self_commit_refusal(
    api, self_commit_scenario
):
    """Once a different manager has committed the spread, the state check at rung 8
    answers first and the author's second attempt is reported as a bad transition.

    PRD: "The target resource is in a state that permits the requested transition —
    `ERR_INVALID_STATE_TRANSITION`, 409. A commit requires a `PROPOSED` run"

    PRD: "because segregation of duties sits at rung 12, ahead of both the presentation
    minimum at rung 13 and fixture capacity at rung 14, an operator committing its own
    proposal always sees `ERR_SEGREGATION_OF_DUTIES` even when the spread would also
    have breached a shelf capacity."

    Design: Corner/rbac/segregation_of_duties_binds_the_author_not_the_executor_and_spares_system_proposals
    """
    run = self_commit_scenario["run"]
    committed = validate_success(api.commit_run(run["id"], MANAGER))
    assert committed["status"] == "COMMITTED"
    assert committed["committed_by_user_id"] == MANAGER["X-User-ID"]

    response = api.commit_run(
        run["id"], make_allocation_manager_headers(ALLOCATOR_USER_ID)
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_approving_a_transfer_you_proposed_yourself_is_refused(api):
    """The rule binds the author on the transfer side too: the allocator who proposed
    the move cannot authorise it, while a different operator can.

    PRD: "the acting `X-User-ID` must differ from `proposed_by_user_id` or the refusal
    is `ERR_SEGREGATION_OF_DUTIES`"

    PRD: "`approved_by_user_id` is set to the acting `X-User-ID`"

    Design: Corner/rbac/segregation_of_duties_binds_the_author_not_the_executor_and_spares_system_proposals
    """
    reset_clock()
    scenario = setup_proposed_transfer()
    transfer = scenario["transfer"]
    assert transfer["proposed_by_user_id"] == ALLOCATOR_USER_ID
    assert transfer["source_reason"] == "REBALANCE"

    response = api.approve_transfer(
        transfer["id"], make_allocation_manager_headers(ALLOCATOR_USER_ID)
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    approved = validate_success(api.approve_transfer(transfer["id"], MANAGER))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == MANAGER["X-User-ID"]


def test_a_system_proposed_consolidation_is_approvable_by_the_manager_who_ordered_it(
    api,
):
    """A consolidation is authored by the service itself, so no human identity can ever
    collide with it — and the freight gate it would otherwise fail is skipped, which is
    what makes the approval observable.

    PRD: "Segregation of duties is structurally unbreakable for `CONSOLIDATION`
    transfers, whose `proposed_by_user_id` is the literal string `system`."

    PRD: "a `CONSOLIDATION` transfer skips it entirely, because a mandated sweep-up is
    exempt by design"

    Design: Corner/rbac/segregation_of_duties_binds_the_author_not_the_executor_and_spares_system_proposals
    """
    reset_clock()
    scenario = setup_executed_consolidation()
    transfer = scenario["transfer"]
    assert transfer["source_reason"] == "CONSOLIDATION"
    assert transfer["proposed_by_user_id"] == "system"
    assert transfer["status"] == "PROPOSED"
    assert transfer["benefit_ratio_bp"] < scenario["program"]["transfer_min_ratio_bp"]

    approved = validate_success(api.approve_transfer(transfer["id"], MANAGER))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == MANAGER["X-User-ID"]
