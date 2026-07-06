"""Entitlement lifespan dates and the effectuation / expiration gates (PRD §3.5, §3.7)."""
from test_helpers import (
    validate_error, ApiErrorId,
    appeal_payload, make_applicant_headers,
    assert_instant_equals,
    build_decided_approved, build_effective, set_clock,
)
from test_helpers import api_client as api


# --- Provisional vs final expiration --------------------------------------

def test_provisional_expiration_from_decision_date(clerk_headers):
    """PRD §3.5: "It also sets a provisional_expiration_date: for a VARIANCE or CUP this is
    decision_at plus 730 days, for a SUBDIVISION it is decision_at plus 1095 days, and for a
    REZONE it is null because a rezone never expires."

    Design: Difficulty/dual_variant_calc/application_expiration_provisional_vs_final
    """
    ctx = build_decided_approved(app_type="CUP")
    app = api.get_application(ctx["app"]["id"], clerk_headers).json()["data"]
    assert_instant_equals(app["provisional_expiration_date"], "2028-05-31T00:00:00Z",
                          "provisional_expiration_date (decision_at + 730d)")


def test_final_expiration_from_effective_date_differs(clerk_headers):
    """PRD §3.7: "sets effective_date equal to the appeal_deadline (the instant the
    entitlement vests), computes the authoritative final_expiration_date as effective_date
    plus the type's entitlement span — 730 days for a VARIANCE or CUP, 1095 days for a
    SUBDIVISION, and null for a REZONE".
    PRD §3.7: "Because effective_date equals appeal_deadline, which is 15 days past
    decision_at, the final_expiration_date lands 15 days later than the earlier
    provisional_expiration_date."

    Design: Difficulty/dual_variant_calc/application_expiration_provisional_vs_final
    """
    ctx = build_effective(app_type="CUP")
    app = api.get_application(ctx["app"]["id"], clerk_headers).json()["data"]
    assert_instant_equals(app["effective_date"], "2026-06-16T00:00:00Z", "effective_date")
    assert_instant_equals(app["final_expiration_date"], "2028-06-15T00:00:00Z",
                          "final_expiration_date (effective_date + 730d)")
    assert app["final_expiration_date"] != app["provisional_expiration_date"], \
        "final expiration must be 15 days later than provisional"


# --- Effectuation gates ---------------------------------------------------

def test_effectuate_before_window_closes_rejected(clerk_headers):
    """PRD §3.7: "Effectuation of an approved application is permitted only when the current
    clock is strictly past the appeal_deadline (else ERR_APPEAL_WINDOW_OPEN)".

    Design: Corner/state_machines/effectuate_before_appeal_window_closes_returns_window_open
    """
    ctx = build_decided_approved(app_type="VARIANCE")
    set_clock("2026-06-10T00:00:00Z")  # still on/before the 2026-06-16 deadline
    resp = api.effectuate_application(ctx["app"]["id"], clerk_headers)
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_OPEN)


def test_effectuate_with_filed_appeal_rejected(clerk_headers):
    """PRD §3.7: "Effectuation of an approved application is permitted only when the current
    clock is strictly past the appeal_deadline (else ERR_APPEAL_WINDOW_OPEN) and no appeal
    for the application is in FILED or UPHELD status (else ERR_APPEAL_PENDING)."

    Design: Corner/state_machines/effectuate_with_pending_appeal_returns_appeal_pending
    """
    ctx = build_decided_approved(app_type="VARIANCE")
    app_id, applicant_id = ctx["app"]["id"], ctx["applicant"]["id"]
    api.create_appeal(appeal_payload(app_id), make_applicant_headers(applicant_id))
    set_clock("2026-06-17T00:00:00Z")  # strictly past the deadline, but appeal still FILED
    resp = api.effectuate_application(app_id, clerk_headers)
    validate_error(resp, ApiErrorId.ERR_APPEAL_PENDING)


def test_expire_before_final_expiration_rejected(clerk_headers):
    """PRD §3.7: "When the clock is strictly past final_expiration_date, the case moves from
    EFFECTIVE to EXPIRED, the parcel returns from ENTITLED to AVAILABLE, and
    review_window_closed_at is stamped; an attempt to expire before that instant is refused
    with ERR_NOT_YET_EXPIRED."

    Design: Corner/state_machines/expire_before_final_expiration_returns_not_yet_expired
    """
    ctx = build_effective(app_type="CUP")
    set_clock("2026-06-20T00:00:00Z")  # long before final_expiration 2028-06-15
    resp = api.effectuate_application(ctx["app"]["id"], clerk_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_YET_EXPIRED)
