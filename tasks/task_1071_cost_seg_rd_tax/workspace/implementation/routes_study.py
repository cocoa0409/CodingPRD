"""Routes: study CRUD and lifecycle transitions."""
from flask import request
from core import (db, ApiError, ok, ok_list, require_role, get_body,
                  require_fields, paginate, sort_key, base_fields, touch,
                  user_id)
from serializers import ser_study, ser_report, ser_fee
from calc import (compute_benefit_fields, study_fee, MAX_FEE_BPS,
                  allocated_components, qualified_lines)
from routes_core import get_or_404, is_int

STUDY_TYPES = {"COST_SEGREGATION", "RD_CREDIT"}
FEE_TYPES = {"FIXED", "PERCENT"}
CREDIT_METHODS = {"REGULAR", "ASC"}
CANCELLABLE = {"DRAFT", "SCOPING", "ENGINEERING", "IN_REVIEW"}


def report_for_study(study_id):
    reps = [r for r in db.reports.values() if r["study_id"] == study_id]
    reps.sort(key=sort_key)
    return reps[0] if reps else None


def base_period_years(tax_year):
    return {tax_year - 3, tax_year - 2, tax_year - 1}


def register(app):
    @app.route("/studies", methods=["POST"])
    def create_study():
        require_role("StudyManager")
        body = get_body()
        require_fields(body, "client_id", "study_type", "tax_year")
        client = get_or_404(db.clients, body["client_id"])
        if body["study_type"] not in STUDY_TYPES:
            raise ApiError("ERR_VALIDATION", 400, "Invalid study_type")
        if not is_int(body["tax_year"]):
            raise ApiError("ERR_VALIDATION", 400, "tax_year must be an integer")
        if client["status"] != "ACTIVE":
            raise ApiError("ERR_CLIENT_NOT_ACTIVE", 409, "Client not ACTIVE")
        s = base_fields()
        s.update({
            "client_id": body["client_id"],
            "property_id": None,
            "assigned_engineer_id": None,
            "study_type": body["study_type"],
            "tax_year": body["tax_year"],
            "is_look_back": bool(body.get("is_look_back", False)),
            "fee_type": None,
            "fee_fixed_amount_cents": None,
            "fee_percent_bps": None,
            "credit_method": None,
            "fixed_base_pct": None,
            "avg_annual_gross_receipts_cents": None,
            "prior_qre_year1_cents": 0,
            "prior_qre_year2_cents": 0,
            "prior_qre_year3_cents": 0,
            "status": "DRAFT",
            "reviewer_engineer_id": None,
            "total_allocated_cost_cents": 0,
            "section_481a_cents": 0,
        })
        db.studies[s["id"]] = s
        return ok(ser_study(s), 201)

    @app.route("/studies/<sid>", methods=["GET"])
    def get_study(sid):
        require_role("StudyManager", "Engineer", "Reviewer", "CPA")
        s = get_or_404(db.studies, sid)
        return ok(ser_study(s))

    @app.route("/studies", methods=["GET"])
    def list_studies():
        require_role("StudyManager", "Engineer", "Reviewer", "CPA")
        limit, offset = paginate(request.args)
        items = list(db.studies.values())
        for f in ("client_id", "property_id", "assigned_engineer_id"):
            val = request.args.get(f)
            if val is not None:
                items = [s for s in items if s.get(f) == val]
        items.sort(key=sort_key)
        total = len(items)
        page = items[offset:offset + limit]
        return ok_list([ser_study(s) for s in page], limit, offset, total)

    @app.route("/studies/<sid>/scope", methods=["POST"])
    def scope_study(sid):
        require_role("StudyManager")
        s = get_or_404(db.studies, sid)
        body = get_body()
        require_fields(body, "fee_type")
        fee_type = body["fee_type"]
        if fee_type not in FEE_TYPES:
            raise ApiError("ERR_VALIDATION", 400, "Invalid fee_type")

        # FK existence (priority 3)
        prop = None
        if s["study_type"] == "COST_SEGREGATION":
            if body.get("property_id") is None:
                raise ApiError("ERR_VALIDATION", 400, "property_id required for COST_SEGREGATION")
            prop = get_or_404(db.properties, body["property_id"])
            if prop["client_id"] != s["client_id"]:
                raise ApiError("ERR_NOT_FOUND", 404, "Property not owned by study client")
        else:  # RD_CREDIT
            if body.get("credit_method") is None:
                raise ApiError("ERR_VALIDATION", 400, "credit_method required for RD_CREDIT")
            if body["credit_method"] not in CREDIT_METHODS:
                raise ApiError("ERR_VALIDATION", 400, "Invalid credit_method")

        # state (priority 4)
        if s["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409, "Study not in DRAFT")

        # overlap / temporal (priority 8/9)
        if s["study_type"] == "COST_SEGREGATION":
            for other in db.studies.values():
                if (other["id"] != s["id"] and other["study_type"] == "COST_SEGREGATION"
                        and other["status"] != "CANCELLED"
                        and other.get("property_id") == body["property_id"]
                        and other["tax_year"] == s["tax_year"]):
                    raise ApiError("ERR_PROPERTY_STUDY_OVERLAP", 409,
                                   "Overlapping cost-seg study on property")
        else:
            mine = base_period_years(s["tax_year"])
            for other in db.studies.values():
                if (other["id"] != s["id"] and other["study_type"] == "RD_CREDIT"
                        and other["status"] != "CANCELLED"
                        and other["client_id"] == s["client_id"]):
                    if mine & base_period_years(other["tax_year"]):
                        raise ApiError("ERR_RD_BASE_PERIOD_OVERLAP", 409,
                                       "Overlapping R&D base period")

        # fee terms / fiscal (priority 11)
        if fee_type == "FIXED":
            if body.get("fee_fixed_amount_cents") is None:
                raise ApiError("ERR_MISSING_FEE_TERMS", 422, "fee_fixed_amount_cents required")
        else:  # PERCENT
            if body.get("fee_percent_bps") is None:
                raise ApiError("ERR_MISSING_FEE_TERMS", 422, "fee_percent_bps required")
            if body["fee_percent_bps"] > MAX_FEE_BPS:
                raise ApiError("ERR_FEE_PERCENT_TOO_HIGH", 422, "fee_percent_bps exceeds cap")

        # record
        s["fee_type"] = fee_type
        if fee_type == "FIXED":
            s["fee_fixed_amount_cents"] = body["fee_fixed_amount_cents"]
        else:
            s["fee_percent_bps"] = body["fee_percent_bps"]
        if s["study_type"] == "COST_SEGREGATION":
            s["property_id"] = body["property_id"]
        else:
            s["credit_method"] = body["credit_method"]
            s["fixed_base_pct"] = body.get("fixed_base_pct")
            s["avg_annual_gross_receipts_cents"] = body.get("avg_annual_gross_receipts_cents")
            s["prior_qre_year1_cents"] = body.get("prior_qre_year1_cents", 0)
            s["prior_qre_year2_cents"] = body.get("prior_qre_year2_cents", 0)
            s["prior_qre_year3_cents"] = body.get("prior_qre_year3_cents", 0)
        s["status"] = "SCOPING"
        touch(s)
        return ok(ser_study(s))

    @app.route("/studies/<sid>/assign-engineer", methods=["POST"])
    def assign_engineer(sid):
        require_role("StudyManager")
        s = get_or_404(db.studies, sid)
        body = get_body()
        require_fields(body, "assigned_engineer_id")
        get_or_404(db.engineers, body["assigned_engineer_id"])
        if s["status"] != "SCOPING":
            raise ApiError("ERR_INVALID_STATE", 409, "Study not in SCOPING")
        s["assigned_engineer_id"] = body["assigned_engineer_id"]
        s["status"] = "ENGINEERING"
        touch(s)
        return ok(ser_study(s))

    @app.route("/studies/<sid>/submit-review", methods=["POST"])
    def submit_review(sid):
        require_role("Engineer")
        s = get_or_404(db.studies, sid)
        if s["status"] != "ENGINEERING":
            raise ApiError("ERR_INVALID_STATE", 409, "Study not in ENGINEERING")
        if s["study_type"] == "COST_SEGREGATION":
            if not allocated_components(s["id"]):
                raise ApiError("ERR_NO_ALLOCATED_COMPONENTS", 409, "No ALLOCATED components")
        else:
            if not qualified_lines(s["id"]):
                raise ApiError("ERR_NO_QUALIFIED_QRE", 409, "No QUALIFIED QRE lines")
        s["status"] = "IN_REVIEW"
        touch(s)
        # Report handling
        rep = report_for_study(s["id"])
        if rep is None:
            rep = base_fields()
            rep.update({
                "study_id": s["id"],
                "report_type": ("COST_SEG_REPORT" if s["study_type"] == "COST_SEGREGATION"
                                else "RD_CREDIT_REPORT"),
                "revision_count": 0,
                "issued_at": None,
                "status": "DRAFT",
            })
            db.reports[rep["id"]] = rep
        elif rep["status"] == "REVISION_REQUESTED":
            rep["status"] = "DRAFT"
            rep["revision_count"] += 1
            touch(rep)
        return ok(ser_study(s))

    @app.route("/studies/<sid>/reject", methods=["POST"])
    def reject_study(sid):
        require_role("Reviewer")
        s = get_or_404(db.studies, sid)
        if s["status"] != "IN_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409, "Study not IN_REVIEW")
        if user_id() == s.get("assigned_engineer_id"):
            raise ApiError("ERR_SOD_VIOLATION", 403, "Reviewer cannot review own preparation")
        s["status"] = "ENGINEERING"
        touch(s)
        rep = report_for_study(s["id"])
        if rep is not None and rep["status"] == "DRAFT":
            rep["status"] = "REVISION_REQUESTED"
            touch(rep)
        return ok(ser_study(s))

    @app.route("/studies/<sid>/finalize", methods=["POST"])
    def finalize_study(sid):
        require_role("Reviewer")
        s = get_or_404(db.studies, sid)
        if s["status"] != "IN_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409, "Study not IN_REVIEW")
        if user_id() == s.get("assigned_engineer_id"):
            raise ApiError("ERR_SOD_VIOLATION", 403, "Reviewer cannot review own preparation")
        s["status"] = "FINALIZED"
        s["reviewer_engineer_id"] = user_id()
        touch(s)
        # cascade link1: report DRAFT->ISSUED
        rep = report_for_study(s["id"])
        if rep is not None and rep["status"] == "DRAFT":
            rep["status"] = "ISSUED"
            rep["issued_at"] = db.clock
            touch(rep)
        # cascade link2: create FeeInvoice
        amount = study_fee(s)
        inv = base_fields()
        inv.update({
            "study_id": s["id"],
            "amount_cents": amount,
            "fee_basis": s["fee_type"],
            "status": "ISSUED",
        })
        db.fee_invoices[inv["id"]] = inv
        # cascade link3: client ledger
        client = db.clients.get(s["client_id"])
        if client is not None:
            client["outstanding_fee_cents"] += amount
            touch(client)
        return ok(ser_study(s))

    @app.route("/studies/<sid>/deliver", methods=["POST"])
    def deliver_study(sid):
        require_role("CPA")
        s = get_or_404(db.studies, sid)
        if s["status"] != "FINALIZED":
            raise ApiError("ERR_INVALID_STATE", 409, "Study not FINALIZED")
        s["status"] = "DELIVERED"
        touch(s)
        return ok(ser_study(s))

    @app.route("/studies/<sid>/cancel", methods=["POST"])
    def cancel_study(sid):
        require_role("StudyManager")
        s = get_or_404(db.studies, sid)
        if s["status"] not in CANCELLABLE:
            raise ApiError("ERR_INVALID_STATE", 409, "Study not cancellable")
        s["status"] = "CANCELLED"
        touch(s)
        return ok(ser_study(s))

    @app.route("/studies/<sid>/reports", methods=["GET"])
    def list_reports(sid):
        require_role("StudyManager", "Engineer", "Reviewer", "CPA")
        get_or_404(db.studies, sid)
        limit, offset = paginate(request.args)
        items = [r for r in db.reports.values() if r["study_id"] == sid]
        items.sort(key=sort_key)
        total = len(items)
        page = items[offset:offset + limit]
        return ok_list([ser_report(r) for r in page], limit, offset, total)
