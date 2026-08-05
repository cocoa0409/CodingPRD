"""Serializers, computed aggregates, and the calculation rules (scaffold 1.3)."""
from store import S, dec, round_half_up, parse_dt

# ---- constants (scaffold 1.3) ----
HARD_TO_FILL_MULTIPLIER = dec("1.20")
TAX_GROSS_UP_FACTOR = dec("1.25")
W_SPECIALTY = 50
W_GEO = 30
W_LICENSE = 20
CANDIDATE_TRAVEL_BUFFER_MINUTES = 120

LIVE_PLACEMENT_STATUSES = {"PRE_START", "ACTIVE", "GUARANTEE_MET"}
OPEN_PIPELINE_STAGES = {"SOURCED", "SCREENED", "SUBMITTED", "INTERVIEWING", "OFFER_STAGE"}


# --------------------------------------------------------------------------
# computed aggregates (always derived live -> no ledger drift)
# --------------------------------------------------------------------------
def positions_filled(opening_id):
    return sum(
        1
        for p in S.placements.values()
        if p["opening_id"] == opening_id and p["placement_status"] in LIVE_PLACEMENT_STATUSES
    )


def net_placement_fee(client_id):
    recognized = sum(
        p["placement_fee_cents"]
        for p in S.placements.values()
        if p["client_id"] == client_id and p["fee_status"] in ("INVOICED", "PAID", "CREDITED")
    )
    credited = sum(
        c["credit_cents"]
        for c in S.guarantee_claims.values()
        if c["client_id"] == client_id
        and c["status"] in ("RESOLVED_REFUND", "RESOLVED_REPLACEMENT")
    )
    return recognized - credited


# --------------------------------------------------------------------------
# calculations
# --------------------------------------------------------------------------
def placement_fee(first_year_comp_cents, client, opening):
    multiplier = HARD_TO_FILL_MULTIPLIER if opening["is_hard_to_fill"] else dec("1.0")
    raw = round_half_up(dec(first_year_comp_cents) * dec(client["contingency_pct"]) * multiplier)
    return max(raw, client["min_fee_cents"])


def match_score(candidate, opening):
    s = 0
    if candidate["specialty"] == opening["specialty"]:
        s += W_SPECIALTY
    if candidate["home_region"] == opening["region"]:
        s += W_GEO
    if opening["region_state"] in candidate["license_states"]:
        s += W_LICENSE
    return s


def relocation_reimbursed(placement_id, cap_cents):
    total = 0
    for e in S.reloc_expenses.values():
        if e["placement_id"] != placement_id or e["status"] != "APPROVED":
            continue
        if e["is_taxable"]:
            total += round_half_up(dec(e["amount_cents"]) * TAX_GROSS_UP_FACTOR)
        else:
            total += e["amount_cents"]
    return min(total, cap_cents)


def guarantee_credit_refund(placement, client, days_worked):
    gd = client["guarantee_days"]
    unworked = dec(gd - days_worked) / dec(gd)
    if unworked < 0:
        unworked = dec(0)
    return round_half_up(dec(placement["placement_fee_cents"]) * unworked)


def guarantee_credit_replacement(placement, replacement_placement):
    return min(placement["placement_fee_cents"], replacement_placement["fee_estimate_cents"])


def open_pipeline_load(recruiter_id):
    return sum(
        1
        for a in S.applications.values()
        if a["recruiter_id"] == recruiter_id and a["stage"] in OPEN_PIPELINE_STAGES
    )


def credentialing_overall_status(file_id):
    """Derive a credentialing file's overall_status purely from its items."""
    items = [i for i in S.cred_items.values() if i["credentialing_file_id"] == file_id]
    if not items:
        return "NOT_STARTED"
    if any(i["status"] == "FLAGGED" for i in items):
        return "FLAGGED"
    any_active = any(i["status"] in ("SUBMITTED", "VERIFIED") for i in items)
    if not any_active:
        return "NOT_STARTED"
    required = [i for i in items if i["is_required"]]
    if all(i["status"] == "VERIFIED" for i in required):
        return "CLEARED"
    return "IN_PROGRESS"


# --------------------------------------------------------------------------
# serializers
# --------------------------------------------------------------------------
def _base(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def staff_user_dict(r):
    d = _base(r)
    d.update(
        role=r["role"],
        full_name=r["full_name"],
        email=r["email"],
        covered_specialties=r["covered_specialties"],
        status=r["status"],
    )
    return d


def client_dict(r):
    d = _base(r)
    d.update(
        name=r["name"],
        region=r["region"],
        account_manager_id=r["account_manager_id"],
        contingency_pct=r["contingency_pct"],
        min_fee_cents=r["min_fee_cents"],
        guarantee_days=r["guarantee_days"],
        status=r["status"],
        net_placement_fee_cents=net_placement_fee(r["id"]),
    )
    return d


def opening_dict(r):
    d = _base(r)
    d.update(
        client_id=r["client_id"],
        specialty=r["specialty"],
        region=r["region"],
        region_state=r["region_state"],
        comp_min_cents=r["comp_min_cents"],
        comp_max_cents=r["comp_max_cents"],
        is_hard_to_fill=r["is_hard_to_fill"],
        positions_total=r["positions_total"],
        positions_filled=positions_filled(r["id"]),
        recruiter_id=r["recruiter_id"],
        status=r["status"],
    )
    return d


def candidate_dict(r):
    d = _base(r)
    d.update(
        recruiter_id=r["recruiter_id"],
        full_name=r["full_name"],
        specialty=r["specialty"],
        home_region=r["home_region"],
        license_states=r["license_states"],
        desired_comp_cents=r["desired_comp_cents"],
        status=r["status"],
    )
    return d


def application_dict(r):
    d = _base(r)
    d.update(
        candidate_id=r["candidate_id"],
        opening_id=r["opening_id"],
        recruiter_id=r["recruiter_id"],
        match_score=r["match_score"],
        stage=r["stage"],
        reject_reason=r["reject_reason"],
    )
    return d


def site_visit_dict(r):
    d = _base(r)
    d.update(
        application_id=r["application_id"],
        interviewer_user_id=r["interviewer_user_id"],
        scheduled_start=r["scheduled_start"],
        scheduled_end=r["scheduled_end"],
        location=r["location"],
        status=r["status"],
    )
    return d


def offer_dict(r):
    d = _base(r)
    d.update(
        application_id=r["application_id"],
        base_salary_cents=r["base_salary_cents"],
        sign_on_bonus_cents=r["sign_on_bonus_cents"],
        start_date=r["start_date"],
        relocation_cap_cents=r["relocation_cap_cents"],
        expires_at=r["expires_at"],
        round_number=r["round_number"],
        extended_by_user_id=r["extended_by_user_id"],
        offered_first_year_comp_cents=r["offered_first_year_comp_cents"],
        status=r["status"],
    )
    return d


def placement_dict(r):
    d = _base(r)
    d.update(
        offer_id=r["offer_id"],
        application_id=r["application_id"],
        client_id=r["client_id"],
        candidate_id=r["candidate_id"],
        opening_id=r["opening_id"],
        start_date=r["start_date"],
        fee_estimate_cents=r["fee_estimate_cents"],
        final_first_year_comp_cents=r["final_first_year_comp_cents"],
        placement_fee_cents=r["placement_fee_cents"],
        relocation_cap_cents=r["relocation_cap_cents"],
        relocation_reimbursed_cents=r["relocation_reimbursed_cents"],
        relocation_status=r["relocation_status"],
        guarantee_end_date=r["guarantee_end_date"],
        placement_status=r["placement_status"],
        fee_status=r["fee_status"],
    )
    return d


def cred_file_dict(r):
    d = _base(r)
    d.update(
        placement_id=r["placement_id"],
        candidate_id=r["candidate_id"],
        overall_status=r["overall_status"],
    )
    return d


def cred_item_dict(r):
    d = _base(r)
    d.update(
        credentialing_file_id=r["credentialing_file_id"],
        item_type=r["item_type"],
        is_required=r["is_required"],
        status=r["status"],
    )
    return d


def reloc_expense_dict(r):
    d = _base(r)
    d.update(
        placement_id=r["placement_id"],
        category=r["category"],
        amount_cents=r["amount_cents"],
        is_taxable=r["is_taxable"],
        status=r["status"],
    )
    return d


def guarantee_claim_dict(r):
    d = _base(r)
    d.update(
        placement_id=r["placement_id"],
        client_id=r["client_id"],
        fell_out_date=r["fell_out_date"],
        reason=r["reason"],
        replacement_placement_id=r["replacement_placement_id"],
        days_worked=r["days_worked"],
        credit_cents=r["credit_cents"],
        status=r["status"],
    )
    return d
