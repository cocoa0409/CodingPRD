"""apc_coverage_determination and the agreement quota cycle (PRD 3.2, 3.4)."""
from decimal import Decimal

from clock import clock
from db import db, new_ledger_row, set_fields, sort_rows, touch
from util import dec, parse_iso_date, round_half_up


# ------------------------------------------------------------- lookups

def effective_determination(article_id):
    """The row with the highest sequence_no (PRD 3.4)."""
    rows = [d for d in db.determinations.values() if d["article_id"] == article_id]
    if not rows:
        return None
    return max(rows, key=lambda d: d["sequence_no"])


def fund_requests_of_article(article_id):
    return sort_rows([r for r in db.fund_requests.values() if r["article_id"] == article_id])


def _has_committed_request(article_id):
    return any(
        r["status"] in ("APPROVED", "PAID") for r in db.fund_requests.values()
        if r["article_id"] == article_id
    )


def ta_token_count(agreement_id, final_only=False, exclude_article_id=None):
    """Articles whose effective determination names this agreement on a TA route."""
    if not agreement_id:
        return 0
    count = 0
    for article in db.articles.values():
        if exclude_article_id is not None and article["id"] == exclude_article_id:
            continue
        det = effective_determination(article["id"])
        if det is None:
            continue
        if det.get("agreement_id") != agreement_id:
            continue
        if det["route"] not in ("TA_FULL", "TA_CAPPED"):
            continue
        if final_only and det["basis"] != "FINAL":
            continue
        count += 1
    return count


# --------------------------------------------- publisher / agreement counters

def recompute_publisher_agreement_count(publisher_id):
    publisher = db.publishers.get(publisher_id)
    if publisher is None:
        return
    active = sum(
        1 for a in db.agreements.values()
        if a["publisher_id"] == publisher_id and a["status"] == "ACTIVE"
    )
    set_fields(publisher, active_agreement_count=active)


def recompute_agreement_usage(agreement_id):
    """Recompute articles_used and drive the ACTIVE <-> EXHAUSTED cycle."""
    if not agreement_id:
        return
    agreement = db.agreements.get(agreement_id)
    if agreement is None:
        return
    used = ta_token_count(agreement_id)
    changes = {"articles_used": used}
    previous_status = agreement["status"]
    new_status = previous_status
    if previous_status == "ACTIVE" and used >= agreement["article_quota"]:
        new_status = "EXHAUSTED"
    elif previous_status == "EXHAUSTED" and used < agreement["article_quota"]:
        if clock.date() < parse_iso_date(agreement["effective_until"]):
            new_status = "ACTIVE"
    if new_status != previous_status:
        changes["status"] = new_status
    set_fields(agreement, **changes)
    if new_status != previous_status:
        recompute_publisher_agreement_count(agreement["publisher_id"])


# --------------------------------------------------------- the determination

def _fund_route_eligible(article, journal):
    grant_id = article.get("grant_id")
    if not grant_id:
        return False
    grant = db.grants.get(grant_id)
    if grant is None or grant["status"] != "ACTIVE":
        return False
    funder = db.funders.get(grant["funder_id"])
    if funder is None:
        return False
    if funder["mandate_type"] not in ("GOLD_OA", "IMMEDIATE_CC_BY"):
        return False
    if not funder["apc_allowable"]:
        return False
    return journal["oa_model"] == "FULLY_OA"


def _matching_coverage(agreement_id, journal_id, reference_date):
    matches = []
    for coverage in db.coverages.values():
        if coverage["agreement_id"] != agreement_id:
            continue
        if coverage["journal_id"] != journal_id:
            continue
        if coverage["coverage_type"] not in ("FULL_APC", "CAPPED_APC"):
            continue
        if parse_iso_date(coverage["covered_from"]) > reference_date:
            continue
        if parse_iso_date(coverage["covered_until"]) < reference_date:
            continue
        matches.append(coverage)
    if not matches:
        return None
    return sort_rows(matches)[0]


def compute_determination(article, basis):
    """Pure computation of one EligibilityDetermination payload."""
    journal = db.journals[article["journal_id"]]
    publisher = db.publishers[journal["publisher_id"]]

    if basis == "PROVISIONAL":
        reference_raw = article["accepted_on"]
    else:
        reference_raw = article.get("publication_date") or clock.date().isoformat()
    reference_date = parse_iso_date(reference_raw)

    if basis == "FINAL" and article.get("apc_list_cents") is not None:
        list_base_cents = article["apc_list_cents"]
    else:
        list_base_cents = journal["list_apc_cents"]

    base = {
        "basis": basis,
        "reference_date": reference_raw,
        "list_base_cents": list_base_cents,
    }

    # ---- screening gate (PRD 3.4, third step)
    if publisher["screening_status"] == "PREDATORY_FLAGGED":
        base.update({
            "route": "AUTHOR_PAYS",
            "agreement_id": None,
            "coverage_id": None,
            "discount_pct_applied": 0,
            "covered_amount_cents": 0,
            "author_share_cents": list_base_cents,
            "eligible_request_cents": 0,
            "determination_reason": "PREDATORY_FLAGGED_NO_INSTITUTIONAL_FUNDS",
            "quota_position": None,
        })
        return base

    fund_route_eligible = _fund_route_eligible(article, journal)

    # ---- candidate agreements (PRD 3.4, fourth step)
    candidates = []
    for agreement in db.agreements.values():
        if agreement["publisher_id"] != journal["publisher_id"]:
            continue
        if agreement["status"] not in ("ACTIVE", "EXHAUSTED"):
            continue
        if parse_iso_date(agreement["effective_from"]) > reference_date:
            continue
        if parse_iso_date(agreement["effective_until"]) <= reference_date:
            continue
        if journal["oa_model"] not in agreement["covered_oa_models"]:
            continue
        if basis == "PROVISIONAL":
            held = ta_token_count(agreement["id"])
        else:
            held = ta_token_count(agreement["id"], final_only=True)
        if held >= agreement["article_quota"]:
            continue
        coverage = _matching_coverage(agreement["id"], journal["id"], reference_date)
        if coverage is None:
            continue
        candidates.append((agreement, coverage))

    if candidates:
        candidates.sort(key=lambda pair: (
            -dec(pair[0]["discount_pct"]),
            parse_iso_date(pair[0]["effective_until"]),
            pair[0]["created_at"],
            pair[0]["_seq"],
        ))
        agreement, coverage = candidates[0]
        discount = dec(agreement["discount_pct"])
        price_after_discount = round_half_up(dec(list_base_cents) * (Decimal(1) - discount))
        quota_position = ta_token_count(agreement["id"], exclude_article_id=article["id"]) + 1
        base.update({
            "agreement_id": agreement["id"],
            "coverage_id": coverage["id"],
            "discount_pct_applied": agreement["discount_pct"],
            "quota_position": quota_position,
        })
        if coverage["coverage_type"] == "FULL_APC":
            base.update({
                "route": "TA_FULL",
                "covered_amount_cents": price_after_discount,
                "author_share_cents": 0,
                "eligible_request_cents": 0,
                "determination_reason": "TA_FULL_COVERAGE",
            })
        else:
            covered = min(coverage["capped_amount_cents"], price_after_discount)
            author_share = price_after_discount - covered
            base.update({
                "route": "TA_CAPPED",
                "covered_amount_cents": covered,
                "author_share_cents": author_share,
                "eligible_request_cents": author_share if fund_route_eligible else 0,
                "determination_reason": "TA_CAPPED_COVERAGE",
            })
        return base

    base.update({
        "agreement_id": None,
        "coverage_id": None,
        "discount_pct_applied": 0,
        "quota_position": None,
        "covered_amount_cents": 0,
        "author_share_cents": list_base_cents,
    })
    if fund_route_eligible:
        base.update({
            "route": "FUND_APC",
            "eligible_request_cents": list_base_cents,
            "determination_reason": "NO_COVERAGE_FUND_ELIGIBLE",
        })
    else:
        base.update({
            "route": "AUTHOR_PAYS",
            "eligible_request_cents": 0,
            "determination_reason": "NO_COVERAGE_AUTHOR_PAYS",
        })
    return base


def funding_status_for_route(payload):
    route = payload["route"]
    if route == "TA_FULL":
        return "FUNDED"
    if route == "TA_CAPPED":
        return "ELIGIBILITY_CHECKED" if payload["eligible_request_cents"] > 0 else "SELF_FUNDED"
    if route == "FUND_APC":
        return "ELIGIBILITY_CHECKED"
    return "SELF_FUNDED"


def append_determination(article, basis, extra_article_changes=None):
    """Insert a determination, refresh the article and cycle the quota tokens."""
    previous = effective_determination(article["id"])
    previous_agreement_id = previous.get("agreement_id") if previous else None

    payload = compute_determination(article, basis)
    sequence_no = article["determination_count"] + 1
    row = new_ledger_row(article_id=article["id"], sequence_no=sequence_no, **payload)
    db.determinations[row["id"]] = row

    changes = dict(extra_article_changes or {})
    changes.update({
        "determination_count": sequence_no,
        "eligibility_route": row["route"],
        "covered_amount_cents": row["covered_amount_cents"],
        "author_share_cents": row["author_share_cents"],
    })
    locked = article["funding_status"] == "DECLINED" or _has_committed_request(article["id"])
    if not locked:
        changes["funding_status"] = funding_status_for_route(row)
    set_fields(article, _force=True, **changes)

    touched = []
    for agreement_id in (previous_agreement_id, row.get("agreement_id")):
        if agreement_id and agreement_id not in touched:
            touched.append(agreement_id)
    for agreement_id in touched:
        recompute_agreement_usage(agreement_id)
    return row
