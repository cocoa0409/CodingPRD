"""Move-out / termination workflows, deposit settlement (provisional vs final
variants), per-line rounding order, and charge payment rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_timestamp_equals,
    create_access_group,
    create_credential,
    create_person,
    get_success_data,
    issue_credential,
    list_charges,
    make_resident_headers,
    set_clock,
    setup_building_with_chain,
    setup_moved_out_settlement,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["security_admin_headers"]
DESK = TEST_USERS["front_desk_headers"]


# ---------------------------------------------------------------------------
# Corner: move-out side effects and guards
# ---------------------------------------------------------------------------

def test_moveout_strips_group_membership(api):
    """PRD §3.6: "The transition stamps `moved_out_at` to now, deactivates
    every credential currently `ISSUED` to that person with
    `deactivated_reason` `MOVE_OUT`, removes the person's id from the
    `person_ids` of every access group in the building, and creates the
    settlement charge in `DRAFT`: `kind` `MOVE_OUT_SETTLEMENT`, `person_id`
    set, `deposit_cents` snapshotted from the person's `key_deposit_cents`,
    `moved_out_at` recorded, `line_items` holding the forfeiture lines for
    the credentials `ISSUED` at move-out, `provisional_refund_cents`
    computed, and `amount_cents` 0 while in draft."

    Design: Corner/state_machines/moveout_strips_group_membership
    """
    ctx = setup_building_with_chain("Strip House", with_door=True)
    building, door = ctx["building"], ctx["door"]
    set_clock("2026-08-01T09:00:00Z")
    r1 = create_person(building["id"], "Res One", "RESIDENT", unit_label="U-1")
    group = create_access_group(building["id"], "Residents", door_ids=[door["id"]],
                                person_ids=[r1["id"]], days_of_week=["MON"],
                                window_start_utc="08:00", window_end_utc="20:00")

    resp = api.move_out_person(r1["id"], DESK)
    validate_success(resp)

    updated = validate_success(api.get_access_group(group["id"], ADMIN))
    assert updated["person_ids"] == []
    groups = get_success_data(
        api.list_access_groups(ADMIN, params={"person_id": r1["id"]})
    )
    assert groups == []


def test_person_moveout_on_staff_rejected(api):
    """PRD §3.6: "A `FrontDesk` or `SecurityAdmin` moves a person out —
    `ACTIVE` → `MOVED_OUT`, one of the two terminal person states alongside
    `TERMINATED` — only when the person is `ACTIVE` (else
    `ERR_PERSON_INVALID_STATE`) and of `kind` `RESIDENT` (else
    `ERR_PERSON_KIND_MISMATCH`)."

    Design: Corner/validations/person_moveout_on_staff_rejected
    """
    ctx = setup_building_with_chain("Kind House")
    s1 = create_person(ctx["building"]["id"], "Staff One", "STAFF")
    resp = api.move_out_person(s1["id"], DESK)
    validate_error(resp, ApiErrorId.ERR_PERSON_KIND_MISMATCH)
    assert validate_success(api.get_person(s1["id"], DESK))["status"] == "ACTIVE"


def test_person_moveout_twice_rejected(api):
    """PRD §3.6: "A `FrontDesk` or `SecurityAdmin` moves a person out —
    `ACTIVE` → `MOVED_OUT`, one of the two terminal person states alongside
    `TERMINATED` — only when the person is `ACTIVE` (else
    `ERR_PERSON_INVALID_STATE`) and of `kind` `RESIDENT` (else
    `ERR_PERSON_KIND_MISMATCH`)."

    Design: Corner/validations/person_moveout_twice_rejected
    """
    ctx = setup_building_with_chain("Twice House")
    set_clock("2026-08-01T09:00:00Z")
    r1 = create_person(ctx["building"]["id"], "Res One", "RESIDENT", unit_label="U-1")
    validate_success(api.move_out_person(r1["id"], DESK))
    resp = api.move_out_person(r1["id"], DESK)
    validate_error(resp, ApiErrorId.ERR_PERSON_INVALID_STATE)


def test_charge_pay_from_draft_rejected(api):
    """PRD §3.6: "Issuing moves `DRAFT` → `ISSUED` (guarded by
    `ERR_CHARGE_INVALID_STATE`), payment moves `ISSUED` → `PAID` and requires
    the supplied `paid_amount_cents` to equal `amount_cents` exactly (else
    `ERR_PAYMENT_AMOUNT_MISMATCH`; `Resident`/`Vendor` payers must own the
    charge, else `ERR_FORBIDDEN`), and voiding moves `DRAFT` or `ISSUED` →
    `VOID` (`SecurityAdmin` only)."

    Design: Corner/state_machines/charge_pay_from_draft_rejected
    """
    ctx = setup_moved_out_settlement("Pay House", deposit_cents=1000,
                                     credential_specs=(("F-1", "FOB"),))
    charge = ctx["charge"]
    assert charge["status"] == "DRAFT"
    resp = api.pay_charge(charge["id"], {"paid_amount_cents": 0}, DESK)
    validate_error(resp, ApiErrorId.ERR_CHARGE_INVALID_STATE)
    assert validate_success(api.get_charge(charge["id"], DESK))["status"] == "DRAFT"


def test_charge_payment_amount_mismatch_rejected(api):
    """PRD §3.6: "Issuing moves `DRAFT` → `ISSUED` (guarded by
    `ERR_CHARGE_INVALID_STATE`), payment moves `ISSUED` → `PAID` and requires
    the supplied `paid_amount_cents` to equal `amount_cents` exactly (else
    `ERR_PAYMENT_AMOUNT_MISMATCH`; `Resident`/`Vendor` payers must own the
    charge, else `ERR_FORBIDDEN`), and voiding moves `DRAFT` or `ISSUED` →
    `VOID` (`SecurityAdmin` only)."

    Design: Corner/validations/charge_payment_amount_mismatch_rejected
    """
    ctx = setup_moved_out_settlement("Mismatch House", deposit_cents=1000,
                                     credential_specs=(("F-1", "FOB"),))
    charge = ctx["charge"]
    validate_success(api.issue_charge(charge["id"], DESK))
    issued = validate_success(api.get_charge(charge["id"], DESK))
    # FOB line = round_half_up(4500 * 1.25) = 5625; amount = max(0, 5625 - 1000)
    assert issued["amount_cents"] == 4625

    resp = api.pay_charge(charge["id"], {"paid_amount_cents": 4624}, DESK)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)
    assert validate_success(api.get_charge(charge["id"], DESK))["status"] == "ISSUED"


def test_resident_pays_own_charge_but_forbidden_for_others(api):
    """PRD §2.1: "Concretely, a `Resident` or `Vendor` may read only their own
    `Person` record (path id must equal `X-User-ID`, else `ERR_FORBIDDEN`), may
    list credentials only with a `holder_person_id` filter equal to their own
    id, may list charges only with a `person_id` filter equal to their own id,
    may pay only charges whose `person_id` equals their own id, and may report
    lost only credentials whose `holder_person_id` equals their own id."
    PRD §3.6: "Issuing moves `DRAFT` → `ISSUED` (guarded by
    `ERR_CHARGE_INVALID_STATE`), payment moves `ISSUED` → `PAID` and requires
    the supplied `paid_amount_cents` to equal `amount_cents` exactly (else
    `ERR_PAYMENT_AMOUNT_MISMATCH`; `Resident`/`Vendor` payers must own the
    charge, else `ERR_FORBIDDEN`), and voiding moves `DRAFT` or `ISSUED` →
    `VOID` (`SecurityAdmin` only)."

    Design: Corner/roles/resident_pays_own_charge_but_forbidden_for_others
    """
    ctx = setup_moved_out_settlement("OwnPay House", deposit_cents=1000,
                                     credential_specs=(("F-1", "FOB"),))
    building, r1, charge = ctx["building"], ctx["person"], ctx["charge"]
    r2 = create_person(building["id"], "Res Two", "RESIDENT", unit_label="U-2")
    validate_success(api.issue_charge(charge["id"], DESK))

    resp = api.pay_charge(charge["id"], {"paid_amount_cents": 4625},
                          make_resident_headers(r2["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    paid = validate_success(api.pay_charge(charge["id"], {"paid_amount_cents": 4625},
                                           make_resident_headers(r1["id"])))
    assert paid["status"] == "PAID"


# ---------------------------------------------------------------------------
# Difficulty: provisional vs final settlement divergence
# ---------------------------------------------------------------------------

def _setup_settlement_divergence():
    """Resident R1 (deposit 20000) holds FOB F-1 and CARD C-1; METAL_KEY K-0 was
    reported lost 5 days before move-out (inside the trailing 30-day window)."""
    ctx = setup_building_with_chain("Settlement House")
    building, change = ctx["building"], ctx["change"]
    set_clock("2026-08-01T09:00:00Z")
    r1 = create_person(building["id"], "Res One", "RESIDENT", unit_label="U-1",
                       key_deposit_cents=20000)
    k0 = create_credential(building["id"], change["id"], "K-0", "METAL_KEY")
    f1 = create_credential(building["id"], change["id"], "F-1", "FOB")
    c1 = create_credential(building["id"], change["id"], "C-1", "CARD")
    issue_credential(k0["id"], r1["id"])
    issue_credential(f1["id"], r1["id"])
    issue_credential(c1["id"], r1["id"])
    set_clock("2026-08-06T09:00:00Z")
    validate_success(api_client.report_lost_credential(k0["id"], DESK))
    set_clock("2026-08-10T09:00:00Z")
    validate_success(api_client.move_out_person(r1["id"], DESK))
    charges = list_charges(person_id=r1["id"], kind="MOVE_OUT_SETTLEMENT")
    assert len(charges) == 1
    ctx.update({"person": r1, "k0": k0, "f1": f1, "c1": c1, "charge": charges[0]})
    return ctx


def test_moveout_settlement_provisional_variant(api):
    """PRD §3.6: "The provisional variant, computed at move-out, forfeits only
    the credentials `ISSUED` at that instant and sets
    `provisional_refund_cents` to the deposit minus the line total, floored at
    zero."
    PRD §3.6: "Each forfeiture line prices one lost or unreturned credential:
    the per-type fee is 1500 cents for a `METAL_KEY`, 4500 cents for a `FOB`,
    and 1501 cents for a `CARD`; each line's fee is uplifted by a 25 percent
    administrative surcharge and rounded half-up to integer cents per line
    first, and only then are lines summed — summing before rounding produces a
    different, incorrect result."

    Design: Difficulty/dual_variant_calc/moveout_settlement_provisional_vs_final_divergence
    """
    ctx = _setup_settlement_divergence()
    charge = ctx["charge"]
    # Provisional forfeits the two credentials ISSUED at move-out:
    # FOB line 5625 (= round(4500*1.25)) + CARD line 1876 (= round(1501*1.25)).
    assert charge["status"] == "DRAFT"
    assert charge["provisional_refund_cents"] == 12499, (
        f"expected 20000 - (5625 + 1876) = 12499, got {charge['provisional_refund_cents']}"
    )
    assert charge["amount_cents"] == 0
    assert charge["deposit_cents"] == 20000


def test_moveout_settlement_final_variant_adds_trailing_losses(api):
    """PRD §3.6: "The final variant runs when the settlement charge is issued:
    it appends lines for credentials whose `lost_at` falls within the inclusive
    trailing window from 30 days before `moved_out_at` up to and including
    `moved_out_at` — membership judged by `lost_at` regardless of the
    credential's current status — with the provisional lines ordered first, each
    set internally ordered by the credential's `created_at` ascending then
    `serial_no` ascending. It then sets `final_forfeit_total_cents` to the sum
    of all lines, `final_refund_cents` to the deposit minus that total floored
    at zero, and `amount_cents` to the total minus the deposit floored at zero."

    Design: Difficulty/dual_variant_calc/moveout_settlement_provisional_vs_final_divergence
    """
    ctx = _setup_settlement_divergence()
    charge = ctx["charge"]
    validate_success(api.issue_charge(charge["id"], DESK))
    final = validate_success(api.get_charge(charge["id"], DESK))

    # Final adds the METAL_KEY lost 5 days before move-out: 5625 + 1876 + 1875.
    assert final["final_forfeit_total_cents"] == 9376
    assert final["final_refund_cents"] == 10624
    assert final["amount_cents"] == 0

    fees = [line["fee_cents"] for line in final["line_items"]]
    assert fees == [5625, 1876, 1875], f"unexpected line order/fees: {final['line_items']}"
    assert final["line_items"][0]["credential_id"] == ctx["f1"]["id"]
    assert final["line_items"][1]["credential_id"] == ctx["c1"]["id"]
    assert final["line_items"][2]["credential_id"] == ctx["k0"]["id"]

    k0 = validate_success(api.get_credential(ctx["k0"]["id"], DESK))
    assert_timestamp_equals(k0["lost_at"], "2026-08-06T09:00:00Z")


# ---------------------------------------------------------------------------
# Difficulty: per-line rounding order
# ---------------------------------------------------------------------------

def _setup_two_card_resident():
    ctx = setup_building_with_chain("Rounding Hall")
    building, change = ctx["building"], ctx["change"]
    set_clock("2026-08-01T09:00:00Z")
    r2 = create_person(building["id"], "Res Two", "RESIDENT", unit_label="U-2",
                       key_deposit_cents=10000)
    ca = create_credential(building["id"], change["id"], "C-A", "CARD")
    cb = create_credential(building["id"], change["id"], "C-B", "CARD")
    issue_credential(ca["id"], r2["id"])
    issue_credential(cb["id"], r2["id"])
    ctx.update({"person": r2, "ca": ca, "cb": cb})
    return ctx


def test_settlement_forfeit_per_line_rounding_order_refund(api):
    """PRD §3.6: "Each forfeiture line prices one lost or unreturned credential:
    the per-type fee is 1500 cents for a `METAL_KEY`, 4500 cents for a `FOB`,
    and 1501 cents for a `CARD`; each line's fee is uplifted by a 25 percent
    administrative surcharge and rounded half-up to integer cents per line
    first, and only then are lines summed — summing before rounding produces a
    different, incorrect result."
    PRD §3.6: "The provisional variant, computed at move-out, forfeits only the
    credentials `ISSUED` at that instant and sets `provisional_refund_cents` to
    the deposit minus the line total, floored at zero."

    Design: Difficulty/combinatorial_formula/settlement_forfeit_per_line_rounding_order
    """
    ctx = _setup_two_card_resident()
    validate_success(api.move_out_person(ctx["person"]["id"], DESK))
    charges = list_charges(person_id=ctx["person"]["id"], kind="MOVE_OUT_SETTLEMENT")
    assert len(charges) == 1
    # round_half_up(1501 * 1.25) = 1876 per CARD line; 10000 - 2*1876 = 6248.
    # A sum-then-round implementation would report 10000 - 3753 = 6247.
    assert charges[0]["provisional_refund_cents"] == 6248


def test_settlement_forfeit_per_line_rounding_order_line_items(api):
    """PRD §3.6: "Each line is a snapshot of `credential_id`, `type`, and
    `fee_cents`."
    PRD §3.6: "Each forfeiture line prices one lost or unreturned credential:
    the per-type fee is 1500 cents for a `METAL_KEY`, 4500 cents for a `FOB`,
    and 1501 cents for a `CARD`; each line's fee is uplifted by a 25 percent
    administrative surcharge and rounded half-up to integer cents per line
    first, and only then are lines summed — summing before rounding produces a
    different, incorrect result."

    Design: Difficulty/combinatorial_formula/settlement_forfeit_per_line_rounding_order
    """
    ctx = _setup_two_card_resident()
    validate_success(api.move_out_person(ctx["person"]["id"], DESK))
    charges = list_charges(person_id=ctx["person"]["id"], kind="MOVE_OUT_SETTLEMENT")
    lines = charges[0]["line_items"]
    assert lines == [
        {"credential_id": ctx["ca"]["id"], "type": "CARD", "fee_cents": 1876},
        {"credential_id": ctx["cb"]["id"], "type": "CARD", "fee_cents": 1876},
    ], f"unexpected line_items: {lines}"


# ---------------------------------------------------------------------------
# Difficulty: deposit split conservation across issue + void
# ---------------------------------------------------------------------------

def test_settlement_deposit_split_conservation_at_issue(api):
    """PRD §3.6: "It then sets `final_forfeit_total_cents` to the sum of all
    lines, `final_refund_cents` to the deposit minus that total floored at zero,
    and `amount_cents` to the total minus the deposit floored at zero."

    Design: Difficulty/compensating_invariant/settlement_deposit_split_conservation_across_void
    """
    ctx = setup_moved_out_settlement("Money House", deposit_cents=10000,
                                     credential_specs=(("F-1", "FOB"),))
    charge = ctx["charge"]
    validate_success(api.issue_charge(charge["id"], DESK))
    issued = validate_success(api.get_charge(charge["id"], DESK))
    # FOB line 5625; deposit 10000 fully allocated: 5625 + 4375 == 10000.
    assert issued["final_forfeit_total_cents"] == 5625
    assert issued["final_refund_cents"] == 4375
    assert issued["final_forfeit_total_cents"] + issued["final_refund_cents"] == 10000
    assert issued["deposit_cents"] == 10000
    assert issued["amount_cents"] == 0


def test_settlement_deposit_conservation_compensating_void(api):
    """PRD §3.6: "Issuing moves `DRAFT` → `ISSUED` (guarded by
    `ERR_CHARGE_INVALID_STATE`), payment moves `ISSUED` → `PAID` and requires
    the supplied `paid_amount_cents` to equal `amount_cents` exactly (else
    `ERR_PAYMENT_AMOUNT_MISMATCH`; `Resident`/`Vendor` payers must own the
    charge, else `ERR_FORBIDDEN`), and voiding moves `DRAFT` or `ISSUED` →
    `VOID` (`SecurityAdmin` only)."

    Design: Difficulty/compensating_invariant/settlement_deposit_split_conservation_across_void
    """
    ctx = setup_moved_out_settlement("Money House", deposit_cents=10000,
                                     credential_specs=(("F-1", "FOB"),))
    charge, r1 = ctx["charge"], ctx["person"]
    validate_success(api.issue_charge(charge["id"], DESK))
    validate_success(api.void_charge(charge["id"], ADMIN))

    voided = validate_success(api.get_charge(charge["id"], DESK))
    assert voided["status"] == "VOID"
    paid = list_charges(person_id=r1["id"], status="PAID")
    assert paid == []
