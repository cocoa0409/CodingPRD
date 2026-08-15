"""Inquiries: initial state, required fields and enums, claim/respond ownership,
the response-time SLA boundary, mark-lost cascade, and list pagination."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_same_instant,
    create_agent,
    create_contacted_inquiry,
    create_floorplan,
    create_guided_tour,
    create_inquiry,
    create_property,
    get_inquiry,
    claim_inquiry,
    get_tour,
    make_leasing_agent_headers,
    respond_inquiry,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["property_manager_headers"]


class TestInquiryCreation:
    def test_inquiry_created_in_initial_state_new(self, api, property_manager_headers):
        """PRD §3.3: "New inquiries arrive `NEW` with `assigned_agent_id` still null."

        Design: Corner/state_machines/inquiry_created_in_initial_state_new
        """
        prop = create_property(name="Init Towers", code="IN1")
        resp = api.create_inquiry(
            {"property_id": prop["id"], "contact_name": "Init",
             "contact_email": "init@x.com", "source": "WALK_IN"},
            property_manager_headers)
        inquiry = validate_success(resp, 201)
        assert inquiry["status"] == "NEW"
        assert inquiry["assigned_agent_id"] is None
        # Computed response fields stay unset until the first response.
        assert inquiry.get("first_responded_at") is None
        assert inquiry.get("response_met_target") is None

    def test_inquiry_missing_required_source_returns_invalid_request(
            self, api, leasing_agent_headers):
        """PRD §3.3: "A `LeasingAgent` or `PropertyManager` creates one with the
        `property_id`, an optional `floorplan_id` naming the floorplan of interest,
        the prospect's `contact_name` and `contact_email`, and the lead `source` —
        one of `WALK_IN`, `PHONE`, `WEB_FORM`, `ILS_LISTING`, or `REFERRAL`."
        PRD §2.10: "malformed payloads — a missing required field, an invalid enum
        member, a negative or otherwise invalid numeric, a malformed datetime, or a
        conditional-field violation such as an `agent_id` attached to a `SELF_GUIDED`
        tour or missing from a `GUIDED` one — fail with `ERR_INVALID_REQUEST`;"

        Design: Corner/entities/inquiry_missing_required_source_returns_invalid_request
        """
        prop = create_property(name="Req Towers", code="RQ1")
        resp = api.create_inquiry(
            {"property_id": prop["id"], "contact_name": "NoSource",
             "contact_email": "ns@x.com"},
            leasing_agent_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        data, meta = validate_paginated(
            api.list_inquiries(PM, params={"property_id": prop["id"]}))
        assert data == [], "a rejected creation must not persist an inquiry"

    def test_inquiry_invalid_source_enum_rejected(self, api, leasing_agent_headers):
        """PRD §2.10: "malformed payloads — a missing required field, an invalid enum
        member, a negative or otherwise invalid numeric, a malformed datetime, or a
        conditional-field violation such as an `agent_id` attached to a `SELF_GUIDED`
        tour or missing from a `GUIDED` one — fail with `ERR_INVALID_REQUEST`;"
        PRD §3.3: "the lead `source` — one of `WALK_IN`, `PHONE`, `WEB_FORM`,
        `ILS_LISTING`, or `REFERRAL`."

        Design: Corner/entities/inquiry_invalid_source_enum_rejected
        """
        prop = create_property(name="Enum Estates", code="EN1")
        resp = api.create_inquiry(
            {"property_id": prop["id"], "contact_name": "BadEnum",
             "contact_email": "be@x.com", "source": "SMOKE_SIGNAL"},
            leasing_agent_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestClaim:
    def test_claim_then_double_claim_rejected(self, api):
        """PRD §3.3: "Claiming assigns the card: `assigned_agent_id` becomes the
        caller's agent id (for a `PropertyManager` caller, their own agent record),
        while the status is unchanged. Only an unassigned inquiry in `NEW`,
        `CONTACTED`, or `TOUR_SCHEDULED` can be claimed; a terminal inquiry or an
        already-assigned one is rejected with `ERR_INQUIRY_INVALID_STATE`."

        Design: Corner/state_machines/claim_then_double_claim_rejected
        """
        prop = create_property(name="Claim Court", code="CL1")
        agent1 = create_agent(prop["id"], full_name="A One", email="a1@x.com")
        agent2 = create_agent(prop["id"], full_name="A Two", email="a2@x.com")
        inquiry = create_inquiry(prop["id"], agent_id=agent1["id"],
                                 contact_name="Cl", contact_email="cl@x.com",
                                 source="PHONE")

        claimed = validate_success(api.claim_inquiry(
            inquiry["id"], make_leasing_agent_headers(agent1["id"])))
        assert claimed["assigned_agent_id"] == agent1["id"]
        assert claimed["status"] == "NEW"

        resp = api.claim_inquiry(inquiry["id"], make_leasing_agent_headers(agent2["id"]))
        validate_error(resp, ApiErrorId.ERR_INQUIRY_INVALID_STATE)
        assert get_inquiry(inquiry["id"])["assigned_agent_id"] == agent1["id"], \
            "the failed claim must not reassign the inquiry"


class TestRespond:
    def test_respond_by_other_agent_returns_forbidden(self, api):
        """PRD §2.1: "Recording a first response or marking an inquiry lost requires
        the caller to be the inquiry's assigned agent or a `PropertyManager`; anyone
        else is rejected with `ERR_NOT_ASSIGNED_AGENT` (HTTP 403)."

        Design: Corner/validations/respond_by_other_agent_returns_forbidden
        """
        prop = create_property(name="Owner Oaks", code="OW1")
        agent1 = create_agent(prop["id"], full_name="O One", email="o1@x.com")
        agent2 = create_agent(prop["id"], full_name="O Two", email="o2@x.com")
        inquiry = create_inquiry(prop["id"], agent_id=agent1["id"],
                                 contact_name="OW", contact_email="ow@x.com",
                                 source="PHONE")
        claim_inquiry(inquiry["id"], agent1["id"])

        resp = api.respond_inquiry(inquiry["id"],
                                   make_leasing_agent_headers(agent2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_AGENT, 403)

        responded = respond_inquiry(inquiry["id"], agent1["id"])
        assert responded["status"] == "CONTACTED"

    def test_respond_twice_returns_already_responded(self, api):
        """PRD §3.3: "Responding is permitted exactly once, from `NEW`: a repeat
        response on an inquiry already `CONTACTED` or further along is rejected with
        `ERR_ALREADY_RESPONDED`, responding on a terminal inquiry or an unassigned
        one is rejected with `ERR_INQUIRY_INVALID_STATE`, and a caller who is neither
        the assigned agent nor a `PropertyManager` is rejected with
        `ERR_NOT_ASSIGNED_AGENT`."
        PRD §3.3: "A successful response stamps `first_responded_at` with the current
        logical time, moves the inquiry to `CONTACTED`, and computes
        `response_met_target`"

        Design: Corner/validations/respond_twice_returns_already_responded
        """
        prop = create_property(name="Twice Terrace", code="TW1")
        agent = create_agent(prop["id"], full_name="TwA", email="twa@x.com")
        inquiry = create_inquiry(prop["id"], agent_id=agent["id"],
                                 contact_name="TW", contact_email="tw@x.com")
        claim_inquiry(inquiry["id"], agent["id"])
        respond_inquiry(inquiry["id"], agent["id"])  # first response at the default clock

        set_clock("2026-08-01T00:30:00Z")
        resp = api.respond_inquiry(inquiry["id"],
                                   make_leasing_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_ALREADY_RESPONDED)
        # The original first-response timestamp is preserved.
        assert_same_instant(get_inquiry(inquiry["id"])["first_responded_at"],
                            "2026-08-01T00:00:00Z", label="first_responded_at")

    def test_response_met_target_inclusive_boundary(self, api):
        """PRD §3.3: "A successful response stamps `first_responded_at` with the
        current logical time, moves the inquiry to `CONTACTED`, and computes
        `response_met_target`: the elapsed whole minutes between the inquiry's
        `created_at` and `first_responded_at`, truncated to whole minutes, is
        compared against the property's `response_time_target_minutes`, and a
        response landing at exactly the target counts as met."

        Design: Corner/calculations/response_met_target_inclusive_boundary
        """
        prop = create_property(name="SLA Springs", code="SL1",
                               response_time_target_minutes=60)
        agent = create_agent(prop["id"], full_name="SlA", email="sla@x.com")
        floorplan = create_floorplan(prop["id"])
        inquiry1 = create_inquiry(prop["id"], agent_id=agent["id"],
                                  floorplan_id=floorplan["id"],
                                  contact_name="OnTime", contact_email="ot@x.com")
        inquiry2 = create_inquiry(prop["id"], agent_id=agent["id"],
                                  floorplan_id=floorplan["id"],
                                  contact_name="Late", contact_email="lt@x.com")
        claim_inquiry(inquiry1["id"], agent["id"])
        claim_inquiry(inquiry2["id"], agent["id"])

        set_clock("2026-08-01T01:00:00Z")  # exactly 60 minutes after creation
        on_time = respond_inquiry(inquiry1["id"], agent["id"])
        assert on_time["response_met_target"] is True
        assert_same_instant(on_time["first_responded_at"], "2026-08-01T01:00:00Z",
                            label="first_responded_at")

        set_clock("2026-08-01T01:01:00Z")  # 61 minutes after creation
        late = respond_inquiry(inquiry2["id"], agent["id"])
        assert late["response_met_target"] is False


class TestMarkLost:
    def test_mark_lost_cascades_tour_cancellation(self, api):
        """PRD §3.3: "The inquiry lands in the terminal `LOST` state, and the loss
        cascades: every `SCHEDULED` tour of the inquiry is cancelled."
        PRD §3.3: "Marking an inquiry lost is permitted from `NEW`, `CONTACTED`, or
        `TOUR_SCHEDULED` — from anywhere else it is `ERR_INQUIRY_INVALID_STATE` — and
        only by the assigned agent or a `PropertyManager` (`ERR_NOT_ASSIGNED_AGENT`)."

        Design: Corner/state_machines/mark_lost_cascades_tour_cancellation
        """
        prop = create_property(name="Lost Lake", code="LL1")
        agent = create_agent(prop["id"], full_name="LA", email="lla@x.com")
        floorplan = create_floorplan(prop["id"])
        inquiry = create_contacted_inquiry(prop["id"], agent["id"],
                                           floorplan_id=floorplan["id"],
                                           contact_name="LL", contact_email="ll@x.com",
                                           source="ILS_LISTING")
        tour = create_guided_tour(inquiry["id"], agent["id"],
                                  "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")

        resp = api.mark_inquiry_lost(inquiry["id"],
                                     make_leasing_agent_headers(agent["id"]))
        assert validate_success(resp)["status"] == "LOST"
        assert get_tour(tour["id"])["status"] == "CANCELLED", \
            "mark-lost cascades to the inquiry's still-SCHEDULED tours"


class TestInquiryListing:
    def test_inquiries_list_paginates_with_envelope_fields(self, api,
                                                           property_manager_headers):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; when omitted it defaults to 10, and it accepts values from a
        minimum of 1 to a maximum of 100. The `offset` parameter sets the number of
        items skipped and defaults to 0."
        PRD §2.3: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`, `total_count`,
        and `has_more`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/endpoints/inquiries_list_paginates_with_envelope_fields
        """
        prop = create_property(name="Page Place", code="PG1")
        for i in range(3):
            create_inquiry(prop["id"], contact_name=f"P{i + 1}",
                           contact_email=f"pg{i + 1}@x.com",
                           source=["WEB_FORM", "PHONE", "WALK_IN"][i])

        page1, meta1 = validate_paginated(api.list_inquiries(
            property_manager_headers,
            params={"property_id": prop["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_inquiries(
            property_manager_headers,
            params={"property_id": prop["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        # Defaults apply when the parameters are omitted.
        default_page, default_meta = validate_paginated(api.list_inquiries(
            property_manager_headers, params={"property_id": prop["id"]}))
        assert default_meta["limit"] == 10
        assert len(default_page) == 3
