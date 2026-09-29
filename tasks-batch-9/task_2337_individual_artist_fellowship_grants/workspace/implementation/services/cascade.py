"""System cascades (PRD sections 2.5, 2.6, 3.4-3.11).

Each cascade runs to completion inside the request that triggered it, and each
compensating cascade recomputes derived state from its sources so the values it
restores are exactly the values that preceded the operation it compensates.
"""

import db
import constants as C
from services import calc, derive

set_fields = derive.set_fields


def now_iso():
    return db.iso3(db.now())


# ---------------------------------------------------------------- reviews


def invalidate_reviews(reviews, reason):
    """Move SUBMITTED reviews to INVALIDATED; return affected application ids."""
    affected = []
    for review in reviews:
        if review["status"] == "SUBMITTED":
            set_fields(review, status="INVALIDATED", invalidation_reason=reason)
            if review["application_id"] not in affected:
                affected.append(review["application_id"])
    return affected


def recompute_applications(application_ids, include_final=False, include_spread=True):
    for application_id in application_ids:
        application = db.get("applications", application_id)
        if application is not None:
            derive.refresh_application_scores(
                application,
                include_final=include_final,
                include_spread=include_spread,
            )


# --------------------------------------------------------------- anonymity


def breach_application(application):
    """The FLAGGED_IDENTIFYING cascade."""
    if application is None:
        return
    set_fields(application, anonymity_status="BREACHED")
    invalidate_reviews(
        derive.reviews_of_application(application["id"]), "ANONYMITY_BREACH"
    )
    derive.refresh_application_scores(application)
    void_proposed_slots(application)
    derive.refresh_panel_by_id(application.get("assigned_panel_id"))
    derive.refresh_cycle_by_id(application["cycle_id"])


def clear_breach_if_resolved(application):
    """The redaction cascade: BREACHED -> REDACTED once no FLAGGED sample remains."""
    if application is None:
        return
    remaining = [
        s
        for s in db.rows(
            "work_samples", lambda r, a=application["id"]: r["application_id"] == a
        )
        if s["status"] == "FLAGGED"
    ]
    if not remaining and application["anonymity_status"] == "BREACHED":
        set_fields(application, anonymity_status="REDACTED")
    derive.refresh_cycle_by_id(application["cycle_id"])


def void_proposed_slots(application):
    for slot in derive.slots_of_application(application["id"]):
        if slot["status"] != "PROPOSED":
            continue
        set_fields(slot, status="VOIDED", awarded_amount_cents=0)
        panel = db.get("panels", slot["panel_id"])
        cycle = db.get("cycles", slot["cycle_id"])
        if panel is not None and cycle is not None:
            if panel["round_number"] < cycle["max_review_rounds"]:
                set_fields(panel, reopen_required=True)


# --------------------------------------------------------------- conflicts


def apply_block(conflict, officer_id):
    """Screening a conflict BLOCKING."""
    panelist = db.get("panelists", conflict["panelist_id"])
    application = db.get("applications", conflict["application_id"])
    set_fields(conflict, status="BLOCKING", screened_by=officer_id)

    if panelist is not None:
        recused = list(panelist.get("recused_application_ids") or [])
        if conflict["application_id"] not in recused:
            recused.append(conflict["application_id"])
        fields = {"recused_application_ids": recused}
        if panelist["status"] == "SEATED":
            fields["status"] = "RECUSED"
        set_fields(panelist, **fields)

    if panelist is not None and application is not None:
        mine = [
            r
            for r in derive.reviews_of_application(application["id"])
            if r["panelist_id"] == panelist["id"]
        ]
        invalidate_reviews(mine, "BLOCKING_CONFLICT")
        derive.refresh_application_scores(application)
        void_proposed_slots(application)

    if panelist is not None:
        derive.refresh_panel_by_id(panelist["panel_id"])
        panel = db.get("panels", panelist["panel_id"])
        if panel is not None:
            derive.refresh_cycle_by_id(panel["cycle_id"])


def release_block(conflict, officer_id, justification):
    """Overriding a BLOCKING conflict: restore every effect the block caused."""
    panelist = db.get("panelists", conflict["panelist_id"])
    application = db.get("applications", conflict["application_id"])
    set_fields(
        conflict,
        status="WAIVED",
        screened_by=officer_id,
        override_justification=justification,
    )

    if panelist is not None and application is not None:
        for review in derive.reviews_of_application(application["id"]):
            if (
                review["panelist_id"] == panelist["id"]
                and review["status"] == "INVALIDATED"
                and review["invalidation_reason"] == "BLOCKING_CONFLICT"
            ):
                set_fields(review, status="SUBMITTED", invalidation_reason=None)
        derive.refresh_application_scores(application)

    if panelist is not None:
        recused = [
            a
            for a in (panelist.get("recused_application_ids") or [])
            if a != conflict["application_id"]
        ]
        fields = {"recused_application_ids": recused}
        others = [
            c
            for c in db.rows(
                "conflicts", lambda r, p=panelist["id"]: r["panelist_id"] == p
            )
            if c["status"] == "BLOCKING"
        ]
        if not others and panelist["status"] == "RECUSED":
            fields["status"] = "SEATED"
        set_fields(panelist, **fields)
        derive.refresh_panel_by_id(panelist["panel_id"])
        panel = db.get("panels", panelist["panel_id"])
        if panel is not None:
            derive.refresh_cycle_by_id(panel["cycle_id"])


def resign_panelist(panelist):
    """Resignation: release the seat and invalidate the panelist's scoring."""
    previous = panelist["status"]
    set_fields(panelist, status="RESIGNED")
    affected = []
    if previous in C.OCCUPYING_PANELIST_STATUSES:
        mine = db.rows("reviews", lambda r, p=panelist["id"]: r["panelist_id"] == p)
        affected = invalidate_reviews(mine, "BLOCKING_CONFLICT")
        # §3.6 names only valid_review_count and provisional_composite_score for a
        # resignation; the empty-set invariant still nulls the spread when nothing counts.
        recompute_applications(affected, include_spread=False)
    derive.refresh_panel_by_id(panelist["panel_id"])
    panel = db.get("panels", panelist["panel_id"])
    if panel is not None:
        derive.refresh_cycle_by_id(panel["cycle_id"])


# ------------------------------------------------------------------ awards


def create_award(slot, cycle, application, amount_cents, is_prorated, board_member_id):
    deadline = db.plus_days(db.now(), int(cycle["acceptance_window_days"]))
    award = db.insert(
        "awards",
        {
            "application_id": application["id"],
            "artist_id": application["artist_id"],
            "cycle_id": cycle["id"],
            "recommendation_slot_id": slot["id"],
            "gross_amount_cents": amount_cents,
            "is_prorated": is_prorated,
            "acceptance_deadline_at": db.iso3(deadline),
            "grant_period_start": cycle["grant_period_start"],
            "grant_period_end": cycle["grant_period_end"],
            "accept_agreement_version": None,
            "tax_certification_signed": False,
            "status": "OFFERED",
            "payment_status": "UNPAID",
            "reporting_status": "NOT_DUE",
            "final_report_due_at": None,
            "scheduled_withholding_cents": 0,
            "total_withholding_cents": 0,
            "disbursed_gross_cents": 0,
            "disbursed_net_cents": 0,
            "undisbursed_gross_cents": 0,
            "approved_by_user_id": board_member_id,
            "rescind_reason_code": None,
        },
    )
    return award


def unwind_award(award, new_status, rescind_reason_code=None):
    """Decline, rescission and forfeiture share one compensating unwind."""
    application = db.get("applications", award["application_id"])
    slot = db.get("slots", award["recommendation_slot_id"])

    fields = {"status": new_status}
    if rescind_reason_code is not None:
        fields["rescind_reason_code"] = rescind_reason_code
    set_fields(award, **fields)

    for installment in derive.installments_of_award(award["id"]):
        if installment["status"] in ("SCHEDULED", "HELD"):
            set_fields(installment, status="VOIDED", hold_reason_code=None)
    derive.refresh_award_ledger(award)

    if application is not None and application["status"] in ("RECOMMENDED", "AWARDED"):
        set_fields(application, status="NOT_AWARDED", notified_at=now_iso())

    if slot is not None and slot["status"] in ("PROPOSED", "BOARD_APPROVED"):
        set_fields(slot, status="VOIDED", awarded_amount_cents=0)

    derive.refresh_artist_by_id(award["artist_id"])
    if application is not None:
        derive.refresh_discipline_by_id(application["discipline_category_id"])
    derive.refresh_cycle_by_id(award["cycle_id"])


def complete_award(award):
    """ACTIVE -> COMPLETED on an accepted final report, when fully paid."""
    if award["status"] != "ACTIVE" or award["payment_status"] != "FULLY_PAID":
        return False
    set_fields(award, status="COMPLETED")
    artist = db.get("artists", award["artist_id"])
    cycle = db.get("cycles", award["cycle_id"])
    if artist is not None:
        fields = {"prior_award_count": int(artist["prior_award_count"]) + 1}
        if cycle is not None:
            fields["last_award_fiscal_year"] = cycle["fiscal_year"]
        fields["last_award_period_end"] = award["grant_period_end"]
        set_fields(artist, **fields)
        derive.refresh_artist(artist)
    application = db.get("applications", award["application_id"])
    if application is not None:
        derive.refresh_discipline_by_id(application["discipline_category_id"])
    derive.refresh_cycle_by_id(award["cycle_id"])
    return True


def hold_scheduled_installments(artist, reason_code):
    """Debarment sweep: award created_at ASC, then installment_number ASC."""
    held = []
    for award in derive.awards_of_artist(artist["id"]):
        installments = sorted(
            derive.installments_of_award(award["id"]),
            key=lambda r: (r["installment_number"], r["_seq"]),
        )
        for installment in installments:
            if installment["status"] == "SCHEDULED":
                set_fields(installment, status="HELD", hold_reason_code=reason_code)
                held.append(installment["id"])
        derive.refresh_award_ledger(award)
    return held


def clear_report_delinquency(award):
    """A filed final report clears the delinquency hold."""
    was_delinquent = award["reporting_status"] == "DELINQUENT"
    if award["reporting_status"] in ("DUE", "DELINQUENT"):
        set_fields(award, reporting_status="RECEIVED")
    artist = db.get("artists", award["artist_id"])
    if was_delinquent:
        derive.refresh_artist(artist)
        debarred = artist is not None and artist["standing"] == "DEBARRED"
        if not debarred:
            for installment in derive.installments_of_award(award["id"]):
                if (
                    installment["status"] == "HELD"
                    and installment["hold_reason_code"] == "REPORT_DELINQUENT"
                ):
                    set_fields(installment, status="SCHEDULED", hold_reason_code=None)
        derive.refresh_award_ledger(award)


# ------------------------------------------------------------ appeal remedies


def remedy_reinstate_eligibility(application):
    if application is None or application["status"] != "INELIGIBLE":
        return
    set_fields(
        application,
        status="ELIGIBLE",
        ineligibility_reason_code=None,
        assigned_panel_id=None,
    )
    derive.refresh_discipline_by_id(application["discipline_category_id"])
    derive.refresh_cycle_by_id(application["cycle_id"])


def remedy_rescore_by_new_panel(application):
    if application is None:
        return
    panel = db.get("panels", application.get("assigned_panel_id"))
    invalidate_reviews(derive.reviews_of_application(application["id"]), "APPEAL_REMEDY")
    # The remedy is only ever reachable once the applicant has been notified, which
    # means the slate has already gone in: the application sits in NOT_RECOMMENDED and
    # its panel in SLATE_SUBMITTED.  The cascade is therefore applied unconditionally
    # -- the application returns to the pool as ELIGIBLE and the panel returns to
    # SCORING with its round incremented -- guarded only by the round ceiling, which
    # the caller reports as ERR_SCORE_SPREAD_REQUIRES_ANOTHER_ROUND.
    set_fields(application, status="ELIGIBLE", assigned_panel_id=None)
    derive.refresh_application_scores(application, include_final=True)
    if panel is not None:
        set_fields(
            panel,
            status="SCORING",
            round_number=int(panel["round_number"]) + 1,
            reopen_required=False,
        )
        derive.refresh_panel(panel)
    derive.refresh_discipline_by_id(application["discipline_category_id"])
    derive.refresh_cycle_by_id(application["cycle_id"])


def remedy_reissue_slate(application):
    if application is None:
        return
    for slot in derive.slots_of_application(application["id"]):
        if slot["status"] in ("VOIDED", "BOARD_STRUCK"):
            set_fields(
                slot, status="PROPOSED", board_action_by=None, struck_reason_code=None
            )
    if application["status"] == "NOT_RECOMMENDED":
        set_fields(application, status="SCORED")
    derive.refresh_cycle_by_id(application["cycle_id"])


# ------------------------------------------------------------ cycle cascades


def cycle_awarded(cycle):
    """Unseal, release the reserve and close out unrecommended applications."""
    for application in derive.applications_of_cycle(cycle["id"]):
        if application["anonymity_status"] in ("SEALED", "REDACTED"):
            set_fields(application, anonymity_status="UNSEALED")
    for application in derive.applications_of_cycle(cycle["id"]):
        if application["status"] != "SCORED":
            continue
        approved = [
            s
            for s in derive.slots_of_application(application["id"])
            if s["status"] == "BOARD_APPROVED"
        ]
        if not approved:
            set_fields(application, status="NOT_RECOMMENDED", notified_at=now_iso())


def cycle_cancelled(cycle):
    for application in derive.applications_of_cycle(cycle["id"]):
        if application["status"] in ("DRAFT", "SUBMITTED"):
            set_fields(application, status="WITHDRAWN")
            reject_open_samples(application)
    for discipline in db.rows(
        "disciplines", lambda r, c=cycle["id"]: r["cycle_id"] == c
    ):
        derive.refresh_discipline(discipline)


def cycle_closed_out(cycle):
    for panel in derive.panels_of_cycle(cycle["id"]):
        if panel["status"] != "DISSOLVED":
            set_fields(panel, status="DISSOLVED")


def reject_open_samples(application):
    for sample in db.rows(
        "work_samples", lambda r, a=application["id"]: r["application_id"] == a
    ):
        if sample["status"] in ("PENDING_SCREEN", "FLAGGED"):
            set_fields(sample, status="REJECTED")
    derive.refresh_work_sample_count(application)


# ------------------------------------------------------- operations checkpoint


def checkpoint():
    """Runs on every clock write, over awards in created_at ASC order."""
    forfeited = []
    delinquent = []
    held = []
    for award in db.rows("awards"):
        moment = db.now()

        if award["status"] == "OFFERED":
            deadline = db.dt_of(award, "acceptance_deadline_at")
            if deadline is not None and deadline < moment:
                unwind_award(award, "FORFEITED")
                forfeited.append(award["id"])
                continue

        if award["status"] in ("ACCEPTED", "ACTIVE") and award["reporting_status"] == "NOT_DUE":
            period_end = db.dt_of(award, "grant_period_end")
            if period_end is not None and period_end < moment:
                set_fields(award, reporting_status="DUE")

        if award["reporting_status"] == "DUE":
            due_at = db.dt_of(award, "final_report_due_at")
            if (
                due_at is not None
                and due_at < moment
                and derive.report_of_award(award["id"]) is None
            ):
                set_fields(award, reporting_status="DELINQUENT")
                delinquent.append(award["id"])
                for installment in sorted(
                    derive.installments_of_award(award["id"]),
                    key=lambda r: (r["installment_number"], r["_seq"]),
                ):
                    if installment["status"] == "SCHEDULED":
                        set_fields(
                            installment,
                            status="HELD",
                            hold_reason_code="REPORT_DELINQUENT",
                        )
                        held.append(installment["id"])
                derive.refresh_award_ledger(award)
                derive.refresh_artist_by_id(award["artist_id"])
    return forfeited, delinquent, held
