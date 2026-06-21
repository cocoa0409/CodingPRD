"""Coverage-ledger reconciliation, version monotonicity, and the remaining
reverse-reachability list endpoints (PRD §2.4, §2.7, §3.7, §4)."""
from test_helpers import set_clock, validate_paginated, validate_success
from test_helpers import fixtures as F


# ─── Corner: cross-cutting (version monotonicity) ────────────────────────────
def test_registration_version_starts_at_one_and_increments_on_validate(api):
    """PRD §2.4: "the `version` field is an integer that starts at 1 on creation
    and increments by one on every mutation, supporting optimistic concurrency
    control."
    PRD §3.3: "Either outcome increments the parent registration's version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_mutation
    """
    set_clock("2024-01-15T00:00:00Z")
    product = F.create_product()
    F.create_tier(product["id"], tier_name="BASE", coverage_cap_cents=20000)
    owner = F.create_owner()
    reg = F.create_registration(product["id"], owner["id"], purchase_date="2024-01-15T00:00:00Z")
    assert reg["version"] == 1
    F.submit_and_validate_proof(reg["id"], owner["id"], stated_amount_cents=50000)
    reg_after = F.get_registration(reg["id"], owner["id"])
    assert reg_after["version"] > 1
    assert reg_after["status"] == "ACTIVE"


# ─── Corner: cross-cutting (derived remaining-coverage reconciliation) ───────
def test_remaining_coverage_reconciled_after_repair_debit(api):
    """PRD §2.7: "its `remaining_coverage_cents` is a derived field reconstructed
    from that stream rather than mutated in place ... the system takes the coverage
    cap of the registration's currently active tier, sums the `amount_cents` of all
    `DEBIT` entries ... sums the `amount_cents` of all `CREDIT` entries ... and
    computes the cap minus total debits plus total credits."

    Design: Corner/cross_cutting_complexity_layers/derived_field_remaining_coverage_reconciled_after_debit
    """
    # cap 40000, single REPAIR debit 5000 -> remaining 35000.
    s = F.setup_claim_in_rma(
        reg_setup_kwargs={"base_cap_cents": 40000, "product_overrides": {"base_warranty_months": 24}},
    )
    F.adjudicate_approve(s["claim"]["id"], "REPAIR", repair_cost_cents=5000)
    reg = F.get_registration(s["registration"]["id"], s["owner"]["id"])
    assert reg["remaining_coverage_cents"] == 35000


# ─── Corner: endpoints (remaining reverse-reachability list filters) ─────────
def test_list_registrations_filter_by_owner_user_id(api):
    """PRD §4: "List registrations (filter by owner_user_id, product_id,
    active_tier_id)".
    PRD §2.5: "Several list endpoints support reverse-reachability filters".

    Design: Corner/endpoints/list_registrations_filter_by_owner_user_id_reverse_reachability
    """
    set_clock("2024-01-15T00:00:00Z")
    product = F.create_product()
    F.create_tier(product["id"], tier_name="BASE", coverage_cap_cents=20000)
    o1 = F.create_owner()
    o2 = F.create_owner()
    reg1 = F.create_registration(product["id"], o1["id"], serial_number="SN-E7A", purchase_date="2024-01-15T00:00:00Z")
    F.create_registration(product["id"], o2["id"], serial_number="SN-E7B", purchase_date="2024-01-15T00:00:00Z")
    resp = api.list_registrations(F.ADMIN, params={"owner_user_id": o1["id"]})
    data, _ = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == reg1["id"]


def test_list_proofs_filter_by_registration_id(api):
    """PRD §4: "GET `/proofs` List proofs (filter by registration_id)".
    PRD §2.5: "Several list endpoints support reverse-reachability filters".

    Design: Corner/endpoints/list_proofs_filter_by_registration_id_reverse_reachability
    """
    set_clock("2024-01-15T00:00:00Z")
    product = F.create_product()
    F.create_tier(product["id"], tier_name="BASE", coverage_cap_cents=20000)
    owner = F.create_owner()
    reg = F.create_registration(product["id"], owner["id"], purchase_date="2024-01-15T00:00:00Z")
    proof = F.submit_proof(reg["id"], owner["id"], stated_amount_cents=50000)
    resp = api.list_proofs(F.make_owner_headers(owner["id"]), params={"registration_id": reg["id"]})
    data, _ = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == proof["id"]
