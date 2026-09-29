"""What a write derives is already true for the read that follows it.

Each write below is followed immediately by reads of every row it touched, so a
counter that is only reconciled later would be caught by the very next request.
"""

from test_helpers import (
    CT_OUTCOME_ACCEPTED,
    CT_OUTCOME_REJECTED,
    FIRST_SERIAL_NUMBER,
    LIFECYCLE_ISSUED,
    LOG_OPERATOR_CLOUDFLARE_NIMBUS,
    LOG_OPERATOR_GOOGLE_ARGON,
    REQUEST_ISSUED,
    REVOCATION_STATUS_NONE,
    VALIDATION_TYPE_DV,
    advance_clock,
    assert_append_only_identity,
    assert_certificate_dimensions,
    assert_counters,
    assert_instant_equals,
    build_environment,
    cleared_request,
    ct_submission_payload,
    get_success_data,
    ids_of,
    issuance_charge_cents,
    issue_certificate,
    issue_payload,
    plus_days,
    profile_payload,
    read_ceremony,
    read_certificate,
    read_request,
    read_subscriber,
    subscriber_payload,
    users,
    validate_paginated,
    validate_success,
)

WINDOW_END = "2026-08-01T00:30:00Z"
BASE_FEE_CENTS = 20000


def _dv_estate(client, **profile_overrides):
    """A DV estate with ample credit, ready to issue at the window close."""
    return build_environment(
        client,
        profile_payload=profile_payload(
            base_fee_cents=BASE_FEE_CENTS, **profile_overrides
        ),
        subscriber_payload=subscriber_payload(credit_limit_cents=500_000),
    )


def _issue_one(client, environment):
    """Clear one request and issue against it, returning both rows."""
    request = cleared_request(
        client,
        environment.subscriber_id,
        environment.profile_id,
        ("d1.example.org",),
    )
    certificate = get_success_data(
        client.issue_certificate(
            request["id"],
            issue_payload(environment.ceremony_id),
            users.ISSUANCE_OPERATOR_9,
        ),
        201,
    )
    return request, certificate


def _submit(client, certificate_id, log_operator, outcome, rejection_reason=None):
    return get_success_data(
        client.submit_ct_log(
            certificate_id,
            ct_submission_payload(log_operator, outcome, rejection_reason),
            users.ISSUANCE_OPERATOR,
        ),
        201,
    )


class TestTheIssuanceDebitAndItsCountersAreVisibleAtOnce:
    def test_a_the_settlement_total_lands_on_the_ledger_immediately(self, client):
        """The 201 body and the next subscriber read agree on the same money.

        PRD 3.7: "`charged_amount_cents` is the settlement total, computed at
        issuance by exactly the same six-step tiered calculation described in
        §3.5 that produced `projected_charge_cents`."
        PRD 3.7: "Issuance then debits the subscriber:
        `outstanding_balance_cents` rises by `charged_amount_cents` and
        `issued_certificate_count` rises by one, with the subscriber's `version`
        incrementing."
        PRD 3.7: "The new record carries `lifecycle_status` `PREISSUANCE` and
        `revocation_status` `NONE`, a fresh `serial_number` taken as the previous
        serial plus one (the very first certificate the system ever issues being
        `"1000001"`), the `request_id` of the originating request, and
        `subscriber_id` and `profile_id` copied from it, along with the
        `ceremony_id` and any `supersedes_certificate_id` supplied in the body."

        Design: Corner/consistency_model/the_issuance_debit_and_every_derived_counter_are_visible_in_the_same_instant
        """
        environment = _dv_estate(client, required_sct_count=0)
        before = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            before, outstanding_balance_cents=0, issued_certificate_count=0
        )

        request, certificate = _issue_one(client, environment)

        expected_charge = issuance_charge_cents(BASE_FEE_CENTS, VALIDATION_TYPE_DV, 1)
        assert expected_charge == 20000, (
            f"a single-domain DV issuance at a 20000 base fee settles at 20000, "
            f"the formula gives {expected_charge}"
        )
        assert certificate["charged_amount_cents"] == expected_charge, (
            f"charged_amount_cents is {certificate['charged_amount_cents']}, "
            f"expected {expected_charge} in the issuance response itself"
        )
        assert certificate["serial_number"] == FIRST_SERIAL_NUMBER, (
            f"serial_number is {certificate['serial_number']!r}, "
            f"expected {FIRST_SERIAL_NUMBER!r}"
        )

        # The debit is not deferred: the read that follows the write sees it.
        after = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            after,
            outstanding_balance_cents=expected_charge,
            issued_certificate_count=1,
        )
        assert after["version"] == before["version"] + 1, (
            f"the debit bumps the subscriber once, from version "
            f"{before['version']} to {after['version']}"
        )
        # The same figure is readable on the certificate, not only in the 201.
        stored = read_certificate(client, certificate["id"])
        assert stored["charged_amount_cents"] == expected_charge, (
            f"the stored charge is {stored['charged_amount_cents']}, "
            f"expected {expected_charge}"
        )
        assert stored["request_id"] == request["id"]

    def test_b_the_request_link_and_the_ceremony_tally_are_current(self, client):
        """Both rows the issuance touched read back updated on the next request.

        PRD 3.7: "The originating request moves `READY_TO_ISSUE → ISSUED`, its
        `issued_certificate_id` is set to the new certificate, and its `version`
        increments."
        PRD 3.7: "The signing ceremony's `issued_certificate_count` increments by
        one."
        PRD 2.4: "`version` is an integer that begins at 1 when the resource is
        created and increases by exactly one on every mutation of that resource,
        whether the mutation was requested directly by a client or applied
        indirectly by a cascade."

        Design: Corner/consistency_model/the_issuance_debit_and_every_derived_counter_are_visible_in_the_same_instant
        """
        environment = _dv_estate(client, required_sct_count=0)
        ceremony_before = read_ceremony(client, environment.ceremony_id)
        assert_counters(ceremony_before, issued_certificate_count=0)

        request, certificate = _issue_one(client, environment)

        settled = read_request(client, request["id"])
        assert settled["state"] == REQUEST_ISSUED, (
            f"state is {settled['state']!r}, expected {REQUEST_ISSUED!r}"
        )
        assert settled["issued_certificate_id"] == certificate["id"], (
            f"issued_certificate_id is {settled['issued_certificate_id']!r}, "
            f"expected {certificate['id']!r}"
        )
        assert settled["version"] == request["version"] + 1, (
            f"the issuance bumps the request once, from version "
            f"{request['version']} to {settled['version']}"
        )

        ceremony_after = read_ceremony(client, environment.ceremony_id)
        assert_counters(ceremony_after, issued_certificate_count=1)
        assert ceremony_after["version"] == ceremony_before["version"] + 1, (
            f"the tally is a mutation of the ceremony, so its version moves from "
            f"{ceremony_before['version']} to {ceremony_after['version']}"
        )

    def test_c_the_final_validity_window_is_readable_in_the_same_instant(self, client):
        """The window is computed at issuance, not on first inspection.

        PRD 3.7: "`not_before` is the logical clock at issuance."
        PRD 3.7: "`not_after` is the earliest of those three."
        PRD 3.7: "`validity_days_final` is then the number of whole days in the
        final window: the total seconds from `not_before` to `not_after` divided
        by 86,400 seconds per day, with any fraction discarded downward."

        Design: Corner/consistency_model/the_issuance_debit_and_every_derived_counter_are_visible_in_the_same_instant
        """
        environment = _dv_estate(client, required_sct_count=0)
        _, certificate = _issue_one(client, environment)

        # The profile cap is 90 days and the attestation cap 60, so the binding
        # candidate is the authorization floor, 30 days past the window close.
        expected_not_after = plus_days(WINDOW_END, 30)
        assert_instant_equals(certificate["not_before"], WINDOW_END, "not_before")
        assert_instant_equals(
            certificate["not_after"], expected_not_after, "not_after"
        )
        assert certificate["validity_days_final"] == 30, (
            f"validity_days_final is {certificate['validity_days_final']}, "
            f"expected 30 whole days"
        )

        stored = read_certificate(client, certificate["id"])
        assert_instant_equals(stored["not_before"], WINDOW_END, "not_before")
        assert_instant_equals(stored["not_after"], expected_not_after, "not_after")
        assert stored["validity_days_final"] == 30, (
            f"the stored validity_days_final is {stored['validity_days_final']}, "
            f"expected 30"
        )


class TestTheSctCounterIsCurrentOnTheNextRead:
    def test_a_the_first_acceptance_counts_and_the_duplicate_does_not(self, client):
        """One log accepted twice raises the count once and only once.

        PRD 3.7: "`counted_toward_sct` on a new submission is true only when its
        `outcome` is `ACCEPTED` and no earlier submission for the same
        certificate and the same `log_operator` was already `ACCEPTED`."
        PRD 3.7: "The certificate's `sct_count` is then recomputed as the number
        of distinct `log_operator` values that have ever returned `ACCEPTED` for
        it, so a second acceptance from a log already represented raises nothing,
        and a `REJECTED` submission neither raises nor lowers the count."
        PRD 3.7: "Recording a submission increments the certificate's `version`."

        Design: Corner/consistency_model/a_denormalised_sct_counter_is_current_on_the_next_read_and_ignores_duplicates
        """
        environment = _dv_estate(client, required_sct_count=2)
        certificate = issue_certificate(client, environment)
        assert certificate["sct_count"] == 0, (
            f"a fresh certificate starts at 0 SCTs, found {certificate['sct_count']}"
        )

        first = _submit(
            client,
            certificate["id"],
            LOG_OPERATOR_GOOGLE_ARGON,
            CT_OUTCOME_ACCEPTED,
        )
        assert first["counted_toward_sct"] is True, (
            "the first acceptance from a log is the one that counts"
        )
        after_first = read_certificate(client, certificate["id"])
        assert after_first["sct_count"] == 1, (
            f"sct_count is {after_first['sct_count']}, expected 1 on the read "
            f"immediately after the acceptance"
        )
        assert after_first["version"] == certificate["version"] + 1, (
            f"version is {after_first['version']}, expected "
            f"{certificate['version'] + 1}"
        )

        duplicate = _submit(
            client,
            certificate["id"],
            LOG_OPERATOR_GOOGLE_ARGON,
            CT_OUTCOME_ACCEPTED,
        )
        assert duplicate["counted_toward_sct"] is False, (
            "the same log accepting twice is already represented"
        )
        after_duplicate = read_certificate(client, certificate["id"])
        assert after_duplicate["sct_count"] == 1, (
            f"sct_count is {after_duplicate['sct_count']}, expected to stay 1 "
            f"because the operator is not a new distinct log"
        )
        assert after_duplicate["version"] == certificate["version"] + 2, (
            f"version is {after_duplicate['version']}, expected "
            f"{certificate['version'] + 2}: recording a submission is a mutation "
            f"even when it counts for nothing"
        )

    def test_b_a_rejection_neither_raises_nor_lowers_the_running_count(self, client):
        """A refused log leaves the count alone; its later acceptance raises it.

        PRD 3.7: "The certificate's `sct_count` is then recomputed as the number
        of distinct `log_operator` values that have ever returned `ACCEPTED` for
        it, so a second acceptance from a log already represented raises nothing,
        and a `REJECTED` submission neither raises nor lowers the count."
        PRD 3.7: "`counted_toward_sct` on a new submission is true only when its
        `outcome` is `ACCEPTED` and no earlier submission for the same
        certificate and the same `log_operator` was already `ACCEPTED`."

        Design: Corner/consistency_model/a_denormalised_sct_counter_is_current_on_the_next_read_and_ignores_duplicates
        """
        environment = _dv_estate(client, required_sct_count=2)
        certificate = issue_certificate(client, environment)
        _submit(
            client,
            certificate["id"],
            LOG_OPERATOR_GOOGLE_ARGON,
            CT_OUTCOME_ACCEPTED,
        )

        rejected = _submit(
            client,
            certificate["id"],
            LOG_OPERATOR_CLOUDFLARE_NIMBUS,
            CT_OUTCOME_REJECTED,
            "unknown issuer chain",
        )
        assert rejected["counted_toward_sct"] is False, (
            "a rejection never counts toward the requirement"
        )
        assert rejected["rejection_reason"] == "unknown issuer chain", (
            f"rejection_reason is {rejected['rejection_reason']!r}, expected the "
            f"cause the log reported"
        )
        after_rejection = read_certificate(client, certificate["id"])
        assert after_rejection["sct_count"] == 1, (
            f"sct_count is {after_rejection['sct_count']}, expected to stay 1 "
            f"across a rejection"
        )

        accepted = _submit(
            client,
            certificate["id"],
            LOG_OPERATOR_CLOUDFLARE_NIMBUS,
            CT_OUTCOME_ACCEPTED,
        )
        assert accepted["counted_toward_sct"] is True, (
            "the earlier submission from this log was rejected, not accepted, so "
            "this acceptance is the log's first"
        )
        after_acceptance = read_certificate(client, certificate["id"])
        assert after_acceptance["sct_count"] == 2, (
            f"sct_count is {after_acceptance['sct_count']}, expected 2 distinct "
            f"accepting logs"
        )

    def test_c_activation_reads_the_same_count_the_client_just_read(self, client):
        """The counter the read reported is the counter the gate compares.

        PRD 3.7: "Finally `sct_count` must be at least the profile's
        `required_sct_count`; the comparison is inclusive, so a count exactly
        equal to the requirement passes, while anything lower is refused with
        `ERR_INSUFFICIENT_SCTS`."
        PRD 3.7: "Activation is the final step: an `ISSUANCE_OPERATOR` moves the
        certificate `PREISSUANCE → ISSUED`, which is what makes it publicly
        usable."
        PRD 3.7: "Activation stamps `activated_at` with the logical clock and
        increments the certificate's `version`."

        Design: Corner/consistency_model/a_denormalised_sct_counter_is_current_on_the_next_read_and_ignores_duplicates
        """
        environment = _dv_estate(client, required_sct_count=2)
        certificate = issue_certificate(client, environment)
        _submit(
            client, certificate["id"], LOG_OPERATOR_GOOGLE_ARGON, CT_OUTCOME_ACCEPTED
        )
        _submit(
            client, certificate["id"], LOG_OPERATOR_GOOGLE_ARGON, CT_OUTCOME_ACCEPTED
        )
        _submit(
            client,
            certificate["id"],
            LOG_OPERATOR_CLOUDFLARE_NIMBUS,
            CT_OUTCOME_REJECTED,
            "unknown issuer chain",
        )
        _submit(
            client,
            certificate["id"],
            LOG_OPERATOR_CLOUDFLARE_NIMBUS,
            CT_OUTCOME_ACCEPTED,
        )

        before = read_certificate(client, certificate["id"])
        assert before["sct_count"] == 2, (
            f"sct_count is {before['sct_count']}, expected exactly the required 2"
        )

        activated = validate_success(
            client.activate_certificate(certificate["id"], users.ISSUANCE_OPERATOR),
            200,
        )
        assert_certificate_dimensions(
            activated, LIFECYCLE_ISSUED, REVOCATION_STATUS_NONE
        )
        assert_instant_equals(activated["activated_at"], WINDOW_END, "activated_at")
        assert activated["version"] == before["version"] + 1, (
            f"version is {activated['version']}, expected {before['version'] + 1}"
        )
        assert activated["sct_count"] == 2, (
            f"activation does not disturb the counter, found {activated['sct_count']}"
        )

    def test_d_every_submission_is_readable_in_recording_order(self, client):
        """The ignored submissions are kept too, each stamped and immutable.

        PRD 2.3: "A certificate's transparency-log submissions are returned in
        ascending `created_at` order."
        PRD 3.7: "The submission's `certificate_id` comes from the certificate it
        is recorded against, `sct_timestamp` is stamped with the logical clock,
        and the record is immutable thereafter — it carries `id` and `created_at`
        and no `updated_at` or `version` of its own."
        PRD 3.7: "`counted_toward_sct` on a new submission is true only when its
        `outcome` is `ACCEPTED` and no earlier submission for the same
        certificate and the same `log_operator` was already `ACCEPTED`."

        Design: Corner/consistency_model/a_denormalised_sct_counter_is_current_on_the_next_read_and_ignores_duplicates
        """
        environment = _dv_estate(client, required_sct_count=2)
        certificate = issue_certificate(client, environment)

        # One submission per instant, so the recording order is unambiguous.
        recorded = []
        recorded.append(
            _submit(
                client,
                certificate["id"],
                LOG_OPERATOR_GOOGLE_ARGON,
                CT_OUTCOME_ACCEPTED,
            )
        )
        advance_clock(client, "2026-08-01T01:00:00Z")
        recorded.append(
            _submit(
                client,
                certificate["id"],
                LOG_OPERATOR_GOOGLE_ARGON,
                CT_OUTCOME_ACCEPTED,
            )
        )
        advance_clock(client, "2026-08-01T01:30:00Z")
        recorded.append(
            _submit(
                client,
                certificate["id"],
                LOG_OPERATOR_CLOUDFLARE_NIMBUS,
                CT_OUTCOME_REJECTED,
                "unknown issuer chain",
            )
        )
        advance_clock(client, "2026-08-01T02:00:00Z")
        recorded.append(
            _submit(
                client,
                certificate["id"],
                LOG_OPERATOR_CLOUDFLARE_NIMBUS,
                CT_OUTCOME_ACCEPTED,
            )
        )

        stamps = [WINDOW_END] + [
            "2026-08-01T01:00:00Z",
            "2026-08-01T01:30:00Z",
            "2026-08-01T02:00:00Z",
        ]
        for submission, stamp in zip(recorded, stamps):
            assert_append_only_identity(submission)
            assert submission["certificate_id"] == certificate["id"], (
                f"certificate_id is {submission['certificate_id']!r}, expected "
                f"{certificate['id']!r}"
            )
            assert_instant_equals(submission["sct_timestamp"], stamp, "sct_timestamp")

        rows, meta = validate_paginated(
            client.list_ct_submissions(certificate["id"], users.ISSUANCE_OPERATOR)
        )
        assert meta["total_count"] == 4, (
            f"all four submissions are kept, found {meta['total_count']}"
        )
        assert ids_of(rows) == ids_of(recorded), (
            "the submissions read back oldest first, in the order they were "
            f"recorded: {ids_of(rows)} against {ids_of(recorded)}"
        )
        assert [row["counted_toward_sct"] for row in rows] == [
            True,
            False,
            False,
            True,
        ], (
            "only the first acceptance from each distinct log counts, found "
            f"{[row['counted_toward_sct'] for row in rows]}"
        )
        assert read_certificate(client, certificate["id"])["sct_count"] == 2, (
            "two distinct logs ever accepted, so the counter is 2"
        )
