"""Entity -> JSON projections.  Every row carries id/created_at/updated_at/version."""
from store import common_out, iso, iso_date, numout


def company_out(c):
    out = {
        "id": c["id"],
        "ticker": c["ticker"],
        "legal_name": c["legal_name"],
        "shares_outstanding": c["shares_outstanding"],
        "blackout_window_start": iso(c["blackout_window_start"]),
        "blackout_window_end": iso(c["blackout_window_end"]),
        "dividend_reserve_cents": c["dividend_reserve_cents"],
        "dividend_paid_cents": c["dividend_paid_cents"],
        "disclosure_posture": c["disclosure_posture"],
        "open_inquiry_count": c["open_inquiry_count"],
        "posture_recomputed_at": iso(c["posture_recomputed_at"]),
    }
    out.update(common_out(c))
    return out


def contact_out(c):
    out = {
        "id": c["id"],
        "company_id": c["company_id"],
        "contact_type": c["contact_type"],
        "display_name": c["display_name"],
        "email": c["email"],
        "shares_held": c["shares_held"],
        "ownership_pct": numout(c["ownership_pct"]),
        "target_tier": c["target_tier"],
        "nda_on_file": c["nda_on_file"],
        "model_access_status": c["model_access_status"],
        "coverage_status": c["coverage_status"],
        "activist_flag": c["activist_flag"],
        "threat_level": c["threat_level"],
        "dividend_received_cents": c["dividend_received_cents"],
    }
    out.update(common_out(c))
    return out


def disclosure_out(d):
    out = {
        "id": d["id"],
        "company_id": d["company_id"],
        "disclosure_type": d["disclosure_type"],
        "fact_key": d["fact_key"],
        "metric": d["metric"],
        "period_label": d["period_label"],
        "guidance_low": numout(d["guidance_low"]),
        "guidance_high": numout(d["guidance_high"]),
        "status": d["status"],
        "published_at": iso(d["published_at"]),
        "is_guidance": d["is_guidance"],
        "withdrawal_reason": d["withdrawal_reason"],
    }
    out.update(common_out(d))
    return out


def inquiry_out(i):
    out = {
        "id": i["id"],
        "company_id": i["company_id"],
        "contact_id": i["contact_id"],
        "linked_prior_inquiry_id": i["linked_prior_inquiry_id"],
        "topic_category": i["topic_category"],
        "subject": i["subject"],
        "requests_nonpublic_detail": i["requests_nonpublic_detail"],
        "sensitivity_score": i["sensitivity_score"],
        "routing_queue": i["routing_queue"],
        "sla_due_at": iso(i["sla_due_at"]),
        "status": i["status"],
        "answered_at": iso(i["answered_at"]),
    }
    out.update(common_out(i))
    return out


def draft_out(d):
    out = {
        "id": d["id"],
        "inquiry_id": d["inquiry_id"],
        "cited_disclosure_id": d["cited_disclosure_id"],
        "author_user_id": d["author_user_id"],
        "reviewer_user_id": d["reviewer_user_id"],
        "body_text": d["body_text"],
        "disclosure_class": d["disclosure_class"],
        "status": d["status"],
        "revision_round": d["revision_round"],
        "reviewer_note": d["reviewer_note"],
        "pinned_disclosure_version": d["pinned_disclosure_version"],
        "blocked_reason": d["blocked_reason"],
    }
    out.update(common_out(d))
    return out


def estimate_out(e):
    out = {
        "id": e["id"],
        "contact_id": e["contact_id"],
        "metric": e["metric"],
        "period_label": e["period_label"],
        "value": numout(e["value"]),
        "submitted_at": iso(e["submitted_at"]),
        "status": e["status"],
    }
    out.update(common_out(e))
    return out


def event_out(e):
    out = {
        "id": e["id"],
        "company_id": e["company_id"],
        "event_type": e["event_type"],
        "venue_city": e["venue_city"],
        "window_start": iso(e["window_start"]),
        "window_end": iso(e["window_end"]),
        "slot_minutes": e["slot_minutes"],
        "capacity_slots": e["capacity_slots"],
        "allocated_count": e["allocated_count"],
        "waitlisted_count": e["waitlisted_count"],
        "released_count": e["released_count"],
        "declined_count": e["declined_count"],
        "request_ledger_total": e["request_ledger_total"],
        "status": e["status"],
    }
    out.update(common_out(e))
    return out


def meeting_request_out(m):
    out = {
        "id": m["id"],
        "event_id": m["event_id"],
        "contact_id": m["contact_id"],
        "requested_slot_start": iso(m["requested_slot_start"]),
        "requested_slot_end": iso(m["requested_slot_end"]),
        "provisional_priority_score": numout(m["provisional_priority_score"]),
        "final_priority_score": numout(m["final_priority_score"]),
        "status": m["status"],
        "allocated_at": iso(m["allocated_at"]),
        "release_reason": m["release_reason"],
        "promoted_from_waitlist": m["promoted_from_waitlist"],
    }
    out.update(common_out(m))
    return out


def instruction_out(t):
    ledger = t["payout_ledger"]
    if ledger is not None:
        ledger = [
            {
                "contact_id": row["contact_id"],
                "shares_held": row["shares_held"],
                "amount_cents": row["amount_cents"],
            }
            for row in ledger
        ]
    out = {
        "id": t["id"],
        "company_id": t["company_id"],
        "instruction_type": t["instruction_type"],
        "record_date": iso_date(t["record_date"]),
        "payable_date": iso_date(t["payable_date"]),
        "declared_rate_cents_per_share": numout(t["declared_rate_cents_per_share"]),
        "funding_mode": t["funding_mode"],
        "notes": t["notes"],
        "submitted_by_user_id": t["submitted_by_user_id"],
        "acknowledged_by_user_id": t["acknowledged_by_user_id"],
        "executed_by_user_id": t["executed_by_user_id"],
        "snapshot_holder_count": t["snapshot_holder_count"],
        "snapshot_shares_total": t["snapshot_shares_total"],
        "payout_ledger": ledger,
        "total_payout_cents": t["total_payout_cents"],
        "executed_at": iso(t["executed_at"]),
        "status": t["status"],
        "decision_reason": t["decision_reason"],
    }
    out.update(common_out(t))
    return out
