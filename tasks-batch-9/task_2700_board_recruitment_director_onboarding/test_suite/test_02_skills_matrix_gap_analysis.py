"""The skills matrix gap analysis and its two rating variants."""
from test_helpers import fixtures as X
from test_helpers.assertions import assert_fields_equal, assert_gap_row
from test_helpers.test_users import make_committee_chair_headers


def _board_with_cyber_ratings(client):
    """Two categories, three seated directors, one validated-down and one raw rating."""
    X.adopt_policy(client)
    capital = X.new_skill_category(
        client,
        code="CAPITAL_ALLOCATION",
        name="Capital Allocation",
        strategic_weight=0.6,
        required_min_directors=2,
        risk_oversight=False,
        criticality="STRATEGIC",
    )
    cyber = X.new_skill_category(
        client,
        code="CYBER_RISK",
        name="Cybersecurity Risk Oversight",
        strategic_weight=0.8,
        required_min_directors=2,
        risk_oversight=True,
        criticality="CORE",
    )
    chair = X.new_seated_director(
        client, full_name="Dana Chair", email="dana.chair@issuer.example",
        birth_date="1962-03-15", appointed_on="2019-05-01",
    )
    chair_headers = make_committee_chair_headers(chair["id"])
    d1 = X.new_seated_director(
        client, full_name="Dir One", email="d1@issuer.example",
        birth_date="1968-01-10", appointed_on="2021-05-01",
    )
    d2 = X.new_seated_director(
        client, full_name="Dir Two", email="d2@issuer.example",
        birth_date="1970-09-22", appointed_on="2022-05-01",
    )
    rating_d1 = X.record_rating(client, d1["id"], cyber["id"], 4)
    X.validate_rating(client, rating_d1["id"], 2, chair_headers)
    rating_d2 = X.record_rating(client, d2["id"], cyber["id"], 3)
    return {
        "capital": capital,
        "cyber": cyber,
        "rating_d1": rating_d1,
        "rating_d2": rating_d2,
    }


def test_self_reported_variant_reads_raw_self_ratings_and_covers_cyber_risk(client):
    """Under SELF_REPORTED both cyber ratings count at their self_rating, so cyber is
    covered and the only weighted gap left is CAPITAL_ALLOCATION at 1.20.

    PRD: "the rating used under `SELF_REPORTED` is that pair's `self_rating`, regardless of `validation_status`; under `VALIDATED_ONLY` it is the `validated_rating` when the row is `VALIDATED` and zero otherwise."

    Design: Difficulty/dual_variant_calc/skills_gap_self_reported_vs_validated_only_flip_priority_category
    """
    _board_with_cyber_ratings(client)

    analysis = X.get_gap_analysis(client, variant="SELF_REPORTED")

    assert_fields_equal(
        analysis,
        {
            "variant": "SELF_REPORTED",
            "seated_director_count": 3,
            "category_count": 2,
            "board_gap_index": 1.20,
            "priority_category_code": "CAPITAL_ALLOCATION",
        },
    )
    assert_gap_row(analysis, "CYBER_RISK", 2, 0, 0.00, "COVERED")
    assert_gap_row(analysis, "CAPITAL_ALLOCATION", 0, 2, 1.20, "CRITICAL_GAP")


def test_validated_only_variant_zeroes_the_unvalidated_row_and_flips_the_priority(client):
    """Under VALIDATED_ONLY the unvalidated row scores zero and the validated row reads 2,
    so cyber becomes a critical gap at 2.40 and takes the priority slot.

    PRD: "The `priority_category_code` is the `code` of the single most pressing category, chosen by sorting categories on `weighted_gap` descending, then on criticality rank ascending"

    Design: Difficulty/dual_variant_calc/skills_gap_self_reported_vs_validated_only_flip_priority_category
    """
    _board_with_cyber_ratings(client)

    analysis = X.get_gap_analysis(client, variant="VALIDATED_ONLY")

    assert_fields_equal(
        analysis,
        {
            "variant": "VALIDATED_ONLY",
            "seated_director_count": 3,
            "category_count": 2,
            "board_gap_index": 3.60,
            "priority_category_code": "CYBER_RISK",
        },
    )
    assert_gap_row(analysis, "CYBER_RISK", 0, 2, 2.40, "CRITICAL_GAP")
    assert_gap_row(analysis, "CAPITAL_ALLOCATION", 0, 2, 1.20, "CRITICAL_GAP")


def test_the_risk_oversight_multiplier_only_shows_up_once_the_gap_is_non_zero(client):
    """The 1.5 risk multiplier is what makes the cyber weighted gap 2.40 rather than 1.60,
    and it is invisible while the same category is covered.

    PRD: "The `weighted_gap` is the `gap` multiplied by the category's `strategic_weight` multiplied by that risk multiplier, rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/skills_gap_self_reported_vs_validated_only_flip_priority_category
    """
    _board_with_cyber_ratings(client)

    self_reported = X.get_gap_analysis(client, variant="SELF_REPORTED")
    validated_only = X.get_gap_analysis(client, variant="VALIDATED_ONLY")

    assert_gap_row(self_reported, "CYBER_RISK", 2, 0, 0.00, "COVERED")
    assert_gap_row(validated_only, "CYBER_RISK", 0, 2, 2.40, "CRITICAL_GAP")
    assert self_reported["board_gap_index"] == 1.20
    assert validated_only["board_gap_index"] == 3.60


def test_categories_come_back_in_ascending_code_order_under_both_variants(client):
    """The categories array is ordered by code, so CAPITAL_ALLOCATION precedes CYBER_RISK
    whichever variant was asked for.

    PRD: "Categories are then processed in ascending `code` order, and for each one the analysis produces five figures."

    Design: Difficulty/dual_variant_calc/skills_gap_self_reported_vs_validated_only_flip_priority_category
    """
    _board_with_cyber_ratings(client)

    for variant in ("SELF_REPORTED", "VALIDATED_ONLY"):
        analysis = X.get_gap_analysis(client, variant=variant)
        codes = [row["code"] for row in analysis["categories"]]
        assert codes == ["CAPITAL_ALLOCATION", "CYBER_RISK"], (variant, codes)


def test_validation_replaces_the_effective_rating_but_leaves_the_other_row_alone(client):
    """Validating one rating flips only that row to VALIDATED with effective_rating 2; the
    untouched row stays UNVALIDATED with its self_rating still effective.

    PRD: "When the committee chair validates a rating, they supply a `validated_rating` from 1 through 5; the rating flips to `VALIDATED`, `validated_at` records the logical clock instant, and `effective_rating` becomes the `validated_rating`."

    Design: Difficulty/dual_variant_calc/skills_gap_self_reported_vs_validated_only_flip_priority_category
    """
    board = _board_with_cyber_ratings(client)

    assert_fields_equal(
        X.get_rating(client, board["rating_d1"]["id"]),
        {"validation_status": "VALIDATED", "validated_rating": 2, "effective_rating": 2},
    )
    assert_fields_equal(
        X.get_rating(client, board["rating_d2"]["id"]),
        {"validation_status": "UNVALIDATED", "validated_rating": None, "effective_rating": 3},
    )
