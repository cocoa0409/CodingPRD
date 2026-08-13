"""Plan enrollments (PRD §3.3): creation, activation, supersede cascade."""

import db
from errors import ApiError, ERR_NOT_FOUND, ERR_ENROLLMENT_ALREADY_SCHEDULED, \
    ERR_EFFECTIVE_DATE_REGRESSION
from services.common import new_id, stamp_new, touch


def current_enrollment(agent_id):
    """The agent's current ACTIVE enrollment, if any."""
    for e in db.enrollments.values():
        if e["agent_id"] == agent_id and e["status"] == "ACTIVE":
            return e
    return None


def scheduled_enrollment(agent_id):
    for e in db.enrollments.values():
        if e["agent_id"] == agent_id and e["status"] == "SCHEDULED":
            return e
    return None


def covering_enrollment(agent_id, closing_date):
    """The enrollment whose [effective_from, effective_to) contains the
    closing date. SUPERSEDED/ENDED windows are honored for past closings."""
    from timeutil import parse_date
    best = None
    for e in db.enrollments.values():
        if e["agent_id"] != agent_id:
            continue
        if e["status"] not in ("ACTIVE", "SUPERSEDED", "ENDED"):
            continue
        ef = parse_date(e["effective_from"])
        et = parse_date(e["effective_to"]) if e["effective_to"] else None
        if ef <= closing_date and (et is None or closing_date < et):
            if best is None or ef > parse_date(best["effective_from"]):
                best = e
    return best


def activate_enrollment(enr, bump_agent_version):
    """Activate a SCHEDULED enrollment, superseding the agent's currently
    ACTIVE enrollment (PRD §3.3)."""
    agent = db.agents[enr["agent_id"]]
    prev = current_enrollment(agent["id"])
    if prev is not None and prev["id"] != enr["id"]:
        prev["status"] = "SUPERSEDED"
        prev["effective_to"] = enr["effective_from"]
        touch(prev)
    enr["status"] = "ACTIVE"
    touch(enr)
    if bump_agent_version:
        touch(agent)


def create_enrollment(agent, plan, effective_from):
    """Create an enrollment. Caller has already validated agent/plan state and
    OCC. Enforces the effective-date chaining rules (PRD §3.3)."""
    from timeutil import parse_date

    active = current_enrollment(agent["id"])
    sched = scheduled_enrollment(agent["id"])

    # Effective-date regression: strictly after the current enrollment's
    # effective_from (no overlap, no back-dating).
    if active is not None:
        if effective_from <= parse_date(active["effective_from"]):
            raise ApiError(ERR_EFFECTIVE_DATE_REGRESSION, 422,
                           "effective_from must be strictly after the current enrollment's effective_from")
    if sched is not None:
        if effective_from <= parse_date(sched["effective_from"]):
            raise ApiError(ERR_EFFECTIVE_DATE_REGRESSION, 422,
                           "effective_from must be strictly after the scheduled enrollment's effective_from")

    activates_inline = effective_from <= db.clock_date()

    # A second SCHEDULED enrollment is rejected — only when the new one would
    # itself be SCHEDULED; an inline-activating enrollment proceeds.
    if sched is not None and not activates_inline:
        raise ApiError(ERR_ENROLLMENT_ALREADY_SCHEDULED, 422,
                       "agent already has a SCHEDULED enrollment")

    enr = {
        "id": new_id(),
        "agent_id": agent["id"],
        "plan_id": plan["id"],
        "plan_version": plan["version"],
        "effective_from": effective_from.isoformat(),
        "effective_to": None,
        "status": "SCHEDULED",
    }
    stamp_new(enr)
    db.enrollments[enr["id"]] = enr

    if activates_inline:
        # Born ACTIVE; supersedes the current ACTIVE enrollment. The create
        # endpoint's single Agent.version bump covers the whole request.
        activate_enrollment(enr, bump_agent_version=False)

    # Exactly +1 Agent.version per enrollment-create request.
    touch(agent)
    return enr


def plan_terms(plan_id, plan_version):
    """The pinned plan terms as-of an enrollment. Since plans are editable
    only while DRAFT, an ACTIVE plan's terms equal the terms pinned at
    enrollment; we keep a version snapshot for fidelity anyway."""
    plan = db.plans.get(plan_id)
    if plan is None:
        raise ApiError(ERR_NOT_FOUND, 404, "plan not found")
    versions = plan.setdefault("_versions", {})
    if plan["version"] not in versions:
        versions[plan["version"]] = _snapshot_terms(plan)
    if plan_version not in versions:
        versions[plan_version] = _snapshot_terms(plan)
    return versions[plan_version]


def _snapshot_terms(plan):
    return {
        "name": plan["name"],
        "royalty_pct": plan["royalty_pct"],
        "royalty_cap_cents": plan["royalty_cap_cents"],
        "eo_fee_cents": plan["eo_fee_cents"],
        "transaction_fee_cents": plan["transaction_fee_cents"],
        "mentor_split_pct": plan["mentor_split_pct"],
        "mentor_deal_count": plan["mentor_deal_count"],
        "tiers": [dict(t) for t in plan["tiers"]],
    }
