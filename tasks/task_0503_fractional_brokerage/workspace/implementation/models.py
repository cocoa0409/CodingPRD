"""Entity construction and serialization (SCAFFOLD §1.1, PRD §2.4).

Records are plain dicts stored in db. Common system fields:
  id, created_at, updated_at, version  (full set for the 10 mutable entities)
  id, created_at                       (Security, Fill — immutable reference records)

`_seq` is an internal monotonic ordering key (NOT serialized) used to break
created_at ties for default ascending-by-creation sort and FIFO lot ordering.
"""
from db import db, new_id, created_ts


def _base_full():
    ts = created_ts()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def _base_ref():
    return {
        "id": new_id(),
        "created_at": created_ts(),
        "_seq": db.next_seq(),
    }


def touch(record):
    """Mutation bookkeeping: refresh updated_at and bump version (PRD §2.4)."""
    record["updated_at"] = created_ts()
    record["version"] = record.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Serializers — strip internal keys and present declared fields.
# ---------------------------------------------------------------------------
def _clean(record, extra_hidden=()):
    """Serialize a record, dropping any internal key (those starting with '_')."""
    hidden = set(extra_hidden)
    return {k: v for k, v in record.items()
            if not k.startswith("_") and k not in hidden}


def account_dict(a):
    from services.account import recompute_account
    recompute_account(a)
    return _clean(a, extra_hidden=("_dt_events",))


def security_dict(s):
    return _clean(s)


def deposit_dict(d):
    return _clean(d)


def order_dict(o):
    return _clean(o)


def fill_dict(f):
    return _clean(f)


def settlement_dict(s):
    return _clean(s)


def position_dict(p):
    return _clean(p)


def lot_dict(l):
    return _clean(l)


def disposal_dict(d):
    return _clean(d)


def dividend_dict(d):
    return _clean(d)


def options_approval_dict(o):
    return _clean(o)


def margin_call_dict(m):
    return _clean(m)


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------
def make_account(holder_email, account_type):
    rec = _base_full()
    rec.update({
        "holder_email": holder_email,
        "account_type": account_type,
        "options_level": 0,
        "trading_status": "ACTIVE",
        "settled_cash_cents": 0,
        "unsettled_cash_cents": 0,
        "instant_credit_cents": 0,
        "buying_power_cents": 0,
        "account_equity_cents": 0,
        "maintenance_requirement_cents": 0,
        "maintenance_excess_cents": 0,
        "day_trade_count": 0,
        "pdt_flagged": False,
        "compliance_hold": False,
        # internal: day-trade detection events [{date, count}]
        "_dt_events": [],
    })
    db.accounts[rec["id"]] = rec
    return rec


def make_security(symbol, instrument_type, last_price_cents, fractional_enabled,
                  maintenance_rate_bps, required_options_level, extended_hours_eligible):
    rec = _base_ref()
    rec.update({
        "symbol": symbol,
        "instrument_type": instrument_type,
        "last_price_cents": last_price_cents,
        "fractional_enabled": fractional_enabled,
        "maintenance_rate_bps": maintenance_rate_bps,
        "required_options_level": required_options_level,
        "extended_hours_eligible": extended_hours_eligible,
    })
    db.securities[rec["id"]] = rec
    return rec
