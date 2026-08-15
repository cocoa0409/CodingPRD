"""Scale-up trials: the pilot plant, the formula revision loop, touch-allowed
booking, and capacity limits (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_customer,
    create_formula,
    create_pilot_cell,
    create_scale_up_trial_payload,
    get_formula,
    record_trial_results,
    schedule_trial,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]


class TestTrialFailureRevisionLoop:

    def test_trial_failure_loops_formula_back_to_draft(self):
        """PRD §3.2: "A failing trial moves to `FAILED` and sends the formula back from `IN_TRIAL` to `DRAFT`, opening the revision loop: adjust the recipe in `DRAFT`, then trial again."

        Design: Difficulty/non_linear_state_machine/formula_trial_failure_revision_loop
        """
        customer = create_customer()
        formula = create_formula(customer["id"])
        cell = create_pilot_cell()
        trial = schedule_trial(formula["id"], cell["id"])
        record_trial_results(trial["id"], passed=False, yield_units=0)

        trial_after = validate_success(
            api_client.get_scale_up_trial(trial["id"], OPS), expected_status=200
        )
        assert trial_after["status"] == "FAILED"
        formula_after = get_formula(formula["id"])
        assert formula_after["status"] == "DRAFT", (
            f"failed trial must loop formula back to DRAFT, got "
            f"{formula_after['status']}"
        )

    def test_revision_untouched_by_failure_loop_and_retrial_passes(self):
        """PRD §3.1: "A formula is born in `DRAFT` status with `revision` 1."
        PRD §3.3: "The formula returns to `DRAFT`, its `revision` increments by one, and its `version` advances."
        PRD §3.2: "A passing trial moves to `PASSED`, its `yield_units` is recorded, and the formula advances out of `IN_TRIAL` — to `TRIAL_PASSED` for `ACIDIFIED` and `LOW_ACID` products, or directly to `APPROVED` for `ACID` products, which are letter-exempt and need no further regulatory step."

        Design: Difficulty/non_linear_state_machine/formula_trial_failure_revision_loop
        """
        customer = create_customer()
        formula = create_formula(customer["id"])
        cell = create_pilot_cell()
        trial1 = schedule_trial(formula["id"], cell["id"])
        record_trial_results(trial1["id"], passed=False, yield_units=0)
        mid = get_formula(formula["id"])
        assert mid["status"] == "DRAFT"
        assert mid["revision"] == 1, (
            f"revision changes only on reformulate, not on trial failure; "
            f"got {mid['revision']}"
        )

        trial2 = schedule_trial(
            formula["id"],
            cell["id"],
            scheduled_start="2026-09-02T08:00:00Z",
            scheduled_end="2026-09-02T12:00:00Z",
        )
        record_trial_results(trial2["id"], passed=True, yield_units=450)
        trial2_after = validate_success(
            api_client.get_scale_up_trial(trial2["id"], OPS), expected_status=200
        )
        assert trial2_after["status"] == "PASSED"
        final = get_formula(formula["id"])
        assert final["status"] == "TRIAL_PASSED", (
            f"ACIDIFIED formula must be TRIAL_PASSED after a passing retrial, "
            f"got {final['status']}"
        )
        assert final["revision"] == 1


class TestTrialTerminalStates:

    def test_trial_record_results_twice_rejected(self):
        """PRD §3.2: "The trial must still be `SCHEDULED`; recording results against a trial in any other status is rejected with `ERR_TRIAL_NOT_SCHEDULED`."

        Design: Corner/state_machines/trial_record_results_twice_rejected
        """
        customer = create_customer()
        formula = create_formula(customer["id"])
        cell = create_pilot_cell()
        trial = schedule_trial(formula["id"], cell["id"])
        record_trial_results(trial["id"], passed=True, yield_units=480)

        resp = api_client.record_trial_results(
            trial["id"], {"passed": True, "yield_units": 480}, OPS
        )
        validate_error(resp, ApiErrorId.ERR_TRIAL_NOT_SCHEDULED)
        after = validate_success(
            api_client.get_scale_up_trial(trial["id"], OPS), expected_status=200
        )
        assert after["status"] == "PASSED"

    def test_trial_cancel_returns_formula_to_draft(self):
        """PRD §3.2: "Cancelling a trial follows the same discipline — only a `SCHEDULED` trial may be cancelled (`ERR_TRIAL_NOT_SCHEDULED`), the trial becomes `CANCELLED`, and its formula likewise returns from `IN_TRIAL` to `DRAFT`."

        Design: Corner/state_machines/trial_cancel_returns_formula_to_draft
        """
        from test_helpers import cancel_trial

        customer = create_customer()
        formula = create_formula(customer["id"])
        cell = create_pilot_cell()
        trial = schedule_trial(formula["id"], cell["id"])

        cancelled = cancel_trial(trial["id"])
        assert cancelled["status"] == "CANCELLED"
        formula_after = get_formula(formula["id"])
        assert formula_after["status"] == "DRAFT", (
            f"cancelling the trial must return the formula to DRAFT, got "
            f"{formula_after['status']}"
        )


class TestAcidAutoApproval:

    def test_acid_formula_auto_approved_on_trial_pass(self):
        """PRD §3.2: "A passing trial moves to `PASSED`, its `yield_units` is recorded, and the formula advances out of `IN_TRIAL` — to `TRIAL_PASSED` for `ACIDIFIED` and `LOW_ACID` products, or directly to `APPROVED` for `ACID` products, which are letter-exempt and need no further regulatory step."

        Design: Corner/state_machines/acid_formula_auto_approves_on_trial_pass
        """
        customer = create_customer()
        formula = create_formula(
            customer["id"],
            product_name="Vinegar Hot Sauce",
            sku_code="VH-001",
            process_category="ACID",
            min_run_units=100,
            unit_rate_cents=100,
        )
        cell = create_pilot_cell()
        trial = schedule_trial(
            formula["id"],
            cell["id"],
            batch_size_units=100,
            scheduled_start="2026-09-01T08:00:00Z",
            scheduled_end="2026-09-01T10:00:00Z",
        )
        record_trial_results(trial["id"], passed=True, yield_units=95)

        trial_after = validate_success(
            api_client.get_scale_up_trial(trial["id"], OPS), expected_status=200
        )
        assert trial_after["status"] == "PASSED"
        formula_after = get_formula(formula["id"])
        assert formula_after["status"] == "APPROVED", (
            f"ACID formula is letter-exempt and must auto-approve, got "
            f"{formula_after['status']}"
        )


class TestPilotCellConstraints:

    def test_trial_batch_exceeding_cell_capacity_rejected(self):
        """PRD §3.2: "A batch larger than the cell's `max_batch_units` is refused with `ERR_BATCH_EXCEEDS_CAPACITY`."

        Design: Corner/validations/trial_batch_exceeds_capacity_rejected
        """
        customer = create_customer()
        formula = create_formula(customer["id"])
        cell = create_pilot_cell()

        resp = api_client.create_scale_up_trial(
            create_scale_up_trial_payload(
                formula["id"], cell["id"], batch_size_units=6000
            ),
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_BATCH_EXCEEDS_CAPACITY)
        formula_after = get_formula(formula["id"])
        assert formula_after["status"] == "DRAFT", (
            f"rejected trial must not move the formula, got "
            f"{formula_after['status']}"
        )

    def test_pilot_cell_touching_window_booking_allowed(self):
        """PRD §3.2: "Pilot cells enforce a zero-buffer touch-allowed booking rule: only `SCHEDULED` trials occupy a cell, and a new window that merely touches an occupying window — one's `scheduled_end` exactly equal to the other's `scheduled_start` — is permitted, while any genuine overlap is rejected with `ERR_PILOT_CELL_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/pilot_cell_touch_allowed_booking
        """
        customer = create_customer()
        formula_a = create_formula(
            customer["id"], product_name="Sauce A", sku_code="SA-001"
        )
        formula_b = create_formula(
            customer["id"],
            product_name="Sauce B",
            sku_code="SB-001",
            process_category="ACID",
            allergen_class="SOY",
            min_run_units=100,
            unit_rate_cents=100,
        )
        cell = create_pilot_cell()
        schedule_trial(
            formula_a["id"],
            cell["id"],
            batch_size_units=100,
            scheduled_start="2026-09-01T08:00:00Z",
            scheduled_end="2026-09-01T12:00:00Z",
        )

        touch = api_client.create_scale_up_trial(
            create_scale_up_trial_payload(
                formula_b["id"],
                cell["id"],
                batch_size_units=100,
                scheduled_start="2026-09-01T12:00:00Z",
                scheduled_end="2026-09-01T16:00:00Z",
            ),
            OPS,
        )
        trial_b = validate_success(touch, expected_status=201)
        assert trial_b["status"] == "SCHEDULED", (
            "touching window (12:00 == 12:00) must be permitted under "
            "half-open zero-buffer semantics"
        )
        formula_b_after = get_formula(formula_b["id"])
        assert formula_b_after["status"] == "IN_TRIAL"

    def test_pilot_cell_overlapping_window_rejected(self):
        """PRD §3.2: "Pilot cells enforce a zero-buffer touch-allowed booking rule: only `SCHEDULED` trials occupy a cell, and a new window that merely touches an occupying window — one's `scheduled_end` exactly equal to the other's `scheduled_start` — is permitted, while any genuine overlap is rejected with `ERR_PILOT_CELL_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/pilot_cell_touch_allowed_booking
        """
        customer = create_customer()
        formula_a = create_formula(
            customer["id"], product_name="Sauce A", sku_code="SA-001"
        )
        formula_c = create_formula(
            customer["id"],
            product_name="Sauce C",
            sku_code="SC-001",
            process_category="ACID",
            allergen_class="SOY",
            min_run_units=100,
            unit_rate_cents=100,
        )
        cell = create_pilot_cell()
        schedule_trial(
            formula_a["id"],
            cell["id"],
            batch_size_units=100,
            scheduled_start="2026-09-01T08:00:00Z",
            scheduled_end="2026-09-01T12:00:00Z",
        )

        overlap = api_client.create_scale_up_trial(
            create_scale_up_trial_payload(
                formula_c["id"],
                cell["id"],
                batch_size_units=100,
                scheduled_start="2026-09-01T11:00:00Z",
                scheduled_end="2026-09-01T13:00:00Z",
            ),
            OPS,
        )
        validate_error(overlap, ApiErrorId.ERR_PILOT_CELL_CONFLICT)
        formula_c_after = get_formula(formula_c["id"])
        assert formula_c_after["status"] == "DRAFT", (
            f"rejected trial create must leave the formula DRAFT, got "
            f"{formula_c_after['status']}"
        )
