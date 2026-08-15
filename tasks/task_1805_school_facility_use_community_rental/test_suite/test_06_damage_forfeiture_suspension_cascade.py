"""Depth-3 cascade: damage FINAL -> forfeiture allocation -> org suspension
(PRD §3.3, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    sum_txns,
    make_renter_headers,
    make_booking_env, make_under_review_request, approve,
    capture_deposit, set_clock, make_draft_request, submit_request,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]

DAYS = [("2026-09-06T00:00:00Z", "2026-09-06T03:00:00Z", "2026-09-06T12:00:00Z"),
        ("2026-09-13T00:00:00Z", "2026-09-13T03:00:00Z", "2026-09-13T12:00:00Z"),
        ("2026-09-20T00:00:00Z", "2026-09-20T03:00:00Z", "2026-09-20T12:00:00Z")]


def _damage_cycle(api, env, day_start, day_end, clock_after, title,
                  line_items, adjudicated, dep_key, via_appeal=False):
    """Approved permit -> deposit -> complete -> intake -> adjudicate ->
    accept (or appeal + resolve_appeal). Returns (permit, assessment)."""
    req = make_under_review_request(env, event_title=title, headcount_estimate=100,
                                    starts_at=day_start, ends_at=day_end)
    permit = approve(req["id"], req["version"])
    capture_deposit(env, permit["id"], 10000, dep_key)
    set_clock(clock_after)
    validate_success(api.complete_permit(permit["id"], COORDINATOR))
    assessment = validate_success(api.create_damage_assessment(
        permit["id"], {"line_items": line_items}, COORDINATOR), 201)
    validate_success(api.adjudicate_damage_assessment(
        assessment["id"], {"adjudicated_amount_cents": adjudicated}, DIRECTOR))
    org_id = env["org"]["id"]
    if via_appeal:
        validate_success(api.appeal_damage_assessment(
            assessment["id"], {"appeal_reason": "Dispute stage repair scope"},
            make_renter_headers(org_id)))
        assessment = validate_success(api.resolve_damage_appeal(
            assessment["id"], {"final_amount_cents": adjudicated}, DIRECTOR))
    else:
        assessment = validate_success(api.accept_damage_assessment(
            assessment["id"], make_renter_headers(org_id)))
    return permit, assessment


def _three_forfeit_chain(api):
    """Trouble Club accrues three FINAL damage forfeits; the third goes through
    the appeal path. Returns (env, p3, da3)."""
    env = make_booking_env(org_name="Trouble Club",
                           insurance_overrides={"per_occurrence_limit_cents": 200000000,
                                                "aggregate_limit_cents": 400000000})
    _damage_cycle(api, env, *DAYS[0], "Event One",
                  [{"description": "Floor scuff", "repair_cost_cents": 5000}],
                  5000, "dep-f-1")
    _damage_cycle(api, env, *DAYS[1], "Event Two",
                  [{"description": "Broken window", "repair_cost_cents": 8000}],
                  8000, "dep-f-2")
    p3, da3 = _damage_cycle(
        api, env, *DAYS[2], "Event Three",
        [{"description": "Stage repair", "repair_cost_cents": 4000},
         {"description": "Paint", "repair_cost_cents": 3500},
         {"description": "Glass", "repair_cost_cents": 2000}],
        9500, "dep-f-3", via_appeal=True)
    return env, p3, da3


class TestDamageFinalToForfeitureToOrgSuspension:
    def test_resolve_appeal_finalizes_forfeiture_allocation(self, api):
        """PRD §3.8: "The amount applied to damage is the smaller of the held
        deposit and the adjudicated amount; the rest of the held deposit comes
        back to the renter as a `DEPOSIT_REFUND`."
        PRD §3.8: "resolution overwrites `adjudicated_amount_cents` with the final
        amount and moves the assessment `APPEALED` → `FINAL`."

        Design: Difficulty/transitive_cascade/damage_final_to_forfeiture_to_org_suspension_depth3
        """
        env, p3, da3 = _three_forfeit_chain(api)
        assert da3["assessment_status"] == "FINAL"
        assert da3["adjudicated_amount_cents"] == 9500

        # Hop 1: assessment FINAL triggers the permit's forfeiture allocation.
        p3_after = validate_success(api.get_permit(p3["id"], DIRECTOR))
        assert p3_after["financial_status"] == "FORFEITED"
        payments = validate_success(api.list_permit_payments(p3["id"], DIRECTOR))
        assert sum_txns(payments, "DEPOSIT_FORFEIT") == 9500
        assert sum_txns(payments, "DEPOSIT_REFUND") == 500   # 10000 held - 9500

    def test_third_forfeiture_suspends_org_and_blocks_submit(self, api):
        """PRD §3.8: "A finalization with an adjudicated amount above zero moves
        the permit `FORFEIT_PENDING` → `FORFEITED` and increments the renter's
        `forfeiture_count` by one — and a renter whose lifetime count reaches
        three is suspended from that moment."
        PRD §3.3: "Suspension blocks new request submissions and permit
        activations: attempts in that window are rejected with
        `ERR_RENTER_NOT_IN_GOOD_STANDING`."

        Design: Difficulty/transitive_cascade/damage_final_to_forfeiture_to_org_suspension_depth3
        """
        env, p3, da3 = _three_forfeit_chain(api)
        org = validate_success(api.get_renter(env["org"]["id"], DIRECTOR))
        # Hop 2: the forfeiture count mutation...
        assert org["forfeiture_count"] == 3
        # Hop 3: ...flips standing, caused by the count, not the original call.
        assert org["org_standing"] == "SUSPENDED"

        attempt = make_draft_request(
            env, event_title="New Attempt", headcount_estimate=50,
            starts_at="2026-12-05T01:00:00Z", ends_at="2026-12-05T03:00:00Z")
        res = api.submit_request(env["org"]["id"], attempt["id"],
                                 make_renter_headers(env["org"]["id"]))
        validate_error(res, ApiErrorId.ERR_RENTER_NOT_IN_GOOD_STANDING)
