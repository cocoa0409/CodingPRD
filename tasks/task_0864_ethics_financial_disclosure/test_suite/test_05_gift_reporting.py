"""Gift and travel reporting: net vs gross valuation, per-leg travel rounding, the single-gift
boundary, the training gate, statutory limits, disposal, and reverse-reachability.

Queue A: dual_variant_calc (gift net vs gross), combinatorial_formula (travel per-leg rounding),
boundary_precision_check (net == single limit), priority_pair_validation_conflict (training
beats limit). Queue B: over-limit, annual-source limit, dispose aggregate, empty travel legs,
reverse-reachability, dispose-already-disposed.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_filer_headers,
    setup_trained_filer, setup_untrained_filer, report_gift, get_filer,
)


def test_gift_net_reportable_subtracts_consideration(api):
    """PRD 3.6: "is the disclosed gross minus `consideration_paid_cents`, floored at zero so it
    is never negative."

    Design: Difficulty/dual_variant_calc/gift_reportable_net_vs_gross
    """
    jur, filer = setup_trained_filer(category="APPOINTED",
                                     jur_overrides={"gift_single_limit_cents": 5000})
    gift = validate_success(report_gift(
        filer["id"], source_name="Acme Corp", gift_kind="GIFT",
        received_at="2026-05-01T12:00:00Z",
        fair_market_value_cents=6000, consideration_paid_cents=2000), 201)
    assert gift["reportable_value_cents"] == 4000
    assert get_filer(filer["id"])["reportable_gift_total_cents"] == 4000


def test_gift_gross_disclosed_ignores_consideration(api):
    """PRD 3.6: "is the full gross with no consideration subtracted: for a `GIFT` it is
    `fair_market_value_cents`".
    PRD 3.6: "These two differ precisely when `consideration_paid_cents` is greater than zero".

    Design: Difficulty/dual_variant_calc/gift_reportable_net_vs_gross
    """
    jur, filer = setup_trained_filer(category="APPOINTED",
                                     jur_overrides={"gift_single_limit_cents": 5000})
    gift = validate_success(report_gift(
        filer["id"], source_name="Acme Corp", gift_kind="GIFT",
        received_at="2026-05-01T12:00:00Z",
        fair_market_value_cents=6000, consideration_paid_cents=2000), 201)
    assert gift["disclosed_gross_cents"] == 6000
    assert gift["reportable_value_cents"] != gift["disclosed_gross_cents"]


def test_travel_round_per_leg_then_sum(api):
    """PRD 3.6: "A leg's raw value is `nights` multiplied by `nightly_rate_cents`, plus `miles`
    multiplied by the mileage rate of 65.5 cents per mile. The rounding order is pinned: each
    leg's raw value is rounded half-up to whole cents individually, and only then are the rounded
    legs summed to yield the travel gross".

    Design: Difficulty/combinatorial_formula/gift_travel_round_per_leg_then_sum
    """
    jur, filer = setup_trained_filer(category="APPOINTED",
                                     jur_overrides={"gift_single_limit_cents": 5000})
    legs = [{"nights": 0, "nightly_rate_cents": 0, "miles": 33},
            {"nights": 0, "nightly_rate_cents": 0, "miles": 33}]
    gift = validate_success(report_gift(
        filer["id"], source_name="ConfOrg", gift_kind="TRAVEL",
        received_at="2026-05-01T00:00:00Z", consideration_paid_cents=0, travel_legs=legs), 201)
    # 33 * 65.5 = 2161.5 -> round half-up per leg = 2162; two legs -> 4324.
    assert gift["reportable_value_cents"] == 4324
    assert gift["disclosed_gross_cents"] == 4324


def test_travel_valuation_not_sum_then_round(api):
    """PRD 3.6: "the legs are never summed before rounding."

    Design: Difficulty/combinatorial_formula/gift_travel_round_per_leg_then_sum
    """
    jur, filer = setup_trained_filer(category="APPOINTED",
                                     jur_overrides={"gift_single_limit_cents": 5000})
    legs = [{"nights": 0, "nightly_rate_cents": 0, "miles": 33},
            {"nights": 0, "nightly_rate_cents": 0, "miles": 33}]
    gift = validate_success(report_gift(
        filer["id"], source_name="ConfOrg", gift_kind="TRAVEL",
        received_at="2026-05-01T00:00:00Z", consideration_paid_cents=0, travel_legs=legs), 201)
    # sum-then-round would give 4323; per-leg rounding gives 4324.
    assert gift["reportable_value_cents"] == 4324
    assert gift["status"] == "REPORTED"


def test_gift_net_exactly_at_single_limit_allowed(api):
    """PRD 3.6: "The single-gift limit rejects any report whose net `reportable_value_cents`
    exceeds the jurisdiction's `gift_single_limit_cents`, with `ERR_GIFT_LIMIT_EXCEEDED`
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/gift_net_equals_single_limit
    """
    jur, filer = setup_trained_filer(category="APPOINTED",
                                     jur_overrides={"gift_single_limit_cents": 5000})
    gift = validate_success(report_gift(
        filer["id"], source_name="Acme Corp", gift_kind="GIFT",
        received_at="2026-05-01T00:00:00Z", fair_market_value_cents=5000), 201)
    assert gift["reportable_value_cents"] == 5000
    assert gift["status"] == "REPORTED"


def test_gift_at_limit_records_aggregate(api):
    """PRD 3.6: "A gift report's `status` is `REPORTED` on creation, and recording it adds its
    `reportable_value_cents` to the owning filer's `reportable_gift_total_cents`."

    Design: Difficulty/boundary_precision_check/gift_net_equals_single_limit
    """
    jur, filer = setup_trained_filer(category="APPOINTED",
                                     jur_overrides={"gift_single_limit_cents": 5000})
    validate_success(report_gift(
        filer["id"], source_name="Acme Corp", gift_kind="GIFT",
        received_at="2026-05-01T00:00:00Z", fair_market_value_cents=5000), 201)
    assert get_filer(filer["id"])["reportable_gift_total_cents"] == 5000


def test_gift_training_gate_beats_single_limit(api):
    """PRD 2.11: "training currency (`ERR_TRAINING_NOT_CURRENT`), recusal overlap
    (`ERR_RECUSAL_OVERLAP`), period overlap (`ERR_PERIOD_OVERLAP`), duplicate statement
    (`ERR_DUPLICATE_STATEMENT`), single-gift limit (`ERR_GIFT_LIMIT_EXCEEDED`)".
    PRD 3.6: "Reporting requires the acting filer's `training_status` to be `CURRENT`; a lapsed
    filer is rejected with `ERR_TRAINING_NOT_CURRENT`."

    Design: Difficulty/priority_pair_validation_conflict/gift_training_beats_limit
    """
    jur, filer = setup_untrained_filer(jur_overrides={"gift_single_limit_cents": 5000})
    res = report_gift(filer["id"], source_name="Acme Corp", gift_kind="GIFT",
                      received_at="2026-05-01T00:00:00Z",
                      fair_market_value_cents=8000, consideration_paid_cents=1000)
    validate_error(res, "ERR_TRAINING_NOT_CURRENT")


def test_untrained_over_limit_gift_not_recorded(api):
    """PRD 3.9: "Because both statement submission and gift reporting require `training_status`
    to be `CURRENT`, a lapse blocks those operations until a fresh course is completed."

    Design: Difficulty/priority_pair_validation_conflict/gift_training_beats_limit
    """
    jur, filer = setup_untrained_filer(jur_overrides={"gift_single_limit_cents": 5000})
    report_gift(filer["id"], source_name="Acme Corp", gift_kind="GIFT",
                received_at="2026-05-01T00:00:00Z",
                fair_market_value_cents=8000, consideration_paid_cents=1000)
    assert get_filer(filer["id"])["reportable_gift_total_cents"] == 0


def test_gift_over_single_limit_rejected(api):
    """PRD 3.6: "The single-gift limit rejects any report whose net `reportable_value_cents`
    exceeds the jurisdiction's `gift_single_limit_cents`, with `ERR_GIFT_LIMIT_EXCEEDED`
    (HTTP 422)."

    Design: Corner/calculations/gift_over_single_limit_returns_error
    """
    jur, filer = setup_trained_filer(category="APPOINTED",
                                     jur_overrides={"gift_single_limit_cents": 5000})
    res = report_gift(filer["id"], source_name="Acme", gift_kind="GIFT",
                      received_at="2026-05-01T00:00:00Z", fair_market_value_cents=5001)
    validate_error(res, "ERR_GIFT_LIMIT_EXCEEDED")


def test_annual_source_limit_exceeded(api):
    """PRD 3.6: "The annual per-source limit considers the running aggregate: the sum of net
    reportable values across the filer's existing non-disposed gift reports from the same
    `source_name` in the same calendar year as this gift's `received_at`, plus this gift's net
    value; if that aggregate exceeds the jurisdiction's `gift_annual_source_limit_cents`, the
    report is rejected with `ERR_GIFT_ANNUAL_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Corner/calculations/gift_annual_source_limit_exceeded
    """
    jur, filer = setup_trained_filer(
        category="APPOINTED",
        jur_overrides={"gift_single_limit_cents": 20000, "gift_annual_source_limit_cents": 25000})
    validate_success(report_gift(
        filer["id"], source_name="Acme", gift_kind="GIFT",
        received_at="2026-05-01T00:00:00Z", fair_market_value_cents=15000), 201)
    res = report_gift(filer["id"], source_name="Acme", gift_kind="GIFT",
                      received_at="2026-07-01T00:00:00Z", fair_market_value_cents=15000)
    validate_error(res, "ERR_GIFT_ANNUAL_LIMIT_EXCEEDED")
    assert get_filer(filer["id"])["reportable_gift_total_cents"] == 15000


def test_dispose_decrements_aggregate(api):
    """PRD 3.6: "Disposal requires the report to be `REPORTED`, moves it `REPORTED → DISPOSED`,
    and subtracts its `reportable_value_cents` from the filer's `reportable_gift_total_cents`,
    removing it from the annual aggregate."

    Design: Corner/calculations/gift_dispose_decrements_annual_aggregate
    """
    jur, filer = setup_trained_filer(category="APPOINTED",
                                     jur_overrides={"gift_single_limit_cents": 5000})
    gift = validate_success(report_gift(
        filer["id"], source_name="Acme", gift_kind="GIFT",
        received_at="2026-05-01T00:00:00Z", fair_market_value_cents=4000), 201)
    disposed = validate_success(
        api.dispose_gift_report(gift["id"], {"disposition_method": "RETURNED"},
                                make_filer_headers(filer["id"])), 200)
    assert disposed["status"] == "DISPOSED"
    assert get_filer(filer["id"])["reportable_gift_total_cents"] == 0


def test_dispose_already_disposed_gift_invalid_state(api):
    """PRD 3.6: "Disposal requires the report to be `REPORTED`, moves it `REPORTED → DISPOSED`,
    and subtracts its `reportable_value_cents` from the filer's `reportable_gift_total_cents`,
    removing it from the annual aggregate."

    Design: Corner/state_machines/dispose_already_disposed_gift_returns_invalid_state
    """
    jur, filer = setup_trained_filer(category="APPOINTED",
                                     jur_overrides={"gift_single_limit_cents": 5000})
    fh = make_filer_headers(filer["id"])
    gift = validate_success(report_gift(
        filer["id"], source_name="Acme", gift_kind="GIFT",
        received_at="2026-05-01T00:00:00Z", fair_market_value_cents=4000), 201)
    validate_success(api.dispose_gift_report(gift["id"], {}, fh), 200)
    res = api.dispose_gift_report(gift["id"], {}, fh)
    validate_error(res, "ERR_INVALID_STATE")
    assert get_filer(filer["id"])["reportable_gift_total_cents"] == 0


def test_travel_empty_legs_invalid_payload(api):
    """PRD 3.6: "a `TRAVEL` must supply a non-empty `travel_legs` array; a violation of either
    shape is rejected with `ERR_INVALID_GIFT_KIND_PAYLOAD` (HTTP 400)."

    Design: Corner/validations/gift_travel_empty_legs_returns_invalid_payload
    """
    jur, filer = setup_trained_filer(category="APPOINTED",
                                     jur_overrides={"gift_single_limit_cents": 5000})
    res = report_gift(filer["id"], source_name="ConfOrg", gift_kind="TRAVEL",
                      received_at="2026-05-01T00:00:00Z", travel_legs=[])
    validate_error(res, "ERR_INVALID_GIFT_KIND_PAYLOAD")


def test_gift_reports_filtered_by_filer(api, ethics_officer_headers):
    """PRD 2.3: "List responses populate the `limit`, `offset`, `total_count`, and `has_more`
    fields in the `meta` object of the envelope."

    Design: Corner/endpoints/gift_reports_reverse_reachable_by_filer_id
    """
    jur, filer = setup_trained_filer(category="APPOINTED",
                                     jur_overrides={"gift_single_limit_cents": 5000})
    gift = validate_success(report_gift(
        filer["id"], source_name="Acme", gift_kind="GIFT",
        received_at="2026-05-01T00:00:00Z", fair_market_value_cents=3000), 201)
    data, meta = validate_paginated(
        api.list_gift_reports(ethics_officer_headers, params={"filer_id": filer["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == gift["id"]
