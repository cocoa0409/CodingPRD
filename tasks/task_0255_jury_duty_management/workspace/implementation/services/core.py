"""Core business logic: record creation, mutation bookkeeping, calculations,
and the cascade side effects that span entities.

Mutation bookkeeping (PRD §2.4, §2.5): every write to a mutable aggregate
refreshes its updated_at and increments its version by one — including cascaded
adjustments made as a downstream consequence of another operation.
"""
from decimal import Decimal, ROUND_HALF_UP

import db


# ---------------------------------------------------------------------------
# Record construction
# ---------------------------------------------------------------------------

def _base_mutable():
    ts = db.utcnow_iso()
    return {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def _base_append_only():
    return {
        "id": db.new_id(),
        "created_at": db.utcnow_iso(),
        "_seq": db.next_seq(),
    }


def touch(record):
    """Record a mutation: bump version and refresh updated_at (PRD §2.4/§2.5)."""
    record["version"] += 1
    record["updated_at"] = db.utcnow_iso()


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_term(term_id):
    return db.service_terms.get(term_id)


def get_juror(juror_id):
    return db.jurors.get(juror_id)


def get_summons(summons_id):
    return db.summonses.get(summons_id)


def get_disposition(disposition_id):
    return db.dispositions.get(disposition_id)


def get_trial(trial_id):
    return db.trials.get(trial_id)


def get_panel(panel_id):
    return db.panels.get(panel_id)


def get_assignment(assignment_id):
    return db.panel_assignments.get(assignment_id)


# ---------------------------------------------------------------------------
# Computed counter helpers (recomputed from rows; PRD §2.5)
# ---------------------------------------------------------------------------

def term_pool_size(term_id):
    return sum(
        1
        for j in db.jurors.values()
        if j["service_term_id"] == term_id
        and j["qualification_status"] == "QUALIFIED"
        and j["disqualified"] is False
    )


def juror_fta_strike_count(juror_id):
    return sum(1 for st in db.strikes.values() if st["juror_id"] == juror_id and st["source"] == "FTA")


def panel_seated_count(panel_id):
    return sum(
        1
        for a in db.panel_assignments.values()
        if a["panel_id"] == panel_id and a["status"] == "SEATED"
    )


def summons_service_days(summons_id):
    return sum(1 for c in db.check_ins.values() if c["summons_id"] == summons_id)


# ---------------------------------------------------------------------------
# Entity creators
# ---------------------------------------------------------------------------

def create_service_term(name, report_date, daily_pay_cents, half_day_pay_cents,
                        full_day_hours, mileage_rate_cents, pay_day_cap,
                        fta_disqualify_threshold):
    rec = _base_mutable()
    rec.update({
        "name": name,
        "report_date": report_date,
        "daily_pay_cents": daily_pay_cents,
        "half_day_pay_cents": half_day_pay_cents,
        "full_day_hours": full_day_hours,
        "mileage_rate_cents": mileage_rate_cents,
        "pay_day_cap": pay_day_cap,
        "fta_disqualify_threshold": fta_disqualify_threshold,
        "status": "DRAFT",
        "draw_seq": 0,
    })
    db.service_terms[rec["id"]] = rec
    return rec


def create_juror(term_id, full_name, birth_year, round_trip_miles):
    rec = _base_mutable()
    rec.update({
        "service_term_id": term_id,
        "full_name": full_name,
        "birth_year": birth_year,
        "round_trip_miles": round_trip_miles,
        "qualification_status": "PENDING",
        "disqualified": False,
        "last_drawn_seq": 0,
    })
    db.jurors[rec["id"]] = rec
    return rec


def _next_badge_number(term_id):
    existing = [s["badge_number"] for s in db.summonses.values() if s["service_term_id"] == term_id]
    return (max(existing) + 1) if existing else 1


def create_summons(term_id, juror_id, deferral_count=0):
    rec = _base_mutable()
    rec.update({
        "service_term_id": term_id,
        "juror_id": juror_id,
        "badge_number": _next_badge_number(term_id),
        "status": "SUMMONED",
        "deferred_to_term_id": None,
        "deferral_count": deferral_count,
    })
    db.summonses[rec["id"]] = rec
    return rec


def create_qualification_response(summons_id, is_citizen, is_resident,
                                  felony_conviction, english_proficient, evaluated_status):
    rec = _base_append_only()
    rec.update({
        "summons_id": summons_id,
        "is_citizen": is_citizen,
        "is_resident": is_resident,
        "felony_conviction": felony_conviction,
        "english_proficient": english_proficient,
        "evaluated_status": evaluated_status,
    })
    db.qualification_responses[rec["id"]] = rec
    return rec


def create_disposition(summons_id, kind, reason_code, requested_term_id):
    rec = _base_mutable()
    rec.update({
        "summons_id": summons_id,
        "kind": kind,
        "reason_code": reason_code,
        "requested_term_id": requested_term_id,
        "decision": "PENDING",
        "decided_by_role": None,
    })
    db.dispositions[rec["id"]] = rec
    return rec


def create_trial(term_id, caption, required_jurors):
    rec = _base_mutable()
    rec.update({
        "service_term_id": term_id,
        "caption": caption,
        "required_jurors": required_jurors,
        "status": "SCHEDULED",
    })
    db.trials[rec["id"]] = rec
    return rec


def create_panel(term_id, trial_id, target_size):
    rec = _base_mutable()
    rec.update({
        "service_term_id": term_id,
        "trial_id": trial_id,
        "target_size": target_size,
        "seated_count": 0,
        "status": "FORMING",
    })
    db.panels[rec["id"]] = rec
    return rec


def create_panel_assignment(panel_id, summons_id, seat_index):
    rec = _base_mutable()
    rec.update({
        "panel_id": panel_id,
        "summons_id": summons_id,
        "seat_index": seat_index,
        "status": "SEATED",
    })
    db.panel_assignments[rec["id"]] = rec
    return rec


def create_check_in(summons_id, service_date, on_floor_hours, day_kind):
    rec = _base_append_only()
    rec.update({
        "summons_id": summons_id,
        "service_date": service_date,
        "on_floor_hours": on_floor_hours,
        "day_kind": day_kind,
    })
    db.check_ins[rec["id"]] = rec
    return rec


def create_strike(juror_id, summons_id):
    rec = _base_append_only()
    rec.update({
        "juror_id": juror_id,
        "summons_id": summons_id,
        "source": "FTA",
    })
    db.strikes[rec["id"]] = rec
    return rec


def create_pay_voucher(summons_id, variant, paid_days, attendance_cents, mileage_cents, total_cents):
    rec = _base_mutable()
    rec.update({
        "summons_id": summons_id,
        "variant": variant,
        "paid_days": paid_days,
        "attendance_cents": attendance_cents,
        "mileage_cents": mileage_cents,
        "total_cents": total_cents,
    })
    db.pay_vouchers[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Calculations (PRD §3 / scaffold §1.3)
# ---------------------------------------------------------------------------

def _round_half_up(value):
    """Round a Decimal/number half-up to the nearest whole integer (cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def evaluate_qualification(juror, is_citizen, is_resident, felony_conviction, english_proficient):
    """qualification_evaluation (§1.3): strict boolean predicate + age >= 18.

    Age = current calendar year (server clock) - juror.birth_year.
    """
    import clock
    age = clock.current_year() - juror["birth_year"]
    qualified = (
        is_citizen
        and is_resident
        and english_proficient
        and (felony_conviction is False)
        and (age >= 18)
    )
    return "QUALIFIED" if qualified else "INELIGIBLE"


def _eligible_check_ins_sorted(summons_id):
    """All check-ins for the summons, ordered service_date ASC, created_at ASC.

    service_date strings are ISO 8601 so lexical ASC == chronological ASC for a
    consistent format; we tie-break on insertion seq for stable ordering.
    """
    rows = [c for c in db.check_ins.values() if c["summons_id"] == summons_id]
    rows.sort(key=lambda c: (c["service_date"], c["_seq"]))
    return rows


def compute_pay(summons, term, juror, eligible_check_ins):
    """pay_computation (§1.3). Returns (paid_days, attendance_cents,
    mileage_cents, total_cents).

    paid_days = min(count(eligible), pay_day_cap).
    Counted days = first paid_days eligible check-ins by (service_date ASC,
    created_at ASC). attendance = sum of per-day pay (full vs half) over counted.
    Mileage rounding is PINNED: round per-day (round_trip_miles * mileage_rate)
    half-up to whole cents, then multiply by paid_days (round-per-day-then-sum).
    """
    pay_day_cap = term["pay_day_cap"]
    paid_days = min(len(eligible_check_ins), pay_day_cap)
    counted = eligible_check_ins[:paid_days]

    attendance_cents = 0
    for c in counted:
        if c["day_kind"] == "FULL":
            attendance_cents += term["daily_pay_cents"]
        else:
            attendance_cents += term["half_day_pay_cents"]

    per_day_mileage = _round_half_up(
        Decimal(str(juror["round_trip_miles"])) * Decimal(term["mileage_rate_cents"])
    )
    mileage_cents = per_day_mileage * paid_days
    total_cents = attendance_cents + mileage_cents
    return paid_days, attendance_cents, mileage_cents, total_cents


def pool_projection(term):
    """mileage_per_diem_reimbursement (§1.3): sum-then-round (one terminal round).

    pool = QUALIFIED & not disqualified jurors of the term.
    total_miles = sum(round_trip_miles) * pay_day_cap
    projected = round_half_up(total_miles * mileage_rate_cents).
    """
    pool = [
        j
        for j in db.jurors.values()
        if j["service_term_id"] == term["id"]
        and j["qualification_status"] == "QUALIFIED"
        and j["disqualified"] is False
    ]
    sum_miles = sum((Decimal(str(j["round_trip_miles"])) for j in pool), Decimal("0"))
    total_miles = sum_miles * Decimal(term["pay_day_cap"])
    projected = _round_half_up(total_miles * Decimal(term["mileage_rate_cents"]))
    return projected, len(pool)


# ---------------------------------------------------------------------------
# Pay voucher issuance helpers
# ---------------------------------------------------------------------------

def issue_estimated_voucher(summons):
    """ESTIMATED voucher: eligible = all check-ins recorded up to seating."""
    term = db.service_terms[summons["service_term_id"]]
    juror = db.jurors[summons["juror_id"]]
    eligible = _eligible_check_ins_sorted(summons["id"])
    paid, att, mil, total = compute_pay(summons, term, juror, eligible)
    return create_pay_voucher(summons["id"], "ESTIMATED", paid, att, mil, total)


def issue_final_voucher(summons):
    """FINAL voucher: eligible = ALL check-ins through release."""
    term = db.service_terms[summons["service_term_id"]]
    juror = db.jurors[summons["juror_id"]]
    eligible = _eligible_check_ins_sorted(summons["id"])
    paid, att, mil, total = compute_pay(summons, term, juror, eligible)
    return create_pay_voucher(summons["id"], "FINAL", paid, att, mil, total)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def recompute_juror_disqualification(juror):
    """fta_disqualification (§1.3) cascade.

    Recompute fta_strike_count; if it reaches the term threshold flip disqualified
    true; if the juror was QUALIFIED drive it to INELIGIBLE. Each touched mutable
    aggregate gets its own version bump (PRD §2.5).
    """
    term = db.service_terms[juror["service_term_id"]]
    count = juror_fta_strike_count(juror["id"])
    became_disqualified = (count >= term["fta_disqualify_threshold"])

    if became_disqualified and not juror["disqualified"]:
        juror["disqualified"] = True
        if juror["qualification_status"] == "QUALIFIED":
            juror["qualification_status"] = "INELIGIBLE"
        touch(juror)
        # pool_size is a computed counter on the term; recomputing it is itself a
        # mutation of the term (PRD §2.5).
        touch(term)
