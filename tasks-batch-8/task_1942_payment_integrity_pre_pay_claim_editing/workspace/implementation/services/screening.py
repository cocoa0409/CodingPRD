"""Claim screening (run-edits) engine per PRD 3.4."""

from datetime import timedelta

import db
from services.calc import (
    DRG_WEIGHTS,
    HIGH_DOLLAR_THRESHOLD_CENTS,
    IBR_DOCUMENTS_DUE_DAYS,
    READMISSION_WINDOW_DAYS,
    drg_payment,
    whole_days,
)
from services import core


def run_edits(claim: dict) -> None:
    """Execute screening side effects. Preconditions already validated."""
    now = db.now()
    provider = db.get("providers", claim["provider_id"])
    lines = [l for l in db.all_records("claim_lines") if l["claim_id"] == claim["id"]]
    lines.sort(key=lambda l: l["line_number"])

    # --- Baseline allowed ---
    if claim["claim_type"] == "INSTITUTIONAL_INPATIENT":
        initial_allowed = drg_payment(
            claim["drg_code"],
            claim["admission_date"],
            claim["discharge_date"],
            claim["discharge_disposition"],
        )
    else:
        initial_allowed = claim["total_billed_cents"]
    claim["initial_allowed_cents"] = initial_allowed
    claim["allowed_amount_cents"] = initial_allowed
    claim["denied_amount_cents"] = 0

    # Initialize line allowed/denied
    for line in lines:
        line["allowed_cents"] = line["billed_cents"]
        line["denied_cents"] = 0
        db.touch(line)

    # --- High-dollar evaluation ---
    high_dollar = claim["total_billed_cents"] >= HIGH_DOLLAR_THRESHOLD_CENTS
    claim["high_dollar_flag"] = high_dollar
    auto_ibr = None
    if high_dollar:
        auto_ibr = db.create_resource(
            "ibrs",
            {
                "claim_id": claim["id"],
                "provider_id": claim["provider_id"],
                "status": "REQUESTED",
                "requested_at": now,
                "due_at": now + timedelta(days=IBR_DOCUMENTS_DUE_DAYS),
                "completed_at": None,
                "findings_cents": 0,
                "repriced_total_cents": None,
                "auditor_user_id": None,
            },
        )

    # --- Readmission detection (inpatient only) ---
    readmission_flag = False
    readmission_review = None
    if claim["claim_type"] == "INSTITUTIONAL_INPATIENT":
        candidates = []
        for other in db.all_records("claims"):
            if other["id"] == claim["id"]:
                continue
            if other["provider_id"] != claim["provider_id"]:
                continue
            if other["member_id"] != claim["member_id"]:
                continue
            if other["claim_type"] != "INSTITUTIONAL_INPATIENT":
                continue
            if other["status"] not in ("READY_TO_PAY", "DENIED", "PAID"):
                continue
            if other.get("discharge_date") is None:
                continue
            if other["discharge_date"] > claim["admission_date"]:
                continue
            candidates.append(other)
        # most-recent discharge first, ties broken by earliest creation
        candidates.sort(key=lambda c: (-c["discharge_date"].timestamp(), c["created_at"].timestamp()))
        if candidates:
            prior = candidates[0]
            gap_days = whole_days(claim["admission_date"], prior["discharge_date"])
            if 0 <= gap_days <= READMISSION_WINDOW_DAYS:
                readmission_flag = True
                readmission_review = db.create_resource(
                    "inpatient_reviews",
                    {
                        "claim_id": claim["id"],
                        "review_type": "READMISSION",
                        "status": "OPEN",
                        "provider_drg_code": claim["drg_code"],
                        "audited_drg_code": None,
                        "prior_claim_id": prior["id"],
                        "gap_days": gap_days,
                        "outcome": None,
                        "payment_delta_cents": 0,
                    },
                )
        # Every inpatient claim gets a DRG_VALIDATION review
        db.create_resource(
            "inpatient_reviews",
            {
                "claim_id": claim["id"],
                "review_type": "DRG_VALIDATION",
                "status": "OPEN",
                "provider_drg_code": claim["drg_code"],
                "audited_drg_code": None,
                "prior_claim_id": None,
                "gap_days": None,
                "outcome": None,
                "payment_delta_cents": 0,
            },
        )
    claim["readmission_flag"] = readmission_flag

    # --- Edit engine ---
    profile = None
    for p in db.all_records("abrasion_profiles"):
        if p["provider_id"] == claim["provider_id"]:
            profile = p
            break
    monitor_only = bool(profile and profile.get("tier") == "HIGH")

    any_applied_hit = False
    # Eligible ACTIVE edit versions for this claim type
    eligible_versions = []
    for v in db.all_records("edit_versions"):
        if v["status"] != "ACTIVE":
            continue
        if claim["claim_type"] not in v["applies_to_claim_types"]:
            continue
        eligible_versions.append(v)

    for line in lines:
        line_hits = []
        for version in eligible_versions:
            rule = db.get("edit_rules", version["edit_rule_id"])
            source = rule["source"] if rule is not None else "INTERNAL"
            vendor_edit_id = None
            if source == "VENDOR":
                # Find the vendor edit mapped to this rule (mirrored entry)
                for ve in db.all_records("vendor_edits"):
                    if ve.get("mapped_edit_rule_id") == version["edit_rule_id"]:
                        vendor_edit_id = ve["id"]
                        break
            # expected_savings: full line billed for DENY severity (PRD 3.4);
            # the engine does not quantify SUSPEND/MONITOR savings.
            expected = line["billed_cents"] if version["severity"] == "DENY" else 0
            hit = db.create_resource(
                "edit_hits",
                {
                    "claim_id": claim["id"],
                    "claim_line_id": line["id"],
                    "edit_version_id": version["id"],
                    "vendor_edit_id": vendor_edit_id,
                    "status": "FIRED",
                    "applied": not monitor_only,
                    "expected_savings_cents": expected,
                    "attributed_savings_cents": 0,
                    "released_cents": 0,
                    "confirmed_by_user_id": None,
                    "resolved_at": None,
                },
            )
            line_hits.append((hit, version, source))

        # Internal-first waterfall attribution
        applied_hits = [(h, v, s) for (h, v, s) in line_hits if h["applied"]]
        applied_hits.sort(
            key=lambda t: (
                0 if t[2] == "INTERNAL" else 1,
                t[1]["effective_from"],
                t[0]["created_at"],
            )
        )
        running = 0
        for hit, version, source in applied_hits:
            remaining = line["billed_cents"] - running
            if remaining < 0:
                remaining = 0
            attributed = min(hit["expected_savings_cents"], remaining)
            hit["attributed_savings_cents"] = attributed
            db.touch(hit)
            running += attributed

        # Move dollars for applied hits
        for hit, version, source in applied_hits:
            if hit["attributed_savings_cents"] > 0:
                amt = hit["attributed_savings_cents"]
                claim["allowed_amount_cents"] -= amt
                claim["denied_amount_cents"] += amt
                line["allowed_cents"] -= amt
                line["denied_cents"] += amt
                db.touch(line)

        # One review task per applied hit
        for hit, version, source in applied_hits:
            db.create_resource(
                "review_tasks",
                {
                    "claim_id": claim["id"],
                    "edit_hit_id": hit["id"],
                    "status": "PENDING",
                    "assigned_reviewer_user_id": None,
                    "requires_senior": False,
                    "outcome": None,
                    "decision_reason": "",
                },
            )
            any_applied_hit = True

    # Refresh abrasion profile to reflect any auto-created IBR (open_ibr_count)
    core.recompute_abrasion(claim["provider_id"])

    # --- Landing state ---
    any_review = False
    for rev in db.all_records("inpatient_reviews"):
        if rev["claim_id"] == claim["id"] and rev["status"] in core.OPEN_INPATIENT_STATUSES:
            any_review = True
            break

    if any_applied_hit or any_review or high_dollar:
        claim["status"] = "PENDED"
    else:
        claim["status"] = "READY_TO_PAY"
        claim["determined_at"] = now
    db.touch(claim)
