"""Routes: licenses, usage reservations, usage events, license payments."""
from flask import request

import state as S
import services as svc
import serializers as SZ

LIC_READ_ROLES = ["AssetCurator", "ClearanceOfficer", "Negotiator",
                  "LegalCertifier", "FinancePayer", "IngestionAgent"]
RES_READ_ROLES = ["ClearanceOfficer", "IngestionAgent", "FinancePayer"]
EVT_READ_ROLES = ["ClearanceOfficer", "IngestionAgent", "FinancePayer",
                  "LegalCertifier"]
PAY_READ_ROLES = ["ClearanceOfficer", "FinancePayer", "LegalCertifier"]


def _get_license_or_404(lid):
    lic = svc.get_license(lid)
    if lic is None:
        raise S.err("ERR_NOT_FOUND", 404, "License not found")
    return lic


def _get_reservation_or_404(rid):
    r = svc.get_reservation(rid)
    if r is None:
        raise S.err("ERR_NOT_FOUND", 404, "UsageReservation not found")
    return r


# ---------------------------------------------------------------------------
# License reads (PRD 3.4/3.5)
# ---------------------------------------------------------------------------
@S.endpoint("/rights/licenses/<lid>", ["GET"], LIC_READ_ROLES)
def get_license(lid, user_id, user_role):
    lic = _get_license_or_404(lid)
    return SZ.serialize_license(lic), 200


@S.endpoint("/rights/licenses", ["GET"], LIC_READ_ROLES)
def list_licenses(user_id, user_role):
    limit, offset = S.pagination_params()
    asset_f = request.args.get("asset_id")
    cr_f = request.args.get("clearance_request_id")
    ra_f = request.args.get("renewal_alert_id")
    lc_f = request.args.get("lifecycle")
    fs_f = request.args.get("fee_status")
    items = sorted(S.licenses.values(), key=lambda l: (l["created_at"], l["_seq"]))
    if asset_f is not None:
        items = [l for l in items if l["asset_id"] == asset_f]
    if cr_f is not None:
        items = [l for l in items if l["clearance_request_id"] == cr_f]
    if ra_f is not None:
        items = [l for l in items if l.get("renewal_alert_id") == ra_f]
    if lc_f is not None:
        items = [l for l in items if l["lifecycle"] == lc_f]
    if fs_f is not None:
        items = [l for l in items if l["fee_status"] == fs_f]
    return S.paginate([SZ.serialize_license(l) for l in items], limit, offset)


# ---------------------------------------------------------------------------
# License revocation (PRD 3.7)
# ---------------------------------------------------------------------------
@S.endpoint("/rights/licenses/<lid>/revoke", ["POST"], ["LegalCertifier"])
def revoke_license(lid, user_id, user_role):
    lic = _get_license_or_404(lid)
    if lic["lifecycle"] not in ("ACTIVE", "SUSPENDED"):
        raise S.err("ERR_INVALID_STATE", 409,
                    "Cannot revoke from lifecycle %s" % lic["lifecycle"])
    # requires an UPHELD notice on the asset
    upheld = None
    for n in svc.asset_notices(lic["asset_id"]):
        if n["status"] == "UPHELD":
            if upheld is None or n["received_at"] < upheld["received_at"]:
                upheld = n
    if upheld is None:
        raise S.err("ERR_NO_UPHELD_TAKEDOWN", 409,
                    "Revoke requires an UPHELD takedown notice on the asset")
    # forfeit any HELD reservations
    for r in svc.license_reservations(lid):
        if r["status"] == "HELD":
            r["status"] = "FORFEITED"
            S.touch(r)
    # cancel SCHEDULED renewal alert
    for a in svc.license_alerts(lid):
        if a["status"] == "SCHEDULED":
            a["status"] = "CANCELLED"
            S.touch(a)
    # strike POSTED usage events with used_at >= notice.received_at
    for e in svc.license_events(lid):
        if e["posting_kind"] == "POSTED" and e["used_at"] >= upheld["received_at"]:
            e["posting_kind"] = "STRUCK"
    lic["lifecycle"] = "REVOKED"
    lic["suspension_cause"] = None
    S.touch(lic)
    return SZ.serialize_license(lic), 200


# ---------------------------------------------------------------------------
# Usage reservations (PRD 3.5)
# ---------------------------------------------------------------------------
@S.endpoint("/rights/licenses/<lid>/usage-reservations", ["POST"],
            ["IngestionAgent"])
def create_usage_reservation(lid, user_id, user_role):
    lic = _get_license_or_404(lid)
    body = S.get_body()
    units = S.req_int(body, "units", min_v=1)
    expected = S.req_int(body, "expected_license_version", min_v=0)
    # OCC (PRD 2.7)
    if expected != lic["version"]:
        raise S.err("ERR_STALE_VERSION", 412,
                    "expected_license_version does not match current version")
    if lic["lifecycle"] != "ACTIVE":
        raise S.err("ERR_LICENSE_NOT_ACTIVE", 409,
                    "License is not ACTIVE")
    available = svc.license_units_available(lic)
    if units > available:
        raise S.err("ERR_QUOTA_EXCEEDED", 409,
                    "Reservation units exceed units_available")
    from datetime import timedelta
    r = S.stamp_new({
        "license_id": lid,
        "units": units,
        "status": "HELD",
        "hold_expires_at": S.now_dt() + timedelta(hours=S.HOLD_TTL_HOURS),
    })
    S.usage_reservations[r["id"]] = r
    S.touch(lic)
    return SZ.serialize_usage_reservation(r), 201


@S.endpoint("/rights/licenses/<lid>/usage-reservations", ["GET"], RES_READ_ROLES)
def list_usage_reservations(lid, user_id, user_role):
    _get_license_or_404(lid)
    limit, offset = S.pagination_params()
    status_f = request.args.get("status")
    items = sorted(svc.license_reservations(lid),
                   key=lambda r: (r["created_at"], r["_seq"]))
    if status_f is not None:
        items = [r for r in items if r["status"] == status_f]
    return S.paginate([SZ.serialize_usage_reservation(r) for r in items],
                      limit, offset)


@S.endpoint("/rights/usage-reservations/<rid>", ["GET"], RES_READ_ROLES)
def get_usage_reservation(rid, user_id, user_role):
    r = _get_reservation_or_404(rid)
    return SZ.serialize_usage_reservation(r), 200


@S.endpoint("/rights/usage-reservations/<rid>/usage-events", ["GET"],
            RES_READ_ROLES)
def list_reservation_usage_events(rid, user_id, user_role):
    r = _get_reservation_or_404(rid)
    limit, offset = S.pagination_params()
    items = sorted(
        [e for e in S.usage_events.values() if e.get("reservation_id") == rid],
        key=lambda e: (e["created_at"], e["_seq"]),
    )
    return S.paginate([SZ.serialize_usage_event(e) for e in items],
                      limit, offset)


@S.endpoint("/rights/usage-reservations/<rid>/release", ["POST"],
            ["IngestionAgent"])
def release_usage_reservation(rid, user_id, user_role):
    r = _get_reservation_or_404(rid)
    if r["status"] != "HELD":
        raise S.err("ERR_INVALID_STATE", 409,
                    "Only a HELD reservation may be released")
    r["status"] = "RELEASED"
    S.touch(r)
    lic = svc.get_license(r["license_id"])
    if lic is not None:
        S.touch(lic)
    return SZ.serialize_usage_reservation(r), 200


# ---------------------------------------------------------------------------
# Usage events (PRD 3.5)
# ---------------------------------------------------------------------------
@S.endpoint("/rights/licenses/<lid>/usage-events", ["POST"], ["IngestionAgent"])
def post_usage_event(lid, user_id, user_role):
    lic = _get_license_or_404(lid)
    body = S.get_body()
    units = S.req_int(body, "units", min_v=1)
    used_at = S.req_dt(body, "used_at")
    reservation_id = body.get("reservation_id")
    if reservation_id is not None and not isinstance(reservation_id, str):
        raise S.err("ERR_INVALID_REQUEST", 400,
                    "reservation_id must be a string")
    if lic["lifecycle"] != "ACTIVE":
        raise S.err("ERR_LICENSE_NOT_ACTIVE", 409, "License is not ACTIVE")
    reservation = None
    if reservation_id is not None:
        reservation = svc.get_reservation(reservation_id)
        if reservation is None or reservation["license_id"] != lid:
            raise S.err("ERR_NOT_FOUND", 404, "UsageReservation not found")
        if reservation["status"] != "HELD":
            raise S.err("ERR_INVALID_STATE", 409,
                        "Reservation is not HELD")
        clock = S.now_dt()
        if clock >= reservation["hold_expires_at"]:
            raise S.err("ERR_HOLD_EXPIRED", 409,
                        "Reservation hold has expired")
        if units > reservation["units"]:
            raise S.err("ERR_USAGE_OVERDRAW", 409,
                        "Event units exceed reservation remaining units")
    # term check (applies to both reserved and direct-grant usage)
    if not (lic["term_start_at"] <= used_at < lic["term_end_at"]):
        raise S.err("ERR_USAGE_OUTSIDE_TERM", 422,
                    "used_at outside [term_start_at, term_end_at)")
    e = S.stamp_new_lean({
        "license_id": lid,
        "reservation_id": reservation_id,
        "units": units,
        "used_at": used_at,
        "posting_kind": "POSTED",
    })
    S.usage_events[e["id"]] = e
    if reservation is not None:
        if units < reservation["units"]:
            reservation["units"] = reservation["units"] - units
            S.touch(reservation)
        else:
            reservation["status"] = "CONSUMED"
            reservation["units"] = 0
            S.touch(reservation)
    S.touch(lic)
    return SZ.serialize_usage_event(e), 201


@S.endpoint("/rights/licenses/<lid>/usage-events", ["GET"], EVT_READ_ROLES)
def list_usage_events(lid, user_id, user_role):
    _get_license_or_404(lid)
    limit, offset = S.pagination_params()
    items = sorted(svc.license_events(lid),
                   key=lambda e: (e["created_at"], e["_seq"]))
    return S.paginate([SZ.serialize_usage_event(e) for e in items],
                      limit, offset)


# ---------------------------------------------------------------------------
# License payments (PRD 3.6)
# ---------------------------------------------------------------------------
@S.endpoint("/rights/licenses/<lid>/payments", ["POST"], ["FinancePayer"])
def post_license_payment(lid, user_id, user_role):
    lic = _get_license_or_404(lid)
    body = S.get_body()
    amount_cents = body.get("amount_cents")
    if not S.is_intlike(amount_cents) or int(amount_cents) == 0:
        raise S.err("ERR_INVALID_REQUEST", 400,
                    "amount_cents must be a non-zero integer")
    amount_cents = int(amount_cents)
    expected = S.req_int(body, "expected_license_version", min_v=0)
    # OCC (PRD 2.7)
    if expected != lic["version"]:
        raise S.err("ERR_STALE_VERSION", 412,
                    "expected_license_version does not match current version")
    # segregation of duties: payer != originating requester
    req = svc.get_request(lic["clearance_request_id"])
    if req is not None and req["requester_id"] == user_id:
        raise S.err("ERR_SEGREGATION_OF_DUTIES", 422,
                    "Requester may not pay the license")
    paid_so_far = svc.license_paid_total(lic)
    if amount_cents > 0:
        # payment path: license must be payable (lifecycle ACTIVE)
        if lic["lifecycle"] != "ACTIVE":
            raise S.err("ERR_LICENSE_NOT_PAYABLE", 422,
                        "Payments only accepted while lifecycle is ACTIVE")
        if paid_so_far + amount_cents > lic["fee_agreed_cents"]:
            raise S.err("ERR_OVERPAYMENT", 422,
                        "Payment would push cumulative paid above fee_agreed_cents")
    else:
        # refund path: terminal lifecycle + zero gross consumption
        if lic["lifecycle"] not in ("EXPIRED", "REVOKED"):
            raise S.err("ERR_REFUND_REQUIRES_TERMINAL", 422,
                        "Refund requires lifecycle EXPIRED or REVOKED")
        if svc.license_units_consumed_gross(lic) != 0:
            raise S.err("ERR_REFUND_AFTER_USE", 422,
                        "Refund blocked: units_consumed_gross > 0")
        # refund magnitude must exactly cancel cumulative paid to date
        if -amount_cents != paid_so_far:
            raise S.err("ERR_INVALID_REQUEST", 400,
                        "Refund amount must exactly cancel cumulative paid")
    p = S.stamp_new_lean({
        "license_id": lid,
        "amount_cents": amount_cents,
        "payer_id": user_id,
        "posted_at": S.now_dt(),
    })
    S.license_payments[p["id"]] = p
    svc.recompute_fee_status(lic)
    S.touch(lic)
    return SZ.serialize_license_payment(p), 201


@S.endpoint("/rights/licenses/<lid>/payments", ["GET"], PAY_READ_ROLES)
def list_license_payments(lid, user_id, user_role):
    _get_license_or_404(lid)
    limit, offset = S.pagination_params()
    items = sorted(svc.license_payments(lid),
                   key=lambda p: (p["created_at"], p["_seq"]))
    return S.paginate([SZ.serialize_license_payment(p) for p in items],
                      limit, offset)


# ---------------------------------------------------------------------------
# Renewal alerts (PRD 3.9)
# ---------------------------------------------------------------------------
@S.endpoint("/rights/licenses/<lid>/renewal-alerts", ["GET"],
            ["ClearanceOfficer", "FinancePayer", "AssetCurator"])
def list_license_renewal_alerts(lid, user_id, user_role):
    _get_license_or_404(lid)
    limit, offset = S.pagination_params()
    status_f = request.args.get("status")
    items = sorted(svc.license_alerts(lid),
                   key=lambda a: (a["created_at"], a["_seq"]))
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    return S.paginate([SZ.serialize_renewal_alert(a) for a in items],
                      limit, offset)


@S.endpoint("/rights/renewal-alerts", ["GET"],
            ["ClearanceOfficer", "AssetCurator"])
def list_all_renewal_alerts(user_id, user_role):
    limit, offset = S.pagination_params()
    status_f = request.args.get("status")
    items = sorted(S.renewal_alerts.values(),
                   key=lambda a: (a["created_at"], a["_seq"]))
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    return S.paginate([SZ.serialize_renewal_alert(a) for a in items],
                      limit, offset)
