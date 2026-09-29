"""Shared route helpers: path/body resolution, ledger posting and list paging."""

import calc
import derive
import errors
from db import db, insert, ordered, touch
from errors import fail
from response import listing
from validate import q_pagination


# ---------------------------------------------------------------- resolution

def _need(collection, row_id, error_id):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(error_id)
    return row


def location(row_id):
    return _need(db.service_locations, row_id, errors.ERR_SERVICE_LOCATION_NOT_FOUND)


def fleet(row_id):
    return _need(db.fleet_accounts, row_id, errors.ERR_FLEET_ACCOUNT_NOT_FOUND)


def agreement(row_id):
    return _need(db.national_agreements, row_id, errors.ERR_NATIONAL_AGREEMENT_NOT_FOUND)


def policy(row_id):
    return _need(db.tire_policies, row_id, errors.ERR_TIRE_POLICY_NOT_FOUND)


def vehicle(row_id):
    return _need(db.vehicles, row_id, errors.ERR_VEHICLE_NOT_FOUND)


def casing(row_id):
    return _need(db.casings, row_id, errors.ERR_CASING_NOT_FOUND)


def tire_asset(row_id):
    return _need(db.tire_assets, row_id, errors.ERR_TIRE_ASSET_NOT_FOUND)


def tire_survey(row_id):
    return _need(db.tire_surveys, row_id, errors.ERR_TIRE_SURVEY_NOT_FOUND)


def credit_entry(row_id):
    return _need(db.casing_credit_entries, row_id, errors.ERR_CREDIT_ENTRY_NOT_FOUND)


def retread_line(row_id):
    return _need(db.retread_lines, row_id, errors.ERR_RETREAD_LINE_NOT_FOUND)


def retread_job(row_id):
    return _need(db.retread_jobs, row_id, errors.ERR_RETREAD_JOB_NOT_FOUND)


def technician(row_id):
    return _need(db.technicians, row_id, errors.ERR_TECHNICIAN_NOT_FOUND)


def road_service_call(row_id):
    return _need(db.road_service_calls, row_id, errors.ERR_ROAD_SERVICE_CALL_NOT_FOUND)


def scrap_manifest(row_id):
    return _need(db.scrap_manifests, row_id, errors.ERR_SCRAP_MANIFEST_NOT_FOUND)


def invoice(row_id):
    return _need(db.cross_location_invoices, row_id, errors.ERR_INVOICE_NOT_FOUND)


# ---------------------------------------------------------------- listing

def page(rows, serializer):
    limit, offset = q_pagination()
    total_count = len(rows)
    window = rows[offset:offset + limit]
    return listing([serializer(row) for row in window], total_count, limit, offset)


def filtered(collection, predicates):
    """Rows matching every (field, value) predicate whose value is not None."""
    rows = []
    for row in collection.values():
        keep = True
        for field, value in predicates:
            if value is None:
                continue
            if row.get(field) != value:
                keep = False
                break
        if keep:
            rows.append(row)
    return ordered(rows)


# ---------------------------------------------------------------- ledger

def post_entry(fleet_row, entry_type, amount_cents, source_entity_type, source_entity_id,
               memo, casing_id=None):
    """Append a ledger entry. The caller has already run the non-negative check."""
    return insert(
        db.casing_credit_entries,
        {
            "fleet_account_id": fleet_row["id"],
            "casing_id": casing_id,
            "entry_type": entry_type,
            "amount_cents": amount_cents,
            "source_entity_type": source_entity_type,
            "source_entity_id": source_entity_id,
            "posted_at": db.clock_raw,
            "posted_at_dt": db.clock_dt,
            "memo": memo,
        },
        versioned=False,
    )


def guard_balance(fleet_row, delta_cents):
    """Validation step 40: no posting may drive the fleet balance below zero."""
    if derive.fleet_balance_cents(fleet_row["id"]) + delta_cents < 0:
        fail(errors.ERR_CREDIT_BALANCE_NEGATIVE)


def refresh_open_invoices(fleet_row):
    """Cascade hop 5 of retread completion: OPEN invoices re-cap their credit."""
    balance = derive.fleet_balance_cents(fleet_row["id"])
    rows = [
        row for row in db.cross_location_invoices.values()
        if row["fleet_account_id"] == fleet_row["id"] and row["status"] == "OPEN"
    ]
    for row in ordered(rows):
        cap = calc.floor_int(calc.CREDIT_CAP_PCT * calc.dec(row["net_before_credit_cents"]))
        applied = min(balance, cap)
        if applied < 0:
            applied = 0
        row["credit_applied_cents"] = applied
        row["total_cents"] = row["net_before_credit_cents"] - applied
        touch(row)


def sync_vehicle_status(vehicle_row):
    """Vehicle.status is OUT_OF_SERVICE for exactly as long as a live call exists."""
    target = "OUT_OF_SERVICE" if derive.vehicle_has_live_call(vehicle_row["id"]) else "IN_SERVICE"
    if vehicle_row["status"] != target:
        vehicle_row["status"] = target
        touch(vehicle_row)
