"""
Role authority: one citation carried end to end by all six roles in turn, the
six cross-role attempts that are refused before any business rule is reached,
and the three identity comparisons — rider ownership, inspector-on-encounter,
and appellate segregation of duties — that a matching role header cannot buy.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_ENCOUNTER_NOT_PENDING,
    ERR_FORBIDDEN_ROLE,
    ERR_INSPECTOR_NOT_ON_ENCOUNTER,
    ERR_NOT_RESOURCE_OWNER,
    ERR_OPEN_ENCOUNTERS_REMAIN,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_CITATION_VERSION,
)
from test_helpers.assertions import (
    assert_citation_money_identity,
    assert_rate_equals,
)
from test_helpers.constants import (
    ADJUDICATION_CONTESTED,
    ADJUDICATION_ISSUED,
    ADJUDICATION_UPHELD,
    APPEAL_DECISION_DENIED,
    APPEAL_STATUS_DENIED,
    APPEAL_STATUS_SUBMITTED,
    APPEAL_STATUS_SUPPLEMENT_REQUESTED,
    BAND_A,
    CLOCK_EPOCH,
    DECISION_UPHOLD,
    DEPLOYMENT_STATUS_ACTIVE,
    GROUNDS_PROCEDURAL_DEFECT,
    GROUP_BY_DEMOGRAPHIC_BAND,
    HEARING_STATUS_HELD,
    HEARING_STATUS_SCHEDULED,
    OUTCOME_PENDING,
    OUTCOME_WARNING_ISSUED,
    SETTLEMENT_OUTSTANDING,
    VALIDATION_NO_PROOF,
)
from test_helpers.fixtures import ENCOUNTER_AT, OBSERVATION_AT, WINDOW_START
from test_helpers.test_users import (
    ANALYST_HEADERS,
    BOARD_MEMBER_HEADERS,
    HEARING_OFFICER_HEADERS,
    HEARING_OFFICER_USER_ID,
    PLANNER_HEADERS,
    make_board_member_headers,
    make_fare_inspector_headers,
    make_rider_headers,
)

REPORT_WINDOW_END = "2026-09-01T00:00:00Z"
SECOND_ENCOUNTER_AT = "2026-08-05T08:00:00Z"
MEDIA_NONE = "NONE"
IDENTITY_GOVT_ID = "GOVT_ID"
WARNING_ISSUED = "WARNING_ISSUED"


def test_all_six_roles_carry_one_citation_through_their_own_exclusive_stage(api):
    """
    Planners designate and suspend proof-of-payment zones, file signage audits,
    maintain the line network and the inspector and rider registries, plan,
    activate, close and void sampled deployments ... A `FareInspector` works an
    active deployment in the field ... A `Rider` is a cited rider who contests a
    citation, files, supplements and withdraws appeals ... A `HearingOfficer`
    adjudicates contested citations ... An `AppealsBoardMember` requests
    supplementation of an appeal and grants or denies it.  An `EquityAnalyst` is
    strictly read-only.

    Design: Corner/rbac/every_role_can_exercise_its_own_exclusive_operation
    """
    validate_success(api.set_clock(factories.clock_payload(CLOCK_EPOCH), ANALYST_HEADERS))

    env = fixtures.build_environment(api)
    inspector_id = env["inspector"]["id"]
    rider_id = env["rider"]["id"]
    inspector_headers = make_fare_inspector_headers(inspector_id)
    rider_headers = make_rider_headers(rider_id)
    deployment = fixtures.plan_deployment(api, env["line"]["id"], env["zone"]["id"])

    validate_success(api.set_clock(factories.clock_payload(WINDOW_START), inspector_headers))
    validate_success(api.activate_deployment(deployment["id"], PLANNER_HEADERS))
    validate_success(
        api.set_clock(factories.clock_payload(OBSERVATION_AT), HEARING_OFFICER_HEADERS)
    )

    encounter = validate_success(
        api.create_inspection_encounter(
            factories.encounter_payload(
                deployment_id=deployment["id"],
                inspector_id=inspector_id,
                rider_id=rider_id,
                occurred_at=ENCOUNTER_AT,
                fare_media_type=MEDIA_NONE,
                identity_capture_method=IDENTITY_GOVT_ID,
            ),
            inspector_headers,
        ),
        201,
    )
    assert encounter["validation_result"] == VALIDATION_NO_PROOF

    citation = validate_success(
        api.create_citation(factories.citation_payload(encounter["id"]), inspector_headers), 201
    )
    assert citation["total_due_cents"] == 9720
    assert_citation_money_identity(citation)

    hearing = validate_success(api.contest_citation(citation["id"], rider_headers), 201)
    assert (
        fixtures.read_citation(api, citation["id"])["adjudication_status"]
        == ADJUDICATION_CONTESTED
    )

    decided = validate_success(
        api.decide_hearing(
            hearing["id"],
            factories.hearing_decision_payload(DECISION_UPHOLD),
            HEARING_OFFICER_HEADERS,
        )
    )
    assert decided["status"] == HEARING_STATUS_HELD
    assert decided["decision"] == DECISION_UPHOLD
    assert decided["hearing_officer_user_id"] == HEARING_OFFICER_USER_ID

    appeal = validate_success(
        api.create_appeal(
            factories.appeal_payload(
                citation["id"], hearing["id"], GROUNDS_PROCEDURAL_DEFECT
            ),
            rider_headers,
        ),
        201,
    )
    assert appeal["status"] == APPEAL_STATUS_SUBMITTED
    assert appeal["round_index"] == 1

    awaiting = validate_success(
        api.request_appeal_supplement(appeal["id"], BOARD_MEMBER_HEADERS)
    )
    assert awaiting["status"] == APPEAL_STATUS_SUPPLEMENT_REQUESTED

    report = validate_success(
        api.get_equity_distribution_report(
            factories.equity_report_params(
                window_start=CLOCK_EPOCH,
                window_end=REPORT_WINDOW_END,
                group_by=GROUP_BY_DEMOGRAPHIC_BAND,
            ),
            ANALYST_HEADERS,
        )
    )
    assert report["encounter_pool_count"] == 1
    assert report["citation_count"] == 1
    assert report["groups_evaluated"] == 1
    assert_rate_equals(
        report["systemwide_citation_rate"], 1.0000, "report.systemwide_citation_rate"
    )
    assert [group["group_key"] for group in report["groups"]] == [BAND_A]


def test_a_role_header_from_the_wrong_role_is_refused_before_any_business_rule(api):
    """
    If the role is declared but is not one of the roles authorised for the
    endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403).  These two checks precede all others: authentication first, then
    role membership, then everything else.

    Design: Corner/rbac/role_exclusive_operations_cannot_be_crossed_by_another_role
    """
    chain = fixtures.build_citation_chain(api)
    citation_id = chain["citation"]["id"]
    encounter_id = chain["encounter"]["id"]
    deployment_id = chain["deployment"]["id"]
    inspector_id = chain["inspector"]["id"]
    rider_id = chain["rider"]["id"]
    hearing = fixtures.contest(api, citation_id, rider_id)

    crossings = (
        api.create_fare_zone(
            factories.fare_zone_payload(
                zone_code="ZN9", name="Analyst Zone", required_sign_count=5
            ),
            ANALYST_HEADERS,
        ),
        api.create_inspection_encounter(
            factories.encounter_payload(
                deployment_id=deployment_id,
                inspector_id=inspector_id,
                rider_id=rider_id,
                occurred_at=SECOND_ENCOUNTER_AT,
                fare_media_type=MEDIA_NONE,
                identity_capture_method=IDENTITY_GOVT_ID,
            ),
            make_rider_headers(rider_id),
        ),
        api.contest_citation(citation_id, make_fare_inspector_headers(inspector_id)),
        api.create_citation(factories.citation_payload(encounter_id), PLANNER_HEADERS),
        api.decide_hearing(
            hearing["id"],
            factories.hearing_decision_payload(DECISION_UPHOLD),
            BOARD_MEMBER_HEADERS,
        ),
        api.close_deployment(deployment_id, HEARING_OFFICER_HEADERS),
    )
    for response in crossings:
        validate_error(response, ERR_FORBIDDEN_ROLE, 403)

    # The planner's citation attempt would have earned a state refusal on merit.
    assert crossings[3].json()["data"]["error_id"] != ERR_ENCOUNTER_NOT_PENDING
    assert crossings[5].json()["data"]["error_id"] != ERR_OPEN_ENCOUNTERS_REMAIN

    _, zone_meta = validate_paginated(api.list_fare_zones(PLANNER_HEADERS))
    assert zone_meta["total_count"] == 1
    _, citation_meta = validate_paginated(api.list_citations(PLANNER_HEADERS))
    assert citation_meta["total_count"] == 1

    assert fixtures.read_hearing(api, hearing["id"])["status"] == HEARING_STATUS_SCHEDULED
    assert fixtures.read_deployment(api, deployment_id)["status"] == DEPLOYMENT_STATUS_ACTIVE


def test_a_second_rider_is_refused_on_every_rider_authorised_write(api):
    """
    When `X-User-Role` is `Rider`, `X-User-ID` is the `id` of the acting `Rider`
    record; ownership checks compare the resource's rider foreign key to
    `X-User-ID`, so a rider may only act on a citation whose `rider_id` is their
    own, on an appeal whose `appellant_rider_id` is their own, and on a payment
    plan whose citation's `rider_id` is their own.

    Design: Corner/rbac/a_rider_cannot_act_on_another_riders_citation
    """
    chain = fixtures.build_citation_chain(api)
    citation = chain["citation"]
    owner_id = chain["rider"]["id"]
    intruder = fixtures.register_rider(
        api,
        rider_ref="R-200",
        display_name="Rider Two",
        demographic_band="BAND_B",
        residence_geo_tract="T-002",
    )
    intruder_headers = make_rider_headers(intruder["id"])
    assert citation["version"] == 1

    attempts = (
        api.contest_citation(citation["id"], intruder_headers),
        api.create_citation_payment(
            citation["id"], factories.citation_payment_payload(1000), intruder_headers
        ),
        api.create_payment_plan(
            factories.payment_plan_payload(
                citation_id=citation["id"],
                installment_count=2,
                down_payment_cents=1000,
                expected_citation_version=1,
            ),
            intruder_headers,
        ),
    )
    for response in attempts:
        validate_error(response, ERR_NOT_RESOURCE_OWNER, 403)

    # The plan attempt pinned the citation's real version, so the version rule
    # cannot be what refused it.
    assert attempts[2].json()["data"]["error_id"] != ERR_STALE_CITATION_VERSION

    untouched = fixtures.read_citation(api, citation["id"])
    assert untouched["adjudication_status"] == ADJUDICATION_ISSUED
    assert untouched["settlement_status"] == SETTLEMENT_OUTSTANDING
    assert untouched["outstanding_balance_cents"] == 9720
    assert untouched["version"] == 1

    assert fixtures.citation_ledger(api, citation["id"]) == []
    _, plan_meta = validate_paginated(
        api.list_payment_plans(PLANNER_HEADERS, {"citation_id": citation["id"]})
    )
    assert plan_meta["total_count"] == 0

    # The identical payment from the cited rider is accepted, so the refusal was
    # about identity rather than about endpoint authority.
    paid = validate_success(
        api.create_citation_payment(
            citation["id"],
            factories.citation_payment_payload(1000),
            make_rider_headers(owner_id),
        ),
        201,
    )
    assert paid["amount_cents"] == 1000
    assert fixtures.read_citation(api, citation["id"])["amount_paid_cents"] == 1000


def test_a_second_badge_may_neither_resolve_nor_cite_the_first_badges_encounter(api):
    """
    When `X-User-Role` is `FareInspector`, `X-User-ID` is the `id` of the acting
    `Inspector` record; ownership checks on any resource that references an
    `Inspector` compare that resource's inspector foreign key to `X-User-ID`, so
    recording or resolving an encounter and issuing a citation from it require
    `X-User-ID` to equal the encounter's `inspector_id`.

    Design: Corner/rbac/an_inspector_cannot_resolve_or_cite_another_inspectors_encounter
    """
    env = fixtures.build_environment(api)
    first_inspector_id = env["inspector"]["id"]
    second_inspector = fixtures.register_inspector(
        api, badge_number="B-200", display_name="Inspector Two"
    )
    deployment = fixtures.build_active_deployment(api, env)
    encounter = fixtures.build_pending_encounter(api, env, deployment)

    stranger_headers = make_fare_inspector_headers(second_inspector["id"])
    validate_error(
        api.resolve_encounter(
            encounter["id"], factories.resolve_payload(WARNING_ISSUED), stranger_headers
        ),
        ERR_INSPECTOR_NOT_ON_ENCOUNTER,
        403,
    )
    validate_error(
        api.create_citation(factories.citation_payload(encounter["id"]), stranger_headers),
        ERR_INSPECTOR_NOT_ON_ENCOUNTER,
        403,
    )

    untouched = fixtures.read_encounter(api, encounter["id"])
    assert untouched["inspector_id"] == first_inspector_id
    assert untouched["outcome"] == OUTCOME_PENDING
    assert fixtures.read_inspector(api, second_inspector["id"])["citations_issued_count"] == 0

    rows, meta = validate_paginated(
        api.list_citations(PLANNER_HEADERS, {"encounter_id": encounter["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []

    # The identical disposition from the inspector who worked the encounter is
    # accepted, so the payload itself was never the problem.
    resolved = validate_success(
        api.resolve_encounter(
            encounter["id"],
            factories.resolve_payload(WARNING_ISSUED),
            make_fare_inspector_headers(first_inspector_id),
        )
    )
    assert resolved["outcome"] == OUTCOME_WARNING_ISSUED


def test_the_officer_who_decided_the_hearing_cannot_touch_the_appeal(api):
    """
    Per the agency's segregation-of-duties rule, the officer who decided a
    citation's administrative hearing may not act on the appeal of that same
    hearing: whenever an `AppealsBoardMember`'s `X-User-ID` equals the
    `hearing_officer_user_id` recorded on the hearing the appeal was filed
    against, the request is refused with `ERR_SEGREGATION_OF_DUTIES`.  That guard
    applies to both board-member operations — requesting a supplement and
    deciding the appeal.

    Design: Corner/rbac/the_deciding_hearing_officer_cannot_sit_on_the_appeal
    """
    chain = fixtures.build_upheld_citation_chain(api)
    citation_id = chain["citation"]["id"]
    hearing = chain["hearing"]
    assert hearing["hearing_officer_user_id"] == HEARING_OFFICER_USER_ID

    appeal = fixtures.file_appeal(
        api, citation_id, hearing["id"], chain["rider"]["id"], GROUNDS_PROCEDURAL_DEFECT
    )
    conflicted_headers = make_board_member_headers(HEARING_OFFICER_USER_ID)

    validate_error(
        api.request_appeal_supplement(appeal["id"], conflicted_headers),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    validate_error(
        api.decide_appeal(
            appeal["id"],
            factories.appeal_decision_payload(APPEAL_DECISION_DENIED),
            conflicted_headers,
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    still_open = fixtures.read_appeal(api, appeal["id"])
    assert still_open["status"] == APPEAL_STATUS_SUBMITTED
    assert still_open["round_index"] == 1

    # A board member who did not decide the hearing may decide the appeal.
    denied = get_success_data(
        api.decide_appeal(
            appeal["id"],
            factories.appeal_decision_payload(APPEAL_DECISION_DENIED),
            BOARD_MEMBER_HEADERS,
        )
    )
    assert denied["status"] == APPEAL_STATUS_DENIED

    citation = fixtures.read_citation(api, citation_id)
    assert citation["adjudication_status"] == ADJUDICATION_UPHELD
    assert citation["outstanding_balance_cents"] == 9720
    assert_citation_money_identity(citation)
