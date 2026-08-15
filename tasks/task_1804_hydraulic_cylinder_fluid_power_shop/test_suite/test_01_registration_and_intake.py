"""Registration, catalog configuration, and work-order intake gates (PRD §3.1-3.2)."""
from test_helpers import (
    ADMIN,
    ADVISOR,
    TEST_USERS,
    ApiErrorId,
    assert_customer,
    assert_work_order,
    create_customer,
    create_customer_payload,
    create_cylinder,
    create_cylinder_payload,
    create_seal_kit,
    create_seal_kit_payload,
    create_shop,
    create_work_order_payload,
    get_success_data,
    make_customer_headers,
    open_work_order,
    setup_master_data,
    setup_quote_sent,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRegistration:
    def test_customer_creation_applies_defaults(self, api):
        """PRD §3.1: "an optional `opening_ytd_spend_cents` books migrated
        year-to-date spend at account creation and defaults to zero."
        PRD §3.1: "A new customer starts `ACTIVE`, and its `ytd_spend_cents` is
        initialized to the opening value"
        PRD §2.4: "`version` (integer): starts at 1 when the resource is created
        and increments by one with every modification."

        Design: Corner/entities/customer_creation_applies_defaults
        """
        create_shop()
        resp = api.create_customer(
            create_customer_payload(full_name="Defaults Co", email="d@d.com",
                                    credit_limit_cents=500000),
            ADVISOR,
        )
        customer = validate_success(resp, 201)
        assert_customer(customer)
        assert customer["opening_ytd_spend_cents"] == 0
        assert customer["ytd_spend_cents"] == 0
        assert customer["status"] == "ACTIVE"
        assert customer["version"] == 1

    def test_cylinder_create_with_out_of_range_seal_kit_rejected(self, api):
        """PRD §3.1: "Registration validates seal-kit compatibility as a safety
        gate: the cylinder's `bore_mm` must fall within the kit's bore range with
        both bounds inclusive, the kit's `pressure_class_max` must cover the
        cylinder's `pressure_class` — a kit capped at `CLASS_3000` covers only
        `CLASS_3000` cylinders, while a `CLASS_5000` kit covers both classes —
        and the kit's `fluid_compat` must include the cylinder's `fluid_type`.
        A kit that fails any leg is rejected with `ERR_SEAL_KIT_INCOMPATIBLE`."

        Design: Corner/entities/cylinder_create_with_out_of_range_seal_kit_rejected
        """
        create_shop()
        wide_kit = create_seal_kit(
            kit_code="SK-120-PU", bore_min_mm=120, bore_max_mm=200,
            pressure_class_max="CLASS_5000",
            fluid_compat=["MINERAL_OIL", "PHOSPHATE_ESTER", "WATER_GLYCOL"],
            price_cents=32000, material="PU",
        )
        customer = create_customer()
        resp = api.create_cylinder(
            create_cylinder_payload(customer["id"], wide_kit["id"], serial_number="CYL-X01"),
            ADVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_SEAL_KIT_INCOMPATIBLE)
        # No cylinder persisted.
        data, meta = validate_paginated(
            api.list_cylinders(ADVISOR, params={"customer_id": customer["id"]})
        )
        assert meta["total_count"] == 0, f"no cylinder should persist, got {data}"

    def test_cylinder_create_with_fluid_incompatible_kit_rejected(self, api):
        """PRD §3.1: "the kit's `fluid_compat` must include the cylinder's
        `fluid_type`. A kit that fails any leg is rejected with
        `ERR_SEAL_KIT_INCOMPATIBLE`."

        Design: Corner/entities/cylinder_create_with_fluid_incompatible_kit_rejected
        """
        create_shop()
        kit = create_seal_kit()  # fluids [MINERAL_OIL, WATER_GLYCOL]
        customer = create_customer()
        resp = api.create_cylinder(
            create_cylinder_payload(
                customer["id"], kit["id"], serial_number="CYL-X02",
                fluid_type="PHOSPHATE_ESTER",
            ),
            ADVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_SEAL_KIT_INCOMPATIBLE)

    def test_work_order_create_computed_input_ignored(self, api):
        """PRD §3.2: "The system denormalizes the owning `customer_id` from the
        cylinder at creation, and the work order starts in `INTAKE` with
        `assigned_technician_id`, `actual_labor_hours`, `latest_cleanliness_code4`,
        `latest_cleanliness_code6`, `latest_cleanliness_code14`,
        `final_total_cents`, and `invoice_total_cents` all null,
        `cleanliness_passed` false, and `core_credit_applied_cents` zero."

        Design: Corner/entities/work_order_create_computed_input_ignored
        """
        md = setup_master_data()
        cylinder = create_cylinder(md.customer["id"], md.kit["id"], serial_number="CYL-X03")
        payload = create_work_order_payload(
            cylinder["id"], tier="STANDARD", promised_hours=96, complaint="slow leak"
        )
        # Client-supplied values for system-managed fields must not take effect.
        payload.update({"status": "CERTIFIED", "cleanliness_passed": True,
                        "final_total_cents": 1})
        wo = validate_success(api.create_work_order(payload, ADVISOR), 201)
        assert_work_order(wo)
        assert wo["status"] == "INTAKE"
        assert wo["cleanliness_passed"] is False
        assert wo["final_total_cents"] is None
        assert wo["invoice_total_cents"] is None
        assert wo["assigned_technician_id"] is None
        assert wo["core_credit_applied_cents"] == 0


class TestIntakeGuards:
    def test_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.9: "Required fields are present, and types and enum members are
        valid; failures are rejected with `ERR_INVALID_REQUEST`. This check runs
        first on every endpoint."

        Design: Corner/validations/missing_required_field_returns_invalid_request
        """
        create_shop()
        customer = create_customer()
        payload = create_cylinder_payload(customer["id"], "irrelevant",
                                          serial_number="CYL-V10")
        del payload["seal_kit_id"]  # seal_kit_id is a required registration input (§3.1)
        resp = api.create_cylinder(payload, ADVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_cylinder_retired_blocks_new_work_order(self, api):
        """PRD §3.2: "The referenced cylinder must be `ACTIVE`; opening a work
        order on a `RETIRED` or `EXCHANGED` unit is rejected with
        `ERR_CYLINDER_RETIRED`."

        Design: Corner/validations/cylinder_retired_blocks_new_work_order
        """
        sc = setup_quote_sent(rod_needed=False, honing_passes=0, estimated_labor_hours=3.0)
        get_success_data(
            api.authorize_scrap(sc.work_order["id"], make_customer_headers(sc.customer["id"]))
        )
        get_success_data(
            api.complete_scrap(sc.work_order["id"], {"disposal_method": "recycler"}, ADVISOR)
        )
        cyl = get_success_data(api.get_cylinder(sc.cylinder["id"], ADVISOR))
        assert cyl["status"] == "RETIRED"
        resp = api.create_work_order(
            create_work_order_payload(sc.cylinder["id"], tier="STANDARD",
                                      promised_hours=96, complaint="new job on retired unit"),
            ADVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_CYLINDER_RETIRED)

    def test_suspended_customer_blocks_new_work_order(self, api):
        """PRD §3.2: "The owning customer must not be `SUSPENDED`; attempting
        intake for one is rejected with `ERR_CUSTOMER_SUSPENDED`."
        PRD §3.1: "A `ShopAdmin` may suspend a customer, moving it from `ACTIVE`
        to `SUSPENDED`, and later reactivate it back to `ACTIVE`; a suspended
        customer cannot open new work orders."

        Design: Corner/validations_customer_lifecycle/suspended_customer_blocks_new_work_order
        """
        md = setup_master_data()
        cylinder = create_cylinder(md.customer["id"], md.kit["id"], serial_number="CYL-V20")
        suspended = get_success_data(api.suspend_customer(md.customer["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"
        resp = api.create_work_order(
            create_work_order_payload(cylinder["id"], tier="STANDARD", promised_hours=96),
            ADVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED)
        get_success_data(api.reactivate_customer(md.customer["id"], ADMIN))
        wo = validate_success(
            api.create_work_order(
                create_work_order_payload(cylinder["id"], tier="STANDARD", promised_hours=96),
                ADVISOR,
            ),
            201,
        )
        assert wo["status"] == "INTAKE"


class TestTurnaroundTierGate:
    def test_turnaround_boundary_24h_expedite_rejected_emergency_accepted(self, api):
        """PRD §3.2: "When `promised_hours` is at most `emergency_cutoff_hours` —
        24 hours by default — the `tier` must be `EMERGENCY`, so a promise of
        exactly 24 hours demands `EMERGENCY`."
        PRD §3.2: "A request whose promised hours demand a faster tier than the
        one requested is rejected with `ERR_PROMISE_INFEASIBLE`."

        Design: Difficulty/boundary_precision_check/turnaround_tier_boundary_24h
        """
        md = setup_master_data()
        cylinder = create_cylinder(md.customer["id"], md.kit["id"], serial_number="CYL-A01")
        resp = api.create_work_order(
            create_work_order_payload(cylinder["id"], tier="EXPEDITE", promised_hours=24,
                                      complaint="burst hose"),
            ADVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_PROMISE_INFEASIBLE)
        wo = validate_success(
            api.create_work_order(
                create_work_order_payload(cylinder["id"], tier="EMERGENCY", promised_hours=24,
                                          complaint="burst hose"),
                ADVISOR,
            ),
            201,
        )
        assert wo["status"] == "INTAKE"

    def test_turnaround_boundaries_25h_and_48h(self, api):
        """PRD §3.2: "When `promised_hours` is greater than the emergency cutoff
        but at most `expedite_cutoff_hours` — 48 hours by default — the `tier`
        must be `EMERGENCY` or `EXPEDITE`, so a promise of exactly 48 hours
        accepts `EXPEDITE`. Beyond the expedite cutoff any tier is allowed."

        Design: Difficulty/boundary_precision_check/turnaround_tier_boundary_24h
        """
        md = setup_master_data()
        cylinder = create_cylinder(md.customer["id"], md.kit["id"], serial_number="CYL-A02")
        # 25h: above the emergency cutoff — EXPEDITE suffices.
        wo25 = validate_success(
            api.create_work_order(
                create_work_order_payload(cylinder["id"], tier="EXPEDITE", promised_hours=25),
                ADVISOR,
            ),
            201,
        )
        assert wo25["status"] == "INTAKE"
        # 48h boundary inclusive: EXPEDITE accepted, STANDARD demands too slow a tier.
        wo48 = validate_success(
            api.create_work_order(
                create_work_order_payload(cylinder["id"], tier="EXPEDITE", promised_hours=48),
                ADVISOR,
            ),
            201,
        )
        assert wo48["status"] == "INTAKE"
        resp = api.create_work_order(
            create_work_order_payload(cylinder["id"], tier="STANDARD", promised_hours=48),
            ADVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_PROMISE_INFEASIBLE)
        # 49h: beyond the expedite cutoff — any tier allowed.
        wo49 = validate_success(
            api.create_work_order(
                create_work_order_payload(cylinder["id"], tier="STANDARD", promised_hours=49),
                ADVISOR,
            ),
            201,
        )
        assert wo49["status"] == "INTAKE"
