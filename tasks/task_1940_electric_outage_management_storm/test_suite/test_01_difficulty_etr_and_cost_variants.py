"""Difficulty tests — dual_variant_calculation rule.

Covers the provisional-vs-post-assessment ETR variants and the
full-vs-early mutual-aid engagement cost variants.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_instant_equals,
    create_and_activate_event,
    create_confirm_outage_payload,
    create_crew,
    create_damage_assessment_payload,
    create_feeder_record,
    create_mutual_aid_crew_payload,
    create_outage_payload,
    get_success_data,
    make_field_crew_lead_headers,
    set_clock,
    validate_paginated,
)

ED = TEST_USERS["emergency_director_headers"]
DISP = TEST_USERS["dispatcher_headers"]
MAC = TEST_USERS["mutual_aid_coordinator_headers"]


class TestEtrProvisionalVsPostAssessment:
    """Two ETR variants on identical outage attributes diverge predictably."""

    def test_provisional_variant_uses_customer_count_and_cause_factor(self, api):
        """PRD §3.3: "Confirmation stamps `confirmed_at` with the logical now and
        publishes the outage's first ETR revision: sequence 1, reason `INITIAL`,
        `issued_by` recorded as the literal string `system`. Its `published_etr`
        is computed provisionally from what is known before any field assessment —
        a base of 120 minutes of preparation, plus the smaller of
        `customers_affected` and five thousand multiplied by two minutes per
        customer and by a cause factor, that multiplication rounded half up to a
        whole minute before being added to the base."

        Design: Difficulty/dual_variant_calc/etr_provisional_vs_post_assessment
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Alpha", event_type="HURRICANE")
        fd = create_feeder_record(county_code="C1", customer_count=2000)
        ot = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
        )
        confirmed = get_success_data(
            api.confirm_outage(
                ot["id"],
                create_confirm_outage_payload(
                    customers_affected=100, cause_code="TREE"
                ),
                DISP,
            )
        )
        # provisional ETR must be 120 + round_half_up(100*2*1.5) = 420 min
        # after 00:00Z
        assert_instant_equals(confirmed["current_etr"], "2026-08-10T07:00:00Z")
        assert_instant_equals(confirmed["confirmed_at"], "2026-08-10T00:00:00Z")

    def test_post_assessment_variant_uses_repair_minutes_and_crew_factor(self, api):
        """PRD §3.4: "a crew factor of 1.0 applies when any non-cancelled work
        order on the outage already has an internal or mutual-aid assignee, and
        1.5 when none does; the repair component is the accepted assessment's
        `estimated_repair_minutes` multiplied by that factor, rounded half up to
        a whole minute — the rounding is pinned here, before any overhead is
        added — and when the accepted assessment's `requires_switching` is true,
        a forty-five-minute switching overhead is added on top. The published
        instant is the acceptance time plus the total, and `current_etr` moves
        to it."

        Design: Difficulty/dual_variant_calc/etr_provisional_vs_post_assessment
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Alpha", event_type="HURRICANE")
        fd = create_feeder_record(county_code="C1", customer_count=2000)
        ot = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
        )
        confirmed = get_success_data(
            api.confirm_outage(
                ot["id"],
                create_confirm_outage_payload(
                    customers_affected=100, cause_code="TREE"
                ),
                DISP,
            )
        )
        provisional_etr = confirmed["current_etr"]
        outage_version = confirmed["version"]
        cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
        set_clock("2026-08-10T00:30:00Z")
        fcl = make_field_crew_lead_headers(cr_a["id"])
        da = get_success_data(
            api.create_damage_assessment(
                create_damage_assessment_payload(
                    ot["id"],
                    damage_class="MAJOR",
                    estimated_repair_minutes=241,
                    requires_switching=False,
                ),
                fcl,
            )
        )
        get_success_data(api.submit_damage_assessment(da["id"], fcl))
        get_success_data(
            api.accept_damage_assessment(
                da["id"], {"expected_outage_version": outage_version}, DISP
            )
        )
        final = get_success_data(api.get_outage(ot["id"], DISP))
        # post-assessment ETR must be 00:30Z + round_half_up(241*1.5)=362 min
        assert_instant_equals(final["current_etr"], "2026-08-10T06:32:00Z")
        assert final["current_etr"] != provisional_etr, (
            "the two variants must produce different ETRs on identical outage data"
        )

        revisions, meta = validate_paginated(api.list_etr_revisions(ot["id"], DISP))
        assert meta["total_count"] == 2
        seq1, seq2 = revisions[0], revisions[1]
        assert seq1["revision_reason"] == "INITIAL"
        assert seq1["previous_etr"] is None
        assert seq2["revision_reason"] == "DAMAGE_FOUND"
        assert seq2["issued_by"] == "system"
        assert_instant_equals(seq2["previous_etr"], "2026-08-10T07:00:00Z")


class TestMutualAidFullVsEarlyEngagementCost:
    """Identical windows and rates settle differently under full vs early release."""

    def test_early_release_pays_actual_days_plus_penalty(self, api):
        """PRD §3.7: "An early release — `departure_reason` of `EARLY_RELEASE`
        with departure before `committed_window_end` — adds a penalty: the
        remaining time to `committed_window_end`, rounded up to whole days the
        same way, multiplied by the daily rate and by twenty-five percent, with
        the product rounded half up to whole cents; per-diem is never paid on
        the penalty, and rounding is applied only at this final penalty step.
        Departure then posts a `LABOR_MUTUAL_AID` ledger entry for the
        actual-days portion against the crew's `service_county_code` and, when
        the penalty is positive, a separate `MUTUAL_AID_PENALTY` entry — which
        is FEMA-ineligible — and recomputes the event's
        `total_mutual_aid_cents`, `total_labor_cents`, `total_event_cost_cents`,
        and `om_cost_cents`."

        Design: Difficulty/dual_variant_calc/mutual_aid_full_vs_early_engagement_cost
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Beta", event_type="ICE_STORM")
        ma = get_success_data(
            api.create_mutual_aid_crew(
                create_mutual_aid_crew_payload(
                    ev["id"],
                    committed_window_start="2026-08-10T00:00:00Z",
                    committed_window_end="2026-08-14T00:00:00Z",
                    company_name="PeerCo A",
                    crew_type="LINE",
                    roster_size=4,
                    daily_rate_cents=50000,
                    per_diem_cents=7500,
                    service_county_code="C1",
                ),
                MAC,
            )
        )
        get_success_data(api.mark_arrived(ma["id"], MAC))
        get_success_data(api.demobilize_mutual_aid_crew(ma["id"], MAC))
        set_clock("2026-08-12T00:00:00Z")
        departed = get_success_data(
            api.depart_mutual_aid_crew(
                ma["id"], {"departure_reason": "EARLY_RELEASE"}, MAC
            )
        )
        # 2 actual days x (50000 + 4*7500) = 160000;
        # penalty = round_half_up(2 * 50000 * 0.25) = 25000.
        assert departed["engagement_cost_cents"] == 185000, (
            f"early release must settle at 185000 cents; got "
            f"{departed['engagement_cost_cents']}"
        )

        entries, _meta = validate_paginated(
            api.list_cost_ledger_entries(MAC, params={"storm_event_id": ev["id"]})
        )
        labor = [e for e in entries if e["entry_type"] == "LABOR_MUTUAL_AID"]
        penalty = [e for e in entries if e["entry_type"] == "MUTUAL_AID_PENALTY"]
        assert len(labor) == 1 and labor[0]["amount_cents"] == 160000
        # Per-diem must NOT be paid on the penalty: 25000 = 2 * 50000 * 0.25.
        assert len(penalty) == 1 and penalty[0]["amount_cents"] == 25000

    def test_full_engagement_has_no_penalty(self, api):
        """PRD §3.7: "When the departure carries a `departure_reason` of
        `COMPLETED`, or the crew departs at or after `committed_window_end`, the
        engagement cost is the actual days times the daily cost with no
        penalty."

        Design: Difficulty/dual_variant_calc/mutual_aid_full_vs_early_engagement_cost
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Beta", event_type="ICE_STORM")
        mb = get_success_data(
            api.create_mutual_aid_crew(
                create_mutual_aid_crew_payload(
                    ev["id"],
                    committed_window_start="2026-08-10T00:00:00Z",
                    committed_window_end="2026-08-14T00:00:00Z",
                    company_name="PeerCo B",
                    crew_type="LINE",
                    roster_size=4,
                    daily_rate_cents=50000,
                    per_diem_cents=7500,
                    service_county_code="C1",
                ),
                MAC,
            )
        )
        get_success_data(api.mark_arrived(mb["id"], MAC))
        set_clock("2026-08-14T00:00:00Z")
        get_success_data(api.demobilize_mutual_aid_crew(mb["id"], MAC))
        departed = get_success_data(
            api.depart_mutual_aid_crew(
                mb["id"], {"departure_reason": "COMPLETED"}, MAC
            )
        )
        # 4 actual days x (50000 + 4*7500) = 320000; no penalty.
        assert departed["engagement_cost_cents"] == 320000, (
            f"full engagement must settle at 320000 cents; got "
            f"{departed['engagement_cost_cents']}"
        )

        entries, _meta = validate_paginated(
            api.list_cost_ledger_entries(MAC, params={"storm_event_id": ev["id"]})
        )
        labor = [e for e in entries if e["entry_type"] == "LABOR_MUTUAL_AID"]
        penalty = [e for e in entries if e["entry_type"] == "MUTUAL_AID_PENALTY"]
        assert len(labor) == 1 and labor[0]["amount_cents"] == 320000
        assert len(penalty) == 0

        ev_final = get_success_data(api.get_storm_event(ev["id"], MAC))
        assert ev_final["total_mutual_aid_cents"] == 320000
        assert ev_final["total_event_cost_cents"] == 320000
