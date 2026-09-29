"""The portfolio aggregation model at the capacity boundary.

PRD §3.9 builds a modelled exposure for a shared dependency failure and asks
whether it breaches the capacity held for that dependency. Equality is not a
breach, so the interesting pair of runs sits one impact-share step apart.
"""
from test_helpers import ACTUARY_HEADERS
from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.assertions import assert_money, data_of


QUALIFYING = ["NAMED_PLUS_SUPPLY_CHAIN", "BROAD_SYSTEM_FAILURE"]


def _aurora_book_and_two_scenarios(api):
    """One CSP_ALPHA-dependent policy and two drafts differing only in footprint_pct."""
    chain = X.bound_policy(
        api,
        account_spec=C.ACCOUNT_AURORA,
        attestations=C.ATTEST_95,
        requested_aggregate_limit_usd=5000000,
        requested_retention_usd=250000,
        dependent_bi_definition="NAMED_PLUS_SUPPLY_CHAIN",
        coverage_sections=list(C.STANDARD_TOWER),
        period_start="2026-08-01T00:00:00Z",
        period_end="2027-08-01T00:00:00Z",
        findings=[],
    )
    at_capacity = X.draft_scenario(
        api,
        dependency_key="CSP_ALPHA",
        assumed_outage_hours=240,
        footprint_pct=0.50,
        portfolio_capacity_usd=100000,
        qualifying_definitions=QUALIFYING,
    )
    one_step_above = X.draft_scenario(
        api,
        dependency_key="CSP_ALPHA",
        assumed_outage_hours=240,
        footprint_pct=0.51,
        portfolio_capacity_usd=100000,
        qualifying_definitions=QUALIFYING,
    )
    assert at_capacity["status"] == "DRAFT", at_capacity["status"]
    assert at_capacity["modeled_policy_count"] == 0, at_capacity["modeled_policy_count"]
    assert at_capacity["capacity_breached"] is False, at_capacity["capacity_breached"]
    return chain, at_capacity, one_step_above


def test_exposure_exactly_equal_to_the_held_capacity_is_not_a_breach(api):
    """A 100000.00 modelled exposure against a 100,000 capacity leaves the flag down.

    PRD §3.9: "`capacity_breached` is true when `modeled_gross_exposure_usd` is
    strictly greater than `portfolio_capacity_usd`, and equality is not a breach."
    Aurora's dependent section models 200000.00 of modelled paid loss — 216
    compensable hours at 5,000.00 an hour on a 60 percent margin, capped by the
    500,000 sublimit, less the 250,000 retention, net of 20 percent coinsurance — and
    half of that is exactly the capacity held.

    Design: Difficulty/boundary_precision_check/systemic_exposure_equal_to_capacity_does_not_breach_one_cent_band_above_does
    """
    chain, at_capacity, _above = _aurora_book_and_two_scenarios(api)

    modeled = X.run_model(api, at_capacity["id"])

    assert modeled["status"] == "MODELED", modeled["status"]
    assert modeled["modeled_policy_count"] == 1, modeled["modeled_policy_count"]
    assert_money(modeled["modeled_gross_exposure_usd"], 100000.00, "modeled_gross_exposure_usd")
    assert modeled["capacity_breached"] is False, modeled["capacity_breached"]

    policy = X.read_policy(api, chain["policy"]["id"])
    assert policy["aggregation_flagged"] is False, policy["aggregation_flagged"]


def test_one_step_above_capacity_breaches_and_flags_the_included_policy(api):
    """A 0.51 footprint lifts the exposure to 102000.00, which breaches and flags the book.

    PRD §3.9: "A breach has portfolio consequences: every policy included in that run
    has `aggregation_flagged` set to true and its `version` incremented by 1, which
    in turn attaches the ten-percent aggregation load to its renewal pricing." The
    footprint is applied once to the summed figure, so the same 200000.00 sum crosses
    the capacity line on a one-point change in impact share.

    Design: Difficulty/boundary_precision_check/systemic_exposure_equal_to_capacity_does_not_breach_one_cent_band_above_does
    """
    chain, at_capacity, above = _aurora_book_and_two_scenarios(api)
    X.run_model(api, at_capacity["id"])

    modeled = X.run_model(api, above["id"])

    assert modeled["status"] == "MODELED", modeled["status"]
    assert modeled["modeled_policy_count"] == 1, modeled["modeled_policy_count"]
    assert_money(modeled["modeled_gross_exposure_usd"], 102000.00, "modeled_gross_exposure_usd")
    assert modeled["capacity_breached"] is True, modeled["capacity_breached"]

    policy = X.read_policy(api, chain["policy"]["id"])
    assert policy["aggregation_flagged"] is True, policy["aggregation_flagged"]


def test_a_later_non_breaching_run_does_not_clear_the_flag_it_found(api):
    """Re-running the at-capacity scenario after the breach leaves aggregation_flagged true.

    PRD §3.9: "Flags are sticky across re-runs — a policy that falls out of the
    included population on a later run keeps the `aggregation_flagged` value an
    earlier run gave it." The re-run is "a legitimate self-loop within `MODELED` that
    overwrites the previous outputs", so the scenario's own figures return to
    100000.00 and no breach while the policy keeps the flag.

    Design: Difficulty/boundary_precision_check/systemic_exposure_equal_to_capacity_does_not_breach_one_cent_band_above_does
    """
    chain, at_capacity, above = _aurora_book_and_two_scenarios(api)
    X.run_model(api, above["id"])
    assert X.read_policy(api, chain["policy"]["id"])["aggregation_flagged"] is True

    rerun = X.run_model(api, at_capacity["id"])

    assert rerun["status"] == "MODELED", rerun["status"]
    assert_money(rerun["modeled_gross_exposure_usd"], 100000.00, "modeled_gross_exposure_usd")
    assert rerun["capacity_breached"] is False, rerun["capacity_breached"]

    reread = data_of(api.get_systemic_scenario(at_capacity["id"], ACTUARY_HEADERS))
    assert reread["capacity_breached"] is False, reread["capacity_breached"]

    policy = X.read_policy(api, chain["policy"]["id"])
    assert policy["aggregation_flagged"] is True, policy["aggregation_flagged"]
