"""The GVWR certification loop of PRD 3.1.

Covers the two-figure audit view, the cyclic model lifecycle with its
revision round, and the three-hop freeze a revision drives into the trailers,
the jig reservations and the jig's booked-minutes rollup.
"""

import test_helpers as H
from test_helpers import (
    CERT_OFFICER,
    CERT_OFFICER_1_ID,
    WELD_SUPERVISOR,
    validate_error,
    validate_success,
)


class TestProvisionalVersusCertifiedRating:
    def test_provisional_estimate_omits_the_tire_limit_and_the_derate(self, api):
        """A submission writes the engineering estimate from three capacities only.

        PRD 3.1: "At submission time the tire circuit has not yet been sourced,
        so **the tire capacity does not participate** and no brake derate is
        applied: `provisional_gvwr_lbs` is the smallest of the axle, frame and
        coupler capacities, taken as a whole number of pounds with no rounding
        step."

        Design: Difficulty/dual_variant_calc/gvwr_provisional_estimate_versus_certified_final
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_model(api)
        assert model["provisional_gvwr_lbs"] is None
        assert model["certified_gvwr_lbs"] is None

        submitted = H.submit_model(api, model["id"])

        assert submitted["certification_status"] == H.CertificationStatus.IN_ENGINEERING_REVIEW
        # axle 2 x 3500 = 7000, frame 7200, coupler 7500; the 7280 lb tire
        # capacity is deliberately left out of the estimate.
        assert submitted["provisional_gvwr_lbs"] == H.TA_PROVISIONAL_GVWR_LBS
        assert submitted["certified_gvwr_lbs"] is None

    def test_certified_rating_takes_all_four_capacities_then_derates_then_floors(self, api):
        """The signed rating is 700 lb below the estimate the same inputs produced.

        PRD 3.1: "Step one takes the smallest of **all four** capacities — axle,
        tire, frame and coupler. Step two applies the unbraked-axle derate: if
        `design_braked_axle_count` is strictly less than `axle_count`, that
        smallest value is multiplied by ninety hundredths, a ten-percent
        reduction; if every axle is braked, the value passes through unchanged.
        Step three floors the result down to the nearest whole multiple of 10
        pounds."

        Design: Difficulty/dual_variant_calc/gvwr_provisional_estimate_versus_certified_final
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_model(api)
        H.submit_model(api, model["id"])

        response = api.decide_model(
            model["id"], H.decision_payload("CERTIFIED"), headers=CERT_OFFICER
        )

        decided = validate_success(response)
        # min(7000, 7280, 7200, 7500) = 7000; x 0.90 = 6300; floor to 10 lb = 6300.
        assert decided["certified_gvwr_lbs"] == H.TA_CERTIFIED_GVWR_LBS
        assert decided["provisional_gvwr_lbs"] == H.TA_PROVISIONAL_GVWR_LBS
        assert decided["provisional_gvwr_lbs"] - decided["certified_gvwr_lbs"] == 700
        assert decided["certification_status"] == H.CertificationStatus.CERTIFIED
        assert decided["certified_by_user_id"] == CERT_OFFICER_1_ID


class TestCertificationCycle:
    def test_certified_model_travels_back_through_review_to_a_second_signature(self, api):
        """A revision round returns the model to DRAFT and it can be signed again.

        PRD 3.1: "that back-edge is what makes the model lifecycle cyclic, so a
        model can legitimately travel `CERTIFIED` → `IN_ENGINEERING_REVIEW` →
        `DRAFT` → `IN_ENGINEERING_REVIEW` → `CERTIFIED` any number of times."

        Design: Difficulty/non_linear_state_machine/model_certification_cycle_with_revision_round
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)

        H.submit_model(api, model["id"], engineering_note="engineering change: heavier coupler")
        revised = H.decide_model(
            api, model["id"], "REVISION_REQUESTED", decision_note="tire circuit not sourced"
        )
        assert revised["certification_status"] == H.CertificationStatus.DRAFT
        assert revised["revision_round"] == 1

        H.submit_model(api, model["id"], engineering_note="revised package")
        recertified = H.decide_model(
            api, model["id"], "CERTIFIED", decision_note="revision accepted"
        )

        assert recertified["certification_status"] == H.CertificationStatus.CERTIFIED
        assert recertified["revision_round"] == 1
        assert recertified["certified_gvwr_lbs"] == H.TA_CERTIFIED_GVWR_LBS
        assert recertified["provisional_gvwr_lbs"] == H.TA_PROVISIONAL_GVWR_LBS

    def test_duplicate_decision_on_a_certified_model_is_refused_without_a_version_bump(self, api):
        """A second CERTIFIED decision is refused and writes nothing.

        PRD 3.1: "A decision is only accepted while `certification_status` is
        `IN_ENGINEERING_REVIEW`; otherwise the request is refused with
        `ERR_MODEL_STATE_INVALID`."

        Design: Difficulty/non_linear_state_machine/model_certification_cycle_with_revision_round
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)
        H.submit_model(api, model["id"], engineering_note="engineering change: heavier coupler")
        H.decide_model(
            api, model["id"], "REVISION_REQUESTED", decision_note="tire circuit not sourced"
        )
        H.submit_model(api, model["id"], engineering_note="revised package")
        H.decide_model(api, model["id"], "CERTIFIED", decision_note="revision accepted")

        response = api.decide_model(
            model["id"],
            H.decision_payload("CERTIFIED", decision_note="duplicate decision"),
            headers=CERT_OFFICER,
        )

        validate_error(response, H.ERR_MODEL_STATE_INVALID)
        after = H.read_model(api, model["id"])
        assert after["revision_round"] == 1
        # version 1 on creation, then one increment per accepted mutation:
        # three submissions and three decisions land, so the row sits at 7 and
        # the refused seventh call leaves it there.
        assert after["version"] == 7


class TestRevisionCascade:
    def test_revision_holds_the_trailers_releases_the_windows_and_refunds_the_minutes(self, api):
        """One REVISION_REQUESTED decision reaches three levels down.

        PRD 3.1: "First, every trailer built to this model whose `build_status`
        is `PLANNED`, `JIG_RESERVED` or `FRAME_REWORK` moves to `BUILD_HOLD`.
        Second, because those trailers entered the hold state, every jig
        reservation belonging to one of them whose `status` is `RESERVED` moves
        `RESERVED` → `RELEASED`. Third, because those reservations were
        released, each affected jig has its `reserved_minutes_total` reduced by
        the released reservation's `duration_minutes` and its own `version`
        incremented."

        Design: Difficulty/transitive_cascade/model_revision_cascades_to_units_reservations_and_jig_minutes
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)
        jig = H.commission_jig(api)
        unit1 = H.open_unit(api, model["id"], "SN-000101")
        unit2 = H.open_unit(api, model["id"], "SN-000102")
        H.reserve_jig_window(api, jig["id"], unit1["id"], window=H.JIG_WINDOW_1)
        H.reserve_jig_window(
            api, jig["id"], unit2["id"], window=("2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z")
        )
        assert H.read_jig(api, jig["id"])["reserved_minutes_total"] == 240

        H.submit_model(api, model["id"], engineering_note="engineering change after field reports")
        decided = H.decide_model(
            api, model["id"], "REVISION_REQUESTED", decision_note="frame rail gauge under review"
        )

        assert decided["certification_status"] == H.CertificationStatus.DRAFT
        assert decided["revision_round"] == 1
        # Units already pinned keep their snapshot, so the signed rating stays.
        assert decided["certified_gvwr_lbs"] == H.TA_CERTIFIED_GVWR_LBS
        assert H.read_unit(api, unit1["id"])["build_status"] == H.BuildStatus.BUILD_HOLD
        assert H.read_unit(api, unit2["id"])["build_status"] == H.BuildStatus.BUILD_HOLD
        reservations, _meta = H.validate_paginated(
            api.list_jig_reservations(jig["id"], headers=WELD_SUPERVISOR)
        )
        assert len(reservations) == 2
        assert [row["status"] for row in reservations] == [
            H.ReservationStatus.RELEASED,
            H.ReservationStatus.RELEASED,
        ]
        assert H.read_jig(api, jig["id"])["reserved_minutes_total"] == 0

    def test_held_trailers_still_count_as_active_units_on_the_model(self, api):
        """The hold does not change the model's active build count.

        PRD 3.1: "The model's `active_unit_count` is then recomputed — held
        trailers still count as active, so the number does not change on account
        of the hold itself — and the model's `version` increments."

        Design: Difficulty/transitive_cascade/model_revision_cascades_to_units_reservations_and_jig_minutes
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)
        jig = H.commission_jig(api)
        unit1 = H.open_unit(api, model["id"], "SN-000101")
        unit2 = H.open_unit(api, model["id"], "SN-000102")
        H.reserve_jig_window(api, jig["id"], unit1["id"], window=H.JIG_WINDOW_1)
        H.reserve_jig_window(
            api, jig["id"], unit2["id"], window=("2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z")
        )

        H.submit_model(api, model["id"], engineering_note="engineering change after field reports")
        decided = H.decide_model(
            api, model["id"], "REVISION_REQUESTED", decision_note="frame rail gauge under review"
        )

        assert decided["active_unit_count"] == 2
