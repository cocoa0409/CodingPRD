"""Recall actions, the plan-revision cycle, withdrawal rounds and recovery."""

from decimal import Decimal

from flask import Blueprint, request

import access
import calc
import domain
import envelope
import schema
import store
from access import Checks, Ctx
from errors import ApiError

bp = Blueprint("recalls", __name__)

ZERO = Decimal("0.00")


def _owner_of_recall(auth, recall):
    listing = domain.listing_of_recall(recall)
    if listing is not None:
        access.owner_of_listing(auth, listing)


def _owner_of_withdrawal(auth, withdrawal):
    listing = domain.listing_of_withdrawal(withdrawal)
    if listing is not None:
        access.owner_of_listing(auth, listing)


# --------------------------------------------------------------- recall actions
@bp.post("/cosmetics/listings/<lid>/recall-actions")
def open_recall(lid):
    auth = access.authorize("EnforcementOfficer")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_LISTING, lambda: ctx.set("listing", access.need_listing(lid)))
    checks.add(access.R_OWNER, lambda: access.owner_of_listing(auth, ctx.listing))

    def validate():
        payload = body if body is not None else {}
        ctx.basis = schema.enum_field(payload, "initiation_basis", domain.INITIATION_BASES)
        ctx.hazard = schema.enum_field(payload, "hazard_class", domain.HAZARD_CLASSES)

    checks.add(access.R_INVALID, validate)
    checks.run()

    recall = store.insert("recalls", {
        "listing_id": lid,
        "initiation_basis": ctx.basis,
        "hazard_class": ctx.hazard,
        "status": "PLAN_REQUIRED",
        "plan_round": 0,
        "corrective_summary": None,
        "distribution_depth": None,
        "plan_submitted_at": None,
        "plan_decision_user_id": None,
        "plan_decision_at": None,
        "effectiveness_rate_final": None,
    })
    return envelope.created(domain.recall_json(recall))


@bp.get("/cosmetics/listings/<lid>/recall-actions")
def list_recalls(lid):
    auth = access.authorize(domain.ROLES)
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_LISTING, lambda: ctx.set("listing", access.need_listing(lid)))
    checks.add(access.R_OWNER, lambda: access.owner_of_listing(auth, ctx.listing))
    checks.run()
    records = domain.recalls_of_listing(lid)
    status = request.args.get("status")
    if status:
        records = [r for r in records if r["status"] == status]
    return envelope.paginate(store.by_created(records), domain.recall_json)


@bp.get("/cosmetics/recall-actions/<rid>")
def get_recall(rid):
    auth = access.authorize(domain.ROLES)
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_RECALL, lambda: ctx.set("recall", access.need_recall(rid)))
    checks.add(access.R_OWNER, lambda: _owner_of_recall(auth, ctx.recall))
    checks.run()
    return envelope.ok(domain.recall_json(ctx.recall))


# ------------------------------------------------------------ plan / decision
@bp.post("/cosmetics/recall-actions/<rid>/plan")
def submit_plan(rid):
    auth = access.authorize("ResponsiblePersonAgent")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_RECALL, lambda: ctx.set("recall", access.need_recall(rid)))
    checks.add(access.R_OWNER, lambda: _owner_of_recall(auth, ctx.recall))

    def validate():
        payload = body if body is not None else {}
        ctx.summary = schema.string_field(payload, "corrective_summary", max_len=2000)
        ctx.depth = schema.enum_field(payload, "distribution_depth", domain.DISTRIBUTION_DEPTHS)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STATE_RECALL, lambda: access.state_error(
        ctx.recall["status"] in ("PLAN_REQUIRED", "PLAN_REJECTED"), "ERR_INVALID_RECALL_STATE"))
    checks.add(access.R_PLAN_ROUNDS, lambda: access.state_error(
        ctx.recall["plan_round"] < domain.MAX_PLAN_ROUNDS,
        "ERR_RECALL_PLAN_ROUNDS_EXHAUSTED"))
    checks.run()

    recall = ctx.recall
    recall["status"] = "PLAN_SUBMITTED"
    recall["plan_round"] = int(recall["plan_round"]) + 1
    recall["plan_submitted_at"] = store.now()
    recall["corrective_summary"] = ctx.summary
    recall["distribution_depth"] = ctx.depth
    store.touch(recall)
    return envelope.ok(domain.recall_json(recall))


@bp.post("/cosmetics/recall-actions/<rid>/plan-decision")
def plan_decision(rid):
    auth = access.authorize("EnforcementOfficer")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_RECALL, lambda: ctx.set("recall", access.need_recall(rid)))

    def validate():
        payload = body if body is not None else {}
        ctx.decision = schema.enum_field(payload, "decision", ("ACCEPT", "REJECT"))
        ctx.note = schema.string_field(payload, "decision_note", required=False,
                                      max_len=1000, default=None)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STATE_RECALL, lambda: access.state_error(
        ctx.recall["status"] == "PLAN_SUBMITTED", "ERR_INVALID_RECALL_STATE"))
    checks.run()

    recall = ctx.recall
    listing = domain.listing_of_recall(recall)
    facility = domain.facility_of_listing(listing)
    recall["plan_decision_user_id"] = auth.user_id
    recall["plan_decision_at"] = store.now()

    if ctx.decision == "ACCEPT":
        recall["status"] = "PLAN_ACCEPTED"
        store.touch(recall)
        domain.ledger_append(facility["id"], "RECALL_DECISION", "RecallAction", recall["id"],
                             "recall plan accepted")
    elif (recall["plan_round"] >= domain.MAX_PLAN_ROUNDS
            and recall["initiation_basis"] == "MANDATORY_ORDER"):
        # PRD §3.8: the third rejection of a mandatory order escalates.
        domain.escalate_recall(recall)
    else:
        recall["status"] = "PLAN_REJECTED"
        store.touch(recall)
    return envelope.ok(domain.recall_json(recall))


# ------------------------------------------------------------ withdrawal rounds
@bp.post("/cosmetics/recall-actions/<rid>/withdrawals")
def open_withdrawal(rid):
    auth = access.authorize("EnforcementOfficer", "ResponsiblePersonAgent")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_RECALL, lambda: ctx.set("recall", access.need_recall(rid)))
    checks.add(access.R_OWNER, lambda: _owner_of_recall(auth, ctx.recall))

    def validate():
        payload = body if body is not None else {}
        ctx.depth = schema.enum_field(payload, "scope_depth", domain.DISTRIBUTION_DEPTHS)
        ctx.expected = schema.int_field(payload, "expected_recall_action_version", minimum=0)

    checks.add(access.R_INVALID, validate)
    # PRD §3.8: the OCC guard precedes the state check.
    checks.add(access.R_STALE_RECALL, lambda: access.state_error(
        ctx.expected == ctx.recall["version"], "ERR_STALE_RECALL_VERSION"))
    checks.add(access.R_STATE_RECALL, lambda: access.state_error(
        ctx.recall["status"] in ("PLAN_ACCEPTED", "EXECUTING", "EXTENDED"),
        "ERR_INVALID_RECALL_STATE"))
    checks.run()

    recall = ctx.recall
    # Opening a round supersedes the prior non-terminal round and releases its records.
    for predecessor in store.by_created(domain.withdrawals_of_recall(rid)):
        if predecessor["status"] in domain.WITHDRAWAL_SUPERSEDABLE:
            predecessor["status"] = "SUPERSEDED"
            for record in domain.records_of_withdrawal(predecessor["id"]):
                record["withdrawal_id"] = None
                store.touch(record)
            store.touch(predecessor)

    withdrawal = store.insert("withdrawals", {
        "recall_action_id": rid,
        "scope_depth": ctx.depth,
        "status": "OPEN",
        "reported_recovery_rate": ZERO,
        "provisional_verified_rate": None,
        "unreachable_credit_pct": None,
        "adjusted_denominator_units": None,
        "verified_recovery_rate": ZERO,
        "effectiveness_verdict": None,
        "effectiveness_reviewer_user_id": None,
    })
    recall["status"] = "EXECUTING"
    store.touch(recall)
    return envelope.created(domain.withdrawal_json(withdrawal))


@bp.get("/cosmetics/recall-actions/<rid>/withdrawals")
def list_withdrawals(rid):
    auth = access.authorize(domain.ROLES)
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_RECALL, lambda: ctx.set("recall", access.need_recall(rid)))
    checks.add(access.R_OWNER, lambda: _owner_of_recall(auth, ctx.recall))
    checks.run()
    records = domain.withdrawals_of_recall(rid)
    status = request.args.get("status")
    if status:
        records = [r for r in records if r["status"] == status]
    # PRD §3.8: withdrawal rounds are listed newest first.
    return envelope.paginate(store.by_created_desc(records), domain.withdrawal_json)


@bp.get("/cosmetics/withdrawals/<wid>")
def get_withdrawal(wid):
    auth = access.authorize(domain.ROLES)
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_WITHDRAWAL, lambda: ctx.set("withdrawal", access.need_withdrawal(wid)))
    checks.add(access.R_OWNER, lambda: _owner_of_withdrawal(auth, ctx.withdrawal))
    checks.run()
    return envelope.ok(domain.withdrawal_json(ctx.withdrawal))


@bp.post("/cosmetics/withdrawals/<wid>/records-production")
def produce_records(wid):
    auth = access.authorize("ResponsiblePersonAgent")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_WITHDRAWAL, lambda: ctx.set("withdrawal", access.need_withdrawal(wid)))

    def resolve_records():
        # Priority 12: every named identifier resolves, validated in payload order.
        raw = (body or {}).get("distribution_record_ids")
        if not isinstance(raw, list):
            return
        resolved = []
        for value in raw:
            if not isinstance(value, str):
                return
            resolved.append(access.need_record(value))
        ctx.records = resolved

    checks.add(access.R_RECORD, resolve_records)
    checks.add(access.R_OWNER, lambda: _owner_of_withdrawal(auth, ctx.withdrawal))

    def validate():
        payload = body if body is not None else {}
        ctx.ids = schema.id_list_field(payload, "distribution_record_ids")

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STATE_WITHDRAWAL, lambda: access.state_error(
        ctx.withdrawal["status"] == "OPEN", "ERR_INVALID_WITHDRAWAL_STATE"))

    def listing_match():
        listing = domain.listing_of_withdrawal(ctx.withdrawal)
        listing_id = listing["id"] if listing else None
        for record in ctx.get("records") or []:
            access.state_error(record["listing_id"] == listing_id,
                              "ERR_DISTRIBUTION_RECORD_LISTING_MISMATCH")

    checks.add(access.R_RECORD_MISMATCH, listing_match)
    checks.add(access.R_NO_RECORDS, lambda: access.state_error(
        len(ctx.get("records") or []) > 0, "ERR_NO_DISTRIBUTION_RECORDS"))
    checks.run()

    withdrawal = ctx.withdrawal
    for record in ctx.records:
        record["withdrawal_id"] = withdrawal["id"]
        store.touch(record)
    withdrawal["status"] = "RECORDS_PRODUCED"
    store.touch(withdrawal)
    return envelope.ok(domain.withdrawal_json(withdrawal))


@bp.post("/cosmetics/withdrawals/<wid>/recovery-entries")
def post_recovery_entry(wid):
    auth = access.authorize("ResponsiblePersonAgent")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_WITHDRAWAL, lambda: ctx.set("withdrawal", access.need_withdrawal(wid)))

    def resolve_record():
        raw = (body or {}).get("distribution_record_id")
        if isinstance(raw, str) and raw:
            ctx.record = access.need_record(raw)

    checks.add(access.R_RECORD, resolve_record)
    checks.add(access.R_OWNER, lambda: _owner_of_withdrawal(auth, ctx.withdrawal))

    def validate():
        payload = body if body is not None else {}
        ctx.kind = schema.enum_field(payload, "entry_kind", domain.RECOVERY_ENTRY_KINDS)
        schema.string_field(payload, "distribution_record_id", max_len=100)
        ctx.units = schema.int_field(payload, "units", minimum=1)
        raw_target = payload.get("reversal_target_bucket")
        target = None
        if raw_target is not None:
            target = domain.resolve_bucket_field(raw_target)
            if target is None:
                raise ApiError("ERR_INVALID_REQUEST",
                               "reversal_target_bucket is not a recognised recovery bucket.")
        if ctx.kind == "CORRECTION_REVERSAL" and target is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "reversal_target_bucket is required for a CORRECTION_REVERSAL entry.")
        ctx.target = target

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STATE_WITHDRAWAL, lambda: access.state_error(
        ctx.withdrawal["status"] in ("RECORDS_PRODUCED", "INTERIM_REVIEWED"),
        "ERR_INVALID_WITHDRAWAL_STATE"))
    checks.add(access.R_RECORD_NOT_IN_WITHDRAWAL, lambda: access.state_error(
        ctx.record["withdrawal_id"] == ctx.withdrawal["id"], "ERR_RECORD_NOT_IN_WITHDRAWAL"))

    def verified_cap():
        if ctx.kind not in ("VERIFIED_RETURN", "VERIFIED_DESTRUCTION"):
            return
        access.state_error(ctx.units <= domain.record_units_outstanding(ctx.record),
                          "ERR_RECOVERY_EXCEEDS_OUTSTANDING")

    checks.add(access.R_RECOVERY_OUTSTANDING, verified_cap)

    def reversal_cap():
        if ctx.kind != "CORRECTION_REVERSAL":
            return
        access.state_error(ctx.units <= ctx.record[ctx.target], "ERR_REVERSAL_EXCEEDS_RECORDED")

    checks.add(access.R_REVERSAL, reversal_cap)
    checks.run()

    record = ctx.record
    withdrawal = ctx.withdrawal
    listing = domain.listing_of_withdrawal(withdrawal)
    facility = domain.facility_of_listing(listing)
    if ctx.kind == "CORRECTION_REVERSAL":
        field = ctx.target
        record[field] = record[field] - ctx.units
        if field in domain.VERIFIED_BUCKETS:
            domain.ledger_append(
                facility["id"], "UNIT_MOVEMENT", "DistributionRecord", record["id"],
                "correction reversal of a verified recovery movement",
                signed_units_delta=-ctx.units)
    else:
        field = domain.RECOVERY_BUCKETS[ctx.kind]
        record[field] = record[field] + ctx.units
        if field in domain.VERIFIED_BUCKETS:
            domain.ledger_append(
                facility["id"], "UNIT_MOVEMENT", "DistributionRecord", record["id"],
                "verified recovery movement", signed_units_delta=ctx.units)
    store.touch(record)
    store.touch(withdrawal)
    return envelope.created(domain.distribution_record_json(record))


@bp.post("/cosmetics/withdrawals/<wid>/effectiveness-check")
def effectiveness_check(wid):
    auth = access.authorize("EnforcementOfficer")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_WITHDRAWAL, lambda: ctx.set("withdrawal", access.need_withdrawal(wid)))

    def validate():
        payload = body if body is not None else {}
        ctx.basis = schema.enum_field(payload, "basis", domain.EFFECTIVENESS_BASES)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STATE_WITHDRAWAL, lambda: access.state_error(
        ctx.withdrawal["status"] in ("RECORDS_PRODUCED", "INTERIM_REVIEWED"),
        "ERR_INVALID_WITHDRAWAL_STATE"))

    def segregation():
        # PRD §2.12: the officer who decided the plan may not review effectiveness.
        recall = domain.recall_of_withdrawal(ctx.withdrawal)
        decider = recall["plan_decision_user_id"] if recall else None
        access.state_error(decider is None or decider != auth.user_id,
                          "ERR_SEGREGATION_OF_DUTIES")

    checks.add(access.R_SEGREGATION, segregation)
    checks.add(access.R_NO_RECORDS, lambda: access.state_error(
        domain.withdrawal_records_count(ctx.withdrawal) > 0, "ERR_NO_DISTRIBUTION_RECORDS"))
    checks.run()

    withdrawal = ctx.withdrawal
    recall = domain.recall_of_withdrawal(withdrawal)
    listing = domain.listing_of_withdrawal(withdrawal)
    facility = domain.facility_of_listing(listing)
    shipped = domain.withdrawal_shipped_units(withdrawal)

    if ctx.basis == "REPORTED_BASIS":
        reported = domain.withdrawal_reported_units(withdrawal)
        withdrawal["reported_recovery_rate"] = calc.rate(reported, shipped)
        # PRD §3.8: INTERIM is the explicit non-terminal marker.
        withdrawal["effectiveness_verdict"] = "INTERIM"
        withdrawal["effectiveness_reviewer_user_id"] = auth.user_id
        withdrawal["status"] = "INTERIM_REVIEWED"
        store.touch(withdrawal)
        return envelope.ok(domain.withdrawal_json(withdrawal))

    verified = domain.withdrawal_verified_units(withdrawal)
    provisional = calc.rate(verified, shipped)
    credit_pct = calc.unreachable_credit_pct(provisional)
    denominator = calc.adjusted_denominator(shipped, credit_pct)
    final_rate = calc.rate(verified, denominator)
    withdrawal["provisional_verified_rate"] = provisional
    withdrawal["unreachable_credit_pct"] = credit_pct
    withdrawal["adjusted_denominator_units"] = denominator
    withdrawal["verified_recovery_rate"] = final_rate
    withdrawal["effectiveness_reviewer_user_id"] = auth.user_id

    effective = final_rate >= calc.EFFECTIVENESS_PASS_MARK
    withdrawal["effectiveness_verdict"] = "EFFECTIVE" if effective else "NOT_EFFECTIVE"
    withdrawal["status"] = "CLOSED_EFFECTIVE" if effective else "EXTENDED_INEFFECTIVE"
    store.touch(withdrawal)

    if effective:
        recall["status"] = "CLOSED_EFFECTIVE"
        recall["effectiveness_rate_final"] = final_rate
        store.touch(recall)
        store.touch(listing)
        domain.ledger_append(
            facility["id"], "WITHDRAWAL_CLOSURE", "MarketWithdrawal", withdrawal["id"],
            "withdrawal round closed as effective")
    else:
        recall["status"] = "EXTENDED"
        store.touch(recall)
    return envelope.ok(domain.withdrawal_json(withdrawal))
