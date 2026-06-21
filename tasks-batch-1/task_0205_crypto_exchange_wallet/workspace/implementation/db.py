"""In-memory data store. Starts EMPTY on every boot. No seeding."""
import itertools
import uuid

from clock import Clock

# Monotonic sequence to provide a stable tie-break for records created at the
# same logical clock instant (the ledger clock can be frozen across creations).
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.clock = Clock()
        # One dict per entity collection, keyed by id.
        self.accounts = {}
        self.assets = {}              # AssetConfig keyed by id
        self.fee_schedules = {}
        self.balances = {}            # keyed by id
        self.withdrawal_addresses = {}
        self.deposits = {}
        self.withdrawals = {}
        self.travel_rule_records = {}
        self.orders = {}
        self.trades = {}
        self.cost_basis_lots = {}
        self.staking_positions = {}

    # --- lookup helpers -----------------------------------------------------
    def asset_by_symbol(self, symbol):
        for a in self.assets.values():
            if a["symbol"] == symbol:
                return a
        return None

    def fee_schedule_by_tier(self, tier_name):
        for f in self.fee_schedules.values():
            if f["tier_name"] == tier_name:
                return f
        return None

    def account_by_email(self, email):
        for a in self.accounts.values():
            if a["email"] == email:
                return a
        return None

    def balance(self, account_id, asset):
        for b in self.balances.values():
            if b["account_id"] == account_id and b["asset"] == asset:
                return b
        return None

    def get_or_create_balance(self, account_id, asset):
        b = self.balance(account_id, asset)
        if b is not None:
            return b
        now = self.clock.now()
        b = {
            "id": new_id(),
            "account_id": account_id,
            "asset": asset,
            "available_raw": 0.0,
            "reserved_raw": 0.0,
            "held_raw": 0.0,
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": next_seq(),
        }
        self.balances[b["id"]] = b
        return b


db = Store()
