"""QuantityEntry, TmTicket, DistributionRecord routes."""
import json
from decimal import Decimal
from flask import Blueprint, request

from auth import ctx, need
from calc import (
    bump_report,
    touch,
    price_ticket,
    report_has_stoppage,
    normalize_labor_line,
    normalize_equipment_line,
    normalize_material_line,
    distribution_hold,
)
from clock import clock
from db import store
from envelope import success, success_empty
from errors import ApiError, bad
from route_helpers import stamp, list_response
from serializers import ser_quantity_entry, ser_ticket, ser_distribution
from routes.daily_reports import get_report, require_editable
from routes.setup_resources import get_work_area, get_work_item
from util import q3
from validate import (
    body,
    req_str,
    opt_str,
    req_int,
    opt_int,
    req_num,
    req_enum,
    req_list,
    opt_list,
)

bp = Blueprint("commercial", __name__)

ENTRY_STATUSES = ("ACTIVE", "VOIDED")
TICKET_STATUSES = (
    "DRAFT",
    "PENDING_SIGNATURES",
    "PARTIALLY_SIGNED",
    "FULLY_SIGNED",
    "APPROVED",
    "REJECTED",
    "VOID",
)
RECIPIENT_ROLES = ("OWNER", "ARCHITECT", "INSPECTOR", "SUBCONTRACTOR", "INTERNAL")
DISTRIBUTION_STATUSES = ("PENDING", "BLOCKED", "SENT", "ACKNOWLEDGED")


def get_quantity(qid):
    q = store.quantity_entries.get(qid)
    if q is None:
        raise ApiError("ERR_NOT_FOUND", 404, "QuantityEntry not found")
    return q


def get_ticket(tid):
    t = store.tm_tickets.get(tid)
    if t is None:
        raise ApiError("ERR_TICKET_NOT_FOUND", 404, "TmTicket not found")
    return t


def get_distribution(did):
    d = store.distribution_records.get(did)
    if d is None:
        raise ApiError(
            "ERR_DISTRIBUTION_RECORD_NOT_FOUND", 404, "DistributionRecord not found"
        )
    return d


def _fingerprint(b):
    return json.dumps(b, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# quantity entries
# ---------------------------------------------------------------------------

@bp.post("/quantity-entries")
def create_quantity_entry():
    _, role = ctx()
    need(role, ["Superintendent"])
    b = body()
    report_id = req_str(b, "report_id")
    work_item_id = req_str(b, "work_item_id")
    work_area_id = req_str(b, "work_area_id")
    quantity_installed = req_num(b, "quantity_installed", gt=Decimal(0))
    expected_version = req_int(b, "expected_report_version")
    # priority 5: body FK existence
    report = get_report(report_id)
    get_work_item(work_item_id)
    area = get_work_area(work_area_id)
    # priority 6.1: posture gate
    require_editable(report)
    # priority 6.5: OCC on report version
    if expected_version != report["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Report version is stale")
    # priority 10: work area open
    if area["status"] != "OPEN":
        raise ApiError("ERR_WORK_AREA_CLOSED", 409, "WorkArea is CLOSED")
    rounded = q3(quantity_installed)
    # supersede prior ACTIVE entry for the same (report, work_item, work_area)
    prior = None
    for q in store.quantity_entries.values():
        if (
            q["report_id"] == report_id
            and q["work_item_id"] == work_item_id
            and q["work_area_id"] == work_area_id
            and q["status"] == "ACTIVE"
        ):
            prior = q
            break
    rec = stamp(
        {
            "report_id": report_id,
            "work_item_id": work_item_id,
            "work_area_id": work_area_id,
            "quantity_installed": quantity_installed,
            "rounded_quantity": rounded,
            "supersedes_id": None,
            "status": "ACTIVE",
        }
    )
    store.quantity_entries[rec["id"]] = rec
    if prior is not None:
        prior["status"] = "VOIDED"
        prior["supersedes_id"] = rec["id"]
        touch(prior)
    bump_report(report)
    return success(ser_quantity_entry(rec), 201)


@bp.get("/quantity-entries/<qid>")
def get_one_quantity(qid):
    ctx()
    return success(ser_quantity_entry(get_quantity(qid)), 200)


@bp.get("/quantity-entries")
def list_quantities():
    ctx()
    report_id = request.args.get("report_id")
    work_item_id = request.args.get("work_item_id")
    work_area_id = request.args.get("work_area_id")
    status = request.args.get("status")
    supersedes_id = request.args.get("supersedes_id")
    if status is not None and status not in ENTRY_STATUSES:
        bad("Invalid status filter")
    rows = list(store.quantity_entries.values())
    if report_id is not None:
        rows = [r for r in rows if r["report_id"] == report_id]
    if work_item_id is not None:
        rows = [r for r in rows if r["work_item_id"] == work_item_id]
    if work_area_id is not None:
        rows = [r for r in rows if r["work_area_id"] == work_area_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if supersedes_id is not None:
        rows = [r for r in rows if r["supersedes_id"] == supersedes_id]
    return list_response(rows, ser_quantity_entry)


@bp.post("/quantity-entries/<qid>/void")
def void_quantity(qid):
    _, role = ctx()
    need(role, ["Superintendent"])
    q = get_quantity(qid)
    if q["status"] != "ACTIVE":
        raise ApiError("ERR_ENTRY_INVALID_TRANSITION", 409, "Entry is not ACTIVE")
    report = get_report(q["report_id"])
    require_editable(report)
    q["status"] = "VOIDED"
    touch(q)
    bump_report(report)
    return success(ser_quantity_entry(q), 200)


# ---------------------------------------------------------------------------
# T&M tickets
# ---------------------------------------------------------------------------

def _price(t):
    pricing = price_ticket(
        t["labor_lines"],
        t["equipment_lines"],
        t["material_lines"],
        report_has_stoppage(t["report_id"]),
    )
    t.update(pricing)


@bp.post("/tm-tickets")
def create_ticket():
    uid, role = ctx()
    need(role, ["Superintendent"])
    b = body()
    report_id = req_str(b, "report_id")
    work_item_id = req_str(b, "work_item_id")
    description = req_str(b, "description")
    labor_lines = [normalize_labor_line(x) for x in req_list(b, "labor_lines")]
    equipment_lines = [normalize_equipment_line(x) for x in opt_list(b, "equipment_lines")]
    material_lines = [normalize_material_line(x) for x in opt_list(b, "material_lines")]
    ceiling = opt_int(b, "authorized_ceiling_cents", None, mn=1)
    idempotency_key = opt_str(b, "idempotency_key")
    # priority 5: body FK existence
    report = get_report(report_id)
    get_work_item(work_item_id)
    # priority 6.1: posture gate
    require_editable(report)
    # priority 8.5: idempotency
    if idempotency_key is not None:
        prior = store.idempotency.get(("/tm-tickets", uid, idempotency_key))
        if prior is not None:
            if prior["fingerprint"] != _fingerprint(b):
                raise ApiError(
                    "ERR_IDEMPOTENCY_CONFLICT",
                    409,
                    "idempotency_key reused with a different request body",
                )
            return success(ser_ticket(store.tm_tickets[prior["entity_id"]]), 201)
    rec = stamp(
        {
            "report_id": report_id,
            "work_item_id": work_item_id,
            "description": description,
            "authorized_ceiling_cents": ceiling,
            "labor_lines": labor_lines,
            "equipment_lines": equipment_lines,
            "material_lines": material_lines,
            "status": "DRAFT",
            "created_by_user_id": uid,
            "contractor_signed_by": None,
            "owner_signed_by": None,
            "revision_count": 0,
            "reject_reason": None,
        }
    )
    _price(rec)
    store.tm_tickets[rec["id"]] = rec
    bump_report(report)
    if idempotency_key is not None:
        store.idempotency[("/tm-tickets", uid, idempotency_key)] = {
            "fingerprint": _fingerprint(b),
            "entity_id": rec["id"],
        }
    return success(ser_ticket(rec), 201)


@bp.get("/tm-tickets/<tid>")
def get_one_ticket(tid):
    ctx()
    return success(ser_ticket(get_ticket(tid)), 200)


@bp.get("/tm-tickets")
def list_tickets():
    ctx()
    report_id = request.args.get("report_id")
    work_item_id = request.args.get("work_item_id")
    status = request.args.get("status")
    if status is not None and status not in TICKET_STATUSES:
        bad("Invalid status filter")
    rows = list(store.tm_tickets.values())
    if report_id is not None:
        rows = [r for r in rows if r["report_id"] == report_id]
    if work_item_id is not None:
        rows = [r for r in rows if r["work_item_id"] == work_item_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, ser_ticket)


@bp.put("/tm-tickets/<tid>")
def edit_ticket(tid):
    _, role = ctx()
    need(role, ["Superintendent"])
    t = get_ticket(tid)
    b = body()
    expected = req_int(b, "expected_ticket_version")
    new_description = None
    if "description" in b:
        new_description = req_str(b, "description")
    new_labor = None
    if "labor_lines" in b and b["labor_lines"] is not None:
        new_labor = [normalize_labor_line(x) for x in req_list(b, "labor_lines")]
    new_equipment = None
    if "equipment_lines" in b and b["equipment_lines"] is not None:
        new_equipment = [normalize_equipment_line(x) for x in opt_list(b, "equipment_lines")]
    new_material = None
    if "material_lines" in b and b["material_lines"] is not None:
        new_material = [normalize_material_line(x) for x in opt_list(b, "material_lines")]
    new_ceiling = None
    ceiling_cleared = False
    if "authorized_ceiling_cents" in b:
        if b["authorized_ceiling_cents"] is None:
            ceiling_cleared = True
        else:
            new_ceiling = opt_int(b, "authorized_ceiling_cents", None, mn=1)
    # priority 6: ticket must be DRAFT
    if t["status"] != "DRAFT":
        raise ApiError(
            "ERR_TICKET_INVALID_TRANSITION", 409, "Ticket must be DRAFT to edit"
        )
    # priority 6.1: posture gate
    report = get_report(t["report_id"])
    require_editable(report)
    # priority 6.5: OCC on ticket version
    if expected != t["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Ticket version is stale")
    if new_description is not None:
        t["description"] = new_description
    if new_labor is not None:
        t["labor_lines"] = new_labor
    if new_equipment is not None:
        t["equipment_lines"] = new_equipment
    if new_material is not None:
        t["material_lines"] = new_material
    if ceiling_cleared:
        t["authorized_ceiling_cents"] = None
    elif new_ceiling is not None:
        t["authorized_ceiling_cents"] = new_ceiling
    _price(t)
    touch(t)
    return success(ser_ticket(t), 200)


@bp.post("/tm-tickets/<tid>/submit-for-signature")
def submit_ticket(tid):
    _, role = ctx()
    need(role, ["Superintendent"])
    t = get_ticket(tid)
    if t["status"] != "DRAFT":
        raise ApiError(
            "ERR_TICKET_INVALID_TRANSITION", 409, "Ticket must be DRAFT"
        )
    report = get_report(t["report_id"])
    require_editable(report)
    # priority 8.6: non-empty
    if t["total_cents"] <= 0:
        raise ApiError(
            "ERR_TICKET_EMPTY", 422, "Ticket total must be greater than zero"
        )
    t["status"] = "PENDING_SIGNATURES"
    touch(t)
    bump_report(report)
    return success(ser_ticket(t), 200)


@bp.post("/tm-tickets/<tid>/sign")
def sign_ticket(tid):
    uid, role = ctx()
    need(role, ["ContractorRep", "OwnerRep"])
    t = get_ticket(tid)
    b = body()
    signer_role = req_enum(b, "signer_role", ("CONTRACTOR", "OWNER"))
    # signer_role must match the caller's actual role
    if signer_role == "CONTRACTOR" and role != "ContractorRep":
        raise ApiError(
            "ERR_FORBIDDEN", 403, "CONTRACTOR signature requires ContractorRep"
        )
    if signer_role == "OWNER" and role != "OwnerRep":
        raise ApiError("ERR_FORBIDDEN", 403, "OWNER signature requires OwnerRep")
    # priority 6: state
    if t["status"] not in ("PENDING_SIGNATURES", "PARTIALLY_SIGNED"):
        raise ApiError(
            "ERR_TICKET_INVALID_TRANSITION",
            409,
            "Ticket is not accepting signatures",
        )
    if signer_role == "CONTRACTOR":
        if t["contractor_signed_by"] is not None:
            raise ApiError(
                "ERR_TICKET_INVALID_TRANSITION",
                409,
                "Contractor has already signed",
            )
        # priority 8: segregation vs creator
        if uid == t["created_by_user_id"]:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                403,
                "Signer must differ from the ticket creator",
            )
        t["contractor_signed_by"] = uid
        t["status"] = "PARTIALLY_SIGNED"
    else:  # OWNER
        # priority 8: segregation vs creator and contractor signer
        if uid == t["created_by_user_id"] or uid == t["contractor_signed_by"]:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                403,
                "Owner signer must differ from creator and contractor signer",
            )
        # priority 8.1: owner signs only after contractor
        if t["contractor_signed_by"] is None:
            raise ApiError(
                "ERR_SIGNATURE_ORDER",
                409,
                "Owner cannot sign before the contractor",
            )
        t["owner_signed_by"] = uid
        t["status"] = "FULLY_SIGNED"
    touch(t)
    return success(ser_ticket(t), 200)


@bp.post("/tm-tickets/<tid>/approve")
def approve_ticket(tid):
    uid, role = ctx()
    need(role, ["ProjectManager"])
    t = get_ticket(tid)
    if t["status"] != "FULLY_SIGNED":
        raise ApiError(
            "ERR_TICKET_INVALID_TRANSITION", 409, "Ticket must be FULLY_SIGNED"
        )
    # priority 8: segregation vs creator
    if uid == t["created_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "Approver must differ from the ticket creator",
        )
    # priority 10.7: report must have left DRAFT/REVISION_REQUESTED
    report = get_report(t["report_id"])
    if report["status"] in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError(
            "ERR_TICKET_REPORT_NOT_SUBMITTED",
            409,
            "Report must be submitted before ticket approval",
        )
    # priority 11: fiscal ceiling gate (equality passes)
    if (
        t["authorized_ceiling_cents"] is not None
        and t["total_cents"] > t["authorized_ceiling_cents"]
    ):
        raise ApiError(
            "ERR_TM_CEILING_EXCEEDED",
            422,
            "total_cents exceeds authorized_ceiling_cents",
        )
    t["status"] = "APPROVED"
    touch(t)
    return success(ser_ticket(t), 200)


@bp.post("/tm-tickets/<tid>/reject")
def reject_ticket(tid):
    _, role = ctx()
    need(role, ["ProjectManager"])
    t = get_ticket(tid)
    b = body()
    reason = req_str(b, "reason")
    if t["status"] != "FULLY_SIGNED":
        raise ApiError(
            "ERR_TICKET_INVALID_TRANSITION", 409, "Ticket must be FULLY_SIGNED"
        )
    t["status"] = "REJECTED"
    t["reject_reason"] = reason
    touch(t)
    return success(ser_ticket(t), 200)


@bp.post("/tm-tickets/<tid>/revise")
def revise_ticket(tid):
    _, role = ctx()
    need(role, ["Superintendent"])
    t = get_ticket(tid)
    if t["status"] != "REJECTED":
        raise ApiError(
            "ERR_TICKET_INVALID_TRANSITION", 409, "Ticket must be REJECTED to revise"
        )
    report = get_report(t["report_id"])
    require_editable(report)
    t["status"] = "DRAFT"
    t["revision_count"] += 1
    t["contractor_signed_by"] = None
    t["owner_signed_by"] = None
    touch(t)
    return success(ser_ticket(t), 200)


@bp.post("/tm-tickets/<tid>/void")
def void_ticket(tid):
    _, role = ctx()
    need(role, ["Superintendent"])
    t = get_ticket(tid)
    if t["status"] not in ("DRAFT", "PENDING_SIGNATURES", "PARTIALLY_SIGNED", "REJECTED"):
        raise ApiError(
            "ERR_TICKET_INVALID_TRANSITION",
            409,
            "Ticket status does not allow voiding",
        )
    report = get_report(t["report_id"])
    require_editable(report)
    was_draft = t["status"] == "DRAFT"
    t["status"] = "VOID"
    touch(t)
    if was_draft:
        bump_report(report)
    return success(ser_ticket(t), 200)


# ---------------------------------------------------------------------------
# distribution records
# ---------------------------------------------------------------------------

@bp.post("/distribution-records")
def create_distribution():
    _, role = ctx()
    need(role, ["ProjectManager"])
    b = body()
    report_id = req_str(b, "report_id")
    recipient_email = req_str(b, "recipient_email")
    recipient_role = req_enum(b, "recipient_role", RECIPIENT_ROLES)
    # priority 5: body FK existence
    report = get_report(report_id)
    # priority 8.2: recipient unique per report among existing records
    for d in store.distribution_records.values():
        if d["report_id"] == report_id and d["recipient_email"] == recipient_email:
            raise ApiError(
                "ERR_DUPLICATE_RECIPIENT",
                409,
                "Recipient already exists on this report",
            )
    # priority 10.4: report must be APPROVED or LOCKED; hold must be false
    if report["status"] not in ("APPROVED", "LOCKED"):
        raise ApiError(
            "ERR_REPORT_NOT_APPROVED",
            409,
            "Report must be APPROVED or LOCKED for distribution",
        )
    if distribution_hold(report):
        raise ApiError(
            "ERR_DISTRIBUTION_HOLD", 409, "Report is under a distribution hold"
        )
    rec = stamp(
        {
            "report_id": report_id,
            "recipient_email": recipient_email,
            "recipient_role": recipient_role,
            "status": "PENDING",
            "sent_at": None,
            "acknowledged_at": None,
        }
    )
    store.distribution_records[rec["id"]] = rec
    # creation does NOT advance the report version
    return success(ser_distribution(rec), 201)


@bp.get("/distribution-records/<did>")
def get_one_distribution(did):
    ctx()
    return success(ser_distribution(get_distribution(did)), 200)


@bp.get("/distribution-records")
def list_distribution():
    ctx()
    report_id = request.args.get("report_id")
    status = request.args.get("status")
    if status is not None and status not in DISTRIBUTION_STATUSES:
        bad("Invalid status filter")
    rows = list(store.distribution_records.values())
    if report_id is not None:
        rows = [r for r in rows if r["report_id"] == report_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, ser_distribution)


@bp.post("/distribution-records/<did>/send")
def send_distribution(did):
    _, role = ctx()
    need(role, ["SystemAdmin"])
    d = get_distribution(did)
    if d["status"] != "PENDING":
        raise ApiError(
            "ERR_DISTRIBUTION_INVALID_TRANSITION",
            409,
            "Only PENDING records can be sent",
        )
    report = get_report(d["report_id"])
    if distribution_hold(report):
        raise ApiError(
            "ERR_DISTRIBUTION_HOLD", 409, "Report is under a distribution hold"
        )
    d["status"] = "SENT"
    d["sent_at"] = clock.now()
    touch(d)
    bump_report(report)
    return success(ser_distribution(d), 200)


@bp.post("/distribution-records/<did>/acknowledge")
def acknowledge_distribution(did):
    _, role = ctx()
    need(role, ["OwnerRep"])
    d = get_distribution(did)
    if d["status"] != "SENT":
        raise ApiError(
            "ERR_DISTRIBUTION_INVALID_TRANSITION",
            409,
            "Only SENT records can be acknowledged",
        )
    d["status"] = "ACKNOWLEDGED"
    d["acknowledged_at"] = clock.now()
    touch(d)
    return success(ser_distribution(d), 200)


@bp.delete("/distribution-records/<did>")
def delete_distribution(did):
    _, role = ctx()
    need(role, ["ProjectManager"])
    d = get_distribution(did)
    if d["status"] in ("SENT", "ACKNOWLEDGED"):
        raise ApiError(
            "ERR_DISTRIBUTION_ALREADY_SENT",
            409,
            "SENT/ACKNOWLEDGED records are retained for claims",
        )
    del store.distribution_records[did]
    return success_empty(204)
