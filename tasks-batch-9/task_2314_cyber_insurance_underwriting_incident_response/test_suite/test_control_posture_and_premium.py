"""Control posture scoring and the two premium runs.

Everything here exercises PRD §3.4: the attested and verified score variants,
the layer-banded gross premium with its stacked modifiers, and the minimum
verified score of 70 that gates a bindable quote.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import UNDERWRITER_HEADERS, ErrorId
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import assert_money, assert_score_2dp, data_of, find_row, get_rows


# ==========================================================================
# Attested versus verified posture on one application
# ==========================================================================
def _aurora_submitted_with_pending_scan(api):
    """Catalog, Aurora Health, attestations FULL/FULL/FULL/FULL/PARTIAL, one PENDING scan."""
    X.seed_catalog(api)
    account = X.create_account(api, C.ACCOUNT_AURORA)
    application = X.create_application(
        api,
        account["id"],
        requested_aggregate_limit_usd=5000000,
        requested_retention_usd=250000,
    )
    X.attest_controls(api, application["id"], C.ATTEST_95)
    # The indicative run fires at submission (PRD §3.4), so the caller needs the
    # post-submission application, not the DRAFT row returned by creation.
    application = X.submit_application(api, application["id"])
    scan = X.order_scan(api, application["id"], scan_score=68)
    return account, application, scan


def test_scan_finding_lowers_verified_score_below_attested_score(api):
    """A HIGH finding at PARTIAL on EMAIL_FILTERING drops the verified basis to 87.50.

    PRD §3.4: "The level used for scoring is then the lower of the `attested_level`
    and that observed level on the same ordering." The attested basis ignores the
    scan entirely, so `attested_control_score` stays at 95.00 while
    `verified_control_score` lands on 87.50, and the computed posture read returns
    both figures side by side with `quotable` true.

    Design: Difficulty/dual_variant_calc/control_posture_attested_versus_verified_diverge_on_application
    """
    _account, application, scan = _aurora_submitted_with_pending_scan(api)
    assert_score_2dp(application["attested_control_score"], 95.00, "attested_control_score")
    assert_money(application["indicative_premium_usd"], 25398.00, "indicative_premium_usd")

    X.complete_scan(
        api,
        scan["id"],
        findings=[F.scan_finding("EMAIL_FILTERING", "HIGH", "PARTIAL")],
    )

    after = X.read_application(api, application["id"])
    assert_score_2dp(after["attested_control_score"], 95.00, "attested_control_score")
    assert_score_2dp(after["verified_control_score"], 87.50, "verified_control_score")
    assert after["mandatory_gap_count"] == 0, after["mandatory_gap_count"]

    attestations = get_rows(
        api.list_application_control_attestations(application["id"], UNDERWRITER_HEADERS)
    )
    email = find_row(attestations, control_key="EMAIL_FILTERING")
    assert email["attested_level"] == "FULL", email["attested_level"]
    assert email["verified_level"] == "PARTIAL", email["verified_level"]
    mfa = find_row(attestations, control_key="MFA_PRIVILEGED")
    assert mfa["verified_level"] == "FULL", mfa["verified_level"]

    posture = data_of(api.get_control_posture(application["id"], UNDERWRITER_HEADERS))
    assert_score_2dp(posture["attested_score"], 95.00, "attested_score")
    assert_score_2dp(posture["verified_score"], 87.50, "verified_score")
    assert posture["quotable"] is True, posture
    assert posture["min_score_for_coverage"] == 70, posture["min_score_for_coverage"]


def test_bindable_premium_uses_verified_score_and_diverges_from_indicative(api):
    """The bindable run prices 87.50 at 28458.00 against the indicative 25398.00.

    PRD §3.4: "The **indicative run** fires at submission, consumes
    `attested_control_score`, and writes `indicative_premium_usd` — a figure issued
    before any scan can contradict the applicant." Gross is 9,000 x 1.00 x 3.4 =
    30600.00; the indicative multiplier is 1 - 0.15 - 0.10 + 0.08 = 0.83 and the
    bindable multiplier is 1 - 0.05 - 0.10 + 0.08 = 0.93, so the two runs diverge
    by exactly 3060.00.

    Design: Difficulty/dual_variant_calc/control_posture_attested_versus_verified_diverge_on_application
    """
    _account, application, scan = _aurora_submitted_with_pending_scan(api)
    X.complete_scan(
        api,
        scan["id"],
        findings=[F.scan_finding("EMAIL_FILTERING", "HIGH", "PARTIAL")],
    )

    quoted = X.quote_application(api, application["id"])

    assert quoted["status"] == "QUOTED", quoted["status"]
    assert_money(quoted["premium_usd"], 28458.00, "premium_usd")
    assert_money(quoted["indicative_premium_usd"], 25398.00, "indicative_premium_usd")
    divergence = round(float(quoted["premium_usd"]) - float(quoted["indicative_premium_usd"]), 2)
    assert divergence == 3060.00, divergence


# ==========================================================================
# Layer banding with stacked modifiers
# ==========================================================================
def _redstone_quoted(api):
    """Redstone Capital, aggregate 10,000,000, retention 100,000, clean scan."""
    return X.quoted_application(
        api,
        account_spec=C.ACCOUNT_REDSTONE,
        attestations=C.ATTEST_87_50,
        requested_aggregate_limit_usd=10000000,
        requested_retention_usd=100000,
        findings=[],
    )


def test_ten_million_layer_units_price_gross_before_modifiers(api):
    """8,000 x 1.35 x 5.15 layer units then a 0.90 multiplier gives 50058.00.

    PRD §3.4: "Concretely, the layer units are the lesser of the millions figure and
    1, multiplied by 1.00; plus the greater of zero and the quantity (the lesser of
    the millions figure and 5, less 1), multiplied by 0.60; plus the greater of zero
    and the millions figure less 5, multiplied by 0.35." A flat 8,000 x 1.35 x 10
    would price the whole tower at the first-layer factor and is wrong.

    Design: Difficulty/combinatorial_formula/premium_layer_banding_with_stacked_modifiers_mode_a
    """
    chain = _redstone_quoted(api)
    application = chain["application"]

    assert_score_2dp(application["verified_control_score"], 87.50, "verified_control_score")
    assert application["status"] == "QUOTED", application["status"]
    assert_money(application["premium_usd"], 50058.00, "premium_usd")

    layer_units = 1 * 1.00 + 4 * 0.60 + 5 * 0.35
    gross = round(8000 * 1.35 * layer_units, 2)
    assert gross == 55620.00, gross
    assert round(gross * 0.90, 2) == 50058.00
    assert round(float(application["premium_usd"]), 2) != round(8000 * 1.35 * 10 * 0.90, 2)


def test_clean_scan_leaves_indicative_and_bindable_premiums_equal(api):
    """With no findings the two scores coincide, so both premium fields read 50058.00.

    PRD §3.4: "A control absent from the array altogether is treated as observed at
    `FULL`: silence from the scanner is not evidence against the applicant." The
    -0.05 control band, the -0.05 retention credit for 100,000 and the zero
    dependency load for `NONE` therefore apply to both runs alike.

    Design: Difficulty/combinatorial_formula/premium_layer_banding_with_stacked_modifiers_mode_a
    """
    chain = _redstone_quoted(api)
    application = chain["application"]

    assert_money(application["premium_usd"], 50058.00, "premium_usd")
    assert_money(application["indicative_premium_usd"], 50058.00, "indicative_premium_usd")
    assert_score_2dp(application["attested_control_score"], 87.50, "attested_control_score")
    assert_score_2dp(application["verified_control_score"], 87.50, "verified_control_score")


# ==========================================================================
# The minimum verified score of 70
# ==========================================================================
def _cordial_application(api, attestations, seed):
    account_spec = C.ACCOUNT_CORDIAL
    if seed:
        X.seed_catalog(api)
    account = X.create_account(api, account_spec)
    application = X.create_application(
        api,
        account["id"],
        requested_aggregate_limit_usd=5000000,
        requested_retention_usd=250000,
    )
    X.attest_controls(api, application["id"], attestations)
    X.submit_application(api, application["id"])
    scan = X.order_scan(api, application["id"], scan_score=68)
    X.complete_scan(api, scan["id"], findings=[])
    return account, application


def test_verified_score_exactly_seventy_is_quotable(api):
    """70.00 clears the gate and prices in the 70-to-75 band at 33048.00.

    PRD §3.5: "`verified_control_score` must be at least the minimum score for
    coverage, which is 70." A score of exactly 70 is therefore quotable, and the
    positive 0.10 control adjustment applies: 30600.00 x (1 + 0.10 - 0.10 + 0.08)
    = 33048.00.

    Design: Difficulty/boundary_precision_check/control_score_exactly_at_minimum_quotable_while_sixty_five_rejected
    """
    _account, application = _cordial_application(api, C.ATTEST_70, seed=True)

    before = X.read_application(api, application["id"])
    assert_score_2dp(before["verified_control_score"], 70.00, "verified_control_score")
    assert before["mandatory_gap_count"] == 0, before["mandatory_gap_count"]
    assert before["status"] == "UNDERWRITING", before["status"]

    response = api.quote_application(
        application["id"], F.quote_payload(before["version"]), UNDERWRITER_HEADERS
    )
    validate_success(response, expected_status=200)

    quoted = X.read_application(api, application["id"])
    assert quoted["status"] == "QUOTED", quoted["status"]
    assert_money(quoted["premium_usd"], 33048.00, "premium_usd")


def test_verified_score_of_sixty_five_is_refused_but_was_already_priced_indicatively(api):
    """65.00 is refused with ERR_CONTROL_SCORE_BELOW_MINIMUM and keeps its indicative figure.

    PRD §3.5: "A score strictly below 70 with no mandatory gap present is refused
    with `ERR_CONTROL_SCORE_BELOW_MINIMUM`." The refusal leaves `premium_usd` null
    while `indicative_premium_usd` still shows the +0.30 band priced at submission:
    30600.00 x (1 + 0.30 - 0.10 + 0.08) = 39168.00.

    Design: Difficulty/boundary_precision_check/control_score_exactly_at_minimum_quotable_while_sixty_five_rejected
    """
    _account, application = _cordial_application(api, C.ATTEST_65, seed=True)

    before = X.read_application(api, application["id"])
    assert_score_2dp(before["verified_control_score"], 65.00, "verified_control_score")
    assert before["mandatory_gap_count"] == 0, before["mandatory_gap_count"]

    response = api.quote_application(
        application["id"], F.quote_payload(before["version"]), UNDERWRITER_HEADERS
    )
    validate_error(response, ErrorId.CONTROL_SCORE_BELOW_MINIMUM, expected_status=422)

    after = X.read_application(api, application["id"])
    assert after["status"] == "UNDERWRITING", after["status"]
    assert after["premium_usd"] is None, after["premium_usd"]
    assert_money(after["indicative_premium_usd"], 39168.00, "indicative_premium_usd")
