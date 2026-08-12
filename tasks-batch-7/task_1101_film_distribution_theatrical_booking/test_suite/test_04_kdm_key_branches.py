"""KDM key branching: extend vs revoke vs expire (PRD §3.5)."""
from test_helpers import (
    validate_success,
    get_success_data,
    is_valid_uuid,
    setup_distributor_film_theatre_screen,
    setup_kdm_issued_booking,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOOKER = TEST_USERS["booker_headers"]


def _set_clock(api, to_iso8601):
    get_success_data(api.set_current_utc({"to_iso8601": to_iso8601}, ADMIN))


def test_extend_branch_spawns_superseding_key(api):
    """PRD §3.5: "Extending a key from `ISSUED` requires the new `valid_until_utc` to be
    strictly later than the current one; extending from `LIVE` requires only that the
    key still be live. Either extension moves the original record to `EXTENDED` and
    creates a superseding key in `ISSUED` carrying the new window."

    Design: Difficulty/non_linear_state_machine/kdm_key_branching_extend_vs_revoke_vs_expire
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    ba, ship, kdm = setup_kdm_issued_booking(
        did, env["film"]["id"], env["theatre"]["id"], env["screen"]["id"],
        valid_from_utc="2026-05-08T00:00:00Z",
        valid_until_utc="2026-05-15T00:00:00Z",
    )
    assert kdm["status"] == "ISSUED"

    validate_success(api.extend_kdm_key(
        did, ba["id"], kdm["id"], {"valid_until_utc": "2026-05-22T00:00:00Z"}, BOOKER
    ), 200)

    original = validate_success(api.get_kdm_key(did, ba["id"], kdm["id"], BOOKER), 200)
    assert original["status"] == "EXTENDED", (
        f"original key must move to EXTENDED, got {original['status']}"
    )

    keys = api.list_kdm_keys(did, ba["id"], BOOKER).json()["data"]
    superseding = [
        k for k in keys
        if k["id"] != kdm["id"] and k["status"] == "ISSUED"
    ]
    assert len(superseding) == 1, (
        f"expected exactly one superseding ISSUED key, got {len(superseding)}"
    )
    assert superseding[0]["valid_until_utc"].startswith("2026-05-22"), (
        f"superseding key must carry the new window; got {superseding[0]['valid_until_utc']}"
    )
    assert is_valid_uuid(superseding[0]["id"])


def test_revoke_branch_rolls_back_live_print_axis(api):
    """PRD §3.5: "Revoking a key — whether from `ISSUED` or `LIVE` — moves it to
    `REVOKED`, and if the print axis stood at `KEY_LIVE` it rolls back to
    `DCP_DELIVERED`"

    Design: Difficulty/non_linear_state_machine/kdm_key_branching_extend_vs_revoke_vs_expire
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    ba, ship, kdm = setup_kdm_issued_booking(
        did, env["film"]["id"], env["theatre"]["id"], env["screen"]["id"],
        valid_from_utc="2026-05-01T00:00:00Z",
        valid_until_utc="2026-07-31T00:00:00Z",
    )
    # Drive the clock past valid_from so the key goes LIVE and the print axis
    # advances to KEY_LIVE.
    _set_clock(api, "2026-05-01T00:00:01Z")
    live_key = validate_success(api.get_kdm_key(did, ba["id"], kdm["id"], BOOKER), 200)
    assert live_key["status"] == "LIVE", f"Setup failed: key is {live_key['status']}"
    live_ba = validate_success(api.get_booking_agreement(did, ba["id"], BOOKER), 200)
    assert live_ba["print_status"] == "KEY_LIVE", (
        f"Setup failed: print axis is {live_ba['print_status']}"
    )

    validate_success(api.revoke_kdm_key(did, ba["id"], kdm["id"], BOOKER), 200)

    revoked = validate_success(api.get_kdm_key(did, ba["id"], kdm["id"], BOOKER), 200)
    assert revoked["status"] == "REVOKED", f"expected REVOKED, got {revoked['status']}"
    rolled_back = validate_success(api.get_booking_agreement(did, ba["id"], BOOKER), 200)
    assert rolled_back["print_status"] == "DCP_DELIVERED", (
        f"print axis must roll back to DCP_DELIVERED, got {rolled_back['print_status']}"
    )


def test_expire_branch_is_passive_and_creates_no_new_key(api):
    """PRD §3.5: "when the clock reaches `valid_until_utc` the key becomes `EXPIRED` —
    the end boundary is exclusive, so at exactly that instant the key is no longer
    valid."

    Design: Difficulty/non_linear_state_machine/kdm_key_branching_extend_vs_revoke_vs_expire
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    ba, ship, kdm = setup_kdm_issued_booking(
        did, env["film"]["id"], env["theatre"]["id"], env["screen"]["id"],
        valid_from_utc="2026-05-01T00:00:00Z",
        valid_until_utc="2026-05-08T00:00:00Z",
    )
    _set_clock(api, "2026-05-02T00:00:00Z")
    live_key = validate_success(api.get_kdm_key(did, ba["id"], kdm["id"], BOOKER), 200)
    assert live_key["status"] == "LIVE", f"Setup failed: key is {live_key['status']}"
    keys_before = api.list_kdm_keys(did, ba["id"], BOOKER).json()["data"]

    _set_clock(api, "2026-05-08T00:00:00Z")

    expired = validate_success(api.get_kdm_key(did, ba["id"], kdm["id"], BOOKER), 200)
    assert expired["status"] == "EXPIRED", (
        f"at exactly valid_until the key must be EXPIRED, got {expired['status']}"
    )
    keys_after = api.list_kdm_keys(did, ba["id"], BOOKER).json()["data"]
    assert len(keys_after) == len(keys_before), (
        "expiry is passive: no superseding key may be created"
    )
