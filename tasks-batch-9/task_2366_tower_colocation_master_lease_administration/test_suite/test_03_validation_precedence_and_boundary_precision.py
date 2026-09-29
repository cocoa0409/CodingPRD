"""Validation precedence and boundary precision.

Covers the ordered validation ladder of PRD §2.6 — where a request trips two
rules at once and only the lower-numbered one may surface — together with the
boundary comparisons the PRD pins exactly: the structural PASS limit of PRD §3.5
read off the rounded percentage of PRD §2.10, the inclusive delinquency
threshold of PRD §2.12, and the degenerate zero-finding audit total of PRD §3.9.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_CONSTRUCTION_WINDOW_CONFLICT,
    ERR_LANDLORD_W9_MISSING,
    ERR_MLA_PRIVILEGE_SUSPENDED,
    ERR_NO_EQUIPMENT_LINES,
    ERR_PAYMENT_PERIOD_NOT_WHOLE_MONTHS,
    ERR_QUOTATION_MISSING,
)
from test_helpers.assertions import (
    assert_amendment_axes,
    assert_analysis_outcome,
    assert_cents,
    assert_tenant_ledger,
    assert_tower_capacity,
)
from test_helpers.constants import (
    DELINQUENCY_THRESHOLD_CENTS,
    STRUCTURAL_PASS_LIMIT_PCT,
)
from test_helpers.fixtures import DELINQUENCY_FINDING_TOTAL_CENTS
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ENGINEER_HEADERS,
    OTHER_AUDITOR_HEADERS,
)

# ─────────────────────────────────────────────────────────────────────────────
# Suspended application privilege versus an emptied equipment schedule
# ─────────────────────────────────────────────────────────────────────────────


def _carrier_in_modification_required_with_no_lines(api):
    """A MODIFICATION_REQUIRED application whose only line is gone and whose
    master lease has been suspended by an audit-driven delinquency."""
    tower = fixtures.new_tower(
        api,
        site_name="T7 Draw",
        structure_type="SELF_SUPPORT",
        rated_capacity_load_units=4000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=10000,
        baseline_reserved_load_units=3000,
        baseline_reserved_ground_sqft=0,
    )
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Golf Communications"},
        mla_overrides={
            "base_monthly_rent_cents": 190000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
    )
    tenant, mla = carrier["tenant"], carrier["mla"]
    application = fixtures.new_application(
        api,
        tower["id"],
        mla["id"],
        tenant["id"],
        requested_elevation_bottom_ft=100,
        requested_elevation_top_ft=140,
        requested_ground_space_sqft=400,
    )
    line = fixtures.add_equipment_line(
        api,
        application["id"],
        tenant["id"],
        model_code="QX-80",
        quantity=10,
        unit_weight_lbs=80.01,
        wind_area_sqft=0,
        mount_elevation_ft=80,
    )
    fixtures.submit_application(api, application["id"], tenant["id"])
    # 3000 baseline plus 800.1 subject load over a 4000 rating is 95.003%, so
    # the analysis requires modification and the application becomes editable.
    fixtures.run_analysis(api, application["id"], tower["id"], "PRELIMINARY")
    deletion = api.delete_equipment_line(line["id"], carrier["tenant_headers"])
    assert deletion.status_code == 204, deletion.text
    fixtures.make_tenant_delinquent(api, tower["id"], tenant["id"])
    return {
        "tower": tower,
        "tenant": tenant,
        "tenant_headers": carrier["tenant_headers"],
        "mla": mla,
        "application": application,
    }


def test_suspended_privilege_outranks_emptied_equipment_schedule_on_revision(api):
    """PRD §2.6: "The master lease agreement's `application_privilege` is `ENABLED`
    → `ERR_MLA_PRIVILEGE_SUSPENDED` (409), on application submit and application
    revise." The same section pins the ladder: "Checks are evaluated in the
    sequence below, and the first failure is the response; later checks are never
    reached." — so the suspended privilege reports ahead of the emptied schedule.

    Design: Difficulty/priority_pair_validation_conflict/privilege_suspension_outranks_missing_equipment_lines_returns_409
    """
    world = _carrier_in_modification_required_with_no_lines(api)

    response = api.revise_colocation_application(
        world["application"]["id"], {}, world["tenant_headers"]
    )
    validate_error(response, ERR_MLA_PRIVILEGE_SUSPENDED, 409)

    application = fixtures.read_application(api, world["application"]["id"])
    assert application["status"] == "MODIFICATION_REQUIRED"
    assert application["revision_count"] == 0

    mla = fixtures.read_master_lease(api, world["tenant"]["id"], world["mla"]["id"])
    assert mla["application_privilege"] == "SUSPENDED"
    assert mla["status"] == "ACTIVE"

    assert_tenant_ledger(
        fixtures.read_tenant(api, world["tenant"]["id"]),
        outstanding_balance_cents=DELINQUENCY_FINDING_TOTAL_CENTS,
        credit_status="DELINQUENT",
    )


def test_emptied_equipment_schedule_surfaces_once_arrears_privilege_restored(api):
    """PRD §2.6: "The application has at least one equipment line →
    `ERR_NO_EQUIPMENT_LINES` (422), on application submit and application revise."
    PRD §3.3 restores the higher-priority gate first: "If the tenant thereby flips
    from `DELINQUENT` to `CURRENT`, `application_privilege` is set to `ENABLED` on
    every `ACTIVE` master lease of that tenant and each of their applications
    sitting in `ON_HOLD` moves `ON_HOLD → SUBMITTED`."

    Design: Difficulty/priority_pair_validation_conflict/privilege_suspension_outranks_missing_equipment_lines_returns_409
    """
    world = _carrier_in_modification_required_with_no_lines(api)

    fixtures.pay_tenant_balance(
        api, world["tenant"]["id"], DELINQUENCY_FINDING_TOTAL_CENTS
    )
    mla = fixtures.read_master_lease(api, world["tenant"]["id"], world["mla"]["id"])
    assert mla["application_privilege"] == "ENABLED"

    response = api.revise_colocation_application(
        world["application"]["id"], {}, world["tenant_headers"]
    )
    validate_error(response, ERR_NO_EQUIPMENT_LINES, 422)

    application = fixtures.read_application(api, world["application"]["id"])
    assert application["status"] == "MODIFICATION_REQUIRED"
    assert application["revision_count"] == 0

    assert_tenant_ledger(
        fixtures.read_tenant(api, world["tenant"]["id"]),
        outstanding_balance_cents=0,
        credit_status="CURRENT",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Whole-month remittance periods versus the payee's tax documentation
# ─────────────────────────────────────────────────────────────────────────────


def _site_leased_from_a_payee_without_tax_documentation(api):
    """A tower with an ACTIVE ground lease whose landlord has no W-9 on file and
    whose ``paid_through_date`` is still null."""
    tower = fixtures.new_tower(
        api,
        site_name="T9 Flat",
        structure_type="MONOPOLE",
        rated_capacity_load_units=6000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=250,
        ground_space_total_sqft=12000,
    )
    landlord = fixtures.new_landlord(
        api,
        legal_name="Flat Acres Trust",
        remit_contact_email="trust@flat.example",
        w9_on_file=False,
    )
    lease = fixtures.new_ground_lease(api, tower["id"], landlord["id"])
    assert lease["paid_through_date"] is None
    return {"tower": tower, "landlord": landlord, "ground_lease": lease}


def test_mid_month_period_start_outranks_the_payee_tax_documentation_gate(api):
    """PRD §2.6: "On landlord payment creation, the overlap check precedes the
    contiguity check, which precedes the whole-months check, which precedes the
    tax-documentation check." PRD §3.2 states the whole-months rule itself: "the
    period must cover whole calendar months, so `period_start_date` must be the
    first calendar day of a month and `period_end_date` must be the last calendar
    day of a month, otherwise `ERR_PAYMENT_PERIOD_NOT_WHOLE_MONTHS`".

    Design: Difficulty/priority_pair_validation_conflict/whole_month_period_outranks_missing_w9_returns_422
    """
    world = _site_leased_from_a_payee_without_tax_documentation(api)
    lease_id = world["ground_lease"]["id"]

    response = api.create_landlord_payment(
        factories.landlord_payment_payload(lease_id, "2026-08-15", "2026-10-31"),
        ADMIN_HEADERS,
    )
    validate_error(response, ERR_PAYMENT_PERIOD_NOT_WHOLE_MONTHS, 422)

    lease = fixtures.read_ground_lease(api, lease_id)
    assert lease["paid_through_date"] is None
    assert lease["status"] == "ACTIVE"

    _rows, meta = validate_paginated(api.list_landlord_payments(lease_id, {}, ADMIN_HEADERS))
    assert meta["total_count"] == 0


def test_missing_payee_tax_documentation_surfaces_on_a_whole_month_period(api):
    """PRD §3.2: "Finally, the lease's landlord must have `w9_on_file` set to
    `true`, otherwise `ERR_LANDLORD_W9_MISSING`." With the period corrected to
    whole calendar months the higher-priority rule no longer applies, and PRD §2.6
    hands the response to the tax-documentation check.

    Design: Difficulty/priority_pair_validation_conflict/whole_month_period_outranks_missing_w9_returns_422
    """
    world = _site_leased_from_a_payee_without_tax_documentation(api)
    lease_id = world["ground_lease"]["id"]

    response = api.create_landlord_payment(
        factories.landlord_payment_payload(lease_id, "2026-08-01", "2026-10-31"),
        ADMIN_HEADERS,
    )
    validate_error(response, ERR_LANDLORD_W9_MISSING, 422)

    lease = fixtures.read_ground_lease(api, lease_id)
    assert lease["paid_through_date"] is None
    assert lease["status"] == "ACTIVE"

    _rows, meta = validate_paginated(api.list_landlord_payments(lease_id, {}, ADMIN_HEADERS))
    assert meta["total_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Construction-window contention versus an unquoted originating analysis
# ─────────────────────────────────────────────────────────────────────────────


def _tower_with_a_reserved_window_and_an_unquoted_analysis(api):
    """One PROPOSED project holding 2026-09-01..2026-10-31, plus a second
    analysis on the same tower left in ISSUED with no quotation."""
    tower = fixtures.new_tower(
        api,
        site_name="T8 Gap",
        structure_type="SELF_SUPPORT",
        rated_capacity_load_units=4000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=10000,
        baseline_reserved_load_units=3000,
        baseline_reserved_ground_sqft=0,
    )
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Hotel Spectrum"},
        mla_overrides={
            "base_monthly_rent_cents": 230000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
    )
    tenant, mla = carrier["tenant"], carrier["mla"]

    analyses = []
    for bottom_ft, top_ft in ((100, 140), (200, 240)):
        application = fixtures.new_application(
            api,
            tower["id"],
            mla["id"],
            tenant["id"],
            requested_elevation_bottom_ft=bottom_ft,
            requested_elevation_top_ft=top_ft,
            requested_ground_space_sqft=300,
        )
        fixtures.add_equipment_line(
            api,
            application["id"],
            tenant["id"],
            model_code="QX-80",
            quantity=10,
            unit_weight_lbs=80.01,
            wind_area_sqft=0,
            mount_elevation_ft=80,
        )
        fixtures.submit_application(api, application["id"], tenant["id"])
        analyses.append(
            (
                application,
                fixtures.run_analysis(api, application["id"], tower["id"], "PRELIMINARY"),
            )
        )

    first_application, first_analysis = analyses[0]
    second_application, second_analysis = analyses[1]
    quoted = fixtures.quoted_analysis_with_project(
        api,
        tower_id=tower["id"],
        analysis_id=first_analysis["id"],
        cost_cents=22400000,
        project_overrides={
            "construction_window_start_date": "2026-09-01",
            "construction_window_end_date": "2026-10-31",
        },
    )
    return {
        "tower": tower,
        "tenant": tenant,
        "held_project": quoted["project"],
        "first_application": first_application,
        "second_application": second_application,
        "unquoted_analysis": second_analysis,
    }


def test_construction_window_contention_outranks_unquoted_originating_analysis(api):
    """PRD §2.6: "No construction-window conflict on the tower →
    `ERR_CONSTRUCTION_WINDOW_CONFLICT` (409), on project proposal and on
    cost-share allocation." PRD §3.6 spells the conflict out: "no other
    modification project on the same tower whose `status` is `PROPOSED`,
    `COST_ALLOCATED`, `FUNDED` or `IN_CONSTRUCTION` may have a closed date
    interval from its own `construction_window_start_date` through its own
    `construction_window_end_date` that intersects this project's window on any
    calendar day, otherwise `ERR_CONSTRUCTION_WINDOW_CONFLICT`".

    Design: Difficulty/priority_pair_validation_conflict/window_conflict_outranks_missing_quotation_returns_409
    """
    world = _tower_with_a_reserved_window_and_an_unquoted_analysis(api)

    response = api.create_modification_project(
        factories.modification_project_payload(
            world["tower"]["id"],
            world["unquoted_analysis"]["id"],
            construction_window_start_date="2026-10-01",
            construction_window_end_date="2026-11-30",
        ),
        ENGINEER_HEADERS,
    )
    validate_error(response, ERR_CONSTRUCTION_WINDOW_CONFLICT, 409)

    held = fixtures.read_project(api, world["held_project"]["id"])
    assert held["status"] == "PROPOSED"
    assert held["construction_window_start_date"] == "2026-09-01"
    assert held["construction_window_end_date"] == "2026-10-31"

    analysis = fixtures.read_analysis(
        api, world["second_application"]["id"], world["unquoted_analysis"]["id"]
    )
    assert_analysis_outcome(
        analysis, projected_loading_pct=95.003, result="MODIFICATION_REQUIRED", status="ISSUED"
    )

    _rows, meta = validate_paginated(
        api.list_modification_projects({"tower_id": world["tower"]["id"]}, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1


def test_unquoted_originating_analysis_surfaces_on_a_free_construction_window(api):
    """PRD §3.6: "The originating analysis must have `status` equal to `QUOTED`
    with a `modification_construction_cost_cents` greater than zero, otherwise
    `ERR_QUOTATION_MISSING`." PRD §2.6 places it last of the pair: "The
    originating analysis carries a quotation → `ERR_QUOTATION_MISSING` (422), on
    project proposal and on cost-share allocation."

    Design: Difficulty/priority_pair_validation_conflict/window_conflict_outranks_missing_quotation_returns_409
    """
    world = _tower_with_a_reserved_window_and_an_unquoted_analysis(api)

    response = api.create_modification_project(
        factories.modification_project_payload(
            world["tower"]["id"],
            world["unquoted_analysis"]["id"],
            construction_window_start_date="2026-11-01",
            construction_window_end_date="2026-11-30",
        ),
        ENGINEER_HEADERS,
    )
    validate_error(response, ERR_QUOTATION_MISSING, 422)

    analysis = fixtures.read_analysis(
        api, world["second_application"]["id"], world["unquoted_analysis"]["id"]
    )
    assert_analysis_outcome(analysis, status="ISSUED", result="MODIFICATION_REQUIRED")

    assert fixtures.read_project(api, world["held_project"]["id"])["status"] == "PROPOSED"

    _rows, meta = validate_paginated(
        api.list_modification_projects({"tower_id": world["tower"]["id"]}, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# The structural PASS limit read off the rounded percentage
# ─────────────────────────────────────────────────────────────────────────────


def _two_submissions_straddling_the_pass_limit(api):
    """Two applications on a 4000-unit tower already carrying 3000 baseline
    units: one adding exactly 800.0 load units, one adding 800.1."""
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
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Juliet Networks"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
    )
    tenant, mla = carrier["tenant"], carrier["mla"]

    submissions = {}
    for key, bottom_ft, top_ft, model_code, unit_weight_lbs in (
        ("at_limit", 100, 140, "PX-80", 80),
        ("over_limit", 200, 240, "QX-80", 80.01),
    ):
        application = fixtures.new_application(
            api,
            tower["id"],
            mla["id"],
            tenant["id"],
            requested_elevation_bottom_ft=bottom_ft,
            requested_elevation_top_ft=top_ft,
            requested_ground_space_sqft=300,
        )
        fixtures.add_equipment_line(
            api,
            application["id"],
            tenant["id"],
            model_code=model_code,
            quantity=10,
            unit_weight_lbs=unit_weight_lbs,
            wind_area_sqft=0,
            mount_elevation_ft=80,
        )
        submissions[key] = fixtures.submit_application(api, application["id"], tenant["id"])
    return {"tower": tower, "tenant": tenant, **submissions}


def _issue_preliminary_analysis(api, application_id, tower_id):
    version = fixtures.read_tower_version(api, tower_id, ENGINEER_HEADERS)
    return validate_success(
        api.create_structural_analysis(
            factories.structural_analysis_payload(application_id, version, "PRELIMINARY"),
            ENGINEER_HEADERS,
        ),
        201,
    )


def test_projected_loading_of_exactly_the_pass_limit_clears_structural_review(api):
    """PRD §3.5: "The `result` is then read off that rounded percentage against
    two limits: at or below 95.000 percent the result is `PASS`; above 95.000
    percent but strictly below 100.000 percent the result is
    `MODIFICATION_REQUIRED`; at 100.000 percent or above the result is
    `CAPACITY_EXCEEDED`." PRD §3.5 also pins the consequence: "A `PASS` leaves the
    application in `UNDER_STRUCTURAL_REVIEW`."

    Design: Difficulty/boundary_precision_check/structural_pass_boundary_at_exactly_95_000_pct
    """
    world = _two_submissions_straddling_the_pass_limit(api)

    analysis = _issue_preliminary_analysis(
        api, world["at_limit"]["id"], world["tower"]["id"]
    )
    assert_analysis_outcome(
        analysis,
        included_load_units=3800.0,
        projected_loading_pct=STRUCTURAL_PASS_LIMIT_PCT,
        result="PASS",
        variant="PRELIMINARY",
        status="ISSUED",
    )

    application = fixtures.read_application(api, world["at_limit"]["id"])
    assert application["status"] == "UNDER_STRUCTURAL_REVIEW"

    # Neither submission has left review, so no review slot was given back.
    assert_tower_capacity(fixtures.read_tower(api, world["tower"]["id"]), open_review_count=2)


def test_projected_loading_rounding_one_step_above_the_pass_limit_requires_modification(api):
    """PRD §2.10: "Every threshold comparison against a percentage is made against
    the **rounded** value, never against the unrounded intermediate." PRD §3.5
    then states the consequence: "A result of `MODIFICATION_REQUIRED` moves the
    application `UNDER_STRUCTURAL_REVIEW → MODIFICATION_REQUIRED`, decrements the
    tower's `open_review_count` by one, and recomputes `sla_breached`".

    Design: Difficulty/boundary_precision_check/structural_pass_boundary_at_exactly_95_000_pct
    """
    world = _two_submissions_straddling_the_pass_limit(api)

    _issue_preliminary_analysis(api, world["at_limit"]["id"], world["tower"]["id"])
    analysis = _issue_preliminary_analysis(
        api, world["over_limit"]["id"], world["tower"]["id"]
    )
    # 3800.1 of 4000 is 95.0025%, which rounds half up to 95.003%.
    assert_analysis_outcome(
        analysis,
        included_load_units=3800.1,
        projected_loading_pct=95.003,
        result="MODIFICATION_REQUIRED",
        variant="PRELIMINARY",
        status="ISSUED",
    )

    assert (
        fixtures.read_application(api, world["over_limit"]["id"])["status"]
        == "MODIFICATION_REQUIRED"
    )
    assert (
        fixtures.read_application(api, world["at_limit"]["id"])["status"]
        == "UNDER_STRUCTURAL_REVIEW"
    )
    assert_tower_capacity(fixtures.read_tower(api, world["tower"]["id"]), open_review_count=1)


# ─────────────────────────────────────────────────────────────────────────────
# The inclusive delinquency threshold on the receivable ledger
# ─────────────────────────────────────────────────────────────────────────────


def _papered_amendment_with_threshold_sized_deposit(api):
    """An APPROVED application papered into a DRAFT amendment whose restoration
    deposit is exactly the delinquency threshold."""
    return fixtures.build_colocation_chain(
        api,
        stage="PAPERED",
        tower_overrides={
            "site_name": "T1 Ridge",
            "baseline_reserved_load_units": 2000,
        },
        tenant_overrides={"legal_name": "Kilo Wireless"},
        amendment_overrides={
            "effective_date": "2022-08-01",
            "restoration_deposit_cents": DELINQUENCY_THRESHOLD_CENTS,
        },
    )


def test_restoration_deposit_landing_on_the_threshold_suspends_the_master_lease(api):
    """PRD §2.12: "The comparison is inclusive at the boundary — a balance of
    exactly 5,000,000 cents is `DELINQUENT`, and 4,999,999 cents is `CURRENT`."
    PRD §3.7 supplies the charge: "The tenant's `outstanding_balance_cents` is
    increased by `restoration_deposit_cents` and `credit_status` recomputed
    accordingly."

    Design: Difficulty/boundary_precision_check/delinquency_threshold_exact_boundary_on_tenant_payment
    """
    world = _papered_amendment_with_threshold_sized_deposit(api)

    amendment = validate_success(
        api.execute_site_amendment(
            world["amendment"]["id"], factories.execute_payload(True), ADMIN_HEADERS
        ),
        200,
    )
    assert_amendment_axes(
        amendment,
        execution_status="EXECUTED",
        billing_status="BILLING",
        restoration_status="PENDING",
    )
    assert_cents(
        amendment["restoration_deposit_cents"],
        DELINQUENCY_THRESHOLD_CENTS,
        "restoration_deposit_cents",
    )

    assert_tenant_ledger(
        fixtures.read_tenant(api, world["tenant"]["id"]),
        outstanding_balance_cents=DELINQUENCY_THRESHOLD_CENTS,
        credit_status="DELINQUENT",
    )
    mla = fixtures.read_master_lease(api, world["tenant"]["id"], world["mla"]["id"])
    assert mla["application_privilege"] == "SUSPENDED"
    assert mla["status"] == "ACTIVE"


def test_one_cent_payment_below_the_threshold_restores_application_privilege(api):
    """PRD §2.12: "The comparison is inclusive at the boundary — a balance of
    exactly 5,000,000 cents is `DELINQUENT`, and 4,999,999 cents is `CURRENT`."
    PRD §3.3 states what the cash does: "The payment decreases
    `outstanding_balance_cents` by that amount and recomputes `credit_status`."

    Design: Difficulty/boundary_precision_check/delinquency_threshold_exact_boundary_on_tenant_payment
    """
    world = _papered_amendment_with_threshold_sized_deposit(api)
    fixtures.execute_amendment(api, world["amendment"]["id"])

    tenant = validate_success(
        api.create_tenant_payment(
            world["tenant"]["id"], factories.tenant_payment_payload(1), ADMIN_HEADERS
        ),
        200,
    )
    assert_tenant_ledger(
        tenant,
        outstanding_balance_cents=DELINQUENCY_THRESHOLD_CENTS - 1,
        credit_status="CURRENT",
    )

    mla = fixtures.read_master_lease(api, world["tenant"]["id"], world["mla"]["id"])
    assert mla["application_privilege"] == "ENABLED"

    # The deposit itself is untouched: the restoration obligation is still open.
    amendment = fixtures.read_amendment(api, world["amendment"]["id"])
    assert_amendment_axes(
        amendment, execution_status="EXECUTED", restoration_status="PENDING"
    )
    assert_cents(
        amendment["restoration_deposit_cents"],
        DELINQUENCY_THRESHOLD_CENTS,
        "restoration_deposit_cents",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Finalizing a walk-down that found nothing
# ─────────────────────────────────────────────────────────────────────────────


def _clean_walk_down_in_progress(api):
    """A started audit on a tower where nothing unauthorized was found."""
    tower = fixtures.new_tower(
        api,
        site_name="T3 Summit",
        structure_type="GUYED",
        rated_capacity_load_units=7200,
        min_colocation_elevation_ft=50,
        max_elevation_ft=320,
        ground_space_total_sqft=14000,
        baseline_reserved_load_units=3000,
        baseline_reserved_ground_sqft=0,
    )
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Lima Broadband"},
        mla_overrides={
            "base_monthly_rent_cents": 175000,
            "escalator_pct": 2.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
    )
    audit = fixtures.schedule_audit(
        api,
        tower["id"],
        OTHER_AUDITOR_HEADERS,
        audit_date="2026-07-31",
        basis="DISCOVERY_LIMITED",
    )
    fixtures.start_audit(api, audit["id"], OTHER_AUDITOR_HEADERS)
    return {
        "tower": tower,
        "tenant": carrier["tenant"],
        "mla": carrier["mla"],
        "audit": audit,
    }


def test_finalizing_a_walk_down_with_no_findings_writes_a_zero_total(api):
    """PRD §3.9: "Each finding then moves `OPEN → BILLED`, and the audit's
    `retroactive_billing_total_cents` is the sum of `retroactive_billing_cents`
    across the audit's findings, which is 0 when the audit recorded none." PRD
    §3.9 also states the transition has no gate: "Finalizing the audit moves it
    `IN_PROGRESS → FINALIZED` with no preconditions and is where the money is
    computed."

    Design: Difficulty/boundary_precision_check/empty_finding_set_audit_finalize_yields_zero_total
    """
    world = _clean_walk_down_in_progress(api)

    audit = validate_success(
        api.finalize_equipment_audit(world["audit"]["id"], {}, OTHER_AUDITOR_HEADERS), 200
    )
    assert audit["status"] == "FINALIZED"
    assert audit["finding_count"] == 0
    assert_cents(
        audit["retroactive_billing_total_cents"], 0, "retroactive_billing_total_cents"
    )
    assert audit["basis"] == "DISCOVERY_LIMITED"

    _rows, meta = validate_paginated(
        api.list_audit_findings({"equipment_audit_id": world["audit"]["id"]}, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0


def test_finalizing_a_walk_down_with_no_findings_leaves_every_carrier_untouched(api):
    """PRD §3.9: "Because the findings were billed, each affected tenant's
    `outstanding_balance_cents` is increased by that tenant's own finding total."
    With no findings there is no affected tenant, and PRD §2.12 keeps the standing
    that follows from an untouched balance: it is "`DELINQUENT` when
    `outstanding_balance_cents` is greater than or equal to 5,000,000 cents
    (50,000 dollars), and `CURRENT` otherwise".

    Design: Difficulty/boundary_precision_check/empty_finding_set_audit_finalize_yields_zero_total
    """
    world = _clean_walk_down_in_progress(api)

    validate_success(
        api.finalize_equipment_audit(world["audit"]["id"], {}, OTHER_AUDITOR_HEADERS), 200
    )

    assert_tenant_ledger(
        fixtures.read_tenant(api, world["tenant"]["id"]),
        outstanding_balance_cents=0,
        credit_status="CURRENT",
    )
    mla = fixtures.read_master_lease(api, world["tenant"]["id"], world["mla"]["id"])
    assert mla["application_privilege"] == "ENABLED"
    assert mla["status"] == "ACTIVE"
