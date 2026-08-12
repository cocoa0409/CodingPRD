"""Where two rungs of the ladder fail on the same request, the lower-numbered
one is the error that comes back."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    fixtures as fx,
)


# ==========================================================================
# Rung 13 (legal hold) versus rung 44 (scan quota)
# ==========================================================================

def _held_account_with_an_exhausted_scan_pool():
    """A one-scan plan whose single SCAN unit has been spent by a completed
    initial scan, the clock eight days on so the recurring interval is satisfied,
    and the account under legal hold."""
    household = fx.open_household(tier="SOLO", name="Solo Micro",
                                  monthly_fee_cents=900, max_members=1,
                                  profile_quota_per_cycle=1, scan_quota_per_cycle=1,
                                  removal_quota_per_cycle=5,
                                  per_member_removal_subcap=5)
    profile = fx.setup_active_profile(household)
    scan = fx.queue_scan(profile["id"], kind="INITIAL")
    fx.start_scan(scan["id"])
    fx.complete_scan(scan["id"])
    fx.set_clock("2026-05-09T00:00:00Z")
    validate_success(fx.api.set_legal_hold(household["account_id"], "HOLD_ON", fx.ADMIN))
    return household, profile


def test_legal_hold_gate_pre_empts_the_scan_quota_rung(api):
    """PRD §2.6: "13. **Global write gate 1** — the account in scope has `legal_hold`
    false, otherwise `ERR_ACCOUNT_LEGAL_HOLD` (409). Applies to every account-scoped
    mutating endpoint (POST, PATCH, PUT, DELETE) except the legal-hold capability itself."
    PRD §2.7: "Because the gate sits at rung 13, it pre-empts the per-endpoint state gates
    entirely: a request that is both blocked by legal hold and invalid for the target's
    current state reports the hold, not the state."

    Design: Difficulty/priority_pair_validation_conflict/legal_hold_gate_beats_scan_quota_exhausted
    """
    household, profile = _held_account_with_an_exhausted_scan_pool()

    response = api.create_scan_run({"profile_id": profile["id"], "kind": "RECURRING"},
                                   fx.AGENT)

    validate_error(response, ApiErrorId.ERR_ACCOUNT_LEGAL_HOLD.value, 409)
    account = fx.read_account(household)
    assert account["legal_hold"] is True
    # The fiscal rung really was violated too: the single granted unit is spent.
    assert account["scan_units_remaining"] == 0
    _, meta = validate_paginated(api.list_scan_runs(fx.ADMIN,
                                                    params={"profile_id": profile["id"]}))
    assert meta["total_count"] == 1, "the rejected create must not mint a scan row"


def test_lifting_the_legal_hold_exposes_the_scan_quota_rung(api):
    """PRD §2.6: "44. The account's `scan_units_remaining` is at least 1, otherwise
    `ERR_SCAN_QUOTA_EXCEEDED` (409). Applies to scan queuing."
    PRD §3.2: "lowering it — the transition `HOLD_ON → HOLD_OFF` — requires `legal_hold`
    to currently be true and sets it false, clearing `legal_hold_set_at` to null."

    Design: Difficulty/priority_pair_validation_conflict/legal_hold_gate_beats_scan_quota_exhausted
    """
    household, profile = _held_account_with_an_exhausted_scan_pool()

    lifted = validate_success(api.set_legal_hold(household["account_id"],
                                                 "HOLD_OFF", fx.ADMIN))
    assert lifted["legal_hold"] is False
    assert lifted["legal_hold_set_at"] is None

    response = api.create_scan_run({"profile_id": profile["id"], "kind": "RECURRING"},
                                   fx.AGENT)

    validate_error(response, ApiErrorId.ERR_SCAN_QUOTA_EXCEEDED.value, 409)


# ==========================================================================
# Rung 22 (retired broker) versus rung 33 (escalation cap)
# ==========================================================================

def _capped_request_at_a_retired_broker():
    world = fx.setup_household_with_exposure(
        broker_overrides={"name": "QuickLookup", "opt_out_method": "WEB_FORM",
                          "jurisdiction": "OTHER", "response_window_days": 30},
        exposure_kind="PUBLIC_RECORD")
    request_id = fx.drive_removal_around_loop(world["exposure"]["id"], laps=2)
    validate_success(fx.api.retire_broker(world["broker"]["id"], fx.ADMIN))
    return world, request_id


def test_retired_broker_pre_empts_the_escalation_cap_rung(api):
    """PRD §2.6: "22. The broker the operation depends on has status `ACTIVE`, otherwise
    `ERR_BROKER_RETIRED` (409). Applies to finding recording, removal drafting, removal
    submission and removal escalation."
    PRD §3.5: "A retired broker blocks four operations with `ERR_BROKER_RETIRED`:
    recording a finding against it, drafting a removal request at it, submitting one, and
    escalating one."

    Design: Difficulty/priority_pair_validation_conflict/retired_broker_beats_escalation_cap
    """
    world, request_id = _capped_request_at_a_retired_broker()

    response = api.escalate_removal_request(request_id, fx.AGENT)

    validate_error(response, ApiErrorId.ERR_BROKER_RETIRED.value, 409)
    row = fx.read_removal(request_id)
    # The constraint rung at 33 really was violated too.
    assert row["escalation_count"] == 2
    assert row["status"] == "REJECTED"


def test_retired_broker_still_reports_its_lifetime_compliance(api):
    """PRD §3.9: "The score starts from a base of 100, subtracts 8 points per
    reappearance, subtracts 12 points per expired request, subtracts 5 points per rejected
    request, adds 3 points per on-time completion, and is then clamped into the inclusive
    range 0 to 100 — the floor is 0 and the ceiling is 100."
    PRD §3.9: "the expired and rejected figures are the counts of removal requests at this
    broker whose **current** status is `EXPIRED` and `REJECTED` respectively"

    Design: Difficulty/priority_pair_validation_conflict/retired_broker_beats_escalation_cap
    """
    world, request_id = _capped_request_at_a_retired_broker()
    api.escalate_removal_request(request_id, fx.AGENT)

    report = validate_success(api.get_compliance_report(world["broker"]["id"], fx.AGENT,
                                                        params={"scope": "LIFETIME"}))

    # Exactly one request sits in REJECTED right now; nothing is EXPIRED, nothing
    # completed and no exposure has reappeared. 100 - 5 * 1 = 95.
    assert report["rejected_request_count"] == 1
    assert report["expired_request_count"] == 0
    assert report["on_time_completion_count"] == 0
    assert report["reappearance_count"] == 0
    assert report["compliance_score"] == 95
