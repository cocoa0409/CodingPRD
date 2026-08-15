from flask import Blueprint, request

import store as db
import logical_clock as clock
from auth import authorize
from envelope import obj, page
from errors import ApiError
from logic import (new_common, touch, get_or_404, resolve, restriction_status)
from serialize import restricted_out
from validate import (body, no_unknown, req_str, req_enum, req_dt, opt_str,
                      pagination)

bp = Blueprint("restricted", __name__)


@bp.post("/advisory/restricted-list-entries")
def create_entry():
    authorize("ComplianceOfficer")
    b = body()
    no_unknown(b, {"security_id", "restriction_level", "effective_from",
                   "effective_to", "reason"})
    security_id = req_str(b, "security_id")
    level = req_enum(b, "restriction_level", {"NO_BUY", "NO_TRADE"})
    from_dt = req_dt(b, "effective_from")
    to_dt = req_dt(b, "effective_to")
    reason = opt_str(b, "reason", "")
    resolve(db.securities, security_id, "security_id")
    if not from_dt < to_dt:
        raise ApiError("ERR_INVALID_DATE_RANGE", 422,
                       "effective_from must be strictly earlier than effective_to")
    # Half-open [from, to) windows for the same security: any overlap rejected;
    # adjacency (a.to == b.from) permitted.
    for e in db.restricted.values():
        if e["security_id"] != security_id:
            continue
        if from_dt < e["to_dt"] and e["from_dt"] < to_dt:
            raise ApiError("ERR_RESTRICTION_WINDOW_OVERLAP", 422,
                           "Restriction windows for the same security overlap")
    e = new_common()
    e.update({"security_id": security_id, "restriction_level": level,
              "from_dt": from_dt, "to_dt": to_dt, "reason": reason})
    db.restricted[e["id"]] = e
    return obj(restricted_out(e), 201)


@bp.get("/advisory/restricted-list-entries")
def list_entries():
    authorize("Advisor", "ComplianceOfficer")
    limit, offset = pagination()
    rows = sorted(db.restricted.values(), key=lambda e: (e["created_dt"], e["_seq"]))
    sec_id = request.args.get("security_id")
    if sec_id is not None:
        rows = [e for e in rows if e["security_id"] == sec_id]
    level = request.args.get("restriction_level")
    if level is not None:
        rows = [e for e in rows if e["restriction_level"] == level]
    status = request.args.get("status")
    if status is not None:
        rows = [e for e in rows if restriction_status(e) == status]
    total = len(rows)
    return page([restricted_out(e) for e in rows[offset:offset + limit]],
                limit, offset, total)


@bp.get("/advisory/restricted-list-entries/<eid>")
def get_entry(eid):
    authorize("Advisor", "ComplianceOfficer")
    e = get_or_404(db.restricted, eid)
    return obj(restricted_out(e))


@bp.post("/advisory/restricted-list-entries/<eid>/terminate")
def terminate_entry(eid):
    authorize("ComplianceOfficer")
    if request.data:
        no_unknown(body(), set())
    e = get_or_404(db.restricted, eid)
    if restriction_status(e) == "EXPIRED":
        raise ApiError("ERR_INVALID_DATE_RANGE", 422,
                       "Restriction entry is already EXPIRED")
    e["to_dt"] = clock.now()
    touch(e)
    return obj(restricted_out(e))
