"""Shop drawing revision cycle, OCC on order version, and version pinning."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    validate_success, validate_error, get_success_data,
    make_project, make_order, make_opening, configure_order, make_drawing,
    submit_drawing, approve_drawing, reject_drawing, void_drawing,
    get_order, get_drawing, H,
)

PM_H = TEST_USERS["plant_manager_headers"]
EST_H = TEST_USERS["estimator_headers"]
ANY_H = TEST_USERS["any_headers"]


def _configured_rated_order(contract_code, order_code="O-4001"):
    """MAPLE TEMPLATE_PREP MIN_20 order, CONFIGURED, with one 1-leaf rated opening."""
    project = make_project(name="Cycle Proj", site_address="5 Elm St", contract_code=contract_code)
    template = get_success_data(api_client.create_hardware_template(
        {"template_code": "T-C1", "manufacturer": "ACME", "fire_rated_compatible": True}, PM_H,
    ))
    order = make_order(project["id"], order_code=order_code, species="MAPLE", profile_code="PR-7",
                       hardware_prep_mode="TEMPLATE_PREP", fire_rating_required="MIN_20",
                       hardware_template_id=template["id"])
    make_opening(order["id"], opening_no="1", leaf_count=1, fire_rating="MIN_20")
    configure_order(order["id"])
    return project, order


class TestDrawingRevisionCycle:
    def test_rejected_revision_loops_order_back_to_configured(self, api):
        """PRD §3.3: "Rejection moves the drawing from `SUBMITTED` to
        `REJECTED`, records `reviewed_by` and the `review_note`, and returns
        the order from `SUBMITTED` to `CONFIGURED`."

        Design: Difficulty/non_linear_state_machine/shop_drawing_revision_cycle_with_supersede
        """
        _, order = _configured_rated_order("C-4001A")
        drawing1 = make_drawing(order["id"])
        assert drawing1["revision_no"] == 1
        assert drawing1["supersedes_drawing_id"] is None, "null on the first revision"

        submitted = submit_drawing(drawing1["id"], user_id="est-1")
        assert submitted["submitted_by"] == "est-1"
        assert get_order(order["id"])["status"] == "SUBMITTED", (
            "submission cascades the order CONFIGURED -> SUBMITTED"
        )

        rejected = reject_drawing(drawing1["id"], user_id="arch-1", review_note="redesign stile")
        assert rejected["status"] == "REJECTED"
        assert rejected["reviewed_by"] == "arch-1"
        order_after = get_order(order["id"])
        assert order_after["status"] == "CONFIGURED", (
            "rejection returns the order to CONFIGURED"
        )

    def test_approval_change_order_and_next_revision_supersede_chain(self, api):
        """PRD §3.3: "The server assigns `revision_no` as one greater than the
        count of the order's existing drawings, links `supersedes_drawing_id`
        to the previous revision (null on the first)". PRD §3.3: "the cascade
        mirrors approval in reverse: the approved drawing moves to `SUPERSEDED`,
        its programs in `CREATED`, `SETUP_BOOKED`, or `PROVEN` move to `VOIDED`,
        their booked slots move to `CANCELLED`, `config_locked` returns to
        false".

        Design: Difficulty/non_linear_state_machine/shop_drawing_revision_cycle_with_supersede
        """
        _, order = _configured_rated_order("C-4001B")
        # rev1: rejected.
        drawing1 = make_drawing(order["id"])
        submit_drawing(drawing1["id"], user_id="est-1")
        reject_drawing(drawing1["id"], user_id="arch-1", review_note="redesign stile")

        # rev2: approved.
        drawing2 = make_drawing(order["id"])
        assert drawing2["revision_no"] == 2
        assert drawing2["supersedes_drawing_id"] == drawing1["id"]
        submit_drawing(drawing2["id"], user_id="est-1")
        approve_drawing(drawing2["id"], user_id="arch-1")
        assert get_order(order["id"])["status"] == "APPROVED"

        # Change order supersedes the approved revision and unlocks config.
        validate_success(api.change_order(order["id"], EST_H), 200)
        assert get_drawing(drawing2["id"])["status"] == "SUPERSEDED"
        order_after = get_order(order["id"])
        assert order_after["status"] == "CONFIGURED"
        assert order_after["config_locked"] is False

        # rev3 chains onto rev2.
        drawing3 = make_drawing(order["id"])
        assert drawing3["revision_no"] == 3
        assert drawing3["supersedes_drawing_id"] == drawing2["id"]
        assert drawing3["status"] == "DRAFT"
        assert get_drawing(drawing1["id"])["status"] == "REJECTED"


class TestDrawingTerminalAndOcc:
    def test_rejected_drawing_terminal_lockdown(self, api):
        """PRD §3.3: "`REJECTED`, `SUPERSEDED`, and `VOID` are terminal, and
        any other drawing pair fails with `ERR_INVALID_DRAWING_STATUS_TRANSITION`."

        Design: Corner/state_machines/rejected_drawing_terminal_lockdown
        """
        _, order = _configured_rated_order("CS-4", order_code="O-R")
        drawing = make_drawing(order["id"])
        submit_drawing(drawing["id"], user_id="est-1")
        reject_drawing(drawing["id"], user_id="arch-1")

        resp = api.set_shop_drawing_status(
            drawing["id"], {"target_status": "APPROVED"}, H("Architect", "arch-2"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DRAWING_STATUS_TRANSITION, 409)
        assert get_drawing(drawing["id"])["status"] == "REJECTED"

    def test_occ_stale_order_version_on_drawing_create(self, api):
        """PRD §2.6: "If `expected_order_version` differs from the order's
        current `version` — because another writer has advanced the order since
        the client last read it — the create is rejected with
        `ERR_STALE_ORDER_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_order_version_on_drawing_create
        """
        project = make_project(name="P", contract_code="CX-1")
        order = make_order(project["id"], order_code="O-X1")
        make_opening(order["id"], opening_no="1")
        configured = configure_order(order["id"])
        stale_version = configured["version"]

        # First create advances the order's version; void it so the
        # single-active-drawing gate is satisfied for the retry.
        drawing1 = validate_success(api.create_shop_drawing(
            {"order_id": order["id"], "expected_order_version": stale_version}, EST_H,
        ), 201)
        void_drawing(drawing1["id"], user_id="est-1")

        # The stale captured version is now rejected with 412.
        resp = api.create_shop_drawing(
            {"order_id": order["id"], "expected_order_version": stale_version}, EST_H,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION, 412)

        # A fresh read yields the advanced version and the retry succeeds.
        fresh_version = get_order(order["id"])["version"]
        assert fresh_version == stale_version + 1, (
            "the first create advanced the order version by exactly one"
        )
        drawing2 = validate_success(api.create_shop_drawing(
            {"order_id": order["id"], "expected_order_version": fresh_version}, EST_H,
        ), 201)
        assert drawing2["status"] == "DRAFT"


class TestVersionPinning:
    def test_version_pinning_snapshot_and_config_lock(self, api):
        """PRD §3.3: "snapshots the order's current configuration into
        `pinned_species`, `pinned_profile_code`, `pinned_sheen_target`,
        `pinned_fire_rating_required`, and `pinned_hardware_prep_mode`".
        PRD §3.2: "Once the order has moved past `CONFIGURED` the configuration
        is locked (`config_locked` true from approval onward), and edit
        attempts fail with `ERR_ORDER_CONFIG_LOCKED`." PRD §3.3: "Creation is
        only meaningful against a `CONFIGURED` order — anything else fails with
        `ERR_ORDER_NOT_CONFIGURED`".

        Design: Corner/cross_cutting_complexity_layers/version_pinning_snapshot_and_config_lock
        """
        project = make_project(name="P", contract_code="CX-3")
        order = make_order(project["id"], order_code="O-X3", species="MAPLE",
                           profile_code="PR-7", fire_rating_required="NONE")
        make_opening(order["id"], opening_no="1", fire_rating="NONE")
        configure_order(order["id"])
        drawing = make_drawing(order["id"])

        # Edit the order while still CONFIGURED; the snapshot must stay MAPLE.
        validate_success(api.update_order(order["id"], {"species": "WALNUT"}, EST_H), 200)
        pinned = get_drawing(drawing["id"])
        assert pinned["pinned_species"] == "MAPLE", (
            "snapshot frozen at creation despite the WALNUT edit"
        )

        submit_drawing(drawing["id"], user_id="est-1")
        approve_drawing(drawing["id"], user_id="arch-1")

        # APPROVED orders reject config edits.
        resp = api.update_order(order["id"], {"species": "OAK"}, EST_H)
        validate_error(resp, ApiErrorId.ERR_ORDER_CONFIG_LOCKED, 409)

        # The pre-approval edit persisted.
        order_now = get_order(order["id"])
        assert order_now["species"] == "WALNUT"

        # No new drawing may be created while the order is APPROVED.
        resp = api.create_shop_drawing(
            {"order_id": order["id"], "expected_order_version": order_now["version"]}, EST_H,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CONFIGURED, 409)
