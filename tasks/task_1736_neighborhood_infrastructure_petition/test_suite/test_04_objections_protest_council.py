"""Objections, protest weight, council resolutions, and the remand loop
(PRD §3.4, §3.5, §2.7, §2.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_objection_window,
    create_district,
    create_parcel,
    create_resolution_payload,
    district_version,
    drive_to_council_review,
    drive_to_hearing_scheduled,
    drive_to_objection_window,
    drive_to_scoping,
    file_objection,
    get_district,
    list_district_assessments,
    make_property_owner_headers,
    record_hearing_held,
    record_resolution,
    schedule_hearing,
    set_clock,
    submit_and_approve_estimate,
    api_client,
    validate_error,
    validate_success,
)

CLERK = TEST_USERS["clerk_headers"]
FINANCE = TEST_USERS["finance_headers"]
COUNCIL = TEST_USERS["council_headers"]

FOUR_PARCEL_FRONTAGES = (50.0, 75.0, 25.0, 50.0)


def _council_review_with_overruled_pair(name, prefix):
    """District in COUNCIL_REVIEW with OVERRULED objections on P-001 and P-004
    (50.00 + 50.00 = 100.00 of 200.00 ft -> protest exactly 50.00%)."""
    ctx = drive_to_objection_window(
        name, frontages=FOUR_PARCEL_FRONTAGES, prefix=prefix,
        methodology="FRONT_FOOT", contract_price_cents=10000000,
        contingency_cents=500000, venue=f"{name} Venue",
        sign_slice=(0, 1, 3),
    )
    hearing_id = ctx["hearing"]["id"]
    p1 = ctx["pairs"][0][1]
    p4 = ctx["pairs"][3][1]
    o1 = ctx["pairs"][0][0]
    o4 = ctx["pairs"][3][0]
    ob1 = file_objection(hearing_id, p1["id"], o1["id"], grounds="g1")
    ob4 = file_objection(hearing_id, p4["id"], o4["id"], grounds="g4")
    for ob in (ob1, ob4):
        validate_success(api_client.start_objection_review(ob["id"], CLERK))
        validate_success(api_client.overrule_objection(ob["id"], CLERK))
    ctx["district"] = close_objection_window(ctx["district"]["id"],
                                             at="2026-08-31T00:00:00Z")
    return ctx


class TestObjectionSustainCascade:
    def _setup_under_review(self):
        ctx = drive_to_objection_window(
            "TC1", frontages=FOUR_PARCEL_FRONTAGES, prefix="tc1",
            methodology="FRONT_FOOT", contract_price_cents=10000000,
            contingency_cents=500000, venue="City Hall Room A",
            sign_slice=(0, 1, 3),
        )
        p3 = ctx["pairs"][2][1]
        o3 = ctx["pairs"][2][0]
        ob = file_objection(ctx["hearing"]["id"], p3["id"], o3["id"],
                            grounds="wrong frontage")
        validate_success(api_client.start_objection_review(ob["id"], CLERK))
        return ctx, ob, p3

    def test_sustain_removes_parcel_and_its_assessment(self, api):
        """PRD §3.4: "Sustaining an objection fires a three-hop cascade. The
        parcel itself is removed, `ACTIVE` → `REMOVED`. Its `PRELIMINARY`
        assessment is removed with it, `PRELIMINARY` → `REMOVED`."

        Design: Difficulty/transitive_cascade/objection_sustain_reallocation_cascade
        """
        ctx, ob, p3 = self._setup_under_review()
        p3_assessment_id = next(
            a["id"] for a in list_district_assessments(ctx["district"]["id"])
            if a["parcel_id"] == p3["id"]
        )
        validate_success(api_client.sustain_objection(ob["id"], CLERK))

        parcel = validate_success(api_client.get_parcel(p3["id"], CLERK))
        assert parcel["status"] == "REMOVED", "hop 1: parcel removed"

        assessment = validate_success(
            api_client.get_assessment(p3_assessment_id, FINANCE)
        )
        assert assessment["status"] == "REMOVED", (
            "hop 2: the parcel's PRELIMINARY assessment removed with it"
        )

    def test_sustain_reallocates_sibling_roll_and_district_totals(self, api):
        """PRD §3.4: "Then the preliminary allocation re-runs over the
        remaining `ACTIVE` non-exempt parcels against the same locked estimate
        total — same methodology variant, same four-decimal rate rule, same
        remainder order — rewriting every surviving sibling's
        `preliminary_amount_cents`, while the district's `total_frontage_ft`
        and `eligible_parcel_count` are recomputed over the shrunken roll."

        Design: Difficulty/transitive_cascade/objection_sustain_reallocation_cascade
        """
        ctx, ob, p3 = self._setup_under_review()
        validate_success(api_client.sustain_objection(ob["id"], CLERK))

        # Locked total 10,500,000 over 175.00 ft -> rate 60,000.0000 cents/ft.
        assessments = list_district_assessments(ctx["district"]["id"])
        surviving = [a for a in assessments if a["status"] != "REMOVED"]
        amounts = [a["preliminary_amount_cents"] for a in surviving]
        assert amounts == [3000000, 4500000, 3000000], (
            f"hop 3: siblings re-allocated at the new rate, got {amounts}"
        )
        assert sum(amounts) == 10500000, "total conserved across the cascade"

        district = get_district(ctx["district"]["id"])
        assert district["total_frontage_ft"] == pytest.approx(175.00)
        assert district["eligible_parcel_count"] == 3


class TestObjectionWorkflowGates:
    def test_sustain_from_filed_rejected(self, api):
        """PRD §3.4: "Deciding it — in either direction — requires the
        objection be `UNDER_REVIEW` (`ERR_OBJECTION_NOT_UNDER_REVIEW`)".

        Design: Corner/state_machines/sm_objection_sustain_from_filed_rejected
        """
        ctx = drive_to_objection_window("SOS", prefix="sos", venue="SOS Room")
        owner, parcel = ctx["pairs"][0]
        ob = file_objection(ctx["hearing"]["id"], parcel["id"], owner["id"], "g")
        validate_error(
            api_client.sustain_objection(ob["id"], CLERK),
            ApiErrorId.ERR_OBJECTION_NOT_UNDER_REVIEW,
        )

    def test_objection_withdraw_after_adjudication_rejected(self, api):
        """PRD §3.4: "The filing owner may also withdraw their objection, but
        only while it is `FILED` (`ERR_OBJECTION_NOT_FILED` once it has moved
        on; `ERR_NOT_RESOURCE_OWNER` for anyone but the filer)".

        Design: Corner/state_machines/sm_objection_withdraw_after_adjudication_rejected
        """
        ctx = drive_to_objection_window("SOW", prefix="sow", venue="SOW Room")
        owner, parcel = ctx["pairs"][0]
        ob = file_objection(ctx["hearing"]["id"], parcel["id"], owner["id"], "g")
        validate_success(api_client.start_objection_review(ob["id"], CLERK))
        validate_success(api_client.overrule_objection(ob["id"], CLERK))
        validate_error(
            api_client.withdraw_objection(ob["id"], make_property_owner_headers(owner["id"])),
            ApiErrorId.ERR_OBJECTION_NOT_FILED,
        )

    def test_duplicate_objection_rejected(self, api):
        """PRD §3.4: "A parcel carries at most one live objection per hearing:
        a second filing while one stands `FILED` or `UNDER_REVIEW` meets
        `ERR_DUPLICATE_OBJECTION`."

        Design: Corner/errors/err_duplicate_objection_triggered
        """
        ctx = drive_to_objection_window("EDO", prefix="edo", venue="EDO Room")
        owner, parcel = ctx["pairs"][0]
        file_objection(ctx["hearing"]["id"], parcel["id"], owner["id"], "first")
        validate_error(
            api_client.create_objection(
                {"hearing_id": ctx["hearing"]["id"], "parcel_id": parcel["id"],
                 "grounds": "second"},
                make_property_owner_headers(owner["id"]),
            ),
            ApiErrorId.ERR_DUPLICATE_OBJECTION,
        )

    def test_unresolved_objections_block_window_close(self, api):
        """PRD §3.4: "requires that no objection of the district remain `FILED`
        or `UNDER_REVIEW` (`ERR_UNRESOLVED_OBJECTIONS`)".

        Design: Corner/errors/err_unresolved_objections_block_window_close
        """
        ctx = drive_to_objection_window("EUO", prefix="euo", venue="EUO Room")
        owner, parcel = ctx["pairs"][0]
        file_objection(ctx["hearing"]["id"], parcel["id"], owner["id"], "g")
        set_clock("2026-08-31T00:00:00Z")  # past the window end
        validate_error(
            api_client.close_objection_window(ctx["district"]["id"], CLERK),
            ApiErrorId.ERR_UNRESOLVED_OBJECTIONS,
        )

    def test_close_window_at_exact_window_end_rejected(self, api):
        """PRD §3.4: "requires the current time be strictly past
        `objection_window_end` — at or before that instant the close is
        premature and fails with `ERR_OBJECTION_WINDOW_STILL_OPEN`".

        Design: Corner/errors/err_objection_window_still_open_triggered
        """
        ctx = drive_to_objection_window("EOS", prefix="eos", venue="EOS Room")
        # objection_window_end = 2026-08-15 + 15 days = 2026-08-30T00:00:00Z.
        set_clock("2026-08-30T00:00:00Z")
        validate_error(
            api_client.close_objection_window(ctx["district"]["id"], CLERK),
            ApiErrorId.ERR_OBJECTION_WINDOW_STILL_OPEN,
        )

    def test_close_window_requires_objection_window_state(self, api):
        """PRD §3.4: "Closing requires the district be in `OBJECTION_WINDOW`
        (`ERR_DISTRICT_NOT_IN_OBJECTION_WINDOW`)". PRD §2.8: "Every endpoint
        applies its checks in a single fixed priority order, and the first
        failure wins".

        Design: Corner/errors/err_close_window_requires_objection_window
        """
        ctx = drive_to_hearing_scheduled("ECW", prefix="ecw", venue="ECW Room")
        validate_error(
            api_client.close_objection_window(ctx["district"]["id"], CLERK),
            ApiErrorId.ERR_DISTRICT_NOT_IN_OBJECTION_WINDOW,
        )


class TestObjectionReferentialAndTemporal:
    def test_objection_parcel_not_in_district(self, api):
        """PRD §3.4: "the parcel must belong to the hearing's district
        (`ERR_PARCEL_NOT_IN_DISTRICT`)". PRD §2.8: "`ERR_PARCEL_NOT_IN_DISTRICT`
        when a signature's or objection's parcel lies outside the petition's or
        hearing's district".

        Design: Corner/errors/err_parcel_not_in_district_triggered
        """
        ctx = drive_to_objection_window("EPN-A", prefix="epna", venue="EPN-A Room")
        owner = ctx["pairs"][0][0]
        # Second district holding another parcel of the same owner.
        other = create_district(name="EPN-B")
        foreign = create_parcel(other["id"], owner["id"], parcel_number="X-001",
                                frontage_ft=10.0)
        set_clock("2026-08-20T00:00:00Z")  # window still open
        validate_error(
            api_client.create_objection(
                {"hearing_id": ctx["hearing"]["id"], "parcel_id": foreign["id"],
                 "grounds": "g"},
                make_property_owner_headers(owner["id"]),
            ),
            ApiErrorId.ERR_PARCEL_NOT_IN_DISTRICT,
        )

    def test_window_closed_beats_parcel_district_mismatch(self, api):
        """PRD §2.8: "Every endpoint applies its checks in a single fixed
        priority order, and the first failure wins — later checks are never
        evaluated once an earlier one has failed." PRD §2.8: "10. **Temporal
        windows** (HTTP 422): `ERR_OBJECTION_WINDOW_CLOSED` ... 11.
        **Referential coherence** (HTTP 422): `ERR_PARCEL_NOT_IN_DISTRICT`".

        Design: Difficulty/priority_pair_validation_conflict/objection_window_closed_beats_parcel_district_mismatch
        """
        ctx = drive_to_objection_window("PC2", frontages=FOUR_PARCEL_FRONTAGES,
                                        prefix="pc2", methodology="FRONT_FOOT",
                                        contract_price_cents=10000000,
                                        contingency_cents=500000,
                                        venue="City Hall Room A",
                                        sign_slice=(0, 1, 3))
        owner = ctx["pairs"][0][0]
        other = create_district(name="PC2-OTHER")
        foreign = create_parcel(other["id"], owner["id"], parcel_number="X-001",
                                frontage_ft=10.0)
        set_clock("2026-08-31T00:00:00Z")  # window end 2026-08-30 has passed
        validate_error(
            api_client.create_objection(
                {"hearing_id": ctx["hearing"]["id"], "parcel_id": foreign["id"],
                 "grounds": "too high"},
                make_property_owner_headers(owner["id"]),
            ),
            ApiErrorId.ERR_OBJECTION_WINDOW_CLOSED,
        )

    def test_window_closed_filing_creates_no_objection(self, api):
        """PRD §2.8: "Every endpoint applies its checks in a single fixed
        priority order, and the first failure wins — later checks are never
        evaluated once an earlier one has failed." PRD §3.4: "During the window
        — while the current time is on or before `objection_window_end`;
        filings after that instant fail with `ERR_OBJECTION_WINDOW_CLOSED`".

        Design: Difficulty/priority_pair_validation_conflict/objection_window_closed_beats_parcel_district_mismatch
        """
        ctx = drive_to_objection_window("PC2", frontages=FOUR_PARCEL_FRONTAGES,
                                        prefix="pc2", methodology="FRONT_FOOT",
                                        contract_price_cents=10000000,
                                        contingency_cents=500000,
                                        venue="City Hall Room A",
                                        sign_slice=(0, 1, 3))
        owner = ctx["pairs"][0][0]
        other = create_district(name="PC2-OTHER")
        foreign = create_parcel(other["id"], owner["id"], parcel_number="X-001",
                                frontage_ft=10.0)
        set_clock("2026-08-31T00:00:00Z")
        validate_error(
            api_client.create_objection(
                {"hearing_id": ctx["hearing"]["id"], "parcel_id": foreign["id"],
                 "grounds": "too high"},
                make_property_owner_headers(owner["id"]),
            ),
            ApiErrorId.ERR_OBJECTION_WINDOW_CLOSED,
        )
        body = validate_success(
            api_client.list_district_objections(ctx["district"]["id"], CLERK)
        )
        assert body == [], "a rejected filing must not create an Objection resource"


class TestProtestWeightedVoting:
    def test_protest_exactly_fifty_forces_supermajority_three_votes_fail(self, api):
        """PRD §3.5: "When the protest percentage stands at 50.00 or higher, an
        approval motion requires a supermajority of 4 votes; below that mark, a
        simple majority of 3 suffices." PRD §3.5: "A failed `APPROVE`, or an
        adopted `REJECT`, abandons the district — it moves to `ABANDONED`".

        Design: Difficulty/boundary_precision_check/protest_weight_exactly_fifty_percent_requires_supermajority
        """
        ctx = _council_review_with_overruled_pair("B2-A", "b2a")
        district = get_district(ctx["district"]["id"])
        assert district["protest_frontage_pct"] == pytest.approx(50.00), (
            "overruled objections cover 100.00 of 200.00 ft"
        )
        resolution = record_resolution(district["id"], motion="APPROVE",
                                       votes_for=3, votes_against=2)
        assert resolution["required_votes_snapshot"] == 4, (
            ">= 50.00 triggers the supermajority rule"
        )
        assert resolution["outcome"] == "FAILED"
        assert get_district(district["id"])["status"] == "ABANDONED"

    def test_protest_exactly_fifty_supermajority_four_votes_adopt(self, api):
        """PRD §3.5: "an `APPROVE` motion is adopted exactly when `votes_for`
        reaches the required threshold". PRD §3.5: "An adopted `APPROVE` moves
        the district to `APPROVED` and levies the roll".

        Design: Difficulty/boundary_precision_check/protest_weight_exactly_fifty_percent_requires_supermajority
        """
        ctx = _council_review_with_overruled_pair("B2-B", "b2b")
        district = get_district(ctx["district"]["id"])
        assert district["protest_frontage_pct"] == pytest.approx(50.00)
        resolution = record_resolution(district["id"], motion="APPROVE",
                                       votes_for=4, votes_against=1)
        assert resolution["required_votes_snapshot"] == 4
        assert resolution["outcome"] == "ADOPTED"
        assert get_district(district["id"])["status"] == "APPROVED"

    def test_protest_excludes_withdrawn_objection(self, api):
        """PRD §3.4: "`WITHDRAWN` and `SUSTAINED` objections contribute zero to
        the numerator". PRD §3.5: "When the protest percentage stands at 50.00
        or higher, an approval motion requires a supermajority of 4 votes;
        below that mark, a simple majority of 3 suffices."

        Design: Corner/calculations/c_protest_excludes_withdrawn
        """
        ctx = drive_to_objection_window(
            "PWS", frontages=FOUR_PARCEL_FRONTAGES, prefix="pws",
            methodology="FRONT_FOOT", contract_price_cents=10000000,
            contingency_cents=500000, venue="PWS Room", sign_slice=(0, 1, 3),
        )
        hearing_id = ctx["hearing"]["id"]
        o1, p1 = ctx["pairs"][0]
        o3, p3 = ctx["pairs"][2]
        ob1 = file_objection(hearing_id, p1["id"], o1["id"], grounds="withdraw me")
        ob3 = file_objection(hearing_id, p3["id"], o3["id"], grounds="keep me")
        validate_success(
            api_client.withdraw_objection(ob1["id"], make_property_owner_headers(o1["id"]))
        )
        validate_success(api_client.start_objection_review(ob3["id"], CLERK))
        validate_success(api_client.overrule_objection(ob3["id"], CLERK))
        close_objection_window(ctx["district"]["id"], at="2026-08-31T00:00:00Z")

        district = get_district(ctx["district"]["id"])
        assert district["protest_frontage_pct"] == pytest.approx(12.50), (
            "only the OVERRULED objection (25.00 of 200.00 ft) counts"
        )
        resolution = record_resolution(district["id"], motion="APPROVE",
                                       votes_for=3, votes_against=2)
        assert resolution["required_votes_snapshot"] == 3
        assert resolution["outcome"] == "ADOPTED"
        assert get_district(district["id"])["status"] == "APPROVED"


class TestRemandLoop:
    def _drive_first_cycle(self):
        ctx = drive_to_council_review("RM", prefix="rm", venue="City Hall Room R")
        return ctx

    def _remand(self, district_id):
        return record_resolution(district_id, motion="REMAND",
                                 votes_for=3, votes_against=0)

    def _rebuild_cycle(self, district_id, contract_cents, hearing_date, venue,
                       held_at, close_at):
        submit_and_approve_estimate(district_id, contract_cents, 0)
        hearing = schedule_hearing(district_id, hearing_date, venue)
        record_hearing_held(hearing["id"], at=held_at)
        close_objection_window(district_id, at=close_at)
        return hearing

    def test_remand_cycle_loops_twice_with_cascade(self, api):
        """PRD §3.5: "An adopted `REMAND` sends the district back to `SCOPING`
        with the full remand cascade: `remand_count` increases by one, the
        `CLOSED` hearing becomes `SUPERSEDED`, every `PRELIMINARY` assessment
        becomes `SUPERSEDED`, the currently `APPROVED` estimate becomes
        `SUPERSEDED`, and `approved_estimate_id` is cleared".

        Design: Difficulty/non_linear_state_machine/district_remand_cycle_with_cap
        """
        ctx = self._drive_first_cycle()
        district_id = ctx["district"]["id"]
        first_estimate = ctx["estimate"]

        self._remand(district_id)
        after_first = get_district(district_id)
        assert after_first["status"] == "SCOPING"
        assert after_first["remand_count"] == 1

        self._rebuild_cycle(district_id, 105000, "2026-09-15T00:00:00Z",
                            "City Hall Room R", "2026-09-15T10:00:00Z",
                            "2026-10-01T00:00:00Z")
        self._remand(district_id)
        after_second = get_district(district_id)
        assert after_second["status"] == "SCOPING"
        assert after_second["remand_count"] == 2

        # The first cycle's approved estimate was superseded by the remand.
        stale = validate_success(api_client.get_cost_estimate(first_estimate["id"], CLERK))
        assert stale["status"] == "SUPERSEDED"

    def test_third_remand_rejected_at_cap(self, api):
        """PRD §3.5: "a `REMAND` motion is adopted with at least 3 votes in
        favor, provided the district's `remand_count` is still below its hard
        cap of 2 — a remand attempted when two remands have already been
        executed is rejected outright with `ERR_REMAND_LIMIT_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/district_remand_cycle_with_cap
        """
        ctx = self._drive_first_cycle()
        district_id = ctx["district"]["id"]
        self._remand(district_id)
        self._rebuild_cycle(district_id, 105000, "2026-09-15T00:00:00Z",
                            "City Hall Room R", "2026-09-15T10:00:00Z",
                            "2026-10-01T00:00:00Z")
        self._remand(district_id)
        self._rebuild_cycle(district_id, 107000, "2026-10-15T00:00:00Z",
                            "City Hall Room R", "2026-10-15T10:00:00Z",
                            "2026-10-31T00:00:00Z")

        assert get_district(district_id)["remand_count"] == 2
        version = district_version(district_id)
        validate_error(
            api_client.create_resolution(
                create_resolution_payload(district_id=district_id,
                                          expected_district_version=version,
                                          motion="REMAND", votes_for=3,
                                          votes_against=0),
                COUNCIL,
            ),
            ApiErrorId.ERR_REMAND_LIMIT_EXCEEDED,
        )
        after = get_district(district_id)
        assert after["status"] == "COUNCIL_REVIEW", "no state drift on the rejected motion"
        assert after["remand_count"] == 2


class TestResolutionRules:
    def test_resolution_votes_range(self, api):
        """PRD §3.5: "The council seats five members: each tally must lie
        between 0 and 5 inclusive and their sum may not exceed 5, with
        violations rejected as `ERR_INVALID_REQUEST`."

        Design: Corner/validations/v_resolution_votes_range
        """
        ctx = drive_to_council_review("VRV", prefix="vrv", venue="VRV Room")
        district_id = ctx["district"]["id"]
        version = district_version(district_id)
        validate_error(
            api_client.create_resolution(
                create_resolution_payload(district_id=district_id,
                                          expected_district_version=version,
                                          motion="APPROVE", votes_for=6,
                                          votes_against=0),
                COUNCIL,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
        )
        validate_error(
            api_client.create_resolution(
                create_resolution_payload(district_id=district_id,
                                          expected_district_version=version,
                                          motion="APPROVE", votes_for=3,
                                          votes_against=3),
                COUNCIL,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

    def test_failed_reject_motion_keeps_council_review(self, api):
        """PRD §3.5: "A failed `REJECT` and a failed `REMAND` both leave the
        district in `COUNCIL_REVIEW`, where further resolutions may be
        recorded." PRD §3.5: "a `REJECT` motion is adopted with at least 3
        votes in favor".

        Design: Corner/state_machines/sm_failed_reject_motion_keeps_council_review
        """
        ctx = drive_to_council_review("SFR", prefix="sfr", venue="SFR Room")
        district_id = ctx["district"]["id"]
        resolution = record_resolution(district_id, motion="REJECT",
                                       votes_for=2, votes_against=3)
        assert resolution["outcome"] == "FAILED"
        assert get_district(district_id)["status"] == "COUNCIL_REVIEW"

        record_resolution(district_id, motion="REMAND", votes_for=3, votes_against=0)
        after = get_district(district_id)
        assert after["status"] == "SCOPING"
        assert after["remand_count"] == 1

    def test_resolution_requires_council_review(self, api):
        """PRD §3.5: "Recording is possible only while the district sits in
        `COUNCIL_REVIEW` (`ERR_DISTRICT_NOT_IN_COUNCIL_REVIEW`)".

        Design: Corner/errors/err_resolution_requires_council_review
        """
        ctx = drive_to_scoping("ERC", prefix="erc")
        submit_and_approve_estimate(ctx["district"]["id"], 100000, 0)
        version = district_version(ctx["district"]["id"])
        validate_error(
            api_client.create_resolution(
                create_resolution_payload(district_id=ctx["district"]["id"],
                                          expected_district_version=version,
                                          motion="APPROVE", votes_for=5,
                                          votes_against=0),
                COUNCIL,
            ),
            ApiErrorId.ERR_DISTRICT_NOT_IN_COUNCIL_REVIEW,
        )

    def test_finance_cannot_record_resolution(self, api):
        """PRD §2.1: "When the supplied role is not among the roles an endpoint
        admits, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)." PRD §4: "POST `/resolutions` | Record a council resolution
        (OCC on district) | CouncilPresident".

        Design: Corner/rbac/r_finance_cannot_record_resolution
        """
        ctx = drive_to_council_review("RFR", prefix="rfr", venue="RFR Room")
        version = district_version(ctx["district"]["id"])
        validate_error(
            api_client.create_resolution(
                create_resolution_payload(district_id=ctx["district"]["id"],
                                          expected_district_version=version,
                                          motion="APPROVE", votes_for=3,
                                          votes_against=0),
                FINANCE,
            ),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE,
        )

    def test_resolution_stale_district_version_rejected(self, api):
        """PRD §2.7: "Recording a council resolution likewise requires
        `expected_district_version`." and "a mismatch with the parent's current
        `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)". PRD §2.8:
        "a stale version is detected before any state, temporal, or fiscal rule
        runs."

        Design: Corner/cross_cutting_complexity_layers/x_occ_resolution_stale_district_version
        """
        ctx = drive_to_council_review("XOC2", prefix="xoc2", venue="XOC2 Room")
        district_id = ctx["district"]["id"]
        version = district_version(district_id)

        adopted = record_resolution(district_id, motion="APPROVE", votes_for=3,
                                    votes_against=0)
        assert adopted["outcome"] == "ADOPTED"

        # The adopted resolution advanced the district version; replaying the
        # pre-approval version is stale even though the state gate (district no
        # longer in COUNCIL_REVIEW) would also reject the write.
        validate_error(
            api_client.create_resolution(
                create_resolution_payload(district_id=district_id,
                                          expected_district_version=version,
                                          motion="APPROVE", votes_for=3,
                                          votes_against=0),
                COUNCIL,
            ),
            ApiErrorId.ERR_STALE_VERSION,
        )
