"""Transfer review desk: the deficiency cure cycle, medallion coverage
boundary, approval segregation of duties, and validation-order precedence."""
from test_helpers import (
    ApiErrorId,
    approve_transfer,
    create_transfer,
    cure_deficiency,
    flag_deficient,
    get_transfer,
    make_examiner_headers,
    make_shareholder_headers,
    make_supervisor_headers,
    setup_medallion_verified_transfer,
    setup_transfer_pair,
    submit_medallion,
    validate_error,
)


class TestDeficiencyCycleLoops:
    def test_deficient_cure_cycle_loops_back_to_review(self, api):
        """PRD §3.3: "A deficiency is curable: the transferor or an examiner
        cures it, returning the request `DEFICIENT` → `UNDER_REVIEW` with the
        `deficiency_reason` cleared, and the flag-and-cure cycle may repeat as
        often as the paperwork requires."
        PRD §2.1: "the server records it as `last_examiner_id` on a
        `TransferRequest` the examiner verifies or flags"

        Design: Difficulty/non_linear_state_machine/transfer_deficiency_cycle_loops
        """
        ctx = setup_transfer_pair(shares_outstanding=500, book_entry_shares=500,
                                  share_quantity=100)
        tid = ctx["transfer"]["id"]

        flag_deficient(tid, "missing medallion guarantee", examiner_id="exam_1")
        cured = cure_deficiency(tid, examiner_id="exam_1")
        assert cured["status"] == "UNDER_REVIEW"
        assert cured["deficiency_reason"] in (None, ""), "cure clears the reason"

        flag_deficient(tid, "illegible assignment", examiner_id="exam_2")
        cure_deficiency(tid, examiner_id="exam_2")
        verified = submit_medallion(tid, 500000, examiner_id="exam_2")

        assert verified["status"] == "MEDALLION_VERIFIED", (
            "after two full DEFICIENT -> UNDER_REVIEW loops the request "
            "accepts the medallion"
        )
        assert verified["last_examiner_id"] == "exam_2", (
            "the last examiner touch wins"
        )

    def test_deficiency_cycle_mutation_count_tracks_version(self, api):
        """PRD §2.5: "`version` (integer): a system-managed integer that
        increments by one on every mutation of the resource"
        PRD §3.3: "At creation the request's `transfer_value_cents` is frozen
        once and for all as the `share_quantity` multiplied by the issuer's
        `current_market_price_cents` at that moment"

        Design: Difficulty/non_linear_state_machine/transfer_deficiency_cycle_loops
        """
        ctx = setup_transfer_pair(shares_outstanding=500, book_entry_shares=500,
                                  share_quantity=100)
        tid = ctx["transfer"]["id"]

        flag_deficient(tid, "missing medallion guarantee", examiner_id="exam_1")
        cure_deficiency(tid, examiner_id="exam_1")
        flag_deficient(tid, "illegible assignment", examiner_id="exam_2")
        cure_deficiency(tid, examiner_id="exam_2")
        submit_medallion(tid, 500000, examiner_id="exam_2")

        fresh = get_transfer(tid)
        assert fresh["version"] == 6, (
            "create + flag + cure + flag + cure + medallion = six mutations"
        )
        assert fresh["transfer_value_cents"] == 500000, (
            "100 shares x 5000 cents, frozen at creation"
        )


class TestApprovalValidationPrecedence:
    def test_approve_state_gate_precedes_segregation_of_duties(self, api):
        """PRD §2.8: "Every request is validated against a fixed cascade of
        checks, evaluated in the following order, and the first failing check
        determines the error returned"
        PRD §2.8: "5. **State gates.** The target resource must be in a
        from-state the invoked transition permits"
        PRD §2.8: "6. **Segregation of duties.** Approval of an item by the
        same operator who examined or filed it fails with
        `ERR_SEGREGATION_OF_DUTIES`"
        PRD §2.8: "any other transition attempted from an impermissible state
        fails with the generic `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/approve_state_beats_sod_safety
        """
        ctx = setup_transfer_pair(shares_outstanding=100, book_entry_shares=100,
                                  share_quantity=50)
        tid = ctx["transfer"]["id"]
        flag_deficient(tid, "signature mismatch", examiner_id="exam_1")
        cure_deficiency(tid, examiner_id="exam_1")
        # UNDER_REVIEW again, last_examiner_id == "exam_1": approving as
        # "exam_1" violates both the state gate and segregation of duties.
        resp = api.approve_transfer_request(tid, make_supervisor_headers("exam_1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.json()["data"]["error_id"] != "ERR_SEGREGATION_OF_DUTIES", (
            "priority 5 state gate must surface before priority 6 safety"
        )
        assert get_transfer(tid)["status"] == "UNDER_REVIEW"

    def test_approve_state_rejection_leaves_request_actionable(self, api):
        """PRD §3.3: "Approval belongs to a `TransferSupervisor`, and only over
        a medallion-verified request: the approval moves `MEDALLION_VERIFIED` →
        `APPROVED` and records the supervisor's identifier in `approved_by`."
        PRD §2.8: "Because the cascade is ordered, a request that would fail
        several gates always surfaces the earliest one."

        Design: Difficulty/priority_pair_validation_conflict/approve_state_beats_sod_safety
        """
        ctx = setup_transfer_pair(shares_outstanding=100, book_entry_shares=100,
                                  share_quantity=50)
        tid = ctx["transfer"]["id"]
        flag_deficient(tid, "signature mismatch", examiner_id="exam_1")
        cure_deficiency(tid, examiner_id="exam_1")
        resp = api.approve_transfer_request(tid, make_supervisor_headers("exam_1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        # The failed approve changed nothing: a clean medallion + a distinct
        # supervisor completes the review.
        submit_medallion(tid, 250000, examiner_id="exam_2")
        approved = approve_transfer(tid, supervisor_id="sup_1")
        assert approved["status"] == "APPROVED"
        assert approved["approved_by"] == "sup_1"


class TestMedallionCoverageBoundary:
    def _setup_two_open_transfers(self):
        ctx = setup_transfer_pair(shares_outstanding=200, book_entry_shares=200,
                                  share_quantity=100)
        # Second transfer, OCC-threaded against the post-t1 account version.
        t2 = create_transfer(ctx["acct_a"]["id"], ctx["acct_b"]["id"],
                             ctx["issuer"]["id"], 100)
        ctx["t2"] = t2
        return ctx

    def test_medallion_coverage_exactly_value_accepted(self, api):
        """PRD §3.3: "Submitting the medallion signature guarantee — a payload
        carrying the `medallion_reference` and the stamp's `coverage_cents` —
        moves the request `UNDER_REVIEW` → `MEDALLION_VERIFIED`, but only when
        the surety coverage is at least the frozen `transfer_value_cents`; a
        stamp covering even one cent less is refused with
        `ERR_MEDALLION_COVERAGE_INSUFFICIENT`, while coverage exactly equal to
        the transfer value suffices."

        Design: Difficulty/boundary_precision_check/medallion_coverage_boundary_inclusive
        """
        ctx = self._setup_two_open_transfers()
        t1 = ctx["transfer"]
        assert t1["transfer_value_cents"] == 500000  # 100 x 5000

        verified = submit_medallion(t1["id"], 500000, examiner_id="exam_1",
                                    medallion_reference="MED-EQ")
        assert verified["status"] == "MEDALLION_VERIFIED", (
            "coverage == transfer value satisfies the inclusive boundary"
        )
        assert verified["medallion_coverage_cents"] == 500000

    def test_medallion_coverage_one_cent_short_rejected(self, api):
        """PRD §3.3: "a stamp covering even one cent less is refused with
        `ERR_MEDALLION_COVERAGE_INSUFFICIENT`, while coverage exactly equal to
        the transfer value suffices."

        Design: Difficulty/boundary_precision_check/medallion_coverage_boundary_inclusive
        """
        ctx = self._setup_two_open_transfers()
        t2 = ctx["t2"]

        resp = api.submit_medallion(
            t2["id"],
            {"medallion_reference": "MED-SHORT", "coverage_cents": 499999},
            make_examiner_headers("exam_1"),
        )
        validate_error(resp, ApiErrorId.ERR_MEDALLION_COVERAGE_INSUFFICIENT)
        assert get_transfer(t2["id"])["status"] == "UNDER_REVIEW", (
            "a rejected stamp leaves the request in review"
        )


class TestApprovalRoles:
    def test_shareholder_cannot_approve_transfer(self, api):
        """PRD §3.3: "Approval belongs to a `TransferSupervisor`, and only over
        a medallion-verified request"
        PRD §2.1: "A request whose role is not authorized for the endpoint it
        targets — or a `Shareholder` attempting to act on another holder's
        resources — is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/shareholder_cannot_approve_transfer
        """
        ctx = setup_medallion_verified_transfer(share_quantity=10)
        tid = ctx["transfer"]["id"]

        resp = api.approve_transfer_request(
            tid, make_shareholder_headers(ctx["acct_a"]["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert get_transfer(tid)["status"] == "MEDALLION_VERIFIED"

    def test_supervisor_who_examined_cannot_approve(self, api):
        """PRD §3.3: "the approving supervisor's `X-User-ID` must differ from
        the request's `last_examiner_id`, so the operator who verified the
        medallion or flagged the deficiency can never approve the same item; a
        violation is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/supervisor_who_examined_cannot_approve
        """
        ctx = setup_medallion_verified_transfer(share_quantity=10,
                                                examiner_id="exam_1")
        tid = ctx["transfer"]["id"]

        resp = api.approve_transfer_request(tid, make_supervisor_headers("exam_1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        approved = approve_transfer(tid, supervisor_id="sup_9")
        assert approved["status"] == "APPROVED"
        assert approved["approved_by"] == "sup_9"
