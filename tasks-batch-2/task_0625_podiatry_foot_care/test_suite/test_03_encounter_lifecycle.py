"""Encounter lifecycle: complete-exam, code/recode cycle, submit, adjudicate,
void, the rendering-provider ownership check, terminal lockdown, and the
adjudicate-advances-frequency-window cascade.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    assert_encounter, assert_procedure, assert_patient,
    ApiErrorId, TEST_USERS, make_podiatrist_headers,
    setup_practice_provider_patient, create_encounter, add_procedure,
    complete_exam, code_encounter, setup_coded_encounter,
    setup_encounter_in_exam_done, setup_adjudicated_encounter, set_clock,
    create_modality,
)
from test_helpers import create_imaging_order_payload

ADMIN = TEST_USERS["practice_admin_headers"]
FRONTDESK = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]
PAYER = TEST_USERS["payer_agent_headers"]


# ─── non_linear_state_machine / encounter_recode_revert_cycle ──────────────
class TestEncounterRecodeCycle:
    """CODED -> EXAM_DONE recode resets coverage decisions and totals."""

    def _coded_diabetic_encounter(self):
        set_clock("2026-06-01T09:00:00Z")
        practice, provider, patient = setup_practice_provider_patient(
            patient_overrides={"has_diabetes_mellitus": True})
        coded, proc = setup_coded_encounter(
            patient["id"], provider["id"],
            encounter_overrides={"scheduled_start": "2026-06-01T12:00:00Z",
                                 "scheduled_end": "2026-06-01T12:30:00Z"},
            procedure_overrides={"procedure_kind": "ROUTINE_NAIL_DEBRIDEMENT",
                                 "service_date": "2026-06-01",
                                 "billed_cents": 8000, "fee_cap_cents": 7000})
        return coded, proc

    def test_recode_reverts_status_and_zeros_totals(self, api):
        """PRD §3.3: "Should a coding error surface, the same `BillingSpecialist`
        can recode, reverting `CODED → EXAM_DONE`: this resets the exam's
        `exam_coverage_decision` back to `PENDING`, every child procedure's
        `coverage_decision` back to `PENDING`, every per-line
        `medicare_pays_cents` and `patient_resp_cents` to 0, and the encounter's
        two totals to 0, leaving the encounter ready to be corrected and
        re-coded."

        Design: Difficulty/non_linear_state_machine/encounter_recode_revert_cycle
        """
        coded, proc = self._coded_diabetic_encounter()
        reverted = validate_success(api.recode_encounter(coded["id"], BILLING), 200)
        assert_encounter(reverted)
        assert reverted["status"] == "EXAM_DONE"
        assert reverted["total_medicare_pays_cents"] == 0
        assert reverted["total_patient_resp_cents"] == 0

    def test_recode_resets_child_procedure_coverage(self, api):
        """PRD §3.3: "this resets the exam's `exam_coverage_decision` back to
        `PENDING`, every child procedure's `coverage_decision` back to
        `PENDING`, every per-line `medicare_pays_cents` and `patient_resp_cents`
        to 0"

        Design: Difficulty/non_linear_state_machine/encounter_recode_revert_cycle
        """
        coded, proc = self._coded_diabetic_encounter()
        api.recode_encounter(coded["id"], BILLING)
        proc_after = get_success_data(api.get_procedure(proc["id"], FRONTDESK))
        assert proc_after["coverage_decision"] == "PENDING"


# ─── compensating_invariant / encounter_code_then_recode_conserves_charge_zero ─
class TestEncounterChargeConservation:
    """Coding sets nonzero totals (13600/3400); recode restores them to exactly 0."""

    def _coded(self):
        set_clock("2026-06-01T09:00:00Z")
        practice, provider, patient = setup_practice_provider_patient(
            patient_overrides={"has_diabetes_mellitus": True})
        coded, proc = setup_coded_encounter(
            patient["id"], provider["id"],
            encounter_overrides={"scheduled_start": "2026-06-01T21:00:00Z",
                                 "scheduled_end": "2026-06-01T21:30:00Z",
                                 "exam_billed_cents": 12000, "exam_fee_cap_cents": 10000},
            procedure_overrides={"procedure_kind": "ROUTINE_NAIL_DEBRIDEMENT",
                                 "service_date": "2026-06-01",
                                 "billed_cents": 8000, "fee_cap_cents": 7000})
        return coded

    def test_code_sets_nonzero_then_recode_zeros(self, api):
        """PRD §3.3: "the encounter's `total_medicare_pays_cents` and
        `total_patient_resp_cents` are recomputed as the sums of the per-line
        payer and patient amounts across the exam line and all procedures."
        PRD §3.3: "this resets the exam's `exam_coverage_decision` back to
        `PENDING`, every child procedure's `coverage_decision` back to
        `PENDING`, every per-line `medicare_pays_cents` and `patient_resp_cents`
        to 0, and the encounter's two totals to 0"

        Design: Difficulty/compensating_invariant/encounter_code_then_recode_conserves_charge_zero
        """
        coded = self._coded()
        # exam allowed 10000 covered -> 8000/2000; routine covered allowed 7000 -> 5600/1400.
        assert coded["total_medicare_pays_cents"] == 13600
        assert coded["total_patient_resp_cents"] == 3400
        reverted = validate_success(api.recode_encounter(coded["id"], BILLING), 200)
        assert reverted["total_medicare_pays_cents"] == 0
        assert reverted["total_patient_resp_cents"] == 0

    def test_recode_leaves_encounter_in_exam_done(self, api):
        """PRD §3.3: "the same `BillingSpecialist` can recode, reverting
        `CODED → EXAM_DONE`"

        Design: Difficulty/compensating_invariant/encounter_code_then_recode_conserves_charge_zero
        """
        coded = self._coded()
        reverted = validate_success(api.recode_encounter(coded["id"], BILLING), 200)
        assert reverted["status"] == "EXAM_DONE"


# ─── priority_pair_validation_conflict / complete_exam_bad_state_beats_not_rendering_provider ─
class TestCompleteExamPriorityConflict:
    """complete-exam on an EXAM_DONE encounter by a non-renderer: the state
    check (p7) wins over the rendering-provider check (p8)."""

    def test_bad_state_reported_over_not_rendering_provider(self, api):
        """PRD §2.11: "then the target entity's state legality for the requested
        transition (`ERR_ENCOUNTER_BAD_STATE` and its analogues on the other
        lifecycles); then the rendering-provider ownership check on exam
        completion (`ERR_NOT_RENDERING_PROVIDER`)"
        PRD §3.3: "completing an exam on an encounter not in `OPEN` is rejected
        with `ERR_ENCOUNTER_BAD_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/complete_exam_bad_state_beats_not_rendering_provider
        """
        set_clock("2026-06-01T09:00:00Z")
        practice = get_success_data(api.create_practice(
            {"name": "Foot Clinic", "npi": "1234567890"}, ADMIN))
        prov1 = get_success_data(api.create_provider(
            {"practice_id": practice["id"], "full_name": "Dr Sole",
             "role_type": "PODIATRIST"}, ADMIN))
        prov2 = get_success_data(api.create_provider(
            {"practice_id": practice["id"], "full_name": "Dr Other",
             "role_type": "PODIATRIST"}, ADMIN))
        patient = get_success_data(api.create_patient(
            {"practice_id": practice["id"], "full_name": "Pat State",
             "date_of_birth": "1964-10-10", "has_diabetes_mellitus": False}, FRONTDESK))
        enc = create_encounter(patient["id"], prov1["id"],
                               scheduled_start="2026-06-01T16:00:00Z",
                               scheduled_end="2026-06-01T16:30:00Z")
        # Advance to EXAM_DONE by the rendering provider.
        complete_exam(enc["id"], prov1["id"])
        # Now a non-renderer attempts complete-exam on the EXAM_DONE encounter.
        res = api.complete_exam(enc["id"], make_podiatrist_headers(prov2["id"]))
        validate_error(res, ApiErrorId.ERR_ENCOUNTER_BAD_STATE.value)

    def test_bad_state_conflict_is_409(self, api):
        """PRD §3.3: "completing an exam on an encounter not in `OPEN` is rejected
        with `ERR_ENCOUNTER_BAD_STATE`."
        PRD §5: error code catalogue maps `ERR_ENCOUNTER_BAD_STATE` to
        "409 Conflict".

        Design: Difficulty/priority_pair_validation_conflict/complete_exam_bad_state_beats_not_rendering_provider
        """
        set_clock("2026-06-01T09:00:00Z")
        practice = get_success_data(api.create_practice(
            {"name": "Foot Clinic", "npi": "1234567890"}, ADMIN))
        prov1 = get_success_data(api.create_provider(
            {"practice_id": practice["id"], "full_name": "Dr Sole",
             "role_type": "PODIATRIST"}, ADMIN))
        prov2 = get_success_data(api.create_provider(
            {"practice_id": practice["id"], "full_name": "Dr Other",
             "role_type": "PODIATRIST"}, ADMIN))
        patient = get_success_data(api.create_patient(
            {"practice_id": practice["id"], "full_name": "Pat State2",
             "date_of_birth": "1964-10-10", "has_diabetes_mellitus": False}, FRONTDESK))
        enc = create_encounter(patient["id"], prov1["id"],
                               scheduled_start="2026-06-01T16:00:00Z",
                               scheduled_end="2026-06-01T16:30:00Z")
        complete_exam(enc["id"], prov1["id"])
        res = api.complete_exam(enc["id"], make_podiatrist_headers(prov2["id"]))
        assert res.status_code == 409, (
            f"state-vs-auth conflict must surface 409 (ERR_ENCOUNTER_BAD_STATE), "
            f"got {res.status_code}")


# ─── transitive_cascade / adjudicate_advances_patient_window_then_denies_next_coding ─
class TestAdjudicateAdvancesFrequencyWindow:
    """Adjudicating E1 advances last_covered_routine_care_date; a later E2 within
    the window is then coded DENIED_FREQUENCY."""

    def _setup_e1_submitted_e2_exam_done(self, api):
        set_clock("2026-06-01T08:00:00Z")
        practice, provider, patient = setup_practice_provider_patient(
            patient_overrides={"has_diabetes_mellitus": True})
        # E1: service 2026-06-01, code+submit (NOT yet adjudicated).
        e1, p1 = setup_coded_encounter(
            patient["id"], provider["id"],
            encounter_overrides={"scheduled_start": "2026-06-01T09:00:00Z",
                                 "scheduled_end": "2026-06-01T09:30:00Z"},
            procedure_overrides={"procedure_kind": "ROUTINE_NAIL_DEBRIDEMENT",
                                 "service_date": "2026-06-01",
                                 "billed_cents": 8000, "fee_cap_cents": 7000})
        get_success_data(api.submit_encounter(e1["id"], BILLING))
        # E2: service 2026-07-15 (gap 44 < 61), EXAM_DONE only.
        set_clock("2026-07-15T08:00:00Z")
        e2, p2 = setup_encounter_in_exam_done(
            patient["id"], provider["id"],
            encounter_overrides={"scheduled_start": "2026-07-15T09:00:00Z",
                                 "scheduled_end": "2026-07-15T09:30:00Z"},
            procedure_overrides={"procedure_kind": "ROUTINE_NAIL_DEBRIDEMENT",
                                 "service_date": "2026-07-15",
                                 "billed_cents": 8000, "fee_cap_cents": 7000})
        return patient, e1, p1, e2, p2

    def test_adjudicate_sets_last_covered_routine_date(self, api):
        """PRD §3.3: "for each child procedure that is routine and was decided
        `COVERED`, the patient's `last_covered_routine_care_date` is set to the
        later of its existing value and that procedure's `service_date`."

        Design: Difficulty/transitive_cascade/adjudicate_advances_patient_window_then_denies_next_coding
        """
        patient, e1, p1, e2, p2 = self._setup_e1_submitted_e2_exam_done(api)
        get_success_data(api.adjudicate_encounter(e1["id"], PAYER))
        pat_after = get_success_data(api.get_patient(patient["id"], FRONTDESK))
        assert_patient(pat_after)
        assert pat_after["last_covered_routine_care_date"] == "2026-06-01"

    def test_later_encounter_denied_frequency_after_window_advance(self, api):
        """PRD §3.3: "because the frequency window is read at coding time (see
        §3.4), advancing it here means any future encounter coded afterward sees
        the new last-covered date."
        PRD §3.4: "the procedure is `COVERED` when that gap is at least the
        practice's `routine_care_min_interval_days` and `DENIED_FREQUENCY` when
        the gap is strictly less."

        Design: Difficulty/transitive_cascade/adjudicate_advances_patient_window_then_denies_next_coding
        """
        patient, e1, p1, e2, p2 = self._setup_e1_submitted_e2_exam_done(api)
        get_success_data(api.adjudicate_encounter(e1["id"], PAYER))
        code_encounter(e2["id"])
        p2_after = get_success_data(api.get_procedure(p2["id"], FRONTDESK))
        assert p2_after["coverage_decision"] == "DENIED_FREQUENCY"
        assert p2_after["patient_resp_cents"] == 8000


# ─── state_machines / complete_exam_from_open_succeeds_initial_state ───────
def test_complete_exam_from_open_succeeds(api):
    """PRD §3.3: "A `Podiatrist` advances the encounter from `OPEN` to
    `EXAM_DONE` by completing the exam, but only the rendering provider may do
    so: the acting podiatrist's `X-User-ID` must equal the encounter's
    `provider_id`"

    Design: Corner/state_machines/complete_exam_from_open_succeeds_initial_state
    """
    set_clock("2026-06-01T09:00:00Z")
    practice, provider, patient = setup_practice_provider_patient()
    enc = create_encounter(patient["id"], provider["id"])
    assert enc["status"] == "OPEN"
    res = api.complete_exam(enc["id"], make_podiatrist_headers(provider["id"]))
    updated = validate_success(res, 200)
    assert updated["status"] == "EXAM_DONE"


# ─── state_machines / code_encounter_from_open_invalid_transition_rejected ─
def test_code_from_open_rejected(api):
    """PRD §3.3: "Coding an encounter not in `EXAM_DONE` is rejected with
    `ERR_ENCOUNTER_BAD_STATE`."

    Design: Corner/state_machines/code_encounter_from_open_invalid_transition_rejected
    """
    set_clock("2026-06-01T09:00:00Z")
    practice, provider, patient = setup_practice_provider_patient()
    enc = create_encounter(patient["id"], provider["id"])
    res = api.code_encounter(enc["id"], BILLING)
    validate_error(res, ApiErrorId.ERR_ENCOUNTER_BAD_STATE.value)


# ─── state_machines / adjudicated_encounter_terminal_lockdown_void_rejected ─
def test_void_adjudicated_encounter_rejected(api):
    """PRD §3.3: "a `BillingSpecialist` may void an encounter that is in `OPEN`,
    `EXAM_DONE`, or `CODED` (a void from any other state — for example a
    `SUBMITTED` or already-`ADJUDICATED` encounter — is rejected with
    `ERR_ENCOUNTER_BAD_STATE`)."

    Design: Corner/state_machines/adjudicated_encounter_terminal_lockdown_void_rejected
    """
    set_clock("2026-06-01T08:00:00Z")
    practice, provider, patient = setup_practice_provider_patient()
    adj, _ = setup_adjudicated_encounter(patient["id"], provider["id"])
    assert adj["status"] == "ADJUDICATED"
    res = api.void_encounter(adj["id"], BILLING)
    validate_error(res, ApiErrorId.ERR_ENCOUNTER_BAD_STATE.value)


# ─── state_machines / void_cancels_scheduled_child_imaging_order ───────────
def test_void_cancels_scheduled_imaging_order(api):
    """PRD §3.3: "as a cascade cancels any child imaging order still in
    `SCHEDULED` — moving each such `ImagingOrder` to `CANCELLED` and thereby
    freeing the modality interval it held."

    Design: Corner/state_machines/void_cancels_scheduled_child_imaging_order
    """
    set_clock("2026-06-02T08:00:00Z")
    practice, provider, patient = setup_practice_provider_patient()
    modality = create_modality(practice["id"], name="X-Ray 1", modality_type="XRAY",
                               cleanup_buffer_minutes=15)
    enc = create_encounter(patient["id"], provider["id"],
                           scheduled_start="2026-06-02T09:00:00Z",
                           scheduled_end="2026-06-02T09:30:00Z")
    img = get_success_data(api.create_imaging_order(
        create_imaging_order_payload(enc["id"], modality["id"], modality["version"],
                                     study_start="2026-06-02T10:00:00Z",
                                     study_end="2026-06-02T10:30:00Z"),
        make_podiatrist_headers(provider["id"])))
    get_success_data(api.void_encounter(enc["id"], BILLING))
    img_after = get_success_data(api.get_imaging_order(img["id"], FRONTDESK))
    assert img_after["status"] == "CANCELLED"
