"""Request-close compliance gates, the two-dimensional closing verification, close
state legality, and invoice payment state legality."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId, TEST_USERS,
    make_active_listing_file, make_active_purchase_file,
    get_milestone_by_name, get_file_invoice, get_file_closing_verification,
    clear_to_close, request_close, run_audit, accept_document,
    complete_milestone,
)


def _drive_to_pending_close_purchase(scen, doc_acceptances):
    """Shared path: accept the listed documents, audit, complete the single mandatory
    'Earnest Money' milestone, request close. doc_acceptances is a list of
    (doc_type, which) where which is 'buyer' or 'seller'."""
    coord_h, file_id = scen["coord_h"], scen["file"]["id"]
    for doc_type, which in doc_acceptances:
        accept_document(coord_h, scen[f"{which}_h"], file_id, doc_type)
    audit = run_audit(coord_h, file_id)
    assert audit["result"] == "PASS"
    ms = get_milestone_by_name(coord_h, file_id, "Earnest Money")
    complete_milestone(coord_h, ms["id"])
    f = request_close(coord_h, file_id)
    assert f["status"] == "PENDING_CLOSE"
    return get_file_closing_verification(coord_h, file_id)


class TestClosingVerificationDimensions:
    def test_closing_verification_parallel_title_lender_dimensions(self):
        """PRD §3.8: "A `TitleRep` — and only a `TitleRep` — confirms title clearance,
        moving `title_status` from `PENDING` to `CLEARED`. A `LenderRep` — and only a
        `LenderRep` — confirms lender clearance, moving `lender_status` from `PENDING`
        to `CLEAR_TO_CLOSE` (a `NOT_REQUIRED` lender side never moves). The derived
        `overall_status` is `CLEAR_TO_CLOSE` exactly when `title_status` is `CLEARED`
        and `lender_status` is either `CLEAR_TO_CLOSE` or `NOT_REQUIRED`, and
        `PENDING` otherwise; each confirmation recomputes it."

        Design: Corner/state_machines/closing_verification_parallel_title_lender_dimensions
        """
        scen = make_active_purchase_file(
            milestone_defs=[{"name": "Earnest Money", "offset_days": 3, "mandatory": True}],
            required_doc_types=["EXECUTED_CONTRACT"],
        )
        cv = _drive_to_pending_close_purchase(
            scen,
            [("EXECUTED_CONTRACT", "buyer"), ("T47_DISCLOSURE", "seller")],
        )
        assert cv["title_status"] == "PENDING"
        assert cv["lender_status"] == "PENDING"
        assert cv["overall_status"] == "PENDING"

        validate_success(api_client.confirm_title(cv["id"], TEST_USERS["title_rep_headers"]))
        mid = validate_success(api_client.get_closing_verification(cv["id"], scen["coord_h"]))
        assert mid["title_status"] == "CLEARED"
        assert mid["lender_status"] == "PENDING"
        assert mid["overall_status"] == "PENDING", \
            "title alone cannot clear the file while the lender side is PENDING"

        validate_success(api_client.confirm_lender(cv["id"], TEST_USERS["lender_rep_headers"]))
        end = validate_success(api_client.get_closing_verification(cv["id"], scen["coord_h"]))
        assert end["lender_status"] == "CLEAR_TO_CLOSE"
        assert end["overall_status"] == "CLEAR_TO_CLOSE"

    def test_cash_file_lender_dimension_not_required(self):
        """PRD §3.7: "Success creates the file's one-and-only `ClosingVerification`
        with `title_status` `PENDING` and `lender_status` initialized to
        `NOT_REQUIRED` when the file has no `FINANCING` deadline (a cash deal) and to
        `PENDING` otherwise."
        PRD §3.8: "The derived `overall_status` is `CLEAR_TO_CLOSE` exactly when
        `title_status` is `CLEARED` and `lender_status` is either `CLEAR_TO_CLOSE` or
        `NOT_REQUIRED`, and `PENDING` otherwise; each confirmation recomputes it."

        Design: Corner/state_machines/cash_file_lender_dimension_not_required
        """
        scen = make_active_purchase_file(
            milestone_defs=[{"name": "Earnest Money", "offset_days": 3, "mandatory": True}],
            required_doc_types=["EXECUTED_CONTRACT"],
            financing_offset_days=None,
        )
        cv = _drive_to_pending_close_purchase(
            scen,
            [("EXECUTED_CONTRACT", "buyer"), ("T47_DISCLOSURE", "seller")],
        )
        assert cv["lender_status"] == "NOT_REQUIRED", \
            "a cash file has no FINANCING deadline, so the lender side is NOT_REQUIRED"
        validate_success(api_client.confirm_title(cv["id"], TEST_USERS["title_rep_headers"]))
        end = validate_success(api_client.get_closing_verification(cv["id"], scen["coord_h"]))
        assert end["title_status"] == "CLEARED"
        assert end["overall_status"] == "CLEAR_TO_CLOSE", \
            "title clearance alone closes the join when the lender side is NOT_REQUIRED"

    def test_file_close_gated_by_closing_verification(self):
        """PRD §3.8: "Closing moves `PENDING_CLOSE → CLOSED`. The file must be in
        `PENDING_CLOSE` (`ERR_FILE_NOT_PENDING_CLOSE`) and the verification's
        `overall_status` must be `CLEAR_TO_CLOSE` (`ERR_NOT_CLEAR_TO_CLOSE`)."
        PRD §3.8: "The derived `overall_status` is `CLEAR_TO_CLOSE` exactly when
        `title_status` is `CLEARED` and `lender_status` is either `CLEAR_TO_CLOSE` or
        `NOT_REQUIRED`, and `PENDING` otherwise; each confirmation recomputes it."

        Design: Difficulty/cross_entity_state_dependency/file_close_gated_by_closing_verification
        """
        scen = make_active_purchase_file(
            milestone_defs=[
                {"name": "Earnest Money", "offset_days": 3, "mandatory": True},
                {"name": "Inspection Period", "offset_days": 7, "mandatory": True},
                {"name": "Financing Approval", "offset_days": 21, "mandatory": False},
            ],
            required_doc_types=["EXECUTED_CONTRACT", "TITLE_COMMITMENT"],
        )
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        accept_document(coord_h, scen["buyer_h"], file_id, "EXECUTED_CONTRACT")
        accept_document(coord_h, scen["seller_h"], file_id, "TITLE_COMMITMENT")
        accept_document(coord_h, scen["buyer_h"], file_id, "T47_DISCLOSURE")
        audit = run_audit(coord_h, file_id)
        assert audit["result"] == "PASS"
        complete_milestone(coord_h, get_milestone_by_name(coord_h, file_id, "Earnest Money")["id"])
        complete_milestone(coord_h, get_milestone_by_name(coord_h, file_id, "Inspection Period")["id"])
        api_client.waive_milestone(
            get_milestone_by_name(coord_h, file_id, "Financing Approval")["id"], coord_h
        )
        request_close(coord_h, file_id)
        cv = get_file_closing_verification(coord_h, file_id)

        # The file is PENDING_CLOSE but the verification is still PENDING.
        resp = api_client.close_file(file_id, coord_h)
        validate_error(resp, ApiErrorId.ERR_NOT_CLEAR_TO_CLOSE)

        validate_success(api_client.confirm_title(cv["id"], TEST_USERS["title_rep_headers"]))
        mid = validate_success(api_client.get_closing_verification(cv["id"], coord_h))
        assert mid["overall_status"] == "PENDING", "lender side still PENDING"
        validate_success(api_client.confirm_lender(cv["id"], TEST_USERS["lender_rep_headers"]))
        end = validate_success(api_client.get_closing_verification(cv["id"], coord_h))
        assert end["overall_status"] == "CLEAR_TO_CLOSE"

        closed = validate_success(api_client.close_file(file_id, coord_h))
        assert closed["status"] == "CLOSED"
        assert closed["fee_final_cents"] == 39500, "0 EFFECTIVE amendments: base only"
        invoice = get_file_invoice(coord_h, file_id)
        assert invoice["status"] == "ISSUED"
        assert invoice["total_cents"] == 39500


class TestRequestCloseGates:
    def test_request_close_without_audit_rejected(self):
        """PRD §3.7: "Requesting close moves `ACTIVE → PENDING_CLOSE` and enforces
        the compliance gates in fixed sub-order, so the first failing gate is the
        reported one: `last_audit_status` must be `PASS` (`ERR_AUDIT_NOT_PASSED`);
        every mandatory milestone must be `COMPLETED`
        (`ERR_MANDATORY_MILESTONES_OPEN`); and `open_escalation_count` must be 0
        (`ERR_OPEN_ESCALATIONS`)."

        Design: Corner/validations/request_close_without_audit_rejected
        """
        scen = make_active_listing_file(state_code="CO")
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        # No audit was ever run: last_audit_status is NONE.
        resp = api_client.request_close_file(file_id, coord_h)
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_PASSED)
        fetched = validate_success(api_client.get_file(file_id, coord_h))
        assert fetched["status"] == "ACTIVE"

    def test_request_close_with_mandatory_milestone_open_rejected(self):
        """PRD §3.7: "Requesting close moves `ACTIVE → PENDING_CLOSE` and enforces
        the compliance gates in fixed sub-order, so the first failing gate is the
        reported one: `last_audit_status` must be `PASS` (`ERR_AUDIT_NOT_PASSED`);
        every mandatory milestone must be `COMPLETED`
        (`ERR_MANDATORY_MILESTONES_OPEN`); and `open_escalation_count` must be 0
        (`ERR_OPEN_ESCALATIONS`)."

        Design: Corner/validations/request_close_with_mandatory_milestone_open_rejected
        """
        scen = make_active_listing_file(template_overrides={
            "milestone_defs": [{"name": "Earnest Money", "offset_days": 3, "mandatory": True}],
        })
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        accept_document(coord_h, scen["seller_h"], file_id, "T47_DISCLOSURE")
        audit = run_audit(coord_h, file_id)
        assert audit["result"] == "PASS"
        # The mandatory milestone stays PENDING.
        resp = api_client.request_close_file(file_id, coord_h)
        validate_error(resp, ApiErrorId.ERR_MANDATORY_MILESTONES_OPEN)
        fetched = validate_success(api_client.get_file(file_id, coord_h))
        assert fetched["status"] == "ACTIVE"

    def test_request_close_with_open_escalation_rejected(self):
        """PRD §3.7: "Requesting close moves `ACTIVE → PENDING_CLOSE` and enforces
        the compliance gates in fixed sub-order, so the first failing gate is the
        reported one: `last_audit_status` must be `PASS` (`ERR_AUDIT_NOT_PASSED`);
        every mandatory milestone must be `COMPLETED`
        (`ERR_MANDATORY_MILESTONES_OPEN`); and `open_escalation_count` must be 0
        (`ERR_OPEN_ESCALATIONS`)."

        Design: Corner/validations/request_close_with_open_escalation_rejected
        """
        scen = make_active_listing_file(
            state_code="CO",
            template_overrides={
                "milestone_defs": [{"name": "Listing Paperwork", "offset_days": 30, "mandatory": False}],
            },
            file_overrides={"inspection_offset_days": 14, "appraisal_offset_days": 21},
        )
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        get_success_data(api_client.create_communication(
            {
                "file_id": file_id,
                "party": "SELLER_AGENT",
                "direction": "OUTBOUND",
                "body": "Confirm sign install",
                "requires_response": True,
                "response_due_at": "2026-08-02T09:00:00Z",
            },
            coord_h,
        ))
        validate_success(api_client.set_clock({"to_iso8601": "2026-08-04T00:00:00Z"},
                                              TEST_USERS["admin_headers"]))
        audit = run_audit(coord_h, file_id)
        assert audit["result"] == "PASS"
        ms = get_milestone_by_name(coord_h, file_id, "Listing Paperwork")
        validate_success(api_client.waive_milestone(ms["id"], coord_h))
        f_mid = validate_success(api_client.get_file(file_id, coord_h))
        assert f_mid["open_escalation_count"] == 1
        resp = api_client.request_close_file(file_id, coord_h)
        validate_error(resp, ApiErrorId.ERR_OPEN_ESCALATIONS)
        fetched = validate_success(api_client.get_file(file_id, coord_h))
        assert fetched["status"] == "ACTIVE"


class TestCloseAndInvoiceStateLegality:
    def test_close_from_active_rejected(self):
        """PRD §3.8: "Closing moves `PENDING_CLOSE → CLOSED`. The file must be in
        `PENDING_CLOSE` (`ERR_FILE_NOT_PENDING_CLOSE`) and the verification's
        `overall_status` must be `CLEAR_TO_CLOSE` (`ERR_NOT_CLEAR_TO_CLOSE`)."

        Design: Corner/validations/close_from_active_rejected
        """
        scen = make_active_listing_file()
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        resp = api_client.close_file(file_id, coord_h)
        validate_error(resp, ApiErrorId.ERR_FILE_NOT_PENDING_CLOSE)
        fetched = validate_success(api_client.get_file(file_id, coord_h))
        assert fetched["status"] == "ACTIVE"

    def test_mark_paid_draft_invoice_rejected(self):
        """PRD §3.8: "A coordinator may also issue a `DRAFT` invoice manually while
        the owning file is `ACTIVE` or `CLOSED` (otherwise `ERR_INVOICE_INVALID_STATE`
        or `ERR_FILE_NOT_ACTIVE`), and may mark an `ISSUED` invoice `PAID` (any other
        starting state: `ERR_INVOICE_INVALID_STATE`)."

        Design: Corner/validations/mark_paid_draft_invoice_rejected
        """
        scen = make_active_listing_file()
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        invoice = get_file_invoice(coord_h, file_id)
        assert invoice["status"] == "DRAFT"
        resp = api_client.mark_invoice_paid(invoice["id"], coord_h)
        validate_error(resp, ApiErrorId.ERR_INVOICE_INVALID_STATE)
        after = validate_success(api_client.get_invoice(invoice["id"], coord_h))
        assert after["status"] == "DRAFT"


class TestClosingVerificationSecondForm:
    def test_close_gated_lender_first_confirmation_order(self):
        """PRD §3.8: "Closing moves `PENDING_CLOSE → CLOSED`. The file must be in
        `PENDING_CLOSE` (`ERR_FILE_NOT_PENDING_CLOSE`) and the verification's
        `overall_status` must be `CLEAR_TO_CLOSE` (`ERR_NOT_CLEAR_TO_CLOSE`)."
        PRD §3.8: "The derived `overall_status` is `CLEAR_TO_CLOSE` exactly when
        `title_status` is `CLEARED` and `lender_status` is either `CLEAR_TO_CLOSE` or
        `NOT_REQUIRED`, and `PENDING` otherwise; each confirmation recomputes it."

        Design: Difficulty/cross_entity_state_dependency/file_close_gated_by_closing_verification
        """
        scen = make_active_purchase_file(
            milestone_defs=[{"name": "Earnest Money", "offset_days": 3, "mandatory": True}],
            required_doc_types=["EXECUTED_CONTRACT"],
        )
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        cv = _drive_to_pending_close_purchase(
            scen,
            [("EXECUTED_CONTRACT", "buyer"), ("T47_DISCLOSURE", "seller")],
        )
        # Close is blocked while the verification is PENDING.
        resp = api_client.close_file(file_id, coord_h)
        validate_error(resp, ApiErrorId.ERR_NOT_CLEAR_TO_CLOSE)
        # Lender first: title still PENDING, so the join stays PENDING.
        validate_success(api_client.confirm_lender(cv["id"], TEST_USERS["lender_rep_headers"]))
        mid = validate_success(api_client.get_closing_verification(cv["id"], coord_h))
        assert mid["lender_status"] == "CLEAR_TO_CLOSE"
        assert mid["overall_status"] == "PENDING"
        resp2 = api_client.close_file(file_id, coord_h)
        validate_error(resp2, ApiErrorId.ERR_NOT_CLEAR_TO_CLOSE)
        # Title completes the join.
        validate_success(api_client.confirm_title(cv["id"], TEST_USERS["title_rep_headers"]))
        end = validate_success(api_client.get_closing_verification(cv["id"], coord_h))
        assert end["overall_status"] == "CLEAR_TO_CLOSE"
        closed = validate_success(api_client.close_file(file_id, coord_h))
        assert closed["status"] == "CLOSED"
