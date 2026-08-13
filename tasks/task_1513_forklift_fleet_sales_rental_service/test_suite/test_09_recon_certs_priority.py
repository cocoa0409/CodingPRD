"""Reconditioning QC loop, SOLD terminal lockdown, certification expiry and
renewal, and the safety-vs-temporal dispatch conflict."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_service_call,
    get_unit,
    make_customer,
    make_dispatched_call,
    make_operator,
    make_service_call,
    make_sold_unit,
    make_technician,
    make_unit,
    set_clock,
    validate_error,
    validate_success,
)

REGISTRAR = TEST_USERS["training_registrar_headers"]


class TestReconditioningQcLoop:
    def test_qc_fail_loop_then_pass(self, api, fleet_manager_headers):
        """PRD §3.8: "Completing with a `qc_result` of `FAIL` is a rework
        loop: the order stays `IN_PROGRESS` and `qc_fail_count` increments by
        1, ready for another attempt. Completing with a `qc_result` of `PASS`
        requires `listing_price_cents` to be present, else the request is
        rejected with `ERR_INVALID_REQUEST`; on success the order moves to
        `COMPLETED`, the price is recorded on the order, the unit moves from
        `IN_RECON` to `LISTED`, and the unit's own `resale_price_cents` is set
        to the same figure."

        Design: Corner/state_machines/recon_qc_fail_loop_then_pass
        """
        unit = make_unit(serial_number="SN-RC1", disposition="USED_SALE")
        order = validate_success(api.create_reconditioning_order(
            {"unit_id": unit["id"]}, fleet_manager_headers), 201)
        failed = validate_success(api.complete_reconditioning_order(
            order["id"], {"qc_result": "FAIL"}, fleet_manager_headers))
        assert failed["status"] == "IN_PROGRESS"
        assert failed["qc_fail_count"] == 1
        completed = validate_success(api.complete_reconditioning_order(
            order["id"], {"qc_result": "PASS", "listing_price_cents": 1999000},
            fleet_manager_headers))
        assert completed["status"] == "COMPLETED"
        assert completed["listing_price_cents"] == 1999000
        unit_after = get_unit(unit["id"])
        assert unit_after["availability_status"] == "LISTED"
        assert unit_after["resale_price_cents"] == 1999000


class TestSoldUnitLockdown:
    def test_sold_unit_rejects_meter_reading(self, api, fleet_manager_headers):
        """PRD §3.8: "`SOLD` is the terminal point of the unit's availability
        lifecycle — the unit can no longer be referenced by new contracts, and
        meter readings and fuel events against it are rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/sold_unit_rejects_meter_reading
        """
        _customer, unit, quote = make_sold_unit()
        assert quote["status"] == "ACCEPTED"
        assert get_unit(unit["id"])["availability_status"] == "SOLD"
        resp = api.create_meter_reading(unit["id"], {"reading_hours": 10},
                                        fleet_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestCertificationLifecycle:
    def test_certification_auto_expires_and_renews(
            self, api, training_registrar_headers):
        """PRD §2.9: "every certification still `ACTIVE` whose `expires_at`
        has been passed transitions to `EXPIRED`". PRD §3.6: "the registrar
        can renew a certification whether it is currently `ACTIVE` or already
        `EXPIRED`; in both cases `expires_at` moves to the new instant,
        `renewed_count` increments by 1, and the status becomes `ACTIVE`."

        Design: Corner/state_machines/certification_auto_expires_on_clock
        """
        customer = make_customer(name="Cert Co")
        operator = make_operator(customer["id"], full_name="Op Cert",
                                 badge_number="B-C1")
        cert = validate_success(api.issue_certification(
            operator["id"], {"cert_class": "STAND_UP",
                             "expires_at": "2026-09-01T00:00:00Z"},
            training_registrar_headers), 201)
        assert cert["status"] == "ACTIVE"
        set_clock("2026-09-02T00:00:00Z")
        certs = validate_success(api.list_certifications(operator["id"],
                                                         training_registrar_headers))
        assert certs[0]["status"] == "EXPIRED", \
            "clock advance past expires_at must sweep ACTIVE -> EXPIRED"
        renewed = validate_success(api.renew_certification(
            cert["id"], {"new_expires_at": "2027-09-01T00:00:00Z"},
            training_registrar_headers))
        assert renewed["status"] == "ACTIVE"
        assert renewed["renewed_count"] == 1
        assert renewed["expires_at"].startswith("2027-09-01T00:00:00")


class TestDispatchSafetyVsTemporalConflict:
    def _scenario(self, api):
        """Operator whose certification expired after the clock advanced to
        2026-10-01; technician already DISPATCHED 2026-10-05 10:00-11:00
        (buffered closed interval [09:00, 12:00]); second OPEN call naming the
        expired-cert operator."""
        customer = make_customer(name="Safety Co")
        unit = make_unit(serial_number="SN-PP2")
        operator = make_operator(customer["id"], full_name="Op Exp",
                                 badge_number="B-9")
        validate_success(api.issue_certification(
            operator["id"], {"cert_class": "SIT_DOWN",
                             "expires_at": "2026-09-01T00:00:00Z"},
            REGISTRAR), 201)
        set_clock("2026-10-01T00:00:00Z")
        tech = make_technician(full_name="Tech A",
                               van_stock=[{"part_number": "P-100", "qty": 5}])
        first = make_dispatched_call(
            unit["id"], customer["id"], tech["id"],
            scheduled_start="2026-10-05T10:00:00Z",
            scheduled_end="2026-10-05T11:00:00Z")
        second = make_service_call(unit["id"], customer["id"],
                                   operator_id=operator["id"])
        return customer, unit, operator, tech, first, second

    def test_expired_cert_beats_window_overlap(
            self, api, service_dispatcher_headers):
        """PRD §2.6: "the system evaluates them in one fixed precedence
        ladder, and the first failing check determines the error returned",
        with "the dispatch-time operator certification check" ordered ahead of
        "the dispatch window overlap check". PRD §3.5: "if an `operator_id` is
        present on the call, that operator must hold at least one
        certification with status `ACTIVE` at dispatch time, else
        `ERR_OPERATOR_CERT_EXPIRED`".

        Design: Difficulty/priority_pair_validation_conflict/dispatch_cert_expired_vs_window_overlap
        """
        _c, _u, _op, tech, _first, second = self._scenario(api)
        resp = api.dispatch_service_call(
            second["id"],
            {"technician_id": tech["id"],
             "scheduled_start": "2026-10-05T11:30:00Z",
             "scheduled_end": "2026-10-05T12:30:00Z"},
            service_dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_OPERATOR_CERT_EXPIRED, 422)

    def test_conflict_leaves_second_call_open(
            self, api, service_dispatcher_headers):
        """PRD §3.5: dispatch moves a call "from `OPEN` to `DISPATCHED`" only
        on success; when the operator-certification gate (§2.6 ladder: ahead
        of the dispatch-window-overlap gate) rejects the dispatch, the call
        stays OPEN and no window is registered.

        Design: Difficulty/priority_pair_validation_conflict/dispatch_cert_expired_vs_window_overlap
        """
        _c, _u, _op, tech, _first, second = self._scenario(api)
        resp = api.dispatch_service_call(
            second["id"],
            {"technician_id": tech["id"],
             "scheduled_start": "2026-10-05T11:30:00Z",
             "scheduled_end": "2026-10-05T12:30:00Z"},
            service_dispatcher_headers)
        error = resp.json()["data"]["error_id"]
        assert error == "ERR_OPERATOR_CERT_EXPIRED"
        assert error != "ERR_DISPATCH_WINDOW_OVERLAP", (
            "safety check must fire before the temporal check even though the "
            "buffered windows intersect")
        call = get_service_call(second["id"])
        assert call["status"] == "OPEN"
        assert call["technician_id"] is None
