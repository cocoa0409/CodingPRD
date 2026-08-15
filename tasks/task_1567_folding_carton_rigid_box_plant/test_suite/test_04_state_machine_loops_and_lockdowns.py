"""Cyclic state machines (revision sample loop, approval resubmit round) and
terminal/invalid-transition lockdowns across jobs, audits, kits, invoices."""
from test_helpers import (
    ApiErrorId,
    assert_kit_order,
    create_customer,
    create_job,
    create_kit_order,
    create_retail_audit_payload,
    make_brand_quality_headers,
    setup_engineering_job,
    setup_finished_job,
    setup_press_ready_job,
    start_engineering,
    validate_error,
    validate_success,
    get_success_data,
)
from test_helpers.fixtures import ADMIN, CLERK, DESIGNER, KITTER, OPERATOR
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_design_revision_payload,
    create_invoice_payload,
    create_press_approval_payload,
)


class TestDesignRevisionSampleRejectLoop:
    def _sample_made_revision(self, api, brand_code):
        ctx = setup_engineering_job(
            customer_name="Zeta", brand_code=brand_code, standard=False, stock=False,
            finish_coat=True, required_ink_slots=[],
        )
        revision = get_success_data(
            api_client.create_design_revision(
                create_design_revision_payload(
                    ctx["job"]["id"], ctx["job"]["version"]
                ),
                DESIGNER,
            )
        )
        # Return the post-make-sample view: version 2, status SAMPLE_MADE.
        revision = get_success_data(api_client.make_sample(revision["id"], DESIGNER))
        return ctx, revision

    def test_brand_reject_loops_sample_back_to_draft(self, api):
        """PRD §3.3: "The brand then adjudicates the sample: brand acceptance moves it to `BRAND_APPROVED`, while brand rejection loops it back to `DRAFT` for rework."

        Design: Difficulty/non_linear_state_machine/design_revision_sample_reject_loop
        """
        ctx, revision = self._sample_made_revision(api, "ZTA")
        cust_id = ctx["customer"]["id"]
        assert revision["version"] == 2  # create v1, make-sample v2

        rejected = validate_success(
            api.brand_reject_revision(
                revision["id"], make_brand_quality_headers(cust_id)),
            200,
        )
        assert rejected["status"] == "DRAFT"
        assert rejected["version"] == 3

        resampled = validate_success(api.make_sample(revision["id"], DESIGNER), 200)
        assert resampled["status"] == "SAMPLE_MADE"
        assert resampled["version"] == 4

        accepted = validate_success(
            api.brand_accept_revision(
                revision["id"], make_brand_quality_headers(cust_id)),
            200,
        )
        assert accepted["status"] == "BRAND_APPROVED"
        assert accepted["version"] == 5

    def test_loop_reuses_same_revision_number(self, api):
        """PRD §3.3: "Each revision receives a `revision_number` that is one-based per job and increments with every new revision."
        PRD §2.5: "`version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations caused by cascading side effects from operations on other resources."

        Design: Difficulty/non_linear_state_machine/design_revision_sample_reject_loop
        """
        ctx, revision = self._sample_made_revision(api, "ZTB")
        cust_id = ctx["customer"]["id"]
        assert revision["revision_number"] == 1

        get_success_data(api_client.brand_reject_revision(
            revision["id"], make_brand_quality_headers(cust_id)))
        get_success_data(api_client.make_sample(revision["id"], DESIGNER))
        final = get_success_data(api_client.brand_accept_revision(
            revision["id"], make_brand_quality_headers(cust_id)))

        assert final["id"] == revision["id"], "loop reuses the same revision"
        assert final["revision_number"] == 1, "no new revision was ever created"
        assert final["version"] == 5


class TestPressApprovalRejectResubmitRound:
    def test_resubmit_replaces_measurement_and_increments_submission_index(self, api):
        """PRD §3.4: "Rejection is not terminal: the press operator may resubmit with a fresh `measured_delta_e_milli`, which replaces the stored measurement, increments the `submission_index` by one, and returns the approval to `SUBMITTED` for another brand decision."

        Design: Difficulty/non_linear_state_machine/press_approval_reject_resubmit_round
        """
        ctx = setup_press_ready_job(customer_name="Eta", brand_code="ETA")
        approval = validate_success(
            api.create_press_approval(
                create_press_approval_payload(
                    ctx["job"]["id"], ctx["standard"]["id"],
                    measured_delta_e_milli=250),
                OPERATOR,
            ),
            201,
        )
        assert approval["submission_index"] == 1
        assert approval["status"] == "SUBMITTED"

        rejected = validate_success(
            api.reject_press_approval(
                approval["id"], make_brand_quality_headers(ctx["customer"]["id"])),
            200,
        )
        assert rejected["status"] == "REJECTED"

        resubmitted = validate_success(
            api.resubmit_press_approval(
                approval["id"], {"measured_delta_e_milli": 180}, OPERATOR),
            200,
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["submission_index"] == 2
        assert resubmitted["measured_delta_e_milli"] == 180

    def test_approve_after_resubmit_within_tolerance(self, api):
        """PRD §3.4: "Approval by `BrandQuality` — ownership-checked against the job's `customer_id`, failing with `ERR_CUSTOMER_OWNERSHIP_MISMATCH` — moves the approval from `SUBMITTED` to `APPROVED`, but only when the `measured_delta_e_milli` is at or below the standard's `tolerance_delta_e_milli`; the boundary is inclusive, so a measurement exactly equal to the tolerance passes, and anything above it is rejected with `ERR_DELTA_E_EXCEEDED` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/press_approval_reject_resubmit_round
        """
        ctx = setup_press_ready_job(customer_name="Eta", brand_code="ETB")
        approval = get_success_data(api_client.create_press_approval(
            create_press_approval_payload(
                ctx["job"]["id"], ctx["standard"]["id"],
                measured_delta_e_milli=250),
            OPERATOR,
        ))
        get_success_data(api_client.reject_press_approval(
            approval["id"], make_brand_quality_headers(ctx["customer"]["id"])))
        get_success_data(api_client.resubmit_press_approval(
            approval["id"], {"measured_delta_e_milli": 180}, OPERATOR))

        # 180 <= tolerance 200, so the approve succeeds after the round trip.
        approved = validate_success(
            api.approve_press_approval(
                approval["id"], make_brand_quality_headers(ctx["customer"]["id"])),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["version"] == 4  # create, reject, resubmit, approve


def test_job_terminal_cancelled_lockdown(api):
    """PRD §3.2: "A `PlantAdmin` may also cancel a job outright while it is in `QUOTED`, `ENGINEERING`, or `PRESS_READY`; cancellation releases the job's board reservation if one exists — the stock's `reserved_sheets` decreases by the job's remaining reservation — and, as a second-level effect of that job mutation, every `SCHEDULED` press booking and finishing booking belonging to the job is cancelled with it. `CANCELLED` is terminal."
    PRD §2.6: "Sixth, state: the target resource must be in a state from which the requested transition or action is defined — including the rule that imposition plans may only be created against a design revision that is not `SUPERSEDED` (rejected with `ERR_REVISION_SUPERSEDED`) and that invoice finalization requires a `COMPLETE` job (rejected with `ERR_JOB_NOT_COMPLETE`); other state violations return `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/job_terminal_cancelled_lockdown
    """
    customer = create_customer(name="Acme", brand_code="ACM")
    job = create_job(customer["id"], finish_coat=False, required_ink_slots=[])

    cancelled = validate_success(api.cancel_job(job["id"], ADMIN), 200)
    assert cancelled["status"] == "CANCELLED"

    res = api.start_engineering(job["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    res2 = api.cancel_job(job["id"], ADMIN)
    validate_error(res2, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_audit_certify_from_draft_rejected(api):
    """PRD §3.7: "Once `SUBMITTED`, the audit goes to the brand: certification by `BrandQuality` moves it to `CERTIFIED`, rejection moves it to `REJECTED`, and both are ownership-checked against the job's `customer_id` with `ERR_CUSTOMER_OWNERSHIP_MISMATCH` on mismatch."
    PRD §2.6: "Sixth, state: the target resource must be in a state from which the requested transition or action is defined — including the rule that imposition plans may only be created against a design revision that is not `SUPERSEDED` (rejected with `ERR_REVISION_SUPERSEDED`) and that invoice finalization requires a `COMPLETE` job (rejected with `ERR_JOB_NOT_COMPLETE`); other state violations return `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/audit_certify_from_draft_rejected
    """
    customer = create_customer(name="Acme", brand_code="ACM")
    job = create_job(customer["id"], finish_coat=False, required_ink_slots=[],
                     requires_retail_compliance=True)
    audit = validate_success(
        api.create_retail_audit(create_retail_audit_payload(job["id"]), KITTER), 201
    )
    assert audit["verdict"] == "COMPLIANT"
    assert audit["status"] == "DRAFT"

    res = api.certify_retail_audit(
        audit["id"], make_brand_quality_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    after = validate_success(api.get_retail_audit(audit["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"


def test_invoice_finalize_before_job_complete_rejected(api):
    """PRD §3.8: "Finalization is the settlement event and requires the job to be `COMPLETE`; finalizing earlier is rejected with `ERR_JOB_NOT_COMPLETE` (HTTP 409)."
    PRD §3.8: "A new invoice is `DRAFT`, its `variant` reads `PROVISIONAL`, and its charges snapshot the job's provisional quote"

    Design: Corner/state_machines/invoice_finalize_before_job_complete_rejected
    """
    customer = create_customer(name="Acme", brand_code="ACM")
    job = create_job(customer["id"], finish_coat=False, required_ink_slots=[])
    invoice = validate_success(
        api.create_invoice(create_invoice_payload(job["id"]), CLERK), 201
    )
    assert invoice["status"] == "DRAFT"
    assert invoice["variant"] == "PROVISIONAL"

    res = api.finalize_invoice(invoice["id"], CLERK)
    validate_error(res, ApiErrorId.ERR_JOB_NOT_COMPLETE)

    after = validate_success(api.get_invoice(invoice["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"


def test_kit_order_complete_from_planned_rejected(api):
    """PRD §3.7: "Starting the order moves it from `PLANNED` to `IN_PROGRESS`. Completing it reports `kits_completed` — never more than `kits_planned`, else `ERR_INVALID_REQUEST` — and the `labor_minutes_actual` the assembly consumed."
    PRD §2.6: "Sixth, state: the target resource must be in a state from which the requested transition or action is defined — including the rule that imposition plans may only be created against a design revision that is not `SUPERSEDED` (rejected with `ERR_REVISION_SUPERSEDED`) and that invoice finalization requires a `COMPLETE` job (rejected with `ERR_JOB_NOT_COMPLETE`); other state violations return `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/kit_order_complete_from_planned_rejected
    """
    ctx = setup_finished_job(customer_name="Acme", brand_code="ACM")
    kit = create_kit_order(ctx["job"]["id"], kits_planned=10)
    assert_kit_order(kit)
    assert kit["status"] == "PLANNED"

    res = api.complete_kit_order(
        kit["id"], {"kits_completed": 10, "labor_minutes_actual": 60}, KITTER
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    after = validate_success(api.get_kit_order(kit["id"], ADMIN), 200)
    assert after["status"] == "PLANNED"
    assert after["consumed_cartons"] == 0, "no cartons consumed by a rejected complete"


def test_audit_reject_revise_recompute_cycle(api):
    """PRD §3.7: "A rejected audit is revisable: the kitting lead replaces the case and pallet inputs — `orientation`, `case_w_cin`, `case_h_cin`, `case_d_cin`, `case_weight_g`, `cases_per_layer`, `layers`, and `case_count` — the verdict is recomputed from the new values, and the audit returns to `DRAFT` for another submission."
    PRD §3.7: "Count requires `case_count` to equal `cases_per_layer` times `layers` exactly."

    Design: Corner/state_machines/audit_reject_revise_recompute_cycle
    """
    customer = create_customer(name="Acme", brand_code="ACM")
    job = create_job(customer["id"], finish_coat=False, required_ink_slots=[],
                     requires_retail_compliance=True)
    audit = get_success_data(api_client.create_retail_audit(
        create_retail_audit_payload(job["id"]), KITTER))
    get_success_data(api_client.submit_retail_audit(audit["id"], KITTER))

    rejected = validate_success(
        api.reject_retail_audit(
            audit["id"], make_brand_quality_headers(customer["id"])),
        200,
    )
    assert rejected["status"] == "REJECTED"

    revised = validate_success(
        api.revise_retail_audit(
            audit["id"],
            {
                "orientation": "LENGTHWISE",
                "case_w_cin": 1524,
                "case_h_cin": 2540,
                "case_d_cin": 9000,
                "case_weight_g": 14000,
                "cases_per_layer": 8,
                "layers": 6,
                "case_count": 47,
            },
            KITTER,
        ),
        200,
    )
    assert revised["status"] == "DRAFT"
    assert revised["case_count"] == 47
    # 47 != 8*6 -> count check fails -> NON_COMPLIANT
    assert revised["verdict"] == "NON_COMPLIANT"
