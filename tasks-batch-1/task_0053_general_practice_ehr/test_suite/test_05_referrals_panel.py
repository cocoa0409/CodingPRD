"""Referral authorization, panel capacity, and optimistic concurrency on panel
binding.
"""
from datetime import datetime, timezone

import pytest
from test_helpers import (
    validate_success, validate_error,
    make_provider_headers,
    TEST_USERS,
    set_clock,
    create_provider,
    create_patient,
    create_pcp_bound_patient,
    create_referral,
    create_authorized_referral,
    bind_patient,
)

FD = TEST_USERS["frontdesk_headers"]


# ─── Queue A: cross_entity_state_dependency / referral_authorize_requires_patient_pcp_bound ───

def test_authorize_referral_without_pcp_rejected(api):
    """PRD §3.8: "Authorizing advances the referral from `REQUESTED` to `AUTHORIZED`,
    but only when the referred patient has a bound PCP — when the patient's `pcp_id` is
    non-null. An attempt to authorize a referral for a patient with no bound PCP is
    rejected with `ERR_NO_PCP_BOUND`."

    Design: Difficulty/cross_entity_state_dependency/referral_authorize_requires_patient_pcp_bound
    """
    provider = create_provider()
    patient = create_patient(sex="F")  # never bound to a PCP
    referral = create_referral(patient["id"], provider["id"],
                               target_specialty="CARDIOLOGY", priority="ROUTINE")
    res = api.authorize_referral(referral["id"], FD)
    validate_error(res, "ERR_NO_PCP_BOUND")


def test_authorize_referral_without_pcp_leaves_state_requested(api):
    """PRD §3.8: "A new referral begins in `REQUESTED` status with a null
    `authorization_expires_at`."

    Design: Difficulty/cross_entity_state_dependency/referral_authorize_requires_patient_pcp_bound
    """
    provider = create_provider()
    patient = create_patient(sex="F")
    referral = create_referral(patient["id"], provider["id"],
                               target_specialty="CARDIOLOGY", priority="ROUTINE")
    api.authorize_referral(referral["id"], FD)
    after = validate_success(api.get_referral(referral["id"], FD), 200)
    assert after["status"] == "REQUESTED", (
        f"a rejected authorize must leave the referral in REQUESTED, got {after['status']}"
    )


# ─── Queue A: boundary_precision_check / panel_at_capacity_ge_boundary ───

def test_first_bind_below_capacity_succeeds(api):
    """PRD §3.1: "Capacity is a hard ceiling: if completing the bind would make the
    provider's `panel_size` reach or exceed `panel_capacity`, the bind is rejected with
    `ERR_PANEL_AT_CAPACITY`."

    With panel_capacity=2, completing the first bind makes panel_size reach 1, which is
    strictly below the ceiling (1 < 2), so the bind is permitted.

    Design: Difficulty/boundary_precision_check/panel_at_capacity_ge_boundary
    """
    provider = create_provider(panel_capacity=2)
    patient1 = create_patient()
    bound = validate_success(
        api.bind_panel(provider["id"],
                       {"patient_id": patient1["id"], "expected_provider_version": provider["version"]},
                       FD),
        200,
    )
    assert bound["panel_size"] == 1, (
        f"binding the first patient below capacity must succeed (panel_size 1), got {bound['panel_size']}"
    )


def test_bind_reaching_capacity_rejected(api):
    """PRD §3.1: "Capacity is a hard ceiling: if completing the bind would make the
    provider's `panel_size` reach or exceed `panel_capacity`, the bind is rejected with
    `ERR_PANEL_AT_CAPACITY`."

    With panel_capacity=2, completing the second bind would make panel_size reach 2,
    which reaches the ceiling (2 >= 2), so the bind is rejected.

    Design: Difficulty/boundary_precision_check/panel_at_capacity_ge_boundary
    """
    provider = create_provider(panel_capacity=2)
    patient1 = create_patient()
    patient2 = create_patient(sex="F")
    bound = validate_success(
        api.bind_panel(provider["id"],
                       {"patient_id": patient1["id"], "expected_provider_version": provider["version"]},
                       FD),
        200,
    )
    res = api.bind_panel(
        provider["id"],
        {"patient_id": patient2["id"], "expected_provider_version": bound["version"]},
        FD,
    )
    validate_error(res, "ERR_PANEL_AT_CAPACITY")


# ─── Queue B: cross_cutting / panel_bind_stale_provider_version ───

def test_panel_bind_stale_version_rejected(api):
    """PRD §2.8: "Before the bind proceeds, the system compares
    `expected_provider_version` against the provider's current `version`. If they do not
    match — because another writer has advanced the provider's `version` since the client
    read it, for example by binding a different patient and consuming an open panel slot
    — the bind is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/panel_bind_stale_provider_version
    """
    provider = create_provider(panel_capacity=5)
    patient1 = create_patient()
    patient2 = create_patient(sex="F")
    stale_version = provider["version"]
    # First bind advances the provider's version.
    validate_success(
        api.bind_panel(provider["id"],
                       {"patient_id": patient1["id"], "expected_provider_version": stale_version},
                       FD),
        200,
    )
    # Second bind carries the now-stale expected version.
    res = api.bind_panel(
        provider["id"],
        {"patient_id": patient2["id"], "expected_provider_version": stale_version},
        FD,
    )
    validate_error(res, "ERR_STALE_VERSION")


# ─── Queue B: cross_cutting / panel_bind_correct_version_succeeds_and_increments ───

def test_panel_bind_correct_version_increments_provider_version(api):
    """PRD §3.1: "When binding is permitted, the provider's `version` increments by 1."

    Design: Corner/cross_cutting/panel_bind_correct_version_succeeds_and_increments
    """
    provider = create_provider(panel_capacity=5)
    patient1 = create_patient()
    start_version = provider["version"]
    bound = validate_success(
        api.bind_panel(provider["id"],
                       {"patient_id": patient1["id"], "expected_provider_version": start_version},
                       FD),
        200,
    )
    assert bound["panel_size"] == 1
    assert bound["version"] == start_version + 1, (
        f"a successful bind must increment version by exactly 1 (from {start_version}), "
        f"got {bound['version']}"
    )


# ─── Queue B: state_machines / referral_authorize_idempotency_second_call_rejected ───

def test_authorize_already_authorized_referral_rejected(api):
    """PRD §3.8: "Authorizing advances the referral from `REQUESTED` to `AUTHORIZED`,
    but only when the referred patient has a bound PCP — when the patient's `pcp_id` is
    non-null."

    Design: Corner/state_machines/referral_authorize_idempotency_second_call_rejected
    """
    provider, patient, referral = create_authorized_referral(priority="ROUTINE",
                                                             referral_overrides={"target_specialty": "DERMATOLOGY"})
    assert referral["status"] == "AUTHORIZED"
    res = api.authorize_referral(referral["id"], FD)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Queue B: state_machines / referral_schedule_after_window_expired ───

def test_schedule_referral_after_expiry_rejected(api):
    """PRD §3.8: "Scheduling advances it from `AUTHORIZED` to `SCHEDULED` and is
    permitted only while the current clock is strictly before `authorization_expires_at`;
    an attempt to schedule once the clock has reached or passed the expiry instant is
    rejected with `ERR_REFERRAL_EXPIRED`."

    Design: Corner/state_machines/referral_schedule_after_window_expired
    """
    set_clock("2026-06-01T00:00:00Z")
    provider, patient = create_pcp_bound_patient()
    referral = create_referral(patient["id"], provider["id"],
                               target_specialty="ORTHOPEDICS", priority="ROUTINE")
    validate_success(api.authorize_referral(referral["id"], FD), 200)
    # ROUTINE window is 90 days -> expiry 2026-08-30; advance past it.
    set_clock("2026-09-01T00:00:00Z")
    res = api.schedule_referral(referral["id"], FD)
    validate_error(res, "ERR_REFERRAL_EXPIRED")


# ─── Queue B: calculations / referral_auth_window_urgent_vs_routine ───

def test_urgent_referral_authorization_window_is_14_days(api):
    """PRD §3.8: "On authorization, the system sets `authorization_expires_at` to the
    authorizing clock instant plus a whole number of days: 90 days for a `ROUTINE`
    referral and 14 days for an `URGENT` one."

    Design: Corner/calculations/referral_auth_window_urgent_vs_routine
    """
    set_clock("2026-06-01T00:00:00Z")
    provider, patient = create_pcp_bound_patient()
    referral = create_referral(patient["id"], provider["id"],
                               target_specialty="ENDOCRINOLOGY", priority="URGENT")
    authorized = validate_success(api.authorize_referral(referral["id"], FD), 200)
    # 2026-06-01T00:00:00Z + 14 whole days = 2026-06-15T00:00:00Z. Compare the
    # instant rather than the raw string so an equivalent fractional-second
    # serialization (e.g. ...00.000Z) is not spuriously rejected.
    expires = authorized["authorization_expires_at"]
    parsed = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    expected = datetime(2026, 6, 15, 0, 0, 0, tzinfo=timezone.utc)
    assert parsed == expected, (
        f"URGENT window of 14 days from 2026-06-01 must expire at 2026-06-15T00:00:00Z, "
        f"got {expires}"
    )
