"""What intake writes, and what it leaves for the scoring run to write.

Registration seeds a whole capacity ledger; a submission derives its own expiry
and carries a default extended reporting period; and the derived fields on
disclosure packages and litigation events stay at 0 until a scoring run of the
right variant consumes them. Litigation events are the one append-only record.
"""

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    COMPLIANCE,
    UNDERWRITER,
    assert_capacity_derivation,
    assert_disclosure_package,
    assert_insured,
    assert_instant_equals,
    assert_litigation_event,
    assert_money,
    assert_risk_band_matches_score,
    assert_submission,
    create_insured_payload,
    create_litigation_event_payload,
    create_submission_payload,
    file_litigation_event,
    open_submission,
    read_insured,
    register_insured,
    run_scoring,
    setup_insured_with_history,
    setup_scored_submission,
)

SECURITIES_MATTER = {
    "case_type": "SECURITIES_CLASS_ACTION",
    "filed_date": "2024-06-15T00:00:00Z",
    "resolved_date": "2025-01-15T00:00:00Z",
    "indemnity_paid_usd": 4_000_000,
    "outcome": "SETTLED",
}
MERGER_OBJECTION_MATTER = {
    "case_type": "MERGER_OBJECTION",
    "filed_date": "2025-01-10T00:00:00Z",
    "resolved_date": "2025-06-01T00:00:00Z",
    "indemnity_paid_usd": 0,
    "outcome": "SETTLED",
}


def test_registering_an_insured_seeds_its_whole_capacity_ledger(api):
    """PRD 3.1: "A freshly registered insured starts with
    `aggregate_bound_side_c_usd` at 0, `available_side_c_capacity_usd` equal to
    `entity_capacity_cap_usd`, `capacity_posture` `OPEN` and `open_policy_count` at
    0." Two fields may be omitted: "`control_status`, which defaults to
    `INDEPENDENT` and is otherwise `CHANGE_OF_CONTROL_ANNOUNCED` or `ACQUIRED`, and
    `change_of_control_date`, which defaults to null". PRD 2.4: every record carries
    "`version`, an integer that begins at 1 when the record is inserted".

    Design: Corner/entities/insured_creation_initializes_capacity_fields
    """
    response = api.create_insured(create_insured_payload(), UNDERWRITER)

    data = validate_success(response, 201)
    assert_insured(data)
    assert data["legal_name"] == "Vantiq Bio Inc"
    assert data["sector_code"] == "BIOTECH"
    assert data["exchange_listing"] == "LISTED"
    assert data["market_cap_usd"] == pytest.approx(1_800_000_000, abs=0.01)
    assert data["fiscal_year_end"] == "12-31"
    assert_money(data["entity_capacity_cap_usd"], 25_000_000, "entity_capacity_cap_usd")

    assert data["control_status"] == "INDEPENDENT", "the omitted field takes its default"
    assert data["change_of_control_date"] is None

    assert_money(data["aggregate_bound_side_c_usd"], 0, "aggregate_bound_side_c_usd")
    # The whole cap is available before any Side C part exists.
    assert_money(data["available_side_c_capacity_usd"], 25_000_000,
                 "available_side_c_capacity_usd")
    assert data["capacity_posture"] == "OPEN"
    assert data["open_policy_count"] == 0
    assert_capacity_derivation(data)

    assert data["version"] == 1
    assert_instant_equals(data["created_at"], "2026-08-01T00:00:00Z", "created_at")
    assert_instant_equals(data["updated_at"], "2026-08-01T00:00:00Z", "updated_at")


def test_a_new_submission_defaults_its_reporting_period_and_derives_its_expiry(api):
    """PRD 3.2: "One optional field, `erp_days`, sets the extended reporting period
    in days added to the end of the period for claim notice and circumstance
    reporting; it defaults to 90 and must be at least 0." PRD 3.2: "A new submission
    is created with `status` `DRAFT` and with `expires_at` set to its `created_at`
    plus 90 days."

    Design: Corner/entities/submission_defaults_erp_days_and_ninety_day_expiry
    """
    insured = register_insured()

    without_erp = create_submission_payload(insured["id"])
    del without_erp["erp_days"]

    data = validate_success(api.create_submission(without_erp, UNDERWRITER), 201)
    assert_submission(data)
    assert data["erp_days"] == 90, "the declared default, not null and not 0"
    assert data["status"] == "DRAFT"
    assert data["insured_id"] == insured["id"]
    assert_instant_equals(data["created_at"], "2026-08-01T00:00:00Z", "created_at")
    assert_instant_equals(data["expires_at"], "2026-10-30T00:00:00Z", "expires_at")
    assert data["version"] == 1

    # 0 is a legitimate supplied value, which is what makes 90 a default rather
    # than a floor the intake clamps to.
    no_tail = validate_success(
        api.create_submission(
            create_submission_payload(insured["id"], erp_days=0), UNDERWRITER
        ),
        201,
    )
    assert no_tail["erp_days"] == 0
    assert_instant_equals(no_tail["expires_at"], "2026-10-30T00:00:00Z", "expires_at")


def test_a_scored_submission_reads_back_the_same_band_for_every_reader(api):
    """PRD 3.2: "Every accepted run overwrites `risk_score`, `risk_band`,
    `litigation_units` and `disclosure_packages_considered`, sets `score_variant` to
    the requested variant and `scored_at` to the logical-clock reading". PRD 2.1:
    "Every read (`GET`) endpoint is open to all four roles." PRD 2.4: `version` is
    "an integer that begins at 1 when the record is inserted and increases by exactly
    1 on every successful write to it".

    Design: Corner/entities/get_submission_after_score_returns_stored_band_and_counters
    """
    scenario = setup_scored_submission()
    submission_id = scenario["submission"]["id"]

    data = validate_success(api.get_submission(submission_id, COMPLIANCE), 200)

    assert_submission(data)
    assert data["id"] == submission_id
    assert data["insured_id"] == scenario["insured"]["id"]
    assert data["status"] == "SCORED"
    assert data["risk_score"] == pytest.approx(85.80, abs=0.01)
    assert data["risk_band"] == "ELEVATED"
    assert_risk_band_matches_score(data)
    assert data["score_variant"] == "INDICATIVE"
    assert data["litigation_units"] == pytest.approx(20.00, abs=0.01)
    assert data["disclosure_packages_considered"] == 1
    assert_instant_equals(data["scored_at"], "2026-08-01T00:00:00Z", "scored_at")
    assert_instant_equals(data["expires_at"], "2026-10-30T00:00:00Z", "expires_at")
    assert data["version"] == 2, "one insert plus one scoring write"

    again = validate_success(api.get_submission(submission_id, UNDERWRITER), 200)
    assert again["version"] == 2, "a read is not a write, so it bumps nothing"
    assert again["risk_score"] == pytest.approx(85.80, abs=0.01)
    assert again["scored_at"] == data["scored_at"]


def test_the_scoring_run_writes_weight_units_only_where_its_input_set_reached(api):
    """PRD 3.1: "As with a disclosure package, a newly filed event's `weight_units`
    reads 0 until a scoring run consumes it." PRD 3.2, on the `INDICATIVE` input
    set: "It reads only those litigation events whose `case_type` is
    `SECURITIES_CLASS_ACTION` or `REGULATORY_ENFORCEMENT`." PRD 3.2: "An event's
    `weight_units`, written back onto the event, is its case-type weight multiplied
    by that factor, where the case-type weights are 20 for
    `SECURITIES_CLASS_ACTION`, 15 for `REGULATORY_ENFORCEMENT`, 12 for `DERIVATIVE`,
    8 for `FIDUCIARY`, 5 for `MERGER_OBJECTION` and 3 for `EMPLOYMENT_PRACTICES`."
    PRD 3.2: "Each consumed package yields two subscores, written back onto the
    package itself."

    Design: Corner/entities/litigation_event_weight_units_written_by_scoring_run
    """
    scenario = setup_insured_with_history(
        litigation_overrides=[SECURITIES_MATTER, MERGER_OBJECTION_MATTER]
    )
    insured_id = scenario["insured"]["id"]
    securities, merger_objection = scenario["events"]

    for event in scenario["events"]:
        assert_litigation_event(event)
        assert event["weight_units"] == pytest.approx(0, abs=0.01), (
            "creation writes no weight at all"
        )

    scored = run_scoring(open_submission(insured_id)["id"], "INDICATIVE")
    assert scored["risk_score"] == pytest.approx(85.80, abs=0.01), (
        "round((24.00 + 22.00 + 20.00) x 1.30, 2), the MERGER_OBJECTION excluded"
    )
    assert scored["risk_band"] == "ELEVATED"
    assert scored["litigation_units"] == pytest.approx(20.00, abs=0.01)

    events, events_meta = validate_paginated(
        api.list_litigation_events(insured_id, UNDERWRITER,
                                  params={"limit": 10, "offset": 0})
    )
    assert events_meta["total_count"] == 2
    by_id = {event["id"]: event for event in events}
    assert by_id[securities["id"]]["weight_units"] == pytest.approx(20.00, abs=0.01), (
        "20 for SECURITIES_CLASS_ACTION at a recency factor of 1.0"
    )
    assert by_id[merger_objection["id"]]["weight_units"] == pytest.approx(0.00, abs=0.01), (
        "the INDICATIVE input set never reached the merger objection"
    )

    packages, packages_meta = validate_paginated(
        api.list_disclosure_packages(insured_id, UNDERWRITER,
                                     params={"limit": 10, "offset": 0})
    )
    assert packages_meta["total_count"] == 1
    package = packages[0]
    assert_disclosure_package(package)
    assert package["financial_subscore"] == pytest.approx(24.00, abs=0.01), (
        "18 for the restatement plus 6 for one material weakness"
    )
    assert package["governance_subscore"] == pytest.approx(22.00, abs=0.01), (
        "14 for independence below 0.50 plus 8 for the combined chair"
    )


def test_a_litigation_matter_is_corrected_by_appending_another_one(api):
    """PRD 2.4: "A litigation event is write-once at creation: it carries only `id`
    and `created_at`. It has neither `updated_at` nor `version`, exposes no update
    endpoint and takes no concurrency token." PRD 3.1: "Three fields are optional:
    `resolved_date`, which defaults to null and whose absence is how the system knows
    the matter is still open; `indemnity_paid_usd`, which defaults to 0 and must be
    at least 0, recording indemnity already paid on the matter by any carrier or by
    the insured itself; and `outcome`, which defaults to null".

    Design: Corner/entities/litigation_event_carries_no_version_and_no_update_path
    """
    insured = register_insured()

    bare = create_litigation_event_payload(
        insured["id"], case_type="REGULATORY_ENFORCEMENT",
        filed_date="2026-02-02T00:00:00Z", resolved_date=None,
    )
    del bare["indemnity_paid_usd"]
    del bare["outcome"]

    pending = validate_success(
        api.create_litigation_event(insured["id"], bare, UNDERWRITER), 201
    )
    assert_litigation_event(pending)
    assert pending["case_type"] == "REGULATORY_ENFORCEMENT"
    assert pending["resolved_date"] is None, "an open matter carries no resolution date"
    assert pending["indemnity_paid_usd"] == pytest.approx(0, abs=0.01)
    assert pending["outcome"] is None
    assert pending["weight_units"] == pytest.approx(0, abs=0.01)
    assert "version" not in pending
    assert "updated_at" not in pending

    correction = file_litigation_event(
        insured["id"], case_type="REGULATORY_ENFORCEMENT",
        filed_date="2026-02-02T00:00:00Z", resolved_date="2026-06-30T00:00:00Z",
        indemnity_paid_usd=750_000, outcome="SETTLED",
    )
    assert_litigation_event(correction)
    assert "version" not in correction
    assert correction["id"] != pending["id"]

    events, meta = validate_paginated(
        api.list_litigation_events(insured["id"], UNDERWRITER,
                                  params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2, "the correction is an extra row, not an edit"
    still_open = {event["id"]: event for event in events}[pending["id"]]
    assert still_open["resolved_date"] is None
    assert still_open["outcome"] is None
    assert read_insured(insured["id"])["version"] == 1, (
        "appending history is not a write to the insured"
    )


def test_a_package_filed_under_an_unknown_insured_answers_for_the_parent(api):
    """PRD 2.8: "The first identifier that matches no stored record ends the request
    immediately with that resource's own not-found error and HTTP 404:
    `ERR_INSURED_NOT_FOUND` for an insured-scoped path". PRD 2.7 ranks "Path resource
    existence, left to right" third and "Request shape — `ERR_INVALID_REQUEST`, on
    every write endpoint: the body must parse, every required field must be present"
    fifth, and "checks are evaluated in ascending order and the first one violated
    determines the response".

    Design: Corner/entities/disclosure_package_under_unknown_insured_returns_insured_not_found
    """
    insured = register_insured()

    # The body is also short of independent_director_ratio and the four governance
    # flags, so the shape rule would reject it too if it were reached.
    incomplete = {
        "fiscal_year": 2025,
        "filed_date": "2026-03-01T00:00:00Z",
        "restatement_flag": False,
        "material_weakness_count": 0,
        "going_concern_flag": False,
        "negative_operating_cash_flow_flag": False,
        "debt_to_equity": 0.4,
    }

    validate_error(
        api.create_disclosure_package(NON_EXISTENT_UUID, incomplete, UNDERWRITER),
        ApiErrorId.ERR_INSURED_NOT_FOUND,
        404,
    )

    _, meta = validate_paginated(
        api.list_disclosure_packages(insured["id"], UNDERWRITER,
                                     params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0, "the refused call persisted nothing"


def test_intake_reports_the_enum_the_period_and_the_target_as_three_rules(api):
    """PRD 3.1: "`sector_code` is one of `TECH`, `BIOTECH`, `FINANCIAL`, `ENERGY`,
    `INDUSTRIAL` or `CONSUMER`", and PRD 2.7's shape rule requires that "every enum
    value must be a declared member". PRD 3.2: "`requested_period_end` must be
    strictly later than `requested_period_start`, or the submission is refused with
    `ERR_PERIOD_INVALID`, and `requested_program_target_limit_usd` must be greater
    than or equal to `requested_limit_usd`, or it is refused with
    `ERR_PROGRAM_TARGET_BELOW_LIMIT`." PRD 2.7 ranks the period rule sixth and the
    programme-target rule seventh, and "The ordering is normative, not descriptive".

    Design: Corner/entities/submission_range_constraints_reject_before_business_rules
    """
    insured = register_insured()

    validate_error(
        api.create_insured(
            create_insured_payload(legal_name="Helios Grid Corp",
                                   sector_code="UTILITIES",
                                   market_cap_usd=900_000_000,
                                   fiscal_year_end="06-30",
                                   entity_capacity_cap_usd=10_000_000),
            UNDERWRITER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        422,
    )

    validate_error(
        api.create_submission(
            create_submission_payload(insured["id"],
                                      requested_period_end="2026-09-01T00:00:00Z"),
            UNDERWRITER,
        ),
        ApiErrorId.ERR_PERIOD_INVALID,
        422,
    )

    validate_error(
        api.create_submission(
            create_submission_payload(insured["id"],
                                      requested_program_target_limit_usd=8_000_000),
            UNDERWRITER,
        ),
        ApiErrorId.ERR_PROGRAM_TARGET_BELOW_LIMIT,
        422,
    )

    # Both cross-field rules are broken at once, and the earlier rung answers.
    validate_error(
        api.create_submission(
            create_submission_payload(insured["id"],
                                      requested_period_end="2026-09-01T00:00:00Z",
                                      requested_program_target_limit_usd=8_000_000),
            UNDERWRITER,
        ),
        ApiErrorId.ERR_PERIOD_INVALID,
        422,
    )

    _, meta = validate_paginated(
        api.list_submissions(UNDERWRITER, params={"insured_id": insured["id"]})
    )
    assert meta["total_count"] == 0, "none of the four refusals persisted a row"
