"""MealServingRecord endpoints. PRD §3.6."""

from flask import Blueprint, request

from core.auth import require_roles
from core.clock import CLOCK
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, stamp_common, lock, touch, iso_from_dt
from core.validation import require_body, require_field, check_version

from services.calculations import (
    meal_charge_calc, usda_reimbursement_provisional,
)
from services.derived import student_allergy_blocks_menu_item
from services.ledger import (
    append_ledger_entry, simulate_charge_balance,
)
from services.relationships import (
    get_district_or_404, get_student_in_district,
    get_menu_item_in_district, get_meal_serving_in_district,
    get_parent_account_in_district,
)
from services.views import meal_serving_view


bp = Blueprint("meal_servings", __name__)


@bp.post("/districts/<district_id>/meal-servings")
@require_roles("CafeteriaManager")
def create_meal_serving(district_id):
    with lock():
        get_district_or_404(district_id)
        body = require_body(request)
        student_id = require_field(body, "student_id", kind="string")
        menu_item_id = require_field(body, "menu_item_id", kind="string")
        # Cross-aggregate existence + scoping.
        student = get_student_in_district(district_id, student_id)
        menu_item = get_menu_item_in_district(district_id, menu_item_id)
        # State (priority 4): MenuItem must be ACTIVE.
        if menu_item["status"] != "ACTIVE":
            raise_error("ERR_INVALID_STATE",
                        f"MenuItem is not ACTIVE (current={menu_item['status']})")
        # Priority 5: allergen block.
        if student_allergy_blocks_menu_item(student, menu_item):
            raise_error("ERR_ALLERGEN_BLOCK",
                        "Student has an ACTIVE allergy that intersects this MenuItem")
        # Priority 8: at most one SERVED per (student, serving_date).
        today_iso = iso_from_dt(CLOCK.today_midnight())
        for r in STORE.meal_serving_records.values():
            if (r["student_id"] == student_id
                    and r["serving_date"] == today_iso
                    and r["status"] == "SERVED"):
                raise_error("ERR_MEAL_ALREADY_SERVED_TODAY",
                            "Student already has a SERVED MealServingRecord today")
        # Compute charged_cents using tier_at_serving snapshot.
        tier = student.get("eligibility_tier", "PAID")
        charge = meal_charge_calc(tier, menu_item["full_price_cents"])
        # Priority 11: balance check for PAID tier — non-strict (>=).
        if tier == "PAID":
            parent_account = get_parent_account_in_district(
                district_id, student["parent_account_id"])
            # Post-charge balance must be >= 0.
            after = simulate_charge_balance(parent_account["id"], charge)
            if after < 0:
                raise_error("ERR_PREPAID_BALANCE_INSUFFICIENT",
                            "ParentAccount has insufficient prepaid balance "
                            "for a PAID-tier serving")
        provisional = usda_reimbursement_provisional(tier, menu_item["reimbursable"])
        r = {
            "district_id": district_id,
            "student_id": student_id,
            "menu_item_id": menu_item_id,
            "serving_date": today_iso,
            "status": "SERVED",
            "tier_at_serving": tier,
            "charged_cents": charge,
            "provisional_reimbursement_cents": provisional,
        }
        stamp_common(r)
        STORE.meal_serving_records[r["id"]] = r
        # Append CHARGE ledger entry if charge > 0.
        if charge > 0:
            append_ledger_entry(
                student["parent_account_id"], "CHARGE", charge, r["id"])
        return success_object(meal_serving_view(r), status=201)


def _record_locked_by_active_claim(district_id: str, record_id: str) -> bool:
    """True iff the record appears in a SUBMITTED or FINALIZED claim's
    serving_record_ids — or in the implicit period-window of a SUBMITTED claim
    (which has not yet snapshotted its rows). For SUBMITTED claims the
    serving_record_ids snapshot is not taken until FINALIZED; meanwhile the
    lock is by period — any record whose serving_date is inside an active
    claim's period is considered locked."""
    record = STORE.meal_serving_records.get(record_id)
    if record is None:
        return False
    for c in STORE.usda_claims.values():
        if c["district_id"] != district_id:
            continue
        if c["status"] == "SUBMITTED":
            # Period-based lock (snapshot not yet taken).
            if c["period_start"] <= record["serving_date"] <= c["period_end"]:
                return True
        elif c["status"] == "FINALIZED":
            if record_id in c.get("serving_record_ids", []):
                return True
    return False


@bp.post("/districts/<district_id>/meal-servings/<record_id>/void")
@require_roles("CafeteriaManager", "AuditOfficer")
def void_meal_serving(district_id, record_id):
    with lock():
        get_district_or_404(district_id)
        r = get_meal_serving_in_district(district_id, record_id)
        body = require_body(request)
        check_version(body, r)
        if r["status"] != "SERVED":
            raise_error("ERR_INVALID_STATE",
                        f"MealServingRecord is not SERVED (current={r['status']})")
        # Lock check.
        if _record_locked_by_active_claim(district_id, record_id):
            raise_error("ERR_INVALID_STATE",
                        "MealServingRecord is locked inside a SUBMITTED or FINALIZED claim")
        # Side effects.
        charged = r["charged_cents"]
        student = STORE.students[r["student_id"]]
        if charged > 0:
            append_ledger_entry(
                student["parent_account_id"], "REFUND", charged, r["id"])
        r["status"] = "VOIDED"
        r["provisional_reimbursement_cents"] = 0
        touch(r)
        return success_object(meal_serving_view(r))
