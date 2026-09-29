"""Who may call what, and whose records they may touch once they are through the door."""

from test_helpers import (
    AUDITOR,
    AUDITOR_1_ID,
    AUDITOR_2,
    CHAIR,
    CHAIR_2,
    NO_HEADERS,
    OFFICER,
    UNKNOWN_ROLE_HEADER,
    api_errors as E,
    assert_node_position,
    assert_pct,
    assert_score,
    assert_volume,
    factories as f,
    make_brand_licensee_headers,
    make_producer_representative_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_HOLDER_ID = "00000000-0000-4000-8000-000000000021"


class TestEndpointRoleAuthorization:
    """Two endpoints reserved for a single role, called by the wrong one."""

    def test_a_producer_cannot_grant_itself_certification(self, api, clock):
        """Granting certification belongs to certification staff alone, and the refused
        application is left exactly where it was.

        Design: Corner/rbac/producer_representative_cannot_certify_a_holder_returns_403
        """
        holder = f.register_holder(api)
        producer_headers = make_producer_representative_headers(holder["id"])

        response = api.certify_holder(holder["id"], producer_headers)

        validate_error(response, E.ERR_UNAUTHORIZED, 403)
        after = f.read_holder(api, holder["id"])
        assert after["certificate_status"] == "PENDING"
        assert after["certified_at"] is None
        assert after["version"] == holder["version"], "a refused certify writes nothing"

    def test_a_chair_cannot_slip_a_ballot_into_the_round_it_opened(self, api, clock):
        """Only elected members cast ballots, so the chair's own vote never reaches the
        tally and the round stands untouched.

        Design: Corner/rbac/committee_chair_cannot_cast_a_ballot_returns_403
        """
        chain = f.build_funded_committee(api)
        proposal = f.draft_proposal(api, chain, 500000)
        validate_success(api.open_vote(proposal["id"], CHAIR), 200)

        response = api.cast_vote(
            proposal["id"], f.vote_payload("APPROVE", "My own proposal"), CHAIR
        )

        validate_error(response, E.ERR_UNAUTHORIZED, 403)
        rows, meta = validate_paginated(api.list_proposal_votes(proposal["id"], OFFICER))
        assert meta["total_count"] == 0 and rows == []
        after = f.read_proposal(api, proposal["id"])
        assert after["status"] == "UNDER_VOTE"
        assert_pct(after["turnout_pct"], "0.00", "turnout_pct")
        assert_pct(after["approval_pct"], "0.00", "approval_pct")


class TestHeadersBeforeEverythingElse:
    """The identity check runs before the service even looks for the target row."""

    def test_a_call_with_no_identity_headers_is_refused_before_the_lookup(self, api, clock):
        """Suspending a holder that does not exist is answered as an authentication failure
        while the headers are missing, and only becomes a not-found once they are valid;
        a role outside the recognized six is treated as no identity at all.

        Design: Corner/rbac/header_missing_x_user_role_returns_401_before_any_other_check
        """
        anonymous = api.suspend_holder(UNKNOWN_HOLDER_ID, {}, NO_HEADERS)
        validate_error(anonymous, E.ERR_UNAUTHENTICATED, 401)

        identified = api.suspend_holder(
            UNKNOWN_HOLDER_ID, f.reason_payload("MANUAL"), OFFICER
        )
        validate_error(identified, E.ERR_HOLDER_NOT_FOUND, 404)

        unknown_role = api.suspend_holder(
            UNKNOWN_HOLDER_ID, f.reason_payload("MANUAL"), UNKNOWN_ROLE_HEADER
        )
        validate_error(unknown_role, E.ERR_UNAUTHENTICATED, 401)


class TestOwnershipOfTheActingHolder:
    """An entity-backed role may only act on the holder its identity names."""

    def test_a_producer_cannot_book_a_harvest_into_a_neighbours_node(self, api, clock):
        """A second cooperative's representative is refused at both the harvest declaration
        and the node registration, and the same declaration signed by the owner lands.

        Design: Corner/rbac/producer_cannot_declare_harvest_on_another_holders_node
        """
        first = f.build_certified_producer(api, legal_name="Kilimo Coop")
        second = f.build_certified_producer(api, legal_name="Bahati Coop")
        stranger = make_producer_representative_headers(second["holder_id"])

        trespass = api.declare_harvest(first["node_id"], f.harvest_payload(50000), stranger)

        validate_error(trespass, E.ERR_HOLDER_OWNERSHIP_MISMATCH, 403)
        untouched = f.read_node(api, first["node_id"])
        assert_node_position(
            untouched, certified_input_kg="0.000", available_credit_kg="0.000"
        )
        assert untouched["version"] == first["node_version"]

        borrowed_holder = api.create_node(f.node_payload(first["holder_id"]), stranger)
        validate_error(borrowed_holder, E.ERR_HOLDER_OWNERSHIP_MISMATCH, 403)
        rows, meta = validate_paginated(
            api.list_nodes(OFFICER, {"holder_id": first["holder_id"]})
        )
        assert meta["total_count"] == 1 and [row["id"] for row in rows] == [first["node_id"]]

        validate_success(
            api.declare_harvest(
                first["node_id"], f.harvest_payload(50000), first["holder_headers"]
            ),
            201,
        )
        assert_volume(
            f.read_node(api, first["node_id"])["certified_input_kg"],
            "50000.000",
            "certified_input_kg",
        )


class TestChairAndAuditorBinding:
    """A chair is bound to its own committee and an auditor to findings it did not write."""

    def test_a_chair_cannot_spend_another_committees_premium(self, api, clock):
        """The proposal is refused because the acting chair is not the one this committee
        elected, and nothing about the committee or its fund moves.

        Design: Corner/rbac/chair_cannot_propose_on_a_committee_it_does_not_chair
        """
        producer = f.build_certified_producer(api)
        committee = f.constitute_committee(api, producer["holder_id"])
        fund = f.read_fund(api, producer["holder_id"])

        response = api.create_proposal(
            f.proposal_payload(
                committee["id"], fund["version"], 100000, title="Clinic beds",
                use_period_start="2026-09-01", use_period_end="2026-12-01",
            ),
            CHAIR_2,
        )

        validate_error(response, E.ERR_HOLDER_OWNERSHIP_MISMATCH, 403)
        rows, meta = validate_paginated(
            api.list_committee_proposals(committee["id"], OFFICER)
        )
        assert meta["total_count"] == 0 and rows == []
        assert f.read_committee(api, committee["id"])["open_proposal_count"] == 0
        assert f.read_fund(api, producer["holder_id"])["version"] == fund["version"]

    def test_the_auditor_who_wrote_the_finding_cannot_bless_its_own_fix(self, api, clock):
        """A second auditor is needed to accept the plan; once one does, the finding closes
        and the producer's record is clean again, with the original author still recorded.

        Design: Corner/rbac/auditor_cannot_review_the_corrective_action_it_raised
        """
        producer = f.build_certified_producer(api)
        audit = f.build_started_audit(api, producer["holder_id"])
        finding = f.raise_finding(api, audit["id"], "MAJOR")
        validate_success(
            api.submit_cap(finding["id"], f.cap_payload(), producer["holder_headers"]), 201
        )
        submitted = f.read_nonconformity(api, finding["id"])
        assert submitted["status"] == "CAP_SUBMITTED"

        self_review = api.review_cap(
            finding["id"], f.cap_review_payload("ACCEPT", "Self review"), AUDITOR
        )

        validate_error(self_review, E.ERR_SEGREGATION_OF_DUTIES, 403)
        after = f.read_nonconformity(api, finding["id"])
        assert after["status"] == "CAP_SUBMITTED"
        assert after["closed_at"] is None
        assert after["version"] == submitted["version"]

        closed = validate_success(
            api.review_cap(
                finding["id"], f.cap_review_payload("ACCEPT", "Independent review"), AUDITOR_2
            ),
            200,
        )
        assert closed["status"] == "CLOSED"
        assert closed["raised_by_user_id"] == AUDITOR_1_ID
        holder = f.read_holder(api, producer["holder_id"])
        assert holder["open_major_count"] == 0
        assert_score(holder["compliance_score"], 100)


class TestTheEndpointsBothEntityBackedRolesShare:
    """Node registration and volume report filing are open to producers and brands alike."""

    def test_a_producer_and_a_brand_each_map_a_node_and_file_a_report(self, api, clock):
        """Each side registers its own node and files its own period declaration, and the
        brand's mass-balance node is accepted directly downstream of the physical one.

        Design: Corner/rbac/both_entity_backed_roles_may_use_the_shared_node_and_report_endpoints
        """
        chain = f.build_certified_chain(api, harvest_kg=None)
        producer_headers = make_producer_representative_headers(chain["producer_id"])
        brand_headers = make_brand_licensee_headers(chain["brand_id"])

        seller_node = validate_success(
            api.create_node(
                f.node_payload(chain["producer_id"], node_role="COOPERATIVE"), producer_headers
            ),
            201,
        )
        buyer_node = validate_success(
            api.create_node(
                f.node_payload(
                    chain["brand_id"], node_role="BRAND_NODE",
                    traceability_mode="MASS_BALANCE", upstream_node_id=seller_node["id"],
                ),
                brand_headers,
            ),
            201,
        )

        assert seller_node["status"] == "ACTIVE" and buyer_node["status"] == "ACTIVE"
        assert buyer_node["traceability_mode"] == "MASS_BALANCE"
        assert buyer_node["upstream_node_id"] == seller_node["id"]

        seller_report = f.file_volume_report(
            api, chain["producer_id"], chain["brand_id"], "2026-08-01", "2026-09-01", 0,
            headers=producer_headers,
        )
        buyer_report = f.file_volume_report(
            api, chain["brand_id"], chain["producer_id"], "2026-08-01", "2026-09-01", 0,
            headers=brand_headers,
        )

        assert seller_report["reconciliation_status"] == "SUBMITTED"
        assert buyer_report["reconciliation_status"] == "SUBMITTED"
        assert seller_report["holder_id"] == chain["producer_id"]
        assert buyer_report["holder_id"] == chain["brand_id"]
