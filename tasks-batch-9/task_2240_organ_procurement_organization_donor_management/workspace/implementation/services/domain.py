"""Shared domain mechanics: version touching, posture, ledgers and cascades."""

from datetime import timedelta

from flask import g

import db as store
from constants import (
    NOK_DOCS_REQUIRED,
    REGISTRY_REQUIRED,
    THORACIC_TYPES,
)
from db import clock_now, db, ordered
from services.calculations import floor_minutes

# --------------------------------------------------------------------- versioning


def touch(rec):
    """Bump updated_at always; bump version at most once per request per record.

    A single request that mutates several fields of one resource (a status flip
    plus a counter refresh, say) is one mutation for the purposes of PRD 2.4.
    """
    if rec is None:
        return rec
    rec["updated_at"] = clock_now()
    if "version" not in rec:
        return rec
    seen = getattr(g, "_touched", None)
    if seen is None:
        seen = set()
        g._touched = seen
    if rec["id"] not in seen:
        seen.add(rec["id"])
        rec["version"] = rec["version"] + 1
    return rec


# ------------------------------------------------------------------- collections


def organs_of_case(case_id):
    return ordered([o for o in db.organs.values() if o["donor_case_id"] == case_id])


def offers_of_run(run_id):
    rows = [o for o in db.organ_offers.values() if o["match_run_id"] == run_id]
    return sorted(rows, key=lambda r: (r["sequence_position"], r["created_at"], r["_seq"]))


def runs_of_organ(organ_id):
    return ordered([r for r in db.match_runs.values() if r["organ_id"] == organ_id])


def observations_of_case(case_id):
    return ordered([o for o in db.observations.values() if o["donor_case_id"] == case_id])


def operations_of_case(case_id):
    return ordered([o for o in db.recovery_operations.values() if o["donor_case_id"] == case_id])


def contacts_of_authorization(auth_id):
    return ordered([c for c in db.nok_contacts.values() if c["authorization_id"] == auth_id])


def screening_for_referral(referral_id):
    for s in db.eligibility_screenings.values():
        if s["referral_id"] == referral_id:
            return s
    return None


# ------------------------------------------------------------- posture / counters


def derive_posture(case):
    auth = db.authorizations.get(case.get("authorization_id"))
    if (
        case["allocation_status"] == "CLOSED"
        or case["physiologic_status"] == "LOST"
        or (auth is not None and auth["status"] == "RESCINDED")
    ):
        return "FROZEN"
    if case["physiologic_status"] == "DECOMPENSATING":
        return "RESTRICTED"
    return "OPEN"


def refresh_posture(case):
    posture = derive_posture(case)
    if case["case_posture"] != posture:
        case["case_posture"] = posture
        touch(case)
    return posture


def refresh_organ_counters(case):
    organs = organs_of_case(case["id"])
    organ_count = len(organs)
    recovered = sum(1 for o in organs if o["status"] in ("RECOVERED", "TRANSPLANTED", "DISCARDED"))
    nontransplantable = sum(
        1
        for o in organs
        if o["status"] in ("NON_TRANSPLANTABLE", "RESEARCH_REFERRED", "TISSUE_REFERRED")
    )
    if (
        case["organ_count"] != organ_count
        or case["organs_recovered_count"] != recovered
        or case["organs_nontransplantable_count"] != nontransplantable
    ):
        case["organ_count"] = organ_count
        case["organs_recovered_count"] = recovered
        case["organs_nontransplantable_count"] = nontransplantable
        touch(case)


def set_allocation_status(case, new_status, closed_reason=None):
    changed = False
    if case["allocation_status"] != new_status:
        case["allocation_status"] = new_status
        changed = True
    if new_status == "CLOSED" and closed_reason is not None and case["closed_reason"] != closed_reason:
        case["closed_reason"] = closed_reason
        changed = True
    if changed:
        touch(case)
        refresh_posture(case)
    return changed


def refresh_team_ledger(team):
    """booked_or_minutes == sum(or_minutes) over SCHEDULED + COMPLETED (PRD 2.11)."""
    ops = [o for o in db.recovery_operations.values() if o["recovery_team_id"] == team["id"]]
    booked = sum(o["or_minutes"] for o in ops if o["status"] in ("SCHEDULED", "COMPLETED"))
    scheduled = sum(1 for o in ops if o["status"] == "SCHEDULED")
    if team["booked_or_minutes"] != booked or team["scheduled_operation_count"] != scheduled:
        team["booked_or_minutes"] = booked
        team["scheduled_operation_count"] = scheduled
        touch(team)


def refresh_asset_legs(asset):
    """active_leg_count == organs on the asset whose status is RECOVERED (in transit)."""
    count = sum(
        1
        for o in db.organs.values()
        if o["transport_asset_id"] == asset["id"] and o["status"] == "RECOVERED"
    )
    if asset["active_leg_count"] != count:
        asset["active_leg_count"] = count
        touch(asset)


def reset_run_slots(run):
    if run["pending_offer_count"] != 0 or run["slots_free"] != run["primary_offer_slots"]:
        run["pending_offer_count"] = 0
        run["slots_free"] = run["primary_offer_slots"]
        touch(run)


# ---------------------------------------------------------- authorization helpers


def recompute_documentation(auth):
    basis = auth["authorization_basis"]
    present = set(auth["document_types_present"] or [])
    if basis == "FIRST_PERSON_REGISTRY":
        auth["required_document_types"] = list(REGISTRY_REQUIRED)
        complete = "REGISTRY_SCREENSHOT" in present
    elif basis == "LEGAL_NEXT_OF_KIN":
        auth["required_document_types"] = list(NOK_DOCS_REQUIRED)
        complete = set(NOK_DOCS_REQUIRED).issubset(present) and auth["witness_name"] is not None
    else:
        complete = False
    auth["documentation_complete"] = bool(complete)
    return auth["documentation_complete"]


# ------------------------------------------------------------- promotion selector


def promotion_selector(run, sweep=False):
    """The single mechanism that decides which candidates hold live offers.

    STEP 1 expiry sweep runs on an advance only. STEP 5 (the empty-pool
    fallback) is unqualified and therefore runs on every invocation.
    """
    now = clock_now()
    if sweep:
        for offer in offers_of_run(run["id"]):
            if offer["status"] == "PENDING" and offer["expires_at"] is not None:
                if now >= offer["expires_at"]:
                    offer["status"] = "EXPIRED"
                    touch(offer)
                    run["pending_offer_count"] -= 1
                    run["slots_free"] += 1
                    touch(run)

    pool = [o for o in offers_of_run(run["id"]) if o["status"] == "QUEUED"]
    pool_was_empty = not pool

    promoted = 0
    index = 0
    while run["pending_offer_count"] < run["primary_offer_slots"] and index < len(pool):
        offer = pool[index]
        index += 1
        offer["status"] = "PENDING"
        offer["offered_at"] = now
        offer["expires_at"] = now + timedelta(minutes=offer["acceptance_clock_minutes"])
        touch(offer)
        run["pending_offer_count"] += 1
        run["slots_free"] -= 1
        touch(run)
        promoted += 1

    if pool_was_empty and run["pending_offer_count"] == 0 and run["status"] == "OPEN":
        run["status"] = "EXHAUSTED"
        run["closed_reason"] = "CANDIDATES_EXHAUSTED"
        touch(run)
        organ = db.organs.get(run["organ_id"])
        if organ is not None and organ["status"] == "OFFERING":
            organ["status"] = "ALLOCATABLE"
            touch(organ)
            case = db.donor_cases.get(organ["donor_case_id"])
            if case is not None and case["allocation_status"] == "OFFERS_IN_FLIGHT":
                set_allocation_status(case, "MATCH_RUN_OPEN")
    return promoted


def supersede_open_runs(organ, exclude_run_id=None):
    for run in runs_of_organ(organ["id"]):
        if run["id"] == exclude_run_id or run["status"] != "OPEN":
            continue
        run["status"] = "SUPERSEDED"
        run["closed_reason"] = "SUPERSEDED_BY_NEW_RUN"
        touch(run)
        for offer in offers_of_run(run["id"]):
            if offer["status"] in ("QUEUED", "PENDING"):
                offer["status"] = "BYPASSED"
                # A supersede takes bypass_reason null -- deliberately none of the
                # three declared reasons (PRD 3.5).
                offer["bypass_reason"] = None
                touch(offer)
        reset_run_slots(run)


def close_runs_for_organ(organ, closed_reason, bypass_reason, bypass_statuses):
    """Close the OPEN runs of an organ and bypass the offers left standing.

    Only runs still in `OPEN` change status. Offers are swept on *every* run of
    the organ, because the one status that outlives an OPEN run -- `ACCEPTED`,
    which itself closed its run -- is explicitly part of the rescission sweep
    (PRD 3.3 hop 4, and the declared OrganOffer ACCEPTED -> BYPASSED edge).
    """
    for run in runs_of_organ(organ["id"]):
        if run["status"] == "OPEN":
            run["status"] = "CLOSED"
            run["closed_reason"] = closed_reason
            touch(run)
            reset_slots = True
        else:
            reset_slots = False
        for offer in offers_of_run(run["id"]):
            if offer["status"] in bypass_statuses:
                offer["status"] = "BYPASSED"
                offer["bypass_reason"] = bypass_reason
                touch(offer)
        if reset_slots:
            reset_run_slots(run)


# -------------------------------------------------------------------- cascades


def close_case_organs(case, nontransplantable_reason, bypass_statuses):
    """Take live organs to NON_TRANSPLANTABLE and close the allocation behind them."""
    for organ in organs_of_case(case["id"]):
        if organ["status"] not in ("PENDING_EVAL", "ALLOCATABLE", "OFFERING", "ACCEPTED"):
            continue
        organ["status"] = "NON_TRANSPLANTABLE"
        organ["nontransplantable_reason"] = nontransplantable_reason
        organ["accepted_offer_id"] = None
        touch(organ)
        close_runs_for_organ(organ, "CASE_CLOSED", "CASE_CLOSED", bypass_statuses)
    refresh_organ_counters(case)


def cancel_case_operations(case):
    for op in operations_of_case(case["id"]):
        if op["status"] != "SCHEDULED":
            continue
        op["status"] = "CANCELLED"
        op["cancelled_reason"] = "CASE_CLOSED"
        touch(op)
        team = db.recovery_teams.get(op["recovery_team_id"])
        if team is not None:
            refresh_team_ledger(team)


def rescission_cascade(auth):
    """PRD 3.3: five hops, all inside the triggering request."""
    # Hop 2 -- the referral and the donor case close.
    referral = db.death_referrals.get(auth["referral_id"])
    if referral is not None and referral["status"] == "CONVERTED":
        referral["status"] = "NOT_CONVERTED"
        touch(referral)
        hospital = db.hospital_partners.get(referral["hospital_partner_id"])
        if hospital is not None:
            hospital["converted_donor_count"] = max(0, hospital["converted_donor_count"] - 1)
            touch(hospital)

    for case in ordered([c for c in db.donor_cases.values() if c["authorization_id"] == auth["id"]]):
        set_allocation_status(case, "CLOSED", "AUTHORIZATION_RESCINDED")
        refresh_posture(case)
        # Hops 3 and 4.
        close_case_organs(case, "AUTHORIZATION_RESCINDED", ("QUEUED", "PENDING", "ACCEPTED"))
        # Hop 5.
        cancel_case_operations(case)


def decompensation_cascade(case):
    """PRD 3.4: thoracic organs are pulled back under a viability hold."""
    for organ in organs_of_case(case["id"]):
        if organ["organ_type"] not in THORACIC_TYPES:
            continue
        if organ["status"] not in ("ALLOCATABLE", "OFFERING"):
            continue
        was_offering = organ["status"] == "OFFERING"
        organ["viability_hold"] = True
        organ["status"] = "PENDING_EVAL"
        touch(organ)
        if was_offering:
            close_runs_for_organ(organ, "VIABILITY_HOLD", "VIABILITY_HOLD", ("QUEUED", "PENDING"))
    refresh_organ_counters(case)


def donor_loss_cascade(case):
    """PRD 3.4: an arrest strands every live organ of the case."""
    close_case_organs(case, "VIABILITY_FAILURE", ("QUEUED", "PENDING"))


def clear_viability_holds(case):
    for organ in organs_of_case(case["id"]):
        if organ["viability_hold"]:
            organ["viability_hold"] = False
            touch(organ)


# ------------------------------------------------------- observation projection


def project_observations(case):
    """Refresh viability_index, physiologic_status and the observation counters."""
    observations = observations_of_case(case["id"])
    if not observations:
        return None
    latest = max(observations, key=lambda o: (o["recorded_at"], o["created_at"], o["_seq"]))

    previous_status = case["physiologic_status"]
    index = latest["viability_index_snapshot"]
    if latest["cardiac_arrest"]:
        new_status = "LOST"
        index = 0
    elif index >= 70:
        new_status = "OPTIMIZED"
    elif index >= 40:
        new_status = "STABILIZING"
    else:
        new_status = "DECOMPENSATING"

    dmg_count = sum(1 for o in observations if o["dmg_bundle_met"])
    changed = (
        case["viability_index"] != index
        or case["physiologic_status"] != new_status
        or case["dmg_bundle_met_count"] != dmg_count
        or case["observation_count"] != len(observations)
    )
    case["viability_index"] = index
    case["physiologic_status"] = new_status
    case["dmg_bundle_met_count"] = dmg_count
    case["observation_count"] = len(observations)
    if changed:
        touch(case)

    if new_status == "LOST":
        refresh_posture(case)
        if case["allocation_status"] != "RECOVERED":
            set_allocation_status(case, "CLOSED", "DONOR_LOST")
        refresh_posture(case)
        donor_loss_cascade(case)
        return latest

    posture_before = case["case_posture"]
    posture = refresh_posture(case)
    if posture == "RESTRICTED" and posture_before != "RESTRICTED":
        decompensation_cascade(case)
    elif (
        previous_status == "DECOMPENSATING"
        and new_status == "OPTIMIZED"
    ):
        clear_viability_holds(case)
    return latest


# ---------------------------------------------------------------- misc helpers


def or_minutes(start, end):
    return floor_minutes(end, start)
