"""Requests that break two rules at once, where only the earlier check in the
screening order may be reported."""

from test_helpers import (
    adjudicate_claim_payload,
    create_prefinish_run_payload,
    request_info_payload,
    resubmit_claim_payload,
    setup_line_only_submitted_claim,
    setup_prefinish_ready,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    SCHEDULER,
    create_prefinish_line,
    refetch_claim,
    refetch_product_line,
    setup_milled_lot,
)
from test_helpers.test_users import (
    CLAIM_ADJUDICATOR_USER_ID,
    make_warranty_adjudicator_headers,
)

# The window runs backwards: eight hours from end to start.
BACKWARD_WINDOW = {
    "window_start_utc": "2026-08-20T14:00:00.000Z",
    "window_end_utc": "2026-08-20T06:00:00.000Z",
}


class TestClaimStateBeatsReserveSufficiency:
    """Claim state is screened at step 21 and reserve sufficiency at step 51, so
    an out-of-state claim on an underfunded line reports the state."""

    def _underfunded_info_requested_claim(self, api):
        ctx = setup_line_only_submitted_claim(
            api, line_overrides={"warranty_funded_total_cents": 100000}
        )
        adjudicator = make_warranty_adjudicator_headers(CLAIM_ADJUDICATOR_USER_ID)
        validate_success(
            api.request_claim_info(
                ctx["claim"]["id"],
                request_info_payload(info_request_note="Send the subfloor moisture log"),
                adjudicator,
            ),
            expected_status=200,
        )
        return ctx, adjudicator

    def test_out_of_state_claim_reports_the_state_not_the_shortfall(self, api):
        """PRD 2.7: "When several checks could fail on one request, they are
        evaluated in a fixed order and the first failure is the one reported."

        PRD 2.7: "Warranty claim state, in either the adjudication or the
        remediation dimension — `ERR_CLAIM_STATE_INVALID` (409), on requesting
        information, resubmission, adjudication, reversal, starting remediation and
        completing remediation."

        PRD 2.7: "Reserve sufficiency — `ERR_WARRANTY_RESERVE_INSUFFICIENT` (422),
        on adjudication with an approval decision."

        Design: Difficulty/priority_pair_validation_conflict/claim_state_beats_warranty_reserve_insufficient
        """
        ctx, adjudicator = self._underfunded_info_requested_claim(api)

        response = api.adjudicate_claim(
            ctx["claim"]["id"], adjudicate_claim_payload(), adjudicator
        )
        validate_error(response, "ERR_CLAIM_STATE_INVALID", expected_status=409)

        line = refetch_product_line(api, ctx["product_line"]["id"])
        assert line["warranty_balance_cents"] == 100000
        assert line["warranty_committed_cents"] == 0
        assert line["posture"] == "RESTRICTED"

        claim = refetch_claim(api, ctx["claim"]["id"])
        assert claim["adjudication_status"] == "INFO_REQUESTED"
        assert claim["adjudicated_liability_cents"] is None

    def test_once_the_state_is_cleared_the_shortfall_is_the_one_reported(self, api):
        """PRD 3.9: "The line's reserve must cover that charge: when
        `adjudicated_liability_cents` exceeds the line's `warranty_balance_cents`,
        the approval is refused with `ERR_WARRANTY_RESERVE_INSUFFICIENT` and
        nothing moves."

        PRD 3.9: "The claimant's corrected figures then come back through a
        resubmission, which moves the claim from `INFO_REQUESTED` back to
        `SUBMITTED`, overwrites `affected_square_feet`,
        `subfloor_moisture_pct_at_install` and `ambient_rh_pct_at_install` with the
        supplied values, recomputes `estimated_liability_cents` from them by the
        same four steps, and clears `info_request_note`."

        Design: Difficulty/priority_pair_validation_conflict/claim_state_beats_warranty_reserve_insufficient
        """
        ctx, adjudicator = self._underfunded_info_requested_claim(api)
        validate_success(
            api.resubmit_claim(
                ctx["claim"]["id"],
                resubmit_claim_payload(affected_square_feet=240),
                adjudicator,
            ),
            expected_status=200,
        )

        response = api.adjudicate_claim(
            ctx["claim"]["id"], adjudicate_claim_payload(), adjudicator
        )
        validate_error(
            response, "ERR_WARRANTY_RESERVE_INSUFFICIENT", expected_status=422
        )

        line = refetch_product_line(api, ctx["product_line"]["id"])
        assert line["warranty_balance_cents"] == 100000
        assert line["warranty_committed_cents"] == 0


class TestLotGradingPrerequisiteBeatsWindowShape:
    """The grading prerequisite is screened at step 24 and the window shape at
    step 34, so an ungraded lot with a backwards window reports the lot."""

    def test_ungraded_lot_reports_the_lot_not_the_backwards_window(self, api):
        """PRD 2.7: "Lot grading prerequisite — only a `GRADED` lot may be
        prefinished; `ERR_LOT_NOT_GRADED` (409), on `POST /mill/prefinish-runs`."

        PRD 2.7: "Prefinish window shape — `ERR_PREFINISH_WINDOW_INVALID` (422),
        on `POST /mill/prefinish-runs`."

        PRD 3.8: "Only a lot in `GRADED` status may be scheduled; a `PLANNED`,
        `MILLED`, `QUARANTINED` or `VOIDED` lot is refused with
        `ERR_LOT_NOT_GRADED`."

        Design: Difficulty/priority_pair_validation_conflict/lot_not_graded_beats_prefinish_window_invalid
        """
        ctx = setup_milled_lot(api)
        prefinish_line = create_prefinish_line(api)
        assert ctx["lot"]["status"] == "MILLED"

        response = api.create_prefinish_run(
            create_prefinish_run_payload(
                prefinish_line["id"], ctx["lot"]["id"], **BACKWARD_WINDOW
            ),
            SCHEDULER,
        )
        validate_error(response, "ERR_LOT_NOT_GRADED", expected_status=409)

        rows, meta = validate_paginated(
            api.list_prefinish_runs(
                SCHEDULER, params={"flooring_lot_id": ctx["lot"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_once_the_lot_grades_out_the_window_shape_is_the_one_reported(self, api):
        """PRD 2.9: "A window must also be non-empty — its end strictly after its
        start — and no longer than 24 hours, or it is rejected with
        `ERR_PREFINISH_WINDOW_INVALID`."

        PRD 3.8: "The window must satisfy the shape rules of §2.9 or be refused
        with `ERR_PREFINISH_WINDOW_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/lot_not_graded_beats_prefinish_window_invalid
        """
        ctx = setup_prefinish_ready(api)
        assert ctx["lot"]["status"] == "GRADED"

        response = api.create_prefinish_run(
            create_prefinish_run_payload(
                ctx["prefinish_line"]["id"], ctx["lot"]["id"], **BACKWARD_WINDOW
            ),
            SCHEDULER,
        )
        validate_error(response, "ERR_PREFINISH_WINDOW_INVALID", expected_status=422)
