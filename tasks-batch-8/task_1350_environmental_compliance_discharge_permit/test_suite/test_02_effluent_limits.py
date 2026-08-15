"""Effluent limits: input constraints, range overlap and supersession,
rescission compensation, and the outfall-version OCC guard (PRD §2.7, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_effluent_limit,
    create_effluent_limit,
    create_outfall,
    create_permit,
    get_outfall_version,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.factories import create_effluent_limit_payload
from test_helpers.fixtures import EM

ANY_HEADERS = TEST_USERS["regulator_headers"]  # reads are open to every role (PRD §2.1)


class TestLimitInputConstraints:
    def test_limit_create_rejects_zero_limit_value_and_inverted_range(self, api):
        """PRD §2.8: "`limit_value`, `method_detection_limit`, `flow_mgd` and
        `amount_cents` must each be strictly greater than zero; ... `effective_to`
        must be strictly after `effective_from` when present; ... Violations are
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/limit_create_rejects_zero_limit_value_and_inverted_range
        """
        permit = create_permit(permit_number="NPDES-ENT4")
        outfall = create_outfall(permit["id"])
        version = get_outfall_version(outfall["id"])

        resp_zero = api.create_effluent_limit(
            create_effluent_limit_payload(outfall["id"], version, limit_value=0), EM
        )
        validate_error(resp_zero, ApiErrorId.ERR_INVALID_REQUEST)

        resp_inverted = api.create_effluent_limit(
            create_effluent_limit_payload(
                outfall["id"],
                get_outfall_version(outfall["id"]),
                effective_from="2026-06-01T00:00:00Z",
                effective_to="2026-06-01T00:00:00Z",
            ),
            EM,
        )
        validate_error(resp_inverted, ApiErrorId.ERR_INVALID_REQUEST)

    def test_limit_create_rejects_bad_parameter_code_enum(self, api):
        """PRD §3.1: "`parameter_code` (one of `BOD5`, `TSS`, `PH`, `AMMONIA_N`,
        `COPPER`, `FECAL_COLIFORM`)". PRD §2.8: "required fields present, enum
        membership respected ... Violations are `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/limit_create_rejects_bad_parameter_code_enum
        """
        permit = create_permit(permit_number="NPDES-ENT10")
        outfall = create_outfall(permit["id"])
        resp = api.create_effluent_limit(
            create_effluent_limit_payload(
                outfall["id"],
                get_outfall_version(outfall["id"]),
                parameter_code="LEAD",
                limit_value=1.0,
            ),
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestLimitSupersedeAndRescind:
    def test_limit_rescind_compensates_predecessor(self, api):
        """PRD §3.1: "Rescission moves the successor from `ACTIVE` to `RESCINDED`
        and restores its named predecessor `SUPERSEDED → ACTIVE`, increments the
        outfall's `version`, and appends both `LIMIT_RESCINDED` and `LIMIT_RESTORED`
        audit entries."

        Design: Corner/state_machines/limit_rescind_compensates_predecessor
        """
        permit = create_permit(permit_number="NPDES-SM10")
        outfall = create_outfall(permit["id"])
        l1 = create_effluent_limit(
            outfall["id"], limit_value=10.0,
            effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-30T00:00:00Z",
        )
        l2 = create_effluent_limit(
            outfall["id"], limit_value=8.0,
            effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-30T00:00:00Z",
            supersedes_limit_id=l1["id"],
        )
        assert validate_success(api.get_effluent_limit(l1["id"], ANY_HEADERS))["status"] == "SUPERSEDED"
        version_before = get_outfall_version(outfall["id"])

        rescinded = validate_success(api.rescind_effluent_limit(l2["id"], EM))
        assert rescinded["status"] == "RESCINDED"
        restored = validate_success(api.get_effluent_limit(l1["id"], ANY_HEADERS))
        assert restored["status"] == "ACTIVE", "predecessor restored by the compensating action"
        assert get_outfall_version(outfall["id"]) > version_before, (
            "rescission increments the outfall's version"
        )

    def test_limit_rescind_rejected_for_original_limit(self, api):
        """PRD §3.1: "rescinding requires the limit to be `ACTIVE`
        (`ERR_LIMIT_NOT_ACTIVE`) and to have itself been created with a non-null
        `supersedes_limit_id` (`ERR_LIMIT_NOT_A_SUCCESSOR`)."

        Design: Corner/state_machines/limit_rescind_rejected_for_original_limit
        """
        permit = create_permit(permit_number="NPDES-SM11")
        outfall = create_outfall(permit["id"])
        limit = create_effluent_limit(outfall["id"])
        resp = api.rescind_effluent_limit(limit["id"], EM)
        validate_error(resp, ApiErrorId.ERR_LIMIT_NOT_A_SUCCESSOR)

    def test_limit_range_overlap_and_adjacency_semantics(self, api):
        """PRD §3.1: "No other `ACTIVE` limit with the same outfall, parameter and
        limit type may have a range intersecting the new one" and "Adjacency is not
        an overlap: a new limit whose `effective_from` is exactly an existing limit's
        `effective_to` is allowed. A violation is rejected with
        `ERR_LIMIT_RANGE_OVERLAP`."

        Design: Corner/validations/limit_range_overlap_and_adjacency_semantics
        """
        permit = create_permit(permit_number="NPDES-VAL9")
        outfall = create_outfall(permit["id"])
        create_effluent_limit(
            outfall["id"], limit_value=10.0,
            effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-30T00:00:00Z",
        )

        resp_overlap = api.create_effluent_limit(
            create_effluent_limit_payload(
                outfall["id"], get_outfall_version(outfall["id"]),
                limit_value=8.0, effective_from="2026-03-01T00:00:00Z",
            ),
            EM,
        )
        validate_error(resp_overlap, ApiErrorId.ERR_LIMIT_RANGE_OVERLAP)

        adjacent = create_effluent_limit(
            outfall["id"], limit_value=8.0, effective_from="2026-06-30T00:00:00Z"
        )
        assert_effluent_limit(adjacent)
        assert adjacent["status"] == "ACTIVE", "adjacent range is allowed (half-open ranges)"

    def test_limit_supersede_mismatch_rejected(self, api):
        """PRD §3.1: "When `supersedes_limit_id` is supplied it must reference an
        `ACTIVE` limit of the same outfall, the same `parameter_code` and the same
        `limit_type`; otherwise creation fails with `ERR_LIMIT_SUPERSEDE_MISMATCH`."

        Design: Corner/validations/limit_supersede_mismatch_rejected
        """
        permit = create_permit(permit_number="NPDES-VAL10")
        outfall = create_outfall(permit["id"])
        # The incumbent TSS limit ends 2026-06-30 and the new TSS limit starts
        # exactly then — adjacency is not an overlap (PRD §3.1), so the ladder
        # (§2.8: range overlap at rung 9, supersede consistency at rung 10)
        # reaches the supersede-mismatch check.
        create_effluent_limit(
            outfall["id"], parameter_code="TSS", limit_value=10.0,
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-06-30T00:00:00Z",
        )
        copper = create_effluent_limit(
            outfall["id"], parameter_code="COPPER", limit_value=1.0
        )
        resp = api.create_effluent_limit(
            create_effluent_limit_payload(
                outfall["id"], get_outfall_version(outfall["id"]),
                parameter_code="TSS", limit_value=9.0,
                effective_from="2026-06-30T00:00:00Z",
                supersedes_limit_id=copper["id"],
            ),
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_LIMIT_SUPERSEDE_MISMATCH)

    def test_error_limit_not_found_on_rescind(self, api):
        """PRD §2.8: "The first identifier that does not resolve yields the
        corresponding 404: the resource-specific `ERR_PERMIT_NOT_FOUND`,
        `ERR_OUTFALL_NOT_FOUND`, `ERR_LIMIT_NOT_FOUND`, ..."

        Design: Corner/errors/error_limit_not_found_on_rescind
        """
        resp = api.rescind_effluent_limit(NON_EXISTENT_UUID, EM)
        validate_error(resp, ApiErrorId.ERR_LIMIT_NOT_FOUND)


class TestLimitOptimisticConcurrency:
    def test_occ_effluent_limit_create_stale_outfall_version(self, api):
        """PRD §2.7: "Creating an effluent limit requires the request to carry
        `expected_outfall_version`, set to the `version` of the parent outfall as the
        client last observed it. Every successful limit creation increments that
        outfall's `version`, so a request bearing an older observed version is acting
        on a stale view of the outfall's limit set — for example, unaware that a newer
        `ACTIVE` limit has already superseded the one it intends to supersede — and is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_effluent_limit_create_stale_outfall_version
        """
        permit = create_permit(permit_number="NPDES-OCC1")
        outfall = create_outfall(permit["id"])
        stale_version = get_outfall_version(outfall["id"])
        create_effluent_limit(outfall["id"], expected_outfall_version=stale_version)
        assert get_outfall_version(outfall["id"]) != stale_version, (
            "the first creation bumped the outfall version"
        )

        resp = api.create_effluent_limit(
            create_effluent_limit_payload(
                outfall["id"], stale_version,
                parameter_code="BOD5", limit_value=5.0,
            ),
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
