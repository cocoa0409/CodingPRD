"""Lifecycle contracts read one machine at a time: the state a row opens in, the
transitions that are refused because the source state does not declare them, the
terminal states nothing escapes, the preconditions that are checked apart from the
source state, and the side effects a transition drags along with it.
"""

from test_helpers import (
    DEFAULT_LOGICAL_CLOCK,
    FULL_PASS_SCREENING,
    NO_PSYCH_SCREENING,
    TEST_USERS,
    ApiErrorId,
    assert_money,
    create_agreement_payload,
    get_agreement,
    get_applicant,
    get_applicant_version,
    get_production,
    get_shoot_block,
    record_screening_items,
    resolve_complaint,
    set_clock,
    setup_applicant,
    setup_casting_call,
    setup_docusoap_production,
    setup_drafted_agreement,
    setup_executed_agreement,
    setup_minor_applicant,
    setup_minor_protection,
    setup_planned_welfare_protocol,
    setup_production,
    setup_published_casting_call,
    setup_routed_complaint,
    setup_sent_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["production_admin_headers"]
CD = TEST_USERS["casting_director_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]
BA1 = TEST_USERS["business_affairs_headers"]
BA2 = TEST_USERS["business_affairs_2_headers"]
WO1 = TEST_USERS["welfare_officer_headers"]

# The coverage span the recipes of this file use for welfare instruments.
WIDE_COVERAGE = {
    "coverage_start_utc": "2026-09-01T00:00:00Z",
    "coverage_end_utc": "2026-12-31T00:00:00Z",
}

# A GA packet: the state floor is 10 tutoring hours and a tenth of the stipend,
# so 12 hours at fifteen hundredths clears both.
GA_PACKET = {
    "work_permit_number": "GA-77421",
    "education_hours_scheduled_weekly": 12,
    "trust_deposit_pct": 0.15,
}

# A two-episode per-episode deal on a nine-episode docusoap.
DOCUSOAP_TERMS = {
    "exclusivity_window_days": 0,
    "confidentiality_tier": "STANDARD",
    "depiction_rights_scope": "FULL",
    "stipend_structure": "PER_EPISODE",
    "base_stipend_cents": 100_000,
    "episodes_committed": 2,
}


def _harbour_nights(**overrides):
    return setup_docusoap_production(title="Harbour Nights S1", **overrides)


def _referral_call(production_id):
    return setup_casting_call(
        production_id, channel="REFERRAL", min_age=13, max_age=60,
        exclusivity_window_days=0,
    )


def _cleared_adult(production_id, items=NO_PSYCH_SCREENING):
    """A published referral call plus one adult applicant cleared on it."""
    call = setup_published_casting_call(
        production_id, channel="REFERRAL", min_age=13, max_age=60,
        exclusivity_window_days=0,
    )
    applicant = setup_applicant(
        call["id"], legal_name="Ada Reyes", date_of_birth="1994-04-02",
        residency_state_code="GA",
    )
    record_screening_items(applicant["id"], items)
    return call, applicant


class TestCastingCallLifecycle:
    """A call opens in DRAFT, publishes exactly once, and closes only from
    PUBLISHED."""

    def test_a_freshly_drafted_call_opens_in_draft_with_nothing_stamped(self, api):
        """PRD §3.2: "A freshly drafted call sits in `DRAFT` status, has never
        been published, and carries no closing reason."
        PRD §3.2: "Alongside its lifecycle fields each call maintains
        `screened_pass_count`, the number of applicants arriving through it whose
        `screening_status` has reached `CLEARED` or `CAST`; the counter is
        incremented by one each time one of the call's applicants clears
        screening."
        PRD §3.2: "`open_call_window_start_utc` and `open_call_window_end_utc`
        bound the intake window inclusively at both ends, and
        `expected_attendance` forecasts the head count, defaulting to 0 and never
        negative."

        Design: Corner/state_machines/casting_call_initial_state_is_draft_with_null_publish_fields
        """
        production = _harbour_nights()

        call = validate_success(
            api.create_casting_call(
                {
                    "production_id": production["id"],
                    "channel": "REFERRAL",
                    "min_age": 13,
                    "max_age": 60,
                    "exclusivity_window_days": 0,
                },
                CD,
            ),
            201,
        )
        assert call["status"] == "DRAFT"
        assert call["published_at"] is None
        assert call["closed_reason"] is None
        assert call["screened_pass_count"] == 0
        assert call["version"] == 1
        # A referral call names no venue and forecasts no attendance.
        assert call["venue_location_id"] is None
        assert call["expected_attendance"] == 0

    def test_closing_a_draft_is_refused_and_the_same_call_closes_once_published(
        self, api
    ):
        """PRD §2.6: "The addressed entity is in a state from which the requested
        transition is declared, otherwise `ERR_INVALID_STATE_TRANSITION` (409).
        This rung applies to every action endpoint."
        PRD §3.2: "A director may retire a live call at any time, moving it
        `PUBLISHED → CLOSED` with `closed_reason` recorded as `DIRECTOR_CLOSED`."
        PRD §3.2: "On success the call's status becomes `PUBLISHED` and
        `published_at` is stamped with the logical clock's current instant."

        Design: Corner/state_machines/casting_call_close_from_draft_rejected
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])

        validate_error(
            api.close_casting_call(call["id"], CD),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )
        still_draft = validate_success(api.get_casting_call(call["id"], CD))
        assert still_draft["status"] == "DRAFT"
        assert still_draft["closed_reason"] is None

        published = validate_success(api.publish_casting_call(call["id"], CD))
        assert published["status"] == "PUBLISHED"
        assert published["published_at"].startswith(DEFAULT_LOGICAL_CLOCK[:19])

        closed = validate_success(api.close_casting_call(call["id"], CD))
        assert closed["status"] == "CLOSED"
        assert closed["closed_reason"] == "DIRECTOR_CLOSED"

    def test_publishing_twice_is_refused_rather_than_restamping(self, api):
        """PRD §3.2: "Publication is refused unless the call is genuinely in
        `DRAFT`; unless the owning production's posture is `OPEN`, since both
        `RESTRICTED` and `FROZEN` productions reject publication; and, when the
        `channel` is `OPEN_CALL`, unless the venue, both window bounds and the
        expected attendance are all present."
        PRD §2.6: "The addressed entity is in a state from which the requested
        transition is declared, otherwise `ERR_INVALID_STATE_TRANSITION` (409)."

        Design: Corner/state_machines/casting_call_publish_twice_rejected
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        first = validate_success(api.publish_casting_call(call["id"], CD))

        validate_error(
            api.publish_casting_call(call["id"], CD),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )

        # Publication is not a retry-safe stamp: neither the timestamp nor the
        # version counter moved on the refused attempt.
        unchanged = validate_success(api.get_casting_call(call["id"], CD))
        assert unchanged["status"] == "PUBLISHED"
        assert unchanged["published_at"] == first["published_at"]
        assert unchanged["version"] == first["version"]


class TestComplaintTerminalState:
    """RESOLVED is a terminal state on the complaint machine, and the aftercare
    fork touches nothing on the production."""

    def test_a_resolved_complaint_refuses_both_resolve_and_triage(self, api):
        """PRD §3.9: "Both branches join at resolution. A `WelfareOfficer` moves
        the complaint to `RESOLVED` from either `AFTERCARE_ACTIVE` or
        `ESCALATED`, recording a closing `resolution_note`."
        PRD §3.9: "The aftercare branch is the quiet one. It moves the complaint
        `TRIAGED → AFTERCARE_ACTIVE`, stamps `routed_by_user_id`, writes
        `aftercare_sessions_authorized` from the pre-transition tier, leaves
        `duty_of_care_breach` false, and mutates no field on the production
        whatsoever."
        PRD §3.9: "The base session count is 2 sessions at severity 1, 4 at
        severity 2, 8 at severity 3, 12 at severity 4 and 16 at severity 5."
        PRD §3.9: "A `WelfareOfficer` then triages, moving the complaint `OPEN →
        TRIAGED` and stamping `triaged_by_user_id` with the caller's
        `X-User-ID`."

        Design: Corner/state_machines/complaint_resolve_from_terminal_resolved_rejected
        """
        production = _harbour_nights()
        _call, applicant = _cleared_adult(production["id"])
        agreement = setup_executed_agreement(
            applicant["id"], production["id"], **DOCUSOAP_TERMS
        )

        routed = setup_routed_complaint(
            agreement["id"],
            applicant["id"],
            route="AFTERCARE",
            triage_headers=WO1,
            route_headers=WO1,
            category="PAYMENT",
            severity=2,
            narrative="Second stipend instalment was not paid on the agreed date.",
        )
        # Severity 2 is a base of 4 sessions, and a STANDARD tier multiplies it
        # by one, well under the ceiling of 24.
        assert routed["aftercare_sessions_authorized"] == 4
        assert routed["duty_of_care_breach"] is False

        resolved = resolve_complaint(
            routed["id"], WO1, "Instalment paid; participant satisfied."
        )
        assert resolved["status"] == "RESOLVED"

        validate_error(
            api.resolve_complaint(
                routed["id"], {"resolution_note": "Duplicate closure attempt."}, WO1
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )
        validate_error(
            api.triage_complaint(routed["id"], WO1),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )

        rows, _meta = validate_paginated(api.list_complaints(agreement["id"], WO1))
        final = rows[0]
        assert final["status"] == "RESOLVED"
        assert final["resolution_note"] == "Instalment paid; participant satisfied."
        assert final["triaged_by_user_id"] == "wo_1"
        assert final["routed_by_user_id"] == "wo_1"

        # The quiet fork left the production alone.
        untouched = get_production(production["id"])
        assert untouched["welfare_incident_count"] == 0
        assert untouched["duty_of_care_tier"] == "STANDARD"
        assert untouched["casting_posture"] == "OPEN"


class TestWelfareProtocolLifecycle:
    """Cancellation is terminal, activation carries its own coverage
    precondition, and the committed figure is a full recompute either way."""

    def test_activation_after_cancellation_is_refused_and_the_cost_stays_out(
        self, api
    ):
        """PRD §3.7: "Activation moves a protocol `PLANNED → ACTIVE` and is
        admitted only from `PLANNED`, only when an insurance rider carries its
        certificate, and only while `coverage_end_utc` is still later than the
        logical clock — coverage that is already over cannot be activated."
        PRD §3.7: "Step one sums `cost_cents` over the production's protocols
        whose `status` is `PLANNED` or `ACTIVE`, excluding both `EXPIRED` and
        `CANCELLED` rows, to give the protocol subtotal; coverage dates play no
        part in membership, only the sweep's expiry transition does."
        PRD §3.7: "Cancellation moves a protocol to `CANCELLED` from either
        `PLANNED` or `ACTIVE`, and it is the exact compensating action for
        planning one."

        Design: Corner/state_machines/welfare_protocol_activate_after_cancel_rejected
        """
        production = _harbour_nights()
        protocol = setup_planned_welfare_protocol(
            production["id"], kind="AFTERCARE_PROGRAM", cost_cents=1_000_000,
            **WIDE_COVERAGE,
        )
        assert protocol["status"] == "PLANNED"
        # A 1,000,000 subtotal sits in the four-hundredths band, and a STANDARD
        # tier factor of one leaves a 40,000 surcharge.
        assert_money(
            get_production(production["id"])["welfare_committed_cents"],
            1_040_000,
            "committed welfare while planned",
        )

        cancelled = validate_success(api.cancel_welfare_protocol(protocol["id"], WO1))
        assert cancelled["status"] == "CANCELLED"

        validate_error(
            api.activate_welfare_protocol(protocol["id"], WO1),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )
        rows, _meta = validate_paginated(
            api.list_welfare_protocols(production["id"], WO1)
        )
        assert [row["status"] for row in rows] == ["CANCELLED"]
        after = get_production(production["id"])
        assert_money(after["welfare_committed_cents"], 0, "committed welfare")
        assert after["casting_posture"] == "OPEN"

    def test_activating_coverage_that_is_already_over_is_refused(self, api):
        """PRD §3.7: "Activation moves a protocol `PLANNED → ACTIVE` and is
        admitted only from `PLANNED`, only when an insurance rider carries its
        certificate, and only while `coverage_end_utc` is still later than the
        logical clock — coverage that is already over cannot be activated."
        PRD §2.5: "On start-up the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it continues to read that instant until an
        administrator moves it; under no circumstance does it fall back to the
        host's real time."
        PRD §3.7: "Notably, because `PLANNED` and `ACTIVE` rows both count,
        activating a protocol leaves the subtotal unchanged, and because
        cancelled rows drop out, cancelling one removes its cost exactly."

        Design: Corner/state_machines/welfare_protocol_activate_with_coverage_already_over_rejected
        """
        production = _harbour_nights()
        protocol = setup_planned_welfare_protocol(
            production["id"],
            kind="DUTY_OF_CARE_OFFICER",
            coverage_start_utc="2026-06-01T00:00:00Z",
            coverage_end_utc="2026-07-01T00:00:00Z",
            cost_cents=500_000,
        )

        # The window closed a month before the clock's opening instant.
        validate_error(
            api.activate_welfare_protocol(protocol["id"], WO1),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )

        rows, _meta = validate_paginated(
            api.list_welfare_protocols(production["id"], WO1)
        )
        assert [row["status"] for row in rows] == ["PLANNED"]
        # A refused activation is not a release: a planned row still counts, so
        # 500,000 plus a 20,000 surcharge stays committed.
        assert_money(
            get_production(production["id"])["welfare_committed_cents"],
            520_000,
            "committed welfare",
        )

    def test_cancelling_the_second_protocol_returns_the_figure_exactly(self, api):
        """PRD §3.7: "Step three multiplies the subtotal by that band rate and
        again by the tier factor for the production's current
        `duty_of_care_tier` — one for `STANDARD`, one and a half for `ENHANCED`,
        two for `CRITICAL` — rounding the product half up to whole cents to give
        the duty-of-care surcharge."
        PRD §3.7: "Step four sets `welfare_committed_cents` to the protocol
        subtotal plus that surcharge."
        PRD §2.11: "Each is defined as a full recomputation over its contributing
        child records, never as an incremental delta applied to the previous
        value, and each is recomputed in the same request as the write that
        changed its inputs."

        Design: Corner/state_machines/welfare_protocol_cancel_reverses_the_commitment_without_drift
        """
        production = setup_production(
            title="Island Trials S2", season_number=2, episode_order=9,
            minor_participant_cap=2,
        )
        assert production["duty_of_care_tier"] == "ENHANCED"

        first = setup_planned_welfare_protocol(
            production["id"], kind="DUTY_OF_CARE_OFFICER", cost_cents=1_000_000,
            **WIDE_COVERAGE,
        )
        # 1,000,000 in the four-hundredths band gives 40,000, and the ENHANCED
        # factor of one and a half lifts that to 60,000.
        committed_one = get_production(production["id"])["welfare_committed_cents"]
        assert_money(committed_one, 1_060_000, "committed welfare with one protocol")

        second = setup_planned_welfare_protocol(
            production["id"], kind="ONSET_PSYCH_SUPPORT", cost_cents=1_000_000,
            **WIDE_COVERAGE,
        )
        # 2,000,000 is still inside the four-hundredths band: 80,000 x 1.5.
        assert_money(
            get_production(production["id"])["welfare_committed_cents"],
            2_120_000,
            "committed welfare with two protocols",
        )

        cancelled = validate_success(api.cancel_welfare_protocol(second["id"], WO1))
        assert cancelled["status"] == "CANCELLED"

        back = get_production(production["id"])
        assert_money(back["welfare_committed_cents"], 1_060_000, "committed welfare")
        assert back["welfare_committed_cents"] == committed_one
        assert back["casting_posture"] == "OPEN"
        rows, _meta = validate_paginated(
            api.list_welfare_protocols(production["id"], WO1, {"status": "PLANNED"})
        )
        assert [row["id"] for row in rows] == [first["id"]]


class TestMinorProtectionStatusIsRederivedOnEveryAmendment:
    """The packet's derived status moves in both directions as the permit date
    crosses the clock."""

    def test_an_expired_permit_drops_the_packet_and_a_future_one_restores_it(
        self, api
    ):
        """PRD §3.5: "It becomes `COMPLETE` when all three of its conditions hold
        together — the permit's expiry date is strictly after the logical clock's
        date, the scheduled education hours are at least the jurisdiction's
        weekly minimum, and the trust percentage is at least the jurisdiction's
        minimum fraction — and `INCOMPLETE` otherwise."
        PRD §3.5: "Amendment re-derives the status in both directions with equal
        force: a packet may be patched with any of `work_permit_number`,
        `permit_expires_on`, `education_hours_scheduled_weekly` or
        `trust_deposit_pct`, and where the amended packet satisfies all three
        conditions it moves `INCOMPLETE → COMPLETE`, while where the amended
        packet no longer satisfies all three it moves `COMPLETE → INCOMPLETE`."
        PRD §2.12: "The weekly on-set tutoring minimum is 15 hours in `CA`, 12
        hours in `NY`, 10 hours in `GA` and 12 hours in `IL`".
        PRD §2.4: "`version`, an integer that begins at 1 when the record is
        created and increases by exactly one on every mutation."

        Design: Corner/state_machines/minor_protection_patch_expired_permit_drops_complete_to_incomplete
        """
        production = _harbour_nights()
        call = setup_published_casting_call(
            production["id"], channel="REFERRAL", min_age=13, max_age=60,
            exclusivity_window_days=0,
        )
        applicant = setup_minor_applicant(
            call["id"], legal_name="Mila Grant", date_of_birth="2011-05-20",
            residency_state_code="GA", guardian_name="Dana Ruiz",
        )
        assert applicant["is_minor"] is True

        packet = setup_minor_protection(
            applicant["id"], permit_expires_on="2026-12-31", **GA_PACKET
        )
        assert packet["status"] == "COMPLETE"

        lapsed = validate_success(
            api.patch_minor_protection(
                packet["id"], {"permit_expires_on": "2026-07-01"}, CO1
            )
        )
        assert lapsed["status"] == "INCOMPLETE"

        restored = validate_success(
            api.patch_minor_protection(
                packet["id"], {"permit_expires_on": "2026-12-31"}, CO1
            )
        )
        assert restored["status"] == "COMPLETE"
        assert restored["version"] == lapsed["version"] + 1
        # Only the permit date ever moved.
        assert restored["education_hours_scheduled_weekly"] == 12
        assert restored["trust_deposit_pct"] == 0.15
        assert_money(restored["trust_deposited_cents"], 0, "deposited trust")


class TestAgreementSupersedeCascade:
    """Naming a prior draft in supersedes_agreement_id voids it in the same
    request."""

    def test_the_superseding_draft_voids_its_predecessor_in_the_same_request(
        self, api
    ):
        """PRD §3.6: "A draft may finally name `supersedes_agreement_id`, the
        same applicant's prior non-terminal agreement that this one replaces;
        when supplied, that prior agreement — which must belong to the same
        applicant and be in `DRAFTED`, `SENT`, `COUNTERED` or `REVISED` status —
        moves to `VOIDED` with `void_reason` set to `SUPERSEDED` and its
        `version` incremented by one."
        PRD §3.6: "Drafting opens the agreement at `status` `DRAFTED` with
        `round_number` at 0, both stipend figures at 0, `welfare_hold` false, and
        it increments the applicant's `version` by one."
        PRD §2.11: "Agreements in `DRAFTED`, `SENT`, `COUNTERED` or `REVISED`
        status contribute nothing, and `VOIDED` agreements both fall outside the
        summed set and carry a zeroed `total_stipend_commitment_cents`, so
        voiding is an exact reversal of executing."

        Design: Corner/state_machines/agreement_supersede_cascade_voids_the_prior_draft
        """
        production = _harbour_nights()
        _call, applicant = _cleared_adult(production["id"])

        version_before = get_applicant_version(applicant["id"])
        first = setup_drafted_agreement(
            applicant["id"], production["id"], **DOCUSOAP_TERMS
        )
        assert first["status"] == "DRAFTED"

        version_after = get_applicant_version(applicant["id"])
        assert version_after == version_before + 1

        second = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    applicant["id"],
                    production["id"],
                    version_after,
                    exclusivity_window_days=0,
                    confidentiality_tier="ENHANCED",
                    depiction_rights_scope="LIMITED",
                    stipend_structure="PER_EPISODE",
                    base_stipend_cents=120_000,
                    episodes_committed=3,
                    supersedes_agreement_id=first["id"],
                ),
                BA1,
            ),
            201,
        )
        assert second["status"] == "DRAFTED"
        assert second["supersedes_agreement_id"] == first["id"]

        superseded = get_agreement(first["id"])
        assert superseded["status"] == "VOIDED"
        assert superseded["void_reason"] == "SUPERSEDED"
        assert_money(
            superseded["total_stipend_commitment_cents"], 0, "superseded total"
        )
        # Neither draft is executed, so nothing was ever committed.
        assert_money(
            get_production(production["id"])["stipend_committed_cents"],
            0,
            "committed stipend",
        )


class TestWelfareEpochSweepSideEffects:
    """One sweep applies every consequence the clock has made true, and a second
    sweep over the same rows changes nothing."""

    def test_the_sweep_lapses_the_permit_expires_the_medical_and_holds_the_send(
        self, api
    ):
        """PRD §3.7: "Every `COMPLETE` minor-protection packet whose
        `permit_expires_on` is at or before the logical clock becomes `LAPSED`,
        and sets `welfare_hold` on that applicant's agreements in `SENT`,
        `COUNTERED`, `REVISED` or `EXECUTED` status."
        PRD §3.7: "Every applicant whose latest `MEDICAL_EXAM` item has an
        `expires_at` at or before the logical clock moves `medical_status` from
        `CLEARED` to `EXPIRED`."
        PRD §2.6: "The addressed agreement's `welfare_hold` is false. This guards
        all four negotiation writes — send, counter-offer, revise and execute —
        and a held agreement is rejected with `ERR_WELFARE_HOLD_ACTIVE` (409)."
        PRD §3.7: "The sweep is the only mechanism that applies expiry, lapse and
        breach; moving the logical clock alone changes nothing."

        Design: Corner/state_machines/welfare_run_lapses_permit_expires_medical_and_holds_the_agreement
        """
        production = _harbour_nights()
        call = setup_published_casting_call(
            production["id"], channel="REFERRAL", min_age=13, max_age=60,
            exclusivity_window_days=0,
        )
        applicant = setup_minor_applicant(
            call["id"], legal_name="Mila Grant", date_of_birth="2011-05-20",
            residency_state_code="GA", guardian_name="Dana Ruiz",
        )
        record_screening_items(applicant["id"], FULL_PASS_SCREENING)
        packet = setup_minor_protection(
            applicant["id"], permit_expires_on="2026-08-20", **GA_PACKET
        )
        assert packet["status"] == "COMPLETE"

        sent = setup_sent_agreement(
            applicant["id"], production["id"], **DOCUSOAP_TERMS
        )
        assert sent["status"] == "SENT"
        # Forward-looking episode count max(2, 9) = 9 at tier 1.30 gives
        # 1,170,000, plus a two-appearance press reserve and the unconditional
        # reunion charge; a docusoap attracts no hazard uplift.
        assert_money(
            sent["provisional_stipend_cents"], 1_370_000, "provisional stipend"
        )

        set_clock("2026-09-01T00:00:00Z")
        validate_success(api.run_welfare_epoch(production["id"], PA))

        packets, _pmeta = validate_paginated(
            api.list_minor_protections(applicant["id"], CO1)
        )
        assert [row["status"] for row in packets] == ["LAPSED"]

        # The medical exam was recorded at the opening instant and is valid for
        # 30 days, so 2026-08-31 has already passed.
        swept = get_applicant(applicant["id"])
        assert swept["medical_status"] == "EXPIRED"
        assert swept["screening_status"] == "CLEARED"

        held = get_agreement(sent["id"])
        assert held["welfare_hold"] is True
        assert held["status"] == "SENT"

        # The hold rung outranks the medical-clearance rung, so the hold is what
        # the caller hears.
        validate_error(
            api.execute_agreement(sent["id"], BA2),
            ApiErrorId.ERR_WELFARE_HOLD_ACTIVE.value,
            409,
        )
        assert_money(
            get_agreement(sent["id"])["total_stipend_commitment_cents"],
            0,
            "final stipend",
        )
        assert_money(
            get_production(production["id"])["stipend_committed_cents"],
            0,
            "committed stipend",
        )

    def test_two_overdue_obligations_breach_and_a_second_sweep_double_counts_none(
        self, api
    ):
        """PRD §3.9: "An obligation left unfulfilled past its due date is caught
        by the welfare epoch sweep, which moves it `SCHEDULED → BREACHED` when
        `due_utc` falls at or before the logical clock, increments the
        production's `breached_obligation_count`, and — once the owning agreement
        carries two or more breached obligations — sets that agreement's
        `welfare_hold` to true, so that repeat non-appearance freezes the
        participant's contractual position."
        PRD §3.9: "For each ordinal from 1 up to
        `press_appearance_obligation_count`, a press obligation is created with
        `kind` `PRESS_JUNKET`, its `sequence_ordinal` set to that ordinal, its
        `fee_cents` set to the press appearance rate of 25,000 cents, and its
        `due_utc` set to the production's `photography_end_utc` advanced by 30
        days multiplied by the ordinal — so the first junket falls 30 days after
        wrap, the second 60 days after, the third 90 days after, and so on."
        PRD §3.9: "Then, and only when `reunion_obligation` is true, a single
        reunion obligation is created with `kind` `REUNION_TAPING`,
        `sequence_ordinal` 1, `fee_cents` of 150,000 cents, and `due_utc` set to
        `photography_end_utc` advanced by 180 days."

        Design: Corner/state_machines/welfare_run_breaches_two_overdue_obligations_and_sets_the_hold
        """
        production = _harbour_nights()
        _call, applicant = _cleared_adult(production["id"])

        sent = setup_sent_agreement(
            applicant["id"],
            production["id"],
            press_appearance_obligation_count=2,
            reunion_obligation=True,
            **DOCUSOAP_TERMS,
        )
        # max(2, 9) = 9 at tier 1.30 is 1,170,000, the press count is charged at
        # 2 + 2 reserved appearances, and the reunion is charged regardless.
        assert_money(
            sent["provisional_stipend_cents"], 1_420_000, "provisional stipend"
        )

        executed = validate_success(api.execute_agreement(sent["id"], BA2))
        # The final variant takes 2 episodes at tier 1.00, the contracted two
        # junkets and the reunion actually owed.
        assert_money(
            executed["total_stipend_commitment_cents"], 400_000, "final stipend"
        )

        rows, meta = validate_paginated(api.list_post_obligations(sent["id"], BA1))
        assert meta["total_count"] == 3
        # Photography ends 2026-12-15; the first junket falls 30 days later.
        assert rows[0]["kind"] == "PRESS_JUNKET"
        assert rows[0]["due_utc"].startswith("2027-01-14T00:00:00")
        assert_money(rows[0]["fee_cents"], 25_000, "press fee")
        assert rows[1]["due_utc"].startswith("2027-02-13T00:00:00")
        assert rows[2]["kind"] == "REUNION_TAPING"
        assert rows[2]["due_utc"].startswith("2027-06-13T00:00:00")

        set_clock("2027-02-20T00:00:00Z")
        first_sweep = validate_success(api.run_welfare_epoch(production["id"], PA))
        assert first_sweep["breached_obligation_count"] == 2
        assert get_agreement(sent["id"])["welfare_hold"] is True

        second_sweep = validate_success(api.run_welfare_epoch(production["id"], PA))
        assert second_sweep["breached_obligation_count"] == 2, (
            "the breached rows are no longer SCHEDULED, so nothing is counted twice"
        )

        after, _ameta = validate_paginated(api.list_post_obligations(sent["id"], BA1))
        assert [row["status"] for row in after] == [
            "BREACHED",
            "BREACHED",
            "SCHEDULED",
        ]
        # The reunion is not due until 2027-06-13, so it still stands.
        assert after[2]["kind"] == "REUNION_TAPING"
        assert get_applicant(applicant["id"])["medical_status"] == "EXPIRED"
        assert_money(
            get_production(production["id"])["stipend_committed_cents"],
            400_000,
            "committed stipend",
        )


class TestShootBlockWrapSourceState:
    """Wrap is declared from ROLLING alone, and a vacuously complete block
    proves the refusal is the source-state check."""

    def test_wrapping_a_scheduled_block_is_refused_on_its_source_state(self, api):
        """PRD §3.8: "Wrapping moves a block `ROLLING → WRAPPED`, is admitted
        only from `ROLLING`, and re-evaluates coverage at wrap time; incomplete
        coverage is refused with `ERR_RELEASE_COVERAGE_INCOMPLETE`."
        PRD §3.8: "A block expecting no crowd at all, with no releases collected,
        is vacuously complete, because the sum over an empty set is 0 and 0 is
        not less than 0."
        PRD §2.6: "The addressed entity is in a state from which the requested
        transition is declared, otherwise `ERR_INVALID_STATE_TRANSITION` (409).
        This rung applies to every action endpoint."

        Design: Corner/state_machines/shoot_block_wrap_from_scheduled_rejected
        """
        production = _harbour_nights()
        venue = validate_success(
            api.create_location(
                {
                    "name": "Pier 7 Stage",
                    "state_code": "GA",
                    "capacity": 400,
                    "turnaround_buffer_minutes": 60,
                },
                PA,
            ),
            201,
        )
        block = validate_success(
            api.create_shoot_block(
                {
                    "production_id": production["id"],
                    "location_id": venue["id"],
                    "block_kind": "STUDIO",
                    "start_utc": "2026-09-20T08:00:00Z",
                    "end_utc": "2026-09-20T12:00:00Z",
                    "participant_agreement_ids": [],
                },
                PA,
            ),
            201,
        )
        assert block["status"] == "SCHEDULED"
        assert block["expected_crowd_headcount"] == 0
        # No crowd is forecast and no release exists, so the coverage that wrap
        # re-evaluates is vacuously complete and the coverage rung could not
        # have fired; the refusal below can only be the source-state check.

        validate_error(
            api.wrap_shoot_block(block["id"], PA),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )
        after = get_shoot_block(block["id"])
        assert after["status"] == "SCHEDULED"
        assert after["covered_head_count"] == 0
