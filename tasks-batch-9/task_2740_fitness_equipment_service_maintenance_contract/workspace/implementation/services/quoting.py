"""Renewal-quote pricing: seven ordered steps, rounding order included."""
from decimal import Decimal

import db
from services import calc, domain


def price_quote(contract):
    club_id = contract["club_id"]
    fleet = domain.club_equipment(club_id)
    issued_at = db.now()

    # -- step one: per-unit lines, each rounded before the summation ---------
    line_items = []
    quoted_base_cents = 0
    age_multiplier_total = Decimal("0")
    for unit in fleet:
        model = db.equipment_models.get(unit["model_id"])
        base = model["base_annual_service_cents"] if model else 0
        age_years = calc.whole_years(unit["install_date"], issued_at)
        age_mult = calc.age_multiplier(age_years)
        condition_mult = calc.condition_multiplier(
            unit["replacement_recommended"], unit["support_status"]
        )
        line_cents = calc.rhu_int(calc.dec(base) * age_mult * condition_mult)
        line_items.append({
            "equipment_id": unit["id"],
            "age_years": age_years,
            "age_multiplier": age_mult,
            "condition_multiplier": condition_mult,
            "line_cents": line_cents,
        })
        quoted_base_cents += line_cents
        age_multiplier_total += age_mult

    # -- step two: parts surcharge -----------------------------------------
    parts_surcharge_cents = calc.rhu_int(
        calc.dec(quoted_base_cents) * calc.PARTS_SURCHARGE_PCT[contract["parts_inclusion"]]
    )

    # -- step three: service-history load ----------------------------------
    window_start = calc.day_start(contract["term_start_date"])
    sla_breach_count = 0
    critical_call_count = 0
    for call in db.calls.values():
        if call["contract_id"] != contract["id"]:
            continue
        reported_at = db.parse_iso(call.get("reported_at"))
        if reported_at is None or reported_at < window_start or reported_at >= issued_at:
            continue
        if call.get("sla_met") is False:
            sla_breach_count += 1
        if call["severity"] == "CRITICAL" and call["status"] == "RESOLVED":
            critical_call_count += 1
    history_load_pct = calc.history_load_pct(sla_breach_count, critical_call_count)
    history_surcharge_cents = calc.rhu_int(calc.dec(quoted_base_cents) * history_load_pct)

    # -- step four: subtotal -----------------------------------------------
    subtotal_cents = quoted_base_cents + parts_surcharge_cents + history_surcharge_cents

    # -- step five: compliance discount ------------------------------------
    compliance_snapshot = calc.dec(contract["pm_compliance_pct"])
    discount_pct = calc.compliance_discount_pct(compliance_snapshot)
    compliance_discount_cents = calc.rhu_int(calc.dec(subtotal_cents) * discount_pct)

    # -- step six: the collar, floor first then cap ------------------------
    quoted = subtotal_cents - compliance_discount_cents
    floor_cents = calc.rhu_int(calc.dec(contract["annual_base_cents"]) * calc.QUOTE_FLOOR_PCT)
    cap_cents = calc.rhu_int(calc.dec(contract["annual_base_cents"]) * calc.QUOTE_CAP_PCT)
    floor_applied = False
    cap_applied = False
    if quoted < floor_cents:
        quoted = floor_cents
        floor_applied = True
    if quoted > cap_cents:
        quoted = cap_cents
        cap_applied = True

    # -- step seven: index and validity ------------------------------------
    if line_items:
        fleet_age_index = calc.money2(age_multiplier_total / calc.dec(len(line_items)))
    else:
        fleet_age_index = Decimal("0.00")
    expires_at = issued_at + db.days(calc.QUOTE_VALID_DAYS)

    row = db.base_row()
    row.update({
        "contract_id": contract["id"],
        "issued_at": db.iso(issued_at),
        "expires_at": db.iso(expires_at),
        "line_items": line_items,
        "quoted_base_cents": quoted_base_cents,
        "parts_surcharge_cents": parts_surcharge_cents,
        "history_surcharge_cents": history_surcharge_cents,
        "history_load_pct": history_load_pct,
        "subtotal_cents": subtotal_cents,
        "compliance_discount_pct": discount_pct,
        "compliance_discount_cents": compliance_discount_cents,
        "quoted_annual_cents": quoted,
        "fleet_age_index": fleet_age_index,
        "sla_breach_count": sla_breach_count,
        "critical_call_count": critical_call_count,
        "pm_compliance_pct_snapshot": compliance_snapshot,
        "floor_applied": floor_applied,
        "cap_applied": cap_applied,
        "status": "ISSUED",
        "decline_reason": None,
    })

    # Any quote already ISSUED on this contract is superseded, numbers frozen.
    for existing in db.ordered(db.quotes):
        if existing["contract_id"] == contract["id"] and existing["status"] == "ISSUED":
            db.apply_changes(existing, {"status": "SUPERSEDED"})

    db.quotes[row["id"]] = row
    # The status becomes (or remains) RENEWAL_QUOTED and the version advances
    # either way, because RENEWAL_QUOTED -> RENEWAL_QUOTED is a legal re-quote.
    contract["status"] = "RENEWAL_QUOTED"
    db.touch(contract)
    return row


def tear_down_forward_schedule(contract, reason):
    """Cancel scheduled visits and release their reservations."""
    for visit in db.ordered(db.visits):
        if visit["contract_id"] != contract["id"] or visit["visit_status"] != "SCHEDULED":
            continue
        db.apply_changes(visit, {
            "visit_status": "CANCELLED",
            "cancellation_reason": reason,
        })
        assignment = domain.find_assignment(
            preventive_visit_id=visit["id"], statuses=("RESERVED",)
        )
        domain.release_assignment(assignment, reason)
