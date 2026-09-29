"""Compensating actions and the ledgers they must leave undisturbed."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    NETWORK_ADMIN_HEADERS,
    claim_line,
    claim_walked_to,
    create_claim,
    create_enrollment,
    contract_version,
    post_remittance,
    provider_with_contract,
    reject_claim,
    reverse_remittance,
    submit_claim,
)

# Local setup builders


def _july_billing_home():
    """An ACTIVE home with a July contract and two subsidy children."""
    ctx = provider_with_contract(
        apply_overrides={"capacity_slots": 6, "fixed_monthly_cost_cents": 237000},
        agreement_overrides={"shared_services": ["ENROLLMENT", "BILLING"]},
        contract_overrides={
            "daily_rate_cents": 4500,
            "contracted_slots": 4,
            "authorized_amount_cents": 5000000,
            "period_start_on": "2026-07-01T00:00:00Z",
            "absence_rate_pct": 50,
        },
    )
    ctx["e1"] = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-1",
        family_name="Alvarez",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
    )["id"]
    ctx["e2"] = create_enrollment(
        ctx["provider_id"],
        child_ref="CH-2",
        family_name="Brody",
        days_per_week=5,
        private_monthly_tuition_cents=0,
        subsidy_certified=True,
    )["id"]
    return ctx


def _two_reconciled_months():
    """July reconciled at 137250 and August reconciled at 90000 on one contract."""
    ctx = _july_billing_home()
    ctx["july"] = claim_walked_to(
        "RECONCILED",
        ctx["contract_id"],
        ctx["provider_id"],
        "2026-07",
        [claim_line(ctx["e1"], 18, 4), claim_line(ctx["e2"], 10, 2)],
    )
    ctx["august"] = claim_walked_to(
        "RECONCILED",
        ctx["contract_id"],
        ctx["provider_id"],
        "2026-08",
        [claim_line(ctx["e1"], 20, 0)],
    )
    return ctx


def _two_submitted_months():
    """July submitted at 153000 and August submitted at 90000 on one contract."""
    ctx = _july_billing_home()
    ctx["july"] = claim_walked_to(
        "SUBMITTED",
        ctx["contract_id"],
        ctx["provider_id"],
        "2026-07",
        [claim_line(ctx["e1"], 18, 4), claim_line(ctx["e2"], 10, 2)],
    )
    ctx["august"] = claim_walked_to(
        "SUBMITTED",
        ctx["contract_id"],
        ctx["provider_id"],
        "2026-08",
        [claim_line(ctx["e1"], 20, 0)],
    )
    return ctx


# compensating_invariant


def test_a_bulk_payment_waterfalls_by_service_month_and_credits_the_remainder(api):
    """250000 cents settle both months and leave 22750 as unallocated credit.

    Candidates are walked by service month ascending, so July takes its full 137250
    shortfall and August takes its full 90000, both reaching their final amounts and
    settling. The 22750 cents left over are credited rather than lost, and the contract's
    remitted total of 250000 equals 137250 + 90000 + 22750 exactly.

    PRD: "Second, remitted cents: a contract's `remitted_cents` always equals the sum of
    `paid_cents` across that contract's claims plus the contract's
    `unallocated_credit_cents`, both after a payment is posted and after one is reversed."

    Design: Difficulty/compensating_invariant/remittance_reversal_conserves_contract_remitted_cents_ledger
    """
    ctx = _two_reconciled_months()
    assert ctx["july"]["final_amount_cents"] == 137250
    assert ctx["august"]["final_amount_cents"] == 90000

    remittance = post_remittance(
        ctx["contract_id"], "AG-BULK-1", 250000, received_on="2026-08-01T00:00:00Z"
    )
    assert remittance["status"] == "POSTED"
    assert remittance["allocations"] == [
        {"claim_id": ctx["july"]["id"], "allocated_cents": 137250},
        {"claim_id": ctx["august"]["id"], "allocated_cents": 90000},
    ]
    assert remittance["unallocated_cents"] == 22750

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["remitted_cents"] == 250000
    assert contract["unallocated_credit_cents"] == 22750
    assert contract["remitted_cents"] == 137250 + 90000 + 22750

    for claim_id in (ctx["july"]["id"], ctx["august"]["id"]):
        settled = validate_success(api.get_claim(claim_id, NETWORK_ADMIN_HEADERS))
        assert settled["status"] == "SETTLED"


def test_reversing_the_bulk_payment_returns_every_ledger_to_zero_with_no_drift(api):
    """The reversal undoes each allocation and both ledger columns land back on 0.

    Each settled claim gives back exactly what it was allocated and returns to RECONCILED,
    so `remitted_cents` and `unallocated_credit_cents` are both 0 again and the identity
    still holds. The verified valuations are untouched: July is still worth 137250 with a
    settlement delta of 14850.

    PRD: "The contract's `remitted_cents` is reduced by the remittance's `amount_cents` and
    its `unallocated_credit_cents` is reduced by the remittance's `unallocated_cents`."

    Design: Difficulty/compensating_invariant/remittance_reversal_conserves_contract_remitted_cents_ledger
    """
    ctx = _two_reconciled_months()
    remittance = post_remittance(
        ctx["contract_id"], "AG-BULK-1", 250000, received_on="2026-08-01T00:00:00Z"
    )

    reversed_row = reverse_remittance(
        remittance["id"], "Agency mis-posted against the wrong contract"
    )
    assert reversed_row["status"] == "REVERSED"
    assert reversed_row["reversal_reason"] == "Agency mis-posted against the wrong contract"

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["remitted_cents"] == 0
    assert contract["unallocated_credit_cents"] == 0

    july = validate_success(api.get_claim(ctx["july"]["id"], NETWORK_ADMIN_HEADERS))
    august = validate_success(api.get_claim(ctx["august"]["id"], NETWORK_ADMIN_HEADERS))
    assert july["status"] == "RECONCILED"
    assert august["status"] == "RECONCILED"
    assert july["paid_cents"] == 0
    assert august["paid_cents"] == 0
    assert july["final_amount_cents"] == 137250
    assert july["settlement_delta_cents"] == 14850
    assert contract["remitted_cents"] == (
        july["paid_cents"] + august["paid_cents"] + contract["unallocated_credit_cents"]
    )


def test_rejecting_a_claim_gives_its_provisional_amount_back_to_the_contract(api):
    """Authorization falls from 243000 back to 153000 when August is vetoed.

    July's submission counted 153000 against authorization and August's counted 20 * 4500
    == 90000, for 243000. Rejecting August subtracts exactly its own provisional amount,
    leaving 153000 — the figure the contract carried before that submission — and the
    rejected claim never earned an advance or a final valuation.

    PRD: "A `FiscalOfficer` supplies a `rejection_reason`; the claim must be `SUBMITTED`,
    moves `SUBMITTED → REJECTED`, records the reason, and the contract's
    `claimed_amount_cents` is reduced by that claim's `provisional_amount_cents`."

    Design: Difficulty/compensating_invariant/claim_rejection_conserves_contract_claimed_authorization_ledger
    """
    ctx = _two_submitted_months()
    assert ctx["july"]["provisional_amount_cents"] == 153000
    assert ctx["august"]["provisional_amount_cents"] == 90000

    before = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert before["claimed_amount_cents"] == 243000

    rejected = reject_claim(
        ctx["august"]["id"], "Attendance sheets missing for 2026-08"
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "Attendance sheets missing for 2026-08"
    assert rejected["advance_paid_cents"] == 0
    assert rejected["final_amount_cents"] == 0

    after = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert after["claimed_amount_cents"] == 153000


def test_a_replacement_claim_for_the_rejected_month_restores_the_same_total(api):
    """The vetoed month may be re-drafted, and the ledger climbs back to 243000 exactly.

    Because the service-month uniqueness rule skips rejected claims, a fresh 2026-08 claim
    is accepted rather than refused as a duplicate. Submitting it counts the same 90000
    against authorization, so the contract arrives back at 243000 with no drift.

    PRD: "Because the service-month uniqueness rule ignores rejected claims, the provider
    may immediately draft a replacement claim for the same `period_month`."

    Design: Difficulty/compensating_invariant/claim_rejection_conserves_contract_claimed_authorization_ledger
    """
    ctx = _two_submitted_months()
    reject_claim(ctx["august"]["id"], "Attendance sheets missing for 2026-08")

    replacement = create_claim(
        ctx["contract_id"],
        ctx["provider_id"],
        "2026-08",
        [claim_line(ctx["e1"], 20, 0)],
        contract_version(ctx["contract_id"]),
    )
    assert replacement["status"] == "DRAFT"
    assert replacement["period_month"] == "2026-08"

    submitted = submit_claim(replacement["id"], ctx["provider_id"])
    assert submitted["provisional_amount_cents"] == 90000

    contract = validate_success(api.get_contract(ctx["contract_id"], NETWORK_ADMIN_HEADERS))
    assert contract["claimed_amount_cents"] == 243000
