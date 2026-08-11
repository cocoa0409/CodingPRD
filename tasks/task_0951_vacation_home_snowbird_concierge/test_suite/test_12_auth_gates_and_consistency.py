"""Authentication, the role gate, pagination, the logical clock and immediate consistency."""

from test_helpers import (
    ACCOUNT_MANAGER,
    AUDITOR,
    DISPATCHER,
    NO_AUTH_HEADERS,
    PLATFORM_ADMIN,
    ApiErrorId,
    assert_same_instant,
    create_away_period_payload,
    create_owner_payload,
    create_subscription_payload,
    make_headers,
    make_owner_headers,
    new_owner,
    new_property,
    new_service_plan,
    read_clock,
    refresh_cycle,
    refresh_subscription,
    set_clock,
    setup_subscribed_property,
    validate_error,
    validate_paginated,
    validate_success,
)

STANDARD = {"tier": "STANDARD", "monthly_fee_cents": 19986, "included_visit_units": 4,
            "covered_visit_types": ["ROUTINE_WATCH"]}


# --------------------------------------------------------------------------
# Gate G1 — authentication
# --------------------------------------------------------------------------

def test_a_request_with_no_identity_headers_is_unauthenticated(api):
    """PRD 2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting
    principal, and `X-User-Role`, naming the role that principal is acting under. If
    either header is absent or empty the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/errors/err_unauthenticated_when_headers_absent_returns_401
    """
    response = api.create_owner(
        create_owner_payload(full_name="No Auth", email="no.auth@example.com",
                             primary_residence_state="MN"),
        NO_AUTH_HEADERS,
    )
    assert response.status_code == 401, f"expected 401, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_an_undeclared_role_name_is_an_unknown_role(api):
    """PRD 2.1: "If `X-User-Role` carries a string that is not one of the eight declared
    role names, the request is rejected with `ERR_UNKNOWN_ROLE` (also HTTP 401)."
    PRD 2.1: "The eight roles, spelled exactly as they must appear in the header, are
    `PlatformAdmin`, `Owner`, `AccountManager`, `Dispatcher`, `FieldTech`, `Vendor`,
    `StormCoordinator` and `Auditor`."

    Design: Corner/errors/err_unknown_role_for_undeclared_role_header_returns_401
    """
    response = api.create_owner(
        create_owner_payload(full_name="Bad Role", email="bad.role@example.com",
                             primary_residence_state="MN"),
        make_headers("op-1", "Concierge"),
    )
    assert response.status_code == 401, f"expected 401, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_UNKNOWN_ROLE.value)


# --------------------------------------------------------------------------
# Gate G2 — role and scope
# --------------------------------------------------------------------------

def test_the_auditor_can_read_every_collection(api):
    """PRD 2.1: "is a read-only compliance observer. It holds read access to every
    collection and every single-resource read in the system and holds no write permission
    anywhere; every non-read request under this role is rejected with
    `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/auditor_holds_read_access_to_every_collection
    """
    set_clock("2026-06-01T00:00:00Z")
    new_owner(full_name="Ada Audit", primary_residence_state="OR")
    from test_helpers import new_vendor
    vendor = new_vendor(legal_name="Audit Plumbing", trade="PLUMBING", hourly_rate_cents=8000,
                        rating=4.0)

    vendors, vendor_meta = validate_paginated(api.list_vendors(headers=AUDITOR))
    assert vendor_meta["total_count"] == 1
    assert vendors[0]["id"] == vendor["id"]

    invoices = api.list_invoices(headers=AUDITOR)
    invoice_rows, invoice_meta = validate_paginated(invoices)
    assert invoice_meta["total_count"] == 0
    assert invoices.json()["response_type"] == "array"

    _, work_order_meta = validate_paginated(api.list_work_orders(headers=AUDITOR))
    assert work_order_meta["total_count"] == 0


def test_an_owner_cannot_drive_another_owners_property(api):
    """PRD 2.8: "When the acting role is `Owner`, `X-User-ID` equals the `owner_id` of the
    property the request targets, or of the invoice, away period, or work-order's property
    it targets. This applies to every endpoint whose role list includes `Owner`. Otherwise
    `ERR_NOT_RESOURCE_OWNER`, HTTP 403."

    Design: Corner/rbac/owner_cannot_act_on_another_owners_property
    """
    set_clock("2026-06-01T00:00:00Z")
    first = new_owner(full_name="Owner A", email="owner.a@example.com",
                      primary_residence_state="UT")
    second = new_owner(full_name="Owner B", email="owner.b@example.com",
                       primary_residence_state="ID")
    prop = new_property(first["id"], label="A House", address_line="4 Scope St",
                        travel_distance_miles=5.0)

    response = api.create_property_occupancy_transition(
        prop["id"], {"to_state": "OWNER_IN_RESIDENCE"}, make_owner_headers(second["id"])
    )
    assert response.status_code == 403, f"expected 403, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert validate_success(api.get_property(prop["id"], DISPATCHER))["occupancy_state"] == "VACANT"


def test_the_role_gate_answers_before_the_existence_gate(api):
    """PRD 2.7: "The gates are evaluated strictly in ascending gate number, the **first
    gate that fails determines both the `error_id` and the HTTP status**, and no later gate
    is evaluated at all."
    PRD 2.8: "The acting role appears in the endpoint's declared role list, on every
    endpoint. Otherwise `ERR_ROLE_NOT_PERMITTED`, HTTP 403."

    Design: Difficulty/priority_pair_validation_conflict/auditor_write_on_unknown_visit_returns_403_not_404
    """
    set_clock("2026-06-01T00:00:00Z")
    response = api.abort_visit("00000000-0000-4000-8000-000000000001", {}, AUDITOR)
    assert response.status_code == 403, f"expected 403, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)


def test_the_auditor_is_refused_a_write_even_on_a_row_that_exists(api):
    """PRD 2.1: "is a read-only compliance observer. It holds read access to every
    collection and every single-resource read in the system and holds no write permission
    anywhere; every non-read request under this role is rejected with
    `ERR_ROLE_NOT_PERMITTED`."
    PRD 2.7: "2. **G2 — ROLE AND SCOPE.** The acting role is listed in the endpoint's
    authorized roles; then, for the two entity-backed roles, `X-User-ID` must match the
    owning foreign key of the target resource"

    Design: Difficulty/priority_pair_validation_conflict/auditor_write_on_unknown_visit_returns_403_not_404
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    from test_helpers import new_template, new_visit, refresh_visit
    template = new_template("ROUTINE_WATCH", item_codes=["EXT_WALK"], critical_item_codes=[])
    visit = new_visit(ctx["property_id"], template["id"])

    response = api.abort_visit(visit["id"], {}, AUDITOR)
    assert response.status_code == 403, f"expected 403, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)
    assert refresh_visit(visit["id"])["status"] == "SCHEDULED"


# --------------------------------------------------------------------------
# Gate G3 — body foreign keys
# --------------------------------------------------------------------------

def test_unknown_service_plan_on_subscription_creation_is_a_404(api):
    """PRD 2.8: "A body field `service_plan_id` resolves to an existing service plan. This
    applies to subscription creation and to scheduling a plan tier change. Otherwise
    `ERR_SERVICE_PLAN_NOT_FOUND`, HTTP 404."

    Design: Corner/errors/err_service_plan_not_found_on_subscription_create_returns_404
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner(full_name="Nop Plan", primary_residence_state="MN")
    prop = new_property(owner["id"], label="NoPlan House", address_line="10 Void Vw",
                        travel_distance_miles=18.0)
    response = api.create_subscription(
        create_subscription_payload(prop["id"], "00000000-0000-4000-8000-0000000000b1",
                                    "2026-06-01T00:00:00Z"),
        ACCOUNT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_SERVICE_PLAN_NOT_FOUND.value)


# --------------------------------------------------------------------------
# Gate G10 — payload shapes on the away period
# --------------------------------------------------------------------------

def test_a_reversed_away_period_interval_is_malformed(api):
    """PRD 2.8: "Every supplied interval is well formed, on every endpoint that accepts
    one: `scheduled_end_at` strictly after `scheduled_start_at`; `window_end_at` strictly
    after `window_start_at`; `end_at` strictly after `start_at`; `end_on` strictly after
    `start_on`; `checkin_at` strictly after `checkout_at`. Otherwise
    `ERR_INTERVAL_MALFORMED`, HTTP 400."

    Design: Corner/errors/err_interval_malformed_on_reversed_away_period_returns_400
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner(full_name="Rev Interval", primary_residence_state="MN")
    prop = new_property(owner["id"], label="Rev House", address_line="64 Back St",
                        travel_distance_miles=5.0)
    response = api.create_away_period(
        create_away_period_payload(prop["id"], owner["id"], start_at="2026-09-01T00:00:00Z",
                                   end_at="2026-07-01T00:00:00Z", cadence_days=14),
        ACCOUNT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_INTERVAL_MALFORMED.value)
    _, meta = validate_paginated(
        api.list_away_periods(headers=AUDITOR, params={"property_id": prop["id"]})
    )
    assert meta["total_count"] == 0


def test_an_away_period_longer_than_two_hundred_and_forty_days_is_invalid(api):
    """PRD 3.3: "The declared `owner_id` must equal the property's own `owner_id`, and the
    window may span at most 240 days; either violation is rejected with
    `ERR_AWAY_PERIOD_INVALID`."

    Design: Corner/errors/err_away_period_invalid_when_span_exceeds_240_days_returns_400
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner(full_name="Long Away", primary_residence_state="MN")
    prop = new_property(owner["id"], label="Long House", address_line="240 Span St",
                        travel_distance_miles=5.0)
    response = api.create_away_period(
        create_away_period_payload(prop["id"], owner["id"], start_at="2026-07-01T00:00:00Z",
                                   end_at="2027-04-27T00:00:00Z", cadence_days=14),
        ACCOUNT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_AWAY_PERIOD_INVALID.value)


def test_a_cadence_below_three_days_is_out_of_range(api):
    """PRD 3.3: "A snowbird absence is declared as an away period naming a `property_id`
    and an `owner_id`, an inclusive `start_at`, an exclusive `end_at` and a requested
    `cadence_days` between watch visits, which must be at least 3 and at most 30."

    Design: Corner/errors/err_value_out_of_range_for_cadence_below_minimum_returns_400
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner(full_name="Fast Cad", primary_residence_state="MN")
    prop = new_property(owner["id"], label="Fast House", address_line="3 Min St",
                        travel_distance_miles=5.0)
    response = api.create_away_period(
        create_away_period_payload(prop["id"], owner["id"], start_at="2026-07-01T00:00:00Z",
                                   end_at="2026-08-01T00:00:00Z", cadence_days=2),
        ACCOUNT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value)


def test_a_limit_of_zero_is_invalid_pagination(api):
    """PRD 2.3: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100; `offset`
    defaults to 0 and has a minimum of 0. A `limit` outside the inclusive range from 1 to
    100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID` (HTTP 400)."

    Design: Corner/errors/err_pagination_invalid_for_zero_limit_returns_400
    """
    set_clock("2026-06-01T00:00:00Z")
    new_owner(full_name="Pag Owner", primary_residence_state="MN")
    response = api.list_owners(headers=AUDITOR, params={"limit": 0})
    validate_error(response, ApiErrorId.ERR_PAGINATION_INVALID.value)


# --------------------------------------------------------------------------
# The logical clock
# --------------------------------------------------------------------------

def test_the_clock_starts_at_the_declared_default(api):
    """PRD 2.5: "Before any call that sets it, the clock reads exactly
    `2026-05-01T00:00:00Z`, and it never falls back to real time."
    PRD 2.5: "A read-only capability returns the current value as `current_utc` without
    changing it."

    Design: Corner/endpoints/clock_default_is_may_first_2026_before_any_set_call
    """
    data = validate_success(api.get_clock(PLATFORM_ADMIN))
    assert_same_instant(data["current_utc"], "2026-05-01T00:00:00Z", "current_utc")


def test_setting_the_clock_backwards_is_a_regression(api):
    """PRD 2.5: "The clock is monotonic: an attempt to set it to an instant strictly
    earlier than its current value is rejected with `ERR_CLOCK_REGRESSION` (HTTP 400)."

    Design: Corner/errors/err_clock_regression_on_backwards_set_returns_400
    """
    set_clock("2026-06-10T00:00:00Z")
    response = api.set_clock({"to_iso8601": "2026-06-09T23:59:59Z"}, PLATFORM_ADMIN)
    validate_error(response, ApiErrorId.ERR_CLOCK_REGRESSION.value)
    assert_same_instant(read_clock(), "2026-06-10T00:00:00Z", "current_utc after the rejection")


# --------------------------------------------------------------------------
# Immediate consistency and optimistic concurrency
# --------------------------------------------------------------------------

def test_the_patch_response_already_carries_the_recomputed_derived_fields(api):
    """PRD 2.4: "**The response body carries post-mutation values.** Whatever a mutation
    writes — including the version bump, the refreshed `updated_at`, and every derived
    field re-computed as a consequence — is reflected in the resource object returned in
    `data`."
    PRD 3.1: "`travel_zone` is derived from `travel_distance_miles` whenever that distance
    is written, at registration and again on revision, and every comparison is inclusive at
    the upper edge."

    Design: Corner/consistency_model/immediate_consistency_version_visible_in_the_mutating_response
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = new_owner(full_name="Imm Ver", primary_residence_state="MN")
    prop = new_property(owner["id"], label="Imm House", address_line="8 Near Nook",
                        travel_distance_miles=8.0)
    assert prop["version"] == 1
    assert prop["travel_zone"] == "Z1"

    patched = validate_success(
        api.update_property(prop["id"], {"travel_distance_miles": 45.0}, DISPATCHER)
    )
    assert patched["version"] == 2
    assert patched["travel_zone"] == "Z3"

    reread = validate_success(api.get_property(prop["id"], AUDITOR))
    assert reread["version"] == 2
    assert reread["travel_zone"] == "Z3"
    assert reread["travel_distance_miles"] == 45.0


def test_a_second_tier_change_replaying_the_stale_version_is_rejected(api):
    """PRD 2.10: "**Scheduling a plan tier change** requires `expected_subscription_version`
    carrying the client's last observed `version` of that `Subscription`. A mismatch is
    rejected with `ERR_STALE_SUBSCRIPTION_VERSION` and HTTP 412."
    PRD 2.10: "On success the subscription's `version` increments by exactly one for the
    request — not once per affected field and not once per cascade hop into the billing
    cycle — and the mutated subscription returned in `data` carries that post-mutation
    value."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_subscription_version_on_second_tier_change_returns_412
    """
    ctx = setup_subscribed_property(plan_overrides=STANDARD)
    premium = new_service_plan(tier="PREMIUM", monthly_fee_cents=34944, included_visit_units=8,
                               covered_visit_types=["ROUTINE_WATCH"],
                               entitlement_rollover_policy="CARRY_CAPPED",
                               storm_guarantee_included=True)
    basic = new_service_plan(tier="BASIC", monthly_fee_cents=9986, included_visit_units=3,
                             covered_visit_types=["ROUTINE_WATCH"])
    stale_version = refresh_subscription(ctx["subscription_id"])["version"]

    changed = validate_success(api.tier_changes_subscription(
        ctx["subscription_id"],
        {"service_plan_id": premium["id"], "expected_subscription_version": stale_version},
        ACCOUNT_MANAGER,
    ))
    assert changed["version"] == stale_version + 1

    response = api.tier_changes_subscription(
        ctx["subscription_id"],
        {"service_plan_id": basic["id"], "expected_subscription_version": stale_version},
        ACCOUNT_MANAGER,
    )
    assert response.status_code == 412, f"expected 412, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_STALE_SUBSCRIPTION_VERSION.value)

    subscription = refresh_subscription(ctx["subscription_id"])
    assert subscription["service_plan_id"] == premium["id"]
    assert subscription["version"] == stale_version + 1
    cycle = refresh_cycle(ctx["cycle_id"])
    assert cycle["entitlement_granted_units"] == 8
    assert cycle["entitlement_remaining_units"] == 8
