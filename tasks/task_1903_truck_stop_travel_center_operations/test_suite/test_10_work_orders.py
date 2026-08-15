"""Maintenance shop: vendor loop, pinned invoice computation, bay schedule
interval semantics, bay occupancy, and technician identity scoping."""
import pytest

from test_helpers import (
    ApiErrorId,
    set_clock,
    setup_work_order_in_progress,
    validate_error,
    validate_success,
    api_client,
)
from test_helpers.constants import TEST_CLOCK_ISO
from test_helpers.factories import (
    bay_maintenance_block_payload,
    issue_part_payload,
    send_to_vendor_payload,
    work_order_close_payload,
)
from test_helpers.fixtures import (
    CASH_1,
    GM,
    SM_2,
    advance_work_order_to_approved,
    create_bay,
    create_register,
    create_site,
    create_stock_item,
    create_technician,
    create_work_order,
    open_shift,
    reload_bay,
    reload_shift,
    reload_register,
    schedule_work_order,
)
from test_helpers.test_users import make_maintenance_tech_headers


class TestVendorLoopAndInvoice:
    def test_work_order_vendor_loop_and_invoice(self, api):
        """PRD section 3.7: "Work in progress may be sent out to an outside
        vendor — `IN_PROGRESS → WAITING_VENDOR`, bay work only, never a
        road-service call — recording the payload's `vendor_name` and
        `reason` into `vendor_out_reason`, and received back `WAITING_VENDOR
        → IN_PROGRESS`."
        PRD section 3.7: "The invoice is computed in a pinned order:
        `parts_total_cents` first, the exact sum over part lines of
        issued-minus-returned quantity times the snapshotted
        `unit_price_cents`; then `labor_total_cents`, the actual hours
        multiplied by the technician's `hourly_rate_cents`, rounded half up;
        then `environmental_fee_cents`, 150 cents per net tire — the sum of
        issued-minus-returned quantities over parts whose stock item's `sku`
        contains "TIRE", zero otherwise; then `shop_supplies_cents`, three
        percent of the parts total rounded half up; and finally
        `invoice_total_cents` as the sum of the four."
        PRD section 2.8: "Posture is `NEEDS_DROP` when the open shift's
        expected cash exceeds five times the register's `float_cents`".

        Design: Corner/state_machines/sm_work_order_vendor_loop_invoice
        """
        site = create_site("Site S4")
        set_clock(TEST_CLOCK_ISO)
        tire = create_stock_item(
            site["id"], sku="TIRE-STEER", name="Steer tire",
            category="SHOP_PART", unit_price_cents=41500, reorder_point=2,
            initial_on_hand_quantity=10,
        )
        filt = create_stock_item(
            site["id"], sku="FILTER-Y", name="Filter Y", category="SHOP_PART",
            unit_price_cents=4599, reorder_point=2, initial_on_hand_quantity=10,
        )
        register = create_register(site["id"])
        shift = open_shift(site["id"], register["id"])
        shop = setup_work_order_in_progress(site=site)

        validate_success(
            api.work_order_issue_part(shop.wo["id"],
                                      issue_part_payload(tire["id"], 2),
                                      shop.tech_headers),
            201,
        )
        validate_success(
            api.work_order_issue_part(shop.wo["id"],
                                      issue_part_payload(filt["id"], 1),
                                      shop.tech_headers),
            201,
        )

        out = validate_success(
            api.work_order_send_to_vendor(
                shop.wo["id"],
                send_to_vendor_payload("Alignment Co", "alignment rack down"),
                shop.tech_headers,
            )
        )
        assert out["status"] == "WAITING_VENDOR"
        back = validate_success(
            api.work_order_return_from_vendor(shop.wo["id"], shop.tech_headers)
        )
        assert back["status"] == "IN_PROGRESS"

        from test_helpers.factories import complete_work_payload
        completed = validate_success(
            api.work_order_complete_work(
                shop.wo["id"], complete_work_payload(1.5), shop.tech_headers
            )
        )
        assert completed["parts_total_cents"] == 87599   # 2x41500 + 1x4599
        assert completed["labor_total_cents"] == 18750   # 1.5 x 12500
        assert completed["environmental_fee_cents"] == 300  # 2 net tires x 150
        assert completed["shop_supplies_cents"] == 2628  # round(87599 x 0.03)
        assert completed["invoice_total_cents"] == 109277
        assert completed["status"] == "READY_FOR_PICKUP"
        assert reload_bay(shop.bay["id"])["status"] == "IDLE"

        closed = validate_success(
            api.work_order_close(
                shop.wo["id"],
                work_order_close_payload("CASH", shift_id=shift["id"]),
                CASH_1,
            )
        )
        assert closed["status"] == "CLOSED"
        assert closed["payment_status"] == "PAID"
        assert reload_shift(shift["id"])["expected_cash_cents"] == 129277
        assert reload_register(register["id"])["posture"] == "NEEDS_DROP"


class TestBayScheduleIntervals:
    def _setup_bay_with_block(self):
        site = create_site("Site P")
        set_clock(TEST_CLOCK_ISO)
        tech = create_technician(site["id"])
        bay = create_bay(site["id"], 1)
        validate_success(
            api_client.bay_maintenance_block(
                bay["id"],
                bay_maintenance_block_payload(
                    "2026-08-13T12:00:00Z", "2026-08-13T13:00:00Z",
                    "lift inspection"),
                GM,
            )
        )
        wos = []
        for i in range(1, 5):
            wo = create_work_order(site["id"], f"TRK-{i}", f"wo{i}")
            advance_work_order_to_approved(wo["id"], tech["id"])
            wos.append(wo)
        return site, tech, bay, wos

    def _schedule(self, wo_id, bay_id, tech_id, start, end):
        from test_helpers.factories import work_order_schedule_payload
        return api_client.work_order_schedule(
            wo_id, work_order_schedule_payload(bay_id, tech_id, start, end), GM
        )

    def test_schedule_touching_closed_block_or_overlapping_job_rejected(self, api):
        """PRD section 3.7: "The window must also not even touch a closed
        maintenance block on the bay: a conflict exists exactly when
        `scheduled_from` is at or before the block's `blocked_to` and the
        block's `blocked_from` is at or before `scheduled_to`, failing with
        `ERR_BAY_MAINTENANCE_CONFLICT` (HTTP 422)." and "The window must not
        overlap — half-open on both sides — any non-terminal scheduled window
        on the same bay, meaning work orders in `SCHEDULED`, `IN_SHOP`, or
        `IN_PROGRESS`; overlap fails with `ERR_BAY_DOUBLE_BOOKED`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/bay_half_open_schedule_vs_closed_maintenance_block
        """
        _, tech, bay, (wo1, wo2, wo3, _) = self._setup_bay_with_block()
        validate_success(
            self._schedule(wo1["id"], bay["id"], tech["id"],
                           "2026-08-13T08:00:00Z", "2026-08-13T10:00:00Z")
        )

        # [10:00,12:00) touches the closed block [12:00,13:00] at 12:00
        conflict = self._schedule(wo2["id"], bay["id"], tech["id"],
                                  "2026-08-13T10:00:00Z", "2026-08-13T12:00:00Z")
        validate_error(conflict, ApiErrorId.ERR_BAY_MAINTENANCE_CONFLICT)

        # [09:00,11:00) overlaps WO1's [08:00,10:00) interior
        double = self._schedule(wo3["id"], bay["id"], tech["id"],
                                "2026-08-13T09:00:00Z", "2026-08-13T11:00:00Z")
        validate_error(double, ApiErrorId.ERR_BAY_DOUBLE_BOOKED)

    def test_schedule_windows_clearing_block_and_jobs_succeed(self, api):
        """PRD section 3.7: "a conflict exists exactly when `scheduled_from`
        is at or before the block's `blocked_to` and the block's
        `blocked_from` is at or before `scheduled_to`" — [13:01,14:00) fails
        the first conjunct and is admitted; half-open job windows sharing an
        endpoint do not overlap.

        Design: Difficulty/resource_temporal_overlap/bay_half_open_schedule_vs_closed_maintenance_block
        """
        _, tech, bay, (wo1, _, _, wo4) = self._setup_bay_with_block()
        first = self._schedule(wo1["id"], bay["id"], tech["id"],
                               "2026-08-13T08:00:00Z", "2026-08-13T10:00:00Z")
        assert validate_success(first)["status"] == "SCHEDULED"

        fourth = self._schedule(wo4["id"], bay["id"], tech["id"],
                                "2026-08-13T13:01:00Z", "2026-08-13T14:00:00Z")
        assert validate_success(fourth)["status"] == "SCHEDULED"


class TestBayOccupancy:
    def test_checkin_occupied_bay_rejected(self, api):
        """PRD section 3.7: "Arrival moves `SCHEDULED → IN_SHOP` only while
        the bay is `IDLE`, else `ERR_BAY_OCCUPIED` (HTTP 409); check-in
        cascades the bay `IDLE → OCCUPIED`."

        Design: Corner/errors/error_bay_occupied_on_checkin
        """
        site = create_site("Site R4")
        set_clock(TEST_CLOCK_ISO)
        tech = create_technician(site["id"])
        bay = create_bay(site["id"], 1)
        tech_headers = make_maintenance_tech_headers(tech["id"])

        wo1 = create_work_order(site["id"], "TRK-1", "wo1")
        advance_work_order_to_approved(wo1["id"], tech["id"])
        schedule_work_order(wo1["id"], bay["id"], tech["id"],
                            "2026-08-13T08:00:00Z", "2026-08-13T10:00:00Z")
        validate_success(api.work_order_check_in(wo1["id"], tech_headers))

        wo2 = create_work_order(site["id"], "TRK-2", "wo2")
        advance_work_order_to_approved(wo2["id"], tech["id"])
        schedule_work_order(wo2["id"], bay["id"], tech["id"],
                            "2026-08-13T10:00:00Z", "2026-08-13T12:00:00Z")

        resp = api.work_order_check_in(wo2["id"], tech_headers)
        validate_error(resp, ApiErrorId.ERR_BAY_OCCUPIED)


class TestTechnicianScope:
    def test_technician_cannot_start_others_work_order(self, api):
        """PRD section 2.1: "starting work and issuing or returning parts are
        permitted only on work orders whose `technician_id` equals the
        caller's `X-User-ID`" and "Violations of these entity-backed scoping
        rules are rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD section 3.7: "Starting work moves `IN_SHOP → IN_PROGRESS` and is
        restricted to the assigned technician".

        Design: Corner/rbac/rbac_technician_cannot_start_others_work_order
        """
        site = create_site("Site RB2")
        set_clock(TEST_CLOCK_ISO)
        tech1 = create_technician(site["id"], "Tech One", 12500)
        tech2 = create_technician(site["id"], "Tech Two", 12500)
        bay = create_bay(site["id"], 1)

        wo = create_work_order(site["id"], "TRK-1", "noise")
        advance_work_order_to_approved(wo["id"], tech1["id"], 1.0)
        schedule_work_order(wo["id"], bay["id"], tech1["id"],
                            "2026-08-13T08:00:00Z", "2026-08-13T09:00:00Z")
        validate_success(
            api.work_order_check_in(wo["id"],
                                    make_maintenance_tech_headers(tech1["id"]))
        )

        forbidden = api.work_order_start_work(
            wo["id"], make_maintenance_tech_headers(tech2["id"])
        )
        validate_error(forbidden, ApiErrorId.ERR_FORBIDDEN)

        started = validate_success(
            api.work_order_start_work(
                wo["id"], make_maintenance_tech_headers(tech1["id"])
            )
        )
        assert started["status"] == "IN_PROGRESS"
