"""Domain services: row lifecycle, lookups, derived-value recomputation and the
cascades of PRD §2.7 / §3.6 / §3.7 / §3.8.
"""

from decimal import Decimal

from flask import g, has_request_context

import calc
from clockutil import add_days, now
from db import db, new_id
from errors import fail

# --------------------------------------------------------------------------
# row lifecycle
# --------------------------------------------------------------------------

LIVE_SCHEDULE_STATUSES = ("ACTIVE", "DEFAULT_ELIGIBLE", "NOTICED")
OPEN_INSTALLMENT_STATUSES = ("SCHEDULED", "DUE", "DELINQUENT")
WITHDRAWN_EMPLOYER_STATUSES = ("PARTIAL_WITHDRAWN", "COMPLETE_WITHDRAWN", "DEFAULTED")


def _bumped():
    """Ids already version-bumped during the current request.

    One request must move a given row's `version` by at most one, however many
    cascade links happen to reach it; a row created by the request stays at
    version 1.
    """
    if not has_request_context():
        return set()
    seen = getattr(g, "_bumped_rows", None)
    if seen is None:
        seen = set()
        g._bumped_rows = seen
    return seen


def new_row(collection, fields):
    stamp = now()
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = db.next_seq()
    collection[row["id"]] = row
    _bumped().add(row["id"])
    return row


def touch(row):
    row["updated_at"] = now()
    seen = _bumped()
    if row["id"] in seen:
        return
    seen.add(row["id"])
    row["version"] += 1


def apply_changes(row, changes):
    """Apply changed values only; touch the row once if anything moved."""
    dirty = False
    for name, value in changes.items():
        if row.get(name) != value:
            row[name] = value
            dirty = True
    if dirty:
        touch(row)
    return dirty


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])


# --------------------------------------------------------------------------
# lookups (tier 4 / tier 5)
# --------------------------------------------------------------------------

def _find(collection, row_id, error_id):
    if not isinstance(row_id, str):
        fail(error_id)
    row = collection.get(row_id)
    if row is None:
        fail(error_id)
    return row


def get_plan(row_id):
    return _find(db.plans, row_id, "ERR_PLAN_NOT_FOUND")


def get_group(row_id):
    return _find(db.controlled_groups, row_id, "ERR_CONTROLLED_GROUP_NOT_FOUND")


def get_employer(row_id):
    return _find(db.employers, row_id, "ERR_EMPLOYER_NOT_FOUND")


def get_valuation(row_id):
    return _find(db.valuations, row_id, "ERR_VALUATION_NOT_FOUND")


def get_record(row_id):
    return _find(db.contribution_records, row_id, "ERR_CONTRIBUTION_RECORD_NOT_FOUND")


def get_event(row_id):
    return _find(db.withdrawal_events, row_id, "ERR_WITHDRAWAL_EVENT_NOT_FOUND")


def get_assessment(row_id):
    return _find(db.assessments, row_id, "ERR_ASSESSMENT_NOT_FOUND")


def get_schedule(row_id):
    return _find(db.schedules, row_id, "ERR_SCHEDULE_NOT_FOUND")


def get_installment(row_id):
    return _find(db.installments, row_id, "ERR_INSTALLMENT_NOT_FOUND")


def get_review(row_id):
    return _find(db.review_requests, row_id, "ERR_REVIEW_REQUEST_NOT_FOUND")


def get_arbitration(row_id):
    return _find(db.arbitrations, row_id, "ERR_ARBITRATION_NOT_FOUND")


def get_transaction(row_id):
    return _find(db.transactions, row_id, "ERR_TRANSACTION_NOT_FOUND")


# --------------------------------------------------------------------------
# relationship walks
# --------------------------------------------------------------------------

def employer_of_event(event):
    return db.employers.get(event["employer_id"])


def employer_of_assessment(assessment):
    event = db.withdrawal_events.get(assessment["withdrawal_event_id"])
    return employer_of_event(event) if event else None


def employer_of_schedule(schedule):
    assessment = db.assessments.get(schedule["liability_assessment_id"])
    return employer_of_assessment(assessment) if assessment else None


def employer_of_installment(inst):
    schedule = db.schedules.get(inst["payment_schedule_id"])
    return employer_of_schedule(schedule) if schedule else None


def plan_of_employer(employer):
    return db.plans.get(employer["plan_id"])


def plan_of_assessment(assessment):
    employer = employer_of_assessment(assessment)
    return plan_of_employer(employer) if employer else None


def assessments_of_employer(employer_id):
    out = []
    for assessment in db.assessments.values():
        employer = employer_of_assessment(assessment)
        if employer and employer["id"] == employer_id:
            out.append(assessment)
    return out


def assessments_of_plan(plan_id):
    out = []
    for assessment in db.assessments.values():
        employer = employer_of_assessment(assessment)
        if employer and employer["plan_id"] == plan_id:
            out.append(assessment)
    return out


def schedules_of(assessment_id):
    return by_seq([s for s in db.schedules.values()
                   if s["liability_assessment_id"] == assessment_id])


def installments_of(schedule_id):
    rows = [i for i in db.installments.values()
            if i["payment_schedule_id"] == schedule_id]
    rows.sort(key=lambda r: r["sequence_number"])
    return rows


def reviews_of(assessment_id):
    return by_seq([r for r in db.review_requests.values()
                   if r["liability_assessment_id"] == assessment_id])


def arbitrations_of(assessment_id):
    return by_seq([a for a in db.arbitrations.values()
                   if a["liability_assessment_id"] == assessment_id])


# --------------------------------------------------------------------------
# ControlledGroup derived figures (§3.9)
# --------------------------------------------------------------------------

def group_derived(group):
    joint = sum(e["outstanding_liability_cents"] for e in db.employers.values()
                if e["controlled_group_id"] == group["id"]
                and e["status"] in WITHDRAWN_EMPLOYER_STATUSES)
    joint += group.get("_successor_extra_cents", 0)

    clock_year = now().year
    contingent = 0
    bonded = False
    for txn in db.transactions.values():
        if (txn["buyer_controlled_group_id"] == group["id"]
                and txn["exemption_status"] == "EXEMPT_4204"
                and txn["bond_period_end_plan_year"] is not None
                and txn["bond_period_end_plan_year"] >= clock_year):
            contingent += txn["required_bond_cents"]
            bonded = True

    # variant selection: most recently adjudicated transaction of the group
    adjudicated = [t for t in db.transactions.values()
                   if t["buyer_controlled_group_id"] == group["id"]
                   and t["adjudicated_at"] is not None]
    adjudicated.sort(key=lambda t: (-t["adjudicated_at"].timestamp(), -t["_seq"]))
    variant = "SELLER_CONTINUING"
    if adjudicated:
        head = adjudicated[0]
        if head["exemption_status"] == "EXEMPT_4204":
            variant = "SELLER_CONTINUING"
        elif head["successor_determination"] == "SUCCESSOR_LIABLE":
            variant = "SUCCESSOR_ASSUMPTION"

    if variant == "SELLER_CONTINUING":
        raw = (Decimal(joint) + calc.CONTINGENT_EXPOSURE_WEIGHT_4204 * Decimal(contingent))
    else:
        raw = Decimal(joint) + Decimal(contingent)
    score = float(calc.rhu_dec(raw / calc.EXPOSURE_SCALE_CENTS, 4))

    return {
        "bond_posture": "BONDED" if bonded else "UNBONDED",
        "joint_exposure_cents": joint,
        "contingent_exposure_cents": contingent,
        "exposure_score": score,
    }


def recompute_group(group):
    if group is None:
        return
    apply_changes(group, group_derived(group))


def recompute_group_of(employer):
    if employer is None:
        return
    recompute_group(db.controlled_groups.get(employer["controlled_group_id"]))


# --------------------------------------------------------------------------
# Employer derived figures
# --------------------------------------------------------------------------

def employer_outstanding_formula(employer):
    total = 0
    for assessment in assessments_of_employer(employer["id"]):
        for schedule in schedules_of(assessment["id"]):
            if schedule["status"] not in LIVE_SCHEDULE_STATUSES:
                continue
            for inst in installments_of(schedule["id"]):
                if inst["status"] in OPEN_INSTALLMENT_STATUSES:
                    total += inst["principal_cents"]
    return total


def employer_credit_watch(employer):
    for assessment in assessments_of_employer(employer["id"]):
        if assessment["collection_status"] in ("DELINQUENT", "DEFAULTED", "ACCELERATED"):
            return True
    return False


def recompute_employer(employer, outstanding_override=None):
    if employer is None:
        return
    changes = {"credit_watch": employer_credit_watch(employer)}
    if outstanding_override is not None:
        changes["outstanding_liability_cents"] = outstanding_override
    else:
        accelerated = any(a["collection_status"] == "ACCELERATED"
                          for a in assessments_of_employer(employer["id"]))
        if not accelerated:
            changes["outstanding_liability_cents"] = employer_outstanding_formula(employer)
    apply_changes(employer, changes)
    recompute_group_of(employer)


# --------------------------------------------------------------------------
# LiabilityAssessment derived dimensions
# --------------------------------------------------------------------------

def projected_collection_status(assessment):
    candidates = [s for s in schedules_of(assessment["id"])
                  if s["status"] in ("ACTIVE", "DEFAULT_ELIGIBLE", "NOTICED",
                                     "ACCELERATED", "SATISFIED")]
    if not candidates:
        return "NOT_YET_DUE"
    candidates.sort(key=lambda s: (-s["generation_seq"], -s["_seq"]))
    schedule = candidates[0]
    if schedule["status"] == "ACCELERATED":
        return "ACCELERATED"
    if schedule["status"] == "NOTICED":
        return "DEFAULTED"
    if schedule["status"] == "SATISFIED":
        return "SATISFIED"
    rows = installments_of(schedule["id"])
    if any(i["status"] == "DELINQUENT" for i in rows):
        return "DELINQUENT"
    if any(i["status"] == "PAID" for i in rows):
        return "CURRENT"
    return "NOT_YET_DUE"


def active_generation(assessment):
    for schedule in schedules_of(assessment["id"]):
        if schedule["status"] in LIVE_SCHEDULE_STATUSES:
            return schedule["generation_seq"]
    return 0


def recompute_assessment(assessment, cascade=True):
    if not schedules_of(assessment["id"]):
        # No generation was ever minted (degenerate zero-net issuance): the
        # projection has no input and must not overwrite the stamped value.
        return
    apply_changes(assessment, {
        "collection_status": projected_collection_status(assessment),
        "active_schedule_generation": active_generation(assessment),
    })
    if cascade:
        recompute_employer(employer_of_assessment(assessment))


def live_schedule(assessment):
    for schedule in schedules_of(assessment["id"]):
        if schedule["status"] in LIVE_SCHEDULE_STATUSES:
            return schedule
    return None


# --------------------------------------------------------------------------
# generation minting (§3.6)
# --------------------------------------------------------------------------

def applied_credit_for(assessment):
    total = 0
    for schedule in schedules_of(assessment["id"]):
        for inst in installments_of(schedule["id"]):
            total += inst["amount_paid_cents"]
    return total


def check_amortizable(plan, net_assessed_cents, annual_payment_cents, rate_bps,
                      applied_credit):
    """Tier-13 dry run: reject before any row is mutated."""
    figures = calc.build_amortization(net_assessed_cents, annual_payment_cents,
                                      rate_bps, applied_credit,
                                      plan["mass_withdrawal_declared"])
    if figures is None:
        fail("ERR_UNAMORTIZABLE_ASSESSMENT")


def mint_generation(assessment, source, generation_seq, rate_bps, applied_credit):
    plan = plan_of_assessment(assessment)
    figures = calc.build_amortization(
        assessment["net_assessed_cents"], assessment["annual_payment_cents"],
        rate_bps, applied_credit, plan["mass_withdrawal_declared"])
    if figures is None:
        fail("ERR_UNAMORTIZABLE_ASSESSMENT")

    schedule = new_row(db.schedules, {
        "liability_assessment_id": assessment["id"],
        "generation_seq": generation_seq,
        "source": source,
        "interest_rate_bps": figures["interest_rate_bps"],
        "annual_payment_cents": figures["annual_payment_cents"],
        "applied_credit_cents": figures["applied_credit_cents"],
        "amortization_basis_cents": figures["amortization_basis_cents"],
        "forgiven_by_cap_cents": figures["forgiven_by_cap_cents"],
        "capped_basis_cents": figures["capped_basis_cents"],
        "amortization_years": figures["amortization_years"],
        "installment_count": figures["installment_count"],
        "quarterly_installment_cents": figures["quarterly_installment_cents"],
        "final_installment_cents": figures["final_installment_cents"],
        "first_due_date": figures["first_due_date"],
        "consecutive_delinquent_count": 0,
        "default_notice_issued_at": None,
        "cure_deadline_at": None,
        "accelerated_balance_cents": 0,
        "refund_due_cents": 0,
        "status": "ACTIVE",
    })
    for spec in figures["installments"]:
        new_row(db.installments, {
            "payment_schedule_id": schedule["id"],
            "sequence_number": spec["sequence_number"],
            "due_date": spec["due_date"],
            "principal_cents": spec["principal_cents"],
            "amount_due_cents": spec["principal_cents"],
            "amount_paid_cents": 0,
            "delinquent_on": spec["delinquent_on"],
            "paid_at": None,
            "status": "SCHEDULED",
        })
    return schedule


def sustained_interest_rate(assessment):
    """The proposed rate to substitute when an INTEREST_RATE challenge was sustained."""
    for review in reviews_of(assessment["id"]):
        if (review["challenged_assumption"] != "INTEREST_RATE"
                or review["proposed_interest_rate_bps"] is None):
            continue
        if review["assumption_ruling"] == "SUSTAINED":
            return review["proposed_interest_rate_bps"]
        for arb in arbitrations_of(assessment["id"]):
            if arb["assumption_ruling"] == "SUSTAINED":
                return review["proposed_interest_rate_bps"]
    return None


def regenerate(assessment, source, conceded_net):
    """The five-link regeneration cascade of §3.8."""
    # link 1: award_adjustment rises so net equals the conceded amount
    adjustment = (assessment["gross_allocated_cents"]
                  - assessment["de_minimis_reduction_cents"] - conceded_net)
    if adjustment < assessment["award_adjustment_cents"]:
        adjustment = assessment["award_adjustment_cents"]
    assessment["award_adjustment_cents"] = adjustment
    assessment["net_assessed_cents"] = calc.net_assessed(
        assessment["gross_allocated_cents"],
        assessment["de_minimis_reduction_cents"], adjustment)

    substituted = sustained_interest_rate(assessment)
    if substituted is not None:
        assessment["interest_rate_bps_applied"] = substituted
    rate_bps = assessment["interest_rate_bps_applied"]
    touch(assessment)

    # link 2: supersede the incumbent generation and mint the successor
    incumbent = live_schedule(assessment)
    generations = schedules_of(assessment["id"])
    next_seq = max([s["generation_seq"] for s in generations] or [0]) + 1
    applied_credit = applied_credit_for(assessment)
    if incumbent is not None:
        apply_changes(incumbent, {"status": "SUPERSEDED"})

    schedule = mint_generation(assessment, source, next_seq, rate_bps, applied_credit)

    # link 3: void the incumbent's still-open installments
    if incumbent is not None:
        for inst in installments_of(incumbent["id"]):
            if inst["status"] in OPEN_INSTALLMENT_STATUSES:
                apply_changes(inst, {"status": "VOID"})

    # links 4 and 5: employer balance then controlled-group exposure
    apply_changes(assessment, {
        "collection_status": projected_collection_status(assessment),
        "active_schedule_generation": active_generation(assessment),
    })
    recompute_employer(employer_of_assessment(assessment),
                       outstanding_override=schedule["capped_basis_cents"])
    return schedule


def rescind(assessment, arbitration, review):
    """The five-link rescission cascade of §3.8 (VACATE)."""
    employer = employer_of_assessment(assessment)
    event = db.withdrawal_events.get(assessment["withdrawal_event_id"])

    # link 1 / 2: void the live generation and its open installments
    incumbent = live_schedule(assessment)
    if incumbent is not None:
        refund = sum(i["amount_paid_cents"] for i in installments_of(incumbent["id"]))
        apply_changes(incumbent, {"status": "VOID", "refund_due_cents": refund})
        for inst in installments_of(incumbent["id"]):
            if inst["status"] in OPEN_INSTALLMENT_STATUSES:
                apply_changes(inst, {"status": "VOID"})

    apply_changes(assessment, {
        "lifecycle_status": "RESCINDED",
        "review_status": "ARBITRATED",
        "collection_status": "NOT_YET_DUE",
        "active_schedule_generation": 0,
    })

    # links 3 / 4: employer balance to zero and status back to CONTRIBUTING
    if employer is not None:
        apply_changes(employer, {
            "outstanding_liability_cents": 0,
            "status": "CONTRIBUTING",
            "obligation_end_year": None,
            "ceased_cba_count": 0,
            "credit_watch": False,
        })

    # withdrawal event unwinds
    if event is not None:
        apply_changes(event, {
            "status": "NO_WITHDRAWAL",
            "determined_type": "NONE",
            "partial_withdrawal_fraction": 0.0,
        })

    # any still-pending request for review is withdrawn
    for row in reviews_of(assessment["id"]):
        if row["status"] == "PENDING":
            apply_changes(row, {"status": "WITHDRAWN"})

    # a sustained UVB_POOL_ALLOCATION challenge voids the overlapping history
    if (review is not None
            and review["challenged_assumption"] == "UVB_POOL_ALLOCATION"
            and arbitration["assumption_ruling"] == "SUSTAINED"
            and employer is not None):
        anchor = db.valuations.get(assessment.get("valuation_id"))
        if anchor is not None:
            year = anchor["plan_year"]
            for rec in by_seq(list(db.contribution_records.values())):
                if (rec["employer_id"] == employer["id"]
                        and rec["status"] == "CERTIFIED"
                        and rec["plan_year_start"] <= year <= rec["plan_year_end"]):
                    apply_changes(rec, {"status": "VOID"})
                    touch(employer)

    # link 5: controlled-group exposure
    recompute_group_of(employer)


# --------------------------------------------------------------------------
# the sweep (§3.7 / §3.8)
# --------------------------------------------------------------------------

def run_sweep(plan):
    clock = now()
    counters = {
        "installments_marked_due": 0,
        "installments_marked_delinquent": 0,
        "schedules_default_eligible": 0,
        "review_requests_deemed_denied": 0,
        "assessments_finalized": 0,
    }
    assessments = assessments_of_plan(plan["id"])
    touched_employers = {}

    for assessment in assessments:
        for schedule in schedules_of(assessment["id"]):
            if schedule["status"] not in LIVE_SCHEDULE_STATUSES:
                continue
            employer = employer_of_assessment(assessment)
            newly_delinquent = 0
            for inst in installments_of(schedule["id"]):
                if inst["status"] == "SCHEDULED" and inst["due_date"] <= clock:
                    apply_changes(inst, {"status": "DUE"})
                    counters["installments_marked_due"] += 1
                if inst["status"] == "DUE" and inst["delinquent_on"] <= clock:
                    apply_changes(inst, {"status": "DELINQUENT"})
                    counters["installments_marked_delinquent"] += 1
                    newly_delinquent += 1
            if newly_delinquent:
                apply_changes(schedule, {
                    "consecutive_delinquent_count":
                        schedule["consecutive_delinquent_count"] + newly_delinquent,
                })
                if employer is not None:
                    apply_changes(employer, {
                        "delinquency_strikes":
                            employer["delinquency_strikes"] + newly_delinquent,
                    })
            if (schedule["status"] == "ACTIVE"
                    and schedule["consecutive_delinquent_count"]
                    >= calc.DEFAULT_ELIGIBLE_DELINQUENT_COUNT):
                apply_changes(schedule, {"status": "DEFAULT_ELIGIBLE"})
                counters["schedules_default_eligible"] += 1
            if employer is not None:
                touched_employers[employer["id"]] = employer

    for assessment in assessments:
        recompute_assessment(assessment, cascade=False)
    for employer in touched_employers.values():
        recompute_employer(employer)

    # deem undecided requests for review denied
    for assessment in assessments:
        for review in reviews_of(assessment["id"]):
            if (review["status"] == "PENDING"
                    and review["plan_response_deadline_at"] <= clock):
                review["status"] = "DEEMED_DENIED"
                review["arbitration_deadline_at"] = calc.arbitration_deadline(review)
                touch(review)
                counters["review_requests_deemed_denied"] += 1
                apply_changes(assessment, {"review_status": "DECIDED"})

    # finalise assessments whose dispute avenues have closed
    for assessment in assessments:
        if assessment["lifecycle_status"] != "ISSUED":
            continue
        if should_finalize(assessment, clock):
            apply_changes(assessment, {"lifecycle_status": "FINAL"})
            counters["assessments_finalized"] += 1

    return counters


def should_finalize(assessment, clock):
    review_status = assessment["review_status"]
    if review_status == "NONE":
        deadline = assessment["review_deadline_at"]
        return deadline is not None and clock > deadline
    if review_status == "ARBITRATED":
        for arb in arbitrations_of(assessment["id"]):
            if arb["status"] == "CLOSED":
                return True
        return False
    if review_status == "DECIDED":
        if arbitrations_of(assessment["id"]):
            return False
        for review in reviews_of(assessment["id"]):
            deadline = review["arbitration_deadline_at"]
            if deadline is not None and clock > deadline:
                return True
        return False
    return False


# --------------------------------------------------------------------------
# ownership (tier 6)
# --------------------------------------------------------------------------

def require_owner(ctx, employer):
    if ctx.role != "EmployerRepresentative":
        return
    if employer is None or ctx.user_id != employer["id"]:
        fail("ERR_NOT_RESOURCE_OWNER")


# --------------------------------------------------------------------------
# assessment state guard shared by four operations (§3.8)
# --------------------------------------------------------------------------

def require_issued(assessment):
    status = assessment["lifecycle_status"]
    if status == "ISSUED":
        return
    if status == "RESCINDED":
        fail("ERR_ASSESSMENT_RESCINDED")
    fail("ERR_ASSESSMENT_NOT_ISSUED")


def review_deadlines(review):
    review["plan_response_deadline_at"] = add_days(
        review["filed_at"], calc.PLAN_RESPONSE_WINDOW_DAYS)
    review["arbitration_deadline_at"] = calc.arbitration_deadline(review)
