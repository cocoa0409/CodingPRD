"""Segregation of duties: Court adjudicates, Receiver administers, Creditor reads/files."""
from test_helpers import (
    COURT,
    CREDITOR,
    RECEIVER,
    ApiErrorId,
    create_case,
    create_engagement,
    validate_error,
    validate_success,
)


class TestSegregationOfDuties:
    def test_receiver_cannot_decide_engagement(self, api):
        """PRD §2.1: "A request whose role is recognized but is not
        permitted on the targeted endpoint — for example, a `Receiver`
        attempting to adjudicate its own fee application, or a `Creditor`
        attempting to liquidate an asset — is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §2.1: "The division of labor is asymmetric by design. The
        `Court` appoints the receiver by creating the case, adjudicates
        every instrument the receiver files, reconsiders claims, voids paid
        distributions, and discharges the estate."

        Design: Corner/rbac/receiver_cannot_decide_engagement
        """
        case = create_case()
        eng = create_engagement(case["id"])

        resp = api.decide_engagement(eng["id"], {"decision": "APPROVE"}, RECEIVER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        ok = api.decide_engagement(eng["id"], {"decision": "APPROVE"}, COURT)
        assert validate_success(ok, 200)["status"] == "APPROVED"

    def test_court_cannot_create_asset(self, api):
        """PRD §2.1: "The division of labor is asymmetric by design. The
        `Court` appoints the receiver by creating the case, adjudicates
        every instrument the receiver files, reconsiders claims, voids paid
        distributions, and discharges the estate. The `Receiver` marshals
        and liquidates assets, determines claims, proposes engagements,
        files fee applications and status reports, seeks authorization for
        out-of-ordinary-course actions, files and amends the distribution
        plan, and executes payments."

        Design: Corner/rbac/court_cannot_create_asset
        """
        case = create_case()
        resp = api.create_asset(
            {
                "case_id": case["id"],
                "description": "Forklift",
                "asset_class": "EQUIPMENT",
                "estimated_value_cents": 25000,
            },
            COURT,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_receiver_cannot_set_clock(self, api):
        """PRD §2.1: "When `X-User-Role` is `SystemAdmin`, `X-User-ID` is an
        opaque test-harness operator identifier, never an entity `id`, and
        the role controls only the logical clock."

        Design: Corner/rbac/receiver_cannot_set_clock
        """
        resp = api.set_clock("2026-09-15T00:00:00Z", RECEIVER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestAuthorizationPriority:
    def test_forbidden_beats_not_found_for_creditor_engagement_read(self, api):
        """PRD §2.1: "Authentication is always evaluated before
        authorization, and both are evaluated before any request-shape,
        existence, state, or fiscal check."

        Design: Corner/validations/forbidden_beats_not_found_for_creditor_engagement_read
        """
        resp = api.get_engagement(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", CREDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
