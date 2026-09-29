"""Nine guards along the inspect-defect-dispute spine of one back-of-house line."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    acknowledged_plan,
    assert_field_equals,
    assert_item_state,
    assert_plan_dimensions,
    complete_item_work,
    dispute_resolution_payload,
    file_dispute,
    locked_budget,
    perform_inspection,
    punch_verify_payload,
    raise_defect,
    read_dispute,
    read_inspection,
    read_item,
    read_plan,
    read_punch_item,
    remediate_defect,
    resolve_dispute,
    schedule_inspection,
    start_item,
    validate_error,
    verify_defect,
)

_DEFECT_NOTE = (
    "Laundry floor drain cover sits proud of the finished screed by four millimetres."
)
_WAIVER_NOTE = "Cosmetic only; the brand waives the deviation for this cycle."
_PANEL_NOTE = "The scoping stands; the standard cited is current for the 2026.1 edition."


@pytest.fixture
def finished_back_of_house_work_and_a_progress_visit(api):
    """One back-of-house line reported finished, with a progress visit still only scheduled."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "laundry",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-30.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Garrowby Hotels LLC",
        contact_email="ops@garrowbyh.example",
        property_overrides={"name": "Garrowby Assembly Rooms"},
    )
    locked_budget(api, scenario, 1138500)
    start_item(api, scenario, scenario.item_id("laundry"))
    complete_item_work(api, scenario, scenario.item_id("laundry"))
    inspection = schedule_inspection(
        api, scenario, scheduled_date="2026-08-01", inspection_type="PROGRESS"
    )
    return scenario, inspection


def _raise_a_minor_defect(api, scenario, inspection):
    perform_inspection(api, inspection["id"])
    return raise_defect(
        api,
        inspection["id"],
        scenario.item_id("laundry"),
        severity="MINOR",
        defect_note=_DEFECT_NOTE,
    )


def _file_the_scope_dispute(api, scenario):
    return file_dispute(
        api,
        scenario,
        scenario.item_id("laundry"),
        claimed_cost_cents=600000,
        dispute_basis="SCOPE_REASONABLENESS",
    )


class TestTheVisitMustBePerformedExactlyOnceAndNeverSigned:
    def test_a_scheduled_visit_cannot_be_signed_off(
        self, api, brand_inspector, finished_back_of_house_work_and_a_progress_visit
    ):
        """"The inspection must be in `PERFORMED`, or `ERR_INSPECTION_NOT_SIGNABLE`." "The inspection is
        created in `SCHEDULED` with `punch_open_count` 0 and `performed_at`, `signed_off_at` and
        `signed_off_by_user_id` all null."

        Design: Corner/errors/inspection_punch_and_dispute_guards_are_triggerable
        """
        _scenario, inspection = finished_back_of_house_work_and_a_progress_visit

        response = api.sign_off_inspection(inspection["id"], brand_inspector)

        validate_error(response, ApiErrorId.ERR_INSPECTION_NOT_SIGNABLE, 409)
        read_back = read_inspection(api, inspection["id"])
        assert_field_equals(read_back, "status", "SCHEDULED", "inspection")
        assert read_back["performed_at"] is None, (
            f"a refused certification records no visit, got {read_back!r}"
        )

    def test_a_performed_visit_cannot_be_performed_again(
        self, api, brand_inspector, finished_back_of_house_work_and_a_progress_visit
    ):
        """"The action is refused unless the inspection is in `SCHEDULED`
        (`ERR_INSPECTION_NOT_PERFORMABLE`)". "Performing stamps `performed_at` with the logical clock and
        recomputes `punch_open_count`, which is 0 until defects are filed."

        Design: Corner/errors/inspection_punch_and_dispute_guards_are_triggerable
        """
        _scenario, inspection = finished_back_of_house_work_and_a_progress_visit
        performed = perform_inspection(api, inspection["id"])

        response = api.perform_inspection(inspection["id"], brand_inspector)

        assert_field_equals(performed, "status", "PERFORMED", "inspection")
        assert_field_equals(performed, "punch_open_count", 0, "inspection")
        validate_error(response, ApiErrorId.ERR_INSPECTION_NOT_PERFORMABLE, 409)
        assert_field_equals(
            read_inspection(api, inspection["id"]), "status", "PERFORMED", "inspection"
        )

    def test_a_progress_visit_stops_permanently_at_performed(
        self, api, brand_inspector, finished_back_of_house_work_and_a_progress_visit
    ):
        """"Its `inspection_type` must be `COMPLETION`, or `ERR_INSPECTION_TYPE_NOT_SIGNABLE` —
        `SCOPING`, `PROGRESS` and `RE_INSPECTION` visits stop permanently at `PERFORMED`."

        Design: Corner/errors/inspection_punch_and_dispute_guards_are_triggerable
        """
        scenario, inspection = finished_back_of_house_work_and_a_progress_visit
        perform_inspection(api, inspection["id"])

        response = api.sign_off_inspection(inspection["id"], brand_inspector)

        validate_error(response, ApiErrorId.ERR_INSPECTION_TYPE_NOT_SIGNABLE, 409)
        assert_field_equals(
            read_inspection(api, inspection["id"]), "status", "PERFORMED", "inspection"
        )
        assert_plan_dimensions(
            read_plan(api, scenario.plan_id), status="READY_FOR_COMPLETION_INSPECTION"
        )


class TestADefectWalksItsOwnLadder:
    def test_an_open_defect_cannot_be_closed_before_it_is_remediated(
        self, api, brand_inspector, finished_back_of_house_work_and_a_progress_visit
    ):
        """"`CLOSE` and `REOPEN` additionally require the defect to be in `REMEDIATED`
        (`ERR_PUNCH_NOT_VERIFIABLE`)." "A `MINOR` defect does neither: it is recorded, it counts toward
        `punch_open_count`, and the charged item stays in `WORK_COMPLETE`."

        Design: Corner/errors/inspection_punch_and_dispute_guards_are_triggerable
        """
        scenario, inspection = finished_back_of_house_work_and_a_progress_visit
        defect = _raise_a_minor_defect(api, scenario, inspection)

        response = api.verify_punch_list_item(
            defect["id"], punch_verify_payload("CLOSE"), brand_inspector
        )

        validate_error(response, ApiErrorId.ERR_PUNCH_NOT_VERIFIABLE, 409)
        assert_field_equals(read_punch_item(api, defect["id"]), "status", "OPEN", "defect")
        assert_field_equals(
            read_inspection(api, inspection["id"]), "punch_open_count", 1, "inspection"
        )
        assert_item_state(read_item(api, scenario.item_id("laundry")), status="WORK_COMPLETE")

    def test_a_waived_defect_cannot_be_remediated_again(
        self, api, finished_back_of_house_work_and_a_progress_visit
    ):
        """"A waiver moves the defect to `WAIVED`, decreases `punch_open_count` by one, appends a ledger
        entry of type `PUNCH_WAIVED` carrying the defect's `pip_item_id` and a `delta_cents` of 0".
        "this is refused unless the defect is `OPEN` (`ERR_PUNCH_NOT_REMEDIABLE`) and unless the acting
        `X-User-ID` is the property's `franchisee_id`."

        Design: Corner/errors/inspection_punch_and_dispute_guards_are_triggerable
        """
        scenario, inspection = finished_back_of_house_work_and_a_progress_visit
        defect = _raise_a_minor_defect(api, scenario, inspection)
        remediate_defect(api, scenario, defect["id"])
        verify_defect(api, defect["id"], "WAIVE", verification_note=_WAIVER_NOTE)

        response = api.remediate_punch_list_item(defect["id"], scenario.owner_headers)

        validate_error(response, ApiErrorId.ERR_PUNCH_NOT_REMEDIABLE, 409)
        assert_field_equals(read_punch_item(api, defect["id"]), "status", "WAIVED", "defect")
        assert_field_equals(
            read_inspection(api, inspection["id"]), "punch_open_count", 0, "inspection"
        )


class TestTheResolveBodyAndTheRemovalWindowAreBothPoliced:
    def test_the_revised_cost_field_is_bound_to_the_revise_branch(
        self, api, brand_manager, finished_back_of_house_work_and_a_progress_visit
    ):
        """"The `revised_cost_cents` field is branch-bound: it must be present and at least 0 when the
        resolution is `REVISE`, failing with `ERR_REVISION_COST_REQUIRED` (422) otherwise, and it must be
        absent when the resolution is `UPHOLD` or `REMOVE`, failing with
        `ERR_REVISION_NOT_ALLOWED_FOR_RESOLUTION` (422) if supplied."

        Design: Corner/errors/inspection_punch_and_dispute_guards_are_triggerable
        """
        scenario, _inspection = finished_back_of_house_work_and_a_progress_visit
        dispute = _file_the_scope_dispute(api, scenario)

        validate_error(
            api.resolve_dispute(
                dispute["id"], dispute_resolution_payload("REVISE"), brand_manager
            ),
            ApiErrorId.ERR_REVISION_COST_REQUIRED,
            422,
        )
        validate_error(
            api.resolve_dispute(
                dispute["id"],
                dispute_resolution_payload("UPHOLD", revised_cost_cents=600000),
                brand_manager,
            ),
            ApiErrorId.ERR_REVISION_NOT_ALLOWED_FOR_RESOLUTION,
            422,
        )

        assert_field_equals(read_dispute(api, dispute["id"]), "status", "FILED", "dispute")
        assert_plan_dimensions(read_plan(api, scenario.plan_id), dispute_state="DISPUTE_OPEN")

    def test_a_finished_item_has_left_the_removable_window(
        self, api, brand_manager, finished_back_of_house_work_and_a_progress_visit
    ):
        """"It is available only while the contested item's `status` is `SCOPED`,
        `DEFERRED_PENDING_EXTENSION` or `IN_PROGRESS`; from any other state the resolution is refused
        with `ERR_ITEM_NOT_REMOVABLE` (409)."

        Design: Corner/errors/inspection_punch_and_dispute_guards_are_triggerable
        """
        scenario, _inspection = finished_back_of_house_work_and_a_progress_visit
        dispute = _file_the_scope_dispute(api, scenario)

        response = api.resolve_dispute(
            dispute["id"], dispute_resolution_payload("REMOVE"), brand_manager
        )

        validate_error(response, ApiErrorId.ERR_ITEM_NOT_REMOVABLE, 409)
        assert_field_equals(read_dispute(api, dispute["id"]), "status", "FILED", "dispute")
        assert_item_state(read_item(api, scenario.item_id("laundry")), status="WORK_COMPLETE")
        assert_field_equals(read_plan(api, scenario.plan_id), "scope_item_count", 1, "plan")

    def test_the_upheld_dispute_is_terminal_and_moves_no_cost(
        self, api, brand_manager, finished_back_of_house_work_and_a_progress_visit
    ):
        """"`UPHOLD` moves the dispute from `FILED` to `RESOLVED_UPHELD` and sets the plan's
        `dispute_state` to `DISPUTE_RESOLVED_UPHELD`, leaving `status` untouched. No cost moves: the
        item's `approved_cost_cents` stays at its `brand_estimated_cost_cents`." "Resolution is refused
        unless the dispute is in `FILED` (`ERR_DISPUTE_NOT_RESOLVABLE`)".

        Design: Corner/errors/inspection_punch_and_dispute_guards_are_triggerable
        """
        scenario, _inspection = finished_back_of_house_work_and_a_progress_visit
        dispute = _file_the_scope_dispute(api, scenario)

        upheld = resolve_dispute(
            api, dispute["id"], "UPHOLD", panel_decision_note=_PANEL_NOTE
        )
        response = api.resolve_dispute(
            dispute["id"], dispute_resolution_payload("UPHOLD"), brand_manager
        )

        assert_field_equals(upheld, "status", "RESOLVED_UPHELD", "dispute")
        validate_error(response, ApiErrorId.ERR_DISPUTE_NOT_RESOLVABLE, 409)
        assert_plan_dimensions(
            read_plan(api, scenario.plan_id),
            status="READY_FOR_COMPLETION_INSPECTION",
            dispute_state="DISPUTE_RESOLVED_UPHELD",
        )
        item = read_item(api, scenario.item_id("laundry"))
        assert_field_equals(item, "approved_cost_cents", 1000000, "item")
        assert_field_equals(item, "owner_claimed_cost_cents", 600000, "item")
