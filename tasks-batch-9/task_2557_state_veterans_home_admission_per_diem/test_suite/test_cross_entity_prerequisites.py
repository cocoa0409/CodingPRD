"""One request, several answers, because a neighbouring entity is what decides.

In each scenario the request payload never changes. What changes is the state of
some other record — the unit's certification, the home's recognition, the
resident's governing care plan — and that alone flips the outcome.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CARE_LEVEL_MISMATCH,
    ERR_HOME_NOT_RECOGNIZED,
    ERR_NO_ACTIVE_CARE_PLAN,
    ERR_UNIT_NOT_CERTIFIED,
)
from test_helpers.test_users import make_admissions_coordinator_headers


def _admissible_applicant_on_a_conditional_unit(api):
    """An applicant ready for admission into a unit that a survey has made conditional.

    Everything the applicant controls is in order — eligible, queued on this very
    unit, assessment submitted at the unit's care level — and the survey lands last,
    so only the unit's certification stands between them and a bed.
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    home = fx.create_home(api)
    unit = fx.create_unit(api, home["id"], care_level="NURSING", licensed_bed_count=2)
    applicant = fx.create_applicant(
        api, home["id"], requested_care_level="NURSING", application_received_date="2026-08-01"
    )
    fx.determine_eligibility(api, applicant["id"])
    fx.create_waitlist_entry(api, applicant["id"], unit["id"])
    assessment = fx.create_assessment(
        api, applicant["id"], assessed_care_level="NURSING", assessment_date="2026-08-01"
    )
    fx.submit_assessment(api, assessment["id"])
    surveyed = fx.record_survey(
        api,
        unit["id"],
        "2026-08-01",
        [
            f.deficiency("ISOLATED", "ACTUAL_HARM"),
            f.deficiency("WIDESPREAD", "MINIMAL_HARM"),
            f.deficiency("PATTERN", "MINIMAL"),
            f.deficiency("PATTERN", "MINIMAL"),
        ],
    )
    return home, unit, applicant, assessment, surveyed


def test_a_conditional_unit_cannot_be_admitted_into(api):
    """An unblemished applicant is refused because the unit is merely conditional.

    Per the PRD: "the target unit's `certification_status` must be exactly
    `CERTIFIED`, else `ERR_UNIT_NOT_CERTIFIED`". The applicant cannot influence
    that field at all.

    Design: Difficulty/cross_entity_state_dependency/admission_requires_care_unit_certified
    """
    _home, unit, applicant, assessment, surveyed = _admissible_applicant_on_a_conditional_unit(api)
    assert surveyed["certification_status"] == "CONDITIONAL"
    assert surveyed["operational_posture"] == "RESTRICTED"

    validate_error(
        fx.approve_admission(api, applicant["id"], unit["id"], assessment["id"], "2026-08-01"),
        ERR_UNIT_NOT_CERTIFIED,
        409,
    )

    assert fx.read_applicant(api, applicant["id"])["status"] == "WAITLISTED"


def test_a_clean_survey_recertifies_the_unit_and_the_same_admission_succeeds(api):
    """Nothing about the applicant changes; the unit's own certification does.

    Per the PRD: "**`CONDITIONAL` → `CERTIFIED`** on a score of exactly 0.
    `operational_posture` is recomputed from bed availability alone, so a unit with
    free beds returns to `OPEN` and a full one stays `RESTRICTED`."

    Design: Difficulty/cross_entity_state_dependency/admission_requires_care_unit_certified
    """
    _home, unit, applicant, assessment, _surveyed = _admissible_applicant_on_a_conditional_unit(api)
    validate_error(
        fx.approve_admission(api, applicant["id"], unit["id"], assessment["id"], "2026-08-01"),
        ERR_UNIT_NOT_CERTIFIED,
        409,
    )

    fx.set_clock(api, "2026-08-02T00:00:00Z")
    recertified = fx.record_survey(api, unit["id"], "2026-08-02", [])
    assert recertified["last_survey_compliance_score"] == 0
    assert recertified["certification_status"] == "CERTIFIED"
    assert recertified["operational_posture"] == "OPEN"

    resident = validate_success(
        fx.approve_admission(api, applicant["id"], unit["id"], assessment["id"], "2026-08-02"), 201
    )

    assert resident["occupancy_status"] == "ADMITTED"
    assert resident["admission_date"] == "2026-08-02"
    assert fx.read_applicant(api, applicant["id"])["status"] == "ADMITTED"
    rows = api.list_applicant_assessments(
        applicant["id"], make_admissions_coordinator_headers(), {"limit": 100}
    ).json()["data"]
    assert [row["status"] for row in rows] == ["ACCEPTED"]

    refreshed_unit = fx.read_unit(api, unit["id"])
    assert refreshed_unit["occupied_bed_count"] == 1
    assert refreshed_unit["available_bed_count"] == 1


def _drafted_august_claim_at_a_suspended_home(api):
    """A full month drafted at a home whose recognition was suspended beforehand.

    The suspension precedes claim creation deliberately, because entering
    `SUSPENDED` destroys the drafts a home already holds.
    """
    scenario = fx.billed_month(
        api, admission_date="2026-08-01", through_date="2026-08-31", care_level="NURSING"
    )
    fx.set_recognition(api, scenario.home_id, "SUSPEND", "2026-09-01", "recognition review")
    claim = validate_success(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-08", "AUDITED_BASIS"), 201
    )
    return scenario, claim


def test_a_complete_draft_cannot_be_submitted_by_an_unrecognised_home(api):
    """The bill is assembled and priced, and still refused on the home's posture.

    Per the PRD: "The home's `recognition_status` must be `RECOGNIZED`, or
    `ERR_HOME_NOT_RECOGNIZED` (HTTP 409)." The claim's own thirty-one attributed
    days are beside the point.

    Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_home_recognized
    """
    _scenario, claim = _drafted_august_claim_at_a_suspended_home(api)
    assert claim["resident_day_count"] == 31

    validate_error(fx.submit_claim(api, claim["id"]), ERR_HOME_NOT_RECOGNIZED, 409)

    refreshed = fx.read_claim(api, claim["id"])
    assert refreshed["status"] == "DRAFT"
    assert refreshed["recognition_verified"] is False


def test_restoring_recognition_lets_the_identical_submission_through(api):
    """The same call succeeds once the parent home is recognised again.

    Per the PRD: "then it sets `status` to `SUBMITTED`, stamps `submitted_at` from
    the logical clock, sets `recognition_verified` to true, sets
    `per_diem_claim_id` on every attributed census day so that each row's `claimed`
    flag becomes true, and increments both the claim's `version` and the unit's
    `version`."

    Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_home_recognized
    """
    scenario, claim = _drafted_august_claim_at_a_suspended_home(api)
    validate_error(fx.submit_claim(api, claim["id"]), ERR_HOME_NOT_RECOGNIZED, 409)

    fx.set_recognition(api, scenario.home_id, "RESTORE", "2026-09-01", "recognition restored")

    submitted = validate_success(fx.submit_claim(api, claim["id"]), 200)

    assert submitted["status"] == "SUBMITTED"
    assert submitted["recognition_verified"] is True
    assert submitted["resident_day_count"] == 31
    assert submitted["bed_hold_day_count"] == 0
    assert submitted["billable_day_count"] == 31
    assert submitted["claim_amount_cents"] == 367567
    assert submitted["census_reported_resident_count"] == 1
    assert fx.read_home(api, scenario.home_id)["recognition_status"] == "RECOGNIZED"


def _planless_resident_and_a_domiciliary_unit(api):
    """A nursing resident with no care plan at all, and a domiciliary unit to move to.

    Both units are certified with free beds, and they belong to the same home, so
    the plan is the only thing that can be wrong with the move.
    """
    scenario = fx.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )
    target = fx.add_unit(api, scenario, care_level="DOMICILIARY", licensed_bed_count=2)
    fx.set_clock(api, "2026-08-10T00:00:00Z")
    return scenario, target


def test_a_resident_with_no_governing_plan_cannot_be_transferred(api):
    """Without a plan there is no clinical authority for the move.

    Per the PRD: "the separate case of a resident holding *no* `ACTIVE` plan at all
    is checked one rung later and is rejected with `ERR_NO_ACTIVE_CARE_PLAN` (HTTP
    409)."

    Design: Difficulty/cross_entity_state_dependency/transfer_requires_active_care_plan_matching_target_level
    """
    scenario, target = _planless_resident_and_a_domiciliary_unit(api)

    validate_error(
        fx.transfer(api, scenario.resident_id, target["id"], "2026-08-10"),
        ERR_NO_ACTIVE_CARE_PLAN,
        409,
    )

    assert fx.read_resident(api, scenario.resident_id)["care_unit_id"] == scenario.unit_id


def test_a_nursing_plan_will_not_authorise_a_domiciliary_move(api):
    """An active plan at the wrong level is rejected on the level, not on its absence.

    Per the PRD: "When the resident holds an `ACTIVE` plan, that plan's
    `care_level` must equal the target unit's `care_level`, else
    `ERR_CARE_LEVEL_MISMATCH`". The request payload is byte-for-byte the one that
    previously reported a missing plan.

    Design: Difficulty/cross_entity_state_dependency/transfer_requires_active_care_plan_matching_target_level
    """
    scenario, target = _planless_resident_and_a_domiciliary_unit(api)
    validate_error(
        fx.transfer(api, scenario.resident_id, target["id"], "2026-08-10"),
        ERR_NO_ACTIVE_CARE_PLAN,
        409,
    )

    nursing_plan = fx.activate_care_plan(
        api, scenario.resident_id, care_level="NURSING", plan_date="2026-08-10"
    )
    assert nursing_plan["status"] == "ACTIVE"
    assert nursing_plan["revision_number"] == 1

    validate_error(
        fx.transfer(api, scenario.resident_id, target["id"], "2026-08-10"),
        ERR_CARE_LEVEL_MISMATCH,
        409,
    )

    assert fx.read_resident(api, scenario.resident_id)["current_care_level"] == "NURSING"


def test_a_superseding_domiciliary_plan_authorises_the_move(api):
    """Once the governing plan names the target's level, the same transfer runs.

    Per the PRD: "The resident's `care_unit_id` becomes the target and
    `current_care_level` is re-stamped from the target unit's `care_level`. The
    source unit's `occupied_bed_count` falls by 1 and the target unit's rises by 1".

    Design: Difficulty/cross_entity_state_dependency/transfer_requires_active_care_plan_matching_target_level
    """
    scenario, target = _planless_resident_and_a_domiciliary_unit(api)
    validate_error(
        fx.transfer(api, scenario.resident_id, target["id"], "2026-08-10"),
        ERR_NO_ACTIVE_CARE_PLAN,
        409,
    )
    nursing_plan = fx.activate_care_plan(
        api, scenario.resident_id, care_level="NURSING", plan_date="2026-08-10"
    )
    validate_error(
        fx.transfer(api, scenario.resident_id, target["id"], "2026-08-10"),
        ERR_CARE_LEVEL_MISMATCH,
        409,
    )

    domiciliary_plan = fx.activate_care_plan(
        api,
        scenario.resident_id,
        care_level="DOMICILIARY",
        plan_date="2026-08-10",
        adl_support_level="LOW",
        supersedes_care_plan_id=nursing_plan["id"],
    )
    assert domiciliary_plan["status"] == "ACTIVE"
    assert domiciliary_plan["revision_number"] == 2
    assert domiciliary_plan["review_due_date"] == "2026-11-08"
    assert fx.read_care_plan(api, nursing_plan["id"])["status"] == "SUPERSEDED"

    resident = validate_success(
        fx.transfer(api, scenario.resident_id, target["id"], "2026-08-10"), 200
    )

    assert resident["care_unit_id"] == target["id"]
    assert resident["current_care_level"] == "DOMICILIARY"

    source = fx.read_unit(api, scenario.unit_id)
    assert source["occupied_bed_count"] == 0
    assert source["available_bed_count"] == 2
    moved_into = fx.read_unit(api, target["id"])
    assert moved_into["occupied_bed_count"] == 1
    assert moved_into["available_bed_count"] == 1
