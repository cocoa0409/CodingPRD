"""Payout lifecycle, settlement ledger, optimistic concurrency, and RBAC on payouts."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error,
    make_creator_headers,
    fixtures as fx,
    create_payout_payload,
)


# --------------------------------------------------------------------------
# Difficulty: payout creation gated on Creator.status (masks fiscal / OCC checks).
# --------------------------------------------------------------------------

def test_suspended_creator_payout_rejected(api):
    """PRD §3.8: "The creator must be `ACTIVE` — a request from a `SUSPENDED` creator is
    rejected with `ERR_CREATOR_SUSPENDED` — and the amount may not exceed the creator's
    `available_for_payout_cents`, else `ERR_INSUFFICIENT_BALANCE` at HTTP 402."

    Design: Difficulty/cross_entity_state_dependency/payout_requires_active_creator
    """
    creator = fx.create_creator()
    fx.suspend_creator(creator["id"])
    cv = fx.get_creator(creator["id"])["version"]
    resp = api.create_payout(creator["id"], create_payout_payload(1000, cv),
                             make_creator_headers(creator["id"]))
    validate_error(resp, ApiErrorId.ERR_CREATOR_SUSPENDED.value)


def test_suspended_creator_with_balance_still_rejected(api):
    """PRD §2.1: "(8) cross-entity status gates hold; (9) time-window gates hold; (10)
    interval-overlap and uniqueness gates hold; (11) quota and fiscal gates hold; and finally
    (12) the optimistic-concurrency check for payout creation. Earlier checks always mask
    later ones."

    Design: Difficulty/cross_entity_state_dependency/payout_requires_active_creator
    """
    ctx = fx.setup_settled_balance(amount_cents=20000)  # settled 18000 available
    fx.suspend_creator(ctx["creator"]["id"])
    cv = fx.get_creator(ctx["creator"]["id"])["version"]
    resp = api.create_payout(ctx["creator"]["id"], create_payout_payload(5000, cv),
                             make_creator_headers(ctx["creator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CREATOR_SUSPENDED.value)


# --------------------------------------------------------------------------
# Corner: optimistic concurrency on payout creation.
# --------------------------------------------------------------------------

def test_stale_creator_version_second_payout_rejected(api):
    """PRD §2.10: "If that value does not equal the creator's current `version`, the request
    is rejected with `ERR_STALE_CREATOR_VERSION` at HTTP 412, and no payout is created." PRD
    §2.10: "The creator's `version` advances every time a payout is created and every time a
    payout changes status, so once any earlier payout activity has moved the version past
    what the client last read, the current request is refused as operating on a stale balance."

    Design: Corner/cross_cutting/occ_stale_creator_version_returns_412
    """
    ctx = fx.setup_settled_balance(amount_cents=20000)
    cv = ctx["version"]
    fx.request_payout(ctx["creator"]["id"], 5000, cv)  # succeeds, bumps version
    resp = api.create_payout(ctx["creator"]["id"], create_payout_payload(5000, cv),
                             make_creator_headers(ctx["creator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_CREATOR_VERSION.value)


def test_payout_reaching_paid_moves_reserved_into_paid(api):
    """PRD §3.8: "From `PROCESSING` it may reach `PAID`, at which point the amount moves out
    of `earnings_reserved_cents` and into `earnings_paid_cents`."

    Design: Corner/cross_cutting/creator_version_increments_on_payout_paid
    """
    ctx = fx.setup_settled_balance(amount_cents=20000)
    payout = fx.request_payout(ctx["creator"]["id"], 5000, ctx["version"])
    fx.advance_payout(payout["id"], "PROCESSING")
    paid = fx.advance_payout(payout["id"], "PAID")
    assert paid["status"] == "PAID"
    creator = validate_success(
        api.get_creator(ctx["creator"]["id"], make_creator_headers(ctx["creator"]["id"])))
    assert creator["earnings_paid_cents"] == 5000


def test_payout_exceeding_available_balance_rejected(api):
    """PRD §3.8: "the amount may not exceed the creator's `available_for_payout_cents`, else
    `ERR_INSUFFICIENT_BALANCE` at HTTP 402."

    Design: Corner/validations/payout_insufficient_balance_returns_402
    """
    ctx = fx.setup_settled_balance(amount_cents=20000)  # available 18000
    resp = api.create_payout(ctx["creator"]["id"], create_payout_payload(20000, ctx["version"]),
                             make_creator_headers(ctx["creator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value)


def test_payout_skip_processing_transition_rejected(api):
    """PRD §3.8: "A requested transition that is not legal from the payout's current status
    is rejected with `ERR_PAYOUT_INVALID_STATUS_TRANSITION`, and a set-status value outside
    the payout status enum is `ERR_INVALID_STATUS_VALUE`."

    Design: Corner/state_machines/payout_requested_to_paid_skip_returns_409
    """
    ctx = fx.setup_settled_balance(amount_cents=20000)
    payout = fx.request_payout(ctx["creator"]["id"], 5000, ctx["version"])
    resp = api.set_payout_status(payout["id"], {"status": "PAID"},
                                 fx.TEST_USERS["platform_admin_headers"])
    validate_error(resp, ApiErrorId.ERR_PAYOUT_INVALID_STATUS_TRANSITION.value)


def test_creator_cannot_advance_payout_rejected(api):
    """PRD §2.1: "When a syntactically valid request names a role that is not permitted to
    perform the requested operation, the platform responds with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/creator_cannot_advance_payout_returns_403
    """
    ctx = fx.setup_settled_balance(amount_cents=20000)
    payout = fx.request_payout(ctx["creator"]["id"], 5000, ctx["version"])
    resp = api.set_payout_status(payout["id"], {"status": "PROCESSING"},
                                 make_creator_headers(ctx["creator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
