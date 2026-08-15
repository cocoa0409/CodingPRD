"""Installation photo signoffs: evidence rules, the reject/resubmit loop,
segregation of duties, and the four-hop fulfillment cascade."""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_signoff,
    assert_install_signoff,
    create_claim,
    create_signoff,
    get_kit_ledger,
    make_install_crew_lead_headers,
    make_program_manager_headers,
    make_store_manager_headers,
    reject_signoff,
    setup_delivered_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = make_program_manager_headers("pm-suite-6")

ENDCAP_BOM = [{"part_number": "PN-600", "quantity": 1,
               "list_unit_cost_cents": 3000}]
TEN_AT_1000 = [{"part_number": "PN-600", "quantity": 10,
                "unit_cost_cents": 1000}]
GONDOLA_BOM = [{"part_number": "PN-300", "quantity": 5,
                "list_unit_cost_cents": 9000}]
HUNDRED_AT_3000 = [{"part_number": "PN-300", "quantity": 100,
                    "unit_cost_cents": 3000}]


def _delivered_ctx(name, store_code="STORE-S1"):
    return setup_delivered_scenario(
        program_name=name,
        budget_total_cents=1_000_000,
        fixture_code="ENDCAP",
        bom_lines=ENDCAP_BOM,
        store_code=store_code,
        config_lines=TEN_AT_1000,
        wave_capacity=100,
        crew_code="CREW-S",
        estimated_install_hours=4,
    )


class TestSignoffSubmission:

    def test_signoff_without_photos_rejected(self):
        """PRD §3.7: "The evidence list must contain at least one entry; an
        empty or absent list is rejected with `ERR_PHOTO_EVIDENCE_REQUIRED`
        (HTTP 422)."

        Design: Corner/validations/signoff_without_photos_rejected
        """
        ctx = _delivered_ctx("P-VAL7", "STORE-V7")
        resp = api_client.create_install_signoff(
            {"delivery_id": ctx["delivery"]["id"], "photo_urls": []},
            make_install_crew_lead_headers("crew-1"),
        )
        validate_error(resp, ApiErrorId.ERR_PHOTO_EVIDENCE_REQUIRED)

    def test_second_pending_signoff_rejected(self):
        """PRD §3.7: "A delivery may have at most one signoff awaiting review:
        while a `SUBMITTED` signoff exists for the same delivery, a further
        submission is rejected with `ERR_SIGNOFF_ALREADY_PENDING`."

        Design: Corner/validations/second_pending_signoff_rejected
        """
        ctx = _delivered_ctx("P-VAL8", "STORE-V8")
        first = create_signoff(ctx["delivery"]["id"],
                               photo_urls=["https://photos/v8a.jpg"],
                               submitter_user_id="crew-1")
        assert first["status"] == "SUBMITTED"
        resp = api_client.create_install_signoff(
            {"delivery_id": ctx["delivery"]["id"],
             "photo_urls": ["https://photos/v8b.jpg"]},
            make_install_crew_lead_headers("crew-2"),
        )
        validate_error(resp, ApiErrorId.ERR_SIGNOFF_ALREADY_PENDING)


class TestSignoffReviewSecurity:

    def test_crew_lead_cannot_approve_signoff_forbidden(self):
        """PRD §2.1: "When the role named in `X-User-Role` is not permitted to
        perform the requested operation, the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: the `/install-signoffs/{id}/approve` row authorizes only
        StoreManager.

        Design: Corner/rbac/crew_lead_cannot_approve_signoff_forbidden
        """
        ctx = _delivered_ctx("P-RBAC2", "STORE-R2")
        signoff = create_signoff(ctx["delivery"]["id"],
                                 photo_urls=["https://photos/r2.jpg"],
                                 submitter_user_id="crew-1")
        resp = api_client.approve_install_signoff(
            signoff["id"], make_install_crew_lead_headers("crew-9"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        after = validate_success(
            api_client.get_install_signoff(signoff["id"], PM))
        assert after["status"] == "SUBMITTED"

    def test_signoff_self_approval_blocked_by_sod(self):
        """PRD §3.7: "Approving a signoff requires it to be `SUBMITTED`
        (`ERR_SIGNOFF_INVALID_STATE` otherwise) and enforces segregation of
        duties: the approver's `X-User-ID` must differ from the signoff's
        `submitted_by_user_id`, or the approval fails with
        `ERR_SIGNOFF_SELF_APPROVAL` (HTTP 403)."

        Design: Corner/rbac/signoff_self_approval_blocked_by_sod
        """
        ctx = _delivered_ctx("P-RBAC3", "STORE-R3")
        signoff = create_signoff(ctx["delivery"]["id"],
                                 photo_urls=["https://photos/r3.jpg"],
                                 submitter_user_id="crew-1")
        # StoreManager role, but the same X-User-ID as the submitter.
        resp = api_client.approve_install_signoff(
            signoff["id"], make_store_manager_headers("crew-1"))
        validate_error(resp, ApiErrorId.ERR_SIGNOFF_SELF_APPROVAL)
        after = validate_success(
            api_client.get_install_signoff(signoff["id"], PM))
        assert after["status"] == "SUBMITTED"


class TestSignoffRejectResubmitCycle:

    def test_reject_resubmit_then_approve_completes_delivery(self):
        """PRD §3.7: "Resubmission replaces the photo evidence, clears
        `rejection_reason`, stamps `submitted_by_user_id` with the
        resubmitter's `X-User-ID`, increments `submission_count` by one, and
        returns the signoff to `SUBMITTED`, where it awaits a fresh review
        under the same self-approval guard against its most recent submitter."
        PRD §3.7: "The delivery evidenced by the signoff moves `DELIVERED →
        COMPLETE`. The kit that delivery carried moves `RELEASED → FULFILLED`,
        and the program's `fulfilled_kit_count` is incremented by one."

        Design: Difficulty/non_linear_state_machine/signoff_reject_resubmit_cycle
        """
        ctx = _delivered_ctx("P-SO")
        signoff = create_signoff(ctx["delivery"]["id"],
                                 photo_urls=["https://photos/s1a.jpg"],
                                 submitter_user_id="crew-7")
        reject_signoff(signoff["id"], "Missing wall-anchor photo", "sm-3")
        resubmitted = validate_success(api_client.resubmit_install_signoff(
            signoff["id"],
            {"photo_urls": ["https://photos/s1b.jpg",
                            "https://photos/s1c.jpg"],
             "notes": "Anchor photo added"},
            make_install_crew_lead_headers("crew-7"),
        ))
        assert resubmitted["status"] == "SUBMITTED"

        approved = approve_signoff(signoff["id"], "sm-3")
        assert_install_signoff(approved)
        assert approved["status"] == "APPROVED"
        assert approved["submission_count"] == 2
        assert approved["rejection_reason"] is None

        delivery_after = validate_success(
            api_client.get_install_delivery(ctx["delivery"]["id"], PM))
        assert delivery_after["status"] == "COMPLETE"
        kit_after = validate_success(
            api_client.get_store_kit_config(ctx["kit"]["id"], PM))
        assert kit_after["status"] == "FULFILLED"

    def test_reject_records_reason_and_resubmit_clears_it(self):
        """PRD §3.7: "A `StoreManager` may reject a `SUBMITTED` signoff
        (`ERR_SIGNOFF_INVALID_STATE` otherwise) by supplying a `reason`, which
        is recorded on the signoff as `rejection_reason` alongside the
        reviewer's identity in `reviewed_by_user_id`; the signoff moves
        `SUBMITTED → REJECTED`."
        PRD §3.7: "Resubmission replaces the photo evidence, clears
        `rejection_reason`, stamps `submitted_by_user_id` with the
        resubmitter's `X-User-ID`, increments `submission_count` by one, and
        returns the signoff to `SUBMITTED`, where it awaits a fresh review
        under the same self-approval guard against its most recent submitter."

        Design: Difficulty/non_linear_state_machine/signoff_reject_resubmit_cycle
        """
        ctx = _delivered_ctx("P-SO2", "STORE-S9")
        signoff = create_signoff(ctx["delivery"]["id"],
                                 photo_urls=["https://photos/s9a.jpg"],
                                 submitter_user_id="crew-7")
        rejected = reject_signoff(signoff["id"], "Missing wall-anchor photo",
                                  "sm-3")
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "Missing wall-anchor photo"
        assert rejected["reviewed_by_user_id"] == "sm-3"

        resubmitted = validate_success(api_client.resubmit_install_signoff(
            signoff["id"],
            {"photo_urls": ["https://photos/s9b.jpg"]},
            make_install_crew_lead_headers("crew-8"),
        ))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["submission_count"] == 2
        assert resubmitted["rejection_reason"] is None
        assert resubmitted["submitted_by_user_id"] == "crew-8"
        assert resubmitted["photo_urls"] == ["https://photos/s9b.jpg"]


class TestSignoffApprovalCascade:

    def _cascade_scenario(self, name="P-CASC"):
        """Kit (100 components at 3000) RELEASED via a capacity-200 wave;
        delivery DELIVERED; signoff SUBMITTED by crew-1."""
        ctx = setup_delivered_scenario(
            program_name=name,
            budget_total_cents=2_000_000,
            fixture_code="GONDOLA-8FT",
            bom_lines=GONDOLA_BOM,
            store_code="STORE-C1",
            config_lines=HUNDRED_AT_3000,
            wave_capacity=200,
            crew_code="CREW-C",
            estimated_install_hours=6,
        )
        ctx["signoff"] = create_signoff(
            ctx["delivery"]["id"], photo_urls=["https://photos/c1.jpg"],
            submitter_user_id="crew-1")
        return ctx

    def test_signoff_approval_fulfills_chain(self):
        """PRD §3.7: "Approval records the reviewer in `reviewed_by_user_id`,
        moves the signoff `SUBMITTED → APPROVED`, and then fires the longest
        cascade in the system, four hops in one atomic act. The delivery
        evidenced by the signoff moves `DELIVERED → COMPLETE`. The kit that
        delivery carried moves `RELEASED → FULFILLED`, and the program's
        `fulfilled_kit_count` is incremented by one. Finally, an attic stock
        ledger is automatically created for the fulfilled kit — exactly one per
        kit — with its `store_code` copied from the kit, its `quantity_on_hand`
        initialized to five percent of the kit's `total_components` rounded up
        to a whole unit, its `unit_cost_cents` set to the kit's
        `kit_total_cost_cents` divided by its `total_components` and rounded
        half up to a whole cent, its `reorder_point` defaulted to 2, its
        `reorder_required` evaluated immediately per §3.8, and its status
        `ACTIVE`."

        Design: Difficulty/transitive_cascade/signoff_approval_fulfills_chain
        """
        ctx = self._cascade_scenario()
        approved = approve_signoff(ctx["signoff"]["id"], "sm-1")
        assert approved["status"] == "APPROVED"
        assert approved["reviewed_by_user_id"] == "sm-1"

        delivery_after = validate_success(
            api_client.get_install_delivery(ctx["delivery"]["id"], PM))
        assert delivery_after["status"] == "COMPLETE"
        kit_after = validate_success(
            api_client.get_store_kit_config(ctx["kit"]["id"], PM))
        assert kit_after["status"] == "FULFILLED"
        program_after = validate_success(
            api_client.get_rollout_program(ctx["program"]["id"], PM))
        assert program_after["fulfilled_kit_count"] == 1

        ledger = get_kit_ledger(ctx["kit"]["id"])
        # ceil(100 * 0.05) = 5; round_half_up(318000 / 100) = 3180.
        assert ledger["quantity_on_hand"] == 5
        assert ledger["unit_cost_cents"] == 3_180
        assert ledger["status"] == "ACTIVE"

    def test_signoff_approval_creates_exactly_one_ledger_with_kit_fields(self):
        """PRD §3.7: "Finally, an attic stock ledger is automatically created
        for the fulfilled kit — exactly one per kit — with its `store_code`
        copied from the kit, its `quantity_on_hand` initialized to five percent
        of the kit's `total_components` rounded up to a whole unit, its
        `unit_cost_cents` set to the kit's `kit_total_cost_cents` divided by
        its `total_components` and rounded half up to a whole cent, its
        `reorder_point` defaulted to 2, its `reorder_required` evaluated
        immediately per §3.8, and its status `ACTIVE`."

        Design: Difficulty/transitive_cascade/signoff_approval_fulfills_chain
        """
        ctx = self._cascade_scenario("P-CASC2")
        approve_signoff(ctx["signoff"]["id"], "sm-1")
        ledgers, meta = validate_paginated(
            api_client.list_attic_stock_ledgers(
                PM, params={"kit_id": ctx["kit"]["id"]}))
        assert meta["total_count"] == 1, "exactly one ledger per kit"
        ledger = ledgers[0]
        assert ledger["kit_id"] == ctx["kit"]["id"]
        assert ledger["store_code"] == "STORE-C1"
        assert ledger["reorder_point"] == 2
        assert ledger["reorder_required"] is False  # 5 on hand > point 2
        assert ledger["disposition_type"] is None
        assert ledger["recovery_value_cents"] is None


class TestChildDiscovery:

    def test_fk_filtered_list_reverse_reachability(self):
        """PRD §2.3: "Damage claims and install signoffs each filter by
        `delivery_id` and `status`."

        Design: Corner/endpoints/fk_filtered_list_reverse_reachability
        """
        ctx = _delivered_ctx("P-EP1", "STORE-E2")
        claim = create_claim(ctx["delivery"]["id"], "PN-600", "MISSING", 1, 200)
        signoff = create_signoff(ctx["delivery"]["id"],
                                 photo_urls=["https://photos/e2.jpg"],
                                 submitter_user_id="crew-1")

        signoffs, smeta = validate_paginated(
            api_client.list_install_signoffs(
                PM, params={"delivery_id": ctx["delivery"]["id"]}))
        assert smeta["total_count"] == 1
        assert signoffs[0]["id"] == signoff["id"]

        claims, cmeta = validate_paginated(
            api_client.list_damage_claims(
                PM, params={"delivery_id": ctx["delivery"]["id"]}))
        assert cmeta["total_count"] == 1
        assert claims[0]["id"] == claim["id"]

        empty, emeta = validate_paginated(
            api_client.list_damage_claims(
                PM, params={"delivery_id":
                            "00000000-0000-0000-0000-000000000000"}))
        assert emeta["total_count"] == 0
        assert empty == []
