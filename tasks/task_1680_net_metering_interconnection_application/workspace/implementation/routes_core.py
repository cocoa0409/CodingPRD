"""Clock, programs (incl. sweep), tariff schedules, feeders, transformers,
customers."""

import datetime

import clock as clockmod
import envelope
import serializers as ser
import services
from errors import ApiError
from flask import Blueprint
from middleware import (begin, must_exist, must_ref, opt_instant, opt_int,
                        paginate, pagination, req_enum, req_instant, req_int,
                        req_string)
from store import db, stamp_new, sorted_rows, touch

bp = Blueprint("core", __name__)

ANY_ROLE = ()

METERING_VARIANTS = ("ENERGY_BANKING", "MONETARY_CREDIT")
TRUE_UP_MODES = ("AVOIDED_COST_PAYOUT", "BANK_ROLLOVER")
SCREENING_BASES = ("COMMITTED", "INCLUDE_QUEUED")


# ---------------------------------------------------------------------------
# Clock (PRD 2.4)
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    ctx = begin("ProgramAdministrator")
    _, literal = None, None
    value = ctx.body.get("to_iso8601")
    instant = clockmod.parse_instant(value)
    if instant is None:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant.")
    clockmod.clock.set(instant, value)
    return envelope.ok({"current_utc": clockmod.clock.literal})


@bp.route("/_clock", methods=["GET"])
def get_clock():
    begin()
    return envelope.ok({"current_utc": clockmod.clock.literal})


# ---------------------------------------------------------------------------
# Programs (PRD 2.7 / 3.1)
# ---------------------------------------------------------------------------

@bp.route("/programs", methods=["POST"])
def create_program():
    ctx = begin("ProgramAdministrator")
    body = ctx.body
    name = req_string(body, "name")
    aggregate_cap_watts = req_int(body, "aggregate_cap_watts", minimum=1)
    metering_variant = req_enum(body, "metering_variant", METERING_VARIANTS)
    true_up_mode = req_enum(body, "true_up_mode", TRUE_UP_MODES)
    true_up_month = req_int(body, "true_up_month", minimum=1, maximum=12)
    screening_basis = req_enum(body, "screening_basis", SCREENING_BASES)
    bank_cap_wh = opt_int(body, "bank_cap_wh", minimum=0)
    row = stamp_new({
        "name": name,
        "program_status": "OPEN",
        "aggregate_cap_watts": aggregate_cap_watts,
        "metering_variant": metering_variant,
        "true_up_mode": true_up_mode,
        "true_up_month": true_up_month,
        "screening_basis": screening_basis,
        "bank_cap_wh": bank_cap_wh,
        "interconnected_watts": 0,
        "reserved_watts": 0,
        "queued_count": 0,
    })
    db.programs[row["id"]] = row
    return envelope.created(ser.program(row))


@bp.route("/programs", methods=["GET"])
def list_programs():
    ctx = begin()
    rows = list(db.programs.values())
    status = ctx.query.get("program_status")
    if status is not None:
        rows = [r for r in rows if r["program_status"] == status]
    rows = sorted_rows(rows)
    limit, offset = pagination(ctx.query)
    page, total = paginate(rows, limit, offset)
    return envelope.listing([ser.program(r) for r in page], limit, offset, total)


@bp.route("/programs/<program_id>", methods=["GET"])
def get_program(program_id):
    begin()
    row = must_exist(db.programs, program_id)
    return envelope.ok(ser.program(row))


@bp.route("/programs/<program_id>/suspend", methods=["POST"])
def suspend_program(program_id):
    begin("ProgramAdministrator")
    row = must_exist(db.programs, program_id)
    if row["program_status"] not in ("OPEN", "CAP_REACHED"):
        raise ApiError("ERR_INVALID_STATE")
    row["program_status"] = "SUSPENDED"
    touch(row)
    return envelope.ok(ser.program(row))


@bp.route("/programs/<program_id>/resume", methods=["POST"])
def resume_program(program_id):
    begin("ProgramAdministrator")
    row = must_exist(db.programs, program_id)
    if row["program_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE")
    row["program_status"] = "OPEN" if services.program_available(row) > 0 else "CAP_REACHED"
    touch(row)
    return envelope.ok(ser.program(row))


@bp.route("/programs/<program_id>/close", methods=["POST"])
def close_program(program_id):
    begin("ProgramAdministrator")
    row = must_exist(db.programs, program_id)
    if row["program_status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE")
    for application in services.applications_of_program(program_id):
        if application["application_status"] not in services.TERMINAL:
            raise ApiError("ERR_PROGRAM_HAS_INFLIGHT_WORK")
    row["program_status"] = "CLOSED"
    touch(row)
    return envelope.ok(ser.program(row))


@bp.route("/programs/<program_id>/sweep", methods=["POST"])
def sweep_program(program_id):
    """The expiry sweep (PRD 2.4): estimates first, then reservations, each in
    ascending application created_at; then one promotion scan; then posture."""
    begin("ProgramAdministrator")
    row = must_exist(db.programs, program_id)
    now = clockmod.now()

    apps = {a["id"]: a for a in services.applications_of_program(program_id)}

    expiring_estimates = [
        e for e in db.estimates.values()
        if e["application_id"] in apps
        and e["estimate_status"] == "ISSUED"
        and e["valid_until"] < now
    ]
    expiring_estimates.sort(
        key=lambda e: (apps[e["application_id"]]["created_at"], apps[e["application_id"]]["_seq"])
    )
    for estimate in expiring_estimates:
        application = apps[estimate["application_id"]]
        estimate["estimate_status"] = "EXPIRED"
        estimate["decided_at"] = now
        touch(estimate)
        if application["application_status"] in services.WITHDRAWABLE:
            services.withdraw_application(application, "ESTIMATE_EXPIRED", run_scan=False)

    expiring_holders = [
        a for a in services.applications_of_program(program_id)
        if a["application_status"] in services.WITHDRAWABLE
        and a["capacity_reserved_watts"] > 0
        and a["reservation_expires_at"] is not None
        and a["reservation_expires_at"] < now
    ]
    expiring_holders.sort(key=lambda a: (a["created_at"], a["_seq"]))
    for application in expiring_holders:
        services.withdraw_application(application, "RESERVATION_EXPIRED", run_scan=False)

    services.promotion_scan(row)
    services.recompute_posture(row)
    return envelope.ok(ser.program(row))


# ---------------------------------------------------------------------------
# Tariff schedules (PRD 3.1)
# ---------------------------------------------------------------------------

@bp.route("/tariff-schedules", methods=["POST"])
def create_tariff():
    ctx = begin("ProgramAdministrator")
    body = ctx.body
    program_id = req_string(body, "program_id")
    schedule_code = req_string(body, "schedule_code")
    effective_from_dt, effective_from = req_instant(body, "effective_from")
    effective_to_dt, effective_to = opt_instant(body, "effective_to")
    import_rate = req_int(body, "import_rate_millicents_per_kwh", minimum=1)
    export_rate = req_int(body, "export_rate_millicents_per_kwh", minimum=1)
    nsc_rate = req_int(body, "net_surplus_rate_millicents_per_kwh", minimum=1)
    must_ref(db.programs, program_id)
    for other in db.tariffs.values():
        if other["program_id"] != program_id:
            continue
        # Half-open windows [from, to); touching boundaries allowed.
        if effective_from_dt < (other["_to"] or datetime.datetime.max.replace(tzinfo=clockmod.UTC)) \
                and other["_from"] < (effective_to_dt or datetime.datetime.max.replace(tzinfo=clockmod.UTC)):
            raise ApiError("ERR_TARIFF_WINDOW_OVERLAP")
    row = stamp_new({
        "program_id": program_id,
        "schedule_code": schedule_code,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "_from": effective_from_dt,
        "_to": effective_to_dt,
        "import_rate_millicents_per_kwh": import_rate,
        "export_rate_millicents_per_kwh": export_rate,
        "net_surplus_rate_millicents_per_kwh": nsc_rate,
    })
    db.tariffs[row["id"]] = row
    return envelope.created(ser.tariff(row))


@bp.route("/tariff-schedules", methods=["GET"])
def list_tariffs():
    ctx = begin()
    rows = list(db.tariffs.values())
    program_id = ctx.query.get("program_id")
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    rows = sorted_rows(rows)
    limit, offset = pagination(ctx.query)
    page, total = paginate(rows, limit, offset)
    return envelope.listing([ser.tariff(r) for r in page], limit, offset, total)


@bp.route("/tariff-schedules/<tariff_schedule_id>", methods=["GET"])
def get_tariff(tariff_schedule_id):
    begin()
    row = must_exist(db.tariffs, tariff_schedule_id)
    return envelope.ok(ser.tariff(row))


# ---------------------------------------------------------------------------
# Feeders and service transformers (PRD 3.1)
# ---------------------------------------------------------------------------

@bp.route("/feeders", methods=["POST"])
def create_feeder():
    ctx = begin("ProgramAdministrator")
    body = ctx.body
    feeder_code = req_string(body, "feeder_code")
    peak_load_watts = req_int(body, "peak_load_watts", minimum=1)
    pre_existing = opt_int(body, "pre_existing_der_watts", minimum=0)
    for other in db.feeders.values():
        if other["feeder_code"] == feeder_code:
            raise ApiError("ERR_INVALID_REQUEST", "feeder_code must be unique.")
    row = stamp_new({
        "feeder_code": feeder_code,
        "peak_load_watts": peak_load_watts,
        "pre_existing_der_watts": pre_existing if pre_existing is not None else 0,
    })
    db.feeders[row["id"]] = row
    return envelope.created(ser.feeder(row))


@bp.route("/feeders", methods=["GET"])
def list_feeders():
    ctx = begin()
    rows = sorted_rows(list(db.feeders.values()))
    limit, offset = pagination(ctx.query)
    page, total = paginate(rows, limit, offset)
    return envelope.listing([ser.feeder(r) for r in page], limit, offset, total)


@bp.route("/feeders/<feeder_id>", methods=["GET"])
def get_feeder(feeder_id):
    begin()
    row = must_exist(db.feeders, feeder_id)
    return envelope.ok(ser.feeder(row))


@bp.route("/service-transformers", methods=["POST"])
def create_transformer():
    ctx = begin("ProgramAdministrator")
    body = ctx.body
    feeder_id = req_string(body, "feeder_id")
    transformer_code = req_string(body, "transformer_code")
    nameplate_watts = req_int(body, "nameplate_watts", minimum=1)
    pre_existing = opt_int(body, "pre_existing_der_watts", minimum=0)
    must_ref(db.feeders, feeder_id)
    for other in db.transformers.values():
        if other["transformer_code"] == transformer_code:
            raise ApiError("ERR_INVALID_REQUEST", "transformer_code must be unique.")
    row = stamp_new({
        "feeder_id": feeder_id,
        "transformer_code": transformer_code,
        "nameplate_watts": nameplate_watts,
        "pre_existing_der_watts": pre_existing if pre_existing is not None else 0,
    })
    db.transformers[row["id"]] = row
    return envelope.created(ser.transformer(row))


@bp.route("/service-transformers", methods=["GET"])
def list_transformers():
    ctx = begin()
    rows = list(db.transformers.values())
    feeder_id = ctx.query.get("feeder_id")
    if feeder_id is not None:
        rows = [r for r in rows if r["feeder_id"] == feeder_id]
    rows = sorted_rows(rows)
    limit, offset = pagination(ctx.query)
    page, total = paginate(rows, limit, offset)
    return envelope.listing([ser.transformer(r) for r in page], limit, offset, total)


@bp.route("/service-transformers/<service_transformer_id>", methods=["GET"])
def get_transformer(service_transformer_id):
    begin()
    row = must_exist(db.transformers, service_transformer_id)
    return envelope.ok(ser.transformer(row))


# ---------------------------------------------------------------------------
# Customers (PRD 3.2)
# ---------------------------------------------------------------------------

@bp.route("/customers", methods=["POST"])
def create_customer():
    ctx = begin("ProgramAdministrator")
    body = ctx.body
    full_name = req_string(body, "full_name")
    email = req_string(body, "email")
    row = stamp_new({"full_name": full_name, "email": email})
    db.customers[row["id"]] = row
    return envelope.created(ser.customer(row))


@bp.route("/customers", methods=["GET"])
def list_customers():
    ctx = begin()
    rows = sorted_rows(list(db.customers.values()))
    limit, offset = pagination(ctx.query)
    page, total = paginate(rows, limit, offset)
    return envelope.listing([ser.customer(r) for r in page], limit, offset, total)


@bp.route("/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    begin()
    row = must_exist(db.customers, customer_id)
    return envelope.ok(ser.customer(row))
