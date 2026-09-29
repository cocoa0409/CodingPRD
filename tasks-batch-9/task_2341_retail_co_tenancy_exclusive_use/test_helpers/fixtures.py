"""Composite setup helpers.

Every test starts against an empty database, so each precondition has to be
built from scratch through the API itself.  These helpers do exactly that: thin
wrappers that unwrap the success envelope for a single call, and higher-level
builders that stand up whole scenarios (a leased-up center, a breached
condition, an eligible lease, an active reduction, an escalated notice, a signed
certificate, a frozen center).

Identity threading is explicit throughout: any operation the PRD reserves for
the tenant's own representative takes the ``Tenant`` id it must act as.
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import DEFAULT_CLOCK_UTC
from .test_users import (
    ASSET_MANAGER_USER_ID,
    COMPLIANCE_ADJUDICATOR_USER_ID,
    COMPLIANCE_ENFORCER_USER_ID,
    COMPLIANCE_OFFICER_USER_ID,
    COMPLIANCE_REVIEWER_USER_ID,
    LEASE_ADMIN_USER_ID,
    LENDER_REP_USER_ID,
    make_asset_manager_headers,
    make_compliance_officer_headers,
    make_lease_administrator_headers,
    make_lender_rep_headers,
    make_tenant_rep_headers,
)

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def set_clock(
    api: ApiClient, to_iso8601: str = DEFAULT_CLOCK_UTC, user_id: str = COMPLIANCE_OFFICER_USER_ID
) -> Dict[str, Any]:
    """Pin the logical current UTC instant every temporal rule reads."""
    return get_success_data(
        api.set_clock(
            f.clock_payload(to_iso8601), make_compliance_officer_headers(user_id)
        ),
        200,
    )


# --------------------------------------------------------------------------
# Centers and tenants
# --------------------------------------------------------------------------
def create_center(
    api: ApiClient,
    name: str = "Northgate Crossing",
    total_gla_sqft: int = 300000,
    occupancy_grace_days: Optional[int] = None,
    user_id: str = ASSET_MANAGER_USER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_center(
            f.center_payload(
                name=name,
                total_gla_sqft=total_gla_sqft,
                occupancy_grace_days=occupancy_grace_days,
                **overrides,
            ),
            make_asset_manager_headers(user_id),
        ),
        201,
    )


def create_tenant(
    api: ApiClient,
    legal_name: str = "Harbor Goods LLC",
    notice_email: Optional[str] = None,
    primary_use_code: str = "APPAREL",
    is_national_chain: Optional[bool] = None,
    user_id: str = LEASE_ADMIN_USER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    if notice_email is None:
        slug = "".join(c for c in legal_name.lower() if c.isalnum())
        notice_email = f"notices@{slug or 'tenant'}.example"
    return get_success_data(
        api.create_tenant(
            f.tenant_payload(
                legal_name=legal_name,
                notice_email=notice_email,
                primary_use_code=primary_use_code,
                is_national_chain=is_national_chain,
                **overrides,
            ),
            make_lease_administrator_headers(user_id),
        ),
        201,
    )


def set_tenant_status(
    api: ApiClient, tenant_id: str, status: str, user_id: str = LEASE_ADMIN_USER_ID
) -> Dict[str, Any]:
    """Update a tenant's credit status, which re-runs the live strict engine."""
    return get_success_data(
        api.patch_tenant(
            tenant_id,
            f.tenant_patch_payload(status),
            make_lease_administrator_headers(user_id),
        ),
        200,
    )


def run_sweep(
    api: ApiClient, center_id: str, user_id: str = COMPLIANCE_OFFICER_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.compliance_sweep(center_id, None, make_compliance_officer_headers(user_id)),
        200,
    )


# --------------------------------------------------------------------------
# Leases
# --------------------------------------------------------------------------
def draft_lease(
    api: ApiClient,
    center_id: str,
    tenant_id: str,
    suite_code: str = "A-100",
    gla_sqft: int = 3000,
    parcel_kind: str = "INLINE",
    primary_use_code: str = "APPAREL",
    base_rent_monthly_cents: int = 1000000,
    commencement_date: str = "2026-01-01",
    expiration_date: str = "2031-12-31",
    user_id: str = LEASE_ADMIN_USER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_lease(
            center_id,
            f.lease_payload(
                tenant_id=tenant_id,
                suite_code=suite_code,
                gla_sqft=gla_sqft,
                parcel_kind=parcel_kind,
                primary_use_code=primary_use_code,
                base_rent_monthly_cents=base_rent_monthly_cents,
                commencement_date=commencement_date,
                expiration_date=expiration_date,
                **overrides,
            ),
            make_lease_administrator_headers(user_id),
        ),
        201,
    )


def execute_lease(
    api: ApiClient, lease_id: str, user_id: str = LEASE_ADMIN_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.execute_lease(lease_id, None, make_lease_administrator_headers(user_id)), 200
    )


def open_lease(
    api: ApiClient,
    lease_id: str,
    user_id: str = LEASE_ADMIN_USER_ID,
    as_tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    headers = (
        make_tenant_rep_headers(as_tenant_id)
        if as_tenant_id
        else make_lease_administrator_headers(user_id)
    )
    return get_success_data(api.open_lease(lease_id, None, headers), 200)


def go_dark(
    api: ApiClient,
    lease_id: str,
    user_id: str = LEASE_ADMIN_USER_ID,
    as_tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    headers = (
        make_tenant_rep_headers(as_tenant_id)
        if as_tenant_id
        else make_lease_administrator_headers(user_id)
    )
    return get_success_data(api.go_dark(lease_id, None, headers), 200)


def reopen_lease(
    api: ApiClient,
    lease_id: str,
    user_id: str = LEASE_ADMIN_USER_ID,
    as_tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    headers = (
        make_tenant_rep_headers(as_tenant_id)
        if as_tenant_id
        else make_lease_administrator_headers(user_id)
    )
    return get_success_data(api.reopen_lease(lease_id, None, headers), 200)


def terminate_lease(
    api: ApiClient,
    lease_id: str,
    termination_reason_code: str = "LANDLORD_RECAPTURE",
    user_id: str = ASSET_MANAGER_USER_ID,
) -> Dict[str, Any]:
    return get_success_data(
        api.terminate_lease(
            lease_id,
            f.terminate_payload(termination_reason_code),
            make_asset_manager_headers(user_id),
        ),
        200,
    )


def screen_use(
    api: ApiClient, lease_id: str, user_id: str = LEASE_ADMIN_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.screen_use(lease_id, None, make_lease_administrator_headers(user_id)), 200
    )


# --------------------------------------------------------------------------
# Conditions, anchor requirements, clauses, restrictions
# --------------------------------------------------------------------------
def add_condition(
    api: ApiClient,
    lease_id: str,
    condition_kind: str = "ONGOING",
    measurement_basis: str = "GLA_PCT",
    required_occupancy_pct: Optional[float] = 70.0,
    required_open_store_count: Optional[int] = None,
    required_anchor_count: Optional[int] = None,
    grace_period_days: Optional[int] = None,
    cure_period_days: Optional[int] = None,
    remedy_type: str = "RENT_REDUCTION_ONLY",
    max_reduction_pct: Optional[float] = None,
    user_id: str = LEASE_ADMIN_USER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_condition(
            lease_id,
            f.condition_payload(
                condition_kind=condition_kind,
                measurement_basis=measurement_basis,
                required_occupancy_pct=required_occupancy_pct,
                required_open_store_count=required_open_store_count,
                required_anchor_count=required_anchor_count,
                grace_period_days=grace_period_days,
                cure_period_days=cure_period_days,
                remedy_type=remedy_type,
                max_reduction_pct=max_reduction_pct,
                **overrides,
            ),
            make_lease_administrator_headers(user_id),
        ),
        201,
    )


def waive_condition(
    api: ApiClient,
    condition_id: str,
    waiver_reason_code: str = "LANDLORD_ACCOMMODATION",
    user_id: str = ASSET_MANAGER_USER_ID,
) -> Dict[str, Any]:
    return get_success_data(
        api.waive_condition(
            condition_id,
            f.waive_payload(waiver_reason_code),
            make_asset_manager_headers(user_id),
        ),
        200,
    )


def add_anchor_requirement(
    api: ApiClient,
    condition_id: str,
    anchor_lease_id: str,
    substitution_allowed: Optional[bool] = None,
    min_substitute_gla_sqft: Optional[int] = None,
    user_id: str = LEASE_ADMIN_USER_ID,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_anchor_requirement(
            condition_id,
            f.anchor_requirement_payload(
                anchor_lease_id=anchor_lease_id,
                substitution_allowed=substitution_allowed,
                min_substitute_gla_sqft=min_substitute_gla_sqft,
            ),
            make_lease_administrator_headers(user_id),
        ),
        201,
    )


def add_clause(
    api: ApiClient,
    lease_id: str,
    protected_use_codes: Optional[List[str]] = None,
    exclusivity_scope: str = "CENTER_WIDE",
    effective_from_date: str = "2026-01-01",
    effective_through_date: str = "2031-12-31",
    gla_carve_out_sqft: Optional[int] = None,
    incidental_sales_pct_cap: Optional[float] = None,
    user_id: str = LEASE_ADMIN_USER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_clause(
            lease_id,
            f.clause_payload(
                protected_use_codes=protected_use_codes,
                exclusivity_scope=exclusivity_scope,
                effective_from_date=effective_from_date,
                effective_through_date=effective_through_date,
                gla_carve_out_sqft=gla_carve_out_sqft,
                incidental_sales_pct_cap=incidental_sales_pct_cap,
                **overrides,
            ),
            make_lease_administrator_headers(user_id),
        ),
        201,
    )


def add_radius_restriction(
    api: ApiClient,
    lease_id: str,
    radius_miles: float = 3.0,
    measured_from: str = "CENTER_BOUNDARY",
    recapture_basis: str = "GROSS_SALES",
    recapture_pct: float = 6.0,
    window_from_date: str = "2026-01-01",
    window_through_date: str = "2026-12-31",
    protected_baseline_cents: Optional[int] = None,
    user_id: str = LEASE_ADMIN_USER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_radius_restriction(
            lease_id,
            f.radius_restriction_payload(
                radius_miles=radius_miles,
                measured_from=measured_from,
                recapture_basis=recapture_basis,
                recapture_pct=recapture_pct,
                window_from_date=window_from_date,
                window_through_date=window_through_date,
                protected_baseline_cents=protected_baseline_cents,
                **overrides,
            ),
            make_lease_administrator_headers(user_id),
        ),
        201,
    )


# --------------------------------------------------------------------------
# Notices, disputes
# --------------------------------------------------------------------------
def issue_notice(
    api: ApiClient,
    violating_lease_id: str,
    notice_kind: str = "EXCLUSIVE_USE",
    clause_id: Optional[str] = None,
    narrative: Optional[str] = None,
    cure_period_days: Optional[int] = None,
    user_id: str = COMPLIANCE_ENFORCER_USER_ID,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_notice(
            f.notice_payload(
                violating_lease_id=violating_lease_id,
                notice_kind=notice_kind,
                clause_id=clause_id,
                narrative=narrative,
                cure_period_days=cure_period_days,
            ),
            make_compliance_officer_headers(user_id),
        ),
        201,
    )


def report_radius_violation(
    api: ApiClient,
    restriction_id: str,
    reported_offending_sales_cents: int,
    narrative: str = "In-radius store observed inside the protected window.",
    cure_period_days: Optional[int] = None,
    user_id: str = COMPLIANCE_ENFORCER_USER_ID,
) -> Dict[str, Any]:
    return get_success_data(
        api.report_radius_violation(
            restriction_id,
            f.radius_violation_report_payload(
                reported_offending_sales_cents=reported_offending_sales_cents,
                narrative=narrative,
                cure_period_days=cure_period_days,
            ),
            make_compliance_officer_headers(user_id),
        ),
        201,
    )


def cure_notice(
    api: ApiClient,
    notice_id: str,
    cure_evidence_code: str = "USE_DISCONTINUED",
    user_id: str = LEASE_ADMIN_USER_ID,
    as_role: str = "LeaseAdministrator",
) -> Dict[str, Any]:
    headers = (
        make_compliance_officer_headers(user_id)
        if as_role == "ComplianceOfficer"
        else make_lease_administrator_headers(user_id)
    )
    return get_success_data(
        api.cure_notice(notice_id, f.cure_payload(cure_evidence_code), headers), 200
    )


def escalate_notice(
    api: ApiClient, notice_id: str, user_id: str = COMPLIANCE_ENFORCER_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.escalate_notice(notice_id, None, make_compliance_officer_headers(user_id)),
        200,
    )


def withdraw_notice(
    api: ApiClient,
    notice_id: str,
    withdrawal_reason_code: str = "LANDLORD_RECONSIDERED",
    user_id: str = COMPLIANCE_ENFORCER_USER_ID,
) -> Dict[str, Any]:
    return get_success_data(
        api.withdraw_notice(
            notice_id,
            f.withdraw_payload(withdrawal_reason_code),
            make_compliance_officer_headers(user_id),
        ),
        200,
    )


def file_dispute(
    api: ApiClient,
    notice_id: str,
    tenant_id: str,
    grounds_code: str = "NO_PROHIBITED_USE",
    narrative: str = "The suite has never conducted the protected use.",
    cure_extension_days: Optional[int] = None,
) -> Dict[str, Any]:
    """File a dispute as the violating tenant's own representative."""
    return get_success_data(
        api.create_dispute(
            notice_id,
            f.dispute_payload(
                grounds_code=grounds_code,
                narrative=narrative,
                cure_extension_days=cure_extension_days,
            ),
            make_tenant_rep_headers(tenant_id),
        ),
        201,
    )


def adjudicate_dispute(
    api: ApiClient,
    dispute_id: str,
    outcome: str,
    user_id: str = COMPLIANCE_ADJUDICATOR_USER_ID,
) -> Dict[str, Any]:
    """Adjudicate as an officer other than the one who issued the notice."""
    return get_success_data(
        api.adjudicate_dispute(
            dispute_id,
            f.adjudicate_payload(outcome),
            make_compliance_officer_headers(user_id),
        ),
        200,
    )


# --------------------------------------------------------------------------
# Measurements
# --------------------------------------------------------------------------
def prepare_measurement(
    api: ApiClient,
    center_id: str,
    variant: str = "SNAPSHOT_STRICT",
    window_from_date: str = "2026-07-01",
    window_through_date: str = "2026-08-02",
    expected_center_version: Optional[int] = None,
    user_id: str = COMPLIANCE_OFFICER_USER_ID,
) -> Dict[str, Any]:
    """Prepare a draft measurement, reading the center's current version if needed."""
    if expected_center_version is None:
        expected_center_version = fetch_center(api, center_id)["version"]
    return get_success_data(
        api.create_measurement(
            center_id,
            f.measurement_payload(
                variant=variant,
                window_from_date=window_from_date,
                window_through_date=window_through_date,
                expected_center_version=expected_center_version,
            ),
            make_compliance_officer_headers(user_id),
        ),
        201,
    )


def certify_measurement(
    api: ApiClient, measurement_id: str, user_id: str = COMPLIANCE_REVIEWER_USER_ID
) -> Dict[str, Any]:
    """Certify as an officer other than the preparer."""
    return get_success_data(
        api.certify_measurement(
            measurement_id, None, make_compliance_officer_headers(user_id)
        ),
        200,
    )


def supersede_measurement(
    api: ApiClient,
    measurement_id: str,
    supersede_reason_code: str = "REMEASURED",
    user_id: str = COMPLIANCE_REVIEWER_USER_ID,
) -> Dict[str, Any]:
    return get_success_data(
        api.supersede_measurement(
            measurement_id,
            f.supersede_payload(supersede_reason_code),
            make_compliance_officer_headers(user_id),
        ),
        200,
    )


def prepare_and_certify_measurement(
    api: ApiClient,
    center_id: str,
    variant: str = "TRAILING_GRACE",
    window_from_date: str = "2026-07-01",
    window_through_date: str = "2026-08-02",
    preparer_user_id: str = COMPLIANCE_OFFICER_USER_ID,
    certifier_user_id: str = COMPLIANCE_REVIEWER_USER_ID,
) -> Dict[str, Any]:
    """Prepare then certify one measurement with two distinct officers."""
    measurement = prepare_measurement(
        api,
        center_id,
        variant=variant,
        window_from_date=window_from_date,
        window_through_date=window_through_date,
        user_id=preparer_user_id,
    )
    return certify_measurement(api, measurement["id"], certifier_user_id)


# --------------------------------------------------------------------------
# Remedy elections
# --------------------------------------------------------------------------
def elect_remedy(
    api: ApiClient,
    lease_id: str,
    tenant_id: str,
    election_kind: str = "RENT_REDUCTION",
    window_from_date: str = "2026-08-01",
    window_through_date: str = "2026-11-01",
    condition_id: Optional[str] = None,
    source_notice_id: Optional[str] = None,
    expected_lease_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Elect a remedy as the lease's own tenant representative."""
    if expected_lease_version is None:
        expected_lease_version = fetch_lease(api, lease_id)["version"]
    return get_success_data(
        api.create_election(
            lease_id,
            f.election_payload(
                election_kind=election_kind,
                window_from_date=window_from_date,
                window_through_date=window_through_date,
                condition_id=condition_id,
                source_notice_id=source_notice_id,
                expected_lease_version=expected_lease_version,
            ),
            make_tenant_rep_headers(tenant_id),
        ),
        201,
    )


def approve_election(
    api: ApiClient, election_id: str, user_id: str = ASSET_MANAGER_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.approve_election(election_id, None, make_asset_manager_headers(user_id)), 200
    )


def rescind_election(
    api: ApiClient,
    election_id: str,
    rescission_reason_code: str = "TENANT_WITHDREW",
    user_id: str = ASSET_MANAGER_USER_ID,
    as_tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    headers = (
        make_tenant_rep_headers(as_tenant_id)
        if as_tenant_id
        else make_asset_manager_headers(user_id)
    )
    return get_success_data(
        api.rescind_election(
            election_id, f.rescind_payload(rescission_reason_code), headers
        ),
        200,
    )


def consummate_election(
    api: ApiClient, election_id: str, user_id: str = ASSET_MANAGER_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.consummate_election(election_id, None, make_asset_manager_headers(user_id)),
        200,
    )


# --------------------------------------------------------------------------
# Estoppel certificates
# --------------------------------------------------------------------------
def request_certificate(
    api: ApiClient,
    lease_id: str,
    measurement_id: Optional[str] = None,
    expedite_requested: Optional[bool] = None,
    user_id: str = LENDER_REP_USER_ID,
    as_asset_manager: bool = False,
) -> Dict[str, Any]:
    headers = (
        make_asset_manager_headers(ASSET_MANAGER_USER_ID)
        if as_asset_manager
        else make_lender_rep_headers(user_id)
    )
    return get_success_data(
        api.create_certificate(
            lease_id,
            f.certificate_payload(
                measurement_id=measurement_id, expedite_requested=expedite_requested
            ),
            headers,
        ),
        201,
    )


def sign_certificate(api: ApiClient, certificate_id: str, tenant_id: str) -> Dict[str, Any]:
    """Sign as the estopped lease's own tenant representative."""
    return get_success_data(
        api.sign_certificate(certificate_id, None, make_tenant_rep_headers(tenant_id)),
        200,
    )


def accept_certificate(
    api: ApiClient, certificate_id: str, user_id: str = LENDER_REP_USER_ID
) -> Dict[str, Any]:
    return get_success_data(
        api.accept_certificate(certificate_id, None, make_lender_rep_headers(user_id)),
        200,
    )


def reject_certificate(
    api: ApiClient,
    certificate_id: str,
    rejection_reason_code: str = "LENDER_DECLINED",
    user_id: str = LENDER_REP_USER_ID,
) -> Dict[str, Any]:
    return get_success_data(
        api.reject_certificate(
            certificate_id,
            f.reject_certificate_payload(rejection_reason_code),
            make_lender_rep_headers(user_id),
        ),
        200,
    )


# --------------------------------------------------------------------------
# Redevelopment plans
# --------------------------------------------------------------------------
def plan_redevelopment(
    api: ApiClient,
    center_id: str,
    plan_kind: str = "PAD_SALE",
    removed_gla_sqft: Optional[int] = None,
    pad_parcel_lease_id: Optional[str] = None,
    user_id: str = ASSET_MANAGER_USER_ID,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_plan(
            center_id,
            f.plan_payload(
                plan_kind=plan_kind,
                removed_gla_sqft=removed_gla_sqft,
                pad_parcel_lease_id=pad_parcel_lease_id,
            ),
            make_asset_manager_headers(user_id),
        ),
        201,
    )


def record_plan(
    api: ApiClient,
    plan_id: str,
    consent_confirmed: Optional[bool] = None,
    user_id: str = ASSET_MANAGER_USER_ID,
) -> Dict[str, Any]:
    return get_success_data(
        api.record_plan(
            plan_id,
            f.record_plan_payload(consent_confirmed),
            make_asset_manager_headers(user_id),
        ),
        200,
    )


def abandon_plan(
    api: ApiClient,
    plan_id: str,
    abandon_reason_code: str = "PLAN_SHELVED",
    user_id: str = ASSET_MANAGER_USER_ID,
) -> Dict[str, Any]:
    return get_success_data(
        api.abandon_plan(
            plan_id,
            f.abandon_plan_payload(abandon_reason_code),
            make_asset_manager_headers(user_id),
        ),
        200,
    )


# --------------------------------------------------------------------------
# Readers
# --------------------------------------------------------------------------
def fetch_center(api: ApiClient, center_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_center(center_id, make_asset_manager_headers()), 200)


def fetch_tenant(api: ApiClient, tenant_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_tenant(tenant_id, make_lease_administrator_headers()), 200
    )


def fetch_lease(api: ApiClient, lease_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_lease(lease_id, make_lease_administrator_headers()), 200
    )


def fetch_condition(api: ApiClient, condition_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_condition(condition_id, make_lease_administrator_headers()), 200
    )


def fetch_anchor_requirement(api: ApiClient, requirement_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_anchor_requirement(requirement_id, make_lease_administrator_headers()),
        200,
    )


def fetch_clause(api: ApiClient, clause_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_clause(clause_id, make_lease_administrator_headers()), 200
    )


def fetch_restriction(api: ApiClient, restriction_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_radius_restriction(restriction_id, make_lease_administrator_headers()),
        200,
    )


def fetch_notice(api: ApiClient, notice_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_notice(notice_id, make_compliance_officer_headers()), 200
    )


def fetch_dispute(api: ApiClient, dispute_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_dispute(dispute_id, make_compliance_officer_headers()), 200
    )


def fetch_election(api: ApiClient, election_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_election(election_id, make_asset_manager_headers()), 200
    )


def fetch_measurement(api: ApiClient, measurement_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_measurement(measurement_id, make_compliance_officer_headers()), 200
    )


def fetch_certificate(api: ApiClient, certificate_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_certificate(certificate_id, make_lender_rep_headers()), 200
    )


def fetch_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_plan(plan_id, make_asset_manager_headers()), 200)


# --------------------------------------------------------------------------
# Scenario builders
# --------------------------------------------------------------------------
class Scenario(dict):
    """A leased-up center plus the tenants and leases keyed by suite code."""

    @property
    def center_id(self) -> str:
        return self["center"]["id"]

    def lease(self, suite_code: str) -> Dict[str, Any]:
        return self["leases"][suite_code]

    def lease_id(self, suite_code: str) -> str:
        return self["leases"][suite_code]["id"]

    def tenant(self, suite_code: str) -> Dict[str, Any]:
        return self["tenants"][suite_code]

    def tenant_id(self, suite_code: str) -> str:
        return self["tenants"][suite_code]["id"]


def create_lease_for_new_tenant(
    api: ApiClient,
    center_id: str,
    suite_code: str,
    gla_sqft: int = 3000,
    parcel_kind: str = "INLINE",
    primary_use_code: str = "APPAREL",
    base_rent_monthly_cents: int = 1000000,
    commencement_date: str = "2026-01-01",
    expiration_date: str = "2031-12-31",
    tenant_legal_name: Optional[str] = None,
    tenant_use_code: Optional[str] = None,
    is_national_chain: Optional[bool] = None,
    incidental_use_codes: Optional[List[str]] = None,
    projected_incidental_sales_pct: Optional[float] = None,
    state: str = "OPEN",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Register a fresh tenant, draft its lease, and advance it to ``state``.

    ``state`` is one of ``DRAFT``, ``EXECUTED`` or ``OPEN``.
    Returns ``(lease, tenant)`` with the lease read back after the last hop.
    """
    tenant = create_tenant(
        api,
        legal_name=tenant_legal_name or f"Tenant of {suite_code}",
        primary_use_code=tenant_use_code or primary_use_code,
        is_national_chain=is_national_chain,
    )
    lease = draft_lease(
        api,
        center_id,
        tenant["id"],
        suite_code=suite_code,
        gla_sqft=gla_sqft,
        parcel_kind=parcel_kind,
        primary_use_code=primary_use_code,
        base_rent_monthly_cents=base_rent_monthly_cents,
        commencement_date=commencement_date,
        expiration_date=expiration_date,
        incidental_use_codes=incidental_use_codes,
        projected_incidental_sales_pct=projected_incidental_sales_pct,
    )
    if state in ("EXECUTED", "OPEN"):
        lease = execute_lease(api, lease["id"])
    if state == "OPEN":
        lease = open_lease(api, lease["id"])
    return lease, tenant


def build_center_with_leases(
    api: ApiClient,
    lease_specs: Sequence[Dict[str, Any]],
    total_gla_sqft: int = 300000,
    occupancy_grace_days: Optional[int] = None,
    center_name: str = "Northgate Crossing",
    clock: Optional[str] = DEFAULT_CLOCK_UTC,
) -> Scenario:
    """Stand up a center and a lease per spec, each with its own tenant.

    Each spec is a dict of ``create_lease_for_new_tenant`` keyword arguments and
    must carry at least ``suite_code``.  The build runs in three phases — draft
    every lease, then execute every lease that needs executing, then open every
    lease that needs opening — because a lease execution is refused while the
    center is ``FROZEN`` (PRD §2.6) and a center whose stores have not opened
    yet is still below the 50.00 occupancy rung.  An ``EXECUTED`` lease
    contributes nothing to the numerator, so executing the whole roster before
    opening any of it is the only order that never asks the server to execute
    into a center it has already frozen.
    """
    if clock is not None:
        set_clock(api, clock)
    center = create_center(
        api,
        name=center_name,
        total_gla_sqft=total_gla_sqft,
        occupancy_grace_days=occupancy_grace_days,
    )
    leases: Dict[str, Any] = {}
    tenants: Dict[str, Any] = {}
    states: Dict[str, str] = {}
    for spec in lease_specs:
        spec = dict(spec)
        suite_code = spec.pop("suite_code")
        states[suite_code] = spec.pop("state", "OPEN")
        lease, tenant = create_lease_for_new_tenant(
            api, center["id"], suite_code, state="DRAFT", **spec
        )
        leases[suite_code] = lease
        tenants[suite_code] = tenant
    for suite_code, state in states.items():
        if state in ("EXECUTED", "OPEN"):
            leases[suite_code] = execute_lease(api, leases[suite_code]["id"])
    for suite_code, state in states.items():
        if state == "OPEN":
            leases[suite_code] = open_lease(api, leases[suite_code]["id"])
    return Scenario(
        center=fetch_center(api, center["id"]), leases=leases, tenants=tenants
    )


def build_anchored_center(
    api: ApiClient,
    total_gla_sqft: int = 300000,
    anchor_gla_sqft: int = 120000,
    second_anchor_gla_sqft: int = 100000,
    inline_gla_sqft: int = 3000,
    inline_rent_cents: int = 1000000,
    occupancy_grace_days: Optional[int] = None,
    clock: Optional[str] = DEFAULT_CLOCK_UTC,
) -> Scenario:
    """A center with two open anchor boxes and one open inline suite.

    Suites are ``BOX-1`` and ``BOX-2`` (``ANCHOR_BOX``) and ``A-100``
    (``INLINE``), which is the benefited suite in most co-tenancy scenarios.
    """
    return build_center_with_leases(
        api,
        [
            {
                "suite_code": "BOX-1",
                "gla_sqft": anchor_gla_sqft,
                "parcel_kind": "ANCHOR_BOX",
                "primary_use_code": "DEPARTMENT_STORE",
                "base_rent_monthly_cents": 4000000,
            },
            {
                "suite_code": "BOX-2",
                "gla_sqft": second_anchor_gla_sqft,
                "parcel_kind": "ANCHOR_BOX",
                "primary_use_code": "GROCERY",
                "base_rent_monthly_cents": 3000000,
            },
            {
                "suite_code": "A-100",
                "gla_sqft": inline_gla_sqft,
                "parcel_kind": "INLINE",
                "primary_use_code": "APPAREL",
                "base_rent_monthly_cents": inline_rent_cents,
            },
        ],
        total_gla_sqft=total_gla_sqft,
        occupancy_grace_days=occupancy_grace_days,
        clock=clock,
    )


def build_breached_condition(
    api: ApiClient,
    required_occupancy_pct: float = 70.0,
    grace_period_days: Optional[int] = 0,
    cure_period_days: Optional[int] = None,
    remedy_type: str = "RENT_REDUCTION_ONLY",
    max_reduction_pct: Optional[float] = None,
    dark_suite: str = "BOX-1",
    total_gla_sqft: int = 300000,
    anchor_gla_sqft: int = 120000,
    second_anchor_gla_sqft: int = 100000,
    inline_gla_sqft: int = 3000,
    inline_rent_cents: int = 1000000,
    occupancy_grace_days: Optional[int] = None,
    clock: Optional[str] = DEFAULT_CLOCK_UTC,
) -> Scenario:
    """An anchored center whose inline suite holds a condition, then breached.

    The condition is abstracted while everything is open (so it is created
    ``SATISFIED``), and one suite then goes dark, which drives the condition
    ``SATISFIED -> BREACHED`` through the live strict engine.  With a zero grace
    period the benefited lease also reaches ``ELIGIBLE`` in the same request.
    """
    scenario = build_anchored_center(
        api,
        total_gla_sqft=total_gla_sqft,
        anchor_gla_sqft=anchor_gla_sqft,
        second_anchor_gla_sqft=second_anchor_gla_sqft,
        inline_gla_sqft=inline_gla_sqft,
        inline_rent_cents=inline_rent_cents,
        occupancy_grace_days=occupancy_grace_days,
        clock=clock,
    )
    condition = add_condition(
        api,
        scenario.lease_id("A-100"),
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=required_occupancy_pct,
        grace_period_days=grace_period_days,
        cure_period_days=cure_period_days,
        remedy_type=remedy_type,
        max_reduction_pct=max_reduction_pct,
    )
    go_dark(api, scenario.lease_id(dark_suite))
    scenario["condition"] = fetch_condition(api, condition["id"])
    scenario["center"] = fetch_center(api, scenario.center_id)
    scenario["leases"]["A-100"] = fetch_lease(api, scenario.lease_id("A-100"))
    scenario["leases"][dark_suite] = fetch_lease(api, scenario.lease_id(dark_suite))
    return scenario


def build_active_reduction(
    api: ApiClient,
    window_from_date: str = "2026-08-01",
    window_through_date: str = "2026-11-01",
    **breach_kwargs: Any,
) -> Scenario:
    """A breached condition whose benefited tenant holds an approved reduction."""
    scenario = build_breached_condition(api, **breach_kwargs)
    election = elect_remedy(
        api,
        scenario.lease_id("A-100"),
        scenario.tenant_id("A-100"),
        election_kind="RENT_REDUCTION",
        window_from_date=window_from_date,
        window_through_date=window_through_date,
        condition_id=scenario["condition"]["id"],
    )
    scenario["election"] = approve_election(api, election["id"])
    scenario["leases"]["A-100"] = fetch_lease(api, scenario.lease_id("A-100"))
    scenario["center"] = fetch_center(api, scenario.center_id)
    return scenario


def build_noticed_lease(
    api: ApiClient,
    protected_use_codes: Optional[List[str]] = None,
    violating_use_code: str = "COFFEE",
    cure_period_days: Optional[int] = None,
    exclusivity_scope: str = "CENTER_WIDE",
    clock: Optional[str] = DEFAULT_CLOCK_UTC,
) -> Scenario:
    """A center where suite ``A-200`` is under an exclusive-use notice.

    Suite ``A-100`` holds the protected clause; suite ``A-200`` operates the
    protected use and is noticed for it.  The clause is recorded *after* the
    offending lease executes, because screening runs only at execution time.
    """
    scenario = build_center_with_leases(
        api,
        [
            {
                "suite_code": "A-100",
                "gla_sqft": 3000,
                "primary_use_code": "APPAREL",
                "base_rent_monthly_cents": 1000000,
            },
            {
                "suite_code": "A-200",
                "gla_sqft": 2000,
                "primary_use_code": violating_use_code,
                "base_rent_monthly_cents": 800000,
            },
        ],
        total_gla_sqft=10000,
        clock=clock,
    )
    clause = add_clause(
        api,
        scenario.lease_id("A-100"),
        protected_use_codes=protected_use_codes or [violating_use_code],
        exclusivity_scope=exclusivity_scope,
    )
    notice = issue_notice(
        api,
        scenario.lease_id("A-200"),
        notice_kind="EXCLUSIVE_USE",
        clause_id=clause["id"],
        cure_period_days=cure_period_days,
    )
    scenario["clause"] = fetch_clause(api, clause["id"])
    scenario["notice"] = fetch_notice(api, notice["id"])
    scenario["center"] = fetch_center(api, scenario.center_id)
    return scenario


def build_escalated_notice(
    api: ApiClient,
    cure_period_days: int = 30,
    issued_at: str = DEFAULT_CLOCK_UTC,
    escalate_at: str = "2026-09-15T00:00:00Z",
    **notice_kwargs: Any,
) -> Scenario:
    """A noticed lease whose notice has been escalated past its cure deadline."""
    scenario = build_noticed_lease(
        api, cure_period_days=cure_period_days, clock=issued_at, **notice_kwargs
    )
    set_clock(api, escalate_at)
    scenario["notice"] = escalate_notice(api, scenario["notice"]["id"])
    scenario["leases"]["A-200"] = fetch_lease(api, scenario.lease_id("A-200"))
    scenario["leases"]["A-100"] = fetch_lease(api, scenario.lease_id("A-100"))
    scenario["center"] = fetch_center(api, scenario.center_id)
    return scenario


def build_signed_certificate(
    api: ApiClient,
    expedite_requested: Optional[bool] = None,
    measurement_id: Optional[str] = None,
    clock: Optional[str] = DEFAULT_CLOCK_UTC,
) -> Scenario:
    """A clean open lease with a certificate the tenant has already signed."""
    scenario = build_center_with_leases(
        api,
        [
            {
                "suite_code": "A-100",
                "gla_sqft": 8000,
                "primary_use_code": "APPAREL",
                "base_rent_monthly_cents": 1000000,
            }
        ],
        total_gla_sqft=10000,
        clock=clock,
    )
    certificate = request_certificate(
        api,
        scenario.lease_id("A-100"),
        measurement_id=measurement_id,
        expedite_requested=expedite_requested,
    )
    scenario["certificate"] = sign_certificate(
        api, certificate["id"], scenario.tenant_id("A-100")
    )
    return scenario


def build_frozen_center(
    api: ApiClient, clock: Optional[str] = DEFAULT_CLOCK_UTC
) -> Scenario:
    """A center frozen by occupancy: one open suite far below half the area.

    The suite opens first — opening is itself blocked while frozen — and a
    second, larger suite is drafted afterwards so a test has something to try to
    execute against the frozen center.
    """
    scenario = build_center_with_leases(
        api,
        [
            {
                "suite_code": "A-100",
                "gla_sqft": 2000,
                "primary_use_code": "APPAREL",
                "base_rent_monthly_cents": 500000,
            },
            {
                "suite_code": "A-200",
                "gla_sqft": 4000,
                "primary_use_code": "COFFEE",
                "base_rent_monthly_cents": 600000,
                "state": "DRAFT",
            },
        ],
        total_gla_sqft=100000,
        clock=clock,
    )
    scenario["center"] = fetch_center(api, scenario.center_id)
    return scenario
