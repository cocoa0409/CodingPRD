"""Chain replay order, depletion, the royalty cap and severance rounding order."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_acreage, assert_burden, assert_decimal_interest, assert_money, assert_rate
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS


def test_the_replay_follows_instrument_dates_not_insertion_order(api):
    """Filed patent, assignment, probate, deed still replays 640 to 160 to 80.

    PRD: "They are processed in ascending `instrument_date` order with ties broken
    by ascending `created_at`, and an entry's `id` is never used as a sort key."

    Design: Corner/calculations/chain_replay_is_chronological_not_insertion_ordered
    """
    tract = fx.create_tract(api)
    for payload in (
        f.patent_entry_payload(),
        f.assignment_entry_payload(),
        f.probate_entry_payload(),
        f.deed_entry_payload(),
    ):
        fx.add_chain_entry(api, tract["id"], payload)

    certified = fx.certify_tract(api, tract["id"])

    assert_acreage(
        certified["net_mineral_acres_certified"], "80.0000", "net_mineral_acres_certified"
    )
    assert_burden(certified["existing_burden_fraction"], "0.0625", "existing_burden_fraction")
    assert certified["title_status"] == "CERTIFIED"
    assert certified["chain_entry_count"] == 4


def test_a_probate_before_a_deed_drives_the_replay_negative(api):
    """640 halved to 320 then less 480 is below zero, so certification is refused.

    PRD: "After every individual step the running figure is rounded half-up to 4
    decimal places — not merely once at the end — and if at any step the running
    figure is below zero the whole certification is rejected with
    `ERR_CHAIN_ACREAGE_NEGATIVE`."

    Design: Corner/calculations/chain_with_probate_before_deed_is_rejected_as_acreage_negative
    """
    tract = fx.create_tract(api)
    fx.add_chain_entry(api, tract["id"], f.patent_entry_payload())
    fx.add_chain_entry(api, tract["id"], f.probate_entry_payload(instrument_date="1955-03-12"))
    fx.add_chain_entry(api, tract["id"], f.deed_entry_payload(instrument_date="1988-07-20"))

    response = api.certify_title(tract["id"], ANALYST_HEADERS)

    validate_error(response, "ERR_CHAIN_ACREAGE_NEGATIVE", 422)
    reread = validate_success(api.get_tract(tract["id"], ANALYST_HEADERS), 200)
    assert reread["title_status"] == "RESEARCH"
    assert reread["chain_entry_count"] == 3


def test_the_same_instruments_in_the_other_order_certify_at_eighty_acres(api):
    """Deed 1955 before probate 1988 survives, so the divergence is purely chronological.

    PRD: "Because a deed subtracts an absolute acreage while a probate multiplies by
    a fraction, the same set of instruments in two different date orders yields two
    different acreages, and one of those orders can drive the running figure negative
    where the other does not; this is why the sort key is contractual rather than
    incidental."

    Design: Corner/calculations/chain_with_probate_before_deed_is_rejected_as_acreage_negative
    """
    tract = fx.create_tract(api)
    fx.add_chain_entry(api, tract["id"], f.patent_entry_payload())
    fx.add_chain_entry(api, tract["id"], f.deed_entry_payload(instrument_date="1955-03-12"))
    fx.add_chain_entry(api, tract["id"], f.probate_entry_payload(instrument_date="1988-07-20"))

    certified = fx.certify_tract(api, tract["id"])

    assert_acreage(
        certified["net_mineral_acres_certified"], "80.0000", "net_mineral_acres_certified"
    )
    assert_burden(certified["existing_burden_fraction"], "0.0000", "existing_burden_fraction")


def test_depletion_is_capped_by_income_measured_before_depletion(api):
    """15 percent of gross beats 65 percent of pre-depletion income, so 18.16 applies.

    PRD: "Second, `depletion_allowance` is the lesser of two figures — fifteen
    percent of `gross_royalty`, and sixty-five percent of
    `taxable_before_depletion` — rounded to cents; the statutory rate on gross
    revenue is thus capped by a share of income measured *before* depletion."

    Design: Corner/calculations/tax_statement_applies_depletion_rate_under_income_cap
    """
    world = fx.executed_division_order_ready(api)
    detail = fx.report_revenue(api, world["order"]["id"], operator_decimal_used=0.00195313)
    assert detail["check_status"] == "PAID"
    assert_money(detail["reported_gross_royalty"], "121.09", "reported_gross_royalty")
    assert_money(detail["severance_tax_amount"], "5.57", "severance_tax_amount")
    assert_money(detail["net_amount"], "115.52", "net_amount")

    statement = validate_success(
        api.get_tax_statement(world["owner"]["id"], ADMIN_HEADERS, {"tax_year": 2026}), 200
    )

    assert_money(statement["gross_royalty"], "121.09", "gross_royalty")
    assert_money(statement["severance_tax_withheld"], "5.57", "severance_tax_withheld")
    assert_money(statement["taxable_before_depletion"], "115.52", "taxable_before_depletion")
    assert_money(statement["depletion_allowance"], "18.16", "depletion_allowance")
    assert_money(statement["net_taxable"], "97.36", "net_taxable")
    assert statement["detail_count"] == 1


def test_a_leased_royalty_only_election_is_not_bound_by_the_unit_cap(api):
    """A 0.280000 lease rate survives uncapped, so 0.00339844 beats the pooled 0.00292969.

    PRD: "Under `LEASED_ROYALTY_ONLY` the owner is not a unit participant at all,
    so the unit's royalty cap does not bind: the effective rate is the interest's
    `lease_royalty_rate` exactly as written, and the election factor is 1. Under
    `POOLED` the owner is a participant, so the effective rate is the lesser of the
    interest's `lease_royalty_rate` and the unit's `royalty_rate_cap`, and the
    election factor is 1."

    Design: Corner/calculations/leased_royalty_only_election_bypasses_unit_royalty_rate_cap
    """
    tract = fx.create_certified_tract(api)
    first_owner = fx.create_owner(api)
    second_owner = fx.create_owner(api, legal_name="D Heir", mailing_address="2 Pecos Rd, Pecos TX")
    first = fx.create_interest(api, tract["id"], first_owner["id"], lease_royalty_rate=0.28)
    second = fx.create_interest(api, tract["id"], second_owner["id"], lease_royalty_rate=0.28)

    pooled_unit = fx.create_unit(api, unit_name="Reeves Unit 22H")
    leased_unit = fx.create_unit(api, unit_name="Reeves Unit 23H")
    fx.create_allocation(api, pooled_unit["id"], tract["id"])
    fx.create_allocation(
        api, leased_unit["id"], tract["id"], pooling_election="LEASED_ROYALTY_ONLY"
    )

    pooled_order = fx.create_division_order(api, first["id"], pooled_unit["id"])
    leased_order = fx.create_division_order(api, second["id"], leased_unit["id"])

    assert_decimal_interest(
        pooled_order["expected_decimal"], "0.00292969", "pooled expected_decimal"
    )
    assert_decimal_interest(
        leased_order["expected_decimal"], "0.00339844", "leased expected_decimal"
    )


def test_severance_tax_is_taken_on_the_already_rounded_gross(api):
    """124.02 at 4.6 percent gives 5.70 and a net of 118.32, not 5.71 and 118.31.

    PRD: "Note carefully that the tax is computed on the *already rounded* gross
    royalty, never on the raw product of value and decimal — that ordering is
    contractual throughout this calculation and in both variants below."

    Design: Corner/calculations/severance_tax_is_computed_on_the_rounded_gross_royalty
    """
    world = fx.executed_division_order_ready(api)

    detail = fx.report_revenue(
        api,
        world["order"]["id"],
        production_month="2026-07",
        gross_volume=1150.0000,
        gross_value=63500.00,
        operator_decimal_used=0.00195313,
    )

    assert_money(detail["reported_gross_royalty"], "124.02", "reported_gross_royalty")
    assert_rate(detail["severance_tax_rate"], "0.046000", "severance_tax_rate")
    assert_money(detail["severance_tax_amount"], "5.70", "severance_tax_amount")
    assert_money(detail["net_amount"], "118.32", "net_amount")
    assert_money(detail["expected_gross_royalty"], "124.02", "expected_gross_royalty")
    assert_money(detail["expected_net_amount"], "118.32", "expected_net_amount")
    assert_money(detail["variance_amount"], "0.00", "variance_amount")
    assert detail["check_status"] == "PAID"
    assert_money(
        fx.read_division_order(api, world["order"]["id"])["paid_net_total"],
        "118.32",
        "paid_net_total",
    )
