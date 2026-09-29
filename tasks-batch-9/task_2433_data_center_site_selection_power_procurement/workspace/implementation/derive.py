"""Store-aware derived-field reconciliation and the cross-entity cascades.

`reconcile()` runs at the end of every mutating request and recomputes every
*pure* derived field in dependency order, so no response ever exposes a figure
that lags the mutation the request performed.

Deliberately excluded from the blanket pass, because the specification pins them
to an enumerated trigger list rather than to "whenever an input moves":
  * `screening_score` / `hazard_tier`      - frozen at screening time
  * `water_headroom_mgal` / `water_feasible` - screen, drought declaration and the
    disqualification cascade only (see `refresh_water_feasibility`)
  * a zoning docket's `mitigation_cost_usd` / `conditions_escrow_usd` - filing,
    each objection, and the APPROVED/CONTINUED decision branches
  * `site_capital_commitment_usd` - requested per site via `mark_capital()`
"""

from decimal import Decimal

import calc
import constants as K
from db import store
from rounding import dec, q2, q3
from timeutil import parse_dt

ZERO = Decimal("0")
LIVE_SITE_STATUSES = ("DRAFT", "SCREENED", "COMMITTED")
DEMAND_STATUSES = ("SCREENED", "COMMITTED")


# --------------------------------------------------------------------------- #
# accessors
# --------------------------------------------------------------------------- #
def ordered(rows):
    """created_at ascending, insertion order as the total-order tie-break."""
    return sorted(rows, key=lambda row: (row["created_at"], row["_seq"]))


def sites_of_program(program_id):
    return ordered(
        [s for s in store.sites.values() if s["program_id"] == program_id]
    )


def sites_of_utility(utility_id):
    return ordered(
        [s for s in store.sites.values() if s["utility_id"] == utility_id]
    )


def sites_of_source(water_source_id):
    return ordered(
        [s for s in store.sites.values() if s["water_source_id"] == water_source_id]
    )


def apps_of_site(site_id):
    return ordered(
        [a for a in store.applications.values() if a["site_id"] == site_id]
    )


def apps_of_utility(utility_id):
    return ordered(
        [a for a in store.applications.values() if a["utility_id"] == utility_id]
    )


def live_app(site_id):
    """The site's single application that is not WITHDRAWN, or None."""
    for app in apps_of_site(site_id):
        if app["status"] != "WITHDRAWN":
            return app
    return None


def studies_of(application_id):
    return ordered(
        [s for s in store.load_studies.values() if s["application_id"] == application_id]
    )


def newest_study(application_id):
    rows = studies_of(application_id)
    if not rows:
        return None
    return sorted(rows, key=lambda r: (r["study_round"], r["created_at"], r["_seq"]))[-1]


def zoning_of(site_id):
    rows = ordered([z for z in store.zoning.values() if z["site_id"] == site_id])
    return rows[0] if rows else None


def objections_of(zoning_id):
    return ordered(
        [o for o in store.objections.values() if o["zoning_id"] == zoning_id]
    )


def negotiations_of(site_id):
    return ordered(
        [n for n in store.negotiations.values() if n["site_id"] == site_id]
    )


def options_of(site_id):
    return ordered([o for o in store.options.values() if o["site_id"] == site_id])


def options_of_program(program_id):
    site_ids = {s["id"] for s in store.sites.values() if s["program_id"] == program_id}
    return ordered([o for o in store.options.values() if o["site_id"] in site_ids])


def ppas_of_program(program_id):
    return ordered([p for p in store.ppas.values() if p["program_id"] == program_id])


def mark_capital(site_id):
    store.capital_dirty.add(site_id)


# --------------------------------------------------------------------------- #
# transmission overlap helpers
# --------------------------------------------------------------------------- #
def group_demand_mw(app, live, buffer_days):
    """The application's own requested MW plus every overlapping live member's."""
    total = dec(app["requested_mw"])
    for other in live:
        if other["id"] == app["id"]:
            continue
        if calc.buffered_overlap(
            app["window_start"],
            app["window_end"],
            other["window_start"],
            other["window_end"],
            buffer_days,
        ):
            total += dec(other["requested_mw"])
    return q3(total)


def concurrent_mw(app, utility):
    """Sum of the requested MW of every OTHER live application that overlaps."""
    live = [
        a
        for a in apps_of_utility(utility["id"])
        if a["status"] in K.LIVE_RESERVED_STATUSES and a["id"] != app["id"]
    ]
    total = ZERO
    for other in live:
        if calc.buffered_overlap(
            app["window_start"],
            app["window_end"],
            other["window_start"],
            other["window_end"],
            utility["commissioning_buffer_days"],
        ):
            total += dec(other["requested_mw"])
    return q3(total)


# --------------------------------------------------------------------------- #
# per-figure recomputation
# --------------------------------------------------------------------------- #
def site_capital_value(site):
    total = ZERO
    app = live_app(site["id"])
    if app is not None:
        total += dec(app["study_fee_usd"]) + dec(app["network_upgrade_cost_usd"])
    zoning = zoning_of(site["id"])
    if zoning is not None:
        total += dec(zoning["mitigation_cost_usd"]) + dec(
            zoning["conditions_escrow_usd"]
        )
    for option in options_of(site["id"]):
        if option["status"] == "EXERCISED":
            total += dec(option["net_purchase_usd"])
        elif option["status"] == "OPTIONED":
            total += dec(option["option_premium_usd"])
    return q2(total)


def risk_tier(site):
    program = store.programs.get(site["program_id"])
    utility = store.utilities.get(site["utility_id"])
    app = live_app(site["id"])

    if (
        app is not None
        and app["status"] == "ENERGIZATION_COMMITTED"
        and app["committed_energization_date"]
        and program is not None
        and parse_dt(app["committed_energization_date"])
        > parse_dt(program["required_energization_date"])
    ):
        return "BREACHED"

    not_locked = app is None or app["status"] in (
        "DRAFT",
        "SUBMITTED",
        "STUDY_COMPLETE",
    )
    if (
        not_locked
        and utility is not None
        and program is not None
        and q3(dec(utility["available_capacity_mw"]))
        < q3(dec(program["target_load_mw"]))
    ):
        return "AT_RISK"
    return "ON_TRACK"


def zoning_price(zoning):
    """Steps 1-5 of the mitigation waterfall, including cost and escrow."""
    zoning_pure(zoning)
    zoning["mitigation_cost_usd"] = calc.mitigation_cost(
        zoning["required_mitigation_tier"], zoning["noise_excess_dba"]
    )
    zoning["conditions_escrow_usd"] = calc.conditions_escrow(
        zoning["mitigation_cost_usd"]
    )


def zoning_pure(zoning):
    """Steps 1-3 only: the figures that never freeze."""
    objections = objections_of(zoning["id"])
    zoning["objection_count"] = len(objections)
    zoning["weighted_opposition_score"] = calc.weighted_opposition(
        [o["objection_type"] for o in objections]
    )
    zoning["noise_excess_dba"] = calc.noise_excess(
        zoning["projected_noise_dba"], zoning["noise_limit_dba"]
    )
    zoning["required_mitigation_tier"] = calc.required_mitigation_tier(
        zoning["noise_excess_dba"], zoning["weighted_opposition_score"]
    )


def refresh_water_feasibility(water_source_id):
    """Recompute every dependent site's headroom and only afterwards its
    feasibility flag, because feasibility reads the fresh headroom."""
    source = store.water_sources.get(water_source_id)
    if source is None:
        return
    supply = calc.effective_supply(
        source["annual_permitted_mgal"], source["drought_stage"]
    )
    sites = sites_of_source(water_source_id)
    affected = [s for s in sites if s["status"] in LIVE_SITE_STATUSES]

    for site in affected:
        other_demand = ZERO
        for sibling in sites:
            if sibling["id"] == site["id"]:
                continue
            if sibling["status"] in DEMAND_STATUSES:
                other_demand += dec(sibling["annual_water_demand_mgal"] or 0)
        site["water_headroom_mgal"] = q3(supply - other_demand)

    for site in affected:
        demand = site["annual_water_demand_mgal"]
        if demand is None or site["water_headroom_mgal"] is None:
            site["water_feasible"] = False
        else:
            site["water_feasible"] = dec(demand) <= dec(site["water_headroom_mgal"])


# --------------------------------------------------------------------------- #
# cascades
# --------------------------------------------------------------------------- #
def walk_back_application(app):
    """A reservation the revised ceiling can no longer absorb loses the
    reservation, not its place in line."""
    app["status"] = "SUBMITTED"
    app["reserved_mw"] = q3(ZERO)
    app["committed_energization_date"] = None
    app["delay_exposure_usd"] = q2(ZERO)


def revise_capacity(utility, revised_total_capacity_mw):
    utility["total_transmission_capacity_mw"] = q3(dec(revised_total_capacity_mw))
    ceiling = q3(dec(revised_total_capacity_mw))
    buffer_days = utility["commissioning_buffer_days"]

    live = [
        a
        for a in apps_of_utility(utility["id"])
        if a["status"] in K.LIVE_RESERVED_STATUSES
    ]
    # Most senior first, so the applications that keep their reservation are the
    # ones highest in the queue.
    live = sorted(
        live, key=lambda a: (a["queue_position"], a["created_at"], a["_seq"])
    )
    while live:
        over = [a for a in live if group_demand_mw(a, live, buffer_days) > ceiling]
        if not over:
            break
        victim = over[-1]  # the least senior application that still does not fit
        walk_back_application(victim)
        live.remove(victim)


def disqualify_site(site, reason):
    """The four-hop cascade plus its three direct effects. Hops 2-4 (the utility
    ledger, sibling risk tiers, the program rollups and queue contiguity) fall out
    of `reconcile()`."""
    site["status"] = "DISQUALIFIED"
    site["disqualification_reason"] = reason

    app = live_app(site["id"])
    if app is not None and app["status"] in K.QUEUED_STATUSES:
        app["status"] = "WITHDRAWN"
        app["withdrawal_reason"] = "SITE_DISQUALIFIED"
        app["reserved_mw"] = q3(ZERO)
        app["queue_position"] = 0

    for option in options_of(site["id"]):
        if option["status"] == "OPTIONED":
            option["status"] = "RELEASED"

    refresh_water_feasibility(site["water_source_id"])
    mark_capital(site["id"])


def expire_options(program):
    """Option-expiry sweep: OPTIONED options whose half-open window has closed."""
    clock = store.clock
    stamp = store.now_iso()
    lapsed = 0
    for site in sites_of_program(program["id"]):
        for option in options_of(site["id"]):
            if option["status"] != "OPTIONED":
                continue
            if parse_dt(option["window_end"]) <= clock:
                option["status"] = "LAPSED"
                option["lapsed_at"] = stamp
                lapsed += 1
                mark_capital(site["id"])
    return lapsed


# --------------------------------------------------------------------------- #
# the blanket reconciliation pass
# --------------------------------------------------------------------------- #
def reconcile():
    _water_sources()
    _options()
    _land_control()
    _applications()
    _utility_ledgers()
    _queue_positions()
    _risk_tiers()
    _zoning()
    _ppas()
    _site_capital()
    _programs()
    store.capital_dirty = set()


def _water_sources():
    for source in store.water_sources.values():
        source["stage_curtailment_pct"] = q2(
            K.STAGE_CURTAILMENT[source["drought_stage"]]
        )
        source["effective_supply_mgal"] = calc.effective_supply(
            source["annual_permitted_mgal"], source["drought_stage"]
        )
        demand = ZERO
        for site in sites_of_source(source["id"]):
            if site["status"] in DEMAND_STATUSES:
                demand += dec(site["annual_water_demand_mgal"] or 0)
        source["committed_annual_demand_mgal"] = q3(demand)


def _options():
    for option in store.options.values():
        if option["status"] == "EXERCISED":
            option["premium_credited_usd"] = calc.premium_credited(
                option["option_premium_usd"], option["premium_credit_pct"]
            )
            option["net_purchase_usd"] = calc.net_purchase(
                option["purchase_price_usd"], option["premium_credited_usd"]
            )
        else:
            option["premium_credited_usd"] = q2(ZERO)
            option["net_purchase_usd"] = q2(ZERO)


def _land_control():
    for site in store.sites.values():
        controlled = ZERO
        for option in options_of(site["id"]):
            if option["status"] in ("OPTIONED", "EXERCISED"):
                controlled += dec(option["acres"])
        pct, status = calc.land_control(controlled, site["gross_acres"])
        site["land_control_pct"] = pct
        site["land_control_status"] = status


def _applications():
    for app in store.applications.values():
        if app["status"] in K.LIVE_RESERVED_STATUSES:
            app["reserved_mw"] = q3(dec(app["requested_mw"]))
        else:
            app["reserved_mw"] = q3(ZERO)

        study = newest_study(app["id"])
        if study is None:
            app["diversified_peak_mw"] = None
            app["network_upgrade_cost_usd"] = q2(ZERO)
        else:
            app["diversified_peak_mw"] = study["diversified_peak_mw"]
            app["network_upgrade_cost_usd"] = study["network_upgrade_cost_usd"]


def _utility_ledgers():
    for utility in store.utilities.values():
        live = [
            a
            for a in apps_of_utility(utility["id"])
            if a["status"] in K.LIVE_RESERVED_STATUSES
        ]
        if not live:
            reserved = q3(ZERO)
        else:
            buffer_days = utility["commissioning_buffer_days"]
            reserved = q3(
                max(group_demand_mw(a, live, buffer_days) for a in live)
            )
        utility["reserved_capacity_mw"] = reserved
        utility["available_capacity_mw"] = q3(
            dec(utility["total_transmission_capacity_mw"]) - dec(reserved)
        )


def _queue_positions():
    for utility in store.utilities.values():
        ranked = [
            a
            for a in apps_of_utility(utility["id"])
            if a["status"] in K.QUEUED_STATUSES
        ]
        if utility["queue_policy"] == "FIRST_READY_FIRST_SERVED":

            def key(app):
                site = store.sites.get(app["site_id"]) or {}
                score = site.get("screening_score")
                score = dec(score) if score is not None else Decimal("-1")
                return (-score, app["submitted_at"] or "", app["created_at"], app["_seq"])

        else:

            def key(app):
                return (app["submitted_at"] or "", app["created_at"], app["_seq"])

        for index, app in enumerate(sorted(ranked, key=key), start=1):
            app["queue_position"] = index

        for app in apps_of_utility(utility["id"]):
            if app["status"] not in K.QUEUED_STATUSES:
                app["queue_position"] = 0


def _risk_tiers():
    for site in store.sites.values():
        if site["status"] == "DISQUALIFIED":
            continue
        site["energization_risk_tier"] = risk_tier(site)


def _zoning():
    for zoning in store.zoning.values():
        zoning_pure(zoning)


def _ppas():
    for ppa in store.ppas.values():
        ppa["annual_cost_usd"] = calc.annual_cost(
            ppa["annual_generation_mwh"], ppa["strike_price_usd_per_mwh"]
        )
        if ppa["status"] == "EXECUTED":
            ppa["credited_coverage_mwh"] = calc.ppa_credited_coverage(
                ppa["technology"],
                ppa["matching_mode"],
                ppa["annual_generation_mwh"],
                ppa["hourly_matched_mwh"],
            )
        else:
            ppa["credited_coverage_mwh"] = q3(ZERO)


def _site_capital():
    for site_id in list(store.capital_dirty):
        site = store.sites.get(site_id)
        if site is not None:
            site["site_capital_commitment_usd"] = site_capital_value(site)


def _programs():
    for program in store.programs.values():
        program["program_annual_load_mwh"] = calc.program_annual_load(
            program["target_load_mw"]
        )

        credited = ZERO
        for ppa in ppas_of_program(program["id"]):
            if ppa["status"] == "EXECUTED":
                credited += dec(ppa["credited_coverage_mwh"])
        program["renewable_coverage_pct"] = calc.coverage_pct(
            credited, program["program_annual_load_mwh"]
        )

        exposure = ZERO
        forfeited = ZERO
        capitalized = ZERO
        committed_total = ZERO
        for option in options_of_program(program["id"]):
            premium = dec(option["option_premium_usd"])
            committed_total += premium
            if option["status"] == "OPTIONED":
                exposure += premium
            elif option["status"] in ("LAPSED", "RELEASED"):
                forfeited += premium
            elif option["status"] == "EXERCISED":
                capitalized += premium
        program["option_exposure_usd"] = q2(exposure)
        program["forfeited_premium_usd"] = q2(forfeited)
        program["capitalized_premium_usd"] = q2(capitalized)
        program["premium_committed_total_usd"] = q2(committed_total)

        sites = sites_of_program(program["id"])
        program["full_land_control_site_count"] = sum(
            1
            for s in sites
            if s["status"] in LIVE_SITE_STATUSES and s["land_control_status"] == "FULL"
        )

        committed_load = ZERO
        committed_site = None
        for site in sites:
            if site["status"] == "COMMITTED":
                committed_site = site
            for app in apps_of_site(site["id"]):
                if app["status"] == "ENERGIZATION_COMMITTED":
                    committed_load += dec(app["requested_mw"])
        program["committed_load_mw"] = q3(committed_load)

        program["program_status"] = _program_status(committed_site)


def _program_status(committed_site):
    if committed_site is None:
        return "SCREENING"
    impaired = (
        committed_site["land_control_status"] != "FULL"
        or not committed_site["water_feasible"]
        or committed_site["energization_risk_tier"] == "BREACHED"
    )
    if impaired:
        return "STALLED"
    app = live_app(committed_site["id"])
    if app is not None and app["status"] == "ENERGIZATION_COMMITTED":
        return "ENERGIZATION_SECURED"
    return "SITE_COMMITTED"
