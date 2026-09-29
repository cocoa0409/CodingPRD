"""Edges of the household, fee-band, requisition and trial machines.

Each test drives one edge — an entry state, an admitted transition, a refused
one, or a terminal lock — and reads back every row the edge was declared to
touch, so a cascade that only half ran is visible.
"""
from test_helpers import (
    BASE_SCENARIO,
    CONSULTANT,
    PRINCIPAL,
    api_client,
    cancel_trial,
    countersign_agreement_payload,
    create_client_payload,
    create_requisition_payload,
    finalize_scope_payload,
    publish_fee_schedule,
    read_candidate,
    read_client,
    read_requisition,
    read_trial,
    record_trial_outcome_payload,
    retire_fee_schedule,
    scope_requisition_payload,
    set_clock,
    setup_scenario,
    sign_agreement_payload,
    start_trial,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_requisition_payload,
)

TRIAL_START_AT = "2026-08-10T09:00:00Z"


def _sign(scenario):
    return validate_success(
        api_client.confidentiality_agreement(
            scenario["client"]["id"],
            sign_agreement_payload(),
            scenario["client_headers"],
        )
    )


def _countersign(client):
    return api_client.confidentiality_agreement(
        client["id"], countersign_agreement_payload(), PRINCIPAL
    )


class TestHouseholdAgreementMachine:
    def test_01_a_household_enters_on_prospect_and_unsigned(self):
        """Both household dimensions start at their own entry value.

        PRD §3.1: "The new household begins life with `status` `PROSPECT`,
        `confidentiality_agreement_status` `UNSIGNED`, a null `signatory_name`, a
        null `countersigned_at`, `outstanding_balance_cents` of 0,
        `placement_count` of 0, a null `non_solicitation_expires_on` and `version`
        1."

        Design: Corner/state_machines/client_initial_state_is_prospect_with_an_unsigned_agreement
        """
        setup_scenario(stage="clock")

        created = validate_success(
            api_client.create_client(create_client_payload(), CONSULTANT), 201
        )
        assert created["status"] == "PROSPECT"
        assert created["confidentiality_agreement_status"] == "UNSIGNED"

        stored = read_client(created)
        assert stored["status"] == "PROSPECT"
        assert stored["confidentiality_agreement_status"] == "UNSIGNED"

    def test_02_the_countersignature_advances_both_dimensions_at_once(self):
        """One call onboards the household and stamps the clock instant.

        PRD §3.1: "Countersignature advances that field from `SIGNED` to
        `COUNTERSIGNED`, stamps `countersigned_at` with the current logical-clock
        instant, and drives the household lifecycle `PROSPECT → ONBOARDED` — the
        only path by which a household becomes eligible for role scoping —
        incrementing `Client.version` by 1."

        PRD §2.4: "`version` is an integer that begins at 1 when the row is
        created and increments by exactly 1 on every mutation of that row,
        including mutations reached indirectly through a cascade."

        Design: Corner/state_machines/countersigning_the_agreement_onboards_the_household
        """
        scenario = setup_scenario(stage="household")
        signed = _sign(scenario)
        assert signed["confidentiality_agreement_status"] == "SIGNED"
        assert signed["version"] == 2

        data = validate_success(_countersign(scenario["client"]))
        assert data["status"] == "ONBOARDED"
        assert data["confidentiality_agreement_status"] == "COUNTERSIGNED"
        assert data["countersigned_at"].startswith("2026-08-01T00:00:00")
        assert data["signatory_name"] == BASE_SCENARIO["SIGNATORY_NAME"]
        assert data["version"] == 3

    def test_03_countersigning_an_unsigned_agreement_has_no_edge(self):
        """The agreement dimension is still UNSIGNED, so nothing may advance.

        PRD §3.1: "A countersignature attempted while the agreement is still
        `UNSIGNED`, or a second signature on an already-`COUNTERSIGNED` agreement,
        is refused with `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/countersigning_before_the_household_signs_is_an_invalid_transition
        """
        scenario = setup_scenario(stage="household")

        validate_error(
            _countersign(scenario["client"]), "ERR_INVALID_STATE_TRANSITION", 409
        )

        after = read_client(scenario["client"])
        assert after["status"] == "PROSPECT"
        assert after["confidentiality_agreement_status"] == "UNSIGNED"
        assert after["countersigned_at"] is None
        assert after["version"] == 1

    def test_04_a_second_countersignature_is_refused_rather_than_absorbed(self):
        """A repeat is not idempotent: no version bump, no restamp.

        PRD §3.1: "The agency then countersigns: acting as `AgencyPrincipal`, it
        submits an `action` of `COUNTERSIGN`, which is admissible only while
        `confidentiality_agreement_status` is `SIGNED`."

        Design: Corner/state_machines/countersigning_a_second_time_is_refused
        """
        scenario = setup_scenario(stage="onboarded")
        before = read_client(scenario["client"])
        assert before["confidentiality_agreement_status"] == "COUNTERSIGNED"
        assert before["version"] == 3

        validate_error(
            _countersign(scenario["client"]), "ERR_INVALID_STATE_TRANSITION", 409
        )

        after = read_client(scenario["client"])
        assert after["version"] == 3
        assert after["countersigned_at"] == before["countersigned_at"]
        assert after["status"] == "ONBOARDED"


class TestFeeBandRetirement:
    def test_05_retiring_a_retired_band_hits_the_terminal_lock(self):
        """RETIRED accepts no further transition, so the repeat is not a no-op.

        PRD §3.2: "Retirement increments `FeeSchedule.version`, and a second
        retirement attempt on an already-`RETIRED` band is refused with
        `ERR_ENTITY_TERMINAL`."

        Design: Corner/state_machines/retiring_a_fee_band_twice_hits_the_terminal_lock
        """
        setup_scenario(stage="clock")
        band = publish_fee_schedule()
        assert band["status"] == "ACTIVE"
        assert band["version"] == 1

        retired = retire_fee_schedule(band)
        assert retired["status"] == "RETIRED"
        assert retired["version"] == 2

        validate_error(
            api_client.retire_fee_schedule(
                band["id"], {"reason": "Retired again."}, PRINCIPAL
            ),
            "ERR_ENTITY_TERMINAL",
            409,
        )

        after = validate_success(api_client.get_fee_schedule(band["id"], PRINCIPAL))
        assert after["status"] == "RETIRED"
        assert after["version"] == 2

    def test_06_a_retired_band_is_no_longer_in_the_resolution_set(self):
        """Retiring the only covering band empties the candidate set.

        PRD §3.2: "A band may later be retired by the same role, moving it
        `ACTIVE → RETIRED` with an optional `reason`; retirement removes the row
        from every future resolution's candidate set but leaves already-stamped
        references on requisitions and placements untouched, which is what makes
        the snapshots on those rows genuinely pinned."

        PRD §3.2: "When the candidate set is empty the resolution has no result at
        all and the calling operation is refused with `ERR_NO_FEE_SCHEDULE_MATCH`
        (HTTP 422); the most common way to hit this is a compensation figure equal
        to the top band's ceiling when no unbounded band has been published above
        it."

        Design: Corner/state_machines/a_retired_band_leaves_the_resolution_set
        """
        scenario = setup_scenario(stage="scoping")
        assert scenario["requisition"]["status"] == "SCOPING"
        retire_fee_schedule(scenario["fee_schedule"])

        validate_error(
            api_client.finalize_scope(
                scenario["requisition"]["id"], finalize_scope_payload(), CONSULTANT
            ),
            "ERR_NO_FEE_SCHEDULE_MATCH",
            422,
        )

        after = read_requisition(scenario["requisition"])
        assert after["status"] == "SCOPING"
        assert after["resolved_fee_schedule_id"] is None
        assert after["provisional_fee_cents"] is None


class TestRequisitionMachine:
    def test_07_a_requisition_enters_on_draft_with_its_opener_stamped(self):
        """The opening user is recorded, which later audit reads depend on.

        PRD §3.1: "A successfully opened requisition sits in `status` `DRAFT` with
        `scoping_round` 0, `active_trial_count` 0, a null
        `resolved_fee_schedule_id`, `fee_percent_bps`, `guarantee_window_days` and
        `provisional_fee_cents`, `created_by_user_id` stamped from the acting
        `X-User-ID`, and `version` 1."

        Design: Corner/state_machines/requisition_initial_state_is_draft_with_the_opening_user_stamped
        """
        scenario = setup_scenario(stage="onboarded")

        data = validate_success(
            api_client.create_requisition(
                create_requisition_payload(scenario["client"]["id"]), CONSULTANT
            ),
            201,
        )
        assert data["status"] == "DRAFT"
        assert data["scoping_round"] == 0
        assert data["created_by_user_id"] == CONSULTANT["X-User-ID"]

        rows, meta = validate_paginated(
            api_client.list_requisitions(CONSULTANT, {"status": "DRAFT"})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == data["id"]

    def test_08_finalising_an_already_sourcing_requisition_is_refused(self):
        """The finalisation edge leaves SCOPING only, and the snapshot is kept.

        PRD §3.1: "A requisition in any state other than `SCOPING` is refused with
        `ERR_REQUISITION_NOT_SCOPING` (HTTP 409), and a suspended household blocks
        the operation with `ERR_CLIENT_SUSPENDED`."

        Design: Corner/state_machines/finalize_scope_from_sourcing_is_refused
        """
        scenario = setup_scenario(stage="sourcing")
        assert scenario["requisition"]["status"] == "SOURCING"

        validate_error(
            api_client.finalize_scope(
                scenario["requisition"]["id"], finalize_scope_payload(), CONSULTANT
            ),
            "ERR_REQUISITION_NOT_SCOPING",
            409,
        )

        after = read_requisition(scenario["requisition"])
        assert after["status"] == "SOURCING"
        assert after["fee_percent_bps"] == 2000
        assert after["provisional_fee_cents"] == 2_000_000

    def test_09_a_withdrawn_requisition_refuses_even_a_normal_edge(self):
        """The DRAFT → SCOPING edge is unreachable once the row is terminal.

        PRD §2.9: "An action aimed at a row already sitting in a terminal state of
        the machine it would drive is refused with `ERR_ENTITY_TERMINAL` (HTTP
        409)."

        PRD §3.1: "Withdrawal is admissible from `DRAFT`, `SCOPING`, `SOURCING`
        and `TRIALING`, and takes the requisition to `WITHDRAWN`."

        Design: Corner/state_machines/a_withdrawn_requisition_is_locked_against_further_scoping
        """
        scenario = setup_scenario(stage="requisition")
        withdrawn = validate_success(
            api_client.withdraw_requisition(
                scenario["requisition"]["id"],
                withdraw_requisition_payload(reason="Household paused the search."),
                CONSULTANT,
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"

        validate_error(
            api_client.scope_requisition(
                scenario["requisition"]["id"], scope_requisition_payload(), CONSULTANT
            ),
            "ERR_ENTITY_TERMINAL",
            409,
        )

        after = read_requisition(scenario["requisition"])
        assert after["status"] == "WITHDRAWN"
        assert after["scoping_round"] == 0

    def test_10_withdrawal_cancels_the_open_trial_and_frees_the_candidate(self):
        """One call fans out across the requisition, its trial and the candidate.

        PRD §3.1: "Withdrawal cascades in two directions: every `TrialEngagement`
        of the requisition whose `status` is `SCHEDULED` or `IN_PROGRESS` moves to
        `CANCELLED` with `cancel_reason` `CLIENT_REQUEST`, each such cancellation
        restoring the affected candidate's `availability_status` from `ON_TRIAL` to
        `AVAILABLE`; and every `AccommodationTerm` of the requisition whose
        `status` is `PROPOSED` or `COUNTERED` moves to `REJECTED`."

        Design: Corner/state_machines/withdrawal_cancels_the_open_trial_and_releases_the_candidate
        """
        scenario = setup_scenario(stage="trial_booked")
        assert scenario["requisition"]["active_trial_count"] == 1

        data = validate_success(
            api_client.withdraw_requisition(
                scenario["requisition"]["id"],
                withdraw_requisition_payload(reason="Household paused the search."),
                CONSULTANT,
            )
        )
        assert data["status"] == "WITHDRAWN"
        assert data["active_trial_count"] == 0

        trial = read_trial(scenario["trial"])
        assert trial["status"] == "CANCELLED"
        assert trial["cancel_reason"] == "CLIENT_REQUEST"

        candidate = read_candidate(scenario["candidate"])
        assert candidate["availability_status"] == "AVAILABLE"
        assert candidate["vetting_status"] == "CLEARED"


class TestTrialMachine:
    def test_11_a_trial_starts_on_the_inclusive_edge_of_its_window(self):
        """The clock sits exactly on start_at, which is admitted.

        PRD §3.4: "The logical clock must be at or after `start_at`, and an
        earlier clock is refused with `ERR_TRIAL_NOT_STARTED`."

        Design: Corner/state_machines/a_trial_starts_at_exactly_its_start_at
        """
        scenario = setup_scenario(stage="trial_booked")
        assert scenario["trial"]["start_at"].startswith("2026-08-10T09:00:00")
        set_clock(TRIAL_START_AT)

        started = start_trial(scenario["trial"])
        assert started["status"] == "IN_PROGRESS"
        assert started["version"] == 2

        requisition = read_requisition(scenario["requisition"])
        assert requisition["status"] == "TRIALING"
        assert requisition["active_trial_count"] == 1

    def test_12_cancelling_a_running_trial_runs_both_side_effects(self):
        """Cancellation from IN_PROGRESS still empties the search.

        PRD §3.4: "It is admissible from `SCHEDULED` and from `IN_PROGRESS`, both
        taking the engagement to `CANCELLED` with the supplied reason stamped; a
        terminal engagement is refused with `ERR_ENTITY_TERMINAL`."

        PRD §3.4: "Both paths carry the same side-effect set: the candidate is
        returned `ON_TRIAL → AVAILABLE` provided the candidate holds no other
        active engagement **and** the candidate's `vetting_status` is not
        `REJECTED`, and the requisition falls `TRIALING → SOURCING` when the
        recomputed `active_trial_count` reaches 0."

        Design: Corner/state_machines/cancelling_a_running_trial_returns_the_requisition_to_sourcing
        """
        scenario = setup_scenario(stage="trial_booked")
        set_clock(TRIAL_START_AT)
        started = start_trial(scenario["trial"])
        assert started["status"] == "IN_PROGRESS"

        cancelled = cancel_trial(started, "CLIENT_REQUEST")
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "CLIENT_REQUEST"

        assert read_candidate(scenario["candidate"])["availability_status"] == (
            "AVAILABLE"
        )
        requisition = read_requisition(scenario["requisition"])
        assert requisition["status"] == "SOURCING"
        assert requisition["active_trial_count"] == 0

    def test_13_a_cancelled_trial_reports_the_terminal_lock_not_the_state_rule(self):
        """The terminal lock ranks above the IN_PROGRESS precondition.

        PRD §2.11: "A subject row whose current state offers no transition to the
        requested target yields the endpoint's specific state error —
        `ERR_REQUISITION_NOT_SCOPING`, `ERR_TRIAL_NOT_SCHEDULED`,
        `ERR_TRIAL_NOT_IN_PROGRESS`, `ERR_BACKGROUND_NOT_FLAGGED`,
        `ERR_CLAIM_NOT_UNDER_REVIEW`, `ERR_MILESTONE_NOT_INVOICED`,
        `ERR_PLACEMENT_NOT_ACTIVE`, `ERR_CASE_NOT_INVESTIGATING`, or the generic
        `ERR_INVALID_STATE_TRANSITION` where the endpoint has no specific one."

        PRD §2.11: "Ranked immediately below it, a row already in a terminal state
        yields `ERR_ENTITY_TERMINAL`."

        Design: Corner/state_machines/a_cancelled_trial_is_locked_against_recording_an_outcome
        """
        scenario = setup_scenario(stage="trial_booked")
        cancelled = cancel_trial(scenario["trial"], "CLIENT_REQUEST")
        assert cancelled["status"] == "CANCELLED"

        validate_error(
            api_client.record_trial_outcome(
                cancelled["id"], record_trial_outcome_payload("PASSED"), CONSULTANT
            ),
            "ERR_ENTITY_TERMINAL",
            409,
        )

        after = read_trial(cancelled)
        assert after["status"] == "CANCELLED"
        assert after["outcome_note"] is None
