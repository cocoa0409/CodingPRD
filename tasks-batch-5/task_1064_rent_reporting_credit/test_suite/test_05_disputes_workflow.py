"""Disputes: the cyclic REPORTED->DISPUTED->REPORTED loop, the INVESTIGATING fork
(CORRECTED vs UPHELD), the correction/supersede recompute, the conserved effective
count, segregation of duties, and the item-not-disputable state precedence.

Covers the dispute revision loop, the correction/upheld fork, the conserved
effective count, segregation of duties, and item-not-disputable precedence.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_tenant_headers, make_officer_headers,
    create_dispute_payload,
    reset_clock_default, set_clock, create_tenant,
    setup_reported_item, setup_disputed_item, setup_investigating_dispute,
)

TENANT_KEY = "tenant"
OFFICER = TEST_USERS["officer_headers"]  # officer-1
ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / REPORTED->DISPUTED->REPORTED cycle
# --------------------------------------------------------------------------
def test_withdraw_reinstates_item_to_reported(api):
    """PRD §3.7: "Withdrawal is valid from either `OPEN` or `INVESTIGATING`, moves
    the dispute to the terminal `WITHDRAWN`, reinstates the tradeline from
    `DISPUTED` back to `REPORTED`, and recomputes the rate."

    Design: Difficulty/non_linear_state_machine/reported_item_cycle_reported_disputed_reported
    """
    ctx = setup_disputed_item(api, reason_code="PAID_ON_TIME", property_address="3 Pine Rd")
    th = make_tenant_headers(ctx["tenant"]["id"])
    dispute = validate_success(api.withdraw_dispute(th, ctx["dispute"]["id"]), 200)
    assert dispute["status"] == "WITHDRAWN"
    item = validate_success(api.get_reported_item(th, ctx["item"]["id"]), 200)
    assert item["status"] == "REPORTED"


def test_dispute_cycle_increments_item_version(api):
    """PRD §3.7: "moves the tradeline from `REPORTED` to `DISPUTED`, incrementing
    that item's `version` by one."
    PRD §2.7: "each hop independently mutates the entity it touches — refreshing
    `updated_at` and incrementing `version` where those fields exist."

    Design: Difficulty/non_linear_state_machine/reported_item_cycle_reported_disputed_reported
    """
    ctx = setup_disputed_item(api, reason_code="PAID_ON_TIME", property_address="3b Pine Rd")
    th = make_tenant_headers(ctx["tenant"]["id"])
    validate_success(api.withdraw_dispute(th, ctx["dispute"]["id"]), 200)
    item = validate_success(api.get_reported_item(th, ctx["item"]["id"]), 200)
    # created(1) -> disputed(2) -> reinstated(3)
    assert item["version"] >= 3


# --------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / INVESTIGATING -> RESOLVED_CORRECTED fork
# --------------------------------------------------------------------------
def test_resolve_corrected_sets_dispute_and_item_states(api):
    """PRD §3.7: "A `CORRECTED` resolution moves the dispute to the terminal
    `RESOLVED_CORRECTED`, moves the disputed tradeline from `DISPUTED` to
    `CORRECTED`, and creates a superseding replacement tradeline in `REPORTED`
    status".

    Design: Difficulty/non_linear_state_machine/dispute_branching_investigating_to_corrected
    """
    ctx = setup_investigating_dispute(api, reason_code="PAID_ON_TIME",
                                      paid_date="2026-06-20T00:00:00Z", property_address="5 Elm St")
    th = make_tenant_headers(ctx["tenant"]["id"])
    resolved = validate_success(api.resolve_dispute(
        OFFICER, ctx["dispute"]["id"], {"resolution": "CORRECTED", "corrected_on_time": True}), 200)
    assert resolved["status"] == "RESOLVED_CORRECTED"
    item = validate_success(api.get_reported_item(th, ctx["item"]["id"]), 200)
    assert item["status"] == "CORRECTED"


def test_resolve_corrected_creates_superseding_item(api):
    """PRD §3.7: "creates a superseding replacement tradeline in `REPORTED` status
    whose `supersedes_item_id` points back at the corrected original, inheriting
    the original's `source` but carrying the corrected `on_time` and
    `amount_reported_cents` from `corrected_on_time` and `corrected_amount_cents`."

    Design: Difficulty/non_linear_state_machine/dispute_branching_investigating_to_corrected
    """
    ctx = setup_investigating_dispute(api, reason_code="PAID_ON_TIME",
                                      paid_date="2026-06-20T00:00:00Z", property_address="5b Elm St")
    th = make_tenant_headers(ctx["tenant"]["id"])
    validate_success(api.resolve_dispute(
        OFFICER, ctx["dispute"]["id"], {"resolution": "CORRECTED", "corrected_on_time": True}), 200)
    data, _ = validate_paginated(api.list_reported_items(th, params={"supersedes_item_id": ctx["item"]["id"]}))
    assert len(data) == 1
    assert data[0]["status"] == "REPORTED"
    assert data[0]["on_time"] is True


# --------------------------------------------------------------------------
# Difficulty: transitive_cascade / correction supersedes + rate recompute
# --------------------------------------------------------------------------
def test_correction_recomputes_reported_rate_to_100(api):
    """PRD §3.7: "the rate is recomputed to reflect the corrected on-time value."
    PRD §3.9: "The **as-reported** rate ranges only over the tenant's effective
    tradelines, those reported items whose `status` is `REPORTED` or `DISPUTED`:
    if there are none the variant is null, otherwise it is one hundred times the
    number of effective tradelines whose `on_time` snapshot is true divided by the
    count of effective tradelines, rounded half up to a whole percent."

    Design: Difficulty/transitive_cascade/correction_supersedes_item_and_recomputes_rate
    """
    ctx = setup_investigating_dispute(api, reason_code="PAID_ON_TIME",
                                      paid_date="2026-06-25T00:00:00Z", property_address="8 Cedar Ct")
    th = make_tenant_headers(ctx["tenant"]["id"])
    validate_success(api.resolve_dispute(
        OFFICER, ctx["dispute"]["id"], {"resolution": "CORRECTED", "corrected_on_time": True}), 200)
    summary = validate_success(api.get_credit_summary(th, ctx["tenant"]["id"]), 200)
    assert summary["on_time_rate_as_reported_pct"] == 100


def test_correction_keeps_effective_count_at_one(api):
    """PRD §3.7: "Because the corrected item leaves the effective set as the
    superseding item enters it, the tenant's effective count nets out unchanged".

    Design: Difficulty/transitive_cascade/correction_supersedes_item_and_recomputes_rate
    """
    ctx = setup_investigating_dispute(api, reason_code="PAID_ON_TIME",
                                      paid_date="2026-06-25T00:00:00Z", property_address="8b Cedar Ct")
    th = make_tenant_headers(ctx["tenant"]["id"])
    validate_success(api.resolve_dispute(
        OFFICER, ctx["dispute"]["id"], {"resolution": "CORRECTED", "corrected_on_time": True}), 200)
    summary = validate_success(api.get_credit_summary(th, ctx["tenant"]["id"]), 200)
    assert summary["effective_reported_items"] == 1


# --------------------------------------------------------------------------
# Difficulty: compensating_invariant / correction conserves effective count
# --------------------------------------------------------------------------
def test_correction_conserves_effective_count(api):
    """PRD §3.7: "Because the corrected item leaves the effective set as the
    superseding item enters it, the tenant's effective count nets out unchanged".

    Design: Difficulty/compensating_invariant/correction_conserves_effective_furnished_count
    """
    ctx = setup_investigating_dispute(api, reason_code="PAID_ON_TIME",
                                      paid_date="2026-06-25T00:00:00Z", property_address="24 Count Rd")
    th = make_tenant_headers(ctx["tenant"]["id"])
    validate_success(api.resolve_dispute(
        OFFICER, ctx["dispute"]["id"], {"resolution": "CORRECTED", "corrected_on_time": True}), 200)
    summary = validate_success(api.get_credit_summary(th, ctx["tenant"]["id"]), 200)
    assert summary["effective_reported_items"] == 1


def test_correction_supersede_points_at_original(api):
    """PRD §3.7: "creates a superseding replacement tradeline in `REPORTED` status
    whose `supersedes_item_id` points back at the corrected original".

    Design: Difficulty/compensating_invariant/correction_conserves_effective_furnished_count
    """
    ctx = setup_investigating_dispute(api, reason_code="PAID_ON_TIME",
                                      paid_date="2026-06-25T00:00:00Z", property_address="24b Count Rd")
    th = make_tenant_headers(ctx["tenant"]["id"])
    validate_success(api.resolve_dispute(
        OFFICER, ctx["dispute"]["id"], {"resolution": "CORRECTED", "corrected_on_time": True}), 200)
    original = validate_success(api.get_reported_item(th, ctx["item"]["id"]), 200)
    assert original["status"] == "CORRECTED"
    data, _ = validate_paginated(api.list_reported_items(
        th, params={"tenant_id": ctx["tenant"]["id"], "status": "REPORTED"}))
    assert len(data) == 1
    assert data[0]["supersedes_item_id"] == ctx["item"]["id"]


# --------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / state beats window
# --------------------------------------------------------------------------
def test_second_dispute_on_disputed_item_returns_not_disputable(api):
    """PRD §3.7: "a tradeline that is already `DISPUTED`, `CORRECTED`, or
    `RETRACTED` cannot be disputed and is rejected with `ERR_ITEM_NOT_DISPUTABLE`."

    Design: Difficulty/priority_pair_validation_conflict/item_not_disputable_state_beats_dispute_window_temporal
    """
    ctx = setup_disputed_item(api, reason_code="NOT_MINE", property_address="2 Maple Dr")
    th = make_tenant_headers(ctx["tenant"]["id"])
    set_clock(api, "2026-10-15T00:00:00Z")  # also past the dispute window
    resp = api.create_dispute(th, create_dispute_payload(ctx["item"]["id"], "PAID_ON_TIME"))
    validate_error(resp, ApiErrorId.ERR_ITEM_NOT_DISPUTABLE.value, 409)


def test_rejected_second_dispute_creates_no_new_dispute(api):
    """PRD §3.7: "On a valid filing the server creates the dispute in `OPEN`
    status" — a filing rejected with `ERR_ITEM_NOT_DISPUTABLE` creates none, so the
    item still has exactly the one original dispute.

    Design: Difficulty/priority_pair_validation_conflict/item_not_disputable_state_beats_dispute_window_temporal
    """
    ctx = setup_disputed_item(api, reason_code="NOT_MINE", property_address="2b Maple Dr")
    th = make_tenant_headers(ctx["tenant"]["id"])
    set_clock(api, "2026-10-15T00:00:00Z")
    validate_error(api.create_dispute(th, create_dispute_payload(ctx["item"]["id"], "PAID_ON_TIME")),
                   ApiErrorId.ERR_ITEM_NOT_DISPUTABLE.value, 409)
    data, _ = validate_paginated(api.list_disputes(th, params={"reported_item_id": ctx["item"]["id"]}))
    assert len(data) == 1


# --------------------------------------------------------------------------
# Corner: UPHELD reinstates, no superseding item
# --------------------------------------------------------------------------
def test_resolve_upheld_reinstates_without_supersede(api):
    """PRD §3.7: "An `UPHELD` resolution instead moves the dispute to the terminal
    `RESOLVED_UPHELD` and reinstates the tradeline from `DISPUTED` back to
    `REPORTED`, restoring its `bureau_statuses` to `FURNISHED`".

    Design: Corner/state_machines/dispute_upheld_reinstates_reported_item
    """
    ctx = setup_investigating_dispute(api, reason_code="NOT_MINE", property_address="32 Uphold Rd")
    th = make_tenant_headers(ctx["tenant"]["id"])
    resolved = validate_success(api.resolve_dispute(OFFICER, ctx["dispute"]["id"], {"resolution": "UPHELD"}), 200)
    assert resolved["status"] == "RESOLVED_UPHELD"
    item = validate_success(api.get_reported_item(th, ctx["item"]["id"]), 200)
    assert item["status"] == "REPORTED"
    data, _ = validate_paginated(api.list_reported_items(th, params={"supersedes_item_id": ctx["item"]["id"]}))
    assert len(data) == 0


# --------------------------------------------------------------------------
# Corner: resolving an OPEN (never investigated) dispute is invalid
# --------------------------------------------------------------------------
def test_resolve_from_open_returns_invalid_state(api):
    """PRD §3.7: "Resolution is the officer's act and is only valid from
    `INVESTIGATING`".

    Design: Corner/state_machines/resolve_from_open_returns_invalid_state
    """
    ctx = setup_disputed_item(api, reason_code="NOT_MINE", property_address="31 Open Ave")
    resp = api.resolve_dispute(OFFICER, ctx["dispute"]["id"], {"resolution": "UPHELD"})
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# --------------------------------------------------------------------------
# Corner: segregation of duties
# --------------------------------------------------------------------------
def test_resolve_by_investigating_operator_returns_sod(api):
    """PRD §2.8: "When an officer later resolves the dispute, the server checks
    that the officer's `X-User-ID` is not equal to that recorded `analyst_user_id`;
    if they are the same operator, the resolution is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/sod_resolve_by_same_operator_returns_error
    """
    ctx = setup_investigating_dispute(api, analyst_user_id="analyst-1",
                                      reason_code="NOT_MINE", property_address="42 SoD Way")
    # same operator id as the analyst, but acting in the officer role
    resp = api.resolve_dispute(make_officer_headers("analyst-1"), ctx["dispute"]["id"], {"resolution": "UPHELD"})
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)
