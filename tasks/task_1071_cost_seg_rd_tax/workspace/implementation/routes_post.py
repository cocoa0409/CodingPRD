"""Routes: audit-support cases, amended returns, fee invoices."""
from flask import request
from core import (db, ApiError, ok, ok_list, require_role, get_body,
                  require_fields, paginate, sort_key, base_fields, touch)
from serializers import ser_audit, ser_amended, ser_fee
from calc import section_481a, AMEND_STATUTE_YEARS
from routes_core import get_or_404, is_int
from routes_study import report_for_study


def register(app):
    # ---------------- AuditSupportCase ----------------
    @app.route("/studies/<sid>/audit-cases", methods=["POST"])
    def open_audit_case(sid):
        require_role("StudyManager")
        s = get_or_404(db.studies, sid)
        if s["status"] != "DELIVERED":
            raise ApiError("ERR_INVALID_STATE", 409, "Study not DELIVERED")
        body = get_body()
        require_fields(body, "irs_notice_ref")
        a = base_fields()
        a.update({
            "study_id": s["id"],
            "irs_notice_ref": body["irs_notice_ref"],
            "resolution_note": None,
            "status": "OPEN",
        })
        db.audit_cases[a["id"]] = a
        return ok(ser_audit(a), 201)

    @app.route("/studies/<sid>/audit-cases", methods=["GET"])
    def list_audit_cases(sid):
        require_role("StudyManager", "Engineer", "Reviewer", "CPA")
        get_or_404(db.studies, sid)
        limit, offset = paginate(request.args)
        items = [a for a in db.audit_cases.values() if a["study_id"] == sid]
        items.sort(key=sort_key)
        total = len(items)
        page = items[offset:offset + limit]
        return ok_list([ser_audit(a) for a in page], limit, offset, total)

    @app.route("/audit-cases/<aid>/resolve", methods=["POST"])
    def resolve_audit_case(aid):
        require_role("StudyManager")
        a = get_or_404(db.audit_cases, aid)
        if a["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409, "Case not OPEN")
        body = get_body()
        require_fields(body, "resolution_note")
        a["resolution_note"] = body["resolution_note"]
        a["status"] = "RESOLVED"
        touch(a)
        return ok(ser_audit(a))

    # ---------------- AmendedReturn ----------------
    @app.route("/studies/<sid>/amended-returns", methods=["POST"])
    def create_amended_return(sid):
        require_role("StudyManager")
        s = get_or_404(db.studies, sid)
        body = get_body()
        require_fields(body, "amended_tax_year", "expected_study_version")
        if not is_int(body["amended_tax_year"]):
            raise ApiError("ERR_VALIDATION", 400, "amended_tax_year must be an integer")
        # state precondition
        if not (s["is_look_back"] and s["status"] == "DELIVERED"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Study must be look-back and DELIVERED")
        # OCC
        if body["expected_study_version"] != s["version"]:
            raise ApiError("ERR_STALE_STUDY_VERSION", 412, "Stale study version")
        a = base_fields()
        a.update({
            "study_id": s["id"],
            "amended_tax_year": body["amended_tax_year"],
            "section_481a_cents": 0,
            "filed_at": None,
            "status": "DRAFT",
        })
        db.amended_returns[a["id"]] = a
        # successful create advances study version by 1
        touch(s)
        return ok(ser_amended(a), 201)

    @app.route("/studies/<sid>/amended-returns", methods=["GET"])
    def list_amended_returns(sid):
        require_role("StudyManager", "Engineer", "Reviewer", "CPA")
        get_or_404(db.studies, sid)
        limit, offset = paginate(request.args)
        items = [a for a in db.amended_returns.values() if a["study_id"] == sid]
        items.sort(key=sort_key)
        total = len(items)
        page = items[offset:offset + limit]
        return ok_list([ser_amended(a) for a in page], limit, offset, total)

    @app.route("/amended-returns/<aid>/file", methods=["POST"])
    def file_amended_return(aid):
        require_role("StudyManager")
        a = get_or_404(db.amended_returns, aid)
        if a["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409, "Amended return not DRAFT")
        # amendment window: clock year <= amended_tax_year + AMEND_STATUTE_YEARS
        if db.clock.year > a["amended_tax_year"] + AMEND_STATUTE_YEARS:
            raise ApiError("ERR_AMEND_WINDOW_EXPIRED", 409, "Amendment window expired")
        s = db.studies.get(a["study_id"])
        adj = section_481a(s) if s is not None else 0
        a["section_481a_cents"] = adj
        a["filed_at"] = db.clock
        a["status"] = "FILED"
        touch(a)
        # cascade link1: parent study
        if s is not None:
            s["section_481a_cents"] = adj
            touch(s)
            # cascade link2: report ISSUED->SUPERSEDED
            rep = report_for_study(s["id"])
            if rep is not None and rep["status"] == "ISSUED":
                rep["status"] = "SUPERSEDED"
                touch(rep)
        return ok(ser_amended(a))

    # ---------------- FeeInvoice ----------------
    @app.route("/studies/<sid>/fee-invoices", methods=["GET"])
    def list_fee_invoices(sid):
        require_role("StudyManager", "Engineer", "Reviewer", "CPA")
        get_or_404(db.studies, sid)
        limit, offset = paginate(request.args)
        items = [f for f in db.fee_invoices.values() if f["study_id"] == sid]
        items.sort(key=sort_key)
        total = len(items)
        page = items[offset:offset + limit]
        return ok_list([ser_fee(f) for f in page], limit, offset, total)

    @app.route("/fee-invoices/<fid>/pay", methods=["POST"])
    def pay_fee_invoice(fid):
        require_role("StudyManager")
        f = get_or_404(db.fee_invoices, fid)
        if f["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", 409, "Invoice not ISSUED")
        f["status"] = "PAID"
        touch(f)
        _decrement_ledger(f)
        return ok(ser_fee(f))

    @app.route("/fee-invoices/<fid>/void", methods=["POST"])
    def void_fee_invoice(fid):
        require_role("StudyManager")
        f = get_or_404(db.fee_invoices, fid)
        if f["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", 409, "Invoice not ISSUED")
        f["status"] = "VOID"
        touch(f)
        _decrement_ledger(f)
        return ok(ser_fee(f))


def _decrement_ledger(f):
    s = db.studies.get(f["study_id"])
    if s is None:
        return
    client = db.clients.get(s["client_id"])
    if client is not None:
        client["outstanding_fee_cents"] -= f["amount_cents"]
        touch(client)
