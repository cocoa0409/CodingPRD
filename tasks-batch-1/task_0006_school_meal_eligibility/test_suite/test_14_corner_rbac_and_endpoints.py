"""Tests covering RBAC denials beyond §1.8 (SchoolStaff cannot approve;
DistrictReviewer cannot verify; Parent cannot set the clock) plus endpoint
corners (idempotent topup replay, pagination meta, filtered listing,
ledger-entry FK filter, auto-renewal sweep).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    set_clock,
    setup_clean_world,
    create_household,
    create_student,
    create_direct_cert_eligibility,
    create_application,
    submit_application,
    start_review,
    create_menu_item,
    create_service_transaction,
    settle_transaction,
    refund_transaction,
    topup_account,
    resolve_parent_account_id,
    advance_clock_and_expire,
    setup_approved_application,
    api_client,
    TEST_USERS,
    make_parent_headers,
)


# ---------------------------------------------------------------------
# Corner / rbac
# ---------------------------------------------------------------------

def test_school_staff_cannot_approve_application(api):
    """PRD §4 endpoint table: "POST `/school-meals/applications/{id}/approve`
    | Approve an `UNDER_REVIEW` application; cascades to determination and
    pending transactions. | `DistrictReviewer`".
    PRD §2.1: "If the role is recognized but is not on the endpoint's
    allow-list, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/rbac_school_staff_cannot_approve_application
    """
    setup_clean_world()
    hh = create_household()
    app = create_application(hh["id"])
    submit_application(app["id"], hh["id"])
    start_review(app["id"])
    res = api.approve_application(
        app["id"], {"decision_reason": "approving as staff"},
        TEST_USERS["school_staff_headers"],
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_district_reviewer_cannot_verify_determination(api):
    """PRD §4 endpoint table: "POST
    `/school-meals/eligibility-determinations/{id}/verify` | Auditor sets
    verification status to verified. | `USDAAuditor`".
    PRD §2.1: "If the role is recognized but is not on the endpoint's
    allow-list, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/rbac_district_reviewer_cannot_verify_determination
    """
    set_clock("2026-06-15T09:00:00.000Z")
    hh = create_household(direct_certification_flag=True)
    elig = create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-06-15T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    res = api.verify_eligibility_determination(
        elig["id"], TEST_USERS["district_reviewer_headers"]
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_parent_cannot_set_clock(api):
    """PRD §2.1: "`PlatformAdmin` is restricted to the administrative
    test-driving endpoints under `/_clock/` and `/_renewal/`; the other
    operator roles never invoke those endpoints."
    PRD §4 endpoint table: "POST `/school-meals/_clock/set_current_utc` |
    Pin the server clock to a supplied UTC instant. | `PlatformAdmin`".

    Design: Corner/rbac/rbac_parent_cannot_set_clock
    """
    setup_clean_world()
    hh = create_household()
    res = api.set_clock("2026-06-16T00:00:00.000Z", make_parent_headers(hh["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ---------------------------------------------------------------------
# Corner / endpoints
# ---------------------------------------------------------------------

def test_idempotent_topup_replay_returns_original_entry_no_new_ledger_row(api):
    """PRD §3.6: "The `idempotency_key` is required on every top-up and must
    be unique within the account's history. If a parent re-submits a top-up
    with the same `idempotency_key` and the same `amount_cents` as a prior
    successful top-up, the server returns the prior `LedgerEntry` (with the
    original 200/201-class response body) and creates no new entry."

    Design: Corner/endpoints/idempotent_topup_returns_original_entry_on_replay
    """
    set_clock("2026-06-20T09:00:00.000Z")
    hh = create_household()
    pa_id = resolve_parent_account_id(hh["id"])
    first = api.topup_parent_account(
        pa_id,
        {"amount_cents": 5000, "idempotency_key": "idem-1"},
        make_parent_headers(hh["id"]),
    )
    first_data = validate_success(first, 201)
    entry1_id = first_data["id"]
    # Replay with SAME key + SAME amount.
    second = api.topup_parent_account(
        pa_id,
        {"amount_cents": 5000, "idempotency_key": "idem-1"},
        make_parent_headers(hh["id"]),
    )
    # PRD says "original 200/201-class response body" — accept either status.
    assert 200 <= second.status_code < 300, (
        f"idempotent replay must be 2xx; got HTTP {second.status_code}: {second.text}"
    )
    second_body = second.json()
    second_id = second_body.get("data", {}).get("id")
    assert second_id == entry1_id, (
        f"replay must return ORIGINAL LedgerEntry id; "
        f"first={entry1_id!r}, second={second_id!r}"
    )
    # And the balance must not be doubled.
    balance_res = api.get_parent_account(pa_id, make_parent_headers(hh["id"]))
    balance = validate_success(balance_res, 200)
    assert balance["balance_cents"] == 5000, (
        f"balance after idempotent replay must remain 5000 (not 10000); "
        f"got {balance['balance_cents']}"
    )


def test_list_households_returns_pagination_meta_fields(api):
    """PRD §2.3: "The `meta` block on a list response echoes the effective
    `limit` and `offset` alongside `total_count` (the unpaginated row count
    matching the request's filters) and `has_more` (true when
    `offset + limit < total_count`)."

    Design: Corner/endpoints/listing_pagination_meta_fields_present
    """
    setup_clean_world()
    for i in range(3):
        create_household(family_size=i + 1)
    res = api.list_households(
        TEST_USERS["school_staff_headers"], params={"limit": 2, "offset": 0}
    )
    data_list, meta = validate_paginated(res)
    assert len(data_list) == 2, (
        f"limit=2 must cap data array at 2; got {len(data_list)}"
    )
    assert meta.get("total_count") == 3, (
        f"total_count must equal unpaginated row count (3); got {meta.get('total_count')}"
    )
    assert meta.get("has_more") is True, (
        f"has_more must be true when offset + limit < total_count; got {meta.get('has_more')}"
    )


def test_household_eligibility_determinations_nested_read_returns_only_that_household(api):
    """PRD §2.8: "The collection returned by a nested read is filtered to
    children of the resolved parent and paginated under the §2.3 rules."

    Design: Corner/endpoints/filtered_list_eligibility_by_household_returns_only_that_household
    """
    set_clock("2026-06-25T09:00:00.000Z")
    hh_a = create_household(direct_certification_flag=True)
    hh_b = create_household(direct_certification_flag=True)
    elig_a = create_direct_cert_eligibility(
        hh_a["id"], tier="FREE",
        valid_from_utc="2026-06-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    create_direct_cert_eligibility(
        hh_b["id"], tier="FREE",
        valid_from_utc="2026-06-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    res = api.list_household_eligibility_determinations(
        hh_a["id"], TEST_USERS["school_staff_headers"]
    )
    data = validate_success(res, 200)
    rows = data if isinstance(data, list) else data.get("data", data)
    assert len(rows) == 1, (
        f"nested read for hh_a must return exactly the 1 determination of hh_a; "
        f"got {len(rows)}"
    )
    assert rows[0]["id"] == elig_a["id"], (
        f"returned determination must be hh_a's (id={elig_a['id']!r}); "
        f"got id={rows[0]['id']!r}"
    )


def test_ledger_entries_filter_by_linked_transaction_id_returns_charge_and_refund_pair(api):
    """PRD §2.9: "A `MEAL_CHARGE` or `MEAL_REFUND` carries the originating
    transaction's id in `linked_transaction_id`; other entry types leave
    `linked_transaction_id` null."
    PRD §3.6: "On success the server creates a `LedgerEntry` with
    `entry_type` `MEAL_CHARGE`, `amount_cents` equal to the negative of
    `paid_charge_cents`, and `linked_transaction_id` set to the
    transaction's id".
    PRD §3.6: "On success the server creates a compensating `LedgerEntry`
    with `entry_type` `MEAL_REFUND`, `amount_cents` equal to the positive
    `paid_charge_cents`, and the same `linked_transaction_id`".

    Design: Corner/endpoints/ledger_filter_by_linked_transaction_id_returns_pair
    """
    set_clock("2026-06-26T09:00:00.000Z")
    hh, stu, _ = setup_approved_application(
        clock_iso="2026-06-26T09:00:00.000Z",
        family_size=4, annual_income_cents=8_000_000,
        address_state="CA",
        decision_reason="PAID",
        direct_certification_flag=False,
    )
    topup_account(hh["id"], 1000, idempotency_key="lf-1")
    menu = create_menu_item(
        school_code="ELEM-101", name="Burger", list_price_cents=300,
    )
    tx = create_service_transaction(stu["id"], menu["id"])
    settled = settle_transaction(tx["id"])
    refund_transaction(settled["id"], settled["version"])

    res = api.list_ledger_entries(
        TEST_USERS["school_staff_headers"],
        params={"linked_transaction_id": tx["id"]},
    )
    data = validate_success(res, 200)
    rows = data if isinstance(data, list) else data.get("data", data)
    assert len(rows) == 2, (
        f"must return both MEAL_CHARGE and MEAL_REFUND linked to tx; "
        f"got {len(rows)}"
    )
    for r in rows:
        assert r["linked_transaction_id"] == tx["id"], (
            f"all returned entries must link to tx; got {r['linked_transaction_id']!r}"
        )


def test_auto_renewal_creates_auto_renewal_determination_carrying_prior_tier(api):
    """PRD §3.8: "The auto-renewal sweep operates over a `school_year`, a
    `valid_from_utc`, and a `valid_to_utc`. For every household that held an
    `ACTIVE` or `SUPERSEDED` determination in the prior school year and that
    has no `DENIED` `MealApplication` in the supplied `school_year`, the
    server creates a new `EligibilityDetermination` with `source`
    `AUTO_RENEWAL`, the most recent prior tier carried forward, and the
    supplied window."

    Design: Corner/endpoints/auto_renewal_creates_new_determinations_for_returning_households
    """
    set_clock("2026-06-15T00:00:00.000Z")
    hh = create_household(direct_certification_flag=True)
    create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-01-01T00:00:00.000Z",
        valid_to_utc="2026-06-30T00:00:00.000Z",
    )
    # Expire the prior determination at end of school year.
    advance_clock_and_expire("2026-07-01T00:00:00.000Z")
    set_clock("2026-08-01T00:00:00.000Z")
    res = api.run_auto_renewal(
        {
            "school_year": "2026-2027",
            "valid_from_utc": "2026-08-01T00:00:00.000Z",
            "valid_to_utc": "2027-06-30T00:00:00.000Z",
        },
        TEST_USERS["platform_admin_headers"],
    )
    validate_success(res, 200)
    # Confirm an AUTO_RENEWAL determination exists for the household with FREE.
    res2 = api.list_household_eligibility_determinations(
        hh["id"],
        TEST_USERS["school_staff_headers"],
        params={"lifecycle_status": "ACTIVE"},
    )
    data2 = validate_success(res2, 200)
    rows2 = data2 if isinstance(data2, list) else data2.get("data", data2)
    auto_renewals = [
        r for r in rows2
        if r["source"] == "AUTO_RENEWAL" and r["tier"] == "FREE"
    ]
    assert len(auto_renewals) >= 1, (
        f"expected at least one ACTIVE AUTO_RENEWAL FREE determination for the "
        f"returning household; got {len(auto_renewals)} from rows={rows2!r}"
    )
