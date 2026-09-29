"""Lookups, derived-field recomputation and the three cascade families of PRD §2.9."""

from decimal import Decimal

from clockutil import fiscal_year_end
from db import db, ordered, touch
from errors import ApiError
from services import calc

TERMINAL_CASE_STATUSES = ("DENIED", "MSD_ALTERNATIVE_ADOPTED", "DE_ANNEXED")
LIVE_PARCEL_STATUSES = ("PROPOSED", "PENDING_ANNEX", "INCORPORATED")

NOT_FOUND_ERROR = {
    "statute_profiles": "ERR_STATUTE_PROFILE_NOT_FOUND",
    "municipalities": "ERR_MUNICIPALITY_NOT_FOUND",
    "service_providers": "ERR_SERVICE_PROVIDER_NOT_FOUND",
    "property_owners": "ERR_PROPERTY_OWNER_NOT_FOUND",
    "cases": "ERR_CASE_NOT_FOUND",
    "parcels": "ERR_PARCEL_NOT_FOUND",
    "petitions": "ERR_PETITION_NOT_FOUND",
    "consents": "ERR_CONSENT_NOT_FOUND",
    "analyses": "ERR_ANALYSIS_NOT_FOUND",
    "plans": "ERR_PLAN_NOT_FOUND",
    "commitments": "ERR_COMMITMENT_NOT_FOUND",
    "hearings": "ERR_HEARING_NOT_FOUND",
    "notices": "ERR_NOTICE_PUBLICATION_NOT_FOUND",
    "filings": "ERR_FILING_NOT_FOUND",
    "utility_accounts": "ERR_UTILITY_ACCOUNT_NOT_FOUND",
}


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def collection(name):
    return getattr(db, name)


def soft(name, ident):
    """Resolve without raising — used by the scope checks that run before step 6."""
    if not isinstance(ident, str):
        return None
    return collection(name).get(ident)


def path_record(name, ident):
    """Step 6: a path identifier that must resolve, else the entity's own 404."""
    record = soft(name, ident)
    if record is None:
        raise ApiError(NOT_FOUND_ERROR[name])
    return record


def body_ref(name, ident):
    """Step 7: a body foreign key that must resolve, else ERR_REFERENCE_NOT_FOUND."""
    record = soft(name, ident)
    if record is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "A referenced %s does not exist." % name)
    return record


def rows(name):
    """Every record of a collection in created_at ascending order."""
    return ordered(list(collection(name).values()))


def where(name, **equals):
    return [r for r in rows(name) if all(r.get(k) == v for k, v in equals.items())]


# ---------------------------------------------------------------------------
# Walking to the case, the municipality and the statute
# ---------------------------------------------------------------------------

def municipality_of_case(case):
    return soft("municipalities", case.get("municipality_id")) if case else None


def statute_of_municipality(municipality):
    return soft("statute_profiles", municipality.get("statute_profile_id")) if municipality else None


def statute_of_case(case):
    return statute_of_municipality(municipality_of_case(case))


def case_of_parcel(parcel):
    return soft("cases", parcel.get("annexation_case_id")) if parcel else None


def case_of_petition(petition):
    return soft("cases", petition.get("annexation_case_id")) if petition else None


def case_of_consent(consent):
    if not consent:
        return None
    return case_of_petition(soft("petitions", consent.get("petition_id")))


def case_of_plan(plan):
    return soft("cases", plan.get("annexation_case_id")) if plan else None


def case_of_commitment(commitment):
    if not commitment:
        return None
    return case_of_plan(soft("plans", commitment.get("plan_of_services_id")))


def case_of_hearing(hearing):
    return soft("cases", hearing.get("annexation_case_id")) if hearing else None


def case_of_filing(filing):
    if not filing:
        return None
    return case_of_hearing(soft("hearings", filing.get("public_hearing_id")))


def case_of_analysis(analysis):
    return soft("cases", analysis.get("annexation_case_id")) if analysis else None


def case_of_account(account):
    if not account:
        return None
    return case_of_parcel(soft("parcels", account.get("parcel_id")))


def municipality_id_of_case(case):
    return case.get("municipality_id") if case else None


# ---------------------------------------------------------------------------
# Terminality (step 11)
# ---------------------------------------------------------------------------

def assert_case_not_terminal(case):
    if case is not None and case["status"] in TERMINAL_CASE_STATUSES:
        raise ApiError("ERR_CASE_TERMINAL", "The annexation case has reached a terminal status.")


# ---------------------------------------------------------------------------
# Territory
# ---------------------------------------------------------------------------

def own_parcels(case):
    return [p for p in rows("parcels") if p["annexation_case_id"] == case["id"]]


def territory_parcels(case):
    """PRD §3.2: annexation cases read their own parcels, de-annexation the predecessor's."""
    if case.get("case_type") == "DE_ANNEXATION":
        predecessor = soft("cases", case.get("predecessor_case_id"))
        if predecessor is None:
            return []
        return [
            p
            for p in rows("parcels")
            if p["annexation_case_id"] == predecessor["id"] and p["parcel_status"] == "INCORPORATED"
        ]
    return [
        p
        for p in rows("parcels")
        if p["annexation_case_id"] == case["id"] and p["parcel_status"] in LIVE_PARCEL_STATUSES
    ]


def territory_owner_count(case):
    return len({p["primary_owner_id"] for p in territory_parcels(case)})


def recompute_territory_aggregates(case):
    parcels = territory_parcels(case)
    count, acreage, value = calc.territory_aggregates(parcels)
    case["parcel_count"] = count
    case["territory_acreage"] = acreage
    case["territory_assessed_value_cents"] = value
    return parcels


def restamp_qualification(case):
    """The three statutory measurements — refreshed only while the case is DRAFT."""
    municipality = municipality_of_case(case)
    statute = statute_of_municipality(municipality)
    if municipality is None or statute is None:
        return None
    result = calc.territory_qualification(case, municipality, statute, case["territory_acreage"])
    case["contiguity_ratio"] = result["contiguity_ratio"]
    case["urban_development_qualified"] = result["urban_development_qualified"]
    case["qualification_index"] = result["qualification_index"]
    return result


# ---------------------------------------------------------------------------
# Petition aggregates
# ---------------------------------------------------------------------------

def qualifying_consents(petition):
    start = petition["circulation_started_at"]
    deadline = petition["circulation_deadline_at"]
    return [
        c
        for c in rows("consents")
        if c["petition_id"] == petition["id"]
        and c["consent_status"] == "SIGNED"
        and start <= c["signed_at"] <= deadline
    ]


def evaluate_petition(petition, case, statute):
    return calc.petition_sufficiency(
        petition,
        statute,
        qualifying_consents(petition),
        case["territory_assessed_value_cents"],
        territory_owner_count(case),
    )


def stamp_petition_aggregates(petition, case, statute):
    result = evaluate_petition(petition, case, statute)
    petition["qualified_signature_assessed_value_cents"] = result[
        "qualified_signature_assessed_value_cents"
    ]
    petition["qualified_signature_owner_count"] = result["qualified_signature_owner_count"]
    petition["signature_value_pct"] = result["signature_value_pct"]
    petition["signature_owner_pct"] = result["signature_owner_pct"]
    return result


# ---------------------------------------------------------------------------
# Plans, commitments, providers
# ---------------------------------------------------------------------------

def plan_commitments(plan):
    return [c for c in rows("commitments") if c["plan_of_services_id"] == plan["id"]]


def adopted_plan(case):
    for plan in rows("plans"):
        if plan["annexation_case_id"] == case["id"] and plan["adoption_status"] == "ADOPTED":
            return plan
    return None


def recompute_plan(plan, statute):
    live = [c for c in plan_commitments(plan) if c["commitment_status"] in ("ACTIVE", "FULFILLED")]
    required = statute["required_service_types"] if statute else []
    result = calc.plan_service_readiness(live, required)
    plan["committed_cost_cents"] = result["committed_cost_cents"]
    plan["covered_service_types"] = result["covered_service_types"]
    plan["service_readiness"] = result["service_readiness"]
    return result


def recompute_provider_encumbrance(provider):
    live = [
        c
        for c in rows("commitments")
        if c["service_provider_id"] == provider["id"]
        and c["commitment_status"] in ("ACTIVE", "FULFILLED")
    ]
    provider["encumbered_capacity_days"] = calc.encumbered_days(live)


def timeline_ceiling(statute, service_type):
    if service_type in ("POLICE", "FIRE"):
        return int(statute["police_fire_timeline_max_days"])
    return int(statute["water_sewer_timeline_max_days"])


# ---------------------------------------------------------------------------
# Hearings, notices, filings
# ---------------------------------------------------------------------------

def hearing_notices(hearing):
    return [n for n in rows("notices") if n["public_hearing_id"] == hearing["id"]]


def refresh_notice_published_at(hearing):
    published = [n for n in hearing_notices(hearing) if n["notice_status"] == "PUBLISHED"]
    if not published:
        hearing["notice_published_at"] = None
    else:
        hearing["notice_published_at"] = max(n["published_at"] for n in published)


def qualifying_filings(hearing):
    opens = hearing["protest_opens_at"]
    closes = hearing["protest_closes_at"]
    if opens is None or closes is None:
        return []
    return [
        f
        for f in rows("filings")
        if f["public_hearing_id"] == hearing["id"]
        and f["filing_status"] == "FILED"
        and opens <= f["filed_at"] <= closes
    ]


# ---------------------------------------------------------------------------
# Utility accounts
# ---------------------------------------------------------------------------

def parcel_accounts(parcel):
    return [a for a in rows("utility_accounts") if a["parcel_id"] == parcel["id"]]


def refresh_account_rate(account, municipality):
    surcharge = municipality["utility_outside_surcharge_pct"] if municipality else Decimal(0)
    account["effective_monthly_cents"] = calc.utility_effective_monthly_cents(
        account["monthly_base_cents"], account["rate_schedule"], surcharge
    )


# ---------------------------------------------------------------------------
# Cascade 1 — supersession (PRD §2.9, §3.3)
# ---------------------------------------------------------------------------

def supersession_cascade(case):
    """A petition that fell below threshold releases the hearing track it had earned."""
    case["status"] = "PETITION_CIRCULATING"
    for hearing in rows("hearings"):
        if hearing["annexation_case_id"] != case["id"]:
            continue
        if hearing["hearing_status"] != "SCHEDULED":
            continue
        hearing["hearing_status"] = "VACATED"
        for notice in hearing_notices(hearing):
            if notice["notice_status"] == "PUBLISHED":
                # NoticePublication has no updated_at and no version: the flip stamps nothing.
                notice["notice_status"] = "SUPERSEDED"
        hearing["notice_published_at"] = None
        touch(hearing)


# ---------------------------------------------------------------------------
# Cascade 2 — rescind (PRD §2.9, §3.7)
# ---------------------------------------------------------------------------

def rescind_cascade(case, statute):
    for parcel in own_parcels(case):
        if parcel["parcel_status"] == "PENDING_ANNEX":
            parcel["parcel_status"] = "EXCLUDED"
            touch(parcel)

    plan = adopted_plan(case)
    if plan is None:
        return
    plan["adoption_status"] = "RESCINDED"
    touched_providers = {}
    for commitment in plan_commitments(plan):
        if commitment["commitment_status"] not in ("DRAFT", "ACTIVE", "FULFILLED"):
            continue
        released = commitment["commitment_status"] in ("ACTIVE", "FULFILLED")
        commitment["commitment_status"] = "VOIDED"
        touch(commitment)
        if released:
            provider = soft("service_providers", commitment["service_provider_id"])
            if provider is not None:
                touched_providers[provider["id"]] = provider
    for provider in touched_providers.values():
        recompute_provider_encumbrance(provider)
        touch(provider)
    recompute_plan(plan, statute)
    touch(plan)


# ---------------------------------------------------------------------------
# Cascade 3 — effectuation (PRD §3.8) and its de-annexation mirror (PRD §3.9)
# ---------------------------------------------------------------------------

def effectuation_cascade(case, statute, municipality):
    plan = adopted_plan(case)

    # L1 — the case became EFFECTIVE, so PENDING_ANNEX parcels are INCORPORATED.
    incorporated = []
    for parcel in own_parcels(case):
        if parcel["parcel_status"] == "PENDING_ANNEX":
            parcel["parcel_status"] = "INCORPORATED"
            touch(parcel)
            incorporated.append(parcel)

    # L2 — their OUTSIDE_CITY accounts cut over and lose the surcharge.
    transitioning = []
    for parcel in incorporated:
        for account in parcel_accounts(parcel):
            if account["account_status"] != "OUTSIDE_CITY":
                continue
            account["account_status"] = "INSIDE_CITY_PENDING_TRANSITION"
            account["rate_schedule"] = "INSIDE_CITY"
            refresh_account_rate(account, municipality)
            touch(account)
            transitioning.append(account)

    # L3 — each cut-over account advances its matching ACTIVE commitment.
    if plan is not None:
        for account in transitioning:
            for commitment in plan_commitments(plan):
                if commitment["commitment_status"] != "ACTIVE":
                    continue
                if commitment["service_type"] != account["service_type"]:
                    continue
                if commitment["service_provider_id"] != account["service_provider_id"]:
                    continue
                commitment["activated_account_count"] = int(commitment["activated_account_count"]) + 1
                if int(commitment["activated_account_count"]) >= int(commitment["committed_account_count"]):
                    commitment["commitment_status"] = "FULFILLED"
                touch(commitment)
                break

        # L4 — the plan's coverage and readiness are re-derived.
        recompute_plan(plan, statute)
        touch(plan)

        # L5 — a READY plan promotes the pending accounts to active service.
        if plan["service_readiness"] == "READY":
            fulfilled_types = {
                c["service_type"]
                for c in plan_commitments(plan)
                if c["commitment_status"] == "FULFILLED"
            }
            for parcel in own_parcels(case):
                for account in parcel_accounts(parcel):
                    if account["account_status"] != "INSIDE_CITY_PENDING_TRANSITION":
                        continue
                    if account["service_type"] not in fulfilled_types:
                        continue
                    account["account_status"] = "INSIDE_CITY_ACTIVE"
                    touch(account)


def deannexation_cascade(case, statute, municipality):
    """L6 of effectuation for a DE_ANNEXATION case: unwind the predecessor."""
    predecessor = soft("cases", case.get("predecessor_case_id"))
    if predecessor is None:
        return
    predecessor["status"] = "DE_ANNEXED"

    for parcel in own_parcels(predecessor):
        if parcel["parcel_status"] != "INCORPORATED":
            continue
        parcel["parcel_status"] = "DE_ANNEXED"
        touch(parcel)
        for account in parcel_accounts(parcel):
            if account["account_status"] not in ("INSIDE_CITY_PENDING_TRANSITION", "INSIDE_CITY_ACTIVE"):
                continue
            account["account_status"] = "OUTSIDE_CITY"
            account["rate_schedule"] = "OUTSIDE_CITY_SURCHARGE"
            refresh_account_rate(account, municipality)
            touch(account)

    if predecessor["tax_roll_status"] == "POSTED":
        predecessor["tax_roll_status"] = "REVERSED"
        if municipality is not None:
            municipality["taxable_assessed_value_cents"] = int(
                municipality["taxable_assessed_value_cents"]
            ) - int(predecessor["tax_roll_transferred_assessed_value_cents"])
            touch(municipality)
        year_end = fiscal_year_end(case["effective_date"], statute["fiscal_year_end_month_day"])
        case["de_annexation_refund_cents"] = calc.de_annexation_refund_cents(
            statute["de_annexation_refund_basis"],
            predecessor["tax_roll_transferred_tax_cents"],
            case["effective_date"],
            year_end,
        )
    touch(predecessor)


def msd_cascade(case):
    for parcel in own_parcels(case):
        if parcel["parcel_status"] != "PENDING_ANNEX":
            continue
        parcel["parcel_status"] = "EXCLUDED"
        touch(parcel)
        for account in parcel_accounts(parcel):
            if account["account_status"] == "OUTSIDE_CITY":
                account["account_status"] = "DISCONNECTED"
                touch(account)
