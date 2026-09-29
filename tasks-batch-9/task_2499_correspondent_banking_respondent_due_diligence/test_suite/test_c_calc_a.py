"""Corner queue - section calculations, part A: jurisdiction points and ownership look-through."""
from test_helpers import (
    add_owner,
    new_jurisdiction,
    new_respondent,
    read_respondent,
    validate_success,
    verify_owner,
)
from test_helpers.fixtures import ADMIN, ANALYST, OFFICER


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def _respondent():
    _de()
    return new_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )


def test_jurisdiction_risk_points_sums_all_four_components(api):
    """All four addends are non-zero at once and their sum still sits below the cap, so the
    stored figure is the plain sum of the basel term, the sanctions tier, the listing and secrecy.

    Design: Corner/calculations/jurisdiction_risk_points_sums_all_four_components
    """
    created = validate_success(
        api.create_jurisdiction_profile(
            {
                "jurisdiction_code": "KY",
                "name": "Cayman Islands",
                "basel_aml_index": 6.5,
                "corridor_risk_weight": 1.75,
                "sanctions_status": "RESTRICTED",
                "fatf_listing": "CALL_FOR_ACTION",
                "secrecy_flag": True,
            },
            OFFICER,
        ),
        expected_status=201,
    )

    assert created["jurisdiction_risk_points"] == 36.00


def test_jurisdiction_risk_points_clamped_at_points_cap(api):
    """The raw sum of 55.00 is well past the ceiling, so the cap has to be applied to the
    stored value rather than the raw arithmetic being kept.

    Design: Corner/calculations/jurisdiction_risk_points_clamped_at_points_cap
    """
    created = validate_success(
        api.create_jurisdiction_profile(
            {
                "jurisdiction_code": "IR",
                "name": "Iran",
                "basel_aml_index": 10.0,
                "corridor_risk_weight": 2.5,
                "sanctions_status": "COMPREHENSIVELY_SANCTIONED",
                "fatf_listing": "CALL_FOR_ACTION",
                "secrecy_flag": True,
            },
            OFFICER,
        ),
        expected_status=201,
    )

    assert created["jurisdiction_risk_points"] == 40.00


def test_jurisdiction_risk_points_recomputed_on_basel_patch(api):
    """The amendment recomputes from the post-amendment values, so raising the basel index
    rewrites the derived points inside the same response and moves the version on.

    Design: Corner/calculations/jurisdiction_risk_points_recomputed_on_basel_patch
    """
    profile = _de()
    assert profile["jurisdiction_risk_points"] == 8.00

    amended = validate_success(
        api.amend_jurisdiction_profile(profile["id"], {"basel_aml_index": 7.25}, ADMIN)
    )

    assert amended["jurisdiction_risk_points"] == 14.50
    assert amended["version"] == 2


def test_effective_ownership_pct_two_level_look_through_rounds_once(api):
    """The chain product is divided once and rounded once, so the exact quotient 22.221111
    becomes 22.22 while the direct parent keeps its own undivided stake.

    Design: Corner/calculations/effective_ownership_pct_two_level_look_through_rounds_once
    """
    rid = _respondent()["id"]
    root = add_owner(
        rid, "DE", owner_name="Holdco GmbH", owner_type="LEGAL_ENTITY", ownership_pct=66.67
    )

    child = validate_success(
        api.create_beneficial_owner(
            rid,
            {"owner_name": "Klara Vogt", "owner_type": "NATURAL_PERSON",
             "ownership_pct": 33.33, "country_of_residence": "DE",
             "parent_owner_id": root["id"]},
            ANALYST,
        ),
        expected_status=201,
    )

    assert child["chain_depth"] == 2
    assert child["ownership_pct"] == 33.33
    assert child["effective_ownership_pct"] == 22.22
    assert validate_success(
        api.get_beneficial_owner(root["id"], ANALYST)
    )["effective_ownership_pct"] == 66.67


def test_effective_ownership_pct_accepted_at_max_chain_depth_four(api):
    """Four nodes is the last legal depth, and three full pass-throughs leave the fourth
    node's own stake intact after the single division.

    Design: Corner/calculations/effective_ownership_pct_accepted_at_max_chain_depth_four
    """
    rid = _respondent()["id"]
    level1 = add_owner(
        rid, "DE", owner_name="L1 Holding", owner_type="LEGAL_ENTITY", ownership_pct=100.00
    )
    level2 = add_owner(
        rid, "DE", owner_name="L2 Holding", owner_type="LEGAL_ENTITY", ownership_pct=100.00,
        parent_owner_id=level1["id"],
    )
    level3 = add_owner(
        rid, "DE", owner_name="L3 Holding", owner_type="LEGAL_ENTITY", ownership_pct=100.00,
        parent_owner_id=level2["id"],
    )

    level4 = validate_success(
        api.create_beneficial_owner(
            rid,
            {"owner_name": "Ida Brandt", "owner_type": "NATURAL_PERSON",
             "ownership_pct": 50.00, "country_of_residence": "DE",
             "parent_owner_id": level3["id"]},
            ANALYST,
        ),
        expected_status=201,
    )

    assert level4["chain_depth"] == 4
    assert level4["effective_ownership_pct"] == 50.00


def test_ownership_rollup_verifies_at_exactly_seventy_five_percent(api):
    """The threshold comparison is inclusive, so two direct stakes summing to exactly the
    boundary are enough to flip the respondent's ownership flag.

    Design: Corner/calculations/ownership_rollup_verifies_at_exactly_seventy_five_percent
    """
    rid = _respondent()["id"]
    first = add_owner(rid, "DE", owner_name="Anna Weber", ownership_pct=40.00)
    second = add_owner(rid, "DE", owner_name="Bernd Klein", ownership_pct=35.00)
    verify_owner(first["id"])
    assert read_respondent(rid)["ownership_verified"] is False

    validate_success(api.verify_owner(second["id"], {"action": "VERIFY"}, ANALYST))

    respondent = read_respondent(rid)
    assert respondent["verified_ownership_pct"] == 75.00
    assert respondent["ownership_verified"] is True
