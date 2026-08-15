"""Payload factories — one per creatable entity, input fields only."""
import itertools

from .constants import FLAT_LOCAL, PCT_LOCAL

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_local_payload(name=None, method="PCT", **overrides) -> dict:
    """Local charter payload. method='PCT' or 'FLAT' selects the dues branch."""
    base = dict(PCT_LOCAL if method == "PCT" else FLAT_LOCAL)
    base["name"] = name or f"Local {_n()}"
    base.update(overrides)
    return base


def create_classification_payload(code="JOURNEYMAN", min_monthly_dues_cents=3000, **overrides) -> dict:
    payload = {"code": code, "min_monthly_dues_cents": min_monthly_dues_cents}
    payload.update(overrides)
    return payload


def create_employer_payload(name=None, **overrides) -> dict:
    payload = {"name": name or f"Employer {_n()}"}
    payload.update(overrides)
    return payload


def create_member_payload(local_id, classification_id, full_name=None,
                          member_number=None, joined_at="2026-01-15",
                          employer_id=None, **overrides) -> dict:
    n = _n()
    payload = {
        "local_id": local_id,
        "classification_id": classification_id,
        "full_name": full_name or f"Member {n}",
        "member_number": member_number or f"M-{n:05d}",
        "joined_at": joined_at,
    }
    if employer_id is not None:
        payload["employer_id"] = employer_id
    payload.update(overrides)
    return payload


def create_assessment_run_payload(local_id, period) -> dict:
    return {"local_id": local_id, "period": period}


def create_remittance_payload(employer_id, local_id, period, remitted_cents) -> dict:
    return {
        "employer_id": employer_id,
        "local_id": local_id,
        "period": period,
        "remitted_cents": remitted_cents,
    }


def create_remittance_line_payload(member_id, deducted_cents, gross_wages_cents) -> dict:
    return {
        "member_id": member_id,
        "deducted_cents": deducted_cents,
        "gross_wages_cents": gross_wages_cents,
    }


def create_payment_payload(amount_cents) -> dict:
    return {"amount_cents": amount_cents}


def create_transfer_payload(to_local_id, effective_period, expected_member_version) -> dict:
    return {
        "to_local_id": to_local_id,
        "effective_period": effective_period,
        "expected_member_version": expected_member_version,
    }


def create_percapita_report_payload(period, expected_local_version) -> dict:
    return {"period": period, "expected_local_version": expected_local_version}


def create_election_payload(title=None, nomination_open_at="2026-09-01T00:00:00Z",
                            nomination_close_at="2026-09-15T00:00:00Z",
                            eligibility_cutoff_at="2026-09-20T00:00:00Z",
                            **overrides) -> dict:
    payload = {
        "title": title or f"Election {_n()}",
        "nomination_open_at": nomination_open_at,
        "nomination_close_at": nomination_close_at,
        "eligibility_cutoff_at": eligibility_cutoff_at,
    }
    payload.update(overrides)
    return payload


def create_set_rate_payload(chargeable_share_pct) -> dict:
    return {"chargeable_share_pct": chargeable_share_pct}


def create_resolve_dispute_payload(note="accept union-assessed amounts") -> dict:
    return {"resolution_note": note}
