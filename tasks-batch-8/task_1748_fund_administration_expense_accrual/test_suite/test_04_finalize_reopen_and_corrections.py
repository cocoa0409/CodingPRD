"""Finalize/reopen lifecycle, price gates, OCC/SoD guards, and the override
correction cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_money,
    assert_rate,
    base_kit_with_final_nav,
    base_kit_with_nav,
    create_fund,
    create_nav,
    create_security,
    create_share_class,
    finalize_nav,
    open_position,
    set_logical_clock,
    submit_price,
    approve_price,
    subscribe_shares,
    make_fund_accountant_headers,
    make_fund_controller_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CTRL = TEST_USERS["fund_controller_headers"]
ACCT = TEST_USERS["fund_accountant_headers"]
PC = TEST_USERS["pricing_committee_headers"]


def test_finalize_reopen_finalize_status_cycle(api):
    """PRD §3.6: "Finalization is the `FundController`'s sign-off, moving a
    record from `ESTIMATED` to `FINAL` — or, after a correction, from
    `REOPENED` back to `FINAL`; requesting it from any other state is an
    `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.6: "Reopening returns the date's accrual rows from `POSTED` to
    `ESTIMATED`, recomputes the record under the `FINAL_PRICED` variant, and
    increments its `version`."

    Design: Difficulty/non_linear_state_machine/nav_record_finalize_reopen_cycle
    """
    kit = base_kit_with_nav(approve=True)
    nav_id = kit["nav"]["id"]

    fin1 = finalize_nav(nav_id, expected_version=kit["nav"]["version"])
    assert fin1["status"] == "FINAL"

    re = validate_success(api.reopen_nav_record(nav_id, CTRL), 200)
    assert re["status"] == "REOPENED"

    fin2 = finalize_nav(nav_id, expected_version=re["version"])
    assert fin2["status"] == "FINAL"


def test_finalize_reopen_cycle_versions_and_idempotent_nav(api):
    """PRD §2.5: "`version` (integer): a system-managed integer that increments
    by one on every mutation — including mutations caused by cascade
    recomputation rather than by a direct client write."
    PRD §3.6: "A successful finalization recomputes every computed field under
    the `FINAL_PRICED` variant and flips `pricing_variant_used` accordingly"

    Design: Difficulty/non_linear_state_machine/nav_record_finalize_reopen_cycle
    """
    kit = base_kit_with_nav(approve=True)
    nav_id = kit["nav"]["id"]
    v1 = kit["nav"]["version"]

    fin1 = finalize_nav(nav_id, expected_version=v1)
    assert fin1["version"] == v1 + 1
    re = validate_success(api.reopen_nav_record(nav_id, CTRL), 200)
    assert re["version"] == v1 + 2
    fin2 = finalize_nav(nav_id, expected_version=re["version"])
    assert fin2["version"] == v1 + 3
    # Unchanged inputs recompute to the same per-share NAV.
    assert_rate(fin2["nav_per_share"], 10.0000, "nav_per_share")
    assert fin2["pricing_variant_used"] == "FINAL_PRICED"


def test_finalize_blocked_by_submitted_price(api):
    """PRD §3.6: "And pricing must be clean: no security held in an `OPEN`
    position may still have a `SUBMITTED` observation outstanding on the
    `accounting_date`, and every such security must have at least one
    `APPROVED` observation for that date — either failure is rejected with
    `ERR_PRICE_NOT_APPROVED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/finalize_requires_all_prices_approved
    """
    kit = base_kit_with_nav(approve=False)  # observation stays SUBMITTED
    resp = api.finalize_nav_record(
        kit["nav"]["id"],
        {"expected_nav_record_version": kit["nav"]["version"]},
        make_fund_controller_headers("ctl_1"),
    )
    validate_error(resp, ApiErrorId.ERR_PRICE_NOT_APPROVED, 409)


def test_finalize_succeeds_after_price_approval(api):
    """PRD §3.3: "Approval moves a `SUBMITTED` observation to `APPROVED` and
    recomputes the `ESTIMATED` accounting record (if any) of each class holding
    the security on the observation's `price_date`, incrementing that record's
    `version` by one."
    PRD §3.6: "every such security must have at least one `APPROVED`
    observation for that date — either failure is rejected with
    `ERR_PRICE_NOT_APPROVED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/finalize_requires_all_prices_approved
    """
    kit = base_kit_with_nav(approve=False)
    approve_price(kit["observation"]["id"])
    fresh = validate_success(api.get_nav_record(kit["nav"]["id"], CTRL), 200)
    fin = finalize_nav(kit["nav"]["id"], expected_version=fresh["version"])
    assert fin["status"] == "FINAL"


def test_finalize_state_violation_masks_price_constraint(api):
    """PRD §2.9: "Every request is validated in a fixed order, and the first
    failing check determines the error response — later checks never mask
    earlier ones."
    PRD §2.9: "5. State eligibility of the target resource for the requested
    transition — `ERR_INVALID_STATE` (HTTP 409)"
    PRD §2.9: "10. Uniqueness and business-constraint checks — duplicate
    tickers, non-sequential accounting dates, duplicate price sources, reserved
    price sources, missing prices, unapproved prices, non-estimable accrual
    dates, system-managed accrual categories, overlapping cap agreements,
    non-contiguous fee periods, absent final records, zero-variance breaks,
    misordered distribution dates, and reopen guards."

    Design: Difficulty/priority_pair_validation_conflict/finalize_conflict_state_beats_price_constraint
    """
    kit = base_kit_with_final_nav()  # record already FINAL
    # A new SUBMITTED observation lands on the same security/date; the FINAL
    # record is not recomputed by submissions.
    submit_price(kit["security"]["id"], price=99.00, source="BROKER_QUOTE",
                 pricing_level="LEVEL_2")
    fresh = validate_success(api.get_nav_record(kit["nav"]["id"], CTRL), 200)
    resp = api.finalize_nav_record(
        kit["nav"]["id"],
        {"expected_nav_record_version": fresh["version"]},
        make_fund_controller_headers("ctl_1"),
    )
    # State check (FINAL is not finalizable) fires before the price constraint.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_price_constraint_fires_in_isolation(api):
    """PRD §2.9: "Every request is validated in a fixed order, and the first
    failing check determines the error response — later checks never mask
    earlier ones."
    PRD §3.6: "And pricing must be clean: no security held in an `OPEN`
    position may still have a `SUBMITTED` observation outstanding on the
    `accounting_date`, and every such security must have at least one
    `APPROVED` observation for that date — either failure is rejected with
    `ERR_PRICE_NOT_APPROVED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/finalize_conflict_state_beats_price_constraint
    """
    # Isolated single failure: record is ESTIMATED (state allows finalize)
    # and the only problem is the SUBMITTED observation.
    kit = base_kit_with_nav(approve=False)
    resp = api.finalize_nav_record(
        kit["nav"]["id"],
        {"expected_nav_record_version": kit["nav"]["version"]},
        make_fund_controller_headers("ctl_1"),
    )
    validate_error(resp, ApiErrorId.ERR_PRICE_NOT_APPROVED, 409)


def test_accrual_posted_on_finalize_and_restored_on_reopen(api):
    """PRD §3.6: "moves the date's accrual rows from `ESTIMATED` to `POSTED`,
    so they are included in the record's `expense_accrual_total` as posted"
    PRD §3.6: "Reopening returns the date's accrual rows from `POSTED` to
    `ESTIMATED`, recomputes the record under the `FINAL_PRICED` variant, and
    increments its `version`."

    Design: Corner/state_machines/accrual_posted_on_finalize_and_restored_on_reopen
    """
    kit = base_kit_with_nav(approve=True)
    finalize_nav(kit["nav"]["id"], expected_version=kit["nav"]["version"])

    accruals, _ = validate_paginated(
        api.list_expense_accruals(
            CTRL, params={"share_class_id": kit["share_class"]["id"],
                          "accrual_date": "2026-08-04"})
    )
    assert len(accruals) >= 1
    assert all(a["status"] == "POSTED" for a in accruals)

    reopen = validate_success(api.reopen_nav_record(kit["nav"]["id"], CTRL), 200)
    assert reopen["status"] == "REOPENED"
    accruals2, _ = validate_paginated(
        api.list_expense_accruals(
            CTRL, params={"share_class_id": kit["share_class"]["id"],
                          "accrual_date": "2026-08-04"})
    )
    assert all(a["status"] == "ESTIMATED" for a in accruals2)


def test_nav_reopen_not_latest_rejected(api):
    """PRD §3.6: "A `FundController` may reopen a `FINAL` record, moving it to
    `REOPENED`, but only the class's latest record — the one with the greatest
    `accounting_date` — is eligible, anything older being rejected with
    `ERR_NAV_NOT_LATEST` (HTTP 409)"

    Design: Corner/validations/nav_reopen_not_latest_rejected
    """
    kit = base_kit_with_final_nav()  # 2026-08-04 FINAL
    set_logical_clock("2026-08-05T00:00:00Z")
    px2 = submit_price(kit["security"]["id"], price_date="2026-08-05")
    approve_price(px2["id"])
    nav2 = create_nav(kit["share_class"]["id"], accounting_date="2026-08-05")
    finalize_nav(nav2["id"], expected_version=nav2["version"])

    resp = api.reopen_nav_record(kit["nav"]["id"], CTRL)
    validate_error(resp, ApiErrorId.ERR_NAV_NOT_LATEST, 409)


def test_price_override_reopens_final_nav(api):
    """PRD §3.6: "when a fair-value override (§3.3) lands on an observation
    whose `price_date` equals the accounting date of a holding class's `FINAL`
    record that is also that class's latest record, the record is forced from
    `FINAL` to `REOPENED` and recomputed under `FINAL_PRICED` with the newly
    selected price, its `version` incrementing."
    PRD §3.3: "the new observation carries the reserved `FAIR_VALUE_COMMITTEE`
    source, an `is_fair_value_override` flag of true, an immediate `APPROVED`
    status, the same `security_id` and `price_date` as the original, a `price`
    equal to the supplied `override_price`, and the supplied `pricing_level`."

    Design: Corner/complexity_layers/price_override_reopens_final_nav
    """
    kit = base_kit_with_final_nav()  # FINAL at version v; GAV 100000.00
    nav_id = kit["nav"]["id"]
    v_final = kit["nav"]["version"]

    resp = api.override_price_observation(
        kit["observation"]["id"],
        {"override_price": 120.00, "pricing_level": "LEVEL_3"},
        PC,
    )
    new_obs = validate_success(resp, 201)
    assert new_obs["source"] == "FAIR_VALUE_COMMITTEE"
    assert new_obs["is_fair_value_override"] is True
    assert new_obs["status"] == "APPROVED"
    assert new_obs["security_id"] == kit["security"]["id"]
    assert new_obs["price_date"] == "2026-08-04"

    nav = validate_success(api.get_nav_record(nav_id, CTRL), 200)
    assert nav["status"] == "REOPENED"
    assert_money(nav["gross_asset_value"], 120000.00, "gross_asset_value")
    # First-record base rule: accrual recomputes off the new GAV.
    assert_money(nav["expense_accrual_total"], 0.33, "expense_accrual_total")
    assert nav["version"] == v_final + 1

    overridden, meta = validate_paginated(
        api.list_security_prices(
            kit["security"]["id"], CTRL,
            params={"price_date": "2026-08-04", "status": "OVERRIDDEN"})
    )
    assert meta["total_count"] == 1
    assert overridden[0]["source"] == "EXCHANGE_CLOSE"
    assert overridden[0]["id"] == kit["observation"]["id"]


def test_accountant_cannot_finalize_nav(api):
    """PRD §2.1: "A request whose role is not among the roles authorized for
    the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "A `FundController` holds approval and control authority: fund
    and share-class setup, accounting-record finalization and reopening, waiver
    agreements and recoupments, distribution payment and cancellation, break
    resolution and escalation, fee-invoice approval and payment, filing
    approval, and the fiscal-year close."

    Design: Corner/rbac/accountant_cannot_finalize_nav
    """
    kit = base_kit_with_nav(approve=True)
    resp = api.finalize_nav_record(
        kit["nav"]["id"],
        {"expected_nav_record_version": kit["nav"]["version"]},
        make_fund_accountant_headers("acct_1"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    nav = validate_success(api.get_nav_record(kit["nav"]["id"], CTRL), 200)
    assert nav["status"] == "ESTIMATED"


def test_sod_same_user_finalize_rejected(api):
    """PRD §2.7: "On each, the caller's `X-User-ID` must differ from the
    identifier of the user who prepared the resource — the accounting record's
    `created_by_user_id`, the invoice's `created_by_user_id`, or the filing's
    `prepared_by_user_id`. A caller who prepared the resource is rejected with
    `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/sod_same_user_finalize_rejected
    """
    set_logical_clock("2026-08-04T00:00:00Z")
    fund = create_fund()
    share_class = create_share_class(fund["id"])
    subscribe_shares(share_class["id"], 10000, user_id="alice")
    security = create_security()
    open_position(share_class["id"], security["id"], quantity=1000,
                  user_id="alice")
    obs = submit_price(security["id"], user_id="alice")
    approve_price(obs["id"])
    nav = create_nav(share_class["id"], user_id="alice")
    assert nav["created_by_user_id"] == "alice"

    same_user = api.finalize_nav_record(
        nav["id"], {"expected_nav_record_version": nav["version"]},
        make_fund_controller_headers("alice"),
    )
    validate_error(same_user, ApiErrorId.ERR_SOD_VIOLATION, 403)

    other = api.finalize_nav_record(
        nav["id"], {"expected_nav_record_version": nav["version"]},
        make_fund_controller_headers("bob"),
    )
    assert validate_success(other, 200)["status"] == "FINAL"
