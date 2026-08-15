"""Authentication, authorization ordering, and role denials (PRD §2.1, §2.6, §4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_attestation_campaign_payload,
    create_provider,
    create_provider_merge_payload,
    create_roster_file_payload,
    create_source,
    make_headers_without_role,
    set_clock,
    validate_error,
)


class TestAuthentication:
    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or names no known
        role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_role_header
        """
        res = api.list_providers(make_headers_without_role())
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_auth_precedes_not_found(self, api):
        """PRD §2.6: "Authentication comes first — a missing or unknown role yields
        `ERR_UNAUTHENTICATED` before anything else is examined."
        PRD §2.6: "Next, path identifiers are resolved for existence and parentage,
        left to right, with any miss producing `ERR_NOT_FOUND`."

        Design: Corner/validations/priority_auth_before_not_found
        """
        res = api.get_provider(NON_EXISTENT_UUID, make_headers_without_role())
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenials:
    def test_intake_operator_cannot_merge(self, api, intake_operator_headers):
        """PRD §2.1: "A request whose role is not permitted for the endpoint, per the
        authorization column of the endpoint table in §4, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)." §4 lists `POST /pdm/provider-merges` for
        DataSteward only.

        Design: Corner/validations/forbidden_intake_cannot_merge
        """
        set_clock()
        a = create_provider()
        b = create_provider(npi="1234567894", location_key="LOC2")
        res = api.create_provider_merge(
            create_provider_merge_payload(a["id"], b["id"], b["version"], rationale="x"),
            intake_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_distribution_operator_cannot_resolve_conflicts(
        self, api, distribution_operator_headers
    ):
        """PRD §2.1: "A request whose role is not permitted for the endpoint, per the
        authorization column of the endpoint table in §4, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)." §4 lists conflict resolution for DataSteward only,
        and §2.6 evaluates authorization before path existence, so the denial fires even
        for a non-existent conflict id.

        Design: Corner/rbac/distribution_operator_cannot_resolve_conflicts
        """
        set_clock()
        res = api.resolve_attribute_conflict(
            NON_EXISTENT_UUID, {"resolution": "KEEP_INCUMBENT"},
            distribution_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_provider_contact_cannot_create_campaign(self, api, provider_contact_headers):
        """PRD §2.1: "A request whose role is not permitted for the endpoint, per the
        authorization column of the endpoint table in §4, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)." §4 lists `POST /pdm/attestation-campaigns` for
        DataSteward only.

        Design: Corner/rbac/provider_contact_cannot_create_campaign
        """
        set_clock()
        res = api.create_attestation_campaign(
            create_attestation_campaign_payload(name="X", window_days=5),
            provider_contact_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_data_steward_cannot_register_file(self, api, data_steward_headers):
        """PRD §2.1: "A request whose role is not permitted for the endpoint, per the
        authorization column of the endpoint table in §4, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)." §4 lists `POST /pdm/roster-files` for
        IntakeOperator only.

        Design: Corner/rbac/data_steward_cannot_register_file
        """
        set_clock()
        source = create_source(source_code="RB3", precedence_rank=1)
        res = api.create_roster_file(
            create_roster_file_payload(
                source["id"], external_file_ref="rb3f", checksum="rb3c"
            ),
            data_steward_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
