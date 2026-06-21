"""Listing/action endpoints, RBAC, OCC, derived fields, immediate consistency."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_account, create_vehicle, create_transponder, create_plaza, credit_account,
    bind_transponder, record_transponder_read, record_plate_read, price,
    setup_bound_account, create_hov_window_payload, create_transponder_binding_payload,
    setup_plate_violation,
    api_client, TEST_USERS, make_account_holder_headers,
)

OP = TEST_USERS["toll_operator_headers"]


# ─── Endpoints ───────────────────────────────────────────────────────────────

def test_list_vehicles_filtered_by_account_paginated(api):
    """PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."
    PRD §4: "GET | `/etc/vehicles` | List vehicles, filterable by account".

    Design: Corner/endpoints/list_vehicles_filtered_by_account_paginated
    """
    account = create_account(holder_name="Lv")
    create_vehicle(account["id"], plate_number="LV1")
    create_vehicle(account["id"], plate_number="LV2")
    data, meta = validate_paginated(api.list_vehicles(OP, params={"account_id": account["id"]}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_end_binding_unbinds_transponder(api):
    """PRD §3.4: "ending it moves the binding to `ENDED` with `effective_to` set to the
    current moment and returns the transponder from `BOUND` to `UNBOUND`."

    Design: Corner/endpoints/end_binding_unbinds_transponder
    """
    account = create_account(holder_name="Eb")
    vehicle = create_vehicle(account["id"], plate_number="EB1")
    transponder = create_transponder(account["id"], "TP-EB")
    binding = bind_transponder(account["id"], transponder["id"], vehicle["id"],
                               vehicle["version"])
    holder = make_account_holder_headers(account["id"])
    ended = validate_success(api.end_transponder_binding(binding["id"], holder), 200)
    assert ended["status"] == "ENDED"
    tp_after = validate_success(api.get_transponder(transponder["id"], OP), 200)
    assert tp_after["status"] == "UNBOUND"


def test_revoke_hov_window(api):
    """PRD §3.5: "A window's `status` is `DECLARED` on creation, and the holder may later
    revoke it, moving it to `REVOKED`."

    Design: Corner/endpoints/revoke_hov_window
    """
    account = create_account(holder_name="Rh")
    vehicle = create_vehicle(account["id"], plate_number="RH1", hov_capable=True)
    holder = make_account_holder_headers(account["id"])
    hw = validate_success(api.create_hov_window(create_hov_window_payload(
        vehicle["id"], "2026-03-09T07:00:00Z", "2026-03-09T09:00:00Z", 3), holder), 201)
    revoked = validate_success(api.revoke_hov_window(hw["id"], holder), 200)
    assert revoked["status"] == "REVOKED"


def test_list_toll_transactions_by_plaza_subresource(api):
    """PRD §4: "GET | `/etc/plazas/{id}/toll-transactions` | List toll transactions at a
    plaza". PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_toll_transactions_by_plaza_subresource
    """
    account = create_account(holder_name="Lt")
    create_vehicle(account["id"], plate_number="LT1")
    plaza = create_plaza(name="Plt", base_rate_cents=400)
    record_plate_read(plaza["id"], "LT1", "NY", "2026-03-10T08:00:00Z", is_peak=False)
    data, meta = validate_paginated(api.list_plaza_toll_transactions(plaza["id"], OP))
    assert meta["total_count"] == 1


# ─── RBAC ──────────────────────────────────────────────────────────────────

def test_account_holder_cannot_create_plaza(api):
    """PRD §2.1: "If the header is present and recognized but the role is not permitted
    to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)." PRD §4: "POST | `/etc/plazas` | Create a toll plaza | TollOperator".

    Design: Corner/rbac/account_holder_cannot_create_plaza
    """
    account = create_account(holder_name="Rb")
    res = api.create_plaza({"name": "Hack", "state_code": "NY", "base_rate_cents": 400},
                           make_account_holder_headers(account["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_holder_cannot_pay_other_holders_violation(api):
    """PRD §2.1: "When an `AccountHolder` acts on a resource owned by a different account,
    the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §2.1: "a `Violation` is owned through its resolved `account_id`."

    Design: Corner/rbac/holder_cannot_pay_other_holders_violation
    """
    account_a, vehicle, plaza, txn, viol = setup_plate_violation(plate_number="PA1")
    credit_account(account_a["id"], 10000)
    account_b = create_account(holder_name="Pb")
    res = api.pay_violation(viol["id"], make_account_holder_headers(account_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or is not one of the recognized role names,
    the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    res = api.get_account("00000000-0000-4000-8000-000000000000", headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── Optimistic concurrency ──────────────────────────────────────────────────

def test_occ_stale_vehicle_version_on_binding(api):
    """PRD §2.6: "Binding a transponder to a vehicle requires the field
    `expected_vehicle_version`, carrying the client's last observed `version` of the
    target `Vehicle`. If another writer has advanced that vehicle's `version` since the
    client read it ... the create is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_vehicle_version_on_binding
    """
    account = create_account(holder_name="Oc1")
    vehicle = create_vehicle(account["id"], plate_number="OC1V")
    stale_version = vehicle["version"]
    tp_a = create_transponder(account["id"], "TP-OC1A")
    tp_b = create_transponder(account["id"], "TP-OC1B")
    holder = make_account_holder_headers(account["id"])
    # First binding bumps vehicle.version; then end it (doesn't restore version).
    binding = bind_transponder(account["id"], tp_a["id"], vehicle["id"], stale_version,
                               effective_from="2026-01-01T00:00:00Z",
                               effective_to="2026-02-01T00:00:00Z")
    api.end_transponder_binding(binding["id"], holder)
    # Now bind tp_b carrying the original (now stale) version.
    payload = create_transponder_binding_payload(
        tp_b["id"], vehicle["id"], "2026-03-01T00:00:00Z", stale_version)
    res = api.create_transponder_binding(payload, holder)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


# ─── Derived field reconciliation ────────────────────────────────────────────

def test_derived_outstanding_fines_recomputed_on_issue(api):
    """PRD §3.8: "Opening a violation supplies the `toll_transaction_id`. It creates a
    `Violation` in `ASSESSED` status, carries the underlying toll into `toll_due_cents`
    ... and — as a cascade — moves the owning account from `ACTIVE` to `DELINQUENT` if it
    was `ACTIVE`."
    PRD §3.1: "It begins at 0 and is recomputed whenever a violation of the account is
    created, paid, accepted, or rejected."

    Design: Corner/cross_cutting_complexity_layers/derived_outstanding_fines_recomputed_on_issue
    """
    account, vehicle, plaza, txn, viol = setup_plate_violation(plate_number="DF1")
    acct = validate_success(api.get_account(account["id"], OP), 200)
    # fine_total = toll 750 + penalty 2500 = 3250
    assert acct["outstanding_fines_cents"] == 3250, \
        f"expected 3250, got {acct['outstanding_fines_cents']}"
    assert acct["status"] == "DELINQUENT"


# ─── Immediate consistency ───────────────────────────────────────────────────

def test_price_response_reflects_debit_immediately(api):
    """PRD §3.6: "For a transponder read, the account's `balance_cents` is debited by
    `toll_cents`, a `TOLL_DEBIT` ledger entry for the negative `toll_cents` is appended,
    and the settlement dimension moves from `UNSETTLED` to `SETTLED`."

    Design: Corner/consistency_model/price_response_reflects_debit_immediately
    """
    account, vehicle, transponder, _ = setup_bound_account(serial="TP-IM", credit=5000)
    plaza = create_plaza(base_rate_cents=400)
    txn = record_transponder_read(plaza["id"], transponder["id"], "2026-03-16T03:00:00Z",
                                  is_peak=False)
    priced = validate_success(api.price_toll_transaction(txn["id"], OP), 200)
    assert priced["pricing_status"] == "PRICED"
    assert priced["toll_cents"] == 400
    acct = validate_success(api.get_account(account["id"], OP), 200)
    assert acct["balance_cents"] == 4600, f"expected 4600, got {acct['balance_cents']}"
