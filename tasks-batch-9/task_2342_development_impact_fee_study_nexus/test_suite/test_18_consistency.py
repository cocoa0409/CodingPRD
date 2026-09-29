"""Immediate consistency, read literally: the write's own response is already the
settled record, and the read that follows it neither changes nor completes anything."""

from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import fixtures, get_success_data
from test_helpers.fixtures import ANALYST, DEVELOPER

ECHOED_FIELDS = (
    "id",
    "version",
    "updated_at",
    "assessment_status",
    "collection_status",
    "reassessment_required",
    "gross_assessed_cents",
    "credit_applied_cents",
    "admin_charge_cents",
    "net_due_cents",
    "paid_cents",
    "default_penalty_cents",
    "assessed_at",
    "reassessed_at",
    "co_issued_at",
    "pinned_fee_study_id",
    "pinned_fee_study_version",
    "assessed_lines",
)


def test_the_assessment_response_already_carries_every_derived_total(api):
    """A large fraction of this system's state is derived, and none of it is cached
    stale. Consistency is immediate: by the time a write returns, every derived field
    its effects reach has been recomputed and every record whose derived fields
    changed has had its `version` incremented and its `updated_at` refreshed.
    Assessment records `pinned_fee_study_id` and `pinned_fee_study_version` from the
    effective study, stamps `assessed_at` on a first assessment and `reassessed_at`
    on a re-run, sets `reassessment_required` to false, and increments the
    application's `version`. `assessed_lines` is the ordered array of per-line
    objects, in facility category `code` ascending order, each object carrying
    `facility_category_id`, `facility_category_code`, `demand_units`,
    `line_gross_cents`, `line_credit_cents`, `line_admin_cents` and `line_net_cents`.
    For each assessed line, that line's `demand_units` are added to the owning
    category's `committed_demand_units` and that category's `version` is incremented.
    When `collection_trigger` is `PERMIT`, `collection_status` moves
    `NOT_DUE → DUE` in the same call.

    Design: Corner/consistency_model/assessment_response_already_carries_every_derived_total
    """
    chain = fixtures.effective_program(api)
    application = fixtures.file_application(api, chain.program_id)
    chain.application_id = application["id"]
    study = get_success_data(api.get_fee_study(chain.study_id, ANALYST))
    fixtures.set_clock(api, K.CLOCK_ASSESSMENT)

    assessed = fixtures.assess(api, chain.application_id)

    assert assessed["assessment_status"] == K.ASSESSMENT_ASSESSED
    assert assessed["collection_status"] == K.COLLECTION_DUE
    assert assessed["reassessment_required"] is False
    assert [line["facility_category_code"] for line in assessed["assessed_lines"]] == [
        K.PARKS_CODE,
        K.ROADS_CODE,
    ]
    check.assert_application_totals(
        assessed,
        gross_assessed_cents=K.BASELINE_GROSS_ASSESSED,
        credit_applied_cents=0,
        admin_charge_cents=K.BASELINE_ADMIN_CHARGE,
        net_due_cents=K.BASELINE_NET_DUE,
        paid_cents=0,
        default_penalty_cents=0,
    )
    check.assert_net_due_identity(assessed)
    assert assessed["pinned_fee_study_id"] == chain.study_id
    assert assessed["pinned_fee_study_version"] == study["version"]
    check.assert_timestamp_equals(
        assessed["assessed_at"], K.CLOCK_ASSESSMENT, "assessed_at"
    )
    check.assert_fields_null(assessed, "reassessed_at", "co_issued_at")
    check.assert_version_advanced_by(application["version"], assessed["version"], 1)

    reread = get_success_data(
        api.get_development_application(chain.application_id, DEVELOPER)
    )

    for field in ECHOED_FIELDS:
        assert reread[field] == assessed[field], (
            f"reading again changed {field}: the write's own response was already settled"
        )

    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ANALYST))
    roads = get_success_data(api.get_facility_category(chain.roads_category_id, ANALYST))

    check.assert_category_fund(
        parks,
        fund_balance_cents=0,
        refund_due_cents=0,
        committed_demand_units=K.BASELINE_PARKS_DEMAND_UNITS,
        deferred_receivable_cents=0,
        fund_posture=K.FUND_POSTURE_COMPLIANT,
    )
    check.assert_fields_null(parks, "oldest_unexpended_vintage_at")
    check.assert_category_fund(
        roads,
        fund_balance_cents=0,
        committed_demand_units=K.BASELINE_ROADS_DEMAND_UNITS,
    )
    assert (
        fixtures.ledger_rows(api) == []
    ), "assessment creates no ledger rows, so immediacy is not over-eagerness"
