"""Patient registration and the referral triage queue."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, assert_patient, assert_referral, assert_same_instant
from test_helpers import factories as f
from test_helpers.fixtures import (
    ADMIN,
    INTAKE,
    file_referral,
    read_patient,
    register_patient,
    set_clock,
)


# ---------------------------------------------------------------------------
# Triage variant divergence
# ---------------------------------------------------------------------------
def test_hospital_discharge_referral_scores_under_the_payer_sourced_variant(api):
    """PRD 3.1: "`triage_variant` is `PAYER_SOURCED` when the `source` is
    `HOSPITAL_DISCHARGE` or `PAYER`, and `CLINICIAN_SOURCED` for the other three
    sources."
    PRD 3.1: "Under the `PAYER_SOURCED` variant the score is the sum of three
    terms: a flat source weight worth 30 points for a `HOSPITAL_DISCHARGE`
    referral and 20 points for a `PAYER` referral; 12 points for each documented
    serious-illness criterion; and 4 points for each month of prognosis gap."

    Design: Difficulty/dual_variant_calc/referral_triage_variant_diverges_by_referral_source
    """
    patient = register_patient(
        clock="2026-06-01T00:00:00Z",
        full_name="Ada Kessler",
        date_of_birth="1948-03-11",
        opioid_status="OPIOID_TOLERANT",
    )

    response = api.create_referral(
        f.referral_payload(
            patient["id"],
            source="HOSPITAL_DISCHARGE",
            prognosis_months=6,
            serious_illness_criteria_count=3,
        ),
        INTAKE,
    )
    referral = validate_success(response, 201)
    assert_referral(referral)

    assert referral["triage_variant"] == "PAYER_SOURCED", (
        f"HOSPITAL_DISCHARGE must select PAYER_SOURCED, got {referral['triage_variant']}"
    )
    assert referral["triage_score"] == 90, (
        "30 source weight + 3*12 criteria + 6 months of gap * 4 = 90, "
        f"got {referral['triage_score']}"
    )
    assert referral["status"] == "RECEIVED"
    assert referral["re_referral_count"] == 0


def test_oncology_referral_scores_differently_from_an_identical_payer_sourced_one(api):
    """PRD 3.1: "Under the `CLINICIAN_SOURCED` variant there is no source weight
    at all, criteria are worth double — the same 12 points multiplied by 2, so 24
    points per criterion — and each month of prognosis gap is worth only 2
    points."
    PRD 3.1: "The consequence is deliberate: an identical
    `serious_illness_criteria_count` and `prognosis_months` produce a different
    `triage_score` depending on who sent the referral."

    Design: Difficulty/dual_variant_calc/referral_triage_variant_diverges_by_referral_source
    """
    patient = register_patient(clock="2026-06-01T00:00:00Z", full_name="Ada Kessler")

    payer_sourced = file_referral(
        patient["id"],
        source="HOSPITAL_DISCHARGE",
        prognosis_months=6,
        serious_illness_criteria_count=3,
    )
    clinician_sourced = validate_success(
        api.create_referral(
            f.referral_payload(
                patient["id"],
                source="ONCOLOGY",
                prognosis_months=6,
                serious_illness_criteria_count=3,
            ),
            INTAKE,
        ),
        201,
    )

    assert clinician_sourced["triage_variant"] == "CLINICIAN_SOURCED"
    assert clinician_sourced["triage_score"] == 84, (
        "3 criteria * 24 + 6 months of gap * 2 = 84, "
        f"got {clinician_sourced['triage_score']}"
    )
    assert payer_sourced["triage_score"] == 90
    assert payer_sourced["triage_score"] != clinician_sourced["triage_score"], (
        "identical inputs must score differently under the two variants"
    )


# ---------------------------------------------------------------------------
# Registration defaults
# ---------------------------------------------------------------------------
def test_patient_registration_returns_the_declared_default_field_set(api):
    """PRD 3.1: "Registration returns the new patient with `program_status`
    `REFERRED`, `capacity_status` `HAS_CAPACITY`, `code_status` `FULL_CODE`,
    `code_status_rank` 1, `records_frozen` false, `active_daily_mme` 0,
    `acp_minutes_claimed` 0, `acp_paid_cents_ytd` 0, `open_symptom_count` 0 and
    `version` 1."

    Design: Corner/entities/patient_creation_returns_the_full_default_field_set
    """
    set_clock("2026-06-01T00:00:00Z")

    response = api.create_patient(
        f.patient_payload(
            full_name="Ana Petrescu",
            date_of_birth="1950-01-01",
            jurisdiction_code="JUR_TWO_WITNESS",
            opioid_status="OPIOID_TOLERANT",
        ),
        INTAKE,
    )
    patient = validate_success(response, 201)
    assert_patient(patient)

    assert patient["program_status"] == "REFERRED"
    assert patient["capacity_status"] == "HAS_CAPACITY"
    assert patient["code_status"] == "FULL_CODE"
    assert patient["code_status_rank"] == 1
    assert patient["records_frozen"] is False
    assert float(patient["active_daily_mme"]) == 0
    assert patient["acp_minutes_claimed"] == 0
    assert patient["acp_paid_cents_ytd"] == 0
    assert patient["open_symptom_count"] == 0
    assert patient["version"] == 1
    assert_same_instant(
        patient["created_at"], "2026-06-01T00:00:00Z", "Patient.created_at"
    )


# ---------------------------------------------------------------------------
# The re-referral cycle
# ---------------------------------------------------------------------------
def test_third_re_referral_is_refused_once_the_cap_is_reached(api):
    """PRD 3.1: "`RE_REFER` is the cycle back. It applies to a referral in
    `DECLINED`, requires `re_referral_count` to be strictly below 2, and moves the
    referral `DECLINED → RECEIVED`."
    PRD 3.1: "Two re-referrals are therefore possible; a third is refused with
    `ERR_REREFERRAL_LIMIT`, because by then `re_referral_count` has reached the
    cap of 2."

    Design: Corner/state_machines/referral_re_referral_cycle_stops_at_the_declared_limit
    """
    patient = register_patient(clock="2026-06-01T00:00:00Z", full_name="Gil Andersson")
    referral = file_referral(patient["id"])

    for reason in ("OUT_OF_SERVICE_AREA", "DUPLICATE_REFERRAL"):
        validate_success(
            api.decide_referral(
                referral["id"],
                {"decision": "DECLINE", "decline_reason_code": reason},
                INTAKE,
            )
        )
        validate_success(
            api.decide_referral(referral["id"], {"decision": "RE_REFER"}, INTAKE)
        )

    validate_success(
        api.decide_referral(
            referral["id"],
            {"decision": "DECLINE", "decline_reason_code": "PATIENT_DECLINED"},
            INTAKE,
        )
    )

    rejected = api.decide_referral(referral["id"], {"decision": "RE_REFER"}, INTAKE)
    validate_error(rejected, ApiErrorId.ERR_REREFERRAL_LIMIT.value, 409)

    final = validate_success(api.get_patient(patient["id"], ADMIN))
    referrals, _ = validate_paginated(
        api.list_patient_referrals(patient["id"], INTAKE)
    )
    stored = next(row for row in referrals if row["id"] == referral["id"])
    assert stored["status"] == "DECLINED"
    assert stored["re_referral_count"] == 2
    assert stored["decline_reason_code"] == "PATIENT_DECLINED"
    assert stored["triage_score"] == 90, (
        "RE_REFER recomputes the score from the unchanged referral inputs"
    )
    assert final["program_status"] == "REFERRED"


# ---------------------------------------------------------------------------
# Score cap and the acceptance floor
# ---------------------------------------------------------------------------
def test_triage_score_is_capped_at_one_hundred_and_still_clears_the_floor(api):
    """PRD 3.1: "Whichever variant applies, the result is then capped at 100, so
    no referral ever scores higher."
    PRD 3.1: "Acceptance moves the referral `RECEIVED → ACCEPTED`, which is
    terminal, and simultaneously moves the patient `REFERRED → ACTIVE` on
    `program_status`, incrementing the patient's `version` by 1 — this is the
    moment the patient becomes a program participant."

    Design: Corner/calculations/referral_triage_score_is_capped_at_one_hundred
    """
    patient = register_patient(clock="2026-06-01T00:00:00Z", full_name="Xan Beaulieu")

    referral = validate_success(
        api.create_referral(
            f.referral_payload(
                patient["id"],
                source="SELF",
                prognosis_months=1,
                serious_illness_criteria_count=5,
            ),
            INTAKE,
        ),
        201,
    )
    assert referral["triage_variant"] == "CLINICIAN_SOURCED"
    assert referral["triage_score"] == 100, (
        "5*24 + 11 months of gap * 2 = 142 before the cap, so the stored score is 100, "
        f"got {referral['triage_score']}"
    )

    accepted = validate_success(
        api.decide_referral(referral["id"], {"decision": "ACCEPT"}, INTAKE)
    )
    assert accepted["status"] == "ACCEPTED"
    assert read_patient(patient["id"])["program_status"] == "ACTIVE"


def test_accept_below_the_minimum_score_is_ineligible_while_decline_succeeds(api):
    """PRD 3.1: "An `ACCEPT` decision applies to a referral in `RECEIVED` and
    requires a `triage_score` of at least 60; below that floor it is refused with
    `ERR_REFERRAL_INELIGIBLE`."
    PRD 3.1: "A `DECLINE` decision, also from `RECEIVED`, moves the referral to
    `DECLINED`, stores the supplied `decline_reason_code`, and pointedly leaves
    the patient's `program_status` at `REFERRED`."

    Design: Corner/validations/referral_accept_below_the_minimum_score_returns_ineligible
    """
    patient = register_patient(clock="2026-06-01T00:00:00Z", full_name="Liv Ostrom")
    referral = file_referral(
        patient["id"],
        source="PAYER",
        prognosis_months=10,
        serious_illness_criteria_count=2,
    )
    assert referral["triage_variant"] == "PAYER_SOURCED"
    assert referral["triage_score"] == 52, (
        "20 source weight + 2*12 criteria + 2 months of gap * 4 = 52, "
        f"got {referral['triage_score']}"
    )

    rejected = api.decide_referral(referral["id"], {"decision": "ACCEPT"}, INTAKE)
    validate_error(rejected, ApiErrorId.ERR_REFERRAL_INELIGIBLE.value, 422)

    declined = validate_success(
        api.decide_referral(
            referral["id"],
            {"decision": "DECLINE", "decline_reason_code": "NOT_SERIOUS_ILLNESS"},
            INTAKE,
        )
    )
    assert declined["status"] == "DECLINED"
    assert declined["decline_reason_code"] == "NOT_SERIOUS_ILLNESS"
    assert read_patient(patient["id"])["program_status"] == "REFERRED"


# ---------------------------------------------------------------------------
# Patient sub-resource listing
# ---------------------------------------------------------------------------
def test_patient_referral_sub_resource_lists_only_that_patients_referrals(api):
    """PRD 4: "A list endpoint returns an array of the matching resources with
    `response_type` set to `"array"`."
    PRD 3.1: "A referral is then filed against that patient, carrying
    `patient_id`, a `source` of `HOSPITAL_DISCHARGE`, `ONCOLOGY`, `PRIMARY_CARE`,
    `SELF` or `PAYER`, a `prognosis_months` estimate that must be an integer from
    1 to 24 inclusive, and a `serious_illness_criteria_count` that must be an
    integer from 0 to 5 inclusive."

    Design: Corner/endpoints/patient_sub_resource_referral_list_returns_only_that_patients_children
    """
    patient_a = register_patient(clock="2026-06-01T00:00:00Z", full_name="Rae Duval")
    patient_b = register_patient(clock=None, full_name="Sol Nabil")

    file_referral(patient_a["id"], source="HOSPITAL_DISCHARGE")
    file_referral(patient_a["id"], source="ONCOLOGY")
    file_referral(patient_b["id"], source="PAYER")

    rows, meta = validate_paginated(api.list_patient_referrals(patient_a["id"], INTAKE))

    assert len(rows) == 2, f"expected exactly patient A's two referrals, got {len(rows)}"
    assert meta["total_count"] == 2
    assert {row["patient_id"] for row in rows} == {patient_a["id"]}
    assert sorted(row["triage_score"] for row in rows) == [84, 90], (
        "the HOSPITAL_DISCHARGE referral scores 90 and the ONCOLOGY referral 84"
    )
