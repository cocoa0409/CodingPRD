"""Transitive cascades: color-standard supersede (3 levels), press-booking
completion ledger cascade (3 levels), and job-cancellation cascade."""
from test_helpers import (
    assert_inv_sheets,
    create_approved_press_approval,
    create_booked_press_window,
    get_job,
    make_brand_quality_headers,
    setup_in_production_job,
    setup_press_ready_job,
    validate_success,
    get_success_data,
)
from test_helpers.assertions import assert_board_stock
from test_helpers.fixtures import ADMIN, OPERATOR
from test_helpers.api_client import api_client
from test_helpers.factories import create_color_standard_payload


class TestColorStandardSupersedeCascade:
    def _fixture(self, api, brand_code):
        """PRESS_READY job with an APPROVED approval on the ACTIVE standard S1,
        plus a second PENDING_BRAND standard S2 for the same customer/slot."""
        ctx = setup_press_ready_job(customer_name="Theta", brand_code=brand_code)
        ctx["approval"] = create_approved_press_approval(ctx)
        std2 = get_success_data(api_client.create_color_standard(
            create_color_standard_payload(
                ctx["customer"]["id"], l_target=5400, a_target=6700, b_target=3300,
                tolerance_delta_e_milli=250),
            ADMIN,
        ))
        get_success_data(api_client.submit_color_standard(std2["id"], ADMIN))
        ctx["standard2"] = std2
        return ctx

    def test_supersede_invalidates_pinned_approval(self, api):
        """PRD §3.1: "Approval moves the standard from `PENDING_BRAND` to `ACTIVE` and fires a three-level cascade. First, any other `ACTIVE` standard for the same customer and the same `ink_slot` becomes `SUPERSEDED`, so exactly one active standard governs each customer-and-slot pair. Second, every press approval pinned to a newly superseded standard whose job has not yet reached `IN_PRODUCTION` — that is, whose job is not in `IN_PRODUCTION`, `FINISHING`, `FINISHED`, `COMPLETE`, or `CANCELLED` — becomes `INVALIDATED`, because its measurement was taken against a standard that no longer governs."

        Design: Difficulty/transitive_cascade/color_standard_supersede_cascade
        """
        ctx = self._fixture(api, "THT")
        approve_res = api.approve_color_standard(
            ctx["standard2"]["id"],
            make_brand_quality_headers(ctx["customer"]["id"]),
        )
        std2_after = validate_success(approve_res, 200)
        assert std2_after["status"] == "ACTIVE"

        std1_after = validate_success(
            api.get_color_standard(ctx["standard"]["id"], ADMIN), 200
        )
        assert std1_after["status"] == "SUPERSEDED"

        approval_after = validate_success(
            api.get_press_approval(ctx["approval"]["id"], ADMIN), 200
        )
        assert (
            approval_after["status"] == "INVALIDATED"
        ), "approval pinned to the superseded standard, job not yet IN_PRODUCTION"

    def test_press_ready_job_reverts_and_reservation_releases(self, api):
        """PRD §3.1: "Third, each job sitting in `PRESS_READY` that lost an `APPROVED` press approval to the second level reverts to `ENGINEERING`, and its board reservation is released in full: the stock's `reserved_sheets` decreases by the job's `reserved_sheets`, after which the job's `reserved_sheets` returns to zero and its `board_stock_id` is cleared."

        Design: Difficulty/transitive_cascade/color_standard_supersede_cascade
        """
        ctx = self._fixture(api, "THU")
        assert ctx["job"]["status"] == "PRESS_READY"
        assert ctx["job"]["reserved_sheets"] == 130

        validate_success(
            api.approve_color_standard(
                ctx["standard2"]["id"],
                make_brand_quality_headers(ctx["customer"]["id"]),
            ),
            200,
        )

        job_after = validate_success(api.get_job(ctx["job"]["id"], ADMIN), 200)
        assert job_after["status"] == "ENGINEERING"
        assert job_after["reserved_sheets"] == 0
        assert job_after.get("board_stock_id") is None

        stock_after = validate_success(
            api.get_board_stock(ctx["stock"]["id"], ADMIN), 200
        )
        assert stock_after["reserved_sheets"] == 0
        assert stock_after["available_sheets"] == 5000
        assert_inv_sheets(stock_after)


class TestPressBookingCompletionCascade:
    def _fixture(self, api, brand_code):
        ctx = setup_in_production_job(customer_name="Iota", brand_code=brand_code,
                                      quantity_ordered=5000)
        # The recipe's booking covers the full gross reservation of 216 sheets.
        return ctx

    def test_stock_ledger_settles_first(self, api):
        """PRD §3.5: "First, the stock ledger settles: the stock's `consumed_sheets` increases by `sheets_printed`, while both the stock's `reserved_sheets` and the job's `reserved_sheets` decrease by the smaller of `sheets_printed` and the job's remaining reservation — so an over-print consumes unreserved availability without driving reservations negative, and INV-SHEETS holds."
        PRD §2.7: "Sheet inventory obeys a strict conservation law, designated INV-SHEETS: for every `BoardStock`, at all times, `received_sheets` equals the sum of `available_sheets`, `reserved_sheets`, and `consumed_sheets`."

        Design: Difficulty/transitive_cascade/press_booking_completion_cascade
        """
        ctx = self._fixture(api, "IOT")
        validate_success(
            api.complete_press_booking(
                ctx["booking"]["id"],
                {"sheets_printed": 216, "sheets_good": 200},
                OPERATOR,
            ),
            200,
        )
        stock = validate_success(api.get_board_stock(ctx["stock"]["id"], ADMIN), 200)
        assert stock["consumed_sheets"] == 216
        assert stock["reserved_sheets"] == 0  # min(216, reserved 216) released
        assert stock["available_sheets"] == 4784
        assert_board_stock(stock)

    def test_job_actuals_and_locked_plan_realized_fields_refresh(self, api):
        """PRD §3.5: "Second, the job's actuals accumulate: `sheets_consumed_actual` increases by `sheets_printed`, `good_sheets_actual` increases by `sheets_good`, and `good_cartons_actual` is recomputed as `good_sheets_actual` times the job's `locked_ups`. Third, the job's `LOCKED` imposition plan absorbs the realized picture: `realized_sheets_printed` takes the job's `sheets_consumed_actual`, `realized_good_sheets` takes the job's `good_sheets_actual`, and `realized_waste_milli_pct` is recomputed as the difference between printed and good sheets, multiplied by 100000 and floor-divided by the printed sheets — remaining null while no sheets have been printed."

        Design: Difficulty/transitive_cascade/press_booking_completion_cascade
        """
        ctx = self._fixture(api, "IOB")
        validate_success(
            api.complete_press_booking(
                ctx["booking"]["id"],
                {"sheets_printed": 216, "sheets_good": 200},
                OPERATOR,
            ),
            200,
        )
        job = validate_success(api.get_job(ctx["job"]["id"], ADMIN), 200)
        assert job["sheets_consumed_actual"] == 216
        assert job["good_sheets_actual"] == 200
        assert job["good_cartons_actual"] == 5000  # 200 * locked_ups 25

        plan = validate_success(api.get_imposition_plan(ctx["plan"]["id"], ADMIN), 200)
        assert plan["realized_sheets_printed"] == 216
        assert plan["realized_good_sheets"] == 200
        # floor((216 - 200) * 100000 / 216) == 7407
        assert plan["realized_waste_milli_pct"] == 7407


def test_job_cancel_cascades_to_scheduled_booking(api):
    """PRD §3.2: "A `PlantAdmin` may also cancel a job outright while it is in `QUOTED`, `ENGINEERING`, or `PRESS_READY`; cancellation releases the job's board reservation if one exists — the stock's `reserved_sheets` decreases by the job's remaining reservation — and, as a second-level effect of that job mutation, every `SCHEDULED` press booking and finishing booking belonging to the job is cancelled with it. `CANCELLED` is terminal."

    Design: Corner/state_machines/job_cancel_cascades_to_scheduled_booking
    """
    ctx = setup_press_ready_job(customer_name="Acme", brand_code="ACM")
    booking = create_booked_press_window(ctx)

    cancelled = validate_success(api.cancel_job(ctx["job"]["id"], ADMIN), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["reserved_sheets"] == 0

    booking_after = validate_success(api.get_press_booking(booking["id"], ADMIN), 200)
    assert booking_after["status"] == "CANCELLED"

    stock_after = validate_success(api.get_board_stock(ctx["stock"]["id"], ADMIN), 200)
    assert stock_after["reserved_sheets"] == 0
    assert stock_after["available_sheets"] == 5000
    assert_inv_sheets(stock_after)
