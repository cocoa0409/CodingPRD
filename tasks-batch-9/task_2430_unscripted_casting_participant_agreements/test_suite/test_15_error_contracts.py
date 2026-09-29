"""Each error identifier is reached from the violation that owns it: an absent or
unrecognised role at the top of the ladder, a pagination bound, a call outside its
live window, an escrow funded ahead of its commitment, a complaint filed against
terms still under negotiation, an incomplete instrument set, a validity window
that has closed, a missing piece of on-set infrastructure, a packet that never
reached COMPLETE, an aggregate cap counted over executed rows, a conditional
counter-signature, and ten path identifiers that name nothing.
"""

from test_helpers import (
    FULL_PASS_SCREENING,
    TEST_USERS,
    UNKNOWN_UUID,
    ApiErrorId,
    assert_money,
    assert_score,
    build_user_headers,
    create_applicant_payload,
    create_complaint_payload,
    create_docusoap_production_payload,
    create_release_payload,
    create_shoot_block_payload,
    get_agreement,
    get_applicant,
    get_production,
    get_shoot_block,
    make_applicant_headers,
    record_outcome_payload,
    record_screening_items,
    set_clock,
    setup_active_welfare_protocol,
    setup_applicant,
    setup_casting_call,
    setup_docusoap_production,
    setup_drafted_agreement,
    setup_minor_applicant,
    setup_minor_protection,
    setup_planned_welfare_protocol,
    setup_production,
    setup_published_casting_call,
    setup_sent_agreement,
    setup_trust_deposit,
    trust_deposit_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["production_admin_headers"]
CD = TEST_USERS["casting_director_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]
CO2 = TEST_USERS["compliance_officer_2_headers"]
BA1 = TEST_USERS["business_affairs_headers"]
BA2 = TEST_USERS["business_affairs_2_headers"]
WO1 = TEST_USERS["welfare_officer_headers"]

# A well-formed user identifier with no role declared alongside it, and a
# well-formed pair naming a capacity the system does not recognise.
NO_ROLE_HEADERS = {"X-User-ID": "pa_1", "Content-Type": "application/json"}
UNKNOWN_ROLE_HEADERS = build_user_headers("pa_1", "Bystander")

# A two-episode per-episode deal at a 100,000-cent episode rate.
BASE_TERMS = {
    "exclusivity_window_days": 0,
    "confidentiality_tier": "STANDARD",
    "depiction_rights_scope": "FULL",
    "stipend_structure": "PER_EPISODE",
    "base_stipend_cents": 100_000,
    "episodes_committed": 2,
}

# A GA packet at the state floors of 10 tutoring hours and a tenth in trust.
GA_PACKET = {
    "work_permit_number": "GA-2026-11842",
    "permit_expires_on": "2026-12-31",
    "education_hours_scheduled_weekly": 10,
    "trust_deposit_pct": 0.10,
}

# A permitted public venue with room for nine hundred heads.
RIVERWALK_PLAZA = {
    "name": "Riverwalk Plaza",
    "state_code": "GA",
    "capacity": 900,
    "turnaround_buffer_minutes": 60,
    "filming_permit_number": "ATL-FP-2026-77",
}


def _harbour_nights(**overrides):
    """A nine-episode DOCUSOAP in GA: STANDARD tier, no hazard uplift."""
    return setup_docusoap_production(title="Harbour Nights S1", **overrides)


def _island_trials(**overrides):
    """A nine-episode COMPETITION_HIGH_STRESS season photographed in the autumn."""
    return setup_production(
        title="Island Trials S2",
        season_number=2,
        episode_order=9,
        photography_start_utc="2026-10-15T00:00:00Z",
        photography_end_utc="2027-01-15T00:00:00Z",
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


def _cleared_adult(call_id, legal_name, date_of_birth, state_code="GA"):
    """An adult applicant with the three required instruments recorded PASS."""
    applicant = setup_applicant(
        call_id,
        legal_name=legal_name,
        date_of_birth=date_of_birth,
        residency_state_code=state_code,
    )
    record_screening_items(
        applicant["id"],
        (
            ("INTERVIEW", "PASS", 0, CO1),
            ("BACKGROUND_CHECK", "PASS", 0, CO1),
            ("MEDICAL_EXAM", "PASS", 0, CO1),
        ),
    )
    return applicant


def _cleared_minor(call_id, legal_name, date_of_birth, guardian_name, **packet_overrides):
    """A minor applicant with all four instruments and a filed packet."""
    minor = setup_minor_applicant(
        call_id,
        legal_name=legal_name,
        date_of_birth=date_of_birth,
        residency_state_code="GA",
        guardian_name=guardian_name,
    )
    record_screening_items(minor["id"], FULL_PASS_SCREENING)
    packet = setup_minor_protection(
        minor["id"], **dict(GA_PACKET, **packet_overrides)
    )
    return minor, packet


class TestAuthenticationLadder:
    """Authentication is settled before authorisation, and both are settled before
    the server looks for the addressed record."""

    def test_a_missing_or_unrecognised_role_answers_401_before_any_lookup(self, api):
        """PRD §2.1: "Every request, without exception, must carry two headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the
        capacity in which they act."
        PRD §2.1: "If either header is absent or empty, or if `X-User-Role` is not
        one of the six recognised roles, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401). If the header pair is well formed but the
        declared role is not permitted to invoke the addressed operation, the
        rejection is `ERR_ROLE_FORBIDDEN` (HTTP 403)."
        PRD §2.6: "Because most operations in this API are guarded by several
        independent rules at once, the order in which those rules are evaluated is
        part of the contract: the first rule that fails determines the response,
        and no later rule is evaluated."
        PRD §2.6: "Every identifier appearing in the URL path exists, validated
        left to right, with the failure reported as the 404 error naming the
        missing kind: `ERR_PRODUCTION_NOT_FOUND`, `ERR_CASTING_CALL_NOT_FOUND`,
        `ERR_APPLICANT_NOT_FOUND`, `ERR_SCREENING_ITEM_NOT_FOUND`,
        `ERR_MINOR_PROTECTION_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_WELFARE_PROTOCOL_NOT_FOUND`, `ERR_SHOOT_BLOCK_NOT_FOUND`,
        `ERR_POST_OBLIGATION_NOT_FOUND` or `ERR_COMPLAINT_NOT_FOUND`."

        Design: Corner/errors/unauthenticated_when_role_header_missing_or_unknown_rejected
        """
        production = _harbour_nights()
        # The identifier is real: the same read succeeds once a role is declared.
        validate_success(api.get_production(production["id"], PA))

        validate_error(
            api.get_production(production["id"], NO_ROLE_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api.get_production(production["id"], UNKNOWN_ROLE_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        # An unknown identifier does not lower the answer to a 404: the first two
        # rungs are evaluated before the fifth.
        validate_error(
            api.get_production(UNKNOWN_UUID, NO_ROLE_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        # A recognised but unprivileged role is the next rung down, not the same one.
        validate_error(
            api.create_production(
                create_docusoap_production_payload(title="Sneaky S1"), CD
            ),
            ApiErrorId.ERR_ROLE_FORBIDDEN.value,
            403,
        )


class TestPaginationBounds:
    """The pagination bounds are inclusive at 100 and at 0, and breaching them is
    its own error rather than the generic body-shape one."""

    def test_the_limit_ceiling_is_inclusive_and_the_offset_floor_is_zero(self, api):
        """PRD §2.3: "`limit` caps the number of records returned; it defaults to
        10, may be no smaller than 1 and no larger than 100."
        PRD §2.3: "A `limit` outside the range 1 through 100 inclusive, or a
        negative `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`
        and `has_more` inside the `meta` object of the envelope, where
        `total_count` is the number of records matching the filters before
        pagination is applied and `has_more` states whether any matching record
        remains beyond the returned page."

        Design: Corner/errors/pagination_limit_above_maximum_returns_invalid_pagination
        """
        production = _harbour_nights()
        first = setup_casting_call(production["id"])
        second = setup_casting_call(
            production["id"],
            channel="DIGITAL_SUBMISSION",
            min_age=18,
            exclusivity_window_days=30,
        )

        for out_of_bounds in (
            {"limit": 101, "offset": 0},
            {"limit": 0, "offset": 0},
            {"limit": 10, "offset": -1},
        ):
            validate_error(
                api.list_casting_calls(
                    CD, params=dict(out_of_bounds, production_id=production["id"])
                ),
                ApiErrorId.ERR_INVALID_PAGINATION.value,
                400,
            )

        rows, meta = validate_paginated(
            api.list_casting_calls(
                CD,
                params={
                    "production_id": production["id"],
                    "limit": 100,
                    "offset": 0,
                },
            )
        )
        assert meta["limit"] == 100
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert {row["id"] for row in rows} == {first["id"], second["id"]}


class TestCallLifecycleIntakeGate:
    """Intake is admitted only in the published window: the same error answers on
    either side of it."""

    def test_intake_is_refused_before_publication_and_again_after_closure(self, api):
        """PRD §3.3: "Intake is admitted only into a call whose `status` is
        `PUBLISHED` — an application against a draft or closed call is refused
        with `ERR_CASTING_CALL_NOT_OPEN` — and, when the call's channel is
        `OPEN_CALL`, only while the logical clock lies inside the inclusive
        intake window, failing which the answer is
        `ERR_OPEN_CALL_WINDOW_CLOSED`."
        PRD §3.2: "A freshly drafted call sits in `DRAFT` status, has never been
        published, and carries no closing reason."
        PRD §3.2: "A director may retire a live call at any time, moving it
        `PUBLISHED → CLOSED` with `closed_reason` recorded as `DIRECTOR_CLOSED`."
        PRD §3.3: "And the applicant's two independent state dimensions open at
        their initial values: `screening_status` at `SUBMITTED` and
        `medical_status` at `NOT_STARTED`."

        Design: Corner/errors/applicant_intake_against_unpublished_call_rejected
        """
        production = _harbour_nights()
        call = setup_casting_call(production["id"])
        assert call["status"] == "DRAFT"

        validate_error(
            api.create_applicant(
                create_applicant_payload(
                    call["id"],
                    legal_name="Too Early",
                    date_of_birth="1994-04-02",
                    residency_state_code="GA",
                ),
                CD,
            ),
            ApiErrorId.ERR_CASTING_CALL_NOT_OPEN.value,
            409,
        )

        published = validate_success(api.publish_casting_call(call["id"], CD))
        assert published["status"] == "PUBLISHED"
        admitted = validate_success(
            api.create_applicant(
                create_applicant_payload(
                    call["id"],
                    legal_name="Ada Reyes",
                    date_of_birth="1994-04-02",
                    residency_state_code="GA",
                ),
                CD,
            ),
            201,
        )
        assert admitted["screening_status"] == "SUBMITTED"

        closed = validate_success(api.close_casting_call(call["id"], CD))
        assert closed["status"] == "CLOSED"
        assert closed["closed_reason"] == "DIRECTOR_CLOSED"

        validate_error(
            api.create_applicant(
                create_applicant_payload(
                    call["id"],
                    legal_name="Too Late",
                    date_of_birth="1994-04-02",
                    residency_state_code="GA",
                ),
                CD,
            ),
            ApiErrorId.ERR_CASTING_CALL_NOT_OPEN.value,
            409,
        )


class TestTrustDepositOrdering:
    """The blocked trust cannot be funded until there is a settled commitment to
    take a share of."""

    def test_the_deposit_waits_for_execution_and_then_funds_a_tenth(self, api):
        """PRD §3.5: "Funding the trust is a `BusinessAffairs` act, and it is
        admitted only once the applicant's agreement has reached `EXECUTED` — a
        deposit requested any earlier is refused with
        `ERR_AGREEMENT_NOT_EXECUTED`."
        PRD §3.5: "The target amount is the executed agreement's
        `total_stipend_commitment_cents` multiplied by the packet's
        `trust_deposit_pct`."
        PRD §3.5: "That target is divided by the installment count and the
        quotient is rounded half up to whole cents to give `per_installment_cents`;
        `trust_deposited_cents` is then that rounded installment multiplied by the
        installment count, and it is not rounded again."
        PRD §3.1: "The posture opens at `OPEN`, and every rolled-up figure opens
        at zero: `stipend_committed_cents`, `welfare_committed_cents`,
        `trust_escrow_balance_cents`, `welfare_incident_count`,
        `breached_obligation_count` and `minor_participant_count`."

        Design: Corner/errors/trust_deposit_before_execute_rejected
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        minor, packet = _cleared_minor(
            call["id"], "Mika Vance", "2011-05-20", "Dana Vance"
        )
        assert packet["status"] == "COMPLETE"
        assert get_production(production["id"])["trust_escrow_balance_cents"] == 0

        agreement = setup_drafted_agreement(
            minor["id"], production["id"], **BASE_TERMS
        )
        validate_error(
            api.create_trust_deposit(packet["id"], trust_deposit_payload(4), BA1),
            ApiErrorId.ERR_AGREEMENT_NOT_EXECUTED.value,
            409,
        )

        validate_success(api.send_agreement(agreement["id"], BA1))
        validate_error(
            api.create_trust_deposit(packet["id"], trust_deposit_payload(4), BA1),
            ApiErrorId.ERR_AGREEMENT_NOT_EXECUTED.value,
            409,
        )

        executed = validate_success(api.execute_agreement(agreement["id"], BA2))
        assert_money(
            executed["total_stipend_commitment_cents"], 200_000, "final stipend"
        )

        # A tenth of 200,000 is 20,000, and a quarter of that divides exactly.
        deposit = setup_trust_deposit(packet["id"], 4)
        assert_money(deposit["per_installment_cents"], 5_000, "per installment")
        assert_money(deposit["trust_deposited_cents"], 20_000, "trust deposited")
        assert_money(
            get_production(production["id"])["trust_escrow_balance_cents"],
            20_000,
            "trust escrow",
        )


class TestComplaintTargetGate:
    """A complaint reaches back to signed terms only: an offer still in
    negotiation is not a valid target."""

    def test_a_complaint_is_refused_until_the_agreement_is_executed(self, api):
        """PRD §3.9: "A participant files a complaint against their own agreement,
        permitted only while that agreement's `status` is `EXECUTED` or `VOIDED`;
        a complaint against an agreement still in negotiation is refused with
        `ERR_COMPLAINT_TARGET_INVALID`."
        PRD §3.9: "The complaint opens at `status` `OPEN` with
        `duty_of_care_breach` false and `aftercare_sessions_authorized` at 0."
        PRD §3.9: "The aftercare branch is the quiet one."
        PRD §3.1: "The posture opens at `OPEN`, and every rolled-up figure opens
        at zero: `stipend_committed_cents`, `welfare_committed_cents`,
        `trust_escrow_balance_cents`, `welfare_incident_count`,
        `breached_obligation_count` and `minor_participant_count`."

        Design: Corner/errors/complaint_against_drafted_agreement_rejected
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        ada = _cleared_adult(call["id"], "Ada Reyes", "1994-04-02")
        participant = make_applicant_headers(ada["id"])
        agreement = setup_drafted_agreement(ada["id"], production["id"], **BASE_TERMS)

        validate_error(
            api.file_complaint(
                agreement["id"],
                create_complaint_payload(
                    severity=3, narrative="Raised before the paperwork was signed."
                ),
                participant,
            ),
            ApiErrorId.ERR_COMPLAINT_TARGET_INVALID.value,
            409,
        )

        validate_success(api.send_agreement(agreement["id"], BA1))
        validate_error(
            api.file_complaint(
                agreement["id"],
                create_complaint_payload(
                    severity=3, narrative="Raised while the offer was still out."
                ),
                participant,
            ),
            ApiErrorId.ERR_COMPLAINT_TARGET_INVALID.value,
            409,
        )

        validate_success(api.execute_agreement(agreement["id"], BA2))
        complaint = validate_success(
            api.file_complaint(
                agreement["id"],
                create_complaint_payload(
                    severity=3, narrative="Raised after execution, as the rule allows."
                ),
                participant,
            ),
            201,
        )
        assert complaint["status"] == "OPEN"
        assert complaint["aftercare_sessions_authorized"] == 0
        assert complaint["duty_of_care_breach"] is False
        # Filing alone is not an incident; only an escalated breach counts one.
        assert get_production(production["id"])["welfare_incident_count"] == 0


class TestSendClearanceGates:
    """Send is the most heavily guarded transition, and each of its clearance
    conditions has its own answer."""

    def test_the_required_kind_set_gates_the_send_not_the_item_count(self, api):
        """PRD §2.6: "On agreement send and agreement execution, the applicant's
        `screening_status` is `CLEARED`, otherwise `ERR_SCREENING_INCOMPLETE`
        (422)."
        PRD §3.4: "The set of **required kinds** for an applicant is `INTERVIEW`,
        `BACKGROUND_CHECK` and `MEDICAL_EXAM`, plus `PSYCH_EVAL` when the
        applicant's `psych_eval_required` is true."
        PRD §3.4: "An applicant advances `SCREENING → CLEARED` when every required
        kind has an item whose outcome is `PASS` or `CONDITIONAL`, no item of the
        applicant has outcome `FAIL`, and the final risk figure is strictly below
        12.00."
        PRD §3.4: "Opening any screening item while the applicant's
        `screening_status` is `SUBMITTED` or `SCREENING` advances that dimension
        `SUBMITTED → SCREENING` and refreshes the provisional risk figure."

        Design: Corner/errors/send_with_screening_still_in_progress_rejected
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        ada = setup_applicant(
            call["id"],
            legal_name="Ada Reyes",
            date_of_birth="1994-04-02",
            residency_state_code="GA",
        )
        record_screening_items(
            ada["id"],
            (
                ("INTERVIEW", "PASS", 0, CO1),
                ("BACKGROUND_CHECK", "PASS", 0, CO1),
            ),
        )
        mid = get_applicant(ada["id"])
        assert mid["screening_status"] == "SCREENING"
        assert mid["medical_status"] == "NOT_STARTED"

        agreement = setup_drafted_agreement(ada["id"], production["id"], **BASE_TERMS)
        validate_error(
            api.send_agreement(agreement["id"], BA1),
            ApiErrorId.ERR_SCREENING_INCOMPLETE.value,
            422,
        )

        record_screening_items(ada["id"], (("MEDICAL_EXAM", "PASS", 0, CO1),))
        cleared = get_applicant(ada["id"])
        assert cleared["screening_status"] == "CLEARED"
        assert cleared["medical_status"] == "CLEARED"
        # Passing items carry no points however many flags they hold.
        assert_score(cleared["final_risk_score"], 0.0, "final risk score")

        sent = validate_success(api.send_agreement(agreement["id"], BA1))
        assert sent["status"] == "SENT"
        # Nine episodes at the 1.30 tier, two reserve junkets and a reunion.
        assert_money(
            sent["provisional_stipend_cents"], 1_370_000, "provisional stipend"
        )

    def test_a_lapsed_psych_evaluation_is_refused_like_a_missing_one(self, api):
        """PRD §2.6: "On agreement send, when the applicant's
        `psych_eval_required` is true, a `PSYCH_EVAL` item exists whose `outcome`
        is `PASS` or `CONDITIONAL` and whose `expires_at` is either absent or
        strictly later than the logical clock, otherwise
        `ERR_PSYCH_EVAL_REQUIRED` (422)."
        PRD §3.4: "On success the item's `outcome` and `severity_flags` are
        written, `recorded_by_user_id` is stamped with the caller's `X-User-ID`,
        `recorded_at` is stamped with the logical clock, and `expires_at` is
        derived from the kind's validity window: a `MEDICAL_EXAM` clearance is
        valid for 30 days from `recorded_at`, a `PSYCH_EVAL` for 60 days, a
        `BACKGROUND_CHECK` for 180 days, and an `INTERVIEW` never expires, so its
        `expires_at` remains absent."
        PRD §3.3: "`psych_eval_required` is true when the production's
        `format_type` is `COMPETITION_HIGH_STRESS` or when `is_minor` is true;
        high-stress formats and minors both attract mandatory psychological
        evaluation."
        PRD §2.5: "Setting the clock mutates no entity and fires no sweep of any
        kind: expiries, lapses and breaches are only ever applied by the welfare
        epoch sweep described in §3.7, which an operator must invoke explicitly."

        Design: Corner/errors/psych_eval_expired_at_send_rejected
        """
        production = _island_trials()
        call = _referral_call(production["id"], min_age=18)
        ada = setup_applicant(
            call["id"],
            legal_name="Ada Reyes",
            date_of_birth="1994-04-02",
            residency_state_code="CA",
        )
        assert ada["psych_eval_required"] is True
        items = record_screening_items(ada["id"], FULL_PASS_SCREENING)
        psych = next(item for item in items if item["kind"] == "PSYCH_EVAL")
        # Sixty days from the start-up instant.
        assert psych["expires_at"].startswith("2026-09-30T00:00:00")
        assert get_applicant(ada["id"])["screening_status"] == "CLEARED"
        agreement_a = setup_drafted_agreement(
            ada["id"], production["id"], **BASE_TERMS
        )

        set_clock("2026-10-02T00:00:00Z")
        bo = setup_applicant(
            call["id"],
            legal_name="Bo Lindqvist",
            date_of_birth="1990-01-10",
            residency_state_code="CA",
        )
        record_screening_items(bo["id"], FULL_PASS_SCREENING)
        agreement_b = setup_drafted_agreement(bo["id"], production["id"], **BASE_TERMS)

        validate_error(
            api.send_agreement(agreement_a["id"], BA1),
            ApiErrorId.ERR_PSYCH_EVAL_REQUIRED.value,
            422,
        )
        stale = get_applicant(ada["id"])
        # No sweep has run, so the medical dimension is untouched and the rung
        # above cannot claim the refusal.
        assert stale["medical_status"] == "CLEARED"
        assert stale["screening_status"] == "CLEARED"
        assert get_agreement(agreement_a["id"])["status"] == "DRAFTED"

        sent = validate_success(api.send_agreement(agreement_b["id"], BA1))
        assert sent["status"] == "SENT"
        # A high-stress format adds a tenth of the base as hazard uplift.
        assert_money(
            sent["provisional_stipend_cents"], 1_487_000, "provisional stipend"
        )

    def test_a_high_risk_applicant_needs_the_support_protocol_active(self, api):
        """PRD §2.6: "On agreement send, when the applicant's
        `enhanced_support_required` is true, the production has an `ACTIVE`
        `ONSET_PSYCH_SUPPORT` protocol whose coverage spans the entire photography
        window, otherwise `ERR_ENHANCED_SUPPORT_MISSING` (422)."
        PRD §3.4: "Clearing recomputes both risk figures, sets
        `enhanced_support_required` to true exactly when `final_risk_score` is
        8.00 or above, and increments the originating casting call's
        `screened_pass_count` by one."
        PRD §3.4: "Its recorded items are ordered by `recorded_at` descending,
        with ties broken by `created_at` descending, and each item is then
        multiplied by a decay factor determined by its one-based position in that
        ordering: the first item keeps its full points, the second is multiplied by
        eight tenths, the third by six tenths, the fourth by one half, and every
        item from the fifth onward is also multiplied by one half."
        PRD §3.7: "A newly planned protocol sits at `status` `PLANNED`."

        Design: Corner/errors/enhanced_support_missing_for_high_risk_applicant_rejected
        """
        production = _island_trials()
        assert production["duty_of_care_tier"] == "ENHANCED"
        call = _referral_call(production["id"], min_age=18)
        ada = setup_applicant(
            call["id"],
            legal_name="Ada Reyes",
            date_of_birth="1994-04-02",
            residency_state_code="CA",
        )

        # Four instruments recorded on four consecutive logical-clock days, so the
        # recency ordering is unambiguous.
        record_screening_items(ada["id"], (("INTERVIEW", "CONDITIONAL", 3, CO1),))
        set_clock("2026-08-02T00:00:00Z")
        record_screening_items(
            ada["id"], (("BACKGROUND_CHECK", "CONDITIONAL", 3, CO1),)
        )
        set_clock("2026-08-03T00:00:00Z")
        record_screening_items(ada["id"], (("MEDICAL_EXAM", "PASS", 0, CO1),))
        set_clock("2026-08-04T00:00:00Z")
        psych = record_screening_items(
            ada["id"], (("PSYCH_EVAL", "CONDITIONAL", 3, CO2),)
        )[0]
        assert psych["outcome"] == "CONDITIONAL"

        applicant = get_applicant(ada["id"])
        # Undecayed points: interview 2.25, background check 4.50, medical 0,
        # psych evaluation 6.00.
        assert_score(applicant["provisional_risk_score"], 12.75, "provisional risk")
        # Recency order psych / medical / background / interview weighted
        # 1.00 / 0.80 / 0.60 / 0.50 gives 6.00 + 0 + 2.70 + 1.125.
        assert_score(applicant["final_risk_score"], 9.83, "final risk")
        assert applicant["screening_status"] == "CLEARED"
        assert applicant["medical_status"] == "CLEARED"
        assert applicant["enhanced_support_required"] is True

        agreement = setup_drafted_agreement(ada["id"], production["id"], **BASE_TERMS)
        validate_error(
            api.send_agreement(agreement["id"], BA1),
            ApiErrorId.ERR_ENHANCED_SUPPORT_MISSING.value,
            422,
        )

        protocol = setup_planned_welfare_protocol(
            production["id"],
            kind="ONSET_PSYCH_SUPPORT",
            coverage_start_utc="2026-10-01T00:00:00Z",
            coverage_end_utc="2027-02-01T00:00:00Z",
            cost_cents=1_000_000,
        )
        assert protocol["status"] == "PLANNED"
        # Planning is not standing it up: the gate reads the ACTIVE status.
        validate_error(
            api.send_agreement(agreement["id"], BA1),
            ApiErrorId.ERR_ENHANCED_SUPPORT_MISSING.value,
            422,
        )

        activated = validate_success(
            api.activate_welfare_protocol(protocol["id"], WO1)
        )
        assert activated["status"] == "ACTIVE"
        # Activation leaves the subtotal alone: 1,000,000 at four hundredths and
        # the ENHANCED factor of one and a half.
        assert_money(
            get_production(production["id"])["welfare_committed_cents"],
            1_060_000,
            "committed welfare",
        )

        sent = validate_success(api.send_agreement(agreement["id"], BA1))
        assert sent["status"] == "SENT"
        assert_money(
            sent["provisional_stipend_cents"], 1_487_000, "provisional stipend"
        )

    def test_an_incomplete_packet_answers_before_the_permit_inside_it(self, api):
        """PRD §2.6: "On agreement send, when the applicant's `is_minor` is true,
        that applicant has a minor-protection packet in `COMPLETE` status,
        otherwise `ERR_MINOR_PROTECTION_INCOMPLETE` (422)."
        PRD §2.6: "Minor work permits are unexpired: on agreement send for a minor
        applicant, and on shoot-block scheduling for every minor called to the
        block, `permit_expires_on` is strictly after the logical clock's date,
        otherwise `ERR_WORK_PERMIT_EXPIRED` (422)."
        PRD §3.5: "It becomes `COMPLETE` when all three of its conditions hold
        together — the permit's expiry date is strictly after the logical clock's
        date, the scheduled education hours are at least the jurisdiction's weekly
        minimum, and the trust percentage is at least the jurisdiction's minimum
        fraction — and `INCOMPLETE` otherwise."
        PRD §3.5: "Amendment re-derives the status in both directions with equal
        force: a packet may be patched with any of `work_permit_number`,
        `permit_expires_on`, `education_hours_scheduled_weekly` or
        `trust_deposit_pct`, and where the amended packet satisfies all three
        conditions it moves `INCOMPLETE → COMPLETE`, while where the amended
        packet no longer satisfies all three it moves `COMPLETE → INCOMPLETE`."

        Design: Corner/errors/minor_protection_incomplete_at_send_rejected
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        mika = setup_minor_applicant(
            call["id"],
            legal_name="Mika Vance",
            date_of_birth="2011-05-20",
            residency_state_code="GA",
            guardian_name="Dana Vance",
        )
        assert mika["is_minor"] is True
        record_screening_items(mika["id"], FULL_PASS_SCREENING)
        assert get_applicant(mika["id"])["screening_status"] == "CLEARED"

        agreement = setup_drafted_agreement(mika["id"], production["id"], **BASE_TERMS)
        validate_error(
            api.send_agreement(agreement["id"], BA1),
            ApiErrorId.ERR_MINOR_PROTECTION_INCOMPLETE.value,
            422,
        )

        # A permit that lapsed before the clock leaves the packet short of
        # COMPLETE while both statutory floors are met exactly.
        packet = setup_minor_protection(
            mika["id"],
            work_permit_number="GA-2026-00001",
            permit_expires_on="2026-07-15",
            education_hours_scheduled_weekly=10,
            trust_deposit_pct=0.10,
        )
        assert packet["status"] == "INCOMPLETE"
        validate_error(
            api.send_agreement(agreement["id"], BA1),
            ApiErrorId.ERR_MINOR_PROTECTION_INCOMPLETE.value,
            422,
        )

        patched = validate_success(
            api.patch_minor_protection(
                packet["id"], {"permit_expires_on": "2026-12-31"}, CO1
            )
        )
        assert patched["status"] == "COMPLETE"

        sent = validate_success(api.send_agreement(agreement["id"], BA1))
        assert sent["status"] == "SENT"
        assert_money(
            sent["provisional_stipend_cents"], 1_370_000, "provisional stipend"
        )


class TestMinorCapAtExecution:
    """The minor cap is an aggregate over executed rows, so outstanding offers do
    not consume it."""

    def test_only_the_second_execution_trips_the_cap(self, api):
        """PRD §3.6: "Execution moves the agreement `SENT → EXECUTED` and is
        admitted only from `SENT`, only while `welfare_hold` is false, only while
        the production's posture is not `FROZEN`, only when the four-eyes execution
        rule of §2.10 is satisfied, only while the applicant's `screening_status`
        and `medical_status` are both `CLEARED`, only when a minor applicant still
        fits under the cap — the production's `minor_participant_count` plus one
        must be no greater than `minor_participant_cap`, failing which the answer
        is `ERR_MINOR_CAP_EXCEEDED` — and only when `stipend_committed_cents` plus
        this agreement's final stipend figure stay within `stipend_pool_cents`."
        PRD §3.6: "Second, because the final commitment was written, the
        production's `stipend_committed_cents` is recomputed by full re-summation
        over executed agreements and its `minor_participant_count` is recomputed
        as the count of executed agreements whose applicant is a minor."
        PRD §2.11: "Committed stipend is the sum of
        `total_stipend_commitment_cents` over the production's participant
        agreements whose `status` is `EXECUTED`."
        PRD §3.6: "Drafting opens the agreement at `status` `DRAFTED` with
        `round_number` at 0, both stipend figures at 0, `welfare_hold` false, and
        it increments the applicant's `version` by one."

        Design: Corner/errors/minor_cap_exceeded_on_second_minor_execute_rejected
        """
        production = _harbour_nights(minor_participant_cap=1)
        assert production["minor_participant_cap"] == 1
        call = _referral_call(production["id"])
        mika, _ = _cleared_minor(call["id"], "Mika Vance", "2011-05-20", "Dana Vance")
        rue, _ = _cleared_minor(
            call["id"],
            "Rue Alder",
            "2011-07-04",
            "Peta Alder",
            work_permit_number="GA-2026-11843",
        )

        # Both offers go out: the drafting path never consults the cap.
        sent_a = setup_sent_agreement(mika["id"], production["id"], **BASE_TERMS)
        sent_b = setup_sent_agreement(rue["id"], production["id"], **BASE_TERMS)
        assert sent_a["status"] == "SENT"
        assert sent_b["status"] == "SENT"

        executed = validate_success(api.execute_agreement(sent_a["id"], BA2))
        assert executed["status"] == "EXECUTED"
        assert_money(
            executed["total_stipend_commitment_cents"], 200_000, "final stipend"
        )
        mid = get_production(production["id"])
        assert mid["minor_participant_count"] == 1
        assert_money(mid["stipend_committed_cents"], 200_000, "committed stipend")

        validate_error(
            api.execute_agreement(sent_b["id"], BA2),
            ApiErrorId.ERR_MINOR_CAP_EXCEEDED.value,
            409,
        )
        refused = get_agreement(sent_b["id"])
        assert refused["status"] == "SENT"
        assert_money(
            refused["total_stipend_commitment_cents"], 0, "refused final stipend"
        )

        final = get_production(production["id"])
        assert final["minor_participant_count"] == 1
        assert_money(final["stipend_committed_cents"], 200_000, "committed stipend")


class TestReleaseGuardianSignature:
    """The counter-signature is demanded by the subject kind alone, and a refused
    release writes nothing into the coverage rollup."""

    def test_only_a_minor_incidental_release_demands_the_counter_signature(self, api):
        """PRD §3.8: "It may name the subject as `subject_name`, which is absent
        for blanket crowd releases, and it carries `guardian_signature`,
        defaulting to false; a release whose subject kind is `MINOR_INCIDENTAL`
        must carry that counter-signature set to true or it is refused with
        `ERR_GUARDIAN_SIGNATURE_REQUIRED`."
        PRD §3.8: "`covered_head_count` is the sum of `head_count` over the
        block's releases whose `disposition` is `COLLECTED` or `BLURRED_WAIVER`; a
        `REFUSED` release contributes nothing."
        PRD §3.8: "`release_coverage_complete` is true when `covered_head_count`
        is greater than or equal to `expected_crowd_headcount` **and** every
        release of the block whose `subject_kind` is `MINOR_INCIDENTAL` carries
        `guardian_signature` true."
        PRD §3.8: "Wrapping moves a block `ROLLING → WRAPPED`, is admitted only
        from `ROLLING`, and re-evaluates coverage at wrap time; incomplete
        coverage is refused with `ERR_RELEASE_COVERAGE_INCOMPLETE`."

        Design: Corner/errors/minor_incidental_release_without_guardian_signature_rejected
        """
        production = _harbour_nights()
        venue = validate_success(api.create_location(dict(RIVERWALK_PLAZA), PA), 201)
        protocol = setup_active_welfare_protocol(
            production["id"],
            coverage_start_utc="2026-09-15T00:00:00Z",
            coverage_end_utc="2026-12-15T00:00:00Z",
            cost_cents=1_000_000,
        )
        assert protocol["status"] == "ACTIVE"

        block = validate_success(
            api.create_shoot_block(
                create_shoot_block_payload(
                    production["id"],
                    venue["id"],
                    block_kind="PUBLIC_SPACE",
                    start_utc="2026-10-01T08:00:00Z",
                    end_utc="2026-10-01T16:00:00Z",
                    participant_agreement_ids=[],
                    expected_crowd_headcount=200,
                ),
                PA,
            ),
            201,
        )
        assert block["status"] == "SCHEDULED"
        assert block["covered_head_count"] == 0
        rolling = validate_success(api.roll_shoot_block(block["id"], PA))
        assert rolling["status"] == "ROLLING"

        validate_error(
            api.collect_release(
                block["id"],
                create_release_payload(
                    subject_kind="MINOR_INCIDENTAL",
                    subject_name="Unnamed child in frame",
                    head_count=1,
                ),
                PA,
            ),
            ApiErrorId.ERR_GUARDIAN_SIGNATURE_REQUIRED.value,
            422,
        )
        # The coverage rollup runs only on an accepted write.
        assert get_shoot_block(block["id"])["covered_head_count"] == 0

        signed = validate_success(
            api.collect_release(
                block["id"],
                create_release_payload(
                    subject_kind="MINOR_INCIDENTAL",
                    subject_name="Unnamed child in frame",
                    head_count=1,
                    guardian_signature=True,
                ),
                PA,
            ),
            201,
        )
        assert signed["disposition"] == "COLLECTED"
        assert signed["guardian_signature"] is True

        crowd = validate_success(
            api.collect_release(
                block["id"],
                create_release_payload(head_count=199),
                PA,
            ),
            201,
        )
        # The default is acceptable on a blanket crowd release.
        assert crowd["guardian_signature"] is False

        covered = get_shoot_block(block["id"])
        assert covered["covered_head_count"] == 200
        assert covered["release_coverage_complete"] is True
        wrapped = validate_success(api.wrap_shoot_block(block["id"], PA))
        assert wrapped["status"] == "WRAPPED"


class TestNotFoundVocabulary:
    """The 404 vocabulary is per-entity, and an action endpoint resolves its path
    identifier before it reads any state."""

    def test_ten_unknown_path_identifiers_return_ten_distinct_error_ids(self, api):
        """PRD §2.6: "Every identifier appearing in the URL path exists, validated
        left to right, with the failure reported as the 404 error naming the
        missing kind: `ERR_PRODUCTION_NOT_FOUND`, `ERR_CASTING_CALL_NOT_FOUND`,
        `ERR_APPLICANT_NOT_FOUND`, `ERR_SCREENING_ITEM_NOT_FOUND`,
        `ERR_MINOR_PROTECTION_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_WELFARE_PROTOCOL_NOT_FOUND`, `ERR_SHOOT_BLOCK_NOT_FOUND`,
        `ERR_POST_OBLIGATION_NOT_FOUND` or `ERR_COMPLAINT_NOT_FOUND`."
        PRD §2.6: "Where an endpoint's URL nests one collection beneath another —
        a production's welfare protocols, an applicant's screening items, an
        agreement's negotiation rounds — the identifiers are resolved strictly
        left to right, and the first identifier that names no existing record
        produces its own 404 before any identifier to its right is examined."
        PRD §2.6: "The addressed entity is in a state from which the requested
        transition is declared, otherwise `ERR_INVALID_STATE_TRANSITION` (409).
        This rung applies to every action endpoint."

        Design: Corner/errors/unknown_path_ids_return_entity_specific_not_found
        """
        validate_error(
            api.get_production(UNKNOWN_UUID, PA),
            ApiErrorId.ERR_PRODUCTION_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_casting_call(UNKNOWN_UUID, CD),
            ApiErrorId.ERR_CASTING_CALL_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_applicant(UNKNOWN_UUID, BA1),
            ApiErrorId.ERR_APPLICANT_NOT_FOUND.value,
            404,
        )
        # The action endpoints answer 404 rather than reaching their own state or
        # precondition rungs.
        validate_error(
            api.record_screening_outcome(UNKNOWN_UUID, record_outcome_payload(), CO1),
            ApiErrorId.ERR_SCREENING_ITEM_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.patch_minor_protection(UNKNOWN_UUID, {"trust_deposit_pct": 0.2}, CO1),
            ApiErrorId.ERR_MINOR_PROTECTION_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_agreement(UNKNOWN_UUID, BA1),
            ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.activate_welfare_protocol(UNKNOWN_UUID, WO1),
            ApiErrorId.ERR_WELFARE_PROTOCOL_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_shoot_block(UNKNOWN_UUID, PA),
            ApiErrorId.ERR_SHOOT_BLOCK_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.fulfill_post_obligation(UNKNOWN_UUID, BA1),
            ApiErrorId.ERR_POST_OBLIGATION_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.triage_complaint(UNKNOWN_UUID, WO1),
            ApiErrorId.ERR_COMPLAINT_NOT_FOUND.value,
            404,
        )
