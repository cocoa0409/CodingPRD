"""Store-aware domain logic: lookups, derived quantities, cascades, serializers.

Derived fields (ledger sums, section counters, participation rate, term
ia_section_count) are computed at serialization time from the underlying rows so
the two conserved quantities of PRD 2.7 can never drift.  The `recompute_*`
helpers exist for the *other* half of PRD 2.9: bumping `version` / `updated_at`
on the owning entity and reacting with an `ia_status` flip.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from calc import (D, MIN_PARTICIPATION_RATE, STATE_MIN_SAVINGS_PCT,
                  drop_refund, gross_from_tier, opt_out_deadline,
                  proration_pct, publisher_share, ratio4, rebate_and_settlement,
                  rh_cents, total_term_days)
from errors import fail
from store import base_record, db, fmt_dt, in_order, now, now_iso, touch

# ---------------------------------------------------------------------------
# lookups (PRD 2.11 -- each identifier maps to its own 404)
# ---------------------------------------------------------------------------


def _get(table, key, error_id):
    rec = table.get(key) if isinstance(key, str) else None
    if rec is None:
        fail(error_id)
    return rec


def get_term(term_id):
    return _get(db.terms, term_id, "ERR_TERM_NOT_FOUND")


def get_student(student_id):
    return _get(db.students, student_id, "ERR_STUDENT_NOT_FOUND")


def get_agreement(agreement_id):
    return _get(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")


def get_title(title_id):
    return _get(db.titles, title_id, "ERR_TITLE_NOT_FOUND")


def get_tier(tier_id):
    return _get(db.tiers, tier_id, "ERR_TIER_NOT_FOUND")


def get_section(section_id):
    return _get(db.sections, section_id, "ERR_SECTION_NOT_FOUND")


def get_adoption(adoption_id):
    return _get(db.adoptions, adoption_id, "ERR_ADOPTION_NOT_FOUND")


def get_enrollment(enrollment_id):
    return _get(db.enrollments, enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")


def get_charge(charge_id):
    return _get(db.charges, charge_id, "ERR_CHARGE_NOT_FOUND")


def get_ledger_entry(entry_id):
    return _get(db.ledger_entries, entry_id, "ERR_LEDGER_ENTRY_NOT_FOUND")


def get_opt_out_request(request_id):
    return _get(db.opt_out_requests, request_id, "ERR_OPT_OUT_REQUEST_NOT_FOUND")


def get_run(run_id):
    return _get(db.runs, run_id, "ERR_RUN_NOT_FOUND")


def get_report(report_id):
    return _get(db.reports, report_id, "ERR_REPORT_NOT_FOUND")


# ---------------------------------------------------------------------------
# navigation
# ---------------------------------------------------------------------------


def title_of_adoption(adoption):
    return db.titles[adoption["title_id"]]


def agreement_of_title(title):
    return db.agreements[title["agreement_id"]]


def agreement_of_adoption(adoption):
    return agreement_of_title(title_of_adoption(adoption))


def enrollment_of_charge(charge):
    return db.enrollments[charge["enrollment_id"]]


def adoption_of_charge(charge):
    return db.adoptions[charge["adoption_id"]]


def section_of_charge(charge):
    return db.sections[enrollment_of_charge(charge)["section_id"]]


def agreement_of_charge(charge):
    return agreement_of_adoption(adoption_of_charge(charge))


def term_of_section(section):
    return db.terms[section["term_id"]]


def term_of_charge(charge):
    return term_of_section(section_of_charge(charge))


def enrollments_of_section(section_id):
    return in_order([e for e in db.enrollments.values() if e["section_id"] == section_id])


def charges_of_section(section_id):
    out = []
    for c in db.charges.values():
        enr = db.enrollments.get(c["enrollment_id"])
        if enr is not None and enr["section_id"] == section_id:
            out.append(c)
    return in_order(out)


def charges_of_enrollment(enrollment_id):
    return in_order([c for c in db.charges.values() if c["enrollment_id"] == enrollment_id])


def charges_of_adoption(adoption_id):
    return in_order([c for c in db.charges.values() if c["adoption_id"] == adoption_id])


def ledger_of_charge(charge_id):
    return in_order([r for r in db.ledger_entries.values() if r["charge_id"] == charge_id])


def ledger_of_student(student_id):
    return in_order([r for r in db.ledger_entries.values() if r["student_id"] == student_id])


def opt_outs_of_charge(charge_id):
    return in_order([r for r in db.opt_out_requests.values() if r["charge_id"] == charge_id])


def tiers_of_title(title_id):
    return in_order([t for t in db.tiers.values() if t["title_id"] == title_id])


def titles_of_agreement(agreement_id):
    return in_order([t for t in db.titles.values() if t["agreement_id"] == agreement_id])


def adoptions_of_section(section_id):
    return in_order([a for a in db.adoptions.values() if a["section_id"] == section_id])


def sections_of_term(term_id):
    return in_order([s for s in db.sections.values() if s["term_id"] == term_id])


def approved_adoptions(section_id):
    return [a for a in adoptions_of_section(section_id) if a["status"] == "APPROVED"]


def current_approved_adoption(section_id):
    """The APPROVED adoption most recently approved on the section."""
    approved = approved_adoptions(section_id)
    if not approved:
        return None
    return sorted(approved, key=lambda a: (a["approved_at"] or now(), a["_seq"]))[-1]


def charge_order_key(charge):
    """created_at ASC, tie-break owning student's external_id ASC."""
    student = db.students.get(charge["student_id"])
    return (charge["created_at"], (student or {}).get("external_id") or "", charge["_seq"])


# ---------------------------------------------------------------------------
# derived money
# ---------------------------------------------------------------------------


def charge_net(charge):
    return sum(r["amount_cents"] for r in db.ledger_entries.values()
               if r["charge_id"] == charge["id"])


def charge_publisher_share(charge):
    agreement = agreement_of_charge(charge)
    return publisher_share(charge_net(charge), agreement["bookstore_margin_pct"])


def student_balance(student_id):
    return sum(r["amount_cents"] for r in db.ledger_entries.values()
               if r["student_id"] == student_id)


def add_ledger(charge, entry_type, reason_code, amount_cents, source_event):
    rec = base_record(versioned=False)
    rec.update({
        "charge_id": charge["id"],
        "student_id": charge["student_id"],
        "entry_type": entry_type,
        "reason_code": reason_code,
        "amount_cents": int(amount_cents),
        "posted_at": now(),
        "source_event": source_event,
    })
    db.ledger_entries[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# derived section counters
# ---------------------------------------------------------------------------


def section_enrolled_count(section_id):
    return sum(1 for e in db.enrollments.values()
               if e["section_id"] == section_id and e["status"] == "ENROLLED")


def section_provisioned_count(section_id):
    return sum(1 for c in charges_of_section(section_id)
               if c["access_status"] in ("PROVISIONED", "RESTORED"))


def section_revoked_count(section_id):
    return sum(1 for c in charges_of_section(section_id)
               if c["access_status"] == "REVOKED")


def section_opted_out_count(section_id):
    charge_ids = set(c["id"] for c in charges_of_section(section_id))
    return sum(1 for r in db.opt_out_requests.values()
               if r["charge_id"] in charge_ids and r["status"] == "GRANTED")


def section_participation_rate(section_id):
    enrolled = section_enrolled_count(section_id)
    if enrolled == 0:
        return Decimal("0.0000")
    return ratio4(section_provisioned_count(section_id), enrolled)


def term_ia_section_count(term_id):
    return sum(1 for s in db.sections.values()
               if s["term_id"] == term_id and s["inclusive_access_flag"])


def recompute_section(section):
    """PRD 2.9 tail: recompute the section's derived fields (a mutation) and let
    ia_status react from the two billed postures only."""
    rate = section_participation_rate(section["id"])
    if section["ia_status"] == "BILLED" and rate < MIN_PARTICIPATION_RATE:
        section["ia_status"] = "AT_RISK"
    elif section["ia_status"] == "AT_RISK" and rate >= MIN_PARTICIPATION_RATE:
        section["ia_status"] = "BILLED"
    touch(section)


def recompute_term_ia_count(term):
    touch(term)


def mark_agreement_stale(agreement):
    if agreement["reconciliation_status"] in ("COMPUTED", "DISPUTED"):
        agreement["reconciliation_status"] = "STALE"
        touch(agreement)


def cascade_tail(charge):
    """The common tail shared by opt-out grant, rescind, drop and rebill."""
    recompute_section(section_of_charge(charge))
    mark_agreement_stale(agreement_of_charge(charge))


# ---------------------------------------------------------------------------
# pricing
# ---------------------------------------------------------------------------


def resolve_tier(title_id, n):
    for tier in tiers_of_title(title_id):
        if tier["min_enrollment"] <= n and (tier["max_enrollment"] is None
                                            or n <= tier["max_enrollment"]):
            return tier
    return None


def gross_price(adoption, n, strict=True):
    """Three-step per-student price.  Returns None when no band covers n and
    `strict` is False; otherwise raises ERR_NO_PRICING_TIER."""
    title = title_of_adoption(adoption)
    agreement = agreement_of_title(title)
    tier = resolve_tier(title["id"], n)
    if tier is None:
        if strict:
            fail("ERR_NO_PRICING_TIER")
        return None
    return gross_from_tier(
        tier["per_student_price_cents"], agreement["admin_fee_pct"],
        title["list_price_cents"], agreement["max_list_price_pct"],
        agreement["price_floor_cents"],
    )


def tier_basis(section):
    if section["billing_basis_enrollment_count"] is not None:
        return section["billing_basis_enrollment_count"]
    return section_enrolled_count(section["id"])


def census_basis(section, term):
    census = term["census_date"]
    count = 0
    for enr in enrollments_of_section(section["id"]):
        if enr["enrolled_on"] > census:
            continue
        if enr["status"] == "ENROLLED":
            count += 1
        elif enr["dropped_on"] is not None and enr["dropped_on"] > census:
            count += 1
    return count


# ---------------------------------------------------------------------------
# charge posting
# ---------------------------------------------------------------------------


def post_charge(section, term, enrollment, adoption, basis, source_event):
    gross = gross_price(adoption, basis)
    days = term["total_term_days"]
    pct = proration_pct(enrollment["enrolled_on"], term["term_start_date"],
                        term["add_drop_deadline"], days)
    billed = rh_cents(D(gross) * pct)

    charge = base_record()
    charge.update({
        "enrollment_id": enrollment["id"],
        "adoption_id": adoption["id"],
        "student_id": enrollment["student_id"],
        "gross_price_cents": gross,
        "proration_pct": pct,
        "billed_amount_cents": billed,
        "refunded_amount_cents": 0,
        "billing_status": "PENDING",
        "access_status": "NOT_PROVISIONED",
        "posted_at": None,
        "opt_out_deadline_at": None,
        "access_start_at": None,
        "access_revoked_at": None,
        "access_restored_at": None,
        "rebill_count": 0,
    })
    db.charges[charge["id"]] = charge

    # PENDING -> POSTED and NOT_PROVISIONED -> PROVISIONED inside this request.
    reason = "INITIAL_POST"
    if source_event.endswith("/post-charge") and enrollment["registration_type"] == "LATE":
        reason = "LATE_REGISTRATION_POST"
    charge["posted_at"] = now()
    charge["opt_out_deadline_at"] = opt_out_deadline(
        now(), term["opt_out_window_days"], term["add_drop_deadline"])
    charge["billing_status"] = "POSTED"
    charge["access_status"] = "PROVISIONED"
    charge["access_start_at"] = now()
    add_ledger(charge, "CHARGE", reason, billed, source_event)
    return charge


def uncharged_enrollments(section, adoption):
    """ENROLLED enrollments of the section without a live charge on `adoption`,
    ordered by enrolled_on ASC then the student's external_id ASC."""
    out = []
    for enr in enrollments_of_section(section["id"]):
        if enr["status"] != "ENROLLED":
            continue
        if has_live_charge(enr["id"], adoption["id"]):
            continue
        out.append(enr)
    return sorted(out, key=lambda e: (
        e["enrolled_on"],
        (db.students.get(e["student_id"]) or {}).get("external_id") or "",
        e["_seq"],
    ))


def has_live_charge(enrollment_id, adoption_id):
    for c in db.charges.values():
        if c["enrollment_id"] != enrollment_id or c["adoption_id"] != adoption_id:
            continue
        if c["billing_status"] in ("POSTED", "PARTIALLY_REFUNDED", "REFUNDED", "REBILLED"):
            return True
    return False


def freeze_billing_basis(section, term, basis):
    """First successful posting on the section: FLAGGED -> BILLED."""
    if section["ia_status"] == "FLAGGED":
        section["ia_status"] = "BILLED"
        section["billing_basis_enrollment_count"] = basis
        section["first_posted_at"] = now()
        touch(section)


# ---------------------------------------------------------------------------
# title-change rebill (PRD 3.7 hop two)
# ---------------------------------------------------------------------------


def rebill(new_adoption, old_adoption, section, source_event):
    participating = [c for c in charges_of_adoption(old_adoption["id"])
                     if c["billing_status"] in ("POSTED", "REBILLED")]
    participating.sort(key=charge_order_key)
    if not participating:
        return False
    basis = tier_basis(section)
    # Resolve the new price once, before any ledger row is appended, so a
    # missing band cannot leave the rebill half applied.
    new_gross = gross_price(new_adoption, basis)
    for charge in participating:
        old_net = charge_net(charge)
        add_ledger(charge, "REBILL_CREDIT", "TITLE_CHANGE_REBILL", -old_net, source_event)
        new_billed = rh_cents(D(new_gross) * D(charge["proration_pct"]))
        add_ledger(charge, "REBILL_CHARGE", "TITLE_CHANGE_REBILL", new_billed, source_event)
        charge["adoption_id"] = new_adoption["id"]
        charge["gross_price_cents"] = new_gross
        charge["billed_amount_cents"] = new_billed
        charge["billing_status"] = "REBILLED"
        charge["rebill_count"] += 1
        touch(charge)
    return True


# ---------------------------------------------------------------------------
# drop refunds (PRD 3.7)
# ---------------------------------------------------------------------------


def apply_drop_refunds(enrollment, section, term, source_event):
    touched_any = False
    charges = [c for c in charges_of_enrollment(enrollment["id"])
               if c["billing_status"] in ("POSTED", "REBILLED")]
    charges.sort(key=charge_order_key)
    for charge in charges:
        net = charge_net(charge)
        refund = drop_refund(net, enrollment["dropped_on"], term["term_start_date"],
                             term["add_drop_deadline"], term["total_term_days"])
        if refund <= 0:
            continue
        charge["refunded_amount_cents"] += refund
        charge["billing_status"] = "REFUNDED" if refund == net else "PARTIALLY_REFUNDED"
        charge["access_status"] = "REVOKED"
        charge["access_revoked_at"] = now()
        add_ledger(charge, "REFUND", "DROP_PRORATION", -refund, source_event)
        touch(charge)
        touched_any = True
        mark_agreement_stale(agreement_of_charge(charge))
    return touched_any


# ---------------------------------------------------------------------------
# reconciliation
# ---------------------------------------------------------------------------


def run_scope(agreement_id, term_id):
    scope = []
    for charge in db.charges.values():
        adoption = db.adoptions.get(charge["adoption_id"])
        if adoption is None:
            continue
        title = db.titles.get(adoption["title_id"])
        if title is None or title["agreement_id"] != agreement_id:
            continue
        enr = db.enrollments.get(charge["enrollment_id"])
        if enr is None:
            continue
        section = db.sections.get(enr["section_id"])
        if section is None or section["term_id"] != term_id:
            continue
        if not section["inclusive_access_flag"]:
            continue
        scope.append(charge)
    scope.sort(key=charge_order_key)
    return scope


def granted_opt_out_exists(charge_id):
    return any(r["charge_id"] == charge_id and r["status"] == "GRANTED"
               for r in db.opt_out_requests.values())


def reconciliation_totals(agreement, term, method):
    scope = run_scope(agreement["id"], term["id"])

    opted_out_count = sum(1 for c in scope
                          if c["billing_status"] == "REFUNDED"
                          and granted_opt_out_exists(c["id"]))

    if method == "ENROLLMENT_SNAPSHOT":
        included = [c for c in scope
                    if c["billing_status"] in ("POSTED", "PARTIALLY_REFUNDED", "REBILLED")]
        billable_count = len(included)
        gross = sum(charge_publisher_share(c) for c in included)
        return billable_count, opted_out_count, gross

    # ACCESS_DAYS_WEIGHTED
    included = [c for c in scope
                if c["access_status"] in ("PROVISIONED", "REVOKED", "RESTORED")]
    days = term["total_term_days"]
    billable_count = 0
    gross = 0
    for charge in included:
        adoption = adoption_of_charge(charge)
        access_from = max(charge["access_start_at"].date(), adoption["access_start_date"])
        if charge["access_status"] == "REVOKED":
            access_until = min(charge["access_revoked_at"].date() - timedelta(days=1),
                               term["term_end_date"])
        else:
            access_until = term["term_end_date"]
        access_days = max(0, (access_until - access_from).days + 1)
        weight = ratio4(access_days, days)
        share = charge_publisher_share(charge)
        if share == 0 and charge["refunded_amount_cents"] > 0:
            # A refunded charge's net (and therefore its share) is 0; reconstruct
            # the pre-refund publisher share.
            share = publisher_share(charge["refunded_amount_cents"],
                                    agreement["bookstore_margin_pct"])
        if weight > 0:
            billable_count += 1
        gross += rh_cents(D(share) * weight)
    return billable_count, opted_out_count, gross


def current_computed_run(agreement_id, term_id):
    candidates = [r for r in db.runs.values()
                  if r["agreement_id"] == agreement_id and r["term_id"] == term_id
                  and r["status"] in ("COMPUTED", "DISPUTED")]
    if not candidates:
        return None
    return sorted(candidates, key=lambda r: (r["created_at"], r["_seq"]))[-1]


def agreements_pricing_term(term_id):
    out = {}
    for charge in db.charges.values():
        adoption = db.adoptions.get(charge["adoption_id"])
        if adoption is None:
            continue
        title = db.titles.get(adoption["title_id"])
        if title is None:
            continue
        enr = db.enrollments.get(charge["enrollment_id"])
        if enr is None:
            continue
        section = db.sections.get(enr["section_id"])
        if section is None or section["term_id"] != term_id:
            continue
        agreement = db.agreements.get(title["agreement_id"])
        if agreement is not None:
            out[agreement["id"]] = agreement
    return list(out.values())


def close_term_if_ready(term):
    """Hops two and three of the settlement cascade (PRD 3.8)."""
    if term["status"] != "BILLING_LOCKED":
        return
    agreements = agreements_pricing_term(term["id"])
    for agreement in agreements:
        if agreement["reconciliation_status"] != "SETTLED":
            return
    term["status"] = "CLOSED"
    term["closed_at"] = now()
    touch(term)
    for report in db.reports.values():
        if report["term_id"] == term["id"] and report["status"] == "CERTIFIED":
            report["status"] = "PUBLISHED"
            report["published_at"] = now()
            touch(report)


# ---------------------------------------------------------------------------
# affordability metrics (PRD 3.9)
# ---------------------------------------------------------------------------


def affordability_metrics(term_id):
    scope_sections = [s for s in sections_of_term(term_id) if s["inclusive_access_flag"]]
    section_ids = set(s["id"] for s in scope_sections)

    all_charges = []
    for charge in db.charges.values():
        enr = db.enrollments.get(charge["enrollment_id"])
        if enr is not None and enr["section_id"] in section_ids:
            all_charges.append(charge)

    scope_charges = [c for c in all_charges
                     if c["billing_status"] in ("POSTED", "PARTIALLY_REFUNDED", "REBILLED")]

    enrolled_student_count = sum(1 for e in db.enrollments.values()
                                 if e["section_id"] in section_ids and e["status"] == "ENROLLED")

    opted_out_students = set()
    for charge in all_charges:
        if granted_opt_out_exists(charge["id"]):
            opted_out_students.add(charge["student_id"])

    total_list = 0
    for charge in scope_charges:
        adoption = db.adoptions.get(charge["adoption_id"])
        locked = (adoption or {}).get("locked_list_price_cents")
        if locked:
            total_list += locked
    total_net = sum(charge_net(c) for c in scope_charges)

    charge_count = len(scope_charges)
    average = 0 if charge_count == 0 else rh_cents(D(total_net) / D(charge_count))
    if total_list == 0:
        savings = Decimal("0.0000")
    else:
        savings = ratio4(D(total_list) - D(total_net), total_list)

    if charge_count == 0:
        compliance = "NOT_APPLICABLE"
    elif savings >= STATE_MIN_SAVINGS_PCT:
        compliance = "COMPLIANT"
    else:
        compliance = "NON_COMPLIANT"

    return {
        "ia_section_count": len(scope_sections),
        "charge_count": charge_count,
        "enrolled_student_count": enrolled_student_count,
        "opted_out_student_count": len(opted_out_students),
        "total_list_price_cents": total_list,
        "total_net_billed_cents": total_net,
        "average_net_cost_cents": average,
        "savings_pct": savings,
        "compliance_status": compliance,
    }


# ---------------------------------------------------------------------------
# serialization
# ---------------------------------------------------------------------------


def _d(value):
    """ISO calendar date or null."""
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return value


def _t(value):
    """ISO 8601 UTC instant with three fractional digits, or null."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return fmt_dt(value)
    return value


def _n(value):
    """Exact decimal fraction rendered as a JSON number."""
    if value is None:
        return None
    return float(value)


def term_json(term):
    return {
        "id": term["id"],
        "code": term["code"],
        "name": term["name"],
        "term_start_date": _d(term["term_start_date"]),
        "term_end_date": _d(term["term_end_date"]),
        "total_term_days": term["total_term_days"],
        "instructional_days": term["instructional_days"],
        "census_date": _d(term["census_date"]),
        "add_drop_deadline": _d(term["add_drop_deadline"]),
        "late_registration_cutoff_date": _d(term["late_registration_cutoff_date"]),
        "adoption_deadline_date": _d(term["adoption_deadline_date"]),
        "disclosure_deadline_date": _d(term["disclosure_deadline_date"]),
        "opt_out_window_days": term["opt_out_window_days"],
        "status": term["status"],
        "ia_section_count": term_ia_section_count(term["id"]),
        "closed_at": _t(term["closed_at"]),
        "created_at": term["created_at"],
        "updated_at": term["updated_at"],
        "version": term["version"],
    }


def student_json(student):
    return {
        "id": student["id"],
        "external_id": student["external_id"],
        "full_name": student["full_name"],
        "email": student["email"],
        "program_code": student["program_code"],
        "status": student["status"],
        "bursar_balance_cents": student_balance(student["id"]),
        "created_at": student["created_at"],
        "updated_at": student["updated_at"],
        "version": student["version"],
    }


def agreement_json(agreement):
    return {
        "id": agreement["id"],
        "publisher_name": agreement["publisher_name"],
        "agreement_code": agreement["agreement_code"],
        "effective_from": _d(agreement["effective_from"]),
        "effective_to": _d(agreement["effective_to"]),
        "admin_fee_pct": _n(agreement["admin_fee_pct"]),
        "bookstore_margin_pct": _n(agreement["bookstore_margin_pct"]),
        "price_floor_cents": agreement["price_floor_cents"],
        "max_list_price_pct": _n(agreement["max_list_price_pct"]),
        "rebate_threshold_cents": agreement["rebate_threshold_cents"],
        "rebate_pct": _n(agreement["rebate_pct"]),
        "status": agreement["status"],
        "reconciliation_status": agreement["reconciliation_status"],
        "settled_amount_cents": agreement["settled_amount_cents"],
        "suspend_reason_note": agreement["suspend_reason_note"],
        "created_at": agreement["created_at"],
        "updated_at": agreement["updated_at"],
        "version": agreement["version"],
    }


def title_json(title):
    return {
        "id": title["id"],
        "agreement_id": title["agreement_id"],
        "isbn": title["isbn"],
        "title": title["title"],
        "list_price_cents": title["list_price_cents"],
        "format": title["format"],
        "status": title["status"],
        "created_at": title["created_at"],
        "updated_at": title["updated_at"],
        "version": title["version"],
    }


def tier_json(tier):
    return {
        "id": tier["id"],
        "title_id": tier["title_id"],
        "min_enrollment": tier["min_enrollment"],
        "max_enrollment": tier["max_enrollment"],
        "per_student_price_cents": tier["per_student_price_cents"],
        "created_at": tier["created_at"],
        "updated_at": tier["updated_at"],
        "version": tier["version"],
    }


def section_json(section):
    sid = section["id"]
    return {
        "id": sid,
        "term_id": section["term_id"],
        "subject_code": section["subject_code"],
        "catalog_number": section["catalog_number"],
        "section_number": section["section_number"],
        "instructor_user_id": section["instructor_user_id"],
        "max_concurrent_titles": section["max_concurrent_titles"],
        "inclusive_access_flag": section["inclusive_access_flag"],
        "ia_status": section["ia_status"],
        "enrolled_count": section_enrolled_count(sid),
        "provisioned_access_count": section_provisioned_count(sid),
        "revoked_access_count": section_revoked_count(sid),
        "opted_out_count": section_opted_out_count(sid),
        "participation_rate": _n(section_participation_rate(sid)),
        "billing_basis_enrollment_count": section["billing_basis_enrollment_count"],
        "first_posted_at": _t(section["first_posted_at"]),
        "created_at": section["created_at"],
        "updated_at": section["updated_at"],
        "version": section["version"],
    }


def adoption_json(adoption):
    return {
        "id": adoption["id"],
        "section_id": adoption["section_id"],
        "title_id": adoption["title_id"],
        "supersedes_adoption_id": adoption["supersedes_adoption_id"],
        "status": adoption["status"],
        "access_start_date": _d(adoption["access_start_date"]),
        "access_end_date": _d(adoption["access_end_date"]),
        "submitted_by_user_id": adoption["submitted_by_user_id"],
        "approved_by_user_id": adoption["approved_by_user_id"],
        "submitted_at": _t(adoption["submitted_at"]),
        "approved_at": _t(adoption["approved_at"]),
        "locked_list_price_cents": adoption["locked_list_price_cents"],
        "change_note": adoption["change_note"],
        "revision_count": adoption["revision_count"],
        "requires_rebill": adoption["requires_rebill"],
        "created_at": adoption["created_at"],
        "updated_at": adoption["updated_at"],
        "version": adoption["version"],
    }


def enrollment_json(enrollment):
    return {
        "id": enrollment["id"],
        "section_id": enrollment["section_id"],
        "student_id": enrollment["student_id"],
        "enrolled_on": _d(enrollment["enrolled_on"]),
        "registration_type": enrollment["registration_type"],
        "status": enrollment["status"],
        "dropped_on": _d(enrollment["dropped_on"]),
        "created_at": enrollment["created_at"],
        "updated_at": enrollment["updated_at"],
        "version": enrollment["version"],
    }


def charge_json(charge):
    return {
        "id": charge["id"],
        "enrollment_id": charge["enrollment_id"],
        "adoption_id": charge["adoption_id"],
        "student_id": charge["student_id"],
        "gross_price_cents": charge["gross_price_cents"],
        "proration_pct": _n(charge["proration_pct"]),
        "billed_amount_cents": charge["billed_amount_cents"],
        "refunded_amount_cents": charge["refunded_amount_cents"],
        "net_billed_cents": charge_net(charge),
        "publisher_share_cents": charge_publisher_share(charge),
        "billing_status": charge["billing_status"],
        "access_status": charge["access_status"],
        "posted_at": _t(charge["posted_at"]),
        "opt_out_deadline_at": _t(charge["opt_out_deadline_at"]),
        "access_start_at": _t(charge["access_start_at"]),
        "access_revoked_at": _t(charge["access_revoked_at"]),
        "access_restored_at": _t(charge["access_restored_at"]),
        "rebill_count": charge["rebill_count"],
        "created_at": charge["created_at"],
        "updated_at": charge["updated_at"],
        "version": charge["version"],
    }


def ledger_json(entry):
    return {
        "id": entry["id"],
        "charge_id": entry["charge_id"],
        "student_id": entry["student_id"],
        "entry_type": entry["entry_type"],
        "reason_code": entry["reason_code"],
        "amount_cents": entry["amount_cents"],
        "posted_at": _t(entry["posted_at"]),
        "source_event": entry["source_event"],
        "created_at": entry["created_at"],
    }


def opt_out_json(request):
    return {
        "id": request["id"],
        "charge_id": request["charge_id"],
        "status": request["status"],
        "reason_code": request["reason_code"],
        "submitted_at": _t(request["submitted_at"]),
        "decided_at": _t(request["decided_at"]),
        "decided_by_user_id": request["decided_by_user_id"],
        "denial_note": request["denial_note"],
        "refund_amount_cents": request["refund_amount_cents"],
        "rescinded_at": _t(request["rescinded_at"]),
        "recharge_amount_cents": request["recharge_amount_cents"],
        "cycle_count": request["cycle_count"],
        "created_at": request["created_at"],
        "updated_at": request["updated_at"],
        "version": request["version"],
    }


def run_json(run):
    return {
        "id": run["id"],
        "agreement_id": run["agreement_id"],
        "term_id": run["term_id"],
        "supersedes_run_id": run["supersedes_run_id"],
        "method": run["method"],
        "status": run["status"],
        "billable_count": run["billable_count"],
        "opted_out_count": run["opted_out_count"],
        "gross_invoice_cents": run["gross_invoice_cents"],
        "rebate_cents": run["rebate_cents"],
        "settlement_amount_cents": run["settlement_amount_cents"],
        "publisher_reported_count": run["publisher_reported_count"],
        "publisher_reported_amount_cents": run["publisher_reported_amount_cents"],
        "count_variance": run["count_variance"],
        "variance_cents": run["variance_cents"],
        "dispute_note": run["dispute_note"],
        "computed_by_user_id": run["computed_by_user_id"],
        "settled_by_user_id": run["settled_by_user_id"],
        "settled_at": _t(run["settled_at"]),
        "created_at": run["created_at"],
        "updated_at": run["updated_at"],
        "version": run["version"],
    }


def report_json(report):
    return {
        "id": report["id"],
        "term_id": report["term_id"],
        "reporting_state_code": report["reporting_state_code"],
        "status": report["status"],
        "ia_section_count": report["ia_section_count"],
        "charge_count": report["charge_count"],
        "enrolled_student_count": report["enrolled_student_count"],
        "opted_out_student_count": report["opted_out_student_count"],
        "total_list_price_cents": report["total_list_price_cents"],
        "total_net_billed_cents": report["total_net_billed_cents"],
        "average_net_cost_cents": report["average_net_cost_cents"],
        "savings_pct": _n(report["savings_pct"]),
        "compliance_status": report["compliance_status"],
        "certified_by_user_id": report["certified_by_user_id"],
        "certified_at": _t(report["certified_at"]),
        "published_at": _t(report["published_at"]),
        "amendment_note": report["amendment_note"],
        "amendment_count": report["amendment_count"],
        "created_at": report["created_at"],
        "updated_at": report["updated_at"],
        "version": report["version"],
    }
