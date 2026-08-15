"""Visit requests: offer/decline/accept cycle, offer expiry, OCC on the
request version, candidate-team scoring and ranking, unmet-demand summary."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instants_equal,
    complete_orientation,
    complete_visit_ok,
    create_request_ok,
    get_team,
    get_visit,
    get_visit_request,
    offer_request_ok,
    accept_request_ok,
    run_sweeps,
    schedule_visit_ok,
    set_clock,
    setup_active_facility,
    setup_certified_team,
    setup_certified_team_at_facility,
    sign_waiver,
    verify_visit_ok,
    create_active_handler,
    create_forming_team,
    register_animal,
    make_handler_headers,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]


def _request_ctx(name: str):
    """Certified team + ACTIVE facility + orientation + waiver (offer-eligible)."""
    return setup_certified_team_at_facility(
        team_kwargs={"handler_name": name, "team_name": f"{name} Team"},
        facility_kwargs={"name": f"School {name}"},
    )


class TestOfferDeclineCycle:
    def test_decline_returns_request_to_open_with_count(self):
        """PRD §3.6: "Declining — again the offered team's handler, same `OFFERED` and ownership gates — returns the request to `OPEN`, clears `offered_team_id`, `offered_at`, and `offer_expires_at`, and increments `decline_count`; when instead the seventy-two hours lapse, the sweep performs the same return to `OPEN` and clearing but does not increment `decline_count`."
        PRD §3.6: "A successful offer stamps `offered_team_id`, sets `offered_at` to now, fixes `offer_expires_at` seventy-two hours later, moves the request to `OFFERED`, and increments the request's `version` by one."

        Design: Difficulty/non_linear_state_machine/request_offer_decline_cycle
        """
        ctx = _request_ctx("H Q")
        request = create_request_ok(ctx["facility"]["id"], "2026-08-10T14:00:00Z",
                                    "2026-08-10T15:00:00Z")
        offered = offer_request_ok(request["id"], ctx["team"]["id"])
        assert offered["status"] == "OFFERED"
        declined = validate_success(
            api_client.decline_visit_request(request["id"],
                                             make_handler_headers(ctx["handler"]["id"]))
        )
        assert declined["status"] == "OPEN", "The SAME request row cycles back to OPEN"
        assert declined["decline_count"] == 1
        assert declined["offered_team_id"] is None, "Offer fields must be cleared"
        assert declined["offered_at"] is None
        assert declined["offer_expires_at"] is None

    def test_reoffer_and_accept_after_decline(self):
        """PRD §3.6: "Acceptance creates the visit with the offered `team_id`, the request's `facility_id`, the requested window as its `scheduled_start` and `scheduled_end`, and the `request_id` linking back to the request; the visit starts `SCHEDULED` and `UNVERIFIED`, the request moves to `ACCEPTED`, the team's `version` increments by one, and the animal's `forward_workload_minutes` rises by the scheduled minutes per the forward-looking variant."

        Design: Difficulty/non_linear_state_machine/request_offer_decline_cycle
        """
        ctx = _request_ctx("H Q2")
        request = create_request_ok(ctx["facility"]["id"], "2026-08-10T14:00:00Z",
                                    "2026-08-10T15:00:00Z")
        offer_request_ok(request["id"], ctx["team"]["id"])
        validate_success(
            api_client.decline_visit_request(request["id"],
                                             make_handler_headers(ctx["handler"]["id"]))
        )
        # A second offer/accept cycle succeeds on the same row.
        reoffered = offer_request_ok(request["id"], ctx["team"]["id"])
        assert reoffered["status"] == "OFFERED"
        visit = accept_request_ok(request["id"], ctx["handler"]["id"])
        assert visit["lifecycle_status"] == "SCHEDULED"
        assert visit["verification_status"] == "UNVERIFIED"
        assert visit["request_id"] == request["id"]
        assert_instants_equal(visit["scheduled_start"], "2026-08-10T14:00:00Z")
        assert_instants_equal(visit["scheduled_end"], "2026-08-10T15:00:00Z")
        after = get_visit_request(request["id"])
        assert after["status"] == "ACCEPTED"


class TestCandidateMatching:
    def _setup_match_scenario(self):
        """Two certified teams; T1 (DOG, volunteer_since 2024-08-01, one VERIFIED
        visit at f on 2026-07-22, forward workload 60); T2 (CAT, since
        2022-08-01, never visited f, workload 0). Request: DOG, URGENT."""
        t1 = setup_certified_team(handler_name="H T1", team_name="T1",
                                  volunteer_since="2024-08-01",
                                  animal_name="D1", breed="Poodle")
        t2 = setup_certified_team(handler_name="H T2", team_name="T2", species="CAT",
                                  volunteer_since="2022-08-01",
                                  animal_name="C2", breed="Siamese",
                                  # T1's chain advanced the clock to 11:00; schedule
                                  # T2's evaluation at a not-in-the-past slot.
                                  eval_start="2026-08-02T11:30:00Z",
                                  eval_end="2026-08-02T12:30:00Z")
        fac_ctx = setup_active_facility(name="School C", allowed_species=("DOG", "CAT"),
                                        visits_per_week_cap=10)
        for team_ctx in (t1, t2):
            complete_orientation(team_ctx["team"]["id"], fac_ctx["facility"]["id"],
                                 attended_on="2026-07-20")
            sign_waiver(team_ctx["handler"]["id"], team_ctx["team"]["id"],
                        fac_ctx["facility"]["id"], signed_on="2026-07-20")
        # T1's verified visit at f on 2026-07-22 (past, so the clock steps back
        # before booking it — the logical clock is a free test-driving dial).
        set_clock("2026-07-20T00:00:00Z")
        v_past = schedule_visit_ok(t1["team"]["id"], fac_ctx["facility"]["id"],
                                   "2026-07-22T10:00:00Z", "2026-07-22T11:00:00Z")
        complete_visit_ok(v_past["id"], t1["handler"]["id"],
                          "2026-07-22T10:00:00Z", "2026-07-22T11:00:00Z")
        verify_visit_ok(v_past["id"], fac_ctx["facility"]["id"])
        # A forward SCHEDULED visit gives T1 a 60-minute forward workload.
        schedule_visit_ok(t1["team"]["id"], fac_ctx["facility"]["id"],
                          "2026-08-06T10:00:00Z", "2026-08-06T11:00:00Z")
        set_clock("2026-08-05T00:00:00Z")
        request = create_request_ok(fac_ctx["facility"]["id"],
                                    "2026-08-10T14:00:00Z", "2026-08-10T15:00:00Z",
                                    species_preference="DOG", priority="URGENT")
        return t1, t2, fac_ctx, request

    def test_match_score_ranking_order(self):
        """PRD §3.6: "Experience contributes five points per full year elapsed since the handler's `volunteer_since`, capped at forty points. Species contributes twenty-five points when the animal's `species` equals the request's `species_preference`, ten points when the request names no preference, and zero on a mismatch. Recency contributes twenty points minus two per full week since the team's most recent `VERIFIED` visit to that facility, clamped between zero and twenty — and a team that has never had a verified visit there scores zero. The workload penalty subtracts one point per full ten minutes of the animal's current `forward_workload_minutes`, capped at thirty. The subtotal — experience plus species plus recency minus penalty — is then multiplied by 1.5 for an `URGENT` request, 1.2 for `HIGH`, or 1.0 for `ROUTINE`, and the product rounded half-up to two decimal places is the team's score. The slate is ranked by score descending with ties broken by the team's `created_at` ascending; an empty candidate pool is not an error — the response is an empty array with HTTP 200."

        Design: Difficulty/combinatorial_formula/match_score_nested_minmax_branch
        """
        t1, t2, _fac_ctx, request = self._setup_match_scenario()
        data = validate_success(api_client.get_candidate_teams(request["id"], ADMIN))
        assert len(data) == 2
        # T1: (min(2*5, 40) + 25 + (20 - 2*2) - min(6, 30)) * 1.5 = 45 * 1.5 = 67.5
        # T2: (min(4*5, 40) + 0 + 0 - 0) * 1.5 = 30.0  -> T1 ranks first.
        assert data[0]["id"] == t1["team"]["id"], (
            f"T1 (score 67.5) must outrank T2 (score 30.0); got order {[d['id'] for d in data]}"
        )
        assert data[1]["id"] == t2["team"]["id"]

    def test_species_mismatch_lowers_score_but_does_not_exclude(self):
        """PRD §3.6: "Species contributes twenty-five points when the animal's `species` equals the request's `species_preference`, ten points when the request names no preference, and zero on a mismatch."
        PRD §3.6: "A team is eligible only when every one of the following holds: the team is `ACTIVE`; its handler is `ACTIVE`; its animal is `ACTIVE` with no welfare hold in force (`welfare_hold_until` null); the team's certification is `ACTIVE`; a `SIGNED` waiver exists for the team and the request's facility whose `waiver_version` equals the facility's `required_waiver_version`; an orientation record for the team at that facility stands `COMPLETED` with `expires_on` today or later; the handler's insurance is adequate per the facility-specific requirement of §3.5; and, for a `NURSING_HOME`, the handler's `recognition_tier` is anything other than `NONE`."

        Design: Difficulty/combinatorial_formula/match_score_nested_minmax_branch
        """
        t1, t2, _fac_ctx, request = self._setup_match_scenario()
        data = validate_success(api_client.get_candidate_teams(request["id"], ADMIN))
        ids = {row["id"] for row in data}
        assert ids == {t1["team"]["id"], t2["team"]["id"]}, (
            "Both teams are eligible; the CAT team scores zero on species but is NOT excluded"
        )

    def test_candidate_teams_empty_pool_returns_empty_array(self):
        """PRD §3.6: "The slate is ranked by score descending with ties broken by the team's `created_at` ascending; an empty candidate pool is not an error — the response is an empty array with HTTP 200."

        Design: Corner/endpoints/candidate_teams_empty_pool_returns_empty_array
        """
        handler = create_active_handler(full_name="H EP")
        animal = register_animal(handler["id"], name="D")
        # Team stays FORMING (no certification) -> fails the eligibility filter.
        create_forming_team(handler["id"], animal["id"], "TEP")
        fac_ctx = setup_active_facility(name="Fac EP")
        request = create_request_ok(fac_ctx["facility"]["id"],
                                    "2026-08-10T14:00:00Z", "2026-08-10T15:00:00Z")
        resp = api_client.get_candidate_teams(request["id"], ADMIN)
        data = validate_success(resp, 200)
        assert data == [], f"An empty candidate pool is a 200 empty array, got {data}"


class TestOfferGates:
    def test_offer_to_ineligible_team_rejected(self):
        """PRD §3.6: "A `ProgramAdmin` offers an `OPEN` request (otherwise `ERR_REQUEST_NOT_OPEN`) to a chosen team by submitting the `team_id` together with the OCC field `expected_visit_request_version` per §2.6 — a stale view of the request fails with `ERR_STALE_VERSION` — and the named team must pass the full eligibility filter above (otherwise `ERR_TEAM_NOT_ELIGIBLE`)."

        Design: Corner/errors/offer_to_ineligible_team_rejected
        """
        # Certified team but NO orientation and NO waiver at this facility.
        team_ctx = setup_certified_team(handler_name="H NE", team_name="TNE")
        fac_ctx = setup_active_facility(name="Fac NE")
        request = create_request_ok(fac_ctx["facility"]["id"],
                                    "2026-08-10T14:00:00Z", "2026-08-10T15:00:00Z")
        version = request["version"]
        resp = api_client.create_offer(
            request["id"],
            {"team_id": team_ctx["team"]["id"], "expected_visit_request_version": version},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_TEAM_NOT_ELIGIBLE)

    def test_accept_after_offer_expiry_rejected(self):
        """PRD §3.6: "Acceptance requires the request still `OFFERED` (otherwise `ERR_REQUEST_NOT_OFFERED`), the acting handler to own the offered team (otherwise `ERR_OWNERSHIP_MISMATCH`), and the clock not past `offer_expires_at` (otherwise `ERR_OFFER_EXPIRED`); it then re-runs the entire visit-creation gate chain of §3.7 against the requested window — safety, referential, temporal, fiscal, and constraint checks alike."
        PRD §3.6: "A successful offer stamps `offered_team_id`, sets `offered_at` to now, fixes `offer_expires_at` seventy-two hours later, moves the request to `OFFERED`, and increments the request's `version` by one."

        Design: Corner/errors/accept_after_offer_expiry_rejected
        """
        ctx = _request_ctx("H OX")
        request = create_request_ok(ctx["facility"]["id"], "2026-08-10T14:00:00Z",
                                    "2026-08-10T15:00:00Z")
        set_clock("2026-08-02T12:00:00Z")
        offer_request_ok(request["id"], ctx["team"]["id"])
        # offer_expires_at = 2026-08-05T12:00Z; one second past it, no sweep run,
        # so the row is still OFFERED and the temporal gate is what fires.
        set_clock("2026-08-05T12:00:01Z")
        resp = api_client.accept_visit_request(request["id"],
                                               make_handler_headers(ctx["handler"]["id"]))
        validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)

    def test_occ_stale_version_on_offer(self):
        """PRD §2.6: "Creating an offer against a visit request requires `expected_visit_request_version` carrying the client's last observed `version` of that request. If the request's current `version` does not match — because another writer has advanced it since the client last read the request — the offer is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.6: "A successful offer stamps `offered_team_id`, sets `offered_at` to now, fixes `offer_expires_at` seventy-two hours later, moves the request to `OFFERED`, and increments the request's `version` by one."

        Design: Corner/cross_cutting/occ_stale_version_on_offer
        """
        ctx = _request_ctx("H OCC")
        request = create_request_ok(ctx["facility"]["id"], "2026-08-10T14:00:00Z",
                                    "2026-08-10T15:00:00Z")
        observed = request["version"]
        first = validate_success(api_client.create_offer(
            request["id"],
            {"team_id": ctx["team"]["id"], "expected_visit_request_version": observed},
            ADMIN,
        ))
        assert first["status"] == "OFFERED"
        assert first["version"] == observed + 1, "A successful offer increments version by one"
        stale = api_client.create_offer(
            request["id"],
            {"team_id": ctx["team"]["id"], "expected_visit_request_version": observed},
            ADMIN,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)


class TestRequestSweeps:
    def test_sweep_offer_expiry_reopens_without_decline_count(self):
        """PRD §3.6: "Declining — again the offered team's handler, same `OFFERED` and ownership gates — returns the request to `OPEN`, clears `offered_team_id`, `offered_at`, and `offer_expires_at`, and increments `decline_count`; when instead the seventy-two hours lapse, the sweep performs the same return to `OPEN` and clearing but does not increment `decline_count`."

        Design: Corner/state_machines/sweep_offer_expiry_reopens_without_decline_count
        """
        ctx = _request_ctx("H OE")
        request = create_request_ok(ctx["facility"]["id"], "2026-08-10T14:00:00Z",
                                    "2026-08-10T15:00:00Z")
        set_clock("2026-08-02T12:00:00Z")
        offer_request_ok(request["id"], ctx["team"]["id"])
        set_clock("2026-08-05T12:00:01Z")  # past offered_at + 72 hours
        sweep = run_sweeps()
        assert sweep["offers_expired"] == 1
        after = get_visit_request(request["id"])
        assert after["status"] == "OPEN"
        assert after["decline_count"] == 0, "Sweep expiry must NOT count as a decline"
        assert after["offered_team_id"] is None

    def test_sweep_request_expiry_feeds_unmet_demand(self):
        """PRD §3.6: "A request still `OPEN` once its `requested_end` has passed is swept to `EXPIRED` with `expired_on` stamped — the raw material of the unmet-demand measure of §3.8."
        PRD §3.8: "The demand summary for a facility reports the `facility_id`, the `open_request_count` of its requests standing `OPEN` or `OFFERED`, the `expired_last_90d` count of requests swept to `EXPIRED` whose `expired_on` falls on or after ninety days before today — the boundary date itself included — the `fulfilled_last_90d` count of requests reaching `FULFILLED` with `fulfilled_on` inside the same window, and the `unmet_demand_index` formed as the sum of the open count and the recently expired count."

        Design: Corner/state_machines/sweep_request_expiry_feeds_unmet_demand
        """
        fac_ctx = setup_active_facility(name="Fac D")
        request = create_request_ok(fac_ctx["facility"]["id"], "2026-08-10T14:00:00Z",
                                    "2026-08-10T15:00:00Z", priority="URGENT")
        set_clock("2026-08-11T00:00:00Z")  # requested_end has passed
        sweep = run_sweeps()
        assert sweep["requests_expired"] == 1
        summary = validate_success(
            api_client.get_facility_demand_summary(fac_ctx["facility"]["id"], ADMIN)
        )
        assert summary["open_request_count"] == 0
        assert summary["expired_last_90d"] == 1
        assert summary["unmet_demand_index"] == 1, (
            "unmet_demand_index = open_request_count + expired_last_90d"
        )


class TestOfferCycleCardinality:
    def _run_full_cycle(self):
        ctx = _request_ctx("H V3")
        r1 = create_request_ok(ctx["facility"]["id"], "2026-08-10T14:00:00Z",
                               "2026-08-10T15:00:00Z", priority="ROUTINE")
        r2 = create_request_ok(ctx["facility"]["id"], "2026-08-12T09:00:00Z",
                               "2026-08-12T09:30:00Z", visit_program="READING",
                               priority="HIGH")
        offer_request_ok(r1["id"], ctx["team"]["id"])
        validate_success(
            api_client.decline_visit_request(r1["id"], make_handler_headers(ctx["handler"]["id"]))
        )
        offer_request_ok(r1["id"], ctx["team"]["id"])
        visit = accept_request_ok(r1["id"], ctx["handler"]["id"])
        # Cancel well over 48 hours before scheduled_start (now: 2026-08-02).
        cancelled = validate_success(
            api_client.cancel_visit(visit["id"], {"reason": "handler conflict"},
                                    make_handler_headers(ctx["handler"]["id"]))
        )
        return ctx, r1, r2, visit, cancelled

    def test_request_cardinality_conserved_through_cycle(self):
        """PRD §3.6: "Requests resolve in four terminal directions. Completion of the backed visit bubbles the request `ACCEPTED → FULFILLED` and stamps `fulfilled_on` with the date. Cancellation or no-show of the backed visit compensates the request `ACCEPTED → OPEN`, clearing the offer fields while the visit keeps its `request_id` linkage. A request still `OPEN` once its `requested_end` has passed is swept to `EXPIRED` with `expired_on` stamped — the raw material of the unmet-demand measure of §3.8. And withdrawal ends the request at `WITHDRAWN`."
        PRD §2.3: "The `meta` object of every list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Difficulty/compensating_invariant/offer_cycle_queue_cardinality_conservation
        """
        ctx, r1, _r2, _visit, _cancelled = self._run_full_cycle()
        _rows, meta = validate_paginated(
            api_client.list_visit_requests(ADMIN, params={"facility_id": ctx["facility"]["id"]})
        )
        assert meta["total_count"] == 2, (
            "No VisitRequest row is created or destroyed through offer -> decline -> offer -> accept -> cancel"
        )
        after = get_visit_request(r1["id"])
        assert after["status"] == "OPEN", "Accept-then-cancel compensates back to OPEN"
        assert after["decline_count"] == 1, "Only the explicit decline counts"

    def test_handler_cancel_reason_and_no_late_penalty(self):
        """PRD §3.7: "The cancellation stamps `cancelled_at` and records a `cancel_reason` mapped from the actor — `HANDLER_CANCEL`, `ADMIN_CANCEL`, or `FACILITY_CANCEL` — or from the system cause when a cascade drives it: `AGREEMENT_ENDED`, `CERT_SUSPENDED`, `CERT_REVOKED`, `TEAM_DISSOLVED`, or `INCIDENT_PRECAUTION`."
        PRD §3.7: "Handler-initiated cancellation alone carries the late-cancel penalty, tiered by notice floored to whole hours before `scheduled_start`: forty-eight hours or more costs nothing; twenty-four up to forty-eight hours adds one point to the team's `late_cancel_count`; under twenty-four hours adds two."

        Design: Difficulty/compensating_invariant/offer_cycle_queue_cardinality_conservation
        """
        ctx, _r1, _r2, visit, cancelled = self._run_full_cycle()
        assert cancelled["lifecycle_status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "HANDLER_CANCEL"
        team = get_team(ctx["team"]["id"])
        assert team["late_cancel_count"] == 0, (
            "Notice of roughly eight days (>= 48 hours) costs zero penalty points"
        )
        kept = get_visit(visit["id"])
        assert kept["request_id"] is not None, "The visit keeps its request linkage"
