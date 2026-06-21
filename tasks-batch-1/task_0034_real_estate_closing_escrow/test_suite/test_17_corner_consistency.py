"""Corner section: consistency_model — immediate read-after-write
visibility of the confirm mutation in the same response envelope.
"""
from test_helpers import (
    validate_success,
    setup_actors,
    setup_active_agreement,
    create_deposit,
    confirm_deposit_payload,
    api_client,
)


class TestImmediateConsistencyOnEmdConfirm:
    def test_emd_confirm_response_includes_status_confirmed_inline(self, api):
        """PRD §3.1: "When the funds clear at the originating bank, the officer confirms the deposit, supplying a ``confirmation_reference`` in the request body; the deposit advances from ``PENDING`` to ``CONFIRMED``."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_consistency_emd_confirm_visible_in_response
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(actors=actors)
        deposit = create_deposit(actors, base["escrow"]["id"], amount_cents=1_000_000)
        res = api.confirm_earnest_money_deposit(
            deposit["id"], confirm_deposit_payload("IC-1"), actors["eo"]
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "CONFIRMED", \
            f"confirm response must carry post-mutation status=CONFIRMED inline, got {data['status']}"
