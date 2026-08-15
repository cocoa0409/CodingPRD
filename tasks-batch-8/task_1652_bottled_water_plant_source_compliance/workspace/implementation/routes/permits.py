"""Water source permits: register, list, read, suspend, reinstate, close."""
from flask import Blueprint

from db import store, new_resource, touch, by_creation
from errors import ApiError, err_invalid_state
from middleware import auth, ALL_ROLES
from response import ok_object, ok_list
from services import (
    as_date,
    as_int,
    get_body,
    get_or_404,
    permit_json,
    raise_shape,
    suspend_permit,
)

bp = Blueprint("permits", __name__)

CO = ["ComplianceOfficer"]


@bp.post("/api/plants/<plant_id>/permits")
@auth(CO)
def create_permit(plant_id):
    plant = get_or_404(store.plants, plant_id, "plant")
    body = get_body()

    # Input shape (rung 11; no intermediate business rules exist for create).
    errs = []
    permit_number = body.get("permit_number")
    if not isinstance(permit_number, str) or not permit_number:
        errs.append("permit_number is required")
    classification = body.get("source_classification")
    if classification not in ("SPRING", "WELL", "MUNICIPAL"):
        errs.append("source_classification must be SPRING, WELL, or MUNICIPAL")
    daily, ok_d = as_int(body.get("daily_cap_gallons"))
    if not ok_d or daily <= 0:
        errs.append("daily_cap_gallons must be a positive integer")
    monthly, ok_m = as_int(body.get("monthly_cap_gallons"))
    if not ok_m or (ok_d and monthly < daily):
        errs.append("monthly_cap_gallons must be no less than daily_cap_gallons")
    vf, ok_vf = as_date(body.get("valid_from"))
    if not ok_vf:
        errs.append("valid_from must be an ISO date")
    vt, ok_vt = as_date(body.get("valid_to"))
    if not ok_vt:
        errs.append("valid_to must be an ISO date")
    if ok_vf and ok_vt and vt <= vf:
        errs.append("valid_to must fall after valid_from")
    raise_shape(errs)

    permit = new_resource(
        {
            "plant_id": plant["id"],
            "permit_number": permit_number,
            "source_classification": classification,
            "daily_cap_gallons": daily,
            "monthly_cap_gallons": monthly,
            "valid_from": body.get("valid_from"),
            "valid_to": body.get("valid_to"),
            "status": "ACTIVE",
            "suspension_reason": None,
        }
    )
    permit["_valid_from"] = vf
    permit["_valid_to"] = vt
    store.permits[permit["id"]] = permit
    return ok_object(permit_json(permit), 201)


@bp.get("/api/plants/<plant_id>/permits")
@auth(ALL_ROLES)
def list_plant_permits(plant_id):
    get_or_404(store.plants, plant_id, "plant")
    items = [p for p in store.permits.values() if p["plant_id"] == plant_id]
    return ok_list([permit_json(p) for p in by_creation(items)])


@bp.get("/api/permits")
@auth(ALL_ROLES)
def list_permits():
    from flask import request

    items = list(store.permits.values())
    plant_id = request.args.get("plant_id")
    status = request.args.get("status")
    if plant_id is not None:
        items = [p for p in items if p["plant_id"] == plant_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return ok_list([permit_json(p) for p in by_creation(items)])


@bp.get("/api/permits/<permit_id>")
@auth(ALL_ROLES)
def get_permit(permit_id):
    permit = get_or_404(store.permits, permit_id, "permit")
    return ok_object(permit_json(permit))


@bp.post("/api/permits/<permit_id>/suspend")
@auth(CO)
def suspend(permit_id):
    permit = get_or_404(store.permits, permit_id, "permit")
    if permit["status"] != "ACTIVE":
        raise err_invalid_state("only an ACTIVE permit can be suspended")
    suspend_permit(permit, "MANUAL")
    return ok_object(permit_json(permit))


@bp.post("/api/permits/<permit_id>/reinstate")
@auth(CO)
def reinstate(permit_id):
    permit = get_or_404(store.permits, permit_id, "permit")
    if permit["status"] != "SUSPENDED":
        raise err_invalid_state("only a SUSPENDED permit can be reinstated")

    # Guards: no OVERDUE raw-source test; latest completed raw-source test
    # (by collected_at, tie-break created_at ASC) must be a pass, unless none.
    src_tests = [
        t
        for t in store.lab_tests.values()
        if t["test_type"] == "SOURCE_RAW" and t.get("subject_permit_id") == permit["id"]
    ]
    if any(t["status"] == "OVERDUE" for t in src_tests):
        raise ApiError(
            "ERR_REINSTATE_BLOCKED",
            "an OVERDUE source test exists for this permit",
            409,
        )
    completed = [t for t in src_tests if t["status"] in ("COMPLETED_PASS", "COMPLETED_FAIL")]
    if completed:
        # Latest by collected_at; ties broken by created_at ascending — so the
        # winner is the maximum under (collected_at, created_at, seq).
        latest = max(completed, key=lambda t: (t.get("_collected") or 0, t["created_at"], t["_seq"]))
        if latest["status"] != "COMPLETED_PASS":
            raise ApiError(
                "ERR_REINSTATE_BLOCKED",
                "the latest completed source test for this permit is a FAIL",
                409,
            )

    permit["status"] = "ACTIVE"
    permit["suspension_reason"] = None
    touch(permit)
    return ok_object(permit_json(permit))


@bp.post("/api/permits/<permit_id>/close")
@auth(CO)
def close(permit_id):
    permit = get_or_404(store.permits, permit_id, "permit")
    if permit["status"] != "EXPIRED":
        raise err_invalid_state("only an EXPIRED permit can be closed")
    permit["status"] = "CLOSED"
    touch(permit)
    return ok_object(permit_json(permit))
