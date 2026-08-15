"""Cast confirmation: state guards, ownership, exclusivity conflicts, and
immediate visibility of selection side effects."""
from test_helpers import (
    ApiErrorId,
    create_cast_project,
    create_casting_project,
    create_client,
    create_project,
    create_talent,
    get_talent,
    make_client_headers,
    open_casting,
    select_talent,
    setup_cast_with_exclusivity,
    submit_audition,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CD, get_audition, get_project


class TestSelectTalentStateGuard:
    def test_reselect_with_rejected_sibling_returns_invalid_state(self, api):
        """PRD §3.4: "The audition must exist and belong to this project with a
        status of either `SUBMITTED` or `SHORTLISTED`; an unknown identifier
        yields `ERR_NOT_FOUND` and an audition in any other state yields
        `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_select_talent
        """
        client = create_client()
        t1, t2 = create_talent(), create_talent()
        project = create_project(client, product_category="AUTOMOTIVE",
                                 usage_type="TERM", term_months=12,
                                 exclusivity_required=True)
        open_casting(project["id"])
        a1 = submit_audition(project["id"], t1)
        a2 = submit_audition(project["id"], t2)
        select_talent(project, a1)  # project CAST; a2 auto-REJECTED

        resp = api.select_talent(project["id"], a2["id"],
                                 make_client_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_reselect_with_already_selected_audition_returns_invalid_state(self, api):
        """PRD §3.4: "The audition must exist and belong to this project with a
        status of either `SUBMITTED` or `SHORTLISTED`; an unknown identifier
        yields `ERR_NOT_FOUND` and an audition in any other state yields
        `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_select_talent
        """
        ctx = create_cast_project()
        # The chosen audition is now SELECTED — a terminal, non-selectable state.
        resp = api.select_talent(ctx["project"]["id"], ctx["audition"]["id"],
                                 make_client_headers(ctx["client"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_selected_audition_cannot_be_rejected(self, api):
        """PRD §3.3: "`REJECTED` and `SELECTED` are the audition's terminal
        states."

        Design: Corner/state_machines/self_audition_terminal_selected_lockdown
        """
        ctx = create_cast_project()
        assert get_audition(ctx["audition"]["id"])["status"] == "SELECTED"
        resp = api.reject_audition(ctx["audition"]["id"],
                                   make_client_headers(ctx["client"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSelectTalentOwnershipAndConflict:
    def test_client_cannot_act_on_other_client_project(self, api):
        """PRD §3.4: "The acting client must own the project (`ERR_FORBIDDEN`)."

        Design: Corner/validations/client_cannot_act_on_other_client_project
        """
        client_a = create_client()
        ctx = create_casting_project(client=create_client())
        resp = api.select_talent(ctx["project"]["id"], ctx["audition"]["id"],
                                 make_client_headers(client_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_talent_conflict_blocks_select_talent(self, api):
        """PRD §3.4: "When the project's `exclusivity_required` is true, the
        selected talent must hold no `ACTIVE` conflict exclusion in the
        project's `product_category` whose window overlaps the interval
        starting at the current clock and ending `term_months` months later; a
        live conflict is rejected with `ERR_TALENT_CONFLICT` (HTTP 409)."

        Design: Corner/validations/talent_conflict_blocks_select_talent
        """
        first = setup_cast_with_exclusivity(product_category="AUTOMOTIVE",
                                            term_months=12)
        talent = first["talent"]
        assert "AUTOMOTIVE" in get_talent(talent["id"])["active_conflict_categories"]

        client2 = create_client()
        project2 = create_project(client2, product_category="AUTOMOTIVE",
                                  usage_type="TERM", term_months=6,
                                  exclusivity_required=True)
        open_casting(project2["id"])
        a2 = submit_audition(project2["id"], talent)
        resp = api.select_talent(project2["id"], a2["id"],
                                 make_client_headers(client2["id"]))
        validate_error(resp, ApiErrorId.ERR_TALENT_CONFLICT)


class TestSelectTalentSideEffects:
    def test_immediate_visibility_of_select_talent_side_effects(self, api):
        """PRD §3.4: "A successful selection moves the project `CASTING → CAST`
        and fans out into a cascade of side effects." PRD §3.4: "The project
        records the chosen artist in `selected_talent_id`. The final buyout
        `buyout_final_cents` is computed now that the talent is known".

        Design: Corner/consistency_model/immediate_visibility_of_select_talent_side_effects
        """
        ctx = create_casting_project()
        client, talent, project, audition = (
            ctx["client"], ctx["talent"], ctx["project"], ctx["audition"])
        resp = api.select_talent(project["id"], audition["id"],
                                 make_client_headers(client["id"]))
        validate_success(resp, expected_status=200)
        data = get_project(project["id"])
        assert data["status"] == "CAST"
        assert data["selected_talent_id"] == talent["id"]
        assert data["buyout_final_cents"] is not None
        assert isinstance(data["buyout_final_cents"], int)
