"""Composite setup helpers — multi-step preambles tests can reuse.

Travel & Expense Reimbursement lifecycles cross several entities before
interesting claims can be tested:

    Admin → seeds PerDiemRate + Employees (Traveler with Manager link,
            FinanceReviewer, OOPApprover).
    Traveler → creates Trip (DRAFT).
    Traveler → submits Trip (DRAFT→SUBMITTED, provisional budget).
    Manager → approves Trip (SUBMITTED→APPROVED, pins rate id).
    Traveler → opens ExpenseReport (DRAFT), adds ExpenseLines, attaches
               Receipts, submits report (DRAFT→SUBMITTED).
    FinanceReviewer → claims report (SUBMITTED→IN_REVIEW), approves
               (IN_REVIEW→APPROVED) or rejects (IN_REVIEW→REJECTED).
    FinanceReviewer → disburses APPROVED report (APPROVED→REIMBURSED).

IDENTITY THREADING — PRD §2.1 (verbatim):

    "The first four are entity-backed: when `X-User-Role` is any of
    `TRAVELER`, `MANAGER`, `FINANCE_REVIEWER`, or `OOP_APPROVER`, the
    `X-User-ID` value is the `id` of the acting `Employee`, and any
    ownership check on a resource that references an `Employee` ...
    compares that foreign-key field to `X-User-ID`."

Every fixture below that creates a Trip / Report / Line / Receipt /
OOPApproval mints headers via the per-instance builder
`make_{role}_headers(employee.id)` with the real `Employee.id`. The
shared placeholders in TEST_USERS are NEVER substituted here.

SEGREGATION OF DUTIES — PRD §2.7 #7 (verbatim):

    "segregation of duties on approval and disbursement endpoints,
    returning `ERR_SEGREGATION_OF_DUTIES`."

PRD §3.5 (verbatim): "the manager must not themselves be the traveler",
"FINANCE_REVIEWER who is not the traveler", "The acting approver must
not be the traveler, and must not be the same person who acted at L1".

Fixtures default to DISTINCT Employees for Traveler, Manager,
FinanceReviewer, OOPApprover. Tests that exercise SoD failure
deliberately reuse the traveler's id.

Setup calls use `get_success_data` (lenient 2xx validator) so setup
failures surface as 'Setup failed' rather than confusing assertion
failures downstream.
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    LLF_VARIANCE_TOLERANCE_CENTS,
    OCR_CONFIDENCE_VERIFY_THRESHOLD,
    TEST_DEFAULTS,
)
from .factories import (
    add_days,
    attach_receipt_payload,
    clock_advance_payload,
    create_employee_payload,
    create_expense_report_payload,
    create_flight_line_payload,
    create_lodging_line_payload,
    create_meal_line_payload,
    create_mileage_line_payload,
    create_oop_approval_payload,
    create_per_diem_rate_payload,
    create_receipt_payload,
    create_rental_car_line_payload,
    create_trip_payload,
    create_virtual_card_payload,
    lock_virtual_card_payload,
    unique_city,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_finance_reviewer_headers,
    make_manager_headers,
    make_oop_approver_headers,
    make_traveler_headers,
)


# ===========================================================================
# Admin / employee / rate setup
# ===========================================================================
def admin_headers() -> Dict[str, str]:
    """Convenience accessor — admin headers shared across fixtures."""
    return TEST_USERS["admin_headers"]


def seed_per_diem_rate(
    *,
    city: Optional[str] = None,
    state: Optional[str] = None,
    effective_from: Optional[str] = None,
    effective_to: Optional[str] = None,
    lodging_cap_cents: Optional[int] = None,
    mie_cap_cents: Optional[int] = None,
    is_high_cost_locality: bool = False,
) -> Dict[str, Any]:
    """Create a PerDiemRate via /per-diem-rates."""
    payload = create_per_diem_rate_payload(
        city=city,
        state=state,
        effective_from=effective_from,
        effective_to=effective_to,
        lodging_cap_cents=lodging_cap_cents,
        mie_cap_cents=mie_cap_cents,
        is_high_cost_locality=is_high_cost_locality,
    )
    res = api_client.create_per_diem_rate(payload, admin_headers())
    return get_success_data(res)


def seed_default_boston_rate(
    *,
    is_high_cost_locality: bool = False,
) -> Dict[str, Any]:
    """Seed the canonical Boston MA rate used by most fixtures.

    Because the test runner does not reset server state between tests,
    each call would otherwise pile up another Boston/MA rate covering
    the same window and a downstream resolver could pin a different
    `PerDiemRate.id` than the one cached in `cast["rate"]`. To keep the
    one-rate-per-window invariant the tests assume, the seeder first
    queries `/per-diem-rates?city=Boston&state=MA&effective_on=<window>`;
    when a matching rate already exists it is returned as-is, otherwise
    a fresh row is created.
    """
    city = str(TEST_DEFAULTS["TRIP_DESTINATION_CITY"])
    state = str(TEST_DEFAULTS["TRIP_DESTINATION_STATE"])
    eff_from = str(TEST_DEFAULTS["RATE_EFFECTIVE_FROM"])
    eff_to = str(TEST_DEFAULTS["RATE_EFFECTIVE_TO"])
    # Probe for an existing rate covering effective_from.
    res = api_client.list_per_diem_rates(
        admin_headers(),
        params={"city": city, "state": state, "effective_on": eff_from},
    )
    if res.status_code < 300:
        body = res.json()
        rows = body.get("data") or []
        for r in rows:
            if (
                r.get("effective_from") == eff_from
                and r.get("effective_to") == eff_to
                and bool(r.get("is_high_cost_locality"))
                == bool(is_high_cost_locality)
            ):
                return r
    return seed_per_diem_rate(
        city=city,
        state=state,
        effective_from=eff_from,
        effective_to=eff_to,
        lodging_cap_cents=int(TEST_DEFAULTS["RATE_LODGING_CAP_CENTS"]),
        mie_cap_cents=int(TEST_DEFAULTS["RATE_MIE_CAP_CENTS"]),
        is_high_cost_locality=is_high_cost_locality,
    )


def seed_manager() -> Dict[str, Any]:
    """Create a MANAGER employee."""
    payload = create_employee_payload(role="MANAGER")
    res = api_client.create_employee(payload, admin_headers())
    return get_success_data(res)


def seed_finance_reviewer() -> Dict[str, Any]:
    payload = create_employee_payload(role="FINANCE_REVIEWER")
    res = api_client.create_employee(payload, admin_headers())
    return get_success_data(res)


def seed_oop_approver() -> Dict[str, Any]:
    payload = create_employee_payload(role="OOP_APPROVER")
    res = api_client.create_employee(payload, admin_headers())
    return get_success_data(res)


def seed_traveler(manager_id: str) -> Dict[str, Any]:
    """Create a TRAVELER employee whose `manager_id` points to the given
    manager. PRD §3.12 requires `manager_id` for TRAVELER.
    """
    payload = create_employee_payload(
        role="TRAVELER", manager_id=manager_id,
    )
    res = api_client.create_employee(payload, admin_headers())
    return get_success_data(res)


# ===========================================================================
# Standard cast: one Manager + one Traveler + one Finance + one OOP approver
# all linked correctly.  Used by most lifecycle fixtures.
# ===========================================================================
def seed_standard_cast(
    *,
    seed_oop: bool = True,
    seed_rate: bool = True,
) -> Dict[str, Any]:
    """Seed all the entities a Trip / Report flow needs.

    Returns a dict with keys: manager, traveler, finance, oop, rate.
    `oop` is None when seed_oop=False; `rate` is None when seed_rate=False.
    """
    manager = seed_manager()
    traveler = seed_traveler(manager_id=manager["id"])
    finance = seed_finance_reviewer()
    oop = seed_oop_approver() if seed_oop else None
    rate = seed_default_boston_rate() if seed_rate else None
    return {
        "manager": manager,
        "traveler": traveler,
        "finance": finance,
        "oop": oop,
        "rate": rate,
    }


# ===========================================================================
# Trip lifecycle helpers — PRD §3.1
# ===========================================================================
def create_draft_trip(
    *,
    traveler: Dict[str, Any],
    destination_city: Optional[str] = None,
    destination_state: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **trip_overrides: Any,
) -> Dict[str, Any]:
    """Create a Trip in DRAFT state for the given traveler.

    Acts as the traveler — TRAVELER is entity_backed, so headers are
    minted from traveler["id"] (PRD §2.1).
    """
    payload = create_trip_payload(
        traveler_id=traveler["id"],
        destination_city=destination_city,
        destination_state=destination_state,
        start_date=start_date,
        end_date=end_date,
        **trip_overrides,
    )
    res = api_client.create_trip(
        payload, make_traveler_headers(traveler["id"]),
    )
    return get_success_data(res)


def submit_trip(trip: Dict[str, Any], traveler: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.submit_trip(
        trip["id"], make_traveler_headers(traveler["id"]),
    )
    return get_success_data(res)


def approve_trip(trip: Dict[str, Any], manager: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.approve_trip(
        trip["id"], make_manager_headers(manager["id"]),
    )
    return get_success_data(res)


def reject_trip(
    trip: Dict[str, Any], manager: Dict[str, Any],
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    payload = {"reason": reason} if reason else None
    res = api_client.reject_trip(
        trip["id"], make_manager_headers(manager["id"]), payload,
    )
    return get_success_data(res)


def request_changes_trip(
    trip: Dict[str, Any], manager: Dict[str, Any],
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    payload = {"notes": notes} if notes else None
    res = api_client.request_changes_trip(
        trip["id"], make_manager_headers(manager["id"]), payload,
    )
    return get_success_data(res)


def cancel_trip(
    trip: Dict[str, Any], traveler: Dict[str, Any],
) -> Dict[str, Any]:
    res = api_client.cancel_trip(
        trip["id"], make_traveler_headers(traveler["id"]),
    )
    return get_success_data(res)


# ===========================================================================
# Tier 1 / 2 fixtures — APPROVED trip with cast already wired.
# ===========================================================================
def setup_approved_trip(
    *,
    destination_city: Optional[str] = None,
    destination_state: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    seed_oop: bool = True,
    extra_rate_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Standard cast + APPROVED Trip with pinned rate.

    Returns dict with keys: manager, traveler, finance, oop, rate, trip.
    """
    cast = seed_standard_cast(seed_oop=seed_oop, seed_rate=False)
    if extra_rate_kwargs is None:
        rate = seed_default_boston_rate()
    else:
        rate = seed_per_diem_rate(**extra_rate_kwargs)
    cast["rate"] = rate

    trip = create_draft_trip(
        traveler=cast["traveler"],
        destination_city=destination_city or rate["city"],
        destination_state=destination_state or rate["state"],
        start_date=start_date,
        end_date=end_date,
    )
    trip = submit_trip(trip, cast["traveler"])
    trip = approve_trip(trip, cast["manager"])
    cast["trip"] = trip
    return cast


def setup_submitted_trip(
    **kwargs: Any,
) -> Dict[str, Any]:
    """Cast + SUBMITTED Trip (no manager approval yet)."""
    cast = seed_standard_cast(seed_rate=False)
    extra = kwargs.pop("extra_rate_kwargs", None)
    if extra is None:
        rate = seed_default_boston_rate()
    else:
        rate = seed_per_diem_rate(**extra)
    cast["rate"] = rate
    trip = create_draft_trip(traveler=cast["traveler"], **kwargs)
    trip = submit_trip(trip, cast["traveler"])
    cast["trip"] = trip
    return cast


def setup_draft_trip(**kwargs: Any) -> Dict[str, Any]:
    """Cast + DRAFT Trip (never submitted)."""
    cast = seed_standard_cast(seed_rate=False)
    extra = kwargs.pop("extra_rate_kwargs", None)
    if extra is None:
        rate = seed_default_boston_rate()
    else:
        rate = seed_per_diem_rate(**extra)
    cast["rate"] = rate
    trip = create_draft_trip(traveler=cast["traveler"], **kwargs)
    cast["trip"] = trip
    return cast


# ===========================================================================
# Receipt helpers — PRD §3.4
# ===========================================================================
def upload_receipt(
    *,
    uploader: Dict[str, Any],
    merchant_total_cents: int,
    ocr_extracted_date: Optional[str] = None,
    ocr_confidence: float = 0.95,
) -> Dict[str, Any]:
    """Upload a receipt as `uploader` (TRAVELER entity_backed).

    `uploader_employee_id` is read from X-User-ID per PRD §3.4 —
    headers MUST be minted from the actual employee id.
    """
    payload = create_receipt_payload(
        merchant_total_cents=merchant_total_cents,
        ocr_extracted_date=(
            ocr_extracted_date
            or str(TEST_DEFAULTS["TRIP_START_DATE"])
        ),
        ocr_confidence=ocr_confidence,
    )
    res = api_client.create_receipt(
        payload, make_traveler_headers(uploader["id"]),
    )
    return get_success_data(res)


def attach_receipt_to_line(
    *,
    line: Dict[str, Any],
    receipt: Dict[str, Any],
    traveler: Dict[str, Any],
) -> Dict[str, Any]:
    res = api_client.attach_receipt(
        line["id"],
        attach_receipt_payload(receipt_id=receipt["id"]),
        make_traveler_headers(traveler["id"]),
    )
    return get_success_data(res)


# ===========================================================================
# ExpenseReport / ExpenseLine helpers — PRD §3.3
# ===========================================================================
def create_expense_report(
    *,
    trip: Dict[str, Any],
    traveler: Dict[str, Any],
) -> Dict[str, Any]:
    payload = create_expense_report_payload(trip_id=trip["id"])
    res = api_client.create_expense_report(
        payload, make_traveler_headers(traveler["id"]),
    )
    return get_success_data(res)


def add_meal_line(
    *,
    report: Dict[str, Any],
    traveler: Dict[str, Any],
    expense_date: str,
    meal_type: str,
    amount_claimed_cents: Optional[int] = None,
    per_diem_method: Optional[str] = None,
    meal_was_provided: bool = False,
) -> Dict[str, Any]:
    # PRD §3.3: "For categories other than `MILEAGE`, the traveler
    # supplies `amount_claimed_cents` directly". A provided-meal line
    # has its reimbursable amount forced to zero (PRD §3.8) but the
    # claimed amount field is still required on the wire; default to 0
    # so the payload is well-formed when the test omits it.
    if meal_was_provided and amount_claimed_cents is None:
        amount_claimed_cents = 0
    payload = create_meal_line_payload(
        expense_date=expense_date,
        meal_type=meal_type,
        amount_claimed_cents=amount_claimed_cents,
        per_diem_method=per_diem_method,
        meal_was_provided=meal_was_provided,
    )
    res = api_client.create_expense_line(
        report["id"], payload, make_traveler_headers(traveler["id"]),
    )
    return get_success_data(res)


def add_lodging_line(
    *,
    report: Dict[str, Any],
    traveler: Dict[str, Any],
    expense_date: str,
    amount_claimed_cents: int,
    per_diem_method: str = "ACTUAL",
    receipt_id: Optional[str] = None,
    virtual_card_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_lodging_line_payload(
        expense_date=expense_date,
        amount_claimed_cents=amount_claimed_cents,
        per_diem_method=per_diem_method,
        receipt_id=receipt_id,
        virtual_card_id=virtual_card_id,
    )
    res = api_client.create_expense_line(
        report["id"], payload, make_traveler_headers(traveler["id"]),
    )
    return get_success_data(res)


def add_rental_car_line(
    *,
    report: Dict[str, Any],
    traveler: Dict[str, Any],
    expense_date: str,
    amount_claimed_cents: int,
    rental_days: int,
    cdw_purchased: bool = False,
    receipt_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_rental_car_line_payload(
        expense_date=expense_date,
        amount_claimed_cents=amount_claimed_cents,
        rental_days=rental_days,
        cdw_purchased=cdw_purchased,
        receipt_id=receipt_id,
    )
    res = api_client.create_expense_line(
        report["id"], payload, make_traveler_headers(traveler["id"]),
    )
    return get_success_data(res)


def add_mileage_line(
    *,
    report: Dict[str, Any],
    traveler: Dict[str, Any],
    expense_date: str,
    miles_driven: float,
) -> Dict[str, Any]:
    payload = create_mileage_line_payload(
        expense_date=expense_date,
        miles_driven=miles_driven,
    )
    res = api_client.create_expense_line(
        report["id"], payload, make_traveler_headers(traveler["id"]),
    )
    return get_success_data(res)


def add_flight_line(
    *,
    report: Dict[str, Any],
    traveler: Dict[str, Any],
    expense_date: str,
    amount_claimed_cents: int,
    receipt_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_flight_line_payload(
        expense_date=expense_date,
        amount_claimed_cents=amount_claimed_cents,
        receipt_id=receipt_id,
    )
    res = api_client.create_expense_line(
        report["id"], payload, make_traveler_headers(traveler["id"]),
    )
    return get_success_data(res)


def submit_report(
    *, report: Dict[str, Any], traveler: Dict[str, Any],
) -> Dict[str, Any]:
    res = api_client.submit_expense_report(
        report["id"], make_traveler_headers(traveler["id"]),
    )
    return get_success_data(res)


def claim_report(
    *, report: Dict[str, Any], finance: Dict[str, Any],
) -> Dict[str, Any]:
    res = api_client.claim_expense_report(
        report["id"], make_finance_reviewer_headers(finance["id"]),
    )
    return get_success_data(res)


def approve_report(
    *, report: Dict[str, Any], finance: Dict[str, Any],
) -> Dict[str, Any]:
    res = api_client.approve_expense_report(
        report["id"], make_finance_reviewer_headers(finance["id"]),
    )
    return get_success_data(res)


def reject_report(
    *, report: Dict[str, Any], finance: Dict[str, Any],
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    payload = {"reason": reason} if reason else None
    res = api_client.reject_expense_report(
        report["id"],
        make_finance_reviewer_headers(finance["id"]),
        payload,
    )
    return get_success_data(res)


def request_changes_report(
    *, report: Dict[str, Any], finance: Dict[str, Any],
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    payload = {"notes": notes} if notes else None
    res = api_client.request_changes_expense_report(
        report["id"],
        make_finance_reviewer_headers(finance["id"]),
        payload,
    )
    return get_success_data(res)


def disburse_report(
    *, report: Dict[str, Any], finance: Dict[str, Any],
) -> Dict[str, Any]:
    res = api_client.disburse_expense_report(
        report["id"], make_finance_reviewer_headers(finance["id"]),
    )
    return get_success_data(res)


# ===========================================================================
# Virtual card helpers — PRD §3.2
# ===========================================================================
def create_virtual_card(
    *,
    trip: Dict[str, Any],
    traveler: Dict[str, Any],
    credit_limit_cents: int,
) -> Dict[str, Any]:
    payload = create_virtual_card_payload(
        trip_id=trip["id"], credit_limit_cents=credit_limit_cents,
    )
    res = api_client.create_virtual_card(
        payload, make_traveler_headers(traveler["id"]),
    )
    return get_success_data(res)


def issue_virtual_card(
    *, card: Dict[str, Any], finance: Dict[str, Any],
) -> Dict[str, Any]:
    res = api_client.issue_virtual_card(
        card["id"], make_finance_reviewer_headers(finance["id"]),
    )
    return get_success_data(res)


def activate_virtual_card(
    *, card: Dict[str, Any], traveler: Dict[str, Any],
) -> Dict[str, Any]:
    res = api_client.activate_virtual_card(
        card["id"], make_traveler_headers(traveler["id"]),
    )
    return get_success_data(res)


def lock_virtual_card(
    *, card: Dict[str, Any], finance: Dict[str, Any],
    locked_reason: str = "manual_audit",
) -> Dict[str, Any]:
    res = api_client.lock_virtual_card(
        card["id"], lock_virtual_card_payload(locked_reason=locked_reason),
        make_finance_reviewer_headers(finance["id"]),
    )
    return get_success_data(res)


def unlock_virtual_card(
    *, card: Dict[str, Any], finance: Dict[str, Any],
) -> Dict[str, Any]:
    res = api_client.unlock_virtual_card(
        card["id"], make_finance_reviewer_headers(finance["id"]),
    )
    return get_success_data(res)


def close_virtual_card(
    *, card: Dict[str, Any], finance: Dict[str, Any],
) -> Dict[str, Any]:
    res = api_client.close_virtual_card(
        card["id"], make_finance_reviewer_headers(finance["id"]),
    )
    return get_success_data(res)


def setup_active_virtual_card(
    *,
    cast: Optional[Dict[str, Any]] = None,
    credit_limit_cents: int = 50000,
) -> Dict[str, Any]:
    """APPROVED trip + REQUESTED→ISSUED→ACTIVE virtual card.

    Returns the cast dict extended with `card` key.
    """
    if cast is None:
        cast = setup_approved_trip()
    card = create_virtual_card(
        trip=cast["trip"],
        traveler=cast["traveler"],
        credit_limit_cents=credit_limit_cents,
    )
    card = issue_virtual_card(card=card, finance=cast["finance"])
    card = activate_virtual_card(card=card, traveler=cast["traveler"])
    cast["card"] = card
    return cast


# ===========================================================================
# OutOfPolicyApproval helpers — PRD §3.5
# ===========================================================================
def open_oop_approval(
    *,
    line: Dict[str, Any],
    traveler: Dict[str, Any],
    justification: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_oop_approval_payload(
        expense_line_id=line["id"], justification=justification,
    )
    res = api_client.create_oop_approval(
        payload, make_traveler_headers(traveler["id"]),
    )
    return get_success_data(res)


def oop_l1_approve(
    *, approval: Dict[str, Any], manager: Dict[str, Any],
) -> Dict[str, Any]:
    res = api_client.oop_l1_approve(
        approval["id"], make_manager_headers(manager["id"]),
    )
    return get_success_data(res)


def oop_l2_approve(
    *, approval: Dict[str, Any], finance: Dict[str, Any],
) -> Dict[str, Any]:
    res = api_client.oop_l2_approve(
        approval["id"], make_finance_reviewer_headers(finance["id"]),
    )
    return get_success_data(res)


def oop_final_approve(
    *, approval: Dict[str, Any], oop_approver: Dict[str, Any],
) -> Dict[str, Any]:
    res = api_client.oop_final_approve(
        approval["id"], make_oop_approver_headers(oop_approver["id"]),
    )
    return get_success_data(res)


# ===========================================================================
# Bigger composite fixtures — explicitly motivated by the difficulty index
# in SCAFFOLD_DIFFICULTY_DESIGN.yaml.
# ===========================================================================
def setup_report_with_meal_line_in_policy(
    *,
    cast: Optional[Dict[str, Any]] = None,
    meal_type: str = "BREAKFAST",
    per_diem_method: str = "PER_DIEM",
    amount_claimed_cents: int = 0,
) -> Dict[str, Any]:
    """APPROVED trip + DRAFT report + one IN_POLICY meal line (per-diem).

    Useful as a baseline for adding additional lines. PRD §3.3 requires
    `amount_claimed_cents` on non-MILEAGE create payloads; default to 0
    to keep the line trivially IN_POLICY when PER_DIEM is used.
    """
    if cast is None:
        cast = setup_approved_trip()
    report = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    line = add_meal_line(
        report=report,
        traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        meal_type=meal_type,
        per_diem_method=per_diem_method,
        amount_claimed_cents=amount_claimed_cents,
    )
    cast["report"] = report
    cast["line"] = line
    return cast


def setup_report_with_oop_meal_line(
    *,
    cast: Optional[Dict[str, Any]] = None,
    over_cap_amount_cents: Optional[int] = None,
    meal_type: str = "BREAKFAST",
) -> Dict[str, Any]:
    """APPROVED trip + DRAFT report + one OUT_OF_POLICY meal line.

    PRD §3.8: ACTUAL method with amount_claimed_cents above per-meal cap
    flags policy_status=OUT_OF_POLICY. Boston rate mie_cap=8000 means
    breakfast cap = 8000 * 0.25 = 2000. Over-cap default 3000 cents.

    PRD §3.4: "A receipt is required when the line's category is
    `LODGING`, `RENTAL_CAR`, or `FLIGHT`, or when `amount_claimed_cents`
    is strictly greater than 7500 cents." When the test asks for a meal
    line whose claim exceeds the $75 receipt threshold, the fixture
    auto-attaches a receipt so the impl's receipt-required gate does
    not pre-empt the OUT_OF_POLICY policy check the test wants to
    exercise.
    """
    if cast is None:
        cast = setup_approved_trip()
    if over_cap_amount_cents is None:
        over_cap_amount_cents = 3000  # > 2000 breakfast cap on default rate
    report = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    receipt_id: Optional[str] = None
    if over_cap_amount_cents > 7500:
        receipt = upload_receipt(
            uploader=cast["traveler"],
            merchant_total_cents=over_cap_amount_cents,
            ocr_extracted_date=cast["trip"]["start_date"],
        )
        receipt_id = receipt["id"]
    # Build the payload via the factory so the per_diem_method + receipt
    # threading is uniform with add_meal_line's path.
    payload = create_meal_line_payload(
        expense_date=cast["trip"]["start_date"],
        meal_type=meal_type,
        amount_claimed_cents=over_cap_amount_cents,
        per_diem_method="ACTUAL",
        meal_was_provided=False,
        receipt_id=receipt_id,
    )
    res = api_client.create_expense_line(
        report["id"], payload, make_traveler_headers(cast["traveler"]["id"]),
    )
    line = get_success_data(res)
    cast["report"] = report
    cast["line"] = line
    return cast


def setup_report_with_rental_then_mileage(
    *,
    miles_driven: float = 80.0,
    rental_amount_cents: int = 5000,
    rental_days: int = 1,
) -> Dict[str, Any]:
    """APPROVED trip + report + RENTAL_CAR line + same-date MILEAGE line.

    Used by the mileage_rental_overlap difficulty-design instance.
    The MILEAGE calculation should detect the rental on the same date
    and apply the tiered formula (30 mi at 67c + excess at 21c).
    Returns dict with keys cast + report, rental_line, mileage_line.
    """
    cast = setup_approved_trip()
    report = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    # Receipt required for RENTAL_CAR (PRD §3.4).
    rental_receipt = upload_receipt(
        uploader=cast["traveler"],
        merchant_total_cents=rental_amount_cents,
        ocr_extracted_date=cast["trip"]["start_date"],
    )
    rental_line = add_rental_car_line(
        report=report,
        traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        amount_claimed_cents=rental_amount_cents,
        rental_days=rental_days,
        receipt_id=rental_receipt["id"],
    )
    mileage_line = add_mileage_line(
        report=report,
        traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        miles_driven=miles_driven,
    )
    cast["report"] = report
    cast["rental_line"] = rental_line
    cast["mileage_line"] = mileage_line
    cast["rental_receipt"] = rental_receipt
    return cast


def setup_report_with_standalone_mileage(
    *, miles_driven: float = 30.5,
) -> Dict[str, Any]:
    """APPROVED trip + report + single MILEAGE line, NO rental.

    Used by the per-leg-round difficulty-design instance.
    """
    cast = setup_approved_trip()
    report = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    line = add_mileage_line(
        report=report,
        traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        miles_driven=miles_driven,
    )
    cast["report"] = report
    cast["line"] = line
    return cast


def setup_report_with_flight_line(
    *,
    amount_claimed_cents: int,
    receipt_total_cents: Optional[int] = None,
    extra_rate_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """APPROVED trip + report + one FLIGHT line at a specified claim.

    PRD §3.4: FLIGHT category always requires a receipt. Receipt total
    defaults to amount_claimed_cents so OCR verifies cleanly.
    Used by LLF variance boundary tests.
    """
    cast = setup_approved_trip(extra_rate_kwargs=extra_rate_kwargs)
    report = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    receipt = upload_receipt(
        uploader=cast["traveler"],
        merchant_total_cents=(
            receipt_total_cents
            if receipt_total_cents is not None
            else amount_claimed_cents
        ),
        ocr_extracted_date=cast["trip"]["start_date"],
    )
    line = add_flight_line(
        report=report,
        traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        amount_claimed_cents=amount_claimed_cents,
        receipt_id=receipt["id"],
    )
    cast["report"] = report
    cast["receipt"] = receipt
    cast["line"] = line
    return cast


def setup_report_submitted_for_oop_chain(
    *,
    over_cap_amount_cents: int = 3000,
    meal_type: str = "BREAKFAST",
) -> Dict[str, Any]:
    """APPROVED trip + report with single OUT_OF_POLICY meal line, OOP
    approval opened (AWAITING_L1).
    """
    cast = setup_report_with_oop_meal_line(
        over_cap_amount_cents=over_cap_amount_cents,
        meal_type=meal_type,
    )
    approval = open_oop_approval(
        line=cast["line"], traveler=cast["traveler"],
    )
    cast["approval"] = approval
    return cast


def setup_lodging_only_report(
    *,
    nights: int = 2,
    nightly_amount_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """APPROVED trip with N+1 day window + report with N LODGING lines.

    Each lodging line gets its own receipt (PRD §3.4 LODGING always
    requires a receipt). Used by per-diem provisional/final pinning
    tests.
    """
    if nightly_amount_cents is None:
        nightly_amount_cents = int(TEST_DEFAULTS["RATE_LODGING_CAP_CENTS"])
    cast = setup_approved_trip()
    report = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    lodging_lines = []
    start = cast["trip"]["start_date"]
    for n in range(nights):
        d = add_days(start, n)
        receipt = upload_receipt(
            uploader=cast["traveler"],
            merchant_total_cents=nightly_amount_cents,
            ocr_extracted_date=d,
        )
        line = add_lodging_line(
            report=report,
            traveler=cast["traveler"],
            expense_date=d,
            amount_claimed_cents=nightly_amount_cents,
            per_diem_method="ACTUAL",
            receipt_id=receipt["id"],
        )
        lodging_lines.append(line)
    cast["report"] = report
    cast["lodging_lines"] = lodging_lines
    return cast


def setup_submitted_report_with_meal(
    *,
    meal_was_provided: bool = True,
    meal_type: str = "BREAKFAST",
) -> Dict[str, Any]:
    """APPROVED trip + DRAFT report + provided-meal line (no receipt
    needed) + SUBMIT the report. Used by submit-with-zero-lines empty-set
    boundary test (where this exact fixture is the 'one-line' counterpoint).
    """
    cast = setup_approved_trip()
    report = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    line = add_meal_line(
        report=report,
        traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        meal_type=meal_type,
        meal_was_provided=meal_was_provided,
    )
    report = submit_report(report=report, traveler=cast["traveler"])
    cast["report"] = report
    cast["line"] = line
    return cast


def setup_in_review_report(
    *, claimer: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """APPROVED trip + DRAFT report + one provided meal line + SUBMIT +
    /claim by FINANCE_REVIEWER → IN_REVIEW.

    Returns cast extended with `report` and `line`. If `claimer` is None,
    the standard cast finance reviewer is used.
    """
    cast = setup_submitted_report_with_meal(meal_was_provided=True)
    reviewer = claimer or cast["finance"]
    cast["report"] = claim_report(
        report=cast["report"], finance=reviewer,
    )
    return cast


def setup_report_with_card_charge_in_review(
    *,
    credit_limit_cents: int = 50000,
    charge_amount_cents: int = 10000,
) -> Dict[str, Any]:
    """APPROVED trip + ACTIVE card + report with one LODGING line that
    charged the card, SUBMIT + /claim → IN_REVIEW.

    Used by report-reject → line-void → card-deauth cascade test.
    """
    cast = setup_active_virtual_card(
        credit_limit_cents=credit_limit_cents,
    )
    report = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    receipt = upload_receipt(
        uploader=cast["traveler"],
        merchant_total_cents=charge_amount_cents,
        ocr_extracted_date=cast["trip"]["start_date"],
    )
    line = add_lodging_line(
        report=report,
        traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        amount_claimed_cents=charge_amount_cents,
        per_diem_method="ACTUAL",
        receipt_id=receipt["id"],
        virtual_card_id=cast["card"]["id"],
    )
    # Add a second meal line so report has multiple lines (cascade
    # narrative refers to "both lines VOIDED").
    meal_line = add_meal_line(
        report=report,
        traveler=cast["traveler"],
        expense_date=cast["trip"]["start_date"],
        meal_type="BREAKFAST",
        meal_was_provided=True,
    )
    report = submit_report(report=report, traveler=cast["traveler"])
    report = claim_report(report=report, finance=cast["finance"])
    cast["report"] = report
    cast["lodging_line"] = line
    cast["meal_line"] = meal_line
    return cast


def setup_report_changes_requested_cycle_initial(
    *,
    extra_finance: bool = True,
) -> Dict[str, Any]:
    """APPROVED trip + DRAFT report + one provided meal + SUBMIT, ready
    for two distinct finance reviewers (F1 and F2) to take turns
    claiming. If `extra_finance` is True, a second FinanceReviewer is
    seeded under the key `finance2`.
    """
    cast = setup_submitted_report_with_meal(meal_was_provided=True)
    if extra_finance:
        cast["finance2"] = seed_finance_reviewer()
    return cast


# ===========================================================================
# Clock advance — PRD §3.12
# ===========================================================================
def clock_advance(*, to_iso: str) -> Dict[str, Any]:
    """Advance the logical clock to `to_iso` via ADMIN."""
    payload = clock_advance_payload(to_iso=to_iso)
    res = api_client.clock_advance(payload, admin_headers())
    return get_success_data(res)


# ===========================================================================
# Generic helpers
# ===========================================================================
def get_trip(trip_id: str, *, viewer: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch a trip as `viewer` — any entity_backed role works."""
    role = viewer.get("role", "TRAVELER")
    if role == "TRAVELER":
        headers = make_traveler_headers(viewer["id"])
    elif role == "MANAGER":
        headers = make_manager_headers(viewer["id"])
    elif role == "FINANCE_REVIEWER":
        headers = make_finance_reviewer_headers(viewer["id"])
    elif role == "OOP_APPROVER":
        headers = make_oop_approver_headers(viewer["id"])
    else:
        headers = make_admin_headers(viewer["id"])
    return get_success_data(api_client.get_trip(trip_id, headers))


def get_card(
    card_id: str, *, viewer: Dict[str, Any],
) -> Dict[str, Any]:
    role = viewer.get("role", "FINANCE_REVIEWER")
    if role == "TRAVELER":
        headers = make_traveler_headers(viewer["id"])
    elif role == "FINANCE_REVIEWER":
        headers = make_finance_reviewer_headers(viewer["id"])
    else:
        headers = make_admin_headers(viewer["id"])
    return get_success_data(api_client.get_virtual_card(card_id, headers))


def get_report(
    report_id: str, *, viewer: Dict[str, Any],
) -> Dict[str, Any]:
    role = viewer.get("role", "TRAVELER")
    if role == "TRAVELER":
        headers = make_traveler_headers(viewer["id"])
    elif role == "MANAGER":
        headers = make_manager_headers(viewer["id"])
    elif role == "FINANCE_REVIEWER":
        headers = make_finance_reviewer_headers(viewer["id"])
    else:
        headers = make_admin_headers(viewer["id"])
    return get_success_data(api_client.get_expense_report(report_id, headers))


def get_line(
    line_id: str, *, viewer: Dict[str, Any],
) -> Dict[str, Any]:
    role = viewer.get("role", "TRAVELER")
    if role == "TRAVELER":
        headers = make_traveler_headers(viewer["id"])
    elif role == "MANAGER":
        headers = make_manager_headers(viewer["id"])
    elif role == "FINANCE_REVIEWER":
        headers = make_finance_reviewer_headers(viewer["id"])
    else:
        headers = make_admin_headers(viewer["id"])
    return get_success_data(api_client.get_expense_line(line_id, headers))


def get_oop_approval(
    approval_id: str, *, viewer: Dict[str, Any],
) -> Dict[str, Any]:
    role = viewer.get("role", "TRAVELER")
    if role == "TRAVELER":
        headers = make_traveler_headers(viewer["id"])
    elif role == "MANAGER":
        headers = make_manager_headers(viewer["id"])
    elif role == "FINANCE_REVIEWER":
        headers = make_finance_reviewer_headers(viewer["id"])
    elif role == "OOP_APPROVER":
        headers = make_oop_approver_headers(viewer["id"])
    else:
        headers = make_admin_headers(viewer["id"])
    return get_success_data(api_client.get_oop_approval(approval_id, headers))


__all__ = [
    # admin / employees / rate
    "admin_headers",
    "seed_per_diem_rate",
    "seed_default_boston_rate",
    "seed_manager",
    "seed_finance_reviewer",
    "seed_oop_approver",
    "seed_traveler",
    "seed_standard_cast",
    # trip lifecycle
    "create_draft_trip",
    "submit_trip",
    "approve_trip",
    "reject_trip",
    "request_changes_trip",
    "cancel_trip",
    "setup_approved_trip",
    "setup_submitted_trip",
    "setup_draft_trip",
    # receipts
    "upload_receipt",
    "attach_receipt_to_line",
    # reports + lines
    "create_expense_report",
    "add_meal_line",
    "add_lodging_line",
    "add_rental_car_line",
    "add_mileage_line",
    "add_flight_line",
    "submit_report",
    "claim_report",
    "approve_report",
    "reject_report",
    "request_changes_report",
    "disburse_report",
    # virtual cards
    "create_virtual_card",
    "issue_virtual_card",
    "activate_virtual_card",
    "lock_virtual_card",
    "unlock_virtual_card",
    "close_virtual_card",
    "setup_active_virtual_card",
    # OOP approvals
    "open_oop_approval",
    "oop_l1_approve",
    "oop_l2_approve",
    "oop_final_approve",
    # composite fixtures
    "setup_report_with_meal_line_in_policy",
    "setup_report_with_oop_meal_line",
    "setup_report_with_rental_then_mileage",
    "setup_report_with_standalone_mileage",
    "setup_report_with_flight_line",
    "setup_report_submitted_for_oop_chain",
    "setup_lodging_only_report",
    "setup_submitted_report_with_meal",
    "setup_in_review_report",
    "setup_report_with_card_charge_in_review",
    "setup_report_changes_requested_cycle_initial",
    # clock
    "clock_advance",
    # accessors
    "get_trip",
    "get_card",
    "get_report",
    "get_line",
    "get_oop_approval",
]
