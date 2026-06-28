"""Quoting policies, reference data, and basic CRUD/listing claims.

Translates queue B (Corner) instances from the `entities` and `state_machines` sections
that concern policy creation, defaults, required/type fields, not-found, listing, and the
vendor solvency lifecycle.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    api_client, TEST_USERS, make_policyholder_headers, assert_policy,
)
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.constants import RANDOM_UUID

_admin = TEST_USERS["admin_headers"]
_ph = make_policyholder_headers("ph-1")


def test_create_policy_returns_201_with_initial_states(api):
    """PRD §3.2: "A newly created policy begins with `lifecycle_status` of `QUOTED`
    and `billing_status` of `UNPAID`, and the acting user's identifier is captured as
    its `policyholder_id`."
    PRD §3.2: "The policy's computed money fields — `base_premium_cents`,
    `rider_premium_cents`, `total_premium_cents`, `premium_earned_cents`, and
    `refund_due_cents` — all start at zero, and `bind_at` is empty until the policy is
    bound."

    Design: Corner/entities/create_policy_returns_201_with_initial_states
    """
    res = api.create_policy(F.policy_payload(policy_form="SINGLE_EVENT", serves_alcohol=False), _ph)
    policy = validate_success(res, 201)
    assert_policy(policy)
    assert policy["lifecycle_status"] == "QUOTED"
    assert policy["billing_status"] == "UNPAID"
    assert policy["total_premium_cents"] == 0
    assert policy["policyholder_id"] == "ph-1"


def test_create_policy_default_free_look_days_applied(api):
    """PRD §3.2: "They may declare `serves_alcohol` (defaulting to false), which gates
    liquor coverage, and a `free_look_days` count (defaulting to 15, and never negative)".

    Design: Corner/entities/create_policy_default_free_look_days_applied
    """
    res = api.create_policy({"policy_form": "ANNUAL"}, _ph)
    policy = validate_success(res, 201)
    assert policy["free_look_days"] == 15
    assert policy["serves_alcohol"] is False


def test_create_policy_missing_policy_form_returns_invalid_request(api):
    """PRD §3.10: "Any request whose body is malformed, missing a required field, of the
    wrong type, or carrying an invalid enum value is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_policy_missing_policy_form_returns_invalid_request
    """
    res = api.create_policy({"serves_alcohol": True}, _ph)
    validate_error(res, "ERR_INVALID_REQUEST", 400)


def test_create_policy_invalid_enum_policy_form_returns_invalid_request(api):
    """PRD §3.10: "Any request whose body is malformed, missing a required field, of the
    wrong type, or carrying an invalid enum value is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_policy_invalid_enum_policy_form_returns_invalid_request
    """
    res = api.create_policy({"policy_form": "MONTHLY"}, _ph)
    validate_error(res, "ERR_INVALID_REQUEST", 400)


def test_get_policy_nonexistent_returns_not_found(api):
    """PRD §2.6: "The first identifier in the path that does not resolve to an existing
    resource causes the request to be rejected with `ERR_NOT_FOUND` before any deeper
    identifier is examined."

    Design: Corner/entities/get_policy_nonexistent_returns_not_found
    """
    res = api.get_policy(RANDOM_UUID, _ph)
    validate_error(res, "ERR_NOT_FOUND", 404)


def test_list_policies_pagination_envelope(api):
    """PRD §2.3: "List responses surface the pagination state inside the `meta` object of
    the envelope through four fields: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_policies_pagination_envelope
    """
    api.create_policy({"policy_form": "ANNUAL"}, _ph)
    data, meta = validate_paginated(api.list_policies(_admin))
    assert isinstance(data, list)
    assert meta["total_count"] >= 1
    assert meta["has_more"] in (True, False)


def test_event_profile_invalid_window_end_before_start(api):
    """PRD §3.2: "The window must be coherent: `event_end_at` must be strictly after
    `event_start_at`, and `event_start_at` must be strictly after the moment the policy
    was created; a window that violates either condition is rejected with
    `ERR_INVALID_EVENT_WINDOW`."

    Design: Corner/entities/event_profile_invalid_window_end_before_start
    """
    venue = FX.create_venue()
    policy = FX.create_quoted_policy()
    res = api.create_event_profile(policy["id"], F.event_profile_payload(
        venue["id"], event_name="Bad Window", expected_attendance=100,
        event_start_at="2026-08-01T23:00:00Z", event_end_at="2026-08-01T18:00:00Z"), _ph)
    validate_error(res, "ERR_INVALID_EVENT_WINDOW", 422)


def test_vendor_default_from_solvent_without_flag_rejected(api):
    """PRD §3.1: "both the default and clear actions require the vendor to currently be
    `FLAGGED` and are otherwise rejected with `ERR_VENDOR_NOT_FLAGGED`."

    Design: Corner/state_machines/vendor_default_from_solvent_without_flag_rejected
    """
    caterer = FX.create_caterer()
    res = api.default_vendor(caterer["id"], _admin)
    validate_error(res, "ERR_VENDOR_NOT_FLAGGED", 409)
    after = validate_success(api.list_vendors(_admin), 200)
    # confirm the vendor is untouched
    vendor = validate_success(
        api.list_vendors(_admin, params={"status": "SOLVENT"}), 200)
    assert any(v["id"] == caterer["id"] and v["status"] == "SOLVENT" for v in vendor)


def test_vendor_flag_then_clear_returns_solvent_cycle(api):
    """PRD §3.1: "From `FLAGGED`, a vendor may be defaulted, advancing it to `DEFAULTED`,
    or cleared, returning it to `SOLVENT`".
    PRD §2.4: "The `version` field is an integer that starts at its initial value and
    increments by one on every mutation to the resource".

    Design: Corner/state_machines/vendor_flag_then_clear_returns_solvent_cycle
    """
    caterer = FX.create_caterer()
    api.flag_vendor(caterer["id"], _admin)
    res = api.clear_vendor(caterer["id"], _admin)
    cleared = validate_success(res, 200)
    assert cleared["status"] == "SOLVENT"
    assert cleared["version"] == 3
