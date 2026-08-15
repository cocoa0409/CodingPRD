"""Qualification-run review dialogue: re-measurement loop, approval gates, one-active-run constraint, cross-customer access, and OCC on spec version."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_customer, create_spec, submit_spec, begin_qualification,
    create_qualification_run, execute_run, submit_review,
    create_qualification_run_payload, review_qualification_run_payload,
    execute_qualification_run_payload,
    make_customer_quality_rep_headers,
    api_client, ApiErrorId, TEST_USERS,
)

ENGINEER = TEST_USERS["process_engineer"]


def _setup_run_in_customer_review(api, measured_mean_weight_g=22.1):
    """Customer + spec IN_QUALIFICATION with one run in CUSTOMER_REVIEW."""
    customer = create_customer()
    spec = create_spec(customer["id"], label_type="NONE")
    submit_spec(spec["id"])
    begin = begin_qualification(spec["id"])
    qrun = create_qualification_run(spec["id"], begin["version"])
    execute_run(qrun["id"], measured_mean_weight_g=measured_mean_weight_g)
    qrun = submit_review(qrun["id"])
    assert qrun["status"] == "CUSTOMER_REVIEW"
    return customer, spec, qrun, begin


class TestRequestMoreDataCycle:
    def test_request_more_data_returns_run_to_executed(self, api):
        """PRD §3.2: "`REQUEST_MORE_DATA` returns the run from `CUSTOMER_REVIEW` to `EXECUTED` for re-measurement." At creation the run "receives the next 1-based `round_no` among the spec's runs ordered by creation".

Design: Corner/state_machines/qualification_review_request_more_data_cycles"""
        customer, spec, qrun, _ = _setup_run_in_customer_review(api)
        res = api.review_qualification_run(
            qrun["id"],
            review_qualification_run_payload(
                "REQUEST_MORE_DATA", review_note="re-weigh cavity 5"),
            make_customer_quality_rep_headers(customer["id"]))
        run_after = validate_success(res, 200)
        assert run_after["status"] == "EXECUTED"
        assert run_after["round_no"] == 1, (
            "the review cycle must not consume a new qualification round")

    def test_reexecute_after_request_more_data_succeeds(self, api):
        """PRD §3.2: "Executing a run — allowed from `PLANNED`, and again from `EXECUTED` itself when the customer has asked for more data". "it is true when the absolute difference between `measured_mean_weight_g` and the spec's `target_weight_g` is less than or equal to `target_weight_g` multiplied by `weight_tolerance_pct` and divided by 100".

Design: Corner/state_machines/qualification_review_request_more_data_cycles"""
        customer, spec, qrun, _ = _setup_run_in_customer_review(api)
        api.review_qualification_run(
            qrun["id"], review_qualification_run_payload("REQUEST_MORE_DATA"),
            make_customer_quality_rep_headers(customer["id"]))
        res = api.execute_qualification_run(
            qrun["id"],
            execute_qualification_run_payload(measured_mean_weight_g=22.0),
            ENGINEER)
        rerun = validate_success(res, 200)
        assert rerun["status"] == "EXECUTED"
        assert rerun["weight_within_tolerance"] is True, (
            "|22.0 - 22| = 0 <= 22 * 2.0 / 100 = 0.44")


class TestApprovalGates:
    def test_weight_out_of_tolerance_blocks_approve(self, api):
        """PRD §3.2: "Approval is gated twice: `weight_within_tolerance` must be true, otherwise the review is rejected with `ERR_WEIGHT_OUT_OF_TOLERANCE`".

Design: Corner/validations/weight_out_of_tolerance_blocks_approve"""
        # measured 23.0 vs target 22 with 2.0% tolerance (band ±0.44)
        customer, spec, qrun, _ = _setup_run_in_customer_review(
            api, measured_mean_weight_g=23.0)
        run_data = get_success_data(api.get_qualification_run(qrun["id"], ENGINEER))
        assert run_data["weight_within_tolerance"] is False, (
            "|23.0 - 22| = 1.0 > 0.44 must be out of tolerance")
        res = api.review_qualification_run(
            qrun["id"], review_qualification_run_payload("APPROVE"),
            make_customer_quality_rep_headers(customer["id"]))
        validate_error(res, ApiErrorId.ERR_WEIGHT_OUT_OF_TOLERANCE)
        run_after = get_success_data(api.get_qualification_run(qrun["id"], ENGINEER))
        assert run_after["status"] == "CUSTOMER_REVIEW"


class TestOneActiveRun:
    def test_active_qualification_run_blocks_second_run(self, api):
        """PRD §3.2: "Only one run per spec may be in flight: if another run of the same spec sits in `PLANNED`, `EXECUTED`, or `CUSTOMER_REVIEW`, the create fails with `ERR_ACTIVE_QUALIFICATION_EXISTS`."

Design: Corner/validations/active_qualification_run_blocks_second_run"""
        customer = create_customer()
        spec = create_spec(customer["id"], label_type="NONE")
        submit_spec(spec["id"])
        begin = begin_qualification(spec["id"])
        create_qualification_run(spec["id"], begin["version"])  # run 1 PLANNED
        # re-read the spec to pass OCC with the CURRENT version
        spec_fresh = get_success_data(api.get_bottle_spec(spec["id"], ENGINEER))
        res = api.create_qualification_run(
            create_qualification_run_payload(
                spec["id"], spec_fresh["version"], sample_cavity_count=4),
            ENGINEER)
        validate_error(res, ApiErrorId.ERR_ACTIVE_QUALIFICATION_EXISTS)


class TestCrossCustomerAccess:
    def test_cross_customer_review_rejected(self, api):
        """PRD §2.1: "A `CustomerQualityRep` who attempts to review a qualification run belonging to a different customer, or to list another customer's specifications, is rejected with `ERR_CROSS_CUSTOMER_ACCESS` (HTTP 403)."

Design: Corner/validations/cross_customer_review_rejected"""
        customer, spec, qrun, _ = _setup_run_in_customer_review(api)
        other = create_customer(name="Other Co", customer_code="OTHER")
        res = api.review_qualification_run(
            qrun["id"], review_qualification_run_payload("APPROVE"),
            make_customer_quality_rep_headers(other["id"]))
        validate_error(res, ApiErrorId.ERR_CROSS_CUSTOMER_ACCESS)
        run_after = get_success_data(api.get_qualification_run(qrun["id"], ENGINEER))
        assert run_after["status"] == "CUSTOMER_REVIEW"
        spec_after = get_success_data(api.get_bottle_spec(spec["id"], ENGINEER))
        assert spec_after["status"] == "IN_QUALIFICATION"


class TestOccOnSpecVersion:
    def test_stale_spec_version_rejected_on_run_create(self, api):
        """PRD §2.7: "Creating a qualification run requires `expected_bottle_spec_version` matching the spec's current `version`", and "a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)".
PRD §3.2: "At creation the run pins `spec_revision_pinned` to the spec's current `content_revision` (bumping the spec's `version`)".

Design: Corner/cross_cutting_layers/occ_qualification_create_stale_spec_rejected"""
        customer = create_customer()
        spec = create_spec(customer["id"], label_type="NONE")
        submit_spec(spec["id"])
        begin = begin_qualification(spec["id"])
        stale_version = begin["version"]
        create_qualification_run(spec["id"], stale_version)  # bumps spec version
        res = api.create_qualification_run(
            create_qualification_run_payload(
                spec["id"], stale_version, sample_cavity_count=4),
            ENGINEER)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
