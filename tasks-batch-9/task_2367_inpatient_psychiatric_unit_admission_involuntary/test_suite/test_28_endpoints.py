"""What the endpoints themselves promise: a default clock, a timed consent, and paging.

Deadline arithmetic must run off the server's own logical clock even before an
operator ever moves it. An emergency override is the only consent with an expiry, and
the sweep honours it strictly. And every collection reports the filtered total.
"""

from test_helpers import (
    AcuityTier,
    COMPLIANCE_OFFICER_HEADERS,
    ConsentBasis,
    ConsentStatus,
    DeterminationStatus,
    DischargeRequestStatus,
    EvaluationStatus,
    HearingStatus,
    HoldStatus,
    HoldType,
    InterventionType,
    LegalStatus,
    MONITORING_INTERVAL_MINUTES,
    PetitionStatus,
    PlacementStatus,
    RequestedBy,
    RestraintStatus,
    STARTUP_CLOCK_UTC,
    active_hold_case,
    assert_created,
    assert_docket_minutes,
    assert_medication_consent,
    assert_ok,
    assert_page,
    assert_page_window,
    assert_sweep_counts,
    build_ward,
    certified_hold,
    complete_safety_search,
    create_admission,
    create_patient,
    create_petition,
    determine_capacity,
    face_to_face_payload,
    medication_consent_payload,
    monitoring_check_payload,
    order_restraint,
    place_admission,
    read_admission,
    read_capacity_determination,
    read_clinician,
    read_hold,
    read_medication_consent,
    read_petition,
    read_restraint,
    request_discharge,
    run_sweep,
    scheduled_hearing,
    set_clock,
    signed_evaluation,
)

STARTUP_INSTANT = "2026-08-01T00:00:00.000Z"
STARTUP_CERTIFICATION_DEADLINE = "2026-08-01T04:00:00.000Z"
STARTUP_RELEASE_DEADLINE = "2026-08-04T00:00:00.000Z"
STARTUP_FILING_DEADLINE = "2026-08-04T09:00:00.000Z"
EMERGENCY_STATUTORY_HOURS = 72

CONSENT_UNIT = "Ward 35 Consents"
NO_BEDS = ()
PRESCRIBED_AT = "2026-09-03T10:00:00Z"
OVERRIDE_EXPIRY = "2026-09-06T10:00:00.000Z"
AT_THE_EXPIRY = "2026-09-06T10:00:00Z"
ONE_MILLISECOND_LATE = "2026-09-06T10:00:00.001Z"
CONSENT_RELEASE_DEADLINE = "2026-09-06T08:00:00.000Z"
STATUTORY_EXPIRY = "STATUTORY_EXPIRY"
PATIENT_MEDICATION = "Olanzapine"
OVERRIDE_MEDICATION = "Haloperidol"
OVERRIDE_JUSTIFICATION = (
    "Acute agitation with imminent danger; no time for surrogate contact."
)

LISTING_UNIT = "Ward 36 Listing"
# Two beds, so PRD 3.1's restriction threshold — "the greater of 1 and one fifth of
# `licensed_placement_bed_count` rounded down" — leaves the unit `OPEN` and an ordinary
# placement is not refused by the `RESTRICTED` safety reserve.
LISTING_BEDS = (
    {"room_number": "551", "wing_code": "A", "bed_label": "A"},
    {"room_number": "552", "wing_code": "A", "bed_label": "A"},
)
CERTIFICATION_DEADLINE = "2026-09-03T12:00:00.000Z"
RELEASE_DEADLINE = "2026-09-06T08:00:00.000Z"
FILING_DEADLINE = "2026-09-08T09:00:00.000Z"
HEARING_START = "2026-09-04T10:00:00Z"
HEARING_START_INSTANT = "2026-09-04T10:00:00.000Z"
HEARING_END_INSTANT = "2026-09-04T10:30:00.000Z"
HEARING_MINUTES = 30
RESTRAINT_MINUTES = 30
AUTHORIZED_UNTIL = "2026-09-03T08:30:00.000Z"
PINNED_INSTANT = "2026-09-03T08:00:00.000Z"
RESPONSE_DEADLINE = "2026-09-08T14:00:00.000Z"


class TestLogicalClockStartupDefault:
    """A hold built without ever touching the clock still carries determined deadlines."""

    def test_the_startup_clock_anchors_every_hold_deadline(self, api, roster):
        """Untouched, the clock reads the startup instant, and the filing deadline rolls to Tuesday.

        PRD 2.4: "Every timestamp the server writes, and every deadline comparison it
        performs, reads a server-held **logical clock** rather than the real wall clock.
        At process startup that clock holds exactly `2026-08-01T00:00:00Z`; until an
        operator moves it, all deadline arithmetic is anchored to that default."

        PRD 3.3: "`statutory_hours` is 72 for an `EMERGENCY_72H` hold and 336 —
        fourteen days expressed in hours — for an `EXTENSION_14D` hold.
        `clock_started_at` is the statutory anchor and is emphatically *not* the hold
        row's own creation timestamp: for an `EMERGENCY_72H` hold it is the anchoring
        evaluation's `signed_at`, and for an `EXTENSION_14D` successor it is the
        predecessor hold's `release_deadline_at`. From that anchor,
        `certification_deadline_at` is the anchor plus 4 hours."

        PRD 3.3: "The first variant, `release_deadline_at`, is pure wall-clock
        arithmetic: the anchor plus `statutory_hours` hours, with no rolling of any
        kind."

        PRD 3.3: "The second variant, `petition_filing_deadline_at`, starts from that
        same raw instant and then rolls it forward onto the court calendar until it
        lands inside a judicial-day court window."

        Design: Corner/endpoints/logical_clock_startup_default_drives_every_deadline
        """
        assert STARTUP_CLOCK_UTC == "2026-08-01T00:00:00Z"
        patient = create_patient(
            api,
            mrn="MRN-2367-DF",
            legal_name="Default Clock",
            age_years=51,
            gender_care_category="MALE",
        )
        evaluation = signed_evaluation(
            api,
            roster.intake_headers,
            patient["id"],
            danger_to_self=True,
            danger_to_others=False,
            grave_disability=False,
            capacity_present=False,
        )
        assert evaluation["evaluation_started_at"] == STARTUP_INSTANT
        assert evaluation["signed_at"] == STARTUP_INSTANT
        assert evaluation["status"] == EvaluationStatus.SIGNED.value

        hold = certified_hold(api, roster, patient["id"], evaluation["id"])
        assert hold["hold_type"] == HoldType.EMERGENCY_72H.value
        assert hold["statutory_hours"] == EMERGENCY_STATUTORY_HOURS
        assert hold["clock_started_at"] == STARTUP_INSTANT
        assert hold["certification_deadline_at"] == STARTUP_CERTIFICATION_DEADLINE
        assert hold["release_deadline_at"] == STARTUP_RELEASE_DEADLINE
        assert hold["petition_filing_deadline_at"] == STARTUP_FILING_DEADLINE
        assert hold["status"] == HoldStatus.ACTIVE.value
        assert hold["certified_at"] == STARTUP_INSTANT


class TestEmergencyOverrideConsentExpiry:
    """Only the override consent carries an expiry, and the sweep compares strictly."""

    def test_the_override_survives_its_expiry_instant_and_lapses_one_millisecond_later(
        self, api, clock, roster
    ):
        """The hold expires in the earlier sweep and the consent in the later one, never together.

        PRD 3.7: "An emergency override is time-limited by design: its `expires_at` is
        set to the logical clock at creation plus 72 hours, and the compliance sweep
        moves any such consent from `ACTIVE` to `EXPIRED` once the clock has passed that
        instant. Consents on the other two bases carry a null `expires_at` and never
        expire."

        PRD 3.7: "The `capacity_determination_id` is supplied only for a surrogate basis
        and is null for the other two, and `emergency_justification` is supplied only
        for an emergency override and is null otherwise."

        PRD 3.3: "Expiry sets `closure_reason` to `STATUTORY_EXPIRY`, recomputes the
        patient's `active_hold_count` with `Patient.version` incremented by one, and
        flips every admission of that patient in `PENDING_PLACEMENT` or `PLACED` from
        `INVOLUNTARY` to `VOLUNTARY`. It carries one extra consequence the other
        closures do not: for any such admission whose `placement_status` is `PLACED`,
        the expiry also sets `rights_violation_flag` to true, because the patient
        remained physically detained after authority lapsed — and that in turn
        recomputes `open_rights_violation_count` on the owning unit."

        Design: Corner/endpoints/emergency_override_consent_expires_by_sweep_others_never_expire
        """
        ward = build_ward(
            api,
            name=CONSENT_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=0,
            bed_specs=NO_BEDS,
        )
        case = active_hold_case(
            api,
            roster,
            mrn="MRN-2367-MC",
            legal_name="Consent Case",
            age_years=58,
            gender_care_category="MALE",
        )
        assert case["hold"]["release_deadline_at"] == CONSENT_RELEASE_DEADLINE
        admission = create_admission(
            api,
            roster,
            case["patient"]["id"],
            case["evaluation"]["id"],
            ward.id,
            requested_legal_status=LegalStatus.INVOLUNTARY.value,
        )
        determine_capacity(api, roster, admission["id"], True)

        set_clock(api, PRESCRIBED_AT)
        patient_consent = assert_created(
            api.create_medication_consent(
                roster.psychiatrist_headers,
                medication_consent_payload(
                    admission_id=admission["id"],
                    medication_name=PATIENT_MEDICATION,
                    consent_basis=ConsentBasis.PATIENT_CONSENT.value,
                ),
            )
        )
        override = assert_created(
            api.create_medication_consent(
                roster.psychiatrist_headers,
                medication_consent_payload(
                    admission_id=admission["id"],
                    medication_name=OVERRIDE_MEDICATION,
                    consent_basis=ConsentBasis.EMERGENCY_OVERRIDE.value,
                    emergency_justification=OVERRIDE_JUSTIFICATION,
                ),
            )
        )
        assert_medication_consent(patient_consent)
        assert_medication_consent(override)
        assert patient_consent["status"] == ConsentStatus.ACTIVE.value
        assert patient_consent["consent_basis"] == ConsentBasis.PATIENT_CONSENT.value
        assert patient_consent["expires_at"] is None
        assert patient_consent["capacity_determination_id"] is None
        assert override["status"] == ConsentStatus.ACTIVE.value
        assert override["expires_at"] == OVERRIDE_EXPIRY
        assert override["prescribing_clinician_id"] == roster.psychiatrist["id"]

        set_clock(api, AT_THE_EXPIRY)
        first = run_sweep(api)
        assert_sweep_counts(first)
        assert first["expired_hold_count"] == 1
        assert first["expired_consent_count"] == 0

        expired_hold = read_hold(api, case["hold"]["id"])
        assert expired_hold["status"] == HoldStatus.EXPIRED.value
        assert expired_hold["closure_reason"] == STATUTORY_EXPIRY
        assert (
            read_medication_consent(api, override["id"])["status"]
            == ConsentStatus.ACTIVE.value
        )
        freed = read_admission(api, admission["id"])
        assert freed["legal_status"] == LegalStatus.VOLUNTARY.value
        assert freed["placement_status"] == PlacementStatus.PENDING_PLACEMENT.value
        assert freed["rights_violation_flag"] is False

        set_clock(api, ONE_MILLISECOND_LATE)
        second = run_sweep(api)
        assert second["expired_consent_count"] == 1
        assert second["expired_hold_count"] == 0
        assert second["expired_restraint_count"] == 0
        assert second["expired_discharge_request_count"] == 0

        assert (
            read_medication_consent(api, override["id"])["status"]
            == ConsentStatus.EXPIRED.value
        )
        survivor = read_medication_consent(api, patient_consent["id"])
        assert survivor["status"] == ConsentStatus.ACTIVE.value
        assert survivor["expires_at"] is None


class TestEveryCollectionOverOneCaseFile:
    """Nine collections, each filtered to the one row of a single case file."""

    def test_each_collection_reports_its_filtered_total_and_pages_within_it(
        self, api, clock, roster
    ):
        """The one-row filters, an off-the-end page and a filter that matches nothing.

        PRD 2.3: "Every list response reports `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope, where `total_count` is the
        size of the filtered set before pagination is applied and `has_more` indicates
        whether records remain beyond the current page."

        PRD 3.3: "From that anchor, `certification_deadline_at` is the anchor plus 4
        hours."

        PRD 3.6: "And `monitoring_interval_minutes` is 5 for a `PHYSICAL_HOLD` and 15
        for a `MECHANICAL_RESTRAINT` or a `SECLUSION` — the tighter cadence for the
        intervention where a clinician's hands are physically on the patient."

        Design: Corner/endpoints/every_collection_list_filters_and_pages_over_one_full_case_file
        """
        case = self._one_full_case_file(api, roster)
        patient_id = case["patient"]["id"]
        admission_id = case["admission"]["id"]

        evaluations, _ = assert_page(
            api.list_evaluations(
                COMPLIANCE_OFFICER_HEADERS,
                patient_id=patient_id,
                status=EvaluationStatus.SIGNED.value,
            ),
            1,
        )
        assert [row["id"] for row in evaluations] == [case["evaluation"]["id"]]

        beyond_the_end = assert_page_window(
            api.list_evaluations(
                COMPLIANCE_OFFICER_HEADERS, patient_id=patient_id, limit=1, offset=1
            ),
            limit=1,
            offset=1,
            total=1,
        )
        assert beyond_the_end == []

        holds, _ = assert_page(
            api.list_holds(
                roster.advocate_headers,
                patient_id=patient_id,
                status=HoldStatus.ACTIVE.value,
            ),
            1,
        )
        assert holds[0]["id"] == case["hold"]["id"]
        assert holds[0]["certification_deadline_at"] == CERTIFICATION_DEADLINE
        assert holds[0]["release_deadline_at"] == RELEASE_DEADLINE
        assert holds[0]["petition_filing_deadline_at"] == FILING_DEADLINE

        admissions, _ = assert_page(
            api.list_admissions(
                roster.charge_nurse_headers,
                unit_id=case["ward"].id,
                placement_status=PlacementStatus.PLACED.value,
            ),
            1,
        )
        assert admissions[0]["id"] == admission_id
        assert admissions[0]["legal_status"] == LegalStatus.INVOLUNTARY.value
        assert admissions[0]["bed_id"] == case["ward"].beds[0]["id"]
        assert admissions[0]["acuity_tier"] == AcuityTier.MODERATE.value

        petitions, _ = assert_page(
            api.list_petitions(COMPLIANCE_OFFICER_HEADERS, hold_id=case["hold"]["id"]),
            1,
        )
        assert petitions[0] == read_petition(api, case["petition"]["id"])
        assert petitions[0]["status"] == PetitionStatus.HEARING_SCHEDULED.value
        assert petitions[0]["requested_hold_type"] == HoldType.EXTENSION_14D.value

        hearings, _ = assert_page(
            api.list_hearings(
                COMPLIANCE_OFFICER_HEADERS,
                advocate_clinician_id=roster.advocate["id"],
                status=HearingStatus.SCHEDULED.value,
            ),
            1,
        )
        assert hearings[0]["id"] == case["hearing"]["id"]
        assert hearings[0]["scheduled_start_at"] == HEARING_START_INSTANT
        assert hearings[0]["scheduled_end_at"] == HEARING_END_INSTANT
        assert_docket_minutes(
            read_clinician(api, roster.advocate["id"]), HEARING_MINUTES
        )

        active_restraints, _ = assert_page(
            api.list_restraints(
                roster.charge_nurse_headers,
                admission_id=admission_id,
                status=RestraintStatus.ACTIVE.value,
            ),
            1,
        )
        assert active_restraints[0]["id"] == case["restraint"]["id"]

        empty, meta = assert_page(
            api.list_restraints(
                roster.charge_nurse_headers,
                admission_id=admission_id,
                status=RestraintStatus.RELEASED.value,
            ),
            0,
        )
        assert empty == []
        assert meta["has_more"] is False

        episode = read_restraint(api, case["restraint"]["id"])
        assert episode["status"] == RestraintStatus.ACTIVE.value
        assert (
            episode["monitoring_interval_minutes"]
            == MONITORING_INTERVAL_MINUTES[InterventionType.PHYSICAL_HOLD.value]
        )
        assert episode["authorized_until_at"] == AUTHORIZED_UNTIL
        assert episode["face_to_face_at"] == PINNED_INSTANT
        assert len(episode["monitoring_check_log"]) == 1
        entry = episode["monitoring_check_log"][0]
        assert entry["check_type"] == "CIRCULATION"
        assert entry["recorded_at"] == PINNED_INSTANT
        assert entry["recorded_by_clinician_id"] == roster.charge_nurse["id"]

        determinations, _ = assert_page(
            api.list_capacity_determinations(
                roster.psychiatrist_headers,
                admission_id=admission_id,
                status=DeterminationStatus.ACTIVE.value,
            ),
            1,
        )
        determination = read_capacity_determination(api, case["determination"]["id"])
        assert determinations[0] == determination
        assert determination["capacity_present"] is True
        assert determination["surrogate_name"] is None
        assert determination["surrogate_relationship"] is None
        assert determination["surrogate_authority_scope"] is None

        consents, _ = assert_page(
            api.list_medication_consents(
                roster.psychiatrist_headers,
                admission_id=admission_id,
                status=ConsentStatus.ACTIVE.value,
            ),
            1,
        )
        assert consents[0]["id"] == case["consent"]["id"]
        assert consents[0]["consent_basis"] == ConsentBasis.PATIENT_CONSENT.value
        assert consents[0]["prescribing_clinician_id"] == roster.psychiatrist["id"]
        assert consents[0]["capacity_determination_id"] is None
        assert consents[0]["expires_at"] is None

        requests, _ = assert_page(
            api.list_discharge_requests(
                roster.advocate_headers,
                admission_id=admission_id,
                status=DischargeRequestStatus.PENDING.value,
            ),
            1,
        )
        assert requests[0]["id"] == case["request"]["id"]
        assert requests[0]["requested_by"] == RequestedBy.PATIENT.value
        assert requests[0]["response_deadline_at"] == RESPONSE_DEADLINE

    @staticmethod
    def _one_full_case_file(api, roster):
        """One patient carrying a row in every collection the API exposes."""
        ward = build_ward(
            api,
            name=LISTING_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=1,
            bed_specs=LISTING_BEDS,
        )
        case = active_hold_case(
            api,
            roster,
            mrn="MRN-2367-LS",
            legal_name="Listing Case",
            age_years=49,
            gender_care_category="MALE",
        )
        case["ward"] = ward
        case["admission"] = create_admission(
            api,
            roster,
            case["patient"]["id"],
            case["evaluation"]["id"],
            ward.id,
            requested_legal_status=LegalStatus.INVOLUNTARY.value,
        )
        complete_safety_search(api, roster, case["admission"]["id"])
        place_admission(api, roster, case["admission"]["id"], ward.id)
        case["petition"] = create_petition(
            api, roster.psychiatrist_headers, case["hold"]["id"]
        )
        case["hearing"] = scheduled_hearing(
            api,
            roster.advocate_headers,
            case["petition"]["id"],
            roster.advocate["id"],
            HEARING_START,
            HEARING_MINUTES,
        )
        case["determination"] = determine_capacity(
            api, roster, case["admission"]["id"], True
        )
        case["consent"] = assert_created(
            api.create_medication_consent(
                roster.psychiatrist_headers,
                medication_consent_payload(
                    admission_id=case["admission"]["id"],
                    medication_name=PATIENT_MEDICATION,
                    consent_basis=ConsentBasis.PATIENT_CONSENT.value,
                ),
            )
        )
        ordered = order_restraint(
            api,
            roster,
            case["admission"]["id"],
            InterventionType.PHYSICAL_HOLD.value,
            RESTRAINT_MINUTES,
        )
        assert_ok(
            api.record_face_to_face(
                roster.psychiatrist_headers, ordered["id"], face_to_face_payload()
            )
        )
        assert_ok(
            api.add_monitoring_check(
                roster.charge_nurse_headers,
                ordered["id"],
                monitoring_check_payload(check_type="CIRCULATION"),
            )
        )
        case["restraint"] = ordered
        case["request"] = request_discharge(api, roster, case["admission"]["id"])
        return case
