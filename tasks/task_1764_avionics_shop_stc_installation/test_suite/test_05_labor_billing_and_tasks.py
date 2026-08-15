"""Install labor: task validation, tiered billing at verify, and void compensation."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_install_task_payload,
    get_install_task,
    get_work_order,
    setup_installation_work_order,
    setup_pending_approval,
    validate_error,
    validate_success,
    verify_task,
    work_task_to_completed,
)

MANAGER = TEST_USERS["shop_manager_headers"]


class TestQuoteVsActualLaborVariants:
    def test_quote_labor_is_flat_rate(self, api):
        """PRD §3.2: "Its labor component is the work order's `quoted_labor_hours` times the shop rate of 14,500 cents per hour, rounded half-up to whole cents."
        PRD §3.4: "This actual-variant billing deliberately differs from the estimated labor figure inside a quote, which is a flat `quoted_labor_hours` times the shop rate with no overtime tier and no task-kind multiplier, so identical hour counts produce different totals under the two variants."

        Design: Difficulty/dual_variant_calc/labor_quote_flat_vs_billed_tiered
        """
        bundle = setup_pending_approval(
            customer_name="Lab Owner", customer_email="lab@x.com",
            equipment_list=[], layout_notes="labor only",
            work_order_overrides={"quoted_labor_hours": 10})
        # Flat estimate variant: 10.0 h * 14500 = 145000, no tier, no multiplier.
        assert bundle["work_order"]["quoted_total_cents"] == 145000, (
            f"expected flat quoted labor 145000, got "
            f"{bundle['work_order']['quoted_total_cents']}")
        assert bundle["work_order"]["status"] == "PENDING_APPROVAL"

    def test_verified_billing_uses_tiered_actual_variant(self, api):
        """PRD §3.4: "The first 8 hours of a task's `actual_hours` bill as regular time, and any hours beyond 8 bill at one and a half times. The payable hours are multiplied by the shop rate of 14,500 cents per hour and by the task-kind multiplier — 1.0 for `HARNESS_FABRICATION`, 1.1 for `PANEL_ASSEMBLY`, and 1.25 for `INSTALLATION` — and the product is rounded half-up to whole cents."
        PRD §3.4: "A successful verification moves the task from `COMPLETED` to `VERIFIED`, records `verified_by_user_id`, computes `billed_labor_cents`, and recomputes the parent's `total_billed_labor_cents` and `tasks_unverified_count`."

        Design: Difficulty/dual_variant_calc/labor_quote_flat_vs_billed_tiered
        """
        bundle = setup_installation_work_order(
            customer_name="Lab Owner", customer_email="lab@x.com",
            equipment_list=[], layout_notes="labor only",
            work_order_overrides={"quoted_labor_hours": 10})
        task = work_task_to_completed(bundle["work_order"]["id"],
                                      task_kind="INSTALLATION",
                                      estimated_hours=10.0, actual_hours=10.0,
                                      technician_id="tech-1")
        verified = verify_task(task["id"], inspector_id="insp-1")
        # Actual variant: (8 + 2*1.5) * 14500 * 1.25 = 199375.
        assert verified["billed_labor_cents"] == 199375, (
            f"expected tiered billing 199375, got {verified['billed_labor_cents']}")
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "insp-1"
        work_order = get_work_order(bundle["work_order"]["id"])
        assert work_order["total_billed_labor_cents"] == 199375
        assert work_order["quoted_total_cents"] == 145000, (
            "the flat quote figure stays put while actual billing tiers up")
        assert verified["billed_labor_cents"] != work_order["quoted_total_cents"], (
            "identical hour counts produce different totals under the two variants")


class TestOvertimeAndKindMultiplier:
    def test_installation_kind_bills_overtime_with_multiplier(self, api):
        """PRD §3.4: "The first 8 hours of a task's `actual_hours` bill as regular time, and any hours beyond 8 bill at one and a half times. The payable hours are multiplied by the shop rate of 14,500 cents per hour and by the task-kind multiplier — 1.0 for `HARNESS_FABRICATION`, 1.1 for `PANEL_ASSEMBLY`, and 1.25 for `INSTALLATION` — and the product is rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/labor_billing_overtime_and_kind_multiplier
        """
        bundle = setup_installation_work_order(
            customer_name="Tier Owner", customer_email="tier@x.com",
            equipment_list=[], layout_notes="labor only",
            work_order_overrides={"quoted_labor_hours": 24})
        task = work_task_to_completed(bundle["work_order"]["id"],
                                      task_kind="INSTALLATION",
                                      estimated_hours=12.0, actual_hours=12.0,
                                      technician_id="tech-1")
        verified = verify_task(task["id"], inspector_id="insp-1")
        # (min(12,8) + max(0,12-8)*1.5) * 14500 * 1.25 = 14 * 14500 * 1.25.
        assert verified["billed_labor_cents"] == 253750, (
            f"expected 253750 for 12.0 h INSTALLATION, got "
            f"{verified['billed_labor_cents']}")

    def test_harness_kind_bills_overtime_without_multiplier(self, api):
        """PRD §3.4: "The first 8 hours of a task's `actual_hours` bill as regular time, and any hours beyond 8 bill at one and a half times. The payable hours are multiplied by the shop rate of 14,500 cents per hour and by the task-kind multiplier — 1.0 for `HARNESS_FABRICATION`, 1.1 for `PANEL_ASSEMBLY`, and 1.25 for `INSTALLATION` — and the product is rounded half-up to whole cents."
        PRD §2.9: "`total_billed_labor_cents` sums `billed_labor_cents` over its install tasks in `VERIFIED` only."

        Design: Difficulty/combinatorial_formula/labor_billing_overtime_and_kind_multiplier
        """
        bundle = setup_installation_work_order(
            customer_name="Tier Owner", customer_email="tier@x.com",
            equipment_list=[], layout_notes="labor only",
            work_order_overrides={"quoted_labor_hours": 24})
        installation_task = work_task_to_completed(
            bundle["work_order"]["id"], task_kind="INSTALLATION",
            estimated_hours=12.0, actual_hours=12.0, technician_id="tech-1")
        harness_task = work_task_to_completed(
            bundle["work_order"]["id"], task_kind="HARNESS_FABRICATION",
            estimated_hours=12.0, actual_hours=12.0, technician_id="tech-2")
        verified_inst = verify_task(installation_task["id"], inspector_id="insp-1")
        verified_harness = verify_task(harness_task["id"], inspector_id="insp-1")
        # 14 payable hours * 14500 * 1.0 = 203000.
        assert verified_harness["billed_labor_cents"] == 203000, (
            f"expected 203000 for 12.0 h HARNESS_FABRICATION, got "
            f"{verified_harness['billed_labor_cents']}")
        work_order = get_work_order(bundle["work_order"]["id"])
        assert work_order["total_billed_labor_cents"] == 456750, (
            f"253750 + 203000 must roll up to 456750, got "
            f"{work_order['total_billed_labor_cents']}")


class TestRegularHourCap:
    def test_exactly_eight_hours_stays_regular(self, api):
        """PRD §3.4: "The first 8 hours of a task's `actual_hours` bill as regular time, and any hours beyond 8 bill at one and a half times."
        PRD §3.4: "Rounding happens once, per task, at verify time; the work-order aggregate `total_billed_labor_cents` sums these per-task figures over `VERIFIED` tasks and is never re-rounded."

        Design: Corner/calculations/labor_billing_regular_cap_boundary
        """
        bundle = setup_installation_work_order(
            customer_name="Cap Carl", customer_email="c3@x.com",
            equipment_list=[], work_order_overrides={"quoted_labor_hours": 8})
        task = work_task_to_completed(bundle["work_order"]["id"],
                                      task_kind="INSTALLATION",
                                      estimated_hours=8.0, actual_hours=8.0,
                                      technician_id="tech-1")
        verified = verify_task(task["id"], inspector_id="insp-1")
        # Exactly at the cap: 8 * 14500 * 1.25 = 145000, overtime tier untouched.
        assert verified["billed_labor_cents"] == 145000, (
            f"expected 145000 at exactly the 8-hour cap, got "
            f"{verified['billed_labor_cents']}")


class TestVoidRestoresLaborTotals:
    def test_void_removes_completed_hours_from_total(self, api):
        """PRD §3.4: "A task that should never have been worked can be voided by a `ShopManager` from `PLANNED`, `IN_PROGRESS`, or `COMPLETED`, moving it to the terminal `VOIDED` state and recomputing the parent's derived fields; voiding a `COMPLETED` task removes its `actual_hours` from the work order's labor-hour sum."
        PRD §2.9: "`total_actual_labor_hours` sums `actual_hours` over its install tasks in `COMPLETED` or `VERIFIED`."

        Design: Difficulty/compensating_invariant/labor_hours_restored_by_void
        """
        bundle = setup_installation_work_order(
            customer_name="Inv Owner", customer_email="inv@x.com",
            equipment_list=[], work_order_overrides={"quoted_labor_hours": 10})
        work_task_to_completed(bundle["work_order"]["id"],
                               task_kind="HARNESS_FABRICATION",
                               estimated_hours=6.0, actual_hours=6.0,
                               technician_id="tech-1")
        task2 = work_task_to_completed(bundle["work_order"]["id"],
                                       task_kind="INSTALLATION",
                                       estimated_hours=4.0, actual_hours=4.0,
                                       technician_id="tech-2")
        before = get_work_order(bundle["work_order"]["id"])
        assert before["total_actual_labor_hours"] == pytest.approx(10.0), (
            f"6.0 + 4.0 must total 10.0, got {before['total_actual_labor_hours']}")

        voided = validate_success(api.void_task(task2["id"], MANAGER))
        assert voided["status"] == "VOIDED"
        after = get_work_order(bundle["work_order"]["id"])
        assert after["total_actual_labor_hours"] == pytest.approx(6.0), (
            "the complete+void pair leaves the labor-hour total unchanged at 6.0, "
            f"got {after['total_actual_labor_hours']}")

    def test_void_recomputes_unverified_count(self, api):
        """PRD §2.9: "`tasks_unverified_count` counts its install tasks in `PLANNED`, `IN_PROGRESS`, or `COMPLETED`."
        PRD §2.9: "`VOIDED` tasks and `CANCELLED` or `RECEIVED` orders contribute nothing to these figures."

        Design: Difficulty/compensating_invariant/labor_hours_restored_by_void
        """
        bundle = setup_installation_work_order(
            customer_name="Inv Owner", customer_email="inv@x.com",
            equipment_list=[], work_order_overrides={"quoted_labor_hours": 10})
        task1 = work_task_to_completed(bundle["work_order"]["id"],
                                       task_kind="HARNESS_FABRICATION",
                                       estimated_hours=6.0, actual_hours=6.0,
                                       technician_id="tech-1")
        task2 = work_task_to_completed(bundle["work_order"]["id"],
                                       task_kind="INSTALLATION",
                                       estimated_hours=4.0, actual_hours=4.0,
                                       technician_id="tech-2")
        assert get_work_order(bundle["work_order"]["id"])["tasks_unverified_count"] == 2
        validate_success(api.void_task(task2["id"], MANAGER))
        after = get_work_order(bundle["work_order"]["id"])
        assert after["tasks_unverified_count"] == 1, (
            f"only the surviving COMPLETED task counts, got "
            f"{after['tasks_unverified_count']}")
        assert get_install_task(task1["id"])["status"] == "COMPLETED"


class TestTaskKindValidation:
    def test_task_kind_outside_enum_rejected(self, api):
        """PRD §3.4: "A `ShopManager` adds a task with `work_order_id`, a `task_kind` of `HARNESS_FABRICATION`, `PANEL_ASSEMBLY`, or `INSTALLATION`, a `description`, and a positive `estimated_hours`."
        PRD §2.11: "Third come request-body schema checks: required fields present, types valid, enum values in range, `quantity` at least 1, `unit_price_cents` greater than 0, `estimated_hours` greater than 0, `lead_time_days` zero or more, every time window ending after it begins, `removed_arm_in` present exactly when `removed_weight_lb` is greater than zero, and `stc_number` present exactly when `approval_path` is `STC`; the `stc_number` condition carries `ERR_STC_NUMBER_REQUIRED`, and the rest carry `ERR_VALIDATION`."

        Design: Corner/entities/install_task_create_invalid_enum_rejected
        """
        bundle = setup_installation_work_order(customer_name="Enum Erin",
                                               customer_email="e@x.com",
                                               equipment_list=[])
        response = api.create_install_task(
            create_install_task_payload(bundle["work_order"]["id"],
                                        task_kind="AVIONICS_MAGIC",
                                        description="bad kind",
                                        estimated_hours=1.0),
            MANAGER)
        validate_error(response, ApiErrorId.ERR_VALIDATION)
