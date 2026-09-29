"""Lookups, derived-value recomputation, cascades and the release gate ladder."""
from datetime import timedelta

import calc
from errors import fail
from store import by_created, db, iso, now, pdt, touch

OUTSTANDING_INVOICE_STATES = ("ISSUED", "PAST_DUE", "DELINQUENT")
DELINQUENT_ACCOUNT_STATES = ("DELINQUENT", "ABANDONMENT_NOTICE", "ABANDONED")


# ------------------------------------------------------------------ lookups
def find_enrollment(row_id):
    return db.enrollments.get(row_id)


def get_enrollment(row_id):
    row = db.enrollments.get(row_id)
    if row is None:
        fail("ERR_ENROLLMENT_NOT_FOUND")
    return row


def get_account(row_id):
    row = db.accounts.get(row_id)
    if row is None:
        fail("ERR_STORAGE_ACCOUNT_NOT_FOUND")
    return row


def get_kit(row_id):
    row = db.kits.get(row_id)
    if row is None:
        fail("ERR_KIT_NOT_FOUND")
    return row


def get_collection(row_id):
    row = db.collections.get(row_id)
    if row is None:
        fail("ERR_COLLECTION_NOT_FOUND")
    return row


def get_unit(row_id):
    row = db.units.get(row_id)
    if row is None:
        fail("ERR_UNIT_NOT_FOUND")
    return row


def get_run(row_id):
    row = db.runs.get(row_id)
    if row is None:
        fail("ERR_PROCESSING_RUN_NOT_FOUND")
    return row


def get_test(row_id):
    row = db.tests.get(row_id)
    if row is None:
        fail("ERR_QUALITY_TEST_NOT_FOUND")
    return row


def get_screening(row_id):
    row = db.screenings.get(row_id)
    if row is None:
        fail("ERR_SCREENING_NOT_FOUND")
    return row


def get_tank(row_id):
    row = db.tanks.get(row_id)
    if row is None:
        fail("ERR_TANK_NOT_FOUND")
    return row


def get_excursion(row_id):
    row = db.excursions.get(row_id)
    if row is None:
        fail("ERR_EXCURSION_NOT_FOUND")
    return row


def get_listing(row_id):
    row = db.listings.get(row_id)
    if row is None:
        fail("ERR_LISTING_NOT_FOUND")
    return row


def get_invoice(row_id):
    row = db.invoices.get(row_id)
    if row is None:
        fail("ERR_INVOICE_NOT_FOUND")
    return row


def get_reservation(row_id):
    row = db.reservations.get(row_id)
    if row is None:
        fail("ERR_RESERVATION_NOT_FOUND")
    return row


# ------------------------------------------------------------------ relations
def unit_enrollment(unit):
    return db.enrollments.get(unit.get("_enrollment_id"))


def enrollment_units(enrollment_id):
    return by_created([u for u in db.units.values()
                       if u.get("_enrollment_id") == enrollment_id])


def enrollment_account(enrollment_id):
    for account in by_created(list(db.accounts.values())):
        if account["enrollment_id"] == enrollment_id:
            return account
    return None


def unit_account(unit):
    if unit.get("storage_account_id"):
        return db.accounts.get(unit["storage_account_id"])
    return None


def account_units(account_id):
    return by_created([u for u in db.units.values()
                       if u.get("storage_account_id") == account_id])


def account_invoices(account_id):
    return by_created([i for i in db.invoices.values() if i["account_id"] == account_id])


def unit_tests(unit_id):
    return by_created([t for t in db.tests.values() if t["unit_id"] == unit_id])


def post_processing_test(unit_id):
    for test in unit_tests(unit_id):
        if test["test_kind"] == "POST_PROCESSING":
            return test
    return None


def unit_listings(unit_id):
    return by_created([l for l in db.listings.values() if l["unit_id"] == unit_id])


def unit_reservations(unit_id):
    return by_created([r for r in db.reservations.values() if r["unit_id"] == unit_id])


def unit_runs(unit_id):
    return by_created([r for r in db.runs.values() if r["unit_id"] == unit_id])


def kit_collections(kit_id):
    return by_created([c for c in db.collections.values() if c["kit_id"] == kit_id])


def enrollment_kits(enrollment_id):
    return by_created([k for k in db.kits.values() if k["enrollment_id"] == enrollment_id])


def enrollment_screenings(enrollment_id):
    return by_created([s for s in db.screenings.values()
                       if s["enrollment_id"] == enrollment_id])


def tank_units(tank_id):
    return by_created([u for u in db.units.values() if u.get("tank_id") == tank_id])


def tank_excursions(tank_id):
    rows = [e for e in db.excursions.values() if e["tank_id"] == tank_id]
    return sorted(rows, key=lambda r: (r["detected_at"], r["created_at"], r["_seq"]))


def live_excursion(tank_id):
    for row in tank_excursions(tank_id):
        if row["status"] in ("OPEN", "ACKNOWLEDGED", "ESCALATED"):
            return row
    return None


# ------------------------------------------------------------------ ownership
def require_pg_enrollment(user_id, role, enrollment_id):
    """Rung 3 -- compared before path existence, so no lookup is performed."""
    if role == "ParentGuardian" and enrollment_id != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")


def require_pg_account(user_id, role, account_id):
    if role != "ParentGuardian":
        return
    account = db.accounts.get(account_id)
    if account is not None and account["enrollment_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")


def require_pg_invoice(user_id, role, invoice_id):
    if role != "ParentGuardian":
        return
    invoice = db.invoices.get(invoice_id)
    if invoice is None:
        return
    account = db.accounts.get(invoice["account_id"])
    if account is not None and account["enrollment_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")


def require_tc_reservation(user_id, role, reservation_id):
    """Rung 4 -- a missing reservation falls through to rung 6."""
    if role != "TransplantCenter":
        return
    reservation = db.reservations.get(reservation_id)
    if reservation is not None and reservation["requesting_center_user_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")


# ------------------------------------------------------------------ screening
def completed_screenings(enrollment_id):
    return [s for s in enrollment_screenings(enrollment_id) if s["status"] == "COMPLETED"]


def governing_panel(enrollment_id):
    rows = completed_screenings(enrollment_id)
    return rows[-1] if rows else None


def has_current_completed_screening(enrollment_id):
    for row in completed_screenings(enrollment_id):
        valid_until = pdt(row["valid_until"])
        if valid_until is not None and valid_until >= now():
            return True
    return False


# ------------------------------------------------------------------ recomputation
def recompute_score(unit):
    test = post_processing_test(unit["id"])
    if test is None:
        return
    score = calc.acceptance_score(
        unit["program_type"], test["tnc_millions"], test["cd34_thousands"],
        test["viability_pct"], unit["post_processing_volume_ml"],
        test["sterility_result"])
    unit["quality_acceptance_score"] = calc.num(score)


def recompute_occupancy(tank):
    if tank is None:
        return
    count = 0
    for unit in db.units.values():
        if unit.get("tank_id") == tank["id"] and \
                unit["availability_status"] not in ("RELEASED", "DISPOSED"):
            count += 1
    if tank["occupied_slots"] != count:
        tank["occupied_slots"] = count
        touch(tank)


def recompute_excursion_minutes(tank):
    if tank is None:
        return
    window_start = now() - timedelta(days=calc.EXCURSION_WINDOW_DAYS)
    window_end = now()
    total = 0
    for row in tank_excursions(tank["id"]):
        if row["status"] not in ("RESOLVED", "CLOSED_LOSS"):
            continue
        detected = pdt(row["detected_at"])
        if detected is None or detected < window_start or detected > window_end:
            continue
        total += int(row["duration_minutes"] or 0)
    if tank["cumulative_excursion_minutes_30d"] != total:
        tank["cumulative_excursion_minutes_30d"] = total
        touch(tank)


def reconcile_balance(account):
    if account is None:
        return 0
    total = 0
    for invoice in account_invoices(account["id"]):
        if invoice["status"] in OUTSTANDING_INVOICE_STATES:
            total += invoice["amount_due_cents"] - invoice["amount_paid_cents"]
    if account["balance_cents"] != total:
        account["balance_cents"] = total
        touch(account)
    return total


def outstanding_balance(account):
    """Pure reconciliation with no write (settlement step 1)."""
    if account is None:
        return 0
    total = 0
    for invoice in account_invoices(account["id"]):
        if invoice["status"] in OUTSTANDING_INVOICE_STATES:
            total += invoice["amount_due_cents"] - invoice["amount_paid_cents"]
    return total


def account_premium_tank(account_id):
    """True when the single unit billed to this account sits in a PREMIUM tank."""
    for unit in account_units(account_id):
        tank_id = unit.get("tank_id")
        if tank_id:
            tank = db.tanks.get(tank_id)
            if tank is not None and tank["tank_class"] == "PREMIUM":
                return True
    return False


def refresh_invoice_total(invoice):
    invoice["amount_due_cents"] = (invoice["base_line_cents"]
                                   + invoice["surcharge_line_cents"]
                                   + invoice["admin_line_cents"]
                                   + invoice["late_fee_line_cents"])


def projected_settlement(account):
    """calculations.disposition_settlement -- steps 1..5, order pinned."""
    if account is None:
        return None
    balance = outstanding_balance(account)
    refund = calc.prorated_refund_cents(
        account["plan_term_years"],
        calc.unused_days(now(), pdt(account["paid_through_date"])))
    return calc.settlement_total_cents(balance, refund)


def post_settlement(account):
    """Compute, persist on the account, then reconcile the balance."""
    if account is None:
        return None
    total = projected_settlement(account)
    account["last_settlement_total_cents"] = total
    touch(account)
    reconcile_balance(account)
    return total


# ------------------------------------------------------------------ cascades
def cascade_consent_amendment(enrollment):
    """PRD 3.1 -- opening an amendment holds kits and suspends listings."""
    for kit in enrollment_kits(enrollment["id"]):
        if kit["status"] == "DISPATCHED":
            kit["status"] = "HELD"
            kit["hold_reason_code"] = "CONSENT_AMENDMENT_PENDING"
            touch(kit)
    for unit in enrollment_units(enrollment["id"]):
        for listing in unit_listings(unit["id"]):
            if listing["listing_status"] == "ACTIVE":
                listing["listing_status"] = "SUSPENDED"
                listing["suspension_reason_code"] = "CONSENT_AMENDMENT_PENDING"
                touch(listing)


def cascade_reconsent(enrollment):
    """PRD 3.1 -- the exact compensation of cascade_consent_amendment."""
    for kit in enrollment_kits(enrollment["id"]):
        if kit["status"] == "HELD":
            expires = pdt(kit["expires_at"])
            if expires is not None and expires < now():
                continue  # lapsed during the amendment; the nightly run expires it
            kit["status"] = "DISPATCHED"
            kit["hold_reason_code"] = None
            touch(kit)
    for unit in enrollment_units(enrollment["id"]):
        for listing in unit_listings(unit["id"]):
            if listing["listing_status"] == "SUSPENDED" and \
                    listing["suspension_reason_code"] == "CONSENT_AMENDMENT_PENDING":
                listing["listing_status"] = "ACTIVE"
                listing["suspension_reason_code"] = None
                touch(listing)


def cascade_maternal_reactive(enrollment):
    """PRD 3.4 -- three levels; availability_status is deliberately untouched."""
    for unit in enrollment_units(enrollment["id"]):
        if unit["eligibility_status"] != "ELIGIBLE":
            continue
        unit["eligibility_status"] = "INELIGIBLE"
        unit["eligibility_reason_code"] = "MATERNAL_REACTIVE"
        touch(unit)
        for listing in unit_listings(unit["id"]):
            if listing["listing_status"] in ("ACTIVE", "MATCHED"):
                listing["listing_status"] = "SUSPENDED"
                listing["suspension_reason_code"] = "MATERNAL_REACTIVE"
                touch(listing)
        for res in unit_reservations(unit["id"]):
            if res["status"] == "PENDING_CONFIRMATORY":
                res["status"] = "CANCELLED"
                res["cancellation_reason_code"] = "MATERNAL_REACTIVE"
                touch(res)


def cascade_quarantine(tank):
    """PRD 3.5 -- reading, tank, unit, listing, holds; created_at ASC throughout."""
    for unit in tank_units(tank["id"]):
        if unit["availability_status"] not in ("PRIVATE_STORED", "LISTED"):
            continue
        unit["availability_status"] = "QUARANTINED"
        unit["quarantine_reason_code"] = "EXCURSION_OPEN"
        touch(unit)
        for listing in unit_listings(unit["id"]):
            if listing["listing_status"] != "ACTIVE":
                continue
            listing["listing_status"] = "SUSPENDED"
            listing["suspension_reason_code"] = "UNIT_QUARANTINED"
            touch(listing)
            for res in unit_reservations(unit["id"]):
                if res["status"] == "PENDING_CONFIRMATORY":
                    res["status"] = "CANCELLED"
                    res["cancellation_reason_code"] = "LISTING_SUSPENDED"
                    touch(res)


def cascade_excursion_benign(tank):
    """PRD 3.5 -- units and listings return; cancelled holds are NOT revived."""
    for unit in tank_units(tank["id"]):
        if unit["availability_status"] != "QUARANTINED":
            continue
        quarantined_listings = [l for l in unit_listings(unit["id"])
                                if l["listing_status"] == "SUSPENDED"
                                and l["suspension_reason_code"] == "UNIT_QUARANTINED"]
        if unit["program_type"] == "PRIVATE_FAMILY":
            unit["availability_status"] = "PRIVATE_STORED"
        elif quarantined_listings:
            unit["availability_status"] = "LISTED"
        else:
            unit["availability_status"] = "UNAVAILABLE"
        unit["quarantine_reason_code"] = None
        touch(unit)
        for listing in quarantined_listings:
            listing["listing_status"] = "ACTIVE"
            listing["suspension_reason_code"] = None
            touch(listing)


def cascade_excursion_total_loss(tank):
    """PRD 3.5 -- units stay QUARANTINED, their suspended listings are withdrawn."""
    for unit in tank_units(tank["id"]):
        if unit["availability_status"] != "QUARANTINED":
            continue
        for listing in unit_listings(unit["id"]):
            if listing["listing_status"] == "SUSPENDED":
                listing["listing_status"] = "WITHDRAWN"
                touch(listing)


def void_outstanding_invoices(account):
    if account is None:
        return
    for invoice in account_invoices(account["id"]):
        if invoice["status"] in OUTSTANDING_INVOICE_STATES:
            invoice["status"] = "VOID"
            touch(invoice)
    reconcile_balance(account)


def write_off_outstanding_invoices(account):
    if account is None:
        return
    for invoice in account_invoices(account["id"]):
        if invoice["status"] in OUTSTANDING_INVOICE_STATES:
            invoice["status"] = "WRITTEN_OFF"
            touch(invoice)
    reconcile_balance(account)


def maybe_close_enrollment(enrollment):
    """PRD 3.1 -- COLLECTED -> CLOSED once every unit has left inventory."""
    if enrollment is None or enrollment["lifecycle_status"] != "COLLECTED":
        return
    units = enrollment_units(enrollment["id"])
    if not units:
        return
    for unit in units:
        if unit["availability_status"] not in ("DISPOSED", "RELEASED"):
            return
    enrollment["lifecycle_status"] = "CLOSED"
    touch(enrollment)
    account = enrollment_account(enrollment["id"])
    if account is not None and account["status"] in ("ACTIVE", "ABANDONED"):
        account["status"] = "CLOSED"
        touch(account)


def cure_delinquency(account):
    """PRD 3.8 -- a zero balance reverses the ladder for every live unit."""
    if account is None or account["balance_cents"] != 0:
        return
    status = account["status"]
    if status not in ("PAST_DUE", "DELINQUENT", "ABANDONMENT_NOTICE"):
        return
    account["status"] = "ACTIVE"
    account["delinquency_stage_entered_at"] = None
    touch(account)
    if status in ("DELINQUENT", "ABANDONMENT_NOTICE"):
        for unit in account_units(account["id"]):
            if unit["availability_status"] == "PENDING_ABANDONMENT":
                unit["availability_status"] = "PRIVATE_STORED"
                touch(unit)


def dispose_unit_cascade(unit, reason):
    """PRD 3.9 -- the widest cascade in the system, in its pinned order."""
    unit["processing_status"] = "DISCARDED"
    unit["availability_status"] = "DISPOSED"
    unit["disposition_reason"] = reason
    unit["disposed_at"] = iso(now())
    unit["quarantine_reason_code"] = None
    touch(unit)
    recompute_occupancy(db.tanks.get(unit.get("tank_id")))
    for listing in unit_listings(unit["id"]):
        if listing["listing_status"] in ("ACTIVE", "SUSPENDED", "MATCHED"):
            listing["listing_status"] = "WITHDRAWN"
            touch(listing)
    for res in unit_reservations(unit["id"]):
        if res["status"] in ("PENDING_CONFIRMATORY", "CONFIRMED"):
            res["status"] = "CANCELLED"
            res["cancellation_reason_code"] = "UNIT_DISPOSED"
            touch(res)
    account = unit_account(unit)
    if account is not None:
        post_settlement(account)
        if reason == "ABANDONED_NONPAYMENT":
            account["status"] = "CLOSED"
            touch(account)
            write_off_outstanding_invoices(account)
    maybe_close_enrollment(unit_enrollment(unit))


def withdraw_cascade(enrollment, prior_lifecycle):
    """PRD 3.1 -- the compensating reach grows with operational progress."""
    if prior_lifecycle == "CONSENT_PENDING":
        return
    for kit in enrollment_kits(enrollment["id"]):
        if kit["status"] in ("DISPATCHED", "HELD"):
            kit["status"] = "RETURNED"
            kit["hold_reason_code"] = None
            touch(kit)
    account = enrollment_account(enrollment["id"])
    if prior_lifecycle == "COLLECTED":
        for unit in enrollment_units(enrollment["id"]):
            if unit["availability_status"] in ("RELEASED", "DISPOSED"):
                continue
            unit["processing_status"] = "DISCARDED"
            unit["availability_status"] = "DISPOSED"
            unit["disposition_reason"] = "CONSENT_REVOKED"
            unit["disposed_at"] = iso(now())
            unit["quarantine_reason_code"] = None
            touch(unit)
            recompute_occupancy(db.tanks.get(unit.get("tank_id")))
            for listing in unit_listings(unit["id"]):
                if listing["listing_status"] in ("ACTIVE", "SUSPENDED"):
                    listing["listing_status"] = "WITHDRAWN"
                    touch(listing)
            for res in unit_reservations(unit["id"]):
                if res["status"] == "PENDING_CONFIRMATORY":
                    res["status"] = "CANCELLED"
                    res["cancellation_reason_code"] = "UNIT_DISPOSED"
                    touch(res)
    void_outstanding_invoices(account)


# ------------------------------------------------------------------ release gate
def release_blocking_error(reservation, user_id):
    """The §2.9 ladder restricted to the release gates; None when nothing blocks."""
    unit = db.units.get(reservation["unit_id"])
    if reservation["status"] != "CONFIRMED":
        return "ERR_INVALID_RESERVATION_STATE"
    if unit is None:
        return "ERR_UNIT_NOT_FOUND"
    # rung 10 -- segregation of duties against the eligibility determiner
    if unit.get("eligibility_determined_by_user_id") and \
            unit["eligibility_determined_by_user_id"] == user_id:
        return "ERR_SEGREGATION_OF_DUTIES"
    enrollment = unit_enrollment(unit)
    panel = governing_panel(enrollment["id"]) if enrollment is not None else None
    # rung 13 -- a completed, unexpired panel must exist
    if enrollment is None or panel is None or \
            not has_current_completed_screening(enrollment["id"]):
        return "ERR_MATERNAL_SCREENING_INCOMPLETE"
    # rung 14 -- the governing panel must read exactly NON_REACTIVE
    if panel["overall_result"] == "REACTIVE":
        return "ERR_MATERNAL_SCREENING_REACTIVE"
    if panel["overall_result"] != "NON_REACTIVE":
        return "ERR_MATERNAL_SCREENING_INCOMPLETE"
    # rung 17 -- a linked, passing confirmatory test
    test_id = reservation.get("confirmatory_test_id")
    test = db.tests.get(test_id) if test_id else None
    if test is None or test["outcome"] != "PASS":
        return "ERR_CONFIRMATORY_TEST_REQUIRED"
    # rung 18 -- unit eligibility
    if unit["eligibility_status"] != "ELIGIBLE":
        return "ERR_UNIT_NOT_ELIGIBLE"
    # rung 19 -- POST_THAW dose floor
    dose = reservation.get("post_thaw_dose_x1e7_per_kg")
    if dose is None or calc.D(dose) < calc.MIN_RELEASE_DOSE_X1E7:
        return "ERR_DOSE_BELOW_MINIMUM"
    # rung 28 -- the holding tank must be ONLINE
    tank = db.tanks.get(unit.get("tank_id"))
    if tank is None or tank["status"] != "ONLINE":
        return "ERR_TANK_NOT_OPERATIONAL"
    # rung 34 -- the fiscal rung scoped to release
    account = unit_account(unit)
    if account is not None and (account["status"] in DELINQUENT_ACCOUNT_STATES
                                or account["balance_cents"] != 0):
        return "ERR_OUTSTANDING_BALANCE"
    return None


def release_summary(reservation, user_id):
    """PRD 3.7 -- read-only pre-flight; mutates nothing."""
    unit = db.units.get(reservation["unit_id"])
    test_id = reservation.get("confirmatory_test_id")
    test = db.tests.get(test_id) if test_id else None
    recovery = None
    if test is not None and unit is not None and unit.get("post_processing_tnc_millions"):
        recovery = calc.num(calc.confirmatory_recovery_pct(
            test["tnc_millions"], unit["post_processing_tnc_millions"]))
    dose = reservation.get("post_thaw_dose_x1e7_per_kg")
    enrollment = unit_enrollment(unit) if unit is not None else None
    panel = governing_panel(enrollment["id"]) if enrollment is not None else None
    tank = db.tanks.get(unit.get("tank_id")) if unit is not None else None
    account = unit_account(unit) if unit is not None else None
    return {
        "reservation_id": reservation["id"],
        "unit_id": reservation["unit_id"],
        "pre_cryo_dose_x1e7_per_kg": reservation.get("pre_cryo_dose_x1e7_per_kg"),
        "post_thaw_dose_x1e7_per_kg": dose,
        "confirmatory_recovery_pct": recovery,
        "dose_gate_passed": dose is not None
        and calc.D(dose) >= calc.MIN_RELEASE_DOSE_X1E7,
        "confirmatory_test_present": test is not None,
        "maternal_result": panel["overall_result"] if panel is not None else None,
        "tank_status": tank["status"] if tank is not None else None,
        "account_balance_cents": account["balance_cents"] if account is not None else 0,
        "projected_settlement_total_cents": projected_settlement(account),
        "blocking_error_id": release_blocking_error(reservation, user_id),
    }
