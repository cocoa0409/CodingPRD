"""The tenant notice register: notice service, the right of first refusal and
the conserved relocation ledger (PRD 3.6).

The household carries three independent state dimensions on one row and they
are advanced separately; only notice service touches all three at once.
"""

from flask import Blueprint

import clock
import envelope
import serializers
import store
import validation as v
from errors import ApiError
from services import projects as project_service, tenants as tenant_service

bp = Blueprint("tenants", __name__)

SPONSOR = ["ConverterSponsor"]
READ_ROLES = ["ConverterSponsor", "StateRegulator", "PlatformAdmin"]
LIST_ROLES = ["ConverterSponsor", "StateRegulator", "PlatformAdmin",
              "TenantOccupant"]
ROFR_ROLES = ["TenantOccupant", "ConverterSponsor"]

PROTECTED_CLASSES = ["NONE", "HOUSEHOLD_WITH_MINOR", "ELDERLY", "DISABLED"]


def _require_linked_unit(household):
    """`ERR_ROFR_UNIT_NOT_LINKED`: the household must occupy an INCLUDED unit
    of its own project."""
    unit_id = household["occupied_unit_id"]
    unit = store.units.get(unit_id) if unit_id else None
    if unit is None or unit["declaration_status"] != "INCLUDED":
        raise ApiError("ERR_ROFR_UNIT_NOT_LINKED")
    if unit["conversion_project_id"] != household["conversion_project_id"]:
        raise ApiError("ERR_ROFR_UNIT_NOT_LINKED")
    return unit


@bp.post("/conversion-projects/<project_id>/tenant-households")
def register_household(project_id):
    v.authorize(SPONSOR)
    project = v.get_project(project_id)
    body = v.raw_body()
    unit = v.body_ref(body, "occupied_unit_id", v.get_unit)
    v.require_scope(project["id"], unit)
    fields = v.parse([
        v.field("household_label", "string", max_len=100),
        v.field("tenancy_start_date", "datetime"),
        v.field("monthly_rent_cents", "integer", minimum=0),
        v.field("protected_class", "enum", required=False, default="NONE",
                values=PROTECTED_CLASSES),
        v.field("occupied_unit_id", "id", required=False, default=None,
                nullable=True),
    ])
    v.require_unique(store.project_households(project["id"]),
                     household_label=fields["household_label"])
    v.gate_not_frozen(project)
    household = store.new_record(store.tenant_households, {
        "_type": "TenantHousehold",
        "conversion_project_id": project["id"],
        "occupied_unit_id": fields["occupied_unit_id"],
        "household_label": fields["household_label"],
        "tenancy_start_date": fields["tenancy_start_date"],
        "monthly_rent_cents": fields["monthly_rent_cents"],
        "protected_class": fields["protected_class"],
        "notice_status": "PRE_NOTICE",
        "rofr_status": "NOT_OFFERED",
        "relocation_status": "NOT_OWED",
        "notice_served_at": None,
        "notice_period_days": 0,
        "vacate_deadline_at": None,
        "rofr_expires_at": None,
        "relocation_assistance_cents": 0,
        "relocation_paid_cents": 0,
        "relocation_reversed_cents": 0,
    })
    project_service.sync(project)
    return envelope.object_response(serializers.dump(household), 201)


@bp.get("/conversion-projects/<project_id>/tenant-households")
def list_project_households(project_id):
    v.authorize(READ_ROLES)
    project = v.get_project(project_id)
    limit, offset = v.pagination()
    records = [
        h for h in store.project_households(project["id"])
        if v.matches(h,
                     notice_status=v.filter_value("notice_status"),
                     rofr_status=v.filter_value("rofr_status"),
                     relocation_status=v.filter_value("relocation_status"),
                     protected_class=v.filter_value("protected_class"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/tenant-households")
def list_households():
    v.authorize(LIST_ROLES)
    limit, offset = v.pagination()
    records = [
        h for h in store.ordered(store.tenant_households.values())
        if v.matches(
            h,
            conversion_project_id=v.filter_value("conversion_project_id"),
            occupied_unit_id=v.filter_value("occupied_unit_id"),
            notice_status=v.filter_value("notice_status"),
            rofr_status=v.filter_value("rofr_status"),
            relocation_status=v.filter_value("relocation_status"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/tenant-households/<household_id>")
def get_household(household_id):
    user_id, role = v.authorize(LIST_ROLES)
    # A household may read its own record and nothing belonging to another.
    v.require_identity(user_id, role, "TenantOccupant", household_id)
    household = v.get_household(household_id)
    return envelope.object_response(serializers.dump(household), 200)


@bp.patch("/tenant-households/<household_id>")
def patch_household(household_id):
    v.authorize(SPONSOR)
    household = v.get_household(household_id)
    project = v.get_project(household["conversion_project_id"])
    body = v.raw_body()
    unit = v.body_ref(body, "occupied_unit_id", v.get_unit)
    v.require_scope(project["id"], unit)
    fields = v.parse([
        v.field("monthly_rent_cents", "integer", required=False, minimum=0),
        v.field("tenancy_start_date", "datetime", required=False),
        v.field("protected_class", "enum", required=False,
                values=PROTECTED_CLASSES),
        v.field("occupied_unit_id", "id", required=False, nullable=True),
    ])
    v.gate_not_frozen(project)
    # The pre-notice facts freeze once notice has been served.
    v.require_state(household, "notice_status", ("PRE_NOTICE",))
    for name, value in fields.items():
        household[name] = value
    store.touch(household)
    return envelope.object_response(serializers.dump(household), 200)


@bp.post("/tenant-households/<household_id>/notices")
def serve_notice(household_id):
    v.authorize(SPONSOR)
    household = v.get_household(household_id)
    project = v.get_project(household["conversion_project_id"])
    v.gate_not_frozen(project)
    v.require_state(household, "notice_status", ("PRE_NOTICE",))
    package = store.project_package(project["id"])
    if package is None or package["status"] not in ("PLAT_CERTIFIED",
                                                   "RECORDED"):
        # A household cannot be noticed about an unplatted regime.
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    _require_linked_unit(household)

    served_at = clock.now()
    days = tenant_service.notice_period_days(household, served_at)
    assistance = tenant_service.relocation_assistance_cents(household)
    household["notice_status"] = "NOTICE_SERVED"
    household["notice_served_at"] = served_at
    household["notice_period_days"] = days
    household["vacate_deadline_at"] = clock.plus_days(served_at, days)
    household["rofr_expires_at"] = clock.plus_days(
        served_at, tenant_service.ROFR_WINDOW_DAYS)
    household["rofr_status"] = "OFFERED"
    household["relocation_status"] = "ACCRUED"
    household["relocation_assistance_cents"] = assistance
    store.touch(household)

    # The accrued total is monotonic; `sync` derives the other three buckets.
    project["relocation_obligation_accrued_cents"] += assistance
    store.touch(project)
    project_service.sync(project)
    project_service.recompute_posture(project)
    return envelope.object_response(serializers.dump(household), 201)


@bp.post("/tenant-households/<household_id>/rofr-responses")
def rofr_response(household_id):
    user_id, role = v.authorize(ROFR_ROLES)
    v.require_identity(user_id, role, "TenantOccupant", household_id)
    household = v.get_household(household_id)
    project = v.get_project(household["conversion_project_id"])
    body = v.parse([v.field("response", "enum", values=["EXERCISE", "WAIVE"])])
    v.gate_not_frozen(project)
    v.require_state(household, "rofr_status", ("OFFERED",))
    # The window is inclusive: the expiry instant is still inside it.
    if clock.now() > household["rofr_expires_at"]:
        raise ApiError("ERR_ROFR_WINDOW_EXPIRED")

    if body["response"] == "WAIVE":
        # The notice clock keeps running and the obligation stands.
        household["rofr_status"] = "WAIVED"
        store.touch(household)
    else:
        _require_linked_unit(household)
        household["rofr_status"] = "EXERCISED"
        if household["notice_status"] == "NOTICE_SERVED":
            household["notice_status"] = "NOTICE_WITHDRAWN"
            household["vacate_deadline_at"] = None
        if household["relocation_status"] == "ACCRUED":
            household["relocation_reversed_cents"] = (
                household["relocation_assistance_cents"])
            household["relocation_status"] = "REVERSED"
        elif household["relocation_status"] == "PAID":
            household["relocation_reversed_cents"] = (
                household["relocation_paid_cents"])
            household["relocation_paid_cents"] = 0
            household["relocation_status"] = "REVERSED"
        store.touch(household)
    project_service.sync(project)
    project_service.recompute_posture(project)
    return envelope.object_response(serializers.dump(household), 201)


@bp.post("/tenant-households/<household_id>/relocation-disbursements")
def disburse_relocation(household_id):
    v.authorize(["EscrowAgent"])
    household = v.get_household(household_id)
    project = v.get_project(household["conversion_project_id"])
    body = v.parse([v.field("amount_cents", "integer", minimum=0)])
    v.gate_not_frozen(project)
    v.require_state(household, "relocation_status", ("ACCRUED",))
    v.require_state(household, "notice_status",
                    ("NOTICE_SERVED", "VACATE_DUE"))
    if body["amount_cents"] != household["relocation_assistance_cents"]:
        raise ApiError("ERR_RELOCATION_AMOUNT_MISMATCH")
    household["relocation_status"] = "PAID"
    household["relocation_paid_cents"] = body["amount_cents"]
    store.touch(household)
    project_service.sync(project)
    project_service.recompute_posture(project)
    return envelope.object_response(serializers.dump(household), 201)


@bp.post("/tenant-households/<household_id>/occupancy-outcomes")
def occupancy_outcome(household_id):
    v.authorize(SPONSOR)
    household = v.get_household(household_id)
    project = v.get_project(household["conversion_project_id"])
    body = v.parse([v.field("outcome", "enum",
                            values=["VACATED", "HOLDOVER"])])
    v.gate_not_frozen(project)
    v.require_state(household, "notice_status", ("VACATE_DUE",))
    if body["outcome"] == "VACATED":
        # A household cannot move out while the assistance is merely accrued.
        v.require_state(household, "relocation_status", ("PAID", "REVERSED"))
    if clock.now() < household["vacate_deadline_at"]:
        raise ApiError("ERR_NOTICE_PERIOD_NOT_ELAPSED")
    household["notice_status"] = body["outcome"]
    store.touch(household)
    project_service.sync(project)
    project_service.recompute_posture(project)
    return envelope.object_response(serializers.dump(household), 201)
