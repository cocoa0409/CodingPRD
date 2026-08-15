"""Intercompany agreement lifecycle: creation guards, activation gates,
the cyclic amendment detour, termination lockdown, and evidence pinning."""
from test_helpers import (
    ADMIN,
    ANALYST,
    MANAGER,
    ApiErrorId,
    activate_agreement,
    approve_refreshed_study,
    create_agreement,
    create_legal_entity,
    create_study,
    refresh_study,
    setup_active_agreement,
    setup_year_entities_study,
    validate_error,
    validate_success,
    api_client,
)


class TestAgreementCreationGuards:

    def test_same_entity_agreement_rejected(self):
        """PRD section 3.3: "The provider and recipient must differ
        (`ERR_SAME_LEGAL_ENTITY`), both entities must be `ACTIVE`
        (`ERR_ENTITY_INACTIVE`), and the effective window must not overlap"

        Design: Corner/validations/same_entity_agreement_rejected
        """
        entity = create_legal_entity()
        study = create_study()
        resp = api_client.create_agreement(
            {
                "provider_entity_id": entity["id"],
                "recipient_entity_id": entity["id"],
                "transaction_type": "SERVICES",
                "pricing_method": "COST_PLUS",
                "markup_bp": 200,
                "true_up_method": "TO_MEDIAN",
                "benchmarking_study_id": study["id"],
                "effective_from": "2026-01-01",
                "effective_to": "2027-01-01",
            },
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_SAME_LEGAL_ENTITY)


class TestActivationGates:

    def test_activate_outside_effective_window_rejected(self):
        """PRD section 3.3: "the logical clock's date must fall inside the
        half-open window from `effective_from` to `effective_to`
        (`ERR_AGREEMENT_NOT_IN_EFFECT`)"
        PRD section 2.5: "Before any operator sets it, the logical clock
        reads exactly 2026-08-01T00:00:00Z, and it never falls back to
        wall-clock time."

        Design: Corner/errors/activate_outside_effective_window_rejected
        """
        ctx = setup_year_entities_study()
        agreement = create_agreement(
            ctx["provider"]["id"], ctx["recipient"]["id"], ctx["study"]["id"],
            effective_from="2027-01-01", effective_to="2028-01-01")

        resp = api_client.activate_agreement(agreement["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_IN_EFFECT)

        after = validate_success(api_client.get_agreement(agreement["id"],
                                                          MANAGER), 200)
        assert after["status"] == "DRAFT", "rejected activation must not mutate"

    def test_activate_with_draft_study_rejected(self):
        """PRD section 3.3: "and the referenced `benchmarking_study_id` must
        resolve to a study in `CURRENT` (`ERR_STALE_BENCHMARK`)."

        Design: Corner/errors/activate_with_draft_study_rejected
        """
        provider = create_legal_entity(name="USCo", country_code="US",
                                       functional_currency="USD")
        recipient = create_legal_entity(name="DECo", country_code="DE",
                                        functional_currency="EUR")
        study = create_study()  # never approved: stays DRAFT
        agreement = create_agreement(provider["id"], recipient["id"],
                                     study["id"])

        resp = api_client.activate_agreement(agreement["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_STALE_BENCHMARK)

        after = validate_success(api_client.get_agreement(agreement["id"],
                                                          MANAGER), 200)
        assert after["status"] == "DRAFT"
        assert after["pinned_study_id"] is None


class TestInvalidTransitions:

    def test_approve_amendment_from_active_rejected(self):
        """PRD section 3.3: "Approval by a `TaxManager` (`UNDER_AMENDMENT →
        ACTIVE`) requires the approver to differ from
        `amendment_started_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`)"
        PRD section 2.8: "4. **State legality** — the target resource must be
        in a state from which the requested transition or operation is
        defined, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/approve_amendment_from_active_rejected
        """
        ctx = setup_active_agreement()
        agreement = ctx["agreement"]

        resp = api_client.approve_amendment(agreement["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api_client.get_agreement(agreement["id"],
                                                          MANAGER), 200)
        assert after["status"] == "ACTIVE"
        assert after["markup_bp"] == 200, "markup unchanged after rejection"

    def test_activate_after_terminate_rejected(self):
        """PRD section 3.3: "Termination by a `TaxManager` (`ACTIVE →
        TERMINATED`) is refused with `ERR_APA_LOCKED` while an APA lock
        covers the agreement, and with `ERR_AGREEMENT_HAS_OPEN_TRANSACTIONS`
        while any transaction of the agreement has an `elimination_status`
        other than `ELIMINATED`. `TERMINATED` is terminal."
        PRD section 2.8: "Acting on a terminal resource falls under this
        check as well."

        Design: Corner/state_machines/activate_after_terminate_rejected
        """
        ctx = setup_active_agreement()
        agreement = ctx["agreement"]
        terminated = validate_success(
            api_client.terminate_agreement(agreement["id"], MANAGER), 200)
        assert terminated["status"] == "TERMINATED"

        resp = api_client.activate_agreement(agreement["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api_client.get_agreement(agreement["id"],
                                                          MANAGER), 200)
        assert after["status"] == "TERMINATED"


class TestEntityDeactivationGuard:

    def test_deactivate_entity_with_active_agreement_rejected(self):
        """PRD section 3.1: "Deactivation moves an entity from `ACTIVE` to
        `INACTIVE` and is blocked with `ERR_ENTITY_HAS_ACTIVE_AGREEMENTS`
        whenever any agreement in `ACTIVE` or `UNDER_AMENDMENT` references
        the entity as provider or recipient — agreements still in `DRAFT` do
        not block deactivation."

        Design: Corner/errors/deactivate_entity_with_active_agreement_rejected
        """
        ctx = setup_active_agreement()
        draft_only_entity = create_legal_entity(
            name="FRCo", country_code="FR", functional_currency="EUR")
        # A DRAFT agreement referencing the third entity must not block it.
        create_agreement(ctx["provider"]["id"], draft_only_entity["id"],
                         ctx["study"]["id"])

        blocked = api_client.deactivate_legal_entity(
            ctx["recipient"]["id"], ADMIN)
        validate_error(blocked, ApiErrorId.ERR_ENTITY_HAS_ACTIVE_AGREEMENTS)
        still_active = validate_success(
            api_client.get_legal_entity(ctx["recipient"]["id"], ADMIN), 200)
        assert still_active["status"] == "ACTIVE"

        allowed = validate_success(
            api_client.deactivate_legal_entity(draft_only_entity["id"],
                                               ADMIN), 200)
        assert allowed["status"] == "INACTIVE"


class TestAgreementPeriodOverlap:

    def test_overlapping_agreement_period_rejected(self):
        """PRD section 3.3: "and the effective window must not overlap —
        under half-open semantics where one window ending exactly when
        another begins is adjacency, not overlap — any other agreement with
        the same provider, recipient, and transaction type in `DRAFT`,
        `ACTIVE`, or `UNDER_AMENDMENT` (`ERR_AGREEMENT_PERIOD_OVERLAP`)."

        Design: Difficulty/resource_temporal_overlap/agreement_half_open_interval_collision_vs_adjacency
        """
        ctx = setup_year_entities_study()
        create_agreement(ctx["provider"]["id"], ctx["recipient"]["id"],
                         ctx["study"]["id"],
                         effective_from="2026-01-01", effective_to="2027-01-01")

        resp = api_client.create_agreement(
            {
                "provider_entity_id": ctx["provider"]["id"],
                "recipient_entity_id": ctx["recipient"]["id"],
                "transaction_type": "SERVICES",
                "pricing_method": "COST_PLUS",
                "markup_bp": 200,
                "true_up_method": "TO_MEDIAN",
                "benchmarking_study_id": ctx["study"]["id"],
                "effective_from": "2026-06-01",
                "effective_to": "2026-12-01",
            },
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_PERIOD_OVERLAP)

    def test_adjacent_agreement_period_accepted(self):
        """PRD section 3.3: "and the effective window must not overlap —
        under half-open semantics where one window ending exactly when
        another begins is adjacency, not overlap — any other agreement with
        the same provider, recipient, and transaction type in `DRAFT`,
        `ACTIVE`, or `UNDER_AMENDMENT` (`ERR_AGREEMENT_PERIOD_OVERLAP`)."

        Design: Difficulty/resource_temporal_overlap/agreement_half_open_interval_collision_vs_adjacency
        """
        ctx = setup_year_entities_study()
        create_agreement(ctx["provider"]["id"], ctx["recipient"]["id"],
                         ctx["study"]["id"],
                         effective_from="2026-01-01", effective_to="2027-01-01")

        # Adjacent: starts exactly when the first window ends.
        resp = api_client.create_agreement(
            {
                "provider_entity_id": ctx["provider"]["id"],
                "recipient_entity_id": ctx["recipient"]["id"],
                "transaction_type": "SERVICES",
                "pricing_method": "COST_PLUS",
                "markup_bp": 250,
                "true_up_method": "TO_MEDIAN",
                "benchmarking_study_id": ctx["study"]["id"],
                "effective_from": "2027-01-01",
                "effective_to": "2028-01-01",
            },
            ANALYST,
        )
        adjacent = validate_success(resp, expected_status=201)
        assert adjacent["status"] == "DRAFT"


class TestAmendmentCycle:

    def _run_two_amendment_cycles(self):
        ctx = setup_active_agreement()
        agreement_id = ctx["agreement"]["id"]
        # Cycle 1: 200 -> 300
        api_client.start_amendment(agreement_id, {"new_markup_bp": 300},
                                   ANALYST)
        validate_success(api_client.approve_amendment(agreement_id, MANAGER),
                         200)
        # Cycle 2: 300 -> 250
        api_client.start_amendment(agreement_id, {"new_markup_bp": 250},
                                   ANALYST)
        final = validate_success(
            api_client.approve_amendment(agreement_id, MANAGER), 200)
        return ctx, final

    def test_amendment_cycle_restores_active_with_new_markup(self):
        """PRD section 3.3: "Amendment is a cyclic detour out of and back
        into `ACTIVE`."
        PRD section 3.3: "Approval applies `pending_markup_bp` to `markup_bp`,
        re-pins the study and range snapshot when a replacement study was
        proposed, clears the pending fields, adds 1 to `amendments_count`,
        and resets `pricing_review_required` to false — because the approved
        amendment is precisely the expected response to a review flag."

        Design: Difficulty/non_linear_state_machine/agreement_amendment_cycle_restores_active_with_new_markup
        """
        _, final = self._run_two_amendment_cycles()
        assert final["status"] == "ACTIVE", "cyclic return to ACTIVE"
        assert final["markup_bp"] == 250, \
            "the second approved markup supersedes the first"
        assert final["amendments_count"] == 2, "+1 per approved amendment"

    def test_amendment_cycle_version_progression_and_pending_cleared(self):
        """PRD section 2.4: "`version` (integer): a system-managed integer
        that increments by exactly 1 on every mutation of the resource."
        PRD section 3.3: "Approval applies `pending_markup_bp` to `markup_bp`,
        re-pins the study and range snapshot when a replacement study was
        proposed, clears the pending fields, adds 1 to `amendments_count`,
        and resets `pricing_review_required` to false"

        Design: Difficulty/non_linear_state_machine/agreement_amendment_cycle_restores_active_with_new_markup
        """
        _, final = self._run_two_amendment_cycles()
        # create = 1, activate = 2, then start/approve pairs add 2 each.
        assert final["version"] == 6
        assert final["pending_markup_bp"] is None, \
            "pending fields are cleared on approval"
        assert final["pending_study_id"] is None
        assert final["pricing_review_required"] is False


class TestVersionIncrement:

    def test_agreement_version_increments_on_each_mutation(self):
        """PRD section 2.4: "`version` (integer): a system-managed integer
        that increments by exactly 1 on every mutation of the resource."
        PRD section 3.3: "A `TaxAnalyst` starts an amendment (`ACTIVE →
        UNDER_AMENDMENT`) by supplying `new_markup_bp` and optionally
        `new_benchmarking_study_id`; the server stores them as
        `pending_markup_bp` and `pending_study_id` and records
        `amendment_started_by_user_id`."

        Design: Corner/cross_cutting_layers/agreement_version_increments_on_each_mutation
        """
        ctx = setup_year_entities_study()
        draft = create_agreement(ctx["provider"]["id"], ctx["recipient"]["id"],
                                 ctx["study"]["id"])
        assert draft["version"] == 1, "version starts at 1 on create"

        activated = activate_agreement(draft["id"])
        assert activated["version"] == 2

        amended = validate_success(
            api_client.start_amendment(activated["id"],
                                       {"new_markup_bp": 300}, ANALYST), 200)
        assert amended["version"] == 3
        assert amended["status"] == "UNDER_AMENDMENT"
        assert amended["pending_markup_bp"] == 300

        fetched = validate_success(api_client.get_agreement(activated["id"],
                                                            MANAGER), 200)
        assert fetched["version"] == 3


class TestEvidencePinning:

    def test_activation_pins_study_snapshot_against_later_refresh(self):
        """PRD section 3.3: "Activation then pins the evidence:
        `pinned_study_id` is set to the referenced study and `pinned_p25_bp`,
        `pinned_median_bp`, and `pinned_p75_bp` are copied from it, freezing
        the arm's-length range that later true-up runs will test against."
        PRD section 3.2: "If the approved draft carries a
        `supersedes_study_id`, the referenced study — whether `CURRENT` or
        `STALE` — transitions to `SUPERSEDED` in the same operation."

        Design: Corner/cross_cutting_layers/activation_pins_study_snapshot_against_later_refresh
        """
        ctx = setup_active_agreement()
        study = ctx["study"]
        assert study["median_bp"] == 500
        agreement = validate_success(
            api_client.get_agreement(ctx["agreement"]["id"], MANAGER), 200)
        assert agreement["pinned_study_id"] == study["id"]
        assert agreement["pinned_median_bp"] == 500

        # Refresh the study and approve the successor (median moves to 1100).
        child = refresh_study(study["id"], [900, 1000, 1100, 1200, 1300],
                              expected_study_version=study["version"])
        approved_child = approve_refreshed_study(child["id"])
        assert approved_child["median_bp"] == 1100

        old_study = validate_success(
            api_client.get_benchmarking_study(study["id"], MANAGER), 200)
        assert old_study["status"] == "SUPERSEDED"

        after = validate_success(
            api_client.get_agreement(agreement["id"], MANAGER), 200)
        assert after["pinned_study_id"] == study["id"], \
            "the pin is frozen at activation and survives the refresh"
        assert after["pinned_median_bp"] == 500
