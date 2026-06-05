"""Response envelope assertions.

The API uses a fixed envelope (PRD 2.2):
  success: { "meta": {...}, "response_type": "object"|"array", "data": {...} }
  error:   { "meta": {...}, "response_type": "error",
             "data": { "error_id": "ERR_XXX", "message": "..." } }
"""


def data_of(resp):
    """Return resp.json()["data"] (works for both success and error bodies)."""
    body = resp.json()
    assert "data" in body, f"missing data envelope: {body}"
    return body["data"]


def assert_ok(resp, status=200):
    assert resp.status_code == status, (
        f"expected {status}, got {resp.status_code}: {resp.text}"
    )
    return data_of(resp)


def assert_created(resp):
    return assert_ok(resp, 201)


def assert_error(resp, status, error_id):
    assert resp.status_code == status, (
        f"expected {status}, got {resp.status_code}: {resp.text}"
    )
    data = data_of(resp)
    assert data.get("error_id") == error_id, (
        f"expected error_id {error_id}, got {data.get('error_id')}: {data}"
    )
    return data
