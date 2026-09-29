"""Issuance settles everything inside the one response that performs it."""
from test_helpers import (
    ANALYST,
    ApiClient,
    seed_screened_application,
    validate_success,
)


def test_the_issuance_response_already_carries_every_derived_field(api: ApiClient):
    """PRD §3.3: "The system mints a board-assigned `license_number`, sets
    `license_status` to `ACTIVE` and `encumbrance_status` to `CLEAR`, stamps
    `issued_on` from the logical clock, sets `expires_on` to `issued_on` advanced by
    the board's `renewal_period_months`, initialises `practice_restriction_codes` to
    an empty array and `open_encumbrance_count` to 0, and moves the source
    application from `APPROVED` to the terminal `ISSUED`."

    PRD §3.3: "**Compact privilege** is recomputed, never stored by hand."

    PRD §3.3: "Issuance runs it, a registration change runs it, every encumbrance
    transition runs it, and a `LicensureAnalyst` may run it on demand by supplying a
    `variant`."

    PRD §3.3: "Only when both propagation rules pass is the answer `MULTISTATE`."

    Design: Corner/consistency_model/issuance_side_effects_are_all_visible_in_the_same_response
    """
    ctx = seed_screened_application(api)

    minted = validate_success(
        api.create_license({"source_application_id": ctx["application_id"]}, ANALYST),
        201,
    )

    assert minted["license_status"] == "ACTIVE"
    assert minted["encumbrance_status"] == "CLEAR"
    assert minted["multistate_privilege_status"] == "MULTISTATE", (
        "The cross-entity determination ran inside the create, not afterwards"
    )
    assert minted["privilege_basis_state"] == "OH"
    assert minted["license_number"], "A board-assigned number is already present"
    assert minted["issued_on"] == "2026-08-01T00:00:00.000Z"
    assert minted["expires_on"] == "2028-08-01T00:00:00.000Z", (
        f"Twenty-four renewal months after issuance, got {minted['expires_on']}"
    )
    assert minted["practice_restriction_codes"] == []
    assert minted["open_encumbrance_count"] == 0

    parent = validate_success(
        api.get_license_application(ctx["application_id"], ANALYST)
    )
    assert parent["status"] == "ISSUED", (
        f"The parent transition was not deferred to a later pass, got "
        f"{parent['status']}"
    )
    re_read = validate_success(api.get_license(minted["id"], ANALYST))
    assert re_read["multistate_privilege_status"] == minted["multistate_privilege_status"]
    assert re_read["expires_on"] == minted["expires_on"], (
        "Re-reading changes nothing, so no field settles late"
    )
