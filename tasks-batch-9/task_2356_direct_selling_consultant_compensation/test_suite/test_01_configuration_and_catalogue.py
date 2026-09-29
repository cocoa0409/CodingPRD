"""Plan, tax-map and catalogue configuration: fields, defaults, listings and uniqueness."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_compensation_plan,
    assert_consultant,
    assert_instant,
    assert_tax_jurisdiction,
    constants as k,
    factories as f,
    fixtures as fx,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_applicant_headers,
    same_instant,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["commission_analyst_headers"]
LEGAL = TEST_USERS["legal_reviewer_headers"]
CONSULTANT = TEST_USERS["consultant_headers"]
APPLICANT = TEST_USERS["applicant_headers"]


def test_plan_creation_returns_every_declared_field(api):
    """Everything downstream is parameterised by a **compensation plan**, which a `PlatformAdmin`
    creates by supplying a `plan_code` — a business identifier of 1 to 32 characters, unique across
    all plans, with a collision rejected as `ERR_DUPLICATE_PLAN_CODE` — and a display `name`. The
    plan tracks `consultant_count`, the number of consultants enrolled on it whose status is not
    `TERMINATED`, which starts at 0 and moves as consultants are minted, terminated and reinstated.

    Design: Corner/entities/compensation_plan_creation_returns_every_declared_field
    """
    response = api.create_compensation_plan(
        {"plan_code": "PLAN-A", "name": "Consultant Plan A"}, ADMIN
    )
    plan = validate_success(response, 201)

    assert is_valid_uuid(plan["id"]), f"plan id must be a UUID, got {plan['id']!r}"
    assert plan["plan_code"] == "PLAN-A"
    assert plan["name"] == "Consultant Plan A"
    assert plan["compression_mode"] == "DYNAMIC"
    assert plan["point_value_cents"] == 100
    assert plan["consultant_count"] == 0, "consultant_count starts at 0"
    assert plan["version"] == 1

    assert len(plan["rank_ladder"]) == 4, "the default ladder has four rungs"
    assert len(plan["pv_bonus_bands"]) == 3, "the default bonus ladder has three bands"
    assert_compensation_plan(plan)


def test_plan_defaults_applied_when_optional_fields_omitted(api):
    """Every other plan field has a default, so a minimal call yields the canonical plan described
    here. Each product also carries `volume_points_per_unit` (default 0, at least 0), a
    `commissionable` flag (default true) which when false keeps the unit's points out of
    commissionable volume entirely, a `buyback_eligible` flag (default true) which when false
    forbids the product from ever appearing on a buyback line, and an `is_starter_kit` flag
    (default false) which when true is what makes the product usable as an enrollment starter kit.

    Design: Corner/entities/plan_defaults_applied_when_optional_fields_omitted
    """
    plan = validate_success(
        api.create_compensation_plan({"plan_code": "PLAN-D", "name": "Defaults Plan"}, ADMIN), 201
    )

    assert plan["payline_min_pv_points"] == 200
    assert plan["pv_bonus_min_points"] == 100
    assert plan["active_leg_min_points"] == 300
    assert plan["pv_bonus_cap_cents"] == 50000
    assert plan["probation_keep_bp"] == 5000
    assert plan["withhold_tier_threshold_cents"] == 20000
    assert plan["withhold_low_bp"] == 1000
    assert plan["withhold_high_bp"] == 2500
    assert plan["min_payout_cents"] == 2500
    assert plan["seventy_rule_bp"] == 7000
    assert plan["buyback_rate_bp"] == 9000
    assert plan["buyback_window_days"] == 365
    assert plan["restock_free_limit_cents"] == 45000
    assert plan["restock_fee_bp"] == 500
    assert plan["sanction_cooloff_days"] == 30
    assert plan["appeal_window_days"] == 14
    assert plan["reinstatement_window_days"] == 180
    assert plan["max_identity_attempts"] == 2
    assert plan["free_shipping_threshold_cents"] == 25000
    assert plan["flat_shipping_cents"] == 995
    assert plan["consecutive_qualifying_periods"] == 2
    assert plan["maintenance_grace_periods"] == 1
    assert plan["senior_rank_bump_bp"] == 200

    ladder = plan["rank_ladder"]
    assert [rung["rank_code"] for rung in ladder] == [
        "CONSULTANT",
        "SENIOR_CONSULTANT",
        "DIRECTOR",
        "EXECUTIVE_DIRECTOR",
    ]
    assert [rung["rank_order"] for rung in ladder] == [1, 2, 3, 4]

    product = validate_success(
        api.create_product(
            {
                "sku": "PLAIN",
                "name": "Plain Product",
                "wholesale_price_cents": 500,
                "srp_cents": 1000,
            },
            ADMIN,
        ),
        201,
    )
    assert product["volume_points_per_unit"] == 0
    assert product["commissionable"] is True
    assert product["buyback_eligible"] is True
    assert product["is_starter_kit"] is False


def test_product_and_jurisdiction_reads_return_stored_rows(api):
    """Two fields are derived from that boolean and are not supplied by the caller:
    `tax_basis_mode` is `SRP` when a facilitator agreement is active and `NET_PRICE` otherwise, and
    `remitter` is `COMPANY` when a facilitator agreement is active and `CONSULTANT` otherwise.

    Design: Corner/entities/product_and_jurisdiction_reads_return_stored_rows
    """
    env = fx.setup_environment(api, products=(k.PRODUCT_KIT,), periods=())

    jurisdiction = validate_success(
        api.get_tax_jurisdiction(env["jurisdictions"]["TX"]["id"], CONSULTANT)
    )
    assert jurisdiction["state_code"] == "TX"
    assert jurisdiction["tax_rate_bp"] == 825
    assert jurisdiction["tax_basis_mode"] == "SRP"
    assert jurisdiction["remitter"] == "COMPANY"
    assert_tax_jurisdiction(jurisdiction)

    product = validate_success(api.get_product(env["products"]["KIT-STD"]["id"], APPLICANT))
    assert product["sku"] == "KIT-STD"
    assert product["is_starter_kit"] is True
    assert product["volume_points_per_unit"] == 0
    assert product["commissionable"] is True
    assert product["buyback_eligible"] is True

    plan = validate_success(api.get_compensation_plan(env["plan"]["id"], LEGAL))
    assert plan["plan_code"] == "PLAN-A"


def test_listing_endpoints_filter_and_paginate(api):
    """`limit` caps the number of rows returned; it defaults to 10, its minimum accepted value is 1
    and its maximum is 100. Unless a list endpoint's own description in §4 says otherwise, rows are
    returned sorted by `created_at` ascending. Products are listable and filterable by `sku`,
    `is_starter_kit` and `buyback_eligible`.

    Design: Corner/entities/listing_endpoints_filter_and_paginate
    """
    fx.setup_environment(
        api, products=(k.PRODUCT_KIT, k.PRODUCT_SERUM, k.PRODUCT_SAMPLE), periods=()
    )

    rows, meta = validate_paginated(api.list_products(ADMIN))
    assert len(rows) == 3
    assert meta["total_count"] == 3
    assert rows[0]["sku"] == "KIT-STD", "rows come back in creation order"

    kit_rows, kit_meta = validate_paginated(api.list_products(ADMIN, params={"is_starter_kit": True}))
    assert len(kit_rows) == 1
    assert kit_meta["total_count"] == 1, "total_count describes the filtered set"
    assert kit_rows[0]["sku"] == "KIT-STD"

    nobb_rows, nobb_meta = validate_paginated(
        api.list_products(ADMIN, params={"buyback_eligible": False})
    )
    assert len(nobb_rows) == 1
    assert nobb_meta["total_count"] == 1
    assert nobb_rows[0]["sku"] == "SAMPLE"

    page1, meta1 = validate_paginated(api.list_products(ADMIN, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert page1[0]["sku"] == "KIT-STD"
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_products(ADMIN, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert page2[0]["sku"] == "SAMPLE"
    assert meta2["has_more"] is False
    assert not ({row["id"] for row in page1} & {row["id"] for row in page2}), "pages are disjoint"

    combo, _ = validate_paginated(
        api.list_products(ADMIN, params={"is_starter_kit": False, "limit": 1})
    )
    assert len(combo) == 1, "a filter composes with pagination"


NOT_FOUND_CASES = [
    ("get_compensation_plan", "ERR_PLAN_NOT_FOUND"),
    ("get_enrollment_application", "ERR_APPLICATION_NOT_FOUND"),
    ("get_consultant", "ERR_CONSULTANT_NOT_FOUND"),
    ("get_product_order", "ERR_ORDER_NOT_FOUND"),
    ("get_qualification_period", "ERR_PERIOD_NOT_FOUND"),
    ("get_period_qualification", "ERR_QUALIFICATION_NOT_FOUND"),
    ("get_commission_run", "ERR_RUN_NOT_FOUND"),
    ("get_commission_statement", "ERR_STATEMENT_NOT_FOUND"),
    ("get_buyback_request", "ERR_BUYBACK_NOT_FOUND"),
    ("get_compliance_case", "ERR_CASE_NOT_FOUND"),
    ("get_income_disclosure_statement", "ERR_DISCLOSURE_NOT_FOUND"),
    ("get_product", "ERR_PRODUCT_NOT_FOUND"),
    ("get_tax_jurisdiction", "ERR_JURISDICTION_NOT_FOUND"),
]


@pytest.mark.parametrize("getter_name,expected_error", NOT_FOUND_CASES)
def test_not_found_errors_for_every_entity_path(api, getter_name, expected_error):
    """The addressed entity determines the error: `plan_id` yields `ERR_PLAN_NOT_FOUND`,
    `jurisdiction_id` yields `ERR_JURISDICTION_NOT_FOUND`, `product_id` yields
    `ERR_PRODUCT_NOT_FOUND`, `application_id` yields `ERR_APPLICATION_NOT_FOUND`, `consultant_id`
    yields `ERR_CONSULTANT_NOT_FOUND`, `order_id` yields `ERR_ORDER_NOT_FOUND`, `period_id` yields
    `ERR_PERIOD_NOT_FOUND`, `period_qualification_id` yields `ERR_QUALIFICATION_NOT_FOUND`,
    `run_id` yields `ERR_RUN_NOT_FOUND`, `statement_id` addressing a commission statement yields
    `ERR_STATEMENT_NOT_FOUND` while `statement_id` addressing an income disclosure statement yields
    `ERR_DISCLOSURE_NOT_FOUND`, `buyback_id` yields `ERR_BUYBACK_NOT_FOUND`, and `case_id` yields
    `ERR_CASE_NOT_FOUND`. Every one of these carries HTTP 404.

    Design: Corner/entities/not_found_errors_for_every_entity_path
    """
    response = getattr(api, getter_name)(NON_EXISTENT_UUID, ADMIN)
    error = validate_error(response, expected_error, 404)
    assert error.get("message"), f"{expected_error} must carry a non-empty message"


def test_missing_required_fields_and_bad_shapes_rejected_with_validation(api):
    """**Request shape** — every required field present; every enum value a declared member; every
    integer an integer inside its declared range; every array inside its declared length bounds;
    every datetime an ISO 8601 value with a `Z` offset; `limit` between 1 and 100 and `offset` at or
    above 0. Any violation is the single generic `ERR_VALIDATION` (HTTP 400).

    Design: Corner/entities/missing_required_fields_and_bad_shapes_rejected_with_validation
    """
    env = fx.setup_environment(api, products=(k.PRODUCT_KIT,), periods=())

    validate_error(
        api.create_compensation_plan({"plan_code": "PLAN-B"}, ADMIN), "ERR_VALIDATION", 400
    )
    validate_error(
        api.create_product(
            {"sku": "SERUM", "name": "Renewal Serum", "wholesale_price_cents": 2000}, ADMIN
        ),
        "ERR_VALIDATION",
        400,
    )
    validate_error(
        api.create_tax_jurisdiction({"state_code": "CA", "tax_rate_bp": 725}, ADMIN),
        "ERR_VALIDATION",
        400,
    )
    validate_error(
        api.create_enrollment_application(
            {
                "applicant_email": "zoe@ex.test",
                "applicant_full_name": "Zoe Gap",
                "compensation_plan_id": env["plan"]["id"],
                "starter_kit_product_id": env["products"]["KIT-STD"]["id"],
            },
            ADMIN,
        ),
        "ERR_VALIDATION",
        400,
    )

    plans, _ = validate_paginated(api.list_compensation_plans(ADMIN))
    assert len(plans) == 1, "a rejected create writes nothing"
    products, _ = validate_paginated(api.list_products(ADMIN))
    assert len(products) == 1, "a rejected create writes nothing"


def test_computed_fields_ignore_client_supplied_values(api):
    """Unknown body keys, and any attempt to supply a server-computed field, are silently ignored
    rather than rejected. `tax_total_cents` is the sum of the already-rounded `line_tax_cents`
    values; the rate is never applied to the order-level basis, because summing rounded lines and
    rounding a summed basis give different answers and only the former is correct here.

    Design: Corner/entities/computed_fields_ignore_client_supplied_values
    """
    env = fx.setup_environment(api, products=(k.PRODUCT_KIT, k.PRODUCT_SERUM))
    application = fx.create_application(api, env, "computed@ex.test")
    assert application["kit_tax_cents"] == 1229
    assert application["kit_total_cents"] == 11129
    consultant = fx.enroll_root(api, env, email="alice@example.com")

    lines = fx.lines_for(env, ("SERUM", 5))
    payload = f.product_order_payload(consultant["id"], lines, order_type="BUSINESS_SUPPLY")
    order = validate_success(api.create_product_order(payload, ADMIN), 201)

    assert order["merchandise_subtotal_cents"] == 10000
    assert order["srp_basis_cents"] == 20000
    assert order["tax_total_cents"] == 1650
    assert order["shipping_cents"] == 995
    assert order["total_due_cents"] == 12645
    assert order["total_volume_points"] == 100
    assert order["commissionable_volume_points"] == 100
    assert order["returned_volume_points"] == 0
    assert order["refunded_cents"] == 0
    assert order["volume_posted"] is False
    assert order["tax_rate_bp"] == 825
    assert order["tax_basis_mode"] == "SRP"

    dictated = f.product_order_payload(consultant["id"], lines, order_type="BUSINESS_SUPPLY")
    dictated["merchandise_subtotal_cents"] = 1
    dictated["tax_total_cents"] = 1
    dictated["total_due_cents"] = 1
    dictated["volume_posted"] = True
    second = validate_success(api.create_product_order(dictated, ADMIN), 201)

    assert second["merchandise_subtotal_cents"] == 10000
    assert second["tax_total_cents"] == 1650
    assert second["total_due_cents"] == 12645
    assert second["volume_posted"] is False, "a client cannot dictate a server-computed field"


def test_system_fields_generated_and_client_values_ignored(api):
    """Every resource the API exposes carries a server-minted `id`, formatted as a UUID with no type
    prefix, and a `created_at` timestamp: an ISO 8601 UTC value with three fractional digits, for
    example `2026-08-01T00:00:00.000Z`. Clients never supply either. Almost every resource
    additionally carries `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation — and
    `version`, a system-managed integer that starts at 1 and increments by exactly 1 on every
    mutation of the row.

    Design: Corner/entities/system_fields_generated_and_client_values_ignored
    """
    plan = validate_success(
        api.create_compensation_plan({"plan_code": "PLAN-S", "name": "System Fields Plan"}, ADMIN),
        201,
    )
    assert is_valid_uuid(plan["id"])
    assert is_iso8601_timestamp(plan["created_at"]), "created_at is an ISO 8601 UTC value"
    assert is_iso8601_timestamp(plan["updated_at"]), "updated_at is an ISO 8601 UTC timestamp"
    assert plan["version"] == 1

    patched = validate_success(
        api.update_compensation_plan(plan["id"], {"min_payout_cents": 3000}, ADMIN)
    )
    assert patched["id"] == plan["id"]
    assert patched["created_at"] == plan["created_at"], "created_at survives an update"
    assert patched["version"] == 2, "version increments by exactly 1 on every mutation"
    assert patched["min_payout_cents"] == 3000

    forged = validate_success(
        api.create_compensation_plan(
            {
                "plan_code": "PLAN-S2",
                "name": "Forged System Fields",
                "id": NON_EXISTENT_UUID,
                "created_at": "2020-01-01T00:00:00Z",
                "updated_at": "2020-01-01T00:00:00Z",
                "version": 99,
            },
            ADMIN,
        ),
        201,
    )
    assert forged["id"] != NON_EXISTENT_UUID
    assert is_valid_uuid(forged["id"])
    assert not same_instant(forged["created_at"], "2020-01-01T00:00:00Z"), (
        "clients never supply created_at, so the forged value was discarded"
    )
    assert not same_instant(forged["updated_at"], "2020-01-01T00:00:00Z"), (
        "the forged updated_at was discarded too"
    )
    assert forged["version"] == 1


def test_type_constraints_reject_unknown_enums_and_out_of_range_integers(api):
    """A `limit` outside 1 through 100, or a negative `offset`, is a shape error and is rejected with
    `ERR_VALIDATION`. Sales tax treatment is registered per state as a **tax jurisdiction**, again
    by a `PlatformAdmin`, carrying a `state_code` of exactly two uppercase letters and unique across
    all jurisdictions — a repeat is `ERR_DUPLICATE_JURISDICTION` — a `tax_rate_bp` between 0 and
    2,000 inclusive, and a `facilitator_agreement_active` boolean recording whether the company
    holds a marketplace-facilitator agreement in that state.

    Design: Corner/entities/type_constraints_reject_unknown_enums_and_out_of_range_integers
    """
    env = fx.setup_environment(api, products=(k.PRODUCT_KIT, k.PRODUCT_SERUM))
    consultant = fx.enroll_root(api, env)
    serum_id = env["products"]["SERUM"]["id"]

    bad_enum = f.product_order_payload(
        consultant["id"], [f.order_line(serum_id, 5)], order_type="WHOLESALE_CLUB"
    )
    validate_error(api.create_product_order(bad_enum, ADMIN), "ERR_VALIDATION", 400)

    zero_quantity = f.product_order_payload(
        consultant["id"], [f.order_line(serum_id, 0)], order_type="BUSINESS_SUPPLY"
    )
    validate_error(api.create_product_order(zero_quantity, ADMIN), "ERR_VALIDATION", 400)

    no_lines = f.product_order_payload(consultant["id"], [], order_type="BUSINESS_SUPPLY")
    validate_error(api.create_product_order(no_lines, ADMIN), "ERR_VALIDATION", 400)

    validate_error(
        api.create_tax_jurisdiction(
            {"state_code": "NV", "tax_rate_bp": -1, "facilitator_agreement_active": False}, ADMIN
        ),
        "ERR_VALIDATION",
        400,
    )
    validate_error(api.list_products(ADMIN, params={"limit": 0}), "ERR_VALIDATION", 400)

    orders, _ = validate_paginated(api.list_product_orders(ADMIN))
    assert orders == [], "nothing was written by any rejected call"


def test_tax_jurisdiction_is_immutable_with_no_update_path(api):
    """`TaxJurisdiction` is the single exception. A jurisdiction row is immutable after creation, has
    no update endpoint, and carries only `id` and `created_at`: both `updated_at` and `version` are
    absent from its representation.

    Design: Corner/entities/tax_jurisdiction_is_immutable_with_no_update_path
    """
    env = fx.setup_environment(api, products=(k.PRODUCT_KIT,), periods=())
    jurisdiction_id = env["jurisdictions"]["TX"]["id"]

    stored = validate_success(api.get_tax_jurisdiction(jurisdiction_id, ADMIN))
    assert "version" not in stored, "a jurisdiction carries no version"
    assert "updated_at" not in stored, "a jurisdiction carries no updated_at"
    assert is_iso8601_timestamp(stored["created_at"]), "a jurisdiction carries created_at"

    validate_error(
        api.create_tax_jurisdiction(
            {"state_code": "TX", "tax_rate_bp": 900, "facilitator_agreement_active": False}, ADMIN
        ),
        "ERR_DUPLICATE_JURISDICTION",
        409,
    )

    reread = validate_success(api.get_tax_jurisdiction(jurisdiction_id, ADMIN))
    assert reread["state_code"] == "TX"
    assert reread["tax_rate_bp"] == 825, "the stored rate can never be edited in place"
    assert reread["created_at"] == stored["created_at"]


def test_body_foreign_keys_and_nested_line_references_must_resolve(api):
    """The same catalogue serves body references. A `compensation_plan_id` that does not resolve
    yields `ERR_PLAN_NOT_FOUND`; a `sponsor_consultant_id` or `consultant_id` that does not resolve
    yields `ERR_CONSULTANT_NOT_FOUND`; a `starter_kit_product_id`, or a `product_id` inside a line,
    yields `ERR_PRODUCT_NOT_FOUND`; an `applicant_state_code` or `ship_to_state_code` for which no
    jurisdiction is registered yields `ERR_JURISDICTION_NOT_FOUND`; a `posted_period_code` or
    `qualification_period_id` that names no period yields `ERR_PERIOD_NOT_FOUND`; a
    `product_order_id` inside a buyback line yields `ERR_ORDER_NOT_FOUND`; and a
    `commission_run_id` that does not resolve yields `ERR_RUN_NOT_FOUND`.

    Design: Corner/entities/body_foreign_keys_and_nested_line_references_must_resolve
    """
    env = fx.setup_environment(api, products=(k.PRODUCT_KIT, k.PRODUCT_SERUM))
    consultant = fx.enroll_root(api, env)
    kit_id = env["products"]["KIT-STD"]["id"]
    serum_id = env["products"]["SERUM"]["id"]
    period = env["periods"]["2026-08"]

    validate_error(
        api.create_enrollment_application(
            f.enrollment_application_payload(
                NON_EXISTENT_UUID, kit_id, applicant_email="ghost@ex.test"
            ),
            ADMIN,
        ),
        "ERR_PLAN_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_enrollment_application(
            f.enrollment_application_payload(
                env["plan"]["id"], NON_EXISTENT_UUID, applicant_email="ghost2@ex.test"
            ),
            ADMIN,
        ),
        "ERR_PRODUCT_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_product_order(
            f.product_order_payload(
                NON_EXISTENT_UUID, [f.order_line(serum_id, 5)], order_type="BUSINESS_SUPPLY"
            ),
            ADMIN,
        ),
        "ERR_CONSULTANT_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_product_order(
            f.product_order_payload(
                consultant["id"],
                [f.order_line(serum_id, 5)],
                order_type="BUSINESS_SUPPLY",
                ship_to_state_code="CA",
            ),
            ADMIN,
        ),
        "ERR_JURISDICTION_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_product_order(
            f.product_order_payload(
                consultant["id"],
                [f.order_line(NON_EXISTENT_UUID, 5)],
                order_type="BUSINESS_SUPPLY",
            ),
            ADMIN,
        ),
        "ERR_PRODUCT_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_buyback_request(
            f.buyback_request_payload(
                consultant["id"], [f.buyback_line(NON_EXISTENT_UUID, serum_id, 1)]
            ),
            ADMIN,
        ),
        "ERR_ORDER_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_commission_run(
            f.commission_run_payload(NON_EXISTENT_UUID, period["version"]), ANALYST
        ),
        "ERR_PERIOD_NOT_FOUND",
        404,
    )

    orders, _ = validate_paginated(api.list_product_orders(ADMIN))
    assert orders == [], "no row was created by any unresolved reference"


def test_genealogy_graph_keeps_upline_path_depth_and_counts_consistent(api):
    """Two derived fields keep it navigable: `upline_path`, an ordered array of consultant
    identifiers running from the root down to the direct sponsor and excluding the consultant
    themselves, and `genealogy_depth`, the number of entries in that array. A root consultant has an
    empty `upline_path` and a `genealogy_depth` of 0.

    Design: Corner/entities/genealogy_graph_keeps_upline_path_depth_and_counts_consistent
    """
    people = fx.setup_genealogy_abc(api)
    a, b, c = people["a"], people["b"], people["c"]

    a_read = validate_success(api.get_consultant(a["id"], ADMIN))
    assert a_read["upline_path"] == []
    assert a_read["genealogy_depth"] == 0
    assert a_read["direct_downline_count"] == 1, "C is a descendant of A but not a direct child"

    c_read = validate_success(api.get_consultant(c["id"], ADMIN))
    assert c_read["upline_path"] == [a["id"], b["id"]], "upline_path runs root-first"
    assert c_read["genealogy_depth"] == 2
    a_children, _ = validate_paginated(
        api.list_consultants(ADMIN, params={"sponsor_consultant_id": a["id"]})
    )
    assert len(a_children) == 1
    assert a_children[0]["id"] == b["id"]

    b_children, _ = validate_paginated(
        api.list_consultants(ADMIN, params={"sponsor_consultant_id": b["id"]})
    )
    assert len(b_children) == 1
    assert b_children[0]["id"] == c["id"]

    assert_consultant(a_read)
    assert_consultant(c_read)


def test_plan_patch_updates_only_declared_mutable_fields(api):
    """An administrator may revise `compression_mode`, `payline_min_pv_points`, `min_payout_cents`,
    `seventy_rule_bp`, `restock_free_limit_cents`, `restock_fee_bp`, `probation_keep_bp`,
    `withhold_tier_threshold_cents`, `pv_bonus_cap_cents`, `sanction_cooloff_days`,
    `appeal_window_days` and `reinstatement_window_days`; a patch body containing none of those
    fields is refused with `ERR_NO_MUTABLE_FIELDS` rather than silently accepted, and a successful
    patch increments the plan's `version`.

    Design: Corner/endpoints/plan_patch_updates_only_declared_mutable_fields
    """
    plan = fx.create_plan(api)

    validate_error(
        api.update_compensation_plan(plan["id"], {}, ADMIN), "ERR_NO_MUTABLE_FIELDS", 422
    )
    unchanged = validate_success(api.get_compensation_plan(plan["id"], ADMIN))
    assert unchanged["version"] == 1, "a refused patch does not bump the version"

    updated = validate_success(
        api.update_compensation_plan(
            plan["id"],
            {
                "compression_mode": "STATIC",
                "min_payout_cents": 1,
                "seventy_rule_bp": 8000,
                "appeal_window_days": 30,
            },
            ADMIN,
        )
    )
    assert updated["compression_mode"] == "STATIC"
    assert updated["min_payout_cents"] == 1
    assert updated["seventy_rule_bp"] == 8000
    assert updated["appeal_window_days"] == 30
    assert updated["version"] == 2, "one version bump covers the whole multi-field patch"
    assert updated["point_value_cents"] == 100, "point_value_cents is not in the mutable subset"

    rows, _ = validate_paginated(
        api.list_compensation_plans(ADMIN, params={"compression_mode": "STATIC"})
    )
    assert len(rows) == 1
    assert rows[0]["plan_code"] == "PLAN-A"
    assert rows[0]["compression_mode"] == "STATIC"


def test_logical_clock_is_readable_by_every_role_and_stamps_new_rows(api):
    """The clock is readable by all seven roles and its value is exposed as `current_utc`. Before it
    is ever set, the clock reads `2026-08-01T00:00:00Z`. A `PlatformAdmin` may move it by supplying
    a new `current_utc`, which makes long windows reachable in testing without waiting.

    Design: Corner/endpoints/logical_clock_is_readable_by_every_role_and_stamps_new_rows
    """
    env = fx.setup_environment(api, products=(k.PRODUCT_KIT,), periods=())

    before = validate_success(api.get_clock(CONSULTANT))
    assert_instant(before["current_utc"], "2026-08-01T00:00:00Z", "current_utc")

    validate_success(api.set_clock({"current_utc": "2026-12-25T06:30:00Z"}, ADMIN))

    after = validate_success(api.get_clock(LEGAL))
    assert_instant(after["current_utc"], "2026-12-25T06:30:00Z", "current_utc")

    application = validate_success(
        api.create_enrollment_application(
            f.enrollment_application_payload(
                env["plan"]["id"],
                env["products"]["KIT-STD"]["id"],
                applicant_email="xmas@ex.test",
                applicant_full_name="Noel Late",
            ),
            ADMIN,
        ),
        201,
    )
    accepted = validate_success(
        api.accept_agreement(
            application["id"],
            f.accept_agreement_payload(),
            make_applicant_headers("xmas@ex.test"),
        )
    )
    assert_instant(
        accepted["agreement_accepted_at"],
        "2026-12-25T06:30:00Z",
        "agreement_accepted_at takes the logical clock's value, never wall time",
    )


def test_every_uniqueness_constraint_rejects_its_own_duplicate(api):
    """Fourth, no other application with the same `applicant_email` may currently be in `DRAFT`,
    `READY_FOR_APPROVAL` or `APPROVED`; a collision is `ERR_DUPLICATE_APPLICATION_EMAIL`. Three
    rules guard creation, in this order: `period_code` must be unique within the plan, or
    `ERR_DUPLICATE_PERIOD_CODE`; `period_end` must be strictly after `period_start`, since empty and
    inverted periods are meaningless, or `ERR_PERIOD_BOUNDS_INVALID`; and the new interval must not
    intersect any existing period of the same plan, or `ERR_PERIOD_OVERLAP`.

    Design: Corner/errors/every_uniqueness_constraint_rejects_its_own_duplicate
    """
    env = fx.setup_environment(api, products=(k.PRODUCT_KIT,))
    plan_id = env["plan"]["id"]
    kit_id = env["products"]["KIT-STD"]["id"]
    application = fx.create_application(api, env, "dup@ex.test", full_name="Dee First")

    validate_error(
        api.create_compensation_plan({"plan_code": "PLAN-A", "name": "Rival Plan A"}, ADMIN),
        "ERR_DUPLICATE_PLAN_CODE",
        409,
    )
    validate_error(
        api.create_product(
            {
                "sku": "KIT-STD",
                "name": "Rival Kit",
                "wholesale_price_cents": 1,
                "srp_cents": 2,
                "is_starter_kit": True,
            },
            ADMIN,
        ),
        "ERR_DUPLICATE_SKU",
        409,
    )
    validate_error(
        api.create_tax_jurisdiction(
            {"state_code": "TX", "tax_rate_bp": 1, "facilitator_agreement_active": False}, ADMIN
        ),
        "ERR_DUPLICATE_JURISDICTION",
        409,
    )
    validate_error(
        api.create_qualification_period(
            f.qualification_period_payload(
                plan_id,
                period_code="2026-08",
                period_start="2026-11-01T00:00:00Z",
                period_end="2026-12-01T00:00:00Z",
            ),
            ANALYST,
        ),
        "ERR_DUPLICATE_PERIOD_CODE",
        409,
    )
    validate_error(
        api.create_enrollment_application(
            f.enrollment_application_payload(
                plan_id, kit_id, applicant_email="dup@ex.test", applicant_full_name="Dee Twin"
            ),
            ADMIN,
        ),
        "ERR_DUPLICATE_APPLICATION_EMAIL",
        409,
    )

    withdrawn = validate_success(
        api.withdraw_enrollment_application(
            application["id"], f.withdraw_payload("Changed her mind"), ADMIN
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"

    retry = validate_success(
        api.create_enrollment_application(
            f.enrollment_application_payload(
                plan_id, kit_id, applicant_email="dup@ex.test", applicant_full_name="Dee Return"
            ),
            ADMIN,
        ),
        201,
    )
    assert retry["applicant_email"] == "dup@ex.test"
    assert retry["status"] == "DRAFT", "a withdrawn application frees the address"
