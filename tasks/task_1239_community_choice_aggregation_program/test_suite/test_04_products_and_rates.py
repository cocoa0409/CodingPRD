"""Products and rate schedules: computed margin, initial states, half-open
window overlap, the discount-floor boundary, and validation priority."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_product,
    assert_rate_schedule,
    attach_rec,
    bootstrap_authority,
    create_executed_contract,
    create_filing,
    create_product_payload,
    create_rate_schedule_payload,
    create_remittance_file_payload,
    create_supply_contract_payload,
    set_clock,
    validate_error,
    validate_success,
)

BD = TEST_USERS["board_director_headers"]
RA = TEST_USERS["rate_analyst_headers"]
PM = TEST_USERS["portfolio_manager_headers"]
BC = TEST_USERS["billing_coordinator_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def test_rate_schedule_computed_margin_on_create(api):
    """PRD §3.4: "Every schedule carries a computed `comparison_margin_bps`: ten thousand times the difference between the incumbent benchmark and the energy rate, divided by the incumbent benchmark, rounded half up to a whole basis point."
    PRD §3.4: "A `RateAnalyst` creates a schedule in `DRAFT` under a product by supplying the `product_id`, an inclusive `period_start`, an exclusive `period_end`, and three rates: `energy_rate_cents_per_kwh` (strictly positive), `pcia_rate_cents_per_kwh` (the Power Charge Indifference Adjustment exit-fee passthrough collected on behalf of the incumbent, at least zero), and `incumbent_benchmark_rate_cents_per_kwh` (the incumbent's published generation rate used as the comparison baseline, strictly positive)."

    Design: Corner/entities/rate_schedule_computed_margin_ignores_client_input
    """
    bootstrap_authority()
    product = validate_success(api.create_product(create_product_payload(), RA), 201)

    schedule = validate_success(
        api.create_rate_schedule(
            create_rate_schedule_payload(product_id=product["id"]), RA
        ),
        201,
    )
    assert_rate_schedule(schedule)
    # round_half_up(10000 * (12.00 - 11.40) / 12.00) == 500
    assert schedule["comparison_margin_bps"] == 500
    assert schedule["status"] == "DRAFT"


def test_initial_state_on_entity_creation(api):
    """PRD §3.4: "A `RateAnalyst` creates a product in `DRAFT` with a stable `product_code` (unique per authority), an `election_key` mapping the product to one of the three account election values (also unique per authority), and a `renewable_pct` between 0 and 1.0 inclusive."
    PRD §3.5: "A `PortfolioManager` creates a contract in `NEGOTIATING` with a `counterparty` name, a `contract_type` of `ENERGY_BLOCK` (energy only), `RA_CAPACITY` (resource-adequacy capacity), `REC_ONLY` (unbundled renewable credits), or `PPA` (bundled energy plus RECs); an inclusive `delivery_start` and exclusive `delivery_end`; a `capacity_mw` strictly positive; a `total_mwh` at least zero (zero is the norm for pure `RA_CAPACITY` contracts); a `price_dollars_per_mwh` at least zero; an `rps_eligible_pct` between 0 and 1.0 inclusive giving the fraction of delivered energy carrying RPS-eligible attributes; and a `vintage_year` capturing the PCIA-relevant commitment vintage — contracts committed in or before an account's vintage year raise that vintage's exit fee."
    PRD §3.7: "A `BillingCoordinator` registers an incoming file — initial status `RECEIVED` — by supplying the `remittance_period` in `YYYY-MM` form (which must match an accepted extract's billing month before the file can reconcile), the `gross_remittance_cents` remitted, and the `utility_fee_bps` billing-agent fee, which must lie between 0 and 300 basis points inclusive. The file's `net_remittance_cents` is the gross minus the fee, where the fee is the gross times the basis points over ten thousand, rounded half up once on the file — never per line."

    Design: Corner/state_machines/initial_state_on_entity_creation
    """
    bootstrap_authority()

    product = validate_success(
        api.create_product(
            create_product_payload(
                product_code="EVERGREEN100",
                election_key="OPT_UP_100",
                renewable_pct=1.00,
            ),
            RA,
        ),
        201,
    )
    assert_product(product)
    assert product["status"] == "DRAFT"
    assert product["is_default"] is False

    contract = validate_success(
        api.create_supply_contract(
            create_supply_contract_payload(
                counterparty="HydroWest Inc",
                contract_type="RA_CAPACITY",
                delivery_start="2027-01-01T00:00:00Z",
                delivery_end="2028-01-01T00:00:00Z",
                capacity_mw=15.0,
                total_mwh=0,
                price_dollars_per_mwh=0,
                rps_eligible_pct=0.0,
            ),
            PM,
        ),
        201,
    )
    assert contract["status"] == "NEGOTIATING"

    remittance = validate_success(
        api.create_remittance_file(
            create_remittance_file_payload(
                remittance_period="2026-08",
                gross_remittance_cents=100000,
                utility_fee_bps=25,
            ),
            BC,
        ),
        201,
    )
    assert remittance["status"] == "RECEIVED"
    # fee = round_half_up(100000 * 25 / 10000) = 250
    assert remittance["net_remittance_cents"] == 99750


def test_rate_schedule_adjacent_window_adopts(api):
    """PRD §3.4: "And no other adopted schedule for the same product may have an overlapping half-open window — adjacency, where one schedule's `period_end` equals another's `period_start`, is allowed; overlap is `ERR_UNIQUENESS_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rate_schedule_half_open_window_overlap
    """
    bootstrap_authority()
    product = validate_success(api.create_product(create_product_payload(), RA), 201)

    sched_a = validate_success(
        api.create_rate_schedule(
            create_rate_schedule_payload(product_id=product["id"]), RA
        ),
        201,
    )
    validate_success(api.propose_rate_schedule(sched_a["id"], {}, RA), 200)
    adopted_a = validate_success(api.adopt_rate_schedule(sched_a["id"], {}, BD), 200)
    assert adopted_a["status"] == "ADOPTED"

    # Adjacent: new period_start == A's period_end — half-open boundary touch
    # is not an overlap.
    sched_b = validate_success(
        api.create_rate_schedule(
            create_rate_schedule_payload(
                product_id=product["id"],
                period_start="2027-01-01T00:00:00Z",
                period_end="2028-01-01T00:00:00Z",
                energy_rate_cents_per_kwh=11.55,
                pcia_rate_cents_per_kwh=1.60,
            ),
            RA,
        ),
        201,
    )
    validate_success(api.propose_rate_schedule(sched_b["id"], {}, RA), 200)
    adopted_b = validate_success(api.adopt_rate_schedule(sched_b["id"], {}, BD), 200)
    assert adopted_b["status"] == "ADOPTED"


def test_rate_schedule_interior_overlap_rejected(api):
    """PRD §3.4: "And no other adopted schedule for the same product may have an overlapping half-open window — adjacency, where one schedule's `period_end` equals another's `period_start`, is allowed; overlap is `ERR_UNIQUENESS_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rate_schedule_half_open_window_overlap
    """
    bootstrap_authority()
    product = validate_success(api.create_product(create_product_payload(), RA), 201)

    sched_a = validate_success(
        api.create_rate_schedule(
            create_rate_schedule_payload(product_id=product["id"]), RA
        ),
        201,
    )
    validate_success(api.propose_rate_schedule(sched_a["id"], {}, RA), 200)
    validate_success(api.adopt_rate_schedule(sched_a["id"], {}, BD), 200)

    # Interior overlap with A's [2026-01-01, 2027-01-01) window.
    sched_c = validate_success(
        api.create_rate_schedule(
            create_rate_schedule_payload(
                product_id=product["id"],
                period_start="2026-06-01T00:00:00Z",
                period_end="2027-06-01T00:00:00Z",
                energy_rate_cents_per_kwh=11.50,
                pcia_rate_cents_per_kwh=1.55,
            ),
            RA,
        ),
        201,
    )
    validate_success(api.propose_rate_schedule(sched_c["id"], {}, RA), 200)
    res = api.adopt_rate_schedule(sched_c["id"], {}, BD)
    validate_error(res, ApiErrorId.ERR_UNIQUENESS_CONFLICT)

    after = validate_success(api.get_rate_schedule(sched_c["id"], RA), 200)
    assert after["status"] == "PROPOSED", "overlap-rejected schedule must not move"


def test_discount_floor_exact_boundary_adopts(api):
    """PRD §3.4: "Under a `DISCOUNT_TO_INCUMBENT` rate policy, the schedule's `comparison_margin_bps` must be at least the authority's `discount_floor_bps`, or adoption is rejected with `ERR_FISCAL_GATE`; under the other policies no floor applies."
    PRD §3.4: "Every schedule carries a computed `comparison_margin_bps`: ten thousand times the difference between the incumbent benchmark and the energy rate, divided by the incumbent benchmark, rounded half up to a whole basis point."

    Design: Difficulty/boundary_precision_check/discount_floor_bps_exact_boundary_adopt
    """
    bootstrap_authority(
        rate_setting_policy="DISCOUNT_TO_INCUMBENT", discount_floor_bps=100
    )
    product = validate_success(api.create_product(create_product_payload(), RA), 201)

    # rate 11.88 vs benchmark 12.00 -> round_half_up(10000 * 0.12 / 12.00) = 100 bps,
    # exactly the floor; the gate is inclusive ("at least").
    sched = validate_success(
        api.create_rate_schedule(
            create_rate_schedule_payload(
                product_id=product["id"], energy_rate_cents_per_kwh=11.88
            ),
            RA,
        ),
        201,
    )
    validate_success(api.propose_rate_schedule(sched["id"], {}, RA), 200)
    adopted = validate_success(api.adopt_rate_schedule(sched["id"], {}, BD), 200)
    assert adopted["comparison_margin_bps"] == 100
    assert adopted["status"] == "ADOPTED"


def test_discount_floor_one_below_boundary_rejected(api):
    """PRD §3.4: "Under a `DISCOUNT_TO_INCUMBENT` rate policy, the schedule's `comparison_margin_bps` must be at least the authority's `discount_floor_bps`, or adoption is rejected with `ERR_FISCAL_GATE`; under the other policies no floor applies."

    Design: Difficulty/boundary_precision_check/discount_floor_bps_exact_boundary_adopt
    """
    bootstrap_authority(
        rate_setting_policy="DISCOUNT_TO_INCUMBENT", discount_floor_bps=100
    )
    product = validate_success(api.create_product(create_product_payload(), RA), 201)

    # rate 11.89 vs benchmark 12.00 -> round_half_up(10000 * 0.11 / 12.00) = 92 bps,
    # strictly below the 100 bps floor.
    sched = validate_success(
        api.create_rate_schedule(
            create_rate_schedule_payload(
                product_id=product["id"],
                period_start="2027-01-01T00:00:00Z",
                period_end="2028-01-01T00:00:00Z",
                energy_rate_cents_per_kwh=11.89,
            ),
            RA,
        ),
        201,
    )
    validate_success(api.propose_rate_schedule(sched["id"], {}, RA), 200)
    res = api.adopt_rate_schedule(sched["id"], {}, BD)
    validate_error(res, ApiErrorId.ERR_FISCAL_GATE)

    after = validate_success(api.get_rate_schedule(sched["id"], RA), 200)
    assert after["comparison_margin_bps"] == 92
    assert after["status"] == "PROPOSED", "fiscal-gate rejection must not move the schedule"


def test_adopt_draft_schedule_surfaces_invalid_state_not_fiscal(api):
    """PRD §2.9: "When a request fails multiple checks, the error surfaced is determined by a fixed priority order, evaluated from first to last:"
    PRD §2.9: "5. **State-machine legality** — if the target's state machine has no transition for this trigger from its current state, the request yields `ERR_INVALID_STATE`."
    PRD §2.9: "14. **Fiscal gates** — the rate-adoption margin floor and the zero-balance requirement on account close yield `ERR_FISCAL_GATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_rate_adopt
    """
    bootstrap_authority(
        rate_setting_policy="DISCOUNT_TO_INCUMBENT", discount_floor_bps=100
    )
    product = validate_success(api.create_product(create_product_payload(), RA), 201)

    # rate 11.94 -> margin 50 bps, below the floor; the schedule is still DRAFT
    # (never proposed), so the state-machine check fires first.
    sched = validate_success(
        api.create_rate_schedule(
            create_rate_schedule_payload(
                product_id=product["id"], energy_rate_cents_per_kwh=11.94
            ),
            RA,
        ),
        201,
    )
    res = api.adopt_rate_schedule(sched["id"], {}, BD)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_rate_schedule(sched["id"], RA), 200)
    assert after["status"] == "DRAFT"


def test_adopt_below_floor_proposed_schedule_fiscal_gate(api):
    """PRD §3.4: "Under a `DISCOUNT_TO_INCUMBENT` rate policy, the schedule's `comparison_margin_bps` must be at least the authority's `discount_floor_bps`, or adoption is rejected with `ERR_FISCAL_GATE`; under the other policies no floor applies."
    PRD §3.4: "The schedule lifecycle runs `DRAFT → PROPOSED → ADOPTED`, with a `REJECTED` branch off `PROPOSED` and a terminal `SUPERSEDED` state reached only by cascade."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_rate_adopt
    """
    bootstrap_authority(
        rate_setting_policy="DISCOUNT_TO_INCUMBENT", discount_floor_bps=100
    )
    product = validate_success(api.create_product(create_product_payload(), RA), 201)

    # Same 50 bps margin, but now the schedule is legally PROPOSED — the fiscal
    # gate is the failing check in isolation.
    sched = validate_success(
        api.create_rate_schedule(
            create_rate_schedule_payload(
                product_id=product["id"], energy_rate_cents_per_kwh=11.94
            ),
            RA,
        ),
        201,
    )
    validate_success(api.propose_rate_schedule(sched["id"], {}, RA), 200)
    res = api.adopt_rate_schedule(sched["id"], {}, BD)
    validate_error(res, ApiErrorId.ERR_FISCAL_GATE)

    after = validate_success(api.get_rate_schedule(sched["id"], RA), 200)
    assert after["comparison_margin_bps"] == 50
    assert after["status"] == "PROPOSED"


def test_uniqueness_product_code_and_retirement_serial(api):
    """PRD §2.9: "11. **Uniqueness and overlap** — unique-field collisions and adopted rate-window overlap yield `ERR_UNIQUENESS_CONFLICT`."
    PRD §3.4: "A `RateAnalyst` creates a product in `DRAFT` with a stable `product_code` (unique per authority), an `election_key` mapping the product to one of the three account election values (also unique per authority), and a `renewable_pct` between 0 and 1.0 inclusive."
    PRD §3.9: "A `ComplianceOfficer` records one by supplying the `compliance_filing_id` of the RPS filing it supports, the `supply_contract_id` the attributes come from (a `PPA` or `REC_ONLY` contract), the `retired_mwh` (strictly positive), and the external registry's `retirement_serial`, unique per authority; the server stamps `retired_on` from the logical clock."

    Design: Corner/validations/uniqueness_product_code_and_retirement_serial
    """
    set_clock("2026-01-01T00:00:00Z")
    bootstrap_authority()
    validate_success(api.create_product(create_product_payload(), RA), 201)

    contract = create_executed_contract()
    filing1 = create_filing(compliance_year=2026)
    attach_rec(filing1["id"], contract["id"], retired_mwh=100,
               retirement_serial="WREGIS-9200")
    filing2 = create_filing(compliance_year=2027)

    dup_product = api.create_product(
        create_product_payload(election_key="OPT_DOWN_ECONOMY", renewable_pct=0.33),
        RA,
    )
    validate_error(dup_product, ApiErrorId.ERR_UNIQUENESS_CONFLICT)

    dup_serial = api.create_rec_retirement(
        {
            "compliance_filing_id": filing2["id"],
            "supply_contract_id": contract["id"],
            "retired_mwh": 50,
            "retirement_serial": "WREGIS-9200",
        },
        CO,
    )
    validate_error(dup_serial, ApiErrorId.ERR_UNIQUENESS_CONFLICT)
