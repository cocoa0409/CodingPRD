"""Existence resolution (ladder steps 3 and 5).

Path ids are resolved left to right; body references are resolved in the
declaration order fixed by PRD 2.9:
  plan_id -> participant_id -> business_unit_id / new_business_unit_id
  -> bu_pool_id -> award_id -> supersedes_event_id
"""

import db
from errors import ApiError


def _get(collection, entity_id, error_id, label):
    record = collection.get(entity_id)
    if record is None:
        raise ApiError(error_id, "%s '%s' does not exist" % (label, entity_id))
    return record


def plan(plan_id):
    return _get(db.bonus_plans, plan_id, "ERR_PLAN_NOT_FOUND", "Bonus plan")


def metric(metric_id):
    return _get(db.company_metrics, metric_id, "ERR_METRIC_NOT_FOUND", "Company metric")


def business_unit(unit_id):
    return _get(db.business_units, unit_id, "ERR_BUSINESS_UNIT_NOT_FOUND", "Business unit")


def job_level_target(target_id):
    return _get(db.job_level_targets, target_id,
                "ERR_JOB_LEVEL_TARGET_NOT_FOUND", "Job level target")


def participant(participant_id):
    return _get(db.participants, participant_id,
                "ERR_PARTICIPANT_NOT_FOUND", "Participant")


def event(event_id):
    return _get(db.eligibility_events, event_id, "ERR_EVENT_NOT_FOUND",
                "Eligibility event")


def pool(pool_id):
    return _get(db.bu_pools, pool_id, "ERR_POOL_NOT_FOUND", "Business unit pool")


def award(award_id):
    return _get(db.participant_awards, award_id, "ERR_AWARD_NOT_FOUND",
                "Participant award")


def adjustment(adjustment_id):
    return _get(db.discretionary_adjustments, adjustment_id,
                "ERR_ADJUSTMENT_NOT_FOUND", "Discretionary adjustment")


def accrual_period(period_id):
    return _get(db.accrual_periods, period_id,
                "ERR_ACCRUAL_PERIOD_NOT_FOUND", "Accrual period")


def payout_run(run_id):
    return _get(db.payout_runs, run_id, "ERR_PAYOUT_RUN_NOT_FOUND", "Payout run")


def dispute(dispute_id):
    return _get(db.disputes, dispute_id, "ERR_DISPUTE_NOT_FOUND", "Dispute")
