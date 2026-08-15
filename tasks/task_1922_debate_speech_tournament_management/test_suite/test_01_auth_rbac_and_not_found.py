"""Authentication, role/ownership gates, and per-resource 404 behaviour."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_division,
    add_entry,
    add_school,
    create_round_payload,
    create_tournament,
    make_coach_headers,
    open_registration,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
TAB = TEST_USERS["tabstaff_headers"]


class TestAuthHeaders:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role value
        outside this set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        tournament = create_tournament(name="AH")
        resp = api.get_tournament(tournament["id"], {})
        validate_error(resp, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


class TestRoleAndOwnershipGates:
    def test_round_create_as_coach_forbidden(self, api):
        """PRD §2.1: "Once authenticated, a request whose role is not in the
        target endpoint's authorized role list is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §4: "POST | `/rounds` | Create a round (`SCHEDULED`) | TabStaff".

        Design: Corner/validations/tabstaff_action_as_coach_forbidden
        """
        tournament = create_tournament(name="FB")
        division = add_division(tournament["id"])
        school = add_school(tournament["id"], name="Alpha")
        resp = api.create_round(
            create_round_payload(division["id"], round_number=1, kind="PRELIM"),
            make_coach_headers(school["id"]))
        validate_error(resp, "ERR_FORBIDDEN")

    def test_cross_school_entry_confirm_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `SchoolCoach`, `X-User-ID` is the `id`
        of the acting `School`; ownership checks on any resource that references a
        school compare the resource's school foreign-key field to `X-User-ID`, and
        a mismatch is rejected with `ERR_RESOURCE_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/validations/cross_school_entry_confirm_forbidden
        """
        tournament = create_tournament(name="OW")
        division = add_division(tournament["id"])
        alpha = add_school(tournament["id"], name="Alpha")
        beta = add_school(tournament["id"], name="Beta")
        open_registration(tournament["id"])
        entry = add_entry(beta["id"], division["id"], "B-One")

        resp = api.confirm_entry(entry["id"], make_coach_headers(alpha["id"]))
        validate_error(resp, "ERR_RESOURCE_OWNERSHIP_MISMATCH")

        fetched = validate_success(api.get_entry(entry["id"], DIRECTOR))
        assert fetched["status"] == "REGISTERED", (
            "A cross-school confirm must not mutate the entry")

    def test_tabstaff_cannot_publish_results(self, api):
        """PRD §2.1: "`TabStaff` owns rounds, pairing generation, room and judge
        assignment, ballot verification and voiding, and break determination, but
        cannot drive tournament phases or publish results."
        PRD §2.1: "a request whose role is not in the target endpoint's authorized
        role list is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/tabstaff_cannot_publish_results_forbidden
        """
        tournament = create_tournament(name="RB")
        resp = api.publish_results(tournament["id"], TAB)
        validate_error(resp, "ERR_FORBIDDEN")

    def test_coach_shared_read_allowed(self, api):
        """PRD §4: "GET | `/tournaments` | List tournaments | Any authenticated role".
        PRD §4: "GET | `/schools/{id}` | Get a school with computed obligation and
        invoice fields | Any authenticated role".

        Design: Corner/rbac/coach_shared_read_allowed
        """
        tournament = create_tournament(name="CR")
        school = add_school(tournament["id"], name="Alpha")
        coach = make_coach_headers(school["id"])

        list_resp = api.list_tournaments(coach)
        validate_success(list_resp, 200)
        assert list_resp.json()["response_type"] == "array"

        get_resp = api.get_school(school["id"], coach)
        validate_success(get_resp, 200)
        assert get_resp.json()["response_type"] == "object"


class TestResourceNotFound:
    """Each read of an unknown id yields that resource's 404 error id."""

    @pytest.fixture
    def tournament(self, api):
        return create_tournament(name="X")

    def test_tournament_not_found(self, api, tournament):
        """PRD §2.7: "the first missing identifier produces its resource-specific
        not-found error: `ERR_TOURNAMENT_NOT_FOUND`, `ERR_SCHOOL_NOT_FOUND`,
        `ERR_DIVISION_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, ... each at HTTP 404."

        Design: Corner/entities/tournament_not_found_returns_404
        """
        resp = api.get_tournament(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, "ERR_TOURNAMENT_NOT_FOUND")

    def test_school_not_found(self, api, tournament):
        """PRD §2.7: "the first missing identifier produces its resource-specific
        not-found error: `ERR_TOURNAMENT_NOT_FOUND`, `ERR_SCHOOL_NOT_FOUND`,
        `ERR_DIVISION_NOT_FOUND`, ... each at HTTP 404."

        Design: Corner/entities/school_not_found_returns_404
        """
        resp = api.get_school(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, "ERR_SCHOOL_NOT_FOUND")

    def test_division_not_found(self, api, tournament):
        """PRD §2.7: "the first missing identifier produces its resource-specific
        not-found error: ... `ERR_DIVISION_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`,
        `ERR_JUDGE_NOT_FOUND`, ... each at HTTP 404."

        Design: Corner/entities/division_not_found_returns_404
        """
        resp = api.get_division(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, "ERR_DIVISION_NOT_FOUND")

    def test_entry_not_found(self, api, tournament):
        """PRD §2.7: "the first missing identifier produces its resource-specific
        not-found error: ... `ERR_ENTRY_NOT_FOUND`, `ERR_JUDGE_NOT_FOUND`,
        `ERR_JUDGE_CONFLICT_NOT_FOUND`, ... each at HTTP 404."

        Design: Corner/entities/entry_not_found_returns_404
        """
        resp = api.get_entry(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, "ERR_ENTRY_NOT_FOUND")

    def test_judge_not_found(self, api, tournament):
        """PRD §2.7: "the first missing identifier produces its resource-specific
        not-found error: ... `ERR_ENTRY_NOT_FOUND`, `ERR_JUDGE_NOT_FOUND`,
        `ERR_JUDGE_CONFLICT_NOT_FOUND`, ... each at HTTP 404."

        Design: Corner/entities/judge_not_found_returns_404
        """
        resp = api.get_judge(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, "ERR_JUDGE_NOT_FOUND")

    def test_judge_conflict_not_found(self, api, tournament):
        """PRD §2.7: "the first missing identifier produces its resource-specific
        not-found error: ... `ERR_JUDGE_NOT_FOUND`, `ERR_JUDGE_CONFLICT_NOT_FOUND`,
        `ERR_ROOM_NOT_FOUND`, ... each at HTTP 404."

        Design: Corner/entities/judge_conflict_not_found_returns_404
        """
        resp = api.get_judge_conflict(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, "ERR_JUDGE_CONFLICT_NOT_FOUND")

    def test_room_not_found(self, api, tournament):
        """PRD §2.7: "the first missing identifier produces its resource-specific
        not-found error: ... `ERR_JUDGE_CONFLICT_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`,
        `ERR_ROUND_NOT_FOUND`, ... each at HTTP 404."

        Design: Corner/entities/room_not_found_returns_404
        """
        resp = api.get_room(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, "ERR_ROOM_NOT_FOUND")

    def test_round_not_found(self, api, tournament):
        """PRD §2.7: "the first missing identifier produces its resource-specific
        not-found error: ... `ERR_ROOM_NOT_FOUND`, `ERR_ROUND_NOT_FOUND`,
        `ERR_PAIRING_NOT_FOUND`, ... each at HTTP 404."

        Design: Corner/entities/round_not_found_returns_404
        """
        resp = api.get_round(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, "ERR_ROUND_NOT_FOUND")

    def test_pairing_not_found(self, api, tournament):
        """PRD §2.7: "the first missing identifier produces its resource-specific
        not-found error: ... `ERR_ROUND_NOT_FOUND`, `ERR_PAIRING_NOT_FOUND`,
        `ERR_PAIRING_ENTRY_NOT_FOUND`, ... each at HTTP 404."

        Design: Corner/entities/pairing_not_found_returns_404
        """
        resp = api.get_pairing(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, "ERR_PAIRING_NOT_FOUND")

    def test_pairing_entry_not_found(self, api, tournament):
        """PRD §2.7: "the first missing identifier produces its resource-specific
        not-found error: ... `ERR_PAIRING_NOT_FOUND`, `ERR_PAIRING_ENTRY_NOT_FOUND`,
        `ERR_BALLOT_NOT_FOUND`, ... each at HTTP 404."

        Design: Corner/entities/pairing_entry_not_found_returns_404
        """
        resp = api.get_pairing_entry(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, "ERR_PAIRING_ENTRY_NOT_FOUND")

    def test_ballot_not_found(self, api, tournament):
        """PRD §2.7: "the first missing identifier produces its resource-specific
        not-found error: ... `ERR_PAIRING_ENTRY_NOT_FOUND`, `ERR_BALLOT_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, ... each at HTTP 404."

        Design: Corner/entities/ballot_not_found_returns_404
        """
        resp = api.get_ballot(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, "ERR_BALLOT_NOT_FOUND")

    def test_contract_not_found(self, api, tournament):
        """PRD §2.7: "the first missing identifier produces its resource-specific
        not-found error: ... `ERR_BALLOT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, or
        `ERR_ORDER_NOT_FOUND`, each at HTTP 404."

        Design: Corner/entities/contract_not_found_returns_404
        """
        resp = api.get_contract(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, "ERR_CONTRACT_NOT_FOUND")

    def test_order_not_found(self, api, tournament):
        """PRD §2.7: "the first missing identifier produces its resource-specific
        not-found error: ... `ERR_BALLOT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, or
        `ERR_ORDER_NOT_FOUND`, each at HTTP 404."

        Design: Corner/entities/order_not_found_returns_404
        """
        resp = api.get_order(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, "ERR_ORDER_NOT_FOUND")
