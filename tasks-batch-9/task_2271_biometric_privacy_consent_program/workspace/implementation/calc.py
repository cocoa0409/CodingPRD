"""The five normative calculations (PRD 2.10, 3.2, 3.5, 3.8, 3.9)."""

from decimal import Decimal, ROUND_HALF_UP

import constants as K
from store import add_days, db, ordered


def rhu(value, places):
    """Round half up to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


# --- calculations.effective_retention_and_destruction -----------------------

def effective_retention_and_destruction(asset):
    """Returns the destruction_due_at instant (or None)."""
    if asset.get("pinned_policy_id") is None or asset.get("collection_started_at") is None:
        return None
    policy = db.policies.get(asset["pinned_policy_id"])
    juris = db.jurisdictions.get(asset["jurisdiction_id"])
    if policy is None or juris is None:
        return None
    effective_days = min(int(policy["retention_days"]), int(juris["retention_max_days"]))
    horizon = add_days(asset["collection_started_at"], effective_days)
    purpose_branch = (
        policy["destruction_trigger"] == "PURPOSE_SATISFIED_OR_MAX"
        and asset["retention_basis"] == "PURPOSE_LIMITED"
        and asset.get("purpose_satisfied_at") is not None
    )
    if purpose_branch:
        graced = add_days(asset["purpose_satisfied_at"], K.PURPOSE_GRACE_DAYS)
        return graced if graced < horizon else horizon
    return horizon


def refresh_destruction_due_at(asset):
    asset["destruction_due_at"] = effective_retention_and_destruction(asset)
    return asset["destruction_due_at"]


# --- calculations.vendor_risk_score ----------------------------------------

def vendor_risk_score(vendor):
    raw = K.RISK_BASE
    if vendor["sells_biometric_data"]:
        raw += K.RISK_SELLS_POINTS
    raw += K.RISK_SUBPROCESSOR_POINTS * min(
        int(vendor["subprocessor_count"]), K.RISK_SUBPROCESSOR_CAP
    )
    if int(vendor["deletion_sla_days"]) > K.RISK_SLA_TARGET_DAYS:
        raw += K.RISK_SLA_POINTS
    raw += K.RISK_ATTESTATION_POINTS[vendor["attestation_status"]]
    if not vendor["subprocessor_disclosure_complete"]:
        raw += K.RISK_DISCLOSURE_GAP_POINTS
    return max(0, min(100, raw))


def refresh_vendor_risk_score(vendor):
    vendor["risk_score"] = vendor_risk_score(vendor)
    return vendor["risk_score"]


# --- calculations.vendor_contract_compliance_score -------------------------

def vendor_contract_compliance_score(contract, vendor):
    factor = K.ATTESTATION_FACTOR[vendor["attestation_status"]]
    clause_values = (
        K.W_PROHIBITS_SALE if contract["prohibits_sale"] else Decimal("0"),
        K.W_RESTRICTS_DISCLOSURE if contract["restricts_disclosure"] else Decimal("0"),
        K.W_DELETION_ON_TERM if contract["requires_deletion_on_termination"] else Decimal("0"),
        K.W_DELETION_SLA
        if int(contract["deletion_deadline_days"]) <= K.DELETION_DEADLINE_TARGET_DAYS
        else Decimal("0"),
    )
    # PINNED ROUNDING ORDER: round EACH clause to 2dp, THEN sum.
    clause_points = Decimal("0")
    for clause_value in clause_values:
        clause_points += rhu(clause_value * Decimal("100") * factor, 2)
    adjusted = clause_points
    if vendor["sells_biometric_data"]:
        adjusted -= K.SELL_PENALTY_POINTS
    adjusted -= K.SUBPROCESSOR_PENALTY_POINTS * min(
        int(vendor["subprocessor_count"]), K.SUBPROCESSOR_PENALTY_CAP
    )
    clamped = max(Decimal("0"), min(Decimal("100"), adjusted))
    return rhu(clamped, 2)


def refresh_contract_compliance_score(contract):
    vendor = db.vendors.get(contract["vendor_id"])
    if vendor is None:
        return contract.get("compliance_score")
    contract["compliance_score"] = vendor_contract_compliance_score(contract, vendor)
    return contract["compliance_score"]


# --- calculations.incident_notification_deadline_and_cost ------------------

def incident_notification_deadline_and_cost(incident):
    affected = [db.assets[a] for a in incident["affected_asset_ids"] if a in db.assets]

    tier_1 = any(a["modality"] in ("FACE_GEOMETRY", "IRIS") for a in affected) or (
        int(incident["exposed_subject_count"]) >= K.TIER1_SUBJECT_THRESHOLD
    )
    tier = "TIER_1" if tier_1 else "TIER_2"
    deadline_days = K.TIER1_DEADLINE_DAYS if tier == "TIER_1" else K.TIER2_DEADLINE_DAYS
    notification_due_at = add_days(incident["discovered_at"], deadline_days)

    gross = int(incident["exposed_subject_count"]) * K.NOTICE_UNIT_CENTS + int(
        incident["translation_locale_count"]
    ) * K.TRANSLATION_UNIT_CENTS

    if gross < K.SURCHARGE_MID_FLOOR_CENTS:
        surcharge = 0
    elif gross < K.SURCHARGE_HIGH_FLOOR_CENTS:
        surcharge = K.SURCHARGE_MID_CENTS
    else:
        surcharge = K.SURCHARGE_HIGH_CENTS

    vendor_ids = set()
    for asset in affected:
        if asset.get("vendor_id") is not None:
            vendor_ids.add(asset["vendor_id"])
    indemnity_pool = 0
    for contract in db.contracts.values():
        if contract["status"] == "EXECUTED" and contract["vendor_id"] in vendor_ids:
            indemnity_pool += int(contract["indemnity_cap_cents"])

    # Half of the PRE-SURCHARGE gross, TRUNCATED toward zero.
    ceiling = int((K.INDEMNITY_CREDIT_PCT * Decimal(gross)).to_integral_value(rounding="ROUND_DOWN"))
    credit = min(indemnity_pool, ceiling)

    net = gross + surcharge - credit

    return {
        "heightened_tier": tier,
        "notification_due_at": notification_due_at,
        "gross_notice_cents": gross,
        "regulator_surcharge_cents": surcharge,
        "vendor_indemnity_credit_cents": credit,
        "net_incident_cost_cents": net,
    }


# --- calculations.pra_exposure_estimate ------------------------------------

def pra_exposure_estimate(program_id, jurisdiction_id, variant):
    juris = db.jurisdictions.get(jurisdiction_id)
    scope_assets = [
        a
        for a in db.assets.values()
        if a["program_id"] == program_id
        and a["jurisdiction_id"] == jurisdiction_id
        and a["status"] in ("ACTIVE", "GATED")
    ]
    scope_asset_ids = set(a["id"] for a in scope_assets)

    consents = ordered([c for c in db.consents.values() if c["asset_id"] in scope_asset_ids])

    negligent_rows = [c for c in consents if c["status"] in ("SOLICITED", "RESOLICIT_REQUIRED", "EXPIRED")]

    def subject_has_live_accommodation(subject_id):
        for acc in db.accommodations.values():
            if acc["data_subject_id"] == subject_id and acc["status"] in ("PROVISIONED", "ACTIVE"):
                return True
        return False

    reckless_rows = [
        c
        for c in consents
        if c["status"] == "REVOKED" and not subject_has_live_accommodation(c["data_subject_id"])
    ]

    negligent_unit_count = len(negligent_rows)
    reckless_unit_count = len(reckless_rows)

    pra_factor = K.PRA_FACTOR[juris["private_right_of_action"]]

    gap = any(int(a.get("consent_gap_count") or 0) > 0 for a in scope_assets)
    notice_gap_multiplier = K.NOTICE_GAP_MULTIPLIER if gap else Decimal("1.00")

    cure_available = int(juris["cure_period_days"]) >= 1 and any(
        p["program_id"] == program_id
        and p["status"] == "PUBLISHED"
        and jurisdiction_id in p["jurisdiction_scope"]
        for p in db.policies.values()
    )
    cure_credit_pct = K.CURE_CREDIT_PCT if cure_available else Decimal("0.00")

    negligent_cents = int(juris["per_violation_negligent_cents"])
    reckless_cents = int(juris["per_violation_reckless_cents"])

    # step 1: statutory base, variant specific
    if juris["damages_model"] == "ACTUAL_ONLY":
        base_cents = 0
    elif variant == "PER_VIOLATION_STACKED":
        base_cents = negligent_unit_count * negligent_cents + reckless_unit_count * reckless_cents
    else:  # PER_SUBJECT_CAPPED
        per_subject = {}
        order = []
        for row in ordered(negligent_rows + reckless_rows):
            sid = row["data_subject_id"]
            if sid not in per_subject:
                per_subject[sid] = 0
                order.append(sid)
            if row["status"] == "REVOKED":
                per_subject[sid] += reckless_cents
            else:
                per_subject[sid] += negligent_cents
        base_cents = 0
        for sid in order:
            base_cents += min(per_subject[sid], K.PER_SUBJECT_CAP_CENTS)

    # steps 2-4: the three factors, no intermediate rounding
    raw = (
        Decimal(base_cents)
        * pra_factor
        * notice_gap_multiplier
        * (Decimal("1") - cure_credit_pct)
    )
    # step 5: exactly one rounding of the fully multiplied product, then the cap
    capped = int(rhu(raw, 0))
    statutory_cap = juris.get("statutory_cap_cents")
    if statutory_cap is not None:
        exposure_cents = min(capped, int(statutory_cap))
    else:
        exposure_cents = capped

    return {
        "negligent_unit_count": negligent_unit_count,
        "reckless_unit_count": reckless_unit_count,
        "base_cents": base_cents,
        "notice_gap_multiplier": notice_gap_multiplier,
        "cure_credit_pct": cure_credit_pct,
        "exposure_cents": exposure_cents,
    }


# --- calculations.inventory_completeness_pct -------------------------------

def inventory_completeness_pct(program_id):
    scope = [
        a
        for a in db.assets.values()
        if a["program_id"] == program_id and a["status"] != "DECOMMISSIONED"
    ]
    if len(scope) == 0:
        return Decimal("100.00")
    documented = 0
    for asset in scope:
        if asset["status"] not in ("CLASSIFIED", "ACTIVE", "GATED"):
            continue
        if asset["template_storage_location"] == "":
            continue
        if asset.get("vendor_id") is not None:
            has_executed = any(
                c["vendor_id"] == asset["vendor_id"] and c["status"] == "EXECUTED"
                for c in db.contracts.values()
            )
            if not has_executed:
                continue
        documented += 1
    return rhu(Decimal(100) * Decimal(documented) / Decimal(len(scope)), 2)
