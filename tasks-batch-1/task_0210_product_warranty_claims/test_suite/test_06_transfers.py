"""Warranty transfers: tiered transfer-fee computation, the cyclic
ACTIVE->TRANSFER_PENDING->ACTIVE accept path, fee-reversal conservation,
optimistic concurrency, and transfer ownership rules (PRD §3.11, §3.12, §2.8)."""
from test_helpers import set_clock, validate_error, validate_paginated, validate_success
from test_helpers import fixtures as F


# ─── Difficulty: combinatorial_formula (tiered rate + surcharge + floor/cap) ─
def test_transfer_fee_appliance_year1_3_with_surcharge(api):
    """PRD §3.12: "an elapsed age of at least 12 but fewer than 36 months selects
    2500 cents ... A category surcharge of 1000 cents is added when, and only
    when, the product's category is `APPLIANCE` ... The raw fee is the selected
    rate plus any surcharge."
    PRD §3.11: "Initiation drives the registration from `ACTIVE` to
    `TRANSFER_PENDING`".

    Design: Difficulty/combinatorial_formula/transfer_fee_tiered_rate_with_category_surcharge_and_floor
    """
    # APPLIANCE, elapsed 20 months -> 2500 + 1000 = 3500; cap 40000 not binding.
    s = F.setup_pending_transfer(
        base_cap_cents=40000,
        product_overrides={"category": "APPLIANCE", "base_warranty_months": 12, "serviceable_lifespan_months": 48},
        transfer_clock="2025-09-15T00:00:00Z",
    )
    assert s["transfer"]["transfer_fee_cents"] == 3500
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["remaining_coverage_cents"] == 36500
    assert reg["status"] == "TRANSFER_PENDING"


def test_transfer_fee_debited_to_ledger_with_transfer_fee_reason(api):
    """PRD §3.11: "The system writes a `DEBIT` ledger entry with `reason`
    `TRANSFER_FEE` for the fee amount and decrements the registration's
    `remaining_coverage_cents` by the fee through reconciliation."

    Design: Difficulty/combinatorial_formula/transfer_fee_tiered_rate_with_category_surcharge_and_floor
    """
    s = F.setup_pending_transfer(
        base_cap_cents=40000,
        product_overrides={"category": "APPLIANCE", "base_warranty_months": 12, "serviceable_lifespan_months": 48},
        transfer_clock="2025-09-15T00:00:00Z",
    )
    ledger = F.list_ledger(s["registration"]["id"], s["owner"]["id"])
    fee_entries = [e for e in ledger if e["reason"] == "TRANSFER_FEE"]
    assert len(fee_entries) == 1
    assert fee_entries[0]["entry_type"] == "DEBIT"
    assert fee_entries[0]["amount_cents"] == 3500


# ─── Difficulty: non_linear_state_machine (cyclic transfer accept) ───────────
def test_transfer_accept_returns_to_active_with_new_owner(api):
    """PRD §3.11: "acceptance sets the registration's `owner_user_id` to the
    recipient and returns the registration from `TRANSFER_PENDING` to `ACTIVE`,
    incrementing the version by one."

    Design: Difficulty/non_linear_state_machine/registration_cyclic_transfer_pending_back_to_active
    """
    s = F.setup_pending_transfer(base_cap_cents=20000)
    resp = api.accept_transfer(s["registration"]["id"], F.make_owner_headers(s["recipient"]["id"]))
    data = validate_success(resp)
    assert data["status"] == "ACTIVE"
    assert data["owner_user_id"] == s["recipient"]["id"]


def test_transfer_initiation_then_accept_completes_cycle(api):
    """PRD §3.11: "Initiation drives the registration from `ACTIVE` to
    `TRANSFER_PENDING`".
    PRD §3.11: "acceptance sets the registration's `owner_user_id` to the
    recipient and returns the registration from `TRANSFER_PENDING` to `ACTIVE`".

    Design: Difficulty/non_linear_state_machine/registration_cyclic_transfer_pending_back_to_active
    """
    s = F.setup_pending_transfer(base_cap_cents=20000)
    assert s["registration"]["status"] == "TRANSFER_PENDING"
    resp = api.accept_transfer(s["registration"]["id"], F.make_owner_headers(s["recipient"]["id"]))
    validate_success(resp)
    reg = F.get_registration(s["registration"]["id"], s["recipient"]["id"])
    assert reg["status"] == "ACTIVE"
    assert reg["owner_user_id"] == s["recipient"]["id"]


# ─── Difficulty: compensating_invariant (fee reversal conserves coverage) ────
def test_transfer_reject_reverses_fee_and_restores_coverage(api):
    """PRD §3.11: "rejection sets the most recent warranty transfer's `status` to
    `REVERSED`, writes a compensating `CREDIT` ledger entry with `reason`
    `REVERSAL` for the same `transfer_fee_cents`, restores the registration's
    `remaining_coverage_cents` by the reversed fee (so the transfer fee is
    conserved), leaves the `owner_user_id` unchanged because the transfer is
    abandoned, and returns the registration from `TRANSFER_PENDING` to `ACTIVE`".

    Design: Difficulty/compensating_invariant/transfer_fee_debit_reversed_conserves_remaining_coverage
    """
    # ELECTRONICS elapsed 5 months -> fee 1500; cap 20000 -> remaining 18500 -> reject restores 20000.
    s = F.setup_pending_transfer(
        base_cap_cents=20000,
        product_overrides={"category": "ELECTRONICS", "base_warranty_months": 12, "serviceable_lifespan_months": 48},
        transfer_clock="2024-06-15T00:00:00Z",
    )
    assert s["transfer"]["transfer_fee_cents"] == 1500
    resp = api.reject_transfer(s["registration"]["id"], F.make_owner_headers(s["recipient"]["id"]))
    data = validate_success(resp)
    assert data["status"] == "ACTIVE"
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["remaining_coverage_cents"] == 20000
    assert reg["owner_user_id"] == s["owner"]["id"]


def test_transfer_reject_writes_reversal_credit_entry(api):
    """PRD §3.11: "writes a compensating `CREDIT` ledger entry with `reason`
    `REVERSAL` for the same `transfer_fee_cents`".

    Design: Difficulty/compensating_invariant/transfer_fee_debit_reversed_conserves_remaining_coverage
    """
    s = F.setup_pending_transfer(
        base_cap_cents=20000,
        product_overrides={"category": "ELECTRONICS", "base_warranty_months": 12, "serviceable_lifespan_months": 48},
        transfer_clock="2024-06-15T00:00:00Z",
    )
    validate_success(api.reject_transfer(s["registration"]["id"], F.make_owner_headers(s["recipient"]["id"])))
    ledger = F.list_ledger(s["registration"]["id"], s["owner"]["id"])
    reversals = [e for e in ledger if e["reason"] == "REVERSAL"]
    assert len(reversals) == 1
    assert reversals[0]["entry_type"] == "CREDIT"
    assert reversals[0]["amount_cents"] == 1500


# ─── Corner: calculations (transfer fee boundaries) ──────────────────────────
def test_transfer_fee_year3plus_rate_at_36_months(api):
    """PRD §3.12: "an elapsed age of 36 months or more selects 4000 cents."

    Design: Corner/calculations/transfer_fee_year3plus_rate_selected_at_36_months_boundary
    """
    # ELECTRONICS, elapsed exactly 36 months -> 4000; surcharge 0; cap 40000 not binding.
    s = F.setup_pending_transfer(
        base_cap_cents=40000,
        product_overrides={"category": "ELECTRONICS", "base_warranty_months": 60, "serviceable_lifespan_months": 96},
        transfer_clock="2027-01-15T00:00:00Z",
    )
    assert s["transfer"]["transfer_fee_cents"] == 4000
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["remaining_coverage_cents"] == 36000


def test_transfer_fee_capped_by_coverage_below_floor(api):
    """PRD §3.12: "it is raised to a floor of 1000 cents if it falls below that,
    and then capped so it can never exceed the registration's remaining coverage —
    that is, the fee is the smaller of the registration's remaining coverage and
    the larger of the raw fee and the 1000-cent floor."

    Design: Corner/calculations/transfer_fee_floor_binds_when_coverage_below_floor
    """
    # ELECTRONICS year1 rate 1500, remaining 1200 -> min(max(1500,1000),1200) = 1200.
    s = F.setup_pending_transfer(
        base_cap_cents=1200,
        product_overrides={"category": "ELECTRONICS", "base_warranty_months": 12, "serviceable_lifespan_months": 48},
        transfer_clock="2024-06-15T00:00:00Z",
    )
    assert s["transfer"]["transfer_fee_cents"] == 1200
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["remaining_coverage_cents"] == 0


def test_remaining_coverage_clamped_at_zero_never_negative(api):
    """PRD §2.7: "The reconciled `remaining_coverage_cents` is then clamped at a
    floor of zero and may never be reported as negative."

    Design: Corner/calculations/remaining_coverage_clamped_at_floor_never_negative
    """
    s = F.setup_pending_transfer(
        base_cap_cents=1200,
        product_overrides={"category": "ELECTRONICS", "base_warranty_months": 12, "serviceable_lifespan_months": 48},
        transfer_clock="2024-06-15T00:00:00Z",
    )
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["remaining_coverage_cents"] == 0


# ─── Corner: errors / cross-cutting (OCC) ────────────────────────────────────
def test_transfer_with_stale_version_returns_stale_version(api):
    """PRD §2.8: "If another writer has advanced that version since the client last
    read the registration — for example, a claim adjudication that debited coverage
    and bumped the version, or a transfer that already completed — the values no
    longer match and the transfer is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/error_stale_version_triggerable
    """
    s = F.setup_active_registration(base_cap_cents=20000)
    gold = F.create_tier(s["product"]["id"], tier_name="GOLD", extension_months=24, price_cents=12000, coverage_cap_cents=40000)
    recipient = F.create_owner()
    stale_version = F.get_registration_version(s["registration"]["id"], s["owner"]["id"])
    # An extension purchase bumps the version, making `stale_version` stale.
    F.purchase_extension(s["registration"]["id"], s["owner"]["id"], gold["id"], 12000)
    resp = api.transfer_registration(
        s["registration"]["id"],
        {"to_owner_user_id": recipient["id"], "expected_registration_version": stale_version},
        F.make_owner_headers(s["owner"]["id"]),
    )
    validate_error(resp, "ERR_STALE_VERSION")
    assert F.get_registration(s["registration"]["id"], s["owner"]["id"])["status"] == "ACTIVE"


def test_transfer_with_current_version_succeeds(api):
    """PRD §2.8: "The server compares it against the registration's current
    `version`."
    PRD §3.11: "Initiation is permitted only when the registration is `ACTIVE`,
    the supplied `expected_registration_version` matches the registration's
    current version".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_transfer_succeeds
    """
    s = F.setup_active_registration(base_cap_cents=20000)
    recipient = F.create_owner()
    version = F.get_registration_version(s["registration"]["id"], s["owner"]["id"])
    resp = api.transfer_registration(
        s["registration"]["id"],
        {"to_owner_user_id": recipient["id"], "expected_registration_version": version},
        F.make_owner_headers(s["owner"]["id"]),
    )
    data = validate_success(resp, expected_status=201)
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["status"] == "TRANSFER_PENDING"


# ─── Corner: state machine (transfer from REGISTERED rejected) ───────────────
def test_transfer_from_registered_registration_returns_invalid_state(api):
    """PRD §3.11: "Initiation is permitted only when the registration is `ACTIVE`".
    PRD §2.10: "the target resource's state is checked fourth, yielding
    `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/transfer_from_registered_unverified_registration_returns_invalid_state
    """
    set_clock("2024-01-15T00:00:00Z")
    product = F.create_product()
    F.create_tier(product["id"], tier_name="BASE", coverage_cap_cents=20000)
    o1 = F.create_owner()
    o2 = F.create_owner()
    reg = F.create_registration(product["id"], o1["id"], purchase_date="2024-01-15T00:00:00Z")
    # Still REGISTERED (no proof validated). Supply its current version so the
    # failure is the state check, not OCC.
    resp = api.transfer_registration(
        reg["id"],
        {"to_owner_user_id": o2["id"], "expected_registration_version": reg["version"]},
        F.make_owner_headers(o1["id"]),
    )
    validate_error(resp, "ERR_INVALID_STATE")
    assert F.get_registration(reg["id"], o1["id"])["status"] == "REGISTERED"


# ─── Corner: rbac (transfer/accept by non-recipient) ─────────────────────────
def test_transfer_accept_by_non_recipient_returns_not_owner(api):
    """PRD §3.11: "Accepting it requires the registration to be `TRANSFER_PENDING`
    and the acting owner to be the transfer's `to_owner_user_id`".
    PRD §2.10: "Ownership scoping is sixth, yielding `ERR_NOT_OWNER` (HTTP 403)
    when an owner acts on a registration they do not own (or a transfer they are
    not the named recipient of)."

    Design: Corner/rbac/transfer_accept_by_non_recipient_returns_not_owner
    """
    s = F.setup_pending_transfer(base_cap_cents=20000)
    # O1 (original owner, not the recipient) attempts to accept.
    resp = api.accept_transfer(s["registration"]["id"], F.make_owner_headers(s["owner"]["id"]))
    validate_error(resp, "ERR_NOT_OWNER")


# ─── Corner: endpoint (list transfers reverse reachability) ──────────────────
def test_list_transfers_for_registration(api):
    """PRD §3.11: "both owner fields being audit values on the transfer event,
    discoverable through the registration's transfer listing."
    PRD §4: "List transfer records for a registration".

    Design: Corner/endpoints/list_transfers_filter_by_registration_reverse_reachability
    """
    s = F.setup_pending_transfer(base_cap_cents=20000)
    resp = api.list_registration_transfers(s["registration"]["id"], F.make_owner_headers(s["owner"]["id"]))
    data, _ = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["to_owner_user_id"] == s["recipient"]["id"]
    assert data[0]["from_owner_user_id"] == s["owner"]["id"]
