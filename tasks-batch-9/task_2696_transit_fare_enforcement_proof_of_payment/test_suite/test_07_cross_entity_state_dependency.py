"""
Requests whose own payload and own record are in order but which turn on the
live state of a different entity: the zone behind a deployment, the inspector
behind an encounter, and the hearing behind an appeal.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_HEARING_NOT_APPEALABLE,
    ERR_INSPECTOR_CERT_EXPIRED,
    ERR_INSPECTOR_SUSPENDED,
    ERR_ZONE_NOT_DESIGNATED,
)
from test_helpers.assertions import assert_instant_equals, assert_rate_equals
from test_helpers.constants import (
    ADJUDICATION_UPHELD,
    APPEAL_STATUS_SUBMITTED,
    DECISION_PENDING,
    DECISION_UPHOLD,
    DEPLOYMENT_STATUS_ACTIVE,
    DEPLOYMENT_STATUS_PLANNED,
    GROUNDS_PROCEDURAL_DEFECT,
    HEARING_STATUS_HELD,
    HEARING_STATUS_SCHEDULED,
    INSPECTOR_STATUS_SUSPENDED,
    OUTCOME_PENDING,
    SETTLEMENT_OUTSTANDING,
    VALIDATION_NO_PROOF,
    ZONE_STATUS_DESIGNATED,
)
from test_helpers.test_users import (
    HEARING_OFFICER_HEADERS,
    HEARING_OFFICER_USER_ID,
    PLANNER_HEADERS,
    make_fare_inspector_headers,
    make_rider_headers,
)


# ── A deployment waiting on its zone ─────────────────────────────────

def _planned_deployment_over_an_undesignated_zone(api):
    """
    A deployment whose window has opened, over a zone that carries a passing
    audit but has never been designated.
    """
    env = fixtures.build_environment(api, designate=False)
    zone_id = env["zone"]["id"]
    fixtures.get_success_data(api.submit_zone_for_signage(zone_id, PLANNER_HEADERS))
    fixtures.file_audit(api, zone_id, signs_verified_count=10)
    deployment = fixtures.plan_deployment(api, env["line"]["id"], zone_id)
    fixtures.move_clock(api, "2026-08-05T06:00:00Z")
    return env, deployment


def test_activation_is_refused_while_the_zone_is_only_awaiting_signage(api):
    """
    Activation requires the deployment's zone to be `DESIGNATED`; a zone in any
    other status is refused with `ERR_ZONE_NOT_DESIGNATED`, leaving the
    deployment's own `status` at `PLANNED`.

    Design: Difficulty/cross_entity_state_dependency/deployment_activation_depends_on_fare_zone_designation_state
    """
    _env, deployment = _planned_deployment_over_an_undesignated_zone(api)

    validate_error(
        api.activate_deployment(deployment["id"], PLANNER_HEADERS),
        ERR_ZONE_NOT_DESIGNATED,
        409,
    )
    assert (
        fixtures.read_deployment(api, deployment["id"])["status"]
        == DEPLOYMENT_STATUS_PLANNED
    )


def test_designating_the_zone_lets_the_identical_activation_through(api):
    """
    Designation changes only the zone, yet the same activation now succeeds and
    the deployment opens with no encounters recorded against it.

    Design: Difficulty/cross_entity_state_dependency/deployment_activation_depends_on_fare_zone_designation_state
    """
    env, deployment = _planned_deployment_over_an_undesignated_zone(api)
    api.activate_deployment(deployment["id"], PLANNER_HEADERS)

    designated = validate_success(api.designate_zone(env["zone"]["id"], PLANNER_HEADERS), 200)
    assert designated["designation_status"] == ZONE_STATUS_DESIGNATED
    assert_rate_equals(designated["signage_compliance_pct"], 1.0000, "signage_compliance_pct")

    activated = validate_success(
        api.activate_deployment(deployment["id"], PLANNER_HEADERS), 200
    )
    assert activated["status"] == DEPLOYMENT_STATUS_ACTIVE
    assert activated["achieved_sample_count"] == 0
    assert_rate_equals(activated["sample_adequacy_ratio"], 0.0000, "sample_adequacy_ratio")


# ── An encounter waiting on its inspector ────────────────────────────

ENCOUNTER_AT = "2026-08-05T07:00:00Z"


def _three_inspectors_on_one_active_deployment(api):
    """
    One deployment and three inspectors: one fit to work, one suspended, and one
    whose certification lapsed the day before the encounter.
    """
    env = fixtures.build_environment(api)
    suspended = fixtures.register_inspector(
        api,
        badge_number="B-200",
        display_name="Inspector Two",
        status=INSPECTOR_STATUS_SUSPENDED,
    )
    lapsed = fixtures.register_inspector(
        api,
        badge_number="B-300",
        display_name="Inspector Three",
        certification_expiry="2026-08-04T00:00:00Z",
    )
    deployment = fixtures.build_active_deployment(api, env)
    return env, deployment, suspended, lapsed


def _encounter_request(api, deployment, inspector_id, rider_id):
    return api.create_inspection_encounter(
        factories.encounter_payload(
            deployment_id=deployment["id"],
            inspector_id=inspector_id,
            rider_id=rider_id,
            occurred_at=ENCOUNTER_AT,
            fare_media_type="NONE",
            identity_capture_method="GOVT_ID",
        ),
        make_fare_inspector_headers(inspector_id),
    )


def test_a_suspended_inspector_cannot_record_an_encounter(api):
    """
    The inspector's `status` must be `ACTIVE`; a `SUSPENDED` inspector is refused
    with `ERR_INSPECTOR_SUSPENDED`, and the rejection leaves that inspector's own
    record untouched.

    Design: Difficulty/cross_entity_state_dependency/encounter_creation_depends_on_inspector_status_and_certification_state
    """
    env, deployment, suspended, _lapsed = _three_inspectors_on_one_active_deployment(api)

    validate_error(
        _encounter_request(api, deployment, suspended["id"], env["rider"]["id"]),
        ERR_INSPECTOR_SUSPENDED,
        409,
    )
    assert (
        fixtures.read_inspector(api, suspended["id"])["status"]
        == INSPECTOR_STATUS_SUSPENDED
    )


def test_certification_is_tested_against_the_encounter_instant(api):
    """
    An `ACTIVE` inspector whose `certification_expiry` precedes the encounter's
    `occurred_at` is refused with `ERR_INSPECTOR_CERT_EXPIRED`, so the test is
    against the instant of inspection rather than against the logical clock.

    Design: Difficulty/cross_entity_state_dependency/encounter_creation_depends_on_inspector_status_and_certification_state
    """
    env, deployment, _suspended, lapsed = _three_inspectors_on_one_active_deployment(api)

    validate_error(
        _encounter_request(api, deployment, lapsed["id"], env["rider"]["id"]),
        ERR_INSPECTOR_CERT_EXPIRED,
        409,
    )
    assert_instant_equals(
        fixtures.read_inspector(api, lapsed["id"])["certification_expiry"],
        "2026-08-04T00:00:00Z",
        "inspector.certification_expiry",
    )


def test_the_fit_inspector_records_the_same_encounter(api):
    """
    The identical payload under the fit inspector succeeds: an encounter with no
    fare media carries a `validation_result` of `NO_PROOF` and an `outcome` of
    `PENDING`, and it is the only one counted into the sample.

    Design: Difficulty/cross_entity_state_dependency/encounter_creation_depends_on_inspector_status_and_certification_state
    """
    env, deployment, suspended, lapsed = _three_inspectors_on_one_active_deployment(api)
    rider_id = env["rider"]["id"]
    _encounter_request(api, deployment, suspended["id"], rider_id)
    _encounter_request(api, deployment, lapsed["id"], rider_id)

    inspector_id = env["inspector"]["id"]
    encounter = validate_success(
        _encounter_request(api, deployment, inspector_id, rider_id), 201
    )
    assert encounter["validation_result"] == VALIDATION_NO_PROOF
    assert encounter["outcome"] == OUTCOME_PENDING
    assert encounter["inspector_id"] == inspector_id

    counted = fixtures.read_deployment(api, deployment["id"])
    assert counted["achieved_sample_count"] == 1
    assert counted["voided_encounter_count"] == 0
    assert_rate_equals(counted["sample_adequacy_ratio"], 0.2000, "sample_adequacy_ratio")


# ── An appeal waiting on its hearing ─────────────────────────────────

CONTEST_AT = "2026-08-06T00:00:00Z"


def _contested_citation_awaiting_its_hearing(api):
    """A first-offence citation contested but not yet heard."""
    chain = fixtures.build_citation_chain(api)
    fixtures.move_clock(api, CONTEST_AT)
    hearing = fixtures.contest(api, chain["citation"]["id"], chain["rider"]["id"])
    chain["hearing"] = hearing
    return chain


def _appeal_request(api, chain, statement):
    return api.create_appeal(
        factories.appeal_payload(
            citation_id=chain["citation"]["id"],
            hearing_id=chain["hearing"]["id"],
            grounds_code=GROUNDS_PROCEDURAL_DEFECT,
            statement=statement,
        ),
        make_rider_headers(chain["rider"]["id"]),
    )


def test_an_undecided_hearing_is_not_yet_appealable(api):
    """
    An appeal may only be filed against a hearing that is `HELD` and whose
    `decision` is `UPHOLD` or `REDUCE`; a hearing still `SCHEDULED` with
    `decision` `PENDING` is refused with `ERR_HEARING_NOT_APPEALABLE`.

    Design: Difficulty/cross_entity_state_dependency/appeal_filing_depends_on_adjudication_hearing_decision_state
    """
    chain = _contested_citation_awaiting_its_hearing(api)

    validate_error(
        _appeal_request(api, chain, "Filing before the hearing has been held."),
        ERR_HEARING_NOT_APPEALABLE,
        409,
    )

    hearing = fixtures.read_hearing(api, chain["hearing"]["id"])
    assert hearing["status"] == HEARING_STATUS_SCHEDULED
    assert hearing["decision"] == DECISION_PENDING
    assert_instant_equals(hearing["scheduled_for"], "2026-08-20T00:00:00Z", "hearing.scheduled_for")


def test_deciding_the_hearing_makes_the_identical_filing_succeed(api):
    """
    Once the hearing is `HELD` with `decision` `UPHOLD` and the citation has moved
    `CONTESTED` to `UPHELD`, the same request creates the appeal in `SUBMITTED`
    with `round_index` 1 and no supplement deadline.

    Design: Difficulty/cross_entity_state_dependency/appeal_filing_depends_on_adjudication_hearing_decision_state
    """
    chain = _contested_citation_awaiting_its_hearing(api)
    _appeal_request(api, chain, "Filing before the hearing has been held.")

    decided = validate_success(
        api.decide_hearing(
            chain["hearing"]["id"],
            factories.hearing_decision_payload(DECISION_UPHOLD),
            HEARING_OFFICER_HEADERS,
        ),
        200,
    )
    assert decided["status"] == HEARING_STATUS_HELD
    assert decided["decision"] == DECISION_UPHOLD
    assert_instant_equals(decided["decided_at"], CONTEST_AT, "decided.decided_at")
    assert decided["hearing_officer_user_id"] == HEARING_OFFICER_USER_ID
    assert (
        fixtures.read_citation(api, chain["citation"]["id"])["adjudication_status"]
        == ADJUDICATION_UPHELD
    )

    appeal = validate_success(
        _appeal_request(
            api,
            chain,
            "The hearing officer did not consider the signage photographs I submitted.",
        ),
        201,
    )
    assert appeal["status"] == APPEAL_STATUS_SUBMITTED
    assert appeal["round_index"] == 1
    assert appeal["appellant_rider_id"] == chain["rider"]["id"]
    assert appeal["hearing_id"] == chain["hearing"]["id"]
    assert not appeal["supplement_deadline_at"]


def test_neither_the_refusal_nor_the_grant_of_the_appeal_moves_the_money(api):
    """
    The settlement dimension is untouched by the whole appeal-filing sequence:
    the citation stays `OUTSTANDING` owing its full 9720 throughout.

    Design: Difficulty/cross_entity_state_dependency/appeal_filing_depends_on_adjudication_hearing_decision_state
    """
    chain = _contested_citation_awaiting_its_hearing(api)
    _appeal_request(api, chain, "Filing before the hearing has been held.")
    fixtures.decide_hearing(api, chain["hearing"]["id"], DECISION_UPHOLD)
    fixtures.get_success_data(
        _appeal_request(
            api,
            chain,
            "The hearing officer did not consider the signage photographs I submitted.",
        )
    )

    citation = fixtures.read_citation(api, chain["citation"]["id"])
    assert citation["settlement_status"] == SETTLEMENT_OUTSTANDING
    assert citation["outstanding_balance_cents"] == 9720
