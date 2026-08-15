"""Program cycle funds: appropriation identity, cap evaluation order, window
overlap semantics, and lifecycle gates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    adjust_appropriation,
    api_client,
    assert_funds_identity,
    create_application_payload,
    issue_notice,
    make_cycle,
    make_defect,
    make_draft_notice,
    make_owner,
    make_owner_headers,
    make_parcel,
    make_segment,
    setup_approved_application,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
FINANCE = TEST_USERS["finance_headers"]


def _approved_pair(appropriation):
    """Two owners/parcels, each with an issued notice and an APPROVED
    application of qty 100 (provisional 60000 each)."""
    cycle = make_cycle(appropriation_cents=appropriation)
    apps = []
    for idx, (name, pnum, addr) in enumerate(
            [("Ed Ash", "P-501", "5 Ash St"), ("Fern Fig", "P-502", "6 Fig St")]):
        owner = make_owner(name, addr)
        parcel = make_parcel(owner["id"], pnum, addr, "LOCAL")
        segment = make_segment(parcel["id"], f"S-50{idx + 1}-1")
        defect = make_defect(segment["id"], "VERTICAL_SEPARATION", 100,
                             measured_offset_inches=0.75)
        notice = issue_notice(
            make_draft_notice(parcel["id"], [defect["id"]])["id"])
        app = validate_success(api_client.create_application(
            create_application_payload(notice["id"], parcel["id"], cycle["id"],
                                       100), make_owner_headers(owner["id"])),
            201)
        app = validate_success(api_client.decide_application(
            app["id"], {"outcome": "APPROVE"}, COORD))
        apps.append(app)
    return cycle, apps


class TestCycleCreationAndLifecycle:
    def test_creation_applies_system_fields(self, api):
        """PRD §3.1: "At creation the cycle starts in `OPEN` status with
        `committed_cents` and `disbursed_cents` both zero, so `available_cents`
        equals the full appropriation."

        Design: Corner/entities/cycle_creation_applies_system_fields
        """
        cycle = validate_success(api.create_program_cycle(
            {"cycle_year": 2026, "window_start_date": "2026-01-01",
             "window_end_date": "2026-12-31", "appropriation_cents": 5000000},
            COORD), 201)
        assert cycle["status"] == "OPEN"
        assert cycle["version"] == 1
        assert cycle["committed_cents"] == 0
        assert cycle["disbursed_cents"] == 0
        assert cycle["available_cents"] == 5000000

    def test_close_from_open_rejected(self, api):
        """PRD §3.1: "Closing a cycle — `LOCKED → CLOSED` — is permitted only
        once no application in the cycle remains in `SUBMITTED`, `RETURNED`,
        `APPROVED`, or `OBLIGATED` review status"
        PRD §2.7: "The target resource must be in the state the requested
        transition requires, else the transition's specific state error (HTTP
        409): `ERR_INVALID_CYCLE_STATE`"

        Design: Corner/state_machines/cycle_close_from_open_rejected
        """
        cycle = make_cycle(appropriation_cents=1000000)
        assert cycle["status"] == "OPEN"
        resp = api.close_program_cycle(cycle["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_CYCLE_STATE)

    def test_close_with_open_applications_rejected(self, api):
        """PRD §3.1: "Closing a cycle — `LOCKED → CLOSED` — is permitted only
        once no application in the cycle remains in `SUBMITTED`, `RETURNED`,
        `APPROVED`, or `OBLIGATED` review status; otherwise the close fails with
        `ERR_CYCLE_HAS_OPEN_APPLICATIONS`."

        Design: Corner/errors/cycle_close_with_open_applications_rejected
        """
        bundle = setup_approved_application(
            parcel_number="P-T11", segment_code="S-T11-1",
            owner_name="Zoe Zizia", street_address="107 Zizia St",
            estimated_qty_sqft=50)
        cycle = validate_success(
            api.lock_program_cycle(bundle["cycle"]["id"], COORD))
        assert cycle["status"] == "LOCKED", \
            "lock blocks only new applications; it succeeds with in-flight work"

        resp = api.close_program_cycle(bundle["cycle"]["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_CYCLE_HAS_OPEN_APPLICATIONS)

    def test_appropriation_cut_below_obligations_rejected(self, api):
        """PRD §3.1: "Because the funds identity is invariant, a downward
        adjustment that would push `appropriation_cents` below the sum of
        `committed_cents` and `disbursed_cents` is rejected with
        `ERR_APPROPRIATION_BELOW_OBLIGATIONS`."

        Design: Corner/errors/appropriation_cut_below_obligations_rejected
        """
        bundle = setup_approved_application(
            parcel_number="P-T10", segment_code="S-T10-1",
            owner_name="Yan Yatay", street_address="106 Yatay St",
            defect_type="VERTICAL_SEPARATION", measured_offset_inches=0.75,
            area_sqft=100, estimated_qty_sqft=100)
        validate_success(
            api.obligate_application(bundle["application"]["id"], FINANCE))
        cycle = validate_success(
            api.get_program_cycle(bundle["cycle"]["id"], COORD))
        assert cycle["committed_cents"] == 60000
        cycle_v = cycle["version"]

        resp = adjust_appropriation(bundle["cycle"]["id"], -10_000_000, cycle_v)
        validate_error(resp, ApiErrorId.ERR_APPROPRIATION_BELOW_OBLIGATIONS)

        adjusted = validate_success(
            adjust_appropriation(bundle["cycle"]["id"], -9_940_000, cycle_v))
        assert adjusted["appropriation_cents"] == 60000
        assert adjusted["available_cents"] == 0, \
            "equality with committed + disbursed is allowed"
        assert_funds_identity(adjusted)


class TestCapEvaluationOrder:
    def test_second_approved_obligates_first(self, api):
        """PRD §2.8: "There is no priority among approved applications by
        approval order — every capacity check is evaluated strictly at request
        time against the cycle's current balances, which already reflect every
        earlier obligation and release in request order."

        Design: Difficulty/combinatorial_formula/obligation_order_determines_cap_outcome
        """
        cycle, apps = _approved_pair(appropriation=100000)
        app1, app2 = apps

        a2 = validate_success(api.obligate_application(app2["id"], FINANCE))
        assert a2["review_status"] == "OBLIGATED", \
            "the second-approved application obligates first and succeeds"

        resp = api.obligate_application(app1["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_CAP_EXCEEDED)

        cycle = validate_success(api.get_program_cycle(cycle["id"], COORD))
        assert cycle["committed_cents"] == 60000
        assert cycle["available_cents"] == 40000

    def test_first_approved_first_also_succeeds(self, api):
        """PRD §2.8: "There is no priority among approved applications by
        approval order — every capacity check is evaluated strictly at request
        time against the cycle's current balances, which already reflect every
        earlier obligation and release in request order."

        Design: Difficulty/combinatorial_formula/obligation_order_determines_cap_outcome
        """
        cycle, apps = _approved_pair(appropriation=100000)
        app1, app2 = apps

        a1 = validate_success(api.obligate_application(app1["id"], FINANCE))
        assert a1["review_status"] == "OBLIGATED", \
            "reversing the request order reverses the outcome: no approval priority"

        resp = api.obligate_application(app2["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_CAP_EXCEEDED)


class TestCapEqualityBoundary:
    def test_provisional_equal_to_appropriation_obligates(self, api):
        """PRD §3.6: "requires the sum of `committed_cents` and this
        application's `provisional_award_cents` not to exceed
        `appropriation_cents` — equality is allowed — else
        `ERR_PROGRAM_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/program_cap_equality_boundary
        """
        bundle = setup_approved_application(
            appropriation_cents=60000, parcel_number="P-1501",
            segment_code="S-1501-1", owner_name="Quinn Quince",
            street_address="17 Quince St", defect_type="VERTICAL_SEPARATION",
            measured_offset_inches=0.75, area_sqft=100, estimated_qty_sqft=100)
        assert bundle["application"]["provisional_award_cents"] == 60000

        app = validate_success(
            api.obligate_application(bundle["application"]["id"], FINANCE))
        assert app["review_status"] == "OBLIGATED", \
            "provisional exactly equal to the appropriation obligates cleanly"

        cycle = validate_success(
            api.get_program_cycle(bundle["cycle"]["id"], COORD))
        assert cycle["committed_cents"] == 60000
        assert cycle["available_cents"] == 0
        assert_funds_identity(cycle)

    def test_one_cent_over_remaining_fails(self, api):
        """PRD §3.6: "requires the sum of `committed_cents` and this
        application's `provisional_award_cents` not to exceed
        `appropriation_cents` — equality is allowed — else
        `ERR_PROGRAM_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/program_cap_equality_boundary
        """
        bundle1 = setup_approved_application(
            appropriation_cents=60000, parcel_number="P-1501",
            segment_code="S-1501-1", owner_name="Quinn Quince",
            street_address="17 Quince St", defect_type="VERTICAL_SEPARATION",
            measured_offset_inches=0.75, area_sqft=100, estimated_qty_sqft=100)
        validate_success(
            api.obligate_application(bundle1["application"]["id"], FINANCE))

        owner2 = make_owner("Rosa Rose", "18 Rose St")
        parcel2 = make_parcel(owner2["id"], "P-1502", "18 Rose St", "LOCAL")
        segment2 = make_segment(parcel2["id"], "S-1502-1", length_ft=4)
        defect2 = make_defect(segment2["id"], "VERTICAL_SEPARATION", 10,
                              measured_offset_inches=0.75)
        notice2 = issue_notice(
            make_draft_notice(parcel2["id"], [defect2["id"]])["id"])
        app2 = validate_success(api.create_application(
            create_application_payload(notice2["id"], parcel2["id"],
                                       bundle1["cycle"]["id"], 10),
            make_owner_headers(owner2["id"])), 201)
        assert app2["provisional_award_cents"] == 6000
        validate_success(api.decide_application(
            app2["id"], {"outcome": "APPROVE"}, COORD))

        resp = api.obligate_application(app2["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_CAP_EXCEEDED)


class TestObligateWithdrawCompensation:
    def test_obligate_moves_funds_forward(self, api):
        """PRD §3.6: "A successful obligation moves `payment_status` from
        `UNFUNDED` to `RESERVED`, adds the provisional award to the cycle's
        `committed_cents`, recomputes `available_cents`, and increments both
        entities' versions."
        PRD §2.8: "After every mutation the identity must hold exactly:
        `appropriation_cents` equals the sum of `committed_cents`,
        `disbursed_cents`, and `available_cents`."

        Design: Difficulty/compensating_invariant/obligate_then_withdraw_restores_funds
        """
        bundle = setup_approved_application(
            parcel_number="P-2200", segment_code="S-2200-1",
            owner_name="Xena Xyla", street_address="35 Xyla St",
            defect_type="VERTICAL_SEPARATION", measured_offset_inches=0.75,
            area_sqft=100, estimated_qty_sqft=100)
        validate_success(
            api.obligate_application(bundle["application"]["id"], FINANCE))
        cycle = validate_success(
            api.get_program_cycle(bundle["cycle"]["id"], COORD))
        assert cycle["committed_cents"] == 60000
        assert cycle["available_cents"] == 9_940_000
        assert_funds_identity(cycle)

    def test_withdraw_restores_funds_identity(self, api):
        """PRD §3.5: "withdrawal from `OBLIGATED` additionally flips
        `payment_status` from `RESERVED` to `RELEASED` and subtracts the
        `provisional_award_cents` from the cycle's `committed_cents`,
        incrementing both the application's and the cycle's `version`."
        PRD §2.8: "After every mutation the identity must hold exactly:
        `appropriation_cents` equals the sum of `committed_cents`,
        `disbursed_cents`, and `available_cents`."

        Design: Difficulty/compensating_invariant/obligate_then_withdraw_restores_funds
        """
        bundle = setup_approved_application(
            parcel_number="P-2200", segment_code="S-2200-1",
            owner_name="Xena Xyla", street_address="35 Xyla St",
            defect_type="VERTICAL_SEPARATION", measured_offset_inches=0.75,
            area_sqft=100, estimated_qty_sqft=100)
        validate_success(
            api.obligate_application(bundle["application"]["id"], FINANCE))

        app = validate_success(api.withdraw_application(
            bundle["application"]["id"],
            make_owner_headers(bundle["owner"]["id"])))
        assert app["review_status"] == "WITHDRAWN"
        assert app["payment_status"] == "RELEASED"

        cycle = validate_success(
            api.get_program_cycle(bundle["cycle"]["id"], COORD))
        assert cycle["committed_cents"] == 0
        assert cycle["disbursed_cents"] == 0
        assert cycle["available_cents"] == 10_000_000, \
            "the obligate/withdraw pair conserves the funds identity"
        assert_funds_identity(cycle)


class TestCycleWindowClosedInterval:
    def test_shared_endpoint_counts_as_overlap(self, api):
        """PRD §3.1: "The window is a closed interval: `window_end_date` must
        fall strictly after `window_start_date`, and windows of different cycles
        may not overlap at all — one cycle's end date coinciding exactly with
        another's start date already counts as an overlap and is rejected with
        `ERR_CYCLE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/cycle_window_closed_interval_overlap
        """
        make_cycle(appropriation_cents=1000000, cycle_year=2026,
                   window_start_date="2026-01-01", window_end_date="2026-12-31")
        resp = api.create_program_cycle(
            {"cycle_year": 2027, "window_start_date": "2026-12-31",
             "window_end_date": "2027-06-30", "appropriation_cents": 1000000},
            COORD)
        validate_error(resp, ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP)

    def test_day_after_endpoint_is_disjoint(self, api):
        """PRD §3.1: "windows of different cycles may not overlap at all — one
        cycle's end date coinciding exactly with another's start date already
        counts as an overlap and is rejected with `ERR_CYCLE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/cycle_window_closed_interval_overlap
        """
        make_cycle(appropriation_cents=1000000, cycle_year=2026,
                   window_start_date="2026-01-01", window_end_date="2026-12-31")
        cycle2 = validate_success(api.create_program_cycle(
            {"cycle_year": 2027, "window_start_date": "2027-01-01",
             "window_end_date": "2027-12-31", "appropriation_cents": 1000000},
            COORD), 201)
        assert cycle2["status"] == "OPEN", \
            "starting the day after the prior end is disjoint under closed semantics"
