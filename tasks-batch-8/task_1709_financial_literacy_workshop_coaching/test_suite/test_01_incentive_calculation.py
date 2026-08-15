"""Session-incentive calculation: earned vs provisional variants and the pinned
round-per-session-line ordering (PRD §3.2, §2.6)."""
import pytest

from test_helpers import (
    api_client,
    create_module,
    create_participant,
    create_certified_coach,
    create_registration,
    create_workshop,
    set_clock,
    validate_success,
)


def _setup_module_coach_participant(admin_headers, module_overrides):
    module = create_module(admin_headers, **module_overrides)
    coach = create_certified_coach(admin_headers)
    participant = create_participant(admin_headers)
    return module, coach, participant


def _attended_90min_scenario(admin_headers, module_overrides):
    """One ATTENDED 90-minute session (2026-08-02) plus one still-REGISTERED
    90-minute session (2026-08-03) for the same participant on the same module."""
    module, coach, participant = _setup_module_coach_participant(
        admin_headers, module_overrides
    )
    w1 = create_workshop(
        module["id"], coach["id"], admin_headers,
        start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T11:30:00Z",
    )
    w2 = create_workshop(
        module["id"], coach["id"], admin_headers,
        start_at="2026-08-03T10:00:00Z", end_at="2026-08-03T11:30:00Z",
    )
    reg1 = create_registration(w1["id"], participant["id"], admin_headers)
    reg2 = create_registration(w2["id"], participant["id"], admin_headers)
    set_clock("2026-08-02T12:00:00Z", admin_headers)
    resp = api_mark_attended(reg1["id"], admin_headers)
    validate_success(resp)
    return module, participant, reg1, reg2


def api_mark_attended(registration_id, headers):
    return api_client.mark_attendance(registration_id, {"outcome": "ATTENDED"}, headers)


def test_incentive_summary_earned_counts_attended_only(api, admin_headers):
    """PRD §3.2: "It reports `earned_cents` — the sum of the per-session lines
    over all `ATTENDED` registrations, plus the `completion_bonus_cents` of each
    module where the participant's attended sessions of that module have reached
    the module's `completion_threshold` (the bonus counts once per module)".

    Design: Difficulty/dual_variant_calc/incentive_earned_vs_provisional_projection
    """
    module, participant, reg1, _reg2 = _attended_90min_scenario(
        admin_headers,
        dict(module_code="BF-101", session_count=4, incentive_cents_per_hour=655,
             completion_bonus_cents=2500, completion_threshold=2),
    )
    summary = validate_success(
        api.get_incentive_summary(participant["id"], admin_headers)
    )
    # One ATTENDED 90-minute session at 655 cents/hr: round_half_up(655 * 1.5) = 983.
    assert summary["earned_cents"] == 983, (
        f"earned_cents must cover the ATTENDED session only; got {summary['earned_cents']}"
    )
    # Only one attended session so far, below the completion_threshold of 2.
    assert summary["completion_bonuses_earned_cents"] == 0


def test_incentive_summary_provisional_projects_registered_and_bonus(api, admin_headers):
    """PRD §3.2: "and `provisional_cents`, a forward-looking projection that adds
    to `earned_cents` the per-session lines for registrations still in `REGISTERED`
    status plus the projected bonus for any module where attended plus registered
    sessions together reach the `completion_threshold` and the bonus has not yet
    been earned."

    Design: Difficulty/dual_variant_calc/incentive_earned_vs_provisional_projection
    """
    module, participant, _reg1, _reg2 = _attended_90min_scenario(
        admin_headers,
        dict(module_code="BF-101", session_count=4, incentive_cents_per_hour=655,
             completion_bonus_cents=2500, completion_threshold=2),
    )
    summary = validate_success(
        api.get_incentive_summary(participant["id"], admin_headers)
    )
    # 983 earned + 983 projected REGISTERED session + 2500 projected bonus = 4466.
    assert summary["provisional_cents"] == 4466, (
        f"provisional_cents must add the REGISTERED line and projected bonus; "
        f"got {summary['provisional_cents']}"
    )
    assert summary["earned_cents"] != summary["provisional_cents"]


def _two_attended_90min_scenario(admin_headers, module_overrides):
    """Two ATTENDED 90-minute sessions (2026-08-02 and 2026-08-03)."""
    module, coach, participant = _setup_module_coach_participant(
        admin_headers, module_overrides
    )
    regs = []
    for day in ("2026-08-02", "2026-08-03"):
        w = create_workshop(
            module["id"], coach["id"], admin_headers,
            start_at=f"{day}T10:00:00Z", end_at=f"{day}T11:30:00Z",
        )
        regs.append(create_registration(w["id"], participant["id"], admin_headers))
    set_clock("2026-08-04T00:00:00Z", admin_headers)
    for r in regs:
        validate_success(api_mark_attended(r["id"], admin_headers))
    return module, participant, regs


def test_attended_mark_sets_per_session_line_rounded_half_up(api, admin_headers):
    """PRD §3.2: "An `ATTENDED` mark prices the session: the workshop's duration
    in hours is computed exactly from its `end_at` minus its `start_at`, and
    `incentive_earned_cents` is set to the module's `incentive_cents_per_hour`
    multiplied by that duration, rounded half up to integer cents."

    Design: Difficulty/combinatorial_formula/session_incentive_per_line_rounding_order
    """
    _module, _participant, regs = _two_attended_90min_scenario(
        admin_headers,
        dict(module_code="SV-201", session_count=4, incentive_cents_per_hour=655,
             completion_bonus_cents=2500, completion_threshold=3),
    )
    registration = validate_success(api.get_registration(regs[0]["id"], admin_headers))
    # round_half_up(655 * 1.5) = round_half_up(982.5) = 983.
    assert registration["incentive_earned_cents"] == 983, (
        f"per-session line must be rounded half up; got {registration['incentive_earned_cents']}"
    )


def test_earned_cents_sums_per_line_rounding_not_sum_then_round(api, admin_headers):
    """PRD §2.6: "Attendance incentives are rounded per session line first — each
    attended session's line is rounded half up to integer cents on its own — and
    only then summed; summing first and rounding once is a different, incorrect
    algorithm."

    Design: Difficulty/combinatorial_formula/session_incentive_per_line_rounding_order
    """
    _module, participant, _regs = _two_attended_90min_scenario(
        admin_headers,
        dict(module_code="SV-201", session_count=4, incentive_cents_per_hour=655,
             completion_bonus_cents=2500, completion_threshold=3),
    )
    summary = validate_success(
        api.get_incentive_summary(participant["id"], admin_headers)
    )
    # 983 + 983 = 1966; sum-then-round would give round_half_up(1965.0) = 1965.
    assert summary["earned_cents"] == 1966, (
        f"per-line rounding order pinned: expected 1966, got {summary['earned_cents']}"
    )
    assert summary["completion_bonuses_earned_cents"] == 0
