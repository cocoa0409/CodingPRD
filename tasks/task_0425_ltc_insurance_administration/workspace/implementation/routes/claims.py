"""Claim & ClaimLine endpoints, review cycle, approve/deny cascades
(PRD §3.5, §3.6, §3.7)."""
from flask import Blueprint, request

import errors
from db import STORE, new_id, common_fields, touch
from middleware import authenticate, authorize
from response import object_response, array_response
from services import common, serialize, lookup, core

bp = Blueprint("claims", __name__)

PREMIUM_OK_FOR_CLAIM = {"PAID_CURRENT", "WAIVED", "NONFORFEITURE_PAID_UP"}


@bp.route("/claims", methods=["POST"])
def open_claim():
    caller = authenticate()
    authorize(caller, ["ClaimsExaminer"])
    body = common.get_json_body()
    policy_id = common.require_str(body, "policy_id")
    care_plan_id = common.require_str(body, "care_plan_id")
    service_month = common.require_str(body, "service_month")
    expected_version = common.require_int(body, "expected_policy_version")

    # Existence (path-less; body FKs) left-to-right.
    pol = lookup.policy_or_404(policy_id)
    lookup.care_plan_or_404(care_plan_id)

    # The duplicate-month check fires first: a second claim for an already-claimed
    # month is DUPLICATE even when coverage is already CLAIM_OPEN (PRD §3.5). This
    # precedes the coverage-state check so that re-opening the same month on a
    # CLAIM_OPEN policy reports ERR_DUPLICATE_SERVICE_PERIOD rather than the
    # coverage-state error.
    for c in STORE.claims.values():
        if c["policy_id"] == policy_id and c["service_month"] == service_month:
            raise errors.err(errors.ERR_DUPLICATE_SERVICE_PERIOD, "Duplicate service month")

    # State validity (PRD §3.13 priority 5): coverage must be IN_FORCE. This
    # precedes the business rules (premium currency, benefit-trigger) so that an
    # APPLIED / never-issued policy reports ERR_INVALID_STATE ahead of the
    # premium-currency check.
    if pol["coverage_status"] != "IN_FORCE":
        raise errors.err(errors.ERR_INVALID_STATE, "Coverage not IN_FORCE")

    # Business temporal: premium current.
    if pol["premium_status"] not in PREMIUM_OK_FOR_CLAIM:
        raise errors.err(errors.ERR_PREMIUM_NOT_CURRENT, "Premium not current")

    # Business safety: benefits triggered.
    if not serialize.policy_benefits_triggered(policy_id):
        raise errors.err(errors.ERR_BENEFITS_NOT_TRIGGERED, "Benefits not triggered")

    # OCC last.
    if expected_version != pol["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "Stale policy version")

    rid = new_id()
    rec = {
        "id": rid,
        "policy_id": policy_id,
        "care_plan_id": care_plan_id,
        "service_month": service_month,
        "month_paid_cents": 0,
        "requires_reassessment": False,
        "status": "SUBMITTED",
    }
    rec.update(common_fields(STORE.next_seq()))
    STORE.claims[rid] = rec

    # First open claim flips coverage IN_FORCE -> CLAIM_OPEN.
    pol["coverage_status"] = "CLAIM_OPEN"
    touch(pol)
    return object_response(serialize.claim(rec), 201)


@bp.route("/claims", methods=["GET"])
def list_claims():
    caller = authenticate()
    authorize(caller, ["ClaimsExaminer", "Underwriter"])
    records = list(STORE.claims.values())
    policy_id = request.args.get("policy_id")
    care_plan_id = request.args.get("care_plan_id")
    if policy_id is not None:
        records = [r for r in records if r["policy_id"] == policy_id]
    if care_plan_id is not None:
        records = [r for r in records if r["care_plan_id"] == care_plan_id]
    records = lookup.sorted_by_created(records)
    page, limit, offset, total = common.paginate(records)
    return array_response([serialize.claim(r) for r in page], limit, offset, total)


@bp.route("/claims/<rid>", methods=["GET"])
def get_claim(rid):
    caller = authenticate()
    authorize(caller, ["ClaimsExaminer", "Underwriter", "Policyholder"])
    rec = lookup.claim_or_404(rid)
    return object_response(serialize.claim(rec), 200)


@bp.route("/claims/<rid>/lines", methods=["POST"])
def add_line(rid):
    caller = authenticate()
    authorize(caller, ["ClaimsExaminer"])
    claim = lookup.claim_or_404(rid)
    body = common.get_json_body()
    service_date = common.require_str(body, "service_date")
    billed_charge = common.require_int(body, "billed_charge_cents")
    is_qualifying = common.optional_bool(body, "is_qualifying_day", True)

    # Claim must be SUBMITTED to attach lines.
    if claim["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Claim not SUBMITTED")

    # Duplicate service_date within the claim (priority 11) before out-of-month
    # placement (priority 12).
    for line in STORE.claim_lines.values():
        if line["claim_id"] == rid and line["service_date"] == service_date:
            raise errors.err(errors.ERR_DUPLICATE_SERVICE_PERIOD, "Duplicate service date")

    # service_date must fall inside the claim's service_month (YYYY-MM prefix).
    if service_date[:7] != claim["service_month"]:
        raise errors.err(errors.ERR_SERVICE_DATE_OUT_OF_MONTH, "Service date out of month")

    lid = new_id()
    rec = {
        "id": lid,
        "claim_id": rid,
        "service_date": service_date,
        "billed_charge_cents": billed_charge,
        "is_qualifying_day": is_qualifying,
        "elimination_applied": False,
        "benefit_paid_cents": 0,
    }
    rec.update(common_fields(STORE.next_seq()))
    STORE.claim_lines[lid] = rec
    return object_response(serialize.claim_line(rec), 201)


@bp.route("/claims/<rid>/lines", methods=["GET"])
def list_lines(rid):
    caller = authenticate()
    authorize(caller, ["ClaimsExaminer", "Underwriter"])
    lookup.claim_or_404(rid)
    records = [l for l in STORE.claim_lines.values() if l["claim_id"] == rid]
    records = lookup.sorted_by_created(records)
    page, limit, offset, total = common.paginate(records)
    return array_response([serialize.claim_line(l) for l in page], limit, offset, total)


@bp.route("/claims/<rid>/start-review", methods=["POST"])
def start_review(rid):
    caller = authenticate()
    authorize(caller, ["ClaimsExaminer"])
    claim = lookup.claim_or_404(rid)
    if claim["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Claim not SUBMITTED")
    care_plan = STORE.care_plans[claim["care_plan_id"]]
    if care_plan["status"] != "ACTIVE":
        raise errors.err(errors.ERR_CARE_PLAN_NOT_ACTIVE, "Care plan not ACTIVE")
    provider = STORE.providers[care_plan["provider_id"]]
    if provider["eligibility_status"] != "ELIGIBLE":
        raise errors.err(errors.ERR_PROVIDER_NOT_ELIGIBLE, "Provider not eligible")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return object_response(serialize.claim(claim), 200)


@bp.route("/claims/<rid>/request-reassessment", methods=["POST"])
def request_reassessment(rid):
    caller = authenticate()
    authorize(caller, ["ClaimsExaminer"])
    claim = lookup.claim_or_404(rid)
    if claim["status"] != "UNDER_REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Claim not UNDER_REVIEW")
    claim["status"] = "PENDING_REASSESSMENT"
    claim["requires_reassessment"] = True
    # mark the moment the claim was parked for reassessment
    claim["_reassessment_seq"] = STORE.next_seq()
    touch(claim)
    return object_response(serialize.claim(claim), 200)


@bp.route("/claims/<rid>/resume-review", methods=["POST"])
def resume_review(rid):
    caller = authenticate()
    authorize(caller, ["ClaimsExaminer"])
    claim = lookup.claim_or_404(rid)
    if claim["status"] != "PENDING_REASSESSMENT":
        raise errors.err(errors.ERR_INVALID_STATE, "Claim not PENDING_REASSESSMENT")

    # Latest certification for the policy created AFTER reassessment was set
    # must be CERTIFIED.
    parked_seq = claim.get("_reassessment_seq", 0)
    later = [c for c in STORE.trigger_certifications.values()
             if c["policy_id"] == claim["policy_id"] and c["_seq"] > parked_seq]
    if not later:
        raise errors.err(errors.ERR_BENEFITS_NOT_TRIGGERED, "No newer certification")
    later.sort(key=lambda c: c["_seq"])
    if later[-1]["decision"] != "CERTIFIED":
        raise errors.err(errors.ERR_BENEFITS_NOT_TRIGGERED, "Latest certification not CERTIFIED")

    claim["status"] = "UNDER_REVIEW"
    claim["requires_reassessment"] = False
    touch(claim)
    return object_response(serialize.claim(claim), 200)


@bp.route("/claims/<rid>/approve", methods=["POST"])
def approve_claim(rid):
    caller = authenticate()
    authorize(caller, ["ClaimsExaminer"])
    claim = lookup.claim_or_404(rid)
    body = common.get_json_body()
    expected_version = common.require_int(body, "expected_policy_version")

    # State first.
    if claim["status"] != "UNDER_REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Claim not UNDER_REVIEW")
    pol = STORE.policies[claim["policy_id"]]

    # OCC (concurrency guard among business rules).
    if expected_version != pol["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "Stale policy version")

    # Benefits triggered.
    if not serialize.policy_benefits_triggered(pol["id"]):
        raise errors.err(errors.ERR_BENEFITS_NOT_TRIGGERED, "Benefits not triggered")

    # Pool must have headroom before payout.
    pool = core.pool_for_policy(pol["id"])
    if serialize.benefit_pool(pool)["remaining_pool_cents"] <= 0:
        raise errors.err(errors.ERR_POOL_EXHAUSTED, "Pool exhausted")

    # Run payout, append ledger, recompute pool / partnership.
    total = core.run_claim_payout(pol, claim)
    claim["status"] = "APPROVED"
    touch(claim)
    core.append_ledger(pol["id"], claim["id"], "CLAIM_PAYMENT", -total)
    core.recompute_partnership(pol)

    # Coverage transitions.
    remaining = serialize.benefit_pool(pool)["remaining_pool_cents"]
    if remaining == 0:
        pol["coverage_status"] = "EXHAUSTED"
        for other in STORE.claims.values():
            if (other["policy_id"] == pol["id"] and other["id"] != claim["id"]
                    and other["status"] in core.NON_TERMINAL_CLAIM):
                other["status"] = "VOID"
                touch(other)
    elif not core.has_other_non_terminal_claim(pol["id"], claim["id"]):
        if pol["coverage_status"] == "CLAIM_OPEN":
            pol["coverage_status"] = "IN_FORCE"

    touch(pol)
    return object_response(serialize.claim(claim), 200)


@bp.route("/claims/<rid>/deny", methods=["POST"])
def deny_claim(rid):
    caller = authenticate()
    authorize(caller, ["ClaimsExaminer"])
    claim = lookup.claim_or_404(rid)
    body = common.get_json_body()
    expected_version = common.require_int(body, "expected_policy_version")

    if claim["status"] != "UNDER_REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Claim not UNDER_REVIEW")
    pol = STORE.policies[claim["policy_id"]]
    if expected_version != pol["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "Stale policy version")

    claim["status"] = "DENIED"
    touch(claim)

    if not core.has_other_non_terminal_claim(pol["id"], claim["id"]):
        if pol["coverage_status"] == "CLAIM_OPEN":
            pol["coverage_status"] = "IN_FORCE"
    touch(pol)
    return object_response(serialize.claim(claim), 200)
