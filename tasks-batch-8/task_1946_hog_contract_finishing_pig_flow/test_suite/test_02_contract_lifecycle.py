"""Contract lifecycle guards: activation preconditions, the effectiveness
window, site exclusivity, and terminal-exit blockers.
"""
from test_helpers import (
    ApiErrorId,
    assert_contract,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_contract_payload
from test_helpers.fixtures import (
    ADMIN,
    ADMIN2,
    FIELDTECH,
    create_active_contract,
    create_grower,
    create_site,
    get_settlement_for_group,
    set_clock,
    setup_placed_group,
)


class TestActivationGuards:
    def test_contract_activate_suspended_grower_rejected(self, api):
        """PRD §3.1: "Activation moves a contract `DRAFT` → `ACTIVE` and
        enforces four checks: the grower must be `ACTIVE`
        (`ERR_GROWER_NOT_ACTIVE` when suspended), the site must be `ACTIVE`
        (`ERR_SITE_NOT_ACTIVE` when suspended), ...".
        PRD §3.1: "suspension moves `grower_status` to `SUSPENDED` and blocks
        activation of that grower's contracts until reinstatement returns them
        to `ACTIVE`."

        Design: Corner/state_machines/contract_activate_suspended_grower_rejected
        """
        site = create_site(name="S")
        grower = create_grower()
        res = api.create_contract(
            create_contract_payload(grower["id"], site["id"]), ADMIN
        )
        contract = validate_success(res, 201)
        get_success_data(api.suspend_grower(grower["id"], ADMIN))

        res = api.activate_contract(contract["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_GROWER_NOT_ACTIVE, expected_status=409)

        after = validate_success(api.get_contract(contract["id"], ADMIN), 200)
        assert after["contract_status"] == "DRAFT"

    def test_contract_site_overlap_rejected(self, api):
        """PRD §3.1: "no other contract covering the same site may already be
        `ACTIVE` (`ERR_CONTRACT_SITE_OVERLAP`)."

        Design: Corner/errors/contract_site_overlap_rejected
        """
        site = create_site(name="S")
        grower = create_grower()
        contract1 = create_active_contract(grower["id"], site["id"])
        assert contract1["contract_status"] == "ACTIVE"

        res = api.create_contract(
            create_contract_payload(
                grower["id"], site["id"], base_pay_cents_per_head=4100
            ),
            ADMIN,
        )
        contract2 = validate_success(res, 201)

        res = api.activate_contract(contract2["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_CONTRACT_SITE_OVERLAP, expected_status=409)

        after = validate_success(api.get_contract(contract2["id"], ADMIN), 200)
        assert after["contract_status"] == "DRAFT"

    def test_contract_window_errors(self, api):
        """PRD §3.1: "the clock date must fall on or after `effective_date` and
        on or before `expiry_date` (failing early with
        `ERR_CONTRACT_NOT_YET_EFFECTIVE` and late with `ERR_CONTRACT_EXPIRED`)".
        PRD §3.1: "Termination moves the contract to `TERMINATED`; expiry moves
        it to `EXPIRED` and additionally requires the clock date to have passed
        `expiry_date` — expiring too early fails with `ERR_CONTRACT_NOT_EXPIRED`."

        Design: Corner/errors/contract_window_errors
        """
        site1 = create_site(name="S1", county="Sioux")
        site2 = create_site(name="S2", county="Lyon")
        grower = create_grower()
        contract_a = validate_success(
            api.create_contract(
                create_contract_payload(
                    grower["id"], site1["id"],
                    effective_date="2026-06-01", expiry_date="2026-12-31",
                ),
                ADMIN,
            ),
            201,
        )
        contract_b = validate_success(
            api.create_contract(
                create_contract_payload(
                    grower["id"], site2["id"],
                    effective_date="2026-01-01", expiry_date="2026-06-30",
                ),
                ADMIN,
            ),
            201,
        )

        # Early: clock 2026-05-15 is before contract A's effective 2026-06-01.
        set_clock("2026-05-15T00:00:00Z")
        res = api.activate_contract(contract_a["id"], ADMIN)
        validate_error(
            res, ApiErrorId.ERR_CONTRACT_NOT_YET_EFFECTIVE, expected_status=409
        )

        # Late: clock 2026-08-01 is after contract B's expiry 2026-06-30.
        set_clock("2026-08-01T00:00:00Z")
        res = api.activate_contract(contract_b["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_CONTRACT_EXPIRED, expected_status=409)

        # Contract A activates fine inside its window ...
        activated = validate_success(api.activate_contract(contract_a["id"], ADMIN), 200)
        assert_contract(activated)
        assert activated["contract_status"] == "ACTIVE"

        # ... but expiring while clock 2026-08-01 <= expiry 2026-12-31 fails.
        res = api.expire_contract(contract_a["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_EXPIRED, expected_status=409)


class TestTerminateBlockers:
    def test_contract_terminate_blockers(self, api):
        """PRD §3.1: "Both exits share the same blockers: any pig group under
        the contract still `SCHEDULED`, `PLACED`, or `MARKETING` rejects the
        request with `ERR_CONTRACT_HAS_ACTIVE_GROUPS`, and any settlement under
        the contract still `FINALIZED`, `DISPUTED`, or `APPROVED` rejects it
        with `ERR_SETTLEMENTS_PENDING`."
        PRD §3.8: "If `head_unaccounted` is greater than zero — a force
        close-out left pigs unaccounted — the `bonus_cents` is zero."

        Design: Corner/errors/contract_terminate_blockers
        """
        ctx = setup_placed_group(head_placed=100)
        contract_id = ctx["contract"]["id"]
        group_id = ctx["group"]["id"]

        # Live group blocks termination.
        res = api.terminate_contract(contract_id, ADMIN)
        validate_error(
            res, ApiErrorId.ERR_CONTRACT_HAS_ACTIVE_GROUPS, expected_status=409
        )

        # Force close-out mints a FINALIZED settlement, which now blocks.
        get_success_data(api.close_out_pig_group(group_id, FIELDTECH))
        res = api.terminate_contract(contract_id, ADMIN)
        validate_error(res, ApiErrorId.ERR_SETTLEMENTS_PENDING, expected_status=409)

        settlement = get_settlement_for_group(group_id)
        assert settlement["settlement_status"] == "FINALIZED"
        # Force close-out of a 100-head group markets nothing: the
        # incomplete-marketing gate zeroes the bonus; base pay stands alone.
        assert settlement["base_pay_cents"] == 400000
        assert settlement["bonus_cents"] == 0
        assert settlement["total_pay_cents"] == 400000
        group_after = get_success_data(api.get_pig_group(group_id, ADMIN))
        assert group_after["head_unaccounted"] == 100
        assert group_after["head_current"] == 0

        # Approve (adm_1) and pay (adm_2) clear the blocker; terminate succeeds.
        get_success_data(api.approve_settlement(settlement["id"], ADMIN))
        get_success_data(api.pay_settlement(settlement["id"], ADMIN2))
        terminated = validate_success(api.terminate_contract(contract_id, ADMIN), 200)
        assert terminated["contract_status"] == "TERMINATED"
