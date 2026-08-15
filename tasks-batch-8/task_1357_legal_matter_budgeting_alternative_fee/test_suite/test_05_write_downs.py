"""Write-down requests: guards, authority ladder, application effects."""
from test_helpers import (
    ADMIN,
    ANALYST,
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_approved_entry,
    add_billed_entry,
    api_client,
    apply_write_down,
    create_write_down,
    create_write_down_request_payload,
    decide_write_down,
    get_matter,
    make_billing_partner_headers,
    setup_active_matter,
    setup_firm,
    submit_write_down,
    validate_error,
    validate_success,
)


class TestWriteDownApplication:

    def test_write_down_apply_marks_all_entries_written_down(self):
        """PRD section 3.6: "Every listed entry then transitions to
        `WRITTEN_DOWN`, and the request itself moves `APPROVED` → `APPLIED`,
        which is terminal. The matter's books absorb the concession in the
        same operation: `actual_fees_cents` is reduced by each entry's
        allocated share, `write_down_total_cents` grows by the allocated
        shares, and `variance_cents`, `variance_pct_bp`,
        `variance_alert_level`, and `realization_rate_bp` are all
        recomputed."

        Design: Difficulty/combinatorial_formula/write_down_allocation_rounding_waterfall
        """
        ctx = setup_active_matter(
            with_second_partner=True,
            phases=[{"task_code": "L110", "budget": 200000}])
        entries = [
            add_approved_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                               ctx["partner"]["id"], amount,
                               ctx["partner"]["id"],
                               entry_date=f"2026-08-0{5 + i}")
            for i, amount in enumerate((33334, 33333, 33333))
        ]

        wdr = create_write_down(ctx["firm"]["id"], ctx["matter"]["id"],
                                [e["id"] for e in entries], 50000,
                                ctx["partner"]["id"])
        submit_write_down(ctx["firm"]["id"], wdr["id"],
                          ctx["partner"]["id"])
        decide_write_down(ctx["firm"]["id"], wdr["id"], "APPROVE",
                          ctx["partner2"]["id"])
        applied = apply_write_down(ctx["firm"]["id"], wdr["id"],
                                   ctx["partner2"]["id"])
        assert applied["status"] == "APPLIED"

        for entry in entries:
            fetched = validate_success(
                api_client.get_time_entry(entry["id"], ADMIN), 200)
            assert fetched["status"] == "WRITTEN_DOWN", (
                f"listed entry must be WRITTEN_DOWN, got "
                f"{fetched['status']}")

        matter = get_matter(ctx["matter"]["id"])
        assert matter["write_down_total_cents"] == 50000, (
            f"write-down total must be 50000, got "
            f"{matter['write_down_total_cents']}")
        assert matter["actual_fees_cents"] == 50000, (
            f"actual must be 100000 - 50000 = 50000, got "
            f"{matter['actual_fees_cents']}")

    def test_write_down_conserves_total_value(self):
        """PRD section 3.6: "The matter's books absorb the concession in the
        same operation: `actual_fees_cents` is reduced by each entry's
        allocated share, `write_down_total_cents` grows by the allocated
        shares, and `variance_cents`, `variance_pct_bp`,
        `variance_alert_level`, and `realization_rate_bp` are all
        recomputed."
        PRD section 3.5: "Its `actual_fees_cents` is the sum of
        `billable_amount_cents` over entries in `APPROVED`, `BILLED`, or
        `WRITTEN_DOWN`, with one caveat: a `WRITTEN_DOWN` entry contributes
        its post-write-down remainder — its original amount minus its
        allocated write-down share — rather than its original amount."

        Design: Difficulty/compensating_invariant/write_down_apply_invariant_conserves_total_value
        """
        ctx = setup_active_matter(
            with_second_partner=True,
            phases=[{"task_code": "L110", "budget": 100000}])
        entry = add_billed_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                                 ctx["partner"]["id"], 80000,
                                 ctx["partner"]["id"])

        wdr = create_write_down(ctx["firm"]["id"], ctx["matter"]["id"],
                                [entry["id"]], 30000, ctx["partner"]["id"])
        submit_write_down(ctx["firm"]["id"], wdr["id"],
                          ctx["partner"]["id"])
        decide_write_down(ctx["firm"]["id"], wdr["id"], "APPROVE",
                          ctx["partner2"]["id"])
        apply_write_down(ctx["firm"]["id"], wdr["id"],
                         ctx["partner2"]["id"])

        matter = get_matter(ctx["matter"]["id"])
        assert matter["actual_fees_cents"] == 50000, (
            f"actual must be 80000 - 30000 = 50000, got "
            f"{matter['actual_fees_cents']}")
        assert matter["write_down_total_cents"] == 30000
        assert (matter["actual_fees_cents"]
                + matter["write_down_total_cents"]) == 80000, (
            "no value may be created or destroyed: post-write-down actual "
            "plus write-down total must equal the pre-write-down 80000")


class TestWriteDownGuards:

    def test_write_down_zero_amount_rejected(self):
        """PRD section 3.6: "Already at creation, every listed entry must
        exist, belong to the matter, and be in `APPROVED` or `BILLED` —
        violations are rejected with `ERR_WRITE_DOWN_ENTRIES_INVALID`
        (HTTP 422) — and `requested_amount_cents` must be greater than zero
        and no more than the sum of the listed entries'
        `billable_amount_cents`, or creation is rejected with
        `ERR_WRITE_DOWN_AMOUNT_INVALID` (HTTP 422)."

        Design: Corner/validations/write_down_amount_zero_rejected
        """
        ctx = setup_active_matter(
            phases=[{"task_code": "L110", "budget": 100000}])
        entry = add_approved_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                                   ctx["partner"]["id"], 50000,
                                   ctx["partner"]["id"])

        resp = api_client.create_write_down_request(
            ctx["firm"]["id"], ctx["matter"]["id"],
            create_write_down_request_payload([entry["id"]], 0),
            make_billing_partner_headers(ctx["partner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_WRITE_DOWN_AMOUNT_INVALID)

    def test_decide_on_rejected_write_down_invalid(self):
        """PRD section 3.6: "Rejection moves the request to the terminal
        `REJECTED` state from either tier."
        PRD section 2.9: "Generic state-transition legality
        (`ERR_INVALID_STATE_TRANSITION`)."

        Design: Corner/state_machines/write_down_terminal_state_lockdown
        """
        ctx = setup_active_matter(
            with_second_partner=True,
            phases=[{"task_code": "L110", "budget": 100000}])
        entry = add_approved_entry(ctx["firm"]["id"], ctx["matter"]["id"],
                                   ctx["partner"]["id"], 50000,
                                   ctx["partner"]["id"])
        wdr = create_write_down(ctx["firm"]["id"], ctx["matter"]["id"],
                                [entry["id"]], 10000, ctx["partner"]["id"])
        submit_write_down(ctx["firm"]["id"], wdr["id"],
                          ctx["partner"]["id"])
        rejected = decide_write_down(ctx["firm"]["id"], wdr["id"], "REJECT",
                                     ctx["partner2"]["id"])
        assert rejected["status"] == "REJECTED"

        resp = api_client.decide_write_down_request(
            ctx["firm"]["id"], wdr["id"], {"decision": "APPROVE"},
            make_billing_partner_headers(ctx["partner2"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestWriteDownRbac:

    def test_pricing_analyst_cannot_decide_write_down(self):
        """PRD section 2.1: "A request whose role is not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."
        PRD section 4: "| POST |
        `/firms/{firmId}/write_down_requests/{requestId}/decide` | Approve
        or reject (segregation of duties enforced) | BillingPartner,
        ManagingPartner |"

        Design: Corner/rbac/pricing_analyst_cannot_decide_write_down
        """
        firm = setup_firm()
        resp = api_client.decide_write_down_request(
            firm["id"], NON_EXISTENT_UUID, {"decision": "APPROVE"}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
