"""PRD 3.8 - obsolescence management and inventory runout coordination."""
from flask import Blueprint, request

import calc
from cascade import complete_obsolescence, unwind_obsolescence
from core import db, fmt_dt, new_row, parse_dt, rows, touch
from errors import fail, invalid
from http_util import (
    ALL_ROLES,
    auth,
    body_fields,
    created,
    filter_exists,
    is_int,
    load,
    need_array,
    need_datetime,
    need_enum,
    need_int,
    need_nonempty,
    ok,
    paginate,
    raw_body,
)
from serialize import runout_json

bp = Blueprint("runouts", __name__)


def _record_dates(records):
    return [parse_dt(record["week_start_utc"]) for record in records]


def _rederive(runout):
    records = runout["depletion_records"]
    remaining, actual = calc.replay_depletion(
        runout["on_hand_qty"], records, _record_dates(records)
    )
    runout["remaining_qty"] = remaining
    runout["actual_runout_date"] = actual
    runout["trailing_avg_usage_qty"] = calc.trailing_avg(records)


@bp.route("/inventory-runouts", methods=["POST"])
def create_runout():
    auth(["PackagingCoordinator"])
    raw = raw_body()
    asset_ref = raw.get("artwork_asset_id")
    if isinstance(asset_ref, str) and asset_ref:
        load("assets", asset_ref)
    version_ref = raw.get("obsolete_version_id")
    if isinstance(version_ref, str) and version_ref:
        load("versions", version_ref)

    body = body_fields(
        [
            "artwork_asset_id",
            "obsolete_version_id",
            "on_hand_qty",
            "weekly_usage_qty",
            "runout_start_utc",
        ]
    )
    need_nonempty(body, "artwork_asset_id")
    need_nonempty(body, "obsolete_version_id")
    on_hand_qty = need_int(body, "on_hand_qty", 0)
    weekly_usage_qty = need_int(body, "weekly_usage_qty", 0)
    if on_hand_qty > 0 and weekly_usage_qty < calc.MIN_TRAILING_AVG_QTY:
        invalid("weekly_usage_qty must be at least 1 when on_hand_qty is greater than zero")
    start = need_datetime(body, "runout_start_utc")

    asset = load("assets", body["artwork_asset_id"])
    version = load("versions", body["obsolete_version_id"])

    if version["state"] != "OBSOLETE_PENDING":
        fail(
            "ERR_VERSION_STATE_INVALID",
            "a runout may only be opened against an OBSOLETE_PENDING version",
        )

    projected = calc.projected_runout_date(start, on_hand_qty, weekly_usage_qty)
    row = new_row(
        "runouts",
        {
            "artwork_asset_id": asset["id"],
            "obsolete_version_id": version["id"],
            "on_hand_qty": on_hand_qty,
            "weekly_usage_qty": weekly_usage_qty,
            "runout_start_utc": fmt_dt(start),
            "state": "PLANNED",
            "depletion_records": [],
            "remaining_qty": on_hand_qty,
            "trailing_avg_usage_qty": None,
            "projected_runout_date": projected,
            "actual_runout_date": None,
            "disposition": None,
            "units_scrapped": 0,
            "units_reworked": 0,
            "material_writeoff_cents": 0,
            "relabel_cost_cents": 0,
            "changeover_base_cents": 0,
            "changeover_expedite_cents": 0,
            "total_changeover_cost_cents": 0,
            "reversal_count": 0,
            "reversal_reason": None,
        },
    )

    if on_hand_qty == 0:
        # Nothing to deplete: the runout resolves inside this same request (PRD 3.8).
        row["state"] = "RUNOUT_COMPLETE"
        row["actual_runout_date"] = projected
        row["disposition"] = "RUNOUT"
        complete_obsolescence(row)

    return created(runout_json(row))


@bp.route("/inventory-runouts/<runout_id>", methods=["GET"])
def get_runout(runout_id):
    auth(ALL_ROLES)
    return ok(runout_json(load("runouts", runout_id)))


@bp.route("/inventory-runouts", methods=["GET"])
def list_runouts():
    auth(ALL_ROLES)
    asset_id = filter_exists("assets", "artwork_asset_id")
    version_id = filter_exists("versions", "obsolete_version_id")
    items = rows("runouts")
    if asset_id:
        items = [r for r in items if r["artwork_asset_id"] == asset_id]
    if version_id:
        items = [r for r in items if r["obsolete_version_id"] == version_id]
    state = request.args.get("state")
    if state:
        items = [r for r in items if r["state"] == state]
    disposition = request.args.get("disposition")
    if disposition:
        items = [r for r in items if r.get("disposition") == disposition]
    items = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    return paginate(items, runout_json)


@bp.route("/inventory-runouts/<runout_id>/depletion-records", methods=["POST"])
def append_depletion_records(runout_id):
    auth(["PackagingCoordinator"])
    runout = load("runouts", runout_id)
    body = body_fields(["records"])
    entries = need_array(body, "records", 1)
    parsed = []
    for entry in entries:
        if not isinstance(entry, dict):
            invalid("each records entry must be an object")
        for key in entry.keys():
            if key not in ("week_start_utc", "units_consumed"):
                invalid("unknown field %s in a records entry" % key)
        week_start = parse_dt(entry.get("week_start_utc"))
        if week_start is None:
            invalid("week_start_utc must be an ISO 8601 UTC datetime")
        units = entry.get("units_consumed")
        if not is_int(units) or units < 0:
            invalid("units_consumed must be an integer of zero or greater")
        parsed.append((week_start, units))

    if runout["state"] not in ("PLANNED", "MONITORING"):
        fail("ERR_RUNOUT_STATE_INVALID", "depletion records are only admissible while PLANNED or MONITORING")

    stored_dates = _record_dates(runout["depletion_records"])
    latest = max(stored_dates) if stored_dates else None
    previous = None
    for week_start, _units in parsed:
        if previous is not None and not week_start > previous:
            fail(
                "ERR_DEPLETION_RECORD_OUT_OF_ORDER",
                "week_start_utc values must be strictly ascending within the batch",
            )
        if latest is not None and not week_start > latest:
            fail(
                "ERR_DEPLETION_RECORD_OUT_OF_ORDER",
                "every submitted week_start_utc must be strictly later than every stored record",
            )
        previous = week_start

    for week_start, units in parsed:
        runout["depletion_records"].append(
            {"week_start_utc": fmt_dt(week_start), "units_consumed": units}
        )
    _rederive(runout)
    runout["state"] = "MONITORING"
    touch(runout)
    return ok(runout_json(runout))


@bp.route("/inventory-runouts/<runout_id>/disposition", methods=["POST"])
def disposition_runout(runout_id):
    auth(["PackagingCoordinator"])
    runout = load("runouts", runout_id)
    body = body_fields(["disposition"], ["units_scrapped", "units_reworked"])
    disposition = need_enum(body, "disposition", calc.DISPOSITIONS)
    units_scrapped = None
    units_reworked = None
    if disposition == "SCRAP":
        if body.get("units_scrapped") is None or body.get("units_reworked") is None:
            invalid("a SCRAP disposition requires units_scrapped and units_reworked")
        units_scrapped = need_int(body, "units_scrapped", 0)
        units_reworked = need_int(body, "units_reworked", 0)

    if runout["state"] not in ("PLANNED", "MONITORING"):
        fail("ERR_RUNOUT_STATE_INVALID", "the runout is already dispositioned")

    asset = db.assets[runout["artwork_asset_id"]]
    if disposition == "RUNOUT":
        if runout["remaining_qty"] != 0:
            fail(
                "ERR_UNIT_CONSERVATION_VIOLATION",
                "a RUNOUT disposition requires remaining_qty to be exactly 0",
            )
        runout["disposition"] = "RUNOUT"
        runout["state"] = "RUNOUT_COMPLETE"
    else:
        if units_scrapped + units_reworked != runout["remaining_qty"]:
            fail(
                "ERR_UNIT_CONSERVATION_VIOLATION",
                "units_scrapped plus units_reworked must equal remaining_qty exactly",
            )
        material, relabel, base, expedite, total = calc.changeover_cost(
            units_scrapped, units_reworked, asset["standard_unit_cost_cents"]
        )
        runout["disposition"] = "SCRAP"
        runout["units_scrapped"] = units_scrapped
        runout["units_reworked"] = units_reworked
        runout["material_writeoff_cents"] = material
        runout["relabel_cost_cents"] = relabel
        runout["changeover_base_cents"] = base
        runout["changeover_expedite_cents"] = expedite
        runout["total_changeover_cost_cents"] = total
        runout["state"] = "SCRAPPED"
        # The asset's scrapped-unit and changeover ledgers move with this disposition.
        touch(asset)

    touch(runout)
    complete_obsolescence(runout)
    return ok(runout_json(runout))


@bp.route("/inventory-runouts/<runout_id>/disposition-reversal", methods=["POST"])
def reverse_disposition(runout_id):
    auth(["PlatformAdmin"])
    runout = load("runouts", runout_id)
    body = body_fields(["reversal_reason"])
    reason = body.get("reversal_reason")
    if not isinstance(reason, str) or not reason.strip():
        invalid("reversal_reason is required and must be non-empty")

    if runout["state"] != "SCRAPPED":
        fail("ERR_RUNOUT_STATE_INVALID", "only a SCRAPPED runout may be reversed")

    # A pure compensating action: on_hand_qty and depletion_records are never rewritten.
    runout["disposition"] = None
    runout["units_scrapped"] = 0
    runout["units_reworked"] = 0
    runout["material_writeoff_cents"] = 0
    runout["relabel_cost_cents"] = 0
    runout["changeover_base_cents"] = 0
    runout["changeover_expedite_cents"] = 0
    runout["total_changeover_cost_cents"] = 0
    runout["reversal_count"] = runout["reversal_count"] + 1
    runout["reversal_reason"] = reason
    runout["state"] = "MONITORING"
    touch(runout)
    asset = db.assets.get(runout["artwork_asset_id"])
    if asset is not None:
        touch(asset)
    unwind_obsolescence(runout)
    return ok(runout_json(runout))
