"""Which rule speaks first when two rules would both reject the same request.

The rejection ladder of the PRD is strictly ordered and the first failing
check decides the response, so a request that breaches two rules at once must
report the higher-priority one and stay silent about the lower one.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_CERT_WINDOW_CONFLICT,
    ERR_HANDSET_SURRENDER_PROHIBITED,
    ERR_RETENTION_CEILING_EXCEEDED,
    ERR_VERIFIER_NOT_TRUSTED,
)
from test_helpers.assertions import assert_row_count, rows_of
from test_helpers.factories import presentation_session_payload, reader_app_payload
from test_helpers.fixtures import (
    create_approved_verifier,
    create_presentation_ready_world,
    create_profile,
    decide_trust,
)
from test_helpers.test_users import ADMIN, make_verifier_operator_headers


class TestHandsetSurrenderOutranksRetentionCeiling:
    """Ladder step 13 (handset handling) is reported ahead of step 31."""

    @staticmethod
    def _world(api):
        return create_presentation_ready_world(
            api,
            verifier_overrides={
                "organization_name": "Cornhusker Patrol Supply",
                "category": "COMMERCIAL",
                "purpose_scope": ["family_name", "age_over_21"],
                "retention_ceiling_days": 5,
            },
            reader_app_overrides={
                "app_identifier": "kiosk-a",
                "certificate_serial": "SER-K1",
                "requested_elements": ["family_name", "age_over_21"],
                "base_rate_cents": 25,
            },
        )

    def test_surrender_demand_is_named_and_the_retention_breach_is_not(self, api):
        """A request that both demands the handset and over-declares retention
        reports only the handset demand.

        PRD 2.6: "13. Handset-handling policy - `ERR_HANDSET_SURRENDER_PROHIBITED`."
        ... "31. Declared retention within the verifier's contractual ceiling -
        `ERR_RETENTION_CEILING_EXCEEDED`."
        PRD 2.11: "a request declaring `SURRENDER_REQUESTED` is rejected with
        `ERR_HANDSET_SURRENDER_PROHIBITED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/handset_surrender_prohibition_outranks_retention_ceiling
        """
        world = self._world(api)
        headers = make_verifier_operator_headers(world["verifier"]["id"])

        both_breached = api.create_presentation_session(
            presentation_session_payload(
                world["credential"]["id"],
                world["reader_app"]["id"],
                context="ROUTINE",
                purpose="identity check at the counter",
                requested_elements=["family_name", "age_over_21"],
                handset_handling="SURRENDER_REQUESTED",
                retention_days=90,
            ),
            headers,
        )
        error = validate_error(both_breached, ERR_HANDSET_SURRENDER_PROHIBITED, 422)
        assert error["error_id"] != ERR_RETENTION_CEILING_EXCEEDED

        retention_only = api.create_presentation_session(
            presentation_session_payload(
                world["credential"]["id"],
                world["reader_app"]["id"],
                context="ROUTINE",
                purpose="identity check at the counter",
                requested_elements=["family_name", "age_over_21"],
                handset_handling="TAP_TO_READ",
                retention_days=90,
            ),
            headers,
        )
        validate_error(retention_only, ERR_RETENTION_CEILING_EXCEEDED, 422)

    def test_neither_rejected_presentation_leaves_a_trace(self, api):
        """Both rejections are refusals, so no session row and no open-session
        count movement survives them.

        PRD 3.8: "`ERR_RETENTION_CEILING_EXCEEDED` (HTTP 422). That retention
        check is enforced at **both** ends of the presentation: at session
        creation and again at disclosure."
        PRD 3.7: "A new verifier begins in `trust_status` `APPLIED` with
        `exposure_index`, `open_session_count`, `billable_query_balance_cents`,
        `credited_amount_cents` and `probation_strike_count` all at zero"

        Design: Difficulty/priority_pair_validation_conflict/handset_surrender_prohibition_outranks_retention_ceiling
        """
        world = self._world(api)
        headers = make_verifier_operator_headers(world["verifier"]["id"])

        for handling in ("SURRENDER_REQUESTED", "TAP_TO_READ"):
            api.create_presentation_session(
                presentation_session_payload(
                    world["credential"]["id"],
                    world["reader_app"]["id"],
                    context="ROUTINE",
                    purpose="identity check at the counter",
                    requested_elements=["family_name", "age_over_21"],
                    handset_handling=handling,
                    retention_days=90,
                ),
                headers,
            )

        assert_row_count(api.list_presentation_sessions(ADMIN), 0)
        verifier = validate_success(api.get_verifier(world["verifier"]["id"], ADMIN))
        assert verifier["open_session_count"] == 0


class TestVerifierTrustOutranksCertificateRenewalBuffer:
    """Ladder step 16 (verifier trust) is reported ahead of step 22."""

    @staticmethod
    def _suspended_verifier_with_incumbent_app(api):
        create_profile(api)
        verifier = create_approved_verifier(
            api,
            organization_name="Lincoln Transit Authority",
            category="GOVERNMENT_SERVICE",
            purpose_scope=["family_name", "age_over_18"],
            retention_ceiling_days=30,
        )
        incumbent = validate_success(
            api.create_reader_app(
                reader_app_payload(
                    verifier["id"],
                    app_identifier="gate-reader",
                    certificate_serial="SER-G1",
                    cert_not_before="2026-07-01T00:00:00Z",
                    cert_not_after="2027-07-01T00:00:00Z",
                    requested_elements=["family_name", "age_over_18"],
                ),
                make_verifier_operator_headers(verifier["id"]),
            ),
            201,
        )
        decide_trust(api, verifier["id"], "SUSPEND")
        return verifier, incumbent

    @staticmethod
    def _renewal_payload(verifier_id):
        return reader_app_payload(
            verifier_id,
            app_identifier="gate-reader",
            certificate_serial="SER-G2",
            cert_not_before="2027-07-01T00:00:00Z",
            cert_not_after="2028-07-01T00:00:00Z",
            requested_elements=["family_name", "age_over_18"],
        )

    def test_suspended_verifier_is_named_before_the_adjacent_certificate(self, api):
        """A renewal registration that is both untrusted and exactly adjacent
        reports the trust failure, and only reports the buffer failure once the
        verifier is trusted again.

        PRD 2.6: "16. Verifier trust status - `ERR_VERIFIER_NOT_TRUSTED`."
        ... "22. Reader-certificate renewal buffer - `ERR_CERT_WINDOW_CONFLICT`."
        PRD 2.12: "the new certificate must start **at least 24 hours after** the
        incumbent's `cert_not_after`. Exact adjacency is rejected along with
        anything earlier"

        Design: Difficulty/priority_pair_validation_conflict/verifier_trust_status_outranks_reader_cert_renewal_buffer
        """
        verifier, _ = self._suspended_verifier_with_incumbent_app(api)
        operator = make_verifier_operator_headers(verifier["id"])

        while_suspended = api.create_reader_app(
            self._renewal_payload(verifier["id"]), operator
        )
        error = validate_error(while_suspended, ERR_VERIFIER_NOT_TRUSTED, 403)
        assert error["error_id"] != ERR_CERT_WINDOW_CONFLICT

        reinstated = validate_success(
            api.decide_verifier_trust(verifier["id"], {"decision": "REINSTATE"}, ADMIN)
        )
        assert reinstated["trust_status"] == "APPROVED"

        while_approved = api.create_reader_app(
            self._renewal_payload(verifier["id"]), operator
        )
        validate_error(while_approved, ERR_CERT_WINDOW_CONFLICT, 422)

    def test_only_the_incumbent_certificate_remains_registered(self, api):
        """Neither rejected registration created a reader application row.

        PRD 3.7: "`app_identifier` is deliberately **not** unique: a certificate
        renewal registers a brand-new application row sharing the identifier
        with its predecessor, and that is exactly the case the renewal-buffer
        rule polices."

        Design: Difficulty/priority_pair_validation_conflict/verifier_trust_status_outranks_reader_cert_renewal_buffer
        """
        verifier, _ = self._suspended_verifier_with_incumbent_app(api)
        operator = make_verifier_operator_headers(verifier["id"])

        api.create_reader_app(self._renewal_payload(verifier["id"]), operator)
        decide_trust(api, verifier["id"], "REINSTATE")
        api.create_reader_app(self._renewal_payload(verifier["id"]), operator)

        apps = rows_of(api.list_verifier_reader_apps(verifier["id"], operator))
        assert len(apps) == 1
        assert apps[0]["certificate_serial"] == "SER-G1"
