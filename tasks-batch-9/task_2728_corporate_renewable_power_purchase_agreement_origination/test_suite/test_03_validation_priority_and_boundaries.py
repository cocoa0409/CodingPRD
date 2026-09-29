"""Which rule speaks first, and what happens exactly on a threshold.

Two requests each violate two rules at once and the ladder decides the answer;
two metrics are probed on both sides of a boundary, one of them the vacuous
zero-of-zero percentage.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    get_success_data,
    validate_error,
)

from test_helpers import assertions as asserts  # noqa: E402
from test_helpers import factories as f  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402
from test_helpers.api_errors import ApiErrorId  # noqa: E402
from test_helpers.test_users import CREDIT_OFFICER, ORIGINATOR  # noqa: E402

# ---------------------------------------------------------------------------
# Instance: the auth gate at priority 2 against the concurrency gate at
# priority 9, both violated by one request body.
# ---------------------------------------------------------------------------

STALE_TERMS = dict(
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

DEVELOPER_TERMS = dict(
    proposed_escalation_pct_per_year=2.0,
    proposed_shape_product="AS_GENERATED",
    proposed_basis_responsibility="SHARED",
)


def _approved_deal_with_a_stale_token(api):
    """An APPROVED deal, a registered-but-unposted letter of credit, a stale token.

    The token is read after the instrument is registered — registration moves no
    version — and the deal's version is then advanced twice, by the credit
    submission and by the credit decision, so the captured token is two behind.
    """
    chain = fx.origination_chain(
        api, deal_overrides=dict(STALE_TERMS),
        project_overrides={"cod_target_date": "2029-06-01T00:00:00Z"})
    deal_id = chain["deal"]["id"]
    buyer_id = chain["buyer"]["id"]

    term_sheet = fx.table_round(
        api, deal_id, response_deadline="2026-08-15T00:00:00Z",
        proposed_fixed_price_usd_per_mwh=42.50, **DEVELOPER_TERMS)
    fx.confirmed_allocation(api, deal_id, buyer_id, 25.000)
    fx.respond_accept(api, term_sheet["id"], buyer_id)

    chain["instrument"] = fx.register_letter_of_credit(
        api, deal_id, 500000.00, purpose="PERFORMANCE_SECURITY",
        issuer_name="Pacific Coast Bank NA", issuer_rating="A",
        effective_date="2026-08-01T00:00:00Z",
        expiry_date="2027-12-31T00:00:00Z")
    chain["stale_version"] = fx.deal_version(api, deal_id)

    fx.submit_credit(api, deal_id)
    chain["deal"] = fx.decide_credit(api, deal_id, "APPROVE")
    return chain


def _instrument_row(api, deal_id, instrument_id):
    rows, _ = fx.list_all(api.list_credit_support(deal_id, ORIGINATOR))
    return asserts.row_by_id(rows, instrument_id)


def test_01_the_wrong_role_is_refused_before_the_stale_token_is_even_read(api):
    """Priority 2 answers 403 although the body is genuinely two versions behind.

    "Once the headers are present, the role named in `X-User-Role` must appear
    among the roles the target endpoint authorizes; if it does not, the request is
    refused with `ERR_ROLE_NOT_PERMITTED`, and this refusal precedes request-shape
    parsing, so a wrong-role request carrying a malformed body still returns 403
    rather than 400."

    Design: Difficulty/priority_pair_validation_conflict/role_gate_beats_stale_version_returns_403_not_412
    """
    chain = _approved_deal_with_a_stale_token(api)
    deal_id = chain["deal"]["id"]
    instrument_id = chain["instrument"]["id"]
    live_version = fx.deal_version(api, deal_id)

    # The token really is two behind: the ladder has something to preempt.
    assert live_version == chain["stale_version"] + 2, live_version

    refused = api.post_credit_support(
        instrument_id,
        f.post_credit_support_payload(chain["stale_version"]), ORIGINATOR)
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    asserts.assert_error_envelope(refused)

    # Nothing about the rejected request touched the instrument or the deal.
    instrument = _instrument_row(api, deal_id, instrument_id)
    assert instrument["status"] == "PROPOSED", instrument
    asserts.assert_all_null(instrument,
                            ["haircut_pct", "eligible_credit_usd", "posted_at",
                             "closed_at"])
    assert fx.deal_version(api, deal_id) == live_version


def test_02_the_same_body_from_the_right_role_proves_the_staleness_was_real(api):
    """Priority 9 answers 412 on the identical payload, and a fresh token posts.

    "Posting a registered credit-support instrument likewise requires
    `expected_deal_version` matching the parent deal's current `version`."

    Design: Difficulty/priority_pair_validation_conflict/role_gate_beats_stale_version_returns_403_not_412
    """
    chain = _approved_deal_with_a_stale_token(api)
    deal_id = chain["deal"]["id"]
    instrument_id = chain["instrument"]["id"]
    live_version = fx.deal_version(api, deal_id)

    stale = api.post_credit_support(
        instrument_id,
        f.post_credit_support_payload(chain["stale_version"]), CREDIT_OFFICER)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    instrument = _instrument_row(api, deal_id, instrument_id)
    assert instrument["status"] == "PROPOSED", instrument
    assert fx.deal_version(api, deal_id) == live_version

    fresh = api.post_credit_support(
        instrument_id, f.post_credit_support_payload(live_version),
        CREDIT_OFFICER)
    posted = get_success_data(fresh, 200)
    assert posted["status"] == "POSTED", posted
    # An A-rated issuer is undiscounted, so the whole face amount is eligible.
    asserts.assert_money(posted["haircut_pct"], 0.00, "haircut_pct")
    asserts.assert_money(posted["eligible_credit_usd"], 500000.00,
                         "eligible_credit_usd")
    asserts.assert_instant_equals(posted["posted_at"], fx.INITIAL_CLOCK,
                                  "posted_at")
    asserts.assert_money(fx.read_deal(api, deal_id)["posted_credit_support_usd"],
                         500000.00, "posted_credit_support_usd")


# ---------------------------------------------------------------------------
# Instance: window well-formedness at priority 17 against the risk-claim
# collision at priority 22, with no auth or concurrency rule in play.
# ---------------------------------------------------------------------------

CLAIM_TERMS = dict(
    product_type="VIRTUAL_CFD",
    contracted_mw=25.000,
    term_years=12,
    first_delivery_year=2026,
    commercial_operation_deadline="2027-12-31T00:00:00Z",
    settlement_frequency="HOURLY",
    base_fixed_price_usd_per_mwh=22.00,
    escalation_pct_per_year=0.0,
    shape_product="AS_GENERATED",
    basis_responsibility="SHARED",
)

EXISTING_WINDOW = ("2027-07-10T00:00:00Z", "2027-07-20T00:00:00Z")
INVERTED_WINDOW = ("2027-07-18T00:00:00Z", "2027-07-12T00:00:00Z")
DISJOINT_WINDOW = ("2027-09-01T00:00:00Z", "2027-09-10T00:00:00Z")


def _effective_deal_with_a_curtailment_claim(api):
    """An EFFECTIVE deal already carrying one CLAIMED curtailment window."""
    chain = fx.chain_c(
        api, deal_overrides=dict(CLAIM_TERMS),
        project_overrides={"name": "Kramer Junction Solar II",
                           "cod_target_date": "2026-07-01T00:00:00Z"})
    chain["existing"] = fx.file_risk_event(
        api, chain["deal"]["id"], "CURTAILMENT", EXISTING_WINDOW[0],
        EXISTING_WINDOW[1], claimed_by="DEVELOPER",
        description="Economic curtailment at the node")
    return chain


def _file_claim(api, deal_id, window_start, window_end, description):
    return api.create_risk_event(
        deal_id,
        f.risk_event_payload("CURTAILMENT", window_start, window_end,
                             claimed_by="DEVELOPER", description=description),
        ORIGINATOR)


def test_03_an_inverted_window_is_malformed_before_it_can_be_an_overlap(api):
    """Priority 17 answers 422, not the 409 a collision-first reading would give.

    "Well-formedness is checked before any collision check, so a backwards window
    that would also overlap an existing claim returns `ERR_INVALID_WINDOW`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_window_precedes_risk_window_overlap_on_risk_event_claim
    """
    chain = _effective_deal_with_a_curtailment_claim(api)
    deal_id = chain["deal"]["id"]
    assert chain["deal"]["status"] == "EFFECTIVE", chain["deal"]

    refused = _file_claim(api, deal_id, INVERTED_WINDOW[0], INVERTED_WINDOW[1],
                          "Inverted window that also straddles the existing claim")
    validate_error(refused, ApiErrorId.ERR_INVALID_WINDOW.value, 422)
    asserts.assert_error_envelope(refused)

    # The rejected request created nothing and disturbed nothing.
    events, meta = fx.list_all(api.list_risk_events(deal_id, ORIGINATOR))
    assert meta["total_count"] == 1, meta
    untouched = asserts.row_by_id(events, chain["existing"]["id"])
    assert untouched["version"] == chain["existing"]["version"], untouched
    asserts.assert_instant_equals(untouched["window_start"], EXISTING_WINDOW[0],
                                  "window_start")
    asserts.assert_instant_equals(untouched["window_end"], EXISTING_WINDOW[1],
                                  "window_end")


def test_04_the_same_two_instants_in_order_do_collide_with_the_open_claim(api):
    """Priority 22 answers 409 once the window is well formed, and a disjoint one files.

    "It must then not collide with any existing claim of the same deal carrying
    the same `event_type` whose `status` is `CLAIMED` or `ACCEPTED`, or the claim
    is refused with `ERR_RISK_WINDOW_OVERLAP`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_window_precedes_risk_window_overlap_on_risk_event_claim
    """
    chain = _effective_deal_with_a_curtailment_claim(api)
    deal_id = chain["deal"]["id"]
    deal_version_before = fx.deal_version(api, deal_id)

    collided = _file_claim(api, deal_id, INVERTED_WINDOW[1], INVERTED_WINDOW[0],
                           "Same two dates, correct order")
    validate_error(collided, ApiErrorId.ERR_RISK_WINDOW_OVERLAP.value, 409)

    filed = _file_claim(api, deal_id, DISJOINT_WINDOW[0], DISJOINT_WINDOW[1],
                        "Disjoint window")
    claim = get_success_data(filed, 201)
    assert claim["status"] == "CLAIMED", claim
    assert claim["duration_days"] is None, claim
    assert claim["excused_hours"] == 0, claim
    asserts.assert_all_null(claim, ["allocation_outcome",
                                    "price_adjustment_usd_per_mwh",
                                    "reviewed_by_user_id", "reviewed_at"])

    events, meta = fx.list_all(api.list_risk_events(deal_id, ORIGINATOR))
    assert meta["total_count"] == 2, meta
    assert sorted(asserts.ids_of(events)) == \
        sorted([chain["existing"]["id"], claim["id"]]), events
    assert fx.read_deal(api, deal_id)["version"] == deal_version_before


# ---------------------------------------------------------------------------
# Instance: the credit score exactly on the inclusive STANDARD threshold, probed
# from both sides by one hundredth of a leverage point.
# ---------------------------------------------------------------------------

MERIDIAN_PROFILE = dict(
    credit_rating="B",
    rating_agency="MOODYS",
    reported_ebitda_usd=40000000.00,
    disclosure_framework="CDP_AND_TCFD",
    has_science_based_target=True,
    re100_member=False,
    scope2_target_year=2035,
)

SCORE_FIELDS = ["credit_score", "credit_score_variant", "credit_tier",
                "sustainability_score", "unsecured_credit_limit_usd"]


def _threshold_twins(api):
    """Two buyers identical but for a hundredth of a turn of leverage."""
    on = fx.create_offtaker(api, legal_name="Meridian Foods Group Inc",
                            net_debt_to_ebitda=1.3, **MERIDIAN_PROFILE)
    off = fx.create_offtaker(api, legal_name="Meridian Foods Holdings Inc",
                             net_debt_to_ebitda=1.31, **MERIDIAN_PROFILE)
    return on, off


def test_05_a_score_of_exactly_sixty_two_is_standard_not_subprime(api):
    """The tier comparison at the STANDARD floor is inclusive.

    "Every comparison is inclusive at the lower bound, and it is performed on the
    two-decimal `credit_score` with no further rounding — a score of exactly 62.00
    is `STANDARD` and 61.99 is `SUBPRIME`."

    Design: Difficulty/boundary_precision_check/credit_tier_at_exact_standard_threshold_62_00
    """
    on, _off = _threshold_twins(api)

    # "no scoring runs at creation"
    asserts.assert_all_null(on, SCORE_FIELDS)

    scored = fx.submit_offtaker(api, on["id"])
    assert scored["qualification_status"] == "UNDER_REVIEW", scored
    # 0.55 x 38 + 0.30 x (100 - 10 x 1.3) + 0.15 x 100 = 20.90 + 26.10 + 15.00.
    asserts.assert_score(scored["credit_score"], 62.00, "credit_score")
    assert scored["credit_tier"] == "STANDARD", scored
    assert scored["credit_score_variant"] == "STANDALONE", scored
    # PTS_SBT 40 plus the 10 for disclosing at all; 2035 is beyond 2030 and the
    # buyer is not an RE100 member.
    asserts.assert_score(scored["sustainability_score"], 50.00,
                         "sustainability_score")
    # min of the 10,000,000.00 STANDARD cap and two percent of 40,000,000.00.
    asserts.assert_money(scored["unsecured_credit_limit_usd"], 800000.00,
                         "unsecured_credit_limit_usd")


def test_06_one_hundredth_of_a_leverage_turn_costs_six_hundred_thousand(api):
    """61.97 falls to SUBPRIME, and the limit cliff proves two-decimal scoring.

    "`unsecured_credit_limit_usd` is whichever of the two is smaller, and a
    `DECLINED` buyer therefore lands on 0.00 by both limbs."

    Design: Difficulty/boundary_precision_check/credit_tier_at_exact_standard_threshold_62_00
    """
    on, off = _threshold_twins(api)
    asserts.assert_all_null(off, SCORE_FIELDS)

    on_scored = fx.submit_offtaker(api, on["id"])
    off_scored = fx.submit_offtaker(api, off["id"])

    # 0.30 x 86.9 = 26.07, so the score lands three hundredths below the floor.
    asserts.assert_score(off_scored["credit_score"], 61.97, "credit_score")
    assert off_scored["credit_tier"] == "SUBPRIME", off_scored
    assert off_scored["credit_score_variant"] == "STANDALONE", off_scored
    asserts.assert_score(off_scored["sustainability_score"], 50.00,
                         "sustainability_score")
    # min of the 2,000,000.00 SUBPRIME cap and half a percent of 40,000,000.00.
    asserts.assert_money(off_scored["unsecured_credit_limit_usd"], 200000.00,
                         "unsecured_credit_limit_usd")

    # A three-hundredth move in the score moves the limit by 600,000.00, which is
    # only observable because the score is carried at two decimals.
    assert round(on_scored["credit_score"] - off_scored["credit_score"], 2) == 0.03
    assert on_scored["credit_tier"] != off_scored["credit_tier"]
    assert round(on_scored["unsecured_credit_limit_usd"]
                 - off_scored["unsecured_credit_limit_usd"], 2) == 600000.00


# ---------------------------------------------------------------------------
# Instance: the completion percentage over a set that may be empty, probed at
# the vacuous zero-of-zero boundary against a one-element template.
# ---------------------------------------------------------------------------

TWIN_TERMS = dict(
    product_type="VIRTUAL_CFD",
    contracted_mw=25.000,
    term_years=12,
    first_delivery_year=2026,
    commercial_operation_deadline="2029-12-31T00:00:00Z",
    settlement_frequency="HOURLY",
    base_fixed_price_usd_per_mwh=22.00,
    escalation_pct_per_year=0.0,
    shape_product="AS_GENERATED",
    basis_responsibility="SHARED",
)


def _approved_deal_on(api, project_id, buyer_id, settlement_point_id):
    """A TERMS_AGREED deal with credit APPROVED, ready to be signed."""
    deal = fx.create_deal(api, project_id, buyer_id, settlement_point_id,
                          **TWIN_TERMS)
    term_sheet = fx.table_round(api, deal["id"])
    fx.confirmed_allocation(api, deal["id"], buyer_id, 25.000)
    fx.respond_accept(api, term_sheet["id"], buyer_id)
    fx.submit_credit(api, deal["id"])
    return fx.decide_credit(api, deal["id"], "APPROVE")


def _twin_deals(api):
    """Two identical deals whose projects differ only in development status."""
    hub = fx.create_hub(api)
    node_a = fx.create_node(api, name="KRAMER JUNCTION 1N")
    node_b = fx.create_node(api, name="KRAMER JUNCTION 2N")
    buyer = fx.create_qualified_offtaker(api)

    project_a = fx.create_project(api, node_a["id"],
                                  name="Kramer Junction Solar A",
                                  cod_target_date="2026-07-01T00:00:00Z")
    fx.advance_project_to(api, project_a["id"], "OPERATIONAL")
    project_b = fx.create_project(api, node_b["id"],
                                  name="Kramer Junction Solar B",
                                  cod_target_date="2027-07-01T00:00:00Z")
    fx.advance_project_to(api, project_b["id"], "NTP_ISSUED")

    return {
        "buyer": buyer,
        "deal_a": _approved_deal_on(api, project_a["id"], buyer["id"], hub["id"]),
        "deal_b": _approved_deal_on(api, project_b["id"], buyer["id"], hub["id"]),
    }


def test_07_an_empty_condition_template_reads_a_vacuous_one_hundred(api):
    """Zero of zero is complete, and the deal turns on inside the same request.

    "When `cp_total_count` is zero the figure is 100.00 by vacuous truth. That is
    the case that matters most: an already-`OPERATIONAL` project whose anchor
    buyer already holds a registry account produces the empty template, so
    `cp_total_count` is 0, `cp_completion_pct` is 100.00, and the deal moves
    `TERMS_AGREED → EXECUTED → EFFECTIVE` inside the very same request, stamping
    `effective_at` and releasing every `POSTED` instrument whose `purpose` is
    `DEVELOPMENT_SECURITY`."

    Design: Difficulty/boundary_precision_check/cp_completion_pct_vacuous_100_00_on_empty_template
    """
    twins = _twin_deals(api)
    deal_a = twins["deal_a"]
    asserts.assert_money(deal_a["contract_price_usd_per_mwh"], 22.75,
                         "contract_price_usd_per_mwh")
    asserts.assert_money(deal_a["exposure_usd"], 1395030.00, "exposure_usd")
    asserts.assert_money(deal_a["credit_support_required_usd"], 0.00,
                         "credit_support_required_usd")

    signed = fx.execute_deal(api, deal_a["id"])

    assert signed["cp_total_count"] == 0, signed
    asserts.assert_score(signed["cp_completion_pct"], 100.00, "cp_completion_pct")
    assert signed["status"] == "EFFECTIVE", signed
    asserts.assert_instant_equals(signed["effective_at"], fx.INITIAL_CLOCK,
                                  "effective_at")
    # Nothing was waived, so the outside date did not move.
    asserts.assert_instant_equals(signed["commercial_operation_deadline"],
                                  fx.DEFAULT_COD,
                                  "commercial_operation_deadline")
    assert fx.conditions_of(api, deal_a["id"]) == [], "the template is empty"


def test_08_a_one_element_template_reads_a_flat_zero_and_stops_at_executed(api):
    """The same arithmetic over one pending row is 0.00, and a waiver closes it.

    "Execution then sets `cp_total_count` to the number of rows included and
    computes `cp_completion_pct`, which is one hundred multiplied by the count of
    the deal's conditions whose `status` is `SATISFIED` or `WAIVED`, divided by
    `cp_total_count`, rounded half up to two decimal places; both `FAILED` and
    `PENDING` count as not cleared."

    Design: Difficulty/boundary_precision_check/cp_completion_pct_vacuous_100_00_on_empty_template
    """
    twins = _twin_deals(api)
    deal_b = twins["deal_b"]

    signed = fx.execute_deal(api, deal_b["id"])
    assert signed["cp_total_count"] == 1, signed
    asserts.assert_score(signed["cp_completion_pct"], 0.00, "cp_completion_pct")
    assert signed["status"] == "EXECUTED", signed
    assert signed["effective_at"] is None, signed

    conditions = fx.conditions_of(api, deal_b["id"])
    assert [row["cp_type"] for row in conditions] == ["NOTICE_TO_PROCEED"], \
        conditions
    only_row = conditions[0]
    assert only_row["is_waivable"] is True, only_row
    assert only_row["status"] == "PENDING", only_row
    asserts.assert_instant_equals(only_row["deadline_date"],
                                  fx.CP_NOTICE_TO_PROCEED_DEADLINE,
                                  "deadline_date")

    fx.waive_condition(
        api, only_row["id"],
        waiver_justification=("Committee accepts a one-quarter "
                             "full-notice-to-proceed slip"))

    effective = fx.read_deal(api, deal_b["id"])
    asserts.assert_score(effective["cp_completion_pct"], 100.00,
                         "cp_completion_pct")
    assert effective["status"] == "EFFECTIVE", effective
    asserts.assert_instant_equals(effective["commercial_operation_deadline"],
                                  fx.DEFAULT_COD_AFTER_ONE_WAIVER,
                                  "commercial_operation_deadline")
    # The only behavioural difference from its twin traces to the template size.
    asserts.assert_money(effective["contract_price_usd_per_mwh"], 22.75,
                         "contract_price_usd_per_mwh")
