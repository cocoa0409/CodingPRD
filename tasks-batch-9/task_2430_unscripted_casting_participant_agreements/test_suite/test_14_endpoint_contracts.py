"""Endpoints read one surface at a time: what an action endpoint stamps and
whether calling it twice is admitted, how a nested collection is scoped by the
identifier in its path, how a create resolves an array of links into a derived
count, what a single computed read returns without mutating anything, and which
instant the server is working from before any clock has been moved.
"""

from test_helpers import (
    DEFAULT_LOGICAL_CLOCK,
    FULL_PASS_SCREENING,
    NO_PSYCH_SCREENING,
    TEST_USERS,
    ApiErrorId,
    assert_money,
    create_screening_item_payload,
    create_shoot_block_payload,
    get_applicant,
    get_production,
    get_shoot_block,
    record_screening_items,
    set_clock,
    setup_applicant,
    setup_docusoap_production,
    setup_executed_agreement,
    setup_minor_applicant,
    setup_minor_protection,
    setup_planned_welfare_protocol,
    setup_published_casting_call,
    setup_sent_agreement,
    setup_trust_deposit,
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

# A coverage span wide enough to hold the whole photography window.
WIDE_COVERAGE = {
    "coverage_start_utc": "2026-09-01T00:00:00Z",
    "coverage_end_utc": "2026-12-31T00:00:00Z",
}

# A two-episode per-episode deal at a 100,000-cent episode rate.
BASE_TERMS = {
    "exclusivity_window_days": 0,
    "confidentiality_tier": "STANDARD",
    "depiction_rights_scope": "FULL",
    "stipend_structure": "PER_EPISODE",
    "base_stipend_cents": 100_000,
    "episodes_committed": 2,
}

# A GA packet at the state floor of 10 tutoring hours.
GA_PACKET = {
    "work_permit_number": "GA-2026-11842",
    "permit_expires_on": "2026-12-31",
    "education_hours_scheduled_weekly": 10,
}

# A venue registered without a municipal filming permit, so it may host studio
# work only.
PIER_NINE_STAGE = {
    "name": "Pier 9 Stage",
    "state_code": "GA",
    "capacity": 400,
    "turnaround_buffer_minutes": 60,
}

# A studio window well inside the production's photography window.
STUDIO_WINDOW = {
    "start_utc": "2026-09-20T08:00:00Z",
    "end_utc": "2026-09-20T12:00:00Z",
}


def _harbour_nights(**overrides):
    """A nine-episode DOCUSOAP in GA: STANDARD tier, no hazard uplift."""
    return setup_docusoap_production(title="Harbour Nights S1", **overrides)


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
    record_screening_items(applicant["id"], NO_PSYCH_SCREENING)
    return applicant


def _cleared_minor(call_id, **packet_overrides):
    """A minor applicant with a COMPLETE protection packet behind them."""
    minor = setup_minor_applicant(
        call_id,
        legal_name="Mika Vance",
        date_of_birth="2011-05-20",
        residency_state_code="GA",
        guardian_name="Dana Vance",
    )
    record_screening_items(minor["id"], FULL_PASS_SCREENING)
    packet = setup_minor_protection(minor["id"], **dict(GA_PACKET, **packet_overrides))
    return minor, packet


class TestPostObligationFulfilment:
    """Fulfilment is a state-changing POST with an empty body: it stamps the
    logical clock and it is not idempotent."""

    def test_fulfilment_stamps_the_logical_clock_and_refuses_a_second_call(self, api):
        """PRD §3.9: "`BusinessAffairs` closes an obligation out by recording the
        appearance, moving it `SCHEDULED → FULFILLED` and stamping `fulfilled_at`
        with the logical clock."
        PRD §3.9: "Fulfilment is admitted only while the obligation is
        `SCHEDULED` and only while the owning agreement is still `EXECUTED`."
        PRD §2.6: "The addressed entity is in a state from which the requested
        transition is declared, otherwise `ERR_INVALID_STATE_TRANSITION` (409).
        This rung applies to every action endpoint."
        PRD §3.9: "Every obligation records the `agreement_id` that owes the
        appearance and opens at `status` `SCHEDULED` with `fulfilled_at` absent."

        Design: Corner/endpoints/post_obligation_fulfill_sets_fulfilled_at_from_the_logical_clock
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        ada = _cleared_adult(call["id"], "Ada Reyes", "1994-04-02")

        sent = setup_sent_agreement(
            ada["id"],
            production["id"],
            press_appearance_obligation_count=1,
            **BASE_TERMS,
        )
        # The provisional variant assumes nine episodes at the 1.30 tier, three
        # junkets and a reunion; the final variant charges the one junket agreed.
        assert_money(sent["provisional_stipend_cents"], 1_395_000, "provisional stipend")
        executed = validate_success(api.execute_agreement(sent["id"], BA2))
        assert_money(
            executed["total_stipend_commitment_cents"], 225_000, "final stipend"
        )

        rows, meta = validate_paginated(api.list_post_obligations(sent["id"], BA1))
        assert meta["total_count"] == 1
        obligation = rows[0]
        assert obligation["kind"] == "PRESS_JUNKET"
        assert obligation["status"] == "SCHEDULED"
        assert obligation["fulfilled_at"] is None
        assert obligation["due_utc"].startswith("2027-01-14T00:00:00")
        assert_money(obligation["fee_cents"], 25_000, "junket fee")

        fulfilled = validate_success(
            api.fulfill_post_obligation(obligation["id"], BA1)
        )
        assert fulfilled["status"] == "FULFILLED"
        # No clock write has happened, so the stamp is the start-up instant.
        assert fulfilled["fulfilled_at"].startswith(DEFAULT_LOGICAL_CLOCK[:19])

        validate_error(
            api.fulfill_post_obligation(obligation["id"], BA1),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )
        assert get_production(production["id"])["breached_obligation_count"] == 0


class TestCastingCallApplicantsSubResource:
    """The nested applicant collection is scoped by the identifier in its path,
    and its filters narrow inside that scope."""

    def test_the_sub_resource_returns_only_the_addressed_calls_applicants(self, api):
        """PRD §3.2: "Calls can be listed and filtered by `production_id`, by
        `venue_location_id`, by `status` and by `channel`, and the applicants
        received through a single call can be listed and filtered by
        `screening_status` and `medical_status`."
        PRD §3.2: "Alongside its lifecycle fields each call maintains
        `screened_pass_count`, the number of applicants arriving through it whose
        `screening_status` has reached `CLEARED` or `CAST`; the counter is
        incremented by one each time one of the call's applicants clears
        screening."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`
        and `has_more` inside the `meta` object of the envelope, where
        `total_count` is the number of records matching the filters before
        pagination is applied and `has_more` states whether any matching record
        remains beyond the returned page."

        Design: Corner/endpoints/casting_call_applicants_sub_resource_returns_only_that_calls_applicants
        """
        production = _harbour_nights()
        call_one = _referral_call(production["id"])
        call_two = _referral_call(
            production["id"], channel="DIGITAL_SUBMISSION", exclusivity_window_days=30
        )

        ada = _cleared_adult(call_one["id"], "Ada Reyes", "1994-04-02")
        ben = setup_applicant(
            call_one["id"],
            legal_name="Ben Okafor",
            date_of_birth="1990-01-10",
            residency_state_code="GA",
        )
        cleo = setup_applicant(
            call_two["id"],
            legal_name="Cleo Nunes",
            date_of_birth="1988-03-03",
            residency_state_code="IL",
        )

        rows_one, meta_one = validate_paginated(
            api.list_casting_call_applicants(call_one["id"], CD)
        )
        assert meta_one["total_count"] == 2
        assert {row["id"] for row in rows_one} == {ada["id"], ben["id"]}

        rows_two, meta_two = validate_paginated(
            api.list_casting_call_applicants(call_two["id"], CD)
        )
        assert meta_two["total_count"] == 1
        assert rows_two[0]["id"] == cleo["id"]
        assert rows_two[0]["casting_call_id"] == call_two["id"]

        # The filter narrows within the addressed call, not across the production.
        cleared, meta_cleared = validate_paginated(
            api.list_casting_call_applicants(
                call_one["id"], CD, params={"screening_status": "CLEARED"}
            )
        )
        assert meta_cleared["total_count"] == 1
        assert cleared[0]["id"] == ada["id"]

        assert (
            validate_success(api.get_casting_call(call_one["id"], CD))[
                "screened_pass_count"
            ]
            == 1
        )
        assert (
            validate_success(api.get_casting_call(call_two["id"], CD))[
                "screened_pass_count"
            ]
            == 0
        )


class TestShootBlockParticipantLinks:
    """Scheduling resolves every entry of the link array back to its applicant
    and derives the minor head count from what it finds there."""

    def test_the_block_counts_only_the_minors_among_its_two_links(self, api):
        """PRD §3.8: "A newly scheduled block opens at `status` `SCHEDULED`, with
        `minor_participant_count` computed as the number of called agreements
        whose applicant is a minor, `covered_head_count` at 0 and
        `release_coverage_complete` false."
        PRD §3.8: "A `ProductionAdmin` schedules a shooting block by naming the
        `production_id`, the `location_id` of the occupied venue, the `block_kind`
        as `STUDIO`, `LOCATION_EXTERIOR` or `PUBLIC_SPACE`, the inclusive
        `start_utc` and the exclusive `end_utc` strictly after it, and
        `participant_agreement_ids`, the array of executed agreements called to
        the block, holding from 0 to 40 entries with no duplicates."
        PRD §3.6: "Second, because the final commitment was written, the
        production's `stipend_committed_cents` is recomputed by full re-summation
        over executed agreements and its `minor_participant_count` is recomputed
        as the count of executed agreements whose applicant is a minor."

        Design: Corner/endpoints/shoot_block_links_executed_agreements_and_counts_minors
        """
        production = _harbour_nights()
        venue = validate_success(api.create_location(dict(PIER_NINE_STAGE), PA), 201)
        call = _referral_call(production["id"])

        minor, packet = _cleared_minor(call["id"], trust_deposit_pct=0.10)
        assert minor["is_minor"] is True
        assert packet["status"] == "COMPLETE"
        adult = _cleared_adult(call["id"], "Ada Reyes", "1994-04-02")
        assert adult["is_minor"] is False

        minor_agreement = setup_executed_agreement(
            minor["id"], production["id"], **BASE_TERMS
        )
        adult_agreement = setup_executed_agreement(
            adult["id"], production["id"], **BASE_TERMS
        )

        block = validate_success(
            api.create_shoot_block(
                create_shoot_block_payload(
                    production["id"],
                    venue["id"],
                    participant_agreement_ids=[
                        minor_agreement["id"],
                        adult_agreement["id"],
                    ],
                    onset_minor_hours=4.0,
                    **STUDIO_WINDOW,
                ),
                PA,
            ),
            201,
        )
        assert block["status"] == "SCHEDULED"
        # Two links, one of them a minor.
        assert block["minor_participant_count"] == 1

        read_back = get_shoot_block(block["id"])
        assert read_back["minor_participant_count"] == 1
        assert read_back["covered_head_count"] == 0

        after = get_production(production["id"])
        assert after["minor_participant_count"] == 1
        assert_money(after["stipend_committed_cents"], 400_000, "committed stipend")


class TestProductionComputedRead:
    """One read returns every rollup at once, each traceable to a different child
    family, and reading changes nothing."""

    def test_a_single_read_returns_five_rollups_and_mutates_nothing(self, api):
        """PRD §3.1: "Reading a production back returns all of those figures
        alongside the derived posture, and it is the read every role in the system
        is permitted to perform, participants included."
        PRD §3.5: "That target is divided by the installment count and the
        quotient is rounded half up to whole cents to give `per_installment_cents`;
        `trust_deposited_cents` is then that rounded installment multiplied by the
        installment count, and it is not rounded again."
        PRD §2.7: "Otherwise the posture is `RESTRICTED` when committed stipend
        has reached ninety percent of the pool, or when the production admits
        minors at all and its minor headcount has caught up with its cap."
        PRD §2.4: "Most resources — productions, locations, casting calls,
        applicants, screening items, minor-protection packets, participant
        agreements, welfare protocols, shoot blocks and post-production
        obligations, together with complaints — additionally carry `updated_at`,
        an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an
        integer that begins at 1 when the record is created and increases by
        exactly one on every mutation."

        Design: Corner/endpoints/production_get_is_a_computed_read_of_every_rollup
        """
        production = _harbour_nights(minor_participant_cap=1)
        call = _referral_call(production["id"])
        minor, packet = _cleared_minor(call["id"], trust_deposit_pct=0.15)

        agreement = setup_executed_agreement(
            minor["id"], production["id"], **BASE_TERMS
        )
        assert_money(
            agreement["total_stipend_commitment_cents"], 200_000, "final stipend"
        )

        deposit = setup_trust_deposit(packet["id"], 7)
        # A fifteen-hundredths share of 200,000 is 30,000; a seventh of that is
        # 4,285.71 rounded up to 4,286, and seven of those is 30,002.
        assert_money(deposit["per_installment_cents"], 4_286, "per installment")
        assert_money(deposit["trust_deposited_cents"], 30_002, "trust deposited")

        setup_planned_welfare_protocol(
            production["id"],
            kind="DUTY_OF_CARE_OFFICER",
            cost_cents=500_000,
            **WIDE_COVERAGE,
        )

        first = get_production(production["id"])
        assert_money(first["stipend_committed_cents"], 200_000, "committed stipend")
        # 500,000 under the band floor is rated at 0.04 with the STANDARD factor.
        assert_money(first["welfare_committed_cents"], 520_000, "committed welfare")
        assert_money(first["trust_escrow_balance_cents"], 30_002, "trust escrow")
        assert first["minor_participant_count"] == 1
        # One minor against a cap of one restricts, and the referral call, not
        # being an open call, stays published through that cascade.
        assert first["casting_posture"] == "RESTRICTED"
        assert first["duty_of_care_tier"] == "STANDARD"
        assert first["welfare_incident_count"] == 0
        assert first["breached_obligation_count"] == 0

        second = get_production(production["id"], WO1)
        assert second["stipend_committed_cents"] == first["stipend_committed_cents"]
        assert second["welfare_committed_cents"] == first["welfare_committed_cents"]
        assert second["trust_escrow_balance_cents"] == first["trust_escrow_balance_cents"]
        assert second["casting_posture"] == first["casting_posture"]
        # Reading is not a mutation, so the version counter did not move.
        assert second["version"] == first["version"]
        assert second["updated_at"] == first["updated_at"]


class TestLogicalClockDefault:
    """Before any clock write the server reads the start-up instant, and every
    validity window is measured from the stamp the write itself took."""

    def test_the_start_up_epoch_stamps_the_first_write_and_the_window_runs_from_it(
        self, api
    ):
        """PRD §2.5: "On start-up the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it continues to read that instant until an
        administrator moves it; under no circumstance does it fall back to the
        host's real time."
        PRD §3.2: "On success the call's status becomes `PUBLISHED` and
        `published_at` is stamped with the logical clock's current instant."
        PRD §3.4: "On success the item's `outcome` and `severity_flags` are
        written, `recorded_by_user_id` is stamped with the caller's `X-User-ID`,
        `recorded_at` is stamped with the logical clock, and `expires_at` is
        derived from the kind's validity window: a `MEDICAL_EXAM` clearance is
        valid for 30 days from `recorded_at`, a `PSYCH_EVAL` for 60 days, a
        `BACKGROUND_CHECK` for 180 days, and an `INTERVIEW` never expires, so its
        `expires_at` remains absent."
        PRD §3.4: "Opening any screening item while the applicant's
        `screening_status` is `SUBMITTED` or `SCREENING` advances that dimension
        `SUBMITTED → SCREENING` and refreshes the provisional risk figure."

        Design: Corner/endpoints/logical_clock_default_is_2026_08_01_before_any_clock_set
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        assert call["published_at"].startswith(DEFAULT_LOGICAL_CLOCK[:19])

        early_applicant = setup_applicant(
            call["id"],
            legal_name="Ada Reyes",
            date_of_birth="1994-04-02",
            residency_state_code="GA",
        )
        early = validate_success(
            api.create_screening_item(
                early_applicant["id"],
                create_screening_item_payload("BACKGROUND_CHECK"),
                CO1,
            ),
            201,
        )
        assert early["outcome"] == "PASS"
        assert early["recorded_at"].startswith("2026-08-01T00:00:00")
        # 180 days from 2026-08-01.
        assert early["expires_at"].startswith("2027-01-28T00:00:00")

        set_clock("2026-08-15T00:00:00Z")
        later_applicant = setup_applicant(
            call["id"],
            legal_name="Ben Okafor",
            date_of_birth="1990-01-10",
            residency_state_code="GA",
        )
        later = validate_success(
            api.create_screening_item(
                later_applicant["id"],
                create_screening_item_payload("BACKGROUND_CHECK"),
                CO1,
            ),
            201,
        )
        assert later["recorded_at"].startswith("2026-08-15T00:00:00")
        # 180 days from its own recorded_at, not from the start-up epoch.
        assert later["expires_at"].startswith("2027-02-11T00:00:00")

        # One instrument short of the required set, so neither dimension resolves.
        assert get_applicant(early_applicant["id"], CO1)["screening_status"] == "SCREENING"
        assert get_applicant(later_applicant["id"], CO1)["screening_status"] == "SCREENING"
