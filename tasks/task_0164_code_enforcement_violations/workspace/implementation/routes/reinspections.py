"""Reinspection endpoints (PRD §3.7) and notice fines sub-resource list."""

from flask import Blueprint, g

from clock import clock
from db import db, common_fields, touch
from errors import err
from middleware import require_roles
from response import success, list_success
from services import domain, serialize
from services.helpers import (
    get_body,
    lookup,
    pagination_params,
    paginate,
    require_enum,
    resolve_ref,
    sort_by_created,
)

bp = Blueprint("reinspections", __name__)

RESULTS = {"SCHEDULED", "PASSED", "FAILED"}
RESULT_INPUT = {"PASSED", "FAILED"}


@bp.post("/reinspections")
@require_roles("CodeOfficer")
def schedule_reinspection():
    body = get_body()
    if "notice_id" not in body or body["notice_id"] is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: notice_id")
    notice = resolve_ref(db.notices, body["notice_id"])

    record = common_fields()
    record.update({
        "notice_id": notice["id"],
        "requested_by_user_id": g.user_id,
        "result": "SCHEDULED",
        "result_on": None,
    })
    db.reinspections[record["id"]] = record
    return success(serialize.reinspection_out(record), status=201)


@bp.get("/notices/<nid>/reinspections")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk", "Registrant")
def list_notice_reinspections(nid):
    lookup(db.notices, nid)
    limit, offset = pagination_params()
    items = [r for r in db.reinspections.values() if r["notice_id"] == nid]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([serialize.reinspection_out(r) for r in page], limit, offset, total)


@bp.post("/reinspections/<rid>/result")
@require_roles("CodeOfficer")
def record_result(rid):
    reins = lookup(db.reinspections, rid)
    body = get_body()
    require_enum(body, "result", RESULT_INPUT)
    if reins["result"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "re-inspection result already recorded")

    now = clock.now()
    reins["result_on"] = now
    reins["result"] = body["result"]
    touch(reins)

    notice = db.notices.get(reins["notice_id"])
    if notice is not None:
        domain.evaluate_notice(notice)
        if body["result"] == "PASSED" and notice["status"] in ("ISSUED", "OVERDUE"):
            # Cure: notice -> COMPLIED, freeze settlement fine as-of result_on.
            was_issued_in_window = (
                notice["status"] == "ISSUED"
                and notice["compliance_deadline"] is not None
                and now <= notice["compliance_deadline"]
            )
            fs = domain.fee_schedule_for(notice["violation_class"])
            if was_issued_in_window:
                # Cured within window: no overdue accrual — settle to base only.
                notice["fine_total_cents"] = fs["base_fine_cents"] if fs else notice["fine_total_cents"]
                notice["days_overdue"] = 0
            else:
                # From OVERDUE: freeze settlement variant as-of result_on.
                domain.freeze_fine(notice, now)

            notice["status"] = "COMPLIED"
            touch(notice)

            # CITATION Fine settles iff assessed == base only; else stays OPEN.
            for f in domain.fines_for_notice(notice["id"]):
                if f["source_kind"] == "CITATION" and f["settlement_status"] == "OPEN":
                    if fs is not None and f["assessed_cents"] == fs["base_fine_cents"] \
                            and notice["fine_total_cents"] == fs["base_fine_cents"]:
                        f["settlement_status"] = "SETTLED"
                        touch(f)

            case = db.cases.get(notice["case_id"])
            if case is not None:
                domain.recompute_case(case)

    return success(serialize.reinspection_out(reins), status=200)


# Notice fines sub-resource (PRD §3.10).
@bp.get("/notices/<nid>/fines")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk", "Registrant")
def list_notice_fines(nid):
    lookup(db.notices, nid)
    limit, offset = pagination_params()
    items = [f for f in db.fines.values() if f["notice_id"] == nid]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([serialize.fine_out(f) for f in page], limit, offset, total)
