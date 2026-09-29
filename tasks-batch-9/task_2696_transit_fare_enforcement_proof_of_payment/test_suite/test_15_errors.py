"""
Error reachability: the authentication gate that never degrades into a role
refusal, the per-resource not-found codes, and the lifecycle, gate, policy,
settlement and appellate codes reached through the operations that raise them.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_APPEAL_NOT_FOUND,
    ERR_APPEAL_ROUND_LIMIT,
    ERR_APPEAL_STATUS_INVALID,
    ERR_APPEAL_WINDOW_CLOSED,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_CITATION_STATUS_INVALID,
    ERR_CONTEST_WINDOW_CLOSED,
    ERR_DEPLOYMENT_NOT_ACTIVE,
    ERR_DEPLOYMENT_NOT_FOUND,
    ERR_DISPOSITION_NOT_SUPPORTED,
    ERR_DOWN_PAYMENT_EXCEEDS_BALANCE,
    ERR_ENCOUNTER_NOT_FOUND,
    ERR_ENCOUNTER_OUTSIDE_WINDOW,
    ERR_FORBIDDEN_ROLE,
    ERR_HEARING_CITATION_MISMATCH,
    ERR_HEARING_NOT_APPEALABLE,
    ERR_HEARING_NOT_FOUND,
    ERR_HEARING_NOT_SCHEDULED,
    ERR_INSPECTOR_NOT_FOUND,
    ERR_LINE_NOT_FOUND,
    ERR_OPEN_ENCOUNTERS_REMAIN,
    ERR_PLAN_NOT_FOUND,
    ERR_REISSUE_NOT_PERMITTED,
    ERR_REISSUE_WINDOW_CLOSED,
    ERR_RIDER_NOT_FOUND,
    ERR_SAMPLE_SIZE_INADEQUATE,
    ERR_SERVICE_ASSIGNMENT_NOT_FOUND,
    ERR_SERVICE_NOT_ACTIVE,
    ERR_SUPPLEMENT_WINDOW_CLOSED,
    ERR_UNAUTHENTICATED,
    ERR_WARNING_REQUIRED_FIRST_OFFENSE,
    ERR_ZONE_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_citation_money_identity,
    assert_instant_equals,
    assert_ledger_row,
    assert_rate_equals,
    ids_of,
    rows_with_source,
    sole_row_with_source,
)
from test_helpers.constants import (
    ADJUDICATION_DISMISSED,
    ADJUDICATION_ISSUED,
    ADJUDICATION_UPHELD,
    APPEAL_STATUS_SUBMITTED,
    APPEAL_STATUS_SUPPLEMENT_REQUESTED,
    APPEAL_STATUS_WITHDRAWN,
    DECISION_DISMISS,
    DECISION_UPHOLD,
    DEPLOYMENT_STATUS_ACTIVE,
    DISMISSAL_REASON_VALID_FARE_PRESENTED,
    ENFORCEMENT_POLICY_WARNING_FIRST,
    GROUNDS_PROCEDURAL_DEFECT,
    HEARING_STATUS_HELD,
    OUTCOME_PENDING,
    OUTCOME_WARNING_ISSUED,
    PAYMENT_SOURCE_SERVICE_CREDIT,
    SERVICE_STATUS_ACTIVE,
    SERVICE_STATUS_COMPLETED,
    SETTLEMENT_OUTSTANDING,
    SETTLEMENT_SATISFIED,
    SETTLEMENT_SERVICE_ACTIVE,
    SETTLEMENT_WRITTEN_OFF,
    VALIDATION_NO_PROOF,
)
from test_helpers.fixtures import ENCOUNTER_AT, OBSERVATION_AT, WINDOW_END, WINDOW_START
from test_helpers.test_users import (
    BOARD_MEMBER_HEADERS,
    HEARING_OFFICER_HEADERS,
    PLANNER_HEADERS,
    headers_with_empty_user_id,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
    make_fare_inspector_headers,
    make_rider_headers,
)

# Eleven ids that resolve to nothing at all.
UNKNOWN_IDS = tuple(
    f"00000000-0000-4000-8000-0000000000{index:02d}" for index in range(1, 12)
)

SUPPLEMENT_DEADLINE_AT = "2026-08-19T09:00:00Z"
AFTER_SUPPLEMENT_DEADLINE = "2026-08-20T09:00:00Z"
AFTER_APPEAL_WINDOW = "2026-08-27T09:00:00Z"

BEFORE_WINDOW_START = "2026-08-05T05:59:59Z"
AFTER_CLOCK_AT = "2026-08-05T10:00:00Z"
SECOND_ENCOUNTER_AT = "2026-08-05T07:30:00Z"
THIRD_ENCOUNTER_AT = "2026-08-05T08:00:00Z"
FOURTH_ENCOUNTER_AT = "2026-08-05T08:30:00Z"

CONTEST_DEADLINE_AT = "2026-09-04T09:00:00Z"
AFTER_CONTEST_DEADLINE = "2026-09-04T09:00:01Z"
HEARING_FROM_DEADLINE = "2026-09-18T09:00:00Z"

COMPLIANT = "COMPLIANT"
WARNING_ISSUED = "WARNING_ISSUED"
UNRESOLVED_IDENTITY = "UNRESOLVED_IDENTITY"
PARTNER_ORG = "Riverside Community Partners"


def test_an_unusable_header_set_is_always_unauthenticated_never_forbidden(api):
    """
    Every request to every endpoint must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the role that
    principal is acting in.  If either header is absent or empty, or if
    `X-User-Role` does not name one of the six declared roles, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

    Design: Corner/errors/missing_or_unknown_auth_headers_return_unauthenticated
    """
    for headers in (
        headers_without_role(),
        headers_without_user_id(),
        headers_with_empty_user_id(),
        headers_with_unknown_role(),
    ):
        response = api.list_fare_zones(headers)
        validate_error(response, ERR_UNAUTHENTICATED, 401)
        assert response.json()["data"]["error_id"] != ERR_FORBIDDEN_ROLE

    # The same surface answers a well-formed header set normally.
    rows, meta = validate_paginated(api.list_fare_zones(PLANNER_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []


def test_each_resource_kind_answers_an_unknown_path_id_with_its_own_code(api):
    """
    Each resource kind has its own not-found code, all at HTTP 404:
    `ERR_ZONE_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_INSPECTOR_NOT_FOUND`, `ERR_RIDER_NOT_FOUND`,
    `ERR_DEPLOYMENT_NOT_FOUND`, `ERR_ENCOUNTER_NOT_FOUND`,
    `ERR_CITATION_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`,
    `ERR_PLAN_NOT_FOUND` and `ERR_SERVICE_ASSIGNMENT_NOT_FOUND`.

    Design: Corner/errors/every_path_id_has_its_own_entity_specific_not_found_code
    """
    reads = (
        (api.get_fare_zone, PLANNER_HEADERS, ERR_ZONE_NOT_FOUND),
        (api.get_transit_line, PLANNER_HEADERS, ERR_LINE_NOT_FOUND),
        (api.get_zone_line_assignment, PLANNER_HEADERS, ERR_ASSIGNMENT_NOT_FOUND),
        (api.get_inspector, PLANNER_HEADERS, ERR_INSPECTOR_NOT_FOUND),
        (api.get_rider, PLANNER_HEADERS, ERR_RIDER_NOT_FOUND),
        (api.get_deployment, PLANNER_HEADERS, ERR_DEPLOYMENT_NOT_FOUND),
        (api.get_encounter, PLANNER_HEADERS, ERR_ENCOUNTER_NOT_FOUND),
        (api.get_hearing, HEARING_OFFICER_HEADERS, ERR_HEARING_NOT_FOUND),
        (api.get_appeal, BOARD_MEMBER_HEADERS, ERR_APPEAL_NOT_FOUND),
        (api.get_payment_plan, PLANNER_HEADERS, ERR_PLAN_NOT_FOUND),
        (api.get_service_assignment, PLANNER_HEADERS, ERR_SERVICE_ASSIGNMENT_NOT_FOUND),
    )
    assert len(reads) == len(UNKNOWN_IDS)

    for unknown_id, (read, headers, expected_error) in zip(UNKNOWN_IDS, reads):
        validate_error(read(unknown_id, headers), expected_error, 404)


def test_the_adjudication_and_appeal_lifecycle_codes_are_each_reached_in_turn(api):
    """
    Contesting requires the citation's `adjudication_status` to be exactly
    `ISSUED` — a citation already `CONTESTED`, `UPHELD`, `REDUCED`, `DISMISSED`
    or `VOID` is refused with `ERR_CITATION_STATUS_INVALID`. ... Cancellation
    requires the hearing's `status` to be `SCHEDULED` — anything else is refused
    with `ERR_HEARING_NOT_SCHEDULED`. ... A supplement request against an appeal
    whose `status` is not `SUBMITTED`, and a resubmission against an appeal whose
    `status` is not `SUPPLEMENT_REQUESTED`, are both refused with
    `ERR_APPEAL_STATUS_INVALID`. ... must arrive at or before
    `supplement_deadline_at`, a later resubmission being refused with
    `ERR_SUPPLEMENT_WINDOW_CLOSED`. ... the logical clock must be at or before
    the hearing's `decided_at` plus 21 days, and a later filing is refused with
    `ERR_APPEAL_WINDOW_CLOSED`.

    Design: Corner/errors/appeal_and_hearing_lifecycle_codes_are_each_reachable
    """
    chain = fixtures.build_upheld_citation_chain(api)
    citation_id = chain["citation"]["id"]
    rider_id = chain["rider"]["id"]
    hearing_id = chain["hearing"]["id"]
    rider_headers = make_rider_headers(rider_id)

    validate_error(
        api.contest_citation(citation_id, rider_headers), ERR_CITATION_STATUS_INVALID, 409
    )

    validate_error(
        api.decide_hearing(
            hearing_id, factories.hearing_decision_payload(DECISION_UPHOLD), HEARING_OFFICER_HEADERS
        ),
        ERR_HEARING_NOT_SCHEDULED,
        409,
    )
    validate_error(
        api.cancel_hearing(hearing_id, HEARING_OFFICER_HEADERS), ERR_HEARING_NOT_SCHEDULED, 409
    )

    held = fixtures.read_hearing(api, hearing_id)
    assert held["status"] == HEARING_STATUS_HELD
    assert held["decision"] == DECISION_UPHOLD
    assert_instant_equals(held["decided_at"], OBSERVATION_AT, "hearing.decided_at")

    appeal = fixtures.file_appeal(
        api, citation_id, hearing_id, rider_id, GROUNDS_PROCEDURAL_DEFECT
    )
    assert appeal["status"] == APPEAL_STATUS_SUBMITTED
    assert appeal["round_index"] == 1

    validate_error(
        api.resubmit_appeal(
            appeal["id"], factories.appeal_resubmit_payload(), rider_headers
        ),
        ERR_APPEAL_STATUS_INVALID,
        409,
    )

    awaiting = fixtures.request_supplement(api, appeal["id"])
    assert awaiting["status"] == APPEAL_STATUS_SUPPLEMENT_REQUESTED
    assert_instant_equals(
        awaiting["supplement_deadline_at"],
        SUPPLEMENT_DEADLINE_AT,
        "appeal.supplement_deadline_at",
    )

    fixtures.move_clock(api, AFTER_SUPPLEMENT_DEADLINE)
    validate_error(
        api.resubmit_appeal(
            appeal["id"], factories.appeal_resubmit_payload(), rider_headers
        ),
        ERR_SUPPLEMENT_WINDOW_CLOSED,
        422,
    )
    assert fixtures.read_appeal(api, appeal["id"])["round_index"] == 1

    withdrawn = get_success_data(api.withdraw_appeal(appeal["id"], rider_headers))
    assert withdrawn["status"] == APPEAL_STATUS_WITHDRAWN

    fixtures.move_clock(api, AFTER_APPEAL_WINDOW)
    validate_error(
        api.create_appeal(
            factories.appeal_payload(citation_id, hearing_id, GROUNDS_PROCEDURAL_DEFECT),
            rider_headers,
        ),
        ERR_APPEAL_WINDOW_CLOSED,
        422,
    )

    rows, meta = validate_paginated(
        api.list_appeals(BOARD_MEMBER_HEADERS, {"citation_id": citation_id})
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [appeal["id"]]
    assert rows[0]["status"] == APPEAL_STATUS_WITHDRAWN


def test_the_deployment_and_encounter_gate_codes_are_each_reached_in_turn(api):
    """
    The named deployment must be in `status` `ACTIVE`, failing which the request
    is refused with `ERR_DEPLOYMENT_NOT_ACTIVE`. ... And `occurred_at` must fall
    at or after the deployment's `window_start`, strictly before its
    `window_end`, and at or before the current logical clock ... a violation is
    refused with `ERR_ENCOUNTER_OUTSIDE_WINDOW`. ... No encounter under the
    deployment may still be in `PENDING`; if one is, the request is refused with
    `ERR_OPEN_ENCOUNTERS_REMAIN`. ... a ratio of exactly 0.8000 closes the
    deployment, while 0.7999 is refused with `ERR_SAMPLE_SIZE_INADEQUATE`.

    Design: Corner/errors/deployment_and_encounter_gate_codes_are_each_reachable
    """
    env = fixtures.build_environment(api)
    inspector_id = env["inspector"]["id"]
    rider_id = env["rider"]["id"]
    inspector_headers = make_fare_inspector_headers(inspector_id)
    deployment = fixtures.plan_deployment(api, env["line"]["id"], env["zone"]["id"])

    def record(occurred_at):
        return api.create_inspection_encounter(
            factories.encounter_payload(
                deployment_id=deployment["id"],
                inspector_id=inspector_id,
                rider_id=rider_id,
                occurred_at=occurred_at,
                fare_media_type="NONE",
                identity_capture_method="GOVT_ID",
            ),
            inspector_headers,
        )

    validate_error(record(ENCOUNTER_AT), ERR_DEPLOYMENT_NOT_ACTIVE, 409)

    fixtures.move_clock(api, WINDOW_START)
    get_success_data(api.activate_deployment(deployment["id"], PLANNER_HEADERS))
    fixtures.move_clock(api, OBSERVATION_AT)

    for occurred_at in (BEFORE_WINDOW_START, WINDOW_END, AFTER_CLOCK_AT):
        validate_error(record(occurred_at), ERR_ENCOUNTER_OUTSIDE_WINDOW, 422)

    encounter = validate_success(record(ENCOUNTER_AT), 201)
    assert encounter["validation_result"] == VALIDATION_NO_PROOF
    assert encounter["outcome"] == OUTCOME_PENDING

    for disposition in (COMPLIANT, UNRESOLVED_IDENTITY):
        validate_error(
            api.resolve_encounter(
                encounter["id"], factories.resolve_payload(disposition), inspector_headers
            ),
            ERR_DISPOSITION_NOT_SUPPORTED,
            409,
        )

    # The open-encounter clause is reached before sample adequacy is considered.
    response = api.close_deployment(deployment["id"], PLANNER_HEADERS)
    validate_error(response, ERR_OPEN_ENCOUNTERS_REMAIN, 409)
    assert response.json()["data"]["error_id"] != ERR_SAMPLE_SIZE_INADEQUATE

    resolved = fixtures.resolve(api, encounter["id"], inspector_id, WARNING_ISSUED)
    assert resolved["outcome"] == OUTCOME_WARNING_ISSUED
    assert fixtures.read_rider(api, rider_id)["prior_warning_count"] == 1

    measured = fixtures.read_deployment(api, deployment["id"])
    assert measured["achieved_sample_count"] == 1
    assert_rate_equals(
        measured["sample_adequacy_ratio"], 0.2000, "deployment.sample_adequacy_ratio"
    )

    validate_error(
        api.close_deployment(deployment["id"], PLANNER_HEADERS), ERR_SAMPLE_SIZE_INADEQUATE, 409
    )
    still_open = fixtures.read_deployment(api, deployment["id"])
    assert still_open["status"] == DEPLOYMENT_STATUS_ACTIVE
    assert still_open["measured_evasion_rate_bps"] is None


def test_a_warning_first_zone_cites_only_on_the_second_contact_and_the_deadline_is_inclusive(api):
    """
    Inside such a zone a rider's first contact must be a warning, not a citation:
    the warning-inclusive ladder position computed for this rider must be at
    least 2.  A first-contact rider in a `WARNING_FIRST` zone is therefore
    refused with `ERR_WARNING_REQUIRED_FIRST_OFFENSE` ... requires the logical
    clock to be at or before the citation's `contest_deadline_at`, that instant
    itself still counting as inside the window; a later request is refused with
    `ERR_CONTEST_WINDOW_CLOSED`.

    Design: Corner/errors/warning_first_policy_and_the_contest_deadline_edge
    """
    env = fixtures.build_environment(
        api,
        zone_code="ZN2",
        enforcement_policy=ENFORCEMENT_POLICY_WARNING_FIRST,
        penalty_multiplier_bps=12000,
    )
    inspector_id = env["inspector"]["id"]
    first_rider = env["rider"]
    second_rider = fixtures.register_rider(
        api,
        rider_ref="R-200",
        display_name="Rider Two",
        demographic_band="BAND_B",
        residence_geo_tract="T-002",
    )
    deployment = fixtures.build_active_deployment(api, env)
    inspector_headers = make_fare_inspector_headers(inspector_id)

    citations = {}
    for rider, warning_at, citation_at in (
        (first_rider, ENCOUNTER_AT, SECOND_ENCOUNTER_AT),
        (second_rider, THIRD_ENCOUNTER_AT, FOURTH_ENCOUNTER_AT),
    ):
        first_contact = fixtures.build_pending_encounter(
            api, env, deployment, rider=rider, occurred_at=warning_at
        )
        validate_error(
            api.create_citation(
                factories.citation_payload(first_contact["id"]), inspector_headers
            ),
            ERR_WARNING_REQUIRED_FIRST_OFFENSE,
            409,
        )
        fixtures.resolve(api, first_contact["id"], inspector_id, WARNING_ISSUED)
        assert fixtures.read_rider(api, rider["id"])["prior_warning_count"] == 1

        second_contact = fixtures.build_pending_encounter(
            api, env, deployment, rider=rider, occurred_at=citation_at
        )
        citation = fixtures.issue_citation(api, second_contact["id"], inspector_id)
        assert citation["offense_sequence"] == 2
        assert citation["assessed_penalty_cents"] == 18000
        assert citation["admin_fee_cents"] == 2160
        assert citation["total_due_cents"] == 20160
        assert_citation_money_identity(citation)
        assert_instant_equals(
            citation["contest_deadline_at"], CONTEST_DEADLINE_AT, "citation.contest_deadline_at"
        )
        citations[rider["id"]] = citation

    # The deadline instant itself is still inside the window.
    fixtures.move_clock(api, CONTEST_DEADLINE_AT)
    first_citation = citations[first_rider["id"]]
    hearing = validate_success(
        api.contest_citation(first_citation["id"], make_rider_headers(first_rider["id"])), 201
    )
    assert_instant_equals(
        hearing["scheduled_for"], HEARING_FROM_DEADLINE, "hearing.scheduled_for"
    )

    # One second later the same request is out of time.
    fixtures.move_clock(api, AFTER_CONTEST_DEADLINE)
    second_citation = citations[second_rider["id"]]
    validate_error(
        api.contest_citation(second_citation["id"], make_rider_headers(second_rider["id"])),
        ERR_CONTEST_WINDOW_CLOSED,
        422,
    )
    assert (
        fixtures.read_citation(api, second_citation["id"])["adjudication_status"]
        == ADJUDICATION_ISSUED
    )


def test_a_full_down_payment_is_refused_and_a_completed_assignment_takes_no_more_hours(api):
    """
    It must also be strictly less than `outstanding_balance_cents`, since a plan
    with nothing left to finance is not a plan; a down payment equal to or above
    the balance is refused with `ERR_DOWN_PAYMENT_EXCEEDS_BALANCE`. ... an
    assignment whose `status` is not `ACTIVE` is refused with
    `ERR_SERVICE_NOT_ACTIVE`.  The raw credit is the posted hours multiplied by
    1500 cents, and that figure is then capped at the citation's
    `outstanding_balance_cents` at the moment of the call.

    Design: Corner/errors/service_completion_locks_further_logging_and_a_full_down_payment_is_refused
    """
    chain = fixtures.build_citation_chain(api)
    citation = chain["citation"]
    assert citation["total_due_cents"] == 9720
    assert citation["outstanding_balance_cents"] == 9720
    assert citation["version"] == 1

    validate_error(
        api.create_payment_plan(
            factories.payment_plan_payload(
                citation_id=citation["id"],
                installment_count=3,
                down_payment_cents=9720,
                expected_citation_version=1,
            ),
            PLANNER_HEADERS,
        ),
        ERR_DOWN_PAYMENT_EXCEEDS_BALANCE,
        422,
    )
    _, meta = validate_paginated(
        api.list_payment_plans(PLANNER_HEADERS, {"citation_id": citation["id"]})
    )
    assert meta["total_count"] == 0

    assignment = validate_success(
        api.create_service_assignment(
            factories.service_assignment_payload(
                citation_id=citation["id"],
                partner_org_name=PARTNER_ORG,
                expected_citation_version=1,
            ),
            PLANNER_HEADERS,
        ),
        201,
    )
    assert assignment["required_hours"] == 7
    assert assignment["hours_completed"] == 0
    assert assignment["credited_cents"] == 0
    assert assignment["status"] == SERVICE_STATUS_ACTIVE

    opened = fixtures.read_citation(api, citation["id"])
    assert opened["settlement_status"] == SETTLEMENT_SERVICE_ACTIVE
    assert opened["version"] == 2

    completed = validate_success(
        api.log_service_hours(
            assignment["id"], factories.log_hours_payload(7), PLANNER_HEADERS
        )
    )
    assert completed["hours_completed"] == 7
    assert completed["credited_cents"] == 9720
    assert completed["status"] == SERVICE_STATUS_COMPLETED

    worked_off = fixtures.read_citation(api, citation["id"])
    assert worked_off["service_credit_cents"] == 9720
    assert worked_off["amount_paid_cents"] == 0
    assert worked_off["outstanding_balance_cents"] == 0
    assert worked_off["settlement_status"] == SETTLEMENT_SATISFIED
    assert worked_off["version"] == 3
    assert_citation_money_identity(worked_off)

    ledger = fixtures.citation_ledger(api, citation["id"])
    assert_ledger_row(
        sole_row_with_source(ledger, PAYMENT_SOURCE_SERVICE_CREDIT),
        PAYMENT_SOURCE_SERVICE_CREDIT,
        9720,
        hours_credited=7,
        applied_at=OBSERVATION_AT,
        label="service credit row",
    )

    validate_error(
        api.log_service_hours(
            assignment["id"], factories.log_hours_payload(1), PLANNER_HEADERS
        ),
        ERR_SERVICE_NOT_ACTIVE,
        409,
    )
    assert fixtures.read_service_assignment(api, assignment["id"])["hours_completed"] == 7
    assert len(
        rows_with_source(
            fixtures.citation_ledger(api, citation["id"]), PAYMENT_SOURCE_SERVICE_CREDIT
        )
    ) == 1


def test_a_dismissal_on_the_wrong_reason_blocks_reissue_and_a_stale_hearing_blocks_appeal(api):
    """
    That citation's `dismissal_reason_code` must be `PROCEDURAL_DEFECT`; a
    citation dismissed for signage deficiency, a valid fare, an identity error,
    an undesignated zone or first-offence diversion may never be reissued, and
    the attempt is refused with `ERR_REISSUE_NOT_PERMITTED`. ... a hearing still
    `SCHEDULED`, one that was `CANCELLED`, one whose `decision` is still
    `PENDING`, and one that already dismissed the citation are all refused with
    `ERR_HEARING_NOT_APPEALABLE`.  The two identifiers must agree: the named
    hearing's own `citation_id` must equal the `citation_id` in the body, and a
    mismatch is refused with `ERR_HEARING_CITATION_MISMATCH`.

    Design: Corner/errors/dismissal_reason_gates_reissue_and_appealability_precedes_mismatch
    """
    env = fixtures.build_environment(api)
    inspector_id = env["inspector"]["id"]
    first_rider = env["rider"]
    second_rider = fixtures.register_rider(
        api,
        rider_ref="R-200",
        display_name="Rider Two",
        demographic_band="BAND_B",
        residence_geo_tract="T-002",
    )
    deployment = fixtures.build_active_deployment(api, env)

    first_encounter = fixtures.build_pending_encounter(
        api, env, deployment, rider=first_rider, occurred_at=ENCOUNTER_AT
    )
    second_encounter = fixtures.build_pending_encounter(
        api, env, deployment, rider=second_rider, occurred_at=SECOND_ENCOUNTER_AT
    )
    first_citation = fixtures.issue_citation(api, first_encounter["id"], inspector_id)
    second_citation = fixtures.issue_citation(api, second_encounter["id"], inspector_id)

    dismissing_hearing = fixtures.contest(api, first_citation["id"], first_rider["id"])
    upholding_hearing = fixtures.contest(api, second_citation["id"], second_rider["id"])
    fixtures.decide_hearing(
        api,
        dismissing_hearing["id"],
        DECISION_DISMISS,
        dismissal_reason_code=DISMISSAL_REASON_VALID_FARE_PRESENTED,
    )
    fixtures.decide_hearing(api, upholding_hearing["id"], DECISION_UPHOLD)

    dismissed = fixtures.read_citation(api, first_citation["id"])
    assert dismissed["adjudication_status"] == ADJUDICATION_DISMISSED
    assert dismissed["dismissal_reason_code"] == DISMISSAL_REASON_VALID_FARE_PRESENTED
    assert dismissed["settlement_status"] == SETTLEMENT_WRITTEN_OFF
    assert dismissed["outstanding_balance_cents"] == 0

    upheld = fixtures.read_citation(api, second_citation["id"])
    assert upheld["adjudication_status"] == ADJUDICATION_UPHELD
    assert upheld["outstanding_balance_cents"] == 9720

    # The reason gate answers before the window is ever consulted.
    response = api.reissue_citation(first_citation["id"], PLANNER_HEADERS)
    validate_error(response, ERR_REISSUE_NOT_PERMITTED, 409)
    assert response.json()["data"]["error_id"] != ERR_REISSUE_WINDOW_CLOSED

    _, meta = validate_paginated(
        api.list_citations(PLANNER_HEADERS, {"rider_id": first_rider["id"]})
    )
    assert meta["total_count"] == 1

    first_rider_headers = make_rider_headers(first_rider["id"])
    validate_error(
        api.create_appeal(
            factories.appeal_payload(
                first_citation["id"], dismissing_hearing["id"], GROUNDS_PROCEDURAL_DEFECT
            ),
            first_rider_headers,
        ),
        ERR_HEARING_NOT_APPEALABLE,
        409,
    )
    validate_error(
        api.create_appeal(
            factories.appeal_payload(
                first_citation["id"], upholding_hearing["id"], GROUNDS_PROCEDURAL_DEFECT
            ),
            first_rider_headers,
        ),
        ERR_HEARING_CITATION_MISMATCH,
        422,
    )

    rows, meta = validate_paginated(
        api.list_appeals(BOARD_MEMBER_HEADERS, {"citation_id": first_citation["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_the_second_supplement_request_hits_the_round_limit_not_the_status_rule(api):
    """
    The loop is bounded at 2 rounds: both the supplement request and the
    resubmission require `round_index` to be strictly below 2, so an appeal that
    has already been resubmitted once cannot cycle again and the attempt is
    refused with `ERR_APPEAL_ROUND_LIMIT`.

    Design: Corner/errors/a_third_resubmission_hits_the_appeal_round_limit
    """
    chain = fixtures.build_upheld_citation_chain(api)
    citation_id = chain["citation"]["id"]
    rider_headers = make_rider_headers(chain["rider"]["id"])

    appeal = fixtures.file_appeal(
        api,
        citation_id,
        chain["hearing"]["id"],
        chain["rider"]["id"],
        GROUNDS_PROCEDURAL_DEFECT,
    )
    assert appeal["round_index"] == 1

    awaiting = fixtures.request_supplement(api, appeal["id"])
    assert awaiting["status"] == APPEAL_STATUS_SUPPLEMENT_REQUESTED
    assert_instant_equals(
        awaiting["supplement_deadline_at"],
        SUPPLEMENT_DEADLINE_AT,
        "appeal.supplement_deadline_at",
    )

    resubmitted = validate_success(
        api.resubmit_appeal(
            appeal["id"], factories.appeal_resubmit_payload(), rider_headers
        )
    )
    assert resubmitted["status"] == APPEAL_STATUS_SUBMITTED
    assert resubmitted["round_index"] == 2
    assert not resubmitted.get("supplement_deadline_at")

    # The appeal is back in SUBMITTED, so the status rule is satisfied and the
    # round bound is what refuses the second cycle.
    response = api.request_appeal_supplement(appeal["id"], BOARD_MEMBER_HEADERS)
    validate_error(response, ERR_APPEAL_ROUND_LIMIT, 409)
    assert response.json()["data"]["error_id"] != ERR_APPEAL_STATUS_INVALID

    after = fixtures.read_appeal(api, appeal["id"])
    assert after["status"] == APPEAL_STATUS_SUBMITTED
    assert after["round_index"] == 2
    assert not after.get("supplement_deadline_at")

    citation = fixtures.read_citation(api, citation_id)
    assert citation["adjudication_status"] == ADJUDICATION_UPHELD
    assert citation["settlement_status"] == SETTLEMENT_OUTSTANDING
    assert citation["outstanding_balance_cents"] == 9720
