"""Term, renewal, buyout, audit-dating and fiscal-amount validations.

Covers the later rungs of the validation ladder of PRD §2.6: the amendment term
that may not outlast its ground lease (§3.7), the ground-lease renewal window and
its option count and the zero-price buyout (§3.2), the supersede target that must
already be executed (§3.7), the beneficiary set a cost allocation needs (§3.6),
the audit and finding dating rules (§3.9), the strictly positive tenant payment
(§3.3) and the strictly monotonic logical clock (§2.4).
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_AUDIT_DATE_IN_FUTURE,
    ERR_BUYOUT_NOT_AVAILABLE,
    ERR_CLOCK_NOT_MONOTONIC,
    ERR_COST_SHARE_BENEFICIARY_INVALID,
    ERR_FINDING_DATE_AFTER_AUDIT,
    ERR_INVALID_PAYMENT_AMOUNT,
    ERR_NO_RENEWAL_OPTIONS_REMAINING,
    ERR_RENEWAL_WINDOW_CLOSED,
    ERR_SUPERSEDE_TARGET_INVALID,
    ERR_TERM_EXCEEDS_GROUND_LEASE,
)
from test_helpers.assertions import (
    assert_amendment_axes,
    assert_cents,
    assert_clock_summary,
    assert_occupied_band,
    assert_tenant_ledger,
    assert_tower_capacity,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    OTHER_ENGINEER_HEADERS,
    make_tenant_headers,
)

# ─────────────────────────────────────────────────────────────────────────────
# Shared worlds
# ─────────────────────────────────────────────────────────────────────────────


def _carrier_with_two_approved_applications(
    api,
    *,
    site_name,
    landlord_name,
    landlord_email,
    tenant_name,
    carrier_code,
):
    """One carrier holding two approved applications in disjoint elevation bands
    on a tower whose ground lease is ACTIVE through 2031-05-31."""
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "site_name": site_name,
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        landlord_overrides={
            "legal_name": landlord_name,
            "remit_contact_email": landlord_email,
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
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": tenant_name, "carrier_code": carrier_code},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 15,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
    )
    tower, tenant, mla = site["tower"], carrier["tenant"], carrier["mla"]

    applications = []
    for bottom, top, model_code in ((100, 140, "TG-100"), (200, 240, "TG-100B")):
        application = fixtures.new_application(
            api,
            tower["id"],
            mla["id"],
            tenant["id"],
            requested_elevation_bottom_ft=bottom,
            requested_elevation_top_ft=top,
            requested_ground_space_sqft=300,
        )
        fixtures.add_equipment_line(
            api,
            application["id"],
            tenant["id"],
            equipment_type="ANTENNA",
            model_code=model_code,
            quantity=5,
            unit_weight_lbs=100,
            wind_area_sqft=0,
            mount_elevation_ft=80,
        )
        fixtures.submit_application(api, application["id"], tenant["id"])
        fixtures.run_analysis(api, application["id"], tower["id"], "PRELIMINARY")
        applications.append(fixtures.approve_application(api, application["id"]))

    return {
        "tower": tower,
        "ground_lease": site["ground_lease"],
        "tenant": tenant,
        "mla": mla,
        "applications": applications,
    }


def _ground_lease_only(api, *, site_name, landlord_name, landlord_email, **lease_overrides):
    """A tower with a single ACTIVE ground lease and nothing standing on it."""
    lease_payload = {
        "base_monthly_rent_cents": 300000,
        "escalator_pct": 2.0,
        "commencement_date": "2020-06-01",
        "term_end_date": "2031-05-31",
        "renewal_option_count": 1,
        "renewal_term_years": 5,
        "buyout_price_cents": 9000000,
    }
    lease_payload.update(lease_overrides)
    return fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "site_name": site_name,
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        landlord_overrides={
            "legal_name": landlord_name,
            "remit_contact_email": landlord_email,
            "w9_on_file": True,
        },
        lease_overrides=lease_payload,
    )


# ─────────────────────────────────────────────────────────────────────────────
# The amendment term against the ground lease term (PRD §3.7)
# ─────────────────────────────────────────────────────────────────────────────


def test_amendment_term_outlasting_the_ground_lease_rejected(api):
    """PRD §2.6: "The amendment term does not outlast the ground lease term →
    `ERR_TERM_EXCEEDS_GROUND_LEASE` (422), on amendment execution."

    Design: Corner/validations/amendment_term_beyond_ground_lease_rejected
    """
    world = _carrier_with_two_approved_applications(
        api,
        site_name="Term Edge Grade",
        landlord_name="Term Edge Land",
        landlord_email="ap@termedge.example",
        tenant_name="Term Edge Telecom",
        carrier_code="TEG",
    )
    tower, mla = world["tower"], world["mla"]
    long_amendment = fixtures.paper_amendment(
        api,
        mla["id"],
        tower["id"],
        world["applications"][0]["id"],
        effective_date="2026-08-01",
        term_end_date="2031-06-01",
        base_monthly_rent_cents=200000,
        escalator_pct=3.0,
    )
    version_before = fixtures.read_tower(api, tower["id"])["version"]

    resp = api.execute_site_amendment(
        long_amendment["id"], factories.execute_payload(True), ADMIN_HEADERS
    )
    validate_error(resp, ERR_TERM_EXCEEDS_GROUND_LEASE, 422)

    # The amendment did not claim the structure: it is still an unsigned draft.
    unchanged = fixtures.read_amendment(api, long_amendment["id"])
    assert_amendment_axes(
        unchanged,
        execution_status="DRAFT",
        billing_status="NOT_BILLING",
        restoration_status="NOT_REQUIRED",
    )
    assert unchanged["version"] == long_amendment["version"]

    tower_after = fixtures.read_tower(api, tower["id"])
    assert_tower_capacity(
        tower_after,
        reserved_load_units=0,
        reserved_ground_space_sqft=0,
        available_ground_space_sqft=9000,
        occupied_band_count=0,
        capacity_posture="OPEN",
    )
    assert tower_after["version"] == version_before


def test_amendment_term_ending_on_the_ground_lease_end_date_executes(api):
    """PRD §3.7: "the amendment's `term_end_date` must be at or before that active
    ground lease's own `term_end_date` (`ERR_TERM_EXCEEDS_GROUND_LEASE`)"

    Design: Corner/validations/amendment_term_beyond_ground_lease_rejected
    """
    world = _carrier_with_two_approved_applications(
        api,
        site_name="Term Edge Grade",
        landlord_name="Term Edge Land",
        landlord_email="ap@termedge.example",
        tenant_name="Term Edge Telecom",
        carrier_code="TEG",
    )
    tower, mla, tenant = world["tower"], world["mla"], world["tenant"]
    edge_amendment = fixtures.paper_amendment(
        api,
        mla["id"],
        tower["id"],
        world["applications"][1]["id"],
        effective_date="2026-08-01",
        term_end_date="2031-05-31",
        base_monthly_rent_cents=200000,
        escalator_pct=3.0,
    )

    resp = api.execute_site_amendment(
        edge_amendment["id"], factories.execute_payload(True), ADMIN_HEADERS
    )
    executed = validate_success(resp, 200)
    assert_amendment_axes(executed, execution_status="EXECUTED", billing_status="BILLING")

    # The amendment now holds its load, ground space and elevation band.
    tower_after = fixtures.read_tower(api, tower["id"])
    assert_tower_capacity(
        tower_after,
        reserved_load_units=500.0,
        reserved_ground_space_sqft=300,
        available_ground_space_sqft=8700,
        occupied_band_count=1,
    )
    assert_occupied_band(
        tower_after["occupied_elevation_bands"][0],
        amendment_id=edge_amendment["id"],
        bottom_ft=200,
        top_ft=240,
        tenant_id=tenant["id"],
    )
    assert (
        fixtures.read_master_lease(api, tenant["id"], mla["id"])["executed_amendment_count"] == 1
    )


# ─────────────────────────────────────────────────────────────────────────────
# The ground-lease renewal window and its options (PRD §3.2)
# ─────────────────────────────────────────────────────────────────────────────


def test_renewal_opened_before_the_365_day_window_rejected(api):
    """PRD §3.2: "Opening a renewal moves the lease `ACTIVE → RENEWAL_NEGOTIATION`
    and requires two things: that `renewals_exercised` is still strictly less than
    `renewal_option_count`, otherwise `ERR_NO_RENEWAL_OPTIONS_REMAINING`; and that
    the logical clock date has reached the point one year — 365 days — before
    `term_end_date`, meaning the clock date must be at or after `term_end_date`
    minus 365 days, otherwise `ERR_RENEWAL_WINDOW_CLOSED`."

    Design: Corner/validations/renewal_outside_365_day_window_rejected
    """
    site = _ground_lease_only(
        api,
        site_name="Renewal Window Notch",
        landlord_name="Renewal Notch Land",
        landlord_email="ap@renewalnotch.example",
    )
    lease = site["ground_lease"]

    resp = api.open_ground_lease_renewal(lease["id"], {}, ADMIN_HEADERS)
    validate_error(resp, ERR_RENEWAL_WINDOW_CLOSED, 422)

    unchanged = fixtures.read_ground_lease(api, lease["id"])
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["renewals_exercised"] == 0
    assert unchanged["term_end_date"] == "2031-05-31"
    assert unchanged["version"] == lease["version"]


def test_renewal_opened_on_the_window_boundary_day_accepted(api):
    """PRD §3.2: "Opening a renewal moves the lease `ACTIVE → RENEWAL_NEGOTIATION`
    and requires two things: that `renewals_exercised` is still strictly less than
    `renewal_option_count`, otherwise `ERR_NO_RENEWAL_OPTIONS_REMAINING`; and that
    the logical clock date has reached the point one year — 365 days — before
    `term_end_date`, meaning the clock date must be at or after `term_end_date`
    minus 365 days, otherwise `ERR_RENEWAL_WINDOW_CLOSED`."

    Design: Corner/validations/renewal_outside_365_day_window_rejected
    """
    site = _ground_lease_only(
        api,
        site_name="Renewal Window Notch",
        landlord_name="Renewal Notch Land",
        landlord_email="ap@renewalnotch.example",
    )
    lease = site["ground_lease"]

    # 2030-05-31 is exactly 365 days before the 2031-05-31 term end.
    summary = fixtures.advance_clock(api, "2030-05-31T00:00:00Z")
    assert_clock_summary(
        summary,
        expired_ground_lease_count=0,
        expired_master_lease_count=0,
        frozen_tower_count=0,
    )

    resp = api.open_ground_lease_renewal(lease["id"], {}, ADMIN_HEADERS)
    opened = validate_success(resp, 200)
    assert opened["status"] == "RENEWAL_NEGOTIATION"

    # Opening negotiation consumes no option and moves no dates.
    assert opened["renewals_exercised"] == 0
    assert opened["term_end_date"] == "2031-05-31"


def test_renewal_opened_with_no_options_remaining_rejected(api):
    """PRD §2.6: "A renewal option remains → `ERR_NO_RENEWAL_OPTIONS_REMAINING`
    (422), on opening a renewal and on exercising a renewal."

    Design: Corner/validations/renewal_without_remaining_options_rejected
    """
    site = _ground_lease_only(
        api,
        site_name="Renewal Exhausted Hill",
        landlord_name="Exhausted Hill Land",
        landlord_email="ap@exhaustedhill.example",
    )
    lease = site["ground_lease"]

    fixtures.advance_clock(api, "2030-06-01T00:00:00Z")
    validate_success(api.open_ground_lease_renewal(lease["id"], {}, ADMIN_HEADERS), 200)
    renewed = validate_success(api.renew_ground_lease(lease["id"], {}, ADMIN_HEADERS), 200)
    assert renewed["renewals_exercised"] == 1
    assert renewed["term_end_date"] == "2036-05-31"

    # 2035-06-01 is exactly 365 days before the renewed 2036-05-31 term end, so
    # the window is open and only the exhausted option count can bind.
    fixtures.advance_clock(api, "2035-06-01T00:00:00Z")

    resp = api.open_ground_lease_renewal(lease["id"], {}, ADMIN_HEADERS)
    validate_error(resp, ERR_NO_RENEWAL_OPTIONS_REMAINING, 422)

    unchanged = fixtures.read_ground_lease(api, lease["id"])
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["renewals_exercised"] == 1
    assert unchanged["term_end_date"] == "2036-05-31"


def test_buyout_of_a_lease_with_no_negotiated_price_rejected(api):
    """PRD §3.2: "Buying out the landlord's interest is available from either
    `ACTIVE` or `RENEWAL_NEGOTIATION` and requires `buyout_price_cents` to be
    strictly greater than zero, otherwise `ERR_BUYOUT_NOT_AVAILABLE`."

    Design: Corner/validations/buyout_rejected_when_price_is_zero
    """
    site = _ground_lease_only(
        api,
        site_name="Buyout Zero Basin",
        landlord_name="Zero Basin Land",
        landlord_email="ap@zerobasin.example",
        buyout_price_cents=0,
    )
    lease = site["ground_lease"]

    resp = api.buyout_ground_lease(lease["id"], {}, ADMIN_HEADERS)
    validate_error(resp, ERR_BUYOUT_NOT_AVAILABLE, 422)

    unchanged = fixtures.read_ground_lease(api, lease["id"])
    assert unchanged["status"] == "ACTIVE"
    assert_cents(unchanged["buyout_paid_cents"], 0, "buyout_paid_cents")
    assert unchanged["paid_through_date"] is None
    assert unchanged["version"] == lease["version"]


# ─────────────────────────────────────────────────────────────────────────────
# Superseding an amendment that is not yet executed (PRD §3.7)
# ─────────────────────────────────────────────────────────────────────────────


def test_supersede_target_still_in_draft_rejected(api):
    """PRD §3.7: "And `supersedes_amendment_id` names the executed amendment that
    an equipment-swap amendment replaces; when supplied it must reference a site
    amendment whose `execution_status` is `EXECUTED`, with the same `tower_id` and
    the same `master_lease_agreement_id` as the new amendment, otherwise
    `ERR_SUPERSEDE_TARGET_INVALID`."

    Design: Corner/validations/supersede_target_not_executed_rejected
    """
    world = _carrier_with_two_approved_applications(
        api,
        site_name="Supersede Target Terrace",
        landlord_name="Terrace Land Trust",
        landlord_email="ap@terraceland.example",
        tenant_name="Supersede Target Telecom",
        carrier_code="SPT",
    )
    tower, mla = world["tower"], world["mla"]
    target = fixtures.paper_amendment(
        api,
        mla["id"],
        tower["id"],
        world["applications"][0]["id"],
        effective_date="2026-08-01",
        term_end_date="2031-05-31",
        base_monthly_rent_cents=200000,
        escalator_pct=3.0,
    )
    swap_applicant = world["applications"][1]

    resp = api.create_site_amendment(
        factories.site_amendment_payload(
            mla["id"],
            tower["id"],
            swap_applicant["id"],
            effective_date="2026-08-01",
            term_end_date="2031-05-31",
            base_monthly_rent_cents=200000,
            escalator_pct=3.0,
            supersedes_amendment_id=target["id"],
        ),
        ADMIN_HEADERS,
    )
    validate_error(resp, ERR_SUPERSEDE_TARGET_INVALID, 422)

    # No swap amendment was papered and the target is untouched.
    rows, meta = validate_paginated(
        api.list_site_amendments({"tower_id": tower["id"], "limit": 100}, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [target["id"]]
    assert_amendment_axes(
        fixtures.read_amendment(api, target["id"]), execution_status="DRAFT"
    )
    assert fixtures.read_application(api, swap_applicant["id"])["status"] == "APPROVED"


# ─────────────────────────────────────────────────────────────────────────────
# Cost allocation with an empty beneficiary set (PRD §3.6)
# ─────────────────────────────────────────────────────────────────────────────


def test_cost_share_allocation_with_no_beneficiaries_rejected(api):
    """PRD §3.6: "If the resolved set is empty, or if the total basis load summed
    over the set is not greater than zero, the allocation is rejected with
    `ERR_COST_SHARE_BENEFICIARY_INVALID`."

    Design: Corner/validations/cost_share_allocation_without_beneficiaries_rejected
    """
    site = fixtures.site_with_ground_lease(
        api,
        tower_overrides={
            "site_name": "Cost Basis Void",
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 1000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
            "baseline_reserved_load_units": 900,
        },
        landlord_overrides={
            "legal_name": "Basis Void Land",
            "remit_contact_email": "ap@basisvoid.example",
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
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Cost Basis Cellular", "carrier_code": "CBI"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
    )
    tower, tenant, mla = site["tower"], carrier["tenant"], carrier["mla"]

    application = fixtures.new_application(
        api,
        tower["id"],
        mla["id"],
        tenant["id"],
        requested_elevation_bottom_ft=100,
        requested_elevation_top_ft=140,
        requested_ground_space_sqft=300,
    )
    fixtures.add_equipment_line(
        api,
        application["id"],
        tenant["id"],
        equipment_type="ANTENNA",
        model_code="CB-60",
        quantity=1,
        unit_weight_lbs=60,
        wind_area_sqft=0,
        mount_elevation_ft=80,
    )
    fixtures.submit_application(api, application["id"], tenant["id"])
    analysis = fixtures.run_analysis(api, application["id"], tower["id"], "PRELIMINARY")
    project = fixtures.quoted_analysis_with_project(
        api,
        tower_id=tower["id"],
        analysis_id=analysis["id"],
        cost_cents=1000000,
        project_overrides={
            "construction_window_start_date": "2026-09-01",
            "construction_window_end_date": "2026-10-31",
            "allocation_basis": "PRO_RATA_LOAD",
        },
    )["project"]

    # Withdrawing the applicant leaves the tower with no executed amendment and
    # no eligible application, so no beneficiary can be resolved.
    validate_success(
        api.withdraw_colocation_application(
            application["id"], {}, make_tenant_headers(tenant["id"])
        ),
        200,
    )

    resp = api.allocate_cost_shares(project["id"], {}, OTHER_ENGINEER_HEADERS)
    validate_error(resp, ERR_COST_SHARE_BENEFICIARY_INVALID, 422)

    unchanged = fixtures.read_project(api, project["id"])
    assert unchanged["status"] == "PROPOSED"
    assert_cents(unchanged["allocated_cents"], 0, "allocated_cents")
    assert unchanged["version"] == project["version"]

    rows, meta = validate_paginated(
        api.list_cost_shares(
            {"modification_project_id": project["id"], "limit": 100}, ADMIN_HEADERS
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


# ─────────────────────────────────────────────────────────────────────────────
# Dating an audit and its findings (PRD §3.9)
# ─────────────────────────────────────────────────────────────────────────────


def test_audit_dated_after_the_logical_clock_rejected(api):
    """PRD §3.9: "Scheduling an audit names the `tower_id`, an `audit_date` that is
    the as-of date of the inspection and must not be after the current logical
    clock instant (otherwise `ERR_AUDIT_DATE_IN_FUTURE`), and a `basis` of either
    `INSTALL_DATE_BASIS` or `DISCOVERY_LIMITED`."

    Design: Corner/validations/audit_dated_after_the_clock_rejected
    """
    tower = fixtures.new_tower(
        api,
        site_name="Audit Date Draw",
        structure_type="MONOPOLE",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )

    resp = api.create_equipment_audit(
        factories.equipment_audit_payload(
            tower["id"], audit_date="2026-08-02", basis="INSTALL_DATE_BASIS"
        ),
        AUDITOR_HEADERS,
    )
    validate_error(resp, ERR_AUDIT_DATE_IN_FUTURE, 422)

    rows, meta = validate_paginated(
        api.list_tower_equipment_audits(tower["id"], {"limit": 100}, AUDITOR_HEADERS)
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_audit_dated_on_the_clock_date_scheduled(api):
    """PRD §3.9: "Scheduling an audit names the `tower_id`, an `audit_date` that is
    the as-of date of the inspection and must not be after the current logical
    clock instant (otherwise `ERR_AUDIT_DATE_IN_FUTURE`), and a `basis` of either
    `INSTALL_DATE_BASIS` or `DISCOVERY_LIMITED`."

    Design: Corner/validations/audit_dated_after_the_clock_rejected
    """
    tower = fixtures.new_tower(
        api,
        site_name="Audit Date Draw",
        structure_type="MONOPOLE",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )

    # The clock is at its cold-start 2026-08-01T00:00:00Z, so an audit dated
    # exactly 2026-08-01 is not in the future.
    resp = api.create_equipment_audit(
        factories.equipment_audit_payload(
            tower["id"], audit_date="2026-08-01", basis="INSTALL_DATE_BASIS"
        ),
        AUDITOR_HEADERS,
    )
    audit = validate_success(resp, 201)
    assert audit["status"] == "SCHEDULED"
    assert audit["audit_date"] == "2026-08-01"
    assert audit["finding_count"] == 0
    assert_cents(
        audit["retroactive_billing_total_cents"], 0, "retroactive_billing_total_cents"
    )

    _rows, meta = validate_paginated(
        api.list_tower_equipment_audits(tower["id"], {"limit": 100}, AUDITOR_HEADERS)
    )
    assert meta["total_count"] == 1


def test_finding_installed_after_the_audit_date_rejected(api):
    """PRD §3.9: "The `installed_on_date` must not be after the parent audit's
    `audit_date`, otherwise `ERR_FINDING_DATE_AFTER_AUDIT`."

    Design: Corner/validations/finding_installed_after_audit_date_rejected
    """
    tower = fixtures.new_tower(
        api,
        site_name="Finding Date Flat",
        structure_type="MONOPOLE",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )
    tenant = fixtures.new_tenant(api, legal_name="Finding Date Radio", carrier_code="FDA")
    audit = fixtures.schedule_audit(
        api, tower["id"], audit_date="2026-07-01", basis="INSTALL_DATE_BASIS"
    )
    fixtures.start_audit(api, audit["id"])

    resp = api.create_audit_finding(
        audit["id"],
        factories.audit_finding_payload(
            tenant["id"],
            description="Cabinet installed the day after the walk",
            observed_load_units=40,
            installed_on_date="2026-07-02",
            mount_elevation_ft=120,
        ),
        AUDITOR_HEADERS,
    )
    validate_error(resp, ERR_FINDING_DATE_AFTER_AUDIT, 422)

    unchanged = fixtures.read_audit(api, tower["id"], audit["id"])
    assert unchanged["finding_count"] == 0
    assert unchanged["status"] == "IN_PROGRESS"
    _rows, meta = validate_paginated(
        api.list_audit_findings({"equipment_audit_id": audit["id"], "limit": 100}, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0
    assert_tenant_ledger(
        fixtures.read_tenant(api, tenant["id"]),
        outstanding_balance_cents=0,
        credit_status="CURRENT",
    )


def test_finding_installed_on_the_audit_date_recorded_unbilled(api):
    """PRD §3.9: "A new finding starts with `status` `OPEN`, `months_billable` at 0
    and `retroactive_billing_cents` at 0, and it increments the audit's
    `finding_count` by one."

    Design: Corner/validations/finding_installed_after_audit_date_rejected
    """
    tower = fixtures.new_tower(
        api,
        site_name="Finding Date Flat",
        structure_type="MONOPOLE",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )
    tenant = fixtures.new_tenant(api, legal_name="Finding Date Radio", carrier_code="FDA")
    audit = fixtures.schedule_audit(
        api, tower["id"], audit_date="2026-07-01", basis="INSTALL_DATE_BASIS"
    )
    fixtures.start_audit(api, audit["id"])

    # An installation dated exactly on the audit date is not after it.
    resp = api.create_audit_finding(
        audit["id"],
        factories.audit_finding_payload(
            tenant["id"],
            description="Cabinet installed on the day of the walk",
            observed_load_units=40,
            installed_on_date="2026-07-01",
            mount_elevation_ft=120,
        ),
        AUDITOR_HEADERS,
    )
    finding = validate_success(resp, 201)
    assert finding["status"] == "OPEN"
    assert finding["months_billable"] == 0
    assert_cents(finding["retroactive_billing_cents"], 0, "retroactive_billing_cents")

    assert fixtures.read_audit(api, tower["id"], audit["id"])["finding_count"] == 1
    assert_tenant_ledger(
        fixtures.read_tenant(api, tenant["id"]),
        outstanding_balance_cents=0,
        credit_status="CURRENT",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tenant cash and the logical clock (PRD §3.3, §2.4)
# ─────────────────────────────────────────────────────────────────────────────


def test_tenant_payment_of_zero_cents_rejected(api):
    """PRD §3.3: "Cash coming in is applied as a tenant payment carrying
    `amount_cents`, which must be strictly greater than zero, otherwise
    `ERR_INVALID_PAYMENT_AMOUNT`."

    Design: Corner/validations/tenant_payment_of_zero_rejected
    """
    tenant = fixtures.new_tenant(api, legal_name="Payment Zero Radio", carrier_code="PZR")

    resp = api.create_tenant_payment(
        tenant["id"], factories.tenant_payment_payload(0), ADMIN_HEADERS
    )
    validate_error(resp, ERR_INVALID_PAYMENT_AMOUNT, 422)

    unchanged = fixtures.read_tenant(api, tenant["id"])
    assert_tenant_ledger(unchanged, outstanding_balance_cents=0, credit_status="CURRENT")
    assert unchanged["version"] == tenant["version"]


def test_tenant_payment_of_one_cent_drives_the_balance_negative(api):
    """PRD §3.3: "The payment decreases `outstanding_balance_cents` by that amount
    and recomputes `credit_status`."

    Design: Corner/validations/tenant_payment_of_zero_rejected
    """
    tenant = fixtures.new_tenant(api, legal_name="Payment Zero Radio", carrier_code="PZR")

    resp = api.create_tenant_payment(
        tenant["id"], factories.tenant_payment_payload(1), ADMIN_HEADERS
    )
    paid = validate_success(resp, 200)
    assert_tenant_ledger(paid, outstanding_balance_cents=-1, credit_status="CURRENT")
    assert_tenant_ledger(
        fixtures.read_tenant(api, tenant["id"]),
        outstanding_balance_cents=-1,
        credit_status="CURRENT",
    )


def test_clock_set_to_an_earlier_instant_rejected(api):
    """PRD §2.4: "A `PortfolioAdmin` may advance the clock by supplying a
    `to_iso8601` instant; the requested instant must be strictly after the current
    logical clock instant, otherwise the request is rejected with
    `ERR_CLOCK_NOT_MONOTONIC` (422)."

    Design: Corner/validations/clock_set_to_earlier_or_equal_instant_rejected
    """
    fixtures.advance_clock(api, "2026-09-01T00:00:00Z")

    resp = api.set_clock(factories.clock_payload("2026-08-15T00:00:00Z"), ADMIN_HEADERS)
    validate_error(resp, ERR_CLOCK_NOT_MONOTONIC, 422)

    # The clock did not move back: an instant after the refused target but still
    # before the live clock is refused too.
    validate_error(
        api.set_clock(factories.clock_payload("2026-08-20T00:00:00Z"), ADMIN_HEADERS),
        ERR_CLOCK_NOT_MONOTONIC,
        422,
    )

    summary = validate_success(
        api.set_clock(factories.clock_payload("2026-09-01T00:00:01Z"), ADMIN_HEADERS), 200
    )
    assert_clock_summary(
        summary,
        expired_ground_lease_count=0,
        expired_master_lease_count=0,
        frozen_tower_count=0,
    )


def test_clock_set_to_the_current_instant_rejected(api):
    """PRD §2.4: "A `PortfolioAdmin` may advance the clock by supplying a
    `to_iso8601` instant; the requested instant must be strictly after the current
    logical clock instant, otherwise the request is rejected with
    `ERR_CLOCK_NOT_MONOTONIC` (422)."

    Design: Corner/validations/clock_set_to_earlier_or_equal_instant_rejected
    """
    fixtures.advance_clock(api, "2026-09-01T00:00:00Z")

    resp = api.set_clock(factories.clock_payload("2026-09-01T00:00:00Z"), ADMIN_HEADERS)
    validate_error(resp, ERR_CLOCK_NOT_MONOTONIC, 422)

    # One second later is strictly after the live clock and is accepted.
    summary = validate_success(
        api.set_clock(factories.clock_payload("2026-09-01T00:00:01Z"), ADMIN_HEADERS), 200
    )
    assert_clock_summary(
        summary,
        expired_ground_lease_count=0,
        expired_master_lease_count=0,
        frozen_tower_count=0,
    )
