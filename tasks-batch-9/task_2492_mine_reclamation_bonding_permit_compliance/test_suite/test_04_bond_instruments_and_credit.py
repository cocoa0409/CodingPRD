"""Posting financial security: instrument credit, substitution, and the held sum."""
from test_helpers import (
    BOND_SPECIALIST_ACCEPTER,
    ApiErrorId,
    api_client as api,
    assert_bond_instrument,
    assert_money,
    assert_permit_ledger_invariants,
    chain_estimate_accepted,
    chain_issued,
    create_bond_instrument_payload,
    create_collateral_instrument_payload,
    create_surety_instrument_payload,
    is_valid_uuid,
    propose_instrument,
    refresh_operator,
    refresh_permit,
    register_qualified_operator,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_credited_amount_is_computed_at_acceptance_and_client_input_ignored():
    """A proposed instrument begins in `PROPOSED` with `credited_amount` at 0, and
    with `accepted_by_user_id` and `accepted_at` both null.

    Design: Corner/entities/bond_instrument_credited_amount_computed_at_acceptance_client_input_ignored
    """
    ctx = chain_estimate_accepted(
        operator_overrides={
            "legal_name": "Overreach Surety Client",
            "tangible_net_worth": 15000000.00,
            "fixed_assets_in_state": 7500000.00,
            "total_liabilities": 5000000.00,
            "net_income_prior_year": 600000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Overreach Pit", "county": "Logan", "total_acres": 240.00},
        mining_plan_acres=120.00,
    )
    assert_money(ctx["permit"]["bond_required_amount"], 865998.00, "bond_required_amount")

    proposed = validate_success(
        api.create_bond_instrument(
            {
                "permit_id": ctx["permit"]["id"],
                "instrument_type": "SURETY",
                "face_amount": 900000.00,
                "surety_company_name": "Cordillera Surety",
                "surety_naic_rating": "A",
                "credited_amount": 999999.00,
                "status": "ACCEPTED",
            },
            ctx["operator_headers"],
        ),
        201,
    )
    assert_bond_instrument(proposed)
    assert proposed["status"] == "PROPOSED", "the client-supplied status is ignored"
    assert_money(proposed["credited_amount"], 0.00, "credited_amount")
    assert proposed["accepted_by_user_id"] is None, "accepted_by_user_id starts null"
    assert proposed["accepted_at"] is None, "accepted_at starts null"

    accepted = validate_success(
        api.accept_bond_instrument(proposed["id"], BOND_SPECIALIST_ACCEPTER)
    )
    assert accepted["status"] == "ACCEPTED"
    # 900000.00 x 0.90 for the A rating.
    assert_money(accepted["credited_amount"], 810000.00, "credited_amount")

    permit = refresh_permit(ctx["permit"]["id"])
    assert_money(permit["bond_held_amount"], 810000.00, "bond_held_amount")
    assert_money(permit["bond_deficiency_amount"], 55998.00, "bond_deficiency_amount")


def test_surety_b_plus_plus_rating_credits_three_quarters_of_face():
    """A `SURETY` instrument credits its `face_amount` multiplied by the
    multiplier for its rating and rounded half up to two decimals, where
    `A_PLUS_PLUS` and `A_PLUS` both multiply by 1.00, `A` multiplies by 0.90, and
    `B_PLUS_PLUS` multiplies by 0.75.

    Design: Corner/calculations/surety_b_plus_plus_rating_multiplier_applied_to_face_amount
    """
    ctx = chain_estimate_accepted(
        operator_overrides={
            "legal_name": "Weak Rating Mining",
            "tangible_net_worth": 12000000.00,
            "fixed_assets_in_state": 6000000.00,
            "total_liabilities": 4300000.00,
            "net_income_prior_year": 350000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Weak Rating Pit", "county": "Converse", "total_acres": 240.00},
        mining_plan_acres=120.00,
    )
    proposed = validate_success(
        api.create_bond_instrument(
            create_surety_instrument_payload(
                ctx["permit"]["id"],
                rating="B_PLUS_PLUS",
                face_amount=900000.00,
                surety_company_name="Larkspur Indemnity",
            ),
            ctx["operator_headers"],
        ),
        201,
    )

    accepted = validate_success(
        api.accept_bond_instrument(proposed["id"], BOND_SPECIALIST_ACCEPTER)
    )
    assert accepted["status"] == "ACCEPTED"
    assert_money(accepted["credited_amount"], 675000.00, "credited_amount")

    permit = refresh_permit(ctx["permit"]["id"])
    assert_money(permit["bond_required_amount"], 865998.00, "bond_required_amount")
    assert_money(permit["bond_held_amount"], 675000.00, "bond_held_amount")
    assert_money(permit["bond_deficiency_amount"], 190998.00, "bond_deficiency_amount")


def test_collateral_haircut_rounds_half_up_to_cents():
    """A `COLLATERAL` instrument applies a haircut to the **market value** and
    only then applies the face amount as a cap: multiply
    `collateral_market_value` by one minus the haircut for its `collateral_type`,
    round half up to two decimals, and take the lesser of that figure and
    `face_amount`; the haircuts are 0.00 for `US_TREASURY`, 0.05 for
    `MUNICIPAL_BOND`, 0.00 for `IRREVOCABLE_LOC`, and 0.30 for `REAL_PROPERTY`.

    Design: Corner/calculations/collateral_haircut_rounds_half_up_to_cents
    """
    ctx = chain_estimate_accepted(
        operator_overrides={
            "legal_name": "Half Cent Collateral Mining",
            "tangible_net_worth": 12300000.00,
            "fixed_assets_in_state": 6100000.00,
            "total_liabilities": 4350000.00,
            "net_income_prior_year": 360000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Half Cent Pit", "county": "Sublette", "total_acres": 245.00},
        mining_plan_acres=120.00,
    )
    proposed = validate_success(
        api.create_bond_instrument(
            create_collateral_instrument_payload(
                ctx["permit"]["id"],
                collateral_type="MUNICIPAL_BOND",
                market_value=520000.55,
                face_amount=500000.00,
            ),
            ctx["operator_headers"],
        ),
        201,
    )

    accepted = validate_success(
        api.accept_bond_instrument(proposed["id"], BOND_SPECIALIST_ACCEPTER)
    )
    # 520000.55 x 0.95 == 494000.5225, which rounds half up to 494000.52 and
    # stays below the 500000.00 face cap.
    assert_money(accepted["credited_amount"], 494000.52, "credited_amount")
    assert accepted["credited_amount"] < accepted["face_amount"], (
        "the face cap does not bind here"
    )

    permit = refresh_permit(ctx["permit"]["id"])
    assert_money(permit["bond_held_amount"], 494000.52, "bond_held_amount")
    assert_money(permit["bond_deficiency_amount"], 371997.48, "bond_deficiency_amount")


def test_collateral_credit_is_capped_by_the_face_amount():
    """A `COLLATERAL` instrument applies a haircut to the **market value** and
    only then applies the face amount as a cap: multiply
    `collateral_market_value` by one minus the haircut for its `collateral_type`,
    round half up to two decimals, and take the lesser of that figure and
    `face_amount`.

    Design: Corner/calculations/collateral_credit_capped_by_face_amount
    """
    ctx = chain_estimate_accepted(
        operator_overrides={
            "legal_name": "Over Collateral Mining",
            "tangible_net_worth": 12400000.00,
            "fixed_assets_in_state": 6150000.00,
            "total_liabilities": 4380000.00,
            "net_income_prior_year": 370000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Over Collateral Pit", "county": "Sublette", "total_acres": 248.00},
        mining_plan_acres=120.00,
    )
    proposed = validate_success(
        api.create_bond_instrument(
            create_collateral_instrument_payload(
                ctx["permit"]["id"],
                collateral_type="US_TREASURY",
                market_value=620000.00,
                face_amount=500000.00,
            ),
            ctx["operator_headers"],
        ),
        201,
    )

    accepted = validate_success(
        api.accept_bond_instrument(proposed["id"], BOND_SPECIALIST_ACCEPTER)
    )
    # 620000.00 x (1 - 0.00) == 620000.00, clipped to the 500000.00 face amount.
    assert_money(accepted["credited_amount"], 500000.00, "credited_amount")
    assert accepted["credited_amount"] != 620000.00, (
        "over-collateralisation earns no credit above the face amount"
    )

    permit = refresh_permit(ctx["permit"]["id"])
    assert_money(permit["bond_held_amount"], 500000.00, "bond_held_amount")
    assert_money(permit["bond_deficiency_amount"], 365998.00, "bond_deficiency_amount")


def test_held_bond_sum_counts_only_accepted_instruments():
    """`bond_held_amount` is the total credited value of the instruments
    currently securing the permit — specifically, the sum of `credited_amount`
    over every `BondInstrument` on that permit whose status is `ACCEPTED`, less
    `bond_released_to_date`.

    Design: Corner/calculations/bond_held_amount_counts_only_accepted_instruments
    """
    ctx = chain_estimate_accepted(
        operator_overrides={
            "legal_name": "Two Instrument Mining",
            "tangible_net_worth": 12600000.00,
            "fixed_assets_in_state": 6250000.00,
            "total_liabilities": 4400000.00,
            "net_income_prior_year": 390000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={
            "name": "Two Instrument Pit", "county": "Sweetwater", "total_acres": 250.00,
        },
        mining_plan_acres=120.00,
    )
    first = propose_instrument(
        ctx["permit"]["id"], ctx["operator_headers"], instrument_type="CASH", face_amount=900000.00
    )
    accepted = validate_success(
        api.accept_bond_instrument(first["id"], BOND_SPECIALIST_ACCEPTER)
    )
    assert accepted["status"] == "ACCEPTED"
    assert_money(accepted["credited_amount"], 900000.00, "credited_amount")

    second = propose_instrument(
        ctx["permit"]["id"], ctx["operator_headers"], instrument_type="CASH", face_amount=200000.00
    )
    assert second["status"] == "PROPOSED"
    assert_money(second["credited_amount"], 0.00, "credited_amount")

    permit = refresh_permit(ctx["permit"]["id"])
    assert_money(permit["bond_held_amount"], 900000.00, "bond_held_amount")
    assert permit["bond_held_amount"] != 1100000.00, (
        "a PROPOSED instrument is outside the held-bond sum"
    )


def test_surety_proposal_without_its_rating_group_rejected():
    """Type-conditional detail follows: a `SURETY` proposal must carry both
    `surety_company_name` and `surety_naic_rating` and nothing from the collateral
    group. Any deviation from that shape is `ERR_COLLATERAL_DETAILS_REQUIRED` at
    priority 13.

    Design: Corner/validations/surety_instrument_without_rating_fields_rejected
    """
    ctx = chain_estimate_accepted(
        operator_overrides={
            "legal_name": "Bare Surety Mining",
            "tangible_net_worth": 12700000.00,
            "fixed_assets_in_state": 6300000.00,
            "total_liabilities": 4450000.00,
            "net_income_prior_year": 395000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Bare Surety Pit", "county": "Sweetwater", "total_acres": 252.00},
        mining_plan_acres=120.00,
    )

    response = api.create_bond_instrument(
        {
            "permit_id": ctx["permit"]["id"],
            "instrument_type": "SURETY",
            "face_amount": 900000.00,
        },
        ctx["operator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_COLLATERAL_DETAILS_REQUIRED, 422)

    cash = validate_success(
        api.create_bond_instrument(
            create_bond_instrument_payload(ctx["permit"]["id"], face_amount=900000.00),
            ctx["operator_headers"],
        ),
        201,
    )
    assert cash["status"] == "PROPOSED", (
        "CASH carries neither group, so the conditional requirement does not apply"
    )

    _, meta = validate_paginated(
        api.list_permit_instruments(ctx["permit"]["id"], BOND_SPECIALIST_ACCEPTER)
    )
    assert meta["total_count"] == 1, "only the CASH proposal was stored"


def test_surety_rated_b_is_writable_but_not_acceptable():
    """At priority 13, a `SURETY` instrument's `surety_naic_rating` must be one of
    `A_PLUS_PLUS`, `A_PLUS`, `A`, or `B_PLUS_PLUS` — the `B` rating is writable at
    proposal time but not acceptable, and an attempt to accept it is
    `ERR_SURETY_RATING_INELIGIBLE`.

    Design: Corner/errors/ineligible_surety_rating_acceptance_rejected
    """
    ctx = chain_estimate_accepted(
        operator_overrides={
            "legal_name": "Junk Rated Surety Mining",
            "tangible_net_worth": 12300000.00,
            "fixed_assets_in_state": 6100000.00,
            "total_liabilities": 4350000.00,
            "net_income_prior_year": 356000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Junk Rated Pit", "county": "Nye", "total_acres": 246.00},
        mining_plan_acres=120.00,
    )
    proposed = validate_success(
        api.create_bond_instrument(
            create_surety_instrument_payload(
                ctx["permit"]["id"],
                rating="B",
                face_amount=900000.00,
                surety_company_name="Backwater Bonding",
            ),
            ctx["operator_headers"],
        ),
        201,
    )
    assert proposed["surety_naic_rating"] == "B", "B is a writable member of the scale"

    response = api.accept_bond_instrument(proposed["id"], BOND_SPECIALIST_ACCEPTER)
    validate_error(response, ApiErrorId.ERR_SURETY_RATING_INELIGIBLE, 422)

    unchanged = validate_success(
        api.get_bond_instrument(proposed["id"], BOND_SPECIALIST_ACCEPTER)
    )
    assert unchanged["status"] == "PROPOSED"
    assert_money(unchanged["credited_amount"], 0.00, "credited_amount")
    assert unchanged["accepted_by_user_id"] is None
    assert_money(
        refresh_permit(ctx["permit"]["id"])["bond_held_amount"], 0.00, "bond_held_amount"
    )


def test_accepted_substitution_replaces_its_target_instrument():
    """If `replaces_instrument_id` was set, the referenced instrument transitions
    to `REPLACED` — from `ACCEPTED → REPLACED` for a live instrument or from
    `SUBSTITUTION_REQUIRED → REPLACED` for one the state had already flagged as
    needing substitution — and its `credited_amount` consequently leaves the
    permit's held-bond sum, with the replaced row's own `version` incremented.

    Design: Corner/endpoints/bond_instrument_substitution_links_and_replaces_prior_instrument
    """
    ctx = chain_issued(
        operator_overrides={
            "legal_name": "Swap Instrument Mining",
            "tangible_net_worth": 15200000.00,
            "fixed_assets_in_state": 7550000.00,
            "total_liabilities": 5020000.00,
            "net_income_prior_year": 570000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Swap Instrument Pit", "county": "Carbon", "total_acres": 315.00},
        mining_plan_acres=120.00,
    )
    original_id = ctx["instrument"]["id"]

    replacement = propose_instrument(
        ctx["permit"]["id"], ctx["operator_headers"],
        instrument_type="CASH", face_amount=950000.00,
        replaces_instrument_id=original_id,
    )
    assert replacement["replaces_instrument_id"] == original_id
    assert is_valid_uuid(replacement["replaces_instrument_id"])

    accepted = validate_success(
        api.accept_bond_instrument(replacement["id"], BOND_SPECIALIST_ACCEPTER)
    )
    assert accepted["status"] == "ACCEPTED"
    assert_money(accepted["credited_amount"], 950000.00, "credited_amount")

    replaced = validate_success(
        api.get_bond_instrument(original_id, BOND_SPECIALIST_ACCEPTER)
    )
    assert replaced["status"] == "REPLACED", "the substituted instrument is retired"
    assert replaced["version"] > ctx["instrument"]["version"], (
        "the replaced row is itself mutated, so its version advances"
    )

    permit = refresh_permit(ctx["permit"]["id"])
    assert_money(permit["bond_held_amount"], 950000.00, "bond_held_amount")
    assert permit["bond_held_amount"] != 1850000.00, (
        "the replaced credit leaves the held-bond sum"
    )
    assert_money(permit["bond_deficiency_amount"], 0.00, "bond_deficiency_amount")

    rows, meta = validate_paginated(
        api.list_bond_instruments(
            BOND_SPECIALIST_ACCEPTER, params={"replaces_instrument_id": original_id}
        )
    )
    assert meta["total_count"] == 1, "exactly one instrument substitutes for the original"
    assert rows[0]["id"] == replacement["id"]


def test_substitution_target_on_a_different_permit_rejected():
    """At priority 14, when `replaces_instrument_id` is set, the referenced
    instrument must belong to the same permit, must currently be in `ACCEPTED` or
    `SUBSTITUTION_REQUIRED`, and must not already have been superseded by another
    accepted substitution; a target that is on a different permit, in a terminal
    state, or already replaced is `ERR_SUBSTITUTION_TARGET_INVALID`.

    Design: Corner/errors/substitution_target_on_another_permit_rejected
    """
    operator_overrides = {
        "legal_name": "Cross Permit Swap Mining",
        "tangible_net_worth": 20500000.00,
        "fixed_assets_in_state": 9200000.00,
        "total_liabilities": 6100000.00,
        "net_income_prior_year": 820000.00,
        "elected_financial_test": "NET_WORTH_TEST",
    }
    ctx_a = chain_estimate_accepted(
        operator_overrides=operator_overrides,
        site_overrides={"name": "Cross Permit Pit A", "county": "Mohave", "total_acres": 300.00},
        mining_plan_acres=120.00,
    )
    instrument_a = propose_instrument(
        ctx_a["permit"]["id"], ctx_a["operator_headers"],
        instrument_type="CASH", face_amount=900000.00,
    )
    validate_success(api.accept_bond_instrument(instrument_a["id"], BOND_SPECIALIST_ACCEPTER))

    ctx_b = chain_estimate_accepted(
        operator=ctx_a["operator"],
        site_overrides={"name": "Cross Permit Pit B", "county": "Mohave", "total_acres": 300.00},
        mining_plan_acres=120.00,
    )
    instrument_b = propose_instrument(
        ctx_b["permit"]["id"], ctx_b["operator_headers"],
        instrument_type="CASH", face_amount=900000.00,
        replaces_instrument_id=instrument_a["id"],
    )

    response = api.accept_bond_instrument(instrument_b["id"], BOND_SPECIALIST_ACCEPTER)
    validate_error(response, ApiErrorId.ERR_SUBSTITUTION_TARGET_INVALID, 409)

    target = validate_success(
        api.get_bond_instrument(instrument_a["id"], BOND_SPECIALIST_ACCEPTER)
    )
    assert target["status"] == "ACCEPTED", "the resolvable target is untouched"
    attempted = validate_success(
        api.get_bond_instrument(instrument_b["id"], BOND_SPECIALIST_ACCEPTER)
    )
    assert attempted["status"] == "PROPOSED"
    assert_money(attempted["credited_amount"], 0.00, "credited_amount")

    assert_money(
        refresh_permit(ctx_a["permit"]["id"])["bond_held_amount"], 900000.00, "permit A held"
    )
    assert_money(
        refresh_permit(ctx_b["permit"]["id"])["bond_held_amount"], 0.00, "permit B held"
    )


def _boundary_peak_self_bond():
    """A QUALIFIED operator whose single ACCEPTED self-bond consumes all headroom."""
    operator = register_qualified_operator(
        legal_name="Boundary Peak Mining",
        tangible_net_worth=10000000.00,
        fixed_assets_in_state=6000000.00,
        total_liabilities=4000000.00,
        net_income_prior_year=1000000.00,
        elected_financial_test="NET_WORTH_TEST",
    )
    ctx = chain_estimate_accepted(
        operator=operator,
        site_overrides={
            "name": "Boundary Peak Quarry", "county": "Esmeralda", "total_acres": 300.00,
        },
        mining_plan_acres=120.00,
    )
    proposed = propose_instrument(
        ctx["permit"]["id"], ctx["operator_headers"],
        instrument_type="SELF_BOND", face_amount=2500000.00,
    )
    ctx["instrument"] = validate_success(
        api.accept_bond_instrument(proposed["id"], BOND_SPECIALIST_ACCEPTER)
    )
    return ctx


def test_self_bond_acceptance_consumes_the_operators_whole_headroom():
    """A `SELF_BOND` instrument credits 0.00 whenever the operator's
    `self_bond_status` is anything other than `QUALIFIED`; otherwise it credits
    the lesser of `face_amount` and the operator's remaining self-bond headroom,
    that headroom being `self_bond_capacity_amount` minus
    `self_bond_exposure_amount`, rounded half up to two decimals and floored at
    zero.

    Design: Difficulty/priority_pair_validation_conflict/instrument_own_state_outranks_self_bond_capacity_check
    """
    ctx = _boundary_peak_self_bond()

    assert ctx["instrument"]["status"] == "ACCEPTED"
    assert_money(ctx["instrument"]["credited_amount"], 2500000.00, "credited_amount")

    operator = refresh_operator(ctx["operator"]["id"])
    assert_money(operator["self_bond_capacity_amount"], 2500000.00, "self_bond_capacity_amount")
    assert_money(operator["self_bond_exposure_amount"], 2500000.00, "self_bond_exposure_amount")

    permit = refresh_permit(ctx["permit"]["id"])
    assert_money(permit["bond_held_amount"], 2500000.00, "bond_held_amount")
    assert_permit_ledger_invariants(permit)


def test_replayed_acceptance_reports_instrument_state_not_capacity():
    """The system evaluates checks in strict ascending priority order,
    short-circuits at the **first** violated rule, and returns that rule's error
    and nothing else.

    Design: Difficulty/priority_pair_validation_conflict/instrument_own_state_outranks_self_bond_capacity_check
    """
    ctx = _boundary_peak_self_bond()
    instrument_id = ctx["instrument"]["id"]

    # Own-state admissibility sits at priority 9 and the self-bond capacity
    # ceiling at priority 15, while the remaining headroom is now 0.00.
    response = api.accept_bond_instrument(instrument_id, BOND_SPECIALIST_ACCEPTER)
    error = validate_error(response, ApiErrorId.ERR_INSTRUMENT_STATE_INVALID, 409)
    assert error["error_id"] != "ERR_SELF_BOND_CAPACITY_EXCEEDED", (
        "the earlier band wins even though the fiscal ceiling is also violated"
    )

    unchanged = validate_success(
        api.get_bond_instrument(instrument_id, BOND_SPECIALIST_ACCEPTER)
    )
    assert unchanged["status"] == "ACCEPTED", "the replay changed nothing"
    assert_money(unchanged["credited_amount"], 2500000.00, "credited_amount")

    permit = refresh_permit(ctx["permit"]["id"])
    assert_money(permit["bond_held_amount"], 2500000.00, "bond_held_amount")
    assert permit["bond_held_amount"] != 5000000.00, "the credit is not counted twice"
    assert_money(
        refresh_operator(ctx["operator"]["id"])["self_bond_exposure_amount"],
        2500000.00,
        "self_bond_exposure_amount",
    )


def test_ledger_cascade_is_visible_in_the_triggering_response():
    """Where the specification says a cascade fires, the implementation must
    apply every link of it inside the same request, and the response returned to
    the client is the resource the client addressed — the cascade's other effects
    are observable only through subsequent reads.

    Design: Corner/consistency_model/bond_ledger_cascade_is_visible_in_the_triggering_response
    """
    ctx = chain_estimate_accepted(
        operator_overrides={
            "legal_name": "Immediate Ledger Mining",
            "tangible_net_worth": 16400000.00,
            "fixed_assets_in_state": 8060000.00,
            "total_liabilities": 5160000.00,
            "net_income_prior_year": 680000.00,
            "elected_financial_test": "NET_WORTH_TEST",
        },
        site_overrides={"name": "Immediate Ledger Pit", "county": "Graham", "total_acres": 260.00},
        mining_plan_acres=120.00,
    )
    assert ctx["estimate"]["status"] == "ACCEPTED", (
        "the acceptance response itself shows the estimate took effect"
    )
    proposed = validate_success(
        api.create_bond_instrument(
            create_surety_instrument_payload(
                ctx["permit"]["id"], rating="A", face_amount=900000.00,
                surety_company_name="Cordillera Surety",
            ),
            ctx["operator_headers"],
        ),
        201,
    )

    accepted = validate_success(
        api.accept_bond_instrument(proposed["id"], BOND_SPECIALIST_ACCEPTER)
    )
    assert accepted["status"] == "ACCEPTED", "the addressed resource is returned"
    assert_money(accepted["credited_amount"], 810000.00, "credited_amount")

    permit = validate_success(
        api.get_permit(ctx["permit"]["id"], BOND_SPECIALIST_ACCEPTER)
    )
    assert_money(permit["bond_held_amount"], 810000.00, "bond_held_amount")
    assert permit["compliance_posture"] == "BOND_DEFICIENT", (
        "the posture recomputation settled inside the accepting request"
    )

    summary = validate_success(
        api.get_bond_summary(ctx["permit"]["id"], BOND_SPECIALIST_ACCEPTER)
    )
    assert_money(summary["bond_deficiency_amount"], 55998.00, "bond_deficiency_amount")
    assert_money(
        summary["bond_deficiency_amount"],
        permit["bond_deficiency_amount"],
        "the computed read agrees with the stored field",
    )
