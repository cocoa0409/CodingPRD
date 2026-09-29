"""Non-linear lease, docket and leg lifecycles.

These tests exercise the cycles the wet lease model declares: a lease that revisits
ACTIVE after an insurance-driven suspension, a docket that revisits UNDER_REVIEW after
a denial, and a flight leg whose financial dimension advances three times while its
operational dimension stays pinned at COMPLETED.
"""

from test_helpers import (
    TEST_USERS,
    close_month,
    complete_leg,
    determination_payload,
    dispatch_leg,
    file_reliability_report,
    first_open_period,
    issue_insurance_certificate,
    make_billing_admin_headers,
    prepare_invoice,
    revoke_insurance_certificate,
    schedule_leg,
    setup_active_lease,
    setup_filed_lease,
    submit_for_approval_payload,
    validate_paginated,
    validate_success,
    void_invoice,
)

OPS = TEST_USERS["lessor_ops_headers"]
AUTHORITY = TEST_USERS["regulatory_authority_headers"]
BILLING = TEST_USERS["billing_admin_headers"]

# The settlement desk's second-pair-of-eyes rule is enforced on the opaque identifier,
# so the preparer and the approver act under two distinct BillingAdmin identities.
PREPARER = make_billing_admin_headers("billing-clerk-01")
APPROVER = make_billing_admin_headers("billing-supervisor-02")


# --------------------------------------------------------------------------- #
# ACTIVE -> SUSPENDED -> ACTIVE, driven from the certificate endpoints          #
# --------------------------------------------------------------------------- #


class TestLeaseInsuranceSuspensionCycle:
    def test_revoking_the_only_active_certificate_suspends_the_lease_and_cancels_its_leg(
        self, api
    ):
        """PRD §3.3: The underwriter pulls cover by supplying a `revocation_reason` on an `ACTIVE` certificate, which moves it to `REVOKED` and records the reason.

        PRD §3.3: If no `ACTIVE` certificate remains on the lease afterwards, the four-level lapse cascade of §2.7 runs in full: the lease drops from `ACTIVE` to `SUSPENDED` with `suspension_reason` `INSURANCE_LAPSED`, every leg still `SCHEDULED` or `DISPATCHED` on that lease is cancelled into `CANCELLED_LESSOR` with `cancel_reason` `INSURANCE_LAPSE`, and each cancellation recomputes that leg's crew exposure and the open month's charge.

        PRD §3.5: In every case the legs still `SCHEDULED` or `DISPATCHED` on the lease are cancelled into `CANCELLED_LESSOR` with `cancelling_party` `LESSOR` and a `cancel_reason` matched to the cause — `INSURANCE_LAPSE`, `REGULATORY` or `TECHNICAL` respectively — and each cancellation recomputes crew exposure and the open month's charge.

        Design: Difficulty/non_linear_state_machine/lease_cycles_active_suspended_active_via_insurance_replacement
        """
        scenario = setup_active_lease(api)
        leg = schedule_leg(
            api,
            scenario,
            scheduled_out="2026-09-20T06:00:00Z",
            scheduled_in="2026-09-20T09:00:00Z",
        )

        certificate = revoke_insurance_certificate(
            api, scenario["certificate"]["id"], "PREMIUM_NON_PAYMENT"
        )

        assert certificate["status"] == "REVOKED", (
            "revoking cover must move the certificate out of ACTIVE into REVOKED, got "
            f"{certificate['status']}"
        )
        assert certificate["revocation_reason"] == "PREMIUM_NON_PAYMENT", (
            "the supplied revocation_reason must be recorded on the certificate, got "
            f"{certificate['revocation_reason']!r}"
        )

        suspended = validate_success(api.get_lease(scenario["lease"]["id"], OPS))
        assert suspended["status"] == "SUSPENDED", (
            "with no ACTIVE certificate left the lease must drop from ACTIVE to "
            f"SUSPENDED, got {suspended['status']}"
        )
        assert suspended["suspension_reason"] == "INSURANCE_LAPSED", (
            "an insurance-driven suspension must stamp suspension_reason "
            f"INSURANCE_LAPSED, got {suspended['suspension_reason']!r}"
        )

        cancelled = validate_success(api.get_flight_leg(leg["id"], OPS))
        assert cancelled["status"] == "CANCELLED_LESSOR", (
            "the SCHEDULED leg must be cancelled into CANCELLED_LESSOR by the lapse "
            f"cascade, got {cancelled['status']}"
        )
        assert cancelled["cancelling_party"] == "LESSOR", (
            "the cascade cancellation is the lessor's, so cancelling_party must be "
            f"LESSOR, got {cancelled['cancelling_party']!r}"
        )
        assert cancelled["cancel_reason"] == "INSURANCE_LAPSE", (
            "the cancel_reason must be matched to the cause, INSURANCE_LAPSE, got "
            f"{cancelled['cancel_reason']!r}"
        )

    def test_conforming_replacement_certificate_returns_the_lease_to_active_without_restoring_legs(
        self, api
    ):
        """PRD §3.3: When the lease is `SUSPENDED` with `suspension_reason` `INSURANCE_LAPSED` and the new certificate has `additional_insured_lessee` true and a closed coverage interval containing the current logical instant, the lease returns from `SUSPENDED` to `ACTIVE` and `suspension_reason` is set back to null.

        PRD §3.3: Legs already cancelled by the lapse are not restored.

        PRD §2.7: Reactivating a suspended lease does not un-cancel the legs the suspension cancelled.

        PRD §3.3: A new certificate is created with `status` `ACTIVE` and `revocation_reason` null. Its `status` may later become `EXPIRED`, `REVOKED` or `SUPERSEDED`, all three terminal.

        Design: Difficulty/non_linear_state_machine/lease_cycles_active_suspended_active_via_insurance_replacement
        """
        scenario = setup_active_lease(api)
        leg = schedule_leg(
            api,
            scenario,
            scheduled_out="2026-09-20T06:00:00Z",
            scheduled_in="2026-09-20T09:00:00Z",
        )
        first_certificate = revoke_insurance_certificate(
            api, scenario["certificate"]["id"], "PREMIUM_NON_PAYMENT"
        )
        suspended = validate_success(api.get_lease(scenario["lease"]["id"], OPS))
        assert suspended["status"] == "SUSPENDED", (
            "setup must leave the lease SUSPENDED before the replacement cover is "
            f"attached, got {suspended['status']}"
        )

        replacement = issue_insurance_certificate(
            api,
            scenario["lease"]["id"],
            certificate_no="COI-88002",
            effective_from="2026-08-15T00:00:00Z",
            expires_at="2027-01-31T23:59:59Z",
        )

        reactivated = validate_success(api.get_lease(scenario["lease"]["id"], OPS))
        assert reactivated["status"] == "ACTIVE", (
            "attaching conforming replacement cover must return the lease from "
            f"SUSPENDED to ACTIVE, got {reactivated['status']}"
        )
        assert reactivated["suspension_reason"] is None, (
            "suspension_reason must be set back to null on reactivation, got "
            f"{reactivated['suspension_reason']!r}"
        )
        assert reactivated["version"] == suspended["version"] + 1, (
            "the reactivation is one mutation of the lease, so its version must "
            f"increment by 1, expected {suspended['version'] + 1}, got "
            f"{reactivated['version']}"
        )

        still_cancelled = validate_success(api.get_flight_leg(leg["id"], OPS))
        assert still_cancelled["status"] == "CANCELLED_LESSOR", (
            "the cascade is forward-looking: the leg cancelled by the lapse must stay "
            f"CANCELLED_LESSOR after reactivation, got {still_cancelled['status']}"
        )

        assert replacement["status"] == "ACTIVE", (
            f"a new certificate is created ACTIVE, got {replacement['status']}"
        )
        refetched_first = validate_success(
            api.get_insurance_certificate(first_certificate["id"], OPS)
        )
        assert refetched_first["status"] == "REVOKED", (
            "REVOKED is terminal, so the pulled certificate must not be re-derived to "
            f"SUPERSEDED by the replacement, got {refetched_first['status']}"
        )


# --------------------------------------------------------------------------- #
# UNDER_REVIEW -> DENIED -> UNDER_REVIEW on one docket row                      #
# --------------------------------------------------------------------------- #


class TestRegulatoryDocketRevisionLoop:
    def test_denied_determination_sends_the_lease_back_to_draft(self, api):
        """PRD §3.2: When the lease owns no prior docket, a `RegulatoryApproval` row is created against it with `determination` `UNDER_REVIEW`, `review_round` 1, and both `conditions` and `open_condition_codes` empty.

        PRD §3.2: A `DENIED` ruling sends the lease from `PENDING_REGULATORY_APPROVAL` back to `DRAFT` so the arrangement can be restructured and refiled, which is the revision loop that drives the docket `UNDER_REVIEW → DENIED → UNDER_REVIEW` with `review_round` climbing on each pass.

        PRD §3.2: Every determination sets `decided_at` to the current logical instant.

        Design: Difficulty/non_linear_state_machine/regulatory_docket_denied_then_refiled_increments_review_round
        """
        scenario = setup_filed_lease(api)
        first_filing = scenario["approval"]
        assert first_filing["determination"] == "UNDER_REVIEW", (
            "a first filing opens the docket UNDER_REVIEW, got "
            f"{first_filing['determination']}"
        )
        assert first_filing["review_round"] == 1, (
            f"a first filing opens at review_round 1, got {first_filing['review_round']}"
        )

        denied = validate_success(
            api.record_determination(
                first_filing["id"], determination_payload("DENIED"), AUTHORITY
            )
        )

        assert denied["determination"] == "DENIED", (
            f"the docket must record the DENIED ruling, got {denied['determination']}"
        )
        assert denied["decided_at"] is not None, (
            "every determination sets decided_at to the current logical instant"
        )

        lease = validate_success(api.get_lease(scenario["lease"]["id"], OPS))
        assert lease["status"] == "DRAFT", (
            "a DENIED ruling returns the lease from PENDING_REGULATORY_APPROVAL to "
            f"DRAFT, got {lease['status']}"
        )

    def test_refiling_a_denied_lease_reuses_the_docket_and_increments_review_round(
        self, api
    ):
        """PRD §3.2: When the lease already owns a docket whose `determination` is `DENIED`, no second row is created: that docket is refiled in place, moving `DENIED` back to `UNDER_REVIEW`, incrementing `review_round` by 1, resetting `conditions` and `open_condition_codes` to empty, clearing `decided_at`, and overwriting `authority_docket_no` with the newly supplied value.

        PRD §3.2: Filing is admissible only from `DRAFT`, requires the operational-control structure to be lawful, and requires the lessee to be `ACTIVE`; it advances the lease from `DRAFT` to `PENDING_REGULATORY_APPROVAL`.

        PRD §4: Operations that bring a new resource into existence — registering a lessee, an airframe or a crew member, drafting a lease, filing a docket, attaching a certificate, enrolling a qualification, scheduling a leg, requesting a substitution, preparing an invoice, filing a reliability report, or serving termination (which creates the return-conditions record) — return `201 Created`.

        Design: Difficulty/non_linear_state_machine/regulatory_docket_denied_then_refiled_increments_review_round
        """
        scenario = setup_filed_lease(api, determination="DENIED")
        original_docket_id = scenario["approval"]["id"]

        refiled = validate_success(
            api.submit_lease_for_approval(
                scenario["lease"]["id"],
                submit_for_approval_payload(authority_docket_no="CAA-2026-5580"),
                OPS,
            ),
            201,
        )

        assert refiled["id"] == original_docket_id, (
            "refiling a DENIED docket must reuse the same RegulatoryApproval row, "
            f"expected {original_docket_id}, got {refiled['id']}"
        )
        assert refiled["determination"] == "UNDER_REVIEW", (
            "the refiled docket must move from DENIED back to UNDER_REVIEW, got "
            f"{refiled['determination']}"
        )
        assert refiled["review_round"] == 2, (
            f"review_round must increment by 1 on each pass, expected 2, got "
            f"{refiled['review_round']}"
        )
        assert refiled["authority_docket_no"] == "CAA-2026-5580", (
            "the newly supplied authority_docket_no must overwrite the old one, got "
            f"{refiled['authority_docket_no']!r}"
        )
        assert refiled["conditions"] == [], (
            f"refiling resets conditions to empty, got {refiled['conditions']!r}"
        )
        assert refiled["open_condition_codes"] == [], (
            "refiling resets open_condition_codes to empty, got "
            f"{refiled['open_condition_codes']!r}"
        )

        dockets, meta = validate_paginated(
            api.list_regulatory_approvals(
                AUTHORITY, params={"lease_id": scenario["lease"]["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            "no second docket row may be created by the refiling, expected exactly 1 "
            f"docket on the lease, got {meta['total_count']}"
        )
        assert len(dockets) == 1 and dockets[0]["id"] == original_docket_id, (
            "the lease's only docket must be the reused row, got "
            f"{[d['id'] for d in dockets]}"
        )

        lease = validate_success(api.get_lease(scenario["lease"]["id"], OPS))
        assert lease["status"] == "PENDING_REGULATORY_APPROVAL", (
            "filing advances the lease from DRAFT to PENDING_REGULATORY_APPROVAL, got "
            f"{lease['status']}"
        )


# --------------------------------------------------------------------------- #
# Two independent state dimensions on one flight leg                           #
# --------------------------------------------------------------------------- #


def _setup_closed_month_with_one_completed_leg(api) -> dict:
    """ACTIVE lease with one 100-minute completed revenue leg and a closed 2026-09.

    The month's reliability report is filed and accepted so the invoice may be approved.
    """
    scenario = setup_active_lease(api)
    leg = schedule_leg(
        api,
        scenario,
        scheduled_out="2026-09-10T06:00:00Z",
        scheduled_in="2026-09-10T07:40:00Z",
    )
    dispatch_leg(api, leg["id"], "2026-09-10T06:00:00Z")
    scenario["leg"] = complete_leg(
        api, leg["id"], "2026-09-10T07:40:00Z", technical_delay_minutes=0
    )
    scenario["period"] = close_month(
        api, first_open_period(api, scenario["lease"]["id"])["id"]
    )
    file_reliability_report(api, scenario, period_month="2026-09")
    return scenario


def _reread_period(api, scenario: dict) -> dict:
    return validate_success(
        api.get_utilization_period(scenario["period"]["id"], BILLING)
    )


class TestFlightLegDualStateDimensions:
    def test_provisional_invoice_advances_billing_state_leaving_operational_status_completed(
        self, api
    ):
        """PRD §2.10: Advancing the operational dimension never touches the financial dimension — dispatching and completing a leg both leave `billing_state` exactly as it was — and advancing the financial dimension never touches `status`.

        PRD §3.6: Preparing a `PROVISIONAL` invoice over the leg's period moves every leg of that period from `UNBILLED` to `PROVISIONALLY_BILLED`, provided the leg's `status` is `SCHEDULED`, `DISPATCHED` or `COMPLETED`, and leaves `status` untouched.

        PRD §3.9: `amount_cents` is frozen at preparation time: the period's `provisional_charge_cents` when `variant` is `PROVISIONAL`, and its `final_charge_cents` otherwise.

        PRD §3.9: Voiding is admissible from `PREPARED`, from `APPROVED` or from `ISSUED`, always records the supplied `void_reason`, and always lands in the terminal `VOID`.

        Design: Difficulty/non_linear_state_machine/flight_leg_operational_status_and_billing_state_advance_independently
        """
        scenario = _setup_closed_month_with_one_completed_leg(api)

        provisional_invoice = prepare_invoice(
            api,
            _reread_period(api, scenario),
            due_on="2026-10-15",
            variant="PROVISIONAL",
            headers=PREPARER,
        )

        assert provisional_invoice["variant"] == "PROVISIONAL", (
            f"the requested variant must be recorded, got {provisional_invoice['variant']}"
        )
        assert provisional_invoice["amount_cents"] == 2400000, (
            "a PROVISIONAL invoice freezes the period's provisional_charge_cents, "
            f"expected 2400000, got {provisional_invoice['amount_cents']}"
        )

        billed_leg = validate_success(api.get_flight_leg(scenario["leg"]["id"], BILLING))
        assert billed_leg["status"] == "COMPLETED", (
            "advancing the financial dimension never touches status, which must stay "
            f"COMPLETED, got {billed_leg['status']}"
        )
        assert billed_leg["billing_state"] == "PROVISIONALLY_BILLED", (
            "preparing a PROVISIONAL invoice moves the leg from UNBILLED to "
            f"PROVISIONALLY_BILLED, got {billed_leg['billing_state']}"
        )

        voided = void_invoice(
            api, provisional_invoice["id"], "SWITCH_TO_FINAL_VARIANT", headers=PREPARER
        )
        assert voided["status"] == "VOID", (
            f"voiding a PREPARED invoice lands in the terminal VOID, got {voided['status']}"
        )

    def test_settlement_finalizes_billing_state_while_operational_status_stays_completed(
        self, api
    ):
        """PRD §2.10: `status` is the operational dimension: `SCHEDULED`, `DISPATCHED`, `COMPLETED`, `CANCELLED_LESSEE`, `CANCELLED_LESSOR` or `DIVERTED`. A leg is created `SCHEDULED`; `COMPLETED`, `CANCELLED_LESSEE`, `CANCELLED_LESSOR` and `DIVERTED` are terminal.

        PRD §3.9: Approval moves the invoice from `PREPARED` to `APPROVED` and writes `approved_by_user_id` with the approver's identifier.

        PRD §3.9: Issue moves the invoice from `APPROVED` to `ISSUED`, records `due_on`, adds `amount_cents` to the lessee's `outstanding_balance_usd_cents`, and — when the invoice's `variant` is `FINAL` — drives the period from `PENDING_SETTLEMENT` to `SETTLED`.

        PRD §3.9: That settlement moves every `COMPLETED` leg of the month from `UNBILLED` or `PROVISIONALLY_BILLED` to `FINALIZED`, adds the period's `credited_block_minutes` to the lease's `lifetime_credited_block_minutes`, and increments the period's `version`.

        Design: Difficulty/non_linear_state_machine/flight_leg_operational_status_and_billing_state_advance_independently
        """
        scenario = _setup_closed_month_with_one_completed_leg(api)
        provisional_invoice = prepare_invoice(
            api,
            _reread_period(api, scenario),
            due_on="2026-10-15",
            variant="PROVISIONAL",
            headers=PREPARER,
        )
        void_invoice(
            api, provisional_invoice["id"], "SWITCH_TO_FINAL_VARIANT", headers=PREPARER
        )

        final_invoice = prepare_invoice(
            api,
            _reread_period(api, scenario),
            due_on="2026-10-15",
            variant="FINAL",
            headers=PREPARER,
        )
        assert final_invoice["variant"] == "FINAL", (
            f"the requested variant must be recorded, got {final_invoice['variant']}"
        )
        assert final_invoice["amount_cents"] == 2400000, (
            "a FINAL invoice freezes the period's final_charge_cents, expected "
            f"2400000, got {final_invoice['amount_cents']}"
        )

        approved = validate_success(
            api.approve_settlement_invoice(final_invoice["id"], APPROVER)
        )
        assert approved["status"] == "APPROVED", (
            f"approval moves the invoice from PREPARED to APPROVED, got {approved['status']}"
        )
        assert approved["approved_by_user_id"] == "billing-supervisor-02", (
            "approved_by_user_id must be written with the approver's identifier, got "
            f"{approved['approved_by_user_id']!r}"
        )

        issued = validate_success(
            api.issue_settlement_invoice(final_invoice["id"], APPROVER)
        )
        assert issued["status"] == "ISSUED", (
            f"issue moves the invoice from APPROVED to ISSUED, got {issued['status']}"
        )

        settled_leg = validate_success(
            api.get_flight_leg(scenario["leg"]["id"], BILLING)
        )
        assert settled_leg["status"] == "COMPLETED", (
            "COMPLETED is terminal on the operational dimension, so settlement must "
            f"leave status at COMPLETED, got {settled_leg['status']}"
        )
        assert settled_leg["billing_state"] == "FINALIZED", (
            "settlement moves the completed leg from PROVISIONALLY_BILLED to "
            f"FINALIZED, got {settled_leg['billing_state']}"
        )

        period = _reread_period(api, scenario)
        assert period["status"] == "SETTLED", (
            "issuing a FINAL invoice drives the period from PENDING_SETTLEMENT to "
            f"SETTLED, got {period['status']}"
        )

        lease = validate_success(api.get_lease(scenario["lease"]["id"], OPS))
        assert lease["lifetime_credited_block_minutes"] == 100, (
            "settlement adds the period's credited_block_minutes to the lease's "
            f"lifetime_credited_block_minutes, expected 100, got "
            f"{lease['lifetime_credited_block_minutes']}"
        )
