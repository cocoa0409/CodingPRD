"""Response intake/review and incentive award administration: quality flags,
pinned rounding order, award cap, parallel state dimensions, pool conservation."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_cell, create_panelist, create_locked_instrument, create_fielding_wave,
    dispatch_invitation, submit_response, accept_response, get_award_for_response,
    create_response_payload, assert_pool_conservation,
)

PM = TEST_USERS["panel_manager"]
DA = TEST_USERS["data_analyst"]
IC = TEST_USERS["incentive_clerk"]


def _fielding_with_panelist(locale="en", target_size=5, **wave_kw):
    cell = create_cell(target_size=target_size)
    p = create_panelist(preferred_locale=locale)
    enrolled = validate_success(api_enroll(p["id"]), 200)
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"], **wave_kw)
    return cell, enrolled, instr, wave


from test_helpers import api_client as _api


def api_enroll(pid):
    return _api.enroll_panelist(pid, PM)


def test_incentive_amount_per_component_rounding_order(api):
    """PRD §3.6: "First, the completion bonus is the wave's `base_incentive_cents`
    multiplied by `completeness_pct` and divided by 100, rounded half-up to whole
    cents. Second, a locale bonus of ten percent of `base_incentive_cents`,
    likewise rounded half-up, applies when the panelist's `preferred_locale` is
    anything other than `en` ... Fourth, when `speeder_flag` is set the subtotal is
    halved with round-half-up rounding. ... The order is load-bearing: rounding
    each component before summing yields different cents than summing the unrounded
    components whenever the completion or locale bonus lands on a half-cent
    boundary, and the pinned per-component order wins."

    Design: Difficulty/combinatorial_formula/incentive_amount_per_component_rounding_order
    """
    # base 105, completeness 50 -> completion bonus round_half_up(52.5) == 53;
    # locale es -> round_half_up(10.5) == 11; subtotal 105+53+11 == 169;
    # speeder (60s < 120s) -> round_half_up(169/2) == round_half_up(84.5) == 85.
    cell, p1, instr, wave = _fielding_with_panelist(locale="es",
                                                    base_incentive_cents=105)
    inv = dispatch_invitation(wave["id"], p1["id"])
    resp = submit_response(inv["id"], completeness_pct=50, completion_seconds=60)
    assert resp["speeder_flag"] is True
    award = get_award_for_response(resp["id"])
    assert award["amount_cents"] == 85
    assert award["eligibility_status"] == "PENDING"
    assert award["payout_status"] == "UNPAID"


def test_incentive_amount_english_locale_gets_no_locale_bonus(api):
    """PRD §3.6: "Second, a locale bonus of ten percent of `base_incentive_cents`,
    likewise rounded half-up, applies when the panelist's `preferred_locale` is
    anything other than `en`; an English-locale panelist receives zero here."

    Design: Difficulty/combinatorial_formula/incentive_amount_per_component_rounding_order
    """
    # base 105, completeness 50, locale en -> 105 + 53 + 0 = 158; no speeder (300s).
    cell, p1, instr, wave = _fielding_with_panelist(locale="en",
                                                    base_incentive_cents=105)
    inv = dispatch_invitation(wave["id"], p1["id"])
    resp = submit_response(inv["id"], completeness_pct=50, completion_seconds=300)
    assert resp["speeder_flag"] is False
    award = get_award_for_response(resp["id"])
    assert award["amount_cents"] == 158


def test_incentive_cap_applies_at_max(api):
    """PRD §3.6: "Fifth, the amount is the subtotal capped at 10,000 cents — one
    hundred dollars per response at most."

    Design: Corner/calculations/corner_incentive_cap_applies_at_max
    """
    # 9000 + 9000 (100% completion) + 900 (es locale) = 18900 -> clamped to 10000.
    cell, p1, instr, wave = _fielding_with_panelist(
        locale="es", base_incentive_cents=9000, incentive_pool_total_cents=1000000)
    inv = dispatch_invitation(wave["id"], p1["id"])
    resp = submit_response(inv["id"], completeness_pct=100, completion_seconds=300)
    award = get_award_for_response(resp["id"])
    assert award["amount_cents"] == 10000


def test_speeder_flag_boundary_and_halving(api):
    """PRD §3.6: "`speeder_flag` is true when `completion_seconds` is under 120" and
    "Fourth, when `speeder_flag` is set the subtotal is halved with round-half-up
    rounding."

    Design: Corner/calculations/corner_speeder_flag_boundary_and_halving
    """
    cell = create_cell(target_size=5)
    p1 = validate_success(api_enroll(create_panelist()["id"]), 200)
    p2 = validate_success(api_enroll(create_panelist()["id"]), 200)
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"], base_incentive_cents=1000)
    inv1 = dispatch_invitation(wave["id"], p1["id"])
    inv2 = dispatch_invitation(wave["id"], p2["id"])

    r1 = submit_response(inv1["id"], completeness_pct=100, completion_seconds=119)
    r2 = submit_response(inv2["id"], completeness_pct=100, completion_seconds=120)
    assert r1["speeder_flag"] is True
    assert r2["speeder_flag"] is False
    a1 = get_award_for_response(r1["id"])
    a2 = get_award_for_response(r2["id"])
    assert a1["amount_cents"] == 1000   # 2000 subtotal halved
    assert a2["amount_cents"] == 2000   # base 1000 + 1000 completion bonus


def test_incentive_award_parallel_dimensions_independent(api):
    """PRD §3.6: "Authorization requires the award's `eligibility_status` to be
    `ELIGIBLE` and its `payout_status` to be `UNPAID` — otherwise
    `ERR_AWARD_NOT_AUTHORIZED_STATE`" and "Forfeiting also requires `AUTHORIZED`
    (else `ERR_AWARD_NOT_FORFEIT_STATE`)" and "Once eligibility reaches
    `INELIGIBLE`, or payout reaches `PAID` or `FORFEITED`, that dimension of the
    award is closed."

    Design: Difficulty/non_linear_state_machine/incentive_award_parallel_dimensions_independent
    """
    cell, p1, instr, wave = _fielding_with_panelist()
    inv = dispatch_invitation(wave["id"], p1["id"])
    r1 = submit_response(inv["id"], completeness_pct=100, completion_seconds=300)
    award = get_award_for_response(r1["id"])

    # Payout cannot advance while eligibility is PENDING.
    err = validate_error(api.authorize_award(award["id"], IC),
                         ApiErrorId.ERR_AWARD_NOT_AUTHORIZED_STATE)
    assert err["error_id"] == "ERR_AWARD_NOT_AUTHORIZED_STATE"

    # Eligibility moves PENDING -> ELIGIBLE via review without touching payout.
    validate_success(api.quarantine_response(r1["id"], DA), 200)
    validate_success(api.accept_response(r1["id"], DA), 200)
    after_accept = validate_success(api.get_award(award["id"], IC), 200)
    assert after_accept["eligibility_status"] == "ELIGIBLE"
    assert after_accept["payout_status"] == "UNPAID"

    # Payout walks UNPAID -> AUTHORIZED -> PAID while eligibility stays ELIGIBLE.
    after_auth = validate_success(api.authorize_award(award["id"], IC), 200)
    assert after_auth["payout_status"] == "AUTHORIZED"
    assert after_auth["eligibility_status"] == "ELIGIBLE"
    after_pay = validate_success(api.pay_award(award["id"], IC), 200)
    assert after_pay["payout_status"] == "PAID"

    # FORFEITED is unreachable from PAID.
    err2 = validate_error(api.forfeit_award(award["id"], IC),
                          ApiErrorId.ERR_AWARD_NOT_FORFEIT_STATE)
    assert err2["error_id"] == "ERR_AWARD_NOT_FORFEIT_STATE"


def test_award_authorize_rejected_while_quarantined(api):
    """PRD §3.6: "Authorization requires the award's `eligibility_status` to be
    `ELIGIBLE` and its `payout_status` to be `UNPAID` — otherwise
    `ERR_AWARD_NOT_AUTHORIZED_STATE`" and "Quarantining moves `SUBMITTED` →
    `QUARANTINED` with no award effect."

    Design: Difficulty/non_linear_state_machine/incentive_award_parallel_dimensions_independent
    """
    cell, p1, instr, wave = _fielding_with_panelist()
    inv = dispatch_invitation(wave["id"], p1["id"])
    r1 = submit_response(inv["id"], completeness_pct=100, completion_seconds=300)
    award = get_award_for_response(r1["id"])

    validate_success(api.quarantine_response(r1["id"], DA), 200)
    mid = validate_success(api.get_award(award["id"], IC), 200)
    assert mid["eligibility_status"] == "PENDING"
    assert mid["payout_status"] == "UNPAID"
    err = validate_error(api.authorize_award(award["id"], IC),
                         ApiErrorId.ERR_AWARD_NOT_AUTHORIZED_STATE)
    assert err["error_id"] == "ERR_AWARD_NOT_AUTHORIZED_STATE"


def test_incentive_pool_authorize_pay_forfeit_conservation(api):
    """PRD §2.6: "On each survey wave, `incentive_pool_available_cents` is the
    uncommitted remainder of the incentive pool, `incentive_pool_reserved_cents` is
    the sum of award amounts whose payout is currently authorized,
    `incentive_pool_paid_cents` is the sum already paid out ..." and PRD §3.6:
    "on success the amount moves from `incentive_pool_available_cents` into
    `incentive_pool_reserved_cents` and the wave's `version` increments. Paying
    requires `payout_status` `AUTHORIZED` (else `ERR_AWARD_NOT_PAID_STATE`) and
    moves the amount from reserved into `incentive_pool_paid_cents`, again
    incrementing the wave's `version`. Forfeiting also requires `AUTHORIZED` (else
    `ERR_AWARD_NOT_FORFEIT_STATE`) and returns the amount from reserved back to
    available."

    Design: Difficulty/compensating_invariant/incentive_pool_authorize_pay_forfeit_conservation
    """
    cell = create_cell(target_size=10)
    p1 = validate_success(api_enroll(create_panelist()["id"]), 200)
    p2 = validate_success(api_enroll(create_panelist()["id"]), 200)
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"], incentive_pool_total_cents=50000,
                                base_incentive_cents=1000)
    inv1 = dispatch_invitation(wave["id"], p1["id"])
    inv2 = dispatch_invitation(wave["id"], p2["id"])
    r1 = submit_response(inv1["id"])   # 100%/300s -> 2000
    r2 = submit_response(inv2["id"])   # 2000
    accept_response(r1["id"])
    accept_response(r2["id"])
    award1 = get_award_for_response(r1["id"])
    award2 = get_award_for_response(r2["id"])

    validate_success(api.authorize_award(award1["id"], IC), 200)
    w = validate_success(api.get_wave(wave["id"], PM), 200)
    assert (w["incentive_pool_available_cents"], w["incentive_pool_reserved_cents"],
            w["incentive_pool_paid_cents"]) == (48000, 2000, 0)
    assert_pool_conservation(w)

    validate_success(api.authorize_award(award2["id"], IC), 200)
    validate_success(api.pay_award(award1["id"], IC), 200)
    w = validate_success(api.get_wave(wave["id"], PM), 200)
    assert (w["incentive_pool_available_cents"], w["incentive_pool_reserved_cents"],
            w["incentive_pool_paid_cents"]) == (46000, 2000, 2000)
    assert_pool_conservation(w)

    validate_success(api.forfeit_award(award2["id"], IC), 200)
    w = validate_success(api.get_wave(wave["id"], PM), 200)
    assert (w["incentive_pool_available_cents"], w["incentive_pool_reserved_cents"],
            w["incentive_pool_paid_cents"]) == (48000, 0, 2000)
    assert_pool_conservation(w)


def test_pool_conservation_holds_at_mint_and_after_pay(api):
    """PRD §2.6: "On each survey wave, `incentive_pool_available_cents` is the
    uncommitted remainder of the incentive pool, `incentive_pool_reserved_cents` is
    the sum of award amounts whose payout is currently authorized,
    `incentive_pool_paid_cents` is the sum already paid out, ..." and PRD §3.6:
    "The award's `amount_cents` is computed at minting time and never changes
    afterward ..."

    Design: Difficulty/compensating_invariant/incentive_pool_authorize_pay_forfeit_conservation
    """
    cell, p1, instr, wave = _fielding_with_panelist(
        incentive_pool_total_cents=50000, base_incentive_cents=1000)
    inv = dispatch_invitation(wave["id"], p1["id"])
    r1 = submit_response(inv["id"])
    award = get_award_for_response(r1["id"])
    assert award["amount_cents"] == 2000

    # Minting commits nothing: pool still fully available.
    w = validate_success(api.get_wave(wave["id"], PM), 200)
    assert (w["incentive_pool_available_cents"], w["incentive_pool_reserved_cents"],
            w["incentive_pool_paid_cents"]) == (50000, 0, 0)
    assert_pool_conservation(w)

    accept_response(r1["id"])
    validate_success(api.authorize_award(award["id"], IC), 200)
    validate_success(api.pay_award(award["id"], IC), 200)
    w = validate_success(api.get_wave(wave["id"], PM), 200)
    assert (w["incentive_pool_available_cents"], w["incentive_pool_reserved_cents"],
            w["incentive_pool_paid_cents"]) == (48000, 0, 2000)
    assert_pool_conservation(w)
    # amount_cents never changed.
    after = validate_success(api.get_award(award["id"], IC), 200)
    assert after["amount_cents"] == 2000


def test_response_discard_marks_award_ineligible(api):
    """PRD §3.6: "Discarding moves `QUARANTINED` → `DISCARDED` and flips eligibility
    `PENDING` → `INELIGIBLE`." and "Once eligibility reaches `INELIGIBLE`, or
    payout reaches `PAID` or `FORFEITED`, that dimension of the award is closed."

    Design: Corner/state_machines/corner_response_discard_marks_award_ineligible
    """
    cell, p1, instr, wave = _fielding_with_panelist()
    inv = dispatch_invitation(wave["id"], p1["id"])
    r1 = submit_response(inv["id"], completeness_pct=30, completion_seconds=90)
    validate_success(api.quarantine_response(r1["id"], DA), 200)
    award = get_award_for_response(r1["id"])

    discarded = validate_success(api.discard_response(r1["id"], DA), 200)
    assert discarded["status"] == "DISCARDED"
    after = validate_success(api.get_award(award["id"], IC), 200)
    assert after["eligibility_status"] == "INELIGIBLE"
    err = validate_error(api.authorize_award(award["id"], IC),
                         ApiErrorId.ERR_AWARD_NOT_AUTHORIZED_STATE)
    assert err["error_id"] == "ERR_AWARD_NOT_AUTHORIZED_STATE"
    w = validate_success(api.get_wave(wave["id"], PM), 200)
    assert w["incentive_pool_reserved_cents"] == 0


def test_award_pay_before_authorize_returns_409(api):
    """PRD §3.6: "Paying requires `payout_status` `AUTHORIZED` (else
    `ERR_AWARD_NOT_PAID_STATE`) and moves the amount from reserved into
    `incentive_pool_paid_cents`, again incrementing the wave's `version`."

    Design: Corner/errors/corner_award_pay_before_authorize_returns_409
    """
    cell, p1, instr, wave = _fielding_with_panelist()
    inv = dispatch_invitation(wave["id"], p1["id"])
    r1 = submit_response(inv["id"])
    accept_response(r1["id"])
    award = get_award_for_response(r1["id"])
    err = validate_error(api.pay_award(award["id"], IC),
                         ApiErrorId.ERR_AWARD_NOT_PAID_STATE)
    assert err["error_id"] == "ERR_AWARD_NOT_PAID_STATE"
    w = validate_success(api.get_wave(wave["id"], PM), 200)
    assert w["incentive_pool_paid_cents"] == 0


def test_response_accept_twice_returns_409(api):
    """PRD §3.6: "`ACCEPTED` and `DISCARDED` are terminal, and any review action
    from a status that does not permit it — discarding a `SUBMITTED` response,
    accepting a discarded one, or touching a terminal response — is rejected with
    `ERR_RESPONSE_NOT_REVIEWABLE`."

    Design: Corner/errors/corner_response_accept_twice_returns_409
    """
    cell, p1, instr, wave = _fielding_with_panelist()
    inv = dispatch_invitation(wave["id"], p1["id"])
    r1 = submit_response(inv["id"])
    accept_response(r1["id"])
    err = validate_error(api.accept_response(r1["id"], DA),
                         ApiErrorId.ERR_RESPONSE_NOT_REVIEWABLE)
    assert err["error_id"] == "ERR_RESPONSE_NOT_REVIEWABLE"


def test_completeness_range_returns_400(api):
    """PRD §2.8: "Missing required fields, wrong types, enum values outside their
    declared sets, and range violations — `completeness_pct` must lie between 0 and
    100 inclusive, ... — all fail as `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/corner_completeness_range_returns_400
    """
    cell, p1, instr, wave = _fielding_with_panelist()
    inv = dispatch_invitation(wave["id"], p1["id"])
    err = validate_error(api.create_response(
        create_response_payload(inv["id"], completeness_pct=120,
                                completion_seconds=300), PM),
        ApiErrorId.ERR_INVALID_REQUEST)
    assert err["error_id"] == "ERR_INVALID_REQUEST"
    inv_after = validate_success(api.get_invitation(inv["id"], PM), 200)
    assert inv_after["status"] == "SENT"
