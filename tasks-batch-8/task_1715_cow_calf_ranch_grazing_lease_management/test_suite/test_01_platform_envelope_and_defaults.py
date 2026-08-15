"""Response envelope, resource defaults, pagination, and request well-formedness."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_pasture,
    assert_ranch,
    create_herd_group_payload,
    create_pasture_payload,
    create_ranch,
    create_ranch_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

RANCH_MGR = TEST_USERS["ranch_manager_headers"]
RANGE_MGR = TEST_USERS["range_manager_headers"]
HERD_MGR = TEST_USERS["herd_manager_headers"]


class TestRanchDefaults:
    def test_ranch_create_applies_defaults(self, api):
        """PRD §3.1: "A new ranch starts with `drought_posture` of `NORMAL`, a
        `ranch_production_pct` of 100.0, and an `assessment_seq` of zero"
        PRD §3.1: "when omitted, the grace period defaults to 30 days."
        PRD §2.5: "`id` (string): a unique, server-minted identifier formatted as
        a UUID, with no type prefix."

        Design: Corner/entities/ranch_create_applies_defaults
        """
        resp = api.create_ranch(
            create_ranch_payload(name="Default Ranch", hq_state="MT"), RANCH_MGR)
        ranch = validate_success(resp, 201)
        assert_ranch(ranch)
        assert ranch["drought_posture"] == "NORMAL"
        assert ranch["destock_grace_days"] == 30
        assert ranch["assessment_seq"] == 0
        assert ranch["ranch_production_pct"] == 100.0
        assert is_valid_uuid(ranch["id"]), (
            f"id must be a prefix-free UUID, got {ranch['id']!r}"
        )


class TestRequestWellFormedness:
    def test_pasture_create_computed_field_rejected(self, api):
        """PRD §2.8: "Request-body well-formedness: required fields are present,
        enum members are valid, no computed, system-managed, or unknown fields
        are supplied, quantities are positive, and any window's start precedes
        its end (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/pasture_create_computed_field_rejected
        """
        ranch = create_ranch(name="R")
        payload = create_pasture_payload(ranch["id"], name="P",
                                         base_capacity_aum=100)
        payload["available_aum"] = 5  # computed field supplied by the client
        resp = api.create_pasture(payload, RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_herd_group_invalid_enum_rejected(self, api):
        """PRD §2.8: "Request-body well-formedness: required fields are present,
        enum members are valid, no computed, system-managed, or unknown fields
        are supplied, quantities are positive, and any window's start precedes
        its end (`ERR_INVALID_REQUEST`)."
        PRD §3.3: "an `animal_class` of `MATURE_COW`, `REPLACEMENT_HEIFER`, or
        `GROWING`"

        Design: Corner/entities/herd_group_invalid_enum_rejected
        """
        ranch = create_ranch(name="R")
        payload = create_herd_group_payload(
            ranch["id"], group_name="Bad", animal_class="STEER",
            head_count=10, avg_weight_lbs=500)
        resp = api.create_herd_group(payload, HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestNotFound:
    def test_get_pasture_not_found(self, api):
        """PRD §2.8: "Existence: every identifier in the path is resolved,
        validated left-to-right, and every foreign-key identifier in the request
        body exists and belongs to the same ranch as the resource it is attached
        to (`ERR_NOT_FOUND`)."

        Design: Corner/entities/get_pasture_not_found
        """
        resp = api.get_pasture(NON_EXISTENT_UUID, RANGE_MGR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestPasturePagination:
    def test_pasture_list_pagination_envelope(self, api):
        """PRD §2.3: "The `meta` object of a list response carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`,
        where `total_count` reports the full size of the filtered result set and
        `has_more` indicates whether additional items remain beyond the returned
        window."

        Design: Corner/entities/pasture_list_pagination_envelope
        """
        ranch = create_ranch(name="R")
        for name in ("P1", "P2", "P3"):
            p = api.create_pasture(
                create_pasture_payload(ranch["id"], name=name,
                                       base_capacity_aum=100), RANGE_MGR)
            assert_pasture(validate_success(p, 201))

        page1, meta1 = validate_paginated(api.list_pastures(
            RANGE_MGR, params={"limit": 2}))
        assert len(page1) == 2, f"page 1 must hold 2 items, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_pastures(
            RANGE_MGR, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1, f"page 2 must hold 1 item, got {len(page2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestRanchPolicyUpdate:
    def test_ranch_patch_increments_version_and_updated_at(self, api):
        """PRD §3.1: "The `RanchManager` may later update the `name`,
        `hq_state`, or `destock_grace_days` policy fields; each such update
        increments the ranch's `version`."
        PRD §2.5: "`updated_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits recording the resource's last modification; it
        refreshes on any change to the resource's properties."

        Design: Corner/entities/ranch_patch_increments_version_and_updated_at
        """
        ranch = create_ranch(name="R")
        updated = validate_success(
            api.patch_ranch(ranch["id"], {"destock_grace_days": 21}, RANCH_MGR))
        assert updated["version"] == ranch["version"] + 1, (
            f"version must increment by exactly 1: {ranch['version']} -> "
            f"{updated['version']}"
        )
        assert updated["destock_grace_days"] == 21
        assert updated["id"] == ranch["id"]
        assert updated["created_at"] == ranch["created_at"], "created_at is stable"
        assert updated["updated_at"] != ranch["updated_at"], (
            "updated_at must refresh on modification"
        )


class TestInitialStates:
    def test_initial_states_on_create(self, api):
        """PRD §3.2: "The lease's `lease_status` is born `DRAFT`."
        PRD §3.4: "The season's `season_status` opens at `PLANNED`."
        PRD §3.4: "The system derives the season's `required_bull_count` at one
        bull for every 25 exposed females, rounded up to a whole bull."
        PRD §3.4: "A new bull's `bse_status` is `UNTESTED` and its `life_status`
        is `ACTIVE`"
        PRD §3.3: "The program's `program_status` is `ACTIVE` from creation."

        Design: Corner/state_machines/initial_states_on_create
        """
        from test_helpers import (
            create_breeding_season,
            create_bull,
            create_herd_group,
            create_lease,
            create_pasture,
            create_supplement_program,
        )

        ranch = create_ranch(name="R")
        pasture = create_pasture(ranch["id"], name="P", acreage=400,
                                 tenure="LEASED", base_capacity_aum=100)
        group = create_herd_group(ranch["id"], group_name="G")

        lease = create_lease(ranch["id"], pasture["id"], aum_allotment=50,
                             minimum_commit_aum=10, overage_tier1_cap_aum=10)
        assert lease["lease_status"] == "DRAFT"

        season = create_breeding_season(ranch["id"], group["id"],
                                        exposed_head_count=25)
        assert season["season_status"] == "PLANNED"
        assert season["required_bull_count"] == 1, "ceil(25/25) == 1"

        bull = create_bull(ranch["id"], tag="B1")
        assert bull["bse_status"] == "UNTESTED"
        assert bull["life_status"] == "ACTIVE"

        program = create_supplement_program(group["id"], ranch["id"])
        assert program["program_status"] == "ACTIVE"
        assert program["delivered_lbs_total"] == 0


class TestAuthContext:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request whose headers are missing, or whose
        `X-User-Role` does not name one of the four declared roles, is rejected
        with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        resp = api.create_ranch(create_ranch_payload(name="R"), headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_CONTEXT_HEADER,
                       expected_status=400)
