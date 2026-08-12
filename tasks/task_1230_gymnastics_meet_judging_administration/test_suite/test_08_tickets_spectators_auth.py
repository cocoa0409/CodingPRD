"""Spectator admission (ticket issuance guards), RBAC denials at the gate,
authentication, and the public live-scoring read model."""
from test_helpers import (
    ApiErrorId,
    add_published_score,
    build_user_headers,
    create_score_payload,
    get_success_data,
    issue_ticket,
    make_judge_panel_chief_headers,
    open_rotation,
    setup_competition_ready,
    setup_meet_with_session,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

DIRECTOR = TEST_USERS["meet_director_headers"]
GATE = TEST_USERS["gate_attendant_headers"]
SPECTATOR = TEST_USERS["spectator_headers"]


class TestTicketIssuance:
    def test_duplicate_holder_email_rejected(self, api, meet_director_headers):
        """PRD §3.9: "The holder email must be unique within the session among tickets
        whose `ticket_state` is not `VOID`; a duplicate is rejected with
        `ERR_TICKET_DUPLICATE_EMAIL` (HTTP 409)."

        Design: Corner/validations/ticket_duplicate_email_rejected
        """
        ctx = setup_meet_with_session()
        meet_id, session_id = ctx["meet"]["id"], ctx["session"]["id"]
        first = api.issue_ticket(meet_id, session_id, {
            "holder_name": "A", "holder_email": "a@x.com",
            "ticket_class": "GENERAL_ADMISSION", "price_cents": 2500},
            meet_director_headers)
        validate_success(first, 201)
        duplicate = api.issue_ticket(meet_id, session_id, {
            "holder_name": "A Two", "holder_email": "a@x.com",
            "ticket_class": "GENERAL_ADMISSION", "price_cents": 2500},
            meet_director_headers)
        validate_error(duplicate, ApiErrorId.ERR_TICKET_DUPLICATE_EMAIL)

    def test_comp_ticket_must_be_free(self, api, meet_director_headers):
        """PRD §3.9: "The price must agree with the class: a `COMP` ticket must carry a
        `price_cents` of exactly 0 and every other class a positive price; a mismatch is
        rejected with `ERR_TICKET_PRICE_MISMATCH`."

        Design: Corner/validations/ticket_comp_price_must_be_zero
        """
        ctx = setup_meet_with_session()
        meet_id, session_id = ctx["meet"]["id"], ctx["session"]["id"]
        bad = api.issue_ticket(meet_id, session_id, {
            "holder_name": "X", "holder_email": "x@x.com",
            "ticket_class": "COMP", "price_cents": 2500}, meet_director_headers)
        validate_error(bad, ApiErrorId.ERR_TICKET_PRICE_MISMATCH)
        good = api.issue_ticket(meet_id, session_id, {
            "holder_name": "X", "holder_email": "x@x.com",
            "ticket_class": "COMP", "price_cents": 0}, meet_director_headers)
        ticket = validate_success(good, 201)
        assert ticket["ticket_class"] == "COMP"
        assert ticket["price_cents"] == 0


class TestGateRbac:
    def test_gate_attendant_cannot_void_ticket(self, api, meet_director_headers,
                                               gate_attendant_headers):
        """PRD §2.1: "Once authenticated, the acting role must be permitted to invoke the
        target endpoint; otherwise the request is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."
        PRD §4: `POST /api/v1/spectator-tickets/{id}/void` is authorized for MeetDirector
        only; the GateAttendant's ticket authority is selling, scanning, and redeeming
        ("`GateAttendant` — gate staff; sells tickets (shared with the meet director), and
        scans and redeems spectator tickets." §2.1).

        Design: Corner/rbac/gate_attendant_cannot_void_ticket
        """
        ctx = setup_meet_with_session()
        ticket = issue_ticket(ctx["meet"]["id"], ctx["session"]["id"])
        assert ticket["ticket_state"] == "ISSUED"
        res = api.void_ticket(ticket["id"], gate_attendant_headers)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        after = get_success_data(api.get_ticket(ticket["id"], meet_director_headers))
        assert after["ticket_state"] == "ISSUED", "denied void must not transition"


class TestAuthentication:
    def test_missing_or_malformed_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying
        the acting user, and `X-User-Role`, declaring the operational capacity in which they
        act. A request with missing or malformed headers, or whose `X-User-Role` value is
        not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_headers
        """
        # No headers at all.
        validate_error(api.list_meets(None), ApiErrorId.ERR_UNAUTHENTICATED)
        # A role string that is not one of the six declared roles.
        validate_error(api.list_meets(build_user_headers("someone", "NotARole")),
                       ApiErrorId.ERR_UNAUTHENTICATED)


class TestLiveScores:
    def test_spectator_reads_live_scores(self, api, spectator_headers):
        """PRD §3.9: "Throughout the meet, a public live scoring read model exposes each
        session's current state of play: every score in `PUBLISHED` or `FINAL`, the rotation
        currently in progress, and the running leaderboard. It is a read model only — score
        publication refreshes it, and it is the surface a `Spectator` watches — with no
        write path of its own."
        PRD §4: `GET /api/v1/sessions/{id}/live-scores` is authorized for MeetDirector,
        MeetReferee, JudgePanelChief, Coach, Spectator.

        Design: Corner/rbac/spectator_read_get_live_scores
        """
        ctx = setup_meet_with_session()
        res = api.list_live_scores(ctx["session"]["id"], spectator_headers)
        data = validate_success(res)
        assert res.json()["response_type"] == "array"
        assert isinstance(data, list)

    def test_live_scores_excludes_draft_includes_published(self, api, spectator_headers):
        """PRD §3.9: "Throughout the meet, a public live scoring read model exposes each
        session's current state of play: every score in `PUBLISHED` or `FINAL`, the rotation
        currently in progress, and the running leaderboard."

        Design: Corner/endpoints/live_scores_computed_read
        """
        ctx = setup_competition_ready(num_athletes=1)
        rotation = ctx["rotations"][0]
        open_rotation(rotation["id"])
        published = add_published_score(ctx, ctx["entries"][0], rotation, 5.0, 8.0, 0.0)
        # A second score on the next rotation, left in DRAFT.
        draft = get_success_data(api.create_score(
            ctx["entries"][0]["id"],
            create_score_payload(ctx["rotations"][1]["id"], "UNEVEN_BARS", 4.0, 7.5),
            make_judge_panel_chief_headers(ctx["chiefs"]["UNEVEN_BARS"])))
        assert draft["score_state"] == "DRAFT"
        data = validate_success(api.list_live_scores(ctx["session"]["id"], spectator_headers))
        visible_ids = {item["id"] for item in data}
        assert published["id"] in visible_ids, "PUBLISHED scores must appear on live display"
        assert draft["id"] not in visible_ids, (
            "DRAFT scores are neither PUBLISHED nor FINAL and must not appear")
