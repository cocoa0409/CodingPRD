"""Notice, coverage decisions, defense advancement and settlement (PRD 3.7 - 3.9)."""

from flask import Blueprint, request

import clock
import db
from auth import CLAIMS_ADJUSTER, RISK_MANAGER, authenticate, require_owner
from db import store
from errors import ApiError
from money import ZERO, dec, q2
from response import list_response, object_response
from routes.common import (
    get_claim,
    get_invoice,
    get_policy,
    get_proposal,
    get_report,
    owning_insured_id_for_claim,
    owning_insured_id_for_proposal,
)
from routes.policies import reporting_deadline
from services import claims as claim_rules
from services import derive
from validation import Field, paginate, parse_body, parse_pagination, validate

bp = Blueprint("claims", __name__)

CLAIM_TYPES = (
    "SECURITIES_CLASS_ACTION",
    "DERIVATIVE",
    "REGULATORY_ENFORCEMENT",
    "EMPLOYMENT_PRACTICES",
    "INSURED_VS_INSURED",
    "FIDUCIARY",
)
CLAIMANT_CAPACITIES = (
    "THIRD_PARTY",
    "SHAREHOLDER_DERIVATIVE",
    "FORMER_OFFICER",
    "BANKRUPTCY_TRUSTEE",
    "COMPANY",
)
DENIAL_REASONS = (
    "CONDUCT_EXCLUSION",
    "PRIOR_ACTS",
    "INSURED_VS_INSURED",
    "LATE_NOTICE",
    "MISREPRESENTATION",
)
ALLOCATION_METHODS = ("RELATIVE_EXPOSURE", "LARGER_SETTLEMENT")
ADVANCING_CLAIM_STATES = ("COVERAGE_ACCEPTED", "DEFENSE_ADVANCING")

NOTICE_FIELDS = [
    Field("claim_type", "enum", enum=CLAIM_TYPES),
    Field("claimant_name", "string"),
    Field("claimant_capacity", "enum", enum=CLAIMANT_CAPACITIES),
    Field("wrongful_act_date", "datetime"),
    Field("alleged_damages_usd", "money", check=lambda v: v > 0),
]

REPORT_FIELDS = [
    Field("description", "string"),
    Field("discovered_date", "datetime"),
    Field("potential_claimants", "string"),
    Field("estimated_exposure_usd", "money", check=lambda v: v > 0),
]

DECISION_FIELDS = [
    Field("decision", "enum", enum=("ACCEPT_WITH_ROR", "DENY")),
    Field("allocation_method", "enum", required=False, enum=ALLOCATION_METHODS, default=None),
    Field("denial_reason", "enum", required=False, enum=DENIAL_REASONS, default=None),
]

INVOICE_FIELDS = [
    Field("law_firm_name", "string"),
    Field("invoice_reference", "string"),
    Field("billed_amount_usd", "money", check=lambda v: v > 0),
    Field("covered_matter_amount_usd", "money", check=lambda v: v >= 0),
    Field("uncovered_matter_amount_usd", "money", check=lambda v: v >= 0),
    Field("mixed_matter_amount_usd", "money", check=lambda v: v >= 0),
    Field("insured_person_defendant_count", "integer", check=lambda v: v >= 0),
    Field("entity_defendant_count", "integer", check=lambda v: v >= 0),
]

ALLOCATE_FIELDS = [Field("expected_claim_version", "integer")]

PROPOSAL_FIELDS = [
    Field("expected_claim_version", "integer"),
    Field("recommended_amount_usd", "money", check=lambda v: v > 0),
]

RESPOND_FIELDS = [
    Field("response", "enum", enum=("CONSENT", "REFUSE")),
    Field("refusal_reason", "string", required=False, default=None),
]

RESOLVE_FIELDS = [
    Field("final_resolution_amount_usd", "money"),
    Field("post_refusal_defense_usd", "money", required=False, default=ZERO, check=lambda v: v >= 0),
]


def _inside_claims_made_window(policy, instant):
    if instant < policy["period_start"]:
        return False
    if policy["coverage_status"] == "RUNOFF" and policy["runoff_end_date"] is not None:
        return instant < policy["runoff_end_date"]
    return instant < policy["period_end"]


def _new_claim(policy, values, notice_date, report_id, touched):
    claim = db.insert(
        "claims",
        {
            "policy_id": policy["id"],
            "circumstance_report_id": report_id,
            "claim_type": values["claim_type"],
            "claimant_name": values["claimant_name"],
            "claimant_capacity": values["claimant_capacity"],
            "wrongful_act_date": values["wrongful_act_date"],
            "notice_date": notice_date,
            "alleged_damages_usd": values["alleged_damages_usd"],
            "status": "NOTICED",
            "allocation_method": None,
            "denial_reason": None,
            "decided_by_user_id": None,
            "retention_remaining_usd": q2(dec(policy["retention_usd"])),
            "retention_applied_usd": q2(ZERO),
            "advanced_defense_usd": q2(ZERO),
            "post_refusal_defense_usd": q2(ZERO),
            "indemnity_paid_usd": q2(ZERO),
            "insurer_share_usd": q2(ZERO),
            "insured_retained_usd": q2(ZERO),
            "unfunded_excess_usd": q2(ZERO),
            "hammer_applied": False,
        },
    )
    derive.recompute_open_claim_count(policy)
    touched.add(policy)
    return claim


# --------------------------------------------------------------------------
# Notice
# --------------------------------------------------------------------------


@bp.post("/dno/policies/<policy_id>/claims")
def notice_claim(policy_id):
    user_id, role = authenticate(RISK_MANAGER)
    policy = get_policy(policy_id)
    require_owner(role, user_id, policy["insured_id"])
    values, _ = validate(parse_body(), NOTICE_FIELDS)

    if policy["coverage_status"] not in derive.OPEN_COVERAGE_STATUSES:
        raise ApiError("ERR_INVALID_POLICY_STATE")
    if not claim_rules.insured_vs_insured_ok(policy, values["claimant_capacity"]):
        raise ApiError("ERR_INSURED_VS_INSURED_EXCLUDED")
    now = clock.now()
    if not _inside_claims_made_window(policy, now):
        raise ApiError("ERR_NOTICE_OUTSIDE_PERIOD")
    if not claim_rules.prior_acts_ok(policy, values["wrongful_act_date"]):
        raise ApiError("ERR_PRIOR_ACTS_EXCLUDED")
    if policy["coverage_status"] == "RUNOFF" and policy["runoff_start_date"] is not None:
        if values["wrongful_act_date"] >= policy["runoff_start_date"]:
            raise ApiError("ERR_POST_TRANSACTION_ACT")

    touched = derive.Touched()
    claim = _new_claim(policy, values, now, None, touched)
    touched.flush()
    return object_response(claim, 201)


@bp.post("/dno/policies/<policy_id>/circumstance-reports")
def report_circumstance(policy_id):
    user_id, role = authenticate(RISK_MANAGER)
    policy = get_policy(policy_id)
    require_owner(role, user_id, policy["insured_id"])
    values, _ = validate(parse_body(), REPORT_FIELDS)

    if policy["coverage_status"] not in derive.OPEN_COVERAGE_STATUSES:
        raise ApiError("ERR_INVALID_POLICY_STATE")
    now = clock.now()
    if not _inside_claims_made_window(policy, now):
        raise ApiError("ERR_NOTICE_OUTSIDE_PERIOD")

    record = db.insert(
        "circumstance_reports",
        {
            "policy_id": policy["id"],
            "description": values["description"],
            "discovered_date": values["discovered_date"],
            "notice_date": now,
            "potential_claimants": values["potential_claimants"],
            "estimated_exposure_usd": values["estimated_exposure_usd"],
            "reporting_deadline": reporting_deadline(policy),
            "status": "REPORTED",
        },
    )
    return object_response(record, 201)


@bp.get("/dno/policies/<policy_id>/circumstance-reports")
def list_reports(policy_id):
    authenticate()
    policy = get_policy(policy_id)
    limit, offset = parse_pagination()
    records = derive.reports_of(policy["id"])
    return list_response(paginate(records, limit, offset), limit, offset, len(records))


@bp.post("/dno/circumstance-reports/<report_id>/mature")
def mature_report(report_id):
    authenticate(CLAIMS_ADJUSTER)
    report = get_report(report_id)
    values, _ = validate(parse_body(), NOTICE_FIELDS)
    policy = store.policies.get(report["policy_id"])

    if report["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_CIRCUMSTANCE_STATE")
    if not claim_rules.insured_vs_insured_ok(policy, values["claimant_capacity"]):
        raise ApiError("ERR_INSURED_VS_INSURED_EXCLUDED")
    if not claim_rules.prior_acts_ok(policy, values["wrongful_act_date"]):
        raise ApiError("ERR_PRIOR_ACTS_EXCLUDED")
    if policy["coverage_status"] == "RUNOFF" and policy["runoff_start_date"] is not None:
        if values["wrongful_act_date"] >= policy["runoff_start_date"]:
            raise ApiError("ERR_POST_TRANSACTION_ACT")
    if report["reporting_deadline"] is not None and clock.now() >= report["reporting_deadline"]:
        raise ApiError("ERR_REPORTING_WINDOW_CLOSED")

    touched = derive.Touched()
    report["status"] = "MATURED"
    touched.add(report)
    claim = _new_claim(policy, values, report["notice_date"], report["id"], touched)
    touched.flush()
    return object_response(claim, 201)


# --------------------------------------------------------------------------
# Claim reads
# --------------------------------------------------------------------------


@bp.get("/dno/claims/<claim_id>")
def read_claim(claim_id):
    authenticate()
    return object_response(get_claim(claim_id))


@bp.get("/dno/claims")
def list_claims():
    authenticate()
    limit, offset = parse_pagination()
    records = db.ordered(list(store.claims.values()))
    for key in ("policy_id", "circumstance_report_id", "status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    return list_response(paginate(records, limit, offset), limit, offset, len(records))


# --------------------------------------------------------------------------
# Coverage decision
# --------------------------------------------------------------------------


@bp.post("/dno/claims/<claim_id>/coverage-decision")
def coverage_decision(claim_id):
    user_id, _ = authenticate(CLAIMS_ADJUSTER)
    claim = get_claim(claim_id)
    values, _ = validate(parse_body(), DECISION_FIELDS)
    decision = values["decision"]

    if decision == "ACCEPT_WITH_ROR" and values["allocation_method"] is None:
        raise ApiError("ERR_CONDITIONAL_FIELD_REQUIRED")
    if decision == "DENY" and values["denial_reason"] is None:
        raise ApiError("ERR_CONDITIONAL_FIELD_REQUIRED")

    if decision == "ACCEPT_WITH_ROR":
        if claim["status"] != "NOTICED":
            raise ApiError("ERR_INVALID_CLAIM_STATE")
    elif claim["status"] not in ("NOTICED", "COVERAGE_ACCEPTED", "DEFENSE_ADVANCING"):
        raise ApiError("ERR_INVALID_CLAIM_STATE")

    policy = store.policies.get(claim["policy_id"])
    touched = derive.Touched()
    claim["decided_by_user_id"] = user_id
    if decision == "ACCEPT_WITH_ROR":
        claim["status"] = "COVERAGE_ACCEPTED"
        claim["allocation_method"] = values["allocation_method"]
    else:
        claim["status"] = "DENIED"
        claim["denial_reason"] = values["denial_reason"]
        claim_rules.clawback(claim, policy, touched)
        derive.recompute_open_claim_count(policy)
        touched.add(policy)
    touched.add(claim)
    touched.flush()
    return object_response(claim)


# --------------------------------------------------------------------------
# Defense invoices
# --------------------------------------------------------------------------


@bp.post("/dno/claims/<claim_id>/defense-invoices")
def submit_invoice(claim_id):
    user_id, role = authenticate(RISK_MANAGER)
    claim = get_claim(claim_id)
    require_owner(role, user_id, owning_insured_id_for_claim(claim))
    values, _ = validate(parse_body(), INVOICE_FIELDS)

    if claim["status"] not in ADVANCING_CLAIM_STATES:
        raise ApiError("ERR_INVALID_CLAIM_STATE")

    for existing in derive.invoices_of(claim["id"]):
        if existing["status"] != "VOIDED" and existing["invoice_reference"] == values["invoice_reference"]:
            raise ApiError("ERR_DUPLICATE_INVOICE_REFERENCE")

    split_total = (
        values["covered_matter_amount_usd"]
        + values["uncovered_matter_amount_usd"]
        + values["mixed_matter_amount_usd"]
    )
    both_counts_zero = (
        values["insured_person_defendant_count"] == 0
        and values["entity_defendant_count"] == 0
    )
    if split_total != values["billed_amount_usd"] or both_counts_zero:
        raise ApiError("ERR_INVOICE_AMOUNT_MISMATCH")

    record = {"claim_id": claim["id"]}
    for field in INVOICE_FIELDS:
        record[field.name] = values[field.name]
    record.update(
        {
            "allocation_method_applied": None,
            "covered_allocated_usd": q2(ZERO),
            "retention_applied_usd": q2(ZERO),
            "advanced_usd": q2(ZERO),
            "unfunded_excess_usd": q2(ZERO),
            "status": "SUBMITTED",
            "_charges": [],
        }
    )
    return object_response(db.insert("defense_invoices", record), 201)


@bp.get("/dno/claims/<claim_id>/defense-invoices")
def list_invoices(claim_id):
    authenticate()
    claim = get_claim(claim_id)
    limit, offset = parse_pagination()
    records = derive.invoices_of(claim["id"])
    return list_response(paginate(records, limit, offset), limit, offset, len(records))


@bp.post("/dno/defense-invoices/<invoice_id>/allocate")
def allocate_invoice(invoice_id):
    authenticate(CLAIMS_ADJUSTER)
    invoice = get_invoice(invoice_id)
    values, _ = validate(parse_body(), ALLOCATE_FIELDS)
    claim = store.claims.get(invoice["claim_id"])
    policy = store.policies.get(claim["policy_id"])

    if values["expected_claim_version"] != claim["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if claim["status"] not in ADVANCING_CLAIM_STATES:
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    if invoice["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_INVOICE_STATE")
    if policy["premium_status"] == "DELINQUENT":
        raise ApiError("ERR_PREMIUM_DELINQUENT")

    touched = derive.Touched()
    method = claim["allocation_method"]
    covered = claim_rules.covered_allocated(invoice, method)
    outcome = claim_rules.waterfall(claim, policy, covered, touched)

    invoice["allocation_method_applied"] = method
    invoice["covered_allocated_usd"] = covered
    invoice["retention_applied_usd"] = outcome["retention_applied_usd"]
    invoice["advanced_usd"] = outcome["advanced_usd"]
    invoice["unfunded_excess_usd"] = outcome["unfunded_excess_usd"]
    invoice["status"] = "ADVANCED"
    invoice["_charges"] = outcome["charges"]
    touched.add(invoice)

    claim["retention_applied_usd"] = q2(
        dec(claim["retention_applied_usd"]) + outcome["retention_applied_usd"]
    )
    claim["retention_remaining_usd"] = q2(
        dec(claim["retention_remaining_usd"]) - outcome["retention_applied_usd"]
    )
    claim["advanced_defense_usd"] = q2(
        dec(claim["advanced_defense_usd"]) + outcome["advanced_usd"]
    )
    claim["unfunded_excess_usd"] = q2(
        dec(claim["unfunded_excess_usd"]) + outcome["unfunded_excess_usd"]
    )
    claim["status"] = "DEFENSE_ADVANCING"
    touched.add(claim)

    derive.cascade_erosion(policy, touched)
    touched.flush()
    return object_response(invoice)


# --------------------------------------------------------------------------
# Settlement
# --------------------------------------------------------------------------


@bp.post("/dno/claims/<claim_id>/settlement-proposals")
def recommend_settlement(claim_id):
    user_id, _ = authenticate(CLAIMS_ADJUSTER)
    claim = get_claim(claim_id)
    values, _ = validate(parse_body(), PROPOSAL_FIELDS)

    if values["expected_claim_version"] != claim["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if claim["status"] not in ADVANCING_CLAIM_STATES:
        raise ApiError("ERR_INVALID_CLAIM_STATE")

    touched = derive.Touched()
    for existing in derive.proposals_of(claim["id"]):
        if existing["status"] in ("RECOMMENDED", "CONSENTED", "REFUSED"):
            existing["status"] = "SUPERSEDED"
            touched.add(existing)

    proposal = db.insert(
        "settlement_proposals",
        {
            "claim_id": claim["id"],
            "recommended_amount_usd": values["recommended_amount_usd"],
            "recommended_by_user_id": user_id,
            "insured_response": None,
            "response_date": None,
            "refusal_reason": None,
            "hammer_pct_applied": None,
            "insurer_indemnity_cap_usd": None,
            "status": "RECOMMENDED",
        },
    )
    claim["status"] = "SETTLEMENT_PENDING"
    touched.add(claim)
    touched.flush()
    return object_response(proposal, 201)


@bp.get("/dno/claims/<claim_id>/settlement-proposals")
def list_proposals(claim_id):
    authenticate()
    claim = get_claim(claim_id)
    limit, offset = parse_pagination()
    records = derive.proposals_of(claim["id"])
    return list_response(paginate(records, limit, offset), limit, offset, len(records))


@bp.post("/dno/settlement-proposals/<proposal_id>/respond")
def respond_to_proposal(proposal_id):
    user_id, role = authenticate(RISK_MANAGER)
    proposal = get_proposal(proposal_id)
    require_owner(role, user_id, owning_insured_id_for_proposal(proposal))
    values, _ = validate(parse_body(), RESPOND_FIELDS)

    if values["response"] == "REFUSE" and not values["refusal_reason"]:
        raise ApiError("ERR_CONDITIONAL_FIELD_REQUIRED")
    if proposal["status"] != "RECOMMENDED":
        raise ApiError("ERR_INVALID_PROPOSAL_STATE")

    claim = store.claims.get(proposal["claim_id"])
    retention_baseline = dec(claim["retention_remaining_usd"])
    if values["response"] == "CONSENT":
        proposal["status"] = "CONSENTED"
        hammer_pct = claim_rules.HAMMER_CONSENT
    else:
        proposal["status"] = "REFUSED"
        hammer_pct = claim_rules.HAMMER_REFUSE
        proposal["refusal_reason"] = values["refusal_reason"]
    proposal["insured_response"] = values["response"]
    proposal["response_date"] = clock.now()
    proposal["hammer_pct_applied"] = hammer_pct
    proposal["insurer_indemnity_cap_usd"] = claim_rules.hammer_cap(
        hammer_pct, proposal["recommended_amount_usd"], retention_baseline
    )
    db.touch(proposal)
    return object_response(proposal)


def _governing_proposal(claim_id):
    candidates = [
        p for p in derive.proposals_of(claim_id) if p["status"] != "SUPERSEDED"
    ]
    if not candidates:
        return None
    return sorted(candidates, key=db.sort_key)[-1]


@bp.post("/dno/claims/<claim_id>/resolve")
def resolve_claim(claim_id):
    user_id, _ = authenticate(CLAIMS_ADJUSTER)
    claim = get_claim(claim_id)
    values, _ = validate(parse_body(), RESOLVE_FIELDS)
    policy = store.policies.get(claim["policy_id"])

    if claim["status"] != "SETTLEMENT_PENDING":
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    proposal = _governing_proposal(claim["id"])
    if proposal is None or proposal["status"] not in ("CONSENTED", "REFUSED"):
        raise ApiError("ERR_CONSENT_PENDING")
    if user_id == proposal["recommended_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if policy["premium_status"] == "DELINQUENT":
        raise ApiError("ERR_PREMIUM_DELINQUENT")
    if dec(policy["aggregate_remaining_usd"]) <= 0:
        raise ApiError("ERR_LIMIT_EXHAUSTED")

    final_amount = values["final_resolution_amount_usd"]
    post_refusal = values["post_refusal_defense_usd"]
    retention_baseline = dec(claim["retention_remaining_usd"])
    touched = derive.Touched()

    drawn = retention_baseline if retention_baseline < final_amount else final_amount
    if drawn < 0:
        drawn = ZERO
    claim["retention_applied_usd"] = q2(dec(claim["retention_applied_usd"]) + drawn)
    left = retention_baseline - dec(final_amount)
    claim["retention_remaining_usd"] = q2(left if left > 0 else ZERO)

    share = claim_rules.insurer_share(
        final_amount,
        retention_baseline,
        proposal["insurer_indemnity_cap_usd"],
        policy["aggregate_remaining_usd"],
    )
    claim["insurer_share_usd"] = share
    claim["indemnity_paid_usd"] = share
    claim["insured_retained_usd"] = q2(dec(final_amount) - share)
    claim["hammer_applied"] = proposal["insured_response"] == "REFUSE"
    claim["post_refusal_defense_usd"] = q2(dec(post_refusal or ZERO))

    unabsorbed = claim_rules.split_indemnity(claim, policy, share, touched)
    if unabsorbed > 0:
        claim["unfunded_excess_usd"] = q2(dec(claim["unfunded_excess_usd"]) + unabsorbed)

    claim["status"] = "SETTLED"
    touched.add(claim)

    proposal["status"] = "FUNDED" if proposal["insured_response"] == "CONSENT" else "HAMMER_APPLIED"
    touched.add(proposal)

    derive.cascade_erosion(policy, touched)
    derive.recompute_open_claim_count(policy)
    touched.add(policy)
    touched.flush()
    return object_response(claim)
