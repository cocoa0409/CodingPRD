"""Medicated carryover control: the flush gate on batch start, segregation of
duties on flush verification, and flush domain errors (PRD §3.6, §3.7)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_operator_headers,
    setup_medicated_mix_on_line, setup_standard_order_after_med,
    advance_clock, make_employee, make_ingredient, make_line,
    create_flush_record_payload,
)

MM = TEST_USERS["mill_manager_headers"]


class TestBatchStartFlushGate:
    def _contaminated_setup(self, api):
        """Line L1 contaminated by a medicated mix (med70/corn30) at the
        default clock; clock advanced so a later flush verifies strictly after
        the medicated mixed_at; a non-medicated batch PLANNED on L1."""
        ctx = setup_medicated_mix_on_line()
        batch_std = setup_standard_order_after_med(ctx)
        advance_clock("2026-05-02T12:00:00Z")
        ctx["batch_std"] = batch_std
        return ctx

    def test_nonmedicated_batch_start_rejected_on_contaminated_line(self, api):
        """PRD §3.6: "the order must not be `blocked` (`ERR_ORDER_BLOCKED`); and the sequencing gate — a batch whose `is_medicated` is false may not start on a line whose `contamination` is `MEDICATED` unless a `VERIFIED` flush exists whose `verified_at` falls after the last medicated batch's `mixed_at` (`ERR_FLUSH_REQUIRED`)."

        Design: Difficulty/cross_entity_state_dependency/batch_start_gated_by_line_flush_verification
        """
        ctx = self._contaminated_setup(api)
        line = validate_success(api.get_line(ctx["line"]["id"], MM), 200)
        assert line["contamination"] == "MEDICATED"

        resp = api.start_batch(ctx["batch_std"]["id"],
                               make_operator_headers(ctx["op"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FLUSH_REQUIRED)

    def test_verified_flush_clears_contamination_and_allows_start(self, api):
        """PRD §3.7: "A successful verification stamps `verified_by_employee_id` from the caller and `verified_at` from the logical clock, and when that `verified_at` falls after the last medicated mix the line's `contamination` recomputes to `NONE`; the flush's `version` increments."
        PRD §3.7: "The discipline pays out at the sequencing gate of §3.6: a non-medicated batch may follow medicated work on the same line only after this record-then-verify cycle has produced a `VERIFIED` flush newer than the last medicated `mixed_at`."

        Design: Difficulty/cross_entity_state_dependency/batch_start_gated_by_line_flush_verification
        """
        ctx = self._contaminated_setup(api)
        hulls = make_ingredient("HULLS")
        op2 = make_employee("Omar Operator", "OPERATOR")

        # Record by op1; verify by a different operator op2.
        flush = validate_success(api.create_flush_record(
            create_flush_record_payload(ctx["line"]["id"], hulls["id"], 0.5),
            make_operator_headers(ctx["op"]["id"])), 201)
        verified = validate_success(
            api.verify_flush_record(flush["id"], make_operator_headers(op2["id"])), 200)
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_employee_id"] == op2["id"]
        assert verified["verified_by_employee_id"] != verified["recorded_by_employee_id"]

        line = validate_success(api.get_line(ctx["line"]["id"], MM), 200)
        assert line["contamination"] == "NONE", (
            "verified_at falls after the last medicated mixed_at, so the line clears")

        started = validate_success(
            api.start_batch(ctx["batch_std"]["id"],
                            make_operator_headers(ctx["op"]["id"])), 200)
        assert started["status"] == "BATCHING"


class TestFlushSegregationOfDuties:
    def test_flush_verify_by_recorder_rejected_sod(self, api):
        """PRD §3.7: "the caller's `X-User-ID` must differ from `recorded_by_employee_id`, and a self-verification is rejected with `ERR_SOD_VIOLATION`."

        Design: Corner/state_machines/flush_verify_by_recorder_rejected_sod
        """
        hulls = make_ingredient("HULLS")
        op1 = make_employee("Olly Operator", "OPERATOR")
        op2 = make_employee("Omar Operator", "OPERATOR")
        line = make_line("L1")

        flush = validate_success(api.create_flush_record(
            create_flush_record_payload(line["id"], hulls["id"], 0.5),
            make_operator_headers(op1["id"])), 201)
        assert flush["recorded_by_employee_id"] == op1["id"]

        # Self-verification violates segregation of duties.
        resp = api.verify_flush_record(flush["id"], make_operator_headers(op1["id"]))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        # A different operator verifies successfully.
        verified = validate_success(
            api.verify_flush_record(flush["id"], make_operator_headers(op2["id"])), 200)
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_employee_id"] == op2["id"]


class TestFlushDomainErrors:
    def test_flush_domain_errors(self, api):
        """PRD §3.7: "The material must be flush-approved — an ingredient whose `is_flush_material` is false is refused with `ERR_FLUSH_MATERIAL_INVALID` — and the quantity must be at least half a ton: exactly 0.5 tons passes, anything less is rejected with `ERR_FLUSH_QUANTITY_BELOW_MIN`."

        Design: Corner/errors/flush_domain_errors
        """
        corn = make_ingredient("CORN")      # is_flush_material false
        hulls = make_ingredient("HULLS")    # approved flush material
        op = make_employee("Olly Operator", "OPERATOR")
        line = make_line("L1")
        op_headers = make_operator_headers(op["id"])

        r1 = api.create_flush_record(
            create_flush_record_payload(line["id"], corn["id"], 1.0), op_headers)
        validate_error(r1, ApiErrorId.ERR_FLUSH_MATERIAL_INVALID)

        r2 = api.create_flush_record(
            create_flush_record_payload(line["id"], hulls["id"], 0.4), op_headers)
        validate_error(r2, ApiErrorId.ERR_FLUSH_QUANTITY_BELOW_MIN)

        # Inclusive boundary: exactly half a ton is accepted.
        ok = api.create_flush_record(
            create_flush_record_payload(line["id"], hulls["id"], 0.5), op_headers)
        flush = validate_success(ok, 201)
        assert flush["status"] == "RECORDED"
