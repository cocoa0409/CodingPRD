"""Logical clock, taxpayer groups and member entities."""
from flask import Blueprint

from calc import registrations_of_group
from models import (find_group, find_legal_entity, ser_group, ser_legal_entity)
from store import db
from util import (fmt_dt, money, opt_bool, opt_enum, opt_int, req_dt, req_num,
                  req_state_code, req_str, ZERO)
from web import (ANY_ROLE, body_json, created, endpoint, new_record, ok, paginate,
                 sort_created)

bp = Blueprint("core", __name__)

ENTITY_TYPES = ("CORP", "LLC", "PARTNERSHIP", "DISREGARDED")


# --------------------------------------------------------------------------
# Logical compliance clock (PRD 2.5)
# --------------------------------------------------------------------------
@bp.route("/salt/_clock/set_current_utc", methods=["POST"])
@endpoint(["TaxManager"])
def set_clock():
    body = body_json()
    instant = req_dt(body, "to_iso8601")
    db.clock = instant
    return ok({"current_utc": fmt_dt(db.clock)})


# --------------------------------------------------------------------------
# TaxpayerGroup
# --------------------------------------------------------------------------
@bp.route("/salt/groups", methods=["POST"])
@endpoint(["TaxManager"])
def create_group():
    body = body_json()
    name = req_str(body, "name")
    base_state_code = req_state_code(body, "base_state_code")
    everywhere_sales = req_num(body, "everywhere_sales", minv=0)
    everywhere_property = req_num(body, "everywhere_property", minv=0)
    everywhere_payroll = req_num(body, "everywhere_payroll", minv=0)
    fiscal_year_end_month = opt_int(body, "fiscal_year_end_month", 12, minv=1, maxv=12)

    group = new_record()
    group.update({
        "name": name,
        "base_state_code": base_state_code,
        "fiscal_year_end_month": fiscal_year_end_month,
        "everywhere_sales": everywhere_sales,
        "everywhere_property": everywhere_property,
        "everywhere_payroll": everywhere_payroll,
        "open_registration_obligations": 0,
        "compliance_posture": "COMPLIANT",
        "nowhere_sales_pool": money(ZERO),
    })
    db.groups[group["id"]] = group
    return created(ser_group(group))


@bp.route("/salt/groups/<gid>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_group(gid):
    return ok(ser_group(find_group(gid)))


@bp.route("/salt/groups", methods=["GET"])
@endpoint(ANY_ROLE)
def list_groups():
    return paginate(sort_created(list(db.groups.values())), ser_group)


# --------------------------------------------------------------------------
# LegalEntity
# --------------------------------------------------------------------------
@bp.route("/salt/groups/<gid>/legal-entities", methods=["POST"])
@endpoint(["TaxManager"])
def create_legal_entity(gid):
    group = find_group(gid)
    body = body_json()
    name = req_str(body, "name")
    incorporation_state_code = req_state_code(body, "incorporation_state_code")
    entity_type = opt_enum(body, "entity_type", ENTITY_TYPES, "CORP")
    is_unitary_member = opt_bool(body, "is_unitary_member", True)

    entity = new_record()
    entity.update({
        "group_id": group["id"],
        "name": name,
        "entity_type": entity_type,
        "incorporation_state_code": incorporation_state_code,
        "is_unitary_member": is_unitary_member,
        "vda_shield_until": None,
    })
    db.legal_entities[entity["id"]] = entity
    return created(ser_legal_entity(entity))


@bp.route("/salt/legal-entities/<eid>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_legal_entity(eid):
    return ok(ser_legal_entity(find_legal_entity(eid)))


@bp.route("/salt/groups/<gid>/legal-entities", methods=["GET"])
@endpoint(ANY_ROLE)
def list_legal_entities(gid):
    group = find_group(gid)
    rows = [e for e in db.legal_entities.values() if e["group_id"] == group["id"]]
    return paginate(sort_created(rows), ser_legal_entity)
