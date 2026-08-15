"""Serializers: convert internal entities to wire format (PRD 2.4).

Mutable resources carry created_at/updated_at/version; append-only ledger
rows (diligence logs, rounds, usage events, payments) carry only id +
created_at.
"""
import state as S
import services as svc


def _ts(dt):
    return S.ts3(dt) if dt is not None else None


def serialize_rights_holder(h):
    return {
        "id": h["id"],
        "legal_name": h["legal_name"],
        "holder_kind": h["holder_kind"],
        "mfn_floor_cents": h["mfn_floor_cents"],
        "contact_verified": h["contact_verified"],
        "created_at": _ts(h["created_at"]),
        "updated_at": _ts(h["updated_at"]),
        "version": h["version"],
    }


def serialize_asset(a):
    return {
        "id": a["id"],
        "title": a["title"],
        "work_kind": a["work_kind"],
        "permitted_media": list(a["permitted_media"]),
        "embargo_until": _ts(a.get("embargo_until")),
        "rights_holder_id": a.get("rights_holder_id"),
        "orphan_status": a["orphan_status"],
        "posture": a["posture"],
        "retired_at": _ts(a.get("retired_at")),
        "created_at": _ts(a["created_at"]),
        "updated_at": _ts(a["updated_at"]),
        "version": a["version"],
    }


def serialize_diligence_log(d):
    return {
        "id": d["id"],
        "asset_id": d["asset_id"],
        "search_channel": d["search_channel"],
        "outcome": d["outcome"],
        "notes": d["notes"],
        "created_at": _ts(d["created_at"]),
    }


def serialize_clearance_request(r):
    return {
        "id": r["id"],
        "asset_id": r["asset_id"],
        "requester_id": r["requester_id"],
        "media": r["media"],
        "territory": r["territory"],
        "use_start_at": _ts(r["use_start_at"]),
        "use_end_at": _ts(r["use_end_at"]),
        "requested_units": r["requested_units"],
        "status": r["status"],
        "negotiation_round": r["negotiation_round"],
        "agreed_fee_cents": r.get("agreed_fee_cents"),
        "fair_use_assessment_id": r.get("fair_use_assessment_id"),
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_negotiation_round(r):
    return {
        "id": r["id"],
        "clearance_request_id": r["clearance_request_id"],
        "round_index": r["round_index"],
        "offered_fee_cents": r["offered_fee_cents"],
        "offered_by_role": r["offered_by_role"],
        "outcome": r["outcome"],
        "created_at": _ts(r["created_at"]),
    }


def serialize_license(lic):
    return {
        "id": lic["id"],
        "clearance_request_id": lic["clearance_request_id"],
        "asset_id": lic["asset_id"],
        "territory": lic["territory"],
        "media": lic["media"],
        "term_start_at": _ts(lic["term_start_at"]),
        "term_end_at": _ts(lic["term_end_at"]),
        "unit_limit": lic["unit_limit"],
        "fee_agreed_cents": lic["fee_agreed_cents"],
        "fee_status": lic["fee_status"],
        "lifecycle": lic["lifecycle"],
        "units_reserved": svc.license_units_reserved(lic),
        "units_consumed_net": svc.license_units_consumed_net(lic),
        "units_consumed_gross": svc.license_units_consumed_gross(lic),
        "renewal_alert_id": lic.get("renewal_alert_id"),
        "suspension_cause": lic.get("suspension_cause"),
        "created_at": _ts(lic["created_at"]),
        "updated_at": _ts(lic["updated_at"]),
        "version": lic["version"],
    }


def serialize_usage_reservation(r):
    return {
        "id": r["id"],
        "license_id": r["license_id"],
        "units": r["units"],
        "status": r["status"],
        "hold_expires_at": _ts(r["hold_expires_at"]),
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_usage_event(e):
    return {
        "id": e["id"],
        "license_id": e["license_id"],
        "reservation_id": e.get("reservation_id"),
        "units": e["units"],
        "used_at": _ts(e["used_at"]),
        "posting_kind": e["posting_kind"],
        "created_at": _ts(e["created_at"]),
    }


def serialize_license_payment(p):
    return {
        "id": p["id"],
        "license_id": p["license_id"],
        "amount_cents": p["amount_cents"],
        "payer_id": p["payer_id"],
        "posted_at": _ts(p["posted_at"]),
        "created_at": _ts(p["created_at"]),
    }


def serialize_fair_use_assessment(a):
    return {
        "id": a["id"],
        "asset_id": a["asset_id"],
        "clearance_request_id": a["clearance_request_id"],
        "factor_scores": dict(a["factor_scores"]),
        "composite_score": a["composite_score"],
        "certified": a["certified"],
        "status": a["status"],
        "created_at": _ts(a["created_at"]),
        "updated_at": _ts(a["updated_at"]),
        "version": a["version"],
    }


def serialize_takedown_notice(n):
    return {
        "id": n["id"],
        "asset_id": n["asset_id"],
        "claimant_name": n["claimant_name"],
        "received_at": _ts(n["received_at"]),
        "counter_notice_due_at": _ts(n["counter_notice_due_at"]),
        "status": n["status"],
        "created_at": _ts(n["created_at"]),
        "updated_at": _ts(n["updated_at"]),
        "version": n["version"],
    }


def serialize_renewal_alert(a):
    return {
        "id": a["id"],
        "license_id": a["license_id"],
        "fires_at": _ts(a["fires_at"]),
        "status": a["status"],
        "created_at": _ts(a["created_at"]),
        "updated_at": _ts(a["updated_at"]),
        "version": a["version"],
    }
