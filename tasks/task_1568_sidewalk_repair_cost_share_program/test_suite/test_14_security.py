"""Authentication, role authorization, entity-backed identity, and
segregation-of-duties gates."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    make_contractor,
    make_contractor_headers,
    make_cycle,
    make_owner,
    make_owner_headers,
    make_parcel,
    set_clock,
    setup_bid,
    setup_delinquent_notice,
    setup_issued_notice,
    setup_sealed_batch,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
COORD2 = TEST_USERS["coordinator2_headers"]
INSP1 = TEST_USERS["inspector_headers"]
INSP2 = TEST_USERS["inspector2_headers"]
FORESTRY = TEST_USERS["forestry_headers"]
FINANCE = TEST_USERS["finance_headers"]
HEARING = TEST_USERS["hearing_headers"]


class TestAuthentication:
    def test_missing_or_unknown_role_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role value
        outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP
        401)."

        Design: Corner/validations/request_with_unknown_role_unauthenticated
        """
        owner = make_owner("Zed Zelkova", "76 Zelkova St")
        parcel = make_parcel_for(owner)

        resp = api.get_parcel(parcel["id"], headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

        resp = api.get_parcel(parcel["id"],
                              headers=build_user_headers("someone",
                                                         "Anonymous"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_entity_backed_header_must_reference_entity(self, api):
        """PRD §2.1: "When `X-User-Role` is `PropertyOwner`, `X-User-ID` is the
        `id` of the acting `PropertyOwner`; ownership checks on any resource
        that resolves through a parcel chain compare the parcel's `owner_id` to
        `X-User-ID`, and an `X-User-ID` that does not reference an existing
        `PropertyOwner` fails as `ERR_PROPERTY_OWNER_NOT_FOUND`."
        PRD §2.1: "When `X-User-Role` is `Contractor`, `X-User-ID` is the `id`
        of the acting `Contractor`; ownership checks on bids and awarded work
        compare the relevant `contractor_id` to `X-User-ID`, and an unknown
        contractor identifier fails as `ERR_CONTRACTOR_NOT_FOUND`."

        Design: Corner/errors/entity_backed_header_not_found
        """
        resp = api.list_parcels(make_owner_headers(NON_EXISTENT_UUID))
        validate_error(resp, ApiErrorId.ERR_PROPERTY_OWNER_NOT_FOUND)

        resp = api.list_contractors(make_contractor_headers(NON_EXISTENT_UUID))
        validate_error(resp, ApiErrorId.ERR_CONTRACTOR_NOT_FOUND)


def make_parcel_for(owner):
    return make_parcel(owner["id"], "P-V1", "76 Zelkova St", "LOCAL")


class TestRoleAuthorization:
    def test_exclusive_ops_denied_for_other_roles(self, api):
        """PRD §2.1: "A request whose authenticated role is not listed among
        the roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/rbac_exclusive_ops_denied_for_other_roles
        """
        owner = make_owner("Dee Dock", "111 Dock St")
        contractor = make_contractor("Acme Paving", "L-001", "2026-12-31")
        batch = api.create_bid_batch(
            {"neighborhood_code": "NB-R1", "work_window_start": "2026-09-25",
             "work_window_end": "2026-10-15",
             "bid_deadline": "2026-09-22T00:00:00Z"}, COORD)
        batch_v = validate_success(batch, 201)["version"]

        resp = api.create_program_cycle(
            {"cycle_year": 2027, "window_start_date": "2027-01-01",
             "window_end_date": "2027-12-31", "appropriation_cents": 1000000},
            make_owner_headers(owner["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        resp = api.create_defect(
            {"segment_id": NON_EXISTENT_UUID, "defect_type": "SPALLING",
             "area_sqft": 10}, make_contractor_headers(contractor["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        resp = api.create_bid(
            {"batch_id": NON_EXISTENT_UUID, "unit_rate_cents": 900,
             "ramp_flat_fee_cents": 0, "expected_batch_version": batch_v},
            COORD)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        resp = api.obligate_application(NON_EXISTENT_UUID, FORESTRY)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        resp = api.decide_appeal(NON_EXISTENT_UUID, {"decision": "UPHELD"},
                                 FINANCE)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        resp = api.create_lien_case(
            {"notice_id": NON_EXISTENT_UUID, "actual_repair_cost_cents": 1000},
            HEARING)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        resp = api.set_clock("2026-08-02T00:00:00Z", INSP1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_shared_get_cycle_all_roles(self, api):
        """PRD §2.1: "Read endpoints are shared across all seven roles."

        Design: Corner/rbac/rbac_shared_get_cycle_all_roles
        """
        cycle = make_cycle(appropriation_cents=1000000)
        owner = make_owner("Eli Eel", "112 Eel St")
        contractor = make_contractor("Acme Paving", "L-001", "2026-12-31")

        for headers in (COORD, INSP1, make_owner_headers(owner["id"]),
                        make_contractor_headers(contractor["id"]), FORESTRY,
                        FINANCE, HEARING):
            data = validate_success(api.get_program_cycle(cycle["id"],
                                                          headers))
            assert data["status"] == "OPEN"


class TestSegregationOfDuties:
    def test_appeal_decider_must_differ_from_issuer(self, api):
        """PRD §3.4: "requiring the decider's `X-User-ID` to differ from the
        `issued_by_user_id` of the notice (else `ERR_SEGREGATION_OF_DUTIES`)"
        PRD §3.4: "Both branches stamp `appeal_decided_by_user_id` with the
        decider's identifier and `appeal_decided_at` from the logical clock"

        Design: Corner/rbac/segregation_appeal_decider_is_issuer
        """
        bundle = setup_issued_notice(parcel_number="P-RB1",
                                     segment_code="S-RB1-1",
                                     owner_name="Fay Fern",
                                     street_address="113 Fern St")
        notice = bundle["notice"]
        assert notice["issued_by_user_id"] == "coord-1"
        validate_success(api.appeal_repair_notice(
            notice["id"], {"grounds": "dispute"},
            make_owner_headers(bundle["owner"]["id"])))

        # A hearing-officer call carrying the issuer's operator id conflicts.
        resp = api.decide_appeal(notice["id"], {"decision": "UPHELD"},
                                 build_user_headers("coord-1",
                                                    "HearingOfficer"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        decided = validate_success(api.decide_appeal(
            notice["id"], {"decision": "UPHELD"}, HEARING))
        assert decided["status"] == "ISSUED"
        assert decided["appeal_status"] == "UPHELD"
        assert decided["appeal_decided_by_user_id"] == "hear-1"

    def test_inspection_by_defect_recorder_rejected(self, api):
        """PRD §3.3: "the inspecting officer's `X-User-ID` must differ from the
        `recorded_by_inspector_id` of every covered defect (else
        `ERR_SEGREGATION_OF_DUTIES`)"
        PRD §3.2: "The server stamps `recorded_by_inspector_id` with the acting
        inspector's `X-User-ID`"

        Design: Corner/rbac/segregation_inspection_by_defect_recorder
        """
        bundle = setup_issued_notice(parcel_number="P-RB2",
                                     segment_code="S-RB2-1",
                                     owner_name="Gus Gale",
                                     street_address="114 Gale St")
        assert bundle["defect"]["recorded_by_inspector_id"] == "insp-1"

        resp = api.create_inspection(bundle["notice"]["id"],
                                     {"result": "PASS"}, INSP1)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        validate_success(api.create_inspection(bundle["notice"]["id"],
                                               {"result": "PASS"}, INSP2), 201)
        notice = validate_success(
            api.get_repair_notice(bundle["notice"]["id"], COORD))
        assert notice["status"] == "COMPLIANT"

    def test_verify_by_defect_recorder_rejected(self, api):
        """PRD §3.7: "an `Inspector` verifies each completed item —
        `WORK_COMPLETED → VERIFIED` — subject to the same segregation rule as
        compliance inspections, so the verifier's `X-User-ID` must differ from
        the `recorded_by_inspector_id` of every defect on the item's notice
        (else `ERR_SEGREGATION_OF_DUTIES`)"
        PRD §3.7: "when every item of a notice is verified, that notice moves
        from `CITY_REPAIR_SCHEDULED` to `CITY_REPAIR_COMPLETED`; and when every
        item of the batch is verified, the batch itself moves from
        `WORK_IN_PROGRESS` to `COMPLETED`"

        Design: Corner/rbac/segregation_verify_by_defect_recorder
        """
        bundle = setup_delinquent_notice(
            sweep_clock="2026-09-20T00:00:00Z", parcel_number="P-RB3",
            segment_code="S-RB3-1", owner_name="Her Heath",
            street_address="115 Heath St", defect_type="VERTICAL_SEPARATION",
            measured_offset_inches=0.75, area_sqft=50)
        setup_sealed_batch(bundle, "NB-RB3", "2026-09-21", "2026-10-05",
                           "2026-09-21T00:00:00Z")
        setup_bid(bundle, unit_rate_cents=1100)
        set_clock("2026-09-22T00:00:00Z")
        validate_success(api.award_bid_batch(bundle["batch"]["id"], COORD))
        validate_success(api.start_batch_work(bundle["batch"]["id"], COORD))
        item = validate_success(api.complete_work_item(
            bundle["item"]["id"],
            make_contractor_headers(bundle["contractor"]["id"])))
        assert item["status"] == "WORK_COMPLETED"

        resp = api.verify_work_item(item["id"], INSP1)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        item = validate_success(api.verify_work_item(item["id"], INSP2))
        assert item["status"] == "VERIFIED"
        notice = validate_success(
            api.get_repair_notice(bundle["notice"]["id"], COORD))
        assert notice["status"] == "CITY_REPAIR_COMPLETED"
        batch = validate_success(api.get_bid_batch(bundle["batch"]["id"],
                                                   COORD))
        assert batch["status"] == "COMPLETED"
