"""The priced formulas at their awkward points: which rows feed a total, which
constant band a figure lands in, and how a value moves with the calendar."""

from test_helpers import (
    ApiErrorId,
    UW,
    add_liability_exposure,
    add_livestock_group,
    add_scheduled_item,
    add_seasonal_item,
    assert_labor_units_two_decimals,
    bind_policy,
    bind_policy_ok,
    bootstrap_zone,
    complete_inspection_ok,
    open_account,
    open_policy,
    patch_item_ok,
    rate_policy_ok,
    read_item,
    read_ledger,
    read_policy,
    read_recommendations,
    register_inspector,
    reservation_by_peril,
    schedule_inspection_ok,
    set_clock,
    setup_draft_policy_with_dwelling,
    setup_rated_dwelling_policy,
    upsert_labor_profile,
    validate_error,
    validate_paginated,
)

COMBINE = {
    "item_class": "EQUIPMENT",
    "description": "Combine",
    "valuation_basis": "ACV",
    "stated_value_cents": 30_001_000,
    "age_years": 12,
    "condition_grade": "B",
}

CRITICAL_FINDINGS = [
    {"severity": "CRITICAL", "description": "Rewire the shop panel", "due_date": "2026-09-10"},
    {"severity": "CRITICAL", "description": "Relocate the fuel tank", "due_date": "2026-09-15"},
    {"severity": "CRITICAL", "description": "Guard the auger", "due_date": "2026-09-20"},
]


def test_a_removed_combine_keeps_its_value_but_earns_no_premium(api):
    """"Each `ACTIVE` item then contributes one line: its `insured_value_cents`
    multiplied by the property rate for its `item_class`, multiplied by the
    credit, rounded half up to a whole cent on that line." "Items whose `status`
    is `REMOVED` are excluded outright." The combine is valued at 11040368 cents
    and keeps that figure on the row, but taking it off the schedule before
    rating suppresses its whole 89427-cent line. The catastrophe base ignores it
    too: "`exposed_tiv_cents` is the sum of `insured_value_cents` over the
    `ACTIVE` scheduled items plus the sum of `covered_limit_cents` over all
    livestock groups."

    Design: Corner/calculations/corner_property_premium_ignores_removed_items
    """
    scenario = setup_draft_policy_with_dwelling()
    combine = add_scheduled_item(scenario.agent_headers, scenario.policy_id, **COMBINE)
    assert combine["insured_value_cents"] == 11_040_368

    removed = patch_item_ok(combine["id"], scenario.agent_headers, status="REMOVED")
    assert removed["status"] == "REMOVED"
    assert removed["insured_value_cents"] == 11_040_368

    rated = rate_policy_ok(scenario.policy_id)

    assert rated["property_premium_cents"] == 144_000
    assert rated["exposed_tiv_cents"] == 40_000_000
    assert rated["total_premium_cents"] == 269_200
    assert read_item(combine["id"])["insured_value_cents"] == 11_040_368

    hail = reservation_by_peril(scenario.policy_id)["HAIL"]
    assert hail["amount_cents"] == 20_000_000

    entries = read_ledger(scenario.policy_id)
    assert [(row["txn_type"], row["amount_cents"]) for row in entries] == [
        ("BASE_PROPERTY", 144_000),
        ("CAT_LOAD", 125_200),
    ]

    active, active_meta = validate_paginated(
        api.list_scheduled_items(scenario.policy_id, UW, params={"status": "ACTIVE"})
    )
    assert active_meta["total_count"] == 1
    assert [row["id"] for row in active] == [scenario.item["id"]]
    _, all_meta = validate_paginated(api.list_scheduled_items(scenario.policy_id, UW))
    assert all_meta["total_count"] == 2


def test_the_deductible_credit_bands_break_on_the_upper_edge(api):
    """"A deductible credit is selected from `deductible_cents` in four bands: a
    deductible below 100000 cents earns a credit of 1.00, below 500000 earns
    0.95, below 1000000 earns 0.90, and 1000000 or more earns 0.85." Three
    accounts carry the identical 40000000-cent dwelling, so the whole 160000-cent
    gross line differs only by the band: 99999 keeps all of it, exactly 100000
    has already lost the full credit, and 1000000 lands in the last band. The
    three policies sit on three separate accounts, so the identical terms raise
    no overlap, and "the deductible credit is not applied to the catastrophe
    load."

    Design: Corner/calculations/corner_deductible_credit_bands_at_their_edges
    """
    scenario = bootstrap_zone(with_policy=False, account_overrides={"legal_name": "Band A Farms"})
    headers = scenario.agent_headers
    accounts = [
        scenario.account,
        open_account(headers, legal_name="Band B Farms"),
        open_account(headers, legal_name="Band C Farms"),
    ]
    deductibles = [99_999, 100_000, 1_000_000]
    policies = []
    for account, deductible in zip(accounts, deductibles):
        policy = open_policy(headers, account["id"], deductible_cents=deductible)
        add_scheduled_item(headers, policy["id"])
        policies.append(policy)

    rated = [rate_policy_ok(policy["id"]) for policy in policies]

    assert [row["property_premium_cents"] for row in rated] == [160_000, 152_000, 136_000]
    assert [row["cat_load_cents"] for row in rated] == [125_200, 125_200, 125_200]
    assert [row["total_premium_cents"] for row in rated] == [285_200, 277_200, 261_200]

    utilizations = []
    for policy in policies:
        hail = reservation_by_peril(policy["id"])["HAIL"]
        assert hail["amount_cents"] == 20_000_000
        assert float(hail["scarcity_factor"]) == 1.00
        utilizations.append(float(hail["utilization_at_rating"]))
    assert utilizations == [0.100000, 0.200000, 0.300000]

    assert len({policy["account_id"] for policy in policies}) == 3
    assert {row["uw_status"] for row in rated} == {"RATED"}


def test_two_herds_price_line_by_line_under_their_own_bases(api):
    """"Each group contributes its `covered_limit_cents` multiplied by the
    species rate, multiplied by the peril-restriction factor, multiplied by the
    same deductible credit the property line used, rounded half up per group."
    A catastrophe-only cattle herd capped by head count and a named-peril sheep
    blanket at 80 percent coinsurance therefore price at 172125 and 91800, and
    both covered limits swell the catastrophe base to 73500000 — "Ninth, the
    ledger: one entry is appended per non-zero component in the fixed order
    `BASE_PROPERTY`, `BASE_LIVESTOCK`, `BASE_LIABILITY`, `CAT_LOAD`, each with
    `reason_code` `RATING`, each with a positive `amount_cents`; a component
    worth zero is skipped and consumes no `sequence_no`."

    Design: Corner/calculations/corner_livestock_premium_applies_peril_and_basis_factors
    """
    scenario = setup_draft_policy_with_dwelling()
    cattle = add_livestock_group(
        scenario.agent_headers,
        scenario.policy_id,
        species="CATTLE",
        head_count=170,
        per_head_value_cents=150_000,
        limit_basis="PER_HEAD",
        peril_scope="CATASTROPHE_ONLY",
    )
    sheep = add_livestock_group(
        scenario.agent_headers,
        scenario.policy_id,
        species="SHEEP",
        head_count=300,
        per_head_value_cents=40_000,
        limit_basis="BLANKET",
        peril_scope="NAMED_PERIL",
        blanket_limit_cents=10_000_000,
    )
    assert cattle["covered_limit_cents"] == 25_500_000
    assert sheep["covered_limit_cents"] == 8_000_000

    rated = rate_policy_ok(scenario.policy_id)

    assert rated["property_premium_cents"] == 144_000
    assert rated["livestock_premium_cents"] == 263_925
    assert rated["exposed_tiv_cents"] == 73_500_000
    assert rated["base_premium_cents"] == 407_925
    assert rated["cat_load_cents"] == 230_055
    assert rated["total_premium_cents"] == 637_980

    reservations = reservation_by_peril(scenario.policy_id)
    assert [reservations[peril]["load_cents"] for peril in ("HAIL", "WIND", "WILDFIRE")] == [
        117_600,
        46_305,
        66_150,
    ]

    entries = read_ledger(scenario.policy_id)
    assert [(row["sequence_no"], row["txn_type"], row["amount_cents"]) for row in entries] == [
        (1, "BASE_PROPERTY", 144_000),
        (2, "BASE_LIVESTOCK", 263_925),
        (3, "CAT_LOAD", 230_055),
    ]
    assert sum(row["amount_cents"] for row in entries) == 637_980


def test_three_liability_tiers_charge_acres_visitors_and_a_cap(api):
    """"A `GENERAL_FARM` exposure is priced as 25000 cents plus the account's
    `acreage` multiplied by 90 cents per acre, that acreage term rounded half up
    before it is added, and the result capped at 500000 cents." "An `AGRITOURISM`
    exposure is 60000 cents, plus a per-visitor charge of 120 cents applied only
    to visitors beyond the first 500 — that is, `annual_visitor_count` less 500,
    or zero when the count does not exceed 500 — plus `annual_receipts_cents`
    multiplied by 0.0040 rounded half up, the whole capped at 800000 cents." "A
    `ROADSIDE_STAND` exposure is 30000 cents plus `annual_receipts_cents`
    multiplied by 0.0050 rounded half up, capped at 300000 cents." The 1200-acre
    farm line, 300 charged visitors and a stand whose raw 480000 is clipped roll
    up to 545000, and "the deductible credit described in §3.7 is deliberately
    not applied to liability lines; it is a property and livestock concept only."

    Design: Corner/calculations/corner_liability_tiers_free_visitors_and_cap
    """
    scenario = setup_draft_policy_with_dwelling()
    assert scenario.account["acreage"] == 1200
    general = add_liability_exposure(
        scenario.agent_headers, scenario.policy_id, "GENERAL_FARM", annual_receipts_cents=0
    )
    agritourism = add_liability_exposure(
        scenario.agent_headers,
        scenario.policy_id,
        "AGRITOURISM",
        annual_receipts_cents=4_000_000,
        annual_visitor_count=800,
    )
    roadside = add_liability_exposure(
        scenario.agent_headers,
        scenario.policy_id,
        "ROADSIDE_STAND",
        annual_receipts_cents=90_000_000,
    )
    assert general["exposure_premium_cents"] == 133_000
    assert agritourism["exposure_premium_cents"] == 112_000
    assert roadside["exposure_premium_cents"] == 300_000

    rated = rate_policy_ok(scenario.policy_id)

    assert rated["liability_premium_cents"] == 545_000
    assert rated["property_premium_cents"] == 144_000
    assert rated["livestock_premium_cents"] == 0
    assert rated["exposed_tiv_cents"] == 40_000_000
    assert rated["cat_load_cents"] == 125_200
    assert rated["total_premium_cents"] == 814_200
    assert rated["uw_status"] == "RATED"
    assert rated["referral_reason_code"] is None

    entries = read_ledger(scenario.policy_id)
    assert [(row["txn_type"], row["amount_cents"]) for row in entries] == [
        ("BASE_PROPERTY", 144_000),
        ("BASE_LIABILITY", 545_000),
        ("CAT_LOAD", 125_200),
    ]


def test_a_loss_triggered_visit_with_three_critical_findings_stops_at_one_hundred(api):
    """"Hop one advances the inspection `SCHEDULED → COMPLETED`, stores
    `completed_at` at the current clock instant along with `findings_summary`,
    sets `recommendation_count` to the number of elements in `findings`, and
    computes `hazard_score` as the base score for the `inspection_type` plus the
    severity weight of each supplied finding, the whole capped at 100." "The base
    is 10 for an `INITIAL` visit, 5 for a `RE_INSPECTION` and 20 for a
    `LOSS_TRIGGERED` visit; the severity weights are 30 for `CRITICAL`, 12 for
    `MAJOR` and 4 for `MINOR`." A loss-triggered call with three critical
    findings therefore scores a raw 110 and reports 100. "Still in hop one, one
    recommendation row is created per element in `OPEN` status, and `sequence_no`
    continues from the highest `sequence_no` already present on this inspection: a
    first completion assigns 1 through N in array order, and a later
    re-inspection completion continues at N+1 through N+M."

    Design: Corner/calculations/corner_hazard_score_cap_binds_on_loss_triggered_inspection
    """
    scenario = setup_draft_policy_with_dwelling()
    inspector = register_inspector()
    inspection = schedule_inspection_ok(
        scenario.policy_id,
        inspector["id"],
        inspection_type="LOSS_TRIGGERED",
        scheduled_for="2026-08-16T09:00:00Z",
        duration_minutes=240,
    )
    assert inspection["inspection_type"] == "LOSS_TRIGGERED"

    completed = complete_inspection_ok(
        inspection["id"],
        inspector["id"],
        findings_summary="wiring, storage and guarding all deficient",
        findings=CRITICAL_FINDINGS,
    )

    assert completed["hazard_score"] == 100
    assert completed["recommendation_count"] == 3

    raised = read_recommendations(inspection["id"])
    assert [row["sequence_no"] for row in raised] == [1, 2, 3]
    assert [row["description"] for row in raised] == [
        finding["description"] for finding in CRITICAL_FINDINGS
    ]
    assert [row["due_date"] for row in raised] == ["2026-09-10", "2026-09-15", "2026-09-20"]
    assert {row["severity"] for row in raised} == {"CRITICAL"}
    assert {row["status"] for row in raised} == {"OPEN"}

    policy = read_policy(scenario.policy_id)
    assert policy["compliance_status"] == "RECS_OPEN"
    assert policy["uw_status"] == "DRAFT"


def test_the_migrant_weight_keeps_two_decimals_on_the_labor_score(api):
    """"From the three headcounts the system derives `labor_exposure_units`:
    `full_time_count` weighted at 1.00, plus `seasonal_count` weighted at 0.50,
    plus `migrant_h2a_count` weighted at 0.75, with the sum rounded half up to
    exactly two decimal places." Neither crew is a whole number of units — three
    guest workers add 2.25 and two add 1.50 — and both stay above the threshold.
    "A policy has at most one labor profile, and the producer maintains it as a
    whole-record upsert: the first submission creates the row, every later
    submission overwrites it in place and lifts its `version` by 1."

    Design: Corner/calculations/corner_labor_exposure_units_two_decimal_precision
    """
    scenario = bootstrap_zone()

    first = upsert_labor_profile(
        scenario.agent_headers,
        scenario.policy_id,
        full_time_count=2,
        seasonal_count=4,
        migrant_h2a_count=3,
    )
    assert_labor_units_two_decimals(first["labor_exposure_units"])
    assert float(first["labor_exposure_units"]) == 6.25
    assert first["wc_required"] is True
    assert first["coordination_status"] == "PENDING_PROOF"
    assert first["version"] == 1

    second = upsert_labor_profile(
        scenario.agent_headers,
        scenario.policy_id,
        full_time_count=3,
        seasonal_count=4,
        migrant_h2a_count=2,
    )
    assert_labor_units_two_decimals(second["labor_exposure_units"])
    assert float(second["labor_exposure_units"]) == 6.50
    assert second["wc_required"] is True
    assert second["coordination_status"] == "PENDING_PROOF"

    profiles, meta = validate_paginated(api.get_policy_labor_profile(scenario.policy_id, UW))
    assert meta["total_count"] == 1
    assert profiles[0]["id"] == first["id"]
    assert profiles[0]["version"] == 2
    assert float(profiles[0]["labor_exposure_units"]) == 6.50


def test_a_summer_hay_window_falls_back_to_the_off_peak_value_in_february(api):
    """"When `peak_season_start_month` is less than or equal to
    `peak_season_end_month`, the item is in peak exactly when the valuation month
    lies at or after the start month and at or before the end month." August sits
    inside a June-to-September window, so the baled alfalfa is insured at its
    peak 8280000; read again in February the same row is worth its off-peak
    2760000, because "every such amendment re-derives the item's insured value,
    restamps `valued_at`, and lifts the item's `version` by 1."

    Design: Corner/calculations/corner_forward_season_window_switches_value_by_month
    """
    scenario = bootstrap_zone()
    hay = add_seasonal_item(
        scenario.agent_headers,
        scenario.policy_id,
        item_class="HAY",
        description="Baled alfalfa",
        stated_value_cents=2_760_000,
        peak_season_value_cents=8_280_000,
        peak_season_start_month=6,
        peak_season_end_month=9,
    )
    assert hay["insured_value_cents"] == 8_280_000
    assert hay["valued_at"].startswith("2026-08-15T00:00:00")
    assert hay["stated_value_cents"] == 2_760_000

    set_clock("2026-02-01T00:00:00Z")
    off_peak = patch_item_ok(
        hay["id"],
        scenario.agent_headers,
        peak_season_value_cents=8_280_000,
        peak_season_start_month=6,
        peak_season_end_month=9,
    )

    assert off_peak["insured_value_cents"] == 2_760_000
    assert off_peak["valued_at"].startswith("2026-02-01T00:00:00")
    assert off_peak["stated_value_cents"] == 2_760_000
    assert off_peak["peak_season_value_cents"] == 8_280_000
    assert off_peak["version"] == 2


def test_the_expiry_instant_itself_still_binds(api):
    """"If no trigger matches, the policy advances `DRAFT → RATED`,
    `quote_expires_at` is set to `rating_valuation_date` plus 30 days as exact
    instant arithmetic, and `referred_at`, `referred_by_user_id` and
    `referral_reason_code` are cleared." "The current clock instant must be on or
    before `quote_expires_at`, or `ERR_QUOTE_EXPIRED`; the expiry instant itself
    is still bindable, so the first non-bindable moment is one second later." One
    second past midnight on 2026-09-14 the bind is refused and the reservations
    stay merely reserved; wound back to the instant itself, the very same quote
    binds.

    Design: Corner/calculations/corner_quote_expiry_instant_is_still_bindable
    """
    scenario = setup_rated_dwelling_policy()
    rated = read_policy(scenario.policy_id)
    assert rated["rating_valuation_date"].startswith("2026-08-15T00:00:00")
    assert rated["quote_expires_at"].startswith("2026-09-14T00:00:00")

    set_clock("2026-09-14T00:00:01Z")
    response = bind_policy(scenario.policy_id)

    validate_error(response, ApiErrorId.ERR_QUOTE_EXPIRED.value, 409)
    refused = read_policy(scenario.policy_id)
    assert refused["uw_status"] == "RATED"
    assert refused["version"] == rated["version"]
    assert refused["bound_at"] is None
    assert {row["status"] for row in reservation_by_peril(scenario.policy_id).values()} == {
        "RESERVED"
    }

    set_clock("2026-09-14T00:00:00Z")
    bound = bind_policy_ok(scenario.policy_id)

    assert bound["uw_status"] == "BOUND"
    assert bound["bound_at"].startswith("2026-09-14T00:00:00")
    assert bound["total_premium_cents"] == 269_200
    assert bound["version"] == rated["version"] + 1
    assert {row["status"] for row in reservation_by_peril(scenario.policy_id).values()} == {
        "COMMITTED"
    }
