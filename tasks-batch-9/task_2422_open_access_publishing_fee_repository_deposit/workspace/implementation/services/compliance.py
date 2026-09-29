"""mandate_compliance_and_embargo and the grant roll-up (PRD 3.8)."""
from clock import clock
from db import db, set_fields
from util import add_days, add_months, iso_date, parse_iso_date


def grant_of(article):
    grant_id = article.get("grant_id")
    if not grant_id:
        return None
    return db.grants.get(grant_id)


def funder_of_grant(grant):
    if grant is None:
        return None
    return db.funders.get(grant["funder_id"])


def is_exempt(article):
    grant = grant_of(article)
    funder = funder_of_grant(grant)
    return grant is None or funder is None or funder["mandate_type"] == "NONE"


def deadline_and_embargo(article):
    """Return (deposit_deadline_on, embargo_until) as ISO date strings or None."""
    if is_exempt(article):
        return None, None
    grant = grant_of(article)
    funder = funder_of_grant(grant)
    journal = db.journals[article["journal_id"]]
    accepted = parse_iso_date(article["accepted_on"])
    deadline = add_days(accepted, funder["deposit_deadline_days"])
    if funder["mandate_type"] == "IMMEDIATE_CC_BY":
        months = 0
    else:
        months = min(funder["max_embargo_months"], journal["required_embargo_months"])
    base_raw = article.get("publication_date") or article["accepted_on"]
    base = parse_iso_date(base_raw)
    embargo = add_months(base, months)
    return iso_date(deadline), iso_date(embargo)


def initial_compliance(article):
    """Values applied when the article row is first recorded."""
    if is_exempt(article):
        return {"compliance_status": "EXEMPT", "deposit_deadline_on": None, "embargo_until": None}
    deadline, embargo = deadline_and_embargo(article)
    return {
        "compliance_status": "PENDING_DEPOSIT",
        "deposit_deadline_on": deadline,
        "embargo_until": embargo,
    }


def compliance_at_ingest(article):
    """Verdict applied by a curation INGEST decision."""
    if is_exempt(article):
        return {"compliance_status": "EXEMPT", "deposit_deadline_on": None, "embargo_until": None}
    deadline, embargo = deadline_and_embargo(article)
    today = clock.date()
    if today > parse_iso_date(deadline):
        status = "NON_COMPLIANT"
    elif today >= parse_iso_date(embargo):
        status = "COMPLIANT"
    else:
        status = "EMBARGOED"
    return {
        "compliance_status": status,
        "deposit_deadline_on": deadline,
        "embargo_until": embargo,
    }


def recompute_grant(grant_id):
    """Grant.output_count / compliant_output_count / mandate_status (PRD 3.8)."""
    if not grant_id:
        return
    grant = db.grants.get(grant_id)
    if grant is None:
        return
    articles = [a for a in db.articles.values() if a.get("grant_id") == grant_id]
    output_count = len(articles)
    compliant_output_count = sum(
        1 for a in articles if a["compliance_status"] in ("COMPLIANT", "EXEMPT")
    )
    if any(a["compliance_status"] == "NON_COMPLIANT" for a in articles):
        mandate_status = "BREACHED"
    elif output_count > 0 and compliant_output_count == output_count:
        mandate_status = "SATISFIED"
    else:
        mandate_status = "IN_PROGRESS"
    set_fields(
        grant,
        output_count=output_count,
        compliant_output_count=compliant_output_count,
        mandate_status=mandate_status,
    )
