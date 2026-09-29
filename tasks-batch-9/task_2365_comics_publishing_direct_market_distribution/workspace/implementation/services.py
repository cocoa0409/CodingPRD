"""Lookups, derived-status derivation, ledger recomputes, cascades and
resource serialization.

Every counter here is a FULL RECOMPUTE over its qualifying child set (PRD 2.6 /
2.7) - never an incremental delta - so a counter can legitimately move down when
a contributing row leaves the set.
"""

from core import (
    ApiError,
    REQUIRED_CRAFTS,
    apply_fields,
    db,
    ordered,
    track,
)
from calc import (
    retailer_discount_tier,
    schedule_health_posture,
)

# ---------------------------------------------------------------------------
# Path / body reference resolution (PRD 2.10 steps 4-5)
# ---------------------------------------------------------------------------


def _find(table, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_creator(row_id):
    return _find(db.creators, row_id, "ERR_CREATOR_NOT_FOUND")


def get_title(row_id):
    return _find(db.titles, row_id, "ERR_TITLE_NOT_FOUND")


def get_assignment(row_id):
    return _find(db.assignments, row_id, "ERR_ASSIGNMENT_NOT_FOUND")


def get_issue(row_id):
    return _find(db.issues, row_id, "ERR_ISSUE_NOT_FOUND")


def get_stage(row_id):
    return _find(db.stages, row_id, "ERR_STAGE_NOT_FOUND")


def get_catalog(row_id):
    return _find(db.catalogs, row_id, "ERR_CATALOG_NOT_FOUND")


def get_solicitation(row_id):
    return _find(db.solicitations, row_id, "ERR_SOLICITATION_NOT_FOUND")


def get_variant_cover(row_id):
    return _find(db.variant_covers, row_id, "ERR_VARIANT_COVER_NOT_FOUND")


def get_retailer(row_id):
    return _find(db.retailers, row_id, "ERR_RETAILER_NOT_FOUND")


def get_order(row_id):
    return _find(db.orders, row_id, "ERR_ORDER_NOT_FOUND")


def get_print_run(row_id):
    return _find(db.print_runs, row_id, "ERR_PRINT_RUN_NOT_FOUND")


def get_statement(row_id):
    return _find(db.statements, row_id, "ERR_STATEMENT_NOT_FOUND")


# ---------------------------------------------------------------------------
# Child-set queries (always in created_at ASC order)
# ---------------------------------------------------------------------------


def _children(table, field, value):
    return ordered([r for r in table.values() if r[field] == value])


def title_assignments(title_id):
    return _children(db.assignments, "title_id", title_id)


def creator_assignments(creator_id):
    return _children(db.assignments, "creator_id", creator_id)


def title_issues(title_id):
    return _children(db.issues, "title_id", title_id)


def issue_stages(issue_id):
    return _children(db.stages, "issue_id", issue_id)


def assignment_stages(assignment_id):
    return _children(db.stages, "assignment_id", assignment_id)


def catalog_solicitations(catalog_id):
    return _children(db.solicitations, "catalog_id", catalog_id)


def issue_solicitations(issue_id):
    return _children(db.solicitations, "issue_id", issue_id)


def issue_covers(issue_id):
    return _children(db.variant_covers, "issue_id", issue_id)


def issue_orders(issue_id):
    return _children(db.orders, "issue_id", issue_id)


def retailer_orders(retailer_id):
    return _children(db.orders, "retailer_id", retailer_id)


def issue_print_runs(issue_id):
    return _children(db.print_runs, "issue_id", issue_id)


def issue_release_windows(issue_id):
    return _children(db.release_windows, "issue_id", issue_id)


def issue_revenue_events(issue_id):
    return _children(db.revenue_events, "issue_id", issue_id)


def title_statements(title_id):
    return _children(db.statements, "title_id", title_id)


def standard_cover(issue_id):
    covers = [c for c in issue_covers(issue_id) if c["kind"] == "STANDARD"]
    if not covers:
        return None
    return sorted(covers, key=lambda c: c["code"])[0]


def has_exclusive_cover(issue_id):
    return any(c["kind"] == "RETAILER_EXCLUSIVE" for c in issue_covers(issue_id))


def active_stages(issue_id):
    return [s for s in issue_stages(issue_id) if s["status"] != "CANCELLED"]


def has_required_craft_stages(issue_id):
    crafts = set(s["craft"] for s in active_stages(issue_id))
    return all(craft in crafts for craft in REQUIRED_CRAFTS)


# ---------------------------------------------------------------------------
# Ledger recomputes (PRD 2.7)
# ---------------------------------------------------------------------------

ACTIVE_ASSIGNMENT_STATUSES = ("PROPOSED", "COUNTERED", "ACCEPTED", "ACTIVE")
PARTICIPATING_ASSIGNMENT_STATUSES = ("ACCEPTED", "ACTIVE", "COMPLETED")
COMMITTED_ORDER_STATUSES = ("FOC_LOCKED", "INVOICED", "SHIPPED")
BILLED_ORDER_STATUSES = ("INVOICED", "SHIPPED")
POSTED_STATEMENT_STATUSES = ("ISSUED", "PAID")
SLIP_BEARING_STAGE_STATUSES = ("DELIVERED", "KICKED_BACK", "APPROVED")


def recompute_creator_active_count(creator):
    count = sum(
        1
        for a in creator_assignments(creator["id"])
        if a["status"] in ACTIVE_ASSIGNMENT_STATUSES
    )
    apply_fields(creator, active_assignment_count=count)


def recompute_title_committed_share(title):
    total = sum(
        a["royalty_share_bps"]
        for a in title_assignments(title["id"])
        if a["craft"] != "COVER" and a["status"] in PARTICIPATING_ASSIGNMENT_STATUSES
    )
    apply_fields(title, committed_share_bps=total)


def recompute_title_production_cost(title):
    total = 0
    for issue in title_issues(title["id"]):
        for stage in issue_stages(issue["id"]):
            if stage["status"] == "APPROVED":
                total += stage["page_fee_cents"]
    apply_fields(title, production_cost_cents=total)


def recompute_title_royalty_accrued(title):
    total = sum(
        s["payable_cents"]
        for s in title_statements(title["id"])
        if s["status"] in POSTED_STATEMENT_STATUSES
    )
    apply_fields(title, royalty_accrued_cents=total)


def recompute_unrecouped_advances(title_id, creator_id):
    """An assignment's unrecouped advance is its advance less the recoupment
    posted by that creator's ISSUED/PAID statements on that title."""
    applied = sum(
        s["recoupment_applied_cents"]
        for s in db.statements.values()
        if s["title_id"] == title_id
        and s["creator_id"] == creator_id
        and s["status"] in POSTED_STATEMENT_STATUSES
    )
    for assignment in title_assignments(title_id):
        if assignment["creator_id"] != creator_id:
            continue
        apply_fields(
            assignment,
            unrecouped_advance_cents=assignment["advance_cents"] - applied,
        )


def recompute_catalog_slots(catalog):
    count = sum(
        1 for s in catalog_solicitations(catalog["id"]) if s["status"] == "ACCEPTED"
    )
    apply_fields(catalog, accepted_slot_count=count)


def recompute_retailer_units(retailer):
    total = retailer["opening_units_ytd"] + sum(
        o["total_units"]
        for o in retailer_orders(retailer["id"])
        if o["status"] in COMMITTED_ORDER_STATUSES
    )
    apply_fields(
        retailer,
        cumulative_units_ytd=total,
        discount_tier=retailer_discount_tier(total),
    )


def recompute_retailer_balance(retailer):
    total = sum(
        o["invoice_total_cents"]
        for o in retailer_orders(retailer["id"])
        if o["status"] in BILLED_ORDER_STATUSES
    )
    apply_fields(retailer, open_balance_cents=total)


def recompute_issue_order_units(issue):
    orders = issue_orders(issue["id"])
    ordered_units = sum(
        o["total_units"] for o in orders if o["status"] in COMMITTED_ORDER_STATUSES
    )
    shipped_units = sum(o["total_units"] for o in orders if o["status"] == "SHIPPED")
    apply_fields(
        issue, total_ordered_units=ordered_units, shipped_units=shipped_units
    )


def recompute_issue_printed_units(issue):
    total = sum(
        r["quantity"] for r in issue_print_runs(issue["id"]) if r["status"] == "PRINTED"
    )
    apply_fields(issue, printed_units=total)


# ---------------------------------------------------------------------------
# Derived production dimension (PRD 3.2)
# ---------------------------------------------------------------------------


def _all_approved(stages, crafts=None):
    subset = [s for s in stages if crafts is None or s["craft"] in crafts]
    return all(s["status"] == "APPROVED" for s in subset)


def _any_unapproved(stages, crafts):
    return any(s["craft"] in crafts and s["status"] != "APPROVED" for s in stages)


def derive_production_status(issue):
    """Re-derive the production dimension from the issue's stage set. The rules
    are from-state dependent, so the derivation walks edges until it stabilises;
    in every case with no applicable edge the stored value stays where it was."""
    if issue["production_status"] == "CANCELLED":
        return
    stages = active_stages(issue["id"])
    if not stages:
        apply_fields(issue, production_status="PLANNED")
        return

    state = issue["production_status"]
    for _ in range(8):
        nxt = state
        if state == "PLANNED":
            if not any(s["craft"] == "SCRIPT" and s["status"] == "APPROVED" for s in stages):
                nxt = "SCRIPTING"
        elif state == "SCRIPTING":
            if _all_approved(stages, ("SCRIPT",)) and _any_unapproved(
                stages, ("PENCILS", "INKS", "COLORS")
            ):
                nxt = "ART"
        elif state == "ART":
            if _any_unapproved(stages, ("SCRIPT",)):
                nxt = "SCRIPTING"
            elif _all_approved(
                stages, ("SCRIPT", "PENCILS", "INKS", "COLORS")
            ) and _any_unapproved(stages, ("LETTERS",)):
                nxt = "PREPRESS"
        elif state == "PREPRESS":
            crafts = set(s["craft"] for s in stages)
            if all(c in crafts for c in REQUIRED_CRAFTS) and _all_approved(stages):
                nxt = "CAMERA_READY"
        if nxt == state:
            break
        state = nxt

    if state != issue["production_status"]:
        apply_fields(issue, production_status=state)


# ---------------------------------------------------------------------------
# Slip measurement and the four-hop slip cascade (PRD 3.3)
# ---------------------------------------------------------------------------


def recompute_issue_slip(issue):
    """Hop one: re-sum total_slip_days and re-derive schedule_health. Returns
    True when the posture has just turned into SLIPPED."""
    total = sum(
        s["slip_days"]
        for s in issue_stages(issue["id"])
        if s["status"] in SLIP_BEARING_STAGE_STATUSES
    )
    previous = issue["schedule_health"]
    health = schedule_health_posture(total)
    apply_fields(issue, total_slip_days=total, schedule_health=health)
    return health == "SLIPPED" and previous != "SLIPPED"


def slip_cascade(issue):
    """Hops two through four of the schedule-slip cascade."""
    # Hop two - withdraw the book from every catalog it was listed in. The
    # cascade acts as the system, so a published catalog does not stop it.
    affected_catalogs = {}
    for solicitation in issue_solicitations(issue["id"]):
        if solicitation["status"] in ("SUBMITTED", "ACCEPTED"):
            apply_fields(
                solicitation, status="WITHDRAWN", withdrawn_reason="AUTO_SLIP"
            )
            catalog = db.catalogs.get(solicitation["catalog_id"])
            if catalog is not None:
                affected_catalogs[catalog["id"]] = catalog

    if issue["commercial_status"] == "SOLICITED":
        apply_fields(issue, commercial_status="UNSOLICITED")
    elif issue["commercial_status"] == "FOC_LOCKED":
        pressed = any(
            r["status"] == "PRINTED" for r in issue_print_runs(issue["id"])
        )
        if not pressed:
            apply_fields(issue, commercial_status="UNSOLICITED")

    # Hop three - refresh the slot counts and cancel the order book.
    for catalog in affected_catalogs.values():
        recompute_catalog_slots(catalog)

    affected_retailers = {}
    for order in issue_orders(issue["id"]):
        if order["status"] in ("SUBMITTED", "FOC_LOCKED"):
            apply_fields(order, status="CANCELLED", cancel_reason="AUTO_SLIP")
            retailer = db.retailers.get(order["retailer_id"])
            if retailer is not None:
                affected_retailers[retailer["id"]] = retailer

    # Hop four - refresh the retailer ledgers and the issue roll-up.
    for retailer in affected_retailers.values():
        recompute_retailer_units(retailer)
        recompute_retailer_balance(retailer)
    recompute_issue_order_units(issue)


# ---------------------------------------------------------------------------
# Title bubble-up (PRD 2.6 / 3.7)
# ---------------------------------------------------------------------------


def title_first_issue_created(title):
    if title["status"] == "GREENLIT":
        apply_fields(title, status="IN_PRODUCTION")


def title_issue_went_on_sale(title):
    if title["status"] == "IN_PRODUCTION":
        apply_fields(title, status="PUBLISHING")
        return
    if title["status"] == "PUBLISHING":
        on_sale = sum(
            1
            for i in title_issues(title["id"])
            if i["commercial_status"] == "ON_SALE"
        )
        if on_sale >= title["planned_issue_count"]:
            apply_fields(title, status="COMPLETED")


# ---------------------------------------------------------------------------
# Title cancellation unwind (PRD 3.9)
# ---------------------------------------------------------------------------


def title_cancel_cascade(title):
    # Branch one - release the creative roster.
    affected_creators = {}
    for assignment in title_assignments(title["id"]):
        if assignment["status"] in ACTIVE_ASSIGNMENT_STATUSES:
            apply_fields(
                assignment,
                status="TERMINATED",
                terminated_reason="AUTO_TITLE_CANCEL",
            )
            creator = db.creators.get(assignment["creator_id"])
            if creator is not None:
                affected_creators[creator["id"]] = creator
    for creator in affected_creators.values():
        recompute_creator_active_count(creator)
    recompute_title_committed_share(title)

    # Branch two - close the slate.
    affected_retailers = {}
    cancelled_issues = []
    for issue in title_issues(title["id"]):
        if issue["commercial_status"] == "CANCELLED":
            continue
        apply_fields(issue, commercial_status="CANCELLED", production_status="CANCELLED")
        cancelled_issues.append(issue)

        for run in issue_print_runs(issue["id"]):
            if run["status"] == "PLANNED":
                apply_fields(
                    run, status="CANCELLED", cancel_reason="AUTO_TITLE_CANCEL"
                )
        for stage in issue_stages(issue["id"]):
            if stage["status"] in (
                "NOT_STARTED",
                "IN_PROGRESS",
                "DELIVERED",
                "KICKED_BACK",
            ):
                apply_fields(stage, status="CANCELLED")
        for order in issue_orders(issue["id"]):
            if order["status"] in ("DRAFT", "SUBMITTED", "FOC_LOCKED", "INVOICED"):
                apply_fields(
                    order, status="CANCELLED", cancel_reason="AUTO_TITLE_CANCEL"
                )
                retailer = db.retailers.get(order["retailer_id"])
                if retailer is not None:
                    affected_retailers[retailer["id"]] = retailer

    for retailer in affected_retailers.values():
        recompute_retailer_units(retailer)
        recompute_retailer_balance(retailer)
    for issue in cancelled_issues:
        recompute_issue_order_units(issue)
        recompute_issue_printed_units(issue)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _sys(row, versioned=True):
    out = {"id": row["id"], "created_at": row["created_at"]}
    if versioned:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def creator_json(row):
    out = _sys(row)
    out.update(
        full_name=row["full_name"],
        crafts=list(row["crafts"]),
        default_page_rate_cents=row["default_page_rate_cents"],
        active_assignment_count=row["active_assignment_count"],
    )
    return out


def title_json(row):
    out = _sys(row)
    out.update(
        name=row["name"],
        planned_issue_count=row["planned_issue_count"],
        royalty_pool_bps=row["royalty_pool_bps"],
        cover_participation_bps=row["cover_participation_bps"],
        status=row["status"],
        greenlit_at=row["greenlit_at"],
        committed_share_bps=row["committed_share_bps"],
        production_cost_cents=row["production_cost_cents"],
        royalty_accrued_cents=row["royalty_accrued_cents"],
        cancel_reason=row["cancel_reason"],
    )
    return out


def assignment_json(row):
    out = _sys(row)
    out.update(
        title_id=row["title_id"],
        creator_id=row["creator_id"],
        craft=row["craft"],
        page_rate_cents=row["page_rate_cents"],
        royalty_share_bps=row["royalty_share_bps"],
        booking_start_date=row["booking_start_date"],
        booking_end_date=row["booking_end_date"],
        advance_cents=row["advance_cents"],
        unrecouped_advance_cents=row["unrecouped_advance_cents"],
        status=row["status"],
        negotiation_round=row["negotiation_round"],
        counter_page_rate_cents=row["counter_page_rate_cents"],
        counter_royalty_share_bps=row["counter_royalty_share_bps"],
        terminated_reason=row["terminated_reason"],
    )
    return out


def issue_json(row):
    out = _sys(row)
    out.update(
        title_id=row["title_id"],
        issue_number=row["issue_number"],
        page_count=row["page_count"],
        cover_price_cents=row["cover_price_cents"],
        target_on_sale_date=row["target_on_sale_date"],
        foc_date=row["foc_date"],
        production_status=row["production_status"],
        commercial_status=row["commercial_status"],
        schedule_health=row["schedule_health"],
        total_slip_days=row["total_slip_days"],
        total_ordered_units=row["total_ordered_units"],
        printed_units=row["printed_units"],
        shipped_units=row["shipped_units"],
        on_sale_date=row["on_sale_date"],
    )
    return out


def stage_json(row):
    out = _sys(row)
    out.update(
        issue_id=row["issue_id"],
        assignment_id=row["assignment_id"],
        craft=row["craft"],
        planned_start_date=row["planned_start_date"],
        planned_due_date=row["planned_due_date"],
        actual_delivered_at=row["actual_delivered_at"],
        delivered_pages=row["delivered_pages"],
        slip_days=row["slip_days"],
        page_fee_cents=row["page_fee_cents"],
        kickback_count=row["kickback_count"],
        status=row["status"],
    )
    return out


def catalog_json(row):
    out = _sys(row)
    out.update(
        solicitation_month=row["solicitation_month"],
        submission_deadline=row["submission_deadline"],
        on_sale_month=row["on_sale_month"],
        max_slots=row["max_slots"],
        status=row["status"],
        accepted_slot_count=row["accepted_slot_count"],
        published_at=row["published_at"],
    )
    return out


def solicitation_json(row):
    out = _sys(row)
    out.update(
        catalog_id=row["catalog_id"],
        issue_id=row["issue_id"],
        cover_image_url=row["cover_image_url"],
        copy_text=row["copy_text"],
        variant_cover_ids=list(row["variant_cover_ids"]),
        status=row["status"],
        submitted_at=row["submitted_at"],
        withdrawn_reason=row["withdrawn_reason"],
    )
    return out


def variant_cover_json(row):
    out = _sys(row, versioned=False)
    out.update(
        issue_id=row["issue_id"],
        code=row["code"],
        kind=row["kind"],
        incentive_ratio=row["incentive_ratio"],
        cover_price_cents=row["cover_price_cents"],
        allocation_cap=row["allocation_cap"],
    )
    return out


def retailer_json(row):
    out = _sys(row)
    out.update(
        account_no=row["account_no"],
        name=row["name"],
        credit_limit_cents=row["credit_limit_cents"],
        non_returnable_ack=row["non_returnable_ack"],
        opening_units_ytd=row["opening_units_ytd"],
        cumulative_units_ytd=row["cumulative_units_ytd"],
        open_balance_cents=row["open_balance_cents"],
        discount_tier=row["discount_tier"],
        status=row["status"],
        suspension_reason=row["suspension_reason"],
    )
    return out


def order_json(row):
    out = _sys(row)
    out.update(
        retailer_id=row["retailer_id"],
        issue_id=row["issue_id"],
        standard_qty=row["standard_qty"],
        exclusive_variant_qty=row["exclusive_variant_qty"],
        earned_variant_allocations=[dict(a) for a in row["earned_variant_allocations"]],
        total_units=row["total_units"],
        is_reorder=row["is_reorder"],
        discount_tier_applied=row["discount_tier_applied"],
        merchandise_net_cents=row["merchandise_net_cents"],
        handling_fee_cents=row["handling_fee_cents"],
        invoice_total_cents=row["invoice_total_cents"],
        status=row["status"],
        cancel_reason=row["cancel_reason"],
    )
    return out


def print_run_json(row):
    out = _sys(row)
    out.update(
        issue_id=row["issue_id"],
        printing_number=row["printing_number"],
        basis=row["basis"],
        quantity=row["quantity"],
        order_base_units=row["order_base_units"],
        overprint_units=row["overprint_units"],
        status=row["status"],
        printed_at=row["printed_at"],
        cancel_reason=row["cancel_reason"],
    )
    return out


def release_window_json(row):
    out = _sys(row, versioned=False)
    out.update(
        issue_id=row["issue_id"],
        channel=row["channel"],
        release_date=row["release_date"],
        expected_net_receipts_cents=row["expected_net_receipts_cents"],
    )
    return out


def revenue_event_json(row):
    out = _sys(row, versioned=False)
    out.update(
        issue_id=row["issue_id"],
        channel=row["channel"],
        basis_status=row["basis_status"],
        gross_receipts_cents=row["gross_receipts_cents"],
        net_receipts_cents=row["net_receipts_cents"],
        units=row["units"],
        period=row["period"],
        source=row["source"],
    )
    return out


def statement_json(row):
    out = _sys(row)
    out.update(
        title_id=row["title_id"],
        creator_id=row["creator_id"],
        period=row["period"],
        basis=row["basis"],
        lines=[dict(line) for line in row["lines"]],
        gross_royalty_cents=row["gross_royalty_cents"],
        recoupment_applied_cents=row["recoupment_applied_cents"],
        payable_cents=row["payable_cents"],
        status=row["status"],
        issued_by_user_id=row["issued_by_user_id"],
        paid_by_user_id=row["paid_by_user_id"],
        payment_reference=row["payment_reference"],
        reversal_reason=row["reversal_reason"],
    )
    return out


__all__ = [name for name in dir() if not name.startswith("_")]
