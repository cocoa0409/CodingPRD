"""Composite setup helpers for the Lab-Equipment-Sharing test suite.

Most claims need 5–15 API calls to reach the testable state (create
lab-owner User → create Lab → bootstrap end User → identity-verify →
register Equipment → draft + publish BillingRule → request Authorization
→ approve owner step → optionally approve platform step → reach a
particular clock instant → create Reservation). These helpers wrap those
preambles so tests focus on assertions.

Identity threading (PRD §2.1):
- PlatformAdmin is OPAQUE → ADMIN constant is fine.
- LabOwner is ENTITY-BACKED on the User table. Every ownership-gated
  call MUST use make_lab_owner_headers(owner_user['id']) — the User row
  whose id was passed as lab.contact_user_id.
- User is ENTITY-BACKED on the User table. Every ownership-gated call
  MUST use make_user_headers(user['id']).

Setup helpers use get_success_data (lenient validator), so a broken
precondition surfaces as a clear setup error rather than as a confusing
assertion failure inside the test body.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    accept_maintenance_window_payload,
    check_out_payload,
    clock_payload,
    create_authorization_payload,
    create_billing_rule_payload,
    create_equipment_payload,
    create_lab_payload,
    create_maintenance_window_payload,
    create_reservation_payload,
    create_user_payload,
    identity_verified_payload,
    payment_confirmed_payload,
    random_external_user_id,
    reject_maintenance_window_payload,
    update_equipment_payload,
)
from .test_users import (
    TEST_USERS,
    make_lab_owner_headers,
    make_user_headers,
)


# ===========================================================================
# Shared admin headers (PlatformAdmin is opaque — safe constant)
# ===========================================================================
ADMIN = TEST_USERS["platform_admin_headers"]
ADMIN_ALT = TEST_USERS["platform_admin_headers_alt"]


# ===========================================================================
# Time helpers
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """ISO 8601 UTC with millisecond precision, Z-suffixed.
    PRD §2.4: 'ISO 8601 UTC with three fractional digits'."""
    return dt.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def hours_from(dt: datetime, hours: int) -> str:
    return iso_z(dt + timedelta(hours=hours))


def minutes_from(dt: datetime, minutes: int) -> str:
    return iso_z(dt + timedelta(minutes=minutes))


def advance_clock_to(target_iso: str,
                     headers: Optional[Dict[str, str]] = None) -> None:
    """PRD §3.8: '/_clock/advance ... accepts a target_time ISO timestamp
    and runs every due time-gated transition'."""
    get_success_data(api_client.advance_clock(
        clock_payload(target_iso), headers or ADMIN,
    ))


def set_clock_initial(target_iso: str = "2026-05-12T00:00:00.000Z") -> str:
    """Advance the clock to a canonical anchor used across fixtures."""
    advance_clock_to(target_iso)
    return target_iso


# ===========================================================================
# User provisioning (PlatformAdmin)
# ===========================================================================
def create_user(
    *,
    affiliation: str = "WITHIN_SCHOOL",
    training_certificates: Optional[List[str]] = None,
    department: str = "dept-default",
    external_user_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'End users are likewise provisioned by a PlatformAdmin.'
    Returns the unverified User (identity_verified=false)."""
    payload = create_user_payload(
        affiliation=affiliation,
        training_certificates=training_certificates,
        department=department,
        external_user_id=external_user_id,
        **overrides,
    )
    return get_success_data(api_client.create_user(payload, ADMIN))


def verify_user_identity(user: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.1/§3.8: 'a second VERIFIED event for the same user is a no-op
    success'; here we send the first VERIFIED event."""
    get_success_data(api_client.deliver_identity_verified(
        identity_verified_payload(external_user_id=user["external_user_id"]),
        ADMIN,
    ))
    return get_success_data(api_client.get_user(user["id"], ADMIN))


def create_verified_user(
    *,
    affiliation: str = "WITHIN_SCHOOL",
    training_certificates: Optional[List[str]] = None,
    department: str = "dept-default",
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a User and immediately fire the identity-verified event.
    PRD §3.1: 'A freshly provisioned user is unverified ... until the
    identity-verification system asynchronously emits a VERIFIED event'."""
    user = create_user(
        affiliation=affiliation,
        training_certificates=training_certificates,
        department=department,
        **overrides,
    )
    return verify_user_identity(user)


# ===========================================================================
# Lab + LabOwner pair
# ===========================================================================
def create_lab_with_owner(
    *,
    revenue_share_bps: int = 8000,
    institution: str = "school-alpha",
    department: str = "dept-alpha",
    lab_name: Optional[str] = None,
    owner_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create the lab-owning User first, then the Lab whose
    contact_user_id equals that User.id. Returns (lab, owner_user).

    PRD §2.1: 'When X-User-Role is LabOwner, X-User-ID is the id of the
    acting User; ownership checks on any Lab compare the lab's
    contact_user_id to X-User-ID'."""
    owner_user = create_verified_user(**(owner_overrides or {}))
    lab = get_success_data(api_client.create_lab(
        create_lab_payload(
            name=lab_name,
            institution=institution,
            department=department,
            contact_user_id=owner_user["id"],
            revenue_share_bps=revenue_share_bps,
        ),
        ADMIN,
    ))
    return lab, owner_user


# ===========================================================================
# Equipment
# ===========================================================================
def register_equipment(
    *,
    lab: Dict[str, Any],
    owner_user: Dict[str, Any],
    value_tier: str = "STANDARD",
    sharing_scope: str = "WITHIN_SCHOOL",
    slot_granularity: str = "HOUR",
    lead_time_hours: int = 0,
    single_user_duration_limit_hours: int = 8,
    peak_window_start_hour: int = 22,
    peak_window_end_hour: int = 23,
    required_training_codes: Optional[List[str]] = None,
    allowed_sample_types: Optional[List[str]] = None,
    calibration_expires_at: str = "2099-01-01T00:00:00.000Z",
    safety_inspection_expires_at: str = "2099-01-01T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'A LabOwner registers an Equipment resource under their
    owned lab.' Ownership-gated by lab.contact_user_id (PRD §2.1) — must
    use make_lab_owner_headers(owner_user['id'])."""
    payload = create_equipment_payload(
        lab_id=lab["id"],
        value_tier=value_tier,
        sharing_scope=sharing_scope,
        slot_granularity=slot_granularity,
        lead_time_hours=lead_time_hours,
        single_user_duration_limit_hours=single_user_duration_limit_hours,
        peak_window_start_hour=peak_window_start_hour,
        peak_window_end_hour=peak_window_end_hour,
        required_training_codes=required_training_codes,
        allowed_sample_types=allowed_sample_types,
        calibration_expires_at=calibration_expires_at,
        safety_inspection_expires_at=safety_inspection_expires_at,
        **overrides,
    )
    return get_success_data(api_client.create_equipment(
        payload, make_lab_owner_headers(owner_user["id"]),
    ))


# ===========================================================================
# Billing rules
# ===========================================================================
def draft_billing_rule(
    *,
    equipment: Dict[str, Any],
    owner_user: Dict[str, Any],
    mode: str = "BY_TIME",
    internal_rate_per_hour_cents: int = 10000,
    external_rate_per_hour_cents: int = 20000,
    inter_school_rate_per_hour_cents: int = 15000,
    internal_rate_per_sample_cents: int = 500,
    external_rate_per_sample_cents: int = 800,
    inter_school_rate_per_sample_cents: int = 600,
    peak_multiplier_bps: int = 12500,
    consumables_flat_cents: int = 500,
    platform_fee_bps: int = 1000,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5 draft step. Ownership-gated to LabOwner of equipment.lab_id.
    """
    payload = create_billing_rule_payload(
        mode=mode,
        internal_rate_per_hour_cents=internal_rate_per_hour_cents,
        external_rate_per_hour_cents=external_rate_per_hour_cents,
        inter_school_rate_per_hour_cents=inter_school_rate_per_hour_cents,
        internal_rate_per_sample_cents=internal_rate_per_sample_cents,
        external_rate_per_sample_cents=external_rate_per_sample_cents,
        inter_school_rate_per_sample_cents=
            inter_school_rate_per_sample_cents,
        peak_multiplier_bps=peak_multiplier_bps,
        consumables_flat_cents=consumables_flat_cents,
        platform_fee_bps=platform_fee_bps,
        **overrides,
    )
    return get_success_data(api_client.create_billing_rule(
        equipment["id"], payload,
        make_lab_owner_headers(owner_user["id"]),
    ))


def publish_billing_rule(
    *,
    equipment: Dict[str, Any],
    rule: Dict[str, Any],
    owner_user: Dict[str, Any],
) -> Dict[str, Any]:
    """PRD §3.5: 'Publishing transitions the rule to PUBLISHED'."""
    return get_success_data(api_client.publish_billing_rule(
        equipment["id"], rule["id"],
        make_lab_owner_headers(owner_user["id"]),
    ))


def draft_and_publish_billing_rule(
    *,
    equipment: Dict[str, Any],
    owner_user: Dict[str, Any],
    **rule_overrides: Any,
) -> Dict[str, Any]:
    """Two-step convenience: draft then publish, return the PUBLISHED rule.
    """
    draft = draft_billing_rule(
        equipment=equipment, owner_user=owner_user, **rule_overrides,
    )
    return publish_billing_rule(
        equipment=equipment, rule=draft, owner_user=owner_user,
    )


# ===========================================================================
# Authorizations
# ===========================================================================
def request_authorization(
    *,
    equipment: Dict[str, Any],
    user: Dict[str, Any],
    sample_type: str = "S",
    urgency: str = "NORMAL",
) -> Dict[str, Any]:
    """PRD §3.2: 'The end user opens the request directly against the
    target instrument by supplying their own user_id (which must equal
    X-User-ID)'. Ownership-gated to the User role."""
    payload = create_authorization_payload(
        user_id=user["id"], sample_type=sample_type, urgency=urgency,
    )
    return get_success_data(api_client.create_authorization(
        equipment["id"], payload, make_user_headers(user["id"]),
    ))


def approve_authorization_as_owner(
    *, authorization: Dict[str, Any], owner_user: Dict[str, Any],
) -> Dict[str, Any]:
    """LabOwner step (PRD §3.2). Ownership-gated to lab.contact_user_id."""
    return get_success_data(api_client.approve_authorization(
        authorization["id"],
        make_lab_owner_headers(owner_user["id"]),
    ))


def approve_authorization_as_platform(
    *, authorization: Dict[str, Any],
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PlatformAdmin step (PRD §3.2)."""
    return get_success_data(api_client.approve_authorization(
        authorization["id"], admin_headers or ADMIN,
    ))


def request_and_approve_authorization(
    *,
    equipment: Dict[str, Any],
    user: Dict[str, Any],
    owner_user: Dict[str, Any],
    sample_type: str = "S",
    urgency: str = "NORMAL",
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Walk the request through every necessary approval step to APPROVED.

    PRD §3.2: 'For a STANDARD instrument, the owner step alone is
    decisive'; 'For a HIGH_VALUE instrument ... When urgency is URGENT
    the same single owner approval transitions the authorization
    directly to APPROVED'; 'When urgency is NORMAL the owner approval
    first transitions the authorization to PENDING_PLATFORM ... a
    subsequent platform approval by any PlatformAdmin then ...
    transitions to APPROVED'.
    """
    auth = request_authorization(
        equipment=equipment, user=user,
        sample_type=sample_type, urgency=urgency,
    )
    auth = approve_authorization_as_owner(
        authorization=auth, owner_user=owner_user,
    )
    if auth.get("status") == "PENDING_PLATFORM":
        auth = approve_authorization_as_platform(
            authorization=auth, admin_headers=admin_headers,
        )
    return auth


def revoke_authorization(
    *, authorization: Dict[str, Any], owner_user: Dict[str, Any],
) -> Dict[str, Any]:
    return get_success_data(api_client.revoke_authorization(
        authorization["id"],
        make_lab_owner_headers(owner_user["id"]),
    ))


# ===========================================================================
# Reservations
# ===========================================================================
def make_reservation(
    *,
    equipment: Dict[str, Any],
    user: Dict[str, Any],
    authorization: Dict[str, Any],
    start_at: str,
    end_at: str,
    requested_sample_count: int = 0,
) -> Dict[str, Any]:
    """PRD §3.3 happy path. Ownership-gated to the User role."""
    payload = create_reservation_payload(
        user_id=user["id"],
        authorization_id=authorization["id"],
        start_at=start_at, end_at=end_at,
        requested_sample_count=requested_sample_count,
    )
    return get_success_data(api_client.create_reservation(
        equipment["id"], payload, make_user_headers(user["id"]),
    ))


def check_in(*, reservation: Dict[str, Any], user: Dict[str, Any]
             ) -> Dict[str, Any]:
    return get_success_data(api_client.check_in_reservation(
        reservation["id"], make_user_headers(user["id"]),
    ))


def check_out(
    *,
    reservation: Dict[str, Any],
    user: Dict[str, Any],
    actual_sample_count: int = 0,
    status_handover: str = "NORMAL",
    abnormal_event_code: Any = None,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "actual_sample_count": actual_sample_count,
        "status_handover": status_handover,
    }
    if abnormal_event_code is not None:
        kwargs["abnormal_event_code"] = abnormal_event_code
    payload = check_out_payload(**kwargs)
    return get_success_data(api_client.check_out_reservation(
        reservation["id"], payload, make_user_headers(user["id"]),
    ))


def cancel_reservation(*, reservation: Dict[str, Any],
                       user: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api_client.cancel_reservation(
        reservation["id"], make_user_headers(user["id"]),
    ))


# ===========================================================================
# Maintenance windows
# ===========================================================================
def schedule_maintenance(
    *,
    equipment: Dict[str, Any],
    owner_user: Dict[str, Any],
    start_at: str,
    end_at: str,
    kind: str = "PERIODIC",
    maintenance_notes: str = "scheduled service",
) -> Dict[str, Any]:
    payload = create_maintenance_window_payload(
        kind=kind, start_at=start_at, end_at=end_at,
        maintenance_notes=maintenance_notes,
    )
    return get_success_data(api_client.create_maintenance_window(
        equipment["id"], payload,
        make_lab_owner_headers(owner_user["id"]),
    ))


def accept_maintenance(
    *, window: Dict[str, Any], owner_user: Dict[str, Any],
    acceptance_notes: str = "ok",
) -> Dict[str, Any]:
    return get_success_data(api_client.accept_maintenance_window(
        window["id"],
        make_lab_owner_headers(owner_user["id"]),
        accept_maintenance_window_payload(acceptance_notes=acceptance_notes),
    ))


def reject_maintenance(
    *, window: Dict[str, Any], owner_user: Dict[str, Any],
    acceptance_notes: str = "rework",
) -> Dict[str, Any]:
    return get_success_data(api_client.reject_maintenance_window(
        window["id"],
        make_lab_owner_headers(owner_user["id"]),
        reject_maintenance_window_payload(acceptance_notes=acceptance_notes),
    ))


# ===========================================================================
# Refetch helpers
# ===========================================================================
def get_lab(lab_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_lab(lab_id, ADMIN))


def get_equipment(equipment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_equipment(equipment_id, ADMIN))


def get_reservation(reservation_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_reservation(
        reservation_id, ADMIN,
    ))


def get_authorization(authorization_id: str) -> Dict[str, Any]:
    """No dedicated GET in PRD §4; list audit-events as a workaround when
    needed. For most cases the response from the latest approve/reject
    call is sufficient. We can scan via list_audit_events if needed."""
    raise NotImplementedError(
        "PRD §4 does not declare GET /authorizations/{id}; use the "
        "response of the most recent approve/reject/revoke instead."
    )


def list_audit_events(
    *, subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    limit: int = 100, offset: int = 0,
) -> List[Dict[str, Any]]:
    """List audit events (PRD §4 admin/owner-only)."""
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if subject_type is not None:
        params["subject_type"] = subject_type
    if subject_id is not None:
        params["subject_id"] = subject_id
    if actor_user_id is not None:
        params["actor_user_id"] = actor_user_id
    data, _ = validate_paginated(api_client.list_audit_events(
        headers or ADMIN, params=params,
    ))
    return data


# ===========================================================================
# Composite scenarios (Tier 2/3)
# ===========================================================================
def setup_basic_scenario(
    *,
    user_affiliation: str = "WITHIN_SCHOOL",
    user_training: Optional[List[str]] = None,
    sharing_scope: str = "WITHIN_SCHOOL",
    value_tier: str = "STANDARD",
    revenue_share_bps: int = 8000,
    slot_granularity: str = "HOUR",
    lead_time_hours: int = 0,
    single_user_duration_limit_hours: int = 8,
    peak_window_start_hour: int = 22,
    peak_window_end_hour: int = 23,
    mode: str = "BY_TIME",
    internal_rate_per_hour_cents: int = 10000,
    internal_rate_per_sample_cents: int = 500,
    peak_multiplier_bps: int = 12500,
    consumables_flat_cents: int = 500,
    platform_fee_bps: int = 1000,
    initial_clock: str = "2026-05-12T00:00:00.000Z",
    required_training_codes: Optional[List[str]] = None,
    allowed_sample_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Walk the full happy-path setup through approved authorization, ready
    to book reservations:
      anchor clock → User + identity verify → Lab + LabOwner → Equipment
      → BillingRule (draft → publish) → User → approved Authorization.
    Returns a dict so tests can name fields explicitly.
    """
    set_clock_initial(initial_clock)
    lab, owner_user = create_lab_with_owner(
        revenue_share_bps=revenue_share_bps,
    )
    end_user = create_verified_user(
        affiliation=user_affiliation,
        training_certificates=(
            user_training if user_training is not None else ["T1"]
        ),
    )
    equipment = register_equipment(
        lab=lab, owner_user=owner_user,
        value_tier=value_tier,
        sharing_scope=sharing_scope,
        slot_granularity=slot_granularity,
        lead_time_hours=lead_time_hours,
        single_user_duration_limit_hours=
            single_user_duration_limit_hours,
        peak_window_start_hour=peak_window_start_hour,
        peak_window_end_hour=peak_window_end_hour,
        required_training_codes=required_training_codes,
        allowed_sample_types=allowed_sample_types,
    )
    rule = draft_and_publish_billing_rule(
        equipment=equipment, owner_user=owner_user,
        mode=mode,
        internal_rate_per_hour_cents=internal_rate_per_hour_cents,
        internal_rate_per_sample_cents=internal_rate_per_sample_cents,
        peak_multiplier_bps=peak_multiplier_bps,
        consumables_flat_cents=consumables_flat_cents,
        platform_fee_bps=platform_fee_bps,
    )
    authorization = request_and_approve_authorization(
        equipment=equipment, user=end_user, owner_user=owner_user,
        urgency=("URGENT" if value_tier == "HIGH_VALUE" else "NORMAL"),
    )
    return {
        "lab": lab,
        "owner_user": owner_user,
        "user": end_user,
        "equipment": equipment,
        "rule": rule,
        "authorization": authorization,
        "clock": initial_clock,
    }


def setup_scenario_with_reservation(
    *,
    start_at: str = "2026-05-12T09:00:00.000Z",
    end_at: str = "2026-05-12T11:00:00.000Z",
    requested_sample_count: int = 0,
    **scenario_overrides: Any,
) -> Dict[str, Any]:
    """setup_basic_scenario + one BOOKED reservation. The default window
    is a non-peak 2h slot under the canonical 22-23 peak window."""
    s = setup_basic_scenario(**scenario_overrides)
    reservation = make_reservation(
        equipment=s["equipment"], user=s["user"],
        authorization=s["authorization"],
        start_at=start_at, end_at=end_at,
        requested_sample_count=requested_sample_count,
    )
    s["reservation"] = reservation
    return s


# ===========================================================================
# Difficulty-design fixtures (SCAFFOLD_DIFFICULTY_DESIGN.yaml)
# ===========================================================================
def setup_fee_compare_scenario_estimated_vs_final() -> Dict[str, Any]:
    """Difficulty index: dual_variant_calc/reservation_fee_estimated_vs_final.

    Inputs (from the difficulty-design recipe):
      revenue_share_bps=8000, BY_TIME rate=10000 cents/hr,
      peak_multiplier=12500, platform_fee_bps=1000,
      consumables_flat_cents=500, peak window 22-23 (so 09:00-11:00 has
      zero peak overlap), reservation [09:00, 11:00) requested_sample=0,
      check-out at 11:01 (121 min → ceil(121/60)=3 billed hours).

    Tests then drive the reservation through check-in and check-out and
    assert estimated_fee_cents=22500 / final_fee_cents=33500.
    """
    set_clock_initial("2026-05-12T08:00:00.000Z")
    lab, owner_user = create_lab_with_owner(revenue_share_bps=8000)
    user = create_verified_user(
        affiliation="WITHIN_SCHOOL", training_certificates=["T1"],
    )
    equipment = register_equipment(
        lab=lab, owner_user=owner_user,
        value_tier="STANDARD", sharing_scope="WITHIN_SCHOOL",
        slot_granularity="HOUR", lead_time_hours=0,
        single_user_duration_limit_hours=8,
        peak_window_start_hour=22, peak_window_end_hour=23,
        required_training_codes=["T1"], allowed_sample_types=["S"],
    )
    rule = draft_and_publish_billing_rule(
        equipment=equipment, owner_user=owner_user,
        mode="BY_TIME",
        internal_rate_per_hour_cents=10000,
        external_rate_per_hour_cents=20000,
        inter_school_rate_per_hour_cents=15000,
        internal_rate_per_sample_cents=500,
        external_rate_per_sample_cents=800,
        inter_school_rate_per_sample_cents=600,
        peak_multiplier_bps=12500,
        consumables_flat_cents=500,
        platform_fee_bps=1000,
    )
    authorization = request_and_approve_authorization(
        equipment=equipment, user=user, owner_user=owner_user,
    )
    return {
        "lab": lab, "owner_user": owner_user, "user": user,
        "equipment": equipment, "rule": rule,
        "authorization": authorization,
    }


def setup_hybrid_peak_scenario() -> Dict[str, Any]:
    """Difficulty index: combinatorial_formula/hybrid_fee_three_input_conditional.

    Equipment with peak window 22-23, HYBRID mode, rates as in recipe.
    Anchor clock to 2026-05-12T20:00:00Z so [22:00, 23:00) is reservable.
    """
    set_clock_initial("2026-05-12T20:00:00.000Z")
    lab, owner_user = create_lab_with_owner(revenue_share_bps=8000)
    user = create_verified_user(
        affiliation="WITHIN_SCHOOL", training_certificates=["T1"],
    )
    equipment = register_equipment(
        lab=lab, owner_user=owner_user,
        value_tier="STANDARD", sharing_scope="WITHIN_SCHOOL",
        slot_granularity="HOUR", lead_time_hours=0,
        single_user_duration_limit_hours=8,
        peak_window_start_hour=22, peak_window_end_hour=23,
        required_training_codes=["T1"], allowed_sample_types=["S"],
    )
    rule = draft_and_publish_billing_rule(
        equipment=equipment, owner_user=owner_user,
        mode="HYBRID",
        internal_rate_per_hour_cents=10000,
        external_rate_per_hour_cents=20000,
        inter_school_rate_per_hour_cents=15000,
        internal_rate_per_sample_cents=337,
        external_rate_per_sample_cents=500,
        inter_school_rate_per_sample_cents=400,
        peak_multiplier_bps=12500,
        consumables_flat_cents=500,
        platform_fee_bps=1000,
    )
    authorization = request_and_approve_authorization(
        equipment=equipment, user=user, owner_user=owner_user,
    )
    return {
        "lab": lab, "owner_user": owner_user, "user": user,
        "equipment": equipment, "rule": rule,
        "authorization": authorization,
    }


def setup_high_value_equipment_pair() -> Dict[str, Any]:
    """Difficulty index: non_linear_state_machine/authorization_branching...

    Build a Lab + LabOwner + verified User + TWO equipments — one
    HIGH_VALUE and one STANDARD — both with billing rules published, so
    tests can exercise PENDING_OWNER → PENDING_PLATFORM and the URGENT
    skip in one scenario.
    """
    set_clock_initial("2026-05-12T08:00:00.000Z")
    lab, owner_user = create_lab_with_owner(revenue_share_bps=8000)
    user = create_verified_user(
        affiliation="WITHIN_SCHOOL", training_certificates=["T1"],
    )
    e_high = register_equipment(
        lab=lab, owner_user=owner_user,
        value_tier="HIGH_VALUE", sharing_scope="WITHIN_SCHOOL",
        slot_granularity="HOUR", lead_time_hours=0,
        single_user_duration_limit_hours=8,
        peak_window_start_hour=22, peak_window_end_hour=23,
        required_training_codes=["T1"], allowed_sample_types=["S"],
    )
    draft_and_publish_billing_rule(
        equipment=e_high, owner_user=owner_user,
    )
    e_std = register_equipment(
        lab=lab, owner_user=owner_user,
        value_tier="STANDARD", sharing_scope="WITHIN_SCHOOL",
        slot_granularity="HOUR", lead_time_hours=0,
        single_user_duration_limit_hours=8,
        peak_window_start_hour=22, peak_window_end_hour=23,
        required_training_codes=["T1"], allowed_sample_types=["S"],
    )
    draft_and_publish_billing_rule(
        equipment=e_std, owner_user=owner_user,
    )
    return {
        "lab": lab, "owner_user": owner_user, "user": user,
        "equipment_high": e_high, "equipment_standard": e_std,
    }


def setup_cascade_revoke_scenario() -> Dict[str, Any]:
    """Difficulty index: transitive_cascade/revoke_authorization_chain.

    Approved authorization + two future-dated BOOKED reservations on the
    SAME equipment for the SAME user. Caller invokes /revoke and asserts
    the depth-3 cascade.
    """
    s = setup_basic_scenario(
        initial_clock="2026-05-12T08:00:00.000Z",
    )
    r_x = make_reservation(
        equipment=s["equipment"], user=s["user"],
        authorization=s["authorization"],
        start_at="2026-05-15T09:00:00.000Z",
        end_at="2026-05-15T10:00:00.000Z",
        requested_sample_count=0,
    )
    r_y = make_reservation(
        equipment=s["equipment"], user=s["user"],
        authorization=s["authorization"],
        start_at="2026-05-15T11:00:00.000Z",
        end_at="2026-05-15T12:00:00.000Z",
        requested_sample_count=0,
    )
    s["reservation_x"] = r_x
    s["reservation_y"] = r_y
    return s


def setup_maintenance_cascade_scenario() -> Dict[str, Any]:
    """Difficulty index: transitive_cascade/maintenance_window_in_progress_chain.

    Approved authorization + 1 BOOKED reservation [09:00, 11:00) +
    1 SCHEDULED maintenance window [10:00, 11:00) overlapping it (the
    second hour of the reservation intersects the window). Caller
    advances the clock to 10:00 to trigger the cascade.

    Reservation timestamps are kept on the HOUR slot grid (PRD §2.7) so
    that the §3.7 cascade is exercised rather than the §2.7 grid check.
    """
    s = setup_basic_scenario(
        initial_clock="2026-05-12T08:00:00.000Z",
    )
    reservation = make_reservation(
        equipment=s["equipment"], user=s["user"],
        authorization=s["authorization"],
        start_at="2026-05-12T09:00:00.000Z",
        end_at="2026-05-12T11:00:00.000Z",
        requested_sample_count=0,
    )
    window = schedule_maintenance(
        equipment=s["equipment"], owner_user=s["owner_user"],
        start_at="2026-05-12T10:00:00.000Z",
        end_at="2026-05-12T11:00:00.000Z",
        kind="PERIODIC",
    )
    s["reservation"] = reservation
    s["maintenance_window"] = window
    return s


def setup_overlap_scenario_with_two_users() -> Dict[str, Any]:
    """Difficulty index: resource_temporal_overlap/reservation_half_open_overlap.

    Same equipment, two distinct end users U1 and U2, each holding an
    APPROVED authorization on it. U1 already holds a [09:00, 10:00)
    BOOKED reservation. Tests then create adjacent and overlapping
    reservations from U2.
    """
    set_clock_initial("2026-05-12T08:00:00.000Z")
    lab, owner_user = create_lab_with_owner()
    u1 = create_verified_user(
        affiliation="WITHIN_SCHOOL", training_certificates=["T1"],
    )
    u2 = create_verified_user(
        affiliation="WITHIN_SCHOOL", training_certificates=["T1"],
    )
    equipment = register_equipment(
        lab=lab, owner_user=owner_user,
        slot_granularity="HOUR", lead_time_hours=0,
        peak_window_start_hour=22, peak_window_end_hour=23,
        required_training_codes=["T1"], allowed_sample_types=["S"],
    )
    draft_and_publish_billing_rule(
        equipment=equipment, owner_user=owner_user,
    )
    auth1 = request_and_approve_authorization(
        equipment=equipment, user=u1, owner_user=owner_user,
    )
    auth2 = request_and_approve_authorization(
        equipment=equipment, user=u2, owner_user=owner_user,
    )
    r1 = make_reservation(
        equipment=equipment, user=u1, authorization=auth1,
        start_at="2026-05-12T09:00:00.000Z",
        end_at="2026-05-12T10:00:00.000Z",
    )
    return {
        "lab": lab, "owner_user": owner_user,
        "user1": u1, "user2": u2,
        "equipment": equipment,
        "authorization1": auth1, "authorization2": auth2,
        "reservation1": r1,
    }


def setup_maintenance_overlap_scenario() -> Dict[str, Any]:
    """Difficulty index: resource_temporal_overlap/maintenance_window_overlap_blocking.

    Equipment + APPROVED authorization + SCHEDULED MaintenanceWindow
    [10:00, 12:00). Tests then attempt reservations at various intervals.
    """
    s = setup_basic_scenario(
        initial_clock="2026-05-12T08:00:00.000Z",
    )
    window = schedule_maintenance(
        equipment=s["equipment"], owner_user=s["owner_user"],
        start_at="2026-05-12T10:00:00.000Z",
        end_at="2026-05-12T12:00:00.000Z",
        kind="PERIODIC",
    )
    s["maintenance_window"] = window
    return s


def setup_priority_pair_state_vs_overlap() -> Dict[str, Any]:
    """Difficulty index: priority_pair_validation_conflict/state_vs_business_temporal_overlap.

    Same equipment, two users U1 (CHECKED_IN reservation [09:00,11:00))
    and U2 (APPROVED auth). Test then posts a U2 reservation
    [10:00,12:00) and asserts ERR_RESERVATION_OVERLAP (priority 15 wins).
    """
    set_clock_initial("2026-05-12T08:00:00.000Z")
    lab, owner_user = create_lab_with_owner()
    u1 = create_verified_user(
        affiliation="WITHIN_SCHOOL", training_certificates=["T1"],
    )
    u2 = create_verified_user(
        affiliation="WITHIN_SCHOOL", training_certificates=["T1"],
    )
    equipment = register_equipment(
        lab=lab, owner_user=owner_user,
        slot_granularity="HOUR", lead_time_hours=0,
        peak_window_start_hour=22, peak_window_end_hour=23,
        required_training_codes=["T1"], allowed_sample_types=["S"],
    )
    draft_and_publish_billing_rule(
        equipment=equipment, owner_user=owner_user,
    )
    auth1 = request_and_approve_authorization(
        equipment=equipment, user=u1, owner_user=owner_user,
    )
    auth2 = request_and_approve_authorization(
        equipment=equipment, user=u2, owner_user=owner_user,
    )
    r1 = make_reservation(
        equipment=equipment, user=u1, authorization=auth1,
        start_at="2026-05-12T09:00:00.000Z",
        end_at="2026-05-12T11:00:00.000Z",
    )
    advance_clock_to("2026-05-12T09:00:00.000Z")
    r1 = check_in(reservation=r1, user=u1)
    return {
        "lab": lab, "owner_user": owner_user,
        "user1": u1, "user2": u2,
        "equipment": equipment,
        "authorization1": auth1, "authorization2": auth2,
        "reservation1": r1,
    }


def setup_priority_pair_auth_vs_cert() -> Dict[str, Any]:
    """Difficulty index: priority_pair_validation_conflict/business_safety_cert_vs_business_referential_auth.

    Setup: equipment whose calibration_expires_at is in the past AND an
    Authorization that has been REVOKED. Both invariants are violated
    simultaneously; PRD §2.9 priority order dictates that the
    referential check (priority 7) reports the ERR_AUTHORIZATION_INVALID
    error before the certificate-freshness check (priority 8).

    We use revoke rather than authorization expiry because PRD does not
    fix AUTHORIZATION_TTL_DAYS in prose; revoke produces the same
    'not APPROVED' observable in a TTL-independent way.
    """
    set_clock_initial("2026-05-10T00:00:00.000Z")
    lab, owner_user = create_lab_with_owner()
    user = create_verified_user(
        affiliation="WITHIN_SCHOOL", training_certificates=["T1"],
    )
    equipment = register_equipment(
        lab=lab, owner_user=owner_user,
        slot_granularity="HOUR", lead_time_hours=0,
        peak_window_start_hour=22, peak_window_end_hour=23,
        required_training_codes=["T1"], allowed_sample_types=["S"],
        calibration_expires_at="2026-05-12T00:00:00.000Z",
        safety_inspection_expires_at="2030-01-01T00:00:00.000Z",
    )
    draft_and_publish_billing_rule(
        equipment=equipment, owner_user=owner_user,
    )
    authorization = request_and_approve_authorization(
        equipment=equipment, user=user, owner_user=owner_user,
    )
    # Revoke the authorization while clock is still pre-cert-expiry, so
    # the revoke is permitted unambiguously. Then advance the clock so
    # the certificate is also expired.
    revoke_authorization(
        authorization=authorization, owner_user=owner_user,
    )
    advance_clock_to("2026-05-12T10:00:00.000Z")
    return {
        "lab": lab, "owner_user": owner_user, "user": user,
        "equipment": equipment, "authorization": authorization,
    }


def setup_round_trip_balance_scenario() -> Dict[str, Any]:
    """Difficulty index: compensating_invariant/settlement_balance_round_trip_invariant.

    Basic scenario, no reservations yet. Test creates a reservation +
    cancels with full refund and asserts settlement_balance is restored.
    """
    return setup_basic_scenario(
        initial_clock="2026-05-12T08:00:00.000Z",
    )


def setup_equipment_round_trip_scenario() -> Dict[str, Any]:
    """Difficulty index: compensating_invariant/equipment_status_round_trip_invariant.

    Equipment in AVAILABLE state, no maintenance windows yet. Test then
    drives one full PERIODIC maintenance cycle and asserts return to
    AVAILABLE.
    """
    return setup_basic_scenario(
        initial_clock="2026-05-12T08:00:00.000Z",
    )


def setup_peak_boundary_scenario() -> Dict[str, Any]:
    """Difficulty index: boundary_precision_check/peak_overlap_strict_positive_minutes.

    Equipment with peak window 22-23, BY_TIME mode, internal_rate=10000,
    peak_multiplier=12500, platform_fee_bps=1000, consumables=500. Clock
    anchored at 2026-05-12T20:00.
    """
    set_clock_initial("2026-05-12T20:00:00.000Z")
    lab, owner_user = create_lab_with_owner(revenue_share_bps=8000)
    user = create_verified_user(
        affiliation="WITHIN_SCHOOL", training_certificates=["T1"],
    )
    equipment = register_equipment(
        lab=lab, owner_user=owner_user,
        value_tier="STANDARD", sharing_scope="WITHIN_SCHOOL",
        slot_granularity="HOUR", lead_time_hours=0,
        single_user_duration_limit_hours=8,
        peak_window_start_hour=22, peak_window_end_hour=23,
        required_training_codes=["T1"], allowed_sample_types=["S"],
    )
    rule = draft_and_publish_billing_rule(
        equipment=equipment, owner_user=owner_user,
        mode="BY_TIME",
        internal_rate_per_hour_cents=10000,
        internal_rate_per_sample_cents=500,
        peak_multiplier_bps=12500,
        consumables_flat_cents=500,
        platform_fee_bps=1000,
    )
    authorization = request_and_approve_authorization(
        equipment=equipment, user=user, owner_user=owner_user,
    )
    return {
        "lab": lab, "owner_user": owner_user, "user": user,
        "equipment": equipment, "rule": rule,
        "authorization": authorization,
    }


__all__ = [
    "ADMIN", "ADMIN_ALT",
    "iso_z", "hours_from", "minutes_from",
    "advance_clock_to", "set_clock_initial",
    "create_user", "verify_user_identity", "create_verified_user",
    "create_lab_with_owner",
    "register_equipment",
    "draft_billing_rule", "publish_billing_rule",
    "draft_and_publish_billing_rule",
    "request_authorization",
    "approve_authorization_as_owner",
    "approve_authorization_as_platform",
    "request_and_approve_authorization",
    "revoke_authorization",
    "make_reservation", "check_in", "check_out", "cancel_reservation",
    "schedule_maintenance", "accept_maintenance", "reject_maintenance",
    "get_lab", "get_equipment", "get_reservation",
    "list_audit_events",
    "setup_basic_scenario", "setup_scenario_with_reservation",
    "setup_fee_compare_scenario_estimated_vs_final",
    "setup_hybrid_peak_scenario",
    "setup_high_value_equipment_pair",
    "setup_cascade_revoke_scenario",
    "setup_maintenance_cascade_scenario",
    "setup_overlap_scenario_with_two_users",
    "setup_maintenance_overlap_scenario",
    "setup_priority_pair_state_vs_overlap",
    "setup_priority_pair_auth_vs_cert",
    "setup_round_trip_balance_scenario",
    "setup_equipment_round_trip_scenario",
    "setup_peak_boundary_scenario",
]
