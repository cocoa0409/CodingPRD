"""Corner section: state_machines.

Declared transitions, initial states, terminal lockdown, non-idempotent
decisions, and the side-effect chains a plain create or a batch run fires.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (  # noqa: E402
    ERR_REQUIRED_PROGRAM_MISSING,
    ERR_TRANSITION_NOT_ALLOWED,
)
from test_helpers.assertions import (  # noqa: E402
    assert_certificate_state,
    assert_contractor_posture,
    assert_grant_state,
    assert_instant_equals,
    assert_prequalification_state,
    assert_score_equals,
    assert_site_posture,
)
from test_helpers.constants import (  # noqa: E402
    ANALYST_INSURANCE,
    ANALYST_STATISTICS,
    INITIAL_CLOCK,
)
from test_helpers.factories import (  # noqa: E402
    certificate_decision_payload,
    improvement_plan_payload,
    program_review_payload,
    statistic_decision_payload,
    statistic_payload,
)
from test_helpers.test_users import make_analyst_headers  # noqa: E402


def test_written_program_review_accept_moves_row_to_accepted(build, api):
    """ACCEPT writes the reviewer fields and leaves the dimension at NOT_STARTED.

    PRD Section 3.4: "The four clauses are evaluated in this exact order and the
    first match wins: it reads `DEFICIENT` if any required program type has a row
    whose `review_status` is `DEFICIENT`; otherwise `COMPLETE` if every required
    program type has a row whose `review_status` is either `ACCEPTED` or `WAIVED`;
    otherwise `NOT_STARTED` while the prequalification is still in `DRAFT`;
    otherwise `IN_PROGRESS`."

    Design: Corner/state_machines/written_program_review_accept_moves_row_to_accepted
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor()
    prequalification = build.open_prequalification(contractor["id"], client["id"])
    program = build.tender_program(prequalification["id"], contractor["id"], "HAZCOM")
    assert program["review_status"] == "SUBMITTED"

    reviewed = validate_success(
        api.review_program(
            program["id"],
            program_review_payload("ACCEPT", "Matches the client HazCom appendix"),
            build.manager_headers(client["id"]),
        )
    )
    assert reviewed["review_status"] == "ACCEPTED"
    assert reviewed["reviewed_by_user_id"] == client["id"]
    assert reviewed["reviewer_note"] == "Matches the client HazCom appendix"
    assert reviewed["is_required"] is True, (
        "HAZCOM is demanded by the GENERAL hazard class, so is_required must be true"
    )

    row = build.read_prequalification(prequalification["id"])
    assert_prequalification_state(
        row, status="DRAFT", document_review_status="NOT_STARTED"
    )


def test_submit_without_the_second_required_program_returns_required_program_missing(
    build, api
):
    """The precondition is the required set, not a count of tendered documents.

    PRD Section 3.4: "and every program type in the required set must have a row
    on the prequalification — merely a row, in any review position — otherwise
    `ERR_REQUIRED_PROGRAM_MISSING`."

    Design: Corner/state_machines/submit_without_the_second_required_program_returns_required_program_missing
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor()
    headers = build.contractor_headers(contractor["id"])
    prequalification = build.open_prequalification(contractor["id"], client["id"])

    # A PENDING statistic satisfies the governing-statistic check ahead of it.
    build.file_statistic(prequalification["id"], contractor["id"])
    build.tender_program(prequalification["id"], contractor["id"], "HAZCOM")

    refused = api.submit_prequalification(prequalification["id"], {}, headers)
    validate_error(refused, ERR_REQUIRED_PROGRAM_MISSING, 422)

    still_draft = build.read_prequalification(prequalification["id"])
    assert_prequalification_state(
        still_draft, status="DRAFT", provisional_composite_score=None
    )

    build.tender_program(prequalification["id"], contractor["id"], "DISCIPLINE_POLICY")
    submitted = validate_success(
        api.submit_prequalification(prequalification["id"], {}, headers)
    )
    assert_prequalification_state(submitted, status="SUBMITTED", grade=None)
    assert_score_equals(submitted["provisional_composite_score"], 80.51)


def test_grade_from_draft_status_returns_transition_not_allowed(build, api):
    """Priority 10 fires before the coverage gate at priority 28.

    PRD Section 3.6: "Grading is the `ClientSafetyManager`'s act and it is
    permitted only while the prequalification is in `UNDER_REVIEW`; from anywhere
    else it is `ERR_TRANSITION_NOT_ALLOWED`."

    Design: Corner/state_machines/grade_from_draft_status_returns_transition_not_allowed
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor()
    prequalification = build.open_prequalification(contractor["id"], client["id"])

    response = api.grade_prequalification(
        prequalification["id"], {}, build.manager_headers(client["id"])
    )
    validate_error(response, ERR_TRANSITION_NOT_ALLOWED, 409)

    row = build.read_prequalification(prequalification["id"])
    assert_prequalification_state(
        row, status="DRAFT", grade=None, final_composite_score=None
    )
    assert row["graded_at"] is None
    assert_contractor_posture(
        build.read_contractor(contractor["id"]), open_deficiency_count=0
    )


def test_new_certificate_starts_pending_with_materialized_current_lifecycle(build, api):
    """One request seeds the verification dimension and materializes the other.

    PRD Section 3.5: "Filing a certificate sets `verification_status` to
    `PENDING`, materializes `lifecycle_status` against the clock, materializes
    `available_aggregate` under the depleted-aggregate basis, and then sweeps the
    contractor's history for that coverage type: every previously **refused**
    certificate whose interval intersects the new one has its `lifecycle_status`
    written to `SUPERSEDED`."

    Design: Corner/state_machines/new_certificate_starts_pending_with_materialized_current_lifecycle
    """
    build.set_clock(INITIAL_CLOCK)
    contractor = build.create_contractor()

    live = build.file_certificate(
        contractor["id"],
        "GL",
        effective_date="2026-07-01T00:00:00Z",
        expiration_date="2027-07-01T00:00:00Z",
    )
    future = build.file_certificate(
        contractor["id"],
        "AUTO",
        effective_date="2026-10-01T00:00:00Z",
        expiration_date="2027-10-01T00:00:00Z",
    )

    for row in (live, future):
        assert row["verification_status"] == "PENDING"
        assert row["verified_by_user_id"] is None
        assert row["version"] == 1
        assert row["additional_insured"] is False
        assert row["waiver_of_subrogation"] is False

    assert_certificate_state(
        live, lifecycle_status="CURRENT", available_aggregate=2000000
    )
    assert_certificate_state(future, lifecycle_status="NOT_YET_EFFECTIVE")

    assert_contractor_posture(
        build.read_contractor(contractor["id"]), verified_coverage_types=[]
    )


def test_rejected_safety_statistic_cannot_be_verified_again(build, api):
    """REJECTED is terminal, and the refusal released the reporting year.

    PRD Section 3.3: "`REJECT` carries the row to `REJECTED` and recomputes the
    parent's dimension by the same derivation rule, which releases the
    `reporting_year` for a replacement filing while the prequalification is still
    in `DRAFT`."

    Design: Corner/state_machines/rejected_safety_statistic_cannot_be_verified_again
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor()
    prequalification = build.open_prequalification(contractor["id"], client["id"])
    filed = build.file_statistic(prequalification["id"], contractor["id"])
    refused = build.decide_statistic(filed["id"], "REJECT", ANALYST_STATISTICS)
    assert refused["verification_status"] == "REJECTED"

    response = api.verify_statistic(
        filed["id"],
        statistic_decision_payload("VERIFY"),
        make_analyst_headers(ANALYST_STATISTICS),
    )
    validate_error(response, ERR_TRANSITION_NOT_ALLOWED, 409)

    replacement = validate_success(
        api.create_statistic(
            prequalification["id"],
            statistic_payload(hours_worked=520000, source_document_ref="OSHA300A-2025-REV"),
            build.contractor_headers(contractor["id"]),
        ),
        201,
    )
    assert replacement["verification_status"] == "PENDING"
    assert replacement["reporting_year"] == 2025

    rows, meta = validate_paginated(
        api.list_statistics(prequalification["id"], build.admin_headers)
    )
    assert meta["total_count"] == 2, (
        f"expected the refused row and its replacement, got {meta['total_count']}"
    )
    statuses = sorted(row["verification_status"] for row in rows)
    assert statuses == ["PENDING", "REJECTED"], f"got {statuses}"
    original = [row for row in rows if row["id"] == filed["id"]][0]
    assert original["verified_by_user_id"] == ANALYST_STATISTICS


def test_verifying_an_already_verified_certificate_returns_transition_not_allowed(
    build, api
):
    """VERIFY is not idempotent; the second call is refused, not re-applied.

    PRD Section 3.5: "Then the row must still be `PENDING`, otherwise
    `ERR_TRANSITION_NOT_ALLOWED`."

    Design: Corner/state_machines/verifying_an_already_verified_certificate_returns_transition_not_allowed
    """
    build.set_clock(INITIAL_CLOCK)
    contractor = build.create_contractor()
    verified = build.verified_certificate(contractor["id"], "GL")
    assert_certificate_state(
        verified, verification_status="VERIFIED", lifecycle_status="CURRENT"
    )
    assert verified["verified_by_user_id"] == ANALYST_INSURANCE
    first_version = verified["version"]

    # A different analyst, so no segregation-of-duties conflict is in play.
    response = api.verify_certificate(
        verified["id"],
        certificate_decision_payload("VERIFY"),
        make_analyst_headers("analyst-ins-2"),
    )
    validate_error(response, ERR_TRANSITION_NOT_ALLOWED, 409)

    rows, meta = validate_paginated(
        api.list_certificates(
            contractor["id"], build.admin_headers, {"coverage_type": "GL"}
        )
    )
    assert meta["total_count"] == 1
    intact = rows[0]
    assert_certificate_state(intact, verification_status="VERIFIED")
    assert intact["verified_by_user_id"] == ANALYST_INSURANCE, (
        "the refused call must not have overwritten the deciding analyst"
    )
    assert intact["version"] == first_version, (
        f"expected version {first_version} to be untouched, got {intact['version']}"
    )
    assert_contractor_posture(
        build.read_contractor(contractor["id"]), verified_coverage_types=["GL"]
    )


def test_superseding_prequalification_for_a_new_cycle_year_expires_the_prior_approved_row(
    build, api
):
    """Opening 2027 retires the approved 2026 row and its badge, at an unmoved clock.

    PRD Section 3.2: "Every prequalification for the same contractor and client
    whose `cycle_year` is strictly lower than the new one and whose `status` is
    `APPROVED`, `CONDITIONAL` or `SUSPENDED` is carried to `EXPIRED`, processed in
    ascending `cycle_year` order and, within a year, ascending `created_at` order."

    Design: Corner/state_machines/superseding_prequalification_for_a_new_cycle_year_expires_the_prior_approved_row
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing()
    assert_prequalification_state(
        scenario["prequalification"], status="APPROVED", grade="B"
    )
    grant = build.grant_badge(
        scenario["worker_id"],
        scenario["site_id"],
        scenario["prequalification_id"],
        scenario["contractor_id"],
    )
    assert_grant_state(grant, status="GRANTED")

    successor = build.open_prequalification(
        scenario["contractor_id"], scenario["client_id"], cycle_year=2027
    )
    assert successor["cycle_year"] == 2027
    assert_prequalification_state(successor, status="DRAFT")

    retired = build.read_prequalification(scenario["prequalification_id"])
    assert_prequalification_state(retired, status="EXPIRED", grade="B")

    cascaded = validate_success(
        api.get_grant(grant["id"], scenario["manager_headers"])
    )
    assert_grant_state(
        cascaded, status="REVOKED", revocation_reason="PREQUAL_EXPIRED"
    )
    assert_instant_equals(cascaded["revoked_at"], INITIAL_CLOCK)

    site = validate_success(api.get_site(scenario["site_id"], scenario["manager_headers"]))
    assert_site_posture(site, granted_worker_count=0, access_gate_status="OPEN")

    _rows, meta = validate_paginated(
        api.list_prequalifications(
            build.admin_headers,
            {"contractor_id": scenario["contractor_id"], "status": "APPROVED"},
        )
    )
    assert meta["total_count"] == 0, (
        f"expected no APPROVED row to survive the supersede, got {meta['total_count']}"
    )


def test_improvement_plan_creation_supersedes_the_prior_open_plan(build, api):
    """The second plan carries the first to REJECTED so exactly one plan governs.

    PRD Section 3.7: "Any plan already on the row whose `status` is `OPEN` or
    `SUBMITTED` is superseded — carried to `REJECTED` with `closed_at` set to the
    logical clock — so that exactly one live plan governs the row."

    Design: Corner/state_machines/improvement_plan_creation_supersedes_the_prior_open_plan
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing(statistic_overrides={"emr": 1.01})
    pq_id = scenario["prequalification_id"]
    graded = scenario["prequalification"]
    assert_prequalification_state(
        graded, status="CONDITIONAL", grade="B", deficiency_codes=["EMR"]
    )

    first = validate_success(
        api.create_improvement_plan(
            pq_id,
            improvement_plan_payload(
                expected_prequalification_version=graded["version"],
                due_date="2026-10-01T00:00:00Z",
                milestone_count=3,
            ),
            scenario["manager_headers"],
        ),
        201,
    )
    assert first["status"] == "OPEN"
    assert first["closed_at"] is None

    after_first = build.read_prequalification(pq_id)
    second = validate_success(
        api.create_improvement_plan(
            pq_id,
            improvement_plan_payload(
                expected_prequalification_version=after_first["version"],
                due_date="2026-10-15T00:00:00Z",
                milestone_count=4,
            ),
            scenario["manager_headers"],
        ),
        201,
    )
    assert second["status"] == "OPEN"
    assert second["deficiency_codes"] == ["EMR"]
    assert second["closed_at"] is None

    rows, meta = validate_paginated(
        api.list_improvement_plans(pq_id, scenario["manager_headers"])
    )
    assert meta["total_count"] == 2, (
        f"expected the superseded plan to survive as a row, got {meta['total_count']}"
    )
    superseded = [row for row in rows if row["id"] == first["id"]][0]
    assert superseded["status"] == "REJECTED", (
        f"expected the first plan at REJECTED, got {superseded['status']}"
    )
    assert_instant_equals(superseded["closed_at"], INITIAL_CLOCK)
    assert superseded["decided_by_user_id"] is None, (
        "a system supersede records no deciding user"
    )

    # The row itself never left CONDITIONAL and the counter never moved.
    row = build.read_prequalification(pq_id)
    assert_prequalification_state(
        row, status="CONDITIONAL", grade="B", deficiency_codes=["EMR"]
    )
    assert_contractor_posture(
        build.read_contractor(scenario["contractor_id"]), open_deficiency_count=1
    )


def test_requalification_run_expires_the_row_and_leaves_already_revoked_grants_untouched(
    build, api
):
    """The run expires the annual row but never rewrites a hand-revoked badge.

    PRD Section 3.11: "This run is the only writer that materializes clock-driven
    expiry, and it is idempotent by construction — executed a second time at the
    same logical clock, it reports zeros across all six counters."

    Design: Corner/state_machines/requalification_run_expires_the_row_and_leaves_already_revoked_grants_untouched
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing(
        certificate_overrides={"expiration_date": "2028-07-01T00:00:00Z"}
    )
    manager = scenario["manager_headers"]
    grant = build.grant_badge(
        scenario["worker_id"],
        scenario["site_id"],
        scenario["prequalification_id"],
        scenario["contractor_id"],
        expires_at="2027-06-30T00:00:00Z",
    )
    revoked = build.revoke_badge(grant["id"], scenario["client_id"])
    assert_grant_state(revoked, status="REVOKED", revocation_reason="CLIENT_REVOKED")
    assert_instant_equals(revoked["revoked_at"], INITIAL_CLOCK)

    approved = build.read_prequalification(scenario["prequalification_id"])
    assert_instant_equals(approved["expires_at"], "2027-08-01T00:00:00Z")

    build.set_clock("2027-08-01T00:00:00Z")
    # Setting the clock sweeps nothing: the row is still APPROVED.
    assert_prequalification_state(
        build.read_prequalification(scenario["prequalification_id"]), status="APPROVED"
    )

    result = validate_success(api.run_requalification(scenario["client_id"], {}, manager))
    assert result["expired_count"] == 1, (
        f"expected exactly one annual expiry, got {result['expired_count']}"
    )
    assert result["expired_prequalification_ids"] == [scenario["prequalification_id"]]
    assert result["conditional_rejected_count"] == 0
    assert result["conditional_rejected_prequalification_ids"] == []
    assert result["overdue_plan_count"] == 0
    assert result["lapsed_certificate_count"] == 0

    assert_prequalification_state(
        build.read_prequalification(scenario["prequalification_id"]), status="EXPIRED"
    )

    untouched = validate_success(api.get_grant(grant["id"], manager))
    assert_grant_state(
        untouched, status="REVOKED", revocation_reason="CLIENT_REVOKED"
    )
    assert_instant_equals(untouched["revoked_at"], INITIAL_CLOCK)

    site = validate_success(api.get_site(scenario["site_id"], manager))
    assert_site_posture(site, granted_worker_count=0)

    second = validate_success(api.run_requalification(scenario["client_id"], {}, manager))
    for counter in (
        "expired_count",
        "conditional_rejected_count",
        "overdue_plan_count",
        "lapsed_certificate_count",
    ):
        assert second[counter] == 0, (
            f"the second run must report 0 for {counter}, got {second[counter]}"
        )
    assert second["expired_prequalification_ids"] == []
    assert second["conditional_rejected_prequalification_ids"] == []
