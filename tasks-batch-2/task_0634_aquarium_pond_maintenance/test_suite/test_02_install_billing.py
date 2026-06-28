"""Install projects: provisional deposit vs final-from-actuals divergence, and
the approve-then-cancel account-balance conservation invariant.
"""
from test_helpers import (
    validate_success,
    make_field_tech_headers,
    make_customer_owner_headers,
    create_approved_install,
    create_quoted_install,
    TEST_USERS,
)
from test_helpers.fixtures import create_technician

AM = TEST_USERS["account_manager_headers"]


def test_install_quote_deposit_and_final_total_diverge(api):
    """PRD §3.8: "At approval the provisional figures are computed:
    quote_total_cents is labor_estimate_cents plus equipment_estimate_cents, and
    deposit_cents is that quote total multiplied by the deposit rate of 30%,
    rounded half-up to whole cents."
    PRD §3.8: "At handoff the final figure is computed from actuals: the actual
    labor minutes are divided into 15-minute blocks rounded up, each block
    costing 2000 cents, and final_total_cents is that actual labor charge plus
    actual_equipment_cents plus change_order_cents."

    Estimates 40000+120000 -> quote 160000, deposit 48000. Actuals: 360 min ->
    24 blocks @2000 = 48000 labor + 135000 equipment + 5000 change order =
    188000 final. Divergence 28000.

    Design: Difficulty/dual_variant_calc/install_billing_provisional_vs_final_diverge
    """
    base = create_approved_install(customer_user_id="owner-1", service_tier="PLUS",
                                   labor_estimate_cents=40000,
                                   equipment_estimate_cents=120000)
    install = base["install"]
    assert install["quote_total_cents"] == 160000, (
        f"Expected quote_total 160000, got {install['quote_total_cents']}")
    assert install["deposit_cents"] == 48000, (
        f"Expected deposit 48000, got {install['deposit_cents']}")

    # Start the build, then hand off with the actuals + change order.
    create_technician(tech_user_id="tech-build")
    ft = make_field_tech_headers("tech-build")
    validate_success(api.start_build_install(install["id"], ft))
    handed = validate_success(api.handoff_install(
        install["id"],
        {"actual_labor_minutes": 360, "actual_equipment_cents": 135000,
         "change_order_cents": 5000},
        AM))
    assert handed["final_total_cents"] == 188000, (
        f"Expected final_total 188000, got {handed['final_total_cents']}")
    assert handed["final_total_cents"] - install["quote_total_cents"] == 28000, (
        "Expected a 28000-cent quote-vs-final divergence")


def test_install_approve_computes_provisional_quote_and_deposit(api):
    """PRD §3.8: "At approval the provisional figures are computed:
    quote_total_cents is labor_estimate_cents plus equipment_estimate_cents, and
    deposit_cents is that quote total multiplied by the deposit rate of 30%,
    rounded half-up to whole cents."

    Estimates 40000 + 120000 -> quote_total_cents 160000; deposit 30% -> 48000.
    The provisional variant fires at APPROVED before any actuals exist.

    Design: Difficulty/dual_variant_calc/install_billing_provisional_vs_final_diverge
    """
    base = create_approved_install(customer_user_id="owner-1", service_tier="PLUS",
                                   labor_estimate_cents=40000,
                                   equipment_estimate_cents=120000)
    install = base["install"]
    assert install["status"] == "APPROVED", f"Expected APPROVED, got {install['status']}"
    assert install["quote_total_cents"] == 160000, (
        f"Expected quote_total 160000, got {install['quote_total_cents']}")
    assert install["deposit_cents"] == 48000, (
        f"Expected deposit 48000, got {install['deposit_cents']}")


def test_install_approve_issues_deposit_invoice_raising_balance(api):
    """PRD §3.8: "A deposit Invoice is then created with source_kind INSTALL and
    total_cents equal to deposit_cents, in status ISSUED, which recomputes the
    contract's account_balance_cents."

    Approving issues a 48000-cent deposit invoice, lifting the contract balance
    from 0 to 48000.

    Design: Difficulty/compensating_invariant/install_approve_then_cancel_preserves_account_balance
    """
    base = create_quoted_install(service_tier="PLUS", customer_user_id="owner-1",
                                 labor_estimate_cents=40000,
                                 equipment_estimate_cents=120000)
    contract_id = base["contract"]["id"]

    before = validate_success(api.get_contract(contract_id, AM))
    assert before["account_balance_cents"] == 0

    owner_headers = make_customer_owner_headers("owner-1")
    validate_success(api.approve_install(base["install"]["id"], owner_headers))

    after = validate_success(api.get_contract(contract_id, AM))
    assert after["account_balance_cents"] == 48000, (
        f"Expected balance 48000 after deposit issued, got "
        f"{after['account_balance_cents']}")


def test_install_approve_then_cancel_restores_account_balance(api):
    """PRD §3.8: "A deposit Invoice is then created with source_kind INSTALL and
    total_cents equal to deposit_cents, in status ISSUED, which recomputes the
    contract's account_balance_cents."
    PRD §3.8: "When the cancelled project was APPROVED and therefore had a
    deposit invoice, that deposit Invoice is voided — its status becomes VOID —
    and the contract's account_balance_cents is recomputed to remove the
    deposit's contribution."

    Approve issues a 48000-cent deposit invoice (balance -> 48000); cancelling
    the APPROVED install voids it (balance back to 0, no drift).

    Design: Difficulty/compensating_invariant/install_approve_then_cancel_preserves_account_balance
    """
    base = create_approved_install(customer_user_id="owner-1", service_tier="PLUS",
                                   labor_estimate_cents=40000,
                                   equipment_estimate_cents=120000)
    contract_id = base["contract"]["id"]
    install_id = base["install"]["id"]

    after_approve = validate_success(api.get_contract(contract_id, AM))
    assert after_approve["account_balance_cents"] == 48000, (
        f"Expected balance 48000 after deposit issued, got "
        f"{after_approve['account_balance_cents']}")

    validate_success(api.cancel_install(install_id, AM))
    after_cancel = validate_success(api.get_contract(contract_id, AM))
    assert after_cancel["account_balance_cents"] == 0, (
        f"Expected balance 0 after deposit voided, got "
        f"{after_cancel['account_balance_cents']}")
