"""Storage project endpoints (PRD 3.1, 3.5 unitization, 3.8 authorization, 3.9 PISC/closure)."""

from decimal import Decimal as D

from flask import Blueprint

import clock
import db
import enums
import middleware as mw
import response
from errors import ApiError
from services import calc, derive, lookup, serialize

bp = Blueprint("projects", __name__)

ADMIN = "ProgramAdmin"
DEV = "ProjectDeveloper"
REVIEWER = "RegulatoryReviewer"
VERIFIER = "IndependentVerifier"
LANDOWNER = "Landowner"


@bp.post("/ccs/storage-projects")
@mw.require(ADMIN)
def create_project():
    payload = mw.body()
    name = mw.req_str(payload, "name", max_len=200)
    operator_name = mw.req_str(payload, "operator_name")
    basin_code = mw.req_str(payload, "basin_code", max_len=20)
    total_project_acreage = mw.req_num(payload, "total_project_acreage", gt=0)
    requested_rate = mw.req_num(payload, "requested_annual_injection_rate_tpy", gt=0)
    annual_monitoring_cost = mw.req_num(payload, "annual_monitoring_cost_usd", ge=0)
    required_consent_pct = mw.opt_num(
        payload, "required_consent_pct", default=D("60"), gt=0, le=100
    )
    ca_rig_slots = mw.opt_int(payload, "ca_rig_slots", default=2, ge=1)

    row = db.base_fields()
    row.update(
        {
            "name": name,
            "operator_name": operator_name,
            "basin_code": basin_code,
            "total_project_acreage": total_project_acreage,
            "requested_annual_injection_rate_tpy": requested_rate,
            "annual_monitoring_cost_usd": annual_monitoring_cost,
            "required_consent_pct": required_consent_pct,
            "ca_rig_slots": ca_rig_slots,
            "status": "DRAFT",
            "operational_posture": "OPEN",
            "governing_geologic_model_id": None,
            "aor_radius_km": D("0"),
            "secured_acreage": D("0.0000"),
            "outstanding_acreage": calc.q4(total_project_acreage),
            "pore_space_consent_pct": D("0.00"),
            "pore_space_bonus_total_usd": D("0.00"),
            "unitization_status": "NOT_FILED",
            "unitization_consent_pct_at_filing": None,
            "statutory_bonus_per_acre_usd": None,
            "_statutory_royalty_rate_pct": None,
            "corrective_action_completion_pct": D("100.00"),
            "cumulative_stored_tonnes": D("0.000"),
            "pending_credit_usd": D("0.00"),
            "required_financial_assurance_usd": D("0.00"),
            "allocated_assurance_usd": D("0.00"),
            "assurance_coverage_status": "UNFUNDED",
            "effective_annual_monitoring_cost_usd": calc.q2(annual_monitoring_cost),
            "pisc_duration_years": calc.PISC_DEFAULT_YEARS,
            "alternative_timeframe_years": None,
            "pisc_start_at": None,
            "pisc_start_dt": None,
            "pisc_elapsed_years": D("0.000"),
            "non_endangerment_demonstrated": False,
            "closure_status": "NOT_REQUESTED",
            "closure_certified_by_user_id": None,
            "closure_certified_at": None,
            "open_remediation_count": 0,
        }
    )
    db.projects[row["id"]] = row
    return response.object_response(serialize.project(row), 201)


@bp.get("/ccs/storage-projects")
@mw.require(ADMIN, DEV, REVIEWER, VERIFIER)
def list_projects():
    status = mw.query_enum("status", enums.PROJECT_STATUS)
    rows = db.ordered(db.projects.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = mw.paginate(rows)
    return response.list_response([serialize.project(r) for r in page], limit, offset, total)


@bp.get("/ccs/storage-projects/<project_id>")
@mw.require(ADMIN, DEV, REVIEWER, VERIFIER, LANDOWNER)
def get_project(project_id):
    project = lookup.project(project_id)
    return response.object_response(serialize.project(project))


# --------------------------------------------------------------------------- #
# Unitization
# --------------------------------------------------------------------------- #


@bp.post("/ccs/storage-projects/<project_id>/unitization-petition")
@mw.require(DEV)
def unitization_petition(project_id):
    payload = mw.body()
    mw.opt_str(payload, "petition_note")

    project = lookup.project(project_id)
    derive.require_not_frozen(project)

    if project["unitization_status"] != "NOT_FILED":
        raise ApiError("ERR_INVALID_PROJECT_STATE", "unitization petition already filed")
    if project["status"] not in ("SITE_CHARACTERIZATION", "PERMITTING"):
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE",
            "unitization may only be petitioned during site characterization or permitting",
        )

    project["unitization_consent_pct_at_filing"] = project["pore_space_consent_pct"]
    project["unitization_status"] = "FILED"
    db.touch(project)
    return response.object_response(serialize.project(project))


@bp.post("/ccs/storage-projects/<project_id>/unitization-ruling")
@mw.require(REVIEWER)
def unitization_ruling(project_id):
    payload = mw.body()
    decision = mw.req_enum(payload, "decision", enums.UNITIZATION_DECISION)
    statutory_bonus = None
    statutory_royalty = mw.opt_num(payload, "statutory_royalty_rate_pct", ge=0)
    if decision == "GRANT":
        statutory_bonus = mw.req_num(payload, "statutory_bonus_per_acre_usd", ge=0)
    mw.opt_str(payload, "ruling_note")

    project = lookup.project(project_id)
    derive.require_not_frozen(project)

    if project["unitization_status"] != "FILED":
        raise ApiError("ERR_INVALID_PROJECT_STATE", "no filed unitization petition to rule on")

    if decision == "DENY":
        project["unitization_status"] = "DENIED"
        db.touch(project)
        return response.object_response(serialize.project(project))

    if project["pore_space_consent_pct"] < project["required_consent_pct"]:
        raise ApiError(
            "ERR_UNITIZATION_CONSENT_BELOW_THRESHOLD",
            "pore space consent is below the project's required consent percentage",
        )

    project["statutory_bonus_per_acre_usd"] = calc.q2(statutory_bonus)
    project["_statutory_royalty_rate_pct"] = statutory_royalty

    for tract in db.tracts_of(project["id"]):
        if tract["lease_status"] in ("UNLEASED", "REJECTED"):
            tract["lease_status"] = "UNITIZED"
            tract["executed_bonus_per_acre_usd"] = project["statutory_bonus_per_acre_usd"]
            tract["executed_royalty_rate_pct"] = statutory_royalty
            derive.refresh_tract(tract)
            db.touch(tract)

    derive.recompute_pore_space(project)
    project["unitization_status"] = "GRANTED"
    db.touch(project)
    return response.object_response(serialize.project(project))


# --------------------------------------------------------------------------- #
# Authorization / PISC / closure
# --------------------------------------------------------------------------- #


@bp.post("/ccs/storage-projects/<project_id>/authorize-injection")
@mw.require(REVIEWER)
def authorize_injection(project_id):
    payload = mw.body()
    mw.opt_str(payload, "authorization_note")

    project = lookup.project(project_id)
    derive.require_not_frozen(project)

    if project["status"] != "PERMITTING":
        raise ApiError("ERR_INVALID_PROJECT_STATE", "project status must be PERMITTING")
    if project["operational_posture"] != "OPEN":
        raise ApiError("ERR_INVALID_PROJECT_STATE", "project operational posture must be OPEN")

    model = derive.governing_model(project)
    if model is None or model["seal_classification"] not in ("PASS", "CONDITIONAL"):
        raise ApiError(
            "ERR_SEAL_INTEGRITY_FAIL",
            "governing geologic model is missing or its seal classification is FAIL",
        )
    if D(project["aor_radius_km"]) <= 0:
        raise ApiError("ERR_AOR_NOT_DELINEATED", "area of review has not been delineated")

    permits = db.permits_of(project["id"])
    if not any(p["permit_status"] == "APPROVED" for p in permits):
        raise ApiError("ERR_INVALID_PROJECT_STATE", "no injection well permit is APPROVED")

    plans = db.plans_of(project["id"])
    if not any(p["status"] in ("APPROVED", "APPROVED_WITH_CONDITIONS") for p in plans):
        raise ApiError("ERR_MRV_PLAN_NOT_APPROVED", "no monitoring plan has been approved")

    if project["corrective_action_completion_pct"] != D("100.00"):
        raise ApiError(
            "ERR_CORRECTIVE_ACTION_INCOMPLETE", "corrective action completion percentage is below 100"
        )

    consent_ok = project["pore_space_consent_pct"] >= project["required_consent_pct"]
    if not consent_ok and project["unitization_status"] != "GRANTED":
        raise ApiError("ERR_PORE_SPACE_CONSENT_INSUFFICIENT", "pore space consent is insufficient")

    if project["assurance_coverage_status"] != "FUNDED":
        raise ApiError("ERR_ASSURANCE_INSUFFICIENT", "financial assurance is not fully funded")

    project["status"] = "INJECTION_AUTHORIZED"
    db.touch(project)
    return response.object_response(serialize.project(project))


@bp.post("/ccs/storage-projects/<project_id>/begin-pisc")
@mw.require(DEV)
def begin_pisc(project_id):
    payload = mw.body()
    alternative_years = mw.opt_int(payload, "alternative_timeframe_years")

    project = lookup.project(project_id)
    derive.require_not_frozen(project)

    if project["status"] != "INJECTION_ACTIVE":
        raise ApiError("ERR_INVALID_PROJECT_STATE", "project status must be INJECTION_ACTIVE")

    if any(o["status"] == "OPEN" for o in db.orders_of(project["id"])):
        raise ApiError("ERR_OPEN_REMEDIATION_ORDER", "project has an open remediation order")

    for permit in db.permits_of(project["id"]):
        if permit["permit_status"] == "ACTIVE" and permit["construction_status"] != "COMPLETED":
            raise ApiError(
                "ERR_INVALID_PERMIT_STATE",
                "an active permit has not reached COMPLETED construction status",
            )

    now = clock.now()
    project["pisc_start_at"] = clock.fmt(now)
    project["pisc_start_dt"] = now
    if alternative_years is not None:
        project["alternative_timeframe_years"] = alternative_years
    derive.recompute_pisc_duration(project)
    project["status"] = "PISC"
    derive.suspension_cascade(project)
    derive.recompute_required_assurance(project)
    derive.refresh_pisc_elapsed(project)
    db.touch(project)
    return response.object_response(serialize.project(project))


@bp.post("/ccs/storage-projects/<project_id>/certify-closure")
@mw.require(REVIEWER)
def certify_closure(project_id):
    project = lookup.maybe_project(project_id)

    # PRD 2.6 rank 4 — segregation of duties outranks request shape and state.
    if project is not None:
        acting = mw.caller_id()
        for permit in db.permits_of(project["id"]):
            if permit["technical_reviewer_user_id"] == acting:
                raise ApiError(
                    "ERR_SEGREGATION_OF_DUTIES",
                    "closure may not be certified by a permit's technical reviewer",
                )

    payload = mw.body()
    non_endangerment = mw.req_bool(payload, "non_endangerment_demonstrated")
    mw.opt_str(payload, "closure_note")

    project = lookup.project(project_id)
    derive.require_not_frozen(project)

    if project["status"] != "PISC":
        raise ApiError("ERR_INVALID_PROJECT_STATE", "project status must be PISC")

    if not non_endangerment:
        raise ApiError(
            "ERR_NON_ENDANGERMENT_NOT_DEMONSTRATED", "non-endangerment has not been demonstrated"
        )

    if any(o["status"] == "OPEN" for o in db.orders_of(project["id"])):
        raise ApiError("ERR_OPEN_REMEDIATION_ORDER", "project has an open remediation order")

    derive.refresh_pisc_elapsed(project)
    if project["pisc_elapsed_years"] < D(project["pisc_duration_years"]):
        raise ApiError(
            "ERR_PISC_DURATION_NOT_ELAPSED", "the post-injection site care period has not elapsed"
        )

    project["non_endangerment_demonstrated"] = True
    project["closure_status"] = "CERTIFIED"
    project["closure_certified_by_user_id"] = mw.caller_id()
    project["closure_certified_at"] = clock.now_iso()
    project["status"] = "CLOSED"

    for instrument in db.instruments_of(project["id"]):
        if instrument["status"] == "ALLOCATED":
            released = (
                instrument["allocated_ca_usd"]
                + instrument["allocated_plugging_usd"]
                + instrument["allocated_pisc_usd"]
                + instrument["allocated_emergency_usd"]
            )
            instrument["allocated_ca_usd"] = D("0.00")
            instrument["allocated_plugging_usd"] = D("0.00")
            instrument["allocated_pisc_usd"] = D("0.00")
            instrument["allocated_emergency_usd"] = D("0.00")
            instrument["unallocated_usd"] = calc.q2(instrument["unallocated_usd"] + released)
            instrument["status"] = "RELEASED"
            instrument["released_at"] = clock.now_iso()
            db.touch(instrument)

    derive.recompute_allocated_assurance(project, posture=False)
    db.touch(project)
    return response.object_response(serialize.project(project))


# --------------------------------------------------------------------------- #
# Project-scoped sub-resource listings
# --------------------------------------------------------------------------- #


@bp.get("/ccs/storage-projects/<project_id>/legacy-wellbores")
@mw.require(ADMIN, DEV, REVIEWER)
def list_project_wellbores(project_id):
    status = mw.query_enum("corrective_action_status", enums.CORRECTIVE_ACTION_STATUS)
    project = lookup.project(project_id)
    rows = db.wellbores_of(project["id"])
    if status is not None:
        rows = [r for r in rows if r["corrective_action_status"] == status]
    page, limit, offset, total = mw.paginate(rows)
    return response.list_response([serialize.wellbore(r) for r in page], limit, offset, total)


@bp.get("/ccs/storage-projects/<project_id>/pore-space-tracts")
@mw.require(ADMIN, DEV, REVIEWER, LANDOWNER)
def list_project_tracts(project_id):
    status = mw.query_enum("lease_status", enums.LEASE_STATUS)
    project = lookup.project(project_id)
    rows = db.tracts_of(project["id"])
    if status is not None:
        rows = [r for r in rows if r["lease_status"] == status]
    page, limit, offset, total = mw.paginate(rows)
    return response.list_response([serialize.tract(r) for r in page], limit, offset, total)


@bp.get("/ccs/storage-projects/<project_id>/monitoring-plans")
@mw.require(ADMIN, DEV, REVIEWER, VERIFIER)
def list_project_plans(project_id):
    status = mw.query_enum("status", enums.PLAN_STATUS)
    project = lookup.project(project_id)
    rows = db.plans_of(project["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = mw.paginate(rows)
    return response.list_response([serialize.plan(r) for r in page], limit, offset, total)


@bp.get("/ccs/storage-projects/<project_id>/financial-instruments")
@mw.require(ADMIN, DEV, REVIEWER)
def list_project_instruments(project_id):
    status = mw.query_enum("status", enums.INSTRUMENT_STATUS)
    project = lookup.project(project_id)
    rows = db.instruments_of(project["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = mw.paginate(rows)
    return response.list_response([serialize.instrument(r) for r in page], limit, offset, total)


@bp.get("/ccs/storage-projects/<project_id>/remediation-orders")
@mw.require(ADMIN, DEV, REVIEWER)
def list_project_orders(project_id):
    status = mw.query_enum("status", enums.REMEDIATION_STATUS)
    project = lookup.project(project_id)
    rows = db.orders_of(project["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = mw.paginate(rows)
    return response.list_response([serialize.order(r) for r in page], limit, offset, total)
