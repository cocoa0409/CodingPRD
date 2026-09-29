"""Support person passes (PRD 3.9): 6 endpoints."""

from flask import Blueprint

import calc
import clock
import common
import const
import rev
import store
from fields import q_enum, q_str, s_bool, s_dt, s_enum, s_str
from pipeline import begin, fail, need, run_checks
from store import S

bp = Blueprint("passes", __name__)

READ_ROLES = ["PatientAccessCoordinator", "ChargeNurse", "BedsideNurse",
              "PerinatalSafetyOfficer"]


@bp.post("/support-person-passes")
def issue_pass():
    ctx = begin(
        roles=["PatientAccessCoordinator", "ChargeNurse"],
        body_refs=[("encounter_id", "encounter")],
        specs=[s_str("encounter_id", required=True),
               s_str("person_name", required=True, min_len=1, max_len=120),
               s_enum("credential_type", const.CREDENTIAL_TYPES, required=True),
               s_dt("doula_certification_expires_at"),
               s_bool("or_credentialed", default=False)],
    )
    enc = ctx.r["encounter"]
    credential = ctx.v["credential_type"]
    expires_at = ctx.v["doula_certification_expires_at"]
    if credential == "DOULA_CERTIFIED":
        if expires_at is None:
            fail("ERR_INVALID_FIELD_VALUE",
                 "doula_certification_expires_at is required for a doula pass.")
    elif ctx.v.has("doula_certification_expires_at"):
        fail("ERR_INVALID_FIELD_VALUE",
             "doula_certification_expires_at is only valid for a doula pass.")

    def phase():
        need(enc["labor_phase"] not in const.TERMINAL_PHASES,
             "ERR_ENCOUNTER_PHASE_TERMINAL")

    def credential_live():
        if credential != "DOULA_CERTIFIED":
            return
        need(expires_at > clock.now(), "ERR_DOULA_CREDENTIAL_EXPIRED")

    run_checks([(8.01, phase), (11.6, credential_live)])

    instant = clock.now()
    record = store.new_record({
        "encounter_id": enc["id"],
        "person_name": ctx.v["person_name"],
        "credential_type": credential,
        "doula_certification_expires_at": expires_at,
        "or_credentialed": ctx.v["or_credentialed"],
        "status": "ISSUED",
        "checked_in_at": None,
        "checked_out_at": None,
        "valid_until": clock.plus_hours(instant, const.PASS_VALID_HOURS),
        "reentry_count": 0,
    })
    S.passes[record["id"]] = record
    # An issued pass occupies nothing, so no occupancy recomputation here.
    return common.created("passes", record)


@bp.get("/support-person-passes")
def list_passes():
    begin(roles=READ_ROLES)
    encounter_id = q_str("encounter_id")
    status = q_enum("status", const.PASS_STATUSES)
    credential = q_enum("credential_type", const.CREDENTIAL_TYPES)
    found = [p for p in S.passes.values()
             if common.match(p, "encounter_id", encounter_id)
             and common.match(p, "status", status)
             and common.match(p, "credential_type", credential)]
    return common.listing("passes", found, [("created_at", "asc")])


@bp.get("/support-person-passes/<pass_id>")
def read_pass(pass_id):
    ctx = begin(roles=READ_ROLES, path=[("pass", pass_id)])
    return common.single("passes", ctx.p["pass"])


@bp.post("/support-person-passes/<pass_id>/check-in")
def check_in(pass_id):
    ctx = begin(roles=["PatientAccessCoordinator"], path=[("pass", pass_id)])
    record = ctx.p["pass"]
    enc = S.encounters.get(record["encounter_id"])
    or_doula = (record["credential_type"] == "DOULA_CERTIFIED"
                and record.get("or_credentialed") is True)

    def declared():
        need(record["status"] in ("ISSUED", "CHECKED_OUT"),
             "ERR_INVALID_STATE_TRANSITION")

    def phase():
        need(enc["labor_phase"] not in const.TERMINAL_PHASES,
             "ERR_ENCOUNTER_PHASE_TERMINAL")

    def reentry():
        if record["status"] != "CHECKED_OUT":
            return
        need((record.get("reentry_count") or 0) < const.REENTRY_LIMIT,
             "ERR_SUPPORT_REENTRY_LIMIT_REACHED")

    def not_expired():
        need(clock.now() < record["valid_until"], "ERR_SUPPORT_PASS_EXPIRED")

    def doula_live():
        if record["credential_type"] != "DOULA_CERTIFIED":
            return
        expires_at = record.get("doula_certification_expires_at")
        need(expires_at is not None and expires_at > clock.now(),
             "ERR_DOULA_CREDENTIAL_EXPIRED")

    def theatre():
        if or_doula:
            return                       # the one visitor allowed into theatre
        for event in calc.rows("cesareans", encounter_id=enc["id"]):
            need(event["status"] not in const.CESAREAN_OR_ACTIVE,
                 "ERR_VISITATION_RESTRICTED_BY_PROCEDURE")

    def occupancy():
        # Evaluated last of all: landing exactly on the allowance is admitted.
        allowance = calc.support_allowance(enc)
        need(calc.checked_in_count(enc["id"]) + 1 <= allowance,
             "ERR_SUPPORT_OCCUPANCY_EXCEEDED")

    run_checks([(8, declared), (8.01, phase), (8.10, reentry),
                (11.6, not_expired), (11.61, doula_live), (11.62, theatre),
                (15, occupancy)])

    if record["status"] == "CHECKED_OUT":
        record["reentry_count"] = (record.get("reentry_count") or 0) + 1
    record["status"] = "CHECKED_IN"
    record["checked_in_at"] = clock.now()
    record["checked_out_at"] = None
    rev.touch(record)
    return common.single("passes", record)


@bp.post("/support-person-passes/<pass_id>/check-out")
def check_out(pass_id):
    ctx = begin(roles=["PatientAccessCoordinator"], path=[("pass", pass_id)])
    record = ctx.p["pass"]

    def declared():
        need(record["status"] == "CHECKED_IN", "ERR_INVALID_STATE_TRANSITION")

    run_checks([(8, declared)])

    record["status"] = "CHECKED_OUT"
    record["checked_out_at"] = clock.now()
    rev.touch(record)
    return common.single("passes", record)


@bp.post("/support-person-passes/<pass_id>/revoke")
def revoke_pass(pass_id):
    ctx = begin(roles=["ChargeNurse"], path=[("pass", pass_id)])
    record = ctx.p["pass"]

    def declared():
        need(record["status"] in ("ISSUED", "CHECKED_IN", "CHECKED_OUT"),
             "ERR_INVALID_STATE_TRANSITION")

    run_checks([(8, declared)])

    record["status"] = "REVOKED"
    rev.touch(record)
    return common.single("passes", record)
