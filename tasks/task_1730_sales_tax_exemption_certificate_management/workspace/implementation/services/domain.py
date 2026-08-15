"""Domain services: derived-field recomputation, PRD §3 calculations, and
the state-change cascades. All constants trace to PRD prose."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import ApiError
from middleware import bump

# PRD §2.4: day index 0 corresponds to 2026-08-01T00:00:00Z.
ORIGIN = date(2026, 8, 1)
# PRD §3.2: renewal window is forty-five days, boundary included.
RENEWAL_WINDOW_DAYS = 45
# PRD §3.5: block threshold is ten million cents ($100,000.00), inclusive.
BLOCK_THRESHOLD_CENTS = 10000000
# PRD §3.8: ten-day documentation response window.
DOC_RESPONSE_WINDOW_DAYS = 10
# PRD §3.8: confidence multipliers 90->0.10, 95->0.15, 99->0.25.
CONFIDENCE_MULTIPLIERS = {90: Decimal("0.10"), 95: Decimal("0.15"), 99: Decimal("0.25")}
# FIXED_FLOOR population cap of 5 (scaffold FIXED_FLOOR_MIN).
FIXED_FLOOR_POP_CAP = 5

SAMPLE_TERMINAL_OUTCOMES = ("PASSED", "FAILED", "WAIVED", "EXPIRED_NO_RESPONSE")
SAMPLE_NONTERMINAL_OUTCOMES = ("PENDING", "DOC_REQUESTED", "DOC_RECEIVED")
ORDER_TERMINAL_STATUSES = ("CANCELLED", "INVOICED")


def current_date(tenant):
    return ORIGIN + timedelta(days=tenant["audit_clock_day_index"])


def parse_day(s):
    return date.fromisoformat(str(s)[:10])


# ---------------------------------------------------------------------------
# Scoped lookups (validation priorities 3 and 4)
# ---------------------------------------------------------------------------

def get_tenant(tid):
    t = db.stores["tenants"].get(tid)
    if not t:
        raise ApiError("ERR_NOT_FOUND", "Tenant not found", 404)
    return t


def get_scoped(store, rid, tenant_id):
    rec = db.stores[store].get(rid)
    if not rec or rec.get("tenant_id") != tenant_id:
        raise ApiError("ERR_NOT_FOUND", "Resource not found", 404)
    return rec


def find_reason(tenant_id, code):
    for r in db.stores["exemption_reasons"].values():
        if r["tenant_id"] == tenant_id and r["code"] == code:
            return r
    return None


def require_reason(tenant_id, code):
    r = find_reason(tenant_id, code)
    if not r:
        raise ApiError(
            "ERR_CROSS_TENANT_REFERENCE",
            "exemption_reason_code does not resolve to a record of this tenant",
            404,
        )
    return r


def find_rule(tenant_id, state_code):
    for r in db.stores["jurisdiction_rules"].values():
        if r["tenant_id"] == tenant_id and r["state_code"] == state_code:
            return r
    return None


def customer_orders(customer_id):
    return [o for o in db.stores["orders"].values() if o["customer_id"] == customer_id]


def customer_certs(customer_id):
    return [c for c in db.stores["certificates"].values() if c["customer_id"] == customer_id]


def order_lines_of(order_id):
    lines = [l for l in db.stores["order_lines"].values() if l["order_id"] == order_id]
    lines.sort(key=lambda l: l["_seq"])
    return lines


# ---------------------------------------------------------------------------
# PRD §3.2 derived standings and exposure totals
# ---------------------------------------------------------------------------

def recompute_cert_standing(cust):
    """MISSING when no APPROVED cert; COMPLIANT when every footprint state is
    covered; otherwise PARTIAL. Returns True when the value changed."""
    approved = [c for c in customer_certs(cust["id"]) if c["status"] == "APPROVED"]
    footprint = {cust["primary_ship_to_state"]}
    footprint |= {o["ship_to_state"] for o in customer_orders(cust["id"])}
    covered_states = {c["ship_to_state"] for c in approved}
    if not approved:
        new = "MISSING"
    elif footprint <= covered_states:
        new = "COMPLIANT"
    else:
        new = "PARTIAL"
    if cust["cert_standing"] != new:
        cust["cert_standing"] = new
        return True
    return False


def recompute_collection_standing(cust, tenant):
    """LAPSED when an EXPIRED cert's state lacks APPROVED coverage; else
    RENEWAL_DUE when any APPROVED cert expires within 45 days (inclusive);
    else CURRENT. Returns True when the value changed."""
    certs = customer_certs(cust["id"])
    today = current_date(tenant)
    approved = [c for c in certs if c["status"] == "APPROVED"]
    approved_states = {c["ship_to_state"] for c in approved}
    lapsed = any(
        c["status"] == "EXPIRED" and c["ship_to_state"] not in approved_states
        for c in certs
    )
    if lapsed:
        new = "LAPSED"
    else:
        due = any(
            c["expiration_date"] is not None
            and (parse_day(c["expiration_date"]) - today).days <= RENEWAL_WINDOW_DAYS
            for c in approved
        )
        new = "RENEWAL_DUE" if due else "CURRENT"
    if cust["collection_standing"] != new:
        cust["collection_standing"] = new
        return True
    return False


def recompute_blocked_exposure(cust):
    """PRD §3.5: sum of uncovered_amount_cents over exactly the customer's
    HELD_FOR_CERT orders. Returns True when the value changed."""
    blocked = sum(
        o["uncovered_amount_cents"]
        for o in customer_orders(cust["id"])
        if o["status"] == "HELD_FOR_CERT"
    )
    if cust["blocked_exposure_cents"] != blocked:
        cust["blocked_exposure_cents"] = blocked
        return True
    return False


def recompute_open_exposure(tenant):
    """PRD §3.5: sum of uncovered_amount_cents over all non-terminal orders
    (non-terminal = not CANCELLED, not INVOICED). Returns True when changed."""
    open_exp = sum(
        o["uncovered_amount_cents"]
        for o in db.stores["orders"].values()
        if o["tenant_id"] == tenant["id"] and o["status"] not in ORDER_TERMINAL_STATUSES
    )
    if tenant["open_exposure_cents"] != open_exp:
        tenant["open_exposure_cents"] = open_exp
        return True
    return False


def recompute_audit_standing(cust):
    """PRD §3.2 audit dimension: SAMPLED while any sample names the customer;
    FAILED_SAMPLING when any sample is FAILED without RESOLVED remediation or
    EXPIRED_NO_RESPONSE; REMEDIATED when every FAILED sample has a RESOLVED
    remediation and no sample is in flight. Returns True when changed."""
    samples = [s for s in db.stores["audit_samples"].values() if s["customer_id"] == cust["id"]]
    if not samples:
        new = "NOT_UNDER_AUDIT"
    else:
        actions = list(db.stores["remediation_actions"].values())

        def has_resolved(sample):
            return any(
                a["sample_id"] == sample["id"] and a["status"] == "RESOLVED"
                for a in actions
            )

        unresolved_failed = [
            s for s in samples if s["outcome"] == "FAILED" and not has_resolved(s)
        ]
        expired_no_response = [s for s in samples if s["outcome"] == "EXPIRED_NO_RESPONSE"]
        nonterminal = [s for s in samples if s["outcome"] in SAMPLE_NONTERMINAL_OUTCOMES]
        failed = [s for s in samples if s["outcome"] == "FAILED"]
        if unresolved_failed or expired_no_response:
            new = "FAILED_SAMPLING"
        elif nonterminal:
            new = "SAMPLED"
        elif failed:
            new = "REMEDIATED"
        else:
            new = "SAMPLED"
    if cust["audit_standing"] != new:
        cust["audit_standing"] = new
        return True
    return False


def recompute_audit_posture(tenant):
    """PRD §3.1/§3.8/§3.9: posture follows the most advanced active campaign.
    Returns True when the value changed."""
    camps = [
        c
        for c in db.stores["audit_campaigns"].values()
        if c["tenant_id"] == tenant["id"]
    ]
    active = [c for c in camps if c["status"] not in ("CLOSED", "CANCELLED")]
    if any(c["status"] == "DEFENSE_ASSEMBLY" for c in active):
        new = "DEFENSE_ASSEMBLY"
    elif any(c["status"] == "REMEDIATION" for c in active):
        new = "IN_REMEDIATION"
    elif any(c["status"] in ("SAMPLING", "FIELDWORK") for c in active):
        new = "UNDER_SAMPLING"
    else:
        new = "CLEAR"
    if tenant["audit_posture"] != new:
        tenant["audit_posture"] = new
        return True
    return False


# ---------------------------------------------------------------------------
# PRD §3.5 exemption coverage calculation (dual variant)
# ---------------------------------------------------------------------------

def find_covering_cert(order):
    """An approved certificate held by the order's customer, covering the
    order's ship_to_state, and carrying the claimed exemption_reason_code."""
    cands = [
        c
        for c in db.stores["certificates"].values()
        if c["tenant_id"] == order["tenant_id"]
        and c["customer_id"] == order["customer_id"]
        and c["status"] == "APPROVED"
        and c["ship_to_state"] == order["ship_to_state"]
        and c["exemption_reason_code"] == order["exemption_reason_code"]
    ]
    cands.sort(key=lambda c: c["_seq"])
    return cands[0] if cands else None


def compute_amounts(order, tenant):
    """Returns (exempt, covered, uncovered) per §3.5. Integer cents
    throughout; the proportional fallback is one half rounded up."""
    lines = order_lines_of(order["id"])
    exempt = sum(l["extended_cents"] for l in lines if l["is_exempt_claimed"])
    cert = find_covering_cert(order)
    if tenant.get("coverage_mode") == "LINE_LEVEL_PROPORTIONAL":
        if cert is None:
            covered = 0
        else:
            matching = sum(
                l["extended_cents"]
                for l in lines
                if l["is_exempt_claimed"] and str(l["sku"]).startswith("EX")
            )
            covered = matching if matching > 0 else (exempt + 1) // 2
    else:  # FULL_CERT
        covered = exempt if cert is not None else 0
    return exempt, covered, exempt - covered


def recompute_order_amounts(order, tenant):
    exempt, covered, uncovered = compute_amounts(order, tenant)
    order["exempt_amount_cents"] = exempt
    order["covered_amount_cents"] = covered
    order["uncovered_amount_cents"] = uncovered


# ---------------------------------------------------------------------------
# PRD §3.3 cert_validity_window calculation
# ---------------------------------------------------------------------------

def compute_expiration(cert, tenant):
    """Anchor = certificate's effective_date (EFFECTIVE_DATE) or signed_date
    (SIGNED_DATE); window 0 -> never expires; else anchor + window days."""
    rule = find_rule(tenant["id"], cert["ship_to_state"])
    if not rule or rule["validity_window_days"] == 0:
        return None
    anchor = (
        cert["effective_date"]
        if rule["anchor_rule"] == "EFFECTIVE_DATE"
        else cert["signed_date"]
    )
    return (parse_day(anchor) + timedelta(days=rule["validity_window_days"])).isoformat()


# ---------------------------------------------------------------------------
# Cascades (PRD §3.3 approval, §3.4 suspension/expiration/revocation)
# ---------------------------------------------------------------------------

def approval_cascade(cert, tenant, cust):
    """Runs after a certificate lands in APPROVED: supersession, standings,
    held-order release, exposure restatement. Bumps per PRD §2.5/§3.3."""
    old_id = cert.get("supersedes_certificate_id")
    if old_id:
        old = db.stores["certificates"].get(old_id)
        if old and old["tenant_id"] == tenant["id"]:
            if old["ship_to_state"] != cert["ship_to_state"]:
                raise ApiError(
                    "ERR_INVALID_STATE_TRANSITION",
                    "Renewal certificate's ship_to_state must equal the superseded certificate's",
                    409,
                )
            if old["status"] == "APPROVED":
                old["status"] = "SUPERSEDED"
                old["superseded_by_certificate_id"] = cert["id"]
                bump(old)
    recompute_cert_standing(cust)
    recompute_collection_standing(cust, tenant)
    bump(cust)
    for order in customer_orders(cust["id"]):
        if order["status"] == "HELD_FOR_CERT":
            recompute_order_amounts(order, tenant)
            if order["uncovered_amount_cents"] == 0:
                order["status"] = "READY_TO_SHIP"
            bump(order)
    recompute_blocked_exposure(cust)
    recompute_open_exposure(tenant)
    bump(tenant)


def regate_cascade(tenant, cust):
    """Runs after an APPROVED cert leaves that status (suspend/expire/revoke):
    standings recompute; READY_TO_SHIP orders whose coverage fell short are
    pulled back to HELD_FOR_CERT; exposures restated."""
    recompute_cert_standing(cust)
    recompute_collection_standing(cust, tenant)
    bump(cust)
    for order in customer_orders(cust["id"]):
        if order["status"] == "READY_TO_SHIP":
            recompute_order_amounts(order, tenant)
            if order["uncovered_amount_cents"] > 0:
                order["status"] = "HELD_FOR_CERT"
                bump(order)
    recompute_blocked_exposure(cust)
    recompute_open_exposure(tenant)
    bump(tenant)


# ---------------------------------------------------------------------------
# PRD §3.8 audit sample size calculation (dual variant)
# ---------------------------------------------------------------------------

def sampling_population(tenant, campaign):
    """APPROVED certs for the tenant, restricted to population_state_filter
    when non-empty; deterministic creation order."""
    certs = [
        c
        for c in db.stores["certificates"].values()
        if c["tenant_id"] == tenant["id"] and c["status"] == "APPROVED"
    ]
    filt = campaign.get("population_state_filter") or []
    if filt:
        certs = [c for c in certs if c["ship_to_state"] in filt]
    certs.sort(key=lambda c: c["_seq"])
    return certs


def compute_planned_sample_size(population_count, campaign):
    if campaign["sampling_method"] == "STATISTICAL":
        mult = CONFIDENCE_MULTIPLIERS[campaign["target_confidence_pct"]]
        product = Decimal(population_count) * mult
        # ceiling: any fractional result rounds up to the next whole sample
        planned = int(product.to_integral_value(rounding="ROUND_CEILING"))
        return max(planned, 1)
    # FIXED_FLOOR: max(floor_sample_size, min(population, 5))
    return max(campaign["floor_sample_size"], min(population_count, FIXED_FLOOR_POP_CAP))


def create_samples_for_campaign(campaign, tenant, certs):
    """Create exactly planned_sample_size AuditSample rows in PENDING, cycling
    the population deterministically when the plan exceeds it."""
    created = []
    n = campaign["planned_sample_size"] or 0
    if not certs or n <= 0:
        return created
    for i in range(n):
        cert = certs[i % len(certs)]
        rec = db.make_record({
            "tenant_id": tenant["id"],
            "campaign_id": campaign["id"],
            "certificate_id": cert["id"],
            "customer_id": cert["customer_id"],
            "sampled_at_day_index": tenant["audit_clock_day_index"],
            "doc_due_day_index": tenant["audit_clock_day_index"] + DOC_RESPONSE_WINDOW_DAYS,
            "outcome": "PENDING",
            "failure_reason": None,
        })
        db.stores["audit_samples"][rec["id"]] = rec
        created.append(rec)
    # Every customer named by a new sample moves to SAMPLED.
    for cust_id in {s["customer_id"] for s in created}:
        cust = db.stores["customers"].get(cust_id)
        if cust:
            recompute_audit_standing(cust)
            bump(cust)
    return created


def maybe_campaign_to_remediation(campaign, tenant):
    """PRD §3.8: when every sample has reached a terminal outcome the campaign
    transitions FIELDWORK -> REMEDIATION and posture -> IN_REMEDIATION."""
    if campaign["status"] != "FIELDWORK":
        return
    samples = [
        s for s in db.stores["audit_samples"].values() if s["campaign_id"] == campaign["id"]
    ]
    if samples and all(s["outcome"] in SAMPLE_TERMINAL_OUTCOMES for s in samples):
        campaign["status"] = "REMEDIATION"
        bump(campaign)
        recompute_audit_posture(tenant)
        bump(tenant)


# ---------------------------------------------------------------------------
# PRD §3.7 outreach send execution
# ---------------------------------------------------------------------------

def execute_outreach_send(campaign, tenant):
    """SCHEDULED -> SENDING -> DONE within the same clock advance. Candidate
    window is inclusive: a cert expiring exactly days_before_expiration days
    out is selected. Candidates ordered by customer.created_at ASC then
    certificate.created_at ASC (deterministic, no id tie-break)."""
    today = current_date(tenant)
    filt = campaign.get("target_state_filter") or []
    window = campaign["days_before_expiration"]
    candidates = []
    for cert in db.stores["certificates"].values():
        if cert["tenant_id"] != tenant["id"]:
            continue
        if cert["status"] != "APPROVED" or cert["expiration_date"] is None:
            continue
        remaining = (parse_day(cert["expiration_date"]) - today).days
        if remaining > window:
            continue
        if filt and cert["ship_to_state"] not in filt:
            continue
        cust = db.stores["customers"].get(cert["customer_id"])
        candidates.append((cust["_seq"] if cust else 0, cert["_seq"], cert))
    candidates.sort(key=lambda t: (t[0], t[1]))
    campaign["status"] = "SENDING"
    sent = campaign["sent_count"]
    notified = set()
    for _cseq, _kseq, cert in candidates:
        notice = db.make_notice({
            "campaign_id": campaign["id"],
            "tenant_id": tenant["id"],
            "customer_id": cert["customer_id"],
            "certificate_id": cert["id"],
            "scheduled_send_day_index": campaign["scheduled_send_day_index"],
            "sent_at_day_index": tenant["audit_clock_day_index"],
        })
        db.stores["outreach_notices"][notice["id"]] = notice
        sent += 1
        notified.add(cert["customer_id"])
    campaign["sent_count"] = sent
    for cust_id in notified:
        cust = db.stores["customers"].get(cust_id)
        if cust and cust["collection_standing"] != "RENEWAL_DUE":
            cust["collection_standing"] = "RENEWAL_DUE"
            bump(cust)
    campaign["status"] = "DONE"
    bump(campaign)


# ---------------------------------------------------------------------------
# PRD §2.4 clock advance cascades, in the documented order
# ---------------------------------------------------------------------------

def advance_day_cascades(tenant):
    day_idx = tenant["audit_clock_day_index"]
    today = current_date(tenant)

    # 1. Certificate expirations: APPROVED certs whose expiration_date falls
    # strictly before the new current day -> EXPIRED.
    affected = set()
    certs = sorted(
        (c for c in db.stores["certificates"].values() if c["tenant_id"] == tenant["id"]),
        key=lambda c: c["_seq"],
    )
    for cert in certs:
        if cert["status"] != "APPROVED" or cert["expiration_date"] is None:
            continue
        if parse_day(cert["expiration_date"]) < today:
            cert["status"] = "EXPIRED"
            bump(cert)
            cust = db.stores["customers"].get(cert["customer_id"])
            if cust:
                regate_cascade(tenant, cust)
                affected.add(cust["id"])

    # Renewal-window entry is clock-driven: recompute collection standing for
    # all customers once expirations have been processed.
    for cust in db.stores["customers"].values():
        if cust["tenant_id"] != tenant["id"]:
            continue
        changed = recompute_collection_standing(cust, tenant)
        if changed and cust["id"] not in affected:
            bump(cust)

    # 2. Audit response deadlines: DOC_REQUESTED samples whose
    # doc_due_day_index falls strictly before the new current day.
    samples = sorted(
        (s for s in db.stores["audit_samples"].values() if s["tenant_id"] == tenant["id"]),
        key=lambda s: s["_seq"],
    )
    for sample in samples:
        if sample["outcome"] != "DOC_REQUESTED":
            continue
        if sample["doc_due_day_index"] is not None and sample["doc_due_day_index"] < day_idx:
            sample["outcome"] = "EXPIRED_NO_RESPONSE"
            bump(sample)
            cust = db.stores["customers"].get(sample["customer_id"])
            if cust:
                recompute_audit_standing(cust)
                bump(cust)
            campaign = db.stores["audit_campaigns"].get(sample["campaign_id"])
            if campaign:
                maybe_campaign_to_remediation(campaign, tenant)

    # 3. Scheduled outreach: SCHEDULED campaigns whose send day is on or
    # before the new current day execute SENDING -> DONE in this call.
    campaigns = sorted(
        (c for c in db.stores["outreach_campaigns"].values() if c["tenant_id"] == tenant["id"]),
        key=lambda c: c["_seq"],
    )
    for campaign in campaigns:
        if campaign["status"] == "SCHEDULED" and campaign["scheduled_send_day_index"] <= day_idx:
            execute_outreach_send(campaign, tenant)


# ---------------------------------------------------------------------------
# PRD §3.9 defense packet completeness calculation
# ---------------------------------------------------------------------------

def compute_packet_fields(campaign):
    samples = [
        s for s in db.stores["audit_samples"].values() if s["campaign_id"] == campaign["id"]
    ]
    actions = list(db.stores["remediation_actions"].values())

    def has_resolved(sample):
        return any(
            a["sample_id"] == sample["id"] and a["status"] == "RESOLVED" for a in actions
        )

    def cert_seq(cert_id):
        cert = db.stores["certificates"].get(cert_id)
        return cert["_seq"] if cert else 0

    included_ids = sorted(
        {s["certificate_id"] for s in samples if s["outcome"] in ("PASSED", "WAIVED")},
        key=cert_seq,
    )
    missing_ids = sorted(
        {
            s["certificate_id"]
            for s in samples
            if s["outcome"] == "FAILED" and not has_resolved(s)
        },
        key=cert_seq,
    )
    total = len(included_ids) + len(missing_ids)
    if total == 0:
        score = 0
    else:
        score = int(
            (Decimal(100 * len(included_ids)) / Decimal(total)).to_integral_value(
                rounding=ROUND_HALF_UP
            )
        )
    return included_ids, missing_ids, score
