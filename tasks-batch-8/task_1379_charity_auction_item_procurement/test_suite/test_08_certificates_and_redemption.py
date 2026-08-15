"""Certificates: the closed redemption bound at expiry, the expiry sweep,
half-open blackout intersection, closed containment inside the grace
window, and the containment-before-blackout check order."""
from test_helpers import (
    ADMIN,
    CM,
    ApiErrorId,
    advance_event,
    api_client,
    close_bidding,
    create_bidder,
    create_blackout_window_payload,
    create_event,
    get_certificate_for_invoice,
    get_invoice_for_bundle,
    get_success_data,
    make_bidder_headers,
    pay_invoice_in_full,
    place_bid,
    setup_paid_scenario,
    setup_published_bundle,
    setup_two_issued_certificates,
    setup_valued_item,
    validate_error,
    validate_success,
)


def _redeem(cert_id, bidder_id, start, end):
    return api_client.redeem_certificate(
        cert_id, {"scheduled_start": start, "scheduled_end": end},
        make_bidder_headers(bidder_id))


class TestRedeemExactlyAtExpiry:

    def test_redeem_exactly_at_expiry_succeeds(self):
        """PRD section 3.8: "Redemption remains legal while the current
        instant is at or before `expires_at`; the bound is closed, so a
        redemption at exactly `expires_at` succeeds." PRD section 2.5:
        "A certificate whose `expires_at` equals the new current instant
        survives the sweep, because redemption remains legal at exactly
        that instant."

        Design: Difficulty/boundary_precision_check/certificate_redeem_exactly_at_expiry
        """
        ctx = setup_two_issued_certificates()
        cert_a = ctx["cert_a"]
        assert cert_a["certificate"]["expires_at"] == "2027-08-01T00:00:00Z"

        # now == expires_at exactly: sweep does not fire (bound is strict
        # the other way), and redemption is still legal.
        validate_success(api_client.set_clock(
            {"to_iso8601": "2027-08-01T00:00:00Z"}, ADMIN))
        resp = _redeem(cert_a["certificate"]["id"],
                       cert_a["bidder"]["id"],
                       "2027-07-20T00:00:00Z", "2027-07-25T00:00:00Z")
        cert = validate_success(resp)
        assert cert["status"] == "REDEEMED", "closed bound"

    def test_redeem_one_second_after_expiry_rejected(self):
        """PRD section 2.5: "Setting the clock also runs the certificate
        expiry sweep: every certificate still `ISSUED` whose `expires_at`
        is strictly earlier than the new current instant transitions to
        `EXPIRED`". PRD section 3.8: "The certificate must be `ISSUED`;
        any other status — including a certificate the expiry sweep has
        already moved to `EXPIRED` — is rejected with
        `ERR_CERTIFICATE_NOT_REDEEMABLE`."

        Design: Difficulty/boundary_precision_check/certificate_redeem_exactly_at_expiry
        """
        ctx = setup_two_issued_certificates()
        cert_b = ctx["cert_b"]

        validate_success(api_client.set_clock(
            {"to_iso8601": "2027-08-01T00:00:01Z"}, ADMIN))
        swept = get_success_data(
            api_client.get_certificate(cert_b["certificate"]["id"], ADMIN))
        assert swept["status"] == "EXPIRED", \
            "one second past expiry the sweep has fired"

        resp = _redeem(cert_b["certificate"]["id"], cert_b["bidder"]["id"],
                       "2027-07-20T00:00:00Z", "2027-07-25T00:00:00Z")
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_NOT_REDEEMABLE)


class TestBlackoutHalfOpenIntersection:

    def test_redemption_adjacent_to_blackout_allowed(self):
        """PRD section 3.8: "the scheduled window must not intersect any
        blackout window of any `EXPERIENCE` member item of the bundle;
        intersection is tested on half-open intervals, so a window that
        merely touches a blackout's edge — adjacency — is allowed, while
        a true overlap is rejected with `ERR_BLACKOUT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/blackout_half_open_intersection
        """
        ctx = setup_two_issued_certificates(blackouts=True)
        cert_a = ctx["cert_a"]
        # Window [2027-08-01, 2027-08-05) ends exactly at the blackout
        # start 2027-08-05: adjacent, not intersecting.
        resp = _redeem(cert_a["certificate"]["id"], cert_a["bidder"]["id"],
                       "2027-08-01T00:00:00Z", "2027-08-05T00:00:00Z")
        cert = validate_success(resp)
        assert cert["status"] == "REDEEMED"
        assert cert["scheduled_start"] == "2027-08-01T00:00:00Z"
        assert cert["scheduled_end"] == "2027-08-05T00:00:00Z"

    def test_redemption_overlapping_blackout_rejected(self):
        """PRD section 3.8: "while a true overlap is rejected with
        `ERR_BLACKOUT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/blackout_half_open_intersection
        """
        ctx = setup_two_issued_certificates(blackouts=True)
        cert_b = ctx["cert_b"]
        # Window [2027-08-01, 2027-08-06) overlaps the blackout
        # [2027-08-05, 2027-08-12) by one day.
        resp = _redeem(cert_b["certificate"]["id"], cert_b["bidder"]["id"],
                       "2027-08-01T00:00:00Z", "2027-08-06T00:00:00Z")
        validate_error(resp, ApiErrorId.ERR_BLACKOUT_CONFLICT)


class TestRedemptionClosedContainment:

    def test_redemption_end_at_grace_end_allowed(self):
        """PRD section 3.8: "the window must sit inside containment
        bounds: `valid_from` at or before `scheduled_start`,
        `scheduled_start` strictly earlier than `scheduled_end`, and
        `scheduled_end` at or before `grace_end_at` — a `scheduled_end`
        exactly equal to `grace_end_at` is allowed."

        Design: Difficulty/resource_temporal_overlap/redemption_closed_containment_with_grace
        """
        ctx = setup_two_issued_certificates()
        cert_a = ctx["cert_a"]
        assert cert_a["certificate"]["grace_end_at"] == \
            "2027-08-31T00:00:00Z"
        resp = _redeem(cert_a["certificate"]["id"], cert_a["bidder"]["id"],
                       "2027-08-20T00:00:00Z", "2027-08-31T00:00:00Z")
        cert = validate_success(resp)
        assert cert["status"] == "REDEEMED", "closed containment"

    def test_redemption_end_past_grace_rejected(self):
        """PRD section 3.8: "Any breach of containment is rejected with
        `ERR_REDEMPTION_WINDOW_INVALID`."

        Design: Difficulty/resource_temporal_overlap/redemption_closed_containment_with_grace
        """
        ctx = setup_two_issued_certificates()
        cert_b = ctx["cert_b"]
        resp = _redeem(cert_b["certificate"]["id"], cert_b["bidder"]["id"],
                       "2027-08-20T00:00:00Z", "2027-09-01T00:00:00Z")
        validate_error(resp, ApiErrorId.ERR_REDEMPTION_WINDOW_INVALID)


class TestTemporalBeatsConstraint:

    def _paid_cert_with_blackout(self):
        """One EXPERIENCE bundle sold and fully paid at the default
        clock; the blackout [2027-08-05, 2027-08-12) is registered on the
        item before the catalog opens. Certificate ISSUED with grace_end
        2027-08-31."""
        event = create_event()
        advance_event(event["id"])  # SOLICITING
        part = setup_valued_item(event["id"], 40000, kind="EXPERIENCE",
                                 title="Villa weekend")
        validate_success(api_client.create_blackout_window(
            part["item"]["id"], create_blackout_window_payload(), CM),
            expected_status=201)
        advance_event(event["id"])  # CATALOGING
        bundle = setup_published_bundle(event["id"], [part["item"]["id"]],
                                        title="Villa")
        advance_event(event["id"])  # BIDDING_OPEN
        bidder = create_bidder(event["id"])
        place_bid(bundle["id"], 50000, bidder["id"])
        close_bidding(event["id"])
        invoice = get_invoice_for_bundle(bundle["id"])
        pay_invoice_in_full(invoice, bidder["id"])
        cert = get_certificate_for_invoice(invoice["id"])
        return {"event": event, "bundle": bundle, "bidder": bidder,
                "invoice": invoice}, cert

    def test_dual_violation_reports_window_invalid(self):
        """PRD section 2.8: "Every request is evaluated against a single
        ordered cascade of checks; a failure at any step short-circuits
        the rest, so the error a client receives identifies the earliest
        failing category." PRD section 2.8: "the scheduled experience
        window sits inside the certificate's validity and grace bounds;
        otherwise `ERR_REDEMPTION_WINDOW_INVALID` (HTTP 422)." (step 14,
        ahead of the step-15 blackout check)

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_redeem
        """
        ctx, cert = self._paid_cert_with_blackout()
        # [2027-08-06, 2027-09-05] both exceeds grace_end (2027-08-31)
        # AND overlaps the blackout [2027-08-05, 2027-08-12).
        resp = _redeem(cert["id"], ctx["bidder"]["id"],
                       "2027-08-06T00:00:00Z", "2027-09-05T00:00:00Z")
        validate_error(resp, ApiErrorId.ERR_REDEMPTION_WINDOW_INVALID)

    def test_blackout_conflict_when_containment_passes(self):
        """PRD section 2.8: "the scheduled window does not intersect any
        member experience item's blackout window; otherwise
        `ERR_BLACKOUT_CONFLICT` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_redeem
        """
        ctx, cert = self._paid_cert_with_blackout()
        # [2027-08-06, 2027-08-10] sits inside the containment bounds but
        # overlaps the blackout: only the blackout check can fail.
        resp = _redeem(cert["id"], ctx["bidder"]["id"],
                       "2027-08-06T00:00:00Z", "2027-08-10T00:00:00Z")
        validate_error(resp, ApiErrorId.ERR_BLACKOUT_CONFLICT)


class TestRedeemTwice:

    def test_certificate_redeem_twice_rejected(self):
        """PRD section 3.8: "The certificate must be `ISSUED`; any other
        status — including a certificate the expiry sweep has already
        moved to `EXPIRED` — is rejected with
        `ERR_CERTIFICATE_NOT_REDEEMABLE`."

        Design: Corner/state_machines/certificate_redeem_twice_rejected
        """
        ctx = setup_paid_scenario(fmv_cents=40000, bid_amount=50000,
                                  kind="EXPERIENCE")
        cert = get_certificate_for_invoice(ctx["invoice"]["id"])
        first = _redeem(cert["id"], ctx["bidder"]["id"],
                        "2027-01-10T00:00:00Z", "2027-01-12T00:00:00Z")
        validate_success(first)

        second = _redeem(cert["id"], ctx["bidder"]["id"],
                         "2027-02-10T00:00:00Z", "2027-02-12T00:00:00Z")
        validate_error(second, ApiErrorId.ERR_CERTIFICATE_NOT_REDEEMABLE)
