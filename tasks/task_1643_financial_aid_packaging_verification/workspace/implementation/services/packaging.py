"""Packaging waterfall, snapshots, repack, over-award detection, needs_repack.

PRD 3.6 pins the waterfall's five-step evaluation order; PRD 3.8 pins the
status-dependent counted total for over-award detection.
"""
from db import db
from errors import raise_error, ERR_FUND_POOL_EXHAUSTED
from services.calc import pell_offer, sub_cap, unsub_cap
from services.core import (
    current_isir, latest_verification_case, package_for, counted_external_aid,
    new_record, touch, recompute_package_totals, recompute_aggregates,
)

# Package statuses whose counted total for over-award detection is the OFFERED
# total (PRD 3.8); all later statuses count the ACCEPTED total.
OFFERED_COUNTED_STATUSES = {"DRAFT", "PACKAGED", "NOTIFIED", "REVISION_REQUESTED"}
# Packages in these statuses observe needs_repack when the official EFC or the
# COA deltas drift from the frozen snapshots (PRD 3.4/3.5/3.6).
REPACK_FLAG_STATUSES = {"NOTIFIED", "PARTIALLY_ACCEPTED", "ACCEPTED"}


def approved_pj_cases(student_id, aid_year_id):
    return [c for c in db.pj_cases.values()
            if c["student_id"] == student_id and c["aid_year_id"] == aid_year_id
            and c["status"] == "APPROVED"]


def compute_snapshots(student, aid_year, isir):
    """coa_used / efc_used / need from current inputs (PRD 3.6 step 1).

    An approved EFC adjustment carries a non-positive delta that lowers the EFC:
    efc_used = max(0, efc_official + sum(applied_efc_delta_cents)). (The PJ
    approval precondition — the delta must leave efc_official at zero or above
    once applied — pins the additive reading.)
    """
    pjs = approved_pj_cases(student["id"], aid_year["id"])
    coa_delta = sum(c["applied_coa_delta_cents"] for c in pjs)
    efc_delta = sum(c["applied_efc_delta_cents"] for c in pjs)
    if student["residency"] == "IN_STATE":
        coa_used = aid_year["coa_in_state_cents"] + coa_delta
    else:
        coa_used = aid_year["coa_out_of_state_cents"] + coa_delta
    efc_used = max(0, isir["efc_official_cents"] + efc_delta)
    need = max(0, coa_used - efc_used)
    return coa_used, efc_used, need


def verification_satisfied(student_id, aid_year_id):
    """Waterfall step 3b: no case at all, or the case is COMPLETED_SATISFIED /
    WAIVED."""
    case = latest_verification_case(student_id, aid_year_id)
    if case is None:
        return True
    return case["status"] in ("COMPLETED_SATISFIED", "WAIVED")


def run_waterfall(student, aid_year, isir, released):
    """Evaluate the pinned waterfall. `released` maps fund_id -> reserved amount
    of this package's own existing counted lines, notionally released before the
    pool check (repack semantics: the old lines are being replaced).

    Returns (offers, gift_aid) where offers is a list of (fund, offer) in
    evaluation order. Pure: mutates nothing.
    """
    coa_used, efc_used, need = compute_snapshots(student, aid_year, isir)
    remaining_need = need
    remaining_gap = coa_used
    gift = 0
    offers = []

    funds = [f for f in db.fund_types.values()
             if f["aid_year_id"] == aid_year["id"] and f["status"] == "ACTIVE"]
    funds.sort(key=lambda f: (f["packaging_rank"], f["fund_code"]))

    for fund in funds:
        # 3a. priority cohort restriction.
        if fund["priority_cohort_only"] and isir["cohort"] != "PRIORITY":
            continue
        # 3b. verification-complete restriction.
        if fund["requires_verification_complete"] and not verification_satisfied(
                student["id"], aid_year["id"]):
            continue
        # 3c. base offer.
        code = fund["fund_code"]
        if code == "PELL":
            base = pell_offer(aid_year["pell_schedule"], efc_used,
                              student["enrollment_status"])
        elif code == "SUB":
            base = min(sub_cap(student["grade_level"], student["dependency_status"]),
                       remaining_need)
        elif code == "UNSUB":
            base = min(unsub_cap(student["grade_level"], student["dependency_status"]),
                       remaining_gap)
        else:
            running = remaining_need if fund["need_based"] else remaining_gap
            base = min(fund["annual_cap_cents"], running)
        # 3d. pool check for every fund except PELL. A zero budget means the
        # fund has no pool constraint at all.
        offer = base
        if code != "PELL" and fund["pool_budget_cents"] > 0:
            headroom = fund["pool_budget_cents"] - (
                fund["pool_reserved_cents"] - released.get(fund["id"], 0))
            offer = min(base, headroom)
            if offer <= 0:
                continue
        if offer <= 0:
            continue
        offers.append((fund, offer))
        # 4. accumulators, updated after each fund's offer is fixed.
        if fund["need_based"]:
            remaining_need = max(0, remaining_need - offer)
        remaining_gap = max(0, remaining_gap - offer)
        if fund["need_based"] and code not in ("SUB", "UNSUB", "PLUS"):
            gift += offer
    return (coa_used, efc_used, need), offers, gift


def build_package(pkg, student, aid_year, isir):
    """DRAFT -> PACKAGED: run the waterfall and create child lines (PRD 3.6)."""
    (coa_used, efc_used, need), offers, gift = run_waterfall(student, aid_year, isir, {})
    pkg["coa_used_cents"] = coa_used
    pkg["efc_used_cents"] = efc_used
    pkg["need_cents"] = need
    seq = 0
    for fund, offer in offers:
        seq += 1
        new_record("award_lines", {
            "package_id": pkg["id"],
            "fund_type_id": fund["id"],
            "offered_cents": offer,
            "accepted_cents": 0,
            "disbursed_cents": 0,
            "status": "OFFERED",
            "sequence_number": seq,
        })
    pkg["status"] = "PACKAGED"
    touch(pkg)
    recompute_package_totals(pkg)  # no-op touch if already consistent
    recompute_aggregates(aid_year["id"])
    run_overaward_detection(student["id"], aid_year["id"])
    return pkg


def repack_package(pkg, student, aid_year):
    """Revision-approved repack: re-run the waterfall against current inputs,
    adjusting existing OFFERED lines, creating new ones, and cancelling lines
    whose fund is no longer offered (PRD 3.6 revision rules).

    Rung 15: the repack may not push any non-PELL fund's pool_reserved_cents
    above its pool_budget_cents — checked before anything mutates.
    """
    isir = current_isir(student["id"], aid_year["id"])
    if isir is None:
        # Defensive: a package that built once always had a current ISIR.
        from errors import ERR_PREREQUISITE_MISSING
        raise_error(ERR_PREREQUISITE_MISSING, "no current ISIR record for repack")

    old_lines = [l for l in db.award_lines.values()
                 if l["package_id"] == pkg["id"] and l["status"] == "OFFERED"]
    old_by_fund = {l["fund_type_id"]: l for l in old_lines}
    released = {l["fund_type_id"]: l["offered_cents"] for l in old_lines}

    (coa_used, efc_used, need), offers, gift = run_waterfall(
        student, aid_year, isir, released)

    # Rung 15 — pool sufficiency on repack (non-PELL, budgeted funds only).
    for fund, offer in offers:
        if fund["fund_code"] == "PELL" or fund["pool_budget_cents"] <= 0:
            continue
        prospective = (fund["pool_reserved_cents"] - released.get(fund["id"], 0)) + offer
        if prospective > fund["pool_budget_cents"]:
            raise_error(ERR_FUND_POOL_EXHAUSTED,
                        f"repack would push fund {fund['fund_code']} reserved pool "
                        f"above its budget")

    pkg["coa_used_cents"] = coa_used
    pkg["efc_used_cents"] = efc_used
    pkg["need_cents"] = need

    offered_funds = {fund["id"] for fund, _ in offers}
    max_seq = 0
    for l in db.award_lines.values():
        if l["package_id"] == pkg["id"]:
            max_seq = max(max_seq, l["sequence_number"])
    for fund, offer in offers:
        line = old_by_fund.get(fund["id"])
        if line is not None:
            if line["offered_cents"] != offer:
                line["offered_cents"] = offer
                touch(line)
        else:
            max_seq += 1
            new_record("award_lines", {
                "package_id": pkg["id"],
                "fund_type_id": fund["id"],
                "offered_cents": offer,
                "accepted_cents": 0,
                "disbursed_cents": 0,
                "status": "OFFERED",
                "sequence_number": max_seq,
            })
    for line in old_lines:
        if line["fund_type_id"] not in offered_funds:
            line["status"] = "CANCELLED"
            touch(line)

    pkg["needs_repack"] = False  # the flag clears when the repack executes
    recompute_package_totals(pkg)
    recompute_aggregates(aid_year["id"])
    return pkg


def maybe_mark_needs_repack(student_id, aid_year_id):
    """PRD 3.4/3.5/3.6: when the official EFC or the COA deltas drift from a
    package's frozen snapshots while it sits in NOTIFIED / PARTIALLY_ACCEPTED /
    ACCEPTED, set needs_repack. Existing lines are deliberately left untouched."""
    pkg = package_for(student_id, aid_year_id)
    if pkg is None or pkg["status"] not in REPACK_FLAG_STATUSES:
        return
    student = db.students.get(student_id)
    aid_year = db.aid_years.get(aid_year_id)
    isir = current_isir(student_id, aid_year_id)
    if student is None or aid_year is None or isir is None:
        return
    coa_used, efc_used, _need = compute_snapshots(student, aid_year, isir)
    if coa_used != pkg["coa_used_cents"] or efc_used != pkg["efc_used_cents"]:
        if not pkg["needs_repack"]:
            pkg["needs_repack"] = True
            touch(pkg)


def run_overaward_detection(student_id, aid_year_id):
    """PRD 3.8: counted total pinned by package status; open a case when the
    overage is strictly positive and none is already OPEN/RESOLVING. There is
    no automatic close."""
    pkg = package_for(student_id, aid_year_id)
    if pkg is None:
        return None
    if pkg["status"] in OFFERED_COUNTED_STATUSES:
        counted = pkg["total_offered_cents"]
    else:
        counted = pkg["total_accepted_cents"]
    total_aid = counted + counted_external_aid(student_id, aid_year_id)
    overage = total_aid - pkg["coa_used_cents"]
    if overage > 0:
        for case in db.overaward_cases.values():
            if (case["student_id"] == student_id and case["aid_year_id"] == aid_year_id
                    and case["status"] in ("OPEN", "RESOLVING")):
                return None
        return new_record("overaward_cases", {
            "student_id": student_id,
            "aid_year_id": aid_year_id,
            "detected_total_aid_cents": total_aid,
            "overage_cents": overage,
            "status": "OPEN",
            "resolution_plan": None,
            "_plan_snapshot": None,
        })
    return None


def overaward_gate_blocks_acceptance(pkg):
    """Rung 16: an OPEN/RESOLVING case blocks acceptance while the
    offered-total-based detection still exceeds the cost of attendance."""
    open_case = None
    for case in db.overaward_cases.values():
        if (case["student_id"] == pkg["student_id"]
                and case["aid_year_id"] == pkg["aid_year_id"]
                and case["status"] in ("OPEN", "RESOLVING")):
            open_case = case
            break
    if open_case is None:
        return False
    total_aid = pkg["total_offered_cents"] + counted_external_aid(
        pkg["student_id"], pkg["aid_year_id"])
    return total_aid > pkg["coa_used_cents"]
