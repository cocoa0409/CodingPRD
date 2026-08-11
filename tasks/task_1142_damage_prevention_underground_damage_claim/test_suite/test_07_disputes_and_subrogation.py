"""Dispute negotiation cycle, polymorphic targets, and subrogation (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_dispute,
    assert_subrogation_case,
    create_excavator,
    get_invoice,
    get_success_data,
    make_adjuster_headers,
    make_excavator_headers,
    make_manager_headers,
    open_invoice_dispute,
    record_payment,
    setup_disputed_invoice,
    setup_finalized_case,
    setup_issued_invoice_case,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = make_manager_headers("mgr-1")
ADJUSTER = make_adjuster_headers("adj-1")


def _get_dispute(api, dispute_id):
    return get_success_data(api.get_dispute(dispute_id, MANAGER))


def _get_subrogation_for_dispute(api, dispute_id):
    resp = api.list_subrogation_cases(MANAGER, params={"dispute_id": dispute_id})
    data, _meta = validate_paginated(resp)
    matches = [s for s in data if s.get("dispute_id") in (None, dispute_id)]
    assert len(matches) == 1, f"expected exactly 1 subrogation case, got {len(matches)}"
    return matches[0]


class TestDisputeRequiresIssuedInvoice:
    def test_dispute_on_draft_invoice_rejected(self, api):
        """PRD §3.8: "When the target is a `ClaimInvoice`, its `status` must be `ISSUED`
        or `PARTIALLY_PAID` (otherwise `ERR_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/dispute_requires_issued_invoice
        """
        ctx = setup_finalized_case(dig_site_address="70 Valley Rd",
                                   occurred_at="2026-05-11T09:00:00Z")
        invoice = ctx["invoices"][0]
        assert invoice["status"] == "DRAFT"
        resp = api.create_dispute(
            {"target_type": "CLAIM_INVOICE", "target_id": invoice["id"], "reason": "AMOUNT"},
            make_excavator_headers(ctx["excavator"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_dispute_after_issue_opens_and_marks_invoice_disputed(self, api):
        """PRD §3.8: "The new dispute starts in `OPEN`" and "When the target is a claim
        invoice, opening the dispute moves the invoice's `status` to `DISPUTED`."

        Design: Difficulty/cross_entity_state_dependency/dispute_requires_issued_invoice
        """
        ctx = setup_issued_invoice_case(dig_site_address="70 Valley Rd",
                                        occurred_at="2026-05-11T09:00:00Z")
        invoice = ctx["invoice"]
        resp = api.create_dispute(
            {"target_type": "CLAIM_INVOICE", "target_id": invoice["id"], "reason": "AMOUNT"},
            make_excavator_headers(ctx["excavator"]["id"]),
        )
        dispute = validate_success(resp, expected_status=201)
        assert_dispute(dispute)
        assert dispute["status"] == "OPEN"
        assert get_invoice(invoice["id"])["status"] == "DISPUTED"


class TestDisputeGuards:
    def test_duplicate_open_dispute_per_target_rejected(self, api):
        """PRD §3.8: "A target that already has a dispute in `OPEN`, `UNDER_REVIEW`, or
        `COUNTERED` rejects the new dispute with `ERR_DISPUTE_ALREADY_OPEN` (HTTP 409)."

        Design: Corner/validations/duplicate_open_dispute_per_target_rejected
        """
        ctx = setup_disputed_invoice(dig_site_address="28 Nu St", severity="MINOR")
        resp = api.create_dispute(
            {
                "target_type": "CLAIM_INVOICE", "target_id": ctx["invoice"]["id"],
                "reason": "EVIDENCE",
            },
            make_excavator_headers(ctx["excavator"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_ALREADY_OPEN, expected_status=409)

    def test_dispute_target_type_mismatch_rejected(self, api):
        """PRD §3.8: "The `target_id` must resolve to an entity matching `target_type` —
        a mismatch is rejected with `ERR_DISPUTE_TARGET_MISMATCH` (HTTP 422)."

        Design: Corner/errors/dispute_target_type_mismatch_rejected
        """
        ctx = setup_issued_invoice_case(dig_site_address="34 Tau St", severity="MINOR")
        resp = api.create_dispute(
            {
                "target_type": "FAULT_ALLOCATION", "target_id": ctx["invoice"]["id"],
                "reason": "FAULT_SHARE",
            },
            make_excavator_headers(ctx["excavator"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_TARGET_MISMATCH, expected_status=422)


class TestDisputeNegotiationCycle:
    def test_dispute_counter_cycle_increments_rounds(self, api):
        """PRD §3.8: "A `ClaimsAdjuster` responds to a dispute in `OPEN` or `COUNTERED`,
        optionally attaching a `response_note`, moving the dispute to `UNDER_REVIEW`,
        incrementing `rounds` by 1, and bumping `version`." and "The filer may accept
        the resolution from either `UNDER_REVIEW` or `COUNTERED`, moving the dispute to
        `RESOLVED`; the target invoice then leaves `DISPUTED` and its status is
        recomputed from `amount_paid_cents` per §3.6."

        Design: Corner/state_machines/dispute_counter_cycle_increments_rounds
        """
        ctx = setup_disputed_invoice(dig_site_address="9 Ninth St", reason="AMOUNT",
                                     detail="too high")
        excavator = ctx["excavator"]
        invoice = ctx["invoice"]
        dispute = ctx["dispute"]
        assert dispute["status"] == "OPEN"
        assert dispute["rounds"] == 0

        s1 = validate_success(api.respond_dispute(dispute["id"],
                                                  {"response_note": "reviewed"}, ADJUSTER))
        assert s1["status"] == "UNDER_REVIEW" and s1["rounds"] == 1

        s2 = validate_success(api.counter_dispute(
            dispute["id"], {"counter_note": "still too high"},
            make_excavator_headers(excavator["id"]),
        ))
        assert s2["status"] == "COUNTERED"

        s3 = validate_success(api.respond_dispute(dispute["id"],
                                                  {"response_note": "final offer"}, ADJUSTER))
        assert s3["status"] == "UNDER_REVIEW" and s3["rounds"] == 2

        s4 = validate_success(api.accept_resolution(
            dispute["id"], make_excavator_headers(excavator["id"]),
        ))
        assert s4["status"] == "RESOLVED"
        invoice_after = get_invoice(invoice["id"])
        assert invoice_after["status"] == "ISSUED", (
            "with amount_paid_cents == 0 the invoice recomputes to ISSUED"
        )

    def test_non_filer_cannot_counter_dispute_returns_ownership(self, api):
        """PRD §3.8: "The filer (an `Excavator` or `Locator` whose `X-User-ID` equals the
        dispute's `filed_by_id`) may counter a dispute in `UNDER_REVIEW`, optionally
        attaching a `counter_note`, moving it back to `COUNTERED` — a caller who is not
        the filer is rejected with `ERR_OWNERSHIP_MISMATCH`."

        Design: Corner/rbac/non_filer_cannot_counter_dispute_returns_ownership
        """
        ctx = setup_disputed_invoice(dig_site_address="45 Waw St", severity="MINOR")
        other = create_excavator(company_name="OtherCo", contact_email="o@x.com")
        dispute = ctx["dispute"]
        validate_success(api.respond_dispute(dispute["id"],
                                             {"response_note": "reviewed"}, ADJUSTER))
        resp = api.counter_dispute(
            dispute["id"], {"counter_note": "not mine"},
            make_excavator_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH, expected_status=403)
        assert _get_dispute(api, dispute["id"])["status"] == "UNDER_REVIEW"


class TestSubrogation:
    def test_escalate_creates_subrogation_case(self, api):
        """PRD §3.8: "Escalation creates a `SubrogationCase` in `DEMANDED` whose
        `dispute_id` is the escalated dispute, whose `claim_invoice_id` is set when the
        dispute's target was an invoice, whose `target_party_type` and `target_party_id`
        are the invoice's debtor, and whose `demand_amount_cents` is the invoice's
        `amount_due_cents` snapshot at escalation."

        Design: Corner/state_machines/escalate_creates_subrogation_case
        """
        ctx = setup_disputed_invoice(dig_site_address="11 Eleventh St", reason="FAULT_SHARE")
        dispute = ctx["dispute"]
        invoice = ctx["invoice"]
        resp = api.escalate_dispute(dispute["id"], ADJUSTER)
        escalated = validate_success(resp)
        assert escalated["status"] == "ESCALATED"
        sub = _get_subrogation_for_dispute(api, dispute["id"])
        assert_subrogation_case(sub)
        assert sub["status"] == "DEMANDED"
        assert sub["demand_amount_cents"] == 120000
        assert sub["claim_invoice_id"] == invoice["id"]
        assert sub["target_party_type"] == "EXCAVATOR"
        assert sub["target_party_id"] == ctx["excavator"]["id"]

    def test_subrogation_settlement_waterfall_split(self, api):
        """PRD §3.8: "The waterfall splits the recovery deterministically: legal costs
        come off the top; then, when the case's `claim_invoice_id` is set, an amount up
        to the invoice's `amount_due_cents` is applied to the invoice (increasing
        `amount_paid_cents` and recomputing the invoice's status); any remainder after
        legal costs and the invoice application becomes `owner_share_cents`, the utility
        general fund's share. The three components — applied amount, `legal_cost_cents`,
        and `owner_share_cents` — sum exactly to `recovered_cents`."

        Design: Corner/calculations/subrogation_settlement_waterfall_split
        """
        ctx = setup_issued_invoice_case(dig_site_address="21 Zeta St")
        excavator = ctx["excavator"]
        invoice = ctx["invoice"]
        record_payment("EXCAVATOR", excavator["id"], 70000, claim_invoice_id=invoice["id"])
        dispute = open_invoice_dispute(invoice["id"], "EXCAVATOR", excavator["id"],
                                       reason="FAULT_SHARE")
        validate_success(api.escalate_dispute(dispute["id"], MANAGER))
        sub = _get_subrogation_for_dispute(api, dispute["id"])
        assert sub["demand_amount_cents"] == 50000

        resp = api.record_settlement(
            sub["id"], {"recovered_cents": 100000, "legal_cost_cents": 20000}, MANAGER,
        )
        settled = validate_success(resp)
        assert settled["status"] == "SETTLED"
        assert settled["recovered_cents"] == 100000
        assert settled["owner_share_cents"] == 30000, (
            f"100000 - 20000 legal - 50000 applied = 30000, got {settled['owner_share_cents']}"
        )
        invoice_after = get_invoice(invoice["id"])
        assert invoice_after["amount_paid_cents"] == 120000
        assert invoice_after["status"] == "PAID"
        applied = invoice_after["amount_paid_cents"] - 70000
        assert applied + settled["legal_cost_cents"] + settled["owner_share_cents"] == 100000
