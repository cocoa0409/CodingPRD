"""Policy creation, coverage assembly, premium pricing, and basic CRUD.

Every test builds its own state from scratch; the server starts empty.
"""
from test_helpers import (
    add_full_coverage,
    api_client,
    assert_additional_insured,
    assert_policy,
    assert_policyholder,
    create_policyholder,
    create_quoted_policy,
    get_first_invoice,
    issue_policy,
    make_policyholder_headers,
    set_clock,
    setup_active_policy,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]


# ---------------------------------------------------------------------------
# Queue B: entities — creation / required-fields / defaults / not-found / types
# ---------------------------------------------------------------------------
def test_create_policyholder_mints_system_fields(api):
    """PRD §2.4: "Every entity in this system carries a server-minted `id`
    formatted as a UUID" and "`version` starts at the resource's creation value
    and increments by one on every mutation."

    Design: Corner/entities/create_policyholder_returns_201_with_system_fields
    """
    resp = api.create_policyholder(
        {"email": "c1@x.com", "full_name": "C One", "mailing_address": "1 St"}, UW
    )
    data = validate_success(resp, 201)
    assert_policyholder(data)
    assert data["version"] == 1, f"version must start at 1, got {data['version']}"
    assert data["email"] == "c1@x.com"


def test_create_policy_missing_territory_code_rejected(api):
    """PRD §2.5: "A malformed body — a missing required field, a value of the
    wrong type, or an invalid enumeration value — is rejected with
    ERR_INVALID_REQUEST."

    Design: Corner/entities/create_policy_missing_required_territory_code_returns_invalid_request
    """
    ph = create_policyholder(email="c2@x.com")
    resp = api.create_policy(
        {
            "policyholder_id": ph["id"],
            "insured_address": "30 St",
            "effective_date": "2026-01-01T00:00:00Z",
            "expiry_date": "2027-01-01T00:00:00Z",
            "deductible_cents": 25000,
        },
        UW,
    )
    validate_error(resp, "ERR_INVALID_REQUEST", 400)


def test_policy_pp_valuation_method_defaults_to_rcv(api):
    """PRD §3.2: "an optional `pp_valuation_method` of `RCV` or `ACV`
    (defaulting to `RCV`) that fixes the default personal-property valuation
    for this policy's claims."

    Design: Corner/entities/policy_pp_valuation_method_default_is_rcv
    """
    ph = create_policyholder(email="c3@x.com")
    resp = api.create_policy(
        {
            "policyholder_id": ph["id"],
            "insured_address": "31 St",
            "territory_code": "STANDARD",
            "effective_date": "2026-01-01T00:00:00Z",
            "expiry_date": "2027-01-01T00:00:00Z",
            "deductible_cents": 25000,
        },
        UW,
    )
    data = validate_success(resp, 201)
    assert data["pp_valuation_method"] == "RCV"
    assert data["status"] == "QUOTED"


def test_get_unknown_policy_returns_not_found(api):
    """PRD §2.5: "The same `ERR_NOT_FOUND` covers any single-resource fetch
    whose path identifier is unknown."

    Design: Corner/entities/get_policy_nonexistent_id_returns_not_found
    """
    resp = api.get_policy("00000000-0000-4000-8000-000000000abc", UW)
    validate_error(resp, "ERR_NOT_FOUND", 404)


def test_coverage_line_invalid_enum_rejected(api):
    """PRD §2.5: "A malformed body — a missing required field, a value of the
    wrong type, or an invalid enumeration value — is rejected with
    ERR_INVALID_REQUEST."

    Design: Corner/entities/coverage_line_invalid_enum_coverage_type_returns_invalid_request
    """
    ph = create_policyholder(email="c4@x.com")
    policy = create_quoted_policy(ph["id"])
    resp = api.add_coverage_line(
        policy["id"],
        {"coverage_type": "FLOOD", "limit_cents": 100000,
         "expected_policy_version": policy["version"]},
        UW,
    )
    validate_error(resp, "ERR_INVALID_REQUEST", 400)


def test_create_policy_unknown_policyholder_fk_rejected(api):
    """PRD §2.5: "When a body references another resource by `policyholder_id`,
    `bundle_id`, `policy_id`, `invoice_id`, `coverage_line_id`, or
    `scheduled_item_id`, and that target does not exist, the request is rejected
    with `ERR_FK_NOT_FOUND`."

    Design: Corner/validations/fk_not_found_unknown_policyholder_on_policy_create
    """
    resp = api.create_policy(
        {
            "policyholder_id": "00000000-0000-4000-8000-0000000000ff",
            "insured_address": "54 St",
            "territory_code": "STANDARD",
            "effective_date": "2026-01-01T00:00:00Z",
            "expiry_date": "2027-01-01T00:00:00Z",
            "deductible_cents": 25000,
        },
        UW,
    )
    validate_error(resp, "ERR_FK_NOT_FOUND", 404)


# ---------------------------------------------------------------------------
# Queue A: combinatorial premium calculation (mode a)
# ---------------------------------------------------------------------------
def test_premium_tiered_territory_times_bundle_with_scheduled_surcharge(api):
    """PRD §3.2: "The subtotal is the base policy fee plus four rounded
    components: the personal-property limit multiplied by the personal-property
    rate of 0.004, the liability limit multiplied by the liability rate of
    0.0008, the loss-of-use limit multiplied by the loss-of-use rate of 0.0015,
    and the scheduled-item sum multiplied by the scheduled-item rate of 0.018 —
    each of these four products rounded half up to a whole cent before being
    added into the subtotal."
    PRD §3.2: "The final `annual_premium_cents` is the subtotal multiplied by
    the territory factor and the bundle factor, with that single final product
    rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/premium_tiered_territory_times_bundle_with_scheduled_surcharge
    """
    ph = create_policyholder(email="prem@x.com")
    policy = create_quoted_policy(ph["id"], territory_code="STANDARD")
    add_full_coverage(policy["id"])
    # one scheduled item appraised 500000, threading the live version
    v = api.get_policy(policy["id"], UW).json()["data"]["version"]
    validate_success(
        api.add_scheduled_item(
            policy["id"],
            {"description": "ring", "appraised_value_cents": 500000,
             "deductible_waived": True, "expected_policy_version": v},
            UW,
        ),
        201,
    )
    issued = validate_success(api.issue_policy(policy["id"], UW), 200)
    assert_policy(issued)
    assert issued["annual_premium_cents"] == 42350, issued["annual_premium_cents"]
    assert issued["status"] == "ACTIVE"


def test_premium_standard_no_scheduled_item_value(api):
    """PRD §3.2: "It works from a small set of inputs and a fixed base policy
    fee of 12000 cents." with components "the personal-property limit
    multiplied by the personal-property rate of 0.004, the liability limit
    multiplied by the liability rate of 0.0008, the loss-of-use limit
    multiplied by the loss-of-use rate of 0.0015".
    PRD §3.2: "The territory factor is 1.25 for `HIGH`, 1.00 for `STANDARD`,
    and 0.85 for `LOW`."

    Design: Difficulty/combinatorial_formula/premium_tiered_territory_times_bundle_with_scheduled_surcharge
    """
    _ph, policy, _lines, _inv = setup_active_policy(territory_code="STANDARD",
                                                    email="prem2@x.com")
    assert policy["annual_premium_cents"] == 33350, policy["annual_premium_cents"]


# ---------------------------------------------------------------------------
# Queue B: endpoints — listing, sub-resource reachability, additional insured
# ---------------------------------------------------------------------------
def test_list_policies_filtered_by_policyholder_paginated(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope."
    PRD §4: "List policies (filter by policyholder_id, bundle_id, status)".

    Design: Corner/endpoints/list_policies_filtered_by_policyholder_paginated
    """
    ph = create_policyholder(email="e1@x.com")
    create_quoted_policy(ph["id"], insured_address="55 St")
    create_quoted_policy(ph["id"], insured_address="56 St", territory_code="LOW",
                         effective_date="2026-06-01T00:00:00Z",
                         expiry_date="2027-06-01T00:00:00Z", deductible_cents=50000)
    resp = api.list_policies(UW, params={"policyholder_id": ph["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, meta
    assert len(data) == 2, data


def test_scheduled_items_reverse_reachable_via_subresource(api):
    """PRD §2.5: "Many resources are addressed through a path that names a
    parent and then a child collection — for example a policy and its coverage
    lines, scheduled items, additional insureds, claims, or invoices".

    Design: Corner/endpoints/scheduled_items_reverse_reachable_via_subresource
    """
    ph = create_policyholder(email="e2@x.com")
    policy = create_quoted_policy(ph["id"])
    v = policy["version"]
    si = validate_success(
        api.add_scheduled_item(
            policy["id"],
            {"description": "camera", "appraised_value_cents": 300000,
             "expected_policy_version": v},
            UW,
        ),
        201,
    )
    resp = api.list_scheduled_items(policy["id"], UW)
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, data
    assert data[0]["id"] == si["id"]


def test_add_additional_insured_landlord(api):
    """PRD §3.2: "carries the `party_name` (the interested party's legal name),
    an optional `interest_type` of `LANDLORD` or `PROPERTY_MANAGER` (defaulting
    to `LANDLORD`)... Its `status` is `ACTIVE` on creation".

    Design: Corner/endpoints/add_additional_insured_landlord
    """
    ph = create_policyholder(email="e3@x.com")
    policy = create_quoted_policy(ph["id"])
    resp = api.add_additional_insured(
        policy["id"],
        {"party_name": "Acme Realty", "interest_type": "LANDLORD",
         "notify_email": "ll@x.com"},
        make_policyholder_headers(ph["id"]),
    )
    data = validate_success(resp, 201)
    assert_additional_insured(data)
    assert data["interest_type"] == "LANDLORD"
    assert data["status"] == "ACTIVE"
