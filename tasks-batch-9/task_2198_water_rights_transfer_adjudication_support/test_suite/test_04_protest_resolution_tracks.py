"""The negotiation / hearing fork and the clearance cascade.

PRD §3.6: "The two stipulation branches carry deliberately divergent side-effect
sets."
"""
import pytest
from test_helpers import assert_same_instant
from test_helpers import api_client, get_success_data
from test_helpers.fixtures import (
    ANALYST,
    add_injury_analysis,
    add_point_of_diversion,
    conditions_of,
    create_claimant,
    file_protest,
    publish_application,
    read_application,
    read_claimant,
    read_right,
    resolve_protest,
    route_protest,
    set_clock,
    setup_certified_right,
    setup_published_application,
    submit_application,
)


class TestStipulationBranchesDiverge:
    """PRD §3.6 — "The two tracks reach the same resolved state by entirely
    different means, which is the point of the fork."

    Two headgate-change applications of 50.00 AF each sit on one certified right
    and are analysed identically under `INSTANTANEOUS_DEPLETION` over a 10.00-mile
    move: a distance factor of 0.8500 gives a gross depletion of 39.10 on both.
    Each draws one protest claiming 12.00 AF; one protest is routed to
    `NEGOTIATION` and the other to `HEARING`.
    """

    def _forked(self):
        bundle = setup_certified_right()
        right_id = bundle["right"]["id"]
        study_id = bundle["study"]["id"]
        # PRD §3.4 — a headgate-change application names a proposed headgate and
        # must not carry a proposed purpose of use.
        pod = add_point_of_diversion(right_id)
        applications, analyses = [], []
        for _ in range(2):
            application = get_success_data(
                api_client.create_transfer_application(
                    {
                        "water_right_id": right_id,
                        "hcu_study_id": study_id,
                        "application_type": "POINT_OF_DIVERSION_CHANGE",
                        "requested_af": 50.00,
                        "proposed_point_of_diversion_id": pod["id"],
                    },
                    ANALYST,
                )
            )
            submit_application(application["id"], right_id)
            analyses.append(
                add_injury_analysis(
                    application["id"], "INSTANTANEOUS_DEPLETION", 10.00
                )
            )
            applications.append(publish_application(application["id"]))
        protestant = create_claimant(legal_name="Cottonwood Canal Users")
        set_clock("2026-03-05T00:00:00Z")
        protests = [
            file_protest(application["id"], protestant["id"], 12.00)
            for application in applications
        ]
        bundle.update(
            {
                "pod": pod,
                "applications": applications,
                "analyses": analyses,
                "protests": protests,
                "protestant": protestant,
            }
        )
        return bundle

    def test_negotiation_stipulation_grants_a_volumetric_offset_only(self):
        """PRD §3.6: "On the negotiation branch the protest moves
        `IN_NEGOTIATION → RESOLVED_STIPULATED`, the `stipulated_offset_af` is
        recorded, and the application's `DRAFT` injury analysis recomputes
        `offset_af` as the sum of stipulated offsets across all negotiation-track
        resolved protests and recomputes `net_injury_af` accordingly — a
        volumetric concession, and no condition is created."

        A 10.00 AF concession against the 39.10 gross depletion leaves 29.10 of
        net injury, and the analysis is frozen there by the clearance cascade.

        Design: Difficulty/non_linear_state_machine/protest_track_fork_divergence
        """
        bundle = self._forked()
        route_protest(bundle["protests"][0]["id"], "NEGOTIATION")

        protest = resolve_protest(
            bundle["protests"][0]["id"], "STIPULATE", stipulated_offset_af=10.00
        )

        assert protest["status"] == "RESOLVED_STIPULATED"
        assert protest["track"] == "NEGOTIATION"
        assert protest["stipulated_offset_af"] == pytest.approx(10.00, abs=0.01)
        analysis = get_success_data(
            api_client.get_injury_analysis(bundle["analyses"][0]["id"], ANALYST)
        )
        assert analysis["gross_depletion_af"] == pytest.approx(39.10, abs=0.01)
        assert analysis["offset_af"] == pytest.approx(10.00, abs=0.01)
        assert analysis["net_injury_af"] == pytest.approx(29.10, abs=0.01)
        assert analysis["status"] == "FINALIZED"
        application = read_application(bundle["applications"][0]["id"])
        assert application["status"] == "READY_FOR_DECISION"
        assert application["unresolved_protest_count"] == 0
        assert conditions_of(application["id"]) == [], (
            "the negotiation branch creates no approval condition at all"
        )

    def test_hearing_stipulation_imposes_a_condition_and_no_offset(self):
        """PRD §3.6: "On the hearing branch the protest moves
        `IN_HEARING → RESOLVED_STIPULATED`, `stipulated_offset_af` stays at 0.00
        because the hearing branch grants no volumetric offset at all and
        therefore leaves `net_injury_af` untouched, and instead one approval
        condition is created on the application with `source` set to
        `HEARING_RESOLUTION`, `status` `IMPOSED` and `required_af` equal to the
        protest's `claimed_injury_af`."

        The 39.10 gross depletion therefore survives intact as net injury, while a
        single `MEASUREMENT_DEVICE` condition for 12.00 AF appears. Because that
        type is not `MITIGATION_PAYMENT`, PRD §3.8 leaves it unpriced.

        Design: Difficulty/non_linear_state_machine/protest_track_fork_divergence
        """
        bundle = self._forked()
        route_protest(bundle["protests"][1]["id"], "HEARING")

        protest = resolve_protest(
            bundle["protests"][1]["id"],
            "STIPULATE",
            condition_type="MEASUREMENT_DEVICE",
            compliance_due_date="2026-08-01T00:00:00Z",
        )

        assert protest["status"] == "RESOLVED_STIPULATED"
        assert protest["track"] == "HEARING"
        assert protest["stipulated_offset_af"] == pytest.approx(0.00, abs=0.01)
        analysis = get_success_data(
            api_client.get_injury_analysis(bundle["analyses"][1]["id"], ANALYST)
        )
        assert analysis["offset_af"] == pytest.approx(0.00, abs=0.01)
        assert analysis["net_injury_af"] == pytest.approx(39.10, abs=0.01)
        assert analysis["status"] == "FINALIZED"
        conditions = conditions_of(bundle["applications"][1]["id"])
        assert len(conditions) == 1
        condition = conditions[0]
        assert condition["condition_type"] == "MEASUREMENT_DEVICE"
        assert condition["required_af"] == pytest.approx(12.00, abs=0.01)
        assert condition["compliance_due_date"] == "2026-08-01T00:00:00Z"
        assert condition["source"] == "HEARING_RESOLUTION"
        assert condition["status"] == "IMPOSED"
        assert condition["payment_status"] == "NOT_APPLICABLE"
        assert condition["base_fee_usd"] == pytest.approx(0.00, abs=0.01)
        assert condition["surcharge_pct"] == pytest.approx(0.000, abs=0.0001)
        assert condition["admin_surcharge_usd"] == pytest.approx(0.00, abs=0.01)
        assert condition["total_fee_usd"] == pytest.approx(0.00, abs=0.01)

    def test_identical_claims_produce_different_net_injuries_by_track(self):
        """PRD §3.6: "the hearing branch grants no volumetric offset at all and
        therefore leaves `net_injury_af` untouched".

        Both protests claim exactly 12.00 AF against identical 39.10 AF analyses.
        Resolving one on each track drives the two applications to different net
        injuries — 29.10 versus 39.10 — and to different condition sets, and the
        applicant's fee balance stays at 0.00 because the imposed condition is not
        a mitigation payment.

        Design: Difficulty/non_linear_state_machine/protest_track_fork_divergence
        """
        bundle = self._forked()
        route_protest(bundle["protests"][0]["id"], "NEGOTIATION")
        route_protest(bundle["protests"][1]["id"], "HEARING")

        resolve_protest(
            bundle["protests"][0]["id"], "STIPULATE", stipulated_offset_af=10.00
        )
        resolve_protest(
            bundle["protests"][1]["id"],
            "STIPULATE",
            condition_type="MEASUREMENT_DEVICE",
            compliance_due_date="2026-08-01T00:00:00Z",
        )

        negotiated = get_success_data(
            api_client.get_injury_analysis(bundle["analyses"][0]["id"], ANALYST)
        )
        heard = get_success_data(
            api_client.get_injury_analysis(bundle["analyses"][1]["id"], ANALYST)
        )
        assert negotiated["net_injury_af"] == pytest.approx(29.10, abs=0.01)
        assert heard["net_injury_af"] == pytest.approx(39.10, abs=0.01)
        assert conditions_of(bundle["applications"][0]["id"]) == []
        assert len(conditions_of(bundle["applications"][1]["id"])) == 1
        claimant = read_claimant(bundle["claimant"]["id"])
        assert claimant["outstanding_fee_balance_usd"] == pytest.approx(0.00, abs=0.01)
        assert claimant["standing_status"] == "IN_GOOD_STANDING"


class TestClearanceCascadeFinalizesTheAnalysis:
    """PRD §3.6 — "Whichever route clears the last protest — a stipulation on
    either track, a dismissal, or a withdrawal — the same clearance cascade fires
    when `unresolved_protest_count` reaches exactly 0."

    A 60.00 AF application analysed under `SEASONAL_AVERAGE` grosses
    60.00 * 0.78 = 46.80. Two protestants negotiate concessions of 5.00 and
    7.50 AF on 2026-03-05, well inside the 2026-03-31 window.
    """

    def _two_negotiations(self):
        bundle = setup_published_application(requested_af=60.00)
        senior = create_claimant(legal_name="Bear Creek Ranch")
        public = create_claimant(legal_name="Alder Basin Water Trust")
        set_clock("2026-03-05T00:00:00Z")
        first = file_protest(
            bundle["application"]["id"],
            senior["id"],
            8.00,
            basis="INJURY_TO_SENIOR_RIGHT",
        )
        second = file_protest(
            bundle["application"]["id"], public["id"], 9.00, basis="PUBLIC_INTEREST"
        )
        route_protest(first["id"], "NEGOTIATION")
        route_protest(second["id"], "NEGOTIATION")
        bundle.update({"first": first, "second": second})
        return bundle

    def test_first_stipulation_leaves_the_application_under_protest(self):
        """PRD §3.6: "All three outcomes decrement `unresolved_protest_count`."

        With two protests outstanding, clearing one takes the counter from 2 to 1,
        which is not "exactly 0", so the cascade does not fire: the application
        stays `UNDER_PROTEST` and the analysis stays `DRAFT` while already carrying
        the 5.00 AF concession, leaving 46.80 - 5.00 = 41.80 of net injury.

        Design: Difficulty/transitive_cascade/protest_clearance_finalization_cascade
        """
        bundle = self._two_negotiations()

        resolve_protest(bundle["first"]["id"], "STIPULATE", stipulated_offset_af=5.00)

        application = read_application(bundle["application"]["id"])
        assert application["status"] == "UNDER_PROTEST"
        assert application["unresolved_protest_count"] == 1
        analysis = get_success_data(
            api_client.get_injury_analysis(bundle["analysis"]["id"], ANALYST)
        )
        assert analysis["status"] == "DRAFT"
        assert analysis["gross_depletion_af"] == pytest.approx(46.80, abs=0.01)
        assert analysis["offset_af"] == pytest.approx(5.00, abs=0.01)
        assert analysis["net_injury_af"] == pytest.approx(41.80, abs=0.01)
        assert read_right(bundle["right"]["id"])["pending_review_count"] == 1

    def test_clearing_the_last_protest_finalizes_before_the_deadline(self):
        """PRD §3.6: "The application auto-transitions
        `UNDER_PROTEST → READY_FOR_DECISION`; its `DRAFT` injury analysis moves to
        the terminal `FINALIZED`, freezing `gross_depletion_af`, `offset_af` and
        `net_injury_af`; `pending_review_count` on the right is decremented".

        PRD §3.6: "This cascade fires regardless of whether `protest_deadline` has
        passed — clearing every protest is by itself sufficient to close the
        negotiation phase." The clock is still 2026-03-05 against a 2026-03-31
        deadline. The two concessions sum to 12.50, leaving 34.30 of net injury,
        and the escrow is untouched by the cascade.

        Design: Difficulty/transitive_cascade/protest_clearance_finalization_cascade
        """
        bundle = self._two_negotiations()
        resolve_protest(bundle["first"]["id"], "STIPULATE", stipulated_offset_af=5.00)

        resolve_protest(bundle["second"]["id"], "STIPULATE", stipulated_offset_af=7.50)

        application = read_application(bundle["application"]["id"])
        assert application["status"] == "READY_FOR_DECISION"
        assert application["unresolved_protest_count"] == 0
        assert_same_instant(application["protest_deadline"], "2026-03-31T00:00:00Z", "protest_deadline")
        analysis = get_success_data(
            api_client.get_injury_analysis(bundle["analysis"]["id"], ANALYST)
        )
        assert analysis["status"] == "FINALIZED"
        assert analysis["offset_af"] == pytest.approx(12.50, abs=0.01)
        assert analysis["net_injury_af"] == pytest.approx(34.30, abs=0.01)
        right = read_right(bundle["right"]["id"])
        assert right["pending_review_count"] == 0
        assert right["encumbered_af"] == pytest.approx(60.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(135.00, abs=0.01)
        assert right["status"] == "ENCUMBERED"
