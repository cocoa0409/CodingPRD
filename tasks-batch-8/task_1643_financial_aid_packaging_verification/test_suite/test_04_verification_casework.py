"""Verification and conflicting-information casework: the dual-variant EFC
switch, the correction re-verification loop, document lifecycle, completion
gates, and segregation of duties (PRD §3.3, §3.4, §2.7)."""
from test_helpers import (
    SSN_SELECTED_A,
    TEST_USERS,
    ApiErrorId,
    assert_isir_record,
    assert_timestamp_format,
    assert_verification_case,
    drive_case_to_under_review,
    get_case_documents,
    get_success_data,
    get_isir,
    get_verification_case,
    import_isir,
    make_aid_officer_headers,
    open_conflicting_info_case,
    register_student,
    set_clock,
    setup_open_aid_year,
    setup_selected_student_case,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["aid_officer_headers"]
DIRECTOR = TEST_USERS["aid_director_headers"]

SELECTED_ISIR = {"agi_cents": 4500000, "untaxed_income_cents": 0,
                 "asset_net_worth_cents": 50000, "household_size": 4,
                 "number_in_college": 1}


class TestVerifiedVsProvisionalEfc:
    def test_complete_satisfied_computes_verified_efc(self, api):
        """PRD §3.4: "The request may carry `verified_agi_cents`, `verified_untaxed_income_cents`, `verified_asset_net_worth_cents`, `verified_household_size`, and `verified_number_in_college`; any of these omitted defaults to the as-reported import value. The verified figures recompute the seven-step EFC of §3.3, the result is stored as `efc_verified_cents` on the linked ISIR record, and `efc_official_cents` is set to that verified figure."

        Design: Difficulty/dual_variant_calc/efc_provisional_vs_verified_divergence
        """
        env = setup_open_aid_year()
        student, isir, case = setup_selected_student_case(
            env, SSN_SELECTED_A, dict(SELECTED_ISIR))
        drive_case_to_under_review(case["id"])

        resp = api.complete_satisfied(
            case["id"],
            {"resolution_notes": "AGI corrected per tax transcript",
             "verified_agi_cents": 5200000},
            OFFICER)
        completed = validate_success(resp)
        assert completed["status"] == "COMPLETED_SATISFIED"

        record = get_isir(isir["id"])
        assert_isir_record(record)
        # PROVISIONAL variant on as-reported AGI 4_500_000 -> 742_000.
        assert record["efc_provisional_cents"] == 742000
        # VERIFIED variant on corrected AGI 5_200_000 -> 1_071_000.
        assert record["efc_verified_cents"] == 1071000
        assert record["efc_official_cents"] == 1071000

    def test_official_efc_stands_provisional_until_verification(self, api):
        """PRD §3.3: "The EFC exists in three fields on the record: `efc_provisional_cents`, computed at import from as-reported data; `efc_verified_cents`, which stays null (serializing as null) until verification completes satisfied; and `efc_official_cents`, the figure packaging actually uses — the verified figure once the linked verification case is `COMPLETED_SATISFIED`, and the provisional figure otherwise."
        PRD §3.4: "The case's `completed_at` is stamped and its `version` increments."

        Design: Difficulty/dual_variant_calc/efc_provisional_vs_verified_divergence
        """
        env = setup_open_aid_year()
        student, isir, case = setup_selected_student_case(
            env, SSN_SELECTED_A, dict(SELECTED_ISIR))

        before = get_isir(isir["id"])
        assert before["efc_provisional_cents"] == 742000
        assert before["efc_verified_cents"] is None
        assert before["efc_official_cents"] == 742000

        drive_case_to_under_review(case["id"])
        completed = validate_success(api.complete_satisfied(
            case["id"],
            {"resolution_notes": "AGI corrected per tax transcript",
             "verified_agi_cents": 5200000},
            OFFICER))
        assert completed["status"] == "COMPLETED_SATISFIED"
        assert_timestamp_format(completed["completed_at"])

        after = get_isir(isir["id"])
        assert after["efc_official_cents"] == 1071000


class TestCorrectionReverificationLoop:
    def _drive_to_correction_sent(self, api):
        env = setup_open_aid_year()
        student, isir, case = setup_selected_student_case(
            env, SSN_SELECTED_A, dict(SELECTED_ISIR))
        docs = get_case_documents(case["id"])
        for doc in docs:
            validate_success(api.mark_document_received(doc["id"], OFFICER))
        validate_success(api.accept_document(docs[0]["id"], OFFICER))
        validate_success(api.begin_review_verification_case(case["id"], OFFICER))
        resp = api.complete_correction(
            case["id"], "AGI mismatch; correction filed", OFFICER)
        corrected = validate_success(resp)
        assert corrected["status"] == "COMPLETED_CORRECTION_SENT"
        return env, student, isir, case

    def test_selected_correction_import_loops_case_back(self, api):
        """PRD §3.4: "a correction-sent case loops back to `DOCUMENTS_REQUESTED` when the corrected ISIR arrives selected"
        PRD §3.3: "When a newer transaction is later imported, the older record is superseded — it moves to the terminal `SUPERSEDED` stage and its `is_current` flips to false — while the newcomer becomes current."

        Design: Difficulty/non_linear_state_machine/verification_case_correction_loop_cycle
        """
        env, student, isir1, case = self._drive_to_correction_sent(api)

        # Advance the logical clock so the correction's receipt stamp is not in
        # the future (rung 12 window check).
        set_clock("2026-09-02T00:00:00Z")
        isir2 = import_isir(student["id"], env["aid_year"]["id"],
                            transaction_number=2,
                            received_at="2026-09-02T00:00:00Z",
                            agi_cents=5200000, asset_net_worth_cents=50000,
                            cps_selection_flag=True)

        looped = get_verification_case(case["id"])
        assert_verification_case(looped)
        assert looped["status"] == "DOCUMENTS_REQUESTED"

        assert isir2["is_current"] is True
        superseded = get_isir(isir1["id"])
        assert superseded["is_current"] is False

    def test_correction_import_recomputes_provisional_efc(self, api):
        """PRD §3.4: "Completing with a correction moves the case to `COMPLETED_CORRECTION_SENT` — permitted when at least one required document type has been `ACCEPTED` and a non-empty `resolution_notes` is supplied — recording that the corrected values will arrive later as a new ISIR transaction."
        PRD §3.3: "`efc_provisional_cents`, computed at import from as-reported data".

        Design: Difficulty/non_linear_state_machine/verification_case_correction_loop_cycle
        """
        env, student, isir1, case = self._drive_to_correction_sent(api)

        set_clock("2026-09-02T00:00:00Z")
        isir2 = import_isir(student["id"], env["aid_year"]["id"],
                            transaction_number=2,
                            received_at="2026-09-02T00:00:00Z",
                            agi_cents=5200000, asset_net_worth_cents=50000,
                            cps_selection_flag=True)

        # Corrected AGI 5_200_000 (household 4, DEPENDENT): AI = 2_800_000;
        # IC = 110_000 + 350_000 + 611_000 = 1_071_000.
        assert isir2["efc_provisional_cents"] == 1071000
        assert isir2["is_current"] is True
        assert get_verification_case(case["id"])["status"] == "DOCUMENTS_REQUESTED"


class TestCompleteSatisfiedGates:
    def _setup_under_review_with_open_conflict(self, api):
        env = setup_open_aid_year()
        student, isir, case = setup_selected_student_case(
            env, SSN_SELECTED_A, dict(SELECTED_ISIR))
        drive_case_to_under_review(case["id"])
        conflict = open_conflicting_info_case(
            student["id"], env["aid_year"]["id"], subject_field="agi_cents",
            claimed_value_cents=5200000, opener="officer-alpha")
        return env, student, isir, case, conflict

    def test_open_conflict_blocks_completion(self, api):
        """PRD §3.4: "Completing satisfied moves the case to `COMPLETED_SATISFIED` and carries the heaviest preconditions: the case must be `UNDER_REVIEW`, every required document type must be `ACCEPTED` (otherwise `ERR_VERIFICATION_DOCS_INCOMPLETE`), a non-empty `resolution_notes` must be supplied, and no ConflictingInfoCase for the same student and aid year may sit in `OPEN`, `SUBSTANTIATED`, or `RESOLVED_REQUIRES_CORRECTION` (otherwise `ERR_CONFLICTING_INFO_OPEN`)."

        Design: Difficulty/cross_entity_state_dependency/verification_complete_gated_by_conflicting_info_case
        """
        env, student, isir, case, conflict = (
            self._setup_under_review_with_open_conflict(api))

        resp = api.complete_satisfied(
            case["id"], {"resolution_notes": "All docs verified"}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_CONFLICTING_INFO_OPEN)
        assert get_verification_case(case["id"])["status"] == "UNDER_REVIEW"

    def test_resolved_conflict_unblocks_completion(self, api):
        """PRD §3.4: "no ConflictingInfoCase for the same student and aid year may sit in `OPEN`, `SUBSTANTIATED`, or `RESOLVED_REQUIRES_CORRECTION` (otherwise `ERR_CONFLICTING_INFO_OPEN`)."
        PRD §3.4: "an unsubstantiated case moves straight to `RESOLVED` with a non-empty `resolution`."

        Design: Difficulty/cross_entity_state_dependency/verification_complete_gated_by_conflicting_info_case
        """
        env, student, isir, case, conflict = (
            self._setup_under_review_with_open_conflict(api))

        validate_success(api.unsubstantiate_conflicting_info_case(
            conflict["id"], make_aid_officer_headers("officer-alpha")))
        resolved = validate_success(api.resolve_conflicting_info_case(
            conflict["id"], "Third-party statement was erroneous",
            make_aid_officer_headers("officer-beta")))
        assert resolved["status"] == "RESOLVED"

        completed = validate_success(api.complete_satisfied(
            case["id"], {"resolution_notes": "All docs verified"}, OFFICER))
        assert completed["status"] == "COMPLETED_SATISFIED"
        # No verified_* overrides: verified figures default to as-reported, so
        # the verified EFC recomputes to the same 742_000 and becomes official.
        record = get_isir(isir["id"])
        assert record["efc_verified_cents"] == 742000
        assert record["efc_official_cents"] == 742000

    def test_incomplete_documents_block_completion(self, api):
        """PRD §3.4: "Completing satisfied moves the case to `COMPLETED_SATISFIED` and carries the heaviest preconditions: the case must be `UNDER_REVIEW`, every required document type must be `ACCEPTED` (otherwise `ERR_VERIFICATION_DOCS_INCOMPLETE`), a non-empty `resolution_notes` must be supplied, and no ConflictingInfoCase for the same student and aid year may sit in `OPEN`, `SUBSTANTIATED`, or `RESOLVED_REQUIRES_CORRECTION` (otherwise `ERR_CONFLICTING_INFO_OPEN`)."

        Design: Corner/validations/verification_docs_incomplete_blocks_satisfied
        """
        env = setup_open_aid_year()
        student, isir, case = setup_selected_student_case(
            env, SSN_SELECTED_A, dict(SELECTED_ISIR))
        # Two of three required docs ACCEPTED; the third remains RECEIVED.
        drive_case_to_under_review(case["id"], accept_count=2)

        resp = api.complete_satisfied(
            case["id"],
            {"resolution_notes": "Trying with one doc merely received"},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_VERIFICATION_DOCS_INCOMPLETE)
        assert get_verification_case(case["id"])["status"] == "UNDER_REVIEW"


class TestDocumentLifecycle:
    def test_document_initial_state_and_receive_not_idempotent(self, api):
        """PRD §3.4: "created in `DOCUMENTS_REQUESTED` with three required VerificationDocument rows — `TAX_RETURN_TRANSCRIPT`, `W2`, and `HOUSEHOLD_FORM` — each bound to its case through `verification_case_id` and starting in `REQUESTED`."
        PRD §3.4: "Marking a `REQUESTED` document received moves it to `RECEIVED` and stamps `received_at` from the logical clock".
        PRD §2.7 (rung 5): "the target entity's state machine permits the requested transition from its current state — otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/verification_document_initial_state_and_idempotent_receive
        """
        env = setup_open_aid_year()
        student, isir, case = setup_selected_student_case(
            env, SSN_SELECTED_A, dict(SELECTED_ISIR))
        docs = get_case_documents(case["id"])
        assert len(docs) == 3
        assert docs[0]["status"] == "REQUESTED"

        received = validate_success(api.mark_document_received(docs[0]["id"],
                                                               OFFICER))
        assert received["status"] == "RECEIVED"
        assert_timestamp_format(received["received_at"])

        resp = api.mark_document_received(docs[0]["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestConflictingInfoSegregation:
    def test_opener_cannot_resolve_own_case(self, api):
        """PRD §3.4: "Both resolving transitions stamp `resolved_by_user_id` and enforce segregation of duties — the resolving caller must not be the user recorded in `opened_by_user_id`, or the request fails with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.7 (rung 7): "the resolving caller on a conflicting-information case must differ from `opened_by_user_id`, and the deciding caller on a professional judgment case must differ from `reviewed_by_user_id` — otherwise `ERR_SEGREGATION_OF_DUTIES` (403)."

        Design: Corner/errors/error_segregation_of_duties_conflict_resolver
        """
        env = setup_open_aid_year()
        student = register_student("555667777", full_name="SoD Target",
                                   email="sod@example.edu")
        import_isir(student["id"], env["aid_year"]["id"], agi_cents=4500000)
        conflict = open_conflicting_info_case(
            student["id"], env["aid_year"]["id"], subject_field="household_size",
            claimed_value_cents=5, opener="officer-alpha")
        assert conflict["opened_by_user_id"] == "officer-alpha"

        validate_success(api.unsubstantiate_conflicting_info_case(
            conflict["id"], make_aid_officer_headers("officer-alpha")))

        resp = api.resolve_conflicting_info_case(
            conflict["id"], "Third-party statement was erroneous",
            make_aid_officer_headers("officer-alpha"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        case = get_success_data(api.get_conflicting_info_case(conflict["id"],
                                                              OFFICER))
        assert case["status"] == "UNSUBSTANTIATED"
