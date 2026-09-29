"""Price transparency file build, validation and publication (PRD 3.10)."""

from flask import Blueprint

import validate
from auth import CM, CO, PCA, RIA, SA, require
from calc import transparency_file_build
from derive import find, recompute_facility
from envelope import list_response, ok
from errors import fail
from routes_facilities import body_facility
from store import STORE, fmt_iso, serialize

bp = Blueprint("routes_transparency", __name__)

FILE_FORMATS = ("CSV", "JSON")
FILE_READERS = [SA, CO, RIA, PCA, CM]
FILE_ACTIONS = {
    "VALIDATE": ("BUILDING",),
    "PUBLISH": ("VALIDATED",),
    "FAIL": ("VALIDATED",),
}


def _thaw_items(facility):
    for item in STORE.ordered(STORE.charge_items):
        if item["facility_id"] != facility["id"]:
            continue
        if item["price_status"] != "PRICE_FROZEN":
            continue
        item["price_status"] = "PRICED_CURRENT"
        STORE.touch(item)


@bp.route("/chargemaster/transparency-files", methods=["POST"])
def create_transparency_file():
    require(CO)
    data = validate.body()
    facility = body_facility(data)
    file_format = validate.req_enum(data, "file_format", FILE_FORMATS)
    expected = validate.req_int(data, "expected_facility_version", 0)
    if expected != facility["version"]:
        fail(
            "ERR_STALE_FACILITY_VERSION",
            "expected_facility_version %s does not match the live facility version %s."
            % (expected, facility["version"]),
        )
    as_of = STORE.now
    built = transparency_file_build(facility, as_of)
    row = {
        "facility_id": facility["id"],
        "file_format": file_format,
        "as_of_datetime": fmt_iso(as_of),
        "status": "BUILDING",
        "included_item_count": built["included_item_count"],
        "total_gross_charge_cents": built["total_gross_charge_cents"],
        "payer_column_count": built["payer_column_count"],
        "content_hash": built["content_hash"],
        "validation_errors": built["validation_errors"],
        "published_at": None,
        "superseded_by_file_id": None,
        "_as_of": as_of,
    }
    STORE.stamp_new(row)
    STORE.transparency_files[row["id"]] = row
    recompute_facility(facility, bump=True)
    return ok(serialize(row), 201)


@bp.route("/chargemaster/transparency-files", methods=["GET"])
def list_transparency_files():
    require(FILE_READERS)
    facility_id = validate.query_filter("facility_id")
    superseded_by_file_id = validate.query_filter("superseded_by_file_id")
    status = validate.query_filter("status")

    def keep(row):
        if facility_id is not None and row["facility_id"] != facility_id:
            return False
        if (
            superseded_by_file_id is not None
            and row.get("superseded_by_file_id") != superseded_by_file_id
        ):
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return list_response(STORE.ordered(STORE.transparency_files, keep), serialize)


@bp.route("/chargemaster/transparency-files/<file_id>", methods=["GET"])
def read_transparency_file(file_id):
    require(FILE_READERS)
    row = find(
        STORE.transparency_files,
        file_id,
        "ERR_GOVERNANCE_RESOURCE_NOT_FOUND",
        "TransparencyFile",
    )
    return ok(serialize(row))


@bp.route("/chargemaster/transparency-files/<file_id>/lifecycle", methods=["POST"])
def transparency_file_lifecycle(file_id):
    require(CO)
    row = find(
        STORE.transparency_files,
        file_id,
        "ERR_GOVERNANCE_RESOURCE_NOT_FOUND",
        "TransparencyFile",
    )
    data = validate.body()
    action = validate.req_enum(data, "action", sorted(FILE_ACTIONS))
    validate.opt_string(data, "note")
    if row["status"] not in FILE_ACTIONS[action]:
        fail(
            "ERR_INVALID_FILE_STATE",
            "Action %s is not declared out of %s." % (action, row["status"]),
        )

    facility = STORE.facilities.get(row["facility_id"])
    if action == "PUBLISH":
        for cycle in STORE.code_update_cycles.values():
            if cycle["facility_id"] != facility["id"]:
                continue
            if cycle["status"] in ("MAPPING", "CROSSWALK_APPROVED"):
                fail(
                    "ERR_TRANSPARENCY_BLACKOUT",
                    "A code update crosswalk blackout is in force.",
                )
        if row["included_item_count"] < 1:
            fail("ERR_NO_PUBLISHABLE_ITEMS", "The file contains no publishable items.")

    if action == "VALIDATE":
        built = transparency_file_build(facility, row["_as_of"])
        row["included_item_count"] = built["included_item_count"]
        row["total_gross_charge_cents"] = built["total_gross_charge_cents"]
        row["payer_column_count"] = built["payer_column_count"]
        row["content_hash"] = built["content_hash"]
        row["validation_errors"] = built["validation_errors"]
        if built["validation_errors"]:
            row["status"] = "FAILED"
            STORE.touch(row)
        else:
            row["status"] = "VALIDATED"
            STORE.touch(row)
            for item in STORE.ordered(STORE.charge_items):
                if item["facility_id"] != facility["id"]:
                    continue
                if item["lifecycle_status"] != "ACTIVE":
                    continue
                if item["price_status"] != "PRICED_CURRENT":
                    continue
                item["price_status"] = "PRICE_FROZEN"
                STORE.touch(item)
        recompute_facility(facility, bump=True)
    elif action == "PUBLISH":
        row["status"] = "PUBLISHED"
        row["published_at"] = fmt_iso(STORE.now)
        STORE.touch(row)
        for other in STORE.ordered(STORE.transparency_files):
            if other["id"] == row["id"]:
                continue
            if other["facility_id"] != facility["id"]:
                continue
            if other["status"] != "PUBLISHED":
                continue
            other["status"] = "SUPERSEDED"
            other["superseded_by_file_id"] = row["id"]
            STORE.touch(other)
        _thaw_items(facility)
        facility["published_transparency_file_id"] = row["id"]
        facility["transparency_status"] = "CURRENT"
        recompute_facility(facility, bump=True)
    else:
        row["status"] = "FAILED"
        STORE.touch(row)
        _thaw_items(facility)
        recompute_facility(facility, bump=True)
    return ok(serialize(row))
