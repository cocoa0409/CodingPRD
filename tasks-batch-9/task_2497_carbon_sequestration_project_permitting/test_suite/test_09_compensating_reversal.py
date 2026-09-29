"""Reversals that must leave the books exactly as they were found.

Two quantities are conserved by the programme: the dollars carried on a
financial assurance instrument, which survive allocation and deallocation
without leaking out of the face amount, and the tonnes on a project's
secure-storage ledger, which return to their prior total when a voided
injection period is re-reported.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, fixtures


def _accepted_net_tonnes(api, permit_id):
    """Sum `net_stored_tonnes` over the permit's records that still count."""
    records, _meta = validate_paginated(
        api.list_injection_periods(permit_id, fixtures.DEVELOPER, {"limit": 100})
    )
    accepted = [record for record in records if record["status"] == "ACCEPTED"]
    return round(sum(record["net_stored_tonnes"] for record in accepted), 3), records


def test_assurance_waterfall_allocation_conserves_the_instrument_face_amount(api):
    """The post-injection site care bucket is the project's `pisc_duration_years` multiplied by its `effective_annual_monitoring_cost_usd`, rounded half up to 2 decimal places — fifty years of monitoring at the uplifted rate is by far the largest line item on most projects.

    The emergency reserve bucket is the larger of a two-million-dollar floor and the area-based figure obtained by multiplying 500,000.00 dollars per square kilometre by pi and by the square of the project's `aor_radius_km`, that area-based figure being rounded half up to 2 decimal places before the comparison.

    The administrative fee is tiered on the governing model's `effective_annual_injection_rate_tpy`: it is 250,000.00 dollars when that rate is at most 500,000 tonnes per year, 500,000.00 dollars when the rate exceeds 500,000 but is at most 1,500,000 tonnes per year, and 900,000.00 dollars when the rate exceeds 1,500,000 tonnes per year.

    The project's `required_financial_assurance_usd` is the sum of those five already-rounded buckets, itself rounded half up to 2 decimal places.

    Four requirement figures are taken from the current computation: the corrective-action requirement is the corrective-action bucket, the plugging requirement is the plugging bucket, the post-injection requirement is the post-injection site care bucket, and the emergency requirement is the emergency reserve bucket plus the administrative fee combined into one figure.

    Starting with the whole `face_amount_usd` as the remaining balance, the buckets are filled in the order corrective action, plugging, post-injection site care, emergency: each bucket receives the smaller of the remaining balance and its own requirement, rounded half up to 2 decimal places, and the remaining balance is then reduced by the amount just assigned, again rounded half up to 2 decimal places.

    Dollars are conserved at all times: the four allocated buckets plus `unallocated_usd` plus `drawn_usd` always add back to `face_amount_usd`, and that invariant holds after every allocation, deallocation and emergency draw.

    Allocation sets the instrument's `status` to `ALLOCATED`, recomputes the project's `allocated_assurance_usd` as the sum, over the project's instruments whose `status` is `ALLOCATED`, of their four allocated buckets (rounded half up to 2 decimal places), resets `assurance_coverage_status`, and bumps both the instrument's `version` and the project's `version`.

    Design: Difficulty/compensating_invariant/instrument_dollar_conservation_across_allocate_deallocate
    """
    ctx = fixtures.setup_project_with_accepted_model(api)
    project = ctx["project"]
    assert project["aor_radius_km"] == 0
    assert project["required_financial_assurance_usd"] == 12500000.00

    instrument = fixtures.post_instrument(api, project["id"])
    assertions.assert_financial_instrument(instrument)
    assertions.assert_dollar_conservation(instrument)
    assert instrument["status"] == "POSTED"
    assert instrument["face_amount_usd"] == constants.TRUST_FUND_FACE_AMOUNT_USD
    assert instrument["unallocated_usd"] == 26000000.00

    allocated = fixtures.allocate_instrument(api, instrument)
    assertions.assert_financial_instrument(allocated)
    assertions.assert_dollar_conservation(allocated)
    assert allocated["status"] == "ALLOCATED"
    assert allocated["allocated_ca_usd"] == 0.00
    assert allocated["allocated_plugging_usd"] == 0.00
    assert allocated["allocated_pisc_usd"] == 10000000.00
    assert allocated["allocated_emergency_usd"] == 2500000.00
    assert allocated["unallocated_usd"] == 13500000.00
    assert allocated["drawn_usd"] == 0.00
    assert allocated["version"] > instrument["version"]

    funded = fixtures.refresh_project(api, project["id"])
    assertions.assert_storage_project_invariants(funded)
    assert funded["allocated_assurance_usd"] == 12500000.00
    assert funded["required_financial_assurance_usd"] == 12500000.00
    assert funded["assurance_coverage_status"] == "FUNDED"


def test_assurance_deallocation_returns_every_bucket_and_reallocation_restores_it(api):
    """It zeroes the four allocated buckets, restores `unallocated_usd` to the full `face_amount_usd`, sets `status` back to `POSTED`, recomputes the project's `allocated_assurance_usd` and `assurance_coverage_status`, and bumps both versions.

    Dollars are conserved at all times: the four allocated buckets plus `unallocated_usd` plus `drawn_usd` always add back to `face_amount_usd`, and that invariant holds after every allocation, deallocation and emergency draw.

    `assurance_coverage_status` is then derived by comparing `allocated_assurance_usd` against `required_financial_assurance_usd`, and the tests are applied in this order: the status is `UNFUNDED` when `allocated_assurance_usd` is zero or below; otherwise it is `FUNDED` when `allocated_assurance_usd` is at least `required_financial_assurance_usd`; otherwise it is `UNDERFUNDED`.

    Starting with the whole `face_amount_usd` as the remaining balance, the buckets are filled in the order corrective action, plugging, post-injection site care, emergency: each bucket receives the smaller of the remaining balance and its own requirement, rounded half up to 2 decimal places, and the remaining balance is then reduced by the amount just assigned, again rounded half up to 2 decimal places.

    Design: Difficulty/compensating_invariant/instrument_dollar_conservation_across_allocate_deallocate
    """
    ctx = fixtures.setup_project_with_accepted_model(api)
    project = ctx["project"]
    instrument = fixtures.post_instrument(api, project["id"])
    allocated = fixtures.allocate_instrument(api, instrument)

    deallocated = validate_success(
        api.deallocate_financial_instrument(
            instrument["id"],
            {"deallocation_reason": "trust fund restructured before authorization"},
            fixtures.DEVELOPER,
        ),
        200,
    )
    assertions.assert_financial_instrument(deallocated)
    assertions.assert_dollar_conservation(deallocated)
    assert deallocated["status"] == "POSTED"
    assert deallocated["allocated_ca_usd"] == 0.00
    assert deallocated["allocated_plugging_usd"] == 0.00
    assert deallocated["allocated_pisc_usd"] == 0.00
    assert deallocated["allocated_emergency_usd"] == 0.00
    assert deallocated["unallocated_usd"] == 26000000.00
    assert deallocated["drawn_usd"] == 0.00
    assert deallocated["version"] > allocated["version"]

    emptied = fixtures.refresh_project(api, project["id"])
    assertions.assert_storage_project_invariants(emptied)
    assert emptied["allocated_assurance_usd"] == 0.00
    assert emptied["assurance_coverage_status"] == "UNFUNDED"

    # Re-running the waterfall on the same instrument reproduces the original split.
    reallocated = fixtures.allocate_instrument(api, deallocated)
    assertions.assert_financial_instrument(reallocated)
    assertions.assert_dollar_conservation(reallocated)
    assert reallocated["status"] == "ALLOCATED"
    assert reallocated["allocated_ca_usd"] == 0.00
    assert reallocated["allocated_plugging_usd"] == 0.00
    assert reallocated["allocated_pisc_usd"] == 10000000.00
    assert reallocated["allocated_emergency_usd"] == 2500000.00
    assert reallocated["unallocated_usd"] == 13500000.00
    assert reallocated["drawn_usd"] == 0.00

    refunded = fixtures.refresh_project(api, project["id"])
    assert refunded["allocated_assurance_usd"] == 12500000.00
    assert refunded["assurance_coverage_status"] == "FUNDED"


def test_storage_ledger_void_reverses_the_tonnes_and_the_credit_that_read_them(api):
    """Tonnes are conserved: after a record is created and then voided, the project's `cumulative_stored_tonnes` equals the sum over the remaining accepted records exactly.

    Voiding sets the record's `status` to `VOIDED`, stamps `voided_at` with the logical clock, recomputes the project's `cumulative_stored_tonnes` over the remaining accepted records, then recomputes `reported_tonnes`, `verified_tonnes`, `credit_rate_usd_per_tonne` and `credit_amount_usd` on every tax credit claim of the project whose `status` is `DRAFT` or `SUBMITTED` and whose `tax_year` covers the voided period, then recomputes the project's `pending_credit_usd`, and bumps the project's `version`.

    `verified_tonnes` is `reported_tonnes` less the leakage total less the lifecycle deduction, rounded half up to 3 decimal places.

    The rate is tiered on the project's ledger rather than on the claim's own tonnage, and it degrades as the project stores more: `credit_rate_usd_per_tonne` is 85.00 dollars per tonne while the project's `cumulative_stored_tonnes` is at most 500,000 tonnes, 70.00 dollars per tonne while it exceeds 500,000 but is at most 2,000,000 tonnes, and 55.00 dollars per tonne once it exceeds 2,000,000 tonnes.

    `credit_amount_usd` is the basis multiplied by `credit_rate_usd_per_tonne`, rounded half up to 2 decimal places, where the basis is `reported_tonnes` when the claim's `claim_variant` is `REPORTED` and `verified_tonnes` when it is `VERIFIED`.

    Design: Difficulty/compensating_invariant/storage_ledger_tonne_conservation_across_period_create_and_void
    """
    ctx = fixtures.setup_project_with_ledger(api)
    ctx = fixtures.setup_submitted_tax_credit_claim(
        api,
        ctx,
        tax_year=constants.TAX_YEAR,
        claim_variant="REPORTED",
        lca_upstream_emissions_factor=constants.LCA_UPSTREAM_EMISSIONS_FACTOR,
    )
    permit_id = ctx["permit"]["id"]
    first, second = ctx["periods"]
    claim = ctx["claim"]

    assert first["net_stored_tonnes"] == 299500.000
    assert second["net_stored_tonnes"] == 250000.000
    assert claim["reported_tonnes"] == 550000.000
    assert claim["credit_rate_usd_per_tonne"] == 70.00
    assert claim["credit_amount_usd"] == 38500000.00
    assert ctx["project"]["cumulative_stored_tonnes"] == 549500.000
    assert ctx["project"]["pending_credit_usd"] == 38500000.00

    ledger_before, _rows = _accepted_net_tonnes(api, permit_id)
    assert ledger_before == ctx["project"]["cumulative_stored_tonnes"]

    voided = fixtures.void_period(
        api,
        second["id"],
        void_reason="flow meter recalibration invalidated the reported mass",
    )
    assertions.assert_injection_period_record(voided)
    assert voided["status"] == "VOIDED"
    assert voided["voided_at"][:19] == "2028-02-01T00:00:00"

    reversed_claim = fixtures.refresh_claim(api, claim["id"])
    assertions.assert_tax_credit_claim(reversed_claim)
    assert reversed_claim["status"] == "SUBMITTED"
    assert reversed_claim["reported_tonnes"] == 300000.000
    assert reversed_claim["verified_tonnes"] == 284500.000
    assert reversed_claim["credit_rate_usd_per_tonne"] == 85.00
    assert reversed_claim["credit_amount_usd"] == 25500000.00

    after = fixtures.refresh_project(api, ctx["project"]["id"])
    assertions.assert_storage_project_invariants(after)
    assert after["cumulative_stored_tonnes"] == 299500.000
    assert after["pending_credit_usd"] == 25500000.00

    # The ledger is exactly the sum over what survives the void.
    ledger_after, _rows = _accepted_net_tonnes(api, permit_id)
    assert ledger_after == after["cumulative_stored_tonnes"]


def test_storage_ledger_restored_exactly_when_the_voided_window_is_re_reported(api):
    """Tonnes are conserved: after a record is created and then voided, the project's `cumulative_stored_tonnes` equals the sum over the remaining accepted records exactly.

    The secure-storage ledger is the project's `cumulative_stored_tonnes`: the sum of `net_stored_tonnes` over every injection period record belonging to any permit of that project whose `status` is `ACCEPTED`, processed in `period_start` ascending order with ties broken by `created_at` ascending, and rounded half up to 3 decimal places.

    Records whose `status` is `VOIDED` are excluded entirely.

    Each record's `net_stored_tonnes` is its `mass_injected_tonnes` less its `measured_leakage_tonnes`, rounded half up to 3 decimal places, and the record rests at `status` `ACCEPTED` with `voided_at` null.

    Design: Difficulty/compensating_invariant/storage_ledger_tonne_conservation_across_period_create_and_void
    """
    ctx = fixtures.setup_project_with_ledger(api)
    ctx = fixtures.setup_submitted_tax_credit_claim(
        api,
        ctx,
        tax_year=constants.TAX_YEAR,
        claim_variant="REPORTED",
        lca_upstream_emissions_factor=constants.LCA_UPSTREAM_EMISSIONS_FACTOR,
    )
    permit_id = ctx["permit"]["id"]
    first, second = ctx["periods"]

    fixtures.void_period(
        api,
        second["id"],
        void_reason="flow meter recalibration invalidated the reported mass",
    )

    replacement = fixtures.report_period(
        api,
        permit_id,
        "2027-07-01T00:00:00Z",
        "2027-10-01T00:00:00Z",
        250000,
        measured_leakage_tonnes=0,
    )
    assertions.assert_injection_period_record(replacement)
    assert replacement["status"] == "ACCEPTED"
    assert replacement["net_stored_tonnes"] == 250000.000
    assert replacement["voided_at"] is None

    restored = fixtures.refresh_project(api, ctx["project"]["id"])
    assertions.assert_storage_project_invariants(restored)
    assert restored["cumulative_stored_tonnes"] == 549500.000

    ledger, rows = _accepted_net_tonnes(api, permit_id)
    assert ledger == restored["cumulative_stored_tonnes"]

    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["status"] == "ACCEPTED"
    assert by_id[second["id"]]["status"] == "VOIDED"
    assert by_id[replacement["id"]]["status"] == "ACCEPTED"
