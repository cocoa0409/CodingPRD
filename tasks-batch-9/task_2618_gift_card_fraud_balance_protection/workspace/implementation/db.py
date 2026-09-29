"""In-memory data store. Nothing but the RiskPolicy configuration singleton
(PRD 2.5: "seeded at process start with all of the defaults above") exists at
boot; every entity is created through the declared API surface."""
import uuid

import clock

POLICY_DEFAULTS = {
    "inquiry_velocity_window_minutes": 60,
    "inquiry_velocity_threshold": 5,
    "redemption_window_minutes": 1440,
    "drain_watch_score_threshold": 40,
    "drain_restrict_score_threshold": 70,
    "digital_hold_score_threshold": 45,
    "digital_decline_score_threshold": 75,
    "bulk_identity_threshold_cents": 50000,
    "bulk_quantity_limit": 25,
    "rack_shrink_threshold": 3,
    "rack_seal_break_threshold": 3,
    "floor_heightened_alert_threshold": 2,
    "claim_window_days": 90,
    "claim_evidence_round_limit": 3,
    "reissue_cap_cents": 100000,
    "recovery_factor_bps": 8500,
    "provisional_reserve_rate_bps": 3500,
    "final_reserve_rate_bps": 1000,
}

POLICY_LIMITS = {
    "inquiry_velocity_window_minutes": (1, 10080),
    "inquiry_velocity_threshold": (2, 100),
    "redemption_window_minutes": (1, 43200),
    "drain_watch_score_threshold": (1, 100),
    "drain_restrict_score_threshold": (1, 100),
    "digital_hold_score_threshold": (1, 100),
    "digital_decline_score_threshold": (1, 100),
    "bulk_identity_threshold_cents": (0, None),
    "bulk_quantity_limit": (1, None),
    "rack_shrink_threshold": (1, None),
    "rack_seal_break_threshold": (1, None),
    "floor_heightened_alert_threshold": (1, None),
    "claim_window_days": (1, None),
    "claim_evidence_round_limit": (1, None),
    "reissue_cap_cents": (0, None),
    "recovery_factor_bps": (0, 10000),
    "provisional_reserve_rate_bps": (0, 10000),
    "final_reserve_rate_bps": (0, 10000),
}

TABLES = (
    "stores", "racks", "cards", "issuances", "events", "inquiries",
    "holds", "bulk_orders", "alerts", "claims", "referrals", "listings",
    "periods",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in TABLES:
            setattr(self, name, {})
        self._seq = 0
        self.policy = None
        clock.reset()
        self.bootstrap_policy()

    def next_seq(self):
        self._seq += 1
        return self._seq

    def bootstrap_policy(self):
        now = clock.now()
        rec = {"id": str(uuid.uuid4())}
        rec.update(POLICY_DEFAULTS)
        rec["created_at"] = now
        rec["updated_at"] = now
        rec["version"] = 1
        rec["_seq"] = self.next_seq()
        self.policy = rec


db = Store()


def new_id():
    return str(uuid.uuid4())


def record(fields):
    """Standard record: id + fields + created_at/updated_at/version."""
    now = clock.now()
    rec = {"id": new_id()}
    rec.update(fields)
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def audit_record(fields):
    """Immutable audit record: id + fields + created_at only (PRD 2.4)."""
    rec = {"id": new_id()}
    rec.update(fields)
    rec["created_at"] = clock.now()
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Every mutation bumps version and refreshes updated_at in the same step."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = clock.now()
    return rec


def policy():
    return db.policy


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def sorted_rows(rows, keys):
    """Sort by the given datetime/scalar keys, always tie-broken by created_at
    then insertion order. `id` is never an ordering key (PRD 2.9)."""
    def key(r):
        out = []
        for k in keys:
            out.append(r.get(k))
        out.append(r["created_at"])
        out.append(r["_seq"])
        return tuple(out)
    return sorted(rows, key=key)
