"""Scheduling/approval guard battery: validation precedence pairs, the standing-order
cross-entity dependency, supply/consent/credit/screening checks, segregation of duties,
OCC stale version, and standing-order idempotency.
"""
import pytest
from test_helpers import (
    get_success_data, validate_error, validate_success,
    set_clock, create_menu_item, create_lounge, create_patient, create_membership,
    create_supply_lot, create_draft_standing_order, create_active_standing_order,
    create_requested_appointment, submit_intake, sign_consent, current_version,
    schedule_appointment, setup_screen_pending_appointment,
    setup_cleared_lounge_ready_to_schedule,
    TEST_USERS, make_medical_director_headers,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["clinic_admin_headers"]
FAR_EXPIRY = "2026-12-31T00:00:00Z"


# ─── Difficulty: priority_pair_validation_conflict / pri_state_beats_consent_missing ───
def test_schedule_requested_unconsented_reports_invalid_state(api):
    """PRD §2.6: "whether the target resource is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`). Only after all of those pass does the
    system evaluate the optimistic-concurrency check ... and only after that does it
    evaluate the domain-specific business rules."
    PRD §3.7: "Scheduling is only defined from `SCREEN_PENDING`."

    A REQUESTED (never-screened, never-consented) appointment scheduled returns the
    state error, which outranks the consent-missing business check.

    Design: Difficulty/priority_pair_validation_conflict/pri_state_beats_consent_missing
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", base_price_cents=17500, requires_standing_order=False)
    lounge = create_lounge(bay_count=2)
    patient = create_patient()
    appt = create_requested_appointment(patient["id"], myers["id"], lounge_id=lounge["id"],
                                        start_at="2026-06-23T09:00:00Z")
    v = current_version(appt["id"])
    res = api_client.schedule_appointment(appt["id"], {"expected_appointment_version": v}, ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_schedule_screen_pending_without_consent_reports_consent_missing(api):
    """PRD §3.7: "A `SIGNED` consent must exist for the appointment, or the request is
    rejected with `ERR_CONSENT_MISSING` (HTTP 409)." From SCREEN_PENDING (a defined
    transition state) with no consent, the consent business check fires — the X+1 side of
    the state-vs-consent pair, confirming the consent rule on its own.

    Design: Difficulty/priority_pair_validation_conflict/pri_state_beats_consent_missing
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", base_price_cents=17500, requires_standing_order=False)
    lounge = create_lounge(bay_count=2)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="MY-1",
                      units_total=5, expires_at=FAR_EXPIRY)
    patient = create_patient()
    appt = create_requested_appointment(patient["id"], myers["id"], lounge_id=lounge["id"],
                                        start_at="2026-06-23T09:00:00Z")
    submit_intake(appt["id"])  # -> SCREEN_PENDING, CLEARED, no consent
    v = current_version(appt["id"])
    res = api_client.schedule_appointment(appt["id"], {"expected_appointment_version": v}, ADMIN)
    validate_error(res, "ERR_CONSENT_MISSING", expected_status=409)


# ─── Difficulty: priority_pair_validation_conflict / pri_screening_blocked_beats_credit_insufficient ───
def test_blocked_screening_outranks_credit_insufficient(api):
    """PRD §2.6: "the screening-not-blocked safety check (`ERR_SCREENING_BLOCKED`) is
    evaluated before the signed-consent check ... which is evaluated before ... the
    membership-credit check (`ERR_CREDIT_INSUFFICIENT`)."
    PRD §3.7: "If the latest `SUBMITTED` screening's `outcome` is `BLOCKED`, the request is
    rejected with `ERR_SCREENING_BLOCKED` (HTTP 409)".

    A BLOCKED screening (pregnancy 40 + recent_adverse 20 = 60) plus a credit-short
    PLATINUM membership: the screening-blocked error wins.

    Design: Difficulty/priority_pair_validation_conflict/pri_screening_blocked_beats_credit_insufficient
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", base_price_cents=17500,
                             requires_standing_order=False, g6pd_sensitive=False)
    lounge = create_lounge(bay_count=2)
    mem = create_membership(tier="PLATINUM", covered_drip_tier="MYERS",
                            drip_credits_total=0, addon_credits_total=0)
    patient = create_patient(membership_id=mem["id"])
    appt = create_requested_appointment(patient["id"], myers["id"], lounge_id=lounge["id"],
                                        start_at="2026-06-23T09:00:00Z", membership_id=mem["id"])
    submit_intake(appt["id"], author_user_id="intake-1", pregnancy=True, recent_adverse_event=True)
    sign_consent(appt["id"], witness_user_id="wit-1")
    v = current_version(appt["id"])
    res = api_client.schedule_appointment(appt["id"], {"expected_appointment_version": v}, ADMIN)
    validate_error(res, "ERR_SCREENING_BLOCKED", expected_status=409)


def test_screening_blocked_rejected_in_isolation(api):
    """PRD §3.7: "If the latest `SUBMITTED` screening's `outcome` is `BLOCKED`, the request
    is rejected with `ERR_SCREENING_BLOCKED` (HTTP 409) — a blocked screening can never be
    scheduled or approved."

    Isolated BLOCKED screening (pregnancy 40 + recent_adverse 20 = 60), cash visit with
    consent and supply present, so only the screening-blocked fault remains.

    Design: Difficulty/priority_pair_validation_conflict/pri_screening_blocked_beats_credit_insufficient
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", base_price_cents=17500, requires_standing_order=False)
    lounge = create_lounge(bay_count=2)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="MY-1",
                      units_total=5, expires_at=FAR_EXPIRY)
    patient = create_patient()
    appt = create_requested_appointment(patient["id"], myers["id"], lounge_id=lounge["id"],
                                        start_at="2026-06-23T09:00:00Z")
    submit_intake(appt["id"], author_user_id="intake-1", pregnancy=True, recent_adverse_event=True)
    sign_consent(appt["id"], witness_user_id="wit-1")
    v = current_version(appt["id"])
    res = api_client.schedule_appointment(appt["id"], {"expected_appointment_version": v}, ADMIN)
    validate_error(res, "ERR_SCREENING_BLOCKED", expected_status=409)


# ─── Difficulty: cross_entity_state_dependency / cross_schedule_requires_active_standing_order ───
def test_schedule_blocked_when_standing_order_still_draft(api):
    """PRD §3.7: "If the menu item's `requires_standing_order` is true, there must exist
    an `ACTIVE` standing order covering the menu item's tier and in force at `start_at` ...
    otherwise the request is rejected with `ERR_NO_STANDING_ORDER` (HTTP 409)."

    A NAD drip (requires_standing_order=true) with its only NAD order left DRAFT: scheduling
    fails on the standing-order check and the appointment stays SCREEN_PENDING.

    Design: Difficulty/cross_entity_state_dependency/cross_schedule_requires_active_standing_order
    """
    set_clock("2026-06-22T00:00:00Z")
    nad = create_menu_item(tier="NAD", base_price_cents=65000, requires_standing_order=True)
    lounge = create_lounge(bay_count=2)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="NAD", lot_number="NAD-1",
                      units_total=5, expires_at=FAR_EXPIRY)
    create_draft_standing_order(covered_tier="NAD", md_user_id="md-1")
    patient = create_patient()
    appt = create_requested_appointment(patient["id"], nad["id"], lounge_id=lounge["id"],
                                        start_at="2026-06-23T09:00:00Z")
    submit_intake(appt["id"])
    sign_consent(appt["id"])
    v = current_version(appt["id"])
    res = api_client.schedule_appointment(appt["id"], {"expected_appointment_version": v}, ADMIN)
    validate_error(res, "ERR_NO_STANDING_ORDER", expected_status=409)
    appt_after = get_success_data(api_client.get_appointment(appt["id"], ADMIN))
    assert appt_after["status"] == "SCREEN_PENDING"


def test_schedule_succeeds_once_standing_order_active(api):
    """PRD §3.7: with an ACTIVE standing order covering the tier and in force at start_at,
    "scheduling drives the appointment from `SCREEN_PENDING` to `SCHEDULED`" and "The
    chosen order's identifier is pinned onto the appointment's `standing_order_id`."

    The X+1 partner of the DRAFT-blocks test: activating the same NAD order lets scheduling
    succeed.

    Design: Difficulty/cross_entity_state_dependency/cross_schedule_requires_active_standing_order
    """
    set_clock("2026-06-22T00:00:00Z")
    nad = create_menu_item(tier="NAD", base_price_cents=65000, requires_standing_order=True)
    lounge = create_lounge(bay_count=2)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="NAD", lot_number="NAD-1",
                      units_total=5, expires_at=FAR_EXPIRY)
    order = create_active_standing_order(covered_tier="NAD", md_user_id="md-1")
    patient = create_patient()
    appt = create_requested_appointment(patient["id"], nad["id"], lounge_id=lounge["id"],
                                        start_at="2026-06-23T09:00:00Z")
    submit_intake(appt["id"])
    sign_consent(appt["id"])
    scheduled = schedule_appointment(appt["id"])
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["standing_order_id"] == order["id"], \
        "the chosen ACTIVE order id must be pinned onto standing_order_id"


# ─── Corner: validations / schedule_supply_unavailable ───
def test_schedule_with_no_supply_reports_supply_unavailable(api):
    """PRD §3.10: "If no candidate exists for any required line, the operation is rejected
    with `ERR_SUPPLY_UNAVAILABLE`." A CLEARED+consented MYERS appointment with no MYERS
    lot fails and stays SCREEN_PENDING.

    Design: Corner/validations/schedule_supply_unavailable
    """
    ctx = setup_screen_pending_appointment(
        menu_overrides={"tier": "MYERS", "base_price_cents": 17500,
                        "requires_standing_order": False})
    v = current_version(ctx["appointment"]["id"])
    res = api_client.schedule_appointment(ctx["appointment"]["id"],
                                          {"expected_appointment_version": v}, ADMIN)
    validate_error(res, "ERR_SUPPLY_UNAVAILABLE", expected_status=409)
    appt_after = get_success_data(api_client.get_appointment(ctx["appointment"]["id"], ADMIN))
    assert appt_after["status"] == "SCREEN_PENDING"


# ─── Corner: validations / schedule_expired_lot_not_usable ───
def test_schedule_with_only_expired_lot_reports_supply_unavailable(api):
    """PRD §2.9: "A lot is unusable for any slot whose `start_at` is at or after the lot's
    `expires_at`; the in-force window is half-open, so a lot remains usable exactly while
    the slot's `start_at` is strictly before `expires_at`." With the only MYERS lot expiring
    at 2026-06-23T00:00 and start_at 09:00 that day, no candidate exists.

    Design: Corner/validations/schedule_expired_lot_not_usable
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", base_price_cents=17500, requires_standing_order=False)
    lounge = create_lounge(bay_count=2)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="MY-EXP",
                      units_total=5, expires_at="2026-06-23T00:00:00Z")
    patient = create_patient()
    appt = create_requested_appointment(patient["id"], myers["id"], lounge_id=lounge["id"],
                                        start_at="2026-06-23T09:00:00Z")
    submit_intake(appt["id"])
    sign_consent(appt["id"])
    v = current_version(appt["id"])
    res = api_client.schedule_appointment(appt["id"], {"expected_appointment_version": v}, ADMIN)
    validate_error(res, "ERR_SUPPLY_UNAVAILABLE", expected_status=409)


# ─── Corner: errors / error_consent_missing_triggered ───
def test_error_consent_missing_triggered(api):
    """PRD §3.7: "A `SIGNED` consent must exist for the appointment, or the request is
    rejected with `ERR_CONSENT_MISSING` (HTTP 409)." Scheduling a CLEARED MYERS appointment
    with supply present but no consent fails on the consent check.

    Design: Corner/errors/error_consent_missing_triggered
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", base_price_cents=17500, requires_standing_order=False)
    lounge = create_lounge(bay_count=2)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="MY-1",
                      units_total=5, expires_at=FAR_EXPIRY)
    patient = create_patient()
    appt = create_requested_appointment(patient["id"], myers["id"], lounge_id=lounge["id"],
                                        start_at="2026-06-23T09:00:00Z")
    submit_intake(appt["id"])
    v = current_version(appt["id"])
    res = api_client.schedule_appointment(appt["id"], {"expected_appointment_version": v}, ADMIN)
    validate_error(res, "ERR_CONSENT_MISSING", expected_status=409)


# ─── Corner: validations / consent_witness_equals_author_segregation ───
def test_consent_witness_equals_screening_author_rejected(api):
    """PRD §3.6: "the `witness_user_id` recorded for an appointment must differ from the
    `author_user_id` of that appointment's screening; if they collide, the consent is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

    Design: Corner/validations/consent_witness_equals_author_segregation
    """
    ctx = setup_screen_pending_appointment(
        menu_overrides={"tier": "MYERS", "requires_standing_order": False},
        author_user_id="intake-1", with_consent=False)
    res = api_client.create_consent(
        {"appointment_id": ctx["appointment"]["id"], "signed_by_patient": True,
         "witness_user_id": "intake-1"}, ADMIN)
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=409)


# ─── Corner: validations / consent_not_affirmed_rejected ───
def test_consent_not_affirmed_rejected(api):
    """PRD §3.6: "a `signed_by_patient` boolean that must be true (a consent submitted with
    `signed_by_patient` not equal to true is rejected with `ERR_CONSENT_NOT_AFFIRMED`,
    HTTP 422)".

    Design: Corner/validations/consent_not_affirmed_rejected
    """
    ctx = setup_screen_pending_appointment(
        menu_overrides={"tier": "MYERS", "requires_standing_order": False},
        with_consent=False)
    res = api_client.create_consent(
        {"appointment_id": ctx["appointment"]["id"], "signed_by_patient": False,
         "witness_user_id": "wit-1"}, ADMIN)
    validate_error(res, "ERR_CONSENT_NOT_AFFIRMED", expected_status=422)


# ─── Corner: cross_cutting / occ_schedule_stale_version_conflict ───
def test_schedule_with_stale_version_rejected(api):
    """PRD §2.5: "If a prior write — for example a re-submitted intake that superseded the
    screening, or a cancellation — has advanced the appointment's `version` since the client
    last read it, the scheduling request is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Capture the version after one intake, re-submit intake to bump the version, then schedule
    with the stale value.

    Design: Corner/cross_cutting_complexity_layers/occ_schedule_stale_version_conflict
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", base_price_cents=17500, requires_standing_order=False)
    lounge = create_lounge(bay_count=2)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="MY-1",
                      units_total=5, expires_at=FAR_EXPIRY)
    patient = create_patient()
    appt = create_requested_appointment(patient["id"], myers["id"], lounge_id=lounge["id"],
                                        start_at="2026-06-23T09:00:00Z")
    submit_intake(appt["id"])
    stale_v = current_version(appt["id"])
    sign_consent(appt["id"])
    submit_intake(appt["id"])  # supersedes prior screening, bumps version
    res = api_client.schedule_appointment(appt["id"],
                                          {"expected_appointment_version": stale_v}, ADMIN)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


# ─── Corner: state_machines / activate_already_active_standing_order_invalid_state ───
def test_activate_already_active_standing_order_invalid_state(api):
    """PRD §3.3: "Attempting a transition that is not defined from the order's current
    state — for instance activating an order that is not `DRAFT` — is rejected with
    `ERR_INVALID_STATE`." Activating an already-ACTIVE order a second time fails.

    Design: Corner/state_machines/activate_already_active_standing_order_invalid_state
    """
    set_clock("2026-06-22T00:00:00Z")
    md = make_medical_director_headers("md-1")
    order = get_success_data(api_client.create_standing_order(
        {"medical_director_user_id": "md-1", "covered_tier": "NAD",
         "effective_from": "2026-06-01T00:00:00Z", "expires_at": FAR_EXPIRY}, md))
    get_success_data(api_client.activate_standing_order(order["id"], md))
    res = api_client.activate_standing_order(order["id"], md)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
