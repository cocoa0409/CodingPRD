"""Permit applications: drafting, filing with lead time, and the decision fork."""
from flask import Blueprint

import calc
import serializers as S
import services
from db import store, new_record, touch, ordered, clock_date
from errors import ApiError
from guard import auth, lookup, get_body, resolve_fk, v_string, v_enum
from response import success, created, paginate

bp = Blueprint("permits", __name__)

FOUNDATION_TYPES = ("NONE", "GROUND_ANCHOR", "PIER_FOUNDATION", "ENGINEERED_SLAB")


@bp.post("/permit-applications")
def create_permit():
    auth("LeasingAgent")
    body = get_body()

    # rank 4
    lease = resolve_fk(body, "lease_id", store.leases, "ERR_LEASE_NOT_FOUND")
    jurisdiction = resolve_fk(body, "jurisdiction_id", store.jurisdictions, "ERR_JURISDICTION_NOT_FOUND")

    # rank 5
    lease_id = v_string(body, "lease_id")
    jurisdiction_id = v_string(body, "jurisdiction_id")
    foundation_type = v_enum(body, "foundation_type", FOUNDATION_TYPES)

    # rank 11 -- anchoring agreement
    if foundation_type != jurisdiction["anchoring_standard"]:
        raise ApiError("ERR_ANCHORING_STANDARD_MISMATCH",
                       "The proposed foundation is not the class this authority mandates.")

    # rank 13 -- cross-entity link agreement
    if jurisdiction_id != lease["jurisdiction_id"]:
        raise ApiError("ERR_ENTITY_LINK_MISMATCH",
                       "The application authority differs from the lease authority.")

    unit = store.units[lease["unit_id"]]
    spec = store.building_specs[unit["building_spec_id"]]
    fee = calc.permit_fee(jurisdiction["permit_fee_cents"], spec["floor_area_sqft"])

    record = new_record(
        lease_id=lease_id,
        jurisdiction_id=jurisdiction_id,
        foundation_type=foundation_type,
        status="DRAFT",
        permit_fee_cents=fee,
        submitted_on=None,
        decided_on=None,
        reviewer_note=None,
    )
    store.permits[record["id"]] = record
    return created(S.permit(record))


@bp.get("/permit-applications/<permit_id>")
def read_permit(permit_id):
    auth("LeasingAgent", "FleetAdmin")
    record = lookup(store.permits, permit_id, "ERR_PERMIT_NOT_FOUND")
    return success(S.permit(record))


@bp.get("/permit-applications")
def list_permits():
    auth("LeasingAgent", "FleetAdmin")
    records = ordered(store.permits.values())
    records = services.apply_filters(records, {
        "lease_id": "lease_id",
        "jurisdiction_id": "jurisdiction_id",
        "status": "status",
    })
    return paginate(records, S.permit)


@bp.post("/permit-applications/<permit_id>/submit")
def submit_permit(permit_id):
    auth("LeasingAgent")
    record = lookup(store.permits, permit_id, "ERR_PERMIT_NOT_FOUND")
    lease = store.leases[record["lease_id"]]

    # rank 7 -- source state
    if record["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT application may be filed.")
    if lease["occupancy_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "The lease occupancy axis has left PENDING.")

    # rank 22 -- permit lead time
    jurisdiction = store.jurisdictions[record["jurisdiction_id"]]
    start = calc.parse_iso_date(lease["start_date"])
    if calc.day_diff(start, clock_date()) < jurisdiction["permit_lead_days"]:
        raise ApiError("ERR_PERMIT_LEAD_TIME_VIOLATION",
                       "Too few whole days remain before the lease start date.")

    record["status"] = "SUBMITTED"
    record["submitted_on"] = calc.format_date(clock_date())
    touch(record)
    return success(S.permit(record))


@bp.post("/permit-applications/<permit_id>/decide")
def decide_permit(permit_id):
    auth("FleetAdmin")
    record = lookup(store.permits, permit_id, "ERR_PERMIT_NOT_FOUND")
    body = get_body()
    decision = v_enum(body, "decision", ("APPROVED", "REJECTED"))
    reviewer_note = v_string(body, "reviewer_note", required=False, allow_blank=True)

    # rank 7 -- source state
    if record["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED application may be decided.")

    record["status"] = decision
    record["decided_on"] = calc.format_date(clock_date())
    record["reviewer_note"] = reviewer_note
    touch(record)
    return success(S.permit(record))
