"""Satisfaction surveys: manual dispatch, respond, expire sweep."""

from flask import g

from errors import (
    AppError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_RESOURCE_NOT_FOUND,
    ERR_SURVEY_CHANNEL_FORBIDDEN, ERR_SURVEY_EXPIRED, ERR_SURVEY_NOT_PENDING,
    ERROR_STATUS,
)
import db
import clock
import validators as V
from business_hours import business_seconds_between
from services import audit as audit_svc
from services import work_orders as wo_svc

SURVEY_CHANNELS = {"CALL", "SMS", "IM"}
SURVEY_EXPIRY_BUSINESS_HOURS = 48


def list_surveys(wo_id: str) -> list[dict]:
    wo_svc.get_work_order(wo_id)
    rows = [s for s in db.all_rows("satisfaction_surveys") if s["work_order_id"] == wo_id]
    rows.sort(key=lambda s: s["created_at"])
    return rows


def manual_dispatch(wo_id: str, body: dict) -> dict:
    wo = wo_svc.get_work_order(wo_id)
    if wo["status"] not in ("RESOLVED", "FOLLOWED_UP"):
        raise AppError(ERR_INVALID_STATE, "Manual dispatch requires RESOLVED or FOLLOWED_UP",
                       ERROR_STATUS[ERR_INVALID_STATE])
    channel = V.is_enum(body, "channel", SURVEY_CHANNELS)
    if wo.get("anonymous") and channel in ("CALL", "SMS"):
        raise AppError(ERR_SURVEY_CHANNEL_FORBIDDEN,
                       "CALL/SMS forbidden for anonymous work orders",
                       ERROR_STATUS[ERR_SURVEY_CHANNEL_FORBIDDEN])

    rec = db.insert("satisfaction_surveys", {
        "work_order_id": wo_id,
        "channel": channel,
        "status": "DISPATCHED",
        "score": None,
        "comment": None,
        "dispatched_at": clock.now_iso(),
        "responded_at": None,
    })
    audit_svc.write_audit("SURVEY_DISPATCH", wo_id, {"survey_id": rec["id"], "channel": channel})
    return rec


def get_survey(survey_id: str) -> dict:
    s = db.find_by_id("satisfaction_surveys", survey_id)
    if not s:
        raise AppError(ERR_RESOURCE_NOT_FOUND, "Survey not found",
                       ERROR_STATUS[ERR_RESOURCE_NOT_FOUND])
    return s


def respond(survey_id: str, body: dict) -> dict:
    s = get_survey(survey_id)
    if s["status"] != "DISPATCHED":
        raise AppError(ERR_SURVEY_NOT_PENDING, "Survey is not pending",
                       ERROR_STATUS[ERR_SURVEY_NOT_PENDING])

    # priority 20: SURVEY_EXPIRY (48 business hours)
    dispatched_dt = clock.parse_iso(s["dispatched_at"])
    now_dt = clock.now()
    bh = business_seconds_between(dispatched_dt, now_dt) / 3600.0
    if bh > SURVEY_EXPIRY_BUSINESS_HOURS:
        raise AppError(ERR_SURVEY_EXPIRED, "Survey response past 48 business hours",
                       ERROR_STATUS[ERR_SURVEY_EXPIRED])

    score = V.is_int(body, "score", min_v=1, max_v=5)
    comment = body.get("comment")
    if comment is not None:
        V.is_str(body, "comment", min_len=0, max_len=2000, allow_empty=True)

    now_iso = clock.now_iso()
    db.update_fields(s, {
        "status": "RESPONDED",
        "score": int(score),
        "comment": comment,
        "responded_at": now_iso,
    })

    # Parent WO → FOLLOWED_UP (only if currently RESOLVED).
    wo = db.find_by_id("work_orders", s["work_order_id"])
    if wo and wo["status"] == "RESOLVED":
        db.update_fields(wo, {"status": "FOLLOWED_UP"})

    audit_svc.write_audit("SURVEY_RESPOND", s["work_order_id"], {
        "survey_id": s["id"], "score": int(score),
    })
    return s
