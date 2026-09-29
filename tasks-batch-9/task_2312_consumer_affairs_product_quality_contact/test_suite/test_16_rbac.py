"""Who may act, and in whose name: the identity checks that run before any
business rule, the role lists that make each operation exclusive, and the two
places where the same person may not stand on both sides of a decision."""

from test_helpers import (
    ADMIN,
    CLOCK_EPOCH_MS,
    CLOCK_HEADERS,
    ILLNESS_S1_COMPLAINT,
    ROLE_CARE_AGENT,
    ROLE_SYSTEM_ADMIN,
    STAFF_ROLE_CARE_SUPERVISOR,
    ApiErrorId,
    add_consumer,
    add_contact,
    add_remedy,
    assert_goodwill_ledger,
    assert_goodwill_math,
    assert_severity,
    assert_two_decimal_value,
    complaint_payload,
    contact_payload,
    decide_payload,
    determine_report,
    find_report,
    make_care_agent_headers,
    make_care_supervisor_headers,
    make_consumer_headers,
    plant_payload,
    quality_ops_run_payload,
    regulatory_report_payload,
    response_template_payload,
    seed_base_world,
    seed_submitted_remedy,
    seed_triaged_complaint,
    staff_user_payload,
    submit_remedy,
    submit_report_payload,
    trend_signal_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

GHOST_COMPLAINT_ID = "00000000-0000-0000-0000-0000000000ff"
GHOST_ACTOR_ID = "00000000-0000-0000-0000-0000000000aa"
PLANT_WINDOW = dict(
    window_start="2026-07-01T00:00:00Z", window_end="2026-08-02T00:00:00Z"
)


def _role_only(role: str) -> dict:
    """Headers that declare a capacity but name no acting principal at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
class TestAuthenticationOutranksEverything:
    def test_only_the_clock_may_be_called_without_an_acting_principal(self, api):
        """No actor header: the clock still works, every other surface is 401.

        PRD: "A request that omits `X-User-ID`, or supplies it blank, is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the
        request is inspected."

        Design: Corner/rbac/corner_missing_actor_header_is_unauthenticated_everywhere_but_the_clock
        """
        agent = _role_only(ROLE_CARE_AGENT)
        admin = _role_only(ROLE_SYSTEM_ADMIN)
        assert "X-User-ID" not in agent
        assert "X-User-ID" not in admin
        assert "X-User-ID" not in CLOCK_HEADERS

        clock = validate_success(api.set_clock(CLOCK_EPOCH_MS, CLOCK_HEADERS))
        assert clock["current_utc"] == CLOCK_EPOCH_MS

        validate_error(
            api.list_complaints(agent), ApiErrorId.UNAUTHENTICATED, 401
        )
        # An unresolvable path id is never even looked up.
        validate_error(
            api.get_complaint(GHOST_COMPLAINT_ID, agent),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )
        # Nor is the body: a request with no fields at all fails on identity first.
        validate_error(
            api.create_consumer({}, agent), ApiErrorId.UNAUTHENTICATED, 401
        )
        validate_error(
            api.create_consumer(
                {"external_ref": "C-NOAUTH", "full_name": "No Auth"}, agent
            ),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )
        # The operator surface is no exception.
        validate_error(
            api.list_staff_users(admin), ApiErrorId.UNAUTHENTICATED, 401
        )

    def test_an_unresolvable_or_deactivated_identity_is_no_identity(self, api):
        """One code covers both failures, and it beats role, existence and shape.

        PRD: "If the header is present but does not resolve to an existing record
        — or resolves to a `StaffUser` whose `is_active` is false — the request is
        rejected with `ERR_UNKNOWN_ACTOR` (HTTP 401)."

        Design: Corner/rbac/corner_unknown_and_deactivated_actors_are_both_rejected
        """
        world = seed_base_world(api, actor_keys=("ag1",), create_lot=False)
        retired = validate_success(
            api.create_staff_user(
                staff_user_payload(
                    "SUPX",
                    "Sid Gone",
                    STAFF_ROLE_CARE_SUPERVISOR,
                    authority_tier="TIER_3",
                    is_active=False,
                ),
                ADMIN,
            ),
            201,
        )
        assert retired["is_active"] is False

        nobody = make_care_agent_headers(GHOST_ACTOR_ID)
        validate_error(api.list_complaints(nobody), ApiErrorId.UNKNOWN_ACTOR, 401)

        revoked = make_care_supervisor_headers(retired["id"])
        validate_error(api.list_complaints(revoked), ApiErrorId.UNKNOWN_ACTOR, 401)

        # A supervisor may not raise trend signals, the named plant is really a
        # consumer, and a PLANT scope may not be shaped that way — identity still
        # answers first.
        misdirected = api.create_trend_signal(
            trend_signal_payload("PLANT", world["consumer"]["id"], **PLANT_WINDOW),
            revoked,
        )
        validate_error(misdirected, ApiErrorId.UNKNOWN_ACTOR, 401)

        still_on_file = validate_success(api.get_staff_user(retired["id"], ADMIN))
        assert still_on_file["is_active"] is False
        assert still_on_file["staff_code"] == "SUPX"

        _rows, meta = validate_paginated(api.list_complaints(world.headers("ag1")))
        assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Role exclusivity
# ---------------------------------------------------------------------------
class TestRoleExclusivity:
    def test_each_exclusive_operation_is_refused_to_its_plausible_peers(self, api):
        """Seven wrong-role attempts, seven 403s, and nothing written anywhere.

        PRD: "Only after both of those checks pass does the server compare the
        declared role against the roles authorized for the endpoint in §4; a
        caller outside that list is rejected with `ERR_UNAUTHORIZED` (HTTP 403),
        and because that comparison happens before any path identifier is looked
        up, an unauthorized caller never learns whether the resource they named
        exists."

        Design: Corner/rbac/corner_role_exclusive_operations_are_refused_to_every_peer
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1", "ql1", "ro1"))
        seed_triaged_complaint(
            api,
            world,
            contact_overrides={"channel": "PHONE", "raw_message": "Stale pack."},
            complaint_type="QUALITY",
        )
        complaint_id = world["complaints"]["cp1"]["id"]
        remedy = add_remedy(
            api, world, complaint_id, requested_value_cents=1200, actor="ag1"
        )
        assert remedy["status"] == "DRAFT"
        agent = world.headers("ag1")
        supervisor = world.headers("sup1")
        lead = world.headers("ql1")
        officer = world.headers("ro1")

        validate_error(
            api.quality_hold_complaint(
                complaint_id, {"reason": "Not my call."}, agent
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_quality_ops_run(quality_ops_run_payload(dry_run=True), agent),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        # The remedy is DRAFT, yet the role answers before the state does.
        validate_error(
            api.decide_remedy(remedy["id"], decide_payload("APPROVE"), officer),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_response_template(
                response_template_payload("T-NO", "Nope", "Nope."), lead
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        # Well formed in every respect except the caller.
        validate_error(
            api.create_trend_signal(
                trend_signal_payload("PLANT", world["plant"]["id"], **PLANT_WINDOW),
                supervisor,
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_plant(
                plant_payload("P-NEW", "Rogue Plant", "MW"), supervisor
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        # PRD 4: a QualityLead may escalate, so the peer outside the list is the
        # CareSupervisor.
        validate_error(
            api.create_regulatory_report(
                regulatory_report_payload(complaint_id), supervisor
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

        _rows, templates = validate_paginated(api.list_response_templates(supervisor))
        assert templates["total_count"] == 0
        _rows, plants = validate_paginated(api.list_plants(ADMIN))
        assert plants["total_count"] == 1
        _rows, signals = validate_paginated(api.list_trend_signals(lead))
        assert signals["total_count"] == 0
        _rows, reports = validate_paginated(api.list_regulatory_reports(officer))
        assert reports["total_count"] == 0
        untouched = validate_success(api.get_remedy(remedy["id"], agent))
        assert untouched["status"] == "DRAFT"
        assert untouched["version"] == remedy["version"]

    def test_each_rightful_owner_performs_its_own_exclusive_operations(self, api):
        """The same eight calls, made by the roles that own them, all succeed.

        PRD: "The actor's role appears in the endpoint's authorized-role list —
        otherwise `ERR_UNAUTHORIZED` (403). Evaluated before any path identifier
        is resolved."

        Design: Corner/rbac/corner_each_role_performs_its_own_exclusive_operations
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1", "ql1", "ro1"))
        seed_triaged_complaint(
            api,
            world,
            contact_overrides={"channel": "PHONE", "raw_message": "Stale pack."},
            complaint_type="QUALITY",
        )
        complaint_id = world["complaints"]["cp1"]["id"]
        remedy = seed_submitted_remedy(
            api, world, complaint_id, requested_value_cents=1200, author="ag1"
        )
        assert remedy["status"] == "SUBMITTED"
        assert_goodwill_math(remedy, 1200, 0.10, 120, 1320, "TIER_1")
        lead = world.headers("ql1")
        supervisor = world.headers("sup1")
        officer = world.headers("ro1")

        decided = validate_success(
            api.decide_remedy(
                remedy["id"], decide_payload("APPROVE", decision_note="Fine."), supervisor
            )
        )
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_ref"] == world.actor("sup1").id

        held = validate_success(
            api.quality_hold_complaint(
                complaint_id, {"reason": "Quality review."}, lead
            )
        )
        assert held["handling_status"] == "ON_QUALITY_HOLD"
        released = validate_success(
            api.release_complaint_hold(complaint_id, {"reason": "Cleared."}, lead)
        )
        assert released["handling_status"] == "TRIAGED"

        rehearsal = validate_success(
            api.create_quality_ops_run(quality_ops_run_payload(dry_run=True), lead)
        )
        assert rehearsal["run_at"] == CLOCK_EPOCH_MS

        template = validate_success(
            api.create_response_template(
                response_template_payload("T-OK", "Yes", "Yes."), supervisor
            ),
            201,
        )
        assert template["status"] == "DRAFT"

        signal = validate_success(
            api.create_trend_signal(
                trend_signal_payload("PLANT", world["plant"]["id"], **PLANT_WINDOW),
                lead,
            ),
            201,
        )
        assert signal["status"] == "DETECTED"
        assert signal["detection_source"] == "MANUAL"

        second_plant = validate_success(
            api.create_plant(plant_payload("P-NEW", "Second Plant", "NE"), ADMIN), 201
        )
        assert second_plant["plant_code"] == "P-NEW"

        report = validate_success(
            api.create_regulatory_report(
                regulatory_report_payload(complaint_id), officer
            ),
            201,
        )
        assert report["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Segregation of duties
# ---------------------------------------------------------------------------
class TestSegregationOfDuties:
    def test_the_supervisor_who_authored_a_remedy_may_not_approve_it(self, api):
        """Identity, not role or tier, is what disqualifies the author.

        PRD: "Every one of the three decisions requires that the remedy is in
        `SUBMITTED` and that the deciding staff identifier differs from
        `authored_by_ref`; a decider who authored the remedy is refused with
        `ERR_SEGREGATION_OF_DUTIES` regardless of how much authority they hold."

        Design: Corner/rbac/corner_remedy_author_cannot_be_the_decider
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1", "sup3"))
        seed_triaged_complaint(
            api,
            world,
            contact_overrides={"channel": "EMAIL", "raw_message": "Stale pack."},
            complaint_type="QUALITY",
        )
        complaint_id = world["complaints"]["cp1"]["id"]
        remedy = seed_submitted_remedy(
            api, world, complaint_id, requested_value_cents=2000, author="sup1"
        )
        author = world.headers("sup1")
        peer = world.headers("sup3")
        assert remedy["status"] == "SUBMITTED"
        assert remedy["authored_by_ref"] == world.actor("sup1").id
        assert_goodwill_math(remedy, 2000, 0.10, 200, 2200, "TIER_1")

        own = api.decide_remedy(
            remedy["id"],
            decide_payload("APPROVE", decision_note="Approving my own."),
            author,
        )
        validate_error(own, ApiErrorId.SEGREGATION_OF_DUTIES, 409)

        stalled = validate_success(api.get_remedy(remedy["id"], author))
        assert stalled["status"] == "SUBMITTED"
        assert stalled["decided_by_ref"] is None
        before = validate_success(api.get_consumer(world["consumer"]["id"], author))
        assert_goodwill_ledger(before, authorized=0, outstanding=0)

        # Same role, same tier, different person.
        assert world.actor("sup3").role == world.actor("sup1").role
        assert world.actor("sup3").authority_tier == world.actor("sup1").authority_tier
        approved = validate_success(
            api.decide_remedy(
                remedy["id"],
                decide_payload("APPROVE", decision_note="Peer review."),
                peer,
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_ref"] == world.actor("sup3").id
        after = validate_success(api.get_consumer(world["consumer"]["id"], author))
        assert_goodwill_ledger(after, authorized=2200, outstanding=2200, paid=0)

    def test_the_officer_who_determined_a_report_may_not_file_it(self, api):
        """The second pair spans two transitions and bites only once state allows.

        PRD: "The report must be in `DETERMINED_REPORTABLE`, and the submitting
        staff identifier must differ from `determined_by_ref`; the same officer
        may not both determine and file the same report, and the attempt is
        refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/corner_report_determiner_cannot_be_the_submitter
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1", "ro1", "ro2"))
        seed_triaged_complaint(
            api,
            world,
            contact_overrides={
                "channel": "PHONE",
                "raw_message": "Ill after eating, saw a doctor.",
            },
            **ILLNESS_S1_COMPLAINT,
        )
        complaint_id = world["complaints"]["cp1"]["id"]
        assert_severity(world["complaints"]["cp1"], effective_band="S1")
        first_officer = world.headers("ro1")
        second_officer = world.headers("ro2")

        report = find_report(api, world, complaint_id, actor="ro1")
        assert report["status"] == "OPEN"
        determined = determine_report(api, world, report["id"], "REPORTABLE", actor="ro1")
        assert determined["status"] == "DETERMINED_REPORTABLE"
        assert determined["determined_by_ref"] == world.actor("ro1").id
        assert determined["due_at"] == "2026-08-02T00:00:00.000Z"

        same_hand = api.submit_regulatory_report(
            report["id"], submit_report_payload("AG-90001"), first_officer
        )
        validate_error(same_hand, ApiErrorId.SEGREGATION_OF_DUTIES, 409)

        unfiled = validate_success(
            api.get_regulatory_report(report["id"], first_officer)
        )
        assert unfiled["status"] == "DETERMINED_REPORTABLE"
        assert unfiled["submitted_by_ref"] is None
        assert unfiled.get("agency_reference") is None
        assert unfiled.get("submitted_late") is None

        filed = validate_success(
            api.submit_regulatory_report(
                report["id"], submit_report_payload("AG-90002"), second_officer
            )
        )
        assert filed["status"] == "SUBMITTED"
        assert filed["submitted_by_ref"] == world.actor("ro2").id
        assert filed["agency_reference"] == "AG-90002"
        assert filed["submitted_late"] is False

        complaint = validate_success(
            api.get_complaint(complaint_id, world.headers("ag1"))
        )
        assert complaint["regulatory_status"] == "SUBMITTED"


class TestAuthorityCeiling:
    def test_the_ceiling_tracks_the_payout_and_only_bars_approval(self, api):
        """A TIER_1 supervisor may decline any payout but only approve a small one.

        PRD: "`APPROVE` moves it `SUBMITTED → APPROVED`, stamps
        `decided_by_ref`, and additionally requires two things: that the deciding
        staff member's `authority_tier` rank is at least the remedy's
        `authority_tier_required` rank, ranked `TIER_1` below `TIER_2` below
        `TIER_3`, failing which the decision is refused with
        `ERR_AUTHORITY_TIER_INSUFFICIENT`"

        Design: Corner/rbac/corner_authority_tier_ceiling_is_checked_against_the_payout
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1", "sup2"))
        seed_triaged_complaint(
            api,
            world,
            contact_overrides={"channel": "EMAIL", "raw_message": "Stale pack."},
            complaint_type="QUALITY",
        )
        complaint_id = world["complaints"]["cp1"]["id"]
        junior = world.headers("sup2")
        agent = world.headers("ag1")
        assert world.actor("sup2").authority_tier == "TIER_1"

        big = seed_submitted_remedy(
            api, world, complaint_id, "rm1", requested_value_cents=4000, author="ag1"
        )
        assert_goodwill_math(big, 4000, 0.10, 400, 4400, "TIER_2")

        over_reach = api.decide_remedy(
            big["id"],
            decide_payload("APPROVE", decision_note="Over my ceiling."),
            junior,
        )
        validate_error(over_reach, ApiErrorId.AUTHORITY_TIER_INSUFFICIENT, 403)
        stalled = validate_success(api.get_remedy(big["id"], agent))
        assert stalled["status"] == "SUBMITTED"

        # Declining is not authorising spend, so the ceiling does not apply.
        declined = validate_success(
            api.decide_remedy(
                big["id"],
                decide_payload("REJECT", decision_note="Declining instead."),
                junior,
            )
        )
        assert declined["status"] == "REJECTED"
        assert declined["decided_by_ref"] == world.actor("sup2").id

        small = add_remedy(
            api, world, complaint_id, "rm2", requested_value_cents=2000, actor="ag1"
        )
        assert_goodwill_math(small, 2000, 0.10, 200, 2200, "TIER_1")
        submit_remedy(api, world, small["id"], actor="ag1")
        approved = validate_success(
            api.decide_remedy(
                small["id"],
                decide_payload("APPROVE", decision_note="Within my ceiling."),
                junior,
            )
        )
        assert approved["status"] == "APPROVED"

        consumer = validate_success(
            api.get_consumer(world["consumer"]["id"], world.headers("sup1"))
        )
        assert_goodwill_ledger(consumer, authorized=2200, outstanding=2200, paid=0)


# ---------------------------------------------------------------------------
# The self-service role
# ---------------------------------------------------------------------------
class TestConsumerSelfService:
    def test_a_consumer_reads_only_its_own_record_and_writes_nothing(self, api):
        """One permitted read; five refusals, including a peer's record.

        PRD: "The self-service role may read its own consumer record and nothing
        else; an ownership check compares the requested consumer's `id` to
        `X-User-ID` and rejects a mismatch with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/corner_consumer_role_reads_itself_and_writes_nothing
        """
        world = seed_base_world(api, actor_keys=("ag1",))
        neighbour = add_consumer(
            api, world, "c2", external_ref="C-2", full_name="Ola Berg",
            postal_code="60602",
        )
        add_contact(
            api, world, "ct1", channel="WEB", raw_message="Reporting an issue."
        )
        consumer_id = world["consumer"]["id"]
        contact_id = world["contacts"]["ct1"]["id"]
        myself = make_consumer_headers(consumer_id)

        own_record = validate_success(api.get_consumer(consumer_id, myself))
        assert own_record["id"] == consumer_id
        assert own_record["full_name"] == "Rin Sato"
        assert_two_decimal_value(own_record["sentiment_index"], 50.00)

        validate_error(
            api.create_complaint(complaint_payload(contact_id), myself),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_contact(
                contact_payload(
                    consumer_id, channel="WEB", raw_message="Self service."
                ),
                myself,
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        validate_error(
            api.update_consumer(consumer_id, {"postal_code": "99999"}, myself),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        # The analytic projection belongs to CareSupervisor and QualityLead.
        validate_error(
            api.get_consumer_sentiment(consumer_id, myself),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        # The collection would enumerate peers.
        validate_error(api.list_consumers(myself), ApiErrorId.UNAUTHORIZED, 403)
        # And so would a neighbour's record, reached by id.
        validate_error(
            api.get_consumer(neighbour["id"], myself), ApiErrorId.UNAUTHORIZED, 403
        )

        unchanged = validate_success(
            api.get_consumer(consumer_id, world.headers("ag1"))
        )
        assert unchanged["postal_code"] == "60601"
