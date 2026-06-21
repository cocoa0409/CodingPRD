"""Shared services: serialization, common-fields, cascades, selectors."""
from datetime import timedelta
import db
from response import iso_utc, parse_iso_utc


def now():
    return db.server_now()


def common_fields_init():
    n = now()
    return {
        "id": db.new_id(),
        "created_at": iso_utc(n),
        "updated_at": iso_utc(n),
        "version": 1,
        "_created_at_dt": n,
    }


def common_fields_init_no_version():
    """For LedgerEntry — only id + created_at (no updated_at or version)."""
    n = now()
    return {
        "id": db.new_id(),
        "created_at": iso_utc(n),
        "_created_at_dt": n,
    }


def bump_version(record: dict):
    record["version"] = record.get("version", 0) + 1
    record["updated_at"] = iso_utc(now())


def clean(record):
    """Strip private (underscore-prefixed) fields for serialization."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ------------------------------ Serializers --------------------------------

def serialize(record):
    """Default: return a shallow copy of the record."""
    if record is None:
        return None
    return dict(record)


def serialize_parent_account(rec):
    # Reconcile balance from ledger on every read.
    rec = dict(rec)
    rec["balance_cents"] = compute_balance(rec["id"])
    return rec


def serialize_eligibility_determination(rec):
    return dict(rec)


# --------------------- Hierarchical resource resolution --------------------

def get_or_404(table: dict, entity_id: str, entity_label: str):
    from errors import ERR_NOT_FOUND, raise_err
    if entity_id not in table:
        raise_err(ERR_NOT_FOUND, f"{entity_label} {entity_id} not found")
    return table[entity_id]


# ----------------------------- Ledger helpers ------------------------------

def compute_balance(parent_account_id: str) -> int:
    total = 0
    for entry in db.ledger_entries.values():
        if entry["parent_account_id"] == parent_account_id:
            total += entry["amount_cents"]
    return total


def parent_account_for_household(household_id: str):
    for acct in db.parent_accounts.values():
        if acct["household_id"] == household_id:
            return acct
    return None


# ------------- Select active eligibility determination (§1.3) --------------

def select_active_determination(student_record):
    """Return the chosen EligibilityDetermination or None if no candidates."""
    household_id = student_record["household_id"]
    n = now()
    candidates = []
    for det in db.eligibility_determinations.values():
        if det["household_id"] != household_id:
            continue
        if det["lifecycle_status"] != "ACTIVE":
            continue
        vf = det["_valid_from_dt"]
        vt = det["_valid_to_dt"]
        # half-open [valid_from, valid_to)
        if vf <= n < vt:
            candidates.append(det)
    if not candidates:
        return None

    tier_priority = {"FREE": 3, "REDUCED": 2, "PAID": 1}

    def sort_key(d):
        return (
            -tier_priority.get(d["tier"], 0),
            # latest valid_from first → invert by negating epoch
            -d["_valid_from_dt"].timestamp(),
            -d["_created_at_dt"].timestamp(),
        )

    candidates.sort(key=sort_key)
    return candidates[0]


# ------------------- Allergen cascade (PRD §3.1) ---------------------------

def cascade_allergen_check_for_student(student_id: str):
    """For each PENDING ServiceTransaction tied to this student, if the
    student's CURRENT AllergyProfile would block the served menu item
    (severity==SEVERE_ANAPHYLACTIC AND intersection), reject the transaction."""
    profile = None
    for ap in db.allergy_profiles.values():
        if ap["student_id"] == student_id:
            profile = ap
            break
    if profile is None or profile.get("severity") != "SEVERE_ANAPHYLACTIC":
        return
    profile_allergens = set(profile.get("allergens") or [])
    if not profile_allergens:
        return
    for txn in db.service_transactions.values():
        if txn["student_id"] != student_id:
            continue
        if txn["status"] != "PENDING":
            continue
        menu_item = db.menu_items.get(txn["menu_item_id"])
        if menu_item is None:
            continue
        menu_allergens = set(menu_item.get("allergens_present") or [])
        if profile_allergens & menu_allergens:
            txn["status"] = "REJECTED"
            txn["rejection_reason"] = "ALLERGEN_CONFLICT"
            bump_version(txn)


# ------------- School year end + 30 day carryover (PRD §3.3) --------------

def school_year_end_plus_carryover(school_year: str):
    """Given a school year like '2025-2026', return datetime = end-of-year + 30d.
    End of school year = June 30 of the latter calendar year, 23:59:59.999 UTC.
    Then + 30 days carryover."""
    from datetime import datetime, timezone
    try:
        parts = school_year.split("-")
        end_year = int(parts[1])
    except Exception:
        # Fall back to one year from now
        return now() + timedelta(days=365 + 30)
    end_of_sy = datetime(end_year, 6, 30, 23, 59, 59, 999000, tzinfo=timezone.utc)
    return end_of_sy + timedelta(days=30)


# ----------------------------- Sorting helpers -----------------------------

def sort_by_created_at(items):
    return sorted(items, key=lambda r: r.get("_created_at_dt") or r.get("created_at"))


def paginate(items, limit: int, offset: int):
    total = len(items)
    sliced = items[offset:offset + limit]
    return sliced, total
