"""Envelope timeliness, PRELIMINARY and FINAL variants (PRD 3.4)."""
import db


def grace_limit_at(election_rec):
    return db.add_days(
        election_rec["return_deadline_at"], election_rec["postmark_grace_days"]
    )


def evaluate(env, election_rec, variant):
    """variant is 'PRELIMINARY' or 'FINAL'."""
    received_at = env["received_at"]
    deadline = election_rec["return_deadline_at"]
    channel = env["intake_channel"]

    # Whole-second resolution comparisons in UTC.
    received = received_at.replace(microsecond=0)
    deadline_s = deadline.replace(microsecond=0)

    if channel in ("DROPBOX", "IN_PERSON"):
        # No carrier postmark, therefore no grace at all; equality is timely.
        return "TIMELY" if received <= deadline_s else "UNTIMELY"

    if received <= deadline_s:
        return "TIMELY"

    limit = grace_limit_at(election_rec).replace(microsecond=0)
    if received > limit:
        return "UNTIMELY"

    # Strictly after the return deadline and at or before the grace limit.
    legible = env["postmark_legible"]
    postmark_date = env["postmark_date"]
    if not legible or postmark_date is None:
        return "PROVISIONAL_TIMELY_POSTMARK" if variant == "PRELIMINARY" else "UNTIMELY"

    pm = db.parse_date(postmark_date)
    election_day = db.parse_date(election_rec["election_date"])
    if pm is not None and election_day is not None and pm <= election_day:
        return (
            "PROVISIONAL_TIMELY_POSTMARK"
            if variant == "PRELIMINARY"
            else "TIMELY_BY_POSTMARK"
        )
    return "UNTIMELY"
