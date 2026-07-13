"""Lookups, serializers, selectors and cascades."""
import calc
import db
from db import iso, now, touch
from errors import ApiError

# ---------------------------------------------------------------- lookups ---
_NOT_FOUND = {
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "subscriptions": "ERR_SUBSCRIPTION_NOT_FOUND",
    "kits": "ERR_KIT_NOT_FOUND",
    "samples": "ERR_SAMPLE_NOT_FOUND",
    "batches": "ERR_BATCH_NOT_FOUND",
    "instruments": "ERR_INSTRUMENT_NOT_FOUND",
    "grants": "ERR_CONSENT_NOT_FOUND",
    "reports": "ERR_REPORT_NOT_FOUND",
    "matches": "ERR_MATCH_NOT_FOUND",
    "trees": "ERR_TREE_NOT_FOUND",
    "persons": "ERR_PERSON_NOT_FOUND",
    "hints": "ERR_HINT_NOT_FOUND",
    "data_requests": "ERR_DATA_REQUEST_NOT_FOUND",
}


def get(collection, entity_id):
    table = getattr(db.db, collection)
    record = table.get(entity_id) if isinstance(entity_id, str) else None
    if record is None:
        raise ApiError(_NOT_FOUND[collection])
    return record


def all_of(collection):
    return list(getattr(db.db, collection).values())


# ------------------------------------------------------------- consent ------
def covers_now(grant):
    t = now()
    return grant["effective_from"] <= t <= grant["effective_until"]


def has_live_consent(customer_id, scope):
    for grant in db.db.grants.values():
        if (
            grant["customer_id"] == customer_id
            and grant["scope"] == scope
            and grant["status"] == "ACTIVE"
            and covers_now(grant)
        ):
            return True
    return False


def matching_opt_in(customer_id):
    return has_live_consent(customer_id, "RELATIVE_MATCHING")


# -------------------------------------------------------- subscription ------
def subscription_of(customer_id):
    """The customer's current subscription (latest created), or None."""
    subs = [s for s in db.db.subscriptions.values() if s["customer_id"] == customer_id]
    if not subs:
        return None
    return db.by_creation(subs)[-1]


def access_status_of(customer_id):
    sub = subscription_of(customer_id)
    return sub["access_status"] if sub else "ACTIVE"


def tier_of(customer_id):
    sub = subscription_of(customer_id)
    return sub["tier"] if sub else "FREE"


def published_report_count(sub):
    """Recomputed tally of currently-PUBLISHED reports inside the current period."""
    t = now()
    count = 0
    for report in db.db.reports.values():
        if (
            report["customer_id"] == sub["customer_id"]
            and report["status"] == "PUBLISHED"
            and report["generated_at"] is not None
            and sub["current_period_start"] <= report["generated_at"] <= t
        ):
            count += 1
    return count


# ----------------------------------------------------------- selectors ------
def source_sample(customer_id):
    """report_source_sample: GENOTYPED sample of a PROCESSED kit; latest created_at,
    tie-break higher call_rate. Sample.id is never an input."""
    eligible = []
    for sample in db.db.samples.values():
        if sample["status"] != "GENOTYPED":
            continue
        kit = db.db.kits.get(sample["kit_id"])
        if not kit or kit["customer_id"] != customer_id or kit["status"] != "PROCESSED":
            continue
        eligible.append(sample)
    if not eligible:
        return None
    eligible.sort(
        key=lambda s: (
            s["created_at"],
            s["call_rate"] if s["call_rate"] is not None else -1.0,
            s["_seq"],
        ),
        reverse=True,
    )
    return eligible[0]


def root_person_for(customer_id):
    """hint_root_person: oldest ACTIVE tree (tie: name ASC), then oldest ACTIVE root
    person with both parent links null (tie: surname ASC). Ids are never inputs."""
    trees = [
        t
        for t in db.db.trees.values()
        if t["customer_id"] == customer_id and t["status"] == "ACTIVE"
    ]
    if not trees:
        return None
    trees.sort(key=lambda t: (t["created_at"], str(t["name"]), t["_seq"]))
    tree = trees[0]

    roots = [
        p
        for p in db.db.persons.values()
        if p["tree_id"] == tree["id"]
        and p["status"] == "ACTIVE"
        and p["father_id"] is None
        and p["mother_id"] is None
    ]
    if not roots:
        return None
    roots.sort(key=lambda p: (p["created_at"], str(p["surname"]), p["_seq"]))
    return roots[0]


# ------------------------------------------------------------ cascades ------
def recompute_visible(customer):
    """Customer.visible_match_count = count of ACTIVE matches naming the customer."""
    count = 0
    for match in db.db.matches.values():
        if match["status"] == "ACTIVE" and customer["id"] in (
            match["customer_a_id"],
            match["customer_b_id"],
        ):
            count += 1
    if customer["visible_match_count"] != count:
        customer["visible_match_count"] = count
        touch(customer)


def withdraw_hints_of_match(match):
    """Every PENDING hint sourced from the match -> WITHDRAWN; hint_count decremented."""
    for hint in list(db.db.hints.values()):
        if hint["source_match_id"] != match["id"] or hint["status"] != "PENDING":
            continue
        hint["status"] = "WITHDRAWN"
        touch(hint)
        person = db.db.persons.get(hint["person_id"])
        if person:
            person["hint_count"] = max(0, person["hint_count"] - 1)
            touch(person)


def suppress_matches_for(customer):
    """Consent-withdrawal cascade hops 2-4 (PRD §3.8)."""
    for match in list(db.db.matches.values()):
        if match["status"] != "ACTIVE":
            continue
        if customer["id"] not in (match["customer_a_id"], match["customer_b_id"]):
            continue
        match["status"] = "SUPPRESSED"
        touch(match)
        for side_id in (match["customer_a_id"], match["customer_b_id"]):
            side = db.db.customers.get(side_id)
            if side:
                side["visible_match_count"] = max(0, side["visible_match_count"] - 1)
                touch(side)
        withdraw_hints_of_match(match)


def reactivate_matches_for(customer):
    """Consent re-grant cascade hops 2-3 (PRD §3.6)."""
    for match in list(db.db.matches.values()):
        if match["status"] != "SUPPRESSED":
            continue
        if customer["id"] not in (match["customer_a_id"], match["customer_b_id"]):
            continue
        other_id = (
            match["customer_b_id"]
            if match["customer_a_id"] == customer["id"]
            else match["customer_a_id"]
        )
        other = db.db.customers.get(other_id)
        if not other or other["account_status"] != "ACTIVE" or not matching_opt_in(other_id):
            continue
        match["status"] = "ACTIVE"
        touch(match)
        for side_id in (match["customer_a_id"], match["customer_b_id"]):
            side = db.db.customers.get(side_id)
            if side:
                side["visible_match_count"] = side["visible_match_count"] + 1
                touch(side)


def revoke_reports(customer_id, predicate):
    for report in db.db.reports.values():
        if report["customer_id"] != customer_id:
            continue
        if report["status"] != "PUBLISHED":
            continue
        if predicate(report):
            report["status"] = "REVOKED"
            touch(report)


def sample_terminal_failure_cascade(sample):
    """Sample FAILED_TERMINAL -> Kit VOID -> wallet refund + dna_status NO_SAMPLE."""
    kit = db.db.kits.get(sample["kit_id"])
    if not kit or kit["status"] != "RECEIVED":
        return
    kit["status"] = "VOID"
    touch(kit)
    customer = db.db.customers.get(kit["customer_id"])
    if customer:
        customer["wallet_credit_cents"] = customer["wallet_credit_cents"] + kit["price_cents"]
        customer["dna_status"] = "NO_SAMPLE"
        touch(customer)


def lab_batch_finalize_cascade(sample):
    """Sample GENOTYPED -> Kit PROCESSED -> Customer.dna_status DNA_READY."""
    kit = db.db.kits.get(sample["kit_id"])
    if not kit or kit["status"] != "RECEIVED":
        return
    kit["status"] = "PROCESSED"
    touch(kit)
    customer = db.db.customers.get(kit["customer_id"])
    if customer:
        customer["dna_status"] = "DNA_READY"
        touch(customer)


# --------------------------------------------------------- serializers ------
def _common(rec):
    return {
        "id": rec["id"],
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def customer_json(c):
    out = _common(c)
    out.update(
        {
            "email": c["email"],
            "display_name": c["display_name"],
            "account_status": c["account_status"],
            "dna_status": c["dna_status"],
            "wallet_credit_cents": c["wallet_credit_cents"],
            "matching_opt_in": has_live_consent(c["id"], "RELATIVE_MATCHING"),
            "research_opt_in": has_live_consent(c["id"], "RESEARCH"),
            "health_opt_in": has_live_consent(c["id"], "HEALTH_TRAITS"),
            "visible_match_count": c["visible_match_count"],
        }
    )
    return out


def subscription_json(s):
    out = _common(s)
    out.update(
        {
            "customer_id": s["customer_id"],
            "tier": s["tier"],
            "pending_tier": s["pending_tier"],
            "billing_status": s["billing_status"],
            "access_status": s["access_status"],
            "current_period_start": iso(s["current_period_start"]),
            "current_period_end": iso(s["current_period_end"]),
            "grace_until": iso(s["grace_until"]),
            "lifetime_charged_cents": s["lifetime_charged_cents"],
            "last_change_charge_cents": s["last_change_charge_cents"],
            "last_change_from_tier": s["last_change_from_tier"],
            "published_report_count": published_report_count(s),
        }
    )
    return out


def kit_json(k):
    out = _common(k)
    out.update(
        {
            "customer_id": k["customer_id"],
            "barcode": k["barcode"],
            "chip_version": k["chip_version"],
            "price_cents": k["price_cents"],
            "status": k["status"],
            "activated_at": iso(k["activated_at"]),
        }
    )
    return out


def sample_json(s):
    out = _common(s)
    out.update(
        {
            "kit_id": s["kit_id"],
            "batch_id": s["batch_id"],
            "status": s["status"],
            "extraction_attempts": s["extraction_attempts"],
            "dna_yield_ng": s["dna_yield_ng"],
            "call_rate": s["call_rate"],
            "population_scores": s["population_scores"],
            "genotype_markers": s["genotype_markers"],
        }
    )
    return out


def instrument_json(i):
    out = _common(i)
    out.update({"name": i["name"], "chip_version": i["chip_version"], "status": i["status"]})
    return out


def batch_json(b):
    out = _common(b)
    out.update(
        {
            "instrument_id": b["instrument_id"],
            "run_start_at": iso(b["run_start_at"]),
            "run_end_at": iso(b["run_end_at"]),
            "status": b["status"],
            "member_count": b["member_count"],
            "pass_rate": b["pass_rate"],
        }
    )
    return out


def grant_json(g):
    out = _common(g)
    out.update(
        {
            "customer_id": g["customer_id"],
            "scope": g["scope"],
            "effective_from": iso(g["effective_from"]),
            "effective_until": iso(g["effective_until"]),
            "status": g["status"],
            "withdrawn_at": iso(g["withdrawn_at"]),
        }
    )
    return out


def report_json(r):
    out = _common(r)
    out.update(
        {
            "customer_id": r["customer_id"],
            "sample_id": r["sample_id"],
            "report_type": r["report_type"],
            "variant": r["variant"],
            "status": r["status"],
            "composition": r["composition"],
            "residual_population": r["residual_population"],
            "trait_count": r["trait_count"],
            "generated_at": iso(r["generated_at"]),
        }
    )
    return out


def match_json(m):
    out = _common(m)
    out.update(
        {
            "customer_a_id": m["customer_a_id"],
            "customer_b_id": m["customer_b_id"],
            "shared_cm": m["shared_cm"],
            "segment_count": m["segment_count"],
            "predicted_relationship": m["predicted_relationship"],
            "confidence_score": m["confidence_score"],
            "status": m["status"],
        }
    )
    return out


def tree_json(t):
    out = _common(t)
    out.update(
        {
            "customer_id": t["customer_id"],
            "name": t["name"],
            "status": t["status"],
            "person_count": t["person_count"],
        }
    )
    return out


def person_json(p):
    out = _common(p)
    out.update(
        {
            "tree_id": p["tree_id"],
            "father_id": p["father_id"],
            "mother_id": p["mother_id"],
            "linked_customer_id": p["linked_customer_id"],
            "given_name": p["given_name"],
            "surname": p["surname"],
            "birth_year": p["birth_year"],
            "status": p["status"],
            "hint_count": p["hint_count"],
        }
    )
    return out


def hint_json(h):
    out = _common(h)
    out.update(
        {
            "person_id": h["person_id"],
            "source_match_id": h["source_match_id"],
            "hint_type": h["hint_type"],
            "status": h["status"],
            "confidence": h["confidence"],
        }
    )
    return out


def data_request_json(d):
    out = _common(d)
    out.update(
        {
            "customer_id": d["customer_id"],
            "request_type": d["request_type"],
            "status": d["status"],
            "reviewed_by": d["reviewed_by"],
            "scheduled_purge_at": iso(d["scheduled_purge_at"]),
            "export_url": d["export_url"],
        }
    )
    return out


# ------------------------------------------------------------ validation ----
def require_fields(body, fields):
    for field in fields:
        if field not in body or body[field] is None:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s." % field)


def require_enum(value, allowed, field):
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be one of %s." % (field, ", ".join(allowed)))


def require_not_purged(customer):
    if customer["account_status"] == "PURGED":
        raise ApiError("ERR_CUSTOMER_PURGED")


def owner_of_tree_person(person):
    tree = db.db.trees.get(person["tree_id"])
    return tree["customer_id"] if tree else None


def owner_of_sample(sample):
    kit = db.db.kits.get(sample["kit_id"])
    return kit["customer_id"] if kit else None
