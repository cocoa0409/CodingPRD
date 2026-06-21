"""ServiceTransaction routes + state machine."""
from flask import Blueprint, request
import db
from response import success_object, success_array, iso_utc
from middleware import require_role
from validation import (
    parse_pagination, get_json_body, enforce_keys, require_str, require_int,
    require_bool,
)
from services import (
    common_fields_init, common_fields_init_no_version, bump_version,
    get_or_404, sort_by_created_at, paginate, clean, now,
    select_active_determination, compute_balance, parent_account_for_household,
)
from calculations import compute_paid_charge
from errors import (
    ERR_INVALID_REQUEST, ERR_NOT_RESOURCE_OWNER, ERR_INVALID_STATE,
    ERR_ALLERGEN_CONFLICT, ERR_NO_ACTIVE_ELIGIBILITY, ERR_INSUFFICIENT_FUNDS,
    ERR_STALE_VERSION, raise_err,
)

bp = Blueprint("service_transactions", __name__)


VALID_REJECTION_REASONS = {"ALLERGEN_CONFLICT", "INELIGIBLE_STATE", "INSUFFICIENT_FUNDS", "MANUAL"}
VALID_RESOLUTIONS = {"REFUND", "UPHOLD"}


def _profile_for_student(student_id):
    for ap in db.allergy_profiles.values():
        if ap["student_id"] == student_id:
            return ap
    return None


@bp.post("/school-meals/service-transactions")
def create_transaction():
    require_role({"SchoolStaff"})
    body = get_json_body()
    enforce_keys(body, required={"student_id", "menu_item_id"}, optional={"substitute_for_allergen"})
    require_str(body["student_id"], "student_id")
    require_str(body["menu_item_id"], "menu_item_id")
    substitute = body.get("substitute_for_allergen", False)
    if "substitute_for_allergen" in body:
        require_bool(body["substitute_for_allergen"], "substitute_for_allergen")
    student = get_or_404(db.students, body["student_id"], "Student")
    menu_item = get_or_404(db.menu_items, body["menu_item_id"], "MenuItem")

    # Allergen safety check (validation priority 6).
    profile = _profile_for_student(student["id"])
    student_allergens = profile["allergens"] if profile else []
    student_severity = profile["severity"] if profile else None
    menu_allergens = menu_item.get("allergens_present") or []
    intersects = bool(set(student_allergens) & set(menu_allergens))
    if intersects and student_severity == "SEVERE_ANAPHYLACTIC" and substitute is not True:
        raise_err(ERR_ALLERGEN_CONFLICT, "menu item contains allergen present in student's profile")

    # Select active eligibility determination.
    det = select_active_determination(student)
    if det is None:
        raise_err(ERR_NO_ACTIVE_ELIGIBILITY, "no active eligibility determination for student's household")

    applied_tier = det["tier"]
    paid_charge = compute_paid_charge(
        applied_tier,
        menu_item["list_price_cents"],
        menu_allergens,
        student_allergens,
        bool(substitute),
    )

    n = now()
    rec = {
        **common_fields_init(),
        "student_id": student["id"],
        "menu_item_id": menu_item["id"],
        "eligibility_determination_id": det["id"],
        "applied_tier": applied_tier,
        "status": "PENDING",
        "paid_charge_cents": paid_charge,
        "federal_reimbursement_cents": 0,
        "rejection_reason": None,
        "served_at_utc": iso_utc(n),
        # Stash internal fields for cascades / aggregation.
        "_served_at_dt": n,
        "substitute_for_allergen": bool(substitute),
    }
    db.service_transactions[rec["id"]] = rec
    return success_object(_serialize_txn(rec), status=201)


def _serialize_txn(rec):
    cleaned = clean(rec)
    # Don't leak substitute_for_allergen unless it's intended; keep it for now since
    # it's used for re-binding cascade. The PRD does not list it as part of the
    # entity, so strip it from responses.
    cleaned.pop("substitute_for_allergen", None)
    return cleaned


@bp.get("/school-meals/service-transactions/<tid>")
def read_transaction(tid):
    from middleware import get_auth
    user_id, role = get_auth()
    if role not in {"Parent", "SchoolStaff", "DistrictReviewer", "USDAAuditor"}:
        from errors import ERR_FORBIDDEN
        raise_err(ERR_FORBIDDEN, "role not allowed")
    rec = get_or_404(db.service_transactions, tid, "ServiceTransaction")
    if role == "Parent":
        student = db.students.get(rec["student_id"])
        if student is None or user_id != student["household_id"]:
            raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this transaction")
    return success_object(_serialize_txn(rec))


@bp.get("/school-meals/service-transactions")
def list_transactions():
    require_role({"SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    limit, offset = parse_pagination()
    sid = request.args.get("student_id")
    mid = request.args.get("menu_item_id")
    did = request.args.get("eligibility_determination_id")
    status_f = request.args.get("status")
    school_code = request.args.get("school_code")
    items = list(db.service_transactions.values())
    if sid is not None:
        items = [t for t in items if t["student_id"] == sid]
    if mid is not None:
        items = [t for t in items if t["menu_item_id"] == mid]
    if did is not None:
        items = [t for t in items if t["eligibility_determination_id"] == did]
    if status_f is not None:
        items = [t for t in items if t["status"] == status_f]
    if school_code is not None:
        # Filter by student.school_code.
        kept = []
        for t in items:
            s = db.students.get(t["student_id"])
            if s is not None and s["school_code"] == school_code:
                kept.append(t)
        items = kept
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array([_serialize_txn(r) for r in page], limit=limit, offset=offset, total_count=total)


# ------------------------------ Transitions ----------------------------------

def _household_account_for_student(student_id):
    s = db.students.get(student_id)
    if s is None:
        return None
    return parent_account_for_household(s["household_id"])


@bp.post("/school-meals/service-transactions/<tid>/settle")
def settle_transaction(tid):
    require_role({"SchoolStaff"})
    rec = get_or_404(db.service_transactions, tid, "ServiceTransaction")
    body = get_json_body()
    enforce_keys(body, required=set(), optional=set())
    if rec["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, f"transaction status is {rec['status']}, expected PENDING")
    det = db.eligibility_determinations.get(rec["eligibility_determination_id"])
    if det is None or det["lifecycle_status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "linked eligibility determination is not ACTIVE")
    acct = _household_account_for_student(rec["student_id"])
    if acct is None:
        # Shouldn't happen — household_account is created with household.
        raise_err(ERR_INVALID_STATE, "no parent account for student")
    balance = compute_balance(acct["id"])
    if balance < rec["paid_charge_cents"]:
        raise_err(ERR_INSUFFICIENT_FUNDS, "insufficient funds")

    # Create MEAL_CHARGE ledger entry.
    entry = {
        **common_fields_init_no_version(),
        "parent_account_id": acct["id"],
        "entry_type": "MEAL_CHARGE",
        "amount_cents": -rec["paid_charge_cents"],
        "linked_transaction_id": rec["id"],
        "idempotency_key": None,
    }
    db.ledger_entries[entry["id"]] = entry

    # Set federal_reimbursement_cents from menu item per-tier rate.
    menu = db.menu_items.get(rec["menu_item_id"])
    tier = rec["applied_tier"]
    if tier == "FREE":
        rec["federal_reimbursement_cents"] = menu["federal_reimbursement_free_cents"] if menu else 0
    elif tier == "REDUCED":
        rec["federal_reimbursement_cents"] = menu["federal_reimbursement_reduced_cents"] if menu else 0
    else:
        rec["federal_reimbursement_cents"] = menu["federal_reimbursement_paid_cents"] if menu else 0

    rec["status"] = "SETTLED"
    bump_version(rec)

    # Reconcile balance on the parent account record.
    acct["balance_cents"] = compute_balance(acct["id"])
    bump_version(acct)

    return success_object(_serialize_txn(rec))


@bp.post("/school-meals/service-transactions/<tid>/reject")
def reject_transaction(tid):
    require_role({"SchoolStaff"})
    rec = get_or_404(db.service_transactions, tid, "ServiceTransaction")
    body = get_json_body()
    enforce_keys(body, required={"rejection_reason"}, optional=set())
    require_str(body["rejection_reason"], "rejection_reason")
    if body["rejection_reason"] not in VALID_REJECTION_REASONS:
        raise_err(ERR_INVALID_REQUEST, "invalid rejection_reason")
    if rec["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, f"transaction status is {rec['status']}, expected PENDING")
    rec["status"] = "REJECTED"
    rec["rejection_reason"] = body["rejection_reason"]
    bump_version(rec)
    return success_object(_serialize_txn(rec))


@bp.post("/school-meals/service-transactions/<tid>/refund")
def refund_transaction(tid):
    require_role({"SchoolStaff"})
    rec = get_or_404(db.service_transactions, tid, "ServiceTransaction")
    body = get_json_body()
    enforce_keys(body, required={"expected_servicetransaction_version"}, optional=set())
    require_int(body["expected_servicetransaction_version"], "expected_servicetransaction_version", min_val=0)
    # PRD §2.5 line 90: the OCC stale-version guard for refund explicitly
    # captures the case where the transaction "has advanced — for example,
    # into DISPUTED — since the staff member's read". The OCC check therefore
    # fires before the SETTLED state precondition: a stale-view refund of a
    # now-DISPUTED tx must surface ERR_STALE_VERSION, not ERR_INVALID_STATE.
    if body["expected_servicetransaction_version"] != rec["version"]:
        raise_err(ERR_STALE_VERSION, "expected_servicetransaction_version does not match")
    if rec["status"] != "SETTLED":
        raise_err(ERR_INVALID_STATE, f"transaction status is {rec['status']}, expected SETTLED")
    acct = _household_account_for_student(rec["student_id"])
    if acct is None:
        raise_err(ERR_INVALID_STATE, "no parent account for student")
    entry = {
        **common_fields_init_no_version(),
        "parent_account_id": acct["id"],
        "entry_type": "MEAL_REFUND",
        "amount_cents": rec["paid_charge_cents"],
        "linked_transaction_id": rec["id"],
        "idempotency_key": None,
    }
    db.ledger_entries[entry["id"]] = entry
    rec["status"] = "REFUNDED"
    rec["federal_reimbursement_cents"] = 0
    bump_version(rec)
    acct["balance_cents"] = compute_balance(acct["id"])
    bump_version(acct)
    return success_object(_serialize_txn(rec))


@bp.post("/school-meals/service-transactions/<tid>/dispute")
def dispute_transaction(tid):
    user_id, role = require_role({"Parent"})
    rec = get_or_404(db.service_transactions, tid, "ServiceTransaction")
    student = db.students.get(rec["student_id"])
    if student is None or user_id != student["household_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this transaction")
    body = get_json_body()
    enforce_keys(body, required=set(), optional=set())
    if rec["status"] != "SETTLED":
        raise_err(ERR_INVALID_STATE, f"transaction status is {rec['status']}, expected SETTLED")
    rec["status"] = "DISPUTED"
    bump_version(rec)
    return success_object(_serialize_txn(rec))


@bp.post("/school-meals/service-transactions/<tid>/resolve-dispute")
def resolve_dispute(tid):
    require_role({"DistrictReviewer"})
    rec = get_or_404(db.service_transactions, tid, "ServiceTransaction")
    body = get_json_body()
    enforce_keys(body, required={"resolution"}, optional=set())
    require_str(body["resolution"], "resolution")
    if body["resolution"] not in VALID_RESOLUTIONS:
        raise_err(ERR_INVALID_REQUEST, "resolution must be REFUND or UPHOLD")
    if rec["status"] != "DISPUTED":
        raise_err(ERR_INVALID_STATE, f"transaction status is {rec['status']}, expected DISPUTED")
    if body["resolution"] == "REFUND":
        acct = _household_account_for_student(rec["student_id"])
        if acct is None:
            raise_err(ERR_INVALID_STATE, "no parent account for student")
        entry = {
            **common_fields_init_no_version(),
            "parent_account_id": acct["id"],
            "entry_type": "MEAL_REFUND",
            "amount_cents": rec["paid_charge_cents"],
            "linked_transaction_id": rec["id"],
            "idempotency_key": None,
        }
        db.ledger_entries[entry["id"]] = entry
        rec["status"] = "REFUNDED"
        rec["federal_reimbursement_cents"] = 0
        bump_version(rec)
        acct["balance_cents"] = compute_balance(acct["id"])
        bump_version(acct)
    else:  # UPHOLD
        rec["status"] = "SETTLED"
        bump_version(rec)
    return success_object(_serialize_txn(rec))
