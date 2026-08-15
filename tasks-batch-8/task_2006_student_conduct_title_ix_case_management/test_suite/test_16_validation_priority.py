"""Validation-tier precedence: earlier tiers short-circuit later failures."""
from test_helpers import (
    ApiErrorId,
    appeal_payload,
    create_case,
    drive_case_to_issued,
    drive_to_hearing_preparation,
    get_case,
    hearing_payload,
    make_cast,
    make_coordinator_headers,
    make_party_headers,
    schedule_hearing,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client


class TestStateBeatsTemporalOnAppeal:
    def _closed_case(self, cast):
        """OTHER_SEX_BASED case: issued WARNING at 2026-09-01T10:00, then closed
        once the clock is strictly past the appeal deadline."""
        case = create_case(cast, categories=["OTHER_SEX_BASED"])
        stage = drive_case_to_issued(case["id"], cast)
        # appeal_deadline is 2026-09-06T10:00:00Z; strictly later closes it.
        set_clock("2026-09-07T10:00:00Z")
        resp = api_client.finalize_closure(
            case["id"], make_coordinator_headers(cast["coord"]["id"])
        )
        closed = validate_success(resp, 200)
        assert closed["status"] == "CLOSED"
        return case, stage

    def test_appeal_on_closed_case_state_beats_temporal(self, api):
        """PRD 2.11: "Every request is evaluated against the validation tiers in
        a fixed ascending priority order, and the first failing tier
        short-circuits the remainder. When several failures exist in one request,
        the error the client sees is the one from the earliest tier:"
        PRD 2.11: "**State** — the target entity must be in a from-state from which
        the requested transition exists in its machine, with terminal states
        rejecting all further transitions (`ERR_INVALID_STATE_TRANSITION`, 409);
        and, for child-mutation endpoints nested under a case, the case must not
        be in `CLOSED`, `REFERRED_TO_CONDUCT`, or `RESOLVED_INFORMAL`
        (`ERR_CASE_ALREADY_TERMINAL`, 409). Terminal cases are read-only except
        for the audit-trail listing, annual statistics, and the retention purge;
        filing an appeal on a `DISMISSED` case is expressly exempt from this
        guard (§3.6)."

        Design: Difficulty/priority_pair_validation_conflict/appeal_on_closed_case_state_beats_temporal
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case, _ = self._closed_case(cast)

        # Both violations hold: the case is CLOSED (state tier), and the filing
        # at 2026-09-07T10:00 is strictly after the 2026-09-06T10:00 deadline
        # (temporal tier). The state tier fires first.
        resp = api.file_appeal(
            case["id"],
            appeal_payload("RESPONDENT", "DETERMINATION", ["PROCEDURAL_IRREGULARITY"],
                           statement="Late and closed"),
            make_party_headers(cast["resp"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CASE_ALREADY_TERMINAL)

    def test_appeal_on_closed_case_persists_nothing(self, api):
        """PRD 2.11: "When several failures exist in one request, the error the
        client sees is the one from the earliest tier:"
        PRD 3.6: "a determination-target filing also moves the case
        `DETERMINATION_ISSUED → APPEAL_REVIEW`." (From CLOSED, no such
        transition exists.)

        Design: Difficulty/priority_pair_validation_conflict/appeal_on_closed_case_state_beats_temporal
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case, _ = self._closed_case(cast)

        resp = api.file_appeal(
            case["id"],
            appeal_payload("RESPONDENT", "DETERMINATION", ["PROCEDURAL_IRREGULARITY"],
                           statement="Late and closed"),
            make_party_headers(cast["resp"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CASE_ALREADY_TERMINAL)

        coord_h = make_coordinator_headers(cast["coord"]["id"])
        appeals, meta = validate_paginated(api.list_case_appeals(case["id"], coord_h))
        assert appeals == [] and meta["total_count"] == 0, (
            "a request rejected at the state tier must not persist an appeal"
        )
        assert get_case(case["id"], cast["coord"]["id"])["status"] == "CLOSED"


class TestSafetyBeatsTemporalOnScheduling:
    def _setup_segregation_plus_conflict(self, cast):
        """Case A: X served as investigator (COMPLETED at finalize).
        Case B: hearing SCHEDULED 2026-09-01T10:00 +60min with X as
        decision-maker. Returns (case_a, case_b, hearing_b)."""
        # Case A driven by X as its investigator.
        cast_a = dict(cast)
        cast_a["inv"] = cast["x"]
        case_a = create_case(cast, categories=["SEXUAL_HARASSMENT"])
        drive_to_hearing_preparation(case_a["id"], cast_a)

        # Case B with a different investigator; X is segregation-clean there.
        case_b = create_case(cast, categories=["STALKING"], received_via="EMAIL",
                             occurred_at="2026-07-16T22:00:00Z")
        drive_to_hearing_preparation(case_b["id"], cast)
        hearing_b = schedule_hearing(case_b["id"], cast["coord"]["id"], cast["x"]["id"])
        return case_a, case_b, hearing_b

    def test_hearing_schedule_segregation_beats_calendar_conflict(self, api):
        """PRD 2.11: "Every request is evaluated against the validation tiers in
        a fixed ascending priority order, and the first failing tier
        short-circuits the remainder."
        PRD 2.6: "First, investigator history never washes out: any investigator
        assignment on the case in `PROPOSED`, `ACTIVE`, or `COMPLETED` status
        counts as holding the investigator function, so having once served as
        investigator permanently bars that person from the decision-maker,
        appeal-officer, or facilitator functions on that case even after the
        assignment completes."
        PRD 2.6: "A violation of these rules is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (422)."

        Design: Difficulty/priority_pair_validation_conflict/hearing_schedule_segregation_beats_calendar_conflict
        """
        cast = make_cast("comp", "resp", "coord", "inv", "x")
        case_a, case_b, _ = self._setup_segregation_plus_conflict(cast)

        # Both violations hold: X is case A's COMPLETED investigator (safety
        # tier), and a 10:30 start leaves only a 30-minute gap to X's case B
        # hearing [10:00, 11:00) against the 60-minute buffer (temporal tier).
        resp = api.schedule_hearing(
            case_a["id"],
            hearing_payload(cast["x"]["id"], scheduled_at="2026-09-01T10:30:00Z"),
            make_coordinator_headers(cast["coord"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_segregation_rejection_creates_no_hearing(self, api):
        """PRD 2.11: "When several failures exist in one request, the error the
        client sees is the one from the earliest tier:"
        PRD 2.6: "A violation of these rules is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (422)."

        Design: Difficulty/priority_pair_validation_conflict/hearing_schedule_segregation_beats_calendar_conflict
        """
        cast = make_cast("comp", "resp", "coord", "inv", "x")
        case_a, case_b, _ = self._setup_segregation_plus_conflict(cast)
        coord_h = make_coordinator_headers(cast["coord"]["id"])

        resp = api.schedule_hearing(
            case_a["id"],
            hearing_payload(cast["x"]["id"], scheduled_at="2026-09-01T10:30:00Z"),
            coord_h,
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        hearings, meta = validate_paginated(api.list_case_hearings(case_a["id"], coord_h))
        assert hearings == [] and meta["total_count"] == 0, (
            "the rejected schedule must not persist a hearing row on case A"
        )
