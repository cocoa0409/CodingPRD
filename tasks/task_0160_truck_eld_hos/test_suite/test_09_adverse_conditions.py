"""Adverse-conditions exemption lifecycle — PRD §3.6."""
from __future__ import annotations

import pytest

from test_helpers import (
    ADVERSE_EXTRA_MINUTES,
    ApiErrorId,
    TEST_USERS,
    add_seconds,
    advance_clock_to_iso,
    assert_adverse_conditions_exemption,
    create_adverse_conditions_payload,
    declare_adverse_conditions,
    get_server_clock_iso,
    make_driver_headers,
    setup_full_stack,
    validate_error,
    validate_success,
)


# ===========================================================================
# Declare adverse conditions — PRD §3.6
# ===========================================================================
class TestDeclareAdverseConditions:

    def test_declare_sets_extra_minutes_to_120(self, api):
        """PRD §3.6: "The server mints the exemption with a `status`
        of `ACTIVE`, sets `extra_minutes_granted` to a fixed value of
        120".

        Claim: a successful declaration returns an exemption with
        status="ACTIVE" and extra_minutes_granted == 120.
        """
        state = setup_full_stack()
        driver = state["driver"]
        clock0 = get_server_clock_iso()
        payload = create_adverse_conditions_payload(
            declared_at=add_seconds(clock0, 60),
            reason="Severe ice storm restricting forward visibility.",
        )
        resp = api.create_adverse_conditions(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"
        assert data["extra_minutes_granted"] == 120, (
            "PRD §3.6 fixes extra_minutes_granted at 120 on creation."
        )
        assert_adverse_conditions_exemption(data)
