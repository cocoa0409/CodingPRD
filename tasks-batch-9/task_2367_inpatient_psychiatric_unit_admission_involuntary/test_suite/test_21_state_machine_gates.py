"""Declared initial states, and the guards that refuse an out-of-order transition.

Every row starts where its state machine says it starts, and no creating call can
short-circuit that. Signing, certifying, initiating a hold and opening an
involuntary admission each read a state that belongs to a different row.
"""

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER_HEADERS,
    DischargePlanStatus,
    DischargeRequestStatus,
    EvaluationStatus,
    GenderMixingPolicy,
    HoldStatus,
    InterventionType,
    LegalStatus,
    MONITORING_INTERVAL_MINUTES,
    PlacementStatus,
    RecommendedStatus,
    RestraintStatus,
    SafetySearchStatus,
    AcuityTier,
    BedStatus,
    assert_created,
    assert_error,
    assert_ok,
    assert_page,
    build_ward,
    certification_payload,
    complete_safety_search,
    create_admission,
    create_evaluation,
    create_hold,
    create_patient,
    create_unit,
    hold_payload,
    place_admission,
    read_bed,
    read_evaluation,
    read_hold,
    read_patient,
    request_discharge,
    set_clock,
    signed_evaluation,
    voluntary_case,
)

INITIAL_UNIT = "Ward 16 Initial"
DRAFT_UNIT = "Ward 17 Draft"
CRITERIA_UNIT = "Ward 18 Criteria"
HOLD_GATE_UNIT = "Ward 19 Hold Gate"

# Two beds, so PRD 3.1's restriction threshold — "the greater of 1 and one fifth of
# `licensed_placement_bed_count` rounded down" — leaves the unit `OPEN` and an ordinary
# placement is not refused by the safety reserve.
ONE_BED = (
    {"room_number": "451", "wing_code": "A", "bed_label": "A"},
    {"room_number": "452", "wing_code": "A", "bed_label": "A"},
)

PINNED_INSTANT = "2026-09-03T08:00:00.000Z"
CERTIFICATION_DEADLINE = "2026-09-03T12:00:00.000Z"
AT_THE_DEADLINE = "2026-09-03T12:00:00Z"
ONE_MILLISECOND_LATE = "2026-09-03T12:00:00.001Z"
FOUR_HOURS_ON = "2026-09-03T12:00:00Z"

PHYSICAL_HOLD_MINUTES = 20


def _pending_certification_hold(api, roster, *, mrn, legal_name, age_years=36):
    """A signed involuntary evaluation and a hold left in PENDING_CERTIFICATION."""
    patient = create_patient(
        api,
        mrn=mrn,
        legal_name=legal_name,
        age_years=age_years,
        gender_care_category="MALE",
    )
    evaluation = signed_evaluation(api, roster.intake_headers, patient["id"])
    hold = create_hold(
        api, roster.intake_headers, patient["id"], evaluation["id"]
    )
    return {"patient": patient, "evaluation": evaluation, "hold": hold}


class TestDeclaredInitialStates:
    """Five machines, five declared entry states, none of them client-selectable."""

    def test_the_evaluation_hold_and_admission_all_start_where_declared(
        self, api, clock, roster
    ):
        """DRAFT, PENDING_CERTIFICATION and PENDING_PLACEMENT come out of the creating calls.

        PRD 3.2: "The server stamps `evaluating_clinician_id` from the header and
        `evaluation_started_at` from the logical clock, and the evaluation's `status`
        begins at `DRAFT`."

        PRD 3.3: "The server records `initiated_by_clinician_id` from the header,
        leaves `certifying_clinician_id`, `certified_at` and `closure_reason` null,
        leaves `predecessor_hold_id` null because an emergency hold has no
        predecessor, and sets `status` to `PENDING_CERTIFICATION`."

        Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_states
        """
        ward = build_ward(
            api,
            name=INITIAL_UNIT,
            gender_mixing_policy=GenderMixingPolicy.MIXED_ALLOWED.value,
            seclusion_room_count=0,
            bed_specs=ONE_BED,
        )
        patient = create_patient(
            api,
            mrn="MRN-2367-IS",
            legal_name="Ines Solberg",
            age_years=38,
            gender_care_category="MALE",
        )

        draft = create_evaluation(api, roster.intake_headers, patient["id"])
        assert draft["status"] == EvaluationStatus.DRAFT.value
        assert draft["signed_at"] is None

        signed = assert_ok(api.sign_evaluation(roster.intake_headers, draft["id"]))
        assert signed["status"] == EvaluationStatus.SIGNED.value
        assert signed["signed_at"] == PINNED_INSTANT

        hold = create_hold(api, roster.intake_headers, patient["id"], draft["id"])
        assert hold["status"] == HoldStatus.PENDING_CERTIFICATION.value
        assert hold["certified_at"] is None
        assert hold["closure_reason"] is None
        assert hold["predecessor_hold_id"] is None

        admission = create_admission(
            api,
            roster,
            patient["id"],
            draft["id"],
            ward.id,
            LegalStatus.VOLUNTARY.value,
        )
        assert admission["placement_status"] == PlacementStatus.PENDING_PLACEMENT.value
        assert admission["legal_status"] == LegalStatus.VOLUNTARY.value
        assert admission["acuity_tier"] == AcuityTier.MODERATE.value
        assert admission["safety_search_status"] == SafetySearchStatus.PENDING.value
        assert admission["discharge_plan_status"] == DischargePlanStatus.NOT_STARTED.value

    def test_the_restraint_episode_and_the_discharge_request_start_where_declared(
        self, api, clock, roster
    ):
        """An ordered episode and a fresh request both open with nothing recorded on them.

        PRD 3.6: "On creation the server stamps `started_at` from the logical clock,
        records `ordered_by_clinician_id` from the header, sets `status` to
        `ORDERED`, and computes three derived values."

        PRD 3.8: "A `ChargeNurse` or a `PatientRightsAdvocate` records the request
        against an `admission_id` with a `requested_by` value of `PATIENT` or
        `GUARDIAN`; the server stamps `requested_at` from the logical clock and
        `recorded_by_clinician_id` from the header, sets both `decision` and `status`
        to `PENDING`, and leaves `responding_clinician_id` and `response_note` null."

        Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_states
        """
        ward = build_ward(
            api,
            name=INITIAL_UNIT,
            gender_mixing_policy=GenderMixingPolicy.MIXED_ALLOWED.value,
            seclusion_room_count=0,
            bed_specs=ONE_BED,
        )
        case = voluntary_case(
            api,
            roster,
            mrn="MRN-2367-IS",
            legal_name="Ines Solberg",
            age_years=38,
            gender_care_category="MALE",
        )
        admission = create_admission(
            api,
            roster,
            case["patient"]["id"],
            case["evaluation"]["id"],
            ward.id,
            LegalStatus.VOLUNTARY.value,
        )
        complete_safety_search(api, roster, admission["id"])
        placed = place_admission(
            api, roster, admission["id"], ward.id, bed_id=ward.beds[0]["id"]
        )
        assert placed["placement_status"] == PlacementStatus.PLACED.value
        assert (
            read_bed(api, ward.beds[0]["id"], ward.id)["status"]
            == BedStatus.OCCUPIED.value
        )

        episode = assert_created(
            api.create_restraint(
                roster.psychiatrist_headers,
                admission_id=admission["id"],
                intervention_type=InterventionType.PHYSICAL_HOLD.value,
                ordered_duration_minutes=PHYSICAL_HOLD_MINUTES,
                clinical_justification="Imminent self-harm; verbal de-escalation failed.",
            )
        )
        assert episode["status"] == RestraintStatus.ORDERED.value
        assert episode["started_at"] == PINNED_INSTANT
        assert episode["face_to_face_at"] is None
        assert episode["released_at"] is None
        assert episode["monitoring_check_log"] == []
        assert (
            episode["monitoring_interval_minutes"]
            == MONITORING_INTERVAL_MINUTES[InterventionType.PHYSICAL_HOLD.value]
        )

        pending_request = request_discharge(api, roster, admission["id"])
        assert pending_request["status"] == DischargeRequestStatus.PENDING.value
        assert pending_request["decision"] == "PENDING"
        assert pending_request["responding_clinician_id"] is None
        assert pending_request["response_note"] is None


class TestEvaluationSigningIsTerminal:
    """The signature is the statutory anchor, so it cannot be re-stamped later."""

    def test_a_second_signature_is_refused_and_does_not_move_the_anchor(
        self, api, clock, roster
    ):
        """Four hours later the same evaluation still reports the original signed_at.

        PRD 3.2: "Signing moves the evaluation `DRAFT → SIGNED`, which is terminal
        for this entity; a second attempt fails with
        `ERR_EVALUATION_ALREADY_SIGNED`. Signature stamps `signed_at` from the
        logical clock and freezes the record: `acuity_score`, `acuity_tier`,
        `prior_admission_count_30d` and `recommended_status` keep exactly the values
        computed at creation and are never recomputed at signature, however much the
        world has moved in between."

        Design: Corner/state_machines/evaluation_sign_twice_rejected_as_already_signed
        """
        patient = create_patient(
            api,
            mrn="MRN-2367-SG",
            legal_name="Signe Grunwald",
            age_years=44,
            gender_care_category="FEMALE",
        )
        signed = signed_evaluation(api, roster.intake_headers, patient["id"])
        assert signed["signed_at"] == PINNED_INSTANT

        set_clock(api, FOUR_HOURS_ON)
        refusal = api.sign_evaluation(roster.intake_headers, signed["id"])

        assert_error(refusal, ApiErrorId.EVALUATION_ALREADY_SIGNED)
        unchanged = read_evaluation(api, signed["id"])
        assert unchanged["status"] == EvaluationStatus.SIGNED.value
        assert unchanged["signed_at"] == PINNED_INSTANT
        assert unchanged["version"] == signed["version"]


class TestDraftEvaluationBlocksBothConsumers:
    """Nothing downstream may be built on an evaluation with no anchor instant."""

    def test_a_draft_evaluation_supports_neither_a_hold_nor_an_admission(
        self, api, clock, roster
    ):
        """Both consumers refuse the same unsigned row and neither writes anything.

        PRD 3.2: "`signed_at` is the statutory anchor every emergency hold clock is
        measured from, which is why nothing downstream may be built on a `DRAFT`
        evaluation — hold initiation and admission creation both reject one with
        `ERR_EVALUATION_NOT_SIGNED`."

        Design: Corner/state_machines/hold_and_admission_from_draft_evaluation_rejected
        """
        ward = build_ward(
            api,
            name=DRAFT_UNIT,
            gender_mixing_policy=GenderMixingPolicy.MIXED_ALLOWED.value,
            seclusion_room_count=0,
            bed_specs=({"room_number": "461", "wing_code": "A", "bed_label": "A"},),
        )
        patient = create_patient(
            api,
            mrn="MRN-2367-DE",
            legal_name="Dmitri Egerton",
            age_years=31,
            gender_care_category="MALE",
        )
        draft = create_evaluation(api, roster.intake_headers, patient["id"])

        hold_refusal = api.create_hold(
            roster.intake_headers,
            hold_payload(patient_id=patient["id"], evaluation_id=draft["id"]),
        )
        admission_refusal = api.create_admission(
            roster.intake_headers,
            patient_id=patient["id"],
            evaluation_id=draft["id"],
            unit_id=ward.id,
            requested_legal_status=LegalStatus.VOLUNTARY.value,
        )

        assert_error(hold_refusal, ApiErrorId.EVALUATION_NOT_SIGNED)
        assert_error(admission_refusal, ApiErrorId.EVALUATION_NOT_SIGNED)

        still_draft = read_evaluation(api, draft["id"])
        assert still_draft["status"] == EvaluationStatus.DRAFT.value
        assert still_draft["signed_at"] is None
        assert_page(
            api.list_holds(COMPLIANCE_OFFICER_HEADERS, patient_id=patient["id"]), 0
        )
        assert_page(
            api.list_admissions(COMPLIANCE_OFFICER_HEADERS, patient_id=patient["id"]), 0
        )


class TestHoldCertificationGuards:
    """Certification is guarded twice: by who is asking, and by where the hold is."""

    def test_the_initiator_may_not_certify_their_own_hold(self, api, clock, roster):
        """The refused self-certification leaves the hold pending and uncredited.

        PRD 3.3: "Certification is the act that converts an initiated hold into
        detention authority, and it is restricted to an `AttendingPsychiatrist` other
        than the initiator. A certification arriving from the initiating clinician is
        refused with `ERR_SEGREGATION_OF_DUTIES`; one arriving when the hold is not
        in `PENDING_CERTIFICATION` is refused with
        `ERR_HOLD_NOT_PENDING_CERTIFICATION`; and one arriving after
        `certification_deadline_at` — that is, when the clock is strictly past it —
        is refused with `ERR_CERTIFICATION_WINDOW_CLOSED`, while an arrival exactly
        at the deadline is accepted."

        Design: Corner/state_machines/hold_certification_twice_rejected_and_by_initiator_rejected
        """
        patient = create_patient(
            api,
            mrn="MRN-2367-CT",
            legal_name="Cato Trevelyan",
            age_years=27,
            gender_care_category="NONBINARY",
        )
        evaluation = signed_evaluation(api, roster.psychiatrist_headers, patient["id"])
        hold = create_hold(
            api, roster.psychiatrist_headers, patient["id"], evaluation["id"]
        )
        assert hold["initiated_by_clinician_id"] == roster.psychiatrist["id"]
        assert hold["certification_deadline_at"] == CERTIFICATION_DEADLINE

        refusal = api.certify_hold(
            roster.psychiatrist_headers, hold["id"], certification_payload()
        )

        assert_error(refusal, ApiErrorId.SEGREGATION_OF_DUTIES)
        untouched = read_hold(api, hold["id"])
        assert untouched["status"] == HoldStatus.PENDING_CERTIFICATION.value
        assert untouched["certifying_clinician_id"] is None
        assert read_patient(api, patient["id"])["active_hold_count"] == 0

    def test_a_second_certification_is_refused_and_does_not_double_count(
        self, api, clock, roster
    ):
        """Once ACTIVE the hold leaves PENDING_CERTIFICATION for good.

        PRD 3.3: "A successful certification carries a `certification_note`, moves
        the hold `PENDING_CERTIFICATION → ACTIVE`, stamps `certified_at` and
        `certifying_clinician_id`, recomputes the patient's `active_hold_count`
        upward by one and increments `Patient.version` by one, and then reaches
        across into the admission aggregate: every admission of that patient whose
        `placement_status` is `PENDING_PLACEMENT` or `PLACED` has its `legal_status`
        set to `INVOLUNTARY` and its own `version` incremented by one."

        Design: Corner/state_machines/hold_certification_twice_rejected_and_by_initiator_rejected
        """
        patient = create_patient(
            api,
            mrn="MRN-2367-CT",
            legal_name="Cato Trevelyan",
            age_years=27,
            gender_care_category="NONBINARY",
        )
        evaluation = signed_evaluation(api, roster.psychiatrist_headers, patient["id"])
        hold = create_hold(
            api, roster.psychiatrist_headers, patient["id"], evaluation["id"]
        )

        certified = assert_ok(
            api.certify_hold(
                roster.second_psychiatrist_headers, hold["id"], certification_payload()
            )
        )
        assert certified["status"] == HoldStatus.ACTIVE.value
        assert (
            certified["certifying_clinician_id"] == roster.second_psychiatrist["id"]
        )
        assert certified["certified_at"] == PINNED_INSTANT
        assert read_patient(api, patient["id"])["active_hold_count"] == 1

        duplicate = api.certify_hold(
            roster.second_psychiatrist_headers, hold["id"], certification_payload()
        )

        assert_error(duplicate, ApiErrorId.HOLD_NOT_PENDING_CERTIFICATION)
        assert (
            read_hold(api, hold["id"])["certifying_clinician_id"]
            == roster.second_psychiatrist["id"]
        )
        assert read_patient(api, patient["id"])["active_hold_count"] == 1


class TestCertificationWindowBoundary:
    """The four-hour window is inclusive to the millisecond on two twin holds."""

    def test_certification_at_the_deadline_is_accepted_and_one_millisecond_later_is_not(
        self, api, clock, roster
    ):
        """Two holds with identical deadlines diverge on a single millisecond.

        PRD 3.3: "From that anchor, `certification_deadline_at` is the anchor plus 4
        hours."

        PRD 3.3: "A certification arriving from the initiating clinician is refused
        with `ERR_SEGREGATION_OF_DUTIES`; one arriving when the hold is not in
        `PENDING_CERTIFICATION` is refused with `ERR_HOLD_NOT_PENDING_CERTIFICATION`;
        and one arriving after `certification_deadline_at` — that is, when the clock
        is strictly past it — is refused with `ERR_CERTIFICATION_WINDOW_CLOSED`,
        while an arrival exactly at the deadline is accepted."

        Design: Corner/state_machines/hold_certification_after_deadline_rejected
        """
        on_time = _pending_certification_hold(
            api, roster, mrn="MRN-2367-W3", legal_name="Wren Thackeray"
        )
        late = _pending_certification_hold(
            api, roster, mrn="MRN-2367-W4", legal_name="Wynne Fairholm", age_years=39
        )
        assert on_time["hold"]["certification_deadline_at"] == CERTIFICATION_DEADLINE
        assert late["hold"]["certification_deadline_at"] == CERTIFICATION_DEADLINE

        set_clock(api, AT_THE_DEADLINE)
        accepted = assert_ok(
            api.certify_hold(
                roster.psychiatrist_headers,
                on_time["hold"]["id"],
                certification_payload(),
            )
        )
        assert accepted["status"] == HoldStatus.ACTIVE.value
        assert accepted["certified_at"] == CERTIFICATION_DEADLINE

        set_clock(api, ONE_MILLISECOND_LATE)
        refusal = api.certify_hold(
            roster.psychiatrist_headers, late["hold"]["id"], certification_payload()
        )

        assert_error(refusal, ApiErrorId.CERTIFICATION_WINDOW_CLOSED)
        missed = read_hold(api, late["hold"]["id"])
        assert missed["status"] == HoldStatus.PENDING_CERTIFICATION.value
        assert missed["certified_at"] is None
        assert read_patient(api, late["patient"]["id"])["active_hold_count"] == 0


class TestHoldInitiationRequiresInvoluntaryRecommendation:
    """A voluntary recommendation supports an admission but never a detention."""

    def test_an_evaluation_recommending_voluntary_care_cannot_anchor_a_hold(
        self, api, clock, roster
    ):
        """The same signed evaluation is refused for a hold and accepted for an admission.

        PRD 3.3: "Initiation is permitted only when the anchoring evaluation's
        `recommended_status` is exactly `INVOLUNTARY_HOLD`; a `VOLUNTARY` or
        `NO_ADMISSION` recommendation is refused with
        `ERR_CLINICAL_CRITERIA_NOT_MET`."

        PRD 3.5: "The anchoring evaluation must be `SIGNED`, and its
        `recommended_status` must be either `VOLUNTARY` or `INVOLUNTARY_HOLD`; a
        `NO_ADMISSION` recommendation is refused with
        `ERR_CLINICAL_CRITERIA_NOT_MET`."

        Design: Corner/state_machines/hold_initiation_from_voluntary_recommendation_rejected
        """
        unit = create_unit(
            api, CRITERIA_UNIT, GenderMixingPolicy.MIXED_ALLOWED.value, 0
        )
        case = voluntary_case(
            api,
            roster,
            mrn="MRN-2367-CC",
            legal_name="Calla Corvino",
            age_years=48,
            gender_care_category="FEMALE",
            danger_to_self=False,
            danger_to_others=True,
            grave_disability=True,
        )
        assert case["evaluation"]["acuity_score"] == 8
        assert case["evaluation"]["acuity_tier"] == AcuityTier.MODERATE.value
        assert (
            case["evaluation"]["recommended_status"] == RecommendedStatus.VOLUNTARY.value
        )

        refusal = api.create_hold(
            roster.intake_headers,
            hold_payload(
                patient_id=case["patient"]["id"],
                evaluation_id=case["evaluation"]["id"],
            ),
        )
        assert_error(refusal, ApiErrorId.CLINICAL_CRITERIA_NOT_MET)
        assert_page(
            api.list_holds(
                COMPLIANCE_OFFICER_HEADERS, patient_id=case["patient"]["id"]
            ),
            0,
        )

        admission = create_admission(
            api,
            roster,
            case["patient"]["id"],
            case["evaluation"]["id"],
            unit["id"],
            LegalStatus.VOLUNTARY.value,
        )
        assert admission["legal_status"] == LegalStatus.VOLUNTARY.value
        assert admission["acuity_tier"] == AcuityTier.MODERATE.value


class TestInvoluntaryAdmissionRequiresActiveHold:
    """An initiated hold is not yet detention authority, so the admission must wait."""

    def test_the_involuntary_admission_is_refused_until_the_hold_is_certified(
        self, api, clock, roster
    ):
        """The identical request succeeds the moment the hold reaches ACTIVE.

        PRD 3.5: "Requesting `INVOLUNTARY` requires that the patient already has at
        least one hold in `ACTIVE`; without one the request is refused with
        `ERR_NO_ACTIVE_HOLD`."

        Design: Corner/state_machines/involuntary_admission_without_active_hold_rejected
        """
        unit = create_unit(
            api, HOLD_GATE_UNIT, GenderMixingPolicy.MIXED_ALLOWED.value, 0
        )
        case = _pending_certification_hold(
            api, roster, mrn="MRN-2367-NH", legal_name="Niall Hargreave", age_years=30
        )

        refusal = api.create_admission(
            roster.intake_headers,
            patient_id=case["patient"]["id"],
            evaluation_id=case["evaluation"]["id"],
            unit_id=unit["id"],
            requested_legal_status=LegalStatus.INVOLUNTARY.value,
        )
        assert_error(refusal, ApiErrorId.NO_ACTIVE_HOLD)
        assert_page(
            api.list_admissions(
                COMPLIANCE_OFFICER_HEADERS, patient_id=case["patient"]["id"]
            ),
            0,
        )

        assert_ok(
            api.certify_hold(
                roster.psychiatrist_headers, case["hold"]["id"], certification_payload()
            )
        )
        assert read_hold(api, case["hold"]["id"])["status"] == HoldStatus.ACTIVE.value
        assert read_patient(api, case["patient"]["id"])["active_hold_count"] == 1

        admission = create_admission(
            api,
            roster,
            case["patient"]["id"],
            case["evaluation"]["id"],
            unit["id"],
            LegalStatus.INVOLUNTARY.value,
        )
        assert admission["legal_status"] == LegalStatus.INVOLUNTARY.value
        assert admission["placement_status"] == PlacementStatus.PENDING_PLACEMENT.value
