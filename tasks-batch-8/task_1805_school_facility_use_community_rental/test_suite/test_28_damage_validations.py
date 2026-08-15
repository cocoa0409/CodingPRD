"""Damage-money ceremony validations: segregation of duties, the adjudication
cap, the fourteen-day appeal window, and claim shape (PRD §2.1, §2.4, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    make_renter_headers, make_director_headers, make_coordinator_headers,
    setup_completed_permit, make_damage_assessment, set_clock,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

DIRECTOR = TEST_USERS["director_headers"]

EVENT_START = "2026-09-13T00:00:00Z"
EVENT_END = "2026-09-13T03:00:00Z"
AFTER_EVENT = "2026-09-13T12:00:00Z"


def _completed_permit(api, dep_key):
    return setup_completed_permit(
        deposit_cents=10000, clock_after_end=AFTER_EVENT,
        idempotency_key=dep_key,
        event_title="Auction", headcount_estimate=100,
        starts_at=EVENT_START, ends_at=EVENT_END)


class TestSegregationOfDuties:
    def test_segregation_of_duties_on_adjudication(self, api):
        """PRD §2.1: "One further identity rule stands apart from role membership
        — segregation of duties over damage money: the operator who adjudicates a
        damage assessment, or resolves an appeal on one, must not be the operator
        who recorded that assessment's intake. A caller whose `X-User-ID` equals
        the assessment's `recorded_by_user_id` is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), even when the caller otherwise
        holds the correct role."
        PRD §3.8: "The system stamps the caller's `X-User-ID` as
        `recorded_by_user_id`, computes `total_claimed_cents` as the sum of the
        line items' repair costs, opens the assessment in `OPEN`, and freezes the
        permit's deposit in the same motion: the financial dimension moves from
        `SECURED` or `INVOICED` to `FORFEIT_PENDING`, suspending any release
        pending adjudication."

        Design: Corner/validations/segregation_of_duties_on_adjudication
        """
        env, req, permit, _wo = _completed_permit(api, "dep-sod-1")
        intake_headers = make_coordinator_headers("coord-77")
        assessment = make_damage_assessment(
            permit["id"],
            [{"description": "Floor damage", "repair_cost_cents": 8000}],
            coordinator_headers=intake_headers)
        assert assessment["recorded_by_user_id"] == "coord-77"

        # The same operator id may not adjudicate, even under the right role.
        res = api.adjudicate_damage_assessment(
            assessment["id"], {"adjudicated_amount_cents": 8000},
            make_director_headers("coord-77"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        # A different operator id holding FacilitiesDirector succeeds.
        ok = validate_success(api.adjudicate_damage_assessment(
            assessment["id"], {"adjudicated_amount_cents": 8000},
            make_director_headers("director-01")))
        assert ok["assessment_status"] == "ADJUDICATED"


class TestAdjudicationCapAndAppealWindow:
    def test_appeal_window_elapsed_and_adjudication_cap(self, api):
        """PRD §3.8: "Adjudication belongs to the `FacilitiesDirector`, who awards
        an `adjudicated_amount_cents` — null until this point — of at least zero
        and at most `total_claimed_cents`; anything above the claim is rejected
        with `ERR_ADJUDICATION_EXCEEDS_CLAIM`."
        PRD §3.8: "The renter then has fourteen days, measured on the logical
        clock, to answer. Acceptance — or the window elapsing with no appeal —
        moves the assessment `ADJUDICATED` → `FINAL`. An appeal, filed with an
        `appeal_reason`, moves it `ADJUDICATED` → `APPEALED`; an appeal attempted
        after the fourteen-day window is rejected with
        `ERR_APPEAL_WINDOW_ELAPSED`."
        PRD §2.4: "Advancing the clock is not a passive read change: it fires
        every time-based system transition in the domain — insurance certificates
        expire, unapproved requests lapse, permits activate when their occupancy
        begins or lapse when their deposit was never secured, renter standing is
        recomputed against the thirty-day arrears rule, damage appeal windows
        close, and seasonal series complete at season's end."

        Design: Corner/validations/appeal_window_elapsed_and_adjudication_cap
        """
        env, req, permit, _wo = _completed_permit(api, "dep-ap-1")
        assessment = make_damage_assessment(permit["id"], [
            {"description": "Window", "repair_cost_cents": 8000}])

        # Award above the claim is rejected.
        over = api.adjudicate_damage_assessment(
            assessment["id"], {"adjudicated_amount_cents": 9000},
            make_director_headers("director-01"))
        validate_error(over, ApiErrorId.ERR_ADJUDICATION_EXCEEDS_CLAIM)
        ok = validate_success(api.adjudicate_damage_assessment(
            assessment["id"], {"adjudicated_amount_cents": 8000},
            make_director_headers("director-01")))
        assert ok["assessment_status"] == "ADJUDICATED"

        # 15.5 days after adjudication — past the fourteen-day window. The late
        # appeal is rejected: either by the window rule, or, where the clock
        # advance already closed the window and finalized the assessment, by the
        # terminal-state legality check.
        set_clock("2026-09-29T00:00:00Z")
        late = api.appeal_damage_assessment(
            assessment["id"], {"appeal_reason": "15 days later"},
            make_renter_headers(env["org"]["id"]))
        validate_error_is_one_of(late, [
            ApiErrorId.ERR_APPEAL_WINDOW_ELAPSED,
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        ])


class TestEmptyDamageClaim:
    def test_empty_damage_claim_rejected(self, api):
        """PRD §3.8: "Intake belongs to the `SiteCoordinator`: on a `COMPLETED`
        permit, they record a **DamageAssessment** whose `line_items` form a
        non-empty array, each entry carrying a `description` and a
        `repair_cost_cents` strictly greater than zero — an empty array or any
        non-positive cost is rejected with `ERR_EMPTY_DAMAGE_CLAIM`."

        Design: Corner/errors/empty_damage_claim_rejected
        """
        env, req, permit, _wo = _completed_permit(api, "dep-ed-1")
        coordinator = make_coordinator_headers("coord-77")

        empty = api.create_damage_assessment(permit["id"], {"line_items": []},
                                             coordinator)
        validate_error(empty, ApiErrorId.ERR_EMPTY_DAMAGE_CLAIM)
        zero_cost = api.create_damage_assessment(
            permit["id"],
            {"line_items": [{"description": "Free repair", "repair_cost_cents": 0}]},
            coordinator)
        validate_error(zero_cost, ApiErrorId.ERR_EMPTY_DAMAGE_CLAIM)

        assessments = validate_success(api.list_permit_damage_assessments(
            permit["id"], DIRECTOR))
        assert assessments == [], "no DamageAssessment row created"
        permit_after = validate_success(api.get_permit(permit["id"], DIRECTOR))
        assert permit_after["financial_status"] == "INVOICED", (
            "rejected intakes leave the financial dimension untouched")
