"""Input guards read one rule at a time: which side of an inclusive bound a
value falls on, which conditional field becomes mandatory once a derived flag
turns true, whether a window is closed at both ends, whether an aggregate is
measured before or after a surcharge, whether a referenced row's live status is
read as well as its existence, and which of two simultaneously violated rules the
ladder reports.
"""

from test_helpers import (
    NO_PSYCH_SCREENING,
    TEST_USERS,
    ApiErrorId,
    assert_money,
    create_agreement_payload,
    create_applicant_payload,
    create_shoot_block_payload,
    get_agreement,
    get_applicant,
    get_applicant_version,
    get_production,
    get_shoot_block,
    record_screening_items,
    route_payload,
    run_welfare_epoch,
    set_clock,
    setup_active_welfare_protocol,
    setup_applicant,
    setup_docusoap_production,
    setup_drafted_agreement,
    setup_executed_agreement,
    setup_location,
    setup_open_call,
    setup_published_casting_call,
    setup_sent_agreement,
    setup_shoot_block,
    setup_triaged_complaint,
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
WO2 = TEST_USERS["welfare_officer_2_headers"]

# A coverage span wide enough to hold the whole photography window.
WIDE_COVERAGE = {
    "coverage_start_utc": "2026-09-01T00:00:00Z",
    "coverage_end_utc": "2026-12-31T00:00:00Z",
}

# A two-episode per-episode deal at a 100,000-cent episode rate, with no
# exclusivity, no press appearances and no reunion.
BASE_TERMS = {
    "exclusivity_window_days": 0,
    "confidentiality_tier": "STANDARD",
    "depiction_rights_scope": "FULL",
    "stipend_structure": "PER_EPISODE",
    "base_stipend_cents": 100_000,
    "episodes_committed": 2,
}

# A single-episode flat deal whose provisional figure is dominated by the press
# reserve and the assumed reunion rather than by its base.
ONE_EPISODE_TERMS = {
    "exclusivity_window_days": 0,
    "confidentiality_tier": "STANDARD",
    "depiction_rights_scope": "FULL",
    "stipend_structure": "FLAT",
    "base_stipend_cents": 900_000,
    "episodes_committed": 1,
}

# A venue registered without a municipal filming permit, so it may host studio
# work only.
PIER_NINE_STAGE = {
    "name": "Pier 9 Stage",
    "state_code": "GA",
    "capacity": 400,
    "turnaround_buffer_minutes": 60,
}

# The block window the scheduling recipes share; it sits well inside the
# production's photography window.
STUDIO_WINDOW = {
    "start_utc": "2026-09-20T08:00:00Z",
    "end_utc": "2026-09-20T12:00:00Z",
}


def _harbour_nights(**overrides):
    """A nine-episode DOCUSOAP in GA: STANDARD tier, no hazard uplift."""
    kwargs = {"title": "Harbour Nights S1"}
    kwargs.update(overrides)
    return setup_docusoap_production(**kwargs)


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


class TestApplicantEligibility:
    """Intake measures age against the first day of principal photography, and
    the residency clause is a second, independently falsifiable condition."""

    def test_forty_five_at_photography_start_clears_the_inclusive_upper_bound(self, api):
        """PRD §2.6: "On applicant intake, the applicant is eligible for the call:
        their completed age at the production's `photography_start_utc` lies
        between `min_age` and `max_age` inclusive, and when the call's
        `residency_state_code` is set, the applicant's `residency_state_code`
        equals it. Otherwise `ERR_ELIGIBILITY_NOT_MET` (422)."
        PRD §3.3: "Eligibility is then checked against the call's own criteria:
        the applicant's completed age at the production's `photography_start_utc`
        must lie inside the band bounded inclusively by `min_age` and `max_age`,
        and where the call demands a residency state the applicant's
        `residency_state_code` must equal it."
        PRD §3.3: "And the applicant's two independent state dimensions open at
        their initial values: `screening_status` at `SUBMITTED` and
        `medical_status` at `NOT_STARTED`."

        Design: Corner/validations/eligibility_age_band_upper_bound_is_inclusive
        """
        production = _harbour_nights()
        call = _referral_call(
            production["id"], min_age=18, max_age=45, residency_state_code="GA"
        )

        # Photography starts 2026-09-15, so a 1981-09-15 birthday lands on
        # exactly 45; measured at the logical clock's 2026-08-01 she is still 44.
        at_bound = validate_success(
            api.create_applicant(
                create_applicant_payload(
                    call["id"],
                    legal_name="Rita Boundary",
                    date_of_birth="1981-09-15",
                    residency_state_code="GA",
                ),
                CD,
            ),
            201,
        )
        assert at_bound["screening_status"] == "SUBMITTED"
        assert at_bound["medical_status"] == "NOT_STARTED"
        assert at_bound["is_minor"] is False

        # One year older is 46 at the same instant, one clear of the band.
        validate_error(
            api.create_applicant(
                create_applicant_payload(
                    call["id"],
                    legal_name="Oren Overage",
                    date_of_birth="1980-09-15",
                    residency_state_code="GA",
                ),
                CD,
            ),
            ApiErrorId.ERR_ELIGIBILITY_NOT_MET.value,
            422,
        )

        # Perfectly aged, but resident in the wrong state for a GA-only call.
        validate_error(
            api.create_applicant(
                create_applicant_payload(
                    call["id"],
                    legal_name="Nadia Elsewhere",
                    date_of_birth="1994-04-02",
                    residency_state_code="NY",
                ),
                CD,
            ),
            ApiErrorId.ERR_ELIGIBILITY_NOT_MET.value,
            422,
        )

        after = validate_success(api.get_casting_call(call["id"], CD))
        assert after["screened_pass_count"] == 0

    def test_a_minor_without_a_guardian_name_is_refused_after_the_age_band_passes(
        self, api
    ):
        """PRD §3.3: "When the applicant is a minor the payload must also name the
        parent or guardian of record as `guardian_name`; omitting it for a minor
        is refused with `ERR_GUARDIAN_REQUIRED`."
        PRD §2.6: "On applicant intake, a minor applicant supplies
        `guardian_name`, otherwise `ERR_GUARDIAN_REQUIRED` (422)."
        PRD §3.3: "`psych_eval_required` is true when the production's
        `format_type` is `COMPETITION_HIGH_STRESS` or when `is_minor` is true;
        high-stress formats and minors both attract mandatory psychological
        evaluation."

        Design: Corner/validations/minor_application_without_guardian_name_rejected
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])

        # Fifteen at photography start, so the 13..60 band is satisfied and only
        # the missing guardian can fail: a derived refusal, not a shape error.
        payload = create_applicant_payload(
            call["id"],
            legal_name="Mika Vance",
            date_of_birth="2011-05-20",
            residency_state_code="GA",
        )
        validate_error(
            api.create_applicant(payload, CD),
            ApiErrorId.ERR_GUARDIAN_REQUIRED.value,
            422,
        )

        admitted = validate_success(
            api.create_applicant(dict(payload, guardian_name="Dana Vance"), CD), 201
        )
        assert admitted["is_minor"] is True
        assert admitted["guardian_name"] == "Dana Vance"
        assert admitted["psych_eval_required"] is True

        after = validate_success(api.get_casting_call(call["id"], CD))
        assert after["screened_pass_count"] == 0


class TestOpenCallIntakeWindow:
    """The open-call intake window is closed at both ends, and only the logical
    clock decides which side of it a request falls on."""

    def test_the_closing_instant_is_inside_the_window_and_one_second_later_is_not(
        self, api
    ):
        """PRD §2.6: "On applicant intake through a call whose `channel` is
        `OPEN_CALL`, the logical clock lies inside the closed intake window
        bounded inclusively by `open_call_window_start_utc` and
        `open_call_window_end_utc`, otherwise `ERR_OPEN_CALL_WINDOW_CLOSED`
        (409)."
        PRD §3.3: "Intake is admitted only into a call whose `status` is
        `PUBLISHED` — an application against a draft or closed call is refused
        with `ERR_CASTING_CALL_NOT_OPEN` — and, when the call's channel is
        `OPEN_CALL`, only while the logical clock lies inside the inclusive intake
        window, failing which the answer is `ERR_OPEN_CALL_WINDOW_CLOSED`."
        PRD §2.5: "Every deadline, expiry, intake window, coverage interval and
        age determination in this specification is evaluated against the server's
        **logical clock**, never against real wall-clock time."

        Design: Corner/validations/open_call_intake_inside_and_outside_the_closed_window
        """
        production = _harbour_nights()
        venue = setup_location(
            name="Savannah Civic Hall",
            state_code="GA",
            capacity=400,
            turnaround_buffer_minutes=30,
        )
        call = setup_open_call(
            production["id"],
            venue["id"],
            min_age=13,
            max_age=60,
            open_call_window_start_utc="2026-08-05T00:00:00Z",
            open_call_window_end_utc="2026-08-10T23:59:59Z",
            expected_attendance=100,
        )
        assert call["status"] == "PUBLISHED"

        def _apply(legal_name):
            return api.create_applicant(
                create_applicant_payload(
                    call["id"],
                    legal_name=legal_name,
                    date_of_birth="1994-04-02",
                    residency_state_code="GA",
                ),
                CD,
            )

        # One second before the window opens.
        set_clock("2026-08-04T23:59:59Z")
        validate_error(
            _apply("Early Bird"),
            ApiErrorId.ERR_OPEN_CALL_WINDOW_CLOSED.value,
            409,
        )

        # Exactly the closing instant, which the inclusive upper bound admits.
        set_clock("2026-08-10T23:59:59Z")
        at_edge = validate_success(_apply("Last Second"), 201)
        assert at_edge["screening_status"] == "SUBMITTED"

        # One second past it.
        set_clock("2026-08-11T00:00:00Z")
        validate_error(
            _apply("Too Late"),
            ApiErrorId.ERR_OPEN_CALL_WINDOW_CLOSED.value,
            409,
        )

        after = validate_success(api.get_casting_call(call["id"], CD))
        assert after["screened_pass_count"] == 0


class TestMinorProtectionJurisdictionalFloors:
    """Both statutory minimums are inclusive floors, and when both are short the
    ladder decides which error the client hears."""

    def test_the_education_floor_is_reported_before_the_trust_floor(self, api):
        """PRD §2.6: "On minor-protection filing and on minor-protection
        amendment, `education_hours_scheduled_weekly` is at least the jurisdiction
        minimum, otherwise `ERR_EDUCATION_HOURS_SHORTFALL` (422)."
        PRD §2.6: "On minor-protection filing and on minor-protection amendment,
        `trust_deposit_pct` is at least the jurisdiction minimum, otherwise
        `ERR_TRUST_DEPOSIT_SHORTFALL` (422)."
        PRD §2.6: "Because most operations in this API are guarded by several
        independent rules at once, the order in which those rules are evaluated is
        part of the contract: the first rule that fails determines the response,
        and no later rule is evaluated."
        PRD §2.12: "The weekly on-set tutoring minimum is 15 hours in `CA`, 12
        hours in `NY`, 10 hours in `GA` and 12 hours in `IL`; a packet whose
        `education_hours_scheduled_weekly` is below the applicable figure is
        refused with `ERR_EDUCATION_HOURS_SHORTFALL`."
        PRD §2.12: "The blocked-trust minimum is fifteen hundredths of the
        executed stipend in `CA` and in `NY`, and ten hundredths in `GA` and in
        `IL`; a packet whose `trust_deposit_pct` is below the applicable fraction
        is refused with `ERR_TRUST_DEPOSIT_SHORTFALL`."

        Design: Corner/validations/education_shortfall_outranks_trust_shortfall_on_minor_protection
        """
        production = _harbour_nights(title="Hudson Diaries S1", jurisdiction_code="NY")
        call = _referral_call(production["id"])
        minor = validate_success(
            api.create_applicant(
                create_applicant_payload(
                    call["id"],
                    legal_name="Mika Vance",
                    date_of_birth="2011-05-20",
                    residency_state_code="NY",
                    guardian_name="Dana Vance",
                ),
                CD,
            ),
            201,
        )
        permit = {
            "work_permit_number": "NY-2026-40011",
            "permit_expires_on": "2026-12-31",
        }

        # New York asks for 12 tutoring hours and fifteen hundredths in trust.
        validate_error(
            api.create_minor_protection(
                minor["id"],
                dict(permit, education_hours_scheduled_weekly=10, trust_deposit_pct=0.15),
                CO1,
            ),
            ApiErrorId.ERR_EDUCATION_HOURS_SHORTFALL.value,
            422,
        )
        validate_error(
            api.create_minor_protection(
                minor["id"],
                dict(permit, education_hours_scheduled_weekly=12, trust_deposit_pct=0.10),
                CO1,
            ),
            ApiErrorId.ERR_TRUST_DEPOSIT_SHORTFALL.value,
            422,
        )
        # Both short at once: the education rung sits above the trust rung.
        validate_error(
            api.create_minor_protection(
                minor["id"],
                dict(permit, education_hours_scheduled_weekly=10, trust_deposit_pct=0.10),
                CO1,
            ),
            ApiErrorId.ERR_EDUCATION_HOURS_SHORTFALL.value,
            422,
        )

        packet = validate_success(
            api.create_minor_protection(
                minor["id"],
                dict(permit, education_hours_scheduled_weekly=12, trust_deposit_pct=0.15),
                CO1,
            ),
            201,
        )
        assert packet["status"] == "COMPLETE"


class TestAgreementUniquenessAndSupersede:
    """At most one live agreement per applicant, and a supersede target must be
    that applicant's own live row."""

    def test_a_second_live_agreement_is_admitted_only_by_naming_the_first(self, api):
        """PRD §2.6: "On agreement drafting, the applicant has no other agreement
        whose `status` is `DRAFTED`, `SENT`, `COUNTERED`, `REVISED` or `EXECUTED`,
        unless `supersedes_agreement_id` names exactly that agreement. Otherwise
        `ERR_DUPLICATE_AGREEMENT` (409)."
        PRD §3.6: "A draft may finally name `supersedes_agreement_id`, the same
        applicant's prior non-terminal agreement that this one replaces; when
        supplied, that prior agreement — which must belong to the same applicant
        and be in `DRAFTED`, `SENT`, `COUNTERED` or `REVISED` status — moves to
        `VOIDED` with `void_reason` set to `SUPERSEDED` and its `version`
        incremented by one."
        PRD §2.11: "Committed stipend is the sum of
        `total_stipend_commitment_cents` over the production's participant
        agreements whose `status` is `EXECUTED`."

        Design: Corner/validations/duplicate_agreement_without_supersede_rejected
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        ada = _cleared_adult(call["id"], "Ada Reyes", "1994-04-02")

        first = setup_drafted_agreement(ada["id"], production["id"], **BASE_TERMS)
        assert first["status"] == "DRAFTED"

        # A DRAFTED row is already live, so the bare second draft is refused even
        # though nothing has been executed.
        validate_error(
            api.create_agreement(
                create_agreement_payload(
                    ada["id"],
                    production["id"],
                    get_applicant_version(ada["id"]),
                    **dict(BASE_TERMS, base_stipend_cents=120_000),
                ),
                BA1,
            ),
            ApiErrorId.ERR_DUPLICATE_AGREEMENT.value,
            409,
        )

        second = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    ada["id"],
                    production["id"],
                    get_applicant_version(ada["id"]),
                    supersedes_agreement_id=first["id"],
                    **dict(BASE_TERMS, base_stipend_cents=120_000),
                ),
                BA1,
            ),
            201,
        )
        assert second["status"] == "DRAFTED"

        # Naming the target both admits the new row and retires the old one, so
        # exactly one live agreement remains.
        superseded = get_agreement(first["id"])
        assert superseded["status"] == "VOIDED"
        assert superseded["void_reason"] == "SUPERSEDED"
        assert_money(
            get_production(production["id"])["stipend_committed_cents"],
            0,
            "committed stipend",
        )

    def test_a_supersede_target_owned_by_another_applicant_is_refused(self, api):
        """PRD §2.6: "On agreement drafting, `supersedes_agreement_id`, when
        supplied, references an agreement of the same applicant whose `status` is
        `DRAFTED`, `SENT`, `COUNTERED` or `REVISED`, otherwise
        `ERR_SUPERSEDE_TARGET_INVALID` (422)."
        PRD §3.6: "A draft may finally name `supersedes_agreement_id`, the same
        applicant's prior non-terminal agreement that this one replaces; when
        supplied, that prior agreement — which must belong to the same applicant
        and be in `DRAFTED`, `SENT`, `COUNTERED` or `REVISED` status — moves to
        `VOIDED` with `void_reason` set to `SUPERSEDED` and its `version`
        incremented by one."

        Design: Corner/validations/supersede_target_of_another_applicant_rejected
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        ada = _cleared_adult(call["id"], "Ada Reyes", "1994-04-02")
        ben = _cleared_adult(call["id"], "Ben Okafor", "1990-01-10")

        ada_agreement = setup_drafted_agreement(
            ada["id"], production["id"], **BASE_TERMS
        )

        # Ben holds no live agreement of his own, so the duplicate rung cannot be
        # the failure; only the target's ownership can be.
        validate_error(
            api.create_agreement(
                create_agreement_payload(
                    ben["id"],
                    production["id"],
                    get_applicant_version(ben["id"]),
                    supersedes_agreement_id=ada_agreement["id"],
                    **BASE_TERMS,
                ),
                BA1,
            ),
            ApiErrorId.ERR_SUPERSEDE_TARGET_INVALID.value,
            422,
        )

        ben_agreement = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    ben["id"],
                    production["id"],
                    get_applicant_version(ben["id"]),
                    **BASE_TERMS,
                ),
                BA1,
            ),
            201,
        )
        assert ben_agreement["status"] == "DRAFTED"

        untouched = get_agreement(ada_agreement["id"])
        assert untouched["status"] == "DRAFTED"
        assert untouched["void_reason"] is None


class TestWelfareProtocolConditionalFields:
    """The carrier certificate is demanded of one kind only, and on both of the
    writes that admit that kind."""

    def test_the_carrier_certificate_is_demanded_only_of_an_insurance_rider(self, api):
        """PRD §3.7: "A protocol whose kind is `INSURANCE_RIDER` must also carry
        `carrier_certificate_number`, both when it is planned and when it is later
        activated; without it the answer is `ERR_INSURANCE_CERTIFICATE_MISSING`."
        PRD §2.6: "On welfare-protocol planning and on welfare-protocol
        activation, a protocol whose `kind` is `INSURANCE_RIDER` carries
        `carrier_certificate_number`, otherwise
        `ERR_INSURANCE_CERTIFICATE_MISSING` (422)."
        PRD §3.7: "A newly planned protocol sits at `status` `PLANNED`."
        PRD §3.7: "Activation moves a protocol `PLANNED → ACTIVE` and is admitted
        only from `PLANNED`, only when an insurance rider carries its certificate,
        and only while `coverage_end_utc` is still later than the logical clock —
        coverage that is already over cannot be activated."

        Design: Corner/validations/insurance_rider_without_certificate_rejected
        """
        production = _harbour_nights()
        rider = {"kind": "INSURANCE_RIDER", "cost_cents": 500_000, **WIDE_COVERAGE}

        validate_error(
            api.plan_welfare_protocol(production["id"], rider, WO1),
            ApiErrorId.ERR_INSURANCE_CERTIFICATE_MISSING.value,
            422,
        )

        # The same omission on a different kind is not a defect at all.
        officer = validate_success(
            api.plan_welfare_protocol(
                production["id"],
                {"kind": "DUTY_OF_CARE_OFFICER", "cost_cents": 500_000, **WIDE_COVERAGE},
                WO1,
            ),
            201,
        )
        assert officer["carrier_certificate_number"] is None
        assert officer["status"] == "PLANNED"

        certified = validate_success(
            api.plan_welfare_protocol(
                production["id"],
                dict(rider, carrier_certificate_number="CERT-AX-99814"),
                WO1,
            ),
            201,
        )
        assert certified["status"] == "PLANNED"
        activated = validate_success(
            api.activate_welfare_protocol(certified["id"], WO1)
        )
        assert activated["status"] == "ACTIVE"

        # Two 500,000 rows subtotal to 1,000,000, below the 5,000,000 band floor,
        # so the rate is 0.04 at the STANDARD tier factor of one.
        assert_money(
            get_production(production["id"])["welfare_committed_cents"],
            1_040_000,
            "committed welfare",
        )


class TestShootBlockSchedulingGuards:
    """Scheduling reads the venue's permit against the block's kind, the called
    agreements' live status, and the containment of the whole interval."""

    def test_the_filming_permit_gates_exterior_work_and_not_studio_work(self, api):
        """PRD §2.6: "On shoot-block scheduling, a block whose `block_kind` is
        `LOCATION_EXTERIOR` or `PUBLIC_SPACE` sits at a venue whose
        `filming_permit_number` is present, otherwise
        `ERR_LOCATION_PERMIT_MISSING` (422)."
        PRD §3.8: "A block whose kind is `LOCATION_EXTERIOR` or `PUBLIC_SPACE`
        must sit at a venue carrying a `filming_permit_number`; a permit-less
        venue may host `STUDIO` work only, and any other kind there is refused
        with `ERR_LOCATION_PERMIT_MISSING`."
        PRD §3.1: "A venue may also carry `filming_permit_number`, its municipal
        filming permit; when that field is absent the venue may host studio work
        only, and any attempt to schedule exterior or public-space shooting there
        is refused."

        Design: Corner/validations/exterior_block_at_venue_without_filming_permit_rejected
        """
        production = _harbour_nights()
        bare = validate_success(api.create_location(dict(PIER_NINE_STAGE), PA), 201)
        assert bare["filming_permit_number"] is None
        permitted = setup_location(
            name="River Street Block",
            state_code="GA",
            capacity=800,
            turnaround_buffer_minutes=90,
            filming_permit_number="GA-SAV-2026-0455",
        )

        validate_error(
            api.create_shoot_block(
                create_shoot_block_payload(
                    production["id"],
                    bare["id"],
                    block_kind="LOCATION_EXTERIOR",
                    **STUDIO_WINDOW,
                ),
                PA,
            ),
            ApiErrorId.ERR_LOCATION_PERMIT_MISSING.value,
            422,
        )

        # The identical interval at the identical venue is fine as studio work.
        studio = validate_success(
            api.create_shoot_block(
                create_shoot_block_payload(
                    production["id"], bare["id"], block_kind="STUDIO", **STUDIO_WINDOW
                ),
                PA,
            ),
            201,
        )
        assert studio["status"] == "SCHEDULED"
        assert studio["minor_participant_count"] == 0

        exterior = validate_success(
            api.create_shoot_block(
                create_shoot_block_payload(
                    production["id"],
                    permitted["id"],
                    block_kind="LOCATION_EXTERIOR",
                    **STUDIO_WINDOW,
                ),
                PA,
            ),
            201,
        )
        assert exterior["status"] == "SCHEDULED"

    def test_a_sent_agreement_cannot_be_called_to_a_block_until_it_executes(self, api):
        """PRD §2.6: "On shoot-block scheduling, every entry of
        `participant_agreement_ids` belongs to the named `production_id` and has
        `status` `EXECUTED`, otherwise `ERR_PARTICIPANT_NOT_EXECUTED` (422)."
        PRD §3.8: "Every entry of `participant_agreement_ids` must belong to the
        named production and be in `EXECUTED` status, failing which the answer is
        `ERR_PARTICIPANT_NOT_EXECUTED`."
        PRD §3.8: "A newly scheduled block opens at `status` `SCHEDULED`, with
        `minor_participant_count` computed as the number of called agreements
        whose applicant is a minor, `covered_head_count` at 0 and
        `release_coverage_complete` false."

        Design: Corner/validations/shoot_block_with_non_executed_agreement_rejected
        """
        production = _harbour_nights()
        venue = validate_success(api.create_location(dict(PIER_NINE_STAGE), PA), 201)
        call = _referral_call(production["id"])
        ada = _cleared_adult(call["id"], "Ada Reyes", "1994-04-02")

        agreement = setup_sent_agreement(ada["id"], production["id"], **BASE_TERMS)
        assert agreement["status"] == "SENT"

        payload = create_shoot_block_payload(
            production["id"],
            venue["id"],
            participant_agreement_ids=[agreement["id"]],
            **STUDIO_WINDOW,
        )
        # The id resolves, so this is the referenced row's live status talking,
        # not a missing foreign key.
        validate_error(
            api.create_shoot_block(payload, PA),
            ApiErrorId.ERR_PARTICIPANT_NOT_EXECUTED.value,
            422,
        )

        executed = validate_success(api.execute_agreement(agreement["id"], BA2))
        assert executed["status"] == "EXECUTED"

        block = validate_success(api.create_shoot_block(payload, PA), 201)
        assert block["status"] == "SCHEDULED"
        assert block["minor_participant_count"] == 0

    def test_a_block_straddling_either_end_of_the_photography_window_is_refused(
        self, api
    ):
        """PRD §2.6: "On shoot-block scheduling, the block interval lies inside
        the production's photography window, otherwise
        `ERR_OUTSIDE_PHOTOGRAPHY_WINDOW` (422)."
        PRD §3.8: "The block interval must lie inside the production's window from
        `photography_start_utc` to `photography_end_utc`."

        Design: Corner/validations/shoot_block_outside_photography_window_rejected
        """
        production = _harbour_nights()
        venue = validate_success(api.create_location(dict(PIER_NINE_STAGE), PA), 201)

        # Photography runs 2026-09-15T00:00 to 2026-12-15T00:00. Each of these
        # two blocks overlaps the window without lying inside it.
        validate_error(
            api.create_shoot_block(
                create_shoot_block_payload(
                    production["id"],
                    venue["id"],
                    start_utc="2026-09-14T20:00:00Z",
                    end_utc="2026-09-15T02:00:00Z",
                ),
                PA,
            ),
            ApiErrorId.ERR_OUTSIDE_PHOTOGRAPHY_WINDOW.value,
            422,
        )
        validate_error(
            api.create_shoot_block(
                create_shoot_block_payload(
                    production["id"],
                    venue["id"],
                    start_utc="2026-12-14T22:00:00Z",
                    end_utc="2026-12-15T04:00:00Z",
                ),
                PA,
            ),
            ApiErrorId.ERR_OUTSIDE_PHOTOGRAPHY_WINDOW.value,
            422,
        )

        contained = validate_success(
            api.create_shoot_block(
                create_shoot_block_payload(
                    production["id"],
                    venue["id"],
                    start_utc="2026-09-15T00:00:00Z",
                    end_utc="2026-09-15T06:00:00Z",
                ),
                PA,
            ),
            201,
        )
        assert contained["status"] == "SCHEDULED"


class TestAggregateBudgetGuards:
    """Both money guards are aggregate tests measured after the derivation the
    guard is protecting, not against the raw figure the client supplied."""

    def test_the_second_protocol_crosses_the_band_floor_and_breaks_the_budget(
        self, api
    ):
        """PRD §3.7: "Step two selects the band rate from that pre-surcharge
        subtotal: four hundredths when the subtotal is below 5,000,000 cents,
        seven hundredths when it is at least 5,000,000 cents and below 20,000,000
        cents, and nine hundredths when it is 20,000,000 cents or more."
        PRD §3.7: "Step four sets `welfare_committed_cents` to the protocol
        subtotal plus that surcharge."
        PRD §3.7: "Planning or activating a protocol whose effect would push the
        recomputed `welfare_committed_cents` above `welfare_budget_cents` is
        refused with `ERR_WELFARE_BUDGET_EXCEEDED`."

        Design: Corner/validations/welfare_budget_aggregate_exceeded_by_the_second_protocol_rejected
        """
        production = _harbour_nights(welfare_budget_cents=5_000_000)

        # 4,000,000 sits below the band floor, so 0.04 at the STANDARD factor of
        # one gives a 160,000 surcharge and 4,160,000 committed.
        first = validate_success(
            api.plan_welfare_protocol(
                production["id"],
                {
                    "kind": "DUTY_OF_CARE_OFFICER",
                    "cost_cents": 4_000_000,
                    **WIDE_COVERAGE,
                },
                WO1,
            ),
            201,
        )
        assert first["status"] == "PLANNED"
        assert_money(
            get_production(production["id"])["welfare_committed_cents"],
            4_160_000,
            "committed welfare with one protocol",
        )

        # A further 1,000,000 lifts the subtotal to exactly 5,000,000, which
        # re-rates the whole subtotal at 0.07 and commits 5,350,000 — over the
        # budget even though the raw costs merely equal it. Only cost_cents
        # enters the subtotal, so the kind is immaterial to the arithmetic.
        validate_error(
            api.plan_welfare_protocol(
                production["id"],
                {
                    "kind": "ONSET_PSYCH_SUPPORT",
                    "cost_cents": 1_000_000,
                    **WIDE_COVERAGE,
                },
                WO1,
            ),
            ApiErrorId.ERR_WELFARE_BUDGET_EXCEEDED.value,
            409,
        )

        rows, meta = validate_paginated(
            api.list_welfare_protocols(production["id"], WO1)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]

        after = get_production(production["id"])
        assert_money(
            after["welfare_committed_cents"],
            4_160_000,
            "committed welfare after the refusal",
        )
        assert after["casting_posture"] == "OPEN"

    def test_send_is_guarded_by_the_provisional_figure_not_the_final_one(self, api):
        """PRD §3.6: "and finally that the production's `stipend_committed_cents`
        plus this agreement's provisional stipend figure stay within
        `stipend_pool_cents`, failing which the answer is
        `ERR_STIPEND_POOL_EXCEEDED`."
        PRD §3.6: "It uses as its episode count the larger of `episodes_committed`
        and the production's `episode_order`, on the assumption that the
        participant is retained for the full season — and because that larger
        count can cross a tier boundary, the tier multiplier itself may differ
        from the final variant's."
        PRD §3.6: "It charges the press component against
        `press_appearance_obligation_count` plus a reserve of 2 further
        appearances. It charges the reunion flat amount unconditionally, whether
        or not a reunion is actually owed. And it applies no depiction adjustment
        at all, assuming no discount."
        PRD §3.6: "The **final** variant, written to
        `total_stipend_commitment_cents` on execution and zeroed on voiding, uses
        `episodes_committed` exactly as agreed, the contracted press count without
        any reserve, the actual `reunion_obligation` flag, and it does apply the
        depiction adjustment."

        Design: Corner/validations/stipend_pool_exceeded_at_send_by_the_provisional_variant_rejected
        """
        tight = _harbour_nights(
            title="Tight Pool S1", episode_order=1, stipend_pool_cents=1_000_000
        )
        loose = _harbour_nights(
            title="Loose Pool S1", episode_order=1, stipend_pool_cents=1_200_000
        )
        tight_call = _referral_call(tight["id"])
        loose_call = _referral_call(loose["id"])
        ada = _cleared_adult(tight_call["id"], "Ada Reyes", "1994-04-02")
        ben = _cleared_adult(loose_call["id"], "Ben Okafor", "1990-01-10")

        tight_agreement = setup_drafted_agreement(
            ada["id"], tight["id"], **ONE_EPISODE_TERMS
        )
        loose_agreement = setup_drafted_agreement(
            ben["id"], loose["id"], **ONE_EPISODE_TERMS
        )

        # 900,000 base at the 1.00 tier, plus the two-appearance press reserve of
        # 50,000 and the assumed reunion of 150,000, is 1,100,000.
        validate_error(
            api.send_agreement(tight_agreement["id"], BA1),
            ApiErrorId.ERR_STIPEND_POOL_EXCEEDED.value,
            409,
        )
        assert get_agreement(tight_agreement["id"])["status"] == "DRAFTED"
        assert_money(
            get_production(tight["id"])["stipend_committed_cents"],
            0,
            "committed stipend on the tight pool",
        )

        # The identical row fits a 1,200,000 pool, and settles far lower still.
        sent = validate_success(api.send_agreement(loose_agreement["id"], BA1))
        assert_money(sent["provisional_stipend_cents"], 1_100_000, "provisional stipend")
        executed = validate_success(api.execute_agreement(loose_agreement["id"], BA2))
        assert_money(
            executed["total_stipend_commitment_cents"], 900_000, "final stipend"
        )
        assert_money(
            get_production(loose["id"])["stipend_committed_cents"],
            900_000,
            "committed stipend on the loose pool",
        )


class TestCrossEntityRollGuards:
    """The roll gate reads a third entity — the called participant's applicant —
    and only the epoch sweep makes the passage of the clock visible there."""

    def test_an_expired_medical_clearance_stops_only_the_block_that_called_her(
        self, api
    ):
        """PRD §3.4: "On success the item's `outcome` and `severity_flags` are
        written, `recorded_by_user_id` is stamped with the caller's `X-User-ID`,
        `recorded_at` is stamped with the logical clock, and `expires_at` is
        derived from the kind's validity window: a `MEDICAL_EXAM` clearance is
        valid for 30 days from `recorded_at`, a `PSYCH_EVAL` for 60 days, a
        `BACKGROUND_CHECK` for 180 days, and an `INTERVIEW` never expires, so its
        `expires_at` remains absent."
        PRD §3.7: "Every applicant whose latest `MEDICAL_EXAM` item has an
        `expires_at` at or before the logical clock moves `medical_status` from
        `CLEARED` to `EXPIRED`."
        PRD §2.6: "On shoot-block roll, no called participant's applicant has a
        `medical_status` of `EXPIRED` or `DEFERRED`, otherwise
        `ERR_MEDICAL_CLEARANCE_EXPIRED` (422)."
        PRD §3.8: "Every called participant's applicant must have `medical_status`
        `CLEARED`; a participant whose clearance has gone `EXPIRED` or has been
        left `DEFERRED` blocks the roll with `ERR_MEDICAL_CLEARANCE_EXPIRED`."

        Design: Corner/validations/roll_with_expired_medical_clearance_rejected
        """
        production = _harbour_nights()
        venue = validate_success(api.create_location(dict(PIER_NINE_STAGE), PA), 201)
        protocol = setup_active_welfare_protocol(
            production["id"],
            kind="DUTY_OF_CARE_OFFICER",
            cost_cents=1_000_000,
            **WIDE_COVERAGE,
        )
        call = _referral_call(production["id"])
        applicant = setup_applicant(
            call["id"],
            legal_name="Ada Reyes",
            date_of_birth="1994-04-02",
            residency_state_code="GA",
        )
        items = record_screening_items(applicant["id"], NO_PSYCH_SCREENING)
        medical = [item for item in items if item["kind"] == "MEDICAL_EXAM"][0]
        # Recorded at the start-up clock of 2026-08-01, 30 days out.
        assert medical["expires_at"].startswith("2026-08-31T00:00:00")

        agreement = setup_executed_agreement(
            applicant["id"], production["id"], **BASE_TERMS
        )
        called = setup_shoot_block(
            production["id"],
            venue["id"],
            start_utc="2026-10-10T08:00:00Z",
            end_utc="2026-10-10T12:00:00Z",
            participant_agreement_ids=[agreement["id"]],
        )
        empty = setup_shoot_block(
            production["id"],
            venue["id"],
            start_utc="2026-10-11T08:00:00Z",
            end_utc="2026-10-11T12:00:00Z",
        )

        set_clock("2026-10-01T00:00:00Z")
        swept = run_welfare_epoch(production["id"])
        # This deal owes no press junket and no reunion, so nothing can breach.
        assert swept["breached_obligation_count"] == 0
        assert_money(
            swept["welfare_committed_cents"], 1_040_000, "committed welfare after sweep"
        )

        after = get_applicant(applicant["id"], CO1)
        assert after["medical_status"] == "EXPIRED"
        assert after["screening_status"] == "CAST"

        # Coverage still spans the interval, so this is the participant's own
        # clearance talking rather than a duty-of-care gap.
        validate_error(
            api.roll_shoot_block(called["id"], PA),
            ApiErrorId.ERR_MEDICAL_CLEARANCE_EXPIRED.value,
            422,
        )
        assert get_shoot_block(called["id"])["status"] == "SCHEDULED"

        rolling = validate_success(api.roll_shoot_block(empty["id"], PA))
        assert rolling["status"] == "ROLLING"

        rows, _ = validate_paginated(api.list_welfare_protocols(production["id"], WO1))
        assert {row["id"]: row["status"] for row in rows}[protocol["id"]] == "ACTIVE"
        assert get_agreement(agreement["id"])["welfare_hold"] is False


class TestPostureOutranksWelfareHold:
    """When a frozen production and a held agreement are both true of the same
    send, the ladder's higher rung is the one the client hears."""

    def test_a_frozen_production_answers_before_the_agreements_own_hold_flag(
        self, api
    ):
        """PRD §2.6: "The owning production's `casting_posture` is not `FROZEN` on
        the seven posture-gated write operations — casting-call publish, applicant
        intake, agreement drafting, agreement send, agreement execution,
        shoot-block scheduling and shoot-block roll — otherwise
        `ERR_CASTING_FROZEN` (409)."
        PRD §2.6: "The addressed agreement's `welfare_hold` is false. This guards
        all four negotiation writes — send, counter-offer, revise and execute —
        and a held agreement is rejected with `ERR_WELFARE_HOLD_ACTIVE` (409)."
        PRD §2.7: "The posture is `FROZEN` when `welfare_committed_cents` is
        strictly greater than `welfare_budget_cents`, or when
        `welfare_incident_count` has reached 2 or more."
        PRD §2.7: "The moment a posture becomes `FROZEN`, the cascade is wider and
        channel-blind: every `PUBLISHED` casting call of the production moves to
        `CLOSED` with `closed_reason` set to `POSTURE_FROZEN` and its `version`
        incremented, every shoot block still in `SCHEDULED` status moves to
        `CANCELLED` with its `version` incremented, and every participant
        agreement whose `status` is `DRAFTED`, `SENT`, `COUNTERED` or `REVISED`
        has `welfare_hold` set to true."
        PRD §3.9: "Session authorisation reads the complaint's severity and the
        production's duty-of-care tier **as of the start of the routing
        transition**, that is, before any escalation performed by the very same
        request."

        Design: Corner/validations/frozen_posture_outranks_welfare_hold_on_send
        """
        production = _harbour_nights()
        call = _referral_call(production["id"])
        ada = _cleared_adult(call["id"], "Ada Reyes", "1994-04-02")
        ben = _cleared_adult(call["id"], "Ben Okafor", "1990-01-10")

        executed = setup_executed_agreement(
            ada["id"], production["id"], **BASE_TERMS
        )
        drafted = setup_drafted_agreement(ben["id"], production["id"], **BASE_TERMS)
        assert drafted["welfare_hold"] is False

        first = setup_triaged_complaint(
            executed["id"],
            ada["id"],
            category="WELFARE",
            severity=4,
            narrative="No welfare officer on the night shoot.",
        )
        second = setup_triaged_complaint(
            executed["id"],
            ada["id"],
            category="WELFARE",
            severity=4,
            narrative="Second night shoot again unsupervised.",
        )

        # Severity 4 reads 12 sessions at the STANDARD tier this request is about
        # to leave behind.
        escalated = validate_success(
            api.route_complaint(first["id"], route_payload("ESCALATION"), WO2)
        )
        assert escalated["aftercare_sessions_authorized"] == 12
        mid = get_production(production["id"])
        assert mid["casting_posture"] == "OPEN"
        assert mid["duty_of_care_tier"] == "ENHANCED"
        assert mid["welfare_incident_count"] == 1

        # The second breach reads the ENHANCED factor of one and a half, and its
        # incident takes the count to the freezing clause.
        escalated_again = validate_success(
            api.route_complaint(second["id"], route_payload("ESCALATION"), WO2)
        )
        assert escalated_again["aftercare_sessions_authorized"] == 18
        end = get_production(production["id"])
        assert end["casting_posture"] == "FROZEN"
        assert end["duty_of_care_tier"] == "CRITICAL"
        assert end["welfare_incident_count"] == 2

        held = get_agreement(drafted["id"])
        assert held["welfare_hold"] is True
        assert held["status"] == "DRAFTED"

        # Both the posture rung and the hold rung are violated; the posture rung
        # sits higher, so it is the one that answers.
        validate_error(
            api.send_agreement(drafted["id"], BA1),
            ApiErrorId.ERR_CASTING_FROZEN.value,
            409,
        )
        assert get_agreement(drafted["id"])["status"] == "DRAFTED"

        closed = validate_success(api.get_casting_call(call["id"], CD))
        assert closed["status"] == "CLOSED"
        assert closed["closed_reason"] == "POSTURE_FROZEN"
