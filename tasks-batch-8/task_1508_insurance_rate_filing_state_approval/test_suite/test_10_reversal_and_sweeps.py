"""Wave reversal, post-effective disapproval cascade, and clock sweeps
(PRD §2.4, §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    create_wave,
    find_calendar_entry,
    get_success_data,
    set_clock,
    setup_approved_filing,
    setup_effective_with_wave,
    setup_released_wave,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx

NV_FAU = {"filing_method": "FILE_AND_USE", "deemer_days": 0}
TWO_POLICIES = [
    ("CA-1001", 100_000, 1.0, "2026-11-20"),
    ("CA-1002", 200_000, 2.0, "2026-11-25"),
]


def _rescission_scenario(api):
    """NV FILE_AND_USE filing EFFECTIVE 2026-10-01; wave RELEASED with one
    NOTICE_SENT policy; clock 2026-10-05 (inside the disapproval window)."""
    scenario = setup_effective_with_wave(
        state_code="NV",
        profile_overrides=dict(NV_FAU),
        policies=[("NV-3001", 100_000, 1.0, "2026-11-20")],
    )
    get_success_data(api.release_wave(scenario["wave"]["id"], fx.LEAD))
    set_clock("2026-10-05T00:00:00Z")
    get_success_data(api.send_policy_notice(scenario["policies"][0]["id"], fx.LEAD))
    return scenario


def test_post_effective_disapproval_reverses_wave(api):
    """PRD §3.6: "When all three gates pass, the filing moves to `DISAPPROVED`
    and a three-hop cascade unwinds its footprint. First, every implementation
    wave of the filing in `RELEASED` moves to `REVERSED`, and every wave still
    `SCHEDULED` moves to `CANCELLED`."

    Design: Difficulty/transitive_cascade/post_effective_disapproval_rescission_cascade
    """
    scenario = _rescission_scenario(api)
    disapproved = validate_success(
        api.disapprove_filing(scenario["filing"]["id"], fx.REGULATOR), 200
    )
    assert disapproved["status"] == "DISAPPROVED"

    wave = fx.refresh_wave(scenario["wave"]["id"])
    assert wave["status"] == "REVERSED"
    assert wave["rated_policy_count"] == 0


def test_post_effective_disapproval_rescinds_policy_and_waives_calendar(api):
    """PRD §3.6: "Second, each reversed wave restores its policies: policies in
    `RATED` return to `PENDING` with their premium computation fields and
    `wave_id` nulled, while policies in `NOTICE_SENT` or `COMPLETED` move to
    `RESCINDED` with `current_premium_cents` restored to the snapshotted
    `baseline_premium_cents`. Third, the calendar is cleaned: the restored
    policies' still-pending `RENEWAL_NOTICE_DUE` entries are waived, each
    reversed wave's `WAVE_WINDOW` entry is waived, and each reversed wave's
    `rated_policy_count` is recomputed to zero."

    Design: Difficulty/transitive_cascade/post_effective_disapproval_rescission_cascade
    """
    scenario = _rescission_scenario(api)
    policy_id = scenario["policies"][0]["id"]
    wave_id = scenario["wave"]["id"]

    get_success_data(api.disapprove_filing(scenario["filing"]["id"], fx.REGULATOR))

    policy = fx.refresh_policy(policy_id)
    assert policy["status"] == "RESCINDED"
    assert policy["current_premium_cents"] == 100000
    window = find_calendar_entry(wave_id=wave_id, entry_type="WAVE_WINDOW")
    assert window["status"] == "WAIVED"


def test_wave_reversal_restores_completed_policy_baseline(api):
    """PRD §3.7: "its `NOTICE_SENT` and `COMPLETED` policies move to
    `RESCINDED` — the terminal state of the policy lifecycle — with
    `current_premium_cents` restored to the `baseline_premium_cents` snapshot
    and the computation fields nulled, though `wave_id` is retained for audit".
    PRD §3.7: "Rescission after binding is precisely the compensating action
    that restores the baseline premium ledger."

    Design: Difficulty/compensating_invariant/wave_reversal_baseline_restoration
    """
    scenario = setup_released_wave(policies=TWO_POLICIES)
    p1 = scenario["policies"][0]

    set_clock("2026-10-20T00:00:00Z")
    get_success_data(api.send_policy_notice(p1["id"], fx.LEAD))
    set_clock("2026-11-20T00:00:00Z")
    completed = get_success_data(api.complete_policy_renewal(p1["id"], fx.LEAD))
    assert completed["status"] == "COMPLETED"
    assert completed["current_premium_cents"] == 106765  # final bound

    get_success_data(api.reverse_wave(scenario["wave"]["id"], fx.LEAD))

    restored = fx.refresh_policy(p1["id"])
    assert restored["status"] == "RESCINDED"
    assert restored["current_premium_cents"] == 100000  # baseline restored


def test_wave_reversal_returns_rated_policy_to_pending(api):
    """PRD §3.7: "Reversing a wave moves it to the terminal `REVERSED` state:
    its `RATED` policies return to `PENDING` with `wave_id`, baseline, and the
    raw and final premium fields nulled; its `NOTICE_SENT` and `COMPLETED`
    policies move to `RESCINDED` — the terminal state of the policy lifecycle —
    with `current_premium_cents` restored to the `baseline_premium_cents`
    snapshot and the computation fields nulled, though `wave_id` is retained
    for audit; the affected policies' pending `RENEWAL_NOTICE_DUE` entries and
    the wave's `WAVE_WINDOW` entry are waived; and `rated_policy_count`
    recomputes to zero."

    Design: Difficulty/compensating_invariant/wave_reversal_baseline_restoration
    """
    scenario = setup_released_wave(policies=TWO_POLICIES)
    p1, p2 = scenario["policies"]

    set_clock("2026-10-20T00:00:00Z")
    get_success_data(api.send_policy_notice(p1["id"], fx.LEAD))
    set_clock("2026-11-20T00:00:00Z")
    get_success_data(api.complete_policy_renewal(p1["id"], fx.LEAD))

    reversed_wave = validate_success(
        api.reverse_wave(scenario["wave"]["id"], fx.LEAD), 200
    )
    assert reversed_wave["status"] == "REVERSED"
    assert reversed_wave["rated_policy_count"] == 0

    # P2 was RATED (never noticed): it returns to PENDING, premium untouched.
    p2_after = fx.refresh_policy(p2["id"])
    assert p2_after["status"] == "PENDING"
    assert p2_after["current_premium_cents"] == 200000
    assert p2_after["wave_id"] is None
    assert p2_after["baseline_premium_cents"] is None

    # Book ledger conserved after the round trip.
    p1_after = fx.refresh_policy(p1["id"])
    assert p1_after["current_premium_cents"] + p2_after["current_premium_cents"] == 300000


def test_wave_completes_on_clock_sweep(api):
    """PRD §3.7: "A wave whose end date has passed with no policies left in
    `RATED` or `NOTICE_SENT` — every assigned policy `COMPLETED` or `RESCINDED`
    — is swept to `COMPLETED`, and its `WAVE_WINDOW` entry is marked `MET`."
    PRD §3.7: "completing the renewal moves the policy from `NOTICE_SENT` to
    `COMPLETED` and the new rate binds as `current_premium_cents` takes the
    value of `final_premium_cents`."

    Design: Corner/state_machines/wave_completion_on_clock_sweep
    """
    scenario = setup_released_wave(policies=[("CA-1001", 100_000, 1.0, "2026-11-20")])
    policy = scenario["policies"][0]

    set_clock("2026-10-20T00:00:00Z")
    get_success_data(api.send_policy_notice(policy["id"], fx.LEAD))
    set_clock("2026-11-20T00:00:00Z")
    completed = get_success_data(api.complete_policy_renewal(policy["id"], fx.LEAD))
    assert completed["current_premium_cents"] == 110000

    # Clock past the 2026-12-15 window end sweeps the wave to COMPLETED.
    set_clock("2026-12-16T00:00:00Z")
    wave = fx.refresh_wave(scenario["wave"]["id"])
    assert wave["status"] == "COMPLETED"
    window = find_calendar_entry(
        wave_id=scenario["wave"]["id"], entry_type="WAVE_WINDOW"
    )
    assert window["status"] == "MET"


def test_unnoticed_policy_bounced_by_late_notice_sweep(api):
    """PRD §3.7: "a policy still `RATED` when the logical clock passes its
    `renewal_effective_date` without a notice ever sent — a renewal that has
    passed unactionable — is bounced back to `PENDING` with `wave_id`,
    baseline, and the raw and final premium fields nulled, its
    `exclusion_reason` set to `LATE_NOTICE_SWEEP`, its `RENEWAL_NOTICE_DUE`
    entry marked `MISSED`, and its wave's `rated_policy_count` recomputed".

    Design: Corner/state_machines/late_notice_sweep_bounces_policy
    """
    scenario = setup_released_wave(policies=[("CA-1001", 100_000, 1.0, "2026-11-20")])
    policy_id = scenario["policies"][0]["id"]
    wave_id = scenario["wave"]["id"]

    # Clock past the 2026-11-20 renewal with the notice never sent.
    set_clock("2026-11-21T00:00:00Z")

    policy = fx.refresh_policy(policy_id)
    assert policy["status"] == "PENDING"
    assert policy["exclusion_reason"] == "LATE_NOTICE_SWEEP"
    assert policy["wave_id"] is None
    assert policy["raw_change_pct"] is None
    assert policy["final_premium_cents"] is None

    assert fx.refresh_wave(wave_id)["rated_policy_count"] == 0
    entry = find_calendar_entry(wave_id=wave_id, entry_type="RENEWAL_NOTICE_DUE")
    assert entry["status"] == "MISSED"


def test_calendar_entry_waive_action_and_terminal_lock(api):
    """PRD §2.9: "it becomes `WAIVED` when a `ComplianceOfficer` deliberately
    waives a pending obligation or when a cascade (a withdrawn or disapproved
    filing, a cancelled or reversed wave, a withdrawn objection) vacates the
    obligation."
    PRD §2.9: "An entry leaves `PENDING` in exactly one of three ways,
    recording `resolved_at` at the moment it resolves".

    Design: Corner/endpoints/calendar_entry_waive_action
    """
    scenario = setup_approved_filing(approve_at="2026-09-01T00:00:00Z")
    wave = create_wave(scenario["filing"]["id"])
    entry = find_calendar_entry(wave_id=wave["id"], entry_type="WAVE_WINDOW")
    assert entry["status"] == "PENDING"

    waived = validate_success(api.waive_calendar_entry(entry["id"], fx.OFFICER), 200)
    assert waived["status"] == "WAIVED"
    assert_instant_equals(waived["resolved_at"], "2026-09-01T00:00:00Z")

    # A terminal entry has no further transitions.
    res = api.waive_calendar_entry(entry["id"], fx.OFFICER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
