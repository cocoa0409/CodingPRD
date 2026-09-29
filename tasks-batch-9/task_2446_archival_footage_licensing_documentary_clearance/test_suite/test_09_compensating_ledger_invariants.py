"""Conserved quantities across a cascade and its exact compensating action.

The first scenario runs a most-favored-nations top-up and then unwinds both legs,
proving the debit uses the current binding fee rather than the negotiated one. The
second walks the reverse direction: a lapse is cured and the insurance is re-bound
without re-rating, while the scars the cascade left behind stay exactly as they are.
"""
from test_helpers import (
    CLEARANCE_SUPERVISOR,
    CLEARANCE_SUPERVISOR_USER_ID,
    PRODUCTION_ADMIN,
    REVIEWING_COUNSEL_USER_ID,
    assert_asset_dimensions,
    assert_license_money_ledger,
    assert_posture,
    assert_production_counters,
    auto_suspension_reason,
    create_and_execute_license,
    create_archive_with_rate_card,
    create_music_asset,
    create_production_in_clearance,
    get_asset,
    get_chart,
    get_delivery_package,
    get_license,
    get_production,
    rebind_eo_application,
    run_sweep,
    set_clock,
    setup_delivered_production,
    state_payload,
    terminate_license,
    validate_error,
    validate_success,
)

# A 60-second MUSIC asset bills two units and sits in duration tier 2 (1.25).
# MASTER on the label's card:     10000 * 2 * 1.25 * 1.15 * 1.00 * 1.00 =  28750
# PUBLISHING on the publisher's:  20000 * 2 * 1.25 * 1.15 * 1.00 * 1.00 =  57500
MASTER_BASE_FEE_CENTS = 28750
PUBLISHING_FEE_CENTS = 57500
PARITY_FEE_CENTS = 57500
MASTER_TOPUP_CENTS = 28750

# A 45-second BROADCAST / WORLD / 12-month all-media licence on the standard card.
TWELVE_MONTH_FEE_CENTS = 258750

# PRD §3.7 rating of one CLEARED / LICENSED row against a 4000000-cent limit with a
# 100000-cent retention: 50000 base + 40000 loading - 30000 retention credit.
EXPECTED_PREMIUM_CENTS = 60000


def _setup_music_asset_with_both_mfn_legs_executed(api):
    """Both legs of one music cue executed with parity, MASTER first then PUBLISHING."""
    production = create_production_in_clearance(api, title="Parity Ledger",
                                                delivery_deadline_date="2027-12-15")
    label, _label_card = create_archive_with_rate_card(
        api,
        archive_overrides={"name": "Harmony Masters", "holder_type": "RECORD_LABEL"},
        card_overrides={"base_rate_per_30s_cents": 10000, "minimum_fee_cents": 20000,
                        "festival_minimum_fee_cents": 10000})
    publisher, _publisher_card = create_archive_with_rate_card(
        api,
        archive_overrides={"name": "Ash Grove Music", "holder_type": "MUSIC_PUBLISHER"},
        card_overrides={"base_rate_per_30s_cents": 20000, "minimum_fee_cents": 20000,
                        "festival_minimum_fee_cents": 10000})
    asset = create_music_asset(api, production["id"], title="Reel to reel theme",
                               timecode_in_seconds=0, timecode_out_seconds=60,
                               usage_purpose="ILLUSTRATIVE_BACKGROUND")
    master = create_and_execute_license(
        api, production["id"], asset["id"], label["id"], MASTER_BASE_FEE_CENTS,
        rights_leg="MASTER", media="BROADCAST", territory="DOMESTIC",
        window_class="ALL_MEDIA_WINDOW", term_months=12,
        term_start_date="2026-08-15", term_end_date="2027-08-15", mfn_requested=True)
    publishing = create_and_execute_license(
        api, production["id"], asset["id"], publisher["id"], PUBLISHING_FEE_CENTS,
        rights_leg="PUBLISHING", media="BROADCAST", territory="DOMESTIC",
        window_class="ALL_MEDIA_WINDOW", term_months=12,
        term_start_date="2026-08-15", term_end_date="2027-08-15", mfn_requested=True)
    return {
        "production": production,
        "label": label,
        "publisher": publisher,
        "asset": asset,
        "master_license": get_license(api, master["id"]),
        "publishing_license": publishing,
    }


def _setup_remediation_required_after_expiry_sweep(api):
    """A swept-out production: licence EXPIRED, asset LAPSED, package SUSPENDED and
    the bound E&O application pushed into REMEDIATION_REQUIRED."""
    scenario = setup_delivered_production(
        api, policy_number="EO-2026-77",
        license_overrides={"term_months": 12, "term_end_date": "2027-08-15"})
    set_clock(api, "2027-08-20T00:00:00Z")
    scenario["sweep"] = run_sweep(api, scenario["production"]["id"])
    scenario["production"] = get_production(api, scenario["production"]["id"])
    return scenario


def _eo_application_of(api, scenario):
    return validate_success(
        api.get_eo_application(scenario["eo_application"]["id"], CLEARANCE_SUPERVISOR))


def _execute_replacement_license(api, scenario):
    """A fresh 12-month term from the same holder, curing the asset's lapse."""
    return create_and_execute_license(
        api, scenario["production"]["id"], scenario["asset"]["id"],
        scenario["archive"]["id"], TWELVE_MONTH_FEE_CENTS, term_months=12,
        term_start_date="2027-08-20", term_end_date="2028-08-20")


def test_mfn_settlement_tops_up_the_master_leg_before_any_termination(api):
    """PRD §3.4: "The difference between that target and the peer's current
    `executed_fee_cents` is the top-up: it is added to the peer's `mfn_topup_cents`, the
    peer's `executed_fee_cents` is raised to the target, the peer's `version` increments,
    and the production's `committed_fee_cents` rises by the same top-up amount."

    Design: Difficulty/compensating_invariant/termination_reverses_the_mfn_topup_it_received_leaving_no_ledger_residue
    """
    scenario = _setup_music_asset_with_both_mfn_legs_executed(api)

    master = get_license(api, scenario["master_license"]["id"])
    assert master["executed_fee_cents"] == PARITY_FEE_CENTS
    assert master["mfn_topup_cents"] == MASTER_TOPUP_CENTS

    publishing = get_license(api, scenario["publishing_license"]["id"])
    assert publishing["executed_fee_cents"] == PUBLISHING_FEE_CENTS
    assert publishing["mfn_topup_cents"] == 0

    production = get_production(api, scenario["production"]["id"])
    assert production["committed_fee_cents"] == PARITY_FEE_CENTS + PUBLISHING_FEE_CENTS
    assert_production_counters(production, asset_count=1, cleared_asset_count=1,
                               open_asset_count=0)
    assert_asset_dimensions(get_asset(api, scenario["asset"]["id"]),
                            licensing_status="CLEARED", rights_basis="LICENSED",
                            lapse_count=0)
    assert_license_money_ledger(api, production["id"], CLEARANCE_SUPERVISOR)


def test_terminating_the_publishing_leg_debits_its_full_executed_fee(api):
    """PRD §3.4: "From `EXECUTED`, `ACTIVE` or `EXPIRING`, a `ClearanceSupervisor` may move
    the licence to `TERMINATED`; the supplied `reason` is stored as `termination_reason`,
    the production's `committed_fee_cents` is debited by exactly this licence's
    `executed_fee_cents` — which necessarily includes any `mfn_topup_cents` this licence
    had received, so the compensation is exact — the asset's `licensing_status` is
    recomputed, and the licence's `version` increments."

    Design: Difficulty/compensating_invariant/termination_reverses_the_mfn_topup_it_received_leaving_no_ledger_residue
    """
    scenario = _setup_music_asset_with_both_mfn_legs_executed(api)

    terminated = terminate_license(api, scenario["publishing_license"]["id"],
                                   reason="Publisher rescinded")
    assert terminated["status"] == "TERMINATED"
    assert terminated["termination_reason"] == "Publisher rescinded"

    production = get_production(api, scenario["production"]["id"])
    assert production["committed_fee_cents"] == PARITY_FEE_CENTS
    assert_production_counters(production, asset_count=1, cleared_asset_count=0,
                               open_asset_count=1)
    assert_posture(production, "BLOCKED")
    assert_asset_dimensions(get_asset(api, scenario["asset"]["id"]),
                            licensing_status="PARTIALLY_CLEARED",
                            rights_basis="UNDETERMINED", lapse_count=1)
    assert_license_money_ledger(api, production["id"], CLEARANCE_SUPERVISOR)


def test_terminating_the_topped_up_master_leg_returns_the_ledger_to_zero(api):
    """PRD §2.9: "The consequence to test against is exact reversibility: executing a
    licence and then terminating it must return `committed_fee_cents` to its precise
    pre-execution value, with no residue from any rounding, including any top-up that
    licence had received."

    Design: Difficulty/compensating_invariant/termination_reverses_the_mfn_topup_it_received_leaving_no_ledger_residue
    """
    scenario = _setup_music_asset_with_both_mfn_legs_executed(api)

    terminate_license(api, scenario["publishing_license"]["id"], reason="Publisher rescinded")
    master = terminate_license(api, scenario["master_license"]["id"],
                               reason="Cue dropped from the cut")
    assert master["status"] == "TERMINATED"
    assert master["executed_fee_cents"] == PARITY_FEE_CENTS
    assert master["mfn_topup_cents"] == MASTER_TOPUP_CENTS

    production = get_production(api, scenario["production"]["id"])
    assert production["committed_fee_cents"] == 0
    assert_production_counters(production, asset_count=1, cleared_asset_count=0,
                               open_asset_count=1)
    assert_posture(production, "BLOCKED")
    assert_asset_dimensions(get_asset(api, scenario["asset"]["id"]),
                            licensing_status="LAPSED", rights_basis="UNDETERMINED",
                            lapse_count=1)
    assert_license_money_ledger(api, production["id"], CLEARANCE_SUPERVISOR)


def test_rebind_refused_while_the_posture_is_still_blocked(api):
    """PRD §3.7: "Binding out of `REMEDIATION_REQUIRED` is the cycle back into cover after
    a lapse has been cured: it demands that the production's `posture` has returned to
    `OPEN`, refusing anything else with `ERR_PRODUCTION_POSTURE_BLOCKED`, and it
    deliberately retains the existing `premium_cents` and both review statuses rather than
    re-rating the policy."

    Design: Difficulty/compensating_invariant/eo_rebind_after_cure_restores_coverage_without_re_rating_or_double_counting
    """
    scenario = _setup_remediation_required_after_expiry_sweep(api)

    assert_posture(scenario["production"], "BLOCKED")
    assert scenario["production"]["committed_fee_cents"] == 0
    application = _eo_application_of(api, scenario)
    assert application["status"] == "REMEDIATION_REQUIRED"
    assert application["premium_cents"] == EXPECTED_PREMIUM_CENTS

    response = api.set_eo_application_state(application["id"], state_payload("BOUND"),
                                            PRODUCTION_ADMIN)
    validate_error(response, "ERR_PRODUCTION_POSTURE_BLOCKED")

    refused = _eo_application_of(api, scenario)
    assert refused["status"] == "REMEDIATION_REQUIRED"
    assert refused["premium_cents"] == EXPECTED_PREMIUM_CENTS
    assert refused["policy_number"] == "EO-2026-77"


def test_replacement_license_cures_the_lapse_without_double_counting(api):
    """PRD §3.4: "And executing a replacement licence for an asset that had lost its
    coverage moves it `LAPSED → CLEARED`, again setting `rights_basis` to `LICENSED` and
    restoring the counters, while `lapse_count` keeps its historical value."

    Design: Difficulty/compensating_invariant/eo_rebind_after_cure_restores_coverage_without_re_rating_or_double_counting
    """
    scenario = _setup_remediation_required_after_expiry_sweep(api)
    assert_asset_dimensions(get_asset(api, scenario["asset"]["id"]),
                            licensing_status="LAPSED", rights_basis="UNDETERMINED",
                            lapse_count=1)

    replacement = _execute_replacement_license(api, scenario)
    assert replacement["status"] == "EXECUTED"
    assert replacement["executed_fee_cents"] == TWELVE_MONTH_FEE_CENTS

    assert_asset_dimensions(get_asset(api, scenario["asset"]["id"]),
                            licensing_status="CLEARED", rights_basis="LICENSED",
                            lapse_count=1)
    production = get_production(api, scenario["production"]["id"])
    assert_posture(production, "OPEN")
    assert_production_counters(production, asset_count=1, cleared_asset_count=1,
                               open_asset_count=0)
    assert production["committed_fee_cents"] == TWELVE_MONTH_FEE_CENTS
    assert get_license(api, scenario["license"]["id"])["status"] == "EXPIRED"
    assert_license_money_ledger(api, production["id"], CLEARANCE_SUPERVISOR)


def test_rebind_after_cure_retains_the_premium_and_both_reviewer_identities(api):
    """PRD §3.7: "Binding out of `REMEDIATION_REQUIRED` is the cycle back into cover after
    a lapse has been cured: it demands that the production's `posture` has returned to
    `OPEN`, refusing anything else with `ERR_PRODUCTION_POSTURE_BLOCKED`, and it
    deliberately retains the existing `premium_cents` and both review statuses rather than
    re-rating the policy."

    Design: Difficulty/compensating_invariant/eo_rebind_after_cure_restores_coverage_without_re_rating_or_double_counting
    """
    scenario = _setup_remediation_required_after_expiry_sweep(api)
    _execute_replacement_license(api, scenario)

    rebound = rebind_eo_application(api, scenario["eo_application"]["id"])
    assert rebound["status"] == "BOUND"
    assert rebound["premium_cents"] == EXPECTED_PREMIUM_CENTS
    assert rebound["legal_review_status"] == "PASSED"
    assert rebound["underwriting_review_status"] == "PASSED"
    assert rebound["legal_reviewer_user_id"] == REVIEWING_COUNSEL_USER_ID
    assert rebound["underwriting_reviewer_user_id"] == CLEARANCE_SUPERVISOR_USER_ID
    assert rebound["policy_number"] == "EO-2026-77"

    reread = _eo_application_of(api, scenario)
    assert reread["status"] == "BOUND"
    assert reread["premium_cents"] == EXPECTED_PREMIUM_CENTS


def test_rebind_leaves_the_suspended_package_and_the_stale_chart_untouched(api):
    """PRD §3.8: "The move `DELIVERED → SUSPENDED` is never requestable through the state
    endpoint: it is driven only by the system, either from the rights sweep or from the
    opinion-letter withdrawal cascade, and an operator request for it is refused with
    `ERR_INVALID_STATE_TRANSITION`." PRD §2.10: "Pinning a fresh chart on the same
    production moves every earlier chart of that production, whether it was `PINNED` or
    already `STALE`, to `SUPERSEDED`".

    Design: Difficulty/compensating_invariant/eo_rebind_after_cure_restores_coverage_without_re_rating_or_double_counting
    """
    scenario = _setup_remediation_required_after_expiry_sweep(api)
    sweep_epoch = scenario["sweep"]["sweep_epoch"]

    _execute_replacement_license(api, scenario)
    rebind_eo_application(api, scenario["eo_application"]["id"])

    package = get_delivery_package(api, scenario["delivery_package"]["id"])
    assert package["status"] == "SUSPENDED"
    assert package["suspension_reason"] == auto_suspension_reason(sweep_epoch)

    assert get_chart(api, scenario["chart"]["id"])["status"] == "STALE"
    assert_asset_dimensions(get_asset(api, scenario["asset"]["id"]),
                            licensing_status="CLEARED", lapse_count=1)
