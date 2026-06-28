"""Difficulty queue: retainer-ledger dual-variant balances, scholarship net-aid
coordination, and the conserved-quantity (compensating-invariant) ledger tests.

All field names are exact PRD field names. Each test builds its own world from
scratch via test_helpers fixtures and asserts the literal expected values.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    assert_ledger_consistency,
    make_counselor_headers,
    make_student_headers,
    make_admin_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f


# ==========================================================================
# dual_variant_calc / ledger_actual_vs_projected_balance_diverge
# ==========================================================================
def _build_active_package_with_open_fee_task(est_cost_cents=50000, deposit_cents=200000):
    """Onboarded student, ACTIVE PACKAGE contract (retainer deposit), a SELECTED
    school, an Application IN_PROGRESS, and one OPEN billable FEE task.
    Returns (counselor, student, contract, application, task)."""
    counselor, student, contract = fx.setup_active_contract(
        billing_model="PACKAGE",
        contract_overrides={
            "package_fee_cents": 600000,
            "package_milestones": 3,
            "retainer_deposit_cents": deposit_cents,
        },
    )
    ch = make_counselor_headers(counselor["id"])
    app, _item, _v = fx.setup_application(counselor["id"], student)
    app = get_success_data(api_client.start_prep_application(app["id"], ch))
    task = get_success_data(
        api_client.create_application_task(
            f.create_application_task_payload(
                app["id"], task_type="FEE", title="Pay fee",
                due_utc="2026-12-01T00:00:00Z",
                estimated_cost_cents=est_cost_cents, blocks_submission=True,
            ),
            ch,
        )
    )
    return counselor, student, contract, app, task


def test_actual_and_projected_balances_diverge_with_pending_task(api):
    """PRD §3.7: "The `projected_balance_cents` is `retainer_balance_cents` minus
    that pending-task cost."
    PRD §3.7: "The crucial subtlety is that this very set of pending tasks is
    *included* in the projected balance but *excluded* from the actual ledger —
    essay tasks never bill in either — so the two balances legitimately differ
    for identical data."

    Design: Difficulty/dual_variant_calc/ledger_actual_vs_projected_balance_diverge
    """
    counselor, student, contract, app, task = _build_active_package_with_open_fee_task(
        est_cost_cents=50000, deposit_cents=200000
    )
    ch = make_counselor_headers(counselor["id"])
    data = validate_success(api.get_contract(contract["id"], ch))
    assert data["retainer_balance_cents"] == 200000, (
        f"actual retainer_balance_cents should exclude the pending task; got {data['retainer_balance_cents']}"
    )
    assert data["projected_balance_cents"] == 150000, (
        f"projected_balance_cents should subtract the 50000 pending task; got {data['projected_balance_cents']}"
    )
    assert data["retainer_balance_cents"] != data["projected_balance_cents"], (
        "the actual and projected balances must diverge for identical data"
    )


def test_actual_ledger_ignores_pending_task_cost(api):
    """PRD §3.7: "These sums are taken over every entry on the contract with none
    excluded, and because they are pure sums the result does not depend on the
    order in which entries were posted."
    PRD §3.7: "The `projected_balance_cents` is `retainer_balance_cents` minus
    that pending-task cost."

    Design: Difficulty/dual_variant_calc/ledger_actual_vs_projected_balance_diverge
    """
    counselor, student, contract, app, task = _build_active_package_with_open_fee_task(
        est_cost_cents=50000, deposit_cents=200000
    )
    ch = make_counselor_headers(counselor["id"])
    data = validate_success(api.get_contract(contract["id"], ch))
    # charged_cents is 0 (nothing posted yet); the deposit credit is the only posting.
    assert data["charged_cents"] == 0
    assert data["credited_cents"] == 200000
    assert data["retainer_balance_cents"] == 200000
    assert_ledger_consistency(data)


# ==========================================================================
# dual_variant_calc / scholarship_gross_vs_net_coordination_diverge
# ==========================================================================
def _build_admitted_student_with_merit_accepted():
    """Active HOURLY student with a SUBMITTED+ADMITTED application and a MERIT
    award (gross 2500000) already ACCEPTED. Returns (counselor, student, app, merit_award)."""
    counselor, student, contract = fx.setup_active_contract(
        billing_model="HOURLY",
        contract_overrides={"hourly_rate_cents": 25000},
        student_overrides={"gpa": 3.9, "sat_total": 1500},
        activity_overrides=None,
    )
    ch = make_counselor_headers(counselor["id"])
    app, _item, _v = fx.setup_application(counselor["id"], student)
    app = get_success_data(api_client.start_prep_application(app["id"], ch))
    app = get_success_data(api_client.mark_ready_application(app["id"], ch))
    fx.set_clock("2026-12-01T00:00:00Z")
    app = get_success_data(api_client.submit_application(app["id"], ch))
    app = get_success_data(api_client.record_decision(app["id"], {"decision": "ADMITTED"}, ch))
    merit = get_success_data(
        api_client.create_scholarship(
            f.create_scholarship_payload(
                student["id"], award_type="MERIT", gross_amount_cents=2500000,
                award_name="Merit Grant", application_id=app["id"],
            ),
            ch,
        )
    )
    merit = get_success_data(api_client.transition_scholarship(merit["id"], {"to_status": "ACCEPTED"}, ch))
    return counselor, student, app, merit


def test_need_award_net_reduced_by_prior_merit_in_coordination_cap(api):
    """PRD §3.6: "Running through the accepted awards in that order with a running
    total starting at 0, each award's `net_amount_cents` is the lesser of its own
    `gross_amount_cents` and the cap minus the running total so far; if that
    quantity would be negative it is taken as 0; the running total then increases
    by the amount just allocated."
    PRD §3.6: "is a coordination/stacking waterfall over a fixed family
    coordination cap of 4,000,000 cents."

    Design: Difficulty/dual_variant_calc/scholarship_gross_vs_net_coordination_diverge
    """
    counselor, student, app, merit = _build_admitted_student_with_merit_accepted()
    ch = make_counselor_headers(counselor["id"])
    need = get_success_data(
        api_client.create_scholarship(
            f.create_scholarship_payload(
                student["id"], award_type="NEED", gross_amount_cents=2000000,
                award_name="Need Grant", application_id=app["id"],
            ),
            ch,
        )
    )
    accepted_need = validate_success(api.transition_scholarship(need["id"], {"to_status": "ACCEPTED"}, ch))
    assert accepted_need["gross_amount_cents"] == 2000000
    assert accepted_need["net_amount_cents"] == 1500000, (
        f"NEED award should net cap-minus-running = 4000000-2500000 = 1500000; "
        f"got {accepted_need['net_amount_cents']}"
    )


def test_merit_award_net_equals_gross_when_under_cap(api):
    """PRD §3.6: "The student's awards are processed in a pinned order: first by
    award-type rank, where `MERIT` ranks 0, `EXTERNAL` ranks 1, and `NEED` ranks
    2, and within the same rank by `created_at` ascending."
    PRD §3.6: "each award's `net_amount_cents` is the lesser of its own
    `gross_amount_cents` and the cap minus the running total so far"

    Design: Difficulty/dual_variant_calc/scholarship_gross_vs_net_coordination_diverge
    """
    counselor, student, app, merit = _build_admitted_student_with_merit_accepted()
    ch = make_counselor_headers(counselor["id"])
    need = get_success_data(
        api_client.create_scholarship(
            f.create_scholarship_payload(
                student["id"], award_type="NEED", gross_amount_cents=2000000,
                award_name="Need Grant", application_id=app["id"],
            ),
            ch,
        )
    )
    get_success_data(api_client.transition_scholarship(need["id"], {"to_status": "ACCEPTED"}, ch))
    # MERIT ranks first, under the cap, so net == gross.
    merit_after = validate_success(api.get_scholarship(merit["id"], ch))
    assert merit_after["net_amount_cents"] == 2500000, (
        f"MERIT award (rank 0, under cap) should net its full gross; got {merit_after['net_amount_cents']}"
    )


# ==========================================================================
# compensating_invariant / charge_then_equal_credit_conserves_retainer_balance
# ==========================================================================
def _build_active_hourly_with_charge(charge_cents=30000, deposit_cents=200000):
    counselor, student, contract = fx.setup_active_contract(
        billing_model="HOURLY",
        contract_overrides={"hourly_rate_cents": 20000, "retainer_deposit_cents": deposit_cents},
    )
    ch = make_counselor_headers(counselor["id"])
    get_success_data(
        api_client.create_billing_entry(
            f.create_billing_entry_payload(
                contract["id"], "CHARGE", "MANUAL", charge_cents, memo="extra work"
            ),
            ch,
        )
    )
    return counselor, student, contract


def test_charge_then_equal_credit_restores_retainer_balance(api):
    """PRD §3.7: "`retainer_balance_cents` is `credited_cents` minus `charged_cents`
    — a negative value means the student owes money."
    PRD §2.9: "the contract's balance fields are always recomputed from it rather
    than mutated directly."

    Design: Difficulty/compensating_invariant/charge_then_equal_credit_conserves_retainer_balance
    """
    counselor, student, contract = _build_active_hourly_with_charge(30000, 200000)
    ch = make_counselor_headers(counselor["id"])
    get_success_data(
        api_client.create_billing_entry(
            f.create_billing_entry_payload(
                contract["id"], "CREDIT", "MANUAL", 30000, memo="refund"
            ),
            ch,
        )
    )
    data = validate_success(api.get_contract(contract["id"], ch))
    assert data["charged_cents"] == 30000
    assert data["credited_cents"] == 230000
    assert data["retainer_balance_cents"] == 200000, (
        f"charge+equal-credit must conserve the balance at 200000; got {data['retainer_balance_cents']}"
    )


def test_retainer_balance_equals_credited_minus_charged_after_compensating_pair(api):
    """PRD §3.7: "`charged_cents` is the sum of `amount_cents` over all
    `BillingEntry` rows of type `CHARGE` on the contract, `credited_cents` is the
    sum of `amount_cents` over all rows of type `CREDIT`, and
    `retainer_balance_cents` is `credited_cents` minus `charged_cents`"

    Design: Difficulty/compensating_invariant/charge_then_equal_credit_conserves_retainer_balance
    """
    counselor, student, contract = _build_active_hourly_with_charge(30000, 200000)
    ch = make_counselor_headers(counselor["id"])
    # Before the compensating credit: balance dipped by the charge.
    before = validate_success(api.get_contract(contract["id"], ch))
    assert before["retainer_balance_cents"] == 170000
    assert_ledger_consistency(before)
    get_success_data(
        api_client.create_billing_entry(
            f.create_billing_entry_payload(contract["id"], "CREDIT", "MANUAL", 30000, memo="refund"),
            ch,
        )
    )
    after = validate_success(api.get_contract(contract["id"], ch))
    assert_ledger_consistency(after)
    assert after["retainer_balance_cents"] == 200000
