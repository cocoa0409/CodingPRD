"""Calculation rules: infectious window, quarantine end, priority score,
isolation end, completeness score.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula, and the
priority_band boundary instance of boundary_precision_check.
Queue B (Corner): the calculations section instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    make_investigator_headers,
    make_tracer_headers,
    make_intake_headers,
    create_contact_payload,
    create_case_payload,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Queue A — dual_variant_calc
# ===========================================================================
class TestInfectiousWindowDualVariant:
    """The infectious window anchors on symptom_onset_date when symptomatic and on
    specimen_collection_date when asymptomatic, producing different windows."""

    def _setup(self):
        program, jurisdiction, _ = fx.setup_program_jurisdiction_condition(
            condition_overrides={"presymptomatic_days": 2, "infectious_tail_days": 10}
        )
        j = jurisdiction["id"]
        cs = fx.open_and_interview_case(
            program["id"], j,
            case_overrides={
                "patient_reference": "PT-S",
                "symptom_onset_date": "2026-03-10T00:00:00.000Z",
                "is_symptomatic": True,
            },
        )
        ca = fx.open_and_interview_case(
            program["id"], j,
            case_overrides={
                "patient_reference": "PT-A",
                "symptom_onset_date": None,
                "specimen_collection_date": "2026-03-12T00:00:00.000Z",
                "is_symptomatic": False,
            },
        )
        return j, cs, ca

    def test_symptomatic_window_anchors_on_onset(self, api):
        """PRD §3.3: "When the case is symptomatic, the anchor date is `symptom_onset_date`;
        when it is asymptomatic, the anchor date is `specimen_collection_date`."
        PRD §3.3: "The `infectious_start_date` is the anchor shifted earlier by
        `presymptomatic_days` days, and the `infectious_end_date` is the anchor shifted
        later by `infectious_tail_days` days; both are stored as UTC-midnight datetimes."

        Design: Difficulty/dual_variant_calc/infectious_window_symptom_vs_specimen_on_case
        """
        j, cs, _ = self._setup()
        data = validate_success(api.get_case(cs["id"], make_investigator_headers(j)))
        assert data["infectious_start_date"] == "2026-03-08T00:00:00.000Z", data["infectious_start_date"]
        assert data["infectious_end_date"] == "2026-03-20T00:00:00.000Z", data["infectious_end_date"]

    def test_asymptomatic_window_anchors_on_specimen(self, api):
        """PRD §3.3: "When the case is symptomatic, the anchor date is `symptom_onset_date`;
        when it is asymptomatic, the anchor date is `specimen_collection_date`."
        PRD §3.3: "Because the symptomatic and asymptomatic variants anchor on different dates,
        the same calendar inputs can yield a different window depending on `is_symptomatic`."

        Design: Difficulty/dual_variant_calc/infectious_window_symptom_vs_specimen_on_case
        """
        j, _, ca = self._setup()
        data = validate_success(api.get_case(ca["id"], make_investigator_headers(j)))
        assert data["infectious_start_date"] == "2026-03-10T00:00:00.000Z", data["infectious_start_date"]
        assert data["infectious_end_date"] == "2026-03-22T00:00:00.000Z", data["infectious_end_date"]


class TestQuarantineEndDualVariant:
    """Quarantine end is computed on the STANDARD basis at elicitation and recomputed on
    the TEST_BASED basis once a qualifying negative test exists."""

    def _setup(self):
        program, jurisdiction, _ = fx.setup_program_jurisdiction_condition(
            condition_overrides={
                "quarantine_days": 14, "test_based_release_days": 7,
                "test_release_earliest_offset_days": 5,
            }
        )
        j = jurisdiction["id"]
        ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
        kstd = fx.elicit_contact(
            program["id"], ci["id"], j,
            contact_reference="K-STD", last_exposure_date="2026-03-15T00:00:00.000Z",
        )
        ktst = fx.elicit_contact(
            program["id"], ci["id"], j,
            contact_reference="K-TST", last_exposure_date="2026-03-15T00:00:00.000Z",
        )
        api_client.record_qualifying_test(
            ktst["id"],
            {"result_value": "NEGATIVE", "specimen_collection_date": "2026-03-20T00:00:00.000Z"},
            make_tracer_headers(j),
        )
        return j, kstd, ktst

    def test_standard_basis_quarantine_end(self, api):
        """PRD §3.7: "the standard quarantine end is the contact's `last_exposure_date` plus
        `quarantine_days` days, and this STANDARD computation sets `quarantine_release_basis`
        to `STANDARD` and writes `quarantine_end_date`."

        Design: Difficulty/dual_variant_calc/quarantine_end_standard_vs_test_based_on_contact
        """
        j, kstd, _ = self._setup()
        data = validate_success(api.get_contact(kstd["id"], make_tracer_headers(j)))
        assert data["quarantine_release_basis"] == "STANDARD"
        assert data["quarantine_end_date"] == "2026-03-29T00:00:00.000Z", data["quarantine_end_date"]

    def test_test_based_basis_quarantine_end(self, api):
        """PRD §3.7: "When a qualifying negative test exists, the quarantine is recomputed on
        the test-based basis: `quarantine_release_basis` becomes `TEST_BASED` and
        `quarantine_end_date` becomes the `last_exposure_date` plus `test_based_release_days`
        days, which (because `test_based_release_days` does not exceed `quarantine_days`) is
        the same as or earlier than the standard end for the same `last_exposure_date`."

        Design: Difficulty/dual_variant_calc/quarantine_end_standard_vs_test_based_on_contact
        """
        j, _, ktst = self._setup()
        data = validate_success(api.get_contact(ktst["id"], make_tracer_headers(j)))
        assert data["quarantine_release_basis"] == "TEST_BASED"
        assert data["quarantine_end_date"] == "2026-03-22T00:00:00.000Z", data["quarantine_end_date"]


# ===========================================================================
# Queue A — combinatorial_formula
# ===========================================================================
class TestContactPriorityScoreCombinatorial:
    """Priority score combines base + proximity + duration + vulnerability, clamped 0..100."""

    def test_priority_score_clamps_to_100(self, api):
        """PRD §3.6: "The raw sum of base, proximity, duration, and vulnerability is then
        clamped into the inclusive range 0 to 100 to produce the integer `priority_score`."
        PRD §3.6: "The score begins from a base determined by `exposure_setting`: 50 for
        `HOUSEHOLD`, 40 for `HEALTHCARE`, 25 for `WORKPLACE`, 15 for `SOCIAL`, and 10 for
        `COMMUNITY`."

        Design: Difficulty/combinatorial_formula/contact_priority_score_multifactor_clamp_mode_a
        """
        program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
        j = jurisdiction["id"]
        ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
        res = api.create_contact(
            create_contact_payload(
                program["id"], ci["id"], j,
                contact_reference="K-MAX", exposure_setting="HOUSEHOLD",
                proximity_meters=0.5, cumulative_exposure_minutes=30,
                is_high_risk_contact=True, last_exposure_date="2026-03-15T00:00:00.000Z",
            ),
            make_tracer_headers(j),
        )
        data = validate_success(res, expected_status=201)
        assert data["priority_score"] == 100, data["priority_score"]
        assert data["priority_band"] == "HIGH"

    def test_priority_band_high_when_clamped(self, api):
        """PRD §3.6: "The `priority_band` is derived from the score: `HIGH` when `priority_score`
        is at least 70, `MEDIUM` when it is at least 40 (but below 70), and `LOW` otherwise."

        Design: Difficulty/combinatorial_formula/contact_priority_score_multifactor_clamp_mode_a
        """
        program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
        j = jurisdiction["id"]
        ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
        res = api.create_contact(
            create_contact_payload(
                program["id"], ci["id"], j,
                contact_reference="K-MAX2", exposure_setting="HOUSEHOLD",
                proximity_meters=0.5, cumulative_exposure_minutes=30,
                is_high_risk_contact=True, last_exposure_date="2026-03-15T00:00:00.000Z",
            ),
            make_tracer_headers(j),
        )
        data = validate_success(res, expected_status=201)
        assert data["priority_band"] == "HIGH", data["priority_band"]


class TestIsolationEndMaxPrecedence:
    """isolation_end_date is the later (max) of the minimum end and the symptom-resolution
    end when the case is symptomatic with a last_symptomatic_date."""

    def _classify_confirmed_with_last_symptomatic(self):
        program, jurisdiction, _ = fx.setup_program_jurisdiction_condition(
            condition_overrides={
                "isolation_min_days": 5, "fever_free_days": 1, "requires_lab_confirmation": True,
            }
        )
        j = jurisdiction["id"]
        case = fx.open_and_interview_case(
            program["id"], j,
            case_overrides={
                "patient_reference": "PT-X",
                "symptom_onset_date": "2026-03-10T00:00:00.000Z",
                "last_symptomatic_date": "2026-03-18T00:00:00.000Z",
                "is_symptomatic": True,
            },
        )
        lab = fx.intake_lab(
            program["id"], j, patient_reference="PT-X", result_value="POSITIVE",
            specimen_collection_date="2026-03-11T00:00:00.000Z",
        )
        if lab.get("status") != "LINKED":
            fx.link_lab_to_case(case["id"], j, lab["id"])
        return j, case

    def test_classify_confirmed_succeeds(self, api):
        """PRD §3.4: "A successful classify advances the case `UNDER_INVESTIGATION → CLASSIFIED`,
        sets `classification` to the requested value, and recomputes the completeness score."

        Design: Difficulty/combinatorial_formula/isolation_end_max_precedence_mode_c
        """
        j, case = self._classify_confirmed_with_last_symptomatic()
        data = validate_success(
            api.classify_case(case["id"], {"classification": "CONFIRMED"}, make_investigator_headers(j))
        )
        assert data["classification"] == "CONFIRMED"

    def test_isolation_end_selects_later_candidate(self, api):
        """PRD §3.4: "the minimum end is that anchor plus `isolation_min_days` days, and if a
        `last_symptomatic_date` is present a symptom-resolution end is computed as that date plus
        `fever_free_days` days, with `isolation_end_date` taking whichever of the minimum end and
        the symptom-resolution end falls later."

        Design: Difficulty/combinatorial_formula/isolation_end_max_precedence_mode_c
        """
        j, case = self._classify_confirmed_with_last_symptomatic()
        data = validate_success(
            api.classify_case(case["id"], {"classification": "CONFIRMED"}, make_investigator_headers(j))
        )
        # min_end = 2026-03-10 + 5 = 2026-03-15 ; symptom_end = 2026-03-18 + 1 = 2026-03-19 ; max = 03-19
        assert data["isolation_end_date"] == "2026-03-19T00:00:00.000Z", data["isolation_end_date"]


# ===========================================================================
# Queue A — boundary_precision_check / priority_band_inclusive_at_score_40
# ===========================================================================
class TestPriorityBandBoundaryAt40:
    """The MEDIUM band threshold uses an inclusive >= 40; a score of exactly 40 is MEDIUM
    while 35 is LOW."""

    def _setup(self):
        program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
        j = jurisdiction["id"]
        ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
        return program["id"], j, ci["id"]

    def test_score_40_lands_medium(self, api):
        """PRD §3.6: "The `priority_band` is derived from the score: `HIGH` when `priority_score`
        is at least 70, `MEDIUM` when it is at least 40 (but below 70), and `LOW` otherwise."

        Design: Difficulty/boundary_precision_check/priority_band_inclusive_at_score_40
        """
        pid, j, cid = self._setup()
        # WORKPLACE 25 + proximity 1.5m (<=2) 10 + duration 10min (>=5) 5 = 40
        res = api.create_contact(
            create_contact_payload(
                pid, cid, j, contact_reference="K-40", exposure_setting="WORKPLACE",
                proximity_meters=1.5, cumulative_exposure_minutes=10,
                last_exposure_date="2026-03-15T00:00:00.000Z",
            ),
            make_tracer_headers(j),
        )
        data = validate_success(res, expected_status=201)
        assert data["priority_score"] == 40, data["priority_score"]
        assert data["priority_band"] == "MEDIUM", data["priority_band"]

    def test_score_35_lands_low(self, api):
        """PRD §3.6: "A duration bonus is added: 15 points when `cumulative_exposure_minutes` is
        at least 15, 5 points when it is at least 5 (but below 15), and 0 points otherwise."
        PRD §3.6: "The `priority_band` is derived from the score: `HIGH` when `priority_score`
        is at least 70, `MEDIUM` when it is at least 40 (but below 70), and `LOW` otherwise."

        Design: Difficulty/boundary_precision_check/priority_band_inclusive_at_score_40
        """
        pid, j, cid = self._setup()
        # WORKPLACE 25 + proximity 1.5m 10 + duration 2min (<5) 0 = 35
        res = api.create_contact(
            create_contact_payload(
                pid, cid, j, contact_reference="K-35", exposure_setting="WORKPLACE",
                proximity_meters=1.5, cumulative_exposure_minutes=2,
                last_exposure_date="2026-03-15T00:00:00.000Z",
            ),
            make_tracer_headers(j),
        )
        data = validate_success(res, expected_status=201)
        assert data["priority_score"] == 35, data["priority_score"]
        assert data["priority_band"] == "LOW", data["priority_band"]


# ===========================================================================
# Queue B — calculations section
# ===========================================================================
def test_completeness_score_full_stack_reaches_100(api):
    """PRD §3.5: "Forty points are added when `interview_completed` is true. Twenty points are
    added when both `infectious_start_date` and `infectious_end_date` are present. Twenty points
    are added when the case's `contact_count` is at least 1. Twenty points are added when the
    case has at least one linked positive lab result, or equivalently when the case has at least
    one `LINKED` lab result whose `linked_case_id` references it."

    Design: Corner/calculations/completeness_score_full_stack_reaches_100
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    cf = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-F"})
    fx.elicit_contact(program["id"], cf["id"], j, contact_reference="K-F")
    lab = fx.intake_lab(program["id"], j, patient_reference="PT-F", result_value="POSITIVE")
    if lab.get("status") != "LINKED":
        fx.link_lab_to_case(cf["id"], j, lab["id"])
    data = validate_success(api.get_case(cf["id"], make_investigator_headers(j)))
    assert data["completeness_score"] == 100, data["completeness_score"]
    assert data["contact_count"] == 1
    assert data["linked_positive_count"] == 1


def test_priority_score_community_floor_band_low(api):
    """PRD §3.6: "The score begins from a base determined by `exposure_setting`: 50 for
    `HOUSEHOLD`, 40 for `HEALTHCARE`, 25 for `WORKPLACE`, 15 for `SOCIAL`, and 10 for
    `COMMUNITY`."
    PRD §3.6: "A proximity bonus is added: 20 points when `proximity_meters` is less than 1,
    10 points when `proximity_meters` is at most 2 (but not less than 1), and 0 points otherwise."

    Design: Corner/calculations/priority_score_community_floor_band_low
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
    res = api.create_contact(
        create_contact_payload(
            program["id"], ci["id"], j, contact_reference="K-LOW",
            exposure_setting="COMMUNITY", proximity_meters=3, cumulative_exposure_minutes=2,
            last_exposure_date="2026-03-15T00:00:00.000Z",
        ),
        make_tracer_headers(j),
    )
    data = validate_success(res, expected_status=201)
    assert data["priority_score"] == 10, data["priority_score"]
    assert data["priority_band"] == "LOW"


def test_priority_band_high_inclusive_at_score_70(api):
    """PRD §3.6: "The `priority_band` is derived from the score: `HIGH` when `priority_score`
    is at least 70, `MEDIUM` when it is at least 40 (but below 70), and `LOW` otherwise."

    Design: Corner/calculations/priority_band_high_inclusive_at_score_70
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
    # HOUSEHOLD 50 + near<1m 20 + duration 2min 0 = 70
    res = api.create_contact(
        create_contact_payload(
            program["id"], ci["id"], j, contact_reference="K-70",
            exposure_setting="HOUSEHOLD", proximity_meters=0.5, cumulative_exposure_minutes=2,
            last_exposure_date="2026-03-15T00:00:00.000Z",
        ),
        make_tracer_headers(j),
    )
    data = validate_success(res, expected_status=201)
    assert data["priority_score"] == 70, data["priority_score"]
    assert data["priority_band"] == "HIGH"


def test_isolation_end_asymptomatic_specimen_anchor(api):
    """PRD §3.4: "When the case is asymptomatic, the anchor is `specimen_collection_date` and
    `isolation_end_date` is simply that anchor plus `isolation_min_days` days."

    Design: Corner/calculations/isolation_end_asymptomatic_specimen_anchor
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition(
        condition_overrides={"isolation_min_days": 5, "requires_lab_confirmation": False}
    )
    j = jurisdiction["id"]
    cai = fx.open_and_interview_case(
        program["id"], j,
        case_overrides={
            "patient_reference": "PT-AI",
            "symptom_onset_date": None,
            "specimen_collection_date": "2026-03-12T00:00:00.000Z",
            "is_symptomatic": False,
        },
    )
    data = validate_success(
        api.classify_case(cai["id"], {"classification": "CONFIRMED"}, make_investigator_headers(j))
    )
    assert data["classification"] == "CONFIRMED"
    assert data["isolation_end_date"] == "2026-03-17T00:00:00.000Z", data["isolation_end_date"]


def test_quarantine_test_not_counted_before_earliest_offset(api):
    """PRD §3.7: "A test qualifies — setting `has_qualifying_negative_test` to true — when its
    `result_value` is `NEGATIVE` and its `specimen_collection_date` is on or after that earliest
    qualifying date."
    PRD §3.7: "If no qualifying negative test exists, the quarantine stays on the standard basis."

    Design: Corner/calculations/quarantine_test_not_counted_before_earliest_offset
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition(
        condition_overrides={
            "quarantine_days": 14, "test_based_release_days": 7,
            "test_release_earliest_offset_days": 5,
        }
    )
    j = jurisdiction["id"]
    ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
    ke = fx.elicit_contact(
        program["id"], ci["id"], j, contact_reference="K-EARLY",
        last_exposure_date="2026-03-15T00:00:00.000Z",
    )
    # earliest qualifying = 2026-03-15 + 5 = 2026-03-20 ; specimen 2026-03-19 is one day too early
    api.record_qualifying_test(
        ke["id"],
        {"result_value": "NEGATIVE", "specimen_collection_date": "2026-03-19T00:00:00.000Z"},
        make_tracer_headers(j),
    )
    data = validate_success(api.get_contact(ke["id"], make_tracer_headers(j)))
    assert data["has_qualifying_negative_test"] is False
    assert data["quarantine_release_basis"] == "STANDARD"
    assert data["quarantine_end_date"] == "2026-03-29T00:00:00.000Z", data["quarantine_end_date"]
