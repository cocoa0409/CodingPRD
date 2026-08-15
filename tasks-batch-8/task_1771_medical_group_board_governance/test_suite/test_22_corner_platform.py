"""Corner queue: pagination, response envelope, FK reachability, OCC, reconciliation."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adopt_buyout_approval,
    appraise_payload,
    appraise_valuation,
    api_client,
    bill_call,
    capital_call_for_motion,
    capital_call_payload,
    cast_vote,
    close_motion,
    create_and_open_motion,
    create_physician,
    create_policy,
    create_shareholder,
    finalize_exit,
    get_physician,
    get_policy,
    initiate_exit,
    list_call_assessments,
    list_motion_votes,
    list_motions,
    list_physician_assessments,
    list_physician_votes,
    list_physicians,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPhysicianListPaginationAndStatusFilter:
    def test_limit_offset_and_status_filter(self, api):
        """PRD §2.3: "All list endpoints accept two query parameters: `limit` and
        `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` defaults to 0. List results are always ordered by `created_at`
        ascending. The `meta` object of a list response carries `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD §4: "List physicians (filters: `partnership_status`, `standing`)"

        Design: Corner/endpoints/physician_list_pagination_and_status_filter
        """
        create_policy(total_shares_authorized=1000000)
        a = create_shareholder("Dr A", 100, "2015-01-01T00:00:00Z")
        b = create_shareholder("Dr B", 100, "2016-01-01T00:00:00Z")
        c = create_physician(full_name="Dr C", hire_date="2024-01-01T00:00:00Z")

        page1, meta1 = validate_paginated(
            api_client.list_physicians(TEST_USERS["board_admin_headers"],
                                       params={"limit": 2})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api_client.list_physicians(TEST_USERS["board_admin_headers"],
                                       params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False
        paged_ids = {p["id"] for p in page1} | {p["id"] for p in page2}
        assert paged_ids == {a["id"], b["id"], c["id"]}

        filtered, meta3 = validate_paginated(
            api_client.list_physicians(
                TEST_USERS["compliance_officer_headers"],
                params={"partnership_status": "SHAREHOLDER"},
            )
        )
        assert {p["id"] for p in filtered} == {a["id"], b["id"]}
        assert meta3["total_count"] == 2


class TestResponseEnvelopeContract:
    def test_success_and_error_envelopes(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/endpoints/response_envelope_contract_success_and_error
        """
        create_policy(total_shares_authorized=1000000)
        resp = api_client.create_physician(
            {"full_name": "Dr E", "hire_date": "2024-01-01T00:00:00Z"},
            TEST_USERS["board_admin_headers"],
        )
        body = resp.json()
        assert resp.status_code == 201
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        created = validate_success(resp, 201)
        physician_id = created["id"]
        assert body["data"]["id"] == physician_id

        err_resp = api_client.create_physician(
            {"full_name": "Dr Broken"}, TEST_USERS["board_admin_headers"]
        )
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_INVALID_REQUEST"
        assert isinstance(err_body["data"]["message"], str)
        assert len(err_body["data"]["message"]) > 0


class TestFkReverseReachabilitySubresources:
    def test_votes_and_assessments_reachable_both_directions(self, api):
        """PRD §4 endpoint table: "List votes on a motion", "List votes cast by a
        physician", "List assessments of a call", "List assessments of a physician",
        and motions filter `sponsor_physician_id`.

        Design: Corner/endpoints/fk_reverse_reachability_subresources
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        motion = create_and_open_motion(
            "CAPITAL_CALL", a, capital_call_payload(50000, purpose="FK")
        )
        vote = cast_vote(motion["id"], a, "FOR")
        close_motion(motion["id"])
        call = capital_call_for_motion(motion["id"])
        bill_call(call["id"])

        motion_votes, _ = list_motion_votes(motion["id"])
        assert [v["id"] for v in motion_votes] == [vote["id"]]
        physician_votes, _ = list_physician_votes(a["id"])
        assert [v["id"] for v in physician_votes] == [vote["id"]]

        call_assessments, _ = list_call_assessments(call["id"])
        physician_assessments, _ = list_physician_assessments(a["id"])
        assert len(call_assessments) == 1
        assert call_assessments[0]["assessed_cents"] == 50000
        assert [x["id"] for x in physician_assessments] == [call_assessments[0]["id"]]

        sponsored, _ = list_motions(params={"sponsor_physician_id": a["id"]})
        assert [m["id"] for m in sponsored] == [motion["id"]]


class TestOccPolicyUpdateStaleVersion:
    def test_stale_policy_update_rejected(self, api):
        """PRD §2.6: "Updating the governance policy requires the request to carry
        `expected_policy_version`, holding the `version` of the `GovernancePolicy` the
        client last observed; if the policy's current `version` no longer matches —
        because another writer has modified it since the client's last read — the
        update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client
        from silently discarding an update it never saw."

        Design: Corner/cross_cutting_layers/occ_policy_update_stale_version_rejected
        """
        policy = create_policy(total_shares_authorized=1000000)
        assert policy["version"] == 1

        resp = api_client.update_policy(
            {"expected_policy_version": policy["version"], "board_quorum_count": 7},
            TEST_USERS["board_admin_headers"],
        )
        updated = validate_success(resp)
        assert updated["version"] == 2
        assert updated["board_quorum_count"] == 7

        resp = api_client.update_policy(
            {"expected_policy_version": policy["version"], "board_quorum_count": 9},
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_policy()["board_quorum_count"] == 7, "the failed write applies nothing"


class TestOccValuationAppraiseStaleVersion:
    def test_stale_appraise_rejected_fresh_correction_succeeds(self, api):
        """PRD §2.6: "Recording an appraisal against an exit valuation likewise
        requires `expected_valuation_version` matching the `ExitValuation`'s current
        `version`; a mismatch — for instance because another writer has already
        recorded a corrected appraisal that legitimately supersedes the prior value —
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.6: "A corrected appraisal may be recorded while `APPRAISED` — it
        supersedes the prior value and recomputes `final_value_cents`"
        Sole shareholder (ownership 1.0): 90000000 * 0.85 = 76500000;
        95000000 * 0.85 = 80750000.

        Design: Corner/cross_cutting_layers/occ_valuation_appraise_stale_version_rejected
        """
        create_policy(total_shares_authorized=1000000)
        x = create_shareholder("Dr X", 1000, "2010-01-01T00:00:00Z")
        valuation = initiate_exit(x["id"], "VOLUNTARY")

        first = appraise_valuation(valuation, 90000000)
        assert first["status"] == "APPRAISED"
        assert first["final_value_cents"] == 76500000

        resp = api_client.appraise_exit_valuation(
            valuation["id"],
            appraise_payload(80000000, valuation["version"]),
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        corrected = appraise_valuation(first, 95000000)
        assert corrected["final_value_cents"] == 80750000
        assert corrected["version"] == first["version"] + 1


class TestOwnershipAndTreasuryReconcileAfterExit:
    def test_remaining_shareholder_reconciles_immediately(self, api):
        """PRD §3.1: "This recalculation runs whenever any physician's `shares_held`
        mutates: founding creation, buy-in completion, or exit finalization."
        PRD §3.1: "Treasury shares follow the companion rule:
        `total_shares_authorized` minus the sum of `shares_held` over all physicians
        (an `EXITED` physician holds zero, so the two sums coincide in practice)."
        X 1000 exits, Y 1000 remains: Y ownership 1.0; treasury 999000.

        Design: Corner/cross_cutting_layers/ownership_and_treasury_reconcile_after_exit
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        x = create_shareholder("Dr X", 1000, "2010-01-01T00:00:00Z")
        y = create_shareholder("Dr Y", 1000, "2011-01-01T00:00:00Z")
        valuation = initiate_exit(x["id"], "RETIREMENT")
        appraised = appraise_valuation(valuation, 90000000)
        motion = adopt_buyout_approval(y, appraised["id"])
        finalize_exit(appraised["id"], motion["id"])

        y_after = get_physician(y["id"])
        assert y_after["ownership_pct"] == pytest.approx(1.0), (
            "sole remaining holder must reconcile to 1.0"
        )
        assert get_policy()["treasury_shares"] == 999000
        shareholders, _ = list_physicians(params={"partnership_status": "SHAREHOLDER"})
        assert [p["id"] for p in shareholders] == [y["id"]]


class TestImmediateReadAfterWriteVisibility:
    def test_cast_ballot_visible_on_next_read(self, api):
        """PRD §3.4: "Each cast vote recomputes the motion's tallies and bumps the
        motion's `version`."

        Design: Corner/consistency_model/immediate_read_after_write_visibility
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        motion = create_and_open_motion(
            "CAPITAL_CALL", a, capital_call_payload(50000, purpose="Consistency")
        )
        vote = cast_vote(motion["id"], a, "AGAINST")

        resp = api_client.get_motion(
            motion["id"], TEST_USERS["compliance_officer_headers"]
        )
        fetched = validate_success(resp)
        assert fetched["votes_against"] == 1, "no lag between cast and tally"
        assert fetched["eligible_voter_count"] == 1
        votes, _ = list_motion_votes(motion["id"])
        assert [v["id"] for v in votes] == [vote["id"]]
