"""Non-linear lifecycles and transitive cascades of the Tower Colocation API.

Covers the review/modification/revision cycle of a colocation application
(PRD §3.5), the two independent status axes of a site amendment (PRD §2.9,
§3.7, §3.8), the fork and the two joins of a reinforcement project's cost
shares (PRD §3.6), and the four- and five-level cascades that audit
finalization, decommissioning and project funding drive through the tenant
ledger, credit standing, master-lease privileges, held applications and the
tower's capacity posture (PRD §2.12, §3.8, §3.9).
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions, factories, fixtures
from test_helpers.constants import DELINQUENCY_THRESHOLD_CENTS
from test_helpers.test_users import ADMIN_HEADERS, AUDITOR_HEADERS, make_tenant_headers

# ─── Shared worlds ───────────────────────────────────────────────────────────

# The amendment PRD §3.7 papers over the Ridge application: effective 2022-08-01
# so that four anniversaries of the 3.5 percent escalator have passed on the
# cold-start logical clock of 2026-08-01.
RIDGE_AMENDMENT = {
    "effective_date": "2022-08-01",
    "term_end_date": "2031-05-31",
    "base_monthly_rent_cents": 250000,
    "escalator_pct": 3.5,
}

RIDGE_LINES = [
    {
        "equipment_type": "ANTENNA",
        "model_code": "AX-60",
        "quantity": 3,
        "unit_weight_lbs": 60,
        "wind_area_sqft": 8,
        "mount_elevation_ft": 125,
    },
    {
        "equipment_type": "RRU",
        "model_code": "RU-55",
        "quantity": 6,
        "unit_weight_lbs": 55,
        "wind_area_sqft": 2,
        "mount_elevation_ft": 95,
    },
]


def ridge_site_with_approved_application(api):
    """Ridge tower, its ACTIVE ground lease and one APPROVED application.

    The tower is rated 10,000 load units with 2,000 already reserved by the
    owner's own equipment (PRD §3.1), so its posture is OPEN. The carrier's
    two equipment lines carry 1,125.000 plus 690.000 load units under the
    elevation ladder of PRD §3.4, and the PRELIMINARY analysis of PRD §3.5
    therefore reads 38.150 percent and passes.
    """
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 10000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 20000,
            "baseline_reserved_load_units": 2000,
            "baseline_reserved_ground_sqft": 0,
        },
        landlord_overrides={
            "legal_name": "Ridge Land LLC",
            "remit_contact_email": "pay@ridge.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 400000,
            "escalator_pct": 2.5,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
            "renewal_option_count": 2,
            "renewal_term_years": 5,
            "buyout_price_cents": 12000000,
        },
    )
    world = fixtures.build_colocation_chain(
        api,
        stage="APPROVED",
        tower=site["tower"],
        ground_lease=site["ground_lease"],
        tenant_overrides={"legal_name": "Alpha Wireless"},
        mla_overrides={
            "base_monthly_rent_cents": 250000,
            "escalator_pct": 3.5,
            "initial_term_years": 10,
            "renewal_terms_count": 2,
            "expires_on": "2036-07-31",
            "expedited_review_days": 15,
        },
        application_overrides={
            "requested_elevation_bottom_ft": 150,
            "requested_elevation_top_ft": 190,
            "requested_ground_space_sqft": 500,
        },
        lines=RIDGE_LINES,
    )
    world["ground_lease"] = site["ground_lease"]
    return world


def ridge_site_with_charged_deposit_and_notice_given(api):
    """The Ridge world carried to the eve of a completed decommissioning.

    A second application of the same carrier is submitted into structural
    review, then the amendment is executed with a restoration deposit equal to
    the 5,000,000-cent delinquency threshold of PRD §2.12. Charging that
    deposit at execution (PRD §3.7) flips the carrier to DELINQUENT, which
    suspends the master lease and holds the reviewing application. The carrier
    then gives the notice of departure of PRD §3.8.
    """
    world = ridge_site_with_approved_application(api)
    tenant_id = world["tenant"]["id"]
    second = fixtures.new_application(
        api,
        world["tower"]["id"],
        world["mla"]["id"],
        tenant_id,
        requested_elevation_bottom_ft=250,
        requested_elevation_top_ft=290,
        requested_ground_space_sqft=200,
    )
    fixtures.add_equipment_line(
        api,
        second["id"],
        tenant_id,
        equipment_type="DISH",
        model_code="MW-50",
        quantity=2,
        unit_weight_lbs=50,
        wind_area_sqft=0,
        mount_elevation_ft=250,
    )
    world["second_application"] = fixtures.submit_application(api, second["id"], tenant_id)

    amendment = fixtures.paper_amendment(
        api,
        world["mla"]["id"],
        world["tower"]["id"],
        world["application"]["id"],
        restoration_deposit_cents=DELINQUENCY_THRESHOLD_CENTS,
        **RIDGE_AMENDMENT,
    )
    fixtures.execute_amendment(api, amendment["id"])
    world["amendment"] = fixtures.give_notice(api, amendment["id"], tenant_id)
    return world


def crest_application_in_modification_required(api):
    """Crest tower with one application pushed out of review by its loading.

    The tower is rated 4,000 load units with 3,000 already reserved, so the
    single 800.100-load-unit line of the carrier's schedule puts the
    PRELIMINARY analysis of PRD §3.5 at 95.003 percent — above the 95.000
    percent pass limit and below 100.000 percent, hence MODIFICATION_REQUIRED.
    """
    tower = fixtures.new_tower(
        api,
        site_name="T2 Crest",
        structure_type="SELF_SUPPORT",
        rated_capacity_load_units=4000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=10000,
        baseline_reserved_load_units=3000,
        baseline_reserved_ground_sqft=0,
    )
    return fixtures.build_colocation_chain(
        api,
        stage="REVIEWED",
        tower=tower,
        tenant_overrides={"legal_name": "Epsilon Cellular"},
        mla_overrides={
            "base_monthly_rent_cents": 240000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 400,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "QX-80",
                "quantity": 10,
                "unit_weight_lbs": 80.01,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
    )


def mesa_tower_with_reviewing_application_and_open_finding(api):
    """Mesa tower, one application under structural review, one open finding.

    The application is the witness for the fourth level of the finalization
    cascade of PRD §3.9. The audit is dated 2026-07-31 on INSTALL_DATE_BASIS
    and carries one 3,400-load-unit installation dated 2023-02-15.
    """
    tower = fixtures.new_tower(
        api,
        site_name="T5 Mesa",
        structure_type="SELF_SUPPORT",
        rated_capacity_load_units=8000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=15000,
    )
    world = fixtures.build_colocation_chain(
        api,
        stage="SUBMITTED",
        tower=tower,
        tenant_overrides={"legal_name": "Foxtrot Wireless"},
        mla_overrides={
            "base_monthly_rent_cents": 210000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 300,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "FX-100",
                "quantity": 5,
                "unit_weight_lbs": 100,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
    )
    audit = fixtures.schedule_audit(
        api, tower["id"], audit_date="2026-07-31", basis="INSTALL_DATE_BASIS"
    )
    fixtures.start_audit(api, audit["id"])
    world["audit"] = audit
    world["finding"] = fixtures.record_finding(
        api,
        audit["id"],
        world["tenant"]["id"],
        description="unpermitted 12-sector array on the 210 ft face",
        observed_load_units=3400,
        installed_on_date="2023-02-15",
        mount_elevation_ft=210,
    )
    return world


def basin_fork_with_allocated_cost_shares(api):
    """The Basin tower carrying three carriers and one allocated reinforcement.

    Rated 3,900 load units over an ACTIVE ground lease running to 2031-05-31.
    Beta's amendment is EXECUTED at 1,600.000 load units in the 100..140 band.
    Alpha's application adds 2,187.500 load units, so its PRELIMINARY analysis
    reads 97.115 percent and lands in MODIFICATION_REQUIRED; it is quoted at
    20,000,000 cents and a project reserves the 2026-09-01..2026-10-31
    construction window. Gamma's application sits in UNDER_STRUCTURAL_REVIEW as
    the witness for the push-back rule of PRD §3.5. The cost shares are then
    allocated PRO_RATA_LOAD over the beneficiary set of PRD §3.6.

    Returns the site plus ``alpha``, ``beta``, ``gamma``, ``project``,
    ``alpha_share`` and ``beta_share``.
    """
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "site_name": "T4 Basin",
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 3900,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 400,
            "ground_space_total_sqft": 10000,
            "baseline_reserved_load_units": 0,
            "baseline_reserved_ground_sqft": 0,
        },
        landlord_overrides={
            "legal_name": "Basin Ground Co",
            "remit_contact_email": "ap@basin.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 300000,
            "escalator_pct": 2.0,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
            "renewal_option_count": 1,
            "renewal_term_years": 5,
            "buyout_price_cents": 9000000,
        },
    )
    tower = site["tower"]

    beta = fixtures.build_colocation_chain(
        api,
        stage="EXECUTED",
        tower=tower,
        ground_lease=site["ground_lease"],
        tenant_overrides={"legal_name": "Beta Mobile"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
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
            "term_end_date": "2031-05-31",
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "restoration_deposit_cents": 0,
        },
    )

    alpha = fixtures.build_colocation_chain(
        api,
        stage="REVIEWED",
        tower=tower,
        ground_lease=site["ground_lease"],
        tenant_overrides={"legal_name": "Alpha Wireless"},
        mla_overrides={
            "base_monthly_rent_cents": 250000,
            "escalator_pct": 3.5,
            "initial_term_years": 10,
            "renewal_terms_count": 2,
            "expires_on": "2036-07-31",
            "expedited_review_days": 15,
        },
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
    fixtures.quote_analysis(api, alpha["analysis"]["id"], 20000000)

    gamma = fixtures.build_colocation_chain(
        api,
        stage="SUBMITTED",
        tower=tower,
        ground_lease=site["ground_lease"],
        tenant_overrides={"legal_name": "Gamma Telecom"},
        mla_overrides={
            "base_monthly_rent_cents": 180000,
            "escalator_pct": 2.5,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
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
        tower["id"],
        alpha["analysis"]["id"],
        construction_window_start_date="2026-09-01",
        construction_window_end_date="2026-10-31",
        allocation_basis="PRO_RATA_LOAD",
    )
    project = fixtures.allocate_shares(api, project["id"])
    return {
        "tower": tower,
        "ground_lease": site["ground_lease"],
        "alpha": alpha,
        "beta": beta,
        "gamma": gamma,
        "project": project,
        "alpha_share": fixtures.share_for_tenant(api, project["id"], alpha["tenant"]["id"]),
        "beta_share": fixtures.share_for_tenant(api, project["id"], beta["tenant"]["id"]),
    }


# ─── The review / modification / revision cycle (PRD §3.5) ───────────────────


def test_revised_application_reenters_structural_review_with_the_lighter_schedule(api):
    """PRD §3.5: "A carrier whose application landed in `MODIFICATION_REQUIRED` may
    change its equipment lines and re-enter review, moving `MODIFICATION_REQUIRED →
    UNDER_STRUCTURAL_REVIEW` and optionally attaching a `revision_note`."

    The 800.100-load-unit antenna line is swapped for an 800.000-load-unit one
    before the revision, so the recomputed schedule of PRD §3.4 is 800.0.

    Design: Difficulty/non_linear_state_machine/application_review_modification_revision_cycle
    """
    world = crest_application_in_modification_required(api)
    tenant_headers = make_tenant_headers(world["tenant"]["id"])
    assert world["application"]["status"] == "MODIFICATION_REQUIRED"

    dropped = api.delete_equipment_line(world["lines"][0]["id"], tenant_headers)
    assert dropped.status_code == 204, dropped.text
    fixtures.add_equipment_line(
        api,
        world["application"]["id"],
        world["tenant"]["id"],
        equipment_type="ANTENNA",
        model_code="QX-80L",
        quantity=10,
        unit_weight_lbs=80,
        wind_area_sqft=0,
        mount_elevation_ft=80,
    )

    revised = validate_success(
        api.revise_colocation_application(
            world["application"]["id"],
            factories.revise_payload("swapped to the lighter antenna variant"),
            tenant_headers,
        ),
        200,
    )
    assert revised["status"] == "UNDER_STRUCTURAL_REVIEW"
    assert revised["revision_count"] == 1
    assertions.assert_load_units(revised["total_load_units"], 800.0, "total_load_units")


def test_revision_supersedes_the_analysis_that_forced_the_modification(api):
    """PRD §3.5: "Revising increments `revision_count` by one, recomputes
    `total_load_units` from the surviving lines, restamps `submitted_at` and
    recomputes `review_deadline_at`, sets every analysis of the application whose
    `status` is `ISSUED` or `QUOTED` to `SUPERSEDED`, and increments the tower's
    `open_review_count` by one."

    The superseded analysis keeps the figure it was issued with, which PRD §3.5
    fixes as "`projected_loading_pct` is one hundred times `included_load_units`
    divided by the tower's `rated_capacity_load_units`, rounded half up to three
    decimal places." — 3,800.100 over 4,000 load units, i.e. 95.003 percent.

    Design: Difficulty/non_linear_state_machine/application_review_modification_revision_cycle
    """
    world = crest_application_in_modification_required(api)
    tenant_headers = make_tenant_headers(world["tenant"]["id"])
    app_id = world["application"]["id"]
    analysis_id = world["analysis"]["id"]

    issued = fixtures.read_analysis(api, app_id, analysis_id)
    assertions.assert_analysis_outcome(
        issued,
        included_load_units=3800.1,
        projected_loading_pct=95.003,
        result="MODIFICATION_REQUIRED",
        status="ISSUED",
    )

    dropped = api.delete_equipment_line(world["lines"][0]["id"], tenant_headers)
    assert dropped.status_code == 204, dropped.text
    fixtures.add_equipment_line(
        api,
        app_id,
        world["tenant"]["id"],
        equipment_type="ANTENNA",
        model_code="QX-80L",
        quantity=10,
        unit_weight_lbs=80,
        wind_area_sqft=0,
        mount_elevation_ft=80,
    )
    validate_success(
        api.revise_colocation_application(
            app_id, factories.revise_payload("swapped to the lighter antenna variant"), tenant_headers
        ),
        200,
    )

    superseded = fixtures.read_analysis(api, app_id, analysis_id)
    assertions.assert_analysis_outcome(
        superseded, projected_loading_pct=95.003, result="MODIFICATION_REQUIRED", status="SUPERSEDED"
    )


def test_review_slot_is_released_on_modification_and_reclaimed_on_revision(api):
    """PRD §3.5: "A result of `MODIFICATION_REQUIRED` moves the application
    `UNDER_STRUCTURAL_REVIEW → MODIFICATION_REQUIRED`, decrements the tower's
    `open_review_count` by one, and recomputes `sla_breached`; this branch is only
    taken when the analysis just created is the only non-superseded analysis of the
    application."

    Re-entry restores the slot, because PRD §3.5 also says: "Revising increments
    `revision_count` by one, recomputes `total_load_units` from the surviving lines,
    restamps `submitted_at` and recomputes `review_deadline_at`, sets every analysis of
    the application whose `status` is `ISSUED` or `QUOTED` to `SUPERSEDED`, and
    increments the tower's `open_review_count` by one."

    Design: Difficulty/non_linear_state_machine/application_review_modification_revision_cycle
    """
    world = crest_application_in_modification_required(api)
    tenant_headers = make_tenant_headers(world["tenant"]["id"])
    tower_id = world["tower"]["id"]

    assertions.assert_tower_capacity(
        fixtures.read_tower(api, tower_id), open_review_count=0, capacity_posture="OPEN"
    )

    dropped = api.delete_equipment_line(world["lines"][0]["id"], tenant_headers)
    assert dropped.status_code == 204, dropped.text
    fixtures.add_equipment_line(
        api,
        world["application"]["id"],
        world["tenant"]["id"],
        equipment_type="ANTENNA",
        model_code="QX-80L",
        quantity=10,
        unit_weight_lbs=80,
        wind_area_sqft=0,
        mount_elevation_ft=80,
    )
    validate_success(
        api.revise_colocation_application(
            world["application"]["id"],
            factories.revise_payload("swapped to the lighter antenna variant"),
            tenant_headers,
        ),
        200,
    )

    assertions.assert_tower_capacity(
        fixtures.read_tower(api, tower_id), open_review_count=1, capacity_posture="OPEN"
    )


# ─── The two independent amendment axes (PRD §2.9, §3.7, §3.8) ───────────────


def test_billing_suspends_and_resumes_while_the_amendment_sits_under_notice(api):
    """PRD §2.9: "Between `EXECUTED` and `TERMINATED` the two axes evolve
    independently: billing can be suspended and resumed any number of times while
    occupancy continues untouched."

    Design: Difficulty/non_linear_state_machine/site_amendment_parallel_execution_and_billing_axes
    """
    world = ridge_site_with_approved_application(api)
    amendment = fixtures.paper_amendment(
        api,
        world["mla"]["id"],
        world["tower"]["id"],
        world["application"]["id"],
        restoration_deposit_cents=0,
        **RIDGE_AMENDMENT,
    )
    executed = fixtures.execute_amendment(api, amendment["id"])
    assertions.assert_amendment_axes(
        executed,
        execution_status="EXECUTED",
        billing_status="BILLING",
        restoration_status="NOT_REQUIRED",
    )

    suspended = validate_success(
        api.set_site_amendment_billing_status(
            amendment["id"], factories.billing_status_payload("SUSPENDED"), ADMIN_HEADERS
        ),
        200,
    )
    assertions.assert_amendment_axes(
        suspended, execution_status="EXECUTED", billing_status="SUSPENDED"
    )

    noticed = validate_success(
        api.give_termination_notice(
            amendment["id"], {}, make_tenant_headers(world["tenant"]["id"])
        ),
        200,
    )
    assertions.assert_amendment_axes(
        noticed,
        execution_status="TERMINATION_NOTICED",
        billing_status="SUSPENDED",
        restoration_status="PENDING",
    )

    resumed = validate_success(
        api.set_site_amendment_billing_status(
            amendment["id"], factories.billing_status_payload("BILLING"), ADMIN_HEADERS
        ),
        200,
    )
    assertions.assert_amendment_axes(
        resumed,
        execution_status="TERMINATION_NOTICED",
        billing_status="BILLING",
        restoration_status="PENDING",
    )


def test_resuming_billing_recomputes_the_compounded_site_rent(api):
    """PRD §3.7: "Moving `SUSPENDED → BILLING` requires the same `execution_status`
    set and recomputes `current_monthly_rent_cents`."

    PRD §3.7 pins the arithmetic: "For a base of 250,000 cents at an escalator of
    3.5 percent across four anniversaries, the pinned per-anniversary order yields
    286,880 cents, whereas the single-shot power form would yield 286,881; the
    implementation must produce 286,880."

    Design: Difficulty/non_linear_state_machine/site_amendment_parallel_execution_and_billing_axes
    """
    world = ridge_site_with_approved_application(api)
    amendment = fixtures.paper_amendment(
        api,
        world["mla"]["id"],
        world["tower"]["id"],
        world["application"]["id"],
        restoration_deposit_cents=0,
        **RIDGE_AMENDMENT,
    )
    fixtures.execute_amendment(api, amendment["id"])
    validate_success(
        api.set_site_amendment_billing_status(
            amendment["id"], factories.billing_status_payload("SUSPENDED"), ADMIN_HEADERS
        ),
        200,
    )
    fixtures.give_notice(api, amendment["id"], world["tenant"]["id"])

    resumed = validate_success(
        api.set_site_amendment_billing_status(
            amendment["id"], factories.billing_status_payload("BILLING"), ADMIN_HEADERS
        ),
        200,
    )
    assertions.assert_amendment_axes(
        resumed, execution_status="TERMINATION_NOTICED", billing_status="BILLING"
    )
    assertions.assert_cents(
        resumed["current_monthly_rent_cents"], 286880, "current_monthly_rent_cents"
    )
    assertions.assert_cents(
        fixtures.read_amendment(api, amendment["id"])["current_monthly_rent_cents"],
        286880,
        "current_monthly_rent_cents",
    )


def test_notice_of_departure_releases_no_load_or_ground_space(api):
    """PRD §3.8: "Critically, it releases nothing: the equipment is still on the
    structure, so the amendment keeps holding its load, its ground space and its
    elevation band on the tower until decommissioning actually completes."

    Design: Difficulty/non_linear_state_machine/site_amendment_parallel_execution_and_billing_axes
    """
    world = ridge_site_with_approved_application(api)
    tower_id = world["tower"]["id"]
    amendment = fixtures.paper_amendment(
        api,
        world["mla"]["id"],
        tower_id,
        world["application"]["id"],
        restoration_deposit_cents=0,
        **RIDGE_AMENDMENT,
    )
    fixtures.execute_amendment(api, amendment["id"])

    validate_success(
        api.set_site_amendment_billing_status(
            amendment["id"], factories.billing_status_payload("SUSPENDED"), ADMIN_HEADERS
        ),
        200,
    )
    fixtures.give_notice(api, amendment["id"], world["tenant"]["id"])
    validate_success(
        api.set_site_amendment_billing_status(
            amendment["id"], factories.billing_status_payload("BILLING"), ADMIN_HEADERS
        ),
        200,
    )

    tower = fixtures.read_tower(api, tower_id)
    assertions.assert_tower_capacity(
        tower,
        reserved_load_units=3815.0,
        reserved_load_pct=38.15,
        reserved_ground_space_sqft=500,
        available_ground_space_sqft=19500,
        capacity_posture="OPEN",
        occupied_band_count=1,
    )
    assertions.assert_occupied_band(
        tower["occupied_elevation_bands"][0],
        amendment_id=amendment["id"],
        bottom_ft=150,
        top_ft=190,
        tenant_id=world["tenant"]["id"],
    )


# ─── The cost-share fork and its stalled join (PRD §3.6) ─────────────────────


def test_pro_rata_shares_floor_each_beneficiary_and_hand_the_remainder_to_the_oldest(api):
    """PRD §3.6: "Under `PRO_RATA_LOAD`, a beneficiary's `share_cents` is
    `total_cost_cents` multiplied by that beneficiary's `basis_load_units`, divided
    by the total basis, with the result floored to whole cents."

    PRD §3.6 also fixes where the leftover cent goes: "The remainder recipient is
    chosen by ranking beneficiaries by `basis_created_at` ascending, then by the
    beneficiary tenant's own `created_at` ascending, then by `basis_load_units`
    ascending, and taking the first." The executed amendment is older than the
    applicant, so the single leftover cent lands on it.

    Design: Difficulty/non_linear_state_machine/modification_project_fork_join_stalled_branch
    """
    world = basin_fork_with_allocated_cost_shares(api)
    project = fixtures.read_project(api, world["project"]["id"])

    assert project["status"] == "COST_ALLOCATED"
    assertions.assert_cents(project["base_construction_cost_cents"], 20000000)
    assertions.assert_cents(project["engineering_fee_cents"], 2364000)
    assertions.assert_cents(project["total_cost_cents"], 22064000)
    assertions.assert_cents(project["allocated_cents"], 22064000)

    alpha_share = fixtures.read_cost_share(api, world["alpha_share"]["id"])
    beta_share = fixtures.read_cost_share(api, world["beta_share"]["id"])
    assert alpha_share["status"] == "PENDING"
    assert beta_share["status"] == "PENDING"
    assertions.assert_cents(alpha_share["share_cents"], 12743234, "share_cents")
    assertions.assert_cents(beta_share["share_cents"], 9320766, "share_cents")
    assert (
        alpha_share["share_cents"] + beta_share["share_cents"] == project["total_cost_cents"]
    ), "the shares of PRD §3.6 must sum to the project's total cost"


def test_accepting_one_share_leaves_the_project_waiting_on_its_sibling(api):
    """PRD §3.6: "A carrier accepting its own share — permitted only while the share
    is `PENDING` and the parent project is `COST_ALLOCATED`, otherwise
    `ERR_INVALID_COST_SHARE_STATE` — moves the share `PENDING → ACCEPTED` and stamps
    `accepted_at` with the logical clock."

    The join is only reached "When that acceptance leaves no non-voided sibling share
    still `PENDING`", so with one sibling outstanding the project stays where it was
    and nobody is billed.

    Design: Difficulty/non_linear_state_machine/modification_project_fork_join_stalled_branch
    """
    world = basin_fork_with_allocated_cost_shares(api)
    alpha = world["alpha"]

    accepted = validate_success(
        api.accept_cost_share(
            world["alpha_share"]["id"], {}, make_tenant_headers(alpha["tenant"]["id"])
        ),
        200,
    )
    assert accepted["status"] == "ACCEPTED"

    project = fixtures.read_project(api, world["project"]["id"])
    assert project["status"] == "COST_ALLOCATED"
    assertions.assert_tenant_ledger(
        fixtures.read_tenant(api, alpha["tenant"]["id"]),
        outstanding_balance_cents=0,
        credit_status="CURRENT",
    )
    assertions.assert_tower_capacity(
        fixtures.read_tower(api, world["tower"]["id"]),
        capacity_posture="OPEN",
        open_review_count=1,
    )


def test_declined_share_stalls_the_project_and_leaves_the_accepted_share_unbilled(api):
    """PRD §3.6: "The project then joins `COST_ALLOCATED → STALLED`, and the
    side-effect set is deliberately much thinner than the funded branch: every
    remaining `PENDING` share of the project is set to `VOIDED`; `ACCEPTED` shares are
    left exactly as they are and are **not** billed; and the tower's posture is
    recomputed but does not freeze, because a stalled project reserves nothing."

    Design: Difficulty/non_linear_state_machine/modification_project_fork_join_stalled_branch
    """
    world = basin_fork_with_allocated_cost_shares(api)
    alpha, beta = world["alpha"], world["beta"]
    fixtures.accept_share(api, world["alpha_share"]["id"], alpha["tenant"]["id"])

    declined = validate_success(
        api.decline_cost_share(
            world["beta_share"]["id"],
            factories.decline_cost_share_payload(
                "capital plan does not fund tower reinforcement this year"
            ),
            make_tenant_headers(beta["tenant"]["id"]),
        ),
        200,
    )
    assert declined["status"] == "DECLINED"
    assertions.assert_cents(declined["share_cents"], 9320766, "share_cents")

    project = fixtures.read_project(api, world["project"]["id"])
    assert project["status"] == "STALLED"
    assertions.assert_cents(project["total_cost_cents"], 22064000)

    alpha_share = fixtures.read_cost_share(api, world["alpha_share"]["id"])
    assert alpha_share["status"] == "ACCEPTED"
    assertions.assert_cents(alpha_share["share_cents"], 12743234, "share_cents")

    assertions.assert_tenant_ledger(
        fixtures.read_tenant(api, alpha["tenant"]["id"]),
        outstanding_balance_cents=0,
        credit_status="CURRENT",
    )
    assertions.assert_tenant_ledger(
        fixtures.read_tenant(api, beta["tenant"]["id"]),
        outstanding_balance_cents=0,
        credit_status="CURRENT",
    )


def test_stalled_reinforcement_neither_freezes_the_tower_nor_pushes_back_reviews(api):
    """PRD §3.6: "There is no billing, no freeze and no push-back of reviewing
    applications on this branch."

    Design: Difficulty/non_linear_state_machine/modification_project_fork_join_stalled_branch
    """
    world = basin_fork_with_allocated_cost_shares(api)
    fixtures.accept_share(api, world["alpha_share"]["id"], world["alpha"]["tenant"]["id"])
    fixtures.decline_share(api, world["beta_share"]["id"], world["beta"]["tenant"]["id"])

    assertions.assert_tower_capacity(
        fixtures.read_tower(api, world["tower"]["id"]),
        reserved_load_units=1600.0,
        capacity_posture="OPEN",
        open_review_count=1,
    )
    assert (
        fixtures.read_application(api, world["gamma"]["application"]["id"])["status"]
        == "UNDER_STRUCTURAL_REVIEW"
    )
    assert (
        fixtures.read_application(api, world["alpha"]["application"]["id"])["status"]
        == "MODIFICATION_REQUIRED"
    )
    assertions.assert_capacity_summary(
        fixtures.read_capacity_summary(api, world["tower"]["id"]),
        capacity_posture="OPEN",
        open_review_count=1,
        capacity_hold_application_count=0,
    )


# ─── Audit finalization, four levels deep (PRD §3.9) ─────────────────────────


def test_finalized_audit_bills_forty_one_whole_months_of_unauthorized_load(api):
    """PRD §3.9: "Under `INSTALL_DATE_BASIS`, `months_billable` is the gross count
    outright, with no ceiling — an installation forty-one months old bills forty-one
    months."

    PRD §3.9 pins the money in two steps: "First, the monthly rate is 25 cents per
    load unit multiplied by `observed_load_units`, rounded half up to whole cents.
    Second, `retroactive_billing_cents` is `months_billable` multiplied by that
    monthly rate multiplied by a penalty multiplier of 1.5, rounded half up to whole
    cents." — 41 months at 85,000 cents with the 1.5 multiplier is 5,227,500 cents.

    Design: Difficulty/transitive_cascade/audit_finalization_cascade_depth_four
    """
    world = mesa_tower_with_reviewing_application_and_open_finding(api)
    assert world["finding"]["status"] == "OPEN"

    finalized = validate_success(
        api.finalize_equipment_audit(world["audit"]["id"], {}, AUDITOR_HEADERS), 200
    )
    assert finalized["status"] == "FINALIZED"
    assertions.assert_cents(
        finalized["retroactive_billing_total_cents"], 5227500, "retroactive_billing_total_cents"
    )

    finding = fixtures.read_finding(api, world["finding"]["id"])
    assert finding["status"] == "BILLED"
    assert finding["months_billable"] == 41
    assertions.assert_cents(
        finding["retroactive_billing_cents"], 5227500, "retroactive_billing_cents"
    )


def test_retroactive_billing_carries_the_carrier_past_the_delinquency_threshold(api):
    """PRD §3.9: "Because the findings were billed, each affected tenant's
    `outstanding_balance_cents` is increased by that tenant's own finding total."

    PRD §2.12 then derives the standing: "`credit_status` is derived from that balance
    on every mutation of it: it is `DELINQUENT` when `outstanding_balance_cents` is
    greater than or equal to 5,000,000 cents (50,000 dollars), and `CURRENT`
    otherwise."

    Design: Difficulty/transitive_cascade/audit_finalization_cascade_depth_four
    """
    world = mesa_tower_with_reviewing_application_and_open_finding(api)
    tenant_id = world["tenant"]["id"]
    assertions.assert_tenant_ledger(
        fixtures.read_tenant(api, tenant_id),
        outstanding_balance_cents=0,
        credit_status="CURRENT",
    )

    validate_success(api.finalize_equipment_audit(world["audit"]["id"], {}, AUDITOR_HEADERS), 200)

    assertions.assert_tenant_ledger(
        fixtures.read_tenant(api, tenant_id),
        outstanding_balance_cents=5227500,
        credit_status="DELINQUENT",
    )


def test_delinquency_suspends_the_master_lease_and_holds_the_reviewing_application(api):
    """PRD §3.9: "Because the credit standing became `DELINQUENT`, every master lease
    agreement of that tenant whose `status` is `ACTIVE` has `application_privilege` set
    to `SUSPENDED`."

    PRD §3.9 continues to the fourth level: "And because those privileges were
    suspended, each of those leases' applications whose `status` is `SUBMITTED` or
    `UNDER_STRUCTURAL_REVIEW` moves to `ON_HOLD`, with the relevant tower's
    `open_review_count` decremented once for every application that was leaving
    review."

    Design: Difficulty/transitive_cascade/audit_finalization_cascade_depth_four
    """
    world = mesa_tower_with_reviewing_application_and_open_finding(api)
    tenant_id = world["tenant"]["id"]
    app_id = world["application"]["id"]
    tower_id = world["tower"]["id"]

    assert fixtures.read_application(api, app_id)["status"] == "UNDER_STRUCTURAL_REVIEW"
    assert (
        fixtures.read_master_lease(api, tenant_id, world["mla"]["id"])["application_privilege"]
        == "ENABLED"
    )
    assertions.assert_tower_capacity(fixtures.read_tower(api, tower_id), open_review_count=1)

    validate_success(api.finalize_equipment_audit(world["audit"]["id"], {}, AUDITOR_HEADERS), 200)

    assert (
        fixtures.read_master_lease(api, tenant_id, world["mla"]["id"])["application_privilege"]
        == "SUSPENDED"
    )
    assert fixtures.read_application(api, app_id)["status"] == "ON_HOLD"
    assertions.assert_tower_capacity(fixtures.read_tower(api, tower_id), open_review_count=0)


# ─── Decommissioning, four levels deep (PRD §3.8) ────────────────────────────


def test_completed_decommissioning_terminates_the_amendment_and_releases_the_deposit(api):
    """PRD §3.8: "It moves the amendment `TERMINATION_NOTICED → TERMINATED`, stamps
    `terminated_at` with the logical clock, sets `restoration_status` to `COMPLETE`
    and sets `billing_status` to `CLOSED`."

    PRD §3.8 then starts the ledger cascade: "Because the amendment terminated with
    restoration complete, the tenant's `outstanding_balance_cents` is **decreased** by
    `restoration_deposit_cents` — the deposit charged at execution is released."

    Design: Difficulty/transitive_cascade/decommission_deposit_release_cascade_restores_privilege
    """
    world = ridge_site_with_charged_deposit_and_notice_given(api)
    tenant_id = world["tenant"]["id"]
    assertions.assert_tenant_ledger(
        fixtures.read_tenant(api, tenant_id),
        outstanding_balance_cents=5000000,
        credit_status="DELINQUENT",
    )

    terminated = validate_success(
        api.complete_decommission(
            world["amendment"]["id"],
            factories.complete_decommission_payload(True),
            ADMIN_HEADERS,
        ),
        200,
    )
    assertions.assert_amendment_axes(
        terminated,
        execution_status="TERMINATED",
        billing_status="CLOSED",
        restoration_status="COMPLETE",
    )
    assert terminated["terminated_at"] is not None

    assertions.assert_tenant_ledger(
        fixtures.read_tenant(api, tenant_id),
        outstanding_balance_cents=0,
        credit_status="CURRENT",
    )


def test_released_deposit_restores_the_privilege_and_revives_the_held_application(api):
    """PRD §3.8: "Because the credit standing became `CURRENT`, every master lease
    agreement of that tenant whose `status` is `ACTIVE` has `application_privilege`
    recomputed to `ENABLED`."

    And the fourth level, per PRD §3.8: "And because those privileges were restored,
    each of those leases' applications in `ON_HOLD` moves `ON_HOLD → SUBMITTED`."

    Design: Difficulty/transitive_cascade/decommission_deposit_release_cascade_restores_privilege
    """
    world = ridge_site_with_charged_deposit_and_notice_given(api)
    tenant_id = world["tenant"]["id"]
    mla_id = world["mla"]["id"]
    held_app_id = world["second_application"]["id"]

    assert (
        fixtures.read_master_lease(api, tenant_id, mla_id)["application_privilege"] == "SUSPENDED"
    )
    assert fixtures.read_application(api, held_app_id)["status"] == "ON_HOLD"

    validate_success(
        api.complete_decommission(
            world["amendment"]["id"],
            factories.complete_decommission_payload(True),
            ADMIN_HEADERS,
        ),
        200,
    )

    assert fixtures.read_master_lease(api, tenant_id, mla_id)["application_privilege"] == "ENABLED"
    assert fixtures.read_application(api, held_app_id)["status"] == "SUBMITTED"


def test_decommissioning_returns_the_load_and_ground_space_to_the_tower(api):
    """PRD §3.8: "The tower's `reserved_load_units`, `reserved_ground_space_sqft`,
    `available_ground_space_sqft`, `occupied_elevation_bands`, `reserved_load_pct` and
    `capacity_posture` are all recomputed, which is where the released load and ground
    space actually come back."

    PRD §2.7 pins the figures they come back to: "Because reserved quantities are a
    pure function of the contributing set rather than a running total, they are a
    conserved quantity: executing an amendment and then completing its decommissioning
    restores `reserved_load_units` and `reserved_ground_space_sqft` to their exact
    pre-execution values, with no accumulated drift."

    Design: Difficulty/transitive_cascade/decommission_deposit_release_cascade_restores_privilege
    """
    world = ridge_site_with_charged_deposit_and_notice_given(api)
    tower_id = world["tower"]["id"]

    assertions.assert_tower_capacity(
        fixtures.read_tower(api, tower_id),
        reserved_load_units=3815.0,
        available_ground_space_sqft=19500,
        occupied_band_count=1,
    )

    validate_success(
        api.complete_decommission(
            world["amendment"]["id"],
            factories.complete_decommission_payload(True),
            ADMIN_HEADERS,
        ),
        200,
    )

    assertions.assert_tower_capacity(
        fixtures.read_tower(api, tower_id),
        reserved_load_units=2000.0,
        reserved_load_pct=20.0,
        reserved_ground_space_sqft=0,
        available_ground_space_sqft=20000,
        capacity_posture="OPEN",
        open_review_count=0,
        occupied_band_count=0,
    )


# ─── The funded join, five levels deep (PRD §3.6) ────────────────────────────


def test_last_acceptance_funds_the_project_and_bills_every_accepted_share(api):
    """PRD §3.6: "When that acceptance leaves no non-voided sibling share still
    `PENDING`, the project joins `COST_ALLOCATED → FUNDED`, and a substantial cascade
    fires: `funded_at` is stamped with the logical clock; every `ACCEPTED` share moves
    `ACCEPTED → BILLED` and its tenant's `outstanding_balance_cents` is increased by
    that share's `share_cents`; each affected tenant's `credit_status` is recomputed,
    and any flip to `DELINQUENT` sets `application_privilege` to `SUSPENDED` on that
    tenant's `ACTIVE` master leases and moves their `SUBMITTED` and
    `UNDER_STRUCTURAL_REVIEW` applications to `ON_HOLD`; the tower's `capacity_posture`
    is recomputed to `FROZEN`, because a funded reinforcement blocks new occupancy;
    every application on the tower in `UNDER_STRUCTURAL_REVIEW` is pushed
    `UNDER_STRUCTURAL_REVIEW → CAPACITY_HOLD`; and the tower's `version` is incremented
    by one."

    Design: Difficulty/transitive_cascade/funded_join_cascade_freezes_tower_and_pushes_reviews
    """
    world = basin_fork_with_allocated_cost_shares(api)
    alpha, beta = world["alpha"], world["beta"]
    fixtures.accept_share(api, world["beta_share"]["id"], beta["tenant"]["id"])
    assert fixtures.read_project(api, world["project"]["id"])["status"] == "COST_ALLOCATED"

    accepted = validate_success(
        api.accept_cost_share(
            world["alpha_share"]["id"], {}, make_tenant_headers(alpha["tenant"]["id"])
        ),
        200,
    )
    assert accepted["accepted_at"] is not None

    project = fixtures.read_project(api, world["project"]["id"])
    assert project["status"] == "FUNDED"
    assert project["funded_at"] is not None
    assertions.assert_cents(project["total_cost_cents"], 22064000)

    alpha_share = fixtures.read_cost_share(api, world["alpha_share"]["id"])
    beta_share = fixtures.read_cost_share(api, world["beta_share"]["id"])
    assert alpha_share["status"] == "BILLED"
    assert beta_share["status"] == "BILLED"
    assertions.assert_tenant_ledger(
        fixtures.read_tenant(api, alpha["tenant"]["id"]), outstanding_balance_cents=12743234
    )
    assertions.assert_tenant_ledger(
        fixtures.read_tenant(api, beta["tenant"]["id"]), outstanding_balance_cents=9320766
    )


def test_funding_flips_both_paying_carriers_delinquent_and_suspends_their_leases(api):
    """PRD §2.12: "When a balance change flips a tenant from `CURRENT` to
    `DELINQUENT`, every master lease agreement of that tenant whose `status` is
    `ACTIVE` has `application_privilege` set to `SUSPENDED`, and every application
    under those leases whose `status` is `SUBMITTED` or `UNDER_STRUCTURAL_REVIEW` moves
    to `ON_HOLD` — with the tower's `open_review_count` decremented once for each
    application that was leaving review."

    Design: Difficulty/transitive_cascade/funded_join_cascade_freezes_tower_and_pushes_reviews
    """
    world = basin_fork_with_allocated_cost_shares(api)
    alpha, beta = world["alpha"], world["beta"]
    fixtures.accept_share(api, world["beta_share"]["id"], beta["tenant"]["id"])

    validate_success(
        api.accept_cost_share(
            world["alpha_share"]["id"], {}, make_tenant_headers(alpha["tenant"]["id"])
        ),
        200,
    )

    assertions.assert_tenant_ledger(
        fixtures.read_tenant(api, alpha["tenant"]["id"]),
        outstanding_balance_cents=12743234,
        credit_status="DELINQUENT",
    )
    assertions.assert_tenant_ledger(
        fixtures.read_tenant(api, beta["tenant"]["id"]),
        outstanding_balance_cents=9320766,
        credit_status="DELINQUENT",
    )
    assert (
        fixtures.read_master_lease(api, alpha["tenant"]["id"], alpha["mla"]["id"])[
            "application_privilege"
        ]
        == "SUSPENDED"
    )
    assert (
        fixtures.read_master_lease(api, beta["tenant"]["id"], beta["mla"]["id"])[
            "application_privilege"
        ]
        == "SUSPENDED"
    )


def test_funded_reinforcement_freezes_the_tower_and_holds_an_unbilled_carriers_review(api):
    """PRD §2.8: "Otherwise, if any modification project on the tower has `status`
    equal to `FUNDED` or `IN_CONSTRUCTION`, the posture is `FROZEN`."

    The structural arm of the cascade reaches a carrier that owes nothing, because
    PRD §3.5 says: "Whenever a tower's posture is recomputed to `FROZEN` — by a
    ground-lease expiry sweep or by a reinforcement project becoming funded — every
    application on that tower in `UNDER_STRUCTURAL_REVIEW` is pushed back
    `UNDER_STRUCTURAL_REVIEW → CAPACITY_HOLD`, with `open_review_count` decremented by
    one for each."

    Design: Difficulty/transitive_cascade/funded_join_cascade_freezes_tower_and_pushes_reviews
    """
    world = basin_fork_with_allocated_cost_shares(api)
    alpha, beta, gamma = world["alpha"], world["beta"], world["gamma"]
    tower_id = world["tower"]["id"]
    fixtures.accept_share(api, world["beta_share"]["id"], beta["tenant"]["id"])
    assertions.assert_tower_capacity(
        fixtures.read_tower(api, tower_id), capacity_posture="OPEN", open_review_count=1
    )

    validate_success(
        api.accept_cost_share(
            world["alpha_share"]["id"], {}, make_tenant_headers(alpha["tenant"]["id"])
        ),
        200,
    )

    assertions.assert_tower_capacity(
        fixtures.read_tower(api, tower_id), capacity_posture="FROZEN", open_review_count=0
    )
    assert (
        fixtures.read_application(api, gamma["application"]["id"])["status"] == "CAPACITY_HOLD"
    )
    assertions.assert_tenant_ledger(
        fixtures.read_tenant(api, gamma["tenant"]["id"]),
        outstanding_balance_cents=0,
        credit_status="CURRENT",
    )
    assertions.assert_capacity_summary(
        fixtures.read_capacity_summary(api, tower_id),
        capacity_posture="FROZEN",
        open_review_count=0,
        capacity_hold_application_count=1,
    )
