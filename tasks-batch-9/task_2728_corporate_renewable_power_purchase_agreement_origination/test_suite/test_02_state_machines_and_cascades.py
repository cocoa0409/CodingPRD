"""Cyclic lifecycles and the multi-hop cascades a single request sets off.

The negotiation machine revisits states it has already left, the conditions
machine forks three ways out of one state, and two very different triggers each
reach several entities deep without a second request.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import assertions as asserts  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    DEAL_COMMITTEE_ID,
    ORIGINATOR,
    ORIGINATOR_ID,
    ORIGINATOR_SECOND,
    ORIGINATOR_SECOND_ID,
)

# ---------------------------------------------------------------------------
# The redline loop: one agreement round-tripped through the negotiation cycle
# while its credit dimension sits at DECLINED.
# ---------------------------------------------------------------------------

CYCLE_TERMS = dict(
    product_type="VIRTUAL_CFD",
    contracted_mw=25.000,
    term_years=12,
    first_delivery_year=2027,
    commercial_operation_deadline="2027-12-31T00:00:00Z",
    settlement_frequency="HOURLY",
    base_fixed_price_usd_per_mwh=42.50,
    escalation_pct_per_year=2.0,
    shape_product="AS_GENERATED",
    basis_responsibility="SHARED",
)

DEVELOPER_TERMS = dict(
    proposed_escalation_pct_per_year=2.0,
    proposed_shape_product="AS_GENERATED",
    proposed_basis_responsibility="SHARED",
)


def _round_tripped_deal(api):
    """A TERMS_AGREED deal whose credit package has already been declined."""
    hub = fx.create_hub(api)
    node = fx.create_node(api)
    buyer = fx.create_qualified_offtaker(api)
    project = fx.create_project(api, node["id"],
                                cod_target_date="2027-06-01T00:00:00Z")
    deal = fx.create_deal(api, project["id"], buyer["id"], hub["id"],
                          **CYCLE_TERMS)
    deal_id = deal["id"]
    buyer_id = buyer["id"]

    round_a = fx.table_round(api, deal_id, response_deadline="2026-08-15T00:00:00Z",
                             proposed_fixed_price_usd_per_mwh=42.50,
                             **DEVELOPER_TERMS)
    round_b = fx.respond_counter(api, round_a["id"], buyer_id,
                                 counter_fixed_price_usd_per_mwh=41.00,
                                 counter_escalation_pct_per_year=2.0,
                                 counter_shape_product="AS_GENERATED",
                                 counter_basis_responsibility="SHARED")
    round_c = fx.table_round(api, deal_id, response_deadline="2026-08-20T00:00:00Z",
                             proposed_fixed_price_usd_per_mwh=42.50,
                             **DEVELOPER_TERMS)
    allocation = fx.confirmed_allocation(api, deal_id, buyer_id, 25.000)
    fx.respond_accept(api, round_c["id"], buyer_id)
    fx.submit_credit(api, deal_id)
    deal = fx.decide_credit(api, deal_id, "DECLINE")

    return {"deal": deal, "buyer": buyer, "project": project,
            "allocation": allocation, "round_a": round_a, "round_b": round_b,
            "round_c": round_c}


def test_01_the_status_loop_leaves_the_declined_credit_dimension_untouched(api):
    """Re-opening settled terms never re-opens the credit package.

    "`DECLINE` moves the deal `SUBMITTED → DECLINED`, sets
    `credit_approved_by_user_id` back to null, and leaves the commercial `status`
    untouched, which is exactly what makes the two dimensions independent."

    Design: Difficulty/non_linear_state_machine/deal_negotiation_cycle_with_independent_credit_dimension
    """
    state = _round_tripped_deal(api)
    deal_id = state["deal"]["id"]
    buyer_id = state["buyer"]["id"]

    assert state["deal"]["status"] == "TERMS_AGREED"
    assert state["deal"]["credit_status"] == "DECLINED"

    fx.table_round(api, deal_id, response_deadline="2026-08-25T00:00:00Z",
                   proposed_fixed_price_usd_per_mwh=43.10, **DEVELOPER_TERMS)

    mid_cycle = fx.read_deal(api, deal_id)
    assert mid_cycle["status"] == "UNDER_NEGOTIATION", mid_cycle
    assert mid_cycle["credit_status"] == "DECLINED", mid_cycle
    assert mid_cycle["contract_price_usd_per_mwh"] is None, mid_cycle
    assert mid_cycle["price_tier"] is None, mid_cycle

    round_e = fx.table_round(api, deal_id, response_deadline="2026-08-26T00:00:00Z",
                             proposed_fixed_price_usd_per_mwh=42.50,
                             **DEVELOPER_TERMS)
    fx.respond_accept(api, round_e["id"], buyer_id)
    fx.submit_credit(api, deal_id)
    final = fx.decide_credit(api, deal_id, "APPROVE")

    # The commercial machine has returned to a state it already held.
    assert final["status"] == "TERMS_AGREED", final
    assert final["credit_status"] == "APPROVED", final
    asserts.assert_money(final["contract_price_usd_per_mwh"], 44.10,
                         "contract_price_usd_per_mwh")
    assert final["price_tier"] == "MID", final


def test_02_re_tabling_from_under_negotiation_counters_the_still_open_round(api):
    """The redline sweep closes the outstanding round in the tabling party's name.

    "any round whose `status` is `OPEN` and whose `response_deadline` is at or
    after the logical clock moves `OPEN → COUNTERED` with
    `responded_by_user_id` set to the tabling operator."

    Design: Difficulty/non_linear_state_machine/deal_negotiation_cycle_with_independent_credit_dimension
    """
    state = _round_tripped_deal(api)
    deal_id = state["deal"]["id"]
    buyer_id = state["buyer"]["id"]

    round_d = fx.table_round(api, deal_id,
                             response_deadline="2026-08-25T00:00:00Z",
                             proposed_fixed_price_usd_per_mwh=43.10,
                             **DEVELOPER_TERMS)
    round_e = fx.table_round(api, deal_id,
                             response_deadline="2026-08-26T00:00:00Z",
                             proposed_fixed_price_usd_per_mwh=42.50,
                             **DEVELOPER_TERMS)
    fx.respond_accept(api, round_e["id"], buyer_id)
    fx.submit_credit(api, deal_id)
    deal = fx.decide_credit(api, deal_id, "APPROVE")

    assert deal["round_count"] == 5, deal

    rounds, _ = fx.list_all(api.list_rounds(deal_id, ORIGINATOR))
    by_id = {row["id"]: row for row in rounds}
    assert by_id[state["round_a"]["id"]]["status"] == "COUNTERED"
    assert by_id[state["round_b"]["id"]]["status"] == "COUNTERED"
    assert by_id[state["round_c"]["id"]]["status"] == "ACCEPTED"
    assert by_id[round_d["id"]]["status"] == "COUNTERED"
    assert by_id[round_d["id"]]["responded_by_user_id"] == ORIGINATOR_ID
    assert by_id[round_e["id"]]["status"] == "ACCEPTED"
    assert by_id[round_e["id"]]["responded_by_user_id"] == buyer_id

    # "the status loop never disturbed the allocation"
    allocations, _ = fx.list_all(api.list_allocations(deal_id, ORIGINATOR))
    slice_row = asserts.row_by_id(allocations, state["allocation"]["id"])
    assert slice_row["status"] == "CONFIRMED"
    asserts.assert_mw(deal["confirmed_allocated_mw"], 25.000,
                      "confirmed_allocated_mw")


# ---------------------------------------------------------------------------
# The conditions fork: one executed deal on a pre-development project, whose
# three conditions take three different routes out of PENDING.
# ---------------------------------------------------------------------------

FORK_TERMS = dict(
    product_type="VIRTUAL_CFD",
    contracted_mw=25.000,
    term_years=12,
    first_delivery_year=2027,
    commercial_operation_deadline="2029-12-31T00:00:00Z",
    settlement_frequency="HOURLY",
    base_fixed_price_usd_per_mwh=42.50,
    escalation_pct_per_year=2.0,
    shape_product="AS_GENERATED",
    basis_responsibility="SHARED",
)


def _executed_with_three_conditions(api):
    """An EXECUTED deal carrying PERMITTING, INTERCONNECTION and NOTICE_TO_PROCEED."""
    chain = fx.executed_chain_with_conditions(
        api, deal_overrides=dict(FORK_TERMS),
        project_overrides={"cod_target_date": "2029-06-01T00:00:00Z"})
    deal_id = chain["deal"]["id"]
    chain["permitting"] = fx.condition_by_type(api, deal_id, "PERMITTING")
    chain["interconnection"] = fx.condition_by_type(api, deal_id, "INTERCONNECTION")
    chain["notice_to_proceed"] = fx.condition_by_type(api, deal_id,
                                                     "NOTICE_TO_PROCEED")
    return chain


def test_03_a_failed_condition_recures_back_to_pending_with_a_fresh_deadline(api):
    """The cure loop returns the row to a state it had already left.

    "`RECURE` is the cure loop that makes this machine non-linear: it moves the
    condition `FAILED → PENDING`, requires that the deal's `status` is
    `EXECUTED` and that the logical clock is at or before the condition's
    `cure_deadline` — otherwise `ERR_CP_DEADLINE_PASSED` — clears both
    `cure_deadline` and `resolved_at` back to null, and pushes `deadline_date`
    out to 15 days after the logical clock."

    Design: Difficulty/non_linear_state_machine/condition_precedent_fail_recure_loop_then_three_way_fork
    """
    chain = _executed_with_three_conditions(api)
    deal_id = chain["deal"]["id"]

    assert chain["deal"]["cp_total_count"] == 3, chain["deal"]
    asserts.assert_score(chain["deal"]["cp_completion_pct"], 0.00,
                         "cp_completion_pct")
    asserts.assert_instant_equals(chain["permitting"]["deadline_date"],
                                 fx.CP_PERMITTING_DEADLINE, "deadline_date")
    asserts.assert_instant_equals(chain["interconnection"]["deadline_date"],
                                 fx.CP_INTERCONNECTION_DEADLINE, "deadline_date")
    asserts.assert_instant_equals(chain["notice_to_proceed"]["deadline_date"],
                                 fx.CP_NOTICE_TO_PROCEED_DEADLINE, "deadline_date")
    assert chain["permitting"]["is_waivable"] is False
    assert chain["interconnection"]["is_waivable"] is False
    assert chain["notice_to_proceed"]["is_waivable"] is True

    failed = fx.fail_condition(api, chain["permitting"]["id"],
                               headers=ORIGINATOR_SECOND)
    assert failed["status"] == "FAILED", failed
    assert failed["resolved_by_user_id"] == ORIGINATOR_SECOND_ID, failed
    asserts.assert_instant_equals(failed["cure_deadline"], fx.CP_CURE_DEADLINE,
                                 "cure_deadline")
    asserts.assert_score(fx.read_deal(api, deal_id)["cp_completion_pct"], 0.00,
                         "cp_completion_pct")

    recured = fx.recure_condition(api, chain["permitting"]["id"])
    assert recured["status"] == "PENDING", recured
    assert recured["cure_deadline"] is None, recured
    assert recured["resolved_at"] is None, recured
    asserts.assert_instant_equals(recured["deadline_date"], fx.CP_CURE_DEADLINE,
                                 "deadline_date")

    satisfied = fx.satisfy_condition(api, chain["permitting"]["id"],
                                     evidence_ref="CUP-2026-0091-REV2")
    assert satisfied["status"] == "SATISFIED", satisfied
    asserts.assert_score(fx.read_deal(api, deal_id)["cp_completion_pct"], 33.33,
                         "cp_completion_pct")


def test_04_only_the_waiver_fork_extends_the_commercial_operation_deadline(api):
    """Three forks reach 100.00, and just one of them moves the outside date.

    "`WAIVE` carries one side effect that `SATISFY` never applies: it extends
    the deal's `commercial_operation_deadline` by 30 days beyond its prior
    value."

    Design: Difficulty/non_linear_state_machine/condition_precedent_fail_recure_loop_then_three_way_fork
    """
    chain = _executed_with_three_conditions(api)
    deal_id = chain["deal"]["id"]

    fx.satisfy_condition(api, chain["permitting"]["id"],
                         evidence_ref="CUP-2026-0091-REV2")
    fx.satisfy_condition(api, chain["interconnection"]["id"],
                         evidence_ref="LGIA-CAISO-2026-114")

    two_of_three = fx.read_deal(api, deal_id)
    asserts.assert_score(two_of_three["cp_completion_pct"], 66.67,
                         "cp_completion_pct")
    assert two_of_three["status"] == "EXECUTED", two_of_three
    asserts.assert_instant_equals(two_of_three["commercial_operation_deadline"],
                                  fx.DEFAULT_COD,
                                  "commercial_operation_deadline")

    justification = ("Committee accepts EPC full-notice-to-proceed slippage of "
                     "one quarter")
    waived = fx.waive_condition(api, chain["notice_to_proceed"]["id"],
                               waiver_justification=justification)
    assert waived["status"] == "WAIVED", waived
    assert waived["waiver_justification"] == justification, waived
    assert waived["evidence_ref"] is None, waived

    effective = fx.read_deal(api, deal_id)
    asserts.assert_score(effective["cp_completion_pct"], 100.00,
                         "cp_completion_pct")
    assert effective["status"] == "EFFECTIVE", effective
    asserts.assert_instant_equals(effective["effective_at"], fx.INITIAL_CLOCK,
                                  "effective_at")
    asserts.assert_instant_equals(effective["commercial_operation_deadline"],
                                  fx.DEFAULT_COD_AFTER_ONE_WAIVER,
                                  "commercial_operation_deadline")


# ---------------------------------------------------------------------------
# The milestone cascade: one project advance, five hops, three entities.
# ---------------------------------------------------------------------------

CASCADE_TERMS = dict(
    product_type="VIRTUAL_CFD",
    contracted_mw=25.000,
    term_years=12,
    first_delivery_year=2027,
    commercial_operation_deadline="2029-12-31T00:00:00Z",
    settlement_frequency="HOURLY",
    base_fixed_price_usd_per_mwh=42.50,
    escalation_pct_per_year=2.0,
    shape_product="AS_GENERATED",
    basis_responsibility="SHARED",
)

NTP_EVIDENCE = "NTP-KJ1-2026-08"


def _cascade_ready_deal(api):
    """An EXECUTED deal whose only condition is the notice to proceed.

    The project is already `INTERCONNECTION_APPROVED` when the deal is written,
    so neither the permitting nor the interconnection row is ever templated, and
    a single posted development-security letter of credit sits behind the deal.
    """
    chain = fx.negotiated_chain(api, project_status="INTERCONNECTION_APPROVED",
                                deal_overrides=dict(CASCADE_TERMS))
    deal_id = chain["deal"]["id"]
    instrument = fx.register_letter_of_credit(
        api, deal_id, 500000.00, purpose="DEVELOPMENT_SECURITY",
        issuer_name="Pacific Coast Bank NA", issuer_rating="A",
        effective_date="2026-08-01T00:00:00Z",
        expiry_date="2027-12-31T00:00:00Z")
    chain["security"] = fx.post_instrument(api, deal_id, instrument["id"])
    chain["deal"] = fx.execute_deal(api, deal_id)
    chain["conditions"] = fx.conditions_of(api, deal_id)
    return chain


def _instrument_row(api, deal_id, instrument_id):
    rows, _ = fx.list_all(api.list_credit_support(deal_id, ORIGINATOR))
    return asserts.row_by_id(rows, instrument_id)


def test_05_one_milestone_advance_satisfies_the_condition_and_turns_the_deal_on(api):
    """Hops one through three: the project moves, the row closes, the deal starts.

    "Hop three, caused by hop two, recomputes each affected deal's
    `cp_completion_pct`; any deal whose recomputed figure reaches exactly 100.00
    moves `EXECUTED → EFFECTIVE` with `effective_at` stamped at the logical
    clock."

    Design: Difficulty/transitive_cascade/milestone_advance_five_hop_cascade_to_effective_and_security_release
    """
    chain = _cascade_ready_deal(api)
    deal_id = chain["deal"]["id"]
    project_id = chain["project"]["id"]

    # Only the notice-to-proceed row was ever templated.
    assert chain["deal"]["cp_total_count"] == 1, chain["deal"]
    assert [row["cp_type"] for row in chain["conditions"]] == \
        ["NOTICE_TO_PROCEED"], chain["conditions"]
    asserts.assert_score(chain["deal"]["cp_completion_pct"], 0.00,
                         "cp_completion_pct")
    asserts.assert_money(chain["deal"]["contract_price_usd_per_mwh"], 44.10,
                         "contract_price_usd_per_mwh")

    before = fx.read_project(api, project_id)
    project = fx.advance_milestone(api, project_id, "NOTICE_TO_PROCEED",
                                   NTP_EVIDENCE)

    # Hop one.
    assert project["status"] == "NTP_ISSUED", project
    asserts.assert_instant_equals(project["last_milestone_at"], fx.INITIAL_CLOCK,
                                  "last_milestone_at")
    asserts.assert_version_advanced_by(before["version"], project["version"], 1,
                                       "project version")

    # Hop two.
    condition = fx.condition_by_type(api, deal_id, "NOTICE_TO_PROCEED")
    assert condition["status"] == "SATISFIED", condition
    assert condition["evidence_ref"] == NTP_EVIDENCE, condition
    asserts.assert_instant_equals(condition["resolved_at"], fx.INITIAL_CLOCK,
                                  "resolved_at")

    # Hop three.
    deal = fx.read_deal(api, deal_id)
    asserts.assert_score(deal["cp_completion_pct"], 100.00, "cp_completion_pct")
    assert deal["status"] == "EFFECTIVE", deal
    asserts.assert_instant_equals(deal["effective_at"], fx.INITIAL_CLOCK,
                                  "effective_at")
    assert deal["cp_total_count"] == 1, deal


def test_06_becoming_effective_releases_the_development_security_unasked(api):
    """Hops four and five: collateral closes itself and the totals move with it.

    "Hop four, caused by hop three, takes every newly effective deal and moves
    each of its credit-support instruments whose `purpose` is
    `DEVELOPMENT_SECURITY` and whose `status` is `POSTED` from `POSTED →
    RELEASED`, stamping `closed_at`."

    Design: Difficulty/transitive_cascade/milestone_advance_five_hop_cascade_to_effective_and_security_release
    """
    chain = _cascade_ready_deal(api)
    deal_id = chain["deal"]["id"]

    assert chain["security"]["status"] == "POSTED", chain["security"]
    asserts.assert_money(chain["deal"]["posted_credit_support_usd"], 500000.00,
                         "posted_credit_support_usd")
    asserts.assert_money(chain["deal"]["released_credit_support_usd"], 0.00,
                         "released_credit_support_usd")

    fx.advance_milestone(api, chain["project"]["id"], "NOTICE_TO_PROCEED",
                         NTP_EVIDENCE)

    # Hop four: nobody ever called the release endpoint.
    instrument = _instrument_row(api, deal_id, chain["security"]["id"])
    assert instrument["status"] == "RELEASED", instrument
    asserts.assert_instant_equals(instrument["closed_at"], fx.INITIAL_CLOCK,
                                  "closed_at")
    # An A-rated letter of credit is undiscounted, and the release leaves the
    # sizing of the instrument itself untouched.
    asserts.assert_money(instrument["haircut_pct"], 0.00, "haircut_pct")
    asserts.assert_money(instrument["eligible_credit_usd"], 500000.00,
                         "eligible_credit_usd")

    # Hop five.
    deal = fx.read_deal(api, deal_id)
    asserts.assert_money(deal["posted_credit_support_usd"], 0.00,
                         "posted_credit_support_usd")
    asserts.assert_money(deal["released_credit_support_usd"], 500000.00,
                         "released_credit_support_usd")
    asserts.assert_money(deal["drawn_credit_support_usd"], 0.00,
                         "drawn_credit_support_usd")
    # The requirement was 0.00 all along, so the release breaches no coverage.
    asserts.assert_money(deal["credit_support_required_usd"], 0.00,
                         "credit_support_required_usd")


# ---------------------------------------------------------------------------
# The change-in-law cascade: one committee decision reprices the deal and
# knocks its credit standing over, while a force-majeure decision does neither.
# ---------------------------------------------------------------------------

CIL_TERMS = dict(
    product_type="VIRTUAL_CFD",
    contracted_mw=50.000,
    term_years=12,
    first_delivery_year=2026,
    commercial_operation_deadline="2027-12-31T00:00:00Z",
    settlement_frequency="HOURLY",
    base_fixed_price_usd_per_mwh=22.00,
    escalation_pct_per_year=0.0,
    shape_product="AS_GENERATED",
    basis_responsibility="SHARED",
)

CIL_WINDOW = ("2027-01-01T00:00:00Z", "2027-03-31T00:00:00Z")
FM_WINDOW = ("2027-05-01T00:00:00Z", "2027-05-10T00:00:00Z")


def _effective_deal_with_two_claims(api):
    """An EFFECTIVE, APPROVED, uncollateralised deal carrying two open claims."""
    chain = fx.chain_c(
        api, deal_overrides=dict(CIL_TERMS),
        project_overrides={"name": "Kramer Junction Solar II"})
    deal_id = chain["deal"]["id"]
    chain["change_in_law"] = fx.file_risk_event(
        api, deal_id, "CHANGE_IN_LAW", CIL_WINDOW[0], CIL_WINDOW[1],
        claimed_by="DEVELOPER",
        description="State PTC repeal raises delivered cost")
    chain["force_majeure"] = fx.file_risk_event(
        api, deal_id, "FORCE_MAJEURE", FM_WINDOW[0], FM_WINDOW[1],
        claimed_by="DEVELOPER", description="Wildfire smoke derate")
    return chain


def test_07_accepting_a_change_in_law_reprices_the_deal_into_a_shortfall(api):
    """One committee decision reaches the price, the requirement and the standing.

    "Hop three, caused by hop two, catches the coverage consequence: a deal whose
    `credit_status` is `APPROVED` and whose `posted_credit_support_usd` now falls
    below the recomputed `credit_support_required_usd` moves `APPROVED →
    SUPPORT_SHORTFALL` with `support_cure_deadline` set to ten days after the
    logical clock."

    Design: Difficulty/transitive_cascade/change_in_law_acceptance_three_hop_cascade_to_support_shortfall
    """
    chain = _effective_deal_with_two_claims(api)
    deal_id = chain["deal"]["id"]

    assert chain["deal"]["status"] == "EFFECTIVE", chain["deal"]
    assert chain["deal"]["credit_status"] == "APPROVED", chain["deal"]
    asserts.assert_money(chain["deal"]["contract_price_usd_per_mwh"], 22.75,
                         "contract_price_usd_per_mwh")
    asserts.assert_mwh(chain["deal"]["expected_annual_mwh"], 122640.00,
                       "expected_annual_mwh", places=2)
    asserts.assert_money(chain["deal"]["exposure_usd"], 2790060.00,
                         "exposure_usd")
    asserts.assert_money(chain["deal"]["credit_support_required_usd"], 0.00,
                         "credit_support_required_usd")
    asserts.assert_money(chain["deal"]["posted_credit_support_usd"], 0.00,
                         "posted_credit_support_usd")

    # Hop one: the claim is stored, stamped and sized.
    claim = fx.review_risk_event(api, chain["change_in_law"]["id"], "ACCEPT",
                                 allocation_outcome="BUYER_BEARS",
                                 price_adjustment_usd_per_mwh=4.00)
    assert claim["status"] == "ACCEPTED", claim
    assert claim["allocation_outcome"] == "BUYER_BEARS", claim
    asserts.assert_money(claim["price_adjustment_usd_per_mwh"], 4.00,
                         "price_adjustment_usd_per_mwh")
    assert claim["reviewed_by_user_id"] == DEAL_COMMITTEE_ID, claim
    asserts.assert_instant_equals(claim["reviewed_at"], fx.INITIAL_CLOCK,
                                  "reviewed_at")
    # 2027-01-01 to 2027-03-31 is 89 elapsed days counted inclusively of both
    # endpoints, and no metered hour of this deal falls inside the window.
    assert claim["duration_days"] == 90, claim
    assert claim["excused_hours"] == 0, claim

    deal = fx.read_deal(api, deal_id)

    # Hop two: 22.75 + 4.00, and the requirement re-sized off 122,640.00 MWh.
    asserts.assert_money(deal["contract_price_usd_per_mwh"], 26.75,
                         "contract_price_usd_per_mwh")
    asserts.assert_money(deal["exposure_usd"], 3280620.00, "exposure_usd")
    asserts.assert_money(deal["credit_support_required_usd"], 500000.00,
                         "credit_support_required_usd")

    # Hop three: nothing is posted, so the coverage test fails.
    assert deal["credit_status"] == "SUPPORT_SHORTFALL", deal
    asserts.assert_instant_equals(deal["support_cure_deadline"],
                                  fx.SUPPORT_CURE_DEADLINE,
                                  "support_cure_deadline")
    asserts.assert_money(deal["posted_credit_support_usd"], 0.00,
                         "posted_credit_support_usd")
    # The commercial dimension is untouched by any of the three hops.
    assert deal["status"] == "EFFECTIVE", deal


def test_08_rejecting_a_claim_starts_no_hop_at_all(api):
    """The cascade head is acceptance, and only on the change-in-law path.

    "Hop two fires only on the `CHANGE_IN_LAW` path: the deal's
    `contract_price_usd_per_mwh` becomes its prior value plus
    `price_adjustment_usd_per_mwh`, rounded half up to two decimal places, after
    which `exposure_usd` and `credit_support_required_usd` are re-sized by the
    three-step requirement calculation."

    Design: Difficulty/transitive_cascade/change_in_law_acceptance_three_hop_cascade_to_support_shortfall
    """
    chain = _effective_deal_with_two_claims(api)
    deal_id = chain["deal"]["id"]
    before = fx.read_deal(api, deal_id)

    rejected = fx.review_risk_event(api, chain["force_majeure"]["id"], "REJECT")
    assert rejected["status"] == "REJECTED", rejected
    assert rejected["allocation_outcome"] is None, rejected
    assert rejected["price_adjustment_usd_per_mwh"] is None, rejected
    assert rejected["reviewed_by_user_id"] == DEAL_COMMITTEE_ID, rejected

    after = fx.read_deal(api, deal_id)
    asserts.assert_money(after["contract_price_usd_per_mwh"], 22.75,
                         "contract_price_usd_per_mwh")
    asserts.assert_money(after["exposure_usd"], 2790060.00, "exposure_usd")
    asserts.assert_money(after["credit_support_required_usd"], 0.00,
                         "credit_support_required_usd")
    assert after["credit_status"] == "APPROVED", after
    assert after["support_cure_deadline"] is None, after
    assert after["status"] == "EFFECTIVE", after
    assert after["version"] == before["version"], after

    # The still-open change-in-law claim was not swept up by the rejection.
    events, _ = fx.list_all(api.list_risk_events(deal_id, ORIGINATOR))
    open_claim = asserts.row_by_id(events, chain["change_in_law"]["id"])
    assert open_claim["status"] == "CLAIMED", open_claim
