"""Query intake, slush triage scoring, assignment, and slush-capacity posture."""
from test_helpers import (
    ApiErrorId,
    assert_manuscript,
    assert_query_letter,
    assign_query,
    create_agency,
    create_agent,
    create_author,
    create_query_letter_payload,
    get_agency,
    get_success_data,
    intake_query,
    make_agent_headers,
    request_manuscript,
    validate_error,
    validate_paginated,
    validate_success,
)


def _roster(name="Agency Q", slush_capacity=50):
    agency = create_agency(name=name, slush_capacity=slush_capacity)
    agent = create_agent(agency["id"])
    author = create_author(agency["id"])
    return agency, agent, author


class TestQueryIntake:
    def test_query_create_computes_triage_score_ignores_nothing(self, api):
        """PRD 3.2: "The genre factor awards 40 points for `FICTION`, 30 for
        `NONFICTION`, 25 for `YA`, and 10 for `MEMOIR`."
        PRD 3.2: "The length factor awards 40 points when `word_count` falls
        between 70,000 and 120,000 inclusive"
        PRD 3.2: "The author factor reads the author's `status` at intake time
        and awards 20 points for a `CLIENT`, 10 for a `PROSPECT`, and 0 for a
        `FORMER`."
        PRD 3.2: "A successful intake creates the letter in `RECEIVED` status
        with `agency_id` denormalized from the author, `assigned_agent_id`
        null, `requested_period_index` null, and a `triage_score` computed
        once, at this moment and never recomputed."

        Design: Corner/entities/query_create_computes_triage_score_ignores_nothing
        """
        _agency, agent, author = _roster("Agency TS")
        resp = api.create_query_letter(
            create_query_letter_payload(author["id"], genre="FICTION", word_count=90000),
            make_agent_headers(agent["id"]),
        )
        data = validate_success(resp, 201)
        assert_query_letter(data)
        assert data["triage_score"] == 90, (
            f"FICTION(40) + sweet-spot length(40) + PROSPECT(10) = 90, got {data['triage_score']}"
        )
        assert data["status"] == "RECEIVED"
        assert data["assigned_agent_id"] is None

    def test_query_create_with_computed_field_in_payload_invalid_request(self, api):
        """PRD 3.2: "An `Agent` intakes a query letter on behalf of a
        registered author by supplying the `author_id`, the claimed `genre`
        (one of `FICTION`, `NONFICTION`, `YA`, or `MEMOIR`), and the
        manuscript's claimed `word_count` (which must be greater than 0)."
        PRD 2.9: "required fields present, enums valid, ranges valid
        (`eval_score` between 0 and 100 inclusive, `word_count` greater than 0,
        monetary amounts greater than or equal to 0), and no undeclared fields
        (`ERR_INVALID_REQUEST`, 400)."

        Design: Corner/entities/query_create_with_computed_field_in_payload_invalid_request
        """
        _agency, agent, author = _roster("Agency CF")
        payload = create_query_letter_payload(author["id"], genre="FICTION", word_count=90000)
        payload["triage_score"] = 1
        resp = api.create_query_letter(payload, make_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_query_create_invalid_genre_enum_invalid_request(self, api):
        """PRD 3.2: "An `Agent` intakes a query letter on behalf of a
        registered author by supplying the `author_id`, the claimed `genre`
        (one of `FICTION`, `NONFICTION`, `YA`, or `MEMOIR`), and the
        manuscript's claimed `word_count` (which must be greater than 0)."
        PRD 2.9: "required fields present, enums valid, ranges valid
        (`eval_score` between 0 and 100 inclusive, `word_count` greater than 0,
        monetary amounts greater than or equal to 0), and no undeclared fields
        (`ERR_INVALID_REQUEST`, 400)."

        Design: Corner/entities/query_create_invalid_genre_enum_invalid_request
        """
        _agency, agent, author = _roster("Agency EN")
        resp = api.create_query_letter(
            create_query_letter_payload(author["id"], genre="ROMANCE", word_count=90000),
            make_agent_headers(agent["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_query_initial_state_received(self, api):
        """PRD 3.2: "A successful intake creates the letter in `RECEIVED`
        status with `agency_id` denormalized from the author,
        `assigned_agent_id` null, `requested_period_index` null, and a
        `triage_score` computed once, at this moment and never recomputed."

        Design: Corner/state_machines/query_initial_state_received
        """
        _agency, agent, author = _roster("Agency IS")
        resp = api.create_query_letter(
            create_query_letter_payload(author["id"], genre="YA", word_count=60000),
            make_agent_headers(agent["id"]),
        )
        data = validate_success(resp, 201)
        assert data["status"] == "RECEIVED"

    def test_triage_score_word_count_boundary_69999_vs_70000(self, api):
        """PRD 3.2: "The length factor awards 40 points when `word_count`
        falls between 70,000 and 120,000 inclusive; 20 points when it falls
        between 50,000 and 69,999 inclusive or between 120,001 and 150,000
        inclusive; and 5 points in every other case."
        PRD 3.2: "The `triage_score` is the sum of the three factors."

        Design: Corner/calculations/triage_score_word_count_boundary_69999_vs_70000
        """
        _agency, agent, author = _roster("Agency TB")
        low = intake_query(agent["id"], author["id"], genre="MEMOIR", word_count=69999)
        high = intake_query(agent["id"], author["id"], genre="MEMOIR", word_count=70000)
        assert low["triage_score"] == 40, (
            f"MEMOIR(10) + length[50000,69999](20) + PROSPECT(10) = 40, got {low['triage_score']}"
        )
        assert high["triage_score"] == 60, (
            f"MEMOIR(10) + length[70000,120000](40) + PROSPECT(10) = 60, got {high['triage_score']}"
        )

    def test_intake_paused_at_capacity_boundary(self, api, agency_admin_headers):
        """PRD 2.7: "Whenever any intake leaves the open slush count equal to
        `slush_capacity`, the posture flips from `NORMAL` to `INTAKE_PAUSED`;
        while paused, every attempt to intake a new query letter is rejected
        with `ERR_INTAKE_PAUSED`."
        PRD 2.7: "When a rejection, withdrawal, lapse, or manuscript request
        causes the open slush count to drop strictly below `slush_capacity`,
        the posture returns to `NORMAL`."

        Design: Corner/validations/intake_paused_at_capacity_boundary
        """
        agency, agent, author = _roster("Agency IP", slush_capacity=1)

        q1 = intake_query(agent["id"], author["id"], genre="FICTION", word_count=90000)
        assert q1["status"] == "RECEIVED"
        assert get_agency(agency["id"])["posture"] == "INTAKE_PAUSED", (
            "posture must flip to INTAKE_PAUSED once the open slush count reaches capacity"
        )

        blocked = api.create_query_letter(
            create_query_letter_payload(author["id"], genre="YA", word_count=80000),
            make_agent_headers(agent["id"]),
        )
        validate_error(blocked, ApiErrorId.ERR_INTAKE_PAUSED.value)

        ok = api.reject_query(q1["id"], make_agent_headers(agent["id"]))
        validate_success(ok, 200)
        assert get_agency(agency["id"])["posture"] == "NORMAL", (
            "posture must return to NORMAL once the open count drops below capacity"
        )

        q3 = api.create_query_letter(
            create_query_letter_payload(author["id"], genre="YA", word_count=80000),
            make_agent_headers(agent["id"]),
        )
        data3 = validate_success(q3, 201)
        assert data3["status"] == "RECEIVED"

    def test_royalties_accountant_cannot_intake_query_forbidden(
        self, api, royalties_accountant_headers
    ):
        """PRD 2.1: "Each endpoint admits a defined subset of these roles (see §4); a caller whose role is not admitted is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/roles/royalties_accountant_cannot_intake_query_forbidden
        """
        agency = create_agency(name="Agency RB1")
        author = create_author(agency["id"])
        resp = api.create_query_letter(
            create_query_letter_payload(author["id"], genre="FICTION", word_count=90000),
            royalties_accountant_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)

    def test_agent_open_query_count_reconciles_on_assign_and_reject(self, api, agency_admin_headers):
        """PRD 3.2: "Assignment writes `assigned_agent_id`, recomputes
        `open_query_count` for both the previously assigned agent (if any) and
        the newly assigned one, and re-evaluates the agency posture. An agent's
        `open_query_count` counts that agent's letters sitting in `RECEIVED` or
        `IN_REVIEW`."
        PRD 3.2: "the letter leaves the open slush set, so the agent's
        `open_query_count` is recomputed and the agency posture re-evaluated."

        Design: Corner/cross_cutting_layers/agent_open_query_count_reconciles_on_assign_and_reject
        """
        agency, agent, author = _roster("Agency DF")
        q1 = intake_query(agent["id"], author["id"], genre="FICTION", word_count=90000)
        q2 = intake_query(agent["id"], author["id"], genre="YA", word_count=80000)

        assign_query(q1["id"], agent["id"])
        assign_query(q2["id"], agent["id"])
        count2 = validate_success(api.get_agent(agent["id"], agency_admin_headers), 200)
        assert count2["open_query_count"] == 2

        validate_success(api.reject_query(q1["id"], make_agent_headers(agent["id"])), 200)
        count1 = validate_success(api.get_agent(agent["id"], agency_admin_headers), 200)
        assert count1["open_query_count"] == 1

        request_manuscript(q2["id"], agent["id"], title="T2")
        count0 = validate_success(api.get_agent(agent["id"], agency_admin_headers), 200)
        assert count0["open_query_count"] == 0

    def test_request_manuscript_spawns_manuscript_side_effect(self, api):
        """PRD 3.2: "The request supplies the manuscript's `title` and has
        three effects beyond the status change: `requested_period_index` is
        stamped with the agency's current `period_index`; a `Manuscript` record
        is created in `SUBMITTED` status with its `query_letter_id` pointing
        back to the letter, its `author_id` and `agency_id` copied from the
        letter, and its `reader_agent_id` initialized to the assigned agent"

        Design: Corner/state_machines/request_manuscript_spawns_manuscript_side_effect
        """
        _agency, agent, author = _roster("Agency SE")
        query = intake_query(agent["id"], author["id"], genre="FICTION", word_count=90000)
        assign_query(query["id"], agent["id"])

        resp = api.request_manuscript(
            query["id"], {"title": "Spawned"}, make_agent_headers(agent["id"])
        )
        manuscript = get_success_data(resp)
        assert_manuscript(manuscript)
        assert manuscript["status"] == "SUBMITTED"
        assert manuscript["reader_agent_id"] == agent["id"]
        assert manuscript["author_id"] == author["id"]

        found, _meta = validate_paginated(
            api.list_manuscripts(make_agent_headers(agent["id"]),
                                 params={"query_letter_id": query["id"]})
        )
        assert [m["id"] for m in found] == [manuscript["id"]]

        letter = validate_success(
            api.get_query_letter(query["id"], make_agent_headers(agent["id"])), 200
        )
        assert letter["status"] == "REQUESTED"
        assert letter["requested_period_index"] == 0

    def test_reject_from_requested_invalid_state(self, api):
        """PRD 3.2: "Alternatively, the assigned agent may reject the letter
        (`IN_REVIEW` → `REJECTED`, again guarded by `ERR_NOT_ASSIGNED_AGENT`,
        with the count and posture recomputed), and either the assigned agent
        or another agent may reject a letter still sitting unassigned in
        `RECEIVED` (`RECEIVED` → `REJECTED`, no assignment precondition,
        posture re-evaluated)."
        PRD 2.9: "State admissibility — the target resource must be in a state
        that permits the requested transition (`ERR_INVALID_STATE`, 409)."

        Design: Corner/state_machines/reject_from_requested_invalid_state
        """
        _agency, agent, author = _roster("Agency IV")
        query = intake_query(agent["id"], author["id"], genre="FICTION", word_count=90000)
        assign_query(query["id"], agent["id"])
        request_manuscript(query["id"], agent["id"], title="T")

        resp = api.reject_query(query["id"], make_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        letter = validate_success(
            api.get_query_letter(query["id"], make_agent_headers(agent["id"])), 200
        )
        assert letter["status"] == "REQUESTED"

    def test_reject_query_by_unassigned_agent_rejected(self, api):
        """PRD 3.2: "Alternatively, the assigned agent may reject the letter
        (`IN_REVIEW` → `REJECTED`, again guarded by `ERR_NOT_ASSIGNED_AGENT`,
        with the count and posture recomputed)"

        Design: Corner/validations/reject_query_by_unassigned_agent_rejected
        """
        agency = create_agency(name="Agency NA")
        agent1 = create_agent(agency["id"], display_name="Agent One")
        agent2 = create_agent(agency["id"], display_name="Agent Two")
        author = create_author(agency["id"])
        query = intake_query(agent1["id"], author["id"], genre="FICTION", word_count=90000)
        assign_query(query["id"], agent1["id"])

        resp = api.reject_query(query["id"], make_agent_headers(agent2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_AGENT.value)
        letter = validate_success(
            api.get_query_letter(query["id"], make_agent_headers(agent1["id"])), 200
        )
        assert letter["status"] == "IN_REVIEW"

    def test_assign_query_to_inactive_agent_rejected(self, api, agency_admin_headers):
        """PRD 3.2: "An agent claims a letter from the pile by assigning it,
        moving it from `RECEIVED` to `IN_REVIEW`; the payload's `agent_id` must
        reference an `ACTIVE` agent of the same agency, or the request fails
        with `ERR_AGENT_INACTIVE`."

        Design: Corner/validations/assign_query_to_inactive_agent_rejected
        """
        agency = create_agency(name="Agency AI")
        agent1 = create_agent(agency["id"], display_name="Agent One")
        agent2 = create_agent(agency["id"], display_name="Agent Two")
        validate_success(api.deactivate_agent(agent1["id"], agency_admin_headers), 200)
        author = create_author(agency["id"])
        query = intake_query(agent2["id"], author["id"], genre="FICTION", word_count=90000)

        resp = api.assign_query(
            query["id"], {"agent_id": agent1["id"]}, make_agent_headers(agent2["id"])
        )
        validate_error(resp, ApiErrorId.ERR_AGENT_INACTIVE.value)
        letter = validate_success(
            api.get_query_letter(query["id"], make_agent_headers(agent2["id"])), 200
        )
        assert letter["status"] == "RECEIVED"
