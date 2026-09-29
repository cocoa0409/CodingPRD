"""The water-right machine and the consumptive-use study machine.

PRD §3.2: "A right is perfected by an analyst or the adjudicator, moving it
`UNADJUDICATED → ACTIVE`."
"""
import pytest
from test_helpers import ApiErrorId, api_client, get_success_data, validate_error
from test_helpers.fixtures import (
    ANALYST,
    activate_right,
    add_use_record,
    certify_study,
    create_study,
    open_account,
    read_right,
    right_version,
    setup_base_right,
    setup_certified_right,
)
from test_helpers import validate_paginated

CLOCK = "2026-03-01T00:00:00Z"

TWO_HEADGATES = [
    {
        "max_rate_cfs": 5.000,
        "legal_description": "NE1/4 SEC 12 T3N R4E headgate",
        "stream_reach_code": "SNK-14-A",
        "stream_miles_from_headwater": 41.20,
    },
    {
        "max_rate_cfs": 3.000,
        "legal_description": "SW1/4 SEC 18 T3N R4E headgate",
        "stream_reach_code": "SNK-14-B",
        "stream_miles_from_headwater": 46.80,
    },
]


class TestPerfectingARight:
    """PRD §3.2 — activation is one call that moves the right, all of its
    headgates and its risk figures at once."""

    def test_activation_promotes_every_proposed_headgate_and_refreshes_risk(self):
        """PRD §3.2: "Perfecting the right also authorizes its infrastructure:
        every point of diversion on the right still in `PROPOSED` moves to
        `AUTHORIZED`, each such headgate's `version` bumped."

        Both headgates are promoted, not merely the first. PRD §3.2: "The forfeiture
        assessment is re-run, refreshing `forfeiture_risk_score`,
        `forfeiture_risk_band` and `consecutive_nonuse_years`". A single metered 2018
        record inside the 2016-2025 band leaves 2019 through 2025 idle, so the score
        is 63.00 for seven consecutive years plus 7.50 of underuse on a mean of
        300.000 against 400.00 authorized, less the 10.00 meter credit. Activation
        perfects the right but quantifies nothing, so PRD §3.1's "all four volume
        buckets at 0.00" still holds.

        Design: Corner/state_machines/sm_water_right_activate_authorizes_pods_and_refreshes_risk
        """
        bundle = setup_base_right(
            clock=CLOCK, use_years=(2018,), activate=False, pod_specs=TWO_HEADGATES
        )
        right_id = bundle["right"]["id"]
        assert right_version(right_id) == 2, (
            "creation is version 1 and appending the use record bumps it once"
        )

        right = activate_right(right_id)

        assert right["status"] == "ACTIVE"
        assert right["version"] == 3
        assert right["consecutive_nonuse_years"] == 7
        assert right["forfeiture_risk_score"] == pytest.approx(60.50, abs=0.01)
        assert right["forfeiture_risk_band"] == "ELEVATED"
        assert right["certified_hcu_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(0.00, abs=0.01)
        authorized, authorized_meta = validate_paginated(
            api_client.list_points_of_diversion(
                right_id, ANALYST, params={"status": "AUTHORIZED"}
            )
        )
        assert authorized_meta["total_count"] == 2
        assert {pod["id"] for pod in authorized} == {
            pod["id"] for pod in bundle["pods"]
        }
        _proposed, proposed_meta = validate_paginated(
            api_client.list_points_of_diversion(
                right_id, ANALYST, params={"status": "PROPOSED"}
            )
        )
        assert proposed_meta["total_count"] == 0

    def test_activation_turns_on_evidence_quality_not_evidence_presence(self):
        """PRD §3.2: "The single precondition is evidentiary: at least one
        beneficial-use record on the right must carry a `verification_source` of
        `METER` or `AERIAL_IMAGERY`. Affidavit-only evidence cannot perfect a right,
        and an attempt on such a right is `ERR_NO_VERIFIED_USE_EVIDENCE` (HTTP 422)."

        A right with no records at all and a right holding only an affidavit are
        refused alike; appending an aerial-imagery record opens the very transition
        that was refused twice. The affidavit year still counts as a used year for
        PRD §3.2's look-back — "a year counts as a used year when a record exists for
        it whose `reported_diversion_af` is at least 0.50 acre-feet" — so with 2022
        and 2023 both reported the longest idle run inside the 2016-2025 band is
        2016 through 2021.

        Design: Corner/state_machines/sm_water_right_activate_without_verified_evidence_rejected
        """
        bare = setup_base_right(clock=CLOCK, use_years=(), activate=False)
        affidavit = setup_base_right(
            clock=CLOCK,
            use_years=(2022,),
            reported_diversion_af=150.000,
            irrigated_acres=50.00,
            verification_source="AFFIDAVIT",
            activate=False,
            right_number="WR-2198-002",
            priority_date="1912-06-01T00:00:00Z",
            place_of_use_acres=60.00,
            authorized_diversion_af=200.00,
            authorized_rate_cfs=2.500,
        )

        no_records = api_client.activate_water_right(bare["right"]["id"], ANALYST)
        affidavit_only = api_client.activate_water_right(
            affidavit["right"]["id"], ANALYST
        )

        for response in (no_records, affidavit_only):
            validate_error(
                response,
                ApiErrorId.ERR_NO_VERIFIED_USE_EVIDENCE.value,
                expected_status=422,
            )
        untouched = read_right(bare["right"]["id"])
        assert untouched["status"] == "UNADJUDICATED"
        assert untouched["version"] == 1
        assert read_right(affidavit["right"]["id"])["status"] == "UNADJUDICATED"

        add_use_record(
            affidavit["right"]["id"],
            2023,
            reported_diversion_af=150.000,
            irrigated_acres=50.00,
            verification_source="AERIAL_IMAGERY",
        )
        perfected = activate_right(affidavit["right"]["id"])

        assert perfected["status"] == "ACTIVE"
        assert perfected["consecutive_nonuse_years"] == 6

    def test_undeclared_edges_out_of_active_are_refused_without_a_version_bump(self):
        """PRD §2.11: the validation ladder ends with "the domain-specific
        referential, uniqueness, concurrency, state, safety, temporal, constraint and
        fiscal families in that sequence."

        Activation exists only as `UNADJUDICATED → ACTIVE` (PRD §3.2) and
        reinstatement only "closes the cycle `ACTIVE → SUSPENDED → ACTIVE`" (PRD
        §3.2), so neither edge leaves an `ACTIVE` right and both are refused for
        state. Forfeiture is different: the edge exists, so the failure is the
        statutory gate of PRD §3.2 — "rejected with `ERR_FORFEITURE_NOT_ELIGIBLE`
        (HTTP 422) when `consecutive_nonuse_years` falls short of five" — at a
        longest idle run of four. The right's reinstatement gates are both satisfied
        at four idle years, which is what isolates the state failure.

        Design: Corner/state_machines/sm_water_right_invalid_transitions_rejected
        """
        bundle = setup_base_right(clock=CLOCK, use_years=(2020, 2025))
        right_id = bundle["right"]["id"]
        activated_version = read_right(right_id)["version"]
        assert read_right(right_id)["consecutive_nonuse_years"] == 4

        reactivate = api_client.activate_water_right(right_id, ANALYST)
        reinstate = api_client.reinstate_water_right(
            right_id, "no suspension to lift", ANALYST
        )
        forfeit = api_client.declare_forfeiture(right_id, "premature finding", ANALYST)

        validate_error(
            reactivate, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409
        )
        validate_error(
            reinstate, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409
        )
        validate_error(
            forfeit, ApiErrorId.ERR_FORFEITURE_NOT_ELIGIBLE.value, expected_status=422
        )
        final = read_right(right_id)
        assert final["status"] == "ACTIVE"
        assert final["version"] == activated_version

    def test_forfeited_is_sticky_and_locks_the_right_out_of_the_bank(self):
        """PRD §3.2: "the declaration is the deepest cascade in the service and
        `FORFEITED` is terminal and sticky."

        PRD §2.8: "a right already `FORFEITED` stays `FORFEITED`, because forfeiture
        is terminal and sticky", so activation, reinstatement and a second
        declaration all fail for state. A deposit naming the right fails on a
        different code: PRD §3.9 — "the source right's status must be `ACTIVE`,
        `ENCUMBERED` or `PARTIALLY_TRANSFERRED`, otherwise
        `ERR_RIGHT_NOT_TRANSFERABLE` (409)" — and it fails there even though the
        declared account version is the current one, so neither the version guard nor
        the empty transferable bucket is ever consulted.

        Design: Corner/state_machines/sm_water_right_forfeited_state_is_terminal_and_locked
        """
        bundle = setup_base_right(clock=CLOCK, use_years=(2018,), bank_enrolled=True)
        right_id = bundle["right"]["id"]
        account = open_account(bundle["claimant"]["id"])
        get_success_data(
            api_client.declare_forfeiture(
                right_id, "seven consecutive non-use years on the meter record", ANALYST
            )
        )
        forfeited_version = read_right(right_id)["version"]

        reactivate = api_client.activate_water_right(right_id, ANALYST)
        reinstate = api_client.reinstate_water_right(
            right_id, "attempt to revive a forfeited right", ANALYST
        )
        redeclare = api_client.declare_forfeiture(
            right_id, "second declaration", ANALYST
        )
        deposit_attempt = api_client.create_deposit(
            account["id"],
            {
                "water_right_id": right_id,
                "deposit_af": 1.00,
                "expected_water_bank_account_version": account["version"],
            },
            ANALYST,
        )

        for response in (reactivate, reinstate, redeclare):
            validate_error(
                response, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409
            )
        validate_error(
            deposit_attempt,
            ApiErrorId.ERR_RIGHT_NOT_TRANSFERABLE.value,
            expected_status=409,
        )
        right = read_right(right_id)
        assert right["status"] == "FORFEITED"
        assert right["version"] == forfeited_version
        for bucket in (
            "certified_hcu_af",
            "encumbered_af",
            "transferred_away_af",
            "transferable_af",
        ):
            assert right[bucket] == pytest.approx(0.00, abs=0.01)
        unchanged = get_success_data(
            api_client.get_water_bank_account(account["id"], ANALYST)
        )
        assert unchanged["deposited_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert unchanged["version"] == account["version"]


class TestCertificationReplacesRatherThanAccumulates:
    """PRD §2.7 — "Certification legitimately supersedes whatever study was
    previously certified and overwrites the right's certified volume, so a second
    certification is a valid product operation rather than an invalid transition — the
    stale-version check is the only thing that prevents a client from replacing a
    certification it never saw."

    One right carries three metered years of 300.000 AF. Study A spans 2023-2025 and
    is already certified at 195.00 AF; study B spans only 2024-2025.
    """

    def _certified_then_second_study(self):
        bundle = setup_certified_right(clock=CLOCK)
        bundle["second_study"] = get_success_data(
            create_study(bundle["right"]["id"], 2024, 2025)
        )
        return bundle

    def test_a_second_certification_supersedes_the_first_and_replaces_the_volume(self):
        """PRD §3.3: "a short-history haircut applies when `qualifying_year_count` is
        strictly fewer than three years, in which case `short_history_haircut_applied`
        is set true and the carried value is multiplied by 0.85".

        Two qualifying years average the same 195.000 AF, so the only difference is
        the haircut: 165.75 AF. PRD §2.9's identity holds on the replaced figure —
        `certified_hcu_af` reads 165.75 rather than the 390.00 an accumulating
        implementation would show — and the superseded study keeps its own historical
        figure untouched.

        Design: Corner/state_machines/sm_hcu_study_certification_supersedes_the_prior_certified_study
        """
        bundle = self._certified_then_second_study()
        version_before = right_version(bundle["right"]["id"])

        certified = certify_study(
            bundle["second_study"]["id"], bundle["right"]["id"]
        )

        assert certified["status"] == "CERTIFIED"
        assert certified["qualifying_year_count"] == 2
        assert certified["average_annual_cu_af"] == pytest.approx(195.000, abs=0.0005)
        assert certified["short_history_haircut_applied"] is True
        assert certified["transferable_cu_af"] == pytest.approx(165.75, abs=0.01)
        superseded = get_success_data(
            api_client.get_hcu_study(bundle["study"]["id"], ANALYST)
        )
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["transferable_cu_af"] == pytest.approx(195.00, abs=0.01)
        right = read_right(bundle["right"]["id"])
        assert right["certified_hcu_af"] == pytest.approx(165.75, abs=0.01)
        assert right["transferable_af"] == pytest.approx(165.75, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert right["version"] == version_before + 1

    def test_recertifying_the_same_study_is_refused_and_credits_nothing(self):
        """PRD §3.3: "Certifying anything that is not in `DRAFT` is
        `ERR_INVALID_STATE` (HTTP 409)."

        The declared version is deliberately the right's *current* version, so PRD
        §2.7's stale-version guard has nothing to catch — "the stale-version check is
        the only thing that prevents a client from replacing a certification it never
        saw" — and the replay is stopped by the study's own state instead. Neither row
        moves, so the right is not credited twice.

        Design: Corner/state_machines/sm_hcu_idempotency_recertification_rejected_without_double_ledger_move
        """
        bundle = setup_certified_right(clock=CLOCK)
        right_id = bundle["right"]["id"]
        version_before = right_version(right_id)
        study_version_before = bundle["study"]["version"]

        replay = api_client.certify_hcu_study(
            bundle["study"]["id"], version_before, ANALYST
        )

        validate_error(replay, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        right = read_right(right_id)
        assert right["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(195.00, abs=0.01)
        assert right["version"] == version_before
        study = get_success_data(
            api_client.get_hcu_study(bundle["study"]["id"], ANALYST)
        )
        assert study["status"] == "CERTIFIED"
        assert study["version"] == study_version_before
