"""Writes whose legality is decided by the state of a neighbouring entity."""

from test_helpers import (
    CLOCK_EPOCH_MS,
    ApiErrorId,
    add_complaint,
    add_contact,
    add_lot,
    add_template,
    assert_goodwill_ledger,
    decide_remedy,
    seed_base_world,
    seed_shipped_kit,
    seed_submitted_remedy,
    seed_triaged_complaint,
    triage,
    validate_error,
    validate_success,
)

# ---------------------------------------------------------------------------
# Responding depends on the release status of the lot behind the complaint
# ---------------------------------------------------------------------------
def _seed_withdrawn_and_released_lots(api):
    """One template and two mild complaints, one per lot, with one lot withdrawn."""
    world = seed_base_world(api, actor_keys=("ag1", "sup1", "ql1"), create_lot=False)
    add_lot(
        api, world, "lotw", batch_code="LOT-W", code_date="2026-07-10T00:00:00Z"
    )
    add_lot(
        api, world, "lotr", batch_code="LOT-R", code_date="2026-07-11T00:00:00Z"
    )
    add_template(
        api,
        world,
        "tqual",
        template_code="T-QUAL",
        applies_to_type="QUALITY",
        max_band_allowed="S4",
    )
    add_contact(api, world, "ct1")
    for key, batch in (("cpw", "LOTW"), ("cpr", "LOTR")):
        add_complaint(
            api, world, key, complaint_type="QUALITY", reported_batch_code=batch
        )
        world["complaints"][key] = triage(api, world, world["complaints"][key]["id"])
    lead = world.headers("ql1")
    validate_success(
        api.hold_production_lot(
            world["lots"]["lotw"]["id"], {"reason": "Consumer reports clustered."}, lead
        )
    )
    validate_success(
        api.withdraw_production_lot(
            world["lots"]["lotw"]["id"], {"reason": "Stock destroyed."}, lead
        )
    )
    return world


class TestResponseDependsOnLotReleaseStatus:
    def test_withdrawn_lot_freezes_canned_messaging_about_it(self, api):
        """The template fits the complaint perfectly and the lot still blocks the send.

        PRD: "First, the complaint's linked lot must not be `WITHDRAWN` — once a
        lot is withdrawn, canned consumer messaging about it is frozen, and the
        attempt fails with `ERR_LOT_WITHDRAWN`."

        Design: Difficulty/cross_entity_state_dependency/respond_depends_on_production_lot_release_status
        """
        world = _seed_withdrawn_and_released_lots(api)
        withdrawn = validate_success(
            api.get_production_lot(world["lots"]["lotw"]["id"], world.headers("ql1"))
        )
        assert withdrawn["release_status"] == "WITHDRAWN"
        assert world["templates"]["tqual"]["applies_to_type"] == "QUALITY"
        assert world["complaints"]["cpw"]["effective_severity_band"] == "S4"

        refused = api.respond_to_complaint(
            world["complaints"]["cpw"]["id"],
            {"response_template_id": world["templates"]["tqual"]["id"]},
            world.headers("ag1"),
        )
        validate_error(refused, ApiErrorId.LOT_WITHDRAWN, 409)

        complaint = validate_success(
            api.get_complaint(world["complaints"]["cpw"]["id"], world.headers("sup1"))
        )
        assert complaint["handling_status"] == "TRIAGED"
        assert complaint["responded_at"] is None

    def test_same_template_answers_the_complaint_on_the_released_lot(self, api):
        """Only the neighbouring lot differs, and that is enough to flip the outcome.

        PRD: "A successful response moves the complaint `TRIAGED →
        IN_RESOLUTION`, sets `responded_template_id` to the chosen template and
        `responded_at` to the logical clock, and raises the template's
        `usage_count` by one."

        Design: Difficulty/cross_entity_state_dependency/respond_depends_on_production_lot_release_status
        """
        world = _seed_withdrawn_and_released_lots(api)
        template_id = world["templates"]["tqual"]["id"]

        responded = validate_success(
            api.respond_to_complaint(
                world["complaints"]["cpr"]["id"],
                {"response_template_id": template_id},
                world.headers("ag1"),
            )
        )

        assert responded["handling_status"] == "IN_RESOLUTION"
        assert responded["responded_template_id"] == template_id
        assert responded["responded_at"] == CLOCK_EPOCH_MS

        template = validate_success(
            api.get_response_template(template_id, world.headers("sup1"))
        )
        assert template["usage_count"] == 1


# ---------------------------------------------------------------------------
# Approving goodwill depends on where the physical evidence is
# ---------------------------------------------------------------------------
def _seed_submitted_remedy_behind_a_shipped_kit(api):
    """A submitted coupon on a complaint whose kit is still out with the consumer."""
    world = seed_base_world(api, actor_keys=("ag1", "sup1"))
    seed_triaged_complaint(
        api,
        world,
        complaint_type="FOREIGN_MATERIAL",
        foreign_object_class="SOFT",
        units_claimed=1,
    )
    complaint_id = world["complaints"]["cp1"]["id"]
    seed_shipped_kit(
        api, world, complaint_id, "k1", kit_code="K-100", seal_id_issued="SEAL-100"
    )
    seed_submitted_remedy(
        api, world, complaint_id, "rm1", remedy_type="COUPON",
        requested_value_cents=2000,
    )
    return world


class TestRemedyApprovalDependsOnSampleKitStatus:
    def test_approval_is_refused_while_the_evidence_is_in_transit(self, api):
        """The kit is shipped, so the coupon cannot be approved yet.

        PRD: "On `POST /remedies/{id}/decide`, the complaint's kit, if one
        exists, is not in `REQUESTED`, `SHIPPED`, or `IN_TRANSIT_INBOUND` —
        otherwise `ERR_SAMPLE_KIT_IN_FLIGHT` (409)."

        Design: Difficulty/cross_entity_state_dependency/remedy_approval_depends_on_sample_kit_status
        """
        world = _seed_submitted_remedy_behind_a_shipped_kit(api)
        assert world["kits"]["k1"]["status"] == "SHIPPED"
        assert world["remedies"]["rm1"]["status"] == "SUBMITTED"

        refused = api.decide_remedy(
            world["remedies"]["rm1"]["id"],
            {"decision": "APPROVE", "decision_note": "Approving the coupon."},
            world.headers("sup1"),
        )
        validate_error(refused, ApiErrorId.SAMPLE_KIT_IN_FLIGHT, 409)

        remedy = validate_success(
            api.get_remedy(world["remedies"]["rm1"]["id"], world.headers("sup1"))
        )
        assert remedy["status"] == "SUBMITTED"
        consumer = validate_success(
            api.get_consumer(world["consumer"]["id"], world.headers("sup1"))
        )
        assert_goodwill_ledger(consumer, authorized=0, outstanding=0, paid=0, voided=0)

    def test_cancelling_the_kit_frees_the_complaint_and_the_slot(self, api):
        """Abandoning the sample ends the kit's life and releases the consumer's slot.

        PRD: "A `CareSupervisor` may cancel an unreturned kit, optionally with a
        `reason`, from either `REQUESTED` or `SHIPPED`; the kit becomes
        `CANCELLED`, which is terminal, the parent complaint moves
        `AWAITING_SAMPLE → IN_RESOLUTION`, and the consumer's `open_kit_count`
        falls by one."

        Design: Difficulty/cross_entity_state_dependency/remedy_approval_depends_on_sample_kit_status
        """
        world = _seed_submitted_remedy_behind_a_shipped_kit(api)
        before = validate_success(
            api.get_consumer(world["consumer"]["id"], world.headers("sup1"))
        )
        assert before["open_kit_count"] == 1

        cancelled = validate_success(
            api.cancel_sample_kit(
                world["kits"]["k1"]["id"],
                {"reason": "Consumer discarded the sample."},
                world.headers("sup1"),
            )
        )
        assert cancelled["status"] == "CANCELLED"

        complaint = validate_success(
            api.get_complaint(world["complaints"]["cp1"]["id"], world.headers("sup1"))
        )
        assert complaint["handling_status"] == "IN_RESOLUTION"
        after = validate_success(
            api.get_consumer(world["consumer"]["id"], world.headers("sup1"))
        )
        assert after["open_kit_count"] == 0

    def test_the_identical_decision_succeeds_once_the_kit_is_out_of_flight(self, api):
        """Nothing about the remedy changes; only the kit's status does.

        PRD: "Approval raises the consumer's `goodwill_authorized_cents` and
        `goodwill_outstanding_cents` each by `payout_cents`."

        Design: Difficulty/cross_entity_state_dependency/remedy_approval_depends_on_sample_kit_status
        """
        world = _seed_submitted_remedy_behind_a_shipped_kit(api)
        validate_success(
            api.cancel_sample_kit(
                world["kits"]["k1"]["id"],
                {"reason": "Consumer discarded the sample."},
                world.headers("sup1"),
            )
        )

        approved = decide_remedy(
            api, world, world["remedies"]["rm1"]["id"], "APPROVE"
        )

        assert approved["status"] == "APPROVED"
        assert approved["payout_cents"] == 2200
        consumer = validate_success(
            api.get_consumer(world["consumer"]["id"], world.headers("sup1"))
        )
        assert_goodwill_ledger(consumer, authorized=2200, outstanding=2200)
