"""Public field projections for each entity (drops internal-only keys)."""

# Fields that are internal bookkeeping and never serialized.
_INTERNAL = {"_seq", "checked_in_period_index", "payment_credit_cents"}


def _public(rec):
    return {k: v for k, v in rec.items() if k not in _INTERNAL}


def club_out(rec):
    return _public(rec)


def category_out(rec, computed):
    out = _public(rec)
    # active_member_count is a computed field (PRD §3.1)
    out["active_member_count"] = computed.category_active_member_count(rec["id"])
    return out


def membership_out(rec, computed):
    out = _public(rec)
    # Computed fields refreshed at read time from the ledger (PRD §2.9)
    out["charge_balance_cents"] = computed.membership_charge_balance(rec["id"])
    out["fb_spend_period_cents"] = computed.membership_fb_spend_period(rec["id"])
    out["guest_visits_used_period"] = computed.membership_guest_visits_used(rec["id"])
    return out


def resource_out(rec):
    return _public(rec)


def reservation_out(rec):
    return _public(rec)


def chit_out(rec):
    return _public(rec)


def guest_pass_out(rec):
    return _public(rec)


def assessment_out(rec):
    return _public(rec)


def assessment_charge_out(rec):
    return _public(rec)


def waitlist_out(rec):
    return _public(rec)


def statement_out(rec):
    return _public(rec)
