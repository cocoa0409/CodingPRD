"""Projects, influent profiles, treatment objectives, process selection,
bidding, award and closeout deliverables."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import clock
import constants as C
import db
import domain
import response
import serialize
import validate
from errors import fail
from util import D, format_dt

bp = Blueprint("projects", __name__)


# ------------------------------------------------------------------ projects --

@bp.post("/projects")
def create_project():
    auth.require("ContractsAdministrator", "ApplicationEngineer")
    body = validate.body()
    name = validate.string(body, "name", max_length=160)
    owner_agency_name = validate.string(body, "owner_agency_name", max_length=200)
    procurement_type = validate.enum(
        body, "procurement_type", C.PROCUREMENT_TYPES, required=False,
        default="MUNICIPAL_BID")
    bid_due_at = validate.instant(body, "bid_due_at")
    guarantee_deadline_at = validate.instant(body, "guarantee_deadline_at")
    footprint_allowance = validate.number(
        body, "footprint_allowance_sf_per_stage", exclusive_minimum=0)
    if guarantee_deadline_at <= bid_due_at:
        fail("ERR_INVALID_REQUEST",
             "guarantee_deadline_at must be strictly after bid_due_at")

    row = db.new_row("projects")
    row.update({
        "name": name,
        "owner_agency_name": owner_agency_name,
        "procurement_type": procurement_type,
        "bid_due_at": format_dt(bid_due_at),
        "guarantee_deadline_at": format_dt(guarantee_deadline_at),
        "footprint_allowance_sf_per_stage": footprint_allowance,
        "status": "DRAFT",
        "delivery_posture": "ON_TRACK",
        "guarantee_status": "NOT_STARTED",
        "governing_influent_profile_id": None,
        "om_manual_status": "PENDING",
        "operator_training_status": "PENDING",
        "spare_parts_list_status": "PENDING",
        "base_bid_amount_cents": 0,
        "bond_premium_cents": 0,
        "contingency_cents": 0,
        "evaluated_bid_price_cents": 0,
        "offered_price_cents": 0,
        "contract_amount_cents": 0,
        "liquidated_damages_cents": 0,
        "awarded_at": None,
    })
    db.insert("projects", row)
    return response.created(serialize.row(row))


@bp.get("/projects")
def list_projects():
    auth.require(*auth.ROLES)
    status = validate.enum_filter("status", C.PROJECT_STATUSES)
    governing = validate.string_filter("governing_influent_profile_id")
    rows = db.all_rows("projects")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if governing:
        rows = [r for r in rows if r["governing_influent_profile_id"] == governing]
    rows = db.sorted_rows(rows, [("created_at", "desc")])
    return response.paginate(rows, serialize.row)


@bp.get("/projects/<project_id>")
def get_project(project_id):
    auth.require(*auth.ROLES)
    return response.ok(serialize.row(domain.project(project_id)))


# ---------------------------------------------------------- influent profiles --

@bp.post("/projects/<project_id>/influent-profiles")
def create_profile(project_id):
    auth.require("ApplicationEngineer")
    project = domain.project(project_id)
    body = validate.body()
    sample_label = validate.string(body, "sample_label", max_length=160)
    design_flow = validate.number(
        body, "design_flow_mgd", exclusive_minimum=0, places=3)
    peak_factor = validate.number(
        body, "peak_factor", required=False, default=Decimal("1.5"), minimum=1)
    turbidity = validate.number(body, "turbidity_ntu", minimum=0)
    tds = validate.number(body, "tds_mg_l", minimum=0)
    toc = validate.number(body, "toc_mg_l", minimum=0)
    chloride = validate.number(body, "chloride_mg_l", minimum=0)
    temperature = validate.number(body, "temperature_c")
    ph = validate.number(body, "ph", minimum=0, maximum=14)

    row = db.new_row("influent_profiles")
    row.update({
        "project_id": project["id"],
        "sample_label": sample_label,
        "design_flow_mgd": design_flow,
        "peak_factor": peak_factor,
        "turbidity_ntu": turbidity,
        "tds_mg_l": tds,
        "toc_mg_l": toc,
        "chloride_mg_l": chloride,
        "temperature_c": temperature,
        "ph": ph,
        "qa_status": "SUBMITTED",
        "qa_decided_by_user_id": None,
        "qa_note": None,
    })
    db.insert("influent_profiles", row)
    return response.created(serialize.row(row))


@bp.get("/projects/<project_id>/influent-profiles")
def list_project_profiles(project_id):
    auth.require(*auth.ROLES)
    project = domain.project(project_id)
    qa_status = validate.enum_filter("qa_status", C.QA_STATUSES)
    rows = [r for r in db.all_rows("influent_profiles")
            if r["project_id"] == project["id"]]
    if qa_status:
        rows = [r for r in rows if r["qa_status"] == qa_status]
    rows = db.sorted_rows(rows, [("created_at", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/influent-profiles")
def list_profiles():
    auth.require(*auth.ROLES)
    project_id = validate.string_filter("project_id")
    qa_status = validate.enum_filter("qa_status", C.QA_STATUSES)
    rows = db.all_rows("influent_profiles")
    if project_id:
        rows = [r for r in rows if r["project_id"] == project_id]
    if qa_status:
        rows = [r for r in rows if r["qa_status"] == qa_status]
    rows = db.sorted_rows(rows, [("created_at", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/influent-profiles/<profile_id>")
def get_profile(profile_id):
    auth.require(*auth.ROLES)
    return response.ok(serialize.row(domain.profile(profile_id)))


@bp.post("/influent-profiles/<profile_id>/qa-decision")
def qa_decision(profile_id):
    actor = auth.require("QualityEngineer")
    profile = domain.profile(profile_id)
    body = validate.body()
    decision = validate.enum(body, "decision", C.QA_DECISIONS)
    note = validate.string(body, "qa_note", required=False, default=None,
                           max_length=2000, allow_blank=True)
    if profile["qa_status"] != "SUBMITTED":
        fail("ERR_PROFILE_ALREADY_DECIDED",
             "influent profile has already been dispositioned")

    was_governing = False
    project = db.get("projects", profile["project_id"])
    if project is not None:
        was_governing = project["governing_influent_profile_id"] == profile["id"]

    profile["qa_status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    profile["qa_decided_by_user_id"] = actor
    profile["qa_note"] = note
    db.touch(profile)

    if project is not None and project["status"] != "DRAFT":
        should_rederive = decision == "ACCEPT" or was_governing
        if should_rederive:
            new_governing = calc.governing_influent_profile_id(
                project, raise_when_draft=False)
            if new_governing != project["governing_influent_profile_id"]:
                project["governing_influent_profile_id"] = new_governing
                db.touch(project)

    return response.ok(serialize.row(profile))


# ------------------------------------------------------- treatment objectives --

@bp.post("/projects/<project_id>/treatment-objectives")
def create_objective(project_id):
    auth.require("ApplicationEngineer")
    project = domain.project(project_id)
    body = validate.body()
    parameter = validate.enum(body, "parameter", C.OBJECTIVE_PARAMETERS)
    limit_value = validate.number(body, "limit_value", exclusive_minimum=0, places=3)
    basis = validate.enum(body, "basis", C.OBJECTIVE_BASES)
    regulatory_driver = validate.string(body, "regulatory_driver", max_length=300)

    for incumbent in db.all_rows("treatment_objectives"):
        if (incumbent["project_id"] == project["id"]
                and incumbent["parameter"] == parameter
                and incumbent["status"] == "ACTIVE"):
            incumbent["status"] = "RETIRED"
            db.touch(incumbent)

    row = db.new_row("treatment_objectives")
    row.update({
        "project_id": project["id"],
        "parameter": parameter,
        "limit_value": limit_value,
        "basis": basis,
        "regulatory_driver": regulatory_driver,
        "status": "ACTIVE",
    })
    db.insert("treatment_objectives", row)
    return response.created(serialize.row(row))


@bp.get("/projects/<project_id>/treatment-objectives")
def list_project_objectives(project_id):
    auth.require(*auth.ROLES)
    project = domain.project(project_id)
    status = validate.enum_filter("status", C.OBJECTIVE_STATUSES)
    rows = [r for r in db.all_rows("treatment_objectives")
            if r["project_id"] == project["id"]]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = db.sorted_rows(rows, [("parameter", "asc"), ("created_at", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/treatment-objectives")
def list_objectives():
    auth.require(*auth.ROLES)
    project_id = validate.string_filter("project_id")
    status = validate.enum_filter("status", C.OBJECTIVE_STATUSES)
    rows = db.all_rows("treatment_objectives")
    if project_id:
        rows = [r for r in rows if r["project_id"] == project_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = db.sorted_rows(rows, [("parameter", "asc"), ("created_at", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/treatment-objectives/<objective_id>")
def get_objective(objective_id):
    auth.require(*auth.ROLES)
    return response.ok(serialize.row(domain.objective(objective_id)))


# ------------------------------------------------------------ process selection --

@bp.post("/projects/<project_id>/process-selection")
def process_selection(project_id):
    auth.require("ApplicationEngineer")
    project = domain.project(project_id)
    validate.body()

    if project["status"] not in ("DRAFT", "SCOPED"):
        fail("ERR_INVALID_PROJECT_STATE",
             "process selection requires the project to be DRAFT or SCOPED")

    existing_stages = [s for s in db.all_rows("treatment_stages")
                       if s["project_id"] == project["id"]
                       and s["status"] in ("SELECTED", "ENGINEERED")]
    stage_ids = {s["id"] for s in existing_stages}
    for pkg in db.all_rows("equipment_packages"):
        if (pkg["treatment_stage_id"] in stage_ids
                and pkg["status"] in C.FABRICATION_LOCKED_PACKAGE_STATUSES):
            fail("ERR_INVALID_PROJECT_STATE",
                 "fabrication has begun; the treatment train may not be re-scoped")

    governing_id = calc.governing_influent_profile_id(project, raise_when_draft=False)
    if governing_id is None:
        fail("ERR_NO_ACCEPTED_INFLUENT_PROFILE",
             "project has no ACCEPTED influent profile")
    governing = db.get("influent_profiles", governing_id)

    roles = calc.required_roles(project)
    if not roles:
        fail("ERR_NO_TREATMENT_OBJECTIVES",
             "project has no ACTIVE treatment objectives")

    selections = [calc.select_technology(role, project, governing) for role in roles]

    for stage in existing_stages:
        stage["status"] = "SUPERSEDED"
        db.touch(stage)

    project["governing_influent_profile_id"] = governing_id
    created = []
    upstream_id = None
    for index, selection in enumerate(selections, start=1):
        stage = db.new_row("treatment_stages")
        stage.update({
            "project_id": project["id"],
            "technology_id": selection["technology"]["id"],
            "upstream_stage_id": upstream_id,
            "role": selection["role"],
            "stage_index": index,
            "design_flow_mgd": selection["flow"],
            "evaluated_cost_cents": selection["terms"]["evaluated_cost_cents"],
            "equipment_base_cost_cents":
                selection["terms"]["equipment_base_cost_cents"],
            "status": "SELECTED",
        })
        db.insert("treatment_stages", stage)
        created.append(stage)
        upstream_id = stage["id"]

    if project["status"] == "DRAFT":
        project["status"] = "SCOPED"
    domain.recompute_posture(project)

    return response.array_ok(serialize.rows(created), 201)


# ----------------------------------------------------------- treatment stages --

@bp.get("/treatment-stages")
def list_stages():
    auth.require(*auth.ROLES)
    project_id = validate.string_filter("project_id")
    technology_id = validate.string_filter("technology_id")
    upstream_stage_id = validate.string_filter("upstream_stage_id")
    status = validate.enum_filter("status", C.STAGE_STATUSES)
    rows = db.all_rows("treatment_stages")
    if project_id:
        rows = [r for r in rows if r["project_id"] == project_id]
    if technology_id:
        rows = [r for r in rows if r["technology_id"] == technology_id]
    if upstream_stage_id:
        rows = [r for r in rows if r["upstream_stage_id"] == upstream_stage_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = db.sorted_rows(rows, [("stage_index", "asc"), ("created_at", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/treatment-stages/<stage_id>")
def get_stage(stage_id):
    auth.require(*auth.ROLES)
    return response.ok(serialize.row(domain.stage(stage_id)))


# ---------------------------------------------------------------- bid / award --

@bp.post("/projects/<project_id>/bid")
def post_bid(project_id):
    actor = auth.require("ContractsAdministrator")
    project = domain.project(project_id)
    body = validate.body()
    offered = validate.integer(body, "offered_price_cents", minimum=0)

    if project["status"] in ("DRAFT", "SCOPED", "BID_BLOCKED"):
        fail("ERR_INVALID_PROJECT_STATE", "project has not reached bidding")
    if project["status"] != "BID_READY":
        fail("ERR_BID_ALREADY_SUBMITTED", "project bid is already on record")

    submittals = [s for s in db.all_rows("or_equal_submittals")
                  if s["project_id"] == project["id"]]
    pre_approved = [s for s in submittals if s["status"] == "PRE_APPROVED"]

    for submittal in pre_approved:
        domain.forbid_same_user(actor, submittal["authored_by_user_id"],
                                "ERR_SOD_AUTHOR_IS_BIDDER")

    stages = [s for s in db.all_rows("treatment_stages")
              if s["project_id"] == project["id"]
              and s["status"] in ("SELECTED", "ENGINEERED")]
    for stage in stages:
        priced = [
            p for p in db.all_rows("equipment_packages")
            if p["treatment_stage_id"] == stage["id"]
            and p["status"] in C.BID_ELIGIBLE_PACKAGE_STATUSES
            and int(p["firm_cost_cents"]) > 0
        ]
        if len(priced) != 1:
            fail("ERR_OR_EQUAL_NOT_PREAPPROVED",
                 "stage %s is not fully engineered and priced" % stage["stage_index"])
    if not pre_approved:
        fail("ERR_OR_EQUAL_NOT_PREAPPROVED",
             "project has no PRE_APPROVED or-equal submittal")

    if clock.now() >= domain.dt_of(project["bid_due_at"]):
        fail("ERR_BID_WINDOW_CLOSED", "the bid window has closed")

    waterfall = calc.bid_evaluated_price(project)
    if not calc.margin_ok(offered, waterfall["evaluated_bid_price_cents"]):
        fail("ERR_BID_MARGIN_BELOW_FLOOR",
             "offered price does not clear the evaluated floor by 8 percent")

    project.update(waterfall)
    project["offered_price_cents"] = offered
    project["status"] = "BID_SUBMITTED"
    db.touch(project)
    return response.ok(serialize.row(project))


@bp.post("/projects/<project_id>/award")
def post_award(project_id):
    auth.require("ContractsAdministrator")
    project = domain.project(project_id)
    body = validate.body()
    decision = validate.enum(body, "award_decision", C.AWARD_DECISIONS)

    if project["status"] != "BID_SUBMITTED":
        fail("ERR_INVALID_PROJECT_STATE", "project is not awaiting an award decision")

    if decision == "AWARDED":
        project["status"] = "AWARDED"
        project["contract_amount_cents"] = int(project["offered_price_cents"])
        project["awarded_at"] = clock.now_iso()
    else:
        project["status"] = "CLOSED"
        for submittal in db.all_rows("or_equal_submittals"):
            if (submittal["project_id"] == project["id"]
                    and submittal["status"] in ("DRAFT", "SUBMITTED")):
                submittal["status"] = "REJECTED"
                db.touch(submittal)
    db.touch(project)
    return response.ok(serialize.row(project))


# -------------------------------------------------------------- deliverables --

@bp.post("/projects/<project_id>/deliverable-acceptance")
def deliverable_acceptance(project_id):
    auth.require("OwnerRepresentative")
    project = domain.project(project_id)
    body = validate.body()
    deliverable_type = validate.enum(body, "deliverable_type", C.DELIVERABLE_TYPES)
    decision = validate.enum(body, "decision", C.QA_DECISIONS)

    field = C.DELIVERABLE_FIELD[deliverable_type]
    if project[field] == "ACCEPTED":
        fail("ERR_DELIVERABLE_ALREADY_ACCEPTED",
             "%s has already been accepted" % deliverable_type)

    project[field] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    db.touch(project)
    return response.ok(serialize.row(project))
