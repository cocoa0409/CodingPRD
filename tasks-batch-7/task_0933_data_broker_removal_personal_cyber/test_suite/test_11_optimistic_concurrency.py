"""The four stale-version guards, each on a parent row's `version`."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, fixtures as fx,
)


def test_a_stale_profile_version_blocks_a_second_identifier_add(api):
    """PRD §2.8: "Adding an identifier to a monitored profile requires
    `expected_profile_version` matching that profile's current `version`. Identifier
    additions legitimately succeed one after another while the profile stays under its
    eight-identifier ceiling, so no state precondition catches a writer whose view of the
    profile — of how many slots remain, and of which values are already monitored — has gone
    stale. A mismatch is rejected with `ERR_STALE_PROFILE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_profile_version_blocks_second_identifier_add
    """
    household = fx.open_household()
    profile = fx.draft_profile(household)
    stale_version = profile["version"]

    validate_success(api.add_identifier(
        profile["id"],
        {"identifier_type": "EMAIL", "identifier_value": "one@example.com",
         "expected_profile_version": stale_version},
        household["owner"]), 201)
    assert fx.profile_version(profile["id"], household["owner"]) == 2

    response = api.add_identifier(
        profile["id"],
        {"identifier_type": "EMAIL", "identifier_value": "two@example.com",
         "expected_profile_version": stale_version},
        household["owner"])

    validate_error(response, ApiErrorId.ERR_STALE_PROFILE_VERSION.value, 412)
    _, meta = validate_paginated(api.list_identifiers(profile["id"], household["owner"]))
    assert meta["total_count"] == 1

    # Re-reading the parent and resending with the fresh version succeeds.
    validate_success(api.add_identifier(
        profile["id"],
        {"identifier_type": "EMAIL", "identifier_value": "two@example.com",
         "expected_profile_version": fx.profile_version(profile["id"],
                                                        household["owner"])},
        household["owner"]), 201)
    _, meta = validate_paginated(api.list_identifiers(profile["id"], household["owner"]))
    assert meta["total_count"] == 2


def test_a_stale_account_version_blocks_a_second_member_invite(api):
    """PRD §2.8: "Inviting a member likewise requires `expected_account_version` matching
    the account's current `version`. Invitations legitimately succeed one after another
    while the roster stays below the plan's `max_members`, so the member cap alone cannot
    protect a writer working from a stale roster. A mismatch is rejected with
    `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_account_version_blocks_second_member_invite
    """
    household = fx.open_household()
    stale_version = household["account"]["version"]

    validate_success(api.invite_member(
        household["account_id"],
        {"email": "m1@example.com", "full_name": "M One", "role_in_family": "ADULT",
         "expected_account_version": stale_version},
        household["owner"]), 201)
    assert fx.account_version(household) == 2

    response = api.invite_member(
        household["account_id"],
        {"email": "m2@example.com", "full_name": "M Two", "role_in_family": "ADULT",
         "expected_account_version": stale_version},
        household["owner"])

    validate_error(response, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value, 412)
    _, meta = validate_paginated(api.list_account_members(household["account_id"],
                                                          fx.ADMIN))
    # The primary plus m1 only; the roster still has room under the ceiling of 4,
    # so the member cap cannot have been the blocker.
    assert meta["total_count"] == 2


def test_a_stale_addon_version_blocks_a_second_seat_bind(api):
    """PRD §2.8: "Binding a device seat requires `expected_addon_version` matching the
    target add-on's current `version`. Seat binds legitimately succeed one after another
    while seats remain available, so nothing in the state machine catches a writer whose
    view of the seat pool has gone stale. A mismatch is rejected with
    `ERR_STALE_ADDON_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_addon_version_blocks_second_seat_bind
    """
    household = fx.open_household()
    addon = fx.buy_addon(household, addon_type="VPN", seats_total=3,
                         per_seat_fee_cents=300)
    stale_version = addon["version"]

    validate_success(api.create_device_seat(
        {"addon_id": addon["id"], "member_id": household["owner_id"],
         "device_label": "Laptop", "expected_addon_version": stale_version},
        household["owner"]), 201)
    first = fx.read_addon(addon["id"])
    assert first["version"] == stale_version + 1
    assert first["seats_bound"] == 1

    response = api.create_device_seat(
        {"addon_id": addon["id"], "member_id": household["owner_id"],
         "device_label": "Tablet", "expected_addon_version": stale_version},
        household["owner"])

    validate_error(response, ApiErrorId.ERR_STALE_ADDON_VERSION.value, 412)
    after = fx.read_addon(addon["id"])
    # Two of three seats were still free, so capacity was never the issue.
    assert after["seats_bound"] == 1
    assert after["seats_available"] == 2
    _, meta = validate_paginated(api.list_device_seats(household["owner"],
                                                       params={"addon_id": addon["id"]}))
    assert meta["total_count"] == 1


def test_a_stale_account_version_blocks_a_second_plan_change(api):
    """PRD §2.8: "Applying a plan change requires `expected_account_version` matching the
    account's current `version`. A later plan change legitimately supersedes an earlier one
    inside the same cycle, and the proration arithmetic depends on which plan the account
    actually holds, so a stale view must not book a charge derived from a plan the account
    has already left. A mismatch is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."
    PRD §3.9: "Under the **`UPGRADE`** variant, in force when `change_kind` is `UPGRADE` and
    the new fee is strictly greater than the old, the server first divides the fee delta by
    30 and rounds half-up to a whole cent to get a daily rate, and *then* multiplies that
    rounded rate by the remaining days."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_account_version_blocks_second_plan_change
    """
    solo = fx.create_solo_plan()
    family = fx.create_family_plan()
    plus = fx.create_family_plus_plan()
    household = fx.open_household(plan=solo)
    stale_version = household["account"]["version"]
    fx.set_clock("2026-05-11T00:00:00Z")

    first = validate_success(api.change_plan(
        household["account_id"],
        {"new_plan_id": family["id"], "change_kind": "UPGRADE",
         "expected_account_version": stale_version},
        household["owner"]))
    assert first["plan_id"] == family["id"]
    assert first["version"] == stale_version + 1

    response = api.change_plan(
        household["account_id"],
        {"new_plan_id": plus["id"], "change_kind": "UPGRADE",
         "expected_account_version": stale_version},
        household["owner"])

    validate_error(response, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value, 412)
    account = fx.read_account(household)
    assert account["plan_id"] == family["id"]
    assert account["version"] == first["version"]
    # Only the first change booked: delta 1000 -> round_half_up(1000/30) = 33;
    # 33 * 20 remaining days = 660.
    assert fx.first_cycle(household)["proration_charge_cents"] == 660

    validate_success(api.change_plan(
        household["account_id"],
        {"new_plan_id": plus["id"], "change_kind": "UPGRADE",
         "expected_account_version": account["version"]},
        household["owner"]))
    # delta 3400 - 2200 = 1200 -> round_half_up(1200/30) = 40; 40 * 20 = 800.
    assert fx.first_cycle(household)["proration_charge_cents"] == 660 + 800
