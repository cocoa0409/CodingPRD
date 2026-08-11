"""Custody episodes, the stray hold clock, the owner reclaim, and holds."""

from flask import Blueprint, request

import auth
import calc
import clock
import derive
import envelope
import gates
import services
from errors import ApiError
from routing import listing, must, must_fk, query_filters, latch_all
from store import DB, touch
from validation import Field, parse_body

bp = Blueprint("intake", __name__)


@bp.post("/rescue/animals/<animal_id>/intake-records")
def create_intake_record(animal_id):
    auth.authenticate(["PlatformAdmin", "IntakeOfficer"])
    body = parse_body(request, [
        Field("intake_type", "string", required=True, enum="intake_type"),
        Field("intake_datetime", "datetime", required=True),
        Field("source_person_id", "string", default=None),
        Field("impound_billing_basis", "string", default="CALENDAR_DAY",
              enum="impound_billing_basis"),
    ])
    animal = must("Animal", animal_id)
    must_fk("Person", body["source_person_id"])
    gates.run_gates(gates.gate1_org_id(animal=animal), animal=animal, gate2=True)

    # Rung 18: PRE_INTAKE -> IN_CUSTODY, precondition "no IntakeRecord for this
    # animal has status OPEN" (PRD 3.2: at most one open episode at a time).
    if animal["lifecycle_status"] != "PRE_INTAKE" or derive.open_episode(animal) is not None:
        raise ApiError("ERR_INVALID_STATE", "The animal already has an open custody episode.")

    identifiable_at_intake = bool(animal["identifiable"])
    hold_days = calc.stray_hold_days(body["intake_type"], identifiable_at_intake)
    intake_raw = body["intake_datetime"]
    record = DB.insert("IntakeRecord", {
        "animal_id": animal["id"],
        "source_person_id": body["source_person_id"],
        "intake_type": body["intake_type"],
        "intake_datetime": intake_raw,                 # (b) echoed byte-verbatim
        "impound_billing_basis": body["impound_billing_basis"],
        "identifiable_at_intake": identifiable_at_intake,
        "hold_days": hold_days,
        # (c) derived instant, rendered in the style of intake_datetime
        "hold_expires_at": clock.derive(
            clock.plus_days(clock.parse(intake_raw), hold_days), intake_raw),
        "hold_status": "HOLD_ACTIVE",
        "status": "OPEN",
        "reclaim_base_fee_cents": None,
        "impound_billable_days": None,
        "impound_subtotal_cents": None,
        "repeat_offense_multiplier": None,
        "hardship_waiver_cents": None,
        "reclaim_total_cents": None,
    })
    animal["lifecycle_status"] = "IN_CUSTODY"
    animal["current_intake_record_id"] = record["id"]
    touch(animal)
    derive.latch_hold(record)
    return envelope.created(derive.intake_record(record))


@bp.get("/rescue/intake-records/<record_id>")
def read_intake_record(record_id):
    auth.authenticate(["PlatformAdmin", "IntakeOfficer", "AdoptionCounselor", "FinanceOfficer"])
    return envelope.ok(derive.intake_record(must("IntakeRecord", record_id)))


@bp.get("/rescue/intake-records")
def list_intake_records():
    auth.authenticate(["PlatformAdmin", "IntakeOfficer", "AdoptionCounselor", "FinanceOfficer"])
    rows = latch_all("IntakeRecord")
    filters = query_filters(["animal_id", "source_person_id", "intake_type", "status", "hold_status"])
    return listing("IntakeRecord", rows, filters)


@bp.post("/rescue/intake-records/<record_id>/reclaim")
def reclaim(record_id):
    auth.authenticate(["PlatformAdmin", "IntakeOfficer"])
    body = parse_body(request, [Field("reclaiming_person_id", "string", required=True)])
    record = must("IntakeRecord", record_id)
    person = must("Person", body["reclaiming_person_id"])
    animal = DB.get("Animal", record["animal_id"])
    # A reclaim is blocked by an active LEGAL hold but -- deliberately -- never
    # by a MEDICAL or BEHAVIOURAL one (PRD 2.6).
    gates.run_gates(gates.gate1_org_id(animal=animal), animal=animal, gate2=True, gate3=True)

    derive.latch_hold(record)
    if animal["lifecycle_status"] != "IN_CUSTODY" or record["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE",
                       "The animal must be IN_CUSTODY with this episode still OPEN.")

    # The charge is assembled in a pinned order (PRD 3.2).
    days = calc.impound_billable_days(record)
    subtotal = calc.impound_tiered_subtotal(days)
    history = derive.reclaim_history_count(person["id"])   # read BEFORE this reclaim is written
    multiplier = calc.repeat_offense_multiplier(history)
    _step1, _pre_waiver, waiver, total = calc.reclaim_total(
        subtotal, multiplier, bool(person["hardship_certified"]))

    record["reclaim_base_fee_cents"] = calc.BASE_RECLAIM_FEE_CENTS
    record["impound_billable_days"] = days
    record["impound_subtotal_cents"] = subtotal
    record["repeat_offense_multiplier"] = multiplier
    record["hardship_waiver_cents"] = waiver
    record["reclaim_total_cents"] = total

    outcome = services.write_outcome(animal, "RETURN_TO_OWNER",
                                     counterparty_person_id=person["id"])
    return envelope.created(derive.outcome_record(outcome))


# =====================================================================
#  Holds (PRD 3.3)
# =====================================================================

@bp.post("/rescue/animals/<animal_id>/holds")
def create_hold(animal_id):
    auth.authenticate(["PlatformAdmin", "IntakeOfficer", "Veterinarian"])
    body = parse_body(request, [
        Field("hold_type", "string", required=True, enum="hold_type"),
        Field("reason", "string", required=True),
    ])
    animal = must("Animal", animal_id)
    gates.run_gates(gates.gate1_org_id(animal=animal), animal=animal, gate2=True)
    hold = DB.insert("HoldRecord", {
        "animal_id": animal["id"],
        "hold_type": body["hold_type"],
        "reason": body["reason"],
        "status": "ACTIVE",
        "released_at": None,
        "released_by_user_id": None,
    })
    return envelope.created(derive.hold_record(hold))


@bp.get("/rescue/holds/<hold_id>")
def read_hold(hold_id):
    auth.authenticate(["PlatformAdmin", "IntakeOfficer", "Veterinarian",
                       "AdoptionCounselor", "TransportDispatcher"])
    return envelope.ok(derive.hold_record(must("HoldRecord", hold_id)))


@bp.get("/rescue/holds")
def list_holds():
    auth.authenticate(["PlatformAdmin", "IntakeOfficer", "Veterinarian",
                       "AdoptionCounselor", "TransportDispatcher"])
    return listing("HoldRecord", DB.all("HoldRecord"),
                   query_filters(["animal_id", "hold_type", "status"]))


@bp.post("/rescue/holds/<hold_id>/release")
def release_hold(hold_id):
    ctx = auth.authenticate(["PlatformAdmin", "IntakeOfficer", "Veterinarian"])
    parse_body(request, [])
    hold = must("HoldRecord", hold_id)
    animal = DB.get("Animal", hold["animal_id"])
    # PRD 3.3: imposing a hold is subject to the outcome-closed gate, but
    # RELEASING one is not, so a hold left over on a closed animal can always
    # be cleaned up.
    gates.check_gate1(gates.gate1_org_id(animal=animal))
    if hold["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "There is no transition out of RELEASED.")
    hold["status"] = "RELEASED"
    hold["released_at"] = clock.stamp()               # (c) clock-derived
    hold["released_by_user_id"] = ctx.user_id
    touch(hold)
    return envelope.ok(derive.hold_record(hold))
