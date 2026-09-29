"""
Entity-surface corners: envelopes, declared defaults, computed fields, immutable
evidence rows and the two layers of reference checking on a flat topology.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_PRODUCT_NOT_ON_AGREEMENT,
    ERR_RESOURCE_NOT_FOUND,
    ERR_UNKNOWN_REFERENCE,
)
from test_helpers.assertions import (
    assert_cents,
    assert_common_fields,
    assert_equipment_ledger,
    assert_immutable_evidence_fields,
    assert_instant_equals,
    assert_pagination_meta,
    assert_sorted_by_created_at,
)
from test_helpers.test_users import (
    ACCOUNT_MANAGER_HEADERS,
    AUDITOR_1_HEADERS,
    PLATFORM_ADMIN_HEADERS,
)
from test_helpers.types import (
    AGREEMENT_DRAFT,
    DELIVERY_DELIVERED,
    DISPENSER_ACTIVE,
    OP_UP,
    PLACEMENT_INSTALLED,
    PLACEMENT_PENDING_INSTALL,
    POSTURE_NORMAL,
    SITE_ACTIVE,
    SOURCE_DEVICE,
    TECH_AVAILABLE,
    TECH_OFF_DUTY,
    TIER_STANDARD,
)

UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_PRODUCT_UUID = "00000000-0000-4000-8000-0000000000ff"


def test_customer_creation_returns_the_envelope_with_its_declared_defaults(api):
    """
    A create carrying only the two required fields comes back at 201 with the whole
    row inside the success envelope: billing status CURRENT, both ledgers zero,
    version 1, and created_at equal to updated_at.

    PRD §3.1: "The two ledger counters, `equipment_on_placement_value_cents` and
    `active_agreement_count`, both start at 0 and are maintained by the system
    thereafter."

    Design: Corner/entities/customer_creation_returns_envelope_with_declared_defaults
    """
    customer = validate_success(
        api.create_customer(
            F.customer_payload(
                name="Harbor Grill Group", sustainability_goal_water_l=500000
            ),
            ACCOUNT_MANAGER_HEADERS,
        ),
        201,
    )

    assert_common_fields(customer)
    assert customer["billing_status"] == "CURRENT"
    assert_equipment_ledger(customer, 0)
    assert customer["active_agreement_count"] == 0
    assert customer["version"] == 1
    assert customer["created_at"] == customer["updated_at"]
    assert customer["name"] == "Harbor Grill Group"
    assert customer["sustainability_goal_water_l"] == 500000
    assert is_valid_uuid(customer["id"])


def test_placement_read_back_matches_what_creation_stamped(api):
    """
    A GET on a never-installed placement returns exactly the creation stamp:
    PENDING_INSTALL on the lifecycle axis, UP on the health axis, installed_at
    still null and the odometer seeded from initial_cycle_count.

    PRD §3.3: "A new placement begins with `placement_status` `PENDING_INSTALL`,
    `operational_status` `UP`, `installed_at` null, `last_cycle_count` equal to
    `initial_cycle_count`, `cycles_since_calibration` 0, `open_alert_count` 0, and
    both `retrieval_due_date` and `retrieved_at` null."

    Design: Corner/entities/placement_read_back_matches_the_stored_representation
    """
    base = X.program_base(api)
    created = X.create_placement(
        api, base, asset_tag="AT-C01", initial_cycle_count=250
    )

    placement = get_success_data(
        api.get_machine_placement(created["id"], base["technician_headers"])
    )
    assert placement["placement_status"] == PLACEMENT_PENDING_INSTALL
    assert placement["operational_status"] == OP_UP
    assert placement["installed_at"] is None
    assert placement["last_cycle_count"] == 250
    assert placement["cycles_since_calibration"] == 0
    assert placement["open_alert_count"] == 0
    assert placement["retrieval_due_date"] is None
    assert placement["retrieved_at"] is None
    assert placement["asset_tag"] == "AT-C01"
    assert placement["site_id"] == base["site_id"]
    assert placement["agreement_id"] == base["agreement_id"]


def test_placement_listing_counts_the_filtered_set_not_the_page(api):
    """
    Three placements on one kitchen: limit 2 returns two rows with total_count 3
    and has_more true, offset 2 returns the last row with has_more false, and a
    filter that matches nothing reports total_count 0.

    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope, where `total_count` is the
    number of rows matching the filters before pagination is applied and `has_more`
    states whether any matching row remains beyond the returned page."

    Design: Corner/entities/placement_list_pagination_reports_total_count_and_has_more
    """
    base = X.program_base(api)
    created = [
        X.create_placement(api, base, asset_tag=f"AT-C0{index + 1}")
        for index in range(3)
    ]

    first_page, first_meta = validate_paginated(
        api.list_machine_placements(
            ACCOUNT_MANAGER_HEADERS,
            {"site_id": base["site_id"], "limit": 2, "offset": 0},
        )
    )
    assert len(first_page) == 2
    assert_pagination_meta(first_meta, 2, 0, 3, True)
    assert_sorted_by_created_at(first_page)
    assert [row["id"] for row in first_page] == [created[0]["id"], created[1]["id"]]

    second_page, second_meta = validate_paginated(
        api.list_machine_placements(
            ACCOUNT_MANAGER_HEADERS,
            {"site_id": base["site_id"], "limit": 2, "offset": 2},
        )
    )
    assert [row["id"] for row in second_page] == [created[2]["id"]]
    assert_pagination_meta(second_meta, 2, 2, 3, False)

    empty, empty_meta = validate_paginated(
        api.list_machine_placements(
            ACCOUNT_MANAGER_HEADERS,
            {"site_id": base["site_id"], "placement_status": PLACEMENT_INSTALLED},
        )
    )
    assert empty == []
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False


def test_an_unknown_id_and_a_wrong_type_id_are_both_not_found(api):
    """
    A well-formed identifier nobody holds and a real Site identifier used on the
    customers path are both 404s: a wrong-type id is never treated as a hit.

    PRD §2.8: "6. **Path resource existence** — every identifier embedded in the
    URL must resolve to a live row of the expected entity type, otherwise
    `ERR_RESOURCE_NOT_FOUND` (404). An id that belongs to a different entity type
    is treated as not found."

    Design: Corner/entities/get_customer_with_unknown_id_returns_resource_not_found
    """
    customer = X.create_customer(api)
    site = X.create_site(api, customer["id"])

    validate_error(
        api.get_customer(UNKNOWN_UUID, ACCOUNT_MANAGER_HEADERS),
        ERR_RESOURCE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_customer(site["id"], ACCOUNT_MANAGER_HEADERS),
        ERR_RESOURCE_NOT_FOUND,
        404,
    )


def test_a_site_created_without_a_region_code_is_rejected_and_persists_nothing(api):
    """
    region_code is a required field with no default, so omitting it is a shape
    failure and the follow-up listing shows the rejected create left no row behind
    — no blank or inferred region can leak into dispatch eligibility later.

    PRD §2.8: "4. **Request shape** — otherwise `ERR_INVALID_REQUEST` (400). The
    body must be a JSON object; every required field must be present and non-null;
    every field must match its declared JSON type; enum fields must name a declared
    member; monetary and count fields must be integers no smaller than zero;
    percentage tolerances must be numeric and greater than zero; timestamps must be
    ISO 8601 UTC; unknown fields are ignored rather than rejected."

    Design: Corner/entities/site_creation_missing_required_region_code_is_rejected
    """
    customer = X.create_customer(api)

    validate_error(
        api.create_site(
            F.site_payload(customer["id"], region_code=None), ACCOUNT_MANAGER_HEADERS
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    rows, meta = validate_paginated(
        api.list_sites(ACCOUNT_MANAGER_HEADERS, {"customer_id": customer["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_omitted_optional_fields_take_their_declared_defaults(api):
    """
    Four defaults across three entities in one pass: a detergent's tolerance is
    10.00 with every sanitizer-only field absent, a kitchen is STANDARD and ACTIVE
    with a NORMAL posture, and a fresh agreement notices renewal 60 days out with
    auto-renew off, no fee and no term end.

    PRD §3.2: "Two optional fields round out the draft: `renewal_notice_days`, how
    many days before the term end the renewal window opens, at least 1 and
    defaulting to 60, and `auto_renew`, a boolean defaulting to false that is
    surfaced on renewal notices as information only and never itself renews
    anything."

    Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
    """
    customer = X.create_customer(api)

    detergent = validate_success(
        api.create_chemical_product(F.detergent_payload(), PLATFORM_ADMIN_HEADERS), 201
    )
    assert detergent["concentration_tolerance_pct"] == pytest.approx(10.00, abs=0.001)
    # The three sanitizer-only fields must be omitted on a DETERGENT.
    assert detergent.get("sanitizer_min_ppm") is None
    assert detergent.get("sanitizer_max_ppm") is None
    assert detergent.get("min_contact_seconds") is None

    site = validate_success(
        api.create_site(F.site_payload(customer["id"]), ACCOUNT_MANAGER_HEADERS), 201
    )
    assert site["priority_tier"] == TIER_STANDARD
    assert site["status"] == SITE_ACTIVE
    assert site["service_posture"] == POSTURE_NORMAL
    assert site["open_ticket_count"] == 0

    agreement = validate_success(
        api.create_service_agreement(
            F.service_agreement_payload(customer["id"], [detergent["id"]]),
            ACCOUNT_MANAGER_HEADERS,
        ),
        201,
    )
    assert agreement["renewal_notice_days"] == 60
    assert agreement["auto_renew"] is False
    assert agreement["status"] == AGREEMENT_DRAFT
    assert agreement["renewal_count"] == 0
    assert agreement["placement_count"] == 0
    assert agreement["early_termination_fee_cents"] is None
    assert agreement["termination_effective_date"] is None
    assert agreement["term_end_date"] is None


def test_delivery_volume_and_price_are_derived_from_the_unit_count_alone(api):
    """
    The client sends only a unit count: 12 containers of a 20000 ml product bill
    240000 ml at the 5 percent tier, a unit price of 9120 cents and 109440 in total,
    while 9 containers sit below the tier and bill the undiscounted 86400. Each
    delivery advances the kitchen's version.

    PRD §3.7: "The discounted **unit** price is then computed by multiplying the
    product's `unit_price_cents` by one minus that rate and rounding half up to
    whole cents, and `amount_cents` is that rounded unit price multiplied by
    `unit_count`."

    Design: Corner/entities/delivery_quantity_and_amount_are_computed_not_supplied
    """
    base = X.program_base(api)
    version_before = base["site"]["version"]

    first = X.record_delivery(
        api,
        base,
        unit_count=12,
        delivered_at="2026-08-01T00:00:00Z",
        expected_site_version=version_before,
    )
    assert first["quantity_ml"] == 240000
    assert_cents(first["amount_cents"], 109440)
    assert first["status"] == DELIVERY_DELIVERED

    version_after = X.site_version(api, base["site_id"])
    assert version_after == version_before + 1

    second = X.record_delivery(
        api,
        base,
        unit_count=9,
        delivered_at="2026-08-01T00:00:00Z",
        expected_site_version=version_after,
    )
    assert second["quantity_ml"] == 180000
    assert_cents(second["amount_cents"], 86400)


def test_system_fields_are_server_generated_and_a_patch_advances_the_version(api):
    """
    A technician create stamps version 1 with created_at equal to updated_at, and a
    PATCH that only names the status advances the version to 2, freezes created_at,
    moves updated_at to the logical clock, leaves the certification alone and does
    not let the computed counters be written.

    PRD §2.4: "Nothing in this system reads wall-clock time. A single server-held
    logical clock supplies every instant the platform stamps"

    Design: Corner/entities/system_fields_are_server_generated_and_version_advances_on_write
    """
    technician = validate_success(
        api.create_technician(
            F.technician_payload(name="Rico Vance", status=None),
            PLATFORM_ADMIN_HEADERS,
        ),
        201,
    )
    assert_common_fields(technician)
    assert technician["version"] == 1
    assert technician["status"] == TECH_AVAILABLE
    assert technician["open_ticket_count"] == 0
    assert technician["quality_flag_count"] == 0
    assert technician["created_at"] == technician["updated_at"]

    X.set_clock(api, "2026-08-01T09:00:00Z")

    patched = validate_success(
        api.update_technician(
            technician["id"], {"status": TECH_OFF_DUTY}, PLATFORM_ADMIN_HEADERS
        )
    )
    assert patched["version"] == 2
    assert patched["status"] == TECH_OFF_DUTY
    assert patched["created_at"] == technician["created_at"]
    assert_instant_equals(patched["updated_at"], "2026-08-01T09:00:00Z", "updated_at")
    assert patched["certification_level"] == technician["certification_level"]
    assert patched["open_ticket_count"] == 0


def test_bad_enums_inverted_intervals_and_negative_money_are_all_shape_failures(api):
    """
    Three distinct malformed payloads all land on the same shape rung: a product
    type outside the declared member set, a pressure band whose ends are equal
    rather than strictly ordered, and a negative price. None is coerced, and the
    catalog stays empty.

    PRD §3.1: "and `min_rinse_pressure_psi` and `max_rinse_pressure_psi`, the
    acceptable band for final-rinse line pressure, where the maximum must be
    strictly greater than the minimum — a model definition that inverts them is
    refused with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/invalid_enum_and_inverted_interval_payloads_are_rejected
    """
    validate_error(
        api.create_chemical_product(
            F.detergent_payload(sku="BLEACH-1", product_type="BLEACH"),
            PLATFORM_ADMIN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_machine_model(
            F.machine_model_payload(
                model_code="DT-BAD", min_rinse_pressure_psi=25, max_rinse_pressure_psi=25
            ),
            PLATFORM_ADMIN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_chemical_product(
            F.detergent_payload(sku="DET-NEG", unit_price_cents=-1),
            PLATFORM_ADMIN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )


def test_a_telemetry_reading_carries_no_version_and_no_updated_at(api):
    """
    Evidence rows are append-only: the reading comes back with an id and a
    created_at but neither of the two mutable-resource fields, its delta is measured
    from the placement's odometer, and its source defaults to DEVICE.

    PRD §3.4: "and an optional `source` of either `DEVICE` or `MANUAL_AUDIT`,
    defaulting to `DEVICE`."

    Design: Corner/entities/telemetry_reading_and_calibration_record_are_immutable_rows
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-C01")

    created = validate_success(
        api.create_telemetry_reading(
            placement["id"],
            F.telemetry_reading_payload("2026-08-01T00:00:00Z", 40),
            PLATFORM_ADMIN_HEADERS,
        ),
        201,
    )
    assert created["cycle_delta"] == 40
    assert created["triggered_alert_types"] == []

    reading = get_success_data(api.get_telemetry_reading(created["id"], AUDITOR_1_HEADERS))
    assert_immutable_evidence_fields(reading)
    assert reading["source"] == SOURCE_DEVICE
    assert reading["placement_id"] == placement["id"]
    assert_instant_equals(reading["reading_at"], "2026-08-01T00:00:00Z", "reading_at")
    assert reading["cycle_count_total"] == 40
    assert is_iso8601_timestamp(reading["created_at"])


def test_a_placement_cannot_pair_one_customers_agreement_with_anothers_kitchen(api):
    """
    Both parents exist and both are individually valid, but they belong to
    different accounts; the cross-parent ownership edge is what fails, and nothing
    is capitalised.

    PRD §3.3: "the site's owning customer must be the same customer the agreement
    belongs to, and a cross-account pairing is refused with `ERR_UNKNOWN_REFERENCE`"

    Design: Corner/entities/placement_creation_against_another_customers_agreement_is_rejected
    """
    base = X.program_base(api)
    other_customer = X.create_customer(api, name="Copper Kettle Cafeterias")
    other_site = X.create_site(api, other_customer["id"], name="Copper Kettle Line 1")

    validate_error(
        api.create_machine_placement(
            F.machine_placement_payload(
                other_site["id"],
                base["agreement_id"],
                base["model_id"],
                base["agreement_version"],
                asset_tag="AT-C01",
            ),
            ACCOUNT_MANAGER_HEADERS,
        ),
        ERR_UNKNOWN_REFERENCE,
        422,
    )

    customer = get_success_data(
        api.get_customer(base["customer_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_equipment_ledger(customer, 0)
    agreement = get_success_data(
        api.get_service_agreement(base["agreement_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert agreement["placement_count"] == 0


def test_dispenser_references_are_checked_for_existence_before_membership(api):
    """
    On a flat topology every association is an id in a body checked in two layers:
    an id that resolves to nothing is an unknown reference, while a real product
    absent from the agreement's covered list is a coverage failure. Only the third
    call, naming the covered detergent, creates a row.

    PRD §2.8: "7. **Body reference existence** — every foreign key supplied in a
    body must resolve to an existing row, otherwise `ERR_UNKNOWN_REFERENCE` (422)."

    Design: Corner/entities/flat_topology_cross_reference_integrity_on_dispenser_creation
    """
    # The agreement covers DET-100 only, so SAN-200 exists but is uncovered.
    base = X.program_base(api)
    sanitizer = X.create_sanitizer(api)
    assert sanitizer["id"] not in base["agreement"]["covered_product_ids"]
    placement = X.installed_placement(api, base, asset_tag="AT-C01")

    validate_error(
        api.create_dispenser(
            F.dispenser_payload(placement["id"], UNKNOWN_PRODUCT_UUID, 8.00),
            base["technician_headers"],
        ),
        ERR_UNKNOWN_REFERENCE,
        422,
    )
    validate_error(
        api.create_dispenser(
            F.dispenser_payload(placement["id"], sanitizer["id"], 2.00),
            base["technician_headers"],
        ),
        ERR_PRODUCT_NOT_ON_AGREEMENT,
        422,
    )

    dispenser = validate_success(
        api.create_dispenser(
            F.dispenser_payload(placement["id"], base["detergent_id"], 8.00),
            base["technician_headers"],
        ),
        201,
    )
    assert dispenser["dispenser_status"] == DISPENSER_ACTIVE
    assert dispenser["prior_dose_ml_per_rack"] is None
    assert dispenser["last_calibrated_at"] is None
    assert dispenser["lockout_reason"] is None
    assert dispenser["dose_effective_at"] == dispenser["created_at"]

    rows, _meta = validate_paginated(
        api.list_dispensers(
            base["technician_headers"], {"placement_id": placement["id"], "limit": 100}
        )
    )
    assert len(rows) == 1
