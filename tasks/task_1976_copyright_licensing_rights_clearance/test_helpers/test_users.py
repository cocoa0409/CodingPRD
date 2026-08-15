"""Pre-built role headers for every role in PRD §2.1."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for non-ownership tests.
TEST_USERS = {
    "requester_headers": build_user_headers("req_shared_1", "Requester"),
    "officer_headers": build_user_headers("off_shared_1", "ClearanceOfficer"),
    "negotiator_headers": build_user_headers("neg_shared_1", "Negotiator"),
    "payer_headers": build_user_headers("fin_shared_1", "FinancePayer"),
    "ingest_headers": build_user_headers("ing_shared_1", "IngestionAgent"),
    "certifier_headers": build_user_headers("leg_shared_1", "LegalCertifier"),
    "curator_headers": build_user_headers("cur_shared_1", "AssetCurator"),
    # entity_backed: RightsHolderRep — shared constant is a fallback for non-ownership
    # paths only; ownership-gated calls MUST use make_rights_holder_rep_headers.
    "rights_holder_rep_headers": build_user_headers("hr_shared_1", "RightsHolderRep"),
}


def make_requester_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Requester")


def make_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClearanceOfficer")


def make_negotiator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Negotiator")


def make_payer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinancePayer")


def make_ingest_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IngestionAgent")


def make_certifier_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LegalCertifier")


def make_curator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AssetCurator")


def make_rights_holder_rep_headers(holder_id: str) -> dict:
    """For RightsHolderRep (entity_backed:RightsHolder). Pass the actual RightsHolder.id
    whenever the call needs the rep to be identified with the persisted holder record
    (e.g. posting a counter-offer round)."""
    return build_user_headers(holder_id, "RightsHolderRep")
