"""Lookups, lazy expiry sweeps, derived fields and serializers.

PRD 2.6: expiry is lazy -- evaluated at the start of the next request that
reads or writes the affected row (or its parent).
PRD 2.7: derived fields are re-derived from their inputs on every read/write
of the owning resource; LogisticsOrder.cost_cents and the RiskScreening
snapshots/scores are the pinned exceptions.
"""

from decimal import Decimal

import calc
from errors import ApiError
from store import base_row, db, fmt_dt, ordered, parse_dt, touch
from validate import AVOIDABLE_DELAY_CODES


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------
def _find(table, key, err):
    row = table.get(key)
    if row is None:
        raise ApiError(err, "%s does not resolve" % err)
    return row


def get_payer(pid):
    return _find(db.payers, pid, "ERR_PAYER_NOT_FOUND")


def get_patient(pid):
    return _find(db.patients, pid, "ERR_PATIENT_NOT_FOUND")


def get_provider(pid):
    return _find(db.providers, pid, "ERR_PROVIDER_NOT_FOUND")


def get_contract(cid):
    return _find(db.contracts, cid, "ERR_NETWORK_CONTRACT_NOT_FOUND")


def get_vehicle(vid):
    return _find(db.vehicles, vid, "ERR_VEHICLE_NOT_FOUND")


def get_episode(eid):
    return _find(db.episodes, eid, "ERR_EPISODE_NOT_FOUND")


def get_screening(sid):
    return _find(db.screenings, sid, "ERR_SCREENING_NOT_FOUND")


def get_barrier(bid):
    return _find(db.barriers, bid, "ERR_BARRIER_NOT_FOUND")


def get_referral(rid):
    return _find(db.referrals, rid, "ERR_REFERRAL_NOT_FOUND")


def get_offer(oid):
    return _find(db.offers, oid, "ERR_BED_OFFER_NOT_FOUND")


def get_authorization(aid):
    return _find(db.authorizations, aid, "ERR_AUTHORIZATION_NOT_FOUND")


def get_order(oid):
    return _find(db.orders, oid, "ERR_LOGISTICS_ORDER_NOT_FOUND")


# --------------------------------------------------------------------------
# child collections
# --------------------------------------------------------------------------
def barriers_of(episode_id):
    return ordered([b for b in db.barriers.values() if b["episode_id"] == episode_id])


def screenings_of(episode_id):
    return ordered([s for s in db.screenings.values() if s["episode_id"] == episode_id])


def referrals_of(episode_id):
    return ordered([r for r in db.referrals.values() if r["episode_id"] == episode_id])


def offers_of(referral_id):
    return ordered([o for o in db.offers.values() if o["referral_id"] == referral_id])


def offers_by_provider(provider_id):
    return ordered([o for o in db.offers.values() if o["provider_id"] == provider_id])


def authorizations_of(episode_id):
    return ordered([a for a in db.authorizations.values() if a["episode_id"] == episode_id])


def orders_of(episode_id):
    return ordered([o for o in db.orders.values() if o["episode_id"] == episode_id])


def contract_for(payer_id, provider_id):
    for c in db.contracts.values():
        if c["payer_id"] == payer_id and c["provider_id"] == provider_id:
            return c
    return None


def episode_payer(episode):
    patient = db.patients.get(episode["patient_id"])
    if patient is None:
        return None
    return db.payers.get(patient["primary_payer_id"])


# --------------------------------------------------------------------------
# barrier creation (used by manual creates and by every auto-derivation)
# --------------------------------------------------------------------------
def make_barrier(episode, barrier_code, severity, delay_reason_code, origin,
                 opened_by_user_id):
    row = base_row()
    row.update({
        "episode_id": episode["id"],
        "barrier_code": barrier_code,
        "severity": severity,
        "delay_reason_code": delay_reason_code,
        "status": "OPEN",
        "clock_start_at": db.now_iso(),
        "clock_stop_at": None,
        "reopen_count": 0,
        "opened_by_user_id": opened_by_user_id,
        "origin": origin,
        "_accrued_closed": 0,
    })
    db.barriers[row["id"]] = row
    return row


def has_open_barrier(episode_id, barrier_code):
    for b in db.barriers.values():
        if (b["episode_id"] == episode_id and b["barrier_code"] == barrier_code
                and b["status"] in ("OPEN", "MITIGATING")):
            return True
    return False


def close_barrier(barrier, status):
    """RESOLVED / WAIVED: stop the clock and accumulate the closed interval."""
    start = parse_dt(barrier["clock_start_at"])
    now = db.now()
    if start is not None and now > start:
        barrier["_accrued_closed"] = barrier.get("_accrued_closed", 0) + int(
            (now - start).total_seconds() // 60)
    barrier["clock_stop_at"] = db.now_iso()
    barrier["status"] = status
    touch(barrier)


# --------------------------------------------------------------------------
# lazy sweeps (PRD 2.6)
# --------------------------------------------------------------------------
def sweep_offer(offer):
    if offer["status"] != "OFFERED":
        return
    expires = parse_dt(offer["hold_expires_at"])
    if expires is not None and db.now() >= expires:
        offer["status"] = "EXPIRED"
        touch(offer)


def sweep_referral(referral):
    for offer in offers_of(referral["id"]):
        sweep_offer(offer)
    if referral["status"] != "BROADCAST":
        return
    needed_by = parse_dt(referral["needed_by"])
    if needed_by is None or db.now() < needed_by:
        return
    outstanding = [o for o in offers_of(referral["id"])
                   if o["round_index"] == referral["round_index"] and o["status"] == "OFFERED"]
    if outstanding:
        return
    referral["status"] = "EXPIRED"
    touch(referral)
    episode = db.episodes.get(referral["episode_id"])
    if episode is not None and not has_open_barrier(episode["id"], "BED_AVAILABILITY"):
        make_barrier(episode, "BED_AVAILABILITY", "HIGH", "AWAITING_BED",
                     "REVERT_AUTO", "system")


def sweep_authorization(auth):
    if auth["status"] not in ("APPROVED", "PARTIALLY_APPROVED"):
        return
    expires = parse_dt(auth.get("expires_at"))
    if expires is not None and db.now() >= expires:
        auth["status"] = "EXPIRED"
        touch(auth)


def sweep_provider(provider):
    for offer in offers_by_provider(provider["id"]):
        sweep_offer(offer)


def sweep_episode(episode):
    """A request that reads or writes an episode performs three sweeps first:
    bed-offer hold expiry, authorization expiry, referral needed-by expiry."""
    for referral in referrals_of(episode["id"]):
        for offer in offers_of(referral["id"]):
            sweep_offer(offer)
    for auth in authorizations_of(episode["id"]):
        sweep_authorization(auth)
    for referral in referrals_of(episode["id"]):
        sweep_referral(referral)


# --------------------------------------------------------------------------
# derived episode fields
# --------------------------------------------------------------------------
def barrier_posture(episode):
    open_set = [b for b in barriers_of(episode["id"]) if b["status"] in ("OPEN", "MITIGATING")]
    if not open_set:
        return "CLEAR"
    now = db.now()
    for b in open_set:
        if b["severity"] == "CRITICAL":
            return "ESCALATED"
        start = parse_dt(b["clock_start_at"])
        if start is not None:
            hours = int((now - start).total_seconds() // 3600)
            if hours >= calc.ESCALATION_HOURS:
                return "ESCALATED"
    return "ACTIVE"


def avoidable_delay_hours(episode):
    now = db.now()
    intervals = []
    for b in barriers_of(episode["id"]):
        if b["delay_reason_code"] not in AVOIDABLE_DELAY_CODES:
            continue
        if b["status"] == "WAIVED":
            continue
        start = parse_dt(b["clock_start_at"])
        end = parse_dt(b["clock_stop_at"]) if b.get("clock_stop_at") else now
        if start is None or end is None or end <= start:
            continue
        intervals.append((start, end))
    minutes = calc.union_minutes(intervals)
    return calc.one_dp(Decimal(minutes) / Decimal(60))


def barriers_ever_opened_count(episode):
    return len(barriers_of(episode["id"]))


def has_institutional_placement(episode):
    for r in referrals_of(episode["id"]):
        if r["status"] == "PLACED" and r["requested_level_of_care"] in ("SNF", "IRF", "LTACH"):
            return True
    return False


def latest_submitted_screening(episode):
    submitted = [s for s in screenings_of(episode["id"]) if s["status"] == "SUBMITTED"]
    return submitted[-1] if submitted else None


def episode_risk(episode):
    """Step 1 of the throughput procedure -- also the episode's live risk view.

    PREDISCHARGE_VARIANT once the episode has ever reached READY_FOR_DISCHARGE,
    otherwise the variant of the most recent SUBMITTED screening.
    """
    screening = latest_submitted_screening(episode)
    if episode.get("_ever_ready"):
        variant = "PREDISCHARGE_VARIANT"
    elif screening is not None:
        variant = screening.get("variant_applied") or "ADMISSION_VARIANT"
    else:
        variant = "ADMISSION_VARIANT"
    if screening is None:
        return 0, "LOW", variant
    score, band = calc.composite_risk(
        screening, variant,
        barriers_ever_opened_count(episode),
        has_institutional_placement(episode),
    )
    return score, band, variant


def logistics_committed_cents(episode):
    return sum(o["cost_cents"] for o in orders_of(episode["id"])
               if o["status"] in ("CONFIRMED", "COMPLETED"))


def authorized_days_total(episode):
    total = 0
    for a in authorizations_of(episode["id"]):
        if a["status"] in ("APPROVED", "PARTIALLY_APPROVED") and a.get("approved_days"):
            total += a["approved_days"]
    return total


def throughput_metrics(episode):
    score, band, variant = episode_risk(episode)
    avoidable = avoidable_delay_hours(episode)
    admitted = parse_dt(episode["admitted_at"])
    end = parse_dt(episode.get("discharged_at")) if episode.get("discharged_at") else db.now()
    minutes = 0
    if admitted is not None and end is not None and end > admitted:
        minutes = int((end - admitted).total_seconds() // 60)
    los = calc.one_dp(Decimal(minutes) / Decimal(60))
    adjusted = calc.one_dp(Decimal(str(los)) - Decimal(str(avoidable)))
    if adjusted < 0:
        adjusted = 0.0
    multiplier = calc.ACUITY_MULTIPLIER.get(band, Decimal("1.00"))
    expected = calc.one_dp(Decimal(str(episode["drg_gmlos_days"])) * Decimal(24) * multiplier)
    if expected > 0:
        ratio = calc.three_dp(Decimal(str(adjusted)) / Decimal(str(expected)))
    else:
        ratio = 0.0
    return {
        "current_risk_score": score,
        "current_risk_band": band,
        "risk_variant_applied": variant,
        "avoidable_delay_hours": avoidable,
        "los_hours": los,
        "adjusted_los_hours": adjusted,
        "expected_los_hours": expected,
        "observed_expected_ratio": ratio,
        "throughput_grade": calc.throughput_grade(ratio),
    }


# --------------------------------------------------------------------------
# derived bed-offer fields
# --------------------------------------------------------------------------
def offer_context(offer):
    referral = db.referrals.get(offer["referral_id"])
    episode = db.episodes.get(referral["episode_id"]) if referral else None
    payer = episode_payer(episode) if episode else None
    provider = db.providers.get(offer["provider_id"])
    contract = contract_for(payer["id"], offer["provider_id"]) if payer else None
    return referral, episode, payer, provider, contract


def offer_derived(offer):
    referral, episode, payer, provider, contract = offer_context(offer)
    out = {
        "rank_score": 0,
        "rate_variant_applied": "BILLED_RATE",
        "projected_gross_cents": 0,
        "projected_patient_share_cents": 0,
        "projected_plan_share_cents": 0,
    }
    if provider is not None:
        in_network = bool(contract is not None and contract.get("in_network"))
        out["rank_score"] = calc.rank_score(provider, offer["daily_rate_cents"], in_network)
    if referral is not None and payer is not None:
        out.update(calc.placement_projection(
            contract, offer["daily_rate_cents"],
            referral["projected_stay_days"], payer["coinsurance_pct"]))
    return out


def recommended_offer_id(referral):
    now = db.now()
    eligible = []
    for o in offers_of(referral["id"]):
        if o["round_index"] != referral["round_index"]:
            continue
        if o["status"] != "OFFERED":
            continue
        expires = parse_dt(o["hold_expires_at"])
        if expires is None or now >= expires:
            continue
        provider = db.providers.get(o["provider_id"])
        if provider is None or provider["status"] != "ACTIVE":
            continue
        eligible.append(o)
    if not eligible:
        return None
    def sort_key(o):
        return (-offer_derived(o)["rank_score"], o["daily_rate_cents"],
                o["created_at"], o["_seq"])
    eligible.sort(key=sort_key)
    return eligible[0]["id"]


# --------------------------------------------------------------------------
# serializers
# --------------------------------------------------------------------------
def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_payer(row):
    out = _common(row)
    for f in ("name", "snf_auth_required", "hh_auth_required", "coinsurance_pct",
              "auth_expiry_days"):
        out[f] = row[f]
    return out


def ser_patient(row):
    out = _common(row)
    for f in ("mrn", "full_name", "date_of_birth", "primary_payer_id",
              "prior_admissions_180d", "lives_alone", "has_pcp"):
        out[f] = row[f]
    return out


def ser_provider(row):
    out = _common(row)
    for f in ("name", "provider_type", "quality_star_rating",
              "distance_miles_from_hospital", "bed_unit_codes", "status"):
        out[f] = row[f]
    offers = offers_by_provider(row["id"])
    submitted = len(offers)
    accepted = len([o for o in offers if o["status"] == "ACCEPTED_BY_PATIENT"])
    held = len([o for o in offers if o["status"] in ("OFFERED", "ACCEPTED_BY_PATIENT")])
    out["held_bed_units"] = held
    out["offers_received_count"] = row.get("offers_received_count", 0)
    out["offers_submitted_count"] = submitted
    out["offers_accepted_count"] = accepted
    if submitted == 0:
        out["acceptance_rate_pct"] = 0.0
    else:
        out["acceptance_rate_pct"] = calc.one_dp(
            Decimal(accepted) * Decimal(100) / Decimal(submitted))
    return out


def ser_contract(row):
    out = _common(row)
    for f in ("payer_id", "provider_id", "in_network", "negotiated_daily_rate_cents"):
        out[f] = row[f]
    return out


def ser_vehicle(row):
    out = _common(row)
    for f in ("operator_name", "vehicle_type", "base_rate_cents", "per_mile_cents", "status"):
        out[f] = row[f]
    return out


def ser_episode(row):
    out = _common(row)
    for f in ("patient_id", "admission_type", "drg_code", "drg_gmlos_days",
              "attending_unit", "admitted_at", "assigned_case_manager_id",
              "case_status", "discharge_disposition", "pcp_followup_booked",
              "med_reconciliation_completed", "tcm_call_scheduled",
              "home_monitoring_enrolled", "marked_ready_by_user_id",
              "marked_ready_at", "discharged_at"):
        out[f] = row[f]
    metrics = throughput_metrics(row)
    out["barrier_posture"] = barrier_posture(row)
    out["current_risk_score"] = metrics["current_risk_score"]
    out["current_risk_band"] = metrics["current_risk_band"]
    out["risk_variant_applied"] = metrics["risk_variant_applied"]
    out["barriers_ever_opened_count"] = barriers_ever_opened_count(row)
    out["readmission_bundle_complete"] = calc.bundle_complete(row, metrics["current_risk_band"])
    out["logistics_committed_cents"] = logistics_committed_cents(row)
    out["authorized_days_total"] = authorized_days_total(row)
    out["avoidable_delay_hours"] = metrics["avoidable_delay_hours"]
    out["los_hours"] = metrics["los_hours"]
    out["adjusted_los_hours"] = metrics["adjusted_los_hours"]
    out["expected_los_hours"] = metrics["expected_los_hours"]
    out["observed_expected_ratio"] = metrics["observed_expected_ratio"]
    out["throughput_grade"] = metrics["throughput_grade"]
    return out


def ser_screening(row):
    out = _common(row)
    for f in ("episode_id", "screening_type", "functional_score", "cognitive_score",
              "social_support_score", "medication_count", "prior_admissions_snapshot",
              "lives_alone_snapshot", "has_pcp_snapshot", "variant_applied",
              "composite_risk_score", "risk_band", "status", "submitted_at",
              "submitted_by_user_id"):
        out[f] = row[f]
    return out


def ser_barrier(row):
    out = _common(row)
    for f in ("episode_id", "barrier_code", "severity", "delay_reason_code",
              "status", "clock_start_at", "clock_stop_at", "reopen_count",
              "opened_by_user_id", "origin"):
        out[f] = row[f]
    out["avoidable"] = row["delay_reason_code"] in AVOIDABLE_DELAY_CODES
    accrued = row.get("_accrued_closed", 0)
    if row["status"] in ("OPEN", "MITIGATING"):
        start = parse_dt(row["clock_start_at"])
        now = db.now()
        if start is not None and now > start:
            accrued += int((now - start).total_seconds() // 60)
    out["accrued_delay_minutes"] = accrued
    return out


def ser_referral(row):
    out = _common(row)
    for f in ("episode_id", "requested_level_of_care", "projected_stay_days",
              "needed_by", "round_index", "broadcast_provider_ids", "status",
              "chosen_bed_offer_id", "choice_basis", "patient_choice_attested"):
        out[f] = row[f]
    out["recommended_bed_offer_id"] = recommended_offer_id(row)
    return out


def ser_offer(row):
    out = _common(row)
    for f in ("referral_id", "provider_id", "round_index", "bed_unit_code",
              "bed_available_from", "hold_expires_at", "daily_rate_cents", "status"):
        out[f] = row[f]
    out.update(offer_derived(row))
    return out


def ser_authorization(row):
    out = _common(row)
    for f in ("episode_id", "payer_id", "provider_id", "level_of_care",
              "requested_days", "billed_daily_rate_cents", "approved_days",
              "appeal_round", "status", "denial_reason", "decided_at", "expires_at",
              "rate_variant_applied", "gross_projection_cents",
              "volume_discount_pct", "authorized_amount_cents"):
        out[f] = row[f]
    return out


def ser_order(row):
    out = _common(row)
    for f in ("episode_id", "order_type", "vehicle_id", "supplier_provider_id",
              "destination_provider_id", "item_code", "mileage_miles",
              "window_start", "window_end", "cost_cents", "status", "cancel_reason"):
        out[f] = row[f]
    return out
