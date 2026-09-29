"""Access is settled on four independent axes: which roles may invoke an
owner-only creation at all, which rows a participant may reach among peers holding
the same role, and the two segregation rules that lock a single operator out of
the second half of a decision they already touched — one scoped per applicant,
one anchored on the latest production-side proposer. The last surface is the read
every role shares, where the participant's ownership filter deliberately does not
apply.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_money,
    create_agreement_payload,
    create_docusoap_production_payload,
    create_production_payload,
    create_screening_item_payload,
    counter_offer_payload,
    get_agreement,
    get_applicant,
    get_applicant_version,
    make_applicant_headers,
    make_business_affairs_headers,
    record_screening_items,
    revise_payload,
    setup_applicant,
    setup_docusoap_production,
    setup_drafted_agreement,
    setup_production,
    setup_published_casting_call,
    validate_error,
    validate_success,
)

PA = TEST_USERS["production_admin_headers"]
CD = TEST_USERS["casting_director_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]
CO2 = TEST_USERS["compliance_officer_2_headers"]
BA1 = TEST_USERS["business_affairs_headers"]
WO1 = TEST_USERS["welfare_officer_headers"]
ANY_APPLICANT = TEST_USERS["applicant_headers"]

# A second business-affairs operator who will author the standing revision.
BA9 = make_business_affairs_headers("ba_9")

# A two-episode per-episode deal at a 100,000-cent episode rate.
BASE_TERMS = {
    "exclusivity_window_days": 0,
    "confidentiality_tier": "STANDARD",
    "depiction_rights_scope": "FULL",
    "stipend_structure": "PER_EPISODE",
    "base_stipend_cents": 100_000,
    "episodes_committed": 2,
}

THREE_ADULT_INSTRUMENTS = (
    ("INTERVIEW", "PASS", 0, CO1),
    ("BACKGROUND_CHECK", "PASS", 0, CO1),
    ("MEDICAL_EXAM", "PASS", 0, CO1),
)


def _harbour_nights(**overrides):
    return setup_docusoap_production(title="Harbour Nights S1", **overrides)


def _island_trials(**overrides):
    return setup_production(
        title="Island Trials S2",
        season_number=2,
        episode_order=9,
        photography_start_utc="2026-10-15T00:00:00Z",
        photography_end_utc="2027-01-15T00:00:00Z",
        minor_participant_cap=0,
        **overrides,
    )


def _referral_call(production_id, **overrides):
    kwargs = {
        "channel": "REFERRAL",
        "min_age": 13,
        "max_age": 60,
        "exclusivity_window_days": 0,
    }
    kwargs.update(overrides)
    return setup_published_casting_call(production_id, **kwargs)


class TestProductionCreationIsOwnerOnly:
    """Production creation names a single authorised role, and every other role —
    entity-backed or not — is turned away on the role rung rather than a later
    one."""

    def test_five_roles_are_refused_and_only_the_owning_role_succeeds(self, api):
        """PRD §4: "| `POST` | `/casting/productions` | Create a production |
        `ProductionAdmin` |"
        PRD §2.6: "The declared role appears in the addressed endpoint's
        authorised-role list, otherwise `ERR_ROLE_FORBIDDEN` (403)."
        PRD §2.1: "If the header pair is well formed but the declared role is not
        permitted to invoke the addressed operation, the rejection is
        `ERR_ROLE_FORBIDDEN` (HTTP 403)."
        PRD §3.1: "The posture opens at `OPEN`, and every rolled-up figure opens
        at zero: `stipend_committed_cents`, `welfare_committed_cents`,
        `trust_escrow_balance_cents`, `welfare_incident_count`,
        `breached_obligation_count` and `minor_participant_count`."

        Design: Corner/rbac/casting_director_cannot_create_a_production_forbidden
        """
        body = create_docusoap_production_payload(title="Harbour Nights S1")

        for headers in (CD, CO1, BA1, WO1, ANY_APPLICANT):
            # 403 on the role rung, never a 401: the header pair is well formed.
            validate_error(
                api.create_production(dict(body), headers),
                ApiErrorId.ERR_ROLE_FORBIDDEN.value,
                403,
            )

        created = validate_success(api.create_production(dict(body), PA), 201)
        assert created["title"] == "Harbour Nights S1"
        assert created["casting_posture"] == "OPEN"


class TestParticipantOwnershipAmongPeers:
    """Two callers of the same role clear the role rung together and are then
    separated by the ownership rung, which answers 403 rather than 404."""

    def test_a_participant_reaches_only_their_own_applicant_and_agreement(self, api):
        """PRD §2.6: "When the declared role is `Applicant`, `X-User-ID` equals the
        applicant that owns the addressed resource — the applicant record itself,
        or the `applicant_id` of the addressed agreement or of the agreement under
        which the addressed complaint was filed. This ownership rung guards exactly
        five operations: reading one applicant, participant withdrawal, agreement
        counter-offer, filing a complaint against an agreement, and reading one
        agreement. A mismatch yields `ERR_NOT_RESOURCE_OWNER` (403)."
        PRD §2.1: "When `X-User-Role` is `Applicant`, by contrast, `X-User-ID` is
        the `id` of the acting `Applicant` record; ownership checks on any resource
        that references an applicant compare the resource's applicant reference to
        `X-User-ID`."
        PRD §2.1: "Concretely, a participant may read only their own applicant
        record, may withdraw only themselves, and may read, counter-offer against,
        or file a complaint against only an agreement whose `applicant_id` equals
        their own `X-User-ID`."
        PRD §4: "| `GET` | `/casting/applicants/{id}` | Read one applicant
        including both state dimensions and both risk-score variants |
        `ProductionAdmin`, `CastingDirector`, `ComplianceOfficer`,
        `BusinessAffairs`, `WelfareOfficer`, `Applicant` |"

        Design: Corner/rbac/applicant_cannot_read_another_applicants_record_forbidden
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        ada = setup_applicant(
            call["id"],
            legal_name="Ada Reyes",
            date_of_birth="1994-04-02",
            residency_state_code="GA",
        )
        bo = setup_applicant(
            call["id"],
            legal_name="Bo Lindqvist",
            date_of_birth="1990-01-10",
            residency_state_code="GA",
        )
        agreement_a = setup_drafted_agreement(ada["id"], production["id"], **BASE_TERMS)
        agreement_b = setup_drafted_agreement(bo["id"], production["id"], **BASE_TERMS)

        as_ada = make_applicant_headers(ada["id"])

        # Both rows exist; the refusal is about ownership, not existence.
        validate_error(
            api.get_applicant(bo["id"], as_ada),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
            403,
        )
        validate_error(
            api.get_agreement(agreement_b["id"], as_ada),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
            403,
        )

        own_applicant = validate_success(api.get_applicant(ada["id"], as_ada))
        assert own_applicant["legal_name"] == "Ada Reyes"
        own_agreement = validate_success(api.get_agreement(agreement_a["id"], as_ada))
        assert own_agreement["status"] == "DRAFTED"

        # An operator role is not narrowed by the ownership rung at all.
        staff_read = validate_success(api.get_applicant(bo["id"], CO1))
        assert staff_read["legal_name"] == "Bo Lindqvist"


class TestFourEyesScreening:
    """The screening rule bars one officer from holding both sides of the same
    applicant's background and psychological evidence, symmetrically and per
    applicant."""

    def test_one_officer_may_not_hold_both_kinds_for_the_same_applicant(self, api):
        """PRD §2.10: "The `ComplianceOfficer` who records a `BACKGROUND_CHECK`
        outcome for an applicant may not also record a `PSYCH_EVAL` outcome for
        that same applicant, and the converse holds as well: recording a
        `PSYCH_EVAL` outcome is refused when any `BACKGROUND_CHECK` item of the
        same applicant carries a `recorded_by_user_id` equal to the caller's
        `X-User-ID`, and recording a `BACKGROUND_CHECK` outcome is refused when any
        `PSYCH_EVAL` item of the same applicant does."
        PRD §2.6: "The four-eyes screening rule holds on both screening-outcome
        paths — opening a screening item with an outcome supplied, and recording
        the outcome of an existing item — otherwise `ERR_SEGREGATION_OF_DUTIES`
        (403)."
        PRD §3.4: "On success the item's `outcome` and `severity_flags` are
        written, `recorded_by_user_id` is stamped with the caller's `X-User-ID`,
        `recorded_at` is stamped with the logical clock, and `expires_at` is
        derived from the kind's validity window: a `MEDICAL_EXAM` clearance is
        valid for 30 days from `recorded_at`, a `PSYCH_EVAL` for 60 days, a
        `BACKGROUND_CHECK` for 180 days, and an `INTERVIEW` never expires, so its
        `expires_at` remains absent."
        PRD §2.10: "Neither rule can be waived."

        Design: Corner/rbac/four_eyes_screening_same_officer_cannot_record_both_checks
        """
        production = _island_trials()
        call = _referral_call(production["id"], min_age=18)
        ada = setup_applicant(
            call["id"],
            legal_name="Ada Reyes",
            date_of_birth="1994-04-02",
            residency_state_code="CA",
        )
        bo = setup_applicant(
            call["id"],
            legal_name="Bo Lindqvist",
            date_of_birth="1990-01-10",
            residency_state_code="CA",
        )

        # One officer takes opposite halves on two different applicants: the rule
        # is scoped per applicant, so this is admitted.
        ada_background = validate_success(
            api.create_screening_item(
                ada["id"], create_screening_item_payload("BACKGROUND_CHECK"), CO1
            ),
            201,
        )
        assert ada_background["recorded_by_user_id"] == "co_1"
        bo_psych = validate_success(
            api.create_screening_item(
                bo["id"], create_screening_item_payload("PSYCH_EVAL"), CO1
            ),
            201,
        )
        assert bo_psych["recorded_by_user_id"] == "co_1"

        # The same officer reaching for the counterpart kind on an applicant they
        # already touched is refused in both directions.
        validate_error(
            api.create_screening_item(
                ada["id"], create_screening_item_payload("PSYCH_EVAL"), CO1
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )
        validate_error(
            api.create_screening_item(
                bo["id"], create_screening_item_payload("BACKGROUND_CHECK"), CO1
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )

        ada_psych = validate_success(
            api.create_screening_item(
                ada["id"], create_screening_item_payload("PSYCH_EVAL"), CO2
            ),
            201,
        )
        assert ada_psych["recorded_by_user_id"] == "co_2"
        assert ada_psych["outcome"] == "PASS"
        bo_background = validate_success(
            api.create_screening_item(
                bo["id"], create_screening_item_payload("BACKGROUND_CHECK"), CO2
            ),
            201,
        )
        assert bo_background["recorded_by_user_id"] == "co_2"


class TestFourEyesExecution:
    """The execution rule reads the latest production-side proposer, not the
    drafter, so the lock moves with the negotiation."""

    def test_the_reviser_is_locked_out_while_the_original_drafter_is_not(self, api):
        """PRD §2.10: "The `BusinessAffairs` user who authored the most recent
        production-side negotiation round on an agreement, recorded on the
        agreement as `last_production_proposer_user_id`, may not be the user who
        executes it. Execution is permitted when
        `last_production_proposer_user_id` is absent — an agreement executed
        straight out of its first send has no production-side round — and
        otherwise only when the caller's `X-User-ID` differs from it. A caller who
        proposed the standing terms and then attempts to execute them is refused
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.6: "A negotiation round is appended with `proposed_by` as
        `PRODUCTION` and `disposition` as `REVISED`, carrying the revised terms and
        a `round_number` one greater than the current count;
        `last_production_proposer_user_id` is set to the revising user's
        `X-User-ID`, the agreement's `round_number` is incremented by one, and the
        status becomes `REVISED`."
        PRD §3.6: "Note what the cycle implies for the stipend computation:
        negotiation history is never re-read, because each revision has already
        overwritten the agreement's own term fields, and those current fields are
        the sole authority."
        PRD §3.6: "First, the final stipend variant is written to
        `total_stipend_commitment_cents`, the status becomes `EXECUTED`,
        `executed_by_user_id` is stamped with the caller's `X-User-ID`,
        `executed_at` is stamped with the logical clock, and the applicant's
        `screening_status` moves to `CAST`."

        Design: Corner/rbac/four_eyes_execution_reviser_cannot_execute_the_agreement
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        ada = setup_applicant(
            call["id"],
            legal_name="Ada Reyes",
            date_of_birth="1994-04-02",
            residency_state_code="GA",
        )
        record_screening_items(ada["id"], THREE_ADULT_INSTRUMENTS)
        assert get_applicant(ada["id"])["screening_status"] == "CLEARED"

        drafted = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    ada["id"],
                    production["id"],
                    get_applicant_version(ada["id"]),
                    **BASE_TERMS,
                ),
                BA1,
            ),
            201,
        )
        # No production-side round has been authored yet.
        assert drafted.get("last_production_proposer_user_id") is None

        sent = validate_success(api.send_agreement(drafted["id"], BA1))
        countered = validate_success(
            api.counter_offer_agreement(
                drafted["id"],
                counter_offer_payload(
                    sent["version"],
                    requested_base_stipend_cents=150_000,
                    requested_depiction_rights_scope="FULL",
                ),
                make_applicant_headers(ada["id"]),
            )
        )
        assert countered["status"] == "COUNTERED"

        revised = validate_success(
            api.revise_agreement(
                drafted["id"],
                revise_payload(base_stipend_cents=150_000, episodes_committed=2),
                BA9,
            )
        )
        assert revised["status"] == "REVISED"
        assert revised["last_production_proposer_user_id"] == "ba_9"

        resent = validate_success(api.send_agreement(drafted["id"], BA1))
        assert resent["status"] == "SENT"

        # The reviser is locked out even though the drafter re-sent the terms.
        validate_error(
            api.execute_agreement(drafted["id"], BA9),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )
        assert get_agreement(drafted["id"])["status"] == "SENT"

        executed = validate_success(api.execute_agreement(drafted["id"], BA1))
        assert executed["status"] == "EXECUTED"
        assert executed["executed_by_user_id"] == "ba_1"
        # The revised terms are the sole authority: 150,000 over two episodes.
        assert_money(
            executed["total_stipend_commitment_cents"], 300_000, "final stipend"
        )
        assert get_applicant(ada["id"])["screening_status"] == "CAST"


class TestSharedProductionRead:
    """The production read is the one surface every role shares, and the
    participant's ownership filter does not narrow it."""

    def test_all_six_roles_read_the_identical_rollup_payload(self, api):
        """PRD §4: "| `GET` | `/casting/productions/{id}` | Read one production
        including every rollup and the derived posture | `ProductionAdmin`,
        `CastingDirector`, `ComplianceOfficer`, `BusinessAffairs`,
        `WelfareOfficer`, `Applicant` |"
        PRD §2.6: "When the declared role is `Applicant`, `X-User-ID` equals the
        applicant that owns the addressed resource — the applicant record itself,
        or the `applicant_id` of the addressed agreement or of the agreement under
        which the addressed complaint was filed. This ownership rung guards exactly
        five operations: reading one applicant, participant withdrawal, agreement
        counter-offer, filing a complaint against an agreement, and reading one
        agreement. A mismatch yields `ERR_NOT_RESOURCE_OWNER` (403)."
        PRD §3.7: "It opens at `ENHANCED` for a high-stress format and at
        `STANDARD` otherwise, and it escalates one level — `STANDARD` to
        `ENHANCED`, `ENHANCED` to `CRITICAL` — for each escalated complaint that
        constitutes a duty-of-care breach, with `CRITICAL` as a hard ceiling that
        no further breach can exceed."
        PRD §3.1: "The posture opens at `OPEN`, and every rolled-up figure opens
        at zero: `stipend_committed_cents`, `welfare_committed_cents`,
        `trust_escrow_balance_cents`, `welfare_incident_count`,
        `breached_obligation_count` and `minor_participant_count`."

        Design: Corner/rbac/every_role_can_read_the_shared_production_endpoint
        """
        created = validate_success(
            api.create_production(
                create_production_payload(
                    title="Harbour Nights S1",
                    format_type="DOCUSOAP",
                    jurisdiction_code="GA",
                    season_number=1,
                    episode_order=9,
                    photography_start_utc="2026-09-15T00:00:00Z",
                    photography_end_utc="2026-12-15T00:00:00Z",
                    stipend_pool_cents=5_000_000,
                    welfare_budget_cents=2_000_000,
                    minor_participant_cap=2,
                ),
                PA,
            ),
            201,
        )
        call = _referral_call(created["id"])
        ada = setup_applicant(
            call["id"],
            legal_name="Ada Reyes",
            date_of_birth="1994-04-02",
            residency_state_code="GA",
        )

        readers = (PA, CD, CO1, BA1, WO1, make_applicant_headers(ada["id"]))
        payloads = [
            validate_success(api.get_production(created["id"], headers))
            for headers in readers
        ]

        for payload in payloads:
            assert payload["title"] == "Harbour Nights S1"
            assert payload["duty_of_care_tier"] == "STANDARD"
            assert payload["casting_posture"] == "OPEN"
            assert_money(payload["stipend_committed_cents"], 0, "committed stipend")
            assert_money(payload["welfare_committed_cents"], 0, "committed welfare")
            assert_money(payload["trust_escrow_balance_cents"], 0, "trust escrow")
            assert payload["welfare_incident_count"] == 0

        # Every reader, the participant included, sees the same record.
        assert all(payload == payloads[0] for payload in payloads[1:])
