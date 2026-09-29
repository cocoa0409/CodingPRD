"""Duplicate scoring: the mode switch flips a verdict, and the Jaccard term decides the rest."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    setup_base, create_department, create_active_item, item_lifecycle,
    read_item, read_facility, patch_facility, set_clock,
    ANALYST, MANAGER2_USER_ID,
)


def _scope(ccn: str, **facility_extra) -> dict:
    facility_overrides = {"name": f"Hospital {ccn}", "cms_certification_number": ccn,
                          "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000}
    facility_overrides.update(facility_extra)
    return setup_base(
        facility_overrides=facility_overrides,
        revenue_code_overrides={
            "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
            "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={
            "name": "Cardiac Cath Lab", "cost_center_code": "CC-4100",
            "allowed_revenue_code_values": [],
        },
        price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
    )


PRICING = dict(cost_basis_cents=100000, medicare_rate_cents=50000,
               market_p75_cents=900000, effective_from="2026-09-01T00:00:00Z")


def test_switching_the_detection_mode_flips_the_verdict_on_one_unchanged_pair():
    """PRD §3.8: "Under **`STRICT_CODE`**, the score is exactly 1.0000 when the code signal is 1
    *and* the revenue signal is 1 *and* the two items share the same `department_id`, and exactly
    0.0000 in every other case; two items with identical descriptions but different `code_value`
    strings can therefore never be marked duplicates. Under **`FUZZY_DESCRIPTION`**, the score is the
    weighted sum of the code signal at weight 0.5, the description similarity at weight 0.3, and the
    revenue signal at weight 0.2, rounded half up to four decimal places."
    PRD §3.8: "And the similarity score between the item being retired and the surviving item must
    reach the threshold of 0.8000 under the facility's `duplicate_detection_mode`; a score below it
    is `ERR_DUPLICATE_SIMILARITY_TOO_LOW` (422)."
    PRD §3.8: "On success `lifecycle_status` becomes `INACTIVE` and the item's `version` advances by
    1; on the duplicate path, `duplicate_of_item_id` is set to the surviving item's identifier. The
    facility then loses the item from its aggregates: `active_item_count` decreases by 1,
    `aggregate_gross_charge_cents` decreases by the item's `gross_charge_cents`,
    `aggregate_cost_basis_cents` decreases by the item's `cost_basis_cents`, and
    `aggregate_markup_ratio_bp` is recomputed, with `Facility.version` advancing by 1."

    Design: Corner/calculations/duplicate_detection_mode_switch_flips_the_verdict_for_one_unchanged_item_pair
    """
    set_clock("2026-09-01T00:00:00Z")
    base = _scope("CCN-2193-MODE", duplicate_detection_mode="STRICT_CODE")
    annex = create_department(
        base["facility"]["id"], MANAGER2_USER_ID, name="Cardiac Cath Lab Annex",
        cost_center_code="CC-4200", allowed_revenue_code_values=[],
    )
    item_a = create_active_item(
        base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
        code_type="CPT", code_value="93458", **PRICING,
    )
    item_b = create_active_item(
        {**base, "department": annex}, cdm_number="CDM-1002",
        description="CARDIAC CATH BASIC", code_type="CPT", code_value="93458", **PRICING,
    )
    assert item_a["gross_charge_cents"] == 240000
    assert item_b["gross_charge_cents"] == 240000
    assert item_b["department_id"] == annex["id"]

    validate_error(
        api_client.charge_item_lifecycle(
            item_b["id"],
            {"action": "MARK_DUPLICATE", "duplicate_of_item_id": item_a["id"]},
            ANALYST,
        ),
        ApiErrorId.ERR_DUPLICATE_SIMILARITY_TOO_LOW.value, 422,
    )
    assert read_item(item_b["id"])["lifecycle_status"] == "ACTIVE", (
        "under STRICT_CODE the differing department drops the score to 0.0000"
    )

    switched = patch_facility(base["facility"]["id"],
                              duplicate_detection_mode="FUZZY_DESCRIPTION")
    assert switched["duplicate_detection_mode"] == "FUZZY_DESCRIPTION"

    retired = item_lifecycle(item_b["id"], "MARK_DUPLICATE", ANALYST,
                             duplicate_of_item_id=item_a["id"])
    assert retired["lifecycle_status"] == "INACTIVE", (
        "the same call now scores 0.5 plus 0.3 plus 0.2, exactly 1.0000"
    )
    stored_b = read_item(item_b["id"])
    assert stored_b["duplicate_of_item_id"] == item_a["id"]
    assert stored_b["version"] == 6, "create, reprice, submit, approve, activate, mark duplicate"

    survivor = read_item(item_a["id"])
    assert survivor["lifecycle_status"] == "ACTIVE"
    assert survivor["duplicate_of_item_id"] is None

    facility = read_facility(base["facility"]["id"])
    assert facility["duplicate_detection_mode"] == "FUZZY_DESCRIPTION"
    assert facility["active_item_count"] == 1
    assert facility["aggregate_gross_charge_cents"] == 240000
    assert facility["aggregate_cost_basis_cents"] == 100000
    assert facility["aggregate_markup_ratio_bp"] == 24000


def test_the_jaccard_component_alone_decides_which_sibling_is_a_duplicate():
    """PRD §3.8: "The description signal is a Jaccard similarity over description tokens, where
    tokenizing a `description` means upper-casing it, splitting on every non-alphanumeric character,
    discarding tokens shorter than three characters, and deduplicating the remainder into a set; the
    similarity is the size of the intersection of the two token sets divided by the size of their
    union, rounded half up to four decimal places, and defined as 0 when the union is empty."
    PRD §3.8: "a pair with identical codes and the same revenue code scores 0.7000 plus 0.3 times the
    description similarity, crossing the 0.8000 threshold only once that similarity reaches 0.3334."
    PRD §3.8: "Candidates are ranked by score descending, ties broken by `created_at` ascending,
    never by `id`."

    Design: Corner/calculations/fuzzy_weighted_score_crosses_the_threshold_only_when_the_jaccard_component_is_large_enough
    """
    set_clock("2026-09-01T00:00:00Z")
    base = _scope("CCN-2193-FUZZY", duplicate_detection_mode="FUZZY_DESCRIPTION")
    subject = create_active_item(
        base, cdm_number="CDM-1001", description="CARDIAC CATH",
        code_type="CPT", code_value="93458", **PRICING,
    )
    near = create_active_item(
        base, cdm_number="CDM-1002", description="CARDIAC CATH OF LEFT HEART",
        code_type="CPT", code_value="93458", **PRICING,
    )
    far = create_active_item(
        base, cdm_number="CDM-1003", description="CARDIAC OF LEFT HEART VESSEL",
        code_type="CPT", code_value="93458", **PRICING,
    )
    assert subject["gross_charge_cents"] == 240000

    candidates = validate_success(
        api_client.get_duplicate_candidates(subject["id"], ANALYST), 200
    )
    assert [row["id"] for row in candidates] == [near["id"], far["id"]], (
        "0.8500 outranks 0.7600 under score-descending ordering"
    )

    validate_error(
        api_client.charge_item_lifecycle(
            far["id"], {"action": "MARK_DUPLICATE", "duplicate_of_item_id": subject["id"]},
            ANALYST,
        ),
        ApiErrorId.ERR_DUPLICATE_SIMILARITY_TOO_LOW.value, 422,
    )

    retired = item_lifecycle(near["id"], "MARK_DUPLICATE", ANALYST,
                             duplicate_of_item_id=subject["id"])
    assert retired["lifecycle_status"] == "INACTIVE", (
        "two shared tokens out of a four-token union give 0.5000, so the score is 0.8500"
    )
    assert read_item(near["id"])["duplicate_of_item_id"] == subject["id"]

    survivor = read_item(far["id"])
    assert survivor["lifecycle_status"] == "ACTIVE", (
        "one shared token out of a five-token union gives 0.2000, so the score is 0.7600"
    )
    assert survivor["duplicate_of_item_id"] is None
    assert survivor["version"] == 5, "the refused retirement advanced nothing"

    facility = read_facility(base["facility"]["id"])
    assert facility["active_item_count"] == 2
    assert facility["aggregate_gross_charge_cents"] == 480000
