"""Gates whose verdict lives in a sibling record the request never names."""

from test_helpers import ANALYST_1, api_errors as err
from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import fixtures, get_success_data, validate_error
from test_helpers.fixtures import ADMIN, ANALYST, PERMIT_OFFICER


def _adopted_program_with_a_filed_application(api):
    chain = fixtures.adopted_program(api)
    application = fixtures.file_application(api, chain.program_id)
    chain.application_id = application["id"]
    fixtures.set_clock(api, K.CLOCK_EFFECTIVE_DATE)
    return chain


def test_assessment_is_refused_while_the_only_study_is_merely_adopted(api):
    """Three preconditions guard it. The program must have exactly one study in
    status `EFFECTIVE`, or the request is refused with `ERR_NO_EFFECTIVE_STUDY`.

    Design: Difficulty/cross_entity_state_dependency/assessment_requires_an_effective_study_in_the_program
    """
    chain = _adopted_program_with_a_filed_application(api)

    response = api.assess_application(chain.application_id, PERMIT_OFFICER)

    validate_error(response, err.ERR_NO_EFFECTIVE_STUDY, 409)
    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    assert application["assessment_status"] == K.ASSESSMENT_UNASSESSED
    assert application["collection_status"] == K.COLLECTION_NOT_DUE
    check.assert_fields_null(application, "pinned_fee_study_id", "assessed_at")
    check.assert_application_totals(application, gross_assessed_cents=0, net_due_cents=0)
    assert application["assessed_lines"] == []


def test_the_same_assessment_succeeds_once_the_study_is_activated(api):
    """Assessment records `pinned_fee_study_id` and `pinned_fee_study_version`
    from the effective study, stamps `assessed_at` on a first assessment and
    `reassessed_at` on a re-run, sets `reassessment_required` to false, and
    increments the application's `version`.

    Design: Difficulty/cross_entity_state_dependency/assessment_requires_an_effective_study_in_the_program
    """
    chain = _adopted_program_with_a_filed_application(api)
    api.assess_application(chain.application_id, PERMIT_OFFICER)

    fixtures.activate(api, chain.study_id)
    assessed = fixtures.assess(api, chain.application_id)

    assert assessed["assessment_status"] == K.ASSESSMENT_ASSESSED
    assert assessed["collection_status"] == K.COLLECTION_DUE
    assert assessed["pinned_fee_study_id"] == chain.study_id
    assert assessed["reassessment_required"] is False
    check.assert_application_totals(
        assessed,
        gross_assessed_cents=K.BASELINE_GROSS_ASSESSED,
        net_due_cents=K.BASELINE_NET_DUE,
    )
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(parks, committed_demand_units=25.0000)


def test_a_certificate_is_blocked_while_a_requested_deferral_is_undecided(api):
    """A `PermitOfficer` issues it only when `assessment_status` is `ASSESSED` or
    `REASSESSED`, `reassessment_required` is false (otherwise
    `ERR_REASSESSMENT_REQUIRED`), `collection_status` is `PAID`, no agreement of
    the application is left in `REQUESTED`, `EXECUTED` or `DEFAULTED`, and
    `co_issued_at` is still null. An unpaid fee or an open deferral obligation
    both surface as `ERR_CO_BLOCKED_UNPAID`; an already-issued certificate
    surfaces as `ERR_APPLICATION_INVALID_STATE`.

    Design: Difficulty/cross_entity_state_dependency/certificate_of_occupancy_is_blocked_by_an_open_deferral_agreement
    """
    chain = fixtures.effective_program(api)
    fixtures.assessed_application(api, chain)
    agreement = fixtures.request_deferral(
        api,
        chain.application_id,
        6000000,
        "2027-01-01T00:00:00Z",
        requested_security_type=K.SECURITY_LETTER_OF_CREDIT,
    )
    fixtures.paid_application(api, chain)
    paid = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    assert paid["collection_status"] == K.COLLECTION_PAID
    check.assert_application_totals(
        paid, net_due_cents=K.BASELINE_NET_DUE, paid_cents=K.BASELINE_NET_DUE
    )

    response = api.issue_co(chain.application_id, PERMIT_OFFICER)

    validate_error(response, err.ERR_CO_BLOCKED_UNPAID, 409)
    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    check.assert_fields_null(application, "co_issued_at")
    assert application["collection_status"] == K.COLLECTION_PAID
    agreements = get_success_data(api.list_deferral_agreements(chain.application_id, ADMIN))
    assert [row["status"] for row in agreements] == [K.DEFERRAL_REQUESTED]
    assert agreements[0]["id"] == agreement["id"]
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(parks, deferred_receivable_cents=0)


def _study_with_one_stale_roads_component(api):
    chain = fixtures.draft_program(api)
    api.patch_nexus_component(
        chain.roads_component_id, {"planned_growth_share_bp": 7000}, ANALYST
    )
    return chain


def test_certification_is_refused_while_a_sibling_component_is_stale(api):
    """The full revision loop is therefore `PENDING` or
    `STALE → VALID → STALE → VALID`, with certification available again once every
    component is back to `VALID`. The component moves `VALID → STALE`, and
    `plan_based_cost_per_unit_cents`, `standard_based_cost_per_unit_cents`,
    `adopted_cost_per_unit_cents` and `nexus_ratio` are all set to null.

    Design: Difficulty/cross_entity_state_dependency/certification_is_blocked_by_a_stale_component_of_another_category
    """
    chain = _study_with_one_stale_roads_component(api)

    response = api.certify_nexus(chain.study_id, ANALYST)

    validate_error(response, err.ERR_COMPONENT_ALLOCATION_STALE, 409)
    study = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    assert study["status"] == K.STUDY_DRAFT
    check.assert_fields_null(study, "certified_at", "certified_by_user_id")
    parks = get_success_data(api.get_nexus_component(chain.parks_component_id, ADMIN))
    assert parks["allocation_status"] == K.ALLOCATION_VALID
    check.assert_money_equals(
        parks["adopted_cost_per_unit_cents"], 101667, "adopted_cost_per_unit_cents"
    )
    roads = get_success_data(api.get_nexus_component(chain.roads_component_id, ADMIN))
    assert roads["allocation_status"] == K.ALLOCATION_STALE


def test_repairing_the_sibling_component_reopens_certification(api):
    """It also does one thing the first allocation had no occasion to do: every
    schedule line of that component returns to `schedule_status` `VALID` with its
    `fee_per_unit_cents` recomputed from the freshly adopted per-unit cost and its
    own conversion factor. Certification writes `certified_by_user_id` from the
    caller's `X-User-ID` and `certified_at` from the logical clock, and increments
    the study's `version`.

    Design: Difficulty/cross_entity_state_dependency/certification_is_blocked_by_a_stale_component_of_another_category
    """
    chain = _study_with_one_stale_roads_component(api)
    api.certify_nexus(chain.study_id, ANALYST)

    repaired = fixtures.allocate(api, chain.roads_component_id)

    assert repaired["allocation_status"] == K.ALLOCATION_VALID
    check.assert_money_equals(
        repaired["plan_based_cost_per_unit_cents"], 270133, "plan_based_cost_per_unit_cents"
    )
    check.assert_money_equals(
        repaired["adopted_cost_per_unit_cents"], 270133, "adopted_cost_per_unit_cents"
    )
    check.assert_four_decimal_equals(repaired["nexus_ratio"], 1.0194, "nexus_ratio")
    roads_lines = get_success_data(api.list_fee_schedule_items(chain.roads_component_id, ADMIN))
    assert [line["schedule_status"] for line in roads_lines] == [K.SCHEDULE_VALID]
    check.assert_money_equals(
        roads_lines[0]["fee_per_unit_cents"], 272834, "fee_per_unit_cents"
    )
    parks_lines = get_success_data(api.list_fee_schedule_items(chain.parks_component_id, ADMIN))
    check.assert_money_equals(
        parks_lines[0]["fee_per_unit_cents"],
        K.PARKS_SINGLE_FAMILY_FEE_PER_UNIT,
        "fee_per_unit_cents",
    )

    certified = fixtures.certify(api, chain.study_id)
    assert certified["status"] == K.STUDY_NEXUS_CERTIFIED
    assert certified["certified_by_user_id"] == ANALYST_1
