"""The two five-hop cascades (PRD 3.3 close, PRD 3.4 separation) and activation.

Hops that only move derived state — practice posture, the contract credentialing
edges, the credentialing rollup and the affiliation measurement window — are
reconciled centrally by services.uow.finalize(), so they can never disagree with
the rows they summarise.
"""

import clock
import config
import db
from services import derive, uow


def close_affiliation(affiliation):
    # Hop 1: the affiliation itself closes and the measurement window opens.
    affiliation["close_date"] = clock.now()
    affiliation["earnout_measurement_state"] = "OPEN"
    uow.touch(affiliation)

    practices = derive.practices_of_affiliation(affiliation["id"])

    # Hop 2: every practice becomes AFFILIATED and its posture is recomputed.
    for practice in practices:
        practice["affiliation_status"] = "AFFILIATED"
        uow.touch(practice)

    # Hop 3: the OFFERED population splits on offer_accepted; both branches write.
    activated = []
    for practice in practices:
        for employment in derive.employments_of_practice(practice["id"]):
            if employment["employment_status"] != "OFFERED":
                continue
            if employment["offer_accepted"]:
                employment["employment_status"] = "ACTIVE"
                employment["comp_effective_date"] = affiliation["close_date"]
                uow.touch(employment)
                activated.append((practice, employment))
            else:
                employment["employment_status"] = "LAPSED"
                uow.touch(employment)

    # Hop 4: one NOT_STARTED enrollment per newly ACTIVE doctor per LEGACY contract.
    legacy_by_practice = {}
    for practice, _ in activated:
        if practice["id"] in legacy_by_practice:
            continue
        legacy_by_practice[practice["id"]] = [
            contract
            for contract in derive.contracts_of_practice(practice["id"])
            if contract["transition_state"] == "LEGACY"
        ]
    effective_date = clock.add_days(
        affiliation["close_date"], config.POST_CLOSE_ENROLLMENT_LEAD_DAYS
    )
    for practice, employment in activated:
        for contract in legacy_by_practice[practice["id"]]:
            db.insert(
                "payer_enrollments",
                {
                    "payer_contract_id": contract["id"],
                    "doctor_employment_id": employment["id"],
                    "status": "NOT_STARTED",
                    "effective_date": effective_date,
                    "term_date": None,
                    "submitted_at": None,
                    "decided_at": None,
                    "denial_reason": None,
                    "submission_round": 0,
                },
            )

    # Hop 5 (contract credentialing edge) is reconciled by uow.finalize().
    return affiliation


def activate_employment(employment, practice):
    """Post-close acceptance activates immediately (PRD 3.4)."""
    employment["offer_accepted"] = True
    employment["employment_status"] = "ACTIVE"
    employment["comp_effective_date"] = clock.now()
    uow.touch(employment)
    uow.touch(practice)
    return employment


def separate_employment(employment, separation_reason):
    """Hop 1 of the separation cascade; hops 2-5 fall out of derived state."""
    separation_date = clock.now()
    employment["employment_status"] = "SEPARATED"
    employment["separation_date"] = separation_date
    employment["separation_reason"] = separation_reason
    employment["non_compete_end_date"] = clock.add_months(
        separation_date, employment["non_compete_months"]
    )
    employment["records_custody_state"] = "TRANSFER_PENDING"
    employment["non_compete_enforcement_state"] = "PENDING"
    uow.touch(employment)
    return employment
