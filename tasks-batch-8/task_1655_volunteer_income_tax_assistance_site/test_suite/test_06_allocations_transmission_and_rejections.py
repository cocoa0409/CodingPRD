"""Split refunds, transmission, and rejection rework: allocation cardinality
and conservation, per-line savings-match rounding, the transmit site gate,
terminal lockdown, rejection follow-up gating, and the submission ceiling."""
from test_helpers import (
    ApiErrorId,
    add_allocation,
    assert_refund_allocation,
    begin_preparation,
    create_intake_return,
    create_preparation_ready_return,
    create_rejected_return,
    create_verified_taxpayer,
    delete_allocation,
    drive_return_to_completed,
    drive_return_to_qr_passed,
    get_return,
    is_iso8601_timestamp,
    list_allocations,
    list_referrals,
    offer_referral,
    resolve_rejection,
    review_pass,
    rework_rejected_return,
    set_clock,
    setup_staffed_site,
    submit_for_review,
    transition_return,
    transition_site,
    transmit_return,
    validate_error,
    validate_success,
)

DD_PATCH = {
    "documents_received": ["PHOTO_ID", "SSN_CARD", "W2", "BANK_INFO"],
    "refund_method": "DIRECT_DEPOSIT",
}


def _prep_direct_deposit(ctx, ssn, name, patch_extra=None):
    """Return in IN_PREPARATION with refund_method DIRECT_DEPOSIT."""
    tp = create_verified_taxpayer(ctx.scr_headers, full_name=name, ssn_token=ssn,
                                  phone="555-6000")
    overrides = dict(DD_PATCH)
    overrides.update(patch_extra or {})
    appt, ret = create_preparation_ready_return(ctx, tp["id"], patch_overrides=overrides)
    ret = begin_preparation(ret)
    return appt, ret


class TestAllocationCardinality:
    def test_three_allocations_allowed(self, api):
        """PRD §3.6: "Taxpayers electing direct deposit may split their
        refund across up to three accounts."

        Design: Difficulty/boundary_precision_check/allocation_cardinality_3_allowed_4_rejected
        """
        ctx = setup_staffed_site()
        appt, ret = _prep_direct_deposit(ctx, "SSN-007", "Taxpayer Seven")
        created = [
            add_allocation(ret["id"], ctx.preparer["id"],
                           account_type=acct, account_number_mask=f"****000{i}",
                           amount_cents=50000)
            for i, acct in enumerate(("CHECKING", "SAVINGS", "CHECKING"), start=1)
        ]
        for alloc in created:
            assert_refund_allocation(alloc)
        allocs = list_allocations(ret["id"], ctx.prep_headers)
        assert len(allocs) == 3, "a return carries up to three allocations"

    def test_fourth_allocation_rejected(self, api):
        """PRD §3.6: "A fourth allocation is rejected with
        `ERR_ALLOCATION_LIMIT`, and adding or removing an allocation against
        any other return status is rejected with `ERR_INVALID_TRANSITION`."

        Design: Difficulty/boundary_precision_check/allocation_cardinality_3_allowed_4_rejected
        """
        ctx = setup_staffed_site()
        appt, ret = _prep_direct_deposit(ctx, "SSN-007", "Taxpayer Seven")
        for i, acct in enumerate(("CHECKING", "SAVINGS", "CHECKING"), start=1):
            add_allocation(ret["id"], ctx.preparer["id"], account_type=acct,
                           account_number_mask=f"****000{i}", amount_cents=50000)

        resp = api.create_refund_allocation(
            {"tax_return_id": ret["id"], "account_type": "SAVINGS",
             "routing_number": "021000021", "account_number_mask": "****0004",
             "amount_cents": 10000},
            ctx.prep_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_LIMIT)
        allocs = list_allocations(ret["id"], ctx.prep_headers)
        assert len(allocs) == 3, "the rejected fourth allocation adds no row"


class TestSavingsMatch:
    def test_savings_match_per_line_floor(self, api):
        """PRD §3.6: "For every allocation whose `account_type` is `SAVINGS`,
        the line's match is 50 percent of its `amount_cents`, floored down to
        whole dollars; the return's match is the sum of those per-line
        matches, capped at $100. The per-line flooring happens before
        summation, so two `SAVINGS` lines of 3,333 cents each contribute
        1,600 cents apiece for a match of 3,200 cents — flooring the summed
        amount instead would wrongly yield 3,300 cents and is forbidden."

        Design: Difficulty/combinatorial_formula/savings_match_per_line_rounding
        """
        ctx = setup_staffed_site()
        appt, ret = _prep_direct_deposit(
            ctx, "SSN-003", "Taxpayer Three",
            patch_extra={
                "wages_cents": 2000000, "earned_income_cents": 2000000,
                "withholding_reported_cents": 150000,
                "withholding_verified_cents": 150000, "qualifying_children": 1,
            },
        )
        add_allocation(ret["id"], ctx.preparer["id"], account_type="SAVINGS",
                       account_number_mask="****0001", amount_cents=3333)
        add_allocation(ret["id"], ctx.preparer["id"], account_type="SAVINGS",
                       account_number_mask="****0002", amount_cents=3333)
        add_allocation(ret["id"], ctx.preparer["id"], account_type="CHECKING",
                       account_number_mask="****0003", amount_cents=100000)

        ret = get_return(ret["id"], ctx.prep_headers)
        # floor(3333/200)*100 = 1600 per SAVINGS line, summed before the cap
        assert ret["savings_match_cents"] == 3200
        assert ret["savings_match_cents"] != 3300, (
            "sum-then-round is the forbidden order"
        )

    def test_savings_match_recomputed_on_delete(self, api):
        """PRD §3.6: "Each change to the allocation set — and any edit
        touching allocation-relevant state — recomputes the sponsor's
        savings-match incentive, `savings_match_cents`."
        PRD §3.6: "Removing an allocation is permitted in the same window and
        returns no content."

        Design: Difficulty/combinatorial_formula/savings_match_per_line_rounding
        """
        ctx = setup_staffed_site()
        appt, ret = _prep_direct_deposit(ctx, "SSN-003", "Taxpayer Three")
        first = add_allocation(ret["id"], ctx.preparer["id"], account_type="SAVINGS",
                               account_number_mask="****0001", amount_cents=3333)
        add_allocation(ret["id"], ctx.preparer["id"], account_type="SAVINGS",
                       account_number_mask="****0002", amount_cents=3333)
        assert get_return(ret["id"], ctx.prep_headers)["savings_match_cents"] == 3200

        delete_allocation(first["id"], ctx.preparer["id"])
        ret = get_return(ret["id"], ctx.prep_headers)
        # one remaining SAVINGS line: floor(3333/200)*100 = 1600
        assert ret["savings_match_cents"] == 1600

    def test_savings_match_cap_applies(self, api):
        """PRD §3.6: "For every allocation whose `account_type` is `SAVINGS`,
        the line's match is 50 percent of its `amount_cents`, floored down to
        whole dollars; the return's match is the sum of those per-line
        matches, capped at $100."

        Design: Corner/calculations/savings_match_cap_applies
        """
        ctx = setup_staffed_site()
        appt, ret = _prep_direct_deposit(ctx, "SSN-MC1", "Tp MC")
        add_allocation(ret["id"], ctx.preparer["id"], account_type="SAVINGS",
                       account_number_mask="****0010", amount_cents=50000)

        ret = get_return(ret["id"], ctx.prep_headers)
        # raw floor(50000/200)*100 = 25000, clamped to the $100 cap
        assert ret["savings_match_cents"] == 10000


class TestAllocationConservation:
    def _allocated_return(self, ctx):
        """DIRECT_DEPOSIT return in IN_PREPARATION whose figures give a
        final refund of 310000, carrying three allocations summing 310000."""
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Taxpayer Ten",
                                      ssn_token="SSN-010", phone="555-0110")
        appt, ret = create_preparation_ready_return(
            ctx, tp["id"],
            patch_overrides=dict(
                DD_PATCH,
                wages_cents=2000000, other_income_cents=0,
                earned_income_cents=2000000, qualifying_children=1,
                withholding_reported_cents=150000,
                withholding_verified_cents=150000,
            ),
        )
        ret = begin_preparation(ret)
        a1 = add_allocation(ret["id"], ctx.preparer["id"], amount_cents=100000,
                            account_number_mask="****0001")
        a2 = add_allocation(ret["id"], ctx.preparer["id"], amount_cents=100000,
                            account_number_mask="****0002")
        a3 = add_allocation(ret["id"], ctx.preparer["id"], amount_cents=110000,
                            account_number_mask="****0003")
        return ret, (a1, a2, a3)

    def test_delete_restores_sum_and_mismatch_rejected(self, api):
        """PRD §3.6: "when the return's `refund_method` is `DIRECT_DEPOSIT`,
        its allocations must number between one and three and their
        `amount_cents` must sum exactly to the return's `final_refund_cents`,
        failing which the transmission is rejected with
        `ERR_ALLOCATION_SUM_MISMATCH`"
        PRD §3.6: "Removing an allocation is permitted in the same window and
        returns no content."

        Design: Difficulty/compensating_invariant/refund_allocation_conservation
        """
        ctx = setup_staffed_site()
        ret, (a1, a2, a3) = self._allocated_return(ctx)

        delete_allocation(a3["id"], ctx.preparer["id"])
        allocs = list_allocations(ret["id"], ctx.prep_headers)
        assert len(allocs) == 2
        assert sum(a["amount_cents"] for a in allocs) == 200000, (
            "the add/delete pair leaves the allocated total unchanged"
        )

        ret = submit_for_review(get_return(ret["id"], ctx.prep_headers))
        # 150000 + min(round(0.20 * 2000000), 400000) - round(0.12 * 2000000)
        assert ret["final_refund_cents"] == 310000
        ret = review_pass(ret, ctx.reviewer["id"])

        resp = api.transition_tax_return(
            ret["id"], {"to_status": "TRANSMITTED"}, ctx.coord_headers
        )
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_SUM_MISMATCH)

    def test_compensating_readd_allows_transmit(self, api):
        """PRD §3.6: "While the return is `INTAKE_STARTED`, `IN_PREPARATION`,
        or `QR_PASSED` — that is, right up until transmit — the owning
        `Preparer` may add a refund allocation supplying `tax_return_id`, an
        `account_type` of `CHECKING` or `SAVINGS`, a `routing_number` of
        exactly nine digits, a masked `account_number_mask` such as ****6789,
        and an `amount_cents` of at least one cent."
        PRD §3.6: "Each successful transmission increments `submission_count`
        by one and stamps `transmitted_at` with the current logical time."

        Design: Difficulty/compensating_invariant/refund_allocation_conservation
        """
        ctx = setup_staffed_site()
        ret, (a1, a2, a3) = self._allocated_return(ctx)
        delete_allocation(a3["id"], ctx.preparer["id"])
        ret = submit_for_review(get_return(ret["id"], ctx.prep_headers))
        ret = review_pass(ret, ctx.reviewer["id"])
        resp = api.transition_tax_return(
            ret["id"], {"to_status": "TRANSMITTED"}, ctx.coord_headers
        )
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_SUM_MISMATCH)

        # Compensating re-add while QR_PASSED restores conservation exactly.
        add_allocation(ret["id"], ctx.preparer["id"], amount_cents=110000,
                       account_number_mask="****0004")
        allocs = list_allocations(ret["id"], ctx.prep_headers)
        assert sum(a["amount_cents"] for a in allocs) == 310000

        ret = transmit_return(get_return(ret["id"], ctx.prep_headers), ctx.coord_headers)
        assert ret["status"] == "TRANSMITTED"
        assert ret["submission_count"] == 1


class TestTransmitSiteGate:
    def test_transmit_blocked_while_site_suspended(self, api):
        """PRD §3.6: "Transmission — `QR_PASSED` to `TRANSMITTED`, performed
        by the `SiteCoordinator` — e-files the return. The site must be
        `OPEN` (`ERR_SITE_NOT_OPEN`)"
        PRD §3.1: "Link two: each appointment cancelled by link one that
        originated a tax return still in `INTAKE_STARTED` causes that return
        to be withdrawn, with `withdrawal_reason` recorded as
        `SITE_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/transmit_requires_site_open
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Taxpayer Eight",
                                      ssn_token="SSN-008", phone="555-0108")
        appt, ret = drive_return_to_qr_passed(ctx, tp["id"])
        transition_site(ctx.site_id, "SUSPENDED", ctx.coord_headers)

        resp = api.transition_tax_return(
            ret["id"], {"to_status": "TRANSMITTED"}, ctx.coord_headers
        )
        validate_error(resp, ApiErrorId.ERR_SITE_NOT_OPEN)

        ret = get_return(ret["id"], ctx.coord_headers)
        assert ret["status"] == "QR_PASSED", (
            "the suspend cascade withdraws only INTAKE_STARTED returns"
        )
        appt = validate_success(api.get_appointment(appt["id"], ctx.coord_headers))
        assert appt["status"] == "CANCELLED", (
            "link one cancels the CHECKED_IN origin appointment"
        )

    def test_transmit_succeeds_after_reopen(self, api):
        """PRD §3.1: "Re-opening a `SUSPENDED` site carries no preconditions."
        PRD §3.6: "Each successful transmission increments `submission_count`
        by one and stamps `transmitted_at` with the current logical time."

        Design: Difficulty/cross_entity_state_dependency/transmit_requires_site_open
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Taxpayer Eight",
                                      ssn_token="SSN-008", phone="555-0108")
        appt, ret = drive_return_to_qr_passed(ctx, tp["id"])
        transition_site(ctx.site_id, "SUSPENDED", ctx.coord_headers)
        transition_site(ctx.site_id, "OPEN", ctx.coord_headers)

        ret = transmit_return(ret, ctx.coord_headers)
        assert ret["status"] == "TRANSMITTED"
        assert ret["submission_count"] == 1
        assert ret["transmitted_at"] is not None
        assert is_iso8601_timestamp(ret["transmitted_at"])


class TestTransmitRoles:
    def test_screener_cannot_transmit(self, api):
        """PRD §3.6: "Transmission — `QR_PASSED` to `TRANSMITTED`, performed
        by the `SiteCoordinator` — e-files the return."
        PRD §2.1: "Any action attempted outside the caller's role envelope is
        rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/screener_cannot_transmit
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp RB2",
                                      ssn_token="SSN-RB2", phone="555-2030",
                                      id_document_type="PASSPORT")
        appt, ret = drive_return_to_qr_passed(ctx, tp["id"])

        resp = api.transition_tax_return(
            ret["id"], {"to_status": "TRANSMITTED"}, ctx.scr_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        ret = get_return(ret["id"], ctx.coord_headers)
        assert ret["status"] == "QR_PASSED"
        assert ret["submission_count"] == 0


class TestCompletedTerminal:
    def test_completed_terminal_lockdown(self, api):
        """PRD §3.7: "`COMPLETED` is terminal."
        PRD §2.8: "the requested transition must exist from the resource's
        current state — terminal states accept no transitions — and the
        editability windows must hold."

        Design: Corner/state_machines/completed_terminal_lockdown
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp Term",
                                      ssn_token="SSN-TERM", phone="555-2009")
        appt, ret = drive_return_to_completed(ctx, tp["id"])
        assert ret["status"] == "COMPLETED"

        resp = api.transition_tax_return(
            ret["id"],
            {"to_status": "WITHDRAWN", "withdrawal_reason": "Taxpayer request"},
            ctx.coord_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
        ret = get_return(ret["id"], ctx.coord_headers)
        assert ret["status"] == "COMPLETED"


class TestAllocationReverseReach:
    def test_fk_reverse_list_allocations(self, api):
        """PRD §2.3: "Unless otherwise specified, every list endpoint returns
        its resources sorted by creation timestamp in ascending order, and
        the reverse-reach listing views described in §4 (a site's volunteers,
        a site's reports, a volunteer's certification attempts, a return's
        allocations, rejections, and financial referrals) follow the same
        ordering."

        Design: Corner/endpoints/fk_reverse_list_allocations
        """
        ctx = setup_staffed_site()
        appt, ret = _prep_direct_deposit(ctx, "SSN-FK1", "Tp FK")
        add_allocation(ret["id"], ctx.preparer["id"], account_type="CHECKING",
                       account_number_mask="****0101", amount_cents=40000)
        add_allocation(ret["id"], ctx.preparer["id"], account_type="SAVINGS",
                       account_number_mask="****0102", amount_cents=60000)

        allocs = list_allocations(ret["id"], ctx.prep_headers)
        assert len(allocs) == 2
        assert all(a["tax_return_id"] == ret["id"] for a in allocs)
        assert [a["amount_cents"] for a in allocs] == [40000, 60000]
        assert [a["account_number_mask"] for a in allocs] == ["****0101", "****0102"]


class TestRejectionReworkGates:
    def test_rework_blocked_while_rejection_unresolved(self, api):
        """PRD §3.7: "Rework is barred while any of the return's e-file
        rejections has a `follow_up_status` other than `RESOLVED`
        (`ERR_REJECTION_UNRESOLVED`), and it is barred once the return's
        `submission_count` has reached three (`ERR_MAX_SUBMISSIONS_REACHED`)"
        PRD §3.7: "an e-file rejection record is created, bound to the return
        through `tax_return_id`, snapshotting `submission_number` equal to
        the return's current `submission_count`, and opening follow-up work
        in `OPEN` status."

        Design: Corner/validations/rework_blocked_while_rejection_unresolved
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp RJ",
                                      ssn_token="SSN-RJ1", phone="555-2018")
        appt, ret, rejection = create_rejected_return(ctx, taxpayer_id=tp["id"])
        assert rejection["follow_up_status"] == "OPEN"
        assert rejection["submission_number"] == 1

        resp = api.transition_tax_return(
            ret["id"], {"to_status": "IN_PREPARATION"}, ctx.prep_headers
        )
        validate_error(resp, ApiErrorId.ERR_REJECTION_UNRESOLVED)

        rejections = validate_success(
            api.list_efile_rejections(ret["id"], ctx.prep_headers)
        )
        assert rejections[0]["follow_up_status"] == "OPEN"
        ret = get_return(ret["id"], ctx.prep_headers)
        assert ret["status"] == "REJECTED"

    def test_max_submissions_forces_referral(self, api):
        """PRD §3.7: "Rework is barred while any of the return's e-file
        rejections has a `follow_up_status` other than `RESOLVED`
        (`ERR_REJECTION_UNRESOLVED`), and it is barred once the return's
        `submission_count` has reached three (`ERR_MAX_SUBMISSIONS_REACHED`)
        — a return that has exhausted three submissions must be referred out
        instead (§3.8)."

        Design: Corner/validations/max_submissions_forces_referral
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp MX",
                                      ssn_token="SSN-MX1", phone="555-2019")
        appt, ret = create_preparation_ready_return(ctx, tp["id"])
        ret = begin_preparation(ret)

        codes = (("R0000-503", "SSN mismatch"), ("IND-031", "Prior-year AGI mismatch"),
                 ("IND-507", "Dependent claimed elsewhere"))
        for i, (code, text) in enumerate(codes):
            ret = submit_for_review(ret)
            ret = review_pass(ret, ctx.reviewer["id"])
            ret = transmit_return(ret, ctx.coord_headers)
            assert ret["submission_count"] == i + 1
            ret = transition_return(
                ret["id"], "REJECTED", ctx.coord_headers,
                rejection_code=code, rejection_text=text,
            )
            rejections = validate_success(
                api.list_efile_rejections(ret["id"], ctx.rev_headers)
            )
            assert len(rejections) == i + 1
            resolve_rejection(rejections[i]["id"], ctx.rev_headers,
                              resolution_note=f"Cycle {i + 1} corrected")
            if i < 2:
                set_clock(f"2026-08-0{4 + i}T00:00:00Z")
                ret = rework_rejected_return(ret)
                assert ret["status"] == "IN_PREPARATION"

        resp = api.transition_tax_return(
            ret["id"], {"to_status": "IN_PREPARATION"}, ctx.prep_headers
        )
        validate_error(resp, ApiErrorId.ERR_MAX_SUBMISSIONS_REACHED)

        ret = validate_success(
            api.transition_tax_return(
                ret["id"],
                {"to_status": "REFERRED",
                 "referral_reason": "Exceeded maximum e-file submissions",
                 "referral_destination": "Paper filing assistance"},
                ctx.coord_headers,
            )
        )
        assert ret["status"] == "REFERRED"
        assert ret["referral_reason"] == "Exceeded maximum e-file submissions"


class TestWithdrawalReferralInvariant:
    def test_withdraw_voids_referrals(self, api):
        """PRD §3.8: "One invariant protects the financial-capability
        pipeline: every transition of a return into `WITHDRAWN` or `REFERRED`
        — whether actor-driven or cascade-driven — voids the return's
        financial-service referrals still in `OFFERED` or `ACCEPTED`, moving
        them to `VOID`."
        PRD §3.8: "From the same six non-terminal states, a `Preparer` or the
        `SiteCoordinator` may move the return to `WITHDRAWN`, supplying a
        `withdrawal_reason` (`ERR_INVALID_REQUEST` when absent on an
        actor-driven withdrawal)."

        Design: Corner/state_machines/withdraw_voids_referrals
        """
        ctx = setup_staffed_site()
        tp = create_verified_taxpayer(ctx.scr_headers, full_name="Tp WD",
                                      ssn_token="SSN-WD1", phone="555-2012")
        appt, ret = create_intake_return(ctx, tp["id"],
                                         appt_kwargs={"purpose": "INTAKE"})
        referral = offer_referral(ret["id"], ctx.prep_headers, "CREDIT_COUNSELING")
        assert referral["status"] == "OFFERED"

        ret = transition_return(
            ret["id"], "WITHDRAWN", ctx.prep_headers,
            withdrawal_reason="Taxpayer moved away",
        )
        assert ret["status"] == "WITHDRAWN"
        assert ret["withdrawal_reason"] == "Taxpayer moved away"

        referrals = list_referrals(ret["id"], ctx.prep_headers)
        assert len(referrals) == 1
        assert referrals[0]["id"] == referral["id"]
        assert referrals[0]["status"] == "VOID"
