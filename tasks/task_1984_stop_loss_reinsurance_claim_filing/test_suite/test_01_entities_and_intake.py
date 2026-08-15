"""Entity creation, defaults, and intake validation."""
from test_helpers import (
    ADMIN,
    EXAMINER,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_claim,
    assert_member,
    assert_plan,
    create_member,
    create_plan,
    get_contract_version,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_plan_contract_member,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api_client
from test_helpers.factories import create_lasered_term_payload


class TestPlanCreation:
    def test_create_plan_with_required_fields_returns_201(self, api):
        """PRD §3.1: "A `PlanAdministrator` opens the book of business by
        creating a plan with its `plan_name` — the legal name of the
        self-funded employer health plan — and the sponsor's
        `sponsor_tax_id`. A plan's `status` begins as `ACTIVE`"
        PRD §4: "Operations that create a new resource return `201 Created`"
        PRD §2.4: "The `id` is a server-minted UUID with no type prefix. The
        `created_at` timestamp is an ISO 8601 UTC value with three fractional
        digits recording when the resource was created."

        Design: Corner/entities/create_plan_with_required_fields_returns_201
        """
        resp = api.create_plan(
            {"plan_name": "Acme", "sponsor_tax_id": "12-3456789"}, ADMIN)
        data = validate_success(resp, 201)
        assert_plan(data)
        assert data["status"] == "ACTIVE", (
            f"New plan must be ACTIVE, got {data['status']}")
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert data["plan_name"] == "Acme"
        assert data["sponsor_tax_id"] == "12-3456789"

    def test_create_plan_missing_sponsor_tax_id_returns_400(self, api):
        """PRD §2.9: "Independently of this chain, a payload missing a
        required field or containing a malformed value is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "creating a plan with its `plan_name` — the legal name of
        the self-funded employer health plan — and the sponsor's
        `sponsor_tax_id`."

        Design: Corner/entities/create_plan_missing_sponsor_tax_id_returns_400
        """
        resp = api.create_plan({"plan_name": "Incomplete"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_nonexistent_plan_returns_404(self, api):
        """PRD §2.9: "Existence comes third: every path identifier and every
        body foreign key must resolve to an existing entity, failing with
        `ERR_NOT_FOUND` (HTTP 404)"

        Design: Corner/entities/get_nonexistent_plan_returns_404
        """
        resp = api.get_plan(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestClaimAndMemberDefaults:
    def test_new_claim_is_submitted_with_null_paid_date(self, api):
        """PRD §3.4: "A new claim starts in `SUBMITTED`, with `paid_date`
        remaining null until the claim is actually paid."

        Design: Corner/entities/claim_computed_status_field_ignores_client_input
        """
        plan = create_plan(plan_name="P", sponsor_tax_id="22-2222222")
        member = create_member(plan["id"], "M")
        resp = api.create_claim(
            {"plan_id": plan["id"], "member_id": member["id"],
             "service_date": "2026-02-01T00:00:00Z",
             "billed_amount_cents": 1_000_000, "claim_type": "MEDICAL"},
            EXAMINER)
        data = validate_success(resp, 201)
        assert_claim(data)
        assert data["status"] == "SUBMITTED", (
            f"New claim must be SUBMITTED, got {data['status']}")
        assert data["paid_date"] is None, (
            f"paid_date must be null until paid, got {data['paid_date']!r}")

    def test_new_member_notice_status_is_none(self, api):
        """PRD §3.1: "A new member starts with `status` set to `ACTIVE` and
        `notice_status` set to `NONE`."

        Design: Corner/entities/member_default_notice_status_is_none
        """
        plan = create_plan(plan_name="P", sponsor_tax_id="33-3333333")
        resp = api.create_member(
            {"plan_id": plan["id"], "member_external_id": "M",
             "date_of_birth": "1980-01-01",
             "coverage_start": "2025-01-01T00:00:00Z"}, ADMIN)
        data = validate_success(resp, 201)
        assert_member(data)
        assert data["notice_status"] == "NONE", (
            f"New member notice_status must be NONE, got {data['notice_status']}")
        assert data["status"] == "ACTIVE"


class TestLaserIntakeValidation:
    def test_laser_effective_from_equal_effective_to_rejected(self, api):
        """PRD §3.3: "Next the window must be well-formed, with
        `effective_from` strictly earlier than `effective_to`, else
        `ERR_INVALID_DATE_RANGE`."

        Design: Corner/entities/laser_invalid_effective_range_returns_422
        """
        ctx = setup_plan_contract_member(plan_name="P")
        contract_id = ctx["contract"]["id"]
        payload = create_lasered_term_payload(
            contract_id, ctx["member"]["id"], 15_000_000,
            "2026-07-01T00:00:00Z", "2026-07-01T00:00:00Z",
            get_contract_version(contract_id))
        resp = _api_client.create_lasered_term(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)
