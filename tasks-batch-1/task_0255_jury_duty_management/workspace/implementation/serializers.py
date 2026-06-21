"""Entity -> response-dict serializers.

Each entity is stored as a plain dict with all of its persisted fields. The
serializers project the fields that belong in the API response (in particular,
they recompute the `computed` counters so reads always reflect current state, per
PRD §2.5). Append-only rows expose only id + created_at + their own fields.
"""
import db


# ---------------------------------------------------------------------------
# Computed counter recomputation helpers (PRD §2.5 — always derived from rows).
# ---------------------------------------------------------------------------

def _term_pool_size(term_id):
    return sum(
        1
        for j in db.jurors.values()
        if j["service_term_id"] == term_id
        and j["qualification_status"] == "QUALIFIED"
        and j["disqualified"] is False
    )


def _term_summoned_count(term_id):
    # Count of Summons in this term not in a terminal cancelled state.
    # There is no "cancelled" status in the machine; DEFERRED is the only state
    # that retires a summons from active obligation by re-issuing it elsewhere,
    # but it is not "cancelled" — so every summons issued under the term counts.
    return sum(1 for s in db.summonses.values() if s["service_term_id"] == term_id)


def _juror_fta_strike_count(juror_id):
    return sum(1 for st in db.strikes.values() if st["juror_id"] == juror_id and st["source"] == "FTA")


def _summons_deferral_count(summons):
    return summons.get("deferral_count", 0)


def _summons_service_days(summons_id):
    return sum(1 for c in db.check_ins.values() if c["summons_id"] == summons_id)


def _panel_seated_count(panel_id):
    return sum(
        1
        for a in db.panel_assignments.values()
        if a["panel_id"] == panel_id and a["status"] == "SEATED"
    )


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def service_term(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "name": t["name"],
        "report_date": t["report_date"],
        "daily_pay_cents": t["daily_pay_cents"],
        "half_day_pay_cents": t["half_day_pay_cents"],
        "full_day_hours": t["full_day_hours"],
        "mileage_rate_cents": t["mileage_rate_cents"],
        "pay_day_cap": t["pay_day_cap"],
        "fta_disqualify_threshold": t["fta_disqualify_threshold"],
        "pool_size": _term_pool_size(t["id"]),
        "summoned_count": _term_summoned_count(t["id"]),
        "status": t["status"],
        "draw_seq": t["draw_seq"],
    }


def juror(j):
    return {
        "id": j["id"],
        "created_at": j["created_at"],
        "updated_at": j["updated_at"],
        "version": j["version"],
        "service_term_id": j["service_term_id"],
        "full_name": j["full_name"],
        "birth_year": j["birth_year"],
        "round_trip_miles": j["round_trip_miles"],
        "qualification_status": j["qualification_status"],
        "fta_strike_count": _juror_fta_strike_count(j["id"]),
        "disqualified": j["disqualified"],
        "last_drawn_seq": j["last_drawn_seq"],
    }


def summons(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "service_term_id": s["service_term_id"],
        "juror_id": s["juror_id"],
        "badge_number": s["badge_number"],
        "status": s["status"],
        "deferred_to_term_id": s["deferred_to_term_id"],
        "deferral_count": s["deferral_count"],
        "service_days": _summons_service_days(s["id"]),
    }


def qualification_response(q):
    return {
        "id": q["id"],
        "created_at": q["created_at"],
        "summons_id": q["summons_id"],
        "is_citizen": q["is_citizen"],
        "is_resident": q["is_resident"],
        "felony_conviction": q["felony_conviction"],
        "english_proficient": q["english_proficient"],
        "evaluated_status": q["evaluated_status"],
    }


def disposition(d):
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "summons_id": d["summons_id"],
        "kind": d["kind"],
        "reason_code": d["reason_code"],
        "requested_term_id": d["requested_term_id"],
        "decision": d["decision"],
        "decided_by_role": d["decided_by_role"],
    }


def trial(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "service_term_id": t["service_term_id"],
        "caption": t["caption"],
        "required_jurors": t["required_jurors"],
        "status": t["status"],
    }


def panel(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "service_term_id": p["service_term_id"],
        "trial_id": p["trial_id"],
        "target_size": p["target_size"],
        "seated_count": _panel_seated_count(p["id"]),
        "status": p["status"],
    }


def panel_assignment(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "panel_id": a["panel_id"],
        "summons_id": a["summons_id"],
        "seat_index": a["seat_index"],
        "status": a["status"],
    }


def check_in(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "summons_id": c["summons_id"],
        "service_date": c["service_date"],
        "on_floor_hours": c["on_floor_hours"],
        "day_kind": c["day_kind"],
    }


def strike(st):
    return {
        "id": st["id"],
        "created_at": st["created_at"],
        "juror_id": st["juror_id"],
        "summons_id": st["summons_id"],
        "source": st["source"],
    }


def pay_voucher(v):
    return {
        "id": v["id"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
        "summons_id": v["summons_id"],
        "variant": v["variant"],
        "paid_days": v["paid_days"],
        "attendance_cents": v["attendance_cents"],
        "mileage_cents": v["mileage_cents"],
        "total_cents": v["total_cents"],
    }
