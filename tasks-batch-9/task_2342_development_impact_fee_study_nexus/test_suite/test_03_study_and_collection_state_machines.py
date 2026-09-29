"""State machines that do not advance in a straight line: the protest remand,
the two independent application dimensions, and the deferral default."""

from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import fixtures, get_success_data
from test_helpers.fixtures import ADMIN


def _agreement_of(api, application_id):
    agreements = get_success_data(api.list_deferral_agreements(application_id, ADMIN))
    assert len(agreements) == 1, f"expected one deferral agreement, got {len(agreements)}"
    return agreements[0]


def _sustained_protest_setup(api):
    chain = fixtures.noticed_program(api, with_roads=False)
    first = fixtures.record_protest(
        api,
        chain.study_id,
        protester_name="Harbor Homeowners Alliance",
        parcel_count=120,
        weight_bp=3000,
    )
    second = fixtures.record_protest(
        api,
        chain.study_id,
        protester_name="Downtown Merchants Group",
        parcel_count=80,
        weight_bp=2500,
    )
    return chain, first, second


def test_sustained_protest_remands_the_study_and_clears_its_notice(api):
    """`revision_round` increments by one. `certified_by_user_id` and
    `certified_at` are both cleared to null. All four notice fields —
    `notice_method`, `notice_days`, `notice_published_at` and
    `protest_window_ends_at` — are cleared to null. The study's `version`
    increments.

    Design: Difficulty/non_linear_state_machine/sustained_protest_remands_noticed_study_back_to_draft
    """
    chain, _, _ = _sustained_protest_setup(api)
    noticed = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    check.assert_timestamp_equals(
        noticed["protest_window_ends_at"], K.CLOCK_PROTEST_WINDOW_END, "protest_window_ends_at"
    )

    fixtures.set_clock(api, K.CLOCK_PROTEST_WINDOW_END)
    remanded = fixtures.close_protest_window(api, chain.study_id)

    assert remanded["status"] == K.STUDY_DRAFT
    assert remanded["revision_round"] == 1
    check.assert_fields_null(
        remanded,
        "certified_by_user_id",
        "certified_at",
        "notice_method",
        "notice_days",
        "notice_published_at",
        "protest_window_ends_at",
    )
    assert remanded["protest_weight_bp"] == 0
    assert remanded["protest_count"] == 0


def test_the_remand_voids_every_recorded_filing_without_erasing_its_weight(api):
    """Every filing of that study whose `status` was `RECORDED` moves to
    `VOIDED`, and `protest_weight_bp` and `protest_count` are both reset to 0,
    because the next notice starts a fresh protest period and the old filings may
    not be carried forward.

    Design: Difficulty/non_linear_state_machine/sustained_protest_remands_noticed_study_back_to_draft
    """
    chain, first, _ = _sustained_protest_setup(api)

    fixtures.set_clock(api, K.CLOCK_PROTEST_WINDOW_END)
    fixtures.close_protest_window(api, chain.study_id)

    filings = get_success_data(api.list_protest_filings(chain.study_id, ADMIN))
    assert len(filings) == 2
    assert {filing["status"] for filing in filings} == {K.PROTEST_VOIDED}
    voided_first = [f for f in filings if f["id"] == first["id"]][0]
    assert voided_first["weight_bp"] == 3000, "the voided filing keeps its recorded weight"
    component = get_success_data(api.get_nexus_component(chain.parks_component_id, ADMIN))
    assert component["allocation_status"] == K.ALLOCATION_VALID


def test_permit_and_certificate_triggers_land_in_different_collection_states(api):
    """When `collection_trigger` is `PERMIT`, `collection_status` moves
    `NOT_DUE → DUE` in the same call. When `collection_trigger` is
    `CERTIFICATE_OF_OCCUPANCY`, `collection_status` stays `NOT_DUE` — the fee is
    not due until the certificate is sought.

    Design: Difficulty/non_linear_state_machine/assessment_and_collection_dimensions_advance_independently
    """
    chain = fixtures.effective_program(api)
    permit_app = fixtures.file_application(api, chain.program_id)
    co_app = fixtures.file_application(
        api,
        chain.program_id,
        permit_number="BP-1002",
        collection_trigger=K.TRIGGER_CERTIFICATE_OF_OCCUPANCY,
    )
    fixtures.set_clock(api, K.CLOCK_ASSESSMENT)

    assessed_permit = fixtures.assess(api, permit_app["id"])
    assessed_co = fixtures.assess(api, co_app["id"])

    assert assessed_permit["assessment_status"] == K.ASSESSMENT_ASSESSED
    assert assessed_co["assessment_status"] == K.ASSESSMENT_ASSESSED
    assert assessed_permit["collection_status"] == K.COLLECTION_DUE
    assert assessed_co["collection_status"] == K.COLLECTION_NOT_DUE
    check.assert_application_totals(assessed_permit, net_due_cents=K.BASELINE_NET_DUE)
    check.assert_application_totals(assessed_co, net_due_cents=K.BASELINE_NET_DUE)


def test_both_assessments_commit_their_demand_units_to_the_same_standards(api):
    """For each assessed line, that line's `demand_units` are added to the owning
    category's `committed_demand_units` and that category's `version` is
    incremented.

    Design: Difficulty/non_linear_state_machine/assessment_and_collection_dimensions_advance_independently
    """
    chain = fixtures.effective_program(api)
    permit_app = fixtures.file_application(api, chain.program_id)
    co_app = fixtures.file_application(
        api,
        chain.program_id,
        permit_number="BP-1002",
        collection_trigger=K.TRIGGER_CERTIFICATE_OF_OCCUPANCY,
    )
    fixtures.set_clock(api, K.CLOCK_ASSESSMENT)

    fixtures.assess(api, permit_app["id"])
    fixtures.assess(api, co_app["id"])

    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    roads = get_success_data(api.get_facility_category(chain.roads_category_id, ADMIN))
    check.assert_category_fund(parks, committed_demand_units=50.0000)
    check.assert_category_fund(roads, committed_demand_units=20.2000)


def _executed_deferral_setup(api):
    chain = fixtures.effective_program(api)
    fixtures.assessed_application(api, chain)
    agreement = fixtures.request_deferral(
        api,
        chain.application_id,
        6000000,
        "2027-01-01T00:00:00Z",
        requested_security_type=K.SECURITY_LETTER_OF_CREDIT,
    )
    executed = fixtures.decide_deferral(api, agreement["id"], K.DEFERRAL_DECISION_EXECUTE)
    return chain, executed


def test_deferral_default_adds_the_penalty_and_makes_the_project_delinquent(api):
    """`due_at` is set to the earlier of `requested_due_at` and `executed_at`
    plus the program's `max_deferral_days` days. When the sweep finds an
    `EXECUTED` agreement whose `due_at` is at or before the logical clock on an
    application whose `collection_status` is `DEFERRED`, the agreement moves
    `EXECUTED → DEFAULTED` with `defaulted_at` stamped and its `version`
    incremented, and the application moves `collection_status`
    `DEFERRED → DELINQUENT`.

    Design: Difficulty/non_linear_state_machine/deferral_default_then_payment_joins_back_to_satisfied
    """
    chain, executed = _executed_deferral_setup(api)
    check.assert_timestamp_equals(executed["due_at"], "2027-01-01T00:00:00Z", "due_at")

    fixtures.set_clock(api, "2027-01-01T00:00:00Z")
    swept = fixtures.sweep(api, chain.program_id)

    assert executed["id"] in swept["defaulted_agreement_ids"]
    assert chain.application_id in swept["delinquent_application_ids"]
    agreement = _agreement_of(api, chain.application_id)
    assert agreement["status"] == K.DEFERRAL_DEFAULTED
    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    assert application["collection_status"] == K.COLLECTION_DELINQUENT
    check.assert_application_totals(
        application, default_penalty_cents=518952, net_due_cents=5708473
    )


def test_paying_a_defaulted_deferral_satisfies_it_and_releases_the_receivable(api):
    """Both `EXECUTED` and `DEFAULTED` converge on `SATISFIED` when the fee is
    finally paid, and `SATISFIED` is terminal. Either way `satisfied_at` is
    stamped, the agreement's `version` increments, and every facility category
    that carried this application's lines has its `deferred_receivable_cents`
    reduced back by the same line amounts.

    Design: Difficulty/non_linear_state_machine/deferral_default_then_payment_joins_back_to_satisfied
    """
    chain, _ = _executed_deferral_setup(api)
    parks_deferred = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(parks_deferred, deferred_receivable_cents=K.BASELINE_PARKS_LINE_NET)
    fixtures.set_clock(api, "2027-01-01T00:00:00Z")
    fixtures.sweep(api, chain.program_id)

    fixtures.pay(api, chain.application_id, 5708473)

    agreement = _agreement_of(api, chain.application_id)
    assert agreement["status"] == K.DEFERRAL_SATISFIED
    assert agreement["satisfied_at"] is not None
    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    assert application["collection_status"] == K.COLLECTION_PAID
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    roads = get_success_data(api.get_facility_category(chain.roads_category_id, ADMIN))
    check.assert_category_fund(parks, deferred_receivable_cents=0)
    check.assert_category_fund(roads, deferred_receivable_cents=0)
