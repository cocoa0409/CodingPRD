"""Derived-counter recomputation.

Every one of the three conservation invariants of PRD 2.12 is enforced here
and nowhere else: each counter is re-derived from the rows it partitions, so
the partition cannot drift no matter which write path (direct transition,
cascade leg, or a branch the PRD says must NOT fire) reached it.

  * incentive money conservation   -> recompute_period_buckets
  * site slot conservation         -> recompute_site_counters
  * employer quota conservation    -> recompute_contract_quota

Every write path in routes/ calls the recompute for each aggregate it touched.
"""

from . import constants, store


def recompute_site_counters(site):
    """Site.slots_requested_total == held + consumed + no_show + released."""
    held = consumed = no_show = released = total = 0
    for appt in store.all_rows("appointment"):
        if appt["site_id"] != site["id"]:
            continue
        total += 1
        status = appt["status"]
        if status == "BOOKED":
            held += 1
        elif status == "CONSUMED":
            consumed += 1
        elif status == "NO_SHOW":
            no_show += 1
        elif status == "CANCELLED":
            released += 1
    site["slots_held_count"] = held
    site["slots_consumed_count"] = consumed
    site["slots_no_show_count"] = no_show
    site["slots_released_count"] = released
    site["slots_requested_total"] = total


def recompute_contract_quota(contract):
    """requested_total == consumed + released; remaining == total - consumed.

    A cancelled appointment releases the employer's quota; a no-show does not.
    """
    consumed = released = total = 0
    for appt in store.all_rows("appointment"):
        if appt.get("quota_contract_id") != contract["id"]:
            continue
        total += 1
        if appt["status"] in ("BOOKED", "CONSUMED", "NO_SHOW"):
            consumed += 1
        elif appt["status"] == "CANCELLED":
            released += 1
    contract["quota_visits_consumed"] = consumed
    contract["quota_visits_released"] = released
    contract["quota_visits_requested_total"] = total
    contract["quota_visits_remaining"] = int(contract["quota_visits_total"]) - consumed


def recompute_period_buckets(period):
    """awarded == pending + paid + reversed + forfeited."""
    awarded = 0
    buckets = {
        "incentive_pending_cents": 0,
        "incentive_paid_cents": 0,
        "incentive_reversed_cents": 0,
        "incentive_forfeited_cents": 0,
    }
    for award in store.all_rows("award"):
        if award["reporting_period_id"] != period["id"]:
            continue
        amount = int(award["award_amount_cents"])
        awarded += amount
        bucket = constants.AWARD_STATUS_BUCKET[award["status"]]
        buckets[bucket] += amount
    period["incentive_awarded_cents"] = awarded
    for key, value in buckets.items():
        period[key] = value


def recompute_employer_budget(employer):
    committed = 0
    for award in store.all_rows("award"):
        if award["employer_id"] != employer["id"]:
            continue
        if award["status"] in constants.AWARD_COMMITTING_STATUSES:
            committed += int(award["award_amount_cents"])
    employer["wellness_budget_committed_cents"] = committed
    employer["wellness_budget_remaining_cents"] = (
        int(employer["wellness_budget_cents"]) - committed
    )


def recompute_participant_derived(participant):
    visits = 0
    for visit in store.all_rows("visit"):
        if visit["participant_id"] != participant["id"]:
            continue
        if visit["encounter_status"] in constants.DELIVERED_ENCOUNTER_STATES:
            visits += 1
    awarded = 0
    for award in store.all_rows("award"):
        if award["participant_id"] == participant["id"]:
            awarded += int(award["award_amount_cents"])
    participant["completed_visit_count"] = visits
    participant["incentive_awarded_cents"] = awarded


def employer_of_participant(participant):
    return store.get("employer", participant["employer_id"])


def participant_committed_cents(participant_id, period_id):
    """Cap headroom consumption: same participant, same reporting period,
    statuses PENDING / APPROVED / EXPORTED / PAID (PRD 3.8)."""
    total = 0
    for award in store.all_rows("award"):
        if award["participant_id"] != participant_id:
            continue
        if award["reporting_period_id"] != period_id:
            continue
        if award["status"] in constants.AWARD_COMMITTING_STATUSES:
            total += int(award["award_amount_cents"])
    return total
