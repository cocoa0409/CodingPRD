"""Asset registration, quarter interval semantics, and income-item listing."""
from test_helpers import (
    ApiErrorId,
    assert_asset_holding,
    create_asset_holding,
    create_asset_holding_payload,
    create_income_item,
    create_quarter,
    create_quarter_payload,
    create_reit,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_asset_holding_held_status_and_enum_rejection(
        api, compliance_officer_headers):
    """PRD §3.1: "New assets arrive in `HELD` status."
    PRD §3.1: each asset carries "an `asset_class` of `REAL_ESTATE`,
    `QUALIFYING_SECURITY`, or `NON_QUALIFYING`".
    PRD §2.9: "then payload shape and enum/range checks (`ERR_VALIDATION`)".

    Design: Corner/entities/asset_holding_held_status_on_create_and_enum_rejection
    """
    reit = create_reit(legal_name="Asset REIT")
    created = validate_success(
        api.create_asset_holding(
            create_asset_holding_payload(
                reit["id"], asset_name="Depot",
                asset_class="QUALIFYING_SECURITY", value_cents=123456,
                acquisition_date="2025-05-01",
            ),
            compliance_officer_headers,
        ),
        201,
    )
    assert_asset_holding(created)
    assert created["status"] == "HELD"

    bad = api.create_asset_holding(
        create_asset_holding_payload(
            reit["id"], asset_name="Mystery", asset_class="CRYPTO",
            value_cents=1, acquisition_date="2025-05-01",
        ),
        compliance_officer_headers,
    )
    validate_error(bad, ApiErrorId.ERR_VALIDATION)


def test_income_item_cross_reit_quarter_rejected(api, compliance_officer_headers):
    """PRD §3.2: "The quarter referenced by `quarter_id` must belong to the
    same REIT as the `reit_id` on the item; a mismatch is a cross-REIT
    reference and is rejected with `ERR_CROSS_REIT_REFERENCE`."

    Design: Corner/entities/cross_reit_fk_reference_rejected
    """
    reit_a = create_reit(legal_name="RA")
    reit_b = create_reit(legal_name="RB")
    quarter_b = create_quarter(reit_b["id"])

    resp = api.create_income_item(
        {
            "reit_id": reit_a["id"],
            "quarter_id": quarter_b["id"],
            "income_class": "RENTS",
            "amount_cents": 100,
            "source_is_trs": False,
            "accrued_at": "2026-01-15",
        },
        compliance_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_REIT_REFERENCE)


def test_filtered_list_income_items_by_quarter(api, compliance_officer_headers):
    """PRD §4: "List income items; filterable by `reit_id` or `quarter_id`".

    Design: Corner/endpoints/filtered_list_income_items_by_quarter
    """
    reit = create_reit(legal_name="FLT REIT")
    q1 = create_quarter(reit["id"], label="2026-Q1",
                        period_start="2026-01-01", period_end="2026-03-31")
    q2 = create_quarter(reit["id"], label="2026-Q2",
                        period_start="2026-04-01", period_end="2026-06-30")
    create_income_item(reit["id"], q1["id"], amount_cents=100,
                       accrued_at="2026-01-10")
    create_income_item(reit["id"], q2["id"], amount_cents=200,
                       accrued_at="2026-04-10")

    resp = api.list_income_items(compliance_officer_headers,
                                 params={"quarter_id": q1["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"quarter filter must isolate Q1 items: {data}"
    assert data[0]["amount_cents"] == 100
    assert data[0]["quarter_id"] == q1["id"]
    assert meta["total_count"] == 1


class TestQuarterIntervalOverlap:
    def test_adjacent_quarter_accepted(self, api, compliance_officer_headers):
        """PRD §3.2: "the new quarter's closed interval must not intersect any
        existing quarter of the same REIT — adjacency is permitted (an
        existing quarter may end the day before the new one begins), but
        sharing even a single calendar day is a conflict and yields
        `ERR_QUARTER_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/quarter_closed_interval_overlap_rejected_adjacency_allowed
        """
        reit = create_reit(legal_name="OV1 REIT")
        create_quarter(reit["id"], label="2026-Q1",
                       period_start="2026-01-01", period_end="2026-03-31")
        resp = api.create_quarter(
            create_quarter_payload(reit["id"], label="2026-Q2-adjacent",
                                   period_start="2026-04-01",
                                   period_end="2026-06-30"),
            compliance_officer_headers,
        )
        quarter = validate_success(resp, 201)
        assert quarter["status"] == "OPEN"

    def test_single_shared_day_rejected(self, api, compliance_officer_headers):
        """PRD §3.2: "the new quarter's closed interval must not intersect any
        existing quarter of the same REIT — adjacency is permitted (an
        existing quarter may end the day before the new one begins), but
        sharing even a single calendar day is a conflict and yields
        `ERR_QUARTER_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/quarter_closed_interval_overlap_rejected_adjacency_allowed
        """
        reit = create_reit(legal_name="OV1 REIT")
        create_quarter(reit["id"], label="2026-Q1",
                       period_start="2026-01-01", period_end="2026-03-31")
        resp = api.create_quarter(
            create_quarter_payload(reit["id"], label="2026-Q1B",
                                   period_start="2026-03-31",
                                   period_end="2026-05-31"),
            compliance_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_QUARTER_OVERLAP)
