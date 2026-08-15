from core import iso


def spine(r):
    return {
        "id": r["id"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def ser_cell(c):
    d = spine(c)
    d.update({
        "age_band": c["age_band"],
        "district": c["district"],
        "tenure_bucket": c["tenure_bucket"],
        "target_size": c["target_size"],
        "reserved_count": c["reserved_count"],
        "active_count": c["active_count"],
        "status": c["status"],
        "deficit": max(0, c["target_size"] - c["active_count"]),
    })
    return d


def ser_panelist(p):
    d = spine(p)
    d.update({
        "external_ref": p["external_ref"],
        "full_name": p["full_name"],
        "age_band": p["age_band"],
        "district": p["district"],
        "tenure_bucket": p["tenure_bucket"],
        "preferred_locale": p["preferred_locale"],
        "home_cell_id": p["home_cell_id"],
        "status": p["status"],
        "missed_streak": p["missed_streak"],
        "last_contacted_at": iso(p["last_contacted_at"]),
        "lapsed_at": iso(p["lapsed_at"]),
    })
    return d


def ser_instrument(i):
    d = spine(i)
    d.update({
        "title": i["title"],
        "question_count": i["question_count"],
        "required_locales": list(i["required_locales"]),
        "base_locale": i["base_locale"],
        "revision": i["revision"],
        "status": i["status"],
    })
    return d


def ser_translation(t):
    d = spine(t)
    d.update({
        "instrument_id": t["instrument_id"],
        "locale": t["locale"],
        "translator_ref": t["translator_ref"],
        "instrument_revision": t["instrument_revision"],
        "status": t["status"],
    })
    return d


def ser_wave(w):
    d = spine(w)
    d.update({
        "wave_code": w["wave_code"],
        "instrument_id": w["instrument_id"],
        "opens_at": iso(w["opens_at"]),
        "closes_at": iso(w["closes_at"]),
        "min_response_rate": w["min_response_rate"],
        "incentive_pool_total_cents": w["incentive_pool_total_cents"],
        "base_incentive_cents": w["base_incentive_cents"],
        "incentive_pool_available_cents": w["incentive_pool_available_cents"],
        "incentive_pool_reserved_cents": w["incentive_pool_reserved_cents"],
        "incentive_pool_paid_cents": w["incentive_pool_paid_cents"],
        "invited_count": w["invited_count"],
        "completed_count": w["completed_count"],
        "status": w["status"],
    })
    return d


def ser_invitation(i):
    d = spine(i)
    d.update({
        "wave_id": i["wave_id"],
        "panelist_id": i["panelist_id"],
        "sent_at": iso(i["sent_at"]),
        "reminder_count": i["reminder_count"],
        "last_reminder_at": iso(i["last_reminder_at"]),
        "status": i["status"],
    })
    return d


def ser_response(r):
    d = spine(r)
    d.update({
        "invitation_id": r["invitation_id"],
        "wave_id": r["wave_id"],
        "panelist_id": r["panelist_id"],
        "answers_payload": r["answers_payload"],
        "completeness_pct": r["completeness_pct"],
        "completion_seconds": r["completion_seconds"],
        "speeder_flag": r["speeder_flag"],
        "low_effort_flag": r["low_effort_flag"],
        "status": r["status"],
    })
    return d


def ser_award(a):
    d = spine(a)
    d.update({
        "response_id": a["response_id"],
        "wave_id": a["wave_id"],
        "amount_cents": a["amount_cents"],
        "eligibility_status": a["eligibility_status"],
        "payout_status": a["payout_status"],
    })
    return d


def ser_snapshot(s):
    d = spine(s)
    d.update({
        "wave_id": s["wave_id"],
        "method": s["method"],
        "weight_mass": s["weight_mass"],
        "accepted_count": s["accepted_count"],
        "design_effect": s["design_effect"],
        "weighted_cell_shares": dict(s["weighted_cell_shares"]),
        "status": s["status"],
        "finalized_by_user_id": s["finalized_by_user_id"],
    })
    return d


def ser_publication(p):
    d = spine(p)
    d.update({
        "wave_id": p["wave_id"],
        "weight_snapshot_id": p["weight_snapshot_id"],
        "title": p["title"],
        "k_threshold": p["k_threshold"],
        "breakdown_cells": [dict(b) for b in p["breakdown_cells"]],
        "status": p["status"],
    })
    return d


def ser_commitment(c):
    d = spine(c)
    d.update({
        "publication_id": c["publication_id"],
        "department_name": c["department_name"],
        "summary": c["summary"],
        "due_at": iso(c["due_at"]),
        "breached_at": iso(c["breached_at"]),
        "status": c["status"],
    })
    return d


def ser_hold(h):
    d = spine(h)
    d.update({
        "panelist_id": h["panelist_id"],
        "scope": h["scope"],
        "reason": h["reason"],
        "status": h["status"],
    })
    return d


def ser_run(r):
    d = spine(r)
    d.update({
        "run_label": r["run_label"],
        "attrition_grace_days": r["attrition_grace_days"],
        "planned_attrition_count": r["planned_attrition_count"],
        "applied_attrition_count": r["applied_attrition_count"],
        "applied_forfeit_count": r["applied_forfeit_count"],
        "status": r["status"],
    })
    return d
