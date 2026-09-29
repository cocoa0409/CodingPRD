"""Global recomputation of every derived field.

`sync()` is called once at the end of every successful mutating operation.  It
recomputes each computed value from first principles and touches (bumps
`version` / refreshes `updated_at`) only the resources whose values actually
moved, which is what PRD 2.4 asks for.
"""

import calc
import logical_clock
from store import db, get_dt, touch

OCCUPYING = ("CONFIRMED", "RAIN_DIVERTED", "DELIVERED")
LOAD_BEARING = ("REQUESTED", "CONFIRMED", "RAIN_DIVERTED", "DELIVERED")
PROJECTING = ("CONFIRMED", "RAIN_DIVERTED")
AWARDED = ("APPROVED", "PARTIALLY_APPROVED")
CREDITING = ("APPROVED", "PARTIALLY_APPROVED", "DISBURSED")


# --------------------------------------------------------------------------
# small query helpers
# --------------------------------------------------------------------------
def bookings_where(field, value):
    return [b for b in db.bookings.values() if b.get(field) == value]


def aid_for_booking(booking_id):
    return [a for a in db.aid.values() if a["booking_id"] == booking_id]


def aid_for_fund(fund_id):
    return [a for a in db.aid.values() if a["fund_id"] == fund_id]


def training_for(educator_id):
    return [t for t in db.training.values() if t["educator_id"] == educator_id]


def materials_for(offering_id):
    return [m for m in db.materials.values() if m["offering_id"] == offering_id]


def manifests_for(booking_id):
    return [m for m in db.manifests.values() if m["booking_id"] == booking_id]


def evaluations_for(booking_id):
    return [e for e in db.evaluations.values() if e["booking_id"] == booking_id]


def in_week(booking):
    return logical_clock.in_current_week(get_dt(booking, "start_utc"))


def persons(booking):
    return booking["student_count"] + booking["chaperone_count"]


def offering_of(booking):
    return db.offerings.get(booking["offering_id"])


def _apply(entity, updates):
    changed = False
    for key, value in updates.items():
        if entity.get(key) != value:
            entity[key] = value
            changed = True
    if changed:
        touch(entity)
    return changed


# --------------------------------------------------------------------------
# individual derivations
# --------------------------------------------------------------------------
def educator_credentials(educator):
    bands = set()
    tier = "NONE"
    for record in training_for(educator["id"]):
        if record["status"] != "ASSESSED_PASS":
            continue
        if record["track"] == "CURRICULUM":
            if record.get("grade_band"):
                bands.add(record["grade_band"])
        else:
            candidate = record.get("handling_tier") or "NONE"
            if calc.HANDLING_TIER_RANK.get(candidate, 0) > calc.HANDLING_TIER_RANK.get(tier, 0):
                tier = candidate
    return [band for band in calc.GRADE_BANDS if band in bands], tier


def educator_load(educator, exclude_booking_id=None):
    total = 0
    for booking in bookings_where("lead_educator_id", educator["id"]):
        if booking["id"] == exclude_booking_id:
            continue
        if booking["delivery_status"] not in LOAD_BEARING:
            continue
        if not in_week(booking):
            continue
        offering = offering_of(booking)
        if offering:
            total += offering["duration_minutes"]
    return total


def educator_weekly_cap(educator):
    return calc.EDUCATOR_WEEKLY_CAP_MINUTES.get(educator["employment_type"], 0)


def materials_ready(offering_id):
    rows = materials_for(offering_id)
    pre = any(m["phase"] == "PRE_VISIT" and m["status"] == "PUBLISHED" for m in rows)
    post = any(m["phase"] == "POST_VISIT" and m["status"] == "PUBLISHED" for m in rows)
    return pre and post


def alignment_count(offering_id):
    return sum(1 for a in db.alignments.values() if a["offering_id"] == offering_id)


def trail_visitors_this_week(trail, exclude_booking_id=None):
    total = 0
    for booking in bookings_where("trail_segment_id", trail["id"]):
        if booking["id"] == exclude_booking_id:
            continue
        if booking["delivery_status"] not in OCCUPYING or not in_week(booking):
            continue
        total += persons(booking)
    return total


def animal_projected(animal, exclude_booking_id=None):
    total = 0
    for booking in bookings_where("animal_id", animal["id"]):
        if booking["id"] == exclude_booking_id:
            continue
        if booking["delivery_status"] not in PROJECTING or not in_week(booking):
            continue
        offering = offering_of(booking)
        if offering:
            total += offering["duration_minutes"]
    return total


def animal_realized(animal):
    total = 0
    for booking in bookings_where("animal_id", animal["id"]):
        if booking["delivery_status"] != "DELIVERED" or not in_week(booking):
            continue
        total += booking.get("actual_contact_minutes") or 0
    return total


def animal_posture(animal, projected=None):
    permit = db.permits.get(animal["permit_id"])
    permit_status = permit["status"] if permit else "LAPSED"
    if projected is None:
        projected = animal["projected_exposure_minutes_7d"]
    posture = calc.welfare_posture(
        permit_status, animal["status"], projected, animal["weekly_exposure_cap_minutes"]
    )
    return posture, calc.effective_contact_rule(posture, animal["contact_rule"])


def booking_aid_totals(booking_id):
    scholarship = 0
    transport = 0
    for application in aid_for_booking(booking_id):
        if application["status"] in CREDITING:
            scholarship += application["awarded_scholarship_cents"]
            transport += application["awarded_transport_cents"]
    return scholarship, transport


def booking_net_due(booking, aid_amount):
    status = booking["delivery_status"]
    if status == "NO_SHOW":
        return calc.NO_SHOW_FEE_CENTS
    if status == "CANCELLED":
        return 0
    if status == "DELIVERED":
        return max(0, booking["final_gross_fee_cents"] - aid_amount)
    return max(0, booking["provisional_gross_fee_cents"] - aid_amount)


def fund_counters(fund):
    pending = 0
    committed = 0
    disbursed = 0
    transport_awarded = 0
    for application in aid_for_fund(fund["id"]):
        status = application["status"]
        if status == "SUBMITTED":
            pending += application["requested_scholarship_cents"] + application["requested_transport_cents"]
        elif status in AWARDED:
            committed += application["awarded_scholarship_cents"] + application["awarded_transport_cents"]
        elif status == "DISBURSED":
            disbursed += application["awarded_scholarship_cents"] + application["awarded_transport_cents"]
        if status in CREDITING:
            transport_awarded += application["awarded_transport_cents"]
    available = fund["total_cents"] - pending - committed - disbursed
    return {
        "pending_cents": pending,
        "committed_cents": committed,
        "disbursed_cents": disbursed,
        "transport_awarded_cents": transport_awarded,
        "available_cents": available,
    }


def box_truck_loaded(booking_id):
    for manifest in manifests_for(booking_id):
        if manifest["status"] in ("LOADED", "RETURNED", "SHORTAGE_REPORTED") and manifest.get("vehicle_class") == "BOX_TRUCK":
            return True
    return False


def provisional_fee(booking):
    offering = offering_of(booking)
    school = db.schools.get(booking["school_id"])
    if not offering or not school:
        return booking.get("provisional_gross_fee_cents") or 0
    return calc.booking_fee(
        booking["student_count"],
        offering,
        school,
        box_truck_loaded(booking["id"]),
        booking.get("rain_diverted_to_offering_id") is not None,
    )


def final_fee(booking):
    offering = offering_of(booking)
    school = db.schools.get(booking["school_id"])
    if not offering or not school:
        return booking.get("final_gross_fee_cents") or 0
    return calc.booking_fee(
        booking.get("actual_student_count") or 0,
        offering,
        school,
        box_truck_loaded(booking["id"]),
        booking.get("rain_diverted_to_offering_id") is not None,
    )


# --------------------------------------------------------------------------
# the global pass
# --------------------------------------------------------------------------
def sync():
    # 1. educator credentials (from training records)
    for educator in db.educators.values():
        bands, tier = educator_credentials(educator)
        _apply(educator, {
            "curriculum_certified_grade_bands": bands,
            "animal_handling_tier": tier,
        })

    # 2. catalog rollups
    for offering in db.offerings.values():
        _apply(offering, {
            "standard_alignment_count": alignment_count(offering["id"]),
            "materials_ready": materials_ready(offering["id"]),
        })

    # 3. school equity tier and partnership standing
    for school in db.schools.values():
        strikes = sum(
            1 for b in bookings_where("school_id", school["id"])
            if b["delivery_status"] == "NO_SHOW"
        )
        status = school["status"]
        if status != "SUSPENDED":
            status = calc.school_standing(strikes)
        _apply(school, {
            "equity_tier": calc.equity_tier(school["title_i_pct"]),
            "no_show_strikes": strikes,
            "status": status,
        })

    # 4. booking money
    for booking in db.bookings.values():
        offering = offering_of(booking)
        updates = {}
        if offering:
            updates["required_chaperones"] = calc.required_chaperones(
                booking["student_count"], offering["min_chaperone_ratio_students_per_adult"]
            )
        scholarship, transport = booking_aid_totals(booking["id"])
        if booking["delivery_status"] == "CANCELLED":
            scholarship = 0
            transport = 0
        updates["aid_amount_cents"] = scholarship
        updates["transport_subsidy_cents"] = transport
        updates["net_due_cents"] = booking_net_due(booking, scholarship)
        _apply(booking, updates)

    # 5. school outstanding balance (depends on booking net_due / paid)
    for school in db.schools.values():
        balance = 0
        for booking in bookings_where("school_id", school["id"]):
            if booking["funding_status"] == "INVOICED":
                balance += booking["net_due_cents"] - booking["paid_cents"]
        _apply(school, {"outstanding_balance_cents": balance})

    # 6. fund ledger
    for fund in db.funds.values():
        _apply(fund, fund_counters(fund))

    # 7. trail weekly visitors
    for trail in db.trails.values():
        _apply(trail, {"visitors_this_week": trail_visitors_this_week(trail)})

    # 8. animal exposure and welfare posture
    for animal in db.animals.values():
        projected = animal_projected(animal)
        posture, rule = animal_posture(animal, projected)
        _apply(animal, {
            "projected_exposure_minutes_7d": projected,
            "realized_exposure_minutes_7d": animal_realized(animal),
            "welfare_posture": posture,
            "effective_contact_rule": rule,
        })

    # 9. educator weekly delivery load
    for educator in db.educators.values():
        _apply(educator, {"delivery_load_minutes_this_week": educator_load(educator)})
