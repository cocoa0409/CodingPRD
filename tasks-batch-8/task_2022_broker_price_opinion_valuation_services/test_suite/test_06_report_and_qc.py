"""Report submission floors, QC cycle gates, verdict defect rules, and
segregation of duties."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_fee,
    add_photo,
    add_photo_set_for_order,
    add_selected_comps,
    create_qc_verdict_payload,
    drive_order_to_in_progress,
    drive_order_to_report_submitted,
    get_order,
    make_broker_headers,
    make_qc_reviewer_headers,
    open_qc,
    setup_market,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

QC = TEST_USERS["qc_reviewer_headers"]


class TestReportSubmissionFloors:
    def test_insufficient_comparables_wins_over_fee_mismatch(self, api):
        """PRD §2.9: "10. Comparable-count floor at report submission
        (`ERR_INSUFFICIENT_COMPARABLES`)."
        PRD §2.9: "12. Fee reconciliation at report submission
        (`ERR_FEE_RECONCILE_MISMATCH`)."

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_report
        """
        env = setup_market("GA", client_code="CLJ", broker_code="BRKJ")
        order = drive_order_to_in_progress(env, agreed_fee_cents=10000)
        # Only 2 SELECTED comparables (floor is 3 for DRIVE_BY) AND fee lines
        # sum to 9000 against an agreed 10000: both floors fail at once.
        add_selected_comps(env, order, count=2)
        add_photo_set_for_order(env, order)
        add_fee(env, order, 9000)

        resp = api.submit_report(order["id"],
                                 make_broker_headers(env["broker"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_COMPARABLES)
        assert get_order(order["id"])["fulfillment_status"] == "IN_PROGRESS"

    def test_fee_mismatch_alone_returns_reconcile_error(self, api):
        """PRD §3.6: "Fee reconciliation requires the sum of `amount_cents`
        across all fee lines whose `status` is not `CANCELLED` to equal the
        order's `agreed_fee_cents` exactly, else `ERR_FEE_RECONCILE_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_report
        """
        env = setup_market("GA", client_code="CLJ", broker_code="BRKJ")
        order = drive_order_to_in_progress(env, agreed_fee_cents=10000)
        # Comparable floor and photo floor satisfied; only the fee floor fails.
        add_selected_comps(env, order, count=3)
        add_photo_set_for_order(env, order)
        add_fee(env, order, 9000)

        resp = api.submit_report(order["id"],
                                 make_broker_headers(env["broker"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FEE_RECONCILE_MISMATCH)
        assert get_order(order["id"])["fulfillment_status"] == "IN_PROGRESS"


class TestPhotoFloor:
    def test_error_insufficient_photos_interior(self, api):
        """PRD §3.6: "The photo-evidence minimum requires, for a `DRIVE_BY`
        order, at least 2 photo rows whose `photo_kind` is `FRONT` or `STREET`,
        and for an `INTERIOR` order, at least 3 photo rows covering one each of
        `INTERIOR_LIVING`, `INTERIOR_KITCHEN`, and `INTERIOR_BATH` — else
        `ERR_INSUFFICIENT_PHOTOS`."

        Design: Corner/errors/error_insufficient_photos_interior
        """
        env = setup_market("AL", client_code="CIP", broker_code="BIP",
                           license_kind="APPRAISAL",
                           reg_overrides={"appraisal_required_for_interior": True})
        order = drive_order_to_in_progress(
            env, order_kind="APPRAISAL", inspection_level="INTERIOR",
            agreed_fee_cents=25000)
        add_selected_comps(env, order, count=4)
        # Only two of the three required interior kinds; INTERIOR_BATH missing.
        add_photo(env, order, "INTERIOR_LIVING")
        add_photo(env, order, "INTERIOR_KITCHEN")
        add_fee(env, order, 25000)

        resp = api.submit_report(order["id"],
                                 make_broker_headers(env["broker"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PHOTOS)
        assert get_order(order["id"])["fulfillment_status"] == "IN_PROGRESS"


class TestQcVerdictDefectRules:
    def test_qc_verdict_approve_with_defects_rejected(self, api):
        """PRD §3.6: "An `APPROVE` verdict requires `defects_found` to be exactly
        0 (`ERR_INVALID_REQUEST` otherwise)."

        Design: Corner/state_machines/qc_verdict_approve_with_defects_rejected
        """
        env = setup_market("SC", client_code="CT3", broker_code="BT3")
        order = drive_order_to_report_submitted(env)
        qc_review = open_qc(order)

        payload = create_qc_verdict_payload(
            verdict="APPROVE", defects_found=2, notes="bad combo")
        resp = api.record_qc_verdict(order["id"], qc_review["id"], payload, QC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert get_order(order["id"])["fulfillment_status"] == "QC_REVIEW"

    def test_qc_verdict_revise_with_zero_defects_rejected(self, api):
        """PRD §3.6: "A `REVISE` verdict requires `defects_found` of at least 1
        (`ERR_INVALID_REQUEST` otherwise)."

        Design: Corner/state_machines/qc_verdict_revise_with_zero_defects_rejected
        """
        env = setup_market("KY", client_code="CT4", broker_code="BT4")
        order = drive_order_to_report_submitted(env)
        qc_review = open_qc(order)

        payload = create_qc_verdict_payload(
            verdict="REVISE", defects_found=0, notes="no defects")
        resp = api.record_qc_verdict(order["id"], qc_review["id"], payload, QC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert get_order(order["id"])["fulfillment_status"] == "QC_REVIEW"


class TestQcCycleGate:
    def test_qc_open_when_cycle_already_open_rejected(self, api):
        """PRD §3.6: "A `QCReviewer` opens a cycle, moving the order from
        `REPORT_SUBMITTED` to `QC_REVIEW`; if any cycle is already open for the
        order, the attempt is rejected with `ERR_QC_CYCLE_ALREADY_OPEN`."
        (An open cycle implies the order sits in QC_REVIEW, so the generic
        state-legality rejection of PRD §2.9 item 5 is an equally valid
        discharge.)

        Design: Corner/state_machines/qc_open_when_cycle_already_open_rejected
        """
        env = setup_market("TN", client_code="CT5", broker_code="BT5")
        order = drive_order_to_report_submitted(env)
        open_qc(order)

        resp = api.open_qc_review(order["id"], QC)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_QC_CYCLE_ALREADY_OPEN,
                   ApiErrorId.ERR_INVALID_STATE])


class TestQcRbac:
    def test_broker_cannot_open_qc_review(self, api):
        """PRD §2.1: "If the headers are present but the named role is not
        permitted to invoke the target endpoint, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /bpo/valuation-orders/{id}/qc/open is authorized for
        QCReviewer only.

        Design: Corner/rbac/broker_cannot_open_qc_review
        """
        env = setup_market("OK", client_code="CRB", broker_code="BRB")
        order = drive_order_to_report_submitted(env)

        resp = api.open_qc_review(order["id"], env["broker_headers"])
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert get_order(order["id"])["fulfillment_status"] == "REPORT_SUBMITTED"


class TestSegregationOfDuties:
    def test_error_segregation_of_duties(self, api):
        """PRD §2.8: "When a `QCReviewer` records a verdict on an order, the
        reviewer's `X-User-ID` (an opaque identifier) is compared against the
        opaque identity derived from the order's assigned broker. If the two
        coincide, the verdict is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403)."
        PRD §2.8: "marking the review's read-only `is_segregation_violation`
        flag true for audit purposes — true if and only if the reviewer's opaque
        id equals the assigned broker's derived opaque id — even though the
        verdict itself is refused."

        Design: Corner/errors/error_segregation_of_duties
        """
        env = setup_market("IA", client_code="CSD", broker_code="BSD")
        order = drive_order_to_report_submitted(env)
        qc_review = open_qc(order)

        payload = create_qc_verdict_payload(
            verdict="APPROVE", defects_found=0, notes="self-review")
        resp = api.record_qc_verdict(
            order["id"], qc_review["id"], payload,
            make_qc_reviewer_headers(env["broker"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        review = validate_success(api.get_qc_review(qc_review["id"], QC))
        assert review["is_segregation_violation"] is True, (
            "The refused self-review must be recorded via is_segregation_violation")
        assert get_order(order["id"])["fulfillment_status"] == "QC_REVIEW"
