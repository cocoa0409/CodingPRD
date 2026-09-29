"""Logical clock, facade packages and shop-drawing submittals."""

from flask import Blueprint

import calc
import domain
from common import created, get_or_404, listing, single
from envelope import ok
from errors import ApiError
from store import apply, base_row, collection, db, fmt_dt, now_iso, parse_dt, sort_rows
from validate import (
    DECIDED_SYSTEM_TYPES,
    F,
    PACKAGE_STATES,
    POSTURES,
    SUBMITTAL_STATES,
    SUBMITTAL_TYPES,
    SYSTEM_TYPES,
    auth,
    body,
    q_enum,
    q_str,
    read_fields,
    require_user,
    user_id,
)

bp = Blueprint("core", __name__)


# ==========================================================================
# logical clock (PRD §2.5)
# ==========================================================================
@bp.post("/_clock/set_current_utc")
def set_clock():
    payload = body()
    raw = payload.get("to_iso8601")
    if raw is None or not isinstance(raw, str):
        raise ApiError("ERR_INVALID_REQUEST", "field 'to_iso8601' is required")
    parsed = parse_dt(raw)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "field 'to_iso8601' is not ISO 8601")
    db.clock = parsed
    return ok({"current_utc": now_iso()})


# ==========================================================================
# FacadePackage
# ==========================================================================
PACKAGE_SPECS = (
    F("name", "string"),
    F("floor_count", "int", rng=lambda v: v >= 1),
    F("total_area_sqm", "num", rng=lambda v: v > 0),
    F("contract_value_cents", "int", rng=lambda v: v > 0),
    F("unit_rate_cents_per_sqm", "int", rng=lambda v: v > 0),
    F("base_labor_rate_cents_per_hour", "int", rng=lambda v: v > 0),
    F("design_temp_delta_c", "num", rng=lambda v: v > 0),
    F("weather_tightness_deadline_date", "date"),
    F("system_type", "enum", required=False, enum=SYSTEM_TYPES),
)


@bp.post("/facade-packages")
def create_package():
    auth("CWProjectManager")
    values = read_fields(body(), PACKAGE_SPECS)
    row = base_row()
    row.update(
        {
            "name": values["name"],
            "floor_count": values["floor_count"],
            "total_area_sqm": values["total_area_sqm"],
            "contract_value_cents": values["contract_value_cents"],
            "unit_rate_cents_per_sqm": values["unit_rate_cents_per_sqm"],
            "base_labor_rate_cents_per_hour": values["base_labor_rate_cents_per_hour"],
            "design_temp_delta_c": values["design_temp_delta_c"],
            "weather_tightness_deadline_date": values["weather_tightness_deadline_date"],
            "system_type": "UNDECIDED",
            "state": "DESIGN_ASSIST",
            "engineering_posture": "OPEN",
            "blocking_submittal_count": 0,
            "open_critical_defect_count": 0,
            "planned_shop_hours": 0,
            "planned_field_crew_size": 0,
            "certified_area_sqm": 0,
            "earned_value_certified_cents": 0,
            "retention_held_cents": 0,
            "mockup_qualified": False,
            "weather_tight_zone_count": 0,
            "closeout_note": None,
        }
    )
    db.packages[row["id"]] = row
    return created(row, domain.ser_package)


@bp.get("/facade-packages")
def list_packages():
    auth()
    state = q_enum("state", PACKAGE_STATES)
    posture = q_enum("engineering_posture", POSTURES)
    system_type = q_enum("system_type", SYSTEM_TYPES)
    rows = collection(
        db.packages, state=state, engineering_posture=posture, system_type=system_type
    )
    return listing(rows, domain.ser_package)


@bp.get("/facade-packages/<pkg_id>")
def read_package(pkg_id):
    auth()
    row = get_or_404(db.packages, pkg_id, "ERR_PACKAGE_NOT_FOUND")
    return single(row, domain.ser_package)


@bp.post("/facade-packages/<pkg_id>/system-decision")
def system_decision(pkg_id):
    auth("CWProjectManager")
    values = read_fields(
        body(), (F("system_type", "enum", enum=DECIDED_SYSTEM_TYPES),)
    )
    package = get_or_404(db.packages, pkg_id, "ERR_PACKAGE_NOT_FOUND")
    if package["state"] != "DESIGN_ASSIST" or package["system_type"] != "UNDECIDED":
        raise ApiError("ERR_INVALID_STATE")

    system_type = values["system_type"]
    hours, crew = calc.labor_split(system_type, package["total_area_sqm"])
    package["system_type"] = system_type
    for zone in sort_rows(
        [z for z in db.zones.values() if z["package_id"] == package["id"]]
    ):
        apply(zone, domain.zone_limit_fields(zone, package))
    domain.sync_package(
        package,
        {
            "state": "SYSTEM_SELECTED",
            "system_type": system_type,
            "planned_shop_hours": hours,
            "planned_field_crew_size": crew,
        },
    )
    return single(package, domain.ser_package)


@bp.post("/facade-packages/<pkg_id>/close-out")
def close_out(pkg_id):
    auth("CWProjectManager")
    payload = body()
    values = read_fields(payload, (F("closeout_note", "string", required=False),))
    package = get_or_404(db.packages, pkg_id, "ERR_PACKAGE_NOT_FOUND")
    if package["state"] == "CLOSED_OUT":
        raise ApiError("ERR_TERMINAL_STATE")
    if package["state"] != "WEATHER_TIGHT_ACHIEVED":
        raise ApiError("ERR_INVALID_STATE")

    if domain.open_critical_defects(package["id"]):
        raise ApiError("ERR_OPEN_CRITICAL_DEFECT")

    zones = [z for z in db.zones.values() if z["package_id"] == package["id"]]
    if not zones:
        raise ApiError("ERR_ZONES_NOT_WEATHER_TIGHT")
    for zone in zones:
        if zone["weather_status"] != "WEATHER_TIGHT" or zone["install_status"] != "PANELS_HUNG":
            raise ApiError("ERR_ZONES_NOT_WEATHER_TIGHT")

    for item in db.defects.values():
        if item["package_id"] == package["id"] and item["status"] in (
            "OPEN",
            "REMEDIATION_SUBMITTED",
        ):
            raise ApiError("ERR_PUNCH_LIST_OPEN")

    open_notes = 0
    for sub in db.submittals.values():
        if sub["package_id"] != package["id"]:
            continue
        if sub["state"] in (
            "SUBMITTED",
            "UNDER_REVIEW",
            "REVISION_REQUIRED",
            "ESCALATED",
        ):
            raise ApiError("ERR_PUNCH_LIST_OPEN")
        open_notes += int(sub["open_notes_count"] or 0)
    if open_notes != 0:
        raise ApiError("ERR_PUNCH_LIST_OPEN")

    apply(
        package,
        {"state": "CLOSED_OUT", "closeout_note": values["closeout_note"]},
    )
    return single(package, domain.ser_package)


@bp.get("/facade-packages/<pkg_id>/earned-value")
def earned_value(pkg_id):
    auth()
    package = get_or_404(db.packages, pkg_id, "ERR_PACKAGE_NOT_FOUND")
    view = domain.earned_value_view(package)
    return ok(
        {
            "certified_area_sqm": float(view["certified_area_sqm"]),
            "certified_subtotal_cents": view["certified_subtotal_cents"],
            "retention_held_cents": view["retention_held_cents"],
            "earned_value_certified_cents": view["earned_value_certified_cents"],
            "weather_tight_zone_count": view["weather_tight_zone_count"],
            "contract_value_cents": package["contract_value_cents"],
        }
    )


@bp.get("/facade-packages/<pkg_id>/submittals")
def package_submittals(pkg_id):
    auth()
    package = get_or_404(db.packages, pkg_id, "ERR_PACKAGE_NOT_FOUND")
    state = q_enum("state", SUBMITTAL_STATES)
    rows = collection(db.submittals, package_id=package["id"], state=state)
    return listing(rows, domain.ser_submittal, paginated=False)


@bp.get("/facade-packages/<pkg_id>/zones")
def package_zones(pkg_id):
    auth()
    package = get_or_404(db.packages, pkg_id, "ERR_PACKAGE_NOT_FOUND")
    from validate import WEATHER_STATUSES

    weather_status = q_enum("weather_status", WEATHER_STATUSES)
    rows = collection(db.zones, package_id=package["id"], weather_status=weather_status)
    return listing(rows, domain.ser_zone, paginated=False)


# ==========================================================================
# ShopDrawingSubmittal
# ==========================================================================
SUBMITTAL_SPECS = (
    F("package_id", "string"),
    F("submittal_type", "enum", enum=SUBMITTAL_TYPES),
    F("title", "string"),
    F("drawing_set_ref", "string"),
    F("delegated_design_scope", "bool", required=False, default=False),
)


@bp.post("/shop-drawing-submittals")
def create_submittal():
    auth("CWDetailer")
    values = read_fields(body(), SUBMITTAL_SPECS)
    package = get_or_404(db.packages, values["package_id"], "ERR_PACKAGE_NOT_FOUND")
    row = base_row()
    row.update(
        {
            "package_id": package["id"],
            "submittal_type": values["submittal_type"],
            "title": values["title"],
            "drawing_set_ref": values["drawing_set_ref"],
            "delegated_design_scope": bool(values["delegated_design_scope"]),
            "state": "SUBMITTED",
            "revision_cycle": 1,
            "sealed_by_user_id": None,
            "seal_license_no": None,
            "sealed_at": None,
            "reviewed_by_user_id": None,
            "review_decision": None,
            "open_notes_count": 0,
            "escalation_ref": None,
            "dispute_resolution_ref": None,
            "reopen_reason": None,
        }
    )
    db.submittals[row["id"]] = row
    domain.sync_package(package)
    return created(row, domain.ser_submittal)


@bp.get("/shop-drawing-submittals")
def list_submittals():
    auth()
    rows = collection(
        db.submittals,
        package_id=q_str("package_id"),
        state=q_enum("state", SUBMITTAL_STATES),
        submittal_type=q_enum("submittal_type", SUBMITTAL_TYPES),
    )
    return listing(rows, domain.ser_submittal)


@bp.get("/shop-drawing-submittals/<sub_id>")
def read_submittal(sub_id):
    auth()
    row = get_or_404(db.submittals, sub_id, "ERR_SUBMITTAL_NOT_FOUND")
    return single(row, domain.ser_submittal)


@bp.post("/shop-drawing-submittals/<sub_id>/seal")
def seal_submittal(sub_id):
    auth("DelegatedEngineer")
    acting = require_user()
    payload = body()
    license_no = payload.get("seal_license_no")
    if license_no is not None and not isinstance(license_no, str):
        raise ApiError("ERR_INVALID_REQUEST", "field 'seal_license_no' has the wrong type")
    sub = get_or_404(db.submittals, sub_id, "ERR_SUBMITTAL_NOT_FOUND")
    if sub["state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    if license_no is None or not license_no.strip():
        raise ApiError("ERR_SEAL_INVALID")
    if sub["sealed_by_user_id"] is not None:
        raise ApiError("ERR_SEAL_INVALID")
    apply(
        sub,
        {
            "sealed_by_user_id": acting,
            "seal_license_no": license_no,
            "sealed_at": now_iso(),
        },
    )
    return single(sub, domain.ser_submittal)


@bp.post("/shop-drawing-submittals/<sub_id>/start-review")
def start_review(sub_id):
    auth("ArchitectOfRecord")
    acting = require_user()
    sub = get_or_404(db.submittals, sub_id, "ERR_SUBMITTAL_NOT_FOUND")
    if sub["state"] in ("APPROVED", "VOIDED"):
        raise ApiError("ERR_TERMINAL_STATE")
    if sub["state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    needs_seal = (
        sub["submittal_type"] == "STRUCTURAL_CALCULATION"
        or bool(sub["delegated_design_scope"])
    )
    if needs_seal and sub["sealed_by_user_id"] is None:
        raise ApiError("ERR_SEAL_REQUIRED")
    if sub["sealed_by_user_id"] is not None and acting == sub["sealed_by_user_id"]:
        raise ApiError("ERR_SEALER_CANNOT_REVIEW")
    apply(sub, {"state": "UNDER_REVIEW"})
    return single(sub, domain.ser_submittal)


@bp.post("/shop-drawing-submittals/<sub_id>/review")
def review_submittal(sub_id):
    auth("ArchitectOfRecord")
    acting = require_user()
    payload = body()
    values = read_fields(
        payload,
        (
            F(
                "decision",
                "enum",
                enum=("APPROVED", "APPROVED_AS_NOTED", "REVISION_REQUIRED"),
            ),
            F("escalation_ref", "string", required=False),
        ),
    )
    decision = values["decision"]
    notes_count = None
    if decision == "APPROVED_AS_NOTED":
        raw = payload.get("notes_count")
        if raw is None or isinstance(raw, bool) or not isinstance(raw, int):
            raise ApiError("ERR_INVALID_REQUEST", "field 'notes_count' is required")
        if raw < 1:
            raise ApiError("ERR_VALUE_OUT_OF_RANGE", "notes_count must be at least 1")
        notes_count = raw

    sub = get_or_404(db.submittals, sub_id, "ERR_SUBMITTAL_NOT_FOUND")
    if sub["state"] in ("APPROVED", "VOIDED"):
        raise ApiError("ERR_TERMINAL_STATE")
    if sub["state"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE")
    if sub["sealed_by_user_id"] is not None and acting == sub["sealed_by_user_id"]:
        raise ApiError("ERR_SEALER_CANNOT_REVIEW")

    updates = {"reviewed_by_user_id": acting}
    revision_branch = False
    if decision == "APPROVED":
        updates.update(
            {"state": "APPROVED", "review_decision": "APPROVED", "open_notes_count": 0}
        )
    elif decision == "APPROVED_AS_NOTED":
        updates.update(
            {
                "state": "APPROVED_AS_NOTED",
                "review_decision": "APPROVED_AS_NOTED",
                "open_notes_count": notes_count,
            }
        )
    else:
        revision_branch = True
        updates["review_decision"] = "REVISION_REQUIRED"
        if int(sub["revision_cycle"]) <= 2:
            updates["state"] = "REVISION_REQUIRED"
        else:
            updates["state"] = "ESCALATED"
            if values["escalation_ref"] is not None:
                updates["escalation_ref"] = values["escalation_ref"]
    apply(sub, updates)

    if revision_branch:
        domain.revoke_releases("SUBMITTAL_REVISION", submittal_id=sub["id"])
    package = db.packages.get(sub["package_id"])
    if package is not None:
        domain.sync_package(package)
    return single(sub, domain.ser_submittal)


@bp.post("/shop-drawing-submittals/<sub_id>/resubmit")
def resubmit(sub_id):
    auth("CWDetailer")
    values = read_fields(
        body(),
        (
            F("drawing_set_ref", "string"),
            F("dispute_resolution_ref", "string", required=False),
        ),
    )
    sub = get_or_404(db.submittals, sub_id, "ERR_SUBMITTAL_NOT_FOUND")
    if sub["state"] in ("APPROVED", "VOIDED"):
        raise ApiError("ERR_TERMINAL_STATE")
    if sub["state"] not in ("REVISION_REQUIRED", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE")
    dispute = values["dispute_resolution_ref"]
    if sub["state"] == "ESCALATED" and (dispute is None or not dispute.strip()):
        raise ApiError("ERR_DISPUTE_REF_REQUIRED")

    updates = {
        "state": "SUBMITTED",
        "revision_cycle": int(sub["revision_cycle"]) + 1,
        "drawing_set_ref": values["drawing_set_ref"],
        "sealed_by_user_id": None,
        "seal_license_no": None,
        "sealed_at": None,
    }
    if dispute is not None:
        updates["dispute_resolution_ref"] = dispute
    apply(sub, updates)
    package = db.packages.get(sub["package_id"])
    if package is not None:
        domain.sync_package(package)
    return single(sub, domain.ser_submittal)


@bp.post("/shop-drawing-submittals/<sub_id>/reopen-review")
def reopen_review(sub_id):
    auth("ArchitectOfRecord")
    acting = user_id()
    values = read_fields(body(), (F("reopen_reason", "string"),))
    sub = get_or_404(db.submittals, sub_id, "ERR_SUBMITTAL_NOT_FOUND")
    if sub["state"] in ("APPROVED", "VOIDED"):
        raise ApiError("ERR_TERMINAL_STATE")
    if sub["state"] != "APPROVED_AS_NOTED":
        raise ApiError("ERR_INVALID_STATE")
    if int(sub["open_notes_count"] or 0) < 1:
        raise ApiError("ERR_INVALID_STATE")
    if (
        sub["sealed_by_user_id"] is not None
        and acting is not None
        and acting == sub["sealed_by_user_id"]
    ):
        raise ApiError("ERR_SEALER_CANNOT_REVIEW")
    apply(sub, {"state": "UNDER_REVIEW", "reopen_reason": values["reopen_reason"]})
    package = db.packages.get(sub["package_id"])
    if package is not None:
        domain.sync_package(package)
    return single(sub, domain.ser_submittal)


@bp.post("/shop-drawing-submittals/<sub_id>/close-notes")
def close_notes(sub_id):
    auth("ArchitectOfRecord")
    values = read_fields(body(), (F("notes_closed", "int", rng=lambda v: v >= 0),))
    sub = get_or_404(db.submittals, sub_id, "ERR_SUBMITTAL_NOT_FOUND")
    if sub["state"] != "APPROVED_AS_NOTED":
        raise ApiError("ERR_INVALID_STATE")
    remaining = int(sub["open_notes_count"] or 0) - int(values["notes_closed"])
    apply(sub, {"open_notes_count": max(0, remaining)})
    return single(sub, domain.ser_submittal)
