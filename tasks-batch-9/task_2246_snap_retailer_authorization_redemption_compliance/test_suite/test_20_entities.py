"""Entity creation, retrieval, defaults, computed fields and parent references."""
from test_helpers import (
    ADMIN,
    ANALYST,
    ANON,
    INV_PASS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    application_payload,
    assert_common_fields,
    assert_depot_conservation,
    assert_fields,
    assert_instant,
    assert_ledger_conservation,
    assert_no_rows,
    assert_owner_shape,
    assert_penalty_ledger_entry_shape,
    assert_row_count,
    assert_store_shape,
    authorized_store,
    cmp_payment_payload,
    create_application,
    create_depot,
    create_inspector,
    create_owner,
    create_store,
    create_terminal,
    created,
    data_ids,
    deployment_payload,
    elect_cmp,
    file_reply,
    four_closed_periods,
    issue_charge_letter,
    issue_determination,
    ledger_entries,
    open_case,
    owner_payload,
    owner_headers,
    refresh_case,
    refresh_depot,
    refresh_inspector,
    refresh_owner,
    refresh_store,
    store_payload,
    store_visit_payload,
    submit_application,
    substantiated_ineligible_investigation,
    terminal_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

BARE_STORE = {
    "store_name": "Rio Bare Defaults",
    "store_type": "GROCERY",
    "checkout_lane_count": 3,
    "staple_shelf_linear_feet": 60,
    "annual_gross_sales_cents": 36000000,
    "annual_staple_sales_cents": 20000000,
    "max_terminal_slots": 2,
    "tax_rate_bps": None,
    "hardship_designated": None,
}


def test_owner_registration_returns_201_with_the_declared_rollup_defaults():
    """Registering the first owner in an empty database returns 201 with the four
    rollup fields on their declared starting values.

    The specification fixes the opening position: "A freshly registered owner starts
    with `permanent_disqualification_count` at 0, `cmp_outstanding_cents` at 0,
    `sanction_flag` at `CLEAR` and `status` at `ACTIVE`." Registration is also the
    one call an anonymous caller may make.

    Design: Corner/entities/owner_creation_from_empty_db_returns_201_with_system_and_computed_defaults
    """
    response = api_client.create_owner(
        owner_payload(legal_name="Rio Retail LLC", ownership_type="LLC", tax_id_last4="4417"),
        ANON,
    )

    owner = validate_success(response, 201)
    assert_owner_shape(owner)
    assert_fields(
        owner,
        {
            "legal_name": "Rio Retail LLC",
            "ownership_type": "LLC",
            "tax_id_last4": "4417",
            "permanent_disqualification_count": 0,
            "cmp_outstanding_cents": 0,
            "sanction_flag": "CLEAR",
            "status": "ACTIVE",
            "version": 1,
        },
        "registered owner",
    )


def test_store_creation_omitting_the_three_optional_inputs_applies_the_declared_defaults():
    """A registration that supplies only the required profile lands on 0, false and
    null for the optional inputs and on the declared initial system values.

    The specification names all three defaults: "`tax_rate_bps`, the state and
    local sales tax in basis points, which defaults to 0 and may not exceed 2000;
    `hardship_designated`, which defaults to false ...; and `predecessor_store_id`,
    supplied only when this record succeeds an existing store after a change of
    ownership and left null otherwise." It then fixes the rest: "A new store lands
    with `authorization_status` at `NOT_AUTHORIZED`, `sanction_status` at `NONE`,
    `redemption_flag_level` at `FLAG_L0`, `active_terminal_count` at 0, and with
    `fns_number`, `authorized_at`, `disqualified_until` all null and
    `permanently_disqualified` false."

    Design: Corner/entities/store_creation_omitting_optional_inputs_applies_declared_defaults
    """
    owner = create_owner()

    store = created(
        api_client.create_store(store_payload(owner["id"], **BARE_STORE), ADMIN)
    )

    assert_store_shape(store)
    assert_fields(
        store,
        {
            "tax_rate_bps": 0,
            "hardship_designated": False,
            "predecessor_store_id": None,
            "authorization_status": "NOT_AUTHORIZED",
            "sanction_status": "NONE",
            "redemption_flag_level": "FLAG_L0",
            "active_terminal_count": 0,
            "fns_number": None,
            "authorized_at": None,
            "disqualified_until": None,
            "permanently_disqualified": False,
        },
        "bare store",
    )


def test_store_retrieval_echoes_the_stored_row_without_bumping_its_version():
    """A read returns every stored input plus the derived staple share, and leaves
    `version` where the creation left it.

    The specification reserves version movement for mutations: "`version` is an
    integer that begins at 1 on creation and increments by exactly 1 on every
    mutation of the row", so a retrieval cannot move it. The derived share of
    20,000,000c against 36,000,000c floors to 5,555 basis points, which clears the
    strictly-greater comparison against 5,000.

    Design: Corner/entities/store_retrieval_by_id_returns_the_stored_row
    """
    owner = create_owner()
    store = create_store(owner)

    read = validate_success(api_client.get_store(store["id"], ANALYST), 200)

    assert_fields(
        read,
        {
            "id": store["id"],
            "store_name": "Rio Convenience",
            "state_code": "TX",
            "store_type": "CONVENIENCE",
            "tax_rate_bps": 825,
            "hardship_designated": True,
            "staple_sales_bps": 5555,
            "criterion_b_pass": True,
            "version": store["version"],
        },
        "retrieved store",
    )


def test_store_listing_filters_by_owner_and_reports_the_envelope_counts():
    """Two pages of two and one row carry the same `total_count` of three, and the
    other owner's store appears on neither page.

    The specification defines the counters: "For list responses the `meta` object
    carries `limit` and `offset` as they were applied, `total_count` as the number
    of rows matching the filter before pagination, and `has_more` as a boolean that
    is true exactly when `offset` plus the number of returned rows is less than
    `total_count`." Filtering stores by `owner_id` is one of the declared filters.

    Design: Corner/entities/stores_listing_filters_by_owner_and_paginates_with_envelope_counts
    """
    owner = create_owner()
    mine = [
        create_store(owner)["id"],
        create_store(
            owner,
            store_name="Rio Corner Market",
            checkout_lane_count=1,
            annual_gross_sales_cents=24000000,
            annual_staple_sales_cents=14000000,
            max_terminal_slots=1,
            tax_rate_bps=None,
            hardship_designated=None,
        )["id"],
        create_store(
            owner,
            store_name="Rio Depot Grocery",
            store_type="GROCERY",
            checkout_lane_count=4,
            staple_shelf_linear_feet=80,
            annual_gross_sales_cents=90000000,
            annual_staple_sales_cents=50000000,
            max_terminal_slots=3,
            tax_rate_bps=None,
            hardship_designated=None,
        )["id"],
    ]
    other_owner = create_owner(
        legal_name="Second Street Foods Inc",
        ownership_type="CORPORATION",
        tax_id_last4="9032",
    )
    other_store = create_store(other_owner, store_name="Second Street Market")

    first = api_client.list_stores(ADMIN, {"owner_id": owner["id"], "limit": 2, "offset": 0})
    second = api_client.list_stores(ADMIN, {"owner_id": owner["id"], "limit": 2, "offset": 2})

    page1, meta1 = validate_paginated(first)
    assert_fields(
        meta1, {"total_count": 3, "limit": 2, "offset": 0, "has_more": True}, "first page meta"
    )
    assert len(page1) == 2, f"expected 2 rows on the first page, got {len(page1)}"
    page2, meta2 = validate_paginated(second)
    assert_fields(
        meta2, {"total_count": 3, "offset": 2, "has_more": False}, "second page meta"
    )
    assert len(page2) == 1, f"expected 1 row on the second page, got {len(page2)}"
    listed = data_ids(first) + data_ids(second)
    assert sorted(listed) == sorted(mine), f"filtered listing returned {listed}"
    assert other_store["id"] not in listed


def test_store_read_with_an_unused_uuid_reports_store_not_found():
    """A well-formed identifier that names no row answers 404 with the store's own
    code, and the probe creates nothing.

    Path resolution is a validation rule in its own right: "Every identifier in the
    URL path must resolve to an existing row, checked in the order the segments
    appear, yielding ... `ERR_STORE_NOT_FOUND` ... as appropriate (all 404)."

    Design: Corner/entities/store_get_with_unknown_uuid_returns_store_not_found
    """
    owner = create_owner()
    create_store(owner)

    response = api_client.get_store(NON_EXISTENT_UUID, ADMIN)

    validate_error(response, ApiErrorId.ERR_STORE_NOT_FOUND.value, 404)
    assert_row_count(api_client.list_stores(ADMIN), 1)


def test_application_create_without_the_claimed_criterion_is_rejected_as_invalid():
    """Every other required field is present and valid, but the omitted
    `claimed_criterion` alone earns a 400 and writes no application.

    The schema rule requires "Required fields present, types correct, enum values
    within their declared sets, numeric bounds honoured ... otherwise
    `ERR_INVALID_REQUEST` (400)." Because the schema check precedes the optimistic
    concurrency check, the store's version is not consulted and cannot move.

    Design: Corner/entities/application_create_without_claimed_criterion_returns_invalid_request
    """
    owner = create_owner()
    store = create_store(owner)
    payload = application_payload(
        store["id"], store["version"], reported_inventory_lines=INV_PASS
    )
    payload.pop("claimed_criterion")

    response = api_client.create_application(payload, owner_headers(owner))

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert_no_rows(api_client.list_applications(ADMIN, {"store_id": store["id"]}))
    assert refresh_store(store["id"])["version"] == store["version"]


def test_the_staple_share_is_derived_rather_than_accepted_from_the_caller():
    """A registration that also supplies `staple_sales_bps` and `criterion_b_pass`
    gets the server's own figures back.

    The specification derives both: "`staple_sales_bps` is the store's staple share
    of sales in basis points: take the annual staple sales figure, multiply by
    10,000, divide by the annual gross sales figure, and take the floor of the
    result." Nothing in the declared input list admits a caller-supplied share, so
    the smuggled values are ignored and the derivation stands at 5,555.

    Design: Corner/entities/store_computed_staple_sales_bps_ignores_client_supplied_value
    """
    owner = create_owner()

    store = created(
        api_client.create_store(
            store_payload(
                owner["id"],
                store_name="Rio Computed Probe",
                tax_rate_bps=None,
                hardship_designated=None,
                staple_sales_bps=1,
                criterion_b_pass=False,
            ),
            ADMIN,
        )
    )

    assert_fields(
        store, {"staple_sales_bps": 5555, "criterion_b_pass": True}, "computed store"
    )
    assert "annual_staple_sales_pct" not in store


def test_owner_system_fields_are_server_generated_whatever_the_caller_sends():
    """Submitted identifiers, timestamps, versions and rollup counters are all
    discarded in favour of the server's own.

    The specification is explicit about identity -- "Every resource carries an `id`
    that the server mints as a UUID ... Clients never supply an `id`." -- and about
    the clock, which before any caller sets it "reads exactly
    `2026-08-01T00:00:00Z`", so both bookkeeping timestamps land there.

    Design: Corner/entities/owner_system_fields_are_server_generated_and_client_values_ignored
    """
    smuggled = "11111111-1111-4111-8111-111111111111"

    owner = created(
        api_client.create_owner(
            owner_payload(
                legal_name="Ghostwriter Foods",
                ownership_type="SOLE_PROPRIETOR",
                tax_id_last4="0001",
                id=smuggled,
                created_at="2020-01-01T00:00:00Z",
                version=99,
                status="BARRED",
                permanent_disqualification_count=7,
            ),
            ANON,
        )
    )

    assert_common_fields(owner, "owner")
    assert owner["id"] != smuggled, "the client-supplied id was accepted"
    assert_instant(owner["created_at"], "2026-08-01T00:00:00Z", "owner.created_at")
    assert_instant(owner["updated_at"], "2026-08-01T00:00:00Z", "owner.updated_at")
    assert_fields(
        owner,
        {"version": 1, "status": "ACTIVE", "permanent_disqualification_count": 0},
        "owner system fields",
    )
    assert refresh_owner(owner["id"])["status"] == "ACTIVE"


def test_store_creation_with_a_store_type_outside_the_enum_is_rejected():
    """BODEGA is not one of the six declared store types, so the registration is
    refused and no store exists to be measured.

    The declared set is closed: the caller supplies "a `store_type` drawn from
    `SUPERMARKET`, `GROCERY`, `CONVENIENCE`, `SPECIALTY`, `FARMERS_MARKET` and
    `MEAL_SERVICE`", and the schema rule requires "enum values within their declared
    sets ... otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/store_create_with_unknown_store_type_enum_is_rejected
    """
    owner = create_owner()

    response = api_client.create_store(
        store_payload(
            owner["id"],
            store_name="Rio Bodega",
            store_type="BODEGA",
            tax_rate_bps=None,
            hardship_designated=None,
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert_no_rows(api_client.list_stores(ADMIN, {"owner_id": owner["id"]}))


def test_visit_window_ending_before_it_starts_is_rejected_before_any_scheduling():
    """A window running from 04:00 back to 02:00 is refused on shape, so the
    inspector commits nothing and the application does not advance.

    The schema rule names this bound among its checks: "`window_end` strictly after
    `window_start`, `deploy_end` at or after `deploy_start`, `period_end` strictly
    after `period_start` ... otherwise `ERR_INVALID_REQUEST` (400)." Sitting at
    rule 7, it answers before any interval-conflict or capacity arithmetic.

    Design: Corner/entities/store_visit_create_with_window_end_before_window_start_is_rejected
    """
    owner = create_owner()
    store = create_store(owner)
    application = create_application(owner, store, inventory_lines=INV_PASS)
    submit_application(application, owner)
    inspector = create_inspector()

    response = api_client.create_store_visit(
        store_visit_payload(
            application["id"],
            inspector["id"],
            window_start="2026-08-01T04:00:00Z",
            window_end="2026-08-01T02:00:00Z",
        ),
        ANALYST,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert refresh_inspector(inspector["id"])["committed_minutes"] == 0
    assert_no_rows(
        api_client.list_store_visits(ADMIN, {"application_id": application["id"]})
    )


def test_a_partial_payment_appends_an_immutable_ledger_row_instead_of_editing_one():
    """Paying 23,456c against a 423,456c assessment leaves the assessment row
    untouched and appends a second row with no version and no update timestamp.

    The specification carves out exactly this entity: "There is exactly one
    exception. A `PenaltyLedgerEntry` is append-only: it carries `id` and
    `created_at` only. It has no `updated_at` and no `version`, because a ledger row
    is never edited -- a correction is a new compensating row."

    Design: Corner/entities/penalty_ledger_entries_are_append_only_with_no_version_and_no_mutator
    """
    context = authorized_store()
    four_closed_periods(context.store_id)
    investigation = substantiated_ineligible_investigation(context.store_id)
    case = open_case(investigation["id"], "INELIGIBLE_ITEMS_HARDSHIP")
    case = issue_charge_letter(case["id"])
    election = elect_cmp(case, context.owner)
    file_reply(case["id"], context.owner)
    issue_determination(case["id"], "CMP_IN_LIEU")

    entry = created(
        api_client.create_cmp_payment(
            case["id"], cmp_payment_payload(23456), context.owner_h
        )
    )

    assert_penalty_ledger_entry_shape(entry)
    assert_fields(
        entry,
        {
            "entry_type": "CMP_PAYMENT",
            "amount_cents": -23456,
            "reason_code": "RETAILER_REMITTANCE",
            "balance_after_cents": 400000,
        },
        "payment row",
    )
    entries = ledger_entries(case["id"])
    assert len(entries) == 2, f"expected two ledger rows, got {len(entries)}"
    assert_fields(
        entries[0],
        {"amount_cents": 423456, "balance_after_cents": 423456},
        "assessment row",
    )
    final_case = refresh_case(case["id"])
    assert final_case["cmp_outstanding_cents"] == 400000
    assert_ledger_conservation(entries, final_case)
    assert_fields(
        refresh_owner(context.owner_id),
        {"cmp_outstanding_cents": 400000, "sanction_flag": "HAS_ACTIVE_CMP_DEBT"},
        "owner mid-payment",
    )
    elections = assert_row_count(api_client.list_cmp_elections(case["id"], ADMIN), 1)
    assert elections[0]["id"] == election["id"]
    assert elections[0]["status"] == "APPROVED", (
        "the election stays APPROVED while the balance is still positive"
    )


def test_a_terminal_cannot_be_created_against_an_unknown_depot():
    """An unused depot identifier in the body answers 404 with the depot's own code
    and leaves the real depot's counters untouched.

    Body references are resolved as their own validation rule: "Every reference
    supplied in the request body must resolve, checked in the field order the
    endpoint declares, yielding ... `ERR_DEPOT_NOT_FOUND` ... (all 404). This
    guards ... `POST /ebt-terminals` ..."

    Design: Corner/entities/ebt_terminal_create_with_unknown_depot_returns_depot_not_found
    """
    depot = create_depot(total_units_owned=5)

    response = api_client.create_ebt_terminal(
        terminal_payload(
            NON_EXISTENT_UUID, serial_number="EBT-9999", model="EBT_ONLY_WIRELESS"
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_DEPOT_NOT_FOUND.value, 404)
    assert_no_rows(api_client.list_ebt_terminals(ADMIN, {"depot_id": depot["id"]}))
    assert_depot_conservation(
        refresh_depot(depot["id"]),
        {
            "units_in_stock": 5,
            "units_reserved": 0,
            "units_deployed": 0,
            "units_pending_return": 0,
            "units_retired": 0,
        },
    )


def test_deployments_form_a_junction_reachable_from_both_of_its_parents():
    """One terminal booked at two stores over disjoint windows and one store holding
    two terminals are all reachable through the deployment collection's two filters.

    Deployments are the many-to-many link between stores and terminals: the listing
    "Deployments may be filtered by `store_id`, `terminal_id` and `status`", so
    neither parent owns the other. A unit booked twice over disjoint windows is
    still one physical unit, which the depot identity enforces.

    Design: Corner/entities/terminal_deployment_is_the_many_to_many_junction_between_store_and_terminal
    """
    first = authorized_store()
    second_store = create_store(
        first.owner,
        store_name="Rio Corner Market",
        checkout_lane_count=1,
        annual_gross_sales_cents=24000000,
        annual_staple_sales_cents=14000000,
        max_terminal_slots=1,
        tax_rate_bps=None,
        hardship_designated=None,
    )
    depot = create_depot(total_units_owned=5)
    terminal = create_terminal(depot)
    terminal2 = create_terminal(depot, serial_number="EBT-0002", model="EBT_ONLY_DIAL")

    booking_a1 = created(
        api_client.create_terminal_deployment(
            deployment_payload(
                first.store_id,
                terminal["id"],
                deploy_start="2026-08-01T00:00:00Z",
                deploy_end="2026-09-30T00:00:00Z",
            ),
            ADMIN,
        )
    )
    booking_b1 = created(
        api_client.create_terminal_deployment(
            deployment_payload(
                second_store["id"],
                terminal["id"],
                deploy_start="2026-10-01T00:00:00Z",
                deploy_end="2026-12-31T00:00:00Z",
            ),
            ADMIN,
        )
    )
    booking_a2 = created(
        api_client.create_terminal_deployment(
            deployment_payload(
                first.store_id,
                terminal2["id"],
                deploy_start="2026-08-01T00:00:00Z",
                deploy_end="2026-09-30T00:00:00Z",
            ),
            ADMIN,
        )
    )

    for booking in (booking_a1, booking_b1, booking_a2):
        assert booking["status"] == "RESERVED"
    by_terminal = data_ids(
        api_client.list_terminal_deployments(ADMIN, {"terminal_id": terminal["id"]})
    )
    assert sorted(by_terminal) == sorted([booking_a1["id"], booking_b1["id"]])
    by_store = data_ids(
        api_client.list_terminal_deployments(ADMIN, {"store_id": first.store_id})
    )
    assert sorted(by_store) == sorted([booking_a1["id"], booking_a2["id"]])
    assert_depot_conservation(
        refresh_depot(depot["id"]), {"units_reserved": 2, "units_in_stock": 3}
    )
