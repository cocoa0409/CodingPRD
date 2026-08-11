"""Referral revocation: conditional clawback and terminal lockdown (PRD 3.9)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_referral_revoke_pending_posts_no_clawback(api):
    """PRD 3.9: "A PlatformAdmin may revoke a referral in `PENDING` or `QUALIFIED` — any other state is rejected with `ERR_REFERRAL_NOT_REVOKABLE` (HTTP 409). Revoking a `QUALIFIED` referral posts a compensating `REVOKE_REFERRAL` ledger entry of the negated `qualified_credit_cents` to the referrer; revoking a `PENDING` one carries no compensation."

    Design: Corner/state_machines/referral_revoke_pending_posts_no_clawback
    """
    pair = th.register_referral_pair(referrer_email="s14r@x.com",
                                     referee_email="s14e@x.com")
    assert pair["referral"]["status"] == "PENDING"

    revoked = th.validate_success(
        api.revoke_referral(pair["referral"]["id"], ADMIN)
    )
    assert revoked["status"] == "REVOKED"

    # The clawback is conditional on QUALIFIED: zero ledger entries here.
    assert th.list_ledger(customer_id=pair["referrer"]["id"]) == []
    assert th.get_customer_balance(pair["referrer"]["id"]) == 0


def test_revoke_revoked_referral_rejected(api):
    """PRD 3.9: "A PlatformAdmin may revoke a referral in `PENDING` or `QUALIFIED` — any other state is rejected with `ERR_REFERRAL_NOT_REVOKABLE` (HTTP 409). Revoking a `QUALIFIED` referral posts a compensating `REVOKE_REFERRAL` ledger entry of the negated `qualified_credit_cents` to the referrer; revoking a `PENDING` one carries no compensation. Both paths end in the terminal `REVOKED` state and increment the referral's `version` by 1."

    Design: Corner/validations/revoke_revoked_referral_rejected
    """
    pair = th.register_referral_pair(referrer_email="v10r@x.com",
                                     referee_email="v10e@x.com")
    th.validate_success(api.revoke_referral(pair["referral"]["id"], ADMIN))

    # REVOKED is terminal: a second revoke is rejected, no duplicate clawback.
    th.validate_error(
        api.revoke_referral(pair["referral"]["id"], ADMIN),
        th.ApiErrorId.ERR_REFERRAL_NOT_REVOKABLE,
    )
    assert th.list_ledger(customer_id=pair["referrer"]["id"]) == []
