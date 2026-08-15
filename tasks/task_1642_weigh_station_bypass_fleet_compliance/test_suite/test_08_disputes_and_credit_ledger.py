"""Dispute intake rules, the appeal cycle under segregation of duties, and
the credit ledger with its invoice auto-apply cascade."""
from test_helpers import (
    FINANCE,
    ApiErrorId,
    assert_credit_ledger_invariant,
    close_period,
    get_carrier,
    make_compliance_officer_headers,
    open_dispute,
    post_event,
    set_clock,
    setup_bypass_ready,
    setup_carrier_past_due,
    setup_pull_in_event,
    validate_error,
    validate_success,
)


def _open_dispute_on_pull_in(api, claimed_credit_cents=5000,
                             reason="WIM calibration certificate on file"):
    """Bypass-ready fixture with one OVERWEIGHT PULL_IN event and an OPENED
    dispute against it."""
    fx = setup_pull_in_event(approach_at="2026-08-02T10:00:00Z",
                             clock="2026-08-02T12:00:00Z")
    dispute = open_dispute(fx["event"]["id"], fx["carrier"]["id"],
                           claimed_credit_cents=claimed_credit_cents,
                           reason=reason)
    return fx, dispute


class TestDisputeIntake:
    def test_dispute_window_30_days_inclusive(self, api):
        """PRD §3.6: "the filing must come within thirty days of the
        approach, meaning the difference between today and the approach's
        calendar date may not exceed 30, or the open fails with
        `ERR_DISPUTE_WINDOW_EXPIRED` (HTTP 422)."

        Design: Corner/validations/dispute_window_boundary_30_vs_31_days
        """
        fx = setup_bypass_ready()
        set_clock("2026-08-02T12:00:00Z")
        ev1 = post_event(fx["vehicle"]["id"], fx["station"]["id"],
                         "2026-08-02T10:00:00Z", measured_weight_lbs=90000,
                         credentials_presented=["IFTA", "IRP", "UCR"])
        ev2 = post_event(fx["vehicle"]["id"], fx["station"]["id"],
                         "2026-08-02T11:00:00Z", measured_weight_lbs=90000,
                         credentials_presented=["IFTA", "IRP", "UCR"])
        assert ev1["decision"] == "PULL_IN" and ev2["decision"] == "PULL_IN"
        cm = fx["cm_headers"]

        set_clock("2026-09-01T00:00:00Z")
        day30 = validate_success(api.create_dispute(
            {"bypass_event_id": ev1["id"], "reason": "day-30 dispute",
             "claimed_credit_cents": 1000}, cm), expected_status=201)
        assert day30["status"] == "OPENED", "age exactly 30 days is within the window"

        set_clock("2026-09-02T00:00:00Z")
        day31 = api.create_dispute(
            {"bypass_event_id": ev2["id"], "reason": "day-31 dispute",
             "claimed_credit_cents": 1000}, cm)
        validate_error(day31, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED)

    def test_dispute_on_granted_event_rejected(self, api):
        """PRD §3.6: "the event's `decision` must be `PULL_IN` — a
        `BYPASS_GRANTED` event has nothing to dispute and draws
        `ERR_EVENT_NOT_DISPUTABLE` (HTTP 422)"

        Design: Corner/validations/dispute_on_granted_event_returns_422
        """
        fx = setup_bypass_ready()
        set_clock("2026-08-05T12:00:00Z")
        grant = post_event(fx["vehicle"]["id"], fx["station"]["id"],
                           "2026-08-05T10:00:00Z", measured_weight_lbs=80000,
                           credentials_presented=["IFTA", "IRP", "UCR"])
        assert grant["decision"] == "BYPASS_GRANTED"
        resp = api.create_dispute(
            {"bypass_event_id": grant["id"], "reason": "disputing a grant",
             "claimed_credit_cents": 500}, fx["cm_headers"])
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_DISPUTABLE)

    def test_second_open_dispute_per_event_rejected(self, api):
        """PRD §2.6: "A bypass event may have at most one dispute whose
        status is `OPENED`, `UPHELD`, or `APPEALED`
        (`ERR_DISPUTE_ALREADY_OPEN`)."

        Design: Corner/validations/dispute_second_open_returns_409
        """
        fx, _first = _open_dispute_on_pull_in(api, claimed_credit_cents=1000)
        resp = api.create_dispute(
            {"bypass_event_id": fx["event"]["id"], "reason": "second dispute",
             "claimed_credit_cents": 2000}, fx["cm_headers"])
        validate_error(resp, ApiErrorId.ERR_DISPUTE_ALREADY_OPEN)


class TestAppealCycle:
    def test_appeal_requires_a_different_officer(self, api):
        """PRD §3.6: "Segregation of duties governs that review — the
        officer adjudicating an appealed dispute must not be the officer
        recorded as `first_reviewer_id`, and a self-review is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.6: "A carrier that loses may appeal: from `UPHELD`, the
        `CarrierManager` moves the dispute to `APPEALED` for a second
        review."

        Design: Difficulty/non_linear_state_machine/dispute_appeal_cycle_with_sod
        """
        fx, dispute = _open_dispute_on_pull_in(api)
        officer_a = make_compliance_officer_headers("officer-a")

        upheld = validate_success(api.adjudicate_dispute(
            dispute["id"], {"outcome": "UPHELD"}, officer_a))
        assert upheld["status"] == "UPHELD"
        assert upheld["first_reviewer_id"] == "officer-a", \
            "the first adjudication records the officer's identity"
        assert upheld["adjudicated_at"]

        appealed = validate_success(api.appeal_dispute(dispute["id"],
                                                       fx["cm_headers"]))
        assert appealed["status"] == "APPEALED"

        self_review = api.adjudicate_dispute(
            dispute["id"], {"outcome": "OVERTURNED", "credit_amount_cents": 2000},
            officer_a)
        validate_error(self_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        still = validate_success(api.get_dispute(dispute["id"], FINANCE))
        assert still["status"] == "APPEALED", "the rejected review changed nothing"

    def test_second_officer_overturn_grants_credit(self, api):
        """PRD §3.6: "From `APPEALED`, an outcome of `UPHELD` ends the matter
        at `UPHELD_FINAL`; an outcome of `OVERTURNED` applies the same
        credit-bounds check and the same ledger and auto-apply cascade as a
        first-instance overturn."
        PRD §3.6: "The granted amount enters the carrier's `credit_ledger` as
        a positive entry with reason `DISPUTE_OVERTURN_CREDIT` referencing
        the dispute"
        PRD §3.6: "The second reviewer is recorded as `appeal_reviewer_id`"

        Design: Difficulty/non_linear_state_machine/dispute_appeal_cycle_with_sod
        """
        fx, dispute = _open_dispute_on_pull_in(api)
        officer_a = make_compliance_officer_headers("officer-a")
        officer_b = make_compliance_officer_headers("officer-b")
        validate_success(api.adjudicate_dispute(dispute["id"],
                                                {"outcome": "UPHELD"}, officer_a))
        validate_success(api.appeal_dispute(dispute["id"], fx["cm_headers"]))

        overturned = validate_success(api.adjudicate_dispute(
            dispute["id"], {"outcome": "OVERTURNED", "credit_amount_cents": 2000},
            officer_b))
        assert overturned["status"] == "OVERTURNED"
        assert overturned["granted_credit_cents"] == 2000
        assert overturned["appeal_reviewer_id"] == "officer-b"

        carrier = get_carrier(fx["carrier"]["id"])
        assert carrier["credit_balance_cents"] == 2000, \
            "no unpaid invoices exist, so the grant settles on the ledger"
        assert len(carrier["credit_ledger"]) == 1
        entry = carrier["credit_ledger"][0]
        assert entry["amount_cents"] == 2000
        assert entry["reason"] == "DISPUTE_OVERTURN_CREDIT"
        assert entry["reference_id"] == dispute["id"]
        assert_credit_ledger_invariant(carrier)


class TestCreditAutoApplyCascade:
    def _past_due_dispute(self, api):
        """Carrier with a PAST_DUE invoice (due 1799) and an OPENED dispute
        claiming 5000 on a fresh OVERWEIGHT pull-in."""
        fx = setup_carrier_past_due()
        set_clock("2026-09-16T12:00:00Z")
        event = post_event(fx["vehicle"]["id"], fx["station"]["id"],
                           "2026-09-16T10:00:00Z", measured_weight_lbs=90000,
                           credentials_presented=["IFTA", "IRP", "UCR"])
        assert event["decision"] == "PULL_IN"
        dispute = open_dispute(event["id"], fx["carrier"]["id"],
                               claimed_credit_cents=5000,
                               reason="scale miscalibrated")
        return fx, dispute

    def test_overturn_autoapplies_credit_to_past_due_invoice(self, api):
        """PRD §3.6: "That sweep then applies the new credit to money owed:
        it walks the carrier's unpaid invoices — those in `ISSUED` or
        `PAST_DUE` — oldest first by `issued_at`, ties broken by creation
        order, and while the balance covers an invoice's full
        `amount_due_cents` it appends a negative ledger entry of exactly that
        amount with reason `INVOICE_CREDIT_APPLICATION` referencing the
        invoice, marks the invoice `PAID`, and recomputes the balance before
        considering the next."

        Design: Difficulty/transitive_cascade/dispute_overturn_credit_autoapply_cascade
        """
        fx, dispute = self._past_due_dispute(api)
        officer = make_compliance_officer_headers("officer-a")
        decided = validate_success(api.adjudicate_dispute(
            dispute["id"], {"outcome": "OVERTURNED", "credit_amount_cents": 3000},
            officer))
        assert decided["status"] == "OVERTURNED"
        assert decided["granted_credit_cents"] == 3000

        carrier = get_carrier(fx["carrier"]["id"])
        assert carrier["credit_balance_cents"] == 1201, "3000 granted minus 1799 applied"
        ledger = carrier["credit_ledger"]
        assert len(ledger) == 2
        assert ledger[0]["amount_cents"] == 3000
        assert ledger[0]["reason"] == "DISPUTE_OVERTURN_CREDIT"
        assert ledger[0]["reference_id"] == dispute["id"]
        assert ledger[1]["amount_cents"] == -1799
        assert ledger[1]["reason"] == "INVOICE_CREDIT_APPLICATION"
        assert ledger[1]["reference_id"] == fx["invoice"]["id"]
        assert_credit_ledger_invariant(carrier)

        invoice = validate_success(api.get_invoice(fx["invoice"]["id"], FINANCE))
        assert invoice["status"] == "PAID", \
            "full coverage marks the invoice PAID without any payment call"

    def test_standing_recovers_after_credit_sweep(self, api):
        """PRD §3.6: "When the sweep ends and no `PAST_DUE` invoices remain,
        the carrier's subscriptions recover from `PAST_DUE` standing back to
        `CURRENT`."

        Design: Difficulty/transitive_cascade/dispute_overturn_credit_autoapply_cascade
        """
        fx, dispute = self._past_due_dispute(api)
        sub = validate_success(api.get_subscription(fx["subscription"]["id"],
                                                    FINANCE))
        assert sub["payment_standing"] == "PAST_DUE"

        officer = make_compliance_officer_headers("officer-a")
        validate_success(api.adjudicate_dispute(
            dispute["id"], {"outcome": "OVERTURNED", "credit_amount_cents": 3000},
            officer))
        sub = validate_success(api.get_subscription(fx["subscription"]["id"],
                                                    FINANCE))
        assert sub["payment_standing"] == "CURRENT", \
            "the last PAST_DUE invoice was cleared by the credit sweep"
        invoice = validate_success(api.get_invoice(fx["invoice"]["id"], FINANCE))
        assert invoice["status"] == "PAID"


class TestCreditLedgerConservation:
    def _two_overturned_disputes(self, api):
        """Two PULL_IN events, two disputes, both overturned with explicit
        credits 3000 and 1500; no invoices exist yet."""
        fx = setup_bypass_ready()
        set_clock("2026-08-03T12:00:00Z")
        ev1 = post_event(fx["vehicle"]["id"], fx["station"]["id"],
                         "2026-08-03T10:00:00Z", measured_weight_lbs=90000,
                         credentials_presented=["IFTA", "IRP", "UCR"])
        ev2 = post_event(fx["vehicle"]["id"], fx["station"]["id"],
                         "2026-08-03T11:00:00Z", measured_weight_lbs=90000,
                         credentials_presented=["IFTA", "IRP", "UCR"])
        d1 = open_dispute(ev1["id"], fx["carrier"]["id"],
                          claimed_credit_cents=4000,
                          reason="first overweight dispute")
        d2 = open_dispute(ev2["id"], fx["carrier"]["id"],
                          claimed_credit_cents=2000,
                          reason="second overweight dispute")
        officer = make_compliance_officer_headers("officer-a")
        validate_success(api.adjudicate_dispute(
            d1["id"], {"outcome": "OVERTURNED", "credit_amount_cents": 3000},
            officer))
        validate_success(api.adjudicate_dispute(
            d2["id"], {"outcome": "OVERTURNED", "credit_amount_cents": 1500},
            officer))
        return fx

    def test_grants_accumulate_on_append_only_ledger(self, api):
        """PRD §2.8: "The carrier's `credit_balance_cents` is, by invariant,
        exactly the sum of `amount_cents` over all ledger entries, and it is
        recomputed from the ledger after every append — never incrementally
        adjusted — so the balance observed at any instant always equals the
        ledger sum."
        PRD §3.6: "The granted amount enters the carrier's `credit_ledger` as
        a positive entry with reason `DISPUTE_OVERTURN_CREDIT` referencing
        the dispute"

        Design: Difficulty/compensating_invariant/credit_ledger_sum_conservation
        """
        fx = self._two_overturned_disputes(api)
        carrier = get_carrier(fx["carrier"]["id"])
        assert carrier["credit_balance_cents"] == 4500
        ledger = carrier["credit_ledger"]
        assert [e["amount_cents"] for e in ledger] == [3000, 1500]
        assert all(e["reason"] == "DISPUTE_OVERTURN_CREDIT" for e in ledger)
        assert_credit_ledger_invariant(carrier)

    def test_close_applies_credit_and_zero_due_invoice_is_born_paid(self, api):
        """PRD §3.8: "`credit_applied_cents` is the smaller of the carrier's
        `credit_balance_cents` and the gross; when positive, a negative
        ledger entry of that amount with reason `INVOICE_CREDIT_APPLICATION`
        is appended per §2.8, and `amount_due_cents` is the gross minus the
        applied credit."
        PRD §3.8: "when the amount due works out to zero because credit
        covered the gross in full, the invoice is born `PAID` instead."
        PRD §2.8: "The carrier's `credit_balance_cents` is, by invariant,
        exactly the sum of `amount_cents` over all ledger entries"

        Design: Difficulty/compensating_invariant/credit_ledger_sum_conservation
        """
        fx = self._two_overturned_disputes(api)
        set_clock("2026-09-01T00:00:00Z")
        invoice = close_period(fx["carrier"]["id"])
        assert invoice["gross_cents"] == 1799
        assert invoice["credit_applied_cents"] == 1799, "min(4500, 1799)"
        assert invoice["amount_due_cents"] == 0
        assert invoice["status"] == "PAID", \
            "born PAID — credit covered the gross in full at close"

        carrier = get_carrier(fx["carrier"]["id"])
        assert carrier["credit_balance_cents"] == 2701, "3000 + 1500 - 1799"
        ledger = carrier["credit_ledger"]
        assert len(ledger) == 3
        assert [e["amount_cents"] for e in ledger] == [3000, 1500, -1799]
        assert ledger[2]["reason"] == "INVOICE_CREDIT_APPLICATION"
        assert ledger[2]["reference_id"] == invoice["id"]
        assert_credit_ledger_invariant(carrier)
