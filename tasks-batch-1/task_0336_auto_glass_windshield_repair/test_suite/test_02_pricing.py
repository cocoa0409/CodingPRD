"""Price quote at acceptance and trip fee at scheduling (PRD 3.3, 3.4)."""
from test_helpers import validate_success
from test_helpers import fixtures as fx
from test_helpers import factories as f

ADVISOR = fx.ADVISOR


# ---------------------------------------------------------------------------
# Difficulty rule 2 — price_quote_conditional_branch_mode_a (REPLACE+ADAS)
# ---------------------------------------------------------------------------
def test_replace_adas_quote_total(api):
    """PRD 3.3: "For a REPLACE, the base is 32,500 cents, and if the vehicle is
    ADAS-equipped an additional ADAS recalibration fee of 19,900 cents is added to
    the base".
    PRD 3.3: "the system adds a shop fee equal to 8.5 percent of that combined
    base-plus-ADAS amount, computed by summing the base and the ADAS fee first and
    then rounding the percentage of that sum half-up to the nearest cent".

    Design: Difficulty/combinatorial_formula/price_quote_conditional_branch_mode_a
    """
    cust, veh, wo, _ = fx.setup_assessed_work_order(decision="REPLACE", adas_equipped=True, oem="FWADAS1")
    assert wo["service_decision"] == "REPLACE", f"expected REPLACE, got {wo['service_decision']}"
    # 32500 + 19900 = 52400; shop_fee = round_half_up(52400*0.085=4454) = 4454; total 56854.
    assert wo["total_charge_cents"] == 56854, (
        f"REPLACE+ADAS quote must be 56854, got {wo['total_charge_cents']}")


def test_replace_adas_decision_frozen_on_accept(api):
    """PRD 3.3: "the work order's service_decision is set to the accepted
    assessment's recommendation ... the price is quoted into total_charge_cents".

    Design: Difficulty/combinatorial_formula/price_quote_conditional_branch_mode_a
    """
    cust, veh, wo, _ = fx.setup_assessed_work_order(decision="REPLACE", adas_equipped=True, oem="FWADAS2")
    assert wo["status"] == "ASSESSED", f"expected ASSESSED, got {wo['status']}"
    assert wo["service_decision"] == "REPLACE"
    assert wo["total_charge_cents"] == 56854


# ---------------------------------------------------------------------------
# Difficulty rule 2 — trip_fee_circular_on_frozen_total_mode_c (REPAIR mobile OOS)
# ---------------------------------------------------------------------------
def test_trip_fee_reads_frozen_total_out_of_state(api):
    """PRD 3.4: "It is computed as a percentage of the already-frozen
    total_charge_cents produced at acceptance — that frozen value is read as-is and
    never recomputed here".
    PRD 3.4: "for a MOBILE appointment whose customer state is anything other than
    CA, the trip rate is 9 percent of the frozen total".

    Design: Difficulty/combinatorial_formula/trip_fee_circular_on_frozen_total_mode_c
    """
    cust, veh = fx.setup_customer_and_vehicle(state="NV", adas_equipped=False, oem="FWTRIP1")
    tech = fx.create_technician(can_mobile=True, adas_certified=False, home_state="NV")
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.create_assessment(wo["id"])  # repairable defaults -> REPAIR
    wo2 = validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    assert wo2["total_charge_cents"] == 9657, f"frozen REPAIR quote must be 9657, got {wo2['total_charge_cents']}"
    appt = fx.book_appointment(wo["id"], tech["id"], "MOBILE",
                               "2026-06-14T15:00:00Z", "2026-06-14T16:00:00Z")
    final = validate_success(api.schedule_work_order(wo["id"], {"appointment_id": appt["id"]}, ADVISOR), 200)
    # round_half_up(9657*0.09 = 869.13 -> 869); 9657 + 869 = 10526.
    assert final["total_charge_cents"] == 10526, (
        f"out-of-state mobile total must be 10526, got {final['total_charge_cents']}")


def test_trip_fee_frozen_quote_before_schedule(api):
    """PRD 3.4: "pinning the evaluation order so the quote is finalized first and
    the trip fee second."
    PRD 3.3: "No mobile trip fee is included at acceptance time, because the service
    location is not yet chosen".

    Design: Difficulty/combinatorial_formula/trip_fee_circular_on_frozen_total_mode_c
    """
    cust, veh = fx.setup_customer_and_vehicle(state="NV", adas_equipped=False, oem="FWTRIP2")
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.create_assessment(wo["id"])
    wo2 = validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    assert wo2["total_charge_cents"] == 9657, (
        f"quote at accept must be the frozen 9657 with no trip fee, got {wo2['total_charge_cents']}")


# ---------------------------------------------------------------------------
# Corner calculations — replace_non_adas_quote_correct
# ---------------------------------------------------------------------------
def test_replace_non_adas_quote_total(api):
    """PRD 3.3: "a REPLACE on a vehicle that is not ADAS-equipped carries no such
    fee." and the shop fee is "8.5 percent of that combined base-plus-ADAS amount ...
    rounding the percentage of that sum half-up to the nearest cent".

    Design: Corner/calculations/replace_non_adas_quote_correct
    """
    cust, veh, wo, _ = fx.setup_assessed_work_order(decision="REPLACE", adas_equipped=False, oem="FWNONADAS")
    # 32500 + round_half_up(32500*0.085=2762.5 -> 2763) = 35263.
    assert wo["total_charge_cents"] == 35263, (
        f"REPLACE non-ADAS quote must be 35263, got {wo['total_charge_cents']}")


# ---------------------------------------------------------------------------
# Corner calculations — repair_quote_correct
# ---------------------------------------------------------------------------
def test_repair_quote_total(api):
    """PRD 3.3: "For a REPAIR, the base is 8,900 cents and there is no ADAS fee."
    plus the shop fee of 8.5 percent rounded half-up.

    Design: Corner/calculations/repair_quote_correct
    """
    cust, veh, wo, _ = fx.setup_assessed_work_order(decision="REPAIR", adas_equipped=False, oem="FWREPAIR")
    # 8900 + round_half_up(8900*0.085=756.5 -> 757) = 9657.
    assert wo["total_charge_cents"] == 9657, (
        f"REPAIR quote must be 9657, got {wo['total_charge_cents']}")


# ---------------------------------------------------------------------------
# Corner calculations — local_mobile_trip_fee_4pct
# ---------------------------------------------------------------------------
def test_local_mobile_trip_fee_in_state(api):
    """PRD 3.4: "For a MOBILE appointment whose customer service_address_state
    equals CA, the trip rate is 4 percent of the frozen total".

    Design: Corner/calculations/local_mobile_trip_fee_4pct
    """
    cust, veh = fx.setup_customer_and_vehicle(state="CA", adas_equipped=False, oem="FWLOCAL")
    tech = fx.create_technician(can_mobile=True, adas_certified=False, home_state="CA")
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.create_assessment(wo["id"])
    validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    appt = fx.book_appointment(wo["id"], tech["id"], "MOBILE",
                               "2026-06-14T15:00:00Z", "2026-06-14T16:00:00Z")
    final = validate_success(api.schedule_work_order(wo["id"], {"appointment_id": appt["id"]}, ADVISOR), 200)
    # round_half_up(9657*0.04 = 386.28 -> 386); 9657 + 386 = 10043.
    assert final["total_charge_cents"] == 10043, (
        f"in-state mobile total must be 10043, got {final['total_charge_cents']}")


# ---------------------------------------------------------------------------
# Corner calculations — in_shop_no_trip_fee
# ---------------------------------------------------------------------------
def test_in_shop_appointment_adds_no_trip_fee(api):
    """PRD 3.4: "For an IN_SHOP appointment the trip fee is zero and the total is
    unchanged."

    Design: Corner/calculations/in_shop_no_trip_fee
    """
    cust, veh = fx.setup_customer_and_vehicle(state="NV", adas_equipped=False, oem="FWSHOP")
    tech = fx.create_technician(can_mobile=False, adas_certified=False, home_state="CA")
    bay = fx.create_service_bay(name="Shop Bay", bay_type="INSTALL")
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.create_assessment(wo["id"])
    validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    appt = fx.book_appointment(wo["id"], tech["id"], "IN_SHOP",
                               "2026-06-14T15:00:00Z", "2026-06-14T16:00:00Z", service_bay_id=bay["id"])
    final = validate_success(api.schedule_work_order(wo["id"], {"appointment_id": appt["id"]}, ADVISOR), 200)
    assert final["total_charge_cents"] == 9657, (
        f"IN_SHOP total must equal the frozen 9657, got {final['total_charge_cents']}")
