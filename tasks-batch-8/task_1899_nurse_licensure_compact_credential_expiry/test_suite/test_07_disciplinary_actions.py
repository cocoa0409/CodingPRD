"""Disciplinary actions: parallel nurse axes, the encumbrance cascade, resolution
timing, and pipeline precedence on creation (PRD §2.9, §3.5, §3.8)."""
from test_helpers import (
    ApiErrorId,
    acknowledge_discipline,
    adjudicate_discipline,
    book_shift,
    create_license_draft,
    create_nurse,
    create_unit,
    get_license,
    get_nurse,
    get_packet,
    get_shift,
    get_unit,
    list_privilege_evals,
    report_discipline,
    resolve_discipline,
    set_clock,
    setup_approved_packet,
    setup_credentialed_nurse,
    terminate_nurse,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client, TEST_USERS

SPEC1 = TEST_USERS["specialist_1"]
CO1 = TEST_USERS["compliance_1"]
CO2 = TEST_USERS["compliance_2"]
MGR1 = TEST_USERS["manager_1"]
COMPACT_SCOPE = ["AZ", "CO", "FL", "GA", "MD", "NC", "TN", "TX"]


class TestParallelStatusPostureDimensions:
    """Difficulty instance: nurse_parallel_status_posture_dimensions — the lifecycle
    axis stays ACTIVE through a PROBATION cycle while the posture axis cycles
    CLEAR -> PRACTICE_RESTRICTED -> CLEAR; termination then settles both axes."""

    def _setup_nora_adjudicated_probation(self):
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Nora Parallel",
                                       email="nora.parallel@x.com")
        nurse = ctx["nurse"]
        action = report_discipline(nurse["id"], scope="PRIVILEGE",
                                   action_type="PROBATION", effective_on="2026-08-01")
        acknowledge_discipline(action["id"], headers=CO1)
        adjudicate_discipline(action["id"], outcome="SUSTAINED", headers=CO2)
        return ctx, action

    def test_sustained_probation_moves_posture_not_lifecycle(self):
        """PRD §3.8: "When the scope is `PRIVILEGE`, the nurse's privilege re-derives
        downward — `ELIGIBLE_MULTISTATE` becomes `SINGLE_STATE_ONLY` confined to her
        primary state of residence — with a `DISCIPLINE_CHANGE` evaluation appended."
        PRD §3.5: "A nurse with any disciplinary action standing `ADJUDICATED` at
        severity `PROBATION`, `SUSPENSION`, or `REVOCATION` is `PRACTICE_RESTRICTED`."

        Design: Difficulty/non_linear_state_machine/nurse_parallel_status_posture_dimensions
        """
        ctx, _action = self._setup_nora_adjudicated_probation()
        nurse = get_nurse(ctx["nurse"]["id"])
        assert nurse["status"] == "ACTIVE", "the lifecycle axis did not move"
        assert nurse["credential_posture"] == "PRACTICE_RESTRICTED"
        assert nurse["multistate_privilege_status"] == "SINGLE_STATE_ONLY"
        assert nurse["practice_scope"] == ["AZ"]
        assert nurse["open_encumbrance_count"] == 1

    def test_resolve_then_terminate_settles_axes(self):
        """PRD §3.8: "A `PRIVILEGE`-scope action re-derives the nurse's privilege,
        restoring her prior standing and appending a `DISCIPLINE_CHANGE` evaluation.
        And the posture recompute lifts `PRACTICE_RESTRICTED` once this was her last
        open encumbrance."
        PRD §3.8: "A minimum active period must have elapsed since `effective_on`: none
        for `REPRIMAND`, 90 days for `PROBATION`, 30 days for `SUSPENSION`, and 365
        days for `REVOCATION`; resolving earlier is `ERR_RESOLUTION_PREMATURE`."
        PRD §3.1: "The nurse's `credential_posture` is forced to `SCHEDULING_SUSPENDED`
        as the terminal snapshot."

        Design: Difficulty/non_linear_state_machine/nurse_parallel_status_posture_dimensions
        """
        ctx, action = self._setup_nora_adjudicated_probation()
        nurse_id = ctx["nurse"]["id"]

        # 2026-08-01 + 90 days == 2026-10-30: the PROBATION minimum has elapsed.
        set_clock("2026-10-30T00:00:00Z")
        resolved = resolve_discipline(action["id"],
                                      resolution_note="probation terms completed")
        assert resolved["status"] == "RESOLVED"
        nurse = get_nurse(nurse_id)
        assert nurse["status"] == "ACTIVE"
        assert nurse["credential_posture"] == "CLEAR"
        assert nurse["multistate_privilege_status"] == "ELIGIBLE_MULTISTATE"
        assert nurse["practice_scope"] == COMPACT_SCOPE
        assert nurse["open_encumbrance_count"] == 0

        terminated = terminate_nurse(nurse_id)
        assert terminated["status"] == "TERMINATED"
        assert terminated["credential_posture"] == "SCHEDULING_SUSPENDED"


class TestAdjudicationPrivilegeCascade:
    """Difficulty instance: discipline_adjudication_privilege_revocation_cascade —
    SUSTAINED PRIVILEGE-scope SUSPENSION downgrades privilege, flips posture, and the
    cascade auto-cancels the future shift and voids the APPROVED packet."""

    def _setup_tara_adjudicated(self):
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Tara Disc", email="tara.disc@x.com",
                                       employment_type="TRAVEL")
        nurse = ctx["nurse"]
        unit = create_unit(name="MED", required_cert_types=[])
        packet_ctx = setup_approved_packet(nurse["id"], unit["id"])
        shift = book_shift(nurse["id"], unit["id"],
                           "2026-08-10T07:00:00Z", "2026-08-10T19:00:00Z")
        action = report_discipline(nurse["id"], scope="PRIVILEGE",
                                   action_type="SUSPENSION", effective_on="2026-08-01")
        acknowledge_discipline(action["id"], headers=CO1)
        adjudicate_discipline(action["id"], outcome="SUSTAINED", headers=CO2)
        return ctx, unit, packet_ctx, shift, action

    def test_privilege_downgrade_and_posture_flip(self):
        """PRD §3.8: "The nurse's `open_encumbrance_count` increments by 1. ... When
        the scope is `PRIVILEGE`, the nurse's privilege re-derives downward —
        `ELIGIBLE_MULTISTATE` becomes `SINGLE_STATE_ONLY` confined to her primary state
        of residence — with a `DISCIPLINE_CHANGE` evaluation appended."
        PRD §3.5: "A nurse with any disciplinary action standing `ADJUDICATED` at
        severity `PROBATION`, `SUSPENSION`, or `REVOCATION` is `PRACTICE_RESTRICTED`."

        Design: Difficulty/transitive_cascade/discipline_adjudication_privilege_revocation_cascade
        """
        ctx, _unit, _packet_ctx, _shift, _action = self._setup_tara_adjudicated()
        nurse = get_nurse(ctx["nurse"]["id"])
        assert nurse["multistate_privilege_status"] == "SINGLE_STATE_ONLY"
        assert nurse["practice_scope"] == ["AZ"]
        assert nurse["open_encumbrance_count"] == 1
        assert nurse["credential_posture"] == "PRACTICE_RESTRICTED"

        evals = list_privilege_evals(ctx["nurse"]["id"])
        assert len(evals) == 2
        assert (evals[0]["trigger_reason"], evals[0]["resulting_status"]) == (
            "LICENSE_CHANGE", "ELIGIBLE_MULTISTATE",
        )
        assert (evals[1]["trigger_reason"], evals[1]["resulting_status"]) == (
            "DISCIPLINE_CHANGE", "SINGLE_STATE_ONLY",
        )

    def test_cascade_cancels_shift_and_voids_packet(self):
        """PRD §3.8: "When the action type is `PROBATION`, `SUSPENSION`, or
        `REVOCATION`, the posture recompute lands her in `PRACTICE_RESTRICTED`, firing
        the full posture cascade of §3.5: future `SCHEDULED` shifts auto-cancelled with
        `cancel_reason` `POSTURE_PRACTICE_RESTRICTED`, unit counters decremented per
        cancellation, and approved packets voided."

        Design: Difficulty/transitive_cascade/discipline_adjudication_privilege_revocation_cascade
        """
        _ctx, unit, packet_ctx, shift, _action = self._setup_tara_adjudicated()
        after_shift = get_shift(shift["id"])
        assert after_shift["status"] == "AUTO_CANCELLED"
        assert after_shift["cancel_reason"] == "POSTURE_PRACTICE_RESTRICTED"
        unit_after = get_unit(unit["id"])
        assert unit_after["scheduled_hours_total"] == 0.0
        assert unit_after["active_assignment_count"] == 0
        assert get_packet(packet_ctx["packet"]["id"])["status"] == "VOIDED"


class TestAdjudicateResolveConservation:
    """Difficulty instance: discipline_adjudicate_resolve_conserves_encumbrance_count
    — the adjudicate/resolve pair restores the encumbrance ledger and the license."""

    def _setup_quinn_sustained_suspension(self):
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Quinn Balance",
                                       email="quinn.balance@x.com")
        nurse, lic = ctx["nurse"], ctx["license"]
        action = report_discipline(nurse["id"], scope="LICENSE",
                                   action_type="SUSPENSION", effective_on="2026-08-01",
                                   license_id=lic["id"])
        acknowledge_discipline(action["id"], headers=CO1)
        adjudicate_discipline(action["id"], outcome="SUSTAINED", headers=CO2)
        return ctx, action

    def test_adjudicate_encumbers_license_and_counts(self):
        """PRD §3.8: "The nurse's `open_encumbrance_count` increments by 1. When the
        scope is `LICENSE` and the action type is `SUSPENSION` or `REVOCATION`, the
        named license moves from `ACTIVE` to `ENCUMBERED`."
        PRD §3.5: "A nurse with any disciplinary action standing `ADJUDICATED` at
        severity `PROBATION`, `SUSPENSION`, or `REVOCATION` is `PRACTICE_RESTRICTED`."

        Design: Difficulty/compensating_invariant/discipline_adjudicate_resolve_conserves_encumbrance_count
        """
        ctx, _action = self._setup_quinn_sustained_suspension()
        nurse = get_nurse(ctx["nurse"]["id"])
        assert nurse["open_encumbrance_count"] == 1
        assert nurse["credential_posture"] == "PRACTICE_RESTRICTED"
        assert get_license(ctx["license"]["id"])["status"] == "ENCUMBERED"

    def test_resolve_at_minimum_restores_ledgers(self):
        """PRD §3.8: "Resolution decrements `open_encumbrance_count` by 1 and unwinds
        the encumbrance. A license it encumbered returns from `ENCUMBERED` to `ACTIVE`
        when its `expires_on` is on or after the current date, or to `EXPIRED` when
        that date has passed."
        PRD §3.8: "A minimum active period must have elapsed since `effective_on`: none
        for `REPRIMAND`, 90 days for `PROBATION`, 30 days for `SUSPENSION`, and 365
        days for `REVOCATION`; resolving earlier is `ERR_RESOLUTION_PREMATURE`."

        Design: Difficulty/compensating_invariant/discipline_adjudicate_resolve_conserves_encumbrance_count
        """
        ctx, action = self._setup_quinn_sustained_suspension()
        # effective_on 2026-08-01 + MIN_ACTIVE_DAYS[SUSPENSION] 30 == 2026-08-31.
        set_clock("2026-08-31T00:00:00Z")
        resolved = resolve_discipline(action["id"], resolution_note="suspension served")
        assert resolved["status"] == "RESOLVED"

        nurse = get_nurse(ctx["nurse"]["id"])
        assert nurse["open_encumbrance_count"] == 0, "back to the pre-action value"
        assert nurse["credential_posture"] == "CLEAR"
        lic = get_license(ctx["license"]["id"])
        assert lic["status"] == "ACTIVE", "expires_on 2027-06-30 >= 2026-08-31"


class TestDisciplineCreationPrecedence:
    """Difficulty instance: discipline_create_referential_beats_state — body
    referential integrity (stage 5) precedes state validity (stage 7)."""

    def _setup_ann_terminated_and_bob(self):
        set_clock()
        ctx_a = setup_credentialed_nurse(full_name="Ann Ref", email="ann.ref@x.com")
        nurse_a = ctx_a["nurse"]
        terminate_nurse(nurse_a["id"])
        nurse_b = create_nurse(full_name="Bob Ref", email="bob.ref@x.com")
        lic_b = create_license_draft(nurse_b["id"], license_number="RN-AZ-BR1")
        return ctx_a, nurse_a, nurse_b, lic_b

    def _discipline_count(self, nurse_id: str) -> int:
        _data, meta = validate_paginated(
            api_client.list_disciplinary_actions(CO1, params={"nurse_id": nurse_id})
        )
        return meta["total_count"]

    def test_cross_nurse_reference_beats_nurse_state(self):
        """PRD §2.9: "Every request flows through a single ordered validation pipeline,
        and a request violating several checks receives the error from the earliest
        stage it fails."
        PRD §3.8: "...and a `license_id` belonging to a different nurse than the
        payload's `nurse_id` is `ERR_CROSS_NURSE_REFERENCE`."
        PRD §3.8: "The subject nurse must be `ACTIVE`, else `ERR_INVALID_NURSE_STATE`,
        ..."

        Design: Difficulty/priority_pair_validation_conflict/discipline_create_referential_beats_state
        """
        _ctx_a, nurse_a, _nurse_b, lic_b = self._setup_ann_terminated_and_bob()
        assert get_nurse(nurse_a["id"])["status"] == "TERMINATED"

        resp = api_client.create_disciplinary_action(
            {"nurse_id": nurse_a["id"], "scope": "LICENSE", "action_type": "SUSPENSION",
             "effective_on": "2026-08-01", "license_id": lic_b["id"]},
            CO1,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_NURSE_REFERENCE)
        assert self._discipline_count(nurse_a["id"]) == 0

    def test_state_gate_fires_when_referential_check_passes(self):
        """PRD §3.8: "The subject nurse must be `ACTIVE`, else
        `ERR_INVALID_NURSE_STATE`, and `effective_on` must not lie in the future, else
        `ERR_DISCIPLINE_EFFECTIVE_FUTURE`."
        PRD §2.9: "Every request flows through a single ordered validation pipeline,
        and a request violating several checks receives the error from the earliest
        stage it fails."

        Design: Difficulty/priority_pair_validation_conflict/discipline_create_referential_beats_state
        """
        ctx_a, nurse_a, _nurse_b, _lic_b = self._setup_ann_terminated_and_bob()
        # Only the state violation is present: nurse A is TERMINATED, and the named
        # license is her own (referential integrity holds).
        resp = api_client.create_disciplinary_action(
            {"nurse_id": nurse_a["id"], "scope": "LICENSE", "action_type": "SUSPENSION",
             "effective_on": "2026-08-01", "license_id": ctx_a["license"]["id"]},
            CO1,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_NURSE_STATE)
        assert self._discipline_count(nurse_a["id"]) == 0


class TestDisciplineStateAndTemporalRules:
    def test_discipline_resolve_from_reported_rejected(self):
        """PRD §3.8: "Resolution moves the action from `ADJUDICATED` to `RESOLVED` —
        from any other state, `ERR_INVALID_DISCIPLINE_STATE` — and requires a
        `resolution_note`, else `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/discipline_resolve_from_reported_rejected
        """
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Rep Solve", email="rep.solve@x.com")
        action = report_discipline(ctx["nurse"]["id"], scope="PRIVILEGE",
                                   action_type="REPRIMAND", effective_on="2026-08-01")
        resp = api_client.resolve_disciplinary_action(
            action["id"], {"resolution_note": "too early"}, CO1
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DISCIPLINE_STATE)
        after = validate_success(api_client.get_disciplinary_action(action["id"], CO1), 200)
        assert after["status"] == "REPORTED"

    def test_discipline_effective_future_rejected(self):
        """PRD §3.8: "The subject nurse must be `ACTIVE`, else
        `ERR_INVALID_NURSE_STATE`, and `effective_on` must not lie in the future, else
        `ERR_DISCIPLINE_EFFECTIVE_FUTURE`."

        Design: Corner/validations/discipline_effective_future_rejected
        """
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Eff Future", email="eff.future@x.com")
        nurse = ctx["nurse"]

        resp = api_client.create_disciplinary_action(
            {"nurse_id": nurse["id"], "scope": "PRIVILEGE", "action_type": "REPRIMAND",
             "effective_on": "2026-08-02"},
            CO1,
        )
        validate_error(resp, ApiErrorId.ERR_DISCIPLINE_EFFECTIVE_FUTURE)

        ok = validate_success(
            api_client.create_disciplinary_action(
                {"nurse_id": nurse["id"], "scope": "PRIVILEGE",
                 "action_type": "REPRIMAND", "effective_on": "2026-08-01"},
                CO1,
            ),
            201,
        )
        assert ok["status"] == "REPORTED", "effective_on == current_date is accepted"

    def test_resolve_premature_rejected(self):
        """PRD §3.8: "A minimum active period must have elapsed since `effective_on`:
        none for `REPRIMAND`, 90 days for `PROBATION`, 30 days for `SUSPENSION`, and
        365 days for `REVOCATION`; resolving earlier is `ERR_RESOLUTION_PREMATURE`."

        Design: Corner/validations/resolve_premature_rejected
        """
        set_clock()
        ctx = setup_credentialed_nurse(full_name="Pre Mature", email="pre.mature@x.com")
        nurse, lic = ctx["nurse"], ctx["license"]
        action = report_discipline(nurse["id"], scope="LICENSE",
                                   action_type="SUSPENSION", effective_on="2026-08-01",
                                   license_id=lic["id"])
        acknowledge_discipline(action["id"], headers=CO1)
        adjudicate_discipline(action["id"], outcome="SUSTAINED", headers=CO2)

        # 29 days after effective_on: the 30-day minimum is not yet met.
        set_clock("2026-08-30T00:00:00Z")
        resp = api_client.resolve_disciplinary_action(
            action["id"], {"resolution_note": "early"}, CO1
        )
        validate_error(resp, ApiErrorId.ERR_RESOLUTION_PREMATURE)
        after = validate_success(api_client.get_disciplinary_action(action["id"], CO1), 200)
        assert after["status"] == "ADJUDICATED"
        assert get_license(lic["id"])["status"] == "ENCUMBERED"
