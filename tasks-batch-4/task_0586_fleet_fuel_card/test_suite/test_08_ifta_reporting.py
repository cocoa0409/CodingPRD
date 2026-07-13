"""Quarterly IFTA reporting: the net-tax formula, the empty-period edge, and the
settlement precondition on filing."""
import pytest

from test_helpers import (
    ADMIN,
    MERCHANT,
    ApiErrorId,
    assert_ifta_report,
    assert_instant_equals,
    assert_total_tax_is_sum_of_lines,
    create_ifta_report_payload,
    jurisdiction_line,
    make_fleet_account,
    make_ifta_report,
    read_report,
    setup_authorized_fills,
    setup_captured_fills,
    setup_settled_fills,
    validate_error,
    validate_success,
)

Q1_CLOCK = "2026-02-10T12:00:00Z"
Q1_ASSIGNMENT = {"effective_from": "2026-01-01T00:00:00Z"}
Q1_VEHICLE = {
    "tank_capacity_gallons": 5000, "expected_mpg_min": 3,
    "expected_mpg_max": 20, "starting_odometer": 5000,
}

# 400 miles on 50 CA gallons, then 500 miles on 40 AZ gallons.
# Fleet economy = 900 miles / 90 gallons = 10.0 mpg.
_IFTA_FILLS = [
    {"gallons": 50, "unit_price_cents": 400, "odometer": 5400, "jurisdiction": "CA"},
    {"gallons": 40, "unit_price_cents": 400, "odometer": 5900, "jurisdiction": "AZ"},
]


def _ifta_scenario(api):
    return setup_settled_fills(
        api, _IFTA_FILLS, clock=Q1_CLOCK,
        account_overrides={"company_name": "Ifta Fleet"},
        vehicle_overrides=Q1_VEHICLE,
        card_overrides={"last4": "3333"},
        assignment_overrides=Q1_ASSIGNMENT,
    )


# --------------------------------------------------------------------------- #
# The net-tax formula, including the pump-tax credit that drives a line negative
# --------------------------------------------------------------------------- #

def test_ifta_total_tax_can_go_negative_from_pump_credit(api):
    """PRD §3.9: "A jurisdiction's `net_tax_cents` is the tax owed on taxable
    gallons minus the credit for tax already paid at the pump: multiply
    `taxable_gallons` by `tax_rate_cents` and round half up to whole cents, then
    subtract the result of multiplying `gallons_purchased` by `tax_rate_cents` and
    rounding half up to whole cents."
    PRD §3.9: "The report's `total_tax_cents` is the sum of `net_tax_cents` across
    all jurisdiction lines, and may be negative when pump-paid tax exceeds the tax
    owed."
    PRD §3.9: "Generation derives the quarter's `period_start` (inclusive UTC start)
    and `period_end` (exclusive UTC end) from the `quarter`, computes the tax
    figures, and creates the report in status `DRAFT`."

    Design: Difficulty/combinatorial_formula/ifta_net_tax_multi_input_with_pump_credit
    """
    scenario = _ifta_scenario(api)

    payload = create_ifta_report_payload(scenario["account"]["id"], "2026-Q1")
    report = validate_success(api.create_ifta_report(payload, ADMIN), 201)

    assert_ifta_report(report)
    assert report["status"] == "DRAFT"
    assert report["total_tax_cents"] == -420, "CA's -680 credit plus AZ's 260 owed"
    assert_total_tax_is_sum_of_lines(report)


def test_ifta_jurisdiction_lines_carry_the_full_computation(api):
    """PRD §3.9: "The fleet's average economy is the sum of `segment_miles` over
    those settled transactions divided by the sum of their `gallons`; if that gallon
    total is zero, the fleet economy is treated as zero and the report has no
    jurisdiction lines."
    PRD §3.9: "Otherwise, for each jurisdiction with settled activity in the period,
    one entry is emitted in `jurisdiction_lines` carrying: the `jurisdiction` code;
    `miles`, the sum of `segment_miles` for that jurisdiction's settled transactions;
    `gallons_purchased`, the sum of their `gallons`; `taxable_gallons`, which is that
    jurisdiction's `miles` divided by the fleet average economy, rounded half up to
    three decimal places (and zero when the fleet economy is zero); `tax_rate_cents`,
    the per-gallon tax rate for that jurisdiction; and `net_tax_cents`."
    PRD §3.9: "The per-gallon jurisdiction tax rates, in cents, are 68 for `CA`, 26
    for `AZ`, 33 for `NV`, 38 for `OR`, and 20 for `TX`."

    Fleet economy is 900 miles / 90 gallons = 10.0 mpg, so CA's 400 miles yield 40
    taxable gallons (2720 cents owed against 3400 cents paid at the pump: -680) and
    AZ's 500 miles yield 50 taxable gallons (1300 owed against 1040 paid: +260).

    Design: Difficulty/combinatorial_formula/ifta_net_tax_multi_input_with_pump_credit
    """
    scenario = _ifta_scenario(api)
    report = make_ifta_report(api, scenario["account"]["id"], "2026-Q1")

    ca = jurisdiction_line(report, "CA")
    az = jurisdiction_line(report, "AZ")

    assert ca["miles"] == pytest.approx(400, abs=0.001)
    assert ca["gallons_purchased"] == pytest.approx(50, abs=0.001)
    assert ca["taxable_gallons"] == pytest.approx(40.0, abs=0.001)
    assert ca["tax_rate_cents"] == 68
    assert ca["net_tax_cents"] == -680, "2720 owed minus 3400 already paid at the pump"

    assert az["miles"] == pytest.approx(500, abs=0.001)
    assert az["gallons_purchased"] == pytest.approx(40, abs=0.001)
    assert az["taxable_gallons"] == pytest.approx(50.0, abs=0.001)
    assert az["tax_rate_cents"] == 26
    assert az["net_tax_cents"] == 260, "1300 owed minus 1040 already paid at the pump"


# --------------------------------------------------------------------------- #
# The empty settled set
# --------------------------------------------------------------------------- #

def test_ifta_report_with_no_transactions_is_empty_and_zero(api):
    """PRD §3.9: "The computation gathers the account's `SETTLED` transactions whose
    `purchased_at` lies within the half-open period."
    PRD §3.9: "The fleet's average economy is the sum of `segment_miles` over those
    settled transactions divided by the sum of their `gallons`; if that gallon total
    is zero, the fleet economy is treated as zero and the report has no jurisdiction
    lines."
    PRD §3.9: "The report's `total_tax_cents` is the sum of `net_tax_cents` across
    all jurisdiction lines, and may be negative when pump-paid tax exceeds the tax
    owed."

    Design: Difficulty/boundary_precision_check/ifta_empty_settled_set_zero_total
    """
    account = make_fleet_account(api, company_name="Empty Fleet")

    payload = create_ifta_report_payload(account["id"], "2026-Q1")
    report = validate_success(api.create_ifta_report(payload, ADMIN), 201)

    assert_ifta_report(report)
    assert report["jurisdiction_lines"] == [], "a zero gallon total yields no jurisdiction lines"
    assert report["total_tax_cents"] == 0, "the sum over an empty set of lines is zero"


def test_ifta_report_ignores_unsettled_in_period_transactions(api):
    """PRD §3.9: "The computation gathers the account's `SETTLED` transactions whose
    `purchased_at` lies within the half-open period."
    PRD §3.9: "The fleet's average economy is the sum of `segment_miles` over those
    settled transactions divided by the sum of their `gallons`; if that gallon total
    is zero, the fleet economy is treated as zero and the report has no jurisdiction
    lines."

    The account has an in-period fill, but it is only AUTHORIZED — the settled set
    is still empty, so the report has no lines and no tax.

    Design: Difficulty/boundary_precision_check/ifta_empty_settled_set_zero_total
    """
    scenario = setup_authorized_fills(
        api, [{"gallons": 50, "unit_price_cents": 400, "odometer": 5400, "jurisdiction": "CA"}],
        clock=Q1_CLOCK,
        account_overrides={"company_name": "Empty Fleet"},
        vehicle_overrides=Q1_VEHICLE,
        card_overrides={"last4": "3334"},
        assignment_overrides=Q1_ASSIGNMENT,
    )

    report = make_ifta_report(api, scenario["account"]["id"], "2026-Q1")

    assert report["jurisdiction_lines"] == []
    assert report["total_tax_cents"] == 0


# --------------------------------------------------------------------------- #
# Filing depends on the posting state of every in-period transaction
# --------------------------------------------------------------------------- #

def _captured_only_scenario(api):
    return setup_captured_fills(
        api, [{"gallons": 50, "unit_price_cents": 400, "odometer": 5400, "jurisdiction": "CA"}],
        clock=Q1_CLOCK,
        account_overrides={"company_name": "Dep2 Fleet"},
        vehicle_overrides=Q1_VEHICLE,
        card_overrides={"last4": "0112"},
        assignment_overrides=Q1_ASSIGNMENT,
    )


def test_file_rejected_while_an_in_period_transaction_is_unsettled(api):
    """PRD §3.9: "Filing requires that every transaction of the report's account
    whose `purchased_at` falls within the period is `SETTLED`; if any in-period
    transaction is not settled the file is rejected with `ERR_PERIOD_NOT_SETTLED`,
    and filing a report not in `DRAFT` is rejected with `ERR_INVALID_REPORT_STATE`."

    Design: Difficulty/cross_entity_state_dependency/ifta_file_requires_all_in_period_settled
    """
    scenario = _captured_only_scenario(api)
    assert scenario["transactions"][0]["posting_status"] == "CAPTURED"
    report = make_ifta_report(api, scenario["account"]["id"], "2026-Q1")

    resp = api.file_ifta_report(report["id"], ADMIN)

    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_SETTLED.value)
    assert read_report(api, report["id"])["status"] == "DRAFT", "the rejected file left the report DRAFT"


def test_file_succeeds_once_every_in_period_transaction_settles(api):
    """PRD §3.9: "A `ProgramAdmin` files a `DRAFT` report, moving it to the terminal
    `FILED`."
    PRD §3.9: "Filing requires that every transaction of the report's account whose
    `purchased_at` falls within the period is `SETTLED`; if any in-period transaction
    is not settled the file is rejected with `ERR_PERIOD_NOT_SETTLED`, and filing a
    report not in `DRAFT` is rejected with `ERR_INVALID_REPORT_STATE`."
    PRD §3.9: "On file, the system stamps `filed_at` from the logical clock and
    freezes the report's `jurisdiction_lines` and `total_tax_cents`."

    Design: Difficulty/cross_entity_state_dependency/ifta_file_requires_all_in_period_settled
    """
    scenario = _captured_only_scenario(api)
    report = make_ifta_report(api, scenario["account"]["id"], "2026-Q1")

    validate_success(api.settle_transaction(scenario["transactions"][0]["id"], MERCHANT))
    filed = validate_success(api.file_ifta_report(report["id"], ADMIN))

    assert_ifta_report(filed)
    assert filed["status"] == "FILED"
    assert filed["filed_at"] is not None, "filing stamps filed_at from the logical clock"
    assert_instant_equals(filed["filed_at"], Q1_CLOCK, "filed_at")
