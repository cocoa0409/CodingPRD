"""Admission, the day ledger and the episode lifecycle (PRD 3.2, 3.9)."""

from datetime import timedelta

from flask import Blueprint

import calc
import clock
import derived
import envelope
import errors
import ladder
import serializers
import store
from domain import compliance
from domain import episodes as episode_cascades
from errors import fail
from routes.common import apply_filter, endpoint
from routes.referrals import latest_assessment
from store import DB

bp = Blueprint("episodes", __name__)

PROGRAM_TRACKS = ("CMS_WAIVER", "FEE_FOR_SERVICE")

EPISODE_READ_ROLES = [
    "ProgramAdmin", "AdmittingPhysician", "FieldNurse", "CommunityParamedic",
    "LogisticsCoordinator", "PharmacyAuthorizer", "BillingAnalyst", "Patient",
]
EPISODE_LIST_ROLES = [
    "ProgramAdmin", "AdmittingPhysician", "FieldNurse", "CommunityParamedic",
    "LogisticsCoordinator", "BillingAnalyst",
]
TERMINAL_DELIVERY_STATES = ("DELIVERED", "FAILED", "CANCELLED")


@endpoint(bp, "/episodes", ["POST"], ["AdmittingPhysician"])
def create_episode(caller):
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, ["patient_id", "referral_id", "program_track"])
    # rung 4b
    ladder.check_enum(body, "program_track", PROGRAM_TRACKS)
    # rung 5 -- declared resource-type order: patient, then referral
    patient = ladder.body_patient(body)
    referral = ladder.body_referral(body)
    # rung 7
    ladder.require_state(referral["status"] == "ELIGIBLE")

    # rung 9 -- service radius is re-checked, then the evaluation window
    if calc.to_decimal(patient["home_distance_km"]) > calc.SERVICE_RADIUS_KM:
        fail(errors.ERR_OUTSIDE_SERVICE_RADIUS)
    assessment = latest_assessment(referral["id"])
    admitted_dt = clock.now_dt()
    window_start = admitted_dt - timedelta(hours=calc.PHYSICIAN_EVAL_WINDOW_HOURS)
    if assessment is None:
        fail(errors.ERR_EVAL_WINDOW_EXPIRED)
    eval_dt = clock.parse_iso(assessment["in_person_eval_at"])
    if eval_dt is None or eval_dt < window_start or eval_dt > admitted_dt:
        fail(errors.ERR_EVAL_WINDOW_EXPIRED)

    episode = store.make_row("episodes", {
        "patient_id": patient["id"],
        "referral_id": referral["id"],
        "program_track": body["program_track"],
        "acuity": referral["acuity"],
        "status": "ACTIVE",
        "admitted_at": clock.now_raw(),
        "physician_eval_at": assessment["in_person_eval_at"],
        "returned_at": None,
        "discharged_at": None,
        "readmission_count": 0,
        "med_rec_signed": False,
        "med_rec_signed_by_user_id": None,
        "last_deployed_kit_id": None,
    })
    referral["status"] = "ADMITTED"
    store.touch(referral)
    patient["status"] = "IN_PROGRAM"
    store.touch(patient)
    compliance.mint_record(episode, clock.today_date())
    return envelope.ObjResult(episode, serializers.episode, 201)


@endpoint(bp, "/episodes/<episode_id>", ["GET"], EPISODE_READ_ROLES)
def get_episode(caller, episode_id):
    row = ladder.path_row("episodes", episode_id)
    return envelope.ObjResult(row, serializers.episode, 200)


@endpoint(bp, "/episodes", ["GET"], EPISODE_LIST_ROLES)
def list_episodes(caller):
    limit, offset = ladder.pagination_params()
    rows = list(DB.episodes.values())
    rows = apply_filter(rows, "patient_id")
    rows = apply_filter(rows, "referral_id")
    rows = apply_filter(rows, "status")
    return envelope.ListResult(store.ordered(rows), serializers.episode, limit, offset)


@endpoint(bp, "/episodes/<episode_id>/ledger", ["GET"],
          ["ProgramAdmin", "AdmittingPhysician", "BillingAnalyst"])
def get_ledger(caller, episode_id):
    row = ladder.path_row("episodes", episode_id)
    return envelope.RawResult(serializers.episode_ledger(row), 200)


@endpoint(bp, "/episodes/<episode_id>/sign-med-rec", ["POST"], ["AdmittingPhysician"])
def sign_med_rec(caller, episode_id):
    # rung 3 -- there is deliberately no episode-state gate on this operation.
    episode = ladder.path_row("episodes", episode_id)
    episode["med_rec_signed"] = True
    episode["med_rec_signed_by_user_id"] = caller.user_id
    store.touch(episode)
    return envelope.ObjResult(episode, serializers.episode, 200)


@endpoint(bp, "/episodes/<episode_id>/begin-discharge", ["POST"], ["AdmittingPhysician"])
def begin_discharge(caller, episode_id):
    # rung 3
    episode = ladder.path_row("episodes", episode_id)
    # rung 7
    ladder.require_state(episode["status"] == "ACTIVE")
    ladder.require_state(derived.episode_open_escalation_count(episode_id) == 0)
    episode_cascades.begin_discharge(episode)
    return envelope.ObjResult(episode, serializers.episode, 200)


@endpoint(bp, "/episodes/<episode_id>/discharge", ["POST"], ["AdmittingPhysician"])
def discharge(caller, episode_id):
    # rung 3
    episode = ladder.path_row("episodes", episode_id)
    # rung 7
    ladder.require_state(episode["status"] == "DISCHARGE_PENDING")
    # rung 15 -- three gates in a fixed order
    if not episode["med_rec_signed"]:
        fail(errors.ERR_MED_REC_UNSIGNED)
    for order in derived.episode_delivery_orders(episode_id):
        if order["status"] not in TERMINAL_DELIVERY_STATES:
            fail(errors.ERR_DELIVERY_NOT_TERMINAL)
    kit_id = episode.get("last_deployed_kit_id")
    if kit_id is not None:
        for component in derived.kit_components(kit_id):
            if component["reconciliation_status"] in ("DEPLOYED", "PENDING_RECONCILIATION"):
                fail(errors.ERR_RECONCILIATION_INCOMPLETE)

    episode_cascades.discharge(episode)
    return envelope.ObjResult(episode, serializers.episode, 200)


@endpoint(bp, "/episodes/<episode_id>/readmit", ["POST"], ["AdmittingPhysician"])
def readmit(caller, episode_id):
    # rung 3
    episode = ladder.path_row("episodes", episode_id)
    # rung 7
    ladder.require_state(episode["status"] == "RETURNED_TO_FACILITY")
    available = [k for k in DB.kits.values() if k["status"] == "AVAILABLE"]
    ladder.require_state(len(available) > 0)
    episode_cascades.readmit(episode)
    return envelope.ObjResult(episode, serializers.episode, 200)


@endpoint(bp, "/episodes/<episode_id>/compliance-days", ["GET"],
          ["ProgramAdmin", "AdmittingPhysician", "BillingAnalyst"])
def list_compliance_days(caller, episode_id):
    # rung 3
    ladder.path_row("episodes", episode_id)
    limit, offset = ladder.pagination_params()
    rows = [r for r in DB.compliance_days.values() if r["episode_id"] == episode_id]
    rows = apply_filter(rows, "status")
    rows = apply_filter(rows, "service_date")
    return envelope.ListResult(store.ordered(rows), serializers.compliance_day, limit, offset)
