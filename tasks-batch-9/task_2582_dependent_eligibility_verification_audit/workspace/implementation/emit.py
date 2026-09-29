"""Creation helpers for the two append-only outbound records."""

import calc
import clock
import constants as K
import db

DEFAULT_CHANNEL = "EMAIL"


def communication(case, kind, channel=None, template_code=None, sent_at=None):
    """Append one CommunicationEvent, keeping the per-case ordinal in step."""
    if case is None:
        return None
    next_no = (case.get("communication_sequence_no") or 0) + 1
    db.set_fields(case, communication_sequence_no=next_no)
    return db.insert(
        "communications",
        {
            "case_id": case["id"],
            "kind": kind,
            "channel": channel or DEFAULT_CHANNEL,
            "sequence_no": next_no,
            "sent_at": sent_at or clock.now(),
            "template_code": template_code,
        },
    )


def termination_notice(dependent, case, origin, program, batch_sequence_no):
    issued_at = clock.now()
    effective = calc.termination_effective_date(origin, issued_at, program, dependent)
    return db.insert(
        "notices",
        {
            "dependent_id": dependent["id"],
            "case_id": case["id"] if case is not None else None,
            "origin": origin,
            "status": "ISSUED",
            "issued_at": issued_at,
            "effective_date": clock.fmt_date(effective),
            "batch_sequence_no": batch_sequence_no,
            "grace_days_applied": K.TERMINATION_GRACE_DAYS,
            "continuation_election_status": "NOT_ELECTED",
            "continuation_election_deadline": clock.add_days_dt(
                issued_at, K.CONTINUATION_ELECTION_DAYS
            ),
            "continuation_start_date": None,
            "continuation_end_date": None,
            "continuation_monthly_premium_cents": 0,
            "continuation_elected_at": None,
            "rescinded_at": None,
            "rescission_reason": None,
        },
    )
