"""Who may call, and on whose row.

The header pair is checked before any lookup, permission is granted per endpoint
rather than per entity, and the two identity-bound roles are matched against the
row they are acting on.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers.assertions import assert_status
from test_helpers.factories import (
    agreement_payload,
    batch_payload,
    client_payload,
    execute_payload,
    protocol_decision_payload,
    reviewer_payload,
)
from test_helpers.fixtures import REVIEWER_ADA, REVIEWER_BEN
from test_helpers.test_users import (
    ENGAGEMENT_MANAGER,
    QC_LEAD,
    STAFFING_COORDINATOR,
    make_client_counsel_headers,
    make_reviewer_headers,
    raw_headers,
)


class TestMissingAndUnknownRoleHeadersRejected:
    """Two header defects, two different answers, neither reaching a row."""

    def test_omitted_headers_and_an_undeclared_role_are_separate_refusals(
        self, matter_in_intake
    ):
        """PRD §2.1: "If either header is absent or blank, the request is rejected with
        `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before anything else is examined."

        The clock endpoint took no headers at all in the arrangement, and it is the only
        call in the interface that may.

        Design: Corner/rbac/missing_and_unknown_role_headers_rejected
        """
        ladder = matter_in_intake["ladder"]
        matter_id = matter_in_intake["matter_id"]

        missing = validate_error(
            ladder.api.get_matter(matter_id, raw_headers()),
            e.ERR_MISSING_AUTH_HEADERS,
            401,
        )
        unknown = validate_error(
            ladder.api.get_matter(
                matter_id, raw_headers("partner-0001", "MatterPartner")
            ),
            e.ERR_UNKNOWN_ROLE,
            401,
        )
        for body in (missing, unknown):
            assert "status" not in body
            assert "document_count" not in body

        assert ladder.set_clock("2026-08-01T00:00:00Z")["current_utc"].startswith(
            "2026-08-01T00:00:00"
        )


class TestRoleExclusiveOperationsRejectsOtherRoles:
    """A legitimate caller on the wrong endpoint is still refused."""

    def test_permission_is_granted_per_endpoint_rather_than_per_entity(
        self, staffed_matter
    ):
        """PRD §2.1: "If the role is recognised but is not among the roles the target
        operation permits, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        The client's counsel is refused the matter listing yet reads her own matter by
        identifier in the very next call.

        Design: Corner/rbac/role_exclusive_operations_rejects_other_roles
        """
        ladder = staffed_matter["ladder"]
        matter_id = staffed_matter["matter_id"]
        client_id = staffed_matter["client_id"]

        validate_error(
            ladder.api.create_batch(
                matter_id, batch_payload(100), staffed_matter["ada_headers"]
            ),
            e.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        matter = validate_success(ladder.api.get_matter(matter_id, ENGAGEMENT_MANAGER))
        assert matter["unbatched_document_count"] == 600

        validate_error(
            ladder.api.create_reviewer(
                reviewer_payload(full_name="Quinn Overreach"), QC_LEAD
            ),
            e.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        reviewers, _ = validate_paginated(
            ladder.api.list_reviewers(STAFFING_COORDINATOR)
        )
        assert len(reviewers) == 1

        counsel = make_client_counsel_headers(client_id)
        validate_error(
            ladder.api.list_matters(counsel, client_id=client_id),
            e.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        assert_status(
            validate_success(ladder.api.get_matter(matter_id, counsel)), "IN_REVIEW"
        )


class TestReviewerIdentityBindingRejectsAnotherReviewersRow:
    """Holding the reviewer role is not the same as owning the paper."""

    def test_one_reviewer_cannot_sign_another_reviewers_agreement(
        self, matter_in_staffing
    ):
        """PRD §3.5: "Execution by anyone other than the named reviewer is
        `ERR_NOT_RESOURCE_OWNER`."

        The refusal leaves the agreement unsigned, and the owning reviewer's own
        signature then carries the matter over its staffing floor.

        Design: Corner/rbac/reviewer_identity_binding_rejects_another_reviewers_row
        """
        ladder = matter_in_staffing["ladder"]
        matter_id = matter_in_staffing["matter_id"]

        papers = {}
        for spec in (REVIEWER_ADA, REVIEWER_BEN):
            reviewer = ladder.source_reviewer(spec)
            ladder.verify_credential(reviewer["id"])
            screening = ladder.open_screening(reviewer["id"])
            ladder.decide_screening(screening["id"], "CLEARED")
            agreement = validate_success(
                ladder.api.create_agreement(
                    agreement_payload(reviewer["id"], matter_id), STAFFING_COORDINATOR
                ),
                expected_status=201,
            )
            papers[spec["full_name"]] = (reviewer["id"], agreement["id"])

        ada_id, ada_agreement_id = papers["Ada Ishikawa"]
        ben_id, _ = papers["Ben Calder"]

        validate_error(
            ladder.api.execute_agreement(
                ada_agreement_id,
                execute_payload("Ben Calder signing for Ada"),
                make_reviewer_headers(ben_id),
            ),
            e.ERR_NOT_RESOURCE_OWNER,
            403,
        )

        untouched = validate_success(
            ladder.api.get_agreement(ada_agreement_id, STAFFING_COORDINATOR)
        )
        assert_status(untouched, "PENDING")
        assert untouched["signature_name"] is None
        assert untouched["executed_at"] is None

        signed = ladder.execute_agreement(ada_agreement_id, ada_id, "Ada Ishikawa")
        assert_status(signed, "EXECUTED")
        assert signed["signature_name"] == "Ada Ishikawa"

        matter = validate_success(ladder.api.get_matter(matter_id, ENGAGEMENT_MANAGER))
        assert matter["staffed_reviewer_count"] == 1
        assert_status(matter, "IN_REVIEW")


class TestClientCounselIdentityBindingRejectsAnotherClientsMatter:
    """The counsel of an unrelated client is refused the decision."""

    def test_only_the_instructing_client_may_approve_the_protocol(
        self, matter_with_draft_protocol
    ):
        """PRD §3.2: "A decision on a protocol that is not in `CLIENT_REVIEW` is
        `ERR_INVALID_STATE`; a decision by a counsel who is not the matter's client is
        `ERR_NOT_MATTER_CLIENT`."

        The endpoint belongs to the client role, yet the row belongs to one client, and
        the outsider's identical payload changes nothing.

        Design: Corner/rbac/client_counsel_identity_binding_rejects_another_clients_matter
        """
        ladder = matter_with_draft_protocol["ladder"]
        matter_id = matter_with_draft_protocol["matter_id"]
        protocol_id = matter_with_draft_protocol["protocol_id"]
        owning_client_id = matter_with_draft_protocol["client_id"]

        outsider = validate_success(
            ladder.api.create_client(
                client_payload(legal_name="Calder Holdings LLC", primary_state="DE"),
                ENGAGEMENT_MANAGER,
            ),
            expected_status=201,
        )
        ladder.submit_protocol(protocol_id)

        validate_error(
            ladder.api.decide_protocol(
                protocol_id,
                protocol_decision_payload("APPROVE"),
                make_client_counsel_headers(outsider["id"]),
            ),
            e.ERR_NOT_MATTER_CLIENT,
            403,
        )

        untouched = validate_success(
            ladder.api.get_protocol(protocol_id, ENGAGEMENT_MANAGER)
        )
        assert_status(untouched, "CLIENT_REVIEW")
        assert untouched["approved_at"] is None
        assert_status(
            validate_success(ladder.api.get_matter(matter_id, ENGAGEMENT_MANAGER)),
            "PROTOCOL_PENDING",
        )

        approved = validate_success(
            ladder.api.decide_protocol(
                protocol_id,
                protocol_decision_payload("APPROVE"),
                make_client_counsel_headers(owning_client_id),
            )
        )
        assert_status(approved, "APPROVED")
        assert_status(
            validate_success(ladder.api.get_matter(matter_id, ENGAGEMENT_MANAGER)),
            "STAFFING",
        )

        assert (
            validate_success(
                ladder.api.get_client(outsider["id"], ENGAGEMENT_MANAGER)
            )["matter_count"]
            == 0
        )
