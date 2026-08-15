"""Revision rounds under the quality guarantee (PRD §3.7)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    get_success_data, ApiErrorId,
    make_client_agent_headers, make_photographer_headers, make_coordinator_headers,
    make_ops_admin_headers,
    create_market, create_photographer, create_agent, set_clock,
    create_shot_booking, get_booking, iso_plus,
)


def _delivered(api, order_ref="ORD-R", start="2026-08-05T14:00:00Z",
               mark="2026-08-05T14:30:00Z", deliver_at="2026-08-05T16:00:00Z",
               **booking_kw):
    """Booking delivered at `deliver_at`; returns (photog, agent, booking, bundle).

    `revision_window_closes_utc` is delivered_at + 72h per PRD §3.6, so the
    tests below expect 2026-08-08T16:00:00Z."""
    market = create_market(market_code="DEN", display_name="Denver",
                           pricing_multiplier_bps=10000, standard_turnaround_hours=48)
    photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                 equipment_packages=["STANDARD"])
    agent = create_agent(market["id"])
    booking = create_shot_booking(agent, photog, market["id"], mark,
                                  order_ref=order_ref,
                                  property_address="6 Rev Rd", equipment_package="STANDARD",
                                  photo_count=20, scheduled_start_utc=start, **booking_kw)
    set_clock(deliver_at)
    bundle = get_success_data(api_client.deliver(
        booking["id"], {"photo_asset_count": 20},
        make_photographer_headers(photog["id"])))
    return photog, agent, get_booking(booking["id"]), bundle


def _open_and_redeliver(api, booking_id, bundle_id, agent, photog, notes):
    """Open one revision round and close it with a redelivery. Returns (revision, new_bundle)."""
    rev = get_success_data(api_client.create_revision(
        booking_id, bundle_id, notes, make_client_agent_headers(agent["id"])))
    new_bundle = get_success_data(api_client.deliver(
        booking_id, {"photo_asset_count": 20}, make_photographer_headers(photog["id"])))
    return rev, new_bundle


class TestRevisionCycle:
    def test_delivered_redelivered_cycle_twice_then_paid(self, api):
        """PRD §3.7: "While `revisions_used` is still below the free quota of two, the
        new `RevisionRequest` is stamped `is_free` true with `fee_cents` zero; from the
        third round onward `is_free` is false and `fee_cents` resolves to 7500 cents
        multiplied by the market factor, rounded half-up to whole cents."
        PRD §3.7: "Redelivery moves the prior bundle from `DELIVERED` to `SUPERSEDED`,
        creates a fresh bundle whose `round_number` is one greater than its
        predecessor's ... Crucially, redelivery does not extend
        `revision_window_closes_utc`: the window is fixed from the first delivery ..."

        Design: Difficulty/non_linear_state_machine/shootbooking_revision_cycle_delivered_to_redelivered
        """
        set_clock()
        photog, agent, booking, bundle1 = _delivered(api, order_ref="ORD-CYC")
        headers = make_client_agent_headers(agent["id"])
        assert booking["revision_window_closes_utc"] == "2026-08-08T16:00:00Z"

        # round 1 (free): open, claim, redeliver
        rev1 = get_success_data(api_client.create_revision(
            booking["id"], bundle1["id"], "brighten kitchen", headers))
        assert rev1["is_free"] is True and rev1["fee_cents"] == 0
        assert get_booking(booking["id"])["state"] == "REVISION_REQUESTED"
        get_success_data(api_client.claim_revision(
            booking["id"], rev1["id"], make_photographer_headers(photog["id"])))
        bundle2 = get_success_data(api_client.deliver(
            booking["id"], {"photo_asset_count": 20}, make_photographer_headers(photog["id"])))
        assert get_booking(booking["id"])["state"] == "DELIVERED"

        # round 2 (free)
        rev2 = get_success_data(api_client.create_revision(
            booking["id"], bundle2["id"], "straighten verticals", headers))
        assert rev2["is_free"] is True and rev2["fee_cents"] == 0
        bundle3 = get_success_data(api_client.deliver(
            booking["id"], {"photo_asset_count": 20}, make_photographer_headers(photog["id"])))

        # round 3 (paid at 1.0x market factor)
        rev3 = get_success_data(api_client.create_revision(
            booking["id"], bundle3["id"], "sky swap", headers))
        assert rev3["is_free"] is False and rev3["fee_cents"] == 7500

        after = get_booking(booking["id"])
        assert after["revisions_used"] == 3
        assert after["state"] == "REVISION_REQUESTED"
        # window frozen from the first delivery — never extended by redeliveries
        assert after["revision_window_closes_utc"] == "2026-08-08T16:00:00Z"

        b1 = get_success_data(api_client.get_bundle(booking["id"], bundle1["id"], headers))
        b2 = get_success_data(api_client.get_bundle(booking["id"], bundle2["id"], headers))
        b3 = get_success_data(api_client.get_bundle(booking["id"], bundle3["id"], headers))
        assert b1["state"] == "SUPERSEDED"
        assert b2["state"] == "SUPERSEDED"
        assert b3["round_number"] == 3


    def test_redelivery_supersedes_and_resolves_without_extending_window(self, api):
        """PRD §3.7: "Redelivery moves the prior bundle from `DELIVERED` to
        `SUPERSEDED`, creates a fresh bundle whose `round_number` is one greater than
        its predecessor's, delivers that new bundle, and resolves the prior bundle's
        revisions to `RESOLVED`. Crucially, redelivery does not extend
        `revision_window_closes_utc`: the window is fixed from the first delivery, so
        late rounds can never be bought back by re-delivering."

        Design: Difficulty/non_linear_state_machine/shootbooking_revision_cycle_delivered_to_redelivered
        """
        set_clock()
        photog, agent, booking, bundle1 = _delivered(api, order_ref="ORD-CYC2")
        headers = make_client_agent_headers(agent["id"])
        window = booking["revision_window_closes_utc"]

        rev = get_success_data(api_client.create_revision(
            booking["id"], bundle1["id"], "crop tighter", headers))
        assert get_booking(booking["id"])["state"] == "REVISION_REQUESTED"

        bundle2 = get_success_data(api_client.deliver(
            booking["id"], {"photo_asset_count": 20}, make_photographer_headers(photog["id"])))
        assert bundle2["round_number"] == 2

        rev_after = get_success_data(api_client.get_revision(booking["id"], rev["id"], headers))
        assert rev_after["state"] == "RESOLVED"
        bundle1_after = get_success_data(api_client.get_bundle(booking["id"], bundle1["id"], headers))
        assert bundle1_after["state"] == "SUPERSEDED"

        after = get_booking(booking["id"])
        assert after["state"] == "DELIVERED"
        assert after["revision_window_closes_utc"] == window  # fixed from first delivery


class TestRevisionWindowBoundary:
    def test_strictly_before_72h_boundary(self, api):
        """PRD §3.7: "requires the current moment to fall strictly before
        `revision_window_closes_utc` — a request at or after that instant is too late
        and fails with `ERR_REVISION_WINDOW_CLOSED` (HTTP 422) ..."

        Design: Difficulty/boundary_precision_check/revision_window_strictly_before_72h_boundary
        """
        set_clock()
        photog, agent, booking, bundle1 = _delivered(api, order_ref="ORD-BND1")
        headers = make_client_agent_headers(agent["id"])
        # first delivery at 2026-08-05T16:00:00Z -> window closes 2026-08-08T16:00:00Z
        assert booking["revision_window_closes_utc"] == "2026-08-08T16:00:00Z"

        # one second before the close: accepted
        set_clock("2026-08-08T15:59:59Z")
        rev_ok = get_success_data(api_client.create_revision(
            booking["id"], bundle1["id"], "inside window", headers))
        assert rev_ok["state"] == "OPEN"
        # photographer resolves it so the machine returns to DELIVERED for the probe
        bundle2 = get_success_data(api_client.deliver(
            booking["id"], {"photo_asset_count": 20}, make_photographer_headers(photog["id"])))

        # at exactly the closing instant: strictly-before violated
        set_clock("2026-08-08T16:00:00Z")
        resp = api_client.create_revision(booking["id"], bundle2["id"],
                                          "at exact boundary", headers)
        validate_error(resp, ApiErrorId.ERR_REVISION_WINDOW_CLOSED)
        # the failed attempt did not consume a round
        assert get_booking(booking["id"])["revisions_used"] == 1


    def test_open_one_second_before_close_counts_as_free(self, api):
        """PRD §3.7: "requires the current moment to fall strictly before
        `revision_window_closes_utc` — a request at or after that instant is too late
        and fails with `ERR_REVISION_WINDOW_CLOSED` (HTTP 422) ..."
        PRD §3.7: "While `revisions_used` is still below the free quota of two, the
        new `RevisionRequest` is stamped `is_free` true with `fee_cents` zero ..."

        The strictly-before rule decides success at T+71:59:59, and the free-quota
        rule prices that same on-the-boundary open at zero cents.

        Design: Difficulty/boundary_precision_check/revision_window_strictly_before_72h_boundary
        """
        set_clock()
        photog, agent, booking, bundle1 = _delivered(api, order_ref="ORD-BND2")
        headers = make_client_agent_headers(agent["id"])
        assert booking["revision_window_closes_utc"] == "2026-08-08T16:00:00Z"

        set_clock("2026-08-08T15:59:59Z")  # one second inside the window
        rev = get_success_data(api_client.create_revision(
            booking["id"], bundle1["id"], "last-second change", headers))
        assert rev["state"] == "OPEN"
        assert rev["is_free"] is True
        assert rev["fee_cents"] == 0
        assert get_booking(booking["id"])["revisions_used"] == 1


class TestRevisionCapsAndStates:
    def test_revision_limit_reached_at_four(self, api):
        """PRD §3.7: "requires `revisions_used` to still be below the hard cap of four
        consumed rounds, that is two free plus two paid (otherwise
        `ERR_REVISION_LIMIT_REACHED`, HTTP 409)."

        Design: Corner/state_machines/revision_limit_reached_at_four
        """
        set_clock()
        photog, agent, booking, bundle = _delivered(api, order_ref="ORD-RLIM")
        headers = make_client_agent_headers(agent["id"])

        for n in range(1, 5):
            _, bundle = _open_and_redeliver(api, booking["id"], bundle["id"],
                                            agent, photog, f"r{n}")
        assert get_booking(booking["id"])["revisions_used"] == 4

        resp = api_client.create_revision(booking["id"], bundle["id"], "r5 over cap", headers)
        validate_error(resp, ApiErrorId.ERR_REVISION_LIMIT_REACHED)
        after = get_booking(booking["id"])
        assert after["revisions_used"] == 4
        assert after["state"] == "DELIVERED"

    def test_accept_blocked_with_open_revision(self, api):
        """PRD §3.8: "it is blocked while any revision on the booking sits in `OPEN` or
        `IN_PROGRESS` (otherwise `ERR_OPEN_REVISIONS_EXIST`, HTTP 409) ..."
        PRD §3.7: "Redelivery moves the prior bundle from `DELIVERED` to `SUPERSEDED`
        ... and resolves the prior bundle's revisions to `RESOLVED`."

        Design: Corner/state_machines/accept_blocked_with_open_revision
        """
        set_clock()
        photog, agent, booking, bundle = _delivered(api, order_ref="ORD-OPEN")
        headers = make_client_agent_headers(agent["id"])
        get_success_data(api_client.create_revision(
            booking["id"], bundle["id"], "fix shadows", headers))

        # After create_revision, the booking is REVISION_REQUESTED (not DELIVERED),
        # so §2.8 tier-4 state legality would report ERR_BOOKING_NOT_DELIVERED,
        # while §3.8 names ERR_OPEN_REVISIONS_EXIST as the open-revision gate.
        # The PRD does not pin which check pre-empts the other; accept either.
        resp = api_client.accept_booking(booking["id"], headers)
        validate_error_is_one_of(resp, [ApiErrorId.ERR_OPEN_REVISIONS_EXIST,
                                        ApiErrorId.ERR_BOOKING_NOT_DELIVERED])

        # redelivery resolves the open revision; acceptance then succeeds
        get_success_data(api_client.deliver(
            booking["id"], {"photo_asset_count": 20}, make_photographer_headers(photog["id"])))
        accepted = validate_success(api_client.accept_booking(booking["id"], headers))
        assert accepted["state"] == "ACCEPTED"

    def test_revision_claim_requires_open(self, api):
        """PRD §3.7: "claiming requires the revision to be `OPEN` (otherwise
        `ERR_REVISION_NOT_OPEN`) ..."

        Design: Corner/errors/error_revision_claim_requires_open
        """
        set_clock()
        photog, agent, booking, bundle = _delivered(api, order_ref="ORD-CLM")
        headers = make_client_agent_headers(agent["id"])
        rev = get_success_data(api_client.create_revision(
            booking["id"], bundle["id"], "r1", headers))
        photog_headers = make_photographer_headers(photog["id"])
        get_success_data(api_client.claim_revision(booking["id"], rev["id"], photog_headers))

        # second claim: the revision is IN_PROGRESS, not OPEN
        resp = api_client.claim_revision(booking["id"], rev["id"], photog_headers)
        validate_error(resp, ApiErrorId.ERR_REVISION_NOT_OPEN)
