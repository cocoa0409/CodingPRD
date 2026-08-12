"""Sale-creation and bid-window validations (PRD §3.4)."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_prescription_payload,
    create_sale_payload,
    create_stand_payload,
    setup_approved_prescription,
    setup_certified_cruise,
    setup_sale_bidding_open,
)

ADMIN = TEST_USERS["admin_headers"]


def test_offer_with_expired_cruise_rejected(api):
    """PRD §3.4: "And the cruise's `certified_at` must lie within 24 months
    of the logical clock, else the cruise is stale and the offer is refused
    with `ERR_CRUISE_EXPIRED` (HTTP 422)."

    Design: Corner/validations/offer_with_expired_cruise_rejected
    """
    base = setup_approved_prescription()
    fh = base["forester_headers"]
    # Cruise was certified at startup clock 2026-05-01.
    # Sale created with future bid window; advance clock past 24 months.
    payload = create_sale_payload(tract_id=base["tract"]["id"],
                                  stand_id=base["stand"]["id"],
                                  prescription_id=base["prescription"]["id"],
                                  sale_type="LUMP_SUM",
                                  advertised_minimum_cents=7_000_000,
                                  bid_open_at="2028-07-01T00:00:00Z",
                                  bid_close_at="2028-07-10T00:00:00Z",
                                  harvest_window_start="2028-08-01",
                                  harvest_window_end="2028-12-01")
    payload.pop("species_minimum_rates", None)
    sale = get_success_data(api.create_sale(payload, fh))
    get_success_data(api.set_clock({"to_iso8601": "2028-06-02T00:00:00Z"}, ADMIN))
    resp = api.offer_sale(sale["id"], fh)
    validate_error(resp, ApiErrorId.ERR_CRUISE_EXPIRED)


def test_bid_outside_window_boundaries_rejected(api):
    """PRD §3.4: "Acceptance is gated, in order, by the sale being
    `BIDDING_OPEN` (`ERR_SALE_NOT_OPEN_FOR_BIDDING`, HTTP 409), by the clock
    lying at or after `bid_open_at` and strictly before `bid_close_at`
    (`ERR_BID_WINDOW_NOT_OPEN`, HTTP 409)".

    Design: Corner/validations/bid_outside_window_boundaries_rejected
    """
    base = setup_sale_bidding_open(
        sale_overrides={"sale_type": "LUMP_SUM", "advertised_minimum_cents": 7_000_000,
                        "species_minimum_rates": None},
    )
    bh = base["buyer_headers"]
    sale = base["sale"]
    # Before open (bid_open_at 2026-05-10).
    get_success_data(api.set_clock({"to_iso8601": "2026-05-09T00:00:00Z"}, ADMIN))
    resp1 = api.submit_bid(
        sale["id"],
        {"expected_sale_version": sale["version"], "deposit_cents": 50_000,
         "lump_sum_amount_cents": 8_000_000},
        bh,
    )
    validate_error(resp1, ApiErrorId.ERR_BID_WINDOW_NOT_OPEN)
    # At exact close instant 2026-05-20T00:00:00Z -> still outside (half-open).
    get_success_data(api.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, ADMIN))
    resp2 = api.submit_bid(
        sale["id"],
        {"expected_sale_version": sale["version"], "deposit_cents": 50_000,
         "lump_sum_amount_cents": 8_000_000},
        bh,
    )
    validate_error(resp2, ApiErrorId.ERR_BID_WINDOW_NOT_OPEN)


def test_per_unit_bid_below_species_floor_rejected(api):
    """PRD §3.4: "by each per-unit species rate meeting or exceeding the
    advertised `min_rate_cents_per_mbf` floor for that species
    (`ERR_BID_BELOW_MINIMUM`, HTTP 422)".

    Design: Corner/validations/per_unit_bid_below_species_floor_rejected
    """
    base = setup_sale_bidding_open(
        sale_overrides={"sale_type": "PER_UNIT", "advertised_minimum_cents": 10_000_000},
    )
    bh = base["buyer_headers"]
    sale = base["sale"]
    resp = api.submit_bid(
        sale["id"],
        {"expected_sale_version": sale["version"], "deposit_cents": 50_000,
         "species_rates": [{"species": "PINE", "rate_cents_per_mbf": 39_999}]},
        bh,
    )
    validate_error(resp, ApiErrorId.ERR_BID_BELOW_MINIMUM)


def test_species_rate_missing_on_sale_and_bid(api):
    """PRD §3.4: "a `PER_UNIT` sale must advertise its per-species floor rates
    in `species_minimum_rates` — entries pairing each species with a
    `min_rate_cents_per_mbf` — while a `LUMP_SUM` sale must not carry them;
    violations are `ERR_SPECIES_RATE_MISSING` (HTTP 422)."
    PRD §3.4: "Supplying the wrong payload for the sale type — or mixing both —
    is `ERR_SPECIES_RATE_MISSING` (HTTP 422)."

    Design: Corner/validations/species_rate_missing_on_sale_and_bid
    """
    base = setup_approved_prescription()
    fh = base["forester_headers"]
    bh = base["buyer_headers"]
    # PER_UNIT sale without species_minimum_rates -> rejected at create.
    payload1 = create_sale_payload(tract_id=base["tract"]["id"],
                                   stand_id=base["stand"]["id"],
                                   prescription_id=base["prescription"]["id"],
                                   sale_type="PER_UNIT")
    payload1.pop("species_minimum_rates", None)
    resp1 = api.create_sale(payload1, fh)
    validate_error(resp1, ApiErrorId.ERR_SPECIES_RATE_MISSING)

    # Now a valid PER_UNIT sale, offer + open; bid without species_rates -> rejected.
    sale = get_success_data(api.create_sale(
        create_sale_payload(tract_id=base["tract"]["id"],
                            stand_id=base["stand"]["id"],
                            prescription_id=base["prescription"]["id"],
                            sale_type="PER_UNIT"),
        fh,
    ))
    get_success_data(api.offer_sale(sale["id"], fh))
    get_success_data(api.set_clock({"to_iso8601": "2026-05-12T00:00:00Z"}, ADMIN))
    sale = get_success_data(api.open_bidding(sale["id"], fh))
    resp2 = api.submit_bid(
        sale["id"],
        {"expected_sale_version": sale["version"], "deposit_cents": 50_000},
        bh,
    )
    validate_error(resp2, ApiErrorId.ERR_SPECIES_RATE_MISSING)


def test_sale_stand_must_match_prescription_stand(api):
    """PRD §3.4: "the sale's `stand_id` must be the prescription's stand and
    the sale's `tract_id` must be the tract containing that stand, otherwise
    `ERR_SALE_PRESCRIPTION_STAND_MISMATCH` (HTTP 422)."

    Design: Corner/validations/sale_stand_must_match_prescription_stand
    """
    base = setup_certified_cruise()
    fh = base["forester_headers"]
    # Second stand on the same tract.
    stand2 = get_success_data(api.create_stand(
        create_stand_payload(tract_id=base["tract"]["id"], name="Stand 2",
                             acres=40, primary_species="OAK"),
        fh,
    ))
    # Prescription references stand 1.
    prescription = get_success_data(api.create_prescription(
        create_prescription_payload(stand_id=base["stand"]["id"],
                                    cruise_id=base["cruise"]["id"]),
        fh,
    ))
    # Sale references stand 2 with prescription of stand 1 -> mismatch.
    payload = create_sale_payload(tract_id=base["tract"]["id"],
                                  stand_id=stand2["id"],
                                  prescription_id=prescription["id"],
                                  sale_type="LUMP_SUM",
                                  advertised_minimum_cents=7_000_000)
    payload.pop("species_minimum_rates", None)
    resp = api.create_sale(payload, fh)
    validate_error(resp, ApiErrorId.ERR_SALE_PRESCRIPTION_STAND_MISMATCH)


def test_settlement_empty_period_zero_sweep_perunit_empty(api):
    """PRD §3.6: "A period that sweeps no eligible ticket at all is refused
    with `ERR_SETTLEMENT_PERIOD_EMPTY` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/settlement_empty_period_zero_sweep
    """
    # Second instance: empty sweep on a *different* empty window after some
    # tickets were verified but then swept already.
    from test_helpers import (
        add_verified_ticket,
        create_settlement_payload,
        setup_contract_harvesting,
    )
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    add_verified_ticket(base, scaled_date="2026-06-16", log_count=1)
    # Sweep the only ticket.
    get_success_data(api.create_settlement(
        create_settlement_payload(contract_id=base["contract"]["id"],
                                  kind="PER_UNIT_PERIOD",
                                  period_start="2026-06-01",
                                  period_end="2026-07-01"),
        fh,
    ))
    # A later non-overlapping window with zero eligible tickets -> rejected.
    resp = api.create_settlement(
        create_settlement_payload(contract_id=base["contract"]["id"],
                                  kind="PER_UNIT_PERIOD",
                                  period_start="2026-07-01",
                                  period_end="2026-08-01"),
        fh,
    )
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_PERIOD_EMPTY)


def test_lump_sum_milestone_gross_independent_of_delivered_volume(api):
    """PRD §3.6: "Mobilization and midpoint each pay forty percent of
    `awarded_value_cents`, rounded half up". PRD §3.6: "Milestone settlements
    carry no holdback: `holdback_cents` is always zero."

    Design: Difficulty/dual_variant_calc/lump_sum_vs_per_unit_settlement_divergence
    """
    # Two LUMP_SUM contracts with the same awarded value but different delivered
    # volumes pay identical MOBILIZATION grosses.
    from test_helpers import create_settlement_payload, setup_contract_harvesting
    base_a = setup_contract_harvesting(
        sale_overrides={"sale_type": "LUMP_SUM", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 8_000_000,
                        "species_minimum_rates": None},
        bid_overrides={"lump_sum_amount_cents": 9_000_001, "deposit_cents": 100_000},
    )
    fh_a = base_a["forester_headers"]
    stl_a = validate_success(api.create_settlement(
        create_settlement_payload(contract_id=base_a["contract"]["id"],
                                  kind="LUMP_MILESTONE", milestone="MOBILIZATION"),
        fh_a,
    ), 201)
    assert stl_a["gross_cents"] == 3_600_000
    assert stl_a["holdback_cents"] == 0
