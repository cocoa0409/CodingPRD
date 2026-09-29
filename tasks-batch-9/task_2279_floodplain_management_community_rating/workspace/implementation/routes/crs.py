"""Repetitive loss areas, higher-standards credit, and recertification cycles."""

from flask import Blueprint

from db import (base_fields, db, iso, iso_now, now, shift_years, sort_rows,
                to_dt, touch)
from errors import fail
from middleware import ALL_ROLES, require
from response import list_response, object_response
from services import calc, engine
from validation import (as_int, body, fk, lookup, opt_str, pagination,
                        paginate, query_filters, req_dt, req_enum, req_int,
                        req_str)

bp = Blueprint("crs", __name__)

_DECISIONS = ("VERIFY", "REJECT")
_LIVE_CYCLE_STATUSES = ("OPEN", "SUBMITTED", "UNDER_VERIFICATION", "CERTIFIED",
                        "RETROGRADED")


# ------------------------------------------------------- RepetitiveLossArea


@bp.post("/repetitive-loss-areas")
def create_area():
    require("FloodplainAdministrator")
    data = body()
    community_id = fk(data, "community_id", "community")
    area_code = req_str(data, "area_code")
    boundary = req_str(data, "boundary_description")
    lookup("community", community_id)

    if any(a["area_code"] == area_code for a in engine.areas_of(community_id)):
        fail("ERR_DUPLICATE_AREA_CODE")

    row = base_fields()
    row.update({
        "community_id": community_id,
        "area_code": area_code,
        "boundary_description": boundary,
        "status": "DRAFT",
        "analysis_status": "PENDING_ANALYSIS",
        "analyzed_at": None,
        "property_count": 0,
        "rl_property_count": 0,
        "outreach_status": "NOT_STARTED",
        "outreach_cycle_year": None,
        "outreach_crs_cycle_id": None,
        "target_property_count": 0,
        "delivered_count": 0,
        "coverage_pct": calc.r2(0),
    })
    db.loss_areas[row["id"]] = row
    return object_response(row, 201)


@bp.get("/repetitive-loss-areas/<area_id>")
def read_area(area_id):
    require(*ALL_ROLES)
    return object_response(lookup("loss_area", area_id))


@bp.get("/repetitive-loss-areas")
def list_areas():
    require(*ALL_ROLES)
    limit, offset = pagination()
    rows = query_filters(list(db.loss_areas.values()), {
        "community_id": ("community_id", None),
        "outreach_crs_cycle_id": ("outreach_crs_cycle_id", None),
        "status": ("status", None),
        "analysis_status": ("analysis_status", None),
        "outreach_status": ("outreach_status", None),
    })
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/repetitive-loss-areas/<area_id>/analyze")
def analyze_area(area_id):
    require("FloodplainAdministrator")
    area = lookup("loss_area", area_id)

    linked = [p for p in engine.props_of_community(area["community_id"])
              if p["mapped_area_code"] == area["area_code"]]
    for prop in sort_rows(linked):
        changed = prop["repetitive_loss_area_id"] != area["id"]
        prop["repetitive_loss_area_id"] = area["id"]
        recomputed, _status_changed = engine.recompute_property_rl(prop)
        if changed or recomputed:
            touch(prop)

    area["property_count"] = len(linked)
    area["rl_property_count"] = sum(1 for p in linked
                                    if p["repetitive_loss_status"] != "NONE")
    area["analysis_status"] = "ANALYZED"
    area["analyzed_at"] = iso_now()
    touch(area)
    return object_response(area)


@bp.post("/repetitive-loss-areas/<area_id>/designate")
def designate_area(area_id):
    require("FloodplainAdministrator")
    area = lookup("loss_area", area_id)
    if area["status"] != "DRAFT":
        fail("ERR_LOSS_AREA_NOT_DESIGNATED")
    if area["analysis_status"] != "ANALYZED":
        fail("ERR_LOSS_AREA_ANALYSIS_STALE")

    area["status"] = "DESIGNATED"
    touch(area)
    return object_response(area)


@bp.post("/repetitive-loss-areas/<area_id>/outreach")
def launch_outreach(area_id):
    require("FloodplainAdministrator")
    area = lookup("loss_area", area_id)
    data = body()
    cycle_id = fk(data, "crs_cycle_id", "cycle")
    target = req_int(data, "target_property_count", minimum=0)
    cycle = lookup("cycle", cycle_id)

    if cycle["community_id"] != area["community_id"]:
        fail("ERR_CYCLE_COMMUNITY_MISMATCH")
    if area["status"] != "DESIGNATED":
        fail("ERR_LOSS_AREA_NOT_DESIGNATED")
    if area["outreach_status"] == "IN_PROGRESS":
        fail("ERR_OUTREACH_ALREADY_IN_PROGRESS")
    if cycle["status"] != "OPEN":
        fail("ERR_CYCLE_NOT_OPEN")
    if area["analysis_status"] != "ANALYZED":
        fail("ERR_LOSS_AREA_ANALYSIS_STALE")
    if target < area["property_count"]:
        fail("ERR_OUTREACH_TARGET_BELOW_ANALYZED")

    area["outreach_status"] = "IN_PROGRESS"
    area["outreach_cycle_year"] = cycle["cycle_year"]
    area["outreach_crs_cycle_id"] = cycle["id"]
    area["target_property_count"] = target
    area["delivered_count"] = 0
    area["coverage_pct"] = calc.r2(0)
    touch(area)
    return object_response(area)


@bp.post("/repetitive-loss-areas/<area_id>/record-outreach-delivery")
def record_delivery(area_id):
    require("FloodplainAdministrator")
    area = lookup("loss_area", area_id)
    data = body()
    increment = req_int(data, "delivered_increment", minimum=0)

    if area["outreach_status"] != "IN_PROGRESS":
        fail("ERR_OUTREACH_NOT_IN_PROGRESS")
    total = area["delivered_count"] + increment
    if total > area["target_property_count"]:
        fail("ERR_DELIVERY_EXCEEDS_TARGET")

    area["delivered_count"] = total
    area["coverage_pct"] = calc.pct(total, area["target_property_count"])
    touch(area)
    return object_response(area)


@bp.post("/repetitive-loss-areas/<area_id>/complete-outreach")
def complete_outreach(area_id):
    require("FloodplainAdministrator")
    area = lookup("loss_area", area_id)
    if area["outreach_status"] != "IN_PROGRESS":
        fail("ERR_OUTREACH_NOT_IN_PROGRESS")

    area["outreach_status"] = ("COMPLETED"
                              if calc.dec(area["coverage_pct"]) >= calc.OUTREACH_PARTIAL_CREDIT_PCT
                              else "INSUFFICIENT")
    touch(area)
    return object_response(area)


# ----------------------------------------------------------- HigherStandard


@bp.post("/higher-standards")
def create_standard():
    require("FloodplainAdministrator")
    data = body()
    community_id = fk(data, "community_id", "community")
    activity_code = req_enum(data, "activity_code", calc.ACTIVITY_CODES)
    cycle_year = req_int(data, "documentation_cycle_year")
    claimed = req_int(data, "claimed_points", minimum=1)
    expected = req_int(data, "expected_community_version")
    community = lookup("community", community_id)

    if expected != community["version"]:
        fail("ERR_STALE_COMMUNITY_VERSION")

    same_triple = [h for h in engine.standards_of(community_id)
                   if h["activity_code"] == activity_code
                   and h["documentation_cycle_year"] == cycle_year]
    if any(h["documentation_status"] in ("SUBMITTED", "VERIFIED") for h in same_triple):
        fail("ERR_DUPLICATE_STANDARD_ACTIVITY")

    for standard in sort_rows(same_triple):
        if standard["documentation_status"] in ("DRAFT", "REJECTED"):
            standard["documentation_status"] = "EXPIRED"
            standard["verified_points"] = 0
            touch(standard)

    row = base_fields()
    row.update({
        "community_id": community_id,
        "activity_code": activity_code,
        "documentation_cycle_year": cycle_year,
        "claimed_points": claimed,
        "max_points_allowed": 0,
        "verified_points": 0,
        "documentation_status": "DRAFT",
        "submitted_at": None,
        "verified_at": None,
        "doc_expires_at": None,
        "rejection_reason": None,
    })
    row["max_points_allowed"] = engine.max_points_for(row, community)
    db.standards[row["id"]] = row
    touch(community)
    return object_response(row, 201)


@bp.get("/higher-standards/<standard_id>")
def read_standard(standard_id):
    require(*ALL_ROLES)
    return object_response(lookup("standard", standard_id))


@bp.get("/higher-standards")
def list_standards():
    require(*ALL_ROLES)
    limit, offset = pagination()
    rows = query_filters(list(db.standards.values()), {
        "community_id": ("community_id", None),
        "activity_code": ("activity_code", None),
        "documentation_status": ("documentation_status", None),
        "documentation_cycle_year": ("documentation_cycle_year", as_int),
    })
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/higher-standards/<standard_id>/submit")
def submit_standard(standard_id):
    require("FloodplainAdministrator")
    standard = lookup("standard", standard_id)
    if standard["documentation_status"] != "DRAFT":
        fail("ERR_STANDARD_NOT_DRAFT")

    standard["documentation_status"] = "SUBMITTED"
    standard["submitted_at"] = iso_now()
    touch(standard)

    community = db.communities.get(standard["community_id"])
    if community is not None and engine.recompute_claimed(community):
        touch(community)
    return object_response(standard)


@bp.post("/higher-standards/<standard_id>/verify")
def verify_standard(standard_id):
    require("StateNfipCoordinator")
    standard = lookup("standard", standard_id)
    data = body()
    decision = req_enum(data, "decision", _DECISIONS)
    reason = opt_str(data, "rejection_reason")

    if standard["documentation_status"] != "SUBMITTED":
        fail("ERR_STANDARD_NOT_SUBMITTED")

    community = db.communities.get(standard["community_id"])

    if decision == "REJECT":
        standard["documentation_status"] = "REJECTED"
        standard["rejection_reason"] = reason
        standard["verified_points"] = 0
        touch(standard)
        if community is not None and engine.recompute_claimed(community):
            touch(community)
        return object_response(standard)

    ceiling = engine.max_points_for(standard, community) if community else 0
    if ceiling < 1:
        fail("ERR_STANDARD_PREREQUISITE_NOT_MET")

    standard["max_points_allowed"] = ceiling
    standard["verified_points"] = min(standard["claimed_points"], ceiling)
    standard["documentation_status"] = "VERIFIED"
    standard["verified_at"] = iso_now()
    standard["doc_expires_at"] = iso(shift_years(now(), calc.DOC_CYCLE_YEARS))
    touch(standard)

    changed = engine.recompute_verified(community)
    if standard["activity_code"] == "A510_HIGHER_STD_ENFORCEMENT":
        changed = engine.sanction_fields(community) or changed
    if changed:
        touch(community)
    return object_response(standard)


# ------------------------------------------------------------------ CrsCycle


@bp.post("/crs-cycles")
def create_cycle():
    require("StateNfipCoordinator")
    data = body()
    community_id = fk(data, "community_id", "community")
    cycle_year = req_int(data, "cycle_year")
    start = req_dt(data, "cycle_start_date")
    end = req_dt(data, "cycle_end_date")
    due_at = req_dt(data, "due_at")
    if end <= start:
        fail("ERR_INVALID_REQUEST", "cycle_end_date must be after cycle_start_date.")
    lookup("community", community_id)

    siblings = engine.cycles_of(community_id)
    for cycle in sort_rows(siblings):
        if cycle["status"] not in _LIVE_CYCLE_STATUSES:
            continue
        if start <= to_dt(cycle["cycle_end_date"]) and to_dt(cycle["cycle_start_date"]) <= end:
            fail("ERR_CYCLE_WINDOW_OVERLAP")
    if any(c["cycle_year"] == cycle_year for c in siblings):
        fail("ERR_DUPLICATE_CYCLE_YEAR")

    row = base_fields()
    row.update({
        "community_id": community_id,
        "cycle_year": cycle_year,
        "cycle_start_date": iso(start),
        "cycle_end_date": iso(end),
        "due_at": iso(due_at),
        "status": "OPEN",
        "verification_visit_required": cycle_year % calc.VERIFICATION_VISIT_YEAR_MODULUS == 0,
        "verification_visit_completed_at": None,
        "total_claimed_points": 0,
        "total_verified_points": 0,
        "provisional_class": None,
        "resulting_class": None,
        "prior_class": None,
        "submitted_at": None,
    })
    db.cycles[row["id"]] = row
    return object_response(row, 201)


@bp.get("/crs-cycles/<cycle_id>")
def read_cycle(cycle_id):
    require(*ALL_ROLES)
    return object_response(lookup("cycle", cycle_id))


@bp.get("/crs-cycles")
def list_cycles():
    require(*ALL_ROLES)
    limit, offset = pagination()
    rows = query_filters(list(db.cycles.values()), {
        "community_id": ("community_id", None),
        "cycle_year": ("cycle_year", as_int),
        "status": ("status", None),
    })
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/crs-cycles/<cycle_id>/submit")
def submit_cycle(cycle_id):
    require("FloodplainAdministrator")
    cycle = lookup("cycle", cycle_id)
    if cycle["status"] != "OPEN":
        fail("ERR_CYCLE_NOT_OPEN")
    if now() > to_dt(cycle["due_at"]):
        fail("ERR_CYCLE_PAST_DUE")

    community = db.communities.get(cycle["community_id"])
    claimed = community["crs_credit_points_claimed"] if community else 0
    prior = community["crs_class"] if community else calc.WORST_CRS_CLASS
    provisional = engine.crs_class_for(claimed, community) if community else calc.WORST_CRS_CLASS

    cycle["status"] = "SUBMITTED"
    cycle["submitted_at"] = iso_now()
    cycle["total_claimed_points"] = claimed
    cycle["prior_class"] = prior
    cycle["provisional_class"] = provisional
    cycle["verification_visit_required"] = (
        cycle["cycle_year"] % calc.VERIFICATION_VISIT_YEAR_MODULUS == 0
        or (prior is not None and provisional < prior))
    touch(cycle)
    return object_response(cycle)


@bp.post("/crs-cycles/<cycle_id>/verify-visit")
def verify_visit(cycle_id):
    require("StateNfipCoordinator")
    cycle = lookup("cycle", cycle_id)
    data = body()
    opt_str(data, "visit_note")

    if cycle["status"] != "SUBMITTED":
        fail("ERR_CYCLE_NOT_SUBMITTED")

    cycle["status"] = "UNDER_VERIFICATION"
    cycle["verification_visit_completed_at"] = iso_now()
    touch(cycle)
    return object_response(cycle)


@bp.post("/crs-cycles/<cycle_id>/certify")
def certify_cycle(cycle_id):
    require("StateNfipCoordinator")
    cycle = lookup("cycle", cycle_id)
    if cycle["status"] not in ("SUBMITTED", "UNDER_VERIFICATION"):
        fail("ERR_CYCLE_NOT_CERTIFIABLE")

    standards = engine.standards_of(cycle["community_id"])
    if any(h["documentation_status"] == "SUBMITTED" for h in standards):
        fail("ERR_UNRESOLVED_SUBMISSIONS")
    if cycle["verification_visit_required"] and cycle["verification_visit_completed_at"] is None:
        fail("ERR_VERIFICATION_VISIT_REQUIRED")

    community = db.communities.get(cycle["community_id"])

    # Expiry sweep, ascending created_at.
    sanction_dirty = False
    for standard in sort_rows(standards):
        if standard["documentation_status"] != "VERIFIED":
            continue
        expires = standard["doc_expires_at"]
        if expires is None or to_dt(expires) > now():
            continue
        standard["documentation_status"] = "EXPIRED"
        standard["verified_points"] = 0
        touch(standard)
        if standard["activity_code"] == "A510_HIGHER_STD_ENFORCEMENT":
            sanction_dirty = True

    verified = 0
    if community is not None:
        engine.recompute_verified(community)
        if sanction_dirty:
            engine.sanction_fields(community)
        verified = community["crs_credit_points_verified"]
        resulting = engine.crs_class_for(verified, community)
        community["crs_class"] = resulting
        touch(community)
    else:
        resulting = calc.WORST_CRS_CLASS

    cycle["total_verified_points"] = verified
    cycle["resulting_class"] = resulting
    cycle["status"] = "CERTIFIED"
    touch(cycle)
    return object_response(cycle)


@bp.post("/crs-cycles/<cycle_id>/lapse")
def lapse_cycle(cycle_id):
    require("StateNfipCoordinator")
    cycle = lookup("cycle", cycle_id)
    if cycle["status"] != "OPEN":
        fail("ERR_CYCLE_NOT_OPEN")
    if now() <= to_dt(cycle["due_at"]):
        fail("ERR_CYCLE_NOT_PAST_DUE")

    cycle["status"] = "LAPSED"
    touch(cycle)

    community = db.communities.get(cycle["community_id"])
    if community is not None and community["crs_class"] != calc.WORST_CRS_CLASS:
        community["crs_class"] = calc.WORST_CRS_CLASS
        touch(community)
    return object_response(cycle)
