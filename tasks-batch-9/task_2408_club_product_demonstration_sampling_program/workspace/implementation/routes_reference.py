"""Reference data: manufacturers, clubs, products, baselines, roster, equipment units."""

from flask import Blueprint, request

import calc
import domain as dm
import validation as v
from envelope import ok, ok_array, paginate
from errors import fail
from store import by_seq, db, iso_now, new_row, touch

bp = Blueprint("reference", __name__)


# ===========================================================================
# Manufacturer
# ===========================================================================
@bp.post("/manufacturers")
def create_manufacturer():
    v.guard(("ProgramAdmin",))
    body = v.json_body()
    legal_name = v.req_string(body, "legal_name", max_len=160)
    billing_email = v.req_email(body, "billing_email")
    program_tier = v.req_enum(body, "program_tier", calc.PROGRAM_TIERS)
    credit_limit_cents = v.req_int(body, "credit_limit_cents", minimum=0)
    credit_terms_days = v.req_int(body, "credit_terms_days", choices=calc.CREDIT_TERMS_DAYS)

    row = new_row(
        legal_name=legal_name,
        billing_email=billing_email,
        program_tier=program_tier,
        credit_limit_cents=credit_limit_cents,
        credit_terms_days=credit_terms_days,
        account_status="ACTIVE",
        outstanding_balance_cents=0,
        credit_note_balance_cents=0,
    )
    db.manufacturers[row["id"]] = row
    return ok(dm.pub(row), 201)


@bp.get("/manufacturers/<mid>")
def get_manufacturer(mid):
    v.guard(("ProgramAdmin", "Manufacturer"))
    row = dm.resolve(db.manufacturers, mid, "ERR_MANUFACTURER_NOT_FOUND")
    return ok(dm.pub(row))


@bp.patch("/manufacturers/<mid>")
def patch_manufacturer(mid):
    v.guard(("ProgramAdmin",))
    body = v.json_body()
    account_status = v.opt_enum(body, "account_status", calc.ACCOUNT_STATUSES)
    credit_limit_cents = v.opt_int(body, "credit_limit_cents", minimum=0)
    credit_terms_days = v.opt_int(body, "credit_terms_days", choices=calc.CREDIT_TERMS_DAYS)
    billing_email = v.opt_email(body, "billing_email")
    row = dm.resolve(db.manufacturers, mid, "ERR_MANUFACTURER_NOT_FOUND")

    if account_status is not None:
        row["account_status"] = account_status
    if credit_limit_cents is not None:
        row["credit_limit_cents"] = credit_limit_cents
    if credit_terms_days is not None:
        row["credit_terms_days"] = credit_terms_days
    if billing_email is not None:
        row["billing_email"] = billing_email
    if credit_limit_cents is not None and account_status is None:
        dm.evaluate_credit_standing(row)
    touch(row)
    return ok(dm.pub(row))


# ===========================================================================
# Club
# ===========================================================================
@bp.post("/clubs")
def create_club():
    v.guard(("ProgramAdmin",))
    body = v.json_body()
    club_number = v.req_club_number(body, "club_number")
    name = v.req_string(body, "name")
    region_code = v.req_string(body, "region_code")
    club_tier = v.req_enum(body, "club_tier", calc.CLUB_TIERS)
    daily_event_capacity = v.req_int(body, "daily_event_capacity", minimum=1, maximum=12)
    food_station_count = v.req_int(body, "food_station_count", minimum=0, maximum=8)
    permit = v.req_date(body, "health_permit_expires_on")

    for other in db.clubs.values():
        if other["club_number"] == club_number:
            fail("ERR_DUPLICATE_RESOURCE", "club_number already registered.")

    row = new_row(
        club_number=club_number,
        name=name,
        region_code=region_code,
        club_tier=club_tier,
        daily_event_capacity=daily_event_capacity,
        food_station_count=food_station_count,
        health_permit_expires_on=permit.isoformat(),
        club_status="OPEN",
    )
    db.clubs[row["id"]] = row
    return ok(dm.pub(row), 201)


@bp.get("/clubs/<cid>")
def get_club(cid):
    v.guard(("ProgramAdmin", "ClubOperations", "Manufacturer", "StaffingCoordinator"))
    row = dm.resolve(db.clubs, cid, "ERR_CLUB_NOT_FOUND")
    return ok(dm.pub(row))


@bp.patch("/clubs/<cid>")
def patch_club(cid):
    caller = v.guard(("ProgramAdmin", "ClubOperations"))
    body = v.json_body()
    club_status = v.opt_enum(body, "club_status", calc.CLUB_STATUSES)
    daily_event_capacity = v.opt_int(body, "daily_event_capacity", minimum=1, maximum=12)
    food_station_count = v.opt_int(body, "food_station_count", minimum=0, maximum=8)
    permit = v.opt_date(body, "health_permit_expires_on")
    row = dm.resolve(db.clubs, cid, "ERR_CLUB_NOT_FOUND")
    v.check_ownership(caller, club_id=row["id"])

    if daily_event_capacity is not None:
        row["daily_event_capacity"] = daily_event_capacity
    if food_station_count is not None:
        row["food_station_count"] = food_station_count
    if permit is not None:
        row["health_permit_expires_on"] = permit.isoformat()
    if club_status is not None:
        row["club_status"] = club_status
    touch(row)

    if club_status == "CLOSED":
        clock_date = db.clock.date()
        for event in by_seq(list(db.demo_events.values())):
            if event["club_id"] != row["id"]:
                continue
            if event["booking_status"] != "CONFIRMED":
                continue
            if calc.parse_date(event["event_date"]) < clock_date:
                continue
            dm.cancel_confirmed_event(event, "CLUB_CANCELLED")
    return ok(dm.pub(row))


@bp.get("/clubs/<cid>/capacity")
def club_capacity(cid):
    v.guard(("ProgramAdmin", "ClubOperations", "Manufacturer"))
    raw_date = request.args.get("event_date")
    if raw_date is None:
        fail("ERR_VALIDATION", "event_date is required.")
    event_date = calc.parse_date(raw_date)
    if event_date is None:
        fail("ERR_VALIDATION", "event_date must be a YYYY-MM-DD date.")
    product_id = request.args.get("product_id")

    club = dm.resolve(db.clubs, cid, "ERR_CLUB_NOT_FOUND")
    product = None
    if product_id is not None:
        product = dm.resolve(db.products, product_id, "ERR_PRODUCT_NOT_FOUND")

    scope = [
        e
        for e in db.demo_events.values()
        if e["club_id"] == club["id"]
        and e["event_date"] == event_date.isoformat()
        and e["booking_status"] in calc.LIVE_BOOKING_STATUSES
    ]
    confirmed_count = len(scope)
    food_confirmed_count = sum(1 for e in scope if e["event_type"] == "FOOD_SAMPLING")
    category_counts = {}
    for e in scope:
        prod = db.products.get(e["product_id"])
        if prod is None:
            continue
        category_counts[prod["category"]] = category_counts.get(prod["category"], 0) + 1

    week_start = calc.week_monday(event_date)
    data = {
        "club_id": club["id"],
        "event_date": event_date.isoformat(),
        "daily_event_capacity": club["daily_event_capacity"],
        "confirmed_count": confirmed_count,
        "remaining_slots": max(0, club["daily_event_capacity"] - confirmed_count),
        "food_station_count": club["food_station_count"],
        "food_confirmed_count": food_confirmed_count,
        "category_counts": category_counts,
        "week_start_date": week_start.isoformat(),
        "weekly_sample_case_pool": None,
        "pool_cases_used": None,
        "pool_remaining": None,
        "emergency_reserve_cases": None,
        "reserve_cases_used": None,
        "reserve_remaining": None,
    }
    if product is not None:
        _, pool_used, reserve_used = dm.club_week_usage(
            club["id"], product["id"], event_date
        )
        data["weekly_sample_case_pool"] = product["weekly_sample_case_pool"]
        data["pool_cases_used"] = pool_used
        data["pool_remaining"] = max(0, product["weekly_sample_case_pool"] - pool_used)
        data["emergency_reserve_cases"] = product["emergency_reserve_cases"]
        data["reserve_cases_used"] = reserve_used
        data["reserve_remaining"] = max(
            0, product["emergency_reserve_cases"] - reserve_used
        )
    return ok(data)


# ===========================================================================
# Product
# ===========================================================================
@bp.post("/products")
def create_product():
    caller = v.guard(("ProgramAdmin", "Manufacturer"))
    body = v.json_body()
    manufacturer_id = v.req_string(body, "manufacturer_id")
    sku = v.req_string(body, "sku")
    name = v.req_string(body, "name")
    category = v.req_enum(body, "category", calc.CATEGORIES)
    requires_food_handling = v.req_bool(body, "requires_food_handling")
    requires_heat_equipment = v.req_bool(body, "requires_heat_equipment")
    allergen_flag = v.opt_bool(body, "allergen_flag", default=False)
    unit_cost_cents = v.req_int(body, "unit_cost_cents", minimum=0)
    samples_per_case = v.req_int(body, "samples_per_case", minimum=1)
    weekly_sample_case_pool = v.req_int(body, "weekly_sample_case_pool", minimum=0)
    emergency_reserve_cases = v.opt_int(body, "emergency_reserve_cases", default=0, minimum=0)

    man = dm.resolve(db.manufacturers, manufacturer_id, "ERR_MANUFACTURER_NOT_FOUND")
    v.check_ownership(caller, manufacturer_id=man["id"])

    for other in db.products.values():
        if other["manufacturer_id"] == man["id"] and other["sku"] == sku:
            fail("ERR_DUPLICATE_RESOURCE", "sku already registered for this manufacturer.")
    if requires_heat_equipment and not requires_food_handling:
        fail(
            "ERR_PRODUCT_FLAG_INCONSISTENT",
            "requires_heat_equipment may only be true when requires_food_handling is true.",
        )

    row = new_row(
        manufacturer_id=man["id"],
        sku=sku,
        name=name,
        category=category,
        requires_food_handling=requires_food_handling,
        requires_heat_equipment=requires_heat_equipment,
        allergen_flag=allergen_flag,
        unit_cost_cents=unit_cost_cents,
        samples_per_case=samples_per_case,
        weekly_sample_case_pool=weekly_sample_case_pool,
        emergency_reserve_cases=emergency_reserve_cases,
    )
    db.products[row["id"]] = row
    return ok(dm.pub(row), 201)


@bp.get("/products/<pid>")
def get_product(pid):
    v.guard(("ProgramAdmin", "Manufacturer", "ClubOperations"))
    row = dm.resolve(db.products, pid, "ERR_PRODUCT_NOT_FOUND")
    return ok(dm.pub(row))


@bp.get("/products")
def list_products():
    v.guard(("ProgramAdmin", "Manufacturer", "ClubOperations"))
    limit, offset = v.pagination()
    manufacturer_id = request.args.get("manufacturer_id")
    category = v.query_enum("category", calc.CATEGORIES)
    rows = by_seq(list(db.products.values()))
    if manufacturer_id is not None:
        rows = [r for r in rows if r["manufacturer_id"] == manufacturer_id]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    page, total = paginate(rows, limit, offset)
    return ok_array([dm.pub(r) for r in page], limit, offset, total)


# ===========================================================================
# ClubProductBaseline
# ===========================================================================
@bp.post("/club-product-baselines")
def create_baseline():
    v.guard(("ProgramAdmin",))
    body = v.json_body()
    club_id = v.req_string(body, "club_id")
    product_id = v.req_string(body, "product_id")
    baseline_weekly_units = v.req_int(body, "baseline_weekly_units", minimum=0)
    baseline_unit_price_cents = v.req_int(body, "baseline_unit_price_cents", minimum=0)
    week_start = v.req_date(body, "baseline_week_start_date")

    club = dm.resolve(db.clubs, club_id, "ERR_CLUB_NOT_FOUND")
    product = dm.resolve(db.products, product_id, "ERR_PRODUCT_NOT_FOUND")
    if dm.baseline_for(club["id"], product["id"]) is not None:
        fail("ERR_DUPLICATE_RESOURCE", "a baseline already exists for this club and product.")

    row = new_row(
        club_id=club["id"],
        product_id=product["id"],
        baseline_weekly_units=baseline_weekly_units,
        baseline_unit_price_cents=baseline_unit_price_cents,
        baseline_week_start_date=week_start.isoformat(),
        restatement_count=0,
    )
    db.baselines[row["id"]] = row
    return ok(dm.pub(row), 201)


@bp.get("/club-product-baselines/<bid>")
def get_baseline(bid):
    v.guard(("ProgramAdmin", "Manufacturer"))
    row = dm.resolve(db.baselines, bid, "ERR_RESOURCE_NOT_FOUND")
    return ok(dm.pub(row))


@bp.get("/club-product-baselines")
def list_baselines():
    v.guard(("ProgramAdmin", "Manufacturer"))
    limit, offset = v.pagination()
    club_id = request.args.get("club_id")
    product_id = request.args.get("product_id")
    rows = by_seq(list(db.baselines.values()))
    if club_id is not None:
        rows = [r for r in rows if r["club_id"] == club_id]
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    page, total = paginate(rows, limit, offset)
    return ok_array([dm.pub(r) for r in page], limit, offset, total)


@bp.patch("/club-product-baselines/<bid>")
def patch_baseline(bid):
    v.guard(("ProgramAdmin",))
    body = v.json_body()
    weekly_units = v.opt_int(body, "baseline_weekly_units", minimum=0)
    unit_price = v.opt_int(body, "baseline_unit_price_cents", minimum=0)
    row = dm.resolve(db.baselines, bid, "ERR_RESOURCE_NOT_FOUND")

    changed = False
    if weekly_units is not None and weekly_units != row["baseline_weekly_units"]:
        row["baseline_weekly_units"] = weekly_units
        changed = True
    if unit_price is not None and unit_price != row["baseline_unit_price_cents"]:
        row["baseline_unit_price_cents"] = unit_price
        changed = True

    if changed:
        row["restatement_count"] += 1
        for measurement in by_seq(list(db.measurements.values())):
            if measurement["measurement_status"] != "POSTED":
                continue
            event = db.demo_events.get(measurement["demo_event_id"])
            if event is None:
                continue
            if event["club_id"] == row["club_id"] and event["product_id"] == row["product_id"]:
                measurement["measurement_status"] = "STALE"
    touch(row)
    return ok(dm.pub(row))


# ===========================================================================
# Demonstrator + certifications
# ===========================================================================
@bp.post("/demonstrators")
def create_demonstrator():
    v.guard(("ProgramAdmin", "StaffingCoordinator"))
    body = v.json_body()
    home_club_id = v.req_string(body, "home_club_id")
    full_name = v.req_string(body, "full_name")
    hourly_rate_cents = v.req_int(body, "hourly_rate_cents", minimum=1)
    max_weekly_events = v.opt_int(body, "max_weekly_events", default=5, minimum=1, maximum=14)
    club = dm.resolve(db.clubs, home_club_id, "ERR_CLUB_NOT_FOUND")

    row = new_row(
        home_club_id=club["id"],
        full_name=full_name,
        employment_status="ACTIVE",
        hourly_rate_cents=hourly_rate_cents,
        max_weekly_events=max_weekly_events,
        reliability_score_rolling_90=100.00,
        reliability_score_program_to_date=100.00,
        no_show_strike_count=0,
        completed_event_count=0,
    )
    db.demonstrators[row["id"]] = row
    return ok(dm.pub(row), 201)


@bp.get("/demonstrators/<did>")
def get_demonstrator(did):
    v.guard(("ProgramAdmin", "StaffingCoordinator", "Demonstrator", "ClubOperations"))
    row = dm.resolve(db.demonstrators, did, "ERR_DEMONSTRATOR_NOT_FOUND")
    return ok(dm.pub(row))


@bp.get("/demonstrators")
def list_demonstrators():
    v.guard(("ProgramAdmin", "StaffingCoordinator", "ClubOperations"))
    limit, offset = v.pagination()
    home_club_id = request.args.get("home_club_id")
    employment_status = v.query_enum("employment_status", calc.EMPLOYMENT_STATUSES)
    rows = by_seq(list(db.demonstrators.values()))
    if home_club_id is not None:
        rows = [r for r in rows if r["home_club_id"] == home_club_id]
    if employment_status is not None:
        rows = [r for r in rows if r["employment_status"] == employment_status]
    page, total = paginate(rows, limit, offset)
    return ok_array([dm.pub(r) for r in page], limit, offset, total)


@bp.patch("/demonstrators/<did>")
def patch_demonstrator(did):
    v.guard(("ProgramAdmin", "StaffingCoordinator"))
    body = v.json_body()
    employment_status = v.opt_enum(body, "employment_status", calc.EMPLOYMENT_STATUSES)
    hourly_rate_cents = v.opt_int(body, "hourly_rate_cents", minimum=1)
    max_weekly_events = v.opt_int(body, "max_weekly_events", minimum=1, maximum=14)
    row = dm.resolve(db.demonstrators, did, "ERR_DEMONSTRATOR_NOT_FOUND")

    if hourly_rate_cents is not None:
        row["hourly_rate_cents"] = hourly_rate_cents
    if max_weekly_events is not None:
        row["max_weekly_events"] = max_weekly_events
    if employment_status is not None:
        row["employment_status"] = employment_status

    if employment_status in ("ON_LEAVE", "TERMINATED"):
        clock_date = db.clock.date()
        for assignment in dm.demonstrator_assignments(row["id"]):
            if assignment["assignment_status"] not in ("ASSIGNED", "CONFIRMED"):
                continue
            event = db.demo_events.get(assignment["demo_event_id"])
            if event is None:
                continue
            if calc.parse_date(event["event_date"]) < clock_date:
                continue
            assignment["assignment_status"] = "RELEASED"
            touch(assignment)
            if dm.downgrade_coverage(event, False):
                touch(event)
        dm.recompute_demonstrator_metrics(row)
    touch(row)
    return ok(dm.pub(row))


@bp.post("/demonstrators/<did>/certifications")
def create_certification(did):
    v.guard(("ProgramAdmin", "StaffingCoordinator"))
    body = v.json_body()
    cert_type = v.req_enum(body, "cert_type", calc.CERT_TYPES)
    certificate_number = v.req_string(body, "certificate_number")
    issued_on = v.req_date(body, "issued_on")
    expires_on = v.req_date(body, "expires_on")
    if expires_on <= issued_on:
        fail("ERR_VALIDATION", "expires_on must be later than issued_on.")
    dem = dm.resolve(db.demonstrators, did, "ERR_DEMONSTRATOR_NOT_FOUND")

    row = new_row(
        demonstrator_id=dem["id"],
        cert_type=cert_type,
        certificate_number=certificate_number,
        issued_on=issued_on.isoformat(),
        expires_on=expires_on.isoformat(),
        revoked_at=None,
    )
    db.certifications[row["id"]] = row
    return ok(dm.cert_pub(row), 201)


@bp.get("/demonstrators/<did>/certifications")
def list_certifications(did):
    v.guard(("ProgramAdmin", "StaffingCoordinator", "Demonstrator"))
    limit, offset = v.pagination()
    cert_type = v.query_enum("cert_type", calc.CERT_TYPES)
    dem = dm.resolve(db.demonstrators, did, "ERR_DEMONSTRATOR_NOT_FOUND")
    rows = [
        r
        for r in by_seq(list(db.certifications.values()))
        if r["demonstrator_id"] == dem["id"]
    ]
    if cert_type is not None:
        rows = [r for r in rows if r["cert_type"] == cert_type]
    page, total = paginate(rows, limit, offset)
    return ok_array([dm.cert_pub(r) for r in page], limit, offset, total)


@bp.post("/demonstrators/<did>/certifications/<cert_id>/revoke")
def revoke_certification(did, cert_id):
    v.guard(("ProgramAdmin", "StaffingCoordinator"))
    body = v.json_body()
    v.opt_string(body, "reason")
    dem = dm.resolve(db.demonstrators, did, "ERR_DEMONSTRATOR_NOT_FOUND")
    row = dm.resolve(db.certifications, cert_id, "ERR_RESOURCE_NOT_FOUND")
    if row["demonstrator_id"] != dem["id"]:
        fail("ERR_RESOURCE_NOT_FOUND", "certificate does not belong to this demonstrator.")
    row["revoked_at"] = iso_now()
    touch(row)
    return ok(dm.cert_pub(row))


# ===========================================================================
# EquipmentUnit
# ===========================================================================
@bp.post("/equipment-units")
def create_equipment_unit():
    caller = v.guard(("ProgramAdmin", "ClubOperations"))
    body = v.json_body()
    club_id = v.req_string(body, "club_id")
    asset_tag = v.req_string(body, "asset_tag")
    equipment_type = v.req_enum(body, "equipment_type", calc.EQUIPMENT_TYPES)
    club = dm.resolve(db.clubs, club_id, "ERR_CLUB_NOT_FOUND")
    v.check_ownership(caller, club_id=club["id"])

    for other in db.equipment_units.values():
        if other["club_id"] == club["id"] and other["asset_tag"] == asset_tag:
            fail("ERR_DUPLICATE_RESOURCE", "asset_tag already registered at this club.")

    row = new_row(
        club_id=club["id"],
        asset_tag=asset_tag,
        equipment_type=equipment_type,
        requires_food_cert=equipment_type in calc.FOOD_CERT_EQUIPMENT_TYPES,
        sanitation_status="SANITIZED",
        last_sanitized_at=None,
    )
    db.equipment_units[row["id"]] = row
    return ok(dm.pub(row), 201)


@bp.get("/equipment-units/<uid>")
def get_equipment_unit(uid):
    v.guard(("ProgramAdmin", "ClubOperations", "StaffingCoordinator"))
    row = dm.resolve(db.equipment_units, uid, "ERR_RESOURCE_NOT_FOUND")
    return ok(dm.pub(row))


@bp.get("/equipment-units")
def list_equipment_units():
    v.guard(("ProgramAdmin", "ClubOperations", "StaffingCoordinator"))
    limit, offset = v.pagination()
    club_id = request.args.get("club_id")
    equipment_type = v.query_enum("equipment_type", calc.EQUIPMENT_TYPES)
    sanitation_status = v.query_enum("sanitation_status", calc.SANITATION_STATUSES)
    rows = by_seq(list(db.equipment_units.values()))
    if club_id is not None:
        rows = [r for r in rows if r["club_id"] == club_id]
    if equipment_type is not None:
        rows = [r for r in rows if r["equipment_type"] == equipment_type]
    if sanitation_status is not None:
        rows = [r for r in rows if r["sanitation_status"] == sanitation_status]
    page, total = paginate(rows, limit, offset)
    return ok_array([dm.pub(r) for r in page], limit, offset, total)


@bp.patch("/equipment-units/<uid>")
def patch_equipment_unit(uid):
    caller = v.guard(("ProgramAdmin", "ClubOperations"))
    body = v.json_body()
    sanitation_status = v.req_enum(body, "sanitation_status", calc.SANITATION_STATUSES)
    row = dm.resolve(db.equipment_units, uid, "ERR_RESOURCE_NOT_FOUND")
    v.check_ownership(caller, club_id=row["club_id"])

    row["sanitation_status"] = sanitation_status
    if sanitation_status == "SANITIZED":
        row["last_sanitized_at"] = iso_now()
    touch(row)
    return ok(dm.pub(row))


# ===========================================================================
# Test-driving endpoints
# ===========================================================================
@bp.post("/_clock/set_current_utc")
def set_clock():
    v.guard(("ProgramAdmin",))
    body = v.json_body()
    raw = v.req_present(body, "to_iso8601")
    parsed = calc.parse_instant(raw)
    if parsed is None:
        fail("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 UTC instant.")
    db.clock = parsed
    return ok({"current_utc": raw})


@bp.post("/_inject/assignment-history")
def inject_assignment_history():
    v.guard(("ProgramAdmin",))
    body = v.json_body()
    demonstrator_id = v.req_string(body, "demonstrator_id")
    demo_event_id = v.req_string(body, "demo_event_id")
    entries = v.req_present(body, "entries")
    if not isinstance(entries, list):
        fail("ERR_VALIDATION", "entries must be an array.")

    parsed_entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            fail("ERR_VALIDATION", "every entries member must be an object.")
        parsed_entries.append(
            {
                "scheduled_start_utc": v.req_present(entry, "scheduled_start_utc"),
                "scheduled_end_utc": v.req_present(entry, "scheduled_end_utc"),
                "assignment_status": v.req_enum(
                    entry, "assignment_status", calc.ASSIGNMENT_STATUSES
                ),
                "role": v.req_enum(entry, "role", calc.ASSIGNMENT_ROLES),
                "check_in_at": entry.get("check_in_at"),
                "check_out_at": entry.get("check_out_at"),
            }
        )
        for field in ("scheduled_start_utc", "scheduled_end_utc", "check_in_at", "check_out_at"):
            value = parsed_entries[-1][field]
            if value is None:
                continue
            if calc.parse_instant(value) is None:
                fail("ERR_VALIDATION", "%s must be an ISO 8601 UTC instant." % field)

    dem = dm.resolve(db.demonstrators, demonstrator_id, "ERR_DEMONSTRATOR_NOT_FOUND")
    event = dm.resolve(db.demo_events, demo_event_id, "ERR_DEMO_EVENT_NOT_FOUND")

    created = []
    for entry in parsed_entries:
        row = new_row(
            demo_event_id=event["id"],
            demonstrator_id=dem["id"],
            replaces_assignment_id=None,
            role=entry["role"],
            travel_authorized=False,
            assignment_status=entry["assignment_status"],
            scheduled_start_utc=entry["scheduled_start_utc"],
            scheduled_end_utc=entry["scheduled_end_utc"],
            check_in_at=entry["check_in_at"],
            check_out_at=entry["check_out_at"],
            hours_worked=0.00,
            billable_hours=0.00,
            late_check_in=False,
        )
        row["late_check_in"] = dm.compute_late_check_in(row)
        dm.apply_attendance_figures(row)
        db.assignments[row["id"]] = row
        created.append(row)

    dm.recompute_demonstrator_metrics(dem)
    touch(dem)
    return ok_array([dm.pub(r) for r in created], 10, 0, len(created), 201)
