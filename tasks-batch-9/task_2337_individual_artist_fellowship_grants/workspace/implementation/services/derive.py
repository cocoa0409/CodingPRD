"""Derived-field recomputation (PRD section 2.12).

Every derived field is recomputed from its sources rather than nudged, so a
compensating operation restores the exact value that preceded the operation it
compensates.  A recomputation that actually changes a value counts as a
mutation and therefore bumps the row's version (once per request).
"""

import db
import constants as C
from services import calc


def set_fields(row, **fields):
    """Write fields, bumping version/updated_at only when something changed."""
    changed = False
    for key, value in fields.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        db.mark(row)
    return changed


# ------------------------------------------------------------------ lookups


def cycle_of(row):
    return db.get("cycles", row.get("cycle_id"))


def discipline_of(row):
    return db.get("disciplines", row.get("discipline_category_id"))


def applications_of_cycle(cycle_id):
    return db.rows("applications", lambda r: r["cycle_id"] == cycle_id)


def applications_of_discipline(discipline_id):
    return db.rows("applications", lambda r: r["discipline_category_id"] == discipline_id)


def panels_of_cycle(cycle_id):
    return db.rows("panels", lambda r: r["cycle_id"] == cycle_id)


def panelists_of_panel(panel_id):
    return db.rows("panelists", lambda r: r["panel_id"] == panel_id)


def reviews_of_application(application_id):
    return db.rows("reviews", lambda r: r["application_id"] == application_id)


def installments_of_award(award_id):
    return db.rows("installments", lambda r: r["award_id"] == award_id)


def awards_of_cycle(cycle_id):
    return db.rows("awards", lambda r: r["cycle_id"] == cycle_id)


def awards_of_artist(artist_id):
    return db.rows("awards", lambda r: r["artist_id"] == artist_id)


def award_of_application(application_id):
    rows = db.rows("awards", lambda r: r["application_id"] == application_id)
    return rows[-1] if rows else None


def slots_of_application(application_id):
    return db.rows("slots", lambda r: r["application_id"] == application_id)


def report_of_award(award_id):
    rows = db.rows("final_reports", lambda r: r["award_id"] == award_id)
    return rows[-1] if rows else None


def conflict_for(panelist_id, application_id):
    for row in db.rows("conflicts", lambda r: r["panelist_id"] == panelist_id):
        if row["application_id"] == application_id:
            return row
    return None


def has_blocking_conflict(panelist_id, application_id):
    row = conflict_for(panelist_id, application_id)
    return bool(row) and row["status"] == "BLOCKING"


# ------------------------------------------------------------------- cycles


def refresh_cycle(cycle):
    """Recompute the cycle's counters, fiscal ledger and posture."""
    if cycle is None:
        return
    apps = applications_of_cycle(cycle["id"])
    breach_count = sum(1 for a in apps if a["anonymity_status"] == "BREACHED")

    panel_ids = {p["id"] for p in panels_of_cycle(cycle["id"])}
    blocking_count = 0
    for conflict in db.rows("conflicts", lambda r: r["status"] == "BLOCKING"):
        panelist = db.get("panelists", conflict["panelist_id"])
        if panelist is not None and panelist["panel_id"] in panel_ids:
            blocking_count += 1

    funded_total = sum(
        int(a["gross_amount_cents"])
        for a in awards_of_cycle(cycle["id"])
        if a["status"] in C.AWARD_FUNDED_STATUSES
    )
    rate, assessment = calc.admin_assessment(funded_total)
    reserve = calc.reserve_cents(cycle)
    committed, available, posture = calc.budget_posture(
        cycle, funded_total, assessment, reserve, breach_count, blocking_count
    )
    set_fields(
        cycle,
        unresolved_breach_count=breach_count,
        blocking_conflict_count=blocking_count,
        funded_total_cents=funded_total,
        admin_assessment_rate=rate,
        admin_assessment_cents=assessment,
        reserve_cents=reserve,
        committed_cents=committed,
        available_cents=available,
        posture=posture,
    )


def refresh_cycle_by_id(cycle_id):
    refresh_cycle(db.get("cycles", cycle_id))


# -------------------------------------------------------------- disciplines


def refresh_discipline(discipline):
    if discipline is None:
        return
    apps = applications_of_discipline(discipline["id"])
    eligible = sum(1 for a in apps if a["status"] in C.ELIGIBLE_POOL_STATUSES)
    funded = 0
    committed = 0
    for app in apps:
        for award in db.rows("awards", lambda r, i=app["id"]: r["application_id"] == i):
            if award["status"] in C.AWARD_FUNDED_STATUSES:
                funded += 1
                committed += int(award["gross_amount_cents"])
                break
    set_fields(
        discipline,
        eligible_application_count=eligible,
        funded_application_count=funded,
        committed_cents=committed,
    )


def refresh_discipline_by_id(discipline_id):
    refresh_discipline(db.get("disciplines", discipline_id))


# ------------------------------------------------------------------ artists


def refresh_artist(artist):
    if artist is None:
        return
    awards = awards_of_artist(artist["id"])
    active = sum(1 for a in awards if a["status"] in C.AWARD_ACTIVE_STATUSES)
    delinquent = sum(1 for a in awards if a["reporting_status"] == "DELINQUENT")
    fields = {"active_award_count": active, "delinquent_award_count": delinquent}
    if delinquent == 0 and artist["standing"] == "REPORT_DELINQUENT":
        fields["standing"] = "GOOD_STANDING"
    elif delinquent > 0 and artist["standing"] == "GOOD_STANDING":
        fields["standing"] = "REPORT_DELINQUENT"
    set_fields(artist, **fields)


def refresh_artist_by_id(artist_id):
    refresh_artist(db.get("artists", artist_id))


# ------------------------------------------------------------------- panels


def occupying(panel_id):
    """Panelists holding a seat: SEATED, plus RECUSED (recusal keeps the seat)."""
    return [
        p
        for p in panelists_of_panel(panel_id)
        if p["status"] in C.OCCUPYING_PANELIST_STATUSES
    ]


def refresh_panel(panel):
    if panel is None:
        return
    seats = occupying(panel["id"])
    seated_count = len(seats)
    required_regions = list(panel.get("required_regions") or [])
    covered = {p["region"] for p in seats}
    coverage = sum(1 for region in required_regions if region in covered)

    blocking = 0
    for panelist in panelists_of_panel(panel["id"]):
        for conflict in db.rows(
            "conflicts", lambda r, pid=panelist["id"]: r["panelist_id"] == pid
        ):
            if conflict["status"] == "BLOCKING":
                blocking += 1

    quorum_min = calc.quorum_min_reviews(panel["required_seats"])
    has_bonus = any(
        calc.BONUS_EXPERTISE in (p.get("expertise_codes") or []) for p in seats
    )
    readiness = calc.panel_readiness_score(
        seated_count,
        int(panel["required_seats"]),
        coverage,
        len(required_regions),
        blocking,
        has_bonus,
    )
    assigned = len(
        db.rows("applications", lambda r, pid=panel["id"]: r.get("assigned_panel_id") == pid)
    )
    set_fields(
        panel,
        seated_count=seated_count,
        region_coverage_count=coverage,
        blocking_conflict_count=blocking,
        quorum_min_reviews=quorum_min,
        quorum_met=seated_count >= quorum_min,
        readiness_score=readiness,
        assigned_application_count=assigned,
    )


def refresh_panel_by_id(panel_id):
    refresh_panel(db.get("panels", panel_id))


def refresh_panelist_counts(panelist):
    """review_submitted_count is maintained by the submit operation itself."""
    return panelist


# ------------------------------------------------------------- applications


def counted_reviews(application):
    """SUBMITTED reviews of the current panel round, created_at ascending."""
    panel_id = application.get("assigned_panel_id")
    panel = db.get("panels", panel_id) if panel_id else None
    if panel is None:
        return [], None
    round_number = panel["round_number"]
    counted = [
        r
        for r in reviews_of_application(application["id"])
        if r["status"] == "SUBMITTED" and r["round_number"] == round_number
    ]
    return counted, panel


def score_set(application):
    counted, panel = counted_reviews(application)
    seated = panel["seated_count"] if panel else 0
    provisional, final, spread = calc.composite_scores(
        [r["weighted_score"] for r in counted], seated
    )
    return len(counted), provisional, final, spread


def refresh_application_scores(application, include_final=False, include_spread=True):
    """Recompute valid_review_count, the provisional score and the spread.

    §3.7 lists exactly what a review submission recomputes -- the count and the
    provisional composite -- so `include_spread` is False on that path; every
    other lifecycle event (breach, blocking, override, close-round, reopen,
    appeal remedy) names `score_spread` explicitly.  `final_composite_score` is
    written once per round at close-round, but the empty-counted-set invariant
    ("all three ... are null") still forces it to null when nothing counts.
    """
    count, provisional, final, spread = score_set(application)
    fields = {
        "valid_review_count": count,
        "provisional_composite_score": provisional,
    }
    if include_spread or count == 0:
        fields["score_spread"] = spread
    if include_final:
        fields["final_composite_score"] = final
    elif count == 0:
        fields["final_composite_score"] = None
    set_fields(application, **fields)
    return count, provisional, final, spread


def refresh_work_sample_count(application):
    samples = db.rows(
        "work_samples", lambda r, a=application["id"]: r["application_id"] == a
    )
    counted = [s for s in samples if s["status"] in C.COUNTED_SAMPLE_STATUSES]
    set_fields(application, work_sample_count=len(counted))
    return counted


# ------------------------------------------------------------------- awards


def refresh_award_ledger(award):
    if award is None:
        return
    installments = installments_of_award(award["id"])
    live = [i for i in installments if i["status"] in C.INSTALLMENT_LIVE_STATUSES]
    paid = [i for i in installments if i["status"] == "PAID"]
    scheduled_withholding = sum(
        int(i["withholding_cents"])
        for i in installments
        if i["status"] in C.INSTALLMENT_UNDISBURSED_STATUSES
    )
    total_withholding = sum(int(i["withholding_cents"]) for i in live)
    disbursed_gross = sum(int(i["gross_cents"]) for i in paid)
    disbursed_net = sum(int(i["net_cents"]) for i in paid)
    undisbursed = sum(
        int(i["gross_cents"])
        for i in installments
        if i["status"] in C.INSTALLMENT_UNDISBURSED_STATUSES
    )
    # payment_status is judged over the non-VOIDED installments, per section 1.2.
    non_voided = [i for i in installments if i["status"] != "VOIDED"]
    if not paid:
        payment_status = "UNPAID"
    elif len(paid) == len(non_voided):
        payment_status = "FULLY_PAID"
    else:
        payment_status = "PARTIALLY_PAID"
    set_fields(
        award,
        scheduled_withholding_cents=scheduled_withholding,
        total_withholding_cents=total_withholding,
        disbursed_gross_cents=disbursed_gross,
        disbursed_net_cents=disbursed_net,
        undisbursed_gross_cents=undisbursed,
        payment_status=payment_status,
    )


def refresh_award_by_id(award_id):
    refresh_award_ledger(db.get("awards", award_id))
