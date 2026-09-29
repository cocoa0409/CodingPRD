"""Production lifecycle, clearance charts, the rights sweep and the logical clock."""
from datetime import datetime, timezone

from flask import Blueprint, g

import core
from calc import RENEWAL_WINDOW_DAYS
from core import (ROLE_ARCHIVE_RESEARCHER, ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL,
                  ROLE_PRODUCTION_ADMIN, ROLE_RIGHTS_HOLDER_REP, body, created, db, days_between,
                  fail, guard, invalid, is_int, iso_date, new_row, ok, ok_list, opt_date, opt_str,
                  pagination, parse_date, public, req_date, req_enum, req_int, req_str, touch)
from domain import (LIVE_COVERAGE, analyses_of_asset, assets_of_production, charts_of_production,
                    coverage_of_asset, eo_apps_of_production, get_production, letters_of_analysis,
                    licenses_of_production, packages_of_production, recompute_production,
                    rollup_asset)

bp = Blueprint("productions", __name__)

PRODUCTION_STATUSES = ("DEVELOPMENT", "CLEARANCE", "LOCKED", "DELIVERED", "ABANDONED")
ADMIN_TARGETS = ("CLEARANCE", "ABANDONED")
SUPERVISOR_TARGETS = ("LOCKED", "DELIVERED")


def new_production(data):
    row = new_row()
    row.update({
        "title": req_str(data, "title"),
        "delivery_deadline_date": iso_date(req_date(data, "delivery_deadline_date")),
        "festival_premiere_date": None,
        "eo_carrier_name": "UNASSIGNED",
        "status": "DEVELOPMENT",
        "posture": "OPEN",
        "asset_count": 0,
        "cleared_asset_count": 0,
        "open_asset_count": 0,
        "committed_fee_cents": 0,
        "sweep_epoch": 0,
    })
    premiere = opt_date(data, "festival_premiere_date")
    if premiere is not None:
        row["festival_premiere_date"] = iso_date(premiere)
    carrier = opt_str(data, "eo_carrier_name")
    if carrier is not None and carrier.strip():
        row["eo_carrier_name"] = carrier
    return row


@bp.post("/productions")
@guard(ROLE_PRODUCTION_ADMIN)
def create_production():
    data = body()
    row = new_production(data)
    db.productions[row["id"]] = row
    return created(public(row))


@bp.get("/productions/<pid>")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR, ROLE_ARCHIVE_RESEARCHER,
       ROLE_LEGAL_COUNSEL)
def read_production(pid):
    return ok(public(get_production(pid)))


@bp.post("/productions/<pid>/state")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR)
def production_state(pid):
    production = get_production(pid)
    data = body()
    to_status = req_enum(data, "to_status", PRODUCTION_STATUSES)
    reason = opt_str(data, "reason")

    # rung 3 — the two reserved bands of the production lifecycle
    if to_status in ADMIN_TARGETS and g.role != ROLE_PRODUCTION_ADMIN:
        fail("ERR_UNAUTHORIZED",
             "Only ProductionAdmin may drive a production to %s." % to_status)
    if to_status in SUPERVISOR_TARGETS and g.role != ROLE_CLEARANCE_SUPERVISOR:
        fail("ERR_UNAUTHORIZED",
             "Only ClearanceSupervisor may drive a production to %s." % to_status)

    current = production["status"]
    allowed = {
        ("DEVELOPMENT", "CLEARANCE"),
        ("CLEARANCE", "LOCKED"),
        ("LOCKED", "DELIVERED"),
        ("DEVELOPMENT", "ABANDONED"),
        ("CLEARANCE", "ABANDONED"),
    }
    if (current, to_status) not in allowed:
        fail("ERR_INVALID_STATE_TRANSITION",
             "A production in %s cannot move to %s." % (current, to_status))

    if to_status == "LOCKED":
        posture = recompute_production(production)
        if posture == "BLOCKED":
            fail("ERR_PRODUCTION_POSTURE_BLOCKED")
        if posture != "OPEN":
            fail("ERR_PRODUCTION_POSTURE_RESTRICTED")
        if not any(a["status"] == "BOUND" for a in eo_apps_of_production(pid)):
            fail("ERR_EO_NOT_BOUND")
    elif to_status == "DELIVERED":
        if not any(p["status"] == "DELIVERED" for p in packages_of_production(pid)):
            fail("ERR_NO_DELIVERED_PACKAGE")
    elif to_status == "ABANDONED" and current == "CLEARANCE":
        live = [l for l in licenses_of_production(pid) if l["status"] in LIVE_COVERAGE]
        if live:
            fail("ERR_LICENSES_STILL_LIVE")
        for lic in licenses_of_production(pid):
            if lic["status"] in ("DRAFT", "QUOTED", "COUNTERED"):
                lic["status"] = "TERMINATED"
                lic["termination_reason"] = reason or "AUTO: production abandoned"
                touch(lic)

    production["status"] = to_status
    recompute_production(production)
    touch(production)
    return ok(public(production))


# --- clearance charts -------------------------------------------------------
def build_pinned_rows(production):
    rows = []
    gap_count = 0
    letters = []
    for asset in assets_of_production(production["id"]):
        covered, license_ids = coverage_of_asset(asset)
        rows.append({
            "asset_id": asset["id"],
            "asset_version": asset["version"],
            "rights_basis": asset["rights_basis"],
            "licensing_status": asset["licensing_status"],
            "depiction_status": asset["depiction_status"],
            "covered_legs": sorted(covered),
            "license_ids": license_ids,
        })
        if asset["asset_type"] == "MUSIC" and not {"MASTER", "PUBLISHING"} <= covered:
            gap_count += 1
        if asset["rights_basis"] == "FAIR_USE":
            for analysis in analyses_of_asset(asset["id"]):
                if analysis["status"] != "ACCEPTED":
                    continue
                for letter in letters_of_analysis(analysis["id"]):
                    if letter["status"] == "ISSUED":
                        letters.append(letter)
    letter_ids = [l["id"] for l in core.by_seq(letters)]
    return rows, gap_count, letter_ids


@bp.post("/productions/<pid>/clearance-charts")
@guard(ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL)
def pin_chart(pid):
    production = get_production(pid)
    data = body()
    label = req_str(data, "chart_label")
    if "expected_production_version" not in data or not is_int(data["expected_production_version"]):
        invalid("Field 'expected_production_version' is required and must be an integer.")
    expected = data["expected_production_version"]

    if expected != production["version"]:
        fail("ERR_STALE_PRODUCTION_VERSION",
             "expected_production_version %s does not match the production's version %s."
             % (expected, production["version"]))

    if recompute_production(production) == "BLOCKED":
        fail("ERR_PRODUCTION_POSTURE_BLOCKED")

    for chart in charts_of_production(pid):
        if chart["status"] in ("PINNED", "STALE"):
            chart["status"] = "SUPERSEDED"
            touch(chart)

    rows, gap_count, letter_ids = build_pinned_rows(production)
    chart = new_row()
    chart.update({
        "production_id": pid,
        "chart_label": label,
        "pinned_rows": rows,
        "pinned_row_count": len(rows),
        "pinned_opinion_letter_ids": letter_ids,
        "music_leg_gap_count": gap_count,
        "status": "PINNED",
    })
    db.clearance_charts[chart["id"]] = chart

    recompute_production(production)
    touch(production)
    return created(public(chart))


@bp.get("/productions/<pid>/clearance-charts")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL)
def list_charts(pid):
    get_production(pid)
    limit, offset = pagination()
    from flask import request
    rows = list(reversed(charts_of_production(pid)))
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([public(r) for r in rows], limit, offset)


@bp.get("/clearance-charts/<cid>")
@guard(ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL, ROLE_PRODUCTION_ADMIN)
def read_chart(cid):
    from domain import get_chart
    return ok(public(get_chart(cid)))


# --- rights sweep -----------------------------------------------------------
@bp.post("/productions/<pid>/rights-sweep")
@guard(ROLE_CLEARANCE_SUPERVISOR, ROLE_PRODUCTION_ADMIN)
def rights_sweep(pid):
    production = get_production(pid)
    now_date = core.clock_date()

    production["sweep_epoch"] += 1
    epoch = production["sweep_epoch"]

    licences = licenses_of_production(pid)
    activated, expired, expiring = [], [], []
    touched_assets = []

    def mark(lic):
        if lic["asset_id"] not in touched_assets:
            touched_assets.append(lic["asset_id"])

    # step 1 — activation
    for lic in licences:
        if lic["status"] == "EXECUTED" and \
                parse_date(lic["term_start_date"], "term_start_date") <= now_date:
            lic["status"] = "ACTIVE"
            touch(lic)
            activated.append(lic["id"])
            mark(lic)

    # step 2 — expiry (half-open term: equality expires)
    for lic in licences:
        if lic["status"] in ("ACTIVE", "EXPIRING") and \
                now_date >= parse_date(lic["term_end_date"], "term_end_date"):
            lic["status"] = "EXPIRED"
            touch(lic)
            expired.append(lic["id"])
            mark(lic)

    # step 3 — expiry warning
    for lic in licences:
        if lic["status"] == "ACTIVE":
            delta = days_between(now_date, parse_date(lic["term_end_date"], "term_end_date"))
            if 0 <= delta <= RENEWAL_WINDOW_DAYS:
                lic["status"] = "EXPIRING"
                touch(lic)
                expiring.append(lic["id"])
                mark(lic)

    # step 4a — asset rollup for every asset touched above
    previous = {aid: db.assets[aid]["licensing_status"] for aid in touched_assets
                if aid in db.assets}
    lapsed = []
    for asset in assets_of_production(pid):
        if asset["id"] not in previous:
            continue
        rollup_asset(asset)
        if previous[asset["id"]] == "CLEARED" and asset["licensing_status"] != "CLEARED":
            lapsed.append(asset["id"])

    # step 4b — posture
    posture = recompute_production(production)

    # steps 4c / 4d — delivered packages and bound E&O cover
    suspended, remediated = [], []
    if posture == "BLOCKED":
        for pkg in packages_of_production(pid):
            if pkg["status"] == "DELIVERED":
                pkg["status"] = "SUSPENDED"
                pkg["suspension_reason"] = (
                    "AUTO: production posture BLOCKED at sweep epoch %d" % epoch)
                touch(pkg)
                suspended.append(pkg["id"])
        if suspended:
            for app in eo_apps_of_production(pid):
                if app["status"] == "BOUND":
                    app["status"] = "REMEDIATION_REQUIRED"
                    touch(app)
                    remediated.append(app["id"])

    # step 4e — a locked film that lost coverage goes back into clearance
    if production["status"] == "LOCKED" and posture != "OPEN":
        production["status"] = "CLEARANCE"

    touch(production)
    return ok({
        "sweep_epoch": epoch,
        "activated_license_ids": activated,
        "expired_license_ids": expired,
        "expiring_license_ids": expiring,
        "lapsed_asset_ids": lapsed,
        "suspended_delivery_package_ids": suspended,
        "remediated_eo_application_ids": remediated,
        "production_posture": production["posture"],
        "committed_fee_cents": production["committed_fee_cents"],
    })


# --- logical clock ----------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL,
       ROLE_ARCHIVE_RESEARCHER, ROLE_RIGHTS_HOLDER_REP)
def set_clock():
    data = body()
    raw = req_str(data, "to_iso8601").strip()
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        invalid("Field 'to_iso8601' must be an ISO-8601 instant.")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    db.clock = moment.astimezone(timezone.utc)
    return ok({"current_utc": db.clock.strftime("%Y-%m-%dT%H:%M:%SZ")})
