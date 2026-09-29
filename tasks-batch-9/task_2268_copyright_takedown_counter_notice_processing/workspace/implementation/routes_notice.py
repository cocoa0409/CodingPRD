"""Notices, claims, counter-notices, strikes, termination cases,
misrepresentation cases and the logical-clock driver."""
from datetime import timedelta

from flask import Blueprint

import calc
from calc import D, present
from envelope import api, created, many, one
from errors import fail
from guards import (
    authorize,
    body,
    enum_filter,
    id_filter,
    listing,
    opt_bool,
    opt_string,
    pagination,
    path_account,
    path_claim,
    path_counter,
    path_misrep,
    path_notice,
    path_strike,
    path_termination,
    own_account,
    own_holder,
    req_claimed_urls,
    req_enum,
    req_id,
    req_int,
    req_string,
    resolve_fk,
)
import services
import store
from store import create, db, touch, update

notices_bp = Blueprint("notices", __name__)
clock_bp = Blueprint("clock", __name__)

SUBMISSION_CHANNELS = ("WEB_FORM", "EMAIL", "API_BULK")
NOTICE_STATUSES = ("RECEIVED", "VALIDATED", "REJECTED", "PROCESSED", "WITHDRAWN", "CLOSED")
CLAIM_STATUSES = (
    "MATCHED",
    "DISABLED",
    "COUNTER_NOTICED",
    "RESTORATION_SCHEDULED",
    "RESTORED",
    "UPHELD",
    "WITHDRAWN",
)
COUNTER_STATUSES = (
    "RECEIVED",
    "VALIDATED",
    "FORWARDED",
    "RESTORATION_SCHEDULED",
    "RESTORED",
    "BLOCKED_BY_SUIT",
    "SUPERSEDED",
    "REJECTED",
)
STRIKE_STATUSES = ("ACTIVE", "DECAYED", "EXPIRED", "VOIDED")
MISREP_STATUSES = ("OPEN", "SUBSTANTIATED", "DISMISSED")


# ==========================================================================
# TakedownNotice
# ==========================================================================
@notices_bp.route("/notices", methods=["POST"])
@api
def create_notice():
    user_id, role = authorize("RightsHolderRep", "TakedownAgent")
    payload = body()
    holder_id = req_id(payload, "rights_holder_id", db.rights_holders, "ERR_RIGHTS_HOLDER_NOT_FOUND")
    channel = req_enum(payload, "submission_channel", SUBMISSION_CHANNELS)
    claimed_urls = req_claimed_urls(payload)
    batch_id = opt_string(payload, "ingestion_batch_id")
    fields = {
        "signature_present": opt_bool(payload, "signature_present", False),
        "work_identification": opt_string(payload, "work_identification"),
        "material_identification": opt_string(payload, "material_identification"),
        "contact_email": opt_string(payload, "contact_email"),
        "good_faith_statement": opt_bool(payload, "good_faith_statement", False),
        "accuracy_statement": opt_bool(payload, "accuracy_statement", False),
        "authority_statement": opt_bool(payload, "authority_statement", False),
        "sworn_under_penalty": opt_bool(payload, "sworn_under_penalty", False),
    }

    holder = resolve_fk(holder_id, db.rights_holders, "ERR_RIGHTS_HOLDER_NOT_FOUND")
    batch = None
    if batch_id is not None:
        batch = resolve_fk(batch_id, db.batches, "ERR_INGESTION_BATCH_NOT_FOUND")
    own_holder(role, user_id, holder["id"])

    if batch is not None and holder["program_tier"] not in ("VERIFIED", "TRUSTED"):
        fail("ERR_PROGRAM_TIER_INSUFFICIENT", "program_tier must be VERIFIED or TRUSTED.")

    record = {
        "rights_holder_id": holder["id"],
        "ingestion_batch_id": None if batch is None else batch["id"],
        "submission_channel": channel,
        "claimed_urls": list(claimed_urls),
        "completeness_score": 0,
        "compliance_variant": "SUBSTANTIAL_COMPLIANCE",
        "status": "RECEIVED",
        "rejection_reason": None,
        "matched_claim_count": 0,
        "unmatched_url_count": 0,
        "validated_at": None,
        "processed_at": None,
    }
    record.update(fields)
    notice = create(db.notices, record)

    if batch is not None:
        changes = {"notices_created": batch["notices_created"] + 1}
        if batch["status"] == "ACCEPTED":
            changes["status"] = "PROCESSING"
        update(batch, **changes)
    return created(notice)


@notices_bp.route("/notices/<notice_id>", methods=["GET"])
@api
def read_notice(notice_id):
    authorize("ComplianceOfficer", "TakedownAgent", "AbuseInvestigator", "RightsHolderRep")
    return one(path_notice(notice_id))


@notices_bp.route("/notices", methods=["GET"])
@api
def list_notices():
    authorize("ComplianceOfficer", "TakedownAgent", "AbuseInvestigator", "RightsHolderRep")
    pagination()
    status = enum_filter("status", NOTICE_STATUSES)
    holder_id = id_filter("rights_holder_id", db.rights_holders, "ERR_RIGHTS_HOLDER_NOT_FOUND")
    batch_id = id_filter("ingestion_batch_id", db.batches, "ERR_INGESTION_BATCH_NOT_FOUND")
    rows, meta = listing(
        db.notices.values(),
        [
            lambda r: holder_id is None or r["rights_holder_id"] == holder_id,
            lambda r: batch_id is None or r["ingestion_batch_id"] == batch_id,
            lambda r: status is None or r["status"] == status,
        ],
    )
    return many(rows, meta)


@notices_bp.route("/notices/<notice_id>/validate", methods=["POST"])
@api
def validate_notice(notice_id):
    authorize("TakedownAgent")
    notice = path_notice(notice_id)
    provider = services.provider_of_notice(notice)
    services.require_registered_agent(provider)
    if notice["status"] != "RECEIVED":
        fail("ERR_INVALID_NOTICE_STATE", "Only a RECEIVED notice may be validated.")

    holder = db.rights_holders.get(notice["rights_holder_id"])
    tier = "STANDARD" if holder is None else holder["program_tier"]
    score, variant, passes, reason = calc.notice_completeness(notice, tier)

    if passes:
        update(
            notice,
            completeness_score=score,
            compliance_variant=variant,
            validated_at=db.clock,
            status="VALIDATED",
        )
    else:
        update(
            notice,
            completeness_score=score,
            compliance_variant=variant,
            rejection_reason=reason,
            status="REJECTED",
        )
        if holder is not None:
            update(holder, rejected_count=holder["rejected_count"] + 1)
            services.recompute_abuse_score(holder)
    return one(notice)


def _resolve_live_items(notice, provider):
    """Each claimed_urls entry mapped to the live ContentItem it names, or None."""
    resolved = []
    for url in notice["claimed_urls"]:
        found = None
        for item in db.content_items.values():
            if item["content_url"] != url:
                continue
            if item["availability_status"] not in ("AVAILABLE", "RESTORED"):
                continue
            if provider is not None:
                account = services.account_of_item(item)
                if account is None or account["provider_id"] != provider["id"]:
                    continue
            found = item
            break
        resolved.append((url, found))
    return resolved


@notices_bp.route("/notices/<notice_id>/process", methods=["POST"])
@api
def process_notice(notice_id):
    authorize("TakedownAgent")
    notice = path_notice(notice_id)
    provider = services.provider_of_notice(notice)
    services.require_published_policy(provider)
    if notice["status"] != "VALIDATED":
        fail("ERR_INVALID_NOTICE_STATE", "Only a VALIDATED notice may be processed.")

    holder = db.rights_holders.get(notice["rights_holder_id"])
    resolved = _resolve_live_items(notice, provider)
    live = [(url, item) for url, item in resolved if item is not None]

    if not live:
        fail("ERR_NO_ACTIONABLE_CLAIMS", "No claimed URL resolves to live material.")

    def blocked(item):
        for other in db.claims.values():
            if other["content_item_id"] != item["id"]:
                continue
            if other["rights_holder_id"] != notice["rights_holder_id"]:
                continue
            if other["status"] not in services.INTERVAL_STATUSES:
                continue
            if calc.interval_occupied(
                db.clock, other["disabled_at"], other["dispute_window_days"]
            ):
                return True
        return False

    free = [(url, item) for url, item in live if not blocked(item)]
    if not free:
        fail("ERR_DUPLICATE_CLAIM_WINDOW", "Every resolved item is inside an open dispute interval.")

    cfg = services.policy_cfg(None if provider is None else provider["id"])
    candidates = [
        r
        for r in db.reference_files.values()
        if r["rights_holder_id"] == notice["rights_holder_id"] and r["status"] == "ACTIVE"
    ]
    tier = "STANDARD" if holder is None else holder["program_tier"]

    for url, item in free:
        if item["availability_status"] not in ("AVAILABLE", "RESTORED"):
            continue
        claim = create(
            db.claims,
            {
                "notice_id": notice["id"],
                "content_item_id": item["id"],
                "rights_holder_id": notice["rights_holder_id"],
                "reference_file_id": None,
                "matched_url": url,
                "match_confidence": None,
                "status": "MATCHED",
                "dispute_window_days": cfg["dispute_window_days"],
                "counter_notice_window_days": cfg["counter_notice_window_days"],
                "disabled_at": None,
                "restoration_due_at": None,
            },
        )
        reference, confidence = calc.select_reference(
            item["fingerprint_hash"], candidates, tier
        )
        if reference is not None:
            claim["reference_file_id"] = reference["id"]
            claim["match_confidence"] = calc.num(confidence)
            update(reference, match_count=reference["match_count"] + 1)
        claim["status"] = "DISABLED"
        claim["disabled_at"] = db.clock
        account = services.account_of_item(item)
        services.disable_item_for_claim(item, account, holder, claim)

    update(
        notice,
        matched_claim_count=len(live),
        unmatched_url_count=len(resolved) - len(live),
        processed_at=db.clock,
        status="PROCESSED",
    )
    if holder is not None:
        update(holder, notices_processed=holder["notices_processed"] + 1)
    services.maybe_close_notice(notice)
    return one(notice)


@notices_bp.route("/notices/<notice_id>/withdraw", methods=["POST"])
@api
def withdraw_notice(notice_id):
    user_id, role = authorize("RightsHolderRep")
    notice = path_notice(notice_id)
    own_holder(role, user_id, notice["rights_holder_id"])
    status = notice["status"]
    if status not in ("VALIDATED", "PROCESSED"):
        fail("ERR_INVALID_NOTICE_STATE", "Only a VALIDATED or PROCESSED notice may be withdrawn.")

    children = services.claims_of_notice(notice)
    if status == "PROCESSED":
        for claim in children:
            if claim["status"] == "UPHELD":
                fail("ERR_INVALID_NOTICE_STATE", "A child claim is already UPHELD.")

    update(notice, status="WITHDRAWN")
    if status == "PROCESSED":
        children.sort(key=lambda record: record["created_at"])
        for claim in children:
            if claim["status"] in ("DISABLED", "COUNTER_NOTICED"):
                services.withdraw_claim(claim)

    holder = db.rights_holders.get(notice["rights_holder_id"])
    if holder is not None:
        update(holder, withdrawn_count=holder["withdrawn_count"] + 1)
        services.recompute_abuse_score(holder)
    return one(notice)


# ==========================================================================
# NoticeClaim
# ==========================================================================
@notices_bp.route("/claims/<claim_id>", methods=["GET"])
@api
def read_claim(claim_id):
    authorize(
        "ComplianceOfficer",
        "TakedownAgent",
        "AbuseInvestigator",
        "RightsHolderRep",
        "Subscriber",
    )
    return one(path_claim(claim_id))


@notices_bp.route("/claims", methods=["GET"])
@api
def list_claims():
    authorize(
        "ComplianceOfficer",
        "TakedownAgent",
        "AbuseInvestigator",
        "RightsHolderRep",
        "Subscriber",
    )
    pagination()
    status = enum_filter("status", CLAIM_STATUSES)
    notice_id = id_filter("notice_id", db.notices, "ERR_NOTICE_NOT_FOUND")
    item_id = id_filter("content_item_id", db.content_items, "ERR_CONTENT_ITEM_NOT_FOUND")
    holder_id = id_filter("rights_holder_id", db.rights_holders, "ERR_RIGHTS_HOLDER_NOT_FOUND")
    reference_id = id_filter("reference_file_id", db.reference_files, "ERR_REFERENCE_FILE_NOT_FOUND")
    rows, meta = listing(
        db.claims.values(),
        [
            lambda r: notice_id is None or r["notice_id"] == notice_id,
            lambda r: item_id is None or r["content_item_id"] == item_id,
            lambda r: holder_id is None or r["rights_holder_id"] == holder_id,
            lambda r: reference_id is None or r["reference_file_id"] == reference_id,
            lambda r: status is None or r["status"] == status,
        ],
    )
    return many(rows, meta)


@notices_bp.route("/claims/<claim_id>/strikes", methods=["GET"])
@api
def list_claim_strikes(claim_id):
    authorize("ComplianceOfficer", "TakedownAgent", "Subscriber")
    claim = path_claim(claim_id)
    status = enum_filter("status", STRIKE_STATUSES)
    rows, meta = listing(
        db.strikes.values(),
        [
            lambda r: r["claim_id"] == claim["id"],
            lambda r: status is None or r["status"] == status,
        ],
    )
    return many(rows, meta)


@notices_bp.route("/claims/<claim_id>/uphold", methods=["POST"])
@api
def uphold_claim(claim_id):
    authorize("TakedownAgent")
    claim = path_claim(claim_id)
    status = claim["status"]
    item = services.item_of_claim(claim)
    account = services.account_of_item(item)

    if status == "DISABLED":
        for counter in services.counters_of_claim(claim):
            if counter["status"] in ("VALIDATED", "FORWARDED", "RESTORATION_SCHEDULED"):
                fail(
                    "ERR_INVALID_CLAIM_STATE",
                    "A live counter-notice on this claim blocks upholding.",
                )
        if claim["disabled_at"] is None:
            fail("ERR_INVALID_CLAIM_STATE", "The claim carries no disabled_at.")
        window_end = claim["disabled_at"] + timedelta(
            days=claim["counter_notice_window_days"]
        )
        if db.clock < window_end:
            fail("ERR_COUNTER_NOTICE_WINDOW_OPEN", "The counter-notice window is still open.")
        update(claim, status="UPHELD")
        if item is not None:
            update(item, dispute_status="RESOLVED")
        holder = db.rights_holders.get(claim["rights_holder_id"])
        if account is not None and holder is not None:
            services.accrue_strike(account, claim, holder, "CLAIM_UPHELD")
        services.maybe_close_notice(db.notices.get(claim["notice_id"]))
        return one(claim)

    if status == "RESTORATION_SCHEDULED":
        governing = services.governing_counter(claim)
        if governing is None or governing["status"] != "BLOCKED_BY_SUIT":
            fail(
                "ERR_INVALID_CLAIM_STATE",
                "A RESTORATION_SCHEDULED claim may only be upheld once its counter-notice is BLOCKED_BY_SUIT.",
            )
        update(claim, status="UPHELD", restoration_due_at=None)
        if item is not None:
            update(item, dispute_status="RESOLVED")
        services.maybe_close_notice(db.notices.get(claim["notice_id"]))
        return one(claim)

    fail("ERR_INVALID_CLAIM_STATE", "A claim in %s may not be upheld." % status)


@notices_bp.route("/claims/<claim_id>/restore", methods=["POST"])
@api
def restore_claim(claim_id):
    authorize("TakedownAgent")
    claim = path_claim(claim_id)
    if claim["status"] != "RESTORATION_SCHEDULED":
        fail("ERR_INVALID_CLAIM_STATE", "Only a RESTORATION_SCHEDULED claim may be restored.")
    due = claim["restoration_due_at"]
    if due is None or db.clock < due:
        fail("ERR_RESTORATION_TOO_EARLY", "The restoration window has not opened.")
    governing = services.governing_counter(claim)
    if governing is not None and governing["status"] == "BLOCKED_BY_SUIT":
        fail("ERR_RESTORATION_BLOCKED_BY_SUIT", "The complainant filed suit.")

    update(claim, status="RESTORED")
    if governing is not None and governing["status"] in ("FORWARDED", "RESTORATION_SCHEDULED"):
        update(governing, status="RESTORED")

    item = services.item_of_claim(claim)
    account = services.account_of_item(item)
    if item is not None:
        if item["availability_status"] == "DISABLED":
            update(item, availability_status="RESTORED", restored_at=db.clock)
            if account is not None:
                update(
                    account,
                    available_content_count=account["available_content_count"] + 1,
                )
        update(item, dispute_status="RESOLVED")
    services.void_strikes_of_claim(claim)
    if account is not None:
        services.recompute_account(account)
    services.maybe_close_notice(db.notices.get(claim["notice_id"]))
    return one(claim)


# ==========================================================================
# CounterNotice
# ==========================================================================
@notices_bp.route("/counter-notices", methods=["POST"])
@api
def create_counter():
    user_id, role = authorize("Subscriber")
    payload = body()
    claim_id = req_id(payload, "claim_id", db.claims, "ERR_CLAIM_NOT_FOUND")
    expected = req_int(payload, "expected_claim_version")
    subscriber_name = req_string(payload, "subscriber_name")
    fields = {
        "contact_email": opt_string(payload, "contact_email"),
        "material_identification": opt_string(payload, "material_identification"),
        "signature_present": opt_bool(payload, "signature_present", False),
        "good_faith_mistake_statement": opt_bool(payload, "good_faith_mistake_statement", False),
        "consent_to_jurisdiction": opt_bool(payload, "consent_to_jurisdiction", False),
        "consent_to_service_of_process": opt_bool(payload, "consent_to_service_of_process", False),
    }

    claim = resolve_fk(claim_id, db.claims, "ERR_CLAIM_NOT_FOUND")
    item = services.item_of_claim(claim)
    account = services.account_of_item(item)
    if account is None:
        fail("ERR_ACCOUNT_NOT_FOUND", "The claim's content item has no owning account.")
    own_account(role, user_id, account["id"])

    if claim["status"] not in ("DISABLED", "COUNTER_NOTICED"):
        fail("ERR_INVALID_CLAIM_STATE", "Only a DISABLED or COUNTER_NOTICED claim may be disputed.")
    if claim["disabled_at"] is None:
        fail("ERR_INVALID_CLAIM_STATE", "The claim carries no disabled_at.")
    deadline = claim["disabled_at"] + timedelta(days=claim["counter_notice_window_days"])
    if db.clock > deadline:
        fail("ERR_COUNTER_NOTICE_WINDOW_CLOSED", "The counter-notice window has closed.")
    if account["standing"] == "TERMINATED":
        fail("ERR_ACCOUNT_TERMINATED", "The account standing is TERMINATED.")
    if claim["version"] != expected:
        fail(
            "ERR_STALE_CLAIM_VERSION",
            "expected_claim_version %s does not match %s." % (expected, claim["version"]),
        )

    record = {
        "claim_id": claim["id"],
        "account_id": account["id"],
        "superseded_by_counter_notice_id": None,
        "subscriber_name": subscriber_name,
        "completeness_score": 0,
        "status": "RECEIVED",
        "rejection_reason": None,
        "forwarded_at": None,
        "restoration_earliest_at": None,
        "restoration_deadline_at": None,
        "suit_notice_at": None,
    }
    record.update(fields)
    counter = create(db.counter_notices, record)

    for prior in services.counters_of_claim(claim):
        if prior["id"] == counter["id"]:
            continue
        if prior["status"] == "RECEIVED":
            update(prior, status="SUPERSEDED", superseded_by_counter_notice_id=counter["id"])
        elif prior["status"] == "VALIDATED":
            update(prior, status="SUPERSEDED", superseded_by_counter_notice_id=counter["id"])
            update(claim, status="DISABLED")
            if item is not None:
                update(item, dispute_status="UNDER_NOTICE")
    touch(claim)
    return created(counter)


@notices_bp.route("/counter-notices/<counter_id>", methods=["GET"])
@api
def read_counter(counter_id):
    authorize(
        "ComplianceOfficer",
        "TakedownAgent",
        "AbuseInvestigator",
        "RightsHolderRep",
        "Subscriber",
    )
    return one(path_counter(counter_id))


@notices_bp.route("/counter-notices", methods=["GET"])
@api
def list_counters():
    authorize(
        "ComplianceOfficer",
        "TakedownAgent",
        "AbuseInvestigator",
        "RightsHolderRep",
        "Subscriber",
    )
    pagination()
    status = enum_filter("status", COUNTER_STATUSES)
    claim_id = id_filter("claim_id", db.claims, "ERR_CLAIM_NOT_FOUND")
    account_id = id_filter("account_id", db.accounts, "ERR_ACCOUNT_NOT_FOUND")
    superseded_by = id_filter(
        "superseded_by_counter_notice_id", db.counter_notices, "ERR_COUNTER_NOTICE_NOT_FOUND"
    )
    rows, meta = listing(
        db.counter_notices.values(),
        [
            lambda r: claim_id is None or r["claim_id"] == claim_id,
            lambda r: account_id is None or r["account_id"] == account_id,
            lambda r: superseded_by is None
            or r["superseded_by_counter_notice_id"] == superseded_by,
            lambda r: status is None or r["status"] == status,
        ],
    )
    return many(rows, meta)


@notices_bp.route("/counter-notices/<counter_id>/validate", methods=["POST"])
@api
def validate_counter(counter_id):
    authorize("TakedownAgent")
    counter = path_counter(counter_id)
    if counter["status"] != "RECEIVED":
        fail("ERR_INVALID_COUNTER_NOTICE_STATE", "Only a RECEIVED counter-notice may be validated.")

    score, passes, reason = calc.counter_completeness(counter)
    if not passes:
        update(counter, completeness_score=score, status="REJECTED", rejection_reason=reason)
        return one(counter)

    update(counter, completeness_score=score, status="VALIDATED")
    claim = db.claims.get(counter["claim_id"])
    if claim is not None and claim["status"] == "DISABLED":
        update(claim, status="COUNTER_NOTICED")
        item = services.item_of_claim(claim)
        if item is not None and item["dispute_status"] == "UNDER_NOTICE":
            update(item, dispute_status="COUNTER_NOTICED")
    return one(counter)


@notices_bp.route("/counter-notices/<counter_id>/forward", methods=["POST"])
@api
def forward_counter(counter_id):
    authorize("TakedownAgent")
    counter = path_counter(counter_id)
    if counter["status"] != "VALIDATED":
        fail("ERR_INVALID_COUNTER_NOTICE_STATE", "Only a VALIDATED counter-notice may be forwarded.")

    claim = db.claims.get(counter["claim_id"])
    notice = None if claim is None else db.notices.get(claim["notice_id"])
    holder = None if notice is None else db.rights_holders.get(notice["rights_holder_id"])
    if holder is not None and not present(holder["contact_email"]):
        fail("ERR_INVALID_REQUEST", "The complainant has no contact_email to forward to.")

    earliest, deadline = calc.restoration_window(db.clock)
    update(
        counter,
        status="FORWARDED",
        forwarded_at=db.clock,
        restoration_earliest_at=earliest,
        restoration_deadline_at=deadline,
    )
    if claim is not None and claim["status"] == "COUNTER_NOTICED":
        update(claim, status="RESTORATION_SCHEDULED", restoration_due_at=earliest)
        item = services.item_of_claim(claim)
        if item is not None and item["dispute_status"] == "COUNTER_NOTICED":
            update(item, dispute_status="RESTORATION_PENDING")
    return one(counter)


@notices_bp.route("/counter-notices/<counter_id>/record-suit-notice", methods=["POST"])
@api
def record_suit_notice(counter_id):
    authorize("TakedownAgent")
    counter = path_counter(counter_id)
    previous = counter["status"]
    if previous not in ("FORWARDED", "RESTORATION_SCHEDULED"):
        fail(
            "ERR_INVALID_COUNTER_NOTICE_STATE",
            "Only a FORWARDED or RESTORATION_SCHEDULED counter-notice may record a suit notice.",
        )
    deadline = counter["restoration_deadline_at"]
    if deadline is None or db.clock >= deadline:
        fail("ERR_SUIT_NOTICE_WINDOW_CLOSED", "The suit-notice window has closed.")

    update(counter, status="BLOCKED_BY_SUIT", suit_notice_at=db.clock)
    if previous == "FORWARDED":
        claim = db.claims.get(counter["claim_id"])
        if claim is not None and claim["status"] == "RESTORATION_SCHEDULED":
            update(claim, status="UPHELD", restoration_due_at=None)
            item = services.item_of_claim(claim)
            if item is not None:
                update(item, dispute_status="RESOLVED")
            services.maybe_close_notice(db.notices.get(claim["notice_id"]))
    return one(counter)


# ==========================================================================
# StrikeRecord / TerminationCase
# ==========================================================================
@notices_bp.route("/strikes/<strike_id>", methods=["GET"])
@api
def read_strike(strike_id):
    authorize("ComplianceOfficer", "TakedownAgent", "Subscriber")
    return one(path_strike(strike_id))


@notices_bp.route("/termination-cases/<case_id>", methods=["GET"])
@api
def read_termination(case_id):
    authorize("ComplianceOfficer", "Subscriber")
    return one(path_termination(case_id))


@notices_bp.route("/termination-cases/<case_id>/execute", methods=["POST"])
@api
def execute_termination(case_id):
    user_id, role = authorize("ComplianceOfficer")
    case = path_termination(case_id)
    account = db.accounts.get(case["account_id"])
    provider = None if account is None else db.providers.get(account["provider_id"])
    services.require_published_policy(provider)

    if case["status"] != "OPEN":
        fail("ERR_INVALID_TERMINATION_STATE", "Only an OPEN case may be executed.")
    if account is None:
        fail("ERR_ACCOUNT_NOT_FOUND", "The case has no account.")
    cfg = services.policy_cfg(account["provider_id"])
    points = services.computed_points(account, cfg)
    if points < D(cfg["termination_threshold_points"]):
        fail(
            "ERR_INVALID_ACCOUNT_STANDING",
            "Strike points are below the termination threshold.",
        )

    update(
        case,
        status="EXECUTED",
        executed_by_user_id=user_id,
        executed_at=db.clock,
        appeal_deadline_at=db.clock + timedelta(days=cfg["appeal_window_days"]),
    )
    update(
        account,
        standing="TERMINATED",
        terminated_at=db.clock,
        upload_restricted=True,
        strike_points=calc.num(points),
    )
    for item in list(db.content_items.values()):
        if item["account_id"] != account["id"]:
            continue
        if item["availability_status"] not in ("AVAILABLE", "RESTORED"):
            continue
        update(item, availability_status="DISABLED", disabled_at=db.clock)
        update(
            account,
            available_content_count=max(0, account["available_content_count"] - 1),
        )
    return one(case)


@notices_bp.route("/termination-cases/<case_id>/file-appeal", methods=["POST"])
@api
def file_appeal(case_id):
    user_id, role = authorize("Subscriber")
    case = path_termination(case_id)
    own_account(role, user_id, case["account_id"])
    if case["status"] != "EXECUTED":
        fail("ERR_INVALID_TERMINATION_STATE", "Only an EXECUTED case may be appealed.")
    deadline = case["appeal_deadline_at"]
    if deadline is None or db.clock >= deadline:
        fail("ERR_APPEAL_WINDOW_CLOSED", "The appeal window has closed.")
    update(case, status="APPEAL_FILED", appeal_filed_at=db.clock)
    return one(case)


@notices_bp.route("/termination-cases/<case_id>/decide-appeal", methods=["POST"])
@api
def decide_appeal(case_id):
    user_id, role = authorize("ComplianceOfficer")
    payload = body()
    decision = req_enum(payload, "decision", ("UPHELD", "VACATED"))
    case = path_termination(case_id)
    if case["status"] != "APPEAL_FILED":
        fail("ERR_INVALID_TERMINATION_STATE", "Only an APPEAL_FILED case may be decided.")
    if case["executed_by_user_id"] is not None and user_id == case["executed_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The deciding officer must differ from the executing officer.",
        )

    if decision == "UPHELD":
        update(case, status="CLOSED", decided_by_user_id=user_id, decision="UPHELD")
        return one(case)

    update(case, status="VACATED", decided_by_user_id=user_id, decision="VACATED")
    account = db.accounts.get(case["account_id"])
    if account is not None:
        for strike in db.strikes.values():
            if strike["account_id"] == account["id"] and strike["status"] in ("ACTIVE", "DECAYED"):
                update(strike, status="VOIDED", effective_points=0)
        update(account, standing="ACTIVE", terminated_at=None, upload_restricted=False)
        services.recompute_account(account)
    return one(case)


# ==========================================================================
# MisrepresentationCase
# ==========================================================================
@notices_bp.route("/misrepresentation-cases", methods=["POST"])
@api
def create_misrep():
    user_id, role = authorize("AbuseInvestigator")
    payload = body()
    holder_id = req_id(payload, "rights_holder_id", db.rights_holders, "ERR_RIGHTS_HOLDER_NOT_FOUND")
    claim_id = req_id(payload, "claim_id", db.claims, "ERR_CLAIM_NOT_FOUND")
    allegation = req_string(payload, "allegation")
    holder = resolve_fk(holder_id, db.rights_holders, "ERR_RIGHTS_HOLDER_NOT_FOUND")
    claim = resolve_fk(claim_id, db.claims, "ERR_CLAIM_NOT_FOUND")

    for other in db.misrep_cases.values():
        if (
            other["rights_holder_id"] == holder["id"]
            and other["claim_id"] == claim["id"]
            and other["status"] == "OPEN"
        ):
            fail(
                "ERR_MISREPRESENTATION_CASE_EXISTS",
                "An OPEN case already exists for this rights holder and claim.",
            )

    case = create(
        db.misrep_cases,
        {
            "rights_holder_id": holder["id"],
            "claim_id": claim["id"],
            "allegation": allegation,
            "opened_by_user_id": user_id,
            "substantiated_by_user_id": None,
            "status": "OPEN",
            "affected_claim_count": 0,
            "disabled_day_count": 0,
            "base_penalty_cents": 0,
            "surcharge_cents": 0,
            "total_penalty_cents": 0,
            "substantiated_at": None,
        },
    )
    return created(case)


@notices_bp.route("/misrepresentation-cases/<case_id>", methods=["GET"])
@api
def read_misrep(case_id):
    authorize("ComplianceOfficer", "AbuseInvestigator", "RightsHolderRep")
    return one(path_misrep(case_id))


@notices_bp.route("/misrepresentation-cases", methods=["GET"])
@api
def list_misreps():
    authorize("ComplianceOfficer", "AbuseInvestigator", "RightsHolderRep")
    pagination()
    status = enum_filter("status", MISREP_STATUSES)
    holder_id = id_filter("rights_holder_id", db.rights_holders, "ERR_RIGHTS_HOLDER_NOT_FOUND")
    claim_id = id_filter("claim_id", db.claims, "ERR_CLAIM_NOT_FOUND")
    rows, meta = listing(
        db.misrep_cases.values(),
        [
            lambda r: holder_id is None or r["rights_holder_id"] == holder_id,
            lambda r: claim_id is None or r["claim_id"] == claim_id,
            lambda r: status is None or r["status"] == status,
        ],
    )
    return many(rows, meta)


TIER_STEP_DOWN = {"TRUSTED": "VERIFIED", "VERIFIED": "STANDARD", "STANDARD": "STANDARD"}


@notices_bp.route("/misrepresentation-cases/<case_id>/substantiate", methods=["POST"])
@api
def substantiate_misrep(case_id):
    user_id, role = authorize("AbuseInvestigator")
    case = path_misrep(case_id)
    if case["status"] != "OPEN":
        fail("ERR_INVALID_MISREPRESENTATION_STATE", "Only an OPEN case may be substantiated.")
    claim = db.claims.get(case["claim_id"])
    if claim is not None and claim["status"] == "UPHELD":
        fail("ERR_INVALID_MISREPRESENTATION_STATE", "The referenced claim is UPHELD.")
    if case["opened_by_user_id"] is not None and user_id == case["opened_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The substantiating investigator must differ from the opening investigator.",
        )

    siblings = []
    if claim is not None:
        siblings = [
            c
            for c in db.claims.values()
            if c["notice_id"] == claim["notice_id"] and c["status"] in services.PENALTY_STATUSES
        ]
    affected = len(siblings)
    days = 0
    for sibling in siblings:
        item = services.item_of_claim(sibling)
        end = None if item is None else item["restored_at"]
        if end is None:
            end = db.clock
        days += calc.whole_days(sibling["disabled_at"], end)
    base, surcharge, total = calc.misrepresentation_penalty(affected, days)

    update(
        case,
        status="SUBSTANTIATED",
        substantiated_by_user_id=user_id,
        substantiated_at=db.clock,
        affected_claim_count=affected,
        disabled_day_count=days,
        base_penalty_cents=base,
        surcharge_cents=surcharge,
        total_penalty_cents=total,
    )

    holder = db.rights_holders.get(case["rights_holder_id"])
    if holder is not None:
        update(holder, misrepresentation_count=holder["misrepresentation_count"] + 1)
        score = services.recompute_abuse_score(holder)
        if score >= calc.SUSPENSION_FLOOR:
            update(holder, program_tier=TIER_STEP_DOWN[holder["program_tier"]])
            if holder["enrollment_status"] != "SUSPENDED":
                services.suspend_holder(holder)
    return one(case)


@notices_bp.route("/misrepresentation-cases/<case_id>/dismiss", methods=["POST"])
@api
def dismiss_misrep(case_id):
    user_id, role = authorize("AbuseInvestigator")
    case = path_misrep(case_id)
    if case["status"] != "OPEN":
        fail("ERR_INVALID_MISREPRESENTATION_STATE", "Only an OPEN case may be dismissed.")
    if case["opened_by_user_id"] is not None and user_id == case["opened_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The dismissing investigator must differ from the opening investigator.",
        )
    update(case, status="DISMISSED")
    return one(case)


# ==========================================================================
# Logical clock
# ==========================================================================
@clock_bp.route("/_clock/set_current_utc", methods=["POST"])
@api
def set_clock():
    authorize(
        "ComplianceOfficer",
        "TakedownAgent",
        "AbuseInvestigator",
        "RightsHolderRep",
        "Subscriber",
    )
    payload = body()
    raw = payload.get("current_utc")
    if not isinstance(raw, str) or not raw.strip():
        fail("ERR_INVALID_REQUEST", "current_utc is required and must be an ISO-8601 instant.")
    moment = store.parse_instant(raw)
    if moment is None:
        fail("ERR_INVALID_REQUEST", "current_utc must be an ISO-8601 instant.")
    services.advance_clock(moment)
    return one({"current_utc": moment})
