"""Print coordination: the proof revision loop, stage validation, and the
print-delivery gate on order completion."""
from test_helpers import (
    ApiErrorId,
    assert_print_job,
    confirm_order,
    create_order,
    create_print_job,
    decide_qc_report,
    drive_tooling_to_stamper_ready,
    file_qc_report,
    get_order,
    make_customer_headers,
    press_run,
    produce_test_pressing,
    quote_order,
    review_test_pressing,
    schedule_order,
    setup_world,
    ship_test_pressing,
    start_tooling,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CSR, PM


class TestPrintStageMachine:
    def test_print_job_invalid_event_rejected(self, api):
        """PRD §3.5: "Events out of stage order are rejected with
        `ERR_PRINT_JOB_INVALID_STATE`."

        Design: Corner/state_machines/print_job_invalid_event_rejected
        """
        world = setup_world(with_line=False, with_bath=False)
        order = create_order(world["release"]["id"], quantity_ordered=100)
        pj = create_print_job(order["id"], quantity=100, component="INSERT")
        assert pj["status"] == "CREATED"

        # DELIVER is only valid from PRINTING.
        r1 = api.advance_print_job(pj["id"], {"event": "DELIVER"}, CSR)
        validate_error(r1, ApiErrorId.ERR_PRINT_JOB_INVALID_STATE)

        # Proof decisions require PROOF_REVIEW.
        r2 = api.decide_print_proof(
            pj["id"], {"decision": "APPROVE"},
            make_customer_headers(world["customer"]["id"]),
        )
        validate_error(r2, ApiErrorId.ERR_PRINT_JOB_INVALID_STATE)


class TestProofRevisionLoop:
    def _proof_review_job(self, api, world):
        """Confirmed order with a JACKET print job advanced to PROOF_REVIEW."""
        order = create_order(world["release"]["id"], quantity_ordered=1000)
        order = quote_order(order)
        order = confirm_order(order, world["customer"]["id"])
        pj = create_print_job(order["id"], quantity=1000, component="JACKET")
        validate_success(
            api.advance_print_job(pj["id"], {"event": "DISPATCH"}, CSR), 200
        )
        pj = validate_success(
            api.advance_print_job(pj["id"], {"event": "PROOFS_IN"}, CSR), 200
        )
        assert pj["status"] == "PROOF_REVIEW"
        return order, pj

    def test_print_proof_loop_increments_round(self, api):
        """PRD §3.5: "`REQUEST_CHANGES` loops it back `PROOF_REVIEW` →
        `AT_PRINTER`, increments `proof_round`, and triggers a risk recompute
        with cause `SCHEDULE` so that slipping print dates surface through the
        release's `risk_level` and, on worsening, a DelayNotice."

        Design: Difficulty/non_linear_state_machine/print_job_proof_revision_loop
        """
        world = setup_world(with_line=False, with_bath=False)
        _order, pj = self._proof_review_job(api, world)
        resp = api.decide_print_proof(
            pj["id"], {"decision": "REQUEST_CHANGES", "notes": "color off"},
            make_customer_headers(world["customer"]["id"]),
        )
        data = validate_success(resp, 200)
        assert_print_job(data)
        assert data["status"] == "AT_PRINTER", (
            f"REQUEST_CHANGES must loop back to AT_PRINTER, got {data['status']}"
        )
        assert data["proof_round"] == 1

    def test_print_proof_loop_reaches_delivered(self, api):
        """PRD §3.5: "From `PROOF_REVIEW`, a `decision` of `APPROVE` —
        optionally annotated with `notes` — moves the job to `PRINTING`" and
        "`DELIVER` moves a `PRINTING` job to `DELIVERED`."

        Design: Difficulty/non_linear_state_machine/print_job_proof_revision_loop
        """
        world = setup_world(with_line=False, with_bath=False)
        _order, pj = self._proof_review_job(api, world)
        # One revision loop, then approval.
        api.decide_print_proof(
            pj["id"], {"decision": "REQUEST_CHANGES", "notes": "color off"},
            make_customer_headers(world["customer"]["id"]),
        )
        validate_success(
            api.advance_print_job(pj["id"], {"event": "PROOFS_IN"}, CSR), 200
        )
        approved = validate_success(
            api.decide_print_proof(
                pj["id"], {"decision": "APPROVE"},
                make_customer_headers(world["customer"]["id"]),
            ),
            200,
        )
        assert approved["status"] == "PRINTING"
        assert approved["proof_round"] == 1

        delivered = validate_success(
            api.advance_print_job(pj["id"], {"event": "DELIVER"}, CSR), 200
        )
        assert delivered["status"] == "DELIVERED"


class TestCompletionGatedByPrint:
    def _order_in_qc_review_with_print_at_proof_review(self, api, world):
        """Order driven to QC_REVIEW with a PASS report filed; its JACKET print
        job sits undelivered at PROOF_REVIEW."""
        order = create_order(world["release"]["id"], quantity_ordered=1000)
        order = quote_order(order)
        order = confirm_order(order, world["customer"]["id"])
        pj = create_print_job(order["id"], quantity=1000, component="JACKET")
        validate_success(api.advance_print_job(pj["id"], {"event": "DISPATCH"}, CSR), 200)
        validate_success(api.advance_print_job(pj["id"], {"event": "PROOFS_IN"}, CSR), 200)
        job = start_tooling(order["id"])
        drive_tooling_to_stamper_ready(job["id"], world["bath"]["id"])
        tp = produce_test_pressing(order["id"])
        tp = ship_test_pressing(tp["id"])
        review_test_pressing(tp["id"], world["customer"]["id"], "APPROVE")
        order = get_order(order["id"])
        order = schedule_order(order, world["line"]["id"], planned_units=1000)
        press_run(order["id"])
        qc = file_qc_report(order["id"], 1000, 30)  # 3.00 <= 5.0 -> PASS
        assert qc["outcome"] == "PASS"
        return order, pj, qc

    def test_completion_gated_by_print_delivery_blocked(self, api):
        """PRD §3.7: "A `decision` of `ACCEPT` is lawful only when the outcome
        is `PASS` — accepting a `HOLD` report is rejected with
        `ERR_QC_HOLD_REQUIRES_REPRESS` — and only when every non-`CANCELLED`
        print job of the order is `DELIVERED` (`ERR_PRINT_JOBS_NOT_DELIVERED`)."
        PRD §3.5: "Print delivery gates completion of the whole order: quality
        acceptance (§3.7) refuses to complete an order while any
        non-`CANCELLED` print job remains undelivered."

        Design: Difficulty/cross_entity_state_dependency/order_completion_gated_by_print_delivery
        """
        world = setup_world()
        _order, _pj, qc = self._order_in_qc_review_with_print_at_proof_review(api, world)
        resp = api.decide_qc_report(
            qc["id"], {"decision": "ACCEPT", "fault": "NONE"}, PM
        )
        validate_error(resp, ApiErrorId.ERR_PRINT_JOBS_NOT_DELIVERED)
        # The report must remain undecided.
        qcs = validate_success(
            api.list_order_qc_reports(_order["id"], CSR), 200
        )
        assert qcs[0]["status"] == "FILED"

    def test_completion_unblocked_after_delivery(self, api):
        """PRD §3.7: "Acceptance completes the order (`QC_REVIEW` →
        `COMPLETED`)"

        Design: Difficulty/cross_entity_state_dependency/order_completion_gated_by_print_delivery
        """
        world = setup_world()
        order, pj, qc = self._order_in_qc_review_with_print_at_proof_review(api, world)

        # Blocked while the print job is in PROOF_REVIEW.
        resp = api.decide_qc_report(
            qc["id"], {"decision": "ACCEPT", "fault": "NONE"}, PM
        )
        validate_error(resp, ApiErrorId.ERR_PRINT_JOBS_NOT_DELIVERED)

        # Deliver the print job, then the same ACCEPT succeeds.
        validate_success(
            api.decide_print_proof(
                pj["id"], {"decision": "APPROVE"},
                make_customer_headers(world["customer"]["id"]),
            ),
            200,
        )
        validate_success(api.advance_print_job(pj["id"], {"event": "DELIVER"}, CSR), 200)

        decided = decide_qc_report(qc["id"], "ACCEPT", "NONE")
        assert decided["status"] == "DECIDED"
        final = get_order(order["id"])
        assert final["production_status"] == "COMPLETED"
