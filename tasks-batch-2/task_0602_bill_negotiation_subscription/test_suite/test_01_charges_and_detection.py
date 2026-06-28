"""Recurring-charge detection, annualization, and charge lifecycle."""
from test_helpers import (
    api_client,
    validate_success, validate_error,
    make_member_headers, make_admin_headers,
    create_member, setup_member_with_linked_account,
    setup_detected_charge, setup_confirmed_charge,
    create_recurring_charge_payload, create_linked_account_payload,
    ApiErrorId,
)


def test_create_member_returns_all_fields(api):
    """PRD §3.1: "If omitted it defaults to 0.40. This `success_fee_pct` is a contract and display hint only ... A new member's `status` is `ACTIVE`."
    PRD §3.1: "The two computed lifetime fields a member carries — `lifetime_gross_savings_cents` and `lifetime_member_savings_cents` — both start at zero"

    Design: Corner/entities/create_member_returns_all_fields_201
    """
    resp = api.create_member({"email": "c1@x.com", "full_name": "C1"})
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"
    assert data["success_fee_pct"] == 0.40
    assert data["lifetime_gross_savings_cents"] == 0
    assert data["version"] == 1


def test_get_member_not_found(api):
    """PRD §2.8: "When a request targets a resource by `{id}` in the URL and that resource does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_member_not_found
    """
    member = create_member()
    resp = api.get_member("00000000-0000-0000-0000-000000000000",
                          headers=make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_charge_missing_amount_rejected(api):
    """PRD §2.9: "then presence, typing, and enum-membership of required body fields (`ERR_INVALID_REQUEST`)".
    PRD §3.2: "Ingestion supplies the `linked_account_id`, a normalized `merchant_name`, the per-cycle `amount_cents` (which must be at least 1, else `ERR_VALUE_OUT_OF_RANGE`), a `cadence`, an optional `category`, and the `first_seen_utc` timestamp".

    Design: Corner/entities/create_recurring_charge_missing_required_field
    """
    member, la = setup_member_with_linked_account()
    resp = api.create_recurring_charge(
        {"linked_account_id": la["id"], "merchant_name": "X",
         "cadence": "MONTHLY", "first_seen_utc": "2026-01-01T00:00:00Z"},
        headers=make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_charge_invalid_cadence_enum_rejected(api):
    """PRD §3.2: "The `cadence` is one of `MONTHLY`, `ANNUAL`, or `WEEKLY`."
    PRD §2.9: "then presence, typing, and enum-membership of required body fields (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/create_recurring_charge_invalid_enum_cadence
    """
    member, la = setup_member_with_linked_account()
    resp = api.create_recurring_charge(
        {"linked_account_id": la["id"], "merchant_name": "X", "amount_cents": 1000,
         "cadence": "DAILY", "first_seen_utc": "2026-01-01T00:00:00Z"},
        headers=make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_charge_amount_below_min_out_of_range(api):
    """PRD §3.2: "the per-cycle `amount_cents` (which must be at least 1, else `ERR_VALUE_OUT_OF_RANGE`)".

    Design: Corner/entities/charge_amount_below_min_range
    """
    member, la = setup_member_with_linked_account()
    resp = api.create_recurring_charge(
        {"linked_account_id": la["id"], "merchant_name": "X", "amount_cents": 0,
         "cadence": "MONTHLY", "first_seen_utc": "2026-01-01T00:00:00Z"},
        headers=make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value)


def test_charge_default_category_other(api):
    """PRD §3.2: "The `category` is one of `STREAMING`, `TELECOM`, `INSURANCE`, `UTILITY`, `SOFTWARE`, or `OTHER`, defaulting to `OTHER` when omitted. A newly ingested charge has `status` `DETECTED".

    Design: Corner/entities/charge_default_category_other_applied
    """
    member, la = setup_member_with_linked_account()
    resp = api.create_recurring_charge(
        {"linked_account_id": la["id"], "merchant_name": "X", "amount_cents": 1000,
         "cadence": "MONTHLY", "first_seen_utc": "2026-01-01T00:00:00Z"},
        headers=make_member_headers(member["id"]),
    )
    data = validate_success(resp, 201)
    assert data["category"] == "OTHER"
    assert data["status"] == "DETECTED"


def test_annualize_weekly_charge_uses_52(api):
    """PRD §3.2: "a `WEEKLY` charge annualizes to its amount multiplied by fifty-two weeks per year. The weekly case uses exactly fifty-two weeks — not the number of weeks implied by dividing 365 days by 7".

    Design: Corner/entities/annualize_weekly_charge_computed
    """
    member, la = setup_member_with_linked_account()
    resp = api.create_recurring_charge(
        {"linked_account_id": la["id"], "merchant_name": "GymCo", "amount_cents": 1000,
         "cadence": "WEEKLY", "category": "OTHER", "first_seen_utc": "2026-01-01T00:00:00Z"},
        headers=make_member_headers(member["id"]),
    )
    data = validate_success(resp, 201)
    assert data["annualized_cost_cents"] == 52000


def test_list_charges_pagination_envelope(api):
    """PRD §2.3: "the `meta` object carries the pagination fields `limit`, `offset`, `total_count` (the total number of records matching the query before pagination), and `has_more` (a boolean that is true when records remain beyond the current page)."

    Design: Corner/entities/listing_pagination_envelope
    """
    member, la = setup_member_with_linked_account()
    for m in ("A", "B"):
        api.create_recurring_charge(
            create_recurring_charge_payload(la["id"], merchant_name=m, amount_cents=1000),
            headers=make_member_headers(member["id"]),
        )
    resp = api.list_recurring_charges(
        headers=make_member_headers(member["id"]), params={"linked_account_id": la["id"]}
    )
    validate_success(resp)
    meta = resp.json()["meta"]
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_system_fields_ignored_on_member_create(api):
    """PRD §2.4: "The server assigns it; clients never supply it."
    PRD §3.1: "A new member's `status` is `ACTIVE`."
    PRD §3.1: "The two computed lifetime fields a member carries ... both start at zero"

    Design: Corner/entities/system_fields_ignored_on_create
    """
    resp = api.create_member({"email": "c9@x.com", "full_name": "C9","status": "SUSPENDED", "lifetime_member_savings_cents": 999})
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"
    assert data["lifetime_member_savings_cents"] == 0


def test_detected_charge_count_after_two_ingests(api):
    """PRD §3.2: "Each linked account tracks a computed `detected_charge_count` — the number of recurring charges detected on it whose status is not `DISMISSED` — beginning at zero."

    Design: Corner/cross_cutting_complexity_layers/detected_charge_count_derived_after_detect
    """
    member, la = setup_member_with_linked_account()
    for m in ("A", "B"):
        api.create_recurring_charge(
            create_recurring_charge_payload(la["id"], merchant_name=m, amount_cents=1000),
            headers=make_member_headers(member["id"]),
        )
    resp = api.get_linked_account(la["id"], headers=make_member_headers(member["id"]))
    data = validate_success(resp)
    assert data["detected_charge_count"] == 2


# --- Charge lifecycle (state machine) ---

def test_confirm_already_confirmed_invalid_state(api):
    """PRD §2.6: "State-changing operations advance a resource from one named status to another only when the resource is currently in an allowed source state; an attempt from a disallowed state is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/confirm_already_confirmed_charge_invalid_state
    """
    member, la, charge = setup_confirmed_charge(amount_cents=1000)
    resp = api.confirm_recurring_charge(charge["id"], headers=make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_confirm_dismissed_terminal_charge_invalid_state(api):
    """PRD §3.2: "Dismissal advances `status` to `DISMISSED ... DISMISSED` is terminal."
    PRD §2.6: "an attempt from a disallowed state is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/terminal_dismissed_charge_no_transitions
    """
    member, la, charge = setup_detected_charge(amount_cents=1000)
    api.dismiss_recurring_charge(charge["id"], headers=make_member_headers(member["id"]))
    resp = api.confirm_recurring_charge(charge["id"], headers=make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_confirm_requires_linked_account_linked(api):
    """PRD §3.2: "Confirmation is permitted only when the charge is currently `DETECTED` and the linked account it sits on is still `LINKED`; if the linked account is not `LINKED` the confirmation is rejected with `ERR_LINKED_RESOURCE_STATE`."

    Design: Difficulty/cross_entity_state_dependency/confirm_charge_requires_linked_account_linked
    """
    member, la, charge = setup_detected_charge(amount_cents=5000)
    api.unlink_account(la["id"], headers=make_member_headers(member["id"]))
    resp = api.confirm_recurring_charge(charge["id"], headers=make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_LINKED_RESOURCE_STATE.value)
    after = validate_success(api.get_recurring_charge(charge["id"],
                                                      headers=make_member_headers(member["id"])))
    assert after["status"] == "DETECTED"


def test_confirm_blocked_account_leaves_charge_detected(api):
    """PRD §3.2: "if the linked account is not `LINKED` the confirmation is rejected with `ERR_LINKED_RESOURCE_STATE`."
    PRD §2.6: "an attempt from a disallowed state is rejected" (no state change on reject).

    Design: Difficulty/cross_entity_state_dependency/confirm_charge_requires_linked_account_linked
    """
    member, la, charge = setup_detected_charge(amount_cents=1500)
    api.unlink_account(la["id"], headers=make_member_headers(member["id"]))
    api.confirm_recurring_charge(charge["id"], headers=make_member_headers(member["id"]))
    after = validate_success(api.get_recurring_charge(charge["id"],
                                                      headers=make_member_headers(member["id"])))
    assert after["status"] == "DETECTED"


def test_detect_then_dismiss_conserves_count(api):
    """PRD §3.2: "ingestion increments the owning linked account's `detected_charge_count` by one."
    PRD §3.2: "Dismissal advances `status` to `DISMISSED` and decrements the owning linked account's `detected_charge_count` by one."

    Design: Difficulty/compensating_invariant/detect_then_dismiss_conserves_detected_charge_count
    """
    member, la, charge = setup_detected_charge(amount_cents=5000)
    resp = api.dismiss_recurring_charge(charge["id"], headers=make_member_headers(member["id"]))
    data = validate_success(resp)
    assert data["status"] == "DISMISSED"
    after = validate_success(api.get_linked_account(la["id"],
                                                    headers=make_member_headers(member["id"])))
    assert after["detected_charge_count"] == 0


def test_dismiss_after_detect_returns_to_zero_count(api):
    """PRD §3.2: "A newly ingested charge has `status` `DETECTED`, and ingestion increments the owning linked account's `detected_charge_count` by one."
    PRD §3.2: "Dismissal advances `status` to `DISMISSED` and decrements the owning linked account's `detected_charge_count` by one."

    Design: Difficulty/compensating_invariant/detect_then_dismiss_conserves_detected_charge_count
    """
    member, la, charge = setup_detected_charge(amount_cents=2000)
    before = validate_success(api.get_linked_account(la["id"],
                                                     headers=make_member_headers(member["id"])))
    assert before["detected_charge_count"] == 1
    api.dismiss_recurring_charge(charge["id"], headers=make_member_headers(member["id"]))
    after = validate_success(api.get_linked_account(la["id"],
                                                    headers=make_member_headers(member["id"])))
    assert after["detected_charge_count"] == 0
