"""Role and scope gates: the authentication ladder rung, the four exclusive
operations other roles may not reach, program-contact account scoping, the shared
plant read surface, and the user-scoped repair verification split.
"""
from test_helpers import (
    ALL_PLANT_ROLE_HEADERS,
    COMPLIANCE_1,
    INTAKE_CLERK,
    TECHNICIAN_1_USER_ID,
    TECHNICIAN_2,
    TECHNICIAN_2_USER_ID,
    ApiErrorId,
    assert_part_stock_conserved,
    create_account,
    create_intake_shipment_payload,
    determine_payload,
    get_success_data,
    make_customer_contact_headers,
    read_label,
    read_part,
    read_repair_order,
    read_shell_test,
    read_shipment,
    read_unit,
    setup_certified_units,
    setup_counted_shipment,
    setup_reference_data,
    setup_repair_order,
    setup_tested_units,
    validate_error,
    validate_paginated,
    validate_success,
    verify_repair_payload,
    void_label_payload,
)

SHIPMENTS_PATH = "/intake-shipments"


def _open_draft_shipment(api, customer_account_id):
    """Open one shipment for a program and leave it in DRAFT."""
    return get_success_data(
        api.create_intake_shipment(
            create_intake_shipment_payload(customer_account_id), INTAKE_CLERK
        )
    )


def _second_account():
    """A second program account, so ownership checks have something to compare."""
    return create_account(
        waiver=False, org_name="Southside Prep", contact_email="ad@southside.example"
    )


def test_requests_missing_auth_headers_return_unauthenticated(api):
    """Both header defects land on the same authentication refusal.

    The requirements state: "A request that omits `X-User-Role` entirely, or that
    presents `X-User-Role` as `CustomerContact` without an `X-User-ID`, is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)." They also state:
    "**Authentication** — missing `X-User-Role`, or `CustomerContact` without
    `X-User-ID`: `ERR_UNAUTHENTICATED`." as the first-evaluated rung of the
    rejection ladder, so neither request may fall through to the account-scope
    check: both answer ERR_UNAUTHENTICATED.

    Design: Corner/rbac/requests_missing_auth_headers_return_unauthenticated
    """
    ctx = setup_reference_data()
    shipment = _open_draft_shipment(api, ctx["account"]["id"])
    path = f"{SHIPMENTS_PATH}/{shipment['id']}"

    no_role_at_all = api._request("GET", path, headers={})
    validate_error(no_role_at_all, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    contact_without_user_id = api._request(
        "GET", path, headers={"X-User-Role": "CustomerContact"}
    )
    validate_error(contact_without_user_id, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    assert read_shipment(shipment["id"])["status"] == "DRAFT"


def test_technician_cannot_sign_a_determination(api):
    """The technician who recorded the readings may not sign the verdict.

    The requirements state: "`CertifyingInspector` signs pass, repair and condemn
    determinations, condemns units that cannot be reconditioned, and issues
    recertification labels, but may not record the impact readings they
    adjudicate." and "A caller whose role is not among those authorized for the
    endpoint it addressed is rejected with `ERR_UNAUTHORIZED` (HTTP 403)". The
    session must stay COMPLETED with `determination` and `determined_by_user_id`
    still null so an inspector can still adjudicate it. The expected error id is
    ERR_UNAUTHORIZED.

    Design: Corner/rbac/technician_cannot_sign_a_determination
    """
    ctx = setup_tested_units(unit_count=1)
    session_id = ctx["shell_test"]["id"]

    response = api.determine_shell_test(
        session_id, determine_payload("PASS"), ALL_PLANT_ROLE_HEADERS["Technician"]
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    session = read_shell_test(session_id)
    assert session["status"] == "COMPLETED"
    assert session["determination"] is None
    assert session["determined_by_user_id"] is None
    assert session["version"] == ctx["shell_test"]["version"]
    assert read_unit(ctx["unit"]["id"])["recon_status"] == "TESTED"


def test_intake_clerk_cannot_void_a_certification_label(api):
    """Voiding is reserved to compliance, so the clerk is stopped by the role gate.

    The requirements state: "Voiding a label is the mirror image of issuing one,
    and it is reserved to a `ComplianceOfficer` precisely because it unwinds
    another role's signature." The refusal is the role rung, "A caller whose role
    is not among those authorized for the endpoint it addressed is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)", and none of the void's four hops may run: the
    label stays ACTIVE, the unit stays CERTIFIED and the shipment stays
    READY_FOR_RETURN. The expected error id is ERR_UNAUTHORIZED.

    Design: Corner/rbac/intake_clerk_cannot_void_a_certification_label
    """
    ctx = setup_certified_units(unit_count=1)
    label_id = ctx["label"]["id"]

    response = api.void_certification_label(label_id, void_label_payload(), INTAKE_CLERK)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    label = read_label(label_id)
    assert label["status"] == "ACTIVE"
    assert label["voided_at"] is None
    assert label["voided_by_user_id"] is None
    assert label["void_reason"] is None

    assert read_unit(ctx["unit"]["id"])["recon_status"] == "CERTIFIED"
    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["status"] == "READY_FOR_RETURN"
    assert shipment["units_certified"] == 1
    assert shipment["units_in_process"] == 0


def test_compliance_officer_cannot_install_repair_parts(api):
    """The role gate runs before any stock bucket moves.

    The requirements state: "`Technician` performs teardown, component
    inspection, bench testing and part installation, but may neither sign
    determinations nor issue labels." and "A caller whose role is not among those
    authorized for the endpoint it addressed is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)". On a successful install every reserved line "has its quantity
    moved out of its part's `reserved_qty` and into that part's `consumed_qty`",
    so a refused install must leave the four
    reserved-and-on-hand buckets exactly as the submission left them. The expected
    error id is ERR_UNAUTHORIZED.

    Design: Corner/rbac/compliance_officer_cannot_install_repair_parts
    """
    ctx = setup_repair_order(target_status="PARTS_PENDING", quantity=1, received_qty=4)
    order_id = ctx["repair_order"]["id"]

    response = api.install_repair_order(order_id, {}, COMPLIANCE_1)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    order = read_repair_order(order_id)
    assert order["status"] == "PARTS_PENDING"
    assert order["installed_by_user_id"] is None
    assert order["installed_parts_cents"] == 0
    assert order["version"] == ctx["repair_order"]["version"]

    part = read_part(ctx["part"]["id"])
    assert part["received_qty"] == 4
    assert part["on_hand_qty"] == 3
    assert part["reserved_qty"] == 1
    assert part["consumed_qty"] == 0
    assert_part_stock_conserved(part)


def test_customer_contact_cannot_read_another_accounts_shipment(api):
    """A program contact bound to one account cannot reach another's shipment.

    The requirements state: "When `X-User-Role` is `CustomerContact`, by
    contrast, `X-User-ID` is the `id` of the acting `CustomerAccount`; ownership
    checks on any resource that references a `CustomerAccount` compare the
    resource's account foreign key to `X-User-ID`." They continue: "A
    `CustomerContact` that reaches an authorized read endpoint but targets an
    account, a shipment or a loaner assignment belonging to a different
    `CustomerAccount` is rejected with `ERR_ACCOUNT_SCOPE_VIOLATION` (HTTP 403);
    this scope check is deliberately evaluated *after* the role gate, so that a
    caller with the wrong role for an endpoint still receives `ERR_UNAUTHORIZED`
    rather than a scope error." Both the single-shipment read and the shipment
    list are named scoped reads, so both answer ERR_ACCOUNT_SCOPE_VIOLATION rather
    than a not-found or an authorization error.

    Design: Corner/rbac/customer_contact_cannot_read_another_accounts_shipment
    """
    ctx = setup_reference_data()
    owner_id = ctx["account"]["id"]
    shipment = _open_draft_shipment(api, owner_id)
    outsider_headers = make_customer_contact_headers(_second_account()["id"])

    single_read = api.get_intake_shipment(shipment["id"], outsider_headers)
    validate_error(single_read, ApiErrorId.ERR_ACCOUNT_SCOPE_VIOLATION.value, 403)

    list_read = api.list_intake_shipments(
        outsider_headers, params={"customer_account_id": owner_id}
    )
    validate_error(list_read, ApiErrorId.ERR_ACCOUNT_SCOPE_VIOLATION.value, 403)


def test_customer_contact_reads_their_own_account_and_shipments(api):
    """The same contact reads their own account row and their own shipment list.

    The requirements state: "`CustomerContact` is a read-only representative of a
    single program." and: "When `X-User-Role` is `CustomerContact`, by contrast,
    `X-User-ID` is the `id` of the acting `CustomerAccount`; ownership checks on
    any resource that references a `CustomerAccount` compare the resource's
    account foreign key to `X-User-ID`." The account read and the shipment list
    are both documented for this role, so with `X-User-ID` equal to their own
    account id the ownership comparison succeeds; and because "`total_count` is
    the size of the full filtered result set before the page window is applied",
    the contact sees exactly their own single shipment even though a second
    program's shipment exists.

    Design: Corner/rbac/customer_contact_reads_their_own_account_and_shipments
    """
    ctx = setup_reference_data()
    owner_id = ctx["account"]["id"]
    own_shipment = _open_draft_shipment(api, owner_id)
    other_account = _second_account()
    _open_draft_shipment(api, other_account["id"])

    own_headers = make_customer_contact_headers(owner_id)

    shipments, meta = validate_paginated(
        api.list_intake_shipments(own_headers, params={"customer_account_id": owner_id})
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [row["id"] for row in shipments] == [own_shipment["id"]]

    account = validate_success(api.get_customer_account(owner_id, own_headers), 200)
    assert account["id"] == owner_id
    assert account["liability_waiver_status"] == "ON_FILE"


def test_shared_reads_work_for_every_plant_role(api):
    """The unit list admits all five plant roles on the same row.

    The requirements document the unit list for "PlantManager, IntakeClerk,
    Technician, CertifyingInspector, ComplianceOfficer", and state: "Equipment
    units accept `intake_shipment_id`, `model_spec_id`, `recon_status` and
    `custody_status` — note that the two state axes are filterable
    independently, which is the point of keeping them separate." Every one of the
    five roles must therefore be admitted by the role gate and see the same single
    registered unit.

    Design: Corner/rbac/shared_reads_work_for_every_plant_role
    """
    ctx = setup_counted_shipment(unit_count=1)
    shipment_id = ctx["shipment"]["id"]
    unit_id = ctx["unit"]["id"]

    for role, headers in ALL_PLANT_ROLE_HEADERS.items():
        units, meta = validate_paginated(
            api.list_equipment_units(headers, params={"intake_shipment_id": shipment_id})
        )
        assert meta["total_count"] == 1, role
        assert meta["has_more"] is False, role
        assert [row["id"] for row in units] == [unit_id], role


def test_two_different_technicians_satisfy_the_verification_split(api):
    """A second technician's signature closes the order the first installed.

    The requirements state: "A `Technician` verifies an `INSTALLED` order by
    supplying an `outcome` of `PASSED` or `FAILED` and optionally a `note`; the
    acting `X-User-ID` must differ from the order's `installed_by_user_id`,
    failing which the request is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP
    403)." They continue: "A `PASSED` outcome records `verified_by_user_id` from
    the acting `X-User-ID`, sets `labor_cents` to the flat repair labour charge of
    4,500 cents — forty-five dollars per closed repair — advances the order
    `INSTALLED → CLOSED`, and advances the unit `REPAIR_PENDING → REPAIRED`,
    with both `version` counters advancing by one." The check "is on `X-User-ID`,
    not on role", so a second technician holding the same role succeeds.

    Design: Corner/rbac/two_different_technicians_satisfy_the_verification_split
    """
    ctx = setup_repair_order(target_status="INSTALLED", quantity=1, received_qty=4)
    order_id = ctx["repair_order"]["id"]

    response = api.verify_repair_order(
        order_id,
        verify_repair_payload("PASSED", note="crown re-tested dry, torque to spec"),
        TECHNICIAN_2,
    )
    order = validate_success(response, 200)
    assert order["status"] == "CLOSED"
    assert order["installed_by_user_id"] == TECHNICIAN_1_USER_ID
    assert order["verified_by_user_id"] == TECHNICIAN_2_USER_ID
    assert order["labor_cents"] == 4500
    assert order["installed_parts_cents"] == 4500
    assert order["reserved_parts_cents"] == 0
    assert order["verification_failure_count"] == 0
    assert order["version"] == ctx["repair_order"]["version"] + 1

    unit = read_unit(ctx["unit"]["id"])
    assert unit["recon_status"] == "REPAIRED"
    assert unit["version"] == ctx["unit"]["version"] + 1
