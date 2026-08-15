"""Composite setup helpers — multi-step preconditions built from PRD-declared
endpoints only. Each helper builds its preconditions from scratch (the runner
restarts the server before every test, so every test starts on an empty
database) and uses get_success_data() so a setup failure surfaces as a clear
"Setup failed" error rather than a confusing assertion failure.
"""
from typing import List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    add_matter_party_payload,
    create_attorney_payload,
    create_conflict_check_payload,
    create_credit_assessment_payload,
    create_engagement_letter_payload,
    create_matter_payload,
    create_party_payload,
    create_waiver_request_payload,
    review_hit_payload,
    set_clock_payload,
    transition_deposit_payload,
    transition_letter_payload,
    transition_waiver_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_headers,
    make_conflicts_partner_headers,
    make_responsible_attorney_headers,
)

FIRM_ADMIN = TEST_USERS["firm_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 1: base actors
# ---------------------------------------------------------------------------

def create_party(legal_name: str, party_type: str = "CORPORATION",
                 affiliate_of_id: Optional[str] = None,
                 aliases: Optional[list] = None) -> dict:
    """Create one party via FirmAdmin. Returns the Party."""
    overrides = {}
    if affiliate_of_id is not None:
        overrides["affiliate_of_id"] = affiliate_of_id
    if aliases is not None:
        overrides["aliases"] = aliases
    resp = api_client.create_party(
        create_party_payload(
            legal_name=legal_name, party_type=party_type, **overrides
        ),
        FIRM_ADMIN,
    )
    return get_success_data(resp, 201)


def create_attorney(full_name: str = "Rachel Attorney", bar_number: str = "BAR001",
                    practice_group: str = "LITIGATION",
                    hire_type: str = "INTERNAL", **extra) -> dict:
    """Onboard one attorney via FirmAdmin. Returns the Attorney."""
    resp = api_client.create_attorney(
        create_attorney_payload(
            full_name=full_name,
            bar_number=bar_number,
            practice_group=practice_group,
            hire_type=hire_type,
            **extra,
        ),
        FIRM_ADMIN,
    )
    return get_success_data(resp, 201)


def create_conflicts_partner(full_name: str = "Pat Partner",
                             bar_number: str = "BAR002") -> dict:
    """Onboard an INTERNAL attorney to act as the conflicts partner."""
    return create_attorney(full_name=full_name, bar_number=bar_number)


# ---------------------------------------------------------------------------
# Tier 2: matter basics
# ---------------------------------------------------------------------------

def create_matter(client_party_id: str, responsible_attorney_id: str,
                  practice_group: str = "LITIGATION",
                  matter_title: str = "M") -> dict:
    """Open intake for a matter (INTAKE / UNCHECKED). Returns the Matter."""
    resp = api_client.create_matter(
        create_matter_payload(
            client_party_id,
            responsible_attorney_id,
            practice_group=practice_group,
            matter_title=matter_title,
        ),
        INTAKE,
    )
    return get_success_data(resp, 201)


def setup_basic_matter(client_name: str = "Client Corp",
                       attorney_name: str = "Rachel Attorney",
                       bar_number: str = "BAR001",
                       practice_group: str = "LITIGATION",
                       matter_title: str = "M") -> Tuple[dict, dict, dict]:
    """Create (client party, responsible attorney, INTAKE matter).
    Returns (party, attorney, matter)."""
    party = create_party(client_name)
    attorney = create_attorney(full_name=attorney_name, bar_number=bar_number)
    matter = create_matter(
        party["id"], attorney["id"],
        practice_group=practice_group, matter_title=matter_title,
    )
    return party, attorney, matter


def add_roster_party(matter_id: str, party_id: str,
                     role_in_matter: str = "ADVERSE") -> dict:
    """Add one party to a matter roster via IntakeSpecialist."""
    resp = api_client.add_matter_party(
        matter_id, add_matter_party_payload(party_id, role_in_matter), INTAKE
    )
    return get_success_data(resp, 201)


# ---------------------------------------------------------------------------
# Tier 3: conflict checks and hits
# ---------------------------------------------------------------------------

def run_conflict_check(matter_id: str, search_variant: str = "STRICT",
                       match_threshold: Optional[int] = None) -> dict:
    """Run a conflict check via IntakeSpecialist. Returns the ConflictCheck."""
    resp = api_client.create_conflict_check(
        matter_id,
        create_conflict_check_payload(search_variant, match_threshold),
        INTAKE,
    )
    return get_success_data(resp, 201)


def list_hits_for_check(check_id: str) -> List[dict]:
    """All hits produced by one check, in the endpoint's deterministic order."""
    resp = api_client.list_conflict_hits(INTAKE, params={"check_id": check_id})
    return get_success_data(resp, 200)


def setup_matter_with_confirmed_hit(
    client_x_name: str = "Conflict X Inc",
    client_y_name: str = "Conflict Y Corp",
    review_note: Optional[str] = "real conflict",
) -> Tuple[dict, dict, dict, dict]:
    """Two matters: M0 (client X) and M1 (client Y, X added ADVERSE on M1).
    A STRICT check on M1 produces one hit (exact normalized match on X);
    the hit is reviewed CONFIRMED by M1's responsible attorney.
    Returns (party_x, party_y, attorney, matter1). The hit id is discoverable
    via the matter's latest check; callers needing it use
    `get_only_hit_for_matter`."""
    p_x = create_party(client_x_name)
    p_y = create_party(client_y_name)
    atty = create_attorney()
    create_matter(p_x["id"], atty["id"], matter_title="M0")
    m1 = create_matter(p_y["id"], atty["id"], matter_title="M1")
    add_roster_party(m1["id"], p_x["id"], "ADVERSE")
    check = run_conflict_check(m1["id"], "STRICT")
    hits = list_hits_for_check(check["id"])
    ra_headers = make_responsible_attorney_headers(atty["id"])
    payload = review_hit_payload("CONFIRMED")
    if review_note is not None:
        payload["note"] = review_note
    resp = api_client.review_conflict_hit(hits[0]["id"], payload, ra_headers)
    get_success_data(resp, 200)
    return p_x, p_y, atty, m1


def get_only_hit_for_matter(matter_id: str) -> dict:
    """Fetch the single hit whose matched matter or check's matter is the given
    matter: list the matter's checks, then the hits of the latest check."""
    resp = api_client.list_matter_conflict_checks(matter_id, INTAKE)
    checks = get_success_data(resp, 200)
    hits = list_hits_for_check(checks[-1]["id"])
    return hits[0]


def setup_matter_with_waiver(
    client_x_name: str = "Waiver X Inc",
    client_y_name: str = "Waiver Y Corp",
    proposed_terms: str = "terms",
) -> Tuple[dict, dict, dict, dict, dict, dict]:
    """Matter M1 BLOCKED on a CONFIRMED hit; a DRAFT waiver exists for the hit.
    Returns (party_x, party_y, attorney, matter1, hit, waiver)."""
    p_x, p_y, atty, m1 = setup_matter_with_confirmed_hit(
        client_x_name, client_y_name
    )
    hit = get_only_hit_for_matter(m1["id"])
    ra_headers = make_responsible_attorney_headers(atty["id"])
    resp = api_client.create_waiver_request(
        m1["id"],
        create_waiver_request_payload(hit["id"], proposed_terms),
        ra_headers,
    )
    waiver = get_success_data(resp, 201)
    return p_x, p_y, atty, m1, hit, waiver


def send_waiver(waiver_id: str, attorney: dict, **extra) -> dict:
    """SEND a DRAFT waiver as its requester. Returns the updated waiver."""
    resp = api_client.transition_waiver_request(
        waiver_id,
        transition_waiver_payload("SEND", **extra),
        make_responsible_attorney_headers(attorney["id"]),
    )
    return get_success_data(resp, 200)


def consent_waiver(waiver_id: str, client_party: dict,
                   consent_document_ref: str = "doc-001") -> dict:
    """RECORD_CONSENT on a SENT waiver as the owning client."""
    resp = api_client.transition_waiver_request(
        waiver_id,
        transition_waiver_payload(
            "RECORD_CONSENT", consent_document_ref=consent_document_ref
        ),
        make_client_headers(client_party["id"]),
    )
    return get_success_data(resp, 200)


def approve_waiver(waiver_id: str, partner: dict) -> dict:
    """APPROVE a CONSENTED waiver as a conflicts partner distinct from the
    requester (segregation of duties)."""
    resp = api_client.transition_waiver_request(
        waiver_id,
        transition_waiver_payload("APPROVE"),
        make_conflicts_partner_headers(partner["id"]),
    )
    return get_success_data(resp, 200)


def setup_matter_with_approved_waiver(
    client_x_name: str = "Approve X Inc",
    client_y_name: str = "Approve Y Corp",
) -> Tuple[dict, dict, dict, dict, dict, dict, dict]:
    """Matter M1 WAIVED: CONFIRMED hit + waiver driven SEND -> RECORD_CONSENT
    -> APPROVE by a distinct conflicts partner.
    Returns (party_x, party_y, attorney, partner, matter1, hit, waiver)."""
    p_x, p_y, atty, m1, hit, waiver = setup_matter_with_waiver(
        client_x_name, client_y_name
    )
    partner = create_conflicts_partner()
    send_waiver(waiver["id"], atty)
    consent_waiver(waiver["id"], p_y)
    approve_waiver(waiver["id"], partner)
    return p_x, p_y, atty, partner, m1, hit, waiver


# ---------------------------------------------------------------------------
# Tier 4: engagement letters, credit, retainer
# ---------------------------------------------------------------------------

def create_letter(matter: dict, attorney: dict,
                  fee_lines: Optional[List[dict]] = None,
                  scope_text: str = "Scope") -> dict:
    """Create a DRAFT engagement letter as the matter's responsible attorney,
    threading the matter's current version as the OCC token."""
    fresh = get_success_data(api_client.get_matter(matter["id"], INTAKE), 200)
    resp = api_client.create_engagement_letter(
        matter["id"],
        create_engagement_letter_payload(
            fresh["version"], fee_lines=fee_lines, scope_text=scope_text
        ),
        make_responsible_attorney_headers(attorney["id"]),
    )
    letter = get_success_data(resp, 201)
    matter["version"] = fresh["version"] + 1  # letter create bumps the matter
    return letter


def issue_letter(letter_id: str, attorney: dict) -> dict:
    """ISSUE a DRAFT letter as the matter's responsible attorney."""
    resp = api_client.transition_engagement_letter(
        letter_id,
        transition_letter_payload("ISSUE"),
        make_responsible_attorney_headers(attorney["id"]),
    )
    return get_success_data(resp, 200)


def record_credit_assessment(matter_id: str,
                             score: int = TEST_DEFAULTS["PRIME_SCORE"]) -> dict:
    """Record a credit assessment via BillingClerk."""
    resp = api_client.create_credit_assessment(
        matter_id, create_credit_assessment_payload(score), BILLING
    )
    return get_success_data(resp, 201)


def get_deposit(matter_id: str) -> dict:
    """The matter's single retainer deposit (must exist)."""
    resp = api_client.list_matter_retainer_deposits(matter_id, BILLING)
    deposits = get_success_data(resp, 200)
    assert len(deposits) == 1, f"expected exactly one deposit, got {len(deposits)}"
    return deposits[0]


def fund_deposit(deposit_id: str, amount_cents: int) -> dict:
    """FUND a deposit via BillingClerk."""
    resp = api_client.transition_retainer_deposit(
        deposit_id, transition_deposit_payload("FUND", amount_cents), BILLING
    )
    return get_success_data(resp, 200)


def refund_deposit(deposit_id: str, amount_cents: int) -> dict:
    """REFUND a deposit via BillingClerk."""
    resp = api_client.transition_retainer_deposit(
        deposit_id, transition_deposit_payload("REFUND", amount_cents), BILLING
    )
    return get_success_data(resp, 200)


def setup_matter_with_issued_letter(
    client_name: str = "Letter Client Inc",
    score: Optional[int] = TEST_DEFAULTS["PRIME_SCORE"],
    fee_lines: Optional[List[dict]] = None,
    matter_title: str = "M",
    attorney_name: str = "Rachel Attorney",
    bar_number: str = "BAR001",
    practice_group: str = "LITIGATION",
) -> Tuple[dict, dict, dict, dict, dict]:
    """Matter M (INTAKE) + optional credit assessment + DRAFT letter + ISSUE.
    The deposit is auto-created at ISSUE. Returns
    (party, attorney, matter, letter, deposit)."""
    party, attorney, matter = setup_basic_matter(
        client_name=client_name,
        attorney_name=attorney_name,
        bar_number=bar_number,
        practice_group=practice_group,
        matter_title=matter_title,
    )
    if score is not None:
        record_credit_assessment(matter["id"], score)
    letter = create_letter(matter, attorney, fee_lines=fee_lines)
    issue_letter(letter["id"], attorney)
    deposit = get_deposit(matter["id"])
    return party, attorney, matter, letter, deposit


def setup_countersign_ready(
    client_name: str = "Countersign Client Inc",
    score: Optional[int] = TEST_DEFAULTS["PRIME_SCORE"],
    fee_lines: Optional[List[dict]] = None,
    fund_amount: Optional[int] = None,
    run_clearing_check: bool = True,
    practice_group: str = "LITIGATION",
) -> Tuple[dict, dict, dict, dict, dict]:
    """Matter M fully ready for COUNTERSIGN: a zero-hit STRICT check (CLEARED),
    a credit assessment (default PRIME 800), an ISSUED letter, and a FUNDED
    deposit (default: funded at exactly the required amount).
    Returns (party, attorney, matter, letter, deposit)."""
    party, attorney, matter = setup_basic_matter(
        client_name=client_name, practice_group=practice_group
    )
    if run_clearing_check:
        run_conflict_check(matter["id"], "STRICT")
    if score is not None:
        record_credit_assessment(matter["id"], score)
    letter = create_letter(matter, attorney, fee_lines=fee_lines)
    issue_letter(letter["id"], attorney)
    deposit = get_deposit(matter["id"])
    amount = deposit["required_cents"] if fund_amount is None else fund_amount
    deposit = fund_deposit(deposit["id"], amount)
    return party, attorney, matter, letter, deposit


def countersign_letter(letter_id: str, client_party: dict) -> dict:
    """COUNTERSIGN an ISSUED letter as the owning client."""
    resp = api_client.transition_engagement_letter(
        letter_id,
        transition_letter_payload("COUNTERSIGN"),
        make_client_headers(client_party["id"]),
    )
    return get_success_data(resp, 200)


def setup_open_matter(
    client_name: str = "Open Client Inc",
    score: int = TEST_DEFAULTS["PRIME_SCORE"],
    practice_group: str = "LITIGATION",
    matter_title: str = "M",
) -> Tuple[dict, dict, dict, dict, dict]:
    """Drive a matter all the way to OPEN: cleared check, PRIME credit, ISSUED
    letter, FUNDED deposit, client COUNTERSIGN.
    Returns (party, attorney, matter_refreshed, letter, deposit)."""
    party, attorney, matter, letter, deposit = setup_countersign_ready(
        client_name=client_name, score=score, practice_group=practice_group
    )
    countersign_letter(letter["id"], party)
    fresh = get_success_data(api_client.get_matter(matter["id"], INTAKE), 200)
    return party, attorney, fresh, letter, deposit


# ---------------------------------------------------------------------------
# Tier 5: ethical walls and clock
# ---------------------------------------------------------------------------

def create_wall(matter_id: str, partner: dict, reason: str,
                excluded_attorney_ids: List[str],
                memo: Optional[str] = None) -> dict:
    """Create an ACTIVE ethical wall as a conflicts partner."""
    from .factories import create_ethical_wall_payload

    resp = api_client.create_ethical_wall(
        matter_id,
        create_ethical_wall_payload(reason, excluded_attorney_ids, memo),
        make_conflicts_partner_headers(partner["id"]),
    )
    return get_success_data(resp, 201)


def setup_matter_with_wall(
    client_name: str = "Wall Client Inc",
    reason: str = "CLIENT_REQUEST",
) -> Tuple[dict, dict, dict, dict, dict, dict]:
    """Matter M (INTAKE) with one ACTIVE wall excluding a non-responsible
    attorney A1. Returns (party, attorney_responsible, attorney_excluded,
    partner, matter, wall)."""
    party = create_party(client_name)
    atty_r = create_attorney(full_name="Rachel Attorney", bar_number="BAR001")
    atty_x = create_attorney(full_name="Aaron Alpha", bar_number="BAR003")
    partner = create_conflicts_partner()
    matter = create_matter(party["id"], atty_r["id"], matter_title="M")
    wall = create_wall(matter["id"], partner, reason, [atty_x["id"]])
    return party, atty_r, atty_x, partner, matter, wall


def set_clock(to_iso8601: str) -> dict:
    """Move the server logical clock (FirmAdmin-only). Returns the clock-set
    response data (current_utc, expired_waiver_ids)."""
    resp = api_client.set_current_utc(set_clock_payload(to_iso8601), FIRM_ADMIN)
    return get_success_data(resp, 200)
