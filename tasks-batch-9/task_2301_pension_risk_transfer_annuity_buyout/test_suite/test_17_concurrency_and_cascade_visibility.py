"""Optimistic concurrency on the three supersede-style writes, and cascade visibility.

Each test builds its own preconditions through declared endpoints against a
freshly launched server, and reads the parent's `version` back from the API
rather than assuming one.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_errors import (
    ERR_STALE_PARTICIPANT_VERSION,
    ERR_STALE_PLAN_VERSION,
    ERR_STALE_TRANCHE_VERSION,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.types import (
    AddressStatus,
    BenefitAuditStatus,
    Cohort,
    DataReadinessFlag,
    DataStatus,
    MortalityStatus,
    ParticipantAuditStatus,
    ParticipantStatus,
    TransferStatus,
    TrancheStatus,
)

#: The single-participant tranche every funding scenario below is built on.
_LOCKED_PREMIUM_CENTS = 11800000
_DELIVERED_GROSS_CENTS = 12000000


def _retiree_spec() -> fixtures.ParticipantSpec:
    """One retiree whose recomputed benefit matches the stated figure exactly."""
    return fixtures.ParticipantSpec(
        stated_monthly_benefit_cents=60000,
        cohort=Cohort.RETIREE_IN_PAY.value,
        credited_service_months=320,
    )


def _locked_tranche(api) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A buyout tranche locked at a known premium, with one clean retiree assigned."""
    fixtures.set_clock(api, CLOCK_EPOCH)
    authorized = fixtures.build_authorized_plan(api, participants=[_retiree_spec()])
    insurer = fixtures.create_insurer(api)
    tranche = fixtures.build_locked_tranche(
        api,
        authorized.plan_id,
        authorized.participants,
        [fixtures.QuoteSpec(insurer_id=insurer["id"], premium_cents=_LOCKED_PREMIUM_CENTS)],
    )
    assert tranche["tranche_status"] == TrancheStatus.PRICING_LOCKED.value
    assert tranche["locked_premium_cents"] == _LOCKED_PREMIUM_CENTS
    return authorized.participants[0], tranche


def _drafted_tranche(api) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A drafted tranche and the clean retiree that is eligible for it."""
    fixtures.set_clock(api, CLOCK_EPOCH)
    authorized = fixtures.build_authorized_plan(api, participants=[_retiree_spec()])
    tranche = fixtures.create_tranche(api, authorized.plan_id, Cohort.RETIREE_IN_PAY.value)
    return authorized.participants[0], tranche


class TestStaleExpectedPlanVersion:
    """`expected_plan_version` guards the valuation update against a stale client."""

    def test_consistency_stale_expected_plan_version_refuses_a_valuation_update(
        self, api, sponsor, actuary
    ):
        """A second valuation update replaying the version the client first observed is refused with ERR_STALE_PLAN_VERSION and changes nothing.

        Three write operations legitimately supersede something the client may not have seen, and all three are therefore guarded by optimistic concurrency control against the parent entity's `version`. In each case the version field is a required, non-optional member of the request body, and a mismatch against the parent's current `version` is rejected before any state is examined or changed.
        A `POST /prt/plans/{id}/valuation-updates` request must carry `expected_plan_version` holding the client's last observed `version` of the target `PensionPlan`. If the plan's current `version` differs, the update is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412).
        Its accounting figure, `accounting_funded_status_bp`, is 0 whenever `total_liability_cents` is 0; otherwise it is `plan_assets_cents` multiplied by 10,000 and rounded half up over `total_liability_cents`, so a fully funded plan reads 10000 basis points.

        Design: Corner/cross_cutting/stale_expected_plan_version_refuses_a_valuation_update
        """
        fixtures.set_clock(api, CLOCK_EPOCH)
        plan = fixtures.create_plan(api)
        observed_version = plan["version"]

        first = validate_success(
            api.post_valuation_update(
                plan["id"],
                factories.valuation_update_payload(observed_version, plan_assets_cents=95000000),
                actuary,
            ),
            200,
        )
        assert first["plan_assets_cents"] == 95000000
        assert first["version"] == observed_version + 1
        assert first["accounting_funded_status_bp"] == constants.funded_status_bp(
            95000000, first["total_liability_cents"]
        )

        validate_error(
            api.post_valuation_update(
                plan["id"],
                factories.valuation_update_payload(observed_version, plan_assets_cents=80000000),
                sponsor,
            ),
            ERR_STALE_PLAN_VERSION,
        )

        after = fixtures.read_plan(api, plan["id"])
        assert after["plan_assets_cents"] == 95000000
        assert after["version"] == first["version"]
        assert after["accounting_funded_status_bp"] == first["accounting_funded_status_bp"]

    def test_consistency_refreshed_plan_version_admits_the_replayed_valuation_update(
        self, api, sponsor, actuary
    ):
        """The refused update leaves the plan's version untouched, so replaying the very same body against the refreshed version is accepted and advances the version by exactly one.

        A `POST /prt/plans/{id}/valuation-updates` request must carry `expected_plan_version` holding the client's last observed `version` of the target `PensionPlan`. If the plan's current `version` differs, the update is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412).
        All resources except one additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation of the resource, and `version`, an integer that starts at 1 and increments by one on every mutation.

        Design: Corner/cross_cutting/stale_expected_plan_version_refuses_a_valuation_update
        """
        fixtures.set_clock(api, CLOCK_EPOCH)
        plan = fixtures.create_plan(api)
        observed_version = plan["version"]

        first = validate_success(
            api.post_valuation_update(
                plan["id"],
                factories.valuation_update_payload(observed_version, plan_assets_cents=95000000),
                actuary,
            ),
            200,
        )

        stale_body = factories.valuation_update_payload(
            observed_version, plan_assets_cents=80000000
        )
        validate_error(
            api.post_valuation_update(plan["id"], stale_body, sponsor), ERR_STALE_PLAN_VERSION
        )

        replay = dict(stale_body, expected_plan_version=first["version"])
        accepted = validate_success(api.post_valuation_update(plan["id"], replay, sponsor), 200)
        assert accepted["plan_assets_cents"] == 80000000
        assert accepted["version"] == first["version"] + 1
        assert accepted["accounting_funded_status_bp"] == constants.funded_status_bp(
            80000000, accepted["total_liability_cents"]
        )


class TestStaleExpectedParticipantVersion:
    """`expected_participant_version` guards the create-with-supersede audit."""

    def test_consistency_stale_expected_participant_version_refuses_a_benefit_audit(
        self, api, actuary
    ):
        """An address confirmation bumps the participant's version, so an audit carrying the pre-confirmation version is refused with ERR_STALE_PARTICIPANT_VERSION and mints no audit at all.

        A `POST /prt/participants/{id}/benefit-audits` request must carry `expected_participant_version` holding the client's last observed `version` of the target `ParticipantRecord`. If the participant's current `version` differs, the creation is rejected with `ERR_STALE_PARTICIPANT_VERSION` (HTTP 412). A new audit supersedes every prior audit of that participant, so a stale client would discard an audit computed from earnings or service data that has since been corrected.
        In each case the version field is a required, non-optional member of the request body, and a mismatch against the parent's current `version` is rejected before any state is examined or changed.

        Design: Corner/cross_cutting/stale_expected_participant_version_refuses_a_benefit_audit
        """
        fixtures.set_clock(api, CLOCK_EPOCH)
        plan = fixtures.create_plan(api)
        participant = fixtures.create_participant(api, plan["id"])
        observed_version = participant["version"]
        assert participant["benefit_audit_status"] == ParticipantAuditStatus.NOT_AUDITED.value

        confirmed = fixtures.confirm_address(api, participant["id"])
        assert confirmed["address_status"] == AddressStatus.CONFIRMED.value
        assert confirmed["version"] == observed_version + 1

        validate_error(
            api.create_benefit_audit(
                participant["id"], factories.benefit_audit_payload(observed_version), actuary
            ),
            ERR_STALE_PARTICIPANT_VERSION,
        )

        rows, meta = validate_paginated(api.list_benefit_audits(participant["id"], actuary))
        assert rows == []
        assert meta["total_count"] == 0

        after = fixtures.read_participant(api, participant["id"])
        assert after["benefit_audit_status"] == ParticipantAuditStatus.NOT_AUDITED.value
        assert after["version"] == confirmed["version"]

    def test_consistency_refreshed_participant_version_admits_the_benefit_audit(self, api, actuary):
        """Replaying the audit against the version the address confirmation produced is accepted, mints audit sequence 1 with a zero variance, and opens the audit on the participant.

        A `POST /prt/participants/{id}/benefit-audits` request must carry `expected_participant_version` holding the client's last observed `version` of the target `ParticipantRecord`. If the participant's current `version` differs, the creation is rejected with `ERR_STALE_PARTICIPANT_VERSION` (HTTP 412).
        The new audit is assigned an `audit_sequence` equal to the participant's prior audit count plus one, a 1-based ordinal that serves as the deterministic tie-break whenever "the latest audit" must be identified, and it snapshots the participant's `stated_monthly_benefit_cents` as it stood at audit creation.
        When the absolute value of `variance_cents` is at most 500 cents, the audit lands in `PASSED` — the bound is inclusive, so a variance of exactly five dollars in either direction passes — the participant's `audited_monthly_benefit_cents` is left untouched, the participant's `benefit_audit_status` becomes `AUDIT_OPEN` and stays there until the audit is resolved, and the participant's `data_confidence_score` and `data_status` are recomputed.

        Design: Corner/cross_cutting/stale_expected_participant_version_refuses_a_benefit_audit
        """
        fixtures.set_clock(api, CLOCK_EPOCH)
        plan = fixtures.create_plan(api)
        participant = fixtures.create_participant(api, plan["id"])
        confirmed = fixtures.confirm_address(api, participant["id"])

        audit = validate_success(
            api.create_benefit_audit(
                participant["id"],
                factories.benefit_audit_payload(confirmed["version"]),
                actuary,
            ),
            201,
        )
        assertions.assert_audit_shape(audit)
        assert audit["audit_sequence"] == 1
        assert audit["stated_monthly_benefit_cents"] == participant["stated_monthly_benefit_cents"]
        assertions.assert_audit_arithmetic(
            audit,
            participant["final_average_monthly_earnings_cents"],
            participant["credited_service_months"],
        )
        assert audit["variance_cents"] == 0
        assert audit["audit_status"] == BenefitAuditStatus.PASSED.value

        after = fixtures.read_participant(api, participant["id"])
        assert after["benefit_audit_status"] == ParticipantAuditStatus.AUDIT_OPEN.value
        assert (
            after["audited_monthly_benefit_cents"]
            == participant["audited_monthly_benefit_cents"]
        )
        assert after["version"] == confirmed["version"] + 1
        assertions.assert_data_confidence_consistent(after)


class TestStaleExpectedTrancheVersion:
    """`expected_tranche_version` guards the supersede-style asset transfer."""

    def test_consistency_stale_expected_tranche_version_refuses_a_second_asset_transfer(
        self, api, sponsor
    ):
        """The first cash delivery bumps the tranche's version, so a second delivery replaying the pre-delivery version is refused with ERR_STALE_TRANCHE_VERSION and supersedes nothing.

        A `POST /prt/tranches/{id}/asset-transfers` request must carry `expected_tranche_version` holding the client's last observed `version` of the target `BuyoutTranche`. If the tranche's current `version` differs, the creation is rejected with `ERR_STALE_TRANCHE_VERSION` (HTTP 412). A new transfer supersedes any transfer still awaiting the insurer's answer on that tranche, so a stale client would supersede a composition it never saw and fund against an out-of-date `locked_premium_cents`.
        A cash delivery suffers only a wire fee of 8 basis points applied to `gross_value_cents` and rounded half up over 10,000, and its `transfer_expense_cents` is that wire fee alone — no haircut, no per-lot component.
        A delivery that survives starts in `INITIATED` with `insurer_decision`, `rejection_reason`, and `settled_at` null, and bumps the tranche's `version`.

        Design: Corner/cross_cutting/stale_expected_tranche_version_refuses_a_second_asset_transfer
        """
        _participant, tranche = _locked_tranche(api)
        observed_version = tranche["version"]

        first = validate_success(
            api.create_asset_transfer(
                tranche["id"],
                factories.cash_transfer_payload(observed_version, _DELIVERED_GROSS_CENTS),
                sponsor,
            ),
            201,
        )
        assertions.assert_transfer_shape(first)
        assertions.assert_cash_crediting(first)
        assert first["transfer_expense_cents"] == constants.cash_transfer_expense(
            _DELIVERED_GROSS_CENTS
        )
        assert first["credited_value_cents"] == constants.cash_credited_value(
            _DELIVERED_GROSS_CENTS
        )
        assert first["shortfall_cents"] == 0
        assert first["transfer_status"] == TransferStatus.INITIATED.value

        after_first = fixtures.read_tranche(api, tranche["id"])
        assert after_first["version"] == observed_version + 1

        validate_error(
            api.create_asset_transfer(
                tranche["id"],
                factories.in_kind_transfer_payload(observed_version, _DELIVERED_GROSS_CENTS, 2),
                sponsor,
            ),
            ERR_STALE_TRANCHE_VERSION,
        )

        rows, meta = validate_paginated(api.list_asset_transfers(tranche["id"], sponsor))
        assert meta["total_count"] == 1
        assert assertions.ids_of(rows) == [first["id"]]
        assert rows[0]["transfer_status"] == TransferStatus.INITIATED.value

    def test_consistency_refreshed_tranche_version_supersedes_the_first_asset_transfer(
        self, api, sponsor
    ):
        """Replaying the refused in-kind delivery against the refreshed version is accepted, and the superseded cash delivery stays visible in the tranche's transfer history.

        A `POST /prt/tranches/{id}/asset-transfers` request must carry `expected_tranche_version` holding the client's last observed `version` of the target `BuyoutTranche`. If the tranche's current `version` differs, the creation is rejected with `ERR_STALE_TRANCHE_VERSION` (HTTP 412).
        Any delivery still awaiting the carrier's answer on the same tranche transitions `INITIATED → SUPERSEDED` before the new one is created, bumping its own `version`.
        An in-kind delivery suffers two frictions: a valuation haircut of 125 basis points applied to `gross_value_cents` and rounded half up over 10,000, plus a per-lot custody fee of 25,000 cents for each security lot delivered. Its `transfer_expense_cents` is the haircut plus the custody fees.

        Design: Corner/cross_cutting/stale_expected_tranche_version_refuses_a_second_asset_transfer
        """
        _participant, tranche = _locked_tranche(api)
        observed_version = tranche["version"]

        first = validate_success(
            api.create_asset_transfer(
                tranche["id"],
                factories.cash_transfer_payload(observed_version, _DELIVERED_GROSS_CENTS),
                sponsor,
            ),
            201,
        )

        stale_body = factories.in_kind_transfer_payload(
            observed_version, _DELIVERED_GROSS_CENTS, 2
        )
        validate_error(
            api.create_asset_transfer(tranche["id"], stale_body, sponsor),
            ERR_STALE_TRANCHE_VERSION,
        )

        refreshed = fixtures.read_tranche(api, tranche["id"])
        replay = dict(stale_body, expected_tranche_version=refreshed["version"])
        second = validate_success(api.create_asset_transfer(tranche["id"], replay, sponsor), 201)
        assertions.assert_in_kind_crediting(second)
        assert second["transfer_expense_cents"] == constants.in_kind_transfer_expense(
            _DELIVERED_GROSS_CENTS, 2
        )
        assert second["credited_value_cents"] == constants.in_kind_credited_value(
            _DELIVERED_GROSS_CENTS, 2
        )
        assert second["shortfall_cents"] == 0
        assert second["transfer_status"] == TransferStatus.INITIATED.value

        rows, meta = validate_paginated(api.list_asset_transfers(tranche["id"], sponsor))
        assert meta["total_count"] == 2
        assert sorted(assertions.ids_of(rows)) == sorted([first["id"], second["id"]])
        superseded = assertions.require_by_id(rows, first["id"])
        assert superseded["transfer_status"] == TransferStatus.SUPERSEDED.value
        assert superseded["version"] == first["version"] + 1
        assert (
            assertions.require_by_id(rows, second["id"])["transfer_status"]
            == TransferStatus.INITIATED.value
        )

class TestImmediateCascadeVisibility:
    """The response that causes a cascade already carries the cascade's result."""

    def test_consistency_assignment_response_carries_the_recomputed_tranche(
        self, api, administrator
    ):
        """The participant-assignment response is the tranche itself, already carrying the recomputed count, both liabilities and the readiness flag.

        When an operation changes more than one entity, every affected entity is mutated in the same request, each bumping its own `version`.
        Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
        A successful assignment recomputes the tranche's `assigned_participant_count`, `accounting_liability_cents`, `settlement_liability_cents`, and `data_readiness_flag`, and bumps both the participant's and the tranche's `version`.
        The tranche's `accounting_liability_cents` is the sum of those participants' `accounting_liability_cents` and its `settlement_liability_cents` is the sum of their `settlement_liability_cents`, both 0 when the population is empty; because the per-participant amounts are already rounded, no further rounding happens at the tranche level.
        The `data_readiness_flag` is `BLOCKED` if the population is empty, `BLOCKED` if any assigned participant's `data_status` is anything other than `CLEAN`, `BLOCKED` if any assigned participant's `mortality_status` is anything other than `ALIVE_CONFIRMED`, `BLOCKED` if any assigned participant's `benefit_audit_status` is outside `PASSED_CLOSED` and `CORRECTED`, and `READY` only when none of those conditions holds.

        Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
        """
        participant, tranche = _drafted_tranche(api)
        assertions.assert_tranche_shape(tranche)
        assert tranche["assigned_participant_count"] == 0
        assert tranche["accounting_liability_cents"] == 0
        assert tranche["settlement_liability_cents"] == 0
        assert tranche["data_readiness_flag"] == DataReadinessFlag.BLOCKED.value

        assert participant["data_status"] == DataStatus.CLEAN.value
        assert participant["mortality_status"] == MortalityStatus.ALIVE_CONFIRMED.value
        assert participant["benefit_audit_status"] == ParticipantAuditStatus.PASSED_CLOSED.value

        written = validate_success(
            api.post_participant_assignment(
                tranche["id"],
                factories.participant_assignment_payload(participant["id"]),
                administrator,
            ),
            200,
        )
        assert written["id"] == tranche["id"]
        assert written["assigned_participant_count"] == 1
        assert written["accounting_liability_cents"] == participant["accounting_liability_cents"]
        assert written["settlement_liability_cents"] == participant["settlement_liability_cents"]
        assert written["data_readiness_flag"] == DataReadinessFlag.READY.value
        assert written["version"] == tranche["version"] + 1

    def test_consistency_tranche_reread_matches_the_assignment_response(self, api, administrator):
        """A re-read taken right after the assignment reports exactly the figures the write response reported, and the participant end of the same cascade is visible too.

        When an operation changes more than one entity, every affected entity is mutated in the same request, each bumping its own `version`.
        A successful assignment recomputes the tranche's `assigned_participant_count`, `accounting_liability_cents`, `settlement_liability_cents`, and `data_readiness_flag`, and bumps both the participant's and the tranche's `version`.
        A `PlanAdministrator` then assigns participants one at a time by supplying a `participant_id`, moving that participant `IN_PLAN → ASSIGNED` and setting its `tranche_id`.

        Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
        """
        participant, tranche = _drafted_tranche(api)

        written = validate_success(
            api.post_participant_assignment(
                tranche["id"],
                factories.participant_assignment_payload(participant["id"]),
                administrator,
            ),
            200,
        )

        reread = fixtures.read_tranche(api, tranche["id"])
        for field in (
            "assigned_participant_count",
            "accounting_liability_cents",
            "settlement_liability_cents",
            "data_readiness_flag",
            "tranche_status",
            "version",
            "updated_at",
        ):
            assert reread[field] == written[field], field

        moved = fixtures.read_participant(api, participant["id"])
        assert moved["participant_status"] == ParticipantStatus.ASSIGNED.value
        assert moved["tranche_id"] == tranche["id"]
        assert moved["version"] == participant["version"] + 1
