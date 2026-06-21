"""Entity CRUD, defaults, pagination, optimistic concurrency, RBAC, and FK reachability.

Covers queue B sections: entities, endpoints, rbac, cross_cutting_complexity_layers (OCC
and multi-tenancy).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_agency,
    create_agency_and_order,
    setup_order_with_issued_commitment,
    create_pending_policy,
    add_exception_in_curative_pending,
    add_curative_action,
    add_posted_deposit,
    add_disbursement,
    get_order,
    make_agency_headers,
    TEST_USERS,
    TO,
    UW,
)


# ---------------------------------------------------------------------------
# Queue B — entities: creation, retrieval, listing, not-found, required fields, defaults
# ---------------------------------------------------------------------------
def test_create_order_returns_201_with_zero_escrow(api):
    """PRD §3.2: "A new order opens in `OPENED` `status`, with its escrow figures at zero
    and `gap_open` false."
    PRD §2.4: "`version`, an integer that begins at 1 and increments by one on every
    mutation".

    Design: Corner/entities/create_order_returns_201_with_computed_escrow_zero
    """
    agency = create_agency()
    headers = make_agency_headers(agency["id"])
    data = validate_success(
        api.create_order(
            {
                "agency_id": agency["id"], "parcel_id": "APN-C1", "county": "King",
                "transaction_type": "PURCHASE", "sales_price_cents": 25_000_000, "loan_amount_cents": 0,
            },
            headers,
        ),
        expected_status=201,
    )
    assert data["status"] == "OPENED"
    assert data["escrow_balance_cents"] == 0
    assert data["escrow_deposit_total_cents"] == 0
    assert data["escrow_disbursed_total_cents"] == 0
    assert data["gap_open"] is False
    assert data["version"] == 1


def test_get_order_returns_stored_entity(api):
    """PRD §4: "GET `/title/orders/{id}` | Get an order, including computed escrow figures".
    PRD §2.4: "Every resource is addressed by an `id`, which is a server-minted UUID".

    Design: Corner/entities/get_order_returns_stored_entity
    """
    _agency, order = create_agency_and_order(parcel_id="APN-C2")
    data = validate_success(api.get_order(order["id"], UW))
    assert data["id"] == order["id"]
    assert data["parcel_id"] == "APN-C2"


def test_list_orders_returns_paginated_envelope(api):
    """PRD §2.3: "Every list-based response carries the pagination bookkeeping in the
    `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_orders_paginated_envelope
    """
    agency, _order = create_agency_and_order(parcel_id="APN-C3")
    data, meta = validate_paginated(api.list_orders(UW, params={"agency_id": agency["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] >= 1
    assert "has_more" in meta
    assert isinstance(data, list)


def test_get_order_not_found_returns_404(api):
    """PRD §2.5: "For any request that targets a nested resource, the system validates path
    identifiers left to right and rejects the request with `ERR_NOT_FOUND` at the first
    identifier that does not resolve to an existing resource within scope."

    Design: Corner/entities/get_order_not_found_returns_404
    """
    validate_error(api.get_order(NON_EXISTENT_UUID, UW), ApiErrorId.ERR_NOT_FOUND.value)


def test_create_order_missing_transaction_type_rejected(api):
    """PRD §2.8: "Request well-formedness is fourth: a mutating request whose body is
    missing a required field, carries an invalid enum value, or supplies an out-of-range
    number fails with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_order_missing_transaction_type_returns_invalid_request
    """
    agency = create_agency()
    headers = make_agency_headers(agency["id"])
    validate_error(
        api.create_order(
            {
                "agency_id": agency["id"], "parcel_id": "APN-C4", "county": "King",
                "sales_price_cents": 25_000_000, "loan_amount_cents": 0,
            },
            headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


def test_exception_default_curative_required_false(api):
    """PRD §3.5: "an optional `curative_required` flag (defaulting to false) that marks an
    exception which must pass through curative before it can clear."

    Design: Corner/entities/create_exception_default_curative_required_false
    """
    _agency, _order, commitment = setup_order_with_issued_commitment()
    data = validate_success(
        api.create_exception(commitment["id"], {"exception_type": "STANDARD", "description": "Pre-printed survey exception"}, TO),
        expected_status=201,
    )
    assert data["curative_required"] is False
    assert data["status"] == "RAISED"


def test_plant_record_has_no_version_field(api):
    """PRD §2.4: "The `TitlePlantRecord`, which captures an immutable recorded instrument
    in the county plant, carries only `id` and `created_at`; it has neither `updated_at`
    nor `version`, because a recorded instrument is never mutated after it is written into
    the plant."

    Design: Corner/entities/plant_record_immutable_no_version_field
    """
    created = validate_success(
        api.create_plant_record(
            {
                "parcel_id": "APN-C7", "county": "King", "instrument_type": "DEED",
                "recorded_date": "2020-01-01T00:00:00Z", "sequence_no": 1, "grantor": "A", "grantee": "B",
            },
            TO,
        ),
        expected_status=201,
    )
    data = validate_success(api.get_plant_record(created["id"], TO))
    assert "id" in data and "created_at" in data
    assert "version" not in data, "TitlePlantRecord must not carry a version field"
    assert "updated_at" not in data, "TitlePlantRecord must not carry an updated_at field"


# ---------------------------------------------------------------------------
# Queue B — cross_cutting_complexity_layers: optimistic concurrency
# ---------------------------------------------------------------------------
def test_stale_order_version_on_second_commitment_reissue(api):
    """PRD §2.7: "The request body must include `expected_order_version`; if it does not
    equal the order's current `version`, the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    The first re-issue bumps the order version; a second re-issue carrying the pre-bump
    version is stale.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_order_version_on_commitment_reissue
    """
    _agency, order, _c1 = setup_order_with_issued_commitment()
    stale_version = get_order(order["id"])["version"]
    # First re-issue create — consumes stale_version and bumps the order version.
    validate_success(
        api.create_commitment(
            order["id"],
            {
                "effective_date": "2026-02-05T00:00:00Z", "expiry_date": "2026-08-05T00:00:00Z",
                "schedule_a_estate": "FEE_SIMPLE", "insured_amount_cents": 25_000_000,
                "expected_order_version": stale_version,
            },
            TO,
        ),
        expected_status=201,
    )
    # Second re-issue create reusing the now-stale version.
    validate_error(
        api.create_commitment(
            order["id"],
            {
                "effective_date": "2026-03-05T00:00:00Z", "expiry_date": "2026-09-05T00:00:00Z",
                "schedule_a_estate": "FEE_SIMPLE", "insured_amount_cents": 25_000_000,
                "expected_order_version": stale_version,
            },
            TO,
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
    )


def test_stale_order_version_on_second_disbursement_create(api):
    """PRD §2.7: "Its request body must also carry `expected_order_version`; a value that
    does not match the order's current `version` is rejected with `ERR_STALE_VERSION`
    (HTTP 412). Because every disbursement create advances the order's `version`, a client
    whose `expected_order_version` lags behind has not observed a disbursement that already
    drew down the trust balance".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_order_version_on_disbursement_create
    """
    agency, order = create_agency_and_order()
    add_posted_deposit(order, agency, amount_cents=500_000, source_ref="WIRE-IN-OCC")
    stale_version = get_order(order["id"])["version"]
    # First disbursement create — consumes stale_version and bumps the order version.
    validate_success(
        api.create_disbursement(
            order["id"],
            {
                "payee": "Seller", "amount_cents": 100_000, "purpose": "SELLER_PROCEEDS",
                "wire_window_start": "2026-01-20T09:00:00Z", "wire_window_end": "2026-01-20T10:00:00Z",
                "expected_order_version": stale_version,
            },
            UW,
        ),
        expected_status=201,
    )
    # Second disbursement create reusing the now-stale version.
    validate_error(
        api.create_disbursement(
            order["id"],
            {
                "payee": "Payoff", "amount_cents": 100_000, "purpose": "PAYOFF",
                "wire_window_start": "2026-01-20T11:00:00Z", "wire_window_end": "2026-01-20T12:00:00Z",
                "expected_order_version": stale_version,
            },
            UW,
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
    )


def test_order_list_is_tenant_scoped_by_agency_id(api):
    """PRD §4: "GET `/title/orders` | List orders, filterable by `agency_id` and `status`".
    PRD §2.1: "an agency may operate only on orders it owns — an order's `agency_id` must
    equal `X-User-ID`".

    Design: Corner/cross_cutting_complexity_layers/agency_multi_tenant_order_list_isolation
    """
    agency_a = create_agency(name="Agency A")
    agency_b = create_agency(name="Agency B", remit_split_pct=0.80)
    order_a = validate_success(
        api.create_order(
            {"agency_id": agency_a["id"], "parcel_id": "APN-A1", "county": "King",
             "transaction_type": "PURCHASE", "sales_price_cents": 25_000_000, "loan_amount_cents": 0},
            make_agency_headers(agency_a["id"]),
        ),
        expected_status=201,
    )
    order_b = validate_success(
        api.create_order(
            {"agency_id": agency_b["id"], "parcel_id": "APN-B1", "county": "King",
             "transaction_type": "PURCHASE", "sales_price_cents": 25_000_000, "loan_amount_cents": 0},
            make_agency_headers(agency_b["id"]),
        ),
        expected_status=201,
    )
    data, _meta = validate_paginated(api.list_orders(UW, params={"agency_id": agency_a["id"], "limit": 100}))
    ids = {o["id"] for o in data}
    assert order_a["id"] in ids, "agency A's order must appear in its own filtered list"
    assert order_b["id"] not in ids, "agency B's order must NOT leak into agency A's list"


# ---------------------------------------------------------------------------
# Queue B — rbac
# ---------------------------------------------------------------------------
def test_agency_cannot_issue_policy(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted for the requested
    operation is rejected with `ERR_UNAUTHORIZED`."
    Policy creation is an Underwriter operation (PRD §4: POST `/title/orders/{id}/policies`
    | ... | Underwriter).

    Design: Corner/rbac/agency_cannot_issue_policy
    """
    agency, order, commitment = setup_order_with_issued_commitment()
    headers = make_agency_headers(agency["id"])
    validate_error(
        api.create_policy(
            order["id"],
            {"commitment_id": commitment["id"], "policy_type": "OWNER", "coverage_amount_cents": 25_000_000},
            headers,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )


def test_agency_cannot_act_on_foreign_order(api):
    """PRD §2.1: "An agency that attempts to act on an order whose `agency_id` is not its
    own `X-User-ID` is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/agency_cannot_act_on_foreign_order
    """
    agency_a = create_agency(name="Agency A")
    agency_b = create_agency(name="Agency B", remit_split_pct=0.80)
    order_a = validate_success(
        api.create_order(
            {"agency_id": agency_a["id"], "parcel_id": "APN-C29", "county": "King",
             "transaction_type": "PURCHASE", "sales_price_cents": 25_000_000, "loan_amount_cents": 0},
            make_agency_headers(agency_a["id"]),
        ),
        expected_status=201,
    )
    # Agency B reaches for agency A's order.
    validate_error(
        api.create_deposit(order_a["id"], {"amount_cents": 1_000, "source_ref": "WIRE-X"}, make_agency_headers(agency_b["id"])),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "A request that is missing either header, or that carries an `X-User-Role`
    value outside this set, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    from test_helpers import build_user_headers
    headers = build_user_headers("ghost-1", "Nobody")
    validate_error(
        api.create_agency({"name": "Ghost", "remit_split_pct": 0.5}, headers),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )


def test_title_officer_cannot_post_deposit(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted for the requested
    operation is rejected with `ERR_UNAUTHORIZED`."
    Posting a deposit is an Underwriter operation (PRD §4: POST `/title/deposits/{id}/
    transitions` | ... | Underwriter).

    Design: Corner/rbac/titleofficer_cannot_post_deposit_transition
    """
    agency, order = create_agency_and_order()
    deposit = validate_success(
        api.create_deposit(order["id"], {"amount_cents": 100_000, "source_ref": "WIRE-IN-9"}, make_agency_headers(agency["id"])),
        expected_status=201,
    )
    validate_error(
        api.transition_deposit(deposit["id"], {"to_status": "POSTED"}, TO),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )


# ---------------------------------------------------------------------------
# Queue B — endpoints: FK reverse-reachability + conditional clear
# ---------------------------------------------------------------------------
def test_list_exceptions_for_commitment(api):
    """PRD §4: "GET `/title/commitments/{id}/exceptions` | List exceptions for a
    commitment, filterable by `status`".
    PRD §3.5: "A title officer raises one against a commitment".

    Design: Corner/endpoints/fk_reverse_list_exceptions_for_commitment
    """
    _agency, _order, commitment = setup_order_with_issued_commitment()
    validate_success(api.create_exception(commitment["id"], {"exception_type": "STANDARD", "description": "Survey"}, TO), expected_status=201)
    validate_success(api.create_exception(commitment["id"], {"exception_type": "SPECIAL", "description": "Easement"}, TO), expected_status=201)
    data, meta = validate_paginated(api.list_exceptions(commitment["id"], TO))
    assert meta["total_count"] == 2
    assert all(ex["commitment_id"] == commitment["id"] for ex in data)


def test_filter_policies_by_commitment_id(api):
    """PRD §4: "GET `/title/policies` | List policies, filterable by `order_id`,
    `commitment_id`, and `status`".

    Design: Corner/endpoints/fk_reverse_filter_policies_by_commitment
    """
    _agency, order, commitment = setup_order_with_issued_commitment()
    policy = create_pending_policy(order, commitment, coverage_amount_cents=25_000_000)
    data, _meta = validate_paginated(api.list_policies(UW, params={"commitment_id": commitment["id"]}))
    ids = {p["id"] for p in data}
    assert policy["id"] in ids
    assert all(p["commitment_id"] == commitment["id"] for p in data)


def test_curative_action_created_and_listed_on_order(api):
    """PRD §3.5: "Curative work itself is tracked as a `CurativeAction`, opened under an
    order against either an exception or a claim. ... A curative action opens in `OPEN`."

    Design: Corner/endpoints/curative_action_create_and_list
    """
    _agency, order, commitment = setup_order_with_issued_commitment()
    exception = add_exception_in_curative_pending(commitment, exception_type="SPECIAL", description="Boundary encroachment")
    action = validate_success(
        api.create_curative_action(order["id"], {"subject_type": "EXCEPTION", "subject_id": exception["id"], "action_type": "RELEASE_FILED"}, TO),
        expected_status=201,
    )
    assert action["status"] == "OPEN"
    data, _meta = validate_paginated(api.list_curative_actions(order["id"], TO))
    found = [a for a in data if a["id"] == action["id"]]
    assert found and found[0]["subject_id"] == exception["id"]


def test_clear_exception_after_resolved_curative_succeeds(api):
    """PRD §3.5: "From `CURATIVE_PENDING` it can be **cleared** to `CLEARED`, but only once
    a `CurativeAction` whose `subject_type` is `EXCEPTION` and whose `subject_id` is this
    exception exists in `RESOLVED` status (otherwise `ERR_NO_RESOLVED_CURATIVE`)."
    PRD §3.5: "Every transition into `WAIVED`, `CLEARED`, `VOID`, or back to `RAISED`
    recomputes the parent commitment's `open_exception_count`".

    Design: Corner/endpoints/exception_clear_after_resolved_curative_succeeds
    """
    _agency, order, commitment = setup_order_with_issued_commitment()
    exception = add_exception_in_curative_pending(commitment, exception_type="SUBORDINATE_LIEN", description="Second mortgage")
    add_curative_action(order, "EXCEPTION", exception["id"], action_type="PAYOFF", resolve=True)
    data = validate_success(api.transition_exception(exception["id"], {"to_status": "CLEARED"}, TO))
    assert data["status"] == "CLEARED"
    commitment_after = validate_success(api.get_commitment(commitment["id"], TO))
    assert commitment_after["open_exception_count"] == 0
