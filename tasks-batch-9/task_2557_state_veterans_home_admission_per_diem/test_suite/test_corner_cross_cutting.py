"""Cross-cutting layers: version pinning, version counters and cascade extent.

Three writes in this API demand that the client name the version it observed, and
each of these tests issues the same request twice — once with a version that has
moved and once with the observed one — so that the rejection is shown to be the
version token rather than the state of the record. Two further tests pin the
counter those tokens are compared against, and the exact distance a certification
cascade travels when the survey score lands inside the conditional band.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CARE_UNIT_VERSION_STALE,
    ERR_CLAIM_STATE_INVALID,
    ERR_CLAIM_VERSION_STALE,
    ERR_RESIDENT_VERSION_STALE,
    ERR_UNIT_NOT_CERTIFIED,
)
from test_helpers.assertions import assert_immutable_record_fields
from test_helpers.test_users import DEFAULT_ASSESSOR_USER


def _recognized_home_with_nursing_unit(api):
    """One recognised home with one certified two-bed nursing unit and no residents."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    home = fx.create_home(api)
    unit = fx.create_unit(
        api, home["id"], care_level="NURSING", licensed_bed_count=2, out_of_service_bed_count=0
    )
    return home, unit


def _queued_applicant_with_submitted_assessment(api):
    """A recognised home, a certified nursing unit and one waitlisted applicant.

    The applicant is eligible, holds an ACTIVE entry on the unit and carries a
    SUBMITTED nursing assessment written by an assessor who is not the coordinator,
    which is the state an admission decision needs.
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
        DEFAULT_ASSESSOR_USER,
        assessed_care_level="NURSING",
        assessment_date="2026-08-01",
    )
    fx.submit_assessment(api, assessment["id"], DEFAULT_ASSESSOR_USER)
    return home, unit, applicant, entry, assessment


def test_a_stale_care_unit_version_rejects_the_admission_decision_and_writes_nothing(
    api, coordinator_headers
):
    """A version one behind the unit's own is refused, and the retry with the observed one admits.

    Per the PRD: "Recording an admission decision requires `expected_care_unit_version`, carrying the client's last observed `version` of the target `CareUnit`."
    Per the PRD: "If that value does not equal the unit's current `version`, the decision is rejected with `ERR_CARE_UNIT_VERSION_STALE` (HTTP 412)."
    Nothing is written on the refusal: the unit's version does not move, no bed is
    consumed, and the applicant stays waitlisted, because the applicant only
    advances on the approving branch.
    Per the PRD: "On `APPROVED`, the applicant's `status` becomes `ADMITTED`, the cited assessment's `status` becomes `ACCEPTED`, and a **resident** record is created."

    Design: Corner/cross_cutting_layers/occ_stale_care_unit_version_rejected_on_admission_decision
    """
    _home, unit, applicant, _entry, assessment = _queued_applicant_with_submitted_assessment(api)

    observed = fx.read_unit(api, unit["id"])
    assert observed["occupied_bed_count"] == 0

    stale_decision = f.admission_decision_payload(
        unit["id"], assessment["id"], observed["version"] - 1, "2026-08-01", "APPROVED"
    )
    validate_error(
        api.admission_decision(applicant["id"], stale_decision, coordinator_headers),
        ERR_CARE_UNIT_VERSION_STALE,
        412,
    )

    after_refusal = fx.read_unit(api, unit["id"])
    assert after_refusal["version"] == observed["version"]
    assert after_refusal["occupied_bed_count"] == 0
    assert fx.read_applicant(api, applicant["id"])["status"] == "WAITLISTED"

    fresh_decision = f.admission_decision_payload(
        unit["id"], assessment["id"], observed["version"], "2026-08-01", "APPROVED"
    )
    resident = validate_success(
        api.admission_decision(applicant["id"], fresh_decision, coordinator_headers), 201
    )
    assert resident["occupancy_status"] == "ADMITTED"

    unit_after = fx.read_unit(api, unit["id"])
    assert unit_after["occupied_bed_count"] == 1
    assert unit_after["available_bed_count"] == 1


def test_a_stale_resident_version_rejects_the_cost_share_determination(api, bom_headers):
    """A determination pinned to a stale resident version creates no row at all.

    Per the PRD: "Creating a cost-share determination requires `expected_resident_version`, carrying the client's last observed `version` of the target `Resident`."
    Per the PRD: "A mismatch with the resident's current `version` is rejected with `ERR_RESIDENT_VERSION_STALE` (HTTP 412)."
    With no income record for the month the accepted determination computes to
    nothing, which isolates the version pin from the cost-share waterfall:
    "**Net before the medical deduction** is `gross_countable_income_cents` less `pna_deduction_cents`, floored at zero."
    Per the PRD: "For `PROVISIONAL`, `monthly_cost_share_cents` is `tiered_share_cents` less `federal_per_diem_offset_cents` (which is zero), multiplied by `resident_day_count`, divided by the number of calendar days in `effective_month`, rounded half up, and finally floored at zero."

    Design: Corner/cross_cutting_layers/occ_stale_resident_version_rejected_on_cost_share_determination
    """
    scenario = fx.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )

    observed = fx.read_resident(api, scenario.resident_id)
    assert observed["monthly_cost_share_cents"] == 0

    stale_payload = f.cost_share_payload(
        observed["version"] - 1, variant="PROVISIONAL", effective_month="2026-08"
    )
    validate_error(
        api.create_cost_share_determination(scenario.resident_id, stale_payload, bom_headers),
        ERR_RESIDENT_VERSION_STALE,
        412,
    )

    _rows, meta_after_refusal = validate_paginated(
        api.list_cost_share_determinations(
            scenario.resident_id, bom_headers, {"effective_month": "2026-08", "limit": 10}
        )
    )
    assert meta_after_refusal["total_count"] == 0
    assert fx.read_resident(api, scenario.resident_id)["version"] == observed["version"]

    fresh_payload = f.cost_share_payload(
        observed["version"], variant="PROVISIONAL", effective_month="2026-08"
    )
    determination = validate_success(
        api.create_cost_share_determination(scenario.resident_id, fresh_payload, bom_headers),
        201,
    )
    assert determination["variant"] == "PROVISIONAL"
    assert determination["effective_month"] == "2026-08"
    assert determination["monthly_cost_share_cents"] == 0
    assert_immutable_record_fields(determination)

    rows, meta_after_success = validate_paginated(
        api.list_cost_share_determinations(
            scenario.resident_id, bom_headers, {"effective_month": "2026-08", "limit": 10}
        )
    )
    assert meta_after_success["total_count"] == 1
    assert rows[0]["id"] == determination["id"]


def test_a_stale_claim_version_outranks_the_illegal_correction_target(api, bom_headers):
    """A draft is an illegal correction target, yet a stale token is still what comes back.

    Per the PRD: "A correcting claim may be opened only against a claim whose `status` is `PAID` or `REJECTED` — a `DRAFT` or `SUBMITTED` target yields `ERR_CLAIM_STATE_INVALID`, and a `VOID` one likewise — and the request must carry `expected_claim_version` matching the target's current `version`, or `ERR_CLAIM_VERSION_STALE` (HTTP 412)."
    The version token is compared first, so the same call against the same draft
    answers 412 with the stale token and 409 with the observed one.
    Per the PRD: "A stale version is reported *before* any state or capacity check, so a coordinator holding a stale `expected_care_unit_version` learns that their view is out of date rather than that the bed is gone."
    Neither refusal writes: the target keeps its version and its status, and no
    correcting claim exists to point back at it.
    Per the PRD: "A new claim starts `DRAFT` with `correction_generation` 0 and `corrects_claim_id`, `submitted_at`, `adjudicated_at`, `paid_amount_cents`, `rejection_code` and `adjudication_note` all null, and `recognition_verified` false."

    Design: Corner/cross_cutting_layers/occ_stale_claim_version_outranks_claim_state_invalid
    """
    home, unit = _recognized_home_with_nursing_unit(api)

    claim = validate_success(
        fx.open_claim(api, home["id"], unit["id"], claim_month="2026-07"), 201
    )
    assert claim["status"] == "DRAFT"
    assert claim["correction_generation"] == 0
    assert claim["corrects_claim_id"] is None

    observed = fx.read_claim(api, claim["id"])
    observed_version = observed["version"]

    validate_error(
        api.correct_per_diem_claim(
            claim["id"],
            f.correction_payload(observed_version - 1, "stale token"),
            bom_headers,
        ),
        ERR_CLAIM_VERSION_STALE,
        412,
    )
    validate_error(
        api.correct_per_diem_claim(
            claim["id"],
            f.correction_payload(observed_version, "fresh token"),
            bom_headers,
        ),
        ERR_CLAIM_STATE_INVALID,
        409,
    )

    after = fx.read_claim(api, claim["id"])
    assert after["version"] == observed_version
    assert after["status"] == "DRAFT"

    _rows, meta = validate_paginated(
        api.list_per_diem_claims(bom_headers, {"corrects_claim_id": claim["id"], "limit": 10})
    )
    assert meta["total_count"] == 0


def test_the_home_version_moves_once_per_write_and_never_on_a_read(api, admin_headers):
    """The counter the stale-token checks compare against is itself pinned to exact literals.

    Per the PRD: "Most records additionally carry `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the record — and `version`, an integer that starts at 1 when the record is created and increments by exactly 1 on every mutation."
    Per the PRD: "A newly registered home starts with `active_resident_count` at 0, `decertified_unit_count` at 0, `recognition_suspended_reason` null, `last_survey_date` null and `version` at 1."
    Each child unit is a mutation of the parent and is itself born at 1, so the two
    counters advance independently.
    Per the PRD: "Creating a unit is a mutation of its parent home, so the home's `version` increments."
    Per the PRD: "The `GRANT` action moves a home from `PROVISIONAL` to `RECOGNIZED` and is permitted only while `decertified_unit_count` is 0; the `SUSPEND` action moves a home from `RECOGNIZED` to `SUSPENDED`; the `RESTORE` action moves a home from `SUSPENDED` back to `RECOGNIZED` and, like `GRANT`, requires `decertified_unit_count` to be 0."
    Per the PRD: "A `SUSPEND` sets `recognition_suspended_reason` to `UNIT_DECERTIFIED`; a `GRANT` or a `RESTORE` sets it back to null."
    Repeated reads in between move nothing, because a read is not a mutation.

    Design: Corner/cross_cutting_layers/occ_home_version_increments_exactly_once_per_write_and_never_on_read
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")

    home = validate_success(
        api.create_veterans_home(f.veterans_home_payload(), admin_headers), 201
    )
    assert home["version"] == 1
    assert home["recognition_status"] == "RECOGNIZED"

    nursing = validate_success(
        api.create_care_unit(
            home["id"],
            f.care_unit_payload(
                care_level="NURSING", licensed_bed_count=2, out_of_service_bed_count=0
            ),
            admin_headers,
        ),
        201,
    )
    assert nursing["version"] == 1
    assert validate_success(api.get_veterans_home(home["id"], admin_headers), 200)["version"] == 2

    domiciliary = validate_success(
        api.create_care_unit(
            home["id"],
            f.care_unit_payload(
                care_level="DOMICILIARY", licensed_bed_count=4, out_of_service_bed_count=0
            ),
            admin_headers,
        ),
        201,
    )
    assert domiciliary["version"] == 1
    assert validate_success(api.get_veterans_home(home["id"], admin_headers), 200)["version"] == 3
    assert validate_success(api.get_veterans_home(home["id"], admin_headers), 200)["version"] == 3

    suspended = validate_success(
        api.set_recognition(
            home["id"],
            f.recognition_payload("SUSPEND", "2026-08-01", "voluntary hold"),
            admin_headers,
        ),
        200,
    )
    assert suspended["version"] == 4
    assert suspended["recognition_status"] == "SUSPENDED"
    assert suspended["recognition_suspended_reason"] == "UNIT_DECERTIFIED"

    restored = validate_success(
        api.set_recognition(
            home["id"], f.recognition_payload("RESTORE", "2026-08-01"), admin_headers
        ),
        200,
    )
    assert restored["version"] == 5
    assert restored["recognition_status"] == "RECOGNIZED"
    assert restored["recognition_suspended_reason"] is None
    assert restored["decertified_unit_count"] == 0


def test_a_score_of_one_conditionally_restricts_the_unit_and_the_cascade_stops_there(
    api, admin_headers, coordinator_headers, surveyor_headers
):
    """One isolated minimal deficiency scores exactly 1, and nothing beyond the unit moves.

    Per the PRD: "The scope weights are 1 for `ISOLATED`, 2 for `PATTERN` and 4 for `WIDESPREAD`."
    Per the PRD: "The severity weights are 1 for `MINIMAL`, 3 for `MINIMAL_HARM`, 8 for `ACTUAL_HARM` and 20 for `IMMEDIATE_JEOPARDY`."
    Per the PRD: "Otherwise, a score of 25 or more decertifies; a score of at least 1 but below 25 yields `CONDITIONAL`; and a score of exactly 0 yields `CERTIFIED` — unless the unit's current `certification_status` is `DECERTIFIED`, in which case a clean survey yields `CONDITIONAL`."
    Per the PRD: "Otherwise, if `certification_status` is `CONDITIONAL`, the posture is `RESTRICTED` — a conditional unit is always restricted regardless of how many beds are free."
    Both beds stay free and the queue stays intact, while the home keeps its
    recognition and only takes the survey date.
    Per the PRD: "Every survey, whatever its outcome, writes `last_survey_compliance_score`, sets the unit's `last_survey_date` to the supplied `survey_date`, sets the operating home's `last_survey_date` to the same value, recomputes `operational_posture`, and increments the unit's `version`."
    The admission decision then fails on certification rather than on posture or on
    beds, because that gate demands the exact value.
    Per the PRD: "Before either branch runs, the decision passes a long gate sequence in the ladder order of §2.11: the applicant must be `WAITLISTED`; `expected_care_unit_version` must equal the target unit's current `version`, else `ERR_CARE_UNIT_VERSION_STALE`; the cited assessment must belong to this applicant and be `SUBMITTED`, else `ERR_ASSESSMENT_STATE_INVALID`; the acting `X-User-ID` must differ from that assessment's `assessor_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; the target unit's `certification_status` must be exactly `CERTIFIED`, else `ERR_UNIT_NOT_CERTIFIED`; the target unit's `operational_posture` must be `OPEN`, else `ERR_UNIT_POSTURE_BLOCKED`; the cited assessment's `assessed_care_level` must equal the target unit's `care_level`, else `ERR_CARE_LEVEL_MISMATCH`; the applicant must hold an entry on that very unit whose status is `ACTIVE` or `OFFERED`, else `ERR_NO_WAITLIST_ENTRY_FOR_UNIT` (HTTP 409); and the unit must have at least one free bed in `available_bed_count`, else `ERR_NO_AVAILABLE_BED` (HTTP 409)."
    A fresh queue placement is still accepted, because placement asks a weaker
    question of the same field.
    Per the PRD: "The unit must not be `DECERTIFIED`, or the placement is rejected with `ERR_UNIT_NOT_CERTIFIED` (HTTP 409)."
    Per the PRD: "A new entry starts with status `ACTIVE` — the queue lifecycle runs across `ACTIVE`, `OFFERED`, `ADMITTED`, `EXPIRED` and `CANCELLED`, of which the last three are terminal."
    Per the PRD: "`waitlist_active_count` on a unit is the number of waitlist entries on that unit whose status is either `ACTIVE` or `OFFERED`; entries in any other status do not count."
    Per the PRD: "Only a certified unit with at least one free bed is `OPEN`."

    Design: Corner/cross_cutting_layers/layer_cascading_side_effects_stops_inside_the_conditional_band
    """
    home, unit, applicant_a, entry_a, assessment_a = _queued_applicant_with_submitted_assessment(
        api
    )

    conditional = validate_success(
        api.record_survey_result(
            unit["id"],
            f.survey_result_payload("2026-08-01", [f.deficiency("ISOLATED", "MINIMAL")]),
            surveyor_headers,
        ),
        200,
    )
    assert conditional["last_survey_compliance_score"] == 1
    assert conditional["certification_status"] == "CONDITIONAL"
    assert conditional["operational_posture"] == "RESTRICTED"
    assert conditional["available_bed_count"] == 2
    assert conditional["waitlist_active_count"] == 1
    assert conditional["last_survey_date"] == "2026-08-01"

    home_after_survey = validate_success(api.get_veterans_home(home["id"], admin_headers), 200)
    assert home_after_survey["decertified_unit_count"] == 0
    assert home_after_survey["recognition_status"] == "RECOGNIZED"
    assert home_after_survey["recognition_suspended_reason"] is None
    assert home_after_survey["last_survey_date"] == "2026-08-01"

    active_entries, active_meta = validate_paginated(
        api.list_unit_waitlist_entries(
            unit["id"], coordinator_headers, {"status": "ACTIVE", "limit": 10}
        )
    )
    assert active_meta["total_count"] == 1
    assert active_entries[0]["id"] == entry_a["id"]

    conditional_version = fx.read_unit(api, unit["id"])["version"]
    validate_error(
        api.admission_decision(
            applicant_a["id"],
            f.admission_decision_payload(
                unit["id"], assessment_a["id"], conditional_version, "2026-08-01", "APPROVED"
            ),
            coordinator_headers,
        ),
        ERR_UNIT_NOT_CERTIFIED,
        409,
    )

    applicant_b = fx.create_applicant(
        api,
        home["id"],
        date_of_birth="1947-06-06",
        service_connected_disability_pct=40,
        state_residency_years=4,
        requested_care_level="NURSING",
        application_received_date="2026-08-01",
    )
    fx.determine_eligibility(api, applicant_b["id"])
    entry_b = validate_success(
        api.create_waitlist_entry(
            f.waitlist_entry_payload(applicant_b["id"], unit["id"]), coordinator_headers
        ),
        201,
    )
    assert entry_b["status"] == "ACTIVE"

    recertified = validate_success(
        api.record_survey_result(
            unit["id"], f.survey_result_payload("2026-08-01", []), surveyor_headers
        ),
        200,
    )
    assert recertified["last_survey_compliance_score"] == 0
    assert recertified["certification_status"] == "CERTIFIED"
    assert recertified["operational_posture"] == "OPEN"
    assert recertified["waitlist_active_count"] == 2

    recertified_version = fx.read_unit(api, unit["id"])["version"]
    resident = validate_success(
        api.admission_decision(
            applicant_a["id"],
            f.admission_decision_payload(
                unit["id"], assessment_a["id"], recertified_version, "2026-08-01", "APPROVED"
            ),
            coordinator_headers,
        ),
        201,
    )
    assert resident["occupancy_status"] == "ADMITTED"

    final_unit = fx.read_unit(api, unit["id"])
    assert final_unit["occupied_bed_count"] == 1
    assert final_unit["available_bed_count"] == 1
    assert final_unit["waitlist_active_count"] == 1
    assert final_unit["operational_posture"] == "OPEN"
