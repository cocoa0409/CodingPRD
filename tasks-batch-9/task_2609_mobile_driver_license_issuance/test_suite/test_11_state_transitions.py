"""Transitions the PRD declares, and the ones it refuses to declare.

Divergent branches, one-shot triggers, terminal lockdowns and the compound
side-effect bundles that a single transition is required to apply all at once.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_INSUFFICIENT_EVIDENCE,
    ERR_INVALID_STATE,
)
from test_helpers.assertions import assert_field_values, assert_row_count, rows_of
from test_helpers.factories import verifier_payload
from test_helpers.fixtures import (
    STRONG_DOCUMENT_AND_BIOMETRIC,
    append_evidence,
    attest_device,
    create_active_credential,
    create_approved_verifier,
    create_holder,
    create_listed_reader_app,
    create_presentation_ready_world,
    create_profile,
    decide_trust,
    first_delivery_of,
    open_address_change,
    open_presentation_session,
    open_proofing_session,
    register_device,
    submit_session,
)
from test_helpers.test_users import (
    ADJUDICATOR,
    ADMIN,
    PRIVACY_AUDITOR,
    PROOFING_AGENT,
    make_holder_headers,
)


def _collecting_session_with(api, items):
    create_profile(api)
    holder = create_holder(api)
    session = open_proofing_session(api, holder["id"])
    append_evidence(api, session["id"], items)
    return holder, session


class TestHandsetAttestationBranches:
    """PASS and FAIL part company on the multi-device counter."""

    def test_a_failed_attestation_retires_the_handset_and_counts_nothing(self, api):
        """The FAIL branch is not a no-op and not a mirror of PASS: the handset
        goes terminal while the holder's device cap is left alone.

        PRD 3.3: "Both branches record `attestation_result` and
        `secure_element_grade` and both increment the handset's `version` by 1,
        but there they part company. The `PASS` branch drives `REGISTERED ->
        ATTESTED` and increments the owning holder's `bound_device_count` by 1.
        The `FAIL` branch drives `REGISTERED -> RETIRED` and leaves
        `bound_device_count` completely untouched"

        Design: Corner/state_machines/device_attest_fail_branch_retires_handset_without_counting_it
        """
        create_profile(api)
        holder = create_holder(api)
        device = register_device(
            api, holder["id"], platform="IOS", model_name="iPhone 17"
        )

        retired = attest_device(api, device["id"], "FAIL", "SOFTWARE")
        assert_field_values(
            retired,
            {
                "state": "RETIRED",
                "attestation_result": "FAIL",
                "secure_element_grade": "SOFTWARE",
                "active_binding_count": 0,
                "version": 2,
            },
        )

        stored_holder = validate_success(api.get_holder(holder["id"], ADMIN))
        assert stored_holder["bound_device_count"] == 0


class TestProofingSubmission:
    """Submission is a one-shot trigger with a hard evidence floor."""

    def test_one_evidence_item_is_below_the_submission_floor(self, api):
        """A single item is refused, and the refused attempt must not be counted
        as a submission - that count later costs assurance points.

        PRD 3.2: "Submitting a session for adjudication moves it `COLLECTING ->
        SUBMITTED` and increments `submission_count` by 1. Submission requires at
        least two evidence items on the session; a session with fewer is rejected
        with `ERR_INSUFFICIENT_EVIDENCE` (HTTP 422)."

        Design: Corner/state_machines/proofing_submit_with_single_evidence_item_rejected
        """
        _, session = _collecting_session_with(
            api, STRONG_DOCUMENT_AND_BIOMETRIC[:1]
        )

        validate_error(
            api.submit_proofing_session(session["id"], PROOFING_AGENT),
            ERR_INSUFFICIENT_EVIDENCE,
            422,
        )

        unchanged = validate_success(
            api.get_proofing_session(session["id"], PROOFING_AGENT)
        )
        assert_field_values(
            unchanged,
            {"state": "COLLECTING", "submission_count": 0, "evidence_count": 1},
        )

    def test_submitting_an_already_submitted_session_is_refused(self, api):
        """Re-running the transition would inflate the submission count and
        silently charge the applicant the resubmission penalty.

        PRD 3.2: "Submitting a session for adjudication moves it `COLLECTING ->
        SUBMITTED` and increments `submission_count` by 1."
        PRD 2.6: "7. The target resource is in a state from which the requested
        transition is declared - `ERR_INVALID_STATE`, except where one of the
        three more specific state checks below applies."

        Design: Corner/state_machines/second_submit_on_submitted_session_returns_invalid_state
        """
        _, session = _collecting_session_with(api, STRONG_DOCUMENT_AND_BIOMETRIC)
        submit_session(api, session["id"])

        validate_error(
            api.submit_proofing_session(session["id"], PROOFING_AGENT),
            ERR_INVALID_STATE,
            409,
        )

        stored = validate_success(
            api.get_proofing_session(session["id"], PROOFING_AGENT)
        )
        assert_field_values(stored, {"state": "SUBMITTED", "submission_count": 1})

    def test_adjudicating_a_session_that_was_never_submitted_is_refused(self, api):
        """Adjudication is declared only from SUBMITTED, and the state check sits
        above the segregation-of-duties check, so the state code wins.

        PRD 3.2: "Adjudication is a `CredentialAdjudicator` action on a
        `SUBMITTED` session, carrying a `decision` of `VERIFY`, `RETURN` or
        `DENY`."
        PRD 2.6: "7. The target resource is in a state from which the requested
        transition is declared - `ERR_INVALID_STATE` ... 12. Segregation of duties
        at adjudication - `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/state_machines/adjudicate_on_collecting_session_returns_invalid_state
        """
        _, session = _collecting_session_with(api, STRONG_DOCUMENT_AND_BIOMETRIC)

        validate_error(
            api.adjudicate_proofing_session(
                session["id"], {"decision": "VERIFY"}, ADJUDICATOR
            ),
            ERR_INVALID_STATE,
            409,
        )

        stored = validate_success(
            api.get_proofing_session(session["id"], ADJUDICATOR)
        )
        assert_field_values(
            stored,
            {
                "state": "COLLECTING",
                "adjudication_score": None,
                "adjudicator_user_id": None,
            },
        )


class TestVerifierTrustLifecycle:
    """A relying party starts outside the trust list and can leave it for good."""

    def test_a_new_relying_party_starts_applied_with_every_counter_zeroed(self, api):
        """Registration alone confers nothing: the organisation is APPLIED and all
        five derived counters are at zero.

        PRD 3.7: "A new verifier begins in `trust_status` `APPLIED` with
        `exposure_index`, `open_session_count`, `billable_query_balance_cents`,
        `credited_amount_cents` and `probation_strike_count` all at zero, and it
        cannot register reader applications or open presentations until it has
        been approved."

        Design: Corner/state_machines/verifier_is_created_in_applied_trust_status
        """
        created = validate_success(
            api.create_verifier(verifier_payload(), ADMIN), 201
        )
        assert_field_values(
            created,
            {
                "trust_status": "APPLIED",
                "exposure_index": 0,
                "open_session_count": 0,
                "billable_query_balance_cents": 0,
                "credited_amount_cents": 0,
                "probation_strike_count": 0,
                "last_attestation_at": None,
                "version": 1,
            },
        )

    def test_termination_is_final_and_the_delisting_it_caused_stands(self, api):
        """A reinstatement of a terminated organisation is refused and the reader
        application termination delisted stays delisted.

        PRD 3.7: "`REINSTATE` returns a verifier to `APPROVED` from either
        `PROBATION` or `SUSPENDED` ... A reinstatement attempted from any other
        status, or with an `exposure_index` of 60 or more, or from `PROBATION`
        without a prior attestation, fails with `ERR_INVALID_STATE`."
        PRD 3.7: "`TERMINATE` moves the verifier to `TERMINATED` and is accepted
        from any status other than `TERMINATED` itself. Every reader application
        of that verifier whose `trust_state` is `LISTED` becomes `DELISTED`"

        Design: Corner/state_machines/terminated_verifier_cannot_be_reinstated
        """
        verifier = create_approved_verifier(api)
        create_listed_reader_app(
            api,
            verifier["id"],
            app_identifier="till-a",
            certificate_serial="SER-A1",
            base_rate_cents=30,
        )
        decide_trust(api, verifier["id"], "TERMINATE")

        validate_error(
            api.decide_verifier_trust(
                verifier["id"], {"decision": "REINSTATE"}, ADMIN
            ),
            ERR_INVALID_STATE,
            409,
        )

        stored = validate_success(api.get_verifier(verifier["id"], ADMIN))
        assert stored["trust_status"] == "TERMINATED"

        apps = rows_of(api.list_verifier_reader_apps(verifier["id"], ADMIN))
        assert apps[0]["trust_state"] == "DELISTED"


class TestHandsetWipe:
    """One transition, four declared effects, all applied together."""

    def test_the_wipe_revokes_the_suspended_credential_and_frees_the_slot(self, api):
        """Wiping a lost handset must finish the job the loss report started: the
        suspended credential is revoked and the device slot is released.

        PRD 3.4: "The handset moves `LOST_REPORTED -> WIPED`, its
        `active_binding_count` is set to zero, the holder's `bound_device_count`
        decrements by 1 - freeing the device slot at last - and the handset's
        `version` increments by 1. Every credential on that handset in `SUSPENDED`
        moves `SUSPENDED -> REVOKED`, each appending a ledger entry with status
        `REVOKED` and reason `DEVICE_LOST` and incrementing the holder's
        `revoked_credential_count` by 1"

        Design: Corner/state_machines/wipe_revokes_the_suspended_credential_and_clears_every_binding
        """
        bundle = create_active_credential(api)
        holder_id = bundle["holder"]["id"]
        validate_success(
            api.report_device_lost(
                bundle["device"]["id"], make_holder_headers(holder_id)
            )
        )

        wiped = validate_success(api.wipe_device(bundle["device"]["id"], ADMIN))
        assert_field_values(wiped, {"state": "WIPED", "active_binding_count": 0})

        holder = validate_success(api.get_holder(holder_id, ADMIN))
        assert_field_values(
            holder,
            {
                "bound_device_count": 0,
                "active_credential_count": 0,
                "revoked_credential_count": 1,
            },
        )

        credential = validate_success(
            api.get_credential(bundle["credential"]["id"], ADMIN)
        )
        assert credential["lifecycle_state"] == "REVOKED"

        entries = assert_row_count(
            api.list_revocation_entries(bundle["credential"]["id"], ADMIN), 2
        )
        assert_field_values(entries[0], {"sequence": 1, "status": "SUSPENDED"})
        assert_field_values(
            entries[1], {"sequence": 2, "status": "REVOKED", "reason": "DEVICE_LOST"}
        )


class TestUpdateOrderRollupAcrossTwoFailures:
    """Each order rolls up from its own children; only the second failure stales."""

    @staticmethod
    def _two_orders_each_with_one_failing_delivery(api):
        bundle = create_active_credential(api)
        holder_id = bundle["holder"]["id"]

        first_order = open_address_change(api, holder_id)
        first_delivery = first_delivery_of(api, first_order["id"])
        validate_success(
            api.fail_update(
                first_delivery["id"], {"failure_code": "DEVICE_UNREACHABLE"}, ADMIN
            )
        )

        second_order = open_address_change(
            api, holder_id, address_line1="77 Juniper Court"
        )
        second_delivery = first_delivery_of(api, second_order["id"])
        bundle["first_order"] = first_order
        bundle["second_order"] = second_order
        bundle["second_delivery"] = second_delivery
        return bundle

    def test_both_orders_close_failed_and_the_second_failure_stales_the_payload(
        self, api
    ):
        """Order one was already closed by its own child; order two closes the same
        way, and this second failure is what drives the credential to STALE and
        suspends it.

        PRD 3.5: "otherwise when `delivered_count` plus `failed_count` equals
        `delivery_count` - meaning nothing is outstanding and at least one child
        failed - the status is `FAILED_CLOSED`"
        PRD 3.5: "On the **second** failure for that credential - the case where
        `failed_delivery_count` had been exactly 1 before this failure - the sync
        axis moves `UPDATE_PENDING -> STALE`, and the single cross-axis coupling of
        2.8 fires: the lifecycle axis moves `ACTIVE -> SUSPENDED` with
        `suspend_reason` `UPDATE_FAILED`"

        Design: Corner/state_machines/two_singleton_orders_both_close_failed_and_stale_the_credential
        """
        bundle = self._two_orders_each_with_one_failing_delivery(api)

        failed = validate_success(
            api.fail_update(
                bundle["second_delivery"]["id"],
                {"failure_code": "USER_DECLINED"},
                ADMIN,
            )
        )
        assert_field_values(
            failed,
            {
                "status": "FAILED",
                "attempt_count": 1,
                "failure_code": "USER_DECLINED",
            },
        )

        first = validate_success(
            api.get_update_order(bundle["first_order"]["id"], ADMIN)
        )
        assert_field_values(
            first,
            {
                "status": "FAILED_CLOSED",
                "delivery_count": 1,
                "failed_count": 1,
                "target_address_version": 2,
            },
        )

        second = validate_success(
            api.get_update_order(bundle["second_order"]["id"], ADMIN)
        )
        assert_field_values(
            second,
            {
                "status": "FAILED_CLOSED",
                "failed_count": 1,
                "target_address_version": 3,
            },
        )

        credential = validate_success(
            api.get_credential(bundle["credential"]["id"], ADMIN)
        )
        assert_field_values(
            credential,
            {
                "sync_state": "STALE",
                "failed_delivery_count": 2,
                "lifecycle_state": "SUSPENDED",
                "suspend_reason": "UPDATE_FAILED",
                "doc_version": 1,
            },
        )

        holder = validate_success(api.get_holder(bundle["holder"]["id"], ADMIN))
        assert holder["active_credential_count"] == 0


class TestConsentDenialBranch:
    """A refusal still records the over-asking, and still bills nothing."""

    def test_denial_logs_the_excess_and_leaves_every_money_field_alone(self, api):
        """The resident says no: the excess element count reaches the log while the
        reader application's query count and the verifier's balance stay at zero.

        PRD 3.8: "`DENY` moves `CONSENT_PENDING -> DENIED_BY_HOLDER` and appends a
        log entry with `outcome` `DENIED_BY_HOLDER`, `disclosed_element_count`
        zero, `excess_element_count` copied from the session's own excess count,
        `billed_amount_cents` zero and `billing_state` `UNBILLED`. The verifier's
        `open_session_count` decrements by 1. Nothing is billed and the reader
        application's `query_count` does not move."

        Design: Corner/state_machines/consent_deny_branch_logs_excess_without_billing
        """
        world = create_presentation_ready_world(
            api,
            verifier_overrides={
                "organization_name": "Prairie Cellars",
                "category": "AGE_RESTRICTED_RETAIL",
                "purpose_scope": ["family_name", "age_over_21"],
                "retention_ceiling_days": 30,
            },
            reader_app_overrides={
                "app_identifier": "till-a",
                "certificate_serial": "SER-A1",
                "requested_elements": ["family_name", "age_over_21", "address"],
                "base_rate_cents": 30,
            },
        )
        session = open_presentation_session(
            api,
            world,
            requested_elements=["family_name", "age_over_21", "address"],
            purpose="age check at till",
            handset_handling="NO_SURRENDER",
            retention_days=7,
        )

        denied = validate_success(
            api.consent_presentation(
                session["id"],
                {"consent_decision": "DENY"},
                make_holder_headers(world["holder"]["id"]),
            )
        )
        assert_field_values(
            denied,
            {
                "state": "DENIED_BY_HOLDER",
                "minimized_elements": ["family_name", "age_over_21"],
                "withheld_elements": ["address"],
                "excess_element_count": 1,
                "disclosed_element_count": 0,
                "billed_amount_cents": 0,
                "billing_state": "UNBILLED",
            },
        )

        entries = assert_row_count(
            api.list_presentation_log_entries(session["id"], PRIVACY_AUDITOR), 1
        )
        assert_field_values(
            entries[0],
            {
                "outcome": "DENIED_BY_HOLDER",
                "excess_element_count": 1,
                "disclosed_element_count": 0,
                "billing_state": "UNBILLED",
            },
        )

        verifier = validate_success(api.get_verifier(world["verifier"]["id"], ADMIN))
        assert_field_values(
            verifier,
            {
                "open_session_count": 0,
                "billable_query_balance_cents": 0,
                "exposure_index": 0,
            },
        )

        apps = rows_of(
            api.list_verifier_reader_apps(world["verifier"]["id"], ADMIN)
        )
        assert apps[0]["query_count"] == 0
