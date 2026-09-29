"""Registry endpoints, the recertification report and the logical clock."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from constants import (
    DEFAULT_CONCURRENT_LEG_CAPACITY,
    DEFAULT_REFERRAL_TRIGGER_POLICY,
    DEFAULT_TURNAROUND_BUFFER_MINUTES,
    DEFAULT_WINDOW_DAYS,
    DEFAULT_WINDOW_MINUTES,
    RECERT_CONVERSION_PASS,
    RECERT_OPD_PASS,
    RECERT_TIMELY_PASS,
    RECERT_TIMELY_PROBATION,
    REFERRAL_TRIGGER_POLICIES,
    REPORT_BASES,
    TEAM_SPECIALTIES,
    TRANSPORT_MODES,
)
from db import base_record, clock_now, db, lock, set_clock
from errors import ApiError
from middleware import authenticate, enforce_hospital_scope
from response import ok
from services.calculations import round2
from validation import Body, query_enum, query_int

bp = Blueprint("admin", __name__)


# ---------------------------------------------------------------- hospitals
@bp.post("/opo/hospital-partners")
def create_hospital_partner():
    authenticate("OpoAdmin")
    with lock:
        body = Body()
        name = body.string("name", required=True, min_len=1)
        code = body.string("hospital_code", required=True, min_len=2, max_len=12)
        policy = body.enum(
            "referral_trigger_policy",
            REFERRAL_TRIGGER_POLICIES,
            default=DEFAULT_REFERRAL_TRIGGER_POLICY,
        )
        window = body.integer(
            "timely_referral_window_minutes",
            default=DEFAULT_WINDOW_MINUTES,
            minimum=1,
            maximum=1440,
        )
        for existing in db.hospital_partners.values():
            if existing["hospital_code"] == code:
                raise ApiError("ERR_DUPLICATE_KEY", "hospital_code is already registered.")
        record = base_record()
        record.update(
            {
                "name": name,
                "hospital_code": code,
                "referral_trigger_policy": policy,
                "timely_referral_window_minutes": window,
                "referral_count": 0,
                "timely_referral_count": 0,
                "untimely_referral_count": 0,
                "timely_referral_rate": None,
                "partner_posture": "GOOD_STANDING",
                "converted_donor_count": 0,
            }
        )
        db.hospital_partners[record["id"]] = record
        return ok(record, 201)


@bp.get("/opo/hospital-partners/<hospital_id>")
def read_hospital_partner(hospital_id):
    user_id, role = authenticate(
        "OpoAdmin", "ReferralCoordinator", "MedicalDirector", "HospitalReferralClerk"
    )
    with lock:
        enforce_hospital_scope(user_id, role, hospital_id)
        record = db.hospital_partners.get(hospital_id)
        if record is None:
            raise ApiError("ERR_HOSPITAL_NOT_FOUND")
        return ok(record)


@bp.get("/opo/hospital-partners/<hospital_id>/performance")
def hospital_performance(hospital_id):
    authenticate("OpoAdmin", "MedicalDirector")
    with lock:
        hospital = db.hospital_partners.get(hospital_id)
        if hospital is None:
            raise ApiError("ERR_HOSPITAL_NOT_FOUND")
        window_days = query_int("window_days", DEFAULT_WINDOW_DAYS, minimum=1)
        basis = query_enum("basis", REPORT_BASES, "CLINICAL_TRIGGER")

        window_end = clock_now()
        window_start = window_end - timedelta(days=window_days)
        scope = [
            r
            for r in db.death_referrals.values()
            if r["hospital_partner_id"] == hospital_id
            and window_start <= r["referred_at"] < window_end
        ]

        limit = hospital["timely_referral_window_minutes"]
        if basis == "DEATH_NOTE":
            considered = [
                r for r in scope if r["ventilated"] and r["audit_lag_minutes"] is not None
            ]
            eligible_count = len(considered)
            timely_count = sum(1 for r in considered if r["audit_lag_minutes"] <= limit)
        else:
            considered = [r for r in scope if r["ventilated"]]
            eligible_count = len(considered)
            timely_count = sum(1 for r in considered if r["timeliness_flag"] == "TIMELY")

        cleared_count = sum(
            1 for r in scope if r["status"] in ("AUTH_PENDING", "CONVERTED", "NOT_CONVERTED")
        )
        converted_count = sum(1 for r in scope if r["status"] == "CONVERTED")

        scope_ids = {r["id"] for r in scope}
        case_ids = {c["id"] for c in db.donor_cases.values() if c["referral_id"] in scope_ids}
        transplanted = sum(
            1
            for o in db.organs.values()
            if o["status"] == "TRANSPLANTED" and o["donor_case_id"] in case_ids
        )

        timely_rate = None
        if eligible_count:
            timely_rate = round2(Decimal(100) * Decimal(timely_count) / Decimal(eligible_count))
        conversion_rate = None
        if cleared_count:
            conversion_rate = round2(
                Decimal(100) * Decimal(converted_count) / Decimal(cleared_count)
            )
        organs_per_donor = None
        if converted_count:
            organs_per_donor = round2(Decimal(transplanted) / Decimal(converted_count))

        if eligible_count == 0:
            tier = "INSUFFICIENT_DATA"
        else:
            conv = conversion_rate if conversion_rate is not None else Decimal("0")
            opd = organs_per_donor if organs_per_donor is not None else Decimal("0")
            if (
                timely_rate is not None
                and timely_rate >= Decimal(RECERT_TIMELY_PASS)
                and conv >= Decimal(RECERT_CONVERSION_PASS)
                and opd >= Decimal(RECERT_OPD_PASS)
            ):
                tier = "PASS"
            elif timely_rate is not None and timely_rate >= Decimal(RECERT_TIMELY_PROBATION):
                tier = "PROBATION"
            else:
                tier = "FAIL"

        return ok(
            {
                "hospital_partner_id": hospital_id,
                "window_days": window_days,
                "basis": basis,
                "window_start": window_start,
                "window_end": window_end,
                "eligible_referral_count": eligible_count,
                "timely_referral_count": timely_count,
                "timely_referral_rate": timely_rate,
                "cleared_referral_count": cleared_count,
                "converted_referral_count": converted_count,
                "conversion_rate": conversion_rate,
                "transplanted_organ_count": transplanted,
                "organs_per_donor": organs_per_donor,
                "recertification_tier": tier,
            }
        )


# ------------------------------------------------------------- recovery teams
@bp.post("/opo/recovery-teams")
def create_recovery_team():
    authenticate("OpoAdmin")
    with lock:
        body = Body()
        code = body.string("team_code", required=True, min_len=2, max_len=12)
        specialty = body.enum("specialty", TEAM_SPECIALTIES, required=True)
        buffer_minutes = body.integer(
            "turnaround_buffer_minutes",
            default=DEFAULT_TURNAROUND_BUFFER_MINUTES,
            minimum=0,
            maximum=480,
        )
        for existing in db.recovery_teams.values():
            if existing["team_code"] == code:
                raise ApiError("ERR_DUPLICATE_KEY", "team_code is already registered.")
        record = base_record()
        record.update(
            {
                "team_code": code,
                "specialty": specialty,
                "turnaround_buffer_minutes": buffer_minutes,
                "booked_or_minutes": 0,
                "scheduled_operation_count": 0,
            }
        )
        db.recovery_teams[record["id"]] = record
        return ok(record, 201)


@bp.get("/opo/recovery-teams/<team_id>")
def read_recovery_team(team_id):
    authenticate("OpoAdmin", "RecoveryLogistics", "MedicalDirector")
    with lock:
        record = db.recovery_teams.get(team_id)
        if record is None:
            raise ApiError("ERR_TEAM_NOT_FOUND")
        return ok(record)


# ----------------------------------------------------------- transport assets
@bp.post("/opo/transport-assets")
def create_transport_asset():
    authenticate("OpoAdmin")
    with lock:
        body = Body()
        code = body.string("asset_code", required=True, min_len=2, max_len=12)
        mode = body.enum("mode", TRANSPORT_MODES, required=True)
        capacity = body.integer(
            "concurrent_leg_capacity",
            default=DEFAULT_CONCURRENT_LEG_CAPACITY,
            minimum=1,
            maximum=5,
        )
        for existing in db.transport_assets.values():
            if existing["asset_code"] == code:
                raise ApiError("ERR_DUPLICATE_KEY", "asset_code is already registered.")
        record = base_record()
        record.update(
            {
                "asset_code": code,
                "mode": mode,
                "concurrent_leg_capacity": capacity,
                "active_leg_count": 0,
            }
        )
        db.transport_assets[record["id"]] = record
        return ok(record, 201)


@bp.get("/opo/transport-assets/<asset_id>")
def read_transport_asset(asset_id):
    authenticate("OpoAdmin", "RecoveryLogistics")
    with lock:
        record = db.transport_assets.get(asset_id)
        if record is None:
            raise ApiError("ERR_ASSET_NOT_FOUND")
        return ok(record)


# --------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate("OpoAdmin")
    with lock:
        body = Body()
        instant = body.instant("to_iso8601", required=True)
        current = set_clock(instant)
        return ok({"current_utc": current})
