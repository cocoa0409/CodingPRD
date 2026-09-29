"""Domain assertions for the Single-Family Rental Portfolio Operations API.

These helpers wrap the shared envelope validators with the vocabulary of this PRD so
that a test reads as the rule it is checking.  Nothing here relaxes an expectation: each
helper asserts strict equality on the fields the PRD names.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


def created(response):
    """A creation endpoint returned HTTP 201 with the created resource in ``data``.

    PRD SS4: "Endpoints that create a new resource return HTTP 201 with the created
    resource in the ``data`` field."
    """
    return validate_success(response, expected_status=201)


def ok(response):
    """A read/list/mutate endpoint returned HTTP 200 with its payload in ``data``.

    PRD SS4: "Endpoints that read, list or modify an existing resource return HTTP 200
    with the resource, the array of resources, or the computed object in the ``data``
    field."
    """
    return validate_success(response, expected_status=200)


def failed(response, expected_error_id):
    """The request was refused with exactly ``expected_error_id``.

    The HTTP status is cross-checked against the PRD SS5 error table through the status
    map registered by :mod:`test_helpers.api_errors`.
    """
    return validate_error(response, expected_error_id)


def page(response):
    """Unpack a list endpoint into ``(rows, meta)`` with the PRD SS2.3 pagination fields."""
    return validate_paginated(response)


def assert_fields(resource, **expected):
    """Assert every named field of ``resource`` equals the supplied value exactly."""
    for field, want in expected.items():
        assert field in resource, "expected field {!r} to be present, got keys {}".format(
            field, sorted(resource)
        )
        assert resource[field] == want, "field {!r}: expected {!r}, got {!r}".format(
            field, want, resource[field]
        )
    return resource


def assert_absent_or_empty(resource, field):
    """A cleared reference field reads back as an empty string (PRD SS2.2 nullability)."""
    assert field in resource, "expected field {!r} to be present".format(field)
    assert resource[field] == "", "field {!r}: expected cleared (\"\"), got {!r}".format(
        field, resource[field]
    )


def assert_home_dimensions(home, asset_status, occupancy_status, leasing_posture=None):
    """Assert the two independent Home dimensions and, optionally, the derived posture.

    PRD SS2.8: the Home carries "two independent status dimensions" -- ``asset_status``
    and ``occupancy_status`` -- and ``leasing_posture`` is derived from them.
    """
    assert_fields(home, asset_status=asset_status, occupancy_status=occupancy_status)
    if leasing_posture is not None:
        assert_fields(home, leasing_posture=leasing_posture)
    return home


def assert_money_group(resource, **expected):
    """Assert a group of integer-cent fields together, so one wrong term is obvious.

    PRD SS2.5: "All money is stored and exchanged as a whole number of cents."
    """
    for field, want in expected.items():
        assert isinstance(
            resource.get(field), int
        ), "money field {!r} must be an integer number of cents, got {!r}".format(
            field, resource.get(field)
        )
    return assert_fields(resource, **expected)


def assert_version(resource, expected_version):
    """Assert the optimistic-concurrency ``version`` counter (PRD SS2.2)."""
    return assert_fields(resource, version=expected_version)


def assert_ids(rows, expected_ids):
    """Assert a listing returned exactly ``expected_ids``, order-insensitively."""
    got = sorted(row["id"] for row in rows)
    want = sorted(expected_ids)
    assert got == want, "expected rows {}, got {}".format(want, got)
    return rows


def assert_page_meta(meta, total_count=None, has_more=None, limit=None, offset=None):
    """Assert the PRD SS2.3 pagination envelope fields that the test cares about."""
    for field, want in (
        ("total_count", total_count),
        ("has_more", has_more),
        ("limit", limit),
        ("offset", offset),
    ):
        if want is not None:
            assert field in meta, "expected pagination field {!r}".format(field)
            assert meta[field] == want, "pagination {!r}: expected {!r}, got {!r}".format(
                field, want, meta[field]
            )
    return meta
