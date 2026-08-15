"""Prepress proofs: revision cycle, supersede semantics, round numbering,
proof-round overage fee, and state gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_estimate,
    approve_proof,
    create_accepted_job,
    create_customer,
    create_estimate,
    create_received_stock,
    create_stock,
    get_success_data,
    make_customer_headers,
    minimal_signature,
    quote_estimate,
    standard_signatures,
    upload_proof,
    validate_error,
    validate_success,
)

_PRE = TEST_USERS["prepress_headers"]
_PM = TEST_USERS["plant_manager_headers"]
_EST = TEST_USERS["estimator_headers"]


def _prepress_job(name="PJ", quantity=100):
    cust = create_customer(name=name)
    stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
    est, job = create_accepted_job(cust["id"], minimal_signature(stock["id"]),
                                   quantity_ordered=quantity, job_name=name)
    return cust, job


class TestProofRevisionCycle:
    def _cycle_setup(self):
        cust = create_customer(name="Cyc Cust")
        # Stock paper up front: PRD §3.6 reserves planned sheets at schedule
        # time (ERR_PAPER_INSUFFICIENT when lots cannot cover), and the
        # overage-fee test drives the job through a press run (10002 pieces
        # with 3%/2% spoilage reserves 10512 sheets; sheets_used 10600).
        stock, _po = create_received_stock(name="80G", cost_per_sheet_cents=9,
                                           sheets=20000)
        est, job = create_accepted_job(
            cust["id"], standard_signatures(stock["id"]),
            quantity_ordered=10002, press_spoilage_pct=3, bindery_spoilage_pct=2,
            finishing_options=["PERF", "SCORE"], included_proof_rounds=2,
            job_name="Cyc",
        )
        return cust, job

    def test_proof_revision_cycle_supersedes_and_counts_rounds(self, api):
        """PRD §3.4: "If a prior proof of the same job is currently in
        `AWAITING_CUSTOMER` or `CHANGES_REQUESTED`, that prior proof is moved
        to `SUPERSEDED`... Each upload increments the job's
        `proof_rounds_used` by 1." Three rounds cycle request-changes twice
        before approval; proof_rounds_used ends at 3.

        Design: Difficulty/non_linear_state_machine/proof_revision_cycle_with_overage_fee
        """
        cust, job = self._cycle_setup()
        p1 = upload_proof(job["id"], "s3://r1.pdf")
        r = api.request_proof_changes(p1["id"], {"notes": "color off"},
                                      make_customer_headers(cust["id"]))
        validate_success(r, 200)
        p2 = upload_proof(job["id"], "s3://r2.pdf")
        r = api.request_proof_changes(p2["id"], {"notes": "trim"},
                                      make_customer_headers(cust["id"]))
        validate_success(r, 200)
        p3 = upload_proof(job["id"], "s3://r3.pdf")
        r = api.approve_proof(p3["id"], make_customer_headers(cust["id"]))
        validate_success(r, 200)

        p1_after = get_success_data(api.get_proof(p1["id"], _PRE))
        p2_after = get_success_data(api.get_proof(p2["id"], _PRE))
        p3_after = get_success_data(api.get_proof(p3["id"], _PRE))
        assert p1_after["status"] == "SUPERSEDED"
        assert p2_after["status"] == "SUPERSEDED"
        assert p3_after["status"] == "APPROVED"
        assert p3_after["round_number"] == 3

        job_after = get_success_data(api.get_job(job["id"], _PM))
        assert job_after["production_status"] == "PLATED"
        assert job_after["proof_rounds_used"] == 3

    def test_proof_overage_fee_charged_beyond_included_rounds(self, api):
        """PRD §3.12: "Proof overage is charged when the job consumed more
        rounds than included: `proof_overage_cents` is the excess of
        `proof_rounds_used` over `included_proof_rounds`, floored at zero,
        multiplied by 12500 cents per excess round." With 3 rounds used and 2
        included, the overage is 1 x 12500 = 12500.

        Design: Difficulty/non_linear_state_machine/proof_revision_cycle_with_overage_fee
        """
        from test_helpers import (
            complete_bindery_and_deliver,
            complete_press_run,
            create_press,
            schedule_press_run,
        )
        cust, job = self._cycle_setup()
        # 3 proof rounds (1 over included 2)
        p1 = upload_proof(job["id"], "s3://r1.pdf")
        api.request_proof_changes(p1["id"], {"notes": "x"}, make_customer_headers(cust["id"]))
        p2 = upload_proof(job["id"], "s3://r2.pdf")
        api.request_proof_changes(p2["id"], {"notes": "y"}, make_customer_headers(cust["id"]))
        p3 = upload_proof(job["id"], "s3://r3.pdf")
        approve_proof(p3["id"], cust["id"])
        # Drive to FULFILLED and invoice
        press = create_press()
        run = schedule_press_run(press, job_id=job["id"], run_quantity=10002)
        complete_press_run(run["id"], gross_impressions=10002, sheets_used=10600,
                           waste_sheets=300)
        complete_bindery_and_deliver(job["id"], delivered_quantity=10002,
                                     pieces_completed=10002)
        inv = get_success_data(api.create_invoice({"job_id": job["id"]}, _PM))
        assert inv["proof_overage_cents"] == 12500, (
            f"1 excess round x 12500 = 12500, got {inv['proof_overage_cents']}"
        )


class TestProofSupersede:
    def test_proof_round_number_increments_and_supersedes(self, api):
        """PRD §3.4: "Its `round_number` is one more than the maximum existing
        `round_number` for the job, or 1 for the first proof" and the prior
        open proof "is moved to `SUPERSEDED`."

        Design: Corner/entities/proof_round_number_increments_and_supersedes
        """
        cust, job = _prepress_job("P Cust", 100)
        p1 = upload_proof(job["id"], "s3://r1.pdf")
        p2 = upload_proof(job["id"], "s3://r2.pdf")
        p1_after = get_success_data(api.get_proof(p1["id"], _PRE))
        p2_after = get_success_data(api.get_proof(p2["id"], _PRE))
        assert p1_after["status"] == "SUPERSEDED"
        assert p2_after["round_number"] == 2
        assert p2_after["status"] == "AWAITING_CUSTOMER"
        job_after = get_success_data(api.get_job(job["id"], _PM))
        assert job_after["proof_rounds_used"] == 2


class TestProofStateGates:
    def test_proof_approve_twice_rejected(self, api):
        """PRD §3.4: "Actions on a proof no longer in `AWAITING_CUSTOMER` are
        rejected with `ERR_PROOF_NOT_AWAITING`."

        Design: Corner/state_machines/proof_approve_twice_rejected
        """
        cust, job = _prepress_job("PA Cust", 100)
        proof = upload_proof(job["id"], "s3://p.pdf")
        approve_proof(proof["id"], cust["id"])
        resp = api.approve_proof(proof["id"], make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_PROOF_NOT_AWAITING)
        job_after = get_success_data(api.get_job(job["id"], _PM))
        assert job_after["production_status"] == "PLATED"

    def test_proof_upload_after_plating_rejected(self, api, prepress_headers):
        """PRD §3.4: "The job must be in `PREPRESS` or `PROOF_REVIEW`." —
        uploading once the job is PLATED fails the job-state gate.

        Design: Corner/state_machines/proof_upload_after_plating_rejected
        """
        cust, job = _prepress_job("PU Cust", 100)
        proof = upload_proof(job["id"], "s3://p.pdf")
        approve_proof(proof["id"], cust["id"])
        resp = api.create_proof({"job_id": job["id"], "file_uri": "s3://late.pdf"},
                                prepress_headers)
        validate_error(resp, ApiErrorId.ERR_JOB_INVALID_STATE)
