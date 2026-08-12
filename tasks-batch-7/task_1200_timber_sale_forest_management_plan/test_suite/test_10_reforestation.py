"""Reforestation obligations, survival surveys, delinquency (PRD §3.8)."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_record_planting_payload,
    create_survey_payload,
    setup_contract_harvest_complete,
    setup_obligation_planted,
    setup_per_unit_settlement_draft,
    setup_survey_recorded,
)

ADMIN = TEST_USERS["admin_headers"]


def test_survival_exactly_85_passes(api):
    """PRD §3.8: "the `result` is `PASS` when the rounded percentage is at
    least 85.00 — a survival of exactly 85.00 passes — and `FAIL` below it."

    Design: Corner/calculations/survival_exactly_85_passes
    """
    base = setup_survey_recorded(live_seedlings_count=850,
                                 sale_overrides={"sale_type": "LUMP_SUM",
                                                 "scaling_rule": "DOYLE",
                                                 "advertised_minimum_cents": 7_000_000,
                                                 "species_minimum_rates": None},
                                 bid_overrides={"lump_sum_amount_cents": 8_000_000,
                                                "deposit_cents": 100_000})
    fh = base["forester_headers"]
    survey = validate_success(api.finalize_survey(base["survey"]["id"], fh))
    assert survey["survival_pct"] == 85.00
    assert survey["result"] == "PASS"
    obligation = get_success_data(api.get_obligation(base["obligation"]["id"], fh))
    assert obligation["status"] == "SATISFIED"


def test_survival_fail_replant_bond_hold_chain(api):
    """PRD §3.8: "A fail moves it `SURVEYED → REPLANT_REQUIRED`, resets
    `plant_by_date` to the `survey_date` plus another 365 days, and reaches
    across to the performance bond: `reforestation_hold_cents` is recomputed
    upward as the smaller of the bond's `amount_cents` and the stand's `acres`
    multiplied by 45,000 cents per acre — up from the 35,000-per-acre figure
    used at posting — incrementing the bond's `version` alongside the
    obligation's."

    Design: Difficulty/transitive_cascade/survival_fail_replant_bond_hold_chain
    """
    # LUMP_SUM contract awarded at 40000000 -> bond tier 2 (7%) = 2800000; 50 acres.
    base = setup_survey_recorded(
        live_seedlings_count=800,
        sale_overrides={"sale_type": "LUMP_SUM", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 30_000_000,
                        "species_minimum_rates": None},
        bid_overrides={"lump_sum_amount_cents": 40_000_000, "deposit_cents": 500_000},
    )
    fh = base["forester_headers"]
    bond = base["bond"]
    # Initial hold = min(2800000, 50*35000) = 1750000.
    assert bond["reforestation_hold_cents"] == 1_750_000

    survey = validate_success(api.finalize_survey(base["survey"]["id"], fh))
    assert survey["survival_pct"] == 80.00
    assert survey["result"] == "FAIL"
    obligation = get_success_data(api.get_obligation(base["obligation"]["id"], fh))
    assert obligation["status"] == "REPLANT_REQUIRED"
    assert obligation["plant_by_date"] == "2029-04-01"
    # Bond hold recomputed upward: min(2800000, 50*45000) = 2250000.
    bond_after = get_success_data(api.get_bond(bond["id"], fh))
    assert bond_after["reforestation_hold_cents"] == 2_250_000


def test_survival_fail_moves_obligation_to_replant_required(api):
    """PRD §3.8: "A fail moves it `SURVEYED → REPLANT_REQUIRED`, resets
    `plant_by_date` to the `survey_date` plus another 365 days".

    Design: Difficulty/transitive_cascade/survival_fail_replant_bond_hold_chain
    """
    base = setup_survey_recorded(
        live_seedlings_count=700,
        sale_overrides={"sale_type": "LUMP_SUM", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 7_000_000,
                        "species_minimum_rates": None},
        bid_overrides={"lump_sum_amount_cents": 8_000_000, "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    survey = validate_success(api.finalize_survey(base["survey"]["id"], fh))
    assert survey["survival_pct"] == 70.00
    assert survey["result"] == "FAIL"
    obligation = get_success_data(api.get_obligation(base["obligation"]["id"], fh))
    assert obligation["status"] == "REPLANT_REQUIRED"
    # plant_by_date = survey_date 2028-04-01 + 365 days = 2029-04-01.
    assert obligation["plant_by_date"] == "2029-04-01"


def test_survey_void_returns_obligation_to_planted(api):
    """PRD §3.8: "A survey recorded in error can be voided while still
    `RECORDED`, which returns the obligation from `SURVEYED` to `PLANTED` so
    a corrected survey can be taken".

    Design: Corner/state_machines/survey_void_returns_obligation_to_planted
    """
    base = setup_survey_recorded(
        live_seedlings_count=900,
        sale_overrides={"sale_type": "LUMP_SUM", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 7_000_000,
                        "species_minimum_rates": None},
        bid_overrides={"lump_sum_amount_cents": 8_000_000, "deposit_cents": 100_000},
    )
    fh = base["forester_headers"]
    voided = validate_success(api.void_survey(base["survey"]["id"], fh))
    assert voided["status"] == "VOID"
    obligation = get_success_data(api.get_obligation(base["obligation"]["id"], fh))
    assert obligation["status"] == "PLANTED"


def test_planting_after_deadline_rejected(api):
    """PRD §3.8: "Planting after the deadline is refused: the clock's date
    must fall on or before `plant_by_date`, else
    `ERR_PLANTING_DEADLINE_PASSED` (HTTP 422)."

    Design: Corner/validations/planting_after_deadline_rejected
    """
    base = setup_contract_harvest_complete(
        sale_overrides={"sale_type": "LUMP_SUM", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 7_000_000,
                        "species_minimum_rates": None},
        bid_overrides={"lump_sum_amount_cents": 8_000_000, "deposit_cents": 100_000},
        clock_iso="2026-08-01T00:00:00Z",
    )
    obligation = base["obligation"]
    assert obligation["plant_by_date"] == "2027-08-01"
    # Advance clock past plant_by_date.
    get_success_data(api.set_clock({"to_iso8601": "2027-08-02T00:00:00Z"}, ADMIN))
    resp = api.record_planting(
        obligation["id"],
        create_record_planting_payload(planted_date="2027-08-02", seedlings_planted=1000),
        base["contractor_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PLANTING_DEADLINE_PASSED)


def test_survey_before_one_growing_season_rejected(api):
    """PRD §3.8: "the survey date must fall at least 365 days after the most
    recent `planted_date` — an earlier survey is `ERR_SURVEY_TOO_EARLY`
    (HTTP 422)."

    Design: Corner/validations/survey_before_one_growing_season_rejected
    """
    base = setup_obligation_planted(
        sale_overrides={"sale_type": "LUMP_SUM", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 7_000_000,
                        "species_minimum_rates": None},
        bid_overrides={"lump_sum_amount_cents": 8_000_000, "deposit_cents": 100_000},
    )
    # Survey only 92 days after planting (< 365).
    get_success_data(api.set_clock({"to_iso8601": "2027-06-01T00:00:00Z"}, ADMIN))
    resp = api.create_survey(
        base["obligation"]["id"],
        create_survey_payload(survey_date="2027-06-01", live_seedlings_count=900),
        base["forester_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SURVEY_TOO_EARLY)


def test_bond_release_blocked_until_obligation_satisfied(api):
    """PRD §3.5: "release requires the bond `POSTED`, the contract in
    `HARVEST_COMPLETE` or `CLOSED`, and the reforestation obligation
    `SATISFIED` — an outstanding obligation refuses the release with
    `ERR_BOND_HOLD_OUTSTANDING` (HTTP 409)".

    Design: Corner/validations/bond_release_blocked_until_obligation_satisfied
    """
    base = setup_contract_harvest_complete(
        sale_overrides={"sale_type": "LUMP_SUM", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 7_000_000,
                        "species_minimum_rates": None},
        bid_overrides={"lump_sum_amount_cents": 8_000_000, "deposit_cents": 100_000},
        clock_iso="2026-08-01T00:00:00Z",
    )
    fh = base["forester_headers"]
    bond = base["bond"]
    resp = api.release_bond(bond["id"], fh)
    validate_error(resp, ApiErrorId.ERR_BOND_HOLD_OUTSTANDING)
    bond_now = get_success_data(api.get_bond(bond["id"], fh))
    assert bond_now["status"] == "POSTED"


def test_release_holdback_before_satisfaction_rejected(api):
    """PRD §3.5: "the release is refused with `ERR_REFORESTATION_UNSATISFIED`
    (HTTP 409) while the obligation is not `SATISFIED`".

    Design: Corner/validations/release_holdback_before_satisfaction_rejected
    """
    # Contract HARVESTING with one DRAFT settlement carrying holdback; no obligation exists yet.
    base = setup_per_unit_settlement_draft(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 10_000_000},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
        ticket_specs=[{"scaled_date": "2026-06-16", "log_count": 1}],
        period_start="2026-06-01", period_end="2026-07-01",
    )
    fh = base["forester_headers"]
    # Settlement gross 4500, holdback 450.
    assert base["settlement"]["holdback_cents"] == 450
    resp = api.release_holdback(base["contract"]["id"], fh)
    validate_error(resp, ApiErrorId.ERR_REFORESTATION_UNSATISFIED)
    contract = get_success_data(api.get_contract(base["contract"]["id"], fh))
    assert contract["holdback_balance_cents"] == 450


def test_contract_close_blocked_by_unpaid_settlement(api):
    """PRD §3.5: "Final close moves `HARVEST_COMPLETE → CLOSED` behind three
    gates evaluated in order: no bond hold outstanding
    (`ERR_BOND_HOLD_OUTSTANDING`), every settlement of the contract in `PAID`,
    `REFUNDED`, or `VOID` (`ERR_UNPAID_SETTLEMENTS`, HTTP 409), and the
    reforestation obligation `SATISFIED` (`ERR_REFORESTATION_UNSATISFIED`)."

    Design: Corner/validations/contract_close_blocked_by_unpaid_settlement
    """
    # Drive through: HARVEST_COMPLETE with obligation SATISFIED + bond RELEASED
    # + one APPROVED-unpaid settlement.
    base = setup_per_unit_settlement_draft(
        sale_overrides={"sale_type": "PER_UNIT", "scaling_rule": "DOYLE",
                        "advertised_minimum_cents": 10_000_000},
        bid_overrides={"species_rates": [{"species": "PINE", "rate_cents_per_mbf": 45_000}],
                       "deposit_cents": 100_000},
        ticket_specs=[{"scaled_date": "2026-06-16", "log_count": 1}],
        period_start="2026-06-01", period_end="2026-07-01",
    )
    fh = base["forester_headers"]
    lh = base["landowner_headers"]
    ch = base["contractor_headers"]
    settlement = base["settlement"]
    # Approve (but do not disburse) the settlement.
    get_success_data(api.approve_settlement(settlement["id"], lh))
    # Drive to HARVEST_COMPLETE.
    get_success_data(api.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, ADMIN))
    get_success_data(api.complete_harvest(base["contract"]["id"], ch))
    # Get obligation, plant, survey to SATISFIED.
    obligations = get_success_data(api.list_obligations(fh, params={"contract_id": base["contract"]["id"]}))
    obligation = obligations[0]
    get_success_data(api.set_clock({"to_iso8601": "2027-03-01T00:00:00Z"}, ADMIN))
    get_success_data(api.record_planting(
        obligation["id"],
        create_record_planting_payload(planted_date="2027-03-01", seedlings_planted=1000),
        ch,
    ))
    get_success_data(api.set_clock({"to_iso8601": "2028-04-01T00:00:00Z"}, ADMIN))
    survey = get_success_data(api.create_survey(
        obligation["id"],
        create_survey_payload(survey_date="2028-04-01", live_seedlings_count=900),
        fh,
    ))
    get_success_data(api.finalize_survey(survey["id"], fh))
    # Release holdback then bond.
    get_success_data(api.release_holdback(base["contract"]["id"], fh))
    get_success_data(api.release_bond(base["bond"]["id"], fh))
    # Now close should fail with ERR_UNPAID_SETTLEMENTS.
    resp = api.close_contract(base["contract"]["id"], fh)
    validate_error(resp, ApiErrorId.ERR_UNPAID_SETTLEMENTS)
    contract_now = get_success_data(api.get_contract(base["contract"]["id"], fh))
    assert contract_now["status"] == "HARVEST_COMPLETE"
