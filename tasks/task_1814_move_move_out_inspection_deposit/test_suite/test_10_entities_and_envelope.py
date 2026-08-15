"""Entity creation shape, response envelope, server-minted fields, defaults,
and 404/400 surface."""
import test_helpers as th
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_tenancy,
    create_inspection_payload,
    create_jurisdiction,
    create_property,
    create_tenancy,
    create_tenancy_payload,
    create_unit,
    get_success_data,
    get_tenancy,
    is_valid_uuid,
    make_inspector_headers,
    make_manager_admin_headers,
    make_property_manager_headers,
    schedule_inspection,
    validate_error,
    validate_success,
)

ADMIN = make_manager_admin_headers()
PM = make_property_manager_headers()
INSP = make_inspector_headers()


def _portfolio():
    jur = create_jurisdiction(interest_required=False, annual_interest_rate_bp=0)
    prop = create_property(jur["id"])
    unit = create_unit(prop["id"])
    return jur, prop, unit


class TestTenancyCreationDefaults:
    def test_creation_defaults_and_envelope(self):
        """PRD §3.2: "A new tenancy starts in `PENDING_MOVE_IN` with
        `keys_returned` and `fobs_returned` at zero and every money counter at
        zero". PRD §2.7: "The tenancy's `balance_remaining_cents` is defined
        at all times as its `deposit_cents`, plus `interest_accrued_cents`,
        minus `total_deductions_cents`, plus `released_cents`, minus
        `refund_paid_cents`, minus `escheated_cents`, minus `reserved_cents`."
        PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`." and "The
        `response_type` is either "object" for a single resource or "array"
        for a list of resources."

        201 with status PENDING_MOVE_IN, all counters 0, balance == deposit,
        and the success envelope carries meta.api_request_id.

        Design: Corner/entities/tenancy_creation_defaults_and_envelope
        """
        _jur, _prop, unit = _portfolio()
        resp = api_client.create_tenancy(
            create_tenancy_payload(unit_id=unit["id"],
                                   lease_start_on="2026-09-01",
                                   lease_end_on="2027-09-01"),
            PM,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        ten = body["data"]
        assert_tenancy(ten)
        assert ten["status"] == "PENDING_MOVE_IN"
        assert ten["keys_returned"] == 0 and ten["fobs_returned"] == 0
        assert ten["version"] == 1
        for f in ("interest_accrued_cents", "pending_deductions_cents",
                  "total_deductions_cents", "refund_paid_cents",
                  "penalty_paid_cents", "escheated_cents", "reserved_cents",
                  "released_cents"):
            assert ten[f] == 0, f"{f} must start at 0, got {ten[f]}"
        assert ten["balance_remaining_cents"] == 200_000


class TestJurisdictionRequiredFields:
    def test_missing_code_returns_400(self):
        """PRD §2.9: "third, request-body schema — the body must parse and
        contain all required fields with well-typed, non-negative values, and
        this schema check deliberately precedes any identifier resolution
        (`ERR_INVALID_REQUEST`)". PRD §2.10: "A `JurisdictionProfile` captures,
        under a unique `code`".

        Omitting the required `code` fails with ERR_INVALID_REQUEST (400).

        Design: Corner/entities/jurisdiction_missing_required_field_returns_400
        """
        resp = api_client.create_jurisdiction_profile(
            {"deposit_return_deadline_days": 21, "dispute_window_days": 30,
             "interest_required": False, "annual_interest_rate_bp": 0,
             "interest_basis": "ACTUAL_DAYS", "stale_check_days": 180,
             "small_claims_cap_cents": 1_000_000, "bad_faith_multiplier": 2,
             "lock_change_allowed": True, "allow_actual_cost_charge": False},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestNotFound:
    def test_get_unknown_tenancy_returns_404(self):
        """PRD §2.9: "fourth, existence of every referenced resource id,
        validated left-to-right so the first missing identifier in the path or
        body determines the `ERR_NOT_FOUND` rejection".

        GET with a well-formed but nonexistent tenancy id yields 404.

        Design: Corner/entities/get_unknown_tenancy_returns_404
        """
        resp = api_client.get_tenancy(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestSystemFieldsInputIgnored:
    def test_client_supplied_id_and_version_ignored(self):
        """PRD §2.4: "A unique, server-generated identifier formatted as a
        UUID, with no type prefix." and "A system-managed integer that
        increments by one with every modification to the resource, including
        mutations driven by cascading side effects and automatic state
        reconciliation."

        Client-supplied id/version in the create body are ignored: the server
        mints its own id and starts version at 1.

        Design: Corner/entities/tenancy_system_fields_input_ignored
        """
        _jur, _prop, unit = _portfolio()
        payload = create_tenancy_payload(
            unit_id=unit["id"], lease_start_on="2026-09-01",
            lease_end_on="2027-09-01")
        payload["id"] = "11111111-1111-1111-1111-111111111111"
        payload["version"] = 99
        resp = api_client.create_tenancy(payload, PM)
        ten = validate_success(resp, expected_status=201)
        assert ten["id"] != "11111111-1111-1111-1111-111111111111"
        assert is_valid_uuid(ten["id"])
        assert ten["version"] == 1


class TestDefaults:
    def test_forwarding_address_default_null(self):
        """PRD §3.2: "an optional `forwarding_address` records where the
        eventual refund should be mailed and may be set until the statement is
        issued".

        Omitting the optional forwarding_address yields null on the created
        tenancy.

        Design: Corner/entities/forwarding_address_default_null
        """
        _jur, _prop, unit = _portfolio()
        resp = api_client.create_tenancy(
            create_tenancy_payload(unit_id=unit["id"],
                                   lease_start_on="2026-09-01",
                                   lease_end_on="2027-09-01"),
            PM,
        )
        ten = validate_success(resp, expected_status=201)
        assert "forwarding_address" in ten
        assert ten["forwarding_address"] is None

    def test_inspection_item_determination_default_unassessed(self):
        """PRD §3.2: "Each item also carries a `determination` — `UNASSESSED`
        by default, later set to `NORMAL_WEAR` or `TENANT_DAMAGE`".

        An item created without determination reads UNASSESSED.

        Design: Corner/entities/inspection_item_determination_default_unassessed
        """
        _jur, _prop, unit = _portfolio()
        ten = create_tenancy(unit["id"], lease_start_on="2026-09-01",
                             lease_end_on="2027-09-01")
        mi = schedule_inspection(ten["id"], "MOVE_IN",
                                 scheduled_start_at="2026-09-01T09:00:00Z",
                                 scheduled_end_at="2026-09-01T10:00:00Z")
        resp = api_client.add_inspection_item(
            mi["id"],
            {"area_name": "kitchen_floor", "category": "OTHER",
             "condition": "GOOD", "photo_count": 1},
            INSP,
        )
        item = validate_success(resp, expected_status=201)
        assert item["determination"] == "UNASSESSED"
