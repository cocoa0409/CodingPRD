"""Authorisation, tenancy and segregation, each at the rung PRD 2.10 assigns it.

Exclusive operations refuse peers without half-applying their side effects;
shared operations must accept every role the catalogue lists and no other; a
`ClientRepresentative` is scoped through the owning project rather than the
path; segregation bites within a single role; and the two header rungs run
before any payload is examined.
"""
from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    ApiErrorId,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    MICROBIOLOGY_ANALYST,
    PRODUCTION_SUPERVISOR,
    PROGRAM_MANAGER,
    QA_REVIEWER,
    QA_SECOND_USER_ID,
    QA_REVIEWER_SECOND,
    QA_USER_ID,
    QUALIFIED_PERSON,
    headers_without_auth,
    make_client_representative_headers,
    role_headers,
)

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Design instance: microbiology_analyst_cannot_schedule_a_batch_order
# ---------------------------------------------------------------------------
def test_the_denied_scheduling_call_reserves_no_suite_time_at_all(api):
    """The same body is 403 for microbiology and 201 for the program manager.

    PRD 2.1: "Only once the role has resolved does the server test it against the target endpoint's authorised role list; a role that is not on that list yields `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD 4: "| `POST` | `/batch-orders` | Schedule a batch into a shared suite, stamping its component demand and changeover buffer, guarded by optimistic concurrency on the suite version. | `ProgramManager` |"

    Design: Corner/rbac/microbiology_analyst_cannot_schedule_a_batch_order
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_PROJECT)
    suite_version_before = fixtures.suite_version(api, program["suite_id"])
    payload = factories.batch_order_payload(
        program["project_id"],
        program["suite_id"],
        program["qualification_ids"][0],
        suite_version_before,
    )

    validate_error(
        api.create_batch_order(payload, MICROBIOLOGY_ANALYST),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    denied_suite = fixtures.read_suite(api, program["suite_id"])
    assert denied_suite["committed_minutes"] == 0
    assert denied_suite["version"] == suite_version_before

    batch = validate_success(api.create_batch_order(payload, PROGRAM_MANAGER), 201)
    assert batch["production_status"] == "SCHEDULED"
    assert fixtures.read_suite(api, program["suite_id"])["committed_minutes"] == 540


# ---------------------------------------------------------------------------
# Design instance: production_and_quality_roles_cannot_cross_into_each_others_exclusive_acts
# ---------------------------------------------------------------------------
def test_authority_flows_neither_up_nor_down_the_release_chain(api):
    """QP cannot close the record, QA cannot sign it, production can do neither.

    PRD 2.1: "A `QaReviewer` explicitly cannot certify a batch."

    PRD 4: "| `POST` | `/batch-record-reviews/{id}/close` | Close the review once no findings remain, advancing the batch's quality axis BR_REVIEW to QP_REVIEW and stamping the chronological final releasable-unit figure. | `QaReviewer` |"

    PRD 4: "| `POST` | `/batch-orders/{id}/qp-release` | Qualified-Person disposition of a batch in QP_REVIEW. RELEASE additionally stamps release_fee_cents from the pinned five-step tiered fee formula. | `QualifiedPerson` |"

    Design: Corner/rbac/production_and_quality_roles_cannot_cross_into_each_others_exclusive_acts
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_BR_REVIEW)
    review_id = program["review_id"]

    refusals = [
        validate_error(
            api.close_batch_record_review(review_id, QUALIFIED_PERSON),
            ApiErrorId.ROLE_NOT_PERMITTED,
            403,
        ),
        validate_error(
            api.qp_release(
                program["batch_id"],
                factories.qp_release_payload(
                    decision="RELEASE", rationale="QA attempting the QP signature."
                ),
                QA_REVIEWER,
            ),
            ApiErrorId.ROLE_NOT_PERMITTED,
            403,
        ),
        validate_error(
            api.close_batch_record_review(review_id, PRODUCTION_SUPERVISOR),
            ApiErrorId.ROLE_NOT_PERMITTED,
            403,
        ),
    ]
    for refusal in refusals:
        assert refusal["error_id"] == ApiErrorId.ROLE_NOT_PERMITTED
        assert refusal["error_id"] != ApiErrorId.BR_REVIEW_STATE_INVALID
        assert refusal["error_id"] != ApiErrorId.BATCH_QUALITY_STATE_INVALID
        assert refusal["error_id"] != ApiErrorId.SEGREGATION_OF_DUTIES

    assert fixtures.read_review(api, review_id)["status"] == "IN_PROGRESS"
    assert fixtures.read_batch(api, program["batch_id"])["quality_status"] == "BR_REVIEW"
    decisions, meta = validate_paginated(
        api.list_qp_release_decisions(program["batch_id"], QUALIFIED_PERSON)
    )
    assert decisions == []
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Design instance: client_representative_cannot_read_another_projects_batch_order
# ---------------------------------------------------------------------------
def test_a_sponsor_is_scoped_through_the_owning_project_not_the_path(api):
    """Sponsor B is refused three ways and never learns whether the rows exist.

    PRD 2.1: "When `X-User-Role` is `ClientRepresentative`, `X-User-ID` is the `id` of the acting `ClientProject`; ownership checks compare the owning project of the addressed resource to `X-User-ID`."

    PRD 2.1: "For `GET /batch-orders/{id}` and `GET /batch-orders/{id}/unit-accounting` it is against the addressed batch's `client_project_id`. A mismatch on any of those six operations is rejected with `ERR_PROJECT_ACCESS_DENIED` (HTTP 403)."

    Design: Corner/rbac/client_representative_cannot_read_another_projects_batch_order
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_SCHEDULED)
    sponsor_b_project = fixtures.create_project(
        api,
        program["suite_id"],
        client_name="Sponsor B",
        molecule_name="MOL-B",
        dosage_form="PRESYRINGE",
        target_fill_weight_mg=500,
        historical_reject_rate_ppm=1000,
        reserved_unit_budget=20000,
    )
    intruder = make_client_representative_headers(sponsor_b_project["id"])
    owner = make_client_representative_headers(program["project_id"])

    batch_refusal = validate_error(
        api.get_batch_order(program["batch_id"], intruder),
        ApiErrorId.PROJECT_ACCESS_DENIED,
        403,
    )
    assert batch_refusal["error_id"] != ApiErrorId.BATCH_ORDER_NOT_FOUND
    validate_error(
        api.get_unit_accounting(program["batch_id"], intruder),
        ApiErrorId.PROJECT_ACCESS_DENIED,
        403,
    )
    project_refusal = validate_error(
        api.get_client_project(program["project_id"], intruder),
        ApiErrorId.PROJECT_ACCESS_DENIED,
        403,
    )
    assert project_refusal["error_id"] != ApiErrorId.CLIENT_PROJECT_NOT_FOUND

    own_batch = validate_success(api.get_batch_order(program["batch_id"], owner), 200)
    assert own_batch["id"] == program["batch_id"]
    assert own_batch["client_project_id"] == program["project_id"]


# ---------------------------------------------------------------------------
# Design instance: qa_reviewer_cannot_decide_the_capa_on_a_deviation_they_opened
# ---------------------------------------------------------------------------
def test_one_qa_reviewer_opens_the_deviation_and_another_must_decide_it(api):
    """qa-001 is refused its own CAPA; the identical call from qa-002 closes it.

    PRD 2.8: "The `X-User-ID` deciding a CAPA must differ from the `opened_by_user_id` recorded on that deviation."

    PRD 2.8: "Note that the second rule bites even though both actions are performed by the same role: two distinct `QaReviewer` users are required to open a deviation and to decide its CAPA."

    Design: Corner/rbac/qa_reviewer_cannot_decide_the_capa_on_a_deviation_they_opened
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_SCHEDULED)
    deviation = fixtures.raise_deviation(
        api,
        program["batch_id"],
        QA_REVIEWER,
        summary="Line clearance signature missing on the setup checklist.",
    )
    assert deviation["opened_by_user_id"] == QA_USER_ID
    fixtures.classify_deviation(
        api,
        deviation["id"],
        QA_REVIEWER,
        classification="MINOR",
        classification_rationale="Documentation only, no product impact.",
    )
    fixtures.submit_capa(
        api,
        deviation["id"],
        QA_REVIEWER,
        capa_summary="Retrain the shift and add a checklist verification step.",
    )

    validate_error(
        api.decide_capa(
            deviation["id"],
            factories.decide_capa_payload(
                outcome="APPROVED", decision_note="Self-approval attempt."
            ),
            QA_REVIEWER,
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )
    held = fixtures.read_deviation(api, deviation["id"])
    assert held["status"] == "CAPA_PENDING"
    assert held["capa_rejection_count"] == 0

    decided = fixtures.decide_capa(
        api,
        deviation["id"],
        QA_REVIEWER_SECOND,
        outcome="APPROVED",
        decision_note="Independent QA approval.",
    )
    assert decided["status"] == "CLOSED"
    assert decided["opened_by_user_id"] == QA_USER_ID
    assert QA_SECOND_USER_ID != QA_USER_ID


# ---------------------------------------------------------------------------
# Design instance: in_process_check_recording_is_shared_but_microbiology_is_rejected
# ---------------------------------------------------------------------------
def test_recording_a_control_is_shared_by_two_roles_and_closed_to_the_third(api):
    """Production and QA both record; microbiology is refused the same endpoint.

    PRD 4: "| `POST` | `/in-process-checks` | Record an in-process control (fill weight, container closure integrity or visual inspection) against a batch; result is derived by in_process_check_result. | `ProductionSupervisor`, `QaReviewer` |"

    Design: Corner/rbac/in_process_check_recording_is_shared_but_microbiology_is_rejected
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_FILLING)
    batch_id = program["batch_id"]

    by_production = validate_success(
        api.create_in_process_check(
            factories.fill_weight_check_payload(
                batch_id, measured_fill_weights_mg=[1000, 1020]
            ),
            PRODUCTION_SUPERVISOR,
        ),
        201,
    )
    assert by_production["result"] == "PASS"

    by_quality = validate_success(
        api.create_in_process_check(factories.cci_check_payload(batch_id), QA_REVIEWER),
        201,
    )
    assert by_quality["result"] == "PASS"

    validate_error(
        api.create_in_process_check(
            factories.visual_check_payload(
                batch_id, sample_size=8500, reject_unit_count=100
            ),
            MICROBIOLOGY_ANALYST,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
        403,
    )

    rows, meta = validate_paginated(
        api.list_in_process_checks(PROGRAM_MANAGER, {"batch_order_id": batch_id})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 2
    assert {row["check_type"] for row in rows} == {"FILL_WEIGHT", "CCI"}


# ---------------------------------------------------------------------------
# Design instance: missing_auth_headers_and_unknown_role_are_rejected_before_anything_else
# ---------------------------------------------------------------------------
def test_the_two_header_rungs_run_before_the_payload_is_ever_examined(api):
    """A malformed body still answers 401, and an invented role is never a 403.

    PRD 2.1: "If either header is absent or present but empty, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401). If `X-User-Role` carries a value that is not one of the six roles below, the request is rejected with `ERR_UNKNOWN_ROLE` (HTTP 401)."

    PRD 2.1: "The six roles are exactly `ProgramManager`, `ProductionSupervisor`, `MicrobiologyAnalyst`, `QaReviewer`, `QualifiedPerson` and `ClientRepresentative`."

    Design: Corner/rbac/missing_auth_headers_and_unknown_role_are_rejected_before_anything_else
    """
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)

    unauthenticated = validate_error(
        api.create_filling_suite({"grade": "B"}, headers_without_auth()),
        ApiErrorId.MISSING_AUTH_HEADERS,
        401,
    )
    assert unauthenticated["error_id"] != ApiErrorId.INVALID_REQUEST

    invented_role = validate_error(
        api.create_filling_suite(
            factories.filling_suite_payload(),
            role_headers("SterilityAssuranceDirector"),
        ),
        ApiErrorId.UNKNOWN_ROLE,
        401,
    )
    assert invented_role["error_id"] != ApiErrorId.ROLE_NOT_PERMITTED

    validate_error(
        api.list_filling_suites(headers_without_auth()),
        ApiErrorId.MISSING_AUTH_HEADERS,
        401,
    )

    rows, meta = validate_paginated(api.list_filling_suites(PROGRAM_MANAGER))
    assert rows == []
    assert meta["total_count"] == 0
