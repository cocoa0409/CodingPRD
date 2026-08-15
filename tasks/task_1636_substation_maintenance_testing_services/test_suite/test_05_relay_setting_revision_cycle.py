"""RelaySetting revision cycle (PRD §3.8): SUBMITTED -> REJECTED -> SUBMITTED
is legal, and the resubmitted setting can proceed to VERIFIED and ACTIVE."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_relay_setting_payload,
    get_success_data,
    setup_relay_domain,
    validate_success,
)

OPS = TEST_USERS["ops_manager_headers"]


class TestRelaySettingRevisionCycle:
    def _draft_setting(self) -> dict:
        domain = setup_relay_domain()
        setting = get_success_data(
            api_client.create_relay_setting(
                create_relay_setting_payload(domain["asset"]["id"], pickup_a=80),
                domain["author_headers"],
            )
        )
        return {**domain, "setting": setting}

    def test_rejected_setting_can_be_resubmitted(self):
        """PRD §3.8: "Submission is the author's own action — the caller's
        `X-User-ID` must equal `author_technician_id`, otherwise
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — and is permitted from either
        `DRAFT` or `REJECTED`."
        PRD §3.8: "Rejection requires `rejection_note` (absent is
        `ERR_VALIDATION`, HTTP 400) and transitions `SUBMITTED → REJECTED`."

        Design: Difficulty/non_linear_state_machine/relay_setting_revision_cycle
        """
        ctx = self._draft_setting()
        rs_id = ctx["setting"]["id"]

        submitted = validate_success(
            api_client.submit_relay_setting(rs_id, ctx["author_headers"])
        )
        assert submitted["status"] == "SUBMITTED"

        rejected = validate_success(
            api_client.reject_relay_setting(
                rs_id, {"rejection_note": "Curve mismatch with coordination study"},
                ctx["verifier_headers"],
            )
        )
        assert rejected["status"] == "REJECTED"

        # The cycle closes: REJECTED is not a dead end.
        resubmitted = validate_success(
            api_client.submit_relay_setting(rs_id, ctx["author_headers"])
        )
        assert resubmitted["status"] == "SUBMITTED"

    def test_resubmitted_setting_proceeds_to_active(self):
        """PRD §3.8: "Submission is the author's own action — the caller's
        `X-User-ID` must equal `author_technician_id`, otherwise
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — and is permitted from either
        `DRAFT` or `REJECTED`."
        PRD §3.8: "Verification transitions `SUBMITTED → VERIFIED` and stamps
        `verified_by_technician_id`."
        PRD §3.8: "Success transitions the setting `VERIFIED → ACTIVE`."

        Design: Difficulty/non_linear_state_machine/relay_setting_revision_cycle
        """
        ctx = self._draft_setting()
        rs_id = ctx["setting"]["id"]

        validate_success(api_client.submit_relay_setting(rs_id, ctx["author_headers"]))
        validate_success(
            api_client.reject_relay_setting(
                rs_id, {"rejection_note": "Curve mismatch"}, ctx["verifier_headers"]
            )
        )
        validate_success(api_client.submit_relay_setting(rs_id, ctx["author_headers"]))

        verified = validate_success(
            api_client.verify_relay_setting(rs_id, ctx["verifier_headers"])
        )
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_technician_id"] == ctx["verifier"]["id"]

        asset = validate_success(api_client.get_asset(ctx["asset"]["id"], OPS))
        activated = validate_success(
            api_client.activate_relay_setting(
                rs_id, {"expected_asset_version": asset["version"]},
                ctx["verifier_headers"],
            )
        )
        assert activated["status"] == "ACTIVE"
