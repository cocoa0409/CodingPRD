"""Rubric authoring: rubric versions and their line items."""

from flask import Blueprint

import db
import serializers
from common import touch
from errors import fail
from middleware import (
    begin,
    body,
    filter_enum,
    filter_value,
    listing,
    req_bool,
    req_dt,
    req_enum,
    req_id,
    req_int,
    req_str,
    require,
    resolve_identity,
    opt_id,
)
from response import object_response
from services import calc, cascade

bp = Blueprint("rubrics", __name__)

SECTIONS = ("FOOD_SAFETY", "BRAND_STANDARDS", "FACILITY")
RUBRIC_STATUSES = ("DRAFT", "PUBLISHED", "RETIRED")


@bp.route("/rubric-versions", methods=["POST"])
def draft_rubric_version():
    begin("BrandAdmin")
    resolve_identity()
    payload = body()
    brand_id = req_id(payload, "brand_id")
    version_label = req_str(payload, "version_label", 1, 120)
    effective_from = req_dt(payload, "effective_from")
    total_points = req_int(payload, "total_points", 1, 1000)
    supersedes_id = opt_id(payload, "supersedes_rubric_version_id")
    expected_brand_version = req_int(payload, "expected_brand_version", 0)

    brand = require("brand", brand_id)
    if supersedes_id is not None:
        require("rubric_version", supersedes_id)

    if expected_brand_version != brand["version"]:
        fail(
            "ERR_STALE_BRAND_VERSION",
            "expected_brand_version %s does not match the brand's current version %s."
            % (expected_brand_version, brand["version"]),
        )

    for existing in db.store.rubric_versions.values():
        if existing["brand_id"] == brand_id and existing["version_label"] == version_label:
            fail("ERR_DUPLICATE_RUBRIC_ENTRY", "version_label is already used in this brand.")

    record = db.new_record()
    record.update({
        "brand_id": brand_id,
        "supersedes_rubric_version_id": supersedes_id,
        "version_label": version_label,
        "effective_from": effective_from,
        "total_points": total_points,
        "status": "DRAFT",
        "published_at": None,
        "item_count": 0,
        "critical_item_count": 0,
    })
    db.store.rubric_versions[record["id"]] = record

    # A successful draft advances Brand.version by one (PRD 2.9).
    touch(brand)
    return object_response(serializers.rubric_version(record), 201)


@bp.route("/rubric-versions/<rubric_version_id>", methods=["GET"])
def read_rubric_version(rubric_version_id):
    begin("BrandAdmin", "Auditor")
    rubric_version = require("rubric_version", rubric_version_id)
    resolve_identity()
    return object_response(serializers.rubric_version(rubric_version))


@bp.route("/rubric-versions", methods=["GET"])
def list_rubric_versions():
    begin("BrandAdmin", "Auditor")
    resolve_identity()
    brand_id = filter_value("brand_id")
    supersedes_id = filter_value("supersedes_rubric_version_id")
    status = filter_enum("status", RUBRIC_STATUSES)

    records = []
    for rubric_version in db.store.rubric_versions.values():
        if brand_id is not None and rubric_version["brand_id"] != brand_id:
            continue
        if supersedes_id is not None \
                and rubric_version["supersedes_rubric_version_id"] != supersedes_id:
            continue
        if status is not None and rubric_version["status"] != status:
            continue
        records.append(rubric_version)
    return listing(records, serializers.rubric_version)


@bp.route("/rubric-versions/<rubric_version_id>/rubric-items", methods=["POST"])
def append_rubric_item(rubric_version_id):
    begin("BrandAdmin")
    rubric_version = require("rubric_version", rubric_version_id)
    resolve_identity()
    payload = body()
    item_code = req_str(payload, "item_code", 1, 60)
    section = req_enum(payload, "section", SECTIONS)
    max_points = req_int(payload, "max_points", 1, 100)
    is_critical = req_bool(payload, "is_critical", False)
    display_order = req_int(payload, "display_order", 1, 999)

    if rubric_version["status"] != "DRAFT":
        fail(
            "ERR_INVALID_RUBRIC_STATE",
            "Line items may only be appended while the rubric version is DRAFT.",
        )

    for existing in calc.rubric_items_of(rubric_version_id):
        if existing["item_code"] == item_code:
            fail("ERR_DUPLICATE_RUBRIC_ENTRY", "item_code is already used in this rubric version.")
        if existing["display_order"] == display_order:
            fail(
                "ERR_DUPLICATE_RUBRIC_ENTRY",
                "display_order is already used in this rubric version.",
            )

    record = db.new_record(light=True)
    record.update({
        "rubric_version_id": rubric_version_id,
        "item_code": item_code,
        "section": section,
        "max_points": max_points,
        "is_critical": is_critical,
        "display_order": display_order,
    })
    db.store.rubric_items[record["id"]] = record

    cascade.recompute_rubric_version_counts(rubric_version)
    touch(rubric_version)
    return object_response(serializers.rubric_item(record), 201)


@bp.route("/rubric-versions/<rubric_version_id>/rubric-items", methods=["GET"])
def list_rubric_items(rubric_version_id):
    begin("BrandAdmin", "Auditor")
    require("rubric_version", rubric_version_id)
    resolve_identity()
    section = filter_enum("section", SECTIONS)
    records = [
        item for item in calc.rubric_items_of(rubric_version_id)
        if section is None or item["section"] == section
    ]
    return listing(
        records,
        serializers.rubric_item,
        sort_key=lambda item: (item["display_order"], item["_seq"]),
    )


@bp.route("/rubric-versions/<rubric_version_id>/publish", methods=["POST"])
def publish_rubric_version(rubric_version_id):
    begin("BrandAdmin")
    rubric_version = require("rubric_version", rubric_version_id)
    resolve_identity()
    body()

    if rubric_version["status"] != "DRAFT":
        fail("ERR_INVALID_RUBRIC_STATE", "Only a DRAFT rubric version may be published.")

    items = calc.rubric_items_of(rubric_version_id)
    total = sum(item["max_points"] for item in items)
    if total != rubric_version["total_points"]:
        fail(
            "ERR_RUBRIC_TOTAL_MISMATCH",
            "Attached item points sum to %s but total_points is %s."
            % (total, rubric_version["total_points"]),
        )

    if not any(item["is_critical"] for item in items):
        fail("ERR_RUBRIC_SECTION_INCOMPLETE", "The rubric must hold at least one critical item.")
    for section in SECTIONS:
        if not any(item["section"] == section for item in items):
            fail(
                "ERR_RUBRIC_SECTION_INCOMPLETE",
                "Section %s holds no rubric item." % section,
            )

    rubric_version["status"] = "PUBLISHED"
    rubric_version["published_at"] = db.store.clock
    touch(rubric_version)

    predecessor_id = rubric_version["supersedes_rubric_version_id"]
    if predecessor_id:
        predecessor = db.store.rubric_versions.get(predecessor_id)
        if predecessor is not None and predecessor["status"] == "PUBLISHED":
            predecessor["status"] = "RETIRED"
            touch(predecessor)

    return object_response(serializers.rubric_version(rubric_version))
