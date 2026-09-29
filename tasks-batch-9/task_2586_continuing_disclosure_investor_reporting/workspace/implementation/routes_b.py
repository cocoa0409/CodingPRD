"""Annual report cycles and their working content items."""
from flask import Blueprint, g

import calc
import domain
from core import (ALL_ROLES, DB, Obj, ROLE_COMPLIANCE_REVIEWER,
                  ROLE_DISCLOSURE_OFFICER, body, clock_stamp, cycles_of,
                  endpoint, fail, fk, items_of, listing, must_get, new_row,
                  parse_date_str, requirements_of, touch, vdate, venum, vstr)

bp = Blueprint("routes_b", __name__)

AUDIT_OPINION_TYPES = ("UNMODIFIED", "QUALIFIED", "UNAUDITED_INTERIM")
EDITABLE_CYCLE_STATUSES = ("DRAFTING", "READY_TO_FILE", "DELINQUENT")
LIVE_CYCLE_FILING_STATUSES = ("SUBMITTED", "CONFIRMED")


def _issue_of_undertaking(undertaking):
    return DB.bond_issues.get(undertaking["issue_id"]) if undertaking else None


# ---------------------------------------------------------------------- cycles
@bp.post("/disclosure/annual-report-cycles")
@endpoint([ROLE_DISCLOSURE_OFFICER])
def create_cycle():
    data = body()
    undertaking = fk("undertakings", data, "undertaking_id")
    if undertaking is None:
        fail("ERR_INVALID_REQUEST", "undertaking_id is required")
    fiscal_year_label = vstr(data, "fiscal_year_label", max_len=16)
    period_start = vdate(data, "period_start_date")
    period_end = vdate(data, "period_end_date")
    if not period_start < period_end:
        fail("ERR_INVALID_REQUEST",
             "period_start_date must fall strictly before period_end_date")
    issue = _issue_of_undertaking(undertaking)
    if issue is None or issue["status"] != "OUTSTANDING":
        fail("ERR_ISSUE_NOT_OUTSTANDING", "the owning issue is not OUTSTANDING")
    if undertaking["status"] != "ACTIVE":
        fail("ERR_UNDERTAKING_NOT_ACTIVE", "the undertaking is not ACTIVE")
    for existing in cycles_of(undertaking["id"]):
        if existing["status"] in ("WITHDRAWN", "CLOSED_NOT_REQUIRED"):
            continue
        other_start = parse_date_str(existing["period_start_date"])
        other_end = parse_date_str(existing["period_end_date"])
        if period_start < other_end and other_start < period_end:
            fail("ERR_REPORTING_PERIOD_OVERLAP",
                 "the reporting period overlaps an existing cycle")
    requirements = requirements_of(undertaking["id"])
    if not requirements:
        fail("ERR_NO_CONTENT_REQUIREMENTS",
             "the undertaking declares no content requirements")
    weight_total = sum(r["weight_bp"] for r in requirements)
    if weight_total != 10000:
        fail("ERR_CONTENT_WEIGHTS_UNBALANCED",
             "content requirement weights total %d basis points, not 10000"
             % weight_total)
    due_date = calc.annual_report_due_date(period_end, undertaking["filing_window_days"])
    row = new_row({
        "undertaking_id": undertaking["id"],
        "fiscal_year_label": fiscal_year_label,
        "period_start_date": period_start.isoformat(),
        "period_end_date": period_end.isoformat(),
        "due_date": due_date.isoformat(),
        "status": "DRAFTING",
        "completeness_score_pct": 0.00,
        "assembled_by_user_id": None,
        "assembled_at": None,
        "filed_filing_id": None,
        "timeliness_basis_applied": None,
        "filed_at": None,
        "days_late": 0,
        "withdrawal_reason": None,
    })
    DB.cycles[row["id"]] = row
    domain.create_content_items(row, undertaking)
    domain.recompute_completeness(row)
    domain.recompute_open_obligation_count(undertaking)
    return Obj(row, 201)


@bp.get("/disclosure/annual-report-cycles/<row_id>")
@endpoint(ALL_ROLES)
def get_cycle(row_id):
    return Obj(must_get("cycles", row_id))


@bp.get("/disclosure/annual-report-cycles")
@endpoint(ALL_ROLES)
def list_cycles():
    return listing(DB.cycles.values(),
                   {"undertaking_id": "undertaking_id",
                    "filed_filing_id": "filed_filing_id",
                    "status": "status",
                    "fiscal_year_label": "fiscal_year_label"})


@bp.post("/disclosure/annual-report-cycles/<row_id>/assemble")
@endpoint([ROLE_DISCLOSURE_OFFICER])
def assemble_cycle(row_id):
    cycle = must_get("cycles", row_id)
    undertaking = DB.undertakings.get(cycle["undertaking_id"])
    if cycle["status"] not in ("DRAFTING", "DELINQUENT"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "a cycle may only be assembled from DRAFTING or DELINQUENT")
    if undertaking is None or undertaking["status"] != "ACTIVE":
        fail("ERR_UNDERTAKING_NOT_ACTIVE", "the undertaking is not ACTIVE")
    live_items = [i for i in items_of(cycle["id"]) if i["status"] != "VOID"]
    for item in live_items:
        if item["attested_by_user_id"] is not None \
                and item["attested_by_user_id"] == g.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "the attesting user may not declare the report assembled")
    for item in live_items:
        if item["status"] not in ("READY", "WAIVED"):
            fail("ERR_CONTENT_NOT_READY",
                 "every non-VOID content item must be READY or WAIVED")
    if not any(i["status"] == "READY" for i in live_items):
        fail("ERR_NO_FILEABLE_CONTENT",
             "at least one non-VOID content item must be READY")
    was_delinquent = cycle["status"] == "DELINQUENT"
    touch(cycle)
    cycle["status"] = "READY_TO_FILE"
    cycle["assembled_by_user_id"] = g.user_id
    cycle["assembled_at"] = clock_stamp()
    domain.recompute_completeness(cycle)
    if was_delinquent:
        domain.recompute_counters(undertaking)
        domain.run_risk_pass(undertaking)
        domain.recompute_undertaking_invoices(undertaking)
    domain.recompute_open_obligation_count(undertaking)
    return Obj(cycle)


@bp.post("/disclosure/annual-report-cycles/<row_id>/withdraw")
@endpoint([ROLE_DISCLOSURE_OFFICER])
def withdraw_cycle(row_id):
    cycle = must_get("cycles", row_id)
    data = body()
    reason = vstr(data, "withdrawal_reason", max_len=500)
    if cycle["status"] not in ("DRAFTING", "READY_TO_FILE"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "a cycle may only be withdrawn from DRAFTING or READY_TO_FILE")
    for filing in DB.filings.values():
        if filing["cycle_id"] == cycle["id"] \
                and filing["status"] in LIVE_CYCLE_FILING_STATUSES:
            fail("ERR_CYCLE_HAS_LIVE_FILING",
                 "a filing on this cycle is already with the repository")
    touch(cycle)
    cycle["status"] = "WITHDRAWN"
    cycle["withdrawal_reason"] = reason
    for item in items_of(cycle["id"]):
        if item["status"] == "VOID":
            continue
        touch(item)
        item["status"] = "VOID"
        item["readiness_factor"] = calc.readiness_factor("VOID")
    domain.recompute_completeness(cycle)
    domain.recompute_open_obligation_count(DB.undertakings.get(cycle["undertaking_id"]))
    return Obj(cycle)


# --------------------------------------------------------------- content items
@bp.get("/disclosure/cycle-content-items/<row_id>")
@endpoint(ALL_ROLES)
def get_content_item(row_id):
    return Obj(must_get("content_items", row_id))


@bp.get("/disclosure/cycle-content-items")
@endpoint(ALL_ROLES)
def list_content_items():
    return listing(DB.content_items.values(),
                   {"cycle_id": "cycle_id",
                    "content_requirement_id": "content_requirement_id",
                    "status": "status"})


def _item_context(item):
    cycle = DB.cycles.get(item["cycle_id"])
    undertaking = DB.undertakings.get(cycle["undertaking_id"]) if cycle else None
    return cycle, undertaking


def _require_active_undertaking(undertaking):
    if undertaking is None or undertaking["status"] != "ACTIVE":
        fail("ERR_UNDERTAKING_NOT_ACTIVE", "the undertaking is not ACTIVE")


def _require_editable_cycle(cycle):
    if cycle is None or cycle["status"] not in EDITABLE_CYCLE_STATUSES:
        fail("ERR_CYCLE_NOT_EDITABLE", "the owning cycle is not editable")


@bp.patch("/disclosure/cycle-content-items/<row_id>")
@endpoint([ROLE_DISCLOSURE_OFFICER])
def patch_content_item(row_id):
    item = must_get("content_items", row_id)
    data = body()
    opinion = venum(data, "audit_opinion_type", AUDIT_OPINION_TYPES, required=False)
    as_of_date = vdate(data, "data_as_of_date", required=False)
    source_ref = vstr(data, "source_document_ref", required=False, max_len=200)
    if opinion is None and as_of_date is None and source_ref is None:
        fail("ERR_INVALID_REQUEST",
             "at least one of audit_opinion_type, data_as_of_date or "
             "source_document_ref must be supplied")
    cycle, undertaking = _item_context(item)
    if item["status"] not in ("NOT_STARTED", "DRAFT"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a NOT_STARTED or DRAFT content item accepts preparation progress")
    _require_active_undertaking(undertaking)
    _require_editable_cycle(cycle)
    touch(item)
    if opinion is not None:
        item["audit_opinion_type"] = opinion
    if as_of_date is not None:
        item["data_as_of_date"] = as_of_date.isoformat()
    if source_ref is not None:
        item["source_document_ref"] = source_ref
    item["status"] = "DRAFT"
    item["readiness_factor"] = calc.readiness_factor("DRAFT")
    domain.recompute_completeness(cycle)
    return Obj(item)


@bp.post("/disclosure/cycle-content-items/<row_id>/attest")
@endpoint([ROLE_DISCLOSURE_OFFICER])
def attest_content_item(row_id):
    item = must_get("content_items", row_id)
    cycle, undertaking = _item_context(item)
    if item["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION", "only a DRAFT content item may be attested")
    _require_active_undertaking(undertaking)
    if item["source_document_ref"] is None or item["data_as_of_date"] is None:
        fail("ERR_CONTENT_DATA_AS_OF_REQUIRED",
             "source_document_ref and data_as_of_date must both be recorded")
    requirement = DB.content_requirements.get(item["content_requirement_id"])
    if requirement is not None and requirement["requires_audit_opinion"] \
            and item["audit_opinion_type"] is None:
        fail("ERR_AUDIT_OPINION_REQUIRED",
             "this requirement demands an audit_opinion_type")
    _require_editable_cycle(cycle)
    touch(item)
    item["status"] = "READY"
    item["attested_by_user_id"] = g.user_id
    item["attested_at"] = clock_stamp()
    item["readiness_factor"] = calc.readiness_factor("READY")
    domain.recompute_completeness(cycle)
    return Obj(item)


@bp.post("/disclosure/cycle-content-items/<row_id>/reopen")
@endpoint([ROLE_DISCLOSURE_OFFICER])
def reopen_content_item(row_id):
    item = must_get("content_items", row_id)
    cycle, undertaking = _item_context(item)
    if item["status"] != "READY":
        fail("ERR_INVALID_STATE_TRANSITION", "only a READY content item may be reopened")
    _require_active_undertaking(undertaking)
    _require_editable_cycle(cycle)
    touch(item)
    item["status"] = "DRAFT"
    item["attested_by_user_id"] = None
    item["attested_at"] = None
    item["readiness_factor"] = calc.readiness_factor("DRAFT")
    if cycle["status"] == "READY_TO_FILE":
        touch(cycle)
        cycle["status"] = "DRAFTING"
        cycle["assembled_by_user_id"] = None
        cycle["assembled_at"] = None
    domain.recompute_completeness(cycle)
    return Obj(item)


@bp.post("/disclosure/cycle-content-items/<row_id>/waive")
@endpoint([ROLE_COMPLIANCE_REVIEWER])
def waive_content_item(row_id):
    item = must_get("content_items", row_id)
    data = body()
    reason = vstr(data, "waiver_reason", max_len=500)
    cycle, undertaking = _item_context(item)
    if item["status"] not in ("NOT_STARTED", "DRAFT"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a NOT_STARTED or DRAFT content item may be waived")
    _require_active_undertaking(undertaking)
    requirement = DB.content_requirements.get(item["content_requirement_id"])
    if requirement is None or not requirement["waivable"]:
        fail("ERR_REQUIREMENT_NOT_WAIVABLE", "the underlying requirement is not waivable")
    _require_editable_cycle(cycle)
    touch(item)
    item["status"] = "WAIVED"
    item["waiver_reason"] = reason
    item["readiness_factor"] = calc.readiness_factor("WAIVED")
    domain.recompute_completeness(cycle)
    return Obj(item)
