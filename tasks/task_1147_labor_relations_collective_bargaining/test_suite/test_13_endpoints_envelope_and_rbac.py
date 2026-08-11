"""Corner endpoint-shape, RBAC, cross-cutting complexity, and consistency tests."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_active_agreement,
    create_clause,
    create_draft_agreement,
    create_employer_proposal_on_table,
    create_interpreted_clause,
    create_ratification_vote_payload,
    create_reviewed_scenario,
    create_session,
    create_union,
    create_union_payload,
    get_agreement_version,
    get_success_data,
    make_union_representative_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["lr_admin_headers"]
MGR = TEST_USERS["lr_manager_headers"]
NEG1 = TEST_USERS["negotiator_headers"]
NEG2 = TEST_USERS["negotiator_2_headers"]
NEG3 = TEST_USERS["negotiator_3_headers"]
CHIEF = TEST_USERS["chief_negotiator_headers"]
LC = TEST_USERS["legal_counsel_headers"]


# ---------------------------------------------------------------------------
# Corner: endpoints / clause_list_pagination_and_fk_filter
# ---------------------------------------------------------------------------

def test_clause_list_pagination_and_fk_filter(api):
    """PRD §2.3: "`limit` specifies the maximum number of items to return and
    defaults to 10, with a minimum of 1 and a maximum of 100. `offset`
    specifies the number of items to skip and defaults to 0. A `limit` outside
    the range 1 to 100, or an `offset` below 0, is rejected with
    `ERR_PAGINATION_INVALID` (HTTP 400)." and "The `meta` object of a list
    response carries `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/clause_list_pagination_and_fk_filter
    """
    union = create_union(name="Union EA")
    a1 = create_draft_agreement(union["id"], title="CBA EA-1")
    a2 = create_draft_agreement(union["id"], title="CBA EA-2")
    create_clause(a1["id"], article_ref="12.1", title="First", body_text="x")
    create_clause(a1["id"], article_ref="12.2", title="Second", body_text="x")
    create_clause(a2["id"], article_ref="12.1", title="Other", body_text="x")

    page1, meta1 = validate_paginated(
        api.list_clauses(MGR, params={"agreement_id": a1["id"], "limit": 1, "offset": 0})
    )
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert len(page1) == 1

    page2, meta2 = validate_paginated(
        api.list_clauses(MGR, params={"agreement_id": a1["id"], "limit": 1, "offset": 1})
    )
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert len(page2) == 1

    resp = api.list_clauses(MGR, params={"agreement_id": a1["id"], "limit": 0})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID)


# ---------------------------------------------------------------------------
# Corner: endpoints / response_envelope_shapes
# ---------------------------------------------------------------------------

def test_response_envelope_shapes(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources." and error format: "the `error_id` is a
    unique, machine-readable string that identifies the specific error. The
    `message` provides a human-readable explanation of what went wrong."

    Design: Corner/endpoints/response_envelope_shapes
    """
    import requests
    import os

    base_url = os.environ.get("API_BASE_URL", "")
    union = create_union(name="Union EB")

    obj_resp = api.get_union(union["id"], ADMIN)
    obj_body = obj_resp.json()
    assert obj_body["response_type"] == "object"
    assert obj_body["meta"]["api_request_id"]
    assert obj_body["data"]["id"] == union["id"]

    list_resp = api.list_unions(ADMIN)
    list_body = list_resp.json()
    assert list_body["response_type"] == "array"
    assert "total_count" in list_body["meta"]

    err_resp = api.get_union(NON_EXISTENT_UUID, ADMIN)
    err_body = err_resp.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert err_body["data"]["message"]


# ---------------------------------------------------------------------------
# Corner: rbac / missing_auth_headers_return_401
# ---------------------------------------------------------------------------

def test_missing_auth_headers_return_401(api):
    """PRD §2.1: "A request whose headers are missing, blank, or carry an
    undeclared role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_return_401
    """
    resp = api.list_unions(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# ---------------------------------------------------------------------------
# Corner: rbac / negotiator_cannot_lock_scenario
# ---------------------------------------------------------------------------

def test_negotiator_cannot_lock_scenario(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4 endpoint table: "POST /labor-relations/costing-scenarios/{id}/lock
    ... ChiefNegotiator"

    Design: Corner/rbac/negotiator_cannot_lock_scenario
    """
    union = create_union(name="Union RA")
    agreement = create_draft_agreement(
        union["id"], title="CBA RA", headcount_baseline=100, fte_projected=120,
        avg_loaded_wage_cents=5000, costing_envelope_cents=1_000_000_000_000,
    )
    proposal = create_employer_proposal_on_table(
        agreement["id"], union["id"], title="Allowance",
        proposal_type="ECONOMIC", recurring_annual_cost_cents=100,
    )
    scenario = create_reviewed_scenario(
        agreement["id"], [proposal["id"]], name="rbac", scenario_mode="FINAL", term_years=3
    )
    a_v = get_agreement_version(agreement["id"])
    resp = api.lock_costing_scenario(
        scenario["id"], {"expected_agreement_version": a_v}, NEG3
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    after = get_success_data(api.get_costing_scenario(scenario["id"], NEG1))
    assert after["status"] == "REVIEWED"


# ---------------------------------------------------------------------------
# Corner: rbac / union_rep_cannot_create_clause
# ---------------------------------------------------------------------------

def test_union_rep_cannot_create_clause(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4 endpoint table: "POST /labor-relations/clauses ... LRManager"

    Design: Corner/rbac/union_rep_cannot_create_clause
    """
    union = create_union(name="Union RB")
    agreement = create_draft_agreement(union["id"], title="CBA RB")
    resp = api.create_clause(
        {"agreement_id": agreement["id"], "article_ref": "1.1", "title": "Recognition", "body_text": "x"},
        make_union_representative_headers(union["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


# ---------------------------------------------------------------------------
# Corner: rbac / lradmin_cannot_tally_vote
# ---------------------------------------------------------------------------

def test_lradmin_cannot_tally_vote(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the
    target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4 endpoint table: "POST /labor-relations/ratification-votes/{id}/tally
    ... UnionRepresentative"

    Design: Corner/rbac/lradmin_cannot_tally_vote
    """
    union = create_union(name="Union RC")
    agreement = create_draft_agreement(union["id"], title="CBA RC")
    vote = get_success_data(
        api.create_ratification_vote(
            create_ratification_vote_payload(
                agreement_id=agreement["id"], eligible_voter_count=10,
                ballot_close_at="2026-06-01T00:00:00Z",
            ),
            CHIEF,
        )
    )
    resp = api.tally_vote(vote["id"], {"votes_for": 5, "votes_against": 0}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


# ---------------------------------------------------------------------------
# Corner: rbac / lrmanager_cannot_record_interpretation
# ---------------------------------------------------------------------------

def test_lrmanager_cannot_record_interpretation(api):
    """PRD §3.2: "The per-action role gating is fixed: `LRManager` performs
    `OPEN_REVIEW`, `CLOSE_REVIEW`, and `DISPUTE`; `LegalCounsel` performs
    `RECORD` and `RESOLVE`; `UnionRepresentative` performs `DISPUTE` only — any
    other action-per-role combination is rejected with
    `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/lrmanager_cannot_record_interpretation
    """
    union = create_union(name="Union RD")
    agreement = create_draft_agreement(union["id"], title="CBA RD")
    clause = create_clause(agreement["id"], article_ref="3.4", title="Posting", body_text="x")
    get_success_data(api.interpret_clause(clause["id"], {"action": "OPEN_REVIEW"}, MGR))
    resp = api.interpret_clause(
        clause["id"], {"action": "RECORD", "interpretation_text": "Manager overreach"}, MGR
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    after = get_success_data(api.get_clause(clause["id"], MGR))
    assert after["interpretation_status"] == "UNDER_REVIEW"


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / agreement_extend_occ_stale_returns_412
# ---------------------------------------------------------------------------

def test_agreement_extend_occ_stale_returns_412(api):
    """PRD §2.7: "If the supplied value does not equal the agreement's current
    `version`, the request is rejected with `ERR_STALE_AGREEMENT_VERSION`
    (HTTP 412) and no state changes. ... and because extending legitimately
    re-extends an already `EXTENDED` agreement and also bumps `version`, a
    second lock or a second extend carrying the pre-mutation version is
    correctly identified as stale and is rejected deterministically."

    Design: Corner/cross_cutting_complexity_layers/agreement_extend_occ_stale_returns_412
    """
    union = create_union(name="Union LA")
    agreement = create_active_agreement(
        union["id"], title="CBA LA",
        effective_date="2026-01-01T00:00:00Z", expiration_date="2026-06-30T00:00:00Z",
        headcount_baseline=50, fte_projected=60, avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    a_v = get_agreement_version(agreement["id"])
    first = get_success_data(
        api.extend_agreement(
            agreement["id"],
            {"new_expiration_date": "2026-12-31T00:00:00Z", "expected_agreement_version": a_v},
            CHIEF,
        )
    )
    assert first["status"] == "EXTENDED"
    assert first["expiration_date"] == "2026-12-31T00:00:00Z"
    assert first["extension_count"] == 1
    resp = api.extend_agreement(
        agreement["id"],
        {"new_expiration_date": "2027-06-30T00:00:00Z", "expected_agreement_version": a_v},
        CHIEF,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_AGREEMENT_VERSION)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / extend_recomputes_task_due_dates
# ---------------------------------------------------------------------------

def test_extend_recomputes_task_due_dates(api):
    """PRD §3.12: "the cascade fires: every expiration task of this agreement
    in `PENDING` or `IN_PROGRESS` recomputes its `due_date` from the new
    `expiration_date` plus its `due_offset_days`, and any task whose recomputed
    `due_date` is strictly earlier than the current clock becomes `MISSED` in
    the same request."

    Design: Corner/cross_cutting_complexity_layers/extend_recomputes_task_due_dates
    """
    union = create_union(name="Union LB")
    agreement = create_active_agreement(
        union["id"], title="CBA LB",
        effective_date="2026-01-01T00:00:00Z", expiration_date="2026-05-31T00:00:00Z",
        headcount_baseline=50, fte_projected=60, avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    task = get_success_data(
        api.create_expiration_task(
            {
                "agreement_id": agreement["id"], "title": "Notice",
                "task_type": "NOTICE_DEADLINE", "due_offset_days": -60,
                "assignee_user_id": "mgr-1",
            },
            MGR,
        )
    )
    assert task["due_date"] == "2026-04-01T00:00:00Z"
    a_v = get_agreement_version(agreement["id"])
    extended = get_success_data(
        api.extend_agreement(
            agreement["id"],
            {"new_expiration_date": "2026-08-31T00:00:00Z", "expected_agreement_version": a_v},
            CHIEF,
        )
    )
    assert extended["extension_count"] == 1
    task_after = get_success_data(api.get_expiration_task(task["id"], MGR))
    assert task_after["due_date"] == "2026-07-02T00:00:00Z", (
        f"due_date must recompute from the new expiration; got {task_after['due_date']}"
    )
    assert task_after["status"] == "PENDING"
    agreement_after = get_success_data(api.get_agreement(agreement["id"], ADMIN))
    assert agreement_after["posture"] == "SUNSET", "122 days left at default clock -> SUNSET"


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / clock_sweep_is_checkpoint_driven
# ---------------------------------------------------------------------------

def test_clock_sweep_is_checkpoint_driven(api):
    """PRD §2.12: "At startup, before any administrator call, the clock reads
    exactly 2026-05-01T00:00:00Z; it never falls back to wall-clock time." and
    "Advancing the clock is an administrator-only capability invoked with a
    `to_iso8601` payload that runs an epoch sweep in a pinned order. ...
    Step 2: sessions still `SCHEDULED` whose `end_at` is strictly earlier than
    the new clock become `NO_SHOW`"

    Design: Corner/cross_cutting_complexity_layers/clock_sweep_is_checkpoint_driven
    """
    union = create_union(name="Union LC")
    agreement = create_draft_agreement(union["id"], title="CBA LC")
    session = create_session(
        agreement["id"], mediator_id="med-z", lead_negotiator_id="ln-z",
        location="Room 1", start_at="2026-04-30T10:00:00Z", end_at="2026-04-30T11:00:00Z",
    )
    before = get_success_data(api.get_session(session["id"], NEG1))
    assert before["status"] == "SCHEDULED", (
        "no sweep runs without a clock-set call even though end_at precedes the default clock"
    )
    clock_resp = get_success_data(api.set_clock("2026-05-01T00:00:00Z", ADMIN))
    assert clock_resp["current_utc"] == "2026-05-01T00:00:00Z"
    after = get_success_data(api.get_session(session["id"], NEG1))
    assert after["status"] == "NO_SHOW"


# ---------------------------------------------------------------------------
# Corner: consistency_model / immediate_consistency_read_after_write
# ---------------------------------------------------------------------------

def test_immediate_consistency_read_after_write(api):
    """PRD §3.1: "The new union is born in `ACTIVE` status with
    `open_information_request_count` initialized to 0."
    PRD §2.10: "Any state transition or cross-entity cascade that touches an
    entity refreshes that entity's `updated_at` and increments its `version`"

    Design: Corner/consistency_model/immediate_consistency_read_after_write
    """
    union = get_success_data(
        api.create_union(create_union_payload(name="Union IM", union_code="UIM-1"), ADMIN)
    )
    fetched = get_success_data(api.get_union(union["id"], LC))
    assert fetched["name"] == "Union IM"
    assert fetched["union_code"] == "UIM-1"
    assert fetched["status"] == "ACTIVE"
    assert fetched["open_information_request_count"] == 0
