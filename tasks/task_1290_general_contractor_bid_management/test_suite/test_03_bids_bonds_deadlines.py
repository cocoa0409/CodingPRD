"""Bid submission gates, bond boundaries, deadline boundaries, revisions and
their OCC contract, withdrawal, and the append-only revision audit trail."""
from test_helpers import (
    LEAD,
    ApiErrorId,
    advance_clock,
    assert_bid,
    assert_bid_revision,
    assert_timestamp_equals,
    close_bidding,
    create_bid_package,
    decide_application,
    get_package,
    invite,
    make_subcontractor_headers,
    publish_package,
    register_subcontractor,
    respond_bidding,
    setup_approved_subcontractor,
    setup_published_with_bidders,
    submit_bid,
    submit_prequal_application,
    approve_application,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)


def _publish_with_one_bidder(name="Bid Package"):
    """PUBLISHED package + one approved, BIDDING subcontractor."""
    ctx = setup_published_with_bidders(n=1, name=name)
    bidder = ctx["bidders"][0]
    return ctx["package"], bidder["subcontractor"]


class TestBondExactBoundary:

    def test_bond_exactly_at_required_amount_passes(self):
        """PRD §3.6: "The required bond is computed per package: multiply the
        bid amount by the package's `bid_bond_required_pct`, round the product
        half-up to integer cents, and compare — the submitted
        `bond_amount_cents` must be at least the required figure. Equality
        passes; one cent short fails."

        Design: Difficulty/boundary_precision_check/bid_bond_exactly_required_amount_passes
        """
        pkg, sub = _publish_with_one_bidder("Bond Boundary Package")
        resp = api_client.create_bid(
            {"bid_package_id": pkg["id"], "base_bid_cents": 2_000_000,
             "bond_amount_cents": 100_000},
            make_subcontractor_headers(sub["id"]))
        bid = validate_success(resp, expected_status=201)
        assert_bid(bid)
        assert bid["status"] == "SUBMITTED"
        assert get_package(pkg["id"])["submitted_bid_count"] == 1

    def test_bond_one_cent_short_fails(self):
        """PRD §3.6: "The required bond is computed per package: multiply the
        bid amount by the package's `bid_bond_required_pct`, round the product
        half-up to integer cents, and compare — the submitted
        `bond_amount_cents` must be at least the required figure. Equality
        passes; one cent short fails."
        PRD §3.6: "Six preconditions gate the create, in the cascade order of
        §2.8: ... and the bond must cover the required amount
        (`ERR_BID_BOND_INSUFFICIENT`, HTTP 402)."

        Design: Difficulty/boundary_precision_check/bid_bond_exactly_required_amount_passes
        """
        pkg, sub = _publish_with_one_bidder("Bond Boundary Package")
        resp = api_client.create_bid(
            {"bid_package_id": pkg["id"], "base_bid_cents": 2_000_000,
             "bond_amount_cents": 99_999},
            make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_BID_BOND_INSUFFICIENT)
        assert get_package(pkg["id"])["submitted_bid_count"] == 0


class TestBondHalfUpRounding:

    def test_required_bond_rounds_half_up(self):
        """PRD §3.6: "The required bond is computed per package: multiply the
        bid amount by the package's `bid_bond_required_pct`, round the product
        half-up to integer cents, and compare — the submitted
        `bond_amount_cents` must be at least the required figure. Equality
        passes; one cent short fails."
        PRD §2.6: "Where a calculation must convert a fractional input into
        cents — a percentage-of-base leveling adjustment, or the required bid
        bond — the product is rounded to integer cents using the round-half-up
        method, and that rounding happens at the pinned step described in §3
        for each calculation."

        Design: Corner/calculations/bond_required_half_up_rounding_boundary
        """
        ctx = setup_published_with_bidders(n=2, name="Bond Round Package")
        sub_x = ctx["bidders"][0]["subcontractor"]
        sub_y = ctx["bidders"][1]["subcontractor"]
        # round_half_up(1_999_999 * 0.05) = round_half_up(99_999.95) = 100_000.
        resp = api_client.create_bid(
            {"bid_package_id": ctx["package"]["id"],
             "base_bid_cents": 1_999_999, "bond_amount_cents": 100_000},
            make_subcontractor_headers(sub_x["id"]))
        assert validate_success(resp, expected_status=201)["status"] == "SUBMITTED"

        resp = api_client.create_bid(
            {"bid_package_id": ctx["package"]["id"],
             "base_bid_cents": 1_999_999, "bond_amount_cents": 99_999},
            make_subcontractor_headers(sub_y["id"]))
        validate_error(resp, ApiErrorId.ERR_BID_BOND_INSUFFICIENT)


class TestRevisionDeadlineBoundary:

    def test_revision_one_minute_before_deadline_lands_last_minute(self):
        """PRD §3.6: "A successful revision overwrites `base_bid_cents` with
        the new amount, increments the bid's `version` by 1, and appends a
        revision row whose `sequence` is one more than the bid's current
        maximum and whose `amount_cents` carries the new base."
        PRD §3.6: "The `is_last_minute` flag on every revision row — including
        the sequence-1 row at submission — is true if and only if the gap
        between `bid_due_at` and the row's `revised_at` is at most 60 minutes,
        inclusive; a revision recorded with exactly one hour to go is
        last-minute."

        Design: Difficulty/boundary_precision_check/revision_at_exact_deadline_rejected
        """
        pkg, sub = _publish_with_one_bidder("Deadline Package")
        bid = submit_bid(pkg["id"], sub["id"], 1_000_000)
        v1 = bid["version"]

        advance_clock("2026-08-10T13:59:00Z")  # one minute before the deadline
        resp = api_client.create_bid_revision(
            bid["id"], {"new_base_bid_cents": 990_000,
                        "expected_bid_version": v1,
                        "note": "phone-in at 13:59"},
            make_subcontractor_headers(sub["id"]))
        revised = validate_success(resp, expected_status=200)
        assert revised["base_bid_cents"] == 990_000
        assert revised["version"] == v1 + 1

        rows, _ = validate_paginated(
            api_client.list_bid_revisions(bid["id"], LEAD))
        assert len(rows) == 2
        seq2 = [r for r in rows if r["sequence"] == 2][0]
        assert seq2["is_last_minute"] is True, \
            "one minute before the deadline is inside the 60-minute window"
        assert seq2["amount_cents"] == 990_000

    def test_revision_at_exact_deadline_rejected(self):
        """PRD §2.5: "Bid submission and bid revision likewise require the
        logical now to be strictly before `bid_due_at` — the deadline is
        strict, so a submission landing exactly at the deadline instant is
        rejected with `ERR_BID_DEADLINE_PASSED`."

        Design: Difficulty/boundary_precision_check/revision_at_exact_deadline_rejected
        """
        pkg, sub = _publish_with_one_bidder("Deadline Package")
        bid = submit_bid(pkg["id"], sub["id"], 1_000_000)

        advance_clock("2026-08-10T14:00:00Z")  # exactly the deadline instant
        resp = api_client.create_bid_revision(
            bid["id"], {"new_base_bid_cents": 980_000,
                        "expected_bid_version": bid["version"],
                        "note": "too late"},
            make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_BID_DEADLINE_PASSED)
        after = validate_success(api_client.get_bid(bid["id"], LEAD))
        assert after["base_bid_cents"] == 1_000_000
        assert after["version"] == bid["version"]


class TestBidCreatePrequalGate:

    def test_bid_rejected_while_prequal_rejected(self):
        """PRD §3.6: "Six preconditions gate the create, in the cascade order
        of §2.8: ... the caller must hold a prequalification application
        `APPROVED` with `expires_at` still in the future, with lazy expiry
        applied to that check first (`ERR_PREQUAL_NOT_APPROVED`, HTTP 422);
        ..."

        Design: Difficulty/cross_entity_state_dependency/bid_create_requires_current_approved_prequal
        """
        pkg = create_bid_package(name="Gate Package")
        sub = register_subcontractor(legal_name="Gate LLC")
        app = submit_prequal_application(
            sub["id"], declared_annual_revenue_cents=2_500_000_000,
            declared_emr=0.90, declared_bonding_capacity_cents=1_000_000_000)
        decide_application(app["id"], "REJECTED")
        inv = invite(pkg["id"], sub["id"])
        respond_bidding(inv["id"], sub["id"])
        publish_package(pkg["id"])

        resp = api_client.create_bid(
            {"bid_package_id": pkg["id"], "base_bid_cents": 1_000_000,
             "bond_amount_cents": 50_000},
            make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_PREQUAL_NOT_APPROVED)
        assert get_package(pkg["id"])["submitted_bid_count"] == 0, \
            "a rejected bid attempt must leave no residue"

    def test_bid_accepted_after_prequal_approval(self):
        """PRD §3.6: "A submitted bid lands in `SUBMITTED` status with
        `submitted_at` stamped, `version` starting at 1,
        `disqualification_reason` null, and the package's
        `submitted_bid_count` incremented by 1."
        PRD §3.2: "A rejected application may be resubmitted by the firm with
        fresh declared figures; resubmission moves it `REJECTED → SUBMITTED`
        (subject to the window-overlap gate above), recomputes
        `self_reported_score` from the new inputs, and clears every
        `verified_*` field and the `verified_score` back to null."

        Design: Difficulty/cross_entity_state_dependency/bid_create_requires_current_approved_prequal
        """
        pkg = create_bid_package(name="Gate Package")
        sub = register_subcontractor(legal_name="Gate LLC")
        app = submit_prequal_application(
            sub["id"], declared_annual_revenue_cents=2_500_000_000,
            declared_emr=0.90, declared_bonding_capacity_cents=1_000_000_000)
        decide_application(app["id"], "REJECTED")
        inv = invite(pkg["id"], sub["id"])
        respond_bidding(inv["id"], sub["id"])
        publish_package(pkg["id"])

        resp = api_client.resubmit_prequal_application(
            app["id"],
            {"declared_annual_revenue_cents": 3_000_000_000,
             "declared_emr": 0.80,
             "declared_bonding_capacity_cents": 1_500_000_000},
            make_subcontractor_headers(sub["id"]))
        assert validate_success(resp)["status"] == "SUBMITTED"
        approve_application(app["id"])

        resp = api_client.create_bid(
            {"bid_package_id": pkg["id"], "base_bid_cents": 1_000_000,
             "bond_amount_cents": 50_000},
            make_subcontractor_headers(sub["id"]))
        bid = validate_success(resp, expected_status=201)
        assert bid["status"] == "SUBMITTED"
        assert get_package(pkg["id"])["submitted_bid_count"] == 1


class TestBidCreatePriorityPairs:

    def test_state_gate_beats_bond_sufficiency(self):
        """PRD §2.8: "Then state gates (priority 5): ... bid-write, plan-room,
        and reconsider operations that require a `PUBLISHED` package surface
        `ERR_PACKAGE_NOT_ACCEPTING_BIDS`; ..."
        PRD §2.8: "Deadline gates are priority 8, and bid-bond sufficiency is
        priority 9."
        PRD §3.6: "Six preconditions gate the create, in the cascade order of
        §2.8: the package must be `PUBLISHED` (`ERR_PACKAGE_NOT_ACCEPTING_BIDS`);
        ..."

        Design: Difficulty/priority_pair_validation_conflict/bid_create_state_vs_fiscal_priority
        """
        ctx = setup_published_with_bidders(n=1, name="Priority Package")
        pkg, sub = ctx["package"], ctx["bidders"][0]["subcontractor"]
        advance_clock("2026-08-10T15:00:00Z")
        close_bidding(pkg["id"])
        # The payload also under-covers the bond (required 100_000 > 50_000).
        resp = api_client.create_bid(
            {"bid_package_id": pkg["id"], "base_bid_cents": 2_000_000,
             "bond_amount_cents": 50_000},
            make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_ACCEPTING_BIDS)

    def test_failed_create_leaves_no_partial_write(self):
        """PRD §3.6: "Six preconditions gate the create, in the cascade order
        of §2.8: the package must be `PUBLISHED` (`ERR_PACKAGE_NOT_ACCEPTING_BIDS`);
        ..."
        PRD §1: "counters such as `submitted_bid_count` and
        `issued_addendum_count`, derived flags such as `addendum_ack_complete`,
        and a subcontractor's `current_prequal_status` are recomputed at the
        moment the underlying event occurs, never by a background job."

        Design: Difficulty/priority_pair_validation_conflict/bid_create_state_vs_fiscal_priority
        """
        ctx = setup_published_with_bidders(n=1, name="Priority Package")
        pkg, sub = ctx["package"], ctx["bidders"][0]["subcontractor"]
        advance_clock("2026-08-10T15:00:00Z")
        close_bidding(pkg["id"])
        resp = api_client.create_bid(
            {"bid_package_id": pkg["id"], "base_bid_cents": 2_000_000,
             "bond_amount_cents": 50_000},
            make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_ACCEPTING_BIDS)
        assert get_package(pkg["id"])["submitted_bid_count"] == 0
        rows, meta = validate_paginated(
            api_client.list_bids(LEAD, params={"bid_package_id": pkg["id"]}))
        assert rows == [] and meta["total_count"] == 0

    def test_prequal_gate_beats_deadline_gate(self):
        """PRD §2.8: "Business-safety gates follow (priority 6): the
        prequalification gate on bid creation (`ERR_PREQUAL_NOT_APPROVED`) and
        the segregation-of-duties gate on award decisions (`ERR_SOD_VIOLATION`,
        HTTP 403)."
        PRD §2.8: "Deadline gates are priority 8, and bid-bond sufficiency is
        priority 9."

        Design: Difficulty/priority_pair_validation_conflict/bid_create_safety_vs_temporal_priority
        """
        pkg = create_bid_package(name="Priority Package 2")
        sub = register_subcontractor(legal_name="Prio Two LLC")
        app = submit_prequal_application(
            sub["id"], declared_annual_revenue_cents=2_500_000_000,
            declared_emr=0.90, declared_bonding_capacity_cents=1_000_000_000)
        decide_application(app["id"], "REJECTED",
                           review_notes="insufficient bonding")
        inv = invite(pkg["id"], sub["id"])
        respond_bidding(inv["id"], sub["id"])
        publish_package(pkg["id"])
        advance_clock("2026-08-11T00:00:00Z")  # past the deadline, not closed

        resp = api_client.create_bid(
            {"bid_package_id": pkg["id"], "base_bid_cents": 1_000_000,
             "bond_amount_cents": 50_000},
            make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_PREQUAL_NOT_APPROVED)

    def test_prequal_gate_beats_deadline_gate_for_pending_application(self):
        """PRD §3.6: "Six preconditions gate the create, in the cascade order
        of §2.8: ... the caller must hold a prequalification application
        `APPROVED` with `expires_at` still in the future, with lazy expiry
        applied to that check first (`ERR_PREQUAL_NOT_APPROVED`, HTTP 422);
        the logical now must be strictly before `bid_due_at`
        (`ERR_BID_DEADLINE_PASSED`); ..."
        PRD §2.8: "Business-safety gates follow (priority 6): the
        prequalification gate on bid creation (`ERR_PREQUAL_NOT_APPROVED`) ..."

        Design: Difficulty/priority_pair_validation_conflict/bid_create_safety_vs_temporal_priority
        """
        pkg = create_bid_package(name="Priority Package 3")
        sub = register_subcontractor(legal_name="Prio Three LLC")
        submit_prequal_application(sub["id"])  # left SUBMITTED, never decided
        inv = invite(pkg["id"], sub["id"])
        respond_bidding(inv["id"], sub["id"])
        publish_package(pkg["id"])
        advance_clock("2026-08-11T00:00:00Z")  # deadline also violated

        resp = api_client.create_bid(
            {"bid_package_id": pkg["id"], "base_bid_cents": 1_000_000,
             "bond_amount_cents": 50_000},
            make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_PREQUAL_NOT_APPROVED)


class TestSubmitWithdrawCounterInvariant:

    def test_submission_increments_submitted_bid_count(self):
        """PRD §3.6: "A submitted bid lands in `SUBMITTED` status with
        `submitted_at` stamped, `version` starting at 1,
        `disqualification_reason` null, and the package's
        `submitted_bid_count` incremented by 1."

        Design: Difficulty/compensating_invariant/bid_submit_withdraw_conserves_submitted_count
        """
        pkg, sub = _publish_with_one_bidder("Counter Package")
        assert pkg["submitted_bid_count"] == 0
        bid = submit_bid(pkg["id"], sub["id"], 1_000_000)
        assert bid["version"] == 1
        assert get_package(pkg["id"])["submitted_bid_count"] == 1

    def test_withdrawal_restores_submitted_bid_count(self):
        """PRD §3.6: "Withdrawal is the bidder's exit: while the package is
        `PUBLISHED`, the owning `Subcontractor` may withdraw its `SUBMITTED`
        bid, moving it to `WITHDRAWN` and decrementing the package's
        `submitted_bid_count` by 1."

        Design: Difficulty/compensating_invariant/bid_submit_withdraw_conserves_submitted_count
        """
        pkg, sub = _publish_with_one_bidder("Counter Package")
        bid = submit_bid(pkg["id"], sub["id"], 1_000_000)
        assert get_package(pkg["id"])["submitted_bid_count"] == 1

        resp = api_client.withdraw_bid(
            bid["id"], make_subcontractor_headers(sub["id"]))
        withdrawn = validate_success(resp, expected_status=200)
        assert withdrawn["status"] == "WITHDRAWN"
        assert get_package(pkg["id"])["submitted_bid_count"] == 0, \
            "submit + withdraw must restore the pre-submission count exactly"


class TestBidCreationGates:

    def test_bid_create_requires_bidding_intent(self):
        """PRD §3.6: "Six preconditions gate the create, in the cascade order
        of §2.8: ... the caller's invitation for the package must be in
        `BIDDING` status (`ERR_INVITATION_NOT_BIDDING`, HTTP 422); ..."

        Design: Corner/validations/bid_create_requires_bidding_intent
        """
        pkg = create_bid_package(name="Intent Package")
        ctx = setup_approved_subcontractor()
        sub = ctx["subcontractor"]
        invite(pkg["id"], sub["id"])  # never responds: stays SENT
        publish_package(pkg["id"])

        resp = api_client.create_bid(
            {"bid_package_id": pkg["id"], "base_bid_cents": 1_000_000,
             "bond_amount_cents": 50_000},
            make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_INVITATION_NOT_BIDDING)
        assert get_package(pkg["id"])["submitted_bid_count"] == 0

    def test_duplicate_invitation_and_duplicate_bid_rejected(self):
        """PRD §3.1: "One invitation may exist per subcontractor per package; a
        second invite to the same firm on the same package is rejected with
        `ERR_DUPLICATE_INVITATION` (HTTP 409)."
        PRD §3.6: "Six preconditions gate the create, in the cascade order of
        §2.8: ... no other non-terminal bid — one still `SUBMITTED` — may exist
        for this package and caller (`ERR_DUPLICATE_BID`, HTTP 409); ..."

        Design: Corner/validations/duplicate_bid_and_duplicate_invitation_rejected
        """
        pkg, sub = _publish_with_one_bidder("Dup Package")
        invs, _ = validate_paginated(
            api_client.list_invitations(
                LEAD, params={"bid_package_id": pkg["id"],
                              "subcontractor_id": sub["id"]}))
        assert len(invs) == 1

        resp = api_client.create_invitation(
            {"bid_package_id": pkg["id"], "subcontractor_id": sub["id"]}, LEAD)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVITATION)

        bid = submit_bid(pkg["id"], sub["id"], 1_000_000)
        resp = api_client.create_bid(
            {"bid_package_id": pkg["id"], "base_bid_cents": 900_000,
             "bond_amount_cents": 50_000},
            make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BID)

        # WITHDRAWN is terminal, so a fresh bid for the same pair is accepted.
        api_client.withdraw_bid(bid["id"], make_subcontractor_headers(sub["id"]))
        resp = api_client.create_bid(
            {"bid_package_id": pkg["id"], "base_bid_cents": 950_000,
             "bond_amount_cents": 50_000},
            make_subcontractor_headers(sub["id"]))
        rebid = validate_success(resp, expected_status=201)
        assert rebid["status"] == "SUBMITTED"
        assert rebid["base_bid_cents"] == 950_000

    def test_close_bidding_before_deadline_rejected(self):
        """PRD §2.5: "Closing bidding runs the opposite inequality: it requires
        the logical now to be at or after `bid_due_at`, and an early attempt is
        rejected with `ERR_BID_DEADLINE_NOT_REACHED` (HTTP 422 in all three
        cases)."
        PRD §3.8: "When the logical now reaches `bid_due_at`, the
        `LeadEstimator` closes bidding, moving the package `PUBLISHED →
        BIDDING_CLOSED`; attempting this before the deadline is
        `ERR_BID_DEADLINE_NOT_REACHED`."

        Design: Corner/validations/close_bidding_before_deadline_rejected
        """
        pkg = create_bid_package(name="Close Package")
        sub = register_subcontractor(legal_name="Close LLC")
        invite(pkg["id"], sub["id"])
        publish_package(pkg["id"])

        advance_clock("2026-08-09T00:00:00Z")
        resp = api_client.close_bidding(pkg["id"], LEAD)
        validate_error(resp, ApiErrorId.ERR_BID_DEADLINE_NOT_REACHED)
        assert get_package(pkg["id"])["status"] == "PUBLISHED"

        # The boundary is inclusive: at exactly bid_due_at the close succeeds.
        advance_clock("2026-08-10T14:00:00Z")
        resp = api_client.close_bidding(pkg["id"], LEAD)
        assert validate_success(resp)["status"] == "BIDDING_CLOSED"


class TestWithdrawnBidLockdown:

    def test_withdrawn_bid_rejects_revision_and_second_withdrawal(self):
        """PRD §3.6: "Revision or withdrawal against a bid that has reached a
        terminal state (`AWARDED`, `NOT_AWARDED`, `DISQUALIFIED`, `WITHDRAWN`)
        is rejected with `ERR_BID_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/withdrawn_bid_terminal_lockdown
        """
        pkg, sub = _publish_with_one_bidder("Withdraw Package")
        bid = submit_bid(pkg["id"], sub["id"], 1_000_000)
        api_client.withdraw_bid(bid["id"], make_subcontractor_headers(sub["id"]))

        resp = api_client.create_bid_revision(
            bid["id"], {"new_base_bid_cents": 900_000,
                        "expected_bid_version": bid["version"]},
            make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_BID_INVALID_STATE)

        resp = api_client.withdraw_bid(
            bid["id"], make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_BID_INVALID_STATE)


class TestBidRevisionAuditShape:

    def test_initial_revision_row_is_append_only_sequence_one(self):
        """PRD §2.4: "A `BidRevision` is an append-only audit record: it
        carries only `id` and `created_at` from the common set, and both
        `updated_at` and `version` are absent from it."
        PRD §3.6: "Creation also writes the first row of the bid's revision
        audit trail: a **bid revision** with `sequence` 1, carrying the original
        `base_bid_cents` as its `amount_cents`, its `revised_at` stamped at the
        logical now, and its `is_last_minute` flag computed."
        PRD §3.6: "The `is_last_minute` flag on every revision row — including
        the sequence-1 row at submission — is true if and only if the gap
        between `bid_due_at` and the row's `revised_at` is at most 60 minutes,
        inclusive; a revision recorded with exactly one hour to go is
        last-minute."

        Design: Corner/entities/bid_revision_immutability_shape
        """
        pkg, sub = _publish_with_one_bidder("Immutable Package")
        bid = submit_bid(pkg["id"], sub["id"], 1_000_000)

        rows, meta = validate_paginated(
            api_client.list_bid_revisions(bid["id"], LEAD))
        assert meta["total_count"] == 1 and len(rows) == 1
        row = rows[0]
        assert_bid_revision(row)
        assert row["sequence"] == 1
        assert row["amount_cents"] == 1_000_000
        # Submitted at the default clock 2026-08-01, due 2026-08-10: far
        # outside the 60-minute window.
        assert row["is_last_minute"] is False


class TestBidRevisionOcc:

    def test_fresh_revision_then_stale_revision_rejected(self):
        """PRD §2.7: "A bid revision request must carry `expected_bid_version`
        equal to the bid's current `version` as the caller last observed it. If
        the bid's `version` has advanced since that observation — because an
        earlier revision was recorded against it — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the caller from overwriting
        a bid state it has not seen. A successful revision increments the bid's
        `version` by 1."

        Design: Corner/cross_cutting_layers/occ_bid_revision_stale_version
        """
        pkg, sub = _publish_with_one_bidder("OCC Package")
        bid = submit_bid(pkg["id"], sub["id"], 1_000_000)
        v1 = bid["version"]

        resp = api_client.create_bid_revision(
            bid["id"], {"new_base_bid_cents": 990_000,
                        "expected_bid_version": v1},
            make_subcontractor_headers(sub["id"]))
        revised = validate_success(resp, expected_status=200)
        assert revised["base_bid_cents"] == 990_000
        assert revised["version"] == v1 + 1

        resp = api_client.create_bid_revision(
            bid["id"], {"new_base_bid_cents": 980_000,
                        "expected_bid_version": v1},
            make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        after = validate_success(api_client.get_bid(bid["id"], LEAD))
        assert after["base_bid_cents"] == 990_000, \
            "the stale revision must not overwrite the newer amount"
        rows, _ = validate_paginated(
            api_client.list_bid_revisions(bid["id"], LEAD))
        assert len(rows) == 2, "initial row plus one accepted revision only"


class TestDefaultClock:

    def test_default_clock_stamps_writes_before_any_set(self):
        """PRD §1: "the system runs on a **logical clock** — not
        wall-clock time — so that bid deadlines, prequalification expiry windows, and last-minute
        revision flags are fully deterministic; before any test-driving call
        advances it, the logical clock reads exactly `2026-08-01T00:00:00Z` and
        never falls back to wall-clock time."
        PRD §2.5: "All temporal rules — the bid deadline, the 365-day
        prequalification validity window, the 60-minute last-minute revision
        window, the `responded_at`, `submitted_at`, `acknowledged_at`,
        `sent_at`, `decided_at`, `approved_at`, and `issued_at` stamps — read
        the logical clock, which starts at exactly `2026-08-01T00:00:00Z`
        before any test-driving call."

        Design: Corner/cross_cutting_layers/default_clock_before_any_set
        """
        # No clock call is ever made in this test.
        pkg = create_bid_package(name="Clock Package")
        ctx = setup_approved_subcontractor()
        sub, app = ctx["subcontractor"], ctx["application"]
        inv = invite(pkg["id"], sub["id"])
        respond_bidding(inv["id"], sub["id"])
        publish_package(pkg["id"])

        bid = submit_bid(pkg["id"], sub["id"], 1_000_000)
        assert_timestamp_equals(bid["submitted_at"], "2026-08-01T00:00:00Z")
        assert_timestamp_equals(app["approved_at"], "2026-08-01T00:00:00Z")
