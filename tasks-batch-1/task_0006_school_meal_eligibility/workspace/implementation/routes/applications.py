"""MealApplication routes (CRUD + state machine transitions)."""
from flask import Blueprint, request
import db
from response import success_object, success_array, iso_utc
from middleware import require_role
from validation import (
    parse_pagination, get_json_body, enforce_keys, require_str, require_int,
)
from services import (
    common_fields_init, bump_version, get_or_404, sort_by_created_at, paginate, clean,
    now, school_year_end_plus_carryover,
)
from errors import (
    ERR_INVALID_REQUEST, ERR_NOT_RESOURCE_OWNER, ERR_INVALID_STATE,
    ERR_HOUSEHOLD_INCOMPLETE, ERR_STALE_VERSION, ERR_ELIGIBILITY_OVERLAP, raise_err,
)
from calculations import determine_tier_from_income, compute_paid_charge

bp = Blueprint("applications", __name__)


# --------------------- Create / Read / List --------------------------

@bp.post("/school-meals/applications")
def create_application():
    user_id, role = require_role({"Parent", "SchoolStaff"})
    body = get_json_body()
    enforce_keys(body, required={"household_id", "school_year"}, optional=set())
    require_str(body["household_id"], "household_id")
    require_str(body["school_year"], "school_year")
    get_or_404(db.households, body["household_id"], "Household")
    if role == "Parent" and user_id != body["household_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this household")

    rec = {
        **common_fields_init(),
        "household_id": body["household_id"],
        "status": "DRAFT",
        "snapshot_family_size": None,
        "snapshot_annual_income_cents": None,
        "snapshot_address_state": None,
        "school_year": body["school_year"],
        "decision_reason": None,
        "appeal_reason": None,
    }
    db.meal_applications[rec["id"]] = rec
    return success_object(clean(rec), status=201)


@bp.get("/school-meals/applications/<aid>")
def read_application(aid):
    user_id, role = require_role({"Parent", "SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    rec = get_or_404(db.meal_applications, aid, "MealApplication")
    if role == "Parent" and user_id != rec["household_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this application")
    return success_object(clean(rec))


@bp.get("/school-meals/applications")
def list_applications():
    require_role({"SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    hh_f = request.args.get("household_id")
    items = list(db.meal_applications.values())
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    if hh_f is not None:
        items = [a for a in items if a["household_id"] == hh_f]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array([clean(r) for r in page], limit=limit, offset=offset, total_count=total)


# ------------------------- Transitions ------------------------------

def _expect_status(app, expected):
    if app["status"] != expected:
        if isinstance(expected, (set, list, tuple)):
            if app["status"] not in expected:
                raise_err(ERR_INVALID_STATE, f"application status is {app['status']}, expected one of {expected}")
        else:
            raise_err(ERR_INVALID_STATE, f"application status is {app['status']}, expected {expected}")


@bp.post("/school-meals/applications/<aid>/submit")
def submit_application(aid):
    user_id, role = require_role({"Parent"})
    app = get_or_404(db.meal_applications, aid, "MealApplication")
    if user_id != app["household_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this application")
    if app["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, f"application status is {app['status']}, expected DRAFT")
    body = get_json_body()
    enforce_keys(body, required=set(), optional=set())
    household = db.households[app["household_id"]]
    if household.get("annual_income_cents") is None or household.get("family_size") is None:
        raise_err(ERR_HOUSEHOLD_INCOMPLETE, "household income/family_size incomplete")
    app["snapshot_family_size"] = household["family_size"]
    app["snapshot_annual_income_cents"] = household["annual_income_cents"]
    app["snapshot_address_state"] = household["address_state"]
    app["status"] = "SUBMITTED"
    bump_version(app)
    return success_object(clean(app))


@bp.post("/school-meals/applications/<aid>/start-review")
def start_review(aid):
    require_role({"SchoolStaff", "DistrictReviewer"})
    app = get_or_404(db.meal_applications, aid, "MealApplication")
    if app["status"] not in ("SUBMITTED", "APPEALED"):
        raise_err(ERR_INVALID_STATE, f"application status is {app['status']}, expected SUBMITTED or APPEALED")
    body = get_json_body()
    enforce_keys(body, required=set(), optional=set())
    app["status"] = "UNDER_REVIEW"
    bump_version(app)
    return success_object(clean(app))


@bp.post("/school-meals/applications/<aid>/approve")
def approve_application(aid):
    require_role({"DistrictReviewer"})
    app = get_or_404(db.meal_applications, aid, "MealApplication")
    if app["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, f"application status is {app['status']}, expected UNDER_REVIEW")
    body = get_json_body()
    enforce_keys(body, required={"decision_reason"}, optional=set())
    require_str(body["decision_reason"], "decision_reason")

    # Tier calc on snapshots, with current direct_certification_flag at approval time.
    household = db.households[app["household_id"]]
    tier = determine_tier_from_income(
        app["snapshot_annual_income_cents"],
        app["snapshot_family_size"],
        app["snapshot_address_state"],
        bool(household.get("direct_certification_flag", False)),
    )

    n = now()
    valid_to = school_year_end_plus_carryover(app["school_year"])

    # Cascade: supersede prior ACTIVE determinations for this household.
    superseded_ids = []
    for det in db.eligibility_determinations.values():
        if det["household_id"] == app["household_id"] and det["lifecycle_status"] == "ACTIVE":
            det["lifecycle_status"] = "SUPERSEDED"
            det["valid_to_utc"] = iso_utc(n)
            det["_valid_to_dt"] = n
            bump_version(det)
            superseded_ids.append(det["id"])

    # Enforce overlap rule on the new determination (validation priority 8).
    _check_overlap(app["household_id"], n, valid_to)

    # Create new determination.
    new_det = {
        **common_fields_init(),
        "household_id": app["household_id"],
        "source_application_id": app["id"],
        "source": "APPLICATION",
        "tier": tier,
        "lifecycle_status": "ACTIVE",
        "verification_status": "UNVERIFIED",
        "valid_from_utc": iso_utc(n),
        "valid_to_utc": iso_utc(valid_to),
        "_valid_from_dt": n,
        "_valid_to_dt": valid_to,
    }
    db.eligibility_determinations[new_det["id"]] = new_det

    # Re-bind PENDING transactions tied to superseded determinations.
    household_student_ids = {s["id"] for s in db.students.values() if s["household_id"] == app["household_id"]}
    for txn in db.service_transactions.values():
        if txn["status"] != "PENDING":
            continue
        if txn["student_id"] not in household_student_ids:
            continue
        if txn["eligibility_determination_id"] not in superseded_ids:
            continue
        # Recompute paid_charge_cents with the new determination's tier.
        menu = db.menu_items.get(txn["menu_item_id"])
        student = db.students.get(txn["student_id"])
        profile = _profile_for_student(student["id"]) if student else None
        student_allergens = profile["allergens"] if profile else []
        new_charge = compute_paid_charge(
            tier,
            menu["list_price_cents"] if menu else 0,
            menu["allergens_present"] if menu else [],
            student_allergens,
            bool(txn.get("substitute_for_allergen", False)),
        )
        txn["eligibility_determination_id"] = new_det["id"]
        txn["applied_tier"] = tier
        txn["paid_charge_cents"] = new_charge
        bump_version(txn)

    app["status"] = "APPROVED"
    app["decision_reason"] = body["decision_reason"]
    bump_version(app)
    return success_object(clean(app))


def _profile_for_student(student_id):
    for ap in db.allergy_profiles.values():
        if ap["student_id"] == student_id:
            return ap
    return None


def _check_overlap(household_id, new_from, new_to):
    """Half-open [from, to) overlap test against all OTHER determinations for the household."""
    for det in db.eligibility_determinations.values():
        if det["household_id"] != household_id:
            continue
        # We compare against ALL existing determinations for this household, regardless
        # of lifecycle_status, per the strict half-open non-overlap rule in §3.4.
        a_from = det["_valid_from_dt"]
        a_to = det["_valid_to_dt"]
        # overlap if a_from < new_to AND new_from < a_to
        if a_from < new_to and new_from < a_to:
            raise_err(ERR_ELIGIBILITY_OVERLAP, "eligibility window overlaps existing determination")


@bp.post("/school-meals/applications/<aid>/deny")
def deny_application(aid):
    require_role({"DistrictReviewer"})
    app = get_or_404(db.meal_applications, aid, "MealApplication")
    if app["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, f"application status is {app['status']}, expected UNDER_REVIEW")
    body = get_json_body()
    enforce_keys(body, required={"decision_reason"}, optional=set())
    require_str(body["decision_reason"], "decision_reason")
    app["status"] = "DENIED"
    app["decision_reason"] = body["decision_reason"]
    bump_version(app)
    return success_object(clean(app))


@bp.post("/school-meals/applications/<aid>/appeal")
def appeal_application(aid):
    user_id, role = require_role({"Parent"})
    app = get_or_404(db.meal_applications, aid, "MealApplication")
    if user_id != app["household_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this application")
    if app["status"] != "DENIED":
        raise_err(ERR_INVALID_STATE, f"application status is {app['status']}, expected DENIED")
    body = get_json_body()
    enforce_keys(body, required={"appeal_reason", "expected_mealapplication_version"}, optional=set())
    require_str(body["appeal_reason"], "appeal_reason")
    require_int(body["expected_mealapplication_version"], "expected_mealapplication_version", min_val=0)
    if body["expected_mealapplication_version"] != app["version"]:
        raise_err(ERR_STALE_VERSION, "expected_mealapplication_version does not match")
    app["status"] = "APPEALED"
    app["appeal_reason"] = body["appeal_reason"]
    bump_version(app)
    return success_object(clean(app))


@bp.post("/school-meals/applications/<aid>/withdraw")
def withdraw_application(aid):
    user_id, role = require_role({"Parent"})
    app = get_or_404(db.meal_applications, aid, "MealApplication")
    if user_id != app["household_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this application")
    if app["status"] not in ("DRAFT", "SUBMITTED"):
        raise_err(ERR_INVALID_STATE, f"application status is {app['status']}, expected DRAFT or SUBMITTED")
    body = get_json_body()
    enforce_keys(body, required=set(), optional=set())
    app["status"] = "WITHDRAWN"
    bump_version(app)
    return success_object(clean(app))
