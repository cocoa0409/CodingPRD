"""Clinical packet: singleton guards, document union, packet OCC."""
from test_helpers import (
    ApiErrorId,
    assert_clinical_packet,
    certify_screening,
    create_case,
    create_facility,
    create_notification,
    create_packet,
    create_physician,
    create_screening,
    get_packet,
    make_sending_physician_headers,
    upload_documents,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import COORD


class TestDuplicateSingletons:
    def test_duplicate_singletons_rejected(self, api):
        """PRD: "The physician whose `X-User-ID` equals the case's
        `sending_physician_id` creates the case's screening — exactly one per
        case, a second attempt drawing `ERR_DUPLICATE_SCREENING` — recording
        `has_emergency_medical_condition`, `is_stabilized`, an optional
        `benefits_outweigh_risks` defaulting to false, and an optional
        `physician_certification` narrative defaulting to empty."
        PRD: "Creating the case's clinical packet — again a singleton, a second
        attempt drawing `ERR_DUPLICATE_PACKET`, and again requiring `X-User-ID`
        to equal the case's `sending_physician_id` — takes a non-empty
        `required_documents` array drawn from `H_AND_P`, `LABS`,
        `MED_RECONCILIATION`, `CODE_STATUS`, `CONSENT`, and `TRANSFER_CERT`,
        plus an optional `imaging_studies` array of study reference and
        modality pairs the receiving facility requires."
        PRD: "A case carries at most one non-`VOIDED` notification; a second
        live attempt fails with `ERR_DUPLICATE_NOTIFICATION`, and opening one
        while the case is still in `INTAKE` or already terminal fails with
        `ERR_INVALID_STATE`."

        Design: Corner/validations/duplicate_singletons_rejected
        """
        fac = create_facility()
        phys = create_physician("Dr Send", fac["id"], "EMERGENCY")
        case = create_case(fac["id"], phys["id"], acuity_level="URGENT",
                           required_unit_type="TELEMETRY",
                           required_capability="TRAUMA", patient_ref="PT-DUP-1")
        hdrs = make_sending_physician_headers(phys["id"])
        create_screening(case["id"], phys["id"], True, True)
        create_packet(case["id"], phys["id"], ["H_AND_P"])
        certify_screening(case["id"], phys["id"])
        create_notification(case["id"])

        resp = api.create_emtala_screening(
            case["id"],
            {"has_emergency_medical_condition": False, "is_stabilized": True},
            hdrs)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SCREENING, 409)

        resp = api.create_clinical_packet(
            case["id"], {"required_documents": ["LABS"]}, hdrs)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PACKET, 409)

        resp = api.create_insurance_notification(
            case["id"], {"payer_id": "PAYER-10", "channel": "PHONE"}, COORD)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_NOTIFICATION, 409)


class TestPacketDocumentsOcc:
    def test_occ_packet_documents_stale_version_rejected(self, api):
        """PRD: "Appending documents to a clinical packet likewise requires a
        non-optional `expected_clinical_packet_version` matching the packet's
        current `version`, with the same `ERR_STALE_VERSION` (HTTP 412) on
        mismatch; each successful upload bumps the packet version, so a stale
        expectation means the client merged against an outdated document set."
        PRD: "`overall_status` is `READY` only when both are complete,
        otherwise `INCOMPLETE`."

        Design: Corner/cross_cutting_layers/occ_packet_documents_stale_version_rejected
        """
        fac = create_facility()
        phys = create_physician("Dr Send", fac["id"], "EMERGENCY")
        case = create_case(fac["id"], phys["id"], acuity_level="URGENT",
                           required_unit_type="TELEMETRY",
                           required_capability="TRAUMA", patient_ref="PT-OCC-2")
        pkt = create_packet(case["id"], phys["id"], ["H_AND_P", "LABS"])
        assert_clinical_packet(pkt)
        v1 = pkt["version"]
        hdrs = make_sending_physician_headers(phys["id"])

        first = upload_documents(pkt["id"], phys["id"], ["H_AND_P"], v1)
        assert first["version"] == v1 + 1
        assert first["document_status"] == "INCOMPLETE", "LABS still missing"

        resp = api.upload_packet_documents(
            pkt["id"],
            {"documents": ["LABS"], "expected_clinical_packet_version": v1},
            hdrs)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        unchanged = get_packet(pkt["id"])
        assert unchanged["received_documents"] == ["H_AND_P"], (
            "the 412 rejection must not merge any documents"
        )

        retried = upload_documents(pkt["id"], phys["id"], ["LABS"],
                                   first["version"])
        assert retried["document_status"] == "DOCUMENTS_COMPLETE"
        assert retried["overall_status"] == "READY"
