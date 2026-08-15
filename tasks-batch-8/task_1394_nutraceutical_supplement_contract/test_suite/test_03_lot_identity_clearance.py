"""Material lot identity testing, COA review, retest cycle, and SoD (PRD §3.2)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_identity_test,
    coa_review,
    create_material_lot,
    create_raw_material,
    get_material_lot,
    make_qa_manager_headers,
    submit_identity_test,
    validate_error,
)

CHEMIST = TEST_USERS["qa_chemist_headers"]
QA = TEST_USERS["qa_manager_headers"]


def _received_lot(qty=100000):
    material = create_raw_material("VitC", "NONE")
    lot = create_material_lot(material["id"], qty_received=qty)
    return lot


class TestIdentityClearancePath:
    def test_lot_full_path_quarantine_to_released(self, api):
        """PRD §3.2: "a `PASS` result drives the lot to `IDENTITY_PASSED`, a `FAIL`
        result drives it to `IDENTITY_FAILED`."
        PRD §3.2: "Approval moves the test to `COA_APPROVED` with `reviewed_by_id`
        recorded, and releases the lot: `IDENTITY_PASSED` → `RELEASED`."

        Design: Corner/state_machines/lot_full_path_quarantine_to_released
        """
        lot = _received_lot()
        assert lot["status"] == "QUARANTINE"

        test = submit_identity_test(lot["id"], result="PASS", coa_match=True)
        assert_identity_test(test)
        assert test["status"] == "SUBMITTED"
        assert test["tested_by_id"] == "chem-1"
        assert get_material_lot(lot["id"])["status"] == "IDENTITY_PASSED"

        reviewed = coa_review(test["id"], "APPROVE", qm_id="qm-1")
        assert reviewed["status"] == "COA_APPROVED"
        assert reviewed["reviewed_by_id"] == "qm-1"
        assert get_material_lot(lot["id"])["status"] == "RELEASED"

    def test_failed_lot_retest_cycle_returns_to_passed(self, api):
        """PRD §3.2: "A failed lot is not dead — the retest cycle permits a later
        passing submission to carry it from `IDENTITY_FAILED` back to
        `IDENTITY_PASSED`."

        Design: Corner/state_machines/lot_retest_cycle_failed_then_passed
        """
        lot = _received_lot()
        submit_identity_test(lot["id"], result="FAIL", coa_match=False)
        assert get_material_lot(lot["id"])["status"] == "IDENTITY_FAILED"

        retest = submit_identity_test(lot["id"], result="PASS", coa_match=True)
        assert get_material_lot(lot["id"])["status"] == "IDENTITY_PASSED"

        coa_review(retest["id"], "APPROVE")
        assert get_material_lot(lot["id"])["status"] == "RELEASED"

    def test_identity_test_on_released_lot_rejected(self, api):
        """PRD §3.2: "A `QAChemist` submits an identity test against a lot whose
        status is `QUARANTINE` or `IDENTITY_FAILED` — any other posture is rejected
        with `ERR_LOT_STATE`".

        Design: Corner/state_machines/identity_test_on_released_lot_rejected
        """
        lot = _received_lot()
        test = submit_identity_test(lot["id"], result="PASS", coa_match=True)
        coa_review(test["id"], "APPROVE")
        assert get_material_lot(lot["id"])["status"] == "RELEASED"

        resp = api.submit_identity_test(
            lot["id"], {"result": "PASS", "coa_match": True}, CHEMIST
        )
        validate_error(resp, ApiErrorId.ERR_LOT_STATE)
        assert resp.status_code == 409


class TestCoaReviewRules:
    def test_coa_review_twice_rejected_terminal(self, api):
        """PRD §3.2: "The review is rejected with `ERR_IDENTITY_TEST_STATE` unless
        the test is still `SUBMITTED`" and "Both `COA_APPROVED` and `COA_REJECTED`
        are terminal for the test."

        Design: Corner/state_machines/coa_review_twice_rejected
        """
        lot = _received_lot()
        test = submit_identity_test(lot["id"], result="PASS", coa_match=True)
        coa_review(test["id"], "APPROVE", qm_id="qm-1")

        resp = api.coa_review_identity_test(
            test["id"], {"review_outcome": "REJECT"}, make_qa_manager_headers("qm-2")
        )
        validate_error(resp, ApiErrorId.ERR_IDENTITY_TEST_STATE)
        assert resp.status_code == 409
        assert get_material_lot(lot["id"])["status"] == "RELEASED", (
            "the released lot must be unchanged by the rejected second review"
        )

    def test_coa_review_by_testing_user_rejected_sod(self, api):
        """PRD §2.10: "When the two identifiers are equal — the same person
        attempting to check their own work — the request is rejected with
        `ERR_SOD_VIOLATION` (HTTP 403)."
        PRD §2.10: "The comparisons target, respectively, the identity test's
        `tested_by_id`, the batch's `recorded_by_id`, the cleaning validation's
        `recorded_by_id`, and the assay's `submitted_by_id`."

        Design: Corner/state_machines/coa_review_by_testing_user_rejected_sod
        """
        lot = _received_lot()
        test = submit_identity_test(
            lot["id"], result="PASS", coa_match=True, chemist_id="shared-1"
        )
        assert test["tested_by_id"] == "shared-1"

        resp = api.coa_review_identity_test(
            test["id"], {"review_outcome": "APPROVE"}, make_qa_manager_headers("shared-1")
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        assert resp.status_code == 403

    def test_coa_approve_of_fail_test_rejected_then_reject_rejects_lot(self, api):
        """PRD §3.2: "an `APPROVE` outcome is lawful only on a test whose `result`
        was `PASS` — attempting to approve a failed identity test is rejected with
        `ERR_INVALID_REQUEST`."
        PRD §3.2: "Rejection moves the test to `COA_REJECTED` with `reviewed_by_id`
        recorded, and drives the lot to the terminal `REJECTED` status — whether
        the lot sat at `IDENTITY_PASSED` or `IDENTITY_FAILED`."

        Design: Corner/state_machines/coa_approve_of_fail_test_returns_invalid_request
        """
        lot = _received_lot()
        test = submit_identity_test(lot["id"], result="FAIL", coa_match=False)
        assert get_material_lot(lot["id"])["status"] == "IDENTITY_FAILED"

        approve_resp = api.coa_review_identity_test(
            test["id"], {"review_outcome": "APPROVE"}, QA
        )
        validate_error(approve_resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert approve_resp.status_code == 400

        rejected = coa_review(test["id"], "REJECT", qm_id="qm-1")
        assert rejected["status"] == "COA_REJECTED"
        assert rejected["reviewed_by_id"] == "qm-1"
        assert get_material_lot(lot["id"])["status"] == "REJECTED"
