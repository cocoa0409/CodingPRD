"""The global write gates, the authentication and ownership preamble, and the
immediate-consistency guarantee."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, validate_paginated,
    ApiErrorId, build_user_headers, assert_entitlement_arithmetic, fixtures as fx,
)


def test_cancelling_an_already_cancelled_account_runs_no_second_cascade(api):
    """PRD §3.2: "`CANCELLED` is terminal for an account."
    PRD §3.2: "Cancellation, available to `PlatformAdmin` and to the `AccountOwner`, works
    from either `ACTIVE → CANCELLED` or `SUSPENDED → CANCELLED`, requires `legal_hold`
    false, and applies the same side-effect set from either origin: `cancelled_at` is
    stamped; every add-on in `ACTIVE` or `SUSPENDED` moves to `CANCELLED`, and each of those
    add-ons' seats sitting in `BOUND` moves to `VOIDED`; every monitored profile of the
    account in `DRAFT`, `ACTIVE` or `PAUSED` moves to `RETIRED`; and the account's open
    billing cycle moves `OPEN → CLOSED`."

    The friction between rungs 18 and 19 never arises here: a *global write gate* sits
    above both of them and settles the second cancellation outright.
    PRD §2.6: "14. **Global write gate 2** — the account in scope has a status other than
    `CANCELLED`, otherwise `ERR_ACCOUNT_CANCELLED` (409). Applies to every account-scoped
    mutating endpoint except the legal-hold capability itself."
    PRD §2.6: "Rungs 13 through 15 are the **global write gates**, and they deliberately sit
    above every per-endpoint state gate, so an account under legal hold, or a cancelled or
    suspended subscription, pre-empts the entire family of transitions below."
    Rung 15 names account cancellation among its four exceptions; rung 14 names only the
    legal-hold capability, so re-cancelling a `CANCELLED` account is caught at rung 14.

    Design: Corner/state_machines/cancel_account_twice_returns_already_terminal
    """
    household = fx.open_household()
    first = validate_success(api.cancel_account(household["account_id"], fx.ADMIN))
    assert first["status"] == "CANCELLED"

    response = api.cancel_account(household["account_id"], fx.ADMIN)

    validate_error(response, ApiErrorId.ERR_ACCOUNT_CANCELLED.value, 409)
    after = fx.read_account(household)
    assert after["status"] == "CANCELLED"
    assert after["version"] == first["version"], \
        "the refused cancellation must not bump the account"

    cycles, meta = validate_paginated(api.list_billing_cycles(household["account_id"],
                                                              fx.ADMIN))
    assert meta["total_count"] == 1, "the cancel cascade did not run twice"
    assert cycles[0]["status"] == "CLOSED"


def test_resuming_an_active_account_reports_an_invalid_state(api):
    """PRD §3.2: "Resuming is deliberately **asymmetric** to suspending. It requires status
    `SUSPENDED` and `legal_hold` false, moves the account `SUSPENDED → ACTIVE` and clears
    `suspended_at` to null."
    PRD §2.6: "18. The target row is in a from-state for which a transition is declared for
    the requested trigger, otherwise `ERR_INVALID_STATE` (409). Applies to every
    state-transition endpoint."

    Design: Corner/state_machines/resume_an_active_account_returns_invalid_state
    """
    household = fx.open_household()

    response = api.resume_account(household["account_id"], fx.ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    account = fx.read_account(household)
    assert account["status"] == "ACTIVE"
    assert account["version"] == 1


def test_the_cancelled_gate_blocks_an_addon_purchase(api):
    """PRD §2.6: "14. **Global write gate 2** — the account in scope has a status other than
    `CANCELLED`, otherwise `ERR_ACCOUNT_CANCELLED` (409). Applies to every account-scoped
    mutating endpoint except the legal-hold capability itself."
    PRD §2.7: "Cancellation exempts only the legal-hold capability."

    Design: Corner/validations/cancelled_account_gate_rejects_addon_purchase
    """
    household = fx.open_household()
    validate_success(api.cancel_account(household["account_id"], fx.ADMIN))

    response = api.create_addon(household["account_id"],
                                {"addon_type": "VPN", "seats_total": 2,
                                 "per_seat_fee_cents": 300},
                                household["owner"])

    validate_error(response, ApiErrorId.ERR_ACCOUNT_CANCELLED.value, 409)
    _, meta = validate_paginated(api.list_account_addons(household["account_id"],
                                                         fx.ADMIN))
    assert meta["total_count"] == 0

    # The one exempt capability still works on a cancelled account.
    held = validate_success(api.set_legal_hold(household["account_id"], "HOLD_ON",
                                               fx.ADMIN))
    assert held["legal_hold"] is True


def test_the_suspended_gate_blocks_reactivating_a_paused_profile(api):
    """PRD §2.6: "15. **Global write gate 3** — the account in scope has a status other than
    `SUSPENDED`, otherwise `ERR_ACCOUNT_SUSPENDED` (409). Applies to every account-scoped
    mutating endpoint except four: account resume, account cancellation, the legal-hold
    capability, and billing-cycle closure."
    PRD §3.2: "Monitoring does **not** come back: profiles paused by the suspension stay
    `PAUSED` until somebody activates them explicitly."

    Design: Corner/validations/suspended_account_gate_rejects_profile_activation
    """
    household = fx.open_household()
    profile = fx.setup_active_profile(household)
    validate_success(api.suspend_account(household["account_id"], fx.ADMIN))
    assert fx.read_profile(profile["id"])["status"] == "PAUSED"

    response = api.activate_profile(profile["id"], household["owner"])

    validate_error(response, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value, 409)
    assert fx.read_profile(profile["id"])["status"] == "PAUSED"

    validate_success(api.resume_account(household["account_id"], fx.ADMIN))
    reactivated = validate_success(api.activate_profile(profile["id"],
                                                        household["owner"]))
    assert reactivated["status"] == "ACTIVE"
    assert fx.read_account(household)["profile_units_consumed"] == 1, \
        "re-activation from PAUSED consumes no second profile unit"


def test_a_request_without_a_user_id_header_is_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID` and `X-User-Role`. If
    either header is missing or empty, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401). The same code and status are returned when `X-User-Role` carries a value
    outside the five declared roles, which are exactly `PlatformAdmin`, `PrivacyAgent`,
    `AccountOwner`, `Member` and `Auditor`."

    Design: Corner/validations/request_missing_auth_headers_returns_unauthenticated
    """
    headerless = api.raw("GET", "/accounts",
                         headers={"X-User-Role": "PlatformAdmin",
                                  "Content-Type": "application/json"})

    validate_error(headerless, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    unknown_role = api.raw("GET", "/accounts",
                           headers=build_user_headers("admin-1", "Wizard"))
    validate_error(unknown_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_an_owner_of_one_account_may_not_read_another_accounts_profile(api):
    """PRD §2.6: "12. A caller acting as `Member` or `AccountOwner` addresses only rows
    belonging to their own account, and a non-primary `Member` addresses only rows whose
    member reference equals their own `X-User-ID`, except for account-level reads —
    otherwise `ERR_NOT_RESOURCE_OWNER` (403). Applies to every endpoint whose roles list
    includes `Member` or `AccountOwner`."
    PRD §2.1: "When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator
    identifier not tied to any persisted entity; the server never compares it to any row's
    `id`."

    Design: Corner/validations/member_cannot_read_another_accounts_profile
    """
    plan = fx.create_family_plan()
    account_a = fx.open_household(plan=plan, email="a@example.com", full_name="Ann A")
    account_b = fx.open_household(plan=plan, email="b@example.com", full_name="Ben B")
    profile = fx.draft_profile(account_a, full_name="Ann A",
                               date_of_birth="1980-01-01", primary_address="1 A St")

    response = api.get_monitored_profile(profile["id"], account_b["owner"])

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    validate_success(api.get_monitored_profile(profile["id"], account_a["owner"]))
    validate_success(api.get_monitored_profile(profile["id"], fx.ADMIN))


def test_a_disclosure_earlier_than_the_breach_is_an_invalid_date_range(api):
    """PRD §2.6: "10. Date-range coherence holds — otherwise `ERR_INVALID_DATE_RANGE` (422).
    A breach event's `disclosed_at` is at or after its `breach_date`, and an identity
    document's `expires_at` is at least one second after the current instant. The rung
    guards breach-event registration and identity-document upload."

    Design: Corner/validations/breach_event_with_disclosure_before_the_breach_is_rejected
    """
    response = api.create_breach_event(
        {"name": "Impossible Breach", "breach_date": "2026-04-01T00:00:00Z",
         "disclosed_at": "2026-03-01T00:00:00Z", "record_types": ["EMAIL_ADDRESS"],
         "base_severity_points": 10}, fx.ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_DATE_RANGE.value, 422)

    # The comparison is "at or after", so equality is admitted.
    validate_success(api.create_breach_event(
        {"name": "Same Day Breach", "breach_date": "2026-04-01T00:00:00Z",
         "disclosed_at": "2026-04-01T00:00:00Z", "record_types": ["EMAIL_ADDRESS"],
         "base_severity_points": 10}, fx.ADMIN), 201)

    # The same rung guards the document upload: expires_at equal to the current
    # instant is not at least one second later.
    household = fx.open_household()
    document = api.create_identity_document(
        household["owner_id"],
        {"document_type": "PASSPORT", "document_reference": "PASS-2",
         "expires_at": "2026-05-01T00:00:00Z"},
        household["owner"])
    validate_error(document, ApiErrorId.ERR_INVALID_DATE_RANGE.value, 422)


def test_a_non_primary_member_may_not_invite_another_member(api):
    """PRD §3.1: "Every later household seat arrives by **invitation**, an action available
    to the `AccountOwner` and to `PlatformAdmin`."
    PRD §2.6: "3. The endpoint's authorized-roles list contains the supplied `X-User-Role`
    — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."

    Design: Corner/rbac/member_cannot_invite_another_household_member
    """
    household = fx.open_household()
    kid = fx.invite_and_activate_member(household, email="kid@example.com",
                                        full_name="Robin Kid")

    response = api.invite_member(
        household["account_id"],
        {"email": "kid2@example.com", "full_name": "Sam Kid", "role_in_family": "MINOR",
         "expected_account_version": fx.account_version(household)},
        fx.make_member_headers(kid["id"]))

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    _, meta = validate_paginated(api.list_account_members(household["account_id"],
                                                          fx.ADMIN))
    assert meta["total_count"] == 2


def test_the_suspend_response_already_carries_the_post_cascade_figures(api):
    """PRD §2.11: "Where a cascade is described as a numbered chain of hops, that ordering
    is normative: hop 2 is caused by hop 1, hop 3 by hop 2, and so on, and side effects must
    be applied in that sequence because later hops read values that earlier hops have
    already written."
    PRD §3.2: "Hop 5, caused by hop 4, is the arithmetic consequence: each appended entry
    raises `scan_units_released` and therefore `scan_units_remaining`."

    Design: Corner/consistency_model/immediate_consistency_cascade_visible_in_the_same_response
    """
    household = fx.open_household()
    profile = fx.setup_active_profile(household)
    scan = fx.queue_scan(profile["id"], kind="INITIAL")

    data = validate_success(api.suspend_account(household["account_id"], fx.ADMIN))

    # The response body itself is three hops downstream of the transition it reports.
    assert data["scan_units_released"] == 1
    assert data["scan_units_remaining"] == 12
    assert_entitlement_arithmetic(data)

    reread = fx.read_account(household)
    assert reread["scan_units_released"] == 1
    assert reread["scan_units_remaining"] == 12
    assert validate_success(api.get_scan_run(scan["id"], fx.ADMIN))["status"] == "CANCELLED"
    assert fx.read_profile(profile["id"])["status"] == "PAUSED"
