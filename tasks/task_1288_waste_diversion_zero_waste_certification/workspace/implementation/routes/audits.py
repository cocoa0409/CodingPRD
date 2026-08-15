"""WasteAudit endpoints (immutable measurement log: id + created_at only)."""

from flask import Blueprint

from db import new_id, now_ts, store
from errors import ApiError, ERR_INVALID_REQUEST, not_found
from middleware import (
    ALL_ROLES,
    authenticate,
    check_unknown,
    f_date,
    f_str,
    get_body,
)
from response import success_list, success_object
from services.lifecycle import pub_audit
from util import MATERIAL_STREAMS, apply_filters, paginate, sort_items

bp = Blueprint("audits", __name__)


def _validate_findings(v):
    if not isinstance(v, list):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "stream_findings must be an array")
    out = []
    for i, item in enumerate(v):
        if not isinstance(item, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           f"stream_findings[{i}] must be an object")
        check_unknown(item, ["material_stream", "sampled_weight_lbs",
                             "contamination_pct"])
        stream = item.get("material_stream")
        if not isinstance(stream, str) or stream not in MATERIAL_STREAMS:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           f"stream_findings[{i}].material_stream is invalid")
        w = item.get("sampled_weight_lbs")
        if isinstance(w, bool) or not isinstance(w, int) or w < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           f"stream_findings[{i}].sampled_weight_lbs must be a "
                           "non-negative integer")
        pct = item.get("contamination_pct")
        if (isinstance(pct, bool) or not isinstance(pct, (int, float))
                or pct < 0 or pct > 100):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           f"stream_findings[{i}].contamination_pct must be a "
                           "number between 0 and 100")
        out.append({
            "material_stream": stream,
            "sampled_weight_lbs": w,
            "contamination_pct": pct,
        })
    return out


@bp.route("/audits", methods=["POST"])
def create_audit():
    authenticate(["WasteAuditor"])
    b = get_body()
    check_unknown(b, ["site_id", "audit_date", "auditor_name", "stream_findings"])
    site_id = f_str(b, "site_id")
    audit_date = f_date(b, "audit_date")
    auditor = f_str(b, "auditor_name")
    if "stream_findings" not in b:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Missing required field: stream_findings")
    findings = _validate_findings(b["stream_findings"])

    if site_id not in store.sites:
        raise not_found("Site not found")

    rec = {
        "id": new_id(),
        "created_at": now_ts(),
        "_seq": store.next_seq(),
        "site_id": site_id,
        "audit_date": audit_date,
        "auditor_name": auditor,
        "stream_findings": findings,
    }
    store.audits[rec["id"]] = rec
    return success_object(pub_audit(rec), 201)


@bp.route("/audits/<audit_id>", methods=["GET"])
def get_audit(audit_id):
    authenticate(ALL_ROLES)
    rec = store.audits.get(audit_id)
    if rec is None:
        raise not_found("Audit not found")
    return success_object(pub_audit(rec))


@bp.route("/audits", methods=["GET"])
def list_audits():
    authenticate(ALL_ROLES)
    items = apply_filters(store.audits.values(), [("site_id", "site_id", None)])
    page, meta = paginate(sort_items(items))
    return success_list([pub_audit(a) for a in page], meta)
