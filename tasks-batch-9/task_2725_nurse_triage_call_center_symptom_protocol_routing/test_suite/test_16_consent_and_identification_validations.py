"""The two consent safety gates and the identification match gates."""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instant, assert_version_is


@pytest.fixture
def three_identified_calls_by_age(world):
    """Charts aged 14, one-day-short-of-18 and exactly-18 against the clock."""
    world.set_clock("2026-08-03T14:30:00Z")
    world.create_practice(consent_recording_required=False)
    ages = {
        "child": ("Milo Reyes", "2012-05-01", "MALE", "+14155550110", "MRN-0010"),
        "almost_adult": ("Ivy Reyes", "2008-08-04", "FEMALE", "+14155550111", "MRN-0011"),
        "exactly_adult": ("Owen Reyes", "2008-08-03", "MALE", "+14155550112", "MRN-0012"),
    }
    calls = {}
    for key, (name, dob, sex, phone, mrn) in ages.items():
        patient = world.create_patient(
            key, full_name=name, dob=dob, sex=sex, phone=phone, mrn=mrn
        )
        call = world.open_call(
            caller_name=name if key != "child" else "Milo's Mother",
            caller_phone=phone,
            caller_relationship="PARENT_GUARDIAN" if key == "child" else "SELF",
            reason_text="child with a fever" if key == "child" else "sore throat",
        )
        world.match_patient(call["id"], patient["id"])
        calls[key] = call
    return calls


class TestMinorConsentRequiresAGuardian:
    def test_a_fourteen_year_old_cannot_consent_for_themselves(
        self, world, three_identified_calls_by_age
    ):
        """PRD §3.3: "If the matched patient is under eighteen years old — measured as
        the full years elapsed from the patient's `dob` to the calendar date of the
        logical clock — then a `consent_type` of `PATIENT_SELF` is refused with
        `ERR_MINOR_REQUIRES_GUARDIAN_CONSENT`; a minor's consent must come from a
        guardian or a healthcare proxy."

        Design: Corner/validations/minor_consent_requires_a_guardian_and_succeeds_once_supplied
        """
        call = three_identified_calls_by_age["child"]

        response = world.api.record_consent(
            call["id"],
            f.consent_payload(consent_type="PATIENT_SELF", consent_given_by="Milo Reyes"),
            world.intake,
        )

        validate_error(response, ApiErrorId.ERR_MINOR_REQUIRES_GUARDIAN_CONSENT, 422)

    def test_a_caller_whose_eighteenth_birthday_is_tomorrow_is_still_a_minor(
        self, world, three_identified_calls_by_age
    ):
        """PRD §3.3: "measured as the full years elapsed from the patient's `dob` to
        the calendar date of the logical clock".

        Design: Corner/validations/minor_consent_requires_a_guardian_and_succeeds_once_supplied
        """
        call = three_identified_calls_by_age["almost_adult"]

        response = world.api.record_consent(
            call["id"],
            f.consent_payload(consent_type="PATIENT_SELF", consent_given_by="Ivy Reyes"),
            world.intake,
        )

        validate_error(response, ApiErrorId.ERR_MINOR_REQUIRES_GUARDIAN_CONSENT, 422)
        refused = world.call(call["id"])
        assert refused["status"] == "IDENTIFIED"
        assert refused["consent_type"] is None

    def test_guardian_consent_carries_the_minors_call_through(
        self, world, three_identified_calls_by_age
    ):
        """PRD §3.3: "On success the call records `consent_type`, `consent_given_by`
        and `recording_reference`, stamps `consent_recorded_at` with the current
        logical-clock instant, moves to `CONSENTED`, and increases `version` by one."

        Design: Corner/validations/minor_consent_requires_a_guardian_and_succeeds_once_supplied
        """
        call = three_identified_calls_by_age["child"]
        world.api.record_consent(
            call["id"],
            f.consent_payload(consent_type="PATIENT_SELF", consent_given_by="Milo Reyes"),
            world.intake,
        )

        consented = world.record_consent(
            call["id"], consent_type="GUARDIAN", consent_given_by="Rosa Reyes"
        )

        assert consented["status"] == "CONSENTED"
        assert consented["consent_type"] == "GUARDIAN"
        assert consented["consent_given_by"] == "Rosa Reyes"

    def test_the_eighteenth_birthday_itself_is_already_adult(
        self, world, three_identified_calls_by_age
    ):
        """PRD §3.3: "then a `consent_type` of `PATIENT_SELF` is refused with
        `ERR_MINOR_REQUIRES_GUARDIAN_CONSENT`" — which, being keyed on "under
        eighteen", leaves a patient of exactly eighteen full years free to consent.

        Design: Corner/validations/minor_consent_requires_a_guardian_and_succeeds_once_supplied
        """
        call = three_identified_calls_by_age["exactly_adult"]

        consented = world.record_consent(
            call["id"], consent_type="PATIENT_SELF", consent_given_by="Owen Reyes"
        )

        assert consented["status"] == "CONSENTED"
        assert consented["consent_type"] == "PATIENT_SELF"


@pytest.fixture
def two_practices_with_opposite_recording_policies(world):
    """One IDENTIFIED adult call under a lax practice and under a strict one."""
    world.set_clock("2026-08-03T14:30:00Z")
    lax = get_success_data(
        world.api.create_practice(
            f.practice_payload(
                name="No Recording Needed Clinic", consent_recording_required=False
            ),
            world.admin,
        )
    )
    strict = get_success_data(
        world.api.create_practice(
            f.practice_payload(
                name="Recording Mandatory Clinic", consent_recording_required=True
            ),
            world.admin,
        )
    )
    lax_patient = world.create_patient("lax", lax["id"])
    strict_patient = world.create_patient(
        "strict",
        strict["id"],
        full_name="Harold Pike",
        dob="1948-09-10",
        sex="MALE",
        phone="+14155550200",
        mrn="MRN-0002",
    )
    lax_call = world.open_call(lax["id"], reason_text="sore throat")
    world.match_patient(lax_call["id"], lax_patient["id"])
    strict_call = world.open_call(
        strict["id"],
        caller_name="Harold Pike",
        caller_phone="+14155550200",
        reason_text="sore throat",
    )
    world.match_patient(strict_call["id"], strict_patient["id"])
    return lax_call, strict_call


class TestRecordingReferenceIsConditionalOnThePractice:
    def test_the_lax_practice_accepts_consent_with_no_recording_locator(
        self, world, two_practices_with_opposite_recording_policies
    ):
        """PRD §3.3: "`recording_reference` is supplied when a voice-recording locator
        is required."

        Design: Corner/validations/recording_reference_is_required_only_when_the_practice_demands_it
        """
        lax_call, _ = two_practices_with_opposite_recording_policies

        consented = world.record_consent(
            lax_call["id"], consent_type="PATIENT_SELF", consent_given_by="Dana Reyes"
        )

        assert consented["status"] == "CONSENTED"
        assert consented["recording_reference"] is None

    def test_the_identical_payload_is_refused_by_the_strict_practice(
        self, world, two_practices_with_opposite_recording_policies
    ):
        """PRD §3.3: "If the practice sets `consent_recording_required` to true, then a
        `recording_reference` that is absent or empty is refused with
        `ERR_CONSENT_RECORDING_REQUIRED`."

        Design: Corner/validations/recording_reference_is_required_only_when_the_practice_demands_it
        """
        _, strict_call = two_practices_with_opposite_recording_policies

        response = world.api.record_consent(
            strict_call["id"],
            f.consent_payload(
                consent_type="PATIENT_SELF", consent_given_by="Harold Pike"
            ),
            world.intake,
        )

        validate_error(response, ApiErrorId.ERR_CONSENT_RECORDING_REQUIRED, 422)
        assert world.call(strict_call["id"])["status"] == "IDENTIFIED"

    def test_supplying_the_locator_satisfies_the_strict_practice(
        self, world, two_practices_with_opposite_recording_policies
    ):
        """PRD §3.3: "stamps `consent_recorded_at` with the current logical-clock
        instant, moves to `CONSENTED`, and increases `version` by one."

        Design: Corner/validations/recording_reference_is_required_only_when_the_practice_demands_it
        """
        _, strict_call = two_practices_with_opposite_recording_policies
        world.api.record_consent(
            strict_call["id"],
            f.consent_payload(
                consent_type="PATIENT_SELF", consent_given_by="Harold Pike"
            ),
            world.intake,
        )

        consented = world.record_consent(
            strict_call["id"],
            consent_type="PATIENT_SELF",
            consent_given_by="Harold Pike",
            recording_reference="REC-2026-08-03-0001",
        )

        assert consented["status"] == "CONSENTED"
        assert consented["recording_reference"] == "REC-2026-08-03-0001"
        assert_instant(
            consented["consent_recorded_at"],
            "2026-08-03T14:30:00Z",
            "consent_recorded_at",
        )


@pytest.fixture
def two_panels_holding_the_same_person(world):
    """The same person on two panels, with one INTAKE call under the first."""
    world.set_clock("2026-08-03T14:30:00Z")
    practice_a = get_success_data(
        world.api.create_practice(
            f.practice_payload(name="Northside Family Health"), world.admin
        )
    )
    practice_b = get_success_data(
        world.api.create_practice(
            f.practice_payload(
                name="Southside Pediatrics", per_minute_rate_millicents=3000
            ),
            world.admin,
        )
    )
    patient_a = world.create_patient("panel_a", practice_a["id"])
    patient_b = world.create_patient("panel_b", practice_b["id"], mrn="MRN-0099")
    call = world.open_call(practice_a["id"], reason_text="sore throat")
    return call, patient_a, patient_b


class TestPatientMatchGates:
    def test_another_practices_chart_is_a_practice_mismatch(
        self, world, two_panels_holding_the_same_person
    ):
        """PRD §3.3: "and the patient must belong to the same practice as the call, or
        the answer is `ERR_PATIENT_PRACTICE_MISMATCH` — a call may only ever be matched
        to a patient of the practice it was opened for."

        Design: Corner/validations/patient_match_requires_mrn_or_eighty_percent_confidence_and_the_right_practice
        """
        call, _, patient_b = two_panels_holding_the_same_person

        response = world.api.match_patient(
            call["id"], f.match_patient_payload(patient_b["id"]), world.intake
        )

        validate_error(response, ApiErrorId.ERR_PATIENT_PRACTICE_MISMATCH, 409)
        assert world.call(call["id"])["status"] == "INTAKE"

    def test_seventy_nine_percent_confidence_is_below_the_bar(
        self, world, two_panels_holding_the_same_person
    ):
        """PRD §3.3: "A record-number match is trusted outright; any other method must
        carry a confidence of at least 80, and a lower one is refused with
        `ERR_MATCH_CONFIDENCE_TOO_LOW`."

        Design: Corner/validations/patient_match_requires_mrn_or_eighty_percent_confidence_and_the_right_practice
        """
        call, patient_a, _ = two_panels_holding_the_same_person

        response = world.api.match_patient(
            call["id"],
            f.match_patient_payload(
                patient_a["id"], match_method="PHONE_AND_NAME", match_confidence_pct=79
            ),
            world.intake,
        )

        validate_error(response, ApiErrorId.ERR_MATCH_CONFIDENCE_TOO_LOW, 422)

    def test_exactly_eighty_percent_is_accepted_and_binds_the_chart(
        self, world, two_panels_holding_the_same_person
    ):
        """PRD §3.3: "On success the call's `patient_id`, `match_method` and
        `match_confidence_pct` are set, `status` becomes `IDENTIFIED`, and the call's
        `version` increases by one with `updated_at` refreshed."

        Design: Corner/validations/patient_match_requires_mrn_or_eighty_percent_confidence_and_the_right_practice
        """
        call, patient_a, patient_b = two_panels_holding_the_same_person
        world.api.match_patient(
            call["id"], f.match_patient_payload(patient_b["id"]), world.intake
        )
        world.api.match_patient(
            call["id"],
            f.match_patient_payload(
                patient_a["id"], match_method="PHONE_AND_NAME", match_confidence_pct=79
            ),
            world.intake,
        )

        identified = world.match_patient(
            call["id"],
            patient_a["id"],
            match_method="PHONE_AND_NAME",
            match_confidence_pct=80,
        )

        assert identified["status"] == "IDENTIFIED"
        assert identified["match_confidence_pct"] == 80
        assert identified["match_method"] == "PHONE_AND_NAME"
        assert identified["patient_id"] == patient_a["id"]
        assert_version_is(identified, 2, "two refusals wrote nothing")
