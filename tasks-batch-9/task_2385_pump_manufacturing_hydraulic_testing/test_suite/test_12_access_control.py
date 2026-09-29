"""Role authorisation, approver identity and the shared read surface.

Write endpoints in this contract are single-role: the master-data catalogue
belongs to the platform administrator, proposing a selection to the application
engineer and approving it to the hydraulic approver.  The one write that accepts
two roles is the casting defect report, which either the foundry partner running
the lot or a quality inspector may raise.  Reads are never partitioned - every
one of the eight roles may call every read endpoint in the API.

The checks here also separate two refusals that look alike from the outside.  A
caller whose declared role is not among the roles authorised for the endpoint is
turned away before anything about the record is considered.  A caller who does
hold the endpoint's role but happens to be the person recorded as the proposer
gets past that gate and is stopped later, by the rule that an approver must
differ from the proposer.
"""

import pytest

from test_helpers import (
    ALL_ROLES,
    ApiErrorId,
    Role,
    assertions,
    factories as F,
    fixtures as X,
    test_users as U,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    APPLICATION_ENGINEER,
    HYDRAULIC_APPROVER,
    PLATFORM_ADMIN,
    PRODUCTION_PLANNER,
    QUALITY_INSPECTOR,
)


# ─────────────────────────────────────────────────────────────────────────────
# The master-data catalogue belongs to the platform administrator alone
# ─────────────────────────────────────────────────────────────────────────────
class TestCatalogueIsPlatformAdminOnly:
    """A hydraulic model may only be registered by the master-data custodian."""

    def test_foundry_partner_cannot_create_a_pump_model_returns_unauthorized(
        self, api, foundry_partner_headers_factory
    ):
        """The foundry partner is refused the model catalogue, the administrator is not.

        `POST /pump-models` authorises `PlatformAdmin` and nobody else.  A
        foundry partner is a well formed caller - its `X-User-ID` is the
        identifier of a real foundry row - but its declared role is not among
        the roles authorised for the endpoint, so the request is rejected with
        `ERR_UNAUTHORIZED` and nothing is written.  Replaying the identical body
        as the platform administrator then succeeds, which shows the refusal was
        about the role and not about the payload: exactly one model exists
        afterwards, the one the administrator created.

        Design: Corner/rbac/foundry_partner_cannot_create_a_pump_model_returns_unauthorized
        """
        foundry = X.create_foundry(api)
        foundry_headers = foundry_partner_headers_factory(foundry["id"])

        # One payload, offered twice, so the only difference is the caller.
        payload = F.pump_model_payload()

        refused = api.create_pump_model(payload, foundry_headers)
        validate_error(refused, ApiErrorId.UNAUTHORIZED)

        accepted = api.create_pump_model(payload, PLATFORM_ADMIN)
        model = validate_success(accepted, 201)
        assert model["model_code"] == payload["model_code"]
        assert model["status"] == "ORDERABLE"
        assertions.assert_common_fields(model)

        rows, meta = validate_paginated(api.list_pump_models(PLATFORM_ADMIN))
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [model["id"]]


# ─────────────────────────────────────────────────────────────────────────────
# Proposing and approving a selection are two different roles
# ─────────────────────────────────────────────────────────────────────────────
class TestSelectionApprovalChainRoles:
    """Propose is the engineer's move, approve is the approver's, never swapped."""

    def test_application_engineer_cannot_approve_their_own_selection_returns_unauthorized(
        self, api
    ):
        """The engineer who proposed cannot approve, because approval is not their role.

        `POST /selections/{id}/approve` authorises `HydraulicApprover` only.
        When the acting caller declares `ApplicationEngineer` the request never
        reaches the rule that compares the approver with the recorded proposer:
        the authorisation check sits above it in the fixed global order, so the
        first violated check ends the request and the answer is
        `ERR_UNAUTHORIZED`.  The selection is untouched and remains `PROPOSED`
        with no `approved_by_user_id`, and a hydraulic approver can still take
        it from there.

        Design: Corner/rbac/application_engineer_cannot_approve_their_own_selection_returns_unauthorized
        """
        ctx = X.setup_proposed_selection(api)
        selection_id = ctx["selection"]["id"]

        response = api.approve_selection(selection_id, APPLICATION_ENGINEER)
        error = validate_error(response, ApiErrorId.UNAUTHORIZED)
        # The role gate answered first, so the proposer comparison never ran.
        assert error["error_id"] != ApiErrorId.SEGREGATION_OF_DUTIES

        unchanged = X.reread_selection(api, selection_id)
        assert unchanged["status"] == "PROPOSED"
        assert unchanged["proposed_by_user_id"] == U.ENGINEER_USER_ID
        assert unchanged["approved_by_user_id"] is None
        assert unchanged["version"] == ctx["selection"]["version"]

        approved = validate_success(
            api.approve_selection(selection_id, HYDRAULIC_APPROVER), 200
        )
        assert approved["status"] == "APPROVED"

    def test_hydraulic_approver_cannot_propose_a_selection_returns_unauthorized(
        self, api
    ):
        """The approver cannot start the review they are meant to finish.

        `POST /selections/{id}/propose` authorises `ApplicationEngineer` only,
        so a `HydraulicApprover` calling it is rejected with
        `ERR_UNAUTHORIZED`.  Because the refusal happens before any state is
        touched, the selection is still `DRAFT` with `proposed_by_user_id` null,
        and the application engineer whose role it is can then move it
        `DRAFT -> PROPOSED` and be stamped as the proposer.

        Design: Corner/rbac/hydraulic_approver_cannot_propose_a_selection_returns_unauthorized
        """
        ctx = X.setup_draft_selection(api)
        selection_id = ctx["selection"]["id"]

        response = api.propose_selection(selection_id, HYDRAULIC_APPROVER)
        validate_error(response, ApiErrorId.UNAUTHORIZED)

        unchanged = X.reread_selection(api, selection_id)
        assert unchanged["status"] == "DRAFT"
        assert unchanged["proposed_by_user_id"] is None
        assert unchanged["version"] == ctx["selection"]["version"]

        proposed = validate_success(
            api.propose_selection(selection_id, APPLICATION_ENGINEER), 200
        )
        assert proposed["status"] == "PROPOSED"
        assert proposed["proposed_by_user_id"] == U.ENGINEER_USER_ID


# ─────────────────────────────────────────────────────────────────────────────
# Holding the approver role is not enough: the person must differ
# ─────────────────────────────────────────────────────────────────────────────
class TestApprovalSeparatesProposerFromApprover:
    """Approval requires the acting user to differ from the recorded proposer."""

    def test_approve_by_the_proposing_user_returns_segregation_of_duties(self, api):
        """A properly-roled approver who is the proposer is stopped by identity, not role.

        The selection is proposed by `eng-101`.  The first approval attempt is
        made by a caller who declares `HydraulicApprover` - so the authorisation
        gate is satisfied - but whose `X-User-ID` is still `eng-101`.  Selection
        approval requires that the approver differ from the recorded proposer,
        and a match yields `ERR_SEGREGATION_OF_DUTIES`.  The selection stays
        `PROPOSED` and the parent enquiry stays `OPEN`.  A different person
        holding the same role then approves cleanly: the acting `X-User-ID`
        `appr-201` is written to `approved_by_user_id`, `proposed_by_user_id`
        still reads `eng-101`, and the parent enquiry is driven
        `OPEN -> SELECTION_LOCKED`.

        Design: Corner/rbac/approve_by_the_proposing_user_returns_segregation_of_duties
        """
        ctx = X.setup_proposed_selection(api)
        selection_id = ctx["selection"]["id"]
        duty_id = ctx["duty"]["id"]

        # Correct role, wrong person: the proposer wearing the approver's role.
        proposer_as_approver = U.make_headers(
            U.ENGINEER_USER_ID, Role.HYDRAULIC_APPROVER
        )
        refused = api.approve_selection(selection_id, proposer_as_approver)
        error = validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES)
        assert error["error_id"] != ApiErrorId.UNAUTHORIZED

        blocked = X.reread_selection(api, selection_id)
        assert blocked["status"] == "PROPOSED"
        assert blocked["approved_by_user_id"] is None
        assert X.reread_duty_application(api, duty_id)["status"] == "OPEN"

        approved = validate_success(
            api.approve_selection(selection_id, HYDRAULIC_APPROVER), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["proposed_by_user_id"] == U.ENGINEER_USER_ID
        assert approved["approved_by_user_id"] == U.APPROVER_USER_ID

        duty = X.reread_duty_application(api, duty_id)
        assert duty["status"] == "SELECTION_LOCKED"


# ─────────────────────────────────────────────────────────────────────────────
# The one write two roles share: reporting a casting defect
# ─────────────────────────────────────────────────────────────────────────────
class TestSharedDefectReportWrite:
    """Either the foundry partner or a quality inspector may raise a defect."""

    @pytest.fixture
    def poured_lot(self, api):
        """A POURED lot of four pieces, with the partner headers that poured it."""
        world = X.setup_master_data(api)
        world["lot"] = X.pour_casting_lot(api, world)
        return world

    def test_quality_inspector_and_foundry_partner_both_report_defects(
        self, api, poured_lot
    ):
        """Two different roles write to the same endpoint and both are recorded.

        Either a `FoundryPartner` or a `QualityInspector` may report a defect
        against a lot, so both calls are accepted on the same lot.  Each new
        defect is `REPORTED` with `disposition` null,
        `dispositioned_by_user_id` null, and `reported_by_user_id` taken from
        the acting `X-User-ID` - the foundry's own identifier for the partner
        and `qi-301` for the inspector.  Reporting alone leaves the lot's piece
        ledger untouched, so after two reports the lot still shows four accepted
        pieces and nothing scrapped or awaiting rework.

        Design: Corner/rbac/quality_inspector_and_foundry_partner_both_report_defects
        """
        lot_id = poured_lot["lot"]["id"]
        foundry_id = poured_lot["foundry"]["id"]

        by_partner = validate_success(
            api.report_casting_defect(
                lot_id,
                F.casting_defect_payload(defect_type="POROSITY", severity="MINOR"),
                poured_lot["foundry_headers"],
            ),
            201,
        )
        assert by_partner["reported_by_user_id"] == foundry_id
        assert by_partner["status"] == "REPORTED"
        assert by_partner["disposition"] is None
        assert by_partner["dispositioned_by_user_id"] is None

        by_inspector = validate_success(
            api.report_casting_defect(
                lot_id,
                F.casting_defect_payload(defect_type="INCLUSION", severity="MINOR"),
                QUALITY_INSPECTOR,
            ),
            201,
        )
        assert by_inspector["reported_by_user_id"] == U.INSPECTOR_USER_ID
        assert by_inspector["status"] == "REPORTED"
        assert by_inspector["disposition"] is None

        rows, meta = validate_paginated(
            api.list_casting_defects(QUALITY_INSPECTOR, casting_lot_id=lot_id)
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {by_partner["id"], by_inspector["id"]}

        lot = X.reread_casting_lot(api, lot_id)
        assert lot["qty_poured"] == 4
        assert lot["qty_accepted"] == 4
        assert lot["qty_scrapped"] == 0
        assert lot["qty_rework_pending"] == 0
        assertions.assert_piece_ledger_conserved(lot)

    def test_a_third_role_is_still_refused_the_shared_defect_endpoint(
        self, api, poured_lot
    ):
        """Sharing the endpoint between two roles does not open it to the rest.

        `POST /casting-lots/{id}/defects` authorises `FoundryPartner` and
        `QualityInspector`.  A `ProductionPlanner` is outside that pair, so the
        declared role is not among the roles authorised for the endpoint and the
        request is rejected with `ERR_UNAUTHORIZED`.  No defect row is created.

        Design: Corner/rbac/quality_inspector_and_foundry_partner_both_report_defects
        """
        lot_id = poured_lot["lot"]["id"]

        response = api.report_casting_defect(
            lot_id, F.casting_defect_payload(), PRODUCTION_PLANNER
        )
        validate_error(response, ApiErrorId.UNAUTHORIZED)

        _, meta = validate_paginated(
            api.list_casting_defects(PRODUCTION_PLANNER, casting_lot_id=lot_id)
        )
        assert meta["total_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Reads are shared by every role in the contract
# ─────────────────────────────────────────────────────────────────────────────
class TestSharedReadOperations:
    """Every role, including every one of the eight, may call every read endpoint."""

    @pytest.fixture
    def catalogue(self, api, foundry_partner_headers_factory):
        """One model to read, plus headers for all eight roles.

        Seven roles carry opaque identities.  `FoundryPartner` is entity-backed,
        so its `X-User-ID` must be the identifier of a real foundry row and the
        foundry has to exist before the headers can be built.
        """
        foundry = X.create_foundry(api)
        model = X.create_pump_model(api)
        headers_by_role = dict(U.HEADERS_BY_ROLE)
        headers_by_role[Role.FOUNDRY_PARTNER] = foundry_partner_headers_factory(
            foundry["id"]
        )
        assert set(headers_by_role) == set(ALL_ROLES)
        return {"model": model, "headers_by_role": headers_by_role}

    @pytest.mark.parametrize("role", ALL_ROLES)
    def test_every_role_can_read_pump_models_through_the_shared_get_operations(
        self, api, catalogue, role
    ):
        """The model detail and list endpoints answer identically for all eight roles.

        Read endpoints are not partitioned by role: the same registered HSC-14
        model is returned by `GET /pump-models/{id}` and by `GET /pump-models`
        whichever of the eight roles asks, with the same identifier, the same
        `ORDERABLE` status and the same 82.0 percent efficiency at best
        efficiency point.  The listing reports a single row for every caller, so
        no role sees a filtered slice of the catalogue.

        Design: Corner/rbac/every_role_can_read_pump_models_through_the_shared_get_operations
        """
        headers = catalogue["headers_by_role"][role]
        model_id = catalogue["model"]["id"]

        detail = validate_success(api.get_pump_model(model_id, headers), 200)
        assert detail["id"] == model_id
        assert detail["status"] == "ORDERABLE"
        assert detail["interchange_group"] == catalogue["model"]["interchange_group"]
        assert detail["bep_efficiency_pct"] == pytest.approx(82.0, abs=0.01)

        rows, meta = validate_paginated(api.list_pump_models(headers))
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [model_id]
