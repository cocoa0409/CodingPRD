"""The two independent review dimensions of a certification dossier.

An energy approval and a water approval are orthogonal axes carried on one
dossier row, so approving one leaves the dossier in IN_REVIEW with the other
dimension still PENDING and the parent machine model still in DRAFT.
"""

from prd_bench_local_runner.testing import validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    ENERGY_REVIEWER,
    PRODUCT_ENGINEER,
    UID_ENERGY_REVIEWER,
)

ENERGY_NOTE = "0.40 kWh/cwt verified on the 120-cycle run"


def _dossier_in_review(api):
    """A machine model in DRAFT carrying one dossier with both dimensions PENDING."""
    model = fx.make_model(api)
    dossier = fx.make_dossier(api, model["id"])
    return model, dossier


def _approve_energy(api, dossier_id):
    """One compliance officer, who did not prepare the dossier, approves ENERGY."""
    return validate_success(
        api.create_dossier_review(
            dossier_id,
            f.review_payload("ENERGY", "APPROVE", note=ENERGY_NOTE),
            ENERGY_REVIEWER,
        ),
        expected_status=200,
    )


def _read_dossier(api, dossier_id):
    return validate_success(
        api.get_certification_dossier(dossier_id, COMPLIANCE_OFFICER),
        expected_status=200,
    )


class TestOneApprovedDimensionLeavesTheOtherPending:
    def test_01_an_energy_approval_keeps_the_dossier_in_review(self, api):
        """Approving one dimension advances that axis alone and certifies nothing.

        PRD: "Approving one dimension while the other is still `PENDING` sets that dimension's review state to `APPROVED` and stamps the acting `X-User-ID` into the matching reviewer field, but leaves `dossier_state` exactly where it was, at `IN_REVIEW` — a single approval never certifies anything."
        Design: Difficulty/non_linear_state_machine/dossier_parallel_review_dimensions_independent
        """
        model, dossier = _dossier_in_review(api)
        assert dossier["dossier_state"] == "IN_REVIEW"

        _approve_energy(api, dossier["id"])

        reread = _read_dossier(api, dossier["id"])
        assert reread["dossier_state"] == "IN_REVIEW"
        assert reread["energy_review_state"] == "APPROVED"

    def test_02_the_water_dimension_is_untouched_by_an_energy_decision(self, api):
        """The water axis stays PENDING with no reviewer stamped on it.

        PRD: "A new dossier begins with `dossier_state` at `IN_REVIEW`, with both review dimensions at `PENDING` — `energy_review_state` and `water_review_state` — with both reviewer stamps null, namely `energy_reviewer_user_id` and `water_reviewer_user_id`, with `resurvey_reason` at `NONE`, `resurvey_count` at 0, `certified_at` null, `qualified_program_codes` an empty array and `rebate_amount_cents` at 0."
        Design: Difficulty/non_linear_state_machine/dossier_parallel_review_dimensions_independent
        """
        model, dossier = _dossier_in_review(api)

        _approve_energy(api, dossier["id"])

        reread = _read_dossier(api, dossier["id"])
        assert reread["water_review_state"] == "PENDING"
        assert reread["water_reviewer_user_id"] is None

    def test_03_the_deciding_officer_is_stamped_on_the_energy_axis_only(self, api):
        """The energy reviewer's own identifier lands in the matching reviewer field.

        PRD: "A review decision addresses exactly one dimension, named by the `dimension` field as either `ENERGY` or `WATER`, and carries a `decision` of `APPROVE` or `REJECT` plus an optional `note`."
        Design: Difficulty/non_linear_state_machine/dossier_parallel_review_dimensions_independent
        """
        model, dossier = _dossier_in_review(api)

        _approve_energy(api, dossier["id"])

        reread = _read_dossier(api, dossier["id"])
        assert reread["energy_reviewer_user_id"] == UID_ENERGY_REVIEWER

    def test_04_a_single_approval_stamps_no_certification_instant(self, api):
        """Only the certifying second approval stamps certified_at.

        PRD: "It stamps `certified_at` with the current logical-clock instant."
        Design: Difficulty/non_linear_state_machine/dossier_parallel_review_dimensions_independent
        """
        model, dossier = _dossier_in_review(api)

        _approve_energy(api, dossier["id"])

        reread = _read_dossier(api, dossier["id"])
        assert reread["certified_at"] is None

    def test_05_a_single_approval_awards_no_rebate(self, api):
        """Rebate qualification waits for the approval that makes both axes APPROVED.

        PRD: "Only the second approval, the one that makes both dimensions `APPROVED`, advances the dossier from `IN_REVIEW` to `CERTIFIED`."
        Design: Difficulty/non_linear_state_machine/dossier_parallel_review_dimensions_independent
        """
        model, dossier = _dossier_in_review(api)

        _approve_energy(api, dossier["id"])

        reread = _read_dossier(api, dossier["id"])
        assert reread["rebate_amount_cents"] == 0

    def test_06_neither_axis_alone_moves_the_model_out_of_draft(self, api):
        """The parent machine model is still a DRAFT catalogue entry.

        PRD: "A model in `certification_state` `DRAFT` whose dossier just reached `CERTIFIED` moves from `DRAFT` to `CERTIFIED`, copying the dossier's already-sorted `qualified_program_codes` into the model's `rebate_program_codes`, copying the dossier's `rebate_amount_cents` into the model's `rebate_amount_cents`, resetting `suspended_reason` to `NONE`, advancing the model's `version` by 1 and refreshing its `updated_at`."
        Design: Difficulty/non_linear_state_machine/dossier_parallel_review_dimensions_independent
        """
        model, dossier = _dossier_in_review(api)

        _approve_energy(api, dossier["id"])

        reread = validate_success(
            api.get_machine_model(model["id"], PRODUCT_ENGINEER), expected_status=200
        )
        assert reread["certification_state"] == "DRAFT"
