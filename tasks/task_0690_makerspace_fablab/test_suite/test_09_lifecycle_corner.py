"""Breadth coverage: entity creation defaults, not-found / required-field /
type-constraint / duplicate-key errors, listing envelope, pagination bounds, and
the cross-entity validations on confirm and enrollment.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_tier,
    register_member,
    create_active_member_on_tier,
    create_machine,
    create_material_item,
    create_certification_for,
    setup_member_machine_cert,
    create_held_reservation,
    create_draft_purchase,
    setup_workshop,
    enroll_member,
    create_member_payload,
    create_tier_payload,
    create_material_item_payload,
    create_reservation_payload,
    make_member_headers,
    make_staff_headers,
)

MAKER_TIER = {
    "code": "MAKER", "name": "Maker", "billing_mode": "MONTHLY",
    "monthly_fee_cents": 0, "discount_bps": 1000, "prepaid_machine_minutes": 0,
    "locker_free_liters": 50, "unsupervised_allowed": True,
}
LASER_MACHINE = {
    "machine_class": "LASER", "hourly_rate_cents": 4800, "setup_fee_cents": 500,
    "min_billing_minutes": 30, "cooldown_minutes": 15, "requires_certification": True,
}
ADMIN = None  # set below via fixture param


# ===========================================================================
# Corner / entities / create_member_returns_201_with_defaults
# ===========================================================================
def test_create_member_returns_201_with_defaults(api, admin_headers):
    """PRD §3.2: "Registration starts the member in `PENDING_WAIVER` subscription
    status with `wallet_credit_cents` and `prepaid_minutes_remaining` both 0."
    PRD §2.4: "an integer `version` that begins at 1 when the resource is created."

    Design: Corner/entities/create_member_returns_201_with_defaults
    """
    tier = create_tier(**MAKER_TIER)
    data = validate_success(
        api.create_member(create_member_payload(tier["id"], email="c1@x.com"), admin_headers),
        expected_status=201,
    )
    assert data["subscription_status"] == "PENDING_WAIVER"
    assert data["wallet_credit_cents"] == 0
    assert data["version"] == 1


# ===========================================================================
# Corner / entities / get_member_not_found_returns_404
# ===========================================================================
def test_get_member_not_found_returns_404(api, admin_headers):
    """PRD §2.6: "Existence comes third: every path identifier and every foreign key
    in the body must resolve to an existing resource, checked left to right, with the
    first unresolved reference returning `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    validate_error(
        api.get_member(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_NOT_FOUND.value
    )


# ===========================================================================
# Corner / entities / create_member_missing_required_field_returns_422
# ===========================================================================
def test_create_member_missing_full_name_returns_422(api, admin_headers):
    """PRD §2.6: "Request well-formedness comes fourth: required fields present ...
    any violation is `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD §3.2: "A new **member** is registered ... with an `email`, a `full_name`, and
    a `tier_id` naming the chosen tier."

    Design: Corner/entities/create_member_missing_required_field_returns_422
    """
    tier = create_tier(**MAKER_TIER)
    validate_error(
        api.create_member({"email": "c2@x.com", "tier_id": tier["id"]}, admin_headers),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


# ===========================================================================
# Corner / entities / create_machine_invalid_enum_class_returns_422
# ===========================================================================
def test_create_machine_invalid_class_returns_422(api, admin_headers):
    """PRD §2.10: "The fleet is partitioned into three machine classes — `LASER`,
    `CNC`, and `PRINTER_3D` ... These exact strings are the only accepted values for
    their fields, and an out-of-range enum on any create or update is an
    `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_machine_invalid_enum_class_returns_422
    """
    validate_error(
        api.create_machine(
            {"name": "Bad", "machine_class": "PLASMA", "hourly_rate_cents": 1000}, admin_headers
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


# ===========================================================================
# Corner / entities / create_tier_duplicate_code_returns_409
# ===========================================================================
def test_duplicate_tier_code_returns_409(api, admin_headers):
    """PRD §2.10: "a duplicate tier `code` is rejected with `ERR_DUPLICATE_TIER_CODE`
    (HTTP 409)."

    Design: Corner/entities/create_tier_duplicate_code_returns_409
    """
    create_tier(code="DUPCODE", name="First")
    validate_error(
        api.create_tier(create_tier_payload(code="DUPCODE", name="Second"), admin_headers),
        ApiErrorId.ERR_DUPLICATE_TIER_CODE.value,
    )


# ===========================================================================
# Corner / entities / create_material_item_duplicate_sku_returns_409
# ===========================================================================
def test_duplicate_sku_returns_409(api, admin_headers):
    """PRD §2.10: "a duplicate material `sku` with `ERR_DUPLICATE_SKU` (HTTP 409)."

    Design: Corner/entities/create_material_item_duplicate_sku_returns_409
    """
    create_material_item(sku="DUPSKU", name="Acrylic", unit_price_cents=133, stock_qty=10)
    validate_error(
        api.create_material_item(
            create_material_item_payload(sku="DUPSKU", name="Acrylic Dup", unit_price_cents=200),
            admin_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_SKU.value,
    )


# ===========================================================================
# Corner / entities / create_member_unknown_tier_fk_returns_404
# ===========================================================================
def test_create_member_unknown_tier_returns_404(api, admin_headers):
    """PRD §2.7: "Whenever a request carries such references, each is resolved before
    the operation's business logic runs, and an unresolved reference yields
    `ERR_NOT_FOUND` (HTTP 404)."

    A POST /members naming a tier_id that resolves to nothing is a 404.

    Design: Corner/entities/create_member_unknown_tier_fk_returns_404
    """
    validate_error(
        api.create_member(
            {"email": "c3@x.com", "full_name": "C Three", "tier_id": NON_EXISTENT_UUID},
            admin_headers,
        ),
        ApiErrorId.ERR_NOT_FOUND.value,
    )


# ===========================================================================
# Corner / entities / list_machines_paginated_envelope
# ===========================================================================
def test_list_machines_paginated_envelope(api, admin_headers):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."
    PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults
    to 10."

    Two machines yield an array envelope with total_count 2 and has_more false.

    Design: Corner/entities/list_machines_paginated_envelope
    """
    create_machine(name="M1", machine_class="LASER", hourly_rate_cents=4800)
    create_machine(name="M2", machine_class="CNC", hourly_rate_cents=9000)
    data, meta = validate_paginated(api.list_machines(admin_headers))
    assert len(data) == 2, len(data)
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is False, meta["has_more"]


# ===========================================================================
# Corner / entities / pagination_limit_over_max_returns_400
# ===========================================================================
def test_pagination_limit_over_max_returns_400(api, admin_headers):
    """PRD §2.3: "A `limit` outside the inclusive range of 1 through 100, or an
    `offset` below 0, is rejected with `ERR_VALIDATION_LIMIT` (HTTP 400)."

    GET /machines?limit=101 is rejected.

    Design: Corner/entities/pagination_limit_over_max_returns_400
    """
    validate_error(
        api.list_machines(admin_headers, params={"limit": 101}),
        ApiErrorId.ERR_VALIDATION_LIMIT.value,
    )


# ===========================================================================
# Corner / validations / confirm_machine_out_of_service_returns_409
# ===========================================================================
def test_confirm_machine_out_of_service_returns_409(api, admin_headers):
    """PRD §3.6: "the machine's `operational_status` is `AVAILABLE`, or else
    `ERR_MACHINE_OUT_OF_SERVICE` (HTTP 409)."

    Confirming a reservation on a machine set OUT_OF_SERVICE is rejected.

    Design: Corner/validations/confirm_machine_out_of_service_returns_409
    """
    member, machine, cert = setup_member_machine_cert(
        machine_class="LASER", tier_overrides=MAKER_TIER, machine_overrides=LASER_MACHINE,
        topup_cents=10000,
    )
    res = create_held_reservation(
        member, machine, cert, "2026-05-24T10:00:00Z", "2026-05-24T11:00:00Z"
    )
    validate_success(api.set_machine_status(machine["id"], "OUT_OF_SERVICE", admin_headers))
    mh = make_member_headers(member["id"])
    v = validate_success(api.get_member(member["id"], mh))["version"]
    validate_error(
        api.confirm_reservation(res["id"], v, mh), ApiErrorId.ERR_MACHINE_OUT_OF_SERVICE.value
    )


# ===========================================================================
# Corner / validations / duplicate_enrollment_returns_409
# ===========================================================================
def test_duplicate_enrollment_returns_409(api):
    """PRD §3.9: "a member already holding a non-terminal enrollment in the same
    workshop is refused with `ERR_DUPLICATE_ENROLLMENT` (HTTP 409)."

    Design: Corner/validations/duplicate_enrollment_returns_409
    """
    tier = create_tier(**MAKER_TIER)
    instructor = register_member(tier["id"])
    student = register_member(tier["id"])
    _, ws = setup_workshop(
        instructor_id=instructor["id"], capacity=5, starts_at="2026-05-25T09:00:00Z"
    )
    enroll_member(ws["id"], student["id"])
    from test_helpers import create_enrollment_payload
    validate_error(
        api.create_enrollment(
            create_enrollment_payload(ws["id"], student["id"]), make_member_headers(student["id"])
        ),
        ApiErrorId.ERR_DUPLICATE_ENROLLMENT.value,
    )


# ===========================================================================
# Corner / validations / create_reservation_end_before_start_returns_422
# ===========================================================================
def test_reservation_end_before_start_returns_422(api):
    """PRD §3.5: "The body is rejected with `ERR_INVALID_REQUEST` (HTTP 422) unless
    `end_at` is strictly after `start_at`."

    Design: Corner/validations/create_reservation_end_before_start_returns_422
    """
    tier = create_tier(**MAKER_TIER)
    member = register_member(tier["id"])
    machine = create_machine(**LASER_MACHINE)
    cert = create_certification_for(member["id"], "LASER")
    payload = create_reservation_payload(
        member["id"], machine["id"], "2026-05-26T11:00:00Z", "2026-05-26T10:00:00Z",
        certification_id=cert["id"],
    )
    validate_error(
        api.create_reservation(payload, make_member_headers(member["id"])),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


# ===========================================================================
# Corner / endpoints / material_bill_decrements_stock_cascade
# ===========================================================================
def test_bill_decrements_item_stock(api):
    """PRD §3.8: "On success, billing recomputes `subtotal_cents`, `surcharge_cents`,
    and `total_cents`, decrements each line's `MaterialItem` `stock_qty` by that
    line's `quantity`, debits `wallet_credit_cents` by `total_cents`, and appends a
    `WalletEntry` of kind `MATERIAL` with a negative `amount_cents`."

    Billing quantity 3 against an item with stock 10 leaves stock 7; at 100c/unit
    with a 10% tier discount the per-line round is round(3*100*0.9)=270, debited from
    the 5000 wallet -> 4730.

    Design: Corner/endpoints/material_bill_decrements_stock_cascade
    """
    tier = create_tier(**MAKER_TIER)
    member = create_active_member_on_tier(tier, topup_cents=5000)
    item = create_material_item(sku="WID1", name="Widget", unit_price_cents=100, stock_qty=10)
    purchase = create_draft_purchase(
        member, [{"material_item_id": item["id"], "quantity": 3}], waste_surcharge_bps=0
    )
    mh = make_member_headers(member["id"])
    billed = validate_success(api.bill_purchase(purchase["id"], mh))
    assert billed["total_cents"] == 270, billed["total_cents"]
    item_after = validate_success(api.get_material_item(item["id"], mh))
    assert item_after["stock_qty"] == 7, item_after["stock_qty"]
    member_after = validate_success(api.get_member(member["id"], mh))
    assert member_after["wallet_credit_cents"] == 4730, member_after["wallet_credit_cents"]


# ===========================================================================
# Corner / endpoints / workshop_attended_mints_certification
# ===========================================================================
def test_attended_mints_certification(api):
    """PRD §3.9: "Marking an enrollment attended requires that its parent workshop be
    `RUNNING` and moves the enrollment to `ATTENDED`; if the workshop's
    `machine_class` is not null, attendance mints a fresh `Certification` for that
    member and `machine_class` ... and writes that certification's id into the
    enrollment's `certification_id`."

    Design: Corner/endpoints/workshop_attended_mints_certification
    """
    from test_helpers import setup_running_workshop_with_enrollment
    instructor, student, ws, enr = setup_running_workshop_with_enrollment(
        capacity=5, machine_class="CNC", starts_at="2026-05-28T09:00:00Z"
    )
    sh = make_staff_headers(instructor["id"])
    attended = validate_success(api.mark_attended(enr["id"], sh))
    assert attended["status"] == "ATTENDED"
    assert attended["certification_id"] is not None, attended["certification_id"]
