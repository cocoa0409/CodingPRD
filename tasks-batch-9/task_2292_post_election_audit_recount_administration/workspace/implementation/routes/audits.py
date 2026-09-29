"""Audit, AuditRound and AuditBatch endpoints."""

from flask import Blueprint, g

from db import clock_now, db, dt_of, insert, now_iso, set_fields, touch
from errors import fail
from middleware import (
    ROLE_AUDIT_MANAGER,
    ROLE_CANDIDATE_REPRESENTATIVE,
    ROLE_CUSTODY_OFFICER,
    ROLE_ELECTIONS_DIRECTOR,
    ROLE_OBSERVER,
    SIX_ROLES,
    guard,
)
from response import object_response
from routes.common import list_endpoint, lookup, single
from services import calc
from services.domain import (
    TERMINAL_AUDIT_STATES,
    append_custody_event,
    audit_batch_chain,
    audit_batches_of_audit,
    audit_batches_of_round,
    audit_chain,
    create_round,
    discrepancies_of_tally,
    eligible_pool,
    interpretations_of_tally,
    latest_live_round,
    project_audit_timeline,
    recompute_audit_ledger,
    recompute_election,
    recompute_planned_sample_size,
    report_round,
    rounds_of_audit,
    tallies_of_audit,
    tallies_of_audit_batch,
    terminate_audit,
)
from validate import body, opt_num, opt_int, opt_str, req_digits, req_enum, req_int, req_str

bp = Blueprint("audits", __name__)

AUDIT_TYPES = ("RISK_LIMITING", "FIXED_PERCENTAGE", "COMPARISON")
AUDIT_STATUSES = (
    "PLANNED",
    "SEEDED",
    "SAMPLING",
    "TALLYING",
    "DISCREPANCY_REVIEW",
    "ESCALATED_FULL_HAND_COUNT",
    "COMPLETE",
    "TERMINATED",
)
ROUND_STATUSES = ("SELECTED", "TALLYING", "REVIEW_REQUIRED", "COMPLETE", "SUPERSEDED")
RETRIEVAL_STATUSES = ("PENDING_RETRIEVAL", "RETRIEVED", "RETURNED")
TALLY_STATUSES = ("NOT_STARTED", "IN_PROGRESS", "COUNTED", "VOIDED")
TIMELINE_STATUSES = ("ON_TRACK", "AT_RISK", "BREACHED")
REPORT_ROLES = (
    ROLE_ELECTIONS_DIRECTOR,
    ROLE_AUDIT_MANAGER,
    ROLE_CANDIDATE_REPRESENTATIVE,
    ROLE_OBSERVER,
)
ROUND_ORIGIN_STATES = ("SEEDED", "DISCREPANCY_REVIEW")
CLOSABLE_STATES = ("TALLYING", "DISCREPANCY_REVIEW", "ESCALATED_FULL_HAND_COUNT")
BLOCKING_TALLY_STATES = ("DRAFT", "PENDING_ADJUDICATION")


# ---------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------


@bp.post("/audits")
@guard([ROLE_AUDIT_MANAGER])
def create_audit():
    data = body()
    contest_id = req_str(data, "contest_id", 1, None)
    audit_type = req_enum(data, "audit_type", AUDIT_TYPES)
    risk_limit_alpha = opt_num(data, "risk_limit_alpha")
    fixed_percentage_pct = opt_num(data, "fixed_percentage_pct")
    prior_error_rate = opt_num(data, "prior_error_rate", 0, 1)

    contest = lookup("contests", contest_id)
    election = db.elections.get(contest["election_id"])
    if election is not None and election["status"] == "CERTIFIED":
        fail("ERR_ELECTION_ALREADY_CERTIFIED")

    # tier 34: cross-field configuration coherence (body only)
    if audit_type == "FIXED_PERCENTAGE":
        if risk_limit_alpha is not None or fixed_percentage_pct is None:
            fail("ERR_AUDIT_CONFIG_INVALID")
        if fixed_percentage_pct <= 0 or fixed_percentage_pct > 100:
            fail("ERR_AUDIT_CONFIG_INVALID")
    else:
        if fixed_percentage_pct is not None or risk_limit_alpha is None:
            fail("ERR_AUDIT_CONFIG_INVALID")
        if risk_limit_alpha not in calc.ALLOWED_ALPHAS:
            fail("ERR_AUDIT_CONFIG_INVALID")

    if prior_error_rate is None:
        prior_error_rate = calc.dec("0.10")

    measure_variant = (
        "MAX_RELATIVE_OVERSTATEMENT"
        if audit_type == "COMPARISON"
        else "NET_MARGIN_SHIFT"
    )

    row = insert(
        "audits",
        {
            "contest_id": contest_id,
            "audit_type": audit_type,
            "risk_limit_alpha": calc.fnum(risk_limit_alpha)
            if risk_limit_alpha is not None
            else None,
            "fixed_percentage_pct": calc.fnum(fixed_percentage_pct)
            if fixed_percentage_pct is not None
            else None,
            "prior_error_rate": calc.fnum(prior_error_rate),
            "measure_variant": measure_variant,
            "random_seed": None,
            "seed_published_at": None,
            "status": "PLANNED",
            "escalation_level": 0,
            "planned_sample_size": None,
            "sample_size_stale": False,
            "cumulative_sampled_batches": 0,
            "counted_ballots": 0,
            "cumulative_net_error_votes": 0,
            "discrepancy_measure": 0.0,
            "projected_completion_at": None,
            "slack_hours": None,
            "extension_days_granted": 0,
            "effective_slack_hours": None,
            "effective_certification_deadline_at": None,
            "timeline_status": "ON_TRACK",
            "public_report_published": False,
            "terminated_reason": None,
        },
    )
    if contest["status"] in ("CANVASSED", "CERTIFIED"):
        recompute_planned_sample_size(row, contest)
    recompute_election(election)
    return single(row, 201)


@bp.get("/audits")
@guard(SIX_ROLES)
def list_audits():
    return list_endpoint(
        "audits",
        {
            "contest_id": ("contest_id", None),
            "audit_type": ("audit_type", AUDIT_TYPES),
            "status": ("status", AUDIT_STATUSES),
            "timeline_status": ("timeline_status", TIMELINE_STATUSES),
        },
    )


@bp.get("/audits/<audit_id>")
@guard(SIX_ROLES)
def get_audit(audit_id):
    return single(lookup("audits", audit_id))


@bp.post("/audits/<audit_id>/seed")
@guard([ROLE_AUDIT_MANAGER])
def seed_audit(audit_id):
    data = body()
    random_seed = req_digits(data, "random_seed", 10)

    audit = lookup("audits", audit_id)
    if audit["status"] != "PLANNED":
        fail("ERR_INVALID_AUDIT_STATE")
    contest, election = audit_chain(audit)
    if contest["status"] not in ("CANVASSED", "CERTIFIED"):
        fail("ERR_CONTEST_NOT_CANVASSED")

    audit["random_seed"] = random_seed
    audit["seed_published_at"] = now_iso()
    audit["status"] = "SEEDED"
    recompute_planned_sample_size(audit, contest)
    touch(audit)
    return single(audit)


@bp.post("/audits/<audit_id>/rounds")
@guard([ROLE_AUDIT_MANAGER])
def create_audit_round(audit_id):
    data = body()
    expected_version = req_int(data, "expected_audit_version", 1, None)
    requested_size = opt_int(data, "sample_size_batches", 1, None)

    audit = lookup("audits", audit_id)
    if expected_version != audit["version"]:
        fail("ERR_STALE_AUDIT_VERSION")
    if audit["status"] not in ROUND_ORIGIN_STATES:
        fail("ERR_INVALID_AUDIT_STATE")

    contest, election = audit_chain(audit)
    pool = eligible_pool(audit, contest)
    previous_round = latest_live_round(audit)

    if requested_size is not None:
        sample_size = requested_size
    elif previous_round is None:
        sample_size = audit["planned_sample_size"] or 0
    else:
        target = calc.escalation_target(audit["planned_sample_size"])
        sample_size = target - (audit["cumulative_sampled_batches"] or 0)
        if sample_size < 0:
            sample_size = 0

    if len(pool) == 0 or sample_size > len(pool):
        fail("ERR_NO_UNSAMPLED_BATCHES")

    rnd = create_round(audit, contest, pool, sample_size, False, previous_round)
    audit["status"] = "SAMPLING"
    touch(audit)
    recompute_audit_ledger(audit)
    project_audit_timeline(audit)
    recompute_election(election)
    return single(rnd, 201)


@bp.post("/audits/<audit_id>/close")
@guard([ROLE_AUDIT_MANAGER])
def close_audit(audit_id):
    audit = lookup("audits", audit_id)
    if audit["status"] not in CLOSABLE_STATES:
        fail("ERR_INVALID_AUDIT_STATE")

    live_rounds = [r for r in rounds_of_audit(audit) if r["status"] != "SUPERSEDED"]
    drawn = []
    for rnd in live_rounds:
        drawn.extend(audit_batches_of_round(rnd))

    for audit_batch in drawn:
        if audit_batch["tally_status"] != "COUNTED":
            fail("ERR_TALLY_INCOMPLETE")
    for audit_batch in drawn:
        ballot_batch = db.ballot_batches.get(audit_batch["ballot_batch_id"])
        if ballot_batch is None or ballot_batch["custody_status"] != "RESEALED":
            fail("ERR_BATCH_NOT_RETURNED")

    tallies = []
    for audit_batch in drawn:
        tallies.extend(tallies_of_audit_batch(audit_batch))
    for tally in tallies:
        for row in interpretations_of_tally(tally):
            if row["status"] in ("PENDING", "DEADLOCKED"):
                fail("ERR_DEADLOCKED_INTERPRETATION_PENDING")
    for tally in tallies:
        for row in discrepancies_of_tally(tally):
            if row["status"] in ("OPEN", "ESCALATED"):
                fail("ERR_UNRESOLVED_DISCREPANCY")

    audit["status"] = "COMPLETE"
    audit["public_report_published"] = True
    touch(audit)
    for rnd in live_rounds:
        if rnd["status"] != "COMPLETE":
            rnd["status"] = "COMPLETE"
            touch(rnd)
    for tally in tallies_of_audit(audit):
        if tally["status"] == "SUBMITTED":
            tally["status"] = "CERTIFIED"
            touch(tally)

    recompute_audit_ledger(audit)
    project_audit_timeline(audit)
    contest, election = audit_chain(audit)
    recompute_election(election)
    return single(audit)


@bp.post("/audits/<audit_id>/terminate")
@guard([ROLE_ELECTIONS_DIRECTOR])
def terminate_audit_endpoint(audit_id):
    data = body()
    reason = req_str(data, "terminated_reason", 1, None)

    audit = lookup("audits", audit_id)
    if audit["status"] in TERMINAL_AUDIT_STATES:
        fail("ERR_INVALID_AUDIT_STATE")
    for tally in tallies_of_audit(audit):
        if tally["status"] in BLOCKING_TALLY_STATES:
            fail("ERR_INVALID_TALLY_STATE")

    terminate_audit(audit, reason)
    return single(audit)


@bp.post("/audits/<audit_id>/timeline-review")
@guard([ROLE_AUDIT_MANAGER])
def review_audit_timeline(audit_id):
    audit = lookup("audits", audit_id)
    project_audit_timeline(audit)
    contest, election = audit_chain(audit)
    recompute_election(election)
    return single(audit)


@bp.get("/audits/<audit_id>/public-report")
@guard(REPORT_ROLES)
def audit_public_report(audit_id):
    audit = lookup("audits", audit_id)

    if g.role == ROLE_OBSERVER:
        credential = db.observer_credentials.get(g.user_id)
        if credential is None:
            fail("ERR_OBSERVER_CREDENTIAL_NOT_FOUND")
        if credential["status"] != "ACTIVE":
            fail("ERR_OBSERVER_CREDENTIAL_REVOKED")
        now = clock_now()
        start = dt_of(credential["access_start_at"])
        end = dt_of(credential["access_end_at"])
        if now < start or now >= end:
            fail("ERR_OBSERVER_ACCESS_WINDOW_CLOSED")

    if not audit["public_report_published"]:
        fail("ERR_PUBLIC_REPORT_NOT_PUBLISHED")

    contest, election = audit_chain(audit)
    rnd = report_round(audit)
    return object_response(
        {
            "audit_id": audit["id"],
            "contest_label": contest["contest_label"] if contest else None,
            "audit_type": audit["audit_type"],
            "status": audit["status"],
            "random_seed": audit["random_seed"],
            "selection_sequence": list(rnd["selection_sequence"]) if rnd else [],
            "counted_ballots": audit["counted_ballots"],
            "cumulative_net_error_votes": audit["cumulative_net_error_votes"],
            "discrepancy_measure": audit["discrepancy_measure"],
            "discrepancy_count": rnd["discrepancy_count"] if rnd else 0,
            "escalation_level": audit["escalation_level"],
            "timeline_status": audit["timeline_status"],
            "published": audit["public_report_published"],
        }
    )


# ---------------------------------------------------------------------------
# rounds
# ---------------------------------------------------------------------------


@bp.get("/audit-rounds")
@guard(SIX_ROLES)
def list_audit_rounds():
    return list_endpoint(
        "audit_rounds",
        {
            "audit_id": ("audit_id", None),
            "previous_round_id": ("previous_round_id", None),
            "status": ("status", ROUND_STATUSES),
        },
        sort_keys=("round_number",),
    )


@bp.get("/audit-rounds/<round_id>")
@guard(SIX_ROLES)
def get_audit_round(round_id):
    return single(lookup("audit_rounds", round_id))


# ---------------------------------------------------------------------------
# drawn batches
# ---------------------------------------------------------------------------


@bp.get("/audit-batches")
@guard(SIX_ROLES)
def list_audit_batches():
    return list_endpoint(
        "audit_batches",
        {
            "audit_round_id": ("audit_round_id", None),
            "ballot_batch_id": ("ballot_batch_id", None),
            "retrieval_status": ("retrieval_status", RETRIEVAL_STATUSES),
            "tally_status": ("tally_status", TALLY_STATUSES),
        },
        sort_keys=("selection_index",),
    )


@bp.get("/audit-batches/<audit_batch_id>")
@guard(SIX_ROLES)
def get_audit_batch(audit_batch_id):
    return single(lookup("audit_batches", audit_batch_id))


@bp.post("/audit-batches/<audit_batch_id>/retrieve")
@guard([ROLE_CUSTODY_OFFICER])
def retrieve_audit_batch(audit_batch_id):
    data = body()
    expected_version = req_int(data, "expected_ballot_batch_version", 1, None)
    observed_seal_number = req_str(data, "observed_seal_number", 1, None)
    note = opt_str(data, "note", 1, None)

    audit_batch = lookup("audit_batches", audit_batch_id)
    ballot_batch = db.ballot_batches.get(audit_batch["ballot_batch_id"])
    if ballot_batch is None:
        fail("ERR_BALLOT_BATCH_NOT_FOUND")

    if expected_version != ballot_batch["version"]:
        fail("ERR_STALE_BALLOT_BATCH_VERSION")

    if audit_batch["retrieval_status"] != "PENDING_RETRIEVAL":
        fail("ERR_INVALID_AUDIT_BATCH_STATE")
    if ballot_batch["custody_status"] not in ("SEALED", "RESEALED", "QUARANTINED"):
        fail("ERR_INVALID_BATCH_STATE")
    if ballot_batch["custody_status"] == "QUARANTINED":
        fail("ERR_BATCH_QUARANTINED")
    if ballot_batch["retrieval_authorized_at"] is None:
        fail("ERR_RETRIEVAL_NOT_AUTHORIZED")
    if observed_seal_number != ballot_batch["current_seal_number"]:
        fail("ERR_SEAL_NUMBER_MISMATCH")

    ballot_batch["custody_status"] = "CHECKED_OUT"
    ballot_batch["last_checked_out_at"] = now_iso()
    ballot_batch["open_checkout_count"] = ballot_batch["open_checkout_count"] + 1
    touch(ballot_batch)
    append_custody_event(
        ballot_batch, "CHECK_OUT", observed_seal_number, None, note=note
    )
    audit_batch["retrieval_status"] = "RETRIEVED"
    touch(audit_batch)
    return single(audit_batch)


@bp.post("/audit-batches/<audit_batch_id>/return")
@guard([ROLE_CUSTODY_OFFICER])
def return_audit_batch(audit_batch_id):
    data = body()
    reseal_number = req_str(data, "reseal_number", 1, None)
    note = opt_str(data, "note", 1, None)

    audit_batch = lookup("audit_batches", audit_batch_id)
    ballot_batch = db.ballot_batches.get(audit_batch["ballot_batch_id"])
    if ballot_batch is None:
        fail("ERR_BALLOT_BATCH_NOT_FOUND")

    if audit_batch["retrieval_status"] != "RETRIEVED":
        fail("ERR_INVALID_AUDIT_BATCH_STATE")
    if ballot_batch["custody_status"] not in ("CHECKED_OUT", "QUARANTINED"):
        fail("ERR_INVALID_BATCH_STATE")
    for tally in tallies_of_audit_batch(audit_batch):
        if tally["status"] in BLOCKING_TALLY_STATES:
            fail("ERR_INVALID_TALLY_STATE")
    if audit_batch["tally_status"] not in ("COUNTED", "VOIDED", "NOT_STARTED"):
        fail("ERR_INVALID_AUDIT_BATCH_STATE")
    if ballot_batch["custody_status"] == "QUARANTINED":
        fail("ERR_BATCH_QUARANTINED")
    if reseal_number == ballot_batch["current_seal_number"]:
        fail("ERR_SEAL_NUMBER_MISMATCH")

    previous_seal = ballot_batch["current_seal_number"]
    ballot_batch["current_seal_number"] = reseal_number
    ballot_batch["custody_status"] = "RESEALED"
    ballot_batch["last_resealed_at"] = now_iso()
    ballot_batch["open_checkout_count"] = max(
        0, ballot_batch["open_checkout_count"] - 1
    )
    ballot_batch["checkout_cycle_count"] = ballot_batch["checkout_cycle_count"] + 1
    touch(ballot_batch)
    append_custody_event(
        ballot_batch, "CHECK_IN", previous_seal, reseal_number, note=note
    )
    audit_batch["retrieval_status"] = "RETURNED"
    touch(audit_batch)
    return single(audit_batch)
