"""Whole-flock condemned-loss declaration and its threshold (PRD §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_contract_payload,
    create_grower_payload,
    create_house_payload,
    create_settlement_group_payload,
    get_success_data,
    plan_flock,
    place_flock,
    record_feed,
    record_mortality,
    set_logical_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def _setup_boundary_pair(api):
    """Two GROWING flocks of 1000 head each: flock1 at condemnation_pct exactly
    0.30 (300 condemned), flock2 at 0.301 (301 condemned). Logical clock stays
    at the 2026-08-01 startup setting."""
    set_logical_clock("2026-08-01T00:00:00Z")
    grower = get_success_data(
        api.create_grower(create_grower_payload(grower_code="G-B1",
                                                full_name="Boundary Grower"),
                          ADMIN))
    house1 = get_success_data(
        api.create_house(create_house_payload(grower["id"], house_no="H1",
                                              capacity_birds=5000), ADMIN))
    house2 = get_success_data(
        api.create_house(create_house_payload(grower["id"], house_no="H2",
                                              capacity_birds=5000), ADMIN))
    contract = get_success_data(
        api.create_contract(
            create_contract_payload(grower["id"], contract_no="C-B1",
                                    committed_house_count=2), ADMIN))
    get_success_data(api.activate_contract(contract["id"], ADMIN))
    group = get_success_data(
        api.create_settlement_group(
            create_settlement_group_payload(group_code="WK-41",
                                            week_ending_date="2026-11-14"),
            ANALYST))
    flock1 = plan_flock(house1["id"], contract["id"], group["id"], "F-B30")
    flock2 = plan_flock(house2["id"], contract["id"], group["id"], "F-B301")
    place_flock(flock1["id"], "2026-08-01", 1000)
    place_flock(flock2["id"], "2026-08-01", 1000)
    record_feed(flock1["id"], 1000, "2026-08-05", "STARTER", "FT-B30")
    record_feed(flock2["id"], 1000, "2026-08-05", "STARTER", "FT-B301")
    record_mortality(flock1["id"], grower["id"], 0, 300, "2026-08-20")
    record_mortality(flock2["id"], grower["id"], 0, 301, "2026-08-20")
    return grower, house1, house2, flock1, flock2


class TestCondemnationLossThresholdStrictlyGreater:
    def test_exactly_at_threshold_rejected(self, api, admin_headers):
        """PRD §3.6: "The declaration requires the flock's `condemnation_pct`
        to exceed the whole-flock loss threshold of 0.30 — that is, more than
        30 percent of the surviving placed birds condemned; a flock at or below
        the threshold is rejected with `ERR_CONDEMNATION_BELOW_THRESHOLD`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/condemnation_loss_threshold_strictly_greater
        """
        _g, _h1, _h2, flock1, _f2 = _setup_boundary_pair(api)
        placed = validate_success(api.get_flock(flock1["id"], ADMIN))
        # 300 condemned / max(1, 1000 - 0) survivors = 0.30 exactly.
        assert placed["condemnation_pct"] == pytest.approx(0.30, abs=1e-9)

        resp = api.declare_condemned_loss(flock1["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_CONDEMNATION_BELOW_THRESHOLD)

        after = validate_success(api.get_flock(flock1["id"], ADMIN))
        assert after["status"] == "GROWING", \
            "a flock at the threshold must not be written off"

    def test_one_bird_over_threshold_succeeds_and_rests_house(
            self, api, admin_headers):
        """PRD §3.6: "On declaration the flock moves `GROWING` →
        `CONDEMNED_LOSS`, no settlement row is ever created for it, and its
        house is pushed into `DOWNTIME` with `downtime_until` set to the
        current logical date plus 21 days — three weeks of rest after a
        catastrophic health event."

        Design: Difficulty/boundary_precision_check/condemnation_loss_threshold_strictly_greater
        """
        _g, _h1, house2, _f1, flock2 = _setup_boundary_pair(api)
        placed = validate_success(api.get_flock(flock2["id"], ADMIN))
        assert placed["condemnation_pct"] == pytest.approx(0.301, abs=1e-9)

        declared = validate_success(
            api.declare_condemned_loss(flock2["id"], admin_headers))
        assert declared["status"] == "CONDEMNED_LOSS"

        flock = validate_success(api.get_flock(flock2["id"], ADMIN))
        assert flock["status"] == "CONDEMNED_LOSS"

        house = validate_success(api.get_house(house2["id"], ADMIN))
        assert house["house_status"] == "DOWNTIME"
        # Logical clock is still 2026-08-01 -> +21 days.
        assert house["downtime_until"] == "2026-08-22"
