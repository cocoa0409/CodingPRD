"""Cross-entity production gates (press approvals, retail audits), the
inclusive delta-E tolerance boundary, and retail-compliance verdict checks."""
from test_helpers import (
    ApiErrorId,
    assert_inv_sheets,
    assert_retail_audit,
    create_approved_press_approval,
    create_booked_press_window,
    create_customer,
    create_job,
    create_retail_audit_payload,
    make_brand_quality_headers,
    setup_finished_job,
    setup_press_ready_job,
    validate_error,
    validate_success,
    get_success_data,
)
from test_helpers.fixtures import ADMIN, KITTER, OPERATOR
from test_helpers.api_client import api_client
from test_helpers.factories import create_press_approval_payload


class TestStartProductionGatedByPressApproval:
    def test_missing_approval_blocks_start_production(self, api):
        """PRD §3.5: "Two gates apply: every slot in the job's `required_ink_slots` must hold an `APPROVED` press approval pinned to an `ACTIVE` color standard (`ERR_PRESS_APPROVAL_MISSING`), and at least one `SCHEDULED` press booking must exist for the job (`ERR_NO_PRESS_BOOKING`)."

        Design: Difficulty/cross_entity_state_dependency/start_production_gated_by_press_approval
        """
        ctx = setup_press_ready_job(customer_name="Xi", brand_code="XII")
        create_booked_press_window(ctx)

        res = api.start_production(ctx["job"]["id"], OPERATOR)
        validate_error(res, ApiErrorId.ERR_PRESS_APPROVAL_MISSING,
                       expected_status=409)
        job_after = validate_success(api.get_job(ctx["job"]["id"], ADMIN), 200)
        assert job_after["status"] == "PRESS_READY"

    def test_approved_approval_unblocks_start_production(self, api):
        """PRD §3.5: "Production begins when a `PressOperator` starts production on a `PRESS_READY` job, moving it to `IN_PRODUCTION`."

        Design: Difficulty/cross_entity_state_dependency/start_production_gated_by_press_approval
        """
        ctx = setup_press_ready_job(customer_name="Xi", brand_code="XIB")
        create_booked_press_window(ctx)
        create_approved_press_approval(ctx)

        started = validate_success(api.start_production(ctx["job"]["id"], OPERATOR),
                                   200)
        assert started["status"] == "IN_PRODUCTION"


class TestDeltaEInclusiveTolerance:
    def _fixture(self, api, brand_code):
        """PRESS_READY job with standard tolerance 200 and two SUBMITTED
        approvals measuring 200 (== tolerance) and 201 (tolerance + 1)."""
        ctx = setup_press_ready_job(customer_name="Nu", brand_code=brand_code)
        a_boundary = get_success_data(api_client.create_press_approval(
            create_press_approval_payload(
                ctx["job"]["id"], ctx["standard"]["id"],
                measured_delta_e_milli=200),
            OPERATOR,
        ))
        a_over = get_success_data(api_client.create_press_approval(
            create_press_approval_payload(
                ctx["job"]["id"], ctx["standard"]["id"],
                measured_delta_e_milli=201),
            OPERATOR,
        ))
        return ctx, a_boundary, a_over

    def test_measured_equal_to_tolerance_approves(self, api):
        """PRD §3.4: "the boundary is inclusive, so a measurement exactly equal to the tolerance passes, and anything above it is rejected with `ERR_DELTA_E_EXCEEDED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/delta_e_inclusive_tolerance
        """
        ctx, a_boundary, _ = self._fixture(api, "NUU")
        approved = validate_success(
            api.approve_press_approval(
                a_boundary["id"],
                make_brand_quality_headers(ctx["customer"]["id"])),
            200,
        )
        assert approved["status"] == "APPROVED"

    def test_measured_one_above_tolerance_rejected(self, api):
        """PRD §3.4: "Approval by `BrandQuality` — ownership-checked against the job's `customer_id`, failing with `ERR_CUSTOMER_OWNERSHIP_MISMATCH` — moves the approval from `SUBMITTED` to `APPROVED`, but only when the `measured_delta_e_milli` is at or below the standard's `tolerance_delta_e_milli`; the boundary is inclusive, so a measurement exactly equal to the tolerance passes, and anything above it is rejected with `ERR_DELTA_E_EXCEEDED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/delta_e_inclusive_tolerance
        """
        ctx, _, a_over = self._fixture(api, "NUB")
        res = api.approve_press_approval(
            a_over["id"], make_brand_quality_headers(ctx["customer"]["id"]))
        validate_error(res, ApiErrorId.ERR_DELTA_E_EXCEEDED, expected_status=409)

        after = validate_success(api.get_press_approval(a_over["id"], ADMIN), 200)
        assert after["status"] == "SUBMITTED", "failed approve does not move the machine"


class TestJobCompleteGatedByRetailAudit:
    def test_missing_certified_audit_blocks_completion(self, api):
        """PRD §3.7: "If the job's `requires_retail_compliance` is true, a `CERTIFIED` retail-ready audit must exist for the job, or completion is rejected with `ERR_RRP_NOT_CERTIFIED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/job_complete_gated_by_retail_audit
        """
        ctx = setup_finished_job(customer_name="Omicron", brand_code="OMC",
                                 requires_retail_compliance=True)
        res = api.complete_job(ctx["job"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_RRP_NOT_CERTIFIED, expected_status=409)
        job_after = validate_success(api.get_job(ctx["job"]["id"], ADMIN), 200)
        assert job_after["status"] == "FINISHED"

    def test_certified_audit_unblocks_completion(self, api):
        """PRD §3.7: "Submitting the audit asserts the result and requires the verdict to be `COMPLIANT`; submitting a non-compliant configuration is rejected with `ERR_AUDIT_NON_COMPLIANT` (HTTP 409)."
        PRD §3.7: "Completion also releases the job's unused reservation: the stock's `reserved_sheets` decreases by whatever `reserved_sheets` the job still holds, and the job's `reserved_sheets` returns to zero. `COMPLETE` is terminal."

        Design: Difficulty/cross_entity_state_dependency/job_complete_gated_by_retail_audit
        """
        ctx = setup_finished_job(customer_name="Omicron", brand_code="OMB",
                                 requires_retail_compliance=True)
        audit = get_success_data(api_client.create_retail_audit(
            create_retail_audit_payload(ctx["job"]["id"]), KITTER))
        assert audit["verdict"] == "COMPLIANT"
        get_success_data(api_client.submit_retail_audit(audit["id"], KITTER))
        certified = get_success_data(api_client.certify_retail_audit(
            audit["id"], make_brand_quality_headers(ctx["customer"]["id"])))
        assert certified["status"] == "CERTIFIED"

        completed = validate_success(api.complete_job(ctx["job"]["id"], ADMIN), 200)
        assert completed["status"] == "COMPLETE"
        assert completed["reserved_sheets"] == 0
        stock = validate_success(api.get_board_stock(ctx["stock"]["id"], ADMIN), 200)
        assert_inv_sheets(stock)


def _audit_ctx(api, brand_code):
    customer = create_customer(name="Acme", brand_code=brand_code)
    job = create_job(customer["id"], finish_coat=False, required_ink_slots=[],
                     requires_retail_compliance=True)
    return job


def test_audit_exact_boundaries_compliant(api):
    """PRD §3.7: "Every comparison is inclusive, and the `verdict` is `COMPLIANT` only when footprint, height, weight, and count all pass; otherwise it is `NON_COMPLIANT`."

    Design: Corner/calculations/audit_exact_boundaries_compliant
    """
    job = _audit_ctx(api, "ACM")
    audit = validate_success(
        api.create_retail_audit(create_retail_audit_payload(job["id"]), KITTER), 201
    )
    assert_retail_audit(audit)
    # footprint 8*1524 == 12192 (pallet width), height 6*2540 == 15240 (max),
    # count 48 == 8*6, weight 672000 <= 680389 — all inclusive passes.
    assert audit["verdict"] == "COMPLIANT"
    assert audit["status"] == "DRAFT"


def test_audit_count_mismatch_blocks_submit(api):
    """PRD §3.7: "Count requires `case_count` to equal `cases_per_layer` times `layers` exactly."
    PRD §3.7: "Submitting the audit asserts the result and requires the verdict to be `COMPLIANT`; submitting a non-compliant configuration is rejected with `ERR_AUDIT_NON_COMPLIANT` (HTTP 409)."

    Design: Corner/calculations/audit_count_mismatch_blocks_submit
    """
    job = _audit_ctx(api, "ACN")
    audit = validate_success(
        api.create_retail_audit(
            create_retail_audit_payload(job["id"], case_count=47), KITTER
        ),
        201,
    )
    assert audit["verdict"] == "NON_COMPLIANT"  # 47 != 8*6

    res = api.submit_retail_audit(audit["id"], KITTER)
    validate_error(res, ApiErrorId.ERR_AUDIT_NON_COMPLIANT, expected_status=409)

    after = validate_success(api.get_retail_audit(audit["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"


def test_audit_orientation_contrast(api):
    """PRD §3.7: "Footprint requires, for `LENGTHWISE`, that `cases_per_layer` times `case_w_cin` be at most 12192 cin and that `case_d_cin` be at most 10160 cin; for `WIDTHWISE` the depth edge runs along the deck width, so `cases_per_layer` times `case_d_cin` must be at most 12192 cin and `case_w_cin` at most 10160 cin."

    Design: Corner/calculations/audit_orientation_contrast
    """
    job = _audit_ctx(api, "ACO")
    shared = dict(case_w_cin=10160, case_h_cin=2540, case_d_cin=12192,
                  case_weight_g=1000, cases_per_layer=1, layers=6, case_count=6)
    widthwise = validate_success(
        api.create_retail_audit(
            create_retail_audit_payload(job["id"], orientation="WIDTHWISE",
                                        **shared),
            KITTER,
        ),
        201,
    )
    # WIDTHWISE: 1*12192 <= 12192 and 10160 <= 10160 -> footprint holds.
    assert widthwise["verdict"] == "COMPLIANT"

    lengthwise = validate_success(
        api.create_retail_audit(
            create_retail_audit_payload(job["id"], orientation="LENGTHWISE",
                                        **shared),
            KITTER,
        ),
        201,
    )
    # LENGTHWISE: depth 12192 > 10160 -> footprint fails on identical case dims.
    assert lengthwise["verdict"] == "NON_COMPLIANT"


def test_audit_weight_boundary(api):
    """PRD §3.7: "Weight requires `case_count` times `case_weight_g` to be at most 680389 grams."
    PRD §3.7: "Every comparison is inclusive, and the `verdict` is `COMPLIANT` only when footprint, height, weight, and count all pass; otherwise it is `NON_COMPLIANT`."

    Design: Corner/calculations/audit_weight_boundary
    """
    job = _audit_ctx(api, "ACW")
    shared = dict(orientation="LENGTHWISE", case_w_cin=1000, case_h_cin=1000,
                  case_d_cin=1000, cases_per_layer=7, layers=7, case_count=49)
    under = validate_success(
        api.create_retail_audit(
            create_retail_audit_payload(job["id"], case_weight_g=13885, **shared),
            KITTER,
        ),
        201,
    )
    # 49 * 13885 = 680365 <= 680389
    assert under["verdict"] == "COMPLIANT"

    over = validate_success(
        api.create_retail_audit(
            create_retail_audit_payload(job["id"], case_weight_g=13886, **shared),
            KITTER,
        ),
        201,
    )
    # 49 * 13886 = 680414 > 680389
    assert over["verdict"] == "NON_COMPLIANT"
