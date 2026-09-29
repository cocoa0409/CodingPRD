"""Parental reimbursement claims and state/Medicaid recovery claims (3.7 / 3.6)."""
from flask import Blueprint

from calc import (
    HIGH_COST_TRIGGER_CENTS,
    MAX_EQUITABLE_REDUCTION,
    MAX_REMAND_ROUNDS,
    MIN_EQUITABLE_FINDINGS_CHARS,
    high_cost_amounts,
    medicaid_amounts,
    reimbursement_award,
)
from cascades import disburse_direct, reverse_direct
from common import (
    AWARD_BASES,
    CLAIM_TYPES,
    account_or_404,
    collection,
    funding_or_404,
    placement_or_404,
    reimbursement_or_404,
    single,
    student_or_404,
)
from errors import fail
from middleware import (
    ALL_ROLES,
    FISCAL_OFFICER,
    HEARING_ADJUDICATOR,
    PARENT_GUARDIAN,
    PLACEMENT_COORDINATOR,
    check_scope,
    endpoint,
)
from response import created, ok
from store import db, new_row, now_iso, parse_date, public, touch
from validation import (
    get_bool,
    get_cents,
    get_date,
    get_enum,
    get_id,
    get_int,
    get_text,
    q_int,
    q_str,
    read_body,
)

bp = Blueprint("claims", __name__)


# =========================================================================
# reimbursement claims
# =========================================================================

@endpoint(bp, "GET", "/reimbursement-claims", ALL_ROLES)
def list_reimbursement_claims():
    return collection(db.reimbursements.values(), [
        ("student_id", q_str("student_id")),
        ("superseding_placement_id", q_str("superseding_placement_id")),
        ("fiscal_account_id", q_str("fiscal_account_id")),
        ("status", q_str("status")),
    ])


@endpoint(bp, "GET", "/reimbursement-claims/<claim_id>", ALL_ROLES)
def get_reimbursement_claim(claim_id):
    return single(reimbursement_or_404(claim_id))


@endpoint(bp, "POST", "/reimbursement-claims", (PARENT_GUARDIAN, PLACEMENT_COORDINATOR))
def create_reimbursement_claim():
    body = read_body((
        "student_id", "fiscal_account_id", "superseding_placement_id",
        "unilateral_school_name", "claimed_tuition_cents", "claimed_transport_cents",
        "claimed_instructional_days", "notice_date", "unilateral_start_date",
        "unilateral_end_date", "prior_district_offer_date", "parent_cooperation",
    ))
    student_id = get_id(body, "student_id")
    account_id = get_id(body, "fiscal_account_id")
    superseding_id = get_id(body, "superseding_placement_id", required=False,
                            default=None, nullable=True)
    school_name = get_text(body, "unilateral_school_name")
    claimed_tuition = get_cents(body, "claimed_tuition_cents", minimum=0)
    claimed_transport = get_cents(body, "claimed_transport_cents", required=False,
                                  default=0, minimum=0)
    claimed_days = get_int(body, "claimed_instructional_days", minimum=1, maximum=260)
    notice_date = get_date(body, "notice_date")
    start_date = get_date(body, "unilateral_start_date")
    end_date = get_date(body, "unilateral_end_date")
    offer_date = get_date(body, "prior_district_offer_date", required=False,
                          default=None, nullable=True)
    cooperation = get_bool(body, "parent_cooperation", default=True)

    if notice_date > start_date:
        fail("ERR_INVALID_REQUEST",
             "notice_date must fall on or before unilateral_start_date.")
    if end_date < start_date:
        fail("ERR_INVALID_REQUEST",
             "unilateral_end_date must fall on or after unilateral_start_date.")

    student = student_or_404(student_id)
    account_or_404(account_id)
    if superseding_id is not None:
        placement_or_404(superseding_id)

    check_scope(student)

    row = new_row("reimbursement", {
        "student_id": student_id,
        "superseding_placement_id": superseding_id,
        "fiscal_account_id": account_id,
        "unilateral_school_name": school_name,
        "claimed_tuition_cents": claimed_tuition,
        "claimed_transport_cents": claimed_transport,
        "claimed_instructional_days": claimed_days,
        "notice_date": notice_date.isoformat(),
        "unilateral_start_date": start_date.isoformat(),
        "unilateral_end_date": end_date.isoformat(),
        "prior_district_offer_date": offer_date.isoformat() if offer_date else None,
        "parent_cooperation": cooperation,
        "award_basis": None,
        "equitable_reduction_pct": 0,
        "eligible_amount_cents": 0,
        "awarded_amount_cents": 0,
        "awarded_tuition_cents": 0,
        "awarded_transport_cents": 0,
        "remand_round": 0,
        "status": "FILED",
    })
    db.reimbursements[row["id"]] = row
    return created(public(row))


@endpoint(bp, "POST", "/reimbursement-claims/<claim_id>/adjudicate", (HEARING_ADJUDICATOR,))
def adjudicate_claim(claim_id):
    claim = reimbursement_or_404(claim_id)
    body = read_body(("award_basis", "equitable_findings"))
    award_basis = get_enum(body, "award_basis", AWARD_BASES)
    findings = get_text(body, "equitable_findings", required=False, default=None)

    if claim["status"] not in ("FILED", "REMANDED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a FILED or REMANDED claim may be adjudicated.")

    if award_basis == "equitable_actual_cost":
        trimmed = (findings or "").strip()
        if len(trimmed) < MIN_EQUITABLE_FINDINGS_CHARS:
            fail("ERR_EQUITABLE_FINDINGS_REQUIRED",
                 "The equitable basis requires findings of at least thirty characters.")

    claim_start = parse_date(claim["unilateral_start_date"])
    claim_end = parse_date(claim["unilateral_end_date"])
    for placement in db.placements.values():
        if placement["student_id"] != claim["student_id"] or placement["status"] != "ACTIVE":
            continue
        p_start = parse_date(placement["start_date"])
        p_end = parse_date(placement["end_date"])
        if p_start is None or p_end is None:
            continue
        if claim_start <= p_end and p_start <= claim_end:
            fail("ERR_CONCURRENT_DISTRICT_PLACEMENT",
                 "An active district placement covers part of the claimed period.")

    computed = reimbursement_award(claim, award_basis)
    account = db.accounts.get(claim["fiscal_account_id"])
    pays = computed["status"] in ("AWARDED_FULL", "AWARDED_PARTIAL")
    if pays:
        if account is None or account["available_cents"] < computed["awarded_amount_cents"]:
            fail("ERR_INSUFFICIENT_FISCAL_AUTHORITY",
                 "The appropriation cannot cover the award.")

    claim.update(computed)
    touch(claim)
    if pays and computed["awarded_amount_cents"]:
        disburse_direct(account, computed["awarded_amount_cents"])
    return ok(public(claim))


@endpoint(bp, "POST", "/reimbursement-claims/<claim_id>/remand", (HEARING_ADJUDICATOR,))
def remand_claim(claim_id):
    claim = reimbursement_or_404(claim_id)
    body = read_body(("remand_reason",))
    get_text(body, "remand_reason")

    if claim["status"] not in ("AWARDED_PARTIAL", "DENIED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only an AWARDED_PARTIAL or DENIED claim may be remanded.")
    if claim["remand_round"] >= MAX_REMAND_ROUNDS:
        fail("ERR_MAX_ROUNDS_EXCEEDED", "The remand cycle is bounded at two rounds.")

    reversal = claim["awarded_amount_cents"]
    account = db.accounts.get(claim["fiscal_account_id"])
    if reversal > 0 and account is not None:
        reverse_direct(account, reversal)

    claim["awarded_amount_cents"] = 0
    claim["awarded_tuition_cents"] = 0
    claim["awarded_transport_cents"] = 0
    claim["eligible_amount_cents"] = 0
    claim["equitable_reduction_pct"] = 0
    claim["award_basis"] = None
    claim["status"] = "REMANDED"
    claim["remand_round"] += 1
    touch(claim)
    return ok(public(claim))


# =========================================================================
# funding claims
# =========================================================================

@endpoint(bp, "GET", "/funding-claims", ALL_ROLES)
def list_funding_claims():
    return collection(db.funding.values(), [
        ("placement_id", q_str("placement_id")),
        ("claim_type", q_str("claim_type")),
        ("status", q_str("status")),
        ("fiscal_year", q_int("fiscal_year")),
        ("source", q_str("source")),
    ])


@endpoint(bp, "GET", "/funding-claims/<claim_id>", ALL_ROLES)
def get_funding_claim(claim_id):
    return single(funding_or_404(claim_id))


@endpoint(bp, "POST", "/funding-claims", (FISCAL_OFFICER,))
def create_funding_claim():
    body = read_body(("placement_id", "claim_type", "fiscal_year"))
    placement_id = get_id(body, "placement_id")
    claim_type = get_enum(body, "claim_type", CLAIM_TYPES)
    fiscal_year = get_int(body, "fiscal_year", minimum=2020, maximum=2100)

    placement = placement_or_404(placement_id)

    schedule = db.rate_schedules.get(placement["rate_schedule_id"])
    if (schedule is None
            or schedule["fiscal_year"] != fiscal_year
            or placement["contract_executed_at"] is None):
        fail("ERR_FUNDING_CLAIM_LINKAGE_MISMATCH",
             "The fiscal year must match the pinned schedule and the contract must be executed.")

    student = db.students.get(placement["student_id"])
    if claim_type == "MEDICAID":
        if (student is None or not student["medicaid_eligible"]
                or not student["medicaid_consent_on_file"]):
            fail("ERR_MEDICAID_CONSENT_MISSING",
                 "Medicaid eligibility and signed parental consent are both required.")

    for existing in db.funding.values():
        if (existing["placement_id"] == placement_id
                and existing["claim_type"] == claim_type
                and existing["fiscal_year"] == fiscal_year
                and existing["status"] in ("ELIGIBLE", "SUBMITTED")):
            fail("ERR_DUPLICATE_RESOURCE",
                 "A live claim already exists for this placement, type and fiscal year.")

    if claim_type == "HIGH_COST_FUND":
        if placement["paid_total_ytd_cents"] < HIGH_COST_TRIGGER_CENTS:
            fail("ERR_HIGH_COST_THRESHOLD_NOT_MET",
                 "The placement has not paid enough to qualify for the high-cost fund.")
        eligible_base, tier_rate, reimbursable = high_cost_amounts(placement, fiscal_year)
        hours = 0
        if reimbursable <= 0:
            fail("ERR_HIGH_COST_CAP_EXHAUSTED",
                 "The student's annual high-cost ceiling is already exhausted.")
    else:
        hours, eligible_base, tier_rate, reimbursable = medicaid_amounts(placement)

    row = new_row("funding", {
        "placement_id": placement_id,
        "claim_type": claim_type,
        "fiscal_year": fiscal_year,
        "eligible_base_cents": eligible_base,
        "billable_service_hours": hours,
        "tier_rate": tier_rate,
        "reimbursable_amount_cents": reimbursable,
        "source": "MANUAL",
        "status": "ELIGIBLE",
        "submitted_at": None,
        "state_claim_reference": None,
    })
    db.funding[row["id"]] = row

    if student is not None:
        student["projected_state_recovery_cents"] += reimbursable
        touch(student)
    return created(public(row))


@endpoint(bp, "POST", "/funding-claims/<claim_id>/submit-to-state", (FISCAL_OFFICER,))
def submit_funding_claim(claim_id):
    claim = funding_or_404(claim_id)
    body = read_body(("state_claim_reference",))
    reference = get_text(body, "state_claim_reference")

    if claim["status"] != "ELIGIBLE":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only an ELIGIBLE claim may be submitted to the state.")
    if claim["reimbursable_amount_cents"] < 1:
        fail("ERR_INVALID_STATE_TRANSITION", "A claim worth nothing may not be filed.")

    if claim["claim_type"] == "MEDICAID":
        placement = db.placements.get(claim["placement_id"])
        student = db.students.get(placement["student_id"]) if placement else None
        if (student is None or not student["medicaid_eligible"]
                or not student["medicaid_consent_on_file"]):
            fail("ERR_MEDICAID_CONSENT_MISSING",
                 "Medicaid consent has been withdrawn since the claim was computed.")

    claim["status"] = "SUBMITTED"
    claim["submitted_at"] = now_iso()
    claim["state_claim_reference"] = reference
    touch(claim)
    return ok(public(claim))
