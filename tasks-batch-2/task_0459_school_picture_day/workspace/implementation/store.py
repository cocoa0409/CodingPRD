"""Entity construction, common-field bookkeeping, lookup, and serialization.

Common fields (PRD §2.4): id, created_at, updated_at, version (starts at 1,
+1 on every mutation including derived-field mutations).

Internal-only keys are prefixed with '_' and stripped on serialization.
"""
import db
from errors import err

# Public field order per entity (drives serialization output).
ENTITY_FIELDS = {
    "session": [
        "id", "school_name", "scheduled_date", "gallery_access_code",
        "gallery_opens_at", "gallery_closes_at", "retouch_budget_cents",
        "retouch_credit_balance_cents", "school_commission_balance_cents",
        "total_merchandise_cents", "status",
        "created_at", "updated_at", "version",
    ],
    "student": [
        "id", "picture_day_session_id", "guardian_user_id", "full_name",
        "grade", "homeroom", "status",
        "created_at", "updated_at", "version",
    ],
    "photo": [
        "id", "picture_day_session_id", "matched_student_id",
        "retake_of_photo_id", "candidate_grade", "candidate_homeroom",
        "candidate_name", "match_confidence_score", "yearbook_exported",
        "status", "created_at", "updated_at", "version",
    ],
    "package": [
        "id", "picture_day_session_id", "sku", "name", "tier",
        "base_price_cents", "active",
        "created_at", "updated_at", "version",
    ],
    "order": [
        "id", "picture_day_session_id", "student_id", "subtotal_cents",
        "discount_pct", "discount_cents", "merchandise_cents",
        "shipping_cents", "total_cents", "has_premium_line", "status",
        "created_at", "updated_at", "version",
    ],
    "line": [
        "id", "photo_order_id", "package_item_id", "quantity",
        "unit_price_cents", "line_total_cents",
        "created_at", "updated_at", "version",
    ],
    "retouch": [
        "id", "photo_id", "kind", "adjustment_count", "premium_linked",
        "gross_cost_cents", "comp_discount_cents", "net_cost_cents",
        "replacement_photo_id", "status",
        "created_at", "updated_at", "version",
    ],
    "shipment": [
        "id", "photo_order_id", "carrier", "distribution_method",
        "tracking_code", "status",
        "created_at", "updated_at", "version",
    ],
    "backdrop": [
        "id", "picture_day_session_id", "label", "active",
        "created_at", "updated_at", "version",
    ],
    "photographer": [
        "id", "picture_day_session_id", "full_name",
        "created_at", "updated_at", "version",
    ],
    "slot": [
        "id", "picture_day_session_id", "backdrop_id", "photographer_id",
        "homeroom", "start_minute", "end_minute", "status",
        "created_at", "updated_at", "version",
    ],
}


def new_row(kind, fields):
    """Create a new row dict with common fields populated (version=1)."""
    now = db.iso_now()
    row = dict(fields)
    row["id"] = db.new_id()
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1
    row["_kind"] = kind
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Mark a mutation: bump version and refresh updated_at."""
    row["version"] += 1
    row["updated_at"] = db.iso_now()


def serialize(row):
    """Project a row to its public field set in declared order."""
    kind = row["_kind"]
    fields = ENTITY_FIELDS[kind]
    return {f: row.get(f) for f in fields}


# ---------------------------------------------------------------------------
# Lookup helpers — raise the matching not-found error when absent.
# ---------------------------------------------------------------------------
def _get(coll, rid, error_id):
    row = coll.get(rid)
    if row is None:
        raise err(error_id)
    return row


def get_session(rid):
    return _get(db.sessions, rid, "ERR_SESSION_NOT_FOUND")


def get_student(rid):
    return _get(db.students, rid, "ERR_STUDENT_NOT_FOUND")


def get_photo(rid):
    return _get(db.photos, rid, "ERR_PHOTO_NOT_FOUND")


def get_package(rid):
    return _get(db.packages, rid, "ERR_PACKAGE_NOT_FOUND")


def get_order(rid):
    return _get(db.photo_orders, rid, "ERR_ORDER_NOT_FOUND")


def get_line(rid):
    return _get(db.order_lines, rid, "ERR_LINE_NOT_FOUND")


def get_retouch(rid):
    return _get(db.retouch_orders, rid, "ERR_RETOUCH_NOT_FOUND")


def get_shipment(rid):
    return _get(db.shipments, rid, "ERR_SHIPMENT_NOT_FOUND")


def get_backdrop(rid):
    return _get(db.backdrops, rid, "ERR_BACKDROP_NOT_FOUND")


def get_photographer(rid):
    return _get(db.photographers, rid, "ERR_PHOTOGRAPHER_NOT_FOUND")


def get_slot(rid):
    return _get(db.capture_slots, rid, "ERR_SLOT_NOT_FOUND")
