"""Contracts: conditional fields, uniqueness, negotiation cycle, OCC, sign gates."""
from test_helpers import (
    ApiErrorId,
    create_contract,
    create_contract_payload,
    draft_plan,
    offer_contract,
    setup_assessed_casualty,
    setup_planned_casualty,
    submit_plan,
    validate_error,
    validate_success,
)


def test_contract_fixed_price_conditional_field_rejected(api, contracts_officer_headers):
    """PRD 3.3: "The schema rule on `fixed_price_cents` is strict: it must be
    present and positive exactly when the form is `FIXED_PRICE`, and it is
    forbidden on a `NO_CURE_NO_PAY` contract."
    PRD 2.7: "Any failure here yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/contract_fixed_price_conditional_field_rejected
    """
    ctx = setup_planned_casualty(casualty_overrides={"vessel_name": "MV Pax"})
    res1 = api.create_contract(
        create_contract_payload(ctx["casualty"]["id"], ctx["plan"]["id"],
                                form="FIXED_PRICE"),
        contracts_officer_headers,
    )
    validate_error(res1, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
    res2 = api.create_contract(
        create_contract_payload(ctx["casualty"]["id"], ctx["plan"]["id"],
                                form="NO_CURE_NO_PAY", fixed_price_cents=1000),
        contracts_officer_headers,
    )
    validate_error(res2, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_duplicate_active_contract_rejected(api, contracts_officer_headers):
    """PRD 3.3: "A casualty supports at most one contract whose status is not
    `SETTLED` or `TERMINATED`; attempting to create a second non-terminal
    contract on the same casualty fails with `ERR_DUPLICATE_ACTIVE_CONTRACT`."

    Design: Corner/validations/duplicate_active_contract_rejected
    """
    ctx = setup_planned_casualty(casualty_overrides={"vessel_name": "MV Pax"})
    create_contract(ctx["casualty"]["id"], ctx["plan"]["id"])
    res = api.create_contract(
        create_contract_payload(ctx["casualty"]["id"], ctx["plan"]["id"]),
        contracts_officer_headers,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_ACTIVE_CONTRACT, expected_status=409)


def test_contract_sign_from_draft_rejected(api, contracts_officer_headers):
    """PRD 3.3: "Signature by a `ContractsOfficer` moves the contract from
    either `OFFERED` or `COUNTERED` to `SIGNED`."
    PRD 2.7: "Priority 5 covers state permission: an action whose target is in
    the wrong from-state is rejected with `ERR_INVALID_STATE_TRANSITION`"

    Design: Corner/state_machines/contract_sign_from_draft_rejected
    """
    ctx = setup_planned_casualty(casualty_overrides={"vessel_name": "MV Pax"})
    contract = create_contract(ctx["casualty"]["id"], ctx["plan"]["id"])
    assert contract["status"] == "DRAFT"
    res = api.sign_contract(contract["id"], contracts_officer_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    after = validate_success(api.get_contract(contract["id"], contracts_officer_headers), 200)
    assert after["status"] == "DRAFT"
    assert after["provisional_award_cents"] is None, "no figures are computed pre-sign"


def test_plan_not_approved_blocks_signing(api, contracts_officer_headers):
    """PRD 3.3: "Signing is gated on the paperwork beneath the deal: the
    latest-created assessment of the casualty must exist in `APPROVED` status,
    otherwise the sign is rejected with `ERR_ASSESSMENT_NOT_APPROVED`, and the
    contract's `plan_id` must reference a plan in `APPROVED` status, otherwise
    it is rejected with `ERR_PLAN_NOT_APPROVED`."

    Design: Corner/validations/plan_not_approved_blocks_signing
    """
    # Casualty assessed (assessment APPROVED) but the plan is left SUBMITTED.
    ctx = setup_assessed_casualty(casualty_overrides={"vessel_name": "MV Pax"})
    plan = draft_plan(ctx["casualty"]["id"])
    plan = submit_plan(plan["id"])
    assert plan["status"] == "SUBMITTED"
    contract = create_contract(ctx["casualty"]["id"], plan["id"])
    contract = offer_contract(contract["id"])
    res = api.sign_contract(contract["id"], contracts_officer_headers)
    validate_error(res, ApiErrorId.ERR_PLAN_NOT_APPROVED, expected_status=422)
    after = validate_success(api.get_contract(contract["id"], contracts_officer_headers), 200)
    assert after["status"] == "OFFERED"


class TestNegotiationCycle:
    """The OFFERED <-> COUNTERED cycle, each hop OCC-guarded."""

    def _setup_offered(self):
        ctx = setup_planned_casualty(casualty_overrides={"vessel_name": "MV Pax"})
        contract = create_contract(ctx["casualty"]["id"], ctx["plan"]["id"])
        assert contract["status"] == "DRAFT" and contract["negotiation_round"] == 0
        contract = offer_contract(contract["id"])
        return ctx, contract

    def test_offer_counter_counter_cycle_states_and_rounds(self, api, contracts_officer_headers):
        """PRD 3.3: "Negotiation is an explicit cycle. Issuing the opening offer
        moves the contract from `DRAFT` to `OFFERED`, sets `negotiation_round`
        to 1, and increments the contract's `version`. Each counter-offer flips
        the contract between `OFFERED` and `COUNTERED`, increments
        `negotiation_round` by 1, and increments `version`"

        Design: Difficulty/non_linear_state_machine/contract_negotiation_offer_counter_cycle
        """
        _, contract = self._setup_offered()
        assert contract["status"] == "OFFERED"
        assert contract["negotiation_round"] == 1
        v_offer = contract["version"]

        c1 = validate_success(
            api.counter_contract(
                contract["id"], {"expected_contract_version": v_offer},
                contracts_officer_headers,
            ),
            200,
        )
        assert c1["status"] == "COUNTERED", "cycle leg OFFERED -> COUNTERED"
        assert c1["negotiation_round"] == 2
        assert c1["version"] == v_offer + 1, "each hop increments version by 1"

        c2 = validate_success(
            api.counter_contract(
                contract["id"], {"expected_contract_version": c1["version"]},
                contracts_officer_headers,
            ),
            200,
        )
        assert c2["status"] == "OFFERED", "cycle leg COUNTERED -> OFFERED"
        assert c2["negotiation_round"] == 3
        assert c2["version"] == c1["version"] + 1

    def test_sign_after_cycle_computes_flat_provisional(self, api, contracts_officer_headers):
        """PRD 3.3: "Signature by a `ContractsOfficer` moves the contract from
        either `OFFERED` or `COUNTERED` to `SIGNED`."
        PRD 3.3: "for a `NO_CURE_NO_PAY` contract, `provisional_award_cents` is
        twelve percent of the casualty's `declared_salved_value_cents`, rounded
        half up to integer cents"

        Design: Difficulty/non_linear_state_machine/contract_negotiation_offer_counter_cycle
        """
        ctx, contract = self._setup_offered()
        c1 = validate_success(
            api.counter_contract(
                contract["id"], {"expected_contract_version": contract["version"]},
                contracts_officer_headers,
            ),
            200,
        )
        c2 = validate_success(
            api.counter_contract(
                contract["id"], {"expected_contract_version": c1["version"]},
                contracts_officer_headers,
            ),
            200,
        )
        signed = validate_success(api.sign_contract(contract["id"], contracts_officer_headers), 200)
        assert signed["status"] == "SIGNED"
        assert signed["provisional_award_cents"] == 24_000_000, (
            "12% of declared 200,000,000"
        )


def test_contract_counter_stale_version_rejected(api, contracts_officer_headers):
    """PRD 2.9: "Filing a counter-offer against a salvage contract requires
    `expected_contract_version` to equal the contract's current `version` at the
    moment of the write; if another writer has advanced the contract's version
    since the client last read it — for example because the other party's
    counter has just been recorded, legitimately superseding the terms under
    negotiation — the request is rejected with `ERR_STALE_CONTRACT_VERSION` and
    HTTP status 412"

    Design: Corner/cross_cutting_layers/contract_counter_stale_version_rejected
    """
    ctx = setup_planned_casualty(casualty_overrides={"vessel_name": "MV Pax"})
    contract = create_contract(ctx["casualty"]["id"], ctx["plan"]["id"])
    contract = offer_contract(contract["id"])
    stale_version = contract["version"]
    first = validate_success(
        api.counter_contract(
            contract["id"], {"expected_contract_version": stale_version},
            contracts_officer_headers,
        ),
        200,
    )
    # The successful counter advanced the version; replaying the stale read fails.
    res = api.counter_contract(
        contract["id"], {"expected_contract_version": stale_version},
        contracts_officer_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_CONTRACT_VERSION, expected_status=412)
    after = validate_success(api.get_contract(contract["id"], contracts_officer_headers), 200)
    assert after["status"] == "COUNTERED"
    assert after["version"] == first["version"], "the rejected counter changes nothing"
    assert after["negotiation_round"] == first["negotiation_round"]
