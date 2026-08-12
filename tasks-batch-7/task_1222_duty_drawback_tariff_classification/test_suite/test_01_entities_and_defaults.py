"""Entity creation defaults, computed fields, not-found, and pagination."""
from test_helpers import ApiErrorId, NON_EXISTENT_UUID, add_certified_classification, onboard_client, onboard_client_b, TEST_USERS, is_valid_uuid, validate_error, validate_paginated, validate_success
from test_helpers.factories import create_client_payload, create_classification_payload, create_export_shipment_payload, create_import_entry_payload

ADMIN = TEST_USERS["firm_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def test_client_creation_applies_defaults(api):
    """PRD 3.1: "A new client begins in `engagement_status` `ACTIVE` with its
    aggregates zeroed: `lifetime_recovered_cents` at zero,
    `projected_fee_accrual_cents` at zero, and `open_audit_count` at zero."
    PRD 2.5: "The `version` is an integer that starts at 1 on creation and
    increments by one on every mutation of the resource — including mutations
    driven by cross-entity cascades, so a single client-visible operation may
    advance the versions of several resources at once."

    Design: Corner/entities/client_creation_applies_defaults
    """
    client = validate_success(
        api.create_client(create_client_payload(), ADMIN), 201
    )
    assert client["engagement_status"] == "ACTIVE"
    assert client["version"] == 1
    assert client["lifetime_recovered_cents"] == 0

    fetched = validate_success(api.get_client(client["id"], ADMIN))
    assert fetched["projected_fee_accrual_cents"] == 0
    assert fetched["open_audit_count"] == 0


def test_client_create_missing_required_returns_invalid_request(api):
    """PRD 2.7: "Only after the target is located does the server check body
    shape — missing required fields, invalid enum values, non-positive integers,
    or a missing required optimistic-concurrency field — as
    `ERR_INVALID_REQUEST`."
    PRD 3.1: "A `FirmAdmin` onboards each importer or exporter as a `Client` by
    supplying the legal `name`, the IRS-issued `importer_of_record_number` —
    which must be globally unique across all clients — and the engagement's
    `contingency_fee_bps`, the firm's percentage cut of any recovered duty
    expressed in basis points."

    Design: Corner/entities/client_create_missing_required_returns_invalid_request
    """
    payload = {
        "name": "Acme Imports",
        "importer_of_record_number": "12-3456789",
    }
    res = api.create_client(payload, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(api.list_clients(ADMIN))
    assert meta["total_count"] == 0, "no client may be persisted"


def test_client_create_extra_id_input_ignored(api):
    """PRD 2.5: "The `id` is a server-minted UUID with no type prefix."
    PRD 2.5: "The `version` is an integer that starts at 1 on creation and
    increments by one on every mutation of the resource — including mutations
    driven by cross-entity cascades, so a single client-visible operation may
    advance the versions of several resources at once."

    Design: Corner/entities/client_create_extra_id_input_ignored
    """
    payload = create_client_payload(
        id="11111111-2222-3333-4444-555555555555", version=99
    )
    client = validate_success(api.create_client(payload, ADMIN), 201)
    assert client["id"] != "11111111-2222-3333-4444-555555555555", (
        "the server mints its own id"
    )
    assert is_valid_uuid(client["id"])
    assert client["version"] == 1


def test_client_get_not_found_returns_404(api):
    """PRD 2.7: "Path-template identifiers are then resolved left to right, with
    the first nonexistent identifier producing `ERR_NOT_FOUND`."

    Design: Corner/entities/client_get_not_found_returns_404
    """
    res = api.get_client(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_client_list_pagination_fields(api):
    """PRD 2.3: "The `limit` parameter sets the maximum number of items
    returned; it defaults to 10, accepts a minimum of 1, and is capped at 100.
    The `offset` parameter sets the number of items to skip and defaults to 0.
    Unless otherwise specified, every list endpoint returns resources sorted by
    `created_at` in ascending order. Paginated list responses carry `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    envelope."

    Design: Corner/entities/client_list_pagination_fields
    """
    client_a = onboard_client()
    client_b = onboard_client_b()

    page1, meta1 = validate_paginated(api.list_clients(ADMIN, params={"limit": 1}))
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_clients(ADMIN, params={"limit": 1, "offset": 1})
    )
    assert len(page2) == 1
    assert meta2["has_more"] is False
    assert page2[0]["id"] in (client_a["id"], client_b["id"])
    assert page2[0]["id"] != page1[0]["id"]


def test_classification_first_sale_computed_eligible(api):
    """PRD 3.2: "The system derives `first_sale_eligible`, which is true exactly
    when all three booleans are true and `first_sale_price_cents` is present and
    strictly less than `declared_unit_value_cents`. From that it derives
    `appraised_unit_value_cents`: the first-sale price when eligible, otherwise
    the declared unit value."

    Design: Corner/entities/classification_first_sale_computed_eligible
    """
    client = onboard_client()
    cls = validate_success(
        api.create_classification(
            create_classification_payload(
                client["id"],
                first_sale_price_cents=4000,
                bona_fide_sale=True,
                arms_length=True,
                clearly_destined_us=True,
            ),
            ANALYST,
        ),
        201,
    )
    assert cls["first_sale_eligible"] is True
    assert cls["appraised_unit_value_cents"] == 4000


def test_classification_first_sale_computed_ineligible_when_price_higher(api):
    """PRD 3.2: "The system derives `first_sale_eligible`, which is true exactly
    when all three booleans are true and `first_sale_price_cents` is present and
    strictly less than `declared_unit_value_cents`. From that it derives
    `appraised_unit_value_cents`: the first-sale price when eligible, otherwise
    the declared unit value."

    Design: Corner/entities/classification_first_sale_computed_ineligible_when_price_higher
    """
    client = onboard_client()
    cls = validate_success(
        api.create_classification(
            create_classification_payload(
                client["id"],
                first_sale_price_cents=6000,
                bona_fide_sale=True,
                arms_length=True,
                clearly_destined_us=True,
            ),
            ANALYST,
        ),
        201,
    )
    assert cls["first_sale_eligible"] is False, (
        "6000 is not strictly less than declared 5000: the savings condition fails"
    )
    assert cls["appraised_unit_value_cents"] == 5000


def test_entry_computed_fields_on_create_without_measures(api):
    """PRD 3.3: "The entry's `drawback_eligible_duty_cents` is then the greater
    of zero or `duty_paid_cents` minus `non_drawbackable_cents`, and its
    `unclaimed_duty_cents` is the eligible duty minus the sum of
    `drawback_amount_cents` over all `ACTIVE` claim lines referencing it."
    PRD 3.3: "Both resources track a system-maintained `matched_quantity`
    counting units consumed by `ACTIVE` claim lines, and both derive a `status`
    from the same bands: `UNMATCHED` when `matched_quantity` is zero,
    `PARTIALLY_MATCHED` when it is greater than zero but below the total
    quantity, and `MATCHED` once it reaches the entry's `line_quantity` or the
    shipment's `quantity` respectively."

    Design: Corner/entities/entry_computed_fields_on_create_without_measures
    """
    client = onboard_client()
    cls = add_certified_classification(client["id"])
    entry = validate_success(
        api.create_import_entry(
            create_import_entry_payload(client["id"], cls["id"]), ANALYST
        ),
        201,
    )
    assert entry["non_drawbackable_cents"] == 0
    assert entry["drawback_eligible_duty_cents"] == 82500
    assert entry["unclaimed_duty_cents"] == 82500
    assert entry["matched_quantity"] == 0
    assert entry["status"] == "UNMATCHED"


def test_export_defaults_value_pool(api):
    """PRD 3.3: "Symmetrically, each shipment's `value_pool_remaining_cents` is
    its `fob_value_cents` minus the sum of `drawback_amount_cents` over `ACTIVE`
    lines referencing it."
    PRD 3.3: "Both resources track a system-maintained `matched_quantity`
    counting units consumed by `ACTIVE` claim lines, and both derive a `status`
    from the same bands: `UNMATCHED` when `matched_quantity` is zero,
    `PARTIALLY_MATCHED` when it is greater than zero but below the total
    quantity, and `MATCHED` once it reaches the entry's `line_quantity` or the
    shipment's `quantity` respectively."

    Design: Corner/entities/export_defaults_value_pool
    """
    client = onboard_client()
    export = validate_success(
        api.create_export_shipment(
            create_export_shipment_payload(client["id"]), ANALYST
        ),
        201,
    )
    assert export["value_pool_remaining_cents"] == 480000
    assert export["matched_quantity"] == 0
    assert export["status"] == "UNMATCHED"


def test_claim_create_invalid_enum_rejected(api):
    """PRD 2.7: "Only after the target is located does the server check body
    shape — missing required fields, invalid enum values, non-positive integers,
    or a missing required optimistic-concurrency field — as
    `ERR_INVALID_REQUEST`."
    PRD 3.4: "An `Analyst` opens a `DrawbackClaim` for a client by supplying
    `client_id`, a `claim_type` of `DIRECT_IDENTIFICATION` or `SUBSTITUTION`,
    and a coverage window from `period_start` to `period_end`."

    Design: Corner/entities/claim_create_invalid_enum_rejected
    """
    client = onboard_client()
    res = api.create_claim(
        {
            "client_id": client["id"],
            "claim_type": "UNUSED_MERCHANDISE",
            "period_start": "2026-01-01T00:00:00Z",
            "period_end": "2026-03-31T00:00:00Z",
        },
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_cross_client_fk_integrity_on_entry(api):
    """PRD 3.3: "An `ImportEntry` is created with `client_id`, the
    `classification_id` it was entered under — which must reference a
    `CERTIFIED` classification belonging to the same client, otherwise
    `ERR_CLASSIFICATION_NOT_CERTIFIED` or `ERR_CROSS_CLIENT_REFERENCE`
    respectively — the CBP `entry_number`, which must be unique within the
    client (`ERR_DUPLICATE_ENTRY_NUMBER` on collision), the `entry_date` that
    anchors the five-year statutory filing clock, the `port_code`, the
    `line_quantity` of units (which must be positive), the
    `entered_value_cents`, and the `duty_paid_cents` actually paid including
    any trade-remedy surcharges."

    Design: Corner/entities/cross_client_fk_integrity_on_entry
    """
    client_a = onboard_client()
    client_b = onboard_client_b()
    cls_b = add_certified_classification(client_b["id"])

    res = api.create_import_entry(
        create_import_entry_payload(client_a["id"], cls_b["id"]), ANALYST
    )
    validate_error(res, ApiErrorId.ERR_CROSS_CLIENT_REFERENCE)
