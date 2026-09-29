"""Who may act, on which resource, and what the header alone cannot buy.

Three tests walk a role through the operations only it may perform; three more
show the boundaries - a role probing another role's exclusive endpoint, an
operator reaching for another organisation's record, and an operator whose role
header is right but whose identity is the one the duty rule forbids.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import assert_field_values
from test_helpers.factories import (
    holder_payload,
    reader_app_payload,
    verifier_payload,
)
from test_helpers.fixtures import (
    append_evidence,
    create_approved_verifier,
    create_holder,
    create_profile,
    create_verifier,
    open_proofing_session,
    register_reader_app,
    submit_session,
)
from test_helpers.test_users import (
    ADJUDICATOR,
    ADMIN,
    PRIVACY_AUDITOR,
    PROOFING_AGENT,
    make_adjudicator_headers,
    make_holder_headers,
    make_proofing_agent_headers,
    make_verifier_operator_headers,
)

_FOUR_TWENTY_EVIDENCE = [
    {
        "evidence_type": "DOCUMENT_SCAN",
        "quality": "STRONG",
        "captured_at": "2026-07-20T09:00:00Z",
        "source_reference": "doc-1",
    },
    {
        "evidence_type": "KNOWLEDGE_CHECK",
        "quality": "STRONG",
        "captured_at": "2026-07-20T09:10:00Z",
        "source_reference": "kba-1",
    },
    {
        "evidence_type": "ADDRESS_CORROBORATION",
        "quality": "STRONG",
        "captured_at": "2026-07-20T09:20:00Z",
        "source_reference": "utility-1",
    },
]


class TestProofingAgentAuthority:
    """The three operations the proofing clerk owns end to end."""

    def test_the_agent_opens_evidences_and_submits_and_is_recorded(self, api):
        """All three calls succeed for the same clerk, and the identifier stored on
        the session is the clerk's own - the value the duty rule reads later.

        PRD 3.2: "A `ProofingAgent` opens an identity-proofing session naming the
        `holder_id` of the person being proofed and the `requested_assurance_level`
        the agent is attempting to establish ... the agent's own `X-User-ID` is
        stored as `proofing_agent_user_id`. That stored identifier is the
        segregation-of-duties comparand and the reason the field exists: the clerk
        who collected the evidence may never be the operator who blesses it."

        Design: Corner/rbac/proofing_agent_runs_all_three_of_its_exclusive_operations
        """
        agent = make_proofing_agent_headers("pa-007")
        create_profile(api)
        holder = create_holder(api)

        session = open_proofing_session(api, holder["id"], agent_headers=agent)
        for item in _FOUR_TWENTY_EVIDENCE[:2]:
            validate_success(
                api.add_proofing_evidence(session["id"], item, agent), 201
            )
        validate_success(api.submit_proofing_session(session["id"], agent))

        stored = validate_success(api.get_proofing_session(session["id"], agent))
        assert_field_values(
            stored,
            {
                "state": "SUBMITTED",
                "evidence_count": 2,
                "proofing_agent_user_id": "pa-007",
            },
        )


class TestPrivacyAuditorAuthority:
    """The oversight office reads the two privacy surfaces and nothing else."""

    def test_the_auditor_reads_the_exposure_index_and_the_log(self, api):
        """A brand-new organisation has no log at all, so both exposure variants
        read zero and the log listing is empty - but both reads are permitted.

        PRD 4: "GET `/mdl/verifiers/{id}/exposure-index` | Computed read: both
        verifier_exposure_index variants side by side - the 30-day ROLLING_WINDOW
        index and the SINCE_LAST_ATTESTATION index - over the same log rows. |
        `SystemAdmin`, `PrivacyAuditor`, `VerifierOperator`"
        PRD 4: "GET `/mdl/verifiers/{id}/presentation-log-entries` | Privacy-audit
        view of the verifier's pseudonymised presentation log, ordered by
        recorded_at ASC. | `SystemAdmin`, `PrivacyAuditor`"

        Design: Corner/rbac/privacy_auditor_reads_the_two_privacy_surfaces_it_owns
        """
        verifier = create_verifier(
            api,
            organization_name="Prairie Cellars",
            category="AGE_RESTRICTED_RETAIL",
            purpose_scope=["family_name", "age_over_21"],
            retention_ceiling_days=30,
        )

        report = validate_success(
            api.get_exposure_index(verifier["id"], PRIVACY_AUDITOR)
        )
        assert_field_values(
            report,
            {
                "rolling_window_index": 0,
                "since_last_attestation_index": 0,
                "rolling_window_entry_count": 0,
            },
        )

        _, meta = validate_paginated(
            api.list_verifier_log_entries(verifier["id"], PRIVACY_AUDITOR)
        )
        assert meta["total_count"] == 0


class TestVerifierOperatorAuthority:
    """Acting on its own record, the operator may register and may attest."""

    def test_the_operator_registers_a_reader_app_and_files_an_attestation(self, api):
        """The attestation records the declared ceiling, restarts the window at the
        current instant and - because the log is empty and scores zero - leaves the
        organisation approved.

        PRD 3.9: "The since-last-attestation variant runs when a
        `VerifierOperator` files a **retention attestation**, declaring the
        `attested_max_retention_days` the organisation actually applies in
        practice; that call scores the historical log against the newly declared
        ceiling, records the declared value as `attested_max_retention_days`,
        applies the thresholds, sets `last_attestation_at` to the current logical
        instant - restarting the window - and increments the verifier's `version` by
        1."

        Design: Corner/rbac/verifier_operator_registers_its_reader_app_and_attests_retention
        """
        verifier = create_approved_verifier(
            api,
            organization_name="Prairie Cellars",
            category="AGE_RESTRICTED_RETAIL",
            purpose_scope=["family_name", "age_over_21"],
            retention_ceiling_days=30,
        )
        operator = make_verifier_operator_headers(verifier["id"])

        register_reader_app(
            api,
            verifier["id"],
            app_identifier="till-a",
            certificate_serial="SER-A1",
            base_rate_cents=30,
        )
        validate_success(
            api.attest_retention(
                verifier["id"], {"attested_max_retention_days": 14}, operator
            )
        )

        stored = validate_success(api.get_verifier(verifier["id"], ADMIN))
        assert_field_values(
            stored,
            {
                "attested_max_retention_days": 14,
                "last_attestation_at": "2026-08-01T00:00:00Z",
                "exposure_index": 0,
                "trust_status": "APPROVED",
            },
        )


class TestRoleExclusivity:
    """Six probes, each aimed at an endpoint its role is not listed on."""

    def test_no_role_may_perform_another_roles_exclusive_operation(self, api):
        """Every probe names an identifier that has never existed, so an
        implementation that resolves the path before checking the role would answer
        404 instead of the 403 the ladder demands.

        PRD 2.6: "1. Header presence and role validity - `ERR_UNAUTHENTICATED`. 2.
        The acting role is authorized for the endpoint - `ERR_FORBIDDEN_ROLE`. 3.
        Request-body schema conformance ... 4. Every path-templated resource
        resolves, left to right - the per-entity 404 codes."
        PRD 2.6: "A forbidden role always beats a malformed body. A missing
        resource always beats an ownership failure."

        Design: Corner/rbac/each_role_is_denied_another_roles_exclusive_operation
        """
        validate_error(
            api.create_holder(holder_payload(), make_holder_headers(NON_EXISTENT_UUID)),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.create_verifier(verifier_payload(), PROOFING_AGENT),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.add_proofing_evidence(
                NON_EXISTENT_UUID,
                {
                    "evidence_type": "DOCUMENT_SCAN",
                    "quality": "STRONG",
                    "captured_at": "2026-07-20T09:00:00Z",
                    "source_reference": "doc-1",
                },
                ADJUDICATOR,
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.attest_device(
                NON_EXISTENT_UUID,
                {
                    "attestation_result": "PASS",
                    "secure_element_grade": "HARDWARE_STRONGBOX",
                },
                make_verifier_operator_headers(NON_EXISTENT_UUID),
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.revoke_credential(
                NON_EXISTENT_UUID, {"reason": "FRAUD"}, PRIVACY_AUDITOR
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.disclose_presentation(NON_EXISTENT_UUID, ADMIN),
            ERR_FORBIDDEN_ROLE,
            403,
        )


class TestOperatorOwnership:
    """The right role on the wrong organisation is still refused."""

    def test_an_operator_cannot_register_a_reader_app_for_another_verifier(self, api):
        """Both organisations are approved, so the trust gate is satisfied; what
        fails is that the acting identity is not the organisation named in the body,
        and the named organisation ends with no applications.

        PRD 2.1: "When `X-User-Role` is `VerifierOperator`, `X-User-ID` is the `id`
        of the acting Verifier record; ownership checks compare the `verifier_id` of
        the reader application involved (directly, or reached through the
        presentation session's `reader_app_id`) to `X-User-ID`."
        PRD 2.6: "6. Ownership for the entity-backed roles -
        `ERR_NOT_RESOURCE_OWNER`. This applies to credential activation, loss
        reporting, handset recovery, reader-app registration"

        Design: Corner/rbac/verifier_operator_cannot_register_a_reader_app_for_another_verifier
        """
        verifier_a = create_approved_verifier(
            api,
            organization_name="Prairie Cellars",
            category="AGE_RESTRICTED_RETAIL",
            purpose_scope=["family_name", "age_over_21"],
            retention_ceiling_days=30,
        )
        verifier_b = create_approved_verifier(
            api,
            organization_name="Sandhills Bank",
            category="COMMERCIAL",
            purpose_scope=["family_name", "birth_date"],
            retention_ceiling_days=60,
        )

        refused = api.create_reader_app(
            reader_app_payload(
                verifier_a["id"],
                app_identifier="till-a",
                certificate_serial="SER-A1",
                base_rate_cents=30,
            ),
            make_verifier_operator_headers(verifier_b["id"]),
        )
        validate_error(refused, ERR_NOT_RESOURCE_OWNER, 403)

        _, meta = validate_paginated(
            api.list_verifier_reader_apps(verifier_a["id"], ADMIN)
        )
        assert meta["total_count"] == 0


class TestSegregationOfDuties:
    """The clerk who collected the evidence may not bless it."""

    def test_the_proofing_clerk_cannot_adjudicate_its_own_session(self, api):
        """Presenting the adjudicator role with the clerk's own identity is refused
        and writes nothing; a different adjudicator then verifies the same session.

        PRD 3.2: "Before anything else the acting `X-User-ID` is compared against
        the session's `proofing_agent_user_id`; if they are equal the request is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
        PRD 3.2: "On success `achieved_assurance_level` is written from the recorded
        score - `IAL2` at 420 points or above"

        Design: Corner/rbac/same_user_cannot_adjudicate_the_session_they_proofed
        """
        agent = make_proofing_agent_headers("pa-007")
        create_profile(api)
        holder = create_holder(api)
        session = open_proofing_session(api, holder["id"], agent_headers=agent)
        append_evidence(
            api, session["id"], _FOUR_TWENTY_EVIDENCE, agent_headers=agent
        )
        submit_session(api, session["id"], agent_headers=agent)

        validate_error(
            api.adjudicate_proofing_session(
                session["id"],
                {"decision": "VERIFY"},
                make_adjudicator_headers("pa-007"),
            ),
            ERR_SEGREGATION_OF_DUTIES,
            409,
        )

        untouched = validate_success(
            api.get_proofing_session(session["id"], ADJUDICATOR)
        )
        assert_field_values(
            untouched,
            {
                "state": "SUBMITTED",
                "adjudicator_user_id": None,
                "adjudication_score": None,
            },
        )

        verified = validate_success(
            api.adjudicate_proofing_session(
                session["id"], {"decision": "VERIFY"}, ADJUDICATOR
            )
        )
        assert_field_values(
            verified,
            {
                "state": "VERIFIED",
                "adjudication_score": 420,
                "achieved_assurance_level": "IAL2",
                "adjudicator_user_id": "ca-001",
            },
        )
