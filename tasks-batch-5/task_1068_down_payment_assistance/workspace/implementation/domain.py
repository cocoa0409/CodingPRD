"""Cross-cutting domain operations: ledger maintenance and cascades."""
import store
import calc


# ----------------------------------------------------------------------------
# Award / allocation helpers
# ----------------------------------------------------------------------------
def award_allocations(award_id):
    return [a for a in store.allocations.values() if a["award_id"] == award_id]


def recompute_allocated(award):
    total = sum(a["amount_cents"] for a in award_allocations(award["id"])
                if a["status"] in ("RESERVED", "DISBURSED"))
    if award.get("allocated_cents") != total:
        award["allocated_cents"] = total
        store.touch(award)
    else:
        award["allocated_cents"] = total


def maybe_auto_fund(award):
    """APPROVED award whose reservations exactly match the approved amount -> FUNDED."""
    if award["status"] == "APPROVED" and award["allocated_cents"] == award["assistance_amount_cents"]:
        award["status"] = "FUNDED"
        store.touch(award)


# ----------------------------------------------------------------------------
# FundingSource ledger movements
# ----------------------------------------------------------------------------
def _maybe_fully_committed(source):
    if source["available_cents"] == 0 and source["reserved_cents"] == 0:
        source["status"] = "FULLY_COMMITTED"


def reserve_on_source(source, amount):
    source["available_cents"] -= amount
    source["reserved_cents"] += amount
    store.touch(source)


def release_on_source(source, amount):
    source["reserved_cents"] -= amount
    source["available_cents"] += amount
    store.touch(source)


def disburse_on_source(source, amount):
    source["reserved_cents"] -= amount
    source["disbursed_cents"] += amount
    _maybe_fully_committed(source)
    store.touch(source)


# ----------------------------------------------------------------------------
# Award cancel cascade
# ----------------------------------------------------------------------------
def cancel_award_cascade(award):
    for alloc in award_allocations(award["id"]):
        if alloc["status"] == "RESERVED":
            source = store.funding_sources[alloc["funding_source_id"]]
            release_on_source(source, alloc["amount_cents"])
            alloc["status"] = "RELEASED"
            store.touch(alloc)
    award["status"] = "CANCELLED"
    store.touch(award)
    recompute_allocated(award)


# ----------------------------------------------------------------------------
# Closing complete cascade (four hops)
# ----------------------------------------------------------------------------
def complete_closing_cascade(closing, award, application, program, prop):
    # Hop 1: recompute final assistance from closing actuals.
    basis = min(closing["final_purchase_price_cents"], prop["appraised_value_cents"])
    final_assist = calc.assistance_amount(
        basis_cents=basis,
        first_mortgage_cents=closing["final_first_mortgage_cents"],
        stated_contribution_cents=application["buyer_contribution_cents"],
        ami_pct_dec=application["ami_pct"],
        max_assistance_cents=program["max_assistance_cents"],
    )
    award["assistance_amount_final_cents"] = final_assist
    award["basis_value_cents"] = basis

    # Hop 2: reconcile over-reservation (release excess, most-junior first).
    allocated = award["allocated_cents"]
    if final_assist < allocated:
        excess = allocated - final_assist
        reserved = [a for a in award_allocations(award["id"]) if a["status"] == "RESERVED"]
        reserved.sort(key=lambda a: (a["lien_position"], a["created_at"], a["_seq"]), reverse=True)
        for alloc in reserved:
            if excess <= 0:
                break
            source = store.funding_sources[alloc["funding_source_id"]]
            if alloc["amount_cents"] <= excess:
                release_on_source(source, alloc["amount_cents"])
                excess -= alloc["amount_cents"]
                alloc["status"] = "RELEASED"
                store.touch(alloc)
            else:
                # Partial release: reduce this allocation's amount to remainder.
                release_on_source(source, excess)
                alloc["amount_cents"] -= excess
                excess = 0
                store.touch(alloc)
        recompute_allocated(award)

    # Hop 3: disburse every still-RESERVED allocation.
    for alloc in award_allocations(award["id"]):
        if alloc["status"] == "RESERVED":
            source = store.funding_sources[alloc["funding_source_id"]]
            disburse_on_source(source, alloc["amount_cents"])
            alloc["status"] = "DISBURSED"
            store.touch(alloc)
    award["original_disbursed_cents"] = final_assist

    # Award FUNDED -> SERVICING
    award["status"] = "SERVICING"
    store.touch(award)
    recompute_allocated(award)

    # Hop 4: open a servicing account.
    sa = store.new_record("servicing")
    sa["award_id"] = award["id"]
    sa["opened_at"] = store.format_ts(store.clock_now())
    sa["_opened_dt"] = store.clock_now()
    sa["principal_balance_cents"] = award["original_disbursed_cents"]
    sa["recapture_amount_cents"] = None
    sa["forgiven_amount_cents"] = None
    sa["lifecycle_status"] = "ACTIVE"
    sa["payment_status"] = "CURRENT"
    store.servicing[sa["id"]] = sa
    return sa


# ----------------------------------------------------------------------------
# Report sale -> recapture
# ----------------------------------------------------------------------------
def report_sale(sa, award, application, program, sale_price_cents, sale_date_raw, sale_dt):
    appreciation = calc.appreciation_cents(sale_price_cents, award["basis_value_cents"])
    if award["recapture_model"] == "SHARED_APPRECIATION":
        recapture, forgiven = calc.shared_appreciation_recapture(
            award["original_disbursed_cents"], appreciation, program["appreciation_share_pct"])
    else:  # DECLINING_BALANCE
        months = calc.full_calendar_months(sa["_opened_dt"], sale_dt)
        recapture, forgiven = calc.declining_balance_recapture(
            award["original_disbursed_cents"], months, program["recapture_term_months"])

    ev = store.new_record("sale_event")
    ev["servicing_account_id"] = sa["id"]
    ev["sale_price_cents"] = sale_price_cents
    ev["sale_date"] = sale_date_raw
    ev["_sale_dt"] = sale_dt
    ev["appreciation_cents"] = appreciation
    ev["recapture_amount_cents"] = recapture
    ev["forgiven_amount_cents"] = forgiven
    store.sale_events[ev["id"]] = ev

    sa["recapture_amount_cents"] = recapture
    sa["forgiven_amount_cents"] = forgiven
    sa["lifecycle_status"] = "IN_SALE"
    store.touch(sa)
    return ev


def close_servicing(sa, award):
    sa["principal_balance_cents"] = 0
    sa["lifecycle_status"] = "CLOSED"
    store.touch(sa)
    if (sa["recapture_amount_cents"] or 0) > 0:
        award["status"] = "RECAPTURED"
    else:
        award["status"] = "REPAID"
    store.touch(award)
