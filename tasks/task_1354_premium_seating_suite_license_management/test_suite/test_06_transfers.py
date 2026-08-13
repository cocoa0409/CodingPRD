"""Transfer and sublease requests: fee formula, review loop, completion branches."""
from test_helpers import (
    FIN, REP,
    ApiClient, ApiErrorId,
    get_single_invoice, list_invoice_rows, make_account_holder_headers,
    make_active_account, make_executed_agreement, make_season, make_suite, make_venue,
    pay_invoice_in_full, pay_transfer_fee, set_clock, setup_active_agreement,
    setup_transfer, validate_error, validate_paginated, validate_success,
)

GOLD_SUITE = dict(suite_code="G-101", tier="GOLD", capacity_seats=20,
                  base_annual_fee_cents=12000000, f_b_minimum_cents=4000000)


class TestTransferFeeComputation:
    def test_transfer_fee_frozen_across_review_loops(self, api: ApiClient):
        """PRD §3.9: "Review begins when a rep or admin moves `SUBMITTED` to
        `UNDER_REVIEW`, at which moment the `transfer_fee_cents` is computed once and
        frozen on the request." and "The review loop itself is unbounded".
        Design: Corner/state_machines/transfer_fee_frozen_across_review_loops
        """
        s = setup_active_agreement(num_seasons=2, execute_clock="2026-08-20T00:00:00Z",
                                   agreement_over=dict(term_seasons=2))
        buyer = make_active_account()
        tr = setup_transfer(s["agreement"], s["account"], buyer,
                            walk_to="UNDER_REVIEW", asking_price_cents=9000000)
        # Schedule [12000000, 12360000]; index 1 of 2 -> elapsed 0.5 -> 6% tier.
        assert tr["transfer_fee_cents"] == 741600, (
            f"6% of remaining 12360000 expected, got {tr['transfer_fee_cents']}")
        validate_success(api.set_transfer_status(
            tr["id"], {"target_status": "INFO_REQUESTED"}, REP))
        back = validate_success(api.set_transfer_status(
            tr["id"], {"target_status": "UNDER_REVIEW"},
            make_account_holder_headers(s["account"]["id"])))
        assert back["transfer_fee_cents"] == 741600, (
            "re-entry into UNDER_REVIEW must not recompute the frozen fee")

    def test_transfer_fee_tier_boundary_quarter_term(self, api: ApiClient):
        """PRD §3.9: "the percentage applied to the agreement's remaining value ... is
        ten percent when the fraction is below 0.25, six percent when it is at least
        0.25 and below 0.75, and three percent when it is at least 0.75; a fraction of
        exactly 0.25 therefore prices at six percent and exactly 0.75 at three
        percent."
        Design: Corner/calculations/transfer_fee_tier_boundary_quarter_term
        """
        s = setup_active_agreement(num_seasons=1, execute_clock="2026-08-20T00:00:00Z",
                                   agreement_over=dict(term_seasons=4))
        buyer = make_active_account()
        tr = setup_transfer(s["agreement"], s["account"], buyer,
                            walk_to="UNDER_REVIEW", asking_price_cents=20000000)
        # Schedule [12000000, 12360000, 12730800, 13112724]; index 1 of 4 -> exactly
        # 0.25 -> 6% tier; remaining 38203524 -> round_half_up(2292211.44).
        assert tr["transfer_fee_cents"] == 2292211, (
            f"exactly 0.25 selects the 6% tier, got {tr['transfer_fee_cents']}")

    def test_transfer_second_pending_request_rejected(self, api: ApiClient):
        """PRD §3.9: "only one transfer per agreement may be in flight — a second
        request while one sits in `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED`, or
        `APPROVED` is rejected with `ERR_TRANSFER_ALREADY_PENDING`."
        Design: Corner/validations/transfer_second_pending_request_rejected
        """
        s = setup_active_agreement(num_seasons=1)
        buyer = make_active_account()
        third = make_active_account()
        setup_transfer(s["agreement"], s["account"], buyer, walk_to="UNDER_REVIEW")
        resp = api.create_transfer_request(
            {"agreement_id": s["agreement"]["id"], "from_account_id": s["account"]["id"],
             "to_account_id": third["id"], "transfer_type": "SALE_TRANSFER",
             "asking_price_cents": 9500000},
            make_account_holder_headers(s["account"]["id"]))
        validate_error(resp, ApiErrorId.ERR_TRANSFER_ALREADY_PENDING)
        rows = validate_paginated(api.list_transfer_requests(
            REP, params={"agreement_id": s["agreement"]["id"]}))[0]
        assert len(rows) == 1, "no second TransferRequest may persist"


class TestTransferCompletion:
    def test_transfer_complete_spawns_successor_agreement(self, api: ApiClient):
        """PRD §3.9: "A `SALE_TRANSFER` drives the agreement to `TRANSFERRED`, spawning
        the successor `ACTIVE` agreement described in §3.3 — transferee account, same
        suite, remaining covered seasons, the tail of the original fee schedule,
        unchanged food-and-beverage minimum, execution stamped at the clock — while the
        suite remains `LICENSED` and points at the successor."
        Design: Corner/state_machines/transfer_complete_spawns_successor_agreement
        """
        s = setup_active_agreement(num_seasons=2, execute_clock="2026-08-20T00:00:00Z",
                                   agreement_over=dict(term_seasons=2))
        buyer = make_active_account()
        tr = setup_transfer(s["agreement"], s["account"], buyer, walk_to="APPROVED",
                            asking_price_cents=9000000)
        pay_transfer_fee(tr, s["account"])  # completion gate: TRANSFER_FEE PAID
        done = validate_success(api.complete_transfer(tr["id"], REP))
        assert done["status"] == "COMPLETED"
        original = validate_success(api.get_agreement(s["agreement"]["id"], REP))
        assert original["status"] == "TRANSFERRED"
        rows = validate_paginated(api.list_agreements(
            REP, params={"account_id": buyer["id"], "status": "ACTIVE"}))[0]
        assert len(rows) == 1
        successor = rows[0]
        assert successor["suite_id"] == s["suite"]["id"]
        assert successor["fee_schedule_cents"] == [12360000], (
            "the remaining tail of the original schedule (season 2)")
        assert successor["f_b_minimum_cents"] == 4000000
        suite = validate_success(api.get_suite(s["suite"]["id"], REP))
        assert suite["status"] == "LICENSED"
        assert suite["current_agreement_id"] == successor["id"], "no AVAILABLE interlude"

    def test_transfer_sublease_complete_keeps_agreement_active(self, api: ApiClient):
        """PRD §3.9: "A `SUBLEASE` leaves the agreement `ACTIVE` and simply records the
        sublessee by setting the agreement's `active_sublease_account_id` to the
        `to_account_id`." and "For a `SUBLEASE`, the fee is the greater of the same
        50,000-cent flat minimum and five percent of `asking_price_cents` rounded
        half-up."
        Design: Corner/state_machines/transfer_sublease_complete_keeps_agreement_active
        """
        s = setup_active_agreement(num_seasons=1)
        sub = make_active_account(legal_name="Sub Co")
        tr = setup_transfer(s["agreement"], s["account"], sub, walk_to="APPROVED",
                            transfer_type="SUBLEASE", asking_price_cents=8000000)
        assert tr["transfer_fee_cents"] == 400000, "5% of asking 8000000, above the floor"
        pay_transfer_fee(tr, s["account"])
        done = validate_success(api.complete_transfer(tr["id"], REP))
        assert done["status"] == "COMPLETED"
        agreement = validate_success(api.get_agreement(s["agreement"]["id"], REP))
        assert agreement["status"] == "ACTIVE"
        assert agreement["account_id"] == s["account"]["id"]
        assert agreement["active_sublease_account_id"] == sub["id"]
        suite = validate_success(api.get_suite(s["suite"]["id"], REP))
        assert suite["status"] == "LICENSED"
        assert suite["current_agreement_id"] == s["agreement"]["id"], (
            "no successor agreement is created for a SUBLEASE")
