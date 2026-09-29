"""Read-after-write visibility of the in-request cascades, and the layered
scenarios where optimistic concurrency, version arithmetic and repetitive-loss
classification interact.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    amend_standards,
    append_record,
    assess_inspection,
    assert_ledger_aggregates,
    read_community,
    read_compliance_summary,
    read_permit,
    read_property,
    read_structure,
    register_community,
    review_permit,
    setup_parcel,
    setup_scheduled_inspection,
    setup_structure,
    start_permit,
    submit_permit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["administrator_headers"]

_BAYOU_CITY = {"name": "Bayou City", "state_code": "TX",
               "freeboard_ft": 1.5, "cumulative_period_years": 10}
_AE_PANEL = {"panel_number": "48001C0100", "suffix": "H", "flood_zone": "AE",
             "effective_date": "2020-01-01T00:00:00Z", "base_flood_elevation_ft": 12.0}
_RESIDENTIAL = {"structure_use": "RESIDENTIAL", "pre_firm": False,
                "construction_year": 1998, "market_value_usd": 200_000.00,
                "highest_adjacent_grade_ft": 10.0}


def _damage_payload(structure_id, event_date, cost_usd, claim_paid_amount_usd):
    return {
        "structure_id": structure_id,
        "record_type": "DAMAGE",
        "event_date": event_date,
        "cost_usd": cost_usd,
        "claim_paid_amount_usd": claim_paid_amount_usd,
    }


def _cases_for_structure(api, structure_id):
    cases, _meta = validate_paginated(
        api.list_determination_cases(ADMIN, params={"structure_id": structure_id})
    )
    return cases


class TestImmediateConsistency:
    """A cascade's effects are on the very next read, with nothing to settle."""

    def test_finalize_cascade_is_readable_with_no_settling_delay(self, api):
        """PRD §2.10: "Three named cascades run inside the request that triggers them, and all of their effects are visible in the same response."

        PRD §2.10: "There is no deferred or eventual processing anywhere in this service."

        PRD §3.7: "Assessment snapshots `market_value_at_inspection_usd` from the structure's `market_value_usd`, computes `damage_ratio_pct` as `damage_cost_usd` divided by that snapshot, multiplied by 100 and rounded half-up to two decimals, moves the inspection to `ASSESSED`, and stamps `assessed_at`."

        PRD §3.7: "Hop one appends a ledger record for the structure with `record_type` `DAMAGE`, `source` `DISASTER_INSPECTION`, `inspection_id` naming this inspection, `cost_usd` equal to `damage_cost_usd`, `claim_paid_amount_usd` copied from the inspection, and `event_date` equal to `disaster_event_date`."

        PRD §3.3: "A computed improvement summary is available for any structure and reports `structure_id`, the current `anchor_record_id`, the `window_start_date` and `window_end_date` of the closed anchored cumulative window — both null when no counted record exists — the `counted_record_count` of counted, non-reversed records lying inside that window, and the three aggregates `cumulative_counted_cost_usd`, `cumulative_improvement_pct`, and `single_event_improvement_pct`."

        Design: Corner/consistency model/finalize_cascade_is_readable_with_no_settling_delay
        """
        scenario = setup_scheduled_inspection(
            sweep_overrides={"declaration_code": "DR-4801",
                             "event_date": "2026-07-15T00:00:00Z",
                             "inspection_window_days": 30},
            community_overrides=dict(_BAYOU_CITY),
            panel_overrides=dict(_AE_PANEL),
            structure_overrides=dict(_RESIDENTIAL),
        )
        inspection_id = scenario["inspection"]["id"]
        structure_id = scenario["structure"]["id"]
        assessed = assess_inspection(inspection_id, 30_000.00, claim_paid_amount_usd=0)
        assert assessed["status"] == "ASSESSED"

        finalized = validate_success(api.finalize_inspection(inspection_id, ADMIN), 200)
        assert finalized["status"] == "FINALIZED"
        assert float(finalized["damage_ratio_pct"]) == 15.00

        summary = validate_success(api.get_improvement_summary(structure_id, ADMIN), 200)
        assert summary["structure_id"] == structure_id
        assert summary["counted_record_count"] == 1
        assert float(summary["cumulative_counted_cost_usd"]) == 30_000.00
        assert float(summary["cumulative_improvement_pct"]) == 15.00
        assert float(summary["single_event_improvement_pct"]) == 15.00
        assert read_structure(structure_id)["substantial_status"] == "NONE"

    def test_community_posture_is_current_on_the_read_that_follows_the_write(self, api):
        """PRD §3.8: "**Step one** produces the raw score: the severity weights of every violation belonging to any property of the community whose `status` is `OPEN`, `ORDER_ISSUED`, or `ESCALATED` — 2 points for `MINOR`, 6 for `MAJOR`, 12 for `CRITICAL` — plus 5 points for each `DEFAULTED` remediation order whose violation is still `ESCALATED` and whose violation belongs to a property of the community."

        PRD §3.8: "The tier rule is inclusive on the worse side: a score of 25 points or more is `SUSPENDED`, a score of 10 points or more is `ON_PROBATION`, and anything lower is `GOOD_STANDING`."

        PRD §3.8: "**Step three** grants a credit of 4 points, and grants it only when that provisional tier is exactly `ON_PROBATION` *and* the community holds a higher-standards submission for the enforcement activity `A510_HIGHER_STD_ENFORCEMENT` whose `documentation_status` is `VERIFIED`; in every other case the credit is 0."

        PRD §3.8: "A new violation opens with `status` `OPEN`, `opened_at` stamped from the logical clock, `sanction_points_contributed` set to its severity weight, and `version` 1."

        PRD §3.1: "A computed compliance summary is available to the `StateNfipCoordinator` and the `FloodplainAdministrator` and reports the community's enforcement and rating posture in one payload: `community_id`, the current `sanction_risk_points` and `compliance_posture`, the `counted_violation_count` of violations currently inside the counted set, the `defaulted_order_count` of defaulted orders currently carrying a penalty, the `a510_credit_applied` value actually subtracted by the probation credit rule, and the rating figures `crs_class`, `crs_credit_points_claimed`, `crs_credit_points_verified`, `freeboard_ft`, and `cumulative_period_years`."

        Design: Corner/consistency model/community_posture_is_current_on_the_read_that_follows_the_write
        """
        scenario = setup_parcel(
            community_overrides=dict(_BAYOU_CITY),
            panel_overrides=dict(_AE_PANEL),
        )
        community_id = scenario["community"]["id"]
        before = read_compliance_summary(community_id)
        assert before["sanction_risk_points"] == 0
        assert before["compliance_posture"] == "GOOD_STANDING"

        resp = api.create_violation(
            {"property_id": scenario["property"]["id"],
             "violation_type": "ELEVATION_DEFICIENT",
             "severity": "CRITICAL"},
            ADMIN,
        )
        violation = validate_success(resp, 201)
        assert violation["status"] == "OPEN"
        assert violation["sanction_points_contributed"] == 12

        after = validate_success(api.get_compliance_summary(community_id, ADMIN), 200)
        assert after["sanction_risk_points"] == 12
        assert after["compliance_posture"] == "ON_PROBATION"
        assert after["counted_violation_count"] == 1
        assert after["a510_credit_applied"] == 0
        assert read_community(community_id)["sanction_risk_points"] == 12


class TestOptimisticConcurrencyLayers:
    """The two version tokens guard the writes that supersede prior findings."""

    def test_stale_structure_version_blocks_the_determination_case(self, api):
        """PRD §2.7: "A `POST /floodplain/determination-cases` request must carry `expected_structure_version` holding the client's last observed `version` of the target `Structure`."

        PRD §2.7: "Opening a case legitimately withdraws any prior case of that structure that is still `OPEN` or `DETERMINED` and reverts the structure's `substantial_status`, so if the structure's `version` has advanced since the client read it — because a ledger record landed, because the assessed value was corrected, or because another case was determined — the create is rejected with `ERR_STALE_STRUCTURE_VERSION` (HTTP 412) rather than silently discarding a determination made against newer ledger data."

        PRD §3.7: "The new case begins with `status` `OPEN`, `trigger_source` `ADMIN`, `anchor_record_id` copied from the structure's current `anchor_record_id` (null when the structure has no counted record), `threshold_pct` 50.0, `outcome` null, and the structure's `version` incremented by one."

        Design: Corner/cross-cutting complexity layers/stale_structure_version_blocks_the_determination_case
        """
        scenario = setup_structure(
            community_overrides=dict(_BAYOU_CITY),
            panel_overrides=dict(_AE_PANEL),
            structure_overrides=dict(_RESIDENTIAL),
        )
        structure_id = scenario["structure"]["id"]
        append_record(structure_id, record_type="IMPROVEMENT",
                      event_date="2026-05-01T00:00:00Z", cost_usd=60_000.00)
        stale_version = read_structure(structure_id)["version"]
        second = append_record(structure_id, record_type="IMPROVEMENT",
                               event_date="2026-06-01T00:00:00Z", cost_usd=45_000.00)

        cases_before = _cases_for_structure(api, structure_id)
        resp = api.open_determination_case(
            {"structure_id": structure_id, "method": "CUMULATIVE",
             "expected_structure_version": stale_version},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_STRUCTURE_VERSION)
        assert len(_cases_for_structure(api, structure_id)) == len(cases_before)

        structure = read_structure(structure_id)
        assert structure["anchor_record_id"] == second["id"]
        assert float(structure["cumulative_improvement_pct"]) == 52.50
        assert structure["substantial_status"] == "NONE"

        retry = api.open_determination_case(
            {"structure_id": structure_id, "method": "CUMULATIVE",
             "expected_structure_version": structure["version"]},
            ADMIN,
        )
        case = validate_success(retry, 201)
        assert case["status"] == "OPEN"
        assert case["trigger_source"] == "ADMIN"
        assert case["anchor_record_id"] == second["id"]
        assert float(case["threshold_pct"]) == 50.0
        assert case["outcome"] is None

    def test_stale_community_version_blocks_the_credit_submission(self, api):
        """PRD §2.7: "A `POST /floodplain/higher-standards` request must carry `expected_community_version` holding the client's last observed `version` of the target `Community`."

        PRD §2.7: "If `expected_community_version` does not equal the community's current `version`, the create is rejected with `ERR_STALE_COMMUNITY_VERSION` (HTTP 412)."

        PRD §3.1: "The amendment restamps `standards_adopted_at` to the current logical clock and increments the community's `version`."

        PRD §3.9: "For `A430_FREEBOARD` the ceiling is 100 points for each foot of adopted `freeboard_ft`, counting no more than 5.0 feet, with the product truncated downward to a whole number of points — so 2.5 feet of freeboard yields 250 and 5.4 feet still yields 500."

        PRD §3.9: "A new submission has `documentation_status` `DRAFT`, `verified_points` 0, `max_points_allowed` computed from live state, `version` 1, and it increments the community's `version` by one."

        Design: Corner/cross-cutting complexity layers/stale_community_version_blocks_the_credit_submission
        """
        community = register_community(name="Bayou City", state_code="TX",
                                      freeboard_ft=1.5, cumulative_period_years=10)
        community_id = community["id"]
        stale_version = read_community(community_id)["version"]
        amend_standards(community_id, freeboard_ft=2.5)

        resp = api.draft_higher_standard(
            {"community_id": community_id, "activity_code": "A430_FREEBOARD",
             "documentation_cycle_year": 2026, "claimed_points": 150,
             "expected_community_version": stale_version},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_COMMUNITY_VERSION)

        standards, _meta = validate_paginated(
            api.list_higher_standards(ADMIN, params={"community_id": community_id})
        )
        assert standards == []

        refreshed = read_community(community_id)
        assert float(refreshed["freeboard_ft"]) == 2.5
        assert refreshed["crs_credit_points_claimed"] == 0

        retry = api.draft_higher_standard(
            {"community_id": community_id, "activity_code": "A430_FREEBOARD",
             "documentation_cycle_year": 2026, "claimed_points": 150,
             "expected_community_version": refreshed["version"]},
            ADMIN,
        )
        standard = validate_success(retry, 201)
        assert standard["documentation_status"] == "DRAFT"
        assert standard["claimed_points"] == 150
        assert standard["max_points_allowed"] == 250


class TestVersionArithmetic:
    """Every mutation moves `version` by one; reads move nothing."""

    def test_every_permit_write_advances_the_version_by_exactly_one(self, api):
        """PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increments by exactly one on every mutation, including mutations the server performs on its own initiative as part of a cascade, and including mutations that touch only computed fields such as a recomputed `sanction_risk_points` or a recomputed `cumulative_improvement_pct`."

        PRD §3.4: "A draft permit has `revision_round` 0, every determination snapshot null, and `version` 1."

        PRD §3.4: "Issuance moves the permit to `ISSUED`, stamps `issued_at` with the current logical clock, and sets `expires_at` to 365 days after `issued_at`."

        Design: Corner/cross-cutting complexity layers/every_permit_write_advances_the_version_by_exactly_one
        """
        scenario = setup_structure(
            community_overrides=dict(_BAYOU_CITY),
            panel_overrides=dict(_AE_PANEL),
            structure_overrides=dict(_RESIDENTIAL),
        )
        owner_headers = scenario["owner_headers"]
        created = start_permit(
            scenario["property"]["id"], scenario["structure"]["id"], owner_headers,
            project_type="NEW_CONSTRUCTION", declared_project_cost_usd=20_000.00,
            proposed_lowest_floor_elevation_ft=20.0,
        )
        assert created["version"] == 1

        submit_permit(created["id"], owner_headers)
        assert read_permit(created["id"])["version"] == 2

        review_permit(created["id"], "APPROVE")
        assert read_permit(created["id"])["version"] == 3

        issued = validate_success(api.issue_permit(created["id"], ADMIN), 200)
        assert issued["status"] == "ISSUED"
        assert issued["version"] == 4

        assert read_permit(created["id"])["version"] == 4
        assert read_permit(created["id"])["version"] == 4


class TestRepetitiveLossEscalationLayers:
    """The rolling ten-year window drives the property's classification."""

    def test_second_qualifying_claim_inside_the_window_trips_repetitive_loss(self, api):
        """PRD §3.9: "The qualifying set is every `DAMAGE` record, not reversed, whose `claim_paid_amount_usd` is at least 1000.00, drawn from every `Structure` whose `property_id` is this property, sorted by `event_date` ascending and then by `created_at` ascending."

        PRD §3.9: "`max_window_claim_count` is found by treating each qualifying claim in turn as an anchor, counting the qualifying claims whose `event_date` falls in the closed window from the anchor's `event_date` through 10 calendar years after it, and keeping the largest count found."

        PRD §3.9: "The classification then reads off `max_window_claim_count`: the property is `SEVERE_REPETITIVE_LOSS` when that figure is 4 or more, and also when it is 2 or more while a newest qualifying claim exists and `cumulative_claim_paid_usd` strictly exceeds that newest claim's `market_value_at_event_usd`; failing that it is `REPETITIVE_LOSS` when the figure is 2 or more; and otherwise `repetitive_loss_status` is `NONE`."

        PRD §3.6: "Whether a row counts toward cumulative tracking is recorded on the row itself as `counted_in_cumulative`, and the rule is a conjunction of three conditions: the `record_type` must be `IMPROVEMENT` or `DAMAGE`, `is_code_compliance_only` must be false, and `cost_usd` must be at least 500.00."

        Design: Corner/cross-cutting complexity layers/second_qualifying_claim_inside_the_window_trips_repetitive_loss
        """
        scenario = setup_structure(
            community_overrides=dict(_BAYOU_CITY),
            panel_overrides=dict(_AE_PANEL),
            structure_overrides=dict(_RESIDENTIAL),
        )
        structure_id = scenario["structure"]["id"]
        property_id = scenario["property"]["id"]
        append_record(structure_id, record_type="DAMAGE",
                      event_date="2019-06-01T00:00:00Z", cost_usd=400.00,
                      claim_paid_amount_usd=1500.00)
        assert read_property(property_id)["repetitive_loss_status"] == "NONE"

        resp = api.append_improvement_record(
            _damage_payload(structure_id, "2026-06-01T00:00:00Z", 400.00, 2000.00), ADMIN
        )
        validate_success(resp, 201)

        prop = read_property(property_id)
        assert prop["repetitive_loss_status"] == "REPETITIVE_LOSS"
        assert prop["qualifying_claim_count"] == 2
        assert prop["max_window_claim_count"] == 2
        assert float(prop["cumulative_claim_paid_usd"]) == 3500.00

        structure = read_structure(structure_id)
        assert_ledger_aggregates(structure, None, 0, 0.00, 0.00)

    def test_fourth_qualifying_claim_escalates_to_severe_repetitive_loss(self, api):
        """PRD §3.9: "`max_window_claim_count` is found by treating each qualifying claim in turn as an anchor, counting the qualifying claims whose `event_date` falls in the closed window from the anchor's `event_date` through 10 calendar years after it, and keeping the largest count found."

        PRD §3.9: "The classification then reads off `max_window_claim_count`: the property is `SEVERE_REPETITIVE_LOSS` when that figure is 4 or more, and also when it is 2 or more while a newest qualifying claim exists and `cumulative_claim_paid_usd` strictly exceeds that newest claim's `market_value_at_event_usd`; failing that it is `REPETITIVE_LOSS` when the figure is 2 or more; and otherwise `repetitive_loss_status` is `NONE`."

        PRD §3.9: "`qualifying_claim_count` is the size of that set and `cumulative_claim_paid_usd` is the exact sum of its `claim_paid_amount_usd` values."

        Design: Corner/cross-cutting complexity layers/fourth_qualifying_claim_escalates_to_severe_repetitive_loss
        """
        scenario = setup_structure(
            community_overrides=dict(_BAYOU_CITY),
            panel_overrides=dict(_AE_PANEL),
            structure_overrides=dict(_RESIDENTIAL),
        )
        structure_id = scenario["structure"]["id"]
        property_id = scenario["property"]["id"]
        for event_date in ("2020-01-01T00:00:00Z", "2022-01-01T00:00:00Z",
                          "2024-01-01T00:00:00Z"):
            append_record(structure_id, record_type="DAMAGE", event_date=event_date,
                          cost_usd=400.00, claim_paid_amount_usd=1000.00)
        assert read_property(property_id)["repetitive_loss_status"] == "REPETITIVE_LOSS"

        resp = api.append_improvement_record(
            _damage_payload(structure_id, "2026-01-01T00:00:00Z", 400.00, 1000.00), ADMIN
        )
        validate_success(resp, 201)

        prop = read_property(property_id)
        assert prop["repetitive_loss_status"] == "SEVERE_REPETITIVE_LOSS"
        assert prop["qualifying_claim_count"] == 4
        assert prop["max_window_claim_count"] == 4
        assert float(prop["cumulative_claim_paid_usd"]) == 4000.00
