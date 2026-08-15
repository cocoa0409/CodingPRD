"""Job/room/item registration: creation defaults, identity, validation,
barcode uniqueness, room rollup, pagination, job closure gate, and the two
authentication/authorization gatekeepers (PRD §2.1, §2.2, §2.3, §3.1, §3.9).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS, ANONYMOUS_HEADERS,
    assert_pack_out_job, assert_item,
    create_pack_out_job_payload, create_item_payload, create_vault_payload,
    create_job, create_room, register_item, setup_job_with_room,
    setup_cleaned_item, get_job, triage_item, create_cleaning_task,
    transition_cleaning_task, create_vault, place_item,
)

PM = TEST_USERS["project_manager_headers"]
TECH = TEST_USERS["inventory_technician_headers"]


class TestJobCreationDefaults:
    def test_job_created_with_system_defaults(self, api):
        """PRD §3.1: "A new job starts in `INTAKE` status with `structure_status`
        `PENDING` and `billing_status` `ACCUMULATING`."
        PRD §2.4: "Nearly every resource also carries `created_at` and `updated_at`
        timestamps in ISO 8601 UTC format with three fractional digits, plus an
        integer `version` that starts at 1 on creation and increments by exactly 1
        on every mutation of that resource."
        PRD §2.8: "A job's `accrued_storage_total_cents` sums, across that job's
        statements, the `provisional_total_cents` of each provisional statement and
        the `final_total_cents` of each finalized or invoiced statement, excluding
        voided statements entirely" — a fresh job has no statements, so the sum is 0.

        Design: Corner/entities/job_created_with_system_defaults
        """
        res = api.create_pack_out_job(create_pack_out_job_payload(
            claim_number="CLM-EN1", property_address="40 Fir St",
            carrier_name="Acme Mutual", policy_coverage_type="ACV"), PM)
        job = validate_success(res, 201)
        assert_pack_out_job(job)
        assert job["status"] == "INTAKE", f"expected INTAKE, got {job['status']}"
        assert job["structure_status"] == "PENDING"
        assert job["billing_status"] == "ACCUMULATING"
        assert job["accrued_storage_total_cents"] == 0
        assert job["version"] == 1, f"version must start at 1, got {job['version']}"


class TestItemRegistration:
    def test_get_item_not_found_returns_404(self, api, pm_headers):
        """PRD §2.7: "Fifth, resource existence along path and body references
        yields `ERR_NOT_FOUND`."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." and "The `message` provides
        a human-readable explanation of what went wrong."

        Design: Corner/entities/get_item_not_found_returns_404
        """
        res = api.get_item(NON_EXISTENT_UUID, pm_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
        body = res.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["data"]["message"].strip(), "error message must be present"

    def test_create_item_missing_required_barcode_returns_400(self, api):
        """PRD §3.1: "An `InventoryTechnician` registers items into a room with a
        scannable `barcode`, a free-text `description`, an `item_category` of ..." —
        barcode is a required registration input.
        PRD §2.7: "Fourth, request-body schema validation — missing required fields,
        invalid enum members, integer range violations — yields `ERR_VALIDATION`."

        Design: Corner/entities/create_item_missing_required_barcode_returns_400
        """
        job, room = setup_job_with_room(
            job_overrides={"claim_number": "CLM-EN3", "property_address": "42 Elm St"})
        payload = create_item_payload(description="No barcode", item_category="GENERAL",
                                      declared_value_cents=100, volume_cu_ft=5)
        del payload["barcode"]
        res = api.create_item(room["id"], payload, TECH)
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)

        items = validate_success(api.list_items(TECH, params={"room_id": room["id"]}), 200)
        assert items == [], f"nothing may be persisted, got {items}"

    def test_duplicate_barcode_rejected_within_job(self, api):
        """PRD §3.1: "The `barcode` must be unique within the parent job — across
        all rooms of that job — and a duplicate is rejected with
        `ERR_DUPLICATE_BARCODE`."

        Design: Corner/validations/duplicate_barcode_rejected_within_job
        """
        job_a, room_a = setup_job_with_room(
            job_overrides={"claim_number": "CLM-V8A", "property_address": "80 Spruce St"})
        register_item(room_a["id"], barcode="BC-DUP", description="First",
                      declared_value_cents=100, volume_cu_ft=2)
        job_b, room_b = setup_job_with_room(
            job_overrides={"claim_number": "CLM-V8B", "property_address": "82 Alder St",
                           "policy_coverage_type": "RCV"})

        dup = api.create_item(room_a["id"], create_item_payload(
            barcode="BC-DUP", description="Second same-job",
            declared_value_cents=200, volume_cu_ft=2), TECH)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_BARCODE, expected_status=409)

        other_job = api.create_item(room_b["id"], create_item_payload(
            barcode="BC-DUP", description="Other-job reuse",
            declared_value_cents=200, volume_cu_ft=2), TECH)
        reused = validate_success(other_job, 201)
        assert_item(reused)
        assert reused["barcode"] == "BC-DUP", (
            "uniqueness is scoped to the parent job; reuse under another job succeeds")


class TestRoomRollupAndListing:
    def test_room_compound_status_bubble_up(self, api):
        """PRD §3.1: "With at least one item and no item still holding
        `condition_triage` `PENDING`, the room reads `INVENTORIED`."
        PRD §3.1: "When, additionally, no item holds a `processing_status` of
        `REGISTERED`, `AWAITING_CLEANING`, `IN_CLEANING`, `CLEANED`, or
        `AWAITING_DISPOSAL` — meaning every item is stored, out for specialty,
        packed back, delivered, disposed, or claim-settled — the room reads
        `CLEARED`."

        Design: Corner/state_machines/room_compound_status_bubble_up
        """
        job, room = setup_job_with_room(
            job_overrides={"claim_number": "CLM-SM3", "property_address": "50 Poplar St"},
            room_overrides={"name": "Bedroom", "room_type": "BEDROOM"})
        item = register_item(room["id"], barcode="BC-SM3", description="Headboard",
                             item_category="FURNITURE", declared_value_cents=9000,
                             volume_cu_ft=12)

        rooms = validate_success(api.list_rooms(job["id"], PM), 200)
        assert rooms[0]["status"] == "OPEN", (
            f"room must be OPEN while its only item is PENDING triage, got {rooms[0]['status']}")

        triage_item(item["id"], item["version"], "SALVAGEABLE")
        rooms = validate_success(api.list_rooms(job["id"], PM), 200)
        assert rooms[0]["status"] == "INVENTORIED", (
            f"room must be INVENTORIED once no item is PENDING, got {rooms[0]['status']}")

        task = create_cleaning_task(item["id"])
        transition_cleaning_task(task["id"], "START")
        transition_cleaning_task(task["id"], "QA_PASS")
        vault = create_vault(code="V-SM3", climate_class="STANDARD", capacity_cu_ft=1000,
                             monthly_rate_cents_per_cu_ft=100)
        place_item(item["id"], vault["id"])

        rooms = validate_success(api.list_rooms(job["id"], PM), 200)
        assert rooms[0]["status"] == "CLEARED", (
            f"room must be CLEARED once the item is IN_STORAGE, got {rooms[0]['status']}")

    def test_rooms_list_pagination_envelope(self, api, pm_headers):
        """PRD §2.3: "List endpoints accept two query parameters, `limit` and
        `offset`." and "The `meta` block of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`, where `has_more` indicates whether
        additional results exist beyond the returned window."

        Design: Corner/endpoints/rooms_list_pagination_envelope
        """
        job = create_job(claim_number="CLM-EP1", property_address="84 Willow St")
        create_room(job["id"], name="Alpha", room_type="LIVING")
        create_room(job["id"], name="Beta", room_type="BATH")

        page1_res = api.list_rooms(job["id"], pm_headers, params={"limit": 1, "offset": 0})
        page1, meta1 = validate_paginated(page1_res)
        assert page1_res.json()["response_type"] == "array"
        assert len(page1) == 1, f"limit=1 must return exactly one row, got {len(page1)}"
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_rooms(job["id"], pm_headers, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert meta2["offset"] == 1
        assert page1[0]["id"] != page2[0]["id"], "pages must be disjoint windows"


class TestJobClosureGate:
    def test_job_close_with_nonterminal_items_rejected(self, api):
        """PRD §3.9: "Every item of the job — reached through its rooms — must sit
        in a terminal processing state, `DELIVERED`, `DISPOSED`, or `CLAIM_SETTLED`;
        any non-terminal item yields `ERR_JOB_ITEMS_NOT_TERMINAL`."

        Design: Corner/validations/job_close_with_nonterminal_items_rejected
        """
        job, room, item, _task = setup_cleaned_item(
            job_overrides={"claim_number": "CLM-V9", "property_address": "100 Fir St"},
            room_overrides={"name": "Den"},
            item_overrides={"barcode": "BC-V9", "item_category": "FURNITURE",
                            "declared_value_cents": 800, "volume_cu_ft": 3})
        assert item["processing_status"] == "CLEANED", "precondition: item non-terminal"

        res = api.transition_pack_out_job(job["id"], {"action": "CLOSE"}, PM)
        validate_error(res, ApiErrorId.ERR_JOB_ITEMS_NOT_TERMINAL, expected_status=409)

        job_after = get_job(job["id"])
        assert job_after["status"] == "ACTIVE", (
            f"failed CLOSE must leave the job ACTIVE, got {job_after['status']}")


class TestAuthenticationGates:
    def test_unauthenticated_missing_auth_header_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or presenting either header
        empty, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/unauthenticated_missing_auth_header_returns_401
        """
        res = api.create_pack_out_job(create_pack_out_job_payload(
            claim_number="CLM-V1", property_address="66 Maple St"), ANONYMOUS_HEADERS)
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_technician_cannot_create_vault(self, api, tech_headers):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized list
        is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /api/vaults authorizes only ProjectManager.

        Design: Corner/rbac/technician_cannot_create_vault
        """
        res = api.create_vault(create_vault_payload(
            code="V-RB1", climate_class="STANDARD", capacity_cu_ft=100,
            monthly_rate_cents_per_cu_ft=100), tech_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
