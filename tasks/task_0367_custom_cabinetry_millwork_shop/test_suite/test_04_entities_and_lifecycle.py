"""Entity CRUD, defaults, computed/system fields, and project/draw/install
lifecycle transitions.

Breadth coverage of the Corner-design `entities` and `state_machines` sections:
shop defaults, project retrieval, material listing, not-found, required/typed
fields, computed panel area, the lifetime-paid aggregate, spec lock, the
initial/terminal project states, draw pay idempotency, and the install punch /
reopen / bubble transitions.
"""
from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    ApiErrorId,
    TEST_USERS,
    make_customer_headers,
    setup_base_shop,
    setup_contracted_project,
    setup_installation_punch_pending,
    add_punch_item,
    create_shop,
    create_material,
    create_customer,
    create_project,
    add_spec,
)

ADMIN = TEST_USERS["shop_admin_headers"]
MANAGER = TEST_USERS["shop_manager_headers"]
DESIGNER = TEST_USERS["designer_headers"]
INSTALLER = TEST_USERS["installer_headers"]


# ===========================================================================
# Corner / entities
# ===========================================================================
def test_create_shop_returns_201_with_defaults_applied(api):
    """PRD §3.1: "`deposit_pct_bps` is the deposit percentage of the contract
    total used to compute the deposit draw, defaulting to 3000 and bounded 0
    through 10000. `retainage_pct_bps` is the percentage withheld until install
    completion, defaulting to 1000 and bounded 0 through 5000. `rush_surcharge_bps`
    is the surcharge added to the contract total when a project is flagged rush,
    defaulting to 1500 and bounded 0 through 5000. `max_installs_per_day` is the
    shop-wide install-slot capacity per calendar day, defaulting to 2 and required
    to be at least 1."
    PRD §3.1: "a `currency` (an ISO currency code defaulting to `USD`)"

    Design: Corner/entities/create_shop_returns_201_with_defaults_applied
    """
    data = validate_success(api.create_shop({"name": "Defaults Shop"}, ADMIN), 201)
    assert data["deposit_pct_bps"] == 3000, f"deposit_pct_bps default expected 3000, got {data['deposit_pct_bps']}"
    assert data["retainage_pct_bps"] == 1000, f"retainage_pct_bps default expected 1000, got {data['retainage_pct_bps']}"
    assert data["rush_surcharge_bps"] == 1500, f"rush_surcharge_bps default expected 1500, got {data['rush_surcharge_bps']}"
    assert data["max_installs_per_day"] == 2, f"max_installs_per_day default expected 2, got {data['max_installs_per_day']}"
    assert data["tax_rate_bps"] == 0, f"tax_rate_bps default expected 0, got {data['tax_rate_bps']}"
    assert data["currency"] == "USD", f"currency default expected USD, got {data['currency']}"
    assert data["version"] == 1, f"new shop version expected 1, got {data['version']}"


def test_get_project_returns_stored_data(api):
    """PRD §3.2: "A freshly created project begins in `DRAFT` status with all of its
    ledger fields — `estimate_total_cents`, `contract_total_cents`,
    `deposit_required_cents`, `billed_to_date_cents`, `paid_to_date_cents`, and
    `open_change_delta_cents` — set to zero."
    PRD §3.2: "an optional `margin_policy` of either `STANDARD` or `PREMIUM`
    (default `STANDARD`)"

    Design: Corner/entities/get_project_returns_stored_data
    """
    shop, _, customer = setup_base_shop()
    created = create_project(shop["id"], customer["id"], title="Read me")
    data = validate_success(api.get_project(shop["id"], created["id"], DESIGNER))
    assert data["status"] == "DRAFT", f"project status expected DRAFT, got {data['status']}"
    assert data["contract_total_cents"] == 0, f"contract_total_cents expected 0, got {data['contract_total_cents']}"
    assert data["margin_policy"] == "STANDARD", f"margin_policy expected STANDARD, got {data['margin_policy']}"


def test_list_materials_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is the
    number of records matching the query before pagination and `has_more`
    indicates whether records remain beyond the current page."

    Design: Corner/entities/list_materials_paginated_envelope
    """
    shop = create_shop()
    create_material(shop["id"])
    create_material(shop["id"])
    resp = api.list_materials(shop["id"], MANAGER, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"total_count expected 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"has_more expected True with 2 records and limit 1, got {meta['has_more']}"
    assert len(data) == 1, f"page length expected 1 (limit 1), got {len(data)}"


def test_get_project_nonexistent_returns_not_found(api):
    """PRD §2.5: "The first identifier in the path that does not resolve to an
    existing resource causes immediate rejection with `ERR_NOT_FOUND` (HTTP 404);
    later identifiers are not examined."

    Design: Corner/entities/get_project_nonexistent_returns_not_found
    """
    shop = create_shop()
    resp = api.get_project(shop["id"], "00000000-0000-4000-8000-000000000000", MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_spec_missing_required_field_returns_invalid_request(api):
    """PRD §3.3: "Each spec carries a `label`, the dimensions `width_mm`,
    `height_mm`, and `depth_mm` (each a positive integer in millimeters), a
    `quantity` of identical cabinets (at least one), a `base_unit_price_cents` (the
    pre-margin, pre-finish per-cabinet cost, at least zero), and a `material_id`
    naming the sheet stock the cabinet is cut from."
    PRD §4: "then request-body validity such as required fields, enum ranges,
    positive dimensions and quantities, and basis-point bounds
    (`ERR_INVALID_REQUEST`, 422)"

    Design: Corner/entities/create_spec_missing_required_field_returns_invalid_request
    """
    shop, material, customer = setup_base_shop()
    project = create_project(shop["id"], customer["id"], title="P")
    # Omit width_mm.
    resp = api.create_spec(
        shop["id"], project["id"],
        {"label": "B", "height_mm": 720, "depth_mm": 560, "quantity": 4,
         "base_unit_price_cents": 100000, "material_id": material["id"]},
        DESIGNER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_project_default_margin_policy_standard(api):
    """PRD §3.2: "an optional `is_rush` flag (default false), an optional
    `install_address`, and an optional `margin_policy` of either `STANDARD` or
    `PREMIUM` (default `STANDARD`)."

    Design: Corner/entities/create_project_default_margin_policy_standard
    """
    shop = create_shop()
    customer = create_customer(shop["id"])
    data = validate_success(api.create_project(shop["id"], customer["id"], {"title": "P"}, DESIGNER), 201)
    assert data["margin_policy"] == "STANDARD", f"margin_policy default expected STANDARD, got {data['margin_policy']}"
    assert data["is_rush"] is False, f"is_rush default expected False, got {data['is_rush']}"


def test_spec_panel_area_computed(api):
    """PRD §3.3: "On creation the system computes the spec's `panel_area_mm2`, the
    total flat-panel area of one cabinet, as two times the product of width and
    height, plus two times the product of height and depth, plus one times the
    product of width and depth."

    Design: Corner/entities/spec_panel_area_computed_input_ignored
    """
    shop, material, customer = setup_base_shop()
    project = create_project(shop["id"], customer["id"], title="P")
    # 600x720x560 -> 2*(600*720) + 2*(720*560) + (600*560) = 864000 + 806400 + 336000 = 2006400.
    data = validate_success(api.create_spec(
        shop["id"], project["id"],
        {"label": "B", "width_mm": 600, "height_mm": 720, "depth_mm": 560, "quantity": 1,
         "base_unit_price_cents": 100000, "material_id": material["id"]},
        DESIGNER,
    ), 201)
    assert data["panel_area_mm2"] == 2006400, f"panel_area_mm2 expected 2006400, got {data['panel_area_mm2']}"


def test_shop_system_fields_generated(api):
    """PRD §2.4: "Every entity in the system carries a server-minted `id`,
    formatted as a UUID with no type prefix"
    PRD §2.4: "a `version`, an integer that starts at the resource's creation value
    and increments by one on every mutation of that resource."
    PRD §3.1: "A shop also carries `current_utc`, a test clock that begins null and
    is set only through the administrative clock endpoint"

    Design: Corner/entities/shop_system_fields_generated
    """
    data = validate_success(api.create_shop({"name": "Sys"}, ADMIN), 201)
    assert data["version"] == 1, f"new shop version expected 1, got {data['version']}"
    assert data["current_utc"] is None, f"current_utc expected null until clock set, got {data['current_utc']!r}"
    assert is_valid_uuid(data["id"]), f"id must be a UUID with no type prefix, got {data['id']!r}"


def test_create_spec_invalid_enum_finish_rejected(api):
    """PRD §3.5: "Each `FinishSelection` carries a `finish_code` of `RAW`, `STAIN`,
    `PAINT`, or `LACQUER`"
    PRD §4: "then request-body validity such as required fields, enum ranges,
    positive dimensions and quantities, and basis-point bounds
    (`ERR_INVALID_REQUEST`, 422)"

    Design: Corner/entities/create_spec_invalid_enum_finish_rejected
    """
    shop = create_shop()
    customer = create_customer(shop["id"])
    project = create_project(shop["id"], customer["id"], title="P")
    resp = api.create_finish_selection(shop["id"], project["id"], {"finish_code": "GLITTER"}, DESIGNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_customer_lifetime_paid_computed_from_paid_draws(api):
    """PRD §2.10: "The customer-level `lifetime_paid_cents` aggregates
    `amount_cents` across all `PAID` draws on all of that customer's projects."
    PRD §3.8: "adds its `amount_cents` to both the project's `paid_to_date_cents`
    and the customer's `lifetime_paid_cents`."

    Design: Corner/entities/customer_lifetime_paid_computed_from_paid_draws
    """
    # tax0 STAIN qty2 -> contract_total 291600, deposit 87480.
    ctx = setup_contracted_project(specs=[{"quantity": 2}], finish_code="STAIN")
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    dep_id = ctx["deposit_draw"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])
    get_success_data(api.issue_draw(shop_id, proj_id, dep_id, MANAGER))
    get_success_data(api.pay_draw(shop_id, proj_id, dep_id, cust))

    customer = get_success_data(api.get_customer(shop_id, ctx["customer"]["id"], MANAGER))
    assert customer["lifetime_paid_cents"] == 87480, (
        f"lifetime_paid_cents expected 87480 after paying the deposit, got {customer['lifetime_paid_cents']}"
    )
    project = get_success_data(api.get_project(shop_id, proj_id, MANAGER))
    assert project["paid_to_date_cents"] == 87480, (
        f"paid_to_date_cents expected 87480, got {project['paid_to_date_cents']}"
    )


def test_spec_add_after_lock_rejected(api):
    """PRD §3.3: "a spec may be added or deleted only while `OPEN`, and any attempt
    to add or delete a spec after the specs have been locked (which happens at
    contract acceptance, described in §3.4) is rejected with `ERR_SPECS_LOCKED`."

    Design: Corner/entities/spec_add_after_lock_rejected
    """
    # Contracted project -> specs LOCKED.
    ctx = setup_contracted_project(specs=[{"quantity": 4}], finish_code="PAINT")
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    mat_id = ctx["material"]["id"]
    resp = api.create_spec(
        shop_id, proj_id,
        {"label": "X", "width_mm": 600, "height_mm": 720, "depth_mm": 560, "quantity": 1,
         "base_unit_price_cents": 100000, "material_id": mat_id},
        DESIGNER,
    )
    validate_error(resp, ApiErrorId.ERR_SPECS_LOCKED.value)


# ===========================================================================
# Corner / state_machines
# ===========================================================================
def test_contract_from_draft_returns_invalid_state(api):
    """PRD §4: "then that the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`, 409)"
    PRD §3.5: "Contract acceptance is performed by the owning `Customer` on a
    `QUOTED` project and is the system's pivotal commitment."

    Design: Corner/state_machines/contract_from_draft_returns_invalid_state
    """
    shop = create_shop()
    customer = create_customer(shop["id"])
    project = create_project(shop["id"], customer["id"], title="P")
    pv = get_success_data(api.get_project(shop["id"], project["id"], MANAGER))["version"]
    cust = make_customer_headers(customer["id"])
    resp = api.contract_project(shop["id"], project["id"], {"expected_project_version": pv}, cust)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_new_project_initial_state_draft(api):
    """PRD §3.2: "A freshly created project begins in `DRAFT` status with all of its
    ledger fields"
    PRD §2.4: "a `version`, an integer that starts at the resource's creation value
    and increments by one on every mutation of that resource."

    Design: Corner/state_machines/new_project_initial_state_draft
    """
    shop = create_shop()
    customer = create_customer(shop["id"])
    data = validate_success(api.create_project(shop["id"], customer["id"], {"title": "P"}, DESIGNER), 201)
    assert data["status"] == "DRAFT", f"new project status expected DRAFT, got {data['status']}"
    assert data["version"] == 1, f"new project version expected 1, got {data['version']}"


def test_terminal_cancelled_project_rejects_further_transitions(api):
    """PRD §3.2: "`CLOSED` and `CANCELLED` are terminal."
    PRD §4: "then that the target resource is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`, 409)"

    Design: Corner/state_machines/terminal_cancelled_project_rejects_further_transitions
    """
    shop, material, customer = setup_base_shop()
    project = create_project(shop["id"], customer["id"], title="P")
    add_spec(shop["id"], project["id"], material["id"], quantity=1, base_unit_price_cents=100000)
    get_success_data(api.cancel_project(shop["id"], project["id"], MANAGER))
    resp = api.measure_project(shop["id"], project["id"], DESIGNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_pay_draw_twice_second_returns_invalid_state(api):
    """PRD §3.8: "a `status` of `PENDING`, `ISSUED`, `PAID`, or `VOIDED`, where
    `PAID` and `VOIDED` are terminal."
    PRD §4: "then that the target resource is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`, 409)"

    Design: Corner/state_machines/pay_draw_twice_second_returns_invalid_state
    """
    # tax0 STAIN qty2 -> deposit 87480; issue and pay once.
    ctx = setup_contracted_project(specs=[{"quantity": 2}], finish_code="STAIN")
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    dep_id = ctx["deposit_draw"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])
    get_success_data(api.issue_draw(shop_id, proj_id, dep_id, MANAGER))
    get_success_data(api.pay_draw(shop_id, proj_id, dep_id, cust))

    resp = api.pay_draw(shop_id, proj_id, dep_id, cust)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    project = get_success_data(api.get_project(shop_id, proj_id, MANAGER))
    assert project["paid_to_date_cents"] == 87480, (
        f"paid_to_date_cents must not double-count a rejected second pay, expected 87480, "
        f"got {project['paid_to_date_cents']}"
    )


def test_install_complete_with_major_punch_open_blocked(api):
    """PRD §3.9: "Completing an installation moves it from `PUNCH_PENDING` to
    `COMPLETE` and requires that no punch item on it has `severity` of `MAJOR` and
    `status` of `OPEN` — an open major defect blocks completion and is rejected
    with `ERR_MAJOR_PUNCH_OPEN`."

    Design: Corner/state_machines/install_complete_with_major_punch_open_blocked
    """
    ctx = setup_installation_punch_pending(
        specs=[{"quantity": 4}], finish_code="PAINT",
        shop_overrides={"tax_rate_bps": 0, "deposit_pct_bps": 3000, "max_installs_per_day": 2},
        build_start="2026-07-20T09:00:00Z", build_end="2026-07-20T12:00:00Z",
        install_date="2026-09-10", window_start="2026-09-10T08:00:00Z", window_end="2026-09-10T12:00:00Z",
    )
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    inst_id = ctx["installation"]["id"]
    add_punch_item(shop_id, proj_id, inst_id, description="door misaligned", severity="MAJOR")

    resp = api.complete_installation(shop_id, proj_id, inst_id, INSTALLER)
    validate_error(resp, ApiErrorId.ERR_MAJOR_PUNCH_OPEN.value)


def test_install_reopen_loop_returns_to_in_progress(api):
    """PRD §3.9: "If instead the crew needs to redo work, a `PUNCH_PENDING`
    installation may be reopened back to `IN_PROGRESS`, which requires that at least
    one punch item is still `OPEN` (otherwise `ERR_NOTHING_TO_REOPEN`); this forms
    the punch reopen loop in which an installation cycles `PUNCH_PENDING`,
    `IN_PROGRESS`, and back to `PUNCH_PENDING`."

    Design: Corner/state_machines/install_reopen_loop_returns_to_in_progress
    """
    ctx = setup_installation_punch_pending(
        specs=[{"quantity": 4}], finish_code="PAINT",
        shop_overrides={"tax_rate_bps": 0, "deposit_pct_bps": 3000, "max_installs_per_day": 2},
        build_start="2026-07-21T09:00:00Z", build_end="2026-07-21T12:00:00Z",
        install_date="2026-09-11", window_start="2026-09-11T08:00:00Z", window_end="2026-09-11T12:00:00Z",
    )
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    inst_id = ctx["installation"]["id"]
    add_punch_item(shop_id, proj_id, inst_id, description="scratch", severity="MINOR")

    reopened = validate_success(api.reopen_installation(shop_id, proj_id, inst_id, INSTALLER))
    assert reopened["status"] == "IN_PROGRESS", f"after reopen expected IN_PROGRESS, got {reopened['status']}"


def test_mark_ready_with_incomplete_build_job_blocked(api):
    """PRD §3.9: "Marking ready advances the project from `IN_PRODUCTION` to
    `READY_FOR_DELIVERY` and requires that every build job on the project is
    `COMPLETE` (otherwise `ERR_BUILD_INCOMPLETE`)"

    Design: Corner/state_machines/mark_ready_with_incomplete_build_job_blocked
    """
    from test_helpers import setup_in_production_project
    # IN_PRODUCTION with one SCHEDULED (never completed) build job.
    ctx = setup_in_production_project(
        specs=[{"quantity": 4}], finish_code="PAINT",
        build_start="2026-07-22T09:00:00Z", build_end="2026-07-22T12:00:00Z",
    )
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    resp = api.mark_ready(shop_id, proj_id, MANAGER)
    validate_error(resp, ApiErrorId.ERR_BUILD_INCOMPLETE.value)


def test_install_complete_bubbles_project_to_installed_and_creates_retainage(api):
    """PRD §3.9: "When an installation reaches `COMPLETE`, it bubbles up to the
    project: the system drives the project from `READY_FOR_DELIVERY` to `INSTALLED`
    and creates one `RETAINAGE` draw in `PENDING` status as the first hop of the
    install chain."
    PRD §3.8: "for a `RETAINAGE` draw it is the contract total multiplied by the
    shop's `retainage_pct_bps`, divided by 10000 and rounded half up. The draw's
    `amount_cents` is then the lesser of that raw amount and the remaining
    billable"

    Design: Corner/state_machines/install_complete_bubbles_project_to_installed_and_creates_retainage
    """
    # tax800 PAINT qty4 -> contract_total 628992; retainage 10% raw = 62899 (< remaining billable).
    ctx = setup_installation_punch_pending(
        specs=[{"quantity": 4}], finish_code="PAINT",
        shop_overrides={"tax_rate_bps": 800, "deposit_pct_bps": 3000, "retainage_pct_bps": 1000, "max_installs_per_day": 2},
        build_start="2026-07-23T09:00:00Z", build_end="2026-07-23T12:00:00Z",
        install_date="2026-09-12", window_start="2026-09-12T08:00:00Z", window_end="2026-09-12T12:00:00Z",
    )
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    inst_id = ctx["installation"]["id"]

    completed = validate_success(api.complete_installation(shop_id, proj_id, inst_id, INSTALLER))
    assert completed["status"] == "COMPLETE", f"installation expected COMPLETE, got {completed['status']}"

    project = get_success_data(api.get_project(shop_id, proj_id, MANAGER))
    assert project["status"] == "INSTALLED", f"project expected INSTALLED after bubble, got {project['status']}"

    draws = api.list_draws(shop_id, proj_id, MANAGER).json()["data"]
    retainage = [d for d in draws if d["draw_type"] == "RETAINAGE" and d["status"] == "PENDING" and d["amount_cents"] == 62899]
    assert len(retainage) == 1, (
        f"expected exactly one PENDING RETAINAGE draw of 62899, got "
        f"{[(d['draw_type'], d['status'], d['amount_cents']) for d in draws]}"
    )
