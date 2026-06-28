"""Recurring-plan lifecycle invariants, upsell-referral TTL, and pricing-config activation."""
import pytest

from test_helpers import (
    api_client as api, get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_active_pricing_config, create_draft_pricing_config,
    create_home_with_systems, create_home_with_active_plan, create_crew,
    create_completed_work_order, enroll_plan, set_clock,
    duct_line,
)

PA = TEST_USERS["plan_admin_headers"]
DI = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Difficulty: compensating_invariant (has_active_plan pause/resume)
# ===========================================================================
def test_pause_then_resume_restores_has_active_plan():
    """PRD §3.9: "Pausing, resuming, and cancelling each recompute the home's
    has_active_plan and cascade to the home — pause and cancel can drop it to
    false (when no other active plan remains), resume restores it to true"

    Design: Difficulty/compensating_invariant/compensating_pricing_config_active_count_invariant
    """
    home, systems, plan = create_home_with_active_plan(cadence_months=12, num_systems=1,
                                                      register_count=5, zone_code="Z1")
    get_success_data(api.pause_recurring_plan(plan["id"], PA))
    home_paused = get_success_data(api.get_home(home["id"], PA))
    assert home_paused["has_active_plan"] is False, "pause must drop has_active_plan to false"

    resumed = validate_success(api.resume_recurring_plan(plan["id"], PA), expected_status=200)
    assert resumed["lifecycle_status"] == "ACTIVE"
    home_resumed = get_success_data(api.get_home(home["id"], PA))
    assert home_resumed["has_active_plan"] is True, "resume must restore has_active_plan to true"


# ===========================================================================
# Corner: entities
# ===========================================================================
def test_create_home_returns_201_with_defaults():
    """PRD §3.1: "On creation a home starts with an active_system_count of zero and
    has_active_plan false."
    PRD §2.4: "The version field is an integer that starts at 1 on creation"

    Design: Corner/entities/entity_create_home_returns_201_with_defaults
    """
    owner = get_success_data(api.create_homeowner(
        {"full_name": "Ann C", "email": "annc655@x.com", "phone": "555-0200"}, PA))
    resp = api.create_home(
        {"homeowner_id": owner["id"], "address_line": "20 Vent Rd",
         "zone_code": "Z1", "square_footage": 1900}, PA)
    data = validate_success(resp, expected_status=201)
    assert data["active_system_count"] == 0
    assert data["has_active_plan"] is False
    assert data["version"] == 1


def test_get_home_not_found_returns_404():
    """PRD §2.6: "A request for a system under a home that does not exist fails with
    ERR_HOME_NOT_FOUND"

    Design: Corner/entities/entity_get_home_not_found_returns_404
    """
    resp = api.get_home("00000000-0000-4000-8000-000000000abc", DI)
    validate_error(resp, ApiErrorId.ERR_HOME_NOT_FOUND.value)


def test_work_order_missing_service_lines_returns_invalid_request():
    """PRD §3.3: "A body that violates any of these shape rules — empty service
    lines, an unknown enumeration value, an out-of-range integer, or a
    service-line/system_id pairing rule — is rejected with ERR_INVALID_REQUEST."

    Design: Corner/entities/entity_missing_required_field_work_order_returns_invalid_request
    """
    home, systems = create_home_with_systems(0, zone_code="Z1")
    resp = api.create_work_order({"home_id": home["id"], "requested_start_minute": 540}, DI)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_addons_defaults_to_empty_array():
    """PRD §3.3: "The addons array holds codes drawn from SANITIZER, UV, and COIL,
    and is deduplicated; if omitted it defaults to empty."

    Design: Corner/entities/entity_addons_default_empty_array_applied
    """
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    resp = api.create_work_order(
        {"home_id": home["id"], "service_lines": [duct_line(systems[0]["id"])],
         "requested_start_minute": 540}, DI)
    data = validate_success(resp, expected_status=201)
    assert data["addons"] == [], f"Expected addons [], got {data['addons']}"


def test_active_system_count_computed_from_active_children():
    """PRD §3.1: "Adding a system recomputes the home's active_system_count."
    PRD §2.5: "The active_system_count is the number of child HvacSystem rows whose
    status is ACTIVE"

    Design: Corner/entities/entity_active_system_count_computed_input_ignored
    """
    home, systems = create_home_with_systems(2, register_count=5, zone_code="Z1")
    fetched = get_success_data(api.get_home(home["id"], DI))
    assert fetched["active_system_count"] == 2, \
        f"Expected active_system_count 2, got {fetched['active_system_count']}"


def test_invalid_service_type_enum_rejected():
    """PRD §3.3: "Each entry in service_lines carries a service_type that is one of
    DUCT, DRYER_VENT, or SANITIZE."

    Design: Corner/entities/entity_invalid_enum_service_type_rejected
    """
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    resp = api.create_work_order(
        {"home_id": home["id"],
         "service_lines": [{"service_type": "CHIMNEY", "system_id": systems[0]["id"]}],
         "requested_start_minute": 540}, DI)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_system_create_under_missing_home_returns_404():
    """PRD §2.6: "A request for a system under a home that does not exist fails with
    ERR_HOME_NOT_FOUND"

    Design: Corner/entities/entity_system_create_requires_existing_home_parent
    """
    resp = api.add_system("00000000-0000-4000-8000-0000000000ff",
                         {"label": "Orphan", "register_count": 4}, PA)
    validate_error(resp, ApiErrorId.ERR_HOME_NOT_FOUND.value)


def test_list_homes_returns_paginated_array_envelope():
    """PRD §2.3: "Every list response includes limit, offset, total_count, and
    has_more in the meta object of the envelope."

    Design: Corner/entities/entity_list_homes_pagination_envelope
    """
    create_home_with_systems(0, zone_code="Z1")
    data, meta = validate_paginated(api.list_homes(DI))
    assert isinstance(data, list)
    assert meta["total_count"] >= 1
    assert "has_more" in meta


# ===========================================================================
# Corner: validations
# ===========================================================================
def test_quote_without_active_config_rejected():
    """PRD §3.2: "a quote attempted when no config is ACTIVE fails with
    ERR_NO_ACTIVE_PRICING_CONFIG."

    Design: Corner/validations/val_quote_without_active_config_rejected
    """
    from test_helpers import create_inspected_work_order
    create_draft_pricing_config()  # exists but not ACTIVE
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo = create_inspected_work_order(home["id"], [duct_line(systems[0]["id"])], crew["id"],
                                    inspect_overrides={"before_photo_count": 1, "dust_severity": 2})
    from test_helpers import make_technician_headers
    resp = api.quote_work_order(wo["id"], make_technician_headers(crew["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_PRICING_CONFIG.value)


def test_inspect_rejects_decommissioned_system_line():
    """PRD §3.3: "Every service line in an inspect must reference systems that are
    ACTIVE on the work order's home; a line pointing at a decommissioned system
    fails with ERR_SYSTEM_NOT_ACTIVE."

    Design: Corner/validations/val_inspect_rejects_decommissioned_system_line
    """
    from test_helpers import make_technician_headers
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    wo = get_success_data(api.create_work_order(
        {"home_id": home["id"], "service_lines": [duct_line(systems[0]["id"])],
         "requested_start_minute": 540}, DI))
    get_success_data(api.decommission_system(home["id"], systems[0]["id"], PA))
    crew = create_crew(home_zone_code="Z1")
    resp = api.inspect_work_order(wo["id"], {"before_photo_count": 1, "dust_severity": 2},
                                 make_technician_headers(crew["id"]))
    validate_error(resp, ApiErrorId.ERR_SYSTEM_NOT_ACTIVE.value)


def test_complete_with_insufficient_after_photos_rejected():
    """PRD §3.8: "At least one after-service photo is required: after_photo_count
    must be at least one, else ERR_INSUFFICIENT_AFTER_PHOTOS."

    Design: Corner/validations/val_complete_insufficient_after_photos_rejected
    """
    from test_helpers import create_in_progress_work_order, make_technician_headers
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo, route = create_in_progress_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"],
        inspect_overrides={"before_photo_count": 1, "dust_severity": 2},
        service_date="2026-04-26")
    resp = api.complete_work_order(
        wo["id"],
        {"after_photo_count": 0, "dust_severity": 2,
         "performed_service_lines": [duct_line(systems[0]["id"])]},
        make_technician_headers(crew["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_AFTER_PHOTOS.value)


def test_second_enrollment_rejected_plan_already_exists():
    """PRD §3.9: "A home may hold at most one plan whose lifecycle_status is ACTIVE
    or PAUSED at a time; a second enrollment attempt is rejected with
    ERR_PLAN_ALREADY_EXISTS."

    Design: Corner/validations/val_plan_already_exists_on_second_enroll
    """
    home, systems, plan = create_home_with_active_plan(cadence_months=12, num_systems=1,
                                                      register_count=5, zone_code="Z1")
    current = get_success_data(api.get_home(home["id"], PA))
    resp = api.create_recurring_plan(
        home["id"], {"cadence_months": 6, "expected_home_version": current["version"]}, PA)
    validate_error(resp, ApiErrorId.ERR_PLAN_ALREADY_EXISTS.value)


# ===========================================================================
# Corner: endpoints
# ===========================================================================
def test_activate_second_config_retires_prior_active():
    """PRD §3.2: "Activating a DRAFT config moves its status from DRAFT to ACTIVE
    and, as a cascade, retires whatever config was previously ACTIVE by moving its
    status to RETIRED."

    Design: Corner/endpoints/endpoint_pricing_config_activate_retires_prior_active
    """
    cfg1 = create_active_pricing_config()
    cfg2 = create_draft_pricing_config(duct_base_cents=13000)
    activated2 = validate_success(api.activate_pricing_config(cfg2["id"], PA), expected_status=200)
    assert activated2["status"] == "ACTIVE"
    cfg1_now = get_success_data(api.get_pricing_config(cfg1["id"], PA))
    assert cfg1_now["status"] == "RETIRED", \
        f"prior ACTIVE config must be RETIRED, got {cfg1_now['status']}"


def test_expire_before_ttl_leaves_referral_pending():
    """PRD §3.10: "may also be forced explicitly, in which case it is a no-op
    leaving the referral PENDING if the thirty days have not yet elapsed."

    Design: Corner/endpoints/endpoint_referral_expire_before_ttl_rejected_as_bad_state
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo, route = create_completed_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"],
        inspect_overrides={"before_photo_count": 1, "dust_severity": 6},
        complete_overrides={"after_photo_count": 2, "dust_severity": 6,
                            "recommend_hvac_repair": True},
        service_date="2026-04-28")
    referrals, _ = validate_paginated(
        api.list_upsell_referrals(PA, params={"work_order_id": wo["id"]}))
    ref = referrals[0]
    # Clock not advanced past created_at + 30 days.
    expired = validate_success(api.expire_referral(ref["id"], PA), expected_status=200)
    assert expired["status"] == "PENDING", \
        f"expire before TTL must leave PENDING, got {expired['status']}"


# ===========================================================================
# Corner: errors
# ===========================================================================
def test_reactivate_active_config_rejected():
    """PRD §3.2: "Activation is rejected with ERR_PRICING_CONFIG_ALREADY_ACTIVE if
    the target config is not in DRAFT (that is, it is already ACTIVE or RETIRED)."

    Design: Corner/errors/error_pricing_config_already_active_on_reactivate
    """
    cfg = create_active_pricing_config()
    resp = api.activate_pricing_config(cfg["id"], PA)
    validate_error(resp, ApiErrorId.ERR_PRICING_CONFIG_ALREADY_ACTIVE.value)


def test_acknowledge_waiting_reminder_rejected():
    """PRD §3.9: "Forcing a reminder due before next_reminder_at has been reached,
    or acknowledging a reminder that is not DUE, is rejected with
    ERR_REMINDER_NOT_DUE"

    Design: Corner/errors/error_reminder_not_due_on_acknowledge_waiting
    """
    home, systems, plan = create_home_with_active_plan(cadence_months=12, num_systems=1,
                                                      register_count=5, zone_code="Z1")
    assert plan["reminder_status"] == "WAITING"
    resp = api.acknowledge_reminder(plan["id"], PA)
    validate_error(resp, ApiErrorId.ERR_REMINDER_NOT_DUE.value)


# ===========================================================================
# Corner: scheduled_actions (referral expiry past TTL)
# ===========================================================================
def test_referral_expires_after_ttl_clock_advance():
    """PRD §3.10: "a referral may be expired only once the logical clock has
    reached or passed thirty days after its created_at — the referral lifetime is
    thirty days."

    Design: Corner/cross_cutting_complexity_layers/scheduled_referral_expires_after_ttl_clock_advance
    """
    create_active_pricing_config()
    home, systems = create_home_with_systems(1, register_count=5, zone_code="Z1")
    crew = create_crew(home_zone_code="Z1")
    wo, route = create_completed_work_order(
        home["id"], [duct_line(systems[0]["id"])], crew["id"],
        inspect_overrides={"before_photo_count": 1, "dust_severity": 6},
        complete_overrides={"after_photo_count": 2, "dust_severity": 6,
                            "recommend_hvac_repair": True},
        service_date="2026-05-01")
    referrals, _ = validate_paginated(
        api.list_upsell_referrals(PA, params={"work_order_id": wo["id"]}))
    ref = referrals[0]
    # PRD §2.9/§3.10: advancing the clock past created_at + 30 days automatically
    # expires the PENDING referral ("Expiry happens automatically whenever the
    # clock is advanced past that point").
    set_clock("2026-12-01T00:00:00Z")  # well past created_at + 30 days
    expired = validate_success(api.get_upsell_referral(ref["id"], PA), expected_status=200)
    assert expired["status"] == "EXPIRED", \
        f"clock advance past TTL must set EXPIRED, got {expired['status']}"


# ===========================================================================
# Corner: rbac
# ===========================================================================
def test_technician_cannot_create_route():
    """PRD §2.1: "When the headers are valid but the role is not permitted to
    perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/rbac_technician_cannot_create_route
    """
    from test_helpers import make_technician_headers
    crew = create_crew(home_zone_code="Z1")
    resp = api.create_route_plan(
        {"crew_member_id": crew["id"], "zone_code": "Z1", "service_date": "2026-04-29",
         "shift_start_minute": 480, "shift_end_minute": 1020},
        make_technician_headers(crew["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_dispatcher_cannot_activate_pricing_config():
    """PRD §2.1: "When the headers are valid but the role is not permitted to
    perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/rbac_dispatcher_cannot_activate_pricing_config
    """
    cfg = create_draft_pricing_config()
    resp = api.activate_pricing_config(cfg["id"], DI)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_missing_headers_returns_unauthenticated():
    """PRD §2.1: "If either header is missing, or X-User-Role is not one of the
    recognized roles, the request is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT (HTTP 401)."

    Design: Corner/rbac/rbac_missing_headers_returns_unauthenticated
    """
    resp = api.create_pricing_config(
        {"duct_base_cents": 12000, "duct_per_system_cents": 4000,
         "dryer_vent_flat_cents": 9000, "sanitize_per_system_cents": 5000,
         "addon_sanitizer_cents": 3000, "addon_uv_cents": 7000, "addon_coil_cents": 2500,
         "multi_system_discount_pct": 0.10, "plan_member_discount_pct": 0.15,
         "tax_pct": 0.08},
        {"Content-Type": "application/json"})  # no auth headers
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT.value)
