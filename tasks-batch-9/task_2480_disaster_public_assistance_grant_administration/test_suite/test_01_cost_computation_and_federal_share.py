"""Cost computation, the mitigation cap and the federal share.

Every test builds its own world from scratch: the harness restarts the API and
wipes the database before each individual test.
"""
from test_helpers import (
    create_applicant,
    create_facility,
    determine_eligibility,
    make_admin_headers,
    make_applicant_agent_headers,
    make_grants_officer_headers,
    make_specialist_headers,
    setup_declaration,
    setup_obligated_project,
    setup_project_with_labor_claim,
    setup_submitted_project,
    setup_validated_project,
    validate_success,
)
from test_helpers.fixtures import create_cost_line_item, review_cost_line_item

CLOCK = "2026-07-01T00:00:00Z"

# --- DR-4901 / DR-4904: identical inputs, two different money answers -------
HARBORVIEW_DISASTER = {
    "declaration_number": "DR-4901",
    "state_code": "TX",
    "incident_type": "FLOOD",
    "incident_start_at": "2026-06-10T00:00:00Z",
    "incident_end_at": "2026-06-25T00:00:00Z",
    "population": 2_000_000,
    "federal_cost_share_pct": 0.75,
    "small_project_threshold_cents": 4_000_000,
}
HARBORVIEW_APPLICANT = {
    "name": "City of Harborview",
    "applicant_type": "LOCAL_GOVERNMENT",
    "population_served": 120_000,
}
PUMP_STATION_FACILITY = {
    "name": "Riverside Pump Station",
    "facility_type": "WATER_CONTROL",
    "ownership": "PUBLIC",
    "in_active_use": True,
    "legal_responsibility_documented": True,
    "flood_zone": False,
    "prior_disaster_flood_damage": False,
}
PUMP_STATION_PROJECT = {
    "category": "C",
    "title": "Pump station intake rebuild",
    "scope_of_work": "Rebuild intake structure and control panel",
    "estimated_repair_cost_cents": 5_000_000,
    "mitigation_requested_cents": 900_000,
}
# 3_600_000 + 200_000 == 3_800_000 documented actuals, below the threshold.
PUMP_STATION_LINES = [
    {
        "cost_type": "MATERIALS",
        "claimed_cents": 3_600_000,
        "work_start_at": "2026-06-12T08:00:00Z",
        "work_end_at": "2026-06-12T17:00:00Z",
    },
    {
        "cost_type": "MATERIALS",
        "claimed_cents": 200_000,
        "work_start_at": "2026-06-13T08:00:00Z",
        "work_end_at": "2026-06-13T17:00:00Z",
    },
]


def _obligated_pump_station_project(declaration_number: str) -> dict:
    disaster = dict(HARBORVIEW_DISASTER, declaration_number=declaration_number)
    return setup_obligated_project(
        clock=CLOCK,
        disaster_overrides=disaster,
        applicant_overrides=HARBORVIEW_APPLICANT,
        facility_overrides=PUMP_STATION_FACILITY,
        project_overrides=PUMP_STATION_PROJECT,
        line_items=PUMP_STATION_LINES,
    )


# ===========================================================================
# The PROVISIONAL and FINAL cost variants on one project
# ===========================================================================
def test_closeout_final_variant_diverges_from_the_provisional_variant(api):
    """PRD §3.3: "Its repair basis is the project's own `estimated_repair_cost_cents`."

    PRD §3.3: "Finally, `eligible_cost_provisional_cents` is the repair basis
    less the anticipated insurance offset, floored at 0 so an over-insured
    project never produces a negative figure, plus the approved mitigation
    component."

    PRD §3.9: "Its repair basis is the sum of `eligible_cents` over the
    project's `ALLOWED` and `PARTIALLY_ALLOWED` lines, with **no** estimate
    fallback — the empty case cannot arise because it was rejected upstream."

    PRD §3.9: "Its insurance offset is the project's
    `settlement_allocated_cents`, that is, **actual proceeds only**;
    `anticipated_insurance_cents` is deliberately ignored here, which is the
    whole point of having two variants."

    PRD §3.9: "`eligible_cost_final_cents` is therefore the documented repair
    basis less the actual settlement allocation, floored at 0, plus the frozen
    mitigation component."

    PRD §3.9: "The two variants live side by side on the project and are
    expected to differ whenever documented actuals or recorded settlements
    differ from the estimate and the anticipated proceeds."

    Design: Difficulty/dual_variant_calc/project_eligible_cost_provisional_vs_final_divergence
    """
    scenario = _obligated_pump_station_project("DR-4901")

    response = api.request_closeout(
        scenario["project"]["id"],
        make_applicant_agent_headers(scenario["applicant"]["id"]),
    )
    project = validate_success(response)

    assert project["eligible_cost_provisional_cents"] == 5_750_000, (
        "Expected 5750000, got "
        f"{project['eligible_cost_provisional_cents']} for the estimate-based "
        "PROVISIONAL variant after closeout request"
    )
    assert project["eligible_cost_final_cents"] == 4_560_000, (
        "Expected 4560000, got "
        f"{project['eligible_cost_final_cents']} for the documented-actuals "
        "FINAL variant after closeout request"
    )
    divergence = (
        project["eligible_cost_final_cents"] - project["eligible_cost_provisional_cents"]
    )
    assert divergence == -1_190_000, (
        f"Expected -1190000, got {divergence} for the FINAL minus PROVISIONAL gap"
    )


def test_closeout_final_variant_reuses_the_mitigation_frozen_at_cost_review(api):
    """PRD §3.9: "And its mitigation component is `mitigation_approved_cents`
    exactly as frozen at cost review, never recomputed from the actual basis."

    PRD §3.7: "The system totals the `eligible_cents` of every cost line item
    on the project whose `review_status` is `ALLOWED` or `PARTIALLY_ALLOWED`,
    and `repair_eligible_cents` becomes that total."

    PRD §3.9: "When the work is done and the receipts are in, the
    `ApplicantAgent` requests closeout, driving the project `OBLIGATED →
    CLOSEOUT_REQUESTED`."

    Design: Difficulty/dual_variant_calc/project_eligible_cost_provisional_vs_final_divergence
    """
    scenario = _obligated_pump_station_project("DR-4901")

    response = api.request_closeout(
        scenario["project"]["id"],
        make_applicant_agent_headers(scenario["applicant"]["id"]),
    )
    project = validate_success(response)

    assert project["mitigation_approved_cents"] == 760_000, (
        "Expected 760000, got "
        f"{project['mitigation_approved_cents']} — the mitigation award frozen "
        "at cost review must not be recomputed from the FINAL repair basis"
    )
    assert project["repair_eligible_cents"] == 3_800_000, (
        f"Expected 3800000, got {project['repair_eligible_cents']} for the "
        "reviewed repair basis"
    )
    assert project["status"] == "CLOSEOUT_REQUESTED", (
        f"Expected CLOSEOUT_REQUESTED, got {project['status']} after closeout request"
    )


# ===========================================================================
# The SCREENING and MONITORING risk-score variants on one applicant
# ===========================================================================
CEDAR_DISASTER = {
    "declaration_number": "DR-4902",
    "state_code": "TX",
    "incident_type": "SEVERE_STORM",
    "incident_start_at": "2026-06-10T00:00:00Z",
    "incident_end_at": "2026-06-25T00:00:00Z",
    "population": 500_000,
    "federal_cost_share_pct": 0.75,
    "small_project_threshold_cents": 4_000_000,
}


def _cedar_county_with_three_facilities() -> dict:
    """A PENDING LOCAL_GOVERNMENT applicant owning exactly three facilities,
    one of them in a flood zone and carrying no FLOOD policy, with an entirely
    zeroed grant ledger."""
    scenario = setup_declaration(clock=CLOCK, **CEDAR_DISASTER)
    applicant = create_applicant(
        scenario["disaster"]["id"],
        name="Cedar County",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=80_000,
    )
    create_facility(
        applicant["id"],
        name="County Road 12 Bridge",
        facility_type="ROAD_BRIDGE",
        ownership="PUBLIC",
        flood_zone=False,
    )
    create_facility(
        applicant["id"],
        name="County Maintenance Barn",
        facility_type="BUILDING_EQUIPMENT",
        ownership="PUBLIC",
        flood_zone=False,
    )
    create_facility(
        applicant["id"],
        name="Cedar Creek Levee",
        facility_type="WATER_CONTROL",
        ownership="PUBLIC",
        flood_zone=True,
    )
    scenario["applicant"] = applicant
    return scenario


def test_eligibility_determination_scores_only_the_screening_variant(api):
    """PRD §3.1: "Both branches behave identically in every other respect: each
    writes `eligibility_status` and `eligibility_rationale`, each re-scores the
    `SCREENING` variant of the applicant risk score into `risk_score_screening`
    and refreshes `risk_tier`, and each increments the applicant's `version` by
    1."

    PRD §3.1: "Three point components are weighted and summed: the
    applicant-type component at 30 percent, a second component at 30 percent,
    and a third component at 40 percent, with the weighted sum rounded half up
    to two decimal places."

    PRD §3.1: "The applicant-type component is a fixed point value read from
    the `applicant_type`: 20 points for `LOCAL_GOVERNMENT`, 30 for `TRIBE`, 10
    for `STATE_AGENCY` and 60 for `PRIVATE_NONPROFIT`."

    PRD §3.1: "The second component awards 10 points for every facility
    registered to the applicant, counted regardless of each facility's own
    `eligibility_status`, and is then capped at 100 points — so an applicant
    with ten or more facilities scores the maximum."

    PRD §3.1: "The third component is all-or-nothing: it is 100 points when the
    applicant owns at least one facility whose `flood_zone` is true and on which
    no insurance policy of `policy_type` `FLOOD` exists at all, and 0 points
    otherwise."

    PRD §3.1: "The resulting score maps to a tier: at least 60 points is
    `HIGH`, at least 30 but below 60 is `MEDIUM`, and anything below 30 is
    `LOW`."

    Design: Difficulty/dual_variant_calc/applicant_risk_score_screening_vs_monitoring_divergence
    """
    scenario = _cedar_county_with_three_facilities()

    response = api.determine_eligibility(
        scenario["applicant"]["id"],
        {
            "decision": "ELIGIBLE",
            "rationale": "County government inside the declared area",
        },
        make_specialist_headers(),
    )
    applicant = validate_success(response)

    assert applicant["risk_score_screening"] == 55.00, (
        f"Expected 55.00, got {applicant['risk_score_screening']} for the "
        "SCREENING variant after eligibility determination"
    )
    assert applicant["risk_score_monitoring"] is None, (
        "Expected null, got "
        f"{applicant['risk_score_monitoring']} — eligibility determination "
        "must not score the MONITORING variant"
    )
    assert applicant["monitoring_scored_at"] is None, (
        "Expected null, got "
        f"{applicant['monitoring_scored_at']} — nothing has scored monitoring yet"
    )
    assert applicant["risk_tier"] == "MEDIUM", (
        f"Expected MEDIUM, got {applicant['risk_tier']} for a screening score of 55.00"
    )


def test_reporting_sweep_scores_the_monitoring_variant_and_retiers_the_applicant(api):
    """PRD §3.8: "The sweep also re-scores the applicant on the `MONITORING`
    variant, whatever it found: `risk_score_monitoring` is rewritten,
    `monitoring_scored_at` is stamped from the clock, and `risk_tier` is
    refreshed — and because `monitoring_scored_at` is now non-null, `risk_tier`
    follows the monitoring score from here on rather than the screening score."

    PRD §3.8: "The `MONITORING` variant of the risk score shares the skeleton
    of §3.1 — 30 percent on the applicant-type points, 30 percent on the second
    component, 40 percent on the third, rounded half up to two decimal places,
    with the same tier boundaries of at least 60 for `HIGH` and at least 30 for
    `MEDIUM` — but its two behavioural components look at grant conduct rather
    than exposure."

    PRD §3.8: "The second component awards 25 points for each of the
    applicant's `DELINQUENT` reports, capped at 100 points, so four delinquent
    reports max it out."

    PRD §3.8: "The third component measures how much cash the applicant is
    sitting on relative to what it has been awarded: when
    `total_obligated_cents` is exactly 0 while `cash_on_hand_cents` is above 0
    — cash held against no live obligation at all, the worst possible signal —
    the component is a flat 100 points; otherwise it is one hundred multiplied
    by `cash_on_hand_cents`, divided by `total_obligated_cents` (treating a
    zero denominator as 1), truncated downward, and then capped at 100."

    PRD §3.1: "Because two scores can coexist on one applicant, `risk_tier` is
    derived from whichever score is the more recent evidence — it is the tier of
    `risk_score_monitoring` whenever `monitoring_scored_at` is non-null, and the
    tier of `risk_score_screening` otherwise."

    Design: Difficulty/dual_variant_calc/applicant_risk_score_screening_vs_monitoring_divergence
    """
    scenario = _cedar_county_with_three_facilities()
    determine_eligibility(
        scenario["applicant"]["id"],
        decision="ELIGIBLE",
        rationale="County government inside the declared area",
    )

    response = api.reporting_sweep(scenario["applicant"]["id"], make_admin_headers())
    validate_success(response)
    applicant = validate_success(
        api.get_applicant(scenario["applicant"]["id"], make_admin_headers())
    )

    assert applicant["risk_score_monitoring"] == 6.00, (
        f"Expected 6.00, got {applicant['risk_score_monitoring']} for the "
        "MONITORING variant on a zeroed ledger with no delinquent reports"
    )
    assert applicant["risk_score_screening"] == 55.00, (
        f"Expected 55.00, got {applicant['risk_score_screening']} — the "
        "MONITORING pass must leave the screening score untouched"
    )
    assert applicant["risk_tier"] == "LOW", (
        f"Expected LOW, got {applicant['risk_tier']} — the tier follows "
        "risk_score_monitoring once monitoring_scored_at is non-null"
    )
    assert applicant["monitoring_scored_at"] is not None, (
        "Expected monitoring_scored_at to be stamped from the logical clock, got null"
    )
    assert applicant["monitoring_scored_at"].startswith("2026-07-01T00:00:00"), (
        "Expected monitoring_scored_at stamped at 2026-07-01T00:00:00Z, got "
        f"{applicant['monitoring_scored_at']}"
    )


# ===========================================================================
# Per-component rounding of the obligated federal share
# ===========================================================================
ALDER_DISASTER = {
    "declaration_number": "DR-4903",
    "state_code": "TX",
    "incident_type": "FLOOD",
    "incident_start_at": "2026-06-10T00:00:00Z",
    "incident_end_at": "2026-06-25T00:00:00Z",
    "population": 900_000,
    "federal_cost_share_pct": 0.75,
    "small_project_threshold_cents": 4_000_000,
}


def _validated_culvert_project() -> dict:
    """A VALIDATED project whose repair basis is 3800002 cents and whose
    approved mitigation is 200002 cents, so both federal-share components land
    on an exact half cent."""
    return setup_validated_project(
        clock=CLOCK,
        disaster_overrides=ALDER_DISASTER,
        applicant_overrides={
            "name": "Town of Alder",
            "applicant_type": "LOCAL_GOVERNMENT",
            "population_served": 40_000,
        },
        facility_overrides={
            "name": "Alder Street Culvert",
            "facility_type": "ROAD_BRIDGE",
            "ownership": "PUBLIC",
            "in_active_use": True,
            "legal_responsibility_documented": True,
            "flood_zone": False,
            "prior_disaster_flood_damage": False,
        },
        project_overrides={
            "category": "C",
            "title": "Culvert replacement",
            "scope_of_work": "Replace failed culvert and headwalls",
            "estimated_repair_cost_cents": 3_900_000,
            "mitigation_requested_cents": 200_002,
        },
        line_items=[
            {
                "cost_type": "MATERIALS",
                "claimed_cents": 3_800_002,
                "work_start_at": "2026-06-14T08:00:00Z",
                "work_end_at": "2026-06-14T17:00:00Z",
            }
        ],
    )


def test_obligation_rounds_the_repair_and_mitigation_shares_separately(api):
    """PRD §3.7: "First, the net repair figure is `repair_eligible_cents` less
    `insurance_reduction_cents`, floored at 0 so a fully insured repair
    contributes nothing rather than a negative."

    PRD §3.7: "Then the repair share is that net repair figure multiplied by the
    declaration's `federal_cost_share_pct` and rounded half up to whole cents,
    **and separately** the mitigation share is `mitigation_approved_cents`
    multiplied by the same `federal_cost_share_pct` and rounded half up to whole
    cents."

    PRD §3.7: "`federal_share_obligated_cents` is the exact integer sum of those
    two independently rounded values; adding the two products first and rounding
    once is not the rule and can differ by a cent."

    PRD §3.7: "The project's `status` becomes `OBLIGATED` and
    `obligated_by_user_id` records the acting officer's `X-User-ID`, which
    permanently bars that officer from disbursing this project's drawdowns."

    Design: Difficulty/combinatorial_formula/federal_share_obligation_per_component_rounding_order
    """
    scenario = _validated_culvert_project()

    assert scenario["project"]["repair_eligible_cents"] == 3_800_002, (
        f"Expected 3800002, got {scenario['project']['repair_eligible_cents']} "
        "for the reviewed repair basis"
    )
    assert scenario["project"]["mitigation_approved_cents"] == 200_002, (
        f"Expected 200002, got {scenario['project']['mitigation_approved_cents']} "
        "for the approved mitigation award"
    )

    response = api.obligate_project(
        scenario["project"]["id"], make_grants_officer_headers()
    )
    project = validate_success(response)

    assert project["federal_share_obligated_cents"] == 3_000_004, (
        f"Expected 3000004, got {project['federal_share_obligated_cents']} "
        "after obligate"
    )
    assert project["federal_share_obligated_cents"] != 3_000_003, (
        "Got 3000003 after obligate — that is the sum-then-round result, not the "
        "pinned per-component rounding"
    )
    assert project["status"] == "OBLIGATED", (
        f"Expected OBLIGATED, got {project['status']} after obligate"
    )


def test_per_component_obligated_share_posts_to_the_applicant_ledger(api):
    """PRD §3.7: "Because `federal_share_obligated_cents` moved, the applicant's
    grant ledger is recomputed, refreshing `total_obligated_cents` and
    `available_drawdown_cents`."

    PRD §3.8: "`total_obligated_cents` is the sum, over the applicant's projects
    in status `OBLIGATED`, `CLOSEOUT_REQUESTED` or `CLOSED`, of
    `federal_share_obligated_cents` less `deobligated_cents`; projects in
    `DRAFT`, `UNDER_REVIEW`, `RFI_ISSUED`, `VALIDATED` or `DENIED` contribute
    nothing."

    Design: Difficulty/combinatorial_formula/federal_share_obligation_per_component_rounding_order
    """
    scenario = _validated_culvert_project()

    validate_success(
        api.obligate_project(scenario["project"]["id"], make_grants_officer_headers())
    )
    applicant = validate_success(
        api.get_applicant(scenario["applicant"]["id"], make_admin_headers())
    )

    assert applicant["total_obligated_cents"] == 3_000_004, (
        f"Expected 3000004, got {applicant['total_obligated_cents']} on the "
        "applicant ledger after obligate"
    )


# ===========================================================================
# The pinned mitigation-cap evaluation order
# ===========================================================================
def _pump_station_project_awaiting_cost_review() -> dict:
    """A submitted project estimated at 5000000 cents but documented at
    3800000 cents across two reviewed MATERIALS lines."""
    scenario = setup_submitted_project(
        clock=CLOCK,
        disaster_overrides=dict(HARBORVIEW_DISASTER, declaration_number="DR-4904",
                                population=900_000),
        applicant_overrides=HARBORVIEW_APPLICANT,
        facility_overrides={
            "name": "Riverside Pump Station",
            "facility_type": "WATER_CONTROL",
            "ownership": "PUBLIC",
            "flood_zone": False,
        },
        project_overrides=PUMP_STATION_PROJECT,
    )
    for spec in PUMP_STATION_LINES:
        line = create_cost_line_item(
            scenario["project"]["id"], scenario["applicant"]["id"], **spec
        )
        review_cost_line_item(line["id"])
    return scenario


def test_cost_review_classifies_size_from_the_repair_basis_alone(api):
    """PRD §3.7: "The system totals the `eligible_cents` of every cost line item
    on the project whose `review_status` is `ALLOWED` or `PARTIALLY_ALLOWED`,
    and `repair_eligible_cents` becomes that total."

    PRD §3.7: "Finally `size_class` is re-derived: `SMALL` when
    `repair_eligible_cents` is strictly below the declaration's
    `small_project_threshold_cents`, and `LARGE` when it is at or above it."

    PRD §3.7: "Validation records `cost_reviewed_by_user_id` from the acting
    specialist's `X-User-ID`, sets `status` to `VALIDATED`, and increments the
    project's `version` by 1."

    Design: Difficulty/combinatorial_formula/mitigation_cap_allocation_pinned_evaluation_order
    """
    scenario = _pump_station_project_awaiting_cost_review()

    response = api.cost_review(
        scenario["project"]["id"], {"decision": "VALIDATE"}, make_specialist_headers()
    )
    project = validate_success(response)

    assert project["repair_eligible_cents"] == 3_800_000, (
        f"Expected 3800000, got {project['repair_eligible_cents']} for the "
        "reviewed repair basis"
    )
    assert project["size_class"] == "SMALL", (
        f"Expected SMALL, got {project['size_class']} — 3800000 is strictly "
        "below the 4000000 threshold with mitigation excluded"
    )
    assert project["status"] == "VALIDATED", (
        f"Expected VALIDATED, got {project['status']} after cost review"
    )


def test_mitigation_cap_holds_the_small_percentage_when_the_total_crosses_the_threshold(api):
    """PRD §3.7: "The order is: take `repair_eligible_cents` as step one fixed
    it; classify `size_class` from that repair basis **with mitigation
    excluded**; read the cap percentage from the class, which is 20 percent for
    `SMALL` and 15 percent for `LARGE`; and set `mitigation_approved_cents` to
    the lesser of the project's `mitigation_requested_cents` and the repair
    basis multiplied by the cap percentage, truncated downward to whole cents."

    PRD §3.7: "That total may well exceed `small_project_threshold_cents`, and
    when it does the `size_class` from the earlier step **stands unchanged** —
    the classification is never re-derived from the total."

    Design: Difficulty/combinatorial_formula/mitigation_cap_allocation_pinned_evaluation_order
    """
    scenario = _pump_station_project_awaiting_cost_review()
    threshold = scenario["disaster"]["small_project_threshold_cents"]

    response = api.cost_review(
        scenario["project"]["id"], {"decision": "VALIDATE"}, make_specialist_headers()
    )
    project = validate_success(response)

    assert project["mitigation_approved_cents"] == 760_000, (
        f"Expected 760000, got {project['mitigation_approved_cents']} for the "
        "SMALL cap of 20 percent on a 3800000 repair basis"
    )
    assert project["mitigation_approved_cents"] != 570_000, (
        "Got 570000 — the LARGE cap of 15 percent must not be selected"
    )
    total_project_cost = (
        project["repair_eligible_cents"] + project["mitigation_approved_cents"]
    )
    assert total_project_cost == 4_560_000, (
        f"Expected 4560000, got {total_project_cost} for the total project cost"
    )
    assert total_project_cost > threshold, (
        f"Expected the total project cost {total_project_cost} to exceed the "
        f"small-project threshold {threshold}"
    )
    assert project["size_class"] == "SMALL", (
        f"Expected SMALL, got {project['size_class']} — the classification is "
        "never re-derived from the total project cost"
    )


# ===========================================================================
# The force-account labor branch: four interacting inputs
# ===========================================================================
def _emergency_labor_claim() -> dict:
    """A category B (EMERGENCY) project carrying one unreviewed
    FORCE_ACCOUNT_LABOR claim on a PERMANENT employee whose fringe rate sits
    above the 40 percent cap."""
    return setup_project_with_labor_claim(
        resource_overrides={
            "resource_kind": "LABOR",
            "label": "Public Works Crew Lead",
            "employee_type": "PERMANENT",
            "base_hourly_rate_cents": 4_237,
            "fringe_benefit_pct": 0.55,
        },
        line_overrides={
            "claimed_cents": 100_000,
            "work_start_at": "2026-06-12T06:00:00Z",
            "work_end_at": "2026-06-12T22:00:00Z",
            "straight_time_hours": 10,
            "overtime_hours": 6,
        },
        clock=CLOCK,
        disaster_overrides=dict(
            HARBORVIEW_DISASTER,
            declaration_number="DR-4905",
            incident_type="HURRICANE",
            population=900_000,
        ),
        applicant_overrides=HARBORVIEW_APPLICANT,
        facility_overrides={
            "name": "Emergency Debris Corridor",
            "facility_type": "EMERGENCY_PROTECTIVE",
            "ownership": "PUBLIC",
            "flood_zone": False,
        },
        project_overrides={
            "category": "B",
            "title": "Emergency protective measures",
            "scope_of_work": "Sandbagging and road closure crews",
            "estimated_repair_cost_cents": 500_000,
            "mitigation_requested_cents": 0,
        },
    )


def test_permanent_employee_on_emergency_work_loses_straight_time(api):
    """PRD §3.3: "Submission also derives `work_type` from the category once and
    for all: categories `A` and `B` are `EMERGENCY` work, and categories `C`,
    `D`, `E`, `F` and `G` are `PERMANENT` work."

    PRD §3.5: "When the resource's `employee_type` is `PERMANENT` **and** the
    project's `work_type` is `EMERGENCY`, the billable straight-time hours are
    forced to zero — a permanent employee's regular salary is not a disaster
    cost for emergency work, only the premium for working extra hours is — and
    the reduction reason is pinned to
    `STRAIGHT_TIME_NOT_ELIGIBLE_FOR_EMERGENCY_WORK`."

    PRD §3.5: "Three cost components are then formed and — this is the pinned
    order — **each is rounded half up to whole cents before any of them are
    added**: the straight-time component is the billable straight hours
    multiplied by `base_hourly_rate_cents`; the overtime component is
    `overtime_hours` multiplied by `base_hourly_rate_cents` and then by the
    overtime multiplier of one and one half; and the fringe component is the sum
    of the two already-rounded wage components multiplied by the applied fringe
    rate."

    PRD §3.5: "The computed cost is the exact integer sum of the three rounded
    components; summing the three raw products and rounding once is not the
    rule."

    PRD §3.5: "The line's `eligible_cents` is the lesser of the computed cost
    and the line's `claimed_cents` — the program never pays above what was
    claimed."

    PRD §3.5: "The `review_status` is then `ALLOWED` when `eligible_cents`
    equals `claimed_cents`, `DISALLOWED` when `eligible_cents` is 0, and
    `PARTIALLY_ALLOWED` in between; the equality test comes first, so a line
    claiming nothing and computing nothing lands in `ALLOWED`."

    Design: Difficulty/combinatorial_formula/cost_line_item_labor_branch_nonlinear_interaction
    """
    scenario = _emergency_labor_claim()

    response = api.review_cost_line_item(
        scenario["line"]["id"], make_specialist_headers()
    )
    line = validate_success(response)

    assert line["eligible_cents"] == 53_386, (
        f"Expected 53386, got {line['eligible_cents']} after review"
    )
    assert line["eligible_cents"] != 112_704, (
        "Got 112704 after review — straight time must be zeroed for a PERMANENT "
        "employee on EMERGENCY work"
    )
    assert line["review_status"] == "PARTIALLY_ALLOWED", (
        f"Expected PARTIALLY_ALLOWED, got {line['review_status']} for an "
        "eligible amount between 0 and the 100000 claim"
    )


def test_fringe_rate_above_the_cap_overwrites_the_reduction_reason(api):
    """PRD §3.5: "The applied fringe rate is the lesser of the resource's
    `fringe_benefit_pct` and the fringe cap of 40 percent, and whenever the
    resource's own `fringe_benefit_pct` exceeds that 40 percent cap the
    reduction reason is overwritten with `FRINGE_RATE_CAPPED`, superseding
    whatever it was before."

    PRD §3.5: "`disallowance_reason` is null on an `ALLOWED` outcome and
    otherwise carries the reduction reason pinned by the branch."

    Design: Difficulty/combinatorial_formula/cost_line_item_labor_branch_nonlinear_interaction
    """
    scenario = _emergency_labor_claim()

    response = api.review_cost_line_item(
        scenario["line"]["id"], make_specialist_headers()
    )
    line = validate_success(response)

    assert line["disallowance_reason"] == "FRINGE_RATE_CAPPED", (
        f"Expected FRINGE_RATE_CAPPED, got {line['disallowance_reason']} — a "
        "fringe rate of 0.55 clamped to the 0.40 cap supersedes the "
        "straight-time reason"
    )


def test_labor_review_refreshes_the_resource_charged_hours_total(api):
    """PRD §3.4: "Every resource starts with `charged_hours_total` at 0; that
    field is the running total of `straight_time_hours` plus `overtime_hours`
    plus `equipment_hours` across every cost line item that references the
    resource, and it is refreshed whenever one of those lines is reviewed."

    Design: Difficulty/combinatorial_formula/cost_line_item_labor_branch_nonlinear_interaction
    """
    scenario = _emergency_labor_claim()

    validate_success(
        api.review_cost_line_item(scenario["line"]["id"], make_specialist_headers())
    )
    resource = validate_success(
        api.get_force_account_resource(scenario["resource"]["id"], make_admin_headers())
    )

    assert resource["charged_hours_total"] == 16, (
        f"Expected 16, got {resource['charged_hours_total']} for 10 straight-time "
        "plus 6 overtime hours after review"
    )
