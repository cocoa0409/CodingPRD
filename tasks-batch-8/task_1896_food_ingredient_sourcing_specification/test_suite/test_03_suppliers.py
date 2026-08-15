"""Supplier registration, qualification boundaries, and requalification cycle."""
from test_helpers import (
    QM_1,
    SQE_1,
    ApiErrorId,
    create_qualification_payload,
    create_qualified_supplier,
    create_supplier_entity,
    create_supplier_payload,
    make_quality_manager_headers,
    make_sqe_headers,
    validate_error,
    validate_success,
)


class TestQualificationScoreBoundary:
    def test_qualification_score_exactly_70_passes(self, api, quality_manager_headers):
        """PRD §3.3: "Approving requires three checks: the `questionnaire_score`
        must be at least 70 (exactly 70 passes; anything below is rejected with
        `ERR_QUALIFICATION_SCORE_TOO_LOW`), `document_pack_complete` must be true
        (otherwise `ERR_DOCUMENT_PACK_INCOMPLETE`), and `decision_note` must be
        present (otherwise `ERR_INVALID_REQUEST`)." On approval "the supplier
        transitions from `IN_QUALIFICATION` to `QUALIFIED`".

        Design: Difficulty/boundary_precision_check/qualification_score_exactly_70_passes
        """
        supplier = create_supplier_entity("SUP-B1")
        qual = validate_success(api.create_qualification(
            supplier["id"],
            create_qualification_payload(questionnaire_score=70, document_pack_complete=True),
            make_sqe_headers(SQE_1),
        ), expected_status=201)
        validate_success(api.evaluate_qualification(supplier["id"], qual["id"], make_quality_manager_headers(QM_1)))

        decided = validate_success(api.decide_qualification(
            supplier["id"], qual["id"],
            {"decision": "APPROVE", "decision_note": "score at threshold"},
            make_quality_manager_headers(QM_1),
        ))
        assert decided["status"] == "APPROVED", "exactly 70 is inside the >= boundary"
        after = validate_success(api.get_supplier(supplier["id"], quality_manager_headers))
        assert after["status"] == "QUALIFIED"

    def test_qualification_score_69_rejected(self, api):
        """PRD §3.3: "the `questionnaire_score` must be at least 70 (exactly 70
        passes; anything below is rejected with `ERR_QUALIFICATION_SCORE_TOO_LOW`)"
        — 69 is one below the inclusive boundary and must be rejected.

        Design: Difficulty/boundary_precision_check/qualification_score_exactly_70_passes
        """
        supplier = create_supplier_entity("SUP-B2")
        qual = validate_success(api.create_qualification(
            supplier["id"],
            create_qualification_payload(questionnaire_score=69, document_pack_complete=True),
            make_sqe_headers(SQE_1),
        ), expected_status=201)
        validate_success(api.evaluate_qualification(supplier["id"], qual["id"], make_quality_manager_headers(QM_1)))

        resp = api.decide_qualification(
            supplier["id"], qual["id"],
            {"decision": "APPROVE", "decision_note": "score below threshold"},
            make_quality_manager_headers(QM_1),
        )
        validate_error(resp, ApiErrorId.ERR_QUALIFICATION_SCORE_TOO_LOW)


class TestQualificationLifecycle:
    def test_second_open_qualification_blocked(self, api, quality_manager_headers):
        """PRD §3.3: "The open is rejected with `ERR_INVALID_STATE` if the supplier
        is not in `PROSPECT` or `SUSPENDED` status, and with
        `ERR_QUALIFICATION_IN_PROGRESS` if another qualification for the same
        supplier is already `SUBMITTED` or `UNDER_EVALUATION`." and "Opening the
        qualification moves the supplier to `IN_QUALIFICATION`". PRD §2.12 orders
        "state-machine permission for the requested transition" ahead of the
        cascade guards ("duplicate in-progress qualification"), so with the
        supplier already `IN_QUALIFICATION` the state guard is the one that fires.

        Design: Corner/state_machines/second_open_qualification_blocked
        """
        supplier = create_supplier_entity("SUP-QP")
        validate_success(api.create_qualification(
            supplier["id"],
            create_qualification_payload(questionnaire_score=80, document_pack_complete=True),
            make_sqe_headers(SQE_1),
        ), expected_status=201)

        resp = api.create_qualification(
            supplier["id"],
            create_qualification_payload(questionnaire_score=95, document_pack_complete=True),
            make_sqe_headers(SQE_1),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_supplier(supplier["id"], quality_manager_headers))
        assert after["status"] == "IN_QUALIFICATION", "the rejected open must not move the supplier"

    def test_supplier_requalification_cycle_from_suspended(self, api, quality_manager_headers):
        """PRD §3.3: "if the supplier's previous status was `SUSPENDED`, the
        supplier's `requalification_cycle` increments by one" and "On rejection the
        qualification becomes `REJECTED` and the supplier's return path depends on
        its history: if `requalification_cycle` is zero the supplier returns to
        `PROSPECT`; if the cycle is greater than zero (a requalification after a
        suspension), the supplier returns to `SUSPENDED`."

        Design: Corner/state_machines/supplier_requalification_cycle_from_suspended
        """
        supplier = create_qualified_supplier("SUP-RQ", risk_tier="TIER_B", questionnaire_score=85)
        validate_success(api.suspend_supplier(supplier["id"], make_quality_manager_headers(QM_1)))

        # Re-open qualification from SUSPENDED.
        qual2 = validate_success(api.create_qualification(
            supplier["id"],
            create_qualification_payload(questionnaire_score=60, document_pack_complete=False),
            make_sqe_headers(SQE_1),
        ), expected_status=201)
        mid = validate_success(api.get_supplier(supplier["id"], quality_manager_headers))
        assert mid["requalification_cycle"] == 1, "re-entry from SUSPENDED increments the cycle"
        assert mid["status"] == "IN_QUALIFICATION"

        validate_success(api.evaluate_qualification(supplier["id"], qual2["id"], make_quality_manager_headers(QM_1)))
        validate_success(api.decide_qualification(
            supplier["id"], qual2["id"],
            {"decision": "REJECT", "decision_note": "documents still missing"},
            make_quality_manager_headers(QM_1),
        ))
        final = validate_success(api.get_supplier(supplier["id"], quality_manager_headers))
        assert final["status"] == "SUSPENDED", "requalification failure returns to SUSPENDED, not PROSPECT"

    def test_document_pack_incomplete_blocks_qualification_approve(self, api):
        """PRD §3.3: "`document_pack_complete` must be true (otherwise
        `ERR_DOCUMENT_PACK_INCOMPLETE`)".

        Design: Corner/validations/document_pack_incomplete_blocks_qualification_approve
        """
        supplier = create_supplier_entity("SUP-DOC")
        qual = validate_success(api.create_qualification(
            supplier["id"],
            create_qualification_payload(questionnaire_score=90, document_pack_complete=False),
            make_sqe_headers(SQE_1),
        ), expected_status=201)
        validate_success(api.evaluate_qualification(supplier["id"], qual["id"], make_quality_manager_headers(QM_1)))

        resp = api.decide_qualification(
            supplier["id"], qual["id"],
            {"decision": "APPROVE", "decision_note": "attempting approve without pack"},
            make_quality_manager_headers(QM_1),
        )
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_PACK_INCOMPLETE)

    def test_rbac_spec_author_cannot_create_supplier(self, api, spec_author_headers):
        """PRD §2.1: "Once the headers are present, the role named in `X-User-Role`
        is checked against the RBAC matrix for the target endpoint; a role that is
        not permitted for the endpoint is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)." PRD §4 restricts POST /sourcing/suppliers to ProcurementManager.

        Design: Corner/roles/rbac_spec_author_cannot_create_supplier
        """
        resp = api.create_supplier(
            create_supplier_payload(supplier_code="RBAC-1", legal_name="Rbac Supplier"),
            spec_author_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
