"""Standing a job up: parties, contract terms, the opening ledger and breaking ground."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_allowance_item,
    assert_money_equals,
    assert_project,
    assert_project_ledger_invariants,
    assert_subcontractor,
    assert_version_incremented,
    create_allowance_item_payload,
    create_client,
    create_defect_ticket_payload,
    create_project_payload,
    create_staff_member,
    create_subcontractor_payload,
    make_project_manager_headers,
    read_project,
    setup_job,
    setup_submitted_change_order,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_new_project_opens_in_planning_with_a_zeroed_ledger(api):
    """PRD §3.1: "A newly opened project sits in `PLANNING`, with `contract_sum_current`
    initialised to `base_contract_amount` and `budget_posture` initialised to
    `WITHIN_BUDGET`; its `approved_change_order_total`, `allowance_variance_total`,
    `cost_to_date`, `eligible_cost_pool`, `pending_draw_amount`, `funded_to_date`, and
    `retainage_held` all start at zero, and `construction_started_at`,
    `substantial_completion_at`, `final_accepted_at`, `warranty_starts_at`, and
    `warranty_expires_at` all start null."
    PRD §2.4: "`id` is a server-minted UUID with no type prefix of any kind; clients never
    supply it."
    PRD §2.4: "`version` is an integer that begins at 1 when the row is first written and
    increases by one on every mutation of that row."

    Design: Corner/entities/create_project_returns_201_with_computed_ledger_defaults
    """
    client = create_client()

    response = api.create_project(
        create_project_payload(client["id"], base_contract_amount=900000.00), ADMIN
    )
    project = validate_success(response, 201)

    assert_project(project)
    assert project["status"] == "PLANNING"
    assert project["budget_posture"] == "WITHIN_BUDGET"
    assert_money_equals(project["contract_sum_current"], 900000.00, "contract_sum_current")
    assert_money_equals(
        project["approved_change_order_total"], 0.00, "approved_change_order_total"
    )
    assert_money_equals(project["allowance_variance_total"], 0.00, "allowance_variance_total")
    assert_money_equals(project["cost_to_date"], 0.00, "cost_to_date")
    assert_money_equals(project["eligible_cost_pool"], 0.00, "eligible_cost_pool")
    assert_money_equals(project["pending_draw_amount"], 0.00, "pending_draw_amount")
    assert_money_equals(project["funded_to_date"], 0.00, "funded_to_date")
    assert_money_equals(project["retainage_held"], 0.00, "retainage_held")
    assert project["version"] == 1
    assert project["construction_started_at"] is None
    assert project["substantial_completion_at"] is None
    assert project["final_accepted_at"] is None
    assert project["warranty_starts_at"] is None
    assert project["warranty_expires_at"] is None


def test_server_owned_project_fields_cannot_be_supplied_at_creation(api):
    """PRD §3.1: "A newly opened project sits in `PLANNING`, with `contract_sum_current`
    initialised to `base_contract_amount` and `budget_posture` initialised to
    `WITHIN_BUDGET`"
    PRD §2.4: "`version` is an integer that begins at 1 when the row is first written and
    increases by one on every mutation of that row."

    Design: Corner/entities/create_project_with_client_supplied_status_and_version_input_ignored
    """
    client = create_client()

    payload = create_project_payload(client["id"], base_contract_amount=900000.00)
    payload["status"] = "FINAL_ACCEPTED"
    payload["version"] = 77
    payload["contract_sum_current"] = 1.00

    project = validate_success(api.create_project(payload, ADMIN), 201)

    assert project["status"] == "PLANNING", "status is server-owned"
    assert project["version"] == 1, "version is server-owned and begins at 1"
    assert_money_equals(project["contract_sum_current"], 900000.00, "contract_sum_current")


def test_cost_plus_project_without_a_builder_fee_is_refused(api):
    """PRD §3.1: "Coherence between these terms is checked at creation and nowhere else: a
    `COST_PLUS` project submitted without a `builder_fee_pct`, or any project whose
    `gmp_cap` sits below its `base_contract_amount`, is refused with
    `ERR_CONTRACT_TERMS_INVALID`."
    PRD §3.1: "A `FIXED_PRICE` project may omit `builder_fee_pct` entirely — the field is
    simply ignored for that accounting basis."

    Design: Corner/validations/cost_plus_project_without_builder_fee_returns_contract_terms_invalid
    """
    client = create_client()

    fixed_price = validate_success(
        api.create_project(
            create_project_payload(
                client["id"], address="18 Kestrel Ridge", contract_type="FIXED_PRICE"
            ),
            ADMIN,
        ),
        201,
    )
    assert fixed_price.get("builder_fee_pct") is None

    response = api.create_project(
        create_project_payload(
            client["id"], address="22 Kestrel Ridge", contract_type="COST_PLUS"
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_TERMS_INVALID, 422)

    rows, meta = validate_paginated(
        api.list_projects(ADMIN, params={"client_id": client["id"]})
    )
    assert meta["total_count"] == 1, "the refused cost-plus project must not be stored"


def test_reading_an_unknown_project_returns_project_not_found(api):
    """PRD §2.9: "Resources addressed through a nested path are resolved from left to
    right, and the first segment that names a row which does not exist decides the
    rejection. Each resource family has its own not-found code: `ERR_PROJECT_NOT_FOUND`,
    `ERR_ALLOWANCE_ITEM_NOT_FOUND`, `ERR_SELECTION_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`,
    `ERR_SCHEDULE_TASK_NOT_FOUND`, `ERR_COST_ENTRY_NOT_FOUND`, `ERR_DRAW_REQUEST_NOT_FOUND`,
    `ERR_LIEN_WAIVER_NOT_FOUND`, `ERR_DEFECT_TICKET_NOT_FOUND`, and `ERR_PHOTO_NOT_FOUND`,
    each returned with HTTP 404."

    Design: Corner/entities/get_project_with_unknown_id_returns_project_not_found
    """
    client = create_client()
    validate_success(api.create_project(create_project_payload(client["id"]), ADMIN), 201)

    response = api.get_project(NON_EXISTENT_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FOUND, 404)


def test_project_list_pages_with_total_count_and_has_more(api):
    """PRD §2.3: "`limit` controls how many rows come back; it defaults to 10, may not be
    smaller than 1, and may not be larger than 100. `offset` controls how many rows are
    skipped before the page begins; it defaults to 0 and may not be negative."
    PRD §2.3: "List responses report their paging state in the `meta` object, which carries
    `limit`, `offset`, `total_count`, and `has_more`. `total_count` is the number of rows
    matching the filters before paging is applied, and `has_more` is true exactly when rows
    remain beyond the current page."

    Design: Corner/entities/list_projects_paginates_with_total_count_and_has_more
    """
    client = create_client()
    for address, terms in (
        ("18 Kestrel Ridge", {"contract_type": "FIXED_PRICE", "base_contract_amount": 900000.00}),
        ("24 Kestrel Ridge", {"contract_type": "FIXED_PRICE", "base_contract_amount": 700000.00}),
        (
            "31 Kestrel Ridge",
            {
                "contract_type": "COST_PLUS",
                "base_contract_amount": 600000.00,
                "builder_fee_pct": 0.15,
            },
        ),
    ):
        validate_success(
            api.create_project(
                create_project_payload(client["id"], address=address, **terms), ADMIN
            ),
            201,
        )

    first_page = api.list_projects(
        ADMIN, params={"client_id": client["id"], "limit": 2, "offset": 0}
    )
    rows, meta = validate_paginated(first_page)
    assert len(rows) == 2, f"Expected 2 rows on the first page, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert first_page.json()["response_type"] == "array"

    second_page = api.list_projects(
        ADMIN, params={"client_id": client["id"], "limit": 2, "offset": 2}
    )
    rows, meta = validate_paginated(second_page)
    assert len(rows) == 1, f"Expected 1 row on the second page, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert second_page.json()["response_type"] == "array"


def test_subcontractor_waiver_required_defaults_to_true(api):
    """PRD §3.1: "A trade contractor record carries its `company_name`, its `trade` — one of
    `SITEWORK`, `CONCRETE`, `FRAMING`, `PLUMBING`, `ELECTRICAL`, `HVAC`, `DRYWALL`,
    `FINISH_CARPENTRY`, `PAINT`, or `LANDSCAPE` — a `lead_time_days` count of whole days it
    needs between mobilization notice and its first day on site (zero is permitted), a
    `crew_capacity` of at least 1 describing how many schedule intervals its crews can
    occupy simultaneously, and a `waiver_required` flag defaulting to true that determines
    whether draws containing this trade's costs generate lien-waiver paperwork."

    Design: Corner/entities/create_subcontractor_omitting_waiver_required_applies_default_true
    """
    payload = create_subcontractor_payload(
        company_name="Ridgeline Framing", trade="FRAMING", lead_time_days=5, crew_capacity=1
    )
    del payload["waiver_required"]

    subcontractor = validate_success(api.create_subcontractor(payload, ADMIN), 201)

    assert_subcontractor(subcontractor)
    assert subcontractor["waiver_required"] is True
    assert subcontractor["crew_capacity"] == 1


def test_allowance_item_without_an_allowance_amount_is_rejected(api):
    """PRD §2.10: "**Request body well-formed.** Every required field must be present, every
    enum-typed value must be a declared member of its enumeration, every money field must be
    non-negative with at most two decimals, a schedule task's `planned_finish` must be
    strictly later than its `planned_start`, a draw's `period_end` must be strictly later
    than its `period_start`, `limit` must fall within 1 through 100, and `offset` must not be
    negative. Any breach is `ERR_INVALID_REQUEST` (400)."
    PRD §3.2: "A `ProjectManager` adds one to a project by naming the `project_id`, the
    `category` — one of `FLOORING`, `CABINETRY`, `APPLIANCES`, `PLUMBING_FIXTURES`,
    `LIGHTING`, `COUNTERTOPS`, or `LANDSCAPE` — the `allowance_amount` carried in the
    contract, which must be strictly greater than zero with at most two decimals, and a
    `selection_deadline` giving the last logical-clock instant at which the homeowner may
    still propose against the line."

    Design: Corner/entities/create_allowance_item_without_allowance_amount_returns_invalid_request
    """
    ctx = setup_job(start_construction=False, create_allowance=False, create_task=False)

    payload = create_allowance_item_payload(ctx["project"]["id"], category="FLOORING")
    del payload["allowance_amount"]

    response = api.create_allowance_item(payload, ctx["pm_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_allowance_items(ADMIN, params={"project_id": ctx["project"]["id"]})
    )
    assert meta["total_count"] == 0, "no allowance line may be stored by a refused request"


def test_allowance_item_under_an_unknown_project_is_rejected(api):
    """PRD §2.9: "A reference to a homeowner that does not resolve yields
    `ERR_CLIENT_NOT_FOUND`; a lender reference yields `ERR_LENDER_NOT_FOUND`; a staff
    reference yields `ERR_STAFF_NOT_FOUND`; a trade reference yields
    `ERR_SUBCONTRACTOR_NOT_FOUND`; and project, allowance-item, and schedule-task references
    reuse `ERR_PROJECT_NOT_FOUND`, `ERR_ALLOWANCE_ITEM_NOT_FOUND`, and
    `ERR_SCHEDULE_TASK_NOT_FOUND` respectively."
    PRD §2.10: "**Body references resolve.** Every foreign key supplied in the body must name
    an existing row, or the matching 404 from §2.9."

    Design: Corner/entities/create_allowance_item_under_unknown_project_returns_project_not_found
    """
    pm = create_staff_member("Pat Morgan", "PROJECT_MANAGER")

    response = api.create_allowance_item(
        create_allowance_item_payload(NON_EXISTENT_UUID),
        make_project_manager_headers(pm["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FOUND, 404)


def test_defect_ticket_with_an_undeclared_severity_is_rejected(api):
    """PRD §2.10: "**Request body well-formed.** Every required field must be present, every
    enum-typed value must be a declared member of its enumeration"
    PRD §3.9: "Either a `Client` or a `ProjectManager` may open one, naming the `project_id`,
    the `phase`, the `room` where the defect is, a narrative `description`, a `severity` of
    `COSMETIC`, `FUNCTIONAL`, or `LIFE_SAFETY`, a `category` classifying the cause as
    `WORKMANSHIP`, `MATERIAL_DEFECT`, `SYSTEMS`, `HOMEOWNER_DAMAGE`, or `NORMAL_WEAR`, and
    optionally a `source_schedule_task_id` naming the activity that produced the defect."

    Design: Corner/entities/create_defect_ticket_with_unknown_severity_returns_invalid_enum
    """
    ctx = setup_job(start_construction=False, create_allowance=False, create_task=False)

    response = api.create_defect_ticket(
        create_defect_ticket_payload(
            ctx["project"]["id"],
            phase="PUNCH",
            room="Foyer",
            description="Scuffed trim",
            severity="URGENT",
            category="WORKMANSHIP",
        ),
        ctx["pm_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_defect_tickets(ADMIN, params={"project_id": ctx["project"]["id"]})
    )
    assert meta["total_count"] == 0, "no ticket may be stored by a refused request"


def test_start_construction_without_a_schedule_task_is_refused(api):
    """PRD §3.1: "Breaking ground — `START_CONSTRUCTION` — moves a project `PLANNING →
    UNDER_CONSTRUCTION`, and it is only permitted once the job actually has a book and a
    schedule: at least one allowance item must exist on the project and at least one schedule
    task on the project must sit in `PLANNED`. A project missing either is refused with
    `ERR_PROJECT_NOT_READY_TO_START`."
    PRD §3.1: "On success the logical clock now is written into `construction_started_at`,
    `contract_sum_current` and `budget_posture` are recomputed, and the project's `version`
    is incremented by one."

    Design: Corner/state_machines/start_construction_without_any_schedule_task_is_rejected
    """
    ctx = setup_job(start_construction=False, create_task=False)
    assert_allowance_item(ctx["allowance_item"])

    response = api.advance_project(
        ctx["project"]["id"], {"action": "START_CONSTRUCTION"}, ctx["pm_headers"]
    )
    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_READY_TO_START, 409)

    project = read_project(ctx["project"]["id"])
    assert project["status"] == "PLANNING"
    assert project["construction_started_at"] is None


def test_declaring_substantial_completion_with_a_planned_task_is_refused(api):
    """PRD §3.1: "Every schedule task on the project must be `COMPLETE`, and no change order
    on the project may remain in `DRAFT`, `PRICED`, `SUBMITTED`, or `REVISION_REQUESTED`.
    These two checks are ordered: the incomplete-task check runs first and yields
    `ERR_PROJECT_TASKS_INCOMPLETE`, and only a project whose tasks are all complete can go on
    to earn `ERR_CHANGE_ORDER_PENDING` for an in-flight change order."

    Design: Corner/state_machines/declare_substantial_completion_with_planned_task_is_rejected
    """
    ctx = setup_job()

    response = api.advance_project(
        ctx["project"]["id"],
        {"action": "DECLARE_SUBSTANTIAL_COMPLETION"},
        ctx["pm_headers"],
    )
    validate_error(response, ApiErrorId.ERR_PROJECT_TASKS_INCOMPLETE, 409)

    project = read_project(ctx["project"]["id"])
    assert project["status"] == "UNDER_CONSTRUCTION"
    assert project["substantial_completion_at"] is None
    assert project["warranty_expires_at"] is None


def test_project_version_climbs_with_every_ledger_mutation(api):
    """PRD §2.4: "`version` is an integer that begins at 1 when the row is first written and
    increases by one on every mutation of that row."
    PRD §3.1: "On success the logical clock now is written into `construction_started_at`,
    `contract_sum_current` and `budget_posture` are recomputed, and the project's `version`
    is incremented by one."
    PRD §3.3: "**Approval** advances `SUBMITTED → APPROVED`, requires the project to be
    `UNDER_CONSTRUCTION`, stamps `decided_at`, and sets off a four-link cascade: the change
    order's `priced_amount` joins `approved_change_order_total`, which forces
    `contract_sum_current` to be recomputed; because `contract_sum_current` moved,
    `budget_posture` is re-evaluated and may become `OVER_GMP`; because the posture became
    `OVER_GMP`, every allowance item on the project currently in `OPEN` cascades `OPEN →
    FROZEN`; and the project's `version` is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/project_version_increments_on_each_ledger_mutation
    """
    ctx = setup_job(start_construction=False)
    version_at_create = ctx["project"]["version"]
    assert version_at_create == 1

    started = api.advance_project(
        ctx["project"]["id"], {"action": "START_CONSTRUCTION"}, ctx["pm_headers"]
    )
    version_after_start = validate_success(started, 200)["version"]
    assert_version_incremented(version_after_start, version_at_create)

    ctx["project"] = read_project(ctx["project"]["id"])
    change_order = setup_submitted_change_order(
        ctx, direct_cost=3000.00, schedule_impact_days=0, scope_description="Add a wine room"
    )

    approved = validate_success(
        api.decide_change_order(
            change_order["id"], {"decision": "APPROVE"}, ctx["client_headers"]
        ),
        200,
    )
    assert approved["status"] == "APPROVED"

    project = read_project(ctx["project"]["id"])
    assert_version_incremented(project["version"], version_after_start)
    assert_money_equals(project["contract_sum_current"], 903600.00, "contract_sum_current")
    assert_money_equals(
        project["approved_change_order_total"], 3600.00, "approved_change_order_total"
    )
    assert_project_ledger_invariants(project)
