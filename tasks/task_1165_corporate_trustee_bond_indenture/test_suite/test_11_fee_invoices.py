"""Trustee compensation: tiered extraordinary fee with status-dependent rate
and cap, the dispute/amend/reissue cycle, and the extraordinary-basis rule
(PRD §3.8)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    CLOCK_START, set_clock,
    create_active_indenture_with_tranche, create_annual_invoice,
    setup_defaulted_indenture, setup_active_indenture_with_cured_default,
    create_extraordinary_invoice_payload, declare_default,
    get_fee_invoice, get_indenture,
    make_trust_officer_headers, make_trust_manager_headers,
    make_issuer_headers,
)

OFFICER_1 = make_trust_officer_headers("officer-1")
MANAGER_1 = make_trust_manager_headers("manager-1")


class TestExtraordinaryFeeCalculation:
    def test_extraordinary_fee_active_rate_tier_split(self, api):
        """PRD §3.8: "The extraordinary amount uses the indenture's
        `default_hourly_rate_cents` while the indenture is `DEFAULTED` or
        `ACCELERATED` and its `extraordinary_hourly_rate_cents` otherwise;
        the first ten hours are billed at the applicable rate and rounded
        half-up to whole cents, the hours beyond ten are billed at one and a
        half times the rate and likewise rounded half-up, and the invoice
        amount is the sum of the two tier charges capped at four times the
        indenture's `annual_admin_fee_cents`."

        ACTIVE indenture at 12.5 hours: 10*45000 + round_half_up(2.5*67500)
        = 450000 + 168750 = 618750.

        Design: Difficulty/combinatorial_formula/extraordinary_fee_tiered_rate_state_switch_and_cap
        """
        active_ctx = setup_active_indenture_with_cured_default(issuer_ref="issuer-1",
                                                               name="I1")
        indenture = active_ctx["indenture"]
        assert indenture["status"] == "ACTIVE", (
            "cured default leaves the indenture ACTIVE — extraordinary rate applies")
        assert active_ctx["case"]["status"] == "CURED", (
            "basis: a case that reached CONFIRMED and was cured")

        resp = api.create_fee_invoice(
            create_extraordinary_invoice_payload(indenture["id"], 12.5,
                                                 description="default admin (active rate)"),
            OFFICER_1)
        invoice = validate_success(resp, 201)
        assert invoice["amount_cents"] == 618750, (
            f"active-rate tiered amount: expected 618750, "
            f"got {invoice['amount_cents']}")

    def test_extraordinary_fee_default_rate_and_cap(self, api):
        """PRD §3.8: "The extraordinary amount uses the indenture's
        `default_hourly_rate_cents` while the indenture is `DEFAULTED` or
        `ACCELERATED` and its `extraordinary_hourly_rate_cents` otherwise"

        DEFAULTED indenture at 12.5 hours: 10*65000 +
        round_half_up(2.5*97500) = 650000 + 243750 = 893750.
        ACTIVE indenture at 500 hours: uncapped 450000 +
        round_half_up(490*67500) = 33525000, capped at 4*2500000 = 10000000.

        Design: Difficulty/combinatorial_formula/extraordinary_fee_tiered_rate_state_switch_and_cap
        """
        active_ctx = setup_active_indenture_with_cured_default(issuer_ref="issuer-1",
                                                               name="I1")
        defaulted_ctx = setup_defaulted_indenture(issuer_ref="issuer-2", name="I2")
        defaulted = defaulted_ctx["indenture"]
        assert defaulted["status"] == "DEFAULTED", "default rate applies"

        resp = api.create_fee_invoice(
            create_extraordinary_invoice_payload(defaulted["id"], 12.5,
                                                 description="default admin (default rate)"),
            OFFICER_1)
        inv_default = validate_success(resp, 201)
        assert inv_default["amount_cents"] == 893750, (
            f"default-rate tiered amount: expected 893750, "
            f"got {inv_default['amount_cents']}")

        resp = api.create_fee_invoice(
            create_extraordinary_invoice_payload(
                active_ctx["indenture"]["id"], 500,
                description="huge engagement hits cap"),
            OFFICER_1)
        inv_capped = validate_success(resp, 201)
        assert inv_capped["amount_cents"] == 10000000, (
            f"cap binds: min(33525000, 4*2500000) = 10000000, "
            f"got {inv_capped['amount_cents']}")


class TestDisputeAmendReissueCycle:
    def _setup_defaulted_invoice(self, api):
        ctx = setup_defaulted_indenture(issuer_ref="issuer-2", name="I2")
        resp = api.create_fee_invoice(
            create_extraordinary_invoice_payload(ctx["indenture"]["id"], 12.5,
                                                 description="default administration"),
            OFFICER_1)
        invoice = validate_success(resp, 201)
        ctx["invoice"] = invoice
        return ctx

    def test_invoice_dispute_amend_reissue_cycle(self, api):
        """PRD §3.8: "The owning issuer then either pays the `ISSUED`
        invoice, moving it to the terminal `PAID`, or disputes it, moving it
        to `DISPUTED`. A `TrustOfficer` amends a `DISPUTED` invoice,
        replacing `extraordinary_hours` and/or `description` and recomputing
        `amount_cents` under the same tiered rule — and because the rate
        basis is read from the indenture's status at computation time, an
        amendment after a default event can flip the rate even for identical
        hours. The amended invoice returns to `ISSUED` through the same
        segregated issuance step."

        Design: Difficulty/non_linear_state_machine/fee_invoice_dispute_amend_reissue_cycle
        """
        ctx = self._setup_defaulted_invoice(api)
        invoice = ctx["invoice"]
        assert invoice["status"] == "DRAFT"
        assert invoice["amount_cents"] == 893750, "initial default-rate amount"

        statuses = []
        invoice = validate_success(api.issue_fee_invoice(invoice["id"], MANAGER_1))
        statuses.append(invoice["status"])
        invoice = validate_success(api.dispute_fee_invoice(
            invoice["id"], make_issuer_headers("issuer-2")))
        statuses.append(invoice["status"])
        invoice = validate_success(api.amend_fee_invoice(
            invoice["id"], {"extraordinary_hours": 8.0, "description": "revised hours"},
            OFFICER_1))
        statuses.append(invoice["status"])
        assert invoice["amount_cents"] == 520000, (
            f"amended at 8.0h default rate (tier 1 only): expected 520000, "
            f"got {invoice['amount_cents']}")
        invoice = validate_success(api.issue_fee_invoice(invoice["id"], MANAGER_1))
        statuses.append(invoice["status"])
        invoice = validate_success(api.pay_fee_invoice(
            invoice["id"], make_issuer_headers("issuer-2")))
        statuses.append(invoice["status"])

        assert statuses == ["ISSUED", "DISPUTED", "AMENDED", "ISSUED", "PAID"], (
            f"cycle observed on one invoice id: {statuses}")

    def test_invoice_amend_recomputes_amount_at_current_rate(self, api):
        """PRD §3.8: "A `TrustOfficer` amends a `DISPUTED` invoice, replacing
        `extraordinary_hours` and/or `description` and recomputing
        `amount_cents` under the same tiered rule — and because the rate
        basis is read from the indenture's status at computation time, an
        amendment after a default event can flip the rate even for identical
        hours."
        PRD §3.8: "issuance records `issued_by_user_id` and moves the invoice
        to `ISSUED`."

        Design: Difficulty/non_linear_state_machine/fee_invoice_dispute_amend_reissue_cycle
        """
        ctx = self._setup_defaulted_invoice(api)
        invoice = ctx["invoice"]
        assert invoice["drafted_by_user_id"] == "officer-1"

        issued = validate_success(api.issue_fee_invoice(invoice["id"], MANAGER_1))
        assert issued["issued_by_user_id"] == "manager-1"
        assert issued["issued_by_user_id"] != issued["drafted_by_user_id"]

        validate_success(api.dispute_fee_invoice(
            invoice["id"], make_issuer_headers("issuer-2")))
        amended = validate_success(api.amend_fee_invoice(
            invoice["id"], {"extraordinary_hours": 8.0}, OFFICER_1))
        assert amended["status"] == "AMENDED"
        assert amended["amount_cents"] == 520000, (
            "recomputed under the same tiered rule at the default rate")
        assert amended["amount_cents"] != 893750, (
            "amendment recomputes — the amount moves with the hours")

        reissued = validate_success(api.issue_fee_invoice(invoice["id"], MANAGER_1))
        assert reissued["status"] == "ISSUED"
        assert reissued["amount_cents"] == 520000, (
            "re-issuance keeps the amended amount")


class TestExtraordinaryBasis:
    def test_extraordinary_invoice_requires_default_basis(self, api):
        """PRD §3.8: "Extraordinary billing requires an extraordinary basis:
        at least one default case of the indenture must have reached
        `CONFIRMED`, `CURED`, `WAIVED`, or `ACCELERATED` with its
        `declared_at` at or before `service_period_end`, else drafting is
        rejected with `ERR_NO_EXTRAORDINARY_BASIS` (HTTP 422)."
        PRD §3.8: "The `amount_cents` of an `ANNUAL_ADMIN` invoice is simply
        the indenture's `annual_admin_fee_cents`."

        Design: Corner/validations/extraordinary_invoice_without_basis_rejected
        """
        set_clock(CLOCK_START)
        indenture, tranche = create_active_indenture_with_tranche(reset_clock=False)
        # A case that never leaves ALLEGED does not qualify as a basis.
        declare_default(indenture["id"], default_type="PAYMENT", officer_id="officer-1")

        resp = api.create_fee_invoice(
            create_extraordinary_invoice_payload(indenture["id"], 5,
                                                 description="no basis"),
            OFFICER_1)
        validate_error(resp, ApiErrorId.ERR_NO_EXTRAORDINARY_BASIS)

        annual = create_annual_invoice(indenture["id"], officer_id="officer-1")
        assert annual["amount_cents"] == 2500000
        assert annual["status"] == "DRAFT"
