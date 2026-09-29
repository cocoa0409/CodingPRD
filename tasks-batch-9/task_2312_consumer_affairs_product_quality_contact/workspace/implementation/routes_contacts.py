"""Contact intake and the whole complaint lifecycle."""

from flask import Blueprint

import calc
import serializers as ser
import services as svc
from common import (
    ROLE_CARE_AGENT,
    ROLE_CARE_SUPERVISOR,
    ROLE_QUALITY_LEAD,
    ROLE_REGULATORY_OFFICER,
    authorize,
    base_record,
    check_required,
    err,
    get_body,
    must_get,
    now,
    pagination,
    paginated,
    q_str,
    sort_records,
    store,
    success,
    touch,
    v_bool,
    v_datetime,
    v_enum,
    v_int,
    v_string,
    v_string_array,
)

bp = Blueprint("contacts", __name__)

CHANNELS = ("PHONE", "EMAIL", "SOCIAL", "WEB")
COMPLAINT_TYPES = ("FOREIGN_MATERIAL", "ILLNESS", "PACKAGING", "QUALITY")
OBJECT_CLASSES = ("NONE", "SOFT", "HARD_BLUNT", "HARD_SHARP")
SETTLED_REGULATORY = ("NOT_APPLICABLE", "NOT_REPORTABLE", "SUBMITTED")
AUTO_REPORT_KIND = {
    "ILLNESS": "ILLNESS_CLUSTER",
    "FOREIGN_MATERIAL": "FOREIGN_MATERIAL_INJURY",
}


# ---------------------------------------------------------------------------
# contacts
# ---------------------------------------------------------------------------
@bp.post("/contacts")
def create_contact():
    actor = authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR])
    body = get_body()
    if "consumer_id" in body and body["consumer_id"] is not None:
        must_get("consumers", body["consumer_id"])
    check_required(body, ["consumer_id", "channel", "received_at", "raw_message"])
    consumer_id = v_string(body, "consumer_id", 1)
    channel = v_enum(body, "channel", CHANNELS)
    received_at = v_datetime(body, "received_at")
    raw_message = v_string(body, "raw_message", 1, 4000)
    handle_or_address = v_string(body, "handle_or_address", 0)

    if received_at > now():
        raise err("ERR_RECEIVED_AT_IN_FUTURE", "received_at is after the logical clock")

    rec = base_record()
    rec.update(
        {
            "consumer_id": consumer_id,
            "channel": channel,
            "received_at": received_at,
            "raw_message": raw_message,
            "handle_or_address": handle_or_address,
            "status": "OPEN",
            "complaint_count": 0,
            "intake_agent_ref": actor.user_id,
        }
    )
    store.contacts[rec["id"]] = rec
    return success(ser.contact(rec), 201)


@bp.get("/contacts")
def list_contacts():
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD])
    limit, offset = pagination()
    consumer_id = q_str("consumer_id")
    channel = q_str("channel")
    status = q_str("status")
    items = []
    for rec in sort_records(list(store.contacts.values())):
        if consumer_id is not None and rec["consumer_id"] != consumer_id:
            continue
        if channel is not None and rec["channel"] != channel:
            continue
        if status is not None and rec["status"] != status:
            continue
        items.append(ser.contact(rec))
    return paginated(items, limit, offset)


@bp.get("/contacts/<record_id>")
def get_contact(record_id):
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD])
    rec = must_get("contacts", record_id)
    return success(ser.contact(rec))


@bp.post("/contacts/<record_id>/close-no-complaint")
def close_contact(record_id):
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR])
    rec = must_get("contacts", record_id)
    get_body()
    if rec["complaint_count"] != 0:
        raise err(
            "ERR_CONTACT_HAS_COMPLAINTS", "the contact already produced at least one complaint"
        )
    if rec["status"] != "CLOSED_NO_COMPLAINT":
        rec["status"] = "CLOSED_NO_COMPLAINT"
        touch(rec)
    return success(ser.contact(rec))


# ---------------------------------------------------------------------------
# complaints
# ---------------------------------------------------------------------------
@bp.post("/complaints")
def create_complaint():
    actor = authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR])
    body = get_body()
    if "contact_id" in body and body["contact_id"] is not None:
        must_get("contacts", body["contact_id"])
    check_required(body, ["contact_id", "complaint_type"])
    contact_id = v_string(body, "contact_id", 1)
    complaint_type = v_enum(body, "complaint_type", COMPLAINT_TYPES)
    reported_batch_code = v_string(body, "reported_batch_code", 0)
    pack_code_date = v_datetime(body, "pack_code_date")
    foreign_object_class = v_enum(body, "foreign_object_class", OBJECT_CLASSES, "NONE")
    medical_attention_sought = v_bool(body, "medical_attention_sought", False)
    hospitalization = v_bool(body, "hospitalization", False)
    vulnerable_consumer = v_bool(body, "vulnerable_consumer", False)
    symptom_codes = v_string_array(body, "symptom_codes", 12, 1, 16, [])
    units_claimed = v_int(body, "units_claimed", 1, 100, 1)

    contact = store.contacts[contact_id]
    if contact["status"] not in ("OPEN", "LOGGED"):
        raise err("ERR_CONTACT_CLOSED", "the contact was closed as producing no complaint")

    rec = base_record()
    rec.update(
        {
            "contact_id": contact_id,
            "consumer_id": contact["consumer_id"],
            "product_id": None,
            "lot_id": None,
            "duplicate_of_complaint_id": None,
            "responded_template_id": None,
            "reported_batch_code": None,
            "pack_code_date": pack_code_date,
            "complaint_type": complaint_type,
            "foreign_object_class": foreign_object_class,
            "medical_attention_sought": medical_attention_sought,
            "hospitalization": hospitalization,
            "vulnerable_consumer": vulnerable_consumer,
            "symptom_codes": symptom_codes,
            "units_claimed": units_claimed,
            "product_identification_status": "UNRESOLVED",
            "adjudicated_severity_score": None,
            "adjudicated_severity_band": None,
            "handling_status": "INTAKE",
            "regulatory_status": "NOT_APPLICABLE",
            "pre_hold_handling_status": None,
            "responded_at": None,
            "triaged_by_ref": None,
            "created_by_ref": actor.user_id,
            "linked_signal_count": 0,
        }
    )

    # batch-code resolution runs immediately and may abort the whole create
    svc.resolve_batch_code(rec, reported_batch_code, pack_code_date)

    score, band = calc.provisional_severity(rec)
    rec["provisional_severity_score"] = score
    rec["provisional_severity_band"] = band

    store.complaints[rec["id"]] = rec

    if contact["status"] == "OPEN":
        contact["status"] = "LOGGED"
        touch(contact)
    ser.sync_contact(contact)
    ser.sync_consumer(store.consumers.get(rec["consumer_id"]))
    ser.sync_lot(store.production_lots.get(rec.get("lot_id")))
    return success(ser.complaint(rec), 201)


@bp.get("/complaints")
def list_complaints():
    authorize(
        [ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD, ROLE_REGULATORY_OFFICER]
    )
    limit, offset = pagination()
    filters = {
        "contact_id": q_str("contact_id"),
        "consumer_id": q_str("consumer_id"),
        "product_id": q_str("product_id"),
        "lot_id": q_str("lot_id"),
        "duplicate_of_complaint_id": q_str("duplicate_of_complaint_id"),
        "responded_template_id": q_str("responded_template_id"),
        "handling_status": q_str("handling_status"),
        "regulatory_status": q_str("regulatory_status"),
    }
    band = q_str("effective_severity_band")
    items = []
    for rec in sort_records(list(store.complaints.values())):
        if any(value is not None and rec.get(key) != value for key, value in filters.items()):
            continue
        if band is not None and calc.effective_band(rec) != band:
            continue
        items.append(ser.complaint(rec))
    return paginated(items, limit, offset)


@bp.get("/complaints/<record_id>")
def get_complaint(record_id):
    authorize(
        [ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD, ROLE_REGULATORY_OFFICER]
    )
    rec = must_get("complaints", record_id)
    return success(ser.complaint(rec))


@bp.post("/complaints/<record_id>/identify-product")
def identify_product(record_id):
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR])
    rec = must_get("complaints", record_id)
    body = get_body()
    check_required(body, ["reported_batch_code"])
    reported_batch_code = v_string(body, "reported_batch_code", 1)
    pack_code_date = v_datetime(body, "pack_code_date")

    if rec["handling_status"] in ("CLOSED", "DUPLICATE"):
        raise err(
            "ERR_COMPLAINT_STATE_INVALID",
            "the complaint's handling_status does not permit re-identification",
        )

    previous_lot_id = svc.resolve_batch_code(rec, reported_batch_code, pack_code_date)
    touch(rec)
    if previous_lot_id != rec.get("lot_id"):
        ser.sync_lot(store.production_lots.get(previous_lot_id))
    ser.sync_lot(store.production_lots.get(rec.get("lot_id")))
    return success(ser.complaint(rec))


@bp.post("/complaints/<record_id>/triage")
def triage_complaint(record_id):
    actor = authorize([ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD])
    rec = must_get("complaints", record_id)
    body = get_body()
    v_string(body, "reviewer_note", 0)

    if rec["handling_status"] != "INTAKE":
        raise err("ERR_COMPLAINT_STATE_INVALID", "only an INTAKE complaint may be triaged")
    if rec["product_identification_status"] != "RESOLVED":
        raise err("ERR_PRODUCT_UNIDENTIFIED", "the complaint's product is not identified")

    score, band = calc.adjudicated_severity(rec)
    rec["adjudicated_severity_score"] = score
    rec["adjudicated_severity_band"] = band
    rec["handling_status"] = "TRIAGED"
    rec["triaged_by_ref"] = actor.user_id
    touch(rec)

    lot = store.production_lots.get(rec.get("lot_id"))
    ser.sync_lot(lot)

    if (
        band in ("S1", "S2")
        and rec["complaint_type"] in AUTO_REPORT_KIND
        and rec["regulatory_status"] == "NOT_APPLICABLE"
        and svc.active_report_of_complaint(rec["id"]) is None
    ):
        svc.open_regulatory_report(rec, AUTO_REPORT_KIND[rec["complaint_type"]])

    if band == "S1" and lot is not None:
        svc.hold_lot(lot, "TRIAGE")

    if lot is not None:
        ser.sync_plant(svc.plant_of_lot(lot))
    return success(ser.complaint(rec))


@bp.post("/complaints/<record_id>/respond")
def respond_complaint(record_id):
    actor = authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR])
    rec = must_get("complaints", record_id)
    body = get_body()
    if "response_template_id" in body and body["response_template_id"] is not None:
        must_get("response_templates", body["response_template_id"])
    check_required(body, ["response_template_id"])
    template_id = v_string(body, "response_template_id", 1)
    template = store.response_templates[template_id]

    if rec["handling_status"] != "TRIAGED":
        raise err("ERR_COMPLAINT_STATE_INVALID", "only a TRIAGED complaint may be responded to")

    lot = store.production_lots.get(rec.get("lot_id"))
    if lot is not None and lot["release_status"] == "WITHDRAWN":
        raise err("ERR_LOT_WITHDRAWN", "canned messaging is frozen for a withdrawn lot")

    if template["status"] != "ACTIVE":
        raise err("ERR_TEMPLATE_STATE_INVALID", "the selected template is not ACTIVE")
    if template["applies_to_type"] not in ("ANY", rec["complaint_type"]):
        raise err("ERR_TEMPLATE_TYPE_MISMATCH", "the template does not answer this complaint type")

    band = calc.effective_band(rec)
    if calc.BAND_SEVERITY_RANK[template["max_band_allowed"]] < calc.BAND_SEVERITY_RANK[band]:
        raise err(
            "ERR_TEMPLATE_BAND_TOO_LOW", "the template may not answer a complaint of this band"
        )
    if template["requires_supervisor_approval"] and actor.role != ROLE_CARE_SUPERVISOR:
        raise err("ERR_UNAUTHORIZED", "this template may only be sent by a CareSupervisor")

    rec["handling_status"] = "IN_RESOLUTION"
    rec["responded_template_id"] = template_id
    rec["responded_at"] = now()
    touch(rec)
    template["usage_count"] += 1
    touch(template)
    return success(ser.complaint(rec))


@bp.post("/complaints/<record_id>/mark-duplicate")
def mark_duplicate(record_id):
    authorize([ROLE_CARE_SUPERVISOR])
    rec = must_get("complaints", record_id)
    body = get_body()
    check_required(body, ["duplicate_of_complaint_id"])
    target_id = v_string(body, "duplicate_of_complaint_id", 1)

    target = store.complaints.get(target_id)
    if target is None or target_id == rec["id"]:
        raise err("ERR_DUPLICATE_TARGET_INVALID", "the duplicate target is not a valid complaint")

    if rec["handling_status"] not in ("INTAKE", "TRIAGED"):
        raise err(
            "ERR_COMPLAINT_STATE_INVALID",
            "only an INTAKE or TRIAGED complaint may be marked a duplicate",
        )

    if target["handling_status"] == "DUPLICATE" or target["consumer_id"] != rec["consumer_id"]:
        raise err(
            "ERR_DUPLICATE_TARGET_INVALID",
            "the duplicate target must belong to the same consumer and not itself be a duplicate",
        )

    rec["handling_status"] = "DUPLICATE"
    rec["duplicate_of_complaint_id"] = target_id
    touch(rec)
    ser.sync_lot(store.production_lots.get(rec.get("lot_id")))
    ser.sync_consumer(store.consumers.get(rec["consumer_id"]))
    return success(ser.complaint(rec))


@bp.post("/complaints/<record_id>/unmark-duplicate")
def unmark_duplicate(record_id):
    authorize([ROLE_CARE_SUPERVISOR])
    rec = must_get("complaints", record_id)
    get_body()
    if rec["handling_status"] != "DUPLICATE":
        raise err("ERR_COMPLAINT_STATE_INVALID", "the complaint is not marked a duplicate")

    rec["handling_status"] = (
        "TRIAGED" if rec.get("adjudicated_severity_score") is not None else "INTAKE"
    )
    rec["duplicate_of_complaint_id"] = None
    touch(rec)
    ser.sync_lot(store.production_lots.get(rec.get("lot_id")))
    ser.sync_consumer(store.consumers.get(rec["consumer_id"]))
    return success(ser.complaint(rec))


@bp.post("/complaints/<record_id>/quality-hold")
def quality_hold(record_id):
    authorize([ROLE_QUALITY_LEAD])
    rec = must_get("complaints", record_id)
    get_body()
    if rec["handling_status"] not in ("TRIAGED", "AWAITING_SAMPLE", "IN_RESOLUTION"):
        raise err(
            "ERR_COMPLAINT_STATE_INVALID",
            "the complaint's handling_status does not permit a quality hold",
        )
    svc.impose_quality_hold(rec)
    ser.sync_consumer(store.consumers.get(rec["consumer_id"]))
    return success(ser.complaint(rec))


@bp.post("/complaints/<record_id>/release-hold")
def release_hold(record_id):
    authorize([ROLE_QUALITY_LEAD])
    rec = must_get("complaints", record_id)
    get_body()
    if rec["handling_status"] != "ON_QUALITY_HOLD":
        raise err("ERR_COMPLAINT_STATE_INVALID", "the complaint is not on quality hold")
    for signal in svc.signals_containing_complaint(rec["id"]):
        if signal["status"] == "RECALL_EVALUATION":
            raise err(
                "ERR_RECALL_EVALUATION_ACTIVE",
                "a trend signal containing this complaint is under recall evaluation",
            )
    rec["handling_status"] = rec.get("pre_hold_handling_status") or "TRIAGED"
    rec["pre_hold_handling_status"] = None
    touch(rec)
    return success(ser.complaint(rec))


@bp.post("/complaints/<record_id>/resolve")
def resolve_complaint(record_id):
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR])
    rec = must_get("complaints", record_id)
    body = get_body()
    v_string(body, "resolution_note", 0)

    if rec["handling_status"] != "IN_RESOLUTION":
        raise err("ERR_COMPLAINT_STATE_INVALID", "only an IN_RESOLUTION complaint may be resolved")
    if rec.get("responded_at") is None:
        raise err(
            "ERR_COMPLAINT_STATE_INVALID", "the complaint has no consumer response on file"
        )
    for remedy in svc.remedies_of_complaint(rec["id"]):
        if remedy["status"] in svc.LIVE_REMEDY_STATES:
            raise err(
                "ERR_COMPLAINT_STATE_INVALID",
                "a goodwill remedy is still live on this complaint",
            )

    rec["handling_status"] = "RESOLVED"
    touch(rec)
    return success(ser.complaint(rec))


@bp.post("/complaints/<record_id>/close")
def close_complaint(record_id):
    authorize([ROLE_CARE_SUPERVISOR])
    rec = must_get("complaints", record_id)
    body = get_body()
    v_string(body, "closing_note", 0)

    if rec["handling_status"] != "RESOLVED":
        raise err("ERR_COMPLAINT_STATE_INVALID", "only a RESOLVED complaint may be closed")
    if rec["regulatory_status"] not in SETTLED_REGULATORY:
        raise err(
            "ERR_REGULATORY_STATE_INVALID", "the regulatory dimension has not settled"
        )
    rec["handling_status"] = "CLOSED"
    touch(rec)
    return success(ser.complaint(rec))


@bp.get("/complaints/<record_id>/signal-memberships")
def list_complaint_memberships(record_id):
    authorize([ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD])
    must_get("complaints", record_id)
    limit, offset = pagination()
    items = [ser.signal_membership(m) for m in svc.memberships_of_complaint(record_id)]
    return paginated(items, limit, offset)
