"""The age screen's bounded rejection-and-revision loop."""

from test_helpers import (
    ENGINEER_HEADERS,
    OFFICER_HEADERS,
    api_client,
    create_age_screen,
    create_service,
    read_age_screen,
    set_screen_status,
    validate_error,
    validate_paginated,
)


def _rejected_inherit_screen(service_id: str) -> dict:
    """A neutral account-inherit screen sent back by the officer."""
    screen = create_age_screen(
        service_id,
        mechanism="ACCOUNT_AGE_INHERIT",
        inherited_from_verified_account=True,
    )
    set_screen_status(screen["id"], "IN_REVIEW", ENGINEER_HEADERS)
    return set_screen_status(screen["id"], "REJECTED", OFFICER_HEADERS)


class TestAgeScreenRevisionCycle:
    """Two revisions are allowed, the third is refused, and rejection is not activation."""

    def test_01_a_verified_account_inherit_screen_is_neutral(self):
        """Verified inheritance clears the only code its mechanism could raise.

        The codes include "`UNVERIFIED_INHERIT` when `mechanism` is `ACCOUNT_AGE_INHERIT`
        and `inherited_from_verified_account` is false", so a verified inheritance raises
        none of them and "A fully neutral screen carries an empty list."

        Design: Difficulty/non_linear_state_machine/age_screen_rejection_revision_cycle_exhausts_and_locks
        """
        service = create_service(name="Inherit Screen Service")

        screen = create_age_screen(
            service["id"],
            mechanism="ACCOUNT_AGE_INHERIT",
            inherited_from_verified_account=True,
        )

        assert screen["neutrality_violation_codes"] == [], (
            "a verified account-inherit screen with neutral switches raises no codes, got "
            f"{screen['neutrality_violation_codes']}"
        )
        assert screen["revision_round"] == 0
        assert screen["activated_at"] is None

    def test_02_the_officer_may_not_return_a_rejected_screen_to_draft(self):
        """Only the engineer may take a rejected screen back into draft.

        "The `PrivacyEngineer` fixes the offending switches and moves it `REJECTED →
        DRAFT`". Where the acting role is authorised for the endpoint but not for that
        transition, "the rejection is `ERR_TRANSITION_ROLE_NOT_PERMITTED`".

        Design: Difficulty/non_linear_state_machine/age_screen_rejection_revision_cycle_exhausts_and_locks
        """
        service = create_service(name="Officer Revision Service")
        screen = _rejected_inherit_screen(service["id"])

        validate_error(
            api_client.set_age_screen_status(
                screen["id"], {"to_status": "DRAFT"}, OFFICER_HEADERS
            ),
            "ERR_TRANSITION_ROLE_NOT_PERMITTED",
        )

        unchanged = read_age_screen(service["id"], screen["id"])
        assert unchanged["status"] == "REJECTED", (
            f"the refused transition leaves the screen rejected, got {unchanged['status']}"
        )
        assert unchanged["revision_round"] == 0, (
            f"a refused revision does not advance the round, got {unchanged['revision_round']}"
        )

    def test_03_two_revision_rounds_are_permitted_and_the_third_is_refused(self):
        """The loop advances the round twice and then closes.

        "The `PrivacyEngineer` fixes the offending switches and moves it `REJECTED →
        DRAFT`, which advances `revision_round` by one. That loop is bounded: the
        transition is permitted only while `revision_round` is strictly below 2, so a
        screen may go around twice and no further. A third attempt is refused with
        `ERR_SCREEN_REVISIONS_EXHAUSTED` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/age_screen_rejection_revision_cycle_exhausts_and_locks
        """
        service = create_service(name="Bounded Revision Service")
        screen = _rejected_inherit_screen(service["id"])
        screen_id = screen["id"]

        first = set_screen_status(screen_id, "DRAFT", ENGINEER_HEADERS)
        assert first["revision_round"] == 1, (
            f"the first revision sets revision_round to 1, got {first['revision_round']}"
        )

        set_screen_status(screen_id, "IN_REVIEW", ENGINEER_HEADERS)
        set_screen_status(screen_id, "REJECTED", OFFICER_HEADERS)
        second = set_screen_status(screen_id, "DRAFT", ENGINEER_HEADERS)
        assert second["revision_round"] == 2, (
            f"the second revision sets revision_round to 2, got {second['revision_round']}"
        )

        set_screen_status(screen_id, "IN_REVIEW", ENGINEER_HEADERS)
        set_screen_status(screen_id, "REJECTED", OFFICER_HEADERS)

        validate_error(
            api_client.set_age_screen_status(
                screen_id, {"to_status": "DRAFT"}, ENGINEER_HEADERS
            ),
            "ERR_SCREEN_REVISIONS_EXHAUSTED",
        )

        exhausted = read_age_screen(service["id"], screen_id)
        assert exhausted["revision_round"] == 2, (
            f"the refused third revision leaves the round at 2, got {exhausted['revision_round']}"
        )
        assert exhausted["status"] == "REJECTED"

    def test_04_a_rejected_screen_cannot_be_activated_directly(self):
        """Activation is reachable only from review.

        "A `ComplianceOfficer` moves the screen `IN_REVIEW → ACTIVE`", so activation from
        any other status is a transition-legality failure where "Where no more specific
        code applies the response is `ERR_INVALID_STATE`".

        Design: Difficulty/non_linear_state_machine/age_screen_rejection_revision_cycle_exhausts_and_locks
        """
        service = create_service(name="Rejected To Active Service")
        screen = _rejected_inherit_screen(service["id"])

        validate_error(
            api_client.set_age_screen_status(
                screen["id"], {"to_status": "ACTIVE"}, OFFICER_HEADERS
            ),
            "ERR_INVALID_STATE",
        )

        after = read_age_screen(service["id"], screen["id"])
        assert after["status"] == "REJECTED", (
            f"the refused activation leaves the screen rejected, got {after['status']}"
        )
        assert after["activated_at"] is None, (
            f"a refused activation stamps nothing, got {after['activated_at']}"
        )

    def test_05_an_exhausted_screen_never_appears_among_the_active_screens(self):
        """The service ends the cycle with no live screen at all.

        "A successful activation stamps `activated_at` with the current logical-clock
        instant", and "its age-screen, notice and integration reverse-lookups accept
        `status`", so a service whose only screen never activated lists nothing under
        `ACTIVE`.

        Design: Difficulty/non_linear_state_machine/age_screen_rejection_revision_cycle_exhausts_and_locks
        """
        service = create_service(name="No Live Screen Service")
        screen = _rejected_inherit_screen(service["id"])
        screen_id = screen["id"]
        set_screen_status(screen_id, "DRAFT", ENGINEER_HEADERS)
        set_screen_status(screen_id, "IN_REVIEW", ENGINEER_HEADERS)
        set_screen_status(screen_id, "REJECTED", OFFICER_HEADERS)
        set_screen_status(screen_id, "DRAFT", ENGINEER_HEADERS)
        set_screen_status(screen_id, "IN_REVIEW", ENGINEER_HEADERS)
        set_screen_status(screen_id, "REJECTED", OFFICER_HEADERS)

        _, meta = validate_paginated(
            api_client.list_service_age_screens(
                service["id"], OFFICER_HEADERS, {"status": "ACTIVE"}
            )
        )

        assert meta["total_count"] == 0, (
            f"the service must have no ACTIVE screen, got {meta['total_count']}"
        )
