"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import uuid


def _suffix() -> str:
    return uuid.uuid4().hex[:8].upper()


def district_payload(code=None, name="District", max_delegates=3, **overrides):
    defaults = {
        "code": code or f"DIST-{_suffix()}",
        "name": name,
        "max_delegates": max_delegates,
    }
    defaults.update(overrides)
    return defaults


def member_payload(district_id, patron_ref=None, legal_name="Test Farm",
                   member_class="INDIVIDUAL", joined_at="2020-01-01T00:00:00Z",
                   is_producer_member=True, **overrides):
    defaults = {
        "patron_ref": patron_ref or f"P-{_suffix()}",
        "legal_name": legal_name,
        "member_class": member_class,
        "joined_at": joined_at,
        "delegate_district_id": district_id,
        "is_producer_member": is_producer_member,
    }
    defaults.update(overrides)
    return defaults


def fiscal_year_payload(year_code=None, start_date="2025-09-01T00:00:00Z",
                        end_date="2026-08-31T00:00:00Z", net_margin_cents=100000,
                        retained_reserve_pct=0.10, qualified_payout_pct=0.30,
                        **overrides):
    defaults = {
        "year_code": year_code or f"FY-{_suffix()}",
        "start_date": start_date,
        "end_date": end_date,
        "net_margin_cents": net_margin_cents,
        "retained_reserve_pct": retained_reserve_pct,
        "qualified_payout_pct": qualified_payout_pct,
    }
    defaults.update(overrides)
    return defaults


def delivery_payload(member_id, fiscal_year_id, commodity="CORN",
                     gross_bushels=100, dockage_pct=0.0, is_patron_sourced=True,
                     **overrides):
    defaults = {
        "member_id": member_id,
        "fiscal_year_id": fiscal_year_id,
        "commodity": commodity,
        "gross_bushels": gross_bushels,
        "dockage_pct": dockage_pct,
        "is_patron_sourced": is_patron_sourced,
    }
    defaults.update(overrides)
    return defaults


def delegate_payload(member_id, term_start="2025-01-01T00:00:00Z",
                     term_end="2035-01-01T00:00:00Z", **overrides):
    defaults = {
        "member_id": member_id,
        "term_start": term_start,
        "term_end": term_end,
    }
    defaults.update(overrides)
    return defaults


def resolution_payload(kind, subject_ref_id, quorum_required=1,
                       resolution_code=None,
                       voting_opens_at="2000-01-01T00:00:00Z",
                       voting_closes_at="2000-01-02T00:00:00Z", **overrides):
    """Voting window pinned in the far past so a single recorded vote tallies
    immediately (window long closed) regardless of the test's logical clock."""
    defaults = {
        "resolution_code": resolution_code or f"RES-{_suffix()}",
        "kind": kind,
        "subject_ref_id": subject_ref_id,
        "quorum_required": quorum_required,
        "voting_opens_at": voting_opens_at,
        "voting_closes_at": voting_closes_at,
    }
    defaults.update(overrides)
    return defaults


def cycle_payload(cycle_code=None, equity_class="QUALIFIED", target_year_offset=5,
                  window_start="2030-01-01T00:00:00Z",
                  window_end="2030-06-01T00:00:00Z", budget_cap_cents=100000,
                  board_resolution_id="pending-resolution", **overrides):
    defaults = {
        "cycle_code": cycle_code or f"CYC-{_suffix()}",
        "equity_class": equity_class,
        "target_year_offset": target_year_offset,
        "window_start": window_start,
        "window_end": window_end,
        "budget_cap_cents": budget_cap_cents,
        "board_resolution_id": board_resolution_id,
    }
    defaults.update(overrides)
    return defaults


def redemption_request_payload(member_id, kind, certificate_ids,
                               requested_amount_cents, appointment_at,
                               appeal_of_request_id=None, **overrides):
    defaults = {
        "member_id": member_id,
        "kind": kind,
        "certificate_ids": list(certificate_ids),
        "requested_amount_cents": requested_amount_cents,
        "appointment_at": appointment_at,
    }
    if appeal_of_request_id is not None:
        defaults["appeal_of_request_id"] = appeal_of_request_id
    defaults.update(overrides)
    return defaults


def unclaimed_lot_payload(certificate_id, last_known_member_id, dormancy_years=5,
                          state_code="IA", **overrides):
    defaults = {
        "certificate_id": certificate_id,
        "last_known_member_id": last_known_member_id,
        "dormancy_years": dormancy_years,
        "state_code": state_code,
    }
    defaults.update(overrides)
    return defaults
