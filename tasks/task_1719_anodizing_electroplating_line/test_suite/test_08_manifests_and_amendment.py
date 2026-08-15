"""Waste manifest lifecycle, mass invariant, segregation of duties, OCC on amend."""
from test_helpers import (
    ApiErrorId,
    EHS,
    MGR,
    add_line_item,
    create_customer,
    create_manifest,
    get_manifest,
    get_success_data,
    make_customer_headers,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_work_order_payload
from test_helpers.test_users import (
    make_ehs_officer_headers,
    make_shop_manager_headers,
)


def test_manifest_mass_invariant_across_add_remove():
    """PRD §3.9: "The line's `mass_kg` is its volume multiplied by the density of its
    source type — 1.2 kilograms per liter for `BATH_DUMP` and `RINSE_CONCENTRATE`, 1.5
    for `SLUDGE_PRESS` — rounded half-up to three decimal places."
    PRD §3.9: "Each addition or removal recomputes `total_mass_kg` as the sum of the
    lines' masses at three decimals and increments the manifest's `version`"

    Design: Difficulty/compensating_invariant/manifest_mass_invariant
    """
    manifest = create_manifest(creator_user_id="ehs-1", generator_epa_id="EPA-GEN-19")
    headers = make_ehs_officer_headers("ehs-1")
    l1 = add_line_item(manifest["id"], manifest["version"], headers=headers,
                       waste_code="F006", source_type="SLUDGE_PRESS",
                       description="Press cake", volume_liters=100)
    # 100 L x 1.5 kg/L = 150.0
    assert l1["mass_kg"] == 150.0
    assert get_manifest(manifest["id"])["total_mass_kg"] == 150.0
    v1 = get_manifest(manifest["id"])["version"]
    l2 = add_line_item(manifest["id"], v1, headers=headers,
                       waste_code="D007", source_type="RINSE_CONCENTRATE",
                       description="Rinse concentrate", volume_liters=50)
    # 50 L x 1.2 kg/L = 60.0
    assert l2["mass_kg"] == 60.0
    assert get_manifest(manifest["id"])["total_mass_kg"] == 210.0


def test_manifest_mass_invariant_after_compensating_remove():
    """PRD §3.9: "Each addition or removal recomputes `total_mass_kg` as the sum of the
    lines' masses at three decimals and increments the manifest's `version`; line
    operations on a non-draft manifest are rejected with `ERR_MANIFEST_NOT_DRAFT`, and
    removals return 204 with no body."

    Design: Difficulty/compensating_invariant/manifest_mass_invariant
    """
    manifest = create_manifest(creator_user_id="ehs-1", generator_epa_id="EPA-GEN-19B")
    headers = make_ehs_officer_headers("ehs-1")
    l1 = add_line_item(manifest["id"], manifest["version"], headers=headers,
                       waste_code="F006", source_type="SLUDGE_PRESS",
                       description="Press cake", volume_liters=100)
    v1 = get_manifest(manifest["id"])["version"]
    l2 = add_line_item(manifest["id"], v1, headers=headers,
                       waste_code="D007", source_type="RINSE_CONCENTRATE",
                       description="Rinse concentrate", volume_liters=50)
    assert get_manifest(manifest["id"])["total_mass_kg"] == 210.0
    # Compensating action: delete the first line; total returns to exactly l2's mass.
    resp = api_client.delete_manifest_line_item(manifest["id"], l1["id"], headers)
    assert resp.status_code == 204
    final = get_manifest(manifest["id"])
    assert final["total_mass_kg"] == 60.0
    assert final["total_mass_kg"] == l2["mass_kg"]


def test_manifest_lifecycle_terminal_lockdown():
    """PRD §3.9: "Shipping a manifest requires it to be `FINALIZED` (else
    `ERR_MANIFEST_NOT_FINALIZED`) and requires the `transporter_name` to be provided
    (else `ERR_INVALID_REQUEST`); the manifest moves to `SHIPPED`. Confirming receipt
    requires `SHIPPED` (else `ERR_MANIFEST_NOT_SHIPPED`) and lands the manifest in the
    terminal `RECEIVED` state."

    Design: Corner/state_machines/manifest_lifecycle_terminal_lockdown
    """
    manifest = create_manifest(creator_user_id="ehs-a", generator_epa_id="EPA-GEN-T")
    headers_a = make_ehs_officer_headers("ehs-a")
    add_line_item(manifest["id"], manifest["version"], headers=headers_a,
                  waste_code="F007", source_type="RINSE_CONCENTRATE",
                  description="Cyanide rinse", volume_liters=50)
    # Ship from DRAFT is rejected.
    resp_draft = api_client.ship_manifest(manifest["id"], {"transporter_name": "HazTrans Inc"}, EHS)
    validate_error(resp_draft, ApiErrorId.ERR_MANIFEST_NOT_FINALIZED)
    # Finalize by a different user succeeds.
    finalized = get_success_data(
        api_client.finalize_manifest(manifest["id"], make_ehs_officer_headers("ehs-b"))
    )
    assert finalized["status"] == "FINALIZED"
    # Ship without transporter_name is rejected.
    resp_notrans = api_client.ship_manifest(manifest["id"], {}, EHS)
    validate_error(resp_notrans, ApiErrorId.ERR_INVALID_REQUEST)
    # Ship with transporter, then receive; a second receive is rejected.
    shipped = get_success_data(
        api_client.ship_manifest(manifest["id"], {"transporter_name": "HazTrans Inc"}, EHS)
    )
    assert shipped["status"] == "SHIPPED"
    received = get_success_data(api_client.receive_manifest(manifest["id"], EHS))
    assert received["status"] == "RECEIVED"
    resp_recv2 = api_client.receive_manifest(manifest["id"], EHS)
    validate_error(resp_recv2, ApiErrorId.ERR_MANIFEST_NOT_SHIPPED)
    assert get_manifest(manifest["id"])["status"] == "RECEIVED"


def test_manifest_finalize_segregation_and_empty():
    """PRD §3.9: "Above all, the finalizer's `X-User-ID` must differ from the
    manifest's `created_by_user_id` — a rule that binds every role including
    `ShopManager`, rejected as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and per the
    pinned ordering of §2.8 the segregation check fires at tier 10, before the
    exceedance hold at tier 12."
    PRD §3.9: "Finalizing — an `EHSOfficer` or `ShopManager` action — requires the
    manifest to be `DRAFT` (else `ERR_MANIFEST_NOT_DRAFT`), at least one line item
    (else `ERR_MANIFEST_EMPTY`)"

    Design: Corner/validations/manifest_finalize_segregation_and_empty
    """
    mf = create_manifest(creator_user_id="ehs-x", generator_epa_id="EPA-GEN-F")
    mg = get_success_data(api_client.create_waste_manifest(
        {"generator_epa_id": "EPA-GEN-G"}, make_shop_manager_headers("mgr-1")
    ))
    # Creator finalizing -> 403 segregation, even for a ShopManager creator.
    resp_sod = api_client.finalize_manifest(mf["id"], make_ehs_officer_headers("ehs-x"))
    validate_error(resp_sod, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    resp_sod_mgr = api_client.finalize_manifest(mg["id"], make_shop_manager_headers("mgr-1"))
    validate_error(resp_sod_mgr, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    # Different user on an empty manifest -> 422 ERR_MANIFEST_EMPTY.
    resp_empty = api_client.finalize_manifest(mf["id"], make_ehs_officer_headers("ehs-y"))
    validate_error(resp_empty, ApiErrorId.ERR_MANIFEST_EMPTY)
    # Add a line, then a different user finalizes.
    add_line_item(mf["id"], mf["version"], headers=make_ehs_officer_headers("ehs-x"),
                  waste_code="F006", source_type="SLUDGE_PRESS", description="Cake",
                  volume_liters=100)
    finalized = get_success_data(
        api_client.finalize_manifest(mf["id"], make_ehs_officer_headers("ehs-y"))
    )
    assert finalized["status"] == "FINALIZED"
    assert finalized["total_mass_kg"] == 150.0


def test_manifest_line_stale_version_rejected():
    """PRD §2.7: "Adding a line item to a manifest
    (`POST /waste-manifests/{id}/line-items`) requires `expected_manifest_version`
    matching the WasteManifest's current `version`, because the client may have
    computed totals against a line-item set it last observed."

    Design: Corner/validations/manifest_line_stale_version_rejected
    """
    manifest = create_manifest(creator_user_id="ehs-sv", generator_epa_id="EPA-GEN-SV")
    headers = make_ehs_officer_headers("ehs-sv")
    l1 = add_line_item(manifest["id"], manifest["version"], headers=headers,
                       waste_code="F006", source_type="SLUDGE_PRESS",
                       description="Cake A", volume_liters=10)
    assert l1["id"]
    # Second add with the creation-time (now stale) version -> 412.
    resp = api_client.add_manifest_line_item(
        manifest["id"],
        {"waste_code": "F006", "source_type": "SLUDGE_PRESS", "description": "Cake B",
         "volume_liters": 10, "expected_manifest_version": manifest["version"]},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_workorder_amend_stale_version_rejected():
    """PRD §2.7: "Amending a received work order (`PATCH /work-orders/{id}`) requires
    `expected_work_order_version` matching the WorkOrder's current `version`; every
    successful amendment recomputes the provisional quote, so an amendment based on a
    stale quote view is rejected."

    Design: Corner/validations/workorder_amend_occ_and_quote_recompute
    """
    customer = create_customer(company_name="Amend Co")
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id=customer["id"], part_number="PN-V"),
        make_customer_headers(customer["id"]),
    ))
    headers = make_customer_headers(customer["id"])
    # Stale amend: version - 1.
    resp = api_client.patch_work_order(
        wo["id"],
        {"expected_work_order_version": wo["version"] - 1, "part_count": 12},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    # Order is unchanged.
    refreshed = get_success_data(api_client.get_work_order(wo["id"], headers))
    assert refreshed["part_count"] == 10
    assert refreshed["version"] == wo["version"]


def test_workorder_amend_recomputes_provisional_quote():
    """PRD §3.4: "Each successful amendment recomputes `provisional_quote_cents` and
    increments the order's `version`."
    PRD §3.4: "The system derives `surface_area_total_dm2` as the part count multiplied
    by the per-part area."

    Design: Corner/validations/workorder_amend_occ_and_quote_recompute
    """
    customer = create_customer(company_name="Amend Co 2")
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id=customer["id"], part_number="PN-V2"),
        make_customer_headers(customer["id"]),
    ))
    headers = make_customer_headers(customer["id"])
    amended = get_success_data(api_client.patch_work_order(
        wo["id"],
        {"expected_work_order_version": wo["version"], "part_count": 12},
        headers,
    ))
    assert amended["version"] == wo["version"] + 1
    # surface 30 dm2; barrel 1200 + processing round(30 x 15.0 x 15) = 6750 -> 7950
    assert amended["provisional_quote_cents"] == 7950, (
        f"Quote after amend: expected 7950, got {amended['provisional_quote_cents']}"
    )
