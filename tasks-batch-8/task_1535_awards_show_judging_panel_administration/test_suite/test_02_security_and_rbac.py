"""Authentication, authorization, ownership scoping, and duty segregation
(PRD §2.1, §2.5, §3.5).
"""
from test_helpers import (
    ApiErrorId,
    make_entrant_headers,
    make_judge_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
ANON = TEST_USERS["anonymous_headers"]


class TestAuthentication:
    def test_missing_headers_unauthenticated(self, api):
        """PRD §2.1: "Missing or empty headers are rejected with
        `ERR_UNAUTHENTICATED` (401) on every endpoint except the clock-setting
        capability described in §2.6."

        Design: Corner/validations/unauthenticated_request_rejected
        """
        resp = api.list_seasons({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenials:
    def test_entrant_cannot_publish_category(self, api):
        """PRD §2.1: "A role attempting an operation outside its grant in §4 is
        rejected with `ERR_FORBIDDEN_ROLE` (403)."
        PRD §4: category publish is granted to ProgramAdmin only.

        Design: Corner/validations/forbidden_role_denied
        """
        season = fx.create_season("GALA-RB1")
        category = fx.create_category(season["id"], code="CAT-RB1")
        entrant = fx.register_entrant("e1@x.com", "Entrant 1")
        resp = api.publish_category(category["id"], make_entrant_headers(entrant["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        fetched = validate_success(api.get_category(category["id"], ADMIN))
        assert fetched["status"] == "DRAFT"

    def test_judge_cannot_lock_panel(self, api):
        """PRD §2.1: "A role attempting an operation outside its grant in §4 is
        rejected with `ERR_FORBIDDEN_ROLE` (403)."
        PRD §4: "POST | `/awards/scoring-rounds/{id}/lock-panel` | Lock panel
        (`CONFIGURING` → `PANEL_LOCKED`) | ProgramAdmin".

        Design: Corner/rbac/judge_cannot_lock_panel
        """
        bundle = fx.setup_season_closed_with_eligible_entries(
            num_entries=1, code="GALA-RB2"
        )
        judges = fx.create_active_judges(3)
        payload = {
            "round_index": 1,
            "scoring_mode": "RAW_RANK",
            "scheduled_window_start": "2026-09-05T00:00:00Z",
            "scheduled_window_end": "2026-09-07T00:00:00Z",
            "advance_count": 1,
        }
        round_ = fx.get_success_data(
            api.create_round(bundle["category"]["id"], payload, ADMIN)
        )
        for position, judge in enumerate(judges):
            role = "CHAIR" if position == 0 else "MEMBER"
            assignment = fx.propose_assignment(round_["id"], judge["id"], role)
            fx.confirm_assignment(assignment["id"], judge["id"])
        resp = api.lock_panel(round_["id"], make_judge_headers(judges[0]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        fetched = validate_success(api.get_round(round_["id"], ADMIN))
        assert fetched["status"] == "CONFIGURING"

    def test_entrant_cannot_list_other_entrants_entries(self, api):
        """PRD §2.1: "When `X-User-Role` is `Entrant`, `X-User-ID` is the `id` of
        the acting `Entrant`; ownership checks on any resource that references
        an `Entrant` — an entry's `entrant_id`, an appeal's `filed_by_entrant_id`,
        a finalist record's owning entrant — compare the resource's foreign-key
        field to `X-User-ID`."
        PRD §2.1: "A role attempting an operation outside its grant in §4 is
        rejected with `ERR_FORBIDDEN_ROLE` (403)."

        Design: Corner/rbac/entrant_cannot_read_other_entrant_entry_via_ownership
        """
        season, category = fx.setup_open_season_with_category("GALA-RB3")
        ent1 = fx.register_entrant("e1@x.com", "Entrant 1")
        ent2 = fx.register_entrant("e2@x.com", "Entrant 2")
        fx.create_draft_entry(category["id"], ent1["id"], title="Work 1")
        fx.create_draft_entry(category["id"], ent2["id"], title="Work 2")
        resp = api.list_entrant_entries(ent1["id"], make_entrant_headers(ent2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_auditor_cannot_open_season(self, api):
        """PRD §2.1: "A role attempting an operation outside its grant in §4 is
        rejected with `ERR_FORBIDDEN_ROLE` (403)."
        PRD §4: "POST | `/awards/seasons/{id}/open` | Open a season (`DRAFT` →
        `OPEN`) | ProgramAdmin".

        Design: Corner/rbac/auditor_cannot_open_season
        """
        season = fx.create_season("GALA-RB5")
        fx.create_published_category(season["id"], code="CAT-RB5")
        fx.set_clock("2026-08-10T00:00:00Z")
        resp = api.open_season(season["id"], AUDITOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        fetched = validate_success(api.get_season(season["id"], ADMIN))
        assert fetched["status"] == "DRAFT"

    def test_anonymous_can_list_seasons(self, api):
        """PRD §4: "GET | `/awards/seasons` | List seasons | ProgramAdmin,
        Auditor, Entrant, Judge, FulfillmentVendor, Anonymous".

        Design: Corner/rbac/anonymous_can_read_public_season
        """
        fx.create_season("GALA-RB4")
        resp = api.list_seasons(ANON)
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert data[0]["code"] == "GALA-RB4"


class TestSegregationOfDuties:
    def test_judge_cannot_confirm_other_judges_assignment(self, api):
        """PRD §3.5: "Confirmation is personal: the acting judge must be the
        assignee (a mismatch is `ERR_SEGREGATION_OF_DUTIES`)"

        Design: Corner/rbac/segregation_of_duties_self_confirm_blocked
        """
        bundle = fx.setup_season_closed_with_eligible_entries(
            num_entries=1, code="GALA-SOD"
        )
        j1 = fx.create_active_judge("j1@x.com", "Judge 1")
        j2 = fx.create_active_judge("j2@x.com", "Judge 2")
        payload = {
            "round_index": 1,
            "scoring_mode": "RAW_RANK",
            "scheduled_window_start": "2026-09-05T00:00:00Z",
            "scheduled_window_end": "2026-09-07T00:00:00Z",
            "advance_count": 1,
        }
        round_ = fx.get_success_data(
            api.create_round(bundle["category"]["id"], payload, ADMIN)
        )
        assignment = fx.propose_assignment(round_["id"], j1["id"], "CHAIR")
        resp = api.confirm_assignment(assignment["id"], make_judge_headers(j2["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        fetched = validate_success(
            api.list_round_assignments(round_["id"], ADMIN)
        )
        assert fetched[0]["status"] == "PROPOSED"
