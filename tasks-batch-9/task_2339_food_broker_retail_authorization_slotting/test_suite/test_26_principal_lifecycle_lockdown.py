"""Activating a principal needs a live rate card, and termination is final."""

import pytest

from test_helpers import (
    BROKER_ADMIN_HEADERS,
    AgreementStatus,
    ApiErrorId,
    PrincipalStatus,
    fixtures,
    get_success_data,
    validate_error,
)
from test_helpers.assertions import assert_version_bumped_by, assert_version_unchanged


@pytest.fixture
def prospect_with_two_drafts(api):
    """A prospect and two drafted rate cards covering adjacent years, neither activated."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    principal = fixtures.create_principal(api)
    return {
        "retailer": retailer,
        "principal": principal,
        "current_card": fixtures.create_agreement(
            api, principal["id"], retailer["id"], activate=False
        ),
        "future_card": fixtures.create_agreement(
            api,
            principal["id"],
            retailer["id"],
            activate=False,
            effective_start_date="2027-01-01",
            effective_end_date="2028-01-01",
        ),
    }


def set_status(api, principal_id, status):
    return api.set_principal_status(principal_id, {"status": status}, BROKER_ADMIN_HEADERS)


def read_agreement(api, agreement_id):
    return get_success_data(api.get_agreement(agreement_id, BROKER_ADMIN_HEADERS), 200)


def drive_to_terminated(api, scope):
    get_success_data(api.activate_agreement(scope["current_card"]["id"], BROKER_ADMIN_HEADERS), 200)
    get_success_data(set_status(api, scope["principal"]["id"], PrincipalStatus.ACTIVE), 200)
    get_success_data(set_status(api, scope["principal"]["id"], PrincipalStatus.SUSPENDED), 200)
    return get_success_data(
        set_status(api, scope["principal"]["id"], PrincipalStatus.TERMINATED), 200
    )


class TestPrincipalLifecycleLockdown:
    def test_a_draft_rate_card_does_not_earn_activation(self, api, prospect_with_two_drafts):
        """Two agreements exist, but neither has reached ACTIVE.

        PRD: "Promotion from `PROSPECT` to `ACTIVE` requires that at least one commission
        agreement for this principal has already reached `ACTIVE`; without one the request is
        rejected with `ERR_PRINCIPAL_HAS_NO_AGREEMENT`, and on success `credit_posture` is
        recomputed."

        Design: Corner/state_machines/principal_activation_precondition_and_terminated_lockdown_rejected
        """
        response = set_status(api, prospect_with_two_drafts["principal"]["id"], PrincipalStatus.ACTIVE)

        validate_error(response, ApiErrorId.PRINCIPAL_HAS_NO_AGREEMENT, 409)
        after = fixtures.get_principal(api, prospect_with_two_drafts["principal"]["id"])
        assert after["status"] == PrincipalStatus.PROSPECT
        assert_version_unchanged(prospect_with_two_drafts["principal"], after)

    def test_activating_the_card_unlocks_the_status_move(self, api, prospect_with_two_drafts):
        """The identical request succeeds once one card is live.

        PRD: "On success, `activated_at` is stamped from the logical clock, and presentation
        submission and deal acceptance become possible for every date the window covers."

        Design: Corner/state_machines/principal_activation_precondition_and_terminated_lockdown_rejected
        """
        scope = prospect_with_two_drafts
        validate_error(
            set_status(api, scope["principal"]["id"], PrincipalStatus.ACTIVE),
            ApiErrorId.PRINCIPAL_HAS_NO_AGREEMENT,
            409,
        )

        get_success_data(api.activate_agreement(scope["current_card"]["id"], BROKER_ADMIN_HEADERS), 200)
        activated = get_success_data(
            set_status(api, scope["principal"]["id"], PrincipalStatus.ACTIVE), 200
        )

        assert activated["status"] == PrincipalStatus.ACTIVE
        assert_version_bumped_by(scope["principal"], activated, 1)

    def test_suspension_and_termination_both_proceed_without_live_authorizations(
        self, api, prospect_with_two_drafts
    ):
        """No authorization exists anywhere, so nothing blocks the walk to TERMINATED.

        PRD: "Termination is reachable from either `ACTIVE` or `SUSPENDED` and, in both cases,
        requires that no authorization on any of this principal's items is in `PENDING_SETUP`,
        `AUTHORIZED` or `AT_RISK`; a live authorization blocks the move with
        `ERR_PRINCIPAL_HAS_LIVE_AUTHORIZATIONS`."

        Design: Corner/state_machines/principal_activation_precondition_and_terminated_lockdown_rejected
        """
        terminated = drive_to_terminated(api, prospect_with_two_drafts)

        assert terminated["status"] == PrincipalStatus.TERMINATED

    def test_termination_cascades_only_to_the_active_card(self, api, prospect_with_two_drafts):
        """The live card retires with the principal; the untouched draft stays a draft.

        PRD: "Both termination paths cascade identically: every commission agreement of this
        principal whose `status` is `ACTIVE` is set to `TERMINATED`."

        Design: Corner/state_machines/principal_activation_precondition_and_terminated_lockdown_rejected
        """
        scope = prospect_with_two_drafts
        drive_to_terminated(api, scope)

        assert read_agreement(api, scope["current_card"]["id"])["status"] == (
            AgreementStatus.TERMINATED
        )
        assert read_agreement(api, scope["future_card"]["id"])["status"] == AgreementStatus.DRAFT

    def test_every_later_status_write_including_the_repeat_is_refused(
        self, api, prospect_with_two_drafts
    ):
        """Reinstatement and an idempotent re-termination are both invalid moves.

        PRD: "`TERMINATED` is terminal, and any further status move on the principal — or any
        move the machine does not contain, such as `PROSPECT` straight to `SUSPENDED` — is
        rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/principal_activation_precondition_and_terminated_lockdown_rejected
        """
        scope = prospect_with_two_drafts
        terminated = drive_to_terminated(api, scope)

        validate_error(
            set_status(api, scope["principal"]["id"], PrincipalStatus.ACTIVE),
            ApiErrorId.INVALID_STATE,
            409,
        )
        validate_error(
            set_status(api, scope["principal"]["id"], PrincipalStatus.TERMINATED),
            ApiErrorId.INVALID_STATE,
            409,
        )

        after = fixtures.get_principal(api, scope["principal"]["id"])
        assert after["status"] == PrincipalStatus.TERMINATED
        assert_version_unchanged(terminated, after)

    def test_a_terminated_principal_poisons_agreement_activation_with_its_own_code(
        self, api, prospect_with_two_drafts
    ):
        """The surviving draft can never be activated, and not with ERR_INVALID_STATE either.

        PRD: "Activation also requires that the principal is not `TERMINATED`, otherwise
        `ERR_PRINCIPAL_TERMINATED`."

        Design: Corner/state_machines/principal_activation_precondition_and_terminated_lockdown_rejected
        """
        scope = prospect_with_two_drafts
        drive_to_terminated(api, scope)

        response = api.activate_agreement(scope["future_card"]["id"], BROKER_ADMIN_HEADERS)

        validate_error(response, ApiErrorId.PRINCIPAL_TERMINATED, 409)
        assert read_agreement(api, scope["future_card"]["id"])["status"] == AgreementStatus.DRAFT

    def test_an_unreachable_move_out_of_prospect_is_also_invalid(
        self, api, prospect_with_two_drafts
    ):
        """PROSPECT has no edge to SUSPENDED, so the machine refuses it outright.

        PRD: "`TERMINATED` is terminal, and any further status move on the principal — or any
        move the machine does not contain, such as `PROSPECT` straight to `SUSPENDED` — is
        rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/principal_activation_precondition_and_terminated_lockdown_rejected
        """
        scope = prospect_with_two_drafts

        response = set_status(api, scope["principal"]["id"], PrincipalStatus.SUSPENDED)

        validate_error(response, ApiErrorId.INVALID_STATE, 409)
        assert (
            fixtures.get_principal(api, scope["principal"]["id"])["status"]
            == PrincipalStatus.PROSPECT
        )
