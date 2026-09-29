"""Cascade of an appended EligibilityEvent through participant, award, pool, plan.

Order is fixed (PRD 2.7): participant derived fields -> award re-proration ->
pool distribution state -> plan roll-up.  Every record whose stored fields
actually changed gets its own `version` / `updated_at` bump.
"""

import db
from services import proration, rollup

_AWARD_PRORATION_FIELDS = ("target_bonus_pct", "credited_days",
                           "excluded_leave_days", "segment_count",
                           "prorated_target_cents", "eligibility_status")


def cascade_participant(plan, participant):
    before = db.snapshot(participant)
    proration.refresh_participant_derived(plan, participant)
    db.bump_if_changed(participant, before)

    award = db.award_for_participant(participant["id"])
    if award is not None:
        award_before = db.snapshot(award)
        fields = proration.compute_award_targets(plan, participant, strict=False)
        for name in _AWARD_PRORATION_FIELDS:
            award[name] = fields[name]
        award["_job_level"] = fields["_job_level"]
        # An unresolvable pool leaves the previous assignment in place rather
        # than orphaning the award.
        if fields["bu_pool_id"] is not None:
            award["business_unit_id"] = fields["business_unit_id"]
            award["bu_pool_id"] = fields["bu_pool_id"]
        # A TERMINATION classified BAD_LEAVER releases a proposed allocation.
        if fields["eligibility_status"] == "BAD_LEAVER" \
                and award["allocation_status"] == "PROPOSED":
            award["allocation_status"] = "UNALLOCATED"
            award["proposed_allocation_cents"] = 0
        rollup.refresh_award_money(award)
        db.bump_if_changed(award, award_before)

    plan_before = db.snapshot(plan)
    rollup.recompute_pools(plan)
    plan["total_target_cents"] = sum(p["eligible_target_cents"]
                                     for p in db.plan_pools(plan["id"]))
    rollup.apply_plan_governance(plan)
    db.bump_if_changed(plan, plan_before)
