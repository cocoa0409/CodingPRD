"""Domain services: lookups, rollups, state transitions and cascades."""

from datetime import timedelta

import calc
import store
from clock import add_days, clock, format_dt, parse_date, parse_iso
from errors import ApiError
from store import touch

TERMINAL_AGREEMENT = ("EXECUTED", "VOIDED")
NEGOTIABLE_AGREEMENT = ("DRAFTED", "SENT", "COUNTERED", "REVISED")
LIVE_AGREEMENT = ("DRAFTED", "SENT", "COUNTERED", "REVISED", "EXECUTED")


# ------------------------------------------------------------------- lookups
def find_or_404(collection, record_id, error_id):
    if not isinstance(record_id, str):
        raise ApiError(error_id)
    record = collection.get(record_id)
    if record is None:
        raise ApiError(error_id)
    return record


def get_production(production_id):
    return find_or_404(store.productions, production_id, "ERR_PRODUCTION_NOT_FOUND")


def get_location(location_id):
    return find_or_404(store.locations, location_id, "ERR_LOCATION_NOT_FOUND")


def get_casting_call(call_id):
    return find_or_404(store.casting_calls, call_id, "ERR_CASTING_CALL_NOT_FOUND")


def get_applicant(applicant_id):
    return find_or_404(store.applicants, applicant_id, "ERR_APPLICANT_NOT_FOUND")


def get_screening_item(item_id):
    return find_or_404(store.screening_items, item_id, "ERR_SCREENING_ITEM_NOT_FOUND")


def get_minor_protection(packet_id):
    return find_or_404(store.minor_protections, packet_id, "ERR_MINOR_PROTECTION_NOT_FOUND")


def get_agreement(agreement_id):
    return find_or_404(store.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")


def get_welfare_protocol(protocol_id):
    return find_or_404(store.welfare_protocols, protocol_id, "ERR_WELFARE_PROTOCOL_NOT_FOUND")


def get_shoot_block(block_id):
    return find_or_404(store.shoot_blocks, block_id, "ERR_SHOOT_BLOCK_NOT_FOUND")


def get_post_obligation(obligation_id):
    return find_or_404(store.post_obligations, obligation_id, "ERR_POST_OBLIGATION_NOT_FOUND")


def get_complaint(complaint_id):
    return find_or_404(store.complaints, complaint_id, "ERR_COMPLAINT_NOT_FOUND")


def production_of_call(call):
    return store.productions.get(call["production_id"])


def production_of_applicant(applicant):
    call = store.casting_calls.get(applicant["casting_call_id"])
    if call is None:
        return None
    return store.productions.get(call["production_id"])


def production_of_agreement(agreement):
    return store.productions.get(agreement["production_id"])


# ---------------------------------------------------------------- collections
def calls_of_production(production_id):
    return store.by_seq([c for c in store.casting_calls.values() if c["production_id"] == production_id])


def applicants_of_call(call_id):
    return store.by_seq([a for a in store.applicants.values() if a["casting_call_id"] == call_id])


def applicants_of_production(production_id):
    call_ids = {c["id"] for c in store.casting_calls.values() if c["production_id"] == production_id}
    return store.by_seq([a for a in store.applicants.values() if a["casting_call_id"] in call_ids])


def items_of_applicant(applicant_id):
    return store.by_seq([i for i in store.screening_items.values() if i["applicant_id"] == applicant_id])


def packets_of_applicant(applicant_id):
    return store.by_seq([p for p in store.minor_protections.values() if p["applicant_id"] == applicant_id])


def agreements_of_applicant(applicant_id):
    return store.by_seq([a for a in store.agreements.values() if a["applicant_id"] == applicant_id])


def agreements_of_production(production_id):
    return store.by_seq([a for a in store.agreements.values() if a["production_id"] == production_id])


def rounds_of_agreement(agreement_id):
    return store.by_seq([r for r in store.negotiation_rounds.values() if r["agreement_id"] == agreement_id])


def obligations_of_agreement(agreement_id):
    return store.by_seq([o for o in store.post_obligations.values() if o["agreement_id"] == agreement_id])


def complaints_of_agreement(agreement_id):
    return store.by_seq([c for c in store.complaints.values() if c["agreement_id"] == agreement_id])


def protocols_of_production(production_id):
    return store.by_seq(
        [p for p in store.welfare_protocols.values() if p["production_id"] == production_id]
    )


def blocks_of_production(production_id):
    return store.by_seq([b for b in store.shoot_blocks.values() if b["production_id"] == production_id])


def blocks_of_location(location_id):
    return store.by_seq([b for b in store.shoot_blocks.values() if b["location_id"] == location_id])


def releases_of_block(block_id):
    return store.by_seq([r for r in store.releases.values() if r["shoot_block_id"] == block_id])


# -------------------------------------------------------------------- rollups
def recompute_stipend_committed(production):
    total = 0
    for agreement in store.agreements.values():
        if agreement["production_id"] == production["id"] and agreement["status"] == "EXECUTED":
            total += agreement["total_stipend_commitment_cents"]
    production["stipend_committed_cents"] = total
    return total


def recompute_minor_participant_count(production):
    count = 0
    for agreement in store.agreements.values():
        if agreement["production_id"] != production["id"] or agreement["status"] != "EXECUTED":
            continue
        applicant = store.applicants.get(agreement["applicant_id"])
        if applicant is not None and applicant["is_minor"]:
            count += 1
    production["minor_participant_count"] = count
    return count


def recompute_trust_escrow(production):
    applicant_ids = {
        a["applicant_id"] for a in store.agreements.values() if a["production_id"] == production["id"]
    }
    total = 0
    for packet in store.minor_protections.values():
        if packet["applicant_id"] in applicant_ids and packet["status"] in (
            "INCOMPLETE",
            "COMPLETE",
            "LAPSED",
        ):
            total += packet["trust_deposited_cents"]
    production["trust_escrow_balance_cents"] = total
    return total


def recompute_breached_obligation_count(production):
    agreement_ids = {
        a["id"] for a in store.agreements.values() if a["production_id"] == production["id"]
    }
    count = 0
    for obligation in store.post_obligations.values():
        if obligation["agreement_id"] in agreement_ids and obligation["status"] == "BREACHED":
            count += 1
    production["breached_obligation_count"] = count
    return count


def protocol_subtotal(production, extra_cost=0):
    total = 0
    for protocol in store.welfare_protocols.values():
        if protocol["production_id"] == production["id"] and protocol["status"] in ("PLANNED", "ACTIVE"):
            total += protocol["cost_cents"]
    return total + extra_cost


def welfare_committed_preview(production, extra_cost=0):
    return calc.welfare_committed(protocol_subtotal(production, extra_cost), production["duty_of_care_tier"])


def recompute_welfare_committed(production):
    value = welfare_committed_preview(production)
    production["welfare_committed_cents"] = value
    return value


def recompute_welfare_incident_count(production):
    agreement_ids = {
        a["id"] for a in store.agreements.values() if a["production_id"] == production["id"]
    }
    count = 0
    for complaint in store.complaints.values():
        if (
            complaint["agreement_id"] in agreement_ids
            and complaint["status"] == "ESCALATED"
            and complaint["duty_of_care_breach"]
        ):
            count += 1
    production["welfare_incident_count"] = count
    return count


# -------------------------------------------------------------------- posture
def recompute_posture(production):
    """Re-derive casting_posture and fire the retrospective cascades of §2.7."""
    previous = production["casting_posture"]
    derived = calc.derive_casting_posture(production)
    if derived == previous:
        return derived
    production["casting_posture"] = derived
    touch(production)
    if derived == "RESTRICTED":
        cascade_restricted(production)
    elif derived == "FROZEN":
        cascade_frozen(production)
    return derived


def cascade_restricted(production):
    for call in calls_of_production(production["id"]):
        if call["status"] == "PUBLISHED" and call["channel"] == "OPEN_CALL":
            call["status"] = "CLOSED"
            call["closed_reason"] = "POSTURE_RESTRICTED"
            touch(call)


def cascade_frozen(production):
    for call in calls_of_production(production["id"]):
        if call["status"] == "PUBLISHED":
            call["status"] = "CLOSED"
            call["closed_reason"] = "POSTURE_FROZEN"
            touch(call)
    for block in blocks_of_production(production["id"]):
        if block["status"] == "SCHEDULED":
            block["status"] = "CANCELLED"
            touch(block)
    for agreement in agreements_of_production(production["id"]):
        if agreement["status"] in NEGOTIABLE_AGREEMENT and not agreement["welfare_hold"]:
            agreement["welfare_hold"] = True
            touch(agreement)


# ------------------------------------------------------------------ screening
def four_eyes_screening_guard(applicant_id, kind, user_id):
    """Rung 19 — the four-eyes screening rule of §2.10."""
    if kind == "PSYCH_EVAL":
        counterpart = "BACKGROUND_CHECK"
    elif kind == "BACKGROUND_CHECK":
        counterpart = "PSYCH_EVAL"
    else:
        return
    for item in items_of_applicant(applicant_id):
        if item["kind"] == counterpart and item["recorded_by_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")


def expiry_for_kind(kind, recorded_at_iso):
    days = calc.VALIDITY_DAYS_BY_KIND.get(kind)
    if days is None:
        return None
    return format_dt(add_days(parse_iso(recorded_at_iso), days))


def record_outcome_on_item(item, outcome, severity_flags, conditional_conditions, user_id):
    item["outcome"] = outcome
    item["severity_flags"] = severity_flags
    if conditional_conditions is not None:
        item["conditional_conditions"] = conditional_conditions
    item["recorded_by_user_id"] = user_id
    item["recorded_at"] = clock.now_iso()
    item["expires_at"] = expiry_for_kind(item["kind"], item["recorded_at"])


def apply_medical_dimension(applicant, item, recorded_now):
    if item["kind"] != "MEDICAL_EXAM":
        return
    if not recorded_now:
        if applicant["medical_status"] == "NOT_STARTED":
            applicant["medical_status"] = "PENDING"
        return
    if item["outcome"] == "PASS":
        applicant["medical_status"] = "CLEARED"
    elif item["outcome"] == "CONDITIONAL" and applicant["medical_status"] in ("NOT_STARTED", "PENDING"):
        applicant["medical_status"] = "DEFERRED"


def refresh_risk_scores(applicant):
    """Writes provisional_risk_score always; final_risk_score only once every
    required kind has a recorded item.  Returns the final score or None."""
    items = items_of_applicant(applicant["id"])
    applicant["provisional_risk_score"] = float(calc.provisional_ceiling_score(items))
    required = calc.required_kinds(applicant["psych_eval_required"])
    recorded = [i for i in items if i["recorded_at"] is not None]
    recorded_kinds = {i["kind"] for i in recorded}
    if not required.issubset(recorded_kinds):
        return None
    ordered = sorted(
        recorded,
        key=lambda i: (parse_iso(i["recorded_at"]), i["_seq"]),
        reverse=True,
    )
    final = calc.final_decayed_score(ordered)
    applicant["final_risk_score"] = float(final)
    applicant["enhanced_support_required"] = final >= calc.RISK_ENHANCED_SUPPORT_THRESHOLD
    return final


def apply_screening_dimension(applicant, item, recorded_now):
    final = refresh_risk_scores(applicant)
    if applicant["screening_status"] != "SCREENING":
        return
    items = items_of_applicant(applicant["id"])
    required = calc.required_kinds(applicant["psych_eval_required"])
    recorded_kinds = {i["kind"] for i in items if i["recorded_at"] is not None}
    all_required_recorded = required.issubset(recorded_kinds)
    any_fail = any(i["outcome"] == "FAIL" for i in items)

    if recorded_now and item["outcome"] == "FAIL":
        applicant["screening_status"] = "REJECTED"
        return
    if all_required_recorded and final is not None and final >= calc.RISK_REJECT_THRESHOLD:
        applicant["screening_status"] = "REJECTED"
        return
    if any_fail:
        applicant["screening_status"] = "REJECTED"
        return
    passing_kinds = {
        i["kind"] for i in items if i["outcome"] in ("PASS", "CONDITIONAL")
    }
    if (
        required.issubset(passing_kinds)
        and final is not None
        and final < calc.RISK_REJECT_THRESHOLD
    ):
        applicant["screening_status"] = "CLEARED"
        call = store.casting_calls.get(applicant["casting_call_id"])
        if call is not None:
            call["screened_pass_count"] = call["screened_pass_count"] + 1
            touch(call)


def apply_screening_write(applicant, item, recorded_now):
    if applicant["screening_status"] == "SUBMITTED":
        applicant["screening_status"] = "SCREENING"
    apply_medical_dimension(applicant, item, recorded_now)
    apply_screening_dimension(applicant, item, recorded_now)
    touch(applicant)


def latest_recorded_item(applicant_id, kind):
    candidates = [
        i
        for i in items_of_applicant(applicant_id)
        if i["kind"] == kind and i["recorded_at"] is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda i: (parse_iso(i["recorded_at"]), i["_seq"]))


def has_valid_psych_eval(applicant):
    now = clock.now()
    for item in items_of_applicant(applicant["id"]):
        if item["kind"] != "PSYCH_EVAL":
            continue
        if item["outcome"] not in ("PASS", "CONDITIONAL"):
            continue
        if item["expires_at"] is None or parse_iso(item["expires_at"]) > now:
            return True
    return False


# ----------------------------------------------------------- minor protections
def derive_packet_status(packet, production):
    """COMPLETE when the permit is unexpired and both jurisdiction minimums
    are met, else INCOMPLETE."""
    if parse_date(packet["permit_expires_on"]) <= clock.today():
        return "INCOMPLETE"
    minimum_hours = calc.MIN_EDUCATION_HOURS_BY_JURISDICTION[production["jurisdiction_code"]]
    if packet["education_hours_scheduled_weekly"] < minimum_hours:
        return "INCOMPLETE"
    minimum_pct = calc.MIN_TRUST_PCT_BY_JURISDICTION[production["jurisdiction_code"]]
    if calc.dec(packet["trust_deposit_pct"]) < minimum_pct:
        return "INCOMPLETE"
    return "COMPLETE"


def complete_packets_of(applicant_id):
    return [p for p in packets_of_applicant(applicant_id) if p["status"] == "COMPLETE"]


def unexpired_permit_packet(applicant_id, statuses=None):
    today = clock.today()
    for packet in packets_of_applicant(applicant_id):
        if statuses is not None and packet["status"] not in statuses:
            continue
        if parse_date(packet["permit_expires_on"]) > today:
            return packet
    return None


def education_packet_for(applicant_id):
    packets = packets_of_applicant(applicant_id)
    for packet in packets:
        if packet["status"] == "COMPLETE":
            return packet
    for packet in packets:
        if packet["status"] != "RELEASED":
            return packet
    return packets[-1] if packets else None


def release_packets_of_applicant(applicant_id):
    released = False
    for packet in packets_of_applicant(applicant_id):
        if packet["status"] != "RELEASED":
            packet["status"] = "RELEASED"
            packet["trust_deposited_cents"] = 0
            packet["per_installment_cents"] = 0
            touch(packet)
            released = True
    return released


# --------------------------------------------------------------- obligations
def create_post_obligations(agreement, production):
    """post_obligation_fee_allocation: every PRESS_JUNKET by ascending
    ordinal, then the single REUNION_TAPING row."""
    end = parse_iso(production["photography_end_utc"])
    created = []
    for ordinal in range(1, agreement["press_appearance_obligation_count"] + 1):
        record = store.new_record(
            "post_obligation",
            {
                "agreement_id": agreement["id"],
                "kind": "PRESS_JUNKET",
                "sequence_ordinal": ordinal,
                "due_utc": format_dt(end + timedelta(days=calc.PRESS_SPACING_DAYS * ordinal)),
                "fee_cents": calc.PRESS_APPEARANCE_RATE_CENTS,
                "status": "SCHEDULED",
                "fulfilled_at": None,
            },
        )
        store.post_obligations[record["id"]] = record
        created.append(record)
    if agreement["reunion_obligation"]:
        record = store.new_record(
            "post_obligation",
            {
                "agreement_id": agreement["id"],
                "kind": "REUNION_TAPING",
                "sequence_ordinal": 1,
                "due_utc": format_dt(end + timedelta(days=calc.REUNION_OFFSET_DAYS)),
                "fee_cents": calc.REUNION_FLAT_CENTS,
                "status": "SCHEDULED",
                "fulfilled_at": None,
            },
        )
        store.post_obligations[record["id"]] = record
        created.append(record)
    return created


def excuse_scheduled_obligations(agreement):
    for obligation in obligations_of_agreement(agreement["id"]):
        if obligation["status"] == "SCHEDULED":
            obligation["status"] = "EXCUSED"
            touch(obligation)


# ---------------------------------------------------------------- agreements
def void_agreement(agreement, reason):
    """Shared VOIDED transition.  Returns the affected production."""
    prior = agreement["status"]
    agreement["status"] = "VOIDED"
    agreement["void_reason"] = reason
    touch(agreement)
    production = production_of_agreement(agreement)
    if prior == "EXECUTED":
        agreement["total_stipend_commitment_cents"] = 0
        excuse_scheduled_obligations(agreement)
        release_packets_of_applicant(agreement["applicant_id"])
        if production is not None:
            recompute_stipend_committed(production)
            recompute_minor_participant_count(production)
            recompute_trust_escrow(production)
            touch(production)
    return production


def executed_agreement_of_applicant(applicant_id):
    live = [a for a in agreements_of_applicant(applicant_id) if a["status"] != "VOIDED"]
    for agreement in live:
        if agreement["status"] == "EXECUTED":
            return agreement
    return None


# ------------------------------------------------------------------- releases
def recompute_release_coverage(block):
    covered = 0
    minors_signed = True
    for release in releases_of_block(block["id"]):
        if release["disposition"] in ("COLLECTED", "BLURRED_WAIVER"):
            covered += release["head_count"]
        if release["subject_kind"] == "MINOR_INCIDENTAL" and not release["guardian_signature"]:
            minors_signed = False
    block["covered_head_count"] = covered
    block["release_coverage_complete"] = covered >= block["expected_crowd_headcount"] and minors_signed
    return block["release_coverage_complete"]


# -------------------------------------------------------------- welfare epoch
def welfare_run(production):
    """The operator-driven welfare epoch sweep of §3.7, in pinned order."""
    now = clock.now()
    today = clock.today()

    # 1. ACTIVE protocols whose coverage is over become EXPIRED.
    for protocol in protocols_of_production(production["id"]):
        if protocol["status"] == "ACTIVE" and parse_iso(protocol["coverage_end_utc"]) <= now:
            protocol["status"] = "EXPIRED"
            touch(protocol)

    # 2. COMPLETE packets with a lapsed permit become LAPSED and hold their
    #    applicant's live agreements.
    applicant_ids = {a["id"] for a in applicants_of_production(production["id"])}
    for packet in store.by_seq(list(store.minor_protections.values())):
        if packet["applicant_id"] not in applicant_ids:
            continue
        if packet["status"] != "COMPLETE":
            continue
        if parse_date(packet["permit_expires_on"]) <= today:
            packet["status"] = "LAPSED"
            touch(packet)
            for agreement in agreements_of_applicant(packet["applicant_id"]):
                if agreement["status"] in ("SENT", "COUNTERED", "REVISED", "EXECUTED"):
                    if not agreement["welfare_hold"]:
                        agreement["welfare_hold"] = True
                        touch(agreement)

    # 3. Medical clearances whose latest MEDICAL_EXAM has expired.
    for applicant in applicants_of_production(production["id"]):
        if applicant["medical_status"] != "CLEARED":
            continue
        latest = latest_recorded_item(applicant["id"], "MEDICAL_EXAM")
        if latest is None or latest["expires_at"] is None:
            continue
        if parse_iso(latest["expires_at"]) <= now:
            applicant["medical_status"] = "EXPIRED"
            touch(applicant)

    # 4. Overdue SCHEDULED obligations become BREACHED.
    breached_agreements = set()
    for agreement in agreements_of_production(production["id"]):
        for obligation in obligations_of_agreement(agreement["id"]):
            if obligation["status"] == "SCHEDULED" and parse_iso(obligation["due_utc"]) <= now:
                obligation["status"] = "BREACHED"
                touch(obligation)
                breached_agreements.add(agreement["id"])
    if breached_agreements:
        recompute_breached_obligation_count(production)
        for agreement_id in breached_agreements:
            agreement = store.agreements.get(agreement_id)
            if agreement is None:
                continue
            breaches = sum(
                1
                for o in obligations_of_agreement(agreement_id)
                if o["status"] == "BREACHED"
            )
            if breaches >= 2 and not agreement["welfare_hold"]:
                agreement["welfare_hold"] = True
                touch(agreement)

    # 5. Recompute committed welfare and re-derive the posture.
    recompute_welfare_committed(production)
    touch(production)
    recompute_posture(production)
    return production
