"""Who may act: the unauthenticated caller, the exclusive operations that no
neighbouring role may borrow, the receiving-deck operations two roles share, and
the one rule that keys on the operator identifier rather than the role."""

import pytest

from test_helpers import (
    accept_receipt_payload,
    adjudicate_claim_payload,
    complete_milling_payload,
    create_green_receipt_payload,
    create_grade_run_payload,
    create_species_profile_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    INSPECTOR,
    OPERATOR,
    SUPERVISOR,
    create_charge,
    create_species,
    refetch_charge,
    refetch_claim,
    refetch_lot,
    refetch_product_line,
    set_logical_clock,
    setup_line_only_submitted_claim,
    setup_milled_lot,
    setup_planned_lot,
)
from test_helpers.test_users import (
    CLAIM_ADJUDICATOR_USER_ID,
    CLAIM_SUBMITTER_USER_ID,
    NO_ROLE_HEADERS,
    make_warranty_adjudicator_headers,
)

# The milling report for the 4000 board-foot lot used by the peer-role pair.
HALF_LOT_MILLING = {
    "actual_milled_width_in": 3.190,
    "net_flooring_bf": 3200,
    "shorts_bf": 100,
    "sawdust_tons": 1.00,
    "shavings_tons": 0.50,
}

SECOND_CHARGE_START_UTC = "2026-09-05T00:00:00.000Z"


class TestUnauthenticatedCaller:
    """A request with no role header performs no operations at all, and the 401
    is decided before the payload is looked at."""

    def test_a_missing_role_header_beats_a_malformed_payload_and_blocks_reads(
        self, api
    ):
        """PRD 2.1: "A request that carries no role header at all, or that carries the
        reserved value `Anonymous`, is an unauthenticated caller: it performs no
        operations and is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        PRD 2.7: "1. Authentication — a request without an authenticated principal is
        rejected with `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

        PRD 2.7: "3. Schema — required fields present, types well formed, enum values
        within their declared sets, decimals non-negative where applicable, and
        pagination `limit` within 1 through 100 with `offset` at least 0. Rejected with
        `ERR_INVALID_REQUEST` (400). Applies to every endpoint."

        Design: Corner/rbac/species_profile_create_without_role_header_unauthenticated
        """
        set_logical_clock(api)

        validate_error(
            api.create_species_profile(
                create_species_profile_payload(), NO_ROLE_HEADERS
            ),
            "ERR_UNAUTHENTICATED",
            expected_status=401,
        )
        validate_error(
            api.create_species_profile(
                create_species_profile_payload(density_class="NOT_A_CLASS"),
                NO_ROLE_HEADERS,
            ),
            "ERR_UNAUTHENTICATED",
            expected_status=401,
        )
        validate_error(
            api.list_species_profiles(NO_ROLE_HEADERS),
            "ERR_UNAUTHENTICATED",
            expected_status=401,
        )

        _rows, meta = validate_paginated(api.list_species_profiles(ADMIN))
        assert meta["total_count"] == 0


class TestMillingCompletionIsExclusive:
    """Recording milling completion belongs to one role, and the configuration
    backstop does not reach it."""

    def test_neither_the_inspector_nor_the_admin_may_record_milling(self, api):
        """PRD 2.1: "`MillSupervisor` alone records milling completion."

        PRD 2.1: "A request whose role is recognised but is not on the acting
        endpoint's permitted list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        PRD 3.6: "The provisional yield is recorded at the same time:
        `provisional_yield_pct` is `net_flooring_bf` divided by `input_dry_bf`,
        expressed as a percentage and rounded half up to two decimal places — 78.00
        percent in that example."

        Design: Corner/rbac/complete_milling_by_grade_inspector_forbidden
        """
        ctx = setup_planned_lot(api, input_dry_bf=6000)
        lot_id = ctx["lot"]["id"]

        _rows, meta = validate_paginated(
            api.list_byproduct_batches(SUPERVISOR, params={"flooring_lot_id": lot_id})
        )
        assert meta["total_count"] == 0

        for forbidden in (INSPECTOR, ADMIN):
            validate_error(
                api.complete_milling(lot_id, complete_milling_payload(), forbidden),
                "ERR_FORBIDDEN_ROLE",
                expected_status=403,
            )
            assert refetch_lot(api, lot_id)["status"] == "PLANNED"

        milled = validate_success(
            api.complete_milling(lot_id, complete_milling_payload(), SUPERVISOR),
            expected_status=200,
        )
        assert milled["status"] == "MILLED"
        assert milled["provisional_yield_pct"] == pytest.approx(78.00, abs=0.01)

        _rows, meta = validate_paginated(
            api.list_byproduct_batches(SUPERVISOR, params={"flooring_lot_id": lot_id})
        )
        assert meta["total_count"] == 3


class TestPeerRolesDoNotBorrowEachOthersWork:
    """Being adjacent in the workflow grants nothing: the kiln role cannot grade
    and the grading role cannot run the kiln."""

    def test_the_denial_is_symmetric_and_costs_the_lot_no_concurrency_token(self, api):
        """PRD 2.1: "They are peer roles rather than a hierarchy — each owns a stretch
        of the mill and `MillAdmin` acts as a configuration owner and workflow
        backstop:"

        PRD 2.1: "`KilnOperator` alone loads a charge, starts its drying leg, begins
        conditioning, records the stress test and resumes conditioning after a redry."

        PRD 2.1: "`GradeInspector` alone opens a grade run, adds bundles to it and
        finalizes it."

        Design: Corner/rbac/kiln_operator_cannot_grade_and_grade_inspector_cannot_run_the_kiln
        """
        ctx = setup_milled_lot(
            api, input_dry_bf=4000, milling=dict(HALF_LOT_MILLING)
        )
        lot_id = ctx["lot"]["id"]
        milled_version = ctx["lot"]["version"]

        second_charge = create_charge(
            api,
            ctx["schedule"],
            ctx["chamber"],
            planned_start_utc=SECOND_CHARGE_START_UTC,
        )

        validate_error(
            api.create_grade_run(
                create_grade_run_payload(
                    lot_id, milled_version, inspector_ruleset="NHLA"
                ),
                OPERATOR,
            ),
            "ERR_FORBIDDEN_ROLE",
            expected_status=403,
        )
        _rows, meta = validate_paginated(
            api.list_grade_runs(INSPECTOR, params={"flooring_lot_id": lot_id})
        )
        assert meta["total_count"] == 0
        assert refetch_lot(api, lot_id)["version"] == milled_version

        validate_error(
            api.load_charge(second_charge["id"], INSPECTOR),
            "ERR_FORBIDDEN_ROLE",
            expected_status=403,
        )
        assert refetch_charge(api, second_charge["id"])["status"] == "SCHEDULED"

        run = validate_success(
            api.create_grade_run(
                create_grade_run_payload(
                    lot_id, milled_version, inspector_ruleset="NHLA"
                ),
                INSPECTOR,
            ),
            expected_status=201,
        )
        assert run["status"] == "DRAFT"
        assert run["inspector_ruleset"] == "NHLA"
        assert refetch_lot(api, lot_id)["version"] == milled_version + 1


class TestReceivingDeckIsShared:
    """Recording and accepting a receipt are shared operations, and neither is
    scoped to whoever created the row."""

    def test_each_role_can_accept_the_others_receipt(self, api):
        """PRD 2.1: "`ProcurementClerk` owns the receiving deck: recording, accepting
        and rejecting green receipts."

        PRD 2.1: "It also shares most workflow operations as a backstop."

        PRD 3.2: "A `ProcurementClerk` (or a `MillAdmin` acting as backstop) records
        each inbound delivery of logs or green lumber with the `species_profile_id`
        delivered, the `supplier_name` of record, the gross `received_board_feet` as
        delivered, a `receipt_grade` of `FAS`, `SELECT`, `NO1_COMMON` or `NO2_COMMON`
        assigned at the deck, and the measured `moisture_pct_at_receipt`."

        Design: Corner/rbac/green_receipt_create_shared_by_procurement_clerk_and_mill_admin
        """
        set_logical_clock(api)
        species = create_species(api)

        clerk_receipt = validate_success(
            api.create_green_receipt(
                create_green_receipt_payload(species["id"]), CLERK
            ),
            expected_status=201,
        )
        assert clerk_receipt["status"] == "RECEIVED"

        admin_receipt = validate_success(
            api.create_green_receipt(
                create_green_receipt_payload(
                    species["id"],
                    supplier_name="Valley Sawmill",
                    received_board_feet=3000,
                    receipt_grade="SELECT",
                    moisture_pct_at_receipt=44.0,
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert admin_receipt["status"] == "RECEIVED"

        accepted_by_admin = validate_success(
            api.accept_green_receipt(
                clerk_receipt["id"], accept_receipt_payload(5800), ADMIN
            ),
            expected_status=200,
        )
        assert accepted_by_admin["status"] == "ACCEPTED"
        assert accepted_by_admin["accepted_board_feet"] == 5800

        accepted_by_clerk = validate_success(
            api.accept_green_receipt(
                admin_receipt["id"], accept_receipt_payload(2900), CLERK
            ),
            expected_status=200,
        )
        assert accepted_by_clerk["status"] == "ACCEPTED"
        assert accepted_by_clerk["accepted_board_feet"] == 2900

        _rows, meta = validate_paginated(
            api.list_green_receipts(CLERK, params={"status": "ACCEPTED"})
        )
        assert meta["total_count"] == 2


class TestSegregationOfDuties:
    """The one identifier-keyed rule: the operator who filed a claim may not
    decide it, whatever role it presents."""

    def test_the_same_role_under_a_different_identifier_may_adjudicate(self, api):
        """PRD 2.1: "There is exactly one segregation-of-duties rule, and it is enforced
        on identifiers rather than roles: the `X-User-ID` that filed a warranty claim
        may not adjudicate that same claim, even when it presents the
        `WarrantyAdjudicator` role."

        PRD 2.1: "Such an attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP
        403)."

        PRD 2.7: "14. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES` (403), on
        `POST /mill/warranty-claims/{warranty_claim_id}/adjudicate` only."

        Design: Corner/rbac/claim_submitter_cannot_adjudicate_its_own_claim
        """
        ctx = setup_line_only_submitted_claim(api)
        claim_id = ctx["claim"]["id"]
        line_id = ctx["product_line"]["id"]
        submitter = make_warranty_adjudicator_headers(CLAIM_SUBMITTER_USER_ID)
        adjudicator = make_warranty_adjudicator_headers(CLAIM_ADJUDICATOR_USER_ID)

        validate_error(
            api.adjudicate_claim(
                claim_id,
                adjudicate_claim_payload(adjudicated_affected_sf=240),
                submitter,
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            expected_status=403,
        )
        held = refetch_claim(api, claim_id)
        assert held["adjudication_status"] == "SUBMITTED"
        assert held["adjudicated_by_user_id"] is None
        assert held["adjudicated_liability_cents"] is None
        assert refetch_product_line(api, line_id)["warranty_committed_cents"] == 0

        approved = validate_success(
            api.adjudicate_claim(
                claim_id,
                adjudicate_claim_payload(adjudicated_affected_sf=240),
                adjudicator,
            ),
            expected_status=200,
        )
        assert approved["adjudication_status"] == "APPROVED"
        assert approved["adjudicated_by_user_id"] == CLAIM_ADJUDICATOR_USER_ID
        assert approved["adjudicated_liability_cents"] == 173113
        assert approved["submitted_by_user_id"] == CLAIM_SUBMITTER_USER_ID
