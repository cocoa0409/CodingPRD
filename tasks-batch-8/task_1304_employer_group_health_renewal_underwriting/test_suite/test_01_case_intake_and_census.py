"""Case intake, census validation rules, and case version behavior."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    build_user_headers,
    create_broker,
    create_case,
    create_case_in_census_pending,
    create_case_payload,
    create_broker_payload,
    create_census_payload,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]


class TestCaseCreation:
    def test_create_case_returns_intake_initial_state(self):
        """PRD section 3.1: "The case is born in `INTAKE`, and the server stamps
        `assigned_underwriter_id` with the creating underwriter's `X-User-ID`. The
        case's computed pricing fields — `credibility_factor`, `manual_rate_cents`,
        `experience_rate_cents`, `blended_rate_cents`, `rate_cap_pct`, and the
        `is_rate_cap_applied` flag — all start at their zero defaults (0, 0, 0, 0,
        0, and false respectively)".
        PRD section 2.4: "`version` (integer): starts at 1 on creation and
        increments by one on every mutation".

        Design: Corner/entities/create_case_returns_intake_initial_state
        """
        broker = create_broker()
        headers = build_user_headers("uw-001", "Underwriter")
        resp = api_client.create_case(create_case_payload(broker["id"]), headers)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "INTAKE"
        assert data["version"] == 1
        assert data["assigned_underwriter_id"] == "uw-001"
        assert data["credibility_factor"] == 0
        assert data["blended_rate_cents"] == 0
        assert data["manual_rate_cents"] == 0
        assert data["experience_rate_cents"] == 0
        assert data["is_rate_cap_applied"] is False

    def test_get_case_returns_stored_fields(self):
        """PRD section 3.1: "With a broker on file, an `Underwriter` opens an
        **Underwriting Case** by providing the employer's legal `group_name`,
        total eligible `group_size` as an integer, the four-digit `sic_code`,
        the two-letter `state_code` of situs, the renewal `effective_date`, the
        in-force `current_premium_annual` in cents, the `current_renewal_date`,
        the `funding_type` (one of `FULLY_INSURED`, `LEVEL_FUNDED`, or
        `SELF_FUNDED`), and the `broker_id` of the broker of record."

        Design: Corner/entities/get_case_returns_stored_fields
        """
        broker = create_broker()
        case = create_case(broker["id"], group_name="EchoCo")
        resp = api_client.get_case(case["id"], TEST_USERS["compliance_headers"])
        data = validate_success(resp)
        assert data["group_name"] == "EchoCo"
        assert data["group_size"] == 500
        assert data["sic_code"] == "7372"
        assert data["broker_id"] == broker["id"]
        assert data["funding_type"] == "FULLY_INSURED"
        assert data["current_premium_annual"] == 24000000

    def test_list_cases_paginates_with_envelope(self):
        """PRD section 2.3: "The `limit` parameter specifies the maximum number
        of items to return; it defaults to 10 when omitted, with a minimum of 1
        and a maximum of 100."
        PRD section 2.3: "The `offset` parameter specifies how many items to skip
        and defaults to 0."
        PRD section 2.3: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_cases_paginates_with_envelope
        """
        broker = create_broker()
        c1 = create_case(broker["id"], group_name="PageOneCo")
        c2 = create_case(broker["id"], group_name="PageTwoCo")
        page1, meta1 = validate_paginated(
            api_client.list_cases(UW, params={"limit": 1, "offset": 0})
        )
        page2, meta2 = validate_paginated(
            api_client.list_cases(UW, params={"limit": 1, "offset": 1})
        )
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0
        assert meta2["has_more"] is False
        assert len(page1) == 1 and len(page2) == 1
        returned_ids = {page1[0]["id"], page2[0]["id"]}
        assert returned_ids == {c1["id"], c2["id"]}

    def test_get_missing_case_returns_not_found(self):
        """PRD section 2.6: "followed by existence of every resource identifier in
        the path (`ERR_NOT_FOUND`)".

        Design: Corner/entities/get_missing_case_returns_not_found
        """
        resp = api_client.get_case(NON_EXISTENT_UUID, UW)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_create_case_missing_group_size_rejected(self):
        """PRD section 3.1: "an `Underwriter` opens an **Underwriting Case** by
        providing the employer's legal `group_name`, total eligible `group_size`
        as an integer, the four-digit `sic_code`" — omitting the required
        `group_size` input is a malformed request, rejected with
        `ERR_INVALID_REQUEST` (HTTP 400 per the section 5 catalogue).

        Design: Corner/entities/create_case_missing_group_size_rejected
        """
        broker = create_broker()
        payload = create_case_payload(broker["id"])
        del payload["group_size"]
        resp = api_client.create_case(payload, UW)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _cases, meta = validate_paginated(api_client.list_cases(UW))
        assert meta["total_count"] == 0

    def test_create_case_invalid_funding_type_rejected(self):
        """PRD section 3.1: "the `funding_type` (one of `FULLY_INSURED`,
        `LEVEL_FUNDED`, or `SELF_FUNDED`)".

        Design: Corner/entities/create_case_invalid_funding_type_rejected
        """
        broker = create_broker()
        payload = create_case_payload(broker["id"], funding_type="PARTLY_INSURED")
        resp = api_client.create_case(payload, UW)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_broker_created_active_by_default(self):
        """PRD section 3.1: "A newly registered broker is immediately `ACTIVE`".

        Design: Corner/entities/broker_created_active_by_default
        """
        resp = api_client.create_broker(create_broker_payload(), UW)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"

    def test_census_child_scoped_to_parent_case(self):
        """PRD section 2.6: "For nested paths (for example, a census snapshot
        addressed beneath a case), identifiers are validated left to right: the
        system confirms the parent exists before attempting to resolve the child,
        and the first identifier in the path that does not resolve determines the
        404 response."
        PRD section 3.2: "On submission the snapshot is born `PENDING`".

        Design: Corner/entities/census_child_scoped_to_parent_case
        """
        broker = create_broker()
        case = create_case(broker["id"])
        resp = api_client.create_census_snapshot(
            NON_EXISTENT_UUID, create_census_payload(), UW
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        resp = api_client.create_census_snapshot(
            case["id"], create_census_payload(), UW
        )
        data = validate_success(resp, expected_status=201)
        assert data["case_id"] == case["id"]
        assert data["status"] == "PENDING"

    def test_case_version_increments_on_each_mutation(self):
        """PRD section 2.4: "`version` (integer): starts at 1 on creation and
        increments by one on every mutation, including system-driven state
        transitions and derived-field recomputation. Any write that changes a
        resource's state or recomputed fields — including cascades that touch a
        parent — refreshes the parent's `updated_at` and increments its
        `version`."

        Design: Corner/entities/case_version_increments_on_each_mutation
        """
        broker = create_broker()
        case = create_case(broker["id"])
        assert case["version"] == 1
        case2 = validate_success(api_client.submit_for_census(case["id"], UW))
        assert case2["version"] == 2
        census = get_success_data(
            api_client.create_census_snapshot(
                case["id"], create_census_payload(), UW
            )
        )
        validate_success(api_client.validate_census(census["id"], UW))
        # Census validation cascades to the parent (CENSUS_PENDING ->
        # CENSUS_RECEIVED plus rating fields), itself a case mutation.
        after_validate = get_success_data(api_client.get_case(case["id"], UW))
        case3 = validate_success(api_client.request_claims(case["id"], UW))
        assert case3["version"] == after_validate["version"] + 1


class TestCensusValidation:
    def test_census_count_mismatch_alone(self):
        """PRD section 3.2: "its `total_employees` must equal the parent case's
        `group_size` (else `ERR_CENSUS_COUNT_MISMATCH`)".

        Design: Corner/validations/census_count_mismatch_alone
        """
        broker = create_broker()
        case = create_case_in_census_pending(broker["id"])
        census = get_success_data(
            api_client.create_census_snapshot(
                case["id"], create_census_payload(total_employees=999), UW
            )
        )
        resp = api_client.validate_census(census["id"], UW)
        validate_error(resp, ApiErrorId.ERR_CENSUS_COUNT_MISMATCH)
        census = get_success_data(api_client.get_census_snapshot(census["id"], UW))
        assert census["status"] == "PENDING"
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "CENSUS_PENDING"

    def test_census_tier_sum_mismatch(self):
        """PRD section 3.2: "the four values inside `tier_distribution` must sum
        exactly to `enrolled_employees` (else `ERR_TIER_SUM_MISMATCH`)".

        Design: Corner/validations/census_tier_sum_mismatch
        """
        broker = create_broker()
        case = create_case_in_census_pending(broker["id"])
        census = get_success_data(
            api_client.create_census_snapshot(
                case["id"],
                create_census_payload(
                    tier_distribution={"EE": 200, "ES": 80, "EC": 60, "EF": 50}
                ),
                UW,
            )
        )
        resp = api_client.validate_census(census["id"], UW)
        validate_error(resp, ApiErrorId.ERR_TIER_SUM_MISMATCH)
        census = get_success_data(api_client.get_census_snapshot(census["id"], UW))
        assert census["status"] == "PENDING"

    def test_census_empty_enrollment(self):
        """PRD section 3.2: "its `enrolled_employees` must be greater than zero
        (else `ERR_EMPTY_ENROLLMENT`)".

        Design: Corner/validations/census_empty_enrollment
        """
        broker = create_broker()
        case = create_case_in_census_pending(broker["id"])
        census = get_success_data(
            api_client.create_census_snapshot(
                case["id"],
                create_census_payload(
                    enrolled_employees=0,
                    dependent_count=0,
                    tier_distribution={"EE": 0, "ES": 0, "EC": 0, "EF": 0},
                ),
                UW,
            )
        )
        resp = api_client.validate_census(census["id"], UW)
        validate_error(resp, ApiErrorId.ERR_EMPTY_ENROLLMENT)
        census = get_success_data(api_client.get_census_snapshot(census["id"], UW))
        assert census["status"] == "PENDING"

    def test_census_validate_flips_case_to_census_received(self):
        """PRD section 3.2: "When a snapshot passes validation it becomes
        `VALIDATED`, and the cascade begins: if the parent case was
        `CENSUS_PENDING`, it advances automatically to `CENSUS_RECEIVED`".
        PRD section 3.2: "The group-size factor is 0.0 when `group_size` is
        below 25 (too small for any credibility), the group size divided by 100
        when the size is at least 25 but below 100, the group size divided by
        500 when the size is at least 100 but below 500, and 1.0 at 500 lives or
        more."

        Design: Corner/state_machines/census_validate_flips_case_to_census_received
        """
        broker = create_broker()
        case = create_case_in_census_pending(broker["id"], group_size=100)
        census = get_success_data(
            api_client.create_census_snapshot(
                case["id"],
                create_census_payload(
                    total_employees=100,
                    enrolled_employees=80,
                    dependent_count=40,
                    tier_distribution={"EE": 40, "ES": 16, "EC": 12, "EF": 12},
                ),
                UW,
            )
        )
        census = validate_success(api_client.validate_census(census["id"], UW))
        assert census["status"] == "VALIDATED"
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "CENSUS_RECEIVED"
        assert case["credibility_factor"] == pytest.approx(0.2, abs=1e-9)

    def test_state_beats_business_constraint_on_census_validate(self):
        """PRD section 2.6: "After existence and version checks, business-state
        guards fire: the parent-case state guard (`ERR_CASE_INVALID_STATE` and
        its more specific case-state errors), then the entity's own transition
        guard (`ERR_INVALID_STATE_TRANSITION` and the more specific per-entity
        "not in state X" errors), then the rule-specific business constraints
        enumerated throughout section 3".
        PRD section 3.2: "the snapshot must be `PENDING` (else
        `ERR_CENSUS_NOT_PENDING`)".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_census_validate
        """
        broker = create_broker()
        case = create_case_in_census_pending(broker["id"])
        census = get_success_data(
            api_client.create_census_snapshot(
                case["id"], create_census_payload(total_employees=999), UW
            )
        )
        validate_success(api_client.reject_census(census["id"], UW))
        # Both the state check (not PENDING) and the business check (count
        # mismatch) fail; the state guard must win.
        resp = api_client.validate_census(census["id"], UW)
        validate_error(resp, ApiErrorId.ERR_CENSUS_NOT_PENDING)
        census = get_success_data(api_client.get_census_snapshot(census["id"], UW))
        assert census["status"] == "REJECTED"
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "CENSUS_PENDING"

    def test_validate_rejected_census_keeps_case_unchanged(self):
        """PRD section 3.2: "A snapshot that fails review can instead be rejected
        outright, moving it from `PENDING` to `REJECTED` with no arithmetic checks
        applied". A later validate attempt on the rejected snapshot must fail
        because "the snapshot must be `PENDING` (else `ERR_CENSUS_NOT_PENDING`)"
        and leave the parent case in `CENSUS_PENDING`.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_census_validate
        """
        broker = create_broker()
        case = create_case_in_census_pending(broker["id"])
        census = get_success_data(
            api_client.create_census_snapshot(
                case["id"], create_census_payload(), UW
            )
        )
        rejected = validate_success(api_client.reject_census(census["id"], UW))
        assert rejected["status"] == "REJECTED"
        resp = api_client.validate_census(census["id"], UW)
        validate_error(resp, ApiErrorId.ERR_CENSUS_NOT_PENDING)
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "CENSUS_PENDING"
