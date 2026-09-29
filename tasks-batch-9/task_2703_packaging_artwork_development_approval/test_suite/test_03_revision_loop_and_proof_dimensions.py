"""Two state machines that are neither linear nor single-tracked."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    approved_version,
    book_press_check,
    coord,
    current_route,
    decide_color,
    decide_discipline,
    decide_substrate,
    in_review_version,
    new_printer,
    new_proof,
    read_proof,
    read_route,
    read_version,
    revise,
    revise_payload,
    submit,
    tasks_for_route,
    validate_error,
    verify,
)

FILM_BRIEF = {
    "structural_spec": {
        "component_type": "CARTON",
        "dimensions_mm": {"l": 120, "w": 60, "h": 200},
        "substrate_class": "FILM",
        "print_process": "FLEXO",
    }
}


def _bounce_once(version_id):
    """Reject the BRAND task of the version's open pass."""
    return decide_discipline(version_id, "BRAND", "REJECTED")


def _reopen_and_resubmit(version_id):
    revise(version_id)
    verify(version_id)
    return submit(version_id)


class TestRevisionCycleLoopsBackToDraft:
    """The DRAFT -> ELEMENTS_VERIFIED -> IN_REVIEW -> REVISION_REQUESTED loop."""

    def test_rejection_skips_the_siblings_and_reopening_returns_to_draft(self):
        """One rejection closes the pass and the loop re-enters DRAFT.

        PRD §3.3: "A version rejected in review lands in `REVISION_REQUESTED` and
        must be explicitly re-opened before it can be edited into shape and
        resubmitted; that re-opening carries an optional `revise_note` and moves the
        version `REVISION_REQUESTED → DRAFT`, closing the cycle `DRAFT →
        ELEMENTS_VERIFIED → IN_REVIEW → REVISION_REQUESTED → DRAFT`."

        Design: Difficulty/non_linear_state_machine/version_revision_cycle_loops_to_draft_until_cap_blocks_revise
        """
        _brief, _asset, version = in_review_version()
        route = current_route(version["id"])
        assert route["status"] == "IN_PROGRESS"
        assert route["route_no"] == 1

        _bounce_once(version["id"])

        assert read_route(route["id"])["status"] == "COMPLETE_REJECTED"
        bounced = read_version(version["id"])
        assert bounced["state"] == "REVISION_REQUESTED"
        assert bounced["revision_cycle_count"] == 1
        assert bounced["route_count"] == 1

        siblings = [
            task
            for task in tasks_for_route(route["id"])
            if task["discipline"] != "BRAND"
        ]
        assert len(siblings) == 3
        for task in siblings:
            assert task["decision"] == "SKIPPED"
            assert task["decided_by_user_id"] is None
            assert task["is_active"] is False

        reopened = revise(version["id"])
        assert reopened["state"] == "DRAFT"
        assert reopened["revision_cycle_count"] == 1

    def test_third_bounce_permanently_closes_reopening(self):
        """The cap closes the loop once the version has been bounced three times.

        PRD §3.3: "Re-opening is refused with `ERR_VERSION_STATE_INVALID` from any
        other state, and refused with `ERR_REVISION_CYCLE_CAP_EXCEEDED` once the
        version has already been bounced back from review three times."

        Design: Difficulty/non_linear_state_machine/version_revision_cycle_loops_to_draft_until_cap_blocks_revise
        """
        _brief, _asset, version = in_review_version()

        _bounce_once(version["id"])
        assert read_version(version["id"])["revision_cycle_count"] == 1

        _reopen_and_resubmit(version["id"])
        _bounce_once(version["id"])
        second = read_version(version["id"])
        assert second["revision_cycle_count"] == 2
        assert second["route_count"] == 2

        _reopen_and_resubmit(version["id"])
        _bounce_once(version["id"])
        third = read_version(version["id"])
        assert third["revision_cycle_count"] == 3
        assert third["route_count"] == 3
        assert third["state"] == "REVISION_REQUESTED"

        response = api_client.revise_artwork_version(
            version["id"], revise_payload(), coord()
        )
        validate_error(
            response, ApiErrorId.ERR_REVISION_CYCLE_CAP_EXCEEDED.value, 422
        )

        after = read_version(version["id"])
        assert after["state"] == "REVISION_REQUESTED"
        assert after["revision_cycle_count"] == 3
        assert after["route_count"] == 3


class TestProofDimensionsResolveIndependently:
    """Colour, substrate and the press-check track advance on their own."""

    def test_press_check_attendance_leaves_the_other_two_dimensions_pending(self):
        """The press-check booking is a third, independent track.

        PRD §3.6: "Three verdicts then resolve the proof, and they are genuinely
        independent: colour and substrate may be decided in either order, and the
        press-check track advances on its own schedule."

        Design: Difficulty/non_linear_state_machine/proof_three_dimensions_resolve_independently_into_derived_state
        """
        _brief, _asset, version = approved_version(
            brief_overrides=FILM_BRIEF, asset_overrides={"substrate_class": "FILM"}
        )
        printer = new_printer()
        proof = new_proof(version["id"], printer, substrate_code="FILM")

        assert proof["press_check_required"] is True
        assert proof["press_check_status"] == "PRESS_CHECK_REQUIRED"
        assert proof["effective_tolerance"] == pytest.approx(3.5, abs=0.01)

        booked = book_press_check(
            proof["id"],
            press_line_code="LINE-A",
            press_check_start_utc="2026-08-10T08:00:00Z",
            press_check_end_utc="2026-08-10T12:00:00Z",
            attended_by_user_id="u_qa",
        )

        assert booked["press_check_status"] == "PRESS_CHECK_ATTENDED"
        assert booked["color_status"] == "COLOR_PENDING"
        assert booked["substrate_status"] == "SUBSTRATE_PENDING"
        assert booked["proof_state"] == "PROOF_IN_REVIEW"

    def test_derived_state_flips_only_once_all_three_dimensions_resolve(self):
        """The compound verdict is re-derived from all three current values.

        PRD §3.6: "Otherwise, if `color_status` is `COLOR_PASS` **and**
        `substrate_status` is `SUBSTRATE_APPROVED` **and** `press_check_status` is
        either `NOT_REQUIRED` or `PRESS_CHECK_ATTENDED`, the proof is
        `PROOF_APPROVED` and becomes usable as plate-making authorisation."

        Design: Difficulty/non_linear_state_machine/proof_three_dimensions_resolve_independently_into_derived_state
        """
        _brief, _asset, version = approved_version(
            brief_overrides=FILM_BRIEF, asset_overrides={"substrate_class": "FILM"}
        )
        printer = new_printer()
        proof = new_proof(version["id"], printer, substrate_code="FILM")

        book_press_check(
            proof["id"],
            press_line_code="LINE-A",
            press_check_start_utc="2026-08-10T08:00:00Z",
            press_check_end_utc="2026-08-10T12:00:00Z",
            attended_by_user_id="u_qa",
        )

        after_substrate = decide_substrate(proof["id"], "SUBSTRATE_APPROVED")
        assert after_substrate["substrate_status"] == "SUBSTRATE_APPROVED"
        assert after_substrate["color_status"] == "COLOR_PENDING"
        assert after_substrate["proof_state"] == "PROOF_IN_REVIEW"

        after_color = decide_color(proof["id"], 3.0)
        assert after_color["color_status"] == "COLOR_PASS"
        assert after_color["measured_delta_e_max"] == pytest.approx(3.0, abs=0.01)
        assert after_color["proof_state"] == "PROOF_APPROVED"

        assert read_proof(proof["id"])["proof_state"] == "PROOF_APPROVED"
        assert read_version(version["id"])["state"] == "APPROVED"
