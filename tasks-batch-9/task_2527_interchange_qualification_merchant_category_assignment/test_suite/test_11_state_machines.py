"""Lifecycle behaviour: opening states, legal transitions, refused transitions,
terminal lockdown and the restore branches of the audit cascade.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import (
    make_clear_findings_payload,
    make_implementation_window_payload,
    make_reclassification_request_payload,
    make_settlement_batch_payload,
    make_sustain_findings_payload,
    make_transaction_record_payload,
)
from test_helpers.fixtures import (
    add_record,
    board_merchant,
    canonical_environment,
    create_acquirer,
    create_mcc,
    create_platform,
    draft_rate_version,
    file_reclassification,
    finalize_batch,
    open_audit,
    open_batch,
    publish_rate_version,
    read_audit,
    read_batch,
    read_merchant,
    read_record,
    review_reclassification,
    set_clock,
    start_fieldwork,
    submit_batch,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_acquirer_ops_headers,
    make_compliance_auditor_headers,
)

NETWORK_ADMIN = TEST_USERS["network_admin_headers"]
CLOCK = "2026-09-03T00:00:00Z"
CLOCK_STAMP = "2026-09-03T00:00:00.000Z"
PUBLICATION_CLOCK = "2026-09-01T12:00:00Z"
PUBLICATION_STAMP = "2026-09-01T12:00:00.000Z"
TWO_ELEMENTS = ["AUTH_CODE", "TERMINAL_ID"]


def _read_request(request_id, headers=None):
    return validate_success(
        api_client.get_reclassification_request(request_id, headers or NETWORK_ADMIN)
    )


def _batch_with_one_small_ticket_record():
    """One VERIFIED grocery merchant and an OPEN batch holding a single
    1400-cent record carrying `AUTH_CODE` and `TERMINAL_ID`."""
    env = canonical_environment(CLOCK, program_keys=("SMALL_TICKET", "STANDARD"))
    acquirer_id = env["acquirer"]["id"]
    merchant = board_merchant(acquirer_id, "GROCERY", legal_name="Corner Grocer")
    batch = open_batch(acquirer_id, "2026-09-02", "USD")
    record = add_record(
        batch["id"],
        merchant["id"],
        1400,
        acquirer_id,
        expected_batch_version=batch["version"],
        auth_code="A00210",
        auth_timestamp="2026-09-02T00:00:00Z",
        clearing_timestamp="2026-09-02T01:00:00Z",
        data_elements=TWO_ELEMENTS,
    )
    return {
        "acquirer_id": acquirer_id,
        "acquirer_headers": env["acquirer_headers"],
        "merchant": merchant,
        "batch": batch,
        "record": record,
    }


class TestSettlementBatchLifecycle:
    def test_a_freshly_opened_batch_is_empty_and_unfinalized(self):
        """Opening a batch answers with an `OPEN` row whose counters are at rest
        and whose finalization stamp is still absent.

        PRD 3.5: "The batch opens in `status` `OPEN` with `record_count` 0,
        `total_assessed_cents` 0 and `finalized_at` null."

        PRD 3.5: "Its lifecycle is linear: `OPEN → SUBMITTED → FINALIZED`, and
        `FINALIZED` is terminal."

        Design: Corner/state_machines/state_machine_initial_state_settlement_batch_starts_open_with_zero_totals
        """
        set_clock(CLOCK)
        platform = create_platform()
        acquirer = create_acquirer(platform["id"])

        response = api_client.create_settlement_batch(
            make_settlement_batch_payload(acquirer["id"], "2026-09-02", "USD"),
            make_acquirer_ops_headers(acquirer["id"]),
        )
        assert response.status_code == 201
        batch = validate_success(response, 201)
        assert batch["status"] == "OPEN"
        assert batch["record_count"] == 0
        assert batch["total_assessed_cents"] == 0
        assert batch["finalized_at"] is None
        assert batch["version"] == 1

    def test_submitting_closes_intake_without_pricing_anything(self):
        """The submit call moves the batch to `SUBMITTED` and counts its member,
        but no assessment has run: the record is still `PENDING` at zero cents and
        its authorization dimension has not moved.

        PRD 3.5: "Submitting the batch advances it `OPEN → SUBMITTED`, after which
        no further records may be added, and advances `SettlementBatch.version` by
        1."

        PRD 3.5: "Neither figure is ever posted to any ledger:
        `qualification_status` stays `PENDING`, `assessed_interchange_cents` stays
        at its default of 0, and neither the batch total nor the merchant's
        lifetime figure moves."

        Design: Corner/state_machines/state_machine_valid_transition_settlement_batch_open_to_submitted
        """
        state = _batch_with_one_small_ticket_record()

        response = api_client.submit_settlement_batch(
            state["batch"]["id"], state["acquirer_headers"]
        )
        assert response.status_code == 200
        submitted = validate_success(response)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["record_count"] == 1
        assert submitted["total_assessed_cents"] == 0

        stored = read_record(state["record"]["id"])
        assert stored["qualification_status"] == "PENDING"
        assert stored["assessed_interchange_cents"] == 0
        assert stored["authorization_status"] == "AUTH_APPROVED"

    def test_a_submitted_batch_refuses_a_further_record_with_its_own_code(self):
        """Intake against a batch that has left `OPEN` is refused with the
        dedicated batch code rather than the generic state code, and the batch
        keeps the single member it already had.

        PRD 3.5: "Records may only be added while the batch is `OPEN`; an addition
        against a batch in any other status is refused with `ERR_BATCH_NOT_OPEN`."

        PRD 2.9: "The settlement batch receiving a clearing record is in status
        `OPEN` — otherwise `ERR_BATCH_NOT_OPEN` (409)."

        Design: Corner/state_machines/state_machine_invalid_transition_adding_record_to_submitted_batch_is_rejected
        """
        state = _batch_with_one_small_ticket_record()
        submit_batch(state["batch"]["id"], state["acquirer_id"])
        current = read_batch(state["batch"]["id"], state["acquirer_headers"])

        response = api_client.add_transaction_record(
            state["batch"]["id"],
            make_transaction_record_payload(
                state["merchant"]["id"],
                900,
                current["version"],
                auth_code="A00221",
                auth_timestamp="2026-09-02T00:00:00Z",
                clearing_timestamp="2026-09-02T01:00:00Z",
                data_elements=TWO_ELEMENTS,
            ),
            state["acquirer_headers"],
        )
        validate_error(response, "ERR_BATCH_NOT_OPEN", 409)

        after = read_batch(state["batch"]["id"])
        assert after["record_count"] == 1
        assert after["status"] == "SUBMITTED"

        _rows, meta = validate_paginated(
            api_client.list_transaction_records(
                NETWORK_ADMIN, params={"settlement_batch_id": state["batch"]["id"]}
            )
        )
        assert meta["total_count"] == 1

    def test_a_finalized_batch_cannot_be_submitted_again(self):
        """`FINALIZED` is the end of the line: a second submit is refused and the
        finalization stamp is left exactly as the first finalize wrote it.

        PRD 3.5: "Its lifecycle is linear: `OPEN → SUBMITTED → FINALIZED`, and
        `FINALIZED` is terminal."

        PRD 3.6: "On success the batch advances `SUBMITTED → FINALIZED`,
        `finalized_at` is stamped with the current logical-clock instant, and
        `SettlementBatch.version` advances by 1."

        PRD 2.9: "The target resource's own status permits the requested
        transition, and an implementation window being scheduled references a
        `RateProgramVersion` in status `PUBLISHED` — otherwise `ERR_INVALID_STATE`
        (409)."

        Design: Corner/state_machines/state_machine_terminal_lockdown_second_submit_on_finalized_batch_is_rejected
        """
        env = canonical_environment(CLOCK, program_keys=("STANDARD",))
        acquirer_id = env["acquirer"]["id"]
        batch = open_batch(acquirer_id, "2026-09-02", "USD")
        submit_batch(batch["id"], acquirer_id)
        finalized = finalize_batch(batch["id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["finalized_at"] == CLOCK_STAMP

        response = api_client.submit_settlement_batch(
            batch["id"], env["acquirer_headers"]
        )
        validate_error(response, "ERR_INVALID_STATE", 409)

        after = read_batch(batch["id"])
        assert after["status"] == "FINALIZED"
        assert after["finalized_at"] == CLOCK_STAMP


def _quarterly_draft():
    """A CPS_RETAIL program carrying one DRAFT 2026Q4 version, priced 150 bps and
    10 cents, with the implementation deadline one day before the quarter opens."""
    env = canonical_environment(PUBLICATION_CLOCK, program_keys=("CPS_RETAIL",))
    version = draft_rate_version(
        env["programs"]["CPS_RETAIL"]["id"],
        "2026Q4",
        "2026-10-01T00:00:00Z",
        "2027-01-01T00:00:00Z",
        "2026-09-30T00:00:00Z",
        base_rate_bps=150,
        per_item_fee_cents=10,
    )
    env["version"] = version
    return env


class TestPublicationAndSchedulingGates:
    def test_publishing_the_same_version_twice_is_refused(self):
        """Publication is a one-way transition out of `DRAFT`, so the second call
        on the same row is refused and the first publication stamp survives.

        PRD 3.2: "Publishing moves a version `DRAFT → PUBLISHED` and stamps
        `published_at` with the current logical-clock instant."

        PRD 2.9: "The target resource's own status permits the requested
        transition, and an implementation window being scheduled references a
        `RateProgramVersion` in status `PUBLISHED` — otherwise `ERR_INVALID_STATE`
        (409)."

        Design: Corner/state_machines/state_machine_idempotency_publishing_an_already_published_version_is_rejected
        """
        env = _quarterly_draft()
        published = publish_rate_version(env["version"]["id"])
        assert published["status"] == "PUBLISHED"
        assert published["published_at"] == PUBLICATION_STAMP

        response = api_client.publish_rate_program_version(
            env["version"]["id"], NETWORK_ADMIN
        )
        validate_error(response, "ERR_INVALID_STATE", 409)

        stored = validate_success(
            api_client.get_rate_program_version(env["version"]["id"], NETWORK_ADMIN)
        )
        assert stored["status"] == "PUBLISHED"
        assert stored["published_at"] == PUBLICATION_STAMP

    def test_a_window_against_an_unpublished_version_never_reaches_the_envelope_check(self):
        """Scheduling is guarded on the referenced version's own status, and that
        guard sits above the envelope arithmetic, so an unpublished version is
        refused as a state problem and no window row is created.

        PRD 3.2: "Scheduling one records `acquirer_id`, the acquirer that must
        implement; `rate_program_version_id`, the published version being
        implemented, which must be in status `PUBLISHED` or the request is refused
        with `ERR_INVALID_STATE`; `platform_id`, the platform whose capacity the
        window occupies; and `window_start` and `window_end`, which are both
        **inclusive** — this interval is closed, the opposite convention to the rate
        version interval above."

        PRD 3.2: "A drafted version is created in `status` `DRAFT` with
        `published_at` null, and the same program may not carry two versions for the
        same `publication_quarter`."

        PRD 2.9: "The implementation window lies inside its rate version's
        publication-to-deadline envelope: `window_start` is at or after the
        version's `published_at` and `window_end` is at or before the version's
        `implementation_deadline`, both bounds inclusive — otherwise
        `ERR_IMPLEMENTATION_WINDOW_OUT_OF_BOUNDS` (422)."

        Design: Corner/state_machines/state_machine_guarded_transition_window_against_draft_rate_version_is_rejected
        """
        env = _quarterly_draft()

        response = api_client.create_implementation_window(
            make_implementation_window_payload(
                env["acquirer"]["id"],
                env["version"]["id"],
                env["platform"]["id"],
                "2026-09-05T00:00:00Z",
                "2026-09-10T00:00:00Z",
            ),
            env["acquirer_headers"],
        )
        error = validate_error(response, "ERR_INVALID_STATE", 409)
        assert error["error_id"] != "ERR_IMPLEMENTATION_WINDOW_OUT_OF_BOUNDS"

        stored = validate_success(
            api_client.get_rate_program_version(env["version"]["id"], NETWORK_ADMIN)
        )
        assert stored["status"] == "DRAFT"
        assert stored["published_at"] is None

        _rows, meta = validate_paginated(
            api_client.list_implementation_windows(
                NETWORK_ADMIN, params={"platform_id": env["platform"]["id"]}
            )
        )
        assert meta["total_count"] == 0


def _grocery_merchant_under_a_scheduled_audit():
    """A VERIFIED grocery merchant with a periodic audit still in `SCHEDULED`,
    opened by auditor CA-1, in a directory that also defines gambling."""
    env = canonical_environment(CLOCK, mcc_codes=("5411", "7995"), program_keys=())
    acquirer_id = env["acquirer"]["id"]
    merchant = board_merchant(acquirer_id, "GROCERY", legal_name="Corner Grocer")
    audit = open_audit(merchant["id"], "PERIODIC", auditor_user_id="CA-1")
    env["acquirer_id"] = acquirer_id
    env["merchant"] = merchant
    env["audit"] = audit
    return env


class TestAuditPreconditionsAndRestoreBranches:
    def test_findings_cannot_be_sustained_before_fieldwork_has_begun(self):
        """The sustain branch is reachable only from `FIELDWORK`, so calling it on
        a scheduled audit is refused, nothing is written onto the audit, and the
        merchant stays under review rather than being declared misrepresented.

        PRD 3.9: "The audit row is created in `status` `SCHEDULED` with
        `auditor_user_id`, `fieldwork_start`, `fieldwork_end`, `correct_mcc`,
        `findings_note` and `closed_by_user_id` all null and
        `penalty_assessed_cents` 0, and `mcc_at_audit_open` snapshots the merchant's
        `assigned_mcc` as it stands at that moment."

        PRD 3.9: "From `FIELDWORK` exactly one of two mutually exclusive branches
        may be taken, and both are reserved to the operator recorded as
        `auditor_user_id`; another auditor attempting either branch is refused with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/state_machine_precondition_sustain_findings_before_fieldwork_is_rejected
        """
        env = _grocery_merchant_under_a_scheduled_audit()

        response = api_client.sustain_audit_findings(
            env["audit"]["id"],
            make_sustain_findings_payload(
                "7995", findings_note="Premature sustain attempt"
            ),
            make_compliance_auditor_headers("CA-1"),
        )
        validate_error(response, "ERR_INVALID_STATE", 409)

        audit = read_audit(env["audit"]["id"])
        assert audit["status"] == "SCHEDULED"
        assert audit["correct_mcc"] is None
        assert audit["penalty_assessed_cents"] == 0

        merchant = read_merchant(env["merchant"]["id"])
        assert merchant["mcc_status"] == "UNDER_REVIEW"
        assert merchant["assigned_mcc"] == "5411"

    def test_clearing_the_findings_puts_the_suspended_request_back_where_it_was(self):
        """Clearing is the exact inverse of the suspension the audit imposed: the
        request returns to the status held in its snapshot slot, that slot is
        emptied, the reviewer's identity survives, and the merchant returns to
        `VERIFIED`.

        PRD 3.9: "The audit advances `FIELDWORK → FINDINGS_CLEARED`,
        `penalty_assessed_cents` stays at 0 and `correct_mcc` stays null."

        PRD 3.9: "The merchant's `mcc_status` is restored verbatim from
        `mcc_status_before_review` and that snapshot field is then set back to null:
        a merchant whose snapshot held `VERIFIED` returns `UNDER_REVIEW → VERIFIED`,
        and a merchant whose snapshot held `PENDING_VERIFICATION` returns
        `UNDER_REVIEW → PENDING_VERIFICATION`."

        PRD 3.9: "The merchant's suspended reclassification requests are each
        restored verbatim to the status held in `prior_status_before_suspension`,
        which is then cleared to null."

        Design: Corner/state_machines/state_machine_compensation_clear_findings_restores_suspended_reclassification_request
        """
        env = canonical_environment(CLOCK, mcc_codes=("5411", "7995"), program_keys=())
        acquirer_id = env["acquirer"]["id"]
        merchant = board_merchant(acquirer_id, "GROCERY", legal_name="Corner Grocer")
        request = file_reclassification(
            merchant["id"],
            "7995",
            acquirer_id,
            expected_merchant_version=merchant["version"],
            justification="Gaming line of business added",
        )
        review_reclassification(request["id"], analyst_user_id="CAN-1")
        audit = open_audit(merchant["id"], "RECLASS_SUSPICION", auditor_user_id="CA-1")

        suspended = _read_request(request["id"])
        assert suspended["status"] == "SUSPENDED_PENDING_AUDIT"
        assert suspended["prior_status_before_suspension"] == "UNDER_REVIEW"

        start_fieldwork(
            audit["id"],
            "2026-09-03T09:00:00Z",
            "2026-09-04T17:00:00Z",
            auditor_user_id="CA-1",
        )

        response = api_client.clear_audit_findings(
            audit["id"],
            make_clear_findings_payload(
                findings_note="Category confirmed correct, no misrepresentation"
            ),
            make_compliance_auditor_headers("CA-1"),
        )
        assert response.status_code == 200
        cleared = validate_success(response)
        assert cleared["status"] == "FINDINGS_CLEARED"
        assert cleared["penalty_assessed_cents"] == 0
        assert cleared["correct_mcc"] is None

        restored = _read_request(request["id"])
        assert restored["status"] == "UNDER_REVIEW"
        assert restored["prior_status_before_suspension"] is None
        assert restored["reviewer_user_id"] == "CAN-1"

        after = read_merchant(merchant["id"])
        assert after["mcc_status"] == "VERIFIED"
        assert after["mcc_status_before_review"] is None
        assert after["assigned_mcc"] == "5411"

    def test_clearing_the_findings_restores_an_unverified_merchant_to_pending_verification(self):
        """The restore branch reads the snapshot rather than assuming verification:
        a merchant that was never verified comes back to `PENDING_VERIFICATION`, and
        the verification fields the analyst would have written are still empty.

        PRD 3.9: "The audit row is created in `status` `SCHEDULED` with
        `auditor_user_id`, `fieldwork_start`, `fieldwork_end`, `correct_mcc`,
        `findings_note` and `closed_by_user_id` all null and
        `penalty_assessed_cents` 0, and `mcc_at_audit_open` snapshots the merchant's
        `assigned_mcc` as it stands at that moment."

        PRD 3.9: "The merchant's current `mcc_status` is snapshotted into
        `mcc_status_before_review` — the field holds `PENDING_VERIFICATION`,
        `VERIFIED` or null and nothing else — and the merchant then moves to
        `UNDER_REVIEW`, from either `VERIFIED` or `PENDING_VERIFICATION`."

        PRD 3.9: "The merchant's `mcc_status` is restored verbatim from
        `mcc_status_before_review` and that snapshot field is then set back to null:
        a merchant whose snapshot held `VERIFIED` returns `UNDER_REVIEW → VERIFIED`,
        and a merchant whose snapshot held `PENDING_VERIFICATION` returns
        `UNDER_REVIEW → PENDING_VERIFICATION`."

        PRD 3.3: "Three further fields open null and stay null until the workflows
        that own them run: `mcc_status_before_review`, the snapshot slot an audit
        uses; `documentation_ref`; and `verified_by_user_id`."

        Design: Corner/state_machines/state_machine_conditional_cascade_clear_findings_restores_pending_verification_not_verified
        """
        env = canonical_environment(CLOCK, mcc_codes=("4900",), program_keys=())
        merchant = board_merchant(
            env["acquirer"]["id"], "UTILITY_SERVICE", legal_name="Riverside Power"
        )
        assert merchant["mcc_status"] == "PENDING_VERIFICATION"

        audit = open_audit(merchant["id"], "PERIODIC", auditor_user_id="CA-1")
        assert audit["mcc_at_audit_open"] == "4900"
        assert (
            read_merchant(merchant["id"])["mcc_status_before_review"]
            == "PENDING_VERIFICATION"
        )

        start_fieldwork(
            audit["id"],
            "2026-09-03T09:00:00Z",
            "2026-09-04T17:00:00Z",
            auditor_user_id="CA-1",
        )
        response = api_client.clear_audit_findings(
            audit["id"],
            make_clear_findings_payload(
                findings_note="Utility classification is correct"
            ),
            make_compliance_auditor_headers("CA-1"),
        )
        assert response.status_code == 200
        assert validate_success(response)["status"] == "FINDINGS_CLEARED"

        after = read_merchant(merchant["id"])
        assert after["mcc_status"] == "PENDING_VERIFICATION"
        assert after["mcc_status"] != "VERIFIED"
        assert after["mcc_status_before_review"] is None
        assert after["documentation_ref"] is None
        assert after["verified_by_user_id"] is None


class TestSupersessionOnRefiling:
    def test_filing_a_second_request_supersedes_the_live_one(self):
        """The new request opens in `SUBMITTED` at round 1 while the earlier live
        request is closed off as `SUPERSEDED` with no decision recorded, and the
        merchant's own category is untouched by either filing.

        PRD 3.4: "Any earlier request on the same merchant that is still live —
        meaning its `status` is `SUBMITTED`, `UNDER_REVIEW` or `INFO_REQUESTED` — is
        moved to `SUPERSEDED` by the system as the new one is created, and the new
        request opens in `SUBMITTED` with `review_round` 1."

        PRD 3.4: "Creating it advances `Merchant.version` by 1, which is why a
        client that files two requests in a row must re-read the merchant in
        between."

        Design: Corner/state_machines/state_machine_cross_entity_new_reclassification_request_supersedes_the_open_one
        """
        env = canonical_environment(CLOCK, mcc_codes=("5411", "7995"), program_keys=())
        acquirer_id = env["acquirer"]["id"]
        create_mcc(
            "5311",
            "DEPARTMENT_STORE",
            description="Department Stores",
            program_eligibility=[],
        )
        merchant = board_merchant(acquirer_id, "GROCERY", legal_name="Corner Grocer")
        first = file_reclassification(
            merchant["id"],
            "7995",
            acquirer_id,
            expected_merchant_version=merchant["version"],
            justification="Gaming line of business added",
        )
        assert first["review_round"] == 1
        observed_version = read_merchant(merchant["id"], env["acquirer_headers"])[
            "version"
        ]

        response = api_client.create_reclassification_request(
            make_reclassification_request_payload(
                merchant["id"],
                "5311",
                observed_version,
                justification="Correction: general merchandise, not gaming",
            ),
            env["acquirer_headers"],
        )
        assert response.status_code == 201
        second = validate_success(response, 201)
        assert second["status"] == "SUBMITTED"
        assert second["requested_mcc"] == "5311"
        assert second["review_round"] == 1

        superseded = _read_request(first["id"])
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["decided_mcc"] is None

        _rows, meta = validate_paginated(
            api_client.list_reclassification_requests(
                NETWORK_ADMIN, params={"merchant_id": merchant["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert read_merchant(merchant["id"])["assigned_mcc"] == "5411"
