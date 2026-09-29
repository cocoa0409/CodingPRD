"""Entity-level shape: the fields a lease creation seeds, the retrieval and list
envelopes, the declared defaults, the server-derived and server-generated fields
a client cannot supply, the type constraints, and referential integrity."""

from test_helpers import (
    CANONICAL_LESSEE_EMAIL,
    CANONICAL_LESSEE_NAME,
    ERR_DUPLICATE_RECORD,
    ERR_INVALID_REQUEST,
    ERR_LEASE_NOT_FOUND,
    ERR_LESSEE_NOT_FOUND,
    ERR_MORTGAGE_LEASE_MISMATCH,
    NON_EXISTENT_UUID,
    assert_appraisal_shape,
    assert_common_fields,
    assert_deposit_conserved,
    assert_envelope,
    assert_envelope_conserved,
    assert_fields,
    factories as f,
    fixtures as fx,
    make_accountant_headers,
    make_asset_manager_headers,
    make_ground_tenant_headers,
    make_lessor_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_lease_creation_seeds_every_computed_field_from_its_inputs(api):
    """PRD §3.1: "`next_revaluation_date` is set to `commencement_date` advanced by `revaluation_interval_years` whole years."

    Design: Corner/entities/lease_creation_seeds_every_computed_field_from_its_inputs
    """
    lessee = fx.create_lessee(api)
    response = api.create_lease(
        f.lease_payload(lessee["id"], "PIER-71"), make_lessor_admin_headers()
    )
    lease = validate_success(response, expected_status=201)

    assert_fields(
        lease,
        premises_code="PIER-71",
        lessee_id=lessee["id"],
        lease_status="ACTIVE",
        rent_status="BASE_ONLY",
        current_annual_base_rent_cents=10000000,
        next_revaluation_date="2025-01-01T00:00:00Z",
        gfa_allocated_sqft=0,
        gfa_unallocated_sqft=200000,
        deposit_held_cents=5000000,
        deposit_applied_cents=0,
        deposit_refunded_cents=0,
        insurance_status="LAPSED",
        property_all_risk_limit_cents=0,
        builders_risk_limit_cents=0,
        lessor_additional_insured=False,
        arrears_balance_cents=0,
        percentage_rent_sublease_base_cents=0,
        version=1,
    )
    assert lease["insurance_expires_at"] is None
    assert lease["predecessor_lease_id"] is None
    assert lease["origin_mortgage_id"] is None
    assert_common_fields(lease)
    assert_envelope_conserved(lease)
    assert_deposit_conserved(lease)


def test_lease_and_lessee_retrieval_return_the_stored_rows(api):
    """PRD §2.3: "Single-resource reads set `response_type` to `"object"` and omit those four fields."

    Design: Corner/entities/lease_and_lessee_retrieval_return_the_stored_rows
    """
    env = fx.standard_lease(api, "PIER-72")

    response = api.get_lease(env["lease_id"], make_lessor_admin_headers())
    body = response.json()
    assert_envelope(body)
    assert body["response_type"] == "object"
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in body["meta"], field
    lease = validate_success(response)
    assert_fields(
        lease,
        id=env["lease_id"],
        premises_code="PIER-72",
        current_annual_base_rent_cents=10000000,
        total_permitted_gfa_sqft=200000,
        deposit_held_cents=5000000,
        version=1,
    )

    lessee = validate_success(
        api.get_lessee(env["lessee_id"], make_asset_manager_headers("am-1"))
    )
    assert_fields(
        lessee,
        id=env["lessee_id"],
        legal_name=CANONICAL_LESSEE_NAME,
        notice_email=CANONICAL_LESSEE_EMAIL,
        credit_rating_code="A",
    )


def test_lease_listing_paginates_and_filters_with_total_count_and_has_more(api):
    """PRD §2.3: "List responses set `response_type` to `"array"` and carry the four pagination fields in `meta`: the `limit` and `offset` actually applied, `total_count` (the number of rows matching the filter before the page window is applied), and `has_more` (true when `offset` plus the number of returned rows is still below `total_count`)."

    Design: Corner/entities/lease_listing_paginates_and_filters_with_total_count_and_has_more
    """
    lessee = fx.create_lessee(api)
    ids = {
        fx.create_lease(api, lessee["id"], code)["id"]
        for code in ("PIER-73A", "PIER-73B", "PIER-73C")
    }
    admin = make_lessor_admin_headers()

    first, meta_first = validate_paginated(
        api.list_leases(admin, {"limit": 2, "offset": 0})
    )
    assert len(first) == 2
    assert_fields(meta_first, limit=2, offset=0, total_count=3, has_more=True)

    second, meta_second = validate_paginated(
        api.list_leases(admin, {"limit": 2, "offset": 2})
    )
    assert len(second) == 1
    assert_fields(meta_second, limit=2, offset=2, total_count=3, has_more=False)

    seen = [row["id"] for row in first] + [row["id"] for row in second]
    assert len(seen) == len(set(seen))
    assert set(seen) == ids

    filtered, meta_filtered = validate_paginated(
        api.list_leases(
            admin, {"lessee_id": lessee["id"], "lease_status": "IN_DEFAULT"}
        )
    )
    assert filtered == []
    assert_fields(meta_filtered, total_count=0, has_more=False)


def test_lease_get_with_unknown_id_returns_404_not_found(api):
    """PRD §2.12: "Path parameters are validated **left to right**: the outer `{id}` is resolved first, and if it names no row the request fails with that parent's not-found code before any inner segment or body field is examined."

    Design: Corner/entities/lease_get_with_unknown_id_returns_404_not_found
    """
    response = api.get_lease(NON_EXISTENT_UUID, make_lessor_admin_headers())
    validate_error(response, ERR_LEASE_NOT_FOUND, expected_status=404)

    body = response.json()
    assert_envelope(body)
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]

    rows, meta = validate_paginated(api.list_leases(make_lessor_admin_headers()))
    assert rows == []
    assert meta["total_count"] == 0


def test_lease_creation_missing_a_required_field_is_rejected(api):
    """PRD §3.1: "The `LessorAdmin` supplies the tenant as `lessee_id`, the ground parcel as `premises_code`, the term as `commencement_date` and `expiration_date`, the opening rent as `initial_annual_base_rent_cents`, the revaluation cadence as `revaluation_interval_years`, the two collar bounds as `reval_collar_min_uplift_bps` and `reval_collar_max_uplift_bps`, the turnover rent terms as `percentage_rent_rate_bps` and `percentage_rent_breakpoint_cents`, the use clause as `permitted_use_code`, the development envelope as `total_permitted_gfa_sqft`, the two agreed valuations as `improvements_value_cents` and `reversion_land_value_cents`, the end-of-term condition standard as `reversion_standard_code`, and the deposit as `security_deposit_cents`."

    Design: Corner/entities/lease_creation_missing_required_reversion_standard_rejected
    """
    lessee = fx.create_lessee(api)
    admin = make_lessor_admin_headers()

    for omitted in ("reversion_standard_code", "security_deposit_cents"):
        payload = f.lease_payload(lessee["id"], "PIER-74")
        payload.pop(omitted)
        validate_error(
            api.create_lease(payload, admin),
            ERR_INVALID_REQUEST,
            expected_status=400,
        )

    rows, meta = validate_paginated(api.list_leases(admin))
    assert rows == []
    assert meta["total_count"] == 0


def test_omitted_optional_fields_take_their_declared_defaults(api):
    """PRD §3.6: "Optionally the application may carry `parent_transfer_id`, naming the sublease this sub-sublease sits beneath; `transferee_credit_rating_code`, which defaults to `BBB` and takes the same `AAA`, `A`, `BBB`, `SPECULATIVE` scale as the tenant register; and `consent_deposit_cents`, a deposit tendered up front that defaults to 0."

    Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
    """
    lessee = validate_success(
        api.create_lessee(
            {"legal_name": CANONICAL_LESSEE_NAME, "notice_email": CANONICAL_LESSEE_EMAIL},
            make_lessor_admin_headers(),
        ),
        expected_status=201,
    )
    assert lessee["credit_rating_code"] == "BBB"
    lease = fx.create_lease(api, lessee["id"], "PIER-75")
    tenant = make_ground_tenant_headers(lessee["id"])

    sublease = validate_success(
        api.create_transfer(
            {
                "lease_id": lease["id"],
                "transfer_type": "SUBLEASE",
                "term_start": "2027-01-01T00:00:00Z",
                "term_end": "2030-01-01T00:00:00Z",
                "transferee_legal_name": "Wavelength Grocers LLC",
                "premises_unit_code": "UNIT-A",
                "annual_sublease_rent_cents": 12000000,
                "sublet_area_sqft": 50000,
            },
            tenant,
        ),
        expected_status=201,
    )
    assert_fields(sublease, transferee_credit_rating_code="BBB",
                  consent_deposit_cents=0)
    assert sublease["parent_transfer_id"] is None
    assert sublease["net_consideration_cents"] is None

    loss_event = validate_success(
        api.report_loss_event(
            lease["id"],
            {
                "event_type": "CASUALTY",
                "scope_code": "TEMPORARY",
                "occurred_at": "2026-07-01T00:00:00Z",
            },
            tenant,
        ),
        expected_status=201,
    )
    assert_fields(loss_event, damage_estimate_cents=0, damaged_area_sqft=0)


def test_transfer_request_computed_fields_are_server_derived(api):
    """PRD §3.6: "The accepted request opens in `SUBMITTED` with every priced field null, and the request list can be narrowed by `lease_id`, by `parent_transfer_id`, by `transferee_lessee_id`, by `transfer_type` and by status."

    Design: Corner/entities/transfer_request_computed_fields_are_server_derived_input_ignored
    """
    env = fx.standard_lease(api, "PIER-76")

    submitted = validate_success(
        api.create_transfer(
            {
                "lease_id": env["lease_id"],
                "transfer_type": "SUBLEASE",
                "term_start": "2027-01-01T00:00:00Z",
                "term_end": "2030-01-01T00:00:00Z",
                "transferee_legal_name": "Wavelength Grocers LLC",
                "premises_unit_code": "UNIT-A",
                "annual_sublease_rent_cents": 12000000,
                "sublet_area_sqft": 50000,
                "consent_deposit_cents": 0,
                "total_transfer_fee_cents": 1,
                "status": "ACTIVE",
                "tier_depth": 9,
            },
            env["tenant"],
        ),
        expected_status=201,
    )
    # The supplied status, tier_depth and fee total are all ignored.
    assert_fields(submitted, status="SUBMITTED", submitted_late=False,
                  tier_depth=1, transfer_fee_paid_cents=0)
    for field in ("allocable_base_rent_cents", "transfer_fee_gross_cents",
                  "admin_charge_cents", "late_surcharge_cents",
                  "total_transfer_fee_cents"):
        assert submitted[field] is None, field


def test_lease_system_fields_are_server_generated_and_input_is_ignored(api):
    """PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/lease_system_fields_are_server_generated_input_ignored
    """
    lessee = fx.create_lessee(api)
    admin = make_lessor_admin_headers()
    payload = f.lease_payload(lessee["id"], "PIER-77")
    payload.update({
        "id": "11111111-1111-4111-8111-111111111111",
        "version": 47,
        "lease_status": "TERMINATED",
    })

    lease = validate_success(api.create_lease(payload, admin), expected_status=201)
    assert lease["id"] != "11111111-1111-4111-8111-111111111111"
    assert_fields(lease, version=1, lease_status="ACTIVE")
    assert_common_fields(lease)
    assert lease["created_at"] == lease["updated_at"]

    amended = validate_success(
        api.amend_terms(lease["id"], {"percentage_rent_rate_bps": 800}, admin)
    )
    assert_fields(
        amended,
        id=lease["id"],
        created_at=lease["created_at"],
        version=2,
        percentage_rent_rate_bps=800,
        percentage_rent_breakpoint_cents=100000000,
        permitted_use_code="RETAIL_MIXED",
    )
    assert amended["updated_at"] >= lease["created_at"]


def test_invalid_enum_and_out_of_range_values_are_rejected(api):
    """PRD §2.6: "A request carrying a negative money amount, a negative area, a basis-point figure below 0 or above 10,000, or a condition score outside the inclusive range 0 to 100 is rejected with `ERR_INVALID_REQUEST` (HTTP 400) before any business rule is consulted."

    Design: Corner/entities/invalid_enum_and_out_of_range_values_rejected
    """
    env = fx.standard_lease(api, "PIER-78")
    admin = make_lessor_admin_headers()

    # An undeclared use code is malformed, not ERR_USE_NOT_PERMITTED.
    validate_error(
        api.create_alteration(
            env["lease_id"],
            f.alteration_payload(proposed_use_code="OFFICE_TOWER",
                                 requested_gfa_sqft=1000,
                                 construction_window_end="2027-02-01T00:00:00Z",
                                 estimated_cost_cents=100000),
            env["tenant"],
        ),
        ERR_INVALID_REQUEST,
        expected_status=400,
    )
    validate_error(
        api.post_rent_charge(
            env["lease_id"], f.rent_charge_payload(-500, "negative charge"),
            make_accountant_headers("acct-1"),
        ),
        ERR_INVALID_REQUEST,
        expected_status=400,
    )
    validate_error(
        api.amend_terms(env["lease_id"], {"reval_collar_max_uplift_bps": 10001}, admin),
        ERR_INVALID_REQUEST,
        expected_status=400,
    )
    validate_error(
        api.report_loss_event(
            env["lease_id"],
            f.loss_event_payload(event_type="FLOOD"),
            make_asset_manager_headers("am-1"),
        ),
        ERR_INVALID_REQUEST,
        expected_status=400,
    )

    lease = fx.read_lease(api, env["lease_id"])
    assert_fields(lease, arrears_balance_cents=0, reval_collar_max_uplift_bps=5000,
                  version=1)
    _rows, alterations = validate_paginated(api.list_alterations(admin))
    assert alterations["total_count"] == 0
    _rows, losses = validate_paginated(api.list_loss_events(admin))
    assert losses["total_count"] == 0


def test_appraisal_submission_is_immutable_with_no_version_and_no_mutator(api):
    """PRD §3.3: "Submissions are immutable once lodged, which is why they carry no `updated_at` and no `version`."

    Design: Corner/entities/appraisal_submission_is_immutable_with_no_version_and_no_mutator
    """
    env = fx.standard_lease(api, "PIER-79")
    admin = make_lessor_admin_headers()
    reval = fx.open_revaluation(api, env["lease_id"])
    lodged = validate_success(
        api.lodge_appraisal(
            reval["id"], f.appraisal_payload("LESSOR", 14000000, "COMPARABLE_LAND"),
            make_lessor_admin_headers("appraiser-lessor-1"),
        ),
        expected_status=201,
    )

    fetched = validate_success(api.get_appraisal(lodged["id"], admin))
    assert_fields(
        fetched,
        revaluation_id=reval["id"],
        appointed_by="LESSOR",
        appraiser_user_id="appraiser-lessor-1",
        appraised_annual_rent_cents=14000000,
        valuation_method_code="COMPARABLE_LAND",
        round_number=1,
    )
    assert_appraisal_shape(fetched)

    validate_error(
        api.lodge_appraisal(
            reval["id"], f.appraisal_payload("LESSOR", 15000000, "RESIDUAL_LAND"),
            make_lessor_admin_headers("appraiser-lessor-1"),
        ),
        ERR_DUPLICATE_RECORD,
        expected_status=409,
    )
    unchanged = validate_success(api.get_appraisal(lodged["id"], admin))
    assert unchanged["appraised_annual_rent_cents"] == 14000000
    rows, meta = validate_paginated(
        api.list_appraisals(admin, {"revaluation_id": reval["id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_unknown_parent_ids_return_the_parent_specific_not_found_code(api):
    """PRD §2.12: "A revaluation opened under a lease that does not exist reports `ERR_LEASE_NOT_FOUND`, not a revaluation error."

    Design: Corner/entities/lease_creation_with_unknown_lessee_id_returns_404
    """
    admin = make_lessor_admin_headers()

    validate_error(
        api.create_lease(f.lease_payload(NON_EXISTENT_UUID, "PIER-80"), admin),
        ERR_LESSEE_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.record_mortgage(NON_EXISTENT_UUID, f.senior_mortgage_payload(), admin),
        ERR_LEASE_NOT_FOUND,
        expected_status=404,
    )

    _leases, lease_meta = validate_paginated(api.list_leases(admin))
    assert lease_meta["total_count"] == 0
    _mortgages, mortgage_meta = validate_paginated(api.list_mortgages(admin))
    assert mortgage_meta["total_count"] == 0


def test_estoppel_request_naming_another_leases_mortgage_is_rejected(api):
    """PRD §2.12: "An estoppel certificate whose `requested_by_mortgage_id` names a real mortgage that encumbers a *different* lease is refused with `ERR_MORTGAGE_LEASE_MISMATCH` (HTTP 422), and a mortgagee cure whose `mortgage_id` names a mortgage that is not on the notice's lease is refused with the same code."

    Design: Corner/entities/estoppel_request_naming_another_leases_mortgage_rejected
    """
    lessee = fx.create_lessee(api)
    lease_a = fx.create_lease(api, lessee["id"], "PIER-81A")
    lease_b = fx.create_lease(api, lessee["id"], "PIER-81B")
    fx.file_insurance(api, lease_a["id"])
    mortgage_b = fx.record_senior_mortgage(api, lease_b["id"])
    admin = make_lessor_admin_headers()
    version_a = fx.lease_version(api, lease_a["id"])

    validate_error(
        api.issue_estoppel(
            f.estoppel_payload(lease_a["id"], mortgage_b["id"], version_a), admin
        ),
        ERR_MORTGAGE_LEASE_MISMATCH,
        expected_status=422,
    )
    _rows, meta = validate_paginated(
        api.list_estoppels(admin, {"lease_id": lease_a["id"]})
    )
    assert meta["total_count"] == 0
    assert fx.lease_version(api, lease_a["id"]) == version_a
