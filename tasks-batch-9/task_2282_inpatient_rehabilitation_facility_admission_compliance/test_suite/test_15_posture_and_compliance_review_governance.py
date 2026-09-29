"""Facility posture derivation and the governance of compliance reviews."""

from test_helpers import (
    OFFICER_HEADERS,
    SECOND_OFFICER_HEADERS,
    ApiErrorId,
    admit,
    api_client,
    assert_facility_cohort,
    compute_review,
    create_compliance_review_payload,
    discharge,
    open_and_compute_review,
    open_compliance_review,
    read_admission,
    read_compliance_review,
    read_facility,
    setup_admitted_cohort,
    setup_discharged_cohort,
    setup_facility_with_staff,
    setup_interruption_chain,
    validate_error,
)

PRESUMPTIVE_PATIENT = {"impairment_group_code": "0008",
                       "etiologic_diagnosis_code": "I63.9",
                       "comorbidity_tier": "NONE"}
NON_PRESUMPTIVE_PATIENT = {"impairment_group_code": "0950",
                           "etiologic_diagnosis_code": "M17.11",
                           "comorbidity_tier": "NONE"}


def test_posture_stays_open_on_one_discharge_and_freezes_on_the_second():
    """A cohort of one cannot freeze the facility however badly it scores.

    PRD §2.8: "In every other case — including any facility whose provisional
    cohort holds fewer than two admissions — the posture is `OPEN`."

    PRD §2.8: "Otherwise, if the provisional cohort holds at least two admissions
    and the provisional compliance percentage is strictly below the facility's
    threshold reduced by a twenty-percentage-point freeze margin, the posture is
    again `ADMISSION_FREEZE`."

    Design: Corner/calculations/posture_min_cohort_gate_holds_open_until_the_second_discharge
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    stays = setup_admitted_cohort(env, [{"mrn": "MRN-A"}, {"mrn": "MRN-B"}],
                                  admitted_at="2026-08-04T12:00:00Z")

    discharge(env, stays[0]["admission"]["id"], "2026-08-05T12:00:00Z")
    after_first = read_facility(env["facility_id"])
    discharge(env, stays[1]["admission"]["id"], "2026-08-06T12:00:00Z")
    after_second = read_facility(env["facility_id"])

    assert_facility_cohort(after_first, cohort_total_count=1,
                           cohort_qualifying_count=0,
                           provisional_compliance_pct=0.00, posture="OPEN")
    assert_facility_cohort(after_second, cohort_total_count=2,
                           cohort_qualifying_count=0,
                           provisional_compliance_pct=0.00,
                           posture="ADMISSION_FREEZE")


def test_presumptive_review_of_three_cases_scores_thirty_three_thirty_three():
    """One qualifier in three rounds 33.333... down the half-up rule to 33.33.

    PRD §3.9: "`qualifying_cases` is the count of qualifying cohort members, and
    `compliance_pct` is that count multiplied by 100, divided by `total_cases`,
    rounded half up to two decimals."

    PRD §3.9: "Under `PRESUMPTIVE`, an admission qualifies when its patient's
    `impairment_group_code` is one of `0008`, `0110`, `0704`, or `1101`; or when
    its patient's `etiologic_diagnosis_code` is one of `I63.9` or `S72.001A`
    **and** that patient's `comorbidity_tier` is `TIER_1` or `TIER_2`."

    Design: Corner/calculations/compliance_percentage_rounds_one_of_three_cases_to_thirty_three_thirty_three
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    setup_discharged_cohort(
        env,
        [{"mrn": "MRN-A", "patient_overrides": PRESUMPTIVE_PATIENT},
         {"mrn": "MRN-B", "patient_overrides": dict(NON_PRESUMPTIVE_PATIENT,
                                                   full_name="Bo Whitaker")},
         {"mrn": "MRN-C", "patient_overrides": dict(NON_PRESUMPTIVE_PATIENT,
                                                    full_name="Cleo Ashford")}],
        admitted_at="2026-08-04T12:00:00Z",
        discharged_at="2026-08-08T12:00:00Z",
    )

    review = open_and_compute_review(env, method="PRESUMPTIVE")

    assert review["status"] == "COMPUTED"
    assert review["total_cases"] == 3
    assert review["qualifying_cases"] == 1
    assert float(review["compliance_pct"]) == 33.33
    assert review["outcome"] == "FAIL"


def test_computing_a_review_over_an_empty_cohort_is_rejected():
    """Nobody has been discharged inside the period, so there is nothing to score.

    PRD §3.9: "`total_cases` is the cohort size, and an empty cohort is refused
    outright with `ERR_EMPTY_COMPLIANCE_COHORT`."

    Design: Corner/state_machines/compliance_review_compute_with_empty_cohort_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    setup_admitted_cohort(env, [{"mrn": "MRN-A"}],
                          admitted_at="2026-08-04T12:00:00Z")
    review = open_compliance_review(env)

    response = api_client.compute_compliance_review(review["id"],
                                                    OFFICER_HEADERS)

    validate_error(response, ApiErrorId.ERR_EMPTY_COMPLIANCE_COHORT)
    unchanged = read_compliance_review(review["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["computed_at"] is None


def test_review_opened_against_a_superseded_facility_version_is_rejected():
    """Opening the first review advanced the facility the second one still pins.

    PRD §2.7: "A mismatch with the facility's current `version` is rejected with
    `ERR_STALE_FACILITY_VERSION` and HTTP 412."

    Design: Corner/cross-cutting complexity layers/compliance_review_create_with_stale_facility_version_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    version_before = read_facility(env["facility_id"])["version"]
    open_compliance_review(env, expected_facility_version=version_before)

    response = api_client.create_compliance_review(
        create_compliance_review_payload(env["facility_id"], version_before),
        OFFICER_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_STALE_FACILITY_VERSION)
    assert read_facility(env["facility_id"])["version"] == version_before + 1


def test_officer_who_opened_the_review_may_not_certify_it():
    """The same operator cannot both open and certify the compliance finding.

    PRD §2.9: "And the officer certifying a compliance review must not be the
    operator recorded in `created_by_user_id` when the review was opened."

    Design: Corner/rbac/review_certified_by_its_own_creator_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    setup_discharged_cohort(env, [{"mrn": "MRN-A"}],
                            admitted_at="2026-08-04T12:00:00Z",
                            discharged_at="2026-08-08T12:00:00Z")
    review = open_and_compute_review(env)

    response = api_client.certify_compliance_review(review["id"],
                                                    OFFICER_HEADERS)

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    unchanged = read_compliance_review(review["id"])
    assert unchanged["status"] == "COMPUTED"
    assert unchanged["certified_by_user_id"] is None
    assert read_facility(env["facility_id"])["certified_compliance_pct"] is None


def test_certifying_a_cohort_holding_a_reopened_stay_is_rejected():
    """The recomputed cohort still holds the reopened head, so nothing is settled.

    PRD §3.9: "no member of the cohort may have a `payment_status` of `REOPENED`
    at that moment — an unsettled cohort is refused with
    `ERR_COHORT_PAYMENT_UNSETTLED`."

    Design: Corner/validations/certify_with_reopened_cohort_member_rejected
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))
    chain = setup_interruption_chain(env, attach=False)
    review = open_and_compute_review(env)
    assert review["total_cases"] == 1

    admit(env, chain["continuation"]["id"], chain["continuation_admitted_at"])
    assert read_admission(chain["head"]["id"])["payment_status"] == "REOPENED"
    assert read_compliance_review(review["id"])["status"] == "STALE"
    recomputed = compute_review(review["id"])
    assert recomputed["status"] == "COMPUTED"

    response = api_client.certify_compliance_review(review["id"],
                                                    SECOND_OFFICER_HEADERS)

    validate_error(response, ApiErrorId.ERR_COHORT_PAYMENT_UNSETTLED)
    assert read_compliance_review(review["id"])["status"] == "COMPUTED"
