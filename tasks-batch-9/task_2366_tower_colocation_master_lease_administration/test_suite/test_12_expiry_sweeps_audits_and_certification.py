"""Time-driven expiry sweeps, the capacity-posture submission branch, compliance
audit lifecycle and reinforcement certification.

Covers the logical-clock expiry sweeps of PRD §2.4, the posture gate of PRD §2.8
as it branches a submission in PRD §3.4, the audit walk-down lifecycle of
PRD §3.9, project certification in PRD §3.6 and the terminal execution axis of
PRD §2.9 / §3.8.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_INVALID_AMENDMENT_STATE,
    ERR_INVALID_AUDIT_STATE,
)
from test_helpers.assertions import (
    assert_amendment_axes,
    assert_cents,
    assert_clock_summary,
    assert_load_units,
    assert_tenant_ledger,
    assert_tower_capacity,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    ENGINEER_HEADERS,
    OTHER_ENGINEER_HEADERS,
)


def test_ground_lease_expiry_sweep_freezes_tower_and_holds_review(api):
    """PRD §2.4: "Because an expired ground lease means the tower company no longer
    has the right to be on the site, this cascades: the tower's `capacity_posture`
    is recomputed to `FROZEN`; because the posture became `FROZEN`, every
    colocation application on that tower whose `status` is
    `UNDER_STRUCTURAL_REVIEW` moves `UNDER_STRUCTURAL_REVIEW → CAPACITY_HOLD` and
    the tower's `open_review_count` consequently drops to 0; and the tower's
    `version` is incremented by one."

    Design: Corner/state_machines/ground_lease_expiry_sweep_freezes_tower_and_holds_review
    """
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "site_name": "Expiry Sweep Summit",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        landlord_overrides={
            "legal_name": "Sweep Land Trust",
            "remit_contact_email": "ap@sweep.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 300000,
            "escalator_pct": 2.0,
            "commencement_date": "2020-06-01",
            "term_end_date": "2026-12-31",
            "renewal_option_count": 0,
            "renewal_term_years": 5,
            "buyout_price_cents": 0,
        },
    )
    chain = fixtures.add_carrier_to_site(
        api,
        site,
        stage="SUBMITTED",
        tenant_overrides={"legal_name": "Sweep Spectrum", "carrier_code": "GLX"},
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
            "requested_ground_space_sqft": 300,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "GX-100",
                "quantity": 5,
                "unit_weight_lbs": 100,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
    )
    # The tower was OPEN, so the submission entered review and took a slot.
    assert chain["application"]["status"] == "UNDER_STRUCTURAL_REVIEW"
    assert_tower_capacity(
        fixtures.read_tower(api, site["tower"]["id"]),
        capacity_posture="OPEN",
        open_review_count=1,
    )

    summary = validate_success(
        api.set_clock(factories.clock_payload("2027-01-15T00:00:00Z"), ADMIN_HEADERS), 200
    )

    assert summary["current_utc"].startswith("2027-01-15T00:00:00")
    assert_clock_summary(
        summary,
        expired_ground_lease_count=1,
        expired_master_lease_count=0,
        frozen_tower_count=1,
    )
    lease = fixtures.read_ground_lease(api, site["ground_lease"]["id"])
    assert lease["status"] == "EXPIRED"
    assert_tower_capacity(
        fixtures.read_tower(api, site["tower"]["id"]),
        capacity_posture="FROZEN",
        open_review_count=0,
    )
    application = fixtures.read_application(api, chain["application"]["id"])
    assert application["status"] == "CAPACITY_HOLD"
    # The master lease outlives the clock advance, so its axis is untouched.
    mla = fixtures.read_master_lease(api, chain["tenant"]["id"], chain["mla"]["id"])
    assert mla["status"] == "ACTIVE"
    assert mla["application_privilege"] == "ENABLED"


def test_master_lease_expiry_sweep_suspends_privilege_and_holds_application(api):
    """PRD §2.4: "Second, every master lease agreement whose `status` is `ACTIVE`
    and whose `expires_on` falls before the new instant moves `ACTIVE → EXPIRED`,
    its `application_privilege` is set to `SUSPENDED`, and every application under
    it whose `status` is `SUBMITTED` or `UNDER_STRUCTURAL_REVIEW` moves to
    `ON_HOLD`."

    Design: Corner/state_machines/master_lease_expiry_sweep_suspends_privilege_and_holds_application
    """
    chain = fixtures.build_colocation_chain(
        api,
        stage="SUBMITTED",
        with_ground_lease=False,
        tower_overrides={
            "site_name": "Master Sweep Mesa",
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        tenant_overrides={"legal_name": "Master Sweep Mobile", "carrier_code": "MLX"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 5,
            "renewal_terms_count": 0,
            "expires_on": "2026-09-30",
        },
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 300,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "MX-100",
                "quantity": 5,
                "unit_weight_lbs": 100,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
    )
    tower_id = chain["tower"]["id"]
    assert chain["application"]["status"] == "UNDER_STRUCTURAL_REVIEW"
    assert_tower_capacity(fixtures.read_tower(api, tower_id), open_review_count=1)

    summary = validate_success(
        api.set_clock(factories.clock_payload("2026-10-01T00:00:00Z"), ADMIN_HEADERS), 200
    )

    assert_clock_summary(
        summary,
        expired_master_lease_count=1,
        expired_ground_lease_count=0,
        frozen_tower_count=0,
    )
    mla = fixtures.read_master_lease(api, chain["tenant"]["id"], chain["mla"]["id"])
    assert mla["status"] == "EXPIRED"
    assert mla["application_privilege"] == "SUSPENDED"
    application = fixtures.read_application(api, chain["application"]["id"])
    assert application["status"] == "ON_HOLD"
    # No ground lease expired, so the structural gate on this tower stays open
    # while the review slot is released by the application leaving review.
    assert_tower_capacity(
        fixtures.read_tower(api, tower_id),
        capacity_posture="OPEN",
        open_review_count=0,
    )


def test_submission_on_restricted_tower_branches_to_capacity_hold(api):
    """PRD §3.4: "If the posture is `RESTRICTED` or `FROZEN`, the application moves
    `SUBMITTED → CAPACITY_HOLD` instead, the tower's `open_review_count` is left
    unchanged because no review slot was consumed, and no structural analysis may
    be created for the application while it is held."

    Design: Corner/state_machines/submit_on_restricted_tower_branches_to_capacity_hold
    """
    chain = fixtures.build_colocation_chain(
        api,
        stage="DRAFT",
        with_ground_lease=False,
        tower_overrides={
            "site_name": "Restricted Rock",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 1000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
            "baseline_reserved_load_units": 950,
        },
        tenant_overrides={"legal_name": "Restricted Rock Radio", "carrier_code": "RST"},
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
            "requested_ground_space_sqft": 100,
        },
        lines=[
            {
                "equipment_type": "TMA",
                "model_code": "RS-10",
                "quantity": 1,
                "unit_weight_lbs": 10,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
    )
    tower_id = chain["tower"]["id"]
    # 950 of 1000 rated units is 95.000 percent, strictly above the 90.000
    # percent threshold of PRD §2.8, so the tower is RESTRICTED.
    assert_tower_capacity(
        fixtures.read_tower(api, tower_id),
        reserved_load_pct=95.0,
        capacity_posture="RESTRICTED",
        open_review_count=0,
    )

    application = validate_success(
        api.submit_colocation_application(
            chain["application"]["id"],
            {},
            chain["tenant_headers"],
        ),
        200,
    )

    assert application["status"] == "CAPACITY_HOLD"
    assert_load_units(application["total_load_units"], 10.0, "total_load_units")
    # The review commitment is still stamped: the clock stands at its cold-start
    # instant and the standard 45-day review period runs to 2026-09-15.
    assert application["submitted_at"].startswith("2026-08-01T00:00:00")
    assert application["review_deadline_at"].startswith("2026-09-15T00:00:00")
    assert_tower_capacity(
        fixtures.read_tower(api, tower_id),
        reserved_load_pct=95.0,
        capacity_posture="RESTRICTED",
        open_review_count=0,
    )


def test_audit_walk_down_start_moves_scheduled_to_in_progress(api):
    """PRD §3.9: "Starting the walk-down moves the audit `SCHEDULED → IN_PROGRESS`
    and requires `audit_date` to be at or before the current logical clock
    instant."

    Design: Corner/state_machines/audit_start_moves_scheduled_to_in_progress
    """
    tower = fixtures.new_tower(
        api,
        site_name="Audit Start Slope",
        structure_type="MONOPOLE",
        rated_capacity_load_units=5000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=200,
        ground_space_total_sqft=5000,
    )
    audit = fixtures.schedule_audit(
        api, tower["id"], audit_date="2026-07-31", basis="DISCOVERY_LIMITED"
    )
    assert audit["status"] == "SCHEDULED"

    started = validate_success(
        api.start_equipment_audit(audit["id"], {}, AUDITOR_HEADERS), 200
    )

    assert started["status"] == "IN_PROGRESS"
    # Nothing is billed until finalization runs.
    assert started["finding_count"] == 0
    assert_cents(
        started["retroactive_billing_total_cents"], 0, "retroactive_billing_total_cents"
    )


def test_finalizing_an_audit_that_was_never_started_is_rejected(api):
    """PRD §3.9: "Finalizing the audit moves it `IN_PROGRESS → FINALIZED` with no
    preconditions and is where the money is computed."

    Design: Corner/state_machines/audit_finalize_from_scheduled_rejected
    """
    tower = fixtures.new_tower(
        api,
        site_name="Audit Guard Gorge",
        structure_type="MONOPOLE",
        rated_capacity_load_units=5000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=200,
        ground_space_total_sqft=5000,
    )
    audit = fixtures.schedule_audit(
        api, tower["id"], audit_date="2026-07-31", basis="INSTALL_DATE_BASIS"
    )

    resp = api.finalize_equipment_audit(audit["id"], {}, AUDITOR_HEADERS)

    validate_error(resp, ERR_INVALID_AUDIT_STATE, 409)
    unchanged = fixtures.read_audit(api, tower["id"], audit["id"])
    assert unchanged["status"] == "SCHEDULED"
    assert_cents(
        unchanged["retroactive_billing_total_cents"], 0, "retroactive_billing_total_cents"
    )
    assert unchanged["finding_count"] == 0


def _funded_reinforcement_under_construction(api):
    """A tower frozen by a funded reinforcement project, ready for certification.

    The applicant's 800.1 load units sit on a tower rated 4000 with 3000 already
    reserved, so the analysis lands at 95.003 percent and requires modification
    (PRD §3.5). The quotation of 8,000,000 cents runs the cost pipeline of
    PRD §3.6 to a single 8,960,000-cent share, whose acceptance funds the project
    and freezes the tower.
    """
    chain = fixtures.build_colocation_chain(
        api,
        stage="REVIEWED",
        with_ground_lease=False,
        tower_overrides={
            "site_name": "Certified Crest",
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 4000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
            "baseline_reserved_load_units": 3000,
        },
        tenant_overrides={"legal_name": "Certified Crest Cellular", "carrier_code": "CRT"},
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
            "requested_ground_space_sqft": 300,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "CR-80",
                "quantity": 10,
                "unit_weight_lbs": 80.01,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
        variant="PRELIMINARY",
        engineer_headers=ENGINEER_HEADERS,
    )
    assert chain["application"]["status"] == "MODIFICATION_REQUIRED"

    quoted = fixtures.quoted_analysis_with_project(
        api,
        tower_id=chain["tower"]["id"],
        analysis_id=chain["analysis"]["id"],
        cost_cents=8000000,
        engineer_headers=ENGINEER_HEADERS,
        project_overrides={
            "construction_window_start_date": "2026-08-01",
            "construction_window_end_date": "2026-08-31",
            "allocation_basis": "PRO_RATA_LOAD",
        },
    )
    project = quoted["project"]
    fixtures.allocate_shares(api, project["id"], ENGINEER_HEADERS)
    share = fixtures.share_for_tenant(api, project["id"], chain["tenant"]["id"])
    fixtures.accept_share(api, share["id"], chain["tenant"]["id"])
    validate_success(api.start_construction(project["id"], {}, ENGINEER_HEADERS), 200)

    chain["project"] = project
    chain["share"] = share
    return chain


def test_reinforcement_certification_adds_capacity_and_lifts_the_freeze(api):
    """PRD §3.6: "Certification records `certified_by_user_id` as the acting
    operator identifier, increases the tower's `rated_capacity_load_units` by
    `added_capacity_load_units`, recomputes `reserved_load_pct`,
    `available_ground_space_sqft` and `capacity_posture` so the freeze is lifted,
    promotes the single held-application winner if the posture lands on `OPEN`,
    and increments the tower's `version` by one."

    Design: Corner/state_machines/certify_completion_adds_capacity_and_lifts_freeze
    """
    chain = _funded_reinforcement_under_construction(api)
    tower_id = chain["tower"]["id"]
    assert_tower_capacity(
        fixtures.read_tower(api, tower_id),
        rated_capacity_load_units=4000,
        reserved_load_pct=75.0,
        capacity_posture="FROZEN",
    )

    certified = validate_success(
        api.certify_completion(
            chain["project"]["id"],
            factories.certify_completion_payload(1000),
            OTHER_ENGINEER_HEADERS,
        ),
        200,
    )

    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == "eng-2"
    assert certified["proposing_engineer_user_id"] == "eng-1"
    assert_cents(certified["total_cost_cents"], 8960000, "total_cost_cents")
    assert float(certified["volume_discount_pct"]) == 0
    assert_tower_capacity(
        fixtures.read_tower(api, tower_id),
        rated_capacity_load_units=5000,
        reserved_load_units=3000.0,
        reserved_load_pct=60.0,
        available_ground_space_sqft=9000,
        capacity_posture="OPEN",
    )


def test_reinforcement_certification_leaves_the_billed_share_in_place(api):
    """PRD §2.12: "It decreases when the tenant pays cash, when a service-level
    rent credit is issued, when a restoration deposit is released on completed
    decommissioning, and when a billed cost share is reversed by project
    cancellation."

    Design: Corner/state_machines/certify_completion_adds_capacity_and_lifts_freeze
    """
    chain = _funded_reinforcement_under_construction(api)
    tenant_id = chain["tenant"]["id"]
    assert_tenant_ledger(
        fixtures.read_tenant(api, tenant_id),
        outstanding_balance_cents=8960000,
        credit_status="DELINQUENT",
    )

    validate_success(
        api.certify_completion(
            chain["project"]["id"],
            factories.certify_completion_payload(1000),
            OTHER_ENGINEER_HEADERS,
        ),
        200,
    )

    # Certification is not one of the events that reduces the balance, so the
    # funding billing stands even though the reinforcement is complete.
    share = fixtures.read_cost_share(api, chain["share"]["id"])
    assert share["status"] == "BILLED"
    assert_cents(share["share_cents"], 8960000, "share_cents")
    assert_tenant_ledger(
        fixtures.read_tenant(api, tenant_id),
        outstanding_balance_cents=8960000,
        credit_status="DELINQUENT",
    )
    application = fixtures.read_application(api, chain["application"]["id"])
    assert application["status"] == "MODIFICATION_REQUIRED"


def test_second_decommission_of_a_terminated_amendment_is_rejected(api):
    """PRD §2.9: "`execution_status` tracks signature and occupancy and runs
    `DRAFT`, `PENDING_SIGNATURE`, `EXECUTED`, `TERMINATION_NOTICED`,
    `TERMINATED`, `VOIDED`, with `TERMINATED` and `VOIDED` terminal."

    Design: Corner/state_machines/terminated_amendment_lockdown_rejects_second_decommission
    """
    chain = fixtures.build_colocation_chain(
        api,
        stage="EXECUTED",
        tower_overrides={
            "site_name": "Terminal Terrace",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        landlord_overrides={
            "legal_name": "Terrace Land Co",
            "remit_contact_email": "ap@terrace.example",
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
        tenant_overrides={"legal_name": "Terminal Terrace Telecom", "carrier_code": "TRM"},
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
            "requested_ground_space_sqft": 300,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "TM-100",
                "quantity": 5,
                "unit_weight_lbs": 100,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
        amendment_overrides={
            "effective_date": "2026-08-01",
            "term_end_date": "2031-05-31",
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
        },
    )
    amendment_id = chain["amendment"]["id"]
    fixtures.give_notice(api, amendment_id, chain["tenant"]["id"])
    fixtures.complete_decommission(api, amendment_id)

    resp = api.complete_decommission(
        amendment_id, factories.complete_decommission_payload(True), ADMIN_HEADERS
    )

    validate_error(resp, ERR_INVALID_AMENDMENT_STATE, 409)
    amendment = fixtures.read_amendment(api, amendment_id)
    assert_amendment_axes(
        amendment,
        execution_status="TERMINATED",
        billing_status="CLOSED",
        restoration_status="COMPLETE",
    )
    # The capacity release ran exactly once, so the reserved quantities sit at
    # their pre-execution values rather than being released twice.
    tower = fixtures.read_tower(api, chain["tower"]["id"])
    assert_tower_capacity(
        tower,
        reserved_load_units=0.0,
        reserved_ground_space_sqft=0,
        available_ground_space_sqft=9000,
        occupied_band_count=0,
    )
    assert tower["occupied_elevation_bands"] == []
