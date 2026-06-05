"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be in a state reached only after
several API calls (register center + OPO, create + finalize a clinical score,
list a candidate, register a donor organ, run allocation, issue an offer, accept
it, record a transplant, ...). These helpers encapsulate those chains so tests
focus on assertions.

Identity threading: TransplantCenter and OrganProcurementOrg are entity_backed
roles. After a center/OPO is created, every ownership-gated call uses
make_center_headers(center_id) / make_opo_headers(opo_id) with the actual id —
never a shared constant.

All setup calls go through get_success_data() (lenient) so a broken precondition
surfaces as a clear "Setup step failed" error.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_transplant_center_payload,
    create_opo_payload,
    create_candidate_payload,
    create_clinical_score_payload,
    create_donor_organ_payload,
    create_match_run_payload,
    create_offer_payload,
    accept_offer_payload,
    create_transplant_payload,
    create_follow_up_payload,
    set_clock_payload,
)
from .test_users import make_admin_headers, make_center_headers, make_opo_headers


# ─── Tier 0: clock & reference data ────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the deterministic clock. Returns the clock object."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), make_admin_headers()))


def create_center(**overrides):
    """Register a transplant center (UNOSAdmin). Returns the center."""
    return get_success_data(
        api_client.create_transplant_center(create_transplant_center_payload(**overrides), make_admin_headers())
    )


def create_opo(**overrides):
    """Register an organ procurement organization (UNOSAdmin). Returns the OPO."""
    return get_success_data(
        api_client.create_opo(create_opo_payload(**overrides), make_admin_headers())
    )


# ─── Tier 1: candidate state progression ───────────────────────────────

def create_candidate(center, **overrides):
    """Create a DRAFT/ACTIVE candidate owned by `center`. Returns the candidate."""
    headers = make_center_headers(center["id"])
    return get_success_data(
        api_client.create_candidate(create_candidate_payload(center["id"], **overrides), headers)
    )


def create_finalized_score(center, candidate, **score_overrides):
    """Create a DRAFT clinical score on `candidate` and finalize it. Returns the
    finalized score."""
    headers = make_center_headers(center["id"])
    score = get_success_data(
        api_client.create_clinical_score(candidate["id"], create_clinical_score_payload(**score_overrides), headers)
    )
    return get_success_data(api_client.finalize_clinical_score(score["id"], headers))


def create_listed_candidate(center, score_overrides=None, **candidate_overrides):
    """Create a candidate, finalize one clinical score, and list it (DRAFT->LISTED).
    Returns the LISTED candidate (re-fetched)."""
    headers = make_center_headers(center["id"])
    candidate = create_candidate(center, **candidate_overrides)
    create_finalized_score(center, candidate, **(score_overrides or {}))
    return get_success_data(api_client.list_candidate(candidate["id"], headers))


# ─── Tier 2: organ + match-run hierarchy ───────────────────────────────

def create_organ(opo, **overrides):
    """Register an AVAILABLE donor organ owned by `opo`. Returns the organ."""
    headers = make_opo_headers(opo["id"])
    return get_success_data(
        api_client.create_donor_organ(create_donor_organ_payload(opo["id"], **overrides), headers)
    )


def run_match(opo, organ, policy_code="STANDARD"):
    """Run allocation against `organ` (AVAILABLE->MATCHING). Returns
    (match_run, organ_after) where organ_after carries the bumped version."""
    headers = make_opo_headers(opo["id"])
    run = get_success_data(
        api_client.create_match_run(
            create_match_run_payload(organ["id"], organ["version"], policy_code), headers
        )
    )
    organ_after = get_success_data(api_client.get_donor_organ(organ["id"], headers))
    return run, organ_after


# ─── Tier 3: offer lifecycle shortcuts ─────────────────────────────────

def issue_offer(opo, organ, candidate, match_run):
    """Issue a targeted offer (OFFERED). Returns (offer, organ_after) with the
    organ's bumped version after issuance."""
    headers = make_opo_headers(opo["id"])
    offer = get_success_data(
        api_client.create_offer(
            create_offer_payload(organ["id"], candidate["id"], match_run["id"], organ["version"]),
            headers,
        )
    )
    organ_after = get_success_data(api_client.get_donor_organ(organ["id"], headers))
    return offer, organ_after


def accept_offer(center, opo, organ, offer):
    """Accept `offer` (OFFERED->ACCEPTED), driving the allocation cascade.
    Returns (offer_after, organ_after)."""
    center_headers = make_center_headers(center["id"])
    accepted = get_success_data(
        api_client.accept_offer(offer["id"], accept_offer_payload(organ["version"]), center_headers)
    )
    organ_after = get_success_data(api_client.get_donor_organ(organ["id"], make_opo_headers(opo["id"])))
    return accepted, organ_after


# ─── Tier 4: composite scenarios reused across many tests ──────────────

def setup_matching_organ_with_offer(center_overrides=None, opo_overrides=None,
                                    candidate_overrides=None, score_overrides=None,
                                    organ_overrides=None, clock="2026-06-01T00:00:00Z",
                                    policy_code="STANDARD"):
    """Build the canonical pre-offer scenario and issue one targeted offer.

    Steps: set clock -> center -> OPO -> LISTED ACTIVE candidate -> AVAILABLE
    organ -> MATCHING run -> one OFFERED offer.

    Returns a dict with keys: center, opo, candidate, organ (post-issue, with the
    bumped version), match_run, offer.
    """
    set_clock(clock)
    center = create_center(**(center_overrides or {}))
    opo = create_opo(**(opo_overrides or {}))
    candidate = create_listed_candidate(
        center, score_overrides=score_overrides, **(candidate_overrides or {})
    )
    organ = create_organ(opo, **(organ_overrides or {}))
    match_run, organ = run_match(opo, organ, policy_code)
    offer, organ = issue_offer(opo, organ, candidate, match_run)
    return {
        "center": center,
        "opo": opo,
        "candidate": candidate,
        "organ": organ,
        "match_run": match_run,
        "offer": offer,
    }


def setup_matching_organ_with_run(center_overrides=None, opo_overrides=None,
                                  candidate_overrides=None, score_overrides=None,
                                  organ_overrides=None, clock="2026-06-01T00:00:00Z",
                                  policy_code="STANDARD"):
    """Like setup_matching_organ_with_offer but stops at the completed run (no
    offer issued). Returns a dict: center, opo, candidate, organ (post-run, with
    bumped version), match_run.
    """
    set_clock(clock)
    center = create_center(**(center_overrides or {}))
    opo = create_opo(**(opo_overrides or {}))
    candidate = create_listed_candidate(
        center, score_overrides=score_overrides, **(candidate_overrides or {})
    )
    organ = create_organ(opo, **(organ_overrides or {}))
    match_run, organ = run_match(opo, organ, policy_code)
    return {
        "center": center,
        "opo": opo,
        "candidate": candidate,
        "organ": organ,
        "match_run": match_run,
    }


def setup_transplant(center_overrides=None, opo_overrides=None,
                     candidate_overrides=None, organ_overrides=None,
                     clock="2026-06-01T00:00:00Z",
                     transplanted_at="2026-06-01T06:00:00Z"):
    """Full chain through a recorded FUNCTIONING transplant.

    Returns a dict: center, opo, candidate, organ, match_run, offer, transplant.
    """
    scenario = setup_matching_organ_with_offer(
        center_overrides=center_overrides, opo_overrides=opo_overrides,
        candidate_overrides=candidate_overrides, organ_overrides=organ_overrides,
        clock=clock,
    )
    center = scenario["center"]
    center_headers = make_center_headers(center["id"])
    accepted, organ_after = accept_offer(center, scenario["opo"], scenario["organ"], scenario["offer"])
    transplant = get_success_data(
        api_client.create_transplant(
            create_transplant_payload(scenario["offer"]["id"], transplanted_at), center_headers
        )
    )
    scenario["offer"] = accepted
    scenario["organ"] = organ_after
    scenario["transplant"] = transplant
    return scenario


def schedule_follow_up(center, transplant, interval_label="M1",
                       scheduled_for="2026-07-01T00:00:00Z", graft_functioning=True):
    """Schedule a follow-up under `transplant`. Returns the SCHEDULED follow-up."""
    headers = make_center_headers(center["id"])
    payload = create_follow_up_payload(
        interval_label=interval_label, scheduled_for=scheduled_for, graft_functioning=graft_functioning
    )
    return get_success_data(api_client.create_follow_up(transplant["id"], payload, headers))
