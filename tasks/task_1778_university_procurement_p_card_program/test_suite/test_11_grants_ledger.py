"""Grant budget ledger: dual variants, conservation, suspension gates."""
from test_helpers import (
    ApiErrorId,
    assert_grant_ledger_conservation,
    create_approved_requisition,
    create_and_submit_requisition,
    create_department,
    create_grant,
    create_requisition_draft,
    create_vendor,
    get_success_data,
    issue_po_ok,
    make_requester_headers,
    post_invoice,
    post_receipt,
    read_ledger,
    requisition_line,
    submit_requisition_ok,
    validate_error,
    walk_approval_chain,
)
from test_helpers.fixtures import (
    ADMIN,
    AP_CLERK,
    BUYER,
    DEPT_APPROVER,
    GRANT_OFFICER,
)

ADMIN_H = ADMIN
AP_H = AP_CLERK
BUYER_H = BUYER
DEPT_H = DEPT_APPROVER
GRANT_OFFICER_H = GRANT_OFFICER


class TestProvisionalVsSettledVariants:
    def _setup_approved_grant_req(self, api):
        """Grant 10,000,000; requisition direct 900,000 (EQUIPMENT 600,000 over
        the 500,000 cap is excluded) -> charge 900,000 + 156,000 = 1,056,000."""
        dept = create_department(name="Chemistry")
        vendor = create_vendor(legal_name="LabCorp")
        grant = create_grant(
            grant_code="NSF-001", sponsor="NSF", total_award_cents=10000000,
            allowed_categories=["SUPPLIES", "EQUIPMENT"],
        )
        req = create_approved_requisition(
            department_id=dept["id"], vendor_id=vendor["id"], grant_id=grant["id"],
            lines=[
                requisition_line(
                    commodity_code="LAB", description="supplies", quantity=2,
                    unit_price_cents=150000, cost_category="SUPPLIES",
                ),
                requisition_line(
                    commodity_code="LAB", description="centrifuge", quantity=1,
                    unit_price_cents=600000, cost_category="EQUIPMENT",
                ),
            ],
        )
        assert req["charge_cents"] == 1056000
        return grant, req

    def test_grant_ledger_variants_diverge_with_open_encumbrance(self, api):
        """PRD §3.1: "Two remaining-budget variants are derived from these:
        `provisional_remaining_cents` is the total award minus both spent and
        encumbered amounts and is the variant consulted by allowability checks
        and forward planning, while `settled_remaining_cents` subtracts only
        settled spend and is the variant used for reporting actually-incurred
        cost."

        Design: Difficulty/dual_variant_calc/grant_remaining_provisional_vs_settled
        """
        grant, _ = self._setup_approved_grant_req(api)
        ledger = read_ledger(grant["id"])
        assert ledger["spent_cents"] == 0
        assert ledger["encumbered_cents"] == 1056000
        assert ledger["provisional_remaining_cents"] == 8944000
        assert ledger["settled_remaining_cents"] == 10000000, (
            "identical ledger; the settled variant ignores the encumbrance"
        )
        assert_grant_ledger_conservation(ledger, 10000000)

    def test_grant_ledger_variants_converge_after_payment(self, api):
        """PRD §3.6: "When the order is grant-funded, payment is the settlement
        event for the grant ledger: the order's `charge_cents` leaves
        `encumbered_cents` and enters `spent_cents`."
        PRD §3.1: "The ledger is conserved: spent, encumbered, and provisional
        remaining always sum back to `total_award_cents`."

        Design: Difficulty/dual_variant_calc/grant_remaining_provisional_vs_settled
        """
        grant, req = self._setup_approved_grant_req(api)
        po = issue_po_ok(req["id"])
        post_receipt(po["id"], [
            {"line_no": 0, "quantity": 2},
            {"line_no": 1, "quantity": 1},
        ])
        inv = post_invoice(po["id"], [
            {"line_no": 0, "quantity": 2, "unit_price_cents": 150000},
            {"line_no": 1, "quantity": 1, "unit_price_cents": 600000},
        ], invoice_number="INV-1")
        get_success_data(api.pay_invoice(inv["id"], AP_H))

        ledger = read_ledger(grant["id"])
        assert ledger["spent_cents"] == 1056000
        assert ledger["encumbered_cents"] == 0
        assert ledger["provisional_remaining_cents"] == 8944000
        assert ledger["settled_remaining_cents"] == 8944000, (
            "variants converge once the charge settles"
        )
        assert_grant_ledger_conservation(ledger, 10000000)


class TestEncumbranceConservation:
    def _setup_two_approved(self, api):
        dept = create_department(name="Astronomy")
        vendor = create_vendor(legal_name="OpticsCo")
        grant = create_grant(
            grant_code="G-INV", sponsor="NSF", total_award_cents=5000000,
            allowed_categories=["SUPPLIES"],
        )
        r1 = create_approved_requisition(
            department_id=dept["id"], vendor_id=vendor["id"], grant_id=grant["id"],
            lines=[requisition_line(
                commodity_code="AST", description="lenses", quantity=10,
                unit_price_cents=100000, cost_category="SUPPLIES",
            )],
        )
        r2 = create_approved_requisition(
            department_id=dept["id"], vendor_id=vendor["id"], grant_id=grant["id"],
            lines=[requisition_line(
                commodity_code="AST", description="mount", quantity=1,
                unit_price_cents=500000, cost_category="SUPPLIES",
            )],
        )
        assert r1["charge_cents"] == 1520000
        assert r2["charge_cents"] == 760000
        return grant, r1, r2

    def test_cancel_from_approved_releases_encumbrance_conserving_award(self, api):
        """PRD §3.3: "Cancelling from `APPROVED` releases the grant encumbrance by
        subtracting `charge_cents` from `encumbered_cents`."
        PRD §3.1: "The ledger is conserved: spent, encumbered, and provisional
        remaining always sum back to `total_award_cents`."

        Design: Difficulty/compensating_invariant/grant_encumbrance_conservation_invariant
        """
        grant, _, r2 = self._setup_two_approved(api)
        before = read_ledger(grant["id"])
        assert before["spent_cents"] == 0
        assert before["encumbered_cents"] == 2280000
        assert before["provisional_remaining_cents"] == 2720000
        assert_grant_ledger_conservation(before, 5000000)

        get_success_data(
            api.cancel_requisition(r2["id"], make_requester_headers("req-user-1"))
        )
        after = read_ledger(grant["id"])
        assert after["spent_cents"] == 0
        assert after["encumbered_cents"] == 1520000
        assert after["provisional_remaining_cents"] == 3480000
        assert_grant_ledger_conservation(after, 5000000)

    def test_payment_settles_encumbrance_conserving_award(self, api):
        """PRD §3.6: "payment is the settlement event for the grant ledger: the
        order's `charge_cents` leaves `encumbered_cents` and enters
        `spent_cents`."
        PRD §3.1: "The ledger is conserved: spent, encumbered, and provisional
        remaining always sum back to `total_award_cents`."

        Design: Difficulty/compensating_invariant/grant_encumbrance_conservation_invariant
        """
        grant, r1, _ = self._setup_two_approved(api)
        po = issue_po_ok(r1["id"])
        post_receipt(po["id"], [{"line_no": 0, "quantity": 10}])
        inv = post_invoice(po["id"], [
            {"line_no": 0, "quantity": 10, "unit_price_cents": 100000},
        ], invoice_number="INV-INV")
        get_success_data(api.pay_invoice(inv["id"], AP_H))

        ledger = read_ledger(grant["id"])
        assert ledger["spent_cents"] == 1520000
        assert ledger["encumbered_cents"] == 760000, (
            "R2's encumbrance persists; only R1's charge settles"
        )
        assert ledger["provisional_remaining_cents"] == 2720000
        assert ledger["settled_remaining_cents"] == 3480000
        assert_grant_ledger_conservation(ledger, 5000000)


class TestGrantSuspendGates:
    def test_grant_suspend_gates_submit_and_close_preserves_ledger(self, api):
        """PRD §3.1: "Suspending a grant blocks new grant-funded submissions and
        new grant-allocated reconciliations: both require the grant to be
        `ACTIVE`, surfacing `ERR_GRANT_NOT_ACTIVE` otherwise."
        PRD §3.1: "closing is additionally refused with
        `ERR_GRANT_HAS_OPEN_ENCUMBRANCES` while the grant's `encumbered_cents` is
        anything other than zero."

        Design: Corner/state_machines/grant_suspend_gates_submit_preserves_ledger
        """
        dept = create_department(name="Oceanography")
        vendor = create_vendor(legal_name="BoatCo")
        grant = create_grant(
            grant_code="G-SUS", sponsor="NOAA", total_award_cents=5000000,
            allowed_categories=["SUPPLIES"],
        )
        r1 = create_approved_requisition(
            department_id=dept["id"], vendor_id=vendor["id"], grant_id=grant["id"],
            lines=[requisition_line(
                commodity_code="OCE", description="buoy", quantity=1,
                unit_price_cents=1000000, cost_category="SUPPLIES",
            )],
        )
        assert r1["charge_cents"] == 1520000
        get_success_data(api.suspend_grant(grant["id"], GRANT_OFFICER_H))

        r2 = create_requisition_draft(
            department_id=dept["id"], vendor_id=vendor["id"], grant_id=grant["id"],
            lines=[requisition_line(
                commodity_code="OCE", description="rope", quantity=1,
                unit_price_cents=100000, cost_category="SUPPLIES",
            )],
        )
        blocked = api.submit_requisition(
            r2["id"], make_requester_headers("req-user-1")
        )
        validate_error(blocked, ApiErrorId.ERR_GRANT_NOT_ACTIVE, 409)

        close = api.close_grant(grant["id"], GRANT_OFFICER_H)
        validate_error(close, ApiErrorId.ERR_GRANT_HAS_OPEN_ENCUMBRANCES, 409)

        ledger = read_ledger(grant["id"])
        assert ledger["encumbered_cents"] == 1520000, (
            "the encumbrance survives both the suspension and the rejections"
        )
        assert ledger["spent_cents"] == 0


class TestImmediateConsistency:
    def test_immediate_consistency_side_effects_visible(self, api):
        """PRD §2.10: "the server performs those mutations atomically and
        immediately — there is no eventual consistency window."
        PRD §3.3: "on success the requisition becomes `APPROVED` and its
        `charge_cents` is added to the grant's `encumbered_cents`."
        PRD §3.5: "fulfillment is then recomputed: `FULLY_RECEIVED` exactly when
        every line's cumulative posted quantity equals its ordered quantity".

        Design: Corner/consistency_model/immediate_consistency_side_effects_visible
        """
        dept = create_department(name="Imm")
        vendor = create_vendor(legal_name="ImmCo")
        grant = create_grant(
            grant_code="G-IMM", sponsor="NIH", total_award_cents=5000000,
            allowed_categories=["SUPPLIES"],
        )
        req = create_and_submit_requisition(
            department_id=dept["id"], vendor_id=vendor["id"], grant_id=grant["id"],
            lines=[requisition_line(
                commodity_code="IMM", description="scope", quantity=1,
                unit_price_cents=1000000, cost_category="SUPPLIES",
            )],
        )
        get_success_data(api.approve_requisition_step(req["id"], {}, DEPT_H))
        get_success_data(api.approve_requisition_step(req["id"], {}, GRANT_OFFICER_H))
        final = get_success_data(api.approve_requisition_step(req["id"], {}, BUYER_H))
        assert final["status"] == "APPROVED", (
            "the mutation response itself carries the outcome — no polling"
        )
        ledger = read_ledger(grant["id"])
        assert ledger["encumbered_cents"] == 1520000

        po = issue_po_ok(req["id"])
        post_receipt(po["id"], [{"line_no": 0, "quantity": 1}])
        live = get_success_data(api.get_purchase_order(po["id"], ADMIN_H))
        assert live["fulfillment_status"] == "FULLY_RECEIVED"
