"""Entity serializers: internal records -> wire format (ISO timestamps, floats)."""
from common import DB, athlete_count, dec_out, iso


def ser_meet(m):
    return {
        "id": m["id"],
        "meet_name": m["meet_name"],
        "sanction_year": m["sanction_year"],
        "sanction_number": m["sanction_number"],
        "venue_name": m["venue_name"],
        "start_date": iso(m["start_date"]),
        "end_date": iso(m["end_date"]),
        "posture": m["posture"],
        "tiebreak_policy": m["tiebreak_policy"],
        "qualifying_score_rule": m["qualifying_score_rule"],
        "inquiry_window_minutes": m["inquiry_window_minutes"],
        "max_athletes_per_squad": m["max_athletes_per_squad"],
        "created_at": iso(m["created_at"]),
        "updated_at": iso(m["updated_at"]),
        "version": m["version"],
    }


def ser_session(s):
    return {
        "id": s["id"],
        "meet_id": s["meet_id"],
        "session_label": s["session_label"],
        "level_band": s["level_band"],
        "scheduled_start": iso(s["scheduled_start"]),
        "scheduled_end": iso(s["scheduled_end"]),
        "warmup_open_offset_minutes": s["warmup_open_offset_minutes"],
        "march_in_offset_minutes": s["march_in_offset_minutes"],
        "apparatus_set": s["apparatus_set"],
        "state": s["state"],
        "closed_at": iso(s["closed_at"]),
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def ser_squad(s):
    return {
        "id": s["id"],
        "session_id": s["session_id"],
        "squad_label": s["squad_label"],
        "starting_apparatus": s["starting_apparatus"],
        "rotation_index": s["rotation_index"],
        "athlete_count": athlete_count(s["id"]),
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def ser_gymnast(g):
    return {
        "id": g["id"],
        "usag_member_number": g["usag_member_number"],
        "legal_name": g["legal_name"],
        "date_of_birth": iso(g["date_of_birth"]),
        "competitive_level": g["competitive_level"],
        "home_gym": g["home_gym"],
        "created_at": iso(g["created_at"]),
        "updated_at": iso(g["updated_at"]),
        "version": g["version"],
    }


def ser_entry(e):
    return {
        "id": e["id"],
        "session_id": e["session_id"],
        "gymnast_id": e["gymnast_id"],
        "squad_id": e["squad_id"],
        "entry_status": e["entry_status"],
        "scratch_reason": e["scratch_reason"],
        "all_around_total": dec_out(e["all_around_total"]),
        "all_around_rank": e["all_around_rank"],
        "qualified_for_next_meet": e["qualified_for_next_meet"],
        "qualification_mobility_score": dec_out(e["qualification_mobility_score"]),
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


def ser_coach(c):
    return {
        "id": c["id"],
        "usag_coach_number": c["usag_coach_number"],
        "legal_name": c["legal_name"],
        "affiliated_gym": c["affiliated_gym"],
        "background_check_expiry": iso(c["background_check_expiry"]),
        "safety_cert_expiry": iso(c["safety_cert_expiry"]),
        "credential_state": c["credential_state"],
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def ser_pass(p):
    return {
        "id": p["id"],
        "meet_id": p["meet_id"],
        "coach_id": p["coach_id"],
        "pass_state": p["pass_state"],
        "issued_at": iso(p["issued_at"]),
        "floor_access_granted_at": iso(p["floor_access_granted_at"]),
        "suspension_reason": p["suspension_reason"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def ser_judge(j):
    return {
        "id": j["id"],
        "usag_judge_number": j["usag_judge_number"],
        "legal_name": j["legal_name"],
        "rating": j["rating"],
        "affiliated_gym": j["affiliated_gym"],
        "availability_start": iso(j["availability_start"]),
        "availability_end": iso(j["availability_end"]),
        "created_at": iso(j["created_at"]),
        "updated_at": iso(j["updated_at"]),
        "version": j["version"],
    }


def ser_panel(p):
    return {
        "id": p["id"],
        "meet_id": p["meet_id"],
        "session_id": p["session_id"],
        "apparatus": p["apparatus"],
        "panel_state": p["panel_state"],
        "required_judge_count": p["required_judge_count"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"],
        "judge_panel_id": a["judge_panel_id"],
        "judge_id": a["judge_id"],
        "role": a["role"],
        "assignment_state": a["assignment_state"],
        "conflict_flag": a["conflict_flag"],
        "created_at": iso(a["created_at"]),
        "updated_at": iso(a["updated_at"]),
        "version": a["version"],
    }


def ser_rotation(r):
    return {
        "id": r["id"],
        "session_id": r["session_id"],
        "rotation_number": r["rotation_number"],
        "apparatus": r["apparatus"],
        "scheduled_start": iso(r["scheduled_start"]),
        "scheduled_end": iso(r["scheduled_end"]),
        "actual_start": iso(r["actual_start"]),
        "actual_end": iso(r["actual_end"]),
        "state": r["state"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def ser_block(b):
    return {
        "id": b["id"],
        "rotation_id": b["rotation_id"],
        "squad_id": b["squad_id"],
        "apparatus": b["apparatus"],
        "block_start": iso(b["block_start"]),
        "block_end": iso(b["block_end"]),
        "state": b["state"],
        "created_at": iso(b["created_at"]),
        "updated_at": iso(b["updated_at"]),
        "version": b["version"],
    }


def ser_score(s):
    return {
        "id": s["id"],
        "athlete_entry_id": s["athlete_entry_id"],
        "rotation_id": s["rotation_id"],
        "apparatus": s["apparatus"],
        "difficulty_score": dec_out(s["difficulty_score"]),
        "execution_score": dec_out(s["execution_score"]),
        "neutral_deduction": dec_out(s["neutral_deduction"]),
        "provisional_total": dec_out(s["provisional_total"]),
        "final_total": dec_out(s["final_total"]),
        "score_state": s["score_state"],
        "published_at": iso(s["published_at"]),
        "finalized_at": iso(s["finalized_at"]),
        "is_tied": s["is_tied"],
        "tiebreak_rank": s["tiebreak_rank"],
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def ser_inquiry(i):
    return {
        "id": i["id"],
        "score_id": i["score_id"],
        "filed_by_coach_id": i["filed_by_coach_id"],
        "filed_at": iso(i["filed_at"]),
        "inquiry_state": i["inquiry_state"],
        "resolution": i["resolution"],
        "d_score_delta": dec_out(i["d_score_delta"]),
        "e_score_delta": dec_out(i["e_score_delta"]),
        "deduction_delta": dec_out(i["deduction_delta"]),
        "resolved_at": iso(i["resolved_at"]),
        "resolution_reason": i["resolution_reason"],
        "created_at": iso(i["created_at"]),
        "updated_at": iso(i["updated_at"]),
        "version": i["version"],
    }


def ser_award(a):
    return {
        "id": a["id"],
        "session_id": a["session_id"],
        "category": a["category"],
        "place": a["place"],
        "athlete_entry_id": a["athlete_entry_id"],
        "awarded_at": iso(a["awarded_at"]),
        "ceremony_order": a["ceremony_order"],
        "was_tiebroken": a["was_tiebroken"],
        "created_at": iso(a["created_at"]),
        "updated_at": iso(a["updated_at"]),
        "version": a["version"],
    }


def ser_ticket(t):
    return {
        "id": t["id"],
        "meet_id": t["meet_id"],
        "session_id": t["session_id"],
        "holder_name": t["holder_name"],
        "holder_email": t["holder_email"],
        "ticket_class": t["ticket_class"],
        "seat_section": t["seat_section"],
        "price_cents": t["price_cents"],
        "ticket_state": t["ticket_state"],
        "scanned_at": iso(t["scanned_at"]),
        "redeemed_at": iso(t["redeemed_at"]),
        "created_at": iso(t["created_at"]),
        "updated_at": iso(t["updated_at"]),
        "version": t["version"],
    }


def ser_qual_record(r):
    return {
        "id": r["id"],
        "athlete_entry_id": r["athlete_entry_id"],
        "target_meet_level": r["target_meet_level"],
        "qualifying_score_used": dec_out(r["qualifying_score_used"]),
        "threshold_applied": dec_out(r["threshold_applied"]),
        "qualification_state": r["qualification_state"],
        "confirmed_at": iso(r["confirmed_at"]),
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }
