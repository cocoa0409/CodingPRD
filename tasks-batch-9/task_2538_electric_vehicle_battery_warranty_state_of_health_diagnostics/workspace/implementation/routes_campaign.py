"""Software remediation campaigns and the owner-consent lifecycle."""
from flask import Blueprint, request

import cascade
import claim_service as svc
from common import (API_PREFIX, ApiError, CERT_RANK, R_ADMIN, R_OWNER, R_TECH,
                    READ_ROLES, auth, by_created, campaign_consents, db, forbidden,
                    get_body, invalid, must, fk, new_record, now, ok, ok_list, opt_bool,
                    opt_id, opt_str, page, pagination, refresh_technician, req_enum,
                    req_int, req_str, req_str_list, touch)

bp = Blueprint("campaign", __name__, url_prefix=API_PREFIX)

DEFECTS = ("CHARGING", "THERMAL_MANAGEMENT")
PACK_TARGETS = ("NEW", "REMANUFACTURED", "ANY")
SCOPES = ("LIMITED", "FIELD")
DECISIONS = ("GRANT", "DECLINE")


def _filter_eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


# =================================================================== campaigns
@bp.route("/remediation-campaigns", methods=["POST"])
def create_campaign():
    auth((R_ADMIN,))
    body = get_body()
    code = req_str(body, "campaign_code")
    defect = req_enum(body, "target_defect", DEFECTS)
    version_text = req_str(body, "software_version")
    pack_target = req_enum(body, "applies_to_pack_type", PACK_TARGETS)
    model_code = req_str(body, "applies_to_model_code")
    consent_required = opt_bool(body, "consent_required", True)
    pilot_regions = req_str_list(body, "pilot_region_codes")
    for existing in db.campaigns.values():
        if existing["campaign_code"] == code:
            raise ApiError("ERR_DUPLICATE_CAMPAIGN_CODE", 409,
                           "campaign_code %s is already registered." % code)
    record = new_record()
    record.update({
        "campaign_code": code,
        "target_defect": defect,
        "software_version": version_text,
        "applies_to_pack_type": pack_target,
        "applies_to_model_code": model_code,
        "consent_required": consent_required,
        "pilot_region_codes": list(pilot_regions),
        "status": "DRAFT",
        "release_scope": None,
        "solicited_consent_count": 0,
        "open_consent_count": 0,
        "applied_count": 0,
    })
    db.campaigns[record["id"]] = record
    return ok(record, 201)


@bp.route("/remediation-campaigns/<campaign_id>", methods=["GET"])
def get_campaign(campaign_id):
    auth(READ_ROLES)
    return ok(must("campaigns", campaign_id))


@bp.route("/remediation-campaigns", methods=["GET"])
def list_campaigns():
    auth(READ_ROLES)
    limit, offset = pagination()
    rows = by_created(list(db.campaigns.values()))
    for field in ("status", "target_defect", "applies_to_model_code", "release_scope"):
        rows = _filter_eq(rows, field, request.args.get(field))
    window, total = page(rows, limit, offset)
    return ok_list(window, limit, offset, total)


def _pack_type_matches(campaign, vehicle):
    if campaign["applies_to_pack_type"] == "ANY":
        return True
    pack = db.packs.get(vehicle["installed_pack_id"])
    if pack is None:
        return False
    return pack["pack_type"] == campaign["applies_to_pack_type"]


def _targets(campaign, vehicle, scope):
    if vehicle["model_code"] != campaign["applies_to_model_code"]:
        return False
    if not _pack_type_matches(campaign, vehicle):
        return False
    if scope == "LIMITED" and vehicle["region_code"] not in campaign["pilot_region_codes"]:
        return False
    return True


@bp.route("/remediation-campaigns/<campaign_id>/release", methods=["POST"])
def release_campaign(campaign_id):
    auth((R_ADMIN,))
    body = get_body()
    scope = req_enum(body, "release_scope", SCOPES)
    campaign = must("campaigns", campaign_id)
    if campaign["status"] != "DRAFT":
        raise ApiError("ERR_CAMPAIGN_NOT_DRAFT", 409, "Only a DRAFT campaign may be released.")
    if scope == "LIMITED" and not campaign["pilot_region_codes"]:
        raise invalid("A LIMITED release requires at least one pilot region code.")
    campaign["status"] = "LIMITED_RELEASE" if scope == "LIMITED" else "FIELD_RELEASE"
    campaign["release_scope"] = scope
    created = 0
    for vehicle in by_created(list(db.vehicles.values())):
        if vehicle["status"] != "ACTIVE":
            continue
        if not _targets(campaign, vehicle, scope):
            continue
        cascade.create_consent(campaign, vehicle)
        created += 1
    campaign["solicited_consent_count"] = created
    campaign["open_consent_count"] = created
    touch(campaign)
    return ok(campaign)


# ==================================================================== consents
@bp.route("/remediation-consents", methods=["POST"])
def create_consent():
    auth((R_ADMIN,))
    body = get_body()
    campaign_id = req_str(body, "campaign_id")
    vehicle_id = req_str(body, "vehicle_id")
    expected_version = req_int(body, "expected_campaign_version", minimum=0)
    superseded_id = opt_id(body, "superseded_consent_id")
    campaign = must("campaigns", campaign_id)
    vehicle = must("vehicles", vehicle_id)
    superseded = fk("consents", superseded_id)
    if expected_version != campaign["version"]:
        raise ApiError("ERR_STALE_CAMPAIGN_VERSION", 412,
                       "expected_campaign_version does not match the campaign.")
    if campaign["status"] not in cascade.RELEASED_STATUSES:
        raise ApiError("ERR_CAMPAIGN_NOT_RELEASED", 409, "The campaign is not released.")
    if vehicle["status"] != "ACTIVE":
        raise ApiError("ERR_VEHICLE_IMMOBILIZED", 409, "The vehicle is not ACTIVE.")
    if not _targets(campaign, vehicle, campaign["release_scope"]):
        raise ApiError("ERR_VEHICLE_NOT_TARGETED", 422,
                       "The vehicle is outside the campaign's target set.")
    if cascade.existing_open_consent(campaign_id, vehicle_id) is not None:
        raise ApiError("ERR_DUPLICATE_ACTIVE_CONSENT", 409,
                       "An open consent already exists for this campaign and vehicle.")
    if superseded is not None:
        if (superseded["campaign_id"] != campaign_id
                or superseded["vehicle_id"] != vehicle_id
                or superseded["consent_status"] not in ("DECLINED", "EXPIRED")):
            raise ApiError("ERR_DUPLICATE_ACTIVE_CONSENT", 409,
                           "superseded_consent_id must name a declined or expired "
                           "consent for the same campaign and vehicle.")
    record = cascade.create_consent(campaign, vehicle, superseded)
    cascade.refresh_campaign(campaign)
    return ok(record, 201)


@bp.route("/remediation-consents/<consent_id>", methods=["GET"])
def get_consent(consent_id):
    auth(READ_ROLES)
    return ok(must("consents", consent_id))


@bp.route("/remediation-consents", methods=["GET"])
def list_consents():
    auth(READ_ROLES)
    limit, offset = pagination()
    rows = by_created(list(db.consents.values()))
    for field in ("campaign_id", "vehicle_id", "superseded_consent_id", "consent_status"):
        rows = _filter_eq(rows, field, request.args.get(field))
    window, total = page(rows, limit, offset)
    return ok_list(window, limit, offset, total)


def _linked_software_claim(consent):
    for claim in by_created(list(db.claims.values())):
        if claim["vehicle_id"] != consent["vehicle_id"]:
            continue
        if claim["linked_campaign_id"] != consent["campaign_id"]:
            continue
        if claim["adjudication_status"] == "APPROVED_SOFTWARE":
            return claim
    return None


def _consent_context(consent):
    vehicle = db.vehicles[consent["vehicle_id"]]
    campaign = db.campaigns[consent["campaign_id"]]
    return vehicle, campaign


@bp.route("/remediation-consents/<consent_id>/decision", methods=["POST"])
def consent_decision(consent_id):
    role, user_id = auth((R_OWNER,), actor_required=True)
    body = get_body()
    decision = req_enum(body, "decision", DECISIONS)
    opt_str(body, "owner_signature")
    consent = must("consents", consent_id)
    if user_id != consent["vehicle_id"]:
        raise forbidden("X-User-ID must equal the consent's vehicle_id.")
    if consent["consent_status"] != "PENDING":
        raise ApiError("ERR_CONSENT_ALREADY_DECIDED", 409,
                       "The consent has already been decided.")
    vehicle, campaign = _consent_context(consent)
    if vehicle["status"] != "ACTIVE":
        raise ApiError("ERR_VEHICLE_IMMOBILIZED", 409, "The vehicle is not ACTIVE.")
    if now() > consent["expires_at"]:
        raise ApiError("ERR_CONSENT_EXPIRED", 409, "The consent window has closed.")
    if campaign["status"] not in cascade.RELEASED_STATUSES:
        raise ApiError("ERR_CAMPAIGN_NOT_RELEASED", 409, "The campaign is no longer released.")
    consent["decision_at"] = now()
    consent["consent_status"] = "GRANTED" if decision == "GRANT" else "DECLINED"
    touch(consent)
    if decision == "DECLINE":
        cascade.refresh_campaign(campaign)
        claim = _linked_software_claim(consent)
        if claim is not None:
            claim["adjudication_status"] = "DENIED"
            claim["denial_reason"] = "CONSENT_DECLINED"
            svc.zero_money(claim, include_admin_fee=True, reset_proration=False)
            touch(claim)
            cascade.refresh_accrual(svc.program_of(claim))
    return ok(consent)


@bp.route("/remediation-consents/<consent_id>/apply-update", methods=["POST"])
def apply_update(consent_id):
    role, user_id = auth((R_TECH,))
    body = get_body()
    opt_str(body, "installer_note")
    consent = must("consents", consent_id)
    if consent["consent_status"] != "GRANTED":
        raise ApiError("ERR_CONSENT_NOT_GRANTED", 409,
                       "Only a GRANTED consent may record an applied flash.")
    vehicle, campaign = _consent_context(consent)
    if vehicle["status"] != "ACTIVE":
        raise ApiError("ERR_VEHICLE_IMMOBILIZED", 409, "The vehicle is not ACTIVE.")
    if now() > consent["expires_at"]:
        raise ApiError("ERR_CONSENT_EXPIRED", 409, "The consent window has closed.")
    if campaign["status"] not in cascade.RELEASED_STATUSES:
        raise ApiError("ERR_CAMPAIGN_NOT_RELEASED", 409, "The campaign is no longer released.")
    technician = db.technicians.get(user_id) if user_id else None
    if technician is not None:
        refresh_technician(technician)
        if technician["status"] == "CERT_LAPSED":
            raise ApiError("ERR_TECHNICIAN_CERT_EXPIRED", 409,
                           "The acting technician's certification has expired.")
        if CERT_RANK[technician["hv_cert_level"]] < CERT_RANK["L1"]:
            raise ApiError("ERR_TECHNICIAN_LEVEL_INSUFFICIENT", 409,
                           "The technician's certification level is insufficient.")
    consent["consent_status"] = "APPLIED"
    consent["applied_at"] = now()
    consent["applied_software_version"] = campaign["software_version"]
    touch(consent)
    cascade.refresh_campaign(campaign)
    claim = _linked_software_claim(consent)
    if claim is not None:
        claim["adjudication_status"] = "FULFILLED"
        claim["pack_shipment_required"] = False
        touch(claim)
        cascade.refresh_accrual(svc.program_of(claim))
    return ok(consent)
