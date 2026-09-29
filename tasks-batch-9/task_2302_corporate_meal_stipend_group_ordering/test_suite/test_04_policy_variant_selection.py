"""Three dual-variant calculations, each fixed at a different moment."""

from test_helpers import (
    LINES_THREE_1000,
    TEST_USERS,
    add_employee_with_period,
    api_client,
    assert_routing_split_exact,
    confirm_order,
    deliver_order,
    draft_order,
    place_order,
    raise_claim,
    read_claim_refund_entries,
    read_employee,
    read_imputed_records,
    read_order,
    resolve_claim,
    set_clock,
    setup_delivered_order,
    setup_forecast_scenario,
    setup_scenario,
    validate_success,
)

_TIPPED_THREE_LINES = {"lines": LINES_THREE_1000, "tip_cents": 200}


def _patch_program(program_id, payload):
    return validate_success(
        api_client.patch_meal_program(
            program_id, payload, TEST_USERS["platform_admin_headers"]
        )
    )


def _two_pinned_methods():
    """Ada accrues under DE_MINIMIS_EXCLUSION, then the program flips to
    FULL_INCLUSION and Ben accrues under the new selector."""
    ns = setup_delivered_order(order_overrides=_TIPPED_THREE_LINES)
    _patch_program(ns.program["id"], {"taxable_benefit_method": "FULL_INCLUSION"})

    ns.ben, ns.ben_period = add_employee_with_period(
        ns, employee_overrides={"full_name": "Ben Barnes", "email": "ben@acme.test"}
    )
    ben_order = draft_order(
        ns.ben, ns.ben_period, ns.restaurant, ns.location, **_TIPPED_THREE_LINES
    )
    ben_order = place_order(ben_order, ns.ben)
    ben_order = confirm_order(ben_order, ns.restaurant)
    ns.ben_order = deliver_order(ben_order, ns.restaurant)
    return ns


def test_imputed_method_is_pinned_per_record_and_diverges_by_2000_cents():
    """Two records on the same 2,500-cent employer share differ by exactly 2,000.

    PRD §3.7: "Under the `FULL_INCLUSION` method the whole employer share is
    taxable, so the same 2,500-cent employer share yields `taxable_cents` of 2,500
    — a difference of exactly 2,000 cents on that order."

    Design: Difficulty/dual_variant_calc/imputed_taxable_method_pinned_per_record_diverges_by_2000
    """
    ns = _two_pinned_methods()

    assert ns.order["employer_covered_cents"] == 2500
    assert ns.ben_order["employer_covered_cents"] == 2500

    ada_records = read_imputed_records(ns.employee["id"])
    ben_records = read_imputed_records(ns.ben["id"])
    assert len(ada_records) == 1
    assert len(ben_records) == 1
    ada_record, ben_record = ada_records[0], ben_records[0]

    assert ada_record["method"] == "DE_MINIMIS_EXCLUSION"
    assert ada_record["gross_employer_paid_cents"] == 2500
    assert ada_record["taxable_cents"] == 500

    assert ben_record["method"] == "FULL_INCLUSION"
    assert ben_record["gross_employer_paid_cents"] == 2500
    assert ben_record["taxable_cents"] == 2500

    assert ben_record["taxable_cents"] - ada_record["taxable_cents"] == 2000


def test_program_edit_does_not_re_pin_an_existing_record_or_its_employee_flag():
    """The 1,000-cent reporting threshold is crossed by one variant only.

    PRD §3.7: "the flag reads `W2_IMPUTED` once `ytd_imputed_cents` reaches the
    reporting threshold of 1,000 cents — ten dollars — and reads `NONE` below
    that."

    Design: Difficulty/dual_variant_calc/imputed_taxable_method_pinned_per_record_diverges_by_2000
    """
    ns = _two_pinned_methods()

    ada = read_employee(ns.employee["id"])
    assert ada["ytd_imputed_cents"] == 500
    assert ada["tax_treatment_flag"] == "NONE", "500 is below the 1,000-cent threshold"

    ben = read_employee(ns.ben["id"])
    assert ben["ytd_imputed_cents"] == 2500
    assert ben["tax_treatment_flag"] == "W2_IMPUTED"

    assert read_imputed_records(ns.employee["id"])[0]["method"] == "DE_MINIMIS_EXCLUSION", (
        "a later change to the program's taxable_benefit_method does not "
        "retroactively change any existing record's method"
    )


def test_forecast_on_the_commitment_basis_totals_82500_with_a_4125_fee():
    """The committed 80,000 is below the 97,500 ceiling, so it drives the total.

    PRD §3.9: "`COMMITMENT` gives a committed 80,000 against a ceiling of 97,500,
    so `forecast_total_cents` is 82,500 with an administration fee of 4,125, while
    `RUN_RATE` gives 8,750 with a fee of 438."

    Design: Difficulty/dual_variant_calc/forecast_basis_commitment_vs_run_rate_diverges_82500_to_8750
    """
    ns = setup_forecast_scenario()
    set_clock("2026-08-10T00:00:00Z")

    forecast = validate_success(
        api_client.get_forecast(ns.program["id"], TEST_USERS["program_admin_headers"])
    )

    assert forecast["forecast_basis"] == "COMMITMENT"
    assert forecast["remaining_eligible_days"] == 16
    assert forecast["elapsed_eligible_days"] == 6
    assert forecast["total_eligible_days"] == 21
    assert forecast["active_rule_group_count"] == 1
    assert forecast["forecast_total_cents"] == 82500
    assert forecast["forecast_admin_fee_cents"] == 4125


def test_forecast_reads_the_basis_live_so_run_rate_totals_8750_with_a_438_fee():
    """Flipping the selector immediately changes the next forecast on same data.

    PRD §2.12: "The forecast basis, by contrast, is *not* pinned at all: the
    forecast endpoint reads the program's `forecast_basis` live on every call, so
    flipping the selector immediately changes the next forecast."

    Design: Difficulty/dual_variant_calc/forecast_basis_commitment_vs_run_rate_diverges_82500_to_8750
    """
    ns = setup_forecast_scenario()
    set_clock("2026-08-10T00:00:00Z")

    commitment = validate_success(
        api_client.get_forecast(ns.program["id"], TEST_USERS["program_admin_headers"])
    )
    _patch_program(ns.program["id"], {"forecast_basis": "RUN_RATE"})
    run_rate = validate_success(
        api_client.get_forecast(ns.program["id"], TEST_USERS["program_admin_headers"])
    )

    assert run_rate["forecast_basis"] == "RUN_RATE"
    assert run_rate["forecast_total_cents"] == 8750, (
        "2,500 spent over 6 elapsed eligible days across 21 total days"
    )
    assert run_rate["forecast_admin_fee_cents"] == 438, "437.5 rounds half-up to 438"
    assert run_rate["forecast_total_cents"] != commitment["forecast_total_cents"]
    assert commitment["forecast_total_cents"] == 82500
    assert run_rate["remaining_eligible_days"] == 16
    assert run_rate["elapsed_eligible_days"] == 6
    assert run_rate["total_eligible_days"] == 21


def _delivered_order_with_claim(employee_overrides=None):
    ns = setup_delivered_order(
        order_overrides=_TIPPED_THREE_LINES, employee_overrides=employee_overrides
    )
    ns.claim = raise_claim(
        ns.order,
        ns.employee,
        claim_type="MISSING_ITEM",
        line_index=0,
        claimed_cents=1000,
    )
    return ns


def test_routing_basis_employee_first_pays_1000_where_proportional_pays_427():
    """The same approved 1,000 cents splits differently under the two bases.

    PRD §3.8: "On an order with `employee_card_cents` of 1,863,
    `employer_covered_cents` of 2,500, and `gross_total_cents` of 4,363, an
    approved amount of 1,000 routes as 1,000 to the employee and 0 to the employer
    under `EMPLOYEE_FIRST`, but as 427 to the employee and 573 to the employer
    under `PROPORTIONAL`."

    Design: Difficulty/dual_variant_calc/refund_routing_employee_first_vs_proportional_1000_vs_427
    """
    first = _delivered_order_with_claim()
    assert first.order["employee_card_cents"] == 1863
    assert first.order["employer_covered_cents"] == 2500
    assert first.order["gross_total_cents"] == 4363

    employee_first = resolve_claim(
        first.claim, first.order["id"], routing_basis="EMPLOYEE_FIRST"
    )
    assert employee_first["status"] == "ROUTED_EMPLOYEE_FIRST"
    assert employee_first["approved_cents"] == 1000
    assert employee_first["employee_refund_cents"] == 1000
    assert employee_first["employer_credit_cents"] == 0

    second = _delivered_order_with_claim()
    proportional = resolve_claim(
        second.claim, second.order["id"], routing_basis="PROPORTIONAL"
    )
    assert proportional["status"] == "ROUTED_PROPORTIONAL"
    assert proportional["employee_refund_cents"] == 427, (
        "1,000 * 1,863 / 4,363 rounds half-up to 427"
    )
    assert proportional["employer_credit_cents"] == 573


def test_both_routing_bases_reconcile_to_the_approved_amount_without_moving_money():
    """Resolution stores the split; only settlement writes the ledger.

    PRD §3.8: "The routing split itself has two variants, and the employer side
    absorbs the rounding residue in both, so `employee_refund_cents` plus
    `employer_credit_cents` always equals `approved_cents` exactly."

    Design: Difficulty/dual_variant_calc/refund_routing_employee_first_vs_proportional_1000_vs_427
    """
    first = _delivered_order_with_claim()
    employee_first = resolve_claim(
        first.claim, first.order["id"], routing_basis="EMPLOYEE_FIRST"
    )
    assert_routing_split_exact(employee_first)

    second = _delivered_order_with_claim()
    proportional = resolve_claim(
        second.claim, second.order["id"], routing_basis="PROPORTIONAL"
    )
    assert_routing_split_exact(proportional)

    assert read_claim_refund_entries(employee_first["id"]) == []
    assert read_claim_refund_entries(proportional["id"]) == []

    for ns in (first, second):
        order = read_order(ns.order["id"])
        assert order["settlement_status"] == "CAPTURED", (
            "resolution alone does not advance the settlement dimension"
        )
        assert order["employer_refunded_cents"] == 0
        assert order["employee_refunded_cents"] == 0
        assert order["net_charged_cents"] == 4363
