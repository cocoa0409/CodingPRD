"""Clock-set system sweep: fires the six ordered system transitions.

Pinned order:
1. Guardianship auto-termination (payee reached age_of_majority)
2. SCHEDULED -> PAYABLE maturation
3. Agreement FUNDED -> ACTIVE when step 2 produced the first PAYABLE
4. ISSUED + CHECK + age > 180 days -> STALE_DATED
5. {ISSUED, STALE_DATED, RETURNED} past dormancy -> ESCHEATABLE
6. COURT_APPROVED petition expiry at > 60 days past court_order_date
"""

from db import DB, CLOCK, touch, add_years, parse_date
from services import (
    find_profile_by_state,
    majority_birthday,
    active_schedule_for,
    recompute_agreement_totals,
)


STALE_CHECK_DAYS = 180
PETITION_EXPIRY_DAYS = 60


def run_clock_sweep():
    today = CLOCK.today()
    fired = 0

    # Step 1: guardianship auto-termination at majority.
    # Fires only for guardianships that were in force during the payee's
    # minority (effective_from_date strictly before the majority birthday);
    # a guardianship established over an adult (e.g. incapacity guardianship)
    # has no majority birthday within its interval and does not auto-terminate.
    for g in DB.guardianship_cases.values():
        if g["status"] != "ACTIVE":
            continue
        payee = DB.payees.get(g["payee_id"])
        if payee is None:
            continue
        mb = majority_birthday(payee)
        if mb is not None and parse_date(g["effective_from_date"]) < mb and today >= mb:
            g["status"] = "TERMINATED"
            g["terminated_at_date"] = mb.isoformat()
            touch(g)
            fired += 1

    # Step 2: SCHEDULED -> PAYABLE
    agreements_flipped = set()
    for p in DB.scheduled_payments.values():
        if p["status"] != "SCHEDULED":
            continue
        sched = DB.payment_schedules.get(p["payment_schedule_id"])
        if sched is None or sched["status"] != "ACTIVE":
            continue
        agreement = DB.settlement_agreements.get(sched["settlement_agreement_id"])
        if agreement is None or agreement["status"] not in ("FUNDED", "ACTIVE"):
            continue
        if parse_date(p["due_date"]) <= today:
            p["status"] = "PAYABLE"
            touch(p)
            fired += 1
            # Step 3: agreement FUNDED -> ACTIVE
            if agreement["status"] == "FUNDED":
                agreement["status"] = "ACTIVE"
                touch(agreement)
                fired += 1
                agreements_flipped.add(agreement["id"])
            # Maturation keeps payment inside outstanding set; totals recomputed
            recompute_agreement_totals(agreement)

    # Step 4: ISSUED + CHECK + (today - last_issued_at) > 180 -> STALE_DATED
    for p in DB.scheduled_payments.values():
        if p["status"] != "ISSUED":
            continue
        if p.get("last_issue_method") != "CHECK":
            continue
        issued_at = p.get("last_issued_at")
        if not issued_at:
            continue
        if (today - parse_date(issued_at)).days > STALE_CHECK_DAYS:
            p["status"] = "STALE_DATED"
            p["return_reason"] = "UNCASHED_STALE"
            touch(p)
            fired += 1

    # Step 5: {ISSUED, STALE_DATED, RETURNED} past dormancy -> ESCHEATABLE
    for p in DB.scheduled_payments.values():
        if p["status"] not in ("ISSUED", "STALE_DATED", "RETURNED"):
            continue
        payee = DB.payees.get(p["payee_id"])
        if payee is None:
            continue
        profile = find_profile_by_state(payee["address_state_code"])
        if profile is None:
            continue
        dormancy_anniversary = add_years(parse_date(p["due_date"]), profile["dormancy_years"])
        if today > dormancy_anniversary:
            p["status"] = "ESCHEATABLE"
            touch(p)
            fired += 1
            sched = DB.payment_schedules.get(p["payment_schedule_id"])
            if sched is not None:
                agreement = DB.settlement_agreements.get(sched["settlement_agreement_id"])
                if agreement is not None:
                    recompute_agreement_totals(agreement)

    # Step 6: COURT_APPROVED petition expiry at > 60 days
    for pet in DB.transfer_petitions.values():
        if pet["status"] != "COURT_APPROVED":
            continue
        cod = pet.get("court_order_date")
        if not cod:
            continue
        if (today - parse_date(cod)).days > PETITION_EXPIRY_DAYS:
            pet["status"] = "EXPIRED"
            touch(pet)
            fired += 1

    return fired
