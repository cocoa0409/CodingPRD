"""Firmware campaigns and rollouts."""

from flask import Blueprint

import calc
import services as svc
from auth import ADMIN, CARE_OPS, FIRMWARE_ENG, PATIENT, authorize, require_owner
from bodyspec import Body
from common import field, listed, patient_of_device
from errors import ApiError
from resp import created, ok
from routes_order import MODELS
from store import bump, db, now, table_rows

bp = Blueprint("firmware", __name__)

FAILURE_CODES = ("VERSION_DRIFT", "POWER_LOSS", "CHECKSUM", "TIMEOUT")
FAILURE_PAUSE_THRESHOLD = 25.0


def installing_count(campaign_id):
    return sum(1 for r in db.firmware_rollouts.values()
               if r.get("firmware_campaign_id") == campaign_id
               and r.get("status") == "INSTALLING")


def in_window(campaign):
    start = campaign.get("window_start_utc")
    end = campaign.get("window_end_utc")
    if start is None or end is None:
        return False
    return start <= now() <= end


# ----------------------------------------------------------- FirmwareCampaign
@bp.post("/firmware-campaigns")
def create_campaign():
    authorize(FIRMWARE_ENG)
    body = Body()
    code = body.string("campaign_code", min_len=1)
    model = body.enum("model", MODELS)
    from_version = body.string("from_version", min_len=1)
    to_version = body.string("to_version", min_len=1)
    window_start = body.datetime("window_start_utc")
    window_end = body.datetime("window_end_utc")
    batch_size = body.integer("batch_size", required=False, default=3, minimum=1, maximum=100)
    max_installs = body.integer("max_concurrent_installs", required=False, default=2,
                                minimum=1, maximum=50)
    mandatory = body.boolean("is_mandatory_safety", required=False, default=False)
    body.finish()
    for row in db.firmware_campaigns.values():
        if row["campaign_code"] == code:
            raise ApiError("ERR_DUPLICATE_KEY")
    campaign = svc.new_row(db.firmware_campaigns, campaign_code=code, model=model,
                           from_version=from_version, to_version=to_version,
                           status="DRAFT", window_start_utc=window_start,
                           window_end_utc=window_end, max_concurrent_installs=max_installs,
                           batch_size=batch_size, is_mandatory_safety=mandatory,
                           rollout_count=0, installed_count=0, failure_rate_pct=0.0)
    return created(campaign)


@bp.get("/firmware-campaigns")
def list_campaigns():
    authorize(FIRMWARE_ENG, ADMIN, CARE_OPS)
    return listed(table_rows(db.firmware_campaigns),
                  {"model": field("model"), "status": field("status")},
                  owner_field=None)


@bp.get("/firmware-campaigns/<campaign_id>")
def get_campaign(campaign_id):
    authorize(FIRMWARE_ENG, ADMIN, CARE_OPS)
    campaign = svc.find(db.firmware_campaigns, campaign_id)
    return ok(campaign)


@bp.post("/firmware-campaigns/<campaign_id>/schedule")
def schedule_campaign(campaign_id):
    authorize(FIRMWARE_ENG)
    campaign = svc.find(db.firmware_campaigns, campaign_id)
    svc.ensure_state(campaign, "status", ("DRAFT",), "firmware_campaigns")
    if campaign["window_start_utc"] >= campaign["window_end_utc"]:
        raise ApiError("ERR_VALIDATION", "window_start_utc must precede window_end_utc")
    if campaign["to_version"] == campaign["from_version"]:
        raise ApiError("ERR_VALIDATION", "to_version must differ from from_version")
    if calc.campaign_window_conflict(campaign):
        raise ApiError("ERR_CAMPAIGN_WINDOW_CONFLICT")
    campaign["status"] = "SCHEDULED"
    bump(campaign)
    return ok(campaign)


@bp.post("/firmware-campaigns/<campaign_id>/advance")
def advance_campaign(campaign_id):
    authorize(FIRMWARE_ENG)
    campaign = svc.find(db.firmware_campaigns, campaign_id)
    svc.ensure_state(campaign, "status", ("SCHEDULED", "ROLLING"), "firmware_campaigns")
    if campaign["status"] == "SCHEDULED":
        if not in_window(campaign):
            raise ApiError("ERR_INVALID_STATE", "the maintenance window is not open")
    else:
        if now() > campaign["window_end_utc"]:
            raise ApiError("ERR_INVALID_STATE", "the maintenance window has closed")
        if installing_count(campaign["id"]) >= int(campaign["max_concurrent_installs"]):
            raise ApiError("ERR_MAX_CONCURRENT_INSTALLS_REACHED")
    candidates = calc.eligible_devices(campaign)
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_DEVICES")
    rank = 0
    for device in candidates[:int(campaign["batch_size"])]:
        rank += 1
        svc.new_row(db.firmware_rollouts, firmware_campaign_id=campaign["id"],
                    device_id=device["id"], status="PENDING", selection_rank=rank,
                    from_version_observed=device.get("firmware_version"),
                    attempt_count=0, failure_code=None, installed_at=None)
    campaign["status"] = "ROLLING"
    svc.recompute_campaign_counters(campaign)
    return ok(campaign)


@bp.post("/firmware-campaigns/<campaign_id>/pause")
def pause_campaign(campaign_id):
    authorize(FIRMWARE_ENG)
    campaign = svc.find(db.firmware_campaigns, campaign_id)
    svc.ensure_state(campaign, "status", ("ROLLING",), "firmware_campaigns")
    campaign["status"] = "PAUSED"
    bump(campaign)
    return ok(campaign)


@bp.post("/firmware-campaigns/<campaign_id>/resume")
def resume_campaign(campaign_id):
    authorize(FIRMWARE_ENG)
    campaign = svc.find(db.firmware_campaigns, campaign_id)
    svc.ensure_state(campaign, "status", ("PAUSED",), "firmware_campaigns")
    if float(campaign.get("failure_rate_pct") or 0) > FAILURE_PAUSE_THRESHOLD:
        raise ApiError("ERR_INVALID_STATE", "failure_rate_pct exceeds 25.0")
    if now() > campaign["window_end_utc"]:
        raise ApiError("ERR_INVALID_STATE", "the maintenance window has closed")
    campaign["status"] = "ROLLING"
    bump(campaign)
    return ok(campaign)


@bp.post("/firmware-campaigns/<campaign_id>/complete")
def complete_campaign(campaign_id):
    authorize(FIRMWARE_ENG)
    campaign = svc.find(db.firmware_campaigns, campaign_id)
    svc.ensure_state(campaign, "status", ("ROLLING",), "firmware_campaigns")
    for rollout in db.firmware_rollouts.values():
        if rollout.get("firmware_campaign_id") != campaign["id"]:
            continue
        if rollout.get("status") in ("PENDING", "OFFERED", "INSTALLING"):
            raise ApiError("ERR_DEPENDENT_STATE_NOT_READY")
    campaign["status"] = "COMPLETED"
    bump(campaign)
    return ok(campaign)


@bp.post("/firmware-campaigns/<campaign_id>/abort")
def abort_campaign(campaign_id):
    authorize(FIRMWARE_ENG)
    campaign = svc.find(db.firmware_campaigns, campaign_id)
    svc.ensure_state(campaign, "status", ("SCHEDULED", "ROLLING", "PAUSED"),
                     "firmware_campaigns")
    if campaign["status"] == "SCHEDULED" and int(campaign.get("rollout_count") or 0) != 0:
        raise ApiError("ERR_INVALID_STATE", "a scheduled campaign with rollouts may not abort")
    for rollout in table_rows(db.firmware_rollouts):
        if rollout.get("firmware_campaign_id") != campaign["id"]:
            continue
        if rollout.get("status") == "PENDING" or (
                rollout.get("status") == "OFFERED" and not campaign.get("is_mandatory_safety")):
            rollout["status"] = "CANCELLED_INELIGIBLE"
            bump(rollout)
    campaign["status"] = "ABORTED"
    svc.recompute_campaign_counters(campaign)
    return ok(campaign)


@bp.post("/firmware-campaigns/<campaign_id>/manual-enrollments")
def manual_enrollment(campaign_id):
    authorize(FIRMWARE_ENG)
    campaign = svc.find(db.firmware_campaigns, campaign_id)
    body = Body()
    device_id = body.string("device_id", min_len=1)
    expected = body.integer("expected_device_version")
    body.finish()
    device = svc.ref(db.devices, device_id)
    if expected != int(device["version"]):
        raise ApiError("ERR_STALE_DEVICE_VERSION")
    if not campaign.get("is_mandatory_safety"):
        plan = svc.plan_for_device(device)
        if plan is None or plan.get("status") not in ("ACTIVE", "TRIALING") or \
                not plan.get("firmware_auto_update_enabled"):
            raise ApiError("ERR_AUTO_UPDATE_NOT_CONSENTED")
    rollout = svc.new_row(db.firmware_rollouts, firmware_campaign_id=campaign["id"],
                          device_id=device["id"], status="PENDING",
                          selection_rank=int(campaign.get("rollout_count") or 0) + 1,
                          from_version_observed=device.get("firmware_version"),
                          attempt_count=0, failure_code=None, installed_at=None)
    bump(device)
    svc.recompute_campaign_counters(campaign)
    return created(rollout)


@bp.get("/firmware-campaigns/<campaign_id>/rollouts")
def list_campaign_rollouts(campaign_id):
    authorize(FIRMWARE_ENG, ADMIN, CARE_OPS)
    campaign = svc.find(db.firmware_campaigns, campaign_id)
    rows = [r for r in table_rows(db.firmware_rollouts)
            if r["firmware_campaign_id"] == campaign["id"]]
    return listed(rows, {"status": field("status")}, owner_field=None)


# ------------------------------------------------------------ FirmwareRollout
@bp.get("/firmware-rollouts")
def list_rollouts():
    actor = authorize(PATIENT, FIRMWARE_ENG, ADMIN, CARE_OPS)
    rows = table_rows(db.firmware_rollouts)
    if actor.is_patient:
        rows = [r for r in rows if patient_of_device(r["device_id"]) == actor.user_id]
    return listed(rows,
                  {"firmware_campaign_id": field("firmware_campaign_id"),
                   "device_id": field("device_id"), "status": field("status")},
                  owner_field=None)


@bp.post("/firmware-rollouts/<rollout_id>/offer")
def offer_rollout(rollout_id):
    authorize(FIRMWARE_ENG)
    rollout = svc.find(db.firmware_rollouts, rollout_id)
    svc.ensure_state(rollout, "status", ("PENDING",), "firmware_rollouts")
    campaign = db.firmware_campaigns.get(rollout["firmware_campaign_id"])
    if campaign is None or campaign.get("status") != "ROLLING":
        raise ApiError("ERR_DEPENDENT_STATE_NOT_READY")
    if not in_window(campaign):
        raise ApiError("ERR_INVALID_STATE", "the maintenance window is not open")
    if not campaign.get("is_mandatory_safety"):
        plan = svc.plan_for_device(db.devices.get(rollout["device_id"]))
        # §3.9: the offer "requires ... either the device's plan to be ACTIVE or TRIALING or
        # the campaign's is_mandatory_safety to be true" — a sibling-entity precondition, so
        # §2.9 rule 24 governs it.
        if plan is None or plan.get("status") not in ("ACTIVE", "TRIALING"):
            raise ApiError("ERR_DEPENDENT_STATE_NOT_READY")
        # §2.9 rule 33: the subscriber's consent flag, checked after rule 24.
        if not plan.get("firmware_auto_update_enabled"):
            raise ApiError("ERR_AUTO_UPDATE_NOT_CONSENTED")
    rollout["status"] = "OFFERED"
    bump(rollout)
    return ok(rollout)


@bp.post("/firmware-rollouts/<rollout_id>/install")
def install_rollout(rollout_id):
    actor = authorize(PATIENT)
    rollout = svc.find(db.firmware_rollouts, rollout_id)
    require_owner(actor, patient_of_device(rollout["device_id"]))
    svc.ensure_state(rollout, "status", ("OFFERED", "FAILED"), "firmware_rollouts")
    campaign = db.firmware_campaigns.get(rollout["firmware_campaign_id"])
    device = db.devices.get(rollout["device_id"])
    if rollout["status"] == "FAILED":
        if campaign is None or campaign.get("status") != "ROLLING":
            raise ApiError("ERR_DEPENDENT_STATE_NOT_READY")
        if int(rollout.get("attempt_count") or 0) >= 3:
            raise ApiError("ERR_INSTALL_ATTEMPTS_EXHAUSTED")
    if campaign is not None and \
            installing_count(campaign["id"]) >= int(campaign["max_concurrent_installs"]):
        raise ApiError("ERR_MAX_CONCURRENT_INSTALLS_REACHED")
    if device is None or device.get("status") != "WITH_PATIENT":
        raise ApiError("ERR_DEPENDENT_STATE_NOT_READY")
    rollout["status"] = "INSTALLING"
    rollout["attempt_count"] = int(rollout.get("attempt_count") or 0) + 1
    bump(rollout)
    return ok(rollout)


@bp.post("/firmware-rollouts/<rollout_id>/rollback")
def rollback_rollout(rollout_id):
    authorize(FIRMWARE_ENG)
    rollout = svc.find(db.firmware_rollouts, rollout_id)
    svc.ensure_state(rollout, "status", ("FAILED",), "firmware_rollouts")
    if int(rollout.get("attempt_count") or 0) < 3 and \
            rollout.get("failure_code") != "CHECKSUM":
        raise ApiError("ERR_INVALID_STATE",
                       "rollback requires three attempts or a CHECKSUM failure")
    device = db.devices.get(rollout["device_id"])
    rollout["status"] = "ROLLED_BACK"
    bump(rollout)
    if device is not None:
        device["firmware_version"] = rollout.get("from_version_observed")
        bump(device)
        if rollout.get("failure_code") in ("CHECKSUM", "POWER_LOSS"):
            from routes_repair import open_repair
            open_repair(device, "FIRMWARE_BRICK")
    campaign = db.firmware_campaigns.get(rollout["firmware_campaign_id"])
    if campaign is not None:
        svc.recompute_campaign_counters(campaign)
    return ok(rollout)
