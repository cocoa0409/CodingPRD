"""The logical clock and its three ordered system sweeps (PRD 2.5)."""

from datetime import timedelta

from core import constants, payload, store, timeutil
from core.ladder import ObjectResult, Spec


def _validate(ctx):
    payload.require_instant(ctx.body, "to_iso8601")


def _set_clock(ctx):
    target = timeutil.parse_instant(ctx.body["to_iso8601"])
    store.set_clock(timeutil.fmt_instant(target))
    new_dt = store.now_dt()
    new_date = new_dt.date()

    # Sweep 1 -- credential lapse.  The expiry bound is closed at the top: a
    # provider is still credentialed ON license_expiry_date.
    lapsed = []
    for provider in store.sorted_rows("provider"):
        if provider["credential_status"] != "CREDENTIALED":
            continue
        expiry = timeutil.parse_date(provider.get("license_expiry_date"))
        if expiry is not None and new_date > expiry:
            provider["credential_status"] = "LAPSED"
            lapsed.append(provider["id"])

    # Sweep 2 -- referral SLA escalation.  Strict: a referral standing at
    # exactly its sla_due_at has not breached.
    escalated = []
    for referral in store.sorted_rows("referral"):
        if referral["status"] not in ("SUBMITTED", "AUTHORIZED"):
            continue
        due = timeutil.parse_instant(referral.get("sla_due_at"))
        if due is not None and new_dt > due:
            referral["status"] = "ESCALATED"
            referral["escalated_at"] = store.now_iso()
            escalated.append(referral["id"])

    # Sweep 3 -- enrollment closure, with the authorization-axis cascade.
    closed = []
    for participant in store.sorted_rows("participant"):
        if participant["enrollment_status"] != "TERMINATED":
            continue
        eff = timeutil.parse_date(participant.get("termination_effective_date"))
        if eff is None:
            continue
        if new_date > eff + timedelta(days=constants.RETRO_TERMINATION_GRACE_DAYS):
            participant["enrollment_status"] = "CLOSED"
            participant["authorization_status"] = "WITHDRAWN"
            closed.append(participant["id"])

    return ObjectResult(
        {
            "current_utc": store.now_iso(),
            "lapsed_provider_ids": lapsed,
            "escalated_referral_ids": escalated,
            "closed_participant_ids": closed,
        },
        200,
    )


SPECS = [
    Spec(
        method="POST",
        path="/_clock/set_current_utc",
        roles=[constants.ROLE_PROGRAM_ADMIN],
        handler=_set_clock,
        status=200,
        payload=_validate,
        is_write=True,
    ),
]
