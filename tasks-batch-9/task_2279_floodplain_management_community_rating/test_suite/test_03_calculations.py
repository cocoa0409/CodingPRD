"""Derived-value arithmetic: the cumulative improvement ledger, datum
normalization, repetitive-loss classification, outreach coverage and the CRS
activity ceilings.

Every expected figure below is the one the PRD's formulas produce.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    analyze_area,
    append_record,
    assert_calendar_years_after,
    assert_ledger_aggregates,
    assert_one_decimal_place,
    assert_two_decimal_places,
    delineate_area,
    designate_area,
    draft_standard,
    launch_outreach,
    open_cycle,
    read_area,
    read_community,
    read_property,
    read_standard,
    read_structure,
    register_community,
    setup_issued_permit,
    setup_parcel,
    setup_structure,
    submit_standard,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["administrator_headers"]
COORD = TEST_USERS["coordinator_headers"]

# The adopted standards the ledger and elevation scenarios below run against.
_BAYOU_CITY = {"name": "Bayou City", "state_code": "TX",
               "freeboard_ft": 1.5, "cumulative_period_years": 10}
_AE_PANEL = {"panel_number": "48001C0100", "suffix": "H", "flood_zone": "AE",
             "effective_date": "2020-01-01T00:00:00Z", "base_flood_elevation_ft": 12.0}
_RESIDENTIAL = {"structure_use": "RESIDENTIAL", "pre_firm": False,
                "construction_year": 1998, "market_value_usd": 200_000.00,
                "highest_adjacent_grade_ft": 10.0}


def _record_payload(structure_id, record_type, event_date, cost_usd, **extra):
    payload = {
        "structure_id": structure_id,
        "record_type": record_type,
        "event_date": event_date,
        "cost_usd": cost_usd,
    }
    payload.update(extra)
    return payload


class TestImprovementLedgerAggregates:
    """The candidate set, the anchor, the closed window and the two ratios."""

    def test_zero_cumulative_period_collapses_the_window_to_the_anchor_day(self, api):
        """PRD §3.6: "When `cumulative_period_years` is 0 the window collapses to the anchor's single date, and only records sharing the anchor's exact `event_date` are summed."

        PRD §3.6: "`cumulative_counted_cost_usd` is the exact sum of `cost_usd` over the candidates inside that window."

        PRD §3.6: "`cumulative_improvement_pct` is that windowed sum divided by the denominator, multiplied by 100, rounded half-up to two decimals; `single_event_improvement_pct` is the anchor's own `cost_usd` divided by the same denominator, multiplied by 100, rounded half-up to two decimals."

        PRD §3.6: "Whether a row counts toward cumulative tracking is recorded on the row itself as `counted_in_cumulative`, and the rule is a conjunction of three conditions: the `record_type` must be `IMPROVEMENT` or `DAMAGE`, `is_code_compliance_only` must be false, and `cost_usd` must be at least 500.00."

        Design: Corner/calculations/zero_cumulative_period_collapses_the_window_to_the_anchor_day
        """
        scenario = setup_structure(
            community_overrides={"name": "Zero Window City", "state_code": "TX",
                                 "freeboard_ft": 1.5, "cumulative_period_years": 0},
            panel_overrides=dict(_AE_PANEL),
            structure_overrides=dict(_RESIDENTIAL),
        )
        structure_id = scenario["structure"]["id"]
        older = append_record(structure_id, record_type="IMPROVEMENT",
                              event_date="2026-03-01T00:00:00Z", cost_usd=40_000.00)

        resp = api.append_improvement_record(
            _record_payload(structure_id, "IMPROVEMENT", "2026-06-01T00:00:00Z", 60_000.00),
            ADMIN,
        )
        newer = validate_success(resp, 201)

        assert newer["counted_in_cumulative"] is True
        older_now = validate_success(api.get_improvement_record(older["id"], ADMIN), 200)
        assert older_now["counted_in_cumulative"] is True

        structure = read_structure(structure_id)
        assert_ledger_aggregates(structure, newer["id"], 60_000.00, 30.00, 30.00)
        assert_two_decimal_places(structure["cumulative_improvement_pct"],
                                  "cumulative_improvement_pct")
        assert_two_decimal_places(structure["single_event_improvement_pct"],
                                  "single_event_improvement_pct")
        assert structure["substantial_status"] == "NONE"

    def test_code_compliance_only_record_is_excluded_from_the_ledger(self, api):
        """PRD §3.6: "Whether a row counts toward cumulative tracking is recorded on the row itself as `counted_in_cumulative`, and the rule is a conjunction of three conditions: the `record_type` must be `IMPROVEMENT` or `DAMAGE`, `is_code_compliance_only` must be false, and `cost_usd` must be at least 500.00."

        PRD §3.6: "The candidate set is every record of the structure whose `counted_in_cumulative` is true and whose `reversed` is false."

        PRD §3.6: "Otherwise the **anchor** is chosen as the candidate with the latest `event_date`, breaking ties by the latest `created_at` — `created_at` is the only sanctioned tiebreaker and `id` is never used for ordering — and its identifier is written to the structure's `anchor_record_id`."

        Design: Corner/calculations/code_compliance_only_record_is_excluded_from_the_ledger
        """
        scenario = setup_structure(
            community_overrides=dict(_BAYOU_CITY),
            panel_overrides=dict(_AE_PANEL),
            structure_overrides=dict(_RESIDENTIAL),
        )
        structure_id = scenario["structure"]["id"]
        counted = append_record(structure_id, record_type="IMPROVEMENT",
                               event_date="2026-03-01T00:00:00Z", cost_usd=60_000.00)

        resp = api.append_improvement_record(
            _record_payload(structure_id, "IMPROVEMENT", "2026-06-01T00:00:00Z", 150_000.00,
                            is_code_compliance_only=True),
            ADMIN,
        )
        code_only = validate_success(resp, 201)

        assert code_only["counted_in_cumulative"] is False
        assert float(code_only["cost_usd"]) == 150_000.00

        structure = read_structure(structure_id)
        assert_ledger_aggregates(structure, counted["id"], 60_000.00, 30.00, 30.00)
        assert structure["substantial_status"] == "NONE"

    def test_anchor_is_the_latest_event_date_regardless_of_creation_order(self, api):
        """PRD §3.6: "Otherwise the **anchor** is chosen as the candidate with the latest `event_date`, breaking ties by the latest `created_at` — `created_at` is the only sanctioned tiebreaker and `id` is never used for ordering — and its identifier is written to the structure's `anchor_record_id`."

        PRD §3.6: "The **cumulative window** is closed on both ends: it starts at the anchor's `event_date` minus the community's `cumulative_period_years` counted in whole calendar years (with 29 February clamped to 28 February) and ends at the anchor's `event_date` itself, so a record dated exactly on either endpoint is inside the window."

        PRD §3.6: "`cumulative_improvement_pct` is that windowed sum divided by the denominator, multiplied by 100, rounded half-up to two decimals; `single_event_improvement_pct` is the anchor's own `cost_usd` divided by the same denominator, multiplied by 100, rounded half-up to two decimals."

        Design: Corner/calculations/anchor_is_the_latest_event_date_regardless_of_creation_order
        """
        scenario = setup_structure(
            community_overrides=dict(_BAYOU_CITY),
            panel_overrides=dict(_AE_PANEL),
            structure_overrides=dict(_RESIDENTIAL),
        )
        structure_id = scenario["structure"]["id"]
        later_dated = append_record(structure_id, record_type="IMPROVEMENT",
                                    event_date="2026-06-01T00:00:00Z", cost_usd=20_000.00)

        resp = api.append_improvement_record(
            _record_payload(structure_id, "IMPROVEMENT", "2026-01-01T00:00:00Z", 60_000.00),
            ADMIN,
        )
        validate_success(resp, 201)

        structure = read_structure(structure_id)
        assert_ledger_aggregates(structure, later_dated["id"], 80_000.00, 40.00, 10.00)
        assert_two_decimal_places(structure["cumulative_improvement_pct"],
                                  "cumulative_improvement_pct")
        assert_two_decimal_places(structure["single_event_improvement_pct"],
                                  "single_event_improvement_pct")

    def test_market_value_correction_does_not_rewrite_historical_snapshots(self, api):
        """PRD §3.3: "The correction replaces the value and increments the structure's `version`, and it re-runs the ledger aggregates against the existing records."

        PRD §3.3: "Crucially, the per-record `market_value_at_event_usd` snapshots on past ledger rows are *not* rewritten, so a value correction changes which ratio a *future* record produces without retroactively rewriting the denominator of a past one."

        PRD §3.6: "The shared denominator for both ratios is the anchor's `market_value_at_event_usd`."

        Design: Corner/calculations/market_value_correction_does_not_rewrite_historical_snapshots
        """
        scenario = setup_structure(
            community_overrides=dict(_BAYOU_CITY),
            panel_overrides=dict(_AE_PANEL),
            structure_overrides=dict(_RESIDENTIAL),
        )
        structure_id = scenario["structure"]["id"]
        record = append_record(structure_id, record_type="IMPROVEMENT",
                               event_date="2026-03-01T00:00:00Z", cost_usd=60_000.00)

        resp = api.correct_structure_market_value(
            structure_id, {"market_value_usd": 100_000.00}, ADMIN
        )
        structure = validate_success(resp, 200)

        assert float(structure["market_value_usd"]) == 100_000.00
        record_now = validate_success(api.get_improvement_record(record["id"], ADMIN), 200)
        assert float(record_now["market_value_at_event_usd"]) == 200_000.00
        assert_ledger_aggregates(structure, record["id"], 60_000.00, 30.00, 30.00)
        assert structure["substantial_status"] == "NONE"


class TestCertificateDatumNormalization:
    """The offset is applied and rounded before the requirement is subtracted."""

    def test_ngvd29_offset_is_rounded_before_the_margin_is_taken(self, api):
        """PRD §3.5: "The datum offset is added to `measured_lowest_floor_ft` first — the offset is 0.0 feet for `NAVD88` and negative 0.85 feet for `NGVD29` — and that sum is rounded half-up to one decimal place to yield `normalized_lowest_floor_ft`."

        PRD §3.5: "The permit's current `required_lowest_floor_elevation_ft` is then subtracted from that already-rounded normalized value, and the difference is rounded half-up to one decimal place again to yield `freeboard_margin_ft`."

        PRD §3.5: "Rounding twice is deliberate: the margin is always a single-decimal number derived from a single-decimal normalized elevation, never from the raw measurement."

        PRD §3.5: "A new certificate begins with `status` `SUBMITTED`, an empty `deficiency_codes` list, and `version` 1."

        PRD §3.3: "A new structure has `lowest_floor_elevation_ft` null, `substantial_status` `NONE`, `anchor_record_id` null, `cumulative_counted_cost_usd`, `cumulative_improvement_pct` and `single_event_improvement_pct` all 0, and `version` 1."

        Design: Corner/calculations/ngvd29_offset_is_rounded_before_the_margin_is_taken
        """
        scenario = setup_issued_permit(
            permit_overrides={"project_type": "NEW_CONSTRUCTION",
                              "declared_project_cost_usd": 20_000.00,
                              "proposed_lowest_floor_elevation_ft": 20.0},
            community_overrides=dict(_BAYOU_CITY),
            panel_overrides=dict(_AE_PANEL),
            structure_overrides=dict(_RESIDENTIAL),
        )
        permit = scenario["permit"]
        structure_id = scenario["structure"]["id"]
        assert float(permit["required_lowest_floor_elevation_ft"]) == 13.5

        resp = api.file_certificate(
            {
                "permit_id": permit["id"],
                "structure_id": structure_id,
                "certificate_type": "FINISHED_CONSTRUCTION",
                "datum": "NGVD29",
                "measured_lowest_floor_ft": 15.0,
                "measured_bfe_ft": 12.85,
                "surveyor_license_no": "TX-5511",
            },
            scenario["owner_headers"],
        )
        certificate = validate_success(resp, 201)

        assert certificate["status"] == "SUBMITTED"
        assert float(certificate["measured_lowest_floor_ft"]) == 15.00
        assert float(certificate["normalized_lowest_floor_ft"]) == 14.2
        assert float(certificate["freeboard_margin_ft"]) == 0.7
        assert_one_decimal_place(certificate["normalized_lowest_floor_ft"],
                                 "normalized_lowest_floor_ft")
        assert_one_decimal_place(certificate["freeboard_margin_ft"], "freeboard_margin_ft")
        assert read_structure(structure_id)["lowest_floor_elevation_ft"] is None


class TestRepetitiveLossClassification:
    """The qualifying set, the ten-year rolling window and the severity tests."""

    def test_repetitive_loss_ignores_a_claim_one_cent_below_the_minimum(self, api):
        """PRD §3.9: "The qualifying set is every `DAMAGE` record, not reversed, whose `claim_paid_amount_usd` is at least 1000.00, drawn from every `Structure` whose `property_id` is this property, sorted by `event_date` ascending and then by `created_at` ascending."

        PRD §3.9: "`qualifying_claim_count` is the size of that set and `cumulative_claim_paid_usd` is the exact sum of its `claim_paid_amount_usd` values."

        PRD §3.9: "The classification then reads off `max_window_claim_count`: the property is `SEVERE_REPETITIVE_LOSS` when that figure is 4 or more, and also when it is 2 or more while a newest qualifying claim exists and `cumulative_claim_paid_usd` strictly exceeds that newest claim's `market_value_at_event_usd`; failing that it is `REPETITIVE_LOSS` when the figure is 2 or more; and otherwise `repetitive_loss_status` is `NONE`."

        Design: Corner/calculations/repetitive_loss_ignores_a_claim_one_cent_below_the_minimum
        """
        scenario = setup_structure(
            community_overrides=dict(_BAYOU_CITY),
            panel_overrides=dict(_AE_PANEL),
            structure_overrides=dict(_RESIDENTIAL),
        )
        structure_id = scenario["structure"]["id"]
        property_id = scenario["property"]["id"]
        append_record(structure_id, record_type="DAMAGE",
                      event_date="2020-05-01T00:00:00Z", cost_usd=0,
                      claim_paid_amount_usd=1500.00)

        resp = api.append_improvement_record(
            _record_payload(structure_id, "DAMAGE", "2021-05-01T00:00:00Z", 0,
                            claim_paid_amount_usd=999.99),
            ADMIN,
        )
        small = validate_success(resp, 201)

        assert float(small["claim_paid_amount_usd"]) == 999.99
        assert small["counted_in_cumulative"] is False

        prop = read_property(property_id)
        assert prop["qualifying_claim_count"] == 1
        assert float(prop["cumulative_claim_paid_usd"]) == 1500.00
        assert prop["max_window_claim_count"] == 1
        assert prop["repetitive_loss_status"] == "NONE"

    def test_repetitive_loss_window_excludes_a_claim_one_day_past_ten_years(self, api):
        """PRD §3.9: "`max_window_claim_count` is found by treating each qualifying claim in turn as an anchor, counting the qualifying claims whose `event_date` falls in the closed window from the anchor's `event_date` through 10 calendar years after it, and keeping the largest count found."

        PRD §3.9: "The classification then reads off `max_window_claim_count`: the property is `SEVERE_REPETITIVE_LOSS` when that figure is 4 or more, and also when it is 2 or more while a newest qualifying claim exists and `cumulative_claim_paid_usd` strictly exceeds that newest claim's `market_value_at_event_usd`; failing that it is `REPETITIVE_LOSS` when the figure is 2 or more; and otherwise `repetitive_loss_status` is `NONE`."

        Design: Corner/calculations/repetitive_loss_window_excludes_a_claim_one_day_past_ten_years
        """
        panel = dict(_AE_PANEL)
        panel["effective_date"] = "2015-01-01T00:00:00Z"
        scenario = setup_structure(
            community_overrides=dict(_BAYOU_CITY),
            panel_overrides=panel,
            structure_overrides=dict(_RESIDENTIAL),
        )
        structure_id = scenario["structure"]["id"]
        property_id = scenario["property"]["id"]
        append_record(structure_id, record_type="DAMAGE",
                      event_date="2016-01-01T00:00:00Z", cost_usd=0,
                      claim_paid_amount_usd=2000.00)

        resp = api.append_improvement_record(
            _record_payload(structure_id, "DAMAGE", "2026-01-02T00:00:00Z", 0,
                            claim_paid_amount_usd=2000.00),
            ADMIN,
        )
        validate_success(resp, 201)

        prop = read_property(property_id)
        assert prop["qualifying_claim_count"] == 2
        assert float(prop["cumulative_claim_paid_usd"]) == 4000.00
        assert prop["max_window_claim_count"] == 1
        assert prop["repetitive_loss_status"] == "NONE"

    def test_severe_repetitive_loss_reached_by_value_not_by_claim_count(self, api):
        """PRD §3.9: "The classification then reads off `max_window_claim_count`: the property is `SEVERE_REPETITIVE_LOSS` when that figure is 4 or more, and also when it is 2 or more while a newest qualifying claim exists and `cumulative_claim_paid_usd` strictly exceeds that newest claim's `market_value_at_event_usd`; failing that it is `REPETITIVE_LOSS` when the figure is 2 or more; and otherwise `repetitive_loss_status` is `NONE`."

        PRD §3.6: "The record also carries `cost_usd`, the cost of the work or the damage; `market_value_at_event_usd`, a snapshot of the structure's `market_value_usd` taken at record creation, which is the denominator of both ratio methods; `claim_paid_amount_usd`, the NFIP claim paid for the event, defaulting to 0; and the optional `is_code_compliance_only` flag, defaulting to false, which marks work required solely to correct previously cited health and safety code violations."

        Design: Corner/calculations/severe_repetitive_loss_reached_by_value_not_by_claim_count
        """
        scenario = setup_structure(
            community_overrides=dict(_BAYOU_CITY),
            panel_overrides=dict(_AE_PANEL),
            structure_overrides=dict(_RESIDENTIAL),
        )
        structure_id = scenario["structure"]["id"]
        property_id = scenario["property"]["id"]
        append_record(structure_id, record_type="DAMAGE",
                      event_date="2024-01-01T00:00:00Z", cost_usd=0,
                      claim_paid_amount_usd=150_000.00)

        resp = api.append_improvement_record(
            _record_payload(structure_id, "DAMAGE", "2025-01-01T00:00:00Z", 0,
                            claim_paid_amount_usd=150_000.00),
            ADMIN,
        )
        newest = validate_success(resp, 201)

        assert float(newest["market_value_at_event_usd"]) == 200_000.00
        prop = read_property(property_id)
        assert prop["qualifying_claim_count"] == 2
        assert prop["max_window_claim_count"] == 2
        assert float(prop["cumulative_claim_paid_usd"]) == 300_000.00
        assert prop["repetitive_loss_status"] == "SEVERE_REPETITIVE_LOSS"


class TestOutreachCoverage:
    """Coverage is rounded per area at delivery time."""

    def test_outreach_coverage_rounds_one_of_three_to_two_decimals(self, api):
        """PRD §3.9: "`coverage_pct` is then recomputed as 0.00 when `target_property_count` is 0, and otherwise as `delivered_count` divided by `target_property_count`, multiplied by 100, rounded half-up to two decimal places."

        PRD §3.9: "The increment is added to `delivered_count`, and a total that would exceed `target_property_count` is rejected with `ERR_DELIVERY_EXCEEDS_TARGET`."

        PRD §3.9: "A launch moves `outreach_status` to `IN_PROGRESS`, resets `delivered_count` to 0 and `coverage_pct` to 0, and snapshots `target_property_count` from the payload together with `outreach_crs_cycle_id` and `outreach_cycle_year` from the referenced cycle."

        Design: Corner/calculations/outreach_coverage_rounds_one_of_three_to_two_decimals
        """
        scenario = setup_parcel(
            community_overrides=dict(_BAYOU_CITY),
            panel_overrides=dict(_AE_PANEL),
            property_overrides={"mapped_area_code": "RLA-1"},
        )
        area = delineate_area(scenario["community"]["id"], area_code="RLA-1",
                             boundary_description="Bayou bend north bank")
        analyze_area(area["id"])
        designate_area(area["id"])
        cycle = open_cycle(scenario["community"]["id"], cycle_year=2026,
                           cycle_start_date="2026-01-01T00:00:00Z",
                           cycle_end_date="2026-12-31T00:00:00Z",
                           due_at="2027-03-01T00:00:00Z")
        launch_outreach(area["id"], cycle["id"], 3)

        resp = api.record_outreach_delivery(area["id"], {"delivered_increment": 1}, ADMIN)
        updated = validate_success(resp, 200)

        assert updated["delivered_count"] == 1
        assert float(updated["coverage_pct"]) == 33.33
        assert_two_decimal_places(updated["coverage_pct"], "coverage_pct")
        assert updated["outreach_status"] == "IN_PROGRESS"
        assert updated["property_count"] == 1
        assert read_area(area["id"])["coverage_pct"] == updated["coverage_pct"]


class TestHigherStandardCeilings:
    """Each activity's ceiling is recomputed from live state at verification."""

    def test_a420_open_space_credit_is_capped_at_two_hundred_points(self, api):
        """PRD §3.9: "For `A420_OPEN_SPACE` the ceiling is 50 points for each `DESIGNATED` repetitive loss area of the community, capped at 200 points however many areas exist."

        PRD §3.9: "Otherwise `verified_points` becomes the smaller of `claimed_points` and `max_points_allowed`, `documentation_status` becomes `VERIFIED`, `verified_at` is stamped, `doc_expires_at` is set to 5 calendar years after `verified_at`, and the community's `crs_credit_points_verified` is recomputed as the sum of `verified_points` over submissions whose `documentation_status` is `VERIFIED`."

        Design: Corner/calculations/a420_open_space_credit_is_capped_at_two_hundred_points
        """
        community = register_community(name="Open Space City", state_code="TX",
                                      freeboard_ft=1.5, cumulative_period_years=10)
        for index in range(1, 6):
            area = delineate_area(community["id"], area_code=f"RLA-{index}",
                                  boundary_description=f"Reach {index}")
            analyze_area(area["id"])
            designated = designate_area(area["id"])
            assert designated["status"] == "DESIGNATED"

        standard = draft_standard(community["id"], activity_code="A420_OPEN_SPACE",
                                  documentation_cycle_year=2026, claimed_points=250)
        submit_standard(standard["id"])

        resp = api.verify_higher_standard(standard["id"], {"decision": "VERIFY"}, COORD)
        verified = validate_success(resp, 200)

        assert verified["documentation_status"] == "VERIFIED"
        assert verified["claimed_points"] == 250
        assert verified["max_points_allowed"] == 200
        assert verified["verified_points"] == 200
        assert read_community(community["id"])["crs_credit_points_verified"] == 200

    def test_a430_freeboard_credit_is_one_hundred_points_per_adopted_foot(self, api):
        """PRD §3.9: "For `A430_FREEBOARD` the ceiling is 100 points for each foot of adopted `freeboard_ft`, counting no more than 5.0 feet, with the product truncated downward to a whole number of points — so 2.5 feet of freeboard yields 250 and 5.4 feet still yields 500."

        PRD §3.9: "Otherwise `verified_points` becomes the smaller of `claimed_points` and `max_points_allowed`, `documentation_status` becomes `VERIFIED`, `verified_at` is stamped, `doc_expires_at` is set to 5 calendar years after `verified_at`, and the community's `crs_credit_points_verified` is recomputed as the sum of `verified_points` over submissions whose `documentation_status` is `VERIFIED`."

        PRD §2.5: "A verified standard's `doc_expires_at` is its `verified_at` plus 5 calendar years."

        Design: Corner/calculations/a430_freeboard_credit_is_one_hundred_points_per_adopted_foot
        """
        community = register_community(name="Bayou City", state_code="TX",
                                      freeboard_ft=1.5, cumulative_period_years=10)
        standard = draft_standard(community["id"], activity_code="A430_FREEBOARD",
                                  documentation_cycle_year=2026, claimed_points=200)
        submit_standard(standard["id"])

        resp = api.verify_higher_standard(standard["id"], {"decision": "VERIFY"}, COORD)
        verified = validate_success(resp, 200)

        assert verified["documentation_status"] == "VERIFIED"
        assert verified["max_points_allowed"] == 150
        assert verified["verified_points"] == 150
        assert verified["claimed_points"] == 200
        assert_calendar_years_after(verified["doc_expires_at"], verified["verified_at"], 5,
                                    "doc_expires_at")
        assert verified["doc_expires_at"].startswith("2031-08-01")
        assert read_community(community["id"])["crs_credit_points_verified"] == 150

    def test_a430_cumulative_si_verification_rejected_below_ten_year_lookback(self, api):
        """PRD §3.9: "For `A430_CUMULATIVE_SI` the ceiling is 90 points when the community's `cumulative_period_years` is at least 10, and 0 otherwise."

        PRD §3.9: "`VERIFY` first recomputes `max_points_allowed`, and refuses with `ERR_STANDARD_PREREQUISITE_NOT_MET` when that ceiling is 0 — the live community, area, and violation state must actually support the activity."

        Design: Corner/calculations/a430_cumulative_si_verification_rejected_below_ten_year_lookback
        """
        community = register_community(name="Short Lookback City", state_code="TX",
                                      freeboard_ft=1.0, cumulative_period_years=5)
        standard = draft_standard(community["id"], activity_code="A430_CUMULATIVE_SI",
                                  documentation_cycle_year=2026, claimed_points=90)
        submit_standard(standard["id"])

        resp = api.verify_higher_standard(standard["id"], {"decision": "VERIFY"}, COORD)
        validate_error(resp, ApiErrorId.ERR_STANDARD_PREREQUISITE_NOT_MET)

        unchanged = read_standard(standard["id"])
        assert unchanged["documentation_status"] == "SUBMITTED"
        assert unchanged["max_points_allowed"] == 0
        assert unchanged["verified_points"] == 0
        assert read_community(community["id"])["crs_credit_points_verified"] == 0
