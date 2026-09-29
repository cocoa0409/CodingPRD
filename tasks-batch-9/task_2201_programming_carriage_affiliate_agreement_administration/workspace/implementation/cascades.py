"""Multi-entity cascades and the pinned clock sweep (PRD sections 2.4 - 2.5)."""
import constants as K
from calc import blackout_key_rules, window_neighbours
from errors import ApiError
from store import D, add_months, db, floor_days, now, touch


# ---------------------------------------------------------------------------
# content title derivation
# ---------------------------------------------------------------------------
def title_windows(title_id):
    return [w for w in db.rights_windows.values() if w["content_title_id"] == title_id]


def recompute_title(title):
    """Re-derive cleared_window_count and coverage from the current window set."""
    if title is None:
        return None
    occupying = [
        w for w in title_windows(title["id"]) if w["status"] in ("CLEARED", "ACTIVE")
    ]
    platforms = set(w["platform"] for w in occupying)
    title["cleared_window_count"] = len(occupying)

    if len(platforms) == 0:
        coverage = "UNDISTRIBUTED"
    elif platforms == {"LINEAR"}:
        coverage = "LINEAR_ONLY"
    elif len(platforms) >= 2:
        coverage = "MULTIPLATFORM"
    else:
        coverage = "EXCLUSIVE_UNCLEARED"
    title["distribution_coverage_status"] = coverage
    touch(title)
    return title


def recompute_titles(title_ids):
    for title_id in sorted(set(title_ids)):
        recompute_title(db.content_titles.get(title_id))


# ---------------------------------------------------------------------------
# rights window helpers
# ---------------------------------------------------------------------------
def agreement_windows(agreement_id):
    return [w for w in db.rights_windows.values() if w["agreement_id"] == agreement_id]


def window_order(windows):
    return sorted(windows, key=lambda w: (w["window_start"], w["created_at"], w["_seq"]))


def block_window(window, reason):
    window["status"] = "BLOCKED"
    window["block_reason"] = reason
    touch(window)
    return window["content_title_id"]


def block_windows_of_agreement(agreement_id, reason, statuses=("CLEARED", "ACTIVE")):
    touched = []
    for window in window_order(agreement_windows(agreement_id)):
        if window["status"] in statuses:
            touched.append(block_window(window, reason))
    return touched


def expire_windows_of_agreement(agreement_id, statuses):
    touched = []
    for window in window_order(agreement_windows(agreement_id)):
        if window["status"] in statuses:
            window["status"] = "EXPIRED"
            window["block_reason"] = "NONE"
            touch(window)
            touched.append(window["content_title_id"])
    return touched


def blackout_conflicts(window):
    """A SCHEDULED/ENFORCED rule of the same agreement + territory overlapping."""
    for rule in db.blackout_rules.values():
        if rule["agreement_id"] != window["agreement_id"]:
            continue
        if rule["territory_code"] != window["territory_code"]:
            continue
        if rule["status"] not in ("SCHEDULED", "ENFORCED"):
            continue
        if (
            rule["blackout_start"] < window["window_end"]
            and window["window_start"] <= rule["blackout_end"]
        ):
            return rule
    return None


def occupancy_admits(window):
    """True when the window may (re)occupy its title/platform/territory slot."""
    neighbours = window_neighbours(window)
    if window["exclusivity"] == "EXCLUSIVE":
        return (len(neighbours) == 0), len(neighbours)
    for other in neighbours:
        if other["exclusivity"] == "EXCLUSIVE":
            return False, len(neighbours)
    if len(neighbours) + 1 > K.MAX_CONCURRENT_NONEXCLUSIVE:
        return False, len(neighbours)
    return True, len(neighbours)


def unblock_suspended_windows(agreement_id):
    """Reinstatement path: recover only what is still recoverable."""
    touched = []
    for window in window_order(agreement_windows(agreement_id)):
        if window["status"] != "BLOCKED":
            continue
        if window["block_reason"] != "AGREEMENT_SUSPENDED":
            continue
        admits, count = occupancy_admits(window)
        if admits and blackout_conflicts(window) is None:
            window["status"] = "CLEARED"
            window["block_reason"] = "NONE"
            window["concurrent_licensee_count"] = count
            touch(window)
            touched.append(window["content_title_id"])
        else:
            window["block_reason"] = "BLACKOUT_CONFLICT"
            touch(window)
    return touched


# ---------------------------------------------------------------------------
# marketing commitments
# ---------------------------------------------------------------------------
def agreement_commitments(agreement_id):
    return [
        c for c in db.marketing_commitments.values() if c["agreement_id"] == agreement_id
    ]


def refresh_commitment_status(commitment):
    """Re-derive the ladder from the ledger figures (calculation C10)."""
    commitment["earned_unbilled_cents"] = (
        commitment["earned_cents"] - commitment["billed_cents"]
    )
    commitment["remaining_cents"] = (
        commitment["committed_cents"]
        - commitment["earned_cents"]
        - commitment["forfeited_cents"]
    )
    if commitment["forfeited_cents"] > 0:
        # Nothing un-forfeits a commitment.
        commitment["status"] = "FORFEITED"
    elif (
        commitment["remaining_cents"] == 0
        and commitment["earned_unbilled_cents"] == 0
        and commitment["billed_cents"] > 0
    ):
        commitment["status"] = "SETTLED"
    elif commitment["remaining_cents"] == 0 and commitment["earned_cents"] > 0:
        commitment["status"] = "EARNED"
    elif 0 < commitment["earned_cents"] < commitment["committed_cents"]:
        commitment["status"] = "PARTIALLY_EARNED"
    else:
        commitment["status"] = "OPEN"
    return commitment


def forfeit_commitment(commitment):
    if commitment["remaining_cents"] <= 0:
        return commitment
    commitment["forfeited_cents"] += commitment["remaining_cents"]
    commitment["remaining_cents"] = 0
    commitment["earned_unbilled_cents"] = (
        commitment["earned_cents"] - commitment["billed_cents"]
    )
    commitment["status"] = "FORFEITED"
    touch(commitment)
    return commitment


def forfeit_agreement_commitments(agreement_id):
    lines = sorted(
        agreement_commitments(agreement_id),
        key=lambda c: (c["performance_deadline"], c["created_at"], c["_seq"]),
    )
    for line in lines:
        if line["remaining_cents"] > 0:
            forfeit_commitment(line)


# ---------------------------------------------------------------------------
# agreement lifecycle cascades
# ---------------------------------------------------------------------------
def suspend_agreement(agreement, reason):
    """EXECUTED -> SUSPENDED plus the window/title cascade."""
    agreement["lifecycle_status"] = "SUSPENDED"
    agreement["suspension_reason"] = reason
    touch(agreement)
    touched = block_windows_of_agreement(agreement["id"], "AGREEMENT_SUSPENDED")
    recompute_titles(touched)
    return agreement


def expire_agreement(agreement):
    """Swept expiry, covering both the EXECUTED and the SUSPENDED form."""
    was_suspended = agreement["lifecycle_status"] == "SUSPENDED"
    if agreement["renewal_status"] in ("RENEWAL_ANALYSIS", "RENEWAL_OFFERED"):
        agreement["renewal_status"] = "LAPSED"
    agreement["lifecycle_status"] = "EXPIRED"
    agreement["suspension_reason"] = "NONE"
    touch(agreement)

    distributor = db.distributors.get(agreement["distributor_id"])
    if distributor is not None and distributor["executed_agreement_count"] > 0:
        distributor["executed_agreement_count"] -= 1
        touch(distributor)

    statuses = ["PLANNED", "CLEARED", "ACTIVE"]
    if was_suspended:
        statuses.append("BLOCKED")
    touched = expire_windows_of_agreement(agreement["id"], tuple(statuses))
    forfeit_agreement_commitments(agreement["id"])
    return touched


def terminate_agreement(agreement):
    """SUSPENDED -> TERMINATED (the NEGOTIATING form has no cascade)."""
    if agreement["renewal_status"] in ("RENEWAL_ANALYSIS", "RENEWAL_OFFERED"):
        agreement["renewal_status"] = "LAPSED"
    agreement["lifecycle_status"] = "TERMINATED"
    agreement["suspension_reason"] = "NONE"
    touch(agreement)

    distributor = db.distributors.get(agreement["distributor_id"])
    if distributor is not None and distributor["executed_agreement_count"] > 0:
        distributor["executed_agreement_count"] -= 1
        touch(distributor)

    touched = expire_windows_of_agreement(
        agreement["id"], ("PLANNED", "CLEARED", "ACTIVE", "BLOCKED")
    )
    forfeit_agreement_commitments(agreement["id"])
    recompute_titles(touched)
    return agreement


def distributor_agreements(distributor_id):
    return [a for a in db.agreements.values() if a["distributor_id"] == distributor_id]


def apply_credit_hold(distributor, reason):
    """Invoice-issue cascade links 2-5: hold, suspend, block, re-derive."""
    distributor["status"] = "CREDIT_HOLD"
    distributor["credit_hold_reason"] = reason
    touch(distributor)

    touched = []
    executed = [
        a
        for a in distributor_agreements(distributor["id"])
        if a["lifecycle_status"] == "EXECUTED"
    ]
    executed.sort(key=lambda a: (a["created_at"], a["_seq"]))
    for agreement in executed:
        agreement["lifecycle_status"] = "SUSPENDED"
        agreement["suspension_reason"] = "DISTRIBUTOR_CREDIT_HOLD"
        touch(agreement)
        touched.extend(
            block_windows_of_agreement(agreement["id"], "AGREEMENT_SUSPENDED")
        )
    recompute_titles(touched)
    return distributor


# ---------------------------------------------------------------------------
# the pinned six-step clock sweep
# ---------------------------------------------------------------------------
def run_sweep():
    current = now()
    touched_titles = []

    # STEP 1 - agreement expiry
    expiring = [
        a
        for a in db.agreements.values()
        if a["lifecycle_status"] in ("EXECUTED", "SUSPENDED")
        and a["term_end_date"] <= current
        and not (a["lifecycle_status"] == "EXECUTED" and a["renewal_status"] == "RENEWED")
    ]
    expiring.sort(key=lambda a: (a["term_end_date"], a["created_at"], a["_seq"]))
    for agreement in expiring:
        touched_titles.extend(expire_agreement(agreement))

    # STEP 2 - CLEARED -> ACTIVE
    activating = [
        w
        for w in db.rights_windows.values()
        if w["status"] == "CLEARED"
        and w["window_start"] <= current
        and w["window_end"] > current
    ]
    activating.sort(key=lambda w: (w["window_start"], w["created_at"], w["_seq"]))
    for window in activating:
        agreement = db.agreements.get(window["agreement_id"])
        if agreement is None or agreement["lifecycle_status"] != "EXECUTED":
            continue
        window["status"] = "ACTIVE"
        touch(window)
        touched_titles.append(window["content_title_id"])

    # STEP 3 - CLEARED / ACTIVE -> EXPIRED
    ending = [
        w
        for w in db.rights_windows.values()
        if w["status"] in ("CLEARED", "ACTIVE") and w["window_end"] <= current
    ]
    ending.sort(key=lambda w: (w["window_end"], w["created_at"], w["_seq"]))
    for window in ending:
        window["status"] = "EXPIRED"
        touch(window)
        touched_titles.append(window["content_title_id"])

    # STEP 4 - blackout expiry
    stale = [
        b
        for b in db.blackout_rules.values()
        if b["status"] == "SCHEDULED" and b["blackout_end"] < current
    ]
    stale.sort(key=lambda b: (b["blackout_end"], b["created_at"], b["_seq"]))
    for rule in stale:
        rule["status"] = "EXPIRED"
        touch(rule)

    # STEP 5 - commitment forfeiture
    lapsed = [
        c
        for c in db.marketing_commitments.values()
        if c["performance_deadline"] < current and c["remaining_cents"] > 0
    ]
    lapsed.sort(key=lambda c: (c["performance_deadline"], c["created_at"], c["_seq"]))
    for commitment in lapsed:
        forfeit_commitment(commitment)

    # STEP 6 - re-derive every touched content title
    recompute_titles(touched_titles)


# ---------------------------------------------------------------------------
# shared temporal predicates
# ---------------------------------------------------------------------------
def renewal_window_open(agreement):
    return floor_days(agreement["term_end_date"], now()) <= K.RENEWAL_WINDOW_DAYS


def audit_rights_alive(agreement, sample_period_end):
    """Survival test used at engagement open and at fieldwork start."""
    term_end = agreement["term_end_date"]
    end_month_key = "%04d-%02d" % (term_end.year, term_end.month)
    if sample_period_end > end_month_key:
        return False
    if agreement["lifecycle_status"] == "EXPIRED":
        deadline = add_months(term_end, K.AUDIT_RIGHTS_SURVIVAL_MONTHS)
        if now() > deadline:
            return False
    return True
