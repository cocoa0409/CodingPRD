"""State machines that re-enter their own states.

The pathway review loop is bounded by a counter rather than by the state name,
and a product batch runs two independent status dimensions where only one edge
reads across.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_REVISION_LIMIT_EXCEEDED,
    ERR_SAF_CERTIFICATION_REQUIRED,
)
from test_helpers.assertions import assert_fields_null, assert_mass, assert_one_decimal
from test_helpers.test_users import OFFICER_A_HEADERS, VERIFIER_HEADERS
from test_helpers.types import (
    CERT_CERTIFIED,
    CERT_DECISION_REJECT,
    CERT_PENDING,
    CERT_REJECTED,
    CERT_UNCERTIFIED,
    DIST_RESERVED,
    DIST_SHIPPED,
    PATHWAY_RETURNED_FOR_INFO,
)

REJECT_NOTE = "Freeze point above the D7566 limit."


def test_return_and_resubmit_loop_increments_the_revision_round_each_lap(api):
    """PRD §3.8: "A `RETURN` decision requires a present, non-blank `info_request`, which is
    stored on the registration, and moves it `UNDER_REVIEW → RETURNED_FOR_INFO`, re-entering
    the submission cycle."
    PRD §3.8: "Submitting from `RETURNED_FOR_INFO` moves it `RETURNED_FOR_INFO → SUBMITTED`
    and additionally increments `revision_round` and requires that `revision_round` be
    strictly below the limit of 3 before the increment; the fourth attempt is refused with
    `ERR_REVISION_LIMIT_EXCEEDED` while the registration remains at `RETURNED_FOR_INFO`."

    Design: Difficulty/non_linear_state_machine/pathway_return_resubmit_cycle_exhausts_revision_rounds
    """
    plant = fx.registrable_unit(api)

    after_one = fx.returned_pathway(api, plant["unit"]["id"], laps=1)
    assert after_one["status"] == PATHWAY_RETURNED_FOR_INFO
    assert after_one["revision_round"] == 0, (
        "the first submission comes from DRAFT and increments nothing"
    )

    after_four = fx.returned_pathway(api, plant["unit"]["id"], laps=4)
    assert after_four["status"] == PATHWAY_RETURNED_FOR_INFO
    assert after_four["revision_round"] == 3, (
        f"three RETURNED_FOR_INFO resubmissions were made, got {after_four['revision_round']}"
    )


def test_fifth_submission_is_refused_once_the_revision_limit_is_reached(api):
    """PRD §3.8: "Submitting from `RETURNED_FOR_INFO` moves it `RETURNED_FOR_INFO → SUBMITTED`
    and additionally increments `revision_round` and requires that `revision_round` be
    strictly below the limit of 3 before the increment; the fourth attempt is refused with
    `ERR_REVISION_LIMIT_EXCEEDED` while the registration remains at `RETURNED_FOR_INFO`."

    Design: Difficulty/non_linear_state_machine/pathway_return_resubmit_cycle_exhausts_revision_rounds
    """
    plant = fx.registrable_unit(api)
    pathway = fx.returned_pathway(api, plant["unit"]["id"], laps=4)

    validate_error(
        api.submit_pathway(pathway["id"], OFFICER_A_HEADERS), ERR_REVISION_LIMIT_EXCEEDED
    )

    unchanged = validate_success(api.get_pathway(pathway["id"], OFFICER_A_HEADERS))
    assert unchanged["status"] == PATHWAY_RETURNED_FOR_INFO
    assert unchanged["revision_round"] == 3
    assert unchanged["info_request"] == "Provide the mass-balance ledger for round 4.", (
        f"the last return's info request must survive, got {unchanged['info_request']!r}"
    )
    assert_fields_null(unchanged, "certified_ci_gco2e_per_mj")


def test_reserved_saf_batch_may_not_ship_while_it_is_uncertified(api):
    """PRD §3.7: "Exactly one edge crosses between the two dimensions, and only for aviation
    fuel: a batch whose `product_type` is `SAF` may not ship unless its `cert_status` is
    `CERTIFIED`."
    PRD §3.7: "A `RESERVED` SAF batch that is `UNCERTIFIED` or `CERT_REJECTED` is refused
    with `ERR_SAF_CERTIFICATION_REQUIRED`."

    Design: Difficulty/non_linear_state_machine/saf_batch_certification_cycle_independent_of_distribution
    """
    ctx = fx.reserved_saf_batch(api, target_saf_share_pct=10.00)
    batch = ctx["batch"]

    assert batch["cert_status"] == CERT_UNCERTIFIED
    assert batch["distribution_status"] == DIST_RESERVED

    validate_error(
        api.ship_batch(batch["id"], OFFICER_A_HEADERS), ERR_SAF_CERTIFICATION_REQUIRED
    )

    after = validate_success(api.get_product_batch(batch["id"], OFFICER_A_HEADERS))
    assert after["distribution_status"] == DIST_RESERVED, (
        "the refused shipment must leave the distribution dimension where it was"
    )
    assert after["cert_status"] == CERT_UNCERTIFIED


def test_saf_batch_mass_and_volume_come_from_the_measured_aviation_cut(api):
    """PRD §3.6: "Each batch records the campaign that produced it as its `run_id` and
    carries the corresponding measured mass as its own `mass_mt`."
    PRD §3.6: "Its `volume_gal` is that `mass_mt` multiplied by a per-product conversion
    factor — 308.0 gallons per metric tonne for `RENEWABLE_DIESEL` and 322.0 for `SAF` —
    rounded half up to 1 decimal place."

    Design: Difficulty/non_linear_state_machine/saf_batch_certification_cycle_independent_of_distribution
    """
    ctx = fx.reserved_saf_batch(api, target_saf_share_pct=10.00)

    assert_mass(ctx["batch"]["mass_mt"], 30.000, "mass_mt")
    assert_one_decimal(ctx["batch"]["volume_gal"], 9660.0, "volume_gal")


def test_certification_cycle_leaves_the_distribution_dimension_untouched(api):
    """PRD §3.7: "Operations on one dimension leave the other untouched."
    PRD §3.7: "A `REJECT` on a batch at `CERT_PENDING` moves it `CERT_PENDING →
    CERT_REJECTED` and stores the supplied `note` as `cert_reject_reason`, bumping the
    batch's `version`."
    PRD §3.7: "Both values are stored on the batch, `cert_reject_reason` is cleared to null,
    `cert_status` moves to `CERT_PENDING`, and the batch's `version` is bumped."

    Design: Difficulty/non_linear_state_machine/saf_batch_certification_cycle_independent_of_distribution
    """
    ctx = fx.reserved_saf_batch(api, target_saf_share_pct=10.00)
    batch_id = ctx["batch"]["id"]

    pending = validate_success(
        api.request_certification(
            batch_id, f.certification_request_payload(freeze_point_c=-38.0), OFFICER_A_HEADERS
        )
    )
    assert pending["cert_status"] == CERT_PENDING
    assert pending["distribution_status"] == DIST_RESERVED

    rejected = validate_success(
        api.decide_certification(
            batch_id,
            f.certification_decision_payload(CERT_DECISION_REJECT, note=REJECT_NOTE),
            VERIFIER_HEADERS,
        )
    )
    assert rejected["cert_status"] == CERT_REJECTED
    assert rejected["cert_reject_reason"] == REJECT_NOTE
    assert rejected["distribution_status"] == DIST_RESERVED
    assert rejected["offtaker_name"] == "Delta Air Lines"

    refiled = validate_success(
        api.request_certification(
            batch_id, f.certification_request_payload(freeze_point_c=-47.0), OFFICER_A_HEADERS
        )
    )
    assert refiled["cert_status"] == CERT_PENDING, "a rejected batch may be re-filed"
    assert_fields_null(refiled, "cert_reject_reason")
    assert refiled["freeze_point_c"] == -47.0, f"got {refiled['freeze_point_c']}"
    assert refiled["distribution_status"] == DIST_RESERVED


def test_certified_saf_batch_finally_clears_the_shipment_gate(api):
    """PRD §3.7: "A `CERTIFY` on a batch at `CERT_PENDING` moves it `CERT_PENDING →
    CERTIFIED` and bumps its `version` — but for a batch whose `product_type` is `SAF` two
    additional conditions apply: the recorded `freeze_point_c` must be at or below -40.0
    degrees Celsius, and the recorded `astm_annex` must be present."
    PRD §3.7: "Shipping moves `RESERVED → SHIPPED` and bumps the `version`."

    Design: Difficulty/non_linear_state_machine/saf_batch_certification_cycle_independent_of_distribution
    """
    ctx = fx.reserved_saf_batch(api, target_saf_share_pct=10.00)
    batch_id = ctx["batch"]["id"]

    fx.certify_batch(api, batch_id, freeze_point_c=-47.0)
    certified = validate_success(api.get_product_batch(batch_id, OFFICER_A_HEADERS))
    assert certified["cert_status"] == CERT_CERTIFIED
    assert certified["distribution_status"] == DIST_RESERVED

    shipped = validate_success(api.ship_batch(batch_id, OFFICER_A_HEADERS))
    assert shipped["distribution_status"] == DIST_SHIPPED
    assert shipped["cert_status"] == CERT_CERTIFIED
    assert shipped["offtaker_name"] == "Delta Air Lines"
