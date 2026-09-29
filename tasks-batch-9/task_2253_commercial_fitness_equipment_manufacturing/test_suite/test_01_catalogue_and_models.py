"""Catalogue registration, revision creation and the supersession graph."""
from test_helpers import (
    expected_listing_order,
    assert_common_properties,
    assert_equipment_model,
    assert_model_revision,
    assert_success_envelope,
    equipment_model_payload,
    firmware_release_payload,
    list_all,
    make_service_partner_tech_headers,
    model_revision_payload,
    new_equipment_model,
    new_firmware_release,
    new_service_partner,
    read_equipment_model,
    read_facility,
    read_firmware_release,
    read_install_job,
    read_maintenance_visit,
    read_service_partner,
    service_partner_payload,
    setup_active_pm_program,
    setup_installed_order,
    setup_released_revision,
    rig_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _chain_model(api, headers, name, supersedes=None):
    """Register one link of a supersession chain."""
    payload = equipment_model_payload(
        "T900",
        name=name,
        duty_class="LIGHT_COMMERCIAL",
        unit_list_price_cents=300_000,
        shipping_weight_kg=100.0,
        allowed_finish_codes=["GRAPHITE"],
    )
    if supersedes is not None:
        payload["supersedes_model_id"] = supersedes
    return api.create_equipment_model(payload, headers)


def test_equipment_model_creation_derives_connected_and_lifecycle(
    api, product_engineer_headers
):
    """A CARDIO registration derives its own flags rather than echoing inputs.

    The PRD states that "From the category the server derives the boolean
    `connected`, which is true exactly when the `category` is `CONNECTED`" and
    that "A freshly registered model is `PRE_RELEASE`", with
    `released_revision_count` counting released revisions — zero at creation.

    Design: Corner/entities/equipment_model_creation_returns_computed_lifecycle_and_envelope
    """
    payload = equipment_model_payload("T900")

    response = api.create_equipment_model(payload, product_engineer_headers)

    data = validate_success(response, 201)
    assert_success_envelope(response.json(), "object")
    assert_equipment_model(data)
    assert data["name"] == "T900 Treadmill"
    assert data["category"] == "CARDIO"
    assert data["duty_class"] == "FULL_COMMERCIAL"
    assert data["unit_list_price_cents"] == 479_950
    assert float(data["shipping_weight_kg"]) == 212.5
    assert data["allowed_finish_codes"] == ["GRAPHITE", "ARCTIC_WHITE", "CLUB_RED"]
    assert data["connected"] is False
    assert data["console_platform"] is None
    assert data["lifecycle_status"] == "PRE_RELEASE"
    assert data["released_revision_count"] == 0
    assert_common_properties(data, expect_version=1)
    assert "_" not in data["id"], "the id is a bare UUID with no type prefix"

    fetched = validate_success(api.get_equipment_model(data["id"], product_engineer_headers))
    assert fetched["connected"] is False
    assert fetched["lifecycle_status"] == "PRE_RELEASE"


def test_model_revision_retrieval_returns_stored_and_derived_fields(
    api, product_engineer_headers
):
    """A DRAFT revision of a FULL_COMMERCIAL model reads back with its gate derived.

    The PRD states that "At creation the server derives `min_required_cycles`
    from the owning model's `duty_class`" and that it is "500,000 cycles for
    `FULL_COMMERCIAL`", while "A new revision begins at `status` `DRAFT` with
    `rework_count` at 0, `verified_cycle_count` and `projected_cycle_count` both
    at 0".

    Design: Corner/entities/model_revision_retrieval_returns_stored_and_derived_fields
    """
    model = new_equipment_model("T900", allowed_finish_codes=["GRAPHITE"],
                                headers=product_engineer_headers)
    created = validate_success(
        api.create_model_revision(
            model_revision_payload(model["id"], model["version"],
                                   revision_code="T900-R1",
                                   target_cycle_count=600_000),
            product_engineer_headers,
        ),
        201,
    )

    response = api.get_model_revision(created["id"], product_engineer_headers)

    data = validate_success(response)
    assert_model_revision(data)
    assert data["revision_code"] == "T900-R1"
    assert data["target_cycle_count"] == 600_000
    assert data["equipment_model_id"] == model["id"]
    assert data["status"] == "DRAFT"
    assert data["min_required_cycles"] == 500_000
    assert data["verified_cycle_count"] == 0
    assert data["projected_cycle_count"] == 0
    assert data["rework_count"] == 0
    assert data["qualified_at"] is None
    assert data["released_at"] is None
    assert data["sunset_announced_at"] is None
    assert data["firmware_support_until"] is None
    assert data["version"] == 1


def test_equipment_model_listing_pages_in_creation_order(
    api, product_engineer_headers, order_planner_headers
):
    """Three models page out in the declared listing order and filter by category.

    The PRD states that "Every list endpoint returns rows ordered by
    `created_at` ascending, with the row `id` ascending as the tie-break when
    two rows share a creation timestamp."

    Design: Corner/entities/equipment_model_listing_orders_by_created_at_with_pagination
    """
    first = new_equipment_model("T900", allowed_finish_codes=["GRAPHITE"],
                                headers=product_engineer_headers)
    second = new_equipment_model("S500", allowed_finish_codes=["GRAPHITE"],
                                 headers=product_engineer_headers)
    third = new_equipment_model("C700", allowed_finish_codes=["GRAPHITE"],
                                headers=product_engineer_headers)

    page_one_rows, page_one_meta = validate_paginated(
        api.list_equipment_models(order_planner_headers, params={"limit": 2, "offset": 0})
    )
    page_two_rows, page_two_meta = validate_paginated(
        api.list_equipment_models(order_planner_headers, params={"limit": 2, "offset": 2})
    )
    cardio_rows, _ = validate_paginated(
        api.list_equipment_models(order_planner_headers, params={"category": "CARDIO"})
    )

    ordered = expected_listing_order([first, second, third])
    assert page_one_meta["total_count"] == 3
    assert page_one_meta["has_more"] is True
    assert [row["id"] for row in page_one_rows] == ordered[:2]
    assert len(page_two_rows) == 1
    assert page_two_rows[0]["id"] == ordered[2]
    assert page_two_meta["total_count"] == 3
    assert page_two_meta["has_more"] is False
    assert len(cardio_rows) == 1
    assert cardio_rows[0]["id"] == first["id"]
    seen = [row["id"] for row in page_one_rows] + [row["id"] for row in page_two_rows]
    assert len(seen) == len(set(seen)), "no page contains a duplicated id"


def test_declared_defaults_materialise_when_optional_inputs_are_omitted(
    api, product_engineer_headers, order_planner_headers, service_ops_admin_headers
):
    """Four optional inputs left out of their payloads land on their declared defaults.

    The PRD declares "an optional `install_blackout_weekdays` list, which
    defaults to empty", "an optional `mandatory_security` boolean that defaults
    to false", "`travel_buffer_minutes`, a system-set field fixed at 120
    minutes", and "an optional `reserved_units` count between 0 and 50
    (defaulting to 0) of spare units to hold from the partner's stock."

    Design: Corner/entities/declared_defaults_applied_when_optional_inputs_are_omitted
    """
    ctx = setup_installed_order(preset="T900")
    firmware = new_firmware_release(headers=product_engineer_headers)
    program = setup_active_pm_program(
        ctx["facility"]["id"], ctx["partner"]["id"], tier="PRO", visit_interval_days=90
    )

    response = api.create_maintenance_visit(
        {
            "pm_program_id": program["id"],
            "serialized_asset_id": ctx["asset"]["id"],
            "scheduled_date": "2026-09-18T09:00:00Z",
        },
        make_service_partner_tech_headers(ctx["partner"]["id"]),
    )

    visit = validate_success(response, 201)
    assert visit["reserved_units"] == 0
    assert visit["status"] == "SCHEDULED"
    assert visit["labor_hours"] is None
    assert visit["held_reason"] is None

    facility = read_facility(ctx["facility"]["id"], order_planner_headers)
    assert facility["install_blackout_weekdays"] == []

    build = read_firmware_release(firmware["id"], product_engineer_headers)
    assert build["mandatory_security"] is False
    assert build["status"] == "ACTIVE"

    job = read_install_job(ctx["install_job"]["id"], order_planner_headers)
    assert job["travel_buffer_minutes"] == 120

    partner = read_service_partner(ctx["partner"]["id"], service_ops_admin_headers)
    assert partner["spare_stock_received_units"] == 0
    assert partner["spare_stock_reserved_units"] == 0
    assert partner["spare_stock_on_hand_units"] == 0
    assert read_maintenance_visit(visit["id"], service_ops_admin_headers)["reserved_units"] == 0


def test_supersede_chain_accepts_five_edges_and_rejects_the_sixth(
    api, product_engineer_headers
):
    """The supersession chain stops one edge past the fifth.

    The PRD states that "The supersession graph must stay acyclic: a model may
    not supersede itself, may not close a cycle through any chain of
    predecessors, and the resulting chain may be at most five edges long.
    Violating any of the three conditions yields `ERR_SUPERSEDE_CYCLE`."

    Design: Corner/entities/supersede_chain_depth_cap_rejects_the_sixth_edge
    """
    ids = []
    previous = None
    for name in ["Chain Model A", "Chain Model B", "Chain Model C", "Chain Model D",
                 "Chain Model E", "Chain Model F"]:
        created = validate_success(
            _chain_model(api, product_engineer_headers, name, previous), 201
        )
        ids.append(created["id"])
        previous = created["id"]
    assert read_equipment_model(ids[5], product_engineer_headers)[
        "supersedes_model_id"
    ] == ids[4], "the fifth edge is the last permitted one"

    response = _chain_model(api, product_engineer_headers, "Chain Model G", ids[5])

    validate_error(response, "ERR_SUPERSEDE_CYCLE", 422)
    successors, successor_meta = validate_paginated(
        api.list_equipment_models(product_engineer_headers,
                                  params={"supersedes_model_id": ids[5]})
    )
    assert successor_meta["total_count"] == 0
    assert successors == []
    _, all_meta = validate_paginated(api.list_equipment_models(product_engineer_headers))
    assert all_meta["total_count"] == 6
    for model_id in ids:
        assert read_equipment_model(model_id, product_engineer_headers)[
            "lifecycle_status"
        ] == "PRE_RELEASE"


def test_uniqueness_is_global_for_names_and_scoped_for_revision_codes(
    api, product_engineer_headers, service_ops_admin_headers
):
    """One collision code covers five scopes, only one of which is per-model.

    The PRD states that "A revision's `revision_code` is unique among its own
    model's revisions whose `status` is anything other than `SUPERSEDED`; an
    equipment model `name`, a test rig `name`, a service partner `name` and a
    firmware release `version_string` are each globally unique. Any collision is
    `ERR_DUPLICATE_REVISION_CODE` (409)."

    Design: Corner/validations/global_and_scoped_uniqueness_are_enforced_per_declared_scope
    """
    released = setup_released_revision("T900")
    new_service_partner(headers=service_ops_admin_headers)
    new_firmware_release(headers=product_engineer_headers)
    other_model = new_equipment_model("T950", headers=product_engineer_headers)
    current = read_equipment_model(released["model"]["id"], product_engineer_headers)

    validate_error(
        api.create_equipment_model(equipment_model_payload("T900"),
                                   product_engineer_headers),
        "ERR_DUPLICATE_REVISION_CODE", 409,
    )
    validate_error(
        api.create_test_rig(
            rig_payload(name="RIG-A", parallel_station_count=4,
                             supported_duty_classes=["LIGHT_COMMERCIAL"]),
            product_engineer_headers,
        ),
        "ERR_DUPLICATE_REVISION_CODE", 409,
    )
    validate_error(
        api.create_service_partner(
            service_partner_payload(name="Meridian Service Co", region="R_SOUTH",
                                    certified_categories=["STRENGTH"],
                                    certified_technician_count=2,
                                    certified_hours_capacity=40.0),
            service_ops_admin_headers,
        ),
        "ERR_DUPLICATE_REVISION_CODE", 409,
    )
    validate_error(
        api.create_firmware_release(firmware_release_payload(), product_engineer_headers),
        "ERR_DUPLICATE_REVISION_CODE", 409,
    )
    validate_error(
        api.create_model_revision(
            model_revision_payload(current["id"], current["version"],
                                   revision_code="T900-R1",
                                   target_cycle_count=600_000),
            product_engineer_headers,
        ),
        "ERR_DUPLICATE_REVISION_CODE", 409,
    )

    reused = validate_success(
        api.create_model_revision(
            model_revision_payload(other_model["id"], other_model["version"],
                                   revision_code="T900-R1",
                                   target_cycle_count=600_000),
            product_engineer_headers,
        ),
        201,
    )
    assert reused["equipment_model_id"] == other_model["id"]
    _, model_meta = validate_paginated(
        api.list_equipment_models(product_engineer_headers)
    )
    assert model_meta["total_count"] == 2
    _, revision_meta = validate_paginated(
        api.list_model_revisions(product_engineer_headers,
                                 params={"equipment_model_id": current["id"]})
    )
    assert revision_meta["total_count"] == 1


def test_revision_create_rejects_a_stale_equipment_model_version(
    api, product_engineer_headers
):
    """The version captured at model creation goes stale as soon as one revision exists.

    The PRD states that the create "carries `expected_equipment_model_version`
    and the server compares it to the owning `EquipmentModel` row's current
    `version`. If the two differ — because some other writer has advanced the
    model since the client last read it — the create is rejected with
    `ERR_STALE_VERSION` (412) and no revision is persisted. On success the
    owning model's `version` is incremented by one."

    Design: Corner/complexity_layers/revision_create_rejects_a_stale_equipment_model_version
    """
    model = new_equipment_model("T900", allowed_finish_codes=["GRAPHITE"],
                                headers=product_engineer_headers)
    captured_version = model["version"]
    first_revision = validate_success(
        api.create_model_revision(
            model_revision_payload(model["id"], captured_version,
                                   revision_code="T900-R1",
                                   target_cycle_count=600_000),
            product_engineer_headers,
        ),
        201,
    )
    after_first = read_equipment_model(model["id"], product_engineer_headers)
    assert after_first["version"] == captured_version + 1

    response = api.create_model_revision(
        model_revision_payload(model["id"], captured_version,
                               revision_code="T900-R2",
                               target_cycle_count=650_000),
        product_engineer_headers,
    )

    validate_error(response, "ERR_STALE_VERSION", 412)
    _, meta = validate_paginated(
        api.list_model_revisions(product_engineer_headers,
                                 params={"equipment_model_id": model["id"]})
    )
    assert meta["total_count"] == 1, "nothing was written by the rejected create"

    fresh = read_equipment_model(model["id"], product_engineer_headers)
    second = validate_success(
        api.create_model_revision(
            model_revision_payload(model["id"], fresh["version"],
                                   revision_code="T900-R2",
                                   target_cycle_count=650_000),
            product_engineer_headers,
        ),
        201,
    )
    assert second["status"] == "DRAFT"
    assert second["min_required_cycles"] == 500_000
    assert read_equipment_model(model["id"], product_engineer_headers)["version"] == (
        captured_version + 2
    )
    rows = list_all(api.list_model_revisions, {"equipment_model_id": model["id"]},
                    product_engineer_headers)
    assert [row["id"] for row in rows] == expected_listing_order([first_revision, second])
    assert sorted(row["revision_code"] for row in rows) == ["T900-R1", "T900-R2"]
