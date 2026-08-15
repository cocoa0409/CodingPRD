"""Query log discipline: turnaround measurement, closure cascade, aging."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_query,
    close_query,
    create_fieldwork_engagement,
    create_pbc,
    create_query,
    escalate_query,
    get_engagement,
    get_query,
    respond_query,
    route_query,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CONTROLLER = TEST_USERS["controller_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestTurnaroundCeilingBoundary:

    def test_turnaround_exactly_on_the_hour(self):
        """PRD §3.3: "A successful response stamps `responded_at` from the
        logical clock, moves the query to `RESPONDED`, and computes
        `turnaround_hours` as the elapsed seconds between `raised_at` and
        `responded_at` divided by 3600 and rounded up to a whole hour — with
        the boundary convention that a gap landing exactly on the hour yields
        that hour count itself, so exactly 7200 seconds yields 2, not 3."

        Design: Difficulty/combinatorial_formula/query_turnaround_ceiling_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        eng, _loc = create_fieldwork_engagement(client_name="DeltaCo")
        q = create_query(eng["id"], subject="Cutoff", severity="MEDIUM")
        route_query(q["id"])
        set_clock("2026-08-01T02:00:00Z")
        resp = api_client.respond_to_query(
            q["id"], {"response_text": "See attached"},
            TEST_USERS["preparer_headers"])
        data = validate_success(resp)
        assert_query(data)
        assert data["status"] == "RESPONDED"
        assert data["turnaround_hours"] == 2, (
            f"exactly 7200 seconds must yield 2 (not 3), got "
            f"{data['turnaround_hours']}"
        )
        assert data["responded_at"] is not None

    def test_turnaround_one_second_over_the_hour(self):
        """PRD §3.3: "computes `turnaround_hours` as the elapsed seconds
        between `raised_at` and `responded_at` divided by 3600 and rounded up
        to a whole hour — with the boundary convention that a gap landing
        exactly on the hour yields that hour count itself, so exactly 7200
        seconds yields 2, not 3."

        Design: Difficulty/combinatorial_formula/query_turnaround_ceiling_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        eng, _loc = create_fieldwork_engagement(client_name="DeltaCo")
        q = create_query(eng["id"], subject="Cutoff", severity="MEDIUM")
        route_query(q["id"])
        set_clock("2026-08-01T02:00:01Z")
        resp = api_client.respond_to_query(
            q["id"], {"response_text": "See attached"},
            TEST_USERS["preparer_headers"])
        data = validate_success(resp)
        assert data["turnaround_hours"] == 3, (
            f"7201 seconds rounds up to 3, got {data['turnaround_hours']}"
        )

    def test_turnaround_below_one_hour_rounds_up_to_one(self):
        """PRD §3.3: "computes `turnaround_hours` as the elapsed seconds
        between `raised_at` and `responded_at` divided by 3600 and rounded up
        to a whole hour".
        PRD §3.3: "Until the first response is logged, `turnaround_hours` is
        null."

        Design: Corner/calculations/query_turnaround_hours_boundary_below_one_hour
        """
        set_clock("2026-08-01T00:00:00Z")
        eng, _loc = create_fieldwork_engagement(client_name="C")
        q = create_query(eng["id"], subject="Q", severity="LOW")
        assert q["turnaround_hours"] is None, \
            "turnaround_hours is null until the first response"
        route_query(q["id"])
        set_clock("2026-08-01T00:30:00Z")
        data = respond_query(q["id"], response_text="r")
        assert data["turnaround_hours"] == 1, (
            f"1800 seconds rounds up to 1, got {data['turnaround_hours']}"
        )


class TestPbcAgingScore:

    def test_aging_score_with_one_open_query(self):
        """PRD §3.2: "First, `recency_days` is the number of days between the
        most recent upload's `uploaded_at` and now, floored at zero; if the
        request has no evidence yet, the days between the request's
        `created_at` and now are used instead."
        PRD §3.2: "Third, a backlog multiplier of one plus one-tenth of the
        engagement's current `open_query_count` is read from the engagement
        row as it currently stands, not recomputed inside the formula. Fourth,
        the score is one hundred times the quantity one minus freshness,
        multiplied by the backlog multiplier, rounded half-up to 2 decimal
        places."

        Design: Difficulty/combinatorial_formula/pbc_aging_score_circular_eval_order
        """
        set_clock("2026-08-01T00:00:00Z")
        eng, _loc = create_fieldwork_engagement(client_name="GammaInc")
        pbc = create_pbc(eng["id"], owner="prep1", title="Trial balance")
        create_query(eng["id"], subject="Revenue recognition",
                     severity="HIGH")
        set_clock("2026-08-11T00:00:00Z")
        data, _meta = validate_paginated(
            api_client.list_pbc_requests(
                CONTROLLER, params={"engagement_id": eng["id"]}))
        item = next(p for p in data if p["id"] == pbc["id"])
        # recency_days=10, freshness=1/11, backlog=1+0.1*1=1.1
        # score = round_half_up(100 * (10/11) * 1.1, 2) = 100.0
        assert item["pbc_aging_score"] == pytest.approx(100.0, abs=0.01), (
            f"expected pbc_aging_score 100.0, got {item['pbc_aging_score']}"
        )

    def test_aging_score_backlog_multiplier_with_two_open_queries(self):
        """PRD §3.2: "Third, a backlog multiplier of one plus one-tenth of the
        engagement's current `open_query_count` is read from the engagement
        row as it currently stands, not recomputed inside the formula."
        PRD §3.3: "The query opens in `OPEN` status with `raised_at` stamped
        from the logical clock, the raiser's `X-User-ID` recorded as
        `auditor_user_id`, `responded_at` null, and the engagement's
        `open_query_count` incremented by one."

        Design: Difficulty/combinatorial_formula/pbc_aging_score_circular_eval_order
        """
        set_clock("2026-08-01T00:00:00Z")
        eng, _loc = create_fieldwork_engagement(client_name="GammaInc")
        pbc = create_pbc(eng["id"], owner="prep1", title="Trial balance")
        create_query(eng["id"], subject="Q1", severity="LOW")
        create_query(eng["id"], subject="Q2", severity="MEDIUM")
        assert get_engagement(eng["id"])["open_query_count"] == 2
        set_clock("2026-08-11T00:00:00Z")
        data, _meta = validate_paginated(
            api_client.list_pbc_requests(
                CONTROLLER, params={"engagement_id": eng["id"]}))
        item = next(p for p in data if p["id"] == pbc["id"])
        # recency_days=10, freshness=1/11, backlog=1+0.1*2=1.2
        # score = round_half_up(100 * (10/11) * 1.2, 2) = 109.09
        assert item["pbc_aging_score"] == pytest.approx(109.09, abs=0.01), (
            f"expected pbc_aging_score 109.09, got {item['pbc_aging_score']}"
        )


class TestQueryCloseCascade:

    def test_close_responded_query_decrements_open_count(self):
        """PRD §3.3: "Closure, also the auditor's, is permitted from
        `RESPONDED` or `ESCALATED` — otherwise `ERR_QUERY_NOT_CLOSABLE` — and
        lands on the terminal `CLOSED` state, decrementing the engagement's
        `open_query_count` by one."

        Design: Difficulty/transitive_cascade/query_close_decrements_engagement_open_count
        """
        eng, _loc = create_fieldwork_engagement(client_name="ThetaLLC")
        q1 = create_query(eng["id"], subject="Q1", severity="LOW")
        q2 = create_query(eng["id"], subject="Q2", severity="MEDIUM")
        assert get_engagement(eng["id"])["open_query_count"] == 2
        route_query(q1["id"])
        respond_query(q1["id"], response_text="answered")
        closed = close_query(q1["id"])
        assert closed["status"] == "CLOSED"
        assert get_engagement(eng["id"])["open_query_count"] == 1, (
            "close decrements open_query_count by exactly one"
        )
        assert get_query(q2["id"])["status"] == "OPEN", \
            "the untouched query stays OPEN"

    def test_close_escalated_query_decrements_open_count(self):
        """PRD §3.3: "from either `OPEN` or `AWAITING_CLIENT`, escalating
        moves the query to `ESCALATED` (the same `ERR_QUERY_NOT_OPEN` guards
        attempts from any other state)."
        PRD §3.3: "Closure, also the auditor's, is permitted from `RESPONDED`
        or `ESCALATED` — otherwise `ERR_QUERY_NOT_CLOSABLE` — and lands on the
        terminal `CLOSED` state, decrementing the engagement's
        `open_query_count` by one."

        Design: Difficulty/transitive_cascade/query_close_decrements_engagement_open_count
        """
        eng, _loc = create_fieldwork_engagement(client_name="ThetaLLC")
        q1 = create_query(eng["id"], subject="Q1", severity="LOW")
        create_query(eng["id"], subject="Q2", severity="MEDIUM")
        escalated = escalate_query(q1["id"])
        assert escalated["status"] == "ESCALATED"
        closed = close_query(q1["id"])
        assert closed["status"] == "CLOSED"
        assert get_engagement(eng["id"])["open_query_count"] == 1


class TestQueryInvalidTransitions:

    def test_close_from_open_rejected(self):
        """PRD §3.3: "Closure, also the auditor's, is permitted from
        `RESPONDED` or `ESCALATED` — otherwise `ERR_QUERY_NOT_CLOSABLE`".

        Design: Corner/state_machines/query_close_from_open_rejected
        """
        eng, _loc = create_fieldwork_engagement(client_name="C")
        q = create_query(eng["id"], subject="S", severity="LOW")
        resp = api_client.close_query(q["id"], AUDITOR)
        validate_error(resp, ApiErrorId.ERR_QUERY_NOT_CLOSABLE)
        assert get_query(q["id"])["status"] == "OPEN"

    def test_query_not_found_returns_404(self):
        """PRD §2.5: "The server confirms the existence of each identifier in
        path order and rejects the request immediately with the 404 error
        corresponding to the first identifier that does not resolve:
        `ERR_ENGAGEMENT_NOT_FOUND` for engagements, `ERR_LOCATION_NOT_FOUND`
        for locations, `ERR_PBC_NOT_FOUND` for PBC requests,
        `ERR_EVIDENCE_NOT_FOUND` for evidence uploads, `ERR_QUERY_NOT_FOUND`
        for queries".

        Design: Corner/errors/error_query_not_found
        """
        create_fieldwork_engagement(client_name="C")
        resp = api_client.get_query(NON_EXISTENT_UUID, CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_QUERY_NOT_FOUND)
