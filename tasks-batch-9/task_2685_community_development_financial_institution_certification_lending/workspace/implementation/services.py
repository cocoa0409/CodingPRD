"""Derived figures, cascades and cross-entity bookkeeping."""
from decimal import Decimal

import calc
from errors import fail
from numeric import rhu
from store import db, fmt_dt, now, ordered, touch

LIVE_BUCKETS = ("CURRENT", "DELINQUENT_30", "DELINQUENT_60", "DELINQUENT_90")
GOAL_AWARD_STATES = ("AWARDED", "DISBURSING", "DRAW_SUSPENDED")
TEST_FIELDS = (
    "test_primary_mission_state",
    "test_financing_entity_state",
    "test_target_market_state",
    "test_development_services_state",
    "test_accountability_state",
    "test_non_government_state",
)


# --------------------------------------------------------------------------- #
# collection helpers
# --------------------------------------------------------------------------- #
def institution_loans(institution_id):
    return ordered([l for l in db.loans.values()
                    if l["institution_id"] == institution_id])


def institution_seats(institution_id):
    return ordered([s for s in db.board_seats.values()
                    if s["institution_id"] == institution_id])


def institution_markets(institution_id):
    return ordered([m for m in db.target_markets.values()
                    if m["institution_id"] == institution_id])


def award_commitments(award_id):
    return ordered([c for c in db.commitments.values()
                    if c["award_application_id"] == award_id])


def institution_awards(institution_id):
    return ordered([a for a in db.awards.values()
                    if a["institution_id"] == institution_id])


def has_approved_market(institution_id):
    return any(m["state"] == "APPROVED" for m in db.target_markets.values()
               if m["institution_id"] == institution_id)


# --------------------------------------------------------------------------- #
# accountability (PRD 3.1)
# --------------------------------------------------------------------------- #
def _represents_approved(seat):
    if not seat.get("represents_target_market"):
        return False
    market = db.target_markets.get(seat.get("target_market_id"))
    return market is not None and market["state"] == "APPROVED"


def recompute_accountability(inst):
    """Recompute accountability_score / accountability_satisfied in place.

    Counted over ACTIVE seats only; RESIGNED seats leave numerator and
    denominator entirely."""
    gov_total = gov_rep = adv_total = adv_rep = 0
    for seat in db.board_seats.values():
        if seat["institution_id"] != inst["id"] or seat["status"] != "ACTIVE":
            continue
        representing = _represents_approved(seat)
        if seat["structure"] == "GOVERNING_BOARD":
            gov_total += 1
            gov_rep += 1 if representing else 0
        elif seat["structure"] == "ADVISORY_BOARD":
            adv_total += 1
            adv_rep += 1 if representing else 0
    score, satisfied = calc.accountability_score(gov_total, gov_rep,
                                                 adv_total, adv_rep)
    inst["accountability_score"] = score
    inst["accountability_satisfied"] = satisfied
    return satisfied


def accountability_failure_cascade(inst):
    """Head of the accountability cascade: a resignation that flips
    accountability_satisfied true -> false knocks in-flight dockets out of
    review (PRD 3.1)."""
    for app in ordered([a for a in db.cert_apps.values()
                        if a["institution_id"] == inst["id"]
                        and a["state"] == "UNDER_REVIEW"]):
        app["test_accountability_state"] = "FAILED"
        if app["revision_round"] < 2:
            app["state"] = "INFO_REQUESTED"
            app["revision_round"] = app["revision_round"] + 1
            app["info_requested_reason"] = "ACCOUNTABILITY_TEST_FAILED"
        touch(app)


# --------------------------------------------------------------------------- #
# borrower target-market attribution (PRD 3.3)
# --------------------------------------------------------------------------- #
def reattribute_borrower(borrower):
    if borrower["geocode_state"] != "GEOCODED":
        borrower["in_target_market"] = False
        borrower["matched_target_market_type"] = None
        return
    candidates = [m for m in institution_markets(borrower["institution_id"])
                  if m["state"] == "APPROVED"]
    candidates.sort(key=lambda m: (calc.MARKET_TYPE_PRECEDENCE.get(
        m["market_type"], 99), m["created_at"], m["_seq"]))
    for market in candidates:
        if calc.attribution_predicate(market, borrower):
            borrower["in_target_market"] = True
            borrower["matched_target_market_type"] = market["market_type"]
            return
    borrower["in_target_market"] = False
    borrower["matched_target_market_type"] = None


# --------------------------------------------------------------------------- #
# coaching hours (PRD 3.4)
# --------------------------------------------------------------------------- #
def recompute_ta_hours(borrower):
    total = Decimal("0.00")
    for eng in db.ta_engagements.values():
        if eng["borrower_id"] == borrower["id"] and eng["state"] == "COMPLETED":
            total = total + Decimal(eng["actual_hours"])
    total = rhu(total, 2)
    if borrower["ta_hours_total"] != total:
        borrower["ta_hours_total"] = total
        touch(borrower)


def ta_prerequisite_met(borrower_id):
    for eng in db.ta_engagements.values():
        if (eng["borrower_id"] == borrower_id
                and eng["state"] == "COMPLETED"
                and eng["competency_verified"]):
            return True
    return False


# --------------------------------------------------------------------------- #
# product committed principal (PRD 3.4)
# --------------------------------------------------------------------------- #
def recompute_committed_principal(product):
    total = 0
    for loan in db.loans.values():
        if (loan["product_id"] == product["id"]
                and loan["underwriting_state"] in ("APPROVED", "CLOSED")
                and loan["approved_principal_cents"] is not None):
            total += loan["approved_principal_cents"]
    if product["committed_principal_cents"] != total:
        product["committed_principal_cents"] = total
        touch(product)


# --------------------------------------------------------------------------- #
# reserve adequacy, posture and the draw-suspension cascade (PRD 2.11 / 3.6)
# --------------------------------------------------------------------------- #
def recompute_portfolio(inst):
    outstanding = 0
    disbursed = 0
    for loan in db.loans.values():
        if loan["institution_id"] != inst["id"]:
            continue
        outstanding += loan["principal_outstanding_cents"]
        disbursed += loan["principal_disbursed_cents"]
    inst["portfolio_principal_outstanding_cents"] = outstanding
    inst["portfolio_principal_disbursed_cents"] = disbursed


def recompute_reserve(inst, floor_probation=False):
    """Recompute both reserve variants, the selected figure, the coverage ratio
    and the posture, then cascade a fresh PROBATION onto awards and pledges.

    Callers are the four balance-moving operations: disbursement, payment, the
    servicing checkpoint and charge-off."""
    loans = institution_loans(inst["id"])
    recompute_portfolio(inst)
    migration = calc.migration_reserve(loans)
    static = calc.static_pool_reserve(loans, now().year)
    inst["loss_reserve_required_migration_cents"] = migration
    inst["loss_reserve_required_static_cents"] = static
    required = static if inst["reserve_method"] == "STATIC_POOL" else migration
    inst["loss_reserve_required_cents"] = required
    ratio = calc.coverage_ratio(inst["loss_reserve_balance_cents"], required)
    inst["reserve_coverage_ratio"] = ratio
    previous = inst["compliance_posture"]
    posture = calc.posture_for(ratio)
    if floor_probation and ratio < calc.POSTURE_WATCH_MIN_RATIO:
        posture = "PROBATION"
    inst["compliance_posture"] = posture
    if posture == "PROBATION" and previous != "PROBATION":
        suspend_draws(inst)


def suspend_draws(inst):
    """Third and fourth cascade links: probation suspends every open draw
    window, and each suspension freezes that award's still-pledged sources."""
    for award in institution_awards(inst["id"]):
        if award["state"] != "DISBURSING":
            continue
        award["state"] = "DRAW_SUSPENDED"
        award["suspension_reason"] = "POSTURE_PROBATION"
        touch(award)
        for commitment in award_commitments(award["id"]):
            if commitment["status"] == "PLEDGED":
                commitment["status"] = "HELD"
                touch(commitment)


def resume_draws(award):
    """Explicit lift of a suspension: held sources return to pledged."""
    award["state"] = "DISBURSING"
    award["suspension_reason"] = None
    touch(award)
    for commitment in award_commitments(award["id"]):
        if commitment["status"] == "HELD":
            commitment["status"] = "PLEDGED"
            touch(commitment)


# --------------------------------------------------------------------------- #
# impact ledger (PRD 3.7)
# --------------------------------------------------------------------------- #
COUNTER_FIELDS = (
    ("jobs_created", "jobs_created_total"),
    ("jobs_retained", "jobs_retained_total"),
    ("housing_units", "housing_units_total"),
    ("businesses_financed", "businesses_financed_total"),
)


def apply_impact_counts(inst, report, sign):
    for source, target in COUNTER_FIELDS:
        inst[target] = inst[target] + sign * report[source]
    refresh_award_goals(inst)


def refresh_award_goals(inst):
    """Every award of the institution in AWARDED, DISBURSING or DRAW_SUSPENDED
    re-derives goal_attainment_pct off the refreshed ledger."""
    for award in institution_awards(inst["id"]):
        if award["state"] not in GOAL_AWARD_STATES:
            continue
        value = calc.goal_attainment_pct(
            inst["jobs_created_total"], inst["housing_units_total"],
            award["performance_goal_jobs"],
            award["performance_goal_housing_units"])
        if award["goal_attainment_pct"] != value:
            award["goal_attainment_pct"] = value
            touch(award)


# --------------------------------------------------------------------------- #
# match ledger (PRD 3.9)
# --------------------------------------------------------------------------- #
def recompute_match_ledger(award):
    eligible = 0
    for commitment in award_commitments(award["id"]):
        if commitment["status"] == "VERIFIED":
            eligible += commitment["eligible_cents"]
    award["match_eligible_cents"] = eligible
    shortfall = award["required_match_cents"] - eligible
    award["match_shortfall_cents"] = shortfall if shortfall > 0 else 0


# --------------------------------------------------------------------------- #
# recertification (PRD 3.8)
# --------------------------------------------------------------------------- #
def apply_measurement_verdict(inst, measurement):
    from datetime import timedelta

    from store import parse_dt

    if measurement["verdict"] == "PASS":
        end = parse_dt(measurement["period_end"])
        inst["recertification_due_at"] = fmt_dt(
            end + timedelta(days=calc.RECERTIFICATION_INTERVAL_DAYS))
        if inst["certification_state"] == "RECERT_DUE":
            inst["certification_state"] = "CERTIFIED"
    elif measurement["verdict"] == "FAIL":
        if inst["certification_state"] == "RECERT_DUE":
            inst["certification_state"] = "DECERTIFIED"


# --------------------------------------------------------------------------- #
# existence-band lookups
# --------------------------------------------------------------------------- #
def get_institution(institution_id):
    inst = db.institutions.get(institution_id)
    if inst is None:
        fail("ERR_INSTITUTION_NOT_FOUND")
    return inst


def get_cert_app(application_id):
    app = db.cert_apps.get(application_id)
    if app is None:
        fail("ERR_APPLICATION_NOT_FOUND")
    return app


def get_market(target_market_id, institution_id=None):
    market = db.target_markets.get(target_market_id)
    if market is None:
        fail("ERR_TARGET_MARKET_NOT_FOUND")
    if institution_id is not None and market["institution_id"] != institution_id:
        fail("ERR_TARGET_MARKET_NOT_FOUND")
    return market


def get_seat(board_seat_id):
    seat = db.board_seats.get(board_seat_id)
    if seat is None:
        fail("ERR_BOARD_SEAT_NOT_FOUND")
    return seat


def get_borrower(borrower_id, institution_id=None):
    borrower = db.borrowers.get(borrower_id)
    if borrower is None:
        fail("ERR_BORROWER_NOT_FOUND")
    if institution_id is not None and borrower["institution_id"] != institution_id:
        fail("ERR_BORROWER_NOT_FOUND")
    return borrower


def get_product(product_id, institution_id=None):
    product = db.loan_products.get(product_id)
    if product is None:
        fail("ERR_LOAN_PRODUCT_NOT_FOUND")
    if institution_id is not None and product["institution_id"] != institution_id:
        fail("ERR_LOAN_PRODUCT_NOT_FOUND")
    return product


def get_loan(loan_id):
    loan = db.loans.get(loan_id)
    if loan is None:
        fail("ERR_LOAN_NOT_FOUND")
    return loan


def get_engagement(engagement_id):
    eng = db.ta_engagements.get(engagement_id)
    if eng is None:
        fail("ERR_TA_ENGAGEMENT_NOT_FOUND")
    return eng


def get_report(impact_report_id):
    report = db.impact_reports.get(impact_report_id)
    if report is None:
        fail("ERR_IMPACT_REPORT_NOT_FOUND")
    return report


def get_measurement(measurement_id):
    row = db.measurements.get(measurement_id)
    if row is None:
        fail("ERR_MEASUREMENT_NOT_FOUND")
    return row


def get_award(award_id):
    award = db.awards.get(award_id)
    if award is None:
        fail("ERR_AWARD_NOT_FOUND")
    return award


def get_commitment(commitment_id):
    row = db.commitments.get(commitment_id)
    if row is None:
        fail("ERR_COMMITMENT_NOT_FOUND")
    return row


def report_institution(report):
    loan = db.loans.get(report["loan_id"])
    if loan is None:
        return None
    return db.institutions.get(loan["institution_id"])
