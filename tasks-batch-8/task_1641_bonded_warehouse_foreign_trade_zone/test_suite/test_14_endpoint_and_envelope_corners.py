"""Corner coverage for endpoint behaviors: pagination defaults, withdrawal-type
conditional actions, listing filters, the error envelope, and access-event
defaults/immutability."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_zone_access_event,
    create_access_badge_payload,
    create_access_event_payload,
    create_admission,
    create_badge,
    create_filed_withdrawal,
    create_withdrawal,
    create_zone,
    file_withdrawal,
    get_lot,
    get_success_data,
    make_customs_officer_headers,
    make_gate_officer_headers,
    make_importer_headers,
    make_zone_operator_headers,
    setup_zone_with_lot,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestListPaginationDefaults:
    def test_default_limit_ten_and_offset_paging(self):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; it defaults to 10 when omitted, with a minimum of 1 and a
        maximum of 100. The `offset` parameter specifies how many items to skip and
        defaults to 0."
        PRD §2.3: "Paginated list responses carry four fields in the `meta` object
        of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/endpoints/c_list_pagination_defaults
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Page Zone", zone_code="Z-PG")
        imp = make_importer_headers("imp-1")
        for i in range(1, 13):
            get_success_data(api_client.create_admission(
                {"zone_id": zone["id"], "description": f"Lot {i:02d}", "hts_code": "0401.10",
                 "quantity": 1, "unit_value_cents": 100, "zone_status": "DOMESTIC"}, imp,
            ))

        op = make_zone_operator_headers()
        page1, meta1 = validate_paginated(
            api_client.list_admissions(op, params={"zone_id": zone["id"]}))
        assert len(page1) == 10, f"default limit 10, got {len(page1)}"
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api_client.list_admissions(op, params={"zone_id": zone["id"], "offset": 10}))
        assert len(page2) == 2, f"second page holds the remaining 2, got {len(page2)}"
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False


class TestWrongTypeActionsRejected:
    def _setup_filed_pair(self):
        zone, _a, lot = setup_zone_with_lot(
            quantity=10, unit_value_cents=1000, hts_code="0401.10",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Type Zone", zone_code="Z-TYP",
        )
        wx = create_filed_withdrawal(zone["id"], lot["id"], quantity=1,
                                     withdrawal_type="EXPORT", importer_id="imp-1")
        wc = create_filed_withdrawal(zone["id"], lot["id"], quantity=1,
                                     withdrawal_type="CONSUMPTION", importer_id="imp-1")
        return zone, lot, wx, wc

    def test_pay_duty_on_export_rejected(self):
        """PRD §3.5: "paying an `EXPORT` withdrawal is rejected with
        `ERR_WRONG_WITHDRAWAL_TYPE`"

        Design: Corner/endpoints/c_wrong_type_actions_rejected
        """
        _zone, _lot, wx, _wc = self._setup_filed_pair()
        imp = make_importer_headers("imp-1")
        resp = api_client.pay_duty_withdrawal(wx["id"], imp)
        validate_error(resp, ApiErrorId.ERR_WRONG_WITHDRAWAL_TYPE, expected_status=409)
        w_after = get_success_data(api_client.get_withdrawal(wx["id"], make_zone_operator_headers()))
        assert w_after["status"] == "FILED"

    def test_confirm_export_on_consumption_rejected(self):
        """PRD §3.5: "confirming export on a `CONSUMPTION` withdrawal is likewise
        `ERR_WRONG_WITHDRAWAL_TYPE`"

        Design: Corner/endpoints/c_wrong_type_actions_rejected
        """
        _zone, _lot, _wx, wc = self._setup_filed_pair()
        customs = make_customs_officer_headers()
        resp = api_client.confirm_export_withdrawal(wc["id"], customs)
        validate_error(resp, ApiErrorId.ERR_WRONG_WITHDRAWAL_TYPE, expected_status=409)
        w_after = get_success_data(api_client.get_withdrawal(wc["id"], make_zone_operator_headers()))
        assert w_after["status"] == "FILED"


class TestFilterWithdrawalsByType:
    def test_filter_by_withdrawal_type_export(self):
        """PRD §3.5: "Withdrawals may be listed with optional `zone_id`, `lot_id`,
        `weekly_entry_id`, `status`, and `withdrawal_type` filters."
        PRD §3.5: "A **Withdrawal** removes merchandise from the zone, either into
        domestic commerce (`withdrawal_type` of `CONSUMPTION`) or out of the
        country (`EXPORT`)."

        Design: Corner/endpoints/c_filter_withdrawals_by_type
        """
        zone, _a, lot = setup_zone_with_lot(
            quantity=10, unit_value_cents=1000, hts_code="0401.10",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Filter W Zone", zone_code="Z-FW",
        )
        create_withdrawal(zone["id"], lot["id"], quantity=1,
                          withdrawal_type="CONSUMPTION", importer_id="imp-1")
        wx = create_withdrawal(zone["id"], lot["id"], quantity=1,
                               withdrawal_type="EXPORT", importer_id="imp-1")

        op = make_zone_operator_headers()
        rows, meta = validate_paginated(api_client.list_withdrawals(
            op, params={"zone_id": zone["id"], "withdrawal_type": "EXPORT"}))
        assert meta["total_count"] == 1, f"only the EXPORT withdrawal matches, got {meta['total_count']}"
        assert rows[0]["id"] == wx["id"]


class TestErrorEnvelopeContract:
    def test_error_envelope_shape(self):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with "`response_type`: \"error\"" and a `data`
        object carrying `error_id` and `message`.
        PRD §2.2: "The `message` provides a human-readable explanation of what went
        wrong."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`."

        Design: Corner/errors/c_error_envelope_contract
        """
        op = make_zone_operator_headers()
        resp = api_client.create_zone({"name": "Env Zone"}, op)
        err = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(err["message"], str) and len(err["message"].strip()) > 0
        assert isinstance(body["meta"].get("api_request_id"), str)


class TestAccessEventDefaultsAndImmutability:
    def test_default_occurred_at_uses_logical_clock(self):
        """PRD §3.8: "supplying the `zone_id`, the `badge_id`, the `direction`
        (`IN` or `OUT`), and optionally `occurred_at`, which defaults to the
        logical clock's current instant when omitted."
        PRD §2.5: "At server startup the logical clock reads exactly
        2026-08-01T00:00:00Z"

        Design: Corner/entities/c_access_event_default_occurred_at
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Event Zone", zone_code="Z-EVT")
        b = create_badge(zone["id"], holder_name="Ada Lovelace",
                         valid_from="2026-08-01T00:00:00Z", valid_until="2026-12-31T00:00:00Z")
        gate = make_gate_officer_headers()
        data = validate_success(api_client.create_access_event(
            {"zone_id": zone["id"], "badge_id": b["id"], "direction": "IN"}, gate,
        ), expected_status=201)
        assert data["occurred_at"] == "2026-08-01T00:00:00Z", (
            f"default occurred_at is the logical clock default, got {data['occurred_at']!r}"
        )

    def test_append_only_event_shape(self):
        """PRD §2.4: "A `ZoneAccessEvent` is an append-only audit record carrying
        only `id` and `created_at` alongside its event payload; `updated_at` and
        `version` are absent, and the record is immutable once written."

        Design: Corner/entities/c_access_event_immutable_shape
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Event Zone 2", zone_code="Z-EV2")
        b = create_badge(zone["id"], holder_name="Alan Turing",
                         valid_from="2026-08-01T00:00:00Z", valid_until="2026-12-31T00:00:00Z")
        gate = make_gate_officer_headers()
        data = validate_success(api_client.create_access_event(
            {"zone_id": zone["id"], "badge_id": b["id"], "direction": "IN",
             "occurred_at": "2026-08-02T08:00:00Z"}, gate,
        ), expected_status=201)
        assert "id" in data and "created_at" in data
        assert "version" not in data, "append-only event must not carry version"
        assert "updated_at" not in data, "append-only event must not carry updated_at"
        assert_zone_access_event(data)
