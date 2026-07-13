"""List-endpoint pagination envelope.

Queue-B corner instance under the endpoints section.
"""
from test_helpers import (
    TEST_USERS,
    validate_paginated,
    create_home, create_operator,
)

ADMIN = TEST_USERS["admin_headers"]


def test_list_operators_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10 when omitted, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_operators_pagination_envelope
    """
    home = create_home(initial_credits=0)
    create_operator(home["id"], skill="CAMERA", full_name="Op A")
    create_operator(home["id"], skill="AUDIO", full_name="Op B")
    resp = api.list_operators(ADMIN, params={"home_id": home["id"], "limit": 1})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"expected 1 item with limit=1, got {len(data)}"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
