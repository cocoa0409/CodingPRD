"""StandardChargeRecord: extraction into an OPEN cycle, read, filtered list,
and the DRAFT -> VALIDATED transition (PRD 3.3)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CASH_EXCEEDS_GROSS,
    ERR_CHARGE_RECORD_NOT_FOUND,
    ERR_CROSS_FACILITY_REFERENCE,
    ERR_CYCLE_NOT_FOUND,
    ERR_CYCLE_NOT_OPEN,
    ERR_FACILITY_NOT_FOUND,
    ERR_ITEM_RETIRED,
    ERR_NO_NEGOTIATED_RATES,
    ERR_RECORD_NOT_DRAFT,
    ERR_SERVICE_ITEM_NOT_FOUND,
    ERR_SUPERSEDE_TARGET_INVALID,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.core import recompute_record
from util import (
    apply_filters,
    get_json_body,
    optional_string,
    paginate,
    parse_pagination,
    require_int,
    require_string,
    sort_created,
)

bp = Blueprint("records", __name__)


def get_record_or_404(rid: str) -> dict:
    rec = db.standard_charge_records.get(rid)
    if rec is None:
        raise_err(ERR_CHARGE_RECORD_NOT_FOUND, "Standard charge record not found")
    return rec


@bp.post("/transparency/standard-charge-records")
@require_roles("TransparencyOfficer")
def create_record(_user_id: str, _role: str):
    body = get_json_body()
    facility_id = require_string(body, "facility_id")
    cycle_id = require_string(body, "publication_cycle_id")
    item_id = require_string(body, "service_item_id")
    cash = require_int(body, "discounted_cash_cents", minimum=0)
    supersedes_id = optional_string(body, "supersedes_id")

    # Existence (P3), body field order: facility, cycle, item.
    if facility_id not in db.facilities:
        raise_err(ERR_FACILITY_NOT_FOUND, "Facility not found")
    cycle = db.publication_cycles.get(cycle_id)
    if cycle is None:
        raise_err(ERR_CYCLE_NOT_FOUND, "Publication cycle not found")
    item = db.service_items.get(item_id)
    if item is None:
        raise_err(ERR_SERVICE_ITEM_NOT_FOUND, "Service item not found")

    # State (P4): cycle OPEN, then item ACTIVE.
    if cycle["status"] != "OPEN":
        raise_err(ERR_CYCLE_NOT_OPEN, "Records may only be extracted into an OPEN cycle")
    if item["status"] != "ACTIVE":
        raise_err(ERR_ITEM_RETIRED, "Cannot extract a record for a RETIRED service item")

    # Referential (P7): the three references must agree on the facility.
    if cycle["facility_id"] != facility_id or item["facility_id"] != facility_id:
        raise_err(ERR_CROSS_FACILITY_REFERENCE, "facility_id disagrees with the cycle's or item's facility")

    # Supersede target: must exist, same facility, PUBLISHED or FLAGGED.
    if supersedes_id is not None:
        target = db.standard_charge_records.get(supersedes_id)
        if (
            target is None
            or target["facility_id"] != facility_id
            or target["status"] not in ("PUBLISHED", "FLAGGED")
        ):
            raise_err(ERR_SUPERSEDE_TARGET_INVALID, "supersedes_id must reference a PUBLISHED or FLAGGED record of the same facility")

    # Fiscal (P9): discounted cash may never exceed the gross snapshot.
    gross_snapshot = item["gross_charge_cents"]
    if cash > gross_snapshot:
        raise_err(ERR_CASH_EXCEEDS_GROSS, "discounted_cash_cents exceeds gross_charge_cents")

    rec = db.stamp_new({
        "facility_id": facility_id,
        "publication_cycle_id": cycle_id,
        "service_item_id": item_id,
        "supersedes_id": supersedes_id,
        "gross_charge_cents": gross_snapshot,
        "discounted_cash_cents": cash,
        "min_negotiated_cents": None,
        "max_negotiated_cents": None,
        "derived_disclosure_cents": None,
        "derivation_method": "NONE",
        "status": "DRAFT",
    })
    recompute_record(rec)
    db.standard_charge_records[rec["id"]] = rec
    # Creating the record is a mutation of the cycle's child set (PRD 3.3).
    db.bump(cycle)
    return success_object(db.public(rec), 201)


@bp.get("/transparency/standard-charge-records/<rid>")
@require_roles(*ALL_ROLES)
def get_record(rid: str, _user_id: str, _role: str):
    return success_object(db.public(get_record_or_404(rid)), 200)


@bp.get("/transparency/standard-charge-records")
@require_roles(*ALL_ROLES)
def list_records(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = list(db.standard_charge_records.values())
    items = apply_filters(items, ["facility_id", "publication_cycle_id", "service_item_id", "supersedes_id", "status"])
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([db.public(r) for r in page], limit, offset, total)


@bp.post("/transparency/standard-charge-records/<rid>/validate")
@require_roles("TransparencyOfficer")
def validate_record(rid: str, _user_id: str, _role: str):
    rec = get_record_or_404(rid)

    # State (P4), PRD order: record DRAFT, cycle OPEN, item ACTIVE.
    if rec["status"] != "DRAFT":
        raise_err(ERR_RECORD_NOT_DRAFT, "Only a DRAFT record can be validated")
    cycle = db.publication_cycles.get(rec["publication_cycle_id"])
    if cycle is None or cycle["status"] != "OPEN":
        raise_err(ERR_CYCLE_NOT_OPEN, "The owning cycle is no longer OPEN")
    item = db.service_items.get(rec["service_item_id"])
    if item is None or item["status"] != "ACTIVE":
        raise_err(ERR_ITEM_RETIRED, "The record's service item is RETIRED")

    # Refresh derived figures against live rate state before the fiscal gates.
    recompute_record(rec)

    # Fiscal (P9), PRD order: rates must exist, then cash <= gross.
    if rec["min_negotiated_cents"] is None:
        raise_err(ERR_NO_NEGOTIATED_RATES, "No includible ACTIVE negotiated rate exists for this record")
    if rec["discounted_cash_cents"] > rec["gross_charge_cents"]:
        raise_err(ERR_CASH_EXCEEDS_GROSS, "discounted_cash_cents exceeds gross_charge_cents")

    rec["status"] = "VALIDATED"
    db.bump(rec)
    db.bump(cycle)
    return success_object(db.public(rec), 200)
