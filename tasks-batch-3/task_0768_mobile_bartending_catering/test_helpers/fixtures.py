"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test), so these helpers build all preconditions from scratch using
only PRD-declared endpoints. Setup calls use get_success_data() (lenient) so a
broken precondition surfaces as a clear "Setup failed".

Identity threading: the Client and Bartender roles are entity_backed, so any
ownership-gated call uses make_client_headers(client["id"]) /
make_bartender_headers(bartender["id"]) — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_client_headers, make_bartender_headers
from . import factories as F

ADMIN = TEST_USERS["platform_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 0 — single-entity creators
# ---------------------------------------------------------------------------
def create_client(api=api_client, **overrides) -> dict:
    resp = api.create_client(F.create_client_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_package(api=api_client, **overrides) -> dict:
    resp = api.create_package(F.create_package_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_bartender(api=api_client, **overrides) -> dict:
    resp = api.create_bartender(F.create_bartender_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_bar_kit(api=api_client, **overrides) -> dict:
    resp = api.create_bar_kit(F.create_bar_kit_payload(**overrides), ADMIN)
    return get_success_data(resp)


def get_event(api, event_id) -> dict:
    """Read an event via the (shared) Coordinator role."""
    return get_success_data(api.get_event(event_id, COORD))


def event_version(api, event_id) -> int:
    return get_event(api, event_id)["version"]


# ---------------------------------------------------------------------------
# Tier 1 — event in a target booking state
# ---------------------------------------------------------------------------
def create_draft_event(api=api_client, package_overrides=None, **event_overrides) -> dict:
    """Client + Package + a DRAFT event. Returns a bundle dict."""
    client = create_client(api)
    package = create_package(api, **(package_overrides or {}))
    client_headers = make_client_headers(client["id"])
    resp = api.create_event(
        F.create_event_payload(client["id"], package["id"], **event_overrides),
        client_headers,
    )
    event = get_success_data(resp)
    return {
        "client": client,
        "package": package,
        "event": event,
        "client_headers": client_headers,
    }


def open_and_clear_compliance(api, event_id, review_overrides=None) -> dict:
    """Open a review, submit it, and clear it. Returns the cleared review."""
    review = get_success_data(
        api.create_compliance_review(
            event_id, F.create_compliance_review_payload(**(review_overrides or {})), COORD
        )
    )
    get_success_data(api.submit_review(review["id"], {}, COORD))
    get_success_data(api.clear_review(review["id"], {}, OFFICER))
    return review


def create_cleared_event(api=api_client, package_overrides=None, **event_overrides) -> dict:
    """DRAFT event whose compliance_posture has been lifted to CLEARED."""
    bundle = create_draft_event(api, package_overrides=package_overrides, **event_overrides)
    bundle["review"] = open_and_clear_compliance(api, bundle["event"]["id"])
    bundle["event"] = get_event(api, bundle["event"]["id"])
    return bundle


def pay_full_deposit(api, event_id, client_headers) -> dict:
    """Pay exactly the event's deposit_due_cents as a DEPOSIT."""
    ev = get_event(api, event_id)
    deposit = ev["deposit_due_cents"]
    return get_success_data(
        api.create_payment(event_id, F.create_payment_payload("DEPOSIT", deposit), client_headers)
    )


def create_confirmed_event(api=api_client, package_overrides=None, **event_overrides) -> dict:
    """CLEARED + deposit paid + CONFIRMED event."""
    bundle = create_cleared_event(api, package_overrides=package_overrides, **event_overrides)
    ev_id = bundle["event"]["id"]
    pay_full_deposit(api, ev_id, bundle["client_headers"])
    get_success_data(api.confirm_event(ev_id, bundle["client_headers"]))
    bundle["event"] = get_event(api, ev_id)
    return bundle


# ---------------------------------------------------------------------------
# Tier 2 — assignments
# ---------------------------------------------------------------------------
def add_assignment(api, event_id, bartender_id, role_on_event="BACK",
                   shift_start="2026-06-01T17:00:00Z", shift_end="2026-06-01T23:30:00Z",
                   expected_event_version=None) -> dict:
    """Create a PROPOSED assignment (Coordinator). Reads current event version
    when one is not supplied."""
    if expected_event_version is None:
        expected_event_version = event_version(api, event_id)
    payload = F.create_assignment_payload(
        bartender_id, expected_event_version,
        role_on_event=role_on_event, shift_start=shift_start, shift_end=shift_end,
    )
    return get_success_data(api.create_assignment(event_id, payload, COORD))


def add_confirmed_assignment(api, event_id, bartender_id, role_on_event="LEAD", **kwargs) -> dict:
    """Create + confirm an assignment (requires posture CLEARED)."""
    asg = add_assignment(api, event_id, bartender_id, role_on_event=role_on_event, **kwargs)
    return get_success_data(api.confirm_assignment(asg["id"], COORD))


def add_checked_in_assignment(api, event_id, bartender_id, bartender_headers,
                              role_on_event="LEAD", **kwargs) -> dict:
    """Create + confirm + check-in an assignment (check-in as the owning bartender)."""
    asg = add_confirmed_assignment(api, event_id, bartender_id, role_on_event=role_on_event, **kwargs)
    return get_success_data(api.checkin_assignment(asg["id"], bartender_headers))


# ---------------------------------------------------------------------------
# Tier 3 — in-progress event with a LEAD checked in, and returned-kit scenario
# ---------------------------------------------------------------------------
def create_in_progress_event(api=api_client, package_overrides=None,
                             bartender_overrides=None, **event_overrides) -> dict:
    """Full path to booking_status == IN_PROGRESS.

    Confirmed event + one LEAD assignment (confirmed + checked in) + start.
    Returns a bundle with bartender, bartender_headers and the LEAD assignment.
    """
    bundle = create_confirmed_event(api, package_overrides=package_overrides, **event_overrides)
    ev_id = bundle["event"]["id"]
    bartender = create_bartender(api, **(bartender_overrides or {}))
    bartender_headers = make_bartender_headers(bartender["id"])
    asg = add_checked_in_assignment(
        api, ev_id, bartender["id"], bartender_headers, role_on_event="LEAD",
    )
    get_success_data(api.start_event(ev_id, COORD))
    bundle["bartender"] = bartender
    bundle["bartender_headers"] = bartender_headers
    bundle["assignment"] = asg
    bundle["event"] = get_event(api, ev_id)
    return bundle


def setup_returned_kit(api=api_client, glassware_count=200, **event_overrides) -> dict:
    """In-progress event with a bar kit reserved, deployed, and RETURNED.

    Returns the in-progress bundle plus kit, reservation (RETURNED) and its
    items_checked_out baseline. Used by breakage-report tests.
    """
    bundle = create_in_progress_event(api, **event_overrides)
    ev_id = bundle["event"]["id"]
    kit = create_bar_kit(api, glassware_count=glassware_count)
    resv = get_success_data(
        api.create_kit_reservation(
            ev_id,
            F.create_kit_reservation_payload(
                kit["id"], reserve_start="2026-06-01T16:00:00Z", reserve_end="2026-06-02T00:00:00Z",
            ),
            COORD,
        )
    )
    resv = get_success_data(api.deploy_kit_reservation(resv["id"], COORD))
    resv = get_success_data(api.return_kit_reservation(resv["id"], COORD))
    bundle["kit"] = kit
    bundle["reservation"] = resv
    return bundle


def setup_deployed_kit(api=api_client, glassware_count=200, **event_overrides) -> dict:
    """In-progress event with a bar kit reserved and DEPLOYED (not returned)."""
    bundle = create_in_progress_event(api, **event_overrides)
    ev_id = bundle["event"]["id"]
    kit = create_bar_kit(api, glassware_count=glassware_count)
    resv = get_success_data(
        api.create_kit_reservation(
            ev_id, F.create_kit_reservation_payload(kit["id"]), COORD,
        )
    )
    resv = get_success_data(api.deploy_kit_reservation(resv["id"], COORD))
    bundle["kit"] = kit
    bundle["reservation"] = resv
    return bundle


# ---------------------------------------------------------------------------
# Tier 4 — reliability targeting
# ---------------------------------------------------------------------------
def setup_reliability_no_show_and_cancel(api=api_client) -> dict:
    """Build a bartender history of exactly one NO_SHOW + one bartender-CANCEL
    on a single cleared event (two non-overlapping shifts).

    After the chain: completed=0, no_shows=1, cancels(BARTENDER)=1, total=2.
    Returns {"bartender": <re-read bartender dict>, "bartender_headers": ...}.
    """
    bundle = create_cleared_event(api)
    ev_id = bundle["event"]["id"]
    bartender = create_bartender(api)
    b_headers = make_bartender_headers(bartender["id"])
    # Assignment 1: confirm then no-show.
    asg1 = add_confirmed_assignment(
        api, ev_id, bartender["id"], role_on_event="BACK",
        shift_start="2026-06-01T17:00:00Z", shift_end="2026-06-01T19:00:00Z",
    )
    get_success_data(api.no_show_assignment(asg1["id"], COORD))
    # Assignment 2: create then cancel as the owning bartender.
    asg2 = add_assignment(
        api, ev_id, bartender["id"], role_on_event="BACK",
        shift_start="2026-06-01T21:00:00Z", shift_end="2026-06-01T23:00:00Z",
    )
    get_success_data(api.cancel_assignment(asg2["id"], b_headers))
    return {
        "bartender": get_success_data(api.get_bartender(bartender["id"], COORD)),
        "bartender_headers": b_headers,
    }


def make_bartender_with_one_no_show(api=api_client) -> dict:
    """Create a bartender, confirm one assignment on a cleared event, then
    no-show it so reliability_score_strict == 0 (LEAD-ineligible).

    Returns {"bartender": ..., "bartender_headers": ...}.
    """
    bundle = create_cleared_event(api)
    ev_id = bundle["event"]["id"]
    bartender = create_bartender(api)
    asg = add_confirmed_assignment(
        api, ev_id, bartender["id"], role_on_event="BACK",
        shift_start="2026-06-01T17:00:00Z", shift_end="2026-06-01T20:00:00Z",
    )
    get_success_data(api.no_show_assignment(asg["id"], COORD))
    return {
        "bartender": bartender,
        "bartender_headers": make_bartender_headers(bartender["id"]),
    }
