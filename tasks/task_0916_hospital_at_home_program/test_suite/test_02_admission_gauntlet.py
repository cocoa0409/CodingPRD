"""The seven screening rules that stand between a referral and admission."""

from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import ADMITTING_PHYSICIAN


def _read_referral(api, referral_id):
    return validate_success(api.get_referral(referral_id, ADMITTING_PHYSICIAN))


# ─── Service-radius boundary ───────────────────────────────────────────────

def test_home_exactly_forty_km_from_the_hub_passes_the_radius_rule(api):
    """PRD §3.1: "The patient's `home_distance_km` must lie within the program's
    forty-kilometre service radius. The bound is inclusive at the top: a home
    exactly 40.0 km from the hub passes, a home 40.1 km away is refused with
    `ERR_OUTSIDE_SERVICE_RADIUS`."
    PRD §3.1: "When all seven pass, the referral moves `SCREENING → ELIGIBLE`,
    `first_failed_gauntlet_rung` is cleared back to null, and the referral's
    `version` advances by 1."

    Design: Difficulty/boundary_precision_check/service_radius_inclusive_at_40km_and_exclusive_at_40_1km
    """
    parts = fx.setup_screening_referral(
        patient_overrides={
            "mrn": "MRN-AT",
            "full_name": "Ada AtBound",
            "home_distance_km": 40.0,
            "primary_diagnosis_code": "CHF_EXAC",
            "diet_restriction": "NONE",
            "broadband_verified": True,
            "caregiver_present": True,
        }
    )

    data = validate_success(
        api.mark_referral_eligible(parts["referral"]["id"], ADMITTING_PHYSICIAN)
    )
    assert data["status"] == "ELIGIBLE", (
        f"40.0 km sits on the inclusive bound and must pass, got {data['status']}"
    )
    assert data["first_failed_gauntlet_rung"] is None, (
        "a clean pass clears first_failed_gauntlet_rung back to null"
    )


def test_home_at_forty_point_one_km_is_outside_the_service_radius(api):
    """PRD §3.1: "The patient's `home_distance_km` must lie within the program's
    forty-kilometre service radius. The bound is inclusive at the top: a home
    exactly 40.0 km from the hub passes, a home 40.1 km away is refused with
    `ERR_OUTSIDE_SERVICE_RADIUS`."
    PRD §3.1: "When any rule fails, the response carries that rule's error
    identifier at HTTP 422, the referral **stays** in `SCREENING` so the
    physician can fix the underlying fact and retry, and the referral's
    `first_failed_gauntlet_rung` is written with the error identifier of the
    highest-priority rule that failed — the same string the caller just received
    — so that the rejection remains observable on the record afterward."

    Design: Difficulty/boundary_precision_check/service_radius_inclusive_at_40km_and_exclusive_at_40_1km
    """
    parts = fx.setup_screening_referral(
        patient_overrides={
            "mrn": "MRN-OV",
            "full_name": "Otto OverBound",
            "home_distance_km": 40.1,
            "primary_diagnosis_code": "CHF_EXAC",
            "diet_restriction": "NONE",
            "broadband_verified": True,
            "caregiver_present": True,
        }
    )
    referral_id = parts["referral"]["id"]

    validate_error(
        api.mark_referral_eligible(referral_id, ADMITTING_PHYSICIAN),
        ApiErrorId.ERR_OUTSIDE_SERVICE_RADIUS.value,
    )

    referral = _read_referral(api, referral_id)
    assert referral["status"] == "SCREENING", (
        f"a failed gauntlet leaves the referral in SCREENING, got {referral['status']}"
    )
    assert referral["first_failed_gauntlet_rung"] == "ERR_OUTSIDE_SERVICE_RADIUS", (
        "the failing rule's identifier must remain observable on the referral"
    )


# ─── Rule ordering and the individual rungs ────────────────────────────────

def test_origin_rule_wins_over_every_later_gauntlet_failure(api):
    """PRD §3.1: "The system then runs seven eligibility rules against the
    latest-created assessment, **in this exact order**, stopping at the first
    failure:"
    PRD §3.1: "The referral's `origin` must be either `ED` or `INPATIENT_WARD`. A
    referral arriving from `CLINIC` or from `SNF` is not eligible for home
    hospitalization and is refused with `ERR_REFERRAL_ORIGIN_INELIGIBLE`."

    Design: Corner/validations/gauntlet_origin_rung_wins_over_condition_safety_connectivity_and_consent
    """
    parts = fx.setup_screening_referral(
        patient_overrides={
            "mrn": "MRN-GT",
            "full_name": "Gus Gauntlet",
            "home_distance_km": 60.0,
            "primary_diagnosis_code": "OTHER",
            "diet_restriction": "NONE",
            "broadband_verified": False,
            "caregiver_present": False,
        },
        referral_overrides={
            "origin": "CLINIC",
            "qualifying_condition_code": "OTHER",
            "acuity": "HIGH",
        },
        assessment_overrides={
            "home_safety_outcome": "FAIL",
            "broadband_check": "FAIL",
            "caregiver_present_confirmed": False,
            "consent_signed": False,
        },
    )
    referral_id = parts["referral"]["id"]

    error = validate_error(
        api.mark_referral_eligible(referral_id, ADMITTING_PHYSICIAN),
        ApiErrorId.ERR_REFERRAL_ORIGIN_INELIGIBLE.value,
    )
    assert error["error_id"] not in (
        "ERR_CONDITION_NOT_QUALIFYING",
        "ERR_OUTSIDE_SERVICE_RADIUS",
        "ERR_HOME_SAFETY_FAILED",
        "ERR_CONNECTIVITY_INSUFFICIENT",
        "ERR_CAREGIVER_REQUIRED",
        "ERR_CONSENT_MISSING",
    )

    referral = _read_referral(api, referral_id)
    assert referral["status"] == "SCREENING"
    assert referral["first_failed_gauntlet_rung"] == "ERR_REFERRAL_ORIGIN_INELIGIBLE"


def test_qualifying_condition_other_never_qualifies(api):
    """PRD §3.1: "The referral's `qualifying_condition_code` must be one of the
    six qualifying conditions: `CHF_EXAC`, `COPD_EXAC`, `CAP_PNEUMONIA`,
    `CELLULITIS`, `UTI_COMPLICATED` or `COVID_MODERATE`. The seventh legal enum
    value, `OTHER`, is accepted by the schema but never qualifies, and referrals
    claiming it are refused with `ERR_CONDITION_NOT_QUALIFYING`."

    Design: Corner/validations/qualifying_condition_other_is_rejected_while_origin_and_radius_pass
    """
    parts = fx.setup_screening_referral(
        patient_overrides={
            "mrn": "MRN-OT",
            "full_name": "Ora Other",
            "home_distance_km": 5.0,
            "primary_diagnosis_code": "OTHER",
            "diet_restriction": "NONE",
            "broadband_verified": True,
            "caregiver_present": True,
        },
        referral_overrides={"origin": "ED", "qualifying_condition_code": "OTHER"},
    )
    referral_id = parts["referral"]["id"]

    validate_error(
        api.mark_referral_eligible(referral_id, ADMITTING_PHYSICIAN),
        ApiErrorId.ERR_CONDITION_NOT_QUALIFYING.value,
    )
    referral = _read_referral(api, referral_id)
    assert referral["first_failed_gauntlet_rung"] == "ERR_CONDITION_NOT_QUALIFYING"


def test_conditional_home_safety_outcome_is_rejected_like_an_outright_fail(api):
    """PRD §3.1: "The latest assessment's `home_safety_outcome` must be `PASS`.
    Both `CONDITIONAL` and `FAIL` are rejections here — a conditional pass is not
    a pass — and both yield `ERR_HOME_SAFETY_FAILED`."

    Design: Corner/validations/conditional_home_safety_outcome_is_rejected_like_an_outright_fail
    """
    parts = fx.setup_screening_referral(
        patient_overrides={
            "mrn": "MRN-HS",
            "full_name": "Hana Safety",
            "home_distance_km": 5.0,
            "primary_diagnosis_code": "CELLULITIS",
            "diet_restriction": "NONE",
            "broadband_verified": True,
            "caregiver_present": True,
        },
        referral_overrides={
            "origin": "ED",
            "qualifying_condition_code": "CELLULITIS",
        },
        assessment_overrides={"home_safety_outcome": "CONDITIONAL"},
    )
    referral_id = parts["referral"]["id"]

    validate_error(
        api.mark_referral_eligible(referral_id, ADMITTING_PHYSICIAN),
        ApiErrorId.ERR_HOME_SAFETY_FAILED.value,
    )
    assert _read_referral(api, referral_id)["status"] == "SCREENING"


def test_failed_broadband_check_returns_connectivity_insufficient(api):
    """PRD §3.1: "The latest assessment's `broadband_check` must be `PASS`; a
    `FAIL` yields `ERR_CONNECTIVITY_INSUFFICIENT`, because a virtual ward without
    connectivity is not a ward."

    Design: Corner/validations/broadband_check_failure_returns_connectivity_insufficient
    """
    parts = fx.setup_screening_referral(
        patient_overrides={
            "mrn": "MRN-BB",
            "full_name": "Bo Broadband",
            "home_distance_km": 5.0,
            "primary_diagnosis_code": "COPD_EXAC",
            "diet_restriction": "NONE",
            "broadband_verified": False,
            "caregiver_present": True,
        },
        referral_overrides={"origin": "ED", "qualifying_condition_code": "COPD_EXAC"},
        assessment_overrides={"home_safety_outcome": "PASS", "broadband_check": "FAIL"},
    )

    validate_error(
        api.mark_referral_eligible(parts["referral"]["id"], ADMITTING_PHYSICIAN),
        ApiErrorId.ERR_CONNECTIVITY_INSUFFICIENT.value,
    )


def test_caregiver_rule_applies_only_to_high_acuity_referrals(api):
    """PRD §3.1: "When the referral's `acuity` is `HIGH`, **both** the patient
    record's `caregiver_present` flag and the latest assessment's
    `caregiver_present_confirmed` flag must be true; if either is false the
    referral is refused with `ERR_CAREGIVER_REQUIRED`. A referral whose `acuity`
    is `STANDARD` skips this rule entirely — no caregiver is required and neither
    flag is consulted."

    Design: Corner/validations/high_acuity_without_caregiver_returns_caregiver_required_but_standard_passes
    """
    high = fx.setup_screening_referral(
        patient_overrides={
            "mrn": "MRN-CH",
            "full_name": "Cal Caregiver High",
            "home_distance_km": 5.0,
            "primary_diagnosis_code": "CHF_EXAC",
            "diet_restriction": "NONE",
            "broadband_verified": True,
            "caregiver_present": False,
        },
        referral_overrides={"acuity": "HIGH"},
        assessment_overrides={"caregiver_present_confirmed": False},
    )
    standard = fx.setup_screening_referral(
        set_the_clock=False,
        patient_overrides={
            "mrn": "MRN-CS",
            "full_name": "Cleo Caregiver Std",
            "home_distance_km": 5.0,
            "primary_diagnosis_code": "CHF_EXAC",
            "diet_restriction": "NONE",
            "broadband_verified": True,
            "caregiver_present": False,
        },
        referral_overrides={"acuity": "STANDARD"},
        assessment_overrides={"caregiver_present_confirmed": False},
    )

    validate_error(
        api.mark_referral_eligible(high["referral"]["id"], ADMITTING_PHYSICIAN),
        ApiErrorId.ERR_CAREGIVER_REQUIRED.value,
    )
    assert _read_referral(api, high["referral"]["id"])["status"] == "SCREENING"

    passed = validate_success(
        api.mark_referral_eligible(standard["referral"]["id"], ADMITTING_PHYSICIAN)
    )
    assert passed["status"] == "ELIGIBLE", (
        "a STANDARD referral skips the caregiver rule entirely"
    )


def test_unsigned_consent_is_the_last_gauntlet_rung(api):
    """PRD §3.1: "The latest assessment's `consent_signed` must be true;
    otherwise `ERR_CONSENT_MISSING`."
    PRD §3.1: "When any rule fails, the response carries that rule's error
    identifier at HTTP 422, the referral **stays** in `SCREENING` so the
    physician can fix the underlying fact and retry, and the referral's
    `first_failed_gauntlet_rung` is written with the error identifier of the
    highest-priority rule that failed — the same string the caller just received
    — so that the rejection remains observable on the record afterward."

    Design: Corner/validations/unsigned_consent_returns_consent_missing_as_the_last_gauntlet_rung
    """
    parts = fx.setup_screening_referral(
        patient_overrides={
            "mrn": "MRN-CN",
            "full_name": "Cid Consent",
            "home_distance_km": 5.0,
            "primary_diagnosis_code": "UTI_COMPLICATED",
            "diet_restriction": "NONE",
            "broadband_verified": True,
            "caregiver_present": True,
        },
        referral_overrides={
            "origin": "INPATIENT_WARD",
            "qualifying_condition_code": "UTI_COMPLICATED",
        },
        assessment_overrides={"consent_signed": False},
    )
    referral_id = parts["referral"]["id"]

    validate_error(
        api.mark_referral_eligible(referral_id, ADMITTING_PHYSICIAN),
        ApiErrorId.ERR_CONSENT_MISSING.value,
    )
    assert (
        _read_referral(api, referral_id)["first_failed_gauntlet_rung"]
        == "ERR_CONSENT_MISSING"
    )


def test_marking_an_already_eligible_referral_again_is_rejected(api):
    """PRD §3.1: "The referral must currently be in `SCREENING` — a referral
    still in `SUBMITTED`, already `ELIGIBLE`, already `ADMITTED` or `CLOSED` is
    refused with `ERR_INVALID_STATE` — and at least one assessment must exist for
    it."

    Design: Corner/state_machines/referral_mark_eligible_twice_is_rejected_on_the_second_call
    """
    parts = fx.setup_eligible_referral(mrn="MRN-ID", full_name="Ike Idem")
    referral = parts["referral"]
    assert referral["status"] == "ELIGIBLE"
    version_after_first = referral["version"]

    validate_error(
        api.mark_referral_eligible(referral["id"], ADMITTING_PHYSICIAN),
        ApiErrorId.ERR_INVALID_STATE.value,
    )

    unchanged = _read_referral(api, referral["id"])
    assert unchanged["status"] == "ELIGIBLE"
    assert unchanged["version"] == version_after_first, (
        "a rejected mark-eligible must not mutate the referral row"
    )
