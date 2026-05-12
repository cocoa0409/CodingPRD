"""RateOverride routes — submit/approve/reject/withdraw approval chain."""
from flask import Blueprint, request, g

from db import rate_overrides, room_types, stamp_create, stamp_update, lock
from errors import err
from middleware import require_auth
from response import success
from services.projections import project_rate_override
from services.validation import require_dict, required_str, required_int
from services.audit import emit
from services.parity import run_parity_check
from clock import parse_date, today_utc

bp = Blueprint("rate_overrides", __name__)

_VALID_SOURCES = {"SYSTEM_ENGINE", "MANUAL_OVERRIDE"}


@bp.route("/hotel/rate-overrides", methods=["POST"])
@require_auth(roles=["RevenueAnalyst", "RevenueManager"])
def create_override():
    body = require_dict(request.get_json(silent=True))
    room_type_id = required_str(body, "room_type_id")
    stay_date_raw = required_str(body, "stay_date")
    proposed = required_int(body, "proposed_rate_cents")
    if proposed < 1000:
        raise err("ERR_INVALID_INPUT", "proposed_rate_cents must be >= 1000")
    source = required_str(body, "recommendation_source")
    if source not in _VALID_SOURCES:
        raise err("ERR_INVALID_INPUT", "recommendation_source invalid")
    try:
        sd = parse_date(stay_date_raw)
    except ValueError as e:
        raise err("ERR_INVALID_INPUT", str(e))

    with lock():
        rt = room_types.get(room_type_id)
        if rt is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "RoomType not found")
        # Per priority 19: at most one DRAFT or PENDING_APPROVAL per (room_type_id, stay_date)
        for o in rate_overrides.values():
            if (o.get("room_type_id") == room_type_id
                    and o.get("stay_date") == sd.isoformat()
                    and o.get("status") in ("DRAFT", "PENDING_APPROVAL")):
                raise err("ERR_OVERRIDE_ALREADY_PENDING",
                          "An override for this (room_type, date) is already in DRAFT or PENDING_APPROVAL")

        row = {
            "room_type_id": room_type_id,
            "stay_date": sd.isoformat(),
            "proposed_rate_cents": proposed,
            "recommendation_source": source,
            "status": "DRAFT",
            "approved_by": None,
            "applied_rate_cents": None,
            "submitted_by": None,
            "created_by": g.user_id,
        }
        stamp_create(row, common_fields=True)
        rate_overrides[row["id"]] = row
    return success(project_rate_override(row), 201)


@bp.route("/hotel/rate-overrides/<oid>/submit", methods=["POST"])
@require_auth(roles=["RevenueAnalyst"])
def submit_override(oid):
    with lock():
        o = rate_overrides.get(oid)
        if o is None:
            raise err("ERR_NOT_FOUND", "RateOverride not found")
        if o.get("status") != "DRAFT":
            raise err("ERR_INVALID_STATE", "RateOverride is not DRAFT")
        rt = room_types.get(o["room_type_id"])
        if rt is None or rt.get("status") != "ACTIVE":
            raise err("ERR_INVALID_STATE", "RoomType is not ACTIVE")
        sd = parse_date(o["stay_date"])
        if sd < today_utc():
            raise err("ERR_INVALID_STATE", "stay_date is in the past")
        o["status"] = "PENDING_APPROVAL"
        o["submitted_by"] = g.user_id
        stamp_update(o)
    return success(project_rate_override(o))


@bp.route("/hotel/rate-overrides/<oid>/approve", methods=["POST"])
@require_auth(roles=["RevenueManager"])
def approve_override(oid):
    with lock():
        o = rate_overrides.get(oid)
        if o is None:
            raise err("ERR_NOT_FOUND", "RateOverride not found")
        if o.get("status") != "PENDING_APPROVAL":
            raise err("ERR_INVALID_STATE", "RateOverride is not PENDING_APPROVAL")
        # SoD: approver != submitter
        submitter = o.get("submitted_by") or o.get("created_by")
        if submitter is not None and submitter == g.user_id:
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "Approver must differ from submitter")

        rt = room_types.get(o["room_type_id"])
        before_rate = rt["base_rate_cents"] if rt else None

        # Cascade prior APPROVED override on same (room_type_id, stay_date) -> SUPERSEDED
        for prior in rate_overrides.values():
            if prior is o:
                continue
            if (prior.get("room_type_id") == o["room_type_id"]
                    and prior.get("stay_date") == o["stay_date"]
                    and prior.get("status") == "APPROVED"):
                # before_rate becomes that prior's applied_rate_cents
                before_rate = prior.get("applied_rate_cents", before_rate)
                prior["status"] = "SUPERSEDED"
                stamp_update(prior)

        o["status"] = "APPROVED"
        o["applied_rate_cents"] = o["proposed_rate_cents"]
        o["approved_by"] = g.user_id
        stamp_update(o)

        # Audit event
        emit(
            event_type="RATE_OVERRIDE_APPROVED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            subject_entity="RateOverride",
            subject_id=o["id"],
            payload={
                "before_rate_cents": before_rate,
                "after_rate_cents": o["applied_rate_cents"],
                "room_type_id": o["room_type_id"],
                "stay_date": o["stay_date"],
            },
        )

        # Trigger parity check
        run_parity_check(o["room_type_id"], o["stay_date"])
    return success(project_rate_override(o))


@bp.route("/hotel/rate-overrides/<oid>/reject", methods=["POST"])
@require_auth(roles=["RevenueManager"])
def reject_override(oid):
    with lock():
        o = rate_overrides.get(oid)
        if o is None:
            raise err("ERR_NOT_FOUND", "RateOverride not found")
        if o.get("status") != "PENDING_APPROVAL":
            raise err("ERR_INVALID_STATE", "RateOverride is not PENDING_APPROVAL")
        submitter = o.get("submitted_by") or o.get("created_by")
        if submitter is not None and submitter == g.user_id:
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "Approver must differ from submitter")
        o["status"] = "REJECTED"
        stamp_update(o)
        emit(
            event_type="RATE_OVERRIDE_REJECTED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            subject_entity="RateOverride",
            subject_id=o["id"],
            payload={
                "room_type_id": o["room_type_id"],
                "stay_date": o["stay_date"],
                "proposed_rate_cents": o["proposed_rate_cents"],
            },
        )
    return success(project_rate_override(o))


@bp.route("/hotel/rate-overrides/<oid>/withdraw", methods=["POST"])
@require_auth(roles=["RevenueAnalyst"])
def withdraw_override(oid):
    with lock():
        o = rate_overrides.get(oid)
        if o is None:
            raise err("ERR_NOT_FOUND", "RateOverride not found")
        if o.get("status") != "PENDING_APPROVAL":
            raise err("ERR_INVALID_STATE", "RateOverride is not PENDING_APPROVAL")
        # Submitter must equal acting user
        submitter = o.get("submitted_by")
        if submitter is not None and submitter != g.user_id:
            raise err("ERR_FORBIDDEN", "Only the submitting analyst may withdraw")
        o["status"] = "DRAFT"
        stamp_update(o)
    return success(project_rate_override(o))
