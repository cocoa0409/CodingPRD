"""License payments, refunds, OCC on payments, fee-status rule."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_curator_headers,
    make_ingest_headers,
    make_negotiator_headers,
    make_officer_headers,
    make_payer_headers,
    setup_expired_license,
    setup_license,
    setup_request_in_negotiating,
    validate_error,
    validate_success,
)


class TestOverpayment:
    def test_overpayment_rejected_exact_remaining_accepted(self, api):
        """PRD §3.6: "Overpayment is rejected outright — a payment that would
        push the cumulative paid total above `fee_agreed_cents` fails with
        `ERR_OVERPAYMENT` before any status recomputation runs."

        Design: Corner/validations/overpayment_rejected_at_exact_remaining
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=500000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
        )
        payer = make_payer_headers("fin_c_1")
        get_success_data(
            api.post_payment(
                lic["id"],
                {"amount_cents": 400000, "expected_license_version": lic["version"]},
                payer,
            )
        )
        # Overpay by 1 cent.
        err = api.post_payment(
            lic["id"],
            {"amount_cents": 100001, "expected_license_version": lic["version"] + 1},
            payer,
        )
        validate_error(err, ApiErrorId.ERR_OVERPAYMENT)
        # Exact remaining pays off.
        ok = api.post_payment(
            lic["id"],
            {"amount_cents": 100000, "expected_license_version": lic["version"] + 1},
            payer,
        )
        get_success_data(ok)
        lic_after = get_success_data(api.get_license(lic["id"], payer))
        assert lic_after["fee_status"] == "PAID"


class TestRefundGates:
    def test_refund_on_active_license_rejected(self, api):
        """PRD §3.6: "A refund requires a terminal lifecycle — `EXPIRED` or
        `REVOKED` — and anything else is `ERR_REFUND_REQUIRES_TERMINAL`."

        Design: Corner/validations/refund_requires_terminal_lifecycle
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=200000,
            requested_units=2,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
        )
        payer = make_payer_headers("fin_c_2")
        get_success_data(
            api.post_payment(
                lic["id"],
                {"amount_cents": 200000, "expected_license_version": lic["version"]},
                payer,
            )
        )
        err = api.post_payment(
            lic["id"],
            {"amount_cents": -200000, "expected_license_version": lic["version"] + 1},
            payer,
        )
        validate_error(err, ApiErrorId.ERR_REFUND_REQUIRES_TERMINAL)

    def test_refund_after_use_blocked_by_gross_consumption(self, api):
        """PRD §3.6: "It also requires that nothing was ever used:
        `units_consumed_gross` must be zero, and a license with any posted
        usage, even usage later struck by a takedown remedy, refuses the
        refund with `ERR_REFUND_AFTER_USE`."

        Design: Corner/validations/refund_after_use_blocked_by_gross_consumption
        """
        # Pay + post usage BEFORE expiry, then advance clock past term_end.
        holder, asset, req, lic_active, _rid = setup_license(
            fee_cents=200000,
            requested_units=2,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-08-20T00:00:00Z",
        )
        payer = make_payer_headers("fin_c_3")
        get_success_data(
            api.post_payment(
                lic_active["id"],
                {"amount_cents": 200000, "expected_license_version": lic_active["version"]},
                payer,
            )
        )
        ingest = make_ingest_headers("ing_c_3")
        get_success_data(
            api.post_usage_event(
                lic_active["id"],
                {"units": 1, "used_at": "2026-08-15T00:00:00Z"},
                ingest,
            )
        )
        # Advance clock past term end.
        api.set_clock("2026-08-21T00:00:00Z", make_curator_headers("cur_c_3"))
        lic_now = get_success_data(api.get_license(lic_active["id"], payer))
        err = api.post_payment(
            lic_active["id"],
            {"amount_cents": -200000, "expected_license_version": lic_now["version"]},
            payer,
        )
        validate_error(err, ApiErrorId.ERR_REFUND_AFTER_USE)


class TestSegregationOfDuties:
    def test_requester_cannot_pay_own_license(self, api):
        """PRD §3.6: "Segregation of duties applies here as everywhere: the
        payer's `X-User-ID` must differ from the originating request's
        `requester_id`, else `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/segregation_of_duties_requester_cannot_accept_own_round
        """
        # Use a custom requester id and then post a payment AS that same user id.
        holder, asset, req, lic, rid = setup_license(
            fee_cents=200000,
            requested_units=2,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
        )
        payer_as_requester = make_payer_headers(rid)
        err = api.post_payment(
            lic["id"],
            {"amount_cents": 100, "expected_license_version": lic["version"]},
            payer_as_requester,
        )
        validate_error(err, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_requester_cannot_accept_own_round(self, api):
        """PRD §3.3: "And the accepting operator must not be the person who
        asked for the clearance: the acceptor's `X-User-ID` is compared against
        the request's `requester_id`, and a match is `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/segregation_of_duties_requester_cannot_accept_own_round
        """
        holder, asset, req, rid = setup_request_in_negotiating(
            media="STREAMING",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-11-01T00:00:00Z",
            requested_units=2,
        )
        # Negotiator carrying the same user_id as the requester.
        negotiator_as_requester = make_negotiator_headers(rid)
        err = api.post_round(
            req["id"],
            {"offered_fee_cents": 200000, "accept": True},
            negotiator_as_requester,
        )
        validate_error(err, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestPaymentOnExpiredLicense:
    def test_payment_on_expired_license_rejected(self, api):
        """PRD §3.6: "A positive payment is accepted only while the license's
        `lifecycle` is `ACTIVE`; posting against a suspended, expired, or
        revoked license fails with `ERR_LICENSE_NOT_PAYABLE`."

        Design: Corner/errors/error_license_not_payable_on_expired
        """
        holder, asset, req, lic, _ = setup_expired_license(
            fee_cents=200000,
            requested_units=2,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-08-20T00:00:00Z",
            advance_clock_to="2026-08-21T00:00:00Z",
        )
        payer = make_payer_headers("fin_c_4")
        err = api.post_payment(
            lic["id"],
            {"amount_cents": 200000, "expected_license_version": lic["version"]},
            payer,
        )
        validate_error(err, ApiErrorId.ERR_LICENSE_NOT_PAYABLE)


class TestLicenseParallelDimensions:
    def test_fee_status_and_lifecycle_move_independently(self, api):
        """PRD §3.4: "Two parallel dimensions govern a license from that moment
        on. The **lifecycle** dimension walks `ACTIVE`, `SUSPENDED`, `EXPIRED`,
        and `REVOKED`; the **fee status** dimension walks `UNPAID`,
        `PARTIALLY_PAID`, `PAID`, and `REFUNDED`. Transitions on one dimension
        do not move the other except where this document says so explicitly."

        Design: Difficulty/non_linear_state_machine/license_parallel_dimensions_fee_x_lifecycle
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=500000,
            requested_units=10,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-08-20T00:00:00Z",
            permitted_media=["BROADCAST_TV"],
            media="BROADCAST_TV",
        )
        payer = make_payer_headers("fin_par_1")
        # Partial payment: fee axis moves, lifecycle stays ACTIVE.
        get_success_data(
            api.post_payment(
                lic["id"],
                {"amount_cents": 200000, "expected_license_version": lic["version"]},
                payer,
            )
        )
        mid = get_success_data(api.get_license(lic["id"], payer))
        assert mid["lifecycle"] == "ACTIVE"
        assert mid["fee_status"] == "PARTIALLY_PAID"

        # Advance clock past term end: lifecycle moves, fee axis stays PARTIALLY_PAID.
        api.set_clock("2026-08-21T00:00:00Z", make_curator_headers("cur_par_1"))
        after = get_success_data(api.get_license(lic["id"], payer))
        assert after["lifecycle"] == "EXPIRED"
        assert after["fee_status"] == "PARTIALLY_PAID"

    def test_refund_on_terminal_license_moves_fee_status_only(self, api):
        """PRD §3.6: "From `PARTIALLY_PAID`, the refund must exactly cancel
        the cumulative amount paid to date."
        PRD §3.4: "`EXPIRED` and `REVOKED` are the terminal lifecycle states —
        though even a terminal license's fee status may still move to
        `REFUNDED` through the compensation path of §3.6."

        Design: Difficulty/non_linear_state_machine/license_parallel_dimensions_fee_x_lifecycle
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=500000,
            requested_units=10,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-08-20T00:00:00Z",
            permitted_media=["BROADCAST_TV"],
            media="BROADCAST_TV",
        )
        payer = make_payer_headers("fin_par_2")
        get_success_data(
            api.post_payment(
                lic["id"],
                {"amount_cents": 200000, "expected_license_version": lic["version"]},
                payer,
            )
        )
        api.set_clock("2026-08-21T00:00:00Z", make_curator_headers("cur_par_2"))
        expired = get_success_data(api.get_license(lic["id"], payer))
        refund = api.post_payment(
            lic["id"],
            {"amount_cents": -200000, "expected_license_version": expired["version"]},
            payer,
        )
        get_success_data(refund)
        final = get_success_data(api.get_license(lic["id"], payer))
        assert final["lifecycle"] == "EXPIRED"
        assert final["fee_status"] == "REFUNDED"
