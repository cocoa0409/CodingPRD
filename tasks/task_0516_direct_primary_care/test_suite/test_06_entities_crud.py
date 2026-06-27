"""Entity creation, retrieval, defaults, computed fields, immutability, and
listing/pagination. PRD §2.3, §2.4, §3.1, §3.3, §3.5.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, assert_practice, assert_member, assert_provider,
    assert_payment, NON_EXISTENT_UUID, ApiErrorId,
    create_practice, create_provider, register_member,
    setup_active_member, make_member_headers, make_provider_headers,
    register_member_payload, create_visit_slot_payload, set_clock, ADMIN, ANON,
)


def test_create_practice_returns_201_with_all_fields(api):
    """PRD §2.4: "The `version` is an integer that starts at its initial value when
    the resource is created and increments by one on each mutation."
    PRD §3.1: "A practice is created with a display `name`, a soft `panel_target`
    and a hard `panel_hard_cap` that govern panel sizing, the standard individual
    `monthly_fee_cents`."

    Design: Corner/entities/create_practice_returns_201_with_all_fields
    """
    from test_helpers import create_practice_payload
    res = api_client.create_practice(
        create_practice_payload(name="P1", monthly_fee_cents=15000), ADMIN)
    practice = validate_success(res, 201)
    assert_practice(practice)
    assert practice["monthly_fee_cents"] == 15000
    assert practice["version"] == 1


def test_get_member_not_found_returns_404(api):
    """PRD §3.14: "Existence is then checked: every path or body identifier must
    resolve to an existing resource, validated left-to-right in the path, failing
    with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    res = api_client.get_member(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_register_member_missing_email_returns_invalid_request(api):
    """PRD §3.3: "The caller supplies the `practice_id`, a contact `email` that must
    be unique within the practice, the member's `full_name`."
    PRD §3.14: "Request well-formedness follows: required body fields must be
    present and well-typed and enum values must lie within their declared domains,
    failing with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/register_member_missing_required_field_returns_invalid_request
    """
    practice = create_practice(name="P2")
    res = api_client.register_member(
        {"practice_id": practice["id"], "full_name": "No Email"}, ANON)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_register_member_default_plan_type_monthly(api):
    """PRD §3.3: "an optional `plan_type` that defaults to `MONTHLY`, and an optional
    `has_insurance` flag that defaults to false."
    PRD §3.3: "Registration creates the `Member` in `PENDING_PAYMENT` status
    together with its 1:1 `Membership` in a single call."

    Design: Corner/entities/register_member_default_plan_type_monthly_applied
    """
    practice = create_practice(name="P3")
    member = validate_success(api_client.register_member(
        register_member_payload(practice["id"], "def@x.com"), ANON), 201)
    assert member["plan_type"] == "MONTHLY"
    assert member["membership_status"] == "PENDING_PAYMENT"


def test_provider_panel_fields_computed_start_zero(api):
    """PRD §3.1: "At registration a provider's computed `active_panel_count` is
    initialized to zero and its computed `panel_load_bucket` is initialized to
    `UNDER_TARGET`."

    Design: Corner/entities/provider_active_panel_count_computed_starts_zero
    """
    practice = create_practice(name="P4")
    provider = validate_success(api_client.create_provider(
        {"practice_id": practice["id"], "full_name": "Dr Z", "npi": "2000000001"}, ADMIN), 201)
    assert provider["active_panel_count"] == 0
    assert provider["panel_load_bucket"] == "UNDER_TARGET"


def test_create_visit_slot_invalid_interval_returns_validation(api):
    """PRD §3.5: "The `ends_at` must be strictly after `starts_at`; a slot whose
    `ends_at` is at or before `starts_at` is rejected with `ERR_VALIDATION`."

    Design: Corner/entities/create_visit_slot_invalid_interval_returns_validation
    """
    practice = create_practice(name="P5")
    provider = create_provider(practice["id"], full_name="Dr Y", npi="2000000002")
    res = api_client.create_visit_slot(
        provider["id"],
        create_visit_slot_payload("IN_PERSON", "2026-06-05T10:00:00Z", "2026-06-05T10:00:00Z"),
        make_provider_headers(provider["id"]))
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


def test_payment_is_immutable_no_version_field(api):
    """PRD §2.4: "`Payment` is the single exception. A payment is an immutable
    record of a charge attempt and therefore carries only `id` and `created_at`; it
    has neither an `updated_at` nor a `version` field, because once written it is
    never modified."

    Design: Corner/entities/payment_is_immutable_no_version_field
    """
    # The activating charge in setup_active_member produces a SUCCEEDED membership
    # Payment; fetch it via reverse-reachability and assert its shape.
    ctx = setup_active_member()
    member_h = make_member_headers(ctx["member"]["id"])
    data = get_success_data(api_client.list_payments(
        member_h, params={"member_id": ctx["member"]["id"]}))
    rows = data if isinstance(data, list) else data.get("data", data)
    payment = rows[0]
    assert_payment(payment)
    assert payment["charge_kind"] == "MEMBERSHIP_FEE"
    assert payment["outcome"] == "SUCCEEDED"
    assert "version" not in payment


def test_provider_member_panel_reverse_list(api):
    """PRD §3.3: "Assignment sets the member's `assigned_provider_id`; if the member
    is already `ACTIVE` or `PAST_DUE`, the selected provider's `active_panel_count`
    and `panel_load_bucket` are recomputed to reflect the new panel member."
    PRD §4: "List the members on a provider's panel."

    Design: Corner/entities/provider_member_panel_fk_reverse_list
    """
    practice = create_practice(name="P7")
    provider = create_provider(practice["id"], full_name="Dr W", npi="2000000004")
    member = register_member(practice["id"], email="panel@x.com")
    from test_helpers import assign_pcp_manual
    assign_pcp_manual(member["id"], provider["id"])
    data, meta = validate_paginated(api_client.list_provider_members(
        provider["id"], make_provider_headers(provider["id"])))
    assert meta["total_count"] == 1
    assert any(m["id"] == member["id"] for m in data)


def test_list_members_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is the
    count of all matching resources before pagination and `has_more` indicates
    whether further pages remain."

    Design: Corner/entities/list_members_pagination_envelope
    """
    practice = create_practice(name="P8")
    set_clock("2026-06-01T00:00:00Z")
    register_member(practice["id"], email="l1@x.com")
    register_member(practice["id"], email="l2@x.com")
    data, meta = validate_paginated(api_client.list_members(
        ADMIN, params={"practice_id": practice["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
