"""Asset recovery: loss assessments and the chargeback ledger, cross-brand
reconciliation claims, return incentives and theft investigations."""
from flask import Blueprint

import clock
import db
import middleware
import response
import util
from errors import fail
from services import calc, recompute, view

bp = Blueprint("recovery", __name__)

CAUSES = ("LOST_IN_TRADE", "DAMAGED_BEYOND_REPAIR", "NOT_RETURNED_DWELL",
          "STOLEN_SUSPECTED")
BASES = ("REPLACEMENT_COST", "DEPRECIATED_BOOK")
RESOLUTIONS = ("UPHELD", "WAIVED")
CHARGEBACK_ACTIONS = ("SETTLE", "REVERSE")
CLAIM_RESPONSES = ("COUNTER", "AGREE", "REJECT", "WITHDRAW")
LIVE_CLAIM_STATES = ("SUBMITTED", "COUNTERED")
TERMINAL_CLAIM_STATES = ("AGREED", "REJECTED", "WITHDRAWN")
INVESTIGATION_ACTIONS = ("EVIDENCE_HOLD", "RESUME", "CLOSE")
OUTCOMES = ("RECOVERED", "WRITTEN_OFF")
WRITE_OFF_TARGET = {
    "LOST_IN_TRADE": ("LOST", ("FILLED", "IN_TRADE", "AT_RETAIL")),
    "NOT_RETURNED_DWELL": ("LOST", ("FILLED", "IN_TRADE", "AT_RETAIL")),
    "DAMAGED_BEYOND_REPAIR": ("SCRAPPED", ("QUARANTINED",)),
    "STOLEN_SUSPECTED": (None, ()),
}


def _live_assessments(keg_id, exclude_id=None):
    return [row for row in db.assessments.values()
            if row["keg_id"] == keg_id and row["id"] != exclude_id
            and row["assessment_status"] in ("PROPOSED", "DISPUTED")]


def _keg_dwell_at(keg):
    """Whichever accountability clock is open on the keg; the brewer clock
    wins when both are running."""
    if keg["dwell_started_at"] is not None:
        return calc.brewer_spell_days(keg)
    if keg["distributor_custody_started_at"] is not None:
        return calc.distributor_spell_days(keg)
    return 0


# ---------------------------------------------------- loss assessments -------


@bp.post("/loss-assessments")
def create_assessment():
    actor = middleware.authenticate("AssetRecoveryAnalyst")
    payload = util.body()
    util.forbid_version_fields(payload, allowed="expected_keg_version")
    keg_id = util.req_string(payload, "keg_id")
    cause = util.req_enum(payload, "cause", CAUSES)
    expected_version = util.req_int(payload, "expected_keg_version")
    basis = util.opt_enum(payload, "assessment_basis", BASES)
    investigation_id = util.opt_string(payload, "theft_investigation_id")
    keg = db.kegs.get(keg_id)
    if keg is None:
        fail("ERR_KEG_NOT_FOUND")
    if investigation_id is not None \
            and investigation_id not in db.investigations:
        fail("ERR_INVESTIGATION_NOT_FOUND")
    if expected_version != keg["version"]:
        fail("ERR_STALE_KEG_VERSION",
             "expected_keg_version does not match the keg's current version.")
    brewer_id = keg["filling_brewer_id"] or keg["current_brewer_id"]
    if brewer_id is None and cause != "STOLEN_SUSPECTED":
        fail("ERR_NO_CHARGEABLE_PARTY",
             "The keg names no brewer to charge.")
    index_row = calc.effective_index()
    if index_row is None:
        fail("ERR_NO_COMMODITY_INDEX",
             "No commodity index row is effective on the valuation date.")
    live = _live_assessments(keg["id"])
    if any(row["assessment_status"] == "DISPUTED" for row in live):
        fail("ERR_ASSESSMENT_ALREADY_OPEN",
             "A disputed assessment on this keg blocks a new one.")
    stored_basis = calc.coerce_basis(basis, keg, cause)
    pool = db.pools.get(keg["pool_id"])
    scrap = calc.scrap_value_for_pool(pool, index_row) if pool else 0
    valuation = calc.loss_value(pool, keg, cause, stored_basis, scrap)
    for prior in live:
        prior["assessment_status"] = "SUPERSEDED"
        util.bump(prior)
    assessment = util.common_fields()
    assessment.update({
        "keg_id": keg["id"],
        "brewer_id": brewer_id,
        "commodity_index_id": index_row["id"],
        "theft_investigation_id": investigation_id,
        "cause": cause,
        "assessment_basis": stored_basis,
        "dwell_days_at_assessment": _keg_dwell_at(keg),
        "assessment_status": "PROPOSED",
        "chargeback_status": "NONE",
        "settled_amount_cents": None,
        "created_by_user_id": actor.user_id,
        "resolved_by_user_id": None,
        "dispute_reason": None,
        "resolution_notes": None,
    })
    assessment.update(valuation)
    db.assessments[assessment["id"]] = assessment
    keg["assessment_open"] = True
    util.bump(keg)
    return response.created(assessment)


@bp.post("/loss-assessments/<assessment_id>/dispute")
def dispute_assessment(assessment_id):
    actor = middleware.authenticate("Brewer")
    payload = util.body()
    util.forbid_version_fields(payload)
    reason = util.req_string(payload, "dispute_reason", 1, 500)
    assessment = db.assessments.get(assessment_id)
    if assessment is None:
        fail("ERR_ASSESSMENT_NOT_FOUND")
    middleware.owner_check(actor, assessment["brewer_id"])
    if assessment["assessment_status"] in ("UPHELD", "WAIVED", "SUPERSEDED"):
        fail("ERR_ALREADY_TERMINAL",
             "This assessment has already been adjudicated.")
    if assessment["assessment_status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "Only a PROPOSED assessment may be disputed.")
    assessment["assessment_status"] = "DISPUTED"
    assessment["dispute_reason"] = reason
    util.bump(assessment)
    return response.ok(assessment)


@bp.post("/loss-assessments/<assessment_id>/resolve")
def resolve_assessment(assessment_id):
    actor = middleware.authenticate("AssetRecoveryAnalyst")
    payload = util.body()
    util.forbid_version_fields(payload)
    resolution = util.req_enum(payload, "resolution", RESOLUTIONS)
    notes = util.opt_string(payload, "resolution_notes", 1, 1000)
    assessment = db.assessments.get(assessment_id)
    if assessment is None:
        fail("ERR_ASSESSMENT_NOT_FOUND")
    if assessment["assessment_status"] in ("UPHELD", "WAIVED", "SUPERSEDED"):
        fail("ERR_ALREADY_TERMINAL",
             "This assessment has already been adjudicated.")
    brewer = db.brewers.get(assessment["brewer_id"])
    if resolution == "UPHELD" and brewer is not None \
            and brewer["status"] == "SUSPENDED":
        fail("ERR_BREWER_SUSPENDED",
             "A suspended brewer's loss may not be upheld.")
    if actor.user_id == assessment["created_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The analyst who raised the loss may not resolve it.")
    keg = db.kegs.get(assessment["keg_id"])
    assessment["assessment_status"] = resolution
    assessment["resolved_by_user_id"] = actor.user_id
    if notes is not None:
        assessment["resolution_notes"] = notes
    if resolution == "WAIVED":
        util.bump(assessment)
        if keg is not None:
            util.apply_changes(keg, {"assessment_open": False})
        return response.ok(assessment)
    # --- the four-link uphold cascade -------------------------------------
    if assessment["net_chargeback_cents"] > 0:
        assessment["chargeback_status"] = "ISSUED"
    util.bump(assessment)
    if keg is not None:
        target, legal_from = WRITE_OFF_TARGET[assessment["cause"]]
        changes = {"assessment_open": False}
        if target is not None and keg["custody_state"] in legal_from:
            changes["custody_state"] = target
            changes["dwell_flag"] = "WITHIN_LIMIT"
        util.apply_changes(keg, changes)
    if brewer is not None:
        recompute.recompute_brewer_balance(brewer)
        recompute.recompute_brewer_loss_counters(brewer)
        recompute.run_probation_gates(brewer)
        recompute.cascade_brewer(brewer)
    if keg is not None:
        recompute.cascade_pool_id(keg["pool_id"])
    return response.ok(assessment)


@bp.post("/loss-assessments/<assessment_id>/chargeback-resolution")
def resolve_chargeback(assessment_id):
    actor = middleware.authenticate("PoolOperator", "AssetRecoveryAnalyst")
    payload = util.body()
    util.forbid_version_fields(payload)
    action = util.req_enum(payload, "action", CHARGEBACK_ACTIONS)
    amount = None
    if action == "SETTLE":
        amount = util.req_int(payload, "amount_cents", minimum=0)
    else:
        amount = util.opt_int(payload, "amount_cents", minimum=0)
    notes = util.opt_string(payload, "resolution_notes", 1, 1000)
    assessment = db.assessments.get(assessment_id)
    if assessment is None:
        fail("ERR_ASSESSMENT_NOT_FOUND")
    # PRD 2.8 step 11 enumerates the terminal dimensions and `chargeback_status`
    # is not among them, so step 10's state check owns every non-ISSUED row.
    if assessment["chargeback_status"] != "ISSUED":
        fail("ERR_INVALID_STATE",
             "Only an ISSUED chargeback may be settled or reversed.")
    if action == "SETTLE" and actor.role != "PoolOperator":
        fail("ERR_SEGREGATION_OF_DUTIES",
             "Settlement is the pool operator's action.")
    if action == "REVERSE" and actor.role != "AssetRecoveryAnalyst":
        fail("ERR_SEGREGATION_OF_DUTIES",
             "Reversal is the recovery analyst's action.")
    if action == "SETTLE" and amount != assessment["net_chargeback_cents"]:
        fail("ERR_SETTLEMENT_AMOUNT_MISMATCH",
             "amount_cents must equal net_chargeback_cents exactly.")
    if notes is not None:
        assessment["resolution_notes"] = notes
    brewer = db.brewers.get(assessment["brewer_id"])
    if action == "SETTLE":
        assessment["chargeback_status"] = "SETTLED"
        assessment["settled_amount_cents"] = amount
        util.bump(assessment)
        if brewer is not None:
            recompute.recompute_brewer_balance(brewer)
            util.bump(brewer)
        return response.ok(assessment)
    assessment["chargeback_status"] = "REVERSED"
    util.bump(assessment)
    if brewer is not None:
        recompute.recompute_brewer_balance(brewer)
        util.bump(brewer)
        recompute.lift_balance_probation(brewer)
        recompute.cascade_brewer(brewer)
    return response.ok(assessment)


@bp.get("/loss-assessments/<assessment_id>")
def read_assessment(assessment_id):
    middleware.authenticate("PoolOperator", "Brewer", "AssetRecoveryAnalyst")
    assessment = db.assessments.get(assessment_id)
    if assessment is None:
        fail("ERR_ASSESSMENT_NOT_FOUND")
    return response.ok(assessment)


@bp.get("/loss-assessments")
def list_assessments():
    middleware.authenticate("PoolOperator", "Brewer", "AssetRecoveryAnalyst")
    limit, offset = middleware.pagination()
    filters = {field: middleware.qparam(field)
               for field in ("keg_id", "brewer_id", "commodity_index_id",
                             "theft_investigation_id", "assessment_status",
                             "chargeback_status", "cause")}
    rows = [row for row in db.assessments.values()
            if all(view.match(row, field, value)
                   for field, value in filters.items())]
    page, total = view.paginate(view.ordered(rows), limit, offset)
    return response.listing(page, limit, offset, total)


# ---------------------------------------------- reconciliation claims --------


def _evidence_scan(keg_id, scanned_at):
    for scan in db.scan_events.values():
        if scan["keg_id"] != keg_id:
            continue
        if not scan["misdelivery_detected"]:
            continue
        if scan["scanned_at"] == scanned_at:
            return scan
    return None


def _brewer_by_brand(brand_code):
    for row in db.brewers.values():
        if row["brand_code"] == brand_code:
            return row
    return None


def _live_claims(keg_id):
    return [row for row in db.claims.values()
            if row["keg_id"] == keg_id and row["status"] in LIVE_CLAIM_STATES]


@bp.post("/reconciliation-claims")
def create_claim():
    actor = middleware.authenticate("Distributor")
    payload = util.body()
    util.forbid_version_fields(payload)
    keg_id = util.req_string(payload, "keg_id")
    brewer_id = util.req_string(payload, "misdelivered_to_brewer_id")
    claimed = util.req_int(payload, "claimed_offset_cents", minimum=1,
                           maximum=50000)
    evidence_at = util.parse_instant(
        util.req_present(payload, "evidence_scanned_at"), "evidence_scanned_at")
    supersedes_id = util.opt_string(payload, "supersedes_claim_id")
    keg = db.kegs.get(keg_id)
    if keg is None:
        fail("ERR_KEG_NOT_FOUND")
    brewer = db.brewers.get(brewer_id)
    if brewer is None:
        fail("ERR_BREWER_NOT_FOUND")
    prior = None
    if supersedes_id is not None:
        prior = db.claims.get(supersedes_id)
        if prior is None:
            fail("ERR_CLAIM_NOT_FOUND")
    scan = _evidence_scan(keg["id"], evidence_at)
    if scan is None or scan["brand_code_scanned"] != brewer["brand_code"]:
        fail("ERR_NO_MISDELIVERY_EVIDENCE",
             "No misdelivery scan on this keg supports the claim.")
    if prior is not None and (prior["keg_id"] != keg["id"]
                              or prior["status"] not in ("REJECTED",
                                                         "WITHDRAWN")):
        fail("ERR_CLAIM_SUPERSEDE_MISMATCH",
             "supersedes_claim_id must name a closed claim on the same keg.")
    if util.elapsed_days(evidence_at, clock.now()) > calc.CLAIM_WINDOW_DAYS:
        fail("ERR_CLAIM_WINDOW_EXPIRED",
             "The %d-day claim window has closed." % calc.CLAIM_WINDOW_DAYS)
    if _live_claims(keg["id"]):
        fail("ERR_CLAIM_ALREADY_OPEN",
             "A live claim on this keg is already under negotiation.")
    claim = util.common_fields()
    claim.update({
        "keg_id": keg["id"],
        "claimant_distributor_id": actor.user_id,
        "owning_brewer_id": keg["filling_brewer_id"],
        "misdelivered_to_brewer_id": brewer["id"],
        "supersedes_claim_id": supersedes_id,
        "evidence_scanned_at": evidence_at,
        "claimed_offset_cents": claimed,
        "counter_offset_cents": None,
        "agreed_offset_cents": None,
        "round_count": 0,
        "status": "SUBMITTED",
        "last_responder_role": "Distributor",
        "closed_at": None,
    })
    db.claims[claim["id"]] = claim
    return response.created(claim)


@bp.post("/reconciliation-claims/<claim_id>/respond")
def respond_claim(claim_id):
    actor = middleware.authenticate("Brewer", "Distributor")
    payload = util.body()
    util.forbid_version_fields(payload, allowed="expected_claim_version")
    answer = util.req_enum(payload, "response", CLAIM_RESPONSES)
    expected_version = util.req_int(payload, "expected_claim_version")
    counter = None
    if answer == "COUNTER":
        counter = util.req_int(payload, "counter_offset_cents", minimum=1,
                               maximum=50000)
    claim = db.claims.get(claim_id)
    if claim is None:
        fail("ERR_CLAIM_NOT_FOUND")
    middleware.owner_check(actor, claim["misdelivered_to_brewer_id"],
                           claim["claimant_distributor_id"])
    if expected_version != claim["version"]:
        fail("ERR_STALE_CLAIM_VERSION",
             "expected_claim_version does not match the claim's version.")
    if claim["status"] in TERMINAL_CLAIM_STATES:
        fail("ERR_ALREADY_TERMINAL", "This claim is already closed.")
    # Which side may record which response from which live state.
    if answer == "REJECT" and actor.role != "Brewer":
        fail("ERR_INVALID_STATE", "Only the brewer may reject a claim.")
    if answer == "WITHDRAW" and actor.role != "Distributor":
        fail("ERR_INVALID_STATE", "Only the claimant may withdraw a claim.")
    if answer == "COUNTER" and claim["status"] == "SUBMITTED" \
            and actor.role != "Brewer":
        fail("ERR_INVALID_STATE",
             "A SUBMITTED claim is countered by the brewer.")
    if answer == "COUNTER" and claim["status"] == "COUNTERED" \
            and actor.role != "Distributor":
        fail("ERR_INVALID_STATE",
             "A COUNTERED claim is countered back by the distributor.")
    if answer == "AGREE" and claim["status"] == "SUBMITTED" \
            and actor.role != "Brewer":
        fail("ERR_INVALID_STATE", "A SUBMITTED claim is agreed by the brewer.")
    if answer == "AGREE" and claim["status"] == "COUNTERED" \
            and actor.role != "Distributor":
        fail("ERR_INVALID_STATE",
             "A COUNTERED claim is agreed by the distributor.")
    if claim["last_responder_role"] == actor.role:
        fail("ERR_RESPONDER_OUT_OF_TURN",
             "The other side of the table must move next.")
    keg = db.kegs.get(claim["keg_id"])
    if answer == "AGREE" and keg is not None \
            and keg["custody_state"] in calc.WRITTEN_OFF_STATES:
        fail("ERR_ALREADY_TERMINAL",
             "A written-off keg cannot be handed back.")
    if answer == "COUNTER" and claim["round_count"] >= calc.MAX_CLAIM_ROUNDS:
        fail("ERR_CLAIM_ROUND_LIMIT",
             "At most %d counters may be recorded." % calc.MAX_CLAIM_ROUNDS)
    if answer == "COUNTER":
        claim["status"] = "COUNTERED" if claim["status"] == "SUBMITTED" \
            else "SUBMITTED"
        claim["counter_offset_cents"] = counter
        claim["round_count"] = claim["round_count"] + 1
        claim["last_responder_role"] = actor.role
        util.bump(claim)
        return response.ok(claim)
    if answer == "AGREE":
        agreed = claim["counter_offset_cents"] \
            if claim["counter_offset_cents"] is not None \
            else claim["claimed_offset_cents"]
        claim["status"] = "AGREED"
        claim["agreed_offset_cents"] = agreed
        claim["closed_at"] = clock.now()
        claim["last_responder_role"] = actor.role
        util.bump(claim)
        accrual = util.common_fields()
        accrual.update({
            "distributor_id": claim["claimant_distributor_id"],
            "keg_id": claim["keg_id"],
            "claim_id": claim["id"],
            "accrual_type": "RECONCILIATION_OFFSET",
            "dwell_days": 0,
            "tier_pct_bp": 0,
            "cooperation_multiplier_bp": 0,
            "incentive_cents": agreed,
            "triggering_scanned_at": None,
            "status": "ACCRUED",
            "paid_at": None,
            "clawback_reason": None,
        })
        db.accruals[accrual["id"]] = accrual
        distributor = db.distributors.get(claim["claimant_distributor_id"])
        if distributor is not None:
            recompute.recompute_distributor_ledger(distributor)
        if keg is not None:
            keg["misdelivery_open"] = False
            util.bump(keg)
        return response.ok(claim)
    claim["status"] = "REJECTED" if answer == "REJECT" else "WITHDRAWN"
    claim["closed_at"] = clock.now()
    claim["last_responder_role"] = actor.role
    util.bump(claim)
    return response.ok(claim)


@bp.get("/reconciliation-claims/<claim_id>")
def read_claim(claim_id):
    middleware.authenticate("PoolOperator", "Brewer", "Distributor",
                            "AssetRecoveryAnalyst")
    claim = db.claims.get(claim_id)
    if claim is None:
        fail("ERR_CLAIM_NOT_FOUND")
    return response.ok(claim)


@bp.get("/reconciliation-claims")
def list_claims():
    middleware.authenticate("PoolOperator", "Brewer", "Distributor",
                            "AssetRecoveryAnalyst")
    limit, offset = middleware.pagination()
    filters = {field: middleware.qparam(field)
               for field in ("keg_id", "claimant_distributor_id",
                             "owning_brewer_id", "misdelivered_to_brewer_id",
                             "supersedes_claim_id", "status")}
    rows = [row for row in db.claims.values()
            if all(view.match(row, field, value)
                   for field, value in filters.items())]
    page, total = view.paginate(view.ordered(rows), limit, offset)
    return response.listing(page, limit, offset, total)


# ------------------------------------------------------ return incentives ----


@bp.get("/return-incentives/<accrual_id>")
def read_accrual(accrual_id):
    actor = middleware.authenticate("PoolOperator", "Distributor",
                                    "AssetRecoveryAnalyst")
    accrual = db.accruals.get(accrual_id)
    if accrual is None:
        fail("ERR_ACCRUAL_NOT_FOUND")
    middleware.owner_check(actor, accrual["distributor_id"])
    return response.ok(accrual)


@bp.get("/return-incentives")
def list_accruals():
    middleware.authenticate("PoolOperator", "Distributor",
                            "AssetRecoveryAnalyst")
    limit, offset = middleware.pagination()
    filters = {field: middleware.qparam(field)
               for field in ("distributor_id", "keg_id", "claim_id",
                             "accrual_type", "status")}
    rows = [row for row in db.accruals.values()
            if all(view.match(row, field, value)
                   for field, value in filters.items())]
    page, total = view.paginate(view.ordered(rows), limit, offset)
    return response.listing(page, limit, offset, total)


@bp.post("/return-incentives/<accrual_id>/pay")
def pay_accrual(accrual_id):
    middleware.authenticate("PoolOperator")
    payload = util.body()
    util.forbid_version_fields(payload)
    paid_at = util.parse_instant(util.req_present(payload, "paid_at"),
                                 "paid_at")
    accrual = db.accruals.get(accrual_id)
    if accrual is None:
        fail("ERR_ACCRUAL_NOT_FOUND")
    distributor = db.distributors.get(accrual["distributor_id"])
    if distributor is not None and distributor["status"] == "SUSPENDED":
        fail("ERR_DISTRIBUTOR_SUSPENDED",
             "A suspended distributor is not paid out.")
    if accrual["status"] != "ACCRUED":
        fail("ERR_ACCRUAL_NOT_PAYABLE",
             "Only an ACCRUED incentive may be paid.")
    accrual["status"] = "PAID"
    accrual["paid_at"] = paid_at
    util.bump(accrual)
    # PAID rows stay inside the ledger sum, so the balance does not move.
    if distributor is not None:
        recompute.recompute_distributor_ledger(distributor)
    return response.ok(accrual)


# ---------------------------------------------------- theft investigations ---


def _attached_kegs(investigation_id):
    return [row for row in db.kegs.values()
            if row["theft_investigation_id"] == investigation_id]


def _refresh_exposure(investigation):
    index_row = calc.effective_index()
    attached = _attached_kegs(investigation["id"])
    exposure = 0
    for keg in attached:
        exposure += calc.keg_scrap_value(keg, index_row)
    investigation["attached_keg_count"] = len(attached)
    investigation["held_keg_count"] = len(
        [keg for keg in attached if keg["custody_state"] == "EVIDENCE_HOLD"])
    investigation["stainless_value_at_risk_cents"] = exposure
    if index_row is not None:
        investigation["commodity_index_id"] = index_row["id"]


@bp.post("/theft-investigations")
def open_investigation():
    actor = middleware.authenticate("AssetRecoveryAnalyst")
    payload = util.body()
    util.forbid_version_fields(payload)
    pool_id = util.req_string(payload, "pool_id")
    reason = util.req_string(payload, "opened_reason", 1, 500)
    keg_ids = util.req_id_list(payload, "keg_ids")
    suspect_id = util.opt_string(payload, "suspect_distributor_id")
    pool = db.pools.get(pool_id)
    if pool is None:
        fail("ERR_POOL_NOT_FOUND")
    kegs = []
    for keg_id in keg_ids:
        keg = db.kegs.get(keg_id)
        # A keg of another pool is reported as missing: the pool named earlier
        # in the same body scopes the list.
        if keg is None or keg["pool_id"] != pool["id"]:
            fail("ERR_KEG_NOT_FOUND")
        kegs.append(keg)
    if suspect_id is not None and suspect_id not in db.distributors:
        fail("ERR_DISTRIBUTOR_NOT_FOUND")
    investigation = util.common_fields()
    investigation.update({
        "pool_id": pool["id"],
        "suspect_distributor_id": suspect_id,
        "commodity_index_id": None,
        "status": "OPEN",
        "held_keg_count": 0,
        "attached_keg_count": 0,
        "stainless_value_at_risk_cents": 0,
        "opened_reason": reason,
        "opened_by_user_id": actor.user_id,
        "hold_started_at": None,
        "closed_at": None,
        "outcome_notes": None,
    })
    db.investigations[investigation["id"]] = investigation
    for keg in kegs:
        keg["theft_investigation_id"] = investigation["id"]
        util.bump(keg)
    _refresh_exposure(investigation)
    return response.created(investigation)


@bp.post("/theft-investigations/<investigation_id>/status")
def drive_investigation(investigation_id):
    middleware.authenticate("AssetRecoveryAnalyst")
    payload = util.body()
    util.forbid_version_fields(payload)
    action = util.req_enum(payload, "action", INVESTIGATION_ACTIONS)
    keg_ids = None
    hold_started_at = None
    outcome = None
    if action == "EVIDENCE_HOLD":
        keg_ids = util.req_id_list(payload, "keg_ids")
        hold_started_at = util.parse_instant(
            util.req_present(payload, "hold_started_at"), "hold_started_at")
    if action == "CLOSE":
        outcome = util.req_enum(payload, "outcome", OUTCOMES)
    notes = util.opt_string(payload, "outcome_notes", 1, 1000)
    investigation = db.investigations.get(investigation_id)
    if investigation is None:
        fail("ERR_INVESTIGATION_NOT_FOUND")
    named = []
    for keg_id in (keg_ids or []):
        keg = db.kegs.get(keg_id)
        if keg is None:
            fail("ERR_KEG_NOT_FOUND")
        named.append(keg)
    status = investigation["status"]
    if status in ("CLOSED_RECOVERED", "CLOSED_WRITTEN_OFF"):
        fail("ERR_ALREADY_TERMINAL", "This investigation is already closed.")
    if action == "EVIDENCE_HOLD" and status != "OPEN":
        fail("ERR_INVALID_STATE", "An evidence hold requires status OPEN.")
    if action == "RESUME" and status != "EVIDENCE_HOLD":
        fail("ERR_INVALID_STATE", "A resume requires status EVIDENCE_HOLD.")
    if action == "EVIDENCE_HOLD":
        util.not_future_instant(hold_started_at, "hold_started_at")
        for keg in named:
            if keg["theft_investigation_id"] != investigation["id"] \
                    or keg["custody_state"] in calc.WRITTEN_OFF_STATES:
                fail("ERR_KEG_NOT_ATTACHED",
                     "Every held keg must be attached and not written off.")
    pool_ids = set()
    if action == "EVIDENCE_HOLD":
        for keg in named:
            keg["pre_hold_custody_state"] = keg["custody_state"]
            keg["custody_state"] = "EVIDENCE_HOLD"
            keg["dwell_flag"] = "WITHIN_LIMIT"
            util.bump(keg)
            pool_ids.add(keg["pool_id"])
        investigation["status"] = "EVIDENCE_HOLD"
        investigation["hold_started_at"] = hold_started_at
    elif action == "RESUME":
        for keg in _attached_kegs(investigation["id"]):
            if keg["custody_state"] != "EVIDENCE_HOLD":
                continue
            keg["custody_state"] = keg["pre_hold_custody_state"] or "IN_FLOAT"
            keg["pre_hold_custody_state"] = None
            util.bump(keg)
            pool_ids.add(keg["pool_id"])
        investigation["status"] = "OPEN"
        investigation["hold_started_at"] = None
    else:
        attached = _attached_kegs(investigation["id"])
        for keg in attached:
            held = keg["custody_state"] == "EVIDENCE_HOLD"
            if outcome == "RECOVERED":
                if held:
                    keg["custody_state"] = "IN_SERVICE"
                    keg["pre_hold_custody_state"] = None
                keg["theft_investigation_id"] = None
            else:
                if held:
                    keg["custody_state"] = "STOLEN"
                    keg["pre_hold_custody_state"] = None
                    keg["dwell_flag"] = "WITHIN_LIMIT"
                else:
                    keg["theft_investigation_id"] = None
            util.bump(keg)
            pool_ids.add(keg["pool_id"])
        if outcome == "WRITTEN_OFF" \
                and investigation["suspect_distributor_id"] is not None:
            keg_id_set = set(keg["id"] for keg in attached)
            for accrual in db.accruals.values():
                if accrual["distributor_id"] \
                        != investigation["suspect_distributor_id"]:
                    continue
                if accrual["keg_id"] not in keg_id_set:
                    continue
                if accrual["status"] not in ("ACCRUED", "PAID"):
                    continue
                accrual["status"] = "CLAWED_BACK"
                accrual["clawback_reason"] = \
                    "THEFT_INVESTIGATION_WRITTEN_OFF"
                util.bump(accrual)
            suspect = db.distributors.get(
                investigation["suspect_distributor_id"])
            if suspect is not None:
                recompute.recompute_distributor_ledger(suspect)
        investigation["status"] = "CLOSED_RECOVERED" \
            if outcome == "RECOVERED" else "CLOSED_WRITTEN_OFF"
        investigation["closed_at"] = clock.now()
        if notes is not None:
            investigation["outcome_notes"] = notes
    _refresh_exposure(investigation)
    util.bump(investigation)
    pool_ids.add(investigation["pool_id"])
    for pool_id in pool_ids:
        recompute.cascade_pool_id(pool_id)
    return response.ok(investigation)


@bp.get("/theft-investigations/<investigation_id>")
def read_investigation(investigation_id):
    middleware.authenticate("PoolOperator", "AssetRecoveryAnalyst")
    investigation = db.investigations.get(investigation_id)
    if investigation is None:
        fail("ERR_INVESTIGATION_NOT_FOUND")
    return response.ok(investigation)


@bp.get("/theft-investigations")
def list_investigations():
    middleware.authenticate("PoolOperator", "AssetRecoveryAnalyst")
    limit, offset = middleware.pagination()
    filters = {field: middleware.qparam(field)
               for field in ("pool_id", "suspect_distributor_id",
                             "commodity_index_id", "status")}
    rows = [row for row in db.investigations.values()
            if all(view.match(row, field, value)
                   for field, value in filters.items())]
    page, total = view.paginate(view.ordered(rows), limit, offset)
    return response.listing(page, limit, offset, total)
