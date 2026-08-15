"""Scholarship grants: pool conservation, apply ordering, approval bounds."""
from test_helpers import (
    ApiErrorId,
    apply_grant,
    approve_grant,
    assert_scholarship_pool_invariant,
    create_grant,
    create_open_season_with_section,
    enroll_member,
    grant_apply_payload,
    grant_decision_payload,
    issue_invoice,
    pay_dues,
    validate_error,
    validate_success,
)


class TestGrantApplyOrdering:
    def test_grant_apply_state_beats_fiscal(self, api, treasurer_headers):
        """PRD §3.4: "Applying a grant is the state tier's most carefully
        ordered operation: the grant's own status is checked first — it must be
        `APPROVED`, else `ERR_GRANT_NOT_APPROVED` — and only then is the target
        invoice examined"

        Design: Difficulty/priority_pair_validation_conflict/grant_apply_state_beats_fiscal
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        invoice = issue_invoice(member["id"])
        pay_dues(member["id"], 18000)  # invoice PAID, balance zero
        grant = create_grant(member["id"], 5000)  # stays REQUESTED

        # Grant not APPROVED AND amount exceeds the (zero) invoice balance:
        # the grant-state check fires first.
        resp = api.apply_grant(
            grant["id"],
            grant_apply_payload(invoice["id"], 999999),
            treasurer_headers)
        validate_error(resp, ApiErrorId.ERR_GRANT_NOT_APPROVED)

        grant_data = validate_success(api.get_grant(grant["id"],
                                                    treasurer_headers))
        assert grant_data["status"] == "REQUESTED", \
            "rejected apply leaves the grant untouched"

    def test_grant_apply_invoice_state_beats_amount_bound(
            self, api, treasurer_headers):
        """PRD §3.4: "and only then is the target invoice examined, which must
        be in `ISSUED`, `PARTIAL`, or `OVERDUE` with a positive
        `balance_cents`, else `ERR_INVOICE_NOT_OPEN`. The applied amount is the
        lesser of `approved_cents` and the invoice's `balance_cents`; a caller
        may name a smaller explicit `amount_cents`, but one above that bound is
        rejected with `ERR_GRANT_EXCEEDS_INVOICE_BALANCE`."

        Design: Difficulty/priority_pair_validation_conflict/grant_apply_state_beats_fiscal
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        invoice = issue_invoice(member["id"])
        pay_dues(member["id"], 18000)  # invoice PAID: no longer open
        grant = create_grant(member["id"], 5000)
        approve_grant(grant["id"])

        # The grant IS approved, so the invoice-state check fires before the
        # explicit-amount bound even though 999999 also exceeds that bound.
        resp = api.apply_grant(
            grant["id"],
            grant_apply_payload(invoice["id"], 999999),
            treasurer_headers)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_OPEN)

        grant_data = validate_success(api.get_grant(grant["id"],
                                                    treasurer_headers))
        assert grant_data["status"] == "APPROVED"

    def test_grant_apply_explicit_amount_exceeds_balance_rejected(
            self, api, treasurer_headers):
        """PRD §3.4: "The applied amount is the lesser of `approved_cents` and
        the invoice's `balance_cents`; a caller may name a smaller explicit
        `amount_cents`, but one above that bound is rejected with
        `ERR_GRANT_EXCEEDS_INVOICE_BALANCE`."

        Design: Corner/validations/grant_apply_explicit_amount_exceeds_balance_rejected
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        invoice = issue_invoice(member["id"])  # balance 18000
        grant = create_grant(member["id"], 10000)
        approve_grant(grant["id"], approved_cents=10000)

        # Explicit 12000 exceeds min(approved 10000, balance 18000) = 10000.
        resp = api.apply_grant(
            grant["id"],
            grant_apply_payload(invoice["id"], 12000),
            treasurer_headers)
        validate_error(resp, ApiErrorId.ERR_GRANT_EXCEEDS_INVOICE_BALANCE)

        season_data = validate_success(api.get_season(season["id"],
                                                      treasurer_headers))
        assert season_data["pool_reserved_cents"] == 10000, \
            "rejected apply leaves the reservation in place"
        assert season_data["pool_spent_cents"] == 0
        assert_scholarship_pool_invariant(season_data)


class TestPoolApprovalBoundary:
    def test_scholarship_pool_exact_boundary(self, api, treasurer_headers):
        """PRD §3.4: "Approval takes an optional explicit `approved_cents` that
        defaults to the lesser of `requested_cents` and the season's
        `pool_available_cents`; the approved amount must be positive and no
        greater than `pool_available_cents`, else
        `ERR_SCHOLARSHIP_POOL_EXHAUSTED`. Approval reserves the funds —
        `pool_reserved_cents` grows by `approved_cents` and
        `pool_available_cents` shrinks by the same"

        Design: Difficulty/boundary_precision_check/scholarship_pool_exact_boundary
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        g1 = create_grant(member["id"], 50000)
        g2 = create_grant(member["id"], 1)

        # Exactly equal to pool_available: permitted (the bound is inclusive).
        approved = validate_success(api.decide_grant(
            g1["id"], grant_decision_payload("APPROVE"), treasurer_headers))
        assert approved["approved_cents"] == 50000
        assert approved["status"] == "APPROVED"

        # The pool is now empty; one more cent cannot be approved.
        resp = api.decide_grant(
            g2["id"], grant_decision_payload("APPROVE"), treasurer_headers)
        validate_error(resp, ApiErrorId.ERR_SCHOLARSHIP_POOL_EXHAUSTED)

        season_data = validate_success(api.get_season(season["id"],
                                                      treasurer_headers))
        assert season_data["pool_available_cents"] == 0
        assert season_data["pool_reserved_cents"] == 50000
        assert season_data["pool_spent_cents"] == 0
        assert_scholarship_pool_invariant(season_data)

    def test_explicit_approved_cents_one_over_available_rejected(
            self, api, treasurer_headers):
        """PRD §3.4: "the approved amount must be positive and no greater than
        `pool_available_cents`, else `ERR_SCHOLARSHIP_POOL_EXHAUSTED`."

        Design: Difficulty/boundary_precision_check/scholarship_pool_exact_boundary
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        grant = create_grant(member["id"], 60000)

        # 50001 > pool_available 50000: rejected; the grant is undecided.
        resp = api.decide_grant(
            grant["id"],
            grant_decision_payload("APPROVE", approved_cents=50001),
            treasurer_headers)
        validate_error(resp, ApiErrorId.ERR_SCHOLARSHIP_POOL_EXHAUSTED)
        grant_data = validate_success(api.get_grant(grant["id"],
                                                    treasurer_headers))
        assert grant_data["status"] == "REQUESTED"

        # Exactly 50000 passes the inclusive bound.
        approved = validate_success(api.decide_grant(
            grant["id"],
            grant_decision_payload("APPROVE", approved_cents=50000),
            treasurer_headers))
        assert approved["approved_cents"] == 50000
        assert approved["status"] == "APPROVED"


class TestPoolConservation:
    def test_scholarship_pool_conservation(self, api, treasurer_headers,
                                           director_headers):
        """PRD §3.4: "Application unreserves the full approval
        (`pool_reserved_cents` falls by `approved_cents`), spends the applied
        portion (`pool_spent_cents` grows by the applied amount), returns the
        unspent difference to availability (`pool_available_cents` grows by
        `approved_cents` minus the applied amount), raises the invoice's
        `scholarship_applied_cents` by the applied amount, and recomputes its
        balance. A scholarship application that zeroes the invoice moves it to
        `WAIVED` rather than `PAID`, with the same member bubble-up, and the
        grant becomes `APPLIED` — terminal — with `invoice_id` recorded. An
        approved-but-unapplied grant can instead be revoked, moving it to
        `REVOKED` (also terminal) and returning the reservation to the pool:
        `pool_reserved_cents` falls by `approved_cents` and
        `pool_available_cents` rises by the same."

        Design: Difficulty/compensating_invariant/scholarship_pool_conservation
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        invoice = issue_invoice(member["id"])  # 18000
        pay_dues(member["id"], 6000)             # balance 12000, PARTIAL

        g1 = create_grant(member["id"], 20000)
        approve_grant(g1["id"])  # reserved 20000, available 30000
        applied = apply_grant(g1["id"], invoice["id"])
        assert applied["status"] == "APPLIED"
        assert applied["invoice_id"] == invoice["id"]

        invoice_data = validate_success(api.get_invoice(invoice["id"],
                                                        treasurer_headers))
        assert invoice_data["scholarship_applied_cents"] == 12000
        assert invoice_data["balance_cents"] == 0
        assert invoice_data["status"] == "WAIVED", \
            "a scholarship zeroing the invoice yields WAIVED, not PAID"

        member_data = validate_success(api.get_member(member["id"],
                                                      director_headers))
        assert member_data["status"] == "ACTIVE", "WAIVED bubble-up"
        assert member_data["performance_eligible"] is True

        # Approve 5000 then revoke: the reservation returns to availability.
        g2 = create_grant(member["id"], 5000)
        approve_grant(g2["id"])
        revoked = validate_success(api.revoke_grant(g2["id"], treasurer_headers))
        assert revoked["status"] == "REVOKED"

        season_data = validate_success(api.get_season(season["id"],
                                                      treasurer_headers))
        assert season_data["pool_spent_cents"] == 12000
        assert season_data["pool_reserved_cents"] == 0
        assert season_data["pool_available_cents"] == 38000
        assert_scholarship_pool_invariant(season_data)

    def test_partial_explicit_apply_and_rejection_preserve_invariant(
            self, api, treasurer_headers, director_headers):
        """PRD §3.4: "at every instant, `scholarship_pool_cents` equals
        `pool_available_cents` plus `pool_reserved_cents` plus
        `pool_spent_cents`."
        PRD §3.4: "Rejection simply records `decided_by_user_id` and moves the
        grant to `REJECTED`, which is terminal."

        Design: Difficulty/compensating_invariant/scholarship_pool_conservation
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        invoice = issue_invoice(member["id"])  # 18000
        pay_dues(member["id"], 6000)             # balance 12000

        g1 = create_grant(member["id"], 8000)
        approve_grant(g1["id"])  # available 42000, reserved 8000
        # Explicit partial apply: 5000 < min(8000, 12000).
        applied = apply_grant(g1["id"], invoice["id"], amount_cents=5000)
        assert applied["status"] == "APPLIED"

        season_data = validate_success(api.get_season(season["id"],
                                                      treasurer_headers))
        # reserved 8000 -> 0; spent 5000; available 42000 + (8000-5000) = 45000
        assert season_data["pool_spent_cents"] == 5000
        assert season_data["pool_reserved_cents"] == 0
        assert season_data["pool_available_cents"] == 45000
        assert_scholarship_pool_invariant(season_data)

        invoice_data = validate_success(api.get_invoice(invoice["id"],
                                                        treasurer_headers))
        assert invoice_data["scholarship_applied_cents"] == 5000
        assert invoice_data["balance_cents"] == 7000
        assert invoice_data["status"] == "PARTIAL", \
            "a partial application does not zero the invoice"
        member_data = validate_success(api.get_member(member["id"],
                                                      director_headers))
        assert member_data["status"] == "ENROLLED"

        # Rejection moves a REQUESTED grant to terminal REJECTED and does not
        # touch the pool.
        g2 = create_grant(member["id"], 7000)
        rejected = validate_success(api.decide_grant(
            g2["id"], grant_decision_payload("REJECT"), treasurer_headers))
        assert rejected["status"] == "REJECTED"

        season_data = validate_success(api.get_season(season["id"],
                                                      treasurer_headers))
        assert season_data["pool_available_cents"] == 45000
        assert season_data["pool_reserved_cents"] == 0
        assert season_data["pool_spent_cents"] == 5000
        assert_scholarship_pool_invariant(season_data)
