"""Listings, monitoring devices and coverage layers (PRD 3.1 / 3.7)."""

from flask import Blueprint, g

import calc
import views
from core import (ALL_ROLES, ROLE_ADJUDICATOR, ROLE_ADMIN, ROLE_COMPLIANCE,
                  ROLE_GUEST, ROLE_HOST, body_json, db, fail, new_row,
                  object_response, opt_int, opt_string, paginate, qs, req_bool,
                  req_enum, req_int, req_number, req_string, require_auth,
                  require_owner, touch)

bp = Blueprint("listings", __name__)

DEVICE_TYPES = ("NOISE_DECIBEL", "OCCUPANCY_COUNTER", "INDOOR_CAMERA",
                "OUTDOOR_CAMERA")
PLACEMENT_ZONES = ("EXTERIOR", "COMMON_INTERIOR", "BEDROOM", "BATHROOM")
REJECT_REASONS = ("DISCLOSURE_UNCLEAR", "PLACEMENT_DISPUTED",
                  "JURISDICTION_CHANGE")
CAMERAS = ("INDOOR_CAMERA", "OUTDOOR_CAMERA")


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------

@bp.route("/rentals/properties", methods=["POST"])
def create_property():
    require_auth(ROLE_HOST)
    body = body_json()
    host_id = req_string(body, "host_id")
    jurisdiction_rule_id = req_string(body, "jurisdiction_rule_id")
    address_line = req_string(body, "address_line")
    city = req_string(body, "city")
    registration_number = opt_string(body, "registration_number")
    max_occupancy = req_int(body, "max_occupancy", minimum=1)
    bedrooms = req_int(body, "bedrooms", minimum=0)
    nightly_rate_cents = req_int(body, "nightly_rate_cents", minimum=1)
    protection_product = req_enum(body, "protection_product",
                                  ("DEPOSIT", "WAIVER"))
    deposit_amount_cents = req_int(body, "deposit_amount_cents", minimum=0)
    waiver_nightly_fee_cents = req_int(body, "waiver_nightly_fee_cents",
                                      minimum=0)
    claim_ceiling_cents = req_int(body, "claim_ceiling_cents", minimum=1)
    event_policy = req_enum(body, "event_policy",
                            ("EVENTS_ALLOWED", "EVENTS_PROHIBITED"))
    turnover_buffer_nights = opt_int(body, "turnover_buffer_nights",
                                     default=0, minimum=0)

    # Body FK existence in entity field declaration order (PRD 2.9).
    if host_id not in db.hosts:
        fail("ERR_HOST_NOT_FOUND", "Host not found")
    if jurisdiction_rule_id not in db.jurisdiction_rules:
        fail("ERR_JURISDICTION_RULE_NOT_FOUND", "Jurisdiction rule not found")
    require_owner(host_id)

    # Fiscal rule -- evaluated last.
    if protection_product == "DEPOSIT":
        if not (deposit_amount_cents > 0 and waiver_nightly_fee_cents == 0):
            fail("ERR_PRODUCT_CONFIG_INVALID",
                 "A DEPOSIT listing needs a positive deposit_amount_cents and "
                 "a zero waiver_nightly_fee_cents")
    else:
        if not (waiver_nightly_fee_cents > 0 and deposit_amount_cents == 0):
            fail("ERR_PRODUCT_CONFIG_INVALID",
                 "A WAIVER listing needs a positive waiver_nightly_fee_cents "
                 "and a zero deposit_amount_cents")

    row = new_row()
    row.update({
        "host_id": host_id,
        "jurisdiction_rule_id": jurisdiction_rule_id,
        "address_line": address_line,
        "city": city,
        "registration_number": registration_number,
        "max_occupancy": max_occupancy,
        "bedrooms": bedrooms,
        "nightly_rate_cents": nightly_rate_cents,
        "protection_product": protection_product,
        "deposit_amount_cents": deposit_amount_cents,
        "waiver_nightly_fee_cents": waiver_nightly_fee_cents,
        "claim_ceiling_cents": claim_ceiling_cents,
        "event_policy": event_policy,
        "turnover_buffer_nights": turnover_buffer_nights,
        "listing_state": "DRAFT",
        "suspension_reason": None,
    })
    db.properties[row["id"]] = row
    return object_response(views.property_view(row)), 201


@bp.route("/rentals/properties/<pid>", methods=["GET"])
def get_property(pid):
    _, role = require_auth(*ALL_ROLES)
    row = db.properties.get(pid)
    if row is None:
        fail("ERR_PROPERTY_NOT_FOUND", "Property not found")
    # PRD 2.1 / 2.8 step 6: role membership is checked first, then ownership.
    # A Host's ownership of a listing is X-User-ID against host_id; a Guest
    # carries no ownership tie to a listing (nothing on a Property references
    # a Guest), and the three opaque roles are never compared to an entity id.
    if role == ROLE_HOST:
        require_owner(row["host_id"])
    return object_response(views.property_view(row)), 200


@bp.route("/rentals/properties", methods=["GET"])
def list_properties():
    require_auth(*ALL_ROLES)
    host_id = qs("host_id")
    jurisdiction_rule_id = qs("jurisdiction_rule_id")
    listing_state = qs("listing_state")
    rows = list(db.properties.values())
    if host_id is not None:
        rows = [r for r in rows if r["host_id"] == host_id]
    if jurisdiction_rule_id is not None:
        rows = [r for r in rows
                if r["jurisdiction_rule_id"] == jurisdiction_rule_id]
    if listing_state is not None:
        rows = [r for r in rows if r["listing_state"] == listing_state]
    return paginate(rows, views.property_view), 200


@bp.route("/rentals/properties/<pid>/activate", methods=["POST"])
def activate_property(pid):
    require_auth(ROLE_HOST)
    body_json()
    p = db.properties.get(pid)
    if p is None:
        fail("ERR_PROPERTY_NOT_FOUND", "Property not found")
    require_owner(p["host_id"])
    if p["listing_state"] not in ("DRAFT", "SUSPENDED"):
        fail("ERR_INVALID_STATE",
             "Only a DRAFT or SUSPENDED listing can be activated")
    was_suspended = p["listing_state"] == "SUSPENDED"
    if calc.sensor_compliance_state(p) != "COMPLIANT":
        fail("ERR_INVALID_STATE",
             "sensor_compliance_state must read COMPLIANT to activate")
    if was_suspended and calc.coverage_posture(p) == "UNPROTECTED":
        fail("ERR_COVERAGE_UNPROTECTED",
             "A suspended listing cannot be reinstated without coverage")
    jr = calc.prop_rule(p)
    if jr is not None and jr["registration_required"]:
        reg = p["registration_number"]
        if reg is None or reg.strip() == "":
            fail("ERR_REGISTRATION_REQUIRED",
                 "This jurisdiction requires a registration_number")
    p["listing_state"] = "ACTIVE"
    p["suspension_reason"] = None
    touch(p)
    return object_response(views.property_view(p)), 200


@bp.route("/rentals/properties/<pid>/coverage-summary", methods=["GET"])
def property_coverage_summary(pid):
    require_auth(ROLE_HOST, ROLE_ADJUDICATOR, ROLE_COMPLIANCE, ROLE_ADMIN)
    p = db.properties.get(pid)
    if p is None:
        fail("ERR_PROPERTY_NOT_FOUND", "Property not found")
    return object_response(views.coverage_summary_view(p)), 200


# ---------------------------------------------------------------------------
# Monitoring devices -- three privacy rules then the notice rule, in order.
# ---------------------------------------------------------------------------

def enforce_privacy_rules(device_type, placement_zone, records_audio, jr):
    if device_type in CAMERAS and placement_zone in ("BEDROOM", "BATHROOM"):
        fail("ERR_SENSOR_PLACEMENT_PROHIBITED",
             "Cameras may never be placed in a bedroom or bathroom zone")
    if device_type == "INDOOR_CAMERA" and placement_zone == "COMMON_INTERIOR" \
            and not jr["indoor_camera_allowed"]:
        fail("ERR_SENSOR_JURISDICTION_PROHIBITED",
             "This jurisdiction does not allow indoor cameras")
    if records_audio and placement_zone != "EXTERIOR" \
            and not jr["indoor_audio_allowed"]:
        fail("ERR_SENSOR_AUDIO_PROHIBITED",
             "This jurisdiction does not allow indoor audio capture")


def enforce_notice_rule(device_type, records_audio, jr, text):
    if jr["sensor_notice_required"] or device_type in CAMERAS or records_audio:
        if text is None or text.strip() == "":
            fail("ERR_DISCLOSURE_TEXT_REQUIRED",
                 "guest_disclosure_text is required for this device")


@bp.route("/rentals/monitoring-devices", methods=["POST"])
def create_device():
    require_auth(ROLE_HOST)
    body = body_json()
    property_id = req_string(body, "property_id")
    device_type = req_enum(body, "device_type", DEVICE_TYPES)
    placement_zone = req_enum(body, "placement_zone", PLACEMENT_ZONES)
    records_audio = req_bool(body, "records_audio")
    guest_disclosure_text = opt_string(body, "guest_disclosure_text")

    p = db.properties.get(property_id)
    if p is None:
        fail("ERR_PROPERTY_NOT_FOUND", "Property not found")
    require_owner(p["host_id"])
    jr = calc.prop_rule(p)
    enforce_privacy_rules(device_type, placement_zone, records_audio, jr)
    enforce_notice_rule(device_type, records_audio, jr, guest_disclosure_text)

    row = new_row()
    row.update({
        "property_id": property_id,
        "device_type": device_type,
        "placement_zone": placement_zone,
        "records_audio": records_audio,
        "guest_disclosure_text": guest_disclosure_text,
        "disclosure_state": "DRAFT",
        "reject_reason_code": None,
        "reviewed_by_user_id": None,
    })
    db.monitoring_devices[row["id"]] = row
    # Registration re-derives the listing posture to PENDING_REVIEW.
    touch(p)
    return object_response(views.device_view(row)), 201


@bp.route("/rentals/monitoring-devices/<did>", methods=["GET"])
def get_device(did):
    require_auth(ROLE_GUEST, ROLE_HOST, ROLE_COMPLIANCE, ROLE_ADMIN)
    row = db.monitoring_devices.get(did)
    if row is None:
        fail("ERR_DEVICE_NOT_FOUND", "Monitoring device not found")
    return object_response(views.device_view(row)), 200


@bp.route("/rentals/monitoring-devices", methods=["GET"])
def list_devices():
    require_auth(ROLE_GUEST, ROLE_HOST, ROLE_COMPLIANCE, ROLE_ADMIN)
    property_id = qs("property_id")
    disclosure_state = qs("disclosure_state")
    rows = list(db.monitoring_devices.values())
    if property_id is not None:
        rows = [r for r in rows if r["property_id"] == property_id]
    if disclosure_state is not None:
        rows = [r for r in rows if r["disclosure_state"] == disclosure_state]
    return paginate(rows, views.device_view), 200


@bp.route("/rentals/monitoring-devices/<did>/submit-for-review",
          methods=["POST"])
def submit_device(did):
    require_auth(ROLE_HOST)
    body = body_json()
    replacement = opt_string(body, "guest_disclosure_text")
    d = db.monitoring_devices.get(did)
    if d is None:
        fail("ERR_DEVICE_NOT_FOUND", "Monitoring device not found")
    p = db.properties.get(d["property_id"])
    require_owner(p["host_id"])
    if d["disclosure_state"] == "APPROVED":
        fail("ERR_ALREADY_TERMINAL", "This disclosure is already APPROVED")
    if d["disclosure_state"] not in ("DRAFT", "REJECTED"):
        fail("ERR_INVALID_STATE",
             "Only a DRAFT or REJECTED disclosure can be submitted for review")
    text = replacement if replacement is not None \
        else d["guest_disclosure_text"]
    jr = calc.prop_rule(p)
    enforce_notice_rule(d["device_type"], d["records_audio"], jr, text)
    d["guest_disclosure_text"] = text
    d["disclosure_state"] = "PENDING_REVIEW"
    d["reject_reason_code"] = None
    touch(d)
    touch(p)
    return object_response(views.device_view(d)), 200


@bp.route("/rentals/monitoring-devices/<did>/review", methods=["POST"])
def review_device(did):
    require_auth(ROLE_COMPLIANCE)
    body = body_json()
    decision = req_enum(body, "decision", ("APPROVE", "REJECT"))
    reject_reason_code = None
    if decision == "REJECT":
        reject_reason_code = req_enum(body, "reject_reason_code",
                                      REJECT_REASONS)
    d = db.monitoring_devices.get(did)
    if d is None:
        fail("ERR_DEVICE_NOT_FOUND", "Monitoring device not found")
    p = db.properties.get(d["property_id"])
    if d["disclosure_state"] == "APPROVED":
        fail("ERR_ALREADY_TERMINAL", "This disclosure is already APPROVED")
    if d["disclosure_state"] != "PENDING_REVIEW":
        fail("ERR_INVALID_STATE",
             "Only a PENDING_REVIEW disclosure can be reviewed")
    if decision == "APPROVE":
        jr = calc.prop_rule(p)
        enforce_privacy_rules(d["device_type"], d["placement_zone"],
                              d["records_audio"], jr)
        d["reviewed_by_user_id"] = g.user_id
        d["disclosure_state"] = "APPROVED"
        touch(d)
        touch(p)
    else:
        d["reject_reason_code"] = reject_reason_code
        d["reviewed_by_user_id"] = g.user_id
        d["disclosure_state"] = "REJECTED"
        touch(d)
        # Three-link cascade: REJECTED -> NON_COMPLIANT -> SUSPENDED.
        calc.suspend_listing(p, "SENSOR_NON_COMPLIANT")
        touch(p)
    return object_response(views.device_view(d)), 200


# ---------------------------------------------------------------------------
# Coverage layers (PRD 3.7)
# ---------------------------------------------------------------------------

LAYER_SOURCES = ("DAMAGE_WAIVER", "PLATFORM_PROTECTION", "HOST_POLICY",
                 "OWNER_COVERAGE")
LAYER_SCOPES = ("PLATFORM_GLOBAL", "PROPERTY")


@bp.route("/rentals/coverage-layers", methods=["POST"])
def create_coverage_layer():
    require_auth(ROLE_COMPLIANCE, ROLE_ADMIN)
    body = body_json()
    source = req_enum(body, "source", LAYER_SOURCES)
    layer_order = req_int(body, "layer_order", minimum=1)
    limit_cents = req_int(body, "limit_cents", minimum=1)
    deductible_cents = req_int(body, "deductible_cents", minimum=0)
    coverage_pct = req_number(body, "coverage_pct")
    if not (coverage_pct > 0 and coverage_pct <= 1):
        fail("ERR_INVALID_REQUEST",
             "coverage_pct must be greater than 0 and at most 1")
    scope = req_enum(body, "scope", LAYER_SCOPES)
    property_id = opt_string(body, "property_id")

    p = None
    if property_id is not None:
        p = db.properties.get(property_id)
        if p is None:
            fail("ERR_PROPERTY_NOT_FOUND", "Property not found")

    if scope == "PROPERTY" and property_id is None:
        fail("ERR_LAYER_SCOPE_MISMATCH",
             "A PROPERTY-scoped layer must name a property_id")
    if scope == "PLATFORM_GLOBAL" and property_id is not None:
        fail("ERR_LAYER_SCOPE_MISMATCH",
             "A PLATFORM_GLOBAL-scoped layer must leave property_id null")
    if source == "DAMAGE_WAIVER":
        if scope != "PROPERTY" or p is None \
                or p["protection_product"] != "WAIVER":
            fail("ERR_LAYER_SCOPE_MISMATCH",
                 "A DAMAGE_WAIVER layer must be PROPERTY-scoped and attached "
                 "to a WAIVER listing")

    for existing in db.coverage_layers.values():
        if existing["layer_order"] != layer_order:
            continue
        if scope == "PLATFORM_GLOBAL" \
                and existing["scope"] == "PLATFORM_GLOBAL":
            fail("ERR_LAYER_ORDER_CONFLICT",
                 "layer_order is already taken among PLATFORM_GLOBAL layers")
        if scope == "PROPERTY" and existing["scope"] == "PROPERTY" \
                and existing["property_id"] == property_id:
            fail("ERR_LAYER_ORDER_CONFLICT",
                 "layer_order is already taken on this listing")

    row = new_row()
    row.update({
        "source": source,
        "layer_order": layer_order,
        "limit_cents": limit_cents,
        "deductible_cents": deductible_cents,
        "coverage_pct": coverage_pct,
        "scope": scope,
        "property_id": property_id,
        "layer_state": "AVAILABLE",
    })
    db.coverage_layers[row["id"]] = row
    return object_response(views.layer_view(row)), 201


@bp.route("/rentals/coverage-layers/<lid>", methods=["GET"])
def get_coverage_layer(lid):
    require_auth(ROLE_HOST, ROLE_ADJUDICATOR, ROLE_COMPLIANCE, ROLE_ADMIN)
    row = db.coverage_layers.get(lid)
    if row is None:
        fail("ERR_COVERAGE_LAYER_NOT_FOUND", "Coverage layer not found")
    return object_response(views.layer_view(row)), 200


@bp.route("/rentals/coverage-layers", methods=["GET"])
def list_coverage_layers():
    require_auth(ROLE_HOST, ROLE_ADJUDICATOR, ROLE_COMPLIANCE, ROLE_ADMIN)
    property_id = qs("property_id")
    scope = qs("scope")
    source = qs("source")
    layer_state = qs("layer_state")
    rows = list(db.coverage_layers.values())
    if property_id is not None:
        rows = [r for r in rows if r["property_id"] == property_id]
    if scope is not None:
        rows = [r for r in rows if r["scope"] == scope]
    if source is not None:
        rows = [r for r in rows if r["source"] == source]
    if layer_state is not None:
        rows = [r for r in rows if r["layer_state"] == layer_state]
    return paginate(rows, views.layer_view), 200


# ---------------------------------------------------------------------------
# Settlement allocations -- read-only ledger rows (PRD 3.7)
# ---------------------------------------------------------------------------

@bp.route("/rentals/settlement-allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    require_auth(ROLE_HOST, ROLE_ADJUDICATOR, ROLE_COMPLIANCE, ROLE_ADMIN)
    row = db.settlement_allocations.get(aid)
    if row is None:
        fail("ERR_ALLOCATION_NOT_FOUND", "Settlement allocation not found")
    return object_response(views.allocation_view(row)), 200


@bp.route("/rentals/settlement-allocations", methods=["GET"])
def list_allocations():
    require_auth(ROLE_HOST, ROLE_ADJUDICATOR, ROLE_COMPLIANCE, ROLE_ADMIN)
    from core import qs_bool as _qs_bool
    claim_id = qs("claim_id")
    coverage_layer_id = qs("coverage_layer_id")
    voided = _qs_bool("voided")
    rows = list(db.settlement_allocations.values())
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if coverage_layer_id is not None:
        rows = [r for r in rows
                if r["coverage_layer_id"] == coverage_layer_id]
    if voided is not None:
        rows = [r for r in rows if r["voided"] is voided]
    return paginate(rows, views.allocation_view), 200
