"""Routes: interpreting requests, assignments (offers), encounters."""
import math
from datetime import timedelta

from flask import Blueprint

import core
from core import (DB, now, auth_ctx, require_role, check_ownership, get_body,
                  envelope, paginate, sort_by_created, req_str, opt_str,
                  req_enum, opt_enum, req_dt, opt_dt, opt_int, opt_num, err,
                  new_id)
from domain import (MODALITIES, ADA_CONTEXTS, REQUIRED_CREDENTIAL, LEVEL_RANK,
                    touch, ser_request, ser_assignment, ser_encounter,
                    get_request, get_assignment, get_encounter, get_org,
                    get_interpreter, outstanding_offer, encounter_of_assignment,
                    request_rematch_or_unfilled, compute_estimated_cost,
                    select_rate_card, availability_covers,
                    compute_cancellation_fee, fiscal_gate, cancel_request_tree,
                    record_strike, lazy_expire_assignment, lazy_expire_all,
                    interpreter_quality, org_outstanding_balance,
                    create_fee_only_invoice, ser_invoice, ser_complaint,
                    ser_strike, invoice_of_assignment)
from domain import TRAVEL_BUFFER_MIN, VRI_MAX_CONCURRENT_SESSIONS

bp = Blueprint("flow", __name__)


# --------------------------------------------------------------------------
# InterpretingRequest
# --------------------------------------------------------------------------
@bp.route("/requests", methods=["POST"])
def create_request():
    auth = auth_ctx()
    body = get_body(allowed_fields={"org_id", "consumer_name", "modality",
                                    "ada_context", "scheduled_start",
                                    "scheduled_end", "onsite_address",
                                    "estimated_mileage"}, require=True)
    require_role(auth[1], "OrgRequester")
    org_id = req_str(body, "org_id")
    check_ownership(org_id == auth[0])
    consumer_name = req_str(body, "consumer_name")
    modality = req_enum(body, "modality", MODALITIES)
    ada_context = opt_enum(body, "ada_context", ADA_CONTEXTS, "GENERAL")
    scheduled_start = req_dt(body, "scheduled_start")
    scheduled_end = req_dt(body, "scheduled_end")
    onsite_address = opt_str(body, "onsite_address")
    estimated_mileage = opt_num(body, "estimated_mileage", 0, minimum=0)
    if modality in ("ASL_ONSITE", "CART_ONSITE") and not onsite_address:
        err(core.E_ONSITE_ADDR, 400,
            "onsite_address is required for on-site modalities")
    if scheduled_end <= scheduled_start:
        err(core.E_INVALID, 400, "scheduled_end must be later than scheduled_start")
    get_org(org_id)  # existence (tier 5)
    req = {
        "id": new_id(), "org_id": org_id, "consumer_name": consumer_name,
        "modality": modality, "ada_context": ada_context,
        "scheduled_start": scheduled_start, "scheduled_end": scheduled_end,
        "onsite_address": onsite_address,
        "estimated_mileage": estimated_mileage,
        "required_credential_level": REQUIRED_CREDENTIAL[ada_context],
        "status": "DRAFT", "offer_attempt_count": 0,
        "cancellation_fee_cents": None, "cancelled_at": None, "closed_at": None,
        "created_at": now(), "updated_at": now(), "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.requests[req["id"]] = req
    return envelope(ser_request(req), code=201)


@bp.route("/requests", methods=["GET"])
def list_requests():
    auth_ctx()
    lazy_expire_all()
    args = core.request.args
    items = list(DB.requests.values())
    for f in ("org_id", "status", "modality", "ada_context"):
        v = args.get(f)
        if v is not None:
            items = [r for r in items if r[f] == v]
    page, meta = paginate(sort_by_created(items))
    return envelope([ser_request(r) for r in page], pagination=meta)


@bp.route("/requests/<rid>", methods=["GET"])
def get_request_route(rid):
    auth_ctx()
    lazy_expire_all()
    return envelope(ser_request(get_request(rid)))


@bp.route("/requests/<rid>/submit", methods=["POST"])
def submit_request(rid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "OrgRequester")
    req = get_request(rid)
    check_ownership(req["org_id"] == auth[0])
    org = get_org(req["org_id"])
    if org["status"] != "ACTIVE":
        err(core.E_ORG_NOT_ACTIVE, 409, "Organization is not ACTIVE")
    if req["status"] != "DRAFT":
        err(core.E_REQ_NOT_DRAFT, 409, "Submit requires request status DRAFT")
    if (req["scheduled_end"] <= req["scheduled_start"]
            or req["scheduled_start"] < now() + timedelta(hours=2)):
        err(core.E_SCHEDULE, 422,
            "scheduled_end must be after scheduled_start and scheduled_start "
            "must be at least 2 hours in the future")
    req["status"] = "MATCHING"
    touch(req)
    return envelope(ser_request(req))


@bp.route("/requests/<rid>/cancel", methods=["POST"])
def cancel_request(rid):
    auth = auth_ctx()
    get_body(allowed_fields={"reason"})
    require_role(auth[1], "OrgRequester", "PlatformAdmin")
    req = get_request(rid)
    cancelled_by = "PLATFORM"
    if auth[1] == "OrgRequester":
        check_ownership(req["org_id"] == auth[0])
        org = get_org(req["org_id"])
        if org["status"] != "ACTIVE":
            err(core.E_ORG_NOT_ACTIVE, 409, "Organization is not ACTIVE")
        cancelled_by = "REQUESTER"
    if req["status"] not in ("DRAFT", "MATCHING", "OFFERED", "CONFIRMED"):
        err(core.E_REQ_NOT_CANCELLABLE, 409,
            "Cancel requires status DRAFT, MATCHING, OFFERED, or CONFIRMED")
    cancel_request_tree(req, cancelled_by)
    return envelope(ser_request(req))


@bp.route("/requests/<rid>/offers", methods=["POST"])
def create_offer(rid):
    auth = auth_ctx()
    body = get_body(allowed_fields={"interpreter_id",
                                    "expected_request_version"}, require=True)
    require_role(auth[1], "PlatformAdmin")
    interpreter_id = req_str(body, "interpreter_id")
    expected_version = core.req_int(body, "expected_request_version")
    req = get_request(rid)
    interp = get_interpreter(interpreter_id)
    # OCC (tier 6)
    if expected_version != req["version"]:
        err(core.E_STALE_REQUEST, 412,
            "expected_request_version does not match the request's current version")
    # Posture (tier 7)
    if interp["status"] != "ACTIVE":
        err(core.E_INTERP_NOT_ACTIVE, 409, "Interpreter is not ACTIVE")
    # From-state (tier 8)
    if req["status"] not in ("MATCHING", "OFFERED"):
        err(core.E_REQ_NOT_OFFERABLE, 409,
            "Offer requires request status MATCHING or OFFERED")
    # ADA credential/match gate (tier 9, fixed sub-order)
    if req["modality"] not in interp["modalities_offered"]:
        err(core.E_MODALITY, 422, "Modality is not in interpreter.modalities_offered")
    if req["modality"] == "VRI" and not interp["vri_platform_certified"]:
        err(core.E_VRI_CERT, 422, "VRI assignment requires vri_platform_certified")
    sufficient = False
    for c in DB.certifications.values():
        if (c["interpreter_id"] == interp["id"] and c["verified"]
                and LEVEL_RANK[c["level"]] >= LEVEL_RANK[req["required_credential_level"]]
                and c["expires_on"] >= req["scheduled_start"]):
            sufficient = True
            break
    if not sufficient:
        err(core.E_CREDENTIAL, 422,
            "No verified certification with sufficient level and expiry")
    quality, _ = interpreter_quality(interp["id"])
    if quality < 40:
        err(core.E_QUALITY, 422, "Interpreter quality_score is below 40")
    # Structural (tier 11)
    if req["offer_attempt_count"] >= 3:
        err(core.E_MAX_OFFERS, 409, "Maximum of 3 offer attempts reached")
    if not availability_covers(interp["id"], req):
        err(core.E_NO_COVERAGE, 422,
            "Availability windows do not fully cover the scheduled span")
    # Rate card selection + provisional estimate
    card = select_rate_card(req)
    estimated = compute_estimated_cost(req, card)
    # Fiscal gate (tier 12)
    fiscal_gate(get_org(req["org_id"]), estimated)
    # Supersede an outstanding offer
    old = outstanding_offer(req)
    if old is not None:
        old["status"] = "CANCELLED"
        old["cancelled_by"] = "SYSTEM"
        touch(old)
    offered_at = now()
    assignment = {
        "id": new_id(), "request_id": req["id"],
        "interpreter_id": interp["id"],
        "rate_card_id": card["id"], "rate_card_version": card["version"],
        "status": "OFFERED",
        "offered_at": offered_at,
        "response_deadline": min(req["scheduled_start"],
                                 offered_at + timedelta(hours=24)),
        "accepted_at": None,
        "pinned_hourly_rate_cents": card["hourly_rate_cents"],
        "pinned_minimum_billable_minutes": card["minimum_billable_minutes"],
        "pinned_travel_rate_cents_per_hour": card["travel_rate_cents_per_hour"],
        "pinned_mileage_rate_cents_per_mile": card["mileage_rate_cents_per_mile"],
        "pinned_vri_platform_fee_cents_per_min": card["vri_platform_fee_cents_per_min"],
        "pinned_cancel_full_refund_notice_hours": card["cancel_full_refund_notice_hours"],
        "pinned_cancel_partial_notice_hours": card["cancel_partial_notice_hours"],
        "pinned_late_cancel_fee_pct": card["late_cancel_fee_pct"],
        "estimated_cost_cents": estimated,
        "cancelled_by": None, "cancel_notice_hours": None,
        "cancellation_fee_cents": None, "no_show_marked_at": None,
        "travel_minutes_claimed": 0, "mileage_claimed": 0,
        "created_at": now(), "updated_at": now(), "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.assignments[assignment["id"]] = assignment
    req["offer_attempt_count"] += 1
    req["status"] = "OFFERED"
    touch(req)
    return envelope(ser_assignment(assignment), code=201)


@bp.route("/requests/<rid>/offers", methods=["GET"])
def list_request_offers(rid):
    auth_ctx()
    lazy_expire_all()
    get_request(rid)
    status = core.request.args.get("status")
    items = [a for a in DB.assignments.values() if a["request_id"] == rid]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, meta = paginate(sort_by_created(items))
    return envelope([ser_assignment(a) for a in page], pagination=meta)


# --------------------------------------------------------------------------
# Assignment
# --------------------------------------------------------------------------
@bp.route("/assignments", methods=["GET"])
def list_assignments():
    auth_ctx()
    lazy_expire_all()
    args = core.request.args
    items = list(DB.assignments.values())
    for f in ("request_id", "interpreter_id", "rate_card_id", "status"):
        v = args.get(f)
        if v is not None:
            items = [a for a in items if a[f] == v]
    page, meta = paginate(sort_by_created(items))
    return envelope([ser_assignment(a) for a in page], pagination=meta)


@bp.route("/assignments/<aid>", methods=["GET"])
def get_assignment_route(aid):
    auth_ctx()
    a = get_assignment(aid)
    lazy_expire_assignment(a)
    return envelope(ser_assignment(a))


def _interpreter_owned_assignment(aid, auth):
    a = get_assignment(aid)
    lazy_expire_assignment(a)
    check_ownership(a["interpreter_id"] == auth[0])
    return a


@bp.route("/assignments/<aid>/accept", methods=["POST"])
def accept_assignment(aid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "Interpreter")
    a = _interpreter_owned_assignment(aid, auth)
    interp = get_interpreter(a["interpreter_id"])
    if interp["status"] != "ACTIVE":
        err(core.E_INTERP_NOT_ACTIVE, 409, "Interpreter is not ACTIVE")
    if a["status"] != "OFFERED":
        err(core.E_ASN_NOT_OFFERED, 409, "Accept requires assignment status OFFERED")
    if now() >= a["response_deadline"]:
        lazy_expire_assignment(a)
        err(core.E_ASN_NOT_OFFERED, 409, "The offer has expired")
    a["status"] = "ACCEPTED"
    a["accepted_at"] = now()
    touch(a)
    return envelope(ser_assignment(a))


@bp.route("/assignments/<aid>/decline", methods=["POST"])
def decline_assignment(aid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "Interpreter")
    a = _interpreter_owned_assignment(aid, auth)
    if a["status"] != "OFFERED":
        err(core.E_ASN_NOT_OFFERED, 409, "Decline requires assignment status OFFERED")
    a["status"] = "DECLINED"
    touch(a)
    req = DB.requests.get(a["request_id"])
    if req is not None and req["status"] == "OFFERED":
        request_rematch_or_unfilled(req)
    return envelope(ser_assignment(a))


@bp.route("/assignments/<aid>/confirm", methods=["POST"])
def confirm_assignment(aid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "PlatformAdmin")
    a = get_assignment(aid)
    req = get_request(a["request_id"])
    interp = get_interpreter(a["interpreter_id"])
    if interp["status"] != "ACTIVE":
        err(core.E_INTERP_NOT_ACTIVE, 409, "Interpreter is not ACTIVE")
    if a["status"] != "ACCEPTED":
        err(core.E_ASN_NOT_ACCEPTED, 409, "Confirm requires assignment status ACCEPTED")
    # Buffered double-booking check (half-open, 30 min each side)
    new_start = req["scheduled_start"] - timedelta(minutes=TRAVEL_BUFFER_MIN)
    new_end = req["scheduled_end"] + timedelta(minutes=TRAVEL_BUFFER_MIN)
    for other in DB.assignments.values():
        if (other["id"] == a["id"]
                or other["interpreter_id"] != a["interpreter_id"]
                or other["status"] not in ("CONFIRMED", "EN_ROUTE", "ON_SITE")):
            continue
        o_req = DB.requests.get(other["request_id"])
        if o_req is None:
            continue
        o_start = o_req["scheduled_start"] - timedelta(minutes=TRAVEL_BUFFER_MIN)
        o_end = o_req["scheduled_end"] + timedelta(minutes=TRAVEL_BUFFER_MIN)
        if new_start < o_end and new_end > o_start:
            err(core.E_DOUBLE_BOOKED, 409,
                "Confirm would double-book the interpreter within the travel buffer")
    # VRI aggregate capacity (platform-wide, half-open overlap)
    if req["modality"] == "VRI":
        overlapping = 0
        for other in DB.assignments.values():
            if (other["id"] == a["id"]
                    or other["status"] not in ("CONFIRMED", "EN_ROUTE", "ON_SITE")):
                continue
            o_req = DB.requests.get(other["request_id"])
            if o_req is None or o_req["modality"] != "VRI":
                continue
            if (o_req["scheduled_start"] < req["scheduled_end"]
                    and o_req["scheduled_end"] > req["scheduled_start"]):
                overlapping += 1
        if overlapping >= VRI_MAX_CONCURRENT_SESSIONS:
            err(core.E_VRI_CAPACITY, 409,
                "Confirm would exceed the VRI concurrent-session capacity")
    fiscal_gate(get_org(req["org_id"]), a["estimated_cost_cents"])
    a["status"] = "CONFIRMED"
    touch(a)
    if req["status"] == "OFFERED":
        req["status"] = "CONFIRMED"
        touch(req)
    return envelope(ser_assignment(a))


@bp.route("/assignments/<aid>/depart", methods=["POST"])
def depart_assignment(aid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "Interpreter")
    a = _interpreter_owned_assignment(aid, auth)
    req = get_request(a["request_id"])
    if req["modality"] == "VRI":
        err(core.E_INVALID, 400, "VRI assignments cannot depart")
    if a["status"] != "CONFIRMED":
        err(core.E_ASN_NOT_CONFIRMED, 409, "Depart requires assignment status CONFIRMED")
    a["status"] = "EN_ROUTE"
    touch(a)
    return envelope(ser_assignment(a))


@bp.route("/assignments/<aid>/check-in", methods=["POST"])
def check_in_assignment(aid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "Interpreter")
    a = _interpreter_owned_assignment(aid, auth)
    req = get_request(a["request_id"])
    if req["modality"] == "VRI":
        ok_states = ("CONFIRMED",)
    else:
        ok_states = ("EN_ROUTE",)
    if a["status"] not in ok_states:
        err(core.E_ASN_NOT_CONFIRMED, 409,
            "Check-in requires CONFIRMED (VRI) or EN_ROUTE (on-site)")
    if not (req["scheduled_start"] - timedelta(minutes=30)
            <= now() <= req["scheduled_end"]):
        err(core.E_CHECKIN_WINDOW, 422,
            "Check-in outside [scheduled_start - 30min, scheduled_end]")
    a["status"] = "ON_SITE"
    touch(a)
    encounter = {
        "id": new_id(), "assignment_id": a["id"],
        "modality_delivered": req["modality"],
        "actual_start": now(), "actual_end": None,
        "actual_minutes": None, "billable_minutes": None,
        "verified": False, "verify_deadline": None, "verified_by": None,
        "corrected_start": None, "corrected_end": None,
        "created_at": now(), "updated_at": now(), "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.encounters[encounter["id"]] = encounter
    if req["status"] == "CONFIRMED":
        req["status"] = "IN_PROGRESS"
        touch(req)
    return envelope(ser_assignment(a))


@bp.route("/assignments/<aid>/check-out", methods=["POST"])
def check_out_assignment(aid):
    auth = auth_ctx()
    body = get_body(allowed_fields={"travel_minutes_claimed", "mileage_claimed"})
    require_role(auth[1], "Interpreter")
    travel_claimed = opt_int(body, "travel_minutes_claimed", 0, minimum=0)
    mileage_claimed = opt_num(body, "mileage_claimed", 0, minimum=0)
    a = _interpreter_owned_assignment(aid, auth)
    if a["status"] != "ON_SITE":
        err(core.E_ASN_NOT_ON_SITE, 409, "Check-out requires assignment status ON_SITE")
    a["travel_minutes_claimed"] = travel_claimed
    a["mileage_claimed"] = mileage_claimed
    a["status"] = "COMPLETED"
    touch(a)
    encounter = encounter_of_assignment(a["id"])
    encounter["actual_end"] = now()
    elapsed = (encounter["actual_end"] - encounter["actual_start"]).total_seconds()
    encounter["actual_minutes"] = math.ceil(elapsed / 60)
    encounter["billable_minutes"] = max(encounter["actual_minutes"],
                                        a["pinned_minimum_billable_minutes"])
    encounter["verify_deadline"] = encounter["actual_end"] + timedelta(hours=72)
    touch(encounter)
    return envelope(ser_assignment(a))


@bp.route("/assignments/<aid>/cancel", methods=["POST"])
def cancel_assignment_route(aid):
    auth = auth_ctx()
    get_body(allowed_fields={"reason"})
    require_role(auth[1], "OrgRequester", "PlatformAdmin")
    a = get_assignment(aid)
    req = get_request(a["request_id"])
    cancelled_by = "PLATFORM"
    if auth[1] == "OrgRequester":
        check_ownership(req["org_id"] == auth[0])
        org = get_org(req["org_id"])
        if org["status"] != "ACTIVE":
            err(core.E_ORG_NOT_ACTIVE, 409, "Organization is not ACTIVE")
        cancelled_by = "REQUESTER"
    if a["status"] not in ("ACCEPTED", "CONFIRMED", "EN_ROUTE"):
        err(core.E_INVALID, 400,
            "Assignment cancel requires status ACCEPTED, CONFIRMED, or EN_ROUTE")
    fee, notice_hours = compute_cancellation_fee(a, req)
    a["status"] = "CANCELLED"
    a["cancelled_by"] = cancelled_by
    a["cancel_notice_hours"] = notice_hours
    a["cancellation_fee_cents"] = fee
    touch(a)
    if cancelled_by == "REQUESTER":
        req["status"] = "CANCELLED"
        req["cancellation_fee_cents"] = fee
        req["cancelled_at"] = now()
        touch(req)
        if fee > 0:
            create_fee_only_invoice(req, a, fee)
    else:
        if req["status"] in ("OFFERED", "CONFIRMED"):
            request_rematch_or_unfilled(req)
    return envelope(ser_assignment(a))


@bp.route("/assignments/<aid>/mark-no-show", methods=["POST"])
def mark_no_show(aid):
    auth = auth_ctx()
    get_body()
    require_role(auth[1], "PlatformAdmin")
    a = get_assignment(aid)
    req = get_request(a["request_id"])
    if a["status"] not in ("CONFIRMED", "EN_ROUTE"):
        err(core.E_ASN_NOT_CONFIRMED, 409,
            "Mark-no-show requires CONFIRMED or EN_ROUTE")
    if now() < req["scheduled_start"] + timedelta(minutes=15):
        err(core.E_NO_SHOW_EARLY, 422,
            "No-show cannot be marked before scheduled_start + 15 minutes")
    a["status"] = "NO_SHOW"
    a["no_show_marked_at"] = now()
    touch(a)
    # Strike cascade: create -> recompute -> auto-suspend at 3 -> suspension cascade
    record_strike(a["interpreter_id"], req["scheduled_start"], a["id"])
    # Re-match the no-showed request
    if req["status"] == "CONFIRMED":
        request_rematch_or_unfilled(req)
    return envelope(ser_assignment(a))


# --------------------------------------------------------------------------
# Assignment reverse-lookup listings
# --------------------------------------------------------------------------
@bp.route("/assignments/<aid>/encounters", methods=["GET"])
def assignment_encounters(aid):
    auth_ctx()
    get_assignment(aid)
    items = [e for e in DB.encounters.values() if e["assignment_id"] == aid]
    page, meta = paginate(sort_by_created(items))
    return envelope([ser_encounter(e) for e in page], pagination=meta)


@bp.route("/assignments/<aid>/invoices", methods=["GET"])
def assignment_invoices(aid):
    auth_ctx()
    get_assignment(aid)
    items = [inv for inv in DB.invoices.values() if inv["assignment_id"] == aid]
    page, meta = paginate(sort_by_created(items))
    return envelope([ser_invoice(inv) for inv in page], pagination=meta)


@bp.route("/assignments/<aid>/complaints", methods=["GET"])
def assignment_complaints(aid):
    auth_ctx()
    get_assignment(aid)
    status = core.request.args.get("status")
    items = [c for c in DB.complaints.values() if c["assignment_id"] == aid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(sort_by_created(items))
    return envelope([ser_complaint(c) for c in page], pagination=meta)


@bp.route("/assignments/<aid>/strikes", methods=["GET"])
def assignment_strikes(aid):
    auth_ctx()
    get_assignment(aid)
    status = core.request.args.get("status")
    items = [s for s in DB.strikes.values() if s["assignment_id"] == aid]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(sort_by_created(items))
    return envelope([ser_strike(s) for s in page], pagination=meta)


# --------------------------------------------------------------------------
# Encounter
# --------------------------------------------------------------------------
@bp.route("/encounters/<eid>/verify", methods=["POST"])
def verify_encounter(eid):
    auth = auth_ctx()
    body = get_body(allowed_fields={"corrected_start", "corrected_end"})
    require_role(auth[1], "OrgRequester")
    corrected_start = opt_dt(body, "corrected_start")
    corrected_end = opt_dt(body, "corrected_end")
    if (corrected_start is None) != (corrected_end is None):
        err(core.E_INVALID, 400,
            "corrected_start and corrected_end must be supplied together")
    if corrected_start is not None:
        if corrected_start >= corrected_end:
            err(core.E_INVALID, 400, "corrected_start must be before corrected_end")
        if corrected_end > now():
            err(core.E_INVALID, 400, "corrected_end must not lie in the future")
    encounter = get_encounter(eid)
    a = get_assignment(encounter["assignment_id"])
    req = get_request(a["request_id"])
    check_ownership(req["org_id"] == auth[0])
    org = get_org(req["org_id"])
    if org["status"] != "ACTIVE":
        err(core.E_ORG_NOT_ACTIVE, 409, "Organization is not ACTIVE")
    if encounter["verified"]:
        err(core.E_ENC_VERIFIED, 409, "Encounter is already verified")
    encounter["verified"] = True
    encounter["verified_by"] = "ORG"
    if corrected_start is not None:
        encounter["corrected_start"] = corrected_start
        encounter["corrected_end"] = corrected_end
        elapsed = (corrected_end - corrected_start).total_seconds()
        encounter["actual_minutes"] = math.ceil(elapsed / 60)
        encounter["billable_minutes"] = max(encounter["actual_minutes"],
                                            a["pinned_minimum_billable_minutes"])
    touch(encounter)
    if a["status"] == "COMPLETED" and req["status"] == "IN_PROGRESS":
        req["status"] = "COMPLETED"
        touch(req)
    return envelope(ser_encounter(encounter))
