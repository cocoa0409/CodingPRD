"""Line classification: the inclusive variance boundary, the mean, and the five-test ladder."""
from test_helpers import (
    api_client, get_success_data,
    setup_base, create_active_item, item_lifecycle, create_batch, append_line,
    reconcile_batch, read_batch, read_item, set_clock,
    ANALYST,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-MERCY",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
    },
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

ITEM_A = dict(
    cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
    code_type="CPT", code_value="93458", cost_basis_cents=100000,
    medicare_rate_cents=50000, market_p75_cents=900000,
    effective_from="2026-09-01T00:00:00Z",
)


def _read_line(line_id: str) -> dict:
    return get_success_data(api_client.get_captured_charge(line_id, ANALYST))


def test_a_variance_of_exactly_one_percent_still_matches_and_the_mean_is_per_line():
    """PRD §3.9: "Otherwise `expected_charge_cents` is computed as the resolved item's
    `gross_charge_cents` multiplied by the line's `quantity`, and `line_variance_bp` as the posted
    charge less the expected charge, multiplied by 10000, divided by the expected charge, rounded
    half up. If the absolute value of `line_variance_bp` is greater than 100 basis points — that is,
    more than one percent away from expected — `match_status` becomes `PRICE_VARIANCE`. The boundary
    is exact: an absolute variance of exactly 100 basis points is `MATCHED`, and 101 is
    `PRICE_VARIANCE`."
    PRD §3.9: "Otherwise `mean_line_variance_bp` is the sum of the scored lines' already-rounded
    `line_variance_bp` values divided by the count of scored lines, rounded half up to whole basis
    points. Rounding each line first and averaging those rounded values is the specification; summing
    raw amounts and dividing once at the aggregate level produces a different number for the same
    lines and is wrong."
    PRD §3.9: "Alongside the mean, `total_expected_charge_cents` is the sum of
    `expected_charge_cents` over every line whose `match_status` is not `UNKNOWN_CODE`, and
    `total_posted_charge_cents` is the sum of `posted_charge_cents` over **all** lines in the batch
    including the unknown-code and duplicate ones."

    Design: Corner/calculations/variance_tolerance_is_inclusive_at_100_bp_and_the_mean_is_round_per_line_then_average
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    item = create_active_item(base, **ITEM_A)
    assert item["gross_charge_cents"] == 240000

    set_clock("2026-09-10T00:00:00Z")
    batch = create_batch(base, window_start_date="2026-09-01T00:00:00Z",
                         window_end_date="2026-09-07T00:00:00Z")
    zero = append_line(batch["id"], "CDM-1001", base["manager_headers"], encounter_id="ENC-1",
                       payer_code="BCBS", service_datetime="2026-09-02T08:00:00Z", quantity=1,
                       posted_charge_cents=240000)
    edge = append_line(batch["id"], "CDM-1001", base["manager_headers"], encounter_id="ENC-2",
                       payer_code="BCBS", service_datetime="2026-09-03T08:00:00Z", quantity=3,
                       posted_charge_cents=727200)
    over = append_line(batch["id"], "CDM-1001", base["manager_headers"], encounter_id="ENC-3",
                       payer_code="BCBS", service_datetime="2026-09-04T08:00:00Z", quantity=1,
                       posted_charge_cents=242424)
    unknown = append_line(batch["id"], "CDM-9999", base["manager_headers"], encounter_id="ENC-4",
                          payer_code="BCBS", service_datetime="2026-09-05T08:00:00Z", quantity=1,
                          posted_charge_cents=50000)

    reconciled = reconcile_batch(batch["id"])
    assert reconciled["mean_line_variance_bp"] == 67, (
        "the three rounded values 0, 100 and 101 average to 67; aggregating first gives 80"
    )
    assert reconciled["matched_line_count"] == 2
    assert reconciled["exception_line_count"] == 2
    assert reconciled["total_expected_charge_cents"] == 1200000, (
        "the unknown-code line contributes no expectation"
    )
    assert reconciled["total_posted_charge_cents"] == 1259624, (
        "every line's posted charge counts, unknown code included"
    )

    line_zero = _read_line(zero["id"])
    assert line_zero["match_status"] == "MATCHED"
    assert line_zero["line_variance_bp"] == 0

    line_edge = _read_line(edge["id"])
    assert line_edge["match_status"] == "MATCHED", "exactly 100 basis points is still a match"
    assert line_edge["expected_charge_cents"] == 720000
    assert line_edge["line_variance_bp"] == 100

    line_over = _read_line(over["id"])
    assert line_over["match_status"] == "PRICE_VARIANCE", "101 basis points is one too many"
    assert line_over["line_variance_bp"] == 101

    line_unknown = _read_line(unknown["id"])
    assert line_unknown["match_status"] == "UNKNOWN_CODE"
    assert line_unknown["expected_charge_cents"] is None
    assert line_unknown["line_variance_bp"] is None

    stored = read_batch(batch["id"])
    assert stored["status"] == "RECONCILING"
    assert stored["reconcile_pass_count"] == 1
    assert stored["line_count"] == 4
    assert stored["open_finding_count"] == 0


def test_the_first_matching_test_wins_all_the_way_down_the_ladder():
    """PRD §3.9: "Five tests are applied and the **first** match wins:"
    PRD §3.9: "Otherwise `charge_item_id` records the resolved item; if that item's
    `lifecycle_status` is `INACTIVE` or `ARCHIVED`, `match_status` becomes `INACTIVE_ITEM`."
    PRD §3.9: "Otherwise, if another line of the *same* batch shares this line's `encounter_id`,
    `charge_item_id` and `service_datetime` and has an earlier `created_at`, `match_status` becomes
    `DUPLICATE_LINE`."

    Design: Corner/calculations/match_status_precedence_puts_unknown_code_then_inactive_item_then_duplicate_line_before_variance
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    item_a = create_active_item(base, **ITEM_A)
    item_b = create_active_item(
        base, cdm_number="CDM-1002", description="CARDIAC CATH ADD-ON",
        code_type="CPT", code_value="93459", cost_basis_cents=60000,
        medicare_rate_cents=20000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    assert item_a["gross_charge_cents"] == 240000
    assert item_b["gross_charge_cents"] == 144000
    item_lifecycle(item_b["id"], "DEACTIVATE", ANALYST, note="Retired mid-year")
    assert read_item(item_b["id"])["lifecycle_status"] == "INACTIVE"

    set_clock("2026-09-10T00:00:00Z")
    batch = create_batch(base, window_start_date="2026-09-01T00:00:00Z",
                         window_end_date="2026-09-07T00:00:00Z")
    unknown = append_line(batch["id"], "CDM-9999", base["manager_headers"], encounter_id="ENC-1",
                          payer_code="BCBS", service_datetime="2026-09-02T08:00:00Z", quantity=1,
                          posted_charge_cents=10000)
    inactive = append_line(batch["id"], "CDM-1002", base["manager_headers"], encounter_id="ENC-1",
                           payer_code="BCBS", service_datetime="2026-09-02T09:00:00Z", quantity=1,
                           posted_charge_cents=144000)
    first = append_line(batch["id"], "CDM-1001", base["manager_headers"], encounter_id="ENC-2",
                        payer_code="BCBS", service_datetime="2026-09-03T08:00:00Z", quantity=1,
                        posted_charge_cents=480000)
    duplicate = append_line(batch["id"], "CDM-1001", base["manager_headers"], encounter_id="ENC-2",
                            payer_code="BCBS", service_datetime="2026-09-03T08:00:00Z", quantity=1,
                            posted_charge_cents=240000)

    reconciled = reconcile_batch(batch["id"])
    assert reconciled["mean_line_variance_bp"] == 10000, (
        "only the earlier of the twins is scored at all"
    )
    assert reconciled["matched_line_count"] == 0
    assert reconciled["exception_line_count"] == 4
    assert reconciled["total_posted_charge_cents"] == 874000

    line_unknown = _read_line(unknown["id"])
    assert line_unknown["match_status"] == "UNKNOWN_CODE"
    assert line_unknown["charge_item_id"] is None

    line_inactive = _read_line(inactive["id"])
    assert line_inactive["match_status"] == "INACTIVE_ITEM", (
        "the posted amount matches exactly, but the item test ranks higher"
    )
    assert line_inactive["charge_item_id"] == item_b["id"]

    line_first = _read_line(first["id"])
    assert line_first["match_status"] == "PRICE_VARIANCE"
    assert line_first["line_variance_bp"] == 10000

    line_duplicate = _read_line(duplicate["id"])
    assert line_duplicate["match_status"] == "DUPLICATE_LINE", (
        "the later twin is a duplicate even though its own variance would be 0"
    )

    stored = read_batch(batch["id"])
    assert stored["status"] == "RECONCILING"
    assert stored["line_count"] == 4
