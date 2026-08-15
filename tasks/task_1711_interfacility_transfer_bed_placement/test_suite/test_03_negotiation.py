"""Negotiation: request-acceptance, refusal records, risk scoring, re-request loop."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_physician_communication,
    assert_refusal_record,
    certify_screening,
    create_case,
    create_facility,
    create_physician,
    create_screening,
    drive_to_awaiting,
    find_review_for_case,
    get_case,
    get_screening,
    list_communications,
    list_refusal_records,
    refuse_case,
    re_request,
    request_acceptance,
    setup_certified_case,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANY, COORD


class TestRequestAcceptance:
    def test_request_acceptance_creates_pending_communication(self, api):
        """PRD: "A valid request opens a negotiation round: a
        `PhysicianCommunication` is created in `PENDING` with
        `from_physician_id` set to the case's sending physician,
        `to_physician_id` to the addressed receiving physician, `round` set to
        the case's `negotiation_round` plus one, and the `contact_method` and
        `notes` recorded; the case stores the receiving references, increments
        `negotiation_round`, bumps its version, and moves `EMTALA_DETERMINED →
        AWAITING_ACCEPTANCE`."

        Design: Corner/state_machines/request_acceptance_creates_pending_communication
        """
        ws = setup_certified_case(acuity="EMERGENT", unit="ICU",
                                  rcv_beds=(), patient_ref="PT-COMM-1")
        case = request_acceptance(
            ws["case"]["id"], ws["fac_r"]["id"], ws["phys_r"]["id"],
            contact_method="SECURE_MESSAGE", notes="Cath lab activation likely.")
        assert case["status"] == "AWAITING_ACCEPTANCE"
        assert case["negotiation_round"] == 1
        assert case["receiving_facility_id"] == ws["fac_r"]["id"]
        assert case["receiving_physician_id"] == ws["phys_r"]["id"]

        comms = list_communications(transfer_case_id=ws["case"]["id"])
        assert len(comms) == 1
        comm = comms[0]
        assert_physician_communication(comm)
        assert comm["outcome"] == "PENDING"
        assert comm["round"] == 1
        assert comm["from_physician_id"] == ws["phys_s"]["id"]
        assert comm["to_physician_id"] == ws["phys_r"]["id"]
        assert comm["responded_at"] is None

    def test_same_facility_transfer_rejected(self, api):
        """PRD: "then cross-referential rules fire — the receiving facility must
        differ from the sending facility (`ERR_SAME_FACILITY_TRANSFER`) and the
        named physician's home facility must be the receiving facility
        (`ERR_PHYSICIAN_FACILITY_MISMATCH`)."

        Design: Corner/validations/same_facility_transfer_rejected
        """
        fac_s = create_facility()
        phys_s = create_physician("Dr Send", fac_s["id"], "EMERGENCY")
        phys_a = create_physician("Dr Alt", fac_s["id"], "SURGERY")
        case = create_case(fac_s["id"], phys_s["id"], acuity_level="URGENT",
                           required_unit_type="TELEMETRY",
                           required_capability="TRAUMA", patient_ref="PT-SAME-1")
        create_screening(case["id"], phys_s["id"], True, True)
        certify_screening(case["id"], phys_s["id"])

        resp = api.request_acceptance(
            case["id"],
            {"receiving_facility_id": fac_s["id"],
             "receiving_physician_id": phys_a["id"], "contact_method": "PHONE"},
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_SAME_FACILITY_TRANSFER, 400)
        after = get_case(case["id"])
        assert after["status"] == "EMTALA_DETERMINED"
        assert after["negotiation_round"] == 0

    def test_receiving_physician_link_errors_rejected(self, api):
        """PRD: "The checks run in the ladder order of §2.8: both identifiers
        must exist; the receiving facility must list the case's
        `required_capability` among its capabilities, failing with
        `ERR_CAPABILITY_MISMATCH`; then cross-referential rules fire — the
        receiving facility must differ from the sending facility
        (`ERR_SAME_FACILITY_TRANSFER`) and the named physician's home facility
        must be the receiving facility (`ERR_PHYSICIAN_FACILITY_MISMATCH`)."

        Design: Corner/validations/receiving_physician_link_errors_rejected
        """
        fac_s = create_facility()
        fac_r = create_facility(name="Receiving Trauma Center", facility_code="RCV",
                                trauma_level="LEVEL_1", capabilities=["CARDIAC_CATH"])
        fac_o = create_facility(name="Other Hospital", facility_code="OTH",
                                trauma_level="COMMUNITY",
                                capabilities=["CARDIAC_CATH"])
        phys_s = create_physician("Dr Send", fac_s["id"], "EMERGENCY")
        phys_o = create_physician("Dr Elsewhere", fac_o["id"], "CARDIOLOGY")
        case = create_case(fac_s["id"], phys_s["id"], acuity_level="URGENT",
                           required_unit_type="TELEMETRY",
                           required_capability="CARDIAC_CATH",
                           patient_ref="PT-LINK-1")
        create_screening(case["id"], phys_s["id"], True, True)
        certify_screening(case["id"], phys_s["id"])

        resp = api.request_acceptance(
            case["id"],
            {"receiving_facility_id": fac_r["id"],
             "receiving_physician_id": NON_EXISTENT_UUID,
             "contact_method": "PHONE"},
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_PHYSICIAN_NOT_FOUND, 404)

        resp = api.request_acceptance(
            case["id"],
            {"receiving_facility_id": fac_r["id"],
             "receiving_physician_id": phys_o["id"], "contact_method": "PHONE"},
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_PHYSICIAN_FACILITY_MISMATCH, 422)

        after = get_case(case["id"])
        assert after["status"] == "EMTALA_DETERMINED"
        assert after["negotiation_round"] == 0

    def test_capability_mismatch_rejected(self, api):
        """PRD: "The checks run in the ladder order of §2.8: both identifiers
        must exist; the receiving facility must list the case's
        `required_capability` among its capabilities, failing with
        `ERR_CAPABILITY_MISMATCH`; then cross-referential rules fire — the
        receiving facility must differ from the sending facility
        (`ERR_SAME_FACILITY_TRANSFER`) and the named physician's home facility
        must be the receiving facility (`ERR_PHYSICIAN_FACILITY_MISMATCH`)."

        Design: Corner/validations/capability_mismatch_rejected
        """
        ws = setup_certified_case(acuity="CRITICAL", unit="BURN",
                                  required_capability="BURN",
                                  rcv_capabilities=["TRAUMA"], rcv_beds=(),
                                  patient_ref="PT-CAP-1")
        resp = api.request_acceptance(
            ws["case"]["id"],
            {"receiving_facility_id": ws["fac_r"]["id"],
             "receiving_physician_id": ws["phys_r"]["id"],
             "contact_method": "PHONE"},
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_CAPABILITY_MISMATCH, 422)
        assert list_communications(transfer_case_id=ws["case"]["id"]) == []


class TestRefusal:
    def test_refuse_narrative_too_short_rejected(self, api):
        """PRD: "The receiving physician — `X-User-ID` equal to the case's
        `receiving_physician_id` — refuses by supplying a `refusal_category` of
        `NO_BED_AVAILABLE`, `CAPABILITY_UNAVAILABLE`, `DIVERSION_ACTIVE`,
        `UNSTABLE_FOR_TRANSFER`, or `CAPACITY_EXCEEDED`, plus a `narrative` of
        at least 50 characters (`ERR_NARRATIVE_TOO_SHORT`)."

        Design: Corner/validations/refuse_narrative_too_short_rejected
        """
        ws = setup_certified_case(acuity="URGENT", unit="TELEMETRY",
                                  rcv_beds=(), patient_ref="PT-NAR-1")
        drive_to_awaiting(ws)
        from test_helpers import make_receiving_physician_headers
        resp = api.refuse_case(
            ws["case"]["id"],
            {"refusal_category": "NO_BED_AVAILABLE",
             "narrative": "no beds right now"},
            make_receiving_physician_headers(ws["phys_r"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NARRATIVE_TOO_SHORT, 400)
        after = get_case(ws["case"]["id"])
        assert after["status"] == "AWAITING_ACCEPTANCE"
        assert after["refusal_count"] == 0
        assert list_refusal_records(transfer_case_id=ws["case"]["id"]) == []

    def test_refusal_record_immutable_no_version(self, api):
        """PRD: "Three resources are append-only records and carry a reduced
        envelope: a `PhysicianCommunication`, a `RefusalRecord`, and a
        `TransferOutcome` each have only `id` and `created_at` — both
        `updated_at` and `version` are absent from them."

        Design: Corner/entities/refusal_record_immutable_no_version
        """
        ws = setup_certified_case(acuity="STABLE", unit="MED_SURG", emc=False,
                                  rcv_beds=(), patient_ref="PT-IMM-1")
        drive_to_awaiting(ws)
        refuse_case(ws["case"]["id"], ws["phys_r"]["id"],
                    refusal_category="CAPABILITY_UNAVAILABLE",
                    narrative="Requested neuro-interventional capability is not "
                              "available at this facility.")
        records = list_refusal_records(transfer_case_id=ws["case"]["id"])
        assert len(records) == 1
        resp = api.get_refusal_record(records[0]["id"], ANY)
        record = validate_success(resp)
        assert_refusal_record(record)
        assert "version" not in record and "updated_at" not in record

    def test_refusal_risk_flag_scoring_boundaries(self, api):
        """PRD: "The `emtala_risk_score` starts from a category base — 30 for
        `NO_BED_AVAILABLE`, 25 for `CAPABILITY_UNAVAILABLE`, 40 for
        `DIVERSION_ACTIVE`, 10 for `UNSTABLE_FOR_TRANSFER`, 20 for
        `CAPACITY_EXCEEDED` — adds an obligation increment of 50 when the case
        is `EMTALA_APPLIES`, 20 under `EMERGENCY_EXCEPTION`, and 0 under
        `EMTALA_NOT_APPLIES` or `UNDETERMINED`, then adds 10 points per prior
        refusal of the same case, counting at most three priors."
        PRD: "The `emtala_risk_flag` bands the score: `HIGH` at 70 or more —
        exactly 70 is `HIGH` — `ELEVATED` from 40 up to but not including 70,
        and `LOW` below 40."

        Design: Corner/calculations/refusal_risk_flag_scoring_boundaries
        """
        fac_s = create_facility()
        fac_r1 = create_facility(name="Receiving One", facility_code="RCV1",
                                 trauma_level="LEVEL_1",
                                 capabilities=["CARDIAC_CATH"])
        fac_r2 = create_facility(name="Receiving Two", facility_code="RCV2",
                                 trauma_level="LEVEL_1",
                                 capabilities=["CARDIAC_CATH"])
        fac_r3 = create_facility(name="Receiving Three", facility_code="RCV3",
                                 trauma_level="LEVEL_2",
                                 capabilities=["CARDIAC_CATH"])
        phys_s = create_physician("Dr Send", fac_s["id"], "EMERGENCY")
        phys_r1 = create_physician("Dr Recv1", fac_r1["id"], "CARDIOLOGY")
        phys_r2 = create_physician("Dr Recv2", fac_r2["id"], "CARDIOLOGY")
        phys_r3 = create_physician("Dr Recv3", fac_r3["id"], "CARDIOLOGY")

        def certified_case(patient_ref, acuity, unit, emc, stabilized, **kw):
            case = create_case(fac_s["id"], phys_s["id"], acuity, unit,
                               "CARDIAC_CATH", False, patient_ref)
            create_screening(case["id"], phys_s["id"], emc, stabilized, **kw)
            certify_screening(case["id"], phys_s["id"])
            return case

        # Case A: EMTALA_APPLIES, one DIVERSION_ACTIVE refusal -> 40+50+0 = 90.
        case_a = certified_case("PT-RISK-A", "EMERGENT", "ICU", True, True)
        request_acceptance(case_a["id"], fac_r1["id"], phys_r1["id"])
        refuse_case(case_a["id"], phys_r1["id"], "DIVERSION_ACTIVE",
                    "Facility is on documented critical care diversion at time "
                    "of request.")

        # Case B: EMERGENCY_EXCEPTION, three NO_BED_AVAILABLE refusals.
        case_b = certified_case(
            "PT-RISK-B", "CRITICAL", "ICU", True, False,
            benefits_outweigh_risks=True,
            physician_certification="Unstable anterior STEMI; emergent cath "
                                    "outweighs flight risk profile.")
        request_acceptance(case_b["id"], fac_r1["id"], phys_r1["id"])
        refuse_case(case_b["id"], phys_r1["id"], "NO_BED_AVAILABLE",
                    "No ICU bed available at this time; escalation to house "
                    "supervisor complete.")
        re_request(case_b["id"], fac_r2["id"], phys_r2["id"])
        refuse_case(case_b["id"], phys_r2["id"], "NO_BED_AVAILABLE",
                    "All ICU beds occupied; transfer not possible within the "
                    "hour documented.")
        re_request(case_b["id"], fac_r3["id"], phys_r3["id"],
                   contact_method="TELEMEDICINE")
        refuse_case(case_b["id"], phys_r3["id"], "NO_BED_AVAILABLE",
                    "Third refusal: no monitored critical care bed available "
                    "tonight either.")

        # Case C: EMTALA_NOT_APPLIES, one UNSTABLE_FOR_TRANSFER -> 10+0+0 = 10.
        case_c = certified_case("PT-RISK-C", "STABLE", "MED_SURG", False, True)
        request_acceptance(case_c["id"], fac_r1["id"], phys_r1["id"])
        refuse_case(case_c["id"], phys_r1["id"], "UNSTABLE_FOR_TRANSFER",
                    "Receiving team judges the patient unstable for ground "
                    "transfer tonight.")

        rec_a = list_refusal_records(transfer_case_id=case_a["id"])[0]
        assert rec_a["emtala_risk_score"] == 90
        assert rec_a["emtala_risk_flag"] == "HIGH"

        recs_b = list_refusal_records(transfer_case_id=case_b["id"],
                                      refusing_physician_id=phys_r3["id"])
        assert len(recs_b) == 1
        assert recs_b[0]["emtala_risk_score"] == 70, (
            "30 base + 20 exception + 10*min(2,3) priors lands exactly on 70"
        )
        assert recs_b[0]["emtala_risk_flag"] == "HIGH", "exactly 70 is HIGH"
        assert recs_b[0]["round"] == 3

        rec_c = list_refusal_records(transfer_case_id=case_c["id"])[0]
        assert rec_c["emtala_risk_score"] == 10
        assert rec_c["emtala_risk_flag"] == "LOW"

        case_b_after = get_case(case_b["id"])
        assert case_b_after["refusal_count"] == 3
        assert case_b_after["status"] == "REFUSED"


class TestRefusalRerequestCycle:
    def _refused_once_workspace(self):
        """EMTALA_APPLIES case refused by RCV1 in round 1."""
        fac_s = create_facility()
        fac_r1 = create_facility(name="Receiving One", facility_code="RCV1",
                                 trauma_level="LEVEL_1",
                                 capabilities=["CARDIAC_CATH"])
        fac_r2 = create_facility(name="Receiving Two", facility_code="RCV2",
                                 trauma_level="LEVEL_1",
                                 capabilities=["CARDIAC_CATH"])
        phys_s = create_physician("Dr Send", fac_s["id"], "EMERGENCY")
        phys_r1 = create_physician("Dr RecvOne", fac_r1["id"], "CARDIOLOGY")
        phys_r2 = create_physician("Dr RecvTwo", fac_r2["id"], "CARDIOLOGY")
        case = create_case(fac_s["id"], phys_s["id"], "URGENT", "TELEMETRY",
                           "CARDIAC_CATH", False, "PT-CYC-1")
        create_screening(case["id"], phys_s["id"], True, True)
        certify_screening(case["id"], phys_s["id"])
        request_acceptance(case["id"], fac_r1["id"], phys_r1["id"])
        refuse_case(case["id"], phys_r1["id"], "CAPACITY_EXCEEDED",
                    "All telemetry beds occupied and boarding exceeds safe "
                    "threshold tonight.")
        return {"case": case, "fac_s": fac_s, "fac_r1": fac_r1,
                "fac_r2": fac_r2, "phys_s": phys_s, "phys_r1": phys_r1,
                "phys_r2": phys_r2}

    def test_rerequest_reopens_awaiting_acceptance(self, api):
        """PRD: "A new communication opens in `PENDING` for the incremented
        `negotiation_round`, the receiving references are overwritten, and the
        case returns `REFUSED → AWAITING_ACCEPTANCE`."
        PRD: "`REFUSED` is not terminal."

        Design: Difficulty/non_linear_state_machine/case_refusal_rerequest_cycle
        """
        ws = self._refused_once_workspace()
        case = re_request(ws["case"]["id"], ws["fac_r2"]["id"],
                          ws["phys_r2"]["id"], contact_method="TELEMEDICINE")
        assert case["status"] == "AWAITING_ACCEPTANCE", (
            "the cycle REFUSED -> AWAITING_ACCEPTANCE must be permitted"
        )
        assert case["negotiation_round"] == 2
        assert case["refusal_count"] == 1, "refusal history survives the loop"
        assert case["receiving_facility_id"] == ws["fac_r2"]["id"]
        assert case["receiving_physician_id"] == ws["phys_r2"]["id"]

    def test_rerequest_opens_round_two_pending_communication(self, api):
        """PRD: "A new communication opens in `PENDING` for the incremented
        `negotiation_round`, the receiving references are overwritten, and the
        case returns `REFUSED → AWAITING_ACCEPTANCE`."
        PRD: "The loop may iterate any number of times."

        Design: Difficulty/non_linear_state_machine/case_refusal_rerequest_cycle
        """
        ws = self._refused_once_workspace()
        re_request(ws["case"]["id"], ws["fac_r2"]["id"], ws["phys_r2"]["id"],
                   contact_method="TELEMEDICINE")
        comms = list_communications(transfer_case_id=ws["case"]["id"],
                                    to_physician_id=ws["phys_r2"]["id"])
        assert len(comms) == 1
        assert comms[0]["round"] == 2
        assert comms[0]["outcome"] == "PENDING"
        assert comms[0]["responded_at"] is None
        # The round-1 communication remains REFUSED — history is preserved.
        old = list_communications(transfer_case_id=ws["case"]["id"],
                                  to_physician_id=ws["phys_r1"]["id"])
        assert len(old) == 1
        assert old[0]["outcome"] == "REFUSED"
        assert old[0]["round"] == 1


class TestRefusalCascade:
    def _awaiting_emergent_case(self):
        ws = setup_certified_case(acuity="EMERGENT", unit="ICU", rcv_beds=(),
                                  patient_ref="PT-REF-1")
        drive_to_awaiting(ws)
        return ws

    def test_refuse_creates_scored_refusal_record(self, api):
        """PRD: "The current round's communication flips `PENDING → REFUSED`
        with `responded_at` stamped; a `RefusalRecord` is created capturing the
        refusing `facility_id`, the `refusing_physician_id`, the category and
        narrative, and the `round` in which it occurred; the case's
        `refusal_count` — the count of its refusal records — is recomputed, its
        version bumps, and it moves `AWAITING_ACCEPTANCE → REFUSED`."
        PRD: "The `emtala_risk_score` starts from a category base — 30 for
        `NO_BED_AVAILABLE`, 25 for `CAPABILITY_UNAVAILABLE`, 40 for
        `DIVERSION_ACTIVE`, 10 for `UNSTABLE_FOR_TRANSFER`, 20 for
        `CAPACITY_EXCEEDED` — adds an obligation increment of 50 when the case
        is `EMTALA_APPLIES`, 20 under `EMERGENCY_EXCEPTION`, and 0 under
        `EMTALA_NOT_APPLIES` or `UNDETERMINED`, then adds 10 points per prior
        refusal of the same case, counting at most three priors."

        Design: Difficulty/transitive_cascade/refusal_cascade_record_then_auto_review
        """
        ws = self._awaiting_emergent_case()
        case = refuse_case(ws["case"]["id"], ws["phys_r"]["id"],
                           "DIVERSION_ACTIVE",
                           "Facility is on full diversion for critical care; "
                           "accepting would violate diversion policy.")
        assert case["status"] == "REFUSED"
        assert case["refusal_count"] == 1

        records = list_refusal_records(transfer_case_id=ws["case"]["id"])
        assert len(records) == 1
        record = records[0]
        assert_refusal_record(record)
        assert record["emtala_risk_score"] == 90, "40 DIVERSION_ACTIVE + 50 APPLIES"
        assert record["emtala_risk_flag"] == "HIGH"
        assert record["round"] == 1
        assert record["facility_id"] == ws["fac_r"]["id"]
        assert record["refusing_physician_id"] == ws["phys_r"]["id"]

        comms = list_communications(transfer_case_id=ws["case"]["id"])
        assert comms[0]["outcome"] == "REFUSED"
        assert comms[0]["responded_at"] is not None

    def test_refuse_of_emtala_applies_case_auto_opens_review(self, api):
        """PRD: "Refusing a case whose `emtala_obligation` is `EMTALA_APPLIES`
        also auto-opens a `QualityReview` with trigger `REFUSAL_RISK` in `OPEN`,
        but only when the case has no review already `OPEN` or `UNDER_REVIEW`."

        Design: Difficulty/transitive_cascade/refusal_cascade_record_then_auto_review
        """
        ws = self._awaiting_emergent_case()
        refuse_case(ws["case"]["id"], ws["phys_r"]["id"], "DIVERSION_ACTIVE",
                    "Facility is on full diversion for critical care; accepting "
                    "would violate diversion policy.")
        review = find_review_for_case(ws["case"]["id"])
        assert review is not None, "refusal of an EMTALA_APPLIES case must open a review"
        assert review["trigger"] == "REFUSAL_RISK"
        assert review["status"] == "OPEN"

