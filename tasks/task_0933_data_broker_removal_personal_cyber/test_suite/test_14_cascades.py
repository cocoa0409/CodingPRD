"""The two deep cascades: the five-hop account suspension and the four-hop
authorization revocation."""
from test_helpers import (
    validate_success, assert_same_instant,
    assert_entitlement_arithmetic, assert_seat_conservation, fixtures as fx,
)


# ==========================================================================
# Account suspension — the depth-5 chain plus the add-on branch
# ==========================================================================

def _household_ready_to_suspend():
    """An ACTIVE household with one ACTIVE profile, one QUEUED scan holding a
    SCAN unit, and one ACTIVE VPN add-on carrying one BOUND seat."""
    household = fx.open_household()
    profile = fx.setup_active_profile(household)
    addon, seat = fx.setup_addon_with_seat(household, addon_type="VPN",
                                           seats_total=2, per_seat_fee_cents=300,
                                           device_label="Dana Laptop")
    scan = fx.queue_scan(profile["id"], kind="INITIAL")
    return household, profile, addon, seat, scan


def test_account_suspend_pauses_profiles_and_cancels_their_queued_scans(api):
    """PRD §3.2: "Hop 1 moves the account `ACTIVE → SUSPENDED` and stamps `suspended_at`
    with the current instant."
    PRD §3.2: "Hop 2, caused by hop 1, moves every monitored profile of that household
    sitting in `ACTIVE` to `PAUSED`."
    PRD §3.2: "Hop 3, caused by hop 2, moves every scan run on one of those newly paused
    profiles sitting in `QUEUED` to `CANCELLED`."

    Design: Difficulty/transitive_cascade/account_suspend_depth5_scan_entitlement_release
    """
    household, profile, addon, seat, scan = _household_ready_to_suspend()
    before = fx.read_account(household)
    assert before["scan_units_granted"] == 12
    assert before["scan_units_consumed"] == 1
    assert before["scan_units_released"] == 0
    assert before["scan_units_remaining"] == 11

    data = validate_success(api.suspend_account(household["account_id"], fx.ADMIN))

    assert data["status"] == "SUSPENDED"
    assert_same_instant(data["suspended_at"], "2026-05-01T00:00:00Z", "suspended_at")
    assert fx.read_profile(profile["id"])["status"] == "PAUSED"
    cancelled = validate_success(api.get_scan_run(scan["id"], fx.ADMIN))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["entitlement_units_held"] == 0


def test_account_suspend_releases_the_scan_unit_through_the_ledger(api):
    """PRD §3.2: "Hop 4, caused by hop 3, takes each scan that entered `CANCELLED` while
    still holding its unit — that is, with `entitlement_units_held` equal to 1 — sets that
    field to 0 and appends a `SCAN` `RELEASE` ledger entry of `amount` 1 with `reason_code`
    `SCAN_CANCELLED`, booked against the account's open cycle."
    PRD §3.2: "Hop 5, caused by hop 4, is the arithmetic consequence: each appended entry
    raises `scan_units_released` and therefore `scan_units_remaining`."

    Design: Difficulty/transitive_cascade/account_suspend_depth5_scan_entitlement_release
    """
    household, profile, addon, seat, scan = _household_ready_to_suspend()

    data = validate_success(api.suspend_account(household["account_id"], fx.ADMIN))

    rows, meta = fx.ledger_entries(household["account_id"],
                                   resource_type="SCAN", entry_type="RELEASE")
    assert meta["total_count"] == 1
    assert rows[0]["amount"] == 1
    assert rows[0]["reason_code"] == "SCAN_CANCELLED"

    # 12 granted - 1 consumed + 1 released = 12 remaining.
    assert data["scan_units_released"] == 1
    assert data["scan_units_remaining"] == 12
    assert_entitlement_arithmetic(data)
    # Pausing never releases the PROFILE unit; only retirement does.
    assert data["profile_units_consumed"] == 1
    assert data["profile_units_released"] == 0


def test_account_suspend_branch_suspends_addons_and_voids_their_seats(api):
    """PRD §3.2: "Alongside that chain runs a separate branch: every add-on of the account
    sitting in `ACTIVE` moves to `SUSPENDED`, which in turn voids its bound seats."
    PRD §3.8: "Voiding is the involuntary path: a bound seat moves `BOUND → VOIDED` as a
    cascade of its add-on being suspended or cancelled, stamping `voided_at` while
    **preserving** `bind_count`, so binding history survives the suspension."

    Design: Difficulty/transitive_cascade/account_suspend_depth5_scan_entitlement_release
    """
    household, profile, addon, seat, scan = _household_ready_to_suspend()

    validate_success(api.suspend_account(household["account_id"], fx.ADMIN))

    addon_row = validate_success(api.get_addon(addon["id"], fx.ADMIN))
    assert addon_row["status"] == "SUSPENDED"
    assert addon_row["seats_bound"] == 0
    assert addon_row["seats_available"] == 2
    assert_seat_conservation(addon_row)

    seat_row = validate_success(api.get_device_seat(seat["id"], fx.ADMIN))
    assert seat_row["status"] == "VOIDED"
    assert seat_row["bind_count"] == 1, "binding history must survive the suspension"
    assert seat_row["released_at"] is None, \
        "a voided seat was never voluntarily released"


# ==========================================================================
# Authorization revocation — the depth-4 void-and-refund chain
# ==========================================================================

def _household_with_one_drafted_and_one_acknowledged_request():
    world = fx.setup_household_with_two_exposures(
        broker_a={"name": "PeopleFinderCo", "opt_out_method": "POSTAL",
                  "jurisdiction": "US_CA", "response_window_days": 30},
        broker_b={"name": "QuickLookup", "opt_out_method": "WEB_FORM",
                  "jurisdiction": "OTHER", "response_window_days": 30})
    world["drafted"] = fx.draft_removal(world["exposure_a"]["id"])
    world["acknowledged"] = fx.acknowledged_removal(world["exposure_b"]["id"],
                                                    broker_reference="QL-77")
    return world


def test_authorization_revoke_voids_only_the_drafted_request(api):
    """PRD §3.2: "Hop 2, caused by hop 1, moves every removal request of that member
    sitting in `DRAFTED` to `VOIDED` and stamps each one's `closed_at`."
    PRD §3.2: "Requests already sitting in `SUBMITTED`, `ACKNOWLEDGED`, `ESCALATED`,
    `COMPLETED`, `REJECTED` or `EXPIRED` are left entirely untouched."

    Design: Difficulty/transitive_cascade/authorization_revoke_depth4_void_and_refund
    """
    world = _household_with_one_drafted_and_one_acknowledged_request()
    household = world["household"]
    before = fx.read_account(household)
    assert before["removal_units_consumed"] == 2
    assert before["removal_units_remaining"] == 58

    data = validate_success(api.set_member_authorization(
        household["owner_id"], "REVOKE", household["owner"]))

    assert data["authorization_status"] == "REVOKED"
    assert_same_instant(data["authorization_revoked_at"], "2026-05-01T00:00:00Z",
                        "authorization_revoked_at")

    voided = fx.read_removal(world["drafted"]["id"])
    assert voided["status"] == "VOIDED"
    assert_same_instant(voided["closed_at"], "2026-05-01T00:00:00Z", "closed_at")

    survivor = fx.read_removal(world["acknowledged"]["id"])
    assert survivor["status"] == "ACKNOWLEDGED"
    assert survivor["entitlement_units_released"] == 0

    # Voiding a request never touches the exposure axis.
    assert fx.read_exposure(world["exposure_a"]["id"])["status"] == "FOUND"


def test_authorization_revoke_refunds_the_voided_requests_unit(api):
    """PRD §3.2: "Hop 3, caused by hop 2, takes each request entering `VOIDED` whose
    `entitlement_units_consumed` is 1 and whose `entitlement_units_released` is 0, sets
    `entitlement_units_released` to 1, and appends a `REMOVAL` `RELEASE` ledger entry of
    `amount` 1 with `reason_code` `AUTHORIZATION_REVOKED`."
    PRD §3.2: "Hop 4, caused by hop 3, is the arithmetic: `removal_units_released` and
    `removal_units_remaining` rise on the account and `removal_units_consumed_this_cycle`
    falls on the member."

    Design: Difficulty/transitive_cascade/authorization_revoke_depth4_void_and_refund
    """
    world = _household_with_one_drafted_and_one_acknowledged_request()
    household = world["household"]

    validate_success(api.set_member_authorization(
        household["owner_id"], "REVOKE", household["owner"]))

    voided = fx.read_removal(world["drafted"]["id"])
    assert voided["entitlement_units_released"] == 1

    rows, meta = fx.ledger_entries(household["account_id"],
                                   resource_type="REMOVAL", entry_type="RELEASE")
    assert meta["total_count"] == 1
    assert rows[0]["reason_code"] == "AUTHORIZATION_REVOKED"
    assert rows[0]["amount"] == 1

    account = fx.read_account(household)
    # 60 granted - 2 consumed + 1 released = 59 remaining.
    assert account["removal_units_released"] == 1
    assert account["removal_units_remaining"] == 59
    assert_entitlement_arithmetic(account)

    member = validate_success(api.get_member(household["owner_id"], fx.ADMIN))
    # 2 consumed minus the 1 released back = a net draw of 1.
    assert member["removal_units_consumed_this_cycle"] == 1
