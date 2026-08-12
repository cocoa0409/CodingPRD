"""Contract lifecycle: default/cure, stop-work cascade, close (PRD §3.5, §3.7)."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_verified_ticket,
    create_inspection_payload,
    create_scale_ticket_payload,
    create_settlement_payload,
    setup_contract_active,
    setup_contract_harvesting,
    setup_per_unit_settlement_draft,
)

ADMIN = TEST_USERS["admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


def test_contract_default_cure_cycle(api):
    """PRD §3.5: "the contract moves to `DEFAULTED`, `defaulted_at` is
    stamped, and the bond — if `POSTED` — is automatically claimed, moving to
    `FORFEIT_CLAIMED` without any separate filing."
    PRD §3.5: "on cure the pending claim is automatically denied and the bond
    returns to `POSTED`, with both the contract's and the bond's versions
    incrementing."

    Design: Difficulty/non_linear_state_machine/contract_default_cure_cycle
    """
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    bh = base["buyer_headers"]
    contract = base["contract"]
    bond = base["bond"]

    defaulted = validate_success(api.declare_default(contract["id"], {}, fh))
    assert defaulted["status"] == "DEFAULTED"
    assert defaulted["defaulted_at"] is not None
    bond_mid = get_success_data(api.get_bond(bond["id"], fh))
    assert bond_mid["status"] == "FORFEIT_CLAIMED"

    # Cure within window.
    get_success_data(api.set_clock({"to_iso8601": "2026-06-20T00:00:00Z"}, ADMIN))
    cured = validate_success(api.cure_contract(contract["id"], bh))
    assert cured["status"] == "HARVESTING"
    bond_end = get_success_data(api.get_bond(bond["id"], fh))
    assert bond_end["status"] == "POSTED"


def test_default_auto_claims_bond(api):
    """PRD §3.5: "the contract moves to `DEFAULTED`, `defaulted_at` is
    stamped, and the bond — if `POSTED` — is automatically claimed, moving to
    `FORFEIT_CLAIMED` without any separate filing."

    Design: Difficulty/non_linear_state_machine/contract_default_cure_cycle
    """
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    get_success_data(api.declare_default(base["contract"]["id"], {}, fh))
    bond = get_success_data(api.get_bond(base["bond"]["id"], fh))
    assert bond["status"] == "FORFEIT_CLAIMED"


def test_cure_after_period_rejected(api):
    """PRD §3.5: "requires the clock to be no more than 14 days past
    `defaulted_at` (a later cure is `ERR_CURE_PERIOD_EXPIRED`, HTTP 422)".

    Design: Corner/validations/cure_after_period_rejected
    """
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "LUMP_SUM", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 7_000_000,
                        "species_minimum_rates": None},
        bid_overrides={"lump_sum_amount_cents": 8_000_000, "deposit_cents": 100_000},
        clock_iso="2026-06-15T00:00:00Z",
    )
    fh = base["forester_headers"]
    bh = base["buyer_headers"]
    contract = base["contract"]
    get_success_data(api.declare_default(contract["id"], {}, fh))
    # 15 days past defaulted_at (2026-06-15 + 15 = 2026-06-30).
    get_success_data(api.set_clock({"to_iso8601": "2026-06-30T00:00:00Z"}, ADMIN))
    resp = api.cure_contract(contract["id"], bh)
    validate_error(resp, ApiErrorId.ERR_CURE_PERIOD_EXPIRED)
    contract_now = get_success_data(api.get_contract(contract["id"], fh))
    assert contract_now["status"] == "DEFAULTED"


def test_inspection_stop_work_depth3_chain(api):
    """PRD §3.7: "A `MAJOR` noncompliance on a contract that is currently
    `HARVESTING` is the automatic trigger for the stop-work cascade of §3.5:
    the contract is suspended on the spot — which itself flags every `DRAFT`
    and `VERIFIED` scale ticket of the contract for review and voids every
    affected `DRAFT` settlement with its billed, holdback, and fee reversals —
    and the contract's `open_major_findings_count` is recomputed."

    Design: Difficulty/transitive_cascade/inspection_stop_work_depth3_chain
    """
    # Setup: HARVESTING with one VERIFIED ticket swept into DRAFT settlement
    # and one still-DRAFT ticket; one CONDUCTED inspection.
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    ch = base["contractor_headers"]
    tk1 = add_verified_ticket(base, scaled_date="2026-06-16", log_count=1)
    settlement = get_success_data(api.create_settlement(
        create_settlement_payload(contract_id=base["contract"]["id"],
                                  kind="PER_UNIT_PERIOD",
                                  period_start="2026-06-01",
                                  period_end="2026-07-01"),
        fh,
    ))
    assert settlement["gross_cents"] == 4_500
    tk2 = get_success_data(api.create_scale_ticket(
        create_scale_ticket_payload(contract_id=base["contract"]["id"],
                                    scaled_date="2026-06-20", species="PINE",
                                    small_end_diameter_in=14, length_ft=16, log_count=1),
        ch,
    ))
    insp = get_success_data(api.create_inspection(
        create_inspection_payload(contract_id=base["contract"]["id"],
                                  inspection_type="ACTIVE_HARVEST",
                                  scheduled_date="2026-06-25"),
        fh,
    ))
    get_success_data(api.conduct_inspection(insp["id"], INSPECTOR))

    closed = validate_success(api.close_inspection(
        insp["id"],
        {"outcome": "NONCOMPLIANT", "severity": "MAJOR",
         "remediation_cost_estimate_cents": 300_000,
         "findings": "unstable stream crossing"},
        INSPECTOR,
    ))
    assert closed["status"] == "NONCOMPLIANT"

    contract = get_success_data(api.get_contract(base["contract"]["id"], fh))
    assert contract["status"] == "SUSPENDED"
    assert contract["open_major_findings_count"] == 1
    assert contract["billed_total_cents"] == 0

    tk1_now = get_success_data(api.get_scale_ticket(tk1["id"], fh))
    tk2_now = get_success_data(api.get_scale_ticket(tk2["id"], fh))
    assert tk1_now["flagged_for_review"] is True
    assert tk2_now["flagged_for_review"] is True
    stl_now = get_success_data(api.get_settlement(settlement["id"], fh))
    assert stl_now["status"] == "VOID"


def test_inspection_major_suspends_harvesting_contract(api):
    """PRD §3.7: "A `MAJOR` noncompliance on a contract that is currently
    `HARVESTING` is the automatic trigger for the stop-work cascade of §3.5:
    the contract is suspended on the spot".

    Design: Difficulty/transitive_cascade/inspection_stop_work_depth3_chain
    """
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    insp = get_success_data(api.create_inspection(
        create_inspection_payload(contract_id=base["contract"]["id"],
                                  inspection_type="ACTIVE_HARVEST",
                                  scheduled_date="2026-06-25"),
        fh,
    ))
    get_success_data(api.conduct_inspection(insp["id"], INSPECTOR))
    get_success_data(api.close_inspection(
        insp["id"], {"outcome": "NONCOMPLIANT", "severity": "MAJOR",
                     "findings": "spill"}, INSPECTOR,
    ))
    contract = get_success_data(api.get_contract(base["contract"]["id"], fh))
    assert contract["status"] == "SUSPENDED"
    assert contract["open_major_findings_count"] == 1


def test_minor_finding_does_not_suspend_contract(api):
    """PRD §3.7: "A `MINOR` finding, or a `MAJOR` finding on a contract not
    currently harvesting, records the noncompliance and recomputes the count
    without disturbing the contract's state."

    Design: Corner/state_machines/minor_finding_does_not_suspend_contract
    """
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    insp = get_success_data(api.create_inspection(
        create_inspection_payload(contract_id=base["contract"]["id"],
                                  inspection_type="ACTIVE_HARVEST",
                                  scheduled_date="2026-06-16"),
        fh,
    ))
    get_success_data(api.conduct_inspection(insp["id"], INSPECTOR))
    closed = validate_success(api.close_inspection(
        insp["id"], {"outcome": "NONCOMPLIANT", "severity": "MINOR",
                     "findings": "signage faded"}, INSPECTOR,
    ))
    assert closed["status"] == "NONCOMPLIANT"
    contract = get_success_data(api.get_contract(base["contract"]["id"], fh))
    assert contract["status"] == "HARVESTING"
    assert contract["open_major_findings_count"] == 0


def test_safety_beats_temporal_on_start_harvest(api):
    """PRD §3.5: "starting the harvest moves `ACTIVE → HARVESTING` only when
    the acting contractor is the contract's `contractor_id`, when
    `open_major_findings_count` is zero — any open `MAJOR` BMP finding refuses
    the start with `ERR_OPEN_MAJOR_FINDING` (HTTP 409), and this check
    precedes the window checks".

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_start_harvest
    """
    # Contract ACTIVE with an open MAJOR finding (closed PRE_HARVEST inspection
    # before harvest started), and clock outside both windows.
    base = setup_contract_active(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    # Schedule + conduct + close PRE_HARVEST NONCOMPLIANT/MAJOR on the ACTIVE contract.
    insp = get_success_data(api.create_inspection(
        create_inspection_payload(contract_id=base["contract"]["id"],
                                  inspection_type="PRE_HARVEST",
                                  scheduled_date="2026-05-25"),
        fh,
    ))
    get_success_data(api.conduct_inspection(insp["id"], INSPECTOR))
    get_success_data(api.close_inspection(
        insp["id"], {"outcome": "NONCOMPLIANT", "severity": "MAJOR",
                     "findings": "stream buffer flagged"}, INSPECTOR,
    ))
    # Push clock outside both windows (harvest window 2026-06-01..2026-10-01).
    get_success_data(api.set_clock({"to_iso8601": "2027-01-15T00:00:00Z"}, ADMIN))
    resp = api.start_harvest(base["contract"]["id"], base["contractor_headers"])
    validate_error(resp, ApiErrorId.ERR_OPEN_MAJOR_FINDING)
    contract_now = get_success_data(api.get_contract(base["contract"]["id"], fh))
    assert contract_now["status"] == "ACTIVE"


def test_open_major_finding_blocks_start_harvest(api):
    """PRD §3.5: "any open `MAJOR` BMP finding refuses the start with
    `ERR_OPEN_MAJOR_FINDING` (HTTP 409), and this check precedes the window
    checks".

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_start_harvest
    """
    # Contract ACTIVE with an open MAJOR finding; clock is INSIDE the harvest window.
    base = setup_contract_active(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    insp = get_success_data(api.create_inspection(
        create_inspection_payload(contract_id=base["contract"]["id"],
                                  inspection_type="PRE_HARVEST",
                                  scheduled_date="2026-05-25"),
        fh,
    ))
    get_success_data(api.conduct_inspection(insp["id"], INSPECTOR))
    get_success_data(api.close_inspection(
        insp["id"], {"outcome": "NONCOMPLIANT", "severity": "MAJOR",
                     "findings": "stream buffer flagged"}, INSPECTOR,
    ))
    # Clock inside both windows (2026-06-15).
    get_success_data(api.set_clock({"to_iso8601": "2026-06-15T00:00:00Z"}, ADMIN))
    resp = api.start_harvest(base["contract"]["id"], base["contractor_headers"])
    validate_error(resp, ApiErrorId.ERR_OPEN_MAJOR_FINDING)


def test_start_harvest_outside_season_window_rejected(api):
    """PRD §3.5: "when the clock's date lies within the sale's harvest window
    and within the prescription's window, both treated as half-open intervals
    (violation: `ERR_SEASON_WINDOW_VIOLATION`, HTTP 422)".

    Design: Corner/validations/start_harvest_outside_season_window_rejected
    """
    base = setup_contract_active(
        sale_overrides={"sale_type": "LUMP_SUM", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 7_000_000,
                        "species_minimum_rates": None},
        bid_overrides={"lump_sum_amount_cents": 8_000_000, "deposit_cents": 100_000},
    )
    # Clock before both windows open (windows start 2026-06-01).
    get_success_data(api.set_clock({"to_iso8601": "2026-05-25T00:00:00Z"}, ADMIN))
    resp = api.start_harvest(base["contract"]["id"], base["contractor_headers"])
    validate_error(resp, ApiErrorId.ERR_SEASON_WINDOW_VIOLATION)
    contract_now = get_success_data(api.get_contract(base["contract"]["id"], base["forester_headers"]))
    assert contract_now["status"] == "ACTIVE"


def test_bond_forfeiture_waterfall_conservation(api):
    """PRD §3.5: "An upheld claim moves the bond to `FORFEITED` and runs the
    forfeiture waterfall, which drains `amount_cents` through four buckets in
    a fixed order: first `admin_fee_cents` takes the smaller of 250,000 cents
    and the remaining balance; then `remediation_offset_cents` takes the
    smaller of the payload's `remediation_cost_cents` and what remains; then
    `shortfall_offset_cents` takes the smaller of the payload's
    `resale_shortfall_cents` and what remains; and everything left is
    `refunded_cents`, returned to the buyer. The four buckets always sum
    exactly to `amount_cents`."

    Design: Difficulty/compensating_invariant/bond_forfeiture_waterfall_conservation
    """
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    bond = base["bond"]
    # 945394 bond; declare default to auto-claim.
    get_success_data(api.declare_default(base["contract"]["id"],
                                         {"reason": "abandoned site"}, fh))
    adjudicated = validate_success(api.adjudicate_bond(
        bond["id"],
        {"decision": "UPHELD", "remediation_cost_cents": 300_000,
         "resale_shortfall_cents": 400_000},
        ADMIN,
    ))
    assert adjudicated["status"] == "FORFEITED"
    assert adjudicated["admin_fee_cents"] == 250_000
    assert adjudicated["remediation_offset_cents"] == 300_000
    assert adjudicated["shortfall_offset_cents"] == 395_394
    assert adjudicated["refunded_cents"] == 0
    # Conservation invariant.
    total = (adjudicated["admin_fee_cents"] + adjudicated["remediation_offset_cents"]
             + adjudicated["shortfall_offset_cents"] + adjudicated["refunded_cents"])
    assert total == adjudicated["amount_cents"] == 945_394


def test_bond_forfeiture_buckets_fill_in_order(api):
    """PRD §3.5: "first `admin_fee_cents` takes the smaller of 250,000 cents
    and the remaining balance; then `remediation_offset_cents` takes the
    smaller of the payload's `remediation_cost_cents` and what remains; then
    `shortfall_offset_cents` takes the smaller of the payload's
    `resale_shortfall_cents` and what remains; and everything left is
    `refunded_cents`, returned to the buyer."

    Design: Difficulty/compensating_invariant/bond_forfeiture_waterfall_conservation
    """
    base = setup_contract_harvesting(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE"},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    bond = base["bond"]
    get_success_data(api.declare_default(base["contract"]["id"], {}, fh))
    # Tiny offsets: remainder flows to refunded.
    adjudicated = validate_success(api.adjudicate_bond(
        bond["id"],
        {"decision": "UPHELD", "remediation_cost_cents": 10_000,
         "resale_shortfall_cents": 5_000},
        ADMIN,
    ))
    assert adjudicated["admin_fee_cents"] == 250_000
    assert adjudicated["remediation_offset_cents"] == 10_000
    assert adjudicated["shortfall_offset_cents"] == 5_000
    assert adjudicated["refunded_cents"] == 945_394 - 250_000 - 10_000 - 5_000
