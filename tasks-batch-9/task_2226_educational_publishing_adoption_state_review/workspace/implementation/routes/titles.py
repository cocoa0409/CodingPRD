"""Title, inventory, revision-plan and AncillaryBundle endpoints (PRD 3.2)."""

import domain
import serializers as S
import validation as V
from db import apply_changes, base_record, db
from errors import fail
from middleware import authorize
from response import respond, respond_list

from flask import Blueprint

bp = Blueprint("titles", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "PublisherEditor",
    "EditorialDirector",
    "PricingManager",
    "SalesRep",
    "StateAdoptionOfficer",
    "ReviewCommitteeMember",
)

BUNDLE_LIST_ROLES = (
    "PlatformAdmin",
    "PricingManager",
    "PublisherEditor",
    "StateAdoptionOfficer",
    "SalesRep",
)

ADJUSTMENT_TYPES = ("RECEIPT", "WRITE_OFF")
REVISION_ACTIONS = ("PLAN", "CANCEL_PLAN", "SUNSET")


@bp.post("/titles")
def create_title():
    authorize(("PlatformAdmin", "PublisherEditor"))
    payload = V.body()

    isbn_base = V.get_str(payload, "isbn_base", exact_len=13)
    subject = V.get_enum(payload, "subject", V.SUBJECTS)
    grade_low = V.get_int(payload, "grade_low", minimum=0, maximum=12)
    grade_high = V.get_int(payload, "grade_high", minimum=0, maximum=12)
    if grade_low > grade_high:
        fail("ERR_INVALID_REQUEST", "grade_low must not exceed grade_high.")
    edition_number = V.get_int(
        payload, "edition_number", minimum=1, required=False, default=1
    )
    copyright_year = V.get_int(
        payload, "copyright_year", minimum=2015, maximum=2100
    )
    content_tags = V.get_code_array(payload, "content_tags", 40)
    page_count = V.get_int(payload, "page_count", minimum=1)
    signature_page_capacity = V.get_int(
        payload, "signature_page_capacity", minimum=1
    )
    if signature_page_capacity < page_count:
        fail(
            "ERR_INVALID_REQUEST",
            "signature_page_capacity must be at least page_count.",
        )
    list_price_cents = V.get_int(payload, "list_price_cents", minimum=1)

    for existing in db.titles.values():
        if existing["isbn_base"] == isbn_base:
            fail(
                "ERR_DUPLICATE_RESOURCE",
                "ISBN base %s is already registered." % isbn_base,
            )

    record = base_record()
    record.update(
        {
            "isbn_base": isbn_base,
            "subject": subject,
            "grade_low": grade_low,
            "grade_high": grade_high,
            "edition_number": edition_number,
            "copyright_year": copyright_year,
            "content_tags": content_tags,
            "page_count": page_count,
            "signature_page_capacity": signature_page_capacity,
            "page_budget_remaining": signature_page_capacity - page_count,
            "content_revision": 1,
            "list_price_cents": list_price_cents,
            "status": "DRAFT",
            "revision_target_cycle_year": None,
            "adopted_state_codes": [],
            "total_received_units": 0,
            "on_hand_units": 0,
            "committed_units": 0,
            "sample_reserved_units": 0,
            "fulfilled_units": 0,
            "written_off_units": 0,
        }
    )
    db.titles[record["id"]] = record
    return respond(S.serialize(record, S.TITLE_FIELDS), 201)


@bp.get("/titles/<title_id>")
def get_title(title_id):
    authorize(READ_ROLES)
    record = domain.find_title(title_id)
    return respond(S.serialize(record, S.TITLE_FIELDS))


@bp.post("/titles/<title_id>/release")
def release_title(title_id):
    authorize(("PublisherEditor",))
    payload = V.body()
    V.get_str(payload, "note", min_len=1, max_len=500, required=False, default=None)

    title = domain.find_title(title_id)
    if title["status"] != "DRAFT":
        fail("ERR_TITLE_STATE_INVALID", "Only a DRAFT edition may be released.")
    if not title["content_tags"]:
        fail(
            "ERR_TITLE_NOT_RELEASABLE",
            "A released edition must carry at least one content tag.",
        )
    if title["page_count"] > title["signature_page_capacity"]:
        fail(
            "ERR_PAGE_BUDGET_EXCEEDED",
            "page_count exceeds the signature page capacity.",
        )

    apply_changes(title, {"status": "ACTIVE"})
    return respond(S.serialize(title, S.TITLE_FIELDS))


@bp.post("/titles/<title_id>/inventory-adjustments")
def adjust_inventory(title_id):
    authorize(("PlatformAdmin", "EditorialDirector"))
    payload = V.body()

    adjustment_type = V.get_enum(payload, "adjustment_type", ADJUSTMENT_TYPES)
    units = V.get_int(payload, "units", minimum=1)
    V.get_str(payload, "reason", min_len=1, max_len=500, required=False, default=None)

    title = domain.find_title(title_id)

    if adjustment_type == "RECEIPT":
        changes = {
            "total_received_units": title["total_received_units"] + units,
            "on_hand_units": title["on_hand_units"] + units,
        }
    else:
        if title["on_hand_units"] < units:
            fail(
                "ERR_INSUFFICIENT_PRINT_INVENTORY",
                "on_hand_units does not cover the requested write-off.",
            )
        changes = {
            "on_hand_units": title["on_hand_units"] - units,
            "written_off_units": title["written_off_units"] + units,
        }

    apply_changes(title, changes)
    return respond(S.serialize(title, S.TITLE_FIELDS))


@bp.post("/titles/<title_id>/revision-plan")
def revision_plan(title_id):
    authorize(("EditorialDirector",))
    payload = V.body()

    action = V.get_enum(payload, "action", REVISION_ACTIONS)
    target_year = V.get_int(
        payload, "revision_target_cycle_year", minimum=2020, maximum=2100,
        required=False, default=None,
    )
    if action == "PLAN" and target_year is None:
        fail(
            "ERR_INVALID_REQUEST",
            "revision_target_cycle_year is required for action PLAN.",
        )

    title = domain.find_title(title_id)

    if action == "PLAN":
        if title["status"] != "ACTIVE":
            fail(
                "ERR_TITLE_STATE_INVALID",
                "A revision may only be planned for an ACTIVE edition.",
            )
    else:
        if title["status"] != "REVISION_PLANNED":
            fail(
                "ERR_TITLE_STATE_INVALID",
                "Action %s requires a REVISION_PLANNED edition." % action,
            )

    if action == "SUNSET":
        for order in db.district_orders.values():
            if order["title_id"] == title_id and order["status"] == "CONFIRMED":
                fail(
                    "ERR_DISTRICT_ORDER_STATE_INVALID",
                    "A district order of this edition is still CONFIRMED.",
                )

    if action == "PLAN":
        for submission in domain.submissions_of_title(title_id):
            if submission["review_status"] not in domain.LIVE_REVIEW_STATUSES:
                continue
            cycle = db.adoption_cycles[submission["cycle_id"]]
            if cycle["cycle_year"] >= target_year:
                fail(
                    "ERR_REVISION_CONFLICTS_WITH_OPEN_ADOPTION",
                    "This edition still has a live submission in cycle year %d."
                    % cycle["cycle_year"],
                )

    if action == "PLAN":
        changes = {
            "status": "REVISION_PLANNED",
            "revision_target_cycle_year": target_year,
        }
    elif action == "CANCEL_PLAN":
        changes = {"status": "ACTIVE", "revision_target_cycle_year": None}
    else:
        changes = {
            "status": "SUNSET",
            "written_off_units": title["written_off_units"] + title["on_hand_units"],
            "on_hand_units": 0,
        }

    apply_changes(title, changes)
    return respond(S.serialize(title, S.TITLE_FIELDS))


@bp.post("/titles/<title_id>/ancillary-bundles")
def create_bundle(title_id):
    authorize(("PricingManager",))
    payload = V.body()

    bundle_code = V.get_str(payload, "bundle_code", min_len=1, max_len=30)
    component_count = V.get_int(
        payload, "component_count", minimum=1, maximum=12
    )
    component_list_total_cents = V.get_int(
        payload, "component_list_total_cents", minimum=1
    )
    digital_seat_price_cents = V.get_int(
        payload, "digital_seat_price_cents", minimum=1
    )
    rostering_standard = V.get_enum(
        payload, "rostering_standard", V.ROSTERING_STANDARDS
    )
    accessibility_conformance = V.get_enum(
        payload, "accessibility_conformance", V.ACCESSIBILITY_CONFORMANCE
    )
    privacy_addendum_signed = V.get_bool(
        payload, "privacy_addendum_signed", required=False, default=False
    )

    domain.find_title(title_id)

    for existing in db.ancillary_bundles.values():
        if existing["title_id"] == title_id and existing["bundle_code"] == bundle_code:
            fail(
                "ERR_DUPLICATE_RESOURCE",
                "Bundle code %s already exists for this edition." % bundle_code,
            )

    record = base_record()
    record.update(
        {
            "title_id": title_id,
            "bundle_code": bundle_code,
            "component_count": component_count,
            "component_list_total_cents": component_list_total_cents,
            "digital_seat_price_cents": digital_seat_price_cents,
            "rostering_standard": rostering_standard,
            "accessibility_conformance": accessibility_conformance,
            "privacy_addendum_signed": privacy_addendum_signed,
        }
    )
    db.ancillary_bundles[record["id"]] = record
    return respond(S.serialize(record, S.ANCILLARY_BUNDLE_FIELDS), 201)


@bp.get("/titles/<title_id>/ancillary-bundles")
def list_bundles(title_id):
    authorize(BUNDLE_LIST_ROLES)
    limit, offset = V.pagination()
    rostering_standard = V.query_enum("rostering_standard", V.ROSTERING_STANDARDS)

    domain.find_title(title_id)

    items = domain.ordered(
        [b for b in db.ancillary_bundles.values() if b["title_id"] == title_id]
    )
    if rostering_standard is not None:
        items = [i for i in items if i["rostering_standard"] == rostering_standard]

    total = len(items)
    page = items[offset:offset + limit]
    return respond_list(
        S.serialize_many(page, S.ANCILLARY_BUNDLE_FIELDS), total, limit, offset
    )
