"""The two non-linear loops: the unbounded exposure suppression cycle and the
capped reject/escalate/resubmit cycle of a removal request."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_same_instant, fixtures as fx,
)


def _exposure_driven_around_the_loop_twice():
    """Drive one exposure FOUND -> SUPPRESSED -> REAPPEARED -> RE_SUPPRESSED and
    leave a third RECURRING scan RUNNING at 2026-07-01, ready to re-find it.

    Returns (household, broker, profile, first_scan, exposure_id, third_scan).
    """
    world = fx.setup_household_with_exposure(
        broker_overrides={"name": "QuickLookup", "opt_out_method": "WEB_FORM",
                          "jurisdiction": "OTHER", "response_window_days": 30})
    household, broker = world["household"], world["broker"]
    profile, scan1, exposure = world["profile"], world["scan"], world["exposure"]

    # Lap 1: suppress at the startup instant 2026-05-01.
    fx.suppress_exposure(exposure["id"], broker_reference="QL-0001")

    # 44 whole days later the re-finding is a REAPPEARANCE, then re-suppress it.
    fx.set_clock("2026-06-14T00:00:00Z")
    fx.run_scan(profile["id"], [broker["id"]], kind="RECURRING", complete=True)
    fx.suppress_exposure(exposure["id"], broker_reference="QL-0002")

    # 17 whole days after the second suppression, still inside the 45-day window.
    fx.set_clock("2026-07-01T00:00:00Z")
    scan3 = fx.queue_scan(profile["id"], kind="RECURRING")
    fx.start_scan(scan3["id"])
    return household, broker, profile, scan1, exposure["id"], scan3


def test_exposure_reenters_reappeared_from_re_suppressed(api):
    """PRD §3.4: "The exposure axis therefore runs
    `FOUND → SUPPRESSED → REAPPEARED → RE_SUPPRESSED → REAPPEARED …` as an unbounded loop
    with no terminal state, and it evolves entirely independently of the removal-request
    axis that targets it."
    PRD §3.4: "`REAPPEARANCE` mutates the existing row from `SUPPRESSED` or
    `RE_SUPPRESSED` to `REAPPEARED`, increments its `reappearance_count` by 1, sets
    `last_seen_at` to the current instant, and leaves `suppression_count` and
    `first_found_at` untouched; **no new row is created**, and the broker consequently
    re-derives its own reappearance tally and compliance score."

    Design: Difficulty/non_linear_state_machine/exposure_suppress_reappear_resuppress_unbounded_loop
    """
    household, broker, profile, scan1, exposure_id, scan3 = \
        _exposure_driven_around_the_loop_twice()

    data = validate_success(api.record_finding(
        scan3["id"],
        {"broker_id": broker["id"], "exposure_kind": "PEOPLE_SEARCH",
         "source_url": "https://quicklookup.example/dana"},
        fx.AGENT))

    assert data["id"] == exposure_id, "the second lap must mutate the same row"
    assert data["status"] == "REAPPEARED"
    # Two entries into REAPPEARED (2026-06-14 and 2026-07-01).
    assert data["reappearance_count"] == 2
    # Two entries into SUPPRESSED / RE_SUPPRESSED, preserved across the loop.
    assert data["suppression_count"] == 2
    assert data["fee_exempt"] is True
    assert_same_instant(data["last_seen_at"], "2026-07-01T00:00:00Z", "last_seen_at")


def test_exposure_loop_conserves_the_row_and_its_discovery_provenance(api):
    """PRD §2.10: "For a given profile-and-broker pair, a reappearance never creates a
    second exposure row."
    PRD §3.4: "`FRESH` creates a brand-new exposure row in `FOUND`, stamping
    `discovered_by_scan_id` with this scan — a value never rewritten by any later sighting
    — along with `first_found_at` and `last_seen_at` at the current instant,
    `suppression_count` and `reappearance_count` at 0."

    Design: Difficulty/non_linear_state_machine/exposure_suppress_reappear_resuppress_unbounded_loop
    """
    household, broker, profile, scan1, exposure_id, scan3 = \
        _exposure_driven_around_the_loop_twice()
    validate_success(api.record_finding(
        scan3["id"],
        {"broker_id": broker["id"], "exposure_kind": "PEOPLE_SEARCH",
         "source_url": "https://quicklookup.example/dana"},
        fx.AGENT))

    row = validate_success(api.get_exposure(exposure_id, household["owner"]))
    assert row["discovered_by_scan_id"] == scan1["id"], \
        "discovered_by_scan_id must survive every later sighting"
    assert_same_instant(row["first_found_at"], "2026-05-01T00:00:00Z", "first_found_at")

    _, meta = validate_paginated(api.list_exposures(
        household["owner"],
        params={"profile_id": profile["id"], "broker_id": broker["id"]}))
    assert meta["total_count"] == 1, "the whole loop must leave exactly one exposure row"


# ==========================================================================
# The capped removal-request loop
# ==========================================================================

def _request_at_the_escalation_cap():
    """One removal request driven twice around reject -> escalate -> resubmit, so
    it sits in REJECTED with escalation_count 2."""
    world = fx.setup_household_with_exposure(
        broker_overrides={"name": "QuickLookup", "opt_out_method": "WEB_FORM",
                          "jurisdiction": "OTHER", "response_window_days": 30},
        exposure_kind="MARKETING_LIST")
    request_id = fx.drive_removal_around_loop(world["exposure"]["id"], laps=2)
    return world, request_id


def test_third_escalation_is_refused_once_the_cap_is_reached(api):
    """PRD §3.5: "From either `REJECTED → ESCALATED` or `EXPIRED → ESCALATED`, a
    `PrivacyAgent` may escalate while the request's `escalation_count` is strictly below 2
    and the broker is `ACTIVE`; the transition increments `escalation_count` by 1 and
    clears `closed_at` back to null."
    PRD §3.5: "The third escalation is refused with `ERR_ESCALATION_CAP_REACHED`."

    Design: Difficulty/non_linear_state_machine/removal_request_reject_escalate_resubmit_capped_loop
    """
    world, request_id = _request_at_the_escalation_cap()

    response = api.escalate_removal_request(request_id, fx.AGENT)

    validate_error(response, ApiErrorId.ERR_ESCALATION_CAP_REACHED.value, 409)
    row = fx.read_removal(request_id)
    assert row["status"] == "REJECTED", "the refused escalation must not move the row"
    assert row["escalation_count"] == 2


def test_the_capped_loop_costs_exactly_one_removal_unit(api):
    """PRD §3.5: "Three things about rejection deserve emphasis: the consumed removal unit
    is **not** released — a rejected request has still cost the household a unit; the
    linked exposure does **not** change status; and the broker re-derives
    `rejected_request_count` and therefore its compliance score."

    Design: Difficulty/non_linear_state_machine/removal_request_reject_escalate_resubmit_capped_loop
    """
    world, request_id = _request_at_the_escalation_cap()
    api.escalate_removal_request(request_id, fx.AGENT)

    row = fx.read_removal(request_id)
    assert row["entitlement_units_consumed"] == 1
    assert row["entitlement_units_released"] == 0

    account = fx.read_account(world["household"])
    # Three submissions and three rejections drew exactly the single unit taken
    # at draft time; nothing on the loop refunds or re-draws.
    assert account["removal_units_consumed"] == 1
    assert account["removal_units_released"] == 0
    assert account["removal_units_remaining"] == 59

    exposure = fx.read_exposure(world["exposure"]["id"])
    assert exposure["status"] == "FOUND", "rejection never moves the exposure axis"
