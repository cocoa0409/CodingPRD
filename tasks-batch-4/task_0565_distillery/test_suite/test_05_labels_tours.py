"""COLA label revision loop and tasting-room tour confirmation (buffer + capacity)."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_distillery,
    create_gauged_run,
    fill_barrel,
    create_tour,
    create_label_application_payload,
)

_OC = TEST_USERS["compliance_headers"]
_PM = TEST_USERS["production_headers"]
_TRS = TEST_USERS["tasting_headers"]


def _draft_label(api, dist_id):
    return get_success_data(
        api.create_label_application(create_label_application_payload(dist_id), _OC)
    )


class TestLabelRevisionLoop:
    def test_return_sets_needs_correction(self, api):
        """PRD 3.4: "a `RETURN` outcome moves it from `SUBMITTED` to `NEEDS_CORRECTION`
        and records the supplied `correction_notes`."

        Design: Difficulty/non_linear_state_machine/label_needs_correction_resubmit_cycle
        """
        dist = create_distillery(api, dsp_permit_number="DSP-LB-1")
        label = _draft_label(api, dist["id"])
        api.submit_label(label["id"], _OC)
        returned = validate_success(
            api.decide_label(label["id"], {"outcome": "RETURN", "correction_notes": "fix ABV"}, _OC)
        )
        assert returned["status"] == "NEEDS_CORRECTION"

    def test_resubmit_then_approve_cycle(self, api):
        """PRD 3.4: "An application in `NEEDS_CORRECTION` may be resubmitted, moving it
        back from `NEEDS_CORRECTION` to `SUBMITTED` and clearing its `correction_notes`
        — this revision loop may repeat any number of times." PRD 3.4: "an `APPROVE`
        outcome advances it from `SUBMITTED` to `APPROVED`".

        Design: Difficulty/non_linear_state_machine/label_needs_correction_resubmit_cycle
        """
        dist = create_distillery(api, dsp_permit_number="DSP-LB-2")
        label = _draft_label(api, dist["id"])
        api.submit_label(label["id"], _OC)
        api.decide_label(label["id"], {"outcome": "RETURN", "correction_notes": "fix ABV"}, _OC)
        resubmitted = validate_success(api.resubmit_label(label["id"], _OC))
        assert resubmitted["status"] == "SUBMITTED"
        approved = validate_success(api.decide_label(label["id"], {"outcome": "APPROVE"}, _OC))
        assert approved["status"] == "APPROVED"

    def test_decide_before_submit_rejected(self, api):
        """PRD 3.4: "Each of these transitions is legal only from the state named as
        its origin; attempting one from any other state is rejected as an illegal state
        transition." Deciding requires a `SUBMITTED` application.

        Design: Corner/state_machines/label_decide_before_submit_returns_invalid_state
        """
        dist = create_distillery(api, dsp_permit_number="DSP-LB-3")
        label = _draft_label(api, dist["id"])
        resp = api.decide_label(label["id"], {"outcome": "APPROVE"}, _OC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestTourTemporalBeatsCapacity:
    def _setup(self, api, permit):
        dist = create_distillery(api, dsp_permit_number=permit)
        t1, _ = create_tour(api, dist["id"], customer_email="ga@x.com", customer_name="Guest A",
                            start_time="2026-06-01T10:00:00Z", end_time="2026-06-01T11:00:00Z",
                            party_size=15)
        api.confirm_tour(t1["id"], _TRS)
        t2, _ = create_tour(api, dist["id"], customer_email="gb@x.com", customer_name="Guest B",
                            start_time="2026-06-01T10:20:00Z", end_time="2026-06-01T11:00:00Z",
                            party_size=10)
        return t2

    def test_overlap_and_overcapacity_returns_overlap(self, api):
        """PRD 3.9: "First, no already-confirmed tour at the same distillery may start
        within 30 minutes of this tour's `start_time`, otherwise the confirmation is
        rejected with `ERR_TOUR_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/tour_confirm_temporal_beats_capacity
        """
        t2 = self._setup(api, "DSP-TR-1")
        resp = api.confirm_tour(t2["id"], _TRS)
        validate_error(resp, ApiErrorId.ERR_TOUR_OVERLAP.value)

    def test_overlap_precedes_capacity_check(self, api):
        """PRD 3.9: the buffer check applies "First", then capacity "Second" — so a
        tour both within the buffer and over capacity surfaces `ERR_TOUR_OVERLAP`, not
        `ERR_TOUR_CAPACITY`.

        Design: Difficulty/priority_pair_validation_conflict/tour_confirm_temporal_beats_capacity
        """
        t2 = self._setup(api, "DSP-TR-2")
        resp = api.confirm_tour(t2["id"], _TRS)
        assert resp.status_code == 409
        assert resp.json()["data"]["error_id"] == ApiErrorId.ERR_TOUR_OVERLAP.value
        assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_TOUR_CAPACITY.value


class TestTourCapacityBoundary:
    def test_capacity_exactly_20_confirms(self, api):
        """PRD 3.9: "the sum of `party_size` across all confirmed tours whose windows
        overlap this tour's `start_time`-to-`end_time` interval, plus this tour's own
        `party_size`, must not exceed the tasting-room capacity of 20 guests".

        Design: Difficulty/boundary_precision_check/tour_capacity_exact_20_allowed_21_rejected
        """
        dist = create_distillery(api, dsp_permit_number="DSP-TR-3")
        t20, _ = create_tour(api, dist["id"], customer_email="p20@x.com", customer_name="Guest",
                             start_time="2026-06-01T10:00:00Z", end_time="2026-06-01T11:00:00Z",
                             party_size=20)
        confirmed = validate_success(api.confirm_tour(t20["id"], _TRS))
        assert confirmed["status"] == "CONFIRMED"

    def test_capacity_21_rejected(self, api):
        """PRD 3.9: the sum "must not exceed the tasting-room capacity of 20 guests,
        otherwise the confirmation is rejected with `ERR_TOUR_CAPACITY`."

        Design: Difficulty/boundary_precision_check/tour_capacity_exact_20_allowed_21_rejected
        """
        dist = create_distillery(api, dsp_permit_number="DSP-TR-4")
        t21, _ = create_tour(api, dist["id"], customer_email="p21@x.com", customer_name="Guest",
                             start_time="2026-06-01T10:00:00Z", end_time="2026-06-01T11:00:00Z",
                             party_size=21)
        resp = api.confirm_tour(t21["id"], _TRS)
        validate_error(resp, ApiErrorId.ERR_TOUR_CAPACITY.value)


class TestTourBufferGeometry:
    def _setup(self, api, permit):
        dist = create_distillery(api, dsp_permit_number=permit)
        t1, _ = create_tour(api, dist["id"], customer_email="ba@x.com", customer_name="Guest A",
                            start_time="2026-06-01T10:00:00Z", end_time="2026-06-01T11:00:00Z",
                            party_size=2)
        api.confirm_tour(t1["id"], _TRS)
        t2, _ = create_tour(api, dist["id"], customer_email="bb@x.com", customer_name="Guest B",
                            start_time="2026-06-01T10:20:00Z", end_time="2026-06-01T11:20:00Z",
                            party_size=2)
        return t2

    def test_start_within_buffer_rejected(self, api):
        """PRD 3.9: "no already-confirmed tour at the same distillery may start within
        30 minutes of this tour's `start_time`, otherwise the confirmation is rejected
        with `ERR_TOUR_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/tour_buffer_startgap_overlap
        """
        t2 = self._setup(api, "DSP-TR-5")
        resp = api.confirm_tour(t2["id"], _TRS)
        validate_error(resp, ApiErrorId.ERR_TOUR_OVERLAP.value)

    def test_buffer_rejects_despite_free_seats(self, api):
        """PRD 3.9: the 30-minute start-buffer check is independent of capacity, so a
        tour within the buffer is rejected with `ERR_TOUR_OVERLAP` even when total
        seats (4) are well under the capacity of 20.

        Design: Difficulty/resource_temporal_overlap/tour_buffer_startgap_overlap
        """
        t2 = self._setup(api, "DSP-TR-6")
        resp = api.confirm_tour(t2["id"], _TRS)
        assert resp.status_code == 409
        assert resp.json()["data"]["error_id"] == ApiErrorId.ERR_TOUR_OVERLAP.value


class TestBarrelTerminalLockdown:
    def test_dump_already_destroyed_barrel_rejected(self, api):
        """PRD 3.3: "A `ProductionManager` may destroy an aging barrel, moving it from
        `AGING` to `DESTROYED`; destruction is legal only from `AGING`." A second dump
        is an illegal state transition.

        Design: Corner/state_machines/barrel_dump_twice_returns_invalid_state
        """
        dist = create_distillery(api, dsp_permit_number="DSP-TR-7")
        run, _ = create_gauged_run(api, dist["id"])
        barrel = fill_barrel(api, run["id"], fill_proof_gallons=10)
        get_success_data(api.dump_barrel(barrel["id"], _PM))
        resp = api.dump_barrel(barrel["id"], _PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
