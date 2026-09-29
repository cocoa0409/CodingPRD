"""The verification cascade: invoice, crew-hour ledger, notice, parcel, community."""

from test_helpers import (
    assert_2dp,
    assert_cents,
    assert_cost_recovery,
    assert_end_of_day,
    assert_hours,
    assert_instant,
    assert_posture,
    community_metrics,
    create_community,
    create_inspector,
    get_community,
    get_contractor,
    get_notice,
    get_parcel,
    parcel_payload,
    verify_completion,
    work_complete_world,
)

VERIFY_CLOCK = "2026-10-06T08:00:00Z"


def _community_work_complete_world(client, **kw):
    """A WORK_COMPLETE order whose parcel is the sole member of one community.

    The parcel reached ABATEMENT_PENDING through the enforcement chain, so the
    neighbourhood's rate stands at 0.00 with one eligible member.  The crew's
    window opens at 2026-10-06T08:00Z and the clock already sits there.
    """
    community = create_community(client)
    world = work_complete_world(
        client,
        parcel_payload=parcel_payload(community_id=community["id"]),
        **kw
    )
    world["community"] = community
    return world


class TestVerifyCompletionCascade:
    """One verification request unwinds the reservation and lifts the citation."""

    def test_verification_invoices_releases_hours_clears_notice_and_lifts_rate(
        self, client
    ):
        """Five links land in the same request, and the community rate moves
        upward from 0.00 to 100.00.

        PRD: "The cost fields above are computed, verified_by_inspector_id records
        the acting inspector, invoice_due_utc and recovery_basis are set, and the
        order moves WORK_COMPLETE -> INVOICED."

        PRD: "Because the order became invoiced, the reservation finally unwinds:
        the contractor's committed_crew_hours decreases by the order's crew_hours
        and its completed_crew_hours increases by the order's actual_crew_hours,
        restoring the conservation identity of section 2.10."

        PRD: "Because the order became invoiced, the referenced violation notice
        transitions ABATEMENT_AUTHORIZED -> CLEARED with cleared_at_utc stamped at
        the logical clock."

        PRD: "Because that notice cleared, the parcel's open_violation_count
        decreases by 1 and its compliance_status becomes COMPLIANT - but only when
        no other open notice remains on the parcel."

        PRD: "For an invoiced abatement order, total_recoverable_cents always
        equals paid_cents plus lien_amount_cents plus the outstanding remainder."

        Design: Difficulty/transitive_cascade/verify_completion_cascade_clears_notice_and_releases_hours
        """
        world = _community_work_complete_world(client)
        community_id = world["community"]["id"]

        # Before the trigger: hours still committed, nothing worked off the books.
        contractor_before = get_contractor(client, world["contractor"]["id"])
        assert_hours(contractor_before["committed_crew_hours"], 12.5)
        assert_hours(contractor_before["completed_crew_hours"], 0.0)
        assert world["order"]["status"] == "WORK_COMPLETE"
        assert_2dp(community_metrics(client, community_id)["compliance_rate_pct"], 0.00)
        assert get_notice(client, world["notice"]["id"])["status"] == (
            "ABATEMENT_AUTHORIZED"
        )

        verifier = create_inspector(client)
        order = verify_completion(
            client, world["order"]["id"], verifier["id"], "abatement verified"
        )

        # LINK 1 - the invoice.
        assert order["status"] == "INVOICED"
        assert order["verified_by_inspector_id"] == verifier["id"]
        assert_cost_recovery(
            order,
            labor=107500,
            disposal=29900,
            mobilization=32000,
            overhead=21176,
            pre_subsidy_total=190576,
            subsidy_pct=0.20,
            subsidy=38115,
            total_recoverable=152461,
            recovery_basis="DISTRICT_CONTRACTED",
        )
        assert_end_of_day(order["invoice_due_utc"], "2026-11-20")
        assert_cents(order["paid_cents"], 0)
        assert_cents(order["lien_amount_cents"], 0)

        # LINK 2 - the crew-hour ledger.
        contractor = get_contractor(client, world["contractor"]["id"])
        assert_hours(contractor["committed_crew_hours"], 0.0)
        assert_hours(contractor["completed_crew_hours"], 12.5)

        # LINK 3 - the citation is satisfied even though the district paid.
        notice = get_notice(client, world["notice"]["id"])
        assert notice["status"] == "CLEARED"
        assert_instant(notice["cleared_at_utc"], VERIFY_CLOCK)

        # LINK 4 - nothing else is open against the parcel.
        parcel = get_parcel(client, world["parcel"]["id"])
        assert_posture(parcel, "COMPLIANT", open_violation_count=0)

        # LINK 5 - the neighbourhood rate rises.
        community = get_community(client, community_id)
        assert_2dp(community["compliance_rate_pct"], 100.00)
        metrics = community_metrics(client, community_id)
        assert metrics["eligible_parcel_count"] == 1
        assert metrics["compliant_parcel_count"] == 1

    def test_ledger_unwinds_reserved_hours_while_banking_the_worked_hours(
        self, client
    ):
        """Reserved and worked hours are different quantities: 12.5 comes off
        committed while 14.0 goes onto the lifetime tally.

        PRD: "Note that these are different quantities - reserved hours and
        actually-worked hours need not match - and completed_crew_hours is never
        decremented by anything."

        PRD: "A contractor's committed_crew_hours must always equal the sum of
        crew_hours across that contractor's orders whose status is AWARDED or
        WORK_COMPLETE; its completed_crew_hours is a lifetime tally that only ever
        grows."

        PRD: "The labour line is the reported actual_crew_hours multiplied by the
        contractor's hourly_rate_cents, rounded half up to a whole cent, and
        stored as labor_line_cents."

        Design: Difficulty/transitive_cascade/verify_completion_cascade_clears_notice_and_releases_hours
        """
        world = _community_work_complete_world(client, actual_crew_hours=14.0)

        contractor_before = get_contractor(client, world["contractor"]["id"])
        assert_hours(contractor_before["committed_crew_hours"], 12.5)
        assert_hours(contractor_before["completed_crew_hours"], 0.0)
        assert_hours(world["order"]["crew_hours"], 12.5)
        assert_hours(world["order"]["actual_crew_hours"], 14.0)

        verifier = create_inspector(client)
        order = verify_completion(client, world["order"]["id"], verifier["id"])

        # 14.0 hours at 8600 cents, overhead per line 15050 + 3738 + 4000.
        assert_cost_recovery(
            order,
            labor=120400,
            disposal=29900,
            mobilization=32000,
            overhead=22788,
            pre_subsidy_total=205088,
            subsidy_pct=0.20,
            subsidy=41018,
            total_recoverable=164070,
            recovery_basis="DISTRICT_CONTRACTED",
        )

        contractor = get_contractor(client, world["contractor"]["id"])
        assert_hours(contractor["committed_crew_hours"], 0.0)
        assert_hours(contractor["completed_crew_hours"], 14.0)

        # The rest of the chain is indifferent to the hour mismatch.
        assert get_notice(client, world["notice"]["id"])["status"] == "CLEARED"
        assert_posture(
            get_parcel(client, world["parcel"]["id"]),
            "COMPLIANT",
            open_violation_count=0,
        )
        assert_2dp(
            get_community(client, world["community"]["id"])["compliance_rate_pct"],
            100.00,
        )
