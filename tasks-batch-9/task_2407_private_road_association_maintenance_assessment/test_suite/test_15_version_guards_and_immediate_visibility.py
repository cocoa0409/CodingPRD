"""The three version guards each outrank the state guard behind them, and every
derived field is already present in the response that caused it."""
import pytest

from test_helpers import (
    api_client,
    create_contractor_bid_payload,
    create_ballot_payload,
    make_clerk_headers,
    make_commissioner_headers,
    make_contractor_headers,
    make_member_owner_headers,
    make_secretary_headers,
    make_treasurer_headers,
    open_balloting,
    read_parcel,
    read_project,
    reclassify_parcel_payload,
    set_clock,
    setup_assessment_roll,
    setup_association,
    setup_membership_roll,
    setup_parcel,
    setup_project,
    setup_proposal,
    setup_road_segment,
    submit_bid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import award_project as award

SECRETARY = make_secretary_headers("sec-1")
CLERK = make_clerk_headers("clerk-1")
TREASURER = make_treasurer_headers("bt-1")
FIRST_COMMISSIONER = make_commissioner_headers("rc-1")
SECOND_COMMISSIONER = make_commissioner_headers("rc-2")
SECOND_CONTRACTOR = make_contractor_headers("c-2")

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

TWO_VOTERS = [
    {
        "deed_book_page": "DB176-P01",
        "frontage_feet": 240,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 4,
        "covenant_recorded": True,
    },
    {
        "deed_book_page": "DB176-P02",
        "frontage_feet": 200,
        "usage_class": "SEASONAL",
        "trips_per_day": 2,
        "covenant_recorded": True,
    },
]


class TestStaleProjectVersionOutranksTheSolicitationStateGuard:
    """A bid written against the pre-award project reports the version mismatch,
    not the closed solicitation."""

    def _awarded_project(self):
        """A GRADING project opened by rc-1, bid at 500,000 cents by c-1, and
        awarded by rc-2 so the project version has moved past creation."""
        set_clock("2026-08-01T00:00:00Z")
        association = setup_association(
            name="Stale Bid Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Stale Bid Main", **MAIN_SEGMENT)
        project = setup_project(
            segment["id"],
            category="GRADING",
            window_start_date="2026-08-05",
            window_end_date="2026-08-08",
        )
        bid = submit_bid(
            project,
            500_000,
            contractor_user_id="c-1",
            contractor_name="Basin Grading LLC",
            bond_on_file=True,
        )
        awarded = award(project["id"], bid["id"], SECOND_COMMISSIONER)
        return {
            "project": project,
            "creation_version": project["version"],
            "bid": bid,
            "awarded": awarded,
        }

    def test_the_award_leaves_the_creation_version_behind(self, api):
        """PRD §3.7: "The submission increments the project's `version` by one, which is
        exactly why the next bidder's stale version is detectable."

        Design: Corner/complexity_layers/stale_project_version_outranks_the_solicitation_state_guard
        """
        scenario = self._awarded_project()

        assert scenario["awarded"]["status"] == "AWARDED"
        assert scenario["awarded"]["awarded_amount_cents"] == 500_000
        assert scenario["awarded"]["version"] > scenario["creation_version"]

    def test_the_pre_award_version_reports_the_concurrency_error(self, api):
        """PRD §2.9: "If that value does not equal the project's current `version`, the
        submission is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/stale_project_version_outranks_the_solicitation_state_guard
        """
        scenario = self._awarded_project()

        validate_error(
            api_client.create_contractor_bid(
                scenario["project"]["id"],
                create_contractor_bid_payload(
                    scenario["creation_version"],
                    contractor_name="Highline Roadworks",
                    amount_cents=450_000,
                    bond_on_file=True,
                ),
                SECOND_CONTRACTOR,
            ),
            "ERR_STALE_PROJECT_VERSION",
            412,
        )

    def test_the_refreshed_version_then_reaches_the_state_guard(self, api):
        """PRD §2.10: "22. The project's `status` is `BID_SOLICITATION` for bid
        submission and for award — otherwise `ERR_PROJECT_NOT_IN_SOLICITATION` (409)."

        Design: Corner/complexity_layers/stale_project_version_outranks_the_solicitation_state_guard
        """
        scenario = self._awarded_project()
        current_version = read_project(scenario["project"]["id"])["version"]

        validate_error(
            api_client.create_contractor_bid(
                scenario["project"]["id"],
                create_contractor_bid_payload(
                    current_version,
                    contractor_name="Highline Roadworks",
                    amount_cents=450_000,
                    bond_on_file=True,
                ),
                SECOND_CONTRACTOR,
            ),
            "ERR_PROJECT_NOT_IN_SOLICITATION",
            409,
        )

    def test_neither_rejected_submission_created_a_bid_row(self, api):
        """PRD §2.10: "9. `expected_project_version` matches the project's `version` —
        otherwise `ERR_STALE_PROJECT_VERSION` (412), on bid submission."

        Design: Corner/complexity_layers/stale_project_version_outranks_the_solicitation_state_guard
        """
        scenario = self._awarded_project()
        stale_payload = create_contractor_bid_payload(
            scenario["creation_version"],
            contractor_name="Highline Roadworks",
            amount_cents=450_000,
            bond_on_file=True,
        )
        validate_error(
            api_client.create_contractor_bid(
                scenario["project"]["id"], stale_payload, SECOND_CONTRACTOR
            ),
            "ERR_STALE_PROJECT_VERSION",
            412,
        )
        fresh_payload = dict(
            stale_payload,
            expected_project_version=read_project(scenario["project"]["id"])["version"],
        )
        validate_error(
            api_client.create_contractor_bid(
                scenario["project"]["id"], fresh_payload, SECOND_CONTRACTOR
            ),
            "ERR_PROJECT_NOT_IN_SOLICITATION",
            409,
        )

        _, meta = validate_paginated(
            api_client.list_project_bids(scenario["project"]["id"], FIRST_COMMISSIONER)
        )
        assert meta["total_count"] == 1


class TestStaleProposalVersionRejectsACastAgainstAnUnseenTally:
    """The second voter's cast carries the version the first voter already moved."""

    def _open_round(self):
        """Two verified members and one GRADING proposal in BALLOTING until
        2026-08-15T00:00:00Z, capturing the version seen at open-balloting."""
        set_clock("2026-08-01T00:00:00Z")
        scenario = setup_membership_roll(
            parcel_specs=TWO_VOTERS,
            association_overrides={
                "name": "Stale Ballot Road Association",
                "reserve_target_cents": 1_000_000,
            },
            segment_overrides=dict(name="Stale Ballot Main", **MAIN_SEGMENT),
        )
        proposal = setup_proposal(
            scenario,
            project_type="GRADING",
            title="Concurrent ballots",
            estimated_cost_cents=1_500_000,
            cost_allocation_method="EQUAL_SHARE",
        )
        scenario["proposal"] = open_balloting(
            proposal["id"], "2026-08-15T00:00:00Z", TREASURER
        )
        scenario["open_version"] = scenario["proposal"]["version"]
        return scenario

    def _cast(self, scenario, index, choice, expected_version):
        member = scenario["members"][index]
        return api_client.create_ballot(
            create_ballot_payload(
                scenario["proposal"]["id"], member["id"], choice, expected_version
            ),
            make_member_owner_headers(member["id"]),
        )

    def test_the_first_cast_advances_the_tally_and_the_version(self, api):
        """PRD §3.5: "The new ballot starts `CAST`, has `cast_at` stamped with the current
        logical-clock instant, and freezes its `weight_snapshot` from the weight
        computation above under the proposal's basis."

        Design: Corner/complexity_layers/stale_proposal_version_rejects_a_cast_written_against_an_unseen_tally
        """
        scenario = self._open_round()

        ballot = validate_success(
            self._cast(scenario, 0, "YES", scenario["open_version"]), 201
        )
        assert ballot["weight_snapshot"] == pytest.approx(1.0, abs=0.0001)

        proposal = validate_success(
            api_client.get_proposal(scenario["proposal"]["id"], TREASURER)
        )
        assert proposal["counted_weight_total"] == pytest.approx(1.0, abs=0.0001)
        assert proposal["yes_weight_total"] == pytest.approx(1.0, abs=0.0001)
        assert proposal["version"] > scenario["open_version"]

    def test_the_second_cast_replaying_the_open_version_is_rejected(self, api):
        """PRD §2.9: "A mismatch with the proposal's current `version` is rejected with
        `ERR_STALE_PROPOSAL_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/stale_proposal_version_rejects_a_cast_written_against_an_unseen_tally
        """
        scenario = self._open_round()
        validate_success(self._cast(scenario, 0, "YES", scenario["open_version"]), 201)

        validate_error(
            self._cast(scenario, 1, "NO", scenario["open_version"]),
            "ERR_STALE_PROPOSAL_VERSION",
            412,
        )

        proposal = validate_success(
            api_client.get_proposal(scenario["proposal"]["id"], TREASURER)
        )
        assert proposal["counted_weight_total"] == pytest.approx(1.0, abs=0.0001)

    def test_the_refreshed_version_admits_the_identical_cast(self, api):
        """PRD §2.10: "10. `expected_proposal_version` matches the proposal's `version` —
        otherwise `ERR_STALE_PROPOSAL_VERSION` (412), on ballot casting and ballot
        revocation."

        Design: Corner/complexity_layers/stale_proposal_version_rejects_a_cast_written_against_an_unseen_tally
        """
        scenario = self._open_round()
        validate_success(self._cast(scenario, 0, "YES", scenario["open_version"]), 201)
        validate_error(
            self._cast(scenario, 1, "NO", scenario["open_version"]),
            "ERR_STALE_PROPOSAL_VERSION",
            412,
        )

        refreshed = validate_success(
            api_client.get_proposal(scenario["proposal"]["id"], TREASURER)
        )["version"]
        second = validate_success(self._cast(scenario, 1, "NO", refreshed), 201)
        assert second["weight_snapshot"] == pytest.approx(1.0, abs=0.0001)

        proposal = validate_success(
            api_client.get_proposal(scenario["proposal"]["id"], TREASURER)
        )
        assert proposal["counted_weight_total"] == pytest.approx(2.0, abs=0.0001)
        assert proposal["yes_weight_total"] == pytest.approx(1.0, abs=0.0001)
        assert proposal["no_weight_total"] == pytest.approx(1.0, abs=0.0001)
        assert proposal["quorum_met"] is True

    def test_the_rejected_cast_created_no_ballot_row(self, api):
        """PRD §3.5: "Ballots may be read individually, listed per proposal, or listed
        across proposals with `proposal_id`, `member_id`, and `status` filters."

        Design: Corner/complexity_layers/stale_proposal_version_rejects_a_cast_written_against_an_unseen_tally
        """
        scenario = self._open_round()
        validate_success(self._cast(scenario, 0, "YES", scenario["open_version"]), 201)
        validate_error(
            self._cast(scenario, 1, "NO", scenario["open_version"]),
            "ERR_STALE_PROPOSAL_VERSION",
            412,
        )
        refreshed = validate_success(
            api_client.get_proposal(scenario["proposal"]["id"], TREASURER)
        )["version"]
        validate_success(self._cast(scenario, 1, "NO", refreshed), 201)

        _, meta = validate_paginated(
            api_client.list_proposal_ballots(scenario["proposal"]["id"], TREASURER)
        )
        assert meta["total_count"] == 2


class TestStaleParcelVersionRejectsAnOverwriteOfAnUnseenReclassification:
    """Two reclassifications are each legal, so only the version tells them apart."""

    def _fresh_parcel(self):
        """One 240-foot RESIDENTIAL_YEAR_ROUND parcel with no roll in existence."""
        association = setup_association(
            name="Lost Update Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Lost Update Main", **MAIN_SEGMENT)
        parcel = setup_parcel(
            segment["id"],
            deed_book_page="DB177-P01",
            frontage_feet=240,
            usage_class="RESIDENTIAL_YEAR_ROUND",
            trips_per_day=4,
            covenant_recorded=True,
        )
        return parcel

    def test_the_first_reclassification_recomputes_the_frontage_unit(self, api):
        """PRD §3.2: "Only the supplied fields are overwritten, and both share units are
        recomputed afterwards."

        Design: Corner/complexity_layers/stale_parcel_version_rejects_an_overwrite_of_an_unseen_reclassification
        """
        parcel = self._fresh_parcel()
        assert parcel["version"] == 1

        commercial = validate_success(
            api_client.reclassify_parcel(
                parcel["id"],
                reclassify_parcel_payload(parcel["version"], usage_class="COMMERCIAL"),
                SECRETARY,
            )
        )
        assert commercial["usage_class"] == "COMMERCIAL"
        assert commercial["frontage_share_units"] == pytest.approx(420.0, abs=0.0001)
        assert commercial["version"] == 2

    def test_replaying_the_creation_version_cannot_overwrite_it(self, api):
        """PRD §2.9: "Reclassifying a parcel must carry `expected_parcel_version` holding
        the `version` of the target `Parcel` as the client last observed it. A mismatch is
        rejected with `ERR_STALE_PARCEL_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/stale_parcel_version_rejects_an_overwrite_of_an_unseen_reclassification
        """
        parcel = self._fresh_parcel()
        validate_success(
            api_client.reclassify_parcel(
                parcel["id"],
                reclassify_parcel_payload(parcel["version"], usage_class="COMMERCIAL"),
                SECRETARY,
            )
        )

        validate_error(
            api_client.reclassify_parcel(
                parcel["id"],
                reclassify_parcel_payload(parcel["version"], usage_class="SEASONAL"),
                SECRETARY,
            ),
            "ERR_STALE_PARCEL_VERSION",
            412,
        )

        unchanged = read_parcel(parcel["id"])
        assert unchanged["usage_class"] == "COMMERCIAL"
        assert unchanged["frontage_share_units"] == pytest.approx(420.0, abs=0.0001)
        assert unchanged["version"] == 2

    def test_the_refreshed_version_admits_the_same_edit(self, api):
        """PRD §3.2: "`frontage_share_units` is the parcel's `frontage_feet` multiplied by
        the multiplier for its `usage_class`. `trip_share_units` is the parcel's
        `trips_per_day` multiplied by twenty-five, plus its `frontage_feet` multiplied by
        two tenths."

        Design: Corner/complexity_layers/stale_parcel_version_rejects_an_overwrite_of_an_unseen_reclassification
        """
        parcel = self._fresh_parcel()
        commercial = validate_success(
            api_client.reclassify_parcel(
                parcel["id"],
                reclassify_parcel_payload(parcel["version"], usage_class="COMMERCIAL"),
                SECRETARY,
            )
        )

        seasonal = validate_success(
            api_client.reclassify_parcel(
                parcel["id"],
                reclassify_parcel_payload(commercial["version"], usage_class="SEASONAL"),
                SECRETARY,
            )
        )
        assert seasonal["usage_class"] == "SEASONAL"
        assert seasonal["frontage_share_units"] == pytest.approx(144.0, abs=0.0001)
        assert seasonal["trip_share_units"] == pytest.approx(148.0, abs=0.0001)
        assert seasonal["version"] == 3

    def test_the_version_advances_only_on_accepted_writes(self, api):
        """PRD §2.10: "11. `expected_parcel_version` matches the parcel's `version` —
        otherwise `ERR_STALE_PARCEL_VERSION` (412), on parcel reclassification."

        Design: Corner/complexity_layers/stale_parcel_version_rejects_an_overwrite_of_an_unseen_reclassification
        """
        parcel = self._fresh_parcel()
        seen = [parcel["version"]]

        commercial = validate_success(
            api_client.reclassify_parcel(
                parcel["id"],
                reclassify_parcel_payload(seen[-1], usage_class="COMMERCIAL"),
                SECRETARY,
            )
        )
        seen.append(commercial["version"])

        validate_error(
            api_client.reclassify_parcel(
                parcel["id"],
                reclassify_parcel_payload(parcel["version"], usage_class="SEASONAL"),
                SECRETARY,
            ),
            "ERR_STALE_PARCEL_VERSION",
            412,
        )

        seasonal = validate_success(
            api_client.reclassify_parcel(
                parcel["id"],
                reclassify_parcel_payload(seen[-1], usage_class="SEASONAL"),
                SECRETARY,
            )
        )
        seen.append(seasonal["version"])
        assert seen == [1, 2, 3]


class TestEveryDerivedFieldIsVisibleInTheSameResponseThatCausedIt:
    """No read-after-write lag anywhere along the certify-then-levy chain."""

    def _draft_roll(self):
        """A single 290-foot parcel with a verified member and a DRAFT FY2026 roll
        of 4,000,000 cents against a reserve target of 1,000,000."""
        set_clock("2026-08-01T00:00:00Z")
        scenario = setup_membership_roll(
            parcel_specs=[
                {
                    "deed_book_page": "DB178-P01",
                    "frontage_feet": 290,
                    "usage_class": "RESIDENTIAL_YEAR_ROUND",
                    "trips_per_day": 6,
                    "covenant_recorded": True,
                }
            ],
            association_overrides={
                "name": "No Lag Road Association",
                "reserve_target_cents": 1_000_000,
            },
            segment_overrides=dict(name="No Lag Main", **MAIN_SEGMENT),
        )
        assert scenario["association"]["reserve_balance_cents"] == 0
        scenario["roll"] = setup_assessment_roll(
            scenario["association"]["id"],
            fiscal_year=2026,
            fy_start_date="2026-01-01",
            fy_end_date="2026-12-31",
            budget_requirement_cents=4_000_000,
            method_variant="FRONTAGE_WEIGHTED",
        )
        return scenario

    def test_the_certify_response_itself_carries_the_whole_allocation(self, api):
        """PRD §3.4: "The roll moves `DRAFT → CERTIFIED`, `certified_at` is stamped with
        the current logical-clock instant, and the roll's `version` increments by one."

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_that_caused_it
        """
        scenario = self._draft_roll()

        certified = validate_success(api_client.certify_roll(scenario["roll"]["id"], CLERK))
        assert certified["status"] == "CERTIFIED"
        assert certified["total_share_units"] == pytest.approx(290.0, abs=0.0001)
        assert certified["total_levied_cents"] == 1_600_000
        assert certified["unallocated_residual_cents"] == 2_400_000
        assert certified["certified_at"].startswith("2026-08-01T00:00:00")

    def test_the_charge_is_listable_in_the_very_next_call(self, api):
        """PRD §3.4: "The certification writes one charge per assessable parcel with
        `charge_type` `ANNUAL` and `status` `PENDING`, freezing that parcel's
        `share_units_snapshot` and computed `amount_cents` onto the charge"

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_that_caused_it
        """
        scenario = self._draft_roll()
        validate_success(api_client.certify_roll(scenario["roll"]["id"], CLERK))

        rows, meta = validate_paginated(
            api_client.list_assessment_charges(
                CLERK, params={"roll_id": scenario["roll"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["share_units_snapshot"] == pytest.approx(290.0, abs=0.0001)
        assert rows[0]["amount_cents"] == 1_600_000
        assert rows[0]["status"] == "PENDING"

    def test_the_levy_response_itself_carries_the_reserve_contribution(self, api):
        """PRD §3.4: "`levied_at` is stamped with the current logical-clock instant and
        the roll's own `due_date` is set to the same date."

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_that_caused_it
        """
        scenario = self._draft_roll()
        validate_success(api_client.certify_roll(scenario["roll"]["id"], CLERK))

        levied = validate_success(api_client.levy_roll(scenario["roll"]["id"], TREASURER))
        assert levied["status"] == "LEVIED"
        assert levied["reserve_contribution_cents"] == 600_000
        assert levied["due_date"] == "2026-09-15"
        assert levied["levied_at"].startswith("2026-08-01T00:00:00")

    def test_the_association_and_the_charge_reflect_the_levy_with_no_further_write(self, api):
        """PRD §2.6: "the posture is `FULLY_FUNDED` when the balance is at least the
        target; otherwise it is `ADEQUATE` when the balance multiplied by one hundred is
        at least the target multiplied by sixty — so a balance of exactly sixty percent of
        target is `ADEQUATE`"

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response_that_caused_it
        """
        scenario = self._draft_roll()
        validate_success(api_client.certify_roll(scenario["roll"]["id"], CLERK))
        charge_id = validate_paginated(
            api_client.list_assessment_charges(
                CLERK, params={"roll_id": scenario["roll"]["id"]}
            )
        )[0][0]["id"]
        validate_success(api_client.levy_roll(scenario["roll"]["id"], TREASURER))

        association = validate_success(
            api_client.get_association(scenario["association"]["id"], TREASURER)
        )
        assert association["reserve_balance_cents"] == 600_000
        assert association["reserve_funding_ratio"] == pytest.approx(0.6, abs=0.0001)
        assert association["reserve_posture"] == "ADEQUATE"

        charge = validate_success(api_client.get_assessment_charge(charge_id, CLERK))
        assert charge["status"] == "OPEN"
        assert charge["due_date"] == "2026-09-15"
