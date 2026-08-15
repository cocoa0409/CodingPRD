"""Amendment lifecycle: routing, signatures, decline/revise cycles, window overlap,
OCC on file version, and the apply cascade."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId, TEST_USERS,
    make_active_listing_file, make_active_purchase_file,
    get_file_version, make_draft_amendment, make_routed_amendment,
    make_fully_signed_amendment, get_signature_request_for_agent,
    get_deadline_by_kind, get_milestone_by_name, list_reminders_for_deadline,
    list_all_amendments,
)


class TestSignatureBubbleUp:
    def test_signature_bubble_up_partial_then_full(self):
        """PRD §3.6: "A signature stamps `signed_at` and auto-advances the amendment:
        the first signature of the round moves `ROUTED → PARTIALLY_SIGNED`, and when
        every request of the current round is `SIGNED` the amendment becomes
        `FULLY_SIGNED` (directly from `ROUTED` in the single-signer case, or from
        `PARTIALLY_SIGNED`)."

        Design: Corner/state_machines/signature_bubble_up_partial_then_full
        """
        scen = make_active_purchase_file(required_doc_types=["EXECUTED_CONTRACT"])
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        am = make_routed_amendment(coord_h, file_id, "2026-08-10", "2026-08-15",
                                   new_list_price_cents=44500000)
        sig_buyer = get_signature_request_for_agent(coord_h, am["id"], scen["buyer"]["id"])
        sig_seller = get_signature_request_for_agent(coord_h, am["id"], scen["seller"]["id"])
        assert sig_buyer["status"] == "PENDING" and sig_seller["status"] == "PENDING"

        validate_success(api_client.sign_signature_request(sig_buyer["id"], scen["buyer_h"]))
        mid = validate_success(api_client.get_amendment(am["id"], coord_h))
        assert mid["status"] == "PARTIALLY_SIGNED", \
            "the first signature of the round moves ROUTED -> PARTIALLY_SIGNED"

        validate_success(api_client.sign_signature_request(sig_seller["id"], scen["seller_h"]))
        end = validate_success(api_client.get_amendment(am["id"], coord_h))
        assert end["status"] == "FULLY_SIGNED", \
            "when every request of the round is SIGNED the amendment becomes FULLY_SIGNED"
        for sig_id in (sig_buyer["id"], sig_seller["id"]):
            sig = validate_success(api_client.get_signature_request(sig_id, coord_h))
            assert sig["status"] == "SIGNED"
            assert sig["signed_at"] is not None


class TestRejectReviseRerouteCycle:
    def test_amendment_reject_revise_reroute_cycle(self):
        """PRD §3.6: "Declining requires the request `PENDING` and the same actor
        match; a decline — optionally carrying a `reason` — moves the request to
        `DECLINED`, the owning amendment to `REJECTED`, and every remaining `PENDING`
        request of the round to `VOIDED`."
        PRD §3.6: "A rejected amendment can be revised: revising moves `REJECTED →
        DRAFT` and increments `round_number` by 1, ready for a fresh routing round."
        PRD §3.6: "Routing creates the round's `SignatureRequest` rows: for a
        `PURCHASE_SALE` file, one request for `buyer_agent_id` with `signer_party`
        `BUYER_AGENT` and one for `seller_agent_id` with `signer_party`
        `SELLER_AGENT`; for a `LISTING_ONLY` file, only the seller-agent request."

        Design: Difficulty/non_linear_state_machine/amendment_reject_revise_reroute_cycle
        """
        scen = make_active_purchase_file(required_doc_types=["EXECUTED_CONTRACT"])
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        am = make_routed_amendment(coord_h, file_id, "2026-08-10", "2026-08-15",
                                   new_closing_date="2026-09-04")
        sig_buyer = get_signature_request_for_agent(coord_h, am["id"], scen["buyer"]["id"])
        sig_seller = get_signature_request_for_agent(coord_h, am["id"], scen["seller"]["id"])

        declined = validate_success(api_client.decline_signature_request(
            sig_buyer["id"], scen["buyer_h"], payload={"reason": "buyer rejects new closing date"}
        ))
        assert declined["status"] == "DECLINED"
        am_mid = validate_success(api_client.get_amendment(am["id"], coord_h))
        assert am_mid["status"] == "REJECTED"
        seller_sig = validate_success(api_client.get_signature_request(sig_seller["id"], coord_h))
        assert seller_sig["status"] == "VOIDED", \
            "a decline voids every remaining PENDING request of the round"

        revised = validate_success(api_client.revise_amendment(am["id"], coord_h))
        assert revised["status"] == "DRAFT"
        assert revised["round_number"] == 2, "revise increments round_number by 1"

        rerouted = validate_success(api_client.route_amendment(am["id"], coord_h))
        assert rerouted["status"] == "ROUTED"
        round2 = get_success_data(api_client.list_signature_requests(
            coord_h, params={"amendment_id": am["id"], "round_number": 2, "limit": 100}
        ))
        assert len(round2) == 2, "re-routing mints a fresh pair of round-2 requests"
        assert all(s["status"] == "PENDING" for s in round2)
        assert {s["agent_id"] for s in round2} == {scen["buyer"]["id"], scen["seller"]["id"]}


class TestApplyCascade:
    def test_amendment_apply_recomputes_file_deadline_reminder_chain(self):
        """PRD §3.6: "Three cascades fire in order. First, the payload lands on the
        file: `effective_date`, `closing_date`, and `list_price_cents` are replaced
        wherever the corresponding `new_effective_date`, `new_closing_date`, and
        `new_list_price_cents` are non-null, and the file's `version` is incremented.
        Second, the file's `effective_date` change recomputes every non-terminal
        milestone's `due_date` as the new effective date plus that milestone's
        `offset_days`, and every `PENDING` deadline's `due_date` via the deadline
        due-date rule under the file's pinned day convention. Third, each recomputed
        `PENDING` deadline regenerates its reminders: existing `QUEUED` reminders are
        cancelled, new future reminders are created per the schedule rule, and `SENT`
        reminders are preserved untouched and not counted toward the new sequence."

        Design: Difficulty/transitive_cascade/amendment_apply_recomputes_file_deadline_reminder_chain
        """
        scen = make_active_purchase_file(
            milestone_defs=[
                {"name": "Earnest Money", "offset_days": 3, "mandatory": True},
                {"name": "Inspection Period", "offset_days": 7, "mandatory": True},
            ],
            required_doc_types=["EXECUTED_CONTRACT"],
        )
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        insp = get_deadline_by_kind(coord_h, file_id, "INSPECTION")
        assert insp["due_date"] == "2026-08-10"
        assert len(list_reminders_for_deadline(coord_h, insp["id"], status="QUEUED")) == 3

        am = make_fully_signed_amendment(
            coord_h, file_id,
            buyer_h=scen["buyer_h"], seller_h=scen["seller_h"],
            buyer_id=scen["buyer"]["id"], seller_id=scen["seller"]["id"],
            effective_from="2026-08-05", effective_to="2026-08-31",
            new_effective_date="2026-08-05",
        )
        applied = validate_success(api_client.apply_amendment(am["id"], coord_h))
        assert applied["status"] == "EFFECTIVE"

        # Link 1: the payload lands on the file.
        f_after = validate_success(api_client.get_file(file_id, coord_h))
        assert f_after["effective_date"] == "2026-08-05"

        # Link 2: milestone and deadline due dates recompute from the new date.
        dl_after = validate_success(api_client.get_deadline(insp["id"], coord_h))
        assert dl_after["due_date"] == "2026-08-12", \
            "2026-08-05 + 7 calendar days under the TX calendar convention"
        ms_earnest = get_milestone_by_name(coord_h, file_id, "Earnest Money")
        ms_insp = get_milestone_by_name(coord_h, file_id, "Inspection Period")
        assert ms_earnest["due_date"] == "2026-08-08"
        assert ms_insp["due_date"] == "2026-08-12"

        # Link 3: the deadline's reminders regenerate.
        queued = list_reminders_for_deadline(coord_h, insp["id"], status="QUEUED")
        cancelled = list_reminders_for_deadline(coord_h, insp["id"], status="CANCELLED")
        assert len(queued) == 3, f"3 new future reminders; got {len(queued)}"
        assert sorted(r["scheduled_at"][:10] for r in queued) == [
            "2026-08-07", "2026-08-10", "2026-08-12",
        ]
        assert all(r["scheduled_at"][11:19] == "09:00:00" for r in queued)
        assert len(cancelled) == 3, \
            "the 3 pre-amendment QUEUED reminders are cancelled by regeneration"
        assert sorted(r["scheduled_at"][:10] for r in cancelled) == [
            "2026-08-05", "2026-08-08", "2026-08-10",
        ]


class TestAmendmentConstraints:
    def test_amendment_effective_window_half_open_overlap(self):
        """PRD §3.6: "The window is half-open: `effective_from` is inclusive,
        `effective_to` is exclusive, and `effective_to` must be strictly after
        `effective_from` (`ERR_INVALID_AMENDMENT_WINDOW`, HTTP 400)."
        PRD §3.6: "The new window must not overlap the window of any other amendment
        of the same file in `ROUTED`, `PARTIALLY_SIGNED`, `FULLY_SIGNED`, or
        `EFFECTIVE`; half-open semantics mean sharing exactly one boundary date is
        allowed, and a genuine overlap is `ERR_AMENDMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/amendment_effective_window_half_open_overlap
        """
        scen = make_active_listing_file()
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        am_a = make_routed_amendment(coord_h, file_id, "2026-08-10", "2026-08-20")
        # Adjacent at the exclusive end: [2026-08-20, 2026-08-25) shares exactly one
        # boundary date and must be accepted.
        am_b = make_draft_amendment(coord_h, file_id, "2026-08-20", "2026-08-25")
        assert am_b["status"] == "DRAFT"
        # Interior intersection on 2026-08-19 must conflict.
        resp = api_client.create_amendment(
            {
                "file_id": file_id,
                "expected_file_version": get_file_version(coord_h, file_id),
                "effective_from": "2026-08-19",
                "effective_to": "2026-08-25",
            },
            coord_h,
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_WINDOW_OVERLAP)
        amendments = list_all_amendments(coord_h)
        assert len(amendments) == 2, "the rejected amendment must not be persisted"
        by_id = {a["id"]: a for a in amendments}
        assert by_id[am_a["id"]]["status"] == "ROUTED"
        assert by_id[am_b["id"]]["status"] == "DRAFT"

    def test_amendment_window_inverted_rejected(self):
        """PRD §3.6: "The window is half-open: `effective_from` is inclusive,
        `effective_to` is exclusive, and `effective_to` must be strictly after
        `effective_from` (`ERR_INVALID_AMENDMENT_WINDOW`, HTTP 400)."

        Design: Corner/validations/amendment_window_inverted_rejected
        """
        scen = make_active_listing_file()
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        resp = api_client.create_amendment(
            {
                "file_id": file_id,
                "expected_file_version": get_file_version(coord_h, file_id),
                "effective_from": "2026-08-15",
                "effective_to": "2026-08-15",
            },
            coord_h,
        )
        # effective_to == effective_from is not strictly after.
        validate_error(resp, ApiErrorId.ERR_INVALID_AMENDMENT_WINDOW)

    def test_route_second_amendment_in_flight_rejected(self):
        """PRD §3.6: "Routing moves `DRAFT → ROUTED`. The amendment must be `DRAFT`
        (`ERR_AMENDMENT_INVALID_STATE`), the owning file must be `ACTIVE`
        (`ERR_FILE_NOT_ACTIVE`), and no other amendment of the same file may currently
        be in `ROUTED`, `PARTIALLY_SIGNED`, or `FULLY_SIGNED`
        (`ERR_AMENDMENT_IN_FLIGHT`)."

        Design: Corner/validations/route_second_amendment_in_flight_rejected
        """
        scen = make_active_listing_file()
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        am_a = make_routed_amendment(coord_h, file_id, "2026-08-10", "2026-08-15")
        am_b = make_draft_amendment(coord_h, file_id, "2026-08-16", "2026-08-20")
        resp = api_client.route_amendment(am_b["id"], coord_h)
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_IN_FLIGHT)
        b_after = validate_success(api_client.get_amendment(am_b["id"], coord_h))
        a_after = validate_success(api_client.get_amendment(am_a["id"], coord_h))
        assert b_after["status"] == "DRAFT"
        assert a_after["status"] == "ROUTED"

    def test_apply_draft_amendment_rejected(self):
        """PRD §3.6: "Applying a fully signed amendment is the payoff. The amendment
        must be `FULLY_SIGNED` (`ERR_AMENDMENT_INVALID_STATE`)."

        Design: Corner/validations/apply_draft_amendment_rejected
        """
        scen = make_active_listing_file()
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        am = make_draft_amendment(coord_h, file_id, "2026-08-10", "2026-08-15")
        resp = api_client.apply_amendment(am["id"], coord_h)
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_INVALID_STATE)
        am_after = validate_success(api_client.get_amendment(am["id"], coord_h))
        assert am_after["status"] == "DRAFT", "a failed apply must leave the amendment DRAFT"
        f_after = validate_success(api_client.get_file(file_id, coord_h))
        assert f_after["effective_date"] == "2026-08-03", "file fields must be unchanged"

    def test_sign_after_decline_rejected(self):
        """PRD §3.6: "Signing requires the request `PENDING`
        (`ERR_SIGNATURE_INVALID_STATE`), the acting agent's `X-User-ID` to equal the
        request's `agent_id` (`ERR_SIGNATURE_NOT_AUTHORIZED`), and the owning
        amendment to be in `ROUTED` or `PARTIALLY_SIGNED`
        (`ERR_AMENDMENT_INVALID_STATE`)."
        PRD §3.6: "Declining requires the request `PENDING` and the same actor match;
        a decline — optionally carrying a `reason` — moves the request to `DECLINED`,
        the owning amendment to `REJECTED`, and every remaining `PENDING` request of
        the round to `VOIDED`."

        Design: Corner/validations/sign_after_decline_rejected
        """
        scen = make_active_purchase_file(required_doc_types=["EXECUTED_CONTRACT"])
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        am = make_routed_amendment(coord_h, file_id, "2026-08-10", "2026-08-15")
        sig_buyer = get_signature_request_for_agent(coord_h, am["id"], scen["buyer"]["id"])
        sig_seller = get_signature_request_for_agent(coord_h, am["id"], scen["seller"]["id"])
        validate_success(api_client.decline_signature_request(
            sig_buyer["id"], scen["buyer_h"], payload={"reason": "terms unacceptable"}
        ))
        # The seller's request was VOIDED by the decline cascade; signing it now fails
        # on the request's own state.
        resp = api_client.sign_signature_request(sig_seller["id"], scen["seller_h"])
        validate_error(resp, ApiErrorId.ERR_SIGNATURE_INVALID_STATE)
        am_after = validate_success(api_client.get_amendment(am["id"], coord_h))
        assert am_after["status"] == "REJECTED"


class TestAmendmentOcc:
    def test_occ_stale_file_version_rejected(self):
        """PRD §2.6: "A request that creates an amendment against a transaction file
        must carry `expected_file_version`, a non-optional field holding the client's
        last observed `version` of the target `TransactionFile`. If the file's current
        `version` has advanced since the client last read it — amendment creation
        itself supersedes any existing draft amendment and increments `file.version`,
        so a second create carrying the previously observed version is stale — the
        create is rejected with `ERR_STALE_FILE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_file_version_rejected
        """
        scen = make_active_listing_file()
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        file_v = get_file_version(coord_h, file_id)
        am_a = make_draft_amendment(coord_h, file_id, "2026-08-10", "2026-08-15")
        assert am_a["status"] == "DRAFT"
        # The first create bumped file.version, so the previously observed version is
        # now stale even though this create's content is valid.
        resp = api_client.create_amendment(
            {
                "file_id": file_id,
                "expected_file_version": file_v,
                "effective_from": "2026-08-16",
                "effective_to": "2026-08-20",
            },
            coord_h,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_FILE_VERSION)
        amendments = list_all_amendments(coord_h)
        assert len(amendments) == 1, "the stale create must not persist an amendment"
        assert amendments[0]["id"] == am_a["id"]
        assert amendments[0]["status"] == "DRAFT"


class TestCycleAndApplySecondForms:
    def test_amendment_two_reject_revise_cycles_reach_round_three(self):
        """PRD §3.6: "Declining requires the request `PENDING` and the same actor
        match; a decline — optionally carrying a `reason` — moves the request to
        `DECLINED`, the owning amendment to `REJECTED`, and every remaining `PENDING`
        request of the round to `VOIDED`."
        PRD §3.6: "A rejected amendment can be revised: revising moves `REJECTED →
        DRAFT` and increments `round_number` by 1, ready for a fresh routing round."

        Design: Difficulty/non_linear_state_machine/amendment_reject_revise_reroute_cycle
        """
        scen = make_active_purchase_file(required_doc_types=["EXECUTED_CONTRACT"])
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        am = make_routed_amendment(coord_h, file_id, "2026-08-10", "2026-08-15",
                                   new_closing_date="2026-09-04")
        for expected_round in (1, 2):
            sig_buyer = get_signature_request_for_agent(
                coord_h, am["id"], scen["buyer"]["id"], round_number=expected_round
            )
            declined = validate_success(api_client.decline_signature_request(
                sig_buyer["id"], scen["buyer_h"], payload={"reason": "not acceptable"}
            ))
            assert declined["status"] == "DECLINED"
            am_mid = validate_success(api_client.get_amendment(am["id"], coord_h))
            assert am_mid["status"] == "REJECTED"
            revised = validate_success(api_client.revise_amendment(am["id"], coord_h))
            assert revised["status"] == "DRAFT"
            assert revised["round_number"] == expected_round + 1
            rerouted = validate_success(api_client.route_amendment(am["id"], coord_h))
            assert rerouted["status"] == "ROUTED"
        round3 = get_success_data(api_client.list_signature_requests(
            coord_h, params={"amendment_id": am["id"], "round_number": 3, "limit": 100}
        ))
        assert len(round3) == 2
        assert all(s["status"] == "PENDING" for s in round3)
        am_end = validate_success(api_client.get_amendment(am["id"], coord_h))
        assert am_end["round_number"] == 3

    def test_amendment_apply_closing_date_only_change(self):
        """PRD §3.6: "Three cascades fire in order. First, the payload lands on the
        file: `effective_date`, `closing_date`, and `list_price_cents` are replaced
        wherever the corresponding `new_effective_date`, `new_closing_date`, and
        `new_list_price_cents` are non-null, and the file's `version` is incremented."

        Design: Difficulty/transitive_cascade/amendment_apply_recomputes_file_deadline_reminder_chain
        """
        scen = make_active_purchase_file(required_doc_types=["EXECUTED_CONTRACT"])
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        insp_before = get_deadline_by_kind(coord_h, file_id, "INSPECTION")
        am = make_fully_signed_amendment(
            coord_h, file_id,
            buyer_h=scen["buyer_h"], seller_h=scen["seller_h"],
            buyer_id=scen["buyer"]["id"], seller_id=scen["seller"]["id"],
            effective_from="2026-08-10", effective_to="2026-08-15",
            new_closing_date="2026-09-04",
        )
        applied = validate_success(api_client.apply_amendment(am["id"], coord_h))
        assert applied["status"] == "EFFECTIVE"
        f_after = validate_success(api_client.get_file(file_id, coord_h))
        assert f_after["closing_date"] == "2026-09-04", \
            "the non-null new_closing_date replaces the file's closing_date"
        assert f_after["effective_date"] == "2026-08-03", \
            "a null new_effective_date leaves the effective_date untouched"
        # With no effective_date change, due dates are unchanged.
        insp_after = validate_success(api_client.get_deadline(insp_before["id"], coord_h))
        assert insp_after["due_date"] == "2026-08-10"

    def test_amendment_window_overlap_against_effective_amendment(self):
        """PRD §3.6: "The new window must not overlap the window of any other
        amendment of the same file in `ROUTED`, `PARTIALLY_SIGNED`, `FULLY_SIGNED`, or
        `EFFECTIVE`; half-open semantics mean sharing exactly one boundary date is
        allowed, and a genuine overlap is `ERR_AMENDMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/amendment_effective_window_half_open_overlap
        """
        scen = make_active_purchase_file(required_doc_types=["EXECUTED_CONTRACT"])
        coord_h, file_id = scen["coord_h"], scen["file"]["id"]
        am_a = make_fully_signed_amendment(
            coord_h, file_id,
            buyer_h=scen["buyer_h"], seller_h=scen["seller_h"],
            buyer_id=scen["buyer"]["id"], seller_id=scen["seller"]["id"],
            effective_from="2026-08-10", effective_to="2026-08-15",
            new_list_price_cents=44500000,
        )
        applied = validate_success(api_client.apply_amendment(am_a["id"], coord_h))
        assert applied["status"] == "EFFECTIVE"
        # Interior overlap with the EFFECTIVE window: rejected.
        resp = api_client.create_amendment(
            {
                "file_id": file_id,
                "expected_file_version": get_file_version(coord_h, file_id),
                "effective_from": "2026-08-14",
                "effective_to": "2026-08-20",
            },
            coord_h,
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_WINDOW_OVERLAP)
        # Adjacent to the EFFECTIVE window's exclusive end: allowed.
        am_b = make_draft_amendment(coord_h, file_id, "2026-08-15", "2026-08-20")
        assert am_b["status"] == "DRAFT"
        amendments = list_all_amendments(coord_h)
        assert len(amendments) == 2
