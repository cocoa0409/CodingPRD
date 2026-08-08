"""The community resource network: organization suspension, offering inventory
and the ranked eligibility gauntlet."""

from test_helpers import (
    ApiErrorId,
    assert_offering_counters,
    assert_same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import create_referral_payload
from test_helpers.test_users import PROGRAM_ADMIN, SUPERVISOR, make_chw_headers


def test_offering_with_no_criteria_passes_the_gauntlet_trivially(api):
    """PRD §3.3: "Evaluation walks the ordered list and stops at the **first**
    failure, reporting that criterion's error and never looking at the criteria
    behind it. An offering with no criteria at all passes trivially, having
    evaluated zero of them."
    PRD §3.3: "The response reports `eligible` as a boolean, `evaluated_count`
    as the number of criteria in the ordered list, and three fields describing
    the stopping point: `first_failing_criterion_id`,
    `first_failing_criterion_type` and `first_failing_error_id`, which names the
    error identifier the same failure would have produced on a real referral.
    When `eligible` is true, all three of those fields are null."

    Design: Difficulty/boundary_precision_check/empty_criteria_set_passes_eligibility_with_zero_evaluated
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="W-017", mrn="MRN-160", full_name="Empty Set",
        household_size=1, monthly_income_cents=999_000, residence_zip="99999",
    )
    org, offering, _partner = fx.org_with_offering(
        capacity_total=4,
        org_overrides={
            "name": "City Rides", "org_type": "TRANSPORT",
            "contact_email": "ops@cityrides.example",
        },
        unit_type="TRANSPORT_RIDE",
    )

    data = validate_success(
        api.eligibility_check(offering["id"], {"patient_id": patient["id"]}, chw_headers)
    )

    assert data["eligible"] is True, (
        "an offering carrying no criteria passes every patient trivially"
    )
    assert data["evaluated_count"] == 0, (
        f"zero criteria means evaluated_count 0, got {data['evaluated_count']}"
    )
    assert data["first_failing_criterion_id"] is None
    assert data["first_failing_criterion_type"] is None
    assert data["first_failing_error_id"] is None


def test_eligibility_check_answers_200_even_for_a_patient_no_criterion_would_pass(api):
    """PRD §3.3: "A `CHW`, `Supervisor` or `ProgramAdmin` supplies a
    `patient_id` against an offering and receives HTTP 200 whatever the outcome
    — an ineligible patient is a successful answer, not an error."
    PRD §3.3: "Evaluation walks the ordered list and stops at the **first**
    failure, reporting that criterion's error and never looking at the criteria
    behind it. An offering with no criteria at all passes trivially, having
    evaluated zero of them."

    Design: Difficulty/boundary_precision_check/empty_criteria_set_passes_eligibility_with_zero_evaluated
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="W-017B", mrn="MRN-160B", full_name="Empty Set",
        household_size=1, monthly_income_cents=999_000, residence_zip="99999",
    )
    org, offering, _partner = fx.org_with_offering(
        capacity_total=4,
        org_overrides={
            "name": "City Rides", "org_type": "TRANSPORT",
            "contact_email": "ops@cityrides.example",
        },
        unit_type="TRANSPORT_RIDE",
    )

    response = api.eligibility_check(
        offering["id"], {"patient_id": patient["id"]}, chw_headers
    )
    assert response.status_code == 200, (
        f"the eligibility check always answers 200, got {response.status_code}"
    )
    data = validate_success(response)
    assert data["eligible"] is True

    _rows, meta = validate_paginated(api.list_criteria(offering["id"], chw_headers))
    assert meta["total_count"] == 0, (
        f"the offering carries no criteria at all, got {meta['total_count']}"
    )


def test_referral_to_a_suspended_organization_is_refused(api):
    """PRD §3.3: "What suspension blocks is new business — sending or
    re-routing a referral to an offering whose organization is `SUSPENDED` is
    rejected at rung 9 with `ERR_RESOURCE_ORG_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/referral_blocked_while_resource_org_suspended
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="W-018", mrn="MRN-170", full_name="Guarded Case",
        household_size=3,
    )
    org, offering, _partner = fx.org_with_offering(capacity_total=5)
    fx.suspend_org(org["id"])

    response = api.create_referral(
        create_referral_payload(
            patient["id"], offering["id"], worker["id"],
            fx.offering_version(offering["id"]), urgency="URGENT",
        ),
        chw_headers,
    )
    validate_error(response, ApiErrorId.ERR_RESOURCE_ORG_SUSPENDED.value, 409)

    assert_offering_counters(
        fx.read_offering(offering["id"]), available=5, allocated=0, lifetime=0
    )


def test_reinstating_the_organization_lets_the_identical_referral_through(api):
    """PRD §3.3: "A `ProgramAdmin` may later supply an `action` of `SUSPEND` to
    move `ACTIVE` to `SUSPENDED`, or `REINSTATE` to move `SUSPENDED` back to
    `ACTIVE`; either toggle increments the organization's `version` by 1, and
    requesting a toggle from the wrong state is `ERR_INVALID_STATE`."
    PRD §3.4: "**Acknowledgement deadlines.** The `urgency` selects how long the
    partner has to respond: `ROUTINE` allows 72 hours, `URGENT` allows 24 hours,
    and `EMERGENT` allows just 4 hours."
    PRD §3.4: "Under the **fresh-SLA** variant, which applies whenever
    `parent_referral_id` is null, `ack_deadline_at` is this referral's own
    `sent_at` plus the urgency's hours, so a root referral always gets the full
    window."

    Design: Difficulty/cross_entity_state_dependency/referral_blocked_while_resource_org_suspended
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-01T00:00:00Z", employee_code="W-018B",
        mrn="MRN-170B", full_name="Guarded Case", household_size=3,
    )
    org, offering, _partner = fx.org_with_offering(capacity_total=5)
    fx.suspend_org(org["id"])

    refused = api.create_referral(
        create_referral_payload(
            patient["id"], offering["id"], worker["id"],
            fx.offering_version(offering["id"]), urgency="URGENT",
        ),
        chw_headers,
    )
    validate_error(refused, ApiErrorId.ERR_RESOURCE_ORG_SUSPENDED.value, 409)

    reinstated = validate_success(
        api.suspend_resource_org(org["id"], {"action": "REINSTATE"}, PROGRAM_ADMIN)
    )
    assert reinstated["status"] == "ACTIVE"

    referral = validate_success(
        api.create_referral(
            create_referral_payload(
                patient["id"], offering["id"], worker["id"],
                fx.offering_version(offering["id"]), urgency="URGENT",
            ),
            chw_headers,
        ),
        201,
    )
    assert referral["status"] == "SENT"
    assert_same_instant(
        referral["ack_deadline_at"], "2026-06-02T00:00:00Z",
        "URGENT ack_deadline_at (24 hours from sent_at)",
    )
    assert_offering_counters(
        fx.read_offering(offering["id"]), available=4, allocated=1, lifetime=1
    )


def test_eligibility_failure_preempts_the_capacity_shortage(api):
    """PRD §3.3: "All five failures carry HTTP 422 and all five sit at rung 12
    of the ladder, which is why an ineligible patient against a suspended
    organization reports the suspension (rung 9) rather than the ineligibility,
    and why an ineligible patient against an exhausted offering reports the
    ineligibility rather than the shortage (rung 16)."
    PRD §3.3: "A `GEOGRAPHY` criterion passes when the patient's
    `residence_zip` is a member of the criterion's `allowed_zips`. Failure
    raises `ERR_ELIGIBILITY_GEOGRAPHY`."

    Design: Difficulty/priority_pair_validation_conflict/eligibility_rung12_preempts_capacity_rung16
    """
    scene = _exhausted_offering_with_ineligible_patient(api, "W-010", "MRN-100")

    response = api.create_referral(
        create_referral_payload(
            scene["fail_patient"]["id"], scene["offering"]["id"], scene["worker"]["id"],
            fx.offering_version(scene["offering"]["id"]),
        ),
        scene["chw_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ELIGIBILITY_GEOGRAPHY.value, 422)
    assert response.status_code == 422


def test_the_exhausted_offering_is_untouched_by_the_ineligible_request(api):
    """PRD §3.3: "All five failures carry HTTP 422 and all five sit at rung 12
    of the ladder, which is why an ineligible patient against a suspended
    organization reports the suspension (rung 9) rather than the ineligibility,
    and why an ineligible patient against an exhausted offering reports the
    ineligibility rather than the shortage (rung 16)."
    PRD §3.3: "`availability_state` is `AVAILABLE` for as long as
    `available_units` is greater than 0, and flips to `EXHAUSTED` the moment
    `available_units` reaches 0, at which point `exhausted_since` is stamped
    with the current logical clock; when units return and `available_units`
    rises above 0 again, the state flips back to `AVAILABLE` and
    `exhausted_since` returns to null."

    Design: Difficulty/priority_pair_validation_conflict/eligibility_rung12_preempts_capacity_rung16
    """
    scene = _exhausted_offering_with_ineligible_patient(api, "W-010B", "MRN-100B")

    refused = api.create_referral(
        create_referral_payload(
            scene["fail_patient"]["id"], scene["offering"]["id"], scene["worker"]["id"],
            fx.offering_version(scene["offering"]["id"]),
        ),
        scene["chw_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_ELIGIBILITY_GEOGRAPHY.value, 422)

    after = fx.read_offering(scene["offering"]["id"])
    assert_offering_counters(
        after, available=0, allocated=1, availability_state="EXHAUSTED"
    )

    _rows, meta = validate_paginated(
        api.list_referrals(
            scene["chw_headers"], params={"patient_id": scene["fail_patient"]["id"]}
        )
    )
    assert meta["total_count"] == 0, "the refused request created no referral"


def test_income_failure_is_reported_before_geography_failure(api):
    """PRD §3.3: "**Running the gauntlet.** Whenever a patient must be matched
    to an offering, every criterion attached to that offering is evaluated in a
    fixed order: `evaluation_rank` ascending, with `created_at` ascending —
    never `id` — breaking ties between two criteria carrying the same rank."
    PRD §3.3: "The criterion type also fixes the criterion's `evaluation_rank`,
    which is derived by the server and can never be supplied by the client:
    `INCOME_BAND` is rank 1, `GEOGRAPHY` is rank 2, `HOUSEHOLD_SIZE` is rank 3,
    `PROGRAM_ENROLLMENT` is rank 4 and `CATEGORICAL_EXCLUSION` is rank 5."
    PRD §3.3: "An `INCOME_BAND` criterion passes when the patient's
    `monthly_income_cents` is less than or equal to the criterion's
    `max_monthly_income_cents`; income exactly at the band ceiling passes.
    Failure raises `ERR_ELIGIBILITY_INCOME`."
    PRD §3.3: "The response reports `eligible` as a boolean, `evaluated_count`
    as the number of criteria in the ordered list, and three fields describing
    the stopping point: `first_failing_criterion_id`,
    `first_failing_criterion_type` and `first_failing_error_id`, which names the
    error identifier the same failure would have produced on a real referral."

    Design: Corner/calculations/eligibility_income_failure_reported_before_geography_failure
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="C-024", mrn="MRN-C24", full_name="Double Fail",
        household_size=3, monthly_income_cents=300_000, residence_zip="60640",
    )
    org, offering, _partner = fx.org_with_offering(capacity_total=5)
    income_criterion = fx.attach_criterion(
        offering["id"], "INCOME_BAND", max_monthly_income_cents=200_000
    )
    fx.attach_criterion(offering["id"], "GEOGRAPHY", allowed_zips=["60614"])

    response = api.eligibility_check(
        offering["id"], {"patient_id": patient["id"]}, chw_headers
    )
    data = validate_success(response)
    assert response.status_code == 200

    assert data["eligible"] is False
    assert data["evaluated_count"] == 2, (
        "evaluated_count is the number of criteria in the ordered list, which "
        f"holds both the income and the geography criterion, got {data['evaluated_count']}"
    )
    assert data["first_failing_criterion_id"] == income_criterion["id"]
    assert data["first_failing_criterion_type"] == "INCOME_BAND"
    assert data["first_failing_error_id"] == ApiErrorId.ERR_ELIGIBILITY_INCOME.value


def test_each_remaining_criterion_type_reports_its_own_error(api):
    """PRD §3.3: "A `HOUSEHOLD_SIZE` criterion passes when the patient's
    `household_size` is greater than or equal to `min_household_size` and less
    than or equal to `max_household_size`; both ends are inclusive, so a
    household sitting exactly on either bound passes. Failure raises
    `ERR_ELIGIBILITY_HOUSEHOLD_SIZE`."
    PRD §3.3: "A `PROGRAM_ENROLLMENT` criterion passes when the criterion's
    `required_program_code` is a member of the patient's `program_enrollments`.
    Failure raises `ERR_ELIGIBILITY_PROGRAM_ENROLLMENT`."
    PRD §3.3: "A `CATEGORICAL_EXCLUSION` criterion passes when the criterion's
    `excluded_flag_code` is **not** a member of the patient's
    `categorical_exclusions`; presence of the flag is what fails. Failure raises
    `ERR_ELIGIBILITY_CATEGORICAL_EXCLUSION`."

    Design: Corner/validations/remaining_eligibility_criterion_types_each_report_their_own_error
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="C-050", mrn="MRN-C50", full_name="Gauntlet Case",
        household_size=2, categorical_exclusions=["PRIOR_FRAUD_FINDING"],
    )
    org, household_offering, _partner = fx.org_with_offering(capacity_total=5)
    fx.attach_criterion(
        household_offering["id"], "HOUSEHOLD_SIZE",
        min_household_size=4, max_household_size=8,
    )
    program_offering = fx.create_offering(org["id"], capacity_total=5)
    fx.attach_criterion(
        program_offering["id"], "PROGRAM_ENROLLMENT", required_program_code="SNAP"
    )
    exclusion_offering = fx.create_offering(org["id"], capacity_total=5)
    fx.attach_criterion(
        exclusion_offering["id"], "CATEGORICAL_EXCLUSION",
        excluded_flag_code="PRIOR_FRAUD_FINDING",
    )

    expectations = [
        (household_offering, ApiErrorId.ERR_ELIGIBILITY_HOUSEHOLD_SIZE.value),
        (program_offering, ApiErrorId.ERR_ELIGIBILITY_PROGRAM_ENROLLMENT.value),
        (exclusion_offering, ApiErrorId.ERR_ELIGIBILITY_CATEGORICAL_EXCLUSION.value),
    ]
    for offering, expected_error in expectations:
        response = api.create_referral(
            create_referral_payload(
                patient["id"], offering["id"], worker["id"],
                fx.offering_version(offering["id"]),
            ),
            chw_headers,
        )
        validate_error(response, expected_error, 422)
        assert_offering_counters(
            fx.read_offering(offering["id"]), available=5, allocated=0, lifetime=0
        )

    _rows, meta = validate_paginated(
        api.list_referrals(chw_headers, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 0, "not one of the three attempts created a referral"


def test_eligibility_check_has_no_side_effects(api):
    """PRD §3.3: "This capability has no side effects of any kind, and its
    listing companion returns an offering's criteria already sorted into
    evaluation order."
    PRD §3.3: "The gauntlet is also exposed on its own, as a dry run that
    creates nothing."

    Design: Corner/endpoints/eligibility_check_endpoint_has_no_side_effects
    """
    worker, patient, chw_headers = fx.program_with_patient(
        employee_code="C-060", mrn="MRN-C60", full_name="Pure Read Case",
    )
    org, offering, _partner = fx.org_with_offering(capacity_total=3)
    fx.attach_criterion(
        offering["id"], "INCOME_BAND", max_monthly_income_cents=200_000
    )

    first = validate_success(
        api.eligibility_check(offering["id"], {"patient_id": patient["id"]}, chw_headers)
    )
    second = validate_success(
        api.eligibility_check(offering["id"], {"patient_id": patient["id"]}, SUPERVISOR)
    )

    for label, data in (("first", first), ("second", second)):
        assert data["eligible"] is True, f"{label} call must report eligible true"
        assert data["evaluated_count"] == 1, (
            f"{label} call evaluated the single attached criterion, "
            f"got {data['evaluated_count']}"
        )
        assert data["first_failing_criterion_id"] is None

    after = fx.read_offering(offering["id"])
    assert_offering_counters(
        after, available=3, allocated=0, lifetime=0, availability_state="AVAILABLE"
    )

    _rows, meta = validate_paginated(
        api.list_referrals(chw_headers, params={"offering_id": offering["id"]})
    )
    assert meta["total_count"] == 0, "the dry run created no referral"


# ─── Local scenario builder ────────────────────────────────────────────────

def _exhausted_offering_with_ineligible_patient(api, employee_code, mrn_prefix):
    """One single-unit offering already exhausted by an eligible patient, plus a
    second patient who fails the GEOGRAPHY criterion at rank 2."""
    fx.set_clock("2026-06-01T00:00:00Z")
    worker = fx.register_worker(employee_code=employee_code)
    chw_headers = make_chw_headers(worker["id"])

    pass_patient = fx.add_patient(
        chw_headers, mrn=f"{mrn_prefix}-P", full_name="Pass Patient",
        household_size=3, monthly_income_cents=100_000, residence_zip="60614",
    )
    fail_patient = fx.add_patient(
        chw_headers, mrn=f"{mrn_prefix}-F", full_name="Fail Patient",
        household_size=3, monthly_income_cents=150_000, residence_zip="60640",
    )
    fx.enroll_patient(pass_patient["id"])
    fx.enroll_patient(fail_patient["id"])

    org, offering, partner_headers = fx.org_with_offering(capacity_total=1)
    fx.attach_criterion(
        offering["id"], "INCOME_BAND", max_monthly_income_cents=200_000
    )
    fx.attach_criterion(offering["id"], "GEOGRAPHY", allowed_zips=["60614"])

    fx.send_referral(chw_headers, pass_patient["id"], offering["id"], worker["id"])

    return {
        "worker": worker,
        "chw_headers": chw_headers,
        "pass_patient": pass_patient,
        "fail_patient": fail_patient,
        "org": org,
        "offering": offering,
        "partner_headers": partner_headers,
    }
