"""System designs: creation/amendment chain, submit, decide, revise, withdraw."""

from flask import g

import constants as C
import db
import errors
import helpers as H
import middleware as mw
import response as R
import services as svc

S = db.STORE
BASE = "/septic-ops/installer-companies/<cid>/customers/<cuid>/sites/<sid>/designs"
DESIGNER = ("SystemDesigner",)
OFFICER = ("HealthOfficer",)


def create_design(cid, cuid, sid):
    site = H.resolve_site(cid, cuid, sid)
    b = mw.body()
    # (4) body FKs, in-scope
    designer = H.fk_company_staff("system_designers", cid, b.get("designer_id"))
    soil_eval = H.fk_site_row("soil_evaluations", site, b.get("soil_evaluation_id"))
    perc = H.fk_site_row("percolation_tests", site, b.get("percolation_test_id"))
    supersedes_id = b.get("supersedes_design_id")
    superseded = None
    if supersedes_id is not None:
        superseded = H.fk_site_row("designs", site, supersedes_id)
    # (19) ranges
    bedroom_count = mw.req_int(b, "bedroom_count")
    if bedroom_count < 1 or bedroom_count > 12:
        errors.invalid_request("bedroom_count must be between 1 and 12")
    system_type = mw.req_enum(b, "system_type", C.SYSTEM_TYPES)

    design_version = 1
    if superseded is not None:
        design_version = superseded["design_version"] + 1

    rec = db.create_record("designs", {
        "site_id": site["id"],
        "designer_id": designer["id"],
        "soil_evaluation_id": soil_eval["id"],
        "percolation_test_id": perc["id"],
        "bedroom_count": bedroom_count,
        "system_type": system_type,
        "design_daily_flow_gpd": 0.0,
        "required_absorption_area_sqft": 0,
        "tank_capacity_gal": 0,
        "reserve_area_sqft": 0,
        "provisional_estimate_cents": None,
        "design_version": design_version,
        "supersedes_design_id": supersedes_id,
        "status": "DRAFT",
    })
    sizing = svc.compute_sizing(site, soil_eval, bedroom_count, rec["id"])
    rec.update(sizing)
    # amendment chain: a REJECTED or WITHDRAWN named design becomes SUPERSEDED
    if superseded is not None and superseded["status"] in ("REJECTED", "WITHDRAWN"):
        db.set_fields(superseded, status="SUPERSEDED")
    return R.respond_object(rec, 201)


def list_designs(cid, cuid, sid):
    site = H.resolve_site(cid, cuid, sid)
    rows = H.children("designs", "site_id", site["id"])
    rows = H.apply_filters(rows, {"status": "status"})
    return R.respond_list(rows)


def get_design(cid, cuid, sid, did):
    site = H.resolve_site(cid, cuid, sid)
    return R.respond_object(H.resolve_design(site, did))


def submit_design(cid, cuid, sid, did):
    site = H.resolve_site(cid, cuid, sid)
    design = H.resolve_design(site, did)
    # (5) state
    if design["status"] != "DRAFT":
        errors.invalid_state("Only a DRAFT design may be submitted")
    # (6) seasonal freeze
    if site["status"] != "OPEN":
        raise errors.ApiError(errors.ERR_SITE_FROZEN, 409, "Site is not OPEN")
    soil_eval = S["soil_evaluations"][design["soil_evaluation_id"]]
    perc = S["percolation_tests"][design["percolation_test_id"]]
    # (8) pinned science must still be RECORDED
    if soil_eval["status"] != "RECORDED" or perc["status"] != "RECORDED":
        raise errors.ApiError(errors.ERR_STALE_SCIENCE, 409,
                              "Pinned science is no longer RECORDED")
    # (9) science freshness — strict > boundary at SCIENCE_MAX_AGE_PERIODS
    if (svc.science_is_stale(site, soil_eval["evaluation_date_period"])
            or svc.science_is_stale(site, perc["test_date_period"])):
        raise errors.ApiError(errors.ERR_SCIENCE_EXPIRED, 409,
                              "Pinned science has expired")
    # (11) only the authoring designer may submit
    if g.user_id != design["designer_id"]:
        raise errors.ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                              "Only the authoring designer may submit this design")
    # re-derive sizing against current variance context, then submit
    sizing = svc.compute_sizing(site, soil_eval, design["bedroom_count"], design["id"])
    db.set_fields(design, status="SUBMITTED", **sizing)
    return R.respond_object(design)


def decide_design(cid, cuid, sid, did):
    site = H.resolve_site(cid, cuid, sid)
    design = H.resolve_design(site, did)
    b = mw.body()
    # (4) officer FK
    officer = H.fk_company_staff("health_officers", cid, b.get("officer_id"))
    # (5) state
    if design["status"] != "SUBMITTED":
        errors.invalid_state("Only a SUBMITTED design may be decided")
    decision = b.get("decision")
    # (10) high-water-table GRAVITY designs need an APPROVED HWT variance
    if (decision == "APPROVE" and site["high_water_table"]
            and design["system_type"] == "GRAVITY"
            and not svc.has_approved_variance_for_design(design["id"],
                                                         "HIGH_WATER_TABLE")):
        raise errors.ApiError(
            errors.ERR_VARIANCE_REQUIRED, 409,
            "An APPROVED HIGH_WATER_TABLE variance is required for this design")
    # (11) independence: officer badge must differ from the designer's license
    if decision == "APPROVE":
        designer = S["system_designers"].get(design["designer_id"])
        if designer is not None and officer["badge_number"] == designer["license_number"]:
            raise errors.ApiError(
                errors.ERR_SEGREGATION_OF_DUTIES, 403,
                "The deciding officer must not be the authoring designer")
    # (18) REJECT requires a decision_note of at least 20 chars
    note = b.get("decision_note")
    if decision == "REJECT":
        mw.req_note(b, "decision_note")
    # (28) enumerated decision payload
    if decision not in ("APPROVE", "REJECT"):
        raise errors.ApiError(errors.ERR_INVALID_DECISION, 400,
                              "decision must be APPROVE or REJECT")
    if decision == "APPROVE":
        svc.approve_design(site, design)
    else:
        db.set_fields(design, status="REJECTED")
    return R.respond_object(design)


def revise_design(cid, cuid, sid, did):
    site = H.resolve_site(cid, cuid, sid)
    design = H.resolve_design(site, did)
    b = mw.body()
    # (5) state
    if design["status"] != "REJECTED":
        errors.invalid_state("Only a REJECTED design may be revised")
    # (11) only the authoring designer
    if g.user_id != design["designer_id"]:
        raise errors.ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                              "Only the authoring designer may revise this design")
    # (25) OCC
    expected = b.get("expected_design_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        errors.invalid_request("expected_design_version is required and must be an integer")
    if expected != design["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412,
                              "expected_design_version does not match the current version")
    db.set_fields(design, status="DRAFT")
    return R.respond_object(design)


def withdraw_design(cid, cuid, sid, did):
    site = H.resolve_site(cid, cuid, sid)
    design = H.resolve_design(site, did)
    # (5) state
    if design["status"] != "DRAFT":
        errors.invalid_state("Only a DRAFT design may be withdrawn")
    # (11) only the authoring designer
    if g.user_id != design["designer_id"]:
        raise errors.ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                              "Only the authoring designer may withdraw this design")
    db.set_fields(design, status="WITHDRAWN")
    return R.respond_object(design)


def register(app):
    app.add_url_rule(BASE, "design_create", mw.auth(*DESIGNER)(create_design),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE, "design_list", mw.auth()(list_designs),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/<did>", "design_get", mw.auth()(get_design),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/<did>/submit", "design_submit",
                     mw.auth(*DESIGNER)(submit_design),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/<did>/decide", "design_decide",
                     mw.auth(*OFFICER)(decide_design),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/<did>/revise", "design_revise",
                     mw.auth(*DESIGNER)(revise_design),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/<did>/withdraw", "design_withdraw",
                     mw.auth(*DESIGNER)(withdraw_design),
                     methods=["POST"], strict_slashes=False)
