"""EMTALA screening lifecycle: draft, certify, amend, re-certify loop."""
from test_helpers import (
    ApiErrorId,
    assert_emtala_screening,
    amend_screening,
    certify_screening,
    create_case,
    create_facility,
    create_physician,
    create_screening,
    get_case,
    get_screening,
    make_sending_physician_headers,
    drive_to_awaiting,
    setup_certified_case,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import COORD


class TestScreeningCreate:
    def test_screening_create_initial_draft_and_determination(self, api):
        """PRD: "The screening's `determination` is computed, not chosen:
        `EMTALA_NOT_APPLIES` when there is no emergency medical condition,
        `EMTALA_APPLIES` when one exists and the patient is stabilized, and
        `EMERGENCY_EXCEPTION` when one exists and the patient is not
        stabilized."
        PRD: "The screening is born in `DRAFT`."

        Design: Corner/state_machines/screening_create_initial_draft_and_determination
        """
        fac = create_facility()
        phys = create_physician("Dr Send", fac["id"], "EMERGENCY")
        case = create_case(fac["id"], phys["id"], acuity_level="STABLE",
                           required_unit_type="MED_SURG",
                           required_capability="TRAUMA", patient_ref="PT-DRAFT-1")
        resp = api.create_emtala_screening(
            case["id"],
            {"has_emergency_medical_condition": False, "is_stabilized": True},
            make_sending_physician_headers(phys["id"]),
        )
        screening = validate_success(resp, 201)
        assert_emtala_screening(screening)
        assert screening["status"] == "DRAFT"
        assert screening["amendment_count"] == 0
        assert screening["certified_at"] is None
        assert screening["determination"] == "EMTALA_NOT_APPLIES"

        case_after = get_case(case["id"])
        assert case_after["status"] == "INTAKE"
        assert case_after["emtala_obligation"] == "UNDETERMINED"


class TestCertify:
    def test_certify_twice_and_certify_without_screening_rejected(self, api):
        """PRD: "Certifying requires the case in `INTAKE`, the screening present
        (certifying before creation fails with `ERR_SCREENING_NOT_FOUND`), the
        screening in `DRAFT` or `AMENDED`, and the caller to be the case's
        sending physician (`ERR_NOT_CASE_PHYSICIAN`)."

        Design: Corner/state_machines/certify_twice_and_certify_without_screening_rejected
        """
        fac = create_facility()
        phys = create_physician("Dr Send", fac["id"], "EMERGENCY")
        case1 = create_case(fac["id"], phys["id"], acuity_level="EMERGENT",
                            required_unit_type="ICU", required_capability="TRAUMA",
                            patient_ref="PT-CERT-1")
        create_screening(case1["id"], phys["id"], True, True)
        certify_screening(case1["id"], phys["id"])
        case2 = create_case(fac["id"], phys["id"], acuity_level="STABLE",
                            required_unit_type="MED_SURG",
                            required_capability="TRAUMA", patient_ref="PT-CERT-2")

        # Second certify: screening already CERTIFIED -> state failure.
        resp = api.certify_emtala_screening(
            case1["id"], make_sending_physician_headers(phys["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        # Certify with no screening row at all -> existence failure.
        resp = api.certify_emtala_screening(
            case2["id"], make_sending_physician_headers(phys["id"]))
        validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_FOUND, 404)

    def test_screening_certify_by_non_case_physician_rejected(self, api):
        """PRD: "Certifying requires the case in `INTAKE`, the screening present
        (certifying before creation fails with `ERR_SCREENING_NOT_FOUND`), the
        screening in `DRAFT` or `AMENDED`, and the caller to be the case's
        sending physician (`ERR_NOT_CASE_PHYSICIAN`)."
        PRD: "When `X-User-Role` is `SendingPhysician` or `ReceivingPhysician`,
        `X-User-ID` is the `id` of the acting `Physician`; ownership checks on a
        transfer case compare the case's `sending_physician_id` or
        `receiving_physician_id` respectively to `X-User-ID`, and a mismatch is
        rejected with `ERR_NOT_CASE_PHYSICIAN`."

        Design: Corner/validations/screening_certify_by_non_case_physician_rejected
        """
        fac = create_facility()
        phys_s = create_physician("Dr Send", fac["id"], "EMERGENCY")
        phys_o = create_physician("Dr Other", fac["id"], "SURGERY")
        case = create_case(fac["id"], phys_s["id"], acuity_level="EMERGENT",
                           required_unit_type="ICU", required_capability="TRAUMA",
                           patient_ref="PT-ID-1")
        create_screening(case["id"], phys_s["id"], True, True)

        resp = api.certify_emtala_screening(
            case["id"], make_sending_physician_headers(phys_o["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_CASE_PHYSICIAN, 403)

        screening = get_screening(case["id"])[0]
        assert screening["status"] == "DRAFT"
        assert get_case(case["id"])["status"] == "INTAKE"


class TestCertificationInsufficient:
    def test_certification_insufficient_rejected(self, api):
        """PRD: "When the determination would be `EMERGENCY_EXCEPTION`, two
        further conditions must hold: `benefits_outweigh_risks` must be true and
        `physician_certification` must run to at least 30 characters; otherwise
        certification is refused with `ERR_CERTIFICATION_INSUFFICIENT`."

        Design: Corner/validations/certification_insufficient_rejected
        """
        fac = create_facility()
        phys = create_physician("Dr Send", fac["id"], "EMERGENCY")
        # Case A: unstable EMC with a certification narrative under 30 chars.
        case_a = create_case(fac["id"], phys["id"], acuity_level="CRITICAL",
                             required_unit_type="ICU", required_capability="TRAUMA",
                             patient_ref="PT-CERT-A")
        create_screening(case_a["id"], phys["id"], True, False,
                         benefits_outweigh_risks=True,
                         physician_certification="too short")
        # Case B: unstable EMC, long narrative, but benefits attestation false.
        case_b = create_case(fac["id"], phys["id"], acuity_level="CRITICAL",
                             required_unit_type="ICU", required_capability="TRAUMA",
                             patient_ref="PT-CERT-B")
        create_screening(
            case_b["id"], phys["id"], True, False,
            benefits_outweigh_risks=False,
            physician_certification="Long enough narrative but the benefits "
                                    "attestation is explicitly false.")

        resp = api.certify_emtala_screening(
            case_a["id"], make_sending_physician_headers(phys["id"]))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_INSUFFICIENT, 422)
        resp = api.certify_emtala_screening(
            case_b["id"], make_sending_physician_headers(phys["id"]))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_INSUFFICIENT, 422)

        assert get_screening(case_a["id"])[0]["status"] == "DRAFT"
        assert get_screening(case_b["id"])[0]["status"] == "DRAFT"
        assert get_case(case_a["id"])["status"] == "INTAKE"
        assert get_case(case_a["id"])["emtala_obligation"] == "UNDETERMINED"
        assert get_case(case_b["id"])["status"] == "INTAKE"


class TestAmend:
    def test_screening_amend_after_case_advances_locked(self, api):
        """PRD: "Amendment is only possible while the case sits in
        `EMTALA_DETERMINED`: once the case has advanced past it, the screening
        is locked and amending draws `ERR_SCREENING_LOCKED`, while amending a
        case back in `INTAKE` — or a screening not currently `CERTIFIED` —
        draws `ERR_INVALID_STATE`."

        Design: Corner/state_machines/screening_amend_after_case_advances_locked
        """
        ws = setup_certified_case(acuity="EMERGENT", unit="ICU",
                                  patient_ref="PT-LOCK-1")
        drive_to_awaiting(ws)
        case_id = ws["case"]["id"]

        resp = api.amend_emtala_screening(
            case_id, {"is_stabilized": False},
            make_sending_physician_headers(ws["phys_s"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SCREENING_LOCKED, 409)

        screening = get_screening(case_id)[0]
        assert screening["status"] == "CERTIFIED"
        assert screening["amendment_count"] == 0


class TestAmendRecertifyLoop:
    def test_amend_reverts_case_to_intake(self, api):
        """PRD: "Amending applies new values for any of
        `has_emergency_medical_condition`, `is_stabilized`,
        `benefits_outweigh_risks`, or `physician_certification`, flips the
        screening `CERTIFIED → AMENDED`, increments its `amendment_count`,
        reverts the case `EMTALA_DETERMINED → INTAKE`, resets `emtala_obligation`
        to `UNDETERMINED`, clears `emtala_determined_at` to null, and bumps the
        case version."

        Design: Difficulty/non_linear_state_machine/screening_certify_amend_recertify_loop
        """
        ws = setup_certified_case(acuity="EMERGENT", unit="ICU",
                                  required_capability="TRAUMA",
                                  patient_ref="PT-SCR-1")
        case_id = ws["case"]["id"]
        amended = amend_screening(
            case_id, ws["phys_s"]["id"], is_stabilized=False,
            benefits_outweigh_risks=True,
            physician_certification="Patient requires emergent cath lab; "
                                    "benefits of transfer outweigh transport risks.")
        assert amended["status"] == "AMENDED"
        assert amended["amendment_count"] == 1

        mid = get_case(case_id)
        assert mid["status"] == "INTAKE"
        assert mid["emtala_obligation"] == "UNDETERMINED"
        assert mid["emtala_determined_at"] is None

    def test_recertify_after_amend_flips_determination(self, api):
        """PRD: "Re-certification after amendment simply replays the `INTAKE →
        EMTALA_DETERMINED` path with the amended values."
        PRD: "The screening's `determination` is computed, not chosen:
        `EMTALA_NOT_APPLIES` when there is no emergency medical condition,
        `EMTALA_APPLIES` when one exists and the patient is stabilized, and
        `EMERGENCY_EXCEPTION` when one exists and the patient is not
        stabilized."

        Design: Difficulty/non_linear_state_machine/screening_certify_amend_recertify_loop
        """
        ws = setup_certified_case(acuity="EMERGENT", unit="ICU",
                                  required_capability="TRAUMA",
                                  patient_ref="PT-SCR-2")
        case_id = ws["case"]["id"]
        amend_screening(
            case_id, ws["phys_s"]["id"], is_stabilized=False,
            benefits_outweigh_risks=True,
            physician_certification="Patient requires emergent cath lab; "
                                    "benefits of transfer outweigh transport risks.")

        recertified = certify_screening(case_id, ws["phys_s"]["id"])
        assert recertified["status"] == "CERTIFIED"
        assert recertified["amendment_count"] == 1
        assert recertified["determination"] == "EMERGENCY_EXCEPTION"

        end = get_case(case_id)
        assert end["status"] == "EMTALA_DETERMINED"
        assert end["emtala_obligation"] == "EMERGENCY_EXCEPTION"
        assert end["emtala_determined_at"] is not None


class TestScreeningSingletonInvariant:
    def test_amend_recertify_keeps_single_screening_row(self, api):
        """PRD: "The physician whose `X-User-ID` equals the case's
        `sending_physician_id` creates the case's screening — exactly one per
        case, a second attempt drawing `ERR_DUPLICATE_SCREENING` — recording
        `has_emergency_medical_condition`, `is_stabilized`, an optional
        `benefits_outweigh_risks` defaulting to false, and an optional
        `physician_certification` narrative defaulting to empty."

        Design: Difficulty/compensating_invariant/screening_amendment_singleton_invariant
        """
        ws = setup_certified_case(acuity="EMERGENT", unit="ICU",
                                  required_capability="TRAUMA",
                                  patient_ref="PT-SINGLE-1")
        case_id = ws["case"]["id"]
        original_id = ws["screening"]["id"]

        amend_screening(case_id, ws["phys_s"]["id"],
                        physician_certification="Amended certification: repeat "
                                                "evaluation confirms stable EMC.")
        certify_screening(case_id, ws["phys_s"]["id"])

        rows = get_screening(case_id)
        assert len(rows) == 1, "the certify/amend/certify loop must conserve cardinality"
        assert rows[0]["id"] == original_id, "amendment revises in place"

    def test_amend_recertify_records_amendment_count_and_status(self, api):
        """PRD: "Amending applies new values for any of
        `has_emergency_medical_condition`, `is_stabilized`,
        `benefits_outweigh_risks`, or `physician_certification`, flips the
        screening `CERTIFIED → AMENDED`, increments its `amendment_count`,
        reverts the case `EMTALA_DETERMINED → INTAKE`, resets `emtala_obligation`
        to `UNDETERMINED`, clears `emtala_determined_at` to null, and bumps the
        case version."
        PRD: "Re-certification after amendment simply replays the `INTAKE →
        EMTALA_DETERMINED` path with the amended values."

        Design: Difficulty/compensating_invariant/screening_amendment_singleton_invariant
        """
        ws = setup_certified_case(acuity="EMERGENT", unit="ICU",
                                  required_capability="TRAUMA",
                                  patient_ref="PT-SINGLE-2")
        case_id = ws["case"]["id"]

        amend_screening(case_id, ws["phys_s"]["id"],
                        physician_certification="Amended certification: repeat "
                                                "evaluation confirms stable EMC.")
        recertified = certify_screening(case_id, ws["phys_s"]["id"])
        assert recertified["status"] == "CERTIFIED"
        assert recertified["amendment_count"] == 1
        assert recertified["determination"] == "EMTALA_APPLIES", (
            "amended values here do not change the stable-EMC determination"
        )
        assert get_case(case_id)["status"] == "EMTALA_DETERMINED"
