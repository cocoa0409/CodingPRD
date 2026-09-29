"""Consignment items: intake, screening, receiving, placement, disposition,
shrinkage flags, single write-off and release (PRD 3.2, 3.3, 3.5, 3.6, 3.7, 3.9)."""

from flask import Blueprint

import auth
import calc
import envelope
import serializers as ser
import services
import store
import validation as v
from errors import fail
from store import db

bp = Blueprint("items", __name__)

CATEGORIES = ("SOFA", "DINING", "CASEGOOD", "RUG", "ART", "OUTDOOR")
READ_ROLES = (
    "GalleryManager",
    "IntakeAppraiser",
    "FloorOperator",
    "LogisticsCoordinator",
    "Consignor",
    "SystemOperator",
)


def _item(item_id):
    return v.lookup(db.items, item_id, "ERR_ITEM_NOT_FOUND")


def _grade_and_price(row, surface, structure, completeness):
    """The screening arithmetic shared by screening and receiving."""
    score = calc.photo_score(surface, structure, completeness)
    grade = calc.grade_from_score(score)
    price = calc.item_list_price(row["declared_value_cents"], grade, row["category"])
    return score, grade, price


# ---------------------------------------------------------------------------
# intake
# ---------------------------------------------------------------------------
@bp.post("/consignment-items")
def create_item():
    auth.require("IntakeAppraiser")
    data = v.body()

    raw_agreement = v.raw_fk(data, "agreement_id")
    if raw_agreement is not None and raw_agreement not in db.agreements:
        fail("ERR_AGREEMENT_NOT_FOUND")
    raw_parent = v.raw_fk(data, "parent_lot_item_id")
    if raw_parent is not None and raw_parent not in db.items:
        fail("ERR_ITEM_NOT_FOUND")

    agreement_id = v.req_id(data, "agreement_id")
    title = v.req_str(data, "title")
    category = v.req_enum(data, "category", CATEGORIES)
    declared_value_cents = v.req_int(data, "declared_value_cents", minimum=1000)
    photo_count = v.req_int(data, "photo_count", minimum=0)
    volume_cuft = v.req_int(data, "volume_cuft", minimum=1)
    footprint_sqft = v.req_int(data, "footprint_sqft", minimum=1)
    parent_lot_item_id = v.opt_str(data, "parent_lot_item_id")

    agreement = db.agreements.get(agreement_id)
    if agreement is None:
        fail("ERR_AGREEMENT_NOT_FOUND")
    consignor = db.consignors.get(agreement["consignor_id"])

    if consignor is not None and consignor["escheat_state"] == "ESCHEATED":
        fail("ERR_CONSIGNOR_ESCHEATED")
    if consignor is not None and consignor["status"] != "ACTIVE":
        fail("ERR_CONSIGNOR_SUSPENDED")
    if agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE")

    if parent_lot_item_id is not None:
        parent = db.items.get(parent_lot_item_id)
        if parent is None:
            fail("ERR_ITEM_NOT_FOUND")
        if parent.get("parent_lot_item_id") is not None:
            fail("ERR_LOT_NESTING_FORBIDDEN")
        if parent["agreement_id"] != agreement_id:
            fail("ERR_LOT_NESTING_FORBIDDEN")

    row = store.new_row(
        db.items,
        {
            "consignor_id": agreement["consignor_id"],
            "agreement_id": agreement_id,
            "parent_lot_item_id": parent_lot_item_id,
            "pickup_job_id": None,
            "placement_zone_id": None,
            "title": title,
            "category": category,
            "declared_value_cents": declared_value_cents,
            "photo_count": photo_count,
            "volume_cuft": volume_cuft,
            "footprint_sqft": footprint_sqft,
            "photo_surface_score": None,
            "photo_structure_score": None,
            "photo_completeness_score": None,
            "photo_score": None,
            "provisional_condition_grade": None,
            "provisional_list_price_cents": None,
            "condition_grade": None,
            "list_price_cents": None,
            "current_price_cents": None,
            "markdown_sequence": 0,
            "lifecycle_state": "INTAKE_SUBMITTED",
            "inventory_state": "PENDING_CUSTODY",
            "tag_code": None,
            "listed_at": None,
            "election_round": 0,
            "election_deadline_at": None,
            "disposition_election": "NONE",
            "clearance_relocation_pending": False,
            "screened_by_user_id": None,
            "received_by_user_id": None,
            "election_lapsed": False,
        },
    )
    return envelope.created(ser.item(row))


@bp.get("/consignment-items/<item_id>")
def get_item(item_id):
    user_id, role = auth.require(*READ_ROLES)
    row = _item(item_id)
    auth.scope_consignor(role, user_id, row["consignor_id"])
    return envelope.ok(ser.item(row))


@bp.get("/consignment-items")
def list_items():
    user_id, role = auth.require(*READ_ROLES)
    limit, offset = v.pagination()
    rows = store.ordered(db.items)
    if role == "Consignor":
        rows = [r for r in rows if r["consignor_id"] == user_id]
    for field in (
        "consignor_id",
        "agreement_id",
        "parent_lot_item_id",
        "pickup_job_id",
        "placement_zone_id",
        "lifecycle_state",
        "inventory_state",
    ):
        wanted = v.q(field)
        if wanted is not None:
            rows = [r for r in rows if r.get(field) == wanted]
    page = v.window(rows, limit, offset)
    return envelope.listing(ser.many(ser.item, page), limit, offset, len(rows))


@bp.get("/consignment-items/<item_id>/ledger-entries")
def item_ledger(item_id):
    user_id, role = auth.require("GalleryManager", "Consignor", "SystemOperator")
    row = _item(item_id)
    auth.scope_consignor(role, user_id, row["consignor_id"])
    limit, offset = v.pagination()
    entry_type = v.q("entry_type")
    rows = services.ledger_of_item(row["id"])
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    page = v.window(rows, limit, offset)
    return envelope.listing(ser.many(ser.ledger_entry, page), limit, offset, len(rows))


# ---------------------------------------------------------------------------
# screening
# ---------------------------------------------------------------------------
@bp.post("/consignment-items/<item_id>/screen")
def screen_item(item_id):
    user_id, role = auth.require("IntakeAppraiser")
    row = _item(item_id)
    data = v.body()
    decision = v.req_enum(data, "decision", ("ACCEPT", "REJECT"))
    surface = v.opt_num(data, "photo_surface_score", minimum=0, maximum=10)
    structure = v.opt_num(data, "photo_structure_score", minimum=0, maximum=10)
    completeness = v.opt_num(data, "photo_completeness_score", minimum=0, maximum=10)

    if row["lifecycle_state"] != "INTAKE_SUBMITTED":
        fail("ERR_ITEM_STATE_INVALID")
    if row["photo_count"] < 3 or surface is None or structure is None or completeness is None:
        fail("ERR_PHOTOS_INSUFFICIENT")

    score, grade, price = _grade_and_price(row, surface, structure, completeness)
    row["photo_surface_score"] = surface
    row["photo_structure_score"] = structure
    row["photo_completeness_score"] = completeness
    row["photo_score"] = float(score)
    row["provisional_condition_grade"] = grade
    row["screened_by_user_id"] = user_id

    if decision == "REJECT" or grade == "REJECTED":
        row["lifecycle_state"] = "SCREEN_REJECTED"
    else:
        row["lifecycle_state"] = "SCREEN_ACCEPTED"
        row["provisional_list_price_cents"] = price
        row["condition_grade"] = grade
        row["list_price_cents"] = price
        row["current_price_cents"] = price
        if services.lot_component_count(row) > 0:
            services.price_lot_parent(row)
            row["provisional_list_price_cents"] = row["list_price_cents"]
            row["current_price_cents"] = row["list_price_cents"]
    store.touch(row)
    return envelope.ok(ser.item(row))


# ---------------------------------------------------------------------------
# receiving inspection
# ---------------------------------------------------------------------------
@bp.post("/consignment-items/<item_id>/receive")
def receive_item(item_id):
    user_id, role = auth.require("FloorOperator")
    row = _item(item_id)
    # ladder 3: segregation of duties, before any state is inspected
    if row.get("screened_by_user_id") is not None and row["screened_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")

    data = v.body()
    surface = v.req_num(data, "photo_surface_score", minimum=0, maximum=10)
    structure = v.req_num(data, "photo_structure_score", minimum=0, maximum=10)
    completeness = v.req_num(data, "photo_completeness_score", minimum=0, maximum=10)

    if row["lifecycle_state"] != "RECEIVED":
        fail("ERR_ITEM_STATE_INVALID")
    if row["inventory_state"] != "IN_CUSTODY":
        fail("ERR_ITEM_CUSTODY_INVALID")

    score, grade, price = _grade_and_price(row, surface, structure, completeness)
    row["photo_surface_score"] = surface
    row["photo_structure_score"] = structure
    row["photo_completeness_score"] = completeness
    row["photo_score"] = float(score)
    row["condition_grade"] = grade
    row["list_price_cents"] = price
    row["current_price_cents"] = price
    row["received_by_user_id"] = user_id
    if services.lot_component_count(row) > 0:
        services.price_lot_parent(row)
        row["current_price_cents"] = row["list_price_cents"]

    distance = calc.GRADE_RANK.get(row["provisional_condition_grade"], 0) - calc.GRADE_RANK.get(
        row["condition_grade"], 0
    )
    if distance >= 2:
        row["lifecycle_state"] = "RECEIVING_DISPUTE"
        schedule = services.schedule_of_item(row)
        window = schedule["election_window_days"] if schedule else 0
        row["election_deadline_at"] = store.add_days(store.now(), window)
    else:
        row["lifecycle_state"] = "AWAITING_PLACEMENT"
    store.touch(row)

    # PRD 3.5: the five-link upward cascade for a lot component
    services.cascade_lot_parent(row)
    return envelope.ok(ser.item(row))


# ---------------------------------------------------------------------------
# placement
# ---------------------------------------------------------------------------
@bp.post("/consignment-items/<item_id>/place")
def place_item(item_id):
    auth.require("FloorOperator")
    row = _item(item_id)
    data = v.body()

    raw_zone = v.raw_fk(data, "placement_zone_id")
    if raw_zone is not None and raw_zone not in db.zones:
        fail("ERR_ZONE_NOT_FOUND")

    zone_id = v.req_id(data, "placement_zone_id")
    tag_code = v.req_str(data, "tag_code")
    zone = db.zones.get(zone_id)
    if zone is None:
        fail("ERR_ZONE_NOT_FOUND")

    if row["lifecycle_state"] != "AWAITING_PLACEMENT":
        fail("ERR_ITEM_STATE_INVALID")
    if row["inventory_state"] != "IN_CUSTODY":
        fail("ERR_ITEM_CUSTODY_INVALID")

    consignor = db.consignors.get(row["consignor_id"])
    if consignor is not None and consignor["status"] != "ACTIVE":
        fail("ERR_CONSIGNOR_SUSPENDED")

    agreement = services.agreement_of(row)
    if agreement is None or agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE")
    if agreement["expires_at"] is not None and store.now() >= agreement["expires_at"]:
        fail("ERR_AGREEMENT_NOT_ACTIVE")

    if row["condition_grade"] == "REJECTED":
        fail("ERR_GRADE_REJECTED")
    if not services.lot_ready(row):
        fail("ERR_LOT_NOT_READY")

    for other in db.items.values():
        if other["id"] == row["id"]:
            continue
        if other.get("tag_code") == tag_code and other["inventory_state"] != "WRITTEN_OFF_INV":
            fail("ERR_DUPLICATE_TAG_CODE")

    if zone["status"] != "OPEN":
        fail("ERR_ZONE_CLOSED")
    if services.zone_occupied_sqft(zone["id"]) + row["footprint_sqft"] > zone["capacity_sqft"]:
        fail("ERR_ZONE_CAPACITY_EXCEEDED")

    row["lifecycle_state"] = "ON_FLOOR"
    row["placement_zone_id"] = zone["id"]
    row["tag_code"] = tag_code
    if row["listed_at"] is None:
        row["listed_at"] = store.now()
    services.recompute_current_price(row)
    services.clearance_relocation(row)
    store.touch(row)
    return envelope.ok(ser.item(row))


# ---------------------------------------------------------------------------
# disposition election
# ---------------------------------------------------------------------------
ELECTIONS = ("DONATE", "RETURN", "DISCOUNT")

_ELECTION_FROM_STATES = {
    "DISCOUNT": ("RECEIVING_DISPUTE", "UNSOLD_PENDING_ELECTION"),
    "RETURN": ("RECEIVING_DISPUTE", "UNSOLD_PENDING_ELECTION"),
    "DONATE": ("UNSOLD_PENDING_ELECTION",),
}


@bp.post("/consignment-items/<item_id>/elect-disposition")
def elect_disposition(item_id):
    user_id, role = auth.require("Consignor", "GalleryManager")
    row = _item(item_id)
    auth.scope_consignor(role, user_id, row["consignor_id"])
    data = v.body()
    election = v.req_enum(data, "election", ELECTIONS)

    # ladder 9
    if row["lifecycle_state"] not in _ELECTION_FROM_STATES[election]:
        fail("ERR_ITEM_STATE_INVALID")
    # ladder 18
    if election == "DISCOUNT" and int(row["election_round"] or 0) >= 2:
        fail("ERR_ELECTION_ROUND_EXHAUSTED")
    # ladder 19
    deadline = row["election_deadline_at"]
    if deadline is None or store.now() >= deadline:
        fail("ERR_ELECTION_DEADLINE_PASSED")
    # ladder 30
    if election == "DONATE":
        if row["category"] == "ART":
            fail("ERR_DISPOSITION_NOT_ELIGIBLE")
        if (row["current_price_cents"] or 0) > calc.DONATE_PRICE_CEILING_CENTS:
            fail("ERR_DISPOSITION_NOT_ELIGIBLE")
    if election == "RETURN" and row["inventory_state"] == "WRITTEN_OFF_INV":
        fail("ERR_DISPOSITION_NOT_ELIGIBLE")

    from_state = row["lifecycle_state"]
    row["disposition_election"] = election
    row["election_deadline_at"] = None
    if election == "DONATE":
        row["lifecycle_state"] = "DONATION_SCHEDULED"
    elif election == "RETURN":
        row["lifecycle_state"] = "RETURN_SCHEDULED"
    elif from_state == "RECEIVING_DISPUTE":
        # a grading concession: the piece goes back to placement, no extra round
        row["lifecycle_state"] = "AWAITING_PLACEMENT"
    else:
        row["lifecycle_state"] = "MARKED_DOWN"
        row["election_round"] = int(row["election_round"] or 0) + 1
        services.recompute_current_price(row)
        services.clearance_relocation(row)
    store.touch(row)
    return envelope.ok(ser.item(row))


# ---------------------------------------------------------------------------
# shrinkage flags, single write-off, release
# ---------------------------------------------------------------------------
MISSING_BARRED_LIFECYCLE = ("SOLD", "SETTLED", "RETURNED", "DONATED", "SCREEN_REJECTED")


@bp.post("/consignment-items/<item_id>/inventory-flag")
def inventory_flag(item_id):
    auth.require("FloorOperator")
    row = _item(item_id)
    data = v.body()
    flag = v.req_enum(data, "flag", ("MISSING", "RECOVERED"))

    if flag == "MISSING":
        if row["lifecycle_state"] in MISSING_BARRED_LIFECYCLE:
            fail("ERR_ITEM_STATE_INVALID")
        if row["inventory_state"] != "IN_CUSTODY":
            fail("ERR_ITEM_CUSTODY_INVALID")
        row["inventory_state"] = "SHRINKAGE_MISSING"
        store.touch(row)
        return envelope.ok(ser.item(row))

    if row["inventory_state"] == "SHRINKAGE_MISSING":
        row["inventory_state"] = "IN_CUSTODY"
        store.touch(row)
        return envelope.ok(ser.item(row))

    if row["inventory_state"] != "WRITTEN_OFF_INV":
        fail("ERR_ITEM_CUSTODY_INVALID")

    row["inventory_state"] = "IN_CUSTODY"
    row["lifecycle_state"] = "AWAITING_PLACEMENT"
    row["tag_code"] = None
    credited = 0
    for entry in services.ledger_of_item(row["id"]):
        if entry["entry_type"] == "SHRINKAGE_CREDIT":
            credited = int(entry["amount_cents"])
    consignor = services.consignor_of_item(row)
    if consignor is not None and credited:
        services.mint_entry(
            consignor,
            "SHRINKAGE_RECOVERY_DEBIT",
            -credited,
            "shrinkage recovery unwinding the write-off credit for item %s" % row["id"],
            item_id=row["id"],
        )
    store.touch(row)
    return envelope.ok(ser.item(row))


WRITE_OFF_LIFECYCLE = ("AWAITING_PLACEMENT", "ON_FLOOR", "MARKED_DOWN", "UNSOLD_PENDING_ELECTION")


@bp.post("/consignment-items/<item_id>/write-off")
def write_off_item(item_id):
    auth.require("GalleryManager")
    row = _item(item_id)
    data = v.body()
    expected = v.req_int(data, "expected_item_version")

    # ladder 8
    if expected != row["version"]:
        fail("ERR_STALE_ITEM_VERSION")
    if row["lifecycle_state"] not in WRITE_OFF_LIFECYCLE:
        fail("ERR_ITEM_STATE_INVALID")
    if row["inventory_state"] != "SHRINKAGE_MISSING":
        fail("ERR_ITEM_CUSTODY_INVALID")

    credit = calc.shrinkage_credit(row["current_price_cents"])
    row["inventory_state"] = "WRITTEN_OFF_INV"
    row["lifecycle_state"] = "WRITTEN_OFF"
    row["placement_zone_id"] = None
    consignor = services.consignor_of_item(row)
    if consignor is not None:
        services.mint_entry(
            consignor,
            "SHRINKAGE_CREDIT",
            credit,
            "shrinkage write-off credit for item %s" % row["id"],
            item_id=row["id"],
        )
    store.touch(row)
    return envelope.ok(ser.item(row))


@bp.post("/consignment-items/<item_id>/release")
def release_item(item_id):
    auth.require("FloorOperator")
    row = _item(item_id)

    if row["lifecycle_state"] == "RETURN_SCHEDULED":
        row["lifecycle_state"] = "RETURNED"
        amount = -calc.DISPOSAL_FEE_RETURN_CENTS
        memo = "return handling fee for item %s" % row["id"]
    elif row["lifecycle_state"] == "DONATION_SCHEDULED":
        row["lifecycle_state"] = "DONATED"
        amount = -calc.DISPOSAL_FEE_DONATION_CENTS
        if row.get("election_lapsed"):
            memo = "donation handling fee for item %s (election lapsed)" % row["id"]
        else:
            memo = "donation handling fee for item %s (election recorded)" % row["id"]
    else:
        fail("ERR_ITEM_STATE_INVALID")

    row["inventory_state"] = "RELEASED"
    row["placement_zone_id"] = None
    consignor = services.consignor_of_item(row)
    if consignor is not None:
        services.mint_entry(
            consignor, "DISPOSAL_FEE_DEBIT", amount, memo, item_id=row["id"]
        )
    store.touch(row)
    return envelope.ok(ser.item(row))
