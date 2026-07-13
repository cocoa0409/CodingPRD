"""Composite setup helpers.

Most interesting claims in this PRD need the system driven 5–15 calls deep before
the behaviour under test is even reachable: a warranty claim needs a *delivered*
lab order, which needs a shipped one, which needs a QC pass, which needs a started
lab order, which needs a confirmed order, which needs a verified prescription, a
frame, a lens material and a customer. These helpers encapsulate those preambles.

All setup calls go through `get_success_data()` so a broken precondition surfaces
as a clear "Setup step failed" rather than a confusing assertion further down.

Identity threading: `Customer` is entity-backed (PRD §2.1), so every
ownership-gated call here uses `make_customer_headers(customer["id"])` with the
real customer id.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC
from .factories import (
    create_coating_option_payload,
    create_customer_payload,
    create_exam_appointment_payload,
    create_frame_payload,
    create_insurance_claim_payload,
    create_insurance_policy_payload,
    create_kit_payload,
    create_material_option_payload,
    create_order_payload,
    create_prescription_payload,
    create_store_payload,
    create_warranty_claim_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["platform_admin_headers"]
OPTICIAN = TEST_USERS["optician_headers"]
STORE = TEST_USERS["store_associate_headers"]
LAB = TEST_USERS["lab_tech_headers"]
BENEFITS = TEST_USERS["benefits_admin_headers"]


# ═════════════════════════════════════════════════════════════════════════════
# Tier 0 — primitives
# ═════════════════════════════════════════════════════════════════════════════

def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """PRD §2.5 — move the logical clock. Returns
    {current_utc, expired_prescription_ids, overdue_kit_ids}."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def new_policy(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_insurance_policy(
            create_insurance_policy_payload(**overrides), ADMIN
        )
    )


def new_in_network_policy(**overrides) -> Dict[str, Any]:
    overrides.setdefault("network", "IN_NETWORK")
    return new_policy(**overrides)


def new_out_of_network_policy(**overrides) -> Dict[str, Any]:
    overrides.setdefault("network", "OUT_OF_NETWORK")
    overrides.setdefault("frame_allowance_cents", 0)
    overrides.setdefault("lens_copay_cents", 0)
    overrides.setdefault("annual_max_cents", 25000)
    overrides.setdefault("oon_reimburse_pct", 0.75)
    overrides.setdefault("oon_fee_schedule", {"92004": 5000, "V2020": 5000})
    return new_policy(**overrides)


def new_store(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_store(create_store_payload(**overrides), ADMIN)
    )


def new_frame(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_frame(create_frame_payload(**overrides), ADMIN)
    )


def new_material(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_lens_option(create_material_option_payload(**overrides), ADMIN)
    )


def new_coating(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_lens_option(create_coating_option_payload(**overrides), ADMIN)
    )


def new_customer(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    )


def new_prescription(customer_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_prescription(
            create_prescription_payload(customer_id, **overrides),
            make_customer_headers(customer_id),
        )
    )


def verify_prescription(prescription_id: str) -> Dict[str, Any]:
    """PRD §3.2 — an OpticianVerifier rules VERIFIED on a SUBMITTED prescription."""
    return get_success_data(
        api_client.verify_prescription(
            prescription_id, {"decision": "VERIFIED"}, OPTICIAN
        )
    )


def reject_prescription(prescription_id: str, reason: str = "PD looks transposed") -> Dict[str, Any]:
    """PRD §3.2 — a REJECTED decision requires a rejection_reason."""
    return get_success_data(
        api_client.verify_prescription(
            prescription_id,
            {"decision": "REJECTED", "rejection_reason": reason},
            OPTICIAN,
        )
    )


def new_verified_prescription(customer_id: str, **overrides) -> Dict[str, Any]:
    rx = new_prescription(customer_id, **overrides)
    return verify_prescription(rx["id"])


def new_order(
    customer_id: str,
    prescription_id: str,
    frame_id: str,
    material_option_id: str,
    delivery_method: str = "SHIP",
    coating_option_ids: Optional[List[str]] = None,
    store_id: Optional[str] = None,
    exam_appointment_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = create_order_payload(
        customer_id,
        prescription_id,
        frame_id,
        material_option_id,
        delivery_method=delivery_method,
        coating_option_ids=coating_option_ids,
        store_id=store_id,
        exam_appointment_id=exam_appointment_id,
        **overrides,
    )
    return get_success_data(
        api_client.create_order(payload, make_customer_headers(customer_id))
    )


def confirm_order(
    order_id: str, customer_id: str, fsa_amount_cents: Optional[int] = None
) -> Dict[str, Any]:
    """PRD §3.6 — the owning customer confirms a DRAFT order."""
    payload: Dict[str, Any] = {}
    if fsa_amount_cents is not None:
        payload["fsa_amount_cents"] = fsa_amount_cents
    return get_success_data(
        api_client.confirm_order(order_id, payload, make_customer_headers(customer_id))
    )


def cancel_order(order_id: str, customer_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(
        api_client.cancel_order(order_id, payload, make_customer_headers(customer_id))
    )


# ─── Reads ───────────────────────────────────────────────────────────────────

def read_policy(policy_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_insurance_policy(policy_id, ADMIN))


def read_frame(frame_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_frame(frame_id, STORE))


def read_customer(customer_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_customer(customer_id, ADMIN))


def read_prescription(prescription_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_prescription(prescription_id, ADMIN))


def read_order(order_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_order(order_id, ADMIN))


def read_kit(kit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_home_try_on_kit(kit_id, STORE))


def read_lab_order(lab_order_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_lab_order(lab_order_id, LAB))


def read_claim(claim_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_insurance_claim(claim_id, BENEFITS))


def read_warranty_claim(warranty_claim_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_warranty_claim(warranty_claim_id, STORE))


def read_exam_appointment(appointment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_exam_appointment(appointment_id, STORE))


def list_lab_orders_for(order_id: str, **params) -> List[Dict[str, Any]]:
    query = {"order_id": order_id}
    query.update(params)
    return get_success_data(api_client.list_lab_orders(LAB, params=query))


def list_claims_for(order_id: str, **params) -> List[Dict[str, Any]]:
    query = {"order_id": order_id}
    query.update(params)
    return get_success_data(api_client.list_insurance_claims(BENEFITS, params=query))


def list_kit_items(kit_id: str) -> List[Dict[str, Any]]:
    return get_success_data(api_client.list_kit_items(kit_id, STORE))


def list_frame_items(frame_id: str, **params) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_frame_try_on_kit_items(frame_id, STORE, params=params or None)
    )


def lab_order_for(order_id: str) -> Dict[str, Any]:
    """PRD §3.6 — a confirmation mints exactly one lab order for the order."""
    rows = list_lab_orders_for(order_id)
    assert rows, f"Setup step failed: no lab order was minted for order {order_id}"
    return rows[0]


def claim_for(order_id: str) -> Dict[str, Any]:
    """PRD §3.6 — a confirmation mints one claim for an insured customer."""
    rows = list_claims_for(order_id)
    assert rows, f"Setup step failed: no insurance claim exists for order {order_id}"
    return rows[0]


# ─── Lab progression (PRD §3.7) ──────────────────────────────────────────────

def start_lab_order(lab_order_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.start_lab_order(lab_order_id, LAB))


def qc_pass(lab_order_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.qc_lab_order(lab_order_id, {"result": "PASS"}, LAB)
    )


def qc_fail(lab_order_id: str, failure_reason: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.qc_lab_order(
            lab_order_id, {"result": "FAIL", "failure_reason": failure_reason}, LAB
        )
    )


def ship_lab_order(lab_order_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.ship_lab_order(lab_order_id, LAB))


def deliver_lab_order(lab_order_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.deliver_lab_order(lab_order_id, STORE))


def drive_lab_order_to_shipped(lab_order_id: str) -> Dict[str, Any]:
    """QUEUED → IN_PRODUCTION → QC_PASSED → SHIPPED."""
    start_lab_order(lab_order_id)
    qc_pass(lab_order_id)
    return ship_lab_order(lab_order_id)


def drive_lab_order_to_delivered(lab_order_id: str) -> Dict[str, Any]:
    """QUEUED → IN_PRODUCTION → QC_PASSED → SHIPPED → DELIVERED.
    The deliver response carries the lab order's post-delivery `version`, which is
    what a warranty filing must echo back as `expected_lab_order_version` (PRD §2.7)."""
    drive_lab_order_to_shipped(lab_order_id)
    return deliver_lab_order(lab_order_id)


# ─── Try-on (PRD §3.4) ───────────────────────────────────────────────────────

def new_kit(
    customer_id: str,
    frame_ids: List[str],
    ship_date: str = "2026-05-05T00:00:00Z",
    due_date: str = "2026-05-15T00:00:00Z",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_home_try_on_kit(
            create_kit_payload(customer_id, frame_ids, ship_date, due_date),
            make_customer_headers(customer_id),
        )
    )


def ship_kit(kit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.ship_home_try_on_kit(kit_id, STORE))


def return_kit(
    kit_id: str, customer_id: str, kept_frame_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.return_home_try_on_kit(
            kit_id,
            {"kept_frame_ids": kept_frame_ids or []},
            make_customer_headers(customer_id),
        )
    )


def new_shipped_kit(
    customer_id: str,
    frame_ids: List[str],
    ship_date: str = "2026-05-05T00:00:00Z",
    due_date: str = "2026-05-15T00:00:00Z",
) -> Dict[str, Any]:
    kit = new_kit(customer_id, frame_ids, ship_date, due_date)
    return ship_kit(kit["id"])


# ─── Exams (PRD §3.3) ────────────────────────────────────────────────────────

def new_exam_appointment(
    customer_id: str,
    store_id: str,
    start_at: str = "2026-06-01T10:00:00Z",
    end_at: str = "2026-06-01T10:30:00Z",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_exam_appointment(
            create_exam_appointment_payload(customer_id, store_id, start_at, end_at),
            make_customer_headers(customer_id),
        )
    )


# ─── Insurance / warranty filings (PRD §2.7, §3.8, §3.9) ─────────────────────

def file_insurance_claim(
    order_id: str,
    expected_order_version: int,
    service_lines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_insurance_claim(
            create_insurance_claim_payload(
                order_id, expected_order_version, service_lines
            ),
            BENEFITS,
        )
    )


def adjudicate_approved(claim_id: str, allowed_amount_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.adjudicate_insurance_claim(
            claim_id,
            {"decision": "APPROVED", "allowed_amount_cents": allowed_amount_cents},
            BENEFITS,
        )
    )


def adjudicate_denied(claim_id: str, denial_reason: str = "not covered") -> Dict[str, Any]:
    return get_success_data(
        api_client.adjudicate_insurance_claim(
            claim_id, {"decision": "DENIED", "denial_reason": denial_reason}, BENEFITS
        )
    )


def reimburse_claim(claim_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.reimburse_insurance_claim(claim_id, BENEFITS))


def file_warranty_claim(
    lab_order_id: str,
    customer_id: str,
    reason: str,
    expected_lab_order_version: int,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_warranty_claim(
            create_warranty_claim_payload(
                lab_order_id, customer_id, reason, expected_lab_order_version
            ),
            make_customer_headers(customer_id),
        )
    )


def decide_warranty_approved(warranty_claim_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.decide_warranty_claim(
            warranty_claim_id, {"decision": "APPROVED"}, STORE
        )
    )


def decide_warranty_denied(
    warranty_claim_id: str, denial_reason: str = "out of scope"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.decide_warranty_claim(
            warranty_claim_id,
            {"decision": "DENIED", "denial_reason": denial_reason},
            STORE,
        )
    )


# ═════════════════════════════════════════════════════════════════════════════
# Tier 2 — the order scenario (catalog + customer + verified Rx + DRAFT order)
# ═════════════════════════════════════════════════════════════════════════════

# The low-power Rx every "money is irrelevant" scenario uses: power 1.00 → tier 1.50.
LOW_POWER_RX: Dict[str, Any] = {
    "od_sphere": -1.00,
    "od_cylinder": 0.00,
    "os_sphere": -1.00,
    "os_cylinder": 0.00,
    "pd_mm": 62.0,
}

# PRD §3.5: |od_sphere| 5.50 and |od_cylinder| 1.00 give a power of exactly 6.00,
# which lands in the [6.00, 8.00) tier requiring an index of at least 1.67.
RX_POWER_EXACTLY_SIX: Dict[str, Any] = {
    "od_sphere": -5.50,
    "od_cylinder": -1.00,
    "os_sphere": -5.00,
    "os_cylinder": 0.00,
    "pd_mm": 63.0,
}

# Power 9.00 with a prism correction over the 0.50 trigger.
RX_POWER_NINE_WITH_PRISM: Dict[str, Any] = {
    "od_sphere": -8.00,
    "od_cylinder": -2.00,
    "os_sphere": -7.00,
    "os_cylinder": -1.00,
    "pd_mm": 63.0,
    "prism_diopters": 0.75,
}

# Power 13.00 — past the 12.00 point where the high-power surcharge cap binds.
RX_POWER_THIRTEEN: Dict[str, Any] = {
    "od_sphere": -12.00,
    "od_cylinder": -2.00,
    "os_sphere": -11.00,
    "os_cylinder": -1.00,
    "pd_mm": 62.0,
    "prism_diopters": 0.25,
}


def setup_order_scenario(
    *,
    policy: Optional[Dict[str, Any]] = None,
    customer: Optional[Dict[str, Any]] = None,
    frame: Optional[Dict[str, Any]] = None,
    material: Optional[Dict[str, Any]] = None,
    coatings: Optional[List[Dict[str, Any]]] = None,
    prescription: Optional[Dict[str, Any]] = None,
    verify_rx: bool = True,
    delivery_method: str = "SHIP",
    store: Optional[Dict[str, Any]] = None,
    build_order: bool = True,
) -> Dict[str, Any]:
    """Catalog + customer + prescription (+ DRAFT order) in one call.

    `policy` / `frame` / `material` / `prescription` / `store` take payload override
    dicts; `coatings` takes a list of coating payload override dicts. Pass
    `policy=None` for a self-pay customer. Returns a dict with every created row
    plus the acting customer's headers.
    """
    policy_row = new_policy(**policy) if policy is not None else None

    store_row = None
    if store is not None or delivery_method == "BOPIS":
        store_row = new_store(**(store or {}))

    frame_row = new_frame(**(frame or {}))
    material_row = new_material(**(material or {}))
    coating_rows = [new_coating(**c) for c in (coatings or [])]

    customer_overrides = dict(customer or {})
    if policy_row is not None:
        customer_overrides.setdefault("insurance_policy_id", policy_row["id"])
    customer_row = new_customer(**customer_overrides)

    rx_overrides = dict(prescription or {})
    rx_row = new_prescription(customer_row["id"], **rx_overrides)
    if verify_rx:
        rx_row = verify_prescription(rx_row["id"])

    order_row = None
    if build_order:
        order_row = new_order(
            customer_row["id"],
            rx_row["id"],
            frame_row["id"],
            material_row["id"],
            delivery_method=delivery_method,
            coating_option_ids=[c["id"] for c in coating_rows] or None,
            store_id=store_row["id"] if delivery_method == "BOPIS" and store_row else None,
        )

    return {
        "policy": policy_row,
        "store": store_row,
        "frame": frame_row,
        "material": material_row,
        "coatings": coating_rows,
        "customer": customer_row,
        "prescription": rx_row,
        "order": order_row,
        "headers": make_customer_headers(customer_row["id"]),
    }


def setup_confirmed_order(
    *, fsa_amount_cents: Optional[int] = None, **scenario_kwargs
) -> Dict[str, Any]:
    """`setup_order_scenario` driven through POST /orders/{id}/confirm.

    Adds `order` (re-quoted, CONFIRMED/AUTHORIZED), `lab_order` (QUEUED) and —
    only when the customer has a policy — `claim` (SUBMITTED). PRD §3.6.
    """
    scenario = setup_order_scenario(**scenario_kwargs)
    order = confirm_order(
        scenario["order"]["id"], scenario["customer"]["id"], fsa_amount_cents
    )
    scenario["order"] = order
    scenario["lab_order"] = lab_order_for(order["id"])
    scenario["claim"] = (
        claim_for(order["id"]) if scenario["policy"] is not None else None
    )
    return scenario


def setup_delivered_lab_order(**scenario_kwargs) -> Dict[str, Any]:
    """`setup_confirmed_order` driven all the way to a DELIVERED lab order —
    the only state from which a warranty claim may be filed (PRD §3.9).

    The returned `lab_order` is the deliver response, so its `version` is the
    fresh value a warranty filing must echo as `expected_lab_order_version`.
    """
    scenario = setup_confirmed_order(**scenario_kwargs)
    scenario["lab_order"] = drive_lab_order_to_delivered(scenario["lab_order"]["id"])
    return scenario


# ═════════════════════════════════════════════════════════════════════════════
# Tier 3 — named money scenarios reused across several claims
# ═════════════════════════════════════════════════════════════════════════════

def setup_in_network_percey_order(
    *, fsa_balance_cents: int = 10000, build_order: bool = True
) -> Dict[str, Any]:
    """The canonical in-network money scenario (PRD §3.5–§3.6).

    An IN_NETWORK plan (frame allowance 15,000c, lens copay 2,500c), a customer
    with an FSA balance, a verified prescription whose power is exactly 6.00, a
    19,500c frame and an M167 blank under two coatings (AR 4,000c + BLUE 3,000c).

    The pinned ESTIMATED walk: lens upcharge 17,950 → subtotal 37,450 → 10%
    discount 3,745 → net 33,705 → discounted frame 17,550 / discounted lens 16,155
    → benefit_frame 15,000 + benefit_lens 13,655 = benefit_applied 28,655 →
    pre-FSA balance 5,050.
    """
    return setup_order_scenario(
        policy={
            "network": "IN_NETWORK",
            "frame_allowance_cents": 15000,
            "lens_copay_cents": 2500,
            "annual_max_cents": 30000,
        },
        customer={"fsa_balance_cents": fsa_balance_cents},
        frame={"price_cents": 19500, "min_pd_mm": 54.0, "max_pd_mm": 70.0, "tryon_stock": 2},
        material={"code": "M167", "base_price_cents": 12000, "material_index": 1.67},
        coatings=[
            {"code": "AR", "base_price_cents": 4000},
            {"code": "BLUE", "base_price_cents": 3000},
        ],
        prescription=dict(RX_POWER_EXACTLY_SIX),
        build_order=build_order,
    )


def setup_out_of_network_claim_ready(
    *, service_lines: List[Dict[str, Any]], annual_max_cents: int = 25000,
    oon_fee_schedule: Optional[Dict[str, int]] = None, allowed_amount_cents: int = 7498,
) -> Dict[str, Any]:
    """An OUT_OF_NETWORK plan whose claim is ADJUDICATED_APPROVED and therefore
    ready to reimburse (PRD §3.8).

    Out-of-network plans pay nothing at the counter, so the order's benefit is
    zero and the auto-minted claim reserves zero; a BenefitsAdmin then files the
    superseding claim that actually carries the service lines.
    """
    scenario = setup_confirmed_order(
        policy={
            "network": "OUT_OF_NETWORK",
            "frame_allowance_cents": 0,
            "lens_copay_cents": 0,
            "annual_max_cents": annual_max_cents,
            "oon_reimburse_pct": 0.75,
            "oon_fee_schedule": oon_fee_schedule
            if oon_fee_schedule is not None
            else {"92004": 5000, "V2020": 5000},
        },
        frame={"price_cents": 19500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M150", "base_price_cents": 0, "material_index": 1.50},
        prescription={
            "od_sphere": -3.00,
            "od_cylinder": -1.00,
            "os_sphere": -2.50,
            "os_cylinder": -0.50,
            "pd_mm": 63.0,
        },
        fsa_amount_cents=0,
    )
    claim = file_insurance_claim(
        scenario["order"]["id"], scenario["order"]["version"], service_lines
    )
    scenario["claim"] = adjudicate_approved(claim["id"], allowed_amount_cents)
    return scenario


# ═════════════════════════════════════════════════════════════════════════════
# Tier 4 — accumulation: driving a customer's return-risk score to an exact value
# ═════════════════════════════════════════════════════════════════════════════

def setup_risk_score_at_seventy() -> Dict[str, Any]:
    """Drive a customer's `return_risk_score` to exactly 70 — the value at which
    the kit gate fires (PRD §3.4: "strictly below 70 ... the gate fires at a score
    of exactly 70 and above").

    Two kits, both flipped OVERDUE by the clock and then returned: the first kept
    one frame, the second kept nothing. With a lifetime count of 2 the ROLLING
    variant applies and both kits sit inside the 180-day window, so the score is
    100 * (0.6 * 1 zero-kept + 0.4 * 2 overdue) / 2 == 70.
    """
    frame = new_frame(tryon_stock=3, min_pd_mm=50.0, max_pd_mm=75.0)
    customer = new_customer()
    cid = customer["id"]

    set_clock("2026-01-01T00:00:00Z")

    kit_one = new_kit(cid, [frame["id"]], "2026-01-02T00:00:00Z", "2026-01-12T00:00:00Z")
    ship_kit(kit_one["id"])
    set_clock("2026-01-20T00:00:00Z")  # kit one goes OVERDUE
    kit_one = return_kit(kit_one["id"], cid, [frame["id"]])  # kept 1 → not zero-kept

    kit_two = new_kit(cid, [frame["id"]], "2026-01-21T00:00:00Z", "2026-01-31T00:00:00Z")
    ship_kit(kit_two["id"])
    set_clock("2026-02-10T00:00:00Z")  # kit two goes OVERDUE
    kit_two = return_kit(kit_two["id"], cid, [])  # kept nothing → zero-kept

    return {
        "frame": frame,
        "customer": customer,
        "kit_one": kit_one,
        "kit_two": kit_two,
        "headers": make_customer_headers(cid),
    }


def setup_three_kit_strict_history() -> Dict[str, Any]:
    """Build the three-kit history that flips the risk score onto the STRICT
    variant (PRD §3.4: STRICT applies at a `lifetime_kit_count` of three or more).

    - kit_zero: an old, clean kit (returned on time, one frame kept) whose
      `due_date` of 2025-11-12 falls OUTSIDE the ROLLING window once the clock
      reaches 2026-05-20.
    - kit_one: overdue, returned keeping nothing.
    - kit_two: shipped and still out — the caller's trigger advances the clock to
      flip it OVERDUE, which is the third history entry and therefore the moment
      the variant switches.
    """
    frame = new_frame(tryon_stock=3, min_pd_mm=50.0, max_pd_mm=75.0)
    customer = new_customer()
    cid = customer["id"]

    set_clock("2025-11-01T00:00:00Z")
    kit_zero = new_kit(cid, [frame["id"]], "2025-11-02T00:00:00Z", "2025-11-12T00:00:00Z")
    ship_kit(kit_zero["id"])
    set_clock("2025-11-10T00:00:00Z")
    kit_zero = return_kit(kit_zero["id"], cid, [frame["id"]])  # on time, one kept

    set_clock("2026-04-01T00:00:00Z")
    kit_one = new_kit(cid, [frame["id"]], "2026-04-02T00:00:00Z", "2026-04-12T00:00:00Z")
    ship_kit(kit_one["id"])
    set_clock("2026-04-20T00:00:00Z")  # kit one goes OVERDUE
    kit_one = return_kit(kit_one["id"], cid, [])  # kept nothing

    kit_two = new_kit(cid, [frame["id"]], "2026-04-21T00:00:00Z", "2026-05-01T00:00:00Z")
    ship_kit(kit_two["id"])

    return {
        "frame": frame,
        "customer": customer,
        "kit_zero": kit_zero,
        "kit_one": kit_one,
        "kit_two": kit_two,
        "headers": make_customer_headers(cid),
    }


# ═════════════════════════════════════════════════════════════════════════════
# Tier 5 — remake / warranty terminal setups
# ═════════════════════════════════════════════════════════════════════════════

def setup_lab_order_at_remake_limit() -> Dict[str, Any]:
    """A lab order that has already failed QC twice (remake_count 2) and been
    restarted, so it sits IN_PRODUCTION with no failure budget left (PRD §3.7)."""
    scenario = setup_confirmed_order(
        frame={"price_cents": 9500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M150", "base_price_cents": 0, "material_index": 1.50},
        prescription=dict(LOW_POWER_RX),
    )
    lab_id = scenario["lab_order"]["id"]
    start_lab_order(lab_id)
    qc_fail(lab_id, "coating haze")
    start_lab_order(lab_id)
    qc_fail(lab_id, "edge chip")
    scenario["lab_order"] = start_lab_order(lab_id)
    return scenario


def setup_delivered_order_with_open_warranty_claim(
    *, reason: str = "CUSTOMER_DAMAGE"
) -> Dict[str, Any]:
    """A DELIVERED lab order carrying one OPEN warranty claim.

    The parent order's frozen `lens_upcharge_cents` is 6,000 (an M160 blank, no
    coatings, no prism, no high-power surcharge), which is what the remake
    liability of PRD §3.9 is keyed on.
    """
    scenario = setup_delivered_lab_order(
        frame={"price_cents": 9500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M160", "base_price_cents": 6000, "material_index": 1.60},
        prescription={
            "od_sphere": -2.00,
            "od_cylinder": 0.00,
            "os_sphere": -2.00,
            "os_cylinder": 0.00,
            "pd_mm": 62.0,
        },
    )
    scenario["warranty_claim"] = file_warranty_claim(
        scenario["lab_order"]["id"],
        scenario["customer"]["id"],
        reason,
        scenario["lab_order"]["version"],
    )
    return scenario
