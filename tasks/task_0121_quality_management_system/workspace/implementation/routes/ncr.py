"""NonconformanceReport routes (PRD 3.2, 3.3)."""
from flask import Blueprint, request

from common import (require_enum, require_fields, require_non_negative_int,
                    require_string, stamp_create, touch)
from db import db
from errors import (ERR_DEVIATION_REQUIRED, ERR_DISPOSITION_NOT_ALLOWED,
                    ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_NCR_HAS_CAPA, ERR_SEGREGATION_OF_DUTIES, err)
from middleware import (ROLE_QUALITY_ENGINEER, ROLE_QUALITY_MANAGER,
                        authenticate, require_role)
from response import list_success, success
from services.calculations import cost_of_quality
from services.helpers import (get_or_404, paginate, paginate_args,
                              recompute_supplier_rating)
from services.serializers import ncr_out

bp = Blueprint("ncr", __name__)

NCR_SOURCES = {"SUPPLIER", "INTERNAL", "AUDIT"}
SEVERITIES = {"CRITICAL", "MAJOR", "MINOR"}
DISPOSITIONS = {"REWORK", "SCRAP", "USE_AS_IS", "RETURN_TO_SUPPLIER"}


@bp.route("/nonconformance-reports", methods=["POST"])
def create_ncr():
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_ENGINEER})
    body = request.get_json(silent=True) or {}

    # Body FK resolution (priority 4) before well-formedness (priority 5).
    source = body.get("source")
    supplier_id = body.get("supplier_id")
    audit_finding_id = body.get("audit_finding_id")
    inspection_lot_id = body.get("inspection_lot_id")

    if supplier_id is not None and supplier_id not in db.suppliers:
        raise err(ERR_FK_NOT_FOUND, "supplier_id does not resolve")
    if audit_finding_id is not None and audit_finding_id not in db.audit_findings:
        raise err(ERR_FK_NOT_FOUND, "audit_finding_id does not resolve")
    if inspection_lot_id is not None and inspection_lot_id not in db.inspection_lots:
        raise err(ERR_FK_NOT_FOUND, "inspection_lot_id does not resolve")

    # Well-formedness (priority 5).
    require_fields(body, ["title", "source", "severity", "defect_qty",
                          "unit_cost_cents", "part_number"])
    require_string(body["title"], "title")
    require_enum(source, NCR_SOURCES, "source")
    require_enum(body["severity"], SEVERITIES, "severity")
    require_non_negative_int(body["defect_qty"], "defect_qty", minimum=1)
    require_non_negative_int(body["unit_cost_cents"], "unit_cost_cents", minimum=0)
    require_string(body["part_number"], "part_number")

    rework_hours = body.get("rework_hours", 0)
    if rework_hours is None:
        rework_hours = 0
    if not isinstance(rework_hours, (int, float)) or isinstance(rework_hours, bool):
        raise err(ERR_INVALID_REQUEST, "rework_hours must be a number")

    # Source-conditional attribution requirements (PRD 3.2).
    if source == "SUPPLIER":
        if supplier_id is None:
            raise err(ERR_INVALID_REQUEST, "supplier_id required when source=SUPPLIER")
        if audit_finding_id is not None:
            raise err(ERR_INVALID_REQUEST, "audit_finding_id must be omitted when source=SUPPLIER")
    elif source == "AUDIT":
        if audit_finding_id is None:
            raise err(ERR_INVALID_REQUEST, "audit_finding_id required when source=AUDIT")

    rec = {
        "title": body["title"],
        "source": source,
        "supplier_id": supplier_id,
        "audit_finding_id": audit_finding_id,
        "inspection_lot_id": inspection_lot_id,
        "part_number": body["part_number"],
        "severity": body["severity"],
        "defect_qty": body["defect_qty"],
        "unit_cost_cents": body["unit_cost_cents"],
        "rework_hours": rework_hours,
        "status": "DRAFT",
        "disposition": None,
        "deviation_id": None,
        "cost_of_quality_cents": None,
        "budget_reserved_cents": 0,
        "created_by_personnel_id": auth.user_id,
    }
    stamp_create(rec)
    db.nonconformance_reports[rec["id"]] = rec
    return success(ncr_out(rec), status=201)


@bp.route("/nonconformance-reports/<rid>", methods=["GET"])
def get_ncr(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_QUALITY_ENGINEER})
    rec = get_or_404(db.nonconformance_reports, rid)
    return success(ncr_out(rec))


@bp.route("/nonconformance-reports", methods=["GET"])
def list_ncrs():
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_QUALITY_ENGINEER})
    limit, offset = paginate_args()
    supplier_id = request.args.get("supplier_id")
    audit_finding_id = request.args.get("audit_finding_id")
    inspection_lot_id = request.args.get("inspection_lot_id")

    matches = list(db.nonconformance_reports.values())
    if supplier_id is not None:
        matches = [n for n in matches if n["supplier_id"] == supplier_id]
    if audit_finding_id is not None:
        matches = [n for n in matches if n["audit_finding_id"] == audit_finding_id]
    if inspection_lot_id is not None:
        matches = [n for n in matches if n["inspection_lot_id"] == inspection_lot_id]

    page, total = paginate(matches, limit, offset)
    return list_success([ncr_out(n) for n in page], limit, offset, total)


@bp.route("/nonconformance-reports/<rid>/open", methods=["POST"])
def open_ncr(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_ENGINEER})
    rec = get_or_404(db.nonconformance_reports, rid)

    # State check (priority 6).
    if rec["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "NCR is not DRAFT")

    # Source-conditional preconditions (PRD 3.2). Supplier "ACTIVE": the
    # Supplier entity has no status field and no deactivation path, so a
    # resolvable supplier is always active.
    if rec["source"] == "SUPPLIER":
        supplier = db.suppliers.get(rec["supplier_id"])
        if supplier is None:
            raise err(ERR_INVALID_STATE, "Supplier does not resolve")
    elif rec["source"] == "AUDIT":
        finding = db.audit_findings.get(rec["audit_finding_id"])
        if finding is None or finding["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "Audit finding is not OPEN")

    # Reserve budget = defect_qty * unit_cost_cents (PRD 3.2).
    rec["budget_reserved_cents"] = rec["defect_qty"] * rec["unit_cost_cents"]
    rec["status"] = "OPEN"
    touch(rec)

    if rec["source"] == "SUPPLIER":
        supplier = db.suppliers[rec["supplier_id"]]
        supplier["ncrs_attributed"] += 1
        recompute_supplier_rating(supplier)
    elif rec["source"] == "AUDIT":
        finding = db.audit_findings[rec["audit_finding_id"]]
        finding["status"] = "NCR_RAISED"
        finding["raised_ncr_id"] = rec["id"]
        touch(finding)
        # open_finding_count unchanged: NCR_RAISED still counts as open.

    return success(ncr_out(rec))


@bp.route("/nonconformance-reports/<rid>/disposition", methods=["POST"])
def disposition_ncr(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER})
    rec = get_or_404(db.nonconformance_reports, rid)
    body = request.get_json(silent=True) or {}

    # Well-formedness (priority 5).
    require_fields(body, ["disposition"])
    disposition = body["disposition"]
    require_enum(disposition, DISPOSITIONS, "disposition")

    # State check (priority 6) BEFORE SoD (PRD 2.10, 3.3).
    if rec["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "NCR is not OPEN")

    # Segregation of duties (priority 8).
    if auth.user_id == rec["created_by_personnel_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Disposing manager may not be the NCR creator")

    chosen_deviation_id = None

    # USE_AS_IS deviation requirement (priority 9) BEFORE RETURN_TO_SUPPLIER check.
    if disposition == "USE_AS_IS":
        clock = db.get_clock()
        match = None
        for dev in db.deviations.values():
            if (dev["ncr_id"] == rec["id"] and dev["status"] == "APPROVED"
                    and dev["max_qty"] >= rec["defect_qty"]
                    and dev["valid_from_dt"] <= clock < dev["valid_to_dt"]):
                match = dev
                break
        if match is None:
            raise err(ERR_DEVIATION_REQUIRED,
                      "USE_AS_IS requires an approved, in-window deviation")
        chosen_deviation_id = match["id"]
    elif disposition == "RETURN_TO_SUPPLIER":
        # Source check (priority 10).
        if rec["source"] != "SUPPLIER":
            raise err(ERR_DISPOSITION_NOT_ALLOWED,
                      "RETURN_TO_SUPPLIER requires source=SUPPLIER")

    # Compute cost of quality and re-reserve budget (PRD 3.3).
    coq = cost_of_quality(disposition, rec["severity"], rec["defect_qty"],
                          rec["unit_cost_cents"], rec["rework_hours"])
    rec["disposition"] = disposition
    rec["cost_of_quality_cents"] = coq
    rec["budget_reserved_cents"] = coq
    if chosen_deviation_id is not None:
        rec["deviation_id"] = chosen_deviation_id
    rec["status"] = "DISPOSITIONED"
    touch(rec)
    return success(ncr_out(rec))


@bp.route("/nonconformance-reports/<rid>/void", methods=["POST"])
def void_ncr(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_ENGINEER, ROLE_QUALITY_MANAGER})
    rec = get_or_404(db.nonconformance_reports, rid)

    if rec["status"] == "DRAFT":
        # DRAFT -> VOID (QualityEngineer per scaffold actor; both roles allowed
        # to call the endpoint per PRD endpoint table).
        rec["budget_reserved_cents"] = 0
        rec["status"] = "VOID"
        touch(rec)
        return success(ncr_out(rec))

    if rec["status"] == "OPEN":
        # OPEN -> VOID only if no CAPA exists for this NCR (PRD 3.2).
        has_capa = any(c["ncr_id"] == rec["id"] for c in db.capas.values())
        if has_capa:
            raise err(ERR_NCR_HAS_CAPA, "Cannot void an OPEN NCR that has a CAPA")
        rec["budget_reserved_cents"] = 0
        rec["status"] = "VOID"
        touch(rec)
        # Reverse the attribution side effects of opening (PRD 3.2).
        if rec["source"] == "SUPPLIER":
            supplier = db.suppliers.get(rec["supplier_id"])
            if supplier is not None:
                supplier["ncrs_attributed"] -= 1
                recompute_supplier_rating(supplier)
        elif rec["source"] == "AUDIT":
            finding = db.audit_findings.get(rec["audit_finding_id"])
            if finding is not None and finding["status"] == "NCR_RAISED":
                finding["status"] = "OPEN"
                finding["raised_ncr_id"] = None
                touch(finding)
        return success(ncr_out(rec))

    raise err(ERR_INVALID_STATE, "NCR cannot be voided from its current state")
