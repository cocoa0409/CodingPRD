"""Usage reservation quota, draw-down, hold TTL, term bounds."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_certifier_headers,
    make_curator_headers,
    make_ingest_headers,
    make_payer_headers,
    setup_license,
    setup_suspended_license,
    validate_error,
    validate_success,
)


class TestReservationQuota:
    def test_exact_fit_passes_plus_one_fails(self, api):
        """PRD §3.5: "admission requires the requested `units` to be at most
        the units available; requesting exactly the available amount succeeds,
        one more is rejected with `ERR_QUOTA_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/usage_quota_exact_fit_passes_plus_one_fails
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=200000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-12-10T00:00:00Z",
        )
        ingest = make_ingest_headers("ing_q_1")
        ok = api.create_reservation(
            lic["id"],
            {"units": 5, "expected_license_version": lic["version"]},
            ingest,
        )
        ok_data = get_success_data(ok)
        assert ok_data["status"] == "HELD"

        err = api.create_reservation(
            lic["id"],
            {"units": 1, "expected_license_version": lic["version"] + 1},
            ingest,
        )
        validate_error(err, ApiErrorId.ERR_QUOTA_EXCEEDED)


class TestReservationDrawdown:
    def test_partial_consumption_keeps_reservation_held(self, api):
        """PRD §3.5: "the reservation either stays `HELD` with its `units`
        reduced by the event's amount (a partial draw) or, when the event
        exactly empties it, moves to `CONSUMED`."

        Design: Corner/state_machines/partial_consumption_keeps_reservation_held
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=200000,
            requested_units=10,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
        )
        ingest = make_ingest_headers("ing_p_1")
        res = get_success_data(
            api.create_reservation(
                lic["id"],
                {"units": 5, "expected_license_version": lic["version"]},
                ingest,
            )
        )
        event_resp = api.post_usage_event(
            lic["id"],
            {"units": 2, "used_at": "2026-09-01T00:00:00Z", "reservation_id": res["id"]},
            ingest,
        )
        get_success_data(event_resp)
        res_after = get_success_data(api.get_reservation(res["id"], ingest))
        assert res_after["status"] == "HELD"
        assert res_after["units"] == 3

    def test_overdraw_of_reservation_rejected(self, api):
        """PRD §3.5: "the event's `units` must be at most the reservation's
        remaining `units`, with an excess rejected as `ERR_USAGE_OVERDRAW`"

        Design: Corner/state_machines/usage_overdraw_of_reservation_rejected
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=200000,
            requested_units=10,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
        )
        ingest = make_ingest_headers("ing_o_1")
        res = get_success_data(
            api.create_reservation(
                lic["id"],
                {"units": 2, "expected_license_version": lic["version"]},
                ingest,
            )
        )
        err = api.post_usage_event(
            lic["id"],
            {"units": 3, "used_at": "2026-09-01T00:00:00Z", "reservation_id": res["id"]},
            ingest,
        )
        validate_error(err, ApiErrorId.ERR_USAGE_OVERDRAW)


class TestUsageTermBoundary:
    def test_used_at_exactly_term_end_rejected_one_second_inside_passes(self, api):
        """PRD §3.5: "`used_at` must fall inside the license term — on or after
        `term_start_at` and strictly before `term_end_at`, else
        `ERR_USAGE_OUTSIDE_TERM`."

        Design: Corner/state_machines/usage_event_outside_term_rejected
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=200000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
        )
        ingest = make_ingest_headers("ing_t_1")
        err = api.post_usage_event(
            lic["id"],
            {"units": 1, "used_at": "2026-11-10T00:00:00Z"},
            ingest,
        )
        validate_error(err, ApiErrorId.ERR_USAGE_OUTSIDE_TERM)
        ok = api.post_usage_event(
            lic["id"],
            {"units": 1, "used_at": "2026-11-09T23:59:59Z"},
            ingest,
        )
        ok_data = get_success_data(ok)
        assert ok_data["posting_kind"] == "POSTED"


class TestHoldForfeiture:
    def test_held_reservation_forfeited_after_ttl(self, api):
        """PRD §3.5: "Forfeiture is the clock's: when the clock reaches
        `hold_expires_at`, the hold moves to `FORFEITED` and its units return
        to availability."

        Design: Corner/state_machines/hold_forfeit_by_clock_sweep
        """
        # Default clock is 2026-08-01; reservation created then, expires 720h later
        # (2026-08-31T00:00:00Z). License term extends well past that.
        holder, asset, req, lic, _ = setup_license(
            fee_cents=200000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2027-08-10T00:00:00Z",
        )
        ingest = make_ingest_headers("ing_h_1")
        res = get_success_data(
            api.create_reservation(
                lic["id"],
                {"units": 2, "expected_license_version": lic["version"]},
                ingest,
            )
        )
        # Advance past the 30-day hold TTL.
        curator = make_curator_headers("cur_h_1")
        api.set_clock("2026-09-01T00:00:00Z", curator)
        res_after = get_success_data(api.get_reservation(res["id"], ingest))
        assert res_after["status"] == "FORFEITED"
        lic_after = get_success_data(
            api.get_license(lic["id"], make_payer_headers("fin_h_1"))
        )
        assert lic_after["units_reserved"] == 0


class TestUsageOnNonActiveLicense:
    def test_usage_on_suspended_license_rejected(self, api):
        """PRD §3.5: "When a reservation is referenced, the draw-down path
        applies: the license must be `ACTIVE` (`ERR_LICENSE_NOT_ACTIVE`
        otherwise)" and PRD §3.5: "When `reservation_id` is omitted, the event
        is **direct-grant usage**: no reservation bookkeeping applies, but the
        license must still be `ACTIVE` and `used_at` must still fall inside
        the term."

        Design: Corner/state_machines/usage_event_on_suspended_license_rejected
        """
        holder, asset, req, lic, notice, _res = setup_suspended_license(
            fee_cents=200000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
            lapse_to="2026-08-12T00:00:00Z",
        )
        ingest = make_ingest_headers("ing_s_1")
        err = api.post_usage_event(
            lic["id"],
            {"units": 1, "used_at": "2026-08-11T00:00:00Z"},
            ingest,
        )
        validate_error(err, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)

    def test_usage_on_revoked_license_rejected(self, api):
        """PRD §3.5: "the license must be `ACTIVE` (`ERR_LICENSE_NOT_ACTIVE`
        otherwise)"

        Design: Corner/errors/error_already_terminal_license_revoked_blocks_usage
        """
        holder, asset, req, lic, notice, _res = setup_suspended_license(
            fee_cents=200000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
            lapse_to="2026-08-12T00:00:00Z",
        )
        cert = make_certifier_headers("leg_rt_1")
        revoke_resp = api.revoke_license(lic["id"], cert)
        get_success_data(revoke_resp)
        ingest = make_ingest_headers("ing_rt_1")
        err = api.post_usage_event(
            lic["id"],
            {"units": 1, "used_at": "2026-08-15T00:00:00Z"},
            ingest,
        )
        validate_error(err, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)
