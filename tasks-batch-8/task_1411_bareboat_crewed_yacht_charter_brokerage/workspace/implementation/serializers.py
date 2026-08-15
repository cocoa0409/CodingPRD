"""Serializers: record -> public JSON dict.

Common fields (PRD §2.4): id, created_at, updated_at, version. EscrowMovement
and CommissionStatement carry only id + created_at. Datetimes are stored as
aware UTC objects and rendered ISO 8601 with three fractional digits.
"""

from util import fmt_ts


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_ts(rec["created_at"]),
        "updated_at": fmt_ts(rec["updated_at"]),
        "version": rec["version"],
    }


def _slim(rec):
    return {"id": rec["id"], "created_at": fmt_ts(rec["created_at"])}


def ser_operator(o):
    d = _common(o)
    d.update({
        "name": o["name"],
        "home_port": o["home_port"],
        "status": o["status"],
    })
    return d


def ser_broker(b):
    d = _common(b)
    d.update({
        "display_name": b["display_name"],
        "broker_type": b["broker_type"],
        "license_no": b["license_no"],
    })
    return d


def ser_client(c):
    d = _common(c)
    d.update({
        "full_name": c["full_name"],
        "email": c["email"],
        "qualification_status": c["qualification_status"],
        "resume_class": c["resume_class"],
        "skippered_hours": c["skippered_hours"],
        "resume_submitted_at": fmt_ts(c["resume_submitted_at"]),
    })
    return d


def ser_yacht(y):
    d = _common(y)
    d.update({
        "operator_id": y["operator_id"],
        "listing_central_agent_id": y["listing_central_agent_id"],
        "name": y["name"],
        "charter_type": y["charter_type"],
        "home_port": y["home_port"],
        "capacity_berths": y["capacity_berths"],
        "weekly_base_rate_cents": y["weekly_base_rate_cents"],
        "min_charter_days": y["min_charter_days"],
        "required_resume_class": y["required_resume_class"],
        "security_deposit_cents": y["security_deposit_cents"],
        "pricing_mode": y["pricing_mode"],
        "status": y["status"],
    })
    return d


def ser_block(b):
    d = _common(b)
    d.update({
        "yacht_id": b["yacht_id"],
        "charter_agreement_id": b["charter_agreement_id"],
        "block_type": b["block_type"],
        "start_date": b["start_date"],
        "end_date": b["end_date"],
        "status": b["status"],
    })
    return d


def ser_request(r):
    d = _common(r)
    d.update({
        "client_id": r["client_id"],
        "yacht_id": r["yacht_id"],
        "retail_broker_id": r["retail_broker_id"],
        "rebooked_from_request_id": r["rebooked_from_request_id"],
        "start_date": r["start_date"],
        "end_date": r["end_date"],
        "guests_count": r["guests_count"],
        "quoted_charter_fee_cents": r["quoted_charter_fee_cents"],
        "apa_pct": r["apa_pct"],
        "gratuity_pledged_cents": r["gratuity_pledged_cents"],
        "retail_pct_bps": r["retail_pct_bps"],
        "round_count": r["round_count"],
        "offer_expires_at": fmt_ts(r["offer_expires_at"]),
        "status": r["status"],
    })
    return d


def ser_agreement(a):
    d = _common(a)
    d.update({
        "charter_request_id": a["charter_request_id"],
        "client_id": a["client_id"],
        "yacht_id": a["yacht_id"],
        "operator_id": a["operator_id"],
        "retail_broker_id": a["retail_broker_id"],
        "central_agent_id": a["central_agent_id"],
        "start_date": a["start_date"],
        "end_date": a["end_date"],
        "charter_fee_cents": a["charter_fee_cents"],
        "apa_pct": a["apa_pct"],
        "apa_amount_cents": a["apa_amount_cents"],
        "security_deposit_cents": a["security_deposit_cents"],
        "gratuity_pledged_cents": a["gratuity_pledged_cents"],
        "retail_pct_bps": a["retail_pct_bps"],
        "pricing_mode": a["pricing_mode"],
        "signing_due_cents": a["signing_due_cents"],
        "final_due_cents": a["final_due_cents"],
        "client_signed_at": fmt_ts(a["client_signed_at"]),
        "central_agent_signed_at": fmt_ts(a["central_agent_signed_at"]),
        "days_before_start": a["days_before_start"],
        "cancellation_penalty_cents": a["cancellation_penalty_cents"],
        "status": a["status"],
        "funds_status": a["funds_status"],
    })
    return d


def ser_escrow(e):
    d = _common(e)
    d.update({
        "charter_agreement_id": e["charter_agreement_id"],
        "held_charter_fee_cents": e["held_charter_fee_cents"],
        "held_apa_cents": e["held_apa_cents"],
        "held_deposit_cents": e["held_deposit_cents"],
        "held_gratuity_cents": e["held_gratuity_cents"],
        "total_funded_cents": e["total_funded_cents"],
        "total_released_cents": e["total_released_cents"],
        "status": e["status"],
    })
    return d


def ser_movement(m):
    d = _slim(m)
    d.update({
        "escrow_account_id": m["escrow_account_id"],
        "movement_type": m["movement_type"],
        "bucket": m["bucket"],
        "amount_cents": m["amount_cents"],
        "memo": m["memo"],
    })
    return d


def ser_expense(e):
    d = _common(e)
    d.update({
        "charter_agreement_id": e["charter_agreement_id"],
        "bucket": e["bucket"],
        "description": e["description"],
        "amount_cents": e["amount_cents"],
        "status": e["status"],
    })
    return d


def ser_leg(l):
    d = _common(l)
    d.update({
        "charter_agreement_id": l["charter_agreement_id"],
        "seq_no": l["seq_no"],
        "port_name": l["port_name"],
        "arrival_date": l["arrival_date"],
        "departure_date": l["departure_date"],
        "status": l["status"],
    })
    return d


def ser_permit(p):
    d = _common(p)
    d.update({
        "itinerary_leg_id": p["itinerary_leg_id"],
        "port_authority_ref": p["port_authority_ref"],
        "valid_from": p["valid_from"],
        "valid_until": p["valid_until"],
        "status": p["status"],
    })
    return d


def ser_certificate(c):
    d = _common(c)
    d.update({
        "charter_agreement_id": c["charter_agreement_id"],
        "insurer_name": c["insurer_name"],
        "policy_no": c["policy_no"],
        "coverage_amount_cents": c["coverage_amount_cents"],
        "valid_from": c["valid_from"],
        "valid_until": c["valid_until"],
        "status": c["status"],
    })
    return d


def ser_statement(s):
    d = _slim(s)
    d.update({
        "charter_agreement_id": s["charter_agreement_id"],
        "basis": s["basis"],
        "basis_amount_cents": s["basis_amount_cents"],
        "commission_total_cents": s["commission_total_cents"],
        "retail_share_cents": s["retail_share_cents"],
        "central_share_cents": s["central_share_cents"],
    })
    return d
