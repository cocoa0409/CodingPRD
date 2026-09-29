"""Role headers for the six roles named in PRD section 2.1.

Five of the six roles carry an **opaque** identity: their `X-User-ID` "is an
operator identifier that is not tied to any persisted entity" and the server
"never compares it to any entity's `id`".  Shared constants are therefore the
right shape for those five, with per-identity builders for the four
segregation-of-duties comparisons.

`OfftakerRep` is different and the difference is load-bearing: "When
`X-User-Role` is `OfftakerRep`, `X-User-ID` is the `id` of the acting
`Offtaker`".  There is consequently **no** shared `OfftakerRep` constant — every
buyer-side call must be built from that buyer's own primary key through
``make_offtaker_rep_headers``.
"""

from prd_bench_local_runner.testing import build_user_headers

# ---------------------------------------------------------------------------
# Operator identities
# ---------------------------------------------------------------------------

ORIGINATOR_ID = "u_orig_1"
ORIGINATOR_SECOND_ID = "u_orig_2"
CREDIT_OFFICER_ID = "u_credit_1"
CREDIT_OFFICER_SECOND_ID = "u_credit_2"
DEAL_COMMITTEE_ID = "u_committee_1"
DEAL_COMMITTEE_SECOND_ID = "u_committee_2"
SETTLEMENT_ANALYST_ID = "u_analyst_1"
REGISTRY_AGENT_ID = "u_registry_1"

#: One natural person who wears two hats.  Used to prove that the four
#: segregation-of-duties comparisons in PRD section 2.8 are made on
#: `X-User-ID` and not on the declared `X-User-Role`.
DUAL_HAT_ID = "u_dual_1"

# ---------------------------------------------------------------------------
# Ready-made headers for the five opaque roles
# ---------------------------------------------------------------------------

ORIGINATOR = build_user_headers(ORIGINATOR_ID, "Originator")
ORIGINATOR_SECOND = build_user_headers(ORIGINATOR_SECOND_ID, "Originator")
CREDIT_OFFICER = build_user_headers(CREDIT_OFFICER_ID, "CreditOfficer")
CREDIT_OFFICER_SECOND = build_user_headers(CREDIT_OFFICER_SECOND_ID, "CreditOfficer")
DEAL_COMMITTEE = build_user_headers(DEAL_COMMITTEE_ID, "DealCommittee")
DEAL_COMMITTEE_SECOND = build_user_headers(DEAL_COMMITTEE_SECOND_ID, "DealCommittee")
SETTLEMENT_ANALYST = build_user_headers(SETTLEMENT_ANALYST_ID, "SettlementAnalyst")
REGISTRY_AGENT = build_user_headers(REGISTRY_AGENT_ID, "RegistryAgent")

#: The dual-hat operator wearing each of its two hats in turn.
DUAL_HAT_CREDIT_OFFICER = build_user_headers(DUAL_HAT_ID, "CreditOfficer")
DUAL_HAT_DEAL_COMMITTEE = build_user_headers(DUAL_HAT_ID, "DealCommittee")


def make_originator_headers(user_id: str) -> dict:
    """Headers for an `Originator` acting as the given operator identity."""
    return build_user_headers(user_id, "Originator")


def make_credit_officer_headers(user_id: str) -> dict:
    """Headers for a `CreditOfficer` acting as the given operator identity."""
    return build_user_headers(user_id, "CreditOfficer")


def make_deal_committee_headers(user_id: str) -> dict:
    """Headers for a `DealCommittee` operator with the given identity."""
    return build_user_headers(user_id, "DealCommittee")


def make_settlement_analyst_headers(user_id: str) -> dict:
    """Headers for a `SettlementAnalyst` with the given operator identity."""
    return build_user_headers(user_id, "SettlementAnalyst")


def make_registry_agent_headers(user_id: str) -> dict:
    """Headers for a `RegistryAgent` with the given operator identity."""
    return build_user_headers(user_id, "RegistryAgent")


def make_offtaker_rep_headers(offtaker_id: str) -> dict:
    """Headers for the representative of the buyer whose `id` is given.

    `X-User-ID` is the acting `Offtaker.id`, which the server compares against
    a deal's `anchor_offtaker_id` or the `offtaker_id` of one of its
    `CONFIRMED` allocations.
    """
    return build_user_headers(offtaker_id, "OfftakerRep")


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary operator identity and declared role."""
    return build_user_headers(user_id, role)


ALL_ROLE_NAMES = ["Originator", "CreditOfficer", "DealCommittee",
                  "SettlementAnalyst", "RegistryAgent", "OfftakerRep"]

#: The five opaque roles, ready to iterate over.
OPAQUE_ROLE_HEADERS = {
    "Originator": ORIGINATOR,
    "CreditOfficer": CREDIT_OFFICER,
    "DealCommittee": DEAL_COMMITTEE,
    "SettlementAnalyst": SETTLEMENT_ANALYST,
    "RegistryAgent": REGISTRY_AGENT,
}

#: Headers with a role but no identity, and with an identity but no role,
#: for the authentication gate that "happens before anything else".
NO_HEADERS: dict = {}
EMPTY_USER_ID = {"X-User-ID": "", "X-User-Role": "Originator",
                 "Content-Type": "application/json"}
EMPTY_ROLE = {"X-User-ID": ORIGINATOR_ID, "X-User-Role": "",
              "Content-Type": "application/json"}
ROLE_ONLY = {"X-User-Role": "Originator", "Content-Type": "application/json"}
USER_ID_ONLY = {"X-User-ID": ORIGINATOR_ID, "Content-Type": "application/json"}
