"""Lifecycles that are not a single line: two independent dimensions on a
complaint, and a bounded revision loop on a remedy."""

from test_helpers import (
    ILLNESS_S1_COMPLAINT,
    ApiErrorId,
    add_template,
    decide_remedy,
    determine_report,
    find_report,
    respond,
    seed_submitted_remedy,
    seed_triaged_complaint,
    seed_base_world,
    submit_remedy,
    submit_report,
    validate_error,
    validate_success,
)

# ---------------------------------------------------------------------------
# The two status dimensions of a complaint
# ---------------------------------------------------------------------------
def _seed_escalated_illness(api):
    """An S1 illness complaint: triaged in handling, escalated in regulatory."""
    world = seed_base_world(api, actor_keys=("ag1", "sup1", "ro1", "ro2"))
    seed_triaged_complaint(api, world, **ILLNESS_S1_COMPLAINT)
    add_template(
        api,
        world,
        "t1",
        template_code="T-ILL",
        applies_to_type="ILLNESS",
        max_band_allowed="S1",
    )
    return world


class TestComplaintDimensionsAdvanceIndependently:
    def test_handling_dimension_advances_while_regulatory_stays_escalated(self, api):
        """Sending the response and resolving never touch the regulatory dimension.

        PRD: "`regulatory_status` is the regulatory dimension and takes one of
        `NOT_APPLICABLE`, `ESCALATED`, `REPORTABLE`, `NOT_REPORTABLE`, or
        `SUBMITTED`; it begins at `NOT_APPLICABLE` and `SUBMITTED` is terminal
        for that dimension."

        Design: Difficulty/non_linear_state_machine/complaint_handling_and_regulatory_dimensions_advance_independently
        """
        world = _seed_escalated_illness(api)
        complaint_id = world["complaints"]["cp1"]["id"]
        assert world["complaints"]["cp1"]["handling_status"] == "TRIAGED"
        assert world["complaints"]["cp1"]["regulatory_status"] == "ESCALATED"

        responded = respond(api, world, complaint_id, world["templates"]["t1"]["id"])
        assert responded["handling_status"] == "IN_RESOLUTION"
        assert responded["regulatory_status"] == "ESCALATED"

        resolved = validate_success(
            api.resolve_complaint(
                complaint_id, {"resolution_note": "Consumer answered."},
                world.headers("ag1"),
            )
        )
        assert resolved["handling_status"] == "RESOLVED"
        assert resolved["regulatory_status"] == "ESCALATED"

    def test_regulatory_dimension_advances_while_handling_stays_put(self, api):
        """A reportable determination moves only the regulatory dimension.

        PRD: "A `REPORTABLE` verdict moves the report `OPEN →
        DETERMINED_REPORTABLE`, stamps `determined_by_ref` with the deciding
        officer, and advances the complaint `ESCALATED → REPORTABLE`."

        Design: Difficulty/non_linear_state_machine/complaint_handling_and_regulatory_dimensions_advance_independently
        """
        world = _seed_escalated_illness(api)
        complaint_id = world["complaints"]["cp1"]["id"]
        respond(api, world, complaint_id, world["templates"]["t1"]["id"])

        report = find_report(api, world, complaint_id)
        determined = determine_report(api, world, report["id"], "REPORTABLE")

        assert determined["status"] == "DETERMINED_REPORTABLE"
        complaint = validate_success(
            api.get_complaint(complaint_id, world.headers("sup1"))
        )
        assert complaint["regulatory_status"] == "REPORTABLE"
        assert complaint["handling_status"] == "IN_RESOLUTION"

    def test_closure_is_the_single_point_where_the_dimensions_meet(self, api):
        """Closure is refused until the filing lands, then succeeds unchanged.

        PRD: "Closure is the one point where the two dimensions of §2.10 meet:
        it requires that `regulatory_status` has settled into `NOT_APPLICABLE`,
        `NOT_REPORTABLE`, or `SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/complaint_handling_and_regulatory_dimensions_advance_independently
        """
        world = _seed_escalated_illness(api)
        complaint_id = world["complaints"]["cp1"]["id"]
        respond(api, world, complaint_id, world["templates"]["t1"]["id"])
        report = find_report(api, world, complaint_id)
        determine_report(api, world, report["id"], "REPORTABLE")
        validate_success(
            api.resolve_complaint(
                complaint_id, {"resolution_note": "Done."}, world.headers("ag1")
            )
        )

        blocked = api.close_complaint(
            complaint_id, {"closing_note": "Closing early."}, world.headers("sup1")
        )
        validate_error(blocked, ApiErrorId.REGULATORY_STATE_INVALID, 409)
        still_open = validate_success(
            api.get_complaint(complaint_id, world.headers("sup1"))
        )
        assert still_open["handling_status"] == "RESOLVED"

        filed = submit_report(
            api, world, report["id"], actor="ro2", agency_reference="AG-99001"
        )
        assert filed["status"] == "SUBMITTED"

        closed = validate_success(
            api.close_complaint(
                complaint_id, {"closing_note": "Closing now."}, world.headers("sup1")
            )
        )
        assert closed["handling_status"] == "CLOSED"
        assert closed["regulatory_status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# The bounded revision loop on a remedy
# ---------------------------------------------------------------------------
def _seed_submitted_coupon(api):
    world = seed_base_world(api, actor_keys=("ag1", "sup1"))
    seed_triaged_complaint(api, world, complaint_type="QUALITY")
    seed_submitted_remedy(
        api,
        world,
        world["complaints"]["cp1"]["id"],
        remedy_type="COUPON",
        requested_value_cents=2000,
    )
    return world


class TestRemedyRevisionLoop:
    def test_each_revision_round_returns_the_remedy_to_its_author(self, api):
        """Two revision rounds are permitted and each one raises the counter.

        PRD: "`REQUEST_REVISION` moves the remedy `SUBMITTED →
        REVISION_REQUESTED` and raises `revision_count` by one, and it
        additionally requires that `revision_count` is still strictly below the
        cap of 2; at the cap the supervisor must approve or reject instead, and a
        further revision attempt is refused with `ERR_REVISION_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/remedy_revision_cycle_is_bounded_at_two
        """
        world = _seed_submitted_coupon(api)
        remedy_id = world["remedies"]["rm1"]["id"]

        first = decide_remedy(api, world, remedy_id, "REQUEST_REVISION")
        assert first["status"] == "REVISION_REQUESTED"
        assert first["revision_count"] == 1

        resubmitted = submit_remedy(api, world, remedy_id)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_count"] == 1

        second = decide_remedy(api, world, remedy_id, "REQUEST_REVISION")
        assert second["status"] == "REVISION_REQUESTED"
        assert second["revision_count"] == 2

        again = submit_remedy(api, world, remedy_id)
        assert again["status"] == "SUBMITTED"

    def test_third_revision_is_refused_and_the_decision_must_settle(self, api):
        """At the cap the remedy stays submitted until it is approved or rejected.

        PRD: "On `POST /remedies/{id}/decide` with a revision decision,
        `revision_count` is still below the revision cap — otherwise
        `ERR_REVISION_LIMIT_REACHED` (409)."

        Design: Difficulty/non_linear_state_machine/remedy_revision_cycle_is_bounded_at_two
        """
        world = _seed_submitted_coupon(api)
        remedy_id = world["remedies"]["rm1"]["id"]
        for _round in range(2):
            decide_remedy(api, world, remedy_id, "REQUEST_REVISION")
            submit_remedy(api, world, remedy_id)

        refused = api.decide_remedy(
            remedy_id,
            {"decision": "REQUEST_REVISION", "decision_note": "Once more."},
            world.headers("sup1"),
        )
        validate_error(refused, ApiErrorId.REVISION_LIMIT_REACHED, 409)

        stuck = validate_success(api.get_remedy(remedy_id, world.headers("sup1")))
        assert stuck["status"] == "SUBMITTED"
        assert stuck["revision_count"] == 2

        approved = decide_remedy(api, world, remedy_id, "APPROVE")
        assert approved["status"] == "APPROVED"
        assert approved["revision_count"] == 2
        assert approved["base_value_cents"] == 2000
        assert approved["uplift_cents"] == 200
        assert approved["payout_cents"] == 2200
        assert approved["authority_tier_required"] == "TIER_1"
