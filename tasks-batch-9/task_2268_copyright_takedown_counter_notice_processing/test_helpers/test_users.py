"""Pre-built role headers for every role in PRD §2.1.

RightsHolderRep is entity-backed by RightsHolder and Subscriber is
entity-backed by Account: their X-User-ID must be the acting entity's id
whenever the call is ownership-gated. Use make_rights_holder_rep_headers(
rights_holder["id"]) and make_subscriber_headers(account["id"]) for those
calls; the shared constants below are only safe for negative RBAC probes.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "compliance_officer_headers": build_user_headers("officer-01", "ComplianceOfficer"),
    "second_compliance_officer_headers": build_user_headers(
        "officer-02", "ComplianceOfficer"
    ),
    "takedown_agent_headers": build_user_headers("agent-01", "TakedownAgent"),
    "abuse_investigator_headers": build_user_headers("investigator-01", "AbuseInvestigator"),
    "second_abuse_investigator_headers": build_user_headers(
        "investigator-02", "AbuseInvestigator"
    ),
    # entity_backed:RightsHolder — fallback for non-ownership probes only.
    "rights_holder_rep_headers": build_user_headers("rep-orphan-01", "RightsHolderRep"),
    # entity_backed:Account — fallback for non-ownership probes only.
    "subscriber_headers": build_user_headers("subscriber-orphan-01", "Subscriber"),
}

# Headers carrying a well-formed id but a role value outside the declared set.
ANONYMOUS_HEADERS = {"X-User-ID": "anon-01", "Content-Type": "application/json"}
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer identity is opaque but recorded on termination cases,
    so separation-of-duties probes need distinct officer identities."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_takedown_agent_headers(user_id: str) -> dict:
    """TakedownAgent identity is opaque."""
    return build_user_headers(user_id, "TakedownAgent")


def make_abuse_investigator_headers(user_id: str) -> dict:
    """AbuseInvestigator identity is recorded as opened_by_user_id /
    substantiated_by_user_id on misrepresentation cases."""
    return build_user_headers(user_id, "AbuseInvestigator")


def make_rights_holder_rep_headers(rights_holder_id: str) -> dict:
    """RightsHolderRep is entity-backed by RightsHolder: pass the acting rights
    holder's id whenever the call is ownership-gated."""
    return build_user_headers(rights_holder_id, "RightsHolderRep")


def make_subscriber_headers(account_id: str) -> dict:
    """Subscriber is entity-backed by Account: pass the acting account's id
    whenever the call is ownership-gated."""
    return build_user_headers(account_id, "Subscriber")
