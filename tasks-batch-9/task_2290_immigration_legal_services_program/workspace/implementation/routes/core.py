"""Logical clock, clients, capacity cycles, detention facilities."""

from flask import Blueprint, request

import auth
import calc
import response
import serialize
import store
import validation as v
from errors import ApiError

bp = Blueprint("core", __name__)


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@auth.requires("ProgramDirector")
def set_clock():
    payload = v.body()
    moment = v.as_datetime(payload, "to_iso8601")
    store.set_clock(store.iso(moment))
    # PRD 3.10: "The endpoint returns HTTP 200 with an empty data object."
    return response.ok({})


# --------------------------------------------------------------------------
# clients
# --------------------------------------------------------------------------

def _client_shape(payload):
    full_name = v.as_str(payload, "full_name", min_len=1, max_len=160)
    language = v.language_code(payload, "preferred_language_code")
    country = v.country_code(payload, "country_of_birth_code")
    dob = v.as_date(payload, "date_of_birth")
    household = v.as_int(payload, "household_size", minimum=1)
    income = v.as_int(payload, "annual_household_income_cents", minimum=0)
    a_number = v.a_number(payload, "a_number")
    scope = v.as_enum(payload, "confidentiality_consent_scope", calc.CONSENT_SCOPES,
                      required=False, default="PROGRAM_ONLY")
    if dob >= store.clock_date():
        v.bad("date_of_birth must be strictly before the current logical date.")
    if a_number is not None:
        for existing in store.db["clients"].values():
            if existing.get("a_number") == a_number:
                v.bad("a_number must be unique.")
    return {
        "full_name": full_name,
        "preferred_language_code": language,
        "country_of_birth_code": country,
        "date_of_birth": dob.isoformat(),
        "household_size": household,
        "annual_household_income_cents": income,
        "a_number": a_number,
        "confidentiality_consent_scope": scope,
    }


@bp.post("/clients")
@auth.requires("ProgramDirector", "IntakeScreener")
def create_client():
    payload = v.body()
    fields = _client_shape(payload)
    fields["fpl_percent"] = calc.fpl_percent(
        fields["household_size"], fields["annual_household_income_cents"])
    fields["interpreter_required"] = calc.interpreter_required(
        fields["preferred_language_code"])
    fields["open_matter_count"] = 0
    fields["status"] = "ACTIVE"
    row = store.insert("clients", store.new_row(fields))
    return response.created(serialize.client(row))


@bp.get("/clients")
@auth.requires("ProgramDirector", "IntakeScreener", "SupervisingAttorney", "GrantAnalyst")
def list_clients():
    rows = store.rows("clients")
    args = request.args
    if args.get("status"):
        rows = [r for r in rows if r["status"] == args["status"]]
    if args.get("preferred_language_code"):
        rows = [r for r in rows
                if r["preferred_language_code"] == args["preferred_language_code"]]
    if args.get("confidentiality_consent_scope"):
        rows = [r for r in rows
                if r["confidentiality_consent_scope"]
                == args["confidentiality_consent_scope"]]
    page, meta = store.paginate(rows, args)
    return response.collection([serialize.client(r) for r in page], meta)


@bp.get("/clients/<client_id>")
@auth.requires("ProgramDirector", "IntakeScreener", "SupervisingAttorney",
               "CaseRepresentative", "GrantAnalyst", "ClientPortalUser", scoped=True)
def read_client(client_id):
    auth.scope_client(client_id)
    row = store.get("clients", client_id)
    if row is None:
        raise ApiError("ERR_CLIENT_NOT_FOUND")
    return response.ok(serialize.client(row))


@bp.patch("/clients/<client_id>")
@auth.requires("ProgramDirector", "IntakeScreener")
def update_client(client_id):
    row = store.get("clients", client_id)
    if row is None:
        raise ApiError("ERR_CLIENT_NOT_FOUND")
    payload = v.body()
    if v.present(payload, "household_size"):
        row["household_size"] = v.as_int(payload, "household_size", minimum=1)
    if v.present(payload, "annual_household_income_cents"):
        row["annual_household_income_cents"] = v.as_int(
            payload, "annual_household_income_cents", minimum=0)
    if v.present(payload, "preferred_language_code"):
        row["preferred_language_code"] = v.language_code(payload, "preferred_language_code")
    if v.present(payload, "confidentiality_consent_scope"):
        row["confidentiality_consent_scope"] = v.as_enum(
            payload, "confidentiality_consent_scope", calc.CONSENT_SCOPES)
    if v.present(payload, "interpreter_required"):
        v.as_bool(payload, "interpreter_required")
    if v.present(payload, "status"):
        v.as_enum(payload, "status", ("ACTIVE", "CLOSED"))
    row["fpl_percent"] = calc.fpl_percent(
        row["household_size"], row["annual_household_income_cents"])
    row["interpreter_required"] = calc.interpreter_required(row["preferred_language_code"])
    store.touch(row)
    return response.ok(serialize.client(row))


def recompute_client(client):
    """open_matter_count and the derived ACTIVE / CLOSED status (PRD 3.1)."""
    count = 0
    for matter in store.db["matters"].values():
        if matter.get("client_id") != client["id"]:
            continue
        if matter.get("representation_status") == "WITHDRAWN_FROM":
            continue
        count += 1
    previous = int(client.get("open_matter_count") or 0)
    client["open_matter_count"] = count
    if count >= 1:
        client["status"] = "ACTIVE"
    elif previous > 0:
        client["status"] = "CLOSED"
    store.touch(client)
    return client


# --------------------------------------------------------------------------
# capacity cycles
# --------------------------------------------------------------------------

@bp.post("/capacity-cycles")
@auth.requires("ProgramDirector")
def create_cycle():
    payload = v.body()
    label = v.as_str(payload, "cycle_label", min_len=1, max_len=60)
    start = v.as_date(payload, "period_start_date")
    end = v.as_date(payload, "period_end_date")
    total = v.as_int(payload, "total_case_slots", minimum=1)
    reserved = v.as_int(payload, "reserved_detained_slots", minimum=0)
    if end <= start:
        v.bad("period_end_date must be strictly after period_start_date.")
    if reserved > total:
        v.bad("reserved_detained_slots must not exceed total_case_slots.")
    for existing in store.db["cycles"].values():
        if existing.get("cycle_label") == label:
            v.bad("cycle_label must be unique.")
    row = store.new_row({
        "cycle_label": label,
        "period_start_date": start.isoformat(),
        "period_end_date": end.isoformat(),
        "total_case_slots": total,
        "reserved_detained_slots": reserved,
        "general_slots_consumed": 0,
        "detained_slots_consumed": 0,
        "available_slot_count": total,
        "waitlisted_count": 0,
        "utilization_ratio": store.rhu(0, 4),
        "capacity_posture": "OPEN",
        "posture_override_until_utc": None,
        "override_reason_code": None,
        "checkpoint_epoch": 1,
        "last_checkpoint_utc": store.clock_iso(),
    })
    store.insert("cycles", row)
    return response.created(serialize.cycle(row))


@bp.get("/capacity-cycles")
@auth.requires("ProgramDirector", "IntakeScreener", "SupervisingAttorney", "GrantAnalyst")
def list_cycles():
    rows = store.rows("cycles")
    args = request.args
    if args.get("capacity_posture"):
        rows = [r for r in rows
                if calc.effective_posture(r) == args["capacity_posture"]]
    page, meta = store.paginate(rows, args)
    return response.collection([serialize.cycle(r) for r in page], meta)


@bp.get("/capacity-cycles/<cycle_id>")
@auth.requires("ProgramDirector", "IntakeScreener", "SupervisingAttorney", "GrantAnalyst")
def read_cycle(cycle_id):
    row = store.get("cycles", cycle_id)
    if row is None:
        raise ApiError("ERR_CYCLE_NOT_FOUND")
    return response.ok(serialize.cycle(row))


@bp.post("/capacity-cycles/<cycle_id>/posture-override")
@auth.requires("ProgramDirector")
def posture_override(cycle_id):
    row = store.get("cycles", cycle_id)
    if row is None:
        raise ApiError("ERR_CYCLE_NOT_FOUND")
    payload = v.body()
    until = v.as_datetime(payload, "posture_override_until_utc")
    reason = v.as_str(payload, "override_reason_code", min_len=1, max_len=40)
    row["posture_override_until_utc"] = store.iso(until)
    row["override_reason_code"] = reason
    store.touch(row)
    return response.ok(serialize.cycle(row))


@bp.post("/capacity-cycles/<cycle_id>/checkpoint")
@auth.requires("ProgramDirector")
def cycle_checkpoint(cycle_id):
    import cascades
    row = store.get("cycles", cycle_id)
    if row is None:
        raise ApiError("ERR_CYCLE_NOT_FOUND")
    cascades.run_checkpoint(row)
    return response.ok(serialize.cycle(row))


# --------------------------------------------------------------------------
# detention facilities
# --------------------------------------------------------------------------

@bp.post("/detention-facilities")
@auth.requires("ProgramDirector")
def create_facility():
    payload = v.body()
    name = v.as_str(payload, "name", min_len=1, max_len=120)
    jurisdiction = v.upper_code(payload, "jurisdiction_code", 2, 8)
    lead_time = v.as_int(payload, "visit_lead_time_hours", required=False,
                         minimum=0, default=48)
    slots = v.as_int(payload, "max_daily_visit_slots", minimum=0)
    expedited = v.as_int(payload, "expedited_filing_days", required=False,
                         minimum=1, default=21)
    credential = v.as_bool(payload, "access_credential_required", default=True)
    status = v.as_enum(payload, "status", ("OPEN", "RESTRICTED_ACCESS", "CLOSED"),
                       required=False, default="OPEN")
    for existing in store.db["facilities"].values():
        if existing.get("name") == name:
            v.bad("name must be unique.")
    row = store.new_row({
        "name": name,
        "jurisdiction_code": jurisdiction,
        "visit_lead_time_hours": lead_time,
        "max_daily_visit_slots": slots,
        "expedited_filing_days": expedited,
        "access_credential_required": credential,
        "status": status,
    })
    store.insert("facilities", row)
    return response.created(serialize.facility(row))


@bp.get("/detention-facilities")
@auth.requires("ProgramDirector", "IntakeScreener", "SupervisingAttorney",
               "CaseRepresentative")
def list_facilities():
    rows = store.rows("facilities")
    args = request.args
    if args.get("jurisdiction_code"):
        rows = [r for r in rows if r["jurisdiction_code"] == args["jurisdiction_code"]]
    if args.get("status"):
        rows = [r for r in rows if r["status"] == args["status"]]
    page, meta = store.paginate(rows, args)
    return response.collection([serialize.facility(r) for r in page], meta)


@bp.get("/detention-facilities/<facility_id>")
@auth.requires("ProgramDirector", "IntakeScreener", "SupervisingAttorney",
               "CaseRepresentative")
def read_facility(facility_id):
    row = store.get("facilities", facility_id)
    if row is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND")
    return response.ok(serialize.facility(row))
