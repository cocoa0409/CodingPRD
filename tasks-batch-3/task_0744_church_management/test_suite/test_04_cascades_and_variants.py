"""Cross-entity cascades and dual-variant calculations."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_household, create_adult_member,
    create_and_activate_campaign, create_pledge, create_donation,
    cancel_pledge, refund_donation,
    create_facility, create_event, create_facility_booking, get_facility,
    setup_fulfilled_pledge, setup_facility_with_booking,
)


class TestDualVariantPledgeCampaign:
    def test_projected_vs_chronological_diverge(self, api):
        """PRD §3.2: "The default variant (also selected explicitly by
        requesting variant=PROJECTED) is a forward-looking view: it defines
        a projected total, in cents, as the sum of pledged_amount_cents
        across every pledge on this campaign whose status is either ACTIVE
        or FULFILLED; CANCELLED pledges are excluded from the sum."
        PRD §3.2: "The chronological variant (selected by
        variant=CHRONOLOGICAL) is a cash-basis view: it uses
        received_total_cents, defined as the sum of amount_cents across
        every donation whose campaign_id matches this campaign, whose
        status is POSTED, and whose posted_at is at or before the current
        logical clock."

        Design: Difficulty/dual_variant_calc/pledge_campaign_projected_vs_chronological_diverge
        """
        set_clock("2026-06-15T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        c = create_and_activate_campaign(
            name="Building Fund", target_amount_cents=100_000,
            starts_on="2026-05-01", ends_on="2026-12-31",
        )
        p1 = create_pledge(c["id"], m["id"], pledged_amount_cents=40_000,
                           frequency="MONTHLY")
        p2 = create_pledge(c["id"], m["id"], pledged_amount_cents=30_000,
                           frequency="MONTHLY")
        p3 = create_pledge(c["id"], m["id"], pledged_amount_cents=20_000,
                           frequency="MONTHLY")
        cancel_pledge(p3["id"])
        create_donation(m["id"], 10_000, "2026-06-01",
                        payment_method="CHECK",
                        campaign_id=c["id"], pledge_id=p1["id"])
        create_donation(m["id"], 5_000, "2026-06-10",
                        payment_method="CHECK",
                        campaign_id=c["id"], pledge_id=p1["id"])

        # Campaign totals reflect commitments and cash-received.
        resp = api.get_pledge_campaign(c["id"],
                                       TEST_USERS["finance_admin_headers"])
        campaign = validate_success(resp)
        # Projected total = ACTIVE + FULFILLED pledges = 40000 + 30000
        assert campaign["pledged_total_cents"] == 70_000
        # Cash received = POSTED donations = 10000 + 5000
        assert campaign["received_total_cents"] == 15_000
        # PROJECTED (70000) vs CHRONOLOGICAL (15000) differ by exactly 55000.
        assert (
            campaign["pledged_total_cents"] - campaign["received_total_cents"]
            == 55_000
        )

    def test_cancelled_pledges_excluded_from_projected_total(self, api):
        """PRD §3.2: "it defines a projected total, in cents, as the sum
        of pledged_amount_cents across every pledge on this campaign
        whose status is either ACTIVE or FULFILLED; CANCELLED pledges are
        excluded from the sum."

        Design: Difficulty/dual_variant_calc/pledge_campaign_projected_vs_chronological_diverge
        """
        # Second required test for the dual-variant instance — isolates the
        # "CANCELLED pledges are excluded" clause of the projected variant.
        set_clock("2026-06-15T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        c = create_and_activate_campaign(
            name="Cancelled-Excluded", target_amount_cents=100_000,
            starts_on="2026-05-01", ends_on="2026-12-31",
        )
        create_pledge(c["id"], m["id"], pledged_amount_cents=40_000,
                      frequency="MONTHLY")
        p2 = create_pledge(c["id"], m["id"], pledged_amount_cents=25_000,
                           frequency="MONTHLY")
        cancel_pledge(p2["id"])
        campaign = validate_success(
            api.get_pledge_campaign(c["id"],
                                    TEST_USERS["finance_admin_headers"])
        )
        # Only the ACTIVE 40k pledge counts; the CANCELLED 25k is excluded.
        assert campaign["pledged_total_cents"] == 40_000


class TestDepthThreeRefundCascade:
    def test_refund_cascades_to_campaign_fulfilled_counter(self, api):
        """PRD §3.3: "as Link 1 (caused directly by the donation state change), if `pledge_id` is non-null, the pledge's `received_amount_cents` decrements by `amount_cents`. As Link 2 (caused by Link 1's `received_amount_cents` change, not by the refund action itself), if the pledge had been `FULFILLED` and its `received_amount_cents` is now strictly less than `pledged_amount_cents`, the pledge auto-reverts from `FULFILLED` to `ACTIVE`. As Link 3 (caused by Link 2's pledge state change), the campaign's `fulfilled_pledge_count` decrements by one."

        Design: Difficulty/transitive_cascade/donation_refund_depth_three_cascade_to_campaign_counter
        """
        h, m, c, p, d = setup_fulfilled_pledge(
            pledged_amount_cents=10_000,
            donation_date="2026-06-01",
            clock="2026-06-15T00:00:00Z",
        )
        # Verify pre-refund fulfilled_pledge_count == 1.
        campaign_before = validate_success(
            api.get_pledge_campaign(c["id"],
                                    TEST_USERS["finance_admin_headers"])
        )
        assert campaign_before["fulfilled_pledge_count"] == 1

        donation_after = validate_success(
            api.refund_donation(d["id"], TEST_USERS["finance_admin_headers"])
        )
        assert donation_after["status"] == "REFUNDED"  # Link 0

        pledge_after = validate_success(
            api.get_pledge(p["id"], TEST_USERS["finance_admin_headers"])
        )
        assert pledge_after["received_amount_cents"] == 0  # Link 1
        assert pledge_after["status"] == "ACTIVE"  # Link 2

        campaign_after = validate_success(
            api.get_pledge_campaign(c["id"],
                                    TEST_USERS["finance_admin_headers"])
        )
        assert campaign_after["fulfilled_pledge_count"] == 0  # Link 3

    def test_refund_reduces_campaign_received_total(self, api):
        """PRD §3.3: "Independently and in parallel to Links 1–3, if the
        donation's campaign_id is non-null, the campaign's
        received_total_cents decrements by amount_cents."

        Design: Difficulty/transitive_cascade/donation_refund_depth_three_cascade_to_campaign_counter
        """
        # Second required test for this instance.
        h, m, c, p, d = setup_fulfilled_pledge(
            pledged_amount_cents=6_000,
            donation_date="2026-06-01",
            clock="2026-06-15T00:00:00Z",
        )
        api.refund_donation(d["id"], TEST_USERS["finance_admin_headers"])
        campaign_after = validate_success(
            api.get_pledge_campaign(c["id"],
                                    TEST_USERS["finance_admin_headers"])
        )
        assert campaign_after["received_total_cents"] == 0


class TestDepthTwoEventCancelCascade:
    def test_event_cancel_cancels_facility_booking_and_zeroes_hours(self, api):
        """PRD §3.6: "as Link 1 (caused directly by the event state
        change), every CONFIRMED FacilityBooking whose event_id equals
        this event's id auto-transitions to CANCELLED; as Link 2 (caused
        by each Link-1 booking state change, not by the event cancel
        action itself), the affected facility's upcoming_booked_hours is
        recomputed with each cancelled booking excluded."

        Design: Difficulty/transitive_cascade/event_cancel_depth_two_cascade_to_facility_hours
        """
        set_clock("2026-05-01T09:00:00Z")
        f = create_facility(capacity=200, buffer_minutes=0)
        e = create_event(
            name="Sun 10am", event_type="SERVICE",
            starts_at="2026-05-03T10:00:00Z", ends_at="2026-05-03T12:00:00Z",
            expected_attendance=100, volunteer_slots=0,
            facility_id=f["id"],
        )
        b = create_facility_booking(
            f["id"], "2026-05-03T10:00:00Z", "2026-05-03T12:00:00Z",
            headcount=100, expected_facility_version=f["version"],
            booking_type="EVENT", event_id=e["id"],
        )

        cancel_resp = api.cancel_event(e["id"],
                                       TEST_USERS["coordinator_headers"])
        event_after = validate_success(cancel_resp)
        assert event_after["status"] == "CANCELLED"  # Link 0

        booking_after = validate_success(
            api.get_facility_booking(b["id"],
                                     TEST_USERS["coordinator_headers"])
        )
        assert booking_after["status"] == "CANCELLED"  # Link 1

        facility_after = get_facility(f["id"])
        assert facility_after["upcoming_booked_hours"] == 0  # Link 2

    def test_event_cancel_cascades_volunteer_and_child(self, api):
        """PRD §3.6: "every VolunteerAssignment whose event_id equals this
        event and whose status is either INVITED or ACCEPTED
        auto-transitions to CANCELLED, and every ChildCheckIn on this
        event whose status is CHECKED_IN auto-transitions to
        SECURITY_HOLD with hold_reason set to STAFF_HOLD..."

        Design: Difficulty/transitive_cascade/event_cancel_depth_two_cascade_to_facility_hours
        """
        # Second required test for this instance — same event.cancel driver,
        # verifying the fan-out branch (volunteer + child) that PRD §3.6
        # spells out alongside the depth-2 facility chain.
        from test_helpers import (
            setup_child_checked_in, create_volunteer_assignment,
            accept_volunteer_as_member, make_member_headers,
        )
        # Set up a child check-in tied to an event, plus a volunteer.
        h, g, k, e, ch = setup_child_checked_in(
            clock="2026-05-10T09:30:00Z",
            event_starts_at="2026-05-10T10:00:00Z",
            event_ends_at="2026-05-10T11:00:00Z",
        )
        # Volunteer assignment on the same event, ACCEPTED.
        vol_member = create_adult_member(h["id"], full_name="Vol",
                                         email="vol@example.com",
                                         membership_status="REGULAR")
        va = create_volunteer_assignment(e["id"], vol_member["id"],
                                         role_type="USHER")
        accept_volunteer_as_member(va["id"], vol_member["id"])

        api.cancel_event(e["id"], TEST_USERS["coordinator_headers"])

        va_after = validate_success(
            api.get_volunteer_assignment(va["id"],
                                         TEST_USERS["coordinator_headers"])
        )
        assert va_after["status"] == "CANCELLED"

        ch_after = validate_success(
            api.get_child_checkin(ch["id"],
                                  TEST_USERS["coordinator_headers"])
        )
        assert ch_after["status"] == "SECURITY_HOLD"
        assert ch_after["hold_reason"] == "STAFF_HOLD"


class TestPostRefundCompensatingInvariant:
    def test_post_then_refund_restores_campaign_received_total(self, api):
        """PRD §3.3: "if the donation's campaign_id is non-null, the
        campaign's received_total_cents accumulates by the donation's
        amount_cents."
        PRD §3.3: "Independently and in parallel to Links 1–3, if the
        donation's campaign_id is non-null, the campaign's
        received_total_cents decrements by amount_cents."

        Design: Difficulty/compensating_invariant/donation_post_then_refund_preserves_campaign_received_total
        """
        set_clock("2026-06-01T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        c = create_and_activate_campaign(name="Inv", target_amount_cents=50_000,
                                         starts_on="2026-05-01",
                                         ends_on="2026-12-31")
        p = create_pledge(c["id"], m["id"], pledged_amount_cents=10_000)
        d = create_donation(m["id"], 4_000, "2026-06-01",
                            payment_method="CHECK",
                            campaign_id=c["id"], pledge_id=p["id"])
        # Auto-POSTED: received_total_cents == 4000, pledge received == 4000.
        api.refund_donation(d["id"], TEST_USERS["finance_admin_headers"])

        campaign_after = validate_success(
            api.get_pledge_campaign(c["id"],
                                    TEST_USERS["finance_admin_headers"])
        )
        assert campaign_after["received_total_cents"] == 0
        assert campaign_after["fulfilled_pledge_count"] == 0
        pledge_after = validate_success(
            api.get_pledge(p["id"], TEST_USERS["finance_admin_headers"])
        )
        assert pledge_after["received_amount_cents"] == 0
        assert pledge_after["status"] == "ACTIVE"

    def test_post_refund_pair_preserves_pledge_received_amount(self, api):
        """PRD §3.3: "as Link 1 (caused directly by the donation state change), if `pledge_id` is non-null, the pledge's `received_amount_cents` decrements by `amount_cents`."

        Design: Difficulty/compensating_invariant/donation_post_then_refund_preserves_campaign_received_total
        """
        # Second required test for this instance — asserts the paired
        # conserved quantity on the Pledge side (§1.8 second assert line).
        set_clock("2026-06-01T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        c = create_and_activate_campaign(name="Inv2", target_amount_cents=50_000)
        p = create_pledge(c["id"], m["id"], pledged_amount_cents=10_000)
        d = create_donation(m["id"], 2_500, "2026-06-01",
                            payment_method="CHECK",
                            campaign_id=c["id"], pledge_id=p["id"])
        api.refund_donation(d["id"], TEST_USERS["finance_admin_headers"])
        pledge_after = validate_success(
            api.get_pledge(p["id"], TEST_USERS["finance_admin_headers"])
        )
        assert pledge_after["received_amount_cents"] == 0
        assert pledge_after["remaining_amount_cents"] == 10_000


class TestConsistencyModelImmediate:
    def test_received_total_visible_after_post(self, api):
        """PRD §3.3: "if the donation's campaign_id is non-null, the
        campaign's received_total_cents accumulates by the donation's
        amount_cents."

        Design: Corner/consistency_model/immediate_consistency_derived_field_visible_in_response
        """
        set_clock("2026-06-01T00:00:00Z")
        h = create_household()
        m = create_adult_member(h["id"])
        c = create_and_activate_campaign(name="C1", target_amount_cents=50_000)
        p = create_pledge(c["id"], m["id"], pledged_amount_cents=5_000)
        create_donation(m["id"], 1_500, "2026-06-01",
                        payment_method="CHECK",
                        campaign_id=c["id"], pledge_id=p["id"])
        campaign = validate_success(
            api.get_pledge_campaign(c["id"],
                                    TEST_USERS["finance_admin_headers"])
        )
        assert campaign["received_total_cents"] == 1_500
