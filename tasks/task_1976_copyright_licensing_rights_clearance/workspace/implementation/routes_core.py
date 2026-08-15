"""Routes: logical clock, rights holders, assets, diligence logs, retire."""
from datetime import timedelta

from flask import request

import state as S
import services as svc
import serializers as SZ

ALL_READ_ROLES = ["AssetCurator", "ClearanceOfficer", "Negotiator",
                  "Requester", "LegalCertifier", "FinancePayer",
                  "IngestionAgent"]


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------
@S.endpoint("/rights/_clock/set_current_utc", ["POST"], ["AssetCurator"])
def set_clock(user_id, user_role):
    body = S.get_body()
    to = body.get("to_iso8601")
    dt = S.parse_dt(to)
    if dt is None:
        raise S.err("ERR_INVALID_REQUEST", 400,
                    "to_iso8601 must be a well-formed ISO8601 datetime")
    S.CLOCK["now"] = dt
    svc.run_clock_sweeps()
    return {"current_utc": S.ts3(S.CLOCK["now"])}, 200


# ---------------------------------------------------------------------------
# Rights holders (PRD 3.1)
# ---------------------------------------------------------------------------
@S.endpoint("/rights/rights-holders", ["POST"], ["AssetCurator"])
def create_rights_holder(user_id, user_role):
    body = S.get_body()
    legal_name = S.req_str(body, "legal_name")
    holder_kind = S.req_enum(body, "holder_kind", S.HOLDER_KINDS)
    mfn_floor_cents = S.req_int(body, "mfn_floor_cents", min_v=0)
    contact_verified = S.opt_bool(body, "contact_verified", default=False)
    h = S.stamp_new({
        "legal_name": legal_name,
        "holder_kind": holder_kind,
        "mfn_floor_cents": mfn_floor_cents,
        "contact_verified": contact_verified,
    })
    S.rights_holders[h["id"]] = h
    return SZ.serialize_rights_holder(h), 201


@S.endpoint("/rights/rights-holders/<hid>", ["GET"], ALL_READ_ROLES)
def get_rights_holder(hid, user_id, user_role):
    h = svc.get_holder(hid)
    if h is None:
        raise S.err("ERR_NOT_FOUND", 404, "RightsHolder not found")
    return SZ.serialize_rights_holder(h), 200


@S.endpoint("/rights/rights-holders", ["GET"], ALL_READ_ROLES)
def list_rights_holders(user_id, user_role):
    limit, offset = S.pagination_params()
    items = sorted(S.rights_holders.values(),
                   key=lambda h: (h["created_at"], h["_seq"]))
    return S.paginate([SZ.serialize_rights_holder(h) for h in items],
                      limit, offset)


# ---------------------------------------------------------------------------
# Assets (PRD 3.1)
# ---------------------------------------------------------------------------
@S.endpoint("/rights/assets", ["POST"], ["AssetCurator"])
def create_asset(user_id, user_role):
    body = S.get_body()
    title = S.req_str(body, "title")
    work_kind = S.req_enum(body, "work_kind", S.WORK_KINDS)
    permitted_media = body.get("permitted_media")
    if (not isinstance(permitted_media, list) or not permitted_media
            or any(not isinstance(m, str) or m not in S.MEDIA_KINDS
                   for m in permitted_media)):
        raise S.err("ERR_INVALID_REQUEST", 400,
                    "permitted_media must be a non-empty list of media kinds")
    embargo_until = S.opt_dt(body, "embargo_until")
    rights_holder_id = S.opt_str(body, "rights_holder_id")
    if rights_holder_id is not None and svc.get_holder(rights_holder_id) is None:
        raise S.err("ERR_NOT_FOUND", 404, "rights_holder_id not found")
    orphan_status = "NOT_ORPHAN" if rights_holder_id is not None \
        else "DILIGENCE_PENDING"
    a = S.stamp_new({
        "title": title,
        "work_kind": work_kind,
        "permitted_media": list(permitted_media),
        "embargo_until": embargo_until,
        "rights_holder_id": rights_holder_id,
        "orphan_status": orphan_status,
        "posture": "CLEAR",
        "retired_at": None,
    })
    S.assets[a["id"]] = a
    # PRD 3.1: a newly registered asset enters with posture CLEAR regardless of
    # orphan_status; posture re-derives on subsequent change triggers (2.9).
    return SZ.serialize_asset(a), 201


@S.endpoint("/rights/assets/<aid>", ["GET"], ALL_READ_ROLES)
def get_asset(aid, user_id, user_role):
    a = svc.get_asset(aid)
    if a is None:
        raise S.err("ERR_NOT_FOUND", 404, "Asset not found")
    return SZ.serialize_asset(a), 200


@S.endpoint("/rights/assets", ["GET"], ALL_READ_ROLES)
def list_assets(user_id, user_role):
    limit, offset = S.pagination_params()
    posture_f = request.args.get("posture")
    holder_f = request.args.get("rights_holder_id")
    items = sorted(S.assets.values(), key=lambda a: (a["created_at"], a["_seq"]))
    if posture_f is not None:
        items = [a for a in items if a["posture"] == posture_f]
    if holder_f is not None:
        items = [a for a in items if a.get("rights_holder_id") == holder_f]
    return S.paginate([SZ.serialize_asset(a) for a in items], limit, offset)


# ---------------------------------------------------------------------------
# Asset retirement (PRD 3.9)
# ---------------------------------------------------------------------------
@S.endpoint("/rights/assets/<aid>/retire", ["POST"], ["AssetCurator"])
def retire_asset(aid, user_id, user_role):
    a = svc.get_asset(aid)
    if a is None:
        raise S.err("ERR_NOT_FOUND", 404, "Asset not found")
    if a["posture"] == "RETIRED" or a.get("retired_at") is not None:
        raise S.err("ERR_ALREADY_TERMINAL", 409, "Asset is already retired")
    for lic in svc.asset_licenses(aid):
        if lic["lifecycle"] in ("ACTIVE", "SUSPENDED"):
            raise S.err("ERR_ASSET_HAS_LIVE_LICENSES", 409,
                        "Asset has licenses in ACTIVE/SUSPENDED lifecycle")
    for r in svc.asset_requests(aid):
        if r["status"] in ("SUBMITTED", "HOLDER_REVIEW", "NEGOTIATING",
                           "APPROVED"):
            raise S.err("ERR_ASSET_HAS_OPEN_REQUESTS", 409,
                        "Asset has clearance requests in open states")
    a["retired_at"] = S.now_dt()
    a["posture"] = "RETIRED"
    # cancel any SCHEDULED alerts under this asset's licenses
    for lic in svc.asset_licenses(aid):
        for alert in svc.license_alerts(lic["id"]):
            if alert["status"] == "SCHEDULED":
                alert["status"] = "CANCELLED"
                S.touch(alert)
    S.touch(a)
    return SZ.serialize_asset(a), 200


# ---------------------------------------------------------------------------
# Diligence logs (PRD 3.1)
# ---------------------------------------------------------------------------
def _maybe_certify_orphan(asset):
    """ORPHAN_CERTIFY_RULE (scaffold desk_constants): rights_holder_id null AND
    >= 3 logs with pairwise distinct search_channel, every outcome NO_RESULT,
    and (last.created_at - first.created_at) >= 30 days."""
    if asset.get("rights_holder_id") is not None:
        return
    if asset["orphan_status"] != "DILIGENCE_PENDING":
        return
    logs = svc.asset_diligence_logs(asset["id"])
    qualifying = [d for d in logs if d["outcome"] == "NO_RESULT"]
    channels = {d["search_channel"] for d in qualifying}
    if len(qualifying) < S.ORPHAN_MIN_CHANNELS:
        return
    if len(channels) < S.ORPHAN_MIN_CHANNELS:
        return
    # every qualifying log must be NO_RESULT — and per the rule, "every log
    # outcome == NO_RESULT" applies to the qualifying set; a HOLDER_FOUND or
    # CONFLICTING_CLAIM log in the history blocks certification.
    if any(d["outcome"] != "NO_RESULT" for d in logs):
        return
    span = (qualifying[-1]["created_at"] - qualifying[0]["created_at"])
    if span < timedelta(days=S.ORPHAN_MIN_SPAN_DAYS):
        return
    asset["orphan_status"] = "ORPHAN_CERTIFIED"
    svc.recompute_asset_posture(asset)


@S.endpoint("/rights/assets/<aid>/diligence-logs", ["POST"], ["AssetCurator"])
def create_diligence_log(aid, user_id, user_role):
    a = svc.get_asset(aid)
    if a is None:
        raise S.err("ERR_NOT_FOUND", 404, "Asset not found")
    body = S.get_body()
    search_channel = S.req_enum(body, "search_channel", S.SEARCH_CHANNELS)
    outcome = S.req_enum(body, "outcome", S.DILIGENCE_OUTCOMES)
    notes = S.req_str(body, "notes")
    d = S.stamp_new_lean({
        "asset_id": aid,
        "search_channel": search_channel,
        "outcome": outcome,
        "notes": notes,
    })
    S.diligence_logs[d["id"]] = d
    _maybe_certify_orphan(a)
    # diligence-log append is always a posture-recompute trigger (PRD 2.9)
    svc.recompute_asset_posture(a)
    return SZ.serialize_diligence_log(d), 201


@S.endpoint("/rights/assets/<aid>/diligence-logs", ["GET"],
            ["AssetCurator", "ClearanceOfficer", "LegalCertifier"])
def list_diligence_logs(aid, user_id, user_role):
    a = svc.get_asset(aid)
    if a is None:
        raise S.err("ERR_NOT_FOUND", 404, "Asset not found")
    limit, offset = S.pagination_params()
    logs = svc.asset_diligence_logs(aid)
    return S.paginate([SZ.serialize_diligence_log(d) for d in logs],
                      limit, offset)
