"""Mid-term endorsements: premium delta, ledger charge, and OCC on Policy.version.

Queue B (cross_cutting_complexity_layers):
  occ_stale_policy_version_on_second_endorsement_apply
  endorsement_apply_raise_attendance_bumps_premium_and_ledger
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    make_policyholder_headers, TEST_USERS,
)
from test_helpers import fixtures as FX
from test_helpers.assertions import ledger_sum_by_kind

_uw = TEST_USERS["underwriter_headers"]
_ph = make_policyholder_headers("ph-1")


def test_occ_stale_policy_version_on_second_endorsement_apply(api):
    """PRD §2.7: "If they do not match — which happens when some other endorsement apply has
    already advanced the policy's version since the client read it — the apply is rejected
    with `ERR_STALE_POLICY_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_policy_version_on_second_endorsement_apply
    """
    ctx = FX.setup_bound_policy_canc_only()
    pid = ctx["policy"]["id"]
    pol_v = FX.observed_policy_version(pid)
    endo_a = FX.draft_endorsement(pid, "RAISE_ATTENDANCE", {"new_attendance": 250})
    endo_b = FX.draft_endorsement(pid, "RAISE_ATTENDANCE", {"new_attendance": 300})
    # First apply succeeds and advances Policy.version.
    validate_success(api.apply_endorsement(
        pid, endo_a["id"], {"expected_policy_version": pol_v}, _uw), 200)
    # Second apply carries the now-stale version observed before the first apply.
    res = api.apply_endorsement(pid, endo_b["id"], {"expected_policy_version": pol_v}, _uw)
    validate_error(res, "ERR_STALE_POLICY_VERSION", 412)
    endorsements = validate_success(api.list_endorsements(pid, _uw), 200)
    b_after = next(e for e in endorsements if e["id"] == endo_b["id"])
    assert b_after["status"] == "DRAFT"


def test_endorsement_apply_raise_attendance_bumps_premium_and_ledger(api):
    """PRD §3.9: "For a `RAISE_ATTENDANCE` endorsement, the system first snapshots the old
    total attendance as the current sum of `expected_attendance` across all event profiles,
    then sets the named event profile's `expected_attendance` to the new attendance figure,
    then recomputes the new total attendance as the new sum; the delta is the sum, over all
    `ACTIVE` coverage lines, of each line's product `per_guest_premium_cents` multiplied by
    the increase in total attendance (the new total minus the old total)."
    PRD §3.9: "increases the policy's `total_premium_cents` by that delta, appends an
    `ENDORSEMENT_CHARGE` ledger entry whose `amount_cents` is the positive delta".

    Design: Corner/cross_cutting_complexity_layers/endorsement_apply_raise_attendance_bumps_premium_and_ledger
    """
    ctx = FX.setup_bound_policy_canc_only()  # CANC-only, attendance 150, total 65000
    pid = ctx["policy"]["id"]
    pol_v = FX.observed_policy_version(pid)
    endo = FX.draft_endorsement(pid, "RAISE_ATTENDANCE", {"new_attendance": 250})
    applied = validate_success(api.apply_endorsement(
        pid, endo["id"], {"expected_policy_version": pol_v}, _uw), 200)
    assert applied["status"] == "APPLIED"
    # delta = 300 * (250 - 150) == 30000
    assert applied["premium_delta_cents"] == 30000
    policy = validate_success(api.get_policy(pid, _uw), 200)
    assert policy["total_premium_cents"] == 95000
    data, _ = validate_paginated(api.list_ledger(pid, _uw))
    assert ledger_sum_by_kind(data, "ENDORSEMENT_CHARGE") == 30000
