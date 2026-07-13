"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_organizer_payload(**overrides) -> dict:
    """Input for POST /organizers (PRD §3.1): display_name, email."""
    defaults = {"display_name": "Test Organizer", "email": "organizer@example.com"}
    defaults.update(overrides)
    return defaults


def create_beneficiary_payload(**overrides) -> dict:
    """Input for POST /beneficiaries (PRD §3.1): legal_name, email."""
    defaults = {"legal_name": "Test Beneficiary", "email": "beneficiary@example.com"}
    defaults.update(overrides)
    return defaults


def create_donor_payload(**overrides) -> dict:
    """Input for POST /donors (PRD §3.1): display_name, email, is_anonymous_default?."""
    defaults = {"display_name": "Test Donor", "email": "donor@example.com"}
    defaults.update(overrides)
    return defaults


def create_campaign_payload(beneficiary_id, **overrides) -> dict:
    """Input for POST /campaigns (PRD §3.2): beneficiary_id, title, story,
    goal_cents, category, is_charity?."""
    defaults = {
        "beneficiary_id": beneficiary_id,
        "title": "Test Campaign",
        "story": "A worthy cause.",
        "goal_cents": 500_000,
        "category": "MEDICAL",
    }
    defaults.update(overrides)
    return defaults


def create_team_member_payload(campaign_id, organizer_id, team_role="CO_ORGANIZER", **overrides) -> dict:
    """Input for POST /team-members (PRD §3.3)."""
    defaults = {
        "campaign_id": campaign_id,
        "organizer_id": organizer_id,
        "team_role": team_role,
    }
    defaults.update(overrides)
    return defaults


def create_donation_payload(campaign_id, donor_id, amount_cents=10_000, **overrides) -> dict:
    """Input for POST /donations (PRD §3.4): campaign_id, donor_id, amount_cents,
    tip_cents?, is_anonymous?."""
    defaults = {
        "campaign_id": campaign_id,
        "donor_id": donor_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_update_payload(campaign_id, update_type="UPDATE", body="An update.", **overrides) -> dict:
    """Input for POST /updates (PRD §3.5)."""
    defaults = {
        "campaign_id": campaign_id,
        "update_type": update_type,
        "body": body,
    }
    defaults.update(overrides)
    return defaults


def create_payout_payload(campaign_id, amount_cents, expected_campaign_version, **overrides) -> dict:
    """Input for POST /payouts (PRD §3.7): campaign_id, amount_cents,
    scheduled_at?, expected_campaign_version."""
    defaults = {
        "campaign_id": campaign_id,
        "amount_cents": amount_cents,
        "expected_campaign_version": expected_campaign_version,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(donation_id, reason="FRAUD", **overrides) -> dict:
    """Input for POST /disputes (PRD §3.6): donation_id, reason."""
    defaults = {"donation_id": donation_id, "reason": reason}
    defaults.update(overrides)
    return defaults


def create_hold_payload(campaign_id, reason="Under review", severity="STANDARD", **overrides) -> dict:
    """Input for POST /holds (PRD §3.8): campaign_id, reason, severity, locked_amount_cents?."""
    defaults = {
        "campaign_id": campaign_id,
        "reason": reason,
        "severity": severity,
    }
    defaults.update(overrides)
    return defaults


def create_feature_placement_payload(
    campaign_id, category="HOMEPAGE", slot_index=1,
    window_start="2026-04-01T00:00:00Z", window_end="2026-04-08T00:00:00Z", **overrides
) -> dict:
    """Input for POST /feature-placements (PRD §3.8)."""
    defaults = {
        "campaign_id": campaign_id,
        "category": category,
        "slot_index": slot_index,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults
