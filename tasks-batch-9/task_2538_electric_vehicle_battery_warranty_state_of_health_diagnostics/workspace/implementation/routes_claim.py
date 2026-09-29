"""Warranty claims: filing, information rounds, adjudication, fulfilment, close."""
from flask import Blueprint, request

import calc
import cascade
import claim_service as svc
from common import (API_PREFIX, ApiError, CERT_RANK, D, R_ADJ, R_TECH, READ_ROLES,
                    auth, by_created, claim_disputes, db, forbidden, get_body, invalid,
                    must, fk, new_record, now, ok, ok_list, opt_id, opt_str, page,
                    pagination, pack_modules, refresh_technician, req_dt, req_enum,
                    req_str, touch, vehicle_claims, vehicle_thermal_events)

bp = Blueprint("claim", __name__, url_prefix=API_PREFIX)

REMEDIES = ("MODULE_REPLACEMENT", "PACK_REPLACEMENT", "SOFTWARE_REMEDIATION")
DECISIONS = ("MODULE_REPLACEMENT", "PACK_REPLACEMENT", "SOFTWARE_REMEDIATION", "DENIED")
INVALID_DIAGNOSTICS = ("STALE_TELEMETRY", "INSUFFICIENT_DATA", "BENCH_OUT_OF_RANGE")
APPROVED_STATES = ("APPROVED_MODULE", "APPROVED_PACK", "APPROVED_SOFTWARE")
BLOCKING_CENTER_STATUSES = ("SHIPPING_SUSPENDED", "DECERTIFIED")


def _filter_eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


# ================================================================ claim filing
@bp.route("/warranty-claims", methods=["POST"])
def create_claim():
    role, user_id = auth((R_TECH,))
    body = get_body()
    vehicle_id = req_str(body, "vehicle_id")
    center_id = req_str(body, "service_center_id")
    assessment_id = req_str(body, "assessment_id")
    technician_id = req_str(body, "diagnosing_technician_id")
    if user_id != technician_id:
        raise forbidden("X-User-ID must equal diagnosing_technician_id.")
    # Body foreign keys resolve in the order the fields are declared on the entity.
    vehicle = must("vehicles", vehicle_id)
    center = must("centers", center_id)
    assessment = must("assessments", assessment_id)
    technician = refresh_technician(must("technicians", technician_id))
    program = db.programs[vehicle["warranty_program_id"]]

    # 30 -- assessment integrity first: on an invalid diagnostic the retention and
    # coverage fields are null, so the money comparisons below would be meaningless.
    if assessment["superseded"]:
        raise ApiError("ERR_ASSESSMENT_SUPERSEDED", 409,
                       "The backing assessment has been superseded.")
    for other in db.claims.values():
        if other["assessment_id"] == assessment_id and other["adjudication_status"] != "CLOSED":
            raise ApiError("ERR_ASSESSMENT_ALREADY_CLAIMED", 409,
                           "The assessment is already cited by an open claim.")
    if assessment["diagnostic_validity"] in INVALID_DIAGNOSTICS:
        raise ApiError("ERR_DIAGNOSTIC_NOT_VALID", 409,
                       "The backing diagnostic is not VALID.")
    if assessment["vehicle_id"] != vehicle_id:
        raise ApiError("ERR_ASSESSMENT_VEHICLE_MISMATCH", 422,
                       "The assessment describes a different vehicle.")
    if technician["service_center_id"] != center_id:
        raise ApiError("ERR_TECHNICIAN_CENTER_MISMATCH", 422,
                       "The technician does not belong to the named center.")
    if technician["status"] == "CERT_LAPSED":
        raise ApiError("ERR_TECHNICIAN_CERT_EXPIRED", 409,
                       "The diagnosing technician's certification has expired.")
    for other in vehicle_claims(vehicle_id):
        if other["adjudication_status"] != "CLOSED":
            raise ApiError("ERR_CLAIM_ALREADY_OPEN", 409,
                           "The vehicle already carries a non-closed claim.")
    applicable = assessment["applicable_min_retention_pct"]
    retention = assessment["retention_pct"]
    if applicable is not None and retention is not None:
        if D(retention) > D(applicable):
            raise ApiError("ERR_RETENTION_ABOVE_THRESHOLD", 409,
                           "Retention is above the applicable threshold.")
    if assessment["coverage_position"] == "OUT_OF_COVERAGE":
        raise ApiError("ERR_OUT_OF_COVERAGE", 409, "The vehicle is out of coverage.")
    # Two further preconditions are conflicts without a dedicated identifier.
    if vehicle["warranty_hold"]:
        raise ApiError("ERR_VEHICLE_WARRANTY_HOLD", 409,
                       "The vehicle stands under a warranty hold.")
    for event in vehicle_thermal_events(vehicle_id):
        if event["event_status"] == "OPEN":
            raise ApiError("ERR_THERMAL_EVENT_OPEN", 409,
                           "A thermal event on this vehicle is still open.")
    if center["status"] == "DECERTIFIED":
        raise ApiError("ERR_CENTER_DECERTIFIED", 409,
                       "The center of record is decertified.")

    record = new_record()
    record.update({
        "vehicle_id": vehicle_id,
        "service_center_id": center_id,
        "assessment_id": assessment_id,
        "diagnosing_technician_id": technician_id,
        "replacement_pack_id": None,
        "fulfilment_technician_id": None,
        "linked_campaign_id": None,
        "adjudication_status": "SUBMITTED",
        "recommended_remedy": None,
        "approved_remedy": None,
        "recommendation_basis": None,
        "info_request_round": 0,
        "settlement_variant": None,
        "remedy_cost_cents": None,
        "proration_factor": None,
        "owner_share_cents": None,
        "oem_share_cents": None,
        "admin_fee_cents": None,
        "oem_total_cents": None,
        "adjudicated_by_user_id": None,
        "fulfilment_blocked": center["status"] in BLOCKING_CENTER_STATUSES,
        "hv_bay_window_start": None,
        "hv_bay_window_end": None,
        "denial_reason": None,
        "reopened_count": 0,
        "pack_shipment_required": False,
    })
    svc.recompute_recommendation(record)
    db.claims[record["id"]] = record
    return ok(record, 201)


@bp.route("/warranty-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    auth(READ_ROLES)
    return ok(must("claims", claim_id))


@bp.route("/warranty-claims", methods=["GET"])
def list_claims():
    auth(READ_ROLES)
    limit, offset = pagination()
    rows = by_created(list(db.claims.values()))
    for field in ("vehicle_id", "service_center_id", "assessment_id",
                  "diagnosing_technician_id", "fulfilment_technician_id",
                  "replacement_pack_id", "linked_campaign_id", "adjudication_status"):
        rows = _filter_eq(rows, field, request.args.get(field))
    window, total = page(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/warranty-claims/<claim_id>/capacity-disputes", methods=["GET"])
def list_claim_disputes(claim_id):
    auth(READ_ROLES)
    limit, offset = pagination()
    must("claims", claim_id)
    rows = claim_disputes(claim_id)
    rows = _filter_eq(rows, "dispute_status", request.args.get("dispute_status"))
    window, total = page(rows, limit, offset)
    return ok_list(window, limit, offset, total)


# ====================================================== information round trip
@bp.route("/warranty-claims/<claim_id>/request-info", methods=["POST"])
def request_info(claim_id):
    auth((R_ADJ,))
    body = get_body()
    opt_str(body, "reason_note")
    claim = must("claims", claim_id)
    svc.guard_terminal(claim)
    if claim["adjudication_status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_ADJUDICABLE", 409,
                       "Only a SUBMITTED claim may be sent back for information.")
    program = svc.program_of(claim)
    if claim["info_request_round"] >= program["info_request_limit"]:
        raise ApiError("ERR_INFO_REQUEST_LIMIT_EXCEEDED", 409,
                       "The information-request limit for this program is exhausted.")
    claim["adjudication_status"] = "INFO_REQUESTED"
    claim["info_request_round"] = claim["info_request_round"] + 1
    touch(claim)
    return ok(claim)


@bp.route("/warranty-claims/<claim_id>/resubmit", methods=["POST"])
def resubmit(claim_id):
    role, user_id = auth((R_TECH,))
    body = get_body()
    assessment_id = opt_id(body, "assessment_id")
    opt_str(body, "note")
    claim = must("claims", claim_id)
    if user_id != claim["diagnosing_technician_id"]:
        raise forbidden("Only the diagnosing technician may resubmit this claim.")
    replacement = fk("assessments", assessment_id)
    svc.guard_terminal(claim)
    if claim["adjudication_status"] != "INFO_REQUESTED":
        raise ApiError("ERR_INFO_REQUEST_NOT_OPEN", 409,
                       "No information request is open on this claim.")
    if replacement is not None:
        if replacement["superseded"]:
            raise ApiError("ERR_ASSESSMENT_SUPERSEDED", 409,
                           "The replacement assessment has been superseded.")
        if replacement["diagnostic_validity"] != "VALID":
            raise ApiError("ERR_DIAGNOSTIC_NOT_VALID", 409,
                           "The replacement diagnostic is not VALID.")
        if replacement["vehicle_id"] != claim["vehicle_id"]:
            raise ApiError("ERR_ASSESSMENT_VEHICLE_MISMATCH", 422,
                           "The replacement assessment describes a different vehicle.")
        if not replacement["qualifies_for_claim"]:
            if replacement["coverage_position"] == "OUT_OF_COVERAGE":
                raise ApiError("ERR_OUT_OF_COVERAGE", 409,
                               "The replacement assessment is out of coverage.")
            raise ApiError("ERR_RETENTION_ABOVE_THRESHOLD", 409,
                           "The replacement assessment does not qualify for a claim.")
        claim["assessment_id"] = replacement["id"]
    claim["adjudication_status"] = "SUBMITTED"
    svc.recompute_recommendation(claim)
    touch(claim)
    return ok(claim)


# ================================================================ adjudication
def _center_tier_ok(center, remedy):
    rank = CERT_RANK[center["hv_certification_level"]]
    if remedy == "PACK_REPLACEMENT":
        return rank == CERT_RANK["L3"]
    if remedy == "MODULE_REPLACEMENT":
        return rank >= CERT_RANK["L2"]
    return True


def _named_pack_ok(pack, program):
    if pack["status"] != "STOCK":
        return False
    if pack["installed_vehicle_id"] is not None:
        return False
    if pack["pack_type"] == "REMANUFACTURED":
        if pack["refurb_soh_pct"] is None:
            return False
        if D(pack["refurb_soh_pct"]) < D(program["reman_min_soh_pct"]):
            return False
    return True


@bp.route("/warranty-claims/<claim_id>/adjudicate", methods=["POST"])
def adjudicate(claim_id):
    role, user_id = auth((R_ADJ,), actor_required=True)
    body = get_body()
    approved = req_enum(body, "approved_remedy", DECISIONS)
    named_pack_id = opt_id(body, "replacement_pack_id")
    campaign_id = opt_id(body, "linked_campaign_id")
    justification = opt_str(body, "override_justification")
    opt_str(body, "decision_note")
    if approved == "SOFTWARE_REMEDIATION" and campaign_id is None:
        raise invalid("linked_campaign_id is required to approve a software remediation.")
    claim = must("claims", claim_id)
    named_pack = fk("packs", named_pack_id)
    campaign = fk("campaigns", campaign_id)
    svc.guard_terminal(claim)
    if claim["adjudication_status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_ADJUDICABLE", 409,
                       "Only a SUBMITTED claim may be adjudicated.")
    recommended = claim["recommended_remedy"]
    basis = claim["recommendation_basis"]
    if approved != recommended and not justification:
        raise invalid("override_justification is required to depart from the "
                      "recommended remedy.")
    vehicle = svc.vehicle_of(claim)
    center = svc.center_of(claim)
    program = svc.program_of(claim)
    removed = svc.pack_of(claim)
    if approved == "SOFTWARE_REMEDIATION":
        if campaign["status"] not in cascade.RELEASED_STATUSES:
            raise ApiError("ERR_CAMPAIGN_NOT_RELEASED", 409,
                           "The linked campaign is not released.")
        if campaign["applies_to_model_code"] != vehicle["model_code"]:
            raise ApiError("ERR_VEHICLE_NOT_TARGETED", 422,
                           "The campaign does not target this vehicle's model code.")
    if named_pack is not None and approved == "PACK_REPLACEMENT":
        if (named_pack["stock_region_code"] != center["region_code"]
                or named_pack["module_count"] != removed["module_count"]):
            raise ApiError("ERR_PACK_REGION_MISMATCH", 422,
                           "The named replacement pack does not match the center "
                           "region or the removed pack's module count.")
    if not _center_tier_ok(center, approved):
        raise ApiError("ERR_CENTER_CERT_LEVEL_INSUFFICIENT", 409,
                       "The center's certification level is insufficient for %s." % approved)
    if approved == "PACK_REPLACEMENT" and not center["has_pack_lift"]:
        raise ApiError("ERR_PACK_LIFT_REQUIRED", 409,
                       "A certified pack lift is required for a pack replacement.")
    if (recommended == "PACK_REPLACEMENT" and basis in ("THERMAL_HISTORY", "CELL_DELTA")
            and approved in REMEDIES
            and svc.REMEDY_STRENGTH[approved] < svc.REMEDY_STRENGTH["PACK_REPLACEMENT"]):
        raise ApiError("ERR_REMEDY_OVERRIDE_FORBIDDEN", 409,
                       "A %s pack recommendation may not be downgraded." % basis)

    chosen = None
    if approved == "PACK_REPLACEMENT":
        if named_pack is not None:
            if not _named_pack_ok(named_pack, program):
                raise ApiError("ERR_PACK_NOT_IN_STOCK", 409,
                               "The named replacement pack is not free stock of "
                               "acceptable health.")
            chosen = named_pack
        else:
            chosen = calc.select_replacement_pack(program, center, removed)
            if chosen is None:
                raise ApiError("ERR_NO_REMAN_PACK_AVAILABLE", 409,
                               "No eligible replacement pack is available.")

    if approved == "DENIED":
        claim["adjudication_status"] = "DENIED"
        claim["approved_remedy"] = "DENIED"
        claim["denial_reason"] = "ADJUDICATOR_DECISION"
        svc.zero_money(claim)
        claim["adjudicated_by_user_id"] = user_id
        claim["_adjudicated_at"] = now()
        touch(claim)
        return ok(claim)

    # The fiscal ceiling is checked last so that no money rule can mask a
    # safety, referential or constraint failure.
    fields = svc.compute_settlement(claim, approved, chosen)
    if program["accrued_liability_cents"] + fields["oem_total_cents"] > program["liability_cap_cents"]:
        raise ApiError("ERR_LIABILITY_CAP_EXCEEDED", 409,
                       "The program's liability ceiling would be exceeded.")

    if approved == "PACK_REPLACEMENT":
        claim["replacement_pack_id"] = chosen["id"]
        claim["adjudication_status"] = "APPROVED_PACK"
        svc.reserve_pack(chosen)
    elif approved == "MODULE_REPLACEMENT":
        claim["adjudication_status"] = "APPROVED_MODULE"
    else:
        claim["adjudication_status"] = "APPROVED_SOFTWARE"
        claim["linked_campaign_id"] = campaign["id"]
    claim["approved_remedy"] = approved
    svc.write_settlement(claim, fields)
    claim["adjudicated_by_user_id"] = user_id
    claim["_adjudicated_at"] = now()
    touch(claim)
    if approved == "SOFTWARE_REMEDIATION":
        if cascade.any_consent(campaign["id"], vehicle["id"]) is None:
            cascade.create_consent(campaign, vehicle)
            cascade.refresh_campaign(campaign)
    cascade.refresh_accrual(program)
    return ok(claim)


# =================================================================== fulfilment
FULFIL_STATUS = {"APPROVED_MODULE": "MODULE_REPLACEMENT",
                 "APPROVED_PACK": "PACK_REPLACEMENT",
                 "APPROVED_SOFTWARE": "SOFTWARE_REMEDIATION"}


def _tech_tier_ok(technician, remedy):
    rank = CERT_RANK[technician["hv_cert_level"]]
    if remedy == "PACK_REPLACEMENT":
        return rank == CERT_RANK["L3"]
    if remedy == "MODULE_REPLACEMENT":
        return rank >= CERT_RANK["L2"]
    return rank >= CERT_RANK["L1"]


def _containment_open(pack_id, severities):
    from common import pack_thermal_events
    for event in pack_thermal_events(pack_id):
        if event["severity"] in severities and event["containment_status"] != "CONTAINMENT_CLOSED":
            return True
    return False


@bp.route("/warranty-claims/<claim_id>/fulfil", methods=["POST"])
def fulfil(claim_id):
    role, user_id = auth((R_TECH,), actor_required=True)
    body = get_body()
    technician_id = req_str(body, "fulfilment_technician_id")
    start = req_dt(body, "hv_bay_window_start")
    end = req_dt(body, "hv_bay_window_end")
    if user_id != technician_id:
        raise forbidden("X-User-ID must equal fulfilment_technician_id.")
    claim = must("claims", claim_id)
    technician = refresh_technician(must("technicians", technician_id))
    svc.guard_terminal(claim)
    if claim["adjudication_status"] not in APPROVED_STATES or claim["fulfilment_blocked"]:
        raise ApiError("ERR_CLAIM_NOT_FULFILLABLE", 409,
                       "The claim is not in a fulfillable state.")
    remedy = FULFIL_STATUS[claim["adjudication_status"]]
    hardware = remedy in ("MODULE_REPLACEMENT", "PACK_REPLACEMENT")
    center = svc.center_of(claim)
    vehicle = svc.vehicle_of(claim)
    assessed_pack = svc.pack_of(claim)
    if technician["service_center_id"] != claim["service_center_id"]:
        raise ApiError("ERR_TECHNICIAN_CENTER_MISMATCH", 422,
                       "The technician does not belong to the claim's center of record.")
    if center["status"] != "ACTIVE":
        raise ApiError("ERR_CENTER_NOT_CERTIFIED", 409,
                       "The center of record is not ACTIVE.")
    if not _center_tier_ok(center, remedy):
        raise ApiError("ERR_CENTER_CERT_LEVEL_INSUFFICIENT", 409,
                       "The center's certification level is insufficient for %s." % remedy)
    if remedy == "PACK_REPLACEMENT" and not center["has_pack_lift"]:
        raise ApiError("ERR_PACK_LIFT_REQUIRED", 409,
                       "A certified pack lift is required for a pack replacement.")
    if hardware and center["insulation_tester_cal_due_at"] <= now():
        raise ApiError("ERR_INSULATION_TESTER_OVERDUE", 409,
                       "The insulation resistance tester's calibration is overdue.")
    if technician["status"] == "CERT_LAPSED":
        raise ApiError("ERR_TECHNICIAN_CERT_EXPIRED", 409,
                       "The technician's high-voltage certification has expired.")
    if not _tech_tier_ok(technician, remedy):
        raise ApiError("ERR_TECHNICIAN_LEVEL_INSUFFICIENT", 409,
                       "The technician's certification level is insufficient for %s." % remedy)
    if _containment_open(assessed_pack["id"], ("S3", "S4")):
        raise ApiError("ERR_THERMAL_CONTAINMENT_OPEN", 409,
                       "A severe thermal event on this pack is still uncontained.")
    removed = db.packs.get(vehicle["installed_pack_id"]) or assessed_pack
    if remedy == "PACK_REPLACEMENT" and removed["status"] == "QUARANTINED":
        if _containment_open(removed["id"], ("S1", "S2", "S3", "S4")):
            raise ApiError("ERR_THERMAL_CONTAINMENT_OPEN", 409,
                           "Every thermal event on a quarantined pack must be closed "
                           "before removal.")
    if end <= start:
        raise ApiError("ERR_INVALID_BAY_WINDOW", 400,
                       "hv_bay_window_end must be strictly later than hv_bay_window_start.")
    if calc.bay_occupancy(center["id"], start, end, exclude_claim_id=claim["id"]) >= center["hv_bay_count"]:
        raise ApiError("ERR_HV_BAY_CAPACITY_EXCEEDED", 409,
                       "Every high-voltage bay at this center is occupied for that window.")
    if calc.cooldown_conflict(technician, start):
        raise ApiError("ERR_TECHNICIAN_COOLDOWN_CONFLICT", 409,
                       "The technician's sixty-minute cooldown has not elapsed.")
    replacement = None
    if remedy == "PACK_REPLACEMENT":
        replacement = db.packs.get(claim["replacement_pack_id"])
        if replacement is None or replacement["status"] != "RESERVED":
            raise ApiError("ERR_PACK_NOT_IN_STOCK", 409,
                           "The reserved replacement pack is no longer reserved.")

    claim["adjudication_status"] = "FULFILLED"
    claim["fulfilment_technician_id"] = technician_id
    claim["hv_bay_window_start"] = start
    claim["hv_bay_window_end"] = end
    claim["pack_shipment_required"] = bool(hardware)
    touch(claim)
    last = technician.get("last_hv_window_end_at")
    technician["last_hv_window_end_at"] = end if (last is None or end > last) else last
    touch(technician)
    if remedy == "MODULE_REPLACEMENT":
        for module in pack_modules(assessed_pack["id"]):
            if module["status"] == "FAULTED":
                module["status"] = "REPLACED"
                module["replaced_at"] = now()
                touch(module)
        cascade.refresh_pack_counters(assessed_pack)
    elif remedy == "PACK_REPLACEMENT":
        removed["status"] = "REMOVED"
        removed["installed_vehicle_id"] = None
        removed["_last_vehicle_id"] = vehicle["id"]
        touch(removed)
        replacement["status"] = "IN_SERVICE"
        replacement["installed_vehicle_id"] = claim["vehicle_id"]
        replacement["superseded_pack_id"] = removed["id"]
        replacement["_last_vehicle_id"] = vehicle["id"]
        touch(replacement)
        vehicle["installed_pack_id"] = replacement["id"]
        vehicle["warranty_hold"] = False
        vehicle["status"] = "ACTIVE"
        touch(vehicle)
        cascade.refresh_reman_stock()
    cascade.refresh_accrual(svc.program_of(claim))
    return ok(claim)


# ====================================================================== closure
OPEN_DISPUTE_STATUSES = ("LAB_ASSIGNED", "LAB_RESULT_RECEIVED")


@bp.route("/warranty-claims/<claim_id>/close", methods=["POST"])
def close_claim(claim_id):
    auth((R_ADJ,))
    body = get_body()
    opt_str(body, "closure_note")
    claim = must("claims", claim_id)
    svc.guard_terminal(claim)
    if claim["adjudication_status"] not in ("FULFILLED", "DENIED"):
        raise ApiError("ERR_CLAIM_NOT_CLOSABLE", 409,
                       "Only a FULFILLED or DENIED claim may be closed.")
    if claim["adjudication_status"] == "FULFILLED" and claim["pack_shipment_required"]:
        removed = svc.pack_of(claim)
        received = [s for s in db.shipments.values()
                    if s["pack_id"] == removed["id"] and s["status"] == "RECEIVED"]
        if not received:
            raise ApiError("ERR_CLAIM_NOT_CLOSABLE", 409,
                           "The removed pack's shipment has not been received.")
    if claim["adjudication_status"] == "DENIED":
        for dispute in claim_disputes(claim["id"]):
            if dispute["dispute_status"] in OPEN_DISPUTE_STATUSES:
                raise ApiError("ERR_CLAIM_NOT_CLOSABLE", 409,
                               "A capacity dispute on this claim is still open.")
    claim["adjudication_status"] = "CLOSED"
    touch(claim)
    cascade.refresh_accrual(svc.program_of(claim))
    return ok(claim)
