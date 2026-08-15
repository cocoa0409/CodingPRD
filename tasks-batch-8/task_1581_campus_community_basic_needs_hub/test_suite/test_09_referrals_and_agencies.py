"""Partner-agency network: capacity admission and CRISIS overflow, SLA expiry
cascade, pause gating, warm handoff and category checks, capacity floor."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_client,
    create_agency,
    create_coordinator,
    create_counselor,
    create_referral_payload,
    create_screening_payload,
    create_sent_referral,
    get_success_data,
    run_sweeps,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import (
    make_benefits_counselor_headers,
    make_partner_agency_rep_headers,
)

ADMIN = TEST_USERS["hub_admin_headers"]


def _client_with_assessment(coord, alias, **assessment_overrides):
    defaults = dict(
        household_size=1, monthly_income_cents=50000, housing_status="STABLE",
        dependents_under_18=0, receives_snap=False,
        receives_childcare_subsidy=False, food_insecurity_score=1,
        consent_confidential=True,
    )
    defaults.update(assessment_overrides)
    return create_active_client(
        coord, assessment_overrides=defaults,
        client_overrides={"alias_name": alias},
    )[0]


class TestReferralSlaExpiryCascade:
    def _setup_full_agency(self):
        """Agency weekly_capacity 1; referral r1 for client 1 SENT at the
        2026-08-01T00:00:00Z default clock (ack_due_at 2026-08-06T00:00:00Z)."""
        _, coord = create_coordinator()
        c1 = _client_with_assessment(coord, "r1c", monthly_income_cents=70000)
        c2 = _client_with_assessment(
            coord, "r2c", household_size=2, monthly_income_cents=90000,
            housing_status="COST_BURDENED", dependents_under_18=1,
            food_insecurity_score=2,
        )
        agency = create_agency(
            "County SNAP Office", service_categories=["SNAP_APPLICATION"],
            weekly_capacity=1,
        )
        r1 = create_sent_referral(c1, agency, coord)
        return coord, c1, c2, agency, r1

    def test_capacity_full_blocks_then_expiry_frees_slot(self, api):
        """PRD §3.7: "An agency admits while its `active_referral_count` is
        below its `weekly_capacity`; a count already equal to capacity rejects
        with `ERR_AGENCY_CAPACITY_FULL`."
        PRD §3.7: "the expiry decrements the agency's counter, freeing
        capacity for subsequent referrals."

        Design: Difficulty/transitive_cascade/referral_sla_expiry_frees_agency_capacity
        """
        coord, _, c2, agency, _ = self._setup_full_agency()
        res = api_client.create_referral(
            c2["id"], create_referral_payload(agency["id"]), coord
        )
        validate_error(res, ApiErrorId.ERR_AGENCY_CAPACITY_FULL, expected_status=409)

        set_clock("2026-08-06T00:00:01Z")
        run_sweeps()
        r2 = validate_success(
            api_client.create_referral(c2["id"], create_referral_payload(agency["id"]), coord),
            201,
        )
        assert r2["status"] == "INITIATED", (
            "creation itself does not consume capacity"
        )

    def test_referral_expiry_decrements_agency_active_count(self, api):
        """PRD §3.7: "a `SENT` referral flips to `EXPIRED` strictly once the
        logical clock passes `ack_due_at` — exactly at the deadline it remains
        `SENT` — and the expiry decrements the agency's counter, freeing
        capacity for subsequent referrals."

        Design: Difficulty/transitive_cascade/referral_sla_expiry_frees_agency_capacity
        """
        coord, _, _, agency, r1 = self._setup_full_agency()
        set_clock("2026-08-06T00:00:01Z")
        sweep = run_sweeps()
        assert sweep["referrals_expired"] == 1

        r1_after = validate_success(api.get_referral(r1["id"], coord), 200)
        assert r1_after["status"] == "EXPIRED"
        agencies = validate_success(api.list_partner_agencies(ADMIN), 200)
        assert agencies[0]["active_referral_count"] == 0


class TestAgencyPauseGatesSend:
    def _setup_paused_agency_with_referral(self):
        _, coord = create_coordinator()
        client = _client_with_assessment(
            coord, "dale", household_size=2, monthly_income_cents=110000,
            housing_status="COST_BURDENED", dependents_under_18=1,
            food_insecurity_score=2,
        )
        agency = create_agency(
            "Housing Navigators", service_categories=["HOUSING_PLACEMENT"],
            weekly_capacity=10,
        )
        referral = get_success_data(
            api_client.create_referral(
                client["id"],
                create_referral_payload(agency["id"],
                                        service_category="HOUSING_PLACEMENT"),
                coord,
            )
        )
        validate_success(api_client.pause_agency(agency["id"], ADMIN), 200)
        return coord, client, agency, referral

    def test_send_rejected_while_agency_paused(self, api):
        """PRD §3.7: "a paused agency blocks new sends and resends with
        `ERR_AGENCY_NOT_ACTIVE`, while its existing `SENT` and `ACKNOWLEDGED`
        referrals remain actionable."

        Design: Difficulty/cross_entity_state_dependency/referral_send_gated_by_agency_pause_then_resume
        """
        coord, _, agency, referral = self._setup_paused_agency_with_referral()
        res = api.send_referral(referral["id"], coord)
        validate_error(res, ApiErrorId.ERR_AGENCY_NOT_ACTIVE, expected_status=409)
        after = validate_success(api.get_referral(referral["id"], coord), 200)
        assert after["status"] == "INITIATED"

    def test_send_succeeds_after_resume_with_fresh_deadline(self, api):
        """PRD §3.7: "Sending, by the same three hub roles, moves an
        `INITIATED` referral to `SENT` (any other state is
        `ERR_REFERRAL_NOT_ACTIONABLE`), requires the agency `ACTIVE` (else
        `ERR_AGENCY_NOT_ACTIVE`), stamps `sent_at` with the logical now, sets
        `ack_due_at` exactly 120 hours later — the agency's five-day
        acknowledgement deadline — and increments the agency's
        `active_referral_count` by one."

        Design: Difficulty/cross_entity_state_dependency/referral_send_gated_by_agency_pause_then_resume
        """
        coord, _, agency, referral = self._setup_paused_agency_with_referral()
        validate_success(api.resume_agency(agency["id"], ADMIN), 200)
        sent = validate_success(api.send_referral(referral["id"], coord), 200)
        assert sent["status"] == "SENT"
        assert sent["sent_at"] == "2026-08-01T00:00:00.000Z"
        assert sent["ack_due_at"] == "2026-08-06T00:00:00.000Z", (
            "exactly 120 hours after the send"
        )
        agencies = validate_success(api.list_partner_agencies(ADMIN), 200)
        assert agencies[0]["active_referral_count"] == 1


def test_warm_handoff_requires_walk_ins_accepted(api):
    """PRD §3.7: "requesting a `warm_handoff` — a staff-assisted, unscheduled
    introduction — requires the agency's `accepts_walk_ins` to be true (else
    `ERR_WALK_INS_NOT_ACCEPTED`)."
    PRD §3.7: "Configuration updates may change `weekly_capacity`,
    `service_categories`, or `accepts_walk_ins` ..."

    Design: Corner/validations/warm_handoff_requires_walk_ins_accepted
    """
    _, coord = create_coordinator()
    client = _client_with_assessment(
        coord, "wh", monthly_income_cents=40000, housing_status="UNSTABLE",
        food_insecurity_score=5,
    )
    agency = create_agency(
        "Shelter Inc", service_categories=["HOUSING_PLACEMENT"],
        weekly_capacity=5, accepts_walk_ins=False,
    )
    payload = create_referral_payload(
        agency["id"], service_category="HOUSING_PLACEMENT", warm_handoff=True
    )
    res = api.create_referral(client["id"], payload, coord)
    validate_error(res, ApiErrorId.ERR_WALK_INS_NOT_ACCEPTED, expected_status=422)

    validate_success(
        api.patch_partner_agency(agency["id"], {"accepts_walk_ins": True}, ADMIN), 200
    )
    referral = validate_success(api.create_referral(client["id"], payload, coord), 201)
    assert referral["status"] == "INITIATED"


def test_referral_category_not_in_agency_catalog(api):
    """PRD §3.7: "the `service_category` must be among the agency's
    `service_categories` (else `ERR_CATEGORY_NOT_SERVED`)".

    Design: Corner/validations/referral_category_not_in_agency_catalog
    """
    _, coord = create_coordinator()
    client = _client_with_assessment(coord, "cat", monthly_income_cents=40000)
    agency = create_agency(
        "SNAP Only", service_categories=["SNAP_APPLICATION"], weekly_capacity=5
    )
    res = api.create_referral(
        client["id"],
        create_referral_payload(agency["id"], service_category="LEGAL_AID"),
        coord,
    )
    validate_error(res, ApiErrorId.ERR_CATEGORY_NOT_SERVED, expected_status=422)


def test_patch_agency_capacity_below_active_rejected(api):
    """PRD §3.7: "capacity may not be set below the agency's current
    `active_referral_count` (else `ERR_CAPACITY_BELOW_ACTIVE`)."

    Design: Corner/validations/patch_agency_capacity_below_active_rejected
    """
    _, coord = create_coordinator()
    c1 = _client_with_assessment(coord, "p1", monthly_income_cents=40000)
    c2 = _client_with_assessment(coord, "p2", monthly_income_cents=45000)
    agency = create_agency(
        "Cap Test", service_categories=["SNAP_APPLICATION", "LEGAL_AID"],
        weekly_capacity=5,
    )
    create_sent_referral(c1, agency, coord)
    create_sent_referral(c2, agency, coord, service_category="LEGAL_AID")

    res = api.patch_partner_agency(agency["id"], {"weekly_capacity": 1}, ADMIN)
    validate_error(res, ApiErrorId.ERR_CAPACITY_BELOW_ACTIVE, expected_status=409)

    patched = validate_success(
        api.patch_partner_agency(agency["id"], {"weekly_capacity": 2}, ADMIN), 200
    )
    assert patched["weekly_capacity"] == 2, "capacity equal to the active count is admitted"


def test_crisis_referral_overflow_beyond_weekly_capacity(api):
    """PRD §3.7: "An agency admits while its `active_referral_count` is below
    its `weekly_capacity`; a count already equal to capacity rejects with
    `ERR_AGENCY_CAPACITY_FULL`. Clients whose current `risk_tier` is `CRISIS`
    receive overflow headroom: they are admitted while the active count is
    below the capacity multiplied by 1.2 and rounded down to a whole number;
    at or beyond that ceiling even `CRISIS` referrals are rejected with
    `ERR_AGENCY_CAPACITY_FULL`."

    Design: Corner/complexity_layers/crisis_referral_overflow_beyond_weekly_capacity
    """
    _, coord = create_coordinator()
    stable = _client_with_assessment(
        coord, "st", monthly_income_cents=400000, housing_status="STABLE",
        receives_snap=True, food_insecurity_score=0,
    )
    crisis = _client_with_assessment(
        coord, "cr", monthly_income_cents=0, housing_status="HOMELESS",
        food_insecurity_score=6,
    )
    assert validate_success(api.get_client(stable["id"], coord), 200)["risk_tier"] == "STABLE"
    assert validate_success(api.get_client(crisis["id"], coord), 200)["risk_tier"] == "CRISIS"

    agency = create_agency(
        "Overflow Co", service_categories=["SNAP_APPLICATION"], weekly_capacity=5
    )
    for _ in range(5):
        create_sent_referral(stable, agency, coord)

    res = api.create_referral(stable["id"], create_referral_payload(agency["id"]), coord)
    validate_error(res, ApiErrorId.ERR_AGENCY_CAPACITY_FULL, expected_status=409)

    r6 = validate_success(
        api.create_referral(crisis["id"], create_referral_payload(agency["id"]), coord),
        201,
    )
    validate_success(api.send_referral(r6["id"], coord), 200)

    res = api.create_referral(crisis["id"], create_referral_payload(agency["id"]), coord)
    validate_error(res, ApiErrorId.ERR_AGENCY_CAPACITY_FULL, expected_status=409)


def test_referral_and_screening_not_actionable_batch(api):
    """PRD §3.7: "Any of these agency actions from a non-admitting state is
    `ERR_REFERRAL_NOT_ACTIONABLE`."
    PRD §3.4: "Recording application assistance moves `SCREENED` to
    `APPLICATION_ASSISTED` and requires a `result_band` of `LIKELY_ELIGIBLE`
    or `POSSIBLY_ELIGIBLE` — assisting a `NOT_ELIGIBLE` screening, or
    assisting from any other state, is `ERR_SCREENING_NOT_ACTIONABLE`."

    Design: Corner/consistency_model/referral_and_screening_not_actionable_batch
    """
    _, coord = create_coordinator()
    _, couns = create_counselor()
    client = _client_with_assessment(
        coord, "na", monthly_income_cents=400000, housing_status="STABLE",
        receives_snap=True, food_insecurity_score=0,
    )
    agency = create_agency("NA Agency", service_categories=["LEGAL_AID"],
                           weekly_capacity=3)
    referral = get_success_data(
        api.create_referral(
            client["id"],
            create_referral_payload(agency["id"], service_category="LEGAL_AID"),
            coord,
        )
    )
    screening = validate_success(
        api.create_screening(client["id"], create_screening_payload("SNAP"), couns), 201
    )
    scored = validate_success(
        api.score_screening(
            screening["id"],
            make_benefits_counselor_headers(screening["counselor_id"]),
        ),
        200,
    )
    assert scored["result_band"] == "NOT_ELIGIBLE", (
        "receives_snap gate zeroes the SNAP score"
    )

    res = api.acknowledge_referral(
        referral["id"], make_partner_agency_rep_headers(agency["id"])
    )
    validate_error(res, ApiErrorId.ERR_REFERRAL_NOT_ACTIONABLE, expected_status=409)

    res = api.assist_screening(
        screening["id"], make_benefits_counselor_headers(screening["counselor_id"])
    )
    validate_error(res, ApiErrorId.ERR_SCREENING_NOT_ACTIONABLE, expected_status=409)
