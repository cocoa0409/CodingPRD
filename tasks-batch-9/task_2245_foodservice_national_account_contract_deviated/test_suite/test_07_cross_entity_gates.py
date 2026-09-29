"""Two transitions that are gated by the state of a different row: the
manufacturer decision reads the manufacturer's own status, and the dispute audit
reads the status of the rebate period behind the disputed line.
"""
from test_helpers import (
    AUG_10,
    NOV_START,
    SEP_START,
    TERM_START,
    api_client,
    assert_pct,
    bootstrap_partners,
    build_active_deviation,
    build_invoiced_line_world,
    build_signed_contract,
    close_rebate_period,
    create_dispute,
    create_manufacturer,
    create_product,
    decide_deviation,
    make_manufacturer_rep_headers,
    manufacturer_decision_payload,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANALYST, AUDITOR, NAM


def _build_two_funder_world():
    """One SUBMITTED agreement per manufacturer: the beef item is funded by a
    SUSPENDED manufacturer, the chicken item by an ACTIVE one."""
    world = bootstrap_partners()
    suspended_maker = create_manufacturer(
        name="Northwest Beef", manufacturer_code="NWB", status="SUSPENDED"
    )
    chicken = create_product(world["manufacturer_id"])
    beef = create_product(
        suspended_maker["id"],
        sku="P-BEEF",
        description="Beef Chuck 4/10#",
        last_cost_cents=6000,
        avg_cost_cents=5900,
        replacement_cost_cents=6100,
    )
    signed = build_signed_contract(
        world["operator_id"], world["manufacturer_id"], world["dc_id"]
    )
    world.update(signed)
    world["suspended_maker"] = suspended_maker
    world["suspended_maker_id"] = suspended_maker["id"]

    world["beef_deviation"] = build_active_deviation(
        signed["contract_id"],
        beef["id"],
        suspended_maker["id"],
        6200,
        TERM_START,
        NOV_START,
        stage="SUBMITTED",
        requested_net_price_cents=5800,
    )
    world["chicken_deviation"] = build_active_deviation(
        signed["contract_id"],
        chicken["id"],
        world["manufacturer_id"],
        4500,
        TERM_START,
        NOV_START,
        stage="SUBMITTED",
        requested_net_price_cents=3900,
    )
    return world


class TestManufacturerDecisionReadsManufacturerStatus:
    def test_a_suspended_counterparty_cannot_decide_at_all(self):
        """PRD §3.4: "All three branches require the acting `X-User-ID` to equal
        the agreement's `manufacturer_id`, all three require the manufacturer's
        `status` to be `ACTIVE` (a suspended counterparty cannot decide at all,
        and is told so with `ERR_MANUFACTURER_SUSPENDED`), all three write the
        supplied note into `manufacturer_decision_note`, and all three increment
        the agreement's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/manufacturer_decision_requires_active_manufacturer
        """
        world = _build_two_funder_world()
        assert world["suspended_maker"]["status"] == "SUSPENDED"
        agreement = world["beef_deviation"]
        assert agreement["status"] == "SUBMITTED"

        refused = api_client.decide_deviation_agreement(
            agreement["id"],
            manufacturer_decision_payload("APPROVE", "Approved per national program"),
            make_manufacturer_rep_headers(world["suspended_maker_id"]),
        )
        validate_error(refused, "ERR_MANUFACTURER_SUSPENDED", 409)

        unchanged = validate_success(
            api_client.get_deviation_agreement(agreement["id"], ANALYST)
        )
        assert unchanged["status"] == "SUBMITTED"
        assert unchanged["version"] == agreement["version"]
        assert unchanged["manufacturer_decision_note"] is None

    def test_an_active_counterparty_on_the_same_contract_still_approves(self):
        """PRD §3.4: "`APPROVE` moves `SUBMITTED → MANUFACTURER_APPROVED`,
        `REQUEST_REVISION` moves `SUBMITTED → REVISION_REQUESTED` and hands the
        agreement back to the analyst, and `REJECT` moves `SUBMITTED →
        REJECTED`, which is terminal."

        Design: Difficulty/cross_entity_state_dependency/manufacturer_decision_requires_active_manufacturer
        """
        world = _build_two_funder_world()
        agreement = world["chicken_deviation"]

        decided = decide_deviation(agreement["id"], world["manufacturer_id"], "APPROVE")

        assert decided["status"] == "MANUFACTURER_APPROVED"
        assert decided["deviated_price_cents"] == 3900
        assert decided["manufacturer_decision_note"] == "Approved per national program"

        # The suspended funder's agreement was untouched by that decision.
        stalled = validate_success(
            api_client.get_deviation_agreement(world["beef_deviation"]["id"], ANALYST)
        )
        assert stalled["status"] == "SUBMITTED"


def _build_open_period_dispute_world():
    """One invoiced 300-case line at 4725 inside a period that is still OPEN,
    with a dispute claiming 4578 was the correct price."""
    world = build_invoiced_line_world(order_clock=AUG_10)
    world["dispute"] = create_dispute(
        world["order_line_id"], world["operator_id"], 4578, "TIER_MISAPPLIED"
    )
    world["dispute_id"] = world["dispute"]["id"]
    return world


class TestDisputeAuditReadsRebatePeriodStatus:
    def test_the_audit_will_not_start_while_the_period_is_still_open(self):
        """PRD §3.9: "The audit may only begin once the retroactive volume is
        final: the rebate period named by the disputed line's `rebate_period_id`
        must be `CLOSED` or `SETTLED`, otherwise `ERR_REBATE_PERIOD_NOT_CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/dispute_audit_requires_closed_rebate_period
        """
        world = _build_open_period_dispute_world()

        period = validate_success(
            api_client.get_rebate_period(world["rebate_period_id"], NAM)
        )
        assert period["status"] == "OPEN"
        assert world["order_line"]["invoiced_unit_price_cents"] == 4725
        assert world["dispute"]["status"] == "OPEN"

        refused = api_client.start_dispute_audit(world["dispute_id"], AUDITOR)
        validate_error(refused, "ERR_REBATE_PERIOD_NOT_CLOSED", 409)

        unchanged = validate_success(
            api_client.get_pricing_dispute(world["dispute_id"], AUDITOR)
        )
        assert unchanged["status"] == "OPEN"
        assert unchanged["audited_correct_unit_price_cents"] is None
        assert unchanged["variance_cents_per_case"] is None
        assert unchanged["variance_pct"] is None

    def test_closing_the_period_unblocks_the_same_audit_request(self):
        """PRD §3.9: "A `ContractAuditor` starts the audit, moving `OPEN →
        UNDER_AUDIT`."

        Design: Difficulty/cross_entity_state_dependency/dispute_audit_requires_closed_rebate_period
        """
        world = _build_open_period_dispute_world()

        api_client.start_dispute_audit(world["dispute_id"], AUDITOR)

        set_clock(SEP_START)
        closed = close_rebate_period(world["rebate_period_id"])
        assert closed["status"] == "CLOSED"

        audited = validate_success(
            api_client.start_dispute_audit(world["dispute_id"], AUDITOR)
        )
        assert audited["status"] == "UNDER_AUDIT"
        # The single unbounded tier re-derives the same 4725 retroactively.
        assert audited["audited_correct_unit_price_cents"] == 4725
        assert audited["variance_cents_per_case"] == 0
        assert_pct(audited["variance_pct"], 0.00, "variance_pct")
