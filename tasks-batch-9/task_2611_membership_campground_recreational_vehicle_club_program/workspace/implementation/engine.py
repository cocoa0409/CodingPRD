"""Domain engine: night sets, capacity, occupancy runs, counters and cascades."""

from datetime import date, timedelta

import calc
import clock
import store

OCCUPYING_STATUSES = ("CONFIRMED", "CHECKED_IN", "EXTENSION_REVIEW")
RUN_STATUSES = ("CONFIRMED", "CHECKED_IN", "EXTENSION_REVIEW", "COMPLETED")
ACTIVE_STAY_STATUSES = ("CONFIRMED", "CHECKED_IN", "EXTENSION_REVIEW")
OPEN_RESERVATION_STATUSES = ("PENDING", "CONFIRMED", "WAITLISTED", "CHECKED_IN",
                            "EXTENSION_REVIEW")
BLOCKING_WINDOW_STATUSES = ("SCHEDULED", "ACTIVE")
LIVE_PROJECT_STATUSES = ("PROPOSED", "APPROVED", "DEFERRED")


# ---------------------------------------------------------------------------
# small date helpers
# ---------------------------------------------------------------------------
def as_date(value):
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def iso(value):
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return value


def nights_between(arrival, departure):
    return (as_date(departure) - as_date(arrival)).days


def each_night(arrival, departure):
    cursor = as_date(arrival)
    stop = as_date(departure)
    while cursor < stop:
        yield cursor
        cursor = cursor + timedelta(days=1)


def ranges_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection test."""
    return as_date(a_start) < as_date(b_end) and as_date(b_start) < as_date(a_end)


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def park_of(reservation):
    return store.get("parks", reservation.get("park_id"))


def tier_of(membership):
    return store.get("membership_tiers", membership.get("tier_id"))


def membership_of(reservation):
    return store.get("memberships", reservation.get("membership_id"))


def agreement_of(park):
    if not park or not park.get("affiliate_agreement_id"):
        return None
    return store.get("affiliate_agreements", park["affiliate_agreement_id"])


def reservations_at_park(park_id):
    return [r for r in store.all_rows("reservations") if r["park_id"] == park_id]


def reservations_of_membership(membership_id):
    return [r for r in store.all_rows("reservations")
            if r.get("membership_id") == membership_id]


def invoices_of_membership(membership_id):
    return store.ordered([r for r in store.all_rows("dues_invoices")
                          if r["membership_id"] == membership_id])


def surveys_of_park(park_id):
    return [s for s in store.all_rows("satisfaction_surveys")
            if s["park_id"] == park_id]


def projects_of_park(park_id):
    return [p for p in store.all_rows("capital_projects") if p["park_id"] == park_id]


def windows_of_park(park_id):
    return [w for w in store.all_rows("maintenance_windows") if w["park_id"] == park_id]


def inspections_of_park(park_id):
    return [i for i in store.all_rows("amenity_inspections") if i["park_id"] == park_id]


# ---------------------------------------------------------------------------
# capacity
# ---------------------------------------------------------------------------
def _committed(park_id, night, pools, exclude_ids=()):
    total = 0
    for res in reservations_at_park(park_id):
        if res["id"] in exclude_ids:
            continue
        if res["status"] not in OCCUPYING_STATUSES:
            continue
        if res.get("pool_charged") not in pools:
            continue
        if as_date(res["arrival_date"]) <= night < as_date(res["departure_date"]):
            total += 1
    return total


def member_pool_available(park, arrival, departure, exclude_ids=()):
    limit = park["member_pool_sites"]
    for night in each_night(arrival, departure):
        if _committed(park["id"], night, ("MEMBER_POOL",), exclude_ids) + 1 > limit:
            return False
    return True


def borrowed_transient_available(park, arrival, departure, exclude_ids=()):
    limit = park["transient_pool_sites"] - calc.TRANSIENT_FLOOR_SITES
    pools = ("TRANSIENT_POOL", "BORROWED_TRANSIENT")
    for night in each_night(arrival, departure):
        if _committed(park["id"], night, pools, exclude_ids) + 1 > limit:
            return False
    return True


def transient_available(park, arrival, departure, exclude_ids=()):
    limit = park["transient_pool_sites"]
    pools = ("TRANSIENT_POOL", "BORROWED_TRANSIENT")
    for night in each_night(arrival, departure):
        if _committed(park["id"], night, pools, exclude_ids) + 1 > limit:
            return False
    return True


def allocate_member_pool(park, arrival, departure, exclude_ids=()):
    """Returns MEMBER_POOL, BORROWED_TRANSIENT or None."""
    if member_pool_available(park, arrival, departure, exclude_ids):
        return "MEMBER_POOL"
    if borrowed_transient_available(park, arrival, departure, exclude_ids):
        return "BORROWED_TRANSIENT"
    return None


# ---------------------------------------------------------------------------
# merged occupancy run (per membership, per park)
# ---------------------------------------------------------------------------
def merged_run(membership_id, park_id, arrival, departure, exclude_res_id=None,
               created_at=None, seq=None):
    """Merge the candidate stay into the park's runs for this membership.

    Returns (run_nights, run_arrival, run_departure) for the run containing the
    candidate.
    """
    arrival = as_date(arrival)
    departure = as_date(departure)
    candidate = {
        "_candidate": True,
        "arrival": arrival,
        "departure": departure,
        "created_at": created_at or clock.now_iso(),
        "seq": seq if seq is not None else 10 ** 12,
    }
    stays = [candidate]
    for res in reservations_at_park(park_id):
        if res.get("membership_id") != membership_id:
            continue
        if exclude_res_id is not None and res["id"] == exclude_res_id:
            continue
        if res["status"] not in RUN_STATUSES:
            continue
        stays.append({
            "_candidate": False,
            "arrival": as_date(res["arrival_date"]),
            "departure": as_date(res["departure_date"]),
            "created_at": res.get("created_at") or "",
            "seq": res.get("_seq") or 0,
        })
    stays.sort(key=lambda s: (s["arrival"], s["created_at"], s["seq"]))

    runs = []
    current = None
    for stay in stays:
        if current is None:
            current = {"arrival": stay["arrival"], "departure": stay["departure"],
                       "has_candidate": stay["_candidate"]}
            continue
        link_limit = current["departure"] + timedelta(days=calc.LINK_GAP_NIGHTS)
        if stay["arrival"] <= link_limit:
            if stay["departure"] > current["departure"]:
                current["departure"] = stay["departure"]
            current["has_candidate"] = current["has_candidate"] or stay["_candidate"]
        else:
            runs.append(current)
            current = {"arrival": stay["arrival"], "departure": stay["departure"],
                       "has_candidate": stay["_candidate"]}
    if current is not None:
        runs.append(current)

    for run in runs:
        if run["has_candidate"]:
            return ((run["departure"] - run["arrival"]).days, run["arrival"],
                    run["departure"])
    return (nights_between(arrival, departure), arrival, departure)


def out_and_back_gap(membership_id, arrival, exclude_res_id=None):
    """Network-wide previous-stay gap, or None when there is no previous stay."""
    arrival = as_date(arrival)
    best = None
    for res in reservations_of_membership(membership_id):
        if exclude_res_id is not None and res["id"] == exclude_res_id:
            continue
        if res["status"] not in RUN_STATUSES:
            continue
        departure = as_date(res["departure_date"])
        if departure > arrival:
            continue
        if best is None:
            best = res
            continue
        best_dep = as_date(best["departure_date"])
        if departure > best_dep:
            best = res
        elif departure == best_dep and store.sort_key(res) < store.sort_key(best):
            best = res
    if best is None:
        return None
    return (arrival - as_date(best["departure_date"])).days


def has_overlapping_stay(membership_id, arrival, departure, exclude_res_id=None):
    for res in reservations_of_membership(membership_id):
        if exclude_res_id is not None and res["id"] == exclude_res_id:
            continue
        if res["status"] not in ACTIVE_STAY_STATUSES:
            continue
        if ranges_overlap(arrival, departure, res["arrival_date"], res["departure_date"]):
            return True
    return False


def has_maintenance_conflict(park_id, arrival, departure):
    arrival = as_date(arrival)
    departure = as_date(departure)
    for window in windows_of_park(park_id):
        if window["status"] not in BLOCKING_WINDOW_STATUSES:
            continue
        start = as_date(window["start_date"])
        end = as_date(window["end_date"]) + timedelta(days=1)
        if ranges_overlap(arrival, departure, start, end):
            return True
    return False


def window_intersects(window, reservation):
    start = as_date(window["start_date"])
    end = as_date(window["end_date"]) + timedelta(days=1)
    return ranges_overlap(reservation["arrival_date"], reservation["departure_date"],
                          start, end)


def stay_inside_season(park, arrival, departure):
    arrival = as_date(arrival)
    last_night = as_date(departure) - timedelta(days=1)
    return (arrival >= as_date(park["season_open_date"])
            and last_night <= as_date(park["season_close_date"]))


# ---------------------------------------------------------------------------
# entitlement counters
# ---------------------------------------------------------------------------
def class_bucket(park):
    return calc.CLASS_BUCKET[park["park_class"]]


def tier_bucket(park):
    return calc.TIER_ENTITLEMENT[park["park_class"]]


def _recompute_annual(membership):
    membership["annual_nights_used"] = (membership["nights_used_class_a"]
                                        + membership["nights_used_class_b"]
                                        + membership["nights_used_class_c"])


def debit_entitlement(membership, park, nights):
    if nights == 0:
        return
    bucket = class_bucket(park)
    membership[bucket] = membership[bucket] + nights
    _recompute_annual(membership)


def credit_entitlement(membership, park, nights):
    if nights == 0:
        return
    bucket = class_bucket(park)
    membership[bucket] = max(0, membership[bucket] - nights)
    _recompute_annual(membership)


def entitlement_headroom_ok(membership, tier, park, nights):
    bucket = class_bucket(park)
    allowed = tier[tier_bucket(park)]
    if membership[bucket] + nights > allowed:
        return False
    if membership["annual_nights_used"] + nights > tier["annual_total_night_cap"]:
        return False
    return True


# ---------------------------------------------------------------------------
# affiliate quota
# ---------------------------------------------------------------------------
def quota_charge_for(agreement, nights):
    return calc.affiliate_quota_nights(nights, agreement["reciprocity_ratio"])


def quota_headroom_ok(agreement, charged):
    return agreement["nights_consumed_ytd"] + charged <= agreement["annual_member_night_quota"]


def _recompute_settlement(agreement):
    agreement["settlement_owed_cents"] = (agreement["nights_consumed_ytd"]
                                          * agreement["settlement_rate_cents_per_night"])


def add_quota(agreement, charged):
    if agreement is None or charged == 0:
        return
    agreement["nights_consumed_ytd"] = agreement["nights_consumed_ytd"] + charged
    _recompute_settlement(agreement)
    store.touch(agreement)


def credit_quota(agreement, charged):
    if agreement is None or charged == 0:
        return
    agreement["nights_consumed_ytd"] = max(0, agreement["nights_consumed_ytd"] - charged)
    _recompute_settlement(agreement)
    store.touch(agreement)


# ---------------------------------------------------------------------------
# compensating release of a reservation's debits
# ---------------------------------------------------------------------------
def release_debits(reservation):
    """Credit entitlement and quota back and free the pool seat.

    Returns True when a member-pool (or borrowed) seat was released.
    """
    park = park_of(reservation)
    membership = membership_of(reservation)
    charged = reservation.get("entitlement_nights_charged") or 0
    if membership is not None and park is not None and charged:
        credit_entitlement(membership, park, charged)
        store.touch(membership)
    reservation["entitlement_nights_charged"] = 0

    affiliate = reservation.get("affiliate_nights_charged") or 0
    if affiliate:
        credit_quota(agreement_of(park), affiliate)
    reservation["affiliate_nights_charged"] = 0

    released_member_seat = reservation.get("pool_charged") in ("MEMBER_POOL",
                                                              "BORROWED_TRANSIENT")
    reservation["pool_charged"] = "NONE"
    return released_member_seat


def force_cancel(reservation, reason):
    """CONFIRMED/PENDING -> CANCELLED, WAITLISTED -> EXPIRED. Returns seat release."""
    was_waitlisted = reservation["status"] == "WAITLISTED"
    released = release_debits(reservation)
    reservation["status"] = "EXPIRED" if was_waitlisted else "CANCELLED"
    reservation["cancellation_reason"] = reason
    store.touch(reservation)
    return released


# ---------------------------------------------------------------------------
# waitlist promotion
# ---------------------------------------------------------------------------
def _promote(reservation):
    park = park_of(reservation)
    membership = membership_of(reservation)
    reservation["pool_charged"] = "MEMBER_POOL"
    reservation["status"] = "CONFIRMED"
    nights = reservation["nights"]
    reservation["entitlement_nights_charged"] = nights
    debit_entitlement(membership, park, nights)
    agreement = agreement_of(park)
    if agreement is not None:
        charged = quota_charge_for(agreement, nights)
        reservation["affiliate_nights_charged"] = charged
        add_quota(agreement, charged)
    run_nights, _, _ = merged_run(reservation["membership_id"], park["id"],
                                  reservation["arrival_date"],
                                  reservation["departure_date"],
                                  exclude_res_id=reservation["id"],
                                  created_at=reservation.get("created_at"),
                                  seq=reservation.get("_seq"))
    reservation["consecutive_run_nights"] = run_nights
    store.touch(reservation)
    store.touch(membership)


def waitlist_sweep(park_id, min_arrival_after=None):
    """Promote eligible waitlisted member stays until nothing more fits."""
    promotions = 0
    while True:
        park = store.get("parks", park_id)
        if park is None:
            break
        candidates = [r for r in reservations_at_park(park_id)
                      if r["status"] == "WAITLISTED" and r.get("booker_type") == "MEMBER"]
        if min_arrival_after is not None:
            candidates = [r for r in candidates
                          if as_date(r["arrival_date"]) > as_date(min_arrival_after)]
        candidates.sort(key=lambda r: (r.get("created_at") or "",
                                       as_date(r["arrival_date"]),
                                       r.get("_seq") or 0))
        chosen = None
        for candidate in candidates:
            membership = membership_of(candidate)
            if membership is None:
                continue
            if membership["membership_status"] != "ACTIVE":
                continue
            if membership["dues_status"] not in ("CURRENT", "GRACE"):
                continue
            tier = tier_of(membership)
            if tier is None:
                continue
            if not member_pool_available(park, candidate["arrival_date"],
                                        candidate["departure_date"]):
                continue
            if not entitlement_headroom_ok(membership, tier, park, candidate["nights"]):
                continue
            chosen = candidate
            break
        if chosen is None:
            break
        _promote(chosen)
        promotions += 1
    return promotions


# ---------------------------------------------------------------------------
# park derivations: forced cancellations, compliance, rating, project scores
# ---------------------------------------------------------------------------
def forced_count(park):
    return (park.get("_forced_by_year") or {}).get(clock.today().year, 0)


def add_forced_cancellations(park, count):
    if count <= 0:
        return
    year = clock.today().year
    tally = park.setdefault("_forced_by_year", {})
    tally[year] = tally.get(year, 0) + count


def newest_inspection(park_id):
    rows = inspections_of_park(park_id)
    if not rows:
        return None
    rows.sort(key=lambda i: (i.get("inspected_at") or "", i.get("_seq") or 0))
    return rows[-1]


def rederive_compliance(park):
    inspection = newest_inspection(park["id"])
    if inspection is None:
        base = "COMPLIANT"
    else:
        base = calc.AMENITY_RESULT_STATUS[inspection["result"]]
    if (base == "COMPLIANT"
            and forced_count(park) >= calc.FORCED_CANCELLATION_PROBATION_THRESHOLD):
        base = "PROBATION"
    park["amenity_compliance_status"] = base
    return base


def survey_age_days(survey):
    submitted = survey.get("submitted_at") or ""
    submitted_date = date.fromisoformat(submitted[:10])
    return (clock.today() - submitted_date).days


def recompute_park_rating(park):
    surveys = surveys_of_park(park["id"])
    value = calc.recency_weighted_lifetime(surveys, survey_age_days)
    park["rating_score"] = float(value)
    return value


def trailing_rating(park):
    return calc.trailing_window_mean(surveys_of_park(park["id"]), survey_age_days)


def member_nights_ytd(park):
    year = clock.today().year
    total = 0
    for res in reservations_at_park(park["id"]):
        if res["status"] not in ("CHECKED_IN", "EXTENSION_REVIEW", "COMPLETED"):
            continue
        if as_date(res["arrival_date"]).year != year:
            continue
        total += res.get("entitlement_nights_charged") or 0
    return total


def project_priority(project, park):
    return calc.capital_priority_score(
        project["category"],
        park["amenity_compliance_status"],
        trailing_rating(park),
        member_nights_ytd(park),
        park["total_sites"],
        project["requested_cost_cents"],
    )


def recompute_project_scores(park, statuses=LIVE_PROJECT_STATUSES):
    for project in projects_of_park(park["id"]):
        if statuses is not None and project["status"] not in statuses:
            continue
        score = project_priority(project, park)
        if project.get("priority_score") != score:
            project["priority_score"] = score
            store.touch(project)


def recompute_funded_capital(park, fiscal_year):
    total = 0
    for project in projects_of_park(park["id"]):
        if project["status"] == "FUNDED" and project["fiscal_year"] == fiscal_year:
            total += project.get("funded_amount_cents") or 0
    park["funded_capital_cents_ytd"] = total


# ---------------------------------------------------------------------------
# membership / dues helpers
# ---------------------------------------------------------------------------
def tenure_years_of(membership):
    origin = (membership.get("tenure_origin_at") or "")[:10]
    if not origin:
        return 0
    elapsed = (clock.today() - date.fromisoformat(origin)).days
    if elapsed < 0:
        return 0
    return elapsed // calc.ENTITLEMENT_YEAR_DAYS


def recompute_tenure(membership):
    membership["tenure_years"] = tenure_years_of(membership)
    return membership["tenure_years"]


def recompute_dues_balance(membership):
    total = 0
    for invoice in invoices_of_membership(membership["id"]):
        if invoice["status"] not in ("OPEN", "PAST_DUE"):
            continue
        total += (invoice["amount_cents"] + invoice["late_fee_cents"]
                  - invoice["paid_amount_cents"])
    membership["dues_balance_cents"] = total
    return total


def issue_invoice(membership, cycle_year):
    tier = tier_of(membership)
    recompute_tenure(membership)
    parts = calc.dues_invoice_total(tier["annual_dues_cents"], membership["tenure_years"])
    invoice = store.base_row()
    invoice.update({
        "membership_id": membership["id"],
        "cycle_year": cycle_year,
        "amount_cents": parts["amount_cents"],
        "base_dues_cents": parts["base_dues_cents"],
        "capital_assessment_cents": parts["capital_assessment_cents"],
        "loyalty_credit_cents": parts["loyalty_credit_cents"],
        "late_fee_cents": 0,
        "paid_amount_cents": 0,
        "due_date": clock.fmt_date(clock.add_days(clock.today(), calc.DUES_NET_DAYS)),
        "paid_at": None,
        "status": "OPEN",
        "days_past_due": 0,
    })
    store.insert("dues_invoices", invoice)
    recompute_dues_balance(membership)
    return invoice


def void_submitted_transfers(membership, reason):
    voided = 0
    for request in store.ordered(store.all_rows("transfer_requests")):
        if request["membership_id"] != membership["id"]:
            continue
        if request["status"] != "SUBMITTED":
            continue
        request["status"] = "VOIDED"
        request["rejection_reason"] = reason
        request["decided_by_user_id"] = None
        store.touch(request)
        voided += 1
    return voided


def suspend_cascade(membership, reason, void_reason,
                    statuses=("PENDING", "CONFIRMED", "WAITLISTED"),
                    only_future=True):
    """Cancel the membership's upcoming stays, release seats, work the waitlists."""
    cancelled = 0
    touched_parks = []
    today = clock.today()
    for res in store.ordered(reservations_of_membership(membership["id"])):
        if res["status"] not in statuses:
            continue
        if only_future and as_date(res["arrival_date"]) <= today:
            continue
        released = force_cancel(res, "MEMBERSHIP_SUSPENDED")
        cancelled += 1
        if released and res["park_id"] not in touched_parks:
            touched_parks.append(res["park_id"])
    promotions = 0
    for park_id in touched_parks:
        promotions += waitlist_sweep(park_id)
    void_submitted_transfers(membership, void_reason)
    return {"cancelled": cancelled, "promotions": promotions}
