"""Master data, listing, pagination, and universal validation-layer behavior."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    make_design_engineer_headers,
    make_customer,
    make_engineer,
    make_job,
    make_jig,
    make_crane,
    make_design,
    make_lumber_lot,
    book_slot,
    create_job_payload,
    create_design_payload,
    job_fresh,
)

PM = TEST_USERS["plant_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
IM = TEST_USERS["inventory_manager_headers"]
SFL = TEST_USERS["shop_floor_lead_headers"]


class TestCustomerDefaults:
    def test_create_customer_applies_documented_defaults(self, api):
        """PRD §3.1: "Optional account terms include `credit_hold` (default false),
        `storage_free_days` (default 2 whole days), `storage_daily_fee_cents` (default
        15000), `storage_fee_cap_cents` (default 300000), and `max_drops_per_day`
        (default 2)" and "Each account tracks a computed `credit_used_cents`, initially 0".

        Design: Corner/entities/create_customer_applies_documented_defaults
        """
        cust = make_customer(company_name="Defaults Co", credit_limit_cents=500000,
                             delivery_terms="FOB_PLANT")
        data = validate_success(api.get_customer_account(cust["id"], PM))
        assert data["credit_hold"] is False
        assert data["storage_free_days"] == 2
        assert data["storage_daily_fee_cents"] == 15000
        assert data["storage_fee_cap_cents"] == 300000
        assert data["max_drops_per_day"] == 2
        assert data["credit_used_cents"] == 0, "computed credit starts at 0"
        assert is_valid_uuid(data["id"])


class TestJobWindowValidation:
    def test_create_job_window_inverted_returns_invalid_request(self, api):
        """PRD §2.7: "Schema validation (`ERR_INVALID_REQUEST`, HTTP 400) covers
        required-field presence, type agreement, enum membership within the declared
        sets, and the conditional-input rules scattered through §3" and "a job's
        `delivery_window_end` must be on or after its `delivery_window_start`".

        Design: Corner/entities/create_job_window_inverted_returns_invalid_request
        """
        cust = make_customer()
        resp = api.create_job(
            create_job_payload(cust["id"], job_name="Bad Window",
                               delivery_window_start="2026-08-27T00:00:00Z",
                               delivery_window_end="2026-08-20T00:00:00Z"),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        jobs, meta = validate_paginated(api.list_jobs(PM, params={"customer_id": cust["id"]}))
        assert meta["total_count"] == 0 and jobs == [], "rejected create must persist nothing"


class TestJigSetupImmutability:
    def test_jig_setup_immutability_surface(self, api):
        """PRD §2.4: "One resource is the exception: a `JigSetup` is immutable after
        creation and carries only `id` and `created_at`. Both `updated_at` and
        `version` are absent from it."

        Design: Corner/entities/jig_setup_immutability_surface
        """
        jig = make_jig()
        data = validate_success(api.get_jig_setup(jig["id"], PM))
        assert is_valid_uuid(data["id"])
        assert "created_at" in data
        assert "updated_at" not in data, "JigSetup must not expose updated_at"
        assert "version" not in data, "JigSetup must not expose version"
        assert data["changeover_minutes_from"] == {}


class TestDesignReverseLookup:
    def test_fk_reverse_lookup_designs_by_job(self, api):
        """PRD §3.3: "The design list supports filtering by `job_id`,
        `supersedes_design_id`, `submitted_by_engineer_id`, `sealed_by_engineer_id`,
        `status`, and `component_ref`."

        Design: Corner/entities/fk_reverse_lookup_designs_by_job
        """
        cust = make_customer()
        eng = make_engineer("1")
        job = make_job(cust, job_name="FK Job")
        dsg = make_design(job["id"], eng, quantity_required=4, lumber_grade="SYP_NO1",
                          plating="P18", span_ft=30.0, pitch_degrees=22.62)
        data, meta = validate_paginated(api.list_designs(PM, params={"job_id": job["id"]}))
        assert meta["total_count"] == 1 and data[0]["id"] == dsg["id"]
        data2, meta2 = validate_paginated(
            api.list_designs(PM, params={"supersedes_design_id": dsg["id"]}))
        assert meta2["total_count"] == 0 and data2 == [], \
            "no revision supersedes the first design yet — empty list, not an error"


class TestPagination:
    def test_list_pagination_defaults_and_offsets(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100." and "Unless
        otherwise specified, every list endpoint returns resources sorted by
        `created_at` in ascending order."

        Design: Corner/entities/list_pagination_defaults_and_offsets
        """
        for i in range(1, 13):
            make_engineer(f"{i:02d}")
        page1, meta1 = validate_paginated(api.list_engineers(PM))
        assert len(page1) == 10, "default limit is 10"
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert page1[0]["full_name"] == "E01", "default sort is created_at ascending"
        page2, meta2 = validate_paginated(api.list_engineers(PM, params={"offset": 10}))
        assert len(page2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False


class TestUniversalValidationLayers:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request with missing headers, an undeclared role, or — for
        entity-backed roles — an `X-User-ID` that does not resolve to an existing
        instance of the backing entity is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.list_jobs(None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_unknown_resource_returns_not_found(self, api):
        """PRD §2.7: "Existence validation covers every identifier in the URL path and
        every foreign key in the request body, checked left-to-right: path identifiers
        in template order first, then body fields in their declared input order."

        Design: Corner/validations/unknown_resource_returns_not_found
        """
        resp = api.get_job(NON_EXISTENT_UUID, PM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_existence_validated_left_to_right_path_before_body(self, api):
        """PRD §2.7: "A request naming a non-existent job in the path therefore fails
        with `ERR_NOT_FOUND` before any body reference is examined, and a body naming
        a non-existent lot fails before any state or business rule runs."

        Design: Corner/validations/existence_validated_left_to_right_path_before_body
        """
        cust = make_customer()
        eng = make_engineer("1")
        job = make_job(cust, job_name="Real Job")
        payload = create_design_payload(
            job_fresh(job["id"])["version"],
            supersedes_design_id="7b3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d3",
        )
        resp = api.create_design(NON_EXISTENT_UUID, payload,
                                 make_design_engineer_headers(eng["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_role_check_precedes_existence_check(self, api):
        """PRD §2.7: "Every request is validated in a fixed priority order, and when a
        request violates several rules the rejection reported is the one earliest in
        that order. Authentication comes first (`ERR_UNAUTHENTICATED`), then role
        authorization (`ERR_FORBIDDEN_ROLE`), then customer-ownership scope
        (`ERR_FORBIDDEN_OWNERSHIP`), then existence (`ERR_NOT_FOUND`)"

        Design: Corner/validations/role_check_precedes_existence_check
        """
        # ShopFloorLead is not authorized for job confirm AND the job does not exist;
        # role authorization (earlier layer) must be the reported rejection.
        resp = api.confirm_job(NON_EXISTENT_UUID, SFL)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestInitialStates:
    def test_initial_states_sweep(self, api):
        """PRD §3.2: "A job is born `QUOTED`." PRD §3.3: "A design starts in `DRAFT`".
        PRD §3.5: "At receipt, `available_bf` initializes to `received_board_feet` and
        `available_plates` to `received_plates`" and "the lot is born `ACTIVE`".
        PRD §3.6: "Slots are born `BOOKED`".

        Design: Corner/state_machines/initial_states_sweep
        """
        cust = make_customer()
        eng = make_engineer("1")
        job = make_job(cust, job_name="Init Job")
        dsg = make_design(job["id"], eng, quantity_required=4, lumber_grade="SYP_NO1",
                          plating="P18", span_ft=30.0, pitch_degrees=22.62)
        lot = make_lumber_lot(received_board_feet=500.0)
        crane = make_crane(crane_code="CR-C", capacity_lbs=8000, crane_class="STANDARD",
                           hourly_rate_cents=15000)
        slot = book_slot(crane["id"], "BUILD_PICK", "2026-08-12T10:00:00Z", "2026-08-12T12:00:00Z")

        job_data = validate_success(api.get_job(job["id"], PM))
        assert job_data["status"] == "QUOTED" and job_data["posture"] == "GREEN"
        dsg_data = validate_success(api.get_design(dsg["id"], PM))
        assert dsg_data["status"] == "DRAFT" and dsg_data["revision_no"] == 1, \
            "the first design for a (job, component_ref) pair is revision 1"
        lot_data = validate_success(api.get_inventory_lot(lot["id"], IM))
        assert lot_data["status"] == "ACTIVE"
        assert lot_data["available_bf"] == pytest.approx(500.00)
        assert lot_data["reserved_bf"] == 0
        assert lot_data["consumed_bf"] == 0
        assert lot_data["scrapped_bf"] == 0
        slot_data = validate_success(api.get_crane_slot(slot["id"], PP))
        assert slot_data["status"] == "BOOKED"
