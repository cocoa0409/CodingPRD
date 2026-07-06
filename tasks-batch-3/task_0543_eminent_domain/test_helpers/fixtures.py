"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server and resets the DB and logical clock
before every test). Helpers use the lenient get_success_data() so setup failures
surface as clear "Setup failed" errors.

Identity threading: after creating an OwnershipInterest that will act as a
PropertyOwner, ownership-gated calls use make_property_owner_headers(oi["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_property_owner_headers
from .constants import (
    STD_LAND_CENTS, STD_IMPROVEMENTS_CENTS,
    STD_SEVERANCE_CENTS, STD_SPECIAL_BENEFITS_CENTS, STD_OFFER_BASIS_CENTS,
)

ADMIN = TEST_USERS["program_admin_headers"]
AGENT = TEST_USERS["right_of_way_agent_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]
ESCROW = TEST_USERS["escrow_officer_headers"]
UTILITY = TEST_USERS["utility_coordinator_headers"]

_apn_counter = [0]


def _next_apn(prefix="APN"):
    _apn_counter[0] += 1
    return f"{prefix}-{_apn_counter[0]}"


# ---- Atomic building blocks ------------------------------------------------

def set_clock(iso, api=api_client):
    return get_success_data(api.set_clock(iso, ADMIN))


def create_project(budget=100_000_000, name="PJ", agency="DOT", api=api_client):
    return get_success_data(api.create_project(
        {"name": name, "agency_name": agency, "total_budget_cents": budget}, ADMIN))


def create_parcel(project_id, apn=None, total=10_000, take=5_000,
                  take_type="PARTIAL", api=api_client):
    return get_success_data(api.create_parcel({
        "project_id": project_id,
        "apn": apn or _next_apn(),
        "total_area_sqft": total,
        "take_area_sqft": take,
        "take_type": take_type,
    }, AGENT))


def add_ownership_interest(parcel_id, interest_type, holder_name, api=api_client, **fields):
    payload = {"interest_type": interest_type, "holder_name": holder_name}
    payload.update(fields)
    return get_success_data(api.create_ownership_interest(parcel_id, payload, AGENT))


def add_fee_owner(parcel_id, pct=100, holder="O", is_occupant=False, api=api_client):
    return add_ownership_interest(parcel_id, "FEE_OWNER", holder,
                                  ownership_pct=pct, is_occupant=is_occupant, api=api)


def add_lienholder(parcel_id, priority, balance_cents, holder="LH", api=api_client):
    return add_ownership_interest(parcel_id, "LIENHOLDER", holder,
                                  lien_priority=priority,
                                  lien_balance_cents=balance_cents, api=api)


def clear_ownership(parcel_id, api=api_client):
    return get_success_data(api.clear_ownership(parcel_id, AGENT))


def parcel_version(parcel_id, api=api_client):
    return get_success_data(api.get_parcel(parcel_id, APPRAISER))["version"]


def create_appraisal(parcel_id, version=None,
                     land=STD_LAND_CENTS, improvements=STD_IMPROVEMENTS_CENTS,
                     severance=STD_SEVERANCE_CENTS, special=STD_SPECIAL_BENEFITS_CENTS,
                     api=api_client):
    if version is None:
        version = parcel_version(parcel_id, api=api)
    return get_success_data(api.create_appraisal(parcel_id, {
        "appraiser_name": "AX",
        "land_value_cents": land,
        "improvements_value_cents": improvements,
        "severance_damages_cents": severance,
        "special_benefits_cents": special,
        "expected_parcel_version": version,
    }, APPRAISER))


def finalize_appraisal(appraisal_id, api=api_client):
    return get_success_data(api.finalize_appraisal(appraisal_id, APPRAISER))


def create_finalized_appraisal(parcel_id, api=api_client, **appraisal_kwargs):
    appr = create_appraisal(parcel_id, api=api, **appraisal_kwargs)
    finalize_appraisal(appr["id"], api=api)
    return appr


def open_negotiation(parcel_id, offer=STD_OFFER_BASIS_CENTS, api=api_client):
    return get_success_data(api.create_negotiation(
        parcel_id, {"initial_offer_cents": offer}, AGENT))


# ---- Composite scenarios ---------------------------------------------------

def setup_parcel_with_owner(budget=100_000_000, pct=100, is_occupant=False,
                            total=10_000, take=5_000, take_type="PARTIAL",
                            clear=True, api=api_client):
    """Project + parcel + one FEE_OWNER; ownership cleared by default.

    Returns dict: project, parcel, owner.
    """
    project = create_project(budget, api=api)
    parcel = create_parcel(project["id"], total=total, take=take,
                           take_type=take_type, api=api)
    owner = add_fee_owner(parcel["id"], pct=pct, is_occupant=is_occupant, api=api)
    if clear:
        clear_ownership(parcel["id"], api=api)
    return {"project": project, "parcel": parcel, "owner": owner}


def setup_cleared_appraised_parcel(budget=100_000_000, clear=True, finalize=True,
                                   land=STD_LAND_CENTS, improvements=STD_IMPROVEMENTS_CENTS,
                                   severance=STD_SEVERANCE_CENTS, special=STD_SPECIAL_BENEFITS_CENTS,
                                   is_occupant=False, api=api_client):
    """Project + parcel + FEE_OWNER(100%) + one appraisal.

    clear -> research_status OWNERSHIP_CLEARED; finalize -> appraisal FINALIZED.
    Returns dict: project, parcel, owner, appraisal.
    """
    base = setup_parcel_with_owner(budget=budget, is_occupant=is_occupant,
                                   clear=clear, api=api)
    parcel_id = base["parcel"]["id"]
    if finalize:
        appraisal = create_finalized_appraisal(
            parcel_id, land=land, improvements=improvements,
            severance=severance, special=special, api=api)
    else:
        appraisal = create_appraisal(
            parcel_id, land=land, improvements=improvements,
            severance=severance, special=special, api=api)
    base["appraisal"] = appraisal
    return base


def setup_open_negotiation(offer=STD_OFFER_BASIS_CENTS, budget=100_000_000,
                           is_occupant=False, api=api_client):
    """Cleared + finalized parcel with an open negotiation (AGENCY_OFFERED).

    Returns dict: project, parcel, owner, appraisal, negotiation.
    """
    ctx = setup_cleared_appraised_parcel(budget=budget, is_occupant=is_occupant, api=api)
    ctx["negotiation"] = open_negotiation(ctx["parcel"]["id"], offer=offer, api=api)
    return ctx


def setup_agreed_negotiation(offer=STD_OFFER_BASIS_CENTS, budget=100_000_000,
                             api=api_client):
    """Open a negotiation and have the owner accept the opening agency offer.

    Reaches Negotiation AGREED and Parcel acquisition_status AGREED.
    Returns dict: project, parcel, owner, appraisal, negotiation (post-accept read).
    """
    ctx = setup_open_negotiation(offer=offer, budget=budget, api=api)
    owner_headers = make_property_owner_headers(ctx["owner"]["id"])
    get_success_data(api.create_round(
        ctx["negotiation"]["id"], {"action": "ACCEPT"}, owner_headers))
    ctx["negotiation"] = get_success_data(
        api.get_negotiation(ctx["negotiation"]["id"], AGENT))
    return ctx


def setup_condemnation_filed(budget=100_000_000, api=api_client):
    """Cleared + finalized parcel, a negotiation opened (round_count 1, good-faith),
    then a condemnation filed (status FILED, snapshot == condemnation basis).

    Returns dict: project, parcel, owner, appraisal, negotiation, condemnation.
    """
    ctx = setup_open_negotiation(budget=budget, api=api)
    ctx["condemnation"] = get_success_data(
        api.create_condemnation(ctx["parcel"]["id"], AGENT))
    return ctx


def setup_condemnation_deposit_made(deposit_cents=None, budget=100_000_000, api=api_client):
    """Condemnation advanced to DEPOSIT_MADE. Default deposit == snapshot floor."""
    ctx = setup_condemnation_filed(budget=budget, api=api)
    cond = ctx["condemnation"]
    if deposit_cents is None:
        deposit_cents = cond["just_compensation_snapshot_cents"]
    ctx["condemnation"] = get_success_data(
        api.deposit(cond["id"], {"deposit_amount_cents": deposit_cents}, AGENT))
    return ctx


def setup_condemnation_possessed(budget=100_000_000, api=api_client):
    """Condemnation advanced to POSSESSED (parcel POSSESSED)."""
    ctx = setup_condemnation_deposit_made(budget=budget, api=api)
    ctx["condemnation"] = get_success_data(
        api.grant_possession(ctx["condemnation"]["id"], ADMIN))
    return ctx


def setup_occupant_parcel(budget=100_000_000, is_occupant=True, pct=100, api=api_client):
    """Project + parcel + one occupant FEE_OWNER (uncleared, unappraised).

    Enough state to file a relocation benefit. Returns dict: project, parcel, owner.
    """
    return setup_parcel_with_owner(budget=budget, pct=pct, is_occupant=is_occupant,
                                   total=8_000, take=8_000, take_type="FULL",
                                   clear=False, api=api)


def submit_relocation_benefit(parcel_id, owner_id, occupant_type, api=api_client, **fields):
    payload = {"claimant_name": "Occ", "occupant_type": occupant_type}
    payload.update(fields)
    owner_headers = make_property_owner_headers(owner_id)
    return get_success_data(
        api.create_relocation_benefit(parcel_id, payload, owner_headers))


def setup_identified_utility(possessed=False, budget=100_000_000, api=api_client):
    """A parcel with one IDENTIFIED UtilityRelocation.

    possessed=False -> parcel PENDING, possession_cleared False.
    possessed=True  -> parcel POSSESSED (via condemnation), possession_cleared True.
    Returns dict including 'utility'.
    """
    if possessed:
        ctx = setup_condemnation_possessed(budget=budget, api=api)
    else:
        project = create_project(budget, api=api)
        parcel = create_parcel(project["id"], api=api)
        ctx = {"project": project, "parcel": parcel}
    ctx["utility"] = get_success_data(api.create_utility_relocation(
        ctx["parcel"]["id"], {"utility_type": "GAS"}, UTILITY))
    return ctx


def setup_funded_escrow(offer=STD_OFFER_BASIS_CENTS, budget=100_000_000, api=api_client):
    """Agreed negotiation -> open escrow -> fund it (status FUNDED).

    Does NOT close (close requires the undefined statutory waiting period).
    Returns dict: project, parcel, owner, appraisal, negotiation, escrow.
    """
    ctx = setup_agreed_negotiation(offer=offer, budget=budget, api=api)
    escrow = get_success_data(api.create_escrow(
        ctx["parcel"]["id"], {"source": "NEGOTIATED"}, ESCROW))
    ctx["escrow"] = get_success_data(api.fund_escrow(escrow["id"], ESCROW))
    return ctx
