"""The logical clock, participating insurers and policyholders (PRD 3.1)."""

from flask import Blueprint

import calc
import envelope
import guards
import store
from errors import ApiError

bp = Blueprint("insurers", __name__)


# --- POST /eqp/_clock/set_current_utc ------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    guards.auth(("ProgramAdmin",))
    body = guards.body()
    guards.required(body, ("current_utc",))
    instant = guards.instant(body, "current_utc")
    store.set_clock(instant)
    return envelope.empty_ok()


# --- participating insurers ---------------------------------------------

@bp.post("/insurers")
def create_insurer():
    guards.auth(("ProgramAdmin",))
    body = guards.body()
    guards.required(body, ("name", "naic_code", "market_share_pct"))
    guards.decimal_field(body, "market_share_pct", minimum=0, maximum=100, max_places=2)
    naic = body["naic_code"]
    if not isinstance(naic, str) or not isinstance(body["name"], str):
        raise ApiError("ERR_INVALID_REQUEST")
    guards.unique_violation("insurers", "naic_code", naic)
    row = store.insert("insurers", {
        "name": body["name"],
        "naic_code": naic,
        "market_share_pct": body["market_share_pct"],
        "status": "ACTIVE",
        "compliance_status": "COMPLIANT",
        "offers_recorded_count": 0,
        "undocumented_decline_count": 0,
        "last_take_up_rate_bp": 0,
        "assessment_balance_cents": 0,
        "policies_bound_count": 0,
    })
    return envelope.created(store.public(row))


@bp.get("/insurers/<row_id>")
def read_insurer(row_id):
    role = guards.auth(("ProgramAdmin", "ParticipatingInsurer"))
    row = guards.path_row("insurers", row_id)
    if role == "ParticipatingInsurer":
        guards.owner_must_be(row["id"])
    return envelope.object_response(store.public(row))


@bp.get("/insurers")
def list_insurers():
    guards.auth(("ProgramAdmin",))
    rows = guards.filtered(store.all_rows("insurers"),
                           (("status", "status"),
                            ("compliance_status", "compliance_status")))
    return envelope.list_response(rows)


@bp.post("/insurers/<row_id>/compliance-action")
def compliance_action(row_id):
    guards.auth(("ProgramAdmin",))
    insurer = guards.path_row("insurers", row_id)
    body = guards.body()
    guards.required(body, ("action",))
    action = guards.enum(body, "action", "compliance_action")
    guards.optional_string(body, "reason")
    if action == "SANCTION":
        # Rung 37: SANCTION requires the carrier to be UNDER_REVIEW.
        if insurer["compliance_status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INSURER_NOT_SANCTIONED")
        insurer["compliance_status"] = "SANCTIONED"
    elif action == "REINSTATE":
        # Rung 37: REINSTATE requires the carrier to be SANCTIONED.  It
        # deliberately does not reset undocumented_decline_count.
        if insurer["compliance_status"] != "SANCTIONED":
            raise ApiError("ERR_INSURER_NOT_SANCTIONED")
        insurer["compliance_status"] = "COMPLIANT"
    else:
        # Rung 38: WITHDRAW requires the participation dimension to be ACTIVE.
        if insurer["status"] != "ACTIVE":
            raise ApiError("ERR_INSURER_ALREADY_WITHDRAWN")
        insurer["status"] = "WITHDRAWN"
    store.touch(insurer)
    return envelope.object_response(store.public(insurer))


@bp.post("/insurers/<row_id>/take-up-evaluation")
def take_up_evaluation(row_id):
    guards.auth(("ProgramAdmin",))
    insurer = guards.path_row("insurers", row_id)
    body = guards.body()
    guards.required(body, ("window_start", "window_end"))
    start = guards.instant(body, "window_start")
    end = guards.instant(body, "window_end")
    guards.window(start, end)
    calc.take_up_evaluation(insurer, start, end)
    return envelope.object_response(store.public(insurer))


# --- policyholders --------------------------------------------------------

@bp.post("/policyholders")
def create_policyholder():
    guards.auth(("ProgramAdmin", "ParticipatingInsurer"))
    body = guards.body()
    guards.required(body, ("full_name", "email", "county_code"))
    for field in ("full_name", "email", "county_code"):
        if not isinstance(body[field], str):
            raise ApiError("ERR_INVALID_REQUEST")
    campaign = guards.optional_string(body, "outreach_campaign_code", "NONE")
    guards.unique_violation("policyholders", "email", body["email"])
    row = store.insert("policyholders", {
        "full_name": body["full_name"],
        "email": body["email"],
        "county_code": body["county_code"],
        "outreach_campaign_code": campaign,
        "status": "ACTIVE",
    })
    return envelope.created(store.public(row))


@bp.get("/policyholders/<row_id>")
def read_policyholder(row_id):
    role = guards.auth(("ProgramAdmin", "ParticipatingInsurer", "Policyholder"))
    row = guards.path_row("policyholders", row_id)
    if role == "Policyholder":
        guards.owner_must_be(row["id"])
    return envelope.object_response(store.public(row))


@bp.get("/policyholders")
def list_policyholders():
    guards.auth(("ProgramAdmin",))
    rows = guards.filtered(store.all_rows("policyholders"),
                           (("county_code", "county_code"),
                            ("outreach_campaign_code", "outreach_campaign_code"),
                            ("status", "status")))
    return envelope.list_response(rows)
