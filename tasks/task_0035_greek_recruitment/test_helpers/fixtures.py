"""Composite setup helpers for the Greek-recruitment PRD.

Most interesting tests need the system in a specific state that takes 5-20 API
calls to reach (round-in-MUTUAL_SELECTION-with-preferences-filed,
round-in-BID_DAY-with-bid-proposed, chapter-at-risk-threshold, etc.). These
fixtures encapsulate those preambles so test bodies focus on assertions.

All fixtures use `get_success_data()` (lenient 2xx validator) internally so
that setup failures produce clear "setup failed" assertion errors rather than
confusing downstream failures.

Per PRD §2.1, `ChapterOfficer` and `PNM` are entity-backed roles — ownership
checks compare X-User-ID to the relevant entity id. Fixtures therefore call
`make_chapter_officer_headers(chapter['id'])` / `make_pnm_headers(pnm['id'])`
for every ownership-gated call.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_chapter_payload,
    register_pnm_payload,
    create_round_payload,
    create_party_payload,
    create_invitation_payload,
    create_preference_payload,
    create_bid_match_payload,
    rescind_bid_match_payload,
    create_risk_incident_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_chapter_officer_headers,
    make_pnm_headers,
)

# ─── Tier 0: clock setup ────────────────────────────────────────────────────


def set_clock(iso: str = "2026-09-01T00:00:00Z") -> dict:
    """Pin server clock for deterministic temporal tests (PRD §3.9)."""
    return get_success_data(
        api_client.set_clock(
            set_clock_payload(iso), TEST_USERS["panhellenic_admin_headers"]
        )
    )


# ─── Tier 1: bare-entity creators ───────────────────────────────────────────


def create_chapter(
    name: str = "Test Chapter",
    greek_type: str = "SORORITY",
    quota_total: int = 5,
    dues_per_member_cents: int = 10000,
    legacy_priority_slots: int = 0,
    **overrides,
) -> dict:
    """Create a Chapter (PRD §3.1)."""
    payload = create_chapter_payload(
        name=name,
        greek_type=greek_type,
        quota_total=quota_total,
        dues_per_member_cents=dues_per_member_cents,
        legacy_priority_slots=legacy_priority_slots,
        **overrides,
    )
    return get_success_data(
        api_client.create_chapter(payload, TEST_USERS["panhellenic_admin_headers"])
    )


def create_round(
    cycle_label: str = "Fall 2026",
    bid_day_at: str = "2026-09-15T12:00:00Z",
) -> dict:
    """Create a RecruitmentRound in phase PARTY (PRD §3.1)."""
    payload = create_round_payload(cycle_label=cycle_label, bid_day_at=bid_day_at)
    return get_success_data(
        api_client.create_round(payload, TEST_USERS["panhellenic_admin_headers"])
    )


def register_pnm(
    full_name: str = "Test PNM",
    gpa: float = 3.50,
    legacy_chapter_id: Optional[str] = None,
) -> dict:
    """Self-register a PNM via the public endpoint (PRD §3.1)."""
    payload = register_pnm_payload(
        full_name=full_name, gpa=gpa, legacy_chapter_id=legacy_chapter_id
    )
    return get_success_data(
        api_client.register_pnm(payload, TEST_USERS["anonymous_headers"])
    )


def activate_pnm(pnm_id: str) -> dict:
    """Activate a REGISTERED PNM (PRD §3.1)."""
    return get_success_data(
        api_client.activate_pnm(pnm_id, TEST_USERS["recruitment_chair_headers"])
    )


def register_and_activate_pnm(
    full_name: str = "Test PNM",
    gpa: float = 3.50,
    legacy_chapter_id: Optional[str] = None,
) -> dict:
    """Register then activate a PNM. Returns the activated PNM."""
    pnm = register_pnm(full_name=full_name, gpa=gpa, legacy_chapter_id=legacy_chapter_id)
    return activate_pnm(pnm["id"])


# ─── Tier 2: Party lifecycle helpers ────────────────────────────────────────


def create_party(
    round_id: str,
    chapter_id: str,
    scheduled_start_utc: str = "2026-09-05T18:00:00Z",
    duration_minutes: int = 60,
    capacity: int = 10,
) -> dict:
    """Schedule a party (PRD §3.2). round.phase must be PARTY."""
    payload = create_party_payload(
        round_id=round_id,
        chapter_id=chapter_id,
        scheduled_start_utc=scheduled_start_utc,
        duration_minutes=duration_minutes,
        capacity=capacity,
    )
    return get_success_data(
        api_client.create_party(payload, make_chapter_officer_headers(chapter_id))
    )


def open_party(party_id: str, chapter_id: str) -> dict:
    """SCHEDULED -> OPEN (PRD §3.2)."""
    return get_success_data(
        api_client.open_party(party_id, make_chapter_officer_headers(chapter_id))
    )


def complete_party(party_id: str, chapter_id: str) -> dict:
    """OPEN -> COMPLETED (PRD §3.2)."""
    return get_success_data(
        api_client.complete_party(party_id, make_chapter_officer_headers(chapter_id))
    )


def cancel_party(party_id: str, chapter_id: str) -> dict:
    """SCHEDULED|OPEN -> CANCELLED (PRD §3.2)."""
    return get_success_data(
        api_client.cancel_party(party_id, make_chapter_officer_headers(chapter_id))
    )


def create_and_open_party(
    round_id: str,
    chapter_id: str,
    scheduled_start_utc: str = "2026-09-05T18:00:00Z",
    duration_minutes: int = 60,
    capacity: int = 10,
) -> dict:
    """Create + open. Returns the opened party."""
    party = create_party(
        round_id, chapter_id, scheduled_start_utc, duration_minutes, capacity
    )
    return open_party(party["id"], chapter_id)


# ─── Tier 3: PartyInvitation helpers ────────────────────────────────────────


def create_invitation(party_id: str, pnm_id: str, chapter_id: str) -> dict:
    """Officer issues invitation (PRD §3.3)."""
    payload = create_invitation_payload(party_id=party_id, pnm_id=pnm_id)
    return get_success_data(
        api_client.create_invitation(payload, make_chapter_officer_headers(chapter_id))
    )


def accept_invitation(invitation_id: str, pnm_id: str) -> dict:
    """PNM accepts (PRD §3.3). Ownership-gated on PNM.id."""
    return get_success_data(
        api_client.accept_invitation(invitation_id, make_pnm_headers(pnm_id))
    )


def decline_invitation(invitation_id: str, pnm_id: str) -> dict:
    """PNM declines (PRD §3.3). Ownership-gated on PNM.id."""
    return get_success_data(
        api_client.decline_invitation(invitation_id, make_pnm_headers(pnm_id))
    )


# ─── Tier 4: Preference helpers ─────────────────────────────────────────────


def file_pnm_preference(
    round_id: str, pnm_id: str, chapter_id: str, rank: int = 1
) -> dict:
    """PNM_TO_CHAPTER preference (PRD §3.4). Authored by the PNM."""
    payload = create_preference_payload(
        round_id=round_id,
        side="PNM_TO_CHAPTER",
        pnm_id=pnm_id,
        chapter_id=chapter_id,
        rank=rank,
    )
    return get_success_data(
        api_client.create_preference(payload, make_pnm_headers(pnm_id))
    )


def file_chapter_preference(
    round_id: str, chapter_id: str, pnm_id: str, rank: int = 1
) -> dict:
    """CHAPTER_TO_PNM preference (PRD §3.4). Authored by the chapter officer."""
    payload = create_preference_payload(
        round_id=round_id,
        side="CHAPTER_TO_PNM",
        pnm_id=pnm_id,
        chapter_id=chapter_id,
        rank=rank,
    )
    return get_success_data(
        api_client.create_preference(payload, make_chapter_officer_headers(chapter_id))
    )


# ─── Tier 5: round-phase advance helpers ────────────────────────────────────


def advance_round(round_id: str) -> dict:
    """RecruitmentChair advances the round phase (PRD §3.1, §3.5, §3.7)."""
    return get_success_data(
        api_client.advance_round(round_id, TEST_USERS["recruitment_chair_headers"])
    )


# ─── Tier 6: RiskIncident helpers ───────────────────────────────────────────


def file_risk_incident(
    chapter_id: str,
    severity_points: int = 5,
    reason: str = "incident",
    party_id: Optional[str] = None,
) -> dict:
    """RiskOfficer files an incident (PRD §3.8)."""
    payload = create_risk_incident_payload(
        chapter_id=chapter_id,
        severity_points=severity_points,
        reason=reason,
        party_id=party_id,
    )
    return get_success_data(
        api_client.create_risk_incident(payload, TEST_USERS["risk_officer_headers"])
    )


def dismiss_risk_incident(incident_id: str) -> dict:
    """RiskOfficer dismisses an ACTIVE incident (PRD §3.8)."""
    return get_success_data(
        api_client.dismiss_risk_incident(
            incident_id, TEST_USERS["risk_officer_headers"]
        )
    )


# ─── Tier 7: Composite — one-PNM-attends-one-party-at-chapter ───────────────


def attend_and_complete_party_for_pnm(
    round_id: str,
    chapter_id: str,
    pnm_id: str,
    scheduled_start_utc: str = "2026-09-05T18:00:00Z",
    duration_minutes: int = 60,
    capacity: int = 10,
) -> dict:
    """Create + open party, invite PNM, accept, complete -> PNM has ATTENDED invitation.

    This is the minimum precondition for filing a CHAPTER_TO_PNM preference on
    this PNM at this chapter (PRD §3.4 eligibility gate).
    Returns dict with party, invitation.
    """
    party = create_and_open_party(
        round_id, chapter_id, scheduled_start_utc, duration_minutes, capacity
    )
    inv = create_invitation(party["id"], pnm_id, chapter_id)
    accept_invitation(inv["id"], pnm_id)
    complete_party(party["id"], chapter_id)
    return {"party": party, "invitation": inv}


# ─── Tier 8: Round-in-BID_DAY-with-PROPOSED-bid scenario ────────────────────


def setup_round_with_proposed_bid_via_mutual_selection(
    chapter_name: str = "BidChapter",
    greek_type: str = "SORORITY",
    quota_total: int = 5,
    dues_per_member_cents: int = 50000,
    legacy_priority_slots: int = 0,
    pnm_full_name: str = "BidPNM",
    pnm_gpa: float = 3.50,
    pnm_is_legacy: bool = False,
    cycle_label: str = "Fall 2026 bid",
) -> dict:
    """Run a single chapter / single PNM through mutual selection so that on
    BID_DAY phase there is exactly one PROPOSED BidMatch waiting for accept.

    Returns dict: chapter, pnm, round, party, invitation, bid_match.
    """
    set_clock("2026-09-01T00:00:00Z")
    chapter = create_chapter(
        name=chapter_name,
        greek_type=greek_type,
        quota_total=quota_total,
        dues_per_member_cents=dues_per_member_cents,
        legacy_priority_slots=legacy_priority_slots,
    )
    rnd = create_round(cycle_label=cycle_label)
    legacy_chapter_id = chapter["id"] if pnm_is_legacy else None
    pnm = register_and_activate_pnm(
        full_name=pnm_full_name, gpa=pnm_gpa, legacy_chapter_id=legacy_chapter_id
    )
    party_ctx = attend_and_complete_party_for_pnm(
        rnd["id"], chapter["id"], pnm["id"]
    )
    # PARTY -> MUTUAL_SELECTION
    advance_round(rnd["id"])
    file_pnm_preference(rnd["id"], pnm["id"], chapter["id"], rank=1)
    file_chapter_preference(rnd["id"], chapter["id"], pnm["id"], rank=1)
    # MUTUAL_SELECTION -> BID_DAY (runs allocator)
    advance_round(rnd["id"])
    bids = get_success_data(
        api_client.list_pnm_bid_matches(
            pnm["id"], TEST_USERS["panhellenic_admin_headers"]
        )
    )
    assert bids, "Setup failed: matcher produced no BidMatch for the single mutual pair"
    bid_id = bids[0]["id"]
    bid = get_success_data(
        api_client.get_bid_match(bid_id, TEST_USERS["panhellenic_admin_headers"])
    )
    return {
        "chapter": chapter,
        "pnm": pnm,
        "round": rnd,
        "party": party_ctx["party"],
        "invitation": party_ctx["invitation"],
        "bid_match": bid,
    }


# ─── Tier 9: Round-in-BID_DAY-with-ACCEPTED-bid scenario ────────────────────


def setup_round_with_accepted_bid(
    chapter_name: str = "AcceptChapter",
    greek_type: str = "SORORITY",
    quota_total: int = 5,
    dues_per_member_cents: int = 50000,
    legacy_priority_slots: int = 0,
    pnm_full_name: str = "AcceptPNM",
    pnm_is_legacy: bool = False,
    cycle_label: str = "Fall 2026 acc",
) -> dict:
    """Same as proposed-bid scenario, but the PNM also accepts the bid.

    Returns dict: chapter (refreshed post-accept), pnm (refreshed), round,
    party, invitation, bid_match (refreshed), chapter_version_after_accept.
    """
    ctx = setup_round_with_proposed_bid_via_mutual_selection(
        chapter_name=chapter_name,
        greek_type=greek_type,
        quota_total=quota_total,
        dues_per_member_cents=dues_per_member_cents,
        legacy_priority_slots=legacy_priority_slots,
        pnm_full_name=pnm_full_name,
        pnm_is_legacy=pnm_is_legacy,
        cycle_label=cycle_label,
    )
    bid_id = ctx["bid_match"]["id"]
    pnm_id = ctx["pnm"]["id"]
    accepted_bid = get_success_data(
        api_client.accept_bid_match(bid_id, make_pnm_headers(pnm_id))
    )
    chapter_after = get_success_data(
        api_client.get_chapter(
            ctx["chapter"]["id"], TEST_USERS["panhellenic_admin_headers"]
        )
    )
    pnm_after = get_success_data(
        api_client.get_pnm(pnm_id, TEST_USERS["panhellenic_admin_headers"])
    )
    return {
        "chapter": chapter_after,
        "pnm": pnm_after,
        "round": ctx["round"],
        "party": ctx["party"],
        "invitation": ctx["invitation"],
        "bid_match": accepted_bid,
        "chapter_version_after_accept": chapter_after["version"],
    }


# ─── Tier 10: Chapter at a specific risk-points value ───────────────────────


def raise_chapter_to_risk_points(
    chapter_id: str, target_points: int, party_id: Optional[str] = None
) -> list:
    """File ACTIVE RiskIncidents until cumulative severity_points equals target.

    severity_points must be 1..10 per row, so target_points up to ~30 is fine.
    Returns list of created incidents.
    """
    incidents = []
    remaining = target_points
    idx = 0
    while remaining > 0:
        chunk = min(10, remaining)
        ri = file_risk_incident(
            chapter_id=chapter_id,
            severity_points=chunk,
            reason=f"raise-points-{idx}",
            party_id=party_id,
        )
        incidents.append(ri)
        remaining -= chunk
        idx += 1
    return incidents


# ─── Tier 11: helpers for getting current chapter / version snapshots ───────


def get_chapter(chapter_id: str) -> dict:
    return get_success_data(
        api_client.get_chapter(
            chapter_id, TEST_USERS["panhellenic_admin_headers"]
        )
    )


def get_pnm(pnm_id: str) -> dict:
    return get_success_data(
        api_client.get_pnm(pnm_id, TEST_USERS["panhellenic_admin_headers"])
    )


def get_party(party_id: str) -> dict:
    return get_success_data(
        api_client.get_party(party_id, TEST_USERS["panhellenic_admin_headers"])
    )


def get_invitation(invitation_id: str) -> dict:
    return get_success_data(
        api_client.get_invitation(
            invitation_id, TEST_USERS["panhellenic_admin_headers"]
        )
    )


def get_round(round_id: str) -> dict:
    return get_success_data(
        api_client.get_round(round_id, TEST_USERS["panhellenic_admin_headers"])
    )


def get_bid_match(bid_match_id: str) -> dict:
    return get_success_data(
        api_client.get_bid_match(
            bid_match_id, TEST_USERS["panhellenic_admin_headers"]
        )
    )


def get_risk_incident(incident_id: str) -> dict:
    return get_success_data(
        api_client.get_risk_incident(
            incident_id, TEST_USERS["panhellenic_admin_headers"]
        )
    )


def list_dues_ledger(chapter_id: str) -> list:
    return get_success_data(
        api_client.list_chapter_dues_ledger(
            chapter_id, TEST_USERS["panhellenic_admin_headers"]
        )
    )


def list_bid_match_dues_ledger(bid_match_id: str) -> list:
    return get_success_data(
        api_client.list_bid_match_dues_ledger_entries(
            bid_match_id, TEST_USERS["panhellenic_admin_headers"]
        )
    )


def list_pnm_bid_matches(pnm_id: str) -> list:
    return get_success_data(
        api_client.list_pnm_bid_matches(
            pnm_id, TEST_USERS["panhellenic_admin_headers"]
        )
    )
