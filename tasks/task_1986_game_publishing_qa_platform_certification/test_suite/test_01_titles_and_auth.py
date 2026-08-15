"""Title onboarding defaults, envelope rules, auth context, and the title
lifecycle's CERT_APPROVED gate."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_title,
    assert_game_title,
    create_title,
    create_title_payload,
    get_title,
    is_valid_uuid,
    validate_error,
    validate_success,
)


class TestTitleCreation:
    def test_title_created_with_defaults_and_initialized_budget(self, api,
                                                                release_manager_headers):
        """PRD §3.1: "A new title starts in `CONCEPT` with `embargoed` false,
        `embargo_reason` null, `hotfix_rollback_count` zero, and `version` 1."
        PRD §2.7: "The three partitions are defined so that available equals
        `cert_budget_total_cents` minus escrow minus spent, and the conserved
        invariant is that available, escrow, and spent always sum exactly to
        `cert_budget_total_cents`."

        Design: Corner/entities/title_create_applies_defaults_and_computed_budget
        """
        resp = api.create_title(
            create_title_payload(
                title_code="ENT-T1", name="Ent T1",
                platform_codes=["PS5", "PC"], cert_budget_total_cents=300000,
            ),
            release_manager_headers,
        )
        title = validate_success(resp, expected_status=201)
        assert_game_title(title)
        assert title["status"] == "CONCEPT"
        assert title["embargoed"] is False
        assert title["hotfix_rollback_count"] == 0
        assert title["version"] == 1
        assert title["cert_budget_available_cents"] == 300000
        assert title["cert_budget_escrow_cents"] == 0
        assert title["cert_budget_spent_cents"] == 0
        assert title["open_blocker_count"] == 0

    def test_title_create_ignores_client_supplied_id(self, api,
                                                     release_manager_headers):
        """PRD §2.5: "A unique, server-minted identifier formatted as a UUID,
        with no type prefix."

        Design: Corner/entities/title_create_server_minted_id_input_ignored
        """
        payload = create_title_payload(title_code="ENT-T2", name="Ent T2",
                                       cert_budget_total_cents=1000)
        payload["id"] = "client-supplied-id"
        resp = api.create_title(payload, release_manager_headers)
        title = validate_success(resp, expected_status=201)
        assert title["id"] != "client-supplied-id"
        assert is_valid_uuid(title["id"])

    def test_title_create_missing_budget_field_rejected(self, api,
                                                        release_manager_headers):
        """PRD §2.8: "Malformed requests — a missing required field, an unknown
        enum value, a wrong-typed value, an out-of-range scalar, or a window
        whose end is not strictly after its start — are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400) at the point the malformation is
        detected."

        Design: Corner/entities/title_create_missing_required_field
        """
        resp = api.create_title(
            {
                "title_code": "ENT-T3",
                "name": "Ent T3",
                "platform_codes": ["PS5"],
                "target_launch_date": "2026-11-01",
            },
            release_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_title_get_unknown_id_not_found(self, api, reader_headers):
        """PRD §2.11: "the server confirms the parent identifier first and
        rejects immediately with `ERR_NOT_FOUND` (HTTP 404) for the first
        identifier that does not resolve to an existing resource"

        Design: Corner/entities/title_get_not_found_returns_404
        """
        resp = api.get_title(NON_EXISTENT_UUID, reader_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAuthContext:
    def test_create_title_without_identity_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        string outside this declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/errors/titles_create_missing_header_rejected
        """
        resp = api.create_title(
            create_title_payload(title_code="ERR-AUTH", name="Err Auth",
                                 cert_budget_total_cents=1000),
            {},
        )
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
        )

    def test_clock_set_forbidden_for_qa_lead(self, api, qa_lead_headers):
        """PRD §2.4: "A `PlatformAdmin`-only capability sets the logical clock
        to a supplied `to_iso8601` instant, after which all later
        time-dependent evaluations use the new reading."
        PRD §2.1: "When a declared role attempts an operation reserved for a
        different role — including the per-transition role restrictions on
        lifecycle endpoints — the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/clock_set_forbidden_for_qalead
        """
        resp = api.set_clock("2026-08-03T00:00:00Z", qa_lead_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestTitleLifecycleGates:
    def test_cert_approved_requires_an_approved_package(self, api,
                                                        release_manager_headers):
        """PRD §3.1: "Promotion from `CERTIFICATION` to `CERT_APPROVED`
        requires that at least one of the title's submission packages has
        reached `APPROVED`; without one the transition is rejected with
        `ERR_NO_APPROVED_PACKAGE`."

        Design: Corner/state_machines/title_cert_approved_gate_requires_package
        """
        title = create_title(title_code="SM2-TAP", cert_budget_total_cents=1000)
        advance_title(title["id"], "IN_DEVELOPMENT")
        advance_title(title["id"], "CERTIFICATION")
        resp = api.transition_title(
            title["id"], {"to_status": "CERT_APPROVED"}, release_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_NO_APPROVED_PACKAGE)
        assert get_title(title["id"])["status"] == "CERTIFICATION"
