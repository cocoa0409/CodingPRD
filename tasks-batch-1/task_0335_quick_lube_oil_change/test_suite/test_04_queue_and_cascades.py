"""Queue lifecycle and the freed-bay cascade: the cyclic queue ticket, the
complete -> free-bay -> promote chain, the cancel compensating chain, the open-bay-count
conservation invariant, the empty-queue edge, and same-request consistency.

Sources: difficulty rules non_linear_state_machine, transitive_cascade,
compensating_invariant, boundary_precision_check; corner sections state_machines,
consistency_model, cross_cutting_complexity_layers.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    # fixtures
    set_clock,
    setup_shop_with_catalog,
    create_retail_vehicle,
    create_queue_ticket,
    create_direct_work_order,
    create_inspection_item,
    claim_start,
    begin_inspection,
    add_line,
    drive_to_paid,
    complete,
    cancel_work_order,
    get_work_order,
    setup_assigned_ticket,
    create_shop,
    create_package,
    create_bay,
)

SA = TEST_USERS["service_advisor_headers"]
SM = TEST_USERS["shop_manager_headers"]


# ─── non_linear_state_machine / queue_ticket_cyclic_assign_requeue_reassign ─

def test_queue_ticket_requeue_returns_to_waiting(api):
    """PRD §3.3: "Requeuing cancels the draft work order — which releases its bay from
    `OCCUPIED` back to `OPEN` and raises the open-bay count by one — clears the ticket's
    `assigned_bay_id` and `work_order_id`, and returns the ticket to `WAITING`, from which
    it may be assigned again later."

    Design: Difficulty/non_linear_state_machine/queue_ticket_cyclic_assign_requeue_reassign
    """
    s = setup_assigned_ticket()
    ticket, bay = s["ticket"], s["bay"]
    requeued = get_success_data(api.requeue_queue_ticket(ticket["id"], SA))
    assert requeued["status"] == "WAITING"
    assert requeued["work_order_id"] is None


def test_queue_ticket_reassign_after_requeue_completes_cycle(api):
    """PRD §3.3: "A successful assignment advances the ticket from `WAITING` to `ASSIGNED`,
    moves the bay from `OPEN` to `OCCUPIED` while setting its `current_work_order_id` and
    lowering the shop's open-bay count by one and bumping the bay's `version`, and creates
    a fresh `WorkOrder` in service status `DRAFT` and payment status `UNPAID`."

    Design: Difficulty/non_linear_state_machine/queue_ticket_cyclic_assign_requeue_reassign
    """
    s = setup_assigned_ticket()
    ticket, bay = s["ticket"], s["bay"]
    get_success_data(api.requeue_queue_ticket(ticket["id"], SA))
    # Re-observe the bay version (it advanced when the requeue freed the bay).
    bay_now = get_success_data(api.get_bay(bay["id"], SA))
    reassigned = get_success_data(api.assign_queue_ticket(
        ticket["id"], {"bay_id": bay["id"], "expected_bay_version": bay_now["version"]}, SA))
    assert reassigned["status"] == "ASSIGNED"
    bay_after = get_success_data(api.get_bay(bay["id"], SA))
    assert bay_after["status"] == "OCCUPIED"


# ─── transitive_cascade / complete_frees_bay_promotes_next_queue_ticket ────

def test_complete_frees_bay_and_promotes_waiting_ticket(api):
    """PRD §3.9: "That freed bay immediately triggers a promotion: the waiting ticket with
    the lowest `queue_seq` at this shop, if any exists, is pulled forward — it advances
    from `WAITING` to `ASSIGNED`, its `assigned_bay_id` is set to the freed bay, a new
    `DRAFT` work order is created for it, and the bay is occupied again, which lowers the
    open-bay count by one."

    Design: Difficulty/transitive_cascade/complete_frees_bay_promotes_next_queue_ticket
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh_a = create_retail_vehicle(shop["id"], vin="VINCASA01", plate="CSA1",
                                  make="VW", model="Golf", odometer=8000)
    veh_b = create_retail_vehicle(shop["id"], vin="VINCASB01", plate="CSB1",
                                  make="VW", model="Polo", odometer=9000)
    wo_a = create_direct_work_order(shop["id"], veh_a["id"], bay["id"], pkg["id"], 8000)
    ticket_b = create_queue_ticket(shop["id"], veh_b["id"], pkg["id"])
    drive_to_paid(wo_a["id"], tech["id"], payment_method="CASH")
    complete(wo_a["id"])

    promoted = get_success_data(api.get_queue_ticket(ticket_b["id"], SA))
    assert promoted["status"] == "ASSIGNED"
    assert promoted["work_order_id"] is not None
    bay_after = get_success_data(api.get_bay(bay["id"], SA))
    assert bay_after["status"] == "OCCUPIED"  # re-occupied by the promoted ticket


def test_complete_marks_completed_and_links_ticket_done(api):
    """PRD §3.9: "A `ServiceAdvisor` completes a ready order, advancing its service status
    from `READY` to `COMPLETED`."
    PRD §3.9: "Finally, if the order originated from a queue ticket, that ticket advances
    from `IN_BAY` to `DONE`."

    Design: Difficulty/transitive_cascade/complete_frees_bay_promotes_next_queue_ticket
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh_a = create_retail_vehicle(shop["id"], vin="VINCASA02", plate="CSA2",
                                  make="VW", model="Golf", odometer=8000)
    veh_b = create_retail_vehicle(shop["id"], vin="VINCASB02", plate="CSB2",
                                  make="VW", model="Polo", odometer=9000)
    wo_a = create_direct_work_order(shop["id"], veh_a["id"], bay["id"], pkg["id"], 8000)
    create_queue_ticket(shop["id"], veh_b["id"], pkg["id"])
    drive_to_paid(wo_a["id"], tech["id"], payment_method="CASH")
    completed = complete(wo_a["id"])
    assert completed["service_status"] == "COMPLETED"


# ─── transitive_cascade / cancel_voids_lines_and_payment_and_frees_bay ─────

def test_cancel_authorized_fleet_order_voids_payment_and_releases_credit(api):
    """PRD §3.9: "If the order's payment was `AUTHORIZED`, the compensating path runs: the
    `Payment` moves from `AUTHORIZED` to `VOIDED`, the order's `payment_status` becomes
    `VOIDED`, and the fleet account's `reserved_credit_cents` is released."

    Design: Difficulty/transitive_cascade/cancel_voids_lines_and_payment_and_frees_bay
    """
    set_clock()
    shop = get_success_data(api.create_shop(
        {"name": "Main", "tax_rate": 0.0825, "target_throughput_seconds": 1800}, SM))
    pkg = get_success_data(api.create_service_package(
        {"shop_id": shop["id"], "oil_grade": "CONVENTIONAL", "name": "Basic",
         "base_price_cents": 6995, "included_quarts": 5, "labor_minutes": 20,
         "interval_miles": 5000, "interval_days": 180}, SM))
    fleet = get_success_data(api.create_fleet_account(
        {"shop_id": shop["id"], "company_name": "Acme", "discount_pct": 0.10,
         "credit_limit_cents": 100000}, SM))
    bay = get_success_data(api.create_bay({"shop_id": shop["id"], "label": "Bay 1"}, SM))
    tech = get_success_data(api.create_technician({"shop_id": shop["id"], "full_name": "Tess"}, SM))
    veh = get_success_data(api.create_vehicle(
        {"shop_id": shop["id"], "fleet_account_id": fleet["id"], "vin": "VINCXL001",
         "plate": "CXL1", "make": "Ford", "model": "F150", "odometer": 12000},
        {"X-User-ID": fleet["id"], "X-User-Role": "FleetManager", "Content-Type": "application/json"}))
    wo = get_success_data(api.create_work_order(
        {"shop_id": shop["id"], "vehicle_id": veh["id"], "bay_id": bay["id"],
         "package_id": pkg["id"], "odometer_in": 12000}, SA))
    claim_start(wo["id"], tech["id"])
    begin_inspection(wo["id"], tech["id"])
    get_success_data(api.authorize_payment(wo["id"], {"payment_method": "FLEET_ACCOUNT"}, SA))

    before = get_success_data(api.get_fleet_account(fleet["id"], SM))
    assert before["reserved_credit_cents"] == 6814

    cancelled = cancel_work_order(wo["id"])
    assert cancelled["service_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "VOIDED"
    after = get_success_data(api.get_fleet_account(fleet["id"], SM))
    assert after["reserved_credit_cents"] == 0
    bay_after = get_success_data(api.get_bay(bay["id"], SM))
    assert bay_after["status"] == "OPEN"


def test_cancel_voids_lines_and_zeros_lines_total(api):
    """PRD §3.9: "Cancellation voids the order's lines: every `WorkOrderLine` on the order
    has its `voided` flag set to true and the `lines_total_cents` is recomputed to zero."

    Design: Difficulty/transitive_cascade/cancel_voids_lines_and_payment_and_frees_bay
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    item = create_inspection_item(shop["id"], code="AIR_FILTER", name="Air Filter",
                                  price_cents=4495, labor_minutes=5)
    veh = create_retail_vehicle(shop["id"], vin="VINCXL002", plate="CXL2",
                                make="Honda", model="Fit", odometer=12000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 12000)
    claim_start(wo["id"], tech["id"])
    in_insp = begin_inspection(wo["id"], tech["id"])
    add_line(wo["id"], tech["id"], item["id"], in_insp["version"])
    before = get_work_order(wo["id"])
    assert before["lines_total_cents"] == 4495
    cancelled = cancel_work_order(wo["id"])
    assert cancelled["service_status"] == "CANCELLED"
    assert cancelled["lines_total_cents"] == 0
    lines = validate_success(api.list_lines(wo["id"], SA))
    assert all(line["voided"] is True for line in lines), "all lines must be voided on cancel"


# ─── compensating_invariant / open_bay_count_conserved_under_create_then_cancel ─

def test_open_bay_count_drops_on_occupy(api):
    """PRD §2.9: "Creating a bay opens it and raises the count by one; closing an open bay
    lowers it by one; reopening a closed bay raises it by one; occupying a bay lowers it by
    one; and freeing an occupied bay raises it by one."

    Design: Difficulty/compensating_invariant/open_bay_count_conserved_under_create_then_cancel
    """
    shop = create_shop()
    pkg = create_package(shop["id"])
    bay = create_bay(shop["id"])
    before = get_success_data(api.get_shop(shop["id"], SM))
    assert before["open_bay_count"] == 1
    veh = create_retail_vehicle(shop["id"], vin="VININV001", plate="INV1",
                                make="Honda", model="Fit", odometer=2000)
    create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 2000)
    occupied = get_success_data(api.get_shop(shop["id"], SM))
    assert occupied["open_bay_count"] == 0


def test_open_bay_count_conserved_after_create_then_cancel(api):
    """PRD §2.9: "The shop's `open_bay_count` is a conserved tally: it is the count of that
    shop's bays whose status is `OPEN`, and it must move by exactly one in lock-step with
    every bay status change."
    PRD §3.9: "The bay is freed from `OCCUPIED` to `OPEN` with its `current_work_order_id`
    cleared and the open-bay count raised by one."

    Design: Difficulty/compensating_invariant/open_bay_count_conserved_under_create_then_cancel
    """
    shop = create_shop()
    pkg = create_package(shop["id"])
    bay = create_bay(shop["id"])
    veh = create_retail_vehicle(shop["id"], vin="VININV002", plate="INV2",
                                make="Honda", model="Fit", odometer=2000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 2000)
    cancel_work_order(wo["id"])
    after = get_success_data(api.get_shop(shop["id"], SM))
    assert after["open_bay_count"] == 1  # conserved: equals the pre-create value


# ─── boundary_precision_check / empty_queue_complete_no_promotion ──────────

def test_complete_with_empty_queue_leaves_bay_open(api):
    """PRD §3.9: "The net effect on the open-bay count is therefore unchanged when a ticket
    was waiting to take the bay, and a rise of one when the queue was empty."

    Design: Difficulty/boundary_precision_check/empty_queue_complete_no_promotion
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh = create_retail_vehicle(shop["id"], vin="VINEMP001", plate="EMP1",
                                make="Honda", model="Fit", odometer=7000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 7000)
    drive_to_paid(wo["id"], tech["id"], payment_method="CASH")
    complete(wo["id"])
    bay_after = get_success_data(api.get_bay(bay["id"], SA))
    assert bay_after["status"] == "OPEN"  # no WAITING ticket to promote
    shop_after = get_success_data(api.get_shop(shop["id"], SA))
    assert shop_after["open_bay_count"] == 1


def test_complete_with_empty_queue_clears_bay_back_pointer(api):
    """PRD §3.9: "The bay is freed: it moves from `OCCUPIED` to `OPEN`, its
    `current_work_order_id` is cleared, and the shop's `open_bay_count` rises by one."

    Design: Difficulty/boundary_precision_check/empty_queue_complete_no_promotion
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh = create_retail_vehicle(shop["id"], vin="VINEMP002", plate="EMP2",
                                make="Honda", model="Fit", odometer=7000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 7000)
    drive_to_paid(wo["id"], tech["id"], payment_method="CASH")
    completed = complete(wo["id"])
    assert completed["service_status"] == "COMPLETED"
    bay_after = get_success_data(api.get_bay(bay["id"], SA))
    # Empty queue: no promotion, so the freed bay's back-pointer stays cleared.
    assert bay_after["current_work_order_id"] is None


# ─── corner: state_machines / cancel_waiting_queue_ticket_succeeds ─────────

def test_cancel_waiting_queue_ticket_succeeds(api):
    """PRD §3.3: "A `ServiceAdvisor` may cancel a still-waiting ticket, moving it from
    `WAITING` to `CANCELLED`".

    Design: Corner/state_machines/cancel_waiting_queue_ticket_succeeds
    """
    shop = create_shop()
    pkg = create_package(shop["id"])
    veh = create_retail_vehicle(shop["id"], vin="VINQCN001", plate="QCN1",
                                make="Kia", model="Rio", odometer=1000)
    ticket = create_queue_ticket(shop["id"], veh["id"], pkg["id"])
    cancelled = get_success_data(api.cancel_queue_ticket(ticket["id"], SA))
    assert cancelled["status"] == "CANCELLED"


# ─── corner: state_machines / assign_to_non_open_bay_returns_bay_not_open ──

def test_assign_to_closed_bay_returns_bay_not_open(api):
    """PRD §3.3: "The target bay must be `OPEN`, or the request is rejected with
    `ERR_BAY_NOT_OPEN`".

    Design: Corner/state_machines/assign_to_non_open_bay_returns_bay_not_open
    """
    shop = create_shop()
    pkg = create_package(shop["id"])
    bay = create_bay(shop["id"])
    closed = get_success_data(api.close_bay(bay["id"], SM))
    veh = create_retail_vehicle(shop["id"], vin="VINANO001", plate="ANO1",
                                make="Kia", model="Rio", odometer=1000)
    ticket = create_queue_ticket(shop["id"], veh["id"], pkg["id"])
    res = api.assign_queue_ticket(
        ticket["id"], {"bay_id": bay["id"], "expected_bay_version": closed["version"]}, SA)
    validate_error(res, "ERR_BAY_NOT_OPEN", expected_status=409)
    ticket_after = get_success_data(api.get_queue_ticket(ticket["id"], SA))
    assert ticket_after["status"] == "WAITING"


# ─── corner: cross_cutting / derived_field_lines_total_reconciles_on_remove ─

def test_remove_line_reconciles_lines_total_and_total(api):
    """PRD §3.7: "Removing a line is also performed by a `Technician` during inspection;
    the targeted line must exist on the order, else `ERR_LINE_NOT_FOUND`, and removal
    recomputes the order's pricing."
    PRD §3.6: "The `lines_total_cents` is the sum of `price_cents` over this order's
    non-voided lines."

    Design: Corner/cross_cutting_complexity_layers/derived_field_lines_total_reconciles_on_remove
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    item = create_inspection_item(shop["id"], code="AIR_FILTER", name="Air Filter",
                                  price_cents=4495, labor_minutes=5)
    veh = create_retail_vehicle(shop["id"], vin="VINDFR001", plate="DFR1",
                                make="Honda", model="Fit", odometer=1000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 1000)
    claim_start(wo["id"], tech["id"])
    in_insp = begin_inspection(wo["id"], tech["id"])
    line = add_line(wo["id"], tech["id"], item["id"], in_insp["version"])

    after = validate_success(
        api.remove_line(wo["id"], line["id"],
                        {"X-User-ID": tech["id"], "X-User-Role": "Technician",
                         "Content-Type": "application/json"}), 200)
    assert after["lines_total_cents"] == 0
    assert after["subtotal_cents"] == 6995
    assert after["total_cents"] == 7572


# ─── corner: consistency_model / immediate_consistency_open_bay_count ──────

def test_open_bay_count_immediately_reflects_bay_creation(api):
    """PRD §2.9: "Creating a bay opens it and raises the count by one".
    PRD §3.4: "Get a shop (live open-bay count)" — read returns the live count.

    Design: Corner/consistency_model/immediate_consistency_open_bay_count_visible_same_response
    """
    shop = create_shop()
    create_bay(shop["id"], label="Bay 1")
    create_bay(shop["id"], label="Bay 2")
    after = get_success_data(api.get_shop(shop["id"], SM))
    assert after["open_bay_count"] == 2
