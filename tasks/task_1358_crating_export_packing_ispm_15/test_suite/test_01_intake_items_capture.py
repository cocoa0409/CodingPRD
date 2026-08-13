"""Customer intake, item capture, and item-level design guards (PRD §2.1, §2.4, §2.8, §3.1, §3.2)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, is_valid_uuid, NON_EXISTENT_UUID,
    create_customer_payload, create_packing_job_payload, create_item_payload,
    create_design_payload,
    create_customer, create_job, add_item, create_wood_batch,
    setup_quoted_job_with_item, setup_job_with_approved_design,
    setup_packing_job_with_crate,
    assert_customer, assert_item, assert_crate_design,
)
from test_helpers import TEST_USERS

SR = TEST_USERS["sales_rep_headers"]
CD = TEST_USERS["crating_designer_headers"]


def test_create_customer_returns_system_defaults(api, sales_rep_headers):
    """PRD §3.1: "A new customer starts `ACTIVE` with an `open_exposure_cents` of zero."
    PRD §2.4: "`id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix."

    Design: Corner/entities/create_customer_defaults
    """
    res = api.create_customer(
        create_customer_payload(name="Default Co", site_code="DEF-01", credit_limit_cents=500000),
        sales_rep_headers,
    )
    customer = validate_success(res, 201)
    assert_customer(customer)
    assert customer["status"] == "ACTIVE"
    assert customer["open_exposure_cents"] == 0
    assert customer["version"] == 1
    assert is_valid_uuid(customer["id"])


def test_item_create_missing_weight_rejected(api, sales_rep_headers):
    """PRD §3.1: "Each item takes a free-text `description`; strictly positive `length_cm`, `width_cm`, and `height_cm`; a strictly positive actual `weight_kg`".
    PRD §2.8: "required fields present, types valid, enum members recognized, and ranges respected ... otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/item_missing_required_weight_returns_400
    """
    customer = create_customer(name="Req Co", site_code="REQ-01", credit_limit_cents=500000)
    job = create_job(customer)
    payload = {
        "description": "No weight",
        "length_cm": 50, "width_cm": 50, "height_cm": 50,
        "fragile_class": "STANDARD", "declared_value_cents": 1000,
    }
    res = api.create_item(job["id"], payload, sales_rep_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)
    data, meta = validate_paginated(api.list_items(sales_rep_headers,
                                                   params={"packing_job_id": job["id"]}))
    assert len(data) == 0, "no Item may be persisted when the create is rejected"


def test_item_create_invalid_battery_enum_rejected(api, sales_rep_headers):
    """PRD §3.1: "Two optional flags complete the capture: `hazmat` (default false) marks dangerous goods, and `battery_in_equipment` (default `NONE`, otherwise `LITHIUM_ION`, `LITHIUM_METAL`, or `WET_CELL`) marks a battery shipped inside equipment."
    PRD §2.8: "required fields present, types valid, enum members recognized, and ranges respected ... otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/item_battery_invalid_enum_returns_400
    """
    customer = create_customer(name="Enum Co", site_code="ENM-01", credit_limit_cents=500000)
    job = create_job(customer)
    payload = create_item_payload(weight_kg=10, battery_in_equipment="AA",
                                  declared_value_cents=1000)
    res = api.create_item(job["id"], payload, sales_rep_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_item_computed_weight_fields_ignore_client_input(api, sales_rep_headers):
    """PRD §3.1: "Any values a client sends for server-computed fields such as `dimensional_weight_kg` or `chargeable_weight_kg` are ignored."
    PRD §3.1: "then `dimensional_weight_kg`, the same product divided by five thousand and rounded half-up to two decimals, and finally `chargeable_weight_kg`, the greater of the actual weight and the dimensional weight."

    Design: Corner/entities/item_chargeable_weight_input_ignored
    """
    customer = create_customer(name="Computed Co", site_code="CMP-01", credit_limit_cents=500000)
    job = create_job(customer)
    payload = create_item_payload(
        description="Dense block", weight_kg=40, declared_value_cents=1000,
        chargeable_weight_kg=999, dimensional_weight_kg=999,
    )
    item = validate_success(api.create_item(job["id"], payload, sales_rep_headers), 201)
    assert_item(item)
    assert item["dimensional_weight_kg"] == pytest.approx(25.0, abs=0.001), \
        "125000 cm3 / 5000 = 25.0 regardless of the client-sent 999"
    assert item["chargeable_weight_kg"] == pytest.approx(40.0, abs=0.001), \
        "max(actual 40, dimensional 25.0) = 40.0 regardless of the client-sent 999"


def test_get_item_with_unknown_id_returns_not_found(api, sales_rep_headers):
    """PRD §2.8: "Path identifiers — the variables `id`, `itemId`, and `containerId`, rendered in §4 paths inside braces — are resolved left to right ... and the request is rejected with `ERR_NOT_FOUND` at the first identifier that does not resolve."

    Design: Corner/entities/get_item_not_found_returns_404
    """
    res = api.get_item("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", sales_rep_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_design_computed_geometry_for_delicate_item(api, crating_designer_headers):
    """PRD §3.2: "`clearance_cm` is 5 centimeters for `STANDARD`, 10 for `DELICATE`, and 15 for `HIGHLY_FRAGILE`."
    PRD §3.2: "`thickness_cm` is 1.2 centimeters below 50 kilograms, 1.8 centimeters from 50 up to but not including 500 kilograms, and 2.5 centimeters at 500 kilograms or more."
    PRD §3.2: "`moisture_barrier_required` is `VACUUM_SEALED` whenever the item's `battery_in_equipment` is anything other than `NONE`, otherwise `VCI` whenever the item's `fragile_class` is anything other than `STANDARD`, otherwise `NONE`."

    Design: Corner/entities/design_computed_geometry_fields
    """
    _, _, item = setup_quoted_job_with_item(item_overrides={
        "description": "Optics bench", "length_cm": 60, "width_cm": 40, "height_cm": 40,
        "weight_kg": 45, "fragile_class": "DELICATE", "declared_value_cents": 150000,
    })
    design = validate_success(api.create_design(
        item["id"], create_design_payload(item["version"]), crating_designer_headers), 201)
    assert_crate_design(design)
    assert design["clearance_cm"] == 10
    assert design["thickness_cm"] == 1.2, "45 kg is below the 50 kg tier"
    assert design["internal_l_cm"] == 80 and design["internal_w_cm"] == 60
    assert design["internal_h_cm"] == 60
    assert design["external_l_cm"] == pytest.approx(82.4, abs=0.001)
    assert design["external_w_cm"] == pytest.approx(62.4, abs=0.001)
    assert design["external_h_cm"] == pytest.approx(62.4, abs=0.001)
    assert design["board_feet_required"] == 32, \
        "external 82.4x62.4x62.4 cm -> 2.835456 m2 -> 2.835456*11 = 31.190016 -> ceil 32"
    assert design["tare_weight_kg"] == pytest.approx(57.6, abs=0.001), "32 * 1.8"
    assert design["shock_indicator_g"] == 50
    assert design["moisture_barrier_required"] == "VCI"


def test_new_design_starts_draft_with_revision_one(api, crating_designer_headers):
    """PRD §3.2: "A new design starts in `DRAFT` with `wood_batch_id` and `reject_reason` null, and its creation bumps the item's `version`."
    PRD §3.2: "the new design's `revision` is the count of the item's prior designs plus one — so the first design bears `revision` 1."

    Design: Corner/state_machines/design_starts_draft
    """
    _, _, item = setup_quoted_job_with_item(item_overrides={
        "description": "Block", "weight_kg": 50, "declared_value_cents": 1000,
    })
    design = validate_success(api.create_design(
        item["id"], create_design_payload(item["version"]), crating_designer_headers), 201)
    assert_crate_design(design)
    assert design["status"] == "DRAFT"
    assert design["revision"] == 1
    assert design["wood_batch_id"] is None


def test_seal_built_crate_rejected_by_transition_guard(api, compliance_officer_headers,
                                                       shop_foreman_headers):
    """PRD §3.4: "From here a crate walks `PLANNED` → `BUILT` → `PACKED` → `SEALED` → `LOADED` → `SHIPPED` → `DELIVERED`, with a `REOPENED` detour and a `VOIDED` terminus described below; transition attempts from the wrong source state are rejected with `ERR_CRATE_INVALID_STATE`."

    Design: Corner/state_machines/seal_built_crate_rejected
    """
    ctx = setup_packing_job_with_crate(batch_overrides={"received_board_feet": 500,
                                                        "stamps_acquired": 2})
    get_success_data(api_client.build_crate(ctx["crate"]["id"], shop_foreman_headers))
    res = api.seal_crate(ctx["crate"]["id"], compliance_officer_headers)
    validate_error(res, "ERR_CRATE_INVALID_STATE", expected_status=409)
    crate = validate_success(api.get_crate(ctx["crate"]["id"], shop_foreman_headers), 200)
    assert crate["status"] == "BUILT"
    assert crate["stamp_serial"] is None, "no stamp may be minted by a rejected seal"


def test_cancel_job_in_packing_state_rejected(api, sales_rep_headers, shop_foreman_headers):
    """PRD §3.9: "Cancellation is the early exit, available to a `SalesRep` only while the job is `QUOTED` or `DESIGN` (otherwise `ERR_JOB_INVALID_STATE`), and it unwinds everything the job touched."

    Design: Corner/state_machines/cancel_packing_job_rejected
    """
    ctx = setup_packing_job_with_crate(batch_overrides={"received_board_feet": 500,
                                                        "stamps_acquired": 2})
    res = api.cancel_job(ctx["job"]["id"], sales_rep_headers)
    validate_error(res, "ERR_JOB_INVALID_STATE", expected_status=409)
    batch = validate_success(api.get_wood_batch(ctx["batch"]["id"], sales_rep_headers), 200)
    assert batch["reserved_board_feet"] == 27, \
        "the cancel cascade must not fire for a PACKING job, so the reservation is intact"


def test_item_status_bubbles_up_from_design_and_crate_events(api, shop_foreman_headers,
                                                             compliance_officer_headers):
    """PRD §3.2: "the item bubbles from `CAPTURED` to `DESIGN_APPROVED`."
    PRD §3.4: "Packing from `BUILT` bubbles the item to `PACKED`; packing from `REOPENED` leaves the item where the reopen put it."
    PRD §3.4: "A successful seal mints the crate's `stamp_serial` — the literal prefix `ISPM15-`, then the batch's `ht_certificate_no`, then a hyphen, then a four-digit zero-padded sequence equal to the batch's `stamps_applied` plus `stamps_voided` plus one — sets `stamp_status` to `ACTIVE`, increments the batch's `stamps_applied` by one, bubbles the item to `SEALED`, and triggers the job's readiness auto-check described below."

    Design: Corner/state_machines/item_status_bubbles_from_crate
    """
    ctx = setup_packing_job_with_crate(batch_overrides={"received_board_feet": 500,
                                                        "stamps_acquired": 2})
    item = validate_success(api.get_item(ctx["item"]["id"], shop_foreman_headers), 200)
    assert item["status"] == "DESIGN_APPROVED", "set by the design approval"
    get_success_data(api_client.build_crate(ctx["crate"]["id"], shop_foreman_headers))
    get_success_data(api_client.pack_crate(ctx["crate"]["id"],
                                           {"indicator_g": 75, "moisture_barrier": "NONE"},
                                           shop_foreman_headers))
    item = validate_success(api.get_item(ctx["item"]["id"], shop_foreman_headers), 200)
    assert item["status"] == "PACKED"
    get_success_data(api_client.seal_crate(ctx["crate"]["id"], compliance_officer_headers))
    item = validate_success(api.get_item(ctx["item"]["id"], shop_foreman_headers), 200)
    assert item["status"] == "SEALED"


def test_item_patch_blocked_once_live_design_exists(api, sales_rep_headers,
                                                    crating_designer_headers):
    """PRD §3.1: "only while the item has no design in any status other than `SUPERSEDED`; once a live design exists the attempt is rejected with `ERR_ITEM_NOT_CAPTURABLE`."

    Design: Corner/validations/item_patch_locked_by_design_rejected
    """
    _, _, item = setup_quoted_job_with_item(item_overrides={
        "description": "Block", "weight_kg": 50, "declared_value_cents": 1000,
    })
    get_success_data(api_client.create_design(
        item["id"], create_design_payload(item["version"]), crating_designer_headers))
    res = api.patch_item(item["id"], {"weight_kg": 55}, sales_rep_headers)
    validate_error(res, "ERR_ITEM_NOT_CAPTURABLE", expected_status=409)
    item_after = validate_success(api.get_item(item["id"], sales_rep_headers), 200)
    assert item_after["weight_kg"] == 50, "the rejected PATCH must not mutate the item"


def test_design_create_blocked_once_crate_exists(api, crating_designer_headers):
    """PRD §3.2: "Creation is refused outright, with `ERR_ITEM_HAS_CRATE`, when the item already has a crate that is not `VOIDED`."

    Design: Corner/validations/design_create_after_crate_rejected
    """
    ctx = setup_packing_job_with_crate(batch_overrides={"received_board_feet": 500,
                                                        "stamps_acquired": 2})
    fresh_item = validate_success(api.get_item(ctx["item"]["id"], crating_designer_headers), 200)
    res = api.create_design(
        ctx["item"]["id"], create_design_payload(fresh_item["version"]),
        crating_designer_headers)
    validate_error(res, "ERR_ITEM_HAS_CRATE", expected_status=409)
    data, meta = validate_paginated(api.list_designs(crating_designer_headers,
                                                     params={"item_id": ctx["item"]["id"]}))
    assert meta["total_count"] == 1, "no new design may be persisted"


def test_second_customer_with_same_site_code_rejected(api, sales_rep_headers):
    """PRD §2.9: "A customer's `site_code` is unique across all customers, because it doubles as the resource key for on-site permit overlap checks."

    Design: Corner/validations/duplicate_site_code_rejected
    """
    create_customer(name="First Co", site_code="DUP-01", credit_limit_cents=500000)
    res = api.create_customer(
        create_customer_payload(name="Second Co", site_code="DUP-01",
                                credit_limit_cents=500000),
        sales_rep_headers,
    )
    validate_error(res, "ERR_DUPLICATE", expected_status=409)


def test_expired_batch_blocks_design_approval(api, compliance_officer_headers,
                                              crating_designer_headers):
    """PRD §3.2: "the referenced batch must be `ACTIVE` and not past its `expires_at` against the logical clock (otherwise `ERR_BATCH_NOT_ACTIVE`)".
    PRD §2.5: "At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time."

    Design: Corner/validations/batch_expired_blocks_approve
    """
    _, _, item = setup_quoted_job_with_item(customer_overrides={"site_code": "EXP-01"})
    batch = create_wood_batch(ht_certificate_no="HT-OLD-01",
                              expires_at="2026-06-01T00:00:00Z",
                              received_board_feet=500, stamps_acquired=2)
    design = get_success_data(api_client.create_design(
        item["id"], create_design_payload(item["version"]), crating_designer_headers))
    get_success_data(api_client.submit_design(design["id"], crating_designer_headers))
    res = api.approve_design(design["id"], {"wood_batch_id": batch["id"]},
                             compliance_officer_headers)
    validate_error(res, "ERR_BATCH_NOT_ACTIVE", expected_status=409)
    batch_after = validate_success(api.get_wood_batch(batch["id"], compliance_officer_headers), 200)
    assert batch_after["reserved_board_feet"] == 0, "no wood may be reserved by a rejected approval"
