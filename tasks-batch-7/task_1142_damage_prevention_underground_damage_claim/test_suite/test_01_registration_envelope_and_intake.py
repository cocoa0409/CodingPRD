"""Registration, response envelope, and damage-intake surface tests (PRD §2, §3.1, §3.3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_damage_case,
    assert_evidence_item,
    assert_excavator,
    create_damage_case_payload,
    create_excavator,
    create_excavator_payload,
    create_case,
    add_evidence,
    get_success_data,
    make_excavator_headers,
    make_intake_headers,
    make_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRegistrationDefaults:
    def test_excavator_defaults_on_registration(self, api):
        """PRD §3.1: "the new row is initialized with `program_status` `GOOD_STANDING`,
        `offender_points` 0, `credit_balance_cents` 0, and `total_outstanding_cents` 0."

        Design: Corner/entities/excavator_defaults_on_registration
        """
        resp = api.create_excavator(create_excavator_payload(), make_manager_headers())
        data = validate_success(resp, expected_status=201)
        assert_excavator(data)
        assert data["program_status"] == "GOOD_STANDING"
        assert data["offender_points"] == 0
        assert data["credit_balance_cents"] == 0
        assert data["total_outstanding_cents"] == 0

    def test_envelope_shape_on_object_read(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes) follow
        this standard envelope format in their JSON body"

        Design: Corner/entities/envelope_shape_on_object_read
        """
        excavator = create_excavator()
        resp = api.get_excavator(excavator["id"], make_manager_headers())
        body = resp.json()
        assert resp.status_code == 200
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        assert body["data"]["id"] == excavator["id"]


class TestAuthSurface:
    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "Both must be present and the role must be one of the declared role
        names below; otherwise the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/errors/missing_auth_header_returns_400
        """
        excavator = create_excavator()
        resp = api.get_excavator(excavator["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestDamageCaseIntake:
    def test_damage_case_creation_defaults(self, api):
        """PRD §3.3: "The new case is initialized with `investigation_status` `REPORTED`,
        `recovery_status` `UNBILLED`, all computed totals at 0, an empty
        `reconstruction_flags` array, and a server-minted `case_number`."

        Design: Corner/entities/damage_case_creation_defaults
        """
        excavator = create_excavator()
        payload = create_damage_case_payload(
            excavator_id=excavator["id"], dig_site_address="1 First St",
            facility_type="GAS", severity="MINOR", occurred_at="2026-05-02T09:00:00Z",
        )
        resp = api.create_damage_case(payload, make_intake_headers())
        data = validate_success(resp, expected_status=201)
        assert_damage_case(data)
        assert data["investigation_status"] == "REPORTED"
        assert data["recovery_status"] == "UNBILLED"
        assert data["subtotal_cents"] == 0
        assert data["evidence_count"] == 0
        assert isinstance(data["case_number"], str) and len(data["case_number"]) > 0

    def test_damage_case_missing_required_occurred_at_returns_invalid_request(self, api):
        """PRD §3.3: "an `IntakeCoordinator` intakes a `DamageCase` by supplying
        `excavator_id`, `dig_site_address`, `facility_type` (one of `GAS`, `ELECTRIC`,
        `TELECOM`, `WATER`), `severity` (one of `MINOR`, `MAJOR`, `CRITICAL`),
        `occurred_at`, and optionally `locate_ticket_id`." Missing required input is
        rejected with the catalogue's 400 input error (PRD §5).

        Design: Corner/entities/damage_case_missing_required_occurred_at_returns_invalid_request
        """
        excavator = create_excavator()
        payload = {
            "excavator_id": excavator["id"],
            "dig_site_address": "1 First St",
            "facility_type": "GAS",
            "severity": "MINOR",
        }
        resp = api.create_damage_case(payload, make_intake_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_damage_case_invalid_enum_rejected(self, api):
        """PRD §3.3: "`severity` (one of `MINOR`, `MAJOR`, `CRITICAL`)" — a value outside
        the declared set is rejected with the catalogue's 400 input error (PRD §5).

        Design: Corner/entities/damage_case_invalid_enum_rejected
        """
        excavator = create_excavator()
        payload = create_damage_case_payload(
            excavator_id=excavator["id"], dig_site_address="1 First St",
            facility_type="GAS", severity="SEVERE", occurred_at="2026-05-02T09:00:00Z",
        )
        resp = api.create_damage_case(payload, make_intake_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_get_missing_case_not_found_returns_404(self, api):
        """PRD §2.7: "Every id appearing in a URL path or in a request body —
        `damage_case_id`, `locate_ticket_id`, `locator_id`, `excavator_id`, `course_id`,
        `fault_allocation_id`, `claim_invoice_id`, `dispute_id`, `payer_id`, `target_id`,
        each `party_id` inside a `shares` entry, `amends_report_id`,
        `supersedes_allocation_id` — must resolve to an existing record; otherwise the
        request is rejected with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_missing_case_not_found_returns_404
        """
        resp = api.get_damage_case(NON_EXISTENT_UUID, make_manager_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestEvidenceItemSurface:
    def test_evidence_item_immutable_common_fields_absent(self, api):
        """PRD §2.4: "`EvidenceItem` and `TimelineEvent` carry only `id` and
        `created_at`; both `updated_at` and `version` are absent on those two entities
        and are not present in their payloads."

        Design: Corner/entities/evidence_item_immutable_common_fields_absent
        """
        excavator = create_excavator()
        case = create_case(excavator["id"], dig_site_address="2 Second St", severity="MINOR")
        evidence = add_evidence(case["id"])
        resp = api.get_evidence_item(evidence["id"], make_manager_headers())
        data = validate_success(resp)
        assert_evidence_item(data)
        assert data["id"] == evidence["id"]


class TestDamageCaseListing:
    def test_damage_cases_list_pagination_and_filter(self, api):
        """PRD §2.3: "All list endpoints accept two query parameters: `limit` and
        `offset`. `limit` defaults to 10, must be at least 1, and is capped at 100.
        `offset` defaults to 0 and must be non-negative." and "The response `meta` block
        for a list endpoint includes `limit`, `offset`, `total_count`, and `has_more`"

        Design: Corner/entities/damage_cases_list_pagination_and_filter
        """
        excavator = create_excavator()
        create_case(excavator["id"], dig_site_address="3 Third St", severity="MINOR")
        create_case(excavator["id"], dig_site_address="4 Fourth St", severity="MINOR",
                    facility_type="WATER", occurred_at="2026-05-03T09:00:00Z")
        resp = api.list_damage_cases(
            make_manager_headers(),
            params={"investigation_status": "REPORTED", "limit": 1, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"expected exactly 1 row under limit=1, got {len(data)}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
