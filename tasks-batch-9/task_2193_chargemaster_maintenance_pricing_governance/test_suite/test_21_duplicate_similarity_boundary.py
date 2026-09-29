"""The inclusive 0.8000 duplicate-similarity threshold under FUZZY_DESCRIPTION."""
from test_helpers import (
    api_client, validate_error, validate_success, ApiErrorId,
    setup_similarity_boundary_scenario,
    read_item, read_facility,
    ANALYST,
)


def _mark_duplicate(subject_id, survivor_id, note):
    return api_client.charge_item_lifecycle(
        subject_id,
        {"action": "MARK_DUPLICATE", "duplicate_of_item_id": survivor_id, "note": note},
        ANALYST,
    )


def test_a_score_one_step_below_the_threshold_is_refused_and_changes_nothing():
    """PRD §3.8: "And the similarity score between the item being retired and the surviving
    item must reach the threshold of 0.8000 under the facility's `duplicate_detection_mode`; a
    score below it is `ERR_DUPLICATE_SIMILARITY_TOO_LOW` (422)."
    PRD §3.8: "Under **`FUZZY_DESCRIPTION`**, the score is the weighted sum of the code signal
    at weight 0.5, the description similarity at weight 0.3, and the revenue signal at weight
    0.2, rounded half up to four decimal places."
    PRD §3.8: "the similarity is the size of the intersection of the two token sets divided by
    the size of their union, rounded half up to four decimal places, and defined as 0 when the
    union is empty."
    PRD §2.6: "One score in the system is not an integer: the duplicate similarity score is a
    decimal rounded half up to four decimal places, and its description-similarity component
    is rounded to four decimal places *before* it is multiplied by its weight."

    Design: Difficulty/boundary_precision_check/boundary_precision_check__similarity_score_exactly_at_0_8000_threshold_on_mark_duplicate
    """
    s = setup_similarity_boundary_scenario()
    facility_before = read_facility(s["facility"]["id"])
    assert facility_before["active_item_count"] == 6
    assert facility_before["aggregate_gross_charge_cents"] == 768000
    assert facility_before["aggregate_cost_basis_cents"] == 240000
    assert facility_before["aggregate_markup_ratio_bp"] == 32000

    validate_error(
        _mark_duplicate(s["s2"]["id"], s["t2"]["id"], "score 0.7900 one step below"),
        ApiErrorId.ERR_DUPLICATE_SIMILARITY_TOO_LOW.value,
        422,
    )

    subject = read_item(s["s2"]["id"])
    assert subject["lifecycle_status"] == "ACTIVE", (
        "three shared tokens over a ten-token union is 0.3000, so the score is "
        "0.5 + 0.3 * 0.3000 + 0.2 = 0.7900, which is below the threshold"
    )
    assert subject["duplicate_of_item_id"] is None
    assert read_item(s["t2"]["id"])["lifecycle_status"] == "ACTIVE"

    facility_after = read_facility(s["facility"]["id"])
    assert facility_after["active_item_count"] == 6
    assert facility_after["aggregate_gross_charge_cents"] == 768000


def test_a_score_of_exactly_zero_point_eight_retires_the_item_and_drains_the_aggregates():
    """PRD §3.8: "The threshold comparison is inclusive: a score of exactly 0.8000 passes."
    PRD §3.8: "The code signal is 1 when the two items share the same `code_type` and the same
    `code_value` and that `code_value` is non-null, and 0 otherwise. The revenue signal is 1
    when the two items share the same `revenue_code_id` and 0 otherwise."
    PRD §3.8: "On success `lifecycle_status` becomes `INACTIVE` and the item's `version`
    advances by 1; on the duplicate path, `duplicate_of_item_id` is set to the surviving item's
    identifier."
    PRD §3.8: "The facility then loses the item from its aggregates: `active_item_count`
    decreases by 1, `aggregate_gross_charge_cents` decreases by the item's
    `gross_charge_cents`, `aggregate_cost_basis_cents` decreases by the item's
    `cost_basis_cents`, and `aggregate_markup_ratio_bp` is recomputed, with `Facility.version`
    advancing by 1."

    Design: Difficulty/boundary_precision_check/boundary_precision_check__similarity_score_exactly_at_0_8000_threshold_on_mark_duplicate
    """
    s = setup_similarity_boundary_scenario()
    subject_version_before = read_item(s["s3"]["id"])["version"]

    retired = validate_success(
        _mark_duplicate(s["s3"]["id"], s["t3"]["id"], "0.8000 via a different composition"),
        200,
    )
    assert retired["lifecycle_status"] == "INACTIVE", (
        "identical codes give the code signal 1 and identical descriptions give a Jaccard of "
        "1.0000, so 0.5 + 0.3 * 1.0000 + 0.2 * 0 is exactly 0.8000 even though the two items "
        "sit on different revenue codes"
    )
    assert retired["duplicate_of_item_id"] == s["t3"]["id"]
    assert retired["version"] == subject_version_before + 1
    assert read_item(s["t3"]["id"])["lifecycle_status"] == "ACTIVE", (
        "the surviving item is untouched by the retirement"
    )

    facility = read_facility(s["facility"]["id"])
    assert facility["active_item_count"] == 5
    assert facility["aggregate_gross_charge_cents"] == 640000
    assert facility["aggregate_cost_basis_cents"] == 200000
    assert facility["aggregate_markup_ratio_bp"] == 32000, (
        "the five survivors are economically identical, so the ratio is unmoved"
    )
