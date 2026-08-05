"""Cross-entity state dependencies (confirm<-tenant, payout<-booking),
optimistic-concurrency guards, payout segregation of duties, and pagination.

Queue A (Difficulty): cross_entity_state_dependency.
Queue B (Corner): cross_cutting_concerns.
"""
from test_helpers import (
    validate_error, validate_paginated, get_success_data, ApiErrorId,
    register_host, register_tenant, register_tenant_with_pending_verification,
    create_unit, request_booking, confirm_booking,
    setup_active_booking, setup_completed_booking,
    get_deposit_for_booking, get_payout_for_booking,
    make_host_headers, make_tenant_headers, make_admin_headers, TEST_USERS,
)

REVIEWER = TEST_USERS["compliance_reviewer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# --------------------------------------------------------------------------
# cross_entity_state_dependency / confirm_requires_tenant_verified
# --------------------------------------------------------------------------

def test_confirm_pending_tenant_rejected(api):
    """PRD §3.4: "The tenant's `verification_status` must be `VERIFIED` (otherwise
    `ERR_TENANT_NOT_VERIFIED`)."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_tenant_verified
    """
    host = register_host(api, verify_payout=True)
    tenant, ver = register_tenant_with_pending_verification(api)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True, deposit_cents=0)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    resp = api.transition_booking(booking["id"], {"to_status": "CONFIRMED"}, make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_TENANT_NOT_VERIFIED)


def test_confirm_succeeds_after_verification_approved(api):
    """PRD §3.1: "if at least one of the tenant's verifications is `APPROVED`, the
    tenant is `VERIFIED`".
    PRD §3.4: "The tenant's `verification_status` must be `VERIFIED` (otherwise
    `ERR_TENANT_NOT_VERIFIED`)."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_tenant_verified
    """
    host = register_host(api, verify_payout=True)
    tenant, ver = register_tenant_with_pending_verification(api)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True, deposit_cents=0)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    get_success_data(api.transition_verification(ver["id"], {"to_status": "APPROVED"}, REVIEWER))
    confirmed = get_success_data(api.transition_booking(
        booking["id"], {"to_status": "CONFIRMED"}, make_host_headers(host["id"])))
    assert confirmed["status"] == "CONFIRMED", f"confirm must succeed once verified, got {confirmed['status']}"


# --------------------------------------------------------------------------
# cross_entity_state_dependency / payout_schedule_requires_booking_completed
# --------------------------------------------------------------------------

def test_schedule_payout_while_booking_active_rejected(api):
    """PRD §3.9: "an operator schedules the payout, moving `PENDING` to
    `SCHEDULED`; this is permitted only when the booking is `COMPLETED` (otherwise
    `ERR_BOOKING_NOT_COMPLETED`)".

    Design: Difficulty/cross_entity_state_dependency/payout_schedule_requires_booking_completed
    """
    ctx = setup_active_booking(api, unit_overrides={"deposit_cents": 0},
                               start_date="2026-06-01", end_date="2026-07-01",
                               activate_clock="2026-06-15")
    payout = get_payout_for_booking(api, ctx["booking"]["id"])
    resp = api.transition_payout(payout["id"], {"to_status": "SCHEDULED"}, make_admin_headers("admin-1"))
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_COMPLETED)


def test_schedule_payout_after_completion_succeeds(api):
    """PRD §3.9: "First an operator schedules the payout, moving `PENDING` to
    `SCHEDULED`; this is permitted only when the booking is `COMPLETED` (otherwise
    `ERR_BOOKING_NOT_COMPLETED`) and the host's `payout_account_status` is
    `VERIFIED` (otherwise `ERR_HOST_PAYOUT_NOT_VERIFIED`), and it records the
    scheduling operator's `X-User-ID` into `scheduled_by_user_id`."

    Design: Difficulty/cross_entity_state_dependency/payout_schedule_requires_booking_completed
    """
    ctx = setup_completed_booking(api, unit_overrides={"deposit_cents": 0},
                                  start_date="2026-06-01", end_date="2026-07-01",
                                  activate_clock="2026-06-15", complete_clock="2026-07-01")
    payout = get_payout_for_booking(api, ctx["booking"]["id"])
    scheduled = get_success_data(api.transition_payout(
        payout["id"], {"to_status": "SCHEDULED"}, make_admin_headers("admin-1")))
    assert scheduled["status"] == "SCHEDULED", f"schedule must succeed once completed, got {scheduled['status']}"


# --------------------------------------------------------------------------
# cross_cutting_concerns / optimistic concurrency + SoD + pagination
# --------------------------------------------------------------------------

def test_stale_booking_version_second_extension_rejected(api):
    """PRD §2.6: "When the check passes, the newly created extension itself
    advances the booking's `version` by one, so a second extension request
    carrying the same observed version is stale."

    Design: Corner/cross_cutting_concerns/stale_booking_version_extension_conflict
    """
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True, deposit_cents=0)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    confirmed = confirm_booking(api, booking["id"], host["id"])
    v = confirmed["version"]
    get_success_data(api.create_extension(
        {"booking_id": booking["id"], "expected_booking_version": v, "new_end_date": "2026-07-16"},
        make_tenant_headers(tenant["id"])))
    resp = api.create_extension(
        {"booking_id": booking["id"], "expected_booking_version": v, "new_end_date": "2026-07-20"},
        make_tenant_headers(tenant["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_BOOKING_VERSION)


def test_stale_deposit_version_second_claim_rejected(api):
    """PRD §2.6: "if another claim already filed against the same deposit (which
    the platform permits to coexist) has advanced the deposit's version, the values
    differ and the create is rejected with `ERR_STALE_DEPOSIT_VERSION` (HTTP 412).
    A successful filing advances the deposit's `version` by one."

    Design: Corner/cross_cutting_concerns/stale_deposit_version_claim_conflict
    """
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True, deposit_cents=150000)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    confirm_booking(api, booking["id"], host["id"])
    deposit = get_deposit_for_booking(api, booking["id"])
    v = deposit["version"]
    get_success_data(api.create_damage_claim(
        {"deposit_id": deposit["id"], "expected_deposit_version": v, "claimed_cents": 20000, "description": "claim A"},
        make_host_headers(host["id"])))
    resp = api.create_damage_claim(
        {"deposit_id": deposit["id"], "expected_deposit_version": v, "claimed_cents": 30000, "description": "claim B"},
        make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_DEPOSIT_VERSION)


def test_payout_pay_by_scheduler_segregation_of_duties(api):
    """PRD §3.9: "the acting `X-User-ID` must differ from the `scheduled_by_user_id`
    that was recorded at scheduling, else the release is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/cross_cutting_concerns/payout_pay_same_user_segregation_of_duties
    """
    ctx = setup_completed_booking(api, unit_overrides={"deposit_cents": 0},
                                  start_date="2026-06-01", end_date="2026-07-01",
                                  activate_clock="2026-06-15", complete_clock="2026-07-01")
    payout = get_payout_for_booking(api, ctx["booking"]["id"])
    get_success_data(api.transition_payout(payout["id"], {"to_status": "SCHEDULED"}, make_admin_headers("admin-1")))
    resp = api.transition_payout(payout["id"], {"to_status": "PAID"}, make_admin_headers("admin-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_units_list_pagination_envelope(api):
    """PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/cross_cutting_concerns/units_list_pagination_envelope
    """
    host = register_host(api, verify_payout=False)
    create_unit(api, host["id"], listed=False, title="CY1", address="22 A St")
    create_unit(api, host["id"], listed=False, title="CY2", address="23 A St")
    resp = api.list_units(ADMIN, params={"host_id": host["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
    assert meta["has_more"] is False, f"has_more must be False at default limit, got {meta['has_more']}"
    assert len(data) == 2, f"array length must be 2, got {len(data)}"
