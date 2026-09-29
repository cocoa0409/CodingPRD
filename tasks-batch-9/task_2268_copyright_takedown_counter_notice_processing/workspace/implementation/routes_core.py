"""Providers, designated agents, policies, accounts, content items,
rights holders, reference files and ingestion batches."""
from datetime import timedelta

from flask import Blueprint

import calc
from calc import D, present
from envelope import api, created, many, one
from errors import fail
from guards import (
    FINGERPRINT_RE,
    authorize,
    bad,
    body,
    enum_filter,
    id_filter,
    listing,
    opt_int,
    opt_string,
    pagination,
    path_account,
    path_agent,
    path_audit,
    path_batch,
    path_holder,
    path_item,
    path_policy,
    path_provider,
    path_reference,
    own_account,
    own_holder,
    req_fingerprint,
    req_id,
    req_int,
    req_string,
    resolve_fk,
)
import services
import store
from store import create, db, update

core = Blueprint("core", __name__)

SAFE_HARBOR_STATUSES = ("ELIGIBLE", "AT_RISK", "FORFEITED")
AGENT_STATUSES = ("DRAFT", "SUBMITTED", "REGISTERED", "LAPSED")
POLICY_STATUSES = ("DRAFT", "PUBLISHED", "SUPERSEDED")
ACCOUNT_STANDINGS = ("ACTIVE", "LIMITED", "TERMINATED")
AVAILABILITY_STATUSES = ("AVAILABLE", "DISABLED", "RESTORED", "PURGED")
DISPUTE_STATUSES = (
    "NONE",
    "UNDER_NOTICE",
    "COUNTER_NOTICED",
    "RESTORATION_PENDING",
    "RESOLVED",
)
ENROLLMENT_STATUSES = ("PROSPECT", "ENROLLED", "SUSPENDED")
PROGRAM_TIERS = ("STANDARD", "VERIFIED", "TRUSTED")
STRIKE_STATUSES = ("ACTIVE", "DECAYED", "EXPIRED", "VOIDED")
TERMINATION_STATUSES = ("OPEN", "EXECUTED", "APPEAL_FILED", "VACATED", "CLOSED")
REFERENCE_STATUSES = ("PENDING", "ACTIVE", "QUARANTINED")
BATCH_STATUSES = ("ACCEPTED", "PROCESSING", "COMPLETED", "REJECTED")


def opt_number(payload, name, default, low=None, high=None):
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(name, "must be a number")
    if low is not None and D(value) < D(low):
        bad(name, "must be at least %s" % low)
    if high is not None and D(value) > D(high):
        bad(name, "must be at most %s" % high)
    return value


# ==========================================================================
# ServiceProviderProfile
# ==========================================================================
@core.route("/providers", methods=["POST"])
@api
def create_provider():
    authorize("ComplianceOfficer")
    payload = body()
    legal_name = req_string(payload, "legal_name")
    service_domain = req_string(payload, "service_domain")
    provider = create(
        db.providers,
        {
            "legal_name": legal_name,
            "service_domain": service_domain,
            "public_contact_url": None,
            "public_contact_published_at": None,
            "designated_agent_registered": False,
            "repeat_infringer_policy_published": False,
            "safe_harbor_score": 0,
            "safe_harbor_status": "FORFEITED",
            "last_audit_at": None,
        },
    )
    return created(provider)


@core.route("/providers/<provider_id>", methods=["GET"])
@api
def read_provider(provider_id):
    authorize("ComplianceOfficer", "TakedownAgent", "AbuseInvestigator")
    return one(path_provider(provider_id))


@core.route("/providers", methods=["GET"])
@api
def list_providers():
    authorize("ComplianceOfficer", "TakedownAgent", "AbuseInvestigator")
    status = enum_filter("safe_harbor_status", SAFE_HARBOR_STATUSES)
    rows, meta = listing(
        db.providers.values(),
        [lambda r: status is None or r["safe_harbor_status"] == status],
    )
    return many(rows, meta)


@core.route("/providers/<provider_id>/publish-contact", methods=["POST"])
@api
def publish_contact(provider_id):
    authorize("ComplianceOfficer")
    payload = body()
    url = req_string(payload, "public_contact_url")
    provider = path_provider(provider_id)
    update(provider, public_contact_url=url, public_contact_published_at=db.clock)
    services.recompute_posture(provider, "publish_contact")
    return one(provider)


@core.route("/providers/<provider_id>/designated-agents", methods=["GET"])
@api
def list_provider_agents(provider_id):
    authorize("ComplianceOfficer", "TakedownAgent")
    provider = path_provider(provider_id)
    status = enum_filter("registration_status", AGENT_STATUSES)
    rows, meta = listing(
        db.agents.values(),
        [
            lambda r: r["provider_id"] == provider["id"],
            lambda r: status is None or r["registration_status"] == status,
        ],
    )
    return many(rows, meta)


@core.route("/providers/<provider_id>/repeat-infringer-policies", methods=["GET"])
@api
def list_provider_policies(provider_id):
    authorize("ComplianceOfficer", "TakedownAgent", "Subscriber")
    provider = path_provider(provider_id)
    status = enum_filter("status", POLICY_STATUSES)
    rows, meta = listing(
        db.policies.values(),
        [
            lambda r: r["provider_id"] == provider["id"],
            lambda r: status is None or r["status"] == status,
        ],
    )
    return many(rows, meta)


@core.route("/providers/<provider_id>/safe-harbor-audits", methods=["GET"])
@api
def list_provider_audits(provider_id):
    authorize("ComplianceOfficer", "AbuseInvestigator")
    provider = path_provider(provider_id)
    rows, meta = listing(
        db.audits.values(), [lambda r: r["provider_id"] == provider["id"]]
    )
    return many(rows, meta)


# ==========================================================================
# DesignatedAgent
# ==========================================================================
@core.route("/designated-agents", methods=["POST"])
@api
def create_agent():
    authorize("ComplianceOfficer")
    payload = body()
    provider_id = req_id(payload, "provider_id", db.providers, "ERR_PROVIDER_NOT_FOUND")
    agent_name = req_string(payload, "agent_name")
    agent_email = req_string(payload, "agent_email")
    agent_phone = req_string(payload, "agent_phone")
    mailing_address = req_string(payload, "mailing_address")
    resolve_fk(provider_id, db.providers, "ERR_PROVIDER_NOT_FOUND")
    agent = create(
        db.agents,
        {
            "provider_id": provider_id,
            "agent_name": agent_name,
            "agent_email": agent_email,
            "agent_phone": agent_phone,
            "mailing_address": mailing_address,
            "copyright_office_receipt": None,
            "registration_status": "DRAFT",
            "submitted_at": None,
            "registered_at": None,
            "expires_at": None,
        },
    )
    return created(agent)


@core.route("/designated-agents/<agent_id>", methods=["GET"])
@api
def read_agent(agent_id):
    authorize("ComplianceOfficer", "TakedownAgent")
    return one(path_agent(agent_id))


@core.route("/designated-agents/<agent_id>/submit", methods=["POST"])
@api
def submit_agent(agent_id):
    authorize("ComplianceOfficer")
    agent = path_agent(agent_id)
    if agent["registration_status"] not in ("DRAFT", "LAPSED"):
        fail("ERR_INVALID_AGENT_STATE", "Only a DRAFT or LAPSED agent may be submitted.")
    if not (
        present(agent["agent_email"])
        and present(agent["agent_phone"])
        and present(agent["mailing_address"])
    ):
        fail("ERR_INVALID_REQUEST", "agent_email, agent_phone and mailing_address must be non-empty.")
    update(agent, registration_status="SUBMITTED", submitted_at=db.clock)
    return one(agent)


@core.route("/designated-agents/<agent_id>/register", methods=["POST"])
@api
def register_agent(agent_id):
    user_id, role = authorize("ComplianceOfficer")
    payload = body()
    expected = req_int(payload, "expected_provider_version")
    receipt = opt_string(payload, "copyright_office_receipt")
    agent = path_agent(agent_id)
    provider = db.providers.get(agent["provider_id"])

    if provider is None or provider["public_contact_published_at"] is None:
        fail(
            "ERR_PUBLIC_CONTACT_NOT_PUBLISHED",
            "The provider's public contact information is not published.",
        )
    if agent["registration_status"] != "SUBMITTED":
        fail("ERR_INVALID_AGENT_STATE", "Only a SUBMITTED agent may be registered.")
    for other in db.agents.values():
        if (
            other["id"] != agent["id"]
            and other["provider_id"] == provider["id"]
            and other["registration_status"] == "REGISTERED"
        ):
            fail(
                "ERR_AGENT_ALREADY_REGISTERED",
                "Another designated agent of this provider is already REGISTERED.",
            )
    if provider["version"] != expected:
        fail(
            "ERR_STALE_PROVIDER_VERSION",
            "expected_provider_version %s does not match %s." % (expected, provider["version"]),
        )

    fields = {
        "registration_status": "REGISTERED",
        "registered_at": db.clock,
        "expires_at": db.clock + timedelta(days=calc.REGISTRATION_TERM_DAYS),
    }
    if receipt is not None:
        fields["copyright_office_receipt"] = receipt
    update(agent, **fields)
    update(provider, designated_agent_registered=True)
    services.recompute_posture(provider, "agent_register")
    return one(agent)


@core.route("/designated-agents/<agent_id>/lapse", methods=["POST"])
@api
def lapse_agent(agent_id):
    authorize("ComplianceOfficer")
    agent = path_agent(agent_id)
    if agent["registration_status"] != "REGISTERED":
        fail("ERR_INVALID_AGENT_STATE", "Only a REGISTERED agent may lapse.")
    if agent["expires_at"] is None or db.clock < agent["expires_at"]:
        fail("ERR_REGISTRATION_NOT_EXPIRED", "The registration term has not elapsed.")
    update(agent, registration_status="LAPSED")
    provider = db.providers.get(agent["provider_id"])
    if provider is not None:
        services.recompute_posture(provider, "agent_lapse")
    return one(agent)


# ==========================================================================
# RepeatInfringerPolicy
# ==========================================================================
@core.route("/repeat-infringer-policies", methods=["POST"])
@api
def create_policy():
    authorize("ComplianceOfficer")
    payload = body()
    provider_id = req_id(payload, "provider_id", db.providers, "ERR_PROVIDER_NOT_FOUND")
    policy_text = req_string(payload, "policy_text")
    strike_expiry_days = opt_int(payload, "strike_expiry_days", 365, 30, 3650)
    decay_step_days = opt_int(payload, "decay_step_days", 90, 30, 365)
    limitation = opt_number(payload, "limitation_threshold_points", 20)
    termination = opt_number(payload, "termination_threshold_points", 40)
    appeal_window_days = opt_int(payload, "appeal_window_days", 14, 1, 90)
    counter_window = opt_int(payload, "counter_notice_window_days", 30, 1, 180)
    dispute_window = opt_int(payload, "dispute_window_days", 30, 1, 180)
    if D(limitation) <= 0:
        bad("limitation_threshold_points", "must be greater than 0")
    if D(limitation) >= D(termination):
        bad(
            "limitation_threshold_points",
            "must be strictly below termination_threshold_points",
        )
    resolve_fk(provider_id, db.providers, "ERR_PROVIDER_NOT_FOUND")
    policy = create(
        db.policies,
        {
            "provider_id": provider_id,
            "policy_text": policy_text,
            "strike_expiry_days": strike_expiry_days,
            "decay_step_days": decay_step_days,
            "limitation_threshold_points": limitation,
            "termination_threshold_points": termination,
            "appeal_window_days": appeal_window_days,
            "counter_notice_window_days": counter_window,
            "dispute_window_days": dispute_window,
            "status": "DRAFT",
            "published_at": None,
        },
    )
    return created(policy)


@core.route("/repeat-infringer-policies/<policy_id>", methods=["GET"])
@api
def read_policy(policy_id):
    authorize("ComplianceOfficer", "TakedownAgent", "Subscriber")
    return one(path_policy(policy_id))


@core.route("/repeat-infringer-policies/<policy_id>/publish", methods=["POST"])
@api
def publish_policy(policy_id):
    authorize("ComplianceOfficer")
    payload = body()
    expected = req_int(payload, "expected_provider_version")
    policy = path_policy(policy_id)
    provider = db.providers.get(policy["provider_id"])

    if policy["status"] != "DRAFT":
        fail("ERR_INVALID_POLICY_STATE", "Only a DRAFT policy revision may be published.")
    if D(policy["limitation_threshold_points"]) >= D(policy["termination_threshold_points"]):
        fail(
            "ERR_INVALID_REQUEST",
            "limitation_threshold_points must be strictly below termination_threshold_points.",
        )
    if provider is None or provider["version"] != expected:
        current = None if provider is None else provider["version"]
        fail(
            "ERR_STALE_PROVIDER_VERSION",
            "expected_provider_version %s does not match %s." % (expected, current),
        )

    for other in db.policies.values():
        if (
            other["id"] != policy["id"]
            and other["provider_id"] == provider["id"]
            and other["status"] == "PUBLISHED"
        ):
            update(other, status="SUPERSEDED")
    update(policy, status="PUBLISHED", published_at=db.clock)
    update(provider, repeat_infringer_policy_published=True)
    services.recompute_posture(provider, "policy_publish")
    return one(policy)


# ==========================================================================
# Account
# ==========================================================================
@core.route("/accounts", methods=["POST"])
@api
def create_account():
    authorize("ComplianceOfficer")
    payload = body()
    provider_id = req_id(payload, "provider_id", db.providers, "ERR_PROVIDER_NOT_FOUND")
    handle = req_string(payload, "handle")
    email = req_string(payload, "email")
    resolve_fk(provider_id, db.providers, "ERR_PROVIDER_NOT_FOUND")
    for other in db.accounts.values():
        if other["provider_id"] == provider_id and other["handle"] == handle:
            fail("ERR_ACCOUNT_HANDLE_CONFLICT", "handle is already used on this provider.")
    account = create(
        db.accounts,
        {
            "provider_id": provider_id,
            "handle": handle,
            "email": email,
            "standing": "ACTIVE",
            "strike_points": 0,
            "upload_restricted": False,
            "notified_count": 0,
            "available_content_count": 0,
            "terminated_at": None,
        },
    )
    return created(account)


@core.route("/accounts/<account_id>", methods=["GET"])
@api
def read_account(account_id):
    authorize("ComplianceOfficer", "TakedownAgent", "AbuseInvestigator", "Subscriber")
    return one(path_account(account_id))


@core.route("/accounts", methods=["GET"])
@api
def list_accounts():
    authorize("ComplianceOfficer", "TakedownAgent")
    pagination()
    standing = enum_filter("standing", ACCOUNT_STANDINGS)
    provider_id = id_filter("provider_id", db.providers, "ERR_PROVIDER_NOT_FOUND")
    rows, meta = listing(
        db.accounts.values(),
        [
            lambda r: provider_id is None or r["provider_id"] == provider_id,
            lambda r: standing is None or r["standing"] == standing,
        ],
    )
    return many(rows, meta)


@core.route("/accounts/<account_id>/content-items", methods=["GET"])
@api
def list_account_items(account_id):
    authorize("ComplianceOfficer", "TakedownAgent", "Subscriber")
    account = path_account(account_id)
    availability = enum_filter("availability_status", AVAILABILITY_STATUSES)
    dispute = enum_filter("dispute_status", DISPUTE_STATUSES)
    rows, meta = listing(
        db.content_items.values(),
        [
            lambda r: r["account_id"] == account["id"],
            lambda r: availability is None or r["availability_status"] == availability,
            lambda r: dispute is None or r["dispute_status"] == dispute,
        ],
    )
    return many(rows, meta)


@core.route("/accounts/<account_id>/strikes", methods=["GET"])
@api
def list_account_strikes(account_id):
    authorize("ComplianceOfficer", "TakedownAgent", "Subscriber")
    account = path_account(account_id)
    status = enum_filter("status", STRIKE_STATUSES)
    rows, meta = listing(
        db.strikes.values(),
        [
            lambda r: r["account_id"] == account["id"],
            lambda r: status is None or r["status"] == status,
        ],
    )
    return many(rows, meta)


@core.route("/accounts/<account_id>/termination-cases", methods=["GET"])
@api
def list_account_cases(account_id):
    authorize("ComplianceOfficer", "Subscriber")
    account = path_account(account_id)
    status = enum_filter("status", TERMINATION_STATUSES)
    rows, meta = listing(
        db.termination_cases.values(),
        [
            lambda r: r["account_id"] == account["id"],
            lambda r: status is None or r["status"] == status,
        ],
    )
    return many(rows, meta)


@core.route("/accounts/<account_id>/strike-summary", methods=["GET"])
@api
def strike_summary(account_id):
    authorize("ComplianceOfficer", "TakedownAgent", "Subscriber")
    account = path_account(account_id)
    cfg = services.policy_cfg(account["provider_id"])
    points = services.computed_points(account, cfg)
    counts = dict((status, 0) for status in STRIKE_STATUSES)
    for strike in db.strikes.values():
        if strike["account_id"] == account["id"]:
            counts[strike["status"]] = counts.get(strike["status"], 0) + 1
    return one(
        {
            "account_id": account["id"],
            "strike_points": calc.num(points),
            "active_strike_count": counts["ACTIVE"],
            "decayed_strike_count": counts["DECAYED"],
            "expired_strike_count": counts["EXPIRED"],
            "voided_strike_count": counts["VOIDED"],
            "limitation_threshold_points": cfg["limitation_threshold_points"],
            "termination_threshold_points": cfg["termination_threshold_points"],
            "standing": account["standing"],
        }
    )


@core.route("/accounts/<account_id>/reinstate", methods=["POST"])
@api
def reinstate_account(account_id):
    authorize("ComplianceOfficer")
    account = path_account(account_id)
    if account["standing"] != "TERMINATED":
        fail("ERR_INVALID_ACCOUNT_STANDING", "Only a TERMINATED account may be reinstated.")
    cfg = services.policy_cfg(account["provider_id"])
    points = services.computed_points(account, cfg)
    if points >= D(cfg["limitation_threshold_points"]):
        fail(
            "ERR_INVALID_ACCOUNT_STANDING",
            "Strike points have not decayed below the limitation threshold.",
        )
    update(
        account,
        standing="ACTIVE",
        terminated_at=None,
        upload_restricted=False,
        strike_points=calc.num(points),
    )
    return one(account)


# ==========================================================================
# ContentItem
# ==========================================================================
@core.route("/content-items", methods=["POST"])
@api
def create_item():
    user_id, role = authorize("Subscriber")
    payload = body()
    account_id = req_id(payload, "account_id", db.accounts, "ERR_ACCOUNT_NOT_FOUND")
    content_url = req_string(payload, "content_url")
    title = req_string(payload, "title")
    fingerprint = req_fingerprint(payload)
    account = resolve_fk(account_id, db.accounts, "ERR_ACCOUNT_NOT_FOUND")
    own_account(role, user_id, account["id"])

    if account["standing"] == "TERMINATED":
        fail("ERR_ACCOUNT_TERMINATED", "The account standing is TERMINATED.")
    if account["upload_restricted"]:
        fail("ERR_ACCOUNT_UPLOAD_RESTRICTED", "The account is upload restricted.")
    for other in db.content_items.values():
        sibling = db.accounts.get(other["account_id"])
        if sibling is None or sibling["provider_id"] != account["provider_id"]:
            continue
        if other["content_url"] == content_url:
            fail("ERR_CONTENT_URL_CONFLICT", "content_url already exists on this provider.")

    item = create(
        db.content_items,
        {
            "account_id": account["id"],
            "content_url": content_url,
            "title": title,
            "fingerprint_hash": fingerprint,
            "availability_status": "AVAILABLE",
            "dispute_status": "NONE",
            "disabled_at": None,
            "restored_at": None,
        },
    )
    update(account, available_content_count=account["available_content_count"] + 1)
    return created(item)


@core.route("/content-items/<item_id>", methods=["GET"])
@api
def read_item(item_id):
    authorize(
        "ComplianceOfficer",
        "TakedownAgent",
        "AbuseInvestigator",
        "Subscriber",
        "RightsHolderRep",
    )
    return one(path_item(item_id))


@core.route("/content-items/<item_id>/purge", methods=["POST"])
@api
def purge_item(item_id):
    user_id, role = authorize("Subscriber", "ComplianceOfficer")
    item = path_item(item_id)
    own_account(role, user_id, item["account_id"])
    account = db.accounts.get(item["account_id"])
    status = item["availability_status"]

    if status in ("AVAILABLE", "RESTORED"):
        update(item, availability_status="PURGED")
        if account is not None:
            update(
                account,
                available_content_count=max(0, account["available_content_count"] - 1),
            )
        return one(item)

    if status == "DISABLED" and role == "ComplianceOfficer":
        for claim in db.claims.values():
            if claim["content_item_id"] == item["id"] and claim["status"] in (
                "COUNTER_NOTICED",
                "RESTORATION_SCHEDULED",
            ):
                fail(
                    "ERR_INVALID_CONTENT_STATE",
                    "A claim on this item is COUNTER_NOTICED or RESTORATION_SCHEDULED.",
                )
        update(item, availability_status="PURGED")
        return one(item)

    fail("ERR_INVALID_CONTENT_STATE", "The item may not be purged from %s." % status)


# ==========================================================================
# RightsHolder
# ==========================================================================
@core.route("/rights-holders", methods=["POST"])
@api
def create_holder():
    authorize("ComplianceOfficer")
    payload = body()
    legal_name = req_string(payload, "legal_name")
    contact_email = req_string(payload, "contact_email")
    reference_quota = opt_int(payload, "reference_file_quota", 50, 1, 5000)
    daily_quota = opt_int(payload, "daily_item_quota", 500, 1, 100000)
    holder = create(
        db.rights_holders,
        {
            "legal_name": legal_name,
            "contact_email": contact_email,
            "reference_file_quota": reference_quota,
            "daily_item_quota": daily_quota,
            "enrollment_status": "PROSPECT",
            "program_tier": "STANDARD",
            "notices_processed": 0,
            "withdrawn_count": 0,
            "rejected_count": 0,
            "misrepresentation_count": 0,
            "abuse_score": 0,
        },
    )
    return created(holder)


@core.route("/rights-holders/<holder_id>", methods=["GET"])
@api
def read_holder(holder_id):
    authorize("ComplianceOfficer", "TakedownAgent", "AbuseInvestigator", "RightsHolderRep")
    return one(path_holder(holder_id))


@core.route("/rights-holders", methods=["GET"])
@api
def list_holders():
    authorize("ComplianceOfficer", "TakedownAgent", "AbuseInvestigator")
    enrollment = enum_filter("enrollment_status", ENROLLMENT_STATUSES)
    tier = enum_filter("program_tier", PROGRAM_TIERS)
    rows, meta = listing(
        db.rights_holders.values(),
        [
            lambda r: enrollment is None or r["enrollment_status"] == enrollment,
            lambda r: tier is None or r["program_tier"] == tier,
        ],
    )
    return many(rows, meta)


@core.route("/rights-holders/<holder_id>/enroll", methods=["POST"])
@api
def enroll_holder(holder_id):
    authorize("ComplianceOfficer")
    holder = path_holder(holder_id)
    if holder["enrollment_status"] == "ENROLLED":
        return one(holder)
    if not present(holder["contact_email"]):
        fail("ERR_INVALID_REQUEST", "contact_email must be non-empty to enroll.")
    if D(holder["abuse_score"]) >= calc.SUSPENSION_FLOOR:
        fail("ERR_ABUSE_SCORE_TOO_HIGH", "abuse_score is at or above the suspension floor.")
    update(holder, enrollment_status="ENROLLED")
    return one(holder)


@core.route("/rights-holders/<holder_id>/promote-tier", methods=["POST"])
@api
def promote_holder(holder_id):
    authorize("ComplianceOfficer")
    holder = path_holder(holder_id)
    tier = holder["program_tier"]
    if tier == "TRUSTED":
        return one(holder)
    if holder["enrollment_status"] != "ENROLLED":
        fail("ERR_RIGHTS_HOLDER_NOT_ENROLLED", "The rights holder is not ENROLLED.")
    target = "VERIFIED" if tier == "STANDARD" else "TRUSTED"
    if target == "TRUSTED":
        active = any(
            r["rights_holder_id"] == holder["id"] and r["status"] == "ACTIVE"
            for r in db.reference_files.values()
        )
        if not active:
            fail("ERR_NO_REFERENCE_FILE_ACTIVE", "Promotion to TRUSTED needs an ACTIVE reference file.")
    if D(holder["abuse_score"]) >= calc.AUTO_OPEN_FLOOR:
        fail("ERR_ABUSE_SCORE_TOO_HIGH", "abuse_score is at or above the auto-open floor.")
    update(holder, program_tier=target)
    return one(holder)


@core.route("/rights-holders/<holder_id>/suspend", methods=["POST"])
@api
def suspend_holder_route(holder_id):
    authorize("AbuseInvestigator", "ComplianceOfficer")
    holder = path_holder(holder_id)
    if holder["enrollment_status"] == "SUSPENDED":
        return one(holder)
    services.suspend_holder(holder)
    return one(holder)


@core.route("/rights-holders/<holder_id>/reference-files", methods=["GET"])
@api
def list_holder_references(holder_id):
    authorize("ComplianceOfficer", "TakedownAgent", "RightsHolderRep")
    holder = path_holder(holder_id)
    status = enum_filter("status", REFERENCE_STATUSES)
    rows, meta = listing(
        db.reference_files.values(),
        [
            lambda r: r["rights_holder_id"] == holder["id"],
            lambda r: status is None or r["status"] == status,
        ],
    )
    return many(rows, meta)


@core.route("/rights-holders/<holder_id>/ingestion-batches", methods=["GET"])
@api
def list_holder_batches(holder_id):
    authorize("ComplianceOfficer", "TakedownAgent", "RightsHolderRep")
    holder = path_holder(holder_id)
    status = enum_filter("status", BATCH_STATUSES)
    rows, meta = listing(
        db.batches.values(),
        [
            lambda r: r["rights_holder_id"] == holder["id"],
            lambda r: status is None or r["status"] == status,
        ],
    )
    return many(rows, meta)


# ==========================================================================
# ReferenceFile
# ==========================================================================
@core.route("/reference-files", methods=["POST"])
@api
def create_reference():
    user_id, role = authorize("RightsHolderRep", "ComplianceOfficer")
    payload = body()
    holder_id = req_id(payload, "rights_holder_id", db.rights_holders, "ERR_RIGHTS_HOLDER_NOT_FOUND")
    work_title = req_string(payload, "work_title")
    fingerprint = req_fingerprint(payload)
    registration_number = opt_string(payload, "registration_number")
    holder = resolve_fk(holder_id, db.rights_holders, "ERR_RIGHTS_HOLDER_NOT_FOUND")
    own_holder(role, user_id, holder["id"])

    held = sum(
        1
        for r in db.reference_files.values()
        if r["rights_holder_id"] == holder["id"] and r["status"] in ("PENDING", "ACTIVE")
    )
    if held + 1 > holder["reference_file_quota"]:
        fail("ERR_REFERENCE_QUOTA_EXCEEDED", "reference_file_quota would be exceeded.")

    reference = create(
        db.reference_files,
        {
            "rights_holder_id": holder["id"],
            "work_title": work_title,
            "fingerprint_hash": fingerprint,
            "registration_number": registration_number,
            "status": "PENDING",
            "activated_at": None,
            "match_count": 0,
        },
    )
    return created(reference)


@core.route("/reference-files/<reference_id>", methods=["GET"])
@api
def read_reference(reference_id):
    authorize("ComplianceOfficer", "TakedownAgent", "RightsHolderRep")
    return one(path_reference(reference_id))


@core.route("/reference-files/<reference_id>/activate", methods=["POST"])
@api
def activate_reference(reference_id):
    user_id, role = authorize("RightsHolderRep", "ComplianceOfficer")
    reference = path_reference(reference_id)
    own_holder(role, user_id, reference["rights_holder_id"])
    if reference["status"] != "PENDING":
        fail("ERR_INVALID_REFERENCE_FILE_STATE", "Only a PENDING reference file may be activated.")
    holder = db.rights_holders.get(reference["rights_holder_id"])
    if holder is None or holder["enrollment_status"] != "ENROLLED":
        fail("ERR_RIGHTS_HOLDER_NOT_ENROLLED", "The owning rights holder is not ENROLLED.")
    if not FINGERPRINT_RE.match(reference["fingerprint_hash"] or ""):
        fail("ERR_INVALID_REQUEST", "fingerprint_hash must be 32 lowercase hex characters.")
    update(reference, status="ACTIVE", activated_at=db.clock)
    return one(reference)


# ==========================================================================
# IngestionBatch
# ==========================================================================
@core.route("/ingestion-batches", methods=["POST"])
@api
def create_batch():
    user_id, role = authorize("RightsHolderRep")
    payload = body()
    holder_id = req_id(payload, "rights_holder_id", db.rights_holders, "ERR_RIGHTS_HOLDER_NOT_FOUND")
    item_count = req_int(payload, "item_count", 1, 10000)
    holder = resolve_fk(holder_id, db.rights_holders, "ERR_RIGHTS_HOLDER_NOT_FOUND")
    own_holder(role, user_id, holder["id"])

    services.require_safe_harbor_eligible(None)
    if holder["enrollment_status"] != "ENROLLED":
        fail("ERR_RIGHTS_HOLDER_NOT_ENROLLED", "The rights holder is not ENROLLED.")
    if holder["program_tier"] not in ("VERIFIED", "TRUSTED"):
        fail("ERR_PROGRAM_TIER_INSUFFICIENT", "program_tier must be VERIFIED or TRUSTED.")

    lower = calc.window_start(db.clock)
    window_total = 0
    for batch in db.batches.values():
        if batch["rights_holder_id"] != holder["id"]:
            continue
        if batch["status"] not in ("ACCEPTED", "PROCESSING", "COMPLETED"):
            continue
        accepted = batch["accepted_at"]
        if accepted is None or accepted < lower or accepted > db.clock:
            continue
        window_total += batch["item_count"]
    rolling = window_total + item_count
    if rolling > holder["daily_item_quota"]:
        fail("ERR_INGESTION_WINDOW_QUOTA_EXCEEDED", "daily_item_quota would be exceeded.")

    batch = create(
        db.batches,
        {
            "rights_holder_id": holder["id"],
            "item_count": item_count,
            "rolling_item_total": rolling,
            "status": "ACCEPTED",
            "notices_created": 0,
            "matched_count": 0,
            "unmatched_count": 0,
            "accepted_at": db.clock,
        },
    )
    return created(batch)


@core.route("/ingestion-batches/<batch_id>", methods=["GET"])
@api
def read_batch(batch_id):
    authorize("ComplianceOfficer", "TakedownAgent", "RightsHolderRep")
    return one(path_batch(batch_id))


@core.route("/ingestion-batches/<batch_id>/complete", methods=["POST"])
@api
def complete_batch(batch_id):
    user_id, role = authorize("RightsHolderRep")
    batch = path_batch(batch_id)
    own_holder(role, user_id, batch["rights_holder_id"])
    if batch["status"] != "PROCESSING":
        fail("ERR_INVALID_BATCH_STATE", "Only a PROCESSING batch may be completed.")
    notices = [n for n in db.notices.values() if n["ingestion_batch_id"] == batch["id"]]
    for notice in notices:
        if notice["status"] not in ("PROCESSED", "REJECTED", "WITHDRAWN", "CLOSED"):
            fail("ERR_INVALID_BATCH_STATE", "A notice of this batch is still in progress.")
    update(
        batch,
        status="COMPLETED",
        matched_count=sum(n["matched_claim_count"] for n in notices),
        unmatched_count=sum(n["unmatched_url_count"] for n in notices),
    )
    return one(batch)


@core.route("/ingestion-batches/<batch_id>/reject", methods=["POST"])
@api
def reject_batch(batch_id):
    authorize("ComplianceOfficer")
    batch = path_batch(batch_id)
    if batch["status"] != "ACCEPTED" or batch["notices_created"] != 0:
        fail("ERR_INVALID_BATCH_STATE", "Only an empty ACCEPTED batch may be rejected.")
    update(batch, status="REJECTED")
    return one(batch)


# ==========================================================================
# SafeHarborAudit
# ==========================================================================
@core.route("/safe-harbor-audits", methods=["POST"])
@api
def create_audit():
    authorize("ComplianceOfficer")
    payload = body()
    provider_id = req_id(payload, "provider_id", db.providers, "ERR_PROVIDER_NOT_FOUND")
    provider = resolve_fk(provider_id, db.providers, "ERR_PROVIDER_NOT_FOUND")
    audit = services.run_audit(provider)
    return created(audit)


@core.route("/safe-harbor-audits/<audit_id>", methods=["GET"])
@api
def read_audit(audit_id):
    authorize("ComplianceOfficer", "AbuseInvestigator")
    return one(path_audit(audit_id))
