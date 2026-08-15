"""Payload factories — one per creatable resource, input fields only (PRD 3)."""

from .constants import TEST_DEFAULTS


def create_originator_payload(legal_name="Test Originator Co",
                              sec_codes_allowed=("CCD",), **overrides) -> dict:
    """PRD 3.1: registration supplies legal_name and sec_codes_allowed."""
    payload = {
        "legal_name": legal_name,
        "sec_codes_allowed": list(sec_codes_allowed),
    }
    payload.update(overrides)
    return payload


def patch_originator_payload(expected_originator_version, **overrides) -> dict:
    """PRD 2.7/3.1: the update always carries expected_originator_version."""
    payload = {"expected_originator_version": expected_originator_version}
    payload.update(overrides)
    return payload


def create_cutoff_window_payload(window_kind="NEXT_DAY", opens_at_utc="00:00",
                                 closes_at_utc="23:00", per_entry_fee_cents=60,
                                 file_fee_cents=200,
                                 large_entry_surcharge_cents=100,
                                 **overrides) -> dict:
    """PRD 3.2: a window kind, its HH:MM times of day, and its rate card."""
    payload = {
        "window_kind": window_kind,
        "opens_at_utc": opens_at_utc,
        "closes_at_utc": closes_at_utc,
        "per_entry_fee_cents": per_entry_fee_cents,
        "file_fee_cents": file_fee_cents,
        "large_entry_surcharge_cents": large_entry_surcharge_cents,
    }
    payload.update(overrides)
    return payload


def create_ach_file_payload(sec_code="CCD", requested_window_kind="NEXT_DAY",
                            effective_date="2026-08-03", **overrides) -> dict:
    """PRD 3.3: intake supplies sec_code, requested_window_kind, effective_date."""
    payload = {
        "sec_code": sec_code,
        "requested_window_kind": requested_window_kind,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def entry_payload(direction="DEBIT", amount_cents=None, receiver_account="acct-1",
                  receiver_routing=None, **overrides) -> dict:
    """PRD 3.3: each entry supplies direction, amount_cents, receiver fields."""
    payload = {
        "direction": direction,
        "amount_cents": (TEST_DEFAULTS["ENTRY_AMOUNT_CENTS"]
                         if amount_cents is None else amount_cents),
        "receiver_account": receiver_account,
        "receiver_routing": (TEST_DEFAULTS["RECEIVER_ROUTING"]
                             if receiver_routing is None else receiver_routing),
    }
    payload.update(overrides)
    return payload


def make_entry_batch(count, direction="DEBIT", amount_cents=1000,
                     account_prefix="ac") -> list:
    """Build `count` entry payloads with distinct receiver accounts."""
    return [
        entry_payload(direction=direction, amount_cents=amount_cents,
                      receiver_account=f"{account_prefix}-{i:03d}")
        for i in range(count)
    ]


def append_entries_payload(expected_file_version, entries) -> dict:
    """PRD 2.7/3.3: append carries expected_file_version plus the entries list."""
    return {"expected_file_version": expected_file_version, "entries": entries}


def register_return_payload(return_code="R01", **overrides) -> dict:
    payload = {"return_code": return_code}
    payload.update(overrides)
    return payload


def register_noc_payload(noc_code="C01", corrected_data="acct=000111222",
                         **overrides) -> dict:
    payload = {"noc_code": noc_code, "corrected_data": corrected_data}
    payload.update(overrides)
    return payload


def create_reversal_payload(reason="DUPLICATE_ENTRY", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def resolve_risk_case_payload(action="DISMISS", **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def advance_reversal_payload(action="TRANSMIT", **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def advance_batch_payload(action="DISPATCH", **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601) -> dict:
    """PRD 2.4: the clock-set call accepts a to_iso8601 instant."""
    return {"to_iso8601": to_iso8601}
