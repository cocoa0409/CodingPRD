"""Compliance paperwork: health papers, brand inspections, SoD, verification.

Covers PRD §3.4: attachment, verification check chains (PENDING state, load
state, segregation of duties, content match, expiry/freshness), rejection, and
the PLANNED -> PAPERWORK_VERIFIED gate.
"""
from test_helpers import (
    TEST_USERS,
    create_brand_inspection_payload,
    create_health_paper_payload,
    make_compliance_headers,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId as E
from test_helpers.fixtures import (
    CO1,
    CO2,
    set_clock,
    setup_planned_load,
)


class TestHealthPaperVerification:
    def test_verify_expired_health_paper_rejected(self, api):
        """PRD §3.4: "and `expires_at` is strictly later than the load's
        `planned_departure_at` (`ERR_PAPER_EXPIRED`, HTTP 422)."

        Design: Corner/validations/verify_expired_health_paper_rejected
        """
        ctx = setup_planned_load()
        hp = validate_success(
            api.create_health_paper(
                ctx["load"]["id"],
                create_health_paper_payload(
                    issued_at="2026-07-01T00:00:00Z",
                    expires_at="2026-08-01T00:00:00Z"),
                CO1), 201)
        resp = api.verify_health_paper(hp["id"], CO2)
        validate_error(resp, E.ERR_PAPER_EXPIRED)

        # unchanged
        papers = api.list_health_papers(ctx["load"]["id"], CO1).json()["data"]
        assert papers[0]["status"] == "PENDING"

    def test_verify_species_mismatched_paper_rejected(self, api):
        """PRD §3.4: "the paper's `species` equals the load's `species` and
        `head_count_listed` equals `declared_head_count` (`ERR_PAPER_MISMATCH`,
        HTTP 422)"

        Design: Corner/validations/verify_species_mismatched_paper_rejected
        """
        ctx = setup_planned_load()
        hp = validate_success(
            api.create_health_paper(
                ctx["load"]["id"],
                create_health_paper_payload(species="SWINE"),
                CO1), 201)
        resp = api.verify_health_paper(hp["id"], CO2)
        validate_error(resp, E.ERR_PAPER_MISMATCH)

    def test_verify_head_count_mismatched_paper_rejected(self, api):
        """PRD §3.4: "the paper's `species` equals the load's `species` and
        `head_count_listed` equals `declared_head_count` (`ERR_PAPER_MISMATCH`,
        HTTP 422)"

        Design: Corner/validations/verify_head_count_mismatched_paper_rejected
        """
        ctx = setup_planned_load()
        hp = validate_success(
            api.create_health_paper(
                ctx["load"]["id"],
                create_health_paper_payload(head_count_listed=39),
                CO1), 201)
        resp = api.verify_health_paper(hp["id"], CO2)
        validate_error(resp, E.ERR_PAPER_MISMATCH)

    def test_verify_health_paper_twice_rejected(self, api):
        """PRD §3.4: "A `ComplianceOfficer` verifies a paper through a chain of
        checks in fixed order — the paper is `PENDING`
        (`ERR_PAPERWORK_NOT_PENDING`, HTTP 409)"
        PRD §3.4: "Both `VERIFIED` and `REJECTED` are terminal."

        Design: Corner/state_machines/verify_health_paper_twice_rejected
        """
        ctx = setup_planned_load()
        hp = validate_success(
            api.create_health_paper(ctx["load"]["id"],
                                    create_health_paper_payload(), CO1), 201)
        validate_success(api.verify_health_paper(hp["id"], CO2), 200)

        # a third officer re-attempting verification
        resp = api.verify_health_paper(hp["id"], make_compliance_headers("co-3"))
        validate_error(resp, E.ERR_PAPERWORK_NOT_PENDING)

        papers = api.list_health_papers(ctx["load"]["id"], CO1).json()["data"]
        assert papers[0]["status"] == "VERIFIED"
        assert papers[0]["verified_by_user_id"] == "co-2"


class TestSegregationOfDuties:
    def test_verify_own_paper_sod_violation(self, api):
        """PRD §3.4: "Verification enforces segregation of duties: the verifier
        must not be the uploader."
        PRD §3.4: "the verifier's `X-User-ID` differs from `created_by_user_id`
        (`ERR_SOD_VIOLATION`, HTTP 403)"
        PRD §3.4: "A verified paper records `verified_by_user_id` from the
        verifier's `X-User-ID`, moves to `VERIFIED`, and increments its
        `version`."

        Design: Corner/validations/verify_own_paper_sod_violation
        """
        ctx = setup_planned_load()
        hp = validate_success(
            api.create_health_paper(ctx["load"]["id"],
                                    create_health_paper_payload(), CO1), 201)

        # the uploader cannot verify their own paper
        resp = api.verify_health_paper(hp["id"], CO1)
        validate_error(resp, E.ERR_SOD_VIOLATION)

        # a different officer can
        verified = validate_success(api.verify_health_paper(hp["id"], CO2), 200)
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "co-2"


class TestBrandInspectionVerification:
    def test_verify_stale_brand_inspection_rejected(self, api):
        """PRD §3.4: "and the inspection is fresh — `inspected_at` is at or
        before the current time and the span from `inspected_at` to the load's
        `planned_departure_at` does not exceed 96 hours
        (`ERR_BRAND_INSPECTION_STALE`, HTTP 422)."

        Design: Corner/validations/verify_stale_brand_inspection_rejected
        """
        set_clock("2026-08-01T07:00:00Z")
        ctx = setup_planned_load()
        bi = validate_success(
            api.create_brand_inspection(
                ctx["load"]["id"],
                create_brand_inspection_payload(
                    inspected_at="2026-07-25T06:30:00Z"),
                CO1), 201)
        resp = api.verify_brand_inspection(bi["id"], CO2)
        validate_error(resp, E.ERR_BRAND_INSPECTION_STALE)


class TestVerifyPaperworkGate:
    def test_verify_paperwork_without_brand_rejected(self, api):
        """PRD §3.4: "The transition requires at least one `VERIFIED` health
        paper for the load whose `expires_at` is later than
        `planned_departure_at`, and at least one `VERIFIED` brand inspection
        for the load; a shortfall in either is rejected with
        `ERR_PAPERWORK_INCOMPLETE` (HTTP 422)."

        Design: Corner/validations/verify_paperwork_without_brand_rejected
        """
        ctx = setup_planned_load()
        hp = validate_success(
            api.create_health_paper(ctx["load"]["id"],
                                    create_health_paper_payload(), CO1), 201)
        validate_success(api.verify_health_paper(hp["id"], CO2), 200)

        resp = api.verify_paperwork(ctx["load"]["id"], CO2)
        validate_error(resp, E.ERR_PAPERWORK_INCOMPLETE)

        load = validate_success(
            api.get_load(ctx["load"]["id"], TEST_USERS["admin_headers"]))
        assert load["status"] == "PLANNED"
