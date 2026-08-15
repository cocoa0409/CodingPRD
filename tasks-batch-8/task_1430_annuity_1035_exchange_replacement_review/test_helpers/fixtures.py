"""
Composite setup helpers for multi-step test prerequisites.

Every helper builds preconditions from scratch through the public API (each
test runs against a freshly restarted server with an empty database and the
logical clock at its 2026-08-01T00:00:00Z startup default). Setup calls use
get_success_data() so a setup failure surfaces as a clear "Setup failed"
error rather than a confusing assertion failure.

Identity threading: Producer is entity-backed — every ownership-gated call
uses make_producer_headers(producer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT_ISO, TEST_DEFAULTS
from .factories import (
    create_analysis_payload,
    create_case_payload,
    create_client_payload,
    create_contract_payload,
    create_document_payload,
    create_producer_payload,
    rationale_payload,
)
from .test_users import TEST_USERS, make_producer_headers
from .types import REQUIRED_DOC_TYPES

REVIEWER_ID = TEST_DEFAULTS["REVIEWER_ID"]
PRINCIPAL_ID = TEST_DEFAULTS["PRINCIPAL_ID"]
SENIOR_DOB = TEST_DEFAULTS["SENIOR_DOB"]
JUNIOR_DOB = TEST_DEFAULTS["JUNIOR_DOB"]

_ADMIN = TEST_USERS["carrier_admin_headers"]
_REVIEWER = TEST_USERS["reviewer_headers"]
_PRINCIPAL = TEST_USERS["principal_headers"]
_COMPLIANCE = TEST_USERS["compliance_headers"]
_OPS = TEST_USERS["ops_headers"]


# ─── Tier 1: single-resource registration ────────────────────────────────


def register_producer(**overrides) -> dict:
    """CarrierAdmin registers a producer (starts ACTIVE, counters zero)."""
    res = api_client.create_producer(create_producer_payload(**overrides), _ADMIN)
    return get_success_data(res)


def register_client(producer_id: str, **overrides) -> dict:
    """Register an annuitant client as the given producer."""
    res = api_client.create_client(
        create_client_payload(**overrides), make_producer_headers(producer_id)
    )
    return get_success_data(res)


def register_contract(producer_id: str, client_id: str, **overrides) -> dict:
    """Register the canonical in-force contract (K_STD) as the producer."""
    res = api_client.create_contract(
        create_contract_payload(client_id, **overrides),
        make_producer_headers(producer_id),
    )
    return get_success_data(res)


def open_case(producer_id: str, client_id: str, contract_id: str, **overrides) -> dict:
    """Create a DRAFT exchange case owned by the producer."""
    res = api_client.create_case(
        create_case_payload(producer_id, client_id, contract_id, **overrides),
        make_producer_headers(producer_id),
    )
    return get_success_data(res)


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, _ADMIN)
    )


# ─── Tier 2: case state progression ──────────────────────────────────────


def submit_case(case_id: str, producer_id: str) -> dict:
    return get_success_data(
        api_client.submit_case(case_id, make_producer_headers(producer_id))
    )


def start_review(case_id: str, reviewer_id: str = REVIEWER_ID) -> dict:
    from .test_users import make_reviewer_headers

    return get_success_data(
        api_client.start_review(case_id, make_reviewer_headers(reviewer_id))
    )


def setup_case_in_review(
    dob: str = SENIOR_DOB, contract_overrides=None, case_overrides=None
) -> dict:
    """Producer + client + K_STD contract + case submitted and taken into
    SUITABILITY_REVIEW. Returns a bundle with ids and the live case version
    (the value an OCC-guarded analysis creation must name)."""
    producer = register_producer()
    client = register_client(producer["id"], date_of_birth=dob)
    contract = register_contract(
        producer["id"], client["id"], **(contract_overrides or {})
    )
    case = open_case(
        producer["id"], client["id"], contract["id"], **(case_overrides or {})
    )
    submit_case(case["id"], producer["id"])
    reviewed = start_review(case["id"])
    return {
        "producer": producer,
        "client": client,
        "contract": contract,
        "case_id": case["id"],
        "case_version": reviewed["version"],
    }


def submit_document(case_id: str, producer_id: str, doc_type: str) -> dict:
    return get_success_data(
        api_client.create_document(
            case_id,
            create_document_payload(doc_type),
            make_producer_headers(producer_id),
        )
    )


def verify_document(document_id: str, reviewer_id: str = REVIEWER_ID) -> dict:
    from .test_users import make_reviewer_headers

    return get_success_data(
        api_client.verify_document(document_id, make_reviewer_headers(reviewer_id))
    )


def reject_document(document_id: str, rationale: str, reviewer_id: str = REVIEWER_ID) -> dict:
    from .test_users import make_reviewer_headers

    return get_success_data(
        api_client.reject_document(
            document_id, rationale_payload(rationale), make_reviewer_headers(reviewer_id)
        )
    )


def add_verified_documents(
    case_id: str, producer_id: str, reviewer_id: str = REVIEWER_ID
) -> list:
    """Submit and verify all three required document types."""
    docs = [
        submit_document(case_id, producer_id, doc_type)
        for doc_type in REQUIRED_DOC_TYPES
    ]
    for doc in docs:
        verify_document(doc["id"], reviewer_id)
    return docs


def create_analysis(
    case_id: str,
    case_version: int,
    reviewer_id: str = REVIEWER_ID,
    **overrides,
) -> dict:
    from .test_users import make_reviewer_headers

    return get_success_data(
        api_client.create_comparison_analysis(
            case_id,
            create_analysis_payload(case_version, **overrides),
            make_reviewer_headers(reviewer_id),
        )
    )


def recommend_case(case_id: str, reviewer_id: str = REVIEWER_ID, rationale: str = "suitable") -> dict:
    from .test_users import make_reviewer_headers

    return get_success_data(
        api_client.recommend_case(
            case_id, rationale_payload(rationale), make_reviewer_headers(reviewer_id)
        )
    )


def approve_case(case_id: str, principal_id: str = PRINCIPAL_ID, rationale: str = "approved") -> dict:
    from .test_users import make_principal_headers

    return get_success_data(
        api_client.approve_case(
            case_id, rationale_payload(rationale), make_principal_headers(principal_id)
        )
    )


# ─── Tier 3: full lifecycle shortcuts ────────────────────────────────────


def setup_case_pending_principal(
    dob: str = SENIOR_DOB, contract_overrides=None, case_overrides=None
) -> dict:
    """Case with all three documents VERIFIED, a FINAL analysis, and a
    reviewer recommendation (status PENDING_PRINCIPAL)."""
    bundle = setup_case_in_review(dob, contract_overrides, case_overrides)
    bundle["documents"] = add_verified_documents(
        bundle["case_id"], bundle["producer"]["id"]
    )
    bundle["analysis"] = create_analysis(bundle["case_id"], bundle["case_version"])
    recommend_case(bundle["case_id"])
    return bundle


def setup_case_approved(
    dob: str = SENIOR_DOB, contract_overrides=None, case_overrides=None
) -> dict:
    """Case recommended and approved by a distinct principal (APPROVED)."""
    bundle = setup_case_pending_principal(dob, contract_overrides, case_overrides)
    approve_case(bundle["case_id"])
    return bundle


def request_and_receive_funds(case_id: str) -> dict:
    """APPROVED -> FUNDS_REQUESTED -> FUNDS_RECEIVED. Returns the transfer."""
    transfer = get_success_data(api_client.request_funds(case_id, _OPS))
    get_success_data(api_client.mark_transfer_received(transfer["id"], _OPS))
    return transfer


def setup_case_in_free_look(
    dob: str = JUNIOR_DOB,
    contract_overrides=None,
    case_overrides=None,
    delivery_clock: str = None,
) -> dict:
    """Case driven all the way to IN_FREE_LOOK. When delivery_clock is set,
    the logical clock is moved there before delivery is confirmed (the
    delivery date becomes that clock's date)."""
    bundle = setup_case_approved(dob, contract_overrides, case_overrides)
    bundle["transfer"] = request_and_receive_funds(bundle["case_id"])
    if delivery_clock is not None:
        set_clock(delivery_clock)
    delivered = get_success_data(api_client.confirm_delivery(bundle["case_id"], _OPS))
    bundle["case"] = delivered
    return bundle


def setup_case_completed(
    dob: str = JUNIOR_DOB, completion_clock: str = "2026-08-22T00:00:00Z"
) -> dict:
    """Full lifecycle through COMPLETED: delivered at the startup default
    clock, then completed after the free-look deadline passes."""
    bundle = setup_case_in_free_look(dob=dob)
    set_clock(completion_clock)
    bundle["case"] = get_success_data(api_client.complete_case(bundle["case_id"], _OPS))
    return bundle


def setup_case_rescinded(dob: str = JUNIOR_DOB) -> dict:
    """Full lifecycle through RESCINDED at the startup default clock
    (delivered and rescinded on 2026-08-01, inside a junior 20-day window)."""
    bundle = setup_case_in_free_look(dob=dob)
    bundle["case"] = get_success_data(
        api_client.rescind_case(
            bundle["case_id"], make_producer_headers(bundle["producer"]["id"])
        )
    )
    return bundle


# ─── Tier 4: read-side helpers ────────────────────────────────────────────


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_case(case_id, _OPS))


def get_producer(producer_id: str) -> dict:
    return get_success_data(api_client.get_producer(producer_id, _COMPLIANCE))


def get_client(client_id: str) -> dict:
    return get_success_data(api_client.get_client(client_id, _OPS))


def get_single_contract(client_id: str) -> dict:
    """Fetch the client's sole contract via the list endpoint."""
    from prd_bench_local_runner.testing import validate_paginated

    res = api_client.list_client_contracts(client_id, _OPS)
    # get_success_data returns the data array for list endpoints; use the
    # paginated validator for structure.
    items, meta = validate_paginated(res)
    assert len(items) == 1, f"Setup failed: expected 1 contract, got {len(items)}"
    return items[0]


def list_transfers(case_id: str) -> list:
    from prd_bench_local_runner.testing import validate_paginated

    items, _ = validate_paginated(api_client.list_funds_transfers(case_id, _OPS))
    return items


def list_case_documents(case_id: str, params=None) -> list:
    from prd_bench_local_runner.testing import validate_paginated

    items, _ = validate_paginated(
        api_client.list_case_documents(case_id, _OPS, params=params)
    )
    return items


def list_producer_events(producer_id: str, params=None) -> list:
    from prd_bench_local_runner.testing import validate_paginated

    items, _ = validate_paginated(
        api_client.list_producer_activity_events(producer_id, _COMPLIANCE, params=params)
    )
    return items


def list_review_decisions(case_id: str, params=None) -> list:
    from prd_bench_local_runner.testing import validate_paginated

    items, _ = validate_paginated(
        api_client.list_review_decisions(case_id, _OPS, params=params)
    )
    return items


__all__ = [name for name in dir() if not name.startswith("_")]
