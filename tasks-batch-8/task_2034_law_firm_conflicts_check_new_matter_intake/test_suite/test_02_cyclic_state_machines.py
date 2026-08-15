"""Cyclic state machines: the waiver REDRAFT loop and the matter's parallel
clearance dimension (PRD sections 2.8 and 3.6)."""
from test_helpers import (
    TEST_USERS,
    add_roster_party,
    api_client,
    create_attorney,
    create_matter,
    create_party,
    get_success_data,
    list_hits_for_check,
    make_client_headers,
    make_responsible_attorney_headers,
    run_conflict_check,
    setup_matter_with_waiver,
    transition_waiver_payload,
    validate_success,
)

INTAKE = TEST_USERS["intake_specialist_headers"]


class TestWaiverRedraftCycle:
    def test_waiver_full_loop_declined_back_to_draft_then_sent(self):
        """PRD §3.6: "Redrafting closes the cycle. From `DECLINED`, `REVOKED`,
        or `EXPIRED`, the original requester — and only the requester, on pain
        of `ERR_NOT_RESPONSIBLE_ATTORNEY` — may issue a `REDRAFT` action
        returning the waiver to `DRAFT`. Redrafting resets `sent_at`,
        `expires_at`, `consent_document_ref`, `decline_reason`, and
        `approved_by_attorney_id` to null or empty, and the same payload may
        supply replacement `proposed_terms`."

        Design: Difficulty/non_linear_state_machine/waiver_redraft_cycle
        """
        p_x, p_y, atty, m1, hit, waiver = setup_matter_with_waiver(
            "Delta Panda Inc", "Echo Bravo Corp", proposed_terms="v1 terms"
        )
        assert waiver["status"] == "DRAFT"
        ra = make_responsible_attorney_headers(atty["id"])
        client = make_client_headers(p_y["id"])

        sent = validate_success(
            api_client.transition_waiver_request(
                waiver["id"], transition_waiver_payload("SEND"), ra
            ),
            200,
        )
        assert sent["status"] == "SENT"
        assert sent["expires_at"] is not None
        # Default clock 2026-08-01 + 30 days (PRD §3.6: "A successful send
        # stamps `sent_at` from the logical clock and sets `expires_at`
        # exactly thirty days later.")
        assert sent["expires_at"] == "2026-08-31T00:00:00.000Z"

        declined = validate_success(
            api_client.transition_waiver_request(
                waiver["id"],
                transition_waiver_payload("DECLINE", decline_reason="client unhappy"),
                client,
            ),
            200,
        )
        assert declined["status"] == "DECLINED"

        redrafted = validate_success(
            api_client.transition_waiver_request(
                waiver["id"],
                transition_waiver_payload("REDRAFT", proposed_terms="v2 terms"),
                ra,
            ),
            200,
        )
        assert redrafted["status"] == "DRAFT"
        assert redrafted["expires_at"] is None, "REDRAFT resets expires_at"
        assert redrafted["consent_document_ref"] is None, (
            "REDRAFT resets consent_document_ref"
        )

        resent = validate_success(
            api_client.transition_waiver_request(
                waiver["id"], transition_waiver_payload("SEND"), ra
            ),
            200,
        )
        assert resent["status"] == "SENT"
        assert resent["expires_at"] == "2026-08-31T00:00:00.000Z", (
            "second SEND recomputes expires_at fresh from the logical clock"
        )

    def test_waiver_initial_state_and_send_fields(self):
        """PRD §3.6: "The new waiver records the caller as
        `requested_by_attorney_id`, starts in `DRAFT`, and leaves `sent_at`,
        `expires_at`, `consent_document_ref`, and `approved_by_attorney_id`
        null and `decline_reason` empty."
        PRD §3.6: "A successful send stamps `sent_at` from the logical clock
        and sets `expires_at` exactly thirty days later."

        Design: Difficulty/non_linear_state_machine/waiver_redraft_cycle
        """
        p_x, p_y, atty, m1, hit, waiver = setup_matter_with_waiver(
            "Waiver Init X Inc", "Waiver Init Y Corp"
        )
        assert waiver["status"] == "DRAFT"
        assert waiver["requested_by_attorney_id"] == atty["id"]
        assert waiver["sent_at"] is None
        assert waiver["expires_at"] is None
        assert waiver["consent_document_ref"] is None
        assert waiver["approved_by_attorney_id"] is None
        assert waiver["decline_reason"] == ""

        sent = validate_success(
            api_client.transition_waiver_request(
                waiver["id"],
                transition_waiver_payload("SEND"),
                make_responsible_attorney_headers(atty["id"]),
            ),
            200,
        )
        assert sent["status"] == "SENT"
        assert sent["sent_at"] == "2026-08-01T00:00:00.000Z"
        assert sent["expires_at"] == "2026-08-31T00:00:00.000Z"


class TestMatterClearanceCycleParallelDimensions:
    def test_clearance_cycle_uncheck_cleared_uncheck_hits_pending_cleared(self):
        """PRD §2.8: "Observable clearance flips therefore include: `UNCHECKED` →
        `HITS_PENDING` when a check or lateral sweep produces a pending hit;
        `UNCHECKED` → `CLEARED` when a check completes with zero hits;
        `HITS_PENDING` → `CLEARED` when the last pending hit is dismissed;
        `HITS_PENDING` → `BLOCKED` when a hit is confirmed; `BLOCKED` → `WAIVED`
        when a waiver approval waives the last confirmed hit; `WAIVED` →
        `BLOCKED` when a revocation un-waives a hit; `CLEARED` → `UNCHECKED`
        when a roster change supersedes all of the matter's intake checks so
        that no non-superseded checks remain; and `CLEARED` → `HITS_PENDING` or
        `WAIVED` → `HITS_PENDING` when a lateral sweep lands a new pending hit
        on a previously cleared or waived matter."

        Design: Difficulty/non_linear_state_machine/matter_clearance_cycle_parallel_dimensions
        """
        p_x = create_party("Foxtrot Lima LLC")
        p_y = create_party("Golf Hotel Inc")
        atty = create_attorney()
        create_matter(p_x["id"], atty["id"], matter_title="M0")
        m1 = create_matter(p_y["id"], atty["id"], matter_title="M1")
        assert m1["clearance_status"] == "UNCHECKED"
        assert m1["lifecycle_status"] == "INTAKE"

        chk1 = run_conflict_check(m1["id"], "STRICT")
        assert chk1["hit_count"] == 0
        m1_after_chk1 = get_success_data(api_client.get_matter(m1["id"], INTAKE), 200)
        assert m1_after_chk1["clearance_status"] == "CLEARED"

        # Roster add supersedes the INTAKE check -> back to UNCHECKED.
        add_roster_party(m1["id"], p_x["id"], "ADVERSE")
        m1_after_add = get_success_data(api_client.get_matter(m1["id"], INTAKE), 200)
        assert m1_after_add["clearance_status"] == "UNCHECKED"
        assert m1_after_add["lifecycle_status"] == "INTAKE", (
            "clearance movement must not drag the lifecycle dimension"
        )

        # New check now matches X (client of M0, ADVERSE on M1) -> HITS_PENDING.
        chk2 = run_conflict_check(m1["id"], "STRICT")
        assert chk2["hit_count"] == 1
        m1_after_chk2 = get_success_data(api_client.get_matter(m1["id"], INTAKE), 200)
        assert m1_after_chk2["clearance_status"] == "HITS_PENDING"

        hits = list_hits_for_check(chk2["id"])
        resp = api_client.review_conflict_hit(
            hits[0]["id"],
            {"decision": "DISMISSED"},
            make_responsible_attorney_headers(atty["id"]),
        )
        get_success_data(resp, 200)
        m1_final = get_success_data(api_client.get_matter(m1["id"], INTAKE), 200)
        assert m1_final["clearance_status"] == "CLEARED"
        assert m1_final["lifecycle_status"] == "INTAKE"

    def test_lifecycle_stays_intake_throughout_clearance_cycle(self):
        """PRD §2.8: "A matter carries two independent status dimensions on one
        row. The `lifecycle_status` dimension walks `INTAKE` → `OPEN` →
        `CLOSED`, with `INTAKE` → `DECLINED` as the early-exit branch;
        `CLOSED` and `DECLINED` are terminal. The `clearance_status` dimension
        — `UNCHECKED`, `HITS_PENDING`, `CLEARED`, `BLOCKED`, `WAIVED` — is not
        set by any caller; it is derived, and it has no terminal state because
        it remains recomputable even on `OPEN` matters."

        Design: Difficulty/non_linear_state_machine/matter_clearance_cycle_parallel_dimensions
        """
        p_x = create_party("Parallel X LLC")
        p_y = create_party("Parallel Y Inc")
        atty = create_attorney()
        create_matter(p_x["id"], atty["id"], matter_title="M0")
        m1 = create_matter(p_y["id"], atty["id"], matter_title="M1")

        observed_lifecycles = [m1["lifecycle_status"]]
        run_conflict_check(m1["id"], "STRICT")
        observed_lifecycles.append(
            get_success_data(api_client.get_matter(m1["id"], INTAKE), 200)[
                "lifecycle_status"
            ]
        )
        add_roster_party(m1["id"], p_x["id"], "ADVERSE")
        observed_lifecycles.append(
            get_success_data(api_client.get_matter(m1["id"], INTAKE), 200)[
                "lifecycle_status"
            ]
        )
        chk = run_conflict_check(m1["id"], "STRICT")
        observed_lifecycles.append(
            get_success_data(api_client.get_matter(m1["id"], INTAKE), 200)[
                "lifecycle_status"
            ]
        )
        hits = list_hits_for_check(chk["id"])
        api_client.review_conflict_hit(
            hits[0]["id"],
            {"decision": "DISMISSED"},
            make_responsible_attorney_headers(atty["id"]),
        )
        observed_lifecycles.append(
            get_success_data(api_client.get_matter(m1["id"], INTAKE), 200)[
                "lifecycle_status"
            ]
        )
        assert observed_lifecycles == ["INTAKE"] * 5, (
            f"lifecycle must stay pinned at INTAKE while clearance cycles; "
            f"observed {observed_lifecycles}"
        )
