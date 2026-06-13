"""FK reverse-lookup reads, RBAC denials, optimistic-concurrency, and immediate
consistency corners (PRD §2.1, §2.6, §3.1, §3.3, §3.4, §3.5, §3.10).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    setup_active_subscription,
    setup_active_subscription_with_payment_plan,
    setup_pending_subscription,
    create_section,
    create_seat,
    create_account,
    create_season_plan,
    create_subscription,
    create_seat_assignment,
    make_account_holder_headers,
    TEST_USERS,
)

_BOX = TEST_USERS["box_office_headers"]
_FIN = TEST_USERS["finance_headers"]


# =========================================================================
# Endpoints — FK reverse lookups
# =========================================================================
def test_list_section_seats_returns_only_its_seats(api):
    """PRD §3.1: "Seats may be listed beneath their section as a reverse lookup on
    `section_id`."

    Two seats added to a section both appear under its reverse lookup.

    Design: Corner/endpoints/list_seats_by_section_fk_reverse_lookup
    """
    section = create_section(name="Lower 450")
    create_seat(section["id"], row_label="A", seat_number=1)
    create_seat(section["id"], row_label="A", seat_number=2)
    resp = api.list_section_seats(section["id"], _BOX)
    data, _meta = validate_paginated(resp)
    assert len(data) == 2, len(data)
    assert all(s["section_id"] == section["id"] for s in data), data


def test_list_installments_under_plan(api):
    """PRD §3.10: "Installments may be listed beneath their plan and fetched
    individually."

    A 4-installment plan returns 4 rows under its reverse lookup.

    Design: Corner/endpoints/list_installments_under_payment_plan_fk_reverse_lookup
    """
    ctx = setup_active_subscription_with_payment_plan(installment_count=4, base_price_cents=200000)
    resp = api.list_payment_plan_installments(ctx["payment_plan"]["id"], _FIN)
    data, _meta = validate_paginated(resp)
    assert len(data) == 4, len(data)


def test_list_seat_assignments_filtered_by_seat(api):
    """PRD §3.4: "Assignments may be listed globally with filters on
    `subscription_id`, `seat_id`, and `status`."

    Filtering seat-assignments by seat_id returns the single assignment on that seat.

    Design: Corner/endpoints/list_seat_assignments_filtered_by_seat_fk_reverse_lookup
    """
    section = create_section(name="Lower 470")
    seat = create_seat(section["id"], row_label="A", seat_number=1)
    plan = create_season_plan(plan_type="FULL", price_multiplier_bps=10000)
    account = create_account(full_name="Filt Holder")
    sub = create_subscription(account["id"], plan["id"])
    assignment = create_seat_assignment(sub["id"], seat["id"])
    resp = api.list_seat_assignments(_BOX, params={"seat_id": seat["id"]})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, len(data)
    assert data[0]["id"] == assignment["id"], data


# =========================================================================
# RBAC
# =========================================================================
def test_finance_clerk_cannot_create_subscription(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation under the access matrix, the request is
    rejected with `ERR_FORBIDDEN`."
    PRD §2.1: "A `BoxOfficeAgent` is the inventory and administrative operator: it ...
    creates subscriptions and drives their lifecycle."

    A FinanceClerk attempting POST /subscriptions is forbidden.

    Design: Corner/rbac/financeclerk_cannot_create_subscription_forbidden
    """
    plan = create_season_plan(plan_type="FULL", price_multiplier_bps=10000)
    account = create_account(full_name="RBAC Holder")
    resp = api.create_subscription({"account_id": account["id"], "season_plan_id": plan["id"]}, _FIN)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name one
    of these three known roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.create_section({"name": "NoAuth", "tier": "STANDARD", "base_price_cents": 200000}, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# =========================================================================
# Optimistic concurrency
# =========================================================================
def test_relocate_begin_with_correct_version_succeeds_and_bumps(api):
    """PRD §3.5: "Beginning a relocation is legal only while the subscription is
    `ACTIVE`, requires the supplied `expected_subscription_version` to match the
    subscription's current `version` per §2.6, and moves the subscription from
    `ACTIVE` to `RELOCATING` while incrementing its `version`; no seats change yet."

    relocate-begin with the matching version moves to RELOCATING and version++.

    Design: Corner/cross_cutting_complexity_layers/relocate_begin_correct_version_succeeds_and_bumps
    """
    ctx = setup_active_subscription(base_price_cents=200000, section_name="OCC Sec")
    v_active = ctx["subscription"]["version"]
    resp = api.relocate_subscription(ctx["subscription"]["id"], {"expected_subscription_version": v_active}, _BOX)
    sub = validate_success(resp)
    assert sub["status"] == "RELOCATING", sub["status"]
    assert sub["version"] == v_active + 1, (sub["version"], v_active)


def test_renewal_accept_stale_version_rejected(api):
    """PRD §2.6: "Accepting a renewal offer likewise requires
    `expected_subscription_version` to match the subscription's current `version`;
    the price the holder was shown was computed against an earlier version, so if a
    re-priced offer has since advanced the version, the stale acceptance is rejected
    with `ERR_STALE_SUBSCRIPTION_VERSION` at HTTP 412."
    PRD §3.3: "which moves it from `ACTIVE` to `RENEWAL_OFFERED` and increments its
    `version`."

    The offer bumped the version; accepting with the pre-offer version is stale.

    Design: Corner/cross_cutting_complexity_layers/renewal_accept_stale_version_rejected
    """
    ctx = setup_active_subscription(base_price_cents=200000, section_name="Renew Sec")
    sub_id = ctx["subscription"]["id"]
    v_active = ctx["subscription"]["version"]
    validate_success(api.offer_renewal(sub_id, _BOX))  # bumps version beyond v_active
    holder_headers = make_account_holder_headers(ctx["account"]["id"])
    resp = api.accept_renewal(sub_id, {"expected_subscription_version": v_active}, holder_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_SUBSCRIPTION_VERSION.value)


# =========================================================================
# Consistency model — immediate
# =========================================================================
def test_activation_response_reflects_price_and_counts(api):
    """PRD §3.3: "activation moves the subscription to `ACTIVE`. As part of activation
    the system prices the seats and accrues loyalty points ... sets `seat_count` to
    the number of `ASSIGNED` assignments, and sets `locked_price_cents` to the priced
    season total."
    PRD §3.7: "for a `FULL` plan whose multiplier is 10000 this equals the full base
    price."

    The activate response itself already shows ACTIVE, locked_price_cents=200000,
    and seat_count=1 (immediate consistency).

    Design: Corner/consistency_model/activation_side_effects_visible_in_same_response
    """
    ctx = setup_pending_subscription(base_price_cents=200000, plan_type="FULL",
                                     price_multiplier_bps=10000, section_name="Imm Sec")
    resp = api.activate_subscription(ctx["subscription"]["id"], _BOX)
    sub = validate_success(resp)
    assert sub["status"] == "ACTIVE", sub["status"]
    assert sub["locked_price_cents"] == 200000, sub["locked_price_cents"]
    assert sub["seat_count"] == 1, sub["seat_count"]
