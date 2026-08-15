"""Property data room: rent roll append rules, occupancy derivation, and
operating-expense uniqueness (PRD §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_property,
    assert_operating_expense,
    assert_rent_roll_period,
    create_deal,
    create_operating_expense_payload,
    create_property_payload,
    create_rent_roll_payload,
    validate_error,
    validate_success,
)


def _deal_with_property(api, property_overrides=None):
    """Fresh deal + one property (deal left in DRAFT)."""
    deal = create_deal()
    prop = add_property(deal["id"], **(property_overrides or {}))
    return deal, prop


def test_occupancy_pct_null_until_first_rent_roll(api, analyst_headers):
    """PRD §3.2: "Until the first rent roll exists, `occupancy_pct` is null."
    PRD §3.2: "The property's occupancy is the ratio of `occupied_units` to
    `total_units` from the most recent `RentRollPeriod` by `period_month`,
    multiplied by 10000, rounded half-up to an integer, and then divided by 100 —
    yielding a percentage stored with exactly two decimal places (so 92.50 means
    92.50%)."

    Design: Corner/entities/property_occupancy_pct_computed_from_rent_roll
    """
    _, prop = _deal_with_property(api, {"units": 10, "rentable_sqft": 10_000})
    assert prop.get("occupancy_pct") is None, (
        f"occupancy_pct must be null before the first rent roll, got {prop.get('occupancy_pct')!r}"
    )

    rr = validate_success(
        api.create_rent_roll(
            prop["id"],
            create_rent_roll_payload(
                period_month="2026-06", occupied_units=9, total_units=10,
                gross_potential_rent_cents=1_000_000, collected_rent_cents=900_000,
                source_doc_ref="rr",
            ),
            analyst_headers,
        ),
        201,
    )
    assert_rent_roll_period(rr)
    after = validate_success(api.get_property(prop["id"], analyst_headers), 200)
    assert after["occupancy_pct"] == pytest.approx(90.0), (
        f"expected 90.0, got {after['occupancy_pct']!r}"
    )


def test_property_invalid_property_type_returns_400(api, analyst_headers):
    """PRD §3.2: "The analyst provides `address_line`, `market` (an MSA or market
    name such as "Austin, TX"), `property_type` (one of `MULTIFAMILY`, `OFFICE`,
    `RETAIL`, `INDUSTRIAL`, `MIXED_USE`), `units` (at least 1), `rentable_sqft`
    (at least 100), and `year_built` (between 1800 and 2100)."
    PRD §2.8: "9. Business constraint checks (duplicate `deal_code` —
    `ERR_DUPLICATE_DEAL_CODE` (409); duplicate `(property_id, period_month)` for a
    rent roll or `(property_id, period_year, category)` for an operating expense —
    `ERR_DUPLICATE_PERIOD` (409); out-of-range numerics such as
    `occupancy_stress_pct`, `exit_cap_rate_bps`, `amortization_years`,
    `hold_period_years` — `ERR_INVALID_REQUEST` (400))."

    Design: Corner/entities/property_invalid_enum_returns_400
    """
    deal = create_deal()
    res = api.create_property(
        deal["id"],
        create_property_payload(property_type="CASTLE"),
        analyst_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_rent_roll_response_is_append_only(api, analyst_headers):
    """PRD §2.4: "Two resource types are exceptions to this rule and carry only
    `id` and `created_at` — both `updated_at` and `version` are absent:"
    PRD §2.4: "- `RentRollPeriod`"
    PRD §2.4: "These are append-only records. They are never updated, so
    optimistic concurrency does not apply to them."

    Design: Corner/entities/rent_roll_immutable_after_create
    """
    _, prop = _deal_with_property(api)
    rr = validate_success(
        api.create_rent_roll(prop["id"], create_rent_roll_payload(), analyst_headers),
        201,
    )
    assert_rent_roll_period(rr)
    assert "version" not in rr, "RentRollPeriod must not carry version"
    assert "updated_at" not in rr, "RentRollPeriod must not carry updated_at"
    assert "id" in rr and "created_at" in rr


def test_occupancy_recomputed_on_each_rent_roll_post(api, analyst_headers):
    """PRD §3.2: "Each rent roll append also triggers a recomputation of the
    property's `occupancy_pct`."
    PRD §3.2: "The property's occupancy is the ratio of `occupied_units` to
    `total_units` from the most recent `RentRollPeriod` by `period_month`,
    multiplied by 10000, rounded half-up to an integer, and then divided by 100 —
    yielding a percentage stored with exactly two decimal places (so 92.50 means
    92.50%)."

    Design: Corner/cross_cutting_complexity_layers/derived_field_occupancy_reconciles_on_each_rent_roll_post
    """
    _, prop = _deal_with_property(api, {"units": 10, "rentable_sqft": 10_000})
    validate_success(
        api.create_rent_roll(
            prop["id"],
            create_rent_roll_payload(
                period_month="2026-05", occupied_units=5, total_units=10,
                source_doc_ref="rr5",
            ),
            analyst_headers,
        ),
        201,
    )
    after_may = validate_success(api.get_property(prop["id"], analyst_headers), 200)
    assert after_may["occupancy_pct"] == pytest.approx(50.0), (
        f"after 2026-05: expected 50.0, got {after_may['occupancy_pct']!r}"
    )

    validate_success(
        api.create_rent_roll(
            prop["id"],
            create_rent_roll_payload(
                period_month="2026-06", occupied_units=9, total_units=10,
                source_doc_ref="rr6",
            ),
            analyst_headers,
        ),
        201,
    )
    after_june = validate_success(api.get_property(prop["id"], analyst_headers), 200)
    assert after_june["occupancy_pct"] == pytest.approx(90.0), (
        f"after 2026-06: expected 90.0 (recomputed), got {after_june['occupancy_pct']!r}"
    )


def test_occupancy_uses_latest_rent_roll_only(api, analyst_headers):
    """PRD §3.2: "The property's occupancy is the ratio of `occupied_units` to
    `total_units` from the most recent `RentRollPeriod` by `period_month`,
    multiplied by 10000, rounded half-up to an integer, and then divided by 100 —
    yielding a percentage stored with exactly two decimal places (so 92.50 means
    92.50%)."

    Design: Corner/calculations/occupancy_pct_uses_latest_rent_roll_only
    """
    _, prop = _deal_with_property(api, {"units": 100, "rentable_sqft": 10_000})
    validate_success(
        api.create_rent_roll(
            prop["id"],
            create_rent_roll_payload(
                period_month="2026-05", occupied_units=80, total_units=100,
                source_doc_ref="rr5",
            ),
            analyst_headers,
        ),
        201,
    )
    validate_success(
        api.create_rent_roll(
            prop["id"],
            create_rent_roll_payload(
                period_month="2026-06", occupied_units=92, total_units=100,
                source_doc_ref="rr6",
            ),
            analyst_headers,
        ),
        201,
    )
    after = validate_success(api.get_property(prop["id"], analyst_headers), 200)
    assert after["occupancy_pct"] == pytest.approx(92.0), (
        f"latest month must win (not the 86.0 average): got {after['occupancy_pct']!r}"
    )


def test_occupancy_rounds_half_up_one_third(api, analyst_headers):
    """PRD §3.2: "The property's occupancy is the ratio of `occupied_units` to
    `total_units` from the most recent `RentRollPeriod` by `period_month`,
    multiplied by 10000, rounded half-up to an integer, and then divided by 100 —
    yielding a percentage stored with exactly two decimal places (so 92.50 means
    92.50%)."
    1/3 * 10000 = 3333.33... rounds half-up to 3333, divided by 100 -> 33.33.

    Design: Difficulty/boundary_precision_check/occupancy_pct_two_decimal_rounding
    """
    _, prop = _deal_with_property(
        api, {"property_type": "MULTIFAMILY", "units": 3, "rentable_sqft": 3_000}
    )
    validate_success(
        api.create_rent_roll(
            prop["id"],
            create_rent_roll_payload(
                period_month="2026-06", occupied_units=1, total_units=3,
                gross_potential_rent_cents=300_000, collected_rent_cents=100_000,
            ),
            analyst_headers,
        ),
        201,
    )
    after = validate_success(api.get_property(prop["id"], analyst_headers), 200)
    assert after["occupancy_pct"] == pytest.approx(33.33, abs=1e-9), (
        f"1/3 must round half-up to exactly 33.33, got {after['occupancy_pct']!r}"
    )


def test_occupancy_rounds_half_up_two_thirds(api, analyst_headers):
    """PRD §3.2: "The property's occupancy is the ratio of `occupied_units` to
    `total_units` from the most recent `RentRollPeriod` by `period_month`,
    multiplied by 10000, rounded half-up to an integer, and then divided by 100 —
    yielding a percentage stored with exactly two decimal places (so 92.50 means
    92.50%)."
    2/3 * 10000 = 6666.66... rounds half-up to 6667, divided by 100 -> 66.67.

    Design: Difficulty/boundary_precision_check/occupancy_pct_two_decimal_rounding
    """
    _, prop = _deal_with_property(
        api, {"property_type": "MULTIFAMILY", "units": 3, "rentable_sqft": 3_000}
    )
    validate_success(
        api.create_rent_roll(
            prop["id"],
            create_rent_roll_payload(
                period_month="2026-06", occupied_units=2, total_units=3,
                gross_potential_rent_cents=300_000, collected_rent_cents=200_000,
            ),
            analyst_headers,
        ),
        201,
    )
    after = validate_success(api.get_property(prop["id"], analyst_headers), 200)
    assert after["occupancy_pct"] == pytest.approx(66.67, abs=1e-9), (
        f"2/3 must round half-up to exactly 66.67, got {after['occupancy_pct']!r}"
    )


def test_rent_roll_same_month_reentry_rejected(api, analyst_headers):
    """PRD §3.2: "Only one rent roll row may exist per `(property_id,
    period_month)` pair; a duplicate is rejected with `ERR_DUPLICATE_PERIOD`
    (HTTP 409)."
    PRD §2.8: "When several validation rules apply to a single request, they are
    evaluated in the following priority order. A failure at any tier
    short-circuits the remainder." — business-constraint duplicates (tier 9)
    precede business-temporal monotonicity (tier 12), so the same-month re-entry
    surfaces ERR_DUPLICATE_PERIOD.

    Design: Difficulty/resource_temporal_overlap/rent_roll_period_month_strictly_increasing
    """
    _, prop = _deal_with_property(api)
    validate_success(
        api.create_rent_roll(
            prop["id"], create_rent_roll_payload(period_month="2026-06"), analyst_headers
        ),
        201,
    )
    res = api.create_rent_roll(
        prop["id"],
        create_rent_roll_payload(period_month="2026-06", source_doc_ref="rr-dup"),
        analyst_headers,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_PERIOD)


def test_rent_roll_backfill_rejected_nonmonotonic(api, analyst_headers):
    """PRD §3.2: "The server enforces that the new `period_month` is strictly
    greater than the latest existing `period_month` on the same property; an
    append that violates monotonicity is rejected with `ERR_NONMONOTONIC_PERIOD`
    (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/rent_roll_period_month_strictly_increasing
    """
    _, prop = _deal_with_property(api)
    validate_success(
        api.create_rent_roll(
            prop["id"], create_rent_roll_payload(period_month="2026-06"), analyst_headers
        ),
        201,
    )
    res = api.create_rent_roll(
        prop["id"],
        create_rent_roll_payload(period_month="2026-05", source_doc_ref="rr-back"),
        analyst_headers,
    )
    validate_error(res, ApiErrorId.ERR_NONMONOTONIC_PERIOD)


def test_operating_expense_duplicate_year_category_rejected(api, analyst_headers):
    """PRD §3.2: "Only one row may exist per `(property_id, period_year,
    category)` triple; a duplicate is rejected with `ERR_DUPLICATE_PERIOD`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/operating_expense_unique_year_category
    """
    _, prop = _deal_with_property(api)
    first = validate_success(
        api.create_operating_expense(
            prop["id"],
            create_operating_expense_payload(period_year=2025, category="TAXES",
                                             amount_cents=1_000_000),
            analyst_headers,
        ),
        201,
    )
    assert_operating_expense(first)
    res = api.create_operating_expense(
        prop["id"],
        create_operating_expense_payload(period_year=2025, category="TAXES",
                                         amount_cents=999_999),
        analyst_headers,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_PERIOD)


def test_operating_expense_same_category_different_year_allowed(api, analyst_headers):
    """PRD §3.2: "Only one row may exist per `(property_id, period_year,
    category)` triple; a duplicate is rejected with `ERR_DUPLICATE_PERIOD`
    (HTTP 409)." — the uniqueness scope is the full triple, so the same category
    in a different year occupies a different bucket and is accepted.

    Design: Difficulty/resource_temporal_overlap/operating_expense_unique_year_category
    """
    _, prop = _deal_with_property(api)
    validate_success(
        api.create_operating_expense(
            prop["id"],
            create_operating_expense_payload(period_year=2025, category="TAXES",
                                             amount_cents=1_000_000),
            analyst_headers,
        ),
        201,
    )
    other_year = validate_success(
        api.create_operating_expense(
            prop["id"],
            create_operating_expense_payload(period_year=2024, category="TAXES",
                                             amount_cents=900_000),
            analyst_headers,
        ),
        201,
    )
    assert_operating_expense(other_year)
    assert other_year["period_year"] == 2024
    assert other_year["category"] == "TAXES"


def test_operating_expense_future_period_rejected(api, analyst_headers, admin_headers):
    """PRD §3.2: "The server also rejects a `period_year` that lies in the future
    relative to the server's logical clock with `ERR_FUTURE_PERIOD` (HTTP 422)."
    PRD §2.9: "At server startup, the logical clock is initialized to
    `2026-08-01T00:00:00Z` and never falls back to the wall clock."

    Design: Corner/errors/err_future_period_triggered
    """
    validate_success(
        api.set_current_utc({"to_iso8601": "2026-08-01T00:00:00Z"}, admin_headers), 200
    )
    _, prop = _deal_with_property(api)
    res = api.create_operating_expense(
        prop["id"],
        create_operating_expense_payload(period_year=2027, category="TAXES",
                                         amount_cents=100),
        analyst_headers,
    )
    validate_error(res, ApiErrorId.ERR_FUTURE_PERIOD)
