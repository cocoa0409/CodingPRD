"""Family reunification desk: match guards and their pipeline order, reunification
side effects, and the close-out path."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_family_inquiry,
    create_incident,
    create_inquiry,
    create_matched_inquiry,
    create_patient,
    create_transferred_patient,
    setup_incident_with_activated_site,
    validate_error,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
PC = TEST_USERS["planning_chief_headers"]
PIO = TEST_USERS["public_information_officer_headers"]


class TestMatchRequiresTracked:
    def test_match_discharged_record_rejected(self, api):
        """PRD §3.8: "Matching an `OPEN` inquiry to a patient record — by naming
        `patient_record_id` — runs five guards: the record must exist
        (`ERR_NOT_FOUND`); it must belong to the same incident as the inquiry
        (`ERR_CROSS_INCIDENT_REFERENCE`); its `patient_ref` must equal the
        inquiry's `sought_patient_ref` (`ERR_PATIENT_REF_MISMATCH`); it must still
        be `TRACKED` (`ERR_PATIENT_NOT_TRACKED`); and it must not already be
        referenced by another inquiry in `MATCHED` status
        (`ERR_PATIENT_ALREADY_MATCHED`)."

        Design: Difficulty/cross_entity_state_dependency/inquiry_match_requires_record_tracked
        """
        incident = create_incident(incident_name="MCI-match", incident_type="HUMAN")
        record = create_patient(incident["id"], "P-7", triage_category="DELAYED")
        validate_success(api.discharge_patient(record["id"], PC))
        inquiry = create_inquiry(incident["id"], "P-7", inquirer_name="Robin",
                                 inquirer_phone="555-0101")

        resp = api.match_family_inquiry(inquiry["id"], {"patient_record_id": record["id"]}, PIO)
        validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_TRACKED)
        reread = validate_success(api.get_family_inquiry(inquiry["id"], PIO))
        assert reread["status"] == "OPEN"

    def test_match_transferred_record_rejected(self, api):
        """PRD §3.8: "it must still be `TRACKED` (`ERR_PATIENT_NOT_TRACKED`)".
        PRD §3.7: "Transfer moves a `TRACKED` patient to an alternate care site by
        naming `site_id`".

        Design: Difficulty/cross_entity_state_dependency/inquiry_match_requires_record_tracked
        """
        incident, site = setup_incident_with_activated_site(
            bed_capacity=10, incident_overrides={"incident_name": "MCI-match2"}
        )
        record = create_transferred_patient(incident["id"], site["id"], "P-8",
                                            triage_category="DELAYED")
        assert record["status"] == "TRANSFERRED"
        inquiry = create_inquiry(incident["id"], "P-8")

        resp = api.match_family_inquiry(inquiry["id"], {"patient_record_id": record["id"]}, PIO)
        validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_TRACKED)


class TestCrossIncidentPriority:
    def _two_wave_setup(self, api, sought_ref):
        """Wave-1 incident with patient P-1 (discharged, then incident
        demobilized); Wave-2 incident ACTIVATED with an inquiry seeking
        `sought_ref`. Returns (record, inquiry)."""
        wave1 = create_incident(incident_name="Wave-1")
        record = create_patient(wave1["id"], "P-1", triage_category="DELAYED")
        validate_success(api.discharge_patient(record["id"], PC))
        validate_success(api.demobilize_incident(wave1["id"], IC))
        wave2 = create_incident(incident_name="Wave-2",
                                declared_at="2026-08-01T01:00:00Z")
        inquiry = create_inquiry(wave2["id"], sought_ref, inquirer_name="Jamie")
        return record, inquiry

    def test_match_cross_incident_beats_ref_mismatch(self, api):
        """PRD §2.11: "When several validations apply to one request, the server
        evaluates them in a fixed order, and the first failure determines the
        response."
        PRD §2.11: "11. Cross-incident consistency between the referenced
        resources: `ERR_CROSS_INCIDENT_REFERENCE`."
        PRD §2.11: "13. Uniqueness, aggregate, and qualification constraints — the
        long tail from `ERR_BADGE_NUMBER_EXISTS` through `ERR_PATIENTS_STILL_ON_SITE`
        catalogued in §5, each named in §3 beside the workflow that enforces it."

        Design: Difficulty/priority_pair_validation_conflict/match_cross_incident_referential_beats_ref_mismatch_constraint
        """
        record, inquiry = self._two_wave_setup(api, sought_ref="P-999")
        # Cross-incident, ref-mismatch, and not-TRACKED all fail at once; the
        # referential failure outranks the constraint failures.
        resp = api.match_family_inquiry(inquiry["id"], {"patient_record_id": record["id"]}, PIO)
        validate_error(resp, ApiErrorId.ERR_CROSS_INCIDENT_REFERENCE)

    def test_match_cross_incident_beats_not_tracked(self, api):
        """PRD §2.11: "11. Cross-incident consistency between the referenced
        resources: `ERR_CROSS_INCIDENT_REFERENCE`."
        PRD §2.11: "13. Uniqueness, aggregate, and qualification constraints — the
        long tail from `ERR_BADGE_NUMBER_EXISTS` through `ERR_PATIENTS_STILL_ON_SITE`
        catalogued in §5, each named in §3 beside the workflow that enforces it."

        Design: Difficulty/priority_pair_validation_conflict/match_cross_incident_referential_beats_ref_mismatch_constraint
        """
        record, inquiry = self._two_wave_setup(api, sought_ref="P-1")
        # The reference matches here, so only cross-incident and not-TRACKED fail;
        # cross-incident still wins.
        resp = api.match_family_inquiry(inquiry["id"], {"patient_record_id": record["id"]}, PIO)
        validate_error(resp, ApiErrorId.ERR_CROSS_INCIDENT_REFERENCE)


class TestMatchConstraints:
    def test_patient_already_matched_rejected(self, api):
        """PRD §3.8: "it must not already be referenced by another inquiry in
        `MATCHED` status (`ERR_PATIENT_ALREADY_MATCHED`)".

        Design: Corner/validations/patient_already_matched_rejected
        """
        incident = create_incident(incident_name="MCI-double-match",
                                   incident_type="HUMAN")
        record = create_patient(incident["id"], "P-1", triage_category="DELAYED")
        q1 = create_inquiry(incident["id"], "P-1", inquirer_name="A",
                            inquirer_phone="555-0103")
        q2 = create_inquiry(incident["id"], "P-1", inquirer_name="B",
                            inquirer_phone="555-0104")
        validate_success(
            api.match_family_inquiry(q1["id"], {"patient_record_id": record["id"]}, PIO)
        )

        resp = api.match_family_inquiry(q2["id"], {"patient_record_id": record["id"]}, PIO)
        validate_error(resp, ApiErrorId.ERR_PATIENT_ALREADY_MATCHED)
        reread = validate_success(api.get_family_inquiry(q2["id"], PIO))
        assert reread["status"] == "OPEN"

    def test_patient_ref_mismatch_rejected(self, api):
        """PRD §3.8: "its `patient_ref` must equal the inquiry's
        `sought_patient_ref` (`ERR_PATIENT_REF_MISMATCH`)".

        Design: Corner/validations/patient_ref_mismatch_rejected
        """
        incident = create_incident(incident_name="MCI-mismatch", incident_type="HUMAN")
        record = create_patient(incident["id"], "P-1", triage_category="DELAYED")
        inquiry = create_inquiry(incident["id"], "P-9", inquirer_name="C",
                                 inquirer_phone="555-0105")

        resp = api.match_family_inquiry(inquiry["id"], {"patient_record_id": record["id"]}, PIO)
        validate_error(resp, ApiErrorId.ERR_PATIENT_REF_MISMATCH)


class TestReunification:
    def test_inquiry_reunite_marks_patient_reunified(self, api):
        """PRD §3.8: "Reunification moves a `MATCHED` inquiry to `REUNITED`, stamps
        `reunited_at`, and flips the matched patient record's `reunified` flag to
        true — the record's only path to that value."

        Design: Corner/state_machines/inquiry_reunite_marks_patient_reunified
        """
        incident = create_incident(incident_name="MCI-reun", incident_type="HUMAN")
        matched, patient = create_matched_inquiry(incident["id"], "P-3",
                                                  triage_category="DELAYED")
        assert matched["status"] == "MATCHED"

        reunited = validate_success(api.reunite_family_inquiry(matched["id"], PIO))
        assert_family_inquiry(reunited)
        assert reunited["status"] == "REUNITED"
        assert reunited["reunited_at"] is not None

        record = validate_success(api.get_patient_record(patient["id"], PIO))
        assert record["reunified"] is True
