"""Corner coverage: treatment log lifecycle (flag/amend with
restore-then-subtract) and the clinical review cadence/sign-off/escalation
battery."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, get_success_data,
    create_active_home_patient, create_draft_order, create_machine,
    create_log, mark_reviewed, list_reviews, sign_off_review, set_clock,
    get_patient, api_client,
    setup_active_patient_with_delivered_order,
    make_admin_headers, make_nurse_headers, make_patient_headers,
    make_nephrologist_headers, create_treatment_log_payload,
    create_training_attempt_payload,
)


class TestLogLifecycleFlagAmendBattery:
    """Log validation probes plus the FLAGGED -> amend -> SUBMITTED cycle with
    restore-then-subtract on-hand accounting."""

    def _setup(self, api):
        ctx = setup_active_patient_with_delivered_order(order_qty=10,
                                                        delivered_qty=10)
        pat = ctx["patient"]["id"]
        m1 = ctx["machine"]["id"]
        # A second, unassigned machine for the not-assigned probe.
        m2 = create_machine(ctx["program"]["id"], serial_number="SN-Z2")
        set_clock("2026-05-04T09:00:00Z")
        return ctx, pat, m1, m2

    def test_log_validation_probes(self, api):
        """PRD §3.6: "The `treatment_date` is a `YYYY-MM-DD` calendar date that
        may not lie after the current clock date (`ERR_LOG_DATE_IN_FUTURE`),
        and at most one log exists per patient per date
        (`ERR_DUPLICATE_TREATMENT_DATE`)."
        PRD §3.6: "The machine must currently be `ASSIGNED` to this very
        patient (`ERR_MACHINE_NOT_ASSIGNED_TO_PATIENT`)."

        Design: Corner/state_machines/log_lifecycle_flag_amend_battery
        """
        ctx, pat, m1, m2 = self._setup(api)
        # Future treatment_date (clock is 2026-05-04).
        resp = api.create_treatment_log(
            create_treatment_log_payload(pat, m1, "2026-06-01"),
            make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_LOG_DATE_IN_FUTURE)
        log1 = create_log(pat, m1, "2026-05-04",
                          consumption=[{"sku": "DIALYSATE_2L", "units": 6}])
        assert log1["consumption_units"] == 6
        assert log1["status"] == "SUBMITTED"
        # Duplicate date.
        resp = api.create_treatment_log(
            create_treatment_log_payload(pat, m1, "2026-05-04"),
            make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TREATMENT_DATE)
        # Unassigned machine.
        resp = api.create_treatment_log(
            create_treatment_log_payload(pat, m2["id"], "2026-05-03"),
            make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_MACHINE_NOT_ASSIGNED_TO_PATIENT)

    def test_flag_amend_restore_then_subtract(self, api):
        """PRD §3.6: "Amendment settles inventory by restore-then-subtract: the
        old `consumption_units` are first credited back to `on_hand_units`,
        then the new sum is subtracted — and the net increase must fit within
        the on-hand balance, else `ERR_QUANTITY_EXCEEDS_ON_HAND`. The machine's
        runtime recomputes from the amended duration, and the `flag_note` is
        cleared. Mark-reviewed or flag on a non-`SUBMITTED` log, or amend on a
        non-`FLAGGED` log, is `ERR_LOG_INVALID_STATE`."

        Design: Corner/state_machines/log_lifecycle_flag_amend_battery
        """
        ctx, pat, m1, m2 = self._setup(api)
        log1 = create_log(pat, m1, "2026-05-04",
                          consumption=[{"sku": "DIALYSATE_2L", "units": 6}])
        # Amend while SUBMITTED: invalid state.
        resp = api.amend_log(log1["id"], {"consumption": []},
                             make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_LOG_INVALID_STATE)
        flagged = validate_success(api.flag_log(
            log1["id"], {"flag_note": "duration looks wrong"},
            make_nurse_headers("nurse-1")))
        assert flagged["status"] == "FLAGGED"
        assert get_patient(pat)["on_hand_units"] == 4, "10 - 6"
        amended = validate_success(api.amend_log(
            log1["id"],
            {"duration_minutes": 200,
             "consumption": [{"sku": "DIALYSATE_2L", "units": 2}]},
            make_patient_headers(pat)))
        assert amended["status"] == "SUBMITTED"
        assert amended["consumption_units"] == 2
        assert get_patient(pat)["on_hand_units"] == 8, (
            "restore 6 then subtract 2: 4 + 6 - 2 = 8")
        machine = get_success_data(api.get_machine(m1,
                                                   make_admin_headers("admin-1")))
        assert machine["total_runtime_hours"] == pytest.approx(200 / 60, abs=0.01)
        reviewed = mark_reviewed(log1["id"])
        assert reviewed["status"] == "REVIEWED"
        # Flag from REVIEWED: invalid state.
        resp = api.flag_log(log1["id"], {"flag_note": "second flag"},
                            make_nurse_headers("nurse-1"))
        validate_error(resp, ApiErrorId.ERR_LOG_INVALID_STATE)


class TestReviewRetrainingEscalationBattery:
    """Cadence auto-creation, sign-off gating, REQUIRE_RETRAINING latch,
    review replay rejection, and escalation order cascade."""

    def _setup(self, api):
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        mach = ctx["machine"]["id"]
        order = create_draft_order(pat, "2026-05",
                                   [{"sku": "DIALYSATE_2L", "quantity": 10}])
        set_clock("2026-05-03T12:00:00Z")
        log1 = create_log(pat, mach, "2026-05-02")
        log2 = create_log(pat, mach, "2026-05-03")
        reviews = list_reviews(pat)
        return ctx, pat, mach, order, log1, log2, reviews

    def test_cadence_review_auto_created_once(self, api):
        """PRD §3.6: "The second monitor is the cadence trigger on log
        creation: after inserting the new log, the server counts the patient's
        logs in `SUBMITTED` or `FLAGGED`, and when that count reaches the
        program's `review_cadence_treatments` while no `PENDING` review exists
        for the patient, it opens a ClinicalReview with `due_reason` `CADENCE`,
        `period_start` set to the day after the latest prior review's
        `period_end` (or the date of the patient's `created_at` when there is
        no prior review), `period_end` set to the new log's `treatment_date`,
        and `due_at` set to five days after creation."

        Design: Corner/state_machines/review_retraining_escalation_battery
        """
        ctx, pat, mach, order, log1, log2, reviews = self._setup(api)
        assert len(reviews) == 1, "auto-created exactly once after the 2nd log"
        assert reviews[0]["due_reason"] == "CADENCE"
        assert reviews[0]["status"] == "PENDING"

    def test_signoff_gate_retraining_latch_and_clear(self, api):
        """PRD §3.6: "Sign-off belongs to the `Nephrologist` and requires the
        review `PENDING` (`ERR_REVIEW_NOT_PENDING`), an `outcome` drawn from
        `CONTINUE`, `MODIFY_PRESCRIPTION`, `REQUIRE_RETRAINING`, or
        `RECOMMEND_TRANSITION` (`ERR_INVALID_REQUEST`), and a clean period: no
        log of the patient dated inside the inclusive period may remain
        `SUBMITTED` or `FLAGGED` (`ERR_UNREVIEWED_LOGS_REMAIN`)."
        PRD §3.6: "If the outcome is `REQUIRE_RETRAINING`, the patient's
        `retraining_required` latch sets, which drives posture to `BLOCKED` at
        the next evaluation until any passing attempt is signed off (§3.2)."
        PRD §3.2: "A successful sign-off stamps `signed_off_by_user_id` with
        the signer and `signed_off_at` with the current logical clock, moves
        the attempt to `SIGNED_OFF` (terminal), clears the patient's
        `retraining_required` latch if it was set — any passing sign-off clears
        it, regardless of module — and recomputes posture."

        Design: Corner/state_machines/review_retraining_escalation_battery
        """
        ctx, pat, mach, order, log1, log2, reviews = self._setup(api)
        review = reviews[0]
        # Unreviewed period logs block sign-off.
        resp = api.sign_off_review(review["id"], {"outcome": "CONTINUE"},
                                   make_nephrologist_headers("nephro-1"))
        validate_error(resp, ApiErrorId.ERR_UNREVIEWED_LOGS_REMAIN)
        mark_reviewed(log1["id"])
        mark_reviewed(log2["id"])
        signed = sign_off_review(review["id"], "REQUIRE_RETRAINING")
        assert signed["status"] == "SIGNED_OFF"
        assert signed["adherence_rolling_pct"] == pytest.approx(16.7, abs=0.05), (
            "2 logs / 12 scheduled in the trailing 28 days")
        patient = get_patient(pat)
        assert patient["retraining_required"] is True
        assert patient["posture"] == "BLOCKED"
        # BLOCKED posture rejects order submission.
        resp = api.submit_supply_order(order["id"], make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_POSTURE_NOT_ORDERABLE)
        # A fresh passing sign-off clears the latch regardless of module.
        att = validate_success(api.create_training_attempt(
            create_training_attempt_payload(pat, "WATER_HANDLING",
                                            score_pct=95),
            make_nurse_headers("nurse-1")), 201)
        validate_success(api.sign_off_attempt(att["id"],
                                              make_nurse_headers("nurse-2")))
        assert get_patient(pat)["posture"] == "HOME_READY"
        submitted = validate_success(api.submit_supply_order(
            order["id"], make_patient_headers(pat)))
        assert submitted["order_status"] == "SUBMITTED"
        # Replay on the SIGNED_OFF review.
        resp = api.sign_off_review(review["id"], {"outcome": "CONTINUE"},
                                   make_nephrologist_headers("nephro-1"))
        validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_PENDING)

    def test_escalation_cancels_open_orders(self, api):
        """PRD §3.6: "Escalation is the sharp edge: a `HomeNurse` or
        `Nephrologist` may escalate a `PENDING` review to `ESCALATED`. The
        open-escalation condition of the posture ladder now holds, so posture
        recomputes to `BLOCKED`, and the escalation cascade cancels the
        patient's open orders in `DRAFT`, `SUBMITTED`, or `CHANGES_REQUESTED` —
        `APPROVED` orders are deliberately untouched."

        Design: Corner/state_machines/review_retraining_escalation_battery
        """
        ctx, pat, mach, order, log1, log2, reviews = self._setup(api)
        # Resolve the first review so a second can be created.
        mark_reviewed(log1["id"])
        mark_reviewed(log2["id"])
        sign_off_review(reviews[0]["id"], "CONTINUE")
        set_clock("2026-05-05T12:00:00Z")
        create_log(pat, mach, "2026-05-04")
        create_log(pat, mach, "2026-05-05")
        reviews = list_reviews(pat)
        assert len(reviews) == 2
        escalated = validate_success(api.escalate_review(
            reviews[1]["id"], make_nephrologist_headers("nephro-1")))
        assert escalated["status"] == "ESCALATED"
        assert get_patient(pat)["posture"] == "BLOCKED"
        order_after = get_success_data(api.get_supply_order(
            order["id"], make_admin_headers("admin-1")))
        assert order_after["order_status"] == "CANCELLED", (
            "open DRAFT order cascade-cancelled by the escalation")
