"""Entity serializers: public field whitelists.  Derived numeric fields are
projected fresh from the store at read time so reads are always consistent;
mutation paths maintain the stored values (and version bumps) themselves.
"""

import domain
import store


def season_view(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "base_dues_cents": s["base_dues_cents"],
        "early_bird_pct": s["early_bird_pct"],
        "early_bird_cutoff": s["early_bird_cutoff"],
        "dues_due_date": s["dues_due_date"],
        "late_fee_weekly_cents": s["late_fee_weekly_cents"],
        "late_fee_cap_cents": s["late_fee_cap_cents"],
        "scholarship_pool_cents": s["scholarship_pool_cents"],
        "audition_slot_minutes": s["audition_slot_minutes"],
        "attendance_threshold": s["attendance_threshold"],
        "posture": s["posture"],
        "ops_week_index": s["ops_week_index"],
        "pool_available_cents": s["pool_available_cents"],
        "pool_reserved_cents": s["pool_reserved_cents"],
        "pool_spent_cents": s["pool_spent_cents"],
        "treasury_balance_cents": s["treasury_balance_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def section_view(s):
    active = sum(
        1 for m in store.members.values()
        if m["section_id"] == s["id"] and m["status"] in domain.SECTION_COUNT_STATUSES
    )
    return {
        "id": s["id"],
        "season_id": s["season_id"],
        "voice_part": s["voice_part"],
        "target_min": s["target_min"],
        "target_max": s["target_max"],
        "status": s["status"],
        "active_count": active,
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def member_view(m):
    dues = domain.member_dues_balance(m["id"])
    return {
        "id": m["id"],
        "season_id": m["season_id"],
        "full_name": m["full_name"],
        "email": m["email"],
        "section_id": m["section_id"],
        "status": m["status"],
        "enrolled_at": m["enrolled_at"],
        "attendance_rate": domain.compute_attendance_rate(m),
        "performance_eligible": domain.compute_performance_eligible(m, dues_balance=dues),
        "dues_balance_cents": dues,
        "ledger_balance_cents": m["ledger_balance_cents"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def audition_view(a):
    return {
        "id": a["id"],
        "member_id": a["member_id"],
        "scheduled_at": a["scheduled_at"],
        "status": a["status"],
        "tone_score": a["tone_score"],
        "pitch_score": a["pitch_score"],
        "sight_score": a["sight_score"],
        "composite_score": a["composite_score"],
        "decision": a["decision"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def invoice_view(i):
    return {
        "id": i["id"],
        "member_id": i["member_id"],
        "season_id": i["season_id"],
        "issued_at": i["issued_at"],
        "provisional_amount_cents": i["provisional_amount_cents"],
        "final_amount_cents": i["final_amount_cents"],
        "scholarship_applied_cents": i["scholarship_applied_cents"],
        "paid_cents": i["paid_cents"],
        "late_fee_cents": i["late_fee_cents"],
        "balance_cents": domain.invoice_balance(i),
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def payment_view(p):
    return {
        "id": p["id"],
        "member_id": p["member_id"],
        "amount_cents": p["amount_cents"],
        "method": p["method"],
        "allocations": p["allocations"],
        "status": p["status"],
        "received_at": p["received_at"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def grant_view(g):
    return {
        "id": g["id"],
        "member_id": g["member_id"],
        "season_id": g["season_id"],
        "requested_cents": g["requested_cents"],
        "need_note": g["need_note"],
        "status": g["status"],
        "approved_cents": g["approved_cents"],
        "invoice_id": g["invoice_id"],
        "decided_by_user_id": g["decided_by_user_id"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def rehearsal_view(r):
    return {
        "id": r["id"],
        "season_id": r["season_id"],
        "scheduled_at": r["scheduled_at"],
        "location": r["location"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def attendance_record_view(a):
    return {
        "id": a["id"],
        "rehearsal_id": a["rehearsal_id"],
        "member_id": a["member_id"],
        "status": a["status"],
        "excused_by_user_id": a["excused_by_user_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def score_view(s):
    open_n = sum(
        1 for c in store.score_checkouts.values()
        if c["score_id"] == s["id"] and c["status"] in ("CHECKED_OUT", "OVERDUE")
    )
    return {
        "id": s["id"],
        "title": s["title"],
        "composer": s["composer"],
        "copy_count": s["copy_count"],
        "copies_available": s["copy_count"] - open_n - s["copies_lost"],
        "copies_lost": s["copies_lost"],
        "replacement_cost_cents": s["replacement_cost_cents"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def checkout_view(c):
    return {
        "id": c["id"],
        "score_id": c["score_id"],
        "member_id": c["member_id"],
        "checked_out_at": c["checked_out_at"],
        "due_date": c["due_date"],
        "returned_at": c["returned_at"],
        "status": c["status"],
        "fine_cents": c["fine_cents"],
        "charge_cents": c["charge_cents"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def venue_view(v):
    return {
        "id": v["id"],
        "name": v["name"],
        "capacity": v["capacity"],
        "status": v["status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def concert_view(c):
    duration = sum(
        p["duration_seconds"] for p in store.program_pieces.values()
        if p["concert_id"] == c["id"] and p["status"] == "CONFIRMED"
    )
    return {
        "id": c["id"],
        "season_id": c["season_id"],
        "title": c["title"],
        "expected_attendance": c["expected_attendance"],
        "status": c["status"],
        "program_duration_seconds": duration,
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def booking_view(b):
    return {
        "id": b["id"],
        "concert_id": b["concert_id"],
        "venue_id": b["venue_id"],
        "start_at": b["start_at"],
        "end_at": b["end_at"],
        "deposit_cents": b["deposit_cents"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def piece_view(p):
    return {
        "id": p["id"],
        "concert_id": p["concert_id"],
        "title": p["title"],
        "duration_seconds": p["duration_seconds"],
        "sequence_no": p["sequence_no"],
        "featured_member_ids": p["featured_member_ids"],
        "guest_contract_id": p["guest_contract_id"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def contract_view(c):
    return {
        "id": c["id"],
        "season_id": c["season_id"],
        "concert_id": c["concert_id"],
        "musician_name": c["musician_name"],
        "service_lines": c["service_lines"],
        "travel_stipend_cents": c["travel_stipend_cents"],
        "quoted_fee_cents": c["quoted_fee_cents"],
        "cancellation_fee_cents": c["cancellation_fee_cents"],
        "counter_count": c["counter_count"],
        "status": c["status"],
        "approved_by_user_id": c["approved_by_user_id"],
        "paid_by_user_id": c["paid_by_user_id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def tour_view(t):
    confirmed = sum(
        1 for r in store.tour_registrations.values()
        if r["tour_id"] == t["id"] and r["status"] == "CONFIRMED"
    )
    return {
        "id": t["id"],
        "season_id": t["season_id"],
        "name": t["name"],
        "destination": t["destination"],
        "departure_at": t["departure_at"],
        "return_at": t["return_at"],
        "seat_count": t["seat_count"],
        "min_seats": t["min_seats"],
        "transport_lodging_cost_cents": t["transport_lodging_cost_cents"],
        "provisional_share_cents": t["provisional_share_cents"],
        "final_share_cents": t["final_share_cents"],
        "confirmed_count": confirmed,
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def registration_view(r):
    return {
        "id": r["id"],
        "tour_id": r["tour_id"],
        "member_id": r["member_id"],
        "status": r["status"],
        "deposit_paid_cents": r["deposit_paid_cents"],
        "share_charge_cents": r["share_charge_cents"],
        "refund_cents": r["refund_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def committee_view(c):
    raised = sum(
        p["amount_cents"] for p in store.pledges.values()
        if p["committee_id"] == c["id"] and p["status"] == "FULFILLED"
    )
    return {
        "id": c["id"],
        "season_id": c["season_id"],
        "name": c["name"],
        "chair_member_id": c["chair_member_id"],
        "fundraising_goal_cents": c["fundraising_goal_cents"],
        "raised_cents": raised,
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def pledge_view(p):
    return {
        "id": p["id"],
        "committee_id": p["committee_id"],
        "donor_name": p["donor_name"],
        "amount_cents": p["amount_cents"],
        "status": p["status"],
        "recognition_tier": p["recognition_tier"],
        "recorded_by_user_id": p["recorded_by_user_id"],
        "fulfilled_by_user_id": p["fulfilled_by_user_id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }
