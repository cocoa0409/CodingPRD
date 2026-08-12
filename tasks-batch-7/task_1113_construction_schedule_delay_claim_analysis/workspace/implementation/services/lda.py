"""Liquidated damages exposure computation (PRD §3.8, scaffold calculation
liquidated_damages_exposure).

culpable_days := max(0, days_between(
    max(assessment_period_start, project.current_completion_date),
    min(assessment_period_end, projected_finish_or_actual_SC)))
gross_ld_cents := culpable_days * liquidated_damages_daily_rate_cents
prior_assessed_total_cents := sum(assessed_ld_cents over other LDAs in
    {ASSESSED, UPHELD, REDUCED})
assessed_ld_cents := min(gross_ld_cents, max(0, ld_cap_cents - prior_total))
"""

from middleware import touch
from routes.common import (
    ldas_of,
    latest_accepted_update,
    latest_accepted_baseline,
)
from util import parse_dt


def _finish_for_exposure(project):
    """Projected finish, or the actual substantial-completion date once declared."""
    if project.get("_actual_sc_date"):
        return parse_dt(project["_actual_sc_date"], "actual_sc_date")
    v = latest_accepted_update(project["id"])
    if v is None:
        v = latest_accepted_baseline(project["id"])
    if v is not None and v.get("projected_finish_date"):
        return parse_dt(v["projected_finish_date"], "projected_finish_date")
    return parse_dt(project["current_completion_date"], "current_completion_date")


def compute_exposure(project, period_start, period_end):
    lo = max(period_start,
             parse_dt(project["current_completion_date"],
                      "current_completion_date"))
    hi = min(period_end, _finish_for_exposure(project))
    culpable = (hi - lo).days
    if culpable < 0:
        culpable = 0
    gross = culpable * int(project["liquidated_damages_daily_rate_cents"])
    return culpable, gross


def refresh_exposure(project, lda):
    culpable, gross = compute_exposure(
        project,
        parse_dt(lda["assessment_period_start"], "assessment_period_start"),
        parse_dt(lda["assessment_period_end"], "assessment_period_end"),
    )
    lda["culpable_days"] = culpable
    lda["gross_ld_cents"] = gross


def assess_lda(project, lda):
    """PROPOSED -> ASSESSED with the aggregate-cap computation applied."""
    refresh_exposure(project, lda)
    prior = 0
    for other in ldas_of(project["id"]):
        if other["id"] == lda["id"]:
            continue
        if other["status"] in ("ASSESSED", "UPHELD", "REDUCED"):
            prior += other.get("assessed_ld_cents") or 0
    remaining = project["ld_cap_cents"] - prior
    if remaining < 0:
        remaining = 0
    lda["prior_assessed_total_cents"] = prior
    # The aggregate cap is enforced through the min(); the assessment can
    # therefore never push the project total beyond ld_cap_cents.
    lda["assessed_ld_cents"] = min(lda["gross_ld_cents"], remaining)
    lda["status"] = "ASSESSED"
    touch(lda)


def offset_overlapping_ldas(project, old_completion, new_completion):
    """EOT approval cascade: PROPOSED LDAs whose period overlaps
    [old_completion, new_completion) transition to OFFSET_BY_EOT."""
    for lda in sorted(ldas_of(project["id"]),
                      key=lambda l: (l.get("created_at", ""), l.get("_seq", 0))):
        if lda["status"] != "PROPOSED":
            continue
        start = parse_dt(lda["assessment_period_start"],
                         "assessment_period_start")
        end = parse_dt(lda["assessment_period_end"], "assessment_period_end")
        if start < new_completion and end >= old_completion:
            lda["status"] = "OFFSET_BY_EOT"
            lda["assessed_ld_cents"] = 0
            touch(lda)
