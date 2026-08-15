"""Repair orders: two-dimension lifecycle, totals, downtime penalty, invoicing,
payments, credit checks (PRD §3.6, §3.7)."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated, get_success_data,
    create_account, create_fleet_account, create_repair_order, add_labor_line,
    create_bay, create_bay_booking, check_in_booking, drive_ro_to_invoiced,
    create_part, create_parts_sale, set_clock,
    make_fleet_customer_headers,
)

MGR = TEST_USERS["sales_manager_headers"]
ADVISOR = TEST_USERS["service_advisor_headers"]
SERVICE_MGR = TEST_USERS["service_manager_headers"]
CONTROLLER = TEST_USERS["controller_headers"]


def _get_ro(ro_id):
    return get_success_data(api_client.get_repair_order(ro_id, ADVISOR))


def _ar(account_id):
    return get_success_data(
        api_client.get_customer_account(account_id, CONTROLLER))["open_ar_cents"]


def _approved_ro_with_booking(account, labor_hours=1.0, booking_start="2026-08-05T09:00:00Z",
                              booking_end="2026-08-05T11:00:00Z", **ro_kw):
    ro = create_repair_order(account["id"], **ro_kw)
    add_labor_line(ro["id"], hours=labor_hours)
    get_success_data(api_client.submit_estimate(ro["id"], ADVISOR))
    get_success_data(api_client.approve_estimate(
        ro["id"], make_fleet_customer_headers(account["id"])))
    bay = create_bay()
    booking = create_bay_booking(ro["id"], bay["id"], booking_start, booking_end)
    return ro, bay, booking


# ---------------------------------------------------------------- Queue A ---

class TestStartWorkRequiresCheckedInBooking:
    def test_start_rejected_while_booking_only_booked(self, api):
        """PRD §3.6: "Starting work requires `auth_status` `APPROVED`
        (`ERR_RO_NOT_APPROVED`), a `work_status` of `OPEN` or `SCHEDULED`
        (`ERR_RO_STATE`), and at least one booking of this order sitting in
        `CHECKED_IN` (`ERR_BOOKING_NOT_CHECKED_IN`)".
        PRD §3.6: "creating the first booking for an order automatically moves
        it from `OPEN` to `SCHEDULED`."

        Design: Difficulty/cross_entity_state_dependency/start_work_requires_checked_in_booking
        """
        acct = create_account(name="XDep1")
        ro, _, booking = _approved_ro_with_booking(acct)
        assert _get_ro(ro["id"])["work_status"] == "SCHEDULED"
        validate_error(api_client.start_work(ro["id"], ADVISOR),
                       ApiErrorId.ERR_BOOKING_NOT_CHECKED_IN)
        assert _get_ro(ro["id"])["work_status"] == "SCHEDULED"

    def test_start_succeeds_after_check_in(self, api):
        """PRD §3.6: "it stamps `work_started_at` and moves the order to
        `IN_PROGRESS`."

        Design: Difficulty/cross_entity_state_dependency/start_work_requires_checked_in_booking
        """
        acct = create_account(name="XDep1b")
        ro, _, booking = _approved_ro_with_booking(acct)
        check_in_booking(booking["id"])
        data = validate_success(api_client.start_work(ro["id"], ADVISOR), 200)
        assert data["work_status"] == "IN_PROGRESS"
        assert data["work_started_at"]


class TestDowntimeGraceBoundary:
    def _setup_started_ro(self):
        acct = create_account(name="GraceCo")
        ro, bay, booking = _approved_ro_with_booking(
            acct, labor_hours=2.0, promised_ready_at="2026-08-10T17:00:00Z",
            booking_start="2026-08-10T09:00:00Z", booking_end="2026-08-10T11:00:00Z")
        set_clock("2026-08-10T09:00:00Z")
        check_in_booking(booking["id"])
        get_success_data(api_client.start_work(ro["id"], ADVISOR))
        return acct, ro, booking

    def test_exactly_120_minutes_late_owes_nothing(self, api):
        """PRD §3.7: "The first 120 minutes are grace: an order completed
        exactly 120 minutes late owes nothing, while 121 minutes late owes a
        penalty."
        PRD §3.6: "Completing work (from `IN_PROGRESS` only, else
        `ERR_RO_STATE`) stamps `completed_at`, computes the downtime penalty
        described in §3.7, moves the order to `COMPLETED`, and completes every
        `CHECKED_IN` booking on the order."

        Design: Difficulty/boundary_precision_check/downtime_grace_boundary_exactly_120_minutes
        """
        _, ro, booking = self._setup_started_ro()
        set_clock("2026-08-10T19:00:00Z")  # promised 17:00 -> exactly 120 late
        data = validate_success(api_client.complete_work(ro["id"], ADVISOR), 200)
        assert data["work_status"] == "COMPLETED"
        assert data["downtime_penalty_cents"] == 0
        booking_after = get_success_data(api_client.get_service_booking(booking["id"], ADVISOR))
        assert booking_after["status"] == "COMPLETED"

    def test_121_minutes_late_engages_penalty(self, api):
        """PRD §3.7: "Chargeable minutes are the lateness beyond the grace
        window, and the raw penalty is those minutes divided by 60, times the
        order's `labor_rate_cents`, times 25 percent, rounded half-up — then
        capped at half of `labor_sum_cents` (that cap itself rounded half-up)."

        Design: Difficulty/boundary_precision_check/downtime_grace_boundary_exactly_120_minutes
        """
        _, ro, _ = self._setup_started_ro()
        set_clock("2026-08-10T19:01:00Z")  # 121 minutes late -> 1 chargeable
        data = validate_success(api_client.complete_work(ro["id"], ADVISOR), 200)
        # round_half_up(1/60 * 16500 * 0.25) = 69; cap round_half_up(33000*0.5)
        assert data["downtime_penalty_cents"] == 69


class TestRepairOrderTotalsPinnedOrder:
    def _setup_platinum_ro(self):
        acct = create_fleet_account(tier="PLATINUM", credit_limit_cents=10000000,
                                    name="PlatFleet")
        part = create_part(list_price_cents=8000, cost_cents=5000, on_hand=2, sku="BRK-800")
        ro = create_repair_order(acct["id"], external_vin="3ALACWFCXHDXXXX01",
                                 concern="brake job")
        add_labor_line(ro["id"], hours=2.5, description="axle labor")
        add_labor_line(ro["id"], hours=1.0, description="inspection labor")
        add_part_line = api_client.create_repair_order_line(
            {"repair_order_id": ro["id"], "line_type": "PART",
             "part_id": part["id"], "quantity": 1}, ADVISOR)
        assert add_part_line.status_code == 201, f"Setup failed: {add_part_line.text}"
        get_success_data(api_client.submit_estimate(ro["id"], ADVISOR))
        get_success_data(api_client.approve_estimate(
            ro["id"], make_fleet_customer_headers(acct["id"])))
        bay = create_bay()
        booking = create_bay_booking(ro["id"], bay["id"], "2026-08-05T09:00:00Z",
                                     "2026-08-05T11:00:00Z")
        check_in_booking(booking["id"])
        get_success_data(api_client.start_work(ro["id"], ADVISOR))
        get_success_data(api_client.complete_work(ro["id"], ADVISOR))
        return acct, ro

    def test_fee_derives_from_discounted_labor_only(self, api):
        """PRD §3.7: "Then `discount_cents` is the labor sum times the tier
        rate — zero for `STANDARD`, ten percent for `GOLD`, twenty percent for
        `PLATINUM` — rounded half-up; the discount touches labor only, never
        parts. The `shop_supplies_fee_cents` is five percent of the discounted
        labor (labor sum minus discount), rounded half-up, capped at 3,500
        cents."

        Design: Difficulty/combinatorial_formula/repair_order_totals_pinned_evaluation_order
        """
        _, ro = self._setup_platinum_ro()
        data = validate_success(api_client.invoice_repair_order(ro["id"], SERVICE_MGR), 200)
        assert data["labor_sum_cents"] == 57750
        assert data["parts_sum_cents"] == 8000
        assert data["discount_cents"] == 11550  # round_half_up(57750 * 0.20)
        # min(round_half_up(0.05 * (57750 - 11550)), 3500) — not 5% of 57750
        assert data["shop_supplies_fee_cents"] == 2310

    def test_customer_due_sums_in_pinned_order_and_posts_to_ar(self, api):
        """PRD §3.7: "Finally `customer_due_cents` is the labor sum minus the
        discount, plus the parts sum, plus the supplies fee, minus
        `downtime_penalty_cents`, minus the covered amount — floored at zero."
        PRD §3.6: "On success the totals of §3.7 are computed and frozen,
        `customer_due_cents` is added to the account's receivable, and the
        order moves to `INVOICED`."

        Design: Difficulty/combinatorial_formula/repair_order_totals_pinned_evaluation_order
        """
        acct, ro = self._setup_platinum_ro()
        data = validate_success(api_client.invoice_repair_order(ro["id"], SERVICE_MGR), 200)
        # 57750 - 11550 + 8000 + 2310 - 0 - 0
        assert data["customer_due_cents"] == 56510
        assert _ar(acct["id"]) == 56510


# ---------------------------------------------------------------- Queue B ---

def test_booking_cancel_demotes_ro_scheduled_to_open(api):
    """PRD §3.6: "whenever a booking is cancelled or marked no-show, if no
    remaining booking of that order is in `BOOKED` or `CHECKED_IN` and the
    order's `work_status` is `SCHEDULED`, the order demotes back to `OPEN`."

    Design: Corner/state_machines/booking_cancel_demotes_ro_scheduled_to_open
    """
    acct = create_account(name="DemoteCo")
    ro = create_repair_order(acct["id"])
    bay = create_bay()
    booking = create_bay_booking(ro["id"], bay["id"])
    assert _get_ro(ro["id"])["work_status"] == "SCHEDULED"
    data = validate_success(api_client.cancel_booking(booking["id"], ADVISOR), 200)
    assert data["status"] == "CANCELLED"
    assert _get_ro(ro["id"])["work_status"] == "OPEN"


def test_ro_cancel_cascades_to_open_bookings(api):
    """PRD §3.6: "Cancelling an order — advisor-only, and refused once
    `work_status` is `INVOICED`, `PAID`, or already `CANCELLED`
    (`ERR_RO_STATE`) — sets both dimensions to `CANCELLED` and cancels every
    `BOOKED` or `CHECKED_IN` booking on the order."

    Design: Corner/state_machines/ro_cancel_cascades_to_open_bookings
    """
    acct = create_account(name="CascRo")
    ro = create_repair_order(acct["id"])
    bay = create_bay()
    bk1 = create_bay_booking(ro["id"], bay["id"], "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z")
    bk2 = create_bay_booking(ro["id"], bay["id"], "2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z")
    check_in_booking(bk1["id"])
    data = validate_success(api_client.cancel_repair_order(ro["id"], ADVISOR), 200)
    assert data["auth_status"] == "CANCELLED"
    assert data["work_status"] == "CANCELLED"
    bookings, _ = validate_paginated(
        api_client.list_service_bookings(ADVISOR, params={"repair_order_id": ro["id"]}))
    assert {b["id"]: b["status"] for b in bookings} == {
        bk1["id"]: "CANCELLED", bk2["id"]: "CANCELLED"}


def test_booking_no_show_via_sweep(api):
    """PRD §3.5: "The sweep marks a booking `NO_SHOW` once the clock has passed
    its start by more than 60 minutes without a check-in — an event that
    likewise runs the demotion check."

    Design: Corner/state_machines/booking_no_show_via_sweep
    """
    acct = create_account(name="NoShowCo")
    ro = create_repair_order(acct["id"])
    bay = create_bay()
    booking = create_bay_booking(ro["id"], bay["id"], "2026-08-05T09:00:00Z",
                                 "2026-08-05T10:00:00Z")
    set_clock("2026-08-05T10:01:00Z")
    sweep = get_success_data(api_client.run_daily_sweep(TEST_USERS["admin_headers"]))
    assert sweep["bookings_no_show"] == 1
    booking_after = get_success_data(api_client.get_service_booking(booking["id"], ADVISOR))
    assert booking_after["status"] == "NO_SHOW"
    assert _get_ro(ro["id"])["work_status"] == "OPEN"


def test_double_transition_idempotency_second_call_rejected(api):
    """PRD §3.6: "Invoicing belongs to the `ServiceManager`, from `COMPLETED`
    only (`ERR_RO_STATE`)."
    PRD §3.6: "`customer_due_cents` is added to the account's receivable".

    Design: Corner/state_machines/double_transition_idempotency_second_call_rejected
    """
    acct = create_account(name="IdemCo")
    ctx = drive_ro_to_invoiced(acct["id"], labor_hours=1.0)
    ro_id = ctx["ro"]["id"]
    assert ctx["ro"]["customer_due_cents"] == 17325  # 16500 + 825 fee
    validate_error(api_client.invoice_repair_order(ro_id, SERVICE_MGR),
                   ApiErrorId.ERR_RO_STATE)
    assert _ar(acct["id"]) == 17325


def test_estimate_decline_then_revise_cycle(api):
    """PRD §3.6: "Approval moves to `APPROVED`; decline moves to `DECLINED`,
    from which the advisor may revise, returning the order to `DRAFT` provided
    work has not moved past `OPEN` or `SCHEDULED` (`ERR_RO_STATE` otherwise)."

    Design: Corner/rbac/estimate_decline_then_revise_cycle
    """
    acct = create_account(name="CycleRo")
    ro = create_repair_order(acct["id"])
    add_labor_line(ro["id"], hours=1.0)
    get_success_data(api_client.submit_estimate(ro["id"], ADVISOR))
    customer = make_fleet_customer_headers(acct["id"])
    d1 = validate_success(api_client.decline_estimate(ro["id"], customer), 200)
    assert d1["auth_status"] == "DECLINED"
    d2 = validate_success(api_client.revise_estimate(ro["id"], ADVISOR), 200)
    assert d2["auth_status"] == "DRAFT"
    d3 = validate_success(api_client.submit_estimate(ro["id"], ADVISOR), 200)
    assert d3["auth_status"] == "PENDING_APPROVAL"
    d4 = validate_success(api_client.approve_estimate(ro["id"], customer), 200)
    assert d4["auth_status"] == "APPROVED"
    assert d4["work_status"] == "OPEN"


def test_fleet_customer_identity_is_entity_backed(api):
    """PRD §2.1: "When `X-User-Role` is `FleetCustomer`, `X-User-ID` is the
    `id` of the acting `CustomerAccount`; ownership checks on any resource that
    references a `CustomerAccount` compare the resource's foreign-key field to
    `X-User-ID`."
    PRD §3.6: "The customer then approves or declines — `FleetCustomer` only,
    identity matched to the order's `customer_account_id`
    (`ERR_INSUFFICIENT_PERMISSIONS` otherwise)".

    Design: Corner/rbac/fleet_customer_identity_is_entity_backed
    """
    acct = create_account(name="OwnRo")
    other = create_account(name="OtherRo")
    ro = create_repair_order(acct["id"])
    add_labor_line(ro["id"], hours=1.0)
    get_success_data(api_client.submit_estimate(ro["id"], ADVISOR))
    validate_error(api_client.approve_estimate(
        ro["id"], make_fleet_customer_headers(other["id"])),
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
    data = validate_success(api_client.approve_estimate(
        ro["id"], make_fleet_customer_headers(acct["id"])), 200)
    assert data["auth_status"] == "APPROVED"


def test_ro_requires_exactly_one_vehicle_reference(api):
    """PRD §3.6: "a vehicle reference: exactly one of `unit_id` (a unit in
    inventory) or `external_vin` (a customer-owned vehicle the dealership has
    never stocked); supplying both or neither is
    `ERR_VEHICLE_REFERENCE_REQUIRED`."

    Design: Corner/validations/ro_requires_exactly_one_vehicle_reference
    """
    from test_helpers import create_new_unit
    acct = create_account(name="VehCo")
    unit = create_new_unit(vin="1FUJGBDV1CLW88332")
    base = {"customer_account_id": acct["id"], "concern": "x",
            "promised_ready_at": "2026-08-20T17:00:00Z"}
    validate_error(api_client.create_repair_order(dict(base), ADVISOR),
                   ApiErrorId.ERR_VEHICLE_REFERENCE_REQUIRED)
    validate_error(api_client.create_repair_order(
        dict(base, unit_id=unit["id"], external_vin="1M8GDM9A6KP042809"), ADVISOR),
        ApiErrorId.ERR_VEHICLE_REFERENCE_REQUIRED)


def test_credit_limit_enforced_at_invoice_boundary(api):
    """PRD §3.6: "for a `FLEET` account the order's `customer_due_cents` plus
    the account's existing `open_ar_cents` must not exceed
    `credit_limit_cents` (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 402)."

    Design: Corner/validations/credit_limit_enforced_at_invoice_boundary
    """
    acct = create_fleet_account(tier="STANDARD", credit_limit_cents=100000, name="CredCo")
    part = create_part(list_price_cents=90000, cost_cents=50000, on_hand=3, sku="BIG-9")
    create_parts_sale(acct["id"], [{"part_id": part["id"], "quantity": 1}])
    assert _ar(acct["id"]) == 90000
    # RO will invoice at 17325 (16500 labor + 825 fee): 90000 + 17325 > 100000
    ro = create_repair_order(acct["id"])
    add_labor_line(ro["id"], hours=1.0)
    get_success_data(api_client.submit_estimate(ro["id"], ADVISOR))
    get_success_data(api_client.approve_estimate(
        ro["id"], make_fleet_customer_headers(acct["id"])))
    bay = create_bay()
    booking = create_bay_booking(ro["id"], bay["id"])
    check_in_booking(booking["id"])
    get_success_data(api_client.start_work(ro["id"], ADVISOR))
    get_success_data(api_client.complete_work(ro["id"], ADVISOR))
    validate_error(api_client.invoice_repair_order(ro["id"], SERVICE_MGR),
                   ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, 402)
    assert _get_ro(ro["id"])["work_status"] == "COMPLETED"
    assert _ar(acct["id"]) == 90000


def test_ro_payment_must_equal_customer_due(api):
    """PRD §3.6: "a `Controller` posts `amount_cents`, which must equal
    `customer_due_cents` exactly (`ERR_PAYMENT_AMOUNT_MISMATCH`), the order
    moves from `INVOICED` to `PAID`, the receivable drops by the amount".

    Design: Corner/validations/ro_payment_must_equal_customer_due
    """
    acct = create_account(name="PayCo")
    ctx = drive_ro_to_invoiced(acct["id"], labor_hours=1.0)
    ro_id = ctx["ro"]["id"]
    validate_error(api_client.post_ro_payment(ro_id, {"amount_cents": 17324}, CONTROLLER),
                   ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)
    assert _get_ro(ro_id)["work_status"] == "INVOICED"
    data = validate_success(api_client.post_ro_payment(
        ro_id, {"amount_cents": 17325}, CONTROLLER), 200)
    assert data["work_status"] == "PAID"
    assert _ar(acct["id"]) == 0
