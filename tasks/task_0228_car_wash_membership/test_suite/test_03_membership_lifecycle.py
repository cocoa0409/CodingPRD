"""Membership / freeze / invoice state transitions (PRD §3.4, §3.8, §3.10).

Translates queue-A non_linear_state_machine (membership cycle) and several
queue-B state-machine corners.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_membership, assert_freeze,
    TEST_USERS, make_account_holder_headers,
    setup_unlimited_active, schedule_freeze, set_clock,
    create_plan, create_account, create_vehicle, enroll_membership,
    pay_first_cycle_invoice,
)

PA = TEST_USERS["platform_admin_headers"]
BA = TEST_USERS["billing_admin_headers"]


# ─── Queue A: non_linear_state_machine / membership_cyclic_active_frozen_active ───

def test_membership_freeze_then_unfreeze_returns_to_active(api):
    """PRD §3.8: "**Freezing immediately** moves an `ACTIVE` membership to `FROZEN`."
    PRD §3.8: "**Thawing** a frozen membership returns it from `FROZEN` to `ACTIVE`".

    Design: Difficulty/non_linear_state_machine/membership_cyclic_active_frozen_active
    """
    plan, account, vehicle, membership = setup_unlimited_active(license_plate="CYC001")
    hdr = make_account_holder_headers(account["id"])

    frozen = validate_success(api.freeze_membership(membership["id"], hdr), 200)
    assert frozen["status"] == "FROZEN", "freeze must move ACTIVE membership to FROZEN"

    thawed = validate_success(api.unfreeze_membership(membership["id"], hdr), 200)
    assert thawed["status"] == "ACTIVE", "unfreeze must return FROZEN membership to ACTIVE"
    assert_membership(thawed)


def test_unfreeze_ends_the_active_freeze_record(api):
    """PRD §3.8: "**Thawing** a frozen membership returns it from `FROZEN` to `ACTIVE`;
    ... it ends the membership's open freeze record (moving that freeze from `ACTIVE` to
    `ENDED`)".

    Design: Difficulty/non_linear_state_machine/membership_cyclic_active_frozen_active
    """
    plan, account, vehicle, membership = setup_unlimited_active(license_plate="CYC002")
    hdr = make_account_holder_headers(account["id"])

    validate_success(api.freeze_membership(membership["id"], hdr), 200)
    validate_success(api.unfreeze_membership(membership["id"], hdr), 200)

    freezes, _ = (lambda r: (r.json()["data"], r.json()["meta"]))(
        api.list_freezes(membership["id"], hdr)
    )
    assert len(freezes) >= 1, "the immediate-freeze must have created a Freeze record"
    # The freeze that was ACTIVE is now ENDED after the unfreeze.
    assert any(f["status"] == "ENDED" for f in freezes), \
        "the freeze opened by the immediate freeze must be ENDED after unfreeze"


# ─── Queue B: state_machines corners ──────────────────────────────────────

def test_unfreeze_active_membership_rejected(api):
    """PRD §3.8: "Thawing a membership that is not `FROZEN` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/unfreeze_active_membership_invalid_state
    """
    plan, account, vehicle, membership = setup_unlimited_active(license_plate="UNF001")
    hdr = make_account_holder_headers(account["id"])
    res = api.unfreeze_membership(membership["id"], hdr)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_retry_on_paid_invoice_rejected(api):
    """PRD §3.4: "Retrying an invoice that is not `FAILED`, or one that has already
    reached the maximum attempts, is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/invoice_retry_on_paid_invoice_invalid_state
    """
    plan, account, vehicle, membership = setup_unlimited_active(license_plate="PAY001")
    hdr = make_account_holder_headers(account["id"])
    invoices = api.list_invoices(hdr, params={"membership_id": membership["id"], "kind": "CYCLE"})
    inv = validate_success(invoices, 200)[0]
    assert inv["status"] == "PAID", "first CYCLE invoice should be PAID after activation"
    res = api.retry_invoice(inv["id"], BA)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_scheduled_freeze_activates_on_clock_advance(api):
    """PRD §3.8: "When the logical clock is advanced to or past a scheduled freeze's
    `start_utc`, the system activates it: the freeze moves from `SCHEDULED` to `ACTIVE`,
    which drives the owning membership from `ACTIVE` to `FROZEN`".

    Design: Corner/state_machines/scheduled_freeze_activates_on_clock_advance
    """
    plan, account, vehicle, membership = setup_unlimited_active(
        clock="2026-06-01T00:00:00Z", license_plate="SCH001"
    )
    fz = schedule_freeze(
        membership["id"], account["id"], "2026-06-10T00:00:00Z", "2026-06-20T00:00:00Z"
    )
    assert fz["status"] == "SCHEDULED"
    set_clock("2026-06-11T00:00:00Z")

    hdr = make_account_holder_headers(account["id"])
    mem_after = validate_success(api.get_membership(membership["id"], hdr), 200)
    assert mem_after["status"] == "FROZEN", "clock past start_utc must drive membership to FROZEN"

    freezes = validate_success(api.list_freezes(membership["id"], hdr), 200)
    target = next(f for f in freezes if f["id"] == fz["id"])
    assert target["status"] == "ACTIVE", "the scheduled freeze must be ACTIVE after its start"


def test_cancel_scheduled_freeze_returns_cancelled(api):
    """PRD §3.8: "A scheduled freeze that has not yet started may be cancelled, moving it
    from `SCHEDULED` to `CANCELLED`."

    Design: Corner/state_machines/cancel_scheduled_freeze_returns_cancelled
    """
    plan, account, vehicle, membership = setup_unlimited_active(license_plate="FZC001")
    hdr = make_account_holder_headers(account["id"])
    fz = schedule_freeze(
        membership["id"], account["id"], "2026-06-10T00:00:00Z", "2026-06-20T00:00:00Z"
    )
    cancelled = validate_success(api.cancel_freeze(fz["id"], hdr), 200)
    assert cancelled["status"] == "CANCELLED"
    assert_freeze(cancelled)

    mem_after = validate_success(api.get_membership(membership["id"], hdr), 200)
    assert mem_after["status"] == "ACTIVE", "membership stays ACTIVE when a scheduled freeze is cancelled"
    acct_after = validate_success(api.get_account(account["id"], hdr), 200)
    assert acct_after["wallet_balance_cents"] == 0, "no refund credited for a cancelled scheduled freeze"


def test_close_account_with_active_membership_rejected(api):
    """PRD §3.10: "**Closing** an account moves its `status` to `CLOSED`, a terminal
    state, and is permitted only when the account is `ACTIVE` and none of its memberships
    is in any of the states `ACTIVE`, `PAST_DUE`, `FROZEN`, or `CANCEL_SCHEDULED`; ...
    closing one that fails its preconditions is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/account_close_with_active_membership_invalid_state
    """
    plan, account, vehicle, membership = setup_unlimited_active(license_plate="CLS001")
    res = api.close_account(account["id"], PA)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    hdr = make_account_holder_headers(account["id"])
    acct_after = validate_success(api.get_account(account["id"], hdr), 200)
    assert acct_after["status"] == "ACTIVE", "account stays ACTIVE when close precondition fails"
