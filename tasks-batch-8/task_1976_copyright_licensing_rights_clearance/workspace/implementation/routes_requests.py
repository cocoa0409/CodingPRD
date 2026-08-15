"""Routes: clearance requests, negotiation rounds, license grant."""
import state as S
import services as svc
import serializers as SZ

CR_READ_ROLES = ["AssetCurator", "ClearanceOfficer", "Negotiator",
                 "Requester", "LegalCertifier", "FinancePayer"]


def _get_asset_or_404(aid):
    a = svc.get_asset(aid)
    if a is None:
        raise S.err("ERR_NOT_FOUND", 404, "Asset not found")
    return a


def _get_request_or_404(rid):
    r = svc.get_request(rid)
    if r is None:
        raise S.err("ERR_NOT_FOUND", 404, "ClearanceRequest not found")
    return r


def _check_embargo(asset, use_start_at):
    """Embargo gate (scaffold embargo_gate): equality passes."""
    if asset.get("embargo_until") is None:
        return
    from datetime import timedelta
    gate = asset["embargo_until"] + timedelta(days=S.EMBARGO_BUFFER_DAYS)
    if use_start_at < gate:
        raise S.err("ERR_EMBARGO_ACTIVE", 422,
                    "use_start_at is earlier than embargo_until + 30 days")


# ---------------------------------------------------------------------------
# Clearance request intake (PRD 3.2)
# ---------------------------------------------------------------------------
@S.endpoint("/rights/assets/<aid>/clearance-requests", ["POST"], ["Requester"])
def create_clearance_request(aid, user_id, user_role):
    a = _get_asset_or_404(aid)
    body = S.get_body()
    media = S.req_enum(body, "media", S.MEDIA_KINDS)
    territory = S.req_enum(body, "territory", S.TERRITORIES)
    use_start_at = S.req_dt(body, "use_start_at")
    use_end_at = S.req_dt(body, "use_end_at")
    requested_units = S.req_int(body, "requested_units", min_v=1)
    # temporal rules: half-open window, end strictly after start
    if use_end_at <= use_start_at:
        raise S.err("ERR_INVALID_WINDOW", 422,
                    "use_end_at must be strictly after use_start_at")
    # embargo gate at creation (PRD 3.2)
    _check_embargo(a, use_start_at)
    r = S.stamp_new({
        "asset_id": aid,
        "requester_id": user_id,
        "media": media,
        "territory": territory,
        "use_start_at": use_start_at,
        "use_end_at": use_end_at,
        "requested_units": requested_units,
        "status": "SUBMITTED",
        "negotiation_round": 0,
        "agreed_fee_cents": None,
        "fair_use_assessment_id": None,
    })
    S.clearance_requests[r["id"]] = r
    return SZ.serialize_clearance_request(r), 201


@S.endpoint("/rights/clearance-requests/<rid>", ["GET"], CR_READ_ROLES)
def get_clearance_request(rid, user_id, user_role):
    r = _get_request_or_404(rid)
    return SZ.serialize_clearance_request(r), 200


@S.endpoint("/rights/clearance-requests", ["GET"], CR_READ_ROLES)
def list_clearance_requests(user_id, user_role):
    limit, offset = S.pagination_params()
    status_f = S.request_args_get("status")
    fua_f = S.request_args_get("fair_use_assessment_id")
    items = sorted(S.clearance_requests.values(),
                   key=lambda r: (r["created_at"], r["_seq"]))
    if status_f is not None:
        items = [r for r in items if r["status"] == status_f]
    if fua_f is not None:
        items = [r for r in items if r.get("fair_use_assessment_id") == fua_f]
    return S.paginate([SZ.serialize_clearance_request(r) for r in items],
                      limit, offset)


@S.endpoint("/rights/assets/<aid>/clearance-requests", ["GET"], CR_READ_ROLES)
def list_asset_clearance_requests(aid, user_id, user_role):
    _get_asset_or_404(aid)
    limit, offset = S.pagination_params()
    status_f = S.request_args_get("status")
    items = sorted(svc.asset_requests(aid),
                   key=lambda r: (r["created_at"], r["_seq"]))
    if status_f is not None:
        items = [r for r in items if r["status"] == status_f]
    return S.paginate([SZ.serialize_clearance_request(r) for r in items],
                      limit, offset)


# ---------------------------------------------------------------------------
# Advance (SUBMITTED -> HOLDER_REVIEW -> NEGOTIATING), OCC-guarded (PRD 3.2)
# ---------------------------------------------------------------------------
@S.endpoint("/rights/clearance-requests/<rid>/advance", ["POST"],
            ["ClearanceOfficer"])
def advance_clearance_request(rid, user_id, user_role):
    r = _get_request_or_404(rid)
    body = S.get_body()
    expected = S.req_int(body, "expected_clearance_version", min_v=0)
    # OCC (PRD 2.7)
    if expected != r["version"]:
        raise S.err("ERR_STALE_VERSION", 412,
                    "expected_clearance_version does not match current version")
    asset = svc.get_asset(r["asset_id"])
    if r["status"] == "SUBMITTED":
        # Pinned gate order (PRD 3.2): orphan -> media -> posture; embargo
        # re-evaluated at this first advance.
        if asset["orphan_status"] == "DILIGENCE_PENDING":
            raise S.err("ERR_ORPHAN_DILIGENCE_INCOMPLETE", 409,
                        "Orphan diligence incomplete")
        if (asset["orphan_status"] == "ORPHAN_CERTIFIED"
                and asset.get("rights_holder_id") is not None):
            raise S.err("ERR_ORPHAN_DILIGENCE_INCOMPLETE", 409,
                        "Orphan certification invalid once holder identified")
        if r["media"] not in asset["permitted_media"]:
            raise S.err("ERR_MEDIA_NOT_PERMITTED", 409,
                        "Requested media not in asset.permitted_media")
        if asset["posture"] != "CLEAR":
            raise S.err("ERR_ASSET_POSTURE_BLOCKED", 409,
                        "Asset posture is not CLEAR")
        _check_embargo(asset, r["use_start_at"])
        r["status"] = "HOLDER_REVIEW"
    elif r["status"] == "HOLDER_REVIEW":
        if (asset.get("rights_holder_id") is None
                and asset["orphan_status"] != "ORPHAN_CERTIFIED"):
            raise S.err("ERR_RIGHTS_HOLDER_UNIDENTIFIED", 409,
                        "No rights holder and asset not ORPHAN_CERTIFIED")
        r["status"] = "NEGOTIATING"
        # negotiation_round stays 0; provisional estimate available
    else:
        raise S.err("ERR_INVALID_STATE", 409,
                    "Cannot advance from state %s" % r["status"])
    S.touch(r)
    return SZ.serialize_clearance_request(r), 200


# ---------------------------------------------------------------------------
# Deny / withdraw (PRD 3.2)
# ---------------------------------------------------------------------------
def _reject_open_rounds(req):
    for rnd in svc.request_rounds(req["id"]):
        if rnd["outcome"] == "OPEN":
            rnd["outcome"] = "REJECTED"


@S.endpoint("/rights/clearance-requests/<rid>/deny", ["POST"],
            ["ClearanceOfficer"])
def deny_clearance_request(rid, user_id, user_role):
    r = _get_request_or_404(rid)
    if r["status"] not in ("SUBMITTED", "HOLDER_REVIEW", "NEGOTIATING"):
        raise S.err("ERR_INVALID_STATE", 409,
                    "Cannot deny from state %s" % r["status"])
    if r["status"] == "NEGOTIATING":
        _reject_open_rounds(r)
    r["status"] = "DENIED"
    S.touch(r)
    return SZ.serialize_clearance_request(r), 200


@S.endpoint("/rights/clearance-requests/<rid>/withdraw", ["POST"],
            ["Requester"])
def withdraw_clearance_request(rid, user_id, user_role):
    r = _get_request_or_404(rid)
    if r["status"] not in ("SUBMITTED", "HOLDER_REVIEW", "NEGOTIATING"):
        raise S.err("ERR_INVALID_STATE", 409,
                    "Cannot withdraw from state %s" % r["status"])
    if r["requester_id"] != user_id:
        raise S.err("ERR_FORBIDDEN_OWNER_ONLY", 403,
                    "Only the original requester may withdraw this request")
    if r["status"] == "NEGOTIATING":
        _reject_open_rounds(r)
    r["status"] = "WITHDRAWN"
    S.touch(r)
    return SZ.serialize_clearance_request(r), 200


# ---------------------------------------------------------------------------
# Negotiation rounds (PRD 3.3)
# ---------------------------------------------------------------------------
@S.endpoint("/rights/clearance-requests/<rid>/rounds", ["POST"],
            ["Negotiator", "RightsHolderRep"])
def post_negotiation_round(rid, user_id, user_role):
    r = _get_request_or_404(rid)
    body = S.get_body()
    offered_fee_cents = S.req_int(body, "offered_fee_cents", min_v=0)
    accept = S.opt_bool(body, "accept", default=False)
    if r["status"] != "NEGOTIATING":
        raise S.err("ERR_INVALID_STATE", 409,
                    "Rounds may only be posted while NEGOTIATING")
    # cap: a 6th round attempt is rejected
    if r["negotiation_round"] >= S.MAX_NEGOTIATION_ROUNDS:
        raise S.err("ERR_NEGOTIATION_EXHAUSTED", 409,
                    "Maximum negotiation rounds reached")
    offered_by_role = ("NEGOTIATOR" if user_role == "Negotiator"
                       else "RIGHTS_HOLDER_REP")
    rounds = svc.request_rounds(rid)
    # alternation: new round's offered_by_role must differ from latest
    if rounds:
        latest = rounds[-1]
        if latest["offered_by_role"] == offered_by_role:
            raise S.err("ERR_ROUND_ROLE_ALTERNATION", 409,
                        "Consecutive rounds by the same role are not allowed")
    if accept:
        # pinned order: alternation (above) -> MFN floor -> segregation
        asset = svc.get_asset(r["asset_id"])
        floor = svc.mfn_floor_cents(r)
        holder = (svc.get_holder(asset["rights_holder_id"])
                  if asset.get("rights_holder_id") else None)
        is_estate = holder is not None and holder["holder_kind"] == "ESTATE"
        if not is_estate and offered_fee_cents < floor:
            raise S.err("ERR_MFN_FLOOR_VIOLATION", 422,
                        "Accepted offer below the MFN floor")
        if r["requester_id"] == user_id:
            raise S.err("ERR_SEGREGATION_OF_DUTIES", 422,
                        "Requester may not accept a fee round")
    # persist round: supersede prior OPEN round
    for rnd in rounds:
        if rnd["outcome"] == "OPEN":
            rnd["outcome"] = "SUPERSEDED"
    outcome = "ACCEPTED" if accept else "OPEN"
    rnd = S.stamp_new_lean({
        "clearance_request_id": rid,
        "round_index": r["negotiation_round"] + 1,
        "offered_fee_cents": offered_fee_cents,
        "offered_by_role": offered_by_role,
        "outcome": outcome,
    })
    S.negotiation_rounds[rnd["id"]] = rnd
    r["negotiation_round"] = r["negotiation_round"] + 1
    if accept:
        r["status"] = "APPROVED"
        r["agreed_fee_cents"] = offered_fee_cents
        # cascade touch on parent asset (PRD 2.9)
        asset = svc.get_asset(r["asset_id"])
        svc.touch_asset(asset)
    S.touch(r)
    return SZ.serialize_negotiation_round(rnd), 201


@S.endpoint("/rights/clearance-requests/<rid>/rounds", ["GET"],
            ["ClearanceOfficer", "Negotiator", "RightsHolderRep",
             "Requester", "LegalCertifier", "FinancePayer"])
def list_negotiation_rounds(rid, user_id, user_role):
    _get_request_or_404(rid)
    limit, offset = S.pagination_params()
    rounds = svc.request_rounds(rid)
    return S.paginate([SZ.serialize_negotiation_round(x) for x in rounds],
                      limit, offset)


# ---------------------------------------------------------------------------
# License grant (PRD 3.4)
# ---------------------------------------------------------------------------
@S.endpoint("/rights/clearance-requests/<rid>/grant", ["POST"],
            ["ClearanceOfficer"])
def grant_license(rid, user_id, user_role):
    r = _get_request_or_404(rid)
    body = S.get_body()
    grant_fee_cents = S.req_int(body, "grant_fee_cents", min_v=0)
    if r["status"] != "APPROVED":
        raise S.err("ERR_INVALID_STATE", 409,
                    "Grant requires an APPROVED request")
    if grant_fee_cents != r["agreed_fee_cents"]:
        raise S.err("ERR_FEE_MISMATCH", 422,
                    "grant_fee_cents must equal agreed_fee_cents")
    asset = svc.get_asset(r["asset_id"])
    if asset["posture"] != "CLEAR":
        raise S.err("ERR_ASSET_POSTURE_BLOCKED", 409,
                    "Asset posture is not CLEAR")
    # one license max per request
    for lic in S.licenses.values():
        if lic["clearance_request_id"] == rid:
            raise S.err("ERR_LICENSE_ALREADY_EXISTS", 409,
                        "A license already exists for this request")
    # window overlap: same asset, ACTIVE, same media, overlapping territory,
    # intersecting half-open term
    s_new, e_new = r["use_start_at"], r["use_end_at"]
    for lic in svc.asset_licenses(r["asset_id"]):
        if lic["lifecycle"] != "ACTIVE":
            continue
        if lic["media"] != r["media"]:
            continue
        if not svc.territories_overlap(lic["territory"], r["territory"]):
            continue
        if lic["term_start_at"] < e_new and s_new < lic["term_end_at"]:
            raise S.err("ERR_LICENSE_WINDOW_OVERLAP", 422,
                        "Overlapping ACTIVE license window")
    lic = S.stamp_new({
        "clearance_request_id": rid,
        "asset_id": r["asset_id"],
        "territory": r["territory"],
        "media": r["media"],
        "term_start_at": r["use_start_at"],
        "term_end_at": r["use_end_at"],
        "unit_limit": r["requested_units"],
        "fee_agreed_cents": r["agreed_fee_cents"],
        "fee_status": "UNPAID",
        "lifecycle": "ACTIVE",
        "renewal_alert_id": None,
        "suspension_cause": None,
    })
    S.licenses[lic["id"]] = lic
    # schedule renewal alert
    from datetime import timedelta
    alert = S.stamp_new({
        "license_id": lic["id"],
        "fires_at": lic["term_end_at"] - timedelta(days=S.RENEWAL_ALERT_LEAD_DAYS),
        "status": "SCHEDULED",
    })
    S.renewal_alerts[alert["id"]] = alert
    lic["renewal_alert_id"] = alert["id"]
    r["status"] = "LICENSED"
    S.touch(r)
    svc.touch_asset(asset)
    # granting a WORLD/ACTIVE license may shift posture to ENCUMBERED
    svc.recompute_asset_posture(asset)
    return SZ.serialize_license(lic), 201
