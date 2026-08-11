"""Volunteer shifts, the coordinator commission bands and the payout modes."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_commission_accrual,
    assert_credit_grant,
    assert_volunteer_shift,
    canonical_world,
    create_volunteer_shift_payload,
    find_accrual,
    make_coordinator_headers,
    payout_payload,
    rice_world,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["club_admin_headers"]
FINANCE = TEST_USERS["finance_headers"]


# ------------------------------------------------------ commission bands ---
def test_commission_selects_a_flat_band_then_multiplies_by_the_volunteer_factor(api):
    """PRD §3.9: "The band is selected by that base and applied **flat**, not
    marginally: a base of at most 100000 cents takes a `rate_applied` of 0.03, a base
    above 100000 and at most 300000 cents takes 0.05, and a base above 300000 cents
    takes 0.07, and the whole base is then multiplied by that single rate."
    PRD §3.9: "The `volunteer_multiplier_applied` is 1.00 when the drop run's
    `volunteer_obligation_met` is true and 0.50 when it is not — a drop that never
    mustered four verified volunteer hours halves its coordinator's pay."
    PRD §3.9: "`accrued_cents` is `base_subtotal_cents` multiplied by `rate_applied`
    multiplied by `volunteer_multiplier_applied`, with exactly one rounding half up
    applied to the whole product rather than one per factor."

    Design: Difficulty/combinatorial_formula/commission_selects_a_flat_band_then_multiplies_by_the_volunteer_factor
    """
    w = canonical_world(api, "delivered", with_volunteer_shift=False)
    accrual = find_accrual(api, w)

    assert_commission_accrual(accrual)
    assert accrual["base_subtotal_cents"] == 71332
    assert accrual["rate_applied"] == 0.03
    assert accrual["volunteer_multiplier_applied"] == 0.5
    assert accrual["accrued_cents"] == 1070
    assert accrual["clawback_cents"] == 0
    assert accrual["net_cents"] == 1070
    assert accrual["status"] == "ACCRUED"

    assert (
        validate_success(api.get_drop_run(w.drop_run_id, ADMIN))["volunteer_obligation_met"]
        is False
    )


def test_a_met_volunteer_obligation_doubles_the_same_band_one_accrual(api):
    """PRD §3.9: "Commission itself is accrued at delivery, one accrual per settled
    drop run carrying a non-null `coordinator_member_id`, written in ascending
    `created_at` order of the drop runs. The accrual records its `drop_run_id`, its
    `coordinator_member_id`, and a `base_subtotal_cents` copied from the drop run's
    `received_subtotal_cents` at accrual time — the value of what was actually
    delivered, at list prices, **before** any tier discount."
    PRD §2.7: "**Volunteer obligation.** A drop run's volunteer obligation is met
    when its `verified_volunteer_hours` is at least 4.0. Inclusive."

    Design: Difficulty/combinatorial_formula/commission_selects_a_flat_band_then_multiplies_by_the_volunteer_factor
    """
    w = canonical_world(api, "delivered")
    accrual = find_accrual(api, w)

    assert accrual["base_subtotal_cents"] == 71332
    assert accrual["rate_applied"] == 0.03
    assert accrual["volunteer_multiplier_applied"] == 1.0
    assert accrual["accrued_cents"] == 2140
    assert accrual["net_cents"] == 2140
    assert accrual["coordinator_member_id"] == w.cora_id

    drop_run = validate_success(api.get_drop_run(w.drop_run_id, ADMIN))
    assert drop_run["verified_volunteer_hours"] == 4.0
    assert drop_run["volunteer_obligation_met"] is True


def test_commission_band_three_applies_a_flat_seven_percent_to_the_whole_base(api):
    """PRD §3.9: "The band is selected by that base and applied **flat**, not
    marginally: a base of at most 100000 cents takes a `rate_applied` of 0.03, a base
    above 100000 and at most 300000 cents takes 0.05, and a base above 300000 cents
    takes 0.07, and the whole base is then multiplied by that single rate."

    Design: Corner/calculations/commission_band_three_applies_a_flat_seven_percent_to_the_whole_base
    """
    w = rice_world(
        api,
        qty_units=38,
        cases_received=19,
        supplier_invoice_cents=760000,
        stage="delivered",
    )
    accrual = find_accrual(api, w)

    assert (
        validate_success(api.get_drop_run(w.drop_run_id, ADMIN))["received_subtotal_cents"]
        == 760000
    )
    assert accrual["base_subtotal_cents"] == 760000
    assert accrual["rate_applied"] == 0.07
    assert accrual["volunteer_multiplier_applied"] == 0.5
    assert accrual["accrued_cents"] == 26600
    assert accrual["net_cents"] == 26600
    assert accrual["status"] == "ACCRUED"


# ------------------------------------------------------------- payouts -----
def test_commission_payout_in_store_credit_carries_a_ten_percent_bonus(api):
    """PRD §3.9: "Under `STORE_CREDIT`, `payout_value_cents` is `net_cents`
    multiplied by 1.10, rounded half up to the whole cent — a ten-percent bonus — and
    a credit grant with `source` `COMMISSION` is minted for that value, expiring 180
    days after the current clock reading."
    PRD §3.9: "Paying a coordinator is available only once the drop run's
    reconciliation has status `POSTED` and the accrual is in `ACCRUED` or `ADJUSTED`;
    it moves the accrual to `PAID` from either state, computing the payout on
    whichever `net_cents` is current."

    Design: Difficulty/dual_variant_calc/commission_payout_store_credit_bonus_diverges_from_cash_fee
    """
    w = canonical_world(api, "recon_posted")
    accrual = find_accrual(api, w)
    assert accrual["net_cents"] == 2140

    paid = validate_success(
        api.payout_commission_accrual(accrual["id"], payout_payload("STORE_CREDIT"), FINANCE)
    )
    assert paid["payout_value_cents"] == 2354
    assert paid["payout_mode"] == "STORE_CREDIT"
    assert paid["status"] == "PAID"

    grants, _ = validate_paginated(
        api.list_credit_grants(FINANCE, params={"member_id": w.cora_id})
    )
    commission_grants = [g for g in grants if g["source"] == "COMMISSION"]
    assert len(commission_grants) == 1
    assert_credit_grant(commission_grants[0])
    assert commission_grants[0]["amount_cents"] == 2354

    assert validate_success(api.get_member(w.cora_id, ADMIN))["credit_balance_cents"] == 7154


def test_commission_payout_in_cash_deducts_the_floored_fee_and_mints_no_credit(api):
    """PRD §3.9: "Under `CASH`, a fee is computed as the greater of 100 cents and
    `net_cents` multiplied by 0.02 rounded half up to the whole cent,
    `payout_value_cents` is `net_cents` less that fee, and no credit grant is minted.
    On a `net_cents` of 3600, the two modes yield 3960 and 3528 from identical
    inputs."

    Design: Difficulty/dual_variant_calc/commission_payout_store_credit_bonus_diverges_from_cash_fee
    """
    w = canonical_world(api, "recon_posted")
    accrual = find_accrual(api, w)
    assert accrual["net_cents"] == 2140

    paid = validate_success(
        api.payout_commission_accrual(accrual["id"], payout_payload("CASH"), FINANCE)
    )
    assert paid["payout_value_cents"] == 2040
    assert paid["payout_mode"] == "CASH"
    assert paid["status"] == "PAID"

    grants, _ = validate_paginated(
        api.list_credit_grants(FINANCE, params={"member_id": w.cora_id})
    )
    assert [g for g in grants if g["source"] == "COMMISSION"] == []
    assert validate_success(api.get_member(w.cora_id, ADMIN))["credit_balance_cents"] == 4800


def test_a_store_credit_payout_without_the_volunteer_obligation_is_refused(api):
    """PRD §3.9: "The store-credit mode is permitted only when the drop run's
    `volunteer_obligation_met` is true, and is otherwise refused with
    `ERR_VOLUNTEER_OBLIGATION_UNMET`; the cash mode carries no such condition, so a
    coordinator who missed the obligation can still be paid, at the halved accrual."

    Design: Corner/errors/a_store_credit_payout_without_the_volunteer_obligation_is_refused
    """
    w = canonical_world(api, "recon_posted", with_volunteer_shift=False)
    accrual = find_accrual(api, w)

    validate_error(
        api.payout_commission_accrual(
            accrual["id"], payout_payload("STORE_CREDIT"), FINANCE
        ),
        ApiErrorId.ERR_VOLUNTEER_OBLIGATION_UNMET.value,
    )

    paid = validate_success(
        api.payout_commission_accrual(accrual["id"], payout_payload("CASH"), FINANCE)
    )
    assert paid["net_cents"] == 1070
    assert paid["payout_mode"] == "CASH"
    assert paid["payout_value_cents"] == 970
    assert paid["status"] == "PAID"

    _, meta = validate_paginated(
        api.list_credit_grants(FINANCE, params={"member_id": w.cora_id})
    )
    assert meta["total_count"] == 0


def test_paying_out_before_the_ledger_is_posted_returns_invalid_accrual_state(api):
    """PRD §2.9: "**Rung 22** — the commission accrual has status `ACCRUED` or
    `ADJUSTED`, and the drop run it belongs to has a drop reconciliation with status
    `POSTED`. Applies to paying out a commission accrual. Failure:
    `ERR_INVALID_ACCRUAL_STATE`, HTTP 409."

    Design: Corner/state_machines/paying_out_before_the_ledger_is_posted_returns_invalid_accrual_state
    """
    w = canonical_world(api, "delivered")
    accrual = find_accrual(api, w)

    validate_error(
        api.payout_commission_accrual(accrual["id"], payout_payload("CASH"), FINANCE),
        ApiErrorId.ERR_INVALID_ACCRUAL_STATE.value,
    )

    stored = validate_success(api.get_commission_accrual(accrual["id"], FINANCE))
    assert stored["status"] == "ACCRUED"
    assert stored["payout_value_cents"] == 0

    _, meta = validate_paginated(
        api.list_drop_reconciliations(FINANCE, params={"drop_run_id": w.drop_run_id})
    )
    assert meta["total_count"] == 0


def test_an_unknown_commission_accrual_id_returns_accrual_not_found(api):
    """PRD §2.8: "`commission_accrual_id` yields
    `ERR_COMMISSION_ACCRUAL_NOT_FOUND`"

    Design: Corner/errors/an_unknown_commission_accrual_id_returns_accrual_not_found
    """
    w = canonical_world(api, "delivered")

    validate_error(
        api.payout_commission_accrual(
            NON_EXISTENT_UUID, payout_payload("CASH"), FINANCE
        ),
        ApiErrorId.ERR_COMMISSION_ACCRUAL_NOT_FOUND.value,
    )

    _, meta = validate_paginated(
        api.list_commission_accruals(FINANCE, params={"drop_run_id": w.drop_run_id})
    )
    assert meta["total_count"] == 1


# ----------------------------------------------- the verification cascade ---
def test_volunteer_verification_cascades_into_commission_and_the_ledger(api):
    """PRD §3.9: "Second, because a shift became verified, the drop run's
    `verified_volunteer_hours` is recomputed as the sum of `hours` over its shifts
    with status `VERIFIED`, and `volunteer_obligation_met` is re-evaluated as true
    exactly when that sum is at least 4.0; the same hop mints a credit grant for the
    volunteering member with `source` `VOLUNTEER`, an `amount_cents` equal to the
    shift's `hours` multiplied by 1200 cents per hour and rounded half up to the whole
    cent, and an `expires_at` 180 days after the current clock reading, links it back
    through the shift's `credit_grant_id`, and raises the member's
    `credit_balance_cents`."
    PRD §3.9: "Third, because `volunteer_obligation_met` may have flipped to true,
    any commission accrual on that drop run with status `ACCRUED` recomputes its
    `volunteer_multiplier_applied` to 1.00, recomputes `accrued_cents` and `net_cents`,
    and moves `ACCRUED → ADJUSTED`."
    PRD §3.9: "Fourth, because `net_cents` changed, any drop reconciliation on that
    drop run that is not `POSTED` recomputes its `commission_cents` and
    `variance_cents`, and moves `BALANCED → VARIANCE_HELD` when the absolute value of
    `variance_cents` now exceeds 200 cents."

    Design: Difficulty/transitive_cascade/volunteer_verification_cascades_into_commission_and_reopens_the_ledger
    """
    w = canonical_world(api, "recon_balanced", with_volunteer_shift=False)
    accrual = find_accrual(api, w)
    assert accrual["net_cents"] == 1070

    coordinator = make_coordinator_headers(w.cora_id)
    shift = validate_success(
        api.create_volunteer_shift(
            create_volunteer_shift_payload(w.drop_run_id, w.cora_id, 4.0), coordinator
        ),
        201,
    )
    verified = validate_success(api.verify_volunteer_shift(shift["id"], coordinator))
    assert_volunteer_shift(verified)
    assert verified["status"] == "VERIFIED"

    drop_run = validate_success(api.get_drop_run(w.drop_run_id, ADMIN))
    assert drop_run["verified_volunteer_hours"] == 4.0
    assert drop_run["volunteer_obligation_met"] is True

    adjusted = validate_success(api.get_commission_accrual(accrual["id"], FINANCE))
    assert adjusted["volunteer_multiplier_applied"] == 1.0
    assert adjusted["accrued_cents"] == 2140
    assert adjusted["net_cents"] == 2140
    assert adjusted["status"] == "ADJUSTED"

    reconciliation = validate_success(
        api.get_drop_reconciliation(w.reconciliation_id, FINANCE)
    )
    assert reconciliation["commission_cents"] == 2140

    grants, _ = validate_paginated(
        api.list_credit_grants(FINANCE, params={"member_id": w.cora_id})
    )
    volunteer_grants = [g for g in grants if g["source"] == "VOLUNTEER"]
    assert len(volunteer_grants) == 1
    assert volunteer_grants[0]["amount_cents"] == 4800


def test_the_obligation_only_flips_once_the_verified_hours_reach_four(api):
    """PRD §3.9: "A shift is logged against a `drop_run_id` for a `member_id` with
    an `hours` figure, which must be greater than 0 and is recorded in quarter-hour
    increments."
    PRD §3.9: "Second, because a shift became verified, the drop run's
    `verified_volunteer_hours` is recomputed as the sum of `hours` over its shifts
    with status `VERIFIED`, and `volunteer_obligation_met` is re-evaluated as true
    exactly when that sum is at least 4.0; the same hop mints a credit grant for the
    volunteering member with `source` `VOLUNTEER`, an `amount_cents` equal to the
    shift's `hours` multiplied by 1200 cents per hour and rounded half up to the whole
    cent, and an `expires_at` 180 days after the current clock reading, links it back
    through the shift's `credit_grant_id`, and raises the member's
    `credit_balance_cents`."

    Design: Difficulty/transitive_cascade/volunteer_verification_cascades_into_commission_and_reopens_the_ledger
    """
    w = canonical_world(api, "delivered", with_volunteer_shift=False)
    accrual = find_accrual(api, w)
    coordinator = make_coordinator_headers(w.cora_id)

    first = validate_success(
        api.create_volunteer_shift(
            create_volunteer_shift_payload(w.drop_run_id, w.cora_id, 2.0), coordinator
        ),
        201,
    )
    second = validate_success(
        api.create_volunteer_shift(
            create_volunteer_shift_payload(w.drop_run_id, w.cora_id, 2.0), coordinator
        ),
        201,
    )

    validate_success(api.verify_volunteer_shift(first["id"], coordinator))
    midway = validate_success(api.get_drop_run(w.drop_run_id, ADMIN))
    assert midway["verified_volunteer_hours"] == 2.0
    assert midway["volunteer_obligation_met"] is False
    still_accrued = validate_success(api.get_commission_accrual(accrual["id"], FINANCE))
    assert still_accrued["net_cents"] == 1070

    validate_success(api.verify_volunteer_shift(second["id"], coordinator))
    complete = validate_success(api.get_drop_run(w.drop_run_id, ADMIN))
    assert complete["verified_volunteer_hours"] == 4.0
    assert complete["volunteer_obligation_met"] is True

    adjusted = validate_success(api.get_commission_accrual(accrual["id"], FINANCE))
    assert adjusted["net_cents"] == 2140
    assert adjusted["status"] == "ADJUSTED"

    grants, meta = validate_paginated(
        api.list_credit_grants(FINANCE, params={"member_id": w.cora_id})
    )
    volunteer_grants = [g for g in grants if g["source"] == "VOLUNTEER"]
    assert meta["total_count"] == 2
    assert len(volunteer_grants) == 2
    assert all(grant["amount_cents"] == 2400 for grant in volunteer_grants)


def test_verifying_an_already_verified_shift_returns_invalid_shift_state(api):
    """PRD §2.9: "**Rung 23** — the volunteer shift has status `LOGGED`. Applies to
    verifying and rejecting a shift. Failure: `ERR_INVALID_SHIFT_STATE`, HTTP 409."

    Design: Corner/state_machines/verifying_an_already_verified_shift_returns_invalid_shift_state
    """
    w = canonical_world(api, "volunteer_verified")
    coordinator = make_coordinator_headers(w.cora_id)

    validate_error(
        api.verify_volunteer_shift(w.volunteer_shift_id, coordinator),
        ApiErrorId.ERR_INVALID_SHIFT_STATE.value,
    )

    assert (
        validate_success(api.get_volunteer_shift(w.volunteer_shift_id, ADMIN))["status"]
        == "VERIFIED"
    )
    assert (
        validate_success(api.get_drop_run(w.drop_run_id, ADMIN))["verified_volunteer_hours"]
        == 4.0
    )

    grants, meta = validate_paginated(
        api.list_credit_grants(coordinator, params={"member_id": w.cora_id})
    )
    assert meta["total_count"] == 1
    assert grants[0]["amount_cents"] == 4800


def test_rejecting_a_shift_mints_no_credit_and_leaves_the_obligation_unmet(api):
    """PRD §3.9: "Rejecting a shift is the sibling operation and is specified to
    the same depth. It requires the same actor conditions and the same `LOGGED`
    starting status, moves the shift `LOGGED → REJECTED`, and writes
    `verified_by_user_id` from the acting `X-User-ID`. No credit grant is minted, the
    drop run's `verified_volunteer_hours` is unchanged, `volunteer_obligation_met` is
    not re-evaluated, and no commission or reconciliation recompute follows."

    Design: Corner/state_machines/rejecting_a_shift_mints_no_credit_and_leaves_the_obligation_unmet
    """
    w = canonical_world(api, "volunteer_verified")
    coordinator = make_coordinator_headers(w.cora_id)
    shift = validate_success(
        api.create_volunteer_shift(
            create_volunteer_shift_payload(w.drop_run_id, w.mara_id, 6.0), coordinator
        ),
        201,
    )

    rejected = validate_success(api.reject_volunteer_shift(shift["id"], coordinator))
    assert rejected["status"] == "REJECTED"
    assert rejected["credit_grant_id"] is None

    drop_run = validate_success(api.get_drop_run(w.drop_run_id, ADMIN))
    assert drop_run["verified_volunteer_hours"] == 4.0
    assert drop_run["volunteer_obligation_met"] is True

    _, meta = validate_paginated(
        api.list_credit_grants(ADMIN, params={"member_id": w.mara_id})
    )
    assert meta["total_count"] == 0
