"""Logical clock, holiday set and programme reference data (PRD 2.4, 3.1)."""
from flask import Blueprint

import constants as C
import domain
import envelope
import guards as G
import store
from errors import ApiError
from store import DB, serialize

bp = Blueprint("reference", __name__)


# ------------------------------------------------------------ logical clock
@bp.post("/_clock/set_current_utc")
def set_current_utc():
    G.auth(["ProgramAdmin"])
    data = G.body()
    instant = G.req_instant(data, "to_iso8601")
    store.set_clock(instant)
    return envelope.ok({"current_utc": store.fmt_instant(store.now())})


# -------------------------------------------------------------- holiday set
@bp.post("/tcm/holidays")
def replace_holidays():
    G.auth(["ProgramAdmin"])
    data = G.body()
    raw = G.req_array(data, "holiday_dates")
    dates = []
    for value in raw:
        if not isinstance(value, str) or store.parse_date(value) is None:
            raise ApiError(
                "ERR_VALIDATION", "Field 'holiday_dates' must contain YYYY-MM-DD strings."
            )
        dates.append(value)
    store.set_holidays(dates)

    for episode in list(DB["episodes"].values()):
        if episode["record_posture"] != "OPEN":
            continue
        payer = DB["payers"].get(episode["payer_id"])
        if payer is None or payer["contact_deadline_basis"] != "BUSINESS_DAYS":
            continue
        deadline = domain.contact_deadline_at(episode)
        if episode["contact_deadline_at"] != deadline:
            episode["contact_deadline_at"] = deadline
            store.touch(episode)
        domain.recompute_contact_timely(episode)

    return envelope.ok({"holiday_dates": list(store.holidays())})


# ----------------------------------------------------------------- patients
@bp.post("/tcm/patients")
def register_patient():
    G.auth(["ProgramAdmin", "IntakeCoordinator"])
    data = G.body()
    external_mrn = G.req_string(data, "external_mrn")
    full_name = G.req_string(data, "full_name")
    date_of_birth = G.req_date(data, "date_of_birth")
    primary_language = G.opt_string(data, "primary_language", default="EN", allow_empty=False)
    for existing in DB["patients"].values():
        if existing["external_mrn"] == external_mrn:
            raise ApiError("ERR_VALIDATION", "Field 'external_mrn' must be unique across patients.")
    row = store.new_row(
        "patients",
        {
            "external_mrn": external_mrn,
            "full_name": full_name,
            "date_of_birth": date_of_birth,
            "primary_language": primary_language,
            "open_episode_count": 0,
            "lifetime_episode_count": 0,
            "lifetime_readmission_count": 0,
        },
    )
    return envelope.created(serialize(row))


@bp.get("/tcm/patients/<patient_id>")
def read_patient(patient_id):
    G.auth(C.ALL_ROLES)
    return envelope.ok(serialize(G.get_row("patients", patient_id)))


# --------------------------------------------------------------- facilities
@bp.post("/tcm/facilities")
def register_facility():
    G.auth(["ProgramAdmin"])
    data = G.body()
    name = G.req_string(data, "name")
    facility_type = G.req_string(data, "facility_type")
    network_status = G.req_string(data, "network_status")
    G.enum(facility_type, C.FACILITY_TYPES, "facility_type")
    G.enum(network_status, C.NETWORK_STATUSES, "network_status")
    row = store.new_row(
        "facilities",
        {"name": name, "facility_type": facility_type, "network_status": network_status},
    )
    return envelope.created(serialize(row))


@bp.get("/tcm/facilities/<facility_id>")
def read_facility(facility_id):
    G.auth(C.ALL_ROLES)
    return envelope.ok(serialize(G.get_row("facilities", facility_id)))


# ------------------------------------------------------------------- payers
@bp.post("/tcm/payers")
def register_payer():
    G.auth(["ProgramAdmin"])
    data = G.body()
    name = G.req_string(data, "name")
    tcm_covered = G.req_bool(data, "tcm_covered")
    tcm_rate_multiplier = G.opt_number(
        data, "tcm_rate_multiplier", default=1.0, exclusive_min=0, maximum=2.0
    )
    coinsurance_rate = G.opt_number(data, "coinsurance_rate", default=0.2, minimum=0, maximum=0.5)
    basis = G.opt_string(data, "contact_deadline_basis", default="BUSINESS_DAYS")
    G.enum(basis, C.CONTACT_DEADLINE_BASES, "contact_deadline_basis")
    row = store.new_row(
        "payers",
        {
            "name": name,
            "tcm_covered": tcm_covered,
            "tcm_rate_multiplier": tcm_rate_multiplier,
            "coinsurance_rate": coinsurance_rate,
            "contact_deadline_basis": basis,
        },
    )
    return envelope.created(serialize(row))


@bp.get("/tcm/payers/<payer_id>")
def read_payer(payer_id):
    G.auth(C.ALL_ROLES)
    return envelope.ok(serialize(G.get_row("payers", payer_id)))


# --------------------------------------------------------------- navigators
@bp.post("/tcm/navigators")
def register_navigator():
    G.auth(["ProgramAdmin"])
    data = G.body()
    full_name = G.req_string(data, "full_name")
    cap = G.opt_int(
        data, "active_episode_cap", default=C.NAVIGATOR_DEFAULT_ACTIVE_EPISODE_CAP,
        minimum=1, maximum=40,
    )
    cap_policy = G.opt_string(data, "cap_policy", default="COUNT")
    G.enum(cap_policy, C.CAP_POLICIES, "cap_policy")
    row = store.new_row(
        "navigators",
        {
            "full_name": full_name,
            "active_episode_cap": cap,
            "cap_policy": cap_policy,
            "active_episode_count": 0,
            "workload_score": 0,
            "availability_status": "AVAILABLE",
        },
    )
    return envelope.created(serialize(row))


@bp.get("/tcm/navigators/<navigator_id>")
def read_navigator(navigator_id):
    G.auth(C.ALL_ROLES)
    return envelope.ok(serialize(G.get_row("navigators", navigator_id)))
