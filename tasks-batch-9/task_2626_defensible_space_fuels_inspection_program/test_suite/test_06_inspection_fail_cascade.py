"""The failing-inspection cascade: inspection, parcel, notice, certificate, community."""

from test_helpers import (
    FAIL_CLEARANCES,
    PASS_CLEARANCES,
    add_zones,
    assert_2dp,
    assert_end_of_day,
    assert_instant,
    assert_notice_schedule,
    assert_posture,
    assert_risk,
    community_metrics,
    complete_inspection,
    create_community,
    create_inspector,
    create_parcel,
    get_certificate,
    get_community,
    get_parcel,
    issued_certificate,
    list_notices,
    open_cycle,
    schedule_inspection,
    serve_notice,
    set_clock,
)


def _passed_and_certified_world(client):
    """One community, one member parcel, a clean INITIAL pass and a live certificate.

    The parcel carries the canonical HIGH-hazard profile, so the passing
    clearances of 10.0 / 40.0 / 130.0 feet clear every requirement, the parcel
    lands COMPLIANT and the community's rate is 100.00.  A REAL_ESTATE
    certificate is then issued against that clean posture on 2026-08-22.  A
    second, COMPLAINT inspection is scheduled, noticed and measured at the
    deficient clearances but left open for the trigger.
    """
    cycle = open_cycle(client, notice_lead_days=10)
    inspector = create_inspector(client)
    community = create_community(client)
    parcel = create_parcel(
        client, community_id=community["id"], lot_area_sqft=43560
    )

    first = schedule_inspection(
        client,
        parcel["id"],
        cycle["id"],
        inspector["id"],
        scheduled_start_utc="2026-08-20T15:00:00Z",
        scheduled_end_utc="2026-08-20T17:00:00Z",
        inspection_type="INITIAL",
        access_arrangement="OWNER_PRESENT",
    )
    serve_notice(client, first["id"], "EMAIL")
    add_zones(client, first["id"], inspector["id"], PASS_CLEARANCES)
    set_clock(client, "2026-08-22T00:00:00Z")
    complete_inspection(client, first["id"], inspector["id"], result="PASS")
    certificate = issued_certificate(client, parcel["id"])

    second = schedule_inspection(
        client,
        parcel["id"],
        cycle["id"],
        inspector["id"],
        scheduled_start_utc="2026-09-15T15:00:00Z",
        scheduled_end_utc="2026-09-15T17:00:00Z",
        inspection_type="COMPLAINT",
        access_arrangement="EXTERIOR_ONLY",
    )
    serve_notice(client, second["id"], "CERTIFIED_MAIL")
    return {
        "cycle": cycle,
        "inspector": inspector,
        "community": community,
        "parcel": parcel,
        "first": first,
        "certificate": certificate,
        "second": second,
    }


class TestFailCascade:
    """One completion request, six consequences, one of them deliberately absent."""

    def test_fail_propagates_through_notice_certificate_and_community_rate(
        self, client
    ):
        """The rollup rescores the parcel, cites it, revokes its clean paperwork
        and drops its neighbourhood's rate to 0.00 without lapsing it.

        PRD: "max_deficiency_severity is the worst severity among the three zone
        evaluations, ranked NONE, then MINOR, then MAJOR, then CRITICAL, and it is NONE
        when every zone came in compliant."

        PRD: "Because that rollup produced verified measurements, the parcel is
        rescored under the post-inspection-verified variant, risk_score_basis
        becomes POST_INSPECTION_VERIFIED, risk_class is re-banded, and
        compliance_status becomes NON_COMPLIANT."

        PRD: "Because the parcel is now non-compliant, a violation notice is created
        against it, citing this inspection as the substantiating evidence."

        PRD: "The parcel's open_violation_count rises by 1."

        PRD: "Because a violation notice now exists on the parcel, every
        compliance certificate on that parcel standing in ISSUED whose
        expires_at_utc is at or after the logical clock transitions ISSUED ->
        REVOKED with revoked_at_utc stamped at the logical clock."

        PRD: "Because the parcel's compliance_status changed in link 2, the
        compliance_rate_pct of the parcel's community is recomputed whenever
        community_id is not null."

        PRD: "any community standing in CERTIFIED whose freshly recomputed rate
        has fallen below the lapse floor of 60.00 percent transitions CERTIFIED
        -> LAPSED and has its lapse_count incremented by 1."

        Design: Difficulty/transitive_cascade/inspection_fail_cascade_five_links_to_community_rate
        """
        world = _passed_and_certified_world(client)
        parcel_id = world["parcel"]["id"]
        community_id = world["community"]["id"]

        # The pass left a clean slate: veg 0.00, rate 100.00, no lapses.
        assert_risk(get_parcel(client, parcel_id), 37.95, "MODERATE")
        assert_2dp(community_metrics(client, community_id)["compliance_rate_pct"], 100.00)
        assert get_community(client, community_id)["lapse_count"] == 0
        assert_end_of_day(world["certificate"]["expires_at_utc"], "2026-11-20")
        assert world["certificate"]["snapshot_risk_class"] == "MODERATE"

        add_zones(client, world["second"]["id"], world["inspector"]["id"], FAIL_CLEARANCES)
        set_clock(client, "2026-09-15T16:00:00Z")
        inspection = complete_inspection(
            client,
            world["second"]["id"],
            world["inspector"]["id"],
            result="FAIL",
            violation_notice_method="CERTIFIED_MAIL",
        )

        # LINK 1 - the inspection's own rollup.
        assert inspection["result"] == "FAIL"
        assert_2dp(inspection["measured_veg_points"], 94.31)
        assert inspection["max_deficiency_severity"] == "MAJOR"
        assert_instant(inspection["completed_at_utc"], "2026-09-15T16:00:00Z")

        # LINK 2 - the parcel is rescored with a zero hardening credit.
        parcel = get_parcel(client, parcel_id)
        assert_risk(parcel, 70.49, "HIGH", basis="POST_INSPECTION_VERIFIED")
        assert_posture(parcel, "NON_COMPLIANT", open_violation_count=1)

        # LINK 3 - exactly one citation, served by certified mail.
        rows, _meta = list_notices(client, inspection_id=world["second"]["id"])
        assert len(rows) == 1, "expected exactly one citation, got %d" % len(rows)
        notice = rows[0]
        assert_instant(notice["issued_at_utc"], "2026-09-15T16:00:00Z")
        assert_notice_schedule(
            notice,
            severity="MAJOR",
            delivered_at_utc="2026-09-20T16:00:00Z",
            compliance_days=30,
            deadline_date="2026-10-20",
            status="ISSUED",
        )

        # LINK 4 - the unexpired certificate is revoked, snapshots preserved.
        certificate = get_certificate(client, world["certificate"]["id"])
        assert certificate["status"] == "REVOKED"
        assert_instant(certificate["revoked_at_utc"], "2026-09-15T16:00:00Z")
        assert certificate["snapshot_risk_class"] == "MODERATE"
        assert certificate["snapshot_compliance_status"] == "COMPLIANT"

        # LINK 5 - the community rate falls to a real 0.00, not to null.
        community = get_community(client, community_id)
        assert community["compliance_rate_pct"] is not None
        assert_2dp(community["compliance_rate_pct"], 0.00)
        metrics = community_metrics(client, community_id)
        assert metrics["eligible_parcel_count"] == 1
        assert metrics["compliant_parcel_count"] == 0

        # LINK 6 is suppressed: only a CERTIFIED community can lapse.
        assert community["status"] == "ORGANIZING"
        assert community["lapse_count"] == 0

    def test_certificate_survives_when_the_completion_raises_no_notice(self, client):
        """Revocation hangs off the citation, not off the completion itself: the
        same COMPLAINT inspection closed as a pass leaves the certificate ISSUED.

        PRD: "Because a violation notice now exists on the parcel, every
        compliance certificate on that parcel standing in ISSUED whose
        expires_at_utc is at or after the logical clock transitions ISSUED ->
        REVOKED with revoked_at_utc stamped at the logical clock."

        PRD: "A passing inspection sets the parcel's last_passed_inspection_at_utc to
        the same instant as completed_at_utc and sets compliance_status to COMPLIANT -
        unless the parcel's exemption_flag is true, in which case the EXEMPT posture is
        retained rather than overwritten."

        PRD: "A passing INITIAL or COMPLAINT inspection clears nothing - the
        owner must be re-inspected under a REINSPECTION for a citation to lift."

        Design: Difficulty/transitive_cascade/inspection_fail_cascade_five_links_to_community_rate
        """
        world = _passed_and_certified_world(client)
        parcel_id = world["parcel"]["id"]

        add_zones(client, world["second"]["id"], world["inspector"]["id"], PASS_CLEARANCES)
        set_clock(client, "2026-09-15T16:00:00Z")
        inspection = complete_inspection(
            client, world["second"]["id"], world["inspector"]["id"], result="PASS"
        )
        assert_2dp(inspection["measured_veg_points"], 0.00)
        assert inspection["max_deficiency_severity"] == "NONE"

        rows, _meta = list_notices(client, parcel_id=parcel_id)
        assert rows == [], "a passing inspection must raise no citation"

        certificate = get_certificate(client, world["certificate"]["id"])
        assert certificate["status"] == "ISSUED"
        assert certificate["revoked_at_utc"] is None
        assert_end_of_day(certificate["expires_at_utc"], "2026-11-20")

        parcel = get_parcel(client, parcel_id)
        assert_posture(parcel, "COMPLIANT", open_violation_count=0)
        assert_instant(parcel["last_passed_inspection_at_utc"], "2026-09-15T16:00:00Z")
        assert_2dp(get_community(client, world["community"]["id"])["compliance_rate_pct"], 100.00)
