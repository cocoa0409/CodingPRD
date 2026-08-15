"""Inventory programs: creation gates, activation pins, close/suspend
cascades, release creation gates, and deallocation."""
from test_helpers import (
    PLANT,
    SALES,
    ApiErrorId,
    activate_program,
    allocate_release,
    assert_inventory_program,
    assert_release_order,
    create_approved_spec,
    create_inventory_program,
    create_locked_cnc_program,
    create_release,
    create_validated_spec,
    get_program,
    get_release,
    make_customer_headers,
    setup_stocked_program,
    validate_error,
    validate_success,
)


def test_program_create_requires_approved_spec(api):
    """PRD §3.6: "The specification must be `APPROVED`, or the create is
    rejected with `ERR_SPEC_NOT_APPROVED` (HTTP 409), and the program's
    `customer_id` must equal the specification's owning `customer_id`, or the
    create is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/errors/error_spec_not_approved_on_program_create
    """
    customer, _m, spec = create_validated_spec()
    assert spec["status"] == "VALIDATED"

    resp = api.create_inventory_program(
        {
            "customer_id": customer["id"],
            "package_spec_id": spec["id"],
            "pricing_mode": "CURRENT",
            "max_stock_qty": 500,
            "reorder_point_qty": 100,
            "min_release_qty": 50,
        },
        SALES,
    )
    validate_error(resp, ApiErrorId.ERR_SPEC_NOT_APPROVED)


def test_replenish_without_locked_program_returns_error(api):
    """PRD §3.6: "When no `LOCKED` cut program exists for the program's
    specification, the request is rejected with `ERR_NO_LOCKED_PROGRAM` (HTTP
    409)."

    Design: Corner/endpoints/replenish_without_locked_program_returns_error
    """
    customer, _m, spec = create_approved_spec()  # no cut program ever locked
    program = create_inventory_program(customer["id"], spec["id"])
    activate_program(program["id"])

    resp = api.replenish_program(program["id"], 100, PLANT)
    validate_error(resp, ApiErrorId.ERR_NO_LOCKED_PROGRAM)


def test_release_create_on_proposed_program_rejected(api):
    """PRD §3.6: "The caller must own the program — a mismatch is rejected
    with `ERR_FORBIDDEN_OWNERSHIP` — the program must be `ACTIVE`, or the
    create is rejected with `ERR_PROGRAM_NOT_ACTIVE`, and the `qty` must be
    at least the program's `min_release_qty`, or the create is rejected with
    `ERR_MIN_RELEASE_QTY` (HTTP 422)."

    Design: Corner/validations/release_create_on_proposed_program_rejected
    """
    customer, _m, spec = create_approved_spec()
    program = create_inventory_program(customer["id"], spec["id"])
    assert program["status"] == "PROPOSED"

    resp = api.create_release_order(
        {"inventory_program_id": program["id"], "qty": 50,
         "requested_ship_date": "2026-08-10T00:00:00Z"},
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)


def test_release_below_min_qty_rejected(api):
    """PRD §3.6: "The caller must own the program — a mismatch is rejected
    with `ERR_FORBIDDEN_OWNERSHIP` — the program must be `ACTIVE`, or the
    create is rejected with `ERR_PROGRAM_NOT_ACTIVE`, and the `qty` must be
    at least the program's `min_release_qty`, or the create is rejected with
    `ERR_MIN_RELEASE_QTY` (HTTP 422)."

    Design: Corner/validations/release_below_min_qty_rejected
    """
    customer, _m, spec = create_approved_spec()
    program = create_inventory_program(customer["id"], spec["id"],
                                       min_release_qty=50)
    activate_program(program["id"])

    resp = api.create_release_order(
        {"inventory_program_id": program["id"], "qty": 10,
         "requested_ship_date": "2026-08-10T00:00:00Z"},
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MIN_RELEASE_QTY)


def test_program_close_blocked_with_open_release(api):
    """PRD §3.6: "Closure, from `PROPOSED`, `ACTIVE`, or `SUSPENDED`, moves
    the program to `CLOSED` and is permitted only when no release order is
    `PENDING` or `ALLOCATED`; otherwise the close is rejected with
    `ERR_PROGRAM_HAS_OPEN_RELEASES` (HTTP 409)."

    Design: Corner/state_machines/program_close_blocked_with_open_release
    """
    customer, _m, spec = create_approved_spec()
    create_locked_cnc_program(spec["id"])
    program = create_inventory_program(customer["id"], spec["id"],
                                       max_stock_qty=500, reorder_point_qty=100,
                                       min_release_qty=50)
    activate_program(program["id"])
    release = create_release(program["id"], 50, customer["id"])

    resp = api.close_program(program["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_HAS_OPEN_RELEASES)

    cancel = api.cancel_release(release["id"], make_customer_headers(customer["id"]))
    validate_success(cancel)
    closed = validate_success(api.close_program(program["id"], SALES))
    assert closed["status"] == "CLOSED"


def test_release_deallocate_clears_price_and_returns_reservation(api):
    """PRD §3.6: "Deallocation, by a `PlantManager`, moves a release from
    `ALLOCATED` back to `PENDING`: the program's `reserved_qty` is reduced by
    the release `qty`, and `unit_price_cents` and `total_price_cents` reset
    to null, to be repriced at the next allocation."

    Design: Corner/state_machines/release_deallocate_clears_price_and_returns_reservation
    """
    ctx = setup_stocked_program(method="CNC_ROUTE", max_stock_qty=500,
                                reorder_point_qty=100, min_release_qty=50,
                                stock_qty=300, machine_id="CNC-1")
    customer, program = ctx["customer"], ctx["program"]
    release = create_release(program["id"], 100, customer["id"])
    allocated = allocate_release(release["id"])
    assert allocated["status"] == "ALLOCATED"
    assert get_program(program["id"])["reserved_qty"] == 100

    deallocated = validate_success(api.deallocate_release(release["id"], PLANT))
    assert_release_order(deallocated)
    assert deallocated["status"] == "PENDING"
    assert deallocated["unit_price_cents"] is None
    assert deallocated["total_price_cents"] is None
    assert get_program(program["id"])["reserved_qty"] == 0, (
        "deallocation returns the reservation to unreserved stock"
    )


def test_program_suspend_cancels_open_releases_and_frees_reserved(api):
    """PRD §3.6: "Suspension moves an `ACTIVE` program to `SUSPENDED` and
    cancels every release order still `PENDING` or `ALLOCATED`, returning
    each allocated release's reservation — the program's `reserved_qty` is
    reduced by each such release's `qty`." PRD §3.6: "Resumption moves a
    `SUSPENDED` program back to `ACTIVE`."

    Design: Corner/endpoints/program_suspend_cancels_open_releases_and_frees_reserved
    """
    ctx = setup_stocked_program(method="CNC_ROUTE", max_stock_qty=500,
                                reorder_point_qty=100, min_release_qty=50,
                                stock_qty=300, machine_id="CNC-1")
    customer, program = ctx["customer"], ctx["program"]
    rel1 = create_release(program["id"], 100, customer["id"],
                          requested_ship_date="2026-08-10T00:00:00Z")
    allocate_release(rel1["id"])
    rel2 = create_release(program["id"], 50, customer["id"],
                          requested_ship_date="2026-08-11T00:00:00Z")

    suspended = validate_success(api.suspend_program(program["id"], SALES))
    assert_inventory_program(suspended)
    assert suspended["status"] == "SUSPENDED"
    assert suspended["reserved_qty"] == 0, (
        "the allocated release's 100 reserved units are returned"
    )
    assert get_release(rel1["id"])["status"] == "CANCELLED"
    assert get_release(rel2["id"])["status"] == "CANCELLED"

    resumed = validate_success(api.resume_program(program["id"], SALES))
    assert resumed["status"] == "ACTIVE"
    assert get_release(rel1["id"])["status"] == "CANCELLED", (
        "cancelled releases stay cancelled across a resume"
    )


def test_customer_cancels_own_pending_release(api):
    """PRD §3.6: "Cancellation — by the owning `Customer`, by a
    `PlantManager`, or by the system when the program is suspended — moves a
    release from `PENDING` or `ALLOCATED` to `CANCELLED`, and cancelling an
    `ALLOCATED` release returns its reservation to the program."

    Design: Corner/rbac/customer_cancels_own_pending_release
    """
    customer, _m, spec = create_approved_spec()
    create_locked_cnc_program(spec["id"])
    program = create_inventory_program(customer["id"], spec["id"],
                                       max_stock_qty=500, reorder_point_qty=100,
                                       min_release_qty=50)
    activate_program(program["id"])
    release = create_release(program["id"], 50, customer["id"])
    assert release["status"] == "PENDING"

    cancelled = validate_success(
        api.cancel_release(release["id"], make_customer_headers(customer["id"]))
    )
    assert cancelled["status"] == "CANCELLED"


def test_sales_engineer_cannot_allocate_release(api):
    """PRD §2.1: "A request whose role is recognized but not permitted on the
    target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." PRD §4:
    the allocate endpoint's authorized role is `PlantManager`.

    Design: Corner/rbac/sales_engineer_cannot_allocate_release
    """
    customer, _m, spec = create_approved_spec()
    create_locked_cnc_program(spec["id"])
    program = create_inventory_program(customer["id"], spec["id"],
                                       max_stock_qty=500, reorder_point_qty=100,
                                       min_release_qty=50)
    activate_program(program["id"])
    release = create_release(program["id"], 50, customer["id"])

    resp = api.allocate_release(release["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert get_release(release["id"])["status"] == "PENDING"
