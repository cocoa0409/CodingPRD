"""Transitive cascades: one triggering write, every downstream hop the PRD names.

Three named cascades run inside the request that triggers them, and all of their
effects are visible in the same response.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    assess_inspection,
    file_panel,
    issue_order,
    issue_violation,
    open_cycle,
    review_permit,
    run_sweep,
    set_clock,
    setup_accepted_certificate,
    setup_approved_permit,
    setup_issued_permit,
    start_permit,
    submit_permit,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["administrator_headers"]
COORD = TEST_USERS["coordinator_headers"]


# ==========================================================================
# Scenario builders
# ==========================================================================

def _assessed_inspection_over_approved_permit() -> dict:
    """Community freeboard 1.5 on an EFFECTIVE AE panel with base flood elevation
    12.0, one RESIDENTIAL structure worth 200000.00 and an empty ledger, an
    APPROVED permit proposed at 13.5 ft, and one inspection of the DR-4700-TX
    sweep assessed at 120000.00 of damage with no claim paid."""
    scenario = setup_approved_permit(
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 60_000.00,
            "proposed_lowest_floor_elevation_ft": 13.5,
        },
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={
            "structure_use": "RESIDENTIAL",
            "pre_firm": False,
            "construction_year": 1988,
            "market_value_usd": 200_000.00,
            "highest_adjacent_grade_ft": 10.0,
        },
    )
    sweep = run_sweep(
        scenario["community"]["id"],
        declaration_code="DR-4700-TX",
        event_date="2026-07-01T00:00:00Z",
        inspection_window_days=45,
    )
    assert sweep["inspections_created"] == 1
    scenario["inspection"] = assess_inspection(
        sweep["inspection_ids"][0], 120_000.00, claim_paid_amount_usd=0
    )
    return scenario


def _defaulting_order_over_issued_permit() -> dict:
    """An ISSUED permit and an OPEN 2026 cycle in a community carrying two
    CRITICAL violations (24 raw points, ON_PROBATION); the second violation names
    the permit and the structure and carries an ISSUED remediation order whose
    deadline the clock has passed."""
    scenario = setup_issued_permit(
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 150_000.00,
            "proposed_lowest_floor_elevation_ft": 20.0,
        },
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={
            "structure_use": "RESIDENTIAL",
            "pre_firm": False,
            "construction_year": 2010,
            "market_value_usd": 400_000.00,
            "highest_adjacent_grade_ft": 10.0,
        },
    )
    scenario["cycle"] = open_cycle(
        scenario["community"]["id"],
        cycle_year=2026,
        cycle_start_date="2026-01-01T00:00:00Z",
        cycle_end_date="2026-12-31T00:00:00Z",
        due_at="2026-09-30T00:00:00Z",
    )
    scenario["violation_one"] = issue_violation(
        scenario["property"]["id"], violation_type="UNPERMITTED_FILL", severity="CRITICAL"
    )
    scenario["violation_two"] = issue_violation(
        scenario["property"]["id"],
        structure_id=scenario["structure"]["id"],
        permit_id=scenario["permit"]["id"],
        violation_type="ELEVATION_DEFICIENT",
        severity="CRITICAL",
    )
    scenario["order"] = issue_order(
        scenario["violation_two"]["id"],
        "2026-08-10T00:00:00Z",
        required_action="Elevate lowest floor to 13.5 ft NAVD88",
    )
    set_clock("2026-08-11T00:00:00Z")
    return scenario


def _pending_map_revision() -> dict:
    """Panel 48001C0100 suffix H (AE, base flood elevation 12.0) EFFECTIVE over one
    parcel whose structure is COMPLIANT at 13.5 ft on an ACCEPTED finished
    construction certificate filed against an ISSUED permit, a second IMPROVEMENT
    permit APPROVED with a frozen base flood elevation of 12.0, and panel suffix J
    (AE, base flood elevation 14.0) still PENDING_REVISION."""
    scenario = setup_accepted_certificate(
        certificate_overrides={
            "certificate_type": "FINISHED_CONSTRUCTION",
            "datum": "NAVD88",
            "measured_lowest_floor_ft": 13.5,
            "measured_bfe_ft": 12.0,
            "surveyor_license_no": "TX-RPLS-4471",
        },
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 160_000.00,
            "proposed_lowest_floor_elevation_ft": 20.0,
        },
        community_overrides={"freeboard_ft": 1.5, "cumulative_period_years": 10},
        structure_overrides={
            "structure_use": "RESIDENTIAL",
            "pre_firm": False,
            "construction_year": 2024,
            "market_value_usd": 200_000.00,
            "highest_adjacent_grade_ft": 10.0,
        },
    )
    scenario["issued_permit"] = scenario["permit"]
    second = start_permit(
        scenario["property"]["id"],
        scenario["structure"]["id"],
        scenario["owner_headers"],
        project_type="IMPROVEMENT",
        declared_project_cost_usd=50_000.00,
        proposed_lowest_floor_elevation_ft=20.0,
    )
    submit_permit(second["id"], scenario["owner_headers"])
    scenario["approved_permit"] = review_permit(second["id"], "APPROVE")
    scenario["new_panel"] = file_panel(
        scenario["community"]["id"],
        suffix="J",
        flood_zone="AE",
        effective_date="2026-06-01T00:00:00Z",
        base_flood_elevation_ft=14.0,
    )
    return scenario


# ==========================================================================
# The post-disaster cascade
# ==========================================================================

class TestPostDisasterCascade:

    def test_finalize_appends_damage_record_and_recomputes_the_ledger(self, api):
        """PRD §3.7: "Hop one appends a ledger record for the structure with
        `record_type` `DAMAGE`, `source` `DISASTER_INSPECTION`, `inspection_id` naming
        this inspection, `cost_usd` equal to `damage_cost_usd`, `claim_paid_amount_usd`
        copied from the inspection, and `event_date` equal to `disaster_event_date`."
        And: "Hop two, caused by hop one, recomputes the structure's `anchor_record_id`,
        `cumulative_counted_cost_usd`, `cumulative_improvement_pct`, and
        `single_event_improvement_pct`, and recomputes the owning property's
        repetitive-loss fields."  The qualifying set for the property is bounded:
        "The qualifying set is every `DAMAGE` record, not reversed, whose
        `claim_paid_amount_usd` is at least 1000.00, drawn from every `Structure` whose
        `property_id` is this property, sorted by `event_date` ascending and then by
        `created_at` ascending."

        Design: Difficulty/transitive_cascade/inspection_finalize_cascades_five_hops_to_permit_revision
        """
        scenario = _assessed_inspection_over_approved_permit()
        structure_id = scenario["structure"]["id"]
        inspection_id = scenario["inspection"]["id"]

        inspection = validate_success(api.finalize_inspection(inspection_id, ADMIN))
        assert inspection["status"] == "FINALIZED"
        assert float(inspection["damage_ratio_pct"]) == pytest.approx(60.00, abs=0.01)
        assert float(inspection["market_value_at_inspection_usd"]) == pytest.approx(
            200_000.00, abs=0.01
        )

        records, meta = validate_paginated(
            api.list_improvement_records(ADMIN, {"structure_id": structure_id})
        )
        assert meta["total_count"] == 1
        record = records[0]
        assert record["record_type"] == "DAMAGE"
        assert record["source"] == "DISASTER_INSPECTION"
        assert record["inspection_id"] == inspection_id
        assert float(record["cost_usd"]) == pytest.approx(120_000.00, abs=0.01)
        assert record["event_date"].startswith("2026-07-01")
        assert record["counted_in_cumulative"] is True

        structure = validate_success(api.get_structure(structure_id, ADMIN))
        assert structure["anchor_record_id"] == record["id"]
        assert float(structure["cumulative_counted_cost_usd"]) == pytest.approx(
            120_000.00, abs=0.01
        )
        assert float(structure["cumulative_improvement_pct"]) == pytest.approx(60.00, abs=0.01)

        prop = validate_success(api.get_property(scenario["property"]["id"], ADMIN))
        assert prop["repetitive_loss_status"] == "NONE"

    def test_finalize_determines_substantial_damage_and_retreats_approved_permit(self, api):
        """PRD §3.7: "Hop three, caused by hop two, opens a case directly in
        `DETERMINED` with `method` `CUMULATIVE` — but only when
        `cumulative_improvement_pct` has reached 50 percent or more and no case of the
        structure is `OPEN`, `DETERMINED`, or `APPEALED` — and sets the structure's
        `substantial_status` to `SUBSTANTIAL_DAMAGE`."  And: "Hop four, caused by hop
        three, recomputes `required_lowest_floor_elevation_ft` for every permit of the
        structure whose `status` is `UNDER_REVIEW`, `REVISION_REQUIRED`, or `APPROVED`,
        now including the extra half-foot substantial-improvement bump, and moves any
        `APPROVED` permit whose proposed elevation now falls short to
        `REVISION_REQUIRED`."  The server-opened case is labelled by its cause:
        "Cases opened by the server carry `trigger_source` `PERMIT_REVIEW` or
        `DISASTER_INSPECTION` instead of `ADMIN`, according to what created them."
        And: "The status it opens in depends on the record's `source`: a record sourced
        from `ADMIN_ADJUSTMENT` or `PERMIT_CLOSEOUT` produces a case in `OPEN`,
        awaiting a human determination, whereas a record sourced from
        `DISASTER_INSPECTION` produces a case created directly in `DETERMINED` with
        `determined_by_user_id` null."

        Design: Difficulty/transitive_cascade/inspection_finalize_cascades_five_hops_to_permit_revision
        """
        scenario = _assessed_inspection_over_approved_permit()
        structure_id = scenario["structure"]["id"]

        validate_success(api.finalize_inspection(scenario["inspection"]["id"], ADMIN))

        structure = validate_success(api.get_structure(structure_id, ADMIN))
        assert structure["substantial_status"] == "SUBSTANTIAL_DAMAGE"

        cases, meta = validate_paginated(
            api.list_determination_cases(ADMIN, {"structure_id": structure_id})
        )
        assert meta["total_count"] == 1
        case = cases[0]
        assert case["status"] == "DETERMINED"
        assert case["method"] == "CUMULATIVE"
        assert case["determination_type"] == "SUBSTANTIAL_DAMAGE"
        assert case["trigger_source"] == "DISASTER_INSPECTION"
        assert case["determined_by_user_id"] is None

        permit = validate_success(api.get_permit(scenario["permit"]["id"], ADMIN))
        assert float(permit["required_lowest_floor_elevation_ft"]) == pytest.approx(
            14.0, abs=0.01
        )
        assert permit["status"] == "REVISION_REQUIRED"


# ==========================================================================
# The enforcement cascade
# ==========================================================================

class TestEnforcementCascade:

    def test_order_default_escalates_violation_and_re_derives_suspension(self, api):
        """PRD §3.8: "Hop one moves the order to the terminal `DEFAULTED` and stamps
        `resolved_at`."  And: "Hop two moves the violation from `ORDER_ISSUED` to
        `ESCALATED`."  And: "Hop three-a, caused by hop two, recomputes
        `sanction_risk_points` with the defaulted order now contributing its 5-point
        penalty and re-derives `compliance_posture`."  The arithmetic is fixed:
        "**Step one** produces the raw score: the severity weights of every violation
        belonging to any property of the community whose `status` is `OPEN`,
        `ORDER_ISSUED`, or `ESCALATED` — 2 points for `MINOR`, 6 for `MAJOR`, 12 for
        `CRITICAL` — plus 5 points for each `DEFAULTED` remediation order whose
        violation is still `ESCALATED` and whose violation belongs to a property of the
        community."  And: "The tier rule is inclusive on the worse side: a score of 25
        points or more is `SUSPENDED`, a score of 10 points or more is `ON_PROBATION`,
        and anything lower is `GOOD_STANDING`."

        Design: Difficulty/transitive_cascade/order_default_cascades_four_hops_to_cycle_retrograde
        """
        scenario = _defaulting_order_over_issued_permit()

        order = validate_success(
            api.resolve_remediation_order(
                scenario["order"]["id"], {"resolution": "DEFAULTED"}, ADMIN
            )
        )
        assert order["status"] == "DEFAULTED"

        escalated = validate_success(
            api.get_violation(scenario["violation_two"]["id"], ADMIN)
        )
        assert escalated["status"] == "ESCALATED"
        assert escalated["sanction_points_contributed"] == 12

        untouched = validate_success(api.get_violation(scenario["violation_one"]["id"], ADMIN))
        assert untouched["status"] == "OPEN"

        community = validate_success(api.get_community(scenario["community"]["id"], ADMIN))
        assert community["sanction_risk_points"] == 29
        assert community["compliance_posture"] == "SUSPENDED"

    def test_order_default_revokes_named_permit_and_retrogrades_open_cycle(self, api):
        """PRD §3.8: "Hop three-b, also caused by hop two, revokes the permit named in the
        violation's `permit_id` when that field is set and the permit's `status` is
        `APPROVED` or `ISSUED`, moving it to the terminal `REVOKED`."  And: "Hop four,
        caused by hop three-a, fires only when the re-derived `compliance_posture`
        becomes `SUSPENDED`: every `CrsCycle` of the community whose `status` is
        `OPEN`, `SUBMITTED`, or `UNDER_VERIFICATION` moves to the terminal
        `RETROGRADED` and the community's `crs_class` is reset to 10."

        Design: Difficulty/transitive_cascade/order_default_cascades_four_hops_to_cycle_retrograde
        """
        scenario = _defaulting_order_over_issued_permit()

        validate_success(
            api.resolve_remediation_order(
                scenario["order"]["id"], {"resolution": "DEFAULTED"}, ADMIN
            )
        )

        permit = validate_success(api.get_permit(scenario["permit"]["id"], ADMIN))
        assert permit["status"] == "REVOKED"

        cycle = validate_success(api.get_crs_cycle(scenario["cycle"]["id"], COORD))
        assert cycle["status"] == "RETROGRADED"

        community = validate_success(api.get_community(scenario["community"]["id"], COORD))
        assert community["crs_class"] == 10


# ==========================================================================
# The map-revision cascade
# ==========================================================================

class TestMapRevisionCascade:

    def test_activation_supersedes_incumbent_and_repoints_the_parcel(self, api):
        """PRD §3.2: "Activation moves the panel from `PENDING_REVISION` to
        `EFFECTIVE`, stamps `activated_at` with the current logical clock, and records
        in `supersedes_panel_id` the identifier of the panel that was `EFFECTIVE` for
        the same `community_id` and `panel_number` at that moment — null when this is
        the community's first panel for that number."  And: "First, the superseded
        incumbent moves to `SUPERSEDED`, which is terminal — an effective panel is
        retired only by the activation of its successor, and a `PENDING_REVISION` panel
        is never superseded directly."  And: "Second, caused by the first hop, every
        `Property` whose `firm_panel_id` pointed at the superseded panel is repointed to
        the newly effective panel."

        Design: Difficulty/transitive_cascade/panel_activation_cascades_four_hops_to_certificate_supersession
        """
        scenario = _pending_map_revision()
        incumbent_id = scenario["panel"]["id"]
        successor_id = scenario["new_panel"]["id"]

        successor = validate_success(api.activate_firm_panel(successor_id, COORD))
        assert successor["status"] == "EFFECTIVE"
        assert successor["supersedes_panel_id"] == incumbent_id

        incumbent = validate_success(api.get_firm_panel(incumbent_id, COORD))
        assert incumbent["status"] == "SUPERSEDED"

        prop = validate_success(api.get_property(scenario["property"]["id"], ADMIN))
        assert prop["firm_panel_id"] == successor_id

    def test_activation_revises_stale_permit_and_supersedes_the_certificate(self, api):
        """PRD §3.2: "Third, caused by the second hop, every `DevelopmentPermit`
        belonging to one of those repointed properties whose `status` is `UNDER_REVIEW`
        or `APPROVED`, and whose frozen `determined_bfe_ft` differs from the new panel's
        `base_flood_elevation_ft` or whose frozen `determined_zone` differs from the new
        panel's `flood_zone`, moves to `REVISION_REQUIRED` with `determined_zone` and
        `determined_bfe_ft` re-snapshotted from the new panel and
        `required_lowest_floor_elevation_ft` recomputed."  And: "Fourth, caused by the
        third hop, for each permit that the third hop moved to `REVISION_REQUIRED`,
        every `ElevationCertificate` whose `structure_id` equals that permit's
        `structure_id` and whose `status` is `ACCEPTED` moves to `SUPERSEDED` — the
        survey no longer reflects the governing map — and that structure's
        `lowest_floor_elevation_ft` is cleared to null with `compliance_status`
        returning to `PENDING_CERTIFICATE`, unless it is `PRE_FIRM_EXISTING`, which is
        never disturbed."  The recomputed requirement follows §3.4: "**The freeboard**
        is the larger of the permit's `freeboard_applied_ft` and the zone's own
        regulatory floor, which is 1.0 foot for zones `A`, `AE`, and `AO` and 2.0 feet
        for zone `VE`."

        Design: Difficulty/transitive_cascade/panel_activation_cascades_four_hops_to_certificate_supersession
        """
        scenario = _pending_map_revision()

        validate_success(api.activate_firm_panel(scenario["new_panel"]["id"], COORD))

        revised = validate_success(api.get_permit(scenario["approved_permit"]["id"], ADMIN))
        assert revised["status"] == "REVISION_REQUIRED"
        assert float(revised["determined_bfe_ft"]) == pytest.approx(14.0, abs=0.01)
        assert float(revised["required_lowest_floor_elevation_ft"]) == pytest.approx(
            15.5, abs=0.01
        )

        untouched = validate_success(api.get_permit(scenario["issued_permit"]["id"], ADMIN))
        assert untouched["status"] == "ISSUED"

        certificate = validate_success(api.get_certificate(scenario["certificate"]["id"], ADMIN))
        assert certificate["status"] == "SUPERSEDED"

        structure = validate_success(api.get_structure(scenario["structure"]["id"], ADMIN))
        assert structure["lowest_floor_elevation_ft"] is None
        assert structure["compliance_status"] == "PENDING_CERTIFICATE"
