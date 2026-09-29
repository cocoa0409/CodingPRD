"""BuildersRiskPolicy endpoints (PRD 3.2, 3.4, 3.9)."""
from decimal import Decimal

from flask import Blueprint

import calc
import lookup
import recompute
from db import by_policy, by_project, new_row, ordered, store, touch
from enums import ADJUSTMENT_STATUSES, ACKNOWLEDGMENT_STATUSES, CANCEL_REASONS, \
    COVERAGE_PART_STATUSES, DECISIONS_APPROVE_DECLINE, DEDUCTIBLE_TIERS, \
    ENDORSEMENT_STATUSES, PART_TYPES, PARTY_ROLES, PAYMENT_STATUSES, PERILS, \
    POLICY_STATUSES, ASSIGNMENT_STATUSES, TXN_TYPES
from errors import ApiError
from middleware import authenticate, body, filter_enum, filter_str, get_bool, get_dt, \
    get_enum, get_int, get_number, pagination, paginate, present
from response import created, ok, ok_list
from util import add_days, dec, rhu, whole_days

bp = Blueprint("policies", __name__)

REFERRAL_LOAD_VALUES = (Decimal("0"), Decimal("0.10"), Decimal("0.20"))


@bp.post("/policies")
def create_policy():
    authenticate("Underwriter")
    payload = body()
    project = lookup.fk_project(payload)
    expected_project_version = get_int(payload, "expected_project_version", minimum=0)
    term_start_date = get_dt(payload, "term_start_date")
    term_end_date = get_dt(payload, "term_end_date")
    includes_existing_structure = get_bool(
        payload, "includes_existing_structure", required=False, default=False
    )
    deductible_tier = get_enum(payload, "deductible_tier", DEDUCTIBLE_TIERS)
    limit_cents = get_int(payload, "limit_cents", minimum=1)
    daily_delay_rate_cents = get_int(payload, "daily_delay_rate_cents", minimum=0)
    if not term_start_date < term_end_date:
        raise ApiError(
            "ERR_DATE_RANGE_INVALID", "term_end_date must be strictly later than term_start_date."
        )
    if expected_project_version != project["version"]:
        raise ApiError(
            "ERR_STALE_PROJECT_VERSION", "expected_project_version does not match the project."
        )
    if project["status"] != "ELIGIBLE":
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE", "Only an ELIGIBLE project may receive a new draft."
        )
    if includes_existing_structure and (
        project["project_kind"] != "RENOVATION" or project["existing_structure_value_cents"] <= 0
    ):
        raise ApiError(
            "ERR_EXISTING_STRUCTURE_NOT_APPLICABLE",
            "This project has no standing structure to insure.",
        )
    row = new_row()
    row.update({
        "project_id": project["id"],
        "term_start_date": term_start_date,
        "term_end_date": term_end_date,
        "original_term_days": whole_days(term_start_date, term_end_date),
        "cumulative_extension_days": 0,
        "adjusted_completion_date": project["projected_completion_date"],
        "includes_existing_structure": includes_existing_structure,
        "deductible_tier": deductible_tier,
        "occurrence_deductible_cents": calc.OCCURRENCE_DEDUCTIBLE_CENTS[deductible_tier],
        "limit_cents": limit_cents,
        "daily_delay_rate_cents": daily_delay_rate_cents,
        "insured_tiv_cents": calc.insured_tiv_cents(project, includes_existing_structure),
        "quoted_premium_cents": None,
        "referral_load_pct": 0,
        "written_premium_cents": 0,
        "eroded_total_cents": 0,
        "return_premium_cents": None,
        "status": "DRAFT",
        "quoted_by_user_id": None,
        "bound_at": None,
        "cancel_reason": None,
        "cancel_effective_date": None,
    })
    for existing in ordered(by_project(store.policies, project["id"])):
        if existing["status"] == "DRAFT":
            existing["status"] = "SUPERSEDED"
            touch(existing)
    store.policies[row["id"]] = row
    touch(project)
    return created(row)


@bp.post("/policies/<policy_id>/quote")
def quote_policy(policy_id):
    user_id, _role = authenticate("Underwriter")
    policy = lookup.policy(policy_id)
    if policy["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_POLICY_STATE", "Only a DRAFT policy may be rated.")
    project = store.projects[policy["project_id"]]
    if project["status"] not in ("ELIGIBLE", "UNDER_CONSTRUCTION") \
            or project["submission_risk_score"] is None:
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE", "The project has not been screened into a rateable state."
        )
    has_materials = any(
        part["part_type"] == "MATERIALS_ON_SITE"
        for part in by_policy(store.coverage_parts, policy["id"])
    )
    if not has_materials:
        raise ApiError(
            "ERR_COVERAGE_PART_MISSING",
            "A MATERIALS_ON_SITE coverage part must be scheduled before rating.",
        )
    policy["quoted_premium_cents"] = calc.quote_premium(policy, project)
    policy["quoted_by_user_id"] = user_id
    if project["submission_risk_score"] >= calc.REFERRAL_THRESHOLD:
        policy["status"] = "REFERRED"
    else:
        policy["status"] = "QUOTED"
    touch(policy)
    return ok(policy)


@bp.post("/policies/<policy_id>/referral-decision")
def referral_decision(policy_id):
    user_id, _role = authenticate("UnderwritingManager")
    policy = lookup.policy(policy_id)
    if policy["quoted_by_user_id"] is not None and policy["quoted_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "The rating underwriter may not disposition the referral."
        )
    payload = body()
    decision = get_enum(payload, "decision", DECISIONS_APPROVE_DECLINE)
    load = get_number(payload, "referral_load_pct", required=False, default=Decimal("0"))
    if load not in REFERRAL_LOAD_VALUES:
        raise ApiError("ERR_INVALID_REQUEST", "referral_load_pct must be one of 0, 0.10, 0.20.")
    if policy["status"] != "REFERRED":
        raise ApiError("ERR_INVALID_POLICY_STATE", "Only a REFERRED policy may be dispositioned.")
    if decision == "APPROVE":
        policy["referral_load_pct"] = load
        policy["quoted_premium_cents"] = calc.apply_referral_load(
            policy["quoted_premium_cents"], load
        )
        policy["status"] = "QUOTED"
    else:
        policy["status"] = "DECLINED"
    touch(policy)
    return ok(policy)


@bp.post("/policies/<policy_id>/reopen")
def reopen_policy(policy_id):
    authenticate("Underwriter")
    policy = lookup.policy(policy_id)
    if policy["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_POLICY_STATE", "Only a QUOTED policy may be reopened.")
    policy["status"] = "DRAFT"
    policy["quoted_premium_cents"] = None
    policy["quoted_by_user_id"] = None
    # PRD 3.4: any referral_load_pct already recorded on the policy is preserved.
    touch(policy)
    return ok(policy)


@bp.post("/policies/<policy_id>/bind")
def bind_policy(policy_id):
    authenticate("Underwriter")
    policy = lookup.policy(policy_id)
    if policy["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_POLICY_STATE", "Only a QUOTED policy may be bound.")
    for other in by_project(store.policies, policy["project_id"]):
        if other["id"] != policy["id"] and other["status"] in ("BOUND", "IN_FORCE"):
            raise ApiError(
                "ERR_ACTIVE_POLICY_EXISTS", "This project already carries a live policy."
            )
    interests = by_policy(store.interests, policy["id"])
    owner_gc_pct = Decimal("0")
    has_owner = False
    for interest in interests:
        if interest["acknowledgment_status"] != "ACKNOWLEDGED":
            raise ApiError(
                "ERR_INTERESTS_NOT_ACKNOWLEDGED", "Every named interest must be ACKNOWLEDGED."
            )
        if interest["party_role"] == "OWNER":
            has_owner = True
        if interest["party_role"] in ("OWNER", "GENERAL_CONTRACTOR"):
            owner_gc_pct += dec(interest["insurable_interest_pct"])
    if not has_owner or owner_gc_pct != Decimal("100"):
        raise ApiError(
            "ERR_INTERESTS_NOT_ACKNOWLEDGED",
            "The insured schedule must name an OWNER and total exactly 100 percent.",
        )
    schedule_sum = sum(
        part["sublimit_cents"] for part in by_policy(store.coverage_parts, policy["id"])
        if part["part_type"] in ("MATERIALS_ON_SITE", "EXISTING_STRUCTURE")
    )
    if schedule_sum > policy["insured_tiv_cents"]:
        raise ApiError(
            "ERR_SUBLIMIT_EXCEEDS_LIMIT",
            "The property schedule exceeds the policy's insured total insurable value.",
        )
    policy["status"] = "BOUND"
    policy["bound_at"] = store.now()
    policy["written_premium_cents"] = policy["quoted_premium_cents"]
    recompute.append_txn(
        policy, "INITIAL", policy["quoted_premium_cents"], policy["term_start_date"], "bind"
    )
    touch(policy)
    return ok(policy)


@bp.post("/policies/<policy_id>/incept")
def incept_policy(policy_id):
    authenticate("Underwriter")
    policy = lookup.policy(policy_id)
    if policy["status"] != "BOUND":
        raise ApiError("ERR_INVALID_POLICY_STATE", "Only a BOUND policy may be incepted.")
    if store.now() < policy["term_start_date"]:
        raise ApiError(
            "ERR_INVALID_POLICY_STATE", "Inception may not precede the policy's term_start_date."
        )
    policy["status"] = "IN_FORCE"
    touch(policy)
    project = store.projects.get(policy["project_id"])
    if project is not None:
        if project["status"] == "ELIGIBLE":
            project["status"] = "UNDER_CONSTRUCTION"
        recompute.recompute_in_force_policy_count(project)
        touch(project)
    return ok(policy)


@bp.post("/policies/<policy_id>/cancel")
def cancel_policy(policy_id):
    authenticate("UnderwritingManager")
    policy = lookup.policy(policy_id)
    payload = body()
    cancel_reason = get_enum(payload, "cancel_reason", CANCEL_REASONS)
    cancel_effective_date = get_dt(payload, "cancel_effective_date")
    if policy["status"] != "IN_FORCE":
        raise ApiError("ERR_INVALID_POLICY_STATE", "Only an IN_FORCE policy may be cancelled.")
    if not (policy["term_start_date"] < cancel_effective_date <= policy["term_end_date"]) \
            or cancel_effective_date < store.now():
        raise ApiError(
            "ERR_CANCEL_DATE_INVALID",
            "cancel_effective_date must sit inside the term and may not be back-dated.",
        )
    policy["return_premium_cents"] = calc.return_premium(
        policy, cancel_reason, cancel_effective_date
    )
    policy["cancel_reason"] = cancel_reason
    policy["cancel_effective_date"] = cancel_effective_date
    policy["status"] = "CANCELLED"
    recompute.append_txn(
        policy,
        "RETURN_PREMIUM",
        -policy["return_premium_cents"],
        cancel_effective_date,
        "cancellation return",
    )
    touch(policy)
    recompute.policy_leaves_in_force(policy, "POLICY_CANCELLATION")
    return ok(policy)


@bp.get("/policies/<policy_id>")
def read_policy(policy_id):
    authenticate("Underwriter", "UnderwritingManager", "RiskEngineer", "ClaimAdjuster")
    return ok(lookup.policy(policy_id))


@bp.get("/policies")
def list_policies():
    authenticate("Underwriter", "UnderwritingManager", "RiskEngineer", "ClaimAdjuster")
    limit, offset = pagination()
    project_id = filter_str("project_id")
    status = filter_enum("status", POLICY_STATUSES)
    rows = ordered(list(store.policies.values()))
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/policies/<policy_id>/coverage-parts")
def list_policy_coverage_parts(policy_id):
    authenticate("Underwriter", "UnderwritingManager", "RiskEngineer", "ClaimAdjuster")
    lookup.policy(policy_id)
    limit, offset = pagination()
    status = filter_enum("status", COVERAGE_PART_STATUSES)
    part_type = filter_enum("part_type", PART_TYPES)
    rows = ordered(by_policy(store.coverage_parts, policy_id))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if part_type is not None:
        rows = [r for r in rows if r["part_type"] == part_type]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/policies/<policy_id>/named-insured-interests")
def list_policy_interests(policy_id):
    authenticate("Underwriter", "UnderwritingManager", "ClaimAdjuster")
    lookup.policy(policy_id)
    limit, offset = pagination()
    party_role = filter_enum("party_role", PARTY_ROLES)
    ack = filter_enum("acknowledgment_status", ACKNOWLEDGMENT_STATUSES)
    rows = ordered(by_policy(store.interests, policy_id))
    if party_role is not None:
        rows = [r for r in rows if r["party_role"] == party_role]
    if ack is not None:
        rows = [r for r in rows if r["acknowledgment_status"] == ack]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/policies/<policy_id>/extension-endorsements")
def list_policy_endorsements(policy_id):
    authenticate("Underwriter", "UnderwritingManager")
    lookup.policy(policy_id)
    limit, offset = pagination()
    status = filter_enum("status", ENDORSEMENT_STATUSES)
    rows = ordered(by_policy(store.endorsements, policy_id))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/policies/<policy_id>/claims")
def list_policy_claims(policy_id):
    authenticate("Underwriter", "UnderwritingManager", "ClaimAdjuster")
    lookup.policy(policy_id)
    limit, offset = pagination()
    adjustment_status = filter_enum("adjustment_status", ADJUSTMENT_STATUSES)
    payment_status = filter_enum("payment_status", PAYMENT_STATUSES)
    peril = filter_enum("peril", PERILS)
    rows = ordered(by_policy(store.claims, policy_id))
    if adjustment_status is not None:
        rows = [r for r in rows if r["adjustment_status"] == adjustment_status]
    if payment_status is not None:
        rows = [r for r in rows if r["payment_status"] == payment_status]
    if peril is not None:
        rows = [r for r in rows if r["peril"] == peril]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/policies/<policy_id>/premium-transactions")
def list_policy_premium_transactions(policy_id):
    authenticate("Underwriter", "UnderwritingManager")
    lookup.policy(policy_id)
    limit, offset = pagination()
    txn_type = filter_enum("txn_type", TXN_TYPES)
    rows = sorted(by_policy(store.premium_txns, policy_id), key=lambda r: r["sequence_no"])
    if txn_type is not None:
        rows = [r for r in rows if r["txn_type"] == txn_type]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/policies/<policy_id>/storage-assignments")
def list_policy_storage_assignments(policy_id):
    authenticate("Underwriter", "UnderwritingManager", "RiskEngineer")
    lookup.policy(policy_id)
    limit, offset = pagination()
    status = filter_enum("status", ASSIGNMENT_STATUSES)
    rows = ordered(by_policy(store.assignments, policy_id))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/policies/<policy_id>/premium-summary")
def policy_premium_summary(policy_id):
    authenticate("Underwriter", "UnderwritingManager")
    policy = lookup.policy(policy_id)
    rows = recompute.ledger_rows(policy["id"])
    ledger_sum = sum(row["amount_cents"] for row in rows)
    extension_ap_total = sum(
        row["amount_cents"] for row in rows
        if row["txn_type"] in ("EXTENSION_AP", "EXTENSION_AP_REVERSAL")
    )
    return ok({
        "quoted_premium_cents": policy["quoted_premium_cents"],
        "written_premium_cents": policy["written_premium_cents"],
        "ledger_sum_cents": ledger_sum,
        "transaction_count": len(rows),
        "extension_ap_total_cents": extension_ap_total,
        "return_premium_cents": (
            policy["return_premium_cents"] if policy["status"] == "CANCELLED" else 0
        ),
        "balanced": ledger_sum == policy["written_premium_cents"],
    })
