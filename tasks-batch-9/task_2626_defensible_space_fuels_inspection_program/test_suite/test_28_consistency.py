"""The consistency model: one write, and every dependent read is already converged."""

from test_helpers import (
    EPOCH_CLOCK_UTC,
    add_zones,
    assert_2dp,
    assert_end_of_day,
    assert_instant,
    assert_metrics,
    assert_posture,
    assert_risk,
    community_metrics,
    community_world,
    complete_inspection,
    create_inspector,
    cycle_metrics,
    get_community,
    get_cycle,
    get_parcel,
    list_notices,
    schedule_inspection,
    serve_notice,
)


class TestFailCompletionIsImmediatelyVisible:
    """Nothing about the failure cascade is deferred to a later pass."""

    def test_the_first_read_of_every_dependent_row_is_already_converged(self, client):
        """The completion response itself carries the rollup, and the first read of the
        parcel, of its brand-new notice and of the persisted community rate all agree at
        the same logical instant.

        PRD: "Implementations that treat these counters as derived-on-read conveniences
        rather than as invariants maintained on every mutation will diverge from this
        specification in ways the district's auditors notice."

        PRD: "A failing inspection fires the deepest cascade in the system, six linked
        consequences that must all land in the same request:"

        PRD: "measured_veg_points is the sum of the three zones' points values, and the
        rounding discipline here is pinned: each zone's points is already rounded to two
        decimals, and it is those rounded values that are added; the sum is then rounded
        half up to two decimals and capped at 100.00."

        PRD: "Because that rollup produced verified measurements, the parcel is rescored
        under the post-inspection-verified variant, risk_score_basis becomes
        POST_INSPECTION_VERIFIED, risk_class is re-banded, and compliance_status becomes
        NON_COMPLIANT."

        PRD: "Because the parcel's compliance_status changed in link 2, the
        compliance_rate_pct of the parcel's community is recomputed whenever community_id
        is not null."

        PRD: "Parcels sitting in PENDING_INSPECTION or EXEMPT are excluded from both the
        numerator and the denominator - they are not counted as failures, they are simply
        not counted."

        PRD: "The community scope, served by the community metrics read and used at both
        the cycle-advance recomputation and the inspection-failure cascade, spans only
        the parcels whose community_id equals the target community; this is the value
        persisted to Community.compliance_rate_pct and the value compared against the
        75.00 percent certification floor and the 60.00 percent lapse floor."

        Design: Corner/consistency model/fail_completion_effects_visible_without_any_re_read_delay
        """
        world = community_world(client, member_count=3)
        community_id = world["community"]["id"]
        assert world["community"]["compliance_rate_pct"] is None
        member_a, member_b, member_c = world["parcels"]
        assert_risk(member_a, 63.83, "HIGH", basis="INTAKE_PROVISIONAL")

        inspector = create_inspector(client)
        inspection = schedule_inspection(
            client, member_a["id"], world["cycle"]["id"], inspector["id"]
        )
        inspection = serve_notice(client, inspection["id"])
        add_zones(client, inspection["id"], inspector["id"])

        # The single write under test.
        completed = complete_inspection(
            client, inspection["id"], inspector["id"], "FAIL"
        )
        # The trigger's own response already carries the rollup.
        assert completed["result"] == "FAIL"
        assert_2dp(completed["measured_veg_points"], 94.31)
        assert completed["max_deficiency_severity"] == "MAJOR"
        assert_instant(completed["completed_at_utc"], EPOCH_CLOCK_UTC)

        # First read of the parcel: rescored, re-banded and re-postured.
        rescored = get_parcel(client, member_a["id"])
        assert_risk(rescored, 70.49, "HIGH", basis="POST_INSPECTION_VERIFIED")
        assert_posture(rescored, "NON_COMPLIANT", open_violation_count=1)

        # First read of the citation the cascade wrote.
        rows, meta = list_notices(client, parcel_id=member_a["id"])
        assert meta["total_count"] == 1
        notice = rows[0]
        assert notice["severity"] == "MAJOR"
        assert_instant(notice["delivered_at_utc"], "2026-08-06T00:00:00Z")
        assert_end_of_day(notice["deadline_utc"], "2026-09-05")

        # First read of the denormalized community field: it does not lag.
        assert_2dp(get_community(client, community_id)["compliance_rate_pct"], 0.00)
        community_view = community_metrics(client, community_id)
        assert_metrics(community_view, 1, 0, 0.00)
        assert community_view["member_parcel_count"] == 3

        # The district scope agrees in the same instant; B and C are excluded.
        assert_metrics(cycle_metrics(client, world["cycle"]["id"]), 1, 0, 0.00)
        assert_posture(get_parcel(client, member_b["id"]), "PENDING_INSPECTION")
        assert_posture(get_parcel(client, member_c["id"]), "PENDING_INSPECTION")

        # No clock movement and no cycle advance, so convergence cannot be
        # attributed to a background pass.
        assert get_cycle(client, world["cycle"]["id"])["epoch"] == 0
