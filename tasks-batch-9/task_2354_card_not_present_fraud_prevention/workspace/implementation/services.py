"""Domain services: recounts, cascades and the scoring pipeline.

Every function here mutates the in-memory store only. Version discipline is
delegated to db.touch(), which moves updated_at and version at most once per row
per request (PRD 2.5 / 2.9).
"""

from datetime import timedelta

import calc
from db import db, mark_fresh, new_id, sort_rows, touch


# ------------------------------------------------------------------ row helpers
def new_row(**fields):
    """Common-field row: id, created_at, updated_at, version (PRD 2.5)."""
    now = db.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    rec.update(fields)
    mark_fresh(rec)
    return rec


def new_immutable_row(**fields):
    """FraudRule: only id and created_at; no updated_at and no version."""
    rec = {"id": new_id(), "created_at": db.now(), "_seq": db.next_seq()}
    rec.update(fields)
    return rec


# ---------------------------------------------------------------- address helpers
def resolve_cluster(address_id):
    """Cluster root id of an address row (PRD 2.10)."""
    return db.addresses[address_id]["canonical_address_id"]


def cluster_root(address_id):
    return db.addresses[resolve_cluster(address_id)]


def cluster_member_ids(root):
    ids = set([root["id"]])
    for row in db.addresses.values():
        if row.get("canonical_parent_address_id") == root["id"]:
            ids.add(row["id"])
    return ids


# ------------------------------------------------------------------- recomputes
def recompute_device(device):
    """device_reputation_recompute — full recount, never an increment."""
    rows = [
        a for a in db.assessments.values()
        if a["device_profile_id"] == device["id"]
    ]
    customers = set(a["customer_id"] for a in rows if a["decision"] is not None)
    for event in db.auth_events.values():
        if event["device_profile_id"] == device["id"]:
            customers.add(event["customer_id"])
    device["distinct_customer_count"] = len(customers)
    device["approved_use_count"] = len(
        [a for a in rows if a["state"] == "DECIDED_APPROVE"]
    )
    device["fraud_confirmed_count"] = len(
        [a for a in rows if a["outcome_label"] == "FRAUD"]
    )
    device["reputation"] = calc.device_reputation(
        device["fraud_confirmed_count"],
        device["distinct_customer_count"],
        device["approved_use_count"],
        device["emulator_flag"],
    )
    touch(device)


def recompute_address_cluster(root):
    """address_intelligence_recompute — maintained on the cluster ROOT only."""
    if root.get("canonical_parent_address_id") is not None:
        root = cluster_root(root["id"])
    member_ids = cluster_member_ids(root)
    rows = [
        a for a in db.assessments.values()
        if a["shipping_address_id"] in member_ids
    ]
    root["distinct_customer_count"] = len(
        set(a["customer_id"] for a in rows if a["decision"] is not None)
    )
    root["approved_use_count"] = len(
        [a for a in rows if a["state"] == "DECIDED_APPROVE"]
    )
    root["fraud_confirmed_count"] = len(
        [a for a in rows if a["outcome_label"] == "FRAUD"]
    )
    root["promo_redemption_count"] = len(
        [
            a for a in rows
            if a.get("promo_code") is not None and a["state"] == "DECIDED_APPROVE"
        ]
    )
    root["drop_risk_state"] = calc.drop_risk_state(
        root["fraud_confirmed_count"],
        root["distinct_customer_count"],
        root["classification"],
    )
    root["reshipper_confidence"] = calc.reshipper_confidence(
        root["distinct_customer_count"],
        root["promo_redemption_count"],
        root["classification"],
    )
    touch(root)


def recompute_good_standing(customer):
    customer["good_customer_flag"] = calc.customer_good_standing(customer)


# -------------------------------------------------------------- review priority
def case_priority(case):
    assessment = db.assessments[case["assessment_id"]]
    customer = db.customers[assessment["customer_id"]]
    return calc.review_case_priority_score(
        assessment, customer, case["escalation_count"]
    )


def reprice_open_cases(customer_id):
    for case in sort_rows(list(db.review_cases.values())):
        if case["state"] not in ("QUEUED", "ASSIGNED", "ESCALATED"):
            continue
        assessment = db.assessments.get(case["assessment_id"])
        if assessment is None or assessment["customer_id"] != customer_id:
            continue
        case["priority_score"] = case_priority(case)
        touch(case)


def cases_for_assessment(assessment_id):
    return sort_rows(
        [
            c for c in db.review_cases.values()
            if c["assessment_id"] == assessment_id
        ]
    )


# --------------------------------------------------------- containment cascade
def contain_customer(customer):
    """The four-link ATO containment chain (PRD 3.7)."""
    now = db.now()
    customer["ato_posture"] = "CONTAINED"
    customer["account_status"] = "LOCKED"
    customer["locked_reason"] = "ATO_CONTAINMENT"

    in_review = [
        a for a in sort_rows(list(db.assessments.values()))
        if a["customer_id"] == customer["id"] and a["state"] == "IN_REVIEW"
    ]
    for assessment in in_review:
        assessment["state"] = "DECIDED_DECLINE"
        assessment["decision_reason"] = "ATO_CONTAINMENT"
        assessment["final_disposition"] = "DECLINED"
        assessment["decided_at"] = now
        touch(assessment)
        customer["declined_count"] += 1
        for case in cases_for_assessment(assessment["id"]):
            if case["state"] in ("RESOLVED_APPROVE", "RESOLVED_DECLINE"):
                continue
            analyst_id = case.get("assigned_analyst_id")
            case["state"] = "RESOLVED_DECLINE"
            case["resolved_at"] = now
            case["resolved_late"] = now > case["sla_due_at"]
            touch(case)
            if analyst_id is not None and analyst_id in db.analysts:
                analyst = db.analysts[analyst_id]
                analyst["open_case_count"] = max(
                    0, analyst["open_case_count"] - 1
                )
                touch(analyst)

    recompute_good_standing(customer)
    touch(customer)


# ------------------------------------------------------ shift-release cascade
def release_analyst_cases(analyst):
    for case in sort_rows(list(db.review_cases.values())):
        if case["state"] != "ASSIGNED":
            continue
        if case.get("assigned_analyst_id") != analyst["id"]:
            continue
        case["state"] = "QUEUED"
        case["assigned_analyst_id"] = None
        case["assigned_at"] = None
        case["requeue_count"] += 1
        touch(case)
    analyst["open_case_count"] = 0


# ---------------------------------------------------------- exception lookups
def address_whitelist_exception(assessment, now):
    """Rule-stage ADDRESS-family suppression (PRD 3.4 step two)."""
    cluster_id = resolve_cluster(assessment["shipping_address_id"])
    matches = []
    for exc in db.policy_exceptions.values():
        if exc["state"] != "APPROVED":
            continue
        if exc["customer_id"] != assessment["customer_id"]:
            continue
        if exc["scope"] != "ADDRESS_WHITELIST":
            continue
        if not (exc["effective_from"] <= now < exc["expires_at"]):
            continue
        target = exc.get("whitelisted_address_id")
        if target is None or target not in db.addresses:
            continue
        if resolve_cluster(target) != cluster_id:
            continue
        matches.append(exc)
    if not matches:
        return None
    return sort_rows(matches)[0]


def band_stage_exception(assessment, now):
    """Band-stage AUTO_APPROVE_UNDER_AMOUNT override (PRD 3.4 step four)."""
    matches = []
    for exc in db.policy_exceptions.values():
        if exc["state"] != "APPROVED":
            continue
        if exc["customer_id"] != assessment["customer_id"]:
            continue
        if exc["scope"] != "AUTO_APPROVE_UNDER_AMOUNT":
            continue
        if not (exc["effective_from"] <= now < exc["expires_at"]):
            continue
        if exc["max_amount_cents"] < assessment["amount_cents"]:
            continue
        matches.append(exc)
    if not matches:
        return None
    matches = sort_rows(matches)
    matches.sort(key=lambda e: -e["max_amount_cents"])
    return matches[0]


# ------------------------------------------------------------- pinned assets
def active_rule_pack(now):
    candidates = [
        p for p in db.rule_packs.values()
        if p["status"] == "ACTIVE"
        and p["effective_from"] <= now < p["effective_until"]
    ]
    if not candidates:
        return None
    return sort_rows(candidates)[0]


def active_risk_model():
    candidates = [m for m in db.risk_models.values() if m["status"] == "ACTIVE"]
    if not candidates:
        return None
    return sort_rows(candidates)[0]


def pack_rules(pack_id):
    rows = [r for r in db.fraud_rules.values() if r["rule_pack_id"] == pack_id]
    return sorted(rows, key=lambda r: (r["evaluation_order"], r["created_at"], r["_seq"]))


# ------------------------------------------------------------ scoring pipeline
def _velocity_signals(assessment, now):
    customer_window_start = now - timedelta(
        seconds=calc.VELOCITY_CUSTOMER_WINDOW_SECONDS
    )
    device_window_start = now - timedelta(
        seconds=calc.VELOCITY_DEVICE_WINDOW_SECONDS
    )
    promo_window_start = now - timedelta(
        seconds=calc.VELOCITY_PROMO_WINDOW_SECONDS
    )

    customer_count = 0
    bins = set([assessment["card_bin"]])
    promo_count = 0
    cluster_id = resolve_cluster(assessment["shipping_address_id"])

    for other in db.assessments.values():
        if other["id"] == assessment["id"]:
            continue
        created = other["created_at"]
        if (
            other["customer_id"] == assessment["customer_id"]
            and customer_window_start <= created <= now
        ):
            customer_count += 1
        if (
            other["device_profile_id"] == assessment["device_profile_id"]
            and device_window_start <= created <= now
        ):
            bins.add(other["card_bin"])
        if (
            other.get("promo_code") is not None
            and promo_window_start <= created <= now
            and other["shipping_address_id"] in db.addresses
            and resolve_cluster(other["shipping_address_id"]) == cluster_id
        ):
            promo_count += 1

    return customer_count, len(bins), promo_count


def _predicate(code, assessment, device, ship, bill, root, velocity):
    customer_1h, bin_24h, promo_30d = velocity
    if code == "DEV_MULTI_ACCOUNT":
        return device["distinct_customer_count"] >= 3
    if code == "DEV_EMULATOR":
        return device["emulator_flag"] is True
    if code == "BEH_FAST_CHECKOUT":
        return assessment["session_seconds"] < 45
    if code == "BEH_BULK_CART":
        return assessment["cart_item_count"] >= 10
    if code == "VEL_CUSTOMER_1H":
        return customer_1h >= 3
    if code == "VEL_DEVICE_CARD_24H":
        return bin_24h >= 3
    if code == "ID_GEO_MISMATCH":
        return assessment["ip_country"] != bill["country_code"]
    if code == "ADDR_DROP_RISK":
        return root["drop_risk_state"] == "KNOWN_DROP"
    if code == "ADDR_FREIGHT_FORWARDER":
        return ship["classification"] == "FREIGHT_FORWARDER"
    if code == "PROMO_ADDRESS_ABUSE":
        return assessment.get("promo_code") is not None and promo_30d >= 2
    return False


def score_assessment(assessment):
    """Runs the whole pipeline and resolves the three-way fork (PRD 3.4)."""
    now = db.now()
    customer = db.customers[assessment["customer_id"]]
    device = db.devices[assessment["device_profile_id"]]
    pack = db.rule_packs[assessment["rule_pack_id"]]
    model = db.risk_models[assessment["risk_model_id"]]
    ship = db.addresses[assessment["shipping_address_id"]]
    bill = db.addresses[assessment["billing_address_id"]]
    root = cluster_root(assessment["shipping_address_id"])

    # --- step one: velocity windows
    velocity = _velocity_signals(assessment, now)
    assessment["velocity_customer_assessment_count_1h"] = velocity[0]
    assessment["velocity_device_distinct_card_bin_count_24h"] = velocity[1]
    assessment["velocity_promo_address_count_30d"] = velocity[2]

    # --- step two: the rule walk
    suppressor = address_whitelist_exception(assessment, now)
    applied_exception = None
    fired = []
    for rule in pack_rules(pack["id"]):
        if not _predicate(rule["code"], assessment, device, ship, bill, root, velocity):
            continue
        if rule["signal_family"] == "ADDRESS" and suppressor is not None:
            # Suppressed: no points, absent from triggered_rule_codes and unable
            # to short-circuit, but it does claim applied_exception_id.
            applied_exception = suppressor
            continue
        fired.append(rule)
        if rule["hard_decline"]:
            break

    rule_score = min(calc.RULE_SCORE_CAP, sum(r["points"] for r in fired))
    assessment["rule_score"] = rule_score
    assessment["triggered_rule_codes"] = [r["code"] for r in fired]
    assessment["hard_decline_triggered"] = any(r["hard_decline"] for r in fired)
    if fired:
        best = sorted(
            fired, key=lambda r: (-r["points"], r["evaluation_order"], r["created_at"], r["_seq"])
        )[0]
        assessment["primary_signal_family"] = best["signal_family"]
    else:
        assessment["primary_signal_family"] = "MODEL"

    # --- step three: blending
    model_points = calc.model_point_calibration(
        assessment["model_raw_probability"],
        model["calibration_intercept"],
        model["calibration_slope"],
    )
    assessment["model_points"] = model_points
    blended = calc.blended_risk_score(
        pack["blend_mode"],
        pack["rule_weight"],
        pack["model_weight"],
        rule_score,
        model_points,
    )
    assessment["blended_score"] = blended

    # --- step four: the band decision
    if assessment["hard_decline_triggered"]:
        decision, reason = "DECLINE", "HARD_RULE"
    elif blended >= calc.dec(pack["decline_floor_score"]):
        decision, reason = "DECLINE", "SCORE_BAND"
    elif blended >= calc.dec(pack["review_floor_score"]):
        band_exception = band_stage_exception(assessment, now)
        if band_exception is not None:
            decision, reason = "APPROVE", "POLICY_EXCEPTION"
            applied_exception = band_exception
        else:
            decision, reason = "REVIEW", "SCORE_BAND"
    else:
        decision, reason = "APPROVE", "SCORE_BAND"

    assessment["decision"] = decision
    assessment["decision_reason"] = reason
    assessment["applied_exception_id"] = (
        applied_exception["id"] if applied_exception is not None else None
    )

    model["scored_assessment_count"] += 1
    touch(model)

    # --- step five: the three-way fork
    if decision == "APPROVE":
        assessment["state"] = "DECIDED_APPROVE"
        assessment["final_disposition"] = "APPROVED"
        assessment["decided_at"] = now
        assessment["good_customer_at_decision"] = customer["good_customer_flag"]
        touch(assessment)
        customer["approved_count"] += 1
        customer["lifetime_net_approved_cents"] += assessment["amount_cents"]
        recompute_good_standing(customer)
        touch(customer)
        recompute_address_cluster(root)
        recompute_device(device)
        if applied_exception is not None:
            applied_exception["consumed_count"] += 1
            touch(applied_exception)
    elif decision == "REVIEW":
        assessment["state"] = "IN_REVIEW"
        touch(assessment)
        case = new_row(
            assessment_id=assessment["id"],
            assigned_analyst_id=None,
            escalated_by_analyst_id=None,
            state="QUEUED",
            primary_signal_family=assessment["primary_signal_family"],
            priority_score=calc.dec("0.00"),
            sla_due_at=now + timedelta(seconds=calc.SLA_SECONDS),
            assigned_at=None,
            resolved_at=None,
            requeue_count=0,
            escalation_count=0,
            resolved_late=None,
            resolution_note=None,
        )
        db.review_cases[case["id"]] = case
        case["priority_score"] = case_priority(case)
        recompute_device(device)
        recompute_address_cluster(root)
    else:
        assessment["state"] = "DECIDED_DECLINE"
        assessment["final_disposition"] = "DECLINED"
        assessment["decided_at"] = now
        assessment["good_customer_at_decision"] = customer["good_customer_flag"]
        touch(assessment)
        customer["declined_count"] += 1
        touch(customer)
        recompute_device(device)
        recompute_address_cluster(root)

    return assessment


# ------------------------------------------------- manual resolution cascades
def resolve_case_approve(case, note):
    now = db.now()
    analyst_id = case.get("assigned_analyst_id")
    case["state"] = "RESOLVED_APPROVE"
    case["resolved_at"] = now
    case["resolved_late"] = now > case["sla_due_at"]
    if note is not None:
        case["resolution_note"] = note
    touch(case)

    if analyst_id is not None and analyst_id in db.analysts:
        analyst = db.analysts[analyst_id]
        analyst["open_case_count"] = max(0, analyst["open_case_count"] - 1)
        analyst["resolved_case_count"] += 1
        touch(analyst)

    assessment = db.assessments[case["assessment_id"]]
    assessment["state"] = "DECIDED_APPROVE"
    assessment["decision_reason"] = "MANUAL_REVIEW"
    assessment["final_disposition"] = "APPROVED"
    assessment["decided_at"] = now
    touch(assessment)

    customer = db.customers[assessment["customer_id"]]
    customer["approved_count"] += 1
    customer["lifetime_net_approved_cents"] += assessment["amount_cents"]
    recompute_good_standing(customer)
    touch(customer)

    recompute_address_cluster(cluster_root(assessment["shipping_address_id"]))
    recompute_device(db.devices[assessment["device_profile_id"]])


def resolve_case_decline(case, note):
    now = db.now()
    analyst_id = case.get("assigned_analyst_id")
    case["state"] = "RESOLVED_DECLINE"
    case["resolved_at"] = now
    case["resolved_late"] = now > case["sla_due_at"]
    if note is not None:
        case["resolution_note"] = note
    touch(case)

    if analyst_id is not None and analyst_id in db.analysts:
        analyst = db.analysts[analyst_id]
        analyst["open_case_count"] = max(0, analyst["open_case_count"] - 1)
        analyst["resolved_case_count"] += 1
        touch(analyst)

    assessment = db.assessments[case["assessment_id"]]
    assessment["state"] = "DECIDED_DECLINE"
    assessment["decision_reason"] = "MANUAL_REVIEW"
    assessment["final_disposition"] = "DECLINED"
    assessment["decided_at"] = now
    touch(assessment)

    customer = db.customers[assessment["customer_id"]]
    customer["declined_count"] += 1
    touch(customer)

    recompute_device(db.devices[assessment["device_profile_id"]])
    recompute_address_cluster(cluster_root(assessment["shipping_address_id"]))


def escalate_case(case, actor_analyst_id, note):
    analyst_id = case.get("assigned_analyst_id")
    case["state"] = "ESCALATED"
    case["escalated_by_analyst_id"] = actor_analyst_id
    case["assigned_analyst_id"] = None
    # assigned_at is the instant of the most recent assignment and is preserved:
    # only the shift-release cascade clears it.
    case["escalation_count"] += 1
    if note is not None:
        case["resolution_note"] = note
    case["priority_score"] = case_priority(case)
    touch(case)

    if analyst_id is not None and analyst_id in db.analysts:
        analyst = db.analysts[analyst_id]
        analyst["open_case_count"] = max(0, analyst["open_case_count"] - 1)
        touch(analyst)


def assign_case(case, analyst):
    now = db.now()
    case["state"] = "ASSIGNED"
    case["assigned_analyst_id"] = analyst["id"]
    case["assigned_at"] = now
    touch(case)
    analyst["open_case_count"] += 1
    touch(analyst)


# ----------------------------------------------------- chargeback loss cascade
def apply_guarantee(chargeback, assessment):
    state, reason, eligible, fee, reimbursed = calc.guarantee_liability_evaluation(
        chargeback, assessment
    )
    chargeback["guarantee_state"] = state
    chargeback["guarantee_denial_reason"] = reason
    chargeback["guarantee_eligible_cents"] = eligible
    chargeback["guarantee_fee_cents"] = fee
    chargeback["guarantee_reimbursed_cents"] = reimbursed


def chargeback_lose(chargeback):
    now = db.now()
    assessment = db.assessments[chargeback["assessment_id"]]
    chargeback["state"] = "LOST"
    chargeback["resolved_at"] = now
    apply_guarantee(chargeback, assessment)
    touch(chargeback)

    if chargeback["reason_code"] not in calc.GUARANTEE_COVERED_REASON_CODES:
        return
    if assessment["outcome_label"] != "UNKNOWN":
        # Idempotence guard: links 2-5 fire only on the UNKNOWN -> FRAUD move.
        return

    assessment["outcome_label"] = "FRAUD"
    touch(assessment)

    customer = db.customers[assessment["customer_id"]]
    customer["lifetime_net_approved_cents"] -= assessment["amount_cents"]
    customer["confirmed_fraud_count"] += 1
    was_good = customer["good_customer_flag"]
    recompute_good_standing(customer)
    touch(customer)

    if was_good and not customer["good_customer_flag"]:
        reprice_open_cases(customer["id"])

    recompute_device(db.devices[assessment["device_profile_id"]])
    recompute_address_cluster(cluster_root(assessment["shipping_address_id"]))


def chargeback_win(chargeback):
    now = db.now()
    chargeback["state"] = "WON"
    chargeback["resolved_at"] = now
    touch(chargeback)
    assessment = db.assessments[chargeback["assessment_id"]]
    assessment["outcome_label"] = "LEGIT"
    touch(assessment)


# ------------------------------------------------------- rule pack activation
def activate_rule_pack(pack, user_id):
    now = db.now()
    pack["status"] = "ACTIVE"
    pack["activated_at"] = now
    pack["activated_by_user_id"] = user_id
    touch(pack)
    for other in sort_rows(list(db.rule_packs.values())):
        if other["id"] == pack["id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        if other["effective_until"] <= pack["effective_from"]:
            other["status"] = "RETIRED"
            other["retired_at"] = now
            touch(other)


def rule_pack_window_collision(pack):
    freeze = timedelta(seconds=calc.RULE_PACK_ACTIVATION_FREEZE_SECONDS)
    for other in db.rule_packs.values():
        if other["id"] == pack["id"]:
            continue
        if other["status"] not in ("ACTIVE", "RETIRED"):
            continue
        clear = (
            pack["effective_until"] + freeze <= other["effective_from"]
            or other["effective_until"] + freeze <= pack["effective_from"]
        )
        if not clear:
            return True
    return False


# --------------------------------------------------------- model lifecycle
def training_segment_counts(cutoff):
    counts = {}
    for segment in calc.REQUIRED_TRAINING_SEGMENTS:
        counts[segment] = len(
            [
                cb for cb in db.chargebacks.values()
                if cb["state"] == "LOST"
                and cb["reason_code"] == segment
                and cb["received_at"] < cutoff
            ]
        )
    return counts


def promote_model(model):
    now = db.now()
    for other in sort_rows(list(db.risk_models.values())):
        if other["id"] == model["id"]:
            continue
        if other["status"] == "ACTIVE":
            other["status"] = "RETIRED"
            other["retired_at"] = now
            touch(other)
    model["status"] = "ACTIVE"
    model["promoted_at"] = now
    touch(model)


# ----------------------------------------------------------- selector policy
def select_analyst(case):
    pool = []
    for analyst in db.analysts.values():
        if analyst["status"] != "AVAILABLE":
            continue
        if case["primary_signal_family"] not in analyst["skill_families"]:
            continue
        if analyst["open_case_count"] >= analyst["shift_capacity_cases"]:
            continue
        if case["state"] == "ESCALATED":
            if analyst["seniority"] != "LEAD":
                continue
            if analyst["id"] == case.get("escalated_by_analyst_id"):
                continue
        pool.append(analyst)
    if not pool:
        return None
    pool.sort(
        key=lambda a: (
            -(a["shift_capacity_cases"] - a["open_case_count"]),
            calc.SENIORITY_RANK[a["seniority"]],
            a["created_at"],
            a["id"],
        )
    )
    return pool[0]


# ------------------------------------------------------- performance report
def performance_report(pack_id, cohort):
    rows = [
        a for a in db.assessments.values()
        if a["rule_pack_id"] == pack_id
        and a["state"] in ("DECIDED_APPROVE", "DECIDED_DECLINE")
    ]
    if cohort == "GOOD_CUSTOMER_COHORT":
        rows = [a for a in rows if a.get("good_customer_at_decision") is True]
    denominator = len(rows)
    numerator = len(
        [
            a for a in rows
            if a["final_disposition"] == "DECLINED"
            and a["outcome_label"] != "FRAUD"
        ]
    )
    approved = len([a for a in rows if a["final_disposition"] == "APPROVED"])
    declined = len([a for a in rows if a["final_disposition"] == "DECLINED"])
    fraud = [a for a in rows if a["outcome_label"] == "FRAUD"]
    fraud_declined = [a for a in fraud if a["final_disposition"] == "DECLINED"]
    return {
        "cohort": cohort,
        "denominator_count": denominator,
        "approved_count": approved,
        "declined_count": declined,
        "false_positive_count": numerator,
        "confirmed_fraud_count": len(fraud),
        "insult_rate": calc.rate(numerator, denominator),
        "fraud_capture_rate": calc.rate(len(fraud_declined), len(fraud)),
    }
