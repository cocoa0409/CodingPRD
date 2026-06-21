"""List-endpoint envelope and pagination bookkeeping.

Covers the corner endpoints instance.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    create_project, create_art_proof_payload,
    TEST_USERS,
)

SM = TEST_USERS["shop_manager_headers"]
DES = TEST_USERS["designer_headers"]


def test_list_art_proofs_paginated_envelope(api):
    """PRD §2.3: "Every list response carries the pagination bookkeeping in the
    meta object: limit, offset, total_count, and has_more." PRD §2.2: "The
    response_type is either 'object' for a single resource or 'array' for a list
    of resources."

    Design: Corner/endpoints/list_art_proofs_paginated_envelope
    """
    project = create_project(customer_name="List Co", site_address="27 Page St")
    get_success_data(api.create_art_proof(
        project["id"], create_art_proof_payload(color_count=2), DES))
    get_success_data(api.create_art_proof(
        project["id"], create_art_proof_payload(color_count=3), DES))

    data, meta = validate_paginated(api.list_art_proofs(project["id"], DES))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2
