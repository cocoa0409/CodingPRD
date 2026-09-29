"""Partial updates, bulk splits, cross-linked ballots, the read-only what-if,
the per-category award preconditions, and the release action."""
import pytest

from test_helpers import (
    api_client,
    cast_ballot,
    make_clerk_headers,
    make_commissioner_headers,
    make_secretary_headers,
    make_treasurer_headers,
    open_balloting,
    read_association,
    read_bid,
    read_charge,
    read_member,
    read_parcel,
    read_project,
    read_roll,
    reclassify_parcel_payload,
    release_payload,
    record_access_inspection,
    set_clock,
    setup_assessment_roll,
    setup_association,
    setup_membership_roll,
    setup_parcel,
    setup_project,
    setup_proposal,
    setup_road_segment,
    submit_bid,
    subdivide,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import award_project as award
from test_helpers import list_roll_charges
from test_helpers import setup_delinquent_charge

SECRETARY = make_secretary_headers("sec-1")
CLERK = make_clerk_headers("clerk-1")
TREASURER = make_treasurer_headers("bt-1")
SECOND_COMMISSIONER = make_commissioner_headers("rc-2")

MAIN_SEGMENT = {
    "length_feet": 1600,
    "width_feet": 22,
    "max_grade_pct": 8,
    "surface_type": "GRAVEL",
    "turnout_count": 1,
    "turnaround_present": True,
    "bridge_present": False,
    "culvert_count": 2,
}


class TestReclassificationIsGenuinelyPartial:
    """Two patches, two version bumps, and the untouched field stays put."""

    def _parcel(self):
        association = setup_association(
            name="Patchwork Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Patchwork Main", **MAIN_SEGMENT)
        return setup_parcel(
            segment["id"],
            deed_book_page="DB154-P01",
            frontage_feet=290,
            usage_class="RESIDENTIAL_YEAR_ROUND",
            trips_per_day=6,
            covenant_recorded=True,
        )

    def test_the_first_patch_leaves_the_frontage_alone(self, api):
        """PRD §3.2: "Reclassifying a parcel is an `AssociationSecretary` operation
        that takes `expected_parcel_version` plus any subset of `frontage_feet`,
        `usage_class`, and `trips_per_day`. Only the supplied fields are
        overwritten, and both share units are recomputed afterwards."

        Design: Corner/endpoints/parcel_patch_partial_update_recomputes_both_share_units
        """
        parcel = self._parcel()
        assert parcel["version"] == 1
        assert parcel["status"] == "ACTIVE"
        assert parcel["frontage_share_units"] == pytest.approx(290.0, abs=0.0001)
        assert parcel["trip_share_units"] == pytest.approx(208.0, abs=0.0001)

        patched = validate_success(
            api_client.reclassify_parcel(
                parcel["id"],
                reclassify_parcel_payload(1, usage_class="COMMERCIAL", trips_per_day=10),
                SECRETARY,
            )
        )

        assert patched["usage_class"] == "COMMERCIAL"
        assert patched["trips_per_day"] == 10
        assert patched["frontage_feet"] == pytest.approx(290, abs=0.01)
        assert patched["frontage_share_units"] == pytest.approx(507.5, abs=0.0001)
        assert patched["trip_share_units"] == pytest.approx(308.0, abs=0.0001)
        assert patched["version"] == 2

    def test_the_second_patch_retains_the_usage_class_it_never_names(self, api):
        """PRD §2.4: "`version` (integer): an integer that starts at 1 and
        increments by one on every mutation of the row."
        PRD §3.2: "Only the supplied fields are overwritten, and both share units
        are recomputed afterwards."

        Design: Corner/endpoints/parcel_patch_partial_update_recomputes_both_share_units
        """
        parcel = self._parcel()
        validate_success(
            api_client.reclassify_parcel(
                parcel["id"],
                reclassify_parcel_payload(1, usage_class="COMMERCIAL", trips_per_day=10),
                SECRETARY,
            )
        )

        patched = validate_success(
            api_client.reclassify_parcel(
                parcel["id"], reclassify_parcel_payload(2, frontage_feet=300), SECRETARY
            )
        )

        assert patched["usage_class"] == "COMMERCIAL", "not named, not reset"
        assert patched["trips_per_day"] == 10
        assert patched["frontage_share_units"] == pytest.approx(525.0, abs=0.0001)
        assert patched["trip_share_units"] == pytest.approx(310.0, abs=0.0001)
        assert patched["version"] == 3

        reread = read_parcel(parcel["id"])
        assert reread == patched, "the read repeats the patch response exactly"
        assert reread["deed_book_page"] == "DB154-P01"
        assert reread["covenant_recorded"] is True
        assert reread["parent_parcel_id"] is None


class TestSubdivisionIsOneBulkAction:
    """Three children, one envelope, one version bump on the parent."""

    def _split(self):
        association = setup_association(
            name="Three Lot Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Three Lot Main", **MAIN_SEGMENT)
        parent = setup_parcel(
            segment["id"],
            deed_book_page="DB155-P01",
            frontage_feet=300,
            usage_class="RESIDENTIAL_YEAR_ROUND",
            trips_per_day=5,
            covenant_recorded=True,
        )
        result = subdivide(
            parent["id"],
            [
                {"deed_book_page": "DB155-P01A", "frontage_feet": 180},
                {"deed_book_page": "DB155-P01B", "frontage_feet": 70},
                {"deed_book_page": "DB155-P01C", "frontage_feet": 50},
            ],
        )
        return parent, result

    def test_the_response_carries_the_parent_and_the_children_in_request_order(self, api):
        """PRD §3.2: "The response is an object carrying `parent_parcel` and a
        `children` array returned in the same order as the request's entries, so a
        caller can address a specific new lot without depending on a
        creation-timestamp tie-break."
        PRD §3.2: "the parent moves `ACTIVE → SUBDIVIDED`, leaving the assessable
        set, and its `version` increments by one."

        Design: Corner/endpoints/subdivide_bulk_action_creates_children_and_retires_the_parent
        """
        parent, result = self._split()

        assert set(result) >= {"parent_parcel", "children"}
        assert len(result["children"]) == 3
        assert [c["frontage_feet"] for c in result["children"]] == [
            pytest.approx(180, abs=0.01),
            pytest.approx(70, abs=0.01),
            pytest.approx(50, abs=0.01),
        ]
        assert result["parent_parcel"]["status"] == "SUBDIVIDED"
        assert result["parent_parcel"]["frontage_feet"] == pytest.approx(300, abs=0.01)
        assert result["parent_parcel"]["version"] == 2, (
            "one bump for the whole bulk action, not one per child"
        )
        assert parent["version"] == 1

    def test_every_child_starts_undeveloped_and_addressable_by_its_parent(self, api):
        """PRD §3.2: "On success, one parcel is created per entry in `children`, each
        with `parent_parcel_id` pointing at the parent, `status`
        `PENDING_CONNECTION`, `covenant_recorded` false, `usage_class`
        `UNDEVELOPED`, `trips_per_day` zero, and `road_segment_id` copied from the
        parent"
        PRD §3.2: "they can be found by filtering the parcel list on
        `parent_parcel_id`, and the same list also accepts `road_segment_id` and
        `status` filters."

        Design: Corner/endpoints/subdivide_bulk_action_creates_children_and_retires_the_parent
        """
        parent, result = self._split()

        expected_units = [(45.0, 36.0), (17.5, 14.0), (12.5, 10.0)]
        for child, (frontage_units, trip_units) in zip(result["children"], expected_units):
            assert child["status"] == "PENDING_CONNECTION"
            assert child["usage_class"] == "UNDEVELOPED"
            assert child["trips_per_day"] == 0
            assert child["covenant_recorded"] is False
            assert child["parent_parcel_id"] == parent["id"]
            assert child["road_segment_id"] == parent["road_segment_id"]
            assert child["version"] == 1
            assert child["frontage_share_units"] == pytest.approx(frontage_units, abs=0.0001)
            assert child["trip_share_units"] == pytest.approx(trip_units, abs=0.0001)

        rows, meta = validate_paginated(
            api_client.list_parcels(
                SECRETARY, params={"parent_parcel_id": parent["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 3
        assert {row["id"] for row in rows} == {c["id"] for c in result["children"]}


TWO_VOTERS = [
    {
        "deed_book_page": "DB156-P01",
        "frontage_feet": 240,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 4,
    },
    {
        "deed_book_page": "DB156-P02",
        "frontage_feet": 200,
        "usage_class": "SEASONAL",
        "trips_per_day": 2,
    },
]


def _two_voter_round():
    set_clock("2026-08-01T00:00:00Z")
    scenario = setup_membership_roll(
        parcel_specs=TWO_VOTERS,
        association_overrides={
            "name": "Two Voter Road Association",
            "reserve_target_cents": 1_000_000,
        },
        segment_overrides=dict(MAIN_SEGMENT, name="Two Voter Main"),
    )
    proposal = setup_proposal(
        scenario,
        project_type="GRADING",
        title="Spring regrade",
        estimated_cost_cents=1_500_000,
        cost_allocation_method="EQUAL_SHARE",
    )
    scenario["proposal"] = open_balloting(proposal["id"], "2026-08-15T00:00:00Z")
    return scenario


class TestABallotLinksBothParents:
    """One POST, one snapshot, and the link reads from either end."""

    def test_the_round_opens_with_one_vote_per_verified_member(self, api):
        """PRD §3.5: "Under `PER_PARCEL` the weight is one — one vote per deeded
        membership regardless of assessment size, so small parcels carry the same
        weight as large ones."
        PRD §3.5: "Opening the round snapshots `eligible_weight_total` as the summed
        voting weight of the eligible voter set at that moment, stamps
        `balloting_opened_at`, resets `counted_weight_total`, `yes_weight_total`,
        `no_weight_total`, and `abstain_weight_total` to zero, sets `quorum_met` to
        false, and recomputes `required_threshold_bps` from the current
        `reserve_posture` and freezes it for this round."

        Design: Corner/endpoints/ballot_cross_reference_links_proposal_and_member_with_a_weight_snapshot
        """
        scenario = _two_voter_round()
        proposal = scenario["proposal"]

        assert proposal["status"] == "BALLOTING"
        assert proposal["eligible_weight_total"] == pytest.approx(2, abs=0.0001)
        assert proposal["required_threshold_bps"] == 5500, (
            "GRADING's 5000 plus 500 for the UNDERFUNDED reserve"
        )
        assert proposal["quorum_met"] is False
        assert proposal["counted_weight_total"] == pytest.approx(0, abs=0.0001)

    def test_the_ballot_freezes_a_weight_and_is_visible_from_both_sides(self, api):
        """PRD §3.5: "The new ballot starts `CAST`, has `cast_at` stamped with the
        current logical-clock instant, and freezes its `weight_snapshot` from the
        weight computation above under the proposal's basis."
        PRD §3.5: "Ballots may be read individually, listed per proposal, or listed
        across proposals with `proposal_id`, `member_id`, and `status` filters."

        Design: Corner/endpoints/ballot_cross_reference_links_proposal_and_member_with_a_weight_snapshot
        """
        scenario = _two_voter_round()
        proposal = scenario["proposal"]
        voter, absentee = scenario["members"]

        ballot = cast_ballot(proposal, voter, "YES", proposal["version"])

        assert ballot["proposal_id"] == proposal["id"]
        assert ballot["member_id"] == voter["id"]
        assert ballot["choice"] == "YES"
        assert ballot["status"] == "CAST"
        assert ballot["weight_snapshot"] == pytest.approx(1, abs=0.0001)
        assert ballot["cast_at"].startswith("2026-08-01T00:00:00")

        from_proposal, proposal_meta = validate_paginated(
            api_client.list_proposal_ballots(proposal["id"], TREASURER, params={"limit": 100})
        )
        assert proposal_meta["total_count"] == 1
        assert from_proposal[0]["id"] == ballot["id"]

        from_member, member_meta = validate_paginated(
            api_client.list_member_ballots(voter["id"], TREASURER, params={"limit": 100})
        )
        assert member_meta["total_count"] == 1
        assert from_member[0]["id"] == ballot["id"]

        _, absentee_meta = validate_paginated(
            api_client.list_member_ballots(absentee["id"], TREASURER, params={"limit": 100})
        )
        assert absentee_meta["total_count"] == 0

    def test_one_of_two_votes_meets_the_bare_majority_quorum(self, api):
        """PRD §3.5: "`quorum_met` is recomputed on every ballot mutation and is
        true exactly when `counted_weight_total` multiplied by ten thousand is at
        least `eligible_weight_total` multiplied by the association's `quorum_bps`."
        PRD §3.1: "`quorum_bps` is the participation quorum in basis points, must lie
        between 1 and 10000, and defaults to 5000 — a bare majority of eligible
        weight."

        Design: Corner/endpoints/ballot_cross_reference_links_proposal_and_member_with_a_weight_snapshot
        """
        scenario = _two_voter_round()
        proposal = scenario["proposal"]
        voter = scenario["members"][0]

        cast_ballot(proposal, voter, "YES", proposal["version"])

        tallied = validate_success(
            api_client.get_proposal(proposal["id"], TREASURER)
        )
        assert tallied["counted_weight_total"] == pytest.approx(1, abs=0.0001)
        assert tallied["yes_weight_total"] == pytest.approx(1, abs=0.0001)
        assert tallied["no_weight_total"] == pytest.approx(0, abs=0.0001)
        assert tallied["abstain_weight_total"] == pytest.approx(0, abs=0.0001)
        assert tallied["quorum_met"] is True, "1 * 10000 >= 2 * 5000 holds with equality"
        assert tallied["eligible_weight_total"] == pytest.approx(2, abs=0.0001)


FOUR_DIVERGENT = [
    {
        "deed_book_page": "DB157-P01",
        "frontage_feet": 300,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 4,
    },
    {
        "deed_book_page": "DB157-P02",
        "frontage_feet": 300,
        "usage_class": "SEASONAL",
        "trips_per_day": 8,
    },
    {
        "deed_book_page": "DB157-P03",
        "frontage_feet": 400,
        "usage_class": "AGRICULTURAL",
        "trips_per_day": 6,
    },
    {
        "deed_book_page": "DB157-P04",
        "frontage_feet": 200,
        "usage_class": "COMMERCIAL",
        "trips_per_day": 2,
    },
]


def _divergent_draft_roll():
    set_clock("2026-08-01T00:00:00Z")
    scenario = setup_membership_roll(
        parcel_specs=FOUR_DIVERGENT,
        association_overrides={
            "name": "Divergence Road Association",
            "reserve_target_cents": 1_000_000,
        },
        segment_overrides=dict(MAIN_SEGMENT, name="Divergence Main"),
    )
    scenario["roll"] = setup_assessment_roll(
        scenario["association"]["id"],
        fiscal_year=2026,
        fy_start_date="2026-01-01",
        fy_end_date="2026-12-31",
        budget_requirement_cents=2_900_029,
        method_variant="FRONTAGE_WEIGHTED",
    )
    return scenario


class TestTheMethodComparisonIsAReadOnlyWhatIf:
    """Both allocations, side by side, with nothing written down."""

    def test_the_comparison_reports_both_totals_and_the_divergence(self, api):
        """PRD §3.4: "It answers with an object carrying `roll_id`, the roll's own
        `method_variant`, `frontage_weighted_total_cents`,
        `trip_generation_weighted_total_cents`,
        `frontage_weighted_unallocated_residual_cents`,
        `trip_generation_weighted_unallocated_residual_cents`,
        `divergent_parcel_count` — the number of parcels whose rounded amount
        differs between the two methods — and `max_absolute_divergence_cents`, the
        largest absolute per-parcel difference."

        Design: Corner/endpoints/method_comparison_computed_read_reports_both_variants_without_mutating_the_roll
        """
        scenario = _divergent_draft_roll()

        comparison = validate_success(
            api_client.get_method_comparison(scenario["roll"]["id"], TREASURER)
        )

        assert comparison["roll_id"] == scenario["roll"]["id"]
        assert comparison["method_variant"] == "FRONTAGE_WEIGHTED"
        assert comparison["frontage_weighted_total_cents"] == 2_900_030
        assert comparison["frontage_weighted_unallocated_residual_cents"] == -1
        assert comparison["trip_generation_weighted_total_cents"] == 2_900_028
        assert comparison["trip_generation_weighted_unallocated_residual_cents"] == 1
        assert comparison["divergent_parcel_count"] == 4
        assert comparison["max_absolute_divergence_cents"] == 565_011

    def test_the_comparison_writes_nothing_at_all(self, api):
        """PRD §3.4: "This capability runs the full eight-step allocation under
        **both** method variants and mutates nothing at all — no charges, no totals,
        no versions."

        Design: Corner/endpoints/method_comparison_computed_read_reports_both_variants_without_mutating_the_roll
        """
        scenario = _divergent_draft_roll()
        validate_success(api_client.get_method_comparison(scenario["roll"]["id"], TREASURER))

        roll = read_roll(scenario["roll"]["id"])
        assert roll["status"] == "DRAFT"
        assert roll["total_share_units"] == pytest.approx(0, abs=0.0001)
        assert roll["total_levied_cents"] == 0
        assert roll["unallocated_residual_cents"] == 0
        assert roll["certified_at"] is None
        assert roll["version"] == 1
        assert list_roll_charges(roll["id"]) == []


class TestAwardPreconditionsVaryByCategory:
    """One endpoint, two categories, two different sets of gates."""

    def _blacktop(self):
        set_clock("2026-08-01T00:00:00Z")
        association = setup_association(
            name="Blacktop Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Blacktop Main", **MAIN_SEGMENT)
        paving = setup_project(
            segment["id"],
            category="PAVING",
            window_start_date="2026-09-01",
            window_end_date="2026-09-10",
        )
        bid = submit_bid(
            paving, 500_000, contractor_user_id="c-1", contractor_name="Basin Paving LLC"
        )
        return association, segment, paving, bid

    def test_an_uninspected_segment_blocks_the_paving_award(self, api):
        """PRD §2.7: "Awarding a `PAVING` project requires the segment to be
        `COMPLIANT`."
        PRD §2.10: "28. The emergency-vehicle access standard, at the strictnesses
        given in §2.7 — otherwise `ERR_EMERGENCY_ACCESS_DEFICIENT` (409), on project
        award, remedy effectuation, and connection decision."

        Design: Corner/endpoints/paving_award_is_conditional_on_a_compliant_segment_and_a_funded_reserve
        """
        _, segment, paving, bid = self._blacktop()
        assert read_project(paving["id"])["status"] == "BID_SOLICITATION"

        response = api_client.award_project(
            paving["id"], {"bid_id": bid["id"]}, SECOND_COMMISSIONER
        )

        validate_error(response, "ERR_EMERGENCY_ACCESS_DEFICIENT", 409)

        graded = record_access_inspection(
            segment["id"],
            "2026-08-02T00:00:00Z",
            measured_width_feet=22,
            measured_max_grade_pct=8,
            measured_turnout_count=1,
            turnaround_present=True,
        )
        assert graded["emergency_access_grade"] == "COMPLIANT"
        assert graded["required_turnouts"] == 1
        assert graded["last_inspection_at"] == "2026-08-02T00:00:00Z"

    def test_a_compliant_segment_still_needs_the_reserve_to_cover_the_draw(self, api):
        """PRD §3.7: "And the computed reserve draw must not exceed the
        association's `reserve_balance_cents`, an inclusive comparison that permits a
        draw equal to the whole balance and drives it to exactly zero; exceeding it
        is `ERR_INSUFFICIENT_RESERVE`."

        Design: Corner/endpoints/paving_award_is_conditional_on_a_compliant_segment_and_a_funded_reserve
        """
        association, segment, paving, bid = self._blacktop()
        record_access_inspection(
            segment["id"],
            "2026-08-02T00:00:00Z",
            measured_width_feet=22,
            measured_max_grade_pct=8,
            measured_turnout_count=1,
            turnaround_present=True,
        )

        response = api_client.award_project(
            paving["id"], {"bid_id": bid["id"]}, SECOND_COMMISSIONER
        )

        validate_error(response, "ERR_INSUFFICIENT_RESERVE", 409)
        held = read_project(paving["id"])
        assert held["status"] == "BID_SOLICITATION"
        assert held["awarded_bid_id"] is None
        assert held["awarded_amount_cents"] == 0
        assert held["reserve_draw_cents"] == 0
        assert read_bid(bid["id"])["status"] == "SUBMITTED"
        assert read_association(association["id"])["reserve_balance_cents"] == 0

    def test_the_same_endpoint_awards_operating_work_on_an_empty_reserve(self, api):
        """PRD §3.7: "for the operating categories `GRADING`, `SNOW`, and `DUST` the
        draw is zero, because operating work is funded from the annual levy"
        PRD §3.7: "The project's `awarded_bid_id`, `awarded_amount_cents` (taken
        from the awarded bid's `amount_cents`), and `awarded_by_user_id` are set, and
        `reserve_draw_cents` is set to the computed draw."

        Design: Corner/endpoints/paving_award_is_conditional_on_a_compliant_segment_and_a_funded_reserve
        """
        association, segment, _, _ = self._blacktop()
        record_access_inspection(
            segment["id"],
            "2026-08-02T00:00:00Z",
            measured_width_feet=22,
            measured_max_grade_pct=8,
            measured_turnout_count=1,
            turnaround_present=True,
        )
        grading = setup_project(
            segment["id"],
            category="GRADING",
            window_start_date="2026-09-15",
            window_end_date="2026-09-18",
        )
        grading_bid = submit_bid(
            grading, 400_000, contractor_user_id="c-1", contractor_name="Basin Grading LLC"
        )

        awarded = award(grading["id"], grading_bid["id"])

        assert awarded["status"] == "AWARDED"
        assert awarded["awarded_amount_cents"] == 400_000
        assert awarded["reserve_draw_cents"] == 0
        assert awarded["awarded_by_user_id"] == "rc-2"

        after = read_association(association["id"])
        assert after["reserve_balance_cents"] == 0
        assert after["reserve_posture"] == "UNDERFUNDED"


class TestReleasingAnInitiatedRemedyVoidsIt:
    """The release endpoint branches on where the remedy stands."""

    def _initiated_notice(self):
        return setup_delinquent_charge(
            parcel_specs=[
                {
                    "deed_book_page": "DB158-P01",
                    "frontage_feet": 290,
                    "usage_class": "RESIDENTIAL_YEAR_ROUND",
                    "trips_per_day": 6,
                }
            ],
            levy_clock="2026-08-01T00:00:00Z",
            remedy_clock="2026-10-15T00:00:00Z",
            action_type="NOTICE",
        )

    def test_the_release_lands_on_voided_and_leaves_the_charge_alone(self, api):
        """PRD §3.6: "From `INITIATED`, by contrast, the remedy moves `INITIATED →
        VOIDED`: `released_at` and `release_reason` are stamped,
        `lien_amount_cents` stays zero, the charge stays `DELINQUENT` with no lien
        effect at all, and the member's `standing_status` is re-reconciled — falling
        back to `GOOD_STANDING` only if no delinquent charge of theirs remains."

        Design: Corner/endpoints/release_action_endpoint_voids_an_initiated_notice_without_touching_the_charge
        """
        scenario = self._initiated_notice()

        released = validate_success(
            api_client.release_delinquency_action(
                scenario["action"]["id"],
                release_payload("payment plan accepted by the board"),
                TREASURER,
            )
        )

        assert released["status"] == "VOIDED"
        assert released["released_at"].startswith("2026-10-15T00:00:00")
        assert released["release_reason"] == "payment plan accepted by the board"
        assert released["lien_amount_cents"] == 0
        assert released["effectuated_by_user_id"] is None

        charge = read_charge(scenario["charge"]["id"])
        assert charge["status"] == "DELINQUENT"
        assert charge["balance_cents"] == 1_600_000
        assert charge["paid_cents"] == 0
        assert charge["delinquent_since"] == "2026-10-15"

        member = read_member(scenario["members"][0]["id"])
        assert member["standing_status"] == "DELINQUENT"
        assert member["access_status"] == "UNRESTRICTED"
        assert member["encumbered_principal_cents"] == 0

    def test_a_closed_remedy_cannot_be_released_twice(self, api):
        """PRD §3.6: "A remedy already `RELEASED` or `VOIDED` cannot be released
        again, which is `ERR_ACTION_ALREADY_CLOSED`."

        Design: Corner/endpoints/release_action_endpoint_voids_an_initiated_notice_without_touching_the_charge
        """
        scenario = self._initiated_notice()
        first = validate_success(
            api_client.release_delinquency_action(
                scenario["action"]["id"],
                release_payload("payment plan accepted by the board"),
                TREASURER,
            )
        )

        response = api_client.release_delinquency_action(
            scenario["action"]["id"], release_payload("duplicate release attempt"), TREASURER
        )

        validate_error(response, "ERR_ACTION_ALREADY_CLOSED", 409)
        after = validate_success(
            api_client.get_delinquency_action(scenario["action"]["id"], CLERK)
        )
        assert after["released_at"] == first["released_at"]
        assert after["release_reason"] == "payment plan accepted by the board"
