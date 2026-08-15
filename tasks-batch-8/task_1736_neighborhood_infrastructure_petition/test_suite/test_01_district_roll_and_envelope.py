"""District stand-up, property roll, response envelope, pagination, and
resource retrieval (PRD §2.1–§2.5, §2.8, §2.10, §3.1)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_district,
    assert_parcel,
    create_district,
    create_owner,
    create_parcel,
    create_district_payload,
    create_owner_payload,
    create_parcel_payload,
    get_district,
    open_petition,
    validate_error,
    validate_paginated,
    validate_success,
)

CLERK = TEST_USERS["clerk_headers"]
ADMIN = TEST_USERS["admin_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestDistrictCreation:
    def test_district_creation_applies_defaults(self, api):
        """PRD §3.1: "Three numeric and two seasonal parameters complete the
        profile: `annual_interest_rate_bp` carries the installment interest
        rate in basis points, defaulting to 400 when omitted and bounded
        inclusively between 0 and 2000". PRD §3.1: "A new district begins in
        `DRAFT`: `remand_count` starts at zero, the derived roll totals
        `total_frontage_ft` and `eligible_parcel_count` start at zero, ...
        `approved_change_total_cents`, `paid_assessment_count`, and
        `total_assessment_count` start at zero, and `overrun_flag` and
        `all_assessments_paid` start false."

        Design: Corner/entities/e_district_creation_defaults
        """
        data = validate_success(
            api.create_district(
                create_district_payload(name="ENT-DEFAULT", methodology="FRONT_FOOT",
                                        interest_method="SIMPLE"),
                CLERK,
            ),
            expected_status=201,
        )
        assert_district(data)
        assert data["status"] == "DRAFT"
        assert data["annual_interest_rate_bp"] == 400, "default 400 bp must apply"
        assert data["remand_count"] == 0
        assert data["total_frontage_ft"] == 0
        assert data["eligible_parcel_count"] == 0
        assert data["overrun_flag"] is False
        assert data["all_assessments_paid"] is False

    def test_district_missing_methodology_rejected(self, api):
        """PRD §2.8: "**Request shape** (HTTP 400, `ERR_INVALID_REQUEST`):
        required fields present, types correct, enum members valid".

        Design: Corner/entities/e_district_missing_methodology_returns_invalid_request
        """
        payload = {
            "name": "X",
            "interest_method": "SIMPLE",
            "season_start_mmdd": "03-01",
            "season_end_mmdd": "11-30",
        }
        validate_error(
            api.create_district(payload, CLERK),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

    def test_district_invalid_methodology_enum_rejected(self, api):
        """PRD §2.8: "**Request shape** (HTTP 400, `ERR_INVALID_REQUEST`):
        required fields present, types correct, enum members valid".

        Design: Corner/entities/e_district_invalid_enum_returns_invalid_request
        """
        payload = {
            "name": "X",
            "methodology": "BY_VALUE",
            "interest_method": "SIMPLE",
            "season_start_mmdd": "03-01",
            "season_end_mmdd": "11-30",
        }
        validate_error(
            api.create_district(payload, CLERK),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

    def test_district_not_found_returns_404(self, api):
        """PRD §2.8: "**Existence** (HTTP 404): identifiers are validated left
        to right — path identifiers first, then body foreign keys in their
        declared input order. Each resource type has its own error:
        `ERR_DISTRICT_NOT_FOUND`".

        Design: Corner/entities/e_district_not_found_returns_404
        """
        validate_error(
            api.get_district(NON_EXISTENT_UUID, CLERK),
            ApiErrorId.ERR_DISTRICT_NOT_FOUND,
        )


class TestOwnerAndParcelRoll:
    def test_owner_duplicate_email_rejected(self, api):
        """PRD §3.1: "the email is globally unique, and a second registration
        under an existing address of record is refused with
        `ERR_DUPLICATE_OWNER_EMAIL`."

        Design: Corner/entities/e_owner_duplicate_email_rejected
        """
        first = create_owner_payload(full_name="First", email="ent-dup@x.test",
                                     mailing_address="1 A St")
        validate_success(api.create_owner(first, CLERK), expected_status=201)
        second = create_owner_payload(full_name="Second", email="ent-dup@x.test",
                                      mailing_address="2 A St")
        validate_error(
            api.create_owner(second, CLERK),
            ApiErrorId.ERR_DUPLICATE_OWNER_EMAIL,
        )

    def test_parcel_frontage_zero_boundary(self, api):
        """PRD §3.1: "a strictly positive `frontage_ft` measured to two decimal
        places". PRD §2.8: "scalar ranges enforced — `frontage_ft` strictly
        positive".

        Design: Corner/entities/e_parcel_frontage_zero_boundary
        """
        district = create_district(name="ENT-F")
        owner = create_owner(full_name="Owner ef1", email="ef-o1@x.test")
        bad = create_parcel_payload(district_id=district["id"], owner_id=owner["id"],
                                    parcel_number="P-001", frontage_ft=0.0)
        validate_error(api.create_parcel(bad, CLERK), ApiErrorId.ERR_INVALID_REQUEST)
        good = create_parcel_payload(district_id=district["id"], owner_id=owner["id"],
                                     parcel_number="P-001", frontage_ft=0.01)
        data = validate_success(api.create_parcel(good, CLERK), expected_status=201)
        assert data["frontage_ft"] == pytest.approx(0.01)

    def test_parcel_number_uniqueness_scoped_to_district(self, api):
        """PRD §3.1: "an assessor `parcel_number` unique within its district
        (`ERR_DUPLICATE_PARCEL_NUMBER`)". PRD §2.8: "**Uniqueness and resource
        conflicts** (HTTP 409): `ERR_DUPLICATE_PARCEL_NUMBER`".

        Design: Corner/entities/e_parcel_number_scoped_uniqueness
        """
        d_a = create_district(name="EN-A")
        o_a = create_owner(full_name="Owner ena1", email="ena-o1@x.test")
        create_parcel(d_a["id"], o_a["id"], parcel_number="P-001", frontage_ft=50.0)
        d_b = create_district(name="EN-B")
        o_b = create_owner(full_name="Owner enb1", email="enb-o1@x.test")

        dup = create_parcel_payload(district_id=d_a["id"], owner_id=o_a["id"],
                                    parcel_number="P-001", frontage_ft=60.0)
        validate_error(api.create_parcel(dup, CLERK),
                       ApiErrorId.ERR_DUPLICATE_PARCEL_NUMBER)

        ok = create_parcel_payload(district_id=d_b["id"], owner_id=o_b["id"],
                                   parcel_number="P-001", frontage_ft=60.0)
        data = validate_success(api.create_parcel(ok, CLERK), expected_status=201)
        assert_parcel(data)

    def test_parcel_fk_existence_validated_left_to_right(self, api):
        """PRD §2.8: "**Existence** (HTTP 404): identifiers are validated left
        to right — path identifiers first, then body foreign keys in their
        declared input order. ... A request aimed at a missing parent therefore
        reports the parent's absence before any child identifier is examined."

        Design: Corner/entities/e_parcel_fk_existence_left_to_right
        """
        payload = create_parcel_payload(
            district_id=NON_EXISTENT_UUID,
            owner_id=NON_EXISTENT_UUID,
            parcel_number="P-001",
            frontage_ft=10.0,
        )
        validate_error(api.create_parcel(payload, CLERK),
                       ApiErrorId.ERR_DISTRICT_NOT_FOUND)

    def test_reverse_lists_return_children(self, api):
        """PRD §2.3: "Three documented exceptions exist: parcel listings and
        parcel-assessment listings order by `parcel_number` ascending". PRD §4:
        "GET `/owners/{id}/parcels` | List parcels owned by an owner".

        Design: Corner/entities/e_fk_reverse_lists
        """
        district = create_district(name="ENT-R")
        o1 = create_owner(full_name="Owner er1", email="er-o1@x.test")
        o2 = create_owner(full_name="Owner er2", email="er-o2@x.test")
        create_parcel(district["id"], o1["id"], parcel_number="P-001", frontage_ft=50.0)
        p2 = create_parcel(district["id"], o2["id"], parcel_number="P-002",
                           frontage_ft=60.0)

        rows, _ = validate_paginated(
            api.list_district_parcels(district["id"], CLERK)
        )
        assert [r["parcel_number"] for r in rows] == ["P-001", "P-002"], (
            "district parcel listing must order by parcel_number ascending"
        )

        owner_rows, _ = validate_paginated(api.list_owner_parcels(o2["id"], CLERK))
        assert [r["parcel_number"] for r in owner_rows] == ["P-002"]
        assert owner_rows[0]["id"] == p2["id"]

    def test_district_list_pagination(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips a number of items and defaults to 0." and
        "Unless a listing documents otherwise, resources sort by `created_at`
        in ascending order."

        Design: Corner/entities/e_district_list_pagination
        """
        pg1 = create_district(name="PG-1")
        pg2 = create_district(name="PG-2")
        pg3 = create_district(name="PG-3")

        page1, meta1 = validate_paginated(
            api.list_districts(CLERK, params={"limit": 2, "offset": 0})
        )
        assert [r["id"] for r in page1] == [pg1["id"], pg2["id"]]
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_districts(CLERK, params={"limit": 2, "offset": 2})
        )
        assert [r["id"] for r in page2] == [pg3["id"]]
        assert meta2["has_more"] is False

    def test_parcel_create_after_draft_rejected(self, api):
        """PRD §3.1: "Parcels then attach to the district — but only while the
        district remains `DRAFT`; once petitioning has begun the roll is frozen
        and a late addition fails with `ERR_DISTRICT_NOT_DRAFT`."

        Design: Corner/entities/e_parcel_create_after_draft_rejected
        """
        district = create_district(name="ENT-P")
        owner = create_owner(full_name="Owner ep1", email="ep-o1@x.test")
        create_parcel(district["id"], owner["id"], parcel_number="P-001")
        open_petition(district["id"])
        late = create_parcel_payload(district_id=district["id"], owner_id=owner["id"],
                                     parcel_number="P-002", frontage_ft=10.0)
        validate_error(api.create_parcel(late, CLERK), ApiErrorId.ERR_DISTRICT_NOT_DRAFT)

    def test_derived_counters_reconciled_on_parcel_add(self, api):
        """PRD §2.10: "The district's `total_frontage_ft` and
        `eligible_parcel_count` are defined over exactly the participating set
        — parcels that are `ACTIVE` and not exempt — and are recomputed
        whenever that set changes: when parcels are added during `DRAFT`". PRD
        §3.1: "Every accepted parcel immediately recomputes the district's
        `total_frontage_ft` and `eligible_parcel_count`".

        Design: Corner/cross_cutting_complexity_layers/x_derived_counters_reconciled_on_parcel_add
        """
        district = create_district(name="XDR")
        o1 = create_owner(full_name="Owner xdr1", email="xdr-o1@x.test")
        o2 = create_owner(full_name="Owner xdr2", email="xdr-o2@x.test")
        create_parcel(district["id"], o1["id"], parcel_number="P-001", frontage_ft=60.0)
        after_first = get_district(district["id"])
        assert after_first["total_frontage_ft"] == pytest.approx(60.00)
        assert after_first["eligible_parcel_count"] == 1

        create_parcel(district["id"], o2["id"], parcel_number="P-002",
                      frontage_ft=40.0, exempt=True)
        after_exempt = get_district(district["id"])
        assert after_exempt["total_frontage_ft"] == pytest.approx(60.00), (
            "exempt parcel must not add to total_frontage_ft"
        )
        assert after_exempt["eligible_parcel_count"] == 1, (
            "exempt parcel must not add to eligible_parcel_count"
        )


class TestEnvelopeAndRetrieval:
    def test_response_envelope_and_pagination_fields(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources." PRD §2.3: "Both paginated
        and non-paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/ep_response_envelope_and_pagination_fields
        """
        district = create_district(name="ENV")

        single = api.get_district(district["id"], CLERK)
        body = single.json()
        assert single.status_code == 200
        assert body["meta"]["api_request_id"], "meta.api_request_id must be present"
        assert body["response_type"] == "object"
        assert body["data"]["name"] == "ENV"

        listing = api.list_districts(CLERK)
        body = listing.json()
        assert listing.status_code == 200
        assert body["response_type"] == "array"
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in body["meta"], f"meta.{field} missing from list envelope"
        assert body["meta"]["limit"] == 10, "default limit is 10"
        assert body["meta"]["offset"] == 0
        assert body["meta"]["total_count"] == 1
        assert body["meta"]["has_more"] is False

    def test_single_resource_get_not_found_sweep(self, api):
        """PRD §2.8: "Each resource type has its own error:
        `ERR_DISTRICT_NOT_FOUND`, `ERR_OWNER_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`,
        `ERR_PETITION_NOT_FOUND`, `ERR_SIGNATURE_NOT_FOUND`,
        `ERR_COST_ESTIMATE_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
        `ERR_HEARING_NOT_FOUND`, `ERR_OBJECTION_NOT_FOUND`,
        `ERR_RESOLUTION_NOT_FOUND`, `ERR_PHASE_NOT_FOUND`,
        `ERR_CHANGE_ORDER_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, and
        `ERR_PAYMENT_NOT_FOUND`."

        Design: Corner/errors/err_not_found_sweep
        """
        cases = [
            (lambda: api.get_owner(NON_EXISTENT_UUID, CLERK), ApiErrorId.ERR_OWNER_NOT_FOUND),
            (lambda: api.get_parcel(NON_EXISTENT_UUID, CLERK), ApiErrorId.ERR_PARCEL_NOT_FOUND),
            (lambda: api.get_petition(NON_EXISTENT_UUID, CLERK), ApiErrorId.ERR_PETITION_NOT_FOUND),
            (lambda: api.get_signature(NON_EXISTENT_UUID, CLERK), ApiErrorId.ERR_SIGNATURE_NOT_FOUND),
            (lambda: api.get_cost_estimate(NON_EXISTENT_UUID, CLERK), ApiErrorId.ERR_COST_ESTIMATE_NOT_FOUND),
            (lambda: api.get_hearing(NON_EXISTENT_UUID, CLERK), ApiErrorId.ERR_HEARING_NOT_FOUND),
            (lambda: api.get_objection(NON_EXISTENT_UUID, CLERK), ApiErrorId.ERR_OBJECTION_NOT_FOUND),
            (lambda: api.get_resolution(NON_EXISTENT_UUID, CLERK), ApiErrorId.ERR_RESOLUTION_NOT_FOUND),
            (lambda: api.get_assessment(NON_EXISTENT_UUID, CLERK), ApiErrorId.ERR_ASSESSMENT_NOT_FOUND),
            (lambda: api.get_construction_phase(NON_EXISTENT_UUID, CLERK), ApiErrorId.ERR_PHASE_NOT_FOUND),
            (lambda: api.get_change_order(NON_EXISTENT_UUID, CLERK), ApiErrorId.ERR_CHANGE_ORDER_NOT_FOUND),
            (lambda: api.get_invoice(NON_EXISTENT_UUID, CLERK), ApiErrorId.ERR_INVOICE_NOT_FOUND),
            (lambda: api.get_payment(NON_EXISTENT_UUID, CLERK), ApiErrorId.ERR_PAYMENT_NOT_FOUND),
        ]
        for call, expected_error in cases:
            validate_error(call(), expected_error)


class TestAuthenticationAndRoles:
    def test_missing_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        outside this list, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/v_missing_headers_unauthenticated
        """
        payload = create_district_payload(name="X")
        validate_error(
            api.create_district(payload, headers={}),
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
        )

    def test_systemadmin_cannot_create_district(self, api):
        """PRD §2.1: "When the supplied role is not among the roles an endpoint
        admits, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)." PRD §4: "POST `/districts` | Create a special assessment
        district | CityClerk".

        Design: Corner/rbac/r_systemadmin_cannot_create_district
        """
        payload = create_district_payload(name="X")
        validate_error(
            api.create_district(payload, ADMIN),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        )
