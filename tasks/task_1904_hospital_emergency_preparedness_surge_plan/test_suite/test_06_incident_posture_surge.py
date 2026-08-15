"""Incident posture: dual capacity variants, tier boundary selection, the
deactivate/reactivate cycle, and posture gating."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assess_surge,
    assert_incident_event,
    assert_incident_surge_invariants,
    commit_site,
    create_incident,
    create_incident_payload,
    create_site,
    setup_incident_with_activated_site,
    validate_error,
    validate_success,
)

EM = TEST_USERS["emergency_manager_headers"]  # noqa: F401  (role constant for reads)
IC = TEST_USERS["incident_commander_headers"]
PC = TEST_USERS["planning_chief_headers"]
LC = TEST_USERS["logistics_chief_headers"]


class TestDualCapacityVariants:
    def test_licensed_vs_operational_divergence_with_activated_site(self, api):
        """PRD §3.4: "`licensed_surge_capacity`, the regulatory-reporting variant
        surfaced to coalition and government audiences, equals `staffed_bed_count`
        alone. `operational_surge_capacity`, the operational-planning variant,
        equals `staffed_bed_count` plus the `bed_capacity` of every alternate care
        site currently `ACTIVATED` in service of this incident (§3.7); the two
        variants diverge whenever at least one site is serving the incident, and
        operational capacity is then the larger figure."

        Design: Difficulty/dual_variant_calc/surge_capacity_licensed_vs_operational_divergence
        """
        incident, site = setup_incident_with_activated_site(
            bed_capacity=40, incident_overrides={"incident_name": "MCI-1"}
        )
        assessed = assess_surge(incident["id"], 100, 60)
        assert_incident_event(assessed)
        assert_incident_surge_invariants(assessed)
        assert assessed["licensed_surge_capacity"] == 100, (
            "regulatory-reporting variant: staffed beds only"
        )
        assert assessed["operational_surge_capacity"] == 140, (
            "operational-planning variant: 100 staffed + 40 ACTIVATED site beds"
        )

    def test_tier_derived_from_operational_capacity(self, api):
        """PRD §3.4: "The incident's `current_surge_tier` is derived by comparing
        the projected census against operational capacity using exact integer
        cross-multiplication (§2.10)."
        PRD §3.4: "Otherwise, the tier is `GREEN` when the census is below 85
        percent of capacity, `YELLOW` when the census is at least 85 percent but
        below 100 percent of capacity, `ORANGE` when the census is at least 100
        percent but below 115 percent of capacity, and `RED` when the census is at
        least 115 percent of capacity".

        Design: Difficulty/dual_variant_calc/surge_capacity_licensed_vs_operational_divergence
        """
        incident, site = setup_incident_with_activated_site(bed_capacity=40)
        assessed = assess_surge(incident["id"], 100, 60)
        assert assessed["current_surge_tier"] == "GREEN", (
            "6000 < 85*140 = 11900 — census below 85% of operational capacity"
        )

    def test_tier_excludes_committed_not_activated_sites(self, api):
        """PRD §3.4: "`operational_surge_capacity`, the operational-planning
        variant, equals `staffed_bed_count` plus the `bed_capacity` of every
        alternate care site currently `ACTIVATED` in service of this incident
        (§3.7)".

        Design: Corner/calculations/tier_excludes_committed_not_activated_sites
        """
        incident = create_incident(incident_name="MCI-committed-only")
        site = create_site(site_name="Standby Hall", bed_capacity=40)
        commit_site(site["id"], incident["id"])
        assessed = assess_surge(incident["id"], 200, 170)
        assert assessed["operational_surge_capacity"] == 200, (
            "a COMMITTED-but-never-ACTIVATED site contributes no beds"
        )
        assert assessed["current_surge_tier"] == "YELLOW", (
            "100*170 = 17000 >= 85*200 = 17000; counting the 40 beds would be GREEN"
        )


class TestTierBoundarySelection:
    def test_tier_green_to_yellow_at_85_percent(self, api):
        """PRD §3.4: "Otherwise, the tier is `GREEN` when the census is below 85
        percent of capacity, `YELLOW` when the census is at least 85 percent but
        below 100 percent of capacity, `ORANGE` when the census is at least 100
        percent but below 115 percent of capacity, and `RED` when the census is at
        least 115 percent of capacity — a census exactly on a boundary takes the
        higher tier, so exactly 85 percent is `YELLOW`, exactly 100 percent is
        `ORANGE`, and exactly 115 percent is `RED`."

        Design: Difficulty/combinatorial_formula/surge_tier_conditional_threshold_selection
        """
        incident = create_incident(incident_name="MCI-tiers", incident_type="HUMAN")
        t1 = assess_surge(incident["id"], 200, 169, headers=PC)
        assert t1["current_surge_tier"] == "GREEN", "100*169 = 16900 < 85*200 = 17000"
        t2 = assess_surge(incident["id"], 200, 170, headers=PC)
        assert t2["current_surge_tier"] == "YELLOW", (
            "17000 >= 17000 — the 85% boundary is inclusive on the higher tier"
        )

    def test_tier_orange_at_100_percent(self, api):
        """PRD §3.4: "Otherwise, the tier is `GREEN` when the census is below 85
        percent of capacity, `YELLOW` when the census is at least 85 percent but
        below 100 percent of capacity, `ORANGE` when the census is at least 100
        percent but below 115 percent of capacity, and `RED` when the census is at
        least 115 percent of capacity — a census exactly on a boundary takes the
        higher tier, so exactly 85 percent is `YELLOW`, exactly 100 percent is
        `ORANGE`, and exactly 115 percent is `RED`."

        Design: Difficulty/combinatorial_formula/surge_tier_conditional_threshold_selection
        """
        incident = create_incident(incident_name="MCI-tiers", incident_type="HUMAN")
        t3 = assess_surge(incident["id"], 200, 200, headers=PC)
        assert t3["current_surge_tier"] == "ORANGE", (
            "100*200 = 20000 >= 100*200 — the 100% boundary selects ORANGE"
        )
        t4 = assess_surge(incident["id"], 200, 230, headers=PC)
        assert t4["current_surge_tier"] == "RED", "23000 >= 115*200 = 23000"

    def test_tier_orange_just_below_115_percent(self, api):
        """PRD §3.4: "Otherwise, the tier is `GREEN` when the census is below 85
        percent of capacity, `YELLOW` when the census is at least 85 percent but
        below 100 percent of capacity, `ORANGE` when the census is at least 100
        percent but below 115 percent of capacity, and `RED` when the census is at
        least 115 percent of capacity — a census exactly on a boundary takes the
        higher tier, so exactly 85 percent is `YELLOW`, exactly 100 percent is
        `ORANGE`, and exactly 115 percent is `RED`."

        Design: Difficulty/boundary_precision_check/surge_tier_red_boundary_exactly_115_percent
        """
        incident = create_incident(incident_name="MCI-115", incident_type="HAZMAT")
        t1 = assess_surge(incident["id"], 200, 229)
        assert t1["current_surge_tier"] == "ORANGE", "100*229 = 22900 < 23000"

    def test_tier_red_at_exactly_115_percent(self, api):
        """PRD §3.4: "Otherwise, the tier is `GREEN` when the census is below 85
        percent of capacity, `YELLOW` when the census is at least 85 percent but
        below 100 percent of capacity, `ORANGE` when the census is at least 100
        percent but below 115 percent of capacity, and `RED` when the census is at
        least 115 percent of capacity — a census exactly on a boundary takes the
        higher tier, so exactly 85 percent is `YELLOW`, exactly 100 percent is
        `ORANGE`, and exactly 115 percent is `RED`."

        Design: Difficulty/boundary_precision_check/surge_tier_red_boundary_exactly_115_percent
        """
        incident = create_incident(incident_name="MCI-115", incident_type="HAZMAT")
        t2 = assess_surge(incident["id"], 200, 230)
        assert t2["current_surge_tier"] == "RED", (
            "100*230 = 23000 >= 115*200 = 23000 — the 115% boundary belongs to RED"
        )


class TestIncidentCycle:
    def test_demobilize_moves_to_deactivated_keeping_activation_count(self, api):
        """PRD §3.4: "Creation is itself the first activation: the incident enters
        `ACTIVATED` with `activation_count` set to 1 and `activated_at` stamped."
        PRD §3.4: "Third, the incident's `status` becomes `DEACTIVATED` and
        `deactivated_at` is stamped."

        Design: Difficulty/non_linear_state_machine/incident_deactivate_reactivate_cycle
        """
        incident = create_incident(incident_name="Storm wave 1")
        assert incident["status"] == "ACTIVATED"
        assert incident["activation_count"] == 1

        demobilized = validate_success(api.demobilize_incident(incident["id"], IC))
        assert_incident_event(demobilized)
        assert demobilized["status"] == "DEACTIVATED"
        assert demobilized["activation_count"] == 1, (
            "demobilization's enumerated cascade leaves the count untouched"
        )
        assert demobilized["deactivated_at"] is not None

    def test_reactivate_increments_activation_count(self, api):
        """PRD §3.4: "A `DEACTIVATED` incident may be reactivated — `DEACTIVATED` →
        `ACTIVATED` — provided no other incident is currently active
        (`ERR_INCIDENT_ALREADY_ACTIVE`). Reactivation increments `activation_count`
        by one, refreshes `activated_at`, advances the incident's `version`, and
        recomputes every supply item's projected burn using the incident's
        retained `current_surge_tier` — the multiplier resumes, at 1.0 if the tier
        is null — so the cache immediately reflects the restored posture."

        Design: Difficulty/non_linear_state_machine/incident_deactivate_reactivate_cycle
        """
        incident = create_incident(incident_name="Storm wave 1")
        validate_success(api.demobilize_incident(incident["id"], IC))
        reactivated = validate_success(api.reactivate_incident(incident["id"], IC))
        assert_incident_event(reactivated)
        assert reactivated["status"] == "ACTIVATED"
        assert reactivated["activation_count"] == 2, "second activation increments to 2"
        assert reactivated["activated_at"] is not None
        assert reactivated["deactivated_at"] is not None


class TestPostureGating:
    def test_incident_create_missing_required_field_rejected(self, api):
        """PRD §3.4: "an `IncidentCommander` declares an incident with an
        `incident_name`, an `incident_type` of `NATURAL`, `TECHNOLOGICAL`, `HUMAN`,
        `HAZMAT`, or `INFECTIOUS`, and the informational `declared_at` timestamp of
        the field declaration."
        PRD §2.11: "4. Request body shape — required fields present, types and enum
        membership valid, integer ranges respected (`quantity` strictly positive,
        `bed_capacity` strictly positive, `staffed_bed_count` and `projected_census`
        non-negative, hazard `probability`, `severity`, and `preparedness` each
        between 0 and 3 inclusive, `auto_select_count` at least 1), `occurred_at`
        not after the current clock time, and a call-back create carrying exactly
        one of `staff_member_id` or `auto_select_count`: `ERR_INVALID_REQUEST`."

        Design: Corner/entities/incident_create_missing_required_field_rejected
        """
        resp = api.create_incident(
            {"incident_name": "No type", "declared_at": "2026-08-01T00:00:00Z"}, IC
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_assess_surge_on_deactivated_incident_rejected(self, api):
        """PRD §3.4: "Assessment is posture-gated: it is permitted only while the
        incident is `ACTIVATED`, and is otherwise rejected with
        `ERR_INCIDENT_NOT_ACTIVATED`."

        Design: Corner/validations/assess_surge_on_deactivated_incident_rejected
        """
        incident = create_incident(incident_name="MCI-assess")
        validate_success(api.demobilize_incident(incident["id"], IC))
        resp = api.assess_surge(
            incident["id"], {"staffed_bed_count": 100, "projected_census": 50}, IC
        )
        validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_ACTIVATED)

    def test_second_incident_activation_conflict(self, api):
        """PRD §2.6: "at most one `IncidentEvent` may hold `status` `ACTIVATED` at
        any time. Declaring a new incident while another is active, or reactivating
        a demobilized incident while another is active, is rejected with
        `ERR_INCIDENT_ALREADY_ACTIVE` (HTTP 409)."

        Design: Corner/validations/second_incident_activation_conflict
        """
        create_incident(incident_name="Wave-A")
        resp = api.create_incident(
            create_incident_payload(incident_name="Wave-B", incident_type="HUMAN",
                                    declared_at="2026-08-01T01:00:00Z"),
            IC,
        )
        validate_error(resp, ApiErrorId.ERR_INCIDENT_ALREADY_ACTIVE)

    def test_rbac_logistics_chief_cannot_create_incident(self, api):
        """PRD §2.1: "A request that is authenticated but whose role is not
        authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD §4: "POST | `/emergency/incidents` | Declare and activate an incident |
        IncidentCommander".

        Design: Corner/rbac/rbac_logistics_chief_cannot_create_incident
        """
        resp = api.create_incident(
            create_incident_payload(incident_name="Nope"), LC
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
