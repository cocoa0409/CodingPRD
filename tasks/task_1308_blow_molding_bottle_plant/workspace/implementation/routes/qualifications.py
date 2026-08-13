from flask import Blueprint

from auth import authenticate, require_role
from db import store
from envelope import success_object
from errors import raise_err, ERR_QUALIFICATION_RUN_NOT_FOUND, \
    ERR_BOTTLE_SPEC_NOT_FOUND, ERR_INVALID_STATE, ERR_ALREADY_TERMINAL, \
    ERR_STALE_VERSION, ERR_ACTIVE_QUALIFICATION_EXISTS, \
    ERR_CROSS_CUSTOMER_ACCESS, ERR_WEIGHT_OUT_OF_TOLERANCE
from services import stamp_new, touch, ser_qualification_run
from util import new_id
from validate import get_body, check_fields
from routes.specs import get_spec_or_404

bp = Blueprint("qualification_runs", __name__)

READ_ROLES = ["PlantAdmin", "ProcessEngineer", "QualityTechnician",
              "CustomerQualityRep"]
DECISIONS = {"APPROVE", "REJECT", "REQUEST_MORE_DATA"}
ACTIVE_RUN_STATES = ("PLANNED", "EXECUTED", "CUSTOMER_REVIEW")


def get_run_or_404(run_id):
    run = store.qualification_runs.get(run_id)
    if run is None:
        raise_err(ERR_QUALIFICATION_RUN_NOT_FOUND,
                  "QualificationRun id does not resolve")
    return run


def weight_within_tolerance(spec, measured_mean_weight_g):
    target = spec["target_weight_g"]
    band = target * spec["weight_tolerance_pct"] / 100
    return abs(measured_mean_weight_g - target) <= band


@bp.post("/qualification-runs")
def create_run():
    _, role = authenticate()
    require_role(role, ["ProcessEngineer"])
    body = check_fields(get_body(), {
        "bottle_spec_id": ("str", True),
        "sample_cavity_count": ("int", True),
        "expected_bottle_spec_version": ("int", True),
    })
    spec = store.bottle_specs.get(body["bottle_spec_id"])
    if spec is None:
        raise_err(ERR_BOTTLE_SPEC_NOT_FOUND, "BottleSpec id does not resolve")
    # OCC precedes all other state rules
    if body["expected_bottle_spec_version"] != spec["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_bottle_spec_version does not equal the spec's version")
    if spec["status"] == "RETIRED":
        raise_err(ERR_ALREADY_TERMINAL, "RETIRED spec cannot be qualified")
    if spec["status"] != "IN_QUALIFICATION":
        raise_err(ERR_INVALID_STATE,
                  "Qualification runs require a spec in IN_QUALIFICATION")
    for r in store.qualification_runs.values():
        if (r["bottle_spec_id"] == spec["id"]
                and r["status"] in ACTIVE_RUN_STATES):
            raise_err(ERR_ACTIVE_QUALIFICATION_EXISTS,
                      "Another qualification run for the spec is still active")
    round_no = sum(1 for r in store.qualification_runs.values()
                   if r["bottle_spec_id"] == spec["id"]) + 1
    run = {
        "bottle_spec_id": spec["id"],
        "round_no": round_no,
        "spec_revision_pinned": spec["content_revision"],
        "sample_cavity_count": body["sample_cavity_count"],
        "measured_mean_weight_g": None,
        "weight_spread_g": None,
        "visual_defects": None,
        "weight_within_tolerance": None,
        "review_note": None,
        "status": "PLANNED",
    }
    stamp_new(run, new_id())
    store.qualification_runs[run["id"]] = run
    touch(spec)  # run creation bumps the spec's version
    return success_object(ser_qualification_run(run), 201)


@bp.get("/qualification-runs/<rid>")
def get_run(rid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    return success_object(ser_qualification_run(get_run_or_404(rid)))


@bp.post("/qualification-runs/<rid>/execute")
def execute_run(rid):
    _, role = authenticate()
    require_role(role, ["ProcessEngineer"])
    body = check_fields(get_body(), {
        "measured_mean_weight_g": ("number", True),
        "weight_spread_g": ("number", True),
        "visual_defects": ("int", True),
    })
    run = get_run_or_404(rid)
    if run["status"] in ("APPROVED", "REJECTED"):
        raise_err(ERR_ALREADY_TERMINAL, "Run is in a terminal state")
    if run["status"] not in ("PLANNED", "EXECUTED"):
        raise_err(ERR_INVALID_STATE,
                  "Only PLANNED or EXECUTED runs can be executed")
    spec = store.bottle_specs.get(run["bottle_spec_id"])
    run["measured_mean_weight_g"] = body["measured_mean_weight_g"]
    run["weight_spread_g"] = body["weight_spread_g"]
    run["visual_defects"] = body["visual_defects"]
    # recomputed against the spec's CURRENT target/tolerance
    run["weight_within_tolerance"] = weight_within_tolerance(
        spec, body["measured_mean_weight_g"])
    run["status"] = "EXECUTED"
    touch(run)
    return success_object(ser_qualification_run(run))


@bp.post("/qualification-runs/<rid>/submit-review")
def submit_review(rid):
    _, role = authenticate()
    require_role(role, ["QualityTechnician"])
    check_fields(get_body(), {})
    run = get_run_or_404(rid)
    if run["status"] in ("APPROVED", "REJECTED"):
        raise_err(ERR_ALREADY_TERMINAL, "Run is in a terminal state")
    if run["status"] != "EXECUTED":
        raise_err(ERR_INVALID_STATE,
                  "Only an EXECUTED run can be submitted for review")
    run["status"] = "CUSTOMER_REVIEW"
    touch(run)
    return success_object(ser_qualification_run(run))


@bp.post("/qualification-runs/<rid>/review")
def review_run(rid):
    user_id, role = authenticate()
    require_role(role, ["CustomerQualityRep"])
    body = check_fields(get_body(), {
        "decision": ("enum", True, DECISIONS),
        "review_note": ("str", False),
    })
    run = get_run_or_404(rid)
    spec = store.bottle_specs.get(run["bottle_spec_id"])
    # customer ownership: CustomerQualityRep acts on its own customer only
    if spec is None or spec["customer_id"] != user_id:
        raise_err(ERR_CROSS_CUSTOMER_ACCESS,
                  "CustomerQualityRep may review only its own customer's runs")
    if run["status"] in ("APPROVED", "REJECTED"):
        raise_err(ERR_ALREADY_TERMINAL, "Run is in a terminal state")
    if run["status"] != "CUSTOMER_REVIEW":
        raise_err(ERR_INVALID_STATE,
                  "Only a run in CUSTOMER_REVIEW can be reviewed")
    if "review_note" in body:
        run["review_note"] = body["review_note"]
    decision = body["decision"]
    if decision == "REQUEST_MORE_DATA":
        run["status"] = "EXECUTED"
        touch(run)
        return success_object(ser_qualification_run(run))
    if decision == "APPROVE":
        # revision drift makes the approval transition undefined (state
        # rule, ahead of the weight gate)
        if run["spec_revision_pinned"] != spec["content_revision"]:
            raise_err(ERR_INVALID_STATE,
                      "Spec content revision has drifted since the run pinned it")
        if not run["weight_within_tolerance"]:
            raise_err(ERR_WEIGHT_OUT_OF_TOLERANCE,
                      "Measured mean weight is outside the tolerance band")
        run["status"] = "APPROVED"
        touch(run)
        spec["status"] = "QUALIFIED"
        spec["qualified_revision"] = run["spec_revision_pinned"]
        touch(spec)
        return success_object(ser_qualification_run(run))
    # REJECT
    run["status"] = "REJECTED"
    touch(run)
    spec["status"] = "REVISION_REQUESTED"
    spec["rejected_revision"] = spec["content_revision"]
    touch(spec)
    return success_object(ser_qualification_run(run))
