"""PayoutBatch and Payment services."""

from decimal import Decimal
from collections import defaultdict

from db import store
from errors import raise_err
from clock import clock
from util import get_str, get_enum, parse_iso8601, round_half_up_cents


TAX_RATES = {
    "US": Decimal("0.30"),
    "GB": Decimal("0.20"),
    "DE": Decimal("0.26"),
    "JP": Decimal("0.20"),
    "CN": Decimal("0.10"),
    "FR": Decimal("0.25"),
    "IE": Decimal("0.20"),
}


def serialize_batch(b: dict) -> dict:
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "cycle_tag": b["cycle_tag"],
        "scheduled_run_at": b["scheduled_run_at"],
        "status": b["status"],
        "total_payments": b["total_payments"],
        "total_paid_cents_by_currency": b.get("total_paid_cents_by_currency", {}),
    }


def serialize_payment(p: dict) -> dict:
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "payout_batch_id": p["payout_batch_id"],
        "rights_holder_id": p["rights_holder_id"],
        "currency": p["currency"],
        "gross_cents": p["gross_cents"],
        "tax_withheld_cents": p["tax_withheld_cents"],
        "net_payable_cents": p["net_payable_cents"],
        "routing_channel": p["routing_channel"],
        "status": p["status"],
        "retry_count": p["retry_count"],
        "last_failure_reason": p.get("last_failure_reason"),
        "drained_micro_balance_cents": p.get("drained_micro_balance_cents", 0),
    }


def _select_routing_channel(holder: dict) -> str:
    currency = holder["payout_currency"]
    if currency == "USD":
        return "ACH"
    elif currency == "EUR":
        return "SEPA"
    elif currency == "GBP":
        return "SWIFT"
    elif currency == "JPY":
        return "LOCAL_JP"
    elif currency == "CNY":
        return "LOCAL_CN"
    return "SWIFT"


def _get_effective_holder_for_routing(holder: dict):
    """For minors, routing uses guardian's bank token. Returns (routing_holder, missing_guardian_flag)."""
    if holder.get("is_minor"):
        gid = holder.get("guardian_holder_id")
        if not gid:
            return None, True
        guardian = store.rights_holders.get(gid)
        if not guardian:
            return None, True
        # Also check guardian binding via AgencyBinding (the PRD describes "active guardian binding").
        # We interpret it as: guardian_holder exists and is non-minor.
        if guardian.get("is_minor"):
            return None, True
        return guardian, False
    return holder, False


def generate_payout_batch(body: dict) -> dict:
    cycle_tag = get_str(body, "cycle_tag", min_len=1, max_len=32)
    sra_str = get_str(body, "scheduled_run_at")
    parse_iso8601(sra_str)

    with store.lock:
        # Unique cycle_tag.
        for b in store.payout_batches.values():
            if b["cycle_tag"] == cycle_tag:
                raise_err("ERR_DUPLICATE_CYCLE", "Duplicate cycle_tag")

        # Pre-check: any holder with FROZEN or PENDING distributions involved is fine; minors must
        # have an active guardian binding (the PRD says "minor lacking an active guardian binding").
        # We need to identify candidates first.
        # Compute candidates per (holder, currency).
        candidates = defaultdict(list)  # (holder_id, currency) -> list of distributions
        for d in store.distributions.values():
            if d["status"] != "RELEASED":
                continue
            pool = store.royalty_pools.get(d["royalty_pool_id"])
            if not pool or pool["status"] != "DISTRIBUTED":
                continue
            holder = store.rights_holders.get(d["rights_holder_id"])
            if not holder:
                continue
            if pool["pool_currency"] != holder["payout_currency"]:
                # currency mismatch: excluded
                continue
            key = (holder["id"], pool["pool_currency"])
            candidates[key].append(d)

        # Pre-validate minors among any candidate holders.
        candidate_holder_ids = {hid for (hid, _) in candidates.keys()}
        # Also check holders with non-zero micro-balance that would be drained or accumulated.
        for mb in store.micro_balances.values():
            if mb["balance_cents"] > 0:
                candidate_holder_ids.add(mb["rights_holder_id"])

        for hid in candidate_holder_ids:
            holder = store.rights_holders.get(hid)
            if not holder:
                continue
            if holder.get("is_minor"):
                _, missing_guardian = _get_effective_holder_for_routing(holder)
                if missing_guardian:
                    raise_err("ERR_MINOR_PAYOUT_BLOCKED", "Minor without active guardian")

        # Create the batch.
        batch = store.common_fields()
        batch.update({
            "cycle_tag": cycle_tag,
            "scheduled_run_at": sra_str,
            "status": "PENDING",
            "total_payments": 0,
            "total_paid_cents_by_currency": {},
        })
        store.payout_batches[batch["id"]] = batch

        # Pick the most-recent DistributionRuleVersion to source thresholds. Use highest effective_from
        # that is <= now.
        now = clock.now()
        rules_sorted = sorted(store.distribution_rule_versions.values(),
                              key=lambda r: r["effective_from"], reverse=True)
        active_rules = [r for r in rules_sorted if parse_iso8601(r["effective_from"]) <= now]
        # Use the most-recent rule (any channel). If none, default to 0/0.
        if active_rules:
            minimum_payout = active_rules[0]["minimum_payout_cents"]
            micro_cap = active_rules[0]["micro_accumulation_cap_cents"]
        else:
            minimum_payout = 0
            micro_cap = 0

        total_payments = 0
        # For each (holder, currency), compute payment.
        for (hid, currency), dists in candidates.items():
            holder = store.rights_holders[hid]
            base_amount = sum(d["net_after_commission_cents"] for d in dists)
            mb_key = f"{hid}|{currency}"
            mb = store.micro_balances.get(mb_key)
            drained_micro = mb["balance_cents"] if mb else 0
            gross_candidate = base_amount + drained_micro

            # Pinned order: micro-cap FIRST, minimum-payout SECOND.
            if gross_candidate < minimum_payout:
                # Below threshold - check cap.
                if (drained_micro + base_amount) > micro_cap:
                    # Forced payout: drain micro to 0, base paid.
                    payment = _create_payment(
                        batch_id=batch["id"], holder=holder, currency=currency,
                        gross_cents=gross_candidate, drained_micro=drained_micro,
                    )
                    if mb:
                        mb["balance_cents"] = 0
                        store.touch(mb)
                    # Mark candidate distributions toward PAID on PSP success: keep RELEASED, link is via holder/currency.
                    total_payments += 1
                else:
                    # No Payment row; increment micro_balance and mark distributions PAID (consumed).
                    if not mb:
                        mb_row = store.common_fields()
                        mb_row.update({
                            "rights_holder_id": hid,
                            "currency": currency,
                            "balance_cents": 0,
                        })
                        store.micro_balances[mb_key] = mb_row
                        mb = mb_row
                    mb["balance_cents"] += base_amount
                    store.touch(mb)
                    for d in dists:
                        d["status"] = "PAID"
                        store.touch(d)
            else:
                # At/above threshold: create Payment.
                payment = _create_payment(
                    batch_id=batch["id"], holder=holder, currency=currency,
                    gross_cents=gross_candidate, drained_micro=drained_micro,
                )
                if mb:
                    mb["balance_cents"] = 0
                    store.touch(mb)
                total_payments += 1

        batch["total_payments"] = total_payments
        store.touch(batch)
        return serialize_batch(batch)


def _create_payment(*, batch_id: str, holder: dict, currency: str, gross_cents: int, drained_micro: int):
    """Create a Payment row inside the locked store."""
    tax_rate = TAX_RATES.get(holder["tax_jurisdiction"], Decimal("0.30"))
    tax = round_half_up_cents(Decimal(gross_cents) * tax_rate)
    net = gross_cents - tax
    # Routing holder for minors.
    routing_holder, missing = _get_effective_holder_for_routing(holder)
    routing_channel = _select_routing_channel(routing_holder or holder)
    pay = store.common_fields()
    pay.update({
        "payout_batch_id": batch_id,
        "rights_holder_id": holder["id"],
        "currency": currency,
        "gross_cents": gross_cents,
        "tax_withheld_cents": tax,
        "net_payable_cents": net,
        "routing_channel": routing_channel,
        "status": "QUEUED",
        "retry_count": 0,
        "last_failure_reason": None,
        "drained_micro_balance_cents": drained_micro,
    })
    store.payments[pay["id"]] = pay
    return pay


def execute_batch(batch_id: str, body) -> dict:
    with store.lock:
        b = store.payout_batches.get(batch_id)
        if not b:
            raise_err("ERR_NOT_FOUND", "PayoutBatch not found")
        if b["status"] != "PENDING":
            raise_err("ERR_INVALID_STATE", "Batch not PENDING")
        now = clock.now()
        sra = parse_iso8601(b["scheduled_run_at"])
        if now < sra:
            raise_err("ERR_INVALID_STATE", "Before scheduled_run_at")
        if isinstance(body, dict) and body.get("version") is not None:
            if body["version"] != b["version"]:
                raise_err("ERR_VERSION_CONFLICT", "Version conflict")
        b["status"] = "RUNNING"
        store.touch(b)
        # For each payment in this batch, flip QUEUED → SENT and emit an ExternalSyncEvent.
        for pay in store.payments.values():
            if pay["payout_batch_id"] == batch_id and pay["status"] == "QUEUED":
                pay["status"] = "SENT"
                store.touch(pay)
                ev = store.lean_fields()
                ev.update({
                    "target_system": "PAYMENT_PSP",
                    "event_kind": "PAYMENT_INITIATED",
                    "related_entity_kind": "Payment",
                    "related_entity_id": pay["id"],
                    "payload": {
                        "payment_id": pay["id"],
                        "gross_cents": pay["gross_cents"],
                        "net_payable_cents": pay["net_payable_cents"],
                        "currency": pay["currency"],
                        "routing_channel": pay["routing_channel"],
                    },
                })
                store.external_sync_events[ev["id"]] = ev
        return serialize_batch(b)


def get_batch(batch_id: str) -> dict:
    with store.lock:
        b = store.payout_batches.get(batch_id)
        if not b:
            raise_err("ERR_NOT_FOUND", "PayoutBatch not found")
        return serialize_batch(b)


def list_payments(batch_id: str, args):
    from util import parse_pagination
    limit, offset = parse_pagination(args)
    status = args.get("status")
    with store.lock:
        b = store.payout_batches.get(batch_id)
        if not b:
            raise_err("ERR_NOT_FOUND", "PayoutBatch not found")
        rows = [p for p in store.payments.values() if p["payout_batch_id"] == batch_id]
        if status:
            rows = [p for p in rows if p["status"] == status]
        rows.sort(key=lambda r: r["created_at"])
        total = len(rows)
        page = rows[offset:offset + limit]
        return [serialize_payment(p) for p in page], total, limit, offset


def retry_payment(payment_id: str, body) -> dict:
    with store.lock:
        p = store.payments.get(payment_id)
        if not p:
            raise_err("ERR_NOT_FOUND", "Payment not found")
        if p["status"] != "FAILED":
            raise_err("ERR_INVALID_STATE", "Payment not FAILED")
        if p["retry_count"] >= 3:
            raise_err("ERR_INVALID_STATE", "Retry limit reached")
        if isinstance(body, dict) and body.get("version") is not None:
            if body["version"] != p["version"]:
                raise_err("ERR_VERSION_CONFLICT", "Version conflict")
        p["retry_count"] += 1
        p["status"] = "RETRYING"
        store.touch(p)
        return serialize_payment(p)


def abandon_payment(payment_id: str, body) -> dict:
    if not isinstance(body, dict):
        raise_err("ERR_VALIDATION", "body required")
    policy = body.get("policy")
    if policy not in ("FORFEIT", "RETURN_TO_MICRO"):
        raise_err("ERR_VALIDATION", "policy must be FORFEIT or RETURN_TO_MICRO")
    with store.lock:
        p = store.payments.get(payment_id)
        if not p:
            raise_err("ERR_NOT_FOUND", "Payment not found")
        if p["status"] != "FAILED":
            raise_err("ERR_INVALID_STATE", "Payment must be FAILED to abandon")
        if p["retry_count"] < 3:
            raise_err("ERR_INVALID_STATE", "retry_count must be >= 3 to abandon")
        if body.get("version") is not None:
            if body["version"] != p["version"]:
                raise_err("ERR_VERSION_CONFLICT", "Version conflict")
        p["status"] = "ABANDONED"
        store.touch(p)
        # Associated Distributions: identify those for this holder/currency in RELEASED state.
        affected_dists = [d for d in store.distributions.values()
                          if d["rights_holder_id"] == p["rights_holder_id"]
                          and d["status"] == "RELEASED"
                          and store.royalty_pools.get(d["royalty_pool_id"], {}).get("pool_currency") == p["currency"]]
        if policy == "FORFEIT":
            for d in affected_dists:
                d["status"] = "FORFEITED"
                store.touch(d)
                pool = store.royalty_pools.get(d["royalty_pool_id"])
                if pool:
                    pool["net_distributable_cents"] = pool.get("net_distributable_cents", 0) + d["gross_amount_cents"]
                    store.touch(pool)
        else:  # RETURN_TO_MICRO
            mb_key = f"{p['rights_holder_id']}|{p['currency']}"
            mb = store.micro_balances.get(mb_key)
            if not mb:
                mb_row = store.common_fields()
                mb_row.update({
                    "rights_holder_id": p["rights_holder_id"],
                    "currency": p["currency"],
                    "balance_cents": 0,
                })
                store.micro_balances[mb_key] = mb_row
                mb = mb_row
            total_returning = sum(d["net_after_commission_cents"] for d in affected_dists)
            mb["balance_cents"] += total_returning
            store.touch(mb)
            for d in affected_dists:
                d["status"] = "PAID"  # consumed into micro
                store.touch(d)
        return serialize_payment(p)


def psp_callback(body) -> dict:
    if not isinstance(body, dict):
        raise_err("ERR_VALIDATION", "body required")
    payment_id = get_str(body, "payment_id")
    outcome = get_enum(body, "outcome", {"SUCCESS", "FAILURE"})
    reason = body.get("reason")
    with store.lock:
        p = store.payments.get(payment_id)
        if not p:
            raise_err("ERR_NOT_FOUND", "Payment not found")
        if p["status"] != "SENT":
            raise_err("ERR_INVALID_STATE", "Payment not SENT")
        if outcome == "SUCCESS":
            p["status"] = "SUCCEEDED"
            store.touch(p)
            # Cascade associated Distribution RELEASED → PAID for this holder/currency.
            for d in store.distributions.values():
                if (d["rights_holder_id"] == p["rights_holder_id"]
                        and d["status"] == "RELEASED"
                        and store.royalty_pools.get(d["royalty_pool_id"], {}).get("pool_currency") == p["currency"]):
                    d["status"] = "PAID"
                    store.touch(d)
            # Update batch counters.
            b = store.payout_batches.get(p["payout_batch_id"])
            if b:
                cur = p["currency"]
                paid_map = b.setdefault("total_paid_cents_by_currency", {})
                paid_map[cur] = paid_map.get(cur, 0) + p["net_payable_cents"]
                store.touch(b)
            # Update holder lifetime paid.
            store.holder_lifetime_paid_cents[p["rights_holder_id"]] = (
                store.holder_lifetime_paid_cents.get(p["rights_holder_id"], 0) + p["net_payable_cents"]
            )
            # If all SENT/RUNNING payments for this batch are no longer SENT, mark batch COMPLETED.
            if b:
                outstanding = any(
                    pp["payout_batch_id"] == b["id"] and pp["status"] in ("SENT", "QUEUED", "RETRYING")
                    for pp in store.payments.values()
                )
                if not outstanding and b["status"] == "RUNNING":
                    b["status"] = "COMPLETED"
                    store.touch(b)
            # ExternalSyncEvent
            ev = store.lean_fields()
            ev.update({
                "target_system": "PAYMENT_PSP",
                "event_kind": "PAYMENT_SUCCEEDED",
                "related_entity_kind": "Payment",
                "related_entity_id": p["id"],
                "payload": {"payment_id": p["id"], "outcome": "SUCCESS"},
            })
            store.external_sync_events[ev["id"]] = ev
        else:  # FAILURE
            p["status"] = "FAILED"
            p["last_failure_reason"] = reason
            store.touch(p)
            ev = store.lean_fields()
            ev.update({
                "target_system": "PAYMENT_PSP",
                "event_kind": "PAYMENT_FAILED",
                "related_entity_kind": "Payment",
                "related_entity_id": p["id"],
                "payload": {"payment_id": p["id"], "outcome": "FAILURE", "reason": reason},
            })
            store.external_sync_events[ev["id"]] = ev
        return serialize_payment(p)
