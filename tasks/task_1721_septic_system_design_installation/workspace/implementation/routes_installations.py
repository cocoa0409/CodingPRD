"""Installations (hold-point gated advance), inspections, material control."""

from flask import g

import constants as C
import db
import errors
import helpers as H
import middleware as mw
import response as R
import services as svc

S = db.STORE
BASE = "/septic-ops/installer-companies/<cid>/customers/<cuid>/sites/<sid>/installations"
PM = ("ProjectManager",)
INSPECTOR = ("Inspector",)

ADVANCE_NEXT = {
    "NOT_STARTED": "ROUGH_IN_PROGRESS",
    "ROUGH_IN_PROGRESS": "TANK_SET",
    "TANK_SET": "FIELD_INSTALLED",
    "FIELD_INSTALLED": "READY_FOR_FINAL",
}

LEG_HOLD_POINT = {
    "ROUGH_IN_PROGRESS": "TANK_SET",
    "TANK_SET": "FIELD_LAYOUT",
}

LEG_MATERIAL_KINDS = {
    "ROUGH_IN_PROGRESS": ("TANK",),
    "TANK_SET": ("PIPE", "AGGREGATE", "CHAMBER"),
}

PUMP_REQUIRED_SYSTEM_TYPES = ("PRESSURE_DISTRIBUTION", "AEROBIC")


def create_installation(cid, cuid, sid):
    site = H.resolve_site(cid, cuid, sid)
    b = mw.body()
    # (4) FK: permit must exist for this site
    permit = H.fk_site_row("permits", site, b.get("permit_id"))
    crew_lead = mw.req_str(b, "crew_lead")
    rec = db.create_record("installations", {
        "site_id": site["id"],
        "permit_id": permit["id"],
        "crew_lead": crew_lead,
        "started_period": None,
        "completed_period": None,
        "final_absorption_area_sqft": None,
        "status": "NOT_STARTED",
    })
    return R.respond_object(rec, 201)


def list_installations(cid, cuid, sid):
    site = H.resolve_site(cid, cuid, sid)
    rows = H.children("installations", "site_id", site["id"])
    rows = H.apply_filters(rows, {"status": "status"})
    return R.respond_list(rows)


def get_installation(cid, cuid, sid, iid):
    site = H.resolve_site(cid, cuid, sid)
    return R.respond_object(H.resolve_installation(site, iid))


def _permit_and_design(inst):
    permit = S["permits"][inst["permit_id"]]
    design = S["designs"][permit["design_id"]]
    return permit, design


def advance_installation(cid, cuid, sid, iid):
    site = H.resolve_site(cid, cuid, sid)
    inst = H.resolve_installation(site, iid)
    permit, design = _permit_and_design(inst)
    # (5) state: must be in an advancing leg
    if inst["status"] not in ADVANCE_NEXT:
        errors.invalid_state("Installation is not in a state that can advance")
    # (6) site must be OPEN
    if site["status"] != "OPEN":
        raise errors.ApiError(errors.ERR_SITE_FROZEN, 409, "Site is not OPEN")
    # (7) first leg only: permit validity window
    if (inst["status"] == "NOT_STARTED"
            and site["current_period_index"] > permit["expires_period"]):
        raise errors.ApiError(errors.ERR_PERMIT_EXPIRED, 409,
                              "The permit validity window has passed")
    # (12) hold-point gating
    required_hold = LEG_HOLD_POINT.get(inst["status"])
    if required_hold is not None:
        passed = any(i["hold_point"] == required_hold and i["result"] == "PASSED"
                     for i in svc.inspections_of_installation(inst["id"]))
        if not passed:
            raise errors.ApiError(
                errors.ERR_HOLD_POINT_NOT_PASSED, 409,
                "A PASSED {} inspection is required".format(required_hold))
    # (13) material verification completeness
    mvs = svc.materials_of_installation(inst["id"])
    kinds = LEG_MATERIAL_KINDS.get(inst["status"], ())
    if any(mv["material_kind"] in kinds and not mv["verified"] for mv in mvs):
        raise errors.ApiError(errors.ERR_MATERIALS_UNVERIFIED, 409,
                              "Required material deliveries are not verified")
    if inst["status"] == "FIELD_INSTALLED":
        if design["system_type"] in PUMP_REQUIRED_SYSTEM_TYPES:
            if any(mv["material_kind"] == "PUMP" and not mv["verified"]
                   for mv in mvs):
                raise errors.ApiError(errors.ERR_MATERIALS_UNVERIFIED, 409,
                                      "PUMP deliveries are not verified")
    # (14) permit must be ISSUED
    if permit["status"] != "ISSUED":
        raise errors.ApiError(errors.ERR_PERMIT_NOT_ISSUED, 409,
                              "The authorizing permit is not ISSUED")
    fields = {"status": ADVANCE_NEXT[inst["status"]]}
    if inst["status"] == "NOT_STARTED":
        fields["started_period"] = site["current_period_index"]
    db.set_fields(inst, **fields)
    return R.respond_object(inst)


def remediate_installation(cid, cuid, sid, iid):
    site = H.resolve_site(cid, cuid, sid)
    inst = H.resolve_installation(site, iid)
    permit, _design = _permit_and_design(inst)
    # (5) state
    if inst["status"] != "FAILED_HOLD":
        errors.invalid_state("Only a FAILED_HOLD installation may be remediated")
    # (6) site must be OPEN
    if site["status"] != "OPEN":
        raise errors.ApiError(errors.ERR_SITE_FROZEN, 409, "Site is not OPEN")
    # (14) permit must be ISSUED
    if permit["status"] != "ISSUED":
        raise errors.ApiError(errors.ERR_PERMIT_NOT_ISSUED, 409,
                              "The authorizing permit is not ISSUED")
    db.set_fields(inst, status="READY_FOR_FINAL")
    return R.respond_object(inst)


def abandon_installation(cid, cuid, sid, iid):
    site = H.resolve_site(cid, cuid, sid)
    inst = H.resolve_installation(site, iid)
    # (5) state: any non-terminal state may be abandoned
    if inst["status"] not in C.INSTALLATION_NON_TERMINAL:
        errors.invalid_state("Only a non-terminal installation may be abandoned")
    db.set_fields(inst, status="ABANDONED")
    return R.respond_object(inst)


# -------------------------------------------------------------- inspections

def create_inspection(cid, cuid, sid, iid):
    site = H.resolve_site(cid, cuid, sid)
    inst = H.resolve_installation(site, iid)
    b = mw.body()
    # (4) FK: inspector within the company
    inspector = H.fk_company_staff("inspectors", cid, b.get("inspector_id"))
    scheduled_period = b.get("scheduled_period")
    # (17.5) inspector capacity: one PENDING inspection per inspector per period
    if isinstance(scheduled_period, int) and not isinstance(scheduled_period, bool):
        for other in S["inspections"].values():
            if (other["inspector_id"] == inspector["id"]
                    and other["result"] == "PENDING"
                    and other["scheduled_period"] == scheduled_period):
                raise errors.ApiError(
                    errors.ERR_SCHEDULING_CONFLICT, 409,
                    "Inspector already holds a PENDING inspection at that period")
    # (19) ranges
    hold_point = mw.req_enum(b, "hold_point", C.HOLD_POINTS)
    scheduled_period = mw.req_int(b, "scheduled_period")
    if scheduled_period < 0:
        errors.invalid_request("scheduled_period must be >= 0")
    rec = db.create_record("inspections", {
        "installation_id": inst["id"],
        "hold_point": hold_point,
        "inspector_id": inspector["id"],
        "result": "PENDING",
        "scheduled_period": scheduled_period,
        "decided_period": None,
        "decision_note": None,
    })
    return R.respond_object(rec, 201)


def list_inspections(cid, cuid, sid, iid):
    site = H.resolve_site(cid, cuid, sid)
    inst = H.resolve_installation(site, iid)
    rows = svc.inspections_of_installation(inst["id"])
    rows = H.apply_filters(rows, {"result": "result"})
    return R.respond_list(rows)


def get_inspection(cid, cuid, sid, iid, inspid):
    site = H.resolve_site(cid, cuid, sid)
    inst = H.resolve_installation(site, iid)
    return R.respond_object(H.resolve_inspection(inst, inspid))


def decide_inspection(cid, cuid, sid, iid, inspid):
    site = H.resolve_site(cid, cuid, sid)
    inst = H.resolve_installation(site, iid)
    insp = H.resolve_inspection(inst, inspid)
    b = mw.body()
    # (5) state
    if insp["result"] != "PENDING":
        errors.invalid_state("Only a PENDING inspection may be decided")
    decision = b.get("decision")
    # (11) segregation: inspector of record; crew independence
    if g.user_id != insp["inspector_id"]:
        raise errors.ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                              "Only the inspector of record may decide this inspection")
    inspector = S["inspectors"].get(insp["inspector_id"])
    if inspector is not None and inspector["full_name"] == inst["crew_lead"]:
        raise errors.ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                              "The inspector must be independent of the crew lead")
    # (16) decision maturity
    if site["current_period_index"] < insp["scheduled_period"]:
        raise errors.ApiError(errors.ERR_INSPECTION_TOO_EARLY, 409,
                              "The inspection's scheduled period has not been reached")
    # (18) FAIL requires a decision_note >= 20 chars
    note = b.get("decision_note")
    if decision == "FAIL":
        mw.req_note(b, "decision_note")
    # (24) FINAL PASS requires READY_FOR_FINAL
    if (decision == "PASS" and insp["hold_point"] == "FINAL"
            and inst["status"] != "READY_FOR_FINAL"):
        raise errors.ApiError(errors.ERR_INSTALLATION_NOT_READY, 409,
                              "Installation is not READY_FOR_FINAL")
    # (28) enumerated decision payload
    if decision not in ("PASS", "FAIL"):
        raise errors.ApiError(errors.ERR_INVALID_DECISION, 400,
                              "decision must be PASS or FAIL")
    if decision == "PASS":
        fields = {"result": "PASSED",
                  "decided_period": site["current_period_index"]}
        if isinstance(note, str):
            fields["decision_note"] = note
        db.set_fields(insp, **fields)
        if insp["hold_point"] == "FINAL":
            svc.complete_installation(site, inst)
    else:
        db.set_fields(insp, result="FAILED",
                      decided_period=site["current_period_index"],
                      decision_note=note)
        if insp["hold_point"] == "FINAL" and inst["status"] == "READY_FOR_FINAL":
            db.set_fields(inst, status="FAILED_HOLD")
    return R.respond_object(insp)


# ------------------------------------------------------ material verification

def create_material(cid, cuid, sid, iid):
    site = H.resolve_site(cid, cuid, sid)
    inst = H.resolve_installation(site, iid)
    b = mw.body()
    # (19) ranges
    material_kind = mw.req_enum(b, "material_kind", C.MATERIAL_KINDS)
    quantity = mw.req_num(b, "quantity")
    if quantity <= 0:
        errors.invalid_request("quantity must be > 0")
    unit_cost_cents = mw.req_int(b, "unit_cost_cents")
    if unit_cost_cents < 0:
        errors.invalid_request("unit_cost_cents must be >= 0")
    rec = db.create_record("material_verifications", {
        "installation_id": inst["id"],
        "material_kind": material_kind,
        "quantity": quantity,
        "unit_cost_cents": unit_cost_cents,
        "verified": False,
        "verified_by": None,
        "verified_period": None,
    })
    return R.respond_object(rec, 201)


def list_materials(cid, cuid, sid, iid):
    site = H.resolve_site(cid, cuid, sid)
    inst = H.resolve_installation(site, iid)
    rows = svc.materials_of_installation(inst["id"])
    rows = H.apply_filters(rows, {"verified": "verified"})
    return R.respond_list(rows)


def get_material(cid, cuid, sid, iid, mvid):
    site = H.resolve_site(cid, cuid, sid)
    inst = H.resolve_installation(site, iid)
    return R.respond_object(H.resolve_material(inst, mvid))


def verify_material(cid, cuid, sid, iid, mvid):
    site = H.resolve_site(cid, cuid, sid)
    inst = H.resolve_installation(site, iid)
    mv = H.resolve_material(inst, mvid)
    # (5) already-verified deliveries admit no further verification
    if mv["verified"]:
        errors.invalid_state("This material delivery has already been verified")
    # (20) budget ceiling: strict > against the pinned design's ceiling
    _permit, design = _permit_and_design(inst)
    ceiling = svc.material_ceiling_cents(design)
    would_be = svc.verified_material_total_cents(inst["id"]) + svc.delivery_cost_cents(mv)
    if would_be > ceiling:
        raise errors.ApiError(errors.ERR_MATERIAL_BUDGET_EXCEEDED, 402,
                              "Verifying this delivery would exceed the material budget")
    db.set_fields(mv, verified=True, verified_by=g.user_id,
                  verified_period=site["current_period_index"])
    return R.respond_object(mv)


def register(app):
    app.add_url_rule(BASE, "inst_create", mw.auth(*PM)(create_installation),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE, "inst_list", mw.auth()(list_installations),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/<iid>", "inst_get", mw.auth()(get_installation),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/<iid>/advance", "inst_advance",
                     mw.auth(*PM)(advance_installation),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/<iid>/remediate", "inst_remediate",
                     mw.auth(*PM)(remediate_installation),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/<iid>/abandon", "inst_abandon",
                     mw.auth(*PM)(abandon_installation),
                     methods=["POST"], strict_slashes=False)

    app.add_url_rule(BASE + "/<iid>/inspections", "insp_create",
                     mw.auth(*PM)(create_inspection),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/<iid>/inspections", "insp_list",
                     mw.auth()(list_inspections),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/<iid>/inspections/<inspid>", "insp_get",
                     mw.auth()(get_inspection),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/<iid>/inspections/<inspid>/decide", "insp_decide",
                     mw.auth(*INSPECTOR)(decide_inspection),
                     methods=["POST"], strict_slashes=False)

    app.add_url_rule(BASE + "/<iid>/material-verifications", "mat_create",
                     mw.auth(*PM)(create_material),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(BASE + "/<iid>/material-verifications", "mat_list",
                     mw.auth()(list_materials),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/<iid>/material-verifications/<mvid>", "mat_get",
                     mw.auth()(get_material),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(BASE + "/<iid>/material-verifications/<mvid>/verify",
                     "mat_verify", mw.auth(*PM)(verify_material),
                     methods=["POST"], strict_slashes=False)
