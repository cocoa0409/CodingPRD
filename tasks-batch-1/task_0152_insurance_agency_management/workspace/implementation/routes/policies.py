"""Policy endpoints (PRD §3.3, §3.4, §3.6, §3.7) and the policy state machine."""
from flask import Blueprint, request

import clock
import serialize
from db import store, new_common, touch
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INVALID_DATE_RANGE,
    ERR_CARRIER_NOT_ACTIVE,
    ERR_LICENSE_NOT_ACTIVE,
    ERR_NOT_APPOINTED,
    ERR_CANCEL_OUT_OF_TERM,
    ERR_REINSTATE_NOT_ALLOWED,
)
from middleware import auth, get_json_body, lookup, check_version, paginate
from response import object_response, array_response
from services import derived
from services import trust
from services.calculations import compute_return_premium
from util import (
    require_str,
    require_int,
    require_enum,
    require_bool,
    parse_dt,
    validate_state_code,
)

bp = Blueprint("policies", __name__)

ALL_ROLES = {"AgencyAdmin", "Producer", "AccountManager", "TrustAccountant"}
CANCEL_REASON = {"INSURED_REQUEST", "NON_PAYMENT", "UNDERWRITING"}


def _make_policy_record(account_id, product_id, writing_producer_id, state_code,
                        annual_premium_cents, effective_date, expiration_date,
                        renewed_from_policy_id, download_source, status):
    term_kind = "RENEWAL" if renewed_from_policy_id else "NEW_BUSINESS"
    rec = new_common()
    rec.update(
        account_id=account_id,
        product_id=product_id,
        writing_producer_id=writing_producer_id,
        renewed_from_policy_id=renewed_from_policy_id,
        state_code=state_code,
        annual_premium_cents=annual_premium_cents,
        effective_date=effective_date,
        expiration_date=expiration_date,
        term_kind=term_kind,
        status=status,
        cancellation_date=None,
        cancellation_reason=None,
        return_premium_cents=0,
        earned_premium_cents=0,
        download_source=download_source,
        # internal bookkeeping (not serialized)
        activated_at=None,
        prior_return_premium_cents=0,
    )
    return rec


@bp.post("/policies")
def create_policy():
    auth({"AgencyAdmin", "Producer", "AccountManager"})
    body = get_json_body()
    account_id = require_str(body, "account_id")
    product_id = require_str(body, "product_id")
    writing_producer_id = require_str(body, "writing_producer_id")
    with store.lock:
        # existence, left to right
        lookup(store.accounts, account_id)
        lookup(store.products, product_id)
        lookup(store.producers, writing_producer_id)
        renewed_from_policy_id = body.get("renewed_from_policy_id")
        if renewed_from_policy_id is not None:
            if not isinstance(renewed_from_policy_id, str):
                raise err(ERR_INVALID_REQUEST, "renewed_from_policy_id must be a string")
            lookup(store.policies, renewed_from_policy_id)

        state_code = validate_state_code(body.get("state_code"))
        annual = require_int(body, "annual_premium_cents")
        if annual <= 0:
            raise err(ERR_INVALID_REQUEST, "annual_premium_cents must be > 0")
        eff = parse_dt(require_str(body, "effective_date"), "effective_date")
        exp = parse_dt(require_str(body, "expiration_date"), "expiration_date")
        acord = require_bool(body, "acord_download", default=False)

        # business: effective strictly before expiration
        if not (eff < exp):
            raise err(ERR_INVALID_DATE_RANGE, "effective_date must be before expiration_date")

        if acord:
            download_source = "ACORD_DOWNLOAD"
            status = "BOUND"
        else:
            download_source = "MANUAL"
            status = "QUOTED"

        rec = _make_policy_record(
            account_id, product_id, writing_producer_id, state_code, annual,
            body["effective_date"], body["expiration_date"], renewed_from_policy_id,
            download_source, status,
        )
        store.policies[rec["id"]] = rec
        return object_response(serialize.policy(rec), 201)


@bp.get("/policies/<pid>")
def get_policy(pid):
    auth(ALL_ROLES)
    rec = lookup(store.policies, pid)
    return object_response(serialize.policy(rec))


@bp.get("/policies")
def list_policies():
    auth(ALL_ROLES)
    account_id = request.args.get("account_id")
    product_id = request.args.get("product_id")
    writing_producer_id = request.args.get("writing_producer_id")
    renewed_from_policy_id = request.args.get("renewed_from_policy_id")
    status = request.args.get("status")
    recs = [
        p
        for p in store.policies.values()
        if (account_id is None or p["account_id"] == account_id)
        and (product_id is None or p["product_id"] == product_id)
        and (writing_producer_id is None or p["writing_producer_id"] == writing_producer_id)
        and (renewed_from_policy_id is None or p["renewed_from_policy_id"] == renewed_from_policy_id)
        and (status is None or p["status"] == status)
    ]
    page, limit, offset, total = paginate(recs)
    return array_response([serialize.policy(p) for p in page], limit, offset, total)


@bp.post("/policies/<pid>/bind")
def bind_policy(pid):
    auth({"Producer"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.policies, pid)
        if rec["status"] != "QUOTED":
            raise err(ERR_INVALID_STATE, "only a QUOTED policy may be bound")
        check_version(rec, body.get("expected_policy_version"), "expected_policy_version")

        product = store.products[rec["product_id"]]
        carrier = store.carriers[product["carrier_id"]]
        wp = rec["writing_producer_id"]

        # Business checks in order: carrier-active, license, appointment (§3.4).
        if carrier["status"] != "ACTIVE":
            raise err(ERR_CARRIER_NOT_ACTIVE, "carrier is not ACTIVE")
        if not derived.has_active_license(wp, rec["state_code"], product["line_of_business"]):
            raise err(ERR_LICENSE_NOT_ACTIVE, "writing producer has no ACTIVE matching license")
        if not derived.has_active_appointment(wp, carrier["id"], rec["state_code"]):
            raise err(ERR_NOT_APPOINTED, "writing producer is not appointed with carrier in state")

        rec["status"] = "BOUND"
        touch(rec)
        return object_response(serialize.policy(rec))


@bp.post("/policies/<pid>/activate")
def activate_policy(pid):
    auth({"AccountManager"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.policies, pid)
        if rec["status"] != "BOUND":
            raise err(ERR_INVALID_STATE, "only a BOUND policy may be activated")
        check_version(rec, body.get("expected_policy_version"), "expected_policy_version")

        # business: server-now >= effective_date
        eff = parse_dt(rec["effective_date"], "effective_date")
        if not (clock.now() >= eff):
            raise err(ERR_INVALID_STATE, "cannot activate before effective_date")

        rec["status"] = "ACTIVE"
        rec["activated_at"] = clock.now_iso_clock()  # statement-period anchor
        # cascade: lock all DRAFT splits for this policy.
        for split in store.commission_splits.values():
            if split["policy_id"] == pid and split["status"] == "DRAFT":
                split["status"] = "LOCKED"
                touch(split)
        touch(rec)
        return object_response(serialize.policy(rec))


@bp.post("/policies/<pid>/cancel")
def cancel_policy(pid):
    auth({"AccountManager"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.policies, pid)
        if rec["status"] not in ("ACTIVE", "REINSTATED"):
            raise err(ERR_INVALID_STATE, "only an ACTIVE/REINSTATED policy may be cancelled")
        check_version(rec, body.get("expected_policy_version"), "expected_policy_version")

        reason = require_enum(body, "cancellation_reason", CANCEL_REASON)
        cancel_dt = parse_dt(require_str(body, "cancellation_date"), "cancellation_date")
        eff = parse_dt(rec["effective_date"], "effective_date")
        exp = parse_dt(rec["expiration_date"], "expiration_date")
        # business: cancellation_date in [effective_date, expiration_date)
        if not (eff <= cancel_dt < exp):
            raise err(ERR_CANCEL_OUT_OF_TERM, "cancellation_date outside policy term")

        rec["status"] = "CANCELLED"
        rec["cancellation_date"] = body["cancellation_date"]
        rec["cancellation_reason"] = reason

        product = store.products[rec["product_id"]]
        return_premium, earned = compute_return_premium(rec, product)
        rec["return_premium_cents"] = return_premium
        rec["earned_premium_cents"] = earned
        rec["prior_return_premium_cents"] = return_premium  # for reinstatement reversal

        # cross-entity: post RETURN_PREMIUM_REFUND of -return_premium to the
        # state's trust account, then recompute balance (derived).
        ta = trust.trust_account_for_state(rec["state_code"])
        if ta is not None and return_premium != 0:
            trust.post_entry(ta["id"], "RETURN_PREMIUM_REFUND", -return_premium, policy_id=pid)
            touch(ta)  # account version bumps on posting (§3.9)

        # Chargeback against the writing producer's commission is realized via
        # the live statement rollup (which reads return_premium_cents + status).
        touch(rec)
        # Account.active_policy_count recomputed at read (derived).
        return object_response(serialize.policy(rec))


@bp.post("/policies/<pid>/reinstate")
def reinstate_policy(pid):
    auth({"AccountManager"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.policies, pid)
        if rec["status"] != "CANCELLED":
            raise err(ERR_INVALID_STATE, "only a CANCELLED policy may be reinstated")
        check_version(rec, body.get("expected_policy_version"), "expected_policy_version")

        # business: reason != UNDERWRITING and server-now < expiration_date
        if rec["cancellation_reason"] == "UNDERWRITING":
            raise err(ERR_REINSTATE_NOT_ALLOWED, "underwriting cancellations are not reinstatable")
        exp = parse_dt(rec["expiration_date"], "expiration_date")
        if not (clock.now() < exp):
            raise err(ERR_REINSTATE_NOT_ALLOWED, "reinstatement only allowed before expiration_date")

        prior_refund = rec.get("prior_return_premium_cents", 0)

        rec["status"] = "REINSTATED"
        rec["return_premium_cents"] = 0
        rec["earned_premium_cents"] = 0
        rec["cancellation_date"] = None
        rec["cancellation_reason"] = None

        # cross-entity compensation: reversing PREMIUM_RECEIPT of +prior_refund.
        ta = trust.trust_account_for_state(rec["state_code"])
        if ta is not None and prior_refund != 0:
            trust.post_entry(ta["id"], "PREMIUM_RECEIPT", prior_refund, policy_id=pid)
            touch(ta)

        rec["prior_return_premium_cents"] = 0
        # chargeback reversal is automatic: rollup no longer sees CANCELLED.
        touch(rec)
        return object_response(serialize.policy(rec))


@bp.post("/policies/<pid>/expire")
def expire_policy(pid):
    auth({"AccountManager"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.policies, pid)
        if rec["status"] != "PENDING_RENEWAL":
            raise err(ERR_INVALID_STATE, "only a PENDING_RENEWAL policy may be expired")
        check_version(rec, body.get("expected_policy_version"), "expected_policy_version")
        exp = parse_dt(rec["expiration_date"], "expiration_date")
        if not (clock.now() >= exp):
            raise err(ERR_INVALID_STATE, "cannot expire before expiration_date")
        rec["status"] = "EXPIRED"
        touch(rec)
        return object_response(serialize.policy(rec))


@bp.post("/policies/<pid>/non-renew")
def non_renew_policy(pid):
    auth({"AccountManager"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.policies, pid)
        if rec["status"] != "PENDING_RENEWAL":
            raise err(ERR_INVALID_STATE, "only a PENDING_RENEWAL policy may be non-renewed")
        check_version(rec, body.get("expected_policy_version"), "expected_policy_version")
        # business: the policy's renewal task must be in stage LOST.
        lost = False
        for t in store.renewal_tasks.values():
            if t["policy_id"] == pid and t["stage"] == "LOST":
                lost = True
                break
        if not lost:
            raise err(ERR_INVALID_STATE, "policy's renewal task is not LOST")
        rec["status"] = "NON_RENEWED"
        touch(rec)
        return object_response(serialize.policy(rec))
