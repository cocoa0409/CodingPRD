"""Operations endpoints: the nightly sweep, the logical clock, and computed reads."""
from datetime import timedelta

from flask import Blueprint

import calc
import cascades
from core import (ROLE_CLIENT_SPONSOR, ROLE_COMPLIANCE_AUDITOR, ROLE_OPERATOR_ADMIN,
                 ROLE_SITE_MANAGER, bad_request, body, credentials_of_staff, fmt_dt,
                 get_or_404, now, ok, parse_dt, query_required, req_str, require,
                 scope_contract, sessions_of_contract, set_now, today, to_date, upd, where)

bp = Blueprint("ops", __name__)

EXPIRING_WINDOW_DAYS = 30

TALLY_KEYS = ("credentials_expiring_soon", "credentials_expired", "staff_suspended",
              "assignments_vacated", "sessions_at_risk", "sessions_cancelled_no_cover",
              "waivers_expired", "badges_revoked", "assets_maintenance_due", "aed_not_ready")


def _staff_of(contract_id):
    return where("staff", contract_id=contract_id)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    require(ROLE_OPERATOR_ADMIN)
    data = body()
    raw = req_str(data, "current_utc")
    parsed = parse_dt(raw)
    if parsed is None:
        raise bad_request("current_utc must be an ISO-8601 instant")
    set_now(parsed)
    return ok({"current_utc": fmt_dt(parsed)})


# --------------------------------------------------------------------------
# Nightly readiness sweep
# --------------------------------------------------------------------------
@bp.post("/operations/daily-readiness-run")
def daily_readiness_run():
    require(ROLE_OPERATOR_ADMIN)
    data = body()
    contract_id = req_str(data, "contract_id")
    contract = get_or_404("contract", contract_id)
    tally = {}
    for key in TALLY_KEYS:
        tally[key] = 0
    penalty_before = contract.get("pending_penalty_cents") or 0
    day = today()
    warn_edge = day + timedelta(days=EXPIRING_WINDOW_DAYS)

    # ---- step 1: credential expiry and the four-link staffing cascade
    staff_rows = _staff_of(contract_id)
    expired_holders = []
    for staff in staff_rows:
        for credential in credentials_of_staff(staff["id"]):
            expires = to_date(credential["expires_on"])
            if expires is None:
                continue
            status = credential["status"]
            if status in ("VERIFIED", "EXPIRING_SOON") and expires <= day:
                upd(credential, status="EXPIRED")
                tally["credentials_expired"] += 1
                required = staff.get("required_credential_types") or []
                if credential["credential_type"] in required:
                    expired_holders.append(staff)
            elif status == "VERIFIED" and expires <= warn_edge and expires > day:
                upd(credential, status="EXPIRING_SOON")
                tally["credentials_expiring_soon"] += 1
    seen = set()
    for staff in expired_holders:
        if staff["id"] in seen:
            continue
        seen.add(staff["id"])
        cascades.credential_suspension_cascade(staff, tally)

    # ---- step 2: readiness recomputation
    for staff in staff_rows:
        cascades.refresh_readiness(staff)

    # ---- step 3: waiver expiry
    members = where("member", contract_id=contract_id)
    for member in members:
        for waiver in where("waiver", member_id=member["id"]):
            if waiver["status"] != "SIGNED":
                continue
            expires = to_date(waiver["expires_on"])
            if expires is not None and expires < day:
                upd(waiver, status="EXPIRED")
                tally["waivers_expired"] += 1
                if member.get("current_waiver_id") == waiver["id"]:
                    upd(member, current_waiver_id=None)
                if cascades.revoke_badge(member):
                    tally["badges_revoked"] += 1

    # ---- step 4: badge revocation for members no longer eligible
    for member in members:
        if member["eligibility_status"] != "ELIGIBLE" and member["access_status"] == "ACTIVE":
            cascades.revoke_badge(member)
            tally["badges_revoked"] += 1

    # ---- step 5: equipment picture
    aed_total = 0
    aed_ready = 0
    for asset in where("asset", contract_id=contract_id):
        if asset["asset_type"] != "AED":
            if asset["status"] == "IN_SERVICE":
                last = to_date(asset.get("last_service_on"))
                due = last is None or (day - last).days >= (
                    asset.get("service_interval_days") or 90)
                if due:
                    upd(asset, status="MAINTENANCE_DUE")
                    tally["assets_maintenance_due"] += 1
            continue
        cascades.refresh_asset_readiness(asset)
        aed_total += 1
        if asset["readiness_status"] == "READY":
            aed_ready += 1
    tally["aed_not_ready"] = aed_total - aed_ready

    # ---- step 6: attainment recomputation
    for offering in where("offering", contract_id=contract_id):
        cascades.refresh_attainment(offering, provisional=True, final=True)

    # ---- step 7: final coverage sweep
    at_risk = [s for s in sessions_of_contract(contract_id)
               if s["status"] == "STAFFING_AT_RISK" and cascades.in_lock_window(s)]
    at_risk.sort(key=lambda r: (r["scheduled_start_utc"], r["created_at"], r["_seq"]))
    for session in at_risk:
        cascades.cancel_session(session, "NO_COVER")
        tally["sessions_cancelled_no_cover"] += 1

    penalty_after = contract.get("pending_penalty_cents") or 0
    payload = {"contract_id": contract_id, "run_at_utc": fmt_dt(now())}
    for key in TALLY_KEYS:
        payload[key] = tally[key]
    payload["penalty_accrued_cents"] = max(0, penalty_after - penalty_before)
    return ok(payload)


# --------------------------------------------------------------------------
# Computed reads
# --------------------------------------------------------------------------
@bp.get("/operations/readiness-summary")
def readiness_summary():
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, ROLE_COMPLIANCE_AUDITOR)
    contract_id = query_required("contract_id")
    scope_contract(contract_id)
    get_or_404("contract", contract_id)
    aed_ready = 0
    aed_not_ready = 0
    assets_out = 0
    for asset in where("asset", contract_id=contract_id):
        if asset["status"] == "OUT_OF_SERVICE":
            assets_out += 1
        if asset["asset_type"] != "AED":
            continue
        if asset["readiness_status"] == "READY":
            aed_ready += 1
        else:
            aed_not_ready += 1
    expiring = 0
    expired = 0
    suspended = 0
    for staff in _staff_of(contract_id):
        if staff["duty_status"] == "SUSPENDED_FROM_DUTY":
            suspended += 1
        for credential in credentials_of_staff(staff["id"]):
            if credential["status"] == "EXPIRING_SOON":
                expiring += 1
            elif credential["status"] == "EXPIRED":
                expired += 1
    at_risk = len([s for s in sessions_of_contract(contract_id)
                   if s["status"] == "STAFFING_AT_RISK"])
    restricted = len([r for r in where("room", contract_id=contract_id)
                      if r["room_state"] == "RESTRICTED"])
    return ok({
        "contract_id": contract_id,
        "aed_ready_count": aed_ready,
        "aed_not_ready_count": aed_not_ready,
        "credentials_expiring_soon": expiring,
        "credentials_expired": expired,
        "staff_suspended_count": suspended,
        "sessions_at_risk": at_risk,
        "rooms_restricted": restricted,
        "assets_out_of_service": assets_out,
    })


@bp.get("/client-contracts/<cid>/utilization-report")
def utilization_report(cid):
    require(ROLE_OPERATOR_ADMIN, ROLE_CLIENT_SPONSOR, ROLE_COMPLIANCE_AUDITOR)
    contract = get_or_404("contract", cid)
    scope_contract(contract["id"])
    period_month = query_required("period_month")
    if not calc.MONTH_PATTERN.match(period_month):
        raise bad_request("period_month must be YYYY-MM")
    return ok(calc.utilization_rollup(contract, period_month))


@bp.get("/program-offerings/<oid>/attainment")
def offering_attainment(oid):
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, ROLE_CLIENT_SPONSOR,
            ROLE_COMPLIANCE_AUDITOR)
    offering = get_or_404("offering", oid)
    scope_contract(offering["contract_id"])
    parts = calc.compute_attainment(offering)
    return ok({
        "offering_id": offering["id"],
        "participation_target": offering["participation_target"],
        "counted_done": parts["counted_done"],
        "forecast_open": parts["forecast_open"],
        "counted_final": parts["counted_final"],
        "provisional_attainment_pct": parts["provisional_attainment_pct"],
        "final_attainment_pct": parts["final_attainment_pct"],
        "coverage_gap_count": offering.get("coverage_gap_count") or 0,
    })
