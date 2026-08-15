from decimal import Decimal
from flask import Blueprint, request

import store as db
import logical_clock as clock
from auth import authorize
from envelope import obj, arr, page
from errors import ApiError
from logic import (new_common, touch, get_or_404, resolve, month_add,
                   compute_drift, pin_expiry_cascade, RISK_DELTA_MAX)
from serialize import ips_out, target_out
from validate import (body, no_unknown, req_str, req_int, opt_int, pagination,
                      req_list, req_enum, req_pct)

bp = Blueprint("ips", __name__)

ASSET_CLASSES = {"US_EQUITY", "INTL_EQUITY", "FIXED_INCOME", "CASH_EQUIVALENT",
                 "ALTERNATIVES"}


def _targets_of(ips_id):
    rows = [t for t in db.targets.values() if t["ips_id"] == ips_id]
    rows.sort(key=lambda t: (t["created_dt"], t["_seq"]))
    return rows


def _client_owns(uid, ips):
    if ips["client_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Clients may access only their own household's records")


@bp.post("/advisory/ips-policies")
def create_ips():
    authorize("Advisor")
    b = body()
    no_unknown(b, {"client_id", "benchmark_id", "objective_text",
                   "risk_tolerance_score", "review_cadence_months"})
    client_id = req_str(b, "client_id")
    benchmark_id = req_str(b, "benchmark_id")
    objective_text = req_str(b, "objective_text")
    risk = req_int(b, "risk_tolerance_score", 1, 100)
    cadence = opt_int(b, "review_cadence_months", 1, 24, default=12)
    client = resolve(db.clients, client_id, "client_id")
    resolve(db.benchmarks, benchmark_id, "benchmark_id")
    if client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_INVALID_STATE", 409,
                       "IPS drafts require an ACTIVE client")
    ips = new_common()
    ips.update({
        "client_id": client_id, "benchmark_id": benchmark_id,
        "objective_text": objective_text, "risk_tolerance_score": risk,
        "review_cadence_months": cadence, "status": "DRAFT",
        "activated_at_dt": None, "next_review_due_dt": None,
        "supersedes_ips_id": None,
    })
    db.ips_policies[ips["id"]] = ips
    return obj(ips_out(ips), 201)


@bp.get("/advisory/ips-policies")
def list_ips():
    uid, role = authorize("Advisor", "ComplianceOfficer", "Client")
    limit, offset = pagination()
    rows = sorted(db.ips_policies.values(), key=lambda e: (e["created_dt"], e["_seq"]))
    if role == "Client":
        rows = [i for i in rows if i["client_id"] == uid]
    client_id = request.args.get("client_id")
    if client_id is not None:
        rows = [i for i in rows if i["client_id"] == client_id]
    benchmark_id = request.args.get("benchmark_id")
    if benchmark_id is not None:
        rows = [i for i in rows if i["benchmark_id"] == benchmark_id]
    sup = request.args.get("supersedes_ips_id")
    if sup is not None:
        rows = [i for i in rows if i["supersedes_ips_id"] == sup]
    status = request.args.get("status")
    if status is not None:
        rows = [i for i in rows if i["status"] == status]
    total = len(rows)
    return page([ips_out(i) for i in rows[offset:offset + limit]],
                limit, offset, total)


@bp.get("/advisory/ips-policies/<iid>")
def get_ips(iid):
    uid, role = authorize("Advisor", "ComplianceOfficer", "Client")
    ips = get_or_404(db.ips_policies, iid)
    if role == "Client":
        _client_owns(uid, ips)
    return obj(ips_out(ips))


@bp.put("/advisory/ips-policies/<iid>/allocation-targets")
def replace_targets(iid):
    authorize("Advisor")
    b = body()
    no_unknown(b, {"targets"})
    items = req_list(b, "targets")
    seen = set()
    parsed = []
    for item in items:
        if not isinstance(item, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Each target must be an object")
        no_unknown(item, {"asset_class", "target_pct", "band_pct"})
        ac = req_enum(item, "asset_class", ASSET_CLASSES)
        if ac in seen:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Duplicate asset_class in targets array")
        seen.add(ac)
        tp = req_pct(item, "target_pct", 100)
        bpct = req_pct(item, "band_pct", 50)
        parsed.append((ac, tp, bpct))
    ips = get_or_404(db.ips_policies, iid)
    if ips["status"] != "DRAFT":
        raise ApiError("ERR_IPS_INVALID_STATE", 409,
                       "Allocation targets may be replaced only while DRAFT")
    for tid in [t["id"] for t in _targets_of(iid)]:
        del db.targets[tid]
    out = []
    for ac, tp, bpct in parsed:
        t = new_common()
        t.update({"ips_id": iid, "asset_class": ac, "target_pct": tp,
                  "band_pct": bpct})
        db.targets[t["id"]] = t
        out.append(target_out(t))
    # Deliberately does NOT modify the IPS's own version.
    return arr(out, 200)


@bp.get("/advisory/ips-policies/<iid>/allocation-targets")
def list_targets(iid):
    uid, role = authorize("Advisor", "ComplianceOfficer", "Client")
    ips = get_or_404(db.ips_policies, iid)
    if role == "Client":
        _client_owns(uid, ips)
    limit, offset = pagination()
    rows = _targets_of(iid)
    total = len(rows)
    return page([target_out(t) for t in rows[offset:offset + limit]],
                limit, offset, total)


@bp.post("/advisory/ips-policies/<iid>/submit")
def submit_ips(iid):
    authorize("Advisor")
    if request.data:
        no_unknown(body(), set())
    ips = get_or_404(db.ips_policies, iid)
    if ips["status"] != "DRAFT":
        raise ApiError("ERR_IPS_INVALID_STATE", 409, "Submit requires DRAFT")
    tgs = _targets_of(iid)
    if not tgs or sum((t["target_pct"] for t in tgs), Decimal("0")) != Decimal("100.00"):
        raise ApiError("ERR_ALLOCATION_SUM_INVALID", 422,
                       "At least one target and SUM(target_pct) == 100.00 required")
    client = db.clients[ips["client_id"]]
    if abs(ips["risk_tolerance_score"] - client["risk_tolerance_score"]) > RISK_DELTA_MAX:
        raise ApiError("ERR_RISK_TOLERANCE_MISMATCH", 422,
                       "IPS risk score beyond +/-10 of the client's")
    if client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_INVALID_STATE", 409, "Client must be ACTIVE")
    ips["status"] = "PENDING_COMPLIANCE"
    touch(ips)
    return obj(ips_out(ips))


@bp.post("/advisory/ips-policies/<iid>/compliance-approve")
def compliance_approve(iid):
    authorize("ComplianceOfficer")
    if request.data:
        no_unknown(body(), set())
    ips = get_or_404(db.ips_policies, iid)
    if ips["status"] != "PENDING_COMPLIANCE":
        raise ApiError("ERR_IPS_INVALID_STATE", 409,
                       "Compliance approval requires PENDING_COMPLIANCE")
    ips["status"] = "PENDING_CLIENT"
    touch(ips)
    return obj(ips_out(ips))


@bp.post("/advisory/ips-policies/<iid>/compliance-reject")
def compliance_reject(iid):
    authorize("ComplianceOfficer")
    if request.data:
        no_unknown(body(), {"reason"})
        b = body()
        if "reason" in b and b["reason"] is not None and not isinstance(b["reason"], str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "reason must be a string")
    ips = get_or_404(db.ips_policies, iid)
    if ips["status"] != "PENDING_COMPLIANCE":
        raise ApiError("ERR_IPS_INVALID_STATE", 409,
                       "Compliance rejection requires PENDING_COMPLIANCE")
    ips["status"] = "DRAFT"
    touch(ips)
    return obj(ips_out(ips))


@bp.post("/advisory/ips-policies/<iid>/client-sign")
def client_sign(iid):
    uid, role = authorize("Client")
    if request.data:
        no_unknown(body(), set())
    ips = get_or_404(db.ips_policies, iid)
    if ips["client_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Only the owning client may sign")
    if ips["status"] != "PENDING_CLIENT":
        raise ApiError("ERR_IPS_INVALID_STATE", 409,
                       "Client signature requires PENDING_CLIENT")
    client = db.clients[ips["client_id"]]
    if client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_INVALID_STATE", 409, "Client must be ACTIVE")
    benchmark = db.benchmarks[ips["benchmark_id"]]
    if benchmark["status"] != "ACTIVE":
        raise ApiError("ERR_BENCHMARK_NOT_ACTIVE", 422,
                       "Referenced benchmark is not ACTIVE")
    # Supersede the prior ACTIVE IPS of this client (if any).
    prior = None
    for other in db.ips_policies.values():
        if (other["client_id"] == ips["client_id"] and other["status"] == "ACTIVE"
                and other["id"] != ips["id"]):
            prior = other
            break
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
        pin_expiry_cascade(prior["id"])
    ips["supersedes_ips_id"] = prior["id"] if prior is not None else None
    ips["status"] = "ACTIVE"
    ips["activated_at_dt"] = clock.now()
    ips["next_review_due_dt"] = month_add(ips["activated_at_dt"],
                                          ips["review_cadence_months"])
    touch(ips)
    # Drift recompute for every non-CLOSED portfolio of the client.
    for pf in db.portfolios.values():
        if pf["client_id"] == ips["client_id"] and pf["lifecycle_status"] != "CLOSED":
            pf["drift_status"] = compute_drift(pf)
            touch(pf)
    return obj(ips_out(ips))


@bp.post("/advisory/ips-policies/<iid>/client-decline")
def client_decline(iid):
    uid, role = authorize("Client")
    if request.data:
        b = body()
        no_unknown(b, {"reason"})
        if "reason" in b and b["reason"] is not None and not isinstance(b["reason"], str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "reason must be a string")
    ips = get_or_404(db.ips_policies, iid)
    if ips["client_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Only the owning client may decline")
    if ips["status"] != "PENDING_CLIENT":
        raise ApiError("ERR_IPS_INVALID_STATE", 409,
                       "Client decline requires PENDING_CLIENT")
    ips["status"] = "DRAFT"
    touch(ips)
    return obj(ips_out(ips))


@bp.post("/advisory/ips-policies/<iid>/complete-review")
def complete_review(iid):
    authorize("Advisor")
    if request.data:
        no_unknown(body(), set())
    ips = get_or_404(db.ips_policies, iid)
    if ips["status"] != "ACTIVE":
        raise ApiError("ERR_IPS_INVALID_STATE", 409,
                       "Complete-review requires ACTIVE")
    # Chronological accumulator: advance by cadence until strictly in the future.
    while ips["next_review_due_dt"] <= clock.now():
        ips["next_review_due_dt"] = month_add(ips["next_review_due_dt"],
                                              ips["review_cadence_months"])
    touch(ips)
    return obj(ips_out(ips))
