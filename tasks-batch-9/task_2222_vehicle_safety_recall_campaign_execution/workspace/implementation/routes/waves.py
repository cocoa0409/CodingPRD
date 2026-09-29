"""Notification waves: planning, release quota, mailing and cancellation."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import helpers as h
import validators as v
from auth import ALL_ROLES, require_roles
from db import (clock_date, clock_now, fmt_instant, parse_date, sorted_records,
                store, touch)
from errors import ApiError
from response import collection, single

bp = Blueprint("waves", __name__)

RELEASABLE_CAMPAIGN_STATES = ("FILED", "INTERIM_NOTIFIED", "OWNER_NOTIFIED", "MONITORING")


@bp.post("/recall-campaigns/<campaign_id>/notification-waves")
@require_roles("RecallOperationsManager")
def plan_wave(campaign_id):
    campaign = h.get_campaign(campaign_id)
    payload = v.body()
    wave_type = v.req_enum(payload, "wave_type", v.WAVE_TYPES)
    region = v.req_enum(payload, "target_region_code", v.REGION_CODES)
    mail_raw, mail_date = v.req_date_str(payload, "scheduled_mail_date")

    h.assert_campaign_writable(campaign)

    for other in calc.campaign_waves(campaign["id"]):
        if other["status"] == "CANCELLED" or other["target_region_code"] != region:
            continue
        other_date = parse_date(other["scheduled_mail_date"])
        if abs((mail_date - other_date).days) < calc.MIN_WAVE_SEPARATION_DAYS:
            raise ApiError("ERR_WAVE_MAILING_TOO_CLOSE")

    wave = h.create_wave(campaign, wave_type, region, mail_raw, auto_created=False)
    return single(h.wave_out(wave), 201)


@bp.get("/recall-campaigns/<campaign_id>/notification-waves")
@require_roles(*ALL_ROLES)
def list_waves(campaign_id):
    campaign = h.get_campaign(campaign_id)
    wave_type = v.query_enum("wave_type", v.WAVE_TYPES)
    status = v.query_enum("status", v.WAVE_STATUSES)
    rows = calc.campaign_waves(campaign["id"])
    if wave_type is not None:
        rows = [r for r in rows if r["wave_type"] == wave_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return collection(sorted_records(rows), h.wave_out)


@bp.post("/notification-waves/<wave_id>/release")
@require_roles("RecallOperationsManager")
def release_wave(wave_id):
    wave = h.get_wave(wave_id)
    campaign = store.campaigns.get(wave["campaign_id"])

    h.assert_campaign_writable(campaign, RELEASABLE_CAMPAIGN_STATES)
    if wave["wave_type"] == "INTERIM" and campaign["campaign_status"] != "INTERIM_NOTIFIED":
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")
    if wave["status"] != "PLANNED":
        raise ApiError("ERR_WAVE_INVALID_STATE")

    if wave["wave_type"] == "INTERIM":
        if campaign["remedy_status"] == "REMEDY_UNDER_DEVELOPMENT":
            raise ApiError("ERR_REMEDY_NOT_AVAILABLE")
        if campaign["remedy_status"] != "INTERIM_ONLY":
            raise ApiError("ERR_REMEDY_ALREADY_AVAILABLE")
    else:
        h.assert_remedy_available(campaign)

    # step 1 - candidate set
    candidates = calc.wave_candidates(wave)
    eligible = len(candidates)
    if eligible == 0:
        raise ApiError("ERR_EMPTY_WAVE_POPULATION")

    # step 2 - parts capacity snapshot
    capacity = calc.wave_parts_capacity(wave)
    if capacity is None:
        capacity = eligible

    # step 3 - the coverage gate
    provisional = calc.q4(Decimal(capacity) / Decimal(eligible))
    required = calc.REQUIRED_MIN_RATIO_BY_SEVERITY[campaign["risk_severity"]]
    if provisional < required:
        raise ApiError("ERR_INSUFFICIENT_PARTS_COVERAGE")

    # step 4 - tier factor
    tier = calc.coverage_tier_factor(provisional)

    # step 5 - mailing size
    planned = int((Decimal(eligible) * tier).to_integral_value(rounding="ROUND_FLOOR"))
    if planned == 0:
        raise ApiError("ERR_EMPTY_WAVE_POPULATION")

    # step 6 - reported coverage
    reported = calc.q4(Decimal(capacity) / Decimal(planned))

    wave["eligible_vehicle_count"] = eligible
    wave["parts_capacity_qty"] = capacity
    wave["provisional_coverage_ratio"] = provisional
    wave["coverage_tier_factor"] = tier
    wave["planned_vehicle_count"] = planned
    wave["parts_coverage_ratio"] = reported
    wave["status"] = "RELEASE_APPROVED"
    touch(wave)
    return single(h.wave_out(wave))


@bp.post("/notification-waves/<wave_id>/mail")
@require_roles("RecallOperationsManager")
def mail_wave(wave_id):
    wave = h.get_wave(wave_id)
    campaign = store.campaigns.get(wave["campaign_id"])

    h.assert_campaign_writable(campaign)
    if wave["status"] != "RELEASE_APPROVED":
        raise ApiError("ERR_WAVE_INVALID_STATE")
    if clock_date() < parse_date(wave["scheduled_mail_date"]):
        raise ApiError("ERR_WAVE_MAIL_DATE_NOT_REACHED")

    candidates = calc.wave_mailing_order(calc.wave_candidates(wave))
    selected = candidates[:wave["planned_vehicle_count"]]
    stamp = fmt_instant(clock_now())
    for av in selected:
        av["notification_wave_id"] = wave["id"]
        av["notice_count"] = av["notice_count"] + 1
        av["last_notice_type"] = wave["wave_type"]
        av["last_notice_date"] = stamp
        av["requires_renotification"] = False
        touch(av)

    wave["mailed_vehicle_count"] = len(selected)
    wave["actual_mail_date"] = stamp
    wave["status"] = "MAILED"
    touch(wave)

    if wave["wave_type"] in ("REMEDY", "FOLLOW_UP") \
            and campaign["campaign_status"] in ("FILED", "INTERIM_NOTIFIED"):
        campaign["campaign_status"] = "OWNER_NOTIFIED"
    touch(campaign)
    return single(h.wave_out(wave))


@bp.post("/notification-waves/<wave_id>/cancel")
@require_roles("RecallOperationsManager")
def cancel_wave(wave_id):
    wave = h.get_wave(wave_id)
    campaign = store.campaigns.get(wave["campaign_id"])
    payload = v.body()
    cancel_reason = v.opt_str(payload, "cancel_reason")

    if wave["status"] not in ("PLANNED", "RELEASE_APPROVED"):
        raise ApiError("ERR_WAVE_INVALID_STATE")

    wave["status"] = "CANCELLED"
    wave["cancel_reason"] = cancel_reason
    touch(wave)
    touch(campaign)
    return single(h.wave_out(wave))
