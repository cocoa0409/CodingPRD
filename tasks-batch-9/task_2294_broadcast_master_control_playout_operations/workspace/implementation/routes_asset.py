"""Assets, delivery, QC reports, waivers and retraction (PRD 3.4)."""
from flask import Blueprint, request

import auth
import calc
import cascades
import store
import timeutil
import views
from constants import (ASSET_SOURCES, ASSET_STATUSES, AUDIO_CONFIGS, DEFECT_CODES,
                       DELIVERY_GRACE_SECONDS, FRAME_RATES, QC_BASES, RESOLUTION_CLASSES,
                       VIDEO_CODECS, WAIVER_JUSTIFICATION_MIN_CHARS, WAIVER_MIN_SCORE)
from errors import fail
from response import created, listing, ok
from validate import F, enum_filter, validate

bp = Blueprint("asset", __name__)

REGISTRARS = ["QCTechnician", "TrafficCoordinator", "StationAdmin"]
ASSET_READERS = ["MasterControlOperator", "QCTechnician", "ProgramDirector",
                 "TrafficCoordinator", "ComplianceOfficer", "StationAdmin"]
QC_READERS = ["MasterControlOperator", "QCTechnician", "ProgramDirector",
              "ComplianceOfficer", "StationAdmin"]


def governing_report(asset_id, basis):
    reports = [r for r in store.rows(store.qc_reports)
               if r["asset_id"] == asset_id and r["basis"] == basis and not r["superseded"]]
    return reports[-1] if reports else None


# --- registration and delivery --------------------------------------------

@bp.post("/assets")
def create_asset():
    auth.authorize(REGISTRARS)
    body = validate(request.get_json(silent=True), [
        F("house_number", "str", required=True, min_len=1, max_len=32),
        F("title", "str", required=True, min_len=1),
        F("source", "enum", required=True, values=ASSET_SOURCES),
        F("expected_duration_seconds", "int", required=True, minimum=1),
        F("delivery_deadline_utc", "ts", required=True),
        F("required_resolution_class", "enum", required=True, values=RESOLUTION_CLASSES),
        F("captions_required", "bool", required=True),
    ])
    for existing in store.rows(store.assets):
        if existing["house_number"] == body["house_number"]:
            fail("ERR_DUPLICATE_HOUSE_NUMBER",
                 "house_number %s has already been registered." % body["house_number"])
    rec = store.base()
    rec.update({
        "house_number": body["house_number"],
        "title": body["title"],
        "source": body["source"],
        "expected_duration_seconds": int(body["expected_duration_seconds"]),
        "delivery_deadline_utc": body["delivery_deadline_utc"],
        "required_resolution_class": body["required_resolution_class"],
        "captions_required": bool(body["captions_required"]),
        "received_utc": None,
        "measured_duration_seconds": None,
        "video_codec": None,
        "delivered_resolution_class": None,
        "frame_rate": None,
        "audio_loudness_lkfs": None,
        "audio_channel_config": None,
        "caption_present": None,
        "caption_language": None,
        "late_delivery": None,
        "technical_score_ingest": None,
        "technical_score_aircheck": None,
        "qc_verdict": None,
        "waived_by_operator_id": None,
        "waiver_justification": None,
        "status": "EXPECTED",
    })
    store.add(store.assets, rec)
    return created(views.plain(rec))


@bp.get("/assets/<ident>")
def read_asset(ident):
    auth.authorize(ASSET_READERS, mutating=False)
    return ok(views.plain(auth.asset(ident)))


@bp.get("/assets")
def list_assets():
    auth.authorize(ASSET_READERS, mutating=False)
    rows = store.rows(store.assets)
    status = enum_filter("status", ASSET_STATUSES)
    if status:
        rows = [r for r in rows if r["status"] == status]
    for name in ("house_number", "waived_by_operator_id"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if str(r.get(name)) == value]
    return listing(rows, views.plain)


@bp.post("/assets/<ident>/delivery")
def record_delivery(ident):
    auth.authorize(REGISTRARS)
    body = validate(request.get_json(silent=True), [
        F("received_utc", "ts", required=True),
        F("measured_duration_seconds", "int", required=True, minimum=1),
        F("video_codec", "enum", required=True, values=VIDEO_CODECS),
        F("delivered_resolution_class", "enum", required=True, values=RESOLUTION_CLASSES),
        F("frame_rate", "enum_number", required=True, values=FRAME_RATES),
        F("audio_loudness_lkfs", "lkfs", required=True),
        F("audio_channel_config", "enum", required=True, values=AUDIO_CONFIGS),
        F("caption_present", "bool", required=True),
        F("caption_language", "str"),
    ])
    asset = auth.asset(ident)
    now = store.clock()
    received = body["received_utc"]
    if timeutil.sec(received) > timeutil.sec(now):
        fail("ERR_EVENT_TIMESTAMP_IN_FUTURE", "received_utc may not lie in the future.")
    # The deadline is answered before the status precondition: PRD 3.4 says a delivery
    # attempted once the clock is past deadline-plus-grace is refused with
    # ERR_DELIVERY_DEADLINE_PASSED precisely "because by then the clock checkpoint
    # will have swept the asset to EXPIRED", so the expiry must not mask the code.
    limit = timeutil.plus(asset["delivery_deadline_utc"], DELIVERY_GRACE_SECONDS)
    if timeutil.sec(now) > timeutil.sec(limit) or timeutil.sec(received) > timeutil.sec(limit):
        fail("ERR_DELIVERY_DEADLINE_PASSED",
             "The delivery deadline plus the one-hour grace window has passed.")
    if asset["status"] not in ("EXPECTED", "QC_FAILED"):
        fail("ERR_ASSET_INVALID_STATE",
             "Delivery is only legal from EXPECTED or QC_FAILED.")

    asset["received_utc"] = received
    asset["measured_duration_seconds"] = int(body["measured_duration_seconds"])
    asset["video_codec"] = body["video_codec"]
    asset["delivered_resolution_class"] = body["delivered_resolution_class"]
    asset["frame_rate"] = body["frame_rate"]
    asset["audio_loudness_lkfs"] = body["audio_loudness_lkfs"]
    asset["audio_channel_config"] = body["audio_channel_config"]
    asset["caption_present"] = bool(body["caption_present"])
    asset["caption_language"] = body.get("caption_language")
    asset["late_delivery"] = timeutil.sec(received) > timeutil.sec(asset["delivery_deadline_utc"])
    asset["technical_score_ingest"] = None
    asset["technical_score_aircheck"] = None
    asset["qc_verdict"] = None
    asset["status"] = "RECEIVED"
    store.bump(asset)
    return ok(views.plain(asset))


# --- quality control -------------------------------------------------------

@bp.post("/assets/<ident>/qc-reports")
def submit_report(ident):
    auth.authorize(["QCTechnician", "StationAdmin"], cert=True)
    body = validate(request.get_json(silent=True), [
        F("expected_asset_version", "int", required=True, minimum=0),
        F("inspected_by_operator_id", "str", required=True),
        F("basis", "enum", required=True, values=QC_BASES),
        F("defect_codes", "enum_array", required=True, values=DEFECT_CODES),
        F("measured_duration_seconds", "int", required=True, minimum=1),
        F("audio_loudness_lkfs", "lkfs"),
        F("notes", "str"),
    ])
    asset = auth.asset(ident)
    inspector = auth.operator_ref(body["inspected_by_operator_id"])
    if int(body["expected_asset_version"]) != int(asset["version"]):
        fail("ERR_STALE_ASSET_VERSION", "The asset version has moved on.")
    basis = body["basis"]
    if basis == "INGEST" and asset["status"] != "RECEIVED":
        fail("ERR_ASSET_INVALID_STATE", "An ingest report requires the asset to be RECEIVED.")
    if basis == "AIR_CHECK" and asset["status"] not in ("QC_PASSED", "QC_WAIVED"):
        fail("ERR_ASSET_INVALID_STATE",
             "An air-check report requires the asset to be QC_PASSED or QC_WAIVED.")
    if inspector["role_class"] != "QC":
        fail("ERR_OPERATOR_ROLE_CLASS_INVALID", "The inspector must hold the QC role class.")
    if inspector["status"] != "ACTIVE":
        fail("ERR_OPERATOR_SUSPENDED", "The named inspector is suspended.")

    figures = calc.score_report(asset, basis, body["defect_codes"],
                               int(body["measured_duration_seconds"]))
    for earlier in store.rows(store.qc_reports):
        if earlier["asset_id"] == asset["id"] and earlier["basis"] == basis \
                and not earlier["superseded"]:
            earlier["superseded"] = True

    rec = store.base(versioned=False)
    rec.update({
        "asset_id": asset["id"],
        "inspected_by_operator_id": inspector["id"],
        "basis": basis,
        "defect_codes": list(body["defect_codes"]),
        "measured_duration_seconds": int(body["measured_duration_seconds"]),
        "defect_penalty_points": figures["defect_penalty_points"],
        "duration_penalty_points": figures["duration_penalty_points"],
        "loudness_penalty_points": figures["loudness_penalty_points"],
        "fault_penalty_points": figures["fault_penalty_points"],
        "technical_score": figures["technical_score"],
        "verdict": figures["verdict"],
        "superseded": False,
        "notes": body.get("notes"),
    })
    store.add(store.qc_reports, rec)

    if basis == "INGEST":
        asset["technical_score_ingest"] = figures["technical_score"]
        asset["qc_verdict"] = figures["verdict"]
        if figures["verdict"] == "FAIL":
            asset["status"] = "QC_FAILED"
            store.bump(asset)
            cascades.asset_block_cascade(asset, accrue_credit=False)
        else:
            asset["status"] = "QC_PASSED"
            store.bump(asset)
            cascades.asset_clear_cascade(asset, respect_captions=True)
    else:
        asset["technical_score_aircheck"] = figures["technical_score"]
        store.bump(asset)
    return created(views.plain(rec))


@bp.get("/qc-reports/<ident>")
def read_report(ident):
    auth.authorize(QC_READERS, mutating=False)
    return ok(views.plain(auth.qc_report(ident)))


@bp.get("/qc-reports")
def list_reports():
    auth.authorize(QC_READERS, mutating=False)
    rows = store.rows(store.qc_reports)
    for name in ("asset_id", "inspected_by_operator_id", "basis"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if str(r.get(name)) == value]
    include = request.args.get("include_superseded")
    if include is not None and include.lower() in ("false", "0"):
        rows = [r for r in rows if not r["superseded"]]
    return listing(rows, views.plain)


@bp.post("/assets/<ident>/qc-waivers")
def waive(ident):
    auth.authorize(["ProgramDirector", "StationAdmin"], cert=True)
    body = validate(request.get_json(silent=True), [
        F("waived_by_operator_id", "str", required=True),
        F("waiver_justification", "str", required=True),
    ])
    asset = auth.asset(ident)
    signer = auth.operator_ref(body["waived_by_operator_id"])
    if asset["status"] != "QC_FAILED":
        fail("ERR_ASSET_INVALID_STATE", "Only a QC_FAILED asset may be waived.")
    if asset.get("captions_required") and not asset.get("caption_present"):
        fail("ERR_CAPTION_REQUIREMENT_UNMET",
             "A missing caption track is not a waivable defect.")
    score = asset.get("technical_score_ingest")
    if score is None or int(score) < WAIVER_MIN_SCORE:
        fail("ERR_QC_WAIVER_SCORE_TOO_LOW",
             "The governing ingest score must be at least %d." % WAIVER_MIN_SCORE)
    if len(body["waiver_justification"]) < WAIVER_JUSTIFICATION_MIN_CHARS:
        fail("ERR_WAIVER_JUSTIFICATION_REQUIRED",
             "waiver_justification must be at least %d characters."
             % WAIVER_JUSTIFICATION_MIN_CHARS)
    report = governing_report(asset["id"], "INGEST")
    if report is not None:
        inspector = report["inspected_by_operator_id"]
        if inspector in (auth.actor_id(), signer["id"]):
            fail("ERR_SELF_AUTHORIZATION_FORBIDDEN",
                 "An operator may not waive their own inspection.")

    asset["waived_by_operator_id"] = signer["id"]
    asset["waiver_justification"] = body["waiver_justification"]
    asset["status"] = "QC_WAIVED"
    store.bump(asset)
    cascades.asset_clear_cascade(asset, respect_captions=False)
    return ok(views.plain(asset))


@bp.post("/assets/<ident>/retract")
def retract(ident):
    auth.authorize(["TrafficCoordinator", "ProgramDirector", "StationAdmin"])
    body = validate(request.get_json(silent=True), [
        F("reason", "str", required=True, min_len=1),
    ])
    asset = auth.asset(ident)
    if asset["status"] in ("EXPIRED", "RETRACTED"):
        fail("ERR_ASSET_INVALID_STATE", "The asset is already out of use.")
    asset["status"] = "RETRACTED"
    store.bump(asset)
    cascades.asset_block_cascade(asset, accrue_credit=True)
    return ok(views.plain(asset))
