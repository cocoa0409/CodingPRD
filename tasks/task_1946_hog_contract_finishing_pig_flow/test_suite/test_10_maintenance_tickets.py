"""Maintenance tickets: the pinned owner-first rounding of the cost split, the
FieldTech approval threshold, quote/approve segregation, and the EMERGENCY
fix-first guard.
"""
from test_helpers import (
    ApiErrorId,
    assert_ticket_split_invariants,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    FIELDTECH,
    FIELDTECH2,
    create_ticket,
    get_ticket,
    quote_ticket,
    setup_contract_with_barn,
)


class TestCostSplitRoundingOrder:
    def test_maintenance_split_rounding_order(self, api):
        """PRD §3.7: "Otherwise the owner's percentage is selected from the
        contract by `category` — `structural_owner_pct` for `STRUCTURAL`,
        `equipment_owner_pct` for `EQUIPMENT`, and `routine_owner_pct` for both
        `ROUTINE` and `EMERGENCY` — and the `owner_share_cents` is computed
        first as `cost_cents` multiplied by that percentage and divided by one
        hundred, rounded half-up to a whole cent; the `grower_share_cents` is
        then whatever remains of the `cost_cents`."
        PRD §3.7: "When the cause is `NEGLIGENCE`, the owner bears nothing and
        `grower_share_cents` equals the entire `cost_cents`."

        Odd 10001-cent quotes pin the rounding order: owner-first rounds
        5000.5 up to 5001 (grower takes the 5000 remainder); grower-first
        rounding would flip the cent.

        Design: Difficulty/combinatorial_formula/maintenance_split_rounding_order
        """
        ctx = setup_contract_with_barn()  # splits 100 / 50 / 0
        barn_id = ctx["barn"]["id"]
        grower_id = ctx["grower"]["id"]

        t1 = create_ticket(barn_id, grower_id, category="EQUIPMENT",
                           description="auger")
        quote_ticket(t1["id"], cost_cents=10001, cause="WEAR", quoter=FIELDTECH)
        get_success_data(api.approve_maintenance_ticket(t1["id"], FIELDTECH2))

        t2 = create_ticket(barn_id, grower_id, category="STRUCTURAL",
                           description="roof")
        quote_ticket(t2["id"], cost_cents=10001, cause="WEAR", quoter=FIELDTECH)
        get_success_data(api.approve_maintenance_ticket(t2["id"], FIELDTECH2))

        t3 = create_ticket(barn_id, grower_id, category="ROUTINE",
                           description="washdown")
        quote_ticket(t3["id"], cost_cents=10001, cause="NEGLIGENCE",
                     quoter=FIELDTECH)
        get_success_data(api.approve_maintenance_ticket(t3["id"], FIELDTECH2))

        t1 = get_ticket(t1["id"])
        assert t1["owner_share_cents"] == 5001   # round_half_up(10001 * 0.50)
        assert t1["grower_share_cents"] == 5000  # remainder
        assert_ticket_split_invariants(t1)

        t2 = get_ticket(t2["id"])
        assert t2["owner_share_cents"] == 10001  # 100% owner
        assert t2["grower_share_cents"] == 0
        assert_ticket_split_invariants(t2)

        t3 = get_ticket(t3["id"])
        assert t3["owner_share_cents"] == 0      # NEGLIGENCE: owner bears none
        assert t3["grower_share_cents"] == 10001
        assert_ticket_split_invariants(t3)

    def test_split_rounding_half_up_and_even_amounts(self, api):
        """PRD §2.9: "Money is represented as integer cents throughout ...;
        where a computation produces fractional cents, the result is rounded
        half-up to a whole cent".
        PRD §3.7: "the `owner_share_cents` is computed first as `cost_cents`
        multiplied by that percentage and divided by one hundred, rounded
        half-up to a whole cent; the `grower_share_cents` is then whatever
        remains of the `cost_cents`."

        round_half_up(33333 * 0.5) = round_half_up(16666.5) = 16667 (not
        banker's 16666); an even 10000-cent quote splits 5000/5000.

        Design: Difficulty/combinatorial_formula/maintenance_split_rounding_order
        """
        ctx = setup_contract_with_barn()
        barn_id = ctx["barn"]["id"]
        grower_id = ctx["grower"]["id"]

        t1 = create_ticket(barn_id, grower_id, category="EQUIPMENT",
                           description="fan belt")
        quote_ticket(t1["id"], cost_cents=33333, cause="ACT_OF_NATURE",
                     quoter=FIELDTECH)
        get_success_data(api.approve_maintenance_ticket(t1["id"], FIELDTECH2))
        t1 = get_ticket(t1["id"])
        assert t1["owner_share_cents"] == 16667
        assert t1["grower_share_cents"] == 16666
        assert_ticket_split_invariants(t1)

        t2 = create_ticket(barn_id, grower_id, category="EQUIPMENT",
                           description="even split")
        quote_ticket(t2["id"], cost_cents=10000, cause="WEAR", quoter=FIELDTECH)
        get_success_data(api.approve_maintenance_ticket(t2["id"], FIELDTECH2))
        t2 = get_ticket(t2["id"])
        assert t2["owner_share_cents"] == 5000
        assert t2["grower_share_cents"] == 5000


class TestApprovalAuthority:
    def test_ticket_approve_threshold_role(self, api):
        """PRD §3.7: "Approval of a quote is both thresholded and segregated: a
        `FieldTech` may approve only when `cost_cents` is below 50,000 cents,
        while an `IntegratorAdmin` may approve any amount (a `FieldTech`
        attempt at or above the threshold fails with `ERR_FORBIDDEN_ROLE`), and
        the approver's identity must differ from `quoted_by`
        (`ERR_SEGREGATION_OF_DUTIES`)."
        PRD §2.6: "One role check is value-dependent: on ticket approval, a
        `FieldTech` may approve only when the quoted `cost_cents` is below
        50,000 cents, and a `FieldTech` attempt at or above that amount fails
        here rather than later."

        Design: Corner/endpoints/ticket_approve_threshold_role
        """
        ctx = setup_contract_with_barn()
        ticket = create_ticket(ctx["barn"]["id"], ctx["grower"]["id"],
                               category="STRUCTURAL",
                               description="curtain wall")
        quote_ticket(ticket["id"], cost_cents=60000, cause="WEAR",
                     quoter=FIELDTECH)

        # 60000 >= 50000: FieldTech approval fails at the role check.
        res = api.approve_maintenance_ticket(ticket["id"], FIELDTECH2)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
        assert get_ticket(ticket["id"])["ticket_status"] == "QUOTED"

        approved = validate_success(
            api.approve_maintenance_ticket(ticket["id"], ADMIN), 200
        )
        assert approved["ticket_status"] == "APPROVED"
        assert approved["approved_by"] == "adm_1"
        assert approved["approved_flag"] is True
        assert approved["owner_share_cents"] == 60000  # STRUCTURAL 100%
        assert approved["grower_share_cents"] == 0

    def test_sod_quote_approve_same_user_rejected(self, api):
        """PRD §3.7: "Approval of a quote is both thresholded and segregated:
        ... and the approver's identity must differ from `quoted_by`
        (`ERR_SEGREGATION_OF_DUTIES`)."
        PRD §2.11: "the operator who **quotes** a maintenance ticket may not
        **approve** it".

        Design: Corner/rbac/sod_quote_approve_same_user_rejected
        """
        ctx = setup_contract_with_barn()
        ticket = create_ticket(ctx["barn"]["id"], ctx["grower"]["id"],
                               category="EQUIPMENT", description="fan")
        quote_ticket(ticket["id"], cost_cents=30000, cause="WEAR",
                     quoter=FIELDTECH)  # quoted by ft_1

        res = api.approve_maintenance_ticket(ticket["id"], FIELDTECH)  # ft_1 again
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=403)
        assert get_ticket(ticket["id"])["ticket_status"] == "QUOTED"

        approved = validate_success(
            api.approve_maintenance_ticket(ticket["id"], FIELDTECH2), 200
        )
        assert approved["ticket_status"] == "APPROVED"
        assert approved["approved_by"] == "ft_2"
        assert approved["owner_share_cents"] == 15000  # EQUIPMENT 50% of 30000
        assert approved["grower_share_cents"] == 15000


class TestEmergencyPath:
    def test_emergency_complete_unapproved_rejected(self, api):
        """PRD §3.7: "For a ticket whose `category` is `EMERGENCY`, a
        `FieldTech` may start work directly from `QUOTED` — `QUOTED` →
        `IN_PROGRESS` without waiting for approval".
        PRD §3.7: "Completion requires `approved_flag` to be true; completing
        an unapproved ticket fails with `ERR_TICKET_UNAPPROVED`."

        Design: Corner/errors/emergency_complete_unapproved_rejected
        """
        ctx = setup_contract_with_barn()
        ticket = create_ticket(ctx["barn"]["id"], ctx["grower"]["id"],
                               category="EMERGENCY",
                               description="water line burst")
        quote_ticket(ticket["id"], cost_cents=30000, cause="WEAR",
                     quoter=FIELDTECH)

        started = validate_success(
            api.start_work_maintenance_ticket(ticket["id"], FIELDTECH), 200
        )
        assert started["ticket_status"] == "IN_PROGRESS"

        res = api.complete_maintenance_ticket(ticket["id"], FIELDTECH)
        validate_error(res, ApiErrorId.ERR_TICKET_UNAPPROVED, expected_status=409)
        assert get_ticket(ticket["id"])["ticket_status"] == "IN_PROGRESS"
