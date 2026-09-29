"""Cross-entity gating, overlapping intervals and conserved quantities.

This file exercises the places where one entity's state blocks an operation on
another (PRD §2.6 ladder, §3.5 revision, §3.7 execution), the three interval
conventions the PRD pins — the buffered elevation band of §3.7, the closed
construction window of §3.6 and the tiled landlord-payment timeline of §3.2 —
and the two round trips the PRD declares conserved: tower capacity across
execution and decommissioning (§2.7, §3.8) and the tenant receivable ledger
across cost-share funding and project cancellation (§3.6).
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_CONSTRUCTION_WINDOW_CONFLICT,
    ERR_ELEVATION_BAND_CONFLICT,
    ERR_GROUND_LEASE_NOT_ACTIVE,
    ERR_PAYMENT_PERIOD_GAP,
    ERR_PAYMENT_PERIOD_OVERLAP,
    ERR_TENANT_DELINQUENT,
    ERR_TOWER_POSTURE_FROZEN,
)
from test_helpers.assertions import (
    assert_amendment_axes,
    assert_analysis_outcome,
    assert_capacity_summary,
    assert_cents,
    assert_clock_summary,
    assert_load_units,
    assert_occupied_band,
    assert_pct,
    assert_tenant_ledger,
    assert_tower_capacity,
)
from test_helpers.constants import (
    DELINQUENCY_THRESHOLD_CENTS,
    ELEVATION_SEPARATION_BUFFER_FT,
)
from test_helpers.test_users import ADMIN_HEADERS, ENGINEER_HEADERS, make_tenant_headers

# ─── Shared numbers, all of them read off the PRD's own formulas ──────────────

# The two default equipment lines of a carrier schedule: three ANTENNA at 125 ft
# give (60 + 30 * 8) * 3 * 1.25 = 1125.0 load units and six RRU at 95 ft give
# (55 + 30 * 2) * 6 * 1.00 = 690.0, so PRD §3.4 totals the application at 1815.
CARRIER_LOAD_UNITS = 1815.0

# A ten-unit ANTENNA line of 80.01 lbs at 80 ft weighs 800.100 load units, which
# on a tower rated 4000 with 3000 already reserved projects 95.003 percent.
MODIFICATION_LINE = {
    "equipment_type": "ANTENNA",
    "model_code": "QX-80",
    "quantity": 10,
    "unit_weight_lbs": 80.01,
    "wind_area_sqft": 0,
    "mount_elevation_ft": 80,
}


# ─── Setup builders ──────────────────────────────────────────────────────────


def _papered_amendment_over_expiring_ground_lease(api):
    """A DRAFT amendment cleared by a PASS analysis over a lease ending 2026-12-31."""
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={"baseline_reserved_load_units": 2000},
        lease_overrides={"term_end_date": "2026-12-31"},
    )
    chain = fixtures.add_carrier_to_site(
        api,
        site,
        stage="PAPERED",
        amendment_overrides={"effective_date": "2022-08-01"},
    )
    return site, chain


def _papered_amendment_with_delinquent_carrier(api):
    """A flawless DRAFT amendment whose carrier an audit has just made delinquent."""
    site = fixtures.site_with_ground_lease(
        api, tower_overrides={"baseline_reserved_load_units": 2000}
    )
    chain = fixtures.add_carrier_to_site(
        api,
        site,
        stage="PAPERED",
        amendment_overrides={"effective_date": "2022-08-01", "restoration_deposit_cents": 0},
    )
    fixtures.make_tenant_delinquent(api, site["tower"]["id"], chain["tenant"]["id"])
    return site, chain


def _modification_required_application_on_frozen_tower(api):
    """An application parked in MODIFICATION_REQUIRED whose tower then freezes."""
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 4000,
            "baseline_reserved_load_units": 3000,
            "ground_space_total_sqft": 10000,
        },
        lease_overrides={"term_end_date": "2026-12-31"},
    )
    chain = fixtures.add_carrier_to_site(
        api,
        site,
        stage="REVIEWED",
        mla_overrides={"base_monthly_rent_cents": 205000, "escalator_pct": 3.0},
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 400,
        },
        lines=[dict(MODIFICATION_LINE)],
    )
    assert_analysis_outcome(chain["analysis"], result="MODIFICATION_REQUIRED", status="ISSUED")
    assert chain["application"]["status"] == "MODIFICATION_REQUIRED"
    clock = fixtures.advance_clock(api, "2027-01-15T00:00:00Z")
    return site, chain, clock


def _two_carriers_one_foot_apart(api):
    """One EXECUTED band 100..140 and a DRAFT amendment asking for 141..180."""
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 20000,
        },
    )
    sitting = fixtures.add_carrier_to_site(
        api,
        site,
        stage="EXECUTED",
        mla_overrides={"base_monthly_rent_cents": 200000, "escalator_pct": 3.0},
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 400,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "BX-160",
                "quantity": 10,
                "unit_weight_lbs": 160,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
        amendment_overrides={
            "effective_date": "2025-08-01",
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
        },
    )
    arriving = fixtures.add_carrier_to_site(
        api,
        site,
        stage="PAPERED",
        mla_overrides={"base_monthly_rent_cents": 210000, "escalator_pct": 3.0},
        application_overrides={
            "requested_elevation_bottom_ft": 141,
            "requested_elevation_top_ft": 180,
            "requested_ground_space_sqft": 300,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "SX-100",
                "quantity": 10,
                "unit_weight_lbs": 100,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
        amendment_overrides={
            "base_monthly_rent_cents": 210000,
            "escalator_pct": 3.0,
        },
    )
    return site, sitting, arriving


def _tower_with_one_reserved_construction_window(api):
    """Two quoted analyses on one tower, the first holding 2026-09-01..2026-10-31."""
    first = fixtures.build_colocation_chain(
        api,
        stage="REVIEWED",
        with_ground_lease=False,
        tower_overrides={
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 4000,
            "baseline_reserved_load_units": 3000,
            "ground_space_total_sqft": 10000,
        },
        mla_overrides={"base_monthly_rent_cents": 215000, "escalator_pct": 3.0},
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 300,
        },
        lines=[dict(MODIFICATION_LINE)],
    )
    tower = first["tower"]
    fixtures.quote_analysis(api, first["analysis"]["id"], 22400000)
    project = fixtures.propose_project(
        api,
        tower["id"],
        first["analysis"]["id"],
        construction_window_start_date="2026-09-01",
        construction_window_end_date="2026-10-31",
    )
    second = fixtures.build_colocation_chain(
        api,
        stage="REVIEWED",
        tower=tower,
        tenant=first["tenant"],
        mla=first["mla"],
        application_overrides={
            "requested_elevation_bottom_ft": 200,
            "requested_elevation_top_ft": 240,
            "requested_ground_space_sqft": 300,
        },
        lines=[dict(MODIFICATION_LINE)],
    )
    fixtures.quote_analysis(api, second["analysis"]["id"], 22400000)
    return tower, project, second


def _lease_paid_through_october(api):
    """A W-9-backed ground lease whose paid_through_date sits at 2026-10-31."""
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "rated_capacity_load_units": 6000,
            "max_elevation_ft": 250,
            "ground_space_total_sqft": 12000,
        },
        landlord_overrides={"w9_on_file": True},
        lease_overrides={
            "base_monthly_rent_cents": 400000,
            "escalator_pct": 2.5,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
        },
    )
    lease = site["ground_lease"]
    fixtures.record_landlord_payment(api, lease["id"], "2026-08-01", "2026-10-31")
    return lease


def _funded_reinforcement_project(api):
    """The two-beneficiary allocation of PRD §3.6, accepted by both carriers."""
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 3900,
            "max_elevation_ft": 400,
            "ground_space_total_sqft": 10000,
        },
    )
    sitting = fixtures.add_carrier_to_site(
        api,
        site,
        stage="EXECUTED",
        mla_overrides={"base_monthly_rent_cents": 200000, "escalator_pct": 3.0},
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 400,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "BX-160",
                "quantity": 10,
                "unit_weight_lbs": 160,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
        amendment_overrides={
            "effective_date": "2025-08-01",
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
        },
    )
    applicant = fixtures.add_carrier_to_site(
        api,
        site,
        stage="REVIEWED",
        mla_overrides={"expedited_review_days": 15},
        application_overrides={
            "requested_elevation_bottom_ft": 150,
            "requested_elevation_top_ft": 190,
            "requested_ground_space_sqft": 500,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "AX-175",
                "quantity": 10,
                "unit_weight_lbs": 175,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 125,
            }
        ],
    )
    assert_analysis_outcome(applicant["analysis"], result="MODIFICATION_REQUIRED")
    fixtures.quote_analysis(api, applicant["analysis"]["id"], 20000000)
    reviewing = fixtures.add_carrier_to_site(
        api,
        site,
        stage="SUBMITTED",
        mla_overrides={"base_monthly_rent_cents": 180000, "escalator_pct": 2.5},
        application_overrides={
            "requested_elevation_bottom_ft": 250,
            "requested_elevation_top_ft": 290,
            "requested_ground_space_sqft": 100,
        },
        lines=[
            {
                "equipment_type": "TMA",
                "model_code": "TM-10",
                "quantity": 1,
                "unit_weight_lbs": 10,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
    )
    project = fixtures.propose_project(
        api,
        site["tower"]["id"],
        applicant["analysis"]["id"],
        construction_window_start_date="2026-09-01",
        construction_window_end_date="2026-10-31",
    )
    fixtures.allocate_shares(api, project["id"])
    sitting_share = fixtures.share_for_tenant(api, project["id"], sitting["tenant"]["id"])
    applicant_share = fixtures.share_for_tenant(api, project["id"], applicant["tenant"]["id"])
    fixtures.accept_share(api, sitting_share["id"], sitting["tenant"]["id"])
    fixtures.accept_share(api, applicant_share["id"], applicant["tenant"]["id"])
    return {
        "site": site,
        "sitting": sitting,
        "applicant": applicant,
        "reviewing": reviewing,
        "project": project,
        "sitting_share": sitting_share,
        "applicant_share": applicant_share,
    }


# The pinned outputs of the seven-step cost pipeline of PRD §3.6 on a quoted
# construction cost of 20,000,000 cents: the provisional 12 percent fee makes a
# pre-discount total of 22,400,000, which selects the 1.5 percent tier, so the
# discounted construction figure is 19,700,000, the engineering fee 2,364,000
# and the total 22,064,000. Split pro rata over 1600.000 and 2187.500 basis load
# units the floored shares are 9,320,765 and 12,743,234, and the single leftover
# cent goes to the earlier-created beneficiary, the executed amendment.
PROJECT_TOTAL_COST_CENTS = 22064000
SITTING_SHARE_CENTS = 9320766
APPLICANT_SHARE_CENTS = 12743234


# ─── Amendment execution against an expired ground lease ─────────────────────


def test_amendment_execute_rejected_when_ground_lease_expired(api):
    """PRD §2.6: "The amendment's tower has a ground lease in `ACTIVE` status →
    `ERR_GROUND_LEASE_NOT_ACTIVE` (409), on amendment execution."

    Design: Difficulty/cross_entity_state_dependency/amendment_execute_rejected_when_ground_lease_expired
    """
    site, chain = _papered_amendment_over_expiring_ground_lease(api)
    fixtures.advance_clock(api, "2027-01-15T00:00:00Z")

    response = api.execute_site_amendment(
        chain["amendment"]["id"], factories.execute_payload(True), ADMIN_HEADERS
    )
    validate_error(response, ERR_GROUND_LEASE_NOT_ACTIVE, 409)

    amendment = fixtures.read_amendment(api, chain["amendment"]["id"])
    assert_amendment_axes(
        amendment, execution_status="DRAFT", billing_status="NOT_BILLING"
    )
    tower = fixtures.read_tower(api, site["tower"]["id"])
    assert_tower_capacity(tower, reserved_load_units=2000.0, occupied_band_count=0)


def test_ground_lease_expiry_freezes_tower_and_outranks_the_posture_check(api):
    """PRD §2.6: "On amendment execution, the ground-lease status check precedes
    the frozen-posture check, which precedes the structural-capacity check, which
    precedes the structural-clearance check, which precedes the elevation-band
    check, which precedes the ground-space check, which precedes the term check,
    which finally precedes the delinquency check — so an amendment that would
    fail four of these at once reports the earliest one in that order."

    Design: Difficulty/cross_entity_state_dependency/amendment_execute_rejected_when_ground_lease_expired
    """
    site, chain = _papered_amendment_over_expiring_ground_lease(api)

    summary = fixtures.advance_clock(api, "2027-01-15T00:00:00Z")
    assert_clock_summary(
        summary,
        expired_ground_lease_count=1,
        expired_master_lease_count=0,
        frozen_tower_count=1,
    )
    lease = fixtures.read_ground_lease(api, site["ground_lease"]["id"])
    assert lease["status"] == "EXPIRED", "an elapsed term_end_date expires the ground lease"
    tower = fixtures.read_tower(api, site["tower"]["id"])
    assert_tower_capacity(tower, capacity_posture="FROZEN", open_review_count=0)

    # Both the lease-status rule and the frozen-posture rule are live; the
    # earlier rung of the ladder is the one that must answer.
    response = api.execute_site_amendment(
        chain["amendment"]["id"], factories.execute_payload(True), ADMIN_HEADERS
    )
    validate_error(response, ERR_GROUND_LEASE_NOT_ACTIVE, 409)


# ─── Amendment execution against a delinquent carrier ────────────────────────


def test_amendment_execute_rejected_when_owning_tenant_is_delinquent(api):
    """PRD §2.6: "The acting or owning tenant is not delinquent →
    `ERR_TENANT_DELINQUENT` (402), on three operations: application submit,
    application approval, and amendment execution."

    Design: Difficulty/cross_entity_state_dependency/amendment_execute_rejected_when_tenant_delinquent_returns_402
    """
    site, chain = _papered_amendment_with_delinquent_carrier(api)

    response = api.execute_site_amendment(
        chain["amendment"]["id"], factories.execute_payload(True), ADMIN_HEADERS
    )
    validate_error(response, ERR_TENANT_DELINQUENT, 402)

    amendment = fixtures.read_amendment(api, chain["amendment"]["id"])
    assert_amendment_axes(
        amendment, execution_status="DRAFT", billing_status="NOT_BILLING"
    )
    tower = fixtures.read_tower(api, site["tower"]["id"])
    assert_tower_capacity(
        tower,
        reserved_load_units=2000.0,
        capacity_posture="OPEN",
        occupied_band_count=0,
    )


def test_retroactive_audit_billing_makes_carrier_delinquent_without_moving_its_application(api):
    """PRD §2.12: "`credit_status` is derived from that balance on every mutation
    of it: it is `DELINQUENT` when `outstanding_balance_cents` is greater than or
    equal to 5,000,000 cents (50,000 dollars), and `CURRENT` otherwise."

    Design: Difficulty/cross_entity_state_dependency/amendment_execute_rejected_when_tenant_delinquent_returns_402
    """
    _, chain = _papered_amendment_with_delinquent_carrier(api)

    tenant = fixtures.read_tenant(api, chain["tenant"]["id"])
    assert_tenant_ledger(
        tenant, outstanding_balance_cents=5227500, credit_status="DELINQUENT"
    )
    assert tenant["outstanding_balance_cents"] >= DELINQUENCY_THRESHOLD_CENTS

    # PRD §3.7: papering the amendment already moved this application
    # `APPROVED → AMENDMENT_ISSUED`. The suspension cascade of PRD §2.12 only
    # touches applications in SUBMITTED or UNDER_STRUCTURAL_REVIEW, so this one
    # is left where it stands.
    application = fixtures.read_application(api, chain["application"]["id"])
    assert application["status"] == "AMENDMENT_ISSUED"

    response = api.execute_site_amendment(
        chain["amendment"]["id"], factories.execute_payload(True), ADMIN_HEADERS
    )
    validate_error(response, ERR_TENANT_DELINQUENT, 402)


# ─── Revision against a frozen tower ─────────────────────────────────────────


def test_revise_rejected_when_ground_lease_expiry_froze_the_tower(api):
    """PRD §3.5: "Revision requires the ownership check, at least one surviving
    equipment line, an `application_privilege` of `ENABLED`, an `ACTIVE` master
    lease agreement, and a tower posture of `OPEN`; a posture of `FROZEN` or
    `RESTRICTED` blocks the revision with `ERR_TOWER_POSTURE_FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/revise_rejected_when_tower_posture_frozen
    """
    site, chain, _ = _modification_required_application_on_frozen_tower(api)

    response = api.revise_colocation_application(
        chain["application"]["id"],
        factories.revise_payload("retry after the landlord dispute"),
        make_tenant_headers(chain["tenant"]["id"]),
    )
    validate_error(response, ERR_TOWER_POSTURE_FROZEN, 409)

    lease = fixtures.read_ground_lease(api, site["ground_lease"]["id"])
    assert lease["status"] == "EXPIRED"
    tower = fixtures.read_tower(api, site["tower"]["id"])
    assert_tower_capacity(tower, capacity_posture="FROZEN", open_review_count=0)


def test_blocked_revision_leaves_application_and_its_analysis_untouched(api):
    """PRD §3.5: "Revising increments `revision_count` by one, recomputes
    `total_load_units` from the surviving lines, restamps `submitted_at` and
    recomputes `review_deadline_at`, sets every analysis of the application whose
    `status` is `ISSUED` or `QUOTED` to `SUPERSEDED`, and increments the tower's
    `open_review_count` by one."

    Design: Difficulty/cross_entity_state_dependency/revise_rejected_when_tower_posture_frozen
    """
    site, chain, _ = _modification_required_application_on_frozen_tower(api)

    response = api.revise_colocation_application(
        chain["application"]["id"],
        factories.revise_payload("retry after the landlord dispute"),
        make_tenant_headers(chain["tenant"]["id"]),
    )
    validate_error(response, ERR_TOWER_POSTURE_FROZEN, 409)

    application = fixtures.read_application(api, chain["application"]["id"])
    assert application["status"] == "MODIFICATION_REQUIRED"
    assert application["revision_count"] == 0
    assert_load_units(application["total_load_units"], 800.1, "total_load_units")

    analysis = fixtures.read_analysis(
        api, chain["application"]["id"], chain["analysis"]["id"]
    )
    assert_analysis_outcome(analysis, status="ISSUED", result="MODIFICATION_REQUIRED")
    tower = fixtures.read_tower(api, site["tower"]["id"])
    assert_tower_capacity(tower, open_review_count=0)


# ─── The buffered elevation band ─────────────────────────────────────────────


def test_amendment_execute_rejected_when_band_sits_inside_separation_buffer(api):
    """PRD §3.7: "**Band separation** is checked against every other site
    amendment on the same tower whose `execution_status` is `EXECUTED` or
    `TERMINATION_NOTICED`, excluding the one named by `supersedes_amendment_id`:
    for each such neighbour, either this amendment's `elevation_top_ft` plus a
    ten-foot separation buffer must be at or below the neighbour's
    `elevation_bottom_ft`, or the neighbour's `elevation_top_ft` plus that same
    ten-foot buffer must be at or below this amendment's `elevation_bottom_ft`.
    If neither holds for any neighbour, the bands conflict."

    Design: Difficulty/resource_temporal_overlap/elevation_band_buffer_rejected_at_one_foot_separation
    """
    _, sitting, arriving = _two_carriers_one_foot_apart(api)

    neighbour = fixtures.read_amendment(api, sitting["amendment"]["id"])
    candidate = fixtures.read_amendment(api, arriving["amendment"]["id"])
    # The bands do not overlap at all, yet the clear air between them is a
    # single foot — far less than the buffer the separation rule demands.
    assert (
        candidate["elevation_bottom_ft"] - neighbour["elevation_top_ft"]
        < ELEVATION_SEPARATION_BUFFER_FT
    )

    response = api.execute_site_amendment(
        arriving["amendment"]["id"], factories.execute_payload(True), ADMIN_HEADERS
    )
    validate_error(response, ERR_ELEVATION_BAND_CONFLICT, 409)

    candidate = fixtures.read_amendment(api, arriving["amendment"]["id"])
    assert_amendment_axes(
        candidate, execution_status="DRAFT", billing_status="NOT_BILLING"
    )


def test_band_conflict_leaves_sitting_amendment_and_tower_capacity_untouched(api):
    """PRD §2.7: "The contributing set is every site amendment on the tower whose
    `execution_status` is either `EXECUTED` or `TERMINATION_NOTICED`."

    Design: Difficulty/resource_temporal_overlap/elevation_band_buffer_rejected_at_one_foot_separation
    """
    site, sitting, arriving = _two_carriers_one_foot_apart(api)

    response = api.execute_site_amendment(
        arriving["amendment"]["id"], factories.execute_payload(True), ADMIN_HEADERS
    )
    validate_error(response, ERR_ELEVATION_BAND_CONFLICT, 409)

    neighbour = fixtures.read_amendment(api, sitting["amendment"]["id"])
    assert_amendment_axes(neighbour, execution_status="EXECUTED", billing_status="BILLING")

    tower = fixtures.read_tower(api, site["tower"]["id"])
    assert_tower_capacity(
        tower,
        reserved_load_units=1600.0,
        reserved_ground_space_sqft=400,
        available_ground_space_sqft=19600,
        occupied_band_count=1,
    )
    assert_occupied_band(
        tower["occupied_elevation_bands"][0],
        amendment_id=sitting["amendment"]["id"],
        bottom_ft=100,
        top_ft=140,
        tenant_id=sitting["tenant"]["id"],
    )


# ─── The closed construction window ──────────────────────────────────────────


def test_project_proposal_rejected_when_window_shares_a_single_day(api):
    """PRD §3.6: "The construction window must not conflict: no other
    modification project on the same tower whose `status` is `PROPOSED`,
    `COST_ALLOCATED`, `FUNDED` or `IN_CONSTRUCTION` may have a closed date
    interval from its own `construction_window_start_date` through its own
    `construction_window_end_date` that intersects this project's window on any
    calendar day, otherwise `ERR_CONSTRUCTION_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/construction_window_conflict_on_single_shared_day
    """
    tower, _, second = _tower_with_one_reserved_construction_window(api)

    # The new window opens on the very last day the standing project holds.
    response = api.create_modification_project(
        factories.modification_project_payload(
            tower["id"],
            second["analysis"]["id"],
            construction_window_start_date="2026-10-31",
            construction_window_end_date="2026-11-30",
        ),
        ENGINEER_HEADERS,
    )
    validate_error(response, ERR_CONSTRUCTION_WINDOW_CONFLICT, 409)


def test_rejected_window_leaves_first_project_proposed_and_quotation_intact(api):
    """PRD §2.6: "No construction-window conflict on the tower →
    `ERR_CONSTRUCTION_WINDOW_CONFLICT` (409), on project proposal and on
    cost-share allocation."

    Design: Difficulty/resource_temporal_overlap/construction_window_conflict_on_single_shared_day
    """
    tower, project, second = _tower_with_one_reserved_construction_window(api)

    response = api.create_modification_project(
        factories.modification_project_payload(
            tower["id"],
            second["analysis"]["id"],
            construction_window_start_date="2026-10-31",
            construction_window_end_date="2026-11-30",
        ),
        ENGINEER_HEADERS,
    )
    validate_error(response, ERR_CONSTRUCTION_WINDOW_CONFLICT, 409)

    holder = fixtures.read_project(api, project["id"])
    assert holder["status"] == "PROPOSED"
    assert holder["construction_window_start_date"] == "2026-09-01"
    assert holder["construction_window_end_date"] == "2026-10-31"

    # The rejected proposal minted nothing, and the quotation that would have
    # funded it is still standing on the second analysis.
    listed, meta = validate_paginated(
        api.list_modification_projects({"tower_id": tower["id"], "limit": 100}, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in listed] == [project["id"]]

    analysis = fixtures.read_analysis(
        api, second["application"]["id"], second["analysis"]["id"]
    )
    assert_analysis_outcome(analysis, status="QUOTED", result="MODIFICATION_REQUIRED")
    assert_cents(
        analysis["modification_construction_cost_cents"],
        22400000,
        "modification_construction_cost_cents",
    )


# ─── The tiled landlord-payment timeline ─────────────────────────────────────


def test_landlord_payment_rejected_when_period_recovers_paid_ground(api):
    """PRD §3.2: "the period must not re-cover ground already paid, so when
    `paid_through_date` is not null, `period_start_date` must be strictly after
    it, otherwise `ERR_PAYMENT_PERIOD_OVERLAP`"

    Design: Difficulty/resource_temporal_overlap/landlord_payment_period_overlap_and_gap_rejected
    """
    lease = _lease_paid_through_october(api)

    response = api.create_landlord_payment(
        factories.landlord_payment_payload(lease["id"], "2026-10-01", "2026-12-31"),
        ADMIN_HEADERS,
    )
    validate_error(response, ERR_PAYMENT_PERIOD_OVERLAP, 409)

    reread = fixtures.read_ground_lease(api, lease["id"])
    assert reread["paid_through_date"] == "2026-10-31"


def test_landlord_payment_rejected_when_period_skips_a_month(api):
    """PRD §3.2: "the period must be contiguous, so when `paid_through_date` is
    not null, `period_start_date` must be exactly the day after it with no month
    skipped, otherwise `ERR_PAYMENT_PERIOD_GAP`"

    Design: Difficulty/resource_temporal_overlap/landlord_payment_period_overlap_and_gap_rejected
    """
    lease = _lease_paid_through_october(api)

    response = api.create_landlord_payment(
        factories.landlord_payment_payload(lease["id"], "2026-12-01", "2027-01-31"),
        ADMIN_HEADERS,
    )
    validate_error(response, ERR_PAYMENT_PERIOD_GAP, 422)

    reread = fixtures.read_ground_lease(api, lease["id"])
    assert reread["paid_through_date"] == "2026-10-31"


def test_recorded_remittance_survives_both_rejected_periods(api):
    """PRD §3.2: "A recorded payment computes `months_covered` as the count of
    whole calendar months contained in the inclusive-to-inclusive interval
    running from `period_start_date` through `period_end_date`, and computes
    `amount_cents` by evaluating the lease rent at the first day of each of those
    months, rounding each month's figure to whole cents, and summing the rounded
    monthly figures — never by summing first and rounding once."

    Design: Difficulty/resource_temporal_overlap/landlord_payment_period_overlap_and_gap_rejected
    """
    lease = _lease_paid_through_october(api)

    validate_error(
        api.create_landlord_payment(
            factories.landlord_payment_payload(lease["id"], "2026-10-01", "2026-12-31"),
            ADMIN_HEADERS,
        ),
        ERR_PAYMENT_PERIOD_OVERLAP,
        409,
    )
    validate_error(
        api.create_landlord_payment(
            factories.landlord_payment_payload(lease["id"], "2026-12-01", "2027-01-31"),
            ADMIN_HEADERS,
        ),
        ERR_PAYMENT_PERIOD_GAP,
        422,
    )

    payments, meta = validate_paginated(
        api.list_landlord_payments(lease["id"], {"limit": 100}, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1
    assert payments[0]["months_covered"] == 3
    # Six anniversaries of 2020-06-01 have elapsed, so the simple 2.5 percent
    # escalation puts every month of the period at 460,000 cents.
    assert_cents(payments[0]["amount_cents"], 1380000, "amount_cents")

    reread = fixtures.read_ground_lease(api, lease["id"])
    assert reread["paid_through_date"] == "2026-10-31"
    assert_cents(
        reread["current_monthly_rent_cents"], 460000, "current_monthly_rent_cents"
    )


# ─── Tower capacity across execution and decommissioning ─────────────────────


def test_amendment_execution_claims_load_ground_space_and_elevation_band(api):
    """PRD §2.7: "`reserved_load_units` is `baseline_reserved_load_units` plus
    the sum of `reserved_load_units` over the contributing amendments."

    Design: Difficulty/compensating_invariant/tower_capacity_conserved_across_execute_and_decommission
    """
    chain = fixtures.build_colocation_chain(
        api,
        stage="PAPERED",
        tower_overrides={"baseline_reserved_load_units": 2000},
        amendment_overrides={"effective_date": "2022-08-01"},
    )
    amendment = fixtures.execute_amendment(api, chain["amendment"]["id"])
    assert_load_units(
        amendment["reserved_load_units"], CARRIER_LOAD_UNITS, "reserved_load_units"
    )

    summary = fixtures.read_capacity_summary(api, chain["tower"]["id"])
    assert_capacity_summary(
        summary,
        reserved_load_units=3815.0,
        reserved_load_pct=38.15,
        available_ground_space_sqft=19500,
        occupied_band_count=1,
        capacity_posture="OPEN",
    )


def test_termination_notice_releases_no_tower_capacity(api):
    """PRD §3.8: "Critically, it releases nothing: the equipment is still on the
    structure, so the amendment keeps holding its load, its ground space and its
    elevation band on the tower until decommissioning actually completes."

    Design: Difficulty/compensating_invariant/tower_capacity_conserved_across_execute_and_decommission
    """
    chain = fixtures.build_colocation_chain(
        api,
        stage="PAPERED",
        tower_overrides={"baseline_reserved_load_units": 2000},
        amendment_overrides={"effective_date": "2022-08-01"},
    )
    fixtures.execute_amendment(api, chain["amendment"]["id"])
    before = fixtures.read_capacity_summary(api, chain["tower"]["id"])

    noticed = validate_success(
        api.give_termination_notice(
            chain["amendment"]["id"], {}, make_tenant_headers(chain["tenant"]["id"])
        ),
        200,
    )
    assert_amendment_axes(
        noticed,
        execution_status="TERMINATION_NOTICED",
        billing_status="BILLING",
        restoration_status="PENDING",
    )

    after = fixtures.read_capacity_summary(api, chain["tower"]["id"])
    assert_capacity_summary(
        after,
        reserved_load_units=3815.0,
        reserved_load_pct=38.15,
        available_ground_space_sqft=19500,
        occupied_band_count=1,
    )
    assert after["reserved_load_units"] == before["reserved_load_units"]
    assert after["available_ground_space_sqft"] == before["available_ground_space_sqft"]
    assert after["occupied_band_count"] == before["occupied_band_count"]

    tower = fixtures.read_tower(api, chain["tower"]["id"])
    assert_occupied_band(
        tower["occupied_elevation_bands"][0],
        amendment_id=chain["amendment"]["id"],
        bottom_ft=150,
        top_ft=190,
        tenant_id=chain["tenant"]["id"],
    )


def test_completed_decommissioning_restores_tower_capacity_without_drift(api):
    """PRD §2.7: "Because reserved quantities are a pure function of the
    contributing set rather than a running total, they are a conserved quantity:
    executing an amendment and then completing its decommissioning restores
    `reserved_load_units` and `reserved_ground_space_sqft` to their exact
    pre-execution values, with no accumulated drift."

    Design: Difficulty/compensating_invariant/tower_capacity_conserved_across_execute_and_decommission
    """
    chain = fixtures.build_colocation_chain(
        api,
        stage="PAPERED",
        tower_overrides={"baseline_reserved_load_units": 2000},
        amendment_overrides={"effective_date": "2022-08-01"},
    )
    fixtures.execute_amendment(api, chain["amendment"]["id"])
    fixtures.give_notice(api, chain["amendment"]["id"], chain["tenant"]["id"])

    closed = fixtures.complete_decommission(api, chain["amendment"]["id"])
    assert_amendment_axes(
        closed,
        execution_status="TERMINATED",
        billing_status="CLOSED",
        restoration_status="COMPLETE",
    )

    tower = fixtures.read_tower(api, chain["tower"]["id"])
    assert_tower_capacity(
        tower,
        reserved_load_units=2000.0,
        reserved_load_pct=20.0,
        reserved_ground_space_sqft=0,
        available_ground_space_sqft=20000,
        capacity_posture="OPEN",
        occupied_band_count=0,
    )
    assert tower["occupied_elevation_bands"] == []

    mla = fixtures.read_master_lease(api, chain["tenant"]["id"], chain["mla"]["id"])
    assert mla["executed_amendment_count"] == 0
    tenant = fixtures.read_tenant(api, chain["tenant"]["id"])
    assert_tenant_ledger(tenant, outstanding_balance_cents=0, credit_status="CURRENT")


# ─── The receivable ledger across funding and cancellation ───────────────────


def test_final_share_acceptance_funds_project_and_bills_both_carriers(api):
    """PRD §3.6: "When that acceptance leaves no non-voided sibling share still
    `PENDING`, the project joins `COST_ALLOCATED → FUNDED`, and a substantial
    cascade fires: `funded_at` is stamped with the logical clock; every
    `ACCEPTED` share moves `ACCEPTED → BILLED` and its tenant's
    `outstanding_balance_cents` is increased by that share's `share_cents`"

    Design: Difficulty/compensating_invariant/cost_share_ledger_conserved_across_funding_and_cancellation
    """
    world = _funded_reinforcement_project(api)

    project = fixtures.read_project(api, world["project"]["id"])
    assert project["status"] == "FUNDED"
    assert_cents(project["total_cost_cents"], PROJECT_TOTAL_COST_CENTS, "total_cost_cents")
    assert_cents(project["allocated_cents"], PROJECT_TOTAL_COST_CENTS, "allocated_cents")

    sitting_share = fixtures.read_cost_share(api, world["sitting_share"]["id"])
    applicant_share = fixtures.read_cost_share(api, world["applicant_share"]["id"])
    assert sitting_share["status"] == "BILLED"
    assert applicant_share["status"] == "BILLED"
    assert_cents(sitting_share["share_cents"], SITTING_SHARE_CENTS, "share_cents")
    assert_cents(applicant_share["share_cents"], APPLICANT_SHARE_CENTS, "share_cents")
    assert (
        sitting_share["share_cents"] + applicant_share["share_cents"]
        == PROJECT_TOTAL_COST_CENTS
    )

    assert_tenant_ledger(
        fixtures.read_tenant(api, world["sitting"]["tenant"]["id"]),
        outstanding_balance_cents=SITTING_SHARE_CENTS,
        credit_status="DELINQUENT",
    )
    assert_tenant_ledger(
        fixtures.read_tenant(api, world["applicant"]["tenant"]["id"]),
        outstanding_balance_cents=APPLICANT_SHARE_CENTS,
        credit_status="DELINQUENT",
    )

    tower = fixtures.read_tower(api, world["site"]["tower"]["id"])
    assert_tower_capacity(tower, capacity_posture="FROZEN", open_review_count=0)
    held = fixtures.read_application(api, world["reviewing"]["application"]["id"])
    assert held["status"] == "CAPACITY_HOLD"


def test_cancelling_funded_project_reverses_billed_shares_to_the_cent(api):
    """PRD §3.6: "Cancelling from `FUNDED` performs an exact compensation: every
    cost share whose `status` is `BILLED` moves `BILLED → VOIDED` and its
    tenant's `outstanding_balance_cents` is decreased by that share's
    `share_cents`, reversing the funding billing to the cent"

    Design: Difficulty/compensating_invariant/cost_share_ledger_conserved_across_funding_and_cancellation
    """
    world = _funded_reinforcement_project(api)

    cancelled = validate_success(
        api.cancel_modification_project(
            world["project"]["id"],
            factories.cancel_project_payload(
                "tenant capital plans withdrawn; reinforcement deferred"
            ),
            ADMIN_HEADERS,
        ),
        200,
    )
    assert cancelled["status"] == "CANCELLED"
    assert_cents(cancelled["allocated_cents"], 0, "allocated_cents")
    assert_cents(
        cancelled["total_cost_cents"], PROJECT_TOTAL_COST_CENTS, "total_cost_cents"
    )

    for share_id in (world["sitting_share"]["id"], world["applicant_share"]["id"]):
        share = fixtures.read_cost_share(api, share_id)
        assert share["status"] == "VOIDED"

    assert_tenant_ledger(
        fixtures.read_tenant(api, world["sitting"]["tenant"]["id"]),
        outstanding_balance_cents=0,
        credit_status="CURRENT",
    )
    assert_tenant_ledger(
        fixtures.read_tenant(api, world["applicant"]["tenant"]["id"]),
        outstanding_balance_cents=0,
        credit_status="CURRENT",
    )


def test_cancellation_restores_application_privilege_on_both_master_leases(api):
    """PRD §3.6: "a flip from `DELINQUENT` back to `CURRENT` restores
    `application_privilege` to `ENABLED` on that tenant's `ACTIVE` master leases
    and moves their `ON_HOLD` applications back to `SUBMITTED`"

    Design: Difficulty/compensating_invariant/cost_share_ledger_conserved_across_funding_and_cancellation
    """
    world = _funded_reinforcement_project(api)

    for role in ("sitting", "applicant"):
        mla = fixtures.read_master_lease(
            api, world[role]["tenant"]["id"], world[role]["mla"]["id"]
        )
        assert mla["application_privilege"] == "SUSPENDED"

    validate_success(
        api.cancel_modification_project(
            world["project"]["id"],
            factories.cancel_project_payload(
                "tenant capital plans withdrawn; reinforcement deferred"
            ),
            ADMIN_HEADERS,
        ),
        200,
    )

    for role in ("sitting", "applicant"):
        mla = fixtures.read_master_lease(
            api, world[role]["tenant"]["id"], world[role]["mla"]["id"]
        )
        assert mla["status"] == "ACTIVE"
        assert mla["application_privilege"] == "ENABLED"

    applicant_app = fixtures.read_application(
        api, world["applicant"]["application"]["id"]
    )
    assert applicant_app["status"] == "MODIFICATION_REQUIRED"


def test_cancellation_lifts_the_freeze_and_promotes_the_single_held_application(api):
    """PRD §3.6: "In all cancellation paths that had shares, `allocated_cents`
    becomes 0; from `FUNDED` the tower's posture is recomputed with the freeze
    lifted because no funded project remains, the single held-application winner
    is promoted if the posture becomes `OPEN`, and the tower's `version` is
    incremented by one."

    Design: Difficulty/compensating_invariant/cost_share_ledger_conserved_across_funding_and_cancellation
    """
    world = _funded_reinforcement_project(api)

    validate_success(
        api.cancel_modification_project(
            world["project"]["id"],
            factories.cancel_project_payload(
                "tenant capital plans withdrawn; reinforcement deferred"
            ),
            ADMIN_HEADERS,
        ),
        200,
    )

    tower = fixtures.read_tower(api, world["site"]["tower"]["id"])
    assert_tower_capacity(
        tower,
        reserved_load_units=1600.0,
        capacity_posture="OPEN",
        open_review_count=1,
        occupied_band_count=1,
    )
    assert_pct(tower["reserved_load_pct"], 41.026, "reserved_load_pct")

    promoted = fixtures.read_application(api, world["reviewing"]["application"]["id"])
    assert promoted["status"] == "UNDER_STRUCTURAL_REVIEW"
