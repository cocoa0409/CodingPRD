"""Claim endpoints (PRD 3.7, 3.8)."""
from flask import Blueprint

import calc
import lookup
import recompute
from db import by_policy, by_project, new_row, ordered, store, touch
from enums import ADJUSTMENT_BASES, ADJUSTMENT_STATUSES, ADJUST_OUTCOMES, PART_TYPES, \
    PAYMENT_STATUSES, PERILS
from errors import ApiError
from middleware import authenticate, body, filter_enum, filter_str, get_dt, get_enum, \
    get_int, get_str, pagination, paginate, present
from response import created, ok, ok_list

bp = Blueprint("claims", __name__)

ADJUSTABLE_STATUSES = ("REPORTED", "ADJUSTED", "REOPENED")


@bp.post("/claims")
def report_claim():
    authenticate("ClaimAdjuster")
    payload = body()
    policy = lookup.fk_policy(payload)
    peril = get_enum(payload, "peril", PERILS)
    loss_date = get_dt(payload, "loss_date")
    description = get_str(payload, "description")
    if policy["status"] != "IN_FORCE":
        raise ApiError(
            "ERR_INVALID_POLICY_STATE", "First notice of loss requires an IN_FORCE policy."
        )
    if loss_date < policy["term_start_date"] or loss_date > policy["term_end_date"]:
        raise ApiError(
            "ERR_LOSS_DATE_OUTSIDE_TERM", "loss_date must fall inside the policy term."
        )
    row = new_row()
    row.update({
        "policy_id": policy["id"],
        "peril": peril,
        "loss_date": loss_date,
        "description": description,
        "reported_at": store.now(),
        "adjustment_status": "REPORTED",
        "payment_status": "UNPAID",
        "adjustment_basis": None,
        "continuing_pm_weeks": 0,
        "allocation_lines": [],
        "indemnity_cents": 0,
        "uncovered_cents": 0,
        "delay_days_indemnified": 0,
        "paid_cents": 0,
        "outstanding_reserve_cents": 0,
        "total_incurred_cents": 0,
        "adjusted_by_user_id": None,
        "reopen_count": 0,
    })
    store.claims[row["id"]] = row
    return created(row)


def _parse_loss_items(payload, peril):
    """loss_items must be non-empty for every peril other than DELAY (PRD 2.11 step 8)."""
    raw = payload.get("loss_items")
    if peril == "DELAY":
        return []
    if raw is None or not isinstance(raw, list) or len(raw) == 0:
        raise ApiError("ERR_INVALID_REQUEST", "loss_items must be a non-empty array.")
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Each loss item must be an object.")
        part_type = get_enum(entry, "part_type", PART_TYPES)
        gross_loss_cents = get_int(entry, "gross_loss_cents", minimum=0)
        items.append({"part_type": part_type, "gross_loss_cents": gross_loss_cents})
    return items


def _testing_notice_covers(project_id, loss_date):
    for notice in store.notices.values():
        if notice["project_id"] != project_id or notice["status"] != "APPROVED":
            continue
        if notice["window_start"] <= loss_date < notice["window_end"]:
            return True
    return False


def _storage_approved_at(policy_id, loss_date):
    for row in by_policy(store.assignments, policy_id):
        if not (row["window_start"] <= loss_date < row["window_end"]):
            continue
        if row["status"] == "APPROVED":
            return True
        if row["status"] == "RELEASED" and row["released_at"] is not None \
                and row["released_at"] > loss_date:
            return True
    return False


@bp.post("/claims/<claim_id>/adjust")
def adjust_claim(claim_id):
    user_id, _role = authenticate("ClaimAdjuster")
    claim = lookup.claim(claim_id)
    payload = body()
    outcome = get_enum(payload, "outcome", ADJUST_OUTCOMES)
    adjustment_basis = None
    continuing_pm_weeks = 0
    items = []
    if outcome == "ADJUST":
        adjustment_basis = get_enum(payload, "adjustment_basis", ADJUSTMENT_BASES)
        continuing_pm_weeks = get_int(
            payload, "continuing_pm_weeks", required=False, default=0, minimum=0, maximum=12
        )
        items = _parse_loss_items(payload, claim["peril"])
    if claim["adjustment_status"] not in ADJUSTABLE_STATUSES:
        raise ApiError(
            "ERR_INVALID_CLAIM_STATE", "This claim is not in an adjustable adjustment_status."
        )
    if claim["adjustment_status"] == "ADJUSTED" and claim["payment_status"] != "UNPAID":
        raise ApiError(
            "ERR_INVALID_CLAIM_STATE",
            "A re-adjustment requires the payment axis to still read UNPAID.",
        )
    policy = store.policies[claim["policy_id"]]
    if policy["status"] != "IN_FORCE":
        raise ApiError("ERR_INVALID_POLICY_STATE", "Adjustment requires an IN_FORCE policy.")
    project = store.projects[policy["project_id"]]
    parts_by_type = {
        part["part_type"]: part
        for part in by_policy(store.coverage_parts, policy["id"]) if part["status"] == "ACTIVE"
    }
    if outcome == "DENY":
        claim["adjustment_status"] = "DENIED"
        claim["allocation_lines"] = []
        claim["indemnity_cents"] = 0
        claim["uncovered_cents"] = 0
        claim["delay_days_indemnified"] = 0
        claim["outstanding_reserve_cents"] = claim["indemnity_cents"] - claim["paid_cents"]
        claim["total_incurred_cents"] = claim["paid_cents"] + claim["outstanding_reserve_cents"]
        touch(claim)
        recompute.recompute_audit_risk_score(project)
        touch(project)
        return ok(claim)

    seen = set()
    for item in items:
        if item["part_type"] in seen:
            raise ApiError(
                "ERR_DUPLICATE_LOSS_ITEM", "Two loss items may not name the same part_type."
            )
        seen.add(item["part_type"])
    for item in items:
        if item["part_type"] not in parts_by_type:
            raise ApiError(
                "ERR_COVERAGE_PART_MISSING",
                "Every loss item must match an ACTIVE coverage part of the policy.",
            )
    delay_days = 0
    if claim["peril"] == "DELAY":
        if project["actual_substantial_completion_date"] is None \
                or "DELAY_IN_COMPLETION" not in parts_by_type:
            raise ApiError(
                "ERR_PROJECT_NOT_COMPLETE",
                "A DELAY claim requires a substantially complete project and a delay part.",
            )
    if claim["peril"] == "TESTING_FAILURE" or "TESTING_COMMISSIONING" in seen:
        if not _testing_notice_covers(project["id"], claim["loss_date"]):
            raise ApiError(
                "ERR_TESTING_NOTICE_REQUIRED",
                "An APPROVED testing notice covering the loss date is required.",
            )
    if "TEMPORARY_STORAGE" in seen:
        if not _storage_approved_at(policy["id"], claim["loss_date"]):
            raise ApiError(
                "ERR_STORAGE_NOT_APPROVED",
                "The materials were not in approved off-site storage at the loss date.",
            )
    if claim["peril"] == "DELAY":
        delay_days, gross_delay_cents = calc.delay_indemnity(policy, project)
        items = [{"part_type": "DELAY_IN_COMPLETION", "gross_loss_cents": gross_delay_cents}]
    lines, indemnity_cents, uncovered_cents = calc.run_waterfall(
        policy, parts_by_type, items, adjustment_basis, continuing_pm_weeks
    )
    claim["allocation_lines"] = lines
    claim["indemnity_cents"] = indemnity_cents
    claim["uncovered_cents"] = uncovered_cents
    claim["delay_days_indemnified"] = delay_days
    claim["adjustment_basis"] = adjustment_basis
    claim["continuing_pm_weeks"] = continuing_pm_weeks
    claim["adjusted_by_user_id"] = user_id
    claim["outstanding_reserve_cents"] = indemnity_cents - claim["paid_cents"]
    claim["total_incurred_cents"] = claim["paid_cents"] + claim["outstanding_reserve_cents"]
    if indemnity_cents > 0 or claim["adjustment_status"] == "ADJUSTED":
        # A re-adjustment that recomputes to zero indemnity stays ADJUSTED; the denial
        # branch is reachable only out of REPORTED or REOPENED (PRD 3.7).
        claim["adjustment_status"] = "ADJUSTED"
    else:
        claim["adjustment_status"] = "DENIED"
    touch(claim)
    recompute.recompute_audit_risk_score(project)
    touch(project)
    return ok(claim)


@bp.post("/claims/<claim_id>/settle")
def settle_claim(claim_id):
    user_id, _role = authenticate("ClaimAdjuster", "UnderwritingManager")
    claim = lookup.claim(claim_id)
    if claim["adjusted_by_user_id"] is not None and claim["adjusted_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "The adjusting user may not settle the same claim."
        )
    if claim["adjustment_status"] != "ADJUSTED" or claim["indemnity_cents"] <= 0:
        raise ApiError(
            "ERR_INVALID_CLAIM_STATE",
            "Settlement requires an ADJUSTED claim with positive indemnity.",
        )
    claim["adjustment_status"] = "SETTLED"
    touch(claim)
    return ok(claim)


@bp.post("/claims/<claim_id>/reopen")
def reopen_claim(claim_id):
    authenticate("ClaimAdjuster")
    claim = lookup.claim(claim_id)
    if claim["adjustment_status"] not in ("CLOSED", "DENIED"):
        raise ApiError("ERR_INVALID_CLAIM_STATE", "Only a CLOSED or DENIED claim may be reopened.")
    if claim["reopen_count"] >= 2:
        raise ApiError("ERR_REOPEN_LIMIT_REACHED", "This claim has exhausted its reopenings.")
    policy = store.policies[claim["policy_id"]]
    if policy["status"] not in ("IN_FORCE", "EXPIRED"):
        raise ApiError(
            "ERR_INVALID_POLICY_STATE", "Reopening requires an IN_FORCE or EXPIRED policy."
        )
    claim["adjustment_status"] = "REOPENED"
    claim["reopen_count"] += 1
    touch(claim)
    return ok(claim)


@bp.get("/claims/<claim_id>")
def read_claim(claim_id):
    authenticate("Underwriter", "UnderwritingManager", "ClaimAdjuster")
    return ok(lookup.claim(claim_id))


@bp.get("/claims")
def list_claims():
    authenticate("Underwriter", "UnderwritingManager", "ClaimAdjuster")
    limit, offset = pagination()
    policy_id = filter_str("policy_id")
    peril = filter_enum("peril", PERILS)
    adjustment_status = filter_enum("adjustment_status", ADJUSTMENT_STATUSES)
    payment_status = filter_enum("payment_status", PAYMENT_STATUSES)
    rows = ordered(list(store.claims.values()))
    if policy_id is not None:
        rows = [r for r in rows if r["policy_id"] == policy_id]
    if peril is not None:
        rows = [r for r in rows if r["peril"] == peril]
    if adjustment_status is not None:
        rows = [r for r in rows if r["adjustment_status"] == adjustment_status]
    if payment_status is not None:
        rows = [r for r in rows if r["payment_status"] == payment_status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)
