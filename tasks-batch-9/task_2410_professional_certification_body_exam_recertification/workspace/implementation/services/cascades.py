"""Multi-hop synchronous cascades (PRD 2.9 / 3.4 / 3.9 / 3.10 / 3.11 / 3.12).

Every hop is applied inside the originating request; each record the cascade
reaches gets its own `updated_at` refresh and its own single `version` bump.
"""

from decimal import Decimal

from db import DB, mark_created, new_record, ordered, touch
from services import calc, derive
from util import add_days, add_months, dec


def _recount_sessions(session_ids):
    for session in ordered([DB.sessions[i] for i in session_ids if i in DB.sessions]):
        derive.recount_session(session)


# ---------------------------------------------------------------------------
# Item retirement -- four hops (PRD 3.4)
# ---------------------------------------------------------------------------

def cascade_item_retired(item):
    program = DB.programs[item["program_id"]]
    derive.recompute_blueprint_posture(program)

    released_sessions = set()
    for form in derive.forms_citing_item(item["id"]):
        derive.recompute_form_retired_count(form)
        form_program = DB.programs[form["program_id"]]
        if form["status"] != "PUBLISHED":
            continue
        if not calc.form_needs_rebuild(
            form["retired_item_count"],
            len(form["item_ids"]),
            form_program["form_retirement_tolerance_pct"],
        ):
            continue
        form["status"] = "NEEDS_REBUILD"
        touch(form)
        for registration in derive.registrations_of_form(form["id"]):
            if registration["seat_status"] != "SCHEDULED":
                continue
            held = registration["session_id"]
            registration["seat_status"] = "UNSCHEDULED"
            registration["form_reassignment_required"] = True
            registration["session_id"] = None
            touch(registration)
            if held:
                released_sessions.add(held)

    _recount_sessions(released_sessions)


# ---------------------------------------------------------------------------
# Substantiated security incident (PRD 3.9)
# ---------------------------------------------------------------------------

def cascade_incident_substantiated(incident, registration):
    registration["score_status"] = "VOIDED"
    registration["scaled_score"] = None
    registration["outcome"] = None
    touch(registration)

    if incident["severity"] != "CRITICAL":
        return

    candidate = DB.candidates[registration["candidate_id"]]
    candidate["status"] = "BARRED"
    candidate["bar_reason"] = "SECURITY_INCIDENT"
    candidate["barred_until"] = add_days(DB.now(), calc.SECURITY_BAR_DAYS)
    touch(candidate)

    released_sessions = set()
    for sibling in derive.registrations_of_candidate(candidate["id"]):
        if sibling["id"] == registration["id"]:
            continue
        if sibling["seat_status"] != "SCHEDULED":
            continue
        held = sibling["session_id"]
        sibling["seat_status"] = "CANCELLED"
        sibling["session_id"] = None
        touch(sibling)
        if held:
            released_sessions.add(held)
    _recount_sessions(released_sessions)


# ---------------------------------------------------------------------------
# Credentialing -- report-score cascade (PRD 3.10 / 3.11)
# ---------------------------------------------------------------------------

def open_cycle(certificant, program, cycle_number, starts_on, carryover_in):
    ends_on = add_months(starts_on, program["cycle_length_months"])
    cycle = new_record(
        certificant_id=certificant["id"],
        reexam_registration_id=None,
        cycle_number=cycle_number,
        starts_on=starts_on,
        ends_on=ends_on,
        grace_ends_on=add_days(ends_on, program["recert_grace_days"]),
        required_credits=dec(program["required_ceu_credits"]),
        accrual_basis_snapshot=program["ceu_credit_accrual_basis"],
        carryover_credits_in=dec(carryover_in),
        credits_applied=Decimal("0.00"),
        carryover_credits_out=Decimal("0.00"),
        path="CEU",
        status="OPEN",
        reinstatement_fee_cents=None,
    )
    mark_created(cycle)
    DB.cycles[cycle["id"]] = cycle
    derive.reconcile_cycle(cycle, program)
    return cycle


def mint_certificant(registration, application, program):
    """Hops 1-3 of the report-score cascade."""
    program["certificants_issued_count"] += 1
    touch(program)
    issued_on = DB.now()
    certificant = new_record(
        candidate_id=registration["candidate_id"],
        program_id=program["id"],
        certificate_number=calc.certificate_number(
            program["credential_code"], issued_on.year, program["certificants_issued_count"]
        ),
        issued_on=issued_on,
        valid_through=add_months(issued_on, program["cycle_length_months"]),
        status="ACTIVE",
        suspension_until=None,
        publication_status="PUBLISHED",
        ceu_credits_applied=Decimal("0.00"),
        current_cycle_id=None,
    )
    mark_created(certificant)
    DB.certificants[certificant["id"]] = certificant

    open_cycle(certificant, program, 1, issued_on, Decimal("0.00"))
    derive.refresh_certificant_projection(certificant)
    return certificant


def pending_reexam_cycle(candidate_id):
    """The RE_EXAM cycle a reported PASS should satisfy instead of minting."""
    for certificant in derive.certificants_of_candidate(candidate_id):
        cycles = [c for c in derive.cycles_of_certificant(certificant["id"])
                  if c["path"] == "RE_EXAM" and c["status"] in ("OPEN", "LAPSED")]
        if cycles:
            return certificant, min(cycles, key=lambda c: c["cycle_number"])
    return None, None


# ---------------------------------------------------------------------------
# Cycle close -- three hops (PRD 3.11)
# ---------------------------------------------------------------------------

def cascade_cycle_closed(cycle, certificant, program):
    cycle["carryover_credits_out"] = calc.carryover_computation(cycle, program)
    cycle["status"] = "CLOSED"
    touch(cycle)

    certificant["valid_through"] = add_months(
        certificant["valid_through"], program["cycle_length_months"]
    )
    touch(certificant)

    successor = open_cycle(
        certificant,
        program,
        cycle["cycle_number"] + 1,
        cycle["ends_on"],
        cycle["carryover_credits_out"],
    )
    derive.refresh_certificant_projection(certificant)
    return successor


# ---------------------------------------------------------------------------
# Revocation -- three hops (PRD 3.12)
# ---------------------------------------------------------------------------

def cascade_revocation(certificant):
    certificant["status"] = "REVOKED"
    touch(certificant)
    for cycle in derive.cycles_of_certificant(certificant["id"]):
        if cycle["status"] not in ("OPEN", "SATISFIED", "LAPSED"):
            continue
        cycle["status"] = "VOID"
        for activity in derive.activities_of_cycle(cycle["id"]):
            if activity["status"] not in ("APPROVED", "AUDIT_SELECTED", "VERIFIED"):
                continue
            if activity["counted"] or activity["credits_counted"] != Decimal("0.00"):
                activity["counted"] = False
                activity["credits_counted"] = Decimal("0.00")
                touch(activity)
        cycle["credits_applied"] = Decimal("0.00")
        touch(cycle)
    derive.refresh_certificant_projection(certificant)


# ---------------------------------------------------------------------------
# Election of re-examination (PRD 3.11)
# ---------------------------------------------------------------------------

def cascade_elect_reexam(cycle):
    cycle["path"] = "RE_EXAM"
    cycle["required_credits"] = Decimal("0.00")
    for activity in derive.activities_of_cycle(cycle["id"]):
        if activity["status"] not in ("SUBMITTED", "APPROVED", "AUDIT_SELECTED", "VERIFIED"):
            continue
        if activity["counted"] or activity["credits_counted"] != Decimal("0.00"):
            activity["counted"] = False
            activity["credits_counted"] = Decimal("0.00")
            touch(activity)
    cycle["credits_applied"] = Decimal("0.00")
    touch(cycle)
