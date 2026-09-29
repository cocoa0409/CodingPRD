"""Derived-field calculations, rollups and cascades (PRD sections 2.10-2.11, 3.x)."""

from datetime import timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from constants import (
    AGE_DECAY_PER_YEAR,
    CONDITION_MULT,
    DUTY_UPLIFT_PCT,
    FAILURE_CREDIT_FACTOR,
    FINISH_SURCHARGE_CENTS,
    FIRMWARE_SUPPORT_COMMITMENT_DAYS,
    FREE_FREIGHT_THRESHOLD_CENTS,
    FREIGHT_RATE_CENTS_PER_KG,
    INSTALL_HOURS_PER_UNIT,
    INSTALL_JOB_OPEN,
    INSTALL_LABOR_RATE_CENTS,
    PM_BASE_HOURS,
    PUNCH_LIST_CREDIT_CENTS,
    RESIDUAL_BASE,
    RESIDUAL_FLOOR,
    RUNNING_PROJECTION_FACTOR,
    SERVICE_PENALTY_PER_VISIT,
    TIER_MULTIPLIER,
    UNSUPPORTED_CONSOLE_MULT,
    USAGE_NORM_HOURS,
    VOLUME_DISCOUNT_TIERS,
    WARRANTY_DAYS,
)
from errors import ApiError
from store import fmt_iso, mutate, parse_iso, store

ONE = Decimal(1)
CENT = Decimal(1)
HUNDREDTH = Decimal("0.01")


# ---------------------------------------------------------------------------
# numeric helpers
# ---------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


def money_round(value):
    """Round half up to a whole number of cents."""
    return int(dec(value).quantize(CENT, rounding=ROUND_HALF_UP))


def hours_round(value):
    """Round half up to two decimal places."""
    return dec(value).quantize(HUNDREDTH, rounding=ROUND_HALF_UP)


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def dt(value):
    """Parse a stored ISO-8601 string into an aware datetime (or None)."""
    if value is None:
        return None
    return parse_iso(value)


def plus_days(instant, days):
    return fmt_iso(instant + timedelta(days=days))


def whole_days_between(earlier, later):
    """Whole days from earlier to later, fractional part discarded."""
    seconds = (later - earlier).total_seconds()
    return floor_int(Decimal(seconds) / Decimal(86400))


# ---------------------------------------------------------------------------
# row lookups
# ---------------------------------------------------------------------------
def model_of_revision(revision):
    return store.equipment_models[revision["equipment_model_id"]]


def revision_of_asset(asset):
    return store.model_revisions[asset["model_revision_id"]]


def model_of_asset(asset):
    return model_of_revision(revision_of_asset(asset))


def model_of_line(line):
    return model_of_revision(store.model_revisions[line["model_revision_id"]])


def order_lines(order_id, active_only=False):
    rows = [
        line
        for line in store.order_lines.values()
        if line["order_id"] == order_id
        and (not active_only or line["status"] == "ACTIVE")
    ]
    # Lines are processed by created_at ascending. The sort is stable over the
    # store's insertion order, so lines sharing a creation timestamp keep the
    # order they were added in: the units minted from an order's first line
    # take the lower sequence numbers.
    rows.sort(key=lambda row: row["created_at"])
    return rows


def facility_assets(facility_id):
    return [
        asset
        for asset in store.serialized_assets.values()
        if asset["facility_id"] == facility_id
    ]


def in_service_assets(facility_id):
    return [
        asset for asset in facility_assets(facility_id) if asset["status"] == "IN_SERVICE"
    ]


def program_visits(program_id):
    return [
        visit
        for visit in store.maintenance_visits.values()
        if visit["pm_program_id"] == program_id
    ]


def partner_programs(partner_id):
    return [
        program
        for program in store.pm_programs.values()
        if program["service_partner_id"] == partner_id
    ]


# ---------------------------------------------------------------------------
# catalogue rollups
# ---------------------------------------------------------------------------
RELEASED_FAMILY = ("RELEASED", "SUNSET_ANNOUNCED", "OBSOLETE")


def model_revisions(model_id):
    return [
        revision
        for revision in store.model_revisions.values()
        if revision["equipment_model_id"] == model_id
    ]


def recompute_model(model):
    revisions = model_revisions(model["id"])
    live = [r for r in revisions if r["status"] != "SUPERSEDED"]
    released_count = sum(1 for r in revisions if r["status"] in RELEASED_FAMILY)

    if revisions and not live:
        lifecycle = "SUNSET"
    elif not live or not any(r["status"] in RELEASED_FAMILY for r in live):
        lifecycle = "PRE_RELEASE"
    elif any(r["status"] == "RELEASED" for r in live):
        lifecycle = "ACTIVE"
    elif any(r["status"] == "SUNSET_ANNOUNCED" for r in live):
        lifecycle = "SUNSET"
    else:
        lifecycle = "OBSOLETE"

    with mutate(model):
        model["lifecycle_status"] = lifecycle
        model["released_revision_count"] = released_count


def recompute_model_of(revision):
    recompute_model(model_of_revision(revision))


# ---------------------------------------------------------------------------
# durability testing
# ---------------------------------------------------------------------------
def revision_runs(revision_id):
    return [
        run
        for run in store.test_runs.values()
        if run["model_revision_id"] == revision_id
    ]


def cycle_input_runs(revision_id):
    runs = [
        run
        for run in revision_runs(revision_id)
        if run["status"] in ("COMPLETED", "RUNNING") and not run["superseded_by_rework"]
    ]
    runs.sort(key=lambda run: (dt(run["window_end"]), run["created_at"], run["id"]))
    return runs


def cycle_counts(revision_id):
    runs = cycle_input_runs(revision_id)

    verified = 0
    for run in runs:
        if run["status"] == "RUNNING":
            continue
        if run["outcome"] == "PASSED":
            verified += run["achieved_cycles"] or 0
        elif run["outcome"] == "FAILED":
            verified += run["failure_cycle_count"] or 0
            break

    projected = 0
    for run in runs:
        if run["status"] == "RUNNING":
            projected += floor_int(dec(run["target_cycles"]) * RUNNING_PROJECTION_FACTOR)
        elif run["outcome"] == "PASSED":
            projected += run["achieved_cycles"] or 0
        elif run["outcome"] == "FAILED":
            projected += floor_int(
                dec(run["failure_cycle_count"] or 0) * FAILURE_CREDIT_FACTOR
            )

    completed = sum(1 for run in runs if run["status"] == "COMPLETED")
    running = sum(1 for run in runs if run["status"] == "RUNNING")
    return verified, projected, completed, running


def recompute_revision_cycles(revision):
    verified, projected, _, _ = cycle_counts(revision["id"])
    with mutate(revision):
        revision["verified_cycle_count"] = verified
        revision["projected_cycle_count"] = projected


def recompute_rig(rig):
    occupied = sum(
        1
        for run in store.test_runs.values()
        if run["test_rig_id"] == rig["id"] and run["status"] in ("RESERVED", "RUNNING")
    )
    with mutate(rig):
        rig["occupied_station_count"] = occupied


def has_outstanding_runs(revision_id):
    return any(
        run["status"] in ("RESERVED", "RUNNING") for run in revision_runs(revision_id)
    )


# ---------------------------------------------------------------------------
# firmware
# ---------------------------------------------------------------------------
def release_certifications(release_id):
    return [
        cert
        for cert in store.firmware_certifications.values()
        if cert["firmware_release_id"] == release_id
    ]


def revision_certifications(revision_id):
    return [
        cert
        for cert in store.firmware_certifications.values()
        if cert["model_revision_id"] == revision_id
    ]


def recompute_release(release):
    count = sum(
        1
        for cert in release_certifications(release["id"])
        if cert["cert_status"] == "CERTIFIED"
    )
    with mutate(release):
        release["certified_revision_count"] = count


def sunset_horizon(instant):
    return plus_days(instant, FIRMWARE_SUPPORT_COMMITMENT_DAYS)


# ---------------------------------------------------------------------------
# order pricing
# ---------------------------------------------------------------------------
def price_line(line):
    model = model_of_line(line)
    unit = model["unit_list_price_cents"] + sum(
        FINISH_SURCHARGE_CENTS[code] for code in line["finish_codes"]
    )
    extended = money_round(
        dec(unit) * dec(line["quantity"]) * (ONE + DUTY_UPLIFT_PCT[model["duty_class"]])
    )
    with mutate(line):
        line["unit_price_cents"] = unit
        line["extended_price_cents"] = extended


def recompute_order_configuration(order):
    """Re-price the active lines and refresh subtotal and chargeable weight."""
    lines = order_lines(order["id"], active_only=True)
    for line in lines:
        price_line(line)
    subtotal = sum(line["extended_price_cents"] for line in lines)
    weight = Decimal(0)
    for line in lines:
        weight += dec(line["quantity"]) * dec(model_of_line(line)["shipping_weight_kg"])
    with mutate(order):
        order["line_subtotal_cents"] = subtotal
        order["chargeable_weight_kg"] = weight


def volume_discount_rate(discount_base_cents):
    for lower, upper, rate in VOLUME_DISCOUNT_TIERS:
        if discount_base_cents >= lower and (upper is None or discount_base_cents < upper):
            return rate
    return Decimal(0)


def assemble_total(order, install_hours, punch_list_credit_cents):
    """The eight pinned steps of PRD 3.6."""
    facility = store.facilities[order["facility_id"]]
    line_subtotal = order["line_subtotal_cents"]
    install_amount = money_round(dec(install_hours) * INSTALL_LABOR_RATE_CENTS)
    discount_base = line_subtotal + install_amount
    volume_discount = money_round(dec(discount_base) * volume_discount_rate(discount_base))
    discounted_base = discount_base - volume_discount
    if discounted_base >= FREE_FREIGHT_THRESHOLD_CENTS:
        freight = 0
    else:
        freight = money_round(
            dec(order["chargeable_weight_kg"])
            * FREIGHT_RATE_CENTS_PER_KG[facility["freight_zone"]]
        )
    total = discounted_base + freight - punch_list_credit_cents
    return {
        "line_subtotal_cents": line_subtotal,
        "install_amount_cents": install_amount,
        "discount_base_cents": discount_base,
        "volume_discount_cents": volume_discount,
        "discounted_base_cents": discounted_base,
        "freight_cents": freight,
        "punch_list_credit_cents": punch_list_credit_cents,
        "total": total,
    }


def provisional_install_hours(order):
    hours = Decimal(0)
    for line in order_lines(order["id"], active_only=True):
        model = model_of_line(line)
        hours += dec(line["quantity"]) * INSTALL_HOURS_PER_UNIT[model["category"]]
    return hours


def apply_provisional_pricing(order):
    breakdown = assemble_total(order, provisional_install_hours(order), 0)
    with mutate(order):
        order["install_amount_cents"] = breakdown["install_amount_cents"]
        order["volume_discount_cents"] = breakdown["volume_discount_cents"]
        order["freight_cents"] = breakdown["freight_cents"]
        order["punch_list_credit_cents"] = 0
        order["quoted_total_cents"] = breakdown["total"]
        order["final_total_cents"] = None
        order["price_variant_applied"] = "PROVISIONAL"
        order["quoted_at"] = store.now_iso()
        order["billing_status"] = "QUOTED"
    return breakdown


def apply_final_pricing(order, job):
    punch_credit = PUNCH_LIST_CREDIT_CENTS * (job["punch_list_open_count"] or 0)
    breakdown = assemble_total(order, job["actual_labor_hours"], punch_credit)
    with mutate(order):
        order["install_amount_cents"] = breakdown["install_amount_cents"]
        order["volume_discount_cents"] = breakdown["volume_discount_cents"]
        order["freight_cents"] = breakdown["freight_cents"]
        order["punch_list_credit_cents"] = punch_credit
        order["final_total_cents"] = breakdown["total"]
        order["price_variant_applied"] = "FINAL"
        order["billing_status"] = "INVOICED"
        order["amount_due_cents"] = (
            breakdown["total"] - order["tradein_credit_applied_cents"]
        )
    return breakdown


def invalidate_quote(order):
    """Configuration change while CONFIGURING resets the provisional quote."""
    if order["config_status"] != "CONFIGURING" or order["billing_status"] != "QUOTED":
        return
    with mutate(order):
        order["billing_status"] = "UNQUOTED"
        order["quoted_total_cents"] = 0
        order["install_amount_cents"] = 0
        order["volume_discount_cents"] = 0
        order["freight_cents"] = 0
        order["punch_list_credit_cents"] = 0
        order["price_variant_applied"] = "NONE"
        order["quoted_at"] = None


def price_breakdown(order):
    discount_base = order["line_subtotal_cents"] + order["install_amount_cents"]
    discounted_base = discount_base - order["volume_discount_cents"]
    return {
        "line_subtotal_cents": order["line_subtotal_cents"],
        "install_amount_cents": order["install_amount_cents"],
        "discount_base_cents": discount_base,
        "volume_discount_cents": order["volume_discount_cents"],
        "discounted_base_cents": discounted_base,
        "chargeable_weight_kg": order["chargeable_weight_kg"],
        "freight_cents": order["freight_cents"],
        "punch_list_credit_cents": order["punch_list_credit_cents"],
        "quoted_total_cents": order["quoted_total_cents"],
        "final_total_cents": order["final_total_cents"],
        "tradein_credit_applied_cents": order["tradein_credit_applied_cents"],
        "amount_due_cents": order["amount_due_cents"],
        "price_variant_applied": order["price_variant_applied"],
    }


def order_categories(order):
    return {
        model_of_line(line)["category"]
        for line in order_lines(order["id"], active_only=True)
    }


def has_active_line(order):
    return bool(order_lines(order["id"], active_only=True))


# ---------------------------------------------------------------------------
# facility rollups (exposure + trade-in ledger, PRD 2.11)
# ---------------------------------------------------------------------------
def facility_orders(facility_id):
    return [
        order
        for order in store.orders.values()
        if order["facility_id"] == facility_id
    ]


def recompute_facility(facility):
    orders = facility_orders(facility["id"])
    exposure = sum(
        order["quoted_total_cents"]
        for order in orders
        if order["config_status"] == "CONFIRMED"
        and order["billing_status"] in ("QUOTED", "INVOICED")
    )
    granted = sum(
        asset["trade_in_valuation_cents"]
        for asset in facility_assets(facility["id"])
        if asset["trade_in_valuation_cents"] is not None
    )
    applied = sum(order["tradein_credit_applied_cents"] for order in orders)
    balance = granted - applied
    if balance < 0:
        raise ApiError(
            "ERR_TRADEIN_CREDIT_ALREADY_APPLIED",
            "The trade-in credit ledger may not go negative.",
        )
    with mutate(facility):
        facility["open_order_exposure_cents"] = exposure
        facility["tradein_credit_granted_cents"] = granted
        facility["tradein_credit_applied_cents"] = applied
        facility["tradein_credit_balance_cents"] = balance


# ---------------------------------------------------------------------------
# partner rollups (capacity + spare-stock ledger, PRD 2.11 / 3.7)
# ---------------------------------------------------------------------------
def partner_jobs(partner_id):
    return [
        job
        for job in store.install_jobs.values()
        if job["service_partner_id"] == partner_id
    ]


def recompute_partner(partner):
    committed = Decimal(0)
    for job in partner_jobs(partner["id"]):
        if job["status"] in INSTALL_JOB_OPEN:
            committed += dec(job["estimated_labor_hours"])
    reserved = 0
    consumed = 0
    for program in partner_programs(partner["id"]):
        if program["status"] in ("ACTIVE", "NEEDS_REVISION"):
            committed += dec(program["annual_labor_hours_committed"])
        for visit in program_visits(program["id"]):
            if visit["status"] == "SCHEDULED":
                reserved += visit["reserved_units"]
            elif visit["status"] == "COMPLETED":
                consumed += visit["reserved_units"]
    received = partner["spare_stock_received_units"]
    on_hand = received - reserved - consumed
    if on_hand < 0:
        raise ApiError(
            "ERR_INSUFFICIENT_PART_STOCK",
            "The partner's spare-stock ledger may not go negative.",
        )
    coverage = (
        "OVER_COMMITTED"
        if committed > dec(partner["certified_hours_capacity"])
        else "ACTIVE"
    )
    with mutate(partner):
        partner["committed_hours"] = committed
        partner["coverage_status"] = coverage
        partner["spare_stock_reserved_units"] = reserved
        partner["spare_stock_consumed_units"] = consumed
        partner["spare_stock_on_hand_units"] = on_hand


def partner_committed_hours(partner):
    """Current committed hours without persisting anything."""
    committed = Decimal(0)
    for job in partner_jobs(partner["id"]):
        if job["status"] in INSTALL_JOB_OPEN:
            committed += dec(job["estimated_labor_hours"])
    for program in partner_programs(partner["id"]):
        if program["status"] in ("ACTIVE", "NEEDS_REVISION"):
            committed += dec(program["annual_labor_hours_committed"])
    return committed


# ---------------------------------------------------------------------------
# preventive maintenance rollups
# ---------------------------------------------------------------------------
def visits_per_year(visit_interval_days):
    return -(-365 // visit_interval_days)


def program_rollup(facility_id, tier, visit_interval_days):
    assets = in_service_assets(facility_id)
    per_year = visits_per_year(visit_interval_days)
    total = Decimal(0)
    for asset in assets:
        model = model_of_asset(asset)
        usage_factor = min(
            Decimal(2), max(ONE, dec(asset["annual_usage_hours"]) / USAGE_NORM_HOURS)
        )
        total += (
            PM_BASE_HOURS[model["category"]]
            * usage_factor
            * TIER_MULTIPLIER[tier]
            * dec(per_year)
        )
    return len(assets), hours_round(total)


def recompute_program(program):
    count, hours = program_rollup(
        program["facility_id"], program["tier"], program["visit_interval_days"]
    )
    with mutate(program):
        program["covered_asset_count"] = count
        program["annual_labor_hours_committed"] = hours


def facility_programs(facility_id, statuses=None):
    rows = [
        program
        for program in store.pm_programs.values()
        if program["facility_id"] == facility_id
        and (statuses is None or program["status"] in statuses)
    ]
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    return rows


def recompute_facility_programs(facility_id, statuses=("ACTIVE",)):
    """Recompute the facility's programs and then their delivering partners."""
    partners = set()
    for program in facility_programs(facility_id, statuses):
        recompute_program(program)
        partners.add(program["service_partner_id"])
    recompute_partners(partners)


def recompute_partners(partner_ids):
    for partner_id in sorted(partner_ids):
        partner = store.service_partners.get(partner_id)
        if partner is not None:
            recompute_partner(partner)


def facility_categories(facility_id):
    return {model_of_asset(asset)["category"] for asset in in_service_assets(facility_id)}


def release_visit_units(visit):
    """A visit that stops holding stock simply changes status; the ledger is derived."""
    return visit


def hold_program_visits(program, reason="PROGRAM_NEEDS_REVISION"):
    for visit in program_visits(program["id"]):
        if visit["status"] == "SCHEDULED":
            with mutate(visit):
                visit["status"] = "ON_HOLD"
                visit["held_reason"] = reason


# ---------------------------------------------------------------------------
# serialized assets
# ---------------------------------------------------------------------------
def recompute_asset_support(asset):
    revision = revision_of_asset(asset)
    model = model_of_revision(revision)

    warranty_expires = None
    starts = dt(asset["warranty_starts_at"])
    if starts is not None:
        warranty_expires = plus_days(starts, WARRANTY_DAYS[model["duty_class"]])

    release = None
    if asset["installed_firmware_release_id"]:
        release = store.firmware_releases.get(asset["installed_firmware_release_id"])

    if not model["connected"]:
        support_expires = None
        status = "NOT_APPLICABLE"
    elif release is not None and release["status"] == "WITHDRAWN":
        support_expires = release["withdrawn_at"]
        status = "FIRMWARE_REVOKED"
    elif revision["firmware_support_until"] is None:
        support_expires = None
        status = "SUPPORTED"
    else:
        support_expires = revision["firmware_support_until"]
        if warranty_expires is None or dt(support_expires) >= dt(warranty_expires):
            status = "SUNSET_TRACKED"
        else:
            status = "SUPPORT_GAP"

    if support_expires is None or warranty_expires is None:
        gap = 0
    else:
        gap = max(0, whole_days_between(dt(support_expires), dt(warranty_expires)))

    with mutate(asset):
        asset["warranty_expires_at"] = warranty_expires
        asset["firmware_support_expires_at"] = support_expires
        asset["support_gap_days"] = gap
        asset["connectivity_support_status"] = status


def asset_visits(asset_id):
    return [
        visit
        for visit in store.maintenance_visits.values()
        if visit["serialized_asset_id"] == asset_id
    ]


def recompute_asset_service_history(asset):
    completed = [v for v in asset_visits(asset["id"]) if v["status"] == "COMPLETED"]
    hours = Decimal(0)
    for visit in completed:
        hours += dec(visit["labor_hours"])
    with mutate(asset):
        asset["service_history_count"] = len(completed)
        asset["accrued_service_labor_hours"] = hours


def trade_in_valuation(asset, grade):
    model = model_of_asset(asset)
    starts = dt(asset["warranty_starts_at"])
    if starts is None:
        age_years = 0
    else:
        age_years = floor_int(
            Decimal(whole_days_between(starts, store.now())) / Decimal(365)
        )
    residual = (
        RESIDUAL_BASE
        - AGE_DECAY_PER_YEAR * dec(age_years)
        - SERVICE_PENALTY_PER_VISIT * dec(asset["service_history_count"])
    )
    if residual < RESIDUAL_FLOOR:
        residual = RESIDUAL_FLOOR
    horizon = dt(asset["firmware_support_expires_at"])
    if model["connected"] and horizon is not None and horizon <= store.now():
        console_mult = UNSUPPORTED_CONSOLE_MULT
    else:
        console_mult = ONE
    return money_round(
        dec(model["unit_list_price_cents"]) * residual * CONDITION_MULT[grade] * console_mult
    )


def next_sequence_no(revision_id):
    highest = 0
    for asset in store.serialized_assets.values():
        if asset["model_revision_id"] == revision_id:
            highest = max(highest, asset["sequence_no"])
    return highest + 1


def line_assets(line_id):
    return [
        asset
        for asset in store.serialized_assets.values()
        if asset["order_line_id"] == line_id
    ]


def order_assets(order):
    rows = []
    for line in order_lines(order["id"], active_only=True):
        rows.extend(line_assets(line["id"]))
    return rows


# ---------------------------------------------------------------------------
# install completion cascade (PRD 3.7)
# ---------------------------------------------------------------------------
def install_completion_cascade(job):
    order = store.orders[job["order_id"]]
    facility = store.facilities[order["facility_id"]]

    with mutate(job):
        job["completed_at"] = store.now_iso()
        job["status"] = "COMPLETED"

    with mutate(order):
        order["fulfillment_status"] = "INSTALLED"
    if order["billing_status"] == "QUOTED":
        apply_final_pricing(order, job)

    recompute_facility(facility)

    for asset in order_assets(order):
        if asset["status"] != "BUILT":
            continue
        with mutate(asset):
            asset["status"] = "IN_SERVICE"
            asset["warranty_starts_at"] = store.now_iso()
        recompute_asset_support(asset)

    partners = {job["service_partner_id"]}
    for program in facility_programs(facility["id"], ("ACTIVE",)):
        recompute_program(program)
        partners.add(program["service_partner_id"])
    recompute_partners(partners)


# ---------------------------------------------------------------------------
# sunset and firmware-withdrawal cascades
# ---------------------------------------------------------------------------
def sunset_cascade(revision):
    affected_facilities = set()
    for asset in store.serialized_assets.values():
        if asset["model_revision_id"] != revision["id"] or asset["status"] != "IN_SERVICE":
            continue
        recompute_asset_support(asset)
        affected_facilities.add(asset["facility_id"])

    partners = set()
    for facility_id in sorted(affected_facilities):
        for program in facility_programs(facility_id, ("ACTIVE",)):
            with mutate(program):
                program["status"] = "NEEDS_REVISION"
                program["needs_revision_reason"] = "CONSOLE_SUPPORT_LOST"
            recompute_program(program)
            hold_program_visits(program)
            partners.add(program["service_partner_id"])
    recompute_partners(partners)


def withdrawal_cascade(release):
    for cert in release_certifications(release["id"]):
        if cert["cert_status"] == "CERTIFIED":
            with mutate(cert):
                cert["cert_status"] = "REVOKED"
        elif cert["cert_status"] == "SUBMITTED":
            with mutate(cert):
                cert["cert_status"] = "REJECTED"
    recompute_release(release)

    affected_facilities = set()
    for asset in store.serialized_assets.values():
        if asset["installed_firmware_release_id"] != release["id"]:
            continue
        recompute_asset_support(asset)
        affected_facilities.add(asset["facility_id"])

    partners = set()
    for facility_id in sorted(affected_facilities):
        for program in facility_programs(facility_id, ("ACTIVE",)):
            if not any(
                asset["installed_firmware_release_id"] == release["id"]
                for asset in in_service_assets(facility_id)
            ):
                continue
            with mutate(program):
                program["status"] = "NEEDS_REVISION"
                program["needs_revision_reason"] = "FIRMWARE_REVOKED"
            recompute_program(program)
            hold_program_visits(program)
            partners.add(program["service_partner_id"])
    recompute_partners(partners)
