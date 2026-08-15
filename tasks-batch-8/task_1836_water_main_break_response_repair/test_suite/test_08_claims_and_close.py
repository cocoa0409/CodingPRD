"""Damage claims and the break fiscal ledger: filing window, amount rules,
approve/pay/void transitions, terminal-state lockdown, close guards, and the
cost rollup across repair + restoration + claims."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_claim,
    get_break,
    set_clock,
    setup_confirmed_break,
    setup_repaired_break,
    setup_restored_break,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api
from test_helpers import create_damage_claim_payload

DISPATCHER = TEST_USERS["dispatcher_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
ENGINEER = TEST_USERS["engineer_headers"]


def _pine_repaired_with_61000_cost():
    """Break on MAIN-8-PINE fully repaired; actual repair cost 61000
    (labor 1h x 6000 + one materials line 50000 x 1.10 = 55000)."""
    return setup_repaired_break(
        segment_ref="MAIN-8-PINE", diameter_inches=8, install_year=1975,
        break_type="CIRCUMFERENTIAL", severity="MEDIUM",
        location_description="9 Pine Ct",
        crew_name="Crew Pine", crew_rate=6000,
        materials_used=[{"item_code": "PIPE-8IN", "quantity": 1,
                         "unit_price_cents": 50000}],
    )


# ---------------------------------------------------------------------------
# Difficulty: claim_approve_void_conserves_money (2 tests)
# ---------------------------------------------------------------------------

def test_approve_adds_liability_but_not_total_cost(api):
    """PRD §3.7: "Approving a `SUBMITTED` claim sets `approved_amount_cents`,
    which must be greater than zero (otherwise `ERR_INVALID_AMOUNT`) and must
    not exceed `claimed_amount_cents` (otherwise `ERR_AMOUNT_EXCEEDS_CLAIMED`,
    HTTP 409); approval moves the claim to `APPROVED` and adds the approved
    amount into the break's `claims_liability_cents`."
    PRD §3.7: "`total_cost_cents` is the sum of `total_repair_cost_cents`,
    `total_restoration_cost_cents`, and `total_claims_paid_cents` — note that
    open liability is deliberately excluded from the headline cost figure."

    Design: Difficulty/compensating_invariant/claim_approve_void_conserves_money
    """
    ctx = _pine_repaired_with_61000_cost()
    br = ctx["break"]
    assert br["total_repair_cost_cents"] == 61000
    claim = create_claim(br["id"], claimant_name="J. Homeowner",
                         claimed_amount_cents=100000)
    approved = approve_claim(claim["id"], 60000)
    assert approved["claim_status"] == "APPROVED"

    br_after = get_break(br["id"])
    assert br_after["claims_liability_cents"] == 60000, (
        f"approval must add 60000 to liability, got {br_after['claims_liability_cents']}"
    )
    assert br_after["total_claims_paid_cents"] == 0
    assert br_after["total_cost_cents"] == 61000, (
        "open liability is excluded from the headline total cost"
    )


def test_void_after_approve_restores_pre_approve_money(api):
    """PRD §3.7: "Voiding an `APPROVED` claim is the compensating action: the
    claim moves to `VOIDED` (terminal) and the approved amount is subtracted
    from `claims_liability_cents` with no entry into paid totals. An approve
    followed by a void therefore leaves `claims_liability_cents`,
    `total_claims_paid_cents`, and `total_cost_cents` exactly as they were
    before the approval."

    Design: Difficulty/compensating_invariant/claim_approve_void_conserves_money
    """
    ctx = _pine_repaired_with_61000_cost()
    br = ctx["break"]
    claim = create_claim(br["id"], claimant_name="J. Homeowner",
                         claimed_amount_cents=100000)
    approve_claim(claim["id"], 60000)

    voided = validate_success(_api.void_damage_claim(claim["id"], ADJUSTER), 200)
    assert voided["claim_status"] == "VOIDED"

    br_end = get_break(br["id"])
    assert br_end["claims_liability_cents"] == 0, (
        "void must subtract the approved amount from liability"
    )
    assert br_end["total_claims_paid_cents"] == 0
    assert br_end["total_cost_cents"] == 61000, (
        f"approve+void must leave total_cost_cents exactly as before the "
        f"approval (61000), got {br_end['total_cost_cents']}"
    )


# ---------------------------------------------------------------------------
# Corner: terminal_paid_claim_rejects_transitions
# ---------------------------------------------------------------------------

def test_terminal_paid_claim_rejects_transitions(api):
    """PRD §3.7: "Paying an `APPROVED` claim moves it to `PAID` (terminal),
    subtracts `approved_amount_cents` from the break's
    `claims_liability_cents`, and adds the same amount to the break's
    `total_claims_paid_cents`."
    PRD §3.7: "`total_claims_paid_cents` is the sum of `approved_amount_cents`
    over claims in `PAID` status."

    Design: Corner/state_machines/terminal_paid_claim_rejects_transitions
    """
    ctx = setup_confirmed_break(
        segment_ref="MAIN-8-PINE", diameter_inches=8, install_year=1975,
        break_type="CIRCUMFERENTIAL", severity="MEDIUM",
        location_description="9 Pine Ct",
    )
    br = ctx["break"]
    claim = create_claim(br["id"], claimant_name="J. Homeowner",
                         claimed_amount_cents=100000)
    approve_claim(claim["id"], 60000)
    paid = validate_success(_api.pay_damage_claim(claim["id"], ADJUSTER), 200)
    assert paid["claim_status"] == "PAID"

    resp_void = _api.void_damage_claim(claim["id"], ADJUSTER)
    validate_error(resp_void, ApiErrorId.ERR_INVALID_STATE)
    resp_deny = _api.deny_damage_claim(claim["id"], ADJUSTER)
    validate_error(resp_deny, ApiErrorId.ERR_INVALID_STATE)

    br_after = get_break(br["id"])
    assert br_after["total_claims_paid_cents"] == 60000, (
        "rejected transitions on a terminal PAID claim must not move money"
    )


# ---------------------------------------------------------------------------
# Corner: claim_filed_after_90_days_rejected
# ---------------------------------------------------------------------------

def test_claim_filed_after_90_days_rejected(api):
    """PRD §3.7: "Two timing gates apply: the break must be `CONFIRMED` or
    later (a `REPORTED` or `FALSE_ALARM` break cannot take claims), and filing
    must occur no more than 90 days after the break's `confirmed_at` — the
    boundary is inclusive, so filing exactly 90 days after confirmation is
    accepted, and any later filing is rejected with `ERR_CLAIM_FILED_LATE`."

    Design: Corner/validations/claim_filed_after_90_days_rejected
    """
    ctx = setup_confirmed_break(
        segment_ref="MAIN-8-OAK", material="PVC", diameter_inches=8,
        install_year=1999, break_type="SPLIT", severity="LOW",
        location_description="12 Oak St",
    )
    br = ctx["break"]
    # confirmed_at is the startup clock 2026-08-01T00:00:00Z; +90 days is
    # 2026-10-30T00:00:00Z.
    set_clock("2026-10-30T00:00:00Z")
    on_time = validate_success(
        _api.create_damage_claim(
            create_damage_claim_payload(
                break_report_id=br["id"], claimant_name="On Time",
                claimed_amount_cents=1000,
            ),
            DISPATCHER,
        ),
        201,
    )
    assert on_time["claim_status"] == "SUBMITTED", (
        "filing exactly at confirmed_at + 90 days must be accepted"
    )

    set_clock("2026-10-31T00:00:00Z")
    resp = _api.create_damage_claim(
        create_damage_claim_payload(
            break_report_id=br["id"], claimant_name="Too Late",
            claimed_amount_cents=1000,
        ),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_FILED_LATE)


# ---------------------------------------------------------------------------
# Corner: approve_amount_above_claimed_rejected
# ---------------------------------------------------------------------------

def test_approve_amount_above_claimed_rejected(api):
    """PRD §3.7: "Approving a `SUBMITTED` claim sets `approved_amount_cents`,
    which must be greater than zero (otherwise `ERR_INVALID_AMOUNT`) and must
    not exceed `claimed_amount_cents` (otherwise `ERR_AMOUNT_EXCEEDS_CLAIMED`,
    HTTP 409); approval moves the claim to `APPROVED` and adds the approved
    amount into the break's `claims_liability_cents`."

    Design: Corner/validations/approve_amount_above_claimed_rejected
    """
    ctx = setup_confirmed_break(
        segment_ref="MAIN-8-OAK", material="PVC", diameter_inches=8,
        install_year=1999, break_type="SPLIT", severity="LOW",
        location_description="12 Oak St",
    )
    claim = create_claim(ctx["break"]["id"], claimant_name="J. Homeowner",
                         claimed_amount_cents=100000)

    resp = _api.approve_damage_claim(
        claim["id"], {"approved_amount_cents": 100001}, ADJUSTER
    )
    validate_error(resp, ApiErrorId.ERR_AMOUNT_EXCEEDS_CLAIMED)

    approved = validate_success(
        _api.approve_damage_claim(
            claim["id"], {"approved_amount_cents": 100000}, ADJUSTER
        ),
        200,
    )
    assert approved["claim_status"] == "APPROVED", (
        "approving exactly the claimed amount must succeed"
    )


# ---------------------------------------------------------------------------
# Corner: claim_zero_amount_returns_invalid_amount
# ---------------------------------------------------------------------------

def test_claim_zero_amount_returns_invalid_amount(api):
    """PRD §3.7: "Property-damage claims are filed by a `Dispatcher` against a
    break, naming the `break_report_id`, the `claimant_name`, and a
    `claimed_amount_cents` that must be greater than zero (otherwise
    `ERR_INVALID_AMOUNT`)."

    Design: Corner/validations/claim_zero_amount_returns_invalid_amount
    """
    ctx = setup_confirmed_break(
        segment_ref="MAIN-8-OAK", material="PVC", diameter_inches=8,
        install_year=1999, break_type="SPLIT", severity="LOW",
        location_description="12 Oak St",
    )
    resp = _api.create_damage_claim(
        create_damage_claim_payload(
            break_report_id=ctx["break"]["id"], claimant_name="Zero",
            claimed_amount_cents=0,
        ),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT)


# ---------------------------------------------------------------------------
# Corner: close_blocked_by_active_advisory
# ---------------------------------------------------------------------------

def test_close_blocked_by_active_advisory(api):
    """PRD §3.7: "A `PublicWorksEngineer` closes a `RESTORED` break only when
    no advisory for the break remains `ISSUED` (otherwise
    `ERR_ADVISORY_STILL_ACTIVE`) and no claim for the break remains `SUBMITTED`
    or `APPROVED` (otherwise `ERR_CLAIMS_OPEN`). `CLOSED` is terminal."

    Design: Corner/validations/close_blocked_by_active_advisory
    """
    # Extent 550 -> auto advisory ISSUED; repair and restore complete.
    ctx = setup_restored_break(
        segment_ref="MAIN-8-CEDAR", diameter_inches=8, install_year=1970,
        valve_specs=[
            {"valve_code": "V-CED-1", "coverage_zone": "Z1", "customers_served": 300},
            {"valve_code": "V-CED-2", "coverage_zone": "Z2", "customers_served": 250},
        ],
        break_type="CIRCUMFERENTIAL", severity="HIGH",
        location_description="5 Cedar Rd", source="SENSOR_SCADA",
        crew_name="Crew Cedar", crew_size=4, crew_rate=6000,
        permit_block="CEDAR-5-BLK",
        valid_from="2026-08-01T00:00:00Z", valid_to="2026-08-31T00:00:00Z",
        scheduled_start="2026-08-03T08:00:00Z",
        scheduled_end="2026-08-03T16:00:00Z",
    )
    br = ctx["break"]
    assert br["break_status"] == "RESTORED", (
        f"break must be RESTORED before the close attempt, got {br['break_status']!r}"
    )
    resp = _api.close_break_report(br["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_ADVISORY_STILL_ACTIVE)
    assert get_break(br["id"])["break_status"] == "RESTORED"


# ---------------------------------------------------------------------------
# Corner: close_blocked_by_open_claim_then_succeeds
# ---------------------------------------------------------------------------

def test_close_blocked_by_open_claim_then_succeeds(api):
    """PRD §3.7: "A `PublicWorksEngineer` closes a `RESTORED` break only when
    no advisory for the break remains `ISSUED` (otherwise
    `ERR_ADVISORY_STILL_ACTIVE`) and no claim for the break remains `SUBMITTED`
    or `APPROVED` (otherwise `ERR_CLAIMS_OPEN`). `CLOSED` is terminal."
    PRD §3.7: "Denying moves a `SUBMITTED` claim to `DENIED` (terminal) with no
    fiscal effect."

    Design: Corner/validations/close_blocked_by_open_claim_then_succeeds
    """
    ctx = setup_restored_break(
        segment_ref="MAIN-8-PINE", diameter_inches=8, install_year=1975,
        break_type="CIRCUMFERENTIAL", severity="MEDIUM",
        location_description="9 Pine Ct",
        crew_name="Crew Pine", crew_rate=6000,
        permit_block="PINE-9-BLK",
        valid_from="2026-08-01T00:00:00Z", valid_to="2026-08-31T00:00:00Z",
        scheduled_start="2026-08-03T08:00:00Z",
        scheduled_end="2026-08-03T16:00:00Z",
    )
    br = ctx["break"]
    assert br["break_status"] == "RESTORED"
    claim = create_claim(br["id"], claimant_name="J. Homeowner",
                         claimed_amount_cents=100000)

    resp = _api.close_break_report(br["id"], ENGINEER)
    validate_error(resp, ApiErrorId.ERR_CLAIMS_OPEN)

    denied = validate_success(_api.deny_damage_claim(claim["id"], ADJUSTER), 200)
    assert denied["claim_status"] == "DENIED"

    closed = validate_success(_api.close_break_report(br["id"], ENGINEER), 200)
    assert closed["break_status"] == "CLOSED", (
        "once the claim is terminal the close must succeed"
    )


# ---------------------------------------------------------------------------
# Corner: dispatcher_cannot_approve_claim_forbidden
# ---------------------------------------------------------------------------

def test_dispatcher_cannot_approve_claim_forbidden(api):
    """PRD §2.1: "If the named role is not in the endpoint's authorized role
    list — or, for the crew-ownership actions described in §3.4, the calling
    user's identity does not match the work order's assigned crew — the request
    is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.7: "Decisions belong to the `ClaimsAdjuster`."

    Design: Corner/rbac/dispatcher_cannot_approve_claim_forbidden
    """
    ctx = setup_confirmed_break(
        segment_ref="MAIN-8-OAK", material="PVC", diameter_inches=8,
        install_year=1999, break_type="SPLIT", severity="LOW",
        location_description="12 Oak St",
    )
    claim = create_claim(ctx["break"]["id"], claimant_name="J. Homeowner",
                         claimed_amount_cents=100000)
    resp = _api.approve_damage_claim(
        claim["id"], {"approved_amount_cents": 50000}, DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


# ---------------------------------------------------------------------------
# Corner: break_cost_rollup_sum_of_components
# ---------------------------------------------------------------------------

def test_break_cost_rollup_sum_of_components(api):
    """PRD §3.7: "`total_repair_cost_cents` is the sum of `actual_cost_cents`
    over the break's `REPAIR_COMPLETE` work orders.
    `total_restoration_cost_cents` is the sum of `patch_cost_cents` over the
    break's `COMPLETED` restoration jobs. `claims_liability_cents` is the sum
    of `approved_amount_cents` over claims currently in `APPROVED` status — it
    excludes `PAID` and `VOIDED` claims. `total_claims_paid_cents` is the sum
    of `approved_amount_cents` over claims in `PAID` status. `total_cost_cents`
    is the sum of `total_repair_cost_cents`, `total_restoration_cost_cents`,
    and `total_claims_paid_cents` — note that open liability is deliberately
    excluded from the headline cost figure."

    Design: Corner/calculations/break_cost_rollup_sum_of_components
    """
    # Repair (actual 61000) + restoration patch 23000.
    ctx = setup_restored_break(
        segment_ref="MAIN-8-PINE", diameter_inches=8, install_year=1975,
        break_type="CIRCUMFERENTIAL", severity="MEDIUM",
        location_description="9 Pine Ct",
        crew_name="Crew Pine", crew_rate=6000,
        materials_used=[{"item_code": "PIPE-8IN", "quantity": 1,
                         "unit_price_cents": 50000}],
        permit_block="PINE-9-BLK", patch_cost_cents=23000,
        valid_from="2026-08-02T00:00:00Z", valid_to="2026-08-20T00:00:00Z",
        scheduled_start="2026-08-03T08:00:00Z",
        scheduled_end="2026-08-03T16:00:00Z",
    )
    br = ctx["break"]

    # Claim X: approved 60000 then PAID.
    cl_x = create_claim(br["id"], claimant_name="A. Owner",
                        claimed_amount_cents=80000)
    approve_claim(cl_x["id"], 60000)
    validate_success(_api.pay_damage_claim(cl_x["id"], ADJUSTER), 200)

    # Claim Y: approved 45000, left APPROVED (open liability).
    cl_y = create_claim(br["id"], claimant_name="B. Owner",
                        claimed_amount_cents=50000)
    approve_claim(cl_y["id"], 45000)

    final = get_break(br["id"])
    assert final["total_repair_cost_cents"] == 61000
    assert final["total_restoration_cost_cents"] == 23000
    assert final["total_claims_paid_cents"] == 60000
    assert final["claims_liability_cents"] == 45000, (
        "approved-but-unpaid claim stays in liability and out of paid totals"
    )
    assert final["total_cost_cents"] == 144000, (
        f"total = repair 61000 + restoration 23000 + paid 60000 = 144000, "
        f"got {final['total_cost_cents']}"
    )
