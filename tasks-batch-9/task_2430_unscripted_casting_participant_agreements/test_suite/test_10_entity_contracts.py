"""Entity-shape contracts: what a create returns, what a read returns, which
fields are derived rather than supplied, which records are append-only, how the
list envelope paginates, and which 404 or 400 a malformed reference earns.
"""

from test_helpers import (
    DEFAULT_LOGICAL_CLOCK,
    TEST_USERS,
    UNKNOWN_UUID,
    ApiErrorId,
    assert_append_only_envelope,
    assert_money,
    assert_pagination_meta,
    assert_score,
    assert_versioned_envelope,
    create_agreement_payload,
    create_production_payload,
    get_applicant,
    get_applicant_version,
    make_applicant_headers,
    record_screening_items,
    setup_applicant,
    setup_casting_call,
    setup_docusoap_production,
    setup_published_casting_call,
    setup_sent_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["production_admin_headers"]
CD = TEST_USERS["casting_director_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]
BA1 = TEST_USERS["business_affairs_headers"]

# The three screening instruments a DOCUSOAP adult needs; no psych evaluation is
# demanded of them.
ADULT_REQUIRED_SET = (
    ("INTERVIEW", "PASS", 0, CO1),
    ("BACKGROUND_CHECK", "PASS", 0, CO1),
    ("MEDICAL_EXAM", "PASS", 0, CO1),
)

# A venue that carries no filming permit at all, which a STUDIO block does not
# need.
PIER_SEVEN_STAGE = {
    "name": "Pier 7 Stage",
    "state_code": "GA",
    "capacity": 400,
    "turnaround_buffer_minutes": 60,
}


def _harbour_nights(**overrides):
    """The reference DOCUSOAP / GA production of this file."""
    return setup_docusoap_production(title="Harbour Nights S1", **overrides)


class TestProductionCreation:
    """A production's welfare stance and every rollup are derived at creation."""

    def test_creation_derives_the_tier_and_opens_every_rollup_at_zero(self, api):
        """PRD §3.1: "A `COMPETITION_HIGH_STRESS` production opens at a
        `duty_of_care_tier` of `ENHANCED`; every other format opens at
        `STANDARD`."
        PRD §3.1: "The posture opens at `OPEN`, and every rolled-up figure opens
        at zero: `stipend_committed_cents`, `welfare_committed_cents`,
        `trust_escrow_balance_cents`, `welfare_incident_count`,
        `breached_obligation_count` and `minor_participant_count`."
        PRD §2.7: "The minor clause reads: `minor_participant_cap` is strictly
        greater than 0 and `minor_participant_count` is greater than or equal to
        `minor_participant_cap`."
        PRD §2.4: "`version`, an integer that begins at 1 when the record is
        created and increases by exactly one on every mutation."

        Design: Corner/entities/production_create_returns_full_row_with_derived_defaults
        """
        docusoap = _harbour_nights()
        assert docusoap["duty_of_care_tier"] == "STANDARD"

        high_stress = validate_success(
            api.create_production(
                create_production_payload(
                    title="Island Trials S2", season_number=2, minor_participant_cap=2
                ),
                PA,
            ),
            201,
        )
        assert high_stress["duty_of_care_tier"] == "ENHANCED"
        assert high_stress["casting_posture"] == "OPEN"
        assert_money(high_stress["stipend_committed_cents"], 0, "committed stipend")
        assert_money(high_stress["welfare_committed_cents"], 0, "committed welfare")
        assert_money(high_stress["trust_escrow_balance_cents"], 0, "trust escrow")
        assert high_stress["minor_participant_count"] == 0
        assert high_stress["welfare_incident_count"] == 0
        assert high_stress["breached_obligation_count"] == 0
        assert high_stress["version"] == 1
        # A cap of 2 with no minors on the books is not restricted: the clause
        # needs the headcount to have caught up with the cap.
        assert high_stress["minor_participant_cap"] == 2
        assert_versioned_envelope(high_stress, "Production")

    def test_the_read_returns_the_stored_row_and_is_open_to_every_role(self, api):
        """PRD §3.1: "Reading a production back returns all of those figures
        alongside the derived posture, and it is the read every role in the
        system is permitted to perform, participants included."
        PRD §3.1: "Photography is bounded by `photography_start_utc` and
        `photography_end_utc`, the latter strictly after the former; the start
        instant is the reference point for every minor-age determination in the
        system, and the end instant anchors every post-production due date."
        PRD §2.2: "The `data` field contains the resource object or an array of
        resource objects."

        Design: Corner/entities/production_get_returns_stored_row_and_every_rollup
        """
        production = _harbour_nights()

        # Read back by a role that does not own productions at all.
        seen = validate_success(api.get_production(production["id"], CD))
        assert seen["title"] == "Harbour Nights S1"
        assert_money(seen["stipend_pool_cents"], 5_000_000, "stipend pool")
        assert seen["episode_order"] == 9
        assert seen["casting_posture"] == "OPEN"
        assert seen["version"] == 1
        assert seen["jurisdiction_code"] == "GA"
        assert seen["photography_end_utc"].startswith("2026-12-15T00:00:00")


class TestListEnvelope:
    """The list envelope's total_count counts the filtered set, not the page."""

    def test_the_page_carries_the_whole_filtered_count_and_a_has_more_flag(self, api):
        """PRD §2.3: "Every list response carries `limit`, `offset`,
        `total_count` and `has_more` inside the `meta` object of the envelope,
        where `total_count` is the number of records matching the filters before
        pagination is applied and `has_more` states whether any matching record
        remains beyond the returned page."
        PRD §2.3: "Unless a specific endpoint states otherwise, list results are
        ordered by `created_at` ascending."
        PRD §3.2: "A freshly drafted call sits in `DRAFT` status, has never been
        published, and carries no closing reason."

        Design: Corner/entities/casting_calls_list_paginates_with_total_count_and_has_more
        """
        production = _harbour_nights()
        setup_casting_call(
            production["id"], channel="REFERRAL", min_age=13, max_age=60,
            exclusivity_window_days=0,
        )
        setup_casting_call(
            production["id"], channel="DIGITAL_SUBMISSION", min_age=18, max_age=45,
            exclusivity_window_days=30,
        )
        setup_casting_call(
            production["id"], channel="REFERRAL", min_age=21, max_age=70,
            exclusivity_window_days=60,
        )

        page1, meta1 = validate_paginated(
            api.list_casting_calls(
                CD, {"production_id": production["id"], "limit": 2, "offset": 0}
            )
        )
        assert len(page1) == 2
        assert_pagination_meta(meta1, total_count=3, has_more=True, limit=2, offset=0)
        assert page1[0]["status"] == "DRAFT"

        page2, meta2 = validate_paginated(
            api.list_casting_calls(
                CD, {"production_id": production["id"], "limit": 2, "offset": 2}
            )
        )
        assert len(page2) == 1
        assert_pagination_meta(meta2, total_count=3, has_more=False, limit=2, offset=2)


class TestPathAndBodyReferences:
    """Unresolvable identifiers are named by the kind that is missing."""

    def test_an_unknown_path_id_names_the_kind_it_could_not_resolve(self, api):
        """PRD §2.6: "Every identifier appearing in the URL path exists,
        validated left to right, with the failure reported as the 404 error
        naming the missing kind: `ERR_PRODUCTION_NOT_FOUND`,
        `ERR_CASTING_CALL_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
        `ERR_SCREENING_ITEM_NOT_FOUND`, `ERR_MINOR_PROTECTION_NOT_FOUND`,
        `ERR_AGREEMENT_NOT_FOUND`, `ERR_WELFARE_PROTOCOL_NOT_FOUND`,
        `ERR_SHOOT_BLOCK_NOT_FOUND`, `ERR_POST_OBLIGATION_NOT_FOUND` or
        `ERR_COMPLAINT_NOT_FOUND`."

        Design: Corner/entities/applicant_get_with_unknown_id_returns_not_found
        """
        # A real production exists, so neither 404 can be an empty-database
        # artefact.
        production = _harbour_nights()

        validate_error(
            api.get_applicant(UNKNOWN_UUID, CD),
            ApiErrorId.ERR_APPLICANT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_production(UNKNOWN_UUID, PA),
            ApiErrorId.ERR_PRODUCTION_NOT_FOUND.value,
            404,
        )
        assert validate_success(api.get_production(production["id"], PA))["version"] == 1

    def test_an_unknown_body_foreign_key_names_the_kind_it_could_not_resolve(self, api):
        """PRD §2.6: "Every foreign key carried in a request body exists —
        `production_id`, `venue_location_id`, `casting_call_id`, `applicant_id`,
        `location_id`, `supersedes_agreement_id`, and every entry of
        `participant_agreement_ids` — reported as `ERR_PRODUCTION_NOT_FOUND`,
        `ERR_LOCATION_NOT_FOUND`, `ERR_CASTING_CALL_NOT_FOUND`,
        `ERR_APPLICANT_NOT_FOUND` or `ERR_AGREEMENT_NOT_FOUND` (404)."
        PRD §2.6: "This rung applies to the four body-referencing creates:
        casting-call draft, applicant intake, agreement draft and shoot-block
        scheduling."

        Design: Corner/entities/casting_call_create_with_unknown_production_returns_not_found
        """
        production = _harbour_nights()
        venue = validate_success(api.create_location(dict(PIER_SEVEN_STAGE), PA), 201)

        validate_error(
            api.create_casting_call(
                {
                    "production_id": UNKNOWN_UUID,
                    "channel": "REFERRAL",
                    "min_age": 18,
                    "max_age": 45,
                    "exclusivity_window_days": 0,
                },
                CD,
            ),
            ApiErrorId.ERR_PRODUCTION_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_casting_call(
                {
                    "production_id": production["id"],
                    "channel": "OPEN_CALL",
                    "min_age": 18,
                    "max_age": 45,
                    "exclusivity_window_days": 0,
                    "venue_location_id": UNKNOWN_UUID,
                    "open_call_window_start_utc": "2026-08-05T00:00:00Z",
                    "open_call_window_end_utc": "2026-08-10T23:59:59Z",
                    "expected_attendance": 100,
                },
                CD,
            ),
            ApiErrorId.ERR_LOCATION_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_applicant(
                {
                    "casting_call_id": UNKNOWN_UUID,
                    "legal_name": "Ada Reyes",
                    "date_of_birth": "1994-04-02",
                    "residency_state_code": "GA",
                },
                CD,
            ),
            ApiErrorId.ERR_CASTING_CALL_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_shoot_block(
                {
                    "production_id": production["id"],
                    "location_id": venue["id"],
                    "block_kind": "STUDIO",
                    "start_utc": "2026-09-20T08:00:00Z",
                    "end_utc": "2026-09-20T12:00:00Z",
                    "participant_agreement_ids": [UNKNOWN_UUID],
                },
                PA,
            ),
            ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value,
            404,
        )

        # Nothing was persisted by any of the four refusals.
        _calls, call_meta = validate_paginated(
            api.list_casting_calls(CD, {"production_id": production["id"]})
        )
        assert call_meta["total_count"] == 0
        _blocks, block_meta = validate_paginated(
            api.list_shoot_blocks(PA, {"production_id": production["id"]})
        )
        assert block_meta["total_count"] == 0


class TestBodyShapeRung:
    """Rung 7 covers missing fields, bad enums, out-of-range numbers and
    misordered datetime pairs with one error id."""

    def _cleared_adult(self):
        production = _harbour_nights()
        call = setup_published_casting_call(
            production["id"], channel="REFERRAL", min_age=13, max_age=60,
            exclusivity_window_days=0,
        )
        applicant = setup_applicant(
            call["id"], legal_name="Ada Reyes", date_of_birth="1994-04-02",
            residency_state_code="GA",
        )
        record_screening_items(applicant["id"], ADULT_REQUIRED_SET)
        return production, call, applicant

    def test_omitting_a_required_field_persists_nothing(self, api):
        """PRD §2.6: "The request body is well shaped: every required field
        present, every enum value a declared member, every number inside its
        declared range, every datetime pair correctly ordered
        (`photography_end_utc` strictly after `photography_start_utc`,
        `coverage_end_utc` strictly after `coverage_start_utc`, `end_utc`
        strictly after `start_utc`, `open_call_window_end_utc` strictly after
        `open_call_window_start_utc`, and `max_age` no smaller than `min_age`),
        and `participant_agreement_ids` free of duplicate entries."
        PRD §2.6: "Any breach is `ERR_INVALID_REQUEST` (400)."
        PRD §3.6: "A `BusinessAffairs` user drafts an agreement by naming the
        `applicant_id` and the `production_id`, the `exclusivity_window_days`
        from 0 to 730 during which the participant may not appear on a competing
        programme after wrap, the `confidentiality_tier` as `STANDARD`,
        `ENHANCED` or `PERPETUAL`, the `depiction_rights_scope` as `FULL`,
        `LIMITED` or `PSEUDONYMIZED`, the `stipend_structure` as `FLAT`,
        `PER_EPISODE` or `TIERED` — the shape the money takes as agreed with the
        participant, recorded on the agreement as part of its terms — the
        `base_stipend_cents` per episode, and `episodes_committed` from 1 to 40."
        PRD §3.1: "A venue carries a `name`, a `state_code`, a `capacity` of at
        least 1 describing how many heads it can hold at once, and
        `turnaround_buffer_minutes`".

        Design: Corner/entities/agreement_create_missing_required_fields_rejected
        """
        production, _call, applicant = self._cleared_adult()
        version_before = get_applicant_version(applicant["id"])

        draft = create_agreement_payload(
            applicant["id"], production["id"], version_before,
            base_stipend_cents=100_000, episodes_committed=2,
            stipend_structure="PER_EPISODE",
        )
        draft.pop("confidentiality_tier")
        validate_error(
            api.create_agreement(draft, BA1),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api.create_location(
                {
                    "name": "Pier 7 Stage",
                    "state_code": "GA",
                    "turnaround_buffer_minutes": 60,
                },
                PA,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        _rows, meta = validate_paginated(
            api.list_agreements(BA1, {"production_id": production["id"]})
        )
        assert meta["total_count"] == 0
        assert get_applicant_version(applicant["id"]) == version_before

    def test_bad_enums_ranges_and_datetime_order_all_earn_the_same_refusal(self, api):
        """PRD §2.6: "every enum value a declared member, every number inside its
        declared range, every datetime pair correctly ordered
        (`photography_end_utc` strictly after `photography_start_utc`,
        `coverage_end_utc` strictly after `coverage_start_utc`, `end_utc`
        strictly after `start_utc`, `open_call_window_end_utc` strictly after
        `open_call_window_start_utc`, and `max_age` no smaller than `min_age`)"
        PRD §3.2: "a `channel` of `OPEN_CALL`, `DIGITAL_SUBMISSION` or
        `REFERRAL`, an age band of `min_age` between 13 and 80 and `max_age` no
        smaller than `min_age` and no greater than 99"
        PRD §3.4: "the officer also supplies `severity_flags`, the count of
        adverse findings on that instrument from 0 to 5 with a default of 0"

        Design: Corner/entities/casting_call_invalid_enum_and_misordered_age_band_rejected
        """
        production = _harbour_nights()
        call = setup_published_casting_call(
            production["id"], channel="REFERRAL", min_age=13, max_age=60,
            exclusivity_window_days=0,
        )
        applicant = setup_applicant(
            call["id"], legal_name="Ada Reyes", date_of_birth="1994-04-02",
            residency_state_code="GA",
        )

        # An out-of-enum channel.
        validate_error(
            api.create_casting_call(
                {
                    "production_id": production["id"],
                    "channel": "STREET_CAST",
                    "min_age": 18,
                    "max_age": 45,
                    "exclusivity_window_days": 30,
                },
                CD,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        # A max_age below min_age.
        validate_error(
            api.create_casting_call(
                {
                    "production_id": production["id"],
                    "channel": "REFERRAL",
                    "min_age": 30,
                    "max_age": 25,
                    "exclusivity_window_days": 30,
                },
                CD,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        # Six adverse findings against a declared range of nought to five.
        validate_error(
            api.create_screening_item(
                applicant["id"],
                {"kind": "INTERVIEW", "outcome": "CONDITIONAL", "severity_flags": 6},
                CO1,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api.create_production(
                create_production_payload(
                    title="Backwards S1",
                    format_type="DOCUSOAP",
                    jurisdiction_code="GA",
                    episode_order=9,
                    photography_start_utc="2026-12-15T00:00:00Z",
                    photography_end_utc="2026-09-15T00:00:00Z",
                ),
                PA,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        untouched = get_applicant(applicant["id"])
        assert untouched["screening_status"] == "SUBMITTED"
        assert_score(untouched["provisional_risk_score"], 0, "provisional risk")


class TestOmittedOptionalFields:
    """Omitted optional fields take their declared defaults, and a screening
    item opened without an outcome stays pending."""

    def test_defaults_are_applied_and_a_pending_item_is_charged_at_the_ceiling(
        self, api
    ):
        """PRD §3.6: "The draft may also carry
        `press_appearance_obligation_count`, the number of contracted
        press-junket appearances from 0 to 6 with a default of 0, and
        `reunion_obligation`, defaulting to false, stating whether the
        participant owes a reunion taping."
        PRD §3.6: "Drafting opens the agreement at `status` `DRAFTED` with
        `round_number` at 0, both stipend figures at 0, `welfare_hold` false, and
        it increments the applicant's `version` by one."
        PRD §3.4: "Supplying `outcome` records the result immediately; omitting
        it leaves the item's `outcome` at `PENDING` for later completion."
        PRD §3.4: "The **provisional ceiling** variant is written to
        `provisional_risk_score` on every screening-item write, and it charges
        every item that has not yet been recorded — every item whose
        `recorded_at` is still absent — at the pessimistic ceiling: 5 severity
        flags multiplied by that item's kind weight multiplied by a factor of
        one."
        PRD §3.4: "Opening any screening item while the applicant's
        `screening_status` is `SUBMITTED` or `SCREENING` advances that dimension
        `SUBMITTED → SCREENING` and refreshes the provisional risk figure."

        Design: Corner/entities/agreement_and_screening_defaults_applied_when_optional_fields_omitted
        """
        production = _harbour_nights()
        call = setup_published_casting_call(
            production["id"], channel="REFERRAL", min_age=13, max_age=60,
            exclusivity_window_days=0,
        )
        cleared = setup_applicant(
            call["id"], legal_name="Ada Reyes", date_of_birth="1994-04-02",
            residency_state_code="GA",
        )
        record_screening_items(cleared["id"], ADULT_REQUIRED_SET)

        minimal = create_agreement_payload(
            cleared["id"],
            production["id"],
            get_applicant_version(cleared["id"]),
            confidentiality_tier="STANDARD",
            depiction_rights_scope="FULL",
            stipend_structure="PER_EPISODE",
            base_stipend_cents=100_000,
            episodes_committed=2,
            exclusivity_window_days=0,
        )
        for optional in (
            "press_appearance_obligation_count",
            "reunion_obligation",
            "supersedes_agreement_id",
        ):
            minimal.pop(optional, None)

        agreement = validate_success(api.create_agreement(minimal, BA1), 201)
        assert agreement["press_appearance_obligation_count"] == 0
        assert agreement["reunion_obligation"] is False
        assert agreement["status"] == "DRAFTED"
        assert agreement["round_number"] == 0
        assert agreement["welfare_hold"] is False
        assert agreement["supersedes_agreement_id"] is None
        assert_money(agreement["provisional_stipend_cents"], 0, "provisional stipend")
        assert_money(agreement["total_stipend_commitment_cents"], 0, "final stipend")
        assert agreement["void_reason"] is None

        # A second applicant, because the first one's screening dimension has
        # already resolved to CLEARED.
        fresh = setup_applicant(
            call["id"], legal_name="Ben Okafor", date_of_birth="1990-01-10",
            residency_state_code="GA",
        )
        item = validate_success(
            api.create_screening_item(fresh["id"], {"kind": "INTERVIEW"}, CO1), 201
        )
        assert item["outcome"] == "PENDING"
        assert item["severity_flags"] == 0
        assert item["recorded_at"] is None
        assert item["expires_at"] is None

        scored = get_applicant(fresh["id"])
        # One unrecorded interview at the ceiling: 5 x 1.5 x 1 = 7.50.
        assert_score(scored["provisional_risk_score"], 7.50, "provisional risk")
        assert_score(scored["final_risk_score"], 0, "final risk")
        assert scored["screening_status"] == "SCREENING"


class TestComputedAndSystemFields:
    """Minority is judged at photography start, and audit stamps come from the
    header and the logical clock."""

    def test_one_day_of_birth_date_separates_a_minor_from_an_adult(self, api):
        """PRD §3.3: "`is_minor` is true when the applicant's completed age at
        `photography_start_utc` is under 18 — minority is judged as of the first
        day of principal photography, not as of the application date, so an
        applicant who turns 18 between applying and shooting is not a minor for
        this production's purposes."
        PRD §3.3: "`psych_eval_required` is true when the production's
        `format_type` is `COMPETITION_HIGH_STRESS` or when `is_minor` is true;
        high-stress formats and minors both attract mandatory psychological
        evaluation."
        PRD §3.3: "And the applicant's two independent state dimensions open at
        their initial values: `screening_status` at `SUBMITTED` and
        `medical_status` at `NOT_STARTED`."

        Design: Corner/entities/applicant_is_minor_computed_at_photography_start_boundary
        """
        production = _harbour_nights()
        call = setup_published_casting_call(
            production["id"], channel="REFERRAL", min_age=13, max_age=60,
            exclusivity_window_days=0,
        )

        # Photography starts 2026-09-15; a 2008-09-16 birthday has not landed by
        # then, so this applicant is still 17.
        minor = validate_success(
            api.create_applicant(
                {
                    "casting_call_id": call["id"],
                    "legal_name": "Mila Grant",
                    "date_of_birth": "2008-09-16",
                    "residency_state_code": "GA",
                    "guardian_name": "Dana Ruiz",
                },
                CD,
            ),
            201,
        )
        assert minor["is_minor"] is True
        assert minor["psych_eval_required"] is True
        assert minor["screening_status"] == "SUBMITTED"

        adult = validate_success(
            api.create_applicant(
                {
                    "casting_call_id": call["id"],
                    "legal_name": "Noel Grant",
                    "date_of_birth": "2008-09-14",
                    "residency_state_code": "GA",
                },
                CD,
            ),
            201,
        )
        assert adult["is_minor"] is False
        # A docusoap demands no psych evaluation of an adult.
        assert adult["psych_eval_required"] is False
        assert adult["medical_status"] == "NOT_STARTED"

    def test_audit_stamps_come_from_the_header_and_the_logical_clock(self, api):
        """PRD §3.4: "On success the item's `outcome` and `severity_flags` are
        written, `recorded_by_user_id` is stamped with the caller's `X-User-ID`,
        `recorded_at` is stamped with the logical clock, and `expires_at` is
        derived from the kind's validity window: a `MEDICAL_EXAM` clearance is
        valid for 30 days from `recorded_at`, a `PSYCH_EVAL` for 60 days, a
        `BACKGROUND_CHECK` for 180 days, and an `INTERVIEW` never expires, so its
        `expires_at` remains absent."
        PRD §2.5: "On start-up the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it continues to read that instant until an
        administrator moves it; under no circumstance does it fall back to the
        host's real time."

        Design: Corner/entities/screening_item_system_fields_and_expiry_stamped_by_logical_clock
        """
        production = _harbour_nights()
        call = setup_published_casting_call(
            production["id"], channel="REFERRAL", min_age=13, max_age=60,
            exclusivity_window_days=0,
        )
        applicant = setup_applicant(
            call["id"], legal_name="Ada Reyes", date_of_birth="1994-04-02",
            residency_state_code="GA",
        )

        interview = validate_success(
            api.create_screening_item(
                applicant["id"],
                {"kind": "INTERVIEW", "outcome": "PASS", "severity_flags": 0},
                CO1,
            ),
            201,
        )
        assert interview["recorded_by_user_id"] == "co_1"
        assert interview["recorded_at"].startswith(DEFAULT_LOGICAL_CLOCK[:19])
        assert interview["expires_at"] is None

        medical = validate_success(
            api.create_screening_item(
                applicant["id"],
                {"kind": "MEDICAL_EXAM", "outcome": "PASS", "severity_flags": 0},
                CO1,
            ),
            201,
        )
        # 2026-08-01 plus 30 days.
        assert medical["expires_at"].startswith("2026-08-31T00:00:00")

        background = validate_success(
            api.create_screening_item(
                applicant["id"],
                {"kind": "BACKGROUND_CHECK", "outcome": "PASS", "severity_flags": 0},
                CO1,
            ),
            201,
        )
        assert background["recorded_by_user_id"] == "co_1"
        # 2026-08-01 plus 180 days.
        assert background["expires_at"].startswith("2027-01-28T00:00:00")

        resolved = get_applicant(applicant["id"])
        assert resolved["screening_status"] == "CLEARED"
        assert resolved["medical_status"] == "CLEARED"
        assert_score(resolved["final_risk_score"], 0.00, "final risk")


class TestAppendOnlyRecords:
    """Negotiation rounds and releases carry neither version nor updated_at, and
    later writes never rewrite an earlier row."""

    def test_a_second_negotiation_round_leaves_the_first_one_verbatim(self, api):
        """PRD §2.4: "Negotiation rounds and incidental releases are append-only
        evidence, not editable state: each carries only `id` and `created_at`,
        and both `updated_at` and `version` are absent from those records
        entirely."
        PRD §2.4: "A negotiation round's `recorded_at` and a release's
        `collected_at` are stamped once at creation and never mutated
        thereafter."
        PRD §3.6: "A negotiation round is appended against the `agreement_id` of
        the agreement under negotiation, recording `proposed_by` as
        `PARTICIPANT`, `disposition` as `COUNTERED`, `proposer_user_id` as the
        caller's `X-User-ID`, `recorded_at` at the logical clock, and
        `round_number` as one more than the agreement's current round count; the
        agreement's own `round_number` is incremented by one, its `status`
        becomes `COUNTERED`, and its `version` is incremented by one."
        PRD §3.6: "A negotiation round is appended with `proposed_by` as
        `PRODUCTION` and `disposition` as `REVISED`, carrying the revised terms
        and a `round_number` one greater than the current count;
        `last_production_proposer_user_id` is set to the revising user's
        `X-User-ID`, the agreement's `round_number` is incremented by one, and
        the status becomes `REVISED`."

        Design: Corner/entities/negotiation_round_log_is_append_only_and_carries_no_version_field
        """
        production = _harbour_nights()
        call = setup_published_casting_call(
            production["id"], channel="REFERRAL", min_age=13, max_age=60,
            exclusivity_window_days=0,
        )
        applicant = setup_applicant(
            call["id"], legal_name="Ada Reyes", date_of_birth="1994-04-02",
            residency_state_code="GA",
        )
        record_screening_items(applicant["id"], ADULT_REQUIRED_SET)
        sent = setup_sent_agreement(
            applicant["id"],
            production["id"],
            confidentiality_tier="STANDARD",
            depiction_rights_scope="FULL",
            stipend_structure="PER_EPISODE",
            base_stipend_cents=100_000,
            episodes_committed=2,
            exclusivity_window_days=0,
        )

        validate_success(
            api.counter_offer_agreement(
                sent["id"],
                {
                    "requested_base_stipend_cents": 130_000,
                    "requested_exclusivity_window_days": 0,
                    "requested_depiction_rights_scope": "LIMITED",
                    "expected_agreement_version": sent["version"],
                },
                make_applicant_headers(applicant["id"]),
            )
        )

        first_log, first_meta = validate_paginated(
            api.list_negotiation_rounds(sent["id"], BA1)
        )
        assert first_meta["total_count"] == 1
        round_one = first_log[0]
        assert round_one["round_number"] == 1
        assert round_one["proposed_by"] == "PARTICIPANT"
        assert round_one["disposition"] == "COUNTERED"
        assert round_one["proposer_user_id"] == applicant["id"]
        assert round_one["recorded_at"].startswith(DEFAULT_LOGICAL_CLOCK[:19])
        assert_append_only_envelope(round_one, "NegotiationRound")

        validate_success(
            api.revise_agreement(
                sent["id"],
                {
                    "base_stipend_cents": 115_000,
                    "exclusivity_window_days": 0,
                    "depiction_rights_scope": "FULL",
                },
                BA1,
            )
        )

        second_log, second_meta = validate_paginated(
            api.list_negotiation_rounds(sent["id"], BA1)
        )
        assert second_meta["total_count"] == 2
        assert second_log[0]["disposition"] == "COUNTERED"
        assert second_log[0]["recorded_at"] == round_one["recorded_at"]
        assert second_log[1]["disposition"] == "REVISED"
        assert second_log[1]["proposed_by"] == "PRODUCTION"
        for row in second_log:
            assert_append_only_envelope(row, "NegotiationRound")

        agreement = validate_success(api.get_agreement(sent["id"], BA1))
        assert agreement["round_number"] == 2
        assert agreement["status"] == "REVISED"
        assert agreement["last_production_proposer_user_id"] == "ba_1"

    def test_a_second_release_recomputes_coverage_without_rewriting_the_first(
        self, api
    ):
        """PRD §2.4: "Negotiation rounds and incidental releases are append-only
        evidence, not editable state: each carries only `id` and `created_at`,
        and both `updated_at` and `version` are absent from those records
        entirely."
        PRD §3.8: "Collection stamps `collected_at` with the logical clock and is
        never mutated afterwards."
        PRD §3.8: "Every release write, and again the start of every wrap
        attempt, recomputes the block's coverage."
        PRD §3.8: "`covered_head_count` is the sum of `head_count` over the
        block's releases whose `disposition` is `COLLECTED` or `BLURRED_WAIVER`;
        a `REFUSED` release contributes nothing."

        Design: Corner/entities/release_rows_are_append_only_and_carry_no_version_field
        """
        production = _harbour_nights()
        venue = validate_success(api.create_location(dict(PIER_SEVEN_STAGE), PA), 201)
        block = validate_success(
            api.create_shoot_block(
                {
                    "production_id": production["id"],
                    "location_id": venue["id"],
                    "block_kind": "STUDIO",
                    "start_utc": "2026-09-20T08:00:00Z",
                    "end_utc": "2026-09-20T12:00:00Z",
                    "participant_agreement_ids": [],
                    "expected_crowd_headcount": 40,
                },
                PA,
            ),
            201,
        )

        first = validate_success(
            api.collect_release(
                block["id"],
                {
                    "subject_kind": "INCIDENTAL_CROWD",
                    "head_count": 25,
                    "disposition": "COLLECTED",
                },
                PA,
            ),
            201,
        )
        assert first["collected_at"].startswith(DEFAULT_LOGICAL_CLOCK[:19])
        assert_append_only_envelope(first, "Release")

        partial = validate_success(api.get_shoot_block(block["id"], PA))
        assert partial["covered_head_count"] == 25
        assert partial["release_coverage_complete"] is False

        validate_success(
            api.collect_release(
                block["id"],
                {
                    "subject_kind": "BYSTANDER_IDENTIFIABLE",
                    "head_count": 3,
                    "disposition": "REFUSED",
                    "subject_name": "Unknown Passer-By",
                },
                PA,
            ),
            201,
        )
        validate_success(
            api.collect_release(
                block["id"],
                {
                    "subject_kind": "INCIDENTAL_CROWD",
                    "head_count": 15,
                    "disposition": "BLURRED_WAIVER",
                },
                PA,
            ),
            201,
        )

        rows, meta = validate_paginated(api.list_releases(block["id"], PA))
        assert meta["total_count"] == 3
        assert rows[0]["collected_at"] == first["collected_at"]
        for row in rows:
            assert_append_only_envelope(row, "Release")

        # 25 collected plus 15 blurred is 40; the three refused heads count for
        # nothing.
        covered = validate_success(api.get_shoot_block(block["id"], PA))
        assert covered["covered_head_count"] == 40
        assert covered["release_coverage_complete"] is True
        assert covered["status"] == "SCHEDULED"
