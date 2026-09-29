"""
The bottom of the validation ladder: unknown identifiers in the path, unknown
identifiers in the body, and bodies whose shape the specification refuses. Every
refusal here must leave the store exactly as it was.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import API_PREFIX
from test_helpers.test_users import make_member_headers

# One well-formed but unknown identifier per collection, on an empty store.
UNKNOWN_ROWS = [
    ("participants", "99999999-9999-9999-9999-999999999901", "ERR_PARTICIPANT_NOT_FOUND"),
    ("memberships", "99999999-9999-9999-9999-999999999902", "ERR_MEMBERSHIP_NOT_FOUND"),
    ("ballots", "99999999-9999-9999-9999-999999999903", "ERR_BALLOT_NOT_FOUND"),
    ("votes", "99999999-9999-9999-9999-999999999904", "ERR_VOTE_NOT_FOUND"),
    ("comments", "99999999-9999-9999-9999-999999999905", "ERR_COMMENT_NOT_FOUND"),
    (
        "public-reviews",
        "99999999-9999-9999-9999-999999999906",
        "ERR_PUBLIC_REVIEW_NOT_FOUND",
    ),
    (
        "patent-disclosures",
        "99999999-9999-9999-9999-999999999907",
        "ERR_PATENT_DISCLOSURE_NOT_FOUND",
    ),
    ("appeals", "99999999-9999-9999-9999-999999999908", "ERR_APPEAL_NOT_FOUND"),
    (
        "maintenance-items",
        "99999999-9999-9999-9999-999999999909",
        "ERR_MAINTENANCE_ITEM_NOT_FOUND",
    ),
]


class TestUnknownPathIdentifiers:
    """Each collection answers with its own existence code, never a generic one."""

    def test_every_collection_reports_its_own_not_found_code(self, api, staff_headers):
        """
        The applicable error is the one for the missing type:
        `ERR_PARTICIPANT_NOT_FOUND`, `ERR_COMMITTEE_NOT_FOUND`,
        `ERR_MEMBERSHIP_NOT_FOUND`, `ERR_WORK_ITEM_NOT_FOUND`, `ERR_DRAFT_NOT_FOUND`,
        `ERR_BALLOT_NOT_FOUND`, `ERR_VOTE_NOT_FOUND`, `ERR_COMMENT_NOT_FOUND`,
        `ERR_PUBLIC_REVIEW_NOT_FOUND`, `ERR_PATENT_DISCLOSURE_NOT_FOUND`,
        `ERR_APPEAL_NOT_FOUND` or `ERR_MAINTENANCE_ITEM_NOT_FOUND`, each HTTP 404.

        Design: Corner/errors/every_remaining_existence_code_is_triggerable_from_an_empty_database_not_found
        """
        for collection, unknown_id, error_id in UNKNOWN_ROWS:
            response = api.call(
                "GET",
                f"{API_PREFIX}/{collection}/{unknown_id}",
                headers=staff_headers,
            )
            error = validate_error(response, error_id, 404)
            assert error["message"], (
                f"the {collection} refusal carries no message: {error}"
            )

    def test_unknown_work_item_id_reports_the_work_item_code(self, api, staff_headers):
        """
        Every identifier templated into the path resolves to a stored row, checked left
        to right in the order the segments appear.

        Design: Corner/entities/work_item_retrieval_with_an_unknown_id_returns_work_item_not_found
        """
        response = api.get_work_item(
            "99999999-9999-9999-9999-999999999910", staff_headers
        )
        error = validate_error(response, "ERR_WORK_ITEM_NOT_FOUND", 404)
        assert error["message"], f"the refusal carries no message: {error}"

        _, meta = validate_paginated(api.list_work_items(staff_headers))
        a.assert_total_count(meta, 0)

    def test_appointment_to_an_unknown_committee_reports_the_committee_code(
        self, api, staff_headers
    ):
        """
        Appointing a member to an unknown committee returns `ERR_COMMITTEE_NOT_FOUND`
        before any body field is examined.

        Design: Corner/entities/membership_creation_on_an_unknown_committee_returns_committee_not_found
        """
        scenario = fx.Scenario(api)
        scenario.register("p1")

        response = api.create_membership(
            "99999999-9999-9999-9999-999999999911",
            f.membership_payload(scenario.pid("p1")),
            staff_headers,
        )
        validate_error(response, "ERR_COMMITTEE_NOT_FOUND", 404)

        _, meta = validate_paginated(api.list_memberships(staff_headers))
        a.assert_total_count(meta, 0)
        _, committee_meta = validate_paginated(api.list_committees(staff_headers))
        a.assert_total_count(committee_meta, 0)


class TestUnknownBodyIdentifiers:
    """Body foreign keys resolve in the order the target resource declares them."""

    def test_ballot_on_an_unknown_draft_reports_the_draft_code(self, api):
        """
        Opening a ballot on an unknown `draft_id` returns `ERR_DRAFT_NOT_FOUND`;
        approving a scope with an unknown `sponsoring_committee_id` returns
        `ERR_COMMITTEE_NOT_FOUND`. All HTTP 404.

        Design: Corner/entities/ballot_creation_with_an_unknown_draft_id_returns_draft_not_found
        """
        scenario = fx.work_item_in_development(api)

        response = api.create_ballot(
            f.ballot_payload(
                "99999999-9999-9999-9999-999999999912", scenario.committee_id
            ),
            scenario.chair,
        )
        validate_error(response, "ERR_DRAFT_NOT_FOUND", 404)

        _, meta = validate_paginated(api.list_ballots(scenario.staff))
        a.assert_total_count(meta, 0)
        assert scenario.get_committee()["open_ballot_count"] == 0, (
            "the refused ballot never touched the committee's counter"
        )

    def test_unknown_appellant_is_reported_before_the_unknown_cited_ballot(self, api):
        """
        Every foreign identifier in the body resolves to a stored row, checked in the
        order the fields are declared for the target resource.

        Design: Corner/errors/an_unknown_body_foreign_key_is_reported_in_field_declaration_order_not_found
        """
        scenario = fx.work_item_with_draft(api)
        stranger_id = "88888888-8888-8888-8888-888888888801"
        unknown_ballot_id = "88888888-8888-8888-8888-888888888802"

        both_unknown = api.create_appeal(
            f.appeal_payload(
                scenario.work_item_id,
                stranger_id,
                grounds="BALANCE_VIOLATION",
                statement="The roster is packed by one employer",
                cited_ballot_id=unknown_ballot_id,
            ),
            make_member_headers(stranger_id),
        )
        validate_error(both_unknown, "ERR_PARTICIPANT_NOT_FOUND", 404)

        appellant_known = api.create_appeal(
            f.appeal_payload(
                scenario.work_item_id,
                scenario.pid("p2"),
                grounds="BALANCE_VIOLATION",
                statement="The roster is packed by one employer",
                cited_ballot_id=unknown_ballot_id,
            ),
            scenario.member("p2"),
        )
        validate_error(appellant_known, "ERR_BALLOT_NOT_FOUND", 404)

        _, meta = validate_paginated(api.list_appeals(scenario.staff))
        a.assert_total_count(meta, 0)
        assert scenario.get_work_item()["consensus_gate"] == "OPEN", (
            "neither refused filing shut the procedural gate"
        )


class TestRequestShapeRefusals:
    """A required field absent, an enum outside its declaration, a bound crossed."""

    def test_committee_creation_without_a_designation_is_refused(self, api, staff_headers):
        """
        A technical committee is created by the secretariat with a `designation` such as
        TC-14 (a non-blank string of 1 to 32 characters), a `scope_text` statement of 1
        to 600 non-blank characters, a `chair_participant_id` naming the presiding
        chair, and optionally `max_concurrent_ballots`, an integer of at least 1 that
        defaults to 2 and caps how many of the committee's ballot windows may overlap.

        Design: Corner/entities/committee_creation_missing_required_designation_returns_invalid_request
        """
        scenario = fx.Scenario(api)
        scenario.register("p1")

        response = api.create_committee(
            f.committee_payload(scenario.pid("p1"), designation=None),
            staff_headers,
        )
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        _, meta = validate_paginated(api.list_committees(staff_headers))
        a.assert_total_count(meta, 0)
        _, participants = validate_paginated(api.list_participants(staff_headers))
        a.assert_total_count(participants, 1)

    def test_participant_creation_with_an_undeclared_category_is_refused(
        self, api, staff_headers
    ):
        """
        Required fields present; enum fields carrying a declared member; integer fields
        non-negative integers; date fields parsing as ISO 8601 calendar dates and
        datetime fields as ISO 8601 UTC instants; text fields that must be non-empty
        being non-empty after trimming.

        Design: Corner/entities/participant_creation_with_an_undeclared_interest_category_is_rejected
        """
        response = api.create_participant(
            f.participant_payload(
                full_name="Dana Distributor",
                organization="Wholesale Fasteners",
                interest_category="DISTRIBUTOR",
                employer_affiliation_code="WHOLE",
            ),
            staff_headers,
        )
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        _, meta = validate_paginated(api.list_participants(staff_headers))
        a.assert_total_count(meta, 0)

    def test_draft_changing_more_clauses_than_it_has_is_refused(self, api):
        """
        The body carries `total_clause_count` (an integer of at least 1), optionally
        `changed_clause_count` (an integer that defaults to 0, may not be negative and
        may not exceed `total_clause_count`), optionally `prior_draft_id` naming the
        revision this one supersedes, and optionally a `summary` written by the editor.

        Design: Corner/entities/draft_creation_with_changed_clause_count_above_total_is_rejected
        """
        scenario = fx.work_item_in_development(api)
        before = scenario.get_work_item()

        response = api.create_draft(
            scenario.work_item_id,
            f.draft_payload(total_clause_count=40, changed_clause_count=41),
            scenario.chair,
        )
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        _, meta = validate_paginated(api.list_drafts(scenario.staff))
        a.assert_total_count(meta, 0)
        after = scenario.get_work_item()
        assert after["progress_status"] == "IN_DEVELOPMENT", (
            "the refused draft left the work item in development, got "
            f"{after['progress_status']}"
        )
        a.assert_version_unchanged(before, after)
