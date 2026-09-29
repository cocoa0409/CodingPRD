"""Which field an obligation demands, and whether it may be waived, both key off its own row.

Three obligations on one home take three different paths through the same two endpoints: the
HOA citation must produce evidence, the tax appeal must produce a settlement inside a range
bounded by the home's assessment, and neither the CRITICAL citation nor the appeal may be waived
however willing the director is.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import (
    ERR_CRITICAL_OBLIGATION_NOT_WAIVABLE,
    ERR_EVIDENCE_REQUIRED,
    ERR_OBLIGATION_PAST_DUE,
    ERR_OBLIGATION_WORK_ORDER_MISMATCH,
    ERR_SETTLED_VALUE_INVALID,
)
from test_helpers.assertions import (
    assert_absent_or_empty,
    assert_fields,
    assert_money_group,
    created,
    failed,
    ok,
)
from test_helpers.constants import (
    CLOCK_AUG_01,
    OBLIGATION_OPEN,
    OBLIGATION_PLANNED,
    OBLIGATION_RESOLUTION_SUBMITTED,
    OBLIGATION_TYPE_TAX_APPEAL,
)


def test_evidence_for_the_citation_a_settlement_for_the_appeal_and_no_waiver_for_either(api):
    """A date past the deadline, a work order on the wrong home, a missing field, two refused waivers.

    PRD SS3.9 on planning: "A `planned_resolution_on` after the `due_on` is refused with
    `ERR_OBLIGATION_PAST_DUE`, and a `work_order_id` naming a work order that belongs to a different
    home or whose `status` is `VOIDED` is refused with `ERR_OBLIGATION_WORK_ORDER_MISMATCH`", the
    link itself being optional: it "stays the empty string when the cure needs none."  PRD SS3.9 on
    submission: "A `PROPERTY_TAX_APPEAL` requires a `settled_value_cents` that is present, at least
    1, and no greater than the home's `assessed_value_cents`; anything else is refused with
    `ERR_SETTLED_VALUE_INVALID`. ... An obligation whose type is `HOA_VIOLATION` or
    `INSURANCE_DEFICIENCY` instead requires a non-empty `evidence_ref`, and an absent or empty one is
    refused with `ERR_EVIDENCE_REQUIRED`."  A successful submission "moves the obligation `PLANNED ->
    RESOLUTION_SUBMITTED` and its `submitted_by_user_id` is stamped from the caller's `X-User-ID`".
    PRD SS3.9 on the waiver: "`WAIVE` moves it `RESOLUTION_SUBMITTED` -> `WAIVED` and is permitted
    only for an obligation whose `obligation_type` is `HOA_VIOLATION` and whose `severity` is `MINOR`
    or `MAJOR`; a `CRITICAL` obligation of any type, or an obligation of any severity whose type is
    `INSURANCE_DEFICIENCY` or `PROPERTY_TAX_APPEAL`, is refused with
    `ERR_CRITICAL_OBLIGATION_NOT_WAIVABLE`."  The tax money group only ever moves on acceptance --
    PRD SS3.9: "When the accepted obligation's `obligation_type` is `PROPERTY_TAX_APPEAL`, acceptance
    runs four further hops in order", and on creation "`settled_value_cents`,
    `annual_tax_savings_cents`, `consultant_fee_cents` and `net_tax_benefit_cents` all 0."

    Design: Corner/validations/obligation_plan_and_resolution_rules_key_off_type_and_severity
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_general())
    home = x.create_home(api, market["id"])
    other_home = x.create_home(api, market["id"], f.home_payload_no_hoa(market["id"]))
    foreign_order = created(
        api.create_work_order(
            f.work_order_payload(other_home["id"], paint["id"], work_type="TURN"), x.OPS
        )
    )

    citation = x.open_obligation(
        api,
        home["id"],
        severity="MAJOR",
        description="Fence stain out of palette",
        due_on="2026-09-30",
    )
    appeal = x.open_obligation(
        api,
        home["id"],
        obligation_type=OBLIGATION_TYPE_TAX_APPEAL,
        severity="MINOR",
        description="2026 assessment appeal",
        assessed_value_cents=28000000,
        target_value_cents=24500000,
        consultant_fee_bps=3000,
    )
    critical = x.open_obligation(
        api,
        home["id"],
        severity="CRITICAL",
        description="Deck structural failure",
    )

    failed(
        api.plan_obligation(
            citation["id"], f.plan_obligation_payload("2026-10-15"), x.COMPLIANCE
        ),
        ERR_OBLIGATION_PAST_DUE,
    )
    assert_fields(
        ok(api.get_compliance_obligation(citation["id"], x.COMPLIANCE)),
        status=OBLIGATION_OPEN,
    )

    failed(
        api.plan_obligation(
            citation["id"],
            f.plan_obligation_payload("2026-09-15", work_order_id=foreign_order["id"]),
            x.COMPLIANCE,
        ),
        ERR_OBLIGATION_WORK_ORDER_MISMATCH,
    )
    still_open = ok(api.get_compliance_obligation(citation["id"], x.COMPLIANCE))
    assert_fields(still_open, status=OBLIGATION_OPEN)
    assert_absent_or_empty(still_open, "work_order_id")

    planned = ok(
        api.plan_obligation(
            citation["id"], f.plan_obligation_payload("2026-09-15"), x.COMPLIANCE
        )
    )
    assert_fields(
        planned,
        status=OBLIGATION_PLANNED,
        resolution_round=0,
        planned_resolution_on="2026-09-15",
    )
    assert_absent_or_empty(planned, "work_order_id")

    failed(
        api.submit_obligation_resolution(
            citation["id"], f.submit_resolution_payload(), x.COMPLIANCE
        ),
        ERR_EVIDENCE_REQUIRED,
    )
    assert_fields(
        ok(api.get_compliance_obligation(citation["id"], x.COMPLIANCE)),
        status=OBLIGATION_PLANNED,
    )

    ok(api.plan_obligation(appeal["id"], f.plan_obligation_payload("2026-10-15"), x.COMPLIANCE))
    failed(
        api.submit_obligation_resolution(
            appeal["id"], f.submit_resolution_payload(settled_value_cents=28000001), x.COMPLIANCE
        ),
        ERR_SETTLED_VALUE_INVALID,
    )
    failed(
        api.submit_obligation_resolution(
            appeal["id"],
            f.submit_resolution_payload(evidence_ref="appeal-packet-77"),
            x.COMPLIANCE,
        ),
        ERR_SETTLED_VALUE_INVALID,
    )
    assert_fields(
        ok(api.get_compliance_obligation(appeal["id"], x.COMPLIANCE)),
        status=OBLIGATION_PLANNED,
    )

    submitted = ok(
        api.submit_obligation_resolution(
            appeal["id"], f.submit_resolution_payload(settled_value_cents=24800000), x.COMPLIANCE
        )
    )
    assert_fields(
        submitted,
        status=OBLIGATION_RESOLUTION_SUBMITTED,
        submitted_by_user_id="co-1",
    )
    assert_money_group(
        submitted, settled_value_cents=24800000, annual_tax_savings_cents=0
    )

    ok(api.plan_obligation(critical["id"], f.plan_obligation_payload("2026-09-20"), x.COMPLIANCE))
    ok(
        api.submit_obligation_resolution(
            critical["id"],
            f.submit_resolution_payload(evidence_ref="deck-permit-901"),
            x.COMPLIANCE,
        )
    )

    failed(
        api.review_obligation_resolution(
            critical["id"],
            f.review_resolution_payload("WAIVE", review_note="Owner asks for a pass"),
            x.DIRECTOR,
        ),
        ERR_CRITICAL_OBLIGATION_NOT_WAIVABLE,
    )
    assert_fields(
        ok(api.get_compliance_obligation(critical["id"], x.COMPLIANCE)),
        status=OBLIGATION_RESOLUTION_SUBMITTED,
    )

    failed(
        api.review_obligation_resolution(
            appeal["id"],
            f.review_resolution_payload("WAIVE", review_note="Drop the appeal"),
            x.DIRECTOR,
        ),
        ERR_CRITICAL_OBLIGATION_NOT_WAIVABLE,
    )
    assert_fields(
        ok(api.get_compliance_obligation(appeal["id"], x.COMPLIANCE)),
        status=OBLIGATION_RESOLUTION_SUBMITTED,
    )
    assert_money_group(
        ok(api.get_home(home["id"], x.COMPLIANCE)), assessed_value_cents=28000000
    )
