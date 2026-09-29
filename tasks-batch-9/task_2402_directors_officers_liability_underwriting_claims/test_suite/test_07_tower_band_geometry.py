"""Subscribing the tower band by band.

A band is a half-open interval in money space. An exactly identical band is
co-participation, an adjacent band is disjoint, and anything in between is an
overlap — and the geometry rules answer before the money rules.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    UNDERWRITER,
    assert_layer,
    create_layer_payload,
    read_layers,
    read_policy,
    setup_bound_policy,
    subscribe_layer,
)

DIC_NOTES = "No prior-acts carve-back; narrower conduct wording than the primary form"


def _tower_up_to_the_programme_target():
    """A bound policy whose 0-10,000,000 primary is fully subscribed and whose
    10,000,000-20,000,000 band is co-subscribed 0.60 / 0.40 by two carriers."""
    scenario = setup_bound_policy()
    policy_id = scenario["policy"]["id"]
    scenario["primary_layer"] = subscribe_layer(
        policy_id, carrier_name="Meridian Primary", attachment_point_usd=0,
        limit_usd=10_000_000, participation_pct=1.00,
    )
    scenario["dic_layer"] = subscribe_layer(
        policy_id, carrier_name="Northgate Excess", attachment_point_usd=10_000_000,
        limit_usd=10_000_000, participation_pct=0.60,
        form_type="DIFFERENCE_IN_CONDITIONS", dic_deviation_notes=DIC_NOTES,
        underlying_layer_id=scenario["primary_layer"]["id"],
    )
    scenario["coparticipant"] = subscribe_layer(
        policy_id, carrier_name="Calder Re", attachment_point_usd=10_000_000,
        limit_usd=10_000_000, participation_pct=0.40,
        underlying_layer_id=scenario["primary_layer"]["id"],
    )
    scenario["policy"] = read_policy(policy_id)
    return scenario


def test_an_exactly_identical_band_is_admitted_as_quota_share_coparticipation(api):
    """PRD 3.5: "The new layer's band must either match an existing band of the
    policy exactly — which is how co-participation is expressed — or not overlap any
    existing band at all". "`placed_limit_usd` is the sum of `limit_usd` multiplied
    by `participation_pct` across that set, rounded half-up to 2 decimal places",
    and the bands "are contiguous when the set is non-empty, the lowest band
    attaches at 0, each successive band's attachment point equals the previous
    band's attachment point plus the previous band's limit, and every band's
    participations sum to exactly 1.00 compared at 2 decimal places."

    Design: Difficulty/resource_temporal_overlap/layer_band_overlap_versus_identical_band_coparticipation
    """
    scenario = setup_bound_policy()
    policy_id = scenario["policy"]["id"]

    primary = validate_success(
        api.create_layer(
            policy_id,
            create_layer_payload(carrier_name="Meridian Primary",
                                 attachment_point_usd=0, limit_usd=10_000_000,
                                 participation_pct=1.00),
            UNDERWRITER,
        ),
        201,
    )
    assert_layer(primary)
    assert primary["is_primary"] is True
    after_primary = read_policy(policy_id)
    assert after_primary["placed_limit_usd"] == pytest.approx(10_000_000, abs=0.01)
    assert after_primary["tower_posture"] == "CONTIGUOUS"

    # 10,000,000 x 0.60 == 6,000,000, inside 0.40 x 20,000,000 == 8,000,000.
    validate_success(
        api.create_layer(
            policy_id,
            create_layer_payload(
                carrier_name="Northgate Excess", attachment_point_usd=10_000_000,
                limit_usd=10_000_000, participation_pct=0.60,
                form_type="DIFFERENCE_IN_CONDITIONS", dic_deviation_notes=DIC_NOTES,
                underlying_layer_id=primary["id"],
            ),
            UNDERWRITER,
        ),
        201,
    )
    part_subscribed = read_policy(policy_id)
    assert part_subscribed["placed_limit_usd"] == pytest.approx(16_000_000, abs=0.01)
    assert part_subscribed["tower_posture"] == "INCOMPLETE", (
        "the second band's participations sum to 0.60, not 1.00"
    )

    # The identical band, admitted as co-participation rather than refused.
    validate_success(
        api.create_layer(
            policy_id,
            create_layer_payload(
                carrier_name="Calder Re", attachment_point_usd=10_000_000,
                limit_usd=10_000_000, participation_pct=0.40,
                underlying_layer_id=primary["id"],
            ),
            UNDERWRITER,
        ),
        201,
    )
    complete = read_policy(policy_id)
    assert complete["placed_limit_usd"] == pytest.approx(20_000_000, abs=0.01), (
        "exactly the programme target, and the fiscal comparison is inclusive"
    )
    assert complete["tower_posture"] == "CONTIGUOUS"


def test_a_partial_overlap_is_refused_before_any_money_rule_is_reached(api):
    """PRD 2.7: "On a layer subscription, band geometry is checked before money:
    overlap, then oversubscription, then the difference-in-conditions share, then
    primary-layer immutability, and only then whether the placed limit would breach
    the programme target." PRD 3.5: "the new band must start at or above the top of
    the existing band, or end at or below the existing band's attachment point; a
    partial overlap is refused with `ERR_LAYER_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/layer_band_overlap_versus_identical_band_coparticipation
    """
    scenario = _tower_up_to_the_programme_target()
    policy_id = scenario["policy"]["id"]

    # [12,000,000, 17,000,000) neither matches nor clears [10,000,000, 20,000,000),
    # and it would also breach the programme target — the geometry rule answers.
    validate_error(
        api.create_layer(
            policy_id,
            create_layer_payload(
                carrier_name="Ashford Straddle", attachment_point_usd=12_000_000,
                limit_usd=5_000_000, participation_pct=1.00,
                underlying_layer_id=scenario["dic_layer"]["id"],
            ),
            UNDERWRITER,
        ),
        ApiErrorId.ERR_LAYER_OVERLAP,
        409,
    )

    # An exact band match clears the overlap rule and dies on participation:
    # 0.60 + 0.40 + 0.20 == 1.20.
    validate_error(
        api.create_layer(
            policy_id,
            create_layer_payload(
                carrier_name="Ashford Oversubscribe", attachment_point_usd=10_000_000,
                limit_usd=10_000_000, participation_pct=0.20,
                underlying_layer_id=scenario["primary_layer"]["id"],
            ),
            UNDERWRITER,
        ),
        ApiErrorId.ERR_PARTICIPATION_OVERSUBSCRIBED,
        409,
    )

    # [20,000,000, 25,000,000) abuts with a gap of 0, so it is not an overlap and
    # the request reaches the fiscal rule: 20,000,000 + 5,000,000 > 20,000,000.
    validate_error(
        api.create_layer(
            policy_id,
            create_layer_payload(
                carrier_name="Ashford Top", attachment_point_usd=20_000_000,
                limit_usd=5_000_000, participation_pct=1.00,
                underlying_layer_id=scenario["dic_layer"]["id"],
            ),
            UNDERWRITER,
        ),
        ApiErrorId.ERR_TOWER_LIMIT_EXCEEDED,
        409,
    )

    layers, meta = validate_paginated(
        api.list_layers(UNDERWRITER, params={"policy_id": policy_id})
    )
    assert meta["total_count"] == 3, "no refused band was persisted"
    assert len(layers) == 3
    assert read_policy(policy_id)["placed_limit_usd"] == pytest.approx(
        20_000_000, abs=0.01
    )


def test_sealing_moves_the_adjacent_band_failure_further_up_the_ladder(api):
    """PRD 3.5: "A successful seal sets `tower_sealed` to true, re-derives
    `tower_posture` to `SEALED`, makes the layers immutable, and increments the
    policy's `version` by 1." Layers "may not be subscribed at all once the tower
    has been sealed, which is refused with `ERR_TOWER_ALREADY_SEALED`".

    Design: Difficulty/resource_temporal_overlap/layer_band_overlap_versus_identical_band_coparticipation
    """
    scenario = _tower_up_to_the_programme_target()
    policy_id = scenario["policy"]["id"]

    sealed = validate_success(api.seal_tower(policy_id, UNDERWRITER), 200)
    assert sealed["tower_sealed"] is True
    assert sealed["tower_posture"] == "SEALED", (
        "the SEALED rung outranks CONTIGUOUS in the precedence list"
    )

    # The same adjacent band that previously answered ERR_TOWER_LIMIT_EXCEEDED.
    validate_error(
        api.create_layer(
            policy_id,
            create_layer_payload(
                carrier_name="Latecomer Re", attachment_point_usd=20_000_000,
                limit_usd=5_000_000, participation_pct=1.00,
                underlying_layer_id=scenario["dic_layer"]["id"],
            ),
            UNDERWRITER,
        ),
        ApiErrorId.ERR_TOWER_ALREADY_SEALED,
        409,
    )
    assert len(read_layers(policy_id)) == 3
