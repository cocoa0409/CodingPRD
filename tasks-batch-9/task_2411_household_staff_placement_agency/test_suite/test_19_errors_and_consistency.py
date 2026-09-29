"""The error catalogue by entity, the error envelope, and immediate consistency.

The not-found probes walk the whole read surface with one unknown identifier and
insist on eleven distinct answers; the consistency tests insist that a cascade is
readable in the response that caused it.
"""
from test_helpers import (
    BILLING,
    CASE_OPENER,
    CONSULTANT,
    NON_EXISTENT_UUID,
    PRINCIPAL,
    RECORDER,
    api_client,
    confirm_start_payload,
    create_candidate_payload,
    create_onboarded_household,
    ledger_adjustment_payload,
    read_candidate,
    read_client,
    read_ledger,
    read_milestones,
    read_placement,
    read_requisition,
    read_trial,
    set_clock,
    setup_pending_offer,
    setup_scenario,
    start_trial_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestNotFoundIsKeyedOnTheAddressedEntity:
    def test_01_the_search_side_reads_each_report_their_own_not_found(self):
        """One unknown identifier, four read paths, four different answers.

        PRD §2.11: "**Referential resolution, in three steps.** An unresolvable
        path identifier yields that entity's not-found error; then an unresolvable
        body identifier yields the same per-entity catalogue; then rows that
        resolve but do not belong together yield
        `ERR_ENTITY_RELATIONSHIP_MISMATCH`."

        PRD §5: "Every refusal returns the error envelope defined in §2.2 with one
        of the identifiers below in `data.error_id`."

        Design: Corner/errors/unknown_fee_schedule_requisition_candidate_and_trial_ids_return_their_own_not_found_ids
        """
        set_clock("2026-08-01T00:00:00Z")

        validate_error(
            api_client.get_fee_schedule(NON_EXISTENT_UUID, PRINCIPAL),
            "ERR_FEE_SCHEDULE_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_requisition(NON_EXISTENT_UUID, CONSULTANT),
            "ERR_REQUISITION_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_candidate(NON_EXISTENT_UUID, RECORDER),
            "ERR_CANDIDATE_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_trial_engagement(NON_EXISTENT_UUID, CONSULTANT),
            "ERR_TRIAL_NOT_FOUND",
            404,
        )

    def test_02_the_vetting_and_billing_reads_each_report_their_own_not_found(self):
        """Each of these rows is only reachable through its own top-level path.

        PRD §2.11: "**Referential resolution, in three steps.** An unresolvable
        path identifier yields that entity's not-found error; then an unresolvable
        body identifier yields the same per-entity catalogue; then rows that
        resolve but do not belong together yield
        `ERR_ENTITY_RELATIONSHIP_MISMATCH`."

        Design: Corner/errors/unknown_reference_background_term_and_milestone_ids_return_their_own_not_found_ids
        """
        set_clock("2026-08-01T00:00:00Z")

        validate_error(
            api_client.get_reference_check(NON_EXISTENT_UUID, RECORDER),
            "ERR_REFERENCE_CHECK_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_background_verification(NON_EXISTENT_UUID, RECORDER),
            "ERR_BACKGROUND_VERIFICATION_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_accommodation_term(NON_EXISTENT_UUID, CONSULTANT),
            "ERR_ACCOMMODATION_TERM_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_fee_milestone(NON_EXISTENT_UUID, BILLING),
            "ERR_FEE_MILESTONE_NOT_FOUND",
            404,
        )

    def test_03_the_remedial_reads_answer_404_to_a_permitted_caller(self):
        """Each caller is on the endpoint's authorised list, so 403 is excluded.

        PRD §2.11: "**Referential resolution, in three steps.** An unresolvable
        path identifier yields that entity's not-found error; then an unresolvable
        body identifier yields the same per-entity catalogue; then rows that
        resolve but do not belong together yield
        `ERR_ENTITY_RELATIONSHIP_MISMATCH`."

        PRD §4: "A role absent from an endpoint's authorized list receives
        `ERR_UNAUTHORIZED` (HTTP 403) even when its request would otherwise be
        valid."

        Design: Corner/errors/unknown_claim_handoff_and_case_ids_return_their_own_not_found_ids
        """
        set_clock("2026-08-01T00:00:00Z")

        validate_error(
            api_client.get_replacement_claim(NON_EXISTENT_UUID, PRINCIPAL),
            "ERR_REPLACEMENT_CLAIM_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_payroll_handoff(NON_EXISTENT_UUID, CASE_OPENER),
            "ERR_PAYROLL_HANDOFF_NOT_FOUND",
            404,
        )
        validate_error(
            api_client.get_non_solicitation_case(NON_EXISTENT_UUID, CASE_OPENER),
            "ERR_NON_SOLICITATION_CASE_NOT_FOUND",
            404,
        )


class TestTheErrorEnvelope:
    def test_04_a_refusal_carries_the_declared_error_envelope(self):
        """The failure body is asserted field by field, meta block included.

        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/errors/the_error_envelope_for_a_missing_required_field_carries_the_declared_shape
        """
        set_clock("2026-08-01T00:00:00Z")

        payload = create_candidate_payload(
            full_name="Q. Ashe",
            contact_email="qashe@mail.example",
            primary_role_type="CHAUFFEUR",
        )
        payload.pop("years_experience")

        response = api_client.create_candidate(payload, RECORDER)
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_INVALID_REQUEST"
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"].strip() != ""
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)

        _, meta = validate_paginated(api_client.list_candidates(RECORDER))
        assert meta["total_count"] == 0

    def test_05_starting_a_running_trial_names_the_state_it_needed(self):
        """The start edge leaves only SCHEDULED behind it, so the answer is
        state-specific.

        PRD §3.4: "The engagement must be `SCHEDULED`, and any other non-terminal
        state is refused with `ERR_TRIAL_NOT_SCHEDULED`; a `PASSED`, `FAILED` or
        `CANCELLED` engagement is refused with `ERR_ENTITY_TERMINAL`. The logical
        clock must be at or after `start_at`, and an earlier clock is refused with
        `ERR_TRIAL_NOT_STARTED`."

        Design: Corner/errors/starting_a_trial_that_is_already_running_returns_trial_not_scheduled
        """
        scenario = setup_scenario(
            stage="trial_started", trial_end_clock="2026-08-10T09:00:00Z"
        )
        assert read_trial(scenario["trial"])["status"] == "IN_PROGRESS"

        validate_error(
            api_client.start_trial(
                scenario["trial"]["id"], start_trial_payload(), CONSULTANT
            ),
            "ERR_TRIAL_NOT_SCHEDULED",
            409,
        )

        stored = read_trial(scenario["trial"])
        assert stored["status"] == "IN_PROGRESS"
        assert stored["outcome_note"] is None


class TestImmediateConsistency:
    def test_06_the_confirmation_response_already_shows_the_whole_cascade(self):
        """Everything the confirmation recomputes is in its own response body.

        PRD §3.6: "Finally the cascade fans out: the placement moves
        `PENDING_ACCEPTANCE → ACTIVE`, the candidate moves `OFFER_HELD → PLACED`,
        the requisition moves `OFFER_PENDING → PLACED`, and on the household both
        `placement_count` and `non_solicitation_expires_on` are recomputed, the
        latter becoming this `start_date` plus 730 days when this is the
        household's latest placement."

        PRD §2.4: "`version` is an integer that begins at 1 when the row is
        created and increments by exactly 1 on every mutation of that row,
        including mutations reached indirectly through a cascade."

        Design: Corner/consistency_model/the_confirmation_response_already_carries_every_recomputed_value
        """
        scenario = setup_pending_offer()
        set_clock("2026-09-01T00:00:00Z")

        confirmed = validate_success(
            api_client.confirm_placement_start(
                scenario["placement"]["id"], confirm_start_payload(), PRINCIPAL
            )
        )
        assert confirmed["placement_status"] == "ACTIVE"
        assert confirmed["fee_variant"] == "FINAL"
        assert confirmed["fee_cents"] == 2_000_000
        assert confirmed["guarantee_expires_on"] == "2026-11-30"
        assert confirmed["version"] == 2

        reread = read_placement(scenario["placement"])
        assert reread["placement_status"] == "ACTIVE"
        assert reread["fee_variant"] == "FINAL"
        assert reread["fee_cents"] == 2_000_000
        assert reread["guarantee_expires_on"] == "2026-11-30"
        assert reread["version"] == 2

        assert read_requisition(scenario["requisition"])["status"] == "PLACED"
        assert read_candidate(scenario["candidate"])["availability_status"] == "PLACED"

        household = read_client(scenario["client"])
        assert household["placement_count"] == 1
        assert household["non_solicitation_expires_on"] == "2028-08-31"

        milestones = read_milestones(scenario["placement"])
        assert [row["amount_cents"] for row in milestones] == [
            600_000,
            600_000,
            800_000,
        ]

    def test_07_a_credit_movement_shows_on_the_household_in_the_same_breath(self):
        """The balance folds negative in the request that appends the row.

        PRD §2.12: "The invariant is exact and holds after every append: the
        household's `outstanding_balance_cents` equals the sum of
        `signed_amount_cents` across its ledger, and equals the last row's
        `balance_after_cents`."

        Design: Corner/consistency_model/a_negative_ledger_movement_is_visible_on_the_household_at_once
        """
        set_clock("2026-08-01T00:00:00Z")
        household = create_onboarded_household()

        entry = validate_success(
            api_client.create_ledger_adjustment(
                household["id"], ledger_adjustment_payload(-250_000), BILLING
            ),
            201,
        )
        assert entry["signed_amount_cents"] == -250_000
        assert entry["balance_after_cents"] == -250_000

        assert read_client(household)["outstanding_balance_cents"] == -250_000

        entries = read_ledger(household)
        assert len(entries) == 1
        assert entries[0]["sequence_no"] == 1

        _, meta = validate_paginated(
            api_client.list_ledger_entries(household["id"], BILLING)
        )
        assert meta["total_count"] == 1
