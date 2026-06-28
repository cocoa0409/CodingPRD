"""Coverage decisions and charge-split math: the Medicare frequency rule, the
covered/denied dual variant, the conditional min-cap charge branch, lab-order
per-line rounding, and the round-half-up payer portion.

Each test translates exactly one design-index instance (tag on the docstring's
final line).
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success,
    assert_procedure, assert_encounter, assert_lab_order,
    TEST_USERS,
    setup_practice_provider_patient, create_encounter, add_procedure,
    complete_exam, code_encounter, setup_coded_encounter,
    setup_encounter_in_exam_done, establish_last_covered_routine_date,
    create_approved_pa, create_approved_rx, create_lab_order, set_clock,
)

FRONTDESK = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]


# ─── dual_variant_calc / procedure_coverage_covered_via_diabetes_vs_denied_frequency ─
class TestRoutineCoverageDualVariant:
    """Same routine kind + same diabetic patient diverge: COVERED at gap>=61 vs
    DENIED_FREQUENCY at gap==60."""

    def _setup_patient_with_last_covered(self):
        """Diabetic patient whose last_covered_routine_care_date == 2026-04-01."""
        set_clock("2026-04-01T08:00:00Z")
        practice, provider, patient = setup_practice_provider_patient(
            patient_overrides={"has_diabetes_mellitus": True})
        establish_last_covered_routine_date(patient["id"], provider["id"], "2026-04-01")
        return practice, provider, patient

    def test_routine_covered_when_gap_at_least_min_interval(self, api):
        """PRD §3.4: "the procedure is `COVERED` when that gap is at least the
        practice's `routine_care_min_interval_days` and `DENIED_FREQUENCY` when
        the gap is strictly less."
        PRD §3.5: "the payer portion (`medicare_pays_cents`) is the allowed
        amount multiplied by the practice's `fee_split_medicare_pct`, rounded
        half up to whole cents, and the patient portion (`patient_resp_cents`)
        is the exact remainder — the allowed amount minus the payer portion."

        Design: Difficulty/dual_variant_calc/procedure_coverage_covered_via_diabetes_vs_denied_frequency
        """
        practice, provider, patient = self._setup_patient_with_last_covered()
        set_clock("2026-06-01T09:00:00Z")
        coded, proc = setup_coded_encounter(
            patient["id"], provider["id"],
            encounter_overrides={"scheduled_start": "2026-06-01T09:00:00Z",
                                 "scheduled_end": "2026-06-01T09:30:00Z"},
            procedure_overrides={"procedure_kind": "ROUTINE_NAIL_DEBRIDEMENT",
                                 "service_date": "2026-06-01",
                                 "billed_cents": 8000, "fee_cap_cents": 7000})
        assert_procedure(proc)
        assert proc["coverage_decision"] == "COVERED"
        assert proc["medicare_pays_cents"] == 5600
        assert proc["patient_resp_cents"] == 1400

    def test_routine_denied_frequency_when_gap_below_min_interval(self, api):
        """PRD §3.4: "the procedure is `COVERED` when that gap is at least the
        practice's `routine_care_min_interval_days` and `DENIED_FREQUENCY` when
        the gap is strictly less."
        PRD §3.5: "For a line denied under either `DENIED_FREQUENCY` or
        `DENIED_NO_QUALIFYING_DX`, the payer portion is 0 and the patient
        portion is the full billed amount of the line, uncapped — that is, the
        billed amount itself rather than the allowed amount."

        Design: Difficulty/dual_variant_calc/procedure_coverage_covered_via_diabetes_vs_denied_frequency
        """
        practice, provider, patient = self._setup_patient_with_last_covered()
        set_clock("2026-05-31T09:00:00Z")
        coded, proc = setup_coded_encounter(
            patient["id"], provider["id"],
            encounter_overrides={"scheduled_start": "2026-05-31T09:00:00Z",
                                 "scheduled_end": "2026-05-31T09:30:00Z"},
            procedure_overrides={"procedure_kind": "ROUTINE_NAIL_DEBRIDEMENT",
                                 "service_date": "2026-05-31",
                                 "billed_cents": 8000, "fee_cap_cents": 7000})
        assert proc["coverage_decision"] == "DENIED_FREQUENCY"
        assert proc["medicare_pays_cents"] == 0
        assert proc["patient_resp_cents"] == 8000


# ─── combinatorial_formula / encounter_charge_split_conditional_min_cap_branch ─
class TestEncounterChargeSplitCombinatorial:
    """Encounter totals combine a covered exam (min-cap + round-half-up split)
    with a denied routine line (full billed to patient)."""

    def test_covered_exam_plus_denied_no_dx_routine_totals(self, api):
        """PRD §3.4: "if the patient does not have diabetes mellitus, the
        procedure is `DENIED_NO_QUALIFYING_DX` — routine foot care requires the
        qualifying systemic condition."
        PRD §3.5: "the allowed amount for the line is the lesser of its billed
        amount and its fee-schedule cap"
        PRD §3.5: "The encounter totals are then the sum of the payer portions
        across all lines and the sum of the patient portions across all lines."

        Design: Difficulty/combinatorial_formula/encounter_charge_split_conditional_min_cap_branch
        """
        set_clock("2026-06-01T09:00:00Z")
        practice, provider, patient = setup_practice_provider_patient(
            patient_overrides={"has_diabetes_mellitus": False})
        coded, proc = setup_coded_encounter(
            patient["id"], provider["id"],
            encounter_overrides={"scheduled_start": "2026-06-01T10:00:00Z",
                                 "scheduled_end": "2026-06-01T10:30:00Z",
                                 "exam_billed_cents": 12000, "exam_fee_cap_cents": 10000},
            procedure_overrides={"procedure_kind": "ROUTINE_CALLUS_PARING",
                                 "service_date": "2026-06-01",
                                 "billed_cents": 8000, "fee_cap_cents": 7000})
        assert proc["coverage_decision"] == "DENIED_NO_QUALIFYING_DX"
        assert coded["total_medicare_pays_cents"] == 8000
        assert coded["total_patient_resp_cents"] == 10000

    def test_encounter_totals_visible_in_code_response(self, api):
        """PRD §3.3: "the encounter's `total_medicare_pays_cents` and
        `total_patient_resp_cents` are recomputed as the sums of the per-line
        payer and patient amounts across the exam line and all procedures."
        PRD §3.5: "the payer portion (`medicare_pays_cents`) is the allowed
        amount multiplied by the practice's `fee_split_medicare_pct`, rounded
        half up to whole cents, and the patient portion (`patient_resp_cents`)
        is the exact remainder — the allowed amount minus the payer portion."

        Design: Difficulty/combinatorial_formula/encounter_charge_split_conditional_min_cap_branch
        """
        set_clock("2026-06-01T09:00:00Z")
        practice, provider, patient = setup_practice_provider_patient(
            patient_overrides={"has_diabetes_mellitus": False})
        coded, proc = setup_coded_encounter(
            patient["id"], provider["id"],
            encounter_overrides={"scheduled_start": "2026-06-01T10:00:00Z",
                                 "scheduled_end": "2026-06-01T10:30:00Z",
                                 "exam_billed_cents": 12000, "exam_fee_cap_cents": 10000},
            procedure_overrides={"procedure_kind": "ROUTINE_CALLUS_PARING",
                                 "service_date": "2026-06-01",
                                 "billed_cents": 8000, "fee_cap_cents": 7000})
        assert_encounter(coded)
        # exam allowed = min(12000,10000)=10000; covered -> payer 8000, patient 2000.
        # routine denied_no_dx -> payer 0, patient full billed 8000. Totals 8000 / 10000.
        assert coded["total_medicare_pays_cents"] == 8000
        assert coded["total_patient_resp_cents"] == 10000


# ─── combinatorial_formula / lab_order_total_round_per_line_then_sum ────────
class TestLabOrderRoundingOrder:
    """Round each line then sum: two raw 500.5 lines -> 501 each -> total 1002."""

    def _setup_approved_orthotic_rx(self):
        set_clock("2026-06-01T09:00:00Z")
        practice, provider, patient = setup_practice_provider_patient(
            patient_overrides={"has_diabetes_mellitus": True})
        pa = create_approved_pa(patient["id"], service_category="ORTHOTIC",
                                hcpcs_code="L3000", authorized_units=5)
        enc = create_encounter(patient["id"], provider["id"],
                               scheduled_start="2026-06-01T11:00:00Z",
                               scheduled_end="2026-06-01T11:30:00Z")
        rx = create_approved_rx(enc["id"], provider["id"], pa["id"])
        return rx

    def test_total_is_per_line_rounded_then_summed(self, api):
        """PRD §3.7: "for each line item, the raw line charge is its
        `unit_price_cents` multiplied by its `quantity` multiplied by one minus
        its `discount_pct`, that raw line is rounded half up to whole cents, and
        the rounded line cents are accumulated into the running total, which
        becomes `total_cents`."

        Design: Difficulty/combinatorial_formula/lab_order_total_round_per_line_then_sum
        """
        rx = self._setup_approved_orthotic_rx()
        lab = create_lab_order(
            rx["id"], lab_name="OrthoLab",
            line_items=[
                {"description": "shell A", "l_code": "L3000",
                 "unit_price_cents": 1001, "quantity": 1, "discount_pct": 0.5},
                {"description": "shell B", "l_code": "L3000",
                 "unit_price_cents": 1001, "quantity": 1, "discount_pct": 0.5},
            ],
            units_drawn=1)
        assert_lab_order(lab)
        assert lab["total_cents"] == 1002

    def test_lab_total_persisted_on_read(self, api):
        """PRD §3.7: "Rounding each line before summing can differ from rounding
        the sum when two half-cent fractions both round up."
        PRD §3.7: "A read of a lab order exposes its `total_cents`."

        Design: Difficulty/combinatorial_formula/lab_order_total_round_per_line_then_sum
        """
        rx = self._setup_approved_orthotic_rx()
        lab = create_lab_order(
            rx["id"], lab_name="OrthoLab",
            line_items=[
                {"description": "shell A", "l_code": "L3000",
                 "unit_price_cents": 1001, "quantity": 1, "discount_pct": 0.5},
                {"description": "shell B", "l_code": "L3000",
                 "unit_price_cents": 1001, "quantity": 1, "discount_pct": 0.5},
            ],
            units_drawn=1)
        read = get_success_data(api.get_lab_order(lab["id"], FRONTDESK))
        # sum-then-round would be 1001; per-line-then-sum is 1002.
        assert read["total_cents"] == 1002


# ─── boundary_precision_check / routine_frequency_gap_exactly_61_is_covered ─
# Also owns Corner/state_machines/error_routine_frequency_gap_61_covered (stub).
class TestFrequencyGapBoundary:
    """Gap exactly 61 days is COVERED (inclusive boundary)."""

    def _diabetic_with_last_covered_april1(self):
        set_clock("2026-04-01T08:00:00Z")
        practice, provider, patient = setup_practice_provider_patient(
            patient_overrides={"has_diabetes_mellitus": True})
        establish_last_covered_routine_date(patient["id"], provider["id"], "2026-04-01")
        return practice, provider, patient

    def test_gap_exactly_61_is_covered(self, api):
        """PRD §3.4: "The boundary is inclusive: a gap exactly equal to the
        minimum interval is covered."

        Design: Difficulty/boundary_precision_check/routine_frequency_gap_exactly_61_is_covered
        """
        practice, provider, patient = self._diabetic_with_last_covered_april1()
        set_clock("2026-06-01T08:00:00Z")
        coded, proc = setup_coded_encounter(
            patient["id"], provider["id"],
            encounter_overrides={"scheduled_start": "2026-06-01T09:00:00Z",
                                 "scheduled_end": "2026-06-01T09:30:00Z"},
            procedure_overrides={"procedure_kind": "ROUTINE_NAIL_DEBRIDEMENT",
                                 "service_date": "2026-06-01",
                                 "billed_cents": 8000, "fee_cap_cents": 7000})
        assert proc["coverage_decision"] == "COVERED"
        assert proc["medicare_pays_cents"] == 5600

    def test_gap_exactly_61_covered_payer_split(self, api):
        """PRD §3.4: "the procedure is `COVERED` when that gap is at least the
        practice's `routine_care_min_interval_days`"
        PRD §3.5: "the payer portion (`medicare_pays_cents`) is the allowed
        amount multiplied by the practice's `fee_split_medicare_pct`, rounded
        half up to whole cents, and the patient portion (`patient_resp_cents`)
        is the exact remainder — the allowed amount minus the payer portion."

        Design: Difficulty/boundary_precision_check/routine_frequency_gap_exactly_61_is_covered
        """
        practice, provider, patient = self._diabetic_with_last_covered_april1()
        set_clock("2026-06-01T08:00:00Z")
        coded, proc = setup_coded_encounter(
            patient["id"], provider["id"],
            encounter_overrides={"scheduled_start": "2026-06-01T09:00:00Z",
                                 "scheduled_end": "2026-06-01T09:30:00Z"},
            procedure_overrides={"procedure_kind": "ROUTINE_NAIL_DEBRIDEMENT",
                                 "service_date": "2026-06-01",
                                 "billed_cents": 8000, "fee_cap_cents": 7000})
        # allowed = min(8000,7000)=7000; covered -> payer round_half_up(5600)=5600, patient 1400.
        assert proc["coverage_decision"] == "COVERED"
        assert proc["patient_resp_cents"] == 1400


# ─── calculations / covered_split_round_half_up_payer_portion ──────────────
def test_covered_split_round_half_up_payer_portion(api):
    """PRD §2.8: "the system rounds half up."
    PRD §3.5: "the payer portion (`medicare_pays_cents`) is the allowed amount
    multiplied by the practice's `fee_split_medicare_pct`, rounded half up to
    whole cents, and the patient portion (`patient_resp_cents`) is the exact
    remainder — the allowed amount minus the payer portion."

    Design: Corner/calculations/covered_split_round_half_up_payer_portion
    """
    set_clock("2026-06-01T09:00:00Z")
    practice, provider, patient = setup_practice_provider_patient(
        patient_overrides={"has_diabetes_mellitus": True})
    # Exam-only encounter, allowed = min(10001, 12000) = 10001 at 0.80 -> 8000.8 -> 8001.
    coded, _ = setup_coded_encounter(
        patient["id"], provider["id"],
        encounter_overrides={"exam_billed_cents": 10001, "exam_fee_cap_cents": 12000})
    assert coded["total_medicare_pays_cents"] == 8001
    assert coded["total_patient_resp_cents"] == 2000


# ─── calculations / non_routine_wound_debridement_always_covered_no_dx ─────
def test_non_routine_wound_debridement_covered_without_dx(api):
    """PRD §3.4: "A non-routine procedure is always `COVERED`."
    PRD §3.4: "a derived `is_routine` flag is set true exactly when
    `procedure_kind` is one of `ROUTINE_NAIL_DEBRIDEMENT` or
    `ROUTINE_CALLUS_PARING`. The other two kinds, `WOUND_DEBRIDEMENT` and
    `NAIL_AVULSION`, are non-routine."

    Design: Corner/calculations/non_routine_wound_debridement_always_covered_no_dx
    """
    set_clock("2026-06-01T09:00:00Z")
    practice, provider, patient = setup_practice_provider_patient(
        patient_overrides={"has_diabetes_mellitus": False})
    coded, proc = setup_coded_encounter(
        patient["id"], provider["id"],
        procedure_overrides={"procedure_kind": "WOUND_DEBRIDEMENT",
                             "service_date": "2026-06-01",
                             "billed_cents": 9000, "fee_cap_cents": 7000})
    assert proc["coverage_decision"] == "COVERED"
    assert proc["is_routine"] is False
    # allowed = min(9000,7000)=7000 at 0.80 -> payer 5600.
    assert proc["medicare_pays_cents"] == 5600


# ─── consistency_model / immediate_consistency_code_visible_in_response ────
def test_code_response_carries_computed_totals_immediately(api):
    """PRD §3.3: "Coding, performed by a `BillingSpecialist`, advances
    `EXAM_DONE → CODED` and is where all financial computation happens"
    PRD §3.3: "the encounter's `total_medicare_pays_cents` and
    `total_patient_resp_cents` are recomputed as the sums of the per-line payer
    and patient amounts across the exam line and all procedures."

    Design: Corner/consistency_model/immediate_consistency_code_visible_in_response
    """
    set_clock("2026-06-01T09:00:00Z")
    practice, provider, patient = setup_practice_provider_patient(
        patient_overrides={"has_diabetes_mellitus": True})
    enc, _ = setup_encounter_in_exam_done(
        patient["id"], provider["id"],
        encounter_overrides={"exam_billed_cents": 12000, "exam_fee_cap_cents": 10000})
    res = api.code_encounter(enc["id"], BILLING)
    coded = validate_success(res, 200)
    # exam allowed = min(12000,10000)=10000 covered -> payer 8000, patient 2000.
    assert coded["total_medicare_pays_cents"] == 8000
    assert coded["total_patient_resp_cents"] == 2000
