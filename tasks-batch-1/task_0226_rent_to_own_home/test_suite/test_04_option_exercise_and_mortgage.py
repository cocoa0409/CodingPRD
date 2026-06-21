"""Exercising the purchase option, settling the closing numbers, converting to a
mortgage, and the terminal collapses (default / expiry) — plus the error-precedence
ladder and role gates guarding these transitions.
"""

from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    # fixtures / helpers
    create_landlord,
    create_tenant,
    create_property,
    create_parties_and_property,
    create_draft_agreement,
    create_active_agreement,
    activate_agreement,
    schedule_payment,
    record_payment,
    forfeit_payment,
    setup_agreement_with_paid_payments,
    setup_agreement_with_forfeited_payments,
    setup_exercised_agreement,
    set_clock,
    exercise_option,
    convert_to_mortgage,
    get_agreement,
    get_property_state,
    make_landlord_headers,
    make_tenant_headers,
    make_escrow_headers,
    create_agreement_payload,
)


# ─── Settlement math ──────────────────────────────────────────────────────────

def test_settlement_applies_credit_and_fee_credit(api):
    """PRD §3.6: "the credit actually applied, `credit_applied_cents`, is the smaller
    of the agreement's finalized `available_credit_cents` (taken at the exercise
    instant) and that cap". And: "the option-fee credit, `option_fee_credit_cents`,
    is the agreement's `option_fee_cents` when `option_fee_creditable` is true, and
    zero otherwise." And: "the `net_due_at_closing_cents` is the snapshot price minus
    the applied credit minus the option-fee credit."

    Design: Difficulty/combinatorial_formula/cf_purchase_settlement_nested_min_and_conditional
    """
    landlord, tenant, prop, agreement, exercise = setup_exercised_agreement(
        num_paid=3, monthly_payment_cents=200000, credit_pct=0.30,
        locked_price_cents=30000000, option_fee_cents=500000,
        option_fee_creditable=True, max_credit_pct=0.20,
    )
    assert exercise["max_credit_cap_cents"] == 6000000, exercise["max_credit_cap_cents"]
    assert exercise["credit_applied_cents"] == 180000, exercise["credit_applied_cents"]
    assert exercise["option_fee_credit_cents"] == 500000, exercise["option_fee_credit_cents"]
    assert exercise["net_due_at_closing_cents"] == 29320000, exercise["net_due_at_closing_cents"]


def test_settlement_snapshots_locked_price_and_caps_credit(api):
    """PRD §3.6: "First, `locked_price_snapshot_cents` is snapshotted from the
    agreement's `locked_price_cents`. Second, the credit ceiling `max_credit_cap_cents`
    is computed as that snapshot price multiplied by the agreement's `max_credit_pct`,
    rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/cf_purchase_settlement_nested_min_and_conditional
    """
    landlord, tenant, prop, agreement, exercise = setup_exercised_agreement(
        num_paid=3, monthly_payment_cents=200000, credit_pct=0.30,
        locked_price_cents=30000000, option_fee_cents=500000,
        option_fee_creditable=True, max_credit_pct=0.20,
    )
    assert exercise["locked_price_snapshot_cents"] == 30000000, (
        f"snapshot must copy locked_price_cents, got {exercise['locked_price_snapshot_cents']}"
    )
    assert exercise["max_credit_cap_cents"] == 6000000, exercise["max_credit_cap_cents"]


def test_settlement_with_empty_credit_pool_and_noncreditable_fee(api):
    """PRD §3.6: "the credit actually applied, `credit_applied_cents`, is the smaller
    of the agreement's finalized `available_credit_cents` (taken at the exercise
    instant) and that cap". And: "the option-fee credit, `option_fee_credit_cents`,
    is the agreement's `option_fee_cents` when `option_fee_creditable` is true, and
    zero otherwise." And: "the `net_due_at_closing_cents` is the snapshot price minus
    the applied credit minus the option-fee credit."

    Design: Difficulty/boundary_precision_check/bpc_empty_credit_pool_exercise_net_equals_locked
    """
    landlord, tenant, prop = create_parties_and_property()
    _, _, _, agreement = create_draft_agreement(
        landlord, tenant, prop,
        locked_price_cents=30000000, option_fee_cents=500000,
        option_fee_creditable=False, max_credit_pct=0.20,
    )
    agreement = activate_agreement(landlord, prop, agreement)
    set_clock(landlord, "2026-06-01T00:00:00Z")
    exercise = exercise_option(tenant, agreement, "2026-06-01T00:00:00Z")
    assert exercise["credit_applied_cents"] == 0, exercise["credit_applied_cents"]
    assert exercise["option_fee_credit_cents"] == 0, exercise["option_fee_credit_cents"]
    assert exercise["net_due_at_closing_cents"] == 30000000, exercise["net_due_at_closing_cents"]


def test_empty_credit_pool_exercise_advances_agreement(api):
    """PRD §3.6: "A successful exercise creates an `OptionExercise` row in `PENDING`
    and immediately settles it, freezing the closing numbers and advancing the
    agreement `ACTIVE → EXERCISED`."

    Design: Difficulty/boundary_precision_check/bpc_empty_credit_pool_exercise_net_equals_locked
    """
    landlord, tenant, prop = create_parties_and_property()
    _, _, _, agreement = create_draft_agreement(
        landlord, tenant, prop,
        locked_price_cents=30000000, option_fee_cents=500000,
        option_fee_creditable=False, max_credit_pct=0.20,
    )
    agreement = activate_agreement(landlord, prop, agreement)
    set_clock(landlord, "2026-06-01T00:00:00Z")
    exercise_option(tenant, agreement, "2026-06-01T00:00:00Z")
    a = get_agreement(landlord, agreement["id"])
    assert a["status"] == "EXERCISED", f"exercise must advance agreement to EXERCISED, got {a['status']}"


def test_settlement_credit_capped_at_max_credit(api):
    """PRD §3.6: "the credit ceiling `max_credit_cap_cents` is computed as that
    snapshot price multiplied by the agreement's `max_credit_pct`, rounded half up to
    whole cents. Third, the credit actually applied, `credit_applied_cents`, is the
    smaller of the agreement's finalized `available_credit_cents` (taken at the
    exercise instant) and that cap — so the buyer can never apply more credit than the
    ceiling permits."

    Design: Corner/calculations/calc_credit_cap_binds_at_exercise
    """
    landlord, tenant, prop, agreement, exercise = setup_exercised_agreement(
        num_paid=3, monthly_payment_cents=300000, credit_pct=0.30,
        locked_price_cents=1000000, option_fee_cents=50000,
        option_fee_creditable=True, max_credit_pct=0.20,
    )
    assert exercise["max_credit_cap_cents"] == 200000, exercise["max_credit_cap_cents"]
    assert exercise["credit_applied_cents"] == 200000, exercise["credit_applied_cents"]
    assert exercise["net_due_at_closing_cents"] == 750000, exercise["net_due_at_closing_cents"]


# ─── Conversion cascade ───────────────────────────────────────────────────────

def test_conversion_cascades_to_mortgage_and_sold_property(api):
    """PRD §3.7: "Its `principal_cents` is copied from the settled exercise's
    `net_due_at_closing_cents`." And: "Conversion advances the agreement
    `EXERCISED → CONVERTED` and cascades the property `UNDER_AGREEMENT → SOLD`
    (bumping the property's `version`)".

    Design: Difficulty/transitive_cascade/tc_mortgage_conversion_depth3
    """
    landlord, tenant, prop, agreement, exercise = setup_exercised_agreement(
        num_paid=3, monthly_payment_cents=200000, credit_pct=0.30,
        locked_price_cents=30000000, option_fee_cents=500000,
        option_fee_creditable=True, max_credit_pct=0.20,
    )
    mortgage = convert_to_mortgage(agreement, exercise, annual_rate_bps=0, term_months=360)
    assert mortgage["principal_cents"] == 29320000, mortgage["principal_cents"]
    a = get_agreement(landlord, agreement["id"])
    assert a["status"] == "CONVERTED", a["status"]
    p = get_property_state(landlord, prop["id"])
    assert p["status"] == "SOLD", p["status"]


def test_conversion_zero_rate_installment_and_active_mortgage(api):
    """PRD §3.7: "On success the system mints a `Mortgage` in `ACTIVE` — the only state
    a mortgage ever holds." And: "When that monthly rate is zero, the monthly
    installment is simply the principal divided by the number of months, rounded half
    up to whole cents."

    Design: Difficulty/transitive_cascade/tc_mortgage_conversion_depth3
    """
    landlord, tenant, prop, agreement, exercise = setup_exercised_agreement(
        num_paid=3, monthly_payment_cents=200000, credit_pct=0.30,
        locked_price_cents=30000000, option_fee_cents=500000,
        option_fee_creditable=True, max_credit_pct=0.20,
    )
    mortgage = convert_to_mortgage(agreement, exercise, annual_rate_bps=0, term_months=360)
    assert mortgage["status"] == "ACTIVE", mortgage["status"]
    # principal 29320000 / 360 -> round_half_up = 81444
    assert mortgage["monthly_installment_cents"] == 81444, mortgage["monthly_installment_cents"]


def test_conversion_at_minimum_credit_score_succeeds(api):
    """PRD §3.7: "the tenant's `credit_score` must be at least 620, the minimum
    conversion score — a lower score is rejected with `ERR_CREDIT_SCORE_TOO_LOW`."

    Design: Difficulty/cross_entity_state_dependency/cesd_mortgage_depends_on_tenant_credit_score
    """
    landlord = create_landlord()
    tenant = create_tenant(credit_score=620)
    prop = create_property(landlord)
    _, _, _, agreement = create_draft_agreement(
        landlord, tenant, prop, option_fee_creditable=True, max_credit_pct=0.20,
    )
    agreement = activate_agreement(landlord, prop, agreement)
    set_clock(landlord, "2026-06-01T00:00:00Z")
    exercise = exercise_option(tenant, agreement, "2026-06-01T00:00:00Z")
    res = api.create_mortgage(
        agreement["id"],
        {"option_exercise_id": exercise["id"], "annual_rate_bps": 0, "term_months": 360},
        make_escrow_headers(),
    )
    data = validate_success(res, expected_status=201)
    a = get_agreement(landlord, agreement["id"])
    assert a["status"] == "CONVERTED", a["status"]


# ─── Terminal collapses ───────────────────────────────────────────────────────

def test_default_zeroes_credit_and_releases_property(api):
    """PRD §3.8: "Declaring default transitions the agreement `ACTIVE → DEFAULTED`
    and triggers a punishing cascade: every non-terminal payment row ... is forced to
    `FORFEITED`, all earned credit evaporates so that `available_credit_cents` is
    recomputed to zero, the property is released `UNDER_AGREEMENT → AVAILABLE`
    (bumping its `version`)".

    Design: Difficulty/non_linear_state_machine/nlsm_agreement_branching_active_to_default_vs_exercised
    """
    landlord, tenant, prop, agreement, payments = setup_agreement_with_forfeited_payments(3)
    res = api.default_agreement(agreement["id"], make_landlord_headers(landlord["id"]))
    data = validate_success(res, expected_status=200)
    assert data["status"] == "DEFAULTED", data["status"]
    a = get_agreement(landlord, agreement["id"])
    assert a["available_credit_cents"] == 0, a["available_credit_cents"]
    p = get_property_state(landlord, prop["id"])
    assert p["status"] == "AVAILABLE", p["status"]


def test_default_forces_non_terminal_payments_forfeited(api):
    """PRD §3.8: "every non-terminal payment row — that is, every row still in
    `PENDING` or `LATE` — is forced to `FORFEITED`".

    Design: Difficulty/non_linear_state_machine/nlsm_agreement_branching_active_to_default_vs_exercised
    """
    landlord, tenant, prop, agreement = create_active_agreement()
    # Three FORFEITED to reach the default threshold, plus one PENDING that the
    # default cascade must itself force to FORFEITED.
    for i in range(1, 4):
        pay = schedule_payment(landlord, agreement, i, f"2026-{i + 1:02d}-01T00:00:00Z")
        forfeit_payment(landlord, pay)
    pending = schedule_payment(landlord, agreement, 5, "2026-06-01T00:00:00Z")
    get_success_data(api.default_agreement(agreement["id"], make_landlord_headers(landlord["id"])))
    row = get_success_data(
        api.get_rent_payment(pending["id"], make_landlord_headers(landlord["id"]))
    )
    assert row["status"] == "FORFEITED", (
        f"default must force the non-terminal PENDING row to FORFEITED, got {row['status']}"
    )


def test_default_releases_property_to_available(api):
    """PRD §3.8: "Declaring default transitions the agreement `ACTIVE → DEFAULTED`
    ... the property is released `UNDER_AGREEMENT → AVAILABLE` (bumping its
    `version`)".

    Design: Difficulty/transitive_cascade/tc_default_forfeit_chain_depth2
    """
    landlord, tenant, prop, agreement, payments = setup_agreement_with_forfeited_payments(3)
    res = api.default_agreement(agreement["id"], make_landlord_headers(landlord["id"]))
    data = validate_success(res, expected_status=200)
    assert data["status"] == "DEFAULTED", data["status"]
    p = get_property_state(landlord, prop["id"])
    assert p["status"] == "AVAILABLE", p["status"]


def test_default_transitions_agreement_to_defaulted(api):
    """PRD §3.8: "Declaring default transitions the agreement `ACTIVE → DEFAULTED`".

    Design: Difficulty/transitive_cascade/tc_default_forfeit_chain_depth2
    """
    landlord, tenant, prop, agreement, payments = setup_agreement_with_forfeited_payments(3)
    res = api.default_agreement(agreement["id"], make_landlord_headers(landlord["id"]))
    data = validate_success(res, expected_status=200)
    assert data["status"] == "DEFAULTED", (
        f"manual default at threshold must transition the agreement to DEFAULTED, got {data['status']}"
    )


def test_default_below_threshold_rejected(api):
    """PRD §3.8: "A manual default is permitted only while the agreement is `ACTIVE`
    ... and only once the `missed_payment_count` has reached at least three (the
    maximum tolerated missed payments); a manual default attempted below that
    threshold is rejected with `ERR_DEFAULT_THRESHOLD_NOT_MET`."

    Design: Corner/state_machines/sm_default_below_threshold_rejected
    """
    landlord, tenant, prop, agreement, payments = setup_agreement_with_forfeited_payments(1)
    res = api.default_agreement(agreement["id"], make_landlord_headers(landlord["id"]))
    validate_error(res, ApiErrorId.ERR_DEFAULT_THRESHOLD_NOT_MET.value)


def test_expire_before_deadline_rejected(api):
    """PRD §3.8: "Manual expiry is permitted only while the agreement is `ACTIVE`
    ... and only when the server's current clock is strictly past the agreement's
    `option_deadline`; an expiry attempted at or before the deadline is rejected with
    `ERR_OPTION_NOT_YET_EXPIRED`."

    Design: Corner/state_machines/sm_expire_before_deadline_rejected
    """
    landlord, tenant, prop, agreement = create_active_agreement(option_term_months=24)
    set_clock(landlord, "2026-06-01T00:00:00Z")  # before option_deadline 2028-01-01
    res = api.expire_agreement(agreement["id"], make_landlord_headers(landlord["id"]))
    validate_error(res, ApiErrorId.ERR_OPTION_NOT_YET_EXPIRED.value)


# ─── Exercise gates ───────────────────────────────────────────────────────────

def test_exercise_after_deadline_rejected(api):
    """PRD §3.6: "The `exercised_at` instant must be on or before the agreement's
    `option_deadline`; an exercise after the deadline is rejected with
    `ERR_OPTION_EXPIRED`."

    Design: Corner/state_machines/sm_exercise_after_deadline_rejected
    """
    landlord, tenant, prop, agreement = create_active_agreement(
        lease_start="2026-01-01T00:00:00Z", option_term_months=2
    )
    set_clock(landlord, "2026-04-01T00:00:00Z")  # past option_deadline 2026-03-01
    res = api.create_option_exercise(
        agreement["id"], {"exercised_at": "2026-04-01T00:00:00Z"},
        make_tenant_headers(tenant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_OPTION_EXPIRED.value)


def test_exercise_blocked_by_outstanding_default(api):
    """PRD §3.6: "the agreement must carry no outstanding default risk — its
    `missed_payment_count` must be exactly zero; if any payment has been forfeited,
    the exercise is blocked with `ERR_OPTION_BLOCKED_BY_DEFAULT`."

    Design: Corner/validations/val_exercise_blocked_by_outstanding_default
    """
    landlord, tenant, prop, agreement = create_active_agreement()
    pay = schedule_payment(landlord, agreement, 1, "2026-02-01T00:00:00Z")
    forfeit_payment(landlord, pay)  # missed_payment_count = 1, agreement still ACTIVE
    set_clock(landlord, "2026-06-01T00:00:00Z")
    res = api.create_option_exercise(
        agreement["id"], {"exercised_at": "2026-06-01T00:00:00Z"},
        make_tenant_headers(tenant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_OPTION_BLOCKED_BY_DEFAULT.value)


# ─── Error-precedence ladder ──────────────────────────────────────────────────

def test_exercise_on_defaulted_agreement_reports_state_error(api):
    """PRD §3.6: "The agreement must be `ACTIVE` (otherwise
    `ERR_AGREEMENT_NOT_ACTIVE`)."
    PRD §2.8: "the target resource must be in the correct state for the requested
    transition, else `ERR_INVALID_STATE` (409)." This State tier outranks the
    "Domain-specific business rules" tier that holds the safety gate, so the
    not-ACTIVE state rejection is reported instead of the safety error.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_vs_safety_on_exercise
    """
    landlord, tenant, prop, agreement, payments = setup_agreement_with_forfeited_payments(3)
    get_success_data(api.default_agreement(agreement["id"], make_landlord_headers(landlord["id"])))
    # Agreement now DEFAULTED (state fails) AND missed_payment_count == 3 (safety fails).
    res = api.create_option_exercise(
        agreement["id"], {"exercised_at": "2026-06-01T00:00:00Z"},
        make_tenant_headers(tenant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)


def test_exercise_on_defaulted_agreement_leaves_state_unchanged(api):
    """PRD §3.6: "The agreement must be `ACTIVE` (otherwise
    `ERR_AGREEMENT_NOT_ACTIVE`)."
    PRD §2.8: "the target resource must be in the correct state for the requested
    transition, else `ERR_INVALID_STATE` (409)." This State tier outranks the
    domain-specific business rules tier below it.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_vs_safety_on_exercise
    """
    landlord, tenant, prop, agreement, payments = setup_agreement_with_forfeited_payments(3)
    get_success_data(api.default_agreement(agreement["id"], make_landlord_headers(landlord["id"])))
    api.create_option_exercise(
        agreement["id"], {"exercised_at": "2026-06-01T00:00:00Z"},
        make_tenant_headers(tenant["id"]),
    )
    a = get_agreement(landlord, agreement["id"])
    assert a["status"] == "DEFAULTED", (
        f"a rejected exercise must leave the agreement DEFAULTED, got {a['status']}"
    )


def test_conversion_with_missing_exercise_reports_not_found(api):
    """PRD §2.8: "Existence — every resource referenced by the path or body must
    exist; these are validated left-to-right, and the first missing one yields
    `ERR_NOT_FOUND` (404)." This existence tier outranks the State tier below it.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_existence_vs_state_on_mortgage
    """
    landlord, tenant, prop, agreement = create_active_agreement()  # ACTIVE, never EXERCISED
    res = api.create_mortgage(
        agreement["id"],
        {"option_exercise_id": NON_EXISTENT_UUID, "annual_rate_bps": 0, "term_months": 360},
        make_escrow_headers(),
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_conversion_with_missing_exercise_leaves_agreement_active(api):
    """PRD §2.8: "Existence — every resource referenced by the path or body must
    exist; these are validated left-to-right, and the first missing one yields
    `ERR_NOT_FOUND` (404)."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_existence_vs_state_on_mortgage
    """
    landlord, tenant, prop, agreement = create_active_agreement()  # ACTIVE, never EXERCISED
    api.create_mortgage(
        agreement["id"],
        {"option_exercise_id": NON_EXISTENT_UUID, "annual_rate_bps": 0, "term_months": 360},
        make_escrow_headers(),
    )
    a = get_agreement(landlord, agreement["id"])
    assert a["status"] == "ACTIVE", (
        f"a rejected conversion must leave the agreement ACTIVE, got {a['status']}"
    )


def test_conversion_low_credit_score_rejected(api):
    """PRD §3.7: "the tenant's `credit_score` must be at least 620, the minimum
    conversion score — a lower score is rejected with `ERR_CREDIT_SCORE_TOO_LOW`."

    Design: Difficulty/cross_entity_state_dependency/cesd_mortgage_depends_on_tenant_credit_score
    """
    landlord = create_landlord()
    tenant = create_tenant(credit_score=600)
    prop = create_property(landlord)
    _, _, _, agreement = create_draft_agreement(
        landlord, tenant, prop,
        option_fee_creditable=True, max_credit_pct=0.20,
    )
    agreement = activate_agreement(landlord, prop, agreement)
    set_clock(landlord, "2026-06-01T00:00:00Z")
    exercise = exercise_option(tenant, agreement, "2026-06-01T00:00:00Z")
    res = api.create_mortgage(
        agreement["id"],
        {"option_exercise_id": exercise["id"], "annual_rate_bps": 0, "term_months": 360},
        make_escrow_headers(),
    )
    validate_error(res, ApiErrorId.ERR_CREDIT_SCORE_TOO_LOW.value)
    a = get_agreement(landlord, agreement["id"])
    assert a["status"] == "EXERCISED", f"rejected conversion must leave agreement EXERCISED, got {a['status']}"


def test_conversion_with_mismatched_exercise_rejected(api):
    """PRD §3.7: "a `SETTLED` option exercise must exist for the agreement and the
    supplied `option_exercise_id` must in fact belong to the path agreement (a
    mismatch is `ERR_REFERENCE_MISMATCH`)".

    Design: Corner/validations/val_reference_mismatch_option_exercise_wrong_agreement
    """
    landlord = create_landlord()
    tenant = create_tenant(credit_score=700)
    prop_main = create_property(landlord)
    prop_other = create_property(landlord)
    _, _, _, a_main = create_draft_agreement(landlord, tenant, prop_main)
    _, _, _, a_other = create_draft_agreement(landlord, tenant, prop_other)
    a_main = activate_agreement(landlord, prop_main, a_main)
    a_other = activate_agreement(landlord, prop_other, a_other)
    set_clock(landlord, "2026-06-01T00:00:00Z")
    exercise_option(tenant, a_main, "2026-06-01T00:00:00Z")
    oe_other = exercise_option(tenant, a_other, "2026-06-01T00:00:00Z")
    res = api.create_mortgage(
        a_main["id"],
        {"option_exercise_id": oe_other["id"], "annual_rate_bps": 0, "term_months": 360},
        make_escrow_headers(),
    )
    validate_error(res, ApiErrorId.ERR_REFERENCE_MISMATCH.value)


# ─── Role gates ───────────────────────────────────────────────────────────────

def test_landlord_cannot_convert_to_mortgage(api):
    """PRD §4: the routing table lists `POST /agreements/{id}/mortgage` as authorized
    for EscrowAgent only.
    PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or an ownership check fails — the request is
    rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/rbac_escrow_exclusive_convert
    """
    landlord, tenant, prop, agreement, exercise = setup_exercised_agreement(
        num_paid=0, option_fee_creditable=True, max_credit_pct=0.20
    )
    res = api.create_mortgage(
        agreement["id"],
        {"option_exercise_id": exercise["id"], "annual_rate_bps": 0, "term_months": 360},
        make_landlord_headers(landlord["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If the `X-User-Role` header is missing or carries a value that is
    not one of these three known roles, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/rbac_missing_role_header_unauthenticated
    """
    res = api.get_agreement(NON_EXISTENT_UUID, headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)
