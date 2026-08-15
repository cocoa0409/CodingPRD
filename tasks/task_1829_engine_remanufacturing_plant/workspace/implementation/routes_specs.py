"""Build specifications: routes, thresholds, and supersession (PRD 3.2)."""

from flask import Blueprint, request

import clock as clockmod
import envelope
import serializers
from auth import ALL_READ_ROLES, authorized
from errors import ERR_INVALID_STATE, raise_error
from store import db, stamp_new, sorted_rows, touch
from validate import (
    check_allowed_fields,
    filter_enum,
    get_body,
    pagination,
    req_enum,
    req_enum_list,
    req_int,
    req_number,
    req_str,
    req_str_list,
)
from services import get_or_404

bp = Blueprint("build_specs", __name__)

EMISSIONS_TIERS = {"FEDERAL", "CALIFORNIA"}
SPEC_STATUSES = {"DRAFT", "ACTIVE", "RETIRED"}
REUSE_GRADES = {"REUSE_OK", "REWORK"}
OP_TYPES = {"BORE", "DECK", "CRANK_GRIND"}

# Work-order statuses that block explicit retirement of the referenced spec.
OPEN_WORK_ORDER_STATUSES = {"QUEUED", "TEARDOWN", "MACHINING", "ASSEMBLY", "DYNO_TEST"}

_CREATE_FIELDS = [
    "engine_family",
    "application_code",
    "emissions_tier",
    "list_price_cents",
    "core_deposit_cents",
    "core_base_credit_cents",
    "allowed_reuse_grades",
    "allowed_interchange_groups",
    "dyno_min_horsepower",
    "dyno_min_oil_pressure_psi",
    "dyno_max_coolant_temp_f",
    "required_op_sequence",
]


@bp.route("/build-specs", methods=["POST"])
def create_build_spec():
    authorized(["PlantAdmin"])
    body = get_body()
    check_allowed_fields(body, _CREATE_FIELDS)
    record = {
        "engine_family": req_str(body, "engine_family"),
        "application_code": req_str(body, "application_code"),
        "emissions_tier": req_enum(body, "emissions_tier", EMISSIONS_TIERS),
        "list_price_cents": req_int(body, "list_price_cents"),
        "core_deposit_cents": req_int(body, "core_deposit_cents"),
        "core_base_credit_cents": req_int(body, "core_base_credit_cents"),
        "allowed_reuse_grades": req_enum_list(body, "allowed_reuse_grades", REUSE_GRADES),
        "allowed_interchange_groups": req_str_list(body, "allowed_interchange_groups"),
        "dyno_min_horsepower": req_int(body, "dyno_min_horsepower"),
        "dyno_min_oil_pressure_psi": req_number(body, "dyno_min_oil_pressure_psi"),
        "dyno_max_coolant_temp_f": req_int(body, "dyno_max_coolant_temp_f"),
        "required_op_sequence": req_enum_list(body, "required_op_sequence", OP_TYPES),
        "status": "DRAFT",
        "activated_at": None,
        "retired_at": None,
    }
    stamp_new(record)
    db.build_specs[record["id"]] = record
    return envelope.created(serializers.build_spec(record))


@bp.route("/build-specs", methods=["GET"])
def list_build_specs():
    authorized(ALL_READ_ROLES)
    limit, offset = pagination()
    f_family = request.args.get("engine_family")
    f_application = request.args.get("application_code")
    f_tier = filter_enum("emissions_tier", EMISSIONS_TIERS)
    f_status = filter_enum("status", SPEC_STATUSES)
    rows = list(db.build_specs.values())
    if f_family is not None:
        rows = [r for r in rows if r["engine_family"] == f_family]
    if f_application is not None:
        rows = [r for r in rows if r["application_code"] == f_application]
    if f_tier is not None:
        rows = [r for r in rows if r["emissions_tier"] == f_tier]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    rows = sorted_rows(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return envelope.listing([serializers.build_spec(r) for r in page], limit, offset, total)


@bp.route("/build-specs/<rid>", methods=["GET"])
def get_build_spec(rid):
    authorized(ALL_READ_ROLES)
    record = get_or_404("build_specs", rid)
    return envelope.ok(serializers.build_spec(record))


@bp.route("/build-specs/<rid>/activate", methods=["POST"])
def activate_build_spec(rid):
    authorized(["PlantAdmin"])
    body = get_body()
    check_allowed_fields(body, [])
    record = get_or_404("build_specs", rid)
    if record["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "only a DRAFT build spec can be activated")

    now = clockmod.now()
    # SUPERSEDE: every other ACTIVE spec with the same
    # (engine_family, application_code, emissions_tier) retires in the same
    # transaction.
    for sibling in db.build_specs.values():
        if (
            sibling["id"] != record["id"]
            and sibling["status"] == "ACTIVE"
            and sibling["engine_family"] == record["engine_family"]
            and sibling["application_code"] == record["application_code"]
            and sibling["emissions_tier"] == record["emissions_tier"]
        ):
            sibling["status"] = "RETIRED"
            sibling["retired_at"] = now
            touch(sibling)

    record["status"] = "ACTIVE"
    record["activated_at"] = now
    touch(record)
    return envelope.ok(serializers.build_spec(record))


@bp.route("/build-specs/<rid>/retire", methods=["POST"])
def retire_build_spec(rid):
    authorized(["PlantAdmin"])
    body = get_body()
    check_allowed_fields(body, [])
    record = get_or_404("build_specs", rid)
    if record["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "only an ACTIVE build spec can be retired")

    for wo in db.work_orders.values():
        if wo["build_spec_id"] == record["id"] and wo["status"] in OPEN_WORK_ORDER_STATUSES:
            raise_error(
                ERR_INVALID_STATE,
                "build spec is referenced by open work order %s" % wo["id"],
            )

    record["status"] = "RETIRED"
    record["retired_at"] = clockmod.now()
    touch(record)
    return envelope.ok(serializers.build_spec(record))
