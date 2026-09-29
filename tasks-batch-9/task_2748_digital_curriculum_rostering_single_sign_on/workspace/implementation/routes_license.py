"""Vendor licenses, seat entitlement, building allocation and the two computed reads."""
from flask import Blueprint

import auth
import calc
import cascade
import envelope
import serial
import shape
import store
from errors import ApiError
from routes_reads import fetch

bp = Blueprint("license", __name__)


def _allocation_sums(vendor_id):
    allocated = 0
    borrowed = 0
    for allocation in store.building_allocations.values():
        if allocation.get("vendor_app_id") != vendor_id:
            continue
        allocated += allocation.get("allocated_seats") or 0
        borrowed += allocation.get("borrowed_seats") or 0
    return allocated, borrowed


# ------------------------------------------------------------- registration
@bp.post("/rostering/vendor-apps")
def create_vendor_app():
    actor = auth.require(auth.VENDOR_INTEGRATION_MANAGER)
    body = shape.body()
    name = shape.req_str(body, "name", 1, 120)
    vendor_code = shape.req_str(body, "vendor_code", 1, 32)
    term_id = shape.req_id(body, "term_id")
    rostering_standard = shape.req_enum(body, "rostering_standard",
                                       shape.ROSTERING_STANDARDS)
    identifier_strategy = shape.req_enum(body, "identifier_strategy",
                                        shape.IDENTIFIER_STRATEGIES)
    username_domain = shape.req_str(body, "username_domain", 3, 64)
    if "@" in username_domain or username_domain != username_domain.lower():
        shape.bad("username_domain must be lower-case and contain no at-sign.")
    name_format = shape.opt_enum(body, "name_format", shape.NAME_FORMATS, "LAST_FIRST")
    grade_band_scope = shape.req_enum_array(body, "grade_band_scope", shape.GRADE_BANDS)
    seat_model = shape.req_enum(body, "seat_model", shape.SEAT_MODELS)
    allocation_policy = shape.req_enum(body, "allocation_policy",
                                       shape.ALLOCATION_POLICIES)
    if allocation_policy == "FIXED_BUILDING_BLOCKS":
        block_seats = shape.req_int(body, "block_seats", 1, 10000)
    else:
        if shape.present(body, "block_seats"):
            shape.bad("block_seats is only accepted for FIXED_BUILDING_BLOCKS.")
        block_seats = None
    overage_policy = shape.opt_enum(body, "overage_policy", shape.OVERAGE_POLICIES,
                                    "BLOCK")
    unmatched = shape.opt_enum(body, "unmatched_teacher_policy",
                               shape.UNMATCHED_TEACHER_POLICIES, "HOLD_RUN")
    total_seats = shape.req_int(body, "total_seats", 1, 100000)
    price = shape.req_int(body, "price_per_seat_cents", 1, 10000000)

    fetch(store.terms, term_id, "ERR_TERM_NOT_FOUND")

    record = {
        "name": name,
        "vendor_code": vendor_code,
        "created_by_user_id": actor.user_id,
        "activated_by_user_id": None,
        "term_id": term_id,
        "rostering_standard": rostering_standard,
        "identifier_strategy": identifier_strategy,
        "username_domain": username_domain,
        "name_format": name_format,
        "grade_band_scope": list(grade_band_scope),
        "seat_model": seat_model,
        "allocation_policy": allocation_policy,
        "block_seats": block_seats,
        "overage_policy": overage_policy,
        "unmatched_teacher_policy": unmatched,
        "total_seats": total_seats,
        "price_per_seat_cents": price,
        "status": "DRAFT",
        "unallocated_seats": total_seats,
        "consumed_seats": 0,
        "committed_charge_cents": 0,
        "renewal_score": None,
        "renewal_recommendation": None,
        "sync_health": "OK",
    }
    store.stamp_new(record)
    store.vendor_apps[record["id"]] = record
    return envelope.created(serial.vendor_app(record))


@bp.patch("/rostering/vendor-apps/<vendor_app_id>")
def amend_vendor_app(vendor_app_id):
    actor = auth.require(auth.VENDOR_INTEGRATION_MANAGER,
                         auth.DATA_GOVERNANCE_OFFICER)
    vendor = store.vendor_apps.get(vendor_app_id)
    auth.vendor_scope(actor, vendor)
    if vendor is None:
        raise ApiError("ERR_VENDOR_APP_NOT_FOUND", "No such vendor license.")
    body = shape.body()
    total_seats = shape.opt_int(body, "total_seats", None, 1, 100000)
    price = shape.opt_int(body, "price_per_seat_cents", None, 1, 10000000)
    overage = shape.opt_enum(body, "overage_policy", shape.OVERAGE_POLICIES)
    unmatched = shape.opt_enum(body, "unmatched_teacher_policy",
                               shape.UNMATCHED_TEACHER_POLICIES)
    target = shape.opt_enum(body, "status",
                            ["DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED"])
    if target == "DRAFT":
        shape.bad("A license can never be moved back to DRAFT.")

    current = vendor.get("status")
    if target == "SUSPENDED":
        if current == "SUSPENDED":
            target = None
        elif current != "ACTIVE":
            raise ApiError("ERR_VENDOR_APP_NOT_ACTIVE",
                           "Only an ACTIVE license can be suspended.")
    elif target == "ACTIVE":
        if current == "ACTIVE":
            raise ApiError("ERR_VENDOR_APP_ALREADY_ACTIVATED",
                           "The license is already ACTIVE.")
        if current != "SUSPENDED":
            raise ApiError("ERR_VENDOR_APP_NOT_ACTIVE",
                           "Only a SUSPENDED license can be resumed.")
    elif target == "TERMINATED":
        if current not in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_VENDOR_APP_NOT_ACTIVE",
                           "Only an ACTIVE or SUSPENDED license can be terminated.")

    effective_total = total_seats if total_seats is not None else vendor["total_seats"]
    if target == "ACTIVE":
        allocated, _borrowed = _allocation_sums(vendor_app_id)
        if allocated > effective_total:
            raise ApiError("ERR_ALLOCATION_EXCEEDS_LICENSE",
                           "The existing allocations no longer fit inside total_seats.")

    if total_seats is not None:
        vendor["total_seats"] = total_seats
    if price is not None:
        vendor["price_per_seat_cents"] = price
    if overage is not None:
        vendor["overage_policy"] = overage
    if unmatched is not None:
        vendor["unmatched_teacher_policy"] = unmatched

    if target == "TERMINATED":
        today = store.clock_date()
        now = store.fmt_instant(store.clock_now())
        for account in store.sorted_records(store.app_accounts):
            if account.get("_vendor_app_id") != vendor_app_id:
                continue
            if account.get("seat_status") not in ("RESERVED", "ACTIVE"):
                continue
            cascade.release_seat(account, today, identity="DEPROVISIONED",
                                 deprovision_date=today, recompute=False)
        for run in cascade.in_flight_runs(vendor_app_id):
            run["state"] = "SUPERSEDED"
            store.touch(run)
            for item in store.sorted_records(store.error_queue_items):
                if (item.get("sync_run_id") == run["id"]
                        and item.get("status") == "OPEN"):
                    item["status"] = "DISMISSED"
                    item["resolved_at"] = now
                    store.touch(item)
            cascade.recompute_run_counters(run)
        vendor["status"] = "TERMINATED"
    elif target is not None:
        vendor["status"] = target

    cascade.recompute_vendor(vendor, bump_version=False)
    store.touch(vendor)
    return envelope.ok(serial.vendor_app(vendor))


@bp.post("/rostering/vendor-apps/<vendor_app_id>/activate-license")
def activate_license(vendor_app_id):
    actor = auth.require(auth.DATA_GOVERNANCE_OFFICER)
    vendor = fetch(store.vendor_apps, vendor_app_id, "ERR_VENDOR_APP_NOT_FOUND")
    auth.segregation(actor, vendor.get("created_by_user_id"))
    if vendor.get("status") != "DRAFT":
        raise ApiError("ERR_VENDOR_APP_ALREADY_ACTIVATED",
                       "Only a DRAFT license can be activated.")
    candidates = calc.allocation_candidates(vendor)
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_BUILDINGS",
                       "No ACTIVE building sits inside the license's grade bands.")
    granted = calc.split_seats(vendor, candidates)
    hard_cap = vendor.get("overage_policy") == "BLOCK"
    total_granted = 0
    for school, seats in granted:
        allocation = {
            "vendor_app_id": vendor_app_id,
            "school_id": school["id"],
            "allocated_seats": seats,
            "consumed_seats": 0,
            "borrowed_seats": 0,
            "hard_cap": hard_cap,
            "eligible_headcount_snapshot": school.get("enrolled_student_count") or 0,
        }
        store.stamp_new(allocation)
        store.building_allocations[allocation["id"]] = allocation
        total_granted += seats
    vendor["status"] = "ACTIVE"
    vendor["activated_by_user_id"] = actor.user_id
    vendor["unallocated_seats"] = (vendor.get("total_seats") or 0) - total_granted
    store.touch(vendor)
    return envelope.ok(serial.vendor_app(vendor))


@bp.patch("/rostering/building-allocations/<building_allocation_id>")
def recut_allocation(building_allocation_id):
    actor = auth.require(auth.BUILDING_LICENSE_ADMIN, auth.DATA_GOVERNANCE_OFFICER)
    allocation = store.building_allocations.get(building_allocation_id)
    auth.building_scope(actor, allocation)
    if allocation is None:
        raise ApiError("ERR_BUILDING_ALLOCATION_NOT_FOUND", "No such allocation.")
    body = shape.body()
    allocated_seats = shape.req_int(body, "allocated_seats", 0, 100000)
    expected = shape.req_int(body, "expected_vendor_app_version", 1)
    vendor = store.vendor_apps.get(allocation.get("vendor_app_id"))
    if vendor is None or vendor.get("version") != expected:
        raise ApiError("ERR_STALE_VENDOR_APP_VERSION",
                       "expected_vendor_app_version does not match the license.")
    if vendor.get("status") != "ACTIVE":
        raise ApiError("ERR_VENDOR_APP_NOT_ACTIVE", "The license is not ACTIVE.")

    current = allocation.get("allocated_seats") or 0
    if allocated_seats > current:
        allocated_sum, borrowed_sum = _allocation_sums(vendor["id"])
        projected = allocated_sum - current + allocated_seats + borrowed_sum
        if projected > (vendor.get("total_seats") or 0):
            raise ApiError("ERR_ALLOCATION_EXCEEDS_LICENSE",
                           "The re-cut would exceed the purchased total.")
    elif allocated_seats < current:
        if allocated_seats < (allocation.get("consumed_seats") or 0):
            raise ApiError("ERR_ALLOCATION_BELOW_CONSUMED",
                           "Seats already in use cannot be reclaimed by arithmetic.")

    allocation["allocated_seats"] = allocated_seats
    allocation["hard_cap"] = vendor.get("overage_policy") == "BLOCK"
    store.touch(allocation)
    allocated_sum, borrowed_sum = _allocation_sums(vendor["id"])
    vendor["unallocated_seats"] = ((vendor.get("total_seats") or 0)
                                  - allocated_sum - borrowed_sum)
    store.touch(vendor)
    return envelope.ok(serial.building_allocation(allocation))


# ----------------------------------------------------------- computed reads
def _feed_username(vendor, subject_type, subject, taken):
    """Reuse a live account's username; otherwise derive it against `taken`."""
    subject_id = subject["id"]
    for account in store.sorted_records(store.app_accounts):
        if account.get("_vendor_app_id") != vendor["id"]:
            continue
        if account.get("seat_status") == "RELEASED":
            continue
        if account.get("subject_type") != subject_type:
            continue
        key = ("student_id" if subject_type == "STUDENT" else "teacher_id")
        if account.get(key) == subject_id and account.get("username"):
            return account["username"]
    localpart = calc.normalise_localpart(
        calc.raw_identifier(vendor, subject_type, subject))
    if localpart == "":
        return None
    domain = vendor["username_domain"]
    candidate = localpart + "@" + domain
    suffix = calc.COLLISION_SUFFIX_START
    while candidate in taken:
        candidate = "%s+%d@%s" % (localpart, suffix, domain)
        suffix += 1
    taken.add(candidate)
    return candidate


@bp.get("/rostering/vendor-apps/<vendor_app_id>/roster-feed")
def roster_feed(vendor_app_id):
    actor = auth.require(auth.ROSTER_OPERATOR, auth.DATA_GOVERNANCE_OFFICER,
                         auth.VENDOR_INTEGRATION_MANAGER)
    vendor = store.vendor_apps.get(vendor_app_id)
    auth.vendor_scope(actor, vendor)
    if vendor is None:
        raise ApiError("ERR_VENDOR_APP_NOT_FOUND", "No such vendor license.")
    include_archived = shape.qbool("include_archived") or False
    term = store.terms.get(vendor.get("term_id"))
    if include_archived and not calc.archived_read_permitted(term):
        raise ApiError("ERR_ARCHIVE_WINDOW_CLOSED",
                       "The archived-access window for this term is shut.")

    scope = calc.resolve_scope(vendor, None, include_archived)
    taken = calc.taken_usernames(vendor["id"])
    usernames = []
    display_names = []
    for student in scope.feed_students:
        usernames.append(_feed_username(vendor, "STUDENT", student, taken))
        display_names.append(calc.display_name(vendor, "STUDENT", student))
    for teacher in scope.teachers:
        usernames.append(_feed_username(vendor, "TEACHER", teacher, taken))
        display_names.append(calc.display_name(vendor, "TEACHER", teacher))

    return envelope.ok({
        "vendor_app_id": vendor_app_id,
        "rostering_standard": vendor.get("rostering_standard"),
        "section_count": len(scope.feed_sections),
        "student_count": len(scope.feed_students),
        "teacher_count": len(scope.teachers),
        "skipped_section_count": scope.skipped_section_count,
        "sections": [serial.section(s) for s in scope.feed_sections],
        "usernames": usernames,
        "display_names": display_names,
    })


@bp.get("/rostering/vendor-apps/<vendor_app_id>/renewal-summary")
def renewal_summary(vendor_app_id):
    actor = auth.require(auth.ROSTER_OPERATOR, auth.DATA_GOVERNANCE_OFFICER,
                         auth.VENDOR_INTEGRATION_MANAGER,
                         auth.BUILDING_LICENSE_ADMIN)
    vendor = store.vendor_apps.get(vendor_app_id)
    auth.vendor_scope(actor, vendor)
    if vendor is None:
        raise ApiError("ERR_VENDOR_APP_NOT_FOUND", "No such vendor license.")
    basis = shape.qstr("basis") or "final"
    if basis not in ("final", "provisional"):
        shape.bad("basis must be final or provisional.")

    figures = calc.renewal_figures(vendor, basis)
    invoice = calc.invoice_projection(vendor)
    data = {"vendor_app_id": vendor_app_id, "basis": basis}
    for field in ("consumed_seats", "provisioned_seats", "engaged_seats",
                  "utilization", "engagement", "cost_per_engaged_cents",
                  "cost_efficiency", "renewal_score", "renewal_recommendation"):
        data[field] = figures[field]
    for field in ("gross_seat_cents", "discount_rate", "discount_cents",
                  "net_seat_cents", "platform_fee_cents",
                  "shelfware_credit_cents", "invoice_total_cents"):
        data[field] = invoice[field]
    return envelope.ok(data)
