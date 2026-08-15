"""Installer credit gate boundary, suspension cascade, activation checks, and
installer listing."""
from test_helpers import (
    TEST_USERS,
    allocate_current_version,
    api_client,
    assert_installer,
    create_active_installer,
    create_allocation_payload,
    create_installer_payload,
    get_lot,
    make_installer_rep_headers,
    setup_project_with_on_hand_lot,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

MANAGER = TEST_USERS["manager_headers"]
OFFICER = TEST_USERS["officer_headers"]


def test_credit_limit_at_equality_rejected(api):
    """PRD section 3.6: "the credit gate then requires that the installer not
    be on `credit_hold` and that the installer's current
    `credit_exposure_cents` plus the prospective allocation's value — the
    requested units priced at the lot's `unit_cost_cents_provisional` —
    remain strictly below `credit_limit_cents`, failing with
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402) at equality or beyond".
    Ten units at the 55000c provisional cost total exactly the 550000c limit,
    and equality fails.

    Design: Difficulty/boundary_precision_check/credit_limit_boundary_at_equality_triggers_hold
    """
    ctx = setup_project_with_on_hand_lot(
        module_qty=10, lot_qty=10, credit_limit_cents=550000,
    )
    inst_id = ctx["installer"]["id"]
    # The lot's provisional cost is 55000c (declared 50000 + 10% duty).
    assert ctx["lot"]["unit_cost_cents_provisional"] == 55000

    resp = api_client.create_allocation(
        ctx["project"]["id"],
        create_allocation_payload(ctx["lot"]["id"], 10,
                                  ctx["lot"]["version"]),
        make_installer_rep_headers(inst_id),
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


def test_credit_limit_one_unit_below_equality_allowed(api):
    """PRD section 3.6: "the credit gate then requires that the installer not
    be on `credit_hold` and that the installer's current
    `credit_exposure_cents` plus the prospective allocation's value — the
    requested units priced at the lot's `unit_cost_cents_provisional` —
    remain strictly below `credit_limit_cents`, failing with
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402) at equality or beyond".
    Nine units total 495000c, strictly below the 550000c limit, so the
    allocation succeeds.

    Design: Difficulty/boundary_precision_check/credit_limit_boundary_at_equality_triggers_hold
    """
    ctx = setup_project_with_on_hand_lot(
        module_qty=10, lot_qty=10, credit_limit_cents=550000,
    )
    inst_id = ctx["installer"]["id"]

    allocation = allocate_current_version(ctx["project"]["id"], inst_id,
                                          ctx["lot"]["id"], 9)
    assert allocation["status"] == "OPEN"
    assert allocation["qty_allocated"] == 9
    lot = get_lot(ctx["lot"]["id"])
    assert lot["qty_allocated"] == 9
    assert lot["qty_available"] == 1


def test_installer_suspend_cascades_to_cancel_open_allocations(api):
    """PRD section 3.2: "Suspending requires the installer to be `ACTIVE`
    (otherwise `ERR_INSTALLER_NOT_ACTIVE`) and moves it `ACTIVE` →
    `SUSPENDED`; in the same transaction, every `OPEN` allocation on the
    installer's projects is cancelled".
    PRD section 3.6: "Each such cancellation decreases the lot's
    `qty_allocated` by the allocation's quantity and recomputes the project's
    `allocated_value_cents`."

    Design: Corner/state_machines/installer_suspend_cascades_to_cancel_open_allocations
    """
    ctx = setup_project_with_on_hand_lot(module_qty=5, lot_qty=5)
    inst_id = ctx["installer"]["id"]
    allocation = allocate_current_version(ctx["project"]["id"], inst_id,
                                          ctx["lot"]["id"], 5)
    assert allocation["status"] == "OPEN"

    suspended = validate_success(api_client.suspend_installer(inst_id, OFFICER), 200)
    assert suspended["status"] == "SUSPENDED"

    after = validate_success(api_client.get_allocation(allocation["id"], MANAGER), 200)
    assert after["status"] == "CANCELLED", (
        f"suspend must cancel OPEN allocations, got {after['status']}"
    )

    lot = get_lot(ctx["lot"]["id"])
    assert lot["qty_allocated"] == 0, "cascade releases the reserved units"
    assert lot["qty_available"] == 5

    project = validate_success(
        api_client.get_project(ctx["project"]["id"], MANAGER), 200
    )
    assert project["allocated_value_cents"] == 0


def test_installer_invalid_progress_pct_rejected(api):
    """PRD section 3.2: "Activation moves the installer `ONBOARDING` →
    `ACTIVE` and enforces three checks: `credit_limit_cents` must be greater
    than zero, or the request fails with `ERR_CREDIT_LIMIT_REQUIRED`;
    `progress_payment_pct_bp` must lie between 0 and 10000 inclusive, or
    `ERR_INVALID_PROGRESS_PCT`; and `payment_terms_days` must be greater than
    zero, or `ERR_INVALID_PAYMENT_TERMS`."

    Design: Corner/entities/installer_invalid_progress_pct_rejected
    """
    installer = validate_success(
        api_client.create_installer(
            create_installer_payload(progress_payment_pct_bp=15000), MANAGER,
        ),
        201,
    )
    assert_installer(installer)
    assert installer["status"] == "ONBOARDING"

    resp = api_client.activate_installer(installer["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_PROGRESS_PCT)


def test_list_installers_supports_status_filter(api):
    """PRD section 3.2: "Installers can be listed with a `status` filter."

    Design: Corner/endpoints/list_installers_supports_status_filter
    """
    first = create_active_installer(legal_name="Active Solar")
    second = validate_success(
        api_client.create_installer(
            create_installer_payload(legal_name="Onboarding Solar"), MANAGER,
        ),
        201,
    )
    assert second["status"] == "ONBOARDING"

    active, _ = validate_paginated(
        api_client.list_installers(MANAGER, params={"status": "ACTIVE"})
    )
    assert [i["id"] for i in active] == [first["id"]]

    onboarding, _ = validate_paginated(
        api_client.list_installers(MANAGER, params={"status": "ONBOARDING"})
    )
    assert [i["id"] for i in onboarding] == [second["id"]]
