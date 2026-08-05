"""Charge minting, the encounter nominal-fee floor, the visit buckets and the
visit billing axis (PRD 3.10).
"""

import config
import store
from services import calc


def charges_of_visit(visit_id):
    rows = [c for c in store.DB["charges"].values() if c["visit_id"] == visit_id]
    rows.sort(key=store.order_key)
    return rows


def service_category_for_visit(visit):
    if visit["delivery_mode"] == "TELEHEALTH":
        return "TELEHEALTH_ENCOUNTER"
    return config.VISIT_TYPE_TO_SERVICE_CATEGORY[visit["visit_type"]]


def mint_charge(visit, student, service_category):
    no_charge = service_category in config.NO_CHARGE_SERVICE_CATEGORIES
    charge = store.new_row(
        "charges",
        {
            "visit_id": visit["id"],
            "student_id": student["id"],
            "service_category": service_category,
            "gross_amount_cents": config.FEE_SCHEDULE[service_category],
            "payer_route": student["payer_route"],
            "discount_tier_snapshot": student["discount_tier"],
            "provisional_patient_responsibility_cents": 0,
            "final_patient_responsibility_cents": None,
            "floor_adjustment_cents": 0,
            "patient_responsibility_cents": 0,
            "payer_paid_amount_cents": 0,
            "patient_paid_amount_cents": 0,
            "write_off_amount_cents": 0,
            "appeal_count": 0,
            "denial_reason": None,
            "status": "NO_CHARGE" if no_charge else "PENDING",
        },
    )
    charge["provisional_patient_responsibility_cents"] = calc.provisional_responsibility(charge)
    charge["patient_responsibility_cents"] = (
        charge["provisional_patient_responsibility_cents"] + charge["floor_adjustment_cents"]
    )
    return charge


def mint_charges_for_visit(visit, student):
    """PRD 3.10: one charge for the encounter's own service category, plus one
    IMMUNIZATION_ADMIN charge per VALID dose linked to the encounter."""
    minted = [mint_charge(visit, student, service_category_for_visit(visit))]
    doses = [
        d
        for d in store.all_rows("doses")
        if d.get("visit_id") == visit["id"] and d["status"] == "VALID"
    ]
    for _ in doses:
        minted.append(mint_charge(visit, student, "IMMUNIZATION_ADMIN"))
    return minted


def apply_encounter_floor(visit, student):
    """The four pinned steps of the encounter nominal-fee floor (PRD 3.10)."""
    charges = charges_of_visit(visit["id"])
    eligible = [c for c in charges if c["status"] not in ("NO_CHARGE", "REVERSED")]
    before = {
        c["id"]: (c["floor_adjustment_cents"], c["patient_responsibility_cents"]) for c in charges
    }

    # STEP 1 — clear every floor adjustment and take the unfloored amounts.
    for charge in charges:
        charge["floor_adjustment_cents"] = 0
    unfloored = {c["id"]: calc.unfloored_amount(c) for c in eligible}

    # STEP 2 — the encounter total.
    encounter_sum = sum(unfloored.values())

    # STEP 3 — apply the floor only under all three conditions.
    if (
        eligible
        and student["payer_route"] != "MEDICAID"
        and encounter_sum < config.NOMINAL_FEE_FLOOR_CENTS
    ):
        target = sorted(
            eligible,
            key=lambda c: (-c["gross_amount_cents"], c["created_at"], c["_seq"]),
        )[0]
        target["floor_adjustment_cents"] = config.NOMINAL_FEE_FLOOR_CENTS - encounter_sum

    # STEP 4 — the operative per-charge amount, which STEP 4 of the rule then sums.
    for charge in charges:
        charge["patient_responsibility_cents"] = (
            calc.unfloored_amount(charge) + charge["floor_adjustment_cents"]
        )
        after = (charge["floor_adjustment_cents"], charge["patient_responsibility_cents"])
        if before.get(charge["id"]) != after:
            store.touch(charge)


def recompute_visit_buckets(visit):
    charges = charges_of_visit(visit["id"])
    gross = 0
    no_charge = 0
    patient = 0
    write_off = 0
    payer_billed = 0
    for charge in charges:
        status = charge["status"]
        if status != "REVERSED":
            gross += charge["gross_amount_cents"]
        if status == "NO_CHARGE":
            no_charge += charge["gross_amount_cents"]
        if status not in ("REVERSED", "NO_CHARGE"):
            patient += charge["patient_responsibility_cents"]
            payer_billed += (
                charge["gross_amount_cents"]
                - charge["patient_responsibility_cents"]
                - charge["write_off_amount_cents"]
            )
        if status == "WRITTEN_OFF":
            write_off += charge["write_off_amount_cents"]
    visit["gross_charge_total_cents"] = gross
    visit["no_charge_total_cents"] = no_charge
    visit["patient_responsibility_total_cents"] = patient
    visit["write_off_total_cents"] = write_off
    visit["payer_billed_total_cents"] = payer_billed


def derive_billing_status(visit):
    """The billing axis is a pure function of the encounter's charge rows.

    The all-REVERSED test is evaluated FIRST (PRD 3.10).
    """
    charges = charges_of_visit(visit["id"])
    if not charges:
        return "NOT_APPLICABLE"
    if all(c["status"] == "REVERSED" for c in charges):
        return "REVERSED"
    if all(c["status"] in config.TERMINAL_CHARGE_STATUSES for c in charges):
        return "CHARGES_POSTED"
    return "PENDING_CHARGES"


def settle_visit(visit, student, rerun_floor):
    """Recompute everything that hangs off a visit's charge set."""
    if rerun_floor:
        apply_encounter_floor(visit, student)
    recompute_visit_buckets(visit)
    new_status = derive_billing_status(visit)
    if new_status == "REVERSED":
        visit["gross_charge_total_cents"] = 0
        visit["no_charge_total_cents"] = 0
        visit["patient_responsibility_total_cents"] = 0
        visit["write_off_total_cents"] = 0
        visit["payer_billed_total_cents"] = 0
    visit["billing_status"] = new_status
    store.touch(visit)
