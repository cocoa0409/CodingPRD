"""
Claim indemnity arithmetic and the documentation-and-survey rework loop.

Covers the two loss-quantification bases a claim may be adjusted on, where the
deductible enters each of them, the time bar the adjustment pins, and the claim
lifecycle that revisits the survey state a second time when the evidence log is
still short.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, validate_success

from test_helpers import (
    CLAIMS_ADJUSTER,
    EXPECTED_CLAIM_ADJUSTED_DEPRECIATION,
    EXPECTED_CLAIM_ADJUSTED_SALVAGE,
    EXPECTED_CLAIM_DEDUCTIBLE_APPLIED,
    EXPECTED_CLAIM_DEDUCTIBLE_APPLIED_SALVAGE,
    EXPECTED_CLAIM_GROSS,
    EXPECTED_INSURED_VALUE_CIF,
    ApiClient,
    add_claim_document,
    adjust_claim_file,
    assert_instant,
    assert_money,
    assert_total_count,
    build_canonical_environment,
    build_draft_certificate,
    build_environment_with_issued_certificate,
    complete_claim_documents,
    create_survey_order,
    create_surveyor,
    file_survey_report,
    issue_certificate,
    open_claim_file,
    read_claim_file,
    read_survey_order,
    read_surveyor,
    set_clock,
)

# The measurement inputs the two adjustment bases read.
DAMAGE_PERCENTAGE = 12.5
SOUND_MARKET_VALUE = 1200000
DAMAGED_SALE_PROCEEDS = 1050000

# The excess pinned on every certificate of the canonical open cover.
PINNED_DEDUCTIBLE = 2500.00

# The carrier time bar: the certificate's 2026-09-05 discharge plus 365 days.
EXPECTED_TIME_BAR = "2027-09-05T00:00:00Z"

# The two attendance windows of the rework loop, two hours each.
LAP_1_WINDOW = ("2026-08-25T09:00:00Z", "2026-08-25T11:00:00Z")
LAP_2_WINDOW = ("2026-08-26T09:00:00Z", "2026-08-26T11:00:00Z")
LAP_WINDOW_MINUTES = 120


def _build_two_indemnity_variants(api: ApiClient) -> dict:
    """
    Two certificates issued on identical CIF terms — insured value 1155000.00,
    deductible 2500.00 each — carrying one claim apiece with a complete evidence
    log: one on `DEPRECIATION_PCT`, one on `SALVAGE_SALE_PROCEEDS`.
    """
    env = build_canonical_environment(api)
    draft_a = build_draft_certificate(api, env)
    draft_b = build_draft_certificate(api, env, certificate_number="CERT-B")
    env["certificate_a"] = issue_certificate(api, draft_a["id"], env["policy_id"])
    env["certificate_b"] = issue_certificate(api, draft_b["id"], env["policy_id"])

    env["depreciation_claim"] = open_claim_file(
        api, env["certificate_a"]["id"],
        adjustment_basis="DEPRECIATION_PCT",
        claimed_amount=EXPECTED_CLAIM_GROSS,
        damage_percentage=DAMAGE_PERCENTAGE,
    )
    env["salvage_claim"] = open_claim_file(
        api, env["certificate_b"]["id"],
        adjustment_basis="SALVAGE_SALE_PROCEEDS",
        claimed_amount=EXPECTED_CLAIM_GROSS,
        sound_market_value=SOUND_MARKET_VALUE,
        damaged_sale_proceeds=DAMAGED_SALE_PROCEEDS,
    )
    complete_claim_documents(api, env["depreciation_claim"]["id"],
                             reference_prefix="DOC-A")
    complete_claim_documents(api, env["salvage_claim"]["id"],
                             reference_prefix="DOC-B")
    return env


def _adjust_both_indemnity_variants(api: ApiClient, env: dict) -> dict:
    """Adjust both claims and record the two results."""
    env["depreciation_result"] = adjust_claim_file(
        api, env["depreciation_claim"]["id"])
    env["salvage_result"] = adjust_claim_file(api, env["salvage_claim"]["id"])
    return env


def _open_survey_claim(api: ApiClient) -> dict:
    """
    One issued CIF certificate, an active surveyor at the discharge port
    certified for the shipment's susceptibility, and a claim on the
    depreciation basis whose `damage_percentage` is deliberately left unstated.
    """
    env = build_environment_with_issued_certificate(api)
    env["surveyor"] = create_surveyor(api, env["discharge_port_id"])
    env["surveyor_id"] = env["surveyor"]["id"]
    env["claim"] = open_claim_file(
        api, env["certificate_id"],
        adjustment_basis="DEPRECIATION_PCT",
        claimed_amount=EXPECTED_CLAIM_GROSS,
    )
    env["claim_id"] = env["claim"]["id"]
    return env


def _run_first_lap(api: ApiClient, env: dict) -> dict:
    """
    Order the first survey, attend it, file the report and try to adjust while
    the evidence log still holds nothing but that report.
    """
    env["order_1"] = create_survey_order(
        api, env["claim_id"], env["surveyor_id"], *LAP_1_WINDOW)
    set_clock(api, "2026-08-25T09:30:00Z")
    file_survey_report(api, env["order_1"]["id"], env["surveyor_id"],
                       report_reference="SR-LAP1",
                       damage_percentage_found=DAMAGE_PERCENTAGE)
    env["first_adjust"] = adjust_claim_file(api, env["claim_id"])
    return env


def _order_second_survey(api: ApiClient, env: dict) -> dict:
    """Send the reworked file round for a further survey."""
    env["order_2"] = create_survey_order(
        api, env["claim_id"], env["surveyor_id"], *LAP_2_WINDOW)
    return env


def _run_second_lap(api: ApiClient, env: dict) -> dict:
    """
    Attend the second survey, complete the evidence log with the bill of lading
    and the carrier claim letter, and adjust the file for good.
    """
    set_clock(api, "2026-08-26T09:30:00Z")
    file_survey_report(api, env["order_2"]["id"], env["surveyor_id"],
                       report_reference="SR-LAP2",
                       damage_percentage_found=DAMAGE_PERCENTAGE)
    add_claim_document(api, env["claim_id"], "BILL_OF_LADING", "BL-A-1",
                       "2026-08-26T10:00:00Z")
    add_claim_document(api, env["claim_id"], "CARRIER_CLAIM_LETTER", "CL-A-1",
                       "2026-08-26T10:00:00Z")
    env["second_adjust"] = adjust_claim_file(api, env["claim_id"])
    return env


def _run_full_rework_cycle(api: ApiClient) -> dict:
    """Take one claim all the way round the rework loop and out the other side."""
    env = _open_survey_claim(api)
    _run_first_lap(api, env)
    _order_second_survey(api, env)
    return _run_second_lap(api, env)


def test_depreciation_basis_subtracts_the_deductible_after_measuring_the_loss(
        api: ApiClient) -> None:
    """
    Measuring 12.5 percent of 1155000.00 gives a gross loss of 144375.00, and
    the 2500.00 excess comes off afterwards to pay 141875.00.

    `adjusted_amount` is then the gross loss minus the deductible, floored at 0.00 so it can never go negative, and `deductible_applied_amount` is the lesser of the deductible and the gross loss — a deductible larger than the loss is only absorbed up to the loss.

    Design: Difficulty/dual_variant_calc/claim_adjusted_amount_depreciation_pct_vs_salvage_proceeds
    """
    env = _adjust_both_indemnity_variants(api, _build_two_indemnity_variants(api))

    claim = read_claim_file(api, env["depreciation_claim"]["id"], CLAIMS_ADJUSTER)
    assert claim["adjustment_basis"] == "DEPRECIATION_PCT"
    assert claim["status"] == "ADJUSTED"
    assert_money(claim["adjusted_amount"], EXPECTED_CLAIM_ADJUSTED_DEPRECIATION,
                 "depreciation adjusted_amount")
    assert_money(claim["deductible_applied_amount"],
                 EXPECTED_CLAIM_DEDUCTIBLE_APPLIED,
                 "depreciation deductible_applied_amount")
    assert_money(
        float(claim["adjusted_amount"])
        + float(claim["deductible_applied_amount"]),
        EXPECTED_CLAIM_GROSS,
        "gross loss recomposed from the payout and the absorbed excess")


def test_salvage_basis_applies_the_ratio_to_value_net_of_the_deductible(
        api: ApiClient) -> None:
    """
    A depreciation ratio of 0.125000 applied to 1155000.00 less the 2500.00
    excess pays 144062.50 — 2187.50 more than the depreciation basis on the same
    loss.

    `adjusted_amount` is the insured value minus the deductible, multiplied by that ratio, rounded half up to 2 decimals.

    Design: Difficulty/dual_variant_calc/claim_adjusted_amount_depreciation_pct_vs_salvage_proceeds
    """
    env = _adjust_both_indemnity_variants(api, _build_two_indemnity_variants(api))

    salvage = read_claim_file(api, env["salvage_claim"]["id"], CLAIMS_ADJUSTER)
    depreciation = read_claim_file(api, env["depreciation_claim"]["id"],
                                   CLAIMS_ADJUSTER)

    assert salvage["adjustment_basis"] == "SALVAGE_SALE_PROCEEDS"
    assert salvage["status"] == "ADJUSTED"
    assert_money(salvage["adjusted_amount"], EXPECTED_CLAIM_ADJUSTED_SALVAGE,
                 "salvage adjusted_amount")
    assert_money(
        float(salvage["adjusted_amount"]) - float(depreciation["adjusted_amount"]),
        EXPECTED_CLAIM_ADJUSTED_SALVAGE - EXPECTED_CLAIM_ADJUSTED_DEPRECIATION,
        "indemnity divergence between the two bases")


def test_salvage_basis_scales_the_deductible_down_by_the_ratio(
        api: ApiClient) -> None:
    """
    Because the excess enters before the ratio it is only absorbed in
    proportion: 312.50 here against the 2500.00 the depreciation basis absorbs.

    `deductible_applied_amount` is the insured value multiplied by the ratio and rounded half up to 2 decimals, minus the adjusted amount — so the deductible is scaled down by the ratio rather than deducted in full.

    Design: Difficulty/dual_variant_calc/claim_adjusted_amount_depreciation_pct_vs_salvage_proceeds
    """
    env = _adjust_both_indemnity_variants(api, _build_two_indemnity_variants(api))

    salvage = read_claim_file(api, env["salvage_claim"]["id"], CLAIMS_ADJUSTER)
    depreciation = read_claim_file(api, env["depreciation_claim"]["id"],
                                   CLAIMS_ADJUSTER)

    assert_money(salvage["deductible_applied_amount"],
                 EXPECTED_CLAIM_DEDUCTIBLE_APPLIED_SALVAGE,
                 "salvage deductible_applied_amount")
    assert_money(depreciation["deductible_applied_amount"], PINNED_DEDUCTIBLE,
                 "depreciation deductible_applied_amount")
    assert_money(
        float(salvage["adjusted_amount"])
        + float(salvage["deductible_applied_amount"]),
        EXPECTED_CLAIM_GROSS,
        "insured value taken at the ratio, before the excess is scaled out")


def test_both_bases_pin_the_time_bar_to_discharge_plus_365_days(
        api: ApiClient) -> None:
    """
    Whichever basis quantified the loss, reaching the adjusted state pins the
    carrier time bar one year after the certificate's discharge date.

    The loss is quantified, `adjusted_by_user_id` records the acting `X-User-ID`, and `time_bar_at` is pinned to the certificate's `discharge_date` plus 365 days — one year from discharge, the conventional carrier time bar.

    Design: Difficulty/dual_variant_calc/claim_adjusted_amount_depreciation_pct_vs_salvage_proceeds
    """
    env = _adjust_both_indemnity_variants(api, _build_two_indemnity_variants(api))

    for label in ("depreciation_claim", "salvage_claim"):
        claim = read_claim_file(api, env[label]["id"], CLAIMS_ADJUSTER)
        assert claim["status"] == "ADJUSTED", label
        assert is_iso8601_timestamp(claim["time_bar_at"]), label
        assert_instant(claim["time_bar_at"], EXPECTED_TIME_BAR, label)
        assert claim["adjusted_by_user_id"] is not None, label

    certificate = validate_success(
        api.get_certificate(env["certificate_a"]["id"], CLAIMS_ADJUSTER))
    assert_money(certificate["insured_value"], EXPECTED_INSURED_VALUE_CIF,
                 "certificate insured_value read by the adjustment")


def test_incomplete_evidence_sends_the_first_adjustment_to_docs_incomplete(
        api: ApiClient) -> None:
    """
    With only the surveyor's own report on the log, the first adjustment
    quantifies nothing and parks the file in the rework state.

    Evaluated third: if `documentation_complete` is false, the claim moves to `DOCS_INCOMPLETE`, `adjusted_amount` stays null and `adjusted_by_user_id` stays null.

    Design: Difficulty/non_linear_state_machine/claim_file_docs_incomplete_resurvey_cycle
    """
    env = _run_first_lap(api, _open_survey_claim(api))

    assert env["first_adjust"]["status"] == "DOCS_INCOMPLETE"

    claim = read_claim_file(api, env["claim_id"], CLAIMS_ADJUSTER)
    assert claim["status"] == "DOCS_INCOMPLETE"
    assert claim["documentation_complete"] is False
    assert claim["warranty_breach"] is False
    assert claim["adjusted_amount"] is None
    assert claim["adjusted_by_user_id"] is None


def test_second_survey_order_re_enters_survey_ordered_from_docs_incomplete(
        api: ApiClient) -> None:
    """
    A file in the rework state accepts a further appointment and the claim
    returns to the survey state it had already left.

    On success the order is created in `status` `APPOINTED`, its `window_minutes` is computed as the whole number of minutes between the two window instants, the surveyor's `booked_minutes_total` rises by that figure, and the claim moves to `SURVEY_ORDERED` — from `OPENED` on a first survey, or from `DOCS_INCOMPLETE` when the file is going round the rework loop for a further survey.

    Design: Difficulty/non_linear_state_machine/claim_file_docs_incomplete_resurvey_cycle
    """
    env = _order_second_survey(api, _run_first_lap(api, _open_survey_claim(api)))

    second_order = read_survey_order(api, env["order_2"]["id"], CLAIMS_ADJUSTER)
    assert second_order["status"] == "APPOINTED"
    assert second_order["window_minutes"] == LAP_WINDOW_MINUTES

    first_order = read_survey_order(api, env["order_1"]["id"], CLAIMS_ADJUSTER)
    assert first_order["status"] == "REPORT_FILED"
    assert first_order["window_minutes"] == LAP_WINDOW_MINUTES

    claim = read_claim_file(api, env["claim_id"], CLAIMS_ADJUSTER)
    assert claim["status"] == "SURVEY_ORDERED"


def test_booked_minutes_accumulate_across_both_survey_laps(
        api: ApiClient) -> None:
    """
    Two attended two-hour windows leave the surveyor's calendar carrying 240
    minutes, because filing a report never gives the slot back.

    The surveyor's `booked_minutes_total` is *not* reduced: a filed report still occupies the calendar slot that was attended.

    Design: Difficulty/non_linear_state_machine/claim_file_docs_incomplete_resurvey_cycle
    """
    env = _run_full_rework_cycle(api)

    for order_key in ("order_1", "order_2"):
        order = read_survey_order(api, env[order_key]["id"], CLAIMS_ADJUSTER)
        assert order["status"] == "REPORT_FILED", order_key
        assert order["window_minutes"] == LAP_WINDOW_MINUTES, order_key

    surveyor = read_surveyor(api, env["surveyor_id"], CLAIMS_ADJUSTER)
    assert surveyor["booked_minutes_total"] == 2 * LAP_WINDOW_MINUTES


def test_each_survey_lap_appends_its_own_survey_report_document(
        api: ApiClient) -> None:
    """
    The log ends with four rows: one automatic surveyor's report per lap, plus
    the bill of lading and the carrier claim letter appended by the adjuster.

    A damage document of type `SURVEY_REPORT` with `origin` `SURVEYOR` is appended to the claim automatically, and `documentation_complete` is re-derived from the enlarged log — which is often the moment a file becomes complete.

    Design: Difficulty/non_linear_state_machine/claim_file_docs_incomplete_resurvey_cycle
    """
    env = _run_full_rework_cycle(api)

    rows = assert_total_count(
        api.list_claim_documents(env["claim_id"], CLAIMS_ADJUSTER), 4,
        "claim evidence log")

    survey_reports = [row for row in rows if row["doc_type"] == "SURVEY_REPORT"]
    assert len(survey_reports) == 2
    assert all(row["origin"] == "SURVEYOR" for row in survey_reports)

    doc_types = sorted(row["doc_type"] for row in rows)
    assert doc_types == ["BILL_OF_LADING", "CARRIER_CLAIM_LETTER",
                         "SURVEY_REPORT", "SURVEY_REPORT"]

    claim = read_claim_file(api, env["claim_id"], CLAIMS_ADJUSTER)
    assert claim["documentation_complete"] is True


def test_completed_file_adjusts_on_the_certified_damage_percentage(
        api: ApiClient) -> None:
    """
    The claim was opened without a damage percentage, so the surveyor's
    certified 12.5 becomes the measurement and the file finally pays 141875.00.

    Finally, when the claim's `adjustment_basis` is `DEPRECIATION_PCT` and its `damage_percentage` is still null, the surveyor's `damage_percentage_found` is copied into it, so the certified figure becomes the measurement the adjustment will use.

    Design: Difficulty/non_linear_state_machine/claim_file_docs_incomplete_resurvey_cycle
    """
    env = _run_full_rework_cycle(api)

    assert env["second_adjust"]["status"] == "ADJUSTED"

    claim = read_claim_file(api, env["claim_id"], CLAIMS_ADJUSTER)
    assert claim["status"] == "ADJUSTED"
    assert float(claim["damage_percentage"]) == DAMAGE_PERCENTAGE
    assert_money(claim["adjusted_amount"], EXPECTED_CLAIM_ADJUSTED_DEPRECIATION,
                 "adjusted_amount after the rework loop")
    assert_money(claim["deductible_applied_amount"],
                 EXPECTED_CLAIM_DEDUCTIBLE_APPLIED,
                 "deductible_applied_amount after the rework loop")
