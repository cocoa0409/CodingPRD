"""Cross-cutting layers: the two version gates, the tier thresholds and immediate visibility."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_ADJUDICATOR,
    ADMIN_INVESTIGATOR,
    ADMIN_PIGGYBACK,
    ADMIN_REVIEW,
    ApiErrorId,
    assert_cents,
    assert_instant,
    assert_score,
    make_member_headers,
    make_supplier_headers,
)
from test_helpers.constants import (
    BASE_TERM_END,
    CLOCK_TERM_START,
    SKU_DISPENSER,
)
from test_helpers.factories import (
    contract_usage_payload,
    piggyback_analysis_payload,
    renewal_amendment_payload,
)
from test_helpers.fixtures import (
    create_member,
    file_complaint,
    open_investigation,
    read_analysis,
    read_contract,
    read_member,
    read_supplier,
    set_clock,
    setup_active_contract,
    setup_authorised_member,
    setup_pending_contract,
    substantiate_complaint,
    verify_member,
)

RENEWAL_TERM_END = "2028-09-01T00:00:00Z"
NON_EXTENDING_TERM_END = "2026-09-01T00:00:00Z"
QUANTITY_TWO_SUBTOTAL_CENTS = 25000
QUANTITY_TWO_FEE_CENTS = 500
QUANTITY_TWO_TOTAL_CENTS = 25500
MAJOR_POINTS = 7.50
MINOR_POINTS = 2.50


def _verified_member_world(api):
    """An ACTIVE contract plus a member carried from creation through verification."""
    world = setup_active_contract(api)
    created = create_member(api)
    verified = verify_member(api, created["id"])
    world["created_member"] = created
    world["member"] = verified
    return world


def _open_analysis(api, world, expected_version):
    return api.create_piggyback_analysis(
        piggyback_analysis_payload(
            world["member"]["id"], world["contract"]["id"], expected_version
        ),
        ADMIN_PIGGYBACK,
    )


def _executed_contract_world(api):
    """A contract read at its creation version and again after execution."""
    world = setup_pending_contract(api)
    world["created_contract"] = world["contract"]
    set_clock(api, CLOCK_TERM_START)
    world["contract"] = validate_success(
        api.contract_award_status(
            world["contract"]["id"], {"action": "EXECUTE"}, ADMIN_REVIEW
        )
    )
    return world


def _propose_renewal(api, world, expected_version, requested_term_end):
    return api.create_contract_amendment(
        renewal_amendment_payload(
            world["contract"]["id"], expected_version, requested_term_end
        ),
        make_supplier_headers(world["contract"]["supplier_id"]),
    )


def _complaint_world(api, severities):
    """One authorised member and a queue of complaints already under investigation."""
    world = setup_active_contract(api)
    member, analysis = setup_authorised_member(api, world)
    world["member"] = member
    world["analysis"] = analysis
    world["line"] = world["lines"][SKU_DISPENSER]
    world["complaints"] = []
    for index, severity in enumerate(severities):
        complaint = file_complaint(
            api,
            world["contract"]["id"],
            member["id"],
            severity=severity,
            narrative=f"Cooperative service failure number {index + 1}.",
        )
        world["complaints"].append(
            open_investigation(api, complaint["id"], ADMIN_INVESTIGATOR)
        )
    return world


def _substantiate(api, world, count):
    """Carry the queue forward so that exactly `count` complaints are SUBSTANTIATED.

    Substantiation is a one-way transition out of `UNDER_INVESTIGATION`, so a later
    call only advances the complaints the earlier calls left untouched.
    """
    already = world.get("substantiated_count", 0)
    for index in range(already, count):
        world["complaints"][index] = substantiate_complaint(
            api, world["complaints"][index]["id"], ADMIN_ADJUDICATOR
        )
    world["substantiated_count"] = max(already, count)
    return read_supplier(api, world["contract"]["supplier_id"])


class TestMemberAgencyVersionGate:
    def test_01_the_creation_version_is_stale_once_verification_has_run(self, api):
        """PRD §2.6: "`POST /coop/piggyback-analyses` requires a non-optional
        `expected_member_agency_version` field carrying the client's last observed `version` of
        the target `MemberAgency`." PRD §2.6: "If it does not equal the member's current
        `version`, the create is rejected with `ERR_STALE_MEMBER_AGENCY_VERSION` (HTTP 412)." PRD
        §2.9: "Optimistic concurrency — `ERR_STALE_MEMBER_AGENCY_VERSION` or
        `ERR_STALE_CONTRACT_VERSION`, 412, on `POST /coop/piggyback-analyses` and
        `POST /coop/contract-amendments` respectively."

        Design: Corner/Cross-Cutting Complexity Layers/member_agency_version_gate_refuses_a_stale_expectation_and_accepts_the_current_one
        """
        world = _verified_member_world(api)
        assert world["created_member"]["version"] == 1
        assert world["member"]["version"] == 2

        refused = _open_analysis(api, world, world["created_member"]["version"])

        validate_error(refused, ApiErrorId.ERR_STALE_MEMBER_AGENCY_VERSION, 412)
        _, meta = validate_paginated(api.list_piggyback_analyses(ADMIN_REVIEW))
        assert meta["total_count"] == 0
        after = read_member(api, world["member"]["id"])
        assert after["version"] == 2
        assert after["registration_status"] == "ACTIVE"

    def test_02_the_current_version_is_accepted_and_the_member_row_moves_again(self, api):
        """PRD §3.5: "Opening one is a supersession event: any prior analysis for the same
        member-and-contract pair whose `status` is `PENDING` or `DETERMINED` becomes `VOIDED` with
        `voided_reason` `SUPERSEDED_BY_NEWER_ANALYSIS`, and the member's own `version`
        increments." PRD §3.5: "The new row starts in `status` `PENDING` with `determination`,
        `doctrine_applied`, `authority_score`, `determined_at` and `expires_on` all null,
        `deduction_detail` empty and `local_waiver_required` false." PRD §2.4: "A change to a
        *derived* field counts as a mutation: when a member's `committed_spend_cents` moves, when
        a contract's `fee_outstanding_cents` is recomputed, or when a supplier's
        `performance_tier` is rewritten by a cascade, that row's `updated_at` is refreshed and its
        `version` increments."

        Design: Corner/Cross-Cutting Complexity Layers/member_agency_version_gate_refuses_a_stale_expectation_and_accepts_the_current_one
        """
        world = _verified_member_world(api)
        validate_error(
            _open_analysis(api, world, world["created_member"]["version"]),
            ApiErrorId.ERR_STALE_MEMBER_AGENCY_VERSION,
            412,
        )

        analysis = validate_success(
            _open_analysis(api, world, world["member"]["version"]), 201
        )

        assert analysis["status"] == "PENDING"
        assert analysis["member_agency_id"] == world["member"]["id"]
        assert analysis["determination"] is None
        assert analysis["authority_score"] is None
        assert read_analysis(api, analysis["id"])["status"] == "PENDING"
        after = read_member(api, world["member"]["id"])
        assert after["version"] == 3
        assert after["registration_status"] == "ACTIVE"


class TestMasterContractVersionGate:
    def test_03_the_version_rung_answers_before_the_renewal_arithmetic(self, api):
        """PRD §2.6: "`POST /coop/contract-amendments` requires a non-optional
        `expected_contract_version` field carrying the client's last observed `version` of the
        target `MasterContract`." PRD §2.6: "If it does not equal the contract's current
        `version`, the proposal is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412)." PRD
        §2.9: "All checks in the system are evaluated in the following fixed order; the first
        failing check produces the response and no later check runs." PRD §3.8: "For a `RENEWAL`,
        the requested end must genuinely extend the term: because a term is half-open, a
        `requested_term_end` equal to or earlier than the contract's `current_term_end` extends
        nothing and is `ERR_RENEWAL_TERM_NOT_EXTENDING`."

        Design: Corner/Cross-Cutting Complexity Layers/master_contract_version_gate_refuses_a_stale_expectation_on_amendment_creation
        """
        world = _executed_contract_world(api)
        stale_version = world["created_contract"]["version"]
        assert stale_version == 1
        assert world["contract"]["version"] == 2

        legal_term = _propose_renewal(api, world, stale_version, RENEWAL_TERM_END)
        illegal_term = _propose_renewal(api, world, stale_version, NON_EXTENDING_TERM_END)

        validate_error(legal_term, ApiErrorId.ERR_STALE_CONTRACT_VERSION, 412)
        validate_error(illegal_term, ApiErrorId.ERR_STALE_CONTRACT_VERSION, 412)
        assert (
            illegal_term.json()["data"]["error_id"]
            != ApiErrorId.ERR_RENEWAL_TERM_NOT_EXTENDING.value
        )
        _, meta = validate_paginated(api.list_contract_amendments(ADMIN_REVIEW))
        assert meta["total_count"] == 0

    def test_04_the_current_contract_version_carries_the_same_renewal_through(self, api):
        """PRD §3.8: "A new amendment starts in `status` `PROPOSED` with `proposed_by_user_id` set
        to the acting `X-User-ID`, and `effective_from` and `decided_by_user_id` null." PRD §3.8:
        "The `RENEWAL` branch sets the contract's `current_term_end` to `requested_term_end` and
        increments `renewals_used` by 1; already-determined authority opinions keep their frozen
        `expires_on` and are not extended." PRD §2.6: "If it does not equal the contract's current
        `version`, the proposal is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."

        Design: Corner/Cross-Cutting Complexity Layers/master_contract_version_gate_refuses_a_stale_expectation_on_amendment_creation
        """
        world = _executed_contract_world(api)
        validate_error(
            _propose_renewal(
                api, world, world["created_contract"]["version"], RENEWAL_TERM_END
            ),
            ApiErrorId.ERR_STALE_CONTRACT_VERSION,
            412,
        )

        amendment = validate_success(
            _propose_renewal(api, world, world["contract"]["version"], RENEWAL_TERM_END), 201
        )

        assert amendment["status"] == "PROPOSED"
        assert amendment["amendment_type"] == "RENEWAL"
        assert_instant(amendment["requested_term_end"], RENEWAL_TERM_END, "requested_term_end")
        assert amendment["effective_from"] is None
        assert amendment["decided_by_user_id"] is None
        _, meta = validate_paginated(api.list_contract_amendments(ADMIN_REVIEW))
        assert meta["total_count"] == 1
        contract = read_contract(api, world["contract"]["id"])
        assert_instant(contract["current_term_end"], BASE_TERM_END, "current_term_end")
        assert contract["renewals_used"] == 0


class TestPerformanceTierThresholds:
    def test_05_exactly_eighty_five_points_is_still_the_preferred_tier(self, api):
        """PRD §3.9: "`SUBSTANTIATE` moves `UNDER_INVESTIGATION → SUBSTANTIATED` and additionally
        requires the contract's supplier not to be `DEBARRED` (`ERR_SUPPLIER_DEBARRED`); it stamps
        `substantiated_at` with the current logical instant, sets `appeal_deadline_at` to fourteen
        days after `substantiated_at`, and writes `deduction_points` from the asserted `severity`
        — 2.50 points for `MINOR`, 7.50 for `MAJOR`, and 20.00 for `CRITICAL`." PRD §3.9:
        "`performance_tier` bands the score with two inclusive thresholds: 85.00 or more is
        `PREFERRED`, 70.00 or more but below 85.00 is `STANDARD`, and below 70.00 is `PROBATION` —
        so exactly 85.00 is `PREFERRED` and exactly 70.00 is `STANDARD`."

        Design: Corner/Cross-Cutting Complexity Layers/performance_tier_thresholds_fire_exactly_on_the_boundary_and_then_cascade
        """
        world = _complaint_world(api, ("MAJOR", "MAJOR"))

        first = _substantiate(api, world, 1)
        assert_score(first["deduction_points_total"], MAJOR_POINTS, "deduction_points_total")
        assert_score(first["performance_score"], 92.50, "performance_score")
        assert first["performance_tier"] == "PREFERRED"

        second = _substantiate(api, world, 2)

        assert_score(second["deduction_points_total"], 15.00, "deduction_points_total")
        assert_score(second["performance_score"], 85.00, "performance_score")
        assert second["performance_tier"] == "PREFERRED"
        assert second["qualification_status"] == "QUALIFIED"
        assert second["substantiated_complaint_count"] == 2

    def test_06_exactly_seventy_points_is_still_the_standard_tier_and_cascades_nothing(
        self, api
    ):
        """PRD §3.9: "`performance_score` is 100.00 minus that total, clamped to the closed range
        0.00 through 100.00, carried to two decimals with half-up rounding." PRD §3.9:
        "`performance_tier` bands the score with two inclusive thresholds: 85.00 or more is
        `PREFERRED`, 70.00 or more but below 85.00 is `STANDARD`, and below 70.00 is `PROBATION` —
        so exactly 85.00 is `PREFERRED` and exactly 70.00 is `STANDARD`." PRD §3.9: "Third, a
        `performance_tier` of `PROBATION` drives the supplier's standing `QUALIFIED → SUSPENDED`."

        Design: Corner/Cross-Cutting Complexity Layers/performance_tier_thresholds_fire_exactly_on_the_boundary_and_then_cascade
        """
        world = _complaint_world(api, ("MAJOR", "MAJOR", "MAJOR", "MAJOR"))

        third = _substantiate(api, world, 3)
        assert_score(third["performance_score"], 77.50, "performance_score")
        assert third["performance_tier"] == "STANDARD"

        fourth = _substantiate(api, world, 4)

        assert_score(fourth["deduction_points_total"], 30.00, "deduction_points_total")
        assert_score(fourth["performance_score"], 70.00, "performance_score")
        assert fourth["performance_tier"] == "STANDARD"
        assert fourth["qualification_status"] == "QUALIFIED"
        assert read_contract(api, world["contract"]["id"])["status"] == "ACTIVE"
        assert read_analysis(api, world["analysis"]["id"])["status"] == "DETERMINED"

    def test_07_a_single_minor_crossing_of_seventy_drives_the_whole_cascade(self, api):
        """PRD §3.9: "Substantiation then cascades five hops." PRD §3.9: "Third, a
        `performance_tier` of `PROBATION` drives the supplier's standing `QUALIFIED → SUSPENDED`."
        PRD §3.9: "Fourth, that suspension sets every `ACTIVE` master contract of the supplier to
        `SUSPENDED`." PRD §3.9: "Fifth, each of those contract suspensions voids that contract's
        `DETERMINED` authority opinions with `voided_reason` `CONTRACT_SUSPENDED`."

        Design: Corner/Cross-Cutting Complexity Layers/performance_tier_thresholds_fire_exactly_on_the_boundary_and_then_cascade
        """
        world = _complaint_world(api, ("MAJOR", "MAJOR", "MAJOR", "MAJOR", "MINOR"))
        fourth = _substantiate(api, world, 4)
        assert fourth["performance_tier"] == "STANDARD"

        final = _substantiate(api, world, 5)

        minor = world["complaints"][4]
        assert_score(
            validate_success(api.get_complaint(minor["id"], ADMIN_REVIEW))["deduction_points"],
            MINOR_POINTS,
            "deduction_points",
        )
        assert_score(final["deduction_points_total"], 32.50, "deduction_points_total")
        assert_score(final["performance_score"], 67.50, "performance_score")
        assert final["performance_tier"] == "PROBATION"
        assert final["qualification_status"] == "SUSPENDED"
        assert final["substantiated_complaint_count"] == 5
        assert read_contract(api, world["contract"]["id"])["status"] == "SUSPENDED"
        analysis = read_analysis(api, world["analysis"]["id"])
        assert analysis["status"] == "VOIDED"
        assert analysis["voided_reason"] == "CONTRACT_SUSPENDED"


class TestImmediateConsistency:
    def test_08_the_ledger_figures_a_write_produces_are_visible_on_the_next_read(self, api):
        """PRD §3.6: "Only now is `total_cents` added to the member's `committed_spend_cents`, and
        `chargeable_base_cents` added to the contract's `usage_chargeable_cents_total`." PRD §3.6:
        "`subtotal_cents` is `net_unit_price_cents` multiplied by `quantity`." PRD §3.6:
        "`admin_fee_cents` is `chargeable_base_cents` multiplied by `effective_fee_rate_bps` and
        divided by 10,000, rounded half up to a whole cent." PRD §3.7: "`ACCEPT` moves `SUBMITTED
        → ACCEPTED`, stamps `accepted_at` with the current logical instant, sets `fee_due_at` to
        thirty days after `accepted_at`, moves the parallel `fee_status` from `NOT_DUE` to `DUE`,
        and adds `reported_fee_cents` to both the contract's and the supplier's
        `fee_assessed_cents_total` before recomputing the contract's `fee_outstanding_cents`."

        Design: Corner/Consistency Model/every_write_is_immediately_visible_to_the_next_read_with_no_settling_period
        """
        world = setup_active_contract(api)
        member, analysis = setup_authorised_member(api, world)
        line = world["lines"][SKU_DISPENSER]

        order = validate_success(
            api.create_contract_usage(
                contract_usage_payload(
                    world["contract"]["id"],
                    member["id"],
                    line["id"],
                    analysis["id"],
                    quantity=2,
                ),
                make_member_headers(member["id"]),
            ),
            201,
        )

        assert order["status"] == "RECORDED"
        assert_cents(order["net_unit_price_cents"], 12500, "net_unit_price_cents")
        assert_cents(order["subtotal_cents"], QUANTITY_TWO_SUBTOTAL_CENTS, "subtotal_cents")
        assert_cents(order["admin_fee_cents"], QUANTITY_TWO_FEE_CENTS, "admin_fee_cents")
        assert_cents(order["total_cents"], QUANTITY_TWO_TOTAL_CENTS, "total_cents")
        assert_instant(order["ordered_at"], CLOCK_TERM_START, "ordered_at")

        assert_cents(
            read_member(api, member["id"])["committed_spend_cents"],
            QUANTITY_TWO_TOTAL_CENTS,
            "committed_spend_cents",
        )
        contract = read_contract(api, world["contract"]["id"])
        assert_cents(
            contract["usage_chargeable_cents_total"],
            QUANTITY_TWO_SUBTOTAL_CENTS,
            "usage_chargeable_cents_total",
        )
        assert_cents(contract["fee_assessed_cents_total"], 0, "fee_assessed_cents_total")
        rows, meta = validate_paginated(
            api.list_contract_usages(ADMIN_REVIEW, {"member_agency_id": member["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == order["id"]
