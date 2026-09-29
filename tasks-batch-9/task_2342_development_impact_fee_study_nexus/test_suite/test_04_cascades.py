"""Cascades that run several hops from the record the client named."""

from test_helpers import ANALYST_2, api_errors as err
from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import fixtures, get_success_data, make_analyst_headers, validate_error
from test_helpers.fixtures import ADMIN, ANALYST, FINANCE

REVIEWER = make_analyst_headers(ANALYST_2)


def _schedule_line_of(api, component_id):
    lines = get_success_data(api.list_fee_schedule_items(component_id, ADMIN))
    assert len(lines) == 1, f"expected one schedule line, got {len(lines)}"
    return lines[0]


def _noticed_parks_study_with_protests(api):
    chain = fixtures.noticed_program(api, with_roads=False)
    fixtures.record_protest(
        api,
        chain.study_id,
        protester_name="Harbor Homeowners Alliance",
        parcel_count=60,
        weight_bp=1000,
    )
    fixtures.record_protest(
        api,
        chain.study_id,
        protester_name="Bayside Builders Council",
        parcel_count=40,
        weight_bp=1000,
    )
    return chain


def test_component_revision_stales_the_component_and_its_schedule_line(api):
    """The patched inputs are stored and `growth_demand_units` is recomputed
    immediately. The component moves `VALID → STALE`, and
    `plan_based_cost_per_unit_cents`, `standard_based_cost_per_unit_cents`,
    `adopted_cost_per_unit_cents` and `nexus_ratio` are all set to null. Because
    the component went stale, every schedule line belonging to it moves
    `VALID → STALE` and its `fee_per_unit_cents` is set to null.

    Design: Difficulty/transitive_cascade/component_patch_decertifies_noticed_study_and_voids_protest_tally
    """
    chain = _noticed_parks_study_with_protests(api)

    patched = get_success_data(
        api.patch_nexus_component(
            chain.parks_component_id, {"planned_facility_cost_cents": 600000000}, ANALYST
        )
    )

    assert patched["allocation_status"] == K.ALLOCATION_STALE
    check.assert_money_equals(
        patched["planned_facility_cost_cents"], 600000000, "planned_facility_cost_cents"
    )
    check.assert_four_decimal_equals(
        patched["growth_demand_units"], 3000.0000, "growth_demand_units"
    )
    check.assert_fields_null(
        patched,
        "plan_based_cost_per_unit_cents",
        "standard_based_cost_per_unit_cents",
        "adopted_cost_per_unit_cents",
        "nexus_ratio",
    )
    line = _schedule_line_of(api, chain.parks_component_id)
    assert line["schedule_status"] == K.SCHEDULE_STALE
    check.assert_fields_null(line, "fee_per_unit_cents")


def test_component_revision_remands_the_noticed_study_and_voids_its_tally(api):
    """Because a child schedule line went stale, the parent study is remanded to
    `DRAFT` if it was sitting in `NEXUS_CERTIFIED` or `NOTICE_PUBLISHED`. When the
    study being remanded was in `NOTICE_PUBLISHED` rather than `NEXUS_CERTIFIED`,
    the remand additionally clears `notice_method`, `notice_days`,
    `notice_published_at` and `protest_window_ends_at` to null, moves every
    `RECORDED` filing of that study to `VOIDED`, and resets `protest_weight_bp`
    and `protest_count` to 0.

    Design: Difficulty/transitive_cascade/component_patch_decertifies_noticed_study_and_voids_protest_tally
    """
    chain = _noticed_parks_study_with_protests(api)
    noticed = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    assert noticed["protest_weight_bp"] == 2000
    check.assert_timestamp_equals(
        noticed["protest_window_ends_at"], K.CLOCK_PROTEST_WINDOW_END, "protest_window_ends_at"
    )

    api.patch_nexus_component(
        chain.parks_component_id, {"planned_facility_cost_cents": 600000000}, ANALYST
    )

    study = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    assert study["status"] == K.STUDY_DRAFT
    assert study["revision_round"] == 1
    check.assert_fields_null(
        study,
        "certified_by_user_id",
        "certified_at",
        "notice_method",
        "notice_days",
        "notice_published_at",
        "protest_window_ends_at",
    )
    assert study["protest_weight_bp"] == 0
    assert study["protest_count"] == 0
    filings = get_success_data(api.list_protest_filings(chain.study_id, ADMIN))
    assert {filing["status"] for filing in filings} == {K.PROTEST_VOIDED}


def _paid_application_with_parks_credit(api):
    chain = fixtures.effective_program_with_paid_application(api)
    parks_entry = fixtures.collection_rows_for(api, chain.parks_category_id)[0]
    claim = fixtures.file_credit_claim(
        api,
        chain.application_id,
        facility_category_code=K.PARKS_CODE,
        credit_type=K.CREDIT_TYPE_DEVELOPER_IMPROVEMENT,
        valuation_method=K.VALUATION_NOMINAL,
        improvement_value_cents=1000000,
        contribution_years=0,
    )
    return chain, parks_entry, claim


def test_credit_approval_reprices_a_paid_application_into_overpayment(api):
    """Because an approval can only reduce `net_due_cents`, an application that
    had already reached `collection_status` `PAID` may now have `paid_cents`
    greater than `net_due_cents`; that surplus is a refundable overpayment,
    discharged through the ledger as described in §3.9.

    Design: Difficulty/transitive_cascade/credit_approval_reassesses_paid_application_and_opens_overpayment_refund
    """
    chain, _, claim = _paid_application_with_parks_credit(api)

    decided = fixtures.decide_credit_claim(
        api, claim["id"], chain.application_id, K.DECISION_APPROVE_FULL, headers=REVIEWER
    )

    assert decided["status"] == K.CLAIM_APPROVED_FULL
    check.assert_money_equals(decided["approved_cents"], 1000000, "approved_cents")
    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    assert application["assessment_status"] == K.ASSESSMENT_REASSESSED
    check.assert_application_totals(
        application,
        credit_applied_cents=1000000,
        admin_charge_cents=121151,
        net_due_cents=4159521,
        paid_cents=K.BASELINE_NET_DUE,
    )
    assert application["paid_cents"] - application["net_due_cents"] == 1030000


def test_the_overpayment_refund_leaves_the_source_row_open_with_the_remainder(api):
    """Continuing the earlier example: a parks row of 2,617,930 cents fully
    unexpended and `REFUND_DUE` refunds all of it and returns `refund_due_cents` to
    zero, while an application that paid 5,189,521 cents and was then re-assessed to
    4,159,521 by an approved credit has overpaid by 1,030,000, so a refund against a
    parks row holding 2,617,930 unexpended returns 1,030,000 and leaves that row
    `OPEN` with 1,587,930.

    Design: Difficulty/transitive_cascade/credit_approval_reassesses_paid_application_and_opens_overpayment_refund
    """
    chain, parks_entry, claim = _paid_application_with_parks_credit(api)
    fixtures.decide_credit_claim(
        api, claim["id"], chain.application_id, K.DECISION_APPROVE_FULL, headers=REVIEWER
    )

    refund_row = get_success_data(
        api.refund_ledger_entry(
            parks_entry["id"], FINANCE, {"reason": "overpayment created by approved PARKS credit"}
        ),
        201,
    )

    check.assert_money_equals(refund_row["amount_cents"], 1030000, "amount_cents")
    assert refund_row["kind"] == K.LEDGER_KIND_REFUND
    assert refund_row["entry_status"] == K.ENTRY_POSTED
    assert refund_row["refunded_entry_id"] == parks_entry["id"]
    source = get_success_data(api.get_fund_ledger_entry(parks_entry["id"], ADMIN))
    assert source["entry_status"] == K.ENTRY_OPEN
    check.assert_money_equals(source["unexpended_cents"], 1587930, "unexpended_cents")
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    roads = get_success_data(api.get_facility_category(chain.roads_category_id, ADMIN))
    check.assert_category_fund(parks, fund_balance_cents=1587930)
    check.assert_category_fund(roads, fund_balance_cents=K.BASELINE_ROADS_LINE_NET)
    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    check.assert_application_totals(application, paid_cents=4159521)
    assert application["collection_status"] == K.COLLECTION_PAID


def _second_certified_study(api, chain):
    """A second study of the same program, priced over a later horizon."""
    study = fixtures.create_study(api, chain.program_id, title="2027 Impact Fee Study Update")
    parks = fixtures.create_parks_component(
        api, study["id"], chain.parks_category_id, horizon_start_year=2031, horizon_end_year=2035
    )
    roads = fixtures.create_roads_component(
        api, study["id"], chain.roads_category_id, horizon_start_year=2031, horizon_end_year=2035
    )
    fixtures.allocate(api, parks["id"])
    fixtures.allocate(api, roads["id"])
    fixtures.add_schedule_line(api, parks["id"], K.PARKS_SINGLE_FAMILY_CONVERSION_FACTOR)
    fixtures.add_schedule_line(api, roads["id"], K.ROADS_SINGLE_FAMILY_CONVERSION_FACTOR)
    fixtures.certify(api, study["id"])
    return study


def _successor_study_ready_to_activate(api):
    chain = fixtures.effective_program(api)
    fixtures.assessed_application(api, chain)
    successor = _second_certified_study(api, chain)
    fixtures.set_clock(api, "2026-05-05T00:00:00Z")
    fixtures.publish_notice(api, successor["id"], notice_days=30)
    fixtures.set_clock(api, "2026-06-04T00:00:00Z")
    fixtures.close_protest_window(api, successor["id"])
    adopted = fixtures.adopt(api, successor["id"])
    check.assert_timestamp_equals(adopted["effective_at"], "2026-08-03T00:00:00Z", "effective_at")
    fixtures.set_clock(api, "2026-08-03T00:00:00Z")
    return chain, successor


def test_activation_supersedes_the_prior_study_and_flags_its_applications(api):
    """The program's prior study in status `EFFECTIVE`, of which there is at most
    one, moves `EFFECTIVE → SUPERSEDED` with its `superseded_by_fee_study_id`
    pointing at the activating study and its own `version` incremented;
    `SUPERSEDED` is terminal, and a superseded study's schedule remains readable so
    that assessments pinned to it stay auditable. Because that study became
    superseded, every development application whose `pinned_fee_study_id` names it,
    whose `assessment_status` is `ASSESSED` or `REASSESSED`, and whose
    `collection_status` is `NOT_DUE`, `DUE`, `DEFERRED` or `DELINQUENT` has
    `reassessment_required` set to true and its own `version` incremented — an
    application already `PAID` is left alone.

    Design: Difficulty/transitive_cascade/activation_supersedes_prior_study_and_flags_pinned_applications
    """
    chain, successor = _successor_study_ready_to_activate(api)

    activated = fixtures.activate(api, successor["id"])

    assert activated["status"] == K.STUDY_EFFECTIVE
    check.assert_timestamp_equals(
        activated["activated_at"], "2026-08-03T00:00:00Z", "activated_at"
    )
    retired = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    assert retired["status"] == K.STUDY_SUPERSEDED
    assert retired["superseded_by_fee_study_id"] == successor["id"]
    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    assert application["reassessment_required"] is True
    assert application["pinned_fee_study_id"] == chain.study_id
    check.assert_application_totals(application, net_due_cents=K.BASELINE_NET_DUE)


def test_a_flagged_application_may_not_be_collected(api):
    """Four state preconditions guard the payment: `assessment_status` must be
    `ASSESSED` or `REASSESSED`; `reassessment_required` must be false, or the payment
    is refused with `ERR_REASSESSMENT_REQUIRED` because the pinned schedule has been
    retired under the project's feet; `collection_status` must not already be `PAID`;
    and `collection_status` must not be `NOT_DUE` unless `collection_trigger` is
    `CERTIFICATE_OF_OCCUPANCY`, which is the one trigger under which a fee is paid
    straight out of `NOT_DUE`.

    Design: Difficulty/transitive_cascade/activation_supersedes_prior_study_and_flags_pinned_applications
    """
    chain, successor = _successor_study_ready_to_activate(api)
    fixtures.activate(api, successor["id"])

    response = api.create_payment(
        chain.application_id,
        {"amount_cents": K.BASELINE_NET_DUE, "payment_reference": "WIRE-19"},
        fixtures.PERMIT_OFFICER,
    )

    validate_error(response, err.ERR_REASSESSMENT_REQUIRED, 409)
    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    assert application["collection_status"] == K.COLLECTION_DUE
    check.assert_application_totals(application, paid_cents=0)
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(parks, fund_balance_cents=0)
