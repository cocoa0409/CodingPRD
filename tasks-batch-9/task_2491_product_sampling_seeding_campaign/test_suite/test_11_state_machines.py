"""Declared initial states, legal legs, refused legs and transition side effects."""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers import (
    assert_instant,
    MODERATOR_A_USER_ID,
    campaign_manager_headers,
    fulfillment_ops_headers,
    moderator_a_headers,
    moderator_b_headers,
    make_panelist_headers,
)
from test_helpers.api_errors import (
    ERR_CAMPAIGN_KIT_EMPTY,
    ERR_CAMPAIGN_POSTURE_FROZEN,
    ERR_ENROLLMENT_NOT_SCREENABLE,
    ERR_INVALID_CAMPAIGN_TRANSITION,
)
from test_helpers.fixtures import KitSpec


SINGLE_HERO_KIT = (KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 10),)


class TestDeclaredInitialStates:
    """Every machine's birth state, observed on one chain of creations."""

    def test_a_campaign_a_kit_line_a_wave_and_an_enrollment_are_born_where_declared(
        self, api
    ):
        """PRD §3.1: "A campaign is born in `DRAFT` with `compliance_posture`
        `OPEN`, with `budget_available_cents` seeded to the full
        `budget_total_cents` and `budget_committed_cents` at zero, with every
        derived counter at zero, with `kit_assembly_unit_cost_cents` at zero, and
        with `launched_by_user_id` and `closed_at` both unset."

        PRD §3.1: "Every line is created `ACTIVE`, with all four of its unit
        buckets — `units_received`, `units_available`, `units_reserved` and
        `units_shipped` — and `units_written_off` at zero."

        PRD §3.5: "Waves are created `PLANNED` with `planned_unit_count` and
        `shipped_unit_count` at zero."

        PRD §3.4: "Creation assigns `enrollment_seq`, the enrollment's 1-based
        ordinal within its campaign, computed as the campaign's
        `enrollment_count` plus one."

        PRD §3.4: "The new row starts on both of its independent state axes at
        their initial values — `screening_status` at `PENDING_SCREEN` and
        `obligation_status` at `NONE` — with `holdout_flag` false,
        `screen_attempt_count` at zero, and `screening_failure_reason`,
        `review_due_at` and `fraud_score_at_screening` all unset."

        Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
        """
        never_advanced = fx.create_campaign(api, name="Initial A")
        host = fx.create_campaign(api, name="Initial B")
        line = fx.add_kit_line(api, host["id"])
        fx.open_screening(api, host["id"])
        center = fx.create_center(api)
        wave = fx.create_wave(api, center["id"])
        panelist = fx.create_panelist(api)

        enrollment = validate_success(
            api.create_enrollment(
                campaign_manager_headers(),
                campaign_id=host["id"],
                panelist_id=panelist["id"],
                screening_answers={"household_size": 3, "attests_no_resale": True},
            ),
            201,
        )

        assert never_advanced["status"] == "DRAFT"
        assert line["status"] == "ACTIVE"
        assert wave["status"] == "PLANNED"
        assert wave["planned_unit_count"] == 0
        assert wave["shipped_unit_count"] == 0
        assert panelist["integrity_status"] == "CLEAR"
        assert enrollment["screening_status"] == "PENDING_SCREEN"
        assert enrollment["obligation_status"] == "NONE"
        assert enrollment["enrollment_seq"] == 1
        assert enrollment["screen_attempt_count"] == 0
        assert enrollment["screening_failure_reason"] is None
        assert enrollment["holdout_flag"] is False
        assert enrollment["review_due_at"] is None


class TestOpenScreeningLeg:
    """DRAFT to SCREENING_OPEN, with and without its precondition."""

    def test_opening_screening_refreshes_the_kit_cost_and_seeds_the_balance(self, api):
        """PRD §3.2: "Opening screening refreshes `kit_assembly_unit_cost_cents`,
        sets `budget_available_cents` to `budget_total_cents` less
        `budget_committed_cents`, and increases the campaign's `version` by 1."

        PRD §3.2: "Activation records `launched_by_user_id` from the acting
        manager's `X-User-ID` and increases `version`."

        Design: Corner/state_machines/open_screening_seeds_kit_cost_and_available_budget
        """
        campaign = fx.create_campaign(api, name="Seed Budget")
        fx.build_kit(api, campaign["id"])

        opened = validate_success(
            api.open_screening(campaign_manager_headers(), campaign["id"])
        )

        assert opened["status"] == "SCREENING_OPEN"
        assert opened["kit_assembly_unit_cost_cents"] == 454
        assert opened["budget_committed_cents"] == 0
        assert opened["budget_available_cents"] == 1000000
        assert opened["launched_by_user_id"] is None

    def test_a_campaign_with_no_active_line_cannot_open_screening(self, api):
        """PRD §3.2: "The campaign must currently be `DRAFT`, and it must have at
        least one `ACTIVE` kit line — a campaign with an empty kit is refused with
        `ERR_CAMPAIGN_KIT_EMPTY`, since no kit could be assembled."

        Design: Corner/state_machines/open_screening_without_an_active_kit_line_is_rejected
        """
        campaign = fx.create_campaign(api, name="No Kit")

        validate_error(
            api.open_screening(campaign_manager_headers(), campaign["id"]),
            ERR_CAMPAIGN_KIT_EMPTY,
            422,
        )

        stored = fx.get_campaign(api, campaign["id"])
        assert stored["status"] == "DRAFT"
        assert stored["kit_assembly_unit_cost_cents"] == 0
        assert stored["budget_committed_cents"] == 0
        assert stored["budget_available_cents"] == 1000000


class TestActivateSamplingLeg:
    """SCREENING_OPEN to SAMPLING_ACTIVE and its screened-enrollment guard."""

    def test_activation_needs_somebody_already_screened_in(self, api):
        """PRD §3.2: "Activating sampling moves the campaign `SCREENING_OPEN →
        SAMPLING_ACTIVE`, again on a `CampaignManager`'s request, and requires at
        least one enrollment of that campaign already in `SCREEN_PASSED`; a
        campaign with nobody screened in is refused with
        `ERR_INVALID_CAMPAIGN_TRANSITION`."

        Design: Corner/state_machines/activate_sampling_without_a_screen_passed_enrollment_is_rejected
        """
        world = fx.screening_open_campaign(
            api, kit_specs=SINGLE_HERO_KIT, name="Not Ready"
        )
        panelist = fx.create_panelist(api)
        enrollment = fx.create_enrollment(api, world.campaign_id, panelist["id"])

        validate_error(
            api.activate_sampling(campaign_manager_headers(), world.campaign_id),
            ERR_INVALID_CAMPAIGN_TRANSITION,
            409,
        )

        stored = fx.get_campaign(api, world.campaign_id)
        assert stored["status"] == "SCREENING_OPEN"
        assert stored["launched_by_user_id"] is None

        unscreened = fx.get_enrollment(api, enrollment["id"])
        assert unscreened["screening_status"] == "PENDING_SCREEN"


class TestUndeclaredAndTerminalLegs:
    """Lifecycle requests whose declared origin state is not the current one."""

    def test_closing_a_draft_campaign_is_not_a_declared_edge(self, api):
        """PRD §3.2: "Resuming, suspending, reopening or otherwise transitioning a
        `CLOSED` campaign is impossible, and any lifecycle request whose declared
        origin state does not match the campaign's current `status` — activating a
        `DRAFT` campaign, resuming a campaign that is not `SUSPENDED` — is refused
        with `ERR_INVALID_CAMPAIGN_TRANSITION`."

        PRD §3.2: "Closing moves the campaign `REVIEW_WINDOW → CLOSED` and
        requires that no review of the campaign is still sitting in `SUBMITTED`
        awaiting a moderator; an undecided review is refused with
        `ERR_INVALID_CAMPAIGN_TRANSITION`."

        Design: Corner/state_machines/campaign_close_from_draft_is_an_undeclared_transition
        """
        campaign = fx.create_campaign(api, name="Early Close")
        fx.add_kit_line(api, campaign["id"])

        validate_error(
            api.close_campaign(campaign_manager_headers(), campaign["id"]),
            ERR_INVALID_CAMPAIGN_TRANSITION,
            409,
        )

        stored = fx.get_campaign(api, campaign["id"])
        assert stored["status"] == "DRAFT"
        assert stored["closed_at"] is None

    def test_a_closed_campaign_will_not_reopen_its_review_window(self, api):
        """PRD §3.2: "Resuming, suspending, reopening or otherwise transitioning a
        `CLOSED` campaign is impossible, and any lifecycle request whose declared
        origin state does not match the campaign's current `status` — activating a
        `DRAFT` campaign, resuming a campaign that is not `SUSPENDED` — is refused
        with `ERR_INVALID_CAMPAIGN_TRANSITION`."

        PRD §3.2: "Closure then refreshes `cost_per_sample_final_cents`, stamps
        `closed_at` with the logical clock's current instant, and increases the
        campaign's `version`."

        PRD §3.6: "When there are no delivered shipments the value is zero."

        Design: Corner/state_machines/closed_campaign_is_terminal_and_rejects_open_review_window
        """
        world = fx.screening_open_campaign(
            api, kit_specs=SINGLE_HERO_KIT, name="Terminal"
        )
        panelist = fx.create_panelist(api)
        enrollment = fx.create_enrollment(api, world.campaign_id, panelist["id"])
        fx.screen_enrollment(api, enrollment["id"])
        fx.activate_sampling(api, world.campaign_id)
        fx.open_review_window(api, world.campaign_id)
        closed = fx.close_campaign(api, world.campaign_id)

        assert closed["status"] == "CLOSED"
        assert_instant(closed["closed_at"], "2026-08-01T00:00:00Z", "closed_at")

        validate_error(
            api.open_review_window(campaign_manager_headers(), world.campaign_id),
            ERR_INVALID_CAMPAIGN_TRANSITION,
            409,
        )

        stored = fx.get_campaign(api, world.campaign_id)
        assert stored["status"] == "CLOSED"
        assert_instant(stored["closed_at"], "2026-08-01T00:00:00Z", "closed_at")
        assert stored["cost_per_sample_final_cents"] == 0

        untouched = fx.get_enrollment(api, enrollment["id"])
        assert untouched["obligation_status"] == "NONE"

    def test_suspending_a_suspended_campaign_is_refused_rather_than_ignored(self, api):
        """PRD §3.2: "A `ComplianceModerator` moves a live campaign
        `SAMPLING_ACTIVE → SUSPENDED`, which is not terminal, and later moves it
        `SUSPENDED → SAMPLING_ACTIVE` again; a campaign may suspend and resume any
        number of times."

        PRD §3.2: "Resuming, suspending, reopening or otherwise transitioning a
        `CLOSED` campaign is impossible, and any lifecycle request whose declared
        origin state does not match the campaign's current `status` — activating a
        `DRAFT` campaign, resuming a campaign that is not `SUSPENDED` — is refused
        with `ERR_INVALID_CAMPAIGN_TRANSITION`."

        Design: Corner/state_machines/suspending_an_already_suspended_campaign_is_rejected
        """
        world = fx.sampling_active_campaign(
            api, kit_specs=SINGLE_HERO_KIT, with_wave=False, name="Double Suspend"
        )
        suspended = fx.suspend_campaign(api, world.campaign_id)
        assert suspended["status"] == "SUSPENDED"

        validate_error(
            api.suspend_campaign(moderator_a_headers(), world.campaign_id),
            ERR_INVALID_CAMPAIGN_TRANSITION,
            409,
        )

        stored = fx.get_campaign(api, world.campaign_id)
        assert stored["status"] == "SUSPENDED"
        assert stored["compliance_posture"] == "OPEN"


class TestWaveReleaseSideEffects:
    """Every declared side effect of LOCKED to RELEASED, in one observation."""

    def test_release_ships_the_batch_and_empties_the_planned_count(self, api):
        """PRD §3.6: "Every shipment of the released wave still in `ALLOCATED`
        moves to `SHIPPED` with `shipped_at` stamped from the logical clock; each
        such shipment's mapped units move from `units_reserved` to
        `units_shipped` on every kit line named in its `reserved_line_units`,
        with each line's `version` increased by 1; the wave's
        `shipped_unit_count` takes on the units that just shipped while its
        `planned_unit_count` returns to zero; and each affected enrollment's
        obligation axis advances `NONE → SAMPLE_SENT`."

        Design: Corner/state_machines/wave_release_ships_every_allocated_shipment_and_zeroes_planned_units
        """
        world = fx.allocated_sample_world(
            api, panelist_count=1, surcharges=[0], name="Release SE"
        )
        fx.lock_wave(api, world.wave_id)

        wave = validate_success(
            api.release_fulfillment_wave(fulfillment_ops_headers(), world.wave_id)
        )

        assert wave["status"] == "RELEASED"
        assert wave["shipped_unit_count"] == 4
        assert wave["planned_unit_count"] == 0

        shipment = fx.get_shipment(api, world.shipment_id(0))
        assert shipment["status"] == "SHIPPED"
        assert_instant(shipment["shipped_at"], "2026-08-01T00:00:00Z", "shipped_at")
        assert shipment["delivered_at"] is None
        assert shipment["kit_unit_total"] == 4

        hero = fx.get_kit_line(api, world.kit_line_id(0))
        accessory = fx.get_kit_line(api, world.kit_line_id(1))
        insert = fx.get_kit_line(api, world.kit_line_id(2))
        assert (hero["units_reserved"], hero["units_shipped"], hero["units_available"]) == (0, 1, 9)
        assert (
            accessory["units_reserved"],
            accessory["units_shipped"],
            accessory["units_available"],
        ) == (0, 2, 18)
        assert (
            insert["units_reserved"],
            insert["units_shipped"],
            insert["units_available"],
        ) == (0, 1, 9)

        enrollment = fx.get_enrollment(api, world.enrollment_id(0))
        assert enrollment["obligation_status"] == "SAMPLE_SENT"
        assert enrollment["review_due_at"] is None

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["allocated_sample_count"] == 1
        assert campaign["budget_committed_cents"] == 754
        assert campaign["cost_per_sample_provisional_cents"] == 754


class TestDeliveryLedgerSync:
    """SHIPPED to DELIVERED, reconciling the campaign ledger and the obligation."""

    def test_delivery_writes_the_final_cost_and_the_review_due_date(self, api):
        """PRD §3.6: "Confirming delivery moves the shipment `SHIPPED →
        DELIVERED`, stamps `delivered_at` from the logical clock, increases the
        campaign's `delivered_sample_count` by 1, refreshes
        `cost_per_sample_final_cents`, re-evaluates `compliance_posture`, and
        advances the enrollment's obligation axis `SAMPLE_SENT → REVIEW_DUE`
        while stamping `review_due_at` as the delivery instant plus the
        campaign's `review_due_days` days."

        PRD §3.6: "Its numerator population is the campaign's shipments whose
        `status` is `DELIVERED` or `LOST`; the numerator sums, per shipment, the
        campaign's `kit_assembly_unit_cost_cents` plus that shipment's freight
        plus that shipment's `surcharge_cents`, and then adds the campaign's
        whole `write_off_cost_cents` once."

        Design: Corner/state_machines/delivery_syncs_the_campaign_cost_ledger_and_the_review_due_date
        """
        world = fx.allocated_sample_world(
            api, panelist_count=1, surcharges=[0], name="Ledger Sync"
        )
        fx.lock_wave(api, world.wave_id)
        fx.release_wave(api, world.wave_id)

        shipment = validate_success(
            api.deliver_sample_shipment(fulfillment_ops_headers(), world.shipment_id(0))
        )

        assert shipment["status"] == "DELIVERED"
        assert_instant(shipment["delivered_at"], "2026-08-01T00:00:00Z", "delivered_at")

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["delivered_sample_count"] == 1
        assert campaign["cost_per_sample_provisional_cents"] == 754
        assert campaign["cost_per_sample_final_cents"] == 754
        assert campaign["compliance_posture"] == "OPEN"
        assert campaign["write_off_cost_cents"] == 0

        enrollment = fx.get_enrollment(api, world.enrollment_id(0))
        assert enrollment["obligation_status"] == "REVIEW_DUE"
        assert_instant(enrollment["review_due_at"], "2026-08-22T00:00:00Z", "review_due_at")


class TestDiversionCaseLegs:
    """The narrow case machine: investigate, reopen and dismiss."""

    @staticmethod
    def _open_case_on_an_allocated_shipment(api, **panelist_kwargs):
        """One allocated shipment carrying a single OPEN diversion case.

        The panelist has no collisions, no strikes and an account far older than
        thirty days unless the caller says otherwise, so the audit score is
        driven only by the case being investigated.
        """
        world = fx.sampling_active_campaign(
            api, panelist_count=1, kit_specs=SINGLE_HERO_KIT, name="Case Machine"
        )
        panelist = fx.create_panelist(api, **panelist_kwargs)
        enrollment = fx.create_enrollment(api, world.campaign_id, panelist["id"])
        fx.screen_enrollment(api, enrollment["id"])
        shipment = fx.allocate_shipment(
            api, enrollment["id"], world.wave_id, surcharge_cents=0
        )
        case = fx.open_diversion_case(
            api,
            panelist["id"],
            shipment["id"],
            evidence_note="Kit listed for sale on a resale marketplace.",
        )
        return world, panelist, enrollment, case

    def test_investigation_rescores_the_audit_variant_on_another_entity(self, api):
        """PRD §3.9: "Investigation moves it `OPEN → INVESTIGATING` and is the
        trigger for the audit fraud rescore: the panelist's
        `fraud_risk_score_audit` and `last_risk_scored_at` are refreshed, and a
        resulting score of at least 55.0 flags a `CLEAR` panelist. **The status
        write to `INVESTIGATING` happens before the rescore**, which means this
        very case is already counted by the audit variant's live-case term —
        moving a panelist's first case into investigation contributes 15 points to
        their own audit score in the same operation."

        Design: Corner/state_machines/investigate_rescores_the_panelist_audit_variant_across_entities
        """
        _, panelist, enrollment, case = self._open_case_on_an_allocated_shipment(api)

        investigated = validate_success(
            api.investigate_diversion_case(moderator_a_headers(), case["id"])
        )
        assert investigated["status"] == "INVESTIGATING"

        stored = fx.get_panelist(api, panelist["id"])
        assert stored["fraud_risk_score_audit"] == pytest.approx(15.0, abs=0.01)
        assert stored["fraud_risk_score_screening"] == pytest.approx(0.0, abs=0.01)
        assert_instant(stored["last_risk_scored_at"], "2026-08-01T00:00:00Z", "last_risk_scored_at")
        assert stored["integrity_status"] == "CLEAR"
        assert stored["diversion_strikes"] == 0

        screened = fx.get_enrollment(api, enrollment["id"])
        assert screened["screening_status"] == "SCREEN_PASSED"

    def test_reopening_returns_the_case_to_open_and_counts_the_loop(self, api):
        """PRD §3.9: "Reopening moves the case `INVESTIGATING → OPEN` and
        increases `reopen_count` by 1; the cycle `OPEN → INVESTIGATING → OPEN` is
        repeatable, and the audit rescore re-runs on every re-entry into
        investigation."

        PRD §3.9: "The case is created `OPEN` with `reopen_count` at zero,
        `substantiated_at` unset, and `opened_by_user_id` recorded from the
        opening moderator's `X-User-ID` — that recorded identifier is what the
        segregation-of-duties rule later reads."

        Design: Corner/state_machines/reopening_an_investigating_diversion_case_returns_it_to_open_and_counts_the_loop
        """
        world, panelist, _, case = self._open_case_on_an_allocated_shipment(api)
        assert case["reopen_count"] == 0
        fx.investigate_case(api, case["id"])

        reopened = validate_success(
            api.reopen_diversion_case(moderator_a_headers(), case["id"])
        )

        assert reopened["status"] == "OPEN"
        assert reopened["reopen_count"] == 1
        assert reopened["substantiated_at"] is None
        assert reopened["opened_by_user_id"] == MODERATOR_A_USER_ID

        stored = fx.get_panelist(api, panelist["id"])
        assert stored["integrity_status"] == "CLEAR"
        assert stored["diversion_strikes"] == 0

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["substantiated_diversion_count"] == 0

    def test_dismissing_the_only_live_case_restores_the_flagged_standing(self, api):
        """PRD §3.9: "Dismissal moves the case `INVESTIGATING → DISMISSED`, which
        is terminal, and restores standing conditionally: when the panelist is
        currently `FLAGGED` and holds no other case in `INVESTIGATING` or
        `SUBSTANTIATED`, their `integrity_status` returns to `CLEAR` and their
        `version` increases by 1; a panelist with another live case stays
        flagged."

        Design: Corner/state_machines/dismissing_the_last_open_case_clears_the_panelist_flag
        """
        world = fx.sampling_active_campaign(
            api, panelist_count=1, kit_specs=SINGLE_HERO_KIT, name="Dismiss Clear"
        )
        cluster = fx.address_cluster_panelists(api, 4)
        target = cluster[0]
        enrollment = fx.create_enrollment(api, world.campaign_id, target["id"])
        fx.screen_enrollment(api, enrollment["id"])
        shipment = fx.allocate_shipment(
            api, enrollment["id"], world.wave_id, surcharge_cents=0
        )
        case = fx.open_diversion_case(
            api,
            target["id"],
            shipment["id"],
            signal_type="ADDRESS_CLUSTER",
            evidence_note="four accounts share one shipping address",
        )
        fx.investigate_case(api, case["id"])
        flagged = fx.get_panelist(api, target["id"])
        assert flagged["integrity_status"] == "FLAGGED"

        dismissed = validate_success(
            api.dismiss_diversion_case(moderator_b_headers(), case["id"])
        )

        assert dismissed["status"] == "DISMISSED"
        assert dismissed["substantiated_at"] is None

        restored = fx.get_panelist(api, target["id"])
        assert restored["fraud_risk_score_screening"] == pytest.approx(40.0, abs=0.01)
        assert restored["fraud_risk_score_audit"] == pytest.approx(64.0, abs=0.01)
        assert restored["integrity_status"] == "CLEAR"
        assert restored["diversion_strikes"] == 0

        screened = fx.get_enrollment(api, enrollment["id"])
        assert screened["screening_status"] == "SCREEN_PASSED"
        assert screened["fraud_score_at_screening"] == pytest.approx(40.0, abs=0.01)

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["substantiated_diversion_count"] == 0
        assert campaign["compliance_posture"] == "OPEN"


class TestResumeGuard:
    """SUSPENDED to SAMPLING_ACTIVE, guarded by a derived field on the campaign."""

    def test_a_frozen_posture_keeps_a_suspended_campaign_suspended(self, api):
        """PRD §3.2: "Resumption additionally requires that `compliance_posture`
        is not `FROZEN` — a frozen campaign stays suspended until the posture
        clears, and the attempt is refused with `ERR_CAMPAIGN_POSTURE_FROZEN`."

        Design: Corner/state_machines/resume_is_guarded_by_compliance_posture_frozen
        """
        world = fx.delivered_sample_world(
            api,
            panelist_count=1,
            surcharges=[0],
            kit_specs=SINGLE_HERO_KIT,
            name="Frozen Resume",
        )
        case = fx.open_diversion_case(
            api,
            world.panelist_id(0),
            world.shipment_id(0),
            evidence_note="kit listed for resale two days after delivery",
        )
        fx.investigate_case(api, case["id"])
        fx.substantiate_case(api, case["id"])
        fx.suspend_campaign(api, world.campaign_id)

        validate_error(
            api.resume_campaign(moderator_a_headers(), world.campaign_id),
            ERR_CAMPAIGN_POSTURE_FROZEN,
            409,
        )

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["status"] == "SUSPENDED"
        assert campaign["compliance_posture"] == "FROZEN"
        assert campaign["substantiated_diversion_count"] == 1
        assert campaign["delivered_sample_count"] == 1

        panelist = fx.get_panelist(api, world.panelist_id(0))
        assert panelist["integrity_status"] == "BANNED"
        assert panelist["diversion_strikes"] == 1

        enrollment = fx.get_enrollment(api, world.enrollment_id(0))
        assert enrollment["screening_status"] == "SCREEN_REVOKED"
        assert enrollment["obligation_status"] == "FORFEITED"


class TestScreeningRetryCap:
    """SCREEN_FAILED to PENDING_SCREEN, capped at three evaluated attempts."""

    def test_a_fourth_resubmission_is_refused_once_three_attempts_are_spent(self, api):
        """PRD §3.4: "The cycle `SCREEN_FAILED → PENDING_SCREEN → SCREEN_PASSED`
        or `SCREEN_FAILED` is capped at three evaluated attempts: a resubmission
        is refused with `ERR_ENROLLMENT_NOT_SCREENABLE` once
        `screen_attempt_count` has reached 3."

        PRD §3.4: "the request carries a fresh `screening_answers` object that
        replaces the stored one wholesale rather than merging into it, and it
        clears `screening_failure_reason` and increases the enrollment's
        `version` by 1."

        Design: Corner/state_machines/resubmit_screening_after_three_attempts_is_rejected
        """
        world = fx.screening_open_campaign(
            api, kit_specs=SINGLE_HERO_KIT, name="Retry Cap"
        )
        panelist = fx.create_panelist(api, segment_code="RURAL_BOOMER")
        enrollment = fx.create_enrollment(
            api,
            world.campaign_id,
            panelist["id"],
            screening_answers={"household_size": 2, "attests_no_resale": True},
        )

        first = fx.screen_enrollment(api, enrollment["id"])
        assert first["screening_status"] == "SCREEN_FAILED"
        assert first["screening_failure_reason"] == "SEGMENT_MISMATCH"

        fx.resubmit_screening(
            api,
            enrollment["id"],
            panelist["id"],
            {"household_size": 3, "attests_no_resale": True},
        )
        fx.screen_enrollment(api, enrollment["id"])
        fx.resubmit_screening(
            api,
            enrollment["id"],
            panelist["id"],
            {"household_size": 4, "attests_no_resale": True},
        )
        third = fx.screen_enrollment(api, enrollment["id"])
        assert third["screen_attempt_count"] == 3

        validate_error(
            api.resubmit_screening(
                make_panelist_headers(panelist["id"]),
                enrollment["id"],
                {"household_size": 9, "attests_no_resale": True},
            ),
            ERR_ENROLLMENT_NOT_SCREENABLE,
            409,
        )

        stored = fx.get_enrollment(api, enrollment["id"])
        assert stored["screen_attempt_count"] == 3
        assert stored["screening_status"] == "SCREEN_FAILED"
        assert stored["screening_failure_reason"] == "SEGMENT_MISMATCH"
        assert stored["screening_answers"]["household_size"] == 4
        assert stored["holdout_flag"] is False
