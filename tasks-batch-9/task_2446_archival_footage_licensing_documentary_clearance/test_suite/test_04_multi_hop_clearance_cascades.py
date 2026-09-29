"""Transitive cascades: the rights sweep and the opinion-letter withdrawal, five hops each."""

from typing import Any, Dict

from test_helpers import (
    AUTO_WITHDRAWAL_RATIONALE,
    CLEARANCE_SUPERVISOR,
    LEGAL_COUNSEL,
    PRODUCTION_ADMIN,
    assert_asset_dimensions,
    assert_license_money_ledger,
    assert_posture,
    assert_production_counters,
    auto_suspension_reason,
    clear_asset_via_fair_use,
    create_asset,
    create_production_in_clearance,
    deliver_delivery_package,
    drive_opinion_letter,
    drive_production,
    get_asset,
    get_chart,
    get_delivery_package,
    get_license,
    get_production,
    get_success_data,
    open_delivery_package,
    pin_chart,
    place_bound_eo_cover,
    set_clock,
    setup_delivered_production,
    validate_delivery_package,
    validate_success,
)

_SWEEP_CLOCK_AT_SETUP = "2026-08-20T00:00:00Z"
_SWEEP_CLOCK_AFTER_TERM = "2027-08-20T00:00:00Z"

# A 45-second BROADCAST / WORLD / 12-month all-media licence on the standard card:
# 60000 x 2 units x 1.25 tier x 1.15 broadcast x 1.50 world x 1.00 term x 1.00 window.
_TWELVE_MONTH_FEE_CENTS = 258750


def _setup_locked_delivered_production(api) -> Dict[str, Any]:
    """A LOCKED production whose single footage asset is covered by a 12-month licence.

    The chart is PINNED, the E&O application is BOUND and the delivery package has
    reached DELIVERED, so every downstream hop of the sweep has something to bite on.
    """
    set_clock(api, _SWEEP_CLOCK_AT_SETUP)
    scenario = setup_delivered_production(
        api,
        policy_number="EO-2026-77",
        license_overrides={"term_months": 12, "term_start_date": "2026-08-15",
                           "term_end_date": "2027-08-15"})
    drive_production(api, scenario["production"]["id"], "LOCKED")
    scenario["production"] = get_production(api, scenario["production"]["id"])
    return scenario


def _assert_sweep_pre_state(api, scenario: Dict[str, Any]) -> None:
    """The settled position the sweep is about to unwind."""
    license_row = get_license(api, scenario["license"]["id"])
    assert license_row["status"] == "EXECUTED"
    assert license_row["executed_fee_cents"] == _TWELVE_MONTH_FEE_CENTS
    production = get_production(api, scenario["production"]["id"])
    assert production["status"] == "LOCKED"
    assert production["committed_fee_cents"] == _TWELVE_MONTH_FEE_CENTS
    assert production["sweep_epoch"] == 0
    assert_posture(production, "OPEN")
    assert get_delivery_package(api, scenario["delivery_package"]["id"])["status"] == \
        "DELIVERED"
    eo = get_success_data(
        api.get_eo_application(scenario["eo_application"]["id"], CLEARANCE_SUPERVISOR))
    assert eo["status"] == "BOUND"
    assert get_chart(api, scenario["chart"]["id"])["status"] == "PINNED"


def _run_sweep_past_term_end(api, production_id: str) -> Dict[str, Any]:
    """Move the clock past the licence's term end and run the sweep once."""
    set_clock(api, _SWEEP_CLOCK_AFTER_TERM)
    return validate_success(
        api.run_rights_sweep(production_id, CLEARANCE_SUPERVISOR), 200)


def _setup_delivered_fair_use_production(api) -> Dict[str, Any]:
    """A delivered production whose only asset is CLEARED on a FAIR_USE basis.

    The asset has no licence at all, so the accepted analysis — and behind it the one
    ISSUED opinion letter — is the entire basis of its clearance.
    """
    production = create_production_in_clearance(api, title="Opinion Chain",
                                                delivery_deadline_date="2027-07-31")
    asset = create_asset(api, production["id"], title="Contested newsreel",
                         timecode_in_seconds=0, timecode_out_seconds=20,
                         usage_purpose="CRITICAL_COMMENTARY")
    analysis, letter = clear_asset_via_fair_use(api, asset["id"], LEGAL_COUNSEL)
    chart = pin_chart(api, production["id"], "v1 fair-use")
    eo = place_bound_eo_cover(api, production["id"], chart["id"], "EO-2026-91")
    package = open_delivery_package(api, production["id"], chart["id"])
    validate_delivery_package(api, package["id"])
    package = deliver_delivery_package(api, package["id"])
    return {
        "production": get_production(api, production["id"]),
        "asset": get_asset(api, asset["id"]),
        "analysis": analysis,
        "opinion_letter": letter,
        "chart": get_chart(api, chart["id"]),
        "eo_application": eo,
        "delivery_package": package,
    }


def _withdraw_letter(api, letter_id: str) -> Dict[str, Any]:
    return drive_opinion_letter(
        api, letter_id, "WITHDRAWN", LEGAL_COUNSEL,
        withdrawal_reason="New provenance evidence undermines factor four")


# ─── rights_sweep_expiry_cascades_five_hops_to_eo_remediation ─────────────────


def test_sweep_activates_then_expires_the_same_licence_in_one_request(api):
    """PRD §3.8: "This step re-reads the status set that step one has just produced, so
    a licence whose entire term has already elapsed can activate and expire inside a
    single sweep."

    Design: Difficulty/transitive_cascade/rights_sweep_expiry_cascades_five_hops_to_eo_remediation
    """
    scenario = _setup_locked_delivered_production(api)
    _assert_sweep_pre_state(api, scenario)
    license_id = scenario["license"]["id"]

    report = _run_sweep_past_term_end(api, scenario["production"]["id"])

    assert report["sweep_epoch"] == 1
    assert report["activated_license_ids"] == [license_id]
    assert report["expired_license_ids"] == [license_id]
    assert report["expiring_license_ids"] == []
    assert get_license(api, license_id)["status"] == "EXPIRED"
    assert get_production(api, scenario["production"]["id"])["sweep_epoch"] == 1


def test_expired_licence_lapses_the_asset_and_blocks_the_posture(api):
    """PRD §3.8: "(a) The clearance rollup runs for every asset touched by steps one
    through three, which is where a licence's expiry becomes an asset's loss of
    coverage: an asset whose covered-leg set has emptied moves `CLEARED → LAPSED` with
    `lapse_count` raised by one, while a music asset that lost one leg while the other
    stayed live moves `CLEARED → PARTIALLY_CLEARED`, also raising `lapse_count` by one
    and resetting `rights_basis` to `UNDETERMINED`; both moves adjust
    `cleared_asset_count` down and `open_asset_count` up and flip pinning charts to
    `STALE`."

    Design: Difficulty/transitive_cascade/rights_sweep_expiry_cascades_five_hops_to_eo_remediation
    """
    scenario = _setup_locked_delivered_production(api)
    asset_id = scenario["asset"]["id"]

    report = _run_sweep_past_term_end(api, scenario["production"]["id"])

    assert report["lapsed_asset_ids"] == [asset_id]
    asset = get_asset(api, asset_id)
    assert_asset_dimensions(asset, "LAPSED", depiction_status="NOT_REQUIRED",
                            rights_basis="UNDETERMINED", lapse_count=1)

    production = get_production(api, scenario["production"]["id"])
    assert_production_counters(production, asset_count=1, cleared_asset_count=0,
                               open_asset_count=1)
    assert_posture(production, "BLOCKED")
    assert report["production_posture"] == "BLOCKED"


def test_blocked_posture_suspends_the_delivered_package(api):
    """PRD §3.8: "(c) If the recomputed posture is `BLOCKED`, every delivery package of
    the production sitting in `DELIVERED` moves `DELIVERED → SUSPENDED`, in ascending
    `created_at` order, each stamping `suspension_reason` with the text `AUTO: production
    posture BLOCKED at sweep epoch <n>` where the placeholder is the sweep epoch just
    reached."

    Design: Difficulty/transitive_cascade/rights_sweep_expiry_cascades_five_hops_to_eo_remediation
    """
    scenario = _setup_locked_delivered_production(api)
    package_id = scenario["delivery_package"]["id"]

    report = _run_sweep_past_term_end(api, scenario["production"]["id"])

    assert report["suspended_delivery_package_ids"] == [package_id]
    package = get_delivery_package(api, package_id)
    assert package["status"] == "SUSPENDED"
    assert package["suspension_reason"] == auto_suspension_reason(1)


def test_suspended_package_pushes_the_bound_eo_into_remediation(api):
    """PRD §3.8: "(d) For every package just suspended, every E&O application of the
    production sitting in `BOUND` moves `BOUND → REMEDIATION_REQUIRED`."

    Design: Difficulty/transitive_cascade/rights_sweep_expiry_cascades_five_hops_to_eo_remediation
    """
    scenario = _setup_locked_delivered_production(api)
    eo_id = scenario["eo_application"]["id"]

    report = _run_sweep_past_term_end(api, scenario["production"]["id"])

    assert report["remediated_eo_application_ids"] == [eo_id]
    eo = get_success_data(api.get_eo_application(eo_id, CLEARANCE_SUPERVISOR))
    assert eo["status"] == "REMEDIATION_REQUIRED"
    assert eo["policy_number"] == "EO-2026-77"
    assert eo["legal_review_status"] == "PASSED"
    assert eo["underwriting_review_status"] == "PASSED"


def test_sweep_reverts_the_locked_production_and_stales_the_pinned_chart(api):
    """PRD §3.8: "(e) If the production's `status` is `LOCKED` and the recomputed posture
    is anything other than `OPEN`, the production moves `LOCKED → CLEARANCE`,
    incrementing its own `version` — a locked film that has lost coverage is pushed back
    into clearance work rather than being allowed to ship."

    Design: Difficulty/transitive_cascade/rights_sweep_expiry_cascades_five_hops_to_eo_remediation
    """
    scenario = _setup_locked_delivered_production(api)
    chart_id = scenario["chart"]["id"]
    production_before = get_production(api, scenario["production"]["id"])

    _run_sweep_past_term_end(api, scenario["production"]["id"])

    production = get_production(api, scenario["production"]["id"])
    assert production["status"] == "CLEARANCE"
    assert production["version"] > production_before["version"]
    # PRD §2.10: whenever the version of any asset named in a chart's pinned rows
    # advances — for any reason at all — a chart in PINNED moves to STALE.
    assert get_chart(api, chart_id)["status"] == "STALE"


def test_sweep_debits_the_money_ledger_by_the_expired_executed_fee(api):
    """PRD §3.8: "Every licence in `ACTIVE` or `EXPIRING` whose `term_end_date` is on or
    before the clock's date — recall the half-open term of §2.11, so a clock date equal
    to `term_end_date` has already expired — moves to `EXPIRED`, the production's
    `committed_fee_cents` is debited by that licence's `executed_fee_cents`, and its
    `version` increments."

    Design: Difficulty/transitive_cascade/rights_sweep_expiry_cascades_five_hops_to_eo_remediation
    """
    scenario = _setup_locked_delivered_production(api)
    production_id = scenario["production"]["id"]
    assert get_production(api, production_id)["committed_fee_cents"] == \
        _TWELVE_MONTH_FEE_CENTS

    report = _run_sweep_past_term_end(api, production_id)

    assert report["committed_fee_cents"] == 0
    assert get_production(api, production_id)["committed_fee_cents"] == 0
    assert get_license(api, scenario["license"]["id"])["executed_fee_cents"] == \
        _TWELVE_MONTH_FEE_CENTS
    assert_license_money_ledger(api, production_id, CLEARANCE_SUPERVISOR)


# ─── opinion_letter_withdrawal_cascades_five_hops_from_legal_opinion ───────────


def test_fair_use_chart_is_rated_and_bound_before_any_withdrawal(api):
    """PRD §3.7: "The base premium is the requested `coverage_limit_cents` multiplied by
    a base rate of 1.25 percent — that is, 0.0125 — and rounded half up to an integer
    number of cents." Each rated row contributes 0.045 for `FAIR_USE`, and "A retention
    credit is computed as `retention_cents` multiplied by 0.30 — a 30 percent credit for
    self-insurance — rounded half up once."

    Design: Difficulty/transitive_cascade/opinion_letter_withdrawal_cascades_five_hops_from_legal_opinion
    """
    scenario = _setup_delivered_fair_use_production(api)

    eo = get_success_data(
        api.get_eo_application(scenario["eo_application"]["id"], CLEARANCE_SUPERVISOR))
    assert eo["status"] == "BOUND"
    # 4000000 x 0.0125 = 50000 base, plus 4000000 x 0.045 = 180000 for the single
    # CLEARED FAIR_USE row, less 100000 x 0.30 = 30000 of retention credit.
    assert eo["premium_cents"] == 200000

    chart = get_chart(api, scenario["chart"]["id"])
    assert chart["status"] == "PINNED"
    assert chart["pinned_row_count"] == 1
    assert chart["pinned_rows"][0]["rights_basis"] == "FAIR_USE"
    assert chart["pinned_opinion_letter_ids"] == [scenario["opinion_letter"]["id"]]
    assert get_delivery_package(api, scenario["delivery_package"]["id"])["status"] == \
        "DELIVERED"
    assert_asset_dimensions(get_asset(api, scenario["asset"]["id"]), "CLEARED",
                            rights_basis="FAIR_USE", lapse_count=0)


def test_withdrawing_the_last_issued_letter_rejects_the_analysis(api):
    """PRD §3.5: "(1) if that was the last letter in `ISSUED` on its analysis — the count
    of `ISSUED` letters for the analysis having dropped to zero — the analysis moves
    `ACCEPTED → REJECTED` with `decision_rationale` set to the exact text `AUTO:
    supporting opinion letter withdrawn` and its `version` incremented".

    Design: Difficulty/transitive_cascade/opinion_letter_withdrawal_cascades_five_hops_from_legal_opinion
    """
    scenario = _setup_delivered_fair_use_production(api)

    response = api.set_opinion_letter_state(
        scenario["opinion_letter"]["id"],
        {"to_status": "WITHDRAWN",
         "withdrawal_reason": "New provenance evidence undermines factor four"},
        LEGAL_COUNSEL)
    letter = validate_success(response, 200)
    assert letter["status"] == "WITHDRAWN"
    assert letter["withdrawal_reason"] == \
        "New provenance evidence undermines factor four"

    analysis = get_success_data(
        api.get_fair_use_analysis(scenario["analysis"]["id"], LEGAL_COUNSEL))
    assert analysis["status"] == "REJECTED"
    assert analysis["decision_rationale"] == AUTO_WITHDRAWAL_RATIONALE
    # PRD §3.5: factor scores of 90, 60, 40 and 50 score 0.6750 under the
    # transformative weighting — the score was never the reason for the rejection.
    assert analysis["strength_score"] == 0.6750
    assert analysis["weighting_variant"] == "TRANSFORMATIVE_WEIGHTED"


def test_rejected_analysis_lapses_the_asset_off_its_fair_use_basis(api):
    """PRD §3.5: "(2) that rejection re-runs the clearance rollup on the asset, which no
    longer finds an `ACCEPTED` analysis and therefore recomputes the rights basis away
    from `FAIR_USE` — an asset with no covered legs at all moves `CLEARED → LAPSED` with
    `lapse_count` increased by one, while an asset that still holds part of its coverage
    lands on `PARTIALLY_CLEARED` and one that holds none and has never lapsed lands on
    `UNCLEARED`".

    Design: Difficulty/transitive_cascade/opinion_letter_withdrawal_cascades_five_hops_from_legal_opinion
    """
    scenario = _setup_delivered_fair_use_production(api)

    _withdraw_letter(api, scenario["opinion_letter"]["id"])

    asset = get_asset(api, scenario["asset"]["id"])
    assert_asset_dimensions(asset, "LAPSED", depiction_status="NOT_REQUIRED",
                            rights_basis="UNDETERMINED", lapse_count=1)
    assert asset["version"] > scenario["asset"]["version"]


def test_withdrawal_restores_the_asset_counters_and_blocks_the_posture(api):
    """PRD §3.5: "(3) the production's `cleared_asset_count` and `open_asset_count` are
    restored to their pre-issue values and its posture is recomputed, which for a lapsed
    asset forces `BLOCKED`".

    Design: Difficulty/transitive_cascade/opinion_letter_withdrawal_cascades_five_hops_from_legal_opinion
    """
    scenario = _setup_delivered_fair_use_production(api)
    production_id = scenario["production"]["id"]
    assert_production_counters(get_production(api, production_id), asset_count=1,
                               cleared_asset_count=1, open_asset_count=0)

    _withdraw_letter(api, scenario["opinion_letter"]["id"])

    production = get_production(api, production_id)
    assert_production_counters(production, asset_count=1, cleared_asset_count=0,
                               open_asset_count=1)
    assert_posture(production, "BLOCKED")


def test_withdrawal_suspends_the_delivered_package_and_remediates_the_bound_eo(api):
    """PRD §3.5: "(4) every delivery package of the production sitting in `DELIVERED`
    moves `DELIVERED → SUSPENDED` with its `suspension_reason` stamped; and (5) every
    E&O application of the production sitting in `BOUND` moves `BOUND →
    REMEDIATION_REQUIRED`."

    Design: Difficulty/transitive_cascade/opinion_letter_withdrawal_cascades_five_hops_from_legal_opinion
    """
    scenario = _setup_delivered_fair_use_production(api)

    _withdraw_letter(api, scenario["opinion_letter"]["id"])

    package = get_delivery_package(api, scenario["delivery_package"]["id"])
    assert package["status"] == "SUSPENDED"
    assert package["suspension_reason"] is not None

    eo = get_success_data(
        api.get_eo_application(scenario["eo_application"]["id"], PRODUCTION_ADMIN))
    assert eo["status"] == "REMEDIATION_REQUIRED"
    assert eo["policy_number"] == "EO-2026-91"
    assert eo["premium_cents"] == 200000


def test_withdrawal_stales_the_chart_without_rewriting_its_snapshot(api):
    """PRD §3.5: "Every `PINNED` chart pinning the affected asset flips to `STALE` along
    the way, and the letter's, analysis's, asset's and production's `version` values all
    advance within the single request."

    Design: Difficulty/transitive_cascade/opinion_letter_withdrawal_cascades_five_hops_from_legal_opinion
    """
    scenario = _setup_delivered_fair_use_production(api)
    letter_id = scenario["opinion_letter"]["id"]

    _withdraw_letter(api, letter_id)

    chart = get_chart(api, scenario["chart"]["id"])
    assert chart["status"] == "STALE"
    assert chart["pinned_opinion_letter_ids"] == [letter_id]
    assert chart["pinned_rows"][0]["rights_basis"] == "FAIR_USE"
    assert chart["pinned_rows"][0]["asset_id"] == scenario["asset"]["id"]

    # PRD §2.9: no licence ever existed on this production, so the money ledger is
    # untouched by the cascade.
    production = get_production(api, scenario["production"]["id"])
    assert production["committed_fee_cents"] == 0
    assert_license_money_ledger(api, production["id"], CLEARANCE_SUPERVISOR)
