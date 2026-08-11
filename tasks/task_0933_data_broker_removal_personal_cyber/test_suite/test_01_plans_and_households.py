"""Registering plans, opening households and growing the roster."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_plan, assert_account, assert_member,
    assert_same_instant, assert_entitlement_arithmetic, fixtures as fx,
)


def test_plan_registration_echoes_every_declared_quota_column(api):
    """PRD §3.1: "A plan declares a `tier` — one of `SOLO`, `FAMILY` or `FAMILY_PLUS` —
    together with a human-readable `name` of between 1 and 80 characters, a
    `monthly_fee_cents` charged per 30-day billing cycle, a `max_members` ceiling on how
    many household seats the plan admits, and four metering figures:
    `profile_quota_per_cycle`, `scan_quota_per_cycle` and `removal_quota_per_cycle`, which
    are the entitlement units granted to the account at the start of every cycle, plus
    `per_member_removal_subcap`, the maximum share of the shared removal pool that any one
    member may consume inside a single cycle."
    PRD §2.4: "Most resources additionally carry `updated_at` (same format, refreshed on
    every mutation) and `version`, an integer that starts at 1 when the row is created and
    increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/plan_creation_returns_201_with_declared_quota_columns
    """
    payload = {"tier": "FAMILY", "name": "Family Shield", "monthly_fee_cents": 2200,
               "max_members": 4, "profile_quota_per_cycle": 4,
               "scan_quota_per_cycle": 12, "removal_quota_per_cycle": 60,
               "per_member_removal_subcap": 25}

    data = validate_success(api.create_plan(payload, fx.ADMIN), 201)

    assert_plan(data)
    assert data["tier"] == "FAMILY"
    assert data["monthly_fee_cents"] == 2200
    assert data["max_members"] == 4
    assert data["profile_quota_per_cycle"] == 4
    assert data["scan_quota_per_cycle"] == 12
    assert data["removal_quota_per_cycle"] == 60
    assert data["per_member_removal_subcap"] == 25
    assert data["version"] == 1


def test_opening_a_household_mints_member_cycle_and_three_grants(api):
    """PRD §3.1: "It mints the **account** itself in status `ACTIVE` with `legal_hold`
    false and `version` 1; it mints the household's primary **member** directly in `ACTIVE`
    (not `INVITED`) with `is_primary` true, `role_in_family` `PRIMARY` and
    `authorization_status` `GRANTED`, and stamps that member's `id` onto the account as
    `primary_member_id`; it mints the account's first **billing cycle** with `cycle_seq` 1,
    `starts_at` at the current instant, `ends_at` exactly 30 days later, `status` `OPEN`
    and `base_charge_cents` copied from the plan's `monthly_fee_cents`; and it appends
    three ledger entries of type `GRANT` with `reason_code` `CYCLE_GRANT`, one per resource
    type, whose `amount` values come from the plan's three per-cycle quotas."

    Design: Corner/entities/account_creation_mints_primary_member_cycle_and_three_grants
    """
    plan = fx.create_family_plan()

    data = validate_success(api.create_account(
        {"plan_id": plan["id"], "primary_member_email": "owner@example.com",
         "primary_member_full_name": "Dana Owner"}, fx.ADMIN), 201)

    assert_account(data)
    assert data["status"] == "ACTIVE"
    assert data["legal_hold"] is False
    assert data["version"] == 1

    members, meta = validate_paginated(api.list_account_members(data["id"], fx.ADMIN))
    assert meta["total_count"] == 1
    assert members[0]["id"] == data["primary_member_id"]
    owner = members[0]
    assert_member(owner)
    assert owner["is_primary"] is True
    assert owner["status"] == "ACTIVE"
    assert owner["authorization_status"] == "GRANTED"
    assert owner["role_in_family"] == "PRIMARY"
    assert owner["invitation_token"] is None

    cycles, _ = validate_paginated(api.list_billing_cycles(data["id"], fx.ADMIN))
    cycle = cycles[0]
    assert cycle["cycle_seq"] == 1
    assert cycle["status"] == "OPEN"
    assert_same_instant(cycle["starts_at"], "2026-05-01T00:00:00Z", "starts_at")
    # 2026-05-01 + 30 days = 2026-05-31.
    assert_same_instant(cycle["ends_at"], "2026-05-31T00:00:00Z", "ends_at")
    assert cycle["base_charge_cents"] == 2200

    grants, grant_meta = fx.ledger_entries(data["id"], entry_type="GRANT")
    assert grant_meta["total_count"] == 3
    amounts = {row["resource_type"]: row["amount"] for row in grants}
    assert amounts == {"PROFILE": 4, "SCAN": 12, "REMOVAL": 60}
    assert all(row["reason_code"] == "CYCLE_GRANT" for row in grants)

    assert data["profile_units_remaining"] == 4
    assert data["scan_units_remaining"] == 12
    assert data["removal_units_remaining"] == 60


def test_reading_an_unknown_account_id_returns_account_not_found(api):
    """PRD §2.5: "Path parameters are resolved left to right. The first `{id}` segment that
    fails to resolve determines the error, and each resource family has its own code:
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
    `ERR_BROKER_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`,
    `ERR_REMOVAL_REQUEST_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BREACH_EVENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
    `ERR_ADDON_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND` and
    `ERR_LEDGER_ENTRY_NOT_FOUND`, all HTTP 404."

    Design: Corner/entities/get_account_with_unknown_id_returns_not_found
    """
    response = api.get_account("00000000-0000-4000-8000-000000000000", fx.ADMIN)

    validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_account_listing_reports_total_count_and_has_more(api):
    """PRD §2.3: "Both figures, together with `total_count` (the number of rows matching the
    filter before the window is applied) and `has_more` (true when rows remain beyond the
    current window), are echoed in the `meta` block of the response."
    PRD §2.3: "Unless a specific endpoint states otherwise, list results are ordered by
    `created_at` ascending."

    Design: Corner/entities/account_listing_pagination_reports_total_count_and_has_more
    """
    plan = fx.create_family_plan()
    first = fx.open_household(plan=plan, email="a@example.com", full_name="A Owner")
    fx.open_household(plan=plan, email="b@example.com", full_name="B Owner")
    third = fx.open_household(plan=plan, email="c@example.com", full_name="C Owner")

    rows, meta = validate_paginated(api.list_accounts(fx.ADMIN,
                                                      params={"limit": 2, "offset": 0}))
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert rows[0]["id"] == first["account_id"]

    tail, tail_meta = validate_paginated(api.list_accounts(fx.ADMIN,
                                                           params={"limit": 2, "offset": 2}))
    assert len(tail) == 1
    assert tail[0]["id"] == third["account_id"]
    assert tail_meta["has_more"] is False

    _, filtered = validate_paginated(api.list_accounts(fx.ADMIN,
                                                       params={"plan_id": plan["id"]}))
    assert filtered["total_count"] == 3


def test_invited_member_ignores_server_owned_fields_from_the_body(api):
    """PRD §3.1: "The invited row is created in `INVITED` with `is_primary` false,
    `authorization_status` `GRANTED`, and a server-issued opaque `invitation_token`
    returned in the response."

    Design: Corner/entities/member_create_system_field_input_ignored
    """
    household = fx.open_household()

    data = validate_success(api.invite_member(
        household["account_id"],
        {"email": "kid@example.com", "full_name": "Robin Kid",
         "role_in_family": "MINOR",
         "expected_account_version": fx.account_version(household),
         "status": "ACTIVE", "is_primary": True},
        household["owner"]), 201)

    assert data["status"] == "INVITED", "the supplied status must be ignored"
    assert data["is_primary"] is False, "the supplied is_primary must be ignored"
    assert isinstance(data["invitation_token"], str) and data["invitation_token"]
    assert data["authorization_status"] == "GRANTED"
    assert data["activated_at"] is None


def test_account_entitlement_figures_are_derived_from_the_ledger(api):
    """PRD §2.10: "These twelve figures surface on the account as `profile_units_granted`,
    `profile_units_consumed`, `profile_units_released`, `profile_units_remaining`,
    `scan_units_granted`, `scan_units_consumed`, `scan_units_released`,
    `scan_units_remaining`, `removal_units_granted`, `removal_units_consumed`,
    `removal_units_released` and `removal_units_remaining`."
    PRD §3.4: "Queuing is metered immediately: the row is created in `QUEUED` with
    `entitlement_units_held` 1, a `SCAN` `CONSUME` ledger entry of `amount` 1 with
    `reason_code` `SCAN_QUEUED` is appended, and `scan_units_remaining` falls by one."

    Design: Corner/entities/account_entitlement_fields_are_computed_from_the_ledger
    """
    household = fx.open_household()
    profile = fx.setup_active_profile(household)

    fx.queue_scan(profile["id"], kind="INITIAL")
    # A recurring scan queued while last_completed_scan_at is still null is admitted.
    fx.queue_scan(profile["id"], kind="RECURRING")

    data = validate_success(api.get_account(household["account_id"], household["owner"]))
    assert data["scan_units_granted"] == 12
    assert data["scan_units_consumed"] == 2
    assert data["scan_units_released"] == 0
    assert data["scan_units_remaining"] == 10
    assert data["profile_units_consumed"] == 1
    assert data["profile_units_remaining"] == 3
    assert_entitlement_arithmetic(data)

    rows, meta = fx.ledger_entries(household["account_id"],
                                   resource_type="SCAN", entry_type="CONSUME")
    assert meta["total_count"] == 2
    assert all(row["reason_code"] == "SCAN_QUEUED" for row in rows)


def test_redeeming_an_invitation_token_activates_the_member(api):
    """PRD §3.1: "Redeeming that token advances the member `INVITED → ACTIVE`. The caller
    supplies the `invitation_token`, which must equal the one stored on the member row, and
    the owning account must itself be `ACTIVE`."
    PRD §3.1: "On success the server stamps `activated_at` with the current instant and
    clears `invitation_token` to null, so the token is single-use by construction."

    Design: Corner/state_machines/member_activation_requires_the_issued_invitation_token
    """
    household = fx.open_household()
    invited = fx.invite_member(household, email="kid@example.com",
                               full_name="Robin Kid", role_in_family="MINOR")
    assert invited["status"] == "INVITED"

    data = validate_success(api.activate_member(
        invited["id"], invited["invitation_token"],
        fx.make_member_headers(invited["id"])))

    assert data["status"] == "ACTIVE"
    assert data["invitation_token"] is None
    assert_same_instant(data["activated_at"], "2026-05-01T00:00:00Z", "activated_at")


def test_removing_an_active_member_retires_profiles_and_releases_seats(api):
    """PRD §3.1: "Removal from `ACTIVE` fans out: every monitored profile of that member
    sitting in `DRAFT`, `ACTIVE` or `PAUSED` is retired, and each profile leaving `ACTIVE`
    or `PAUSED` appends a `PROFILE` `RELEASE` ledger entry with `reason_code`
    `PROFILE_RETIRED` (a profile leaving `DRAFT` releases nothing, because it never
    consumed anything); and every device seat of that member sitting in `BOUND` is released."

    Design: Corner/state_machines/member_remove_retires_profiles_and_releases_seats
    """
    household = fx.open_household()
    kid = fx.invite_and_activate_member(household, email="kid@example.com",
                                        full_name="Robin Kid")
    kid_headers = fx.make_member_headers(kid["id"])
    owner_profile = fx.setup_active_profile(household)
    kid_profile = fx.setup_active_profile(household, member_id=kid["id"],
                                          headers=kid_headers,
                                          identifier_value="robin@example.com",
                                          full_name="Robin Kid",
                                          date_of_birth="2010-07-14")
    addon = fx.buy_addon(household, addon_type="VPN", seats_total=2,
                         per_seat_fee_cents=300)
    kid_seat = fx.bind_seat(household, addon["id"], member_id=kid["id"],
                            device_label="Robin Tablet", headers=kid_headers)

    data = validate_success(api.remove_member(kid["id"], household["owner"]))

    assert data["status"] == "REMOVED"
    retired = fx.read_profile(kid_profile["id"])
    assert retired["status"] == "RETIRED"
    assert_same_instant(retired["retired_at"], "2026-05-01T00:00:00Z", "retired_at")
    assert fx.read_profile(owner_profile["id"])["status"] == "ACTIVE"

    seat = fx.read_seat(kid_seat["id"])
    assert seat["status"] == "RELEASED"
    assert_same_instant(seat["released_at"], "2026-05-01T00:00:00Z", "released_at")
    addon_row = fx.read_addon(addon["id"])
    assert addon_row["seats_bound"] == 0
    assert addon_row["seats_available"] == 2

    account = fx.read_account(household)
    assert account["profile_units_consumed"] == 2
    assert account["profile_units_released"] == 1
    assert account["profile_units_remaining"] == 3


def test_reusing_a_live_members_email_on_the_same_account_is_rejected(api):
    """PRD §3.1: "An email must contain an at-sign and is unique within its owning account:
    another member on the same account whose status is `INVITED` or `ACTIVE` already
    carrying that address is `ERR_DUPLICATE_MEMBER_EMAIL`."

    Design: Corner/validations/duplicate_member_email_is_rejected
    """
    household = fx.open_household(email="owner@example.com")

    response = api.invite_member(
        household["account_id"],
        {"email": "owner@example.com", "full_name": "Clone Owner",
         "role_in_family": "ADULT",
         "expected_account_version": fx.account_version(household)},
        household["owner"])

    validate_error(response, ApiErrorId.ERR_DUPLICATE_MEMBER_EMAIL.value, 409)
    _, meta = validate_paginated(api.list_account_members(household["account_id"],
                                                          fx.ADMIN))
    assert meta["total_count"] == 1
    assert fx.read_account(household)["version"] == 1, \
        "a rejected invite must not bump the account"


def test_the_invitation_that_would_fill_the_roster_is_rejected(api):
    """PRD §3.1: "The roster ceiling is a **strict** comparison: an invitation is admitted
    only while the count of members in `INVITED` or `ACTIVE` is strictly less than the
    plan's `max_members`, and the invitation that would make the two equal is rejected with
    `ERR_MEMBER_CAP_EXCEEDED`."
    PRD §3.1: "Members in `REMOVED` free their seat and do not count."

    Design: Corner/validations/fifth_member_rejected_by_the_plan_member_cap
    """
    household = fx.open_household()  # FAMILY: max_members 4
    first = fx.invite_member(household, email="m1@example.com", full_name="M One",
                             role_in_family="ADULT")
    fx.invite_member(household, email="m2@example.com", full_name="M Two",
                     role_in_family="ADULT")
    fx.invite_member(household, email="m3@example.com", full_name="M Three",
                     role_in_family="MINOR")

    response = api.invite_member(
        household["account_id"],
        {"email": "m4@example.com", "full_name": "M Four", "role_in_family": "MINOR",
         "expected_account_version": fx.account_version(household)},
        household["owner"])

    validate_error(response, ApiErrorId.ERR_MEMBER_CAP_EXCEEDED.value, 409)
    _, meta = validate_paginated(api.list_account_members(household["account_id"],
                                                          fx.ADMIN))
    assert meta["total_count"] == 4

    # A REMOVED member frees their seat, so the same invitation then lands.
    validate_success(api.remove_member(first["id"], household["owner"]))
    validate_success(api.invite_member(
        household["account_id"],
        {"email": "m4@example.com", "full_name": "M Four", "role_in_family": "MINOR",
         "expected_account_version": fx.account_version(household)},
        household["owner"]), 201)


def test_an_invited_member_cannot_draft_a_monitored_profile(api):
    """PRD §2.6: "21. The member the operation depends on has status `ACTIVE`, otherwise
    `ERR_MEMBER_NOT_ACTIVE` (409). Applies to profile drafting, profile activation, seat
    binding and the member-authorization flip."
    PRD §3.3: "Drafting requires the named member to be `ACTIVE` (otherwise
    `ERR_MEMBER_NOT_ACTIVE`) and their authorization to be `GRANTED`."

    Design: Corner/validations/invited_member_cannot_create_a_monitored_profile
    """
    household = fx.open_household()
    invited = fx.invite_member(household, email="kid@example.com",
                               full_name="Robin Kid", role_in_family="MINOR")
    kid_headers = fx.make_member_headers(invited["id"])

    response = api.create_monitored_profile(
        {"member_id": invited["id"], "full_name": "Robin Kid",
         "date_of_birth": "2010-07-14", "primary_address": "12 Elm St, Springfield"},
        kid_headers)

    validate_error(response, ApiErrorId.ERR_MEMBER_NOT_ACTIVE.value, 409)
    _, meta = validate_paginated(api.list_member_profiles(invited["id"], fx.ADMIN))
    assert meta["total_count"] == 0

    validate_success(api.activate_member(invited["id"], invited["invitation_token"],
                                         kid_headers))
    validate_success(api.create_monitored_profile(
        {"member_id": invited["id"], "full_name": "Robin Kid",
         "date_of_birth": "2010-07-14", "primary_address": "12 Elm St, Springfield"},
        kid_headers), 201)


def test_account_owner_role_on_a_non_primary_member_is_unresolved(api):
    """PRD §2.1: "For both of these roles, if `X-User-ID` does not resolve to an existing
    member row — or if the role is `AccountOwner` and the resolved member has `is_primary`
    false — the request is rejected with `ERR_IDENTITY_UNRESOLVED` (HTTP 403)."

    Design: Corner/validations/accountowner_header_on_a_non_primary_member_returns_forbidden
    """
    household = fx.open_household()
    kid = fx.invite_and_activate_member(household, email="kid@example.com",
                                        full_name="Robin Kid")

    version = fx.account_version(household)
    response = api.invite_member(
        household["account_id"],
        {"email": "kid2@example.com", "full_name": "Sam Kid", "role_in_family": "MINOR",
         "expected_account_version": version},
        fx.make_account_owner_headers(kid["id"]))

    validate_error(response, ApiErrorId.ERR_IDENTITY_UNRESOLVED.value, 403)
    _, meta = validate_paginated(api.list_account_members(household["account_id"],
                                                          fx.ADMIN))
    assert meta["total_count"] == 2

    # The identical call presented by the true primary member succeeds.
    validate_success(api.invite_member(
        household["account_id"],
        {"email": "kid2@example.com", "full_name": "Sam Kid", "role_in_family": "MINOR",
         "expected_account_version": version},
        household["owner"]), 201)
