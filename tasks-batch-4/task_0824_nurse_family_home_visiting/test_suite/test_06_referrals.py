"""Benefit referrals: the contact/reopen re-attempt loop, the connect precondition,
the connected_at stamp, and the consent gate on referral creation."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_referral_payload,
    create_nurse,
    create_client,
    create_prospect_enrollment,
    make_nurse_headers,
    set_clock,
    setup_active_enrollment,
    open_referral,
    api_client,
    get_success_data,
)


# ─── Difficulty: contact/reopen re-attempt loop ─────────
def _referral_reattempt_cycle():
    """Open referral, contact, reopen, contact again. Returns the final referral."""
    ctx = setup_active_enrollment()
    ref = open_referral(ctx, benefit_type="WIC")
    get_success_data(api_client.contact_referral(ref["id"], ctx.nurse_headers))
    get_success_data(api_client.reopen_referral(ref["id"], ctx.nurse_headers))
    return get_success_data(api_client.contact_referral(ref["id"], ctx.nurse_headers))


def test_referral_reattempt_loop_returns_to_contacted(api):
    """PRD 3.8: "Reopening moves a CONTACTED referral back to OPEN for another attempt;
    the next contact from that reopened state increments attempts again, forming a
    re-attempt loop."

    Design: Difficulty/non_linear_state_machine/referral_reattempt_cycle_contacted_to_open_to_contacted
    """
    final = _referral_reattempt_cycle()
    assert final["status"] == "CONTACTED"


def test_referral_reattempt_loop_counts_two_attempts(api):
    """PRD 3.8: "Contacting the benefit provider advances the referral from `OPEN` to `CONTACTED` and increments `attempts` by 1."
    PRD 3.8: "the next contact from that reopened state increments attempts again,
    forming a re-attempt loop."

    Design: Difficulty/non_linear_state_machine/referral_reattempt_cycle_contacted_to_open_to_contacted
    """
    final = _referral_reattempt_cycle()
    assert final["attempts"] == 2


# ─── Corner: connect requires CONTACTED ─────────────────
def test_connect_from_open_is_invalid_state(api):
    """PRD 3.8: "From CONTACTED, connecting the family advances the referral to
    CONNECTED and stamps connected_at with the current logical-clock time."
    PRD 3.8: "Any of these transitions attempted from a status where it is not defined
    yields ERR_INVALID_STATE."

    Design: Corner/state_machines/referral_connect_from_open_is_invalid_state
    """
    ctx = setup_active_enrollment()
    ref = open_referral(ctx, benefit_type="MEDICAID")
    res = api.connect_referral(ref["id"], ctx.nurse_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─── Corner: connect stamps connected_at ────────────────
def test_connect_stamps_connected_at_with_clock(api):
    """PRD 3.8: "From `CONTACTED`, connecting the family advances the referral to `CONNECTED` and stamps `connected_at` with the current logical-clock time."

    Design: Corner/state_machines/referral_connect_stamps_connected_at
    """
    ctx = setup_active_enrollment()
    set_clock("2026-06-01T00:00:00Z")
    ref = open_referral(ctx, benefit_type="HOUSING")
    get_success_data(api_client.contact_referral(ref["id"], ctx.nurse_headers))
    connected = validate_success(api.connect_referral(ref["id"], ctx.nurse_headers), 200)
    assert connected["status"] == "CONNECTED"
    # connected_at reflects the logical clock instant just set (whole-second match; the
    # PRD does not pin the sub-second format of connected_at).
    assert connected["connected_at"] is not None
    assert connected["connected_at"].startswith("2026-06-01T00:00:00")


# ─── Corner: consent gate on referral creation ──────────
def test_referral_without_consent_rejected(api):
    """PRD 3.8: "Opening a referral requires that the mother's consent has been recorded
    — if the client's consent_signed is false the request is rejected with
    ERR_CONSENT_REQUIRED".

    Design: Corner/validations/referral_create_without_consent_rejected
    """
    nurse = create_nurse(full_name="N Nc")
    client = create_client(full_name="C Nc", gestational_age_weeks=18)  # no consent
    enrollment = create_prospect_enrollment(client["id"])
    res = api.create_referral(
        create_referral_payload(enrollment["id"], "WIC"),
        make_nurse_headers(nurse["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CONSENT_REQUIRED.value)
