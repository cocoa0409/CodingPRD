"""Plan approval, release to the plant, and the two independent status dimensions.

PRD §2.8 keeps the commercial and production dimensions of a store plan separate:
a compliance hold never rewinds production, and production never clears a hold.
"""

import pytest

from test_helpers import *  # noqa: F401,F403


class TestApprovalAndRelease:
    """PRD §3.6 and §3.7 — the credit ceiling, then one work order per case."""

    def test_01_plan_approval_above_the_credit_limit_is_rejected(self, api):
        """A 1111328 cent plan cannot be approved against a 1000000 cent ceiling.

        PRD §3.6: "At rank 39 — the last rule in the whole ladder — `total_cents`
        must be at or below `credit_limit_cents`, else
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        Design: Corner/validations/plan_approval_above_credit_limit_rejected
        """
        ctx = setup_priced_plan(plan_overrides={"credit_limit_cents": 1000000})
        assert ctx["store_plan"]["total_cents"] == 1111328

        response = api.approve_store_plan(
            ctx["store_plan"]["id"], TEST_USERS["sales_engineer_alt_headers"]
        )
        validate_error(response, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)

        plan = refresh_store_plan(ctx)
        assert plan["commercial_status"] == "PRICED"
        assert plan["total_cents"] == 1111328
        assert plan.get("approved_by_user_id") is None

    def test_02_release_creates_one_work_order_per_ordered_case(self, api):
        """Two ordered cases become two QUEUED units at the pinned unit price.

        PRD §3.7: "One work order is created per physical case: for each line, as
        many rows as its `quantity`, generated line by line in `created_at`
        ascending order across the plan's lines and, within each line, in
        ascending `unit_sequence` order."

        Design: Corner/endpoints/plan_release_creates_one_work_order_per_unit
        """
        ctx = setup_approved_plan(line_overrides={"quantity": 2})

        released = validate_success(
            api.release_store_plan(
                ctx["store_plan"]["id"], TEST_USERS["plant_supervisor_headers"]
            )
        )
        assert released["production_status"] == "IN_PRODUCTION"
        assert released["units_completed_count"] == 0
        assert released["warranty_reserve_accrual_cents"] == 57392

        units, meta = validate_paginated(
            api.list_work_orders(
                TEST_USERS["plant_supervisor_headers"],
                params={"store_plan_line_id": ctx["store_plan_line"]["id"]},
            )
        )
        assert meta["total_count"] == 2
        assert [unit["unit_sequence"] for unit in units] == [1, 2]
        for unit in units:
            assert_work_order(unit)
            assert unit["status"] == "QUEUED"
            assert unit["unit_price_cents"] == 1043500

    def test_03_warranty_accrual_rounds_each_unit_before_summing(self, api):
        """Four units at 27913 cents each accrue 111652, not 111650.

        PRD §3.7: "with each work order's contribution rounded half up to whole
        cents **before** the summation."

        Design: Corner/calculations/warranty_accrual_rounds_per_work_order_before_summing
        """
        ctx = setup_approved_plan(
            line_overrides={
                "quantity": 4,
                "end_cap": "LEFT",
                "merchandising_options": ["LED_CANOPY"],
            }
        )

        released = validate_success(
            api.release_store_plan(
                ctx["store_plan"]["id"], TEST_USERS["plant_supervisor_headers"]
            )
        )
        assert released["production_status"] == "IN_PRODUCTION"
        assert released["warranty_reserve_accrual_cents"] == 111652
        assert released["warranty_reserve_incurred_cents"] == 0

        units = refresh_work_orders(ctx)
        assert len(units) == 4
        assert [unit["unit_sequence"] for unit in units] == [1, 2, 3, 4]
        for unit in units:
            assert unit["status"] == "QUEUED"
            assert unit["unit_price_cents"] == 1015000


class TestCommercialHoldVersusProduction:
    """PRD §2.8 — the two dimensions move independently, in both directions."""

    def test_04_label_revocation_holds_the_plan_without_rewinding_production(
        self, api
    ):
        """The plan enters HOLD_PENDING_RECERT while production stays IN_PRODUCTION.

        PRD §2.8: "the two lifecycle dimensions of a store plan are genuinely
        independent — a commercial hold never rewinds production, and production
        progress never clears a commercial hold"

        Design: Difficulty/non_linear_state_machine/store_plan_commercial_hold_does_not_rewind_production_dimension
        """
        ctx = setup_released_plan()
        assert ctx["store_plan"]["production_status"] == "IN_PRODUCTION"
        assert len(ctx["work_orders"]) == 1
        assert ctx["work_orders"][0]["status"] == "QUEUED"

        validate_success(
            revoke_label(
                ctx,
                revocation_reason="DOE verification sample exceeded the rated index",
            )
        )

        label = refresh_compliance_label(ctx)
        assert label["label_status"] == "REVOKED"
        assert refresh_case_model(ctx)["status"] == "DECERTIFIED"

        line = validate_success(
            api.get_store_plan_line(
                ctx["store_plan_line"]["id"], TEST_USERS["sales_engineer_headers"]
            )
        )
        assert line["compliance_hold"] is True

        plan = refresh_store_plan(ctx)
        assert plan["held_line_count"] == 1
        assert plan["commercial_status"] == "HOLD_PENDING_RECERT"
        assert plan["production_status"] == "IN_PRODUCTION", (
            "the production dimension is untouched by the commercial hold"
        )

        units = refresh_work_orders(ctx)
        assert units[0]["status"] == "HELD"

    def test_05_recertification_unwinds_the_hold_without_moving_production(self, api):
        """A fresh label returns the plan to APPROVED and the unit to QUEUED.

        PRD §3.4: "For any such plan whose `commercial_status` is
        `HOLD_PENDING_RECERT` and whose `held_line_count` has now reached zero,
        the plan moves `HOLD_PENDING_RECERT → APPROVED`, and every work order of
        that plan sitting in `HELD` moves `HELD → QUEUED`."

        Design: Difficulty/non_linear_state_machine/store_plan_commercial_hold_does_not_rewind_production_dimension
        """
        ctx = setup_released_plan()
        validate_success(
            revoke_label(
                ctx,
                revocation_reason="DOE verification sample exceeded the rated index",
            )
        )
        assert refresh_store_plan(ctx)["commercial_status"] == "HOLD_PENDING_RECERT"

        validate_success(
            open_engineering_change(
                ctx,
                refrigerant_id=ctx["refrigerant"]["id"],
                charge_grams=3900,
                line_set_length_ft=120,
                change_note="Recharge and re-verify after the revoked label",
            )
        )
        validate_success(
            api.run_airflow_model(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )
        validate_success(
            api.submit_case_model_for_test(
                ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
            )
        )
        refresh_case_model(ctx)
        ctx["energy_test"] = validate_success(
            schedule_energy_test(ctx), expected_status=201
        )
        validate_success(
            api.start_energy_test(
                ctx["energy_test"]["id"], TEST_USERS["test_lab_technician_headers"]
            )
        )
        ctx["energy_test"] = validate_success(
            api.complete_energy_test(
                ctx["energy_test"]["id"],
                complete_energy_test_payload(),
                TEST_USERS["test_lab_technician_headers"],
            )
        )
        assert ctx["energy_test"]["status"] == "COMPLETED_PASS"

        fresh_label = validate_success(
            api.create_compliance_label(
                create_compliance_label_payload(
                    ctx["case_model"]["id"],
                    ctx["energy_test"]["id"],
                    label_code="LBL-MT-8-B",
                ),
                TEST_USERS["compliance_officer_headers"],
            ),
            expected_status=201,
        )
        assert fresh_label["pinned_design_revision"] == 2

        line = validate_success(
            api.get_store_plan_line(
                ctx["store_plan_line"]["id"], TEST_USERS["sales_engineer_headers"]
            )
        )
        assert line["compliance_hold"] is False

        plan = refresh_store_plan(ctx)
        assert plan["held_line_count"] == 0
        assert plan["commercial_status"] == "APPROVED"
        assert plan["production_status"] == "IN_PRODUCTION", (
            "recovery from the hold never moves the production dimension either"
        )

        units = refresh_work_orders(ctx)
        assert units[0]["status"] == "QUEUED"


class TestEngineeringChangeCascade:
    """PRD §3.5 — one request walks design, label, line, plan and work order."""

    def test_06_engineering_change_cascades_five_hops_to_the_work_order(self, api):
        """A refrigerant transition freezes the plant queue in the same request.

        PRD §3.5: "**Hop 5 — queued production.** Because the plan entered
        `HOLD_PENDING_RECERT`, every work order of that plan whose status is
        `QUEUED` moves `QUEUED → HELD`."

        Design: Difficulty/transitive_cascade/engineering_change_five_hop_design_to_work_order_cascade
        """
        ctx = setup_released_plan()
        low_gwp = seed_low_gwp_refrigerant(max_charge_grams=4000)

        changed = validate_success(
            open_engineering_change(
                ctx,
                refrigerant_id=low_gwp["id"],
                charge_grams=3600,
                line_set_length_ft=120,
                change_note="R-454C transition mandated for the 2027 GWP step-down",
            )
        )
        assert changed["design_revision"] == 2
        assert changed["status"] == "DRAFT"

        assert refresh_compliance_label(ctx)["label_status"] == "SUPERSEDED"

        line = validate_success(
            api.get_store_plan_line(
                ctx["store_plan_line"]["id"], TEST_USERS["sales_engineer_headers"]
            )
        )
        assert line["compliance_hold"] is True

        plan = refresh_store_plan(ctx)
        assert plan["held_line_count"] == 1
        assert plan["commercial_status"] == "HOLD_PENDING_RECERT"
        assert plan["production_status"] == "IN_PRODUCTION"

        units = refresh_work_orders(ctx)
        assert units[0]["status"] == "HELD"

    def test_07_the_cascade_freezes_only_the_queue_not_units_in_fabrication(self, api):
        """A unit already in sheet metal keeps its place while its peer is held.

        PRD §3.7: "Work orders already in fabrication, in final QA, complete,
        shipped or scrapped are untouched; only the queue is frozen."

        Design: Difficulty/transitive_cascade/engineering_change_five_hop_design_to_work_order_cascade
        """
        ctx = setup_released_plan(line_overrides={"quantity": 2})
        first, second = ctx["work_orders"]
        advanced = validate_success(
            api.advance_work_order(first["id"], TEST_USERS["plant_supervisor_headers"])
        )
        assert advanced["status"] == "SHEET_METAL"
        assert second["status"] == "QUEUED"

        low_gwp = seed_low_gwp_refrigerant(max_charge_grams=4000)
        validate_success(
            open_engineering_change(
                ctx,
                refrigerant_id=low_gwp["id"],
                charge_grams=3600,
                line_set_length_ft=120,
                change_note="R-454C transition mandated for the 2027 GWP step-down",
            )
        )

        units = {unit["id"]: unit for unit in refresh_work_orders(ctx)}
        assert units[first["id"]]["status"] == "SHEET_METAL", (
            "a unit already in fabrication is untouched by hop 5"
        )
        assert units[second["id"]]["status"] == "HELD"

        plan = refresh_store_plan(ctx)
        assert plan["commercial_status"] == "HOLD_PENDING_RECERT"
        assert plan["production_status"] == "IN_PRODUCTION"
        assert plan["held_line_count"] == 1
