"""One retirement, four hops, and a fifth consequence in the programme."""

from test_helpers import assertions as ax
from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_success

RETIREMENT = {"retirement_reason": "EXPOSED"}


def _scheduled_seat_on_a_published_single_item_form(api):
    return fx.pipeline_through_scheduled_seat(api)


class TestRetirementCascade:
    """A single-position published form, one held seat, one retirement."""

    def test_retirement_stamps_the_item_and_decrements_the_programme(self, api):
        """The item goes terminal with its reason and clock stamp, and the
        programme's coverage is recomputed at once.

        PRD §3.4: "The item moves to `RETIRED`, which is terminal, with `retired_at`
        stamped from the logical clock and `retirement_reason` taken from the
        request."

        PRD §3.4: "including the full cascade below and the decrement of the
        program's `operational_item_count` followed by recomputation of
        `deficient_domain_codes` and `blueprint_posture`".

        Design: Difficulty/transitive_cascade/item_retirement_cascades_four_hops_item_to_form_to_registration_to_session_seats
        """
        state = _scheduled_seat_on_a_published_single_item_form(api)

        retired = validate_success(api.retire_item(
            state.item_id, f.retire_item_payload(**RETIREMENT), fx.PSYCHOMETRICIAN), 200)

        assert retired["status"] == "RETIRED"
        assert retired["retirement_reason"] == "EXPOSED"
        assert str(retired["retired_at"]).startswith(k.DEFAULT_CLOCK[:10])
        ax.assert_item(retired)

        program = fx.read_program(api, state.program_id)
        assert program["operational_item_count"] == 0
        assert program["deficient_domain_codes"] == ["D1"]
        assert program["blueprint_posture"] == "DEFICIENT"
        assert program["status"] == "ACTIVE"

    def test_published_form_over_tolerance_moves_to_needs_rebuild(self, api):
        """One retirement on a one-position form gives 100 against 10, which is
        strictly greater, so the published form is rebuilt.

        PRD §3.4: "**Hop one:** every exam form whose item list contains the retired
        item recomputes its `retired_item_count`".

        PRD §3.4: "the form moves `PUBLISHED → NEEDS_REBUILD` when
        `retired_item_count` multiplied by 100 is strictly greater than
        `form_retirement_tolerance_pct` multiplied by the number of entries in
        `item_ids`".

        Design: Difficulty/transitive_cascade/item_retirement_cascades_four_hops_item_to_form_to_registration_to_session_seats
        """
        state = _scheduled_seat_on_a_published_single_item_form(api)
        before = fx.read_form(api, state.form_id)
        assert before["status"] == "PUBLISHED"
        assert before["retired_item_count"] == 0

        validate_success(api.retire_item(
            state.item_id, f.retire_item_payload(**RETIREMENT), fx.PSYCHOMETRICIAN), 200)

        form = fx.read_form(api, state.form_id)
        assert form["retired_item_count"] == 1
        assert form["status"] == "NEEDS_REBUILD"

    def test_rebuild_unschedules_the_seat_and_flags_the_registration(self, api):
        """The registration loses its seat and session and is marked as needing a
        different form, while its score dimension is untouched.

        PRD §3.4: "**Hop three:** because the form moved to `NEEDS_REBUILD`, every
        exam registration on that form whose `seat_status` is `SCHEDULED` moves to
        `UNSCHEDULED`, has `form_reassignment_required` set to true, and has its
        `session_id` cleared."

        Design: Difficulty/transitive_cascade/item_retirement_cascades_four_hops_item_to_form_to_registration_to_session_seats
        """
        state = _scheduled_seat_on_a_published_single_item_form(api)

        validate_success(api.retire_item(
            state.item_id, f.retire_item_payload(**RETIREMENT), fx.PSYCHOMETRICIAN), 200)

        registration = fx.read_registration(api, state.registration_id)
        assert registration["seat_status"] == "UNSCHEDULED"
        assert registration["form_reassignment_required"] is True
        assert registration["session_id"] is None
        assert registration["score_status"] == "NOT_APPLICABLE"

    def test_released_seat_is_recounted_in_the_session(self, api):
        """The session recounts its occupancy, so the ledger returns to zero and
        the session stays open.

        PRD §3.4: "**Hop four:** because those seats were released, every affected
        exam session recounts its `seats_reserved` and recomputes its `status`,
        which may flip a session `FULL → OPEN`."

        Design: Difficulty/transitive_cascade/item_retirement_cascades_four_hops_item_to_form_to_registration_to_session_seats
        """
        state = _scheduled_seat_on_a_published_single_item_form(api)
        assert fx.read_session(api, state.session_id)["seats_reserved"] == 1

        validate_success(api.retire_item(
            state.item_id, f.retire_item_payload(**RETIREMENT), fx.PSYCHOMETRICIAN), 200)

        session = fx.read_session(api, state.session_id)
        assert session["seats_reserved"] == 0
        assert session["status"] == "OPEN"
        ax.assert_seat_ledger_within_bounds(session)
