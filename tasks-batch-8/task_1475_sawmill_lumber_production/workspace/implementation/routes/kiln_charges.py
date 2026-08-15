"""KilnCharge endpoints: schedule, get, start, complete, abort."""
from flask import Blueprint

from db import DB, new_id, now_dt, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok
from services import (
    CHAMBERS,
    MOISTURE_TOLERANCE_PCT,
    SPECIES,
    chamber_conflict,
    get_charge,
    ser_charge,
    stamp,
    touch,
)
from util import (
    as_enum,
    as_iso_dt,
    as_list,
    as_num,
    body,
    dec,
    parse_dt,
    required,
)

bp = Blueprint("kiln_charges", __name__)


@bp.post("/api/kiln-charges")
def create_charge():
    auth(["KilnOperator"])
    data = body()
    chamber = as_enum(required(data, "chamber"), "chamber", CHAMBERS)
    species = as_enum(required(data, "species"), "species", SPECIES)
    package_ids = as_list(
        required(data, "package_ids"), "package_ids", non_empty=True
    )
    for i, pid in enumerate(package_ids):
        if not isinstance(pid, str):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, f"package_ids[{i}] must be a string"
            )
    if len(set(package_ids)) != len(package_ids):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "package_ids contains a duplicate"
        )
    scheduled_start = as_iso_dt(
        required(data, "scheduled_start"), "scheduled_start"
    )
    scheduled_end = as_iso_dt(required(data, "scheduled_end"), "scheduled_end")
    target_moisture_pct = as_num(
        required(data, "target_moisture_pct"), "target_moisture_pct", positive=True
    )
    start_dt = parse_dt(scheduled_start)
    end_dt = parse_dt(scheduled_end)

    # Existence of referenced packages.
    packages = []
    for pid in package_ids:
        pkg = DB["lumber_packages"].get(pid)
        if pkg is None:
            raise ApiError("ERR_NOT_FOUND", 404, f"LumberPackage {pid} not found")
        packages.append(pkg)

    # State: every package must be GREEN.
    for pkg in packages:
        if pkg["status"] != "GREEN":
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                f"LumberPackage {pkg['id']} is not GREEN",
            )

    # Temporal: start not in the past; end strictly after start.
    if start_dt < now_dt():
        raise ApiError(
            "ERR_SCHEDULE_IN_PAST",
            422,
            "scheduled_start lies before the current logical time",
        )
    if end_dt <= start_dt:
        raise ApiError(
            "ERR_END_BEFORE_START",
            422,
            "scheduled_end must be strictly after scheduled_start",
        )

    # Occupancy: chamber non-overlap with the 4h turnaround buffer.
    if chamber_conflict(chamber, start_dt, end_dt):
        raise ApiError(
            "ERR_KILN_OVERLAP",
            409,
            "Charge violates chamber non-overlap or the 4h turnaround buffer",
        )

    # Referential linkage: every package matches the charge species.
    for pkg in packages:
        if pkg["species"] != species:
            raise ApiError(
                "ERR_PRODUCT_MISMATCH",
                422,
                f"LumberPackage {pkg['id']} species does not match the charge species",
            )

    charge = {
        "id": new_id(),
        "chamber": chamber,
        "species": species,
        "package_ids": list(package_ids),
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "_scheduled_start_dt": start_dt,
        "_scheduled_end_dt": end_dt,
        "target_moisture_pct": target_moisture_pct,
        "status": "SCHEDULED",
        "actual_start": None,
        "actual_end": None,
    }
    stamp(charge)
    DB["kiln_charges"][charge["id"]] = charge
    # Charge the packages: GREEN -> IN_KILN.
    for pkg in packages:
        pkg["kiln_charge_id"] = charge["id"]
        pkg["status"] = "IN_KILN"
        touch(pkg)
    return ok(ser_charge(charge), 201)


@bp.get("/api/kiln-charges/<cid>")
def get_one_charge(cid):
    auth(ALL_ROLES)
    return ok(ser_charge(get_charge(cid)))


@bp.post("/api/kiln-charges/<cid>/start")
def start_charge(cid):
    auth(["KilnOperator"])
    charge = get_charge(cid)
    body()
    if charge["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a SCHEDULED charge can be started"
        )
    if now_dt() < charge["_scheduled_start_dt"]:
        raise ApiError(
            "ERR_SCHEDULE_IN_PAST",
            422,
            "Charge cannot be started before its scheduled_start",
        )
    charge["actual_start"] = now_iso()
    charge["status"] = "IN_PROGRESS"
    touch(charge)
    return ok(ser_charge(charge))


@bp.post("/api/kiln-charges/<cid>/complete")
def complete_charge(cid):
    auth(["KilnOperator"])
    charge = get_charge(cid)
    data = body()
    readings = as_list(required(data, "readings"), "readings", non_empty=True)
    parsed = {}
    for i, entry in enumerate(readings):
        if not isinstance(entry, dict):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, f"readings[{i}] must be an object"
            )
        pid = required(entry, "package_id")
        if not isinstance(pid, str):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, f"readings[{i}].package_id must be a string"
            )
        exit_moisture_pct = as_num(
            required(entry, "exit_moisture_pct"),
            f"readings[{i}].exit_moisture_pct",
            non_negative=True,
        )
        if "measured_dry_mbf" in entry and entry["measured_dry_mbf"] is not None:
            measured = entry["measured_dry_mbf"]
        elif "actual_dry_mbf" in entry and entry["actual_dry_mbf"] is not None:
            measured = entry["actual_dry_mbf"]
        else:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                f"readings[{i}].measured_dry_mbf: missing required field",
            )
        measured = as_num(measured, f"readings[{i}].measured_dry_mbf", positive=True)
        if pid in parsed:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                f"readings covers package {pid} more than once",
            )
        parsed[pid] = (exit_moisture_pct, measured)

    # Readings must cover exactly the charged package set — every charged id
    # present, no extras.
    charged = set(charge["package_ids"])
    given = set(parsed.keys())
    if given != charged:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "readings must cover exactly the charged package set",
        )

    # State: charge IN_PROGRESS and scheduled_end reached.
    if charge["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only an IN_PROGRESS charge can be completed"
        )
    if now_dt() < charge["_scheduled_end_dt"]:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Charge cannot be completed before its scheduled_end",
        )

    target = dec(charge["target_moisture_pct"])
    for pid, (exit_moisture_pct, measured) in parsed.items():
        pkg = DB["lumber_packages"][pid]
        pkg["exit_moisture_pct"] = exit_moisture_pct
        if dec(exit_moisture_pct) <= target + MOISTURE_TOLERANCE_PCT:
            # Moisture pass: IN_KILN -> DRY with the measured tally.
            pkg["actual_dry_mbf"] = measured
            pkg["status"] = "DRY"
        else:
            # Moisture fail: rework loop back to GREEN, tally left unset.
            pkg["actual_dry_mbf"] = None
            pkg["status"] = "GREEN"
        pkg["kiln_charge_id"] = None
        touch(pkg)

    charge["actual_end"] = now_iso()
    charge["status"] = "COMPLETED"
    touch(charge)
    return ok(ser_charge(charge))


@bp.post("/api/kiln-charges/<cid>/abort")
def abort_charge(cid):
    auth(["KilnOperator"])
    charge = get_charge(cid)
    body()
    if charge["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Only a SCHEDULED or IN_PROGRESS charge can be aborted",
        )
    for pid in charge["package_ids"]:
        pkg = DB["lumber_packages"].get(pid)
        if pkg is not None and pkg["kiln_charge_id"] == charge["id"]:
            pkg["status"] = "GREEN"
            pkg["kiln_charge_id"] = None
            touch(pkg)
    charge["actual_end"] = now_iso()
    charge["status"] = "ABORTED"
    touch(charge)
    return ok(ser_charge(charge))
