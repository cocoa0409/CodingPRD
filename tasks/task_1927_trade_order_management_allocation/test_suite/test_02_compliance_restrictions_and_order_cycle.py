"""Pre-trade compliance gates, restriction windows, and the Order re-check /
block-membership cycles (PRD §3.3, §3.4, §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_restriction,
    approve_order,
    attach_order,
    create_account,
    create_active_restriction,
    create_block,
    create_restriction,
    create_security,
    get_block,
    get_order,
    setup_posted_plan,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["desk_admin_headers"]
TRADER = TEST_USERS["trader_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


class TestComplianceRecheckCycle:
    def test_prohibited_restriction_rejects_then_retire_allows_recheck(self, api):
        """PRD §3.4: "If an applicable ACTIVE PROHIBITED rule matches the order, or the order would breach an applicable ACTIVE MAX_POSITION_UNITS rule, the order transitions to `COMPLIANCE_REJECTED`, the failing rule's error id — `ERR_TRADE_PROHIBITED` or `ERR_POSITION_LIMIT_BREACH`, in that precedence — is recorded as the order's `compliance_note`, and an `ORDER_COMPLIANCE_REJECTED` event is written."
        PRD §3.4: "An order already `COMPLIANCE_REJECTED` can be checked again after the world changes — a restriction retired, an account resumed."
        PRD §3.4: "If the gates now pass, the order moves `COMPLIANCE_REJECTED → APPROVED` under the same preconditions as a fresh check, its `compliance_note` is cleared, and `ORDER_COMPLIANCE_APPROVED` is written."

        Design: Difficulty/non_linear_state_machine/order_compliance_recheck_and_block_membership_cycles
        """
        account = create_account()
        security = create_security()
        restriction = create_active_restriction(
            account_id=account["id"], security_id=security["id"],
            rule_type="PROHIBITED", side="BUY",
        )
        order = validate_success(
            api.create_order(
                {"account_id": account["id"], "security_id": security["id"],
                 "side": "BUY", "order_qty": 100, "order_type": "MARKET"},
                TRADER,
            ),
            201,
        )

        first = validate_success(api.compliance_check_order(order["id"], COMPLIANCE))
        assert first["status"] == "COMPLIANCE_REJECTED", (
            f"PROHIBITED rule must reject the order, got {first['status']}"
        )
        assert first["compliance_note"] == "ERR_TRADE_PROHIBITED", (
            f"compliance_note must carry the failing rule's error id, got {first['compliance_note']!r}"
        )

        validate_success(api.retire_restriction(restriction["id"], COMPLIANCE))
        second = validate_success(api.compliance_check_order(order["id"], COMPLIANCE))
        assert second["status"] == "APPROVED", (
            f"Re-check after retire must approve (COMPLIANCE_REJECTED → APPROVED), got {second['status']}"
        )
        assert second["compliance_note"] is None, (
            f"compliance_note must be cleared on approval, got {second['compliance_note']!r}"
        )

    def test_attach_then_detach_returns_order_to_approved(self, api):
        """PRD §3.5: "A successful attach sets the order's `block_id` to the block, moves the order `APPROVED → BLOCKED`, adds its `order_qty` into the block's `total_qty`, increments the block's `version`, and writes `ORDER_ATTACHED`."
        PRD §3.5: "The order returns `BLOCKED → APPROVED` with `block_id` cleared, the block's `total_qty` loses the order's quantity, the block's `version` increments, `ORDER_DETACHED` lands, and the detachment responds with 204 and no body."

        Design: Difficulty/non_linear_state_machine/order_compliance_recheck_and_block_membership_cycles
        """
        account = create_account()
        security = create_security()
        order = validate_success(
            api.create_order(
                {"account_id": account["id"], "security_id": security["id"],
                 "side": "BUY", "order_qty": 100, "order_type": "MARKET"},
                TRADER,
            ),
            201,
        )
        approve_order(order["id"])
        block = create_block(security["id"])

        attached = attach_order(block["id"], order["id"])
        assert attached["status"] == "BLOCKED"
        assert attached["block_id"] == block["id"]
        assert get_block(block["id"])["total_qty"] == 100

        res = api.detach_order_from_block(block["id"], order["id"], TRADER)
        assert res.status_code == 204, f"Detach must respond 204, got {res.status_code}"

        detached = get_order(order["id"])
        assert detached["status"] == "APPROVED", (
            f"Detach must return the order BLOCKED → APPROVED, got {detached['status']}"
        )
        assert detached["block_id"] is None, (
            f"Detach must clear block_id, got {detached['block_id']!r}"
        )
        assert get_block(block["id"])["total_qty"] == 0


class TestComplianceSecurityGate:
    def test_compliance_check_rejected_while_security_halted(self, api):
        """PRD §3.4: "First the account must be ACTIVE (`ERR_ACCOUNT_SUSPENDED`) and the security must be ACTIVE (`ERR_SECURITY_HALTED`); failures here abort the check as real error responses."
        PRD §3.1: "Halting a security by submitting `to_status` HALTED blocks compliance approval of its orders, routing of its blocks, and recording of its fills, surfacing `ERR_SECURITY_HALTED` at each; submitting ACTIVE resumes it."

        Design: Difficulty/cross_entity_state_dependency/compliance_check_requires_security_active
        """
        account = create_account()
        security = create_security()
        order = validate_success(
            api.create_order(
                {"account_id": account["id"], "security_id": security["id"],
                 "side": "BUY", "order_qty": 100, "order_type": "MARKET"},
                TRADER,
            ),
            201,
        )
        validate_success(api.set_security_status(security["id"], {"to_status": "HALTED"}, ADMIN))

        res = api.compliance_check_order(order["id"], COMPLIANCE)
        validate_error(res, ApiErrorId.ERR_SECURITY_HALTED)
        assert get_order(order["id"])["status"] == "PENDING_COMPLIANCE", (
            "A check aborted by a halted security must leave the order PENDING_COMPLIANCE"
        )

    def test_compliance_check_succeeds_after_security_resumed(self, api):
        """PRD §3.1: "Halting a security by submitting `to_status` HALTED blocks compliance approval of its orders, routing of its blocks, and recording of its fills, surfacing `ERR_SECURITY_HALTED` at each; submitting ACTIVE resumes it."
        PRD §3.4: "A clean order transitions `PENDING_COMPLIANCE → APPROVED` and writes `ORDER_COMPLIANCE_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/compliance_check_requires_security_active
        """
        account = create_account()
        security = create_security()
        order = validate_success(
            api.create_order(
                {"account_id": account["id"], "security_id": security["id"],
                 "side": "BUY", "order_qty": 100, "order_type": "MARKET"},
                TRADER,
            ),
            201,
        )
        validate_success(api.set_security_status(security["id"], {"to_status": "HALTED"}, ADMIN))
        validate_error(api.compliance_check_order(order["id"], COMPLIANCE), ApiErrorId.ERR_SECURITY_HALTED)

        validate_success(api.set_security_status(security["id"], {"to_status": "ACTIVE"}, ADMIN))
        checked = validate_success(api.compliance_check_order(order["id"], COMPLIANCE))
        assert checked["status"] == "APPROVED", (
            f"Identical request must succeed once the security is ACTIVE, got {checked['status']}"
        )


class TestRestrictionWindowOverlap:
    def test_touching_closed_windows_collide_at_activation(self, api):
        """PRD §3.3: "Activation — whether from `DRAFT` or later from `SUSPENDED` — is where the overlap guard lives: no other ACTIVE restriction with the same key (the combination of `account_id`, `security_id`, `rule_type`, and `side`) may hold a closed window intersecting this one's, and shared endpoints do intersect — two windows that merely touch at a boundary instant collide."
        PRD §3.3: "A violating activation is rejected with `ERR_RESTRICTION_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/restriction_closed_window_overlap
        """
        security = create_security()
        create_active_restriction(
            security_id=security["id"], rule_type="PROHIBITED", side="BUY",
            effective_from="2026-08-01T00:00:00Z", effective_to="2026-08-31T23:59:59Z",
        )
        touching = create_restriction(
            security_id=security["id"], rule_type="PROHIBITED", side="BUY",
            effective_from="2026-08-31T23:59:59Z", effective_to="2026-09-30T23:59:59Z",
        )

        res = api.activate_restriction(touching["id"], COMPLIANCE)
        validate_error(res, ApiErrorId.ERR_RESTRICTION_WINDOW_OVERLAP)
        stayed = validate_success(api.get_restriction(touching["id"], COMPLIANCE))
        assert stayed["status"] == "DRAFT", (
            f"Rejected activation must leave the restriction DRAFT, got {stayed['status']}"
        )

    def test_one_second_gap_is_disjoint_and_activates(self, api):
        """PRD §3.3: "Activation — whether from `DRAFT` or later from `SUSPENDED` — is where the overlap guard lives: no other ACTIVE restriction with the same key (the combination of `account_id`, `security_id`, `rule_type`, and `side`) may hold a closed window intersecting this one's, and shared endpoints do intersect — two windows that merely touch at a boundary instant collide."

        Design: Difficulty/resource_temporal_overlap/restriction_closed_window_overlap
        """
        security = create_security()
        create_active_restriction(
            security_id=security["id"], rule_type="PROHIBITED", side="BUY",
            effective_from="2026-08-01T00:00:00Z", effective_to="2026-08-31T23:59:59Z",
        )
        disjoint = create_restriction(
            security_id=security["id"], rule_type="PROHIBITED", side="BUY",
            effective_from="2026-09-01T00:00:00Z", effective_to="2026-09-30T23:59:59Z",
        )

        activated = activate_restriction(disjoint["id"])
        assert activated["status"] == "ACTIVE", (
            f"A window starting one second after the other's end is disjoint, got {activated['status']}"
        )


def test_retired_restriction_cannot_be_activated(api):
    """PRD §3.3: "An ACTIVE rule can be suspended to `SUSPENDED` and re-activated (the same overlap guard reruns), and a rule in any of `DRAFT`, `ACTIVE`, or `SUSPENDED` can be retired to the terminal `RETIRED`."
    PRD §2.8: "State-machine legality — the target resource is in a valid from-state for the action. Generic mismatches surface as `ERR_INVALID_STATE` (HTTP 409) — examples include approving a DRAFT plan, settling a PENDING instruction, cancelling an ALLOCATED order, or setting an account to the status it already has."

    Design: Corner/state_machines/restriction_retire_terminal_lockdown
    """
    security = create_security()
    restriction = create_restriction(security_id=security["id"], rule_type="PROHIBITED", side="BUY")
    retired = validate_success(api.retire_restriction(restriction["id"], COMPLIANCE))
    assert retired["status"] == "RETIRED"

    res = api.activate_restriction(restriction["id"], COMPLIANCE)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_position_limit_breach_and_equality_boundary(api):
    """PRD §3.4: "A position-limit breach is measured by projection — the account's current `net_qty` for the security (an absent position row counts as zero) plus the signed order quantity, positive for BUY and negative for SELL, must not exceed the rule's `threshold_units`; exceeding it is the breach."
    PRD §3.4: "If an applicable ACTIVE PROHIBITED rule matches the order, or the order would breach an applicable ACTIVE MAX_POSITION_UNITS rule, the order transitions to `COMPLIANCE_REJECTED`, the failing rule's error id — `ERR_TRADE_PROHIBITED` or `ERR_POSITION_LIMIT_BREACH`, in that precedence — is recorded as the order's `compliance_note`, and an `ORDER_COMPLIANCE_REJECTED` event is written."

    Design: Corner/validations/position_limit_breach_and_equality_boundary
    """
    scenario = setup_posted_plan(order_qtys=(100,), fills=((100, 1000),))
    account = scenario["accounts"][0]
    security = scenario["security"]
    # Posted trade leaves net position +100 for (account, security).

    create_active_restriction(
        account_id=account["id"], security_id=security["id"],
        rule_type="MAX_POSITION_UNITS", side="BUY", threshold_units=150,
    )

    breaching = validate_success(
        api.create_order(
            {"account_id": account["id"], "security_id": security["id"],
             "side": "BUY", "order_qty": 100, "order_type": "MARKET"},
            TRADER,
        ),
        201,
    )
    rejected = validate_success(api.compliance_check_order(breaching["id"], COMPLIANCE))
    assert rejected["status"] == "COMPLIANCE_REJECTED"
    assert rejected["compliance_note"] == "ERR_POSITION_LIMIT_BREACH", (
        f"Projected 100 + 100 = 200 > 150 must breach, got note {rejected['compliance_note']!r}"
    )

    at_limit = validate_success(
        api.create_order(
            {"account_id": account["id"], "security_id": security["id"],
             "side": "BUY", "order_qty": 50, "order_type": "MARKET"},
            TRADER,
        ),
        201,
    )
    approved = validate_success(api.compliance_check_order(at_limit["id"], COMPLIANCE))
    assert approved["status"] == "APPROVED", (
        "Projected 100 + 50 = 150 == threshold must be approved; breach requires exceeding it"
    )


def test_trader_cannot_activate_restriction(api, trader_headers):
    """PRD §2.1: "A recognized role that is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "| POST | `/trading/restrictions/{restrictionId}/activate` | Activate a DRAFT or SUSPENDED restriction; same-key closed-window overlap rejected | ComplianceOfficer |"

    Design: Corner/rbac/trader_cannot_activate_restriction
    """
    security = create_security()
    restriction = create_restriction(security_id=security["id"], rule_type="PROHIBITED", side="BUY")

    res = api.activate_restriction(restriction["id"], trader_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    stayed = validate_success(api.get_restriction(restriction["id"], COMPLIANCE))
    assert stayed["status"] == "DRAFT", (
        f"Forbidden activation must leave the restriction DRAFT, got {stayed['status']}"
    )
