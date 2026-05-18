"""Core business engine — state transitions, cascades, payment-schedule
generation, clock advance, default/uplift handling.

All mutations on entities with common-fields refresh updated_at and
increment version (PRD §2.4 and §2.7 cascade rule).
"""
from __future__ import annotations

from config import (
    APR_UPLIFT_BPS,
    DISPOSITION_FEE_CENTS,
    DEFAULT_GRACE_DAYS,
    PURCHASE_OPTION_FEE_CENTS,
    UPLIFT_THRESHOLD,
)
from db import store
from errors import err_payment_due_date_collision
from services.calculations import (
    amortization_step,
    compute_default_rate,
    disposition_fee_for_election,
    lease_end_total_cents,
    loan_monthly_payment_cents,
    mileage_overage,
    mileage_penalty_cents,
)
from utils import new_uuid


# ── Entity stamping ────────────────────────────────────────────────────────


def stamp_create(entity: dict, common: bool = True) -> dict:
    """Set id / created_at / updated_at / version on a new entity.

    common=False is used for Payment / DelinquencyEvent / ClockEvent which
    have only id + created_at (PRD §2.4).
    """
    now = store.now()
    entity.setdefault("id", new_uuid())
    entity["created_at"] = now
    if common:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def stamp_update(entity: dict) -> None:
    """Bump updated_at and increment version for entities with common fields."""
    entity["updated_at"] = store.now()
    entity["version"] = int(entity.get("version", 1)) + 1


# ── Lookups (left-to-right path validation) ────────────────────────────────


def get_customer_or_404(customer_id):
    from errors import err_customer_not_found
    c = store.customers.get(customer_id)
    if c is None:
        raise err_customer_not_found()
    return c


def get_loan_contract_or_404(customer_id, contract_id):
    from errors import err_contract_not_found
    lc = store.loan_contracts.get(contract_id)
    if lc is None or lc["customer_id"] != customer_id:
        raise err_contract_not_found()
    return lc


def get_lease_contract_or_404(customer_id, contract_id):
    from errors import err_contract_not_found
    lc = store.lease_contracts.get(contract_id)
    if lc is None or lc["customer_id"] != customer_id:
        raise err_contract_not_found()
    return lc


def get_payment_or_404(customer_id, payment_id):
    from errors import err_payment_not_found
    p = store.payments.get(payment_id)
    if p is None or p["customer_id"] != customer_id:
        raise err_payment_not_found()
    return p


def get_gap_rider_or_404(customer_id, rider_id):
    from errors import err_rider_not_found
    g = store.gap_riders.get(rider_id)
    if g is None or g["customer_id"] != customer_id:
        raise err_rider_not_found()
    return g


def get_vehicle_or_404(vehicle_id):
    from errors import err_vehicle_not_found
    v = store.vehicles.get(vehicle_id)
    if v is None:
        raise err_vehicle_not_found()
    return v


def get_assessment_for_lease(customer_id, contract_id):
    """Return the active assessment row for this lease (latest one), or None."""
    candidates = [
        a for a in store.lease_end_assessments.values()
        if a["lease_contract_id"] == contract_id and a["customer_id"] == customer_id
    ]
    if not candidates:
        return None
    # Only one assessment is expected per lease at any time; return the
    # most-recently-created in case of duplicates.
    candidates.sort(key=lambda x: x["created_at"])
    return candidates[-1]


# ── Payment schedule generation ────────────────────────────────────────────


def generate_payment_schedule(contract: dict, contract_type: str) -> list:
    """Create term_months Payment rows for an activated contract.

    Each row's due_day_index = origination_day_index + period_index * 30.
    Enforces uniqueness of due_day_index per SCAFFOLD §1.4 priority 8.
    """
    payments = []
    origination = contract["origination_day_index"]
    term = contract["term_months"]
    contract_id = contract["id"]
    customer_id = contract["customer_id"]
    amount_due = contract["monthly_payment_cents"]

    # Collect existing per-contract due-day indexes for collision check (manual paths).
    existing_due_days = {
        p["due_day_index"]
        for p in store.payments.values()
        if p["contract_id"] == contract_id and p["status"] in {"SCHEDULED", "LATE", "DEFAULTED"}
    }

    for i in range(1, term + 1):
        due_day = origination + i * 30
        if due_day in existing_due_days:
            raise err_payment_due_date_collision()
        existing_due_days.add(due_day)
        p = {
            "customer_id": customer_id,
            "contract_id": contract_id,
            "contract_type": contract_type,
            "period_index": i,
            "due_day_index": due_day,
            "amount_due_cents": amount_due,
            "principal_portion_cents": None,
            "interest_portion_cents": None,
            "status": "SCHEDULED",
            "paid_day_index": None,
        }
        stamp_create(p, common=False)
        store.payments[p["id"]] = p
        payments.append(p)

    return payments


# ── Loan re-pricing on default uplift ──────────────────────────────────────


def reprice_scheduled_payments_on_loan(loan: dict) -> None:
    """Recompute monthly_payment_cents for the loan using new apr_bps and
    current remaining_principal_cents; re-snapshot every SCHEDULED Payment
    row's amount_due_cents to the new monthly figure.

    Forward-looking convention only — already-PAID payments are not touched.
    """
    new_monthly = loan_monthly_payment_cents(
        principal_cents=loan["remaining_principal_cents"] or 0,
        apr_bps=loan["apr_bps"],
        term_months=max(1, loan["payments_scheduled_count"] - loan["payments_made_count"]),
    )
    loan["monthly_payment_cents"] = new_monthly
    stamp_update(loan)
    for p in store.payments.values():
        if p["contract_id"] == loan["id"] and p["status"] == "SCHEDULED":
            p["amount_due_cents"] = new_monthly


# ── Default handling on a single payment ───────────────────────────────────


def apply_default_to_payment(payment: dict) -> None:
    """Transition a LATE payment to DEFAULTED with the §3.5 cascade.

    Side effects (executed in one logical transaction):
      1. payment.status = DEFAULTED.
      2. Customer.default_count += 1, default_rate recomputed.
      3. DelinquencyEvent appended.
      4. If default_count crosses UPLIFT_THRESHOLD for the first time AND
         parent contract is a LOAN: every ACTIVE LoanContract for this
         customer has apr_bps += APR_UPLIFT_BPS, monthly_payment_cents
         recomputed, and SCHEDULED payments re-snapshotted.
      5. If parent contract has >= 3 DEFAULTED payments, parent contract
         auto-transitions to DEFAULTED.
    """
    customer = store.customers[payment["customer_id"]]
    contract_type = payment["contract_type"]
    parent_id = payment["contract_id"]

    payment["status"] = "DEFAULTED"

    previous_default_count = customer["default_count"]
    customer["default_count"] = previous_default_count + 1
    customer["default_rate"] = compute_default_rate(
        customer["default_count"], customer["lifetime_payment_count"]
    )
    stamp_update(customer)

    # APR uplift cascade — only fires for LOAN-type defaults that cross
    # the threshold for the first time.
    uplift_applied = 0
    affected_loan_ids = []
    crossed_now = (
        previous_default_count < UPLIFT_THRESHOLD
        and customer["default_count"] >= UPLIFT_THRESHOLD
    )
    if crossed_now and contract_type == "LOAN":
        uplift_applied = APR_UPLIFT_BPS
        for loan in store.loan_contracts.values():
            if loan["customer_id"] != customer["id"]:
                continue
            if loan["status"] != "ACTIVE":
                continue
            loan["apr_bps"] = (loan.get("apr_bps") or loan.get("base_apr_bps") or 0) + APR_UPLIFT_BPS
            reprice_scheduled_payments_on_loan(loan)
            affected_loan_ids.append(loan["id"])

    # Loan-status cascade — parent contract → DEFAULTED if >= 3 defaulted payments.
    parent_defaulted_now = False
    if contract_type == "LOAN":
        parent = store.loan_contracts.get(parent_id)
        if parent is not None and parent["status"] == "ACTIVE":
            defaulted_count = sum(
                1 for p in store.payments.values()
                if p["contract_id"] == parent_id and p["status"] == "DEFAULTED"
            )
            if defaulted_count >= 3:
                parent["status"] = "DEFAULTED"
                stamp_update(parent)
                parent_defaulted_now = True
    else:
        # LEASE: same rule — 3+ defaulted payments → parent lease → DEFAULTED.
        parent = store.lease_contracts.get(parent_id)
        if parent is not None and parent["status"] == "ACTIVE":
            defaulted_count = sum(
                1 for p in store.payments.values()
                if p["contract_id"] == parent_id and p["status"] == "DEFAULTED"
            )
            if defaulted_count >= 3:
                parent["status"] = "DEFAULTED"
                stamp_update(parent)
                parent_defaulted_now = True

    # Append DelinquencyEvent.
    evt = {
        "customer_id": customer["id"],
        "payment_id": payment["id"],
        "default_count_after": customer["default_count"],
        "apr_uplift_bps_applied": uplift_applied,
        "affected_contract_ids": list(affected_loan_ids),
    }
    stamp_create(evt, common=False)
    store.delinquency_events[evt["id"]] = evt


# ── Lifetime payment counter ───────────────────────────────────────────────


def maybe_increment_lifetime_for_payment(payment: dict, customer: dict) -> None:
    """If this payment has not been counted toward lifetime_payment_count
    yet (i.e., status is moving from SCHEDULED → LATE/PAID/DEFAULTED for
    the first time), increment the customer's lifetime counter.

    We track this by remembering on the payment row whether its status has
    ever been one of {LATE, PAID, DEFAULTED}. Simpler: derive at need by
    recounting the "state-ever-touched" set across the customer's payments.

    For correctness and to avoid double-counting, the function checks a
    sentinel `_counted_for_lifetime` flag on the payment.
    """
    if not payment.get("_counted_for_lifetime"):
        payment["_counted_for_lifetime"] = True
        customer["lifetime_payment_count"] = customer.get("lifetime_payment_count", 0) + 1
        # default_rate depends on lifetime_payment_count denominator
        customer["default_rate"] = compute_default_rate(
            customer["default_count"], customer["lifetime_payment_count"]
        )
        stamp_update(customer)


# ── Clock advance ──────────────────────────────────────────────────────────


def advance_clock(customer: dict, days_advanced: int) -> dict:
    """Advance the per-customer clock and run the three sweeps.

    Returns the ClockEvent dict.
    """
    previous = customer["clock_day_index"]
    new = previous + days_advanced
    customer["clock_day_index"] = new
    stamp_update(customer)

    payments_due_now = 0
    payments_defaulted_now = 0

    # Sweep 1: SCHEDULED → LATE for payments whose due_day_index < new clock
    # (i.e., the due date has passed). Iterate over payments owned by
    # this customer in (contract_id, period_index) order for stability.
    customer_payments = sorted(
        [p for p in store.payments.values() if p["customer_id"] == customer["id"]],
        key=lambda p: (p["contract_id"], p["period_index"]),
    )
    for p in customer_payments:
        if p["status"] == "SCHEDULED" and p["due_day_index"] < new:
            p["status"] = "LATE"
            maybe_increment_lifetime_for_payment(p, customer)
        # Count payments that became due in this window (due_day_index
        # falls in closed interval [previous, new]).
        if previous <= p["due_day_index"] <= new:
            payments_due_now += 1

    # Sweep 2: LATE → DEFAULTED for payments where (clock - due) >= GRACE.
    # Re-fetch to include any newly-LATE rows.
    customer_payments = sorted(
        [p for p in store.payments.values() if p["customer_id"] == customer["id"]],
        key=lambda p: (p["contract_id"], p["period_index"]),
    )
    for p in customer_payments:
        if p["status"] == "LATE" and (new - p["due_day_index"]) >= DEFAULT_GRACE_DAYS:
            apply_default_to_payment(p)
            payments_defaulted_now += 1

    # Sweep 3: ACTIVE LeaseContract that has reached maturity AND has all
    # payments paid → MATURED (with DRAFT LeaseEndAssessment side-effect).
    for lease in list(store.lease_contracts.values()):
        if lease["customer_id"] != customer["id"]:
            continue
        if lease["status"] != "ACTIVE":
            continue
        if customer["clock_day_index"] < lease["maturity_day_index"]:
            continue
        if lease["payments_made_count"] != lease["payments_scheduled_count"]:
            continue
        lease["status"] = "MATURED"
        stamp_update(lease)
        create_draft_assessment(lease)

    # Append ClockEvent.
    evt = {
        "customer_id": customer["id"],
        "days_advanced": days_advanced,
        "new_clock_day_index": new,
        "payments_due_now": payments_due_now,
        "payments_defaulted_now": payments_defaulted_now,
    }
    stamp_create(evt, common=False)
    store.clock_events[evt["id"]] = evt
    return evt


# ── Lease maturity / assessment ────────────────────────────────────────────


def create_draft_assessment(lease: dict) -> dict:
    a = {
        "lease_contract_id": lease["id"],
        "customer_id": lease["customer_id"],
        "odometer_reading": None,
        "mileage_overage": 0,
        "mileage_penalty_cents": 0,
        "disposition_fee_cents": 0,
        "purchase_option_cents": 0,
        "total_due_cents": 0,
        "status": "DRAFT",
        "settled_day_index": None,
    }
    stamp_create(a, common=True)
    store.lease_end_assessments[a["id"]] = a
    return a


def recompute_assessment_totals(assessment: dict) -> None:
    assessment["total_due_cents"] = lease_end_total_cents(
        assessment.get("mileage_penalty_cents", 0),
        assessment.get("disposition_fee_cents", 0),
        assessment.get("purchase_option_cents", 0),
    )


def apply_odometer_reading(assessment: dict, lease: dict, reading: int) -> None:
    assessment["odometer_reading"] = reading
    assessment["mileage_overage"] = mileage_overage(reading, lease["mileage_allowance"])
    assessment["mileage_penalty_cents"] = mileage_penalty_cents(
        reading, lease["mileage_allowance"]
    )
    recompute_assessment_totals(assessment)


# ── Pay a Payment ──────────────────────────────────────────────────────────


def apply_payment_paid(payment: dict) -> None:
    """Transition a payment to PAID with all amortization / cascade side
    effects per §3.5.
    """
    customer = store.customers[payment["customer_id"]]
    payment["paid_day_index"] = customer["clock_day_index"]

    if payment["contract_type"] == "LOAN":
        loan = store.loan_contracts[payment["contract_id"]]
        principal, interest = amortization_step(
            remaining_principal_cents=loan["remaining_principal_cents"],
            amount_due_cents=payment["amount_due_cents"],
            apr_bps=loan["apr_bps"],
        )
        payment["principal_portion_cents"] = principal
        payment["interest_portion_cents"] = interest
        loan["remaining_principal_cents"] = loan["remaining_principal_cents"] - principal
        loan["total_principal_paid_cents"] = loan.get("total_principal_paid_cents", 0) + principal
        loan["total_interest_paid_cents"] = loan.get("total_interest_paid_cents", 0) + interest
        loan["payments_made_count"] = loan.get("payments_made_count", 0) + 1
        stamp_update(loan)

        # Payment.status already set to PAID by caller.
        payment["status"] = "PAID"
        # Lifetime counter — pay can be the first state-touch (SCHEDULED→PAID
        # without ever being LATE), so ensure increment is idempotent.
        maybe_increment_lifetime_for_payment(payment, customer)

        # Cascade: if final scheduled payment AND remaining_principal_cents == 0
        # → loan auto-transitions to PAID_OFF; gap rider auto-cancels.
        if (
            loan["payments_made_count"] >= loan["payments_scheduled_count"]
            and loan["remaining_principal_cents"] == 0
            and loan["status"] == "ACTIVE"
        ):
            loan["status"] = "PAID_OFF"
            stamp_update(loan)
            cascade_auto_cancel_gap_riders_for_contract(loan["id"])
    else:
        # LEASE: principal/interest portions are 0.
        lease = store.lease_contracts[payment["contract_id"]]
        payment["principal_portion_cents"] = 0
        payment["interest_portion_cents"] = 0
        lease["payments_made_count"] = lease.get("payments_made_count", 0) + 1
        stamp_update(lease)
        payment["status"] = "PAID"
        maybe_increment_lifetime_for_payment(payment, customer)


# ── Gap-rider cascade cancellation ─────────────────────────────────────────


def cascade_auto_cancel_gap_riders_for_contract(contract_id: str) -> None:
    """When a parent contract reaches PAID_OFF / CHARGED_OFF / CLOSED, any
    ACTIVE rider attached to it auto-CANCELLED with its own version bump
    and updated_at refresh (PRD §2.7).
    """
    for g in store.gap_riders.values():
        if g["contract_id"] != contract_id:
            continue
        if g["status"] != "ACTIVE":
            continue
        g["status"] = "CANCELLED"
        stamp_update(g)


# ── Lease election cascade ─────────────────────────────────────────────────


def apply_lease_election(lease: dict, assessment: dict, election: str) -> None:
    """Set the lease_end_election, mutate the assessment components per
    §3.9, recompute total_due_cents, move the assessment to ISSUED if it
    is still in DRAFT, and propagate the vehicle status change.
    """
    lease["lease_end_election"] = election

    if election == "PURCHASE":
        lease["status"] = "PURCHASED"
        assessment["purchase_option_cents"] = (
            lease["residual_value_cents"] + PURCHASE_OPTION_FEE_CENTS
        )
        assessment["disposition_fee_cents"] = 0
        # Vehicle: AVAILABLE → SOLD (must be SOLD per §3.9).
        veh = store.vehicles.get(lease["vehicle_id"])
        if veh is not None:
            veh["status"] = "SOLD"
            stamp_update(veh)
    elif election == "RENEW":
        lease["status"] = "RENEWED"
        assessment["disposition_fee_cents"] = 0
        assessment["purchase_option_cents"] = 0
        # No vehicle change on renewal.
    elif election == "RETURN":
        lease["status"] = "RETURNED"
        assessment["disposition_fee_cents"] = DISPOSITION_FEE_CENTS
        assessment["purchase_option_cents"] = 0
        veh = store.vehicles.get(lease["vehicle_id"])
        if veh is not None:
            veh["status"] = "AVAILABLE"
            stamp_update(veh)

    recompute_assessment_totals(assessment)

    # Issue the assessment if it is still in DRAFT.
    if assessment["status"] == "DRAFT":
        assessment["status"] = "ISSUED"
    stamp_update(assessment)
    stamp_update(lease)


# ── Lease settle / resolve cascade to CLOSED ──────────────────────────────


def close_lease_and_cascade(lease: dict, assessment: dict) -> None:
    """Move parent lease to CLOSED and cancel any ACTIVE gap rider."""
    customer = store.customers[lease["customer_id"]]
    assessment["settled_day_index"] = customer["clock_day_index"]
    lease["status"] = "CLOSED"
    stamp_update(lease)
    cascade_auto_cancel_gap_riders_for_contract(lease["id"])
