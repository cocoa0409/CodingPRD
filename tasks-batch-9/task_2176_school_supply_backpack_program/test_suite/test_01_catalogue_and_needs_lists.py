"""The catalogue a programme curates and the grade-band needs lists drawn on it."""

from test_helpers import (
    ApiErrorId,
    MISSING_UUID,
    add_spec_line,
    assert_grade_kit_spec,
    assert_school,
    assert_supply_item,
    create_active_school,
    create_backpack,
    create_notebook,
    create_pencil,
    create_published_spec,
    create_spec,
    make_school_liaison_headers,
    move_spec,
    school_payload,
    supply_item_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PD = TEST_USERS["program_director_headers"]


def test_school_registration_lands_in_prospect_with_zeroed_aggregates(api):
    """PRD 3.1: "The school lands in `PROSPECT` with every computed aggregate at zero."
    PRD 2.4: "`version` is an integer that starts at 1 when the resource is created
    and is incremented by exactly 1 on every mutation of that resource, whether the
    mutation was requested directly or was produced as a downstream effect of some
    other operation."

    Design: Corner/entities/school_creation_returns_prospect_status_and_zeroed_aggregates
    """
    response = api.create_school(school_payload(), PD)
    school = validate_success(response, expected_status=201)
    assert_school(school)

    assert school["partnership_status"] == "PROSPECT"
    assert school["version"] == 1, f"new school must start at version 1, got {school['version']}"
    assert school["target_student_count"] == 0
    assert school["students_served_interim_count"] == 0
    assert school["students_served_audited_count"] == 0
    assert school["no_show_count"] == 0
    assert school["kits_delivered_count"] == 0
    assert float(school["impact_index_interim"]) == 0.00
    assert float(school["impact_index_audited"]) == 0.00

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "api_request_id must start with req_"
    )
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_supply_item_optional_flags_take_their_declared_defaults(api):
    """PRD 3.1: "Two booleans tune its handling: `hygiene_sealed_required`, which
    defaults to false and, when true, subjects donated stock of that item to the
    sealed-packaging safety rule of §3.3, and `catalog_active`, which defaults to true
    and, when false, bars the item from being referenced by any new needs-list line,
    donation batch, purchase order or teacher request with `ERR_ITEM_INACTIVE`."

    Design: Corner/entities/supply_item_defaults_applied_when_optional_fields_omitted
    """
    payload = supply_item_payload(
        sku="NBK-01",
        name="Composition notebook",
        category="PAPER",
        unit_cost_cents=180,
        bulk_pack_size=10,
    )
    item = validate_success(api.create_supply_item(payload, PD), expected_status=201)
    assert_supply_item(item)

    assert item["hygiene_sealed_required"] is False
    assert item["catalog_active"] is True


def test_duplicate_sku_is_rejected_and_leaves_the_first_item_untouched(api):
    """PRD 3.1: "A catalogue item carries an `sku` of 1 to 32 characters that must be
    unique across the whole catalogue — a repeat is rejected with `ERR_DUPLICATE_SKU`"

    Design: Corner/entities/supply_item_duplicate_sku_is_rejected
    """
    first = create_pencil()

    response = api.create_supply_item(
        supply_item_payload(sku="PEN-12", name="Pencils, cheaper", unit_cost_cents=199), PD
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_SKU.value, expected_status=409)

    reread = validate_success(api.get_supply_item(first["id"], PD))
    assert reread["unit_cost_cents"] == 250, "the original catalogue item must be untouched"


def test_supply_item_missing_required_field_is_a_malformed_request(api):
    """PRD 2.7: "3. Request shape: every required body field present, every enum value
    inside its declared set, every integer inside its declared range, every ISO 8601
    datetime parseable, `window_start` strictly earlier than `window_end`, and
    pagination `limit` between 1 and 100 with `offset` at least 0 — otherwise
    `ERR_INVALID_REQUEST`, 400."

    Design: Corner/entities/supply_item_missing_required_field_returns_invalid_request
    """
    payload = {
        "sku": "PEN-12",
        "name": "Pencils 12-pack",
        "category": "WRITING",
        "unit_cost_cents": 250,
    }
    response = api.create_supply_item(payload, PD)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_needs_list_kit_cost_and_line_count_track_every_line(api):
    """PRD 3.1: "`kit_unit_cost_cents` is the cost of one complete kit for the band:
    for each line of the list, multiply that line's `qty_per_student` by the
    `unit_cost_cents` of the catalogue item it references, and add those products
    together across every line of the list."
    PRD 3.1: "`line_count` is simply the number of lines attached to the list."

    Design: Corner/entities/grade_kit_spec_computed_kit_unit_cost_and_line_count
    """
    school = create_active_school()
    pencil = create_pencil()
    notebook = create_notebook()
    backpack = create_backpack()
    spec = create_spec(school["id"], grade_band="K_2", student_target_count=100)

    add_spec_line(school["id"], spec["id"], pencil["id"], qty_per_student=4)
    add_spec_line(school["id"], spec["id"], notebook["id"], qty_per_student=2)
    line = validate_success(
        api.create_kit_spec_line(
            {
                "grade_kit_spec_id": spec["id"],
                "supply_item_id": backpack["id"],
                "qty_per_student": 1,
            },
            make_school_liaison_headers(school["id"]),
        ),
        expected_status=201,
    )
    assert line["qty_per_student"] == 1

    reread = validate_success(
        api.get_grade_kit_spec(spec["id"], make_school_liaison_headers(school["id"]))
    )
    assert_grade_kit_spec(reread)
    assert reread["kit_unit_cost_cents"] == 2810, (
        "4*250 + 2*180 + 1*1450 = 2810 cents for one complete kit"
    )
    assert reread["line_count"] == 3
    assert reread["status"] == "DRAFT"


def test_needs_list_line_with_unknown_item_reference_is_not_found(api):
    """PRD 2.6: "The same code set is used for foreign keys carried in a request body;
    body references are resolved in the order the endpoint declares its input fields,
    and again the first failure decides."

    Design: Corner/entities/kit_spec_line_body_fk_supply_item_not_found
    """
    school = create_active_school()
    spec = create_spec(school["id"])

    response = api.create_kit_spec_line(
        {
            "grade_kit_spec_id": spec["id"],
            "supply_item_id": MISSING_UUID,
            "qty_per_student": 4,
        },
        make_school_liaison_headers(school["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SUPPLY_ITEM_NOT_FOUND.value, expected_status=404)

    reread = validate_success(
        api.get_grade_kit_spec(spec["id"], make_school_liaison_headers(school["id"]))
    )
    assert reread["line_count"] == 0


def test_inactive_catalogue_item_cannot_join_a_needs_list(api):
    """PRD 3.1: "Two booleans tune its handling: `hygiene_sealed_required`, which
    defaults to false and, when true, subjects donated stock of that item to the
    sealed-packaging safety rule of §3.3, and `catalog_active`, which defaults to true
    and, when false, bars the item from being referenced by any new needs-list line,
    donation batch, purchase order or teacher request with `ERR_ITEM_INACTIVE`."

    Design: Corner/validations/inactive_catalog_item_cannot_join_a_needs_list
    """
    school = create_active_school()
    ruler = validate_success(
        api.create_supply_item(
            supply_item_payload(
                sku="RUL-01",
                name="Discontinued ruler",
                unit_cost_cents=120,
                bulk_pack_size=10,
                catalog_active=False,
            ),
            PD,
        ),
        expected_status=201,
    )
    spec = create_spec(school["id"])

    liaison = make_school_liaison_headers(school["id"])
    response = api.create_kit_spec_line(
        {
            "grade_kit_spec_id": spec["id"],
            "supply_item_id": ruler["id"],
            "qty_per_student": 2,
        },
        liaison,
    )
    validate_error(response, ApiErrorId.ERR_ITEM_INACTIVE.value, expected_status=422)

    reread = validate_success(api.get_grade_kit_spec(spec["id"], liaison))
    assert reread["line_count"] == 0
    rows, _ = validate_paginated(
        api.list_kit_spec_lines(liaison, params={"grade_kit_spec_id": spec["id"]})
    )
    assert rows == [], "a rejected line must not be persisted"


def test_publishing_a_needs_list_without_lines_is_rejected(api):
    """PRD 3.1: "Publication moves the list from `DRAFT` to `PUBLISHED` and is guarded
    by five conditions: the list must currently be in `DRAFT`; it must carry at least
    one line, otherwise `ERR_INVALID_SPEC_STATE`; the governing school's
    `partnership_status` must be `ACTIVE`, otherwise `ERR_SCHOOL_PARTNERSHIP_INACTIVE`;
    no other needs list for the same `school_id` and `grade_band` may already be
    `PUBLISHED`, otherwise `ERR_DUPLICATE_KIT_SPEC`; and every one of its lines must
    reference a catalogue item whose `catalog_active` is true, otherwise
    `ERR_ITEM_INACTIVE`."

    Design: Corner/state_machines/kit_spec_publish_without_lines_is_rejected
    """
    school = create_active_school()
    spec = create_spec(school["id"])

    response = move_spec(school["id"], spec["id"], "PUBLISHED")
    validate_error(response, ApiErrorId.ERR_INVALID_SPEC_STATE.value, expected_status=409)

    liaison = make_school_liaison_headers(school["id"])
    assert validate_success(api.get_grade_kit_spec(spec["id"], liaison))["status"] == "DRAFT"
    assert validate_success(api.get_school(school["id"], PD))["target_student_count"] == 0


def test_second_published_needs_list_for_the_same_band_is_rejected(api):
    """PRD 3.1: "Publication moves the list from `DRAFT` to `PUBLISHED` and is guarded
    by five conditions: the list must currently be in `DRAFT`; it must carry at least
    one line, otherwise `ERR_INVALID_SPEC_STATE`; the governing school's
    `partnership_status` must be `ACTIVE`, otherwise `ERR_SCHOOL_PARTNERSHIP_INACTIVE`;
    no other needs list for the same `school_id` and `grade_band` may already be
    `PUBLISHED`, otherwise `ERR_DUPLICATE_KIT_SPEC`; and every one of its lines must
    reference a catalogue item whose `catalog_active` is true, otherwise
    `ERR_ITEM_INACTIVE`."
    PRD 3.1: "On success `kit_unit_cost_cents` is recomputed, the school's
    `target_student_count` is recomputed as the sum of `student_target_count` over that
    school's `PUBLISHED` needs lists, and both the needs list's `version` and the
    school's `version` are incremented by 1."

    Design: Corner/state_machines/second_published_spec_for_same_band_is_rejected
    """
    school = create_active_school()
    backpack = create_backpack()
    create_published_spec(
        school["id"], [(backpack["id"], 1)], grade_band="K_2", student_target_count=100
    )

    second = create_spec(school["id"], grade_band="K_2", student_target_count=60)
    add_spec_line(school["id"], second["id"], backpack["id"], qty_per_student=1)

    response = move_spec(school["id"], second["id"], "PUBLISHED")
    validate_error(response, ApiErrorId.ERR_DUPLICATE_KIT_SPEC.value, expected_status=409)

    liaison = make_school_liaison_headers(school["id"])
    assert validate_success(api.get_grade_kit_spec(second["id"], liaison))["status"] == "DRAFT"
    assert validate_success(api.get_school(school["id"], PD))["target_student_count"] == 100


def test_needs_list_line_listing_is_filtered_by_its_parent(api):
    """PRD 3.1: "Needs lists of one school can be listed with an optional `status`
    filter alongside `limit` and `offset`, and lines can be listed filtered by
    `grade_kit_spec_id` and by `supply_item_id`."
    PRD 3.1: "`kit_unit_cost_cents` is the cost of one complete kit for the band: for
    each line of the list, multiply that line's `qty_per_student` by the
    `unit_cost_cents` of the catalogue item it references, and add those products
    together across every line of the list."

    Design: Corner/endpoints/kit_spec_line_filtered_list_returns_only_the_requested_parent
    """
    school = create_active_school()
    backpack = create_backpack()
    pencil = create_pencil()
    liaison = make_school_liaison_headers(school["id"])

    spec_a = create_spec(school["id"], grade_band="K_2", student_target_count=100)
    line_a = add_spec_line(school["id"], spec_a["id"], backpack["id"], qty_per_student=1)
    spec_b = create_spec(school["id"], grade_band="G3_5", student_target_count=80)
    add_spec_line(school["id"], spec_b["id"], backpack["id"], qty_per_student=1)
    add_spec_line(school["id"], spec_b["id"], pencil["id"], qty_per_student=3)

    rows_a, _ = validate_paginated(
        api.list_kit_spec_lines(liaison, params={"grade_kit_spec_id": spec_a["id"]})
    )
    assert len(rows_a) == 1 and rows_a[0]["id"] == line_a["id"]

    rows_b, _ = validate_paginated(
        api.list_kit_spec_lines(liaison, params={"grade_kit_spec_id": spec_b["id"]})
    )
    assert len(rows_b) == 2

    rows_pencil, _ = validate_paginated(
        api.list_kit_spec_lines(liaison, params={"supply_item_id": pencil["id"]})
    )
    assert len(rows_pencil) == 1

    reread_b = validate_success(api.get_grade_kit_spec(spec_b["id"], liaison))
    assert reread_b["kit_unit_cost_cents"] == 2200, "1*1450 + 3*250 = 2200 cents"
