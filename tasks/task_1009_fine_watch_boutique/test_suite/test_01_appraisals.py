"""Appraisals: the two valuation philosophies and the OCC guard on re-appraisal.

Translates queue-A dual_variant_calc/appraisal_market_vs_insurance_replacement
and the corner calculations/cross_cutting instances covering the same surface.
"""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    appraisable_watch, authenticate, TEST_USERS,
)

ASSOC = TEST_USERS["associate_headers"]

# Same watch across the valuation tests: EXCELLENT (0.88) + box/papers (0.08)
# on a 1,000,000-cent MSRP model carrying a 2500-bps scarcity premium.
_MODEL = {"msrp_cents": 1000000, "market_premium_bps": 2500}
_WATCH = {"condition_grade": "EXCELLENT", "has_box_papers": True, "list_price_cents": 1200000}


def test_market_basis_selects_condition_depreciated_value(api):
    """PRD §3.2: "The market value, market_value_cents, is the model's msrp_cents
    multiplied by the condition factor and then by one plus the box premium,
    rounded half-up to whole cents. It depreciates for wear."
    PRD §3.2: "The appraised_value_cents recorded on the appraisal is
    market_value_cents when valuation_basis is MARKET (as used for WARRANTY and
    SALE purposes) and replacement_value_cents when valuation_basis is
    INSURANCE_REPLACEMENT (as used for INSURANCE)."

    Design: Difficulty/dual_variant_calc/appraisal_market_vs_insurance_replacement
    """
    ctx = appraisable_watch(model_over=_MODEL, watch_over=_WATCH)
    watch = ctx["watch"]
    data = validate_success(
        api.create_appraisal(
            watch["id"],
            {"purpose": "SALE", "valuation_basis": "MARKET",
             "expected_watch_version": watch["version"]},
            ASSOC,
        ),
        expected_status=201,
    )
    assert data["market_value_cents"] == 950400, data["market_value_cents"]
    assert data["appraised_value_cents"] == 950400, data["appraised_value_cents"]


def test_market_and_replacement_values_diverge(api):
    """PRD §3.2: "The replacement value, replacement_value_cents, is the model's
    msrp_cents multiplied by one plus market_premium_bps divided by 10000, rounded
    half-up to whole cents. It reflects retail plus scarcity and ignores condition
    entirely, so for a worn but scarce piece it yields the higher figure."

    Design: Difficulty/dual_variant_calc/appraisal_market_vs_insurance_replacement
    """
    ctx = appraisable_watch(model_over=_MODEL, watch_over=_WATCH)
    watch = ctx["watch"]
    data = validate_success(
        api.create_appraisal(
            watch["id"],
            {"purpose": "SALE", "valuation_basis": "MARKET",
             "expected_watch_version": watch["version"]},
            ASSOC,
        ),
        expected_status=201,
    )
    assert data["replacement_value_cents"] == 1250000, data["replacement_value_cents"]
    assert data["market_value_cents"] != data["replacement_value_cents"]


def test_insurance_basis_selects_replacement_value(api):
    """PRD §3.2: "The appraised_value_cents recorded on the appraisal is
    market_value_cents when valuation_basis is MARKET (as used for WARRANTY and
    SALE purposes) and replacement_value_cents when valuation_basis is
    INSURANCE_REPLACEMENT (as used for INSURANCE)."

    Design: Corner/calculations/appraisal_insurance_basis_selects_replacement
    """
    ctx = appraisable_watch(model_over=_MODEL, watch_over=_WATCH)
    watch = ctx["watch"]
    data = validate_success(
        api.create_appraisal(
            watch["id"],
            {"purpose": "INSURANCE", "valuation_basis": "INSURANCE_REPLACEMENT",
             "expected_watch_version": watch["version"]},
            ASSOC,
        ),
        expected_status=201,
    )
    assert data["appraised_value_cents"] == 1250000, data["appraised_value_cents"]
    assert data["replacement_value_cents"] == 1250000
    assert data["market_value_cents"] == 950400


def test_stale_watch_version_rejects_second_appraisal(api):
    """PRD §2.7: "If it is present but does not equal the watch's current version
    — because some other writer has authenticated, flagged, or re-appraised the
    watch since the client last read it — the create is rejected with
    ERR_STALE_VERSION (HTTP 412)."
    PRD §2.7: "Because each successful appraisal supersedes the prior
    current_appraisal_id and itself bumps the watch's version, this rule prevents
    a client from writing an appraisal against a watch state it has not actually
    observed."

    Design: Corner/cross_cutting/occ_stale_expected_watch_version
    """
    ctx = appraisable_watch(model_over={"msrp_cents": 1000000, "market_premium_bps": 1000},
                            watch_over={"condition_grade": "MINT", "list_price_cents": 1000000})
    watch = authenticate(ctx["watch"]["id"])  # create v1 -> authenticate v2
    observed_v = watch["version"]
    first = validate_success(
        api.create_appraisal(
            watch["id"],
            {"purpose": "SALE", "valuation_basis": "MARKET",
             "expected_watch_version": observed_v},
            ASSOC,
        ),
        expected_status=201,
    )
    assert first["id"]
    # The successful appraisal bumped the watch version; the stale value now fails.
    validate_error(
        api.create_appraisal(
            watch["id"],
            {"purpose": "WARRANTY", "valuation_basis": "MARKET",
             "expected_watch_version": observed_v},
            ASSOC,
        ),
        ApiErrorId.ERR_STALE_VERSION,
    )


def test_missing_expected_version_rejected(api):
    """PRD §2.7: "If expected_watch_version is omitted from the request body, the
    request is rejected with ERR_VERSION_REQUIRED (HTTP 400)."

    Design: Corner/cross_cutting/occ_missing_expected_version_required
    """
    ctx = appraisable_watch(model_over={"msrp_cents": 800000},
                            watch_over={"condition_grade": "MINT", "list_price_cents": 800000})
    watch = authenticate(ctx["watch"]["id"])
    validate_error(
        api.create_appraisal(
            watch["id"], {"purpose": "SALE", "valuation_basis": "MARKET"}, ASSOC,
        ),
        ApiErrorId.ERR_VERSION_REQUIRED,
    )
