"""Role-based access control across the seven roles of the /svh surface.

Each test drives one role boundary end to end: the writes a role owns exclusively,
the writes it is refused, the reads it keeps despite that refusal, and — for the
two entity-backed or duty-separated cases — the difference between a refusal that
names the role and a refusal that names the acting operator or the record's owner.
Every scenario is built inside the test, because the server is restarted with an
empty database and the logical clock at its starting instant before each one.
"""

from datetime import datetime

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CLAIM_STATE_INVALID,
    ERR_NOT_RESOURCE_OWNER,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.test_users import (
    DEFAULT_ASSESSOR_USER,
    DEFAULT_COORDINATOR_USER,
    make_admissions_coordinator_headers,
    make_clinical_assessor_headers,
    make_resident_representative_headers,
)


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating the optional fractional digits."""
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def _recognized_home_with_nursing_unit(api):
    """One recognised home with one certified two-bed nursing unit and no residents."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    home = fx.create_home(api)
    unit = fx.create_unit(
        api, home["id"], care_level="NURSING", licensed_bed_count=2, out_of_service_bed_count=0
    )
    return home, unit


def _queued_applicant_with_submitted_assessment(api, assessor_user_id=DEFAULT_ASSESSOR_USER):
    """A recognised home, a certified nursing unit and one waitlisted applicant.

    The applicant is eligible, holds an ACTIVE entry on the unit and carries a
    SUBMITTED nursing assessment, which is the state an admission decision needs.
    """
    home, unit = _recognized_home_with_nursing_unit(api)
    applicant = fx.create_applicant(
        api,
        home["id"],
        requested_care_level="NURSING",
        application_received_date="2026-08-01",
    )
    fx.determine_eligibility(api, applicant["id"])
    entry = fx.create_waitlist_entry(api, applicant["id"], unit["id"])
    assessment = fx.create_assessment(
        api,
        applicant["id"],
        assessor_user_id,
        assessed_care_level="NURSING",
        assessment_date="2026-08-01",
    )
    submitted = fx.submit_assessment(api, assessment["id"], assessor_user_id)
    return home, unit, applicant, entry, assessment, submitted


def test_state_program_admin_writes_are_refused_to_every_other_role(
    api, admin_headers, coordinator_headers, assessor_headers, bom_headers, auditor_headers, surveyor_headers
):
    """Five writes belong to the program administrator alone, and the refusal is operation-scoped.

    Per the PRD: "A `StateProgramAdmin` is the state veterans affairs program administrator: this role alone registers veterans homes, creates care units, changes a home's federal recognition posture, sets the logical clock, and runs the nightly census and operations checkpoint."
    Per the PRD: "If the headers are well-formed but the declared role is not among the roles authorized for the target operation in the endpoint table of §4, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    The roles refused those writes keep their shared reads on homes and care units,
    and the administrator's own checkpoint reports all-zero counters because no
    resident exists: "For every resident whose stay overlaps the run window, one census day row is created per calendar date, and `last_census_date` is then advanced to the end of the window."
    Per the PRD: "One `PNA_CREDIT` trust-fund posting is made per in-scope resident for the operating home's `personal_needs_allowance_monthly_cents`, with `effective_date` set to `through_date` and `memo` set to `personal needs allowance`."
    The checkpoint reports the clock it ran against, which is still the starting
    instant: "Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time."

    Design: Corner/rbac/rbac_state_program_admin_exclusive_ops_others_cannot_invoke
    """
    home, _unit = _recognized_home_with_nursing_unit(api)

    validate_error(
        api.census_run(f.census_run_payload("2026-08-01"), bom_headers),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.census_run(f.census_run_payload("2026-08-01"), auditor_headers),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.set_clock(f.clock_payload("2026-08-05T00:00:00Z"), assessor_headers),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.set_recognition(
            home["id"],
            f.recognition_payload("SUSPEND", "2026-08-01", "coordinator overreach"),
            coordinator_headers,
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_care_unit(
            home["id"],
            f.care_unit_payload(care_level="DOMICILIARY", licensed_bed_count=4),
            surveyor_headers,
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_veterans_home(f.veterans_home_payload(), bom_headers),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    auditor_view = validate_success(api.get_veterans_home(home["id"], auditor_headers), 200)
    assert auditor_view["recognition_status"] == "RECOGNIZED"

    _units, unit_meta = validate_paginated(
        api.list_home_care_units(home["id"], surveyor_headers, {"limit": 10})
    )
    assert unit_meta["total_count"] == 1

    counters = validate_success(
        api.census_run(f.census_run_payload("2026-08-01"), admin_headers), 200
    )
    assert counters["generated_census_day_count"] == 0
    assert counters["pna_credited_resident_count"] == 0
    assert _instant(counters["current_utc"]) == _instant("2026-08-01T00:00:00Z")

    _homes, home_meta = validate_paginated(api.list_veterans_homes(admin_headers, {"limit": 10}))
    assert home_meta["total_count"] == 1


def test_only_the_survey_agency_records_a_survey_and_it_cannot_read_residents(
    api, admin_headers, assessor_headers, surveyor_headers
):
    """The survey write belongs to the survey agency alone, whose reads stop short of residents.

    Per the PRD: "Certification is the state's judgement on a single care unit, and only the `SurveyAgency` role may record it."
    Per the PRD: "A `SurveyAgency` records survey results and does nothing else in the write direction."
    An empty deficiency list is a legal survey: "The score is a whole number and an empty array scores exactly 0."
    Per the PRD: "Every survey, whatever its outcome, writes `last_survey_compliance_score`, sets the unit's `last_survey_date` to the supplied `survey_date`, sets the operating home's `last_survey_date` to the same value, recomputes `operational_posture`, and increments the unit's `version`."
    A clean score leaves a certified unit certified and its posture open, because
    "Only a certified unit with at least one free bed is `OPEN`."

    Design: Corner/rbac/rbac_survey_agency_exclusive_survey_result_and_cannot_read_residents
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    home = fx.create_home(api)
    assert home["last_survey_date"] is None
    unit = fx.create_unit(
        api, home["id"], care_level="NURSING", licensed_bed_count=2, out_of_service_bed_count=0
    )
    assert unit["certification_status"] == "CERTIFIED"
    assert unit["last_survey_compliance_score"] == 0
    assert unit["last_survey_date"] is None

    clean_survey = f.survey_result_payload("2026-08-01", [])
    validate_error(
        api.record_survey_result(unit["id"], clean_survey, admin_headers),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.record_survey_result(unit["id"], clean_survey, assessor_headers),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.list_residents(surveyor_headers, {"limit": 10}),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    surveyed = validate_success(
        api.record_survey_result(unit["id"], clean_survey, surveyor_headers), 200
    )
    assert surveyed["certification_status"] == "CERTIFIED"
    assert surveyed["last_survey_compliance_score"] == 0
    assert surveyed["last_survey_date"] == "2026-08-01"
    assert surveyed["operational_posture"] == "OPEN"

    home_after = validate_success(api.get_veterans_home(home["id"], surveyor_headers), 200)
    assert home_after["last_survey_date"] == "2026-08-01"
    assert home_after["decertified_unit_count"] == 0
    assert home_after["recognition_status"] == "RECOGNIZED"


def test_the_federal_auditor_may_not_open_correct_or_submit_a_claim(
    api, bom_headers, auditor_headers
):
    """The claim lifecycle splits across two roles, and neither may cross into the other's half.

    Per the PRD: "A `FederalPerDiemAuditor` adjudicates submitted claims and does nothing else in the write direction — it can neither create, correct nor submit a claim."
    Per the PRD: "**Adjudication** is the `FederalPerDiemAuditor`'s decision on a `SUBMITTED` claim, and no other role may make it — the business office prepares and submits, the auditor pays or rejects."
    The auditor's own operation on a draft is refused later in the ladder, on the
    claim's state rather than on the role, so a 403 here always names the role. The
    draft prices at nothing because no census day exists to attribute:
    "`billable_day_count` is `resident_day_count` plus those payable bed-hold days — so bed-hold days beyond the cap are excluded from the billable count entirely — and `claim_amount_cents` is the full rate times `resident_day_count`, plus the per-day bed-hold rate times the payable bed-hold days."
    Per the PRD: "A new claim starts `DRAFT` with `correction_generation` 0 and `corrects_claim_id`, `submitted_at`, `adjudicated_at`, `paid_amount_cents`, `rejection_code` and `adjudication_note` all null, and `recognition_verified` false."

    Design: Corner/rbac/rbac_federal_auditor_cannot_create_correct_or_submit_claims
    """
    home, unit = _recognized_home_with_nursing_unit(api)

    claim = validate_success(
        fx.open_claim(api, home["id"], unit["id"], claim_month="2026-07"), 201
    )
    assert claim["status"] == "DRAFT"
    assert claim["claim_amount_cents"] == 0

    validate_error(
        api.create_per_diem_claim(
            f.per_diem_claim_payload(home["id"], unit["id"], claim_month="2026-06"),
            auditor_headers,
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.submit_per_diem_claim(claim["id"], {}, auditor_headers),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.correct_per_diem_claim(
            claim["id"],
            f.correction_payload(claim["version"], "auditor tries to correct"),
            auditor_headers,
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.adjudicate_per_diem_claim(
            claim["id"],
            f.adjudication_payload("PAID", "business office pays itself"),
            bom_headers,
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    auditor_view = validate_success(api.get_per_diem_claim(claim["id"], auditor_headers), 200)
    assert auditor_view["status"] == "DRAFT"
    assert auditor_view["claim_amount_cents"] == 0

    validate_error(
        api.adjudicate_per_diem_claim(
            claim["id"],
            f.adjudication_payload("PAID", "adjudicating a draft"),
            auditor_headers,
        ),
        ERR_CLAIM_STATE_INVALID,
        409,
    )

    _claims, claim_meta = validate_paginated(
        api.list_per_diem_claims(
            auditor_headers, {"veterans_home_id": home["id"], "limit": 10}
        )
    )
    assert claim_meta["total_count"] == 1


def test_the_resident_representative_reads_its_own_record_and_writes_nothing(api):
    """A representative reads its own resident, is refused elsewhere, and never writes.

    Per the PRD: "A `ResidentRepresentative` is the resident or the resident's legal representative and is read-only throughout."
    Per the PRD: "A `ResidentRepresentative` reaching for another resident's record, income, cost-share determinations, care plans or trust-fund activity is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    An endpoint outside the representative's shared-read list, and a write against
    its own resident, are both refused on the role instead — ownership never
    upgrades a reader into a writer.
    Per the PRD: "On success the plan's `status` becomes `ACTIVE`, `activated_at` is stamped from the logical clock, `review_due_date` is stamped as the plan's own `plan_date` plus a ninety-day review cycle, `revision_number` is set to one more than the superseded plan's `revision_number` (or 1 when there is no predecessor), the superseded plan — when one was named — moves to `SUPERSEDED`, the `version` of both plans increments, and the resident's `current_care_level` is re-stamped from this plan's `care_level`, incrementing the resident's `version`."

    Design: Corner/rbac/rbac_resident_representative_is_read_only_and_cannot_write
    """
    scenario = fx.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )
    income = fx.declare_income(
        api, scenario.resident_id, "SSA", 114000, "2026-08", verify=False
    )
    plan = fx.activate_care_plan(
        api,
        scenario.resident_id,
        care_level="NURSING",
        plan_date="2026-08-01",
        assessor_user_id=scenario.assessor_user_id,
    )
    assert plan["status"] == "ACTIVE"
    assert plan["review_due_date"] == "2026-10-30"
    transaction = get_success_data(
        fx.post_trust_entry(
            api, scenario.resident_id, "DEPOSIT", 50000, "2026-08-01", "family deposit"
        )
    )

    own_headers = make_resident_representative_headers(scenario.resident_id)

    resident_view = validate_success(api.get_resident(scenario.resident_id, own_headers), 200)
    assert resident_view["occupancy_status"] == "ADMITTED"
    assert resident_view["trust_fund_balance_cents"] == 50000

    income_rows, income_meta = validate_paginated(
        api.list_income_records(scenario.resident_id, own_headers, {"limit": 10})
    )
    assert income_meta["total_count"] == 1
    assert income_rows[0]["id"] == income["id"]
    assert income_rows[0]["verification_status"] == "UNVERIFIED"

    _determinations, determination_meta = validate_paginated(
        api.list_cost_share_determinations(scenario.resident_id, own_headers, {"limit": 10})
    )
    assert determination_meta["total_count"] == 0

    plan_view = validate_success(api.get_care_plan(plan["id"], own_headers), 200)
    assert plan_view["status"] == "ACTIVE"
    assert plan_view["care_level"] == "NURSING"

    transaction_view = validate_success(
        api.get_trust_fund_transaction(transaction["id"], own_headers), 200
    )
    assert transaction_view["amount_cents"] == 50000
    assert transaction_view["balance_after_cents"] == 50000

    validate_error(
        api.list_census_days(
            own_headers, {"resident_id": scenario.resident_id, "limit": 10}
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.create_trust_fund_transaction(
            scenario.resident_id,
            f.trust_fund_payload("WITHDRAWAL", 1000, "2026-08-01", "representative withdrawal"),
            own_headers,
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    outsider_headers = make_resident_representative_headers("outsider-1")
    validate_error(
        api.get_resident(scenario.resident_id, outsider_headers), ERR_NOT_RESOURCE_OWNER, 403
    )
    validate_error(
        api.get_care_plan(plan["id"], outsider_headers), ERR_NOT_RESOURCE_OWNER, 403
    )
    validate_error(
        api.get_trust_fund_transaction(transaction["id"], outsider_headers),
        ERR_NOT_RESOURCE_OWNER,
        403,
    )


def test_the_assessor_who_wrote_the_assessment_may_not_take_the_decision(api):
    """Two different 403s guard the admission decision, and they are not interchangeable.

    Per the PRD: "A `ClinicalAssessor` cannot record an admission decision at all, and a `FederalPerDiemAuditor` can neither open, correct nor submit the claims it adjudicates."
    Per the PRD: "First, the `AdmissionsCoordinator` who records an admission decision must not be the `ClinicalAssessor` who authored the cited assessment: if the acting `X-User-ID` equals that assessment's `assessor_user_id`, the decision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    Handing the identical payload to a different coordinator then succeeds, which
    proves the block was on the operator identity rather than on the payload, and
    the approval consumes exactly one bed of the two the unit licenses.

    Design: Corner/rbac/rbac_segregation_of_duties_assessor_cannot_decide_own_assessment
    """
    _home, unit, applicant, _entry, assessment, submitted = (
        _queued_applicant_with_submitted_assessment(api)
    )
    assert assessment["assessor_user_id"] == DEFAULT_ASSESSOR_USER
    assert submitted["status"] == "SUBMITTED"

    observed_version = fx.read_unit(api, unit["id"])["version"]
    decision = f.admission_decision_payload(
        unit["id"], assessment["id"], observed_version, "2026-08-01", "APPROVED"
    )

    validate_error(
        api.admission_decision(
            applicant["id"], decision, make_clinical_assessor_headers(DEFAULT_ASSESSOR_USER)
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.admission_decision(
            applicant["id"],
            decision,
            make_admissions_coordinator_headers(DEFAULT_ASSESSOR_USER),
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    assert fx.read_applicant(api, applicant["id"])["status"] == "WAITLISTED"

    resident = validate_success(
        api.admission_decision(
            applicant["id"],
            decision,
            make_admissions_coordinator_headers(DEFAULT_COORDINATOR_USER),
        ),
        201,
    )
    assert resident["occupancy_status"] == "ADMITTED"
    assert resident["care_unit_id"] == unit["id"]

    unit_after = fx.read_unit(api, unit["id"])
    assert unit_after["occupied_bed_count"] == 1
    assert unit_after["available_bed_count"] == 1
