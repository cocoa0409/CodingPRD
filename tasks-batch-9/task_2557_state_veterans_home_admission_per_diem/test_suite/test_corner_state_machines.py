"""State-machine corners: entry states, terminal locks, loops and cross-entity cascades.

Every record in this API moves through a declared lifecycle, and the PRD pins far
more than the happy path: which fields a freshly created row starts with, which
statuses refuse a second attempt at the same move, which moves loop back onto the
same row, and which moves drag other entities with them inside the same request.
These tests exercise those corners on the care plan, the clinical assessment, the
applicant, the veterans home, the care unit, the waitlist entry and the resident.

The API server is restarted before each test, so every test drives its own setup
from an empty database with the logical clock at its starting instant.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    DEFAULT_ASSESSOR_USER,
    DEFAULT_COORDINATOR_USER,
    make_admissions_coordinator_headers,
)


# ---------------------------------------------------------------------------
# Local scenario helpers
# ---------------------------------------------------------------------------
def _eligible_class_one_applicant(api):
    """A recognised home, one certified nursing unit and one ELIGIBLE applicant.

    The applicant carries an eighty percent service-connected disability and six
    completed years of state residency, and their application was received on the
    day the logical clock stands at, so no tenure has accrued yet.
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    home = fx.create_home(api)
    unit = fx.create_unit(api, home["id"], care_level="NURSING", licensed_bed_count=2)
    applicant = fx.create_applicant(
        api,
        home["id"],
        requested_care_level="NURSING",
        application_received_date="2026-08-01",
        service_connected_disability_pct=80,
        state_residency_years=6,
        nursing_care_for_service_connected=False,
    )
    determined = fx.determine_eligibility(api, applicant["id"])
    return home, unit, applicant, determined


def _assessment_row(api, applicant_id, assessment_id):
    """Read one clinical assessment back through its applicant's collection."""
    rows, _meta = validate_paginated(
        api.list_applicant_assessments(
            applicant_id, make_admissions_coordinator_headers(), {"limit": 100}
        )
    )
    matches = [row for row in rows if row["id"] == assessment_id]
    assert matches, f"assessment {assessment_id} missing from the applicant's collection"
    return matches[0]


def _applicant_entry_rows(api, applicant_id):
    """Read every waitlist entry of one applicant, keyed by entry id."""
    rows, meta = validate_paginated(
        api.list_applicant_waitlist_entries(
            applicant_id, make_admissions_coordinator_headers(), {"limit": 100}
        )
    )
    return {row["id"]: row for row in rows}, meta


def test_new_care_plan_enters_draft_with_no_review_clock(api, assessor_headers):
    """A freshly authored care plan is DRAFT, revision 1, with no review date and no activation stamp.

    The review clock starts at activation rather than at authoring, and because no
    predecessor was named the revision counter starts at one.

    Per the PRD: "A new plan is `DRAFT` — the plan lifecycle runs `DRAFT`, `ACTIVE`, `REVIEW_DUE`, `SUPERSEDED` and `VOID`, the last two terminal — with `authored_by_user_id` taken from the acting `X-User-ID`, `activated_at` null, `review_due_date` null, and `revision_number` set to one more than the superseded plan's `revision_number`, or to 1 when `supersedes_care_plan_id` is absent."

    Design: Corner/state_machines/sm_care_plan_initial_state_is_draft
    """
    scenario = fx.admitted_resident(
        api,
        admission_date="2026-08-01",
        care_level="NURSING",
        licensed_bed_count=2,
        out_of_service_bed_count=0,
    )

    plan = validate_success(
        api.create_care_plan(
            scenario.resident_id,
            f.care_plan_payload(
                care_level="NURSING", adl_support_level="HIGH", plan_date="2026-08-01"
            ),
            assessor_headers,
        ),
        201,
    )

    assert plan["status"] == "DRAFT"
    assert plan["revision_number"] == 1
    assert plan["version"] == 1
    assert plan["review_due_date"] is None
    assert plan["activated_at"] is None
    assert plan["authored_by_user_id"] == DEFAULT_ASSESSOR_USER
    assert plan.get("supersedes_care_plan_id") is None

    fetched = fx.read_care_plan(api, plan["id"])
    assert fetched["status"] == "DRAFT"
    assert fetched["review_due_date"] is None
    assert fetched["activated_at"] is None


def test_nursing_assessment_below_two_skilled_hours_cannot_be_submitted(api, assessor_headers):
    """A nursing assessment documenting 1.50 skilled hours is refused, and 2.00 exactly is accepted.

    The refused assessment stays DRAFT at its creation version and contributes no
    acuity, so the applicant's score is unchanged; the accepted one carries the
    ADL and cognitive weights into the score for the first time.

    Per the PRD: "Submission requires the assessment to be `DRAFT`, and an assessment in any other status is rejected with `ERR_ASSESSMENT_STATE_INVALID` (HTTP 409); it requires the owning applicant to be `ELIGIBLE` or `WAITLISTED`, and an applicant outside those two statuses is rejected with `ERR_APPLICANT_STATE_INVALID` (HTTP 409); and when the `assessed_care_level` is `NURSING`, it requires `skilled_nursing_hours_per_day` of at least 2.00, since a nursing placement that documents less than two skilled hours a day contradicts its own care level and is rejected with `ERR_CARE_LEVEL_MISMATCH` (HTTP 409)."
    The PRD also says: "Assessments still in `DRAFT`, and assessments that ended `REJECTED`, contribute nothing, and when no qualifying assessment exists the acuity term is exactly zero."

    Design: Corner/state_machines/sm_clinical_assessment_submit_below_nursing_hours_rejected
    """
    _home, _unit, applicant, determined = _eligible_class_one_applicant(api)
    assert determined["priority_class"] == "CLASS_1"
    assert determined["priority_score"] == 1270

    low = fx.create_assessment(
        api,
        applicant["id"],
        DEFAULT_ASSESSOR_USER,
        assessed_care_level="NURSING",
        adl_dependency_count=4,
        cognitive_impairment=True,
        behavioral_risk_flag=False,
        skilled_nursing_hours_per_day=1.50,
        assessment_date="2026-08-01",
    )
    refusal = api.submit_clinical_assessment(low["id"], {}, assessor_headers)
    validate_error(refusal, "ERR_CARE_LEVEL_MISMATCH", 409)

    low_after = _assessment_row(api, applicant["id"], low["id"])
    assert low_after["status"] == "DRAFT"
    assert low_after["version"] == 1
    assert fx.read_applicant(api, applicant["id"])["priority_score"] == 1270

    ok = fx.create_assessment(
        api,
        applicant["id"],
        DEFAULT_ASSESSOR_USER,
        assessed_care_level="NURSING",
        adl_dependency_count=4,
        cognitive_impairment=True,
        behavioral_risk_flag=False,
        skilled_nursing_hours_per_day=2.00,
        assessment_date="2026-08-01",
    )
    submitted = validate_success(
        api.submit_clinical_assessment(ok["id"], {}, assessor_headers), 200
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["acuity_points"] == 120
    assert fx.read_applicant(api, applicant["id"])["priority_score"] == 1390


def test_submitting_an_assessment_twice_is_refused_and_credits_acuity_once(api, assessor_headers):
    """The second submission of the same assessment is refused and the acuity term is not doubled.

    The first submission moves the row to SUBMITTED and advances it to version 2;
    the second finds a row that is no longer DRAFT, so nothing moves and the
    applicant's score still carries exactly one acuity contribution.

    Per the PRD: "Submission requires the assessment to be `DRAFT`, and an assessment in any other status is rejected with `ERR_ASSESSMENT_STATE_INVALID` (HTTP 409); it requires the owning applicant to be `ELIGIBLE` or `WAITLISTED`, and an applicant outside those two statuses is rejected with `ERR_APPLICANT_STATE_INVALID` (HTTP 409); and when the `assessed_care_level` is `NURSING`, it requires `skilled_nursing_hours_per_day` of at least 2.00, since a nursing placement that documents less than two skilled hours a day contradicts its own care level and is rejected with `ERR_CARE_LEVEL_MISMATCH` (HTTP 409)."
    The PRD also says: "On success the assessment becomes `SUBMITTED`, its `acuity_points` are recomputed, and the applicant's `priority_score` is recomputed — the acuity term becomes non-zero for the first time — which re-orders every queue the applicant sits in, refreshes `rank_score_snapshot` on each of those entries, increments the applicant's `version`, increments the `version` of every care unit whose queue was reordered, and increments the assessment's own `version`."

    Design: Corner/state_machines/sm_clinical_assessment_double_submit_rejected
    """
    _home, _unit, applicant, _determined = _eligible_class_one_applicant(api)
    assessment = fx.create_assessment(
        api,
        applicant["id"],
        DEFAULT_ASSESSOR_USER,
        assessed_care_level="NURSING",
        adl_dependency_count=4,
        cognitive_impairment=True,
        behavioral_risk_flag=False,
        skilled_nursing_hours_per_day=3.00,
        assessment_date="2026-08-01",
    )

    first = validate_success(
        api.submit_clinical_assessment(assessment["id"], {}, assessor_headers), 200
    )
    assert first["status"] == "SUBMITTED"
    assert first["version"] == 2

    second = api.submit_clinical_assessment(assessment["id"], {}, assessor_headers)
    validate_error(second, "ERR_ASSESSMENT_STATE_INVALID", 409)

    row = _assessment_row(api, applicant["id"], assessment["id"])
    assert row["status"] == "SUBMITTED"
    assert row["version"] == 2
    assert fx.read_applicant(api, applicant["id"])["priority_score"] == 1390


def test_denied_applicant_admits_no_further_move(api, coordinator_headers):
    """A denial is terminal: redetermination, re-listing and a retried approval are all refused.

    The denial itself cancels the applicant's queue entry, flips the cited
    assessment to REJECTED and consumes no bed, and every subsequent attempt to
    move the applicant reports the applicant-state violation.

    Per the PRD: "On `DENIED`, the divergent branch runs: the applicant's `status` becomes `DENIED`, the cited assessment's `status` becomes `REJECTED` with `rejection_reason` set to `ADMISSION_DENIED`, and *every* entry of this applicant whose status was `ACTIVE` or `OFFERED` — on the decided unit and on all others alike — moves to `CANCELLED` with `offer_expires_at` cleared and `queue_position` 0, each affected unit's `waitlist_active_count` decremented by 1 and each affected unit's `version` incremented."
    The PRD also says: "The same `ERR_APPLICANT_STATE_INVALID` guards the two later steps: waitlist placement requires the applicant to be `ELIGIBLE` or already `WAITLISTED`, and an admission decision requires the applicant to be `WAITLISTED`."

    Design: Corner/state_machines/sm_applicant_denied_state_is_terminal
    """
    _home, unit, applicant, _determined = _eligible_class_one_applicant(api)
    entry = fx.create_waitlist_entry(api, applicant["id"], unit["id"])
    assessment = fx.create_assessment(
        api,
        applicant["id"],
        DEFAULT_ASSESSOR_USER,
        assessed_care_level="NURSING",
        assessment_date="2026-08-01",
    )
    fx.submit_assessment(api, assessment["id"], DEFAULT_ASSESSOR_USER)

    # Both branches of the decision answer 201 (PRD 3.4).
    denial = fx.approve_admission(
        api,
        applicant["id"],
        unit["id"],
        assessment["id"],
        "2026-08-01",
        DEFAULT_COORDINATOR_USER,
        decision="DENIED",
        decision_note="clinical criteria not met",
    )
    validate_success(denial, 201)

    denied = fx.read_applicant(api, applicant["id"])
    assert denied["status"] == "DENIED"
    assert denied["decided_by_user_id"] == DEFAULT_COORDINATOR_USER
    assert denied["decision_note"] == "clinical criteria not met"

    rejected = _assessment_row(api, applicant["id"], assessment["id"])
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "ADMISSION_DENIED"

    entries, _meta = _applicant_entry_rows(api, applicant["id"])
    assert entries[entry["id"]]["status"] == "CANCELLED"
    assert entries[entry["id"]]["queue_position"] == 0

    unit_after = fx.read_unit(api, unit["id"])
    assert unit_after["waitlist_active_count"] == 0
    assert unit_after["occupied_bed_count"] == 0
    assert unit_after["available_bed_count"] == 2

    validate_error(
        api.determine_eligibility(
            applicant["id"], {"amended_state_residency_years": 9}, coordinator_headers
        ),
        "ERR_APPLICANT_STATE_INVALID",
        409,
    )
    validate_error(
        api.create_waitlist_entry(
            f.waitlist_entry_payload(applicant["id"], unit["id"]), coordinator_headers
        ),
        "ERR_APPLICANT_STATE_INVALID",
        409,
    )
    validate_error(
        fx.approve_admission(
            api,
            applicant["id"],
            unit["id"],
            assessment["id"],
            "2026-08-02",
            DEFAULT_COORDINATOR_USER,
        ),
        "ERR_APPLICANT_STATE_INVALID",
        409,
    )

    residents, residents_meta = validate_paginated(
        api.list_residents(coordinator_headers, {"applicant_id": applicant["id"]})
    )
    assert residents == []
    assert residents_meta["total_count"] == 0


def test_superseded_care_plan_cannot_be_reactivated(api, assessor_headers):
    """Once a replacement plan is activated the replaced plan is closed for good.

    The first plan is activated with a review date ninety days after its own plan
    date, the revision that cites it takes revision number two, and the attempt to
    bring the replaced plan back reports the plan-state violation while leaving it
    SUPERSEDED at the version its three mutations produced.

    Per the PRD: "Attempting to activate a plan whose status is neither `DRAFT` nor `REVIEW_DUE` is rejected with `ERR_CARE_PLAN_STATE_INVALID` (HTTP 409), and activating any plan for a `DISCHARGED` resident is rejected with `ERR_RESIDENT_STATE_INVALID` (HTTP 409)."
    The PRD also says: "On success the plan's `status` becomes `ACTIVE`, `activated_at` is stamped from the logical clock, `review_due_date` is stamped as the plan's own `plan_date` plus a ninety-day review cycle, `revision_number` is set to one more than the superseded plan's `revision_number` (or 1 when there is no predecessor), the superseded plan — when one was named — moves to `SUPERSEDED`, the `version` of both plans increments, and the resident's `current_care_level` is re-stamped from this plan's `care_level`, incrementing the resident's `version`."

    Design: Corner/state_machines/sm_care_plan_activate_from_superseded_rejected
    """
    scenario = fx.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )

    first = fx.activate_care_plan(
        api,
        scenario.resident_id,
        care_level="NURSING",
        plan_date="2026-08-01",
        adl_support_level="HIGH",
        assessor_user_id=DEFAULT_ASSESSOR_USER,
    )
    assert first["status"] == "ACTIVE"
    assert first["review_due_date"] == "2026-10-30"

    revision = fx.activate_care_plan(
        api,
        scenario.resident_id,
        care_level="NURSING",
        plan_date="2026-08-01",
        adl_support_level="MODERATE",
        assessor_user_id=DEFAULT_ASSESSOR_USER,
        supersedes_care_plan_id=first["id"],
    )
    assert revision["status"] == "ACTIVE"
    assert revision["revision_number"] == 2
    assert revision["review_due_date"] == "2026-10-30"

    validate_error(
        api.activate_care_plan(first["id"], {}, assessor_headers),
        "ERR_CARE_PLAN_STATE_INVALID",
        409,
    )

    replaced = fx.read_care_plan(api, first["id"])
    assert replaced["status"] == "SUPERSEDED"
    assert replaced["version"] == 3
    assert replaced["revision_number"] == 1


def test_review_due_care_plan_reactivates_off_the_current_clock(api, assessor_headers):
    """One plan row loops ACTIVE to REVIEW_DUE and back, re-stamping the review date from the clock.

    The checkpoint flags the plan because its review date has fallen behind the run
    window, and the clinician's re-activation dates the next review ninety days
    from the current logical-clock date rather than from the original plan date. No
    new plan was authored, so the revision counter does not move.

    Per the PRD: "Every `ACTIVE` care plan whose `review_due_date` is strictly earlier than `through_date` is set to `REVIEW_DUE`, and the count lands in `review_due_care_plan_count`."
    The PRD also says: "Activating that same plan again returns it to `ACTIVE` and re-stamps `review_due_date` — but this time as the **current logical-clock date** plus the ninety-day cycle, not as `plan_date` plus ninety days, because the clinician has just re-reviewed a plan that may be months old."

    Design: Corner/state_machines/sm_care_plan_review_due_cycle_restamps_review_date
    """
    scenario = fx.admitted_resident_with_care_plan(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )
    activated = fx.read_care_plan(api, scenario.care_plan_id)
    assert activated["status"] == "ACTIVE"
    assert activated["review_due_date"] == "2026-10-30"
    assert activated["version"] == 2

    fx.set_clock(api, "2026-11-01T00:00:00Z")
    counters = fx.census_run(api, "2026-10-31", scenario.home_id)
    assert counters["review_due_care_plan_count"] == 1

    flagged = fx.read_care_plan(api, scenario.care_plan_id)
    assert flagged["status"] == "REVIEW_DUE"
    assert flagged["version"] == 3

    reactivated = validate_success(
        api.activate_care_plan(scenario.care_plan_id, {}, assessor_headers), 200
    )
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["review_due_date"] == "2027-01-30"
    assert reactivated["revision_number"] == 1
    assert reactivated["version"] == 4


def test_grant_moves_a_provisional_home_to_recognized(api, admin_headers):
    """A GRANT is the only exit from PROVISIONAL, and it re-stamps the effective date.

    The action's effective date overwrites the date supplied at registration, the
    suspension reason stays null because the home is not suspended, and the single
    mutation advances the home from version one to version two.

    Per the PRD: "The `GRANT` action moves a home from `PROVISIONAL` to `RECOGNIZED` and is permitted only while `decertified_unit_count` is 0; the `SUSPEND` action moves a home from `RECOGNIZED` to `SUSPENDED`; the `RESTORE` action moves a home from `SUSPENDED` back to `RECOGNIZED` and, like `GRANT`, requires `decertified_unit_count` to be 0."
    The PRD also says: "In every case `recognition_effective_date` is set to the supplied `effective_date`."

    Design: Corner/state_machines/sm_home_provisional_to_recognized_on_grant
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    home = fx.create_home(
        api, recognition_effective_date="2026-07-01", recognition_status="PROVISIONAL"
    )
    assert home["recognition_status"] == "PROVISIONAL"
    assert home["version"] == 1

    granted = validate_success(
        api.set_recognition(
            home["id"],
            f.recognition_payload("GRANT", "2026-08-01", "state survey passed"),
            admin_headers,
        ),
        200,
    )

    assert granted["recognition_status"] == "RECOGNIZED"
    assert granted["recognition_effective_date"] == "2026-08-01"
    assert granted["version"] == 2
    assert granted["recognition_suspended_reason"] is None
    assert granted["decertified_unit_count"] == 0

    fetched = fx.read_home(api, home["id"])
    assert fetched["recognition_status"] == "RECOGNIZED"
    assert fetched["recognition_suspended_reason"] is None


def test_recognition_suspension_voids_the_home_draft_claim_and_frees_its_days(api, admin_headers, bom_headers):
    """Suspending recognition drives the home's draft claim to VOID and releases its census days.

    The draft bills a full month of nursing resident days at the federal rate. The
    suspension is a cross-entity side effect rather than a field flip on the home:
    the claim is voided in the same request and every day it had attributed returns
    to the pool for a future claim.

    Per the PRD: "Suspension is not merely a label: every per diem claim of that home whose status is `DRAFT` is voided in the same request."
    The PRD also says: "Each voided claim releases the census days it had attributed: their `per_diem_claim_id` returns to null and their `claimed` flag returns to false, which puts those days back in the pool for a future claim."
    And: "`billable_day_count` is `resident_day_count` plus those payable bed-hold days — so bed-hold days beyond the cap are excluded from the billable count entirely — and `claim_amount_cents` is the full rate times `resident_day_count`, plus the per-day bed-hold rate times the payable bed-hold days."

    Design: Corner/state_machines/sm_home_suspend_voids_draft_per_diem_claims
    """
    scenario = fx.billed_month(
        api,
        admission_date="2026-08-01",
        through_date="2026-08-31",
        clock_after_month="2026-09-01T00:00:00Z",
        care_level="NURSING",
        licensed_bed_count=2,
    )

    claim = validate_success(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-08", "AUDITED_BASIS"), 201
    )
    assert claim["status"] == "DRAFT"
    assert claim["resident_day_count"] == 31
    assert claim["billable_day_count"] == 31
    assert claim["census_reported_resident_count"] == 1
    assert claim["claim_amount_cents"] == 367567

    suspended = validate_success(
        api.set_recognition(
            scenario.home_id,
            f.recognition_payload("SUSPEND", "2026-09-01", "state action pending"),
            admin_headers,
        ),
        200,
    )
    assert suspended["recognition_status"] == "SUSPENDED"
    assert suspended["recognition_suspended_reason"] == "UNIT_DECERTIFIED"

    voided = fx.read_claim(api, claim["id"])
    assert voided["status"] == "VOID"
    assert voided["submitted_at"] is None

    rows, meta = validate_paginated(
        api.list_census_days(bom_headers, {"care_unit_id": scenario.unit_id, "limit": 100})
    )
    assert meta["total_count"] == 31
    assert all(row["per_diem_claim_id"] is None for row in rows)
    assert all(row["claimed"] is False for row in rows)


def test_clean_survey_returns_a_decertified_unit_to_conditional(api, surveyor_headers):
    """Reinstatement lands on CONDITIONAL, never straight back on CERTIFIED.

    A widespread actual-harm deficiency scores thirty-two, which decertifies the
    unit, freezes it and suspends the home. The clean follow-up survey scores zero
    but reinstates the unit only as far as CONDITIONAL, so its posture is
    RESTRICTED even though both beds are free, while the home's recognition returns.

    Per the PRD: "Note carefully that reinstatement never jumps straight back to `CERTIFIED`: a decertified unit must pass through `CONDITIONAL` first, which is precisely why a clean score of 0 lands on `CONDITIONAL` when the unit was decertified."
    The PRD also says: "Because the home's `decertified_unit_count` falls — and only when it reaches 0, meaning no other unit of the home is still decertified — the home's `recognition_status` moves from `SUSPENDED` back to `RECOGNIZED`, `recognition_suspended_reason` returns to null, and the home's `version` increments."

    Design: Corner/state_machines/sm_decertified_unit_returns_to_conditional_not_certified
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    home = fx.create_home(api)
    unit = fx.create_unit(
        api, home["id"], care_level="NURSING", licensed_bed_count=2, out_of_service_bed_count=0
    )

    decertified = validate_success(
        api.record_survey_result(
            unit["id"],
            f.survey_result_payload(
                "2026-08-01", [f.deficiency("WIDESPREAD", "ACTUAL_HARM")]
            ),
            surveyor_headers,
        ),
        200,
    )
    assert decertified["last_survey_compliance_score"] == 32
    assert decertified["certification_status"] == "DECERTIFIED"
    assert decertified["operational_posture"] == "FROZEN"

    suspended_home = fx.read_home(api, home["id"])
    assert suspended_home["recognition_status"] == "SUSPENDED"
    assert suspended_home["decertified_unit_count"] == 1

    fx.set_clock(api, "2026-08-02T00:00:00Z")
    reinstated = validate_success(
        api.record_survey_result(
            unit["id"], f.survey_result_payload("2026-08-02", []), surveyor_headers
        ),
        200,
    )
    assert reinstated["last_survey_compliance_score"] == 0
    assert reinstated["certification_status"] == "CONDITIONAL"
    assert reinstated["certification_status"] != "CERTIFIED"
    assert reinstated["operational_posture"] == "RESTRICTED"
    assert reinstated["last_survey_date"] == "2026-08-02"

    restored_home = fx.read_home(api, home["id"])
    assert restored_home["recognition_status"] == "RECOGNIZED"
    assert restored_home["recognition_suspended_reason"] is None
    assert restored_home["decertified_unit_count"] == 0
    assert restored_home["last_survey_date"] == "2026-08-02"


def test_admission_to_one_unit_cancels_the_applicants_entry_on_the_other(api):
    """Admitting an applicant queued on two units admits one entry and cancels the other.

    Both queues empty in the same request and both queue positions go to zero, but
    only the admitting unit's beds move: the unit the applicant was merely queued on
    keeps every bed free.

    Per the PRD: "First, the applicant's entry on the admitting unit moves to `ADMITTED` with `queue_position` 0 and that unit's `waitlist_active_count` decremented by 1, while every *other* entry of this applicant on other units whose status was `ACTIVE` or `OFFERED` moves to `CANCELLED` with `offer_expires_at` cleared, `queue_position` 0, each of those units' `waitlist_active_count` decremented by 1 and each of those units' `version` incremented."

    Design: Corner/state_machines/sm_waitlist_entry_cancelled_on_admission_to_other_unit
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    home = fx.create_home(api)
    unit_a = fx.create_unit(
        api, home["id"], care_level="NURSING", licensed_bed_count=2, out_of_service_bed_count=0
    )
    unit_b = fx.create_unit(
        api, home["id"], care_level="NURSING", licensed_bed_count=2, out_of_service_bed_count=0
    )
    applicant = fx.create_applicant(
        api,
        home["id"],
        requested_care_level="NURSING",
        application_received_date="2026-08-01",
        service_connected_disability_pct=80,
        state_residency_years=6,
    )
    fx.determine_eligibility(api, applicant["id"])
    entry_a = fx.create_waitlist_entry(api, applicant["id"], unit_a["id"])
    entry_b = fx.create_waitlist_entry(api, applicant["id"], unit_b["id"])
    assert entry_b["status"] == "ACTIVE"
    assert entry_b["queue_position"] == 1

    assessment = fx.create_assessment(
        api,
        applicant["id"],
        DEFAULT_ASSESSOR_USER,
        assessed_care_level="NURSING",
        assessment_date="2026-08-01",
    )
    fx.submit_assessment(api, assessment["id"], DEFAULT_ASSESSOR_USER)
    assert fx.read_unit(api, unit_a["id"])["waitlist_active_count"] == 1

    resident = validate_success(
        fx.approve_admission(
            api,
            applicant["id"],
            unit_a["id"],
            assessment["id"],
            "2026-08-01",
            DEFAULT_COORDINATOR_USER,
        ),
        201,
    )
    assert resident["care_unit_id"] == unit_a["id"]
    assert fx.read_applicant(api, applicant["id"])["status"] == "ADMITTED"

    entries, meta = _applicant_entry_rows(api, applicant["id"])
    assert meta["total_count"] == 2
    assert entries[entry_a["id"]]["status"] == "ADMITTED"
    assert entries[entry_a["id"]]["queue_position"] == 0
    assert entries[entry_b["id"]]["status"] == "CANCELLED"
    assert entries[entry_b["id"]]["queue_position"] == 0

    admitting = fx.read_unit(api, unit_a["id"])
    assert admitting["waitlist_active_count"] == 0
    assert admitting["occupied_bed_count"] == 1
    assert admitting["available_bed_count"] == 1
    assert admitting["operational_posture"] == "OPEN"

    untouched = fx.read_unit(api, unit_b["id"])
    assert untouched["waitlist_active_count"] == 0
    assert untouched["occupied_bed_count"] == 0
    assert untouched["available_bed_count"] == 2


def test_discharge_voids_draft_plans_and_supersedes_the_active_one(api, assessor_headers):
    """The discharge cascade is status-conditional: the active plan is superseded, the draft is voided.

    One resident holds an ACTIVE plan and a second plan that was never activated.
    Discharge closes billing, frees the bed and returns the unit to OPEN, and the
    two plans take different exits according to the status each was in.

    Per the PRD: "Every one of the resident's plans still in `DRAFT` moves to `VOID`, and every plan that was `ACTIVE` or `REVIEW_DUE` moves to `SUPERSEDED`."
    The PRD also says: "Discharge sets `occupancy_status` to `DISCHARGED`, stores `discharge_date` and `discharge_reason`, sets `billing_status` to `CLOSED`, and sets `bed_hold_active` to false while leaving `bed_hold_started_on` in place."

    Design: Corner/state_machines/sm_discharge_voids_draft_and_supersedes_active_care_plans
    """
    scenario = fx.admitted_resident(
        api,
        admission_date="2026-08-01",
        care_level="NURSING",
        licensed_bed_count=2,
        out_of_service_bed_count=0,
    )
    active_plan = fx.activate_care_plan(
        api,
        scenario.resident_id,
        care_level="NURSING",
        plan_date="2026-08-01",
        adl_support_level="HIGH",
        assessor_user_id=DEFAULT_ASSESSOR_USER,
    )
    draft_plan = validate_success(
        api.create_care_plan(
            scenario.resident_id,
            f.care_plan_payload(
                care_level="NURSING", adl_support_level="MODERATE", plan_date="2026-08-01"
            ),
            assessor_headers,
        ),
        201,
    )
    assert draft_plan["status"] == "DRAFT"

    fx.set_clock(api, "2026-08-10T00:00:00Z")
    discharged = validate_success(
        fx.discharge(api, scenario.resident_id, "2026-08-10", "VOLUNTARY"), 200
    )
    assert discharged["occupancy_status"] == "DISCHARGED"
    assert discharged["billing_status"] == "CLOSED"
    assert discharged["discharge_date"] == "2026-08-10"
    assert discharged["discharge_reason"] == "VOLUNTARY"
    assert discharged["bed_hold_active"] is False

    plans, meta = validate_paginated(
        api.list_care_plans(
            assessor_headers, {"resident_id": scenario.resident_id, "limit": 100}
        )
    )
    assert meta["total_count"] == 2
    by_id = {plan["id"]: plan for plan in plans}
    assert by_id[active_plan["id"]]["status"] == "SUPERSEDED"
    assert by_id[draft_plan["id"]]["status"] == "VOID"

    unit = fx.read_unit(api, scenario.unit_id)
    assert unit["occupied_bed_count"] == 0
    assert unit["available_bed_count"] == 2
    assert unit["operational_posture"] == "OPEN"
