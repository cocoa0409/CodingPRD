"""Error guard coverage: theatre status, wide-release gate, terminal decline
(PRD §3.2, §3.3)."""
from test_helpers import (
    validate_success,
    validate_error,
    setup_distributor,
    setup_film,
    setup_distributor_film_theatre_screen,
    setup_proposed_booking,
    setup_accepted_booking,
    setup_completed_booking,
    setup_screen,
    setup_theatre,
    ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOOKER = TEST_USERS["booker_headers"]
EXHIBITOR = TEST_USERS["exhibitor_headers"]


def test_accept_rejected_when_theatre_suspended(api):
    """PRD §3.3: "Acceptance re-checks the full guard set — distributor posture, film
    bookability, the theatre being `ACTIVE` (`ERR_THEATRE_INACTIVE`), the screen still
    `AVAILABLE`, the zone-clearance check, and the stale-version check."
    PRD §3.1: "a `PlatformAdmin` may suspend it, moving it to `SUSPENDED`, which blocks
    new bookings from being accepted at that theatre until it is restored".

    Design: Corner/errors/err_theatre_inactive_on_accept
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    tid = env["theatre"]["id"]
    ba = setup_proposed_booking(did, env["film"]["id"], tid, env["screen"]["id"])

    theatre = validate_success(api.suspend_theatre(did, tid, ADMIN), 200)
    assert theatre["status"] == "SUSPENDED", f"Setup failed: {theatre['status']}"

    res = api.accept_booking_agreement(
        did, ba["id"], {"expected_booking_agreement_version": ba["version"]}, EXHIBITOR
    )
    validate_error(res, ApiErrorId.ERR_THEATRE_INACTIVE)


def test_wide_release_gate_rejects_insufficient_screens(api):
    """PRD §3.2: "For a `WIDE` picture, the gate is met when `screens_committed` is at
    least `min_screens_for_wide` — equality meets the gate — and an attempt below the
    threshold is rejected with `ERR_WIDE_GATE_NOT_MET`."
    min_screens_for_wide=5 with one accepted agreement (screens_committed=1) -> 409.

    Design: Corner/errors/err_wide_gate_not_met
    """
    distributor = setup_distributor()
    did = distributor["id"]
    film = setup_film(
        did, release_pattern="WIDE", min_screens_for_wide=5,
        target_release_date="2026-05-08T00:00:00Z",
    )
    theatre = setup_theatre(did)
    screen = setup_screen(did, theatre["id"])
    setup_accepted_booking(did, film["id"], theatre["id"], screen["id"])

    film_now = validate_success(api.get_film(did, film["id"], BOOKER), 200)
    assert film_now["screens_committed"] == 1, (
        f"Setup failed: screens_committed={film_now['screens_committed']}"
    )

    res = api.open_release(
        did, film["id"], {"expected_film_version": film_now["version"]}, BOOKER
    )
    validate_error(res, ApiErrorId.ERR_WIDE_GATE_NOT_MET)


def test_decline_completed_agreement_returns_invalid_state(api):
    """PRD §3.3: "Declining is the one-way door: the `Exhibitor` declines from
    `PROPOSED`, the `Booker` declines from `COUNTERED`, and the agreement lands in
    terminal `DECLINED`." — no decline transition exists from COMPLETED.
    PRD §2.11: "5. State-machine validity — the resource is in a state from which the
    requested transition exists (`ERR_INVALID_STATE`)."

    Design: Corner/errors/err_invalid_state_already_terminal_decline
    """
    env = setup_completed_booking()
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    assert env["booking"]["deal_status"] == "COMPLETED"

    res = api.decline_booking_agreement(did, baid, EXHIBITOR)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_booking_agreement(did, baid, BOOKER), 200)
    assert after["deal_status"] == "COMPLETED"
