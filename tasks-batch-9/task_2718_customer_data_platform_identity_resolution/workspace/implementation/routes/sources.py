"""Retail feeds and ingest batches."""

import re

from flask import Blueprint

import db
import middleware
import validators
from errors import ApiError
from routes import common
from services import calc, ingest

bp = Blueprint("sources", __name__)

CODE_RE = re.compile(r"^[A-Z0-9_]+$")
CHANNEL_TYPES = ("TRANSACTIONS", "LOYALTY", "WEB", "APP", "SUPPORT")
DQ_MODES = ("UNWEIGHTED_MEAN", "WEIGHTED_COMPONENTS", "PENALIZED_WEIGHTED")
PURPOSES = ("MARKETING", "PERSONALIZATION", "MEASUREMENT")
CONSENT_STATES = ("OPT_IN", "OPT_OUT")

RAW_RECORD_FIELDS = (
    "email_raw", "phone_raw", "loyalty_number",
    "first_name", "last_name", "postal_code", "address_line",
)
SENSITIVE_FIELDS = (
    "inferred_health_interest", "inferred_ethnicity_affinity", "precise_geolocation_grid",
)


# ------------------------------------------------------------ source systems

@bp.post("/cdp/source-systems")
def create_source():
    middleware.require_role(middleware.ROLE_ADMIN)
    body = validators.body_object()
    code = validators.req_str(body, "code", 3, 20, CODE_RE)
    display_name = validators.req_str(body, "display_name", 1, 120)
    channel_type = validators.req_enum(body, "channel_type", CHANNEL_TYPES)
    trust_tier = validators.opt_int(body, "trust_tier", 1, 5, 3)
    mode = validators.opt_enum(body, "dq_scoring_mode", DQ_MODES, "WEIGHTED_COMPONENTS")
    floor = validators.opt_decimal(body, "pii_completeness_floor", 0, 1, 2, 0.70)
    if any(s["code"] == code for s in db.all_of("source_systems")):
        raise ApiError("ERR_DUPLICATE_CODE")
    entity = db.new_entity(
        "source_systems",
        code=code,
        display_name=display_name,
        channel_type=channel_type,
        trust_tier=trust_tier,
        dq_scoring_mode=mode,
        pii_completeness_floor=floor,
        status="REGISTERED",
        dq_window_start_at=db.now(),
        quarantine_count=0,
        last_reinstated_at=None,
    )
    return common.one("source_systems", entity, 201)


@bp.get("/cdp/source-systems/<source_id>")
def read_source(source_id):
    middleware.require_role(*middleware.READ_ROLES)
    return common.one("source_systems", common.source(source_id))


@bp.get("/cdp/source-systems")
def list_sources():
    middleware.require_role(*middleware.READ_ROLES)
    return common.collection_list(
        "source_systems",
        {"status": "status", "channel_type": "channel_type"},
        common.seq_sort_desc,
    )


@bp.post("/cdp/source-systems/<source_id>/reinstate")
def reinstate_source(source_id):
    middleware.require_role(middleware.ROLE_ADMIN)
    validators.body_object(required=False)
    entity = common.source(source_id)
    common.require_status(entity, ("QUARANTINED",))
    entity["status"] = "ACTIVE"
    entity["dq_window_start_at"] = db.now()
    entity["last_reinstated_at"] = db.now()
    db.touch(entity)
    return common.one("source_systems", entity)


# ------------------------------------------------------------ ingest batches

def _parse_signal(raw, index):
    signal = validators.sub_object(raw, "consent_signals[%d]" % index)
    return {
        "channel": validators.req_enum(signal, "channel", calc.CHANNELS),
        "purpose": validators.req_enum(signal, "purpose", PURPOSES),
        "consent_state": validators.req_enum(signal, "consent_state", CONSENT_STATES),
    }


def _parse_record(raw, index):
    element = validators.sub_object(raw, "records[%d]" % index)
    record = {
        "external_id": validators.req_str(element, "external_id", 1, 120),
        "event_timestamp": validators.req_ts(element, "event_timestamp"),
    }
    for field in RAW_RECORD_FIELDS:
        record[field] = validators.raw_str(element, field)
    for field in SENSITIVE_FIELDS:
        record[field] = validators.raw_str(element, field)
    record["loyalty_tier"] = validators.opt_enum(element, "loyalty_tier", calc.LOYALTY_TIERS)
    signals = validators.opt_array(element, "consent_signals")
    record["consent_signals"] = [
        _parse_signal(signal, position) for position, signal in enumerate(signals)
    ]
    return record


@bp.post("/cdp/ingest-batches")
def create_batch():
    middleware.require_role(middleware.ROLE_ENGINEER)
    body = validators.body_object()
    source_id = validators.req_id(body, "source_system_id")
    label = validators.req_str(body, "batch_label", 1, 80)
    raw_records = validators.req_array(body, "records", 1, 200)
    records = [_parse_record(raw, index) for index, raw in enumerate(raw_records)]
    source = common.source(source_id)
    if source["status"] == "QUARANTINED":
        raise ApiError("ERR_SOURCE_SYSTEM_QUARANTINED")
    seen = set()
    for record in records:
        if record["external_id"] in seen:
            raise ApiError("ERR_DUPLICATE_EXTERNAL_ID")
        seen.add(record["external_id"])
    entity = db.new_entity(
        "ingest_batches",
        source_system_id=source["id"],
        batch_label=label,
        records=records,
        record_count=len(records),
        valid_record_count=0,
        invalid_record_count=0,
        dq_score=None,
        dq_failure_breakdown={},
        status="RECEIVED",
        retry_round=0,
        rejection_reason=None,
        validated_at=None,
        promoted_at=None,
        new_profile_count=0,
        matched_deterministic_count=0,
        matched_probabilistic_count=0,
    )
    return common.one("ingest_batches", entity, 201)


@bp.get("/cdp/ingest-batches/<batch_id>")
def read_batch(batch_id):
    middleware.require_role(*middleware.READ_ROLES)
    return common.one("ingest_batches", common.batch(batch_id))


@bp.get("/cdp/ingest-batches")
def list_batches():
    middleware.require_role(*middleware.READ_ROLES)
    return common.collection_list(
        "ingest_batches",
        {"source_system_id": "source_system_id", "status": "status"},
        common.seq_sort,
    )


@bp.post("/cdp/ingest-batches/<batch_id>/validate")
def validate_batch(batch_id):
    middleware.require_role(middleware.ROLE_ENGINEER)
    validators.body_object(required=False)
    entity = common.batch(batch_id)
    common.require_status(entity, ("RECEIVED",))
    source = db.store["source_systems"][entity["source_system_id"]]
    if source["status"] == "QUARANTINED":
        raise ApiError("ERR_SOURCE_SYSTEM_QUARANTINED")
    ingest.validate_batch(entity, source)
    return common.one("ingest_batches", entity)


@bp.post("/cdp/ingest-batches/<batch_id>/requeue")
def requeue_batch(batch_id):
    middleware.require_role(middleware.ROLE_ENGINEER)
    validators.body_object(required=False)
    entity = common.batch(batch_id)
    common.require_status(entity, ("QUARANTINED",))
    ingest.requeue_batch(entity)
    return common.one("ingest_batches", entity)


@bp.post("/cdp/ingest-batches/<batch_id>/promote")
def promote_batch(batch_id):
    middleware.require_role(middleware.ROLE_ENGINEER)
    validators.body_object(required=False)
    entity = common.batch(batch_id)
    common.require_status(entity, ("VALIDATED",))
    source = db.store["source_systems"][entity["source_system_id"]]
    if source["status"] == "QUARANTINED":
        raise ApiError("ERR_SOURCE_SYSTEM_QUARANTINED")
    ingest.promote_batch(entity, source)
    return common.one("ingest_batches", entity)
