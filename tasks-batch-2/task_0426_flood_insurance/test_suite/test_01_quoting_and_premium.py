"""Premium quoting: the two rating regimes, the combinatorial premium pipeline,
the CRS discount, the waiting-period derivation, and quote-time defaults/system
fields.

Covers difficulty queue A (dual_variant_calc, combinatorial_formula) and corner
queue B (entities/calculations sections touching the quote pipeline).
"""
from test_helpers import (
    validate_success,
    set_clock,
    create_community,
    create_property,
    create_elevation_certificate,
    quote_policy,
    quote_policy_as_underwriter,
    setup_community_property,
    assert_policy,
    assert_community,
    assert_elevation_certificate,
    make_policy_holder_headers,
    TEST_USERS,
)


def test_premium_rr2_and_legacy_diverge_on_identical_inputs(api):
    """PRD §3.4: "The two regimes will therefore produce different premiums for
    identical coverage, community, and property inputs."

    Design: Difficulty/dual_variant_calc/premium_rr2_vs_legacy_same_inputs_diverge
    """
    community = create_community(crs_class=5, participating=True)
    prop = create_property(
        community["id"], "holder-1", flood_zone="AE",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=8.0,
    )
    create_elevation_certificate(prop["id"], "holder-1", lowest_floor_elevation_ft=10.0)

    rr2 = quote_policy(
        prop["id"], "holder-1", "RISK_RATING_2_0",
        building_coverage=250000, contents_coverage=100000,
    )
    legacy = quote_policy(
        prop["id"], "holder-1", "LEGACY_SUBSIDIZED",
        building_coverage=250000, contents_coverage=100000,
    )

    assert rr2["quoted_premium"] == 676, rr2["quoted_premium"]
    assert legacy["quoted_premium"] == 1538, legacy["quoted_premium"]
    assert rr2["quoted_premium"] != legacy["quoted_premium"]


def test_premium_rr2_combines_zone_band_elevation_and_crs(api):
    """PRD §3.4: "The risk base is the building coverage multiplied by its band
    rate plus the contents coverage multiplied by the contents rate, that whole
    sum multiplied by the elevation factor, and then rounded to whole dollars."
    PRD §3.3: "On filing, the system computes `freeboard_ft` as the certificate's
    lowest-floor elevation minus the property's base flood elevation"

    Design: Difficulty/combinatorial_formula/premium_quote_zone_band_times_elevation_times_crs
    """
    community = create_community(crs_class=5, participating=True)
    prop = create_property(
        community["id"], "holder-3", flood_zone="AE",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=8.0,
    )
    cert = create_elevation_certificate(
        prop["id"], "holder-3", lowest_floor_elevation_ft=10.0
    )
    assert cert["freeboard_ft"] == 2.0, cert["freeboard_ft"]

    policy = quote_policy(
        prop["id"], "holder-3", "RISK_RATING_2_0",
        building_coverage=250000, contents_coverage=100000,
    )
    assert policy["quoted_premium"] == 676, policy["quoted_premium"]


def test_legacy_premium_uses_flat_zone_rates_ignoring_elevation(api):
    """PRD §3.4: "Under `LEGACY_SUBSIDIZED`, the elevation certificate is ignored
    entirely; the risk base is the building coverage multiplied by the legacy
    building rate for the flood zone plus the contents coverage multiplied by the
    legacy contents rate for the flood zone, rounded to whole dollars, where the
    legacy building rate is 0.0060 for `AE`, 0.0090 for `VE`, and 0.0010 for `X`,
    and the legacy contents rate is 0.0035 for `AE`, 0.0050 for `VE`, and 0.0008
    for `X`."

    Design: Difficulty/dual_variant_calc/premium_rr2_vs_legacy_same_inputs_diverge
    """
    community = create_community(crs_class=5, participating=True)
    prop = create_property(
        community["id"], "holder-leg", flood_zone="AE",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=8.0,
    )
    # An elevation certificate exists but legacy must ignore it.
    create_elevation_certificate(prop["id"], "holder-leg", lowest_floor_elevation_ft=10.0)
    legacy = quote_policy(
        prop["id"], "holder-leg", "LEGACY_SUBSIDIZED",
        building_coverage=250000, contents_coverage=100000,
    )
    assert legacy["quoted_premium"] == 1538, legacy["quoted_premium"]


def test_elevation_certificate_freeboard_is_computed(api):
    """PRD §3.3: "On filing, the system computes `freeboard_ft` as the
    certificate's lowest-floor elevation minus the property's base flood
    elevation"

    Design: Corner/entities/elevation_certificate_freeboard_computed_immutable_record
    """
    community = create_community()
    prop = create_property(
        community["id"], "h-ec", flood_zone="AE",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=8.0,
    )
    cert = create_elevation_certificate(
        prop["id"], "h-ec", lowest_floor_elevation_ft=11.5
    )
    assert_elevation_certificate(cert)
    assert cert["freeboard_ft"] == 3.5, cert["freeboard_ft"]
    # common_fields:false — immutable evidence record carries no version field.
    assert "version" not in cert
    assert "updated_at" not in cert


def test_quote_ignores_client_status_and_computes_premium(api):
    """PRD §3.4: "its `status` enters `QUOTED`, and its `quoted_premium` is
    computed immediately."

    Design: Corner/entities/policy_system_fields_ignored_on_create
    """
    community = create_community(crs_class=10)
    prop = create_property(
        community["id"], "h-sys", flood_zone="X",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=10.0,
    )
    create_elevation_certificate(prop["id"], "h-sys", lowest_floor_elevation_ft=11.0)
    resp = api.quote_policy(
        prop["id"],
        {
            "rating_method": "RISK_RATING_2_0",
            "building_coverage": 100000,
            "contents_coverage": 40000,
            "status": "ACTIVE",          # client-supplied system field, must be ignored
            "quoted_premium": 999999,    # client-supplied computed field, must be ignored
        },
        make_policy_holder_headers("h-sys"),
    )
    policy = validate_success(resp, expected_status=201)
    assert_policy(policy)
    assert policy["status"] == "QUOTED", policy["status"]
    assert policy["quoted_premium"] == 320, policy["quoted_premium"]
    assert policy["version"] == 1, policy["version"]


def test_create_community_computes_crs_discount_from_class(api):
    """PRD §3.1: "class 1 yields a discount of 0.45, class 2 yields 0.40, class 3
    yields 0.35, class 4 yields 0.30, class 5 yields 0.25, class 6 yields 0.20,
    class 7 yields 0.15, class 8 yields 0.10, class 9 yields 0.05, and class 10
    yields 0.00."

    Design: Corner/entities/create_community_returns_201_with_computed_discount
    """
    resp = api.create_community(
        {"name": "Harbor", "county_code": "C100", "participating": True, "crs_class": 3},
        TEST_USERS["fema_admin_headers"],
    )
    community = validate_success(resp, expected_status=201)
    assert_community(community)
    assert community["crs_discount_pct"] == 0.35, community["crs_discount_pct"]
    assert community["version"] == 1, community["version"]


def test_crs_class_1_yields_maximum_discount(api):
    """PRD §3.1: "class 1 yields a discount of 0.45, class 2 yields 0.40, class 3
    yields 0.35, class 4 yields 0.30, class 5 yields 0.25, class 6 yields 0.20,
    class 7 yields 0.15, class 8 yields 0.10, class 9 yields 0.05, and class 10
    yields 0.00."

    Design: Corner/calculations/crs_class_1_max_discount_applied
    """
    community = create_community(crs_class=1)
    assert community["crs_discount_pct"] == 0.45, community["crs_discount_pct"]


def test_community_defaults_class_10_and_participating(api):
    """PRD §3.1: "an optional `participating` flag (which defaults to true and
    governs whether policies may be written there), and an optional `crs_class`
    (which defaults to 10)."

    Design: Corner/entities/create_community_default_crs_class_10_zero_discount
    """
    resp = api.create_community(
        {"name": "Default Town", "county_code": "C101"},
        TEST_USERS["fema_admin_headers"],
    )
    community = validate_success(resp, expected_status=201)
    assert community["crs_class"] == 10, community["crs_class"]
    assert community["crs_discount_pct"] == 0.0, community["crs_discount_pct"]
    assert community["participating"] is True, community["participating"]


def test_lender_required_gives_zero_day_waiting_period(api):
    """PRD §3.5: "the waiting period is 0 days when the policy was written to
    satisfy a loan closing — that is, when `is_lender_required` is true — and 30
    days otherwise, so `effective_date` is the bind date plus the waiting period,
    and `expiration_date` is the effective date plus 365 days."

    Design: Corner/calculations/lender_required_zero_waiting_period_same_day_effective
    """
    community, prop, _cert = setup_community_property(
        crs_class=10, owner_id="h-l0", flood_zone="X",
        base_flood_elevation_ft=10.0, lowest_floor_elevation_ft=11.0,
    )
    set_clock("2026-03-01T00:00:00Z")
    quoted = quote_policy_as_underwriter(
        prop["id"], "RISK_RATING_2_0",
        building_coverage=100000, contents_coverage=40000, is_lender_required=True,
    )
    bound = validate_success(api.bind_policy(
        quoted["id"], TEST_USERS["underwriter_headers"]
    ))
    assert bound["effective_date"] == "2026-03-01T00:00:00.000Z", bound["effective_date"]
    assert bound["expiration_date"] == "2027-03-01T00:00:00.000Z", bound["expiration_date"]
