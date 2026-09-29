"""Wine lists, list versions and the priced list entries."""
from flask import Blueprint

from core import (
    API_PREFIX,
    D,
    MAX_REVISION_ROUNDS,
    authorize,
    bool_param,
    check_venue_scope,
    fail,
    get_body,
    get_list_entry,
    get_list_version,
    get_venue,
    get_wine,
    get_wine_list,
    new_record,
    now,
    paginate,
    q,
    respond_list,
    respond_object,
    serialize,
    sort_default,
    store,
    touch,
    validate_body,
)
from calc import (
    LIVE_VERSION_STATES,
    TOP_TWO_BANDS,
    bottle_price_cents,
    contest_points,
    effective_pours_for,
    glass_price_cents,
    price_band,
)
from cascade import (
    entries_of_version,
    mark_pinned_events_stale,
    venue_id_of_entry,
    venue_id_of_version,
    wine_available,
)

bp = Blueprint("lists", __name__)

LIST_READ_ROLES = ["BeverageDirector", "VenueSommelier", "Controller", "ComplianceOfficer"]

WINE_LIST_SPEC = [
    {"name": "name", "type": "string", "required": True, "min_len": 1, "max_len": 80}
]


@bp.post(API_PREFIX + "/venues/<venue_id>/wine-lists")
def create_wine_list(venue_id):
    user_id, role = authorize("BeverageDirector", "VenueSommelier")
    check_venue_scope(role, user_id, venue_id)
    get_venue(venue_id)
    body = get_body()
    validate_body(body, WINE_LIST_SPEC)
    rec = new_record(
        {
            "venue_id": venue_id,
            "name": body["name"],
            "next_version_no": 1,
            "published_version_no": None,
        }
    )
    store.wine_lists[rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@bp.get(API_PREFIX + "/wine-lists/<wine_list_id>")
def read_wine_list(wine_list_id):
    authorize(LIST_READ_ROLES)
    return respond_object(serialize(get_wine_list(wine_list_id)))


@bp.get(API_PREFIX + "/wine-lists")
def list_wine_lists():
    authorize(LIST_READ_ROLES)
    rows = list(store.wine_lists.values())
    venue_id = q("venue_id")
    if venue_id is not None:
        rows = [r for r in rows if r["venue_id"] == venue_id]
    page, meta = paginate(sort_default(rows))
    return respond_list([serialize(r) for r in page], meta)


VERSION_SPEC = [{"name": "supersedes_version_id", "type": "string"}]


@bp.post(API_PREFIX + "/wine-lists/<wine_list_id>/versions")
def create_list_version(wine_list_id):
    user_id, role = authorize("VenueSommelier", "BeverageDirector")
    wine_list = get_wine_list(wine_list_id)
    check_venue_scope(role, user_id, wine_list["venue_id"])
    body = get_body()
    if body.get("supersedes_version_id") is not None:
        superseded = get_list_version(body["supersedes_version_id"])
        if superseded["wine_list_id"] != wine_list_id:
            fail(
                "ERR_LIST_VERSION_NOT_FOUND",
                "The superseded version belongs to another wine list.",
            )
    validate_body(body, VERSION_SPEC)

    rec = new_record(
        {
            "wine_list_id": wine_list_id,
            "version_no": int(wine_list["next_version_no"]),
            "supersedes_version_id": body.get("supersedes_version_id"),
            "state": "DRAFT",
            "entry_count": 0,
            "stale_entry_count": 0,
            "out_of_stock_entry_count": 0,
            "reprint_required": False,
            "revision_round": 0,
            "submitted_by_user_id": None,
            "published_by_user_id": None,
            "published_at": None,
            "printed_at": None,
        }
    )
    store.list_versions[rec["id"]] = rec
    wine_list["next_version_no"] = int(wine_list["next_version_no"]) + 1
    touch(wine_list)
    return respond_object(serialize(rec), 201)


@bp.get(API_PREFIX + "/list-versions/<list_version_id>")
def read_list_version(list_version_id):
    authorize(LIST_READ_ROLES)
    return respond_object(serialize(get_list_version(list_version_id)))


@bp.get(API_PREFIX + "/list-versions")
def list_list_versions():
    authorize(LIST_READ_ROLES)
    rows = list(store.list_versions.values())
    for field in ("wine_list_id", "supersedes_version_id", "state"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, meta = paginate(sort_default(rows))
    return respond_list([serialize(r) for r in page], meta)


@bp.post(API_PREFIX + "/list-versions/<list_version_id>/submit")
def submit_list_version(list_version_id):
    user_id, role = authorize("VenueSommelier", "BeverageDirector")
    version = get_list_version(list_version_id)
    check_venue_scope(role, user_id, venue_id_of_version(version))
    if version["state"] != "DRAFT":
        fail("ERR_LIST_VERSION_NOT_DRAFT", "Only a draft version may be submitted.")
    if int(version["entry_count"]) < 1:
        fail("ERR_EMPTY_LIST_VERSION", "A version with no entry cannot be submitted.")
    version["state"] = "IN_REVIEW"
    version["submitted_by_user_id"] = user_id
    touch(version)
    return respond_object(serialize(version))


NOTE_SPEC = [{"name": "note", "type": "string", "required": True}]


@bp.post(API_PREFIX + "/list-versions/<list_version_id>/request-changes")
def request_changes(list_version_id):
    authorize("BeverageDirector")
    version = get_list_version(list_version_id)
    body = get_body()
    validate_body(body, NOTE_SPEC)
    if version["state"] != "IN_REVIEW":
        fail("ERR_LIST_VERSION_NOT_IN_REVIEW", "Only a version under review may be bounced back.")
    if int(version["revision_round"]) >= MAX_REVISION_ROUNDS:
        fail("ERR_REVISION_LIMIT_REACHED", "The revision-round ceiling has been reached.")
    version["state"] = "DRAFT"
    version["revision_round"] = int(version["revision_round"]) + 1
    version["submitted_by_user_id"] = None
    touch(version)
    return respond_object(serialize(version))


@bp.post(API_PREFIX + "/list-versions/<list_version_id>/publish")
def publish_list_version(list_version_id):
    user_id, role = authorize("BeverageDirector")
    version = get_list_version(list_version_id)
    if version["state"] != "IN_REVIEW":
        fail("ERR_LIST_VERSION_NOT_IN_REVIEW", "Only a version under review may be published.")
    if version["submitted_by_user_id"] is not None and str(
        version["submitted_by_user_id"]
    ) == str(user_id):
        fail("ERR_SEGREGATION_OF_DUTIES", "The submitter of a version may not publish it.")
    venue = store.venues.get(venue_id_of_version(version))
    if venue is not None and venue["program_posture"] == "FROZEN":
        fail("ERR_VENUE_PROGRAM_FROZEN", "This venue's beverage program is frozen.")

    version["state"] = "PUBLISHED"
    version["published_at"] = now()
    version["printed_at"] = now()
    version["published_by_user_id"] = user_id

    wine_list = store.wine_lists.get(version["wine_list_id"])
    if wine_list is not None:
        wine_list["published_version_no"] = int(version["version_no"])
        touch(wine_list)

    out_of_stock = 0
    for entry in entries_of_version(version["id"]):
        state = (
            "AVAILABLE"
            if wine_available(venue["id"], entry["wine_id"])
            else "OUT_OF_STOCK"
        )
        if state != entry["availability_state"]:
            entry["availability_state"] = state
            touch(entry)
        if state == "OUT_OF_STOCK":
            out_of_stock += 1
    version["out_of_stock_entry_count"] = out_of_stock
    touch(version)

    if version["supersedes_version_id"]:
        superseded = store.list_versions.get(version["supersedes_version_id"])
        if superseded is not None and superseded["state"] in LIVE_VERSION_STATES:
            superseded["state"] = "SUPERSEDED"
            touch(superseded)
            mark_pinned_events_stale(superseded["id"])
    return respond_object(serialize(version))


@bp.post(API_PREFIX + "/list-versions/<list_version_id>/mark-reprinted")
def mark_reprinted(list_version_id):
    user_id, role = authorize("VenueSommelier", "BeverageDirector")
    version = get_list_version(list_version_id)
    check_venue_scope(role, user_id, venue_id_of_version(version))
    if version["state"] != "REPRINT_PENDING":
        fail(
            "ERR_LIST_VERSION_NOT_REPRINT_PENDING",
            "Only a version awaiting a reprint may be acknowledged.",
        )
    version["state"] = "PUBLISHED"
    version["printed_at"] = now()
    for entry in entries_of_version(version["id"]):
        if entry["vintage_stale"]:
            entry["vintage_stale"] = False
            touch(entry)
    version["stale_entry_count"] = 0
    version["reprint_required"] = False
    touch(version)
    return respond_object(serialize(version))


@bp.post(API_PREFIX + "/list-versions/<list_version_id>/archive")
def archive_list_version(list_version_id):
    authorize("BeverageDirector")
    version = get_list_version(list_version_id)
    if version["state"] != "DRAFT":
        fail("ERR_LIST_VERSION_NOT_DRAFT", "Only a draft version may be archived.")
    version["state"] = "ARCHIVED"
    touch(version)
    return respond_object(serialize(version))


ENTRY_SPEC = [
    {"name": "wine_id", "type": "string", "required": True},
    {"name": "sort_rank", "type": "int", "required": True, "min": 1},
    {"name": "expected_list_version_version", "type": "int", "required": True},
    {"name": "by_the_glass", "type": "bool"},
    {"name": "pour_size_ml", "type": "int", "min": 25, "max": 500},
    {"name": "par_bottles", "type": "int", "min": 0},
    {"name": "tasting_note", "type": "string", "min_len": 0, "max_len": 500},
    {"name": "education_verified", "type": "bool"},
]


@bp.post(API_PREFIX + "/list-versions/<list_version_id>/entries")
def create_list_entry(list_version_id):
    user_id, role = authorize("VenueSommelier")
    version = get_list_version(list_version_id)
    venue_id = venue_id_of_version(version)
    check_venue_scope(role, user_id, venue_id)
    body = get_body()
    wine = None
    if body.get("wine_id") is not None:
        wine = get_wine(body["wine_id"])
    validate_body(body, ENTRY_SPEC)

    by_the_glass = bool(body.get("by_the_glass", False))
    pour_size_ml = body.get("pour_size_ml")
    if by_the_glass and pour_size_ml is None:
        fail("ERR_POUR_SIZE_REQUIRED", "A by-the-glass listing needs a pour size.")
    if any(
        e["list_version_id"] == list_version_id and e["wine_id"] == body["wine_id"]
        for e in store.list_entries.values()
    ):
        fail("ERR_DUPLICATE_LIST_ENTRY_WINE", "That wine is already on this version.")
    if int(body["expected_list_version_version"]) != int(version["version"]):
        fail("ERR_STALE_VERSION", "The list version has moved on since it was last read.")
    if version["state"] != "DRAFT":
        fail("ERR_LIST_VERSION_NOT_DRAFT", "Entries may only be added to a draft version.")

    venue = store.venues.get(venue_id)
    effective_pours = None
    glass_price = None
    if by_the_glass:
        effective_pours = effective_pours_for(wine["bottle_size_ml"], pour_size_ml)
        if effective_pours < 1:
            fail("ERR_POUR_SIZE_TOO_LARGE", "That pour size leaves no saleable glass.")
        glass_price = glass_price_cents(wine, venue, effective_pours)

    bottle_price = bottle_price_cents(wine, venue)
    band = price_band(bottle_price)
    if venue["program_posture"] in ("RESTRICTED", "FROZEN") and band in TOP_TWO_BANDS:
        fail(
            "ERR_VENUE_PROGRAM_RESTRICTED",
            "This venue may not list a wine in the top two price bands.",
        )

    available = wine_available(venue_id, body["wine_id"])
    rec = new_record(
        {
            "list_version_id": list_version_id,
            "wine_id": body["wine_id"],
            "bottle_price_cents": bottle_price,
            "price_band": band,
            "by_the_glass": by_the_glass,
            "pour_size_ml": pour_size_ml if by_the_glass else None,
            "glass_price_cents": glass_price,
            "effective_pours": effective_pours,
            "par_bottles": body.get("par_bottles", 0),
            "tasting_note": body.get("tasting_note"),
            "education_verified": bool(body.get("education_verified", False)),
            "availability_state": "AVAILABLE" if available else "OUT_OF_STOCK",
            "vintage_stale": int(wine["successor_count"]) > 0,
            "contest_points": D("0.00"),
            "sort_rank": body["sort_rank"],
        }
    )
    store.list_entries[rec["id"]] = rec
    rec["contest_points"] = contest_points(rec, venue, wine)

    version["entry_count"] = int(version["entry_count"]) + 1
    if rec["availability_state"] == "OUT_OF_STOCK":
        version["out_of_stock_entry_count"] = int(version["out_of_stock_entry_count"]) + 1
    if rec["vintage_stale"]:
        version["stale_entry_count"] = int(version["stale_entry_count"]) + 1
    touch(version)
    return respond_object(serialize(rec), 201)


@bp.get(API_PREFIX + "/list-entries/<list_entry_id>")
def read_list_entry(list_entry_id):
    authorize(LIST_READ_ROLES)
    return respond_object(serialize(get_list_entry(list_entry_id)))


@bp.get(API_PREFIX + "/list-entries")
def list_list_entries():
    authorize(LIST_READ_ROLES)
    rows = list(store.list_entries.values())
    for field in ("list_version_id", "wine_id", "price_band", "availability_state"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    by_the_glass = bool_param("by_the_glass")
    if by_the_glass is not None:
        rows = [r for r in rows if bool(r["by_the_glass"]) == by_the_glass]
    rows = sorted(rows, key=lambda r: (r["sort_rank"], r["created_at"], r["_seq"]))
    page, meta = paginate(rows)
    return respond_list([serialize(r) for r in page], meta)


PATCH_ENTRY_SPEC = [
    {"name": "by_the_glass", "type": "bool"},
    {"name": "pour_size_ml", "type": "int", "min": 25, "max": 500},
    {"name": "tasting_note", "type": "string", "min_len": 0, "max_len": 500},
    {"name": "education_verified", "type": "bool"},
    {"name": "par_bottles", "type": "int", "min": 0},
    {"name": "sort_rank", "type": "int", "min": 1},
]


@bp.patch(API_PREFIX + "/list-entries/<list_entry_id>")
def patch_list_entry(list_entry_id):
    user_id, role = authorize("VenueSommelier")
    entry = get_list_entry(list_entry_id)
    venue_id = venue_id_of_entry(entry)
    check_venue_scope(role, user_id, venue_id)
    body = get_body()
    validate_body(body, PATCH_ENTRY_SPEC)

    by_the_glass = bool(body["by_the_glass"]) if "by_the_glass" in body else bool(
        entry["by_the_glass"]
    )
    pour_size_ml = body["pour_size_ml"] if "pour_size_ml" in body else entry["pour_size_ml"]
    if by_the_glass and pour_size_ml is None:
        fail("ERR_POUR_SIZE_REQUIRED", "A by-the-glass listing needs a pour size.")

    version = store.list_versions.get(entry["list_version_id"])
    if version is None or version["state"] != "DRAFT":
        fail("ERR_LIST_VERSION_NOT_DRAFT", "Only an entry on a draft version may be amended.")

    venue = store.venues.get(venue_id)
    wine = store.wines.get(entry["wine_id"])
    if by_the_glass:
        effective_pours = effective_pours_for(wine["bottle_size_ml"], pour_size_ml)
        if effective_pours < 1:
            fail("ERR_POUR_SIZE_TOO_LARGE", "That pour size leaves no saleable glass.")
        entry["effective_pours"] = effective_pours
        entry["glass_price_cents"] = glass_price_cents(wine, venue, effective_pours)
        entry["pour_size_ml"] = pour_size_ml
    else:
        entry["effective_pours"] = None
        entry["glass_price_cents"] = None
        if "pour_size_ml" in body:
            entry["pour_size_ml"] = body["pour_size_ml"]
    entry["by_the_glass"] = by_the_glass
    for field in ("tasting_note", "education_verified", "par_bottles", "sort_rank"):
        if field in body:
            entry[field] = body[field]
    entry["contest_points"] = contest_points(entry, venue, wine)
    touch(entry)
    return respond_object(serialize(entry))
