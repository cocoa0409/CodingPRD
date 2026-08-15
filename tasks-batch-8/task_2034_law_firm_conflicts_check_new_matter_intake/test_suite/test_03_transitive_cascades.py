"""Multi-hop cascades: waiver-revoke chain and lateral-review activation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_roster_party,
    api_client,
    approve_waiver,
    consent_waiver,
    create_attorney,
    create_conflicts_partner,
    create_letter,
    create_matter,
    create_party,
    get_deposit,
    get_success_data,
    issue_letter,
    list_hits_for_check,
    make_client_headers,
    make_conflicts_partner_headers,
    make_responsible_attorney_headers,
    run_conflict_check,
    send_waiver,
    setup_matter_with_approved_waiver,
    setup_matter_with_waiver,
    transition_waiver_payload,
    validate_error,
    validate_success,
)

INTAKE = TEST_USERS["intake_specialist_headers"]
FIRM_ADMIN = TEST_USERS["firm_admin_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


class TestWaiverRevokeThreeHopCascade:
    def test_revoke_unwaives_hit_blocks_matter_and_voids_issued_letter(self):
        """PRD §3.6: "Revoking an `APPROVED` waiver unwinds the whole chain: the
        referenced hit returns from `WAIVED` to `CONFIRMED`, the matter's
        clearance recomputes to `BLOCKED`, and every engagement letter of the
        matter still `ISSUED` is voided to `VOID`, while letters in `DRAFT` or
        already `COUNTERSIGNED` are untouched."

        Design: Difficulty/transitive_cascade/waiver_revoke_three_hop_cascade
        """
        p_x, p_y, atty, partner, m1, hit, waiver = (
            setup_matter_with_approved_waiver("Kilo Victor Inc", "Lima Zulu Corp")
        )
        m1_after_approve = get_success_data(
            api_client.get_matter(m1["id"], INTAKE), 200
        )
        assert m1_after_approve["clearance_status"] == "WAIVED"

        # Issue a letter while clearance is WAIVED.
        letter = create_letter(m1_after_approve, atty)
        issued = issue_letter(letter["id"], atty)
        assert issued["status"] == "ISSUED"

        revoked = validate_success(
            api_client.transition_waiver_request(
                waiver["id"],
                transition_waiver_payload("REVOKE"),
                make_client_headers(p_y["id"]),
            ),
            200,
        )
        assert revoked["status"] == "REVOKED"

        hit_after = get_success_data(
            api_client.get_conflict_hit(hit["id"], INTAKE), 200
        )
        assert hit_after["review_status"] == "CONFIRMED", (
            "hop 1: waiver revoke un-waives the hit"
        )
        m1_after = get_success_data(api_client.get_matter(m1["id"], INTAKE), 200)
        assert m1_after["clearance_status"] == "BLOCKED", (
            "hop 2: clearance recompute on the hit flip"
        )
        assert m1_after["lifecycle_status"] == "INTAKE"
        letters = get_success_data(
            api_client.list_matter_engagement_letters(m1["id"], INTAKE), 200
        )
        assert letters[0]["status"] == "VOID", (
            "hop 3: conditional cascade voids only the ISSUED letter"
        )

    def test_approve_waives_hit_and_flips_clearance_to_waived(self):
        """PRD §3.6: "Approving from `CONSENTED` stamps
        `approved_by_attorney_id` with the caller, cascades the referenced hit
        from `CONFIRMED` to `WAIVED`, and recomputes the matter's clearance —
        which becomes `WAIVED` when no `CONFIRMED` hits remain."

        Design: Difficulty/transitive_cascade/waiver_revoke_three_hop_cascade
        """
        p_x, p_y, atty, m1, hit, waiver = setup_matter_with_waiver(
            "Pre Revoke X Inc", "Pre Revoke Y Corp"
        )
        partner = create_conflicts_partner()
        send_waiver(waiver["id"], atty)
        consent_waiver(waiver["id"], p_y, "doc-001")
        approved = approve_waiver(waiver["id"], partner)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_attorney_id"] == partner["id"]

        hit_after = get_success_data(
            api_client.get_conflict_hit(hit["id"], INTAKE), 200
        )
        assert hit_after["review_status"] == "WAIVED"
        m1_after = get_success_data(api_client.get_matter(m1["id"], INTAKE), 200)
        assert m1_after["clearance_status"] == "WAIVED"


class TestLateralReviewActivationWallCascade:
    def test_review_confirm_activates_lateral_and_creates_wall(self):
        """PRD §3.2: "Activation is automatic. After every lateral-sweep hit
        review, the system counts that attorney's sweep hits still `PENDING`;
        when the count reaches zero, the attorney flips from `LATERAL_PENDING`
        to `ACTIVE` with its `version` incremented, and the imputation cascade
        runs immediately: for each `CONFIRMED` sweep hit's matter, if an
        `ACTIVE` ethical wall already exists on that matter, the attorney is
        appended to its `excluded_attorney_ids` unless already present;
        otherwise a new wall is created on that matter with reason
        `LATERAL_IMPUTATION` and an `excluded_attorney_ids` list containing
        exactly that attorney."

        Design: Difficulty/transitive_cascade/lateral_review_activation_wall_cascade
        """
        p_g = create_party("Acme Global Ltd")
        atty_r = create_attorney()
        m0 = create_matter(p_g["id"], atty_r["id"], matter_title="M0")

        lateral = create_attorney(
            full_name="Larry Lateral",
            bar_number="BAR009",
            hire_type="LATERAL",
            lateral_employed_from="2024-01-01",
            lateral_employed_to="2026-08-15",
            prior_client_names=["Acme Global"],
        )
        assert lateral["status"] == "LATERAL_PENDING", (
            "sweep produced a hit, so no immediate activation"
        )

        resp = api_client.list_conflict_hits(
            make_conflicts_partner_headers(atty_r["id"]),
            params={"matched_matter_id": m0["id"]},
        )
        hits = get_success_data(resp, 200)
        assert hits[0]["matched_via"] == "LATERAL"
        assert hits[0]["lateral_attorney_id"] == lateral["id"]
        m0_mid = get_success_data(api_client.get_matter(m0["id"], INTAKE), 200)
        assert m0_mid["clearance_status"] == "HITS_PENDING", (
            "retroactive imputation on an existing matter"
        )

        reviewed = validate_success(
            api_client.review_conflict_hit(
                hits[0]["id"],
                {"decision": "CONFIRMED", "note": "lateral represented adverse party"},
                make_responsible_attorney_headers(atty_r["id"]),
            ),
            200,
        )
        assert reviewed["review_status"] == "CONFIRMED"

        lateral_after = get_success_data(
            api_client.get_attorney(lateral["id"], FIRM_ADMIN), 200
        )
        assert lateral_after["status"] == "ACTIVE", (
            "hop 2: last PENDING resolved auto-activates the lateral"
        )

        walls = get_success_data(
            api_client.list_matter_ethical_walls(
                m0["id"], make_conflicts_partner_headers(atty_r["id"])
            ),
            200,
        )
        assert walls[0]["reason"] == "LATERAL_IMPUTATION"
        assert lateral["id"] in walls[0]["excluded_attorney_ids"], (
            "hop 3: wall auto-created with the lateral excluded"
        )

        denied = api_client.get_matter(
            m0["id"], make_responsible_attorney_headers(lateral["id"])
        )
        validate_error(denied, ApiErrorId.ERR_WALL_EXCLUDED)

    def test_lateral_sweep_hit_is_attributed_and_carries_pending_status(self):
        """PRD §3.2: "For every surviving (name, matter) pair, the system
        creates a conflict check of `check_kind` `LATERAL_SWEEP` on that
        existing matter — never on any new matter — with its `search_variant`
        fixed to `PHONETIC`, its `match_threshold` at 60, its
        `lateral_attorney_id` attributing the onboarding attorney, and its
        `query_label` recording the prior-client string that produced it; the
        sweep's hits carry the same `lateral_attorney_id` attribution, which
        the activation gate below reads."
        PRD §3.2: "The new attorney starts `LATERAL_PENDING` if the sweep
        created at least one hit, and `ACTIVE` otherwise; `INTERNAL` hires
        always start `ACTIVE`."

        Design: Difficulty/transitive_cascade/lateral_review_activation_wall_cascade
        """
        p_g = create_party("Acme Global Ltd")
        atty_r = create_attorney()
        m0 = create_matter(p_g["id"], atty_r["id"], matter_title="M0")

        lateral = create_attorney(
            full_name="Larry Lateral",
            bar_number="BAR009",
            hire_type="LATERAL",
            lateral_employed_from="2024-01-01",
            lateral_employed_to="2026-08-15",
            prior_client_names=["Acme Global"],
        )
        assert lateral["status"] == "LATERAL_PENDING"

        resp = api_client.list_conflict_hits(
            make_conflicts_partner_headers(atty_r["id"]),
            params={"matched_matter_id": m0["id"]},
        )
        hits = get_success_data(resp, 200)
        assert len(hits) == 1
        assert hits[0]["review_status"] == "PENDING"
        assert hits[0]["matched_via"] == "LATERAL"
        assert hits[0]["lateral_attorney_id"] == lateral["id"]
        assert hits[0]["matched_party_id"] == p_g["id"]
