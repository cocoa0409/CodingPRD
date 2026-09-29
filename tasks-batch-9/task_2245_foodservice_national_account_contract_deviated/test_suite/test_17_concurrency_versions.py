"""Optimistic concurrency on the two tokens a client must carry: the parent
contract's version on a deviation draft, and the agreement's own version on a
bill-back claim. Both move on writes the token holder never made.
"""
from test_helpers import (
    AUG_05,
    NOV_START,
    SEP_START,
    TERM_START,
    add_coverage,
    add_tier,
    api_client,
    bill_back_claim_payload,
    bootstrap_partners,
    build_signed_contract,
    create_contract_draft,
    create_deviation,
    create_invoiced_line,
    create_product,
    decide_deviation,
    deviation_agreement_payload,
    open_rebate_period,
    submit_deviation,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ACCOUNTANT, ANALYST, NAM

FLAT_COST = {
    "last_cost_cents": 4000,
    "avg_cost_cents": 4000,
    "replacement_cost_cents": 4000,
}
PROTEIN_QUARTER = {
    "product_class_code": "PROTEIN",
    "cost_basis": "LAST_COST",
    "markup_type": "PERCENT_OF_COST",
    "markup_value": 25.00,
    "min_case_volume": 0,
}


def _chicken(manufacturer_id, **overrides):
    return create_product(manufacturer_id, **dict(FLAT_COST, **overrides))


class TestContractVersionToken:
    def test_a_replayed_contract_version_is_refused_and_the_re_read_one_works(self):
        """PRD §2.4: "`version` is an integer that starts at 1 on creation and
        increases by exactly 1 on every mutation of that row; `updated_at` is
        refreshed on the same mutation."

        PRD §2.8: "`expected_contract_version` matches the referenced contract's
        `version` — `ERR_STALE_CONTRACT_VERSION` (412), on deviation create."

        PRD §3.4: "A successful draft lands in `DRAFT` with `revision_round` 0,
        `price_revision_count` 0, and `submitted_by_user_id` and
        `manufacturer_decision_note` both null, and it increments the parent
        contract's `version` by 1."

        Design: Corner/Cross-Cutting Complexity Layers/stale_expected_contract_version_is_refused_with_412
        """
        world = bootstrap_partners()
        chicken = _chicken(world["manufacturer_id"])
        contract = create_contract_draft(
            world["operator_id"], world["manufacturer_id"]
        )
        contract_id = contract["id"]
        assert contract["version"] == 1
        add_tier(contract_id, **PROTEIN_QUARTER)
        add_coverage(contract_id, world["dc_id"])

        submitted = validate_success(
            api_client.submit_contract_for_signature(contract_id, NAM)
        )
        assert submitted["version"] == 2
        signed = validate_success(
            api_client.sign_contract(contract_id, world["buyer"])
        )
        assert signed["status"] == "ACTIVE"
        assert signed["version"] == 3
        stale_token = signed["version"]

        # Two writes the deviation client never made move the token.
        suspended = validate_success(
            api_client.suspend_contract(contract_id, NAM, {"note": "Credit review"})
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["version"] == 4
        reinstated = validate_success(
            api_client.reinstate_contract(contract_id, NAM)
        )
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["version"] == 5

        payload = deviation_agreement_payload(
            contract_id,
            chicken["id"],
            world["manufacturer_id"],
            stale_token,
            5000,
            TERM_START,
            NOV_START,
            requested_net_price_cents=4200,
        )
        validate_error(
            api_client.create_deviation_agreement(payload, ANALYST),
            "ERR_STALE_CONTRACT_VERSION",
            412,
        )

        fresh = validate_success(api_client.get_contract(contract_id, ANALYST))
        assert fresh["version"] == 5
        payload["expected_contract_version"] = fresh["version"]
        agreement = validate_success(
            api_client.create_deviation_agreement(payload, ANALYST), 201
        )
        assert agreement["status"] == "DRAFT"
        assert agreement["version"] == 1
        assert agreement["deviated_price_cents"] == 4200
        # The refusal wrote nothing: one agreement, and the parent moved once.
        rows, page = validate_paginated(
            api_client.list_deviation_agreements(
                ANALYST, {"contract_id": contract_id, "limit": 10, "offset": 0}
            )
        )
        assert [row["id"] for row in rows] == [agreement["id"]]
        assert page["total_count"] == 1
        assert (
            validate_success(api_client.get_contract(contract_id, NAM))["version"] == 6
        )


class TestDeviationVersionToken:
    def test_a_pre_activation_deviation_version_is_refused_on_claim_create(self):
        """PRD §2.8: "`expected_deviation_agreement_version` matches the referenced
        agreement's `version` — `ERR_STALE_DEVIATION_VERSION` (412), on claim
        create."

        PRD §3.8: "A `RebateAccountant` accrues that expectation as a claim by
        naming the `deviation_agreement_id`, the half-open sweep window
        `claim_period_start` to `claim_period_end`, and
        `expected_deviation_agreement_version`."

        PRD §3.8: "`claimed_amount_cents` accumulates, over the same lines
        iterated in `order_date` ascending order and then `created_at` ascending
        order, the greater of zero and the difference between the line's
        `list_unit_price_cents` and its `invoiced_unit_price_cents`, multiplied by
        that line's `quantity_cases`; clamping each per-line delta at zero means a
        held contract price above list can never produce a negative claim."

        Design: Corner/Cross-Cutting Complexity Layers/stale_expected_deviation_version_is_refused_with_412
        """
        world = bootstrap_partners()
        chicken = _chicken(world["manufacturer_id"])
        signed = build_signed_contract(
            world["operator_id"],
            world["manufacturer_id"],
            world["dc_id"],
            tiers=[PROTEIN_QUARTER],
        )
        contract_id = signed["contract_id"]

        drafted = create_deviation(
            contract_id,
            chicken["id"],
            world["manufacturer_id"],
            5000,
            TERM_START,
            NOV_START,
            requested_net_price_cents=4200,
        )
        assert drafted["version"] == 1
        submitted = submit_deviation(drafted["id"])
        assert submitted["version"] == 2
        approved = decide_deviation(
            drafted["id"], world["manufacturer_id"], "APPROVE"
        )
        assert approved["status"] == "MANUFACTURER_APPROVED"
        assert approved["version"] == 3
        pre_activation_token = approved["version"]
        activated = validate_success(
            api_client.activate_deviation_agreement(drafted["id"], NAM)
        )
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == 4

        open_rebate_period(contract_id, TERM_START, SEP_START)
        line = create_invoiced_line(
            contract_id,
            chicken["id"],
            world["dc_id"],
            world["operator_id"],
            10,
            order_clock=AUG_05,
        )
        assert line["list_unit_price_cents"] == 5000
        assert line["invoiced_unit_price_cents"] == 4200
        assert line["billback_status"] == "ACCRUED"

        claim_payload = bill_back_claim_payload(
            drafted["id"], TERM_START, SEP_START, pre_activation_token
        )
        validate_error(
            api_client.create_bill_back_claim(claim_payload, ACCOUNTANT),
            "ERR_STALE_DEVIATION_VERSION",
            412,
        )

        claim_payload["expected_deviation_agreement_version"] = activated["version"]
        claim = validate_success(
            api_client.create_bill_back_claim(claim_payload, ACCOUNTANT), 201
        )
        assert claim["status"] == "ACCRUED"
        assert claim["claimed_cases"] == 10
        assert claim["claimed_amount_cents"] == 8000
        assert claim["manufacturer_id"] == world["manufacturer_id"]
        assert claim["recovered_amount_cents"] == 0

        assert (
            validate_success(api_client.get_order_line(line["id"], NAM))[
                "billback_status"
            ]
            == "CLAIMED"
        )
        rows, page = validate_paginated(
            api_client.list_bill_back_claims(
                ACCOUNTANT,
                {
                    "deviation_agreement_id": drafted["id"],
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert [row["id"] for row in rows] == [claim["id"]]
        assert page["total_count"] == 1
