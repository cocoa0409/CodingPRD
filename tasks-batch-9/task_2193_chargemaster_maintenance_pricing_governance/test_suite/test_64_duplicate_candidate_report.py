"""The duplicate-candidate report: fuzzy scores, the score-then-created_at order, and min_score."""
from test_helpers import (
    api_client, validate_paginated,
    setup_base, create_item, create_active_item, item_lifecycle,
    read_facility, set_clock,
    ANALYST, APPROVER, COMPLIANCE,
)

FUZZY = dict(
    facility_overrides={
        "name": "Mercy Fuzzy", "cms_certification_number": "CCN-2193-FUZZY",
        "rounding_mode": "NEAREST_CENT", "duplicate_detection_mode": "FUZZY_DESCRIPTION",
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={"name": "Cardiac Cath Lab", "cost_center_code": "CC-100",
                         "allowed_revenue_code_values": []},
    price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
)


def _candidates(subject_id: str, headers, params=None):
    return validate_paginated(
        api_client.get_duplicate_candidates(subject_id, headers, params or {}))


def test_the_report_lists_five_scored_siblings_in_score_order_and_honours_an_inclusive_min_score():
    """PRD §3.8: "The candidate set for any subject item is every `ChargeItem` of the same facility other
    than the subject itself whose `lifecycle_status` is `ACTIVE` and whose `duplicate_of_item_id` is
    null; `INACTIVE`, `ARCHIVED` and `DRAFT` items and items already flagged as duplicates are excluded."
    PRD §3.8: "Candidates are ranked by score descending, ties broken by `created_at` ascending, never by
    `id`."
    PRD §3.8: "Under **`FUZZY_DESCRIPTION`**, the score is the weighted sum of the code signal at weight
    0.5, the description similarity at weight 0.3, and the revenue signal at weight 0.2, rounded half up
    to four decimal places."
    PRD §3.8: "The threshold comparison is inclusive: a score of exactly 0.8000 passes."
    PRD §3.8: "The same scoring is also available as a read-only report over a subject item's `ACTIVE`,
    non-duplicate siblings, ranked the same way, and accepting an optional `min_score` filter alongside
    the standard pagination parameters."

    Design: Corner/endpoints/duplicate_candidate_report_ranks_by_score_then_created_at_and_honours_min_score
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**FUZZY)
    facility_id = base["facility"]["id"]
    assert base["facility"]["duplicate_detection_mode"] == "FUZZY_DESCRIPTION"

    def pricing(hour):
        # Each item is created an hour after the previous one so that `created_at` is strictly
        # ordered and the score tie-break is observable; `effective_from` tracks the logical now.
        stamp = f"2026-09-01T{hour:02d}:00:00Z"
        set_clock(stamp)
        return dict(cost_basis_cents=100000, medicare_rate_cents=50000,
                    market_p75_cents=900000, effective_from=stamp)

    subject = create_active_item(base, cdm_number="CDM-2000",
                                 description="CARDIAC CATH LEFT HEART",
                                 code_type="CPT", code_value="93458", **pricing(0))
    assert subject["gross_charge_cents"] == 240000
    perfect = create_active_item(base, cdm_number="CDM-2001",
                                 description="CARDIAC CATH LEFT HEART",
                                 code_type="CPT", code_value="93458", **pricing(1))
    near = create_active_item(base, cdm_number="CDM-2002",
                              description="CARDIAC CATH RIGHT HEART",
                              code_type="CPT", code_value="93458", **pricing(2))
    disjoint_early = create_active_item(base, cdm_number="CDM-2003",
                                        description="PULMONARY FUNCTION TEST",
                                        code_type="CPT", code_value="93458", **pricing(3))
    disjoint_late = create_active_item(base, cdm_number="CDM-2004",
                                       description="BLOOD GAS PANEL",
                                       code_type="CPT", code_value="93458", **pricing(4))
    other_code = create_active_item(base, cdm_number="CDM-2005",
                                    description="CARDIAC CATH LEFT HEART",
                                    code_type="CPT", code_value="93460", **pricing(5))
    retired = create_active_item(base, cdm_number="CDM-2006",
                                 description="CARDIAC CATH LEFT HEART",
                                 code_type="CPT", code_value="93458", **pricing(6))
    flagged = item_lifecycle(retired["id"], "MARK_DUPLICATE", ANALYST,
                             duplicate_of_item_id=perfect["id"])
    assert flagged["lifecycle_status"] == "INACTIVE", "a score of 1.0000 clears the 0.8000 threshold"
    assert flagged["duplicate_of_item_id"] == perfect["id"]
    draft = create_item(base, cdm_number="CDM-2007", description="CARDIAC CATH LEFT HEART",
                        code_type="CPT", code_value="93458", **pricing(7))

    rows, meta = _candidates(subject["id"], ANALYST)
    assert meta["total_count"] == 5
    assert [row["id"] for row in rows] == [
        perfect["id"],        # 0.5 + 0.3 + 0.2 = 1.0000
        near["id"],           # 0.5 + 0.3 * 0.6000 + 0.2 = 0.8800
        disjoint_early["id"],  # 0.5 + 0 + 0.2 = 0.7000, created first
        disjoint_late["id"],  # 0.5 + 0 + 0.2 = 0.7000, created second
        other_code["id"],     # 0 + 0.3 + 0.2 = 0.5000
    ]
    listed = {row["id"] for row in rows}
    assert subject["id"] not in listed
    assert retired["id"] not in listed, "an item already flagged as a duplicate is excluded"
    assert draft["id"] not in listed, "a DRAFT sibling is excluded"

    strict_rows, strict_meta = _candidates(subject["id"], COMPLIANCE, {"min_score": 0.8801})
    assert strict_meta["total_count"] == 1
    assert [row["id"] for row in strict_rows] == [perfect["id"]], "0.8800 is below 0.8801"

    edge_rows, edge_meta = _candidates(subject["id"], APPROVER, {"min_score": 0.88})
    assert edge_meta["total_count"] == 2
    assert [row["id"] for row in edge_rows] == [perfect["id"], near["id"]], (
        "the floor is inclusive, so the 0.8800 row survives"
    )

    page_rows, page_meta = _candidates(
        subject["id"], ANALYST, {"min_score": 0.7, "limit": 2, "offset": 2})
    assert page_meta["total_count"] == 4
    assert page_meta["has_more"] is False
    assert [row["id"] for row in page_rows] == [disjoint_early["id"], disjoint_late["id"]], (
        "the 0.7000 tie is broken by created_at ascending"
    )

    top_rows, top_meta = _candidates(subject["id"], ANALYST, {"min_score": 0.9})
    assert top_meta["total_count"] == 1
    assert [row["id"] for row in top_rows] == [perfect["id"]]

    empty_rows, empty_meta = _candidates(other_code["id"], ANALYST, {"min_score": 0.8})
    assert empty_meta["total_count"] == 0
    assert empty_rows == [], "code 93460 matches nothing, so every sibling scores 0.5000 or less"

    facility = read_facility(facility_id)
    assert facility["active_item_count"] == 6
    assert facility["aggregate_gross_charge_cents"] == 1440000
    assert facility["aggregate_markup_ratio_bp"] == 24000
    assert facility["stale_price_item_count"] == 0
    assert facility["chargemaster_posture"] == "OPEN"
