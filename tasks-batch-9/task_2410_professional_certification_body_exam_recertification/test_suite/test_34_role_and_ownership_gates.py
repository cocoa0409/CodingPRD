"""Role membership, certificant ownership and adopter independence, each refusing on its own
layer while the legitimate caller is admitted."""

import pytest

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.test_users import (
    IMPOSTOR_USER_ID,
    ITEM_AUTHOR_ID,
    PSYCHOMETRICIAN_2_ID,
    PSYCHOMETRICIAN_ID,
    make_certificant_headers,
    make_psychometrician_headers,
)

IMPOSTOR_CERTIFICANT = make_certificant_headers(IMPOSTOR_USER_ID)
INDEPENDENT_PSYCHOMETRICIAN = make_psychometrician_headers(PSYCHOMETRICIAN_2_ID)

# A well-formed role header with no acting identity behind it. Built literally rather
# than through ``build_user_headers``, which always emits both headers.
ROLE_WITHOUT_AN_IDENTITY = {"X-User-Role": "ExamOperations", "Content-Type": "application/json"}

WRONG_ROLE_ITEM = {"cognitive_level": "RECALL", "stem": "Item written by the wrong role"}
RIGHT_ROLE_ITEM = {"cognitive_level": "RECALL", "stem": "Item written by the right role"}


def _a_programme_and_a_draft_item(api):
    program = fx.active_program(api)
    item = fx.draft_item(api, program["id"], **WRONG_ROLE_ITEM)
    return program, item


def _claim_body():
    return f.claim_ceu_payload(activity_date="2026-09-15T00:00:00Z",
                              provider="State Chapter Seminar", contact_hours=12.0)


def _activities_of(api, cycle_id):
    return validate_paginated(api.list_cycle_ceu_activities(cycle_id, fx.PROGRAM_ADMIN))


def _a_form_rated_by_its_only_panellist(api):
    """A form whose single panellist is psy-1, who is also a Psychometrician."""
    state = fx.pipeline_through_ratings(api, panelist_user_ids=[PSYCHOMETRICIAN_ID],
                                        ratings=[(PSYCHOMETRICIAN_ID, 0.60)])
    form = fx.read_form(api, state.form_id)
    assert form["panelist_user_ids"] == [PSYCHOMETRICIAN_ID]
    assert form["panel_status"] == "RATINGS_COMPLETE"
    assert form["status"] == "ASSEMBLED"
    return state, form


class TestCrossRoleWritesAreRefusedOnTheRole:
    """Each endpoint's role list is exhaustive, and authentication precedes authorisation."""

    def test_a_programme_and_an_item_written_by_the_wrong_roles_are_each_forbidden(self, api):
        """An `ItemSpecialist` may not define a credential and a `Psychometrician` may not
        author an item; both bodies are complete, and neither refusal stores anything.

        PRD §2.1: "A request whose `X-User-Role` is absent, unrecognised, or not among the
        roles the addressed operation admits is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        PRD §2.7: "2. **Authorisation.** `X-User-Role` present and among the endpoint's
        declared roles, on every endpoint except the public verification read → otherwise
        `ERR_FORBIDDEN_ROLE` (403)."

        Design: Corner/rbac/cross_role_writes_are_refused_forbidden_role_while_a_headerless_write_is_unauthenticated
        """
        program, _item = _a_programme_and_a_draft_item(api)

        refused_program = api.create_program(
            f.create_program_payload(name="Certified Practitioner Y", credential_code="CPY"),
            fx.ITEM_AUTHOR)
        validate_error(refused_program, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

        refused_item = api.create_item(
            f.create_item_payload(program["id"], **WRONG_ROLE_ITEM), fx.PSYCHOMETRICIAN)
        validate_error(refused_item, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

        rows, meta = validate_paginated(api.list_programs(fx.PROGRAM_ADMIN))
        assert meta["total_count"] == 1
        assert [row["credential_code"] for row in rows] == ["CPX"]

    def test_an_admin_may_not_submit_an_item_that_the_author_may(self, api):
        """Submission is an `ItemSpecialist` capability, so the `ProgramAdmin` is turned away
        before the authorship question arises, and the identical item body from the right role
        is created — which is what makes the refusals role decisions rather than payload
        defects.

        PRD §2.1: "Role membership is the coarse gate; segregation of duties is the fine one,
        and the two are independent."

        PRD §3.2: "Authorship is taken from the acting identity, not from the payload:
        `author_user_id` is set to the acting `X-User-ID` and any value a client supplies for
        it is ignored."

        Design: Corner/rbac/cross_role_writes_are_refused_forbidden_role_while_a_headerless_write_is_unauthenticated
        """
        program, item = _a_programme_and_a_draft_item(api)

        refused = api.submit_item_for_review(
            item["id"], f.submit_item_payload(revision_note="admin tries to submit"),
            fx.PROGRAM_ADMIN)

        error = validate_error(refused, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
        assert error["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value
        assert fx.read_item(api, item["id"])["status"] == "DRAFT"

        accepted = validate_success(api.create_item(
            f.create_item_payload(program["id"], **RIGHT_ROLE_ITEM), fx.ITEM_AUTHOR), 201)
        assert accepted["status"] == "DRAFT"
        assert accepted["author_user_id"] == ITEM_AUTHOR_ID
        ax.assert_item(accepted, expected_version=1)

    def test_a_write_carrying_a_role_but_no_identity_is_unauthenticated(self, api):
        """`ExamOperations` is an admitted role on candidate registration, so the only defect
        is the missing acting identity, and the earlier layer answers 401 rather than 403.

        PRD §2.1: "A request that omits `X-User-ID`, or supplies it empty, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        PRD §2.7: "1. **Authentication.** `X-User-ID` present and non-empty on every endpoint
        except the public verification read → otherwise `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/cross_role_writes_are_refused_forbidden_role_while_a_headerless_write_is_unauthenticated
        """
        _program, _item = _a_programme_and_a_draft_item(api)

        refused = api.create_candidate(f.create_candidate_payload(), ROLE_WITHOUT_AN_IDENTITY)

        error = validate_error(refused, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        assert error["error_id"] != ApiErrorId.ERR_FORBIDDEN_ROLE.value
        _rows, meta = validate_paginated(api.list_candidates(fx.EXAM_OPERATIONS))
        assert meta["total_count"] == 0


class TestCertificantOwnershipOnAnotherHoldersCycle:
    """The Certificant role is scoped by `candidate_id`, not by the role header alone."""

    def test_a_foreign_identity_holding_the_role_is_refused_as_a_non_owner(self, api):
        """The role is admitted on the endpoint and the body is exactly the one the owner
        will use, so the refusal is about ownership, and no activity row is written.

        PRD §2.1: "When `X-User-Role` is `Certificant`, `X-User-ID` is the `id` of the acting
        `Candidate` behind the credential — that is, ownership is established by comparing the
        addressed `Certificant`'s `candidate_id` to `X-User-ID`."

        PRD §2.7: "6. **Certificant ownership.** A `Certificant`-role caller acts only on
        cycles, credit activities, and disciplinary cases belonging to a `Certificant` whose
        `candidate_id` equals the acting `X-User-ID` → otherwise `ERR_NOT_RESOURCE_OWNER`
        (403). This layer guards claiming credit against a cycle, closing a cycle, electing
        re-examination, reinstating a lapsed cycle, and responding to a disciplinary case."

        Design: Corner/rbac/certificant_actions_on_another_users_cycle_return_not_resource_owner
        """
        state = fx.pipeline_through_certificant(api)
        assert fx.read_certificant(api, state.certificant_id)["candidate_id"] == \
            state.candidate_id

        refused = api.claim_ceu_activity(state.cycle_id, _claim_body(), IMPOSTOR_CERTIFICANT)

        error = validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
        assert error["error_id"] != ApiErrorId.ERR_FORBIDDEN_ROLE.value
        _rows, meta = _activities_of(api, state.cycle_id)
        assert meta["total_count"] == 0

    def test_the_owning_candidate_id_is_accepted_and_counts_nothing_yet(self, api):
        """The same body from the holder's own `candidate_id` creates the claim with its
        award already fixed, while the cycle's applied total waits for review.

        PRD §2.1: "A `Certificant`-role caller may therefore act only on recertification
        cycles, continuing-education activities, and disciplinary cases that hang off a
        `Certificant` whose `candidate_id` equals the acting `X-User-ID`"

        PRD §3.11: "A new claim has its `cycle_id` set to the cycle it was claimed against,
        `status` `SUBMITTED`, `counted` false, `credits_counted` 0.00, `reviewer_user_id` and
        `audit_verifier_user_id` null, and `review_note` null until a reviewer supplies one."

        Design: Corner/rbac/certificant_actions_on_another_users_cycle_return_not_resource_owner
        """
        state = fx.pipeline_through_certificant(api)
        api.claim_ceu_activity(state.cycle_id, _claim_body(), IMPOSTOR_CERTIFICANT)

        claimed = validate_success(api.claim_ceu_activity(
            state.cycle_id, _claim_body(), state.owner_headers), 201)

        assert claimed["cycle_id"] == state.cycle_id
        assert claimed["status"] == "SUBMITTED"
        assert claimed["counted"] is False
        assert float(claimed["credits_awarded"]) == pytest.approx(12.00, abs=0.01)
        assert float(claimed["credits_counted"]) == pytest.approx(0.00, abs=0.01)
        assert claimed["reviewer_user_id"] is None
        ax.assert_ceu_activity(claimed)

        cycle = fx.read_cycle(api, state.cycle_id)
        assert float(cycle["credits_applied"]) == pytest.approx(0.00, abs=0.01)
        assert cycle["status"] == "OPEN"


class TestCutScoreAdoptionExcludesThePanel:
    """Nobody ratifies their own judgement, and the refusal costs the form no version."""

    def test_the_only_panellist_may_not_adopt_the_cut_score_they_rated(self, api):
        """psy-1 holds the `Psychometrician` role the endpoint admits, and is refused purely
        for appearing on the panel; the form keeps its status, its panel verdict, its null cut
        score and its version.

        PRD §3.5: "The form must be in `ASSEMBLED` or `CUT_SCORE_SET` status — otherwise
        `ERR_INVALID_STATE` — and the adopting user must not appear in the form's
        `panelist_user_ids`, or the adoption is refused with `ERR_SEGREGATION_OF_DUTIES`:
        nobody ratifies their own judgement."

        PRD §2.7: "19. **Segregation of duties**, evaluated before any temporal or capacity
        check → otherwise `ERR_SEGREGATION_OF_DUTIES` (409)."

        Design: Corner/rbac/cut_score_adoption_by_a_panel_member_is_refused_and_an_independent_psychometrician_adopts
        """
        _state, form = _a_form_rated_by_its_only_panellist(api)
        token = form["version"]

        refused = api.adopt_cut_score(
            form["id"], f.adopt_cut_score_payload(token), fx.PSYCHOMETRICIAN)

        error = validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_PANEL_QUORUM_NOT_MET.value
        held = fx.read_form(api, form["id"])
        assert held["status"] == "ASSEMBLED"
        assert held["panel_status"] == "RATINGS_COMPLETE"
        assert held["raw_cut_score"] is None
        assert held["mean_expected_pass_rate"] is None
        assert held["version"] == token

    def test_an_independent_psychometrician_adopts_with_the_very_same_token(self, api):
        """Because the refused call bumped nothing, the token captured before it is still
        current; psy-2's adoption sets the trimmed mean to six decimals, clamps the raw cut to
        the upper bound and bumps the version exactly once.

        PRD §3.5: "Quorum is then tested twice: the number of entries in `panel_ratings` must
        be at least the program's `min_panelists`, and that number less twice the program's
        `panel_trim_count` must be at least 1; either failure is `ERR_PANEL_QUORUM_NOT_MET`."

        PRD §3.5: "Adoption moves the form `ASSEMBLED → CUT_SCORE_SET`, or leaves it in
        `CUT_SCORE_SET` when it is a re-adoption after further ratings, sets `panel_status` to
        `ADOPTED`, and increments the form's `version` by 1."

        PRD §3.5: "Finally clamp it: the lower bound is forty percent of `scored_item_count`
        rounded up to a whole number, the upper bound is ninety percent of `scored_item_count`
        rounded down to a whole number, and `raw_cut_score` is the unclamped raw cut raised to
        the lower bound if it falls below and then lowered to the upper bound if it rises
        above."

        Design: Corner/rbac/cut_score_adoption_by_a_panel_member_is_refused_and_an_independent_psychometrician_adopts
        """
        _state, form = _a_form_rated_by_its_only_panellist(api)
        token = form["version"]
        api.adopt_cut_score(form["id"], f.adopt_cut_score_payload(token), fx.PSYCHOMETRICIAN)

        adopted = validate_success(api.adopt_cut_score(
            form["id"], f.adopt_cut_score_payload(token), INDEPENDENT_PSYCHOMETRICIAN), 200)

        assert adopted["status"] == "CUT_SCORE_SET"
        assert adopted["panel_status"] == "ADOPTED"
        assert float(adopted["mean_expected_pass_rate"]) == pytest.approx(0.600000,
                                                                         abs=0.000001)
        assert adopted["raw_cut_score"] == 0
        assert adopted["version"] == token + 1
        assert adopted["scored_item_count"] == 1
        ax.assert_standard_setting_precision(adopted["mean_expected_pass_rate"])
