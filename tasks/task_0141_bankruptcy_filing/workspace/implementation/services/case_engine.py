"""Bankruptcy case engine.

Encapsulates the state-machine transitions for Case, Plan, Claim, and the
cross-aggregate CollectionAction insertion gate. Every transition:
  - validates preconditions in priority order, raising ApiError with the
    scaffold-defined error_id;
  - applies side effects atomically (under store.lock);
  - bumps updated_at + version on the affected rows so cascaded mutations
    refresh bookkeeping the same way direct mutations do (PRD §2.4 / §2.10).

OCC handling: when a mutating request body includes `version`, callers compare
it against the row's current version BEFORE the mutation commits. A mismatch
raises ERR_STALE_DATA (409). When `version` is omitted, no OCC check runs.
"""

from datetime import timedelta

from db import store
from errors import make_error
from utils import iso_now, new_uuid
from services.calculations import (
    compute_schedule_completeness,
    latest_schedule,
    run_means_test,
    run_trustee_payment_waterfall,
)


# ---------------------------------------------------------------------------
# Common mutation helpers
# ---------------------------------------------------------------------------
def touch(row: dict) -> None:
    """Refresh updated_at and bump version (mutable entities only)."""
    row["updated_at"] = iso_now(store.now())
    row["version"] = row.get("version", 1) + 1


def check_occ(row: dict, body_version) -> None:
    """If the request body carries a `version`, verify it matches the row's."""
    if body_version is None:
        return
    if not isinstance(body_version, int):
        raise make_error("ERR_BAD_REQUEST", "version must be an integer.")
    if body_version != row["version"]:
        raise make_error("ERR_STALE_DATA")


# ---------------------------------------------------------------------------
# Look-ups + ownership
# ---------------------------------------------------------------------------
def get_case_or_404(case_id: str) -> dict:
    case = store.cases.get(case_id)
    if case is None:
        raise make_error("ERR_NOT_FOUND", f"Case {case_id} not found.")
    return case


def get_plan_scoped_or_404(case_id: str, plan_id: str) -> dict:
    # case existence first (left-to-right path resolution).
    get_case_or_404(case_id)
    plan = store.plans.get(plan_id)
    if plan is None or plan["case_id"] != case_id:
        raise make_error("ERR_NOT_FOUND", f"Plan {plan_id} not found under case {case_id}.")
    return plan


def get_claim_scoped_or_404(case_id: str, claim_id: str) -> dict:
    get_case_or_404(case_id)
    claim = store.claims.get(claim_id)
    if claim is None or claim["case_id"] != case_id:
        raise make_error("ERR_NOT_FOUND", f"Claim {claim_id} not found under case {case_id}.")
    return claim


def active_plan_for_case(case_id: str) -> dict | None:
    """Return the Plan in {PROPOSED, CONFIRMED, IN_REPAYMENT} (=PROPOSED for Plan,
    case-level mapping) for this case, or None.

    Per scaffold concurrency rule: at most one Plan per Case in the active set
    {PROPOSED, CONFIRMED}. We extend with IN_REPAYMENT (which corresponds to
    Plan.status=CONFIRMED while case.status=IN_REPAYMENT, since Plan transitions
    PROPOSED→CONFIRMED→COMPLETED|DEFAULTED|WITHDRAWN — there's no IN_REPAYMENT
    state on Plan; we treat any non-terminal Plan as active).
    """
    for plan in store.plans.values():
        if plan["case_id"] == case_id and plan["status"] in {"PROPOSED", "CONFIRMED"}:
            return plan
    return None


# ===========================================================================
# Debtor / Creditor creation helpers
# ===========================================================================
def create_debtor(*, full_name: str, household_size, state_code: str) -> dict:
    if not isinstance(household_size, int) or household_size < 1:
        raise make_error("ERR_BAD_REQUEST", "household_size must be an integer >= 1.")
    if not isinstance(state_code, str) or len(state_code) != 2 or not state_code.isupper() or not state_code.isalpha():
        raise make_error("ERR_BAD_REQUEST", "state_code must be exactly 2 uppercase letters.")
    if not isinstance(full_name, str) or not full_name.strip():
        raise make_error("ERR_BAD_REQUEST", "full_name must be a non-empty string.")
    now = iso_now(store.now())
    debtor = {
        "id": new_uuid(),
        "full_name": full_name,
        "household_size": household_size,
        "state_code": state_code,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.debtors[debtor["id"]] = debtor
    return debtor


def create_creditor(*, name: str, creditor_type: str) -> dict:
    from config import CREDITOR_TYPES

    if not isinstance(name, str) or not name.strip():
        raise make_error("ERR_BAD_REQUEST", "name must be a non-empty string.")
    if creditor_type not in CREDITOR_TYPES:
        raise make_error("ERR_BAD_REQUEST", "creditor_type must be SECURED, PRIORITY, or GENERAL_UNSECURED.")
    now = iso_now(store.now())
    creditor = {
        "id": new_uuid(),
        "name": name,
        "creditor_type": creditor_type,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.creditors[creditor["id"]] = creditor
    return creditor


# ===========================================================================
# Case creation + transitions
# ===========================================================================
def create_case(*, debtor_id: str, chapter_requested: str, acting_user_id: str | None) -> dict:
    from config import CHAPTERS

    debtor = store.debtors.get(debtor_id)
    if debtor is None:
        raise make_error("ERR_NOT_FOUND", f"Debtor {debtor_id} not found.")
    # Ownership: Debtor role X-User-ID must equal Debtor.id.
    if acting_user_id is not None and acting_user_id != debtor_id:
        raise make_error("ERR_FORBIDDEN", "Debtor may only open cases for themselves.")
    if chapter_requested not in CHAPTERS:
        raise make_error("ERR_BAD_REQUEST", "chapter_requested must be CHAPTER_7 or CHAPTER_13.")
    now = iso_now(store.now())
    case = {
        "id": new_uuid(),
        "debtor_id": debtor_id,
        "chapter_requested": chapter_requested,
        "chapter_effective": None,
        "status": "DRAFT",
        "filing_date": None,
        "meeting_341_date": None,
        "means_test_result_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.cases[case["id"]] = case
    return case


def withdraw_draft_case(case: dict, *, acting_user_id: str | None) -> dict:
    if acting_user_id is not None and acting_user_id != case["debtor_id"]:
        raise make_error("ERR_FORBIDDEN", "Debtor may only withdraw their own case.")
    if case["status"] != "DRAFT":
        raise make_error("ERR_INVALID_STATE", "Case must be in DRAFT to be withdrawn.")
    case["status"] = "WITHDRAWN_PRE_FILE"
    touch(case)
    return case


# ---------------------------------------------------------------------------
# Schedule submission
# ---------------------------------------------------------------------------
def submit_schedule(case: dict, *, schedule_type: str, line_items, acting_user_id: str | None) -> dict:
    from config import SCHEDULE_TYPES

    if acting_user_id is not None and acting_user_id != case["debtor_id"]:
        raise make_error("ERR_FORBIDDEN", "Debtor may only submit schedules for their own case.")
    if schedule_type not in SCHEDULE_TYPES:
        raise make_error("ERR_BAD_REQUEST", "schedule_type must be one of A..J.")
    if not isinstance(line_items, list):
        raise make_error("ERR_BAD_REQUEST", "line_items must be an array.")
    # Validate line items + compute total.
    total_cents = 0
    normalised: list[dict] = []
    for item in line_items:
        if not isinstance(item, dict):
            raise make_error("ERR_BAD_REQUEST", "Each line_item must be an object.")
        label = item.get("label", "")
        amount = item.get("amount_cents")
        if not isinstance(amount, int):
            raise make_error("ERR_BAD_REQUEST", "line_item.amount_cents must be an integer.")
        normalised.append({"label": label, "amount_cents": amount})
        total_cents += amount

    now = iso_now(store.now())
    new_id = new_uuid()
    # Supersede the previous unsuperseded snapshot of the same type for this case.
    for sched in store.schedules.values():
        if (
            sched["case_id"] == case["id"]
            and sched["schedule_type"] == schedule_type
            and sched.get("superseded_by_id") is None
        ):
            sched["superseded_by_id"] = new_id

    schedule = {
        "id": new_id,
        "case_id": case["id"],
        "schedule_type": schedule_type,
        "line_items": normalised,
        "total_cents": total_cents,
        "superseded_by_id": None,
        "created_at": now,
    }
    store.schedules[new_id] = schedule
    # Case.schedule_completeness is computed on read so no field to update,
    # but touch the case to reflect the new schedule submission as a mutation.
    touch(case)
    return schedule


# ---------------------------------------------------------------------------
# Means test run
# ---------------------------------------------------------------------------
def run_case_means_test(case: dict) -> dict:
    result = run_means_test(case["id"])
    now = iso_now(store.now())
    mtr_id = new_uuid()
    row = {
        "id": mtr_id,
        "case_id": case["id"],
        "created_at": now,
        **result,
    }
    store.means_test_results[mtr_id] = row
    case["means_test_result_id"] = mtr_id
    touch(case)
    return row


# ---------------------------------------------------------------------------
# DRAFT → FILED
# ---------------------------------------------------------------------------
def file_case(case: dict, *, acting_user_id: str | None) -> dict:
    if acting_user_id is not None and acting_user_id != case["debtor_id"]:
        raise make_error("ERR_FORBIDDEN", "Debtor may only file their own case.")
    if case["status"] != "DRAFT":
        raise make_error("ERR_INVALID_STATE", "Case must be in DRAFT to be filed.")
    # Priority 9: schedule completeness.
    missing = compute_schedule_completeness(case["id"])
    if missing:
        raise make_error("ERR_SCHEDULES_INCOMPLETE", f"Missing schedules: {missing}")
    # Priority 10: means test must exist.
    mtr_id = case.get("means_test_result_id")
    if mtr_id is None or mtr_id not in store.means_test_results:
        raise make_error("ERR_MEANS_TEST_NOT_RUN")
    mtr = store.means_test_results[mtr_id]
    # Priority 11: presumption-of-abuse Ch7 gate.
    if case["chapter_requested"] == "CHAPTER_7" and mtr["presumption_of_abuse"]:
        raise make_error("ERR_PRESUMPTION_OF_ABUSE")
    # Commit side effects atomically.
    case["filing_date"] = iso_now(store.now())
    case["chapter_effective"] = "CHAPTER_7" if case["chapter_requested"] == "CHAPTER_7" else "CHAPTER_13"
    case["status"] = "FILED"
    touch(case)
    return case


# ---------------------------------------------------------------------------
# FILED → MEETING_SCHEDULED
# ---------------------------------------------------------------------------
def schedule_341(case: dict, *, meeting_date_iso: str) -> dict:
    if case["status"] != "FILED":
        raise make_error("ERR_INVALID_STATE", "Case must be FILED to schedule 341.")
    from utils import parse_iso8601

    try:
        proposed = parse_iso8601(meeting_date_iso)
    except Exception:
        raise make_error("ERR_BAD_REQUEST", "meeting_date must be an ISO 8601 timestamp.")
    filed = case.get("filing_date")
    if filed is None:
        raise make_error("ERR_INVALID_STATE", "Case has no filing_date.")
    filed_dt = parse_iso8601(filed)
    threshold = filed_dt + timedelta(days=21)
    if proposed < threshold:
        raise make_error("ERR_MEETING_TOO_EARLY")
    case["meeting_341_date"] = iso_now(proposed)
    case["status"] = "MEETING_SCHEDULED"
    touch(case)
    return case


# ---------------------------------------------------------------------------
# MEETING_SCHEDULED → MEETING_HELD (+ claim cascade FILED → ALLOWED)
# ---------------------------------------------------------------------------
def conduct_341(case: dict) -> dict:
    if case["status"] != "MEETING_SCHEDULED":
        raise make_error("ERR_INVALID_STATE", "Case must be MEETING_SCHEDULED to conduct 341.")
    from utils import parse_iso8601

    meeting_dt = parse_iso8601(case["meeting_341_date"])
    if store.now() < meeting_dt:
        raise make_error("ERR_MEETING_DATE_NOT_REACHED")
    # Side effect: all FILED claims for this case → ALLOWED. Each cascaded
    # claim mutation refreshes updated_at + version (PRD §2.10).
    for claim in store.claims.values():
        if claim["case_id"] == case["id"] and claim["status"] == "FILED":
            if claim["amount_cents"] <= 0:
                # Should not be possible given creation-time validation.
                raise make_error("ERR_CLAIM_AMOUNT_INVALID")
            claim["status"] = "ALLOWED"
            touch(claim)
    case["status"] = "MEETING_HELD"
    touch(case)
    return case


# ---------------------------------------------------------------------------
# Trustee dismissal — from MEETING_SCHEDULED, PLAN_PROPOSED, or IN_REPAYMENT.
# ---------------------------------------------------------------------------
def dismiss_case(case: dict) -> dict:
    status = case["status"]
    if status not in {"MEETING_SCHEDULED", "PLAN_PROPOSED", "IN_REPAYMENT"}:
        raise make_error("ERR_INVALID_STATE", f"Case in state {status} cannot be dismissed by trustee.")
    if status == "IN_REPAYMENT":
        plan = _confirmed_plan_for_case(case["id"])
        if plan is None:
            raise make_error("ERR_INVALID_STATE", "IN_REPAYMENT case has no active plan.")
        missed = sum(
            1
            for pmt in store.trustee_payments.values()
            if pmt["plan_id"] == plan["id"] and pmt["status"] == "MISSED"
        )
        if missed < 3:
            raise make_error("ERR_DISMISSAL_NOT_WARRANTED")
        # Side effects: Plan.status → DEFAULTED, all ALLOWED claims → NON_DISCHARGEABLE_REMAINS.
        plan["status"] = "DEFAULTED"
        touch(plan)
        for claim in store.claims.values():
            if claim["case_id"] == case["id"] and claim["status"] == "ALLOWED":
                claim["status"] = "NON_DISCHARGEABLE_REMAINS"
                touch(claim)
    elif status == "PLAN_PROPOSED":
        # PRD §3.11: PLAN_PROPOSED dismissal has no precondition; the active
        # PROPOSED plan should also be considered withdrawn.
        plan = active_plan_for_case(case["id"])
        if plan is not None and plan["status"] == "PROPOSED":
            plan["status"] = "WITHDRAWN"
            touch(plan)
    case["status"] = "DISMISSED"
    touch(case)
    return case


def _confirmed_plan_for_case(case_id: str) -> dict | None:
    for plan in store.plans.values():
        if plan["case_id"] == case_id and plan["status"] == "CONFIRMED":
            return plan
    return None


# ---------------------------------------------------------------------------
# Discharge — judge action.
# ---------------------------------------------------------------------------
def discharge_case(case: dict) -> dict:
    status = case["status"]
    if status not in {"MEETING_HELD", "IN_REPAYMENT"}:
        raise make_error("ERR_INVALID_STATE", f"Case in state {status} cannot be discharged.")

    if status == "MEETING_HELD":
        # Ch7 path only — Ch13 case at MEETING_HELD has not yet completed plan.
        if case["chapter_effective"] != "CHAPTER_7":
            raise make_error("ERR_PLAN_NOT_COMPLETE", "Chapter 13 case must complete plan first.")
        # Ch7 discharge: exemption-partition pass only.
        _exemption_partition(case["id"])
    else:
        # IN_REPAYMENT → DISCHARGED — Ch13 path.
        plan = _confirmed_plan_for_case(case["id"])
        if plan is None:
            raise make_error("ERR_INVALID_STATE", "IN_REPAYMENT case has no confirmed plan.")
        paid = sum(
            pmt["amount_cents"]
            for pmt in store.trustee_payments.values()
            if pmt["plan_id"] == plan["id"] and pmt["status"] == "APPLIED"
        )
        missed = sum(
            1
            for pmt in store.trustee_payments.values()
            if pmt["plan_id"] == plan["id"] and pmt["status"] == "MISSED"
        )
        if paid < plan["planned_total_cents"]:
            raise make_error("ERR_PLAN_NOT_COMPLETE")
        if missed > 0:
            raise make_error("ERR_PLAN_IN_DEFAULT")
        # Side effects: Plan.status → COMPLETED, waterfall runs (informational
        # invariant check), then exemption partition runs.
        plan["paid_to_date_cents"] = paid  # snapshot for waterfall computation
        run_trustee_payment_waterfall(case["id"], plan)
        plan["status"] = "COMPLETED"
        touch(plan)
        _exemption_partition(case["id"])

    case["status"] = "DISCHARGED"
    touch(case)
    return case


def _exemption_partition(case_id: str) -> None:
    """Move every ALLOWED claim on the case to DISCHARGED or NON_DISCHARGEABLE_REMAINS
    by is_dischargeable. Partition is total — sum of amount_cents preserved.
    """
    for claim in store.claims.values():
        if claim["case_id"] == case_id and claim["status"] == "ALLOWED":
            claim["status"] = "DISCHARGED" if claim["is_dischargeable"] else "NON_DISCHARGEABLE_REMAINS"
            touch(claim)


# ===========================================================================
# Claim ops
# ===========================================================================
def create_claim(
    case: dict,
    *,
    creditor_id: str,
    claim_class: str,
    amount_cents,
    is_dischargeable,
    acting_user_id: str | None,
) -> dict:
    from config import CREDITOR_TYPES

    creditor = store.creditors.get(creditor_id)
    if creditor is None:
        raise make_error("ERR_NOT_FOUND", f"Creditor {creditor_id} not found.")
    if acting_user_id is not None and acting_user_id != creditor_id:
        raise make_error("ERR_FORBIDDEN", "Creditor may only file claims in their own name.")
    if claim_class not in CREDITOR_TYPES:
        raise make_error("ERR_BAD_REQUEST", "claim_class must be SECURED, PRIORITY, or GENERAL_UNSECURED.")
    if not isinstance(amount_cents, int):
        raise make_error("ERR_BAD_REQUEST", "amount_cents must be an integer.")
    if amount_cents <= 0:
        raise make_error("ERR_CLAIM_AMOUNT_INVALID")
    if claim_class != creditor["creditor_type"]:
        raise make_error("ERR_CLAIM_CLASS_MISMATCH")
    if not isinstance(is_dischargeable, bool):
        raise make_error("ERR_BAD_REQUEST", "is_dischargeable must be a boolean.")

    now = iso_now(store.now())
    claim = {
        "id": new_uuid(),
        "case_id": case["id"],
        "creditor_id": creditor_id,
        "claim_class": claim_class,
        "amount_cents": amount_cents,
        "is_dischargeable": is_dischargeable,
        "status": "FILED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.claims[claim["id"]] = claim
    return claim


def disallow_claim(case: dict, claim: dict) -> dict:
    if claim["status"] != "FILED":
        raise make_error("ERR_INVALID_STATE", "Only FILED claims may be disallowed.")
    if case["status"] not in {"FILED", "MEETING_SCHEDULED"}:
        raise make_error("ERR_INVALID_STATE", "Disallow requires case in FILED or MEETING_SCHEDULED.")
    claim["status"] = "DISALLOWED"
    touch(claim)
    return claim


# ===========================================================================
# Plan ops
# ===========================================================================
def create_plan(
    case: dict,
    *,
    proposed_monthly_payment_cents,
    plan_months,
    acting_user_id: str | None,
) -> dict:
    if acting_user_id is not None and acting_user_id != case["debtor_id"]:
        raise make_error("ERR_FORBIDDEN", "Debtor may only submit plans for their own case.")
    # PRD §3.8/§3.12: the at-most-one-plan-per-case rule pre-empts the
    # case-state gate. The "second plan insert" scenario described in PRD
    # is only reachable when the case has already transitioned to
    # PLAN_PROPOSED (because the first plan caused that transition); PRD
    # mandates that this scenario returns ERR_PLAN_ALREADY_EXISTS, which
    # is only consistent with the active-plan check firing before the
    # case-status check.
    if active_plan_for_case(case["id"]) is not None:
        raise make_error("ERR_PLAN_ALREADY_EXISTS")
    # Priority 4: state check.
    if case["status"] != "MEETING_HELD":
        raise make_error("ERR_INVALID_STATE", "Plan submission requires case in MEETING_HELD.")
    # Priority 6: chapter check.
    if case.get("chapter_effective") != "CHAPTER_13":
        raise make_error("ERR_NOT_CHAPTER_13")
    # Validate types up front so the priority-13 check has well-formed inputs.
    if not isinstance(proposed_monthly_payment_cents, int) or proposed_monthly_payment_cents < 0:
        raise make_error("ERR_BAD_REQUEST", "proposed_monthly_payment_cents must be a non-negative integer.")
    if not isinstance(plan_months, int) or plan_months <= 0:
        raise make_error("ERR_BAD_REQUEST", "plan_months must be a positive integer.")
    # Priority 13: plan_months must match required_plan_months from MTR.
    mtr_id = case.get("means_test_result_id")
    if mtr_id is None:
        raise make_error("ERR_MEANS_TEST_NOT_RUN")
    mtr = store.means_test_results[mtr_id]
    if plan_months != mtr["required_plan_months"]:
        raise make_error("ERR_PLAN_MONTHS_MISMATCH")

    now = iso_now(store.now())
    plan = {
        "id": new_uuid(),
        "case_id": case["id"],
        "proposed_monthly_payment_cents": proposed_monthly_payment_cents,
        "plan_months": plan_months,
        "planned_total_cents": proposed_monthly_payment_cents * plan_months,
        "paid_to_date_cents": 0,
        "missed_payment_count": 0,
        "status": "PROPOSED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.plans[plan["id"]] = plan
    case["status"] = "PLAN_PROPOSED"
    touch(case)
    return plan


def withdraw_plan(case: dict, plan: dict, *, acting_user_id: str | None) -> dict:
    if acting_user_id is not None and acting_user_id != case["debtor_id"]:
        raise make_error("ERR_FORBIDDEN", "Debtor may only withdraw plans for their own case.")
    if case["status"] != "PLAN_PROPOSED":
        raise make_error("ERR_INVALID_STATE", "Plan withdrawal requires case in PLAN_PROPOSED.")
    if plan["status"] != "PROPOSED":
        raise make_error("ERR_INVALID_STATE", "Only PROPOSED plans may be withdrawn.")
    plan["status"] = "WITHDRAWN"
    touch(plan)
    case["status"] = "MEETING_HELD"
    touch(case)
    return plan


def confirm_plan(case: dict, plan: dict) -> dict:
    if case["status"] != "PLAN_PROPOSED":
        raise make_error("ERR_INVALID_STATE", "Plan confirmation requires case in PLAN_PROPOSED.")
    if plan["status"] != "PROPOSED":
        raise make_error("ERR_INVALID_STATE", "Only PROPOSED plans may be confirmed.")
    mtr_id = case.get("means_test_result_id")
    if mtr_id is None:
        raise make_error("ERR_MEANS_TEST_NOT_RUN")
    mtr = store.means_test_results[mtr_id]
    # Priority 12 then 13 — under-funding before months mismatch (per ordering).
    if plan["planned_total_cents"] < mtr["minimum_plan_total_cents"]:
        raise make_error("ERR_PLAN_UNDERFUNDED")
    if plan["plan_months"] != mtr["required_plan_months"]:
        raise make_error("ERR_PLAN_MONTHS_MISMATCH")
    plan["status"] = "CONFIRMED"
    touch(plan)
    case["status"] = "PLAN_CONFIRMED"
    touch(case)
    return plan


# ---------------------------------------------------------------------------
# TrusteePayment
# ---------------------------------------------------------------------------
def record_trustee_payment(
    case: dict,
    plan: dict,
    *,
    sequence_number,
    amount_cents,
    status: str,
) -> dict:
    if plan["status"] not in {"CONFIRMED"}:
        raise make_error("ERR_INVALID_STATE", "Payments require plan in CONFIRMED status.")
    if case["status"] not in {"PLAN_CONFIRMED", "IN_REPAYMENT"}:
        raise make_error("ERR_INVALID_STATE", "Payments require case in PLAN_CONFIRMED or IN_REPAYMENT.")
    if status not in {"APPLIED", "MISSED"}:
        raise make_error("ERR_BAD_REQUEST", "status must be APPLIED or MISSED.")
    if not isinstance(sequence_number, int):
        raise make_error("ERR_BAD_REQUEST", "sequence_number must be an integer.")
    if not isinstance(amount_cents, int) or amount_cents < 0:
        raise make_error("ERR_BAD_REQUEST", "amount_cents must be a non-negative integer.")
    # Sequence number must be in range [1, plan_months] and unique per plan.
    if sequence_number < 1 or sequence_number > plan["plan_months"]:
        raise make_error("ERR_PAYMENT_SEQUENCE_DUPLICATE")
    for existing in store.trustee_payments.values():
        if existing["plan_id"] == plan["id"] and existing["sequence_number"] == sequence_number:
            raise make_error("ERR_PAYMENT_SEQUENCE_DUPLICATE")

    now = iso_now(store.now())
    payment = {
        "id": new_uuid(),
        "plan_id": plan["id"],
        "sequence_number": sequence_number,
        "amount_cents": amount_cents,
        "status": status,
        "applied_at": now,
        "created_at": now,
    }
    store.trustee_payments[payment["id"]] = payment

    # Case PLAN_CONFIRMED → IN_REPAYMENT on first APPLIED payment with seq 1.
    if case["status"] == "PLAN_CONFIRMED" and status == "APPLIED" and sequence_number == 1:
        case["status"] = "IN_REPAYMENT"
        touch(case)

    return payment


# ===========================================================================
# CollectionAction (cross-aggregate; stay-gated insertion)
# ===========================================================================
def create_collection_action(
    *,
    creditor_id: str,
    case_id: str,
    action_kind: str,
    acting_user_id: str | None,
) -> tuple[dict, bool]:
    """Insert a CollectionAction. Returns (row, was_rejected).

    Per priority-5 validation, the stay check runs after auth/existence/state
    but BEFORE other business rules; if the stay is active, the row is still
    persisted with outcome=REJECTED_STAY and the caller raises 409.
    """
    from config import COLLECTION_ACTION_KINDS

    creditor = store.creditors.get(creditor_id)
    if creditor is None:
        raise make_error("ERR_NOT_FOUND", f"Creditor {creditor_id} not found.")
    if acting_user_id is not None and acting_user_id != creditor_id:
        raise make_error("ERR_FORBIDDEN", "Creditor may only act in their own name.")
    case = store.cases.get(case_id)
    if case is None:
        raise make_error("ERR_NOT_FOUND", f"Case {case_id} not found.")
    if action_kind not in COLLECTION_ACTION_KINDS:
        raise make_error("ERR_BAD_REQUEST", "action_kind must be GARNISH | LIEN | LAWSUIT | DUNNING_LETTER.")

    stay_active = case["status"] in {
        "FILED",
        "MEETING_SCHEDULED",
        "MEETING_HELD",
        "PLAN_PROPOSED",
        "PLAN_CONFIRMED",
        "IN_REPAYMENT",
    }
    now = iso_now(store.now())
    row = {
        "id": new_uuid(),
        "creditor_id": creditor_id,
        "case_id": case_id,
        "action_kind": action_kind,
        "outcome": "REJECTED_STAY" if stay_active else "PROCESSED",
        "rejected_reason": "AUTOMATIC_STAY_ACTIVE" if stay_active else "",
        "created_at": now,
    }
    store.collection_actions[row["id"]] = row
    return row, stay_active
