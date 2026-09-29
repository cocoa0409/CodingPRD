"""Carbon-intensity certification variants and the power-contract changeover buffer."""

import pytest
from test_helpers import (
    ENGINEER,
    CANONICAL_CONTRACT,
    CANONICAL_LOT_CI_ANNUAL,
    CANONICAL_LOT_CI_HOURLY,
    api_client,
    certify_lot_ci,
    create_production_asset,
    list_meta,
    list_rows,
    power_supply_contract_payload,
    read_lot,
    set_clock,
    setup_canonical_produced_lot,
    validate_error,
    validate_success,
)

# ─── Recipe builders ──────────────────────────────────────────────────────


def _hourly_matched_lot():
    """The recurring lot under a contract that has opted into hourly matching."""
    set_clock("2026-08-01T00:00:00Z")
    return setup_canonical_produced_lot(
        contract_overrides={"hourly_matching_enabled": True}
    )


def _asset_with_incumbent_contract():
    """One asset whose incumbent contract occupies 2026-01-01 to 2026-06-01."""
    set_clock("2026-08-01T00:00:00Z")
    asset = create_production_asset(
        pathway="PEM_ELECTROLYSIS",
        nameplate_kg_per_day=1200.000,
        ccs_capture_rate=0.0000,
        operator_org="Harbor H2 Production",
    )
    incumbent = validate_success(
        api_client.create_power_supply_contract(
            asset["id"],
            power_supply_contract_payload(
                asset["id"],
                **{**CANONICAL_CONTRACT, "effective_to": "2026-06-01T00:00:00Z"},
            ),
            ENGINEER,
        ),
        expected_status=201,
    )
    return asset, incumbent


def _successor_payload(asset_id, effective_from):
    return power_supply_contract_payload(
        asset_id,
        grid_ci_gco2e_per_mwh=300000.00,
        annual_renewable_pct=70.000,
        hourly_matched_renewable_pct=50.000,
        hourly_matching_enabled=True,
        effective_from=effective_from,
        effective_to="2026-12-01T00:00:00Z",
    )


# ─── Carbon-intensity variants ────────────────────────────────────────────


def test_certified_intensity_uses_hourly_matched_while_provisional_stays_annual():
    """The two carbon-intensity figures on one lot diverge by their renewable share.

    "`HOURLY_MATCHED` applies when the selected contract's `hourly_matching_enabled`
    is true, and only when the certified figure is being stamped; it uses
    `hourly_matched_renewable_pct` instead, crediting only renewable generation
    matched hour by hour."  Meanwhile "the server stamps
    `ci_provisional_gco2e_per_mj`, the provisional carbon intensity, using the
    `ANNUAL_AVERAGE` variant unconditionally — regardless of whether the selected
    contract has hourly matching enabled."

    Design: Difficulty/dual_variant_calc/lot_carbon_intensity_annual_average_versus_hourly_matched
    """
    scenario = _hourly_matched_lot()
    lot = scenario["lot"]

    assert lot["selected_power_contract_id"] == scenario["contract"]["id"]
    assert lot["ci_provisional_gco2e_per_mj"] == pytest.approx(
        CANONICAL_LOT_CI_ANNUAL, abs=0.01
    ), "the provisional figure credits the 62.500 % annual-average renewable share"
    assert lot["ci_certified_gco2e_per_mj"] is None

    certified = certify_lot_ci(lot["id"])

    assert certified["ci_variant_applied"] == "HOURLY_MATCHED"
    assert certified["ci_certified_gco2e_per_mj"] == pytest.approx(
        CANONICAL_LOT_CI_HOURLY, abs=0.01
    ), "the certified figure credits only the 41.000 % hourly-matched share"
    assert certified["ci_provisional_gco2e_per_mj"] == pytest.approx(
        CANONICAL_LOT_CI_ANNUAL, abs=0.01
    ), "certification never rewrites the provisional figure"
    assert round(
        certified["ci_certified_gco2e_per_mj"] - certified["ci_provisional_gco2e_per_mj"], 2
    ) == pytest.approx(35.87, abs=0.01), (
        "hourly matching is strictly dirtier when the matched share is the smaller one"
    )


def test_certifying_carbon_intensity_advances_only_the_carbon_branch():
    """Certification moves `ci_status` and leaves the lot's own status alone.

    "The lot's own `status` is untouched: this is progress along one branch of a
    two-branch lifecycle, not a lifecycle transition, so the lot remains
    `PRODUCED` throughout."

    Design: Difficulty/dual_variant_calc/lot_carbon_intensity_annual_average_versus_hourly_matched
    """
    scenario = _hourly_matched_lot()
    lot = scenario["lot"]
    assert lot["ci_status"] == "PENDING"
    assert lot["status"] == "PRODUCED"

    certified = certify_lot_ci(lot["id"])

    assert certified["ci_status"] == "CERTIFIED"
    assert certified["status"] == "PRODUCED"
    assert certified["qa_status"] == "PENDING", "the quality branch advances separately"
    assert certified["version"] > lot["version"]

    reread = read_lot(lot["id"])
    assert reread["ci_status"] == "CERTIFIED"
    assert reread["status"] == "PRODUCED"
    assert reread["selected_power_contract_id"] == scenario["contract"]["id"]


# ─── Power-contract changeover buffer ─────────────────────────────────────


def test_back_to_back_power_contract_falls_inside_the_changeover_buffer():
    """A successor starting the instant the incumbent ends is refused.

    "The practical consequence is that back-to-back contracts still conflict: an
    interval that begins the instant its predecessor ends is inside the buffer,
    and only a separation of at least twenty-four hours clears it."

    Design: Difficulty/resource_temporal_overlap/power_supply_contract_exclusive_with_24_hour_changeover_buffer
    """
    asset, incumbent = _asset_with_incumbent_contract()

    response = api_client.create_power_supply_contract(
        asset["id"], _successor_payload(asset["id"], "2026-06-01T00:00:00Z"), ENGINEER
    )

    validate_error(response, "ERR_POWER_CONTRACT_OVERLAP", expected_status=409)

    listing = api_client.list_power_supply_contracts(
        asset["id"], ENGINEER, params={"limit": 100, "offset": 0}
    )
    rows = list_rows(listing)
    assert list_meta(listing)["total_count"] == 1, "the refused booking created no row"
    assert [row["id"] for row in rows] == [incumbent["id"]]


def test_power_contract_a_full_day_past_the_incumbent_is_admitted():
    """A separation of a full twenty-four hours clears the buffer.

    "Contracts on one asset must not merely avoid overlapping — they must be
    separated by a changeover buffer of a full day, twenty-four hours."  A start
    at 2026-06-02T00:00:00Z is not strictly earlier than the incumbent's
    `effective_to` advanced by twenty-four hours, so no conflict exists.

    Design: Difficulty/resource_temporal_overlap/power_supply_contract_exclusive_with_24_hour_changeover_buffer
    """
    asset, incumbent = _asset_with_incumbent_contract()
    validate_error(
        api_client.create_power_supply_contract(
            asset["id"], _successor_payload(asset["id"], "2026-06-01T00:00:00Z"), ENGINEER
        ),
        "ERR_POWER_CONTRACT_OVERLAP",
        expected_status=409,
    )

    accepted = validate_success(
        api_client.create_power_supply_contract(
            asset["id"], _successor_payload(asset["id"], "2026-06-02T00:00:00Z"), ENGINEER
        ),
        expected_status=201,
    )

    assert accepted["effective_from"].startswith("2026-06-02T00:00:00")
    assert accepted["hourly_matching_enabled"] is True

    listing = api_client.list_power_supply_contracts(
        asset["id"], ENGINEER, params={"limit": 100, "offset": 0}
    )
    rows = list_rows(listing)
    assert list_meta(listing)["total_count"] == 2
    assert {row["id"] for row in rows} == {incumbent["id"], accepted["id"]}
    survivor = next(row for row in rows if row["id"] == incumbent["id"])
    assert survivor["effective_to"].startswith("2026-06-01T00:00:00"), (
        "the incumbent interval is never truncated to make room"
    )
