"""Requests that violate two rules at once, where the ladder decides the answer."""

from test_helpers import (
    CLOCK_EPOCH,
    ApiErrorId,
    add_complaint,
    add_contact,
    add_kit,
    add_template,
    assert_goodwill_ledger,
    seed_approved_remedy,
    seed_base_world,
    seed_shipped_kit,
    seed_triaged_complaint,
    shift,
    triage,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Remedy state (step 18) outranks the authority tier (step 45)
# ---------------------------------------------------------------------------
def _seed_approved_refund(api):
    """A 5,390-cent refund already approved by the tier-3 supervisor."""
    world = seed_base_world(api, actor_keys=("ag1", "sup1", "sup2"))
    seed_triaged_complaint(api, world, complaint_type="QUALITY", units_claimed=2)
    seed_approved_remedy(
        api,
        world,
        world["complaints"]["cp1"]["id"],
        "rm1",
        remedy_type="REFUND",
        requested_value_cents=4900,
        author="ag1",
        decider="sup1",
    )
    return world


class TestRemedyStateBeatsAuthorityTier:
    def test_second_decision_reports_the_state_error_not_the_tier_shortfall(self, api):
        """A tier-1 supervisor deciding an approved TIER_2 remedy sees the state error.

        PRD: "The remedy's `status` permits the requested transition —
        otherwise `ERR_REMEDY_STATE_INVALID` (409). Applies to `POST
        /remedies/{id}/submit`, `/decide`, `/fulfill`, and `/void`. Deliberately
        ranked **above** the authority-tier fiscal rule, so a remedy that is
        both in the wrong state and beyond the decider's tier reports the state
        error."

        Design: Difficulty/priority_pair_validation_conflict/remedy_state_beats_authority_tier
        """
        world = _seed_approved_refund(api)
        remedy = world["remedies"]["rm1"]
        assert remedy["status"] == "APPROVED"
        assert remedy["payout_cents"] == 5390
        assert remedy["authority_tier_required"] == "TIER_2"
        assert world.actor("sup2").authority_tier == "TIER_1"

        refused = api.decide_remedy(
            remedy["id"],
            {"decision": "APPROVE", "decision_note": "Approving again."},
            world.headers("sup2"),
        )

        error = validate_error(refused, ApiErrorId.REMEDY_STATE_INVALID, 409)
        assert error["error_id"] != ApiErrorId.AUTHORITY_TIER_INSUFFICIENT

    def test_refused_decision_leaves_the_stamp_and_the_ledger_untouched(self, api):
        """The original decider and the authorized total both survive the refusal.

        PRD: "Approval raises the consumer's `goodwill_authorized_cents` and
        `goodwill_outstanding_cents` each by `payout_cents`."

        Design: Difficulty/priority_pair_validation_conflict/remedy_state_beats_authority_tier
        """
        world = _seed_approved_refund(api)
        remedy = world["remedies"]["rm1"]

        api.decide_remedy(
            remedy["id"],
            {"decision": "APPROVE", "decision_note": "Approving again."},
            world.headers("sup2"),
        )

        after = validate_success(api.get_remedy(remedy["id"], world.headers("sup1")))
        assert after["status"] == "APPROVED"
        assert after["decided_by_ref"] == world.actor("sup1").id
        consumer = validate_success(
            api.get_consumer(world["consumer"]["id"], world.headers("sup1"))
        )
        assert_goodwill_ledger(consumer, authorized=5390, outstanding=5390)


# ---------------------------------------------------------------------------
# The withdrawn lot (step 26) outranks the template rules (step 42)
# ---------------------------------------------------------------------------
def _seed_withdrawn_lot_response(api):
    """A mild QUALITY complaint on a withdrawn lot, plus a packaging-only template."""
    world = seed_base_world(api, actor_keys=("ag1", "sup1", "ql1"))
    seed_triaged_complaint(api, world, complaint_type="QUALITY")
    add_template(
        api,
        world,
        "tpack",
        template_code="T-PACK",
        applies_to_type="PACKAGING",
        max_band_allowed="S1",
    )
    lead = world.headers("ql1")
    validate_success(
        api.hold_production_lot(
            world["lot"]["id"], {"reason": "Staling review."}, lead
        )
    )
    validate_success(
        api.withdraw_production_lot(
            world["lot"]["id"], {"reason": "Pulled from trade."}, lead
        )
    )
    return world


class TestWithdrawnLotBeatsTemplateMismatch:
    def test_withdrawn_lot_masks_the_template_type_mismatch(self, api):
        """A packaging template on a quality complaint still reports the lot problem.

        PRD: "On `POST /complaints/{id}/respond`, the complaint's linked lot is
        not `WITHDRAWN` — otherwise `ERR_LOT_WITHDRAWN` (409). Ranked **above**
        the template-eligibility rules in steps 42 and 43, so a withdrawn lot
        masks a template mismatch."

        Design: Difficulty/priority_pair_validation_conflict/withdrawn_lot_beats_template_type_mismatch
        """
        world = _seed_withdrawn_lot_response(api)
        assert world["complaints"]["cp1"]["effective_severity_band"] == "S4"
        assert world["templates"]["tpack"]["status"] == "ACTIVE"

        refused = api.respond_to_complaint(
            world["complaints"]["cp1"]["id"],
            {"response_template_id": world["templates"]["tpack"]["id"]},
            world.headers("ag1"),
        )

        error = validate_error(refused, ApiErrorId.LOT_WITHDRAWN, 409)
        assert error["error_id"] != ApiErrorId.TEMPLATE_TYPE_MISMATCH

    def test_refused_response_neither_stamps_the_complaint_nor_uses_the_template(self, api):
        """No response instant, no template link, no usage increment.

        PRD: "A successful response moves the complaint `TRIAGED →
        IN_RESOLUTION`, sets `responded_template_id` to the chosen template and
        `responded_at` to the logical clock, and raises the template's
        `usage_count` by one."

        Design: Difficulty/priority_pair_validation_conflict/withdrawn_lot_beats_template_type_mismatch
        """
        world = _seed_withdrawn_lot_response(api)

        api.respond_to_complaint(
            world["complaints"]["cp1"]["id"],
            {"response_template_id": world["templates"]["tpack"]["id"]},
            world.headers("ag1"),
        )

        complaint = validate_success(
            api.get_complaint(world["complaints"]["cp1"]["id"], world.headers("sup1"))
        )
        assert complaint["handling_status"] == "TRIAGED"
        assert complaint["responded_at"] is None
        assert complaint["responded_template_id"] is None
        template = validate_success(
            api.get_response_template(
                world["templates"]["tpack"]["id"], world.headers("sup1")
            )
        )
        assert template["usage_count"] == 0


# ---------------------------------------------------------------------------
# The occupancy interval (step 34) outranks the address check (step 38)
# ---------------------------------------------------------------------------
def _seed_two_kits_and_no_postal_code(api):
    """One shipped kit holding the interval, one requested kit, no address on file."""
    world = seed_base_world(api, actor_keys=("ag1", "sup1"))
    add_contact(api, world, "ct1")
    for key in ("cpa", "cpb"):
        add_complaint(
            api,
            world,
            key,
            complaint_type="FOREIGN_MATERIAL",
            foreign_object_class="SOFT",
        )
        world["complaints"][key] = triage(api, world, world["complaints"][key]["id"])
    seed_shipped_kit(
        api,
        world,
        world["complaints"]["cpa"]["id"],
        "k1",
        kit_code="K-001",
        seal_id_issued="SEAL-001",
    )
    add_kit(
        api,
        world,
        world["complaints"]["cpb"]["id"],
        "k2",
        kit_code="K-002",
        seal_id_issued="SEAL-002",
    )
    validate_success(
        api.update_consumer(
            world["consumer"]["id"], {"postal_code": None}, world.headers("sup1")
        )
    )
    return world


class TestKitIntervalConflictBeatsMissingAddress:
    def test_dispatch_stamps_the_closed_occupancy_interval(self, api):
        """Fourteen days to return and 48 hours of slack at either end.

        PRD: "`occupied_from` is 48 hours before `shipped_at`, and
        `occupied_until` is 48 hours after `expected_return_by`; together they
        bound a **closed** exclusivity interval — closed at both ends, unlike
        the half-open detection window used for trend monitoring — during which
        the consumer may not hold another kit."

        Design: Difficulty/priority_pair_validation_conflict/kit_interval_conflict_beats_missing_postal_code
        """
        world = _seed_two_kits_and_no_postal_code(api)
        kit = validate_success(
            api.get_sample_kit(world["kits"]["k1"]["id"], world.headers("ag1"))
        )

        assert kit["shipped_at"] == shift(CLOCK_EPOCH)
        assert kit["expected_return_by"] == shift(CLOCK_EPOCH, days=14)
        assert kit["occupied_from"] == shift(CLOCK_EPOCH, hours=-48)
        assert kit["occupied_until"] == shift(CLOCK_EPOCH, days=14, hours=48)

    def test_interval_conflict_masks_the_missing_postal_code(self, api):
        """Both rules are genuinely violated and the interval rule answers first.

        PRD: "On `POST /sample-kits/{id}/ship`, the consumer holds no other kit
        whose closed occupancy interval contains the prospective `shipped_at` —
        otherwise `ERR_KIT_INTERVAL_CONFLICT` (409). Ranked **above** the
        address-completeness rule in step 38, so an interval collision masks a
        missing postal code."

        Design: Difficulty/priority_pair_validation_conflict/kit_interval_conflict_beats_missing_postal_code
        """
        world = _seed_two_kits_and_no_postal_code(api)
        consumer = validate_success(
            api.get_consumer(world["consumer"]["id"], world.headers("sup1"))
        )
        assert not consumer["postal_code"]

        refused = api.ship_sample_kit(
            world["kits"]["k2"]["id"], {}, world.headers("ag1")
        )

        error = validate_error(refused, ApiErrorId.KIT_INTERVAL_CONFLICT, 409)
        assert error["error_id"] != ApiErrorId.CONSUMER_ADDRESS_MISSING

        kit = validate_success(
            api.get_sample_kit(world["kits"]["k2"]["id"], world.headers("ag1"))
        )
        assert kit["status"] == "REQUESTED"
        assert kit["shipped_at"] is None
        assert kit["custody_event_count"] == 0
        _events, meta = validate_paginated(
            api.list_custody_events(world["kits"]["k2"]["id"], world.headers("ag1"))
        )
        assert meta["total_count"] == 0
