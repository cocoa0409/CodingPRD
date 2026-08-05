"""Dynamic pricing quote (seasonal x occupancy x last-minute) and pricing-rule OCC."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    create_pricing_rule_payload, fixtures,
)

PM = TEST_USERS["property_manager_headers"]


def _seasonal_quote_setup(api):
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api, base_nightly_rate_cents=20000,
                                             cleaning_fee_cents=15000, occupancy_tax_pct=10)
    pid = listed["property"]["id"]
    version = fixtures.get_property_version(api, pid)
    get_success_data(api.create_pricing_rule(pid, create_pricing_rule_payload(
        "SEASONAL", priority=1, expected_property_version=version,
        multiplier_bps=15000, start_date="2026-06-01T00:00:00Z", end_date="2026-06-30T00:00:00Z"), PM))
    return pid


def test_dynamic_quote_seasonal_lastminute_per_night(api):
    """PRD §3.3: "among matches, the highest-priority rule wins, breaking any tie in favor
    of the earliest-created rule, and its factor is its `multiplier_bps` divided by 10000".
    PRD §3.3: "The last-minute factor applies when the whole-day gap between the logical
    clock and check-in is seven days or fewer, in which case the factor is 0.85, otherwise 1.0."
    PRD §3.3: "The per-night rate is the base multiplied by all three factors, rounded
    half-up to whole cents exactly once after the full product".

    Design: Difficulty/combinatorial_formula/dynamic_quote_seasonal_occupancy_lastminute
    """
    pid = _seasonal_quote_setup(api)
    resp = api.quote_property(pid, {"check_in": "2026-06-06T00:00:00Z", "check_out": "2026-06-09T00:00:00Z"}, PM)
    data = validate_success(resp, 200)
    # base 20000 * seasonal 1.5 * occupancy 1.0 * last-minute 0.85 = 25500
    assert data["per_night_rate_cents"] == 25500, f"expected 25500, got {data['per_night_rate_cents']}"
    assert data["occupancy_pct"] == 0, f"expected occupancy 0, got {data['occupancy_pct']}"


def test_dynamic_quote_seasonal_subtotal_and_total(api):
    """PRD §3.3: "the nightly subtotal is then that per-night rate multiplied by the number of nights."
    PRD §3.4: "computes `occupancy_tax_cents` as the taxable base (nightly subtotal plus
    cleaning fee) multiplied by the active permit's `occupancy_tax_pct` divided by one
    hundred and rounded half-up ... and sets `total_cents` to the sum of nightly subtotal,
    cleaning fee, and occupancy tax."

    Design: Difficulty/combinatorial_formula/dynamic_quote_seasonal_occupancy_lastminute
    """
    pid = _seasonal_quote_setup(api)
    resp = api.quote_property(pid, {"check_in": "2026-06-06T00:00:00Z", "check_out": "2026-06-09T00:00:00Z"}, PM)
    data = validate_success(resp, 200)
    assert data["nightly_subtotal_cents"] == 76500, f"expected 76500, got {data['nightly_subtotal_cents']}"
    # taxable base 91500 * 10% = 9150 tax; total 76500 + 15000 + 9150 = 100650
    assert data["total_cents"] == 100650, f"expected 100650, got {data['total_cents']}"


def test_last_minute_discount_7day_inclusive_boundary(api):
    """PRD §3.3: "The last-minute factor applies when the whole-day gap between the logical
    clock and check-in is seven days or fewer, in which case the factor is 0.85, otherwise 1.0."
    PRD §3.3: "The per-night rate is the base multiplied by all three factors, rounded
    half-up to whole cents exactly once after the full product".

    Design: Corner/calculations/last_minute_discount_7day_inclusive_boundary
    """
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api, base_nightly_rate_cents=20000)
    resp = api.quote_property(listed["property"]["id"],
                              {"check_in": "2026-06-08T00:00:00Z", "check_out": "2026-06-09T00:00:00Z"}, PM)
    data = validate_success(resp, 200)
    # exactly 7 days out => 0.85 applies; round_half_up(20000 * 0.85) = 17000
    assert data["per_night_rate_cents"] == 17000, f"expected 17000, got {data['per_night_rate_cents']}"


def test_pricing_rule_create_correct_version_succeeds(api):
    """PRD §2.7: "A successful pricing-rule create increments the property's `version` by 1."
    PRD §3.3: "A rule carries an `active` flag that begins true and is set false once the
    rule is superseded."

    Design: Corner/cross_cutting_complexity_layers/pricing_rule_create_correct_version_succeeds
    """
    owner = fixtures.create_owner(api)
    prop = fixtures.create_property(api, owner["id"])
    assert prop["version"] == 1
    resp = api.create_pricing_rule(prop["id"], create_pricing_rule_payload(
        "SEASONAL", priority=1, expected_property_version=prop["version"],
        multiplier_bps=12000, start_date="2026-07-01T00:00:00Z", end_date="2026-07-31T00:00:00Z"), PM)
    rule = validate_success(resp, 201)
    assert rule["active"] is True
    assert get_success_data(api.get_property(prop["id"], PM))["version"] == 2


def test_pricing_rule_create_stale_version_returns_412(api):
    """PRD §2.7: "The create request must carry an `expected_property_version` field, which
    is not optional and must equal the target property's current `version` at the moment the
    server processes the request. If another writer has advanced the property's version since
    the client last read it — for example by creating an intervening pricing rule — the create
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/pricing_rule_create_stale_version_returns_412
    """
    owner = fixtures.create_owner(api)
    prop = fixtures.create_property(api, owner["id"])
    original_version = prop["version"]
    get_success_data(api.create_pricing_rule(prop["id"], create_pricing_rule_payload(
        "SEASONAL", priority=1, expected_property_version=original_version,
        multiplier_bps=12000, start_date="2026-07-01T00:00:00Z", end_date="2026-07-31T00:00:00Z"), PM))
    # second create still carries the now-stale original version
    resp = api.create_pricing_rule(prop["id"], create_pricing_rule_payload(
        "SEASONAL", priority=2, expected_property_version=original_version,
        multiplier_bps=13000, start_date="2026-08-01T00:00:00Z", end_date="2026-08-31T00:00:00Z"), PM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
