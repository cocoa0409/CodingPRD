"""Warranty claims: adjudication, payment, audit, chargebacks, disputes."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    accept_sale,
    assert_claim,
    create_claim,
    create_dealer,
    create_sales_target,
    decide_claim,
    get_dealer,
    get_lead,
    make_dealer_user_headers,
    report_sale,
    set_clock,
    setup_active_dealer,
    setup_claim_in_state,
    setup_routed_lead,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestClaimAuditDisputeCycle:
    """The claim machine cycles PAID -> AUDIT_FLAGGED -> CHARGED_BACK ->
    DISPUTED -> PAID, with the dealer balance posted and reversed mid-loop."""

    def _setup_flagged_claim(self, api, dealer_code="DL-E1"):
        ctx = setup_active_dealer(dealer_code)
        claim = setup_claim_in_state(
            ctx["dealer"]["id"], "C-500", "AUDIT_FLAGGED",
            parts_cost_cents=10000)
        return ctx, claim

    def test_chargeback_posts_balance_without_suspension_below_threshold(
            self, api, auditor_headers, oem_admin_headers):
        """PRD section 3.5: "A `FULL` finding sets `chargeback_amount_cents` to the entire `claim_amount_cents`; a `PARTIAL` finding claws back only the labor, setting `chargeback_amount_cents` to the `claim_amount_cents` minus the `parts_cost_cents`. Either way the claim moves to `CHARGED_BACK`, the chargeback amount is added to the dealer's `chargeback_balance_cents` — and here the cascade of §2.9 may fire: if the balance has reached or exceeded 50000 cents and the dealer is `ACTIVE`, the dealer is automatically suspended to `SUSPENDED`, and every lead currently `ROUTED` to that dealer is re-queued to `NEW` with its routing fields cleared."

        Design: Difficulty/non_linear_state_machine/warranty_claim_audit_dispute_cycle
        """
        ctx, claim = self._setup_flagged_claim(api)

        charged = validate_success(
            api.chargeback_claim(claim["id"], {"finding": "FULL"},
                                 auditor_headers), 200)
        assert_claim(charged)
        assert charged["status"] == "CHARGED_BACK"
        assert charged["chargeback_amount_cents"] == 10000, (
            "FULL finding charges back the entire claim_amount_cents"
        )

        dealer = validate_success(api.get_dealer(ctx["dealer"]["id"],
                                                 oem_admin_headers), 200)
        assert dealer["chargeback_balance_cents"] == 10000
        assert dealer["status"] == "ACTIVE", (
            "10000 is below the 50000-cent suspension threshold"
        )

    def test_dispute_upheld_reverses_chargeback(self, api, auditor_headers,
                                                oem_admin_headers):
        """PRD section 3.5: "The claim-owning `DealerUser` may dispute a `CHARGED_BACK` claim, moving it to `DISPUTED`; the caller must be the claim's dealer (`ERR_DEALER_IDENTITY_MISMATCH`), and the claim must be `CHARGED_BACK` (`ERR_CLAIM_INVALID_STATE`). The auditor resolves the dispute with an `outcome`: `UPHELD` finds for the dealer, returning the claim to `PAID`, subtracting the `chargeback_amount_cents` from the dealer's `chargeback_balance_cents`, and resetting the claim's `chargeback_amount_cents` to null; `DENIED` lets the chargeback stand, returning the claim to `CHARGED_BACK` with no balance change."

        Design: Difficulty/non_linear_state_machine/warranty_claim_audit_dispute_cycle
        """
        ctx, claim = self._setup_flagged_claim(api)
        validate_success(
            api.chargeback_claim(claim["id"], {"finding": "FULL"},
                                 auditor_headers), 200)
        dealer_id = ctx["dealer"]["id"]
        assert get_dealer(dealer_id)["chargeback_balance_cents"] == 10000

        disputed = validate_success(
            api.dispute_claim(claim["id"], make_dealer_user_headers(dealer_id)),
            200)
        assert disputed["status"] == "DISPUTED"

        resolved = validate_success(
            api.resolve_claim_dispute(claim["id"], {"outcome": "UPHELD"},
                                      auditor_headers), 200)
        assert resolved["status"] == "PAID", (
            "UPHELD returns the claim to PAID, closing the cycle"
        )
        assert resolved["chargeback_amount_cents"] is None

        dealer_after = validate_success(api.get_dealer(dealer_id,
                                                       oem_admin_headers),
                                        200)
        assert dealer_after["chargeback_balance_cents"] == 0


class TestChargebackSuspensionCascade:
    """A chargeback that pushes the balance to 50000 cents suspends the
    dealer and re-queues its routed leads."""

    def _setup_two_flagged_claims(self, api):
        ctx = setup_routed_lead("DL-H1", "T-300", coverage_type="EXCLUSIVE")
        dealer_id = ctx["dealer"]["id"]
        claim1 = setup_claim_in_state(dealer_id, "H-1", "AUDIT_FLAGGED",
                                      parts_cost_cents=30000)
        claim2 = setup_claim_in_state(dealer_id, "H-2", "AUDIT_FLAGGED",
                                      parts_cost_cents=25000)
        return ctx, claim1, claim2

    def test_balance_crossing_threshold_suspends_dealer(
            self, api, auditor_headers, oem_admin_headers):
        """PRD section 3.5: "Either way the claim moves to `CHARGED_BACK`, the chargeback amount is added to the dealer's `chargeback_balance_cents` — and here the cascade of §2.9 may fire: if the balance has reached or exceeded 50000 cents and the dealer is `ACTIVE`, the dealer is automatically suspended to `SUSPENDED`, and every lead currently `ROUTED` to that dealer is re-queued to `NEW` with its routing fields cleared."

        Design: Difficulty/transitive_cascade/chargeback_suspension_cascade
        """
        ctx, claim1, claim2 = self._setup_two_flagged_claims(api)
        dealer_id = ctx["dealer"]["id"]

        validate_success(
            api.chargeback_claim(claim1["id"], {"finding": "FULL"},
                                 auditor_headers), 200)
        dealer_mid = validate_success(api.get_dealer(dealer_id,
                                                     oem_admin_headers), 200)
        assert dealer_mid["chargeback_balance_cents"] == 30000
        assert dealer_mid["status"] == "ACTIVE", (
            "30000 is below the 50000-cent threshold; no suspension yet"
        )

        charged2 = validate_success(
            api.chargeback_claim(claim2["id"], {"finding": "FULL"},
                                 auditor_headers), 200)
        assert charged2["chargeback_amount_cents"] == 25000

        dealer_after = validate_success(api.get_dealer(dealer_id,
                                                       oem_admin_headers),
                                        200)
        assert dealer_after["chargeback_balance_cents"] == 55000
        assert dealer_after["status"] == "SUSPENDED", (
            "the balance crossing 50000 must flip the ACTIVE dealer to "
            f"SUSPENDED, got {dealer_after['status']}"
        )

    def test_suspension_requeues_routed_lead(self, api, auditor_headers,
                                             oem_admin_headers):
        """PRD section 2.9: "Third, **the chargeback suspension cascade**: a chargeback that pushes a dealer's chargeback balance to the suspension threshold flips an `ACTIVE` dealer to `SUSPENDED`, which in turn re-queues its routed leads."
        PRD section 2.9: "First, **lead re-queuing**: whenever a territory assignment leaves `ACTIVE`, or a dealer is suspended or terminated, every lead currently `ROUTED` through the affected assignment or dealer returns to `NEW`, and its routing fields (`routed_dealer_id`, `routed_assignment_id`, `routed_at`) are cleared."

        Design: Difficulty/transitive_cascade/chargeback_suspension_cascade
        """
        ctx, claim1, claim2 = self._setup_two_flagged_claims(api)
        lead_id = ctx["lead"]["id"]
        assert get_lead(lead_id)["status"] == "ROUTED"

        api.chargeback_claim(claim1["id"], {"finding": "FULL"},
                             auditor_headers)
        assert get_lead(lead_id)["status"] == "ROUTED", (
            "below the threshold the lead stays routed"
        )

        validate_success(
            api.chargeback_claim(claim2["id"], {"finding": "FULL"},
                                 auditor_headers), 200)
        lead_after = validate_success(api.get_lead(lead_id,
                                                   oem_admin_headers), 200)
        assert lead_after["status"] == "NEW"
        assert lead_after["routed_dealer_id"] is None
        assert lead_after["routed_assignment_id"] is None
        assert lead_after["routed_at"] is None


class TestClaimStateAndWindowRules:

    def test_claim_pay_from_rejected_terminal_lockdown(
            self, api, auditor_headers, oem_admin_headers):
        """PRD section 3.5: "An `OemAuditor` adjudicates with a `decision`: `APPROVE` moves the claim to `APPROVED`, `REJECT` moves it to the terminal `REJECTED` state, and either `decision` requires the claim to currently be `SUBMITTED` (`ERR_CLAIM_INVALID_STATE`); the payload may carry an optional `reason`."
        PRD section 2.8: "6. **State and concurrency.** The target resource must be in a valid from-state for the requested transition, and — for agreement activation — the OCC check of §2.7 must pass (`ERR_STALE_VERSION` and the state errors: `ERR_DEALER_NOT_ACTIVE`, `ERR_DEALER_NOT_SUSPENDED`, `ERR_AGREEMENT_NOT_IN_DRAFT`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_ASSIGNMENT_NOT_ACTIVE`, `ERR_TARGET_NOT_OPEN`, `ERR_SALE_NOT_REPORTED`, `ERR_SALE_NOT_ACCEPTED`, `ERR_ADVANCE_NOT_OPEN`, `ERR_CLAIM_INVALID_STATE`, `ERR_RETURN_INVALID_STATE`, `ERR_CERT_INVALID_STATE`, `ERR_LEAD_INVALID_STATE`)."

        Design: Corner/state_machines/claim_pay_from_rejected_terminal_lockdown
        """
        ctx = setup_active_dealer("DL-SM1")
        claim = create_claim(ctx["dealer"]["id"], "SM-1",
                             parts_cost_cents=3000)
        rejected = decide_claim(claim["id"], "REJECT")
        assert rejected["status"] == "REJECTED"

        resp = api.pay_claim(claim["id"], auditor_headers)
        validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_STATE)

        unchanged = validate_success(api.get_claim(claim["id"],
                                                   oem_admin_headers), 200)
        assert unchanged["status"] == "REJECTED"
        assert unchanged["paid_amount_cents"] is None

    def test_audit_window_closed_after_365_days(self, api, auditor_headers,
                                                oem_admin_headers):
        """PRD section 3.5: "An auditor may flag a `PAID` claim for audit, moving it to `AUDIT_FLAGGED`, only while the current logical datetime is no later than 365 days after `paid_at`; once that window has closed the flagging is rejected with `ERR_AUDIT_WINDOW_CLOSED`, and flagging a claim in any other state fails with `ERR_CLAIM_INVALID_STATE`."

        Design: Corner/validations/audit_window_closed_after_365_days
        """
        ctx = setup_active_dealer("DL-AW1")
        # Paid at the startup clock of 2026-08-01T00:00:00Z.
        claim = setup_claim_in_state(ctx["dealer"]["id"], "AW-1", "PAID",
                                     parts_cost_cents=10000)
        # paid_at + 365 days is 2027-08-01T00:00:00Z; one day later the
        # window is closed.
        set_clock("2027-08-02T00:00:00Z")

        resp = api.flag_claim_audit(claim["id"], auditor_headers)
        validate_error(resp, ApiErrorId.ERR_AUDIT_WINDOW_CLOSED)

        unchanged = validate_success(api.get_claim(claim["id"],
                                                   oem_admin_headers), 200)
        assert unchanged["status"] == "PAID"


class TestClaimAmountLaborRate:

    def test_warranty_claim_amount_uses_gold_tier_labor_rate(
            self, api, sales_ops_headers, oem_admin_headers):
        """PRD section 3.5: "The claim's value is computed at submission and stored in `claim_amount_cents`: the parts cost plus the labor charge, where the labor charge is the `labor_hours` multiplied by the dealer's tier labor rate **as it stands at submission time** — 12000 cents per hour for a `GOLD` dealer, 10000 for `SILVER`, 8500 for `BRONZE` — with the labor charge rounded half-up to a whole cent."
        PRD section 3.3: "Finally, the dealer's `tier` is recomputed from the final ratio — `GOLD`, `SILVER`, or `BRONZE` by the same thresholds — and `Dealer.version` increments."

        Design: Corner/calculations/warranty_claim_amount_uses_gold_tier_labor_rate
        """
        ctx = setup_active_dealer("DL-CC1")
        dealer_id = ctx["dealer"]["id"]
        target = create_sales_target(dealer_id, target_units=5)
        # Six accepted sales against a 5-unit target -> ratio 1.2 -> GOLD.
        for i in range(6):
            sale = report_sale(dealer_id, f"CC-{i + 1}", f"2026-08-0{i + 1}",
                               list_price_cents=1000)
            accept_sale(sale["id"])
        set_clock("2026-10-01T00:00:00Z")
        validate_success(api.close_sales_target(target["id"],
                                                sales_ops_headers),
                         200)

        dealer = validate_success(api.get_dealer(dealer_id,
                                                 oem_admin_headers), 200)
        assert dealer["tier"] == "GOLD", (
            "ratio 6/5 = 1.2 meets the GOLD threshold, got "
            f"{dealer['tier']}"
        )

        claim = validate_success(
            api.create_claim(
                {
                    "dealer_id": dealer_id,
                    "unit_serial": "CC-X",
                    "parts_cost_cents": 5000,
                    "labor_hours": 2.0,
                    "failure_description": "pump",
                },
                make_dealer_user_headers(dealer_id),
            ),
            expected_status=201,
        )
        assert claim["claim_amount_cents"] == 29000, (
            "5000 parts + 2.0 h * 12000 GOLD rate = 29000, got "
            f"{claim['claim_amount_cents']}"
        )


class TestClaimAccessAndListing:

    def test_sales_ops_cannot_chargeback_claim(self, api, sales_ops_headers,
                                               oem_admin_headers):
        """PRD section 2.1: "Beyond header presence, each operation is restricted to specific roles; a caller whose role is not permitted for the endpoint receives `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD section 4: "| POST | `/network/warranty-claims/{claimId}/chargeback` | Charge back a flagged claim (`finding` `FULL` or `PARTIAL`) | OemAuditor |"

        Design: Corner/rbac/sales_ops_cannot_chargeback_claim
        """
        ctx = setup_active_dealer("DL-RD2")
        claim = setup_claim_in_state(ctx["dealer"]["id"], "RD-2",
                                     "AUDIT_FLAGGED", parts_cost_cents=1000)

        resp = api.chargeback_claim(claim["id"], {"finding": "FULL"},
                                    sales_ops_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        unchanged = validate_success(api.get_claim(claim["id"],
                                                   oem_admin_headers), 200)
        assert unchanged["status"] == "AUDIT_FLAGGED"

    def test_priority_existence_beats_state_on_unknown_claim(
            self, api, auditor_headers):
        """PRD section 2.8: "When several things are wrong with a single request, the server does not choose an error arbitrarily; validations run in a fixed priority order, and the first failing check determines the rejection."
        PRD section 2.8: "4. **Existence.** Every referenced resource must exist, checked left-to-right: path identifiers first, then identifiers referenced in the request body. The corresponding not-found error is raised for the first missing identifier (`ERR_DEALER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_TARGET_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, `ERR_ADVANCE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_LEAD_NOT_FOUND`)."

        Design: Corner/validations/priority_existence_beats_state_on_unknown_claim
        """
        resp = api.decide_claim(NON_EXISTENT_UUID, {"decision": "APPROVE"},
                                auditor_headers)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND)
        assert resp.status_code == 404

    def test_filtered_list_returns_only_matching_dealer_claims(
            self, api, oem_admin_headers):
        """PRD section 4: "| GET | `/network/warranty-claims` | List claims; optional filters `dealer_id`, `status` | Any |"
        PRD section 3.5: "Warranty reimbursement begins at the dealership. A `DealerUser` submits a **WarrantyClaim** for their own dealership, supplying the `dealer_id` (identity-checked), the `unit_serial` the claim pertains to, a `parts_cost_cents` that may be zero but not negative, `labor_hours` that likewise may be zero but not negative, and a free-text `failure_description`."

        Design: Corner/endpoints/filtered_list_returns_only_matching_dealer_claims
        """
        ctx = setup_active_dealer("DL-FL1")
        dealer_id = ctx["dealer"]["id"]
        create_claim(dealer_id, "FL-1", parts_cost_cents=1000,
                     failure_description="f1")
        create_claim(dealer_id, "FL-2", parts_cost_cents=2000,
                     failure_description="f2")
        other = create_dealer("DL-FL2", name="Dealer FL2", region="East")

        data, meta = validate_paginated(
            api.list_claims(oem_admin_headers,
                            params={"dealer_id": dealer_id}))
        assert meta["total_count"] == 2
        assert len(data) == 2
        assert all(item["dealer_id"] == dealer_id for item in data)

        data2, meta2 = validate_paginated(
            api.list_claims(oem_admin_headers,
                            params={"dealer_id": other["id"]}))
        assert meta2["total_count"] == 0
        assert data2 == []
