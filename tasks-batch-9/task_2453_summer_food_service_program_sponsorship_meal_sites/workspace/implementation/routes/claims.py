"""Monthly meal claims, line items, edit checks, payment and revision.

PRD sec 3.8.
"""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.common import require_owner, require_state
from services import cascades
from services import calculations as calc
from services import lookup
from services import serializers as ser

bp = Blueprint("claims", __name__)

REVIEWER = mw.ROLE_STATE_AGENCY_REVIEWER
SPONSOR_ADMIN = mw.ROLE_SPONSOR_ADMIN

CLAIM_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "VALIDATED",
    "EDIT_CHECK_FAILED",
    "PAID",
    "REVISION_OPENED",
)
EDIT_CHECK_STATUSES = ("PENDING", "PASSED", "FAILED")
DISALLOW_REASONS = (
    "NONE",
    "MISSING_MONITORING",
    "FOOD_SAFETY_BREACH",
    "EXCEEDS_PRODUCTION",
)
PRELIMINARY_STATUSES = ("DRAFT", "SUBMITTED", "REVISION_OPENED")


# --------------------------------------------------------------------------
# Aggregation helpers
# --------------------------------------------------------------------------
def _finalized_days(site_id, claim_month):
    prefix = claim_month + "-"
    days = [
        day
        for day in db.store.days.values()
        if day["site_id"] == site_id
        and day["status"] == "FINALIZED"
        and str(day["service_date"]).startswith(prefix)
    ]
    days.sort(key=lambda day: (day["service_date"], day["_seq"]))
    return days


def _aggregate_line(line, site, claim_month):
    """Re-derive the line's day count and per-type claimed meals."""
    days = _finalized_days(site["id"], claim_month)
    first_map = {}
    second_map = {}
    for day in days:
        per_type = calc.classify_day(day, site)["per_type"]
        for meal_type, (first, second) in per_type.items():
            first_map[meal_type] = first_map.get(meal_type, 0) + first
            second_map[meal_type] = second_map.get(meal_type, 0) + second
    keys = sorted(set(first_map) | set(second_map))
    line["finalized_day_count"] = len(days)
    line["claimed_first_meals_by_type"] = {key: first_map.get(key, 0) for key in keys}
    line["claimed_second_meals_by_type"] = {key: second_map.get(key, 0) for key in keys}
    line["meals_rate_value_cents"] = calc.line_meals_rate_value(line)
    return days


def _recompute_claim_meals(claim):
    total = 0
    for line in lookup.claim_line_items(claim["id"]):
        total += line["meals_rate_value_cents"] or 0
    claim["meals_rate_value_cents"] = total
    return total


# --------------------------------------------------------------------------
# Claim creation and reads
# --------------------------------------------------------------------------
@bp.post("/sfsp/meal-claims")
@mw.endpoint([SPONSOR_ADMIN])
def create_claim():
    body = mw.json_body()
    sponsor_id = mw.field_str(body, "sponsor_id")
    claim_month = mw.field_month(body, "claim_month")
    expected_version = mw.field_int(body, "expected_sponsor_version", minimum=0)

    sponsor = lookup.require_sponsor(sponsor_id)
    require_owner(sponsor["id"])
    require_state(
        sponsor["application_status"] == "APPROVED", "ERR_SPONSOR_NOT_APPROVED"
    )
    if expected_version != sponsor["version"]:
        raise ApiError("ERR_STALE_SPONSOR_VERSION")

    for existing in db.store.claims.values():
        if (
            existing["sponsor_id"] == sponsor["id"]
            and existing["claim_month"] == claim_month
        ):
            raise ApiError("ERR_DUPLICATE_CLAIM_MONTH")

    year, month = db.parse_year_month(claim_month)
    deadline_year, deadline_month = db.add_months(year, month, 2)
    deadline = db.last_day_of_month(deadline_year, deadline_month)

    claim = db.new_row(
        {
            "sponsor_id": sponsor["id"],
            "claim_month": claim_month,
            "status": "DRAFT",
            "revision_round": 0,
            "claimed_operating_cost_cents": None,
            "claimed_admin_cost_cents": None,
            "meals_rate_value_cents": 0,
            "preliminary_reimbursement_cents": None,
            "final_reimbursement_cents": None,
            "advance_offset_cents": None,
            "net_payable_cents": None,
            "disallowed_meal_count": 0,
            "blocking_hold_count": 0,
            "edit_check_failure_codes": None,
            "deadline_date": db.date_iso(deadline),
            "is_late": False,
            "submitted_at": None,
            "paid_at": None,
            "_allocations": [],
        }
    )
    db.store.claims[claim["id"]] = claim
    db.touch(sponsor)
    return response.created_response(ser.meal_claim(claim))


@bp.get("/sfsp/meal-claims/<claim_id>")
@mw.endpoint([SPONSOR_ADMIN, REVIEWER])
def get_claim(claim_id):
    claim = lookup.require_claim(claim_id)
    return response.object_response(ser.meal_claim(claim))


@bp.get("/sfsp/meal-claims")
@mw.endpoint([SPONSOR_ADMIN, REVIEWER])
def list_claims():
    limit, offset = mw.pagination()
    sponsor_id = mw.query_value("sponsor_id")
    claim_month = mw.query_month("claim_month")
    status = mw.query_enum("status", CLAIM_STATUSES)

    rows = []
    for claim in db.store.claims.values():
        if sponsor_id is not None and claim["sponsor_id"] != sponsor_id:
            continue
        if claim_month is not None and claim["claim_month"] != claim_month:
            continue
        if status is not None and claim["status"] != status:
            continue
        rows.append(claim)
    return response.paginate(rows, limit, offset, ser.meal_claim)


# --------------------------------------------------------------------------
# Line items
# --------------------------------------------------------------------------
@bp.post("/sfsp/meal-claims/<claim_id>/line-items")
@mw.endpoint([SPONSOR_ADMIN])
def add_line_item(claim_id):
    body = mw.json_body()
    site_id = mw.field_str(body, "site_id")

    # Existence order of PRD sec 2.6 step 4: site precedes claim.
    site = lookup.require_site(site_id)
    claim = lookup.require_claim(claim_id)
    require_owner(claim["sponsor_id"])
    require_state(
        claim["status"] in ("DRAFT", "REVISION_OPENED"), "ERR_CLAIM_STATE_INVALID"
    )

    if site["sponsor_id"] != claim["sponsor_id"]:
        raise ApiError("ERR_SITE_SPONSOR_MISMATCH")

    for existing in lookup.claim_line_items(claim["id"]):
        if existing["site_id"] == site["id"]:
            raise ApiError("ERR_DUPLICATE_CLAIM_LINE_ITEM")

    days = _finalized_days(site["id"], claim["claim_month"])
    if not days:
        raise ApiError("ERR_NO_FINALIZED_DAYS")

    line = db.new_row(
        {
            "meal_claim_id": claim["id"],
            "site_id": site["id"],
            "rate_class": calc.rate_class_for_site(site),
            "finalized_day_count": 0,
            "claimed_first_meals_by_type": {},
            "claimed_second_meals_by_type": {},
            "disallowed_counts_by_type": None,
            "meals_rate_value_cents": 0,
            "disallowed_meal_count": 0,
            "edit_check_status": "PENDING",
            "disallow_reason": "NONE",
            "hold_flag": bool(site["claim_hold"]),
        }
    )
    _aggregate_line(line, site, claim["claim_month"])
    db.store.line_items[line["id"]] = line

    _recompute_claim_meals(claim)
    claim["blocking_hold_count"] = sum(
        1 for row in lookup.claim_line_items(claim["id"]) if row["hold_flag"]
    )
    db.touch(claim)

    return response.created_response(ser.claim_line_item(line))


@bp.get("/sfsp/claim-line-items/<line_item_id>")
@mw.endpoint([SPONSOR_ADMIN, REVIEWER])
def get_line_item(line_item_id):
    line = lookup.require_line_item(line_item_id)
    return response.object_response(ser.claim_line_item(line))


@bp.get("/sfsp/claim-line-items")
@mw.endpoint([SPONSOR_ADMIN, REVIEWER])
def list_line_items():
    limit, offset = mw.pagination()
    claim_id = mw.query_value("meal_claim_id")
    site_id = mw.query_value("site_id")
    edit_check_status = mw.query_enum("edit_check_status", EDIT_CHECK_STATUSES)
    disallow_reason = mw.query_enum("disallow_reason", DISALLOW_REASONS)

    rows = []
    for line in db.store.line_items.values():
        if claim_id is not None and line["meal_claim_id"] != claim_id:
            continue
        if site_id is not None and line["site_id"] != site_id:
            continue
        if edit_check_status is not None and line["edit_check_status"] != edit_check_status:
            continue
        if disallow_reason is not None and line["disallow_reason"] != disallow_reason:
            continue
        rows.append(line)
    return response.paginate(rows, limit, offset, ser.claim_line_item)


# --------------------------------------------------------------------------
# Submission
# --------------------------------------------------------------------------
@bp.post("/sfsp/meal-claims/<claim_id>/submit")
@mw.endpoint([SPONSOR_ADMIN])
def submit_claim(claim_id):
    body = mw.json_body()
    operating_cents = mw.field_int(body, "claimed_operating_cost_cents", minimum=0)
    admin_cents = mw.field_int(body, "claimed_admin_cost_cents", minimum=0)

    claim = lookup.require_claim(claim_id)
    require_owner(claim["sponsor_id"])
    require_state(
        claim["status"] in ("DRAFT", "REVISION_OPENED"), "ERR_CLAIM_STATE_INVALID"
    )
    sponsor = lookup.require_sponsor(claim["sponsor_id"])

    lines = lookup.claim_line_items(claim["id"])
    if not lines:
        raise ApiError("ERR_CLAIM_HAS_NO_LINE_ITEMS")
    if (claim["blocking_hold_count"] or 0) != 0:
        raise ApiError("ERR_CLAIM_HOLD_BLOCKING")

    year, _month = db.parse_year_month(claim["claim_month"])
    budget = lookup.approved_budget_for(sponsor, prefer_year=year)
    if budget is None:
        raise ApiError("ERR_BUDGET_NOT_APPROVED")
    if operating_cents > (budget["approved_operating_cost_cents"] or 0):
        raise ApiError("ERR_OPERATING_COST_EXCEEDS_BUDGET")
    if admin_cents > (budget["approved_admin_cost_cents"] or 0):
        raise ApiError("ERR_ADMIN_COST_EXCEEDS_BUDGET")

    previous = claim["status"]

    # Re-aggregate every line so days finalized since the last submission count.
    for line in lines:
        site = db.store.sites[line["site_id"]]
        before = dict(line)
        _aggregate_line(line, site, claim["claim_month"])
        if (
            before["finalized_day_count"] != line["finalized_day_count"]
            or before["claimed_first_meals_by_type"] != line["claimed_first_meals_by_type"]
            or before["claimed_second_meals_by_type"]
            != line["claimed_second_meals_by_type"]
            or before["meals_rate_value_cents"] != line["meals_rate_value_cents"]
        ):
            db.touch(line)

    claim["claimed_operating_cost_cents"] = operating_cents
    claim["claimed_admin_cost_cents"] = admin_cents
    claim["status"] = "SUBMITTED"
    claim["submitted_at"] = db.clock.now_iso()
    claim["is_late"] = db.clock.today() > db.parse_date(claim["deadline_date"])
    _recompute_claim_meals(claim)
    claim["preliminary_reimbursement_cents"] = calc.preliminary_reimbursement(claim)
    if previous == "REVISION_OPENED":
        claim["revision_round"] = (claim["revision_round"] or 0) + 1
    db.touch(claim)

    return response.object_response(ser.meal_claim(claim))


# --------------------------------------------------------------------------
# Edit checks
# --------------------------------------------------------------------------
def _first_week_satisfied(site_id):
    for visit in lookup.site_visits(site_id):
        if visit["visit_type"] != "FIRST_WEEK":
            continue
        if visit["status"] not in ("CONDUCTED", "REPORT_FILED", "CLOSED"):
            continue
        due_date = db.parse_date(visit["due_date"])
        conducted = db.parse_datetime(visit["conducted_at"])
        if due_date is None or conducted is None:
            continue
        if conducted.date() <= due_date:
            return True
    return False


def _evaluate_line(line, site, claim_month):
    """Returns (reason, disallowed_counts_by_type) for the first rule that fires."""
    days = _finalized_days(site["id"], claim_month)
    first_map = line["claimed_first_meals_by_type"] or {}
    second_map = line["claimed_second_meals_by_type"] or {}

    # Rule 1 — the whole line comes out.
    if not _first_week_satisfied(site["id"]):
        counts = {
            meal_type: (first_map.get(meal_type) or 0) + (second_map.get(meal_type) or 0)
            for meal_type in sorted(first_map)
        }
        return ("MISSING_MONITORING", counts)

    # Rule 2 — only the breaching days lose their meals.
    breaching = [day for day in days if day["food_safety_status"] == "BREACH"]
    if breaching:
        counts = {}
        for day in breaching:
            per_type = calc.classify_day(day, site)["per_type"]
            for meal_type, (first, second) in per_type.items():
                counts[meal_type] = counts.get(meal_type, 0) + first + second
        return ("FOOD_SAFETY_BREACH", {key: counts[key] for key in sorted(counts)})

    # Rule 3 — vended sites only: claimed meals above the delivered quantity.
    if site["production_mode"] == "VENDED":
        counts = {}
        total = 0
        for day in days:
            per_type = calc.classify_day(day, site)["per_type"]
            production = day["production_counts"] or {}
            for service in day["meal_services"] or []:
                meal_type = service["meal_type"]
                first, second = per_type.get(meal_type, (0, 0))
                excess = first + second - (production.get(meal_type) or 0)
                if excess > 0:
                    counts[meal_type] = counts.get(meal_type, 0) + excess
                    total += excess
        if total > 0:
            return ("EXCEEDS_PRODUCTION", {key: counts[key] for key in sorted(counts)})

    return ("NONE", {})


@bp.post("/sfsp/meal-claims/<claim_id>/edit-check")
@mw.endpoint([REVIEWER])
def edit_check(claim_id):
    claim = lookup.require_claim(claim_id)
    require_state(claim["status"] == "SUBMITTED", "ERR_CLAIM_STATE_INVALID")

    failing_reasons = []
    flagged_sites = []
    for line in lookup.claim_line_items(claim["id"]):
        site = db.store.sites[line["site_id"]]
        reason, counts = _evaluate_line(line, site, claim["claim_month"])
        changes = {
            "disallow_reason": reason,
            "edit_check_status": "PASSED" if reason == "NONE" else "FAILED",
            "disallowed_counts_by_type": counts,
            "disallowed_meal_count": sum(counts.values()),
        }
        line.update(changes)
        line["meals_rate_value_cents"] = calc.line_meals_rate_value(line)
        db.touch(line)
        if reason != "NONE":
            if reason not in failing_reasons:
                failing_reasons.append(reason)
            if reason in ("EXCEEDS_PRODUCTION", "MISSING_MONITORING"):
                flagged_sites.append(site)

    lines = lookup.claim_line_items(claim["id"])
    _recompute_claim_meals(claim)
    claim["disallowed_meal_count"] = sum(
        (line["disallowed_meal_count"] or 0) for line in lines
    )
    claim["status"] = "VALIDATED" if not failing_reasons else "EDIT_CHECK_FAILED"
    claim["edit_check_failure_codes"] = sorted(failing_reasons)
    claim["final_reimbursement_cents"] = calc.final_reimbursement_breakdown(claim)[
        "gross_cents"
    ]
    db.touch(claim)

    # Two-hop compliance cascade: count every flag first, then trip thresholds.
    for site in flagged_sites:
        site["compliance_flag_count"] = (site["compliance_flag_count"] or 0) + 1
        db.touch(site)
    for site in flagged_sites:
        if site["compliance_flag_count"] == calc.COMPLIANCE_FLAG_THRESHOLD:
            cascades.create_corrective_action(
                site,
                severity="MAJOR",
                finding_code="COMPLIANCE_FLAG_THRESHOLD",
                origin="COMPLIANCE_FLAG",
                opened_by_user_id="SYSTEM",
                monitoring_visit_id=None,
            )
            cascades.raise_claim_hold(site)

    return response.object_response(ser.meal_claim(claim))


# --------------------------------------------------------------------------
# Payment and the advance recovery waterfall
# --------------------------------------------------------------------------
def _recovery_candidates(sponsor_id):
    candidates = [
        advance
        for advance in db.store.advances.values()
        if advance["sponsor_id"] == sponsor_id
        and advance["status"] in ("DISBURSED", "PARTIALLY_RECOVERED", "DEMAND_ISSUED")
        and ser.raw_outstanding(advance) > 0
    ]
    candidates.sort(
        key=lambda advance: (
            advance["request_month"],
            advance["created_at"],
            advance["_seq"],
        )
    )
    return candidates


@bp.post("/sfsp/meal-claims/<claim_id>/pay")
@mw.endpoint([REVIEWER])
def pay_claim(claim_id):
    claim = lookup.require_claim(claim_id)
    require_state(claim["status"] == "VALIDATED", "ERR_CLAIM_STATE_INVALID")
    require_state(claim["final_reimbursement_cents"] is not None, "ERR_CLAIM_STATE_INVALID")
    sponsor = lookup.require_sponsor(claim["sponsor_id"])

    remaining = claim["final_reimbursement_cents"]
    offset = 0
    allocations = []
    for advance in _recovery_candidates(sponsor["id"]):
        if remaining <= 0:
            break
        outstanding = ser.raw_outstanding(advance)
        amount = outstanding if outstanding < remaining else remaining
        if amount <= 0:
            continue
        advance["recovered_amount_cents"] = (
            advance["recovered_amount_cents"] or 0
        ) + amount
        if amount == outstanding:
            advance["status"] = "RECOVERED"
        elif advance["status"] == "DISBURSED":
            advance["status"] = "PARTIALLY_RECOVERED"
        db.touch(advance)
        allocations.append({"advance_id": advance["id"], "amount": amount})
        offset += amount
        remaining -= amount

    claim["advance_offset_cents"] = offset
    claim["net_payable_cents"] = claim["final_reimbursement_cents"] - offset
    claim["status"] = "PAID"
    claim["paid_at"] = db.clock.now_iso()
    claim["_allocations"] = allocations
    db.touch(claim)
    db.touch(sponsor)

    return response.object_response(ser.meal_claim(claim))


# --------------------------------------------------------------------------
# Reopening
# --------------------------------------------------------------------------
def _reset_lines(claim):
    for line in lookup.claim_line_items(claim["id"]):
        line["edit_check_status"] = "PENDING"
        line["disallow_reason"] = "NONE"
        line["disallowed_counts_by_type"] = None
        line["disallowed_meal_count"] = 0
        line["meals_rate_value_cents"] = calc.line_meals_rate_value(line)
        db.touch(line)
    _recompute_claim_meals(claim)
    claim["disallowed_meal_count"] = 0


def _restored_advance_status(advance):
    outstanding = ser.raw_outstanding(advance)
    if advance["demand_issued_at"] is not None and outstanding > 0:
        return "DEMAND_ISSUED"
    if outstanding == 0:
        return "RECOVERED"
    if (advance["recovered_amount_cents"] or 0) > 0:
        return "PARTIALLY_RECOVERED"
    return "DISBURSED"


@bp.post("/sfsp/meal-claims/<claim_id>/open-revision")
@mw.endpoint([REVIEWER])
def open_revision(claim_id):
    body = mw.json_body()
    reason = mw.field_str(body, "reason", required=False)

    claim = lookup.require_claim(claim_id)
    require_state(
        claim["status"] in ("EDIT_CHECK_FAILED", "PAID"), "ERR_CLAIM_STATE_INVALID"
    )
    if claim["status"] == "PAID" and reason is None:
        mw.bad_request("Field 'reason' is required to reopen a paid claim.")

    if claim["status"] == "EDIT_CHECK_FAILED":
        claim["status"] = "DRAFT"
        claim["revision_round"] = (claim["revision_round"] or 0) + 1
        claim["submitted_at"] = None
        claim["preliminary_reimbursement_cents"] = None
        claim["final_reimbursement_cents"] = None
        claim["edit_check_failure_codes"] = None
        db.touch(claim)
        _reset_lines(claim)
        return response.object_response(ser.meal_claim(claim))

    # PAID -> REVISION_OPENED, undoing the payment exactly.
    sponsor = lookup.require_sponsor(claim["sponsor_id"])
    claim["status"] = "REVISION_OPENED"
    claim["revision_round"] = (claim["revision_round"] or 0) + 1
    db.touch(claim)
    _reset_lines(claim)

    for allocation in reversed(claim["_allocations"] or []):
        advance = db.store.advances.get(allocation["advance_id"])
        if advance is None:
            continue
        advance["recovered_amount_cents"] = (
            advance["recovered_amount_cents"] or 0
        ) - allocation["amount"]
        advance["status"] = _restored_advance_status(advance)
        db.touch(advance)
    claim["_allocations"] = []
    db.touch(sponsor)

    claim["advance_offset_cents"] = None
    claim["net_payable_cents"] = None
    claim["paid_at"] = None
    claim["final_reimbursement_cents"] = None
    db.touch(claim)

    return response.object_response(ser.meal_claim(claim))


# --------------------------------------------------------------------------
# Reimbursement summary
# --------------------------------------------------------------------------
@bp.get("/sfsp/meal-claims/<claim_id>/reimbursement-summary")
@mw.endpoint([SPONSOR_ADMIN, REVIEWER])
def reimbursement_summary(claim_id):
    claim = lookup.require_claim(claim_id)
    breakdown = calc.final_reimbursement_breakdown(claim)
    variant = "PRELIMINARY" if claim["status"] in PRELIMINARY_STATUSES else "FINAL"
    return response.object_response(
        {
            "claim_id": claim["id"],
            "status": claim["status"],
            "variant": variant,
            "meals_rate_value_cents": breakdown["meals_rate_value_cents"],
            "operating_reimbursement_cents": breakdown["operating_reimbursement_cents"],
            "admin_cap_cents": breakdown["admin_cap_cents"],
            "admin_reimbursement_cents": breakdown["admin_reimbursement_cents"],
            "preliminary_reimbursement_cents": claim["preliminary_reimbursement_cents"],
            "final_reimbursement_cents": claim["final_reimbursement_cents"],
            "advance_offset_cents": claim["advance_offset_cents"],
            "net_payable_cents": claim["net_payable_cents"],
            "disallowed_meal_count": claim["disallowed_meal_count"],
        }
    )
