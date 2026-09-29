"""Declared initial states, terminal states, and the doors they close.

Each aggregate in the CA is born in one specific state and refuses the acts that
belong to other states. These tests walk the compound vetting machine, the
attempt-limited domain challenge, the finite return loop, the ceremony quorum,
and the two exits from a revocation request.
"""

from test_helpers import (
    AUDIT_SCHEDULED,
    AUTH_EXHAUSTED,
    AUTH_FAILED,
    AUTH_PENDING,
    CEREMONY_ABORTED,
    CEREMONY_SCHEDULED,
    CEREMONY_WITNESSED,
    CHECK_FAILED,
    CHECK_NOT_STARTED,
    CHECK_PASSED,
    CLOCK_EPOCH,
    CT_OUTCOME_ACCEPTED,
    CT_OUTCOME_REJECTED,
    DEFAULT_WINDOW_END,
    DIMENSION_CALLBACK,
    DIMENSION_REGISTRY,
    ERR_AUTHORIZATION_NOT_VALIDATABLE,
    ERR_CEREMONY_NOT_ABORTABLE,
    ERR_CEREMONY_NOT_SCHEDULED,
    ERR_CEREMONY_NOT_WITNESSED,
    ERR_DUPLICATE_WITNESS,
    ERR_PROFILE_NOT_DRAFT,
    ERR_REQUEST_NOT_DRAFT,
    ERR_REQUEST_NOT_REJECTABLE,
    ERR_REQUEST_NOT_SUBMITTED,
    ERR_VETTING_ALREADY_DECIDED,
    ERR_VETTING_NOT_AWAITING_APPROVAL,
    INCIDENT_OPEN,
    LIFECYCLE_ISSUED,
    LOG_OPERATOR_CLOUDFLARE_NIMBUS,
    LOG_OPERATOR_GOOGLE_ARGON,
    ORIGIN_SUBSCRIBER,
    PARTITION_OPERATIONAL,
    POSTURE_NOMINAL,
    PROFILE_STATE_ACTIVE,
    REASON_AFFILIATION_CHANGED,
    REQUEST_DRAFT,
    REQUEST_REJECTED,
    REQUEST_SUBMITTED,
    REVOCATION_DENIED,
    REVOCATION_REQUESTED,
    REVOCATION_STATUS_NONE,
    REVOCATION_STATUS_PENDING,
    SUBSCRIBER_ACTIVE,
    VETTING_APPROVED,
    VETTING_AWAITING_APPROVAL,
    VETTING_IN_PROGRESS,
    VETTING_LEVEL_OV,
    VETTING_PENDING,
    VETTING_REJECTED,
    abort_payload,
    advance_clock,
    assert_counters,
    assert_instant_equals,
    assert_modifiable_identity,
    assert_nulls,
    check_payload,
    create_authorization,
    create_partition,
    create_profile,
    create_request,
    create_subscriber,
    ct_submission_payload,
    denial_payload,
    get_success_data,
    ids_of,
    issue_certificate,
    open_audit,
    open_incident,
    profile_payload,
    raise_revocation,
    read_authorization,
    read_ceremony,
    read_certificate,
    read_partition,
    read_profile,
    read_request,
    read_revocation,
    read_subscriber,
    reject_payload,
    return_payload,
    revocation_deadline_at,
    schedule_ceremony,
    users,
    validate_error,
    validate_paginated,
    validate_payload,
    vetting_payload,
)


def _open_vetting(client, subscriber_id, required_level=VETTING_LEVEL_OV):
    """One vetting file, freshly opened and still untouched."""
    return get_success_data(
        client.open_vetting(
            subscriber_id, vetting_payload(required_level), users.VALIDATION_OFFICER
        ),
        201,
    )


def _record(client, vetting_id, dimension, outcome, officer=None):
    """Record one check dimension and hand back the raw response."""
    return client.record_check(
        vetting_id,
        check_payload(dimension, outcome),
        officer or users.VALIDATION_OFFICER,
    )


def _attempt(client, authorization_id, token):
    """One challenge attempt, which the PRD answers 200 either way."""
    return get_success_data(
        client.validate_authorization(
            authorization_id, validate_payload(token), users.VALIDATION_OFFICER
        )
    )


class TestDeclaredInitialStates:
    def test_a_vetting_file_and_subscriber_start_untouched(self, client):
        """A registered subscriber is ACTIVE and its first file is PENDING.

        PRD 3.2: "Registration puts the account in `account_status` `ACTIVE` with
        `outstanding_balance_cents`, `issued_certificate_count`,
        `revocation_pending_count` and `risk_score_operational` all at 0,
        `risk_score_audit_final` null until the first audit opinion covers the
        subscriber, and `suspended_at` null."
        PRD 3.3: "The file begins in `vetting_state` `PENDING` with all three
        check dimensions at `NOT_STARTED` and `approved_at`,
        `approved_by_user_id` and `rejected_at` all null."

        Design: Corner/state_machines/every_entity_is_created_in_its_declared_initial_state
        """
        subscriber = create_subscriber(client)
        assert subscriber["account_status"] == SUBSCRIBER_ACTIVE, (
            f"a new subscriber is ACTIVE, found {subscriber['account_status']!r}"
        )
        assert_counters(
            subscriber,
            outstanding_balance_cents=0,
            issued_certificate_count=0,
            revocation_pending_count=0,
            risk_score_operational=0,
        )
        assert_nulls(subscriber, "risk_score_audit_final", "suspended_at")
        assert_modifiable_identity(subscriber, expected_version=1)

        vetting = _open_vetting(client, subscriber["id"])
        assert vetting["vetting_state"] == VETTING_PENDING, (
            f"a new vetting file is PENDING, found {vetting['vetting_state']!r}"
        )
        assert_counters(
            vetting,
            registry_check_status=CHECK_NOT_STARTED,
            callback_check_status=CHECK_NOT_STARTED,
            authority_check_status=CHECK_NOT_STARTED,
        )
        assert_nulls(vetting, "approved_at", "approved_by_user_id", "rejected_at")
        assert vetting["subscriber_id"] == subscriber["id"], (
            "the file takes its subscriber_id from the path, found "
            f"{vetting['subscriber_id']!r}"
        )
        assert_modifiable_identity(vetting, expected_version=1)

    def test_b_authorization_partition_and_ceremony_start_untouched(self, client):
        """A challenge, a partition and a ceremony all start at zero.

        PRD 3.4: "Creation mints a `challenge_token` — a server-generated value,
        deterministic per authorization, which is returned in the response and
        which the applicant must echo back — and initialises `state` to `PENDING`
        with `attempt_count`, `reuse_count` and `invalidation_count` all at 0 and
        `validated_at`, `expires_at` and `invalidated_at` all null."
        PRD 3.6: "The partition starts in `state` `OPERATIONAL` with
        `quarantined_at` null and `attested_ceremony_count` at 0."
        PRD 3.6: "A new ceremony starts in `SCHEDULED` with `witness_user_ids` an
        empty array, `witness_count` at 0, `issued_certificate_count` at 0, and
        `attested_at`, `attested_by_user_id`, `attestation_expires_at` and
        `attestation_revoked_at` all null."

        Design: Corner/state_machines/every_entity_is_created_in_its_declared_initial_state
        """
        profile = create_profile(client)
        subscriber = create_subscriber(client)

        authorization = create_authorization(
            client, subscriber["id"], profile["id"], "initial.example.org"
        )
        assert authorization["state"] == AUTH_PENDING, (
            f"a new challenge is PENDING, found {authorization['state']!r}"
        )
        assert_counters(
            authorization, attempt_count=0, reuse_count=0, invalidation_count=0
        )
        assert_nulls(authorization, "validated_at", "expires_at", "invalidated_at")
        assert isinstance(authorization["challenge_token"], str), (
            "creation must mint a challenge_token, found "
            f"{authorization['challenge_token']!r}"
        )
        assert authorization["challenge_token"], "the minted token must not be empty"

        partition = create_partition(client)
        assert partition["state"] == PARTITION_OPERATIONAL, (
            f"a new partition is OPERATIONAL, found {partition['state']!r}"
        )
        assert_counters(partition, attested_ceremony_count=0)
        assert_nulls(partition, "quarantined_at")

        ceremony = schedule_ceremony(client, partition["id"])
        assert ceremony["state"] == CEREMONY_SCHEDULED, (
            f"a new ceremony is SCHEDULED, found {ceremony['state']!r}"
        )
        assert ceremony["witness_user_ids"] == [], (
            f"no witnesses yet, found {ceremony['witness_user_ids']!r}"
        )
        assert_counters(ceremony, witness_count=0, issued_certificate_count=0)
        assert_nulls(
            ceremony,
            "attested_at",
            "attested_by_user_id",
            "attestation_expires_at",
            "attestation_revoked_at",
        )

    def test_c_incident_and_audit_start_untouched(self, client):
        """A misissuance incident opens OPEN and an audit opens SCHEDULED.

        PRD 3.9: "The incident is born in `state` `OPEN` with
        `disclosure_breached` false, `disclosed_at` and `closed_at` null, and
        `revoked_certificate_count`, `remaining_scope_count` and
        `penalty_total_cents` all initialised to 0."
        PRD 3.9: "The audit is born in `state` `SCHEDULED` with `finding_count`,
        `critical_finding_count`, `assessed_subscriber_count` and
        `retired_profile_count` all 0 and `opinion_at` and `opined_by_user_id`
        null."

        Design: Corner/state_machines/every_entity_is_created_in_its_declared_initial_state
        """
        profile = create_profile(client)

        incident = open_incident(client, profile["id"])
        assert incident["state"] == INCIDENT_OPEN, (
            f"a new incident is OPEN, found {incident['state']!r}"
        )
        assert incident["disclosure_breached"] is False, (
            "the deadline cannot be breached at the discovery instant, found "
            f"{incident['disclosure_breached']!r}"
        )
        assert_nulls(incident, "disclosed_at", "closed_at")
        assert_counters(
            incident,
            revoked_certificate_count=0,
            remaining_scope_count=0,
            penalty_total_cents=0,
        )

        audit = open_audit(client)
        assert audit["state"] == AUDIT_SCHEDULED, (
            f"a new audit is SCHEDULED, found {audit['state']!r}"
        )
        assert_counters(
            audit,
            finding_count=0,
            critical_finding_count=0,
            assessed_subscriber_count=0,
            retired_profile_count=0,
        )
        assert_nulls(audit, "opinion_at", "opined_by_user_id")


class TestCompoundVettingMachine:
    def test_a_two_passed_dimensions_open_the_door_for_the_approver(self, client):
        """An OV file awaits approval with AUTHORITY still NOT_STARTED.

        PRD 3.3: "A `PASSED` result on a dimension that was still `NOT_STARTED`,
        recorded while at least one required dimension remains `NOT_STARTED`
        afterwards, moves the file `PENDING → IN_PROGRESS`. A `PASSED` result
        that leaves every dimension required by `required_level` at `PASSED`
        moves the file `IN_PROGRESS → AWAITING_APPROVAL`; for an `OV` file this
        fires as soon as the registry and callback dimensions are both `PASSED`,
        even while `authority_check_status` is still `NOT_STARTED`."
        PRD 3.3: "Recording stamps that dimension's status and writes the acting
        `X-User-ID` into the matching `registry_checked_by_user_id`,
        `callback_checked_by_user_id` or `authority_checked_by_user_id`, and
        increments the file's `version`."
        PRD 3.3: "Approval moves the file `AWAITING_APPROVAL → APPROVED`, stamps
        `approved_at` with the logical clock and `approved_by_user_id` with the
        approver's `X-User-ID`, and increments `version`."

        Design: Corner/state_machines/ov_vetting_reaches_awaiting_approval_on_two_dimensions_and_is_then_approved
        """
        subscriber = create_subscriber(client)
        vetting = _open_vetting(client, subscriber["id"])

        after_registry = get_success_data(
            _record(client, vetting["id"], DIMENSION_REGISTRY, CHECK_PASSED)
        )
        assert after_registry["vetting_state"] == VETTING_IN_PROGRESS, (
            "one of two required dimensions leaves the file IN_PROGRESS, found "
            f"{after_registry['vetting_state']!r}"
        )
        assert_counters(
            after_registry,
            registry_check_status=CHECK_PASSED,
            registry_checked_by_user_id=users.USER_VALIDATION_OFFICER,
        )
        assert after_registry["version"] == 2, (
            f"recording a check increments version to 2, found {after_registry['version']}"
        )

        after_callback = get_success_data(
            _record(client, vetting["id"], DIMENSION_CALLBACK, CHECK_PASSED)
        )
        assert after_callback["vetting_state"] == VETTING_AWAITING_APPROVAL, (
            "both OV dimensions passed, so the file awaits approval, found "
            f"{after_callback['vetting_state']!r}"
        )
        assert_counters(
            after_callback,
            callback_check_status=CHECK_PASSED,
            callback_checked_by_user_id=users.USER_VALIDATION_OFFICER,
            authority_check_status=CHECK_NOT_STARTED,
        )
        assert_nulls(after_callback, "authority_checked_by_user_id", "approved_at")

        approved = get_success_data(
            client.approve_vetting(vetting["id"], users.VETTING_APPROVER)
        )
        assert approved["vetting_state"] == VETTING_APPROVED, (
            f"approval lands in APPROVED, found {approved['vetting_state']!r}"
        )
        assert approved["approved_by_user_id"] == users.USER_VETTING_APPROVER, (
            "approved_by_user_id is the approver's X-User-ID, found "
            f"{approved['approved_by_user_id']!r}"
        )
        assert_instant_equals(approved["approved_at"], CLOCK_EPOCH, "approved_at")
        assert approved["version"] == 4, (
            "two checks and one approval lift version 1 to 4, found "
            f"{approved['version']}"
        )
        assert_nulls(approved, "rejected_at")

    def test_b_approval_before_the_last_required_dimension_is_refused(self, client):
        """One passed dimension is not a quorum for the approver.

        PRD 3.3: "A `VETTING_APPROVER` approves a file that is in
        `AWAITING_APPROVAL` — any other state is refused with
        `ERR_VETTING_NOT_AWAITING_APPROVAL` — and the approving `X-User-ID` must
        differ from every non-null value among the three `*_checked_by_user_id`
        fields, or the approval is refused with `ERR_VETTING_SOD_VIOLATION`."
        PRD 3.3: "A `PASSED` result on a dimension that was still `NOT_STARTED`,
        recorded while at least one required dimension remains `NOT_STARTED`
        afterwards, moves the file `PENDING → IN_PROGRESS`."

        Design: Corner/state_machines/approval_before_the_last_required_dimension_passes_is_rejected
        """
        subscriber = create_subscriber(client)
        vetting = _open_vetting(client, subscriber["id"])
        get_success_data(_record(client, vetting["id"], DIMENSION_REGISTRY, CHECK_PASSED))

        response = client.approve_vetting(vetting["id"], users.VETTING_APPROVER)
        validate_error(response, ERR_VETTING_NOT_AWAITING_APPROVAL)
        assert response.status_code == 409, (
            f"a wrong-state approval is a 409, found {response.status_code}"
        )

        settled = get_success_data(
            client.get_vetting(vetting["id"], users.VALIDATION_OFFICER)
        )
        assert settled["vetting_state"] == VETTING_IN_PROGRESS, (
            "the refused approval must leave the file IN_PROGRESS, found "
            f"{settled['vetting_state']!r}"
        )
        assert_nulls(settled, "approved_at", "approved_by_user_id")
        assert settled["version"] == 2, (
            f"a refused approval writes nothing, found version {settled['version']}"
        )

    def test_c_one_failed_required_dimension_closes_the_file(self, client):
        """A failed callback rejects the whole file and locks later checks.

        PRD 3.3: "A `FAILED` result on any dimension that `required_level`
        requires drives the whole file to the terminal `REJECTED` state and
        stamps `rejected_at` with the logical clock — and it does so from
        `PENDING`, from `IN_PROGRESS`, and even from `AWAITING_APPROVAL`, where it
        overwrites a dimension that had already been recorded `PASSED`."
        PRD 3.3: "Recording is only permitted while the file is still open,
        meaning `vetting_state` is `PENDING`, `IN_PROGRESS` or
        `AWAITING_APPROVAL`; a file already `APPROVED` or `REJECTED` rejects any
        further check with `ERR_VETTING_ALREADY_DECIDED`."
        PRD 3.3: "Recording stamps that dimension's status and writes the acting
        `X-User-ID` into the matching `registry_checked_by_user_id`,
        `callback_checked_by_user_id` or `authority_checked_by_user_id`, and
        increments the file's `version`."

        Design: Corner/state_machines/failed_required_dimension_rejects_the_vetting_file_and_locks_further_checks
        """
        subscriber = create_subscriber(client)
        vetting = _open_vetting(client, subscriber["id"])

        rejected = get_success_data(
            _record(client, vetting["id"], DIMENSION_CALLBACK, CHECK_FAILED)
        )
        assert rejected["vetting_state"] == VETTING_REJECTED, (
            "a failed required dimension rejects the file straight from PENDING, "
            f"found {rejected['vetting_state']!r}"
        )
        assert_counters(
            rejected,
            callback_check_status=CHECK_FAILED,
            callback_checked_by_user_id=users.USER_VALIDATION_OFFICER,
            registry_check_status=CHECK_NOT_STARTED,
        )
        assert_instant_equals(rejected["rejected_at"], CLOCK_EPOCH, "rejected_at")
        assert rejected["version"] == 2, (
            f"the recorded check increments version to 2, found {rejected['version']}"
        )

        response = _record(client, vetting["id"], DIMENSION_REGISTRY, CHECK_PASSED)
        validate_error(response, ERR_VETTING_ALREADY_DECIDED)
        assert response.status_code == 409, (
            f"a decided file refuses further checks with 409, found {response.status_code}"
        )

        settled = get_success_data(
            client.get_vetting(vetting["id"], users.VALIDATION_OFFICER)
        )
        assert settled["registry_check_status"] == CHECK_NOT_STARTED, (
            "the refused check must not be stamped, found "
            f"{settled['registry_check_status']!r}"
        )
        assert settled["version"] == 2, (
            f"a refused check writes nothing, found version {settled['version']}"
        )
        assert settled["vetting_state"] == VETTING_REJECTED, "REJECTED is terminal"


class TestProfileActivationIsOnceOnly:
    def test_a_second_activation_is_refused_and_changes_nothing(self, client):
        """ACTIVE is not DRAFT, so the second activation is a 409.

        PRD 3.1: "Activation by a `POLICY_ADMIN` moves it `DRAFT → ACTIVE`; the
        profile must actually be in `DRAFT` (a second activation attempt earns
        `ERR_PROFILE_NOT_DRAFT`), and the tier consistency condition must hold,
        meaning the profile is either a `DV` profile or one whose
        `org_vetting_reuse_days` is at least 1 — a condition the creation-time
        range check already guarantees."
        PRD 3.1: "Activation stamps `activated_at` with the logical clock and
        increments the profile's `version`."

        Design: Corner/state_machines/activating_an_already_active_profile_is_rejected_as_not_draft
        """
        drafted = create_profile(client, profile_payload(), activate=False)
        activated = get_success_data(
            client.activate_profile(drafted["id"], users.POLICY_ADMIN)
        )
        assert activated["status"] == PROFILE_STATE_ACTIVE, (
            f"the first activation succeeds, found {activated['status']!r}"
        )
        assert_instant_equals(activated["activated_at"], CLOCK_EPOCH, "activated_at")
        assert activated["version"] == 2, (
            f"activation lifts version 1 to 2, found {activated['version']}"
        )

        advance_clock(client, "2026-08-02T00:00:00Z")
        response = client.activate_profile(drafted["id"], users.POLICY_ADMIN)
        validate_error(response, ERR_PROFILE_NOT_DRAFT)
        assert response.status_code == 409, (
            f"a second activation is a 409, found {response.status_code}"
        )

        settled = read_profile(client, drafted["id"])
        assert settled["status"] == PROFILE_STATE_ACTIVE, (
            f"the profile stays ACTIVE, found {settled['status']!r}"
        )
        assert_instant_equals(
            settled["activated_at"], CLOCK_EPOCH, "activated_at after the refusal"
        )
        assert settled["version"] == 2, (
            f"the refused activation writes nothing, found version {settled['version']}"
        )


class TestRequestReturnLoopIsFinite:
    def test_a_the_third_return_rejects_instead_of_returning(self, client):
        """Two bounces are allowed; the third return is a rejection.

        PRD 3.5: "While `return_count` is below 2, the return moves the request
        `SUBMITTED → DRAFT` and increments `return_count` — so the request may
        bounce `SUBMITTED → DRAFT → SUBMITTED` twice. When `return_count` is
        already exactly 2, the third return is not a return at all: it drives
        `return_count` to 3, moves the request to the terminal `REJECTED` state,
        and copies the supplied `return_reason` value into the request's
        `rejected_reason`. The endpoint still answers 200 with the request in
        `REJECTED`, not an error."
        PRD 3.5: "Submission moves the request `DRAFT → SUBMITTED` and stamps
        `submitted_at` with the logical clock."

        Design: Corner/state_machines/request_return_cycle_terminates_in_rejection_on_the_third_return
        """
        profile = create_profile(client)
        subscriber = create_subscriber(client)
        request = create_request(client, subscriber["id"], profile["id"])
        assert request["state"] == REQUEST_DRAFT, (
            f"a new request is DRAFT, found {request['state']!r}"
        )

        submitted = get_success_data(
            client.submit_request(request["id"], users.VALIDATION_OFFICER)
        )
        assert submitted["state"] == REQUEST_SUBMITTED, (
            f"submission moves the request to SUBMITTED, found {submitted['state']!r}"
        )
        assert_instant_equals(submitted["submitted_at"], CLOCK_EPOCH, "submitted_at")

        for expected_count in (1, 2):
            returned = get_success_data(
                client.return_request(
                    request["id"],
                    return_payload(f"more evidence needed, round {expected_count}"),
                    users.VALIDATION_OFFICER,
                )
            )
            assert returned["state"] == REQUEST_DRAFT, (
                f"return {expected_count} bounces the request back to DRAFT, found "
                f"{returned['state']!r}"
            )
            assert_counters(returned, return_count=expected_count)
            assert_nulls(returned, "rejected_reason")
            get_success_data(
                client.submit_request(request["id"], users.VALIDATION_OFFICER)
            )

        third_reason = "the applicant never produced the missing evidence"
        response = client.return_request(
            request["id"], return_payload(third_reason), users.VALIDATION_OFFICER
        )
        final = get_success_data(response)
        assert response.status_code == 200, (
            f"the third return still answers 200, found {response.status_code}"
        )
        assert final["state"] == REQUEST_REJECTED, (
            f"the third return rejects the request, found {final['state']!r}"
        )
        assert_counters(final, return_count=3)
        assert final["rejected_reason"] == third_reason, (
            "the return_reason is copied into rejected_reason, found "
            f"{final['rejected_reason']!r}"
        )


class TestRejectedRequestIsTerminal:
    def _rejected_request(self, client):
        """One SUBMITTED request driven to the terminal REJECTED state."""
        profile = create_profile(client)
        subscriber = create_subscriber(client)
        request = create_request(client, subscriber["id"], profile["id"])
        get_success_data(client.submit_request(request["id"], users.VALIDATION_OFFICER))
        rejected = get_success_data(
            client.reject_request(
                request["id"],
                reject_payload("the organisation could not be vetted at all"),
                users.VALIDATION_OFFICER,
            )
        )
        assert rejected["state"] == REQUEST_REJECTED, (
            f"a rejected SUBMITTED request becomes REJECTED, found {rejected['state']!r}"
        )
        return rejected

    def test_a_a_rejected_request_can_be_neither_resubmitted_nor_rejected_again(
        self, client
    ):
        """REJECTED is not DRAFT and no longer rejectable.

        PRD 3.5: "The request must be in `DRAFT`, or the attempt is refused with
        `ERR_REQUEST_NOT_DRAFT`, and both the subscriber and the profile must be
        `ACTIVE`."
        PRD 3.5: "Outright rejection is the other exit. It carries a
        `rejected_reason` and is permitted only while the request is `DRAFT` or
        `SUBMITTED`, otherwise `ERR_REQUEST_NOT_REJECTABLE`. The destination
        state depends on where the request was: a `SUBMITTED` request becomes
        `REJECTED`, while a `DRAFT` request — on which no validation work was
        performed — becomes `WITHDRAWN` instead. Both are terminal, and both
        stamp `rejected_reason` from the body."

        Design: Corner/state_machines/rejected_request_is_locked_against_every_further_lifecycle_action
        """
        rejected = self._rejected_request(client)
        reason = rejected["rejected_reason"]

        response = client.submit_request(rejected["id"], users.VALIDATION_OFFICER)
        validate_error(response, ERR_REQUEST_NOT_DRAFT)

        response = client.reject_request(
            rejected["id"], reject_payload("a second opinion"), users.VALIDATION_OFFICER
        )
        validate_error(response, ERR_REQUEST_NOT_REJECTABLE)

        settled = read_request(client, rejected["id"])
        assert settled["state"] == REQUEST_REJECTED, "REJECTED is terminal"
        assert settled["rejected_reason"] == reason, (
            "the original rejected_reason must survive, found "
            f"{settled['rejected_reason']!r}"
        )
        assert_nulls(settled, "issued_certificate_id")

    def test_b_a_rejected_request_can_be_neither_returned_nor_cleared(self, client):
        """Both acts that need a SUBMITTED request are refused.

        PRD 3.5: "Returning a request requires a `return_reason` and requires the
        request to be `SUBMITTED`, or `ERR_REQUEST_NOT_SUBMITTED` is raised."
        PRD 3.5: "A `VALIDATION_OFFICER` clears a `SUBMITTED` request
        (`ERR_REQUEST_NOT_SUBMITTED` otherwise), with the subscriber and profile
        both `ACTIVE`, and the operation takes no input fields at all: everything
        it needs is already on the request."

        Design: Corner/state_machines/rejected_request_is_locked_against_every_further_lifecycle_action
        """
        rejected = self._rejected_request(client)

        response = client.return_request(
            rejected["id"],
            return_payload("please send the registry extract"),
            users.VALIDATION_OFFICER,
        )
        validate_error(response, ERR_REQUEST_NOT_SUBMITTED)

        response = client.clear_validation(rejected["id"], users.VALIDATION_OFFICER)
        validate_error(response, ERR_REQUEST_NOT_SUBMITTED)

        settled = read_request(client, rejected["id"])
        assert settled["state"] == REQUEST_REJECTED, "REJECTED is terminal"
        assert_counters(settled, return_count=0)
        assert_nulls(
            settled,
            "validation_cleared_at",
            "validation_cleared_by_user_id",
            "projected_charge_cents",
        )


class TestChallengeAttemptLimit:
    def test_a_three_misses_exhaust_the_challenge_permanently(self, client):
        """Each miss spends an attempt, and the third closes the door.

        PRD 3.4: "When the submitted token does not match, the outcome depends on
        how many attempts have already been spent, and in neither case is the
        response an error: the endpoint answers 200 with the updated
        authorization. If the incremented `attempt_count` is still below 3, the
        authorization lands in `FAILED` — moving `PENDING → FAILED` on the first
        miss and remaining `FAILED → FAILED` on the second. If the incremented
        `attempt_count` reaches exactly 3, the authorization moves
        `FAILED → EXHAUSTED`, which is terminal: an exhausted authorization can
        never be validated, and the operator must open a fresh one."
        PRD 3.4: "Every attempt, successful or not, increments `attempt_count` by
        one and the authorization's `version` by one."
        PRD 3.4: "the authorization must be in `PENDING` or `FAILED` (anything
        else, including an already `VALIDATED`, `EXHAUSTED` or `EXPIRED`
        authorization, is refused with `ERR_AUTHORIZATION_NOT_VALIDATABLE`)"

        Design: Corner/state_machines/dcv_challenge_failures_exhaust_the_authorization_after_three_attempts
        """
        profile = create_profile(client)
        subscriber = create_subscriber(client)
        authorization = create_authorization(
            client, subscriber["id"], profile["id"], "attempts.example.org"
        )
        good_token = authorization["challenge_token"]

        for miss, expected_state in ((1, AUTH_FAILED), (2, AUTH_FAILED), (3, AUTH_EXHAUSTED)):
            after = _attempt(client, authorization["id"], f"not-the-token-{miss}")
            assert after["state"] == expected_state, (
                f"miss {miss} must land in {expected_state}, found {after['state']!r}"
            )
            assert_counters(after, attempt_count=miss, reuse_count=0)
            assert after["version"] == 1 + miss, (
                f"attempt {miss} must increment version to {1 + miss}, "
                f"found {after['version']}"
            )
            assert_nulls(after, "validated_at", "expires_at")

        response = client.validate_authorization(
            authorization["id"], validate_payload(good_token), users.VALIDATION_OFFICER
        )
        validate_error(response, ERR_AUTHORIZATION_NOT_VALIDATABLE)
        assert response.status_code == 409, (
            f"an exhausted challenge answers 409, found {response.status_code}"
        )

        settled = read_authorization(client, authorization["id"])
        assert settled["state"] == AUTH_EXHAUSTED, "EXHAUSTED is terminal"
        assert_counters(settled, attempt_count=3)
        assert settled["version"] == 4, (
            f"the refused attempt writes nothing, found version {settled['version']}"
        )


class TestAbortedCeremonyIsTerminal:
    def _aborted_ceremony(self, client):
        """A partition and one ceremony witnessed once and then abandoned."""
        partition = create_partition(client)
        ceremony = schedule_ceremony(client, partition["id"])
        get_success_data(
            client.witness_ceremony(ceremony["id"], users.ISSUANCE_OPERATOR)
        )
        aborted = get_success_data(
            client.abort_ceremony(
                ceremony["id"],
                abort_payload("the hardware token holder never arrived"),
                users.ISSUANCE_OPERATOR,
            )
        )
        return partition, aborted

    def test_a_an_aborted_ceremony_refuses_witnesses_and_a_second_abort(self, client):
        """ABORTED is neither SCHEDULED nor abortable any more.

        PRD 3.6: "An `ISSUANCE_OPERATOR` aborts a ceremony that is `SCHEDULED` or
        `WITNESSED`, supplying a `reason`; any other state is refused with
        `ERR_CEREMONY_NOT_ABORTABLE`. The abort moves the ceremony to the
        terminal `ABORTED` state, increments its `version`, and frees its
        occupation window so a replacement ceremony may be scheduled over it."
        PRD 3.6: "The ceremony must be `SCHEDULED`, or
        `ERR_CEREMONY_NOT_SCHEDULED` is raised, and the acting `X-User-ID` must
        not already appear in `witness_user_ids`, or `ERR_DUPLICATE_WITNESS` is
        raised."

        Design: Corner/state_machines/aborted_ceremony_is_locked_against_witness_attest_and_a_second_abort
        """
        partition, aborted = self._aborted_ceremony(client)
        assert aborted["state"] == CEREMONY_ABORTED, (
            f"the abort lands in ABORTED, found {aborted['state']!r}"
        )
        assert aborted["version"] == 3, (
            "creation, one witness and the abort make version 3, found "
            f"{aborted['version']}"
        )

        response = client.witness_ceremony(aborted["id"], users.ISSUANCE_OPERATOR_2)
        validate_error(response, ERR_CEREMONY_NOT_SCHEDULED)
        assert response.status_code == 409, (
            f"witnessing an aborted ceremony is a 409, found {response.status_code}"
        )

        response = client.abort_ceremony(
            aborted["id"], abort_payload("try again"), users.ISSUANCE_OPERATOR
        )
        validate_error(response, ERR_CEREMONY_NOT_ABORTABLE)

        settled = read_ceremony(client, aborted["id"])
        assert settled["state"] == CEREMONY_ABORTED, "ABORTED is terminal"
        assert_counters(settled, witness_count=1)
        assert settled["witness_user_ids"] == [users.USER_ISSUANCE_OPERATOR], (
            "the refused witness must not be appended, found "
            f"{settled['witness_user_ids']!r}"
        )
        assert settled["version"] == 3, (
            f"the two refusals write nothing, found version {settled['version']}"
        )
        assert_nulls(settled, "attested_at", "attested_by_user_id")

        stored_partition = read_partition(client, partition["id"])
        assert stored_partition["state"] == PARTITION_OPERATIONAL, (
            f"an abort does not quarantine, found {stored_partition['state']!r}"
        )
        assert_counters(stored_partition, attested_ceremony_count=0)

    def test_b_an_aborted_ceremony_cannot_be_attested_even_after_its_window(
        self, client
    ):
        """With the window closed, only the state check can still refuse.

        PRD 3.6: "A `COMPLIANCE_AUDITOR` attests a ceremony that is `WITNESSED`
        (`ERR_CEREMONY_NOT_WITNESSED` otherwise), whose window has closed — the
        logical clock must be at or after `window_end`, and attesting while the
        window is still open is refused with `ERR_CEREMONY_WINDOW_OPEN` — and
        whose `witness_user_ids` does not contain the attester's own `X-User-ID`,
        since an auditor may not attest a ceremony it witnessed."
        PRD 3.6: "The abort moves the ceremony to the terminal `ABORTED` state,
        increments its `version`, and frees its occupation window so a
        replacement ceremony may be scheduled over it."

        Design: Corner/state_machines/aborted_ceremony_is_locked_against_witness_attest_and_a_second_abort
        """
        partition, aborted = self._aborted_ceremony(client)
        advance_clock(client, DEFAULT_WINDOW_END)

        response = client.attest_ceremony(aborted["id"], users.COMPLIANCE_AUDITOR)
        validate_error(response, ERR_CEREMONY_NOT_WITNESSED)
        assert response.status_code == 409, (
            f"attesting an aborted ceremony is a 409, found {response.status_code}"
        )

        settled = read_ceremony(client, aborted["id"])
        assert settled["state"] == CEREMONY_ABORTED, "ABORTED is terminal"
        assert_nulls(
            settled, "attested_at", "attested_by_user_id", "attestation_expires_at"
        )
        assert settled["version"] == 3, (
            f"the refused attestation writes nothing, found version {settled['version']}"
        )
        stored_partition = read_partition(client, partition["id"])
        assert_counters(stored_partition, attested_ceremony_count=0)


class TestWitnessQuorum:
    def test_a_one_user_cannot_be_both_witnesses(self, client):
        """The same X-User-ID is refused, a distinct second one completes the quorum.

        PRD 3.6: "The ceremony must be `SCHEDULED`, or
        `ERR_CEREMONY_NOT_SCHEDULED` is raised, and the acting `X-User-ID` must
        not already appear in `witness_user_ids`, or `ERR_DUPLICATE_WITNESS` is
        raised."
        PRD 3.6: "The first witness appends its `X-User-ID` to
        `witness_user_ids`, sets `witness_count` to 1, and deliberately leaves
        the ceremony in `SCHEDULED` — one signature is not a quorum. The second,
        distinct witness appends its `X-User-ID`, sets `witness_count` to 2, and
        moves the ceremony `SCHEDULED → WITNESSED`. Both attempts increment the
        ceremony's `version`, and `witness_user_ids` preserves the order in which
        the witnesses were recorded."
        PRD 3.6: "Witnessing is a two-person join, and it is the one act both
        `ISSUANCE_OPERATOR` and `COMPLIANCE_AUDITOR` may perform."

        Design: Corner/state_machines/the_same_user_cannot_witness_a_ceremony_twice
        """
        partition = create_partition(client)
        ceremony = schedule_ceremony(client, partition["id"])

        first = get_success_data(
            client.witness_ceremony(ceremony["id"], users.ISSUANCE_OPERATOR)
        )
        assert first["state"] == CEREMONY_SCHEDULED, (
            f"one signature is not a quorum, found {first['state']!r}"
        )
        assert_counters(first, witness_count=1)
        assert first["witness_user_ids"] == [users.USER_ISSUANCE_OPERATOR], (
            f"the first witness is recorded, found {first['witness_user_ids']!r}"
        )
        assert first["version"] == 2, (
            f"the first witness increments version to 2, found {first['version']}"
        )

        response = client.witness_ceremony(ceremony["id"], users.ISSUANCE_OPERATOR)
        validate_error(response, ERR_DUPLICATE_WITNESS)
        assert response.status_code == 409, (
            f"a repeat witness is a 409, found {response.status_code}"
        )
        unchanged = read_ceremony(client, ceremony["id"])
        assert_counters(unchanged, witness_count=1)
        assert unchanged["version"] == 2, (
            f"the refused witness writes nothing, found version {unchanged['version']}"
        )

        second = get_success_data(
            client.witness_ceremony(ceremony["id"], users.COMPLIANCE_AUDITOR_2)
        )
        assert second["state"] == CEREMONY_WITNESSED, (
            f"two distinct witnesses reach WITNESSED, found {second['state']!r}"
        )
        assert_counters(second, witness_count=2)
        assert second["witness_user_ids"] == [
            users.USER_ISSUANCE_OPERATOR,
            users.USER_COMPLIANCE_AUDITOR_2,
        ], (
            "witness_user_ids preserves the recording order, found "
            f"{second['witness_user_ids']!r}"
        )
        assert second["version"] == 3, (
            f"the second witness increments version to 3, found {second['version']}"
        )


class TestRevocationRequestExits:
    def test_a_denial_releases_the_certificate_and_the_subscriber(
        self, client, dv_environment
    ):
        """REVOCATION_PENDING goes back to NONE and the count returns to zero.

        PRD 3.8: "Raising a request also moves the certificate. Its
        `revocation_status` goes `NONE → REVOCATION_PENDING`, its `version`
        increments, and the owning subscriber's `revocation_pending_count` rises
        by one — which suspends the account the moment that count reaches 2, as
        described in §3.2."
        PRD 3.8: "Denial moves the request to the terminal `DENIED` state, stamps
        `denied_at` with the logical clock and records the `denial_reason`. The
        target certificate returns `REVOCATION_PENDING → NONE`, but only when no
        other revocation request for it remains in `REQUESTED`; the subscriber's
        `revocation_pending_count` decrements by one, un-suspending the account
        once it is below 2. The `version` of the request, the certificate and the
        subscriber all increment."

        Design: Corner/state_machines/denying_a_revocation_request_reverses_every_pending_side_effect
        """
        environment = dv_environment
        certificate = issue_certificate(client, environment)
        assert certificate["version"] == 1, (
            f"a fresh certificate is at version 1, found {certificate['version']}"
        )

        request = raise_revocation(client, certificate, REASON_AFFILIATION_CHANGED)
        pending = read_certificate(client, certificate["id"])
        assert pending["revocation_status"] == REVOCATION_STATUS_PENDING, (
            "raising a request moves the certificate to REVOCATION_PENDING, found "
            f"{pending['revocation_status']!r}"
        )
        assert pending["version"] == 2, (
            f"the certificate's version increments to 2, found {pending['version']}"
        )
        owner = read_subscriber(client, environment.subscriber_id)
        assert_counters(owner, revocation_pending_count=1)
        assert owner["account_status"] == SUBSCRIBER_ACTIVE, (
            f"one pending revocation does not suspend, found {owner['account_status']!r}"
        )

        reason = "the registrant confirmed the key was never exposed"
        denied = get_success_data(
            client.deny_revocation(
                request["id"], denial_payload(reason), users.REVOCATION_OFFICER
            )
        )
        assert denied["state"] == REVOCATION_DENIED, (
            f"denial lands in the terminal DENIED state, found {denied['state']!r}"
        )
        assert denied["denial_reason"] == reason, (
            f"the denial_reason is recorded, found {denied['denial_reason']!r}"
        )
        assert_instant_equals(denied["denied_at"], DEFAULT_WINDOW_END, "denied_at")
        assert_nulls(denied, "executed_at", "superseded_at")

        released = read_certificate(client, certificate["id"])
        assert released["revocation_status"] == REVOCATION_STATUS_NONE, (
            "the only open request was denied, so the certificate returns to NONE, "
            f"found {released['revocation_status']!r}"
        )
        assert_nulls(released, "revoked_at", "revocation_reason_code")
        assert released["version"] == 3, (
            f"the release increments the certificate to version 3, found "
            f"{released['version']}"
        )
        settled_owner = read_subscriber(client, environment.subscriber_id)
        assert_counters(settled_owner, revocation_pending_count=0)
        assert settled_owner["account_status"] == SUBSCRIBER_ACTIVE, (
            f"the account stays ACTIVE, found {settled_owner['account_status']!r}"
        )

    def test_b_a_denied_request_never_reaches_the_revocation_ledger(
        self, client, dv_environment
    ):
        """The request is born REQUESTED with a computed deadline and revokes nothing.

        PRD 3.8: "The presence of the link also decides provenance: `origin` is
        set to `SUBSCRIBER` when `incident_id` is absent and to `COMPLIANCE` when
        it is present. `requested_by_user_id` takes the acting `X-User-ID` and
        `requested_at` the logical clock, and the request is born in `state`
        `REQUESTED` with `deadline_breached` false and `executed_at`, `denied_at`,
        `denial_reason` and `superseded_at` all null."
        PRD 3.8: "The base allowance comes from the reason code: 24 hours for
        `KEY_COMPROMISE` and for `PRIVILEGE_WITHDRAWN`, and 120 hours for
        `AFFILIATION_CHANGED`, `SUPERSEDED`, `CESSATION_OF_OPERATION` and
        `UNSPECIFIED`."
        PRD 3.8: "Hop two: because the certificate became `REVOKED`, the
        governing profile's `revoked_certificate_count` and
        `pending_crl_entry_count` each rise by one."

        Design: Corner/state_machines/denying_a_revocation_request_reverses_every_pending_side_effect
        """
        environment = dv_environment
        certificate = issue_certificate(client, environment)

        request = raise_revocation(client, certificate, REASON_AFFILIATION_CHANGED)
        assert request["state"] == REVOCATION_REQUESTED, (
            f"a new request is REQUESTED, found {request['state']!r}"
        )
        assert request["origin"] == ORIGIN_SUBSCRIBER, (
            f"no incident_id means SUBSCRIBER origin, found {request['origin']!r}"
        )
        assert request["requested_by_user_id"] == users.USER_REVOCATION_OFFICER, (
            "requested_by_user_id takes the acting X-User-ID, found "
            f"{request['requested_by_user_id']!r}"
        )
        assert request["deadline_breached"] is False, (
            f"a new request has not breached, found {request['deadline_breached']!r}"
        )
        assert_nulls(request, "executed_at", "denied_at", "denial_reason", "superseded_at")
        assert_instant_equals(
            request["requested_at"], DEFAULT_WINDOW_END, "requested_at"
        )
        assert_instant_equals(
            request["deadline_at"],
            revocation_deadline_at(DEFAULT_WINDOW_END, REASON_AFFILIATION_CHANGED),
            "deadline_at",
        )

        get_success_data(
            client.deny_revocation(
                request["id"], denial_payload(), users.REVOCATION_OFFICER
            )
        )

        profile = read_profile(client, environment.profile_id)
        assert_counters(
            profile,
            revoked_certificate_count=0,
            pending_crl_entry_count=0,
            total_crl_entries_published=0,
        )
        assert profile["status_service_posture"] == POSTURE_NOMINAL, (
            "no entry was ever queued, so the posture stays NOMINAL, found "
            f"{profile['status_service_posture']!r}"
        )
        settled = read_revocation(client, request["id"])
        assert settled["state"] == REVOCATION_DENIED, "DENIED is terminal"


class TestSctLedger:
    def test_a_submissions_deduplicate_by_log_operator(self, client, dv_environment):
        """Two acceptances from one log count once, and a rejection counts never.

        PRD 3.7: "`counted_toward_sct` on a new submission is true only when its
        `outcome` is `ACCEPTED` and no earlier submission for the same certificate
        and the same `log_operator` was already `ACCEPTED`. The certificate's
        `sct_count` is then recomputed as the number of distinct `log_operator`
        values that have ever returned `ACCEPTED` for it, so a second acceptance
        from a log already represented raises nothing, and a `REJECTED`
        submission neither raises nor lowers the count."
        PRD 3.7: "Finally `sct_count` must be at least the profile's
        `required_sct_count`; the comparison is inclusive, so a count exactly
        equal to the requirement passes, while anything lower is refused with
        `ERR_INSUFFICIENT_SCTS`."
        PRD 3.7: "Activation stamps `activated_at` with the logical clock and
        increments the certificate's `version`."

        Design: Corner/state_machines/ct_submissions_keep_the_certificate_sct_ledger_in_sync
        """
        environment = dv_environment
        certificate = issue_certificate(client, environment)
        assert_counters(certificate, sct_count=0)

        first = get_success_data(
            client.submit_ct_log(
                certificate["id"],
                ct_submission_payload(LOG_OPERATOR_GOOGLE_ARGON, CT_OUTCOME_ACCEPTED),
                users.ISSUANCE_OPERATOR,
            ),
            201,
        )
        assert first["counted_toward_sct"] is True, (
            "the first acceptance from a log counts, found "
            f"{first['counted_toward_sct']!r}"
        )
        assert_counters(read_certificate(client, certificate["id"]), sct_count=1)

        repeat = get_success_data(
            client.submit_ct_log(
                certificate["id"],
                ct_submission_payload(LOG_OPERATOR_GOOGLE_ARGON, CT_OUTCOME_ACCEPTED),
                users.ISSUANCE_OPERATOR,
            ),
            201,
        )
        assert repeat["counted_toward_sct"] is False, (
            "a second acceptance from the same log must not count, found "
            f"{repeat['counted_toward_sct']!r}"
        )
        assert_counters(read_certificate(client, certificate["id"]), sct_count=1)

        refused = get_success_data(
            client.submit_ct_log(
                certificate["id"],
                ct_submission_payload(
                    LOG_OPERATOR_CLOUDFLARE_NIMBUS,
                    CT_OUTCOME_REJECTED,
                    "the log reported an unrecognised issuer chain",
                ),
                users.ISSUANCE_OPERATOR,
            ),
            201,
        )
        assert refused["counted_toward_sct"] is False, (
            f"a rejection never counts, found {refused['counted_toward_sct']!r}"
        )
        assert_counters(read_certificate(client, certificate["id"]), sct_count=1)

        rows, meta = validate_paginated(
            client.list_ct_submissions(certificate["id"], users.ISSUANCE_OPERATOR)
        )
        assert meta["total_count"] == 3, (
            f"every submission is kept, found {meta['total_count']}"
        )
        assert set(ids_of(rows)) == {first["id"], repeat["id"], refused["id"]}, (
            "the listing must return all three submissions"
        )

        activated = get_success_data(
            client.activate_certificate(certificate["id"], users.ISSUANCE_OPERATOR)
        )
        assert activated["lifecycle_status"] == LIFECYCLE_ISSUED, (
            "one distinct accepted log meets a required_sct_count of 1, found "
            f"{activated['lifecycle_status']!r}"
        )
        assert_counters(activated, sct_count=1)
        assert_instant_equals(
            activated["activated_at"], DEFAULT_WINDOW_END, "activated_at"
        )
