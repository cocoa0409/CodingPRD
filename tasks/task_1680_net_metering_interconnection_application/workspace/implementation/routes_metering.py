"""Meter readings, the credit ledger, and annual reconciliations (PRD 3.9)."""

import datetime

import clock as clockmod
import envelope
import serializers as ser
import services
from errors import ApiError
from flask import Blueprint
from middleware import (begin, must_exist, must_ref, paginate, pagination,
                        req_instant, req_int, req_string)
from store import db, stamp_new, sorted_rows, touch

bp = Blueprint("metering", __name__)


# ---------------------------------------------------------------------------
# Meter readings (PRD 3.9)
# ---------------------------------------------------------------------------

@bp.route("/meter-readings", methods=["POST"])
def create_reading():
    ctx = begin("MeterTechnician")
    body = ctx.body
    service_account_id = req_string(body, "service_account_id")
    period_start_dt, period_start = req_instant(body, "period_start")
    period_end_dt, period_end = req_instant(body, "period_end")
    import_wh = req_int(body, "import_wh", minimum=0)
    export_wh = req_int(body, "export_wh", minimum=0)
    if period_end_dt <= period_start_dt:
        raise ApiError("ERR_INVALID_REQUEST", "period_end must be strictly after period_start.")
    expected_version = body.get("expected_account_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ApiError("ERR_INVALID_REQUEST", "expected_account_version must be an integer.")

    account = must_ref(db.accounts, service_account_id)

    # Rung 7: optimistic concurrency on the account version.
    if account["version"] != expected_version:
        raise ApiError("ERR_STALE_ACCOUNT_VERSION")

    # Rung 11 (structural): exact-period match supersedes; partial overlap is
    # rejected.  Only POSTED readings participate.
    superseded = None
    for other in db.readings.values():
        if other["service_account_id"] != service_account_id:
            continue
        if other["reading_status"] != "POSTED":
            continue
        exact = other["_period_start"] == period_start_dt and other["_period_end"] == period_end_dt
        if exact:
            superseded = other
            continue
        if period_start_dt < other["_period_end"] and other["_period_start"] < period_end_dt:
            raise ApiError("ERR_READING_PERIOD_OVERLAP")

    # Rung 12 (cross-entity gates), pinned order: metering, then standing,
    # then the effective tariff at period_start.
    if account["metering_status"] != "NET_METERING":
        raise ApiError("ERR_ACCOUNT_NOT_NET_METERING")
    if account["account_status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE")
    program = services.account_program(account)
    tariff = services.effective_tariff(program["id"], period_start_dt) if program else None
    if tariff is None:
        raise ApiError("ERR_NO_EFFECTIVE_TARIFF")

    if superseded is not None:
        superseded["reading_status"] = "SUPERSEDED"
        touch(superseded)
        services.reverse_reading_entries(superseded)

    row = stamp_new({
        "service_account_id": service_account_id,
        "period_start": period_start,
        "period_end": period_end,
        "_period_start": period_start_dt,
        "_period_end": period_end_dt,
        "import_wh": import_wh,
        "export_wh": export_wh,
        "reading_status": "POSTED",
        "tariff_id": tariff["id"],
        "bill_cents": 0,
        "credit_applied_cents": 0,
        "bank_drawn_wh": 0,
        "bank_deposited_wh": 0,
    })
    db.readings[row["id"]] = row
    services.apply_monthly_netting(row, account, program, tariff)

    # The first POSTED reading flips the account's PTO_GRANTED application to
    # OPERATING (PRD 3.8).
    for application in services.applications_of_account(service_account_id):
        if application["application_status"] == "PTO_GRANTED":
            application["application_status"] = "OPERATING"
            touch(application)

    touch(account)  # the single OCC version increment for the create
    return envelope.created(ser.meter_reading(row))


@bp.route("/meter-readings", methods=["GET"])
def list_readings():
    ctx = begin()
    rows = list(db.readings.values())
    service_account_id = ctx.query.get("service_account_id")
    if service_account_id is not None:
        rows = [r for r in rows if r["service_account_id"] == service_account_id]
    reading_status = ctx.query.get("reading_status")
    if reading_status is not None:
        rows = [r for r in rows if r["reading_status"] == reading_status]
    tariff_id = ctx.query.get("tariff_id")
    if tariff_id is not None:
        rows = [r for r in rows if r["tariff_id"] == tariff_id]
    rows = sorted_rows(rows)
    limit, offset = pagination(ctx.query)
    page, total = paginate(rows, limit, offset)
    return envelope.listing([ser.meter_reading(r) for r in page], limit, offset, total)


@bp.route("/meter-readings/<meter_reading_id>", methods=["GET"])
def get_reading(meter_reading_id):
    begin()
    row = must_exist(db.readings, meter_reading_id)
    return envelope.ok(ser.meter_reading(row))


@bp.route("/meter-readings/<meter_reading_id>/void", methods=["POST"])
def void_reading(meter_reading_id):
    ctx = begin("MeterTechnician")
    row = must_exist(db.readings, meter_reading_id)
    req_string(ctx.body, "reason")
    if row["reading_status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATE")
    row["reading_status"] = "VOIDED"
    touch(row)
    services.reverse_reading_entries(row)
    account = db.accounts.get(row["service_account_id"])
    if account is not None:
        touch(account)
    return envelope.ok(ser.meter_reading(row))


# ---------------------------------------------------------------------------
# Credit ledger (PRD 2.8)
# ---------------------------------------------------------------------------

@bp.route("/ledger-entries", methods=["GET"])
def list_ledger_entries():
    ctx = begin()
    rows = list(db.ledger.values())
    service_account_id = ctx.query.get("service_account_id")
    if service_account_id is not None:
        rows = [r for r in rows if r["service_account_id"] == service_account_id]
    meter_reading_id = ctx.query.get("meter_reading_id")
    if meter_reading_id is not None:
        rows = [r for r in rows if r["meter_reading_id"] == meter_reading_id]
    annual_reconciliation_id = ctx.query.get("annual_reconciliation_id")
    if annual_reconciliation_id is not None:
        rows = [r for r in rows if r["annual_reconciliation_id"] == annual_reconciliation_id]
    entry_type = ctx.query.get("entry_type")
    if entry_type is not None:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    rows = sorted_rows(rows)
    limit, offset = pagination(ctx.query)
    page, total = paginate(rows, limit, offset)
    return envelope.listing([ser.ledger_entry(r) for r in page], limit, offset, total)


@bp.route("/ledger-entries/<ledger_entry_id>", methods=["GET"])
def get_ledger_entry(ledger_entry_id):
    begin()
    row = must_exist(db.ledger, ledger_entry_id)
    return envelope.ok(ser.ledger_entry(row))


# ---------------------------------------------------------------------------
# Annual reconciliations (PRD 3.9)
# ---------------------------------------------------------------------------

@bp.route("/annual-reconciliations", methods=["POST"])
def create_reconciliation():
    ctx = begin("ProgramAdministrator")
    body = ctx.body
    service_account_id = req_string(body, "service_account_id")
    reconciliation_year = req_int(body, "reconciliation_year")
    account = must_ref(db.accounts, service_account_id)

    program = services.account_program(account)
    window_start = window_end = None
    if program is not None:
        try:
            window_start = datetime.datetime(
                reconciliation_year, program["true_up_month"], 1, tzinfo=clockmod.UTC
            )
            window_end = datetime.datetime(
                reconciliation_year + 1, program["true_up_month"], 1, tzinfo=clockmod.UTC
            )
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "reconciliation_year is out of range.")

    # Rung 10 (temporal): the run window is [window_end, window_end + 60 days).
    if window_end is not None:
        now = clockmod.now()
        if not (window_end <= now < window_end + datetime.timedelta(days=services.TRUE_UP_RUN_WINDOW_DAYS)):
            raise ApiError("ERR_TRUE_UP_WINDOW_NOT_OPEN")

    # Rung 11 (structural): at most one non-void reconciliation per (account, year).
    for other in db.reconciliations.values():
        if (
            other["service_account_id"] == service_account_id
            and other["reconciliation_year"] == reconciliation_year
            and other["reconciliation_status"] in ("COMPUTED", "SETTLED")
        ):
            raise ApiError("ERR_DUPLICATE_TRUE_UP")

    # Rung 12 (cross-entity): net-metered account, effective tariff at now.
    if account["metering_status"] != "NET_METERING":
        raise ApiError("ERR_ACCOUNT_NOT_NET_METERING")
    tariff = services.effective_tariff(program["id"], clockmod.now())
    if tariff is None:
        raise ApiError("ERR_NO_EFFECTIVE_TARIFF")

    surplus_wh = 0
    for reading in db.readings.values():
        if reading["service_account_id"] != service_account_id:
            continue
        if reading["reading_status"] != "POSTED":
            continue
        if window_start <= reading["_period_start"] < window_end:
            surplus_wh += max(0, reading["export_wh"] - reading["import_wh"])

    credit_balance_cents, banked_wh = services.account_balances(service_account_id)
    nsc_cents = services.round_half_up_milli(
        surplus_wh * tariff["net_surplus_rate_millicents_per_kwh"]
    )
    if program["true_up_mode"] == "AVOIDED_COST_PAYOUT":
        payout_cents = min(credit_balance_cents, nsc_cents)
        forfeited_cents = credit_balance_cents - payout_cents
        forfeited_wh = 0
    else:  # BANK_ROLLOVER
        payout_cents = 0
        forfeited_cents = 0
        bank_cap = program["bank_cap_wh"]
        forfeited_wh = max(0, banked_wh - bank_cap) if bank_cap is not None else 0

    row = stamp_new({
        "service_account_id": service_account_id,
        "reconciliation_year": reconciliation_year,
        "reconciliation_status": "COMPUTED",
        "window_start": window_start,
        "window_end": window_end,
        "surplus_wh": surplus_wh,
        "credit_balance_at_compute_cents": credit_balance_cents,
        "nsc_cents": nsc_cents,
        "payout_cents": payout_cents,
        "forfeited_cents": forfeited_cents,
        "forfeited_wh": forfeited_wh,
        "tariff_id": tariff["id"],
    })
    db.reconciliations[row["id"]] = row
    return envelope.created(ser.annual_reconciliation(row))


@bp.route("/annual-reconciliations", methods=["GET"])
def list_reconciliations():
    ctx = begin()
    rows = list(db.reconciliations.values())
    service_account_id = ctx.query.get("service_account_id")
    if service_account_id is not None:
        rows = [r for r in rows if r["service_account_id"] == service_account_id]
    reconciliation_status = ctx.query.get("reconciliation_status")
    if reconciliation_status is not None:
        rows = [r for r in rows if r["reconciliation_status"] == reconciliation_status]
    tariff_id = ctx.query.get("tariff_id")
    if tariff_id is not None:
        rows = [r for r in rows if r["tariff_id"] == tariff_id]
    rows = sorted_rows(rows)
    limit, offset = pagination(ctx.query)
    page, total = paginate(rows, limit, offset)
    return envelope.listing([ser.annual_reconciliation(r) for r in page], limit, offset, total)


@bp.route("/annual-reconciliations/<annual_reconciliation_id>", methods=["GET"])
def get_reconciliation(annual_reconciliation_id):
    begin()
    row = must_exist(db.reconciliations, annual_reconciliation_id)
    return envelope.ok(ser.annual_reconciliation(row))


@bp.route("/annual-reconciliations/<annual_reconciliation_id>/finalize", methods=["POST"])
def finalize_reconciliation(annual_reconciliation_id):
    begin("ProgramAdministrator")
    row = must_exist(db.reconciliations, annual_reconciliation_id)
    if row["reconciliation_status"] != "COMPUTED":
        raise ApiError("ERR_INVALID_STATE")
    account = db.accounts.get(row["service_account_id"])
    program = services.account_program(account) if account else None
    if program is not None and program["true_up_mode"] == "AVOIDED_COST_PAYOUT":
        if row["payout_cents"] > 0:
            services.post_ledger_entry(
                row["service_account_id"], "TRUE_UP_PAYOUT",
                -row["payout_cents"], 0,
                annual_reconciliation_id=row["id"],
            )
        if row["forfeited_cents"] > 0:
            services.post_ledger_entry(
                row["service_account_id"], "TRUE_UP_FORFEIT",
                -row["forfeited_cents"], 0,
                annual_reconciliation_id=row["id"],
            )
    else:
        if row["forfeited_wh"] > 0:
            services.post_ledger_entry(
                row["service_account_id"], "BANK_FORFEIT",
                0, -row["forfeited_wh"],
                annual_reconciliation_id=row["id"],
            )
    row["reconciliation_status"] = "SETTLED"
    touch(row)
    if account is not None:
        touch(account)
    return envelope.ok(ser.annual_reconciliation(row))


@bp.route("/annual-reconciliations/<annual_reconciliation_id>/void", methods=["POST"])
def void_reconciliation(annual_reconciliation_id):
    begin("ProgramAdministrator")
    row = must_exist(db.reconciliations, annual_reconciliation_id)
    if row["reconciliation_status"] != "COMPUTED":
        raise ApiError("ERR_INVALID_STATE")
    row["reconciliation_status"] = "VOIDED"
    touch(row)
    return envelope.ok(ser.annual_reconciliation(row))
