"""Public serialization for each entity (PRD 2.4 common fields + entity fields).

Records are stored with their public field names plus internal keys prefixed
with '_'. Serializers select the public shape and compute derived fields.
"""
from store import db
from core import parse_dt

_COMMON = ("id", "created_at", "updated_at", "version")
_REF_COMMON = ("id", "created_at")


def _pick(rec, fields):
    return {f: rec[f] for f in fields if f in rec}


def compute_age(birth_raw):
    bd = parse_dt(birth_raw, "birth_date")
    today = db.clock.date()
    b = bd.date()
    years = today.year - b.year
    if (today.month, today.day) < (b.month, b.day):
        years -= 1
    return years


def ser_participant(r):
    out = _pick(r, _COMMON)
    out.update({
        "full_name": r["full_name"],
        "birth_date": r["birth_date"],
        "gender": r["gender"],
        "ethnicity": r["ethnicity"],
        "race": r["race"],
        "poverty_status": r["poverty_status"],
        "lives_alone": r["lives_alone"],
        "rural": r["rural"],
        "veteran": r["veteran"],
        "disability_count": r["disability_count"],
        "status": r["status"],
        "funded_cents": r["funded_cents"],
        "age": compute_age(r["birth_date"]),
    })
    return out


def ser_grant(r):
    out = _pick(r, _COMMON)
    out.update({
        "title": r["title"],
        "oaa_title": r["oaa_title"],
        "category": r["category"],
        "authorized_cents": r["authorized_cents"],
        "committed_cents": r["committed_cents"],
        "available_cents": r["available_cents"],
        "status": r["status"],
    })
    return out


def ser_donation(r):
    out = _pick(r, _COMMON)
    out.update({
        "donor_name": r["donor_name"],
        "category": r["category"],
        "amount_cents": r["amount_cents"],
        "remaining_cents": r["remaining_cents"],
        "restricted": r["restricted"],
    })
    return out


def ser_funded_service(r):
    out = _pick(r, _COMMON)
    out.update({
        "participant_id": r["participant_id"],
        "category": r["category"],
        "quantity": r["quantity"],
        "service_date": r["service_date"],
        "grant_award_id": r["grant_award_id"],
        "donation_id": r["donation_id"],
        "billable_cents": r["billable_cents"],
        "grant_amount_cents": r["grant_amount_cents"],
        "donation_amount_cents": r["donation_amount_cents"],
        "unfunded_amount_cents": r["unfunded_amount_cents"],
        "funding_status": r["funding_status"],
        "status": r["status"],
    })
    return out


def ser_room(r):
    out = _pick(r, _REF_COMMON)
    out.update({"name": r["name"], "capacity": r["capacity"]})
    return out


def ser_session(r):
    out = _pick(r, _COMMON)
    out.update({
        "title": r["title"],
        "category": r["category"],
        "room_id": r["room_id"],
        "starts_at": r["starts_at"],
        "ends_at": r["ends_at"],
        "capacity": r["capacity"],
        "enrolled_count": r["enrolled_count"],
        "status": r["status"],
    })
    return out


def ser_signup(r):
    out = _pick(r, _COMMON)
    out.update({
        "session_id": r["session_id"],
        "participant_id": r["participant_id"],
        "status": r["status"],
    })
    return out


def ser_vehicle(r):
    out = _pick(r, _REF_COMMON)
    out.update({"name": r["name"], "seat_capacity": r["seat_capacity"]})
    return out


def ser_transport(r):
    out = _pick(r, _COMMON)
    out.update({
        "participant_id": r["participant_id"],
        "vehicle_id": r["vehicle_id"],
        "linked_session_id": r["linked_session_id"],
        "starts_at": r["starts_at"],
        "ends_at": r["ends_at"],
        "eligibility_status": r["eligibility_status"],
        "trip_status": r["trip_status"],
    })
    return out


def ser_service_day(r):
    out = _pick(r, _COMMON)
    reserved = r["reserved_count"]
    served = r["served_count"]
    out.update({
        "service_date": r["service_date"],
        "site_name": r["site_name"],
        "capacity": r["capacity"],
        "reserved_count": reserved,
        "available_seats": r["capacity"] - reserved,
        "served_count": served,
        "provisional_reimbursable_units": reserved,
        "final_reimbursable_units": served,
        "status": r["status"],
    })
    return out


def ser_reservation(r):
    out = _pick(r, _COMMON)
    out.update({
        "service_day_id": r["service_day_id"],
        "participant_id": r["participant_id"],
        "suggested_contribution_cents": r["suggested_contribution_cents"],
        "status": r["status"],
    })
    return out


def ser_program(r):
    out = _pick(r, _COMMON)
    out.update({
        "title": r["title"],
        "model": r["model"],
        "total_sessions": r["total_sessions"],
        "fidelity_min_sessions": r["fidelity_min_sessions"],
    })
    return out


def ser_enrollment(r):
    out = _pick(r, _COMMON)
    program = db.programs.get(r["program_id"])
    total = program["total_sessions"] if program else 0
    fidelity = program["fidelity_min_sessions"] if program else 0
    projected = "WILL_GRADUATE" if (total - r["absences_total"]) >= fidelity else "AT_RISK"
    out.update({
        "program_id": r["program_id"],
        "participant_id": r["participant_id"],
        "sessions_attended": r["sessions_attended"],
        "consecutive_absences": r["consecutive_absences"],
        "absences_total": r["absences_total"],
        "projected_graduation_status": projected,
        "status": r["status"],
    })
    return out


def ser_volunteer_shift(r):
    out = _pick(r, _COMMON)
    out.update({
        "volunteer_name": r["volunteer_name"],
        "role": r["role"],
        "hours": r["hours"],
        "service_date": r["service_date"],
    })
    return out
