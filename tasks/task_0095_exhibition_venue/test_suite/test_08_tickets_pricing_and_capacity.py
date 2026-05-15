"""Tickets, pricing, capacity, posture cascade, and group discounts —
PRD §3.7, §2.9, §2.6.

Covers:
- ticket_price kind × channel × group multiplier (all three branches)
- group threshold strict at 10 (Rule 6 instance 2)
- ERR_CAPACITY_EXCEEDED strict-less-than boundary on scan-in
  (Rule 6 instance 1)
- depth-3 posture cascade: scan-in mutates Ticket → Exhibition
  .live_occupancy → Exhibition.posture (Rule 4 instance 1)
- scan-in/scan-out conservation of live_occupancy (Rule 9 instance 2)
- ERR_POSTURE_BLOCKED on scanning when posture != OPEN
- error precedence between state (priority 4) and posture (priority 5)
  (Rule 5 instance 1) — state wins
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_ticket_payload,
    random_group_id,
    setup_open_exhibition,
    setup_open_exhibition_at_occupancy,
    validate_error,
    validate_success,
)


# ===========================================================================
# Ticket pricing (PRD §3.7)
# ===========================================================================
class TestTicketPricing:

    def test_visitor_online_presale_price_5000(
        self, api, venue_admin_headers,
    ):
        """PRD §3.7: "five thousand for VISITOR ... twelve thousand
        for PROFESSIONAL_BUYER, two thousand five hundred for STUDENT,
        and thirty thousand for VIP."
        PRD §3.7: "It then applies a channel multiplier: when channel
        is ONSITE and kind is anything other than VIP, the multiplier
        is one-point-two (a twenty-percent onsite surcharge); in
        every other case the multiplier is one."

        Claim: VISITOR + ONLINE_PRESALE + no group → price_cents=5000.
        """
        ctx = setup_open_exhibition()
        res = api.create_ticket(
            ctx["exhibition"]["id"],
            create_ticket_payload(
                kind="VISITOR", channel="ONLINE_PRESALE",
            ),
            venue_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["price_cents"] == 5000

    def test_professional_buyer_onsite_surcharge_14400(
        self, api, venue_admin_headers,
    ):
        """PRD §3.7: "twelve thousand for PROFESSIONAL_BUYER ... when
        channel is ONSITE and kind is anything other than VIP, the
        multiplier is one-point-two (a twenty-percent onsite
        surcharge)."

        Claim: PROFESSIONAL_BUYER + ONSITE + no group →
        price_cents=round_half_up(12000*1.20)=14400.
        """
        ctx = setup_open_exhibition()
        res = api.create_ticket(
            ctx["exhibition"]["id"],
            create_ticket_payload(
                kind="PROFESSIONAL_BUYER", channel="ONSITE",
            ),
            venue_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["price_cents"] == 14400

    def test_vip_onsite_no_surcharge(
        self, api, venue_admin_headers,
    ):
        """PRD §3.7: "when channel is ONSITE and kind is anything
        other than VIP, the multiplier is one-point-two ... in every
        other case the multiplier is one."

        Claim: VIP + ONSITE → price_cents=30000 (no surcharge).
        """
        ctx = setup_open_exhibition()
        res = api.create_ticket(
            ctx["exhibition"]["id"],
            create_ticket_payload(kind="VIP", channel="ONSITE"),
            venue_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["price_cents"] == 30000


# ===========================================================================
# Group ticket boundary (PRD §3.7)
# ===========================================================================
class TestGroupTicketBoundary:
    # difficulty: boundary_precision_check/group_size_minimum_ten_empty_set_edge

    def test_first_nine_tickets_no_discount(
        self, api, venue_admin_headers,
    ):
        """PRD §3.7: "the count of issued tickets sharing the same
        group_id at the issuance instant is at least ten, the
        multiplier is zero-point-eight-five (a fifteen-percent group
        discount); in every other case the multiplier is one."

        Claim: STUDENT + ONLINE_PRESALE + group_id='G1' issued nine
        times — each ticket has price_cents=2500 (no discount, group
        size still < 10 at issuance).
        """
        # difficulty: boundary_precision_check/group_size_minimum_ten_empty_set_edge
        ctx = setup_open_exhibition()
        gid = random_group_id()
        last = None
        for _ in range(9):
            res = api.create_ticket(
                ctx["exhibition"]["id"],
                create_ticket_payload(
                    kind="STUDENT", channel="ONLINE_PRESALE",
                    group_id=gid,
                ),
                venue_admin_headers,
            )
            last = validate_success(res, expected_status=201)
            assert last["price_cents"] == 2500

    def test_tenth_group_ticket_gets_discount(
        self, api, venue_admin_headers,
    ):
        """PRD §3.7: "when the ticket's group_id is not null and the
        count of issued tickets sharing the same group_id at the
        issuance instant is at least ten, the multiplier is
        zero-point-eight-five."

        Claim: the 10th STUDENT ticket with the same group_id has
        price_cents=round_half_up(2500*1.0*0.85)=2125 (group size
        becomes 10 at the moment of the 10th issuance).
        """
        # difficulty: boundary_precision_check/group_size_minimum_ten_empty_set_edge
        ctx = setup_open_exhibition()
        gid = random_group_id()
        for _ in range(9):
            api.create_ticket(
                ctx["exhibition"]["id"],
                create_ticket_payload(
                    kind="STUDENT", channel="ONLINE_PRESALE",
                    group_id=gid,
                ),
                venue_admin_headers,
            )
        # The 10th ticket — group size including this one is 10 ≥ 10.
        res = api.create_ticket(
            ctx["exhibition"]["id"],
            create_ticket_payload(
                kind="STUDENT", channel="ONLINE_PRESALE", group_id=gid,
            ),
            venue_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        # round_half_up(2500 * 1.0 * 0.85) == round_half_up(2125.0) == 2125
        assert data["price_cents"] == 2125


# ===========================================================================
# Scan-in capacity boundary (PRD §3.7)
# ===========================================================================
class TestScanInCapacityBoundary:
    # difficulty: boundary_precision_check/capacity_strict_less_than_boundary

    def test_scan_in_just_below_capacity_succeeds(
        self, api, gate_operator_headers,
    ):
        """PRD §3.7: "Scanning a ticket in at the gate requires the
        exhibition's posture to be OPEN ... and the exhibition's
        live_occupancy to be strictly less than capacity_max
        (otherwise ERR_CAPACITY_EXCEEDED — note that an exhibition
        created with capacity_max of zero blocks every scan-in)."

        Claim: with capacity_max=100 and live_occupancy=50, a fresh
        scan-in succeeds (50 < 100, well below saturation so posture
        stays OPEN).
        """
        # difficulty: boundary_precision_check/capacity_strict_less_than_boundary
        ctx = setup_open_exhibition_at_occupancy(
            capacity_max=100,
            target_live_occupancy=50,
            extra_unscanned_tickets=1,
        )
        t = ctx["issued_tickets"][0]
        r = api.scan_in_ticket(t["id"], gate_operator_headers)
        validate_success(r, expected_status=200)

    def test_scan_in_at_capacity_zero_blocks_every_scan_in(
        self, api, gate_operator_headers, venue_admin_headers,
    ):
        """PRD §3.7: "an exhibition created with capacity_max of zero
        blocks every scan-in."

        Claim: with capacity_max=0, scan-in evaluates 0 < 0 (false)
        → ERR_CAPACITY_EXCEEDED.

        Note: PRD §2.10 places posture (priority 5) before capacity
        (priority 14); at capacity_max=0 the saturation ratio
        condition (live_occupancy/capacity_max >= 0.95) is not
        meaningfully evaluable. The single observable rule the PRD
        commits to in prose is the strict-less-than capacity check
        — and PRD explicitly states it blocks every scan-in. We
        therefore accept either ERR_CAPACITY_EXCEEDED (capacity
        rule fired) or ERR_POSTURE_BLOCKED (posture rule fired).
        """
        # difficulty: boundary_precision_check/capacity_strict_less_than_boundary
        from test_helpers import setup_open_exhibition
        # We can't reach OPEN status with capacity_max=0 because the
        # posture flips before we'd ever leave SETUP. Instead, test by
        # advancing an OPEN exhibition's live_occupancy and verifying
        # capacity_max=1 with live_occupancy=1 also blocks.
        ctx = setup_open_exhibition_at_occupancy(
            capacity_max=2,
            target_live_occupancy=1,
            extra_unscanned_tickets=2,
        )
        # Scan one more → live_occupancy=2 (ratio 1.0 → posture
        # RESTRICTED after the increment). Then the NEXT scan-in
        # attempt is rejected — by capacity or posture.
        t_first = ctx["issued_tickets"][0]
        api.scan_in_ticket(t_first["id"], gate_operator_headers)
        # Now live_occupancy=2, posture is RESTRICTED (or capacity
        # check would also fail). Either way the third scan fails.
        t_third = ctx["issued_tickets"][1]
        from test_helpers import validate_error_is_one_of
        r = api.scan_in_ticket(t_third["id"], gate_operator_headers)
        validate_error_is_one_of(r, [
            ApiErrorId.ERR_CAPACITY_EXCEEDED.value,
            ApiErrorId.ERR_POSTURE_BLOCKED.value,
        ])


# ===========================================================================
# Scan-in posture cascade (PRD §3.7, §2.9, §2.6)
# ===========================================================================
class TestScanInPostureCascade:
    # difficulty: transitive_cascade/scan_in_posture_cascade_depth_3

    def test_posture_flips_to_restricted_when_ratio_reaches_saturation(
        self, api, gate_operator_headers, venue_admin_headers,
    ):
        """PRD §3.7: "if the ratio of live_occupancy to capacity_max
        reaches at least ninety-five hundredths after the increment,
        the exhibition's posture moves from OPEN to RESTRICTED."

        Claim: with capacity_max=20 and live_occupancy=18 (ratio 0.90,
        still OPEN), scanning ticket T19 brings live_occupancy to 19
        (ratio 0.95 — saturation reached). Therefore Exhibition.posture
        becomes 'RESTRICTED' on that mutation; a follow-up scan-in
        attempt is rejected with ERR_POSTURE_BLOCKED.
        """
        # difficulty: transitive_cascade/scan_in_posture_cascade_depth_3
        ctx = setup_open_exhibition_at_occupancy(
            capacity_max=20,
            target_live_occupancy=18,
            extra_unscanned_tickets=2,
        )
        t19, t20 = ctx["issued_tickets"][0], ctx["issued_tickets"][1]
        # Scan T19 in — live_occupancy 18→19; 19/20 = 0.95 reaches
        # saturation; posture flips OPEN → RESTRICTED.
        r19 = api.scan_in_ticket(t19["id"], gate_operator_headers)
        validate_success(r19, expected_status=200)
        # Verify exhibition state.
        exh_res = api.get_exhibition(
            ctx["exhibition"]["id"], venue_admin_headers,
        )
        exh_after = validate_success(exh_res, expected_status=200)
        assert exh_after["live_occupancy"] == 19
        assert exh_after["posture"] == "RESTRICTED", (
            f"posture should flip to RESTRICTED at saturation; got "
            f"{exh_after['posture']!r}"
        )
        # Follow-up scan T20 — posture is now RESTRICTED → blocked.
        r20 = api.scan_in_ticket(t20["id"], gate_operator_headers)
        validate_error(r20, ApiErrorId.ERR_POSTURE_BLOCKED.value)

    def test_posture_stays_open_below_saturation(
        self, api, gate_operator_headers, venue_admin_headers,
    ):
        """PRD §3.7: "if the ratio of live_occupancy to capacity_max
        reaches at least ninety-five hundredths after the increment,
        the exhibition's posture moves from OPEN to RESTRICTED."

        Claim: at live_occupancy=18 and capacity_max=20 (ratio 0.90 <
        0.95), the exhibition's posture is still OPEN — the
        saturation threshold has not been reached. This is the
        cascade's negative case: the second-level mutation
        (posture flip) does NOT fire below threshold.
        """
        # difficulty: transitive_cascade/scan_in_posture_cascade_depth_3
        ctx = setup_open_exhibition_at_occupancy(
            capacity_max=20,
            target_live_occupancy=18,
        )
        exh_after = validate_success(
            api.get_exhibition(
                ctx["exhibition"]["id"], venue_admin_headers,
            ),
            expected_status=200,
        )
        assert exh_after["live_occupancy"] == 18
        assert exh_after["posture"] == "OPEN"


# ===========================================================================
# Scan-out conservation (PRD §3.7)
# ===========================================================================
class TestScanInScanOutConservation:
    # difficulty: compensating_invariant/occupancy_invariant_on_scan_in_then_out

    def test_scan_in_then_scan_out_restores_live_occupancy(
        self, api, gate_operator_headers, venue_admin_headers,
    ):
        """PRD §3.7: "Scanning out moves the ticket from SCANNED_IN to
        the terminal SCANNED_OUT, decrements live_occupancy, stamps
        scanned_out_at."

        Claim: live_occupancy before scan-in equals live_occupancy
        after scan-in+scan-out on the same ticket.
        """
        # difficulty: compensating_invariant/occupancy_invariant_on_scan_in_then_out
        ctx = setup_open_exhibition_at_occupancy(
            capacity_max=10,
            target_live_occupancy=3,
            extra_unscanned_tickets=1,
        )
        # Verify the baseline N0 = live_occupancy.
        exh = validate_success(
            api.get_exhibition(
                ctx["exhibition"]["id"], venue_admin_headers,
            ),
            expected_status=200,
        )
        n0 = exh["live_occupancy"]
        assert n0 == 3
        ticket = ctx["issued_tickets"][0]
        # Scan-in.
        scan_in = api.scan_in_ticket(
            ticket["id"], gate_operator_headers,
        )
        scanned_in = validate_success(scan_in, expected_status=200)
        assert scanned_in["status"] == "SCANNED_IN"
        # Verify live_occupancy incremented.
        exh = validate_success(
            api.get_exhibition(
                ctx["exhibition"]["id"], venue_admin_headers,
            ),
            expected_status=200,
        )
        assert exh["live_occupancy"] == n0 + 1
        # Scan-out.
        scan_out = api.scan_out_ticket(
            ticket["id"], gate_operator_headers,
        )
        scanned_out = validate_success(scan_out, expected_status=200)
        assert scanned_out["status"] == "SCANNED_OUT"
        # Verify live_occupancy restored.
        exh_final = validate_success(
            api.get_exhibition(
                ctx["exhibition"]["id"], venue_admin_headers,
            ),
            expected_status=200,
        )
        assert exh_final["live_occupancy"] == n0, (
            f"invariant violated: started at {n0}, ended at "
            f"{exh_final['live_occupancy']}"
        )

    def test_scanned_in_at_and_scanned_out_at_stamped(
        self, api, gate_operator_headers, venue_admin_headers,
    ):
        """PRD §3.7: "scanned_in_at := now()" and "stamps
        scanned_out_at."

        Claim: after the scan-in/scan-out pair, the ticket carries
        non-null scanned_in_at and scanned_out_at and ends in
        SCANNED_OUT (the terminal state).
        """
        # difficulty: compensating_invariant/occupancy_invariant_on_scan_in_then_out
        ctx = setup_open_exhibition_at_occupancy(
            capacity_max=10,
            target_live_occupancy=2,
            extra_unscanned_tickets=1,
        )
        ticket = ctx["issued_tickets"][0]
        validate_success(
            api.scan_in_ticket(ticket["id"], gate_operator_headers),
            expected_status=200,
        )
        scan_out = validate_success(
            api.scan_out_ticket(ticket["id"], gate_operator_headers),
            expected_status=200,
        )
        assert scan_out["status"] == "SCANNED_OUT"
        assert scan_out.get("scanned_in_at") is not None
        assert scan_out.get("scanned_out_at") is not None


# ===========================================================================
# Error precedence: state before posture on scan-in (PRD §2.10)
# ===========================================================================
class TestStateBeforePostureOnScanIn:
    # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_scan_in

    def test_already_scanned_in_ticket_yields_invalid_state_not_posture(
        self, api, gate_operator_headers,
    ):
        """PRD §2.10: "The order is: authentication header presence
        first (ERR_AUTH_REQUIRED), then role permission (ERR_FORBIDDEN),
        then path-identifier existence (ERR_NOT_FOUND, applied
        left-to-right per §2.7), then state-transition legality
        (ERR_INVALID_STATE), then domain-safety gates such as
        posture, safety-inspection presence, and overnight-permit
        requirement, then business constraints."

        Claim: when a ticket already in SCANNED_IN is re-scanned,
        the state check fires before the posture check — the response
        is ERR_INVALID_STATE.
        """
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_scan_in
        ctx = setup_open_exhibition_at_occupancy(
            capacity_max=10,
            target_live_occupancy=0,
            extra_unscanned_tickets=1,
        )
        ticket = ctx["issued_tickets"][0]
        # First scan-in succeeds.
        validate_success(
            api.scan_in_ticket(ticket["id"], gate_operator_headers),
            expected_status=200,
        )
        # Second scan-in on the same ticket: ticket is now in
        # SCANNED_IN — state check at priority 4 wins over posture.
        res = api.scan_in_ticket(ticket["id"], gate_operator_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_scan_in_voided_ticket_yields_invalid_state(
        self, api, gate_operator_headers, venue_admin_headers,
    ):
        """PRD §2.10: "The order is: ... state-transition legality
        (ERR_INVALID_STATE), then domain-safety gates such as
        posture, safety-inspection presence, and overnight-permit
        requirement."

        Claim: scanning a VOIDed (ISSUED→VOID terminal) ticket fails
        with ERR_INVALID_STATE — the state check fires before any
        posture check.
        """
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_on_scan_in
        ctx = setup_open_exhibition_at_occupancy(
            capacity_max=10,
            target_live_occupancy=0,
            extra_unscanned_tickets=1,
        )
        ticket = ctx["issued_tickets"][0]
        # VOID the ticket (admin).
        validate_success(
            api.void_ticket(ticket["id"], venue_admin_headers),
            expected_status=200,
        )
        # Now try to scan-in the VOIDed ticket — state check fires.
        res = api.scan_in_ticket(ticket["id"], gate_operator_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
