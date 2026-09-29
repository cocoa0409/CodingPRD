"""Operations whose legality is decided by the state of a neighbouring entity.

Signing a flawless deal is refused because the buyer record beside it is not
`QUALIFIED`; invoicing a calculated settlement period is refused because a risk
claim beside it is still undecided.  In both cases the blocked entity is itself
in perfect order, and the only variable in the experiment is the foreign state.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import validate_error  # noqa: E402

from test_helpers import assertions as asserts  # noqa: E402
from test_helpers import factories as f  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402
from test_helpers.api_errors import ApiErrorId  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    CREDIT_OFFICER_ID,
    DEAL_COMMITTEE,
    ORIGINATOR,
    SETTLEMENT_ANALYST,
)

# ---------------------------------------------------------------------------
# Instance: the signing gate reads the anchor buyer's qualification status, and
# reads it for exactly one value.
# ---------------------------------------------------------------------------

#: The two remediation items the credit officer attaches to a conditional
#: decision, which the revision loop later clears.
CONDITIONS = ["Quarterly covenant certificate", "Parent support letter"]

CONTRACT_PRICE = 22.75
CONTRACTED_MW = 25.000
EXPOSURE_USD = 1395030.00
UNSECURED_LIMIT_USD = 3000000.00
CREDIT_SCORE = 83.70
SUSTAINABILITY_SCORE = 100.00


def _terms_agreed_deal_behind_a_conditional_buyer(api):
    """A deal at `TERMS_AGREED` with credit `APPROVED` whose buyer is `CONDITIONAL`.

    Everything the signing gate checks about the deal itself passes: the slice is
    confirmed for the whole contracted capacity and the requirement is 0.00, so
    credit approves with nothing posted.  Only the buyer's own state is deficient.
    """
    node = fx.create_node(api)
    buyer = fx.create_conditional_offtaker(api, conditions=list(CONDITIONS))
    project = fx.create_project(api, node["id"],
                                cod_target_date="2029-06-01T00:00:00Z")
    deal = fx.create_deal(api, project["id"], buyer["id"], node["id"])
    deal_id = deal["id"]

    term_sheet = fx.table_round(api, deal_id)
    fx.confirmed_allocation(api, deal_id, buyer["id"], CONTRACTED_MW)
    fx.respond_accept(api, term_sheet["id"], buyer["id"])
    fx.submit_credit(api, deal_id)
    deal = fx.decide_credit(api, deal_id, "APPROVE")
    return {"node": node, "buyer": buyer, "project": project, "deal": deal}


def _assert_deal_is_otherwise_ready(deal):
    asserts.assert_money(deal["contract_price_usd_per_mwh"], CONTRACT_PRICE,
                         "contract_price_usd_per_mwh")
    asserts.assert_money(deal["exposure_usd"], EXPOSURE_USD, "exposure_usd")
    asserts.assert_money(deal["credit_support_required_usd"], 0.00,
                         "credit_support_required_usd")
    asserts.assert_mw(deal["confirmed_allocated_mw"], CONTRACTED_MW,
                      "confirmed_allocated_mw")
    assert deal["status"] == "TERMS_AGREED", deal
    assert deal["credit_status"] == "APPROVED", deal


def test_01_a_conditional_buyer_cannot_sign_a_deal_that_is_otherwise_perfect(api):
    """Every gate on the deal passes and the signature is still refused, leaving
    no condition-precedent rows behind.

    "The anchor buyer's `qualification_status` must be exactly `QUALIFIED` — a
    `CONDITIONAL` buyer may be structured, negotiated and even cleared through
    credit, but it may not sign, and the attempt is refused with
    `ERR_OFFTAKER_NOT_QUALIFIED`."

    Design: Difficulty/cross_entity_state_dependency/execute_blocked_by_conditional_then_under_review_anchor_offtaker
    """
    chain = _terms_agreed_deal_behind_a_conditional_buyer(api)
    deal_id = chain["deal"]["id"]

    buyer = fx.read_offtaker(api, chain["buyer"]["id"])
    assert buyer["qualification_status"] == "CONDITIONAL", buyer
    asserts.assert_score(buyer["credit_score"], CREDIT_SCORE, "credit_score")
    assert buyer["credit_tier"] == "PRIME", buyer
    asserts.assert_score(buyer["sustainability_score"], SUSTAINABILITY_SCORE,
                         "sustainability_score")
    asserts.assert_money(buyer["unsecured_credit_limit_usd"],
                         UNSECURED_LIMIT_USD, "unsecured_credit_limit_usd")
    assert buyer["conditions"] == CONDITIONS, buyer

    _assert_deal_is_otherwise_ready(chain["deal"])

    refused = api.execute_deal(deal_id, DEAL_COMMITTEE)
    validate_error(refused, ApiErrorId.ERR_OFFTAKER_NOT_QUALIFIED.value, 422)
    asserts.assert_error_envelope(refused)

    after = fx.read_deal(api, deal_id)
    assert after["status"] == "TERMS_AGREED", after
    assert after["cp_total_count"] == 0, after
    assert after["version"] == chain["deal"]["version"], after
    assert fx.conditions_of(api, deal_id) == [], "no rows may have been created"


def test_02_under_review_is_no_more_signable_than_conditional(api):
    """The revision loop clears the buyer's conditions and moves it out of
    `CONDITIONAL`, and the signature is refused with the very same error.

    "The same action is also the revision loop: a buyer sitting at `CONDITIONAL`
    after a conditional decision re-submits along `CONDITIONAL → UNDER_REVIEW`
    once it has remediated its conditions, and on that path the `conditions`
    array is cleared to empty **before** the scores are recomputed."

    "The anchor buyer's `qualification_status` must be exactly `QUALIFIED` — a
    `CONDITIONAL` buyer may be structured, negotiated and even cleared through
    credit, but it may not sign, and the attempt is refused with
    `ERR_OFFTAKER_NOT_QUALIFIED`."

    Design: Difficulty/cross_entity_state_dependency/execute_blocked_by_conditional_then_under_review_anchor_offtaker
    """
    chain = _terms_agreed_deal_behind_a_conditional_buyer(api)
    deal_id = chain["deal"]["id"]
    buyer_id = chain["buyer"]["id"]
    deal_before = fx.read_deal(api, deal_id)

    resubmitted = fx.submit_offtaker(api, buyer_id)
    assert resubmitted["qualification_status"] == "UNDER_REVIEW", resubmitted
    assert resubmitted["conditions"] == [], resubmitted
    # Re-scoring the same inputs reproduces the same numbers.
    asserts.assert_score(resubmitted["credit_score"], CREDIT_SCORE,
                         "credit_score")
    assert resubmitted["credit_tier"] == "PRIME", resubmitted

    # The buyer's own transition changed nothing on the deal.
    unchanged = fx.read_deal(api, deal_id)
    assert unchanged["version"] == deal_before["version"], unchanged
    assert unchanged["status"] == "TERMS_AGREED", unchanged

    refused = api.execute_deal(deal_id, DEAL_COMMITTEE)
    validate_error(refused, ApiErrorId.ERR_OFFTAKER_NOT_QUALIFIED.value, 422)

    after = fx.read_deal(api, deal_id)
    assert after["status"] == "TERMS_AGREED", after
    assert after["cp_total_count"] == 0, after
    assert fx.conditions_of(api, deal_id) == [], "still no rows"


def test_03_the_identical_request_signs_once_the_buyer_is_qualified(api):
    """Nothing about the deal changed between the refusal and the signature; the
    template that appears is the pre-development one.

    "A `PERMITTING` condition is included when the parent project's `status` is
    `PRE_DEVELOPMENT`; it is not waivable, and its `deadline_date` is the earlier
    of the deal's `commercial_operation_deadline` and 270 days after the logical
    clock."

    Design: Difficulty/cross_entity_state_dependency/execute_blocked_by_conditional_then_under_review_anchor_offtaker
    """
    chain = _terms_agreed_deal_behind_a_conditional_buyer(api)
    deal_id = chain["deal"]["id"]
    buyer_id = chain["buyer"]["id"]

    refused = api.execute_deal(deal_id, DEAL_COMMITTEE)
    validate_error(refused, ApiErrorId.ERR_OFFTAKER_NOT_QUALIFIED.value, 422)

    fx.submit_offtaker(api, buyer_id)
    qualified = fx.decide_offtaker(api, buyer_id, "QUALIFY")
    assert qualified["qualification_status"] == "QUALIFIED", qualified
    assert qualified["decision_by_user_id"] == CREDIT_OFFICER_ID, qualified

    signed = fx.execute_deal(api, deal_id)
    assert signed["status"] == "EXECUTED", signed
    assert signed["credit_status"] == "APPROVED", signed
    assert signed["cp_total_count"] == 3, signed
    asserts.assert_score(signed["cp_completion_pct"], 0.00, "cp_completion_pct")

    rows = fx.conditions_of(api, deal_id)
    assert len(rows) == 3, rows
    assert sorted(row["cp_type"] for row in rows) == [
        "INTERCONNECTION", "NOTICE_TO_PROCEED", "PERMITTING"], rows
    permitting = asserts.row_by(rows, "cp_type", "PERMITTING")
    asserts.assert_instant_equals(permitting["deadline_date"],
                                  fx.CP_PERMITTING_DEADLINE, "deadline_date")
    assert permitting["is_waivable"] is False, permitting
    interconnection = asserts.row_by(rows, "cp_type", "INTERCONNECTION")
    asserts.assert_instant_equals(interconnection["deadline_date"],
                                  fx.CP_INTERCONNECTION_DEADLINE,
                                  "deadline_date")
    notice = asserts.row_by(rows, "cp_type", "NOTICE_TO_PROCEED")
    asserts.assert_instant_equals(notice["deadline_date"],
                                  fx.CP_NOTICE_TO_PROCEED_DEADLINE,
                                  "deadline_date")
    assert notice["is_waivable"] is True, notice
    for row in rows:
        assert row["status"] == "PENDING", row
        asserts.assert_all_null(row, ["evidence_ref", "waiver_justification",
                                      "cure_deadline", "resolved_at",
                                      "resolved_by_user_id"])


# ---------------------------------------------------------------------------
# Instance: invoicing reads the deal's risk claims, and reads both their status
# and whether their window intersects this period.
# ---------------------------------------------------------------------------

INVOICE_PERIOD = ("2027-07-01T00:00:00Z", "2027-08-01T00:00:00Z")

#: Two uncurtailed hours, so no deemed volume can arise however a claim is
#: decided.
INVOICE_HOURS = [
    {"hour_start": "2027-07-01T00:00:00Z", "metered_mwh": 7.0000,
     "node_price_usd_per_mwh": 30.00, "hub_price_usd_per_mwh": 30.00},
    {"hour_start": "2027-07-01T01:00:00Z", "metered_mwh": 7.0000,
     "node_price_usd_per_mwh": 30.00, "hub_price_usd_per_mwh": 30.00},
]

TOTAL_METERED_MWH = 14.0000

#: Strictly inside the July period.
INSIDE_THE_PERIOD = ("2027-07-05T00:00:00Z", "2027-07-06T00:00:00Z")

#: Entirely after the July period, and never reviewed.
AFTER_THE_PERIOD = ("2027-09-05T00:00:00Z", "2027-09-06T00:00:00Z")

PERIOD_MONEY_FIELDS = [
    "total_metered_mwh",
    "total_deemed_mwh",
    "total_delivered_mwh",
    "weighted_avg_index_usd_per_mwh",
    "energy_settlement_usd",
    "basis_adjustment_usd",
    "net_settlement_usd",
    "seller_pays_usd",
    "buyer_pays_usd",
]


def _calculated_period_with_claims(api, inside: bool = True):
    """A `CALCULATED` July period, one live claim after it and optionally one in it."""
    chain = fx.calculated_period_chain(
        api, hours=INVOICE_HOURS, period_start=INVOICE_PERIOD[0],
        period_end=INVOICE_PERIOD[1],
        project_overrides={"name": "Kramer Junction Solar II",
                           "cod_target_date": "2026-07-01T00:00:00Z"})
    deal_id = chain["deal"]["id"]
    if inside:
        chain["curtailment"] = fx.file_risk_event(api, deal_id, "CURTAILMENT",
                                                  *INSIDE_THE_PERIOD)
    chain["force_majeure"] = fx.file_risk_event(api, deal_id, "FORCE_MAJEURE",
                                                *AFTER_THE_PERIOD)
    return chain


def _invoice(api, period_id):
    return api.advance_settlement_period(
        period_id, f.period_advance_payload("INVOICE"), SETTLEMENT_ANALYST)


def _money_of(period):
    return {field: period[field] for field in PERIOD_MONEY_FIELDS}


def test_04_an_undecided_claim_inside_the_window_blocks_the_invoice(api):
    """The period is calculated and complete, and the only obstacle is a claim
    filed over four days in the middle of it.

    "`INVOICE` requires `status` `CALCULATED` and moves the period `CALCULATED →
    INVOICED`, stamping `invoiced_at` with the logical clock; it is refused with
    `ERR_OPEN_RISK_CLAIM` while any risk claim of the deal whose `status` is
    `CLAIMED` has a window intersecting the period's half-open window from
    `period_start` up to but not including `period_end`."

    Design: Difficulty/cross_entity_state_dependency/invoice_blocked_by_claimed_risk_event_over_the_period_window
    """
    chain = _calculated_period_with_claims(api)
    period_id = chain["period"]["id"]

    before = fx.read_period(api, period_id)
    assert before["status"] == "CALCULATED", before
    assert before["invoiced_at"] is None, before
    assert before["interval_count"] == 2, before
    asserts.assert_mwh(before["total_metered_mwh"], TOTAL_METERED_MWH,
                       "total_metered_mwh")
    asserts.assert_mwh(before["total_deemed_mwh"], 0.0000, "total_deemed_mwh")
    assert chain["curtailment"]["status"] == "CLAIMED", chain["curtailment"]

    refused = _invoice(api, period_id)
    validate_error(refused, ApiErrorId.ERR_OPEN_RISK_CLAIM.value, 409)
    asserts.assert_error_envelope(refused)

    after = fx.read_period(api, period_id)
    assert after["status"] == "CALCULATED", after
    assert after["invoiced_at"] is None, after
    assert after["version"] == before["version"], after

    deal = fx.read_deal(api, chain["deal"]["id"])
    assert deal["status"] == "EFFECTIVE", deal
    assert deal["credit_status"] == "APPROVED", deal


def test_05_deciding_the_claim_clears_the_block_without_touching_the_money(api):
    """Rejecting the claim is enough — the row stays on the deal — and the
    identical invoice request then succeeds with every computed figure unmoved.

    "An unreviewed curtailment, change-in-law or force-majeure claim over the
    period must be decided first; a claim already `REJECTED` or `ACCEPTED` does
    not block invoicing."

    Design: Difficulty/cross_entity_state_dependency/invoice_blocked_by_claimed_risk_event_over_the_period_window
    """
    chain = _calculated_period_with_claims(api)
    period_id = chain["period"]["id"]

    blocked = _invoice(api, period_id)
    validate_error(blocked, ApiErrorId.ERR_OPEN_RISK_CLAIM.value, 409)
    before = fx.read_period(api, period_id)
    money_before = _money_of(before)

    rejected = fx.review_risk_event(api, chain["curtailment"]["id"], "REJECT")
    assert rejected["status"] == "REJECTED", rejected
    assert rejected["allocation_outcome"] is None, rejected
    assert rejected["excused_hours"] == 0, rejected

    # Reviewing the claim moved nothing on the period.
    unchanged = fx.read_period(api, period_id)
    assert unchanged["version"] == before["version"], unchanged
    assert _money_of(unchanged) == money_before, unchanged

    invoiced = fx.advance_period(api, period_id, "INVOICE")
    assert invoiced["status"] == "INVOICED", invoiced
    asserts.assert_instant_equals(invoiced["invoiced_at"], fx.INITIAL_CLOCK,
                                  "invoiced_at")
    assert _money_of(invoiced) == money_before, invoiced

    # The claim was decided, not deleted: it is still on the deal.
    rows, _ = fx.list_all(api.list_risk_events(chain["deal"]["id"], ORIGINATOR))
    assert len(rows) == 2, rows
    assert asserts.row_by_id(rows, chain["curtailment"]["id"])["status"] \
        == "REJECTED"


def test_06_a_claim_whose_window_misses_the_period_blocks_nothing(api):
    """A live September claim leaves the July invoice untouched, so window
    intersection is part of the predicate and not merely claim status.

    "`INVOICE` requires `status` `CALCULATED` and moves the period `CALCULATED →
    INVOICED`, stamping `invoiced_at` with the logical clock; it is refused with
    `ERR_OPEN_RISK_CLAIM` while any risk claim of the deal whose `status` is
    `CLAIMED` has a window intersecting the period's half-open window from
    `period_start` up to but not including `period_end`."

    Design: Difficulty/cross_entity_state_dependency/invoice_blocked_by_claimed_risk_event_over_the_period_window
    """
    chain = _calculated_period_with_claims(api, inside=False)
    period_id = chain["period"]["id"]

    assert chain["force_majeure"]["status"] == "CLAIMED", chain["force_majeure"]

    invoiced = fx.advance_period(api, period_id, "INVOICE")
    assert invoiced["status"] == "INVOICED", invoiced
    asserts.assert_instant_equals(invoiced["invoiced_at"], fx.INITIAL_CLOCK,
                                  "invoiced_at")

    # The unreviewed claim is untouched by the invoice it never blocked.
    rows, _ = fx.list_all(api.list_risk_events(chain["deal"]["id"], ORIGINATOR))
    assert len(rows) == 1, rows
    still_open = asserts.row_by_id(rows, chain["force_majeure"]["id"])
    assert still_open["status"] == "CLAIMED", still_open
    assert still_open["version"] == chain["force_majeure"]["version"]
