"""Payment arrangements: installment math, default→reinstate cycle, the three-link
default cascade, optimistic-concurrency supersede, and stale-version rejection."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS,
    open_account, arrangement_payload,
    setup_active_arrangement, setup_account_with_bill_and_arrangement,
)

BS = TEST_USERS["billing_specialist_headers"]
CO = TEST_USERS["collections_officer_headers"]
CW = TEST_USERS["assistance_caseworker_headers"]


# ---------------------------------------------------------------------------
# non_linear_state_machine / payment_arrangement_default_reinstate_cycle
# ---------------------------------------------------------------------------
def test_arrangement_installment_amount_rounded(api):
    """PRD §3.7: "The arrangement's `installment_amount_cents` is the total divided by the
    installment count, rounded half up."

    Design: Difficulty/non_linear_state_machine/payment_arrangement_default_reinstate_cycle
    """
    ctx = setup_active_arrangement(api, total_arranged_cents=30000, installment_count=3)
    assert ctx["arrangement"]["installment_amount_cents"] == 10000


def test_arrangement_default_then_reinstate_returns_to_active(api):
    """PRD §3.7: "When an assistance caseworker reinstates a `DEFAULTED` arrangement, it
    moves `DEFAULTED → ACTIVE`, any `SCHEDULED` `CASCADE` shutoff order created by that
    default is cancelled (`SCHEDULED → CANCELLED`), and — if the arrangement covers the
    account's arrears — the account recovers `DELINQUENT → ACTIVE`. This reinstatement loop
    between `ACTIVE` and `DEFAULTED` may repeat."

    Design: Difficulty/non_linear_state_machine/payment_arrangement_default_reinstate_cycle
    """
    ctx = setup_active_arrangement(api, total_arranged_cents=30000, installment_count=3)
    pa_id = ctx["arrangement"]["id"]
    defaulted = validate_success(api.record_missed(pa_id, CO))
    assert defaulted["status"] == "DEFAULTED"
    reinstated = validate_success(api.reinstate_arrangement(pa_id, CW))
    assert reinstated["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# transitive_cascade / arrangement_default_cascade_to_shutoff_depth3
# ---------------------------------------------------------------------------
def test_record_missed_defaults_arrangement_and_delinquents_account_and_bill(api):
    """PRD §3.7: "When a collections officer records a missed installment against an
    `ACTIVE` arrangement, the arrangement moves `ACTIVE → DEFAULTED`; the account moves
    `ACTIVE → DELINQUENT`; the account's `UNPAID` and `PARTIAL` bills move `collection_status`
    `CURRENT → DELINQUENT` (driving the recompute of `delinquent_balance_cents`); and a
    `CASCADE`-origin shutoff order is auto-created in `status` `SCHEDULED` for the account.
    All three links apply together."

    Design: Difficulty/transitive_cascade/arrangement_default_cascade_to_shutoff_depth3
    """
    ctx = setup_account_with_bill_and_arrangement(api, reading_value=9500,
                                                  total_arranged_cents=4640, installment_count=4)
    pa = validate_success(api.record_missed(ctx["arrangement"]["id"], CO))
    assert pa["status"] == "DEFAULTED"
    account = validate_success(api.get_account(ctx["account"]["id"], BS))
    assert account["status"] == "DELINQUENT"
    bill = validate_success(api.get_bill(ctx["bill"]["id"], BS))
    assert bill["collection_status"] == "DELINQUENT"


def test_record_missed_auto_creates_cascade_shutoff_order(api):
    """PRD §3.7: "a `CASCADE`-origin shutoff order is auto-created in `status` `SCHEDULED`
    for the account. All three links apply together."

    Design: Difficulty/transitive_cascade/arrangement_default_cascade_to_shutoff_depth3
    """
    ctx = setup_account_with_bill_and_arrangement(api, reading_value=9500,
                                                  total_arranged_cents=4640, installment_count=4)
    validate_success(api.record_missed(ctx["arrangement"]["id"], CO))
    orders, _ = validate_paginated(api.list_shutoff_orders(ctx["account"]["id"], CO))
    assert len(orders) == 1, f"expected exactly one auto-created order, got {len(orders)}"
    assert orders[0]["origin"] == "CASCADE"
    assert orders[0]["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# cross_cutting_complexity_layers / arrangement_create_stale_account_version_returns_412
# ---------------------------------------------------------------------------
def test_arrangement_create_with_stale_version_rejected(api):
    """PRD §2.7: "A `POST /accounts/{id}/payment-arrangements` request must carry
    `expected_account_version` as a non-optional field, holding the client's last observed
    `version` of the target `Account`. If that value does not equal the account's current
    `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/arrangement_create_stale_account_version_returns_412
    """
    account = open_account(api, account_holder_name="OCC Ola")
    v0 = account["version"]
    pa1 = validate_success(api.create_arrangement(account["id"], arrangement_payload(20000, 4, v0), CW), 201)
    # Second create reuses the now-stale v0 (account advanced to v0+1 on the first create).
    resp = api.create_arrangement(account["id"], arrangement_payload(30000, 5, v0), CW)
    validate_error(resp, "ERR_STALE_VERSION")
    still = validate_success(api.get_account(account["id"], BS))
    pas, _ = validate_paginated(api.list_arrangements(account["id"], CW))
    first = [p for p in pas if p["id"] == pa1["id"]][0]
    assert first["status"] == "ACTIVE", "the stale request must not supersede the prior arrangement"


# ---------------------------------------------------------------------------
# cross_cutting_complexity_layers / arrangement_create_supersede_prior_active
# ---------------------------------------------------------------------------
def test_arrangement_create_supersedes_prior_active(api):
    """PRD §3.7: "Creating an arrangement supersedes any prior `ACTIVE` arrangement on the
    account — the prior one moves `ACTIVE → SUPERSEDED` — the new arrangement opens
    `ACTIVE`, and the account's `version` increments by 1."

    Design: Corner/cross_cutting_complexity_layers/arrangement_create_supersede_prior_active
    """
    account = open_account(api, account_holder_name="Sup Sue")
    pa1 = validate_success(api.create_arrangement(account["id"], arrangement_payload(20000, 4, account["version"]), CW), 201)
    refreshed = validate_success(api.get_account(account["id"], CW))
    pa2 = validate_success(api.create_arrangement(account["id"], arrangement_payload(30000, 5, refreshed["version"]), CW), 201)
    pas, _ = validate_paginated(api.list_arrangements(account["id"], CW))
    by_id = {p["id"]: p for p in pas}
    assert by_id[pa1["id"]]["status"] == "SUPERSEDED"
    assert by_id[pa2["id"]]["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# state_machines / reinstate_active_arrangement_returns_invalid_state (corner)
# ---------------------------------------------------------------------------
def test_reinstate_active_arrangement_rejected(api):
    """PRD §3.7: "When an assistance caseworker reinstates a `DEFAULTED` arrangement, it
    moves `DEFAULTED → ACTIVE`".
    PRD §2.11: "a transition attempted from an invalid current state yields
    `ERR_INVALID_STATE` (409)".

    Design: Corner/state_machines/reinstate_active_arrangement_returns_invalid_state
    """
    ctx = setup_active_arrangement(api, total_arranged_cents=12000, installment_count=4)
    validate_error(api.reinstate_arrangement(ctx["arrangement"]["id"], CW), "ERR_INVALID_STATE")
