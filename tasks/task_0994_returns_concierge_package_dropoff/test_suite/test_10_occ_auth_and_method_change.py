"""Optimistic concurrency control on the four OCC-guarded writes, the
authentication floor, and the method-change operation that voids labels and
releases reservations."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_order_to_tote,
    book_pickup,
    change_method_payload,
    create_counter_order_dropped_off,
    create_location,
    create_order,
    create_return_item_line,
    drive_pickup_collect,
    issue_label,
    issue_label_payload,
    make_location_operator_headers,
    make_support_agent_headers,
    open_exception,
    setup_commercial_spine,
    setup_tote_with_route,
    start_investigation,
    tote_membership_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT_A = make_support_agent_headers("agent-a")
AGENT_B = make_support_agent_headers("agent-b")


class TestAuthentication:

    def test_caller_missing_header_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity
        in which they act. A request missing either header, or carrying a role
        the system does not declare, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/caller_missing_header_returns_unauthenticated
        """
        from test_helpers import NON_EXISTENT_ID, api_client
        # No X-User-ID / X-User-Role headers at all.
        resp = api_client._request(
            "GET", f"/v1/return-orders/{NON_EXISTENT_ID}", headers={}
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestOccLabelIssue:

    def test_occ_label_issue_stale_version_rejected(self, api):
        """PRD §2.7: "Issuing a label for a return order requires
        `expected_return_order_version` matching the order's current
        `version`. Because issuing a label legitimately supersedes the prior
        active one, a writer holding a stale view of the order — for example,
        unaware another label was just issued — must be refused." "if the
        presented value does not equal the parent resource's current
        `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP
        412)".

        Design: Corner/cross_cutting_layers/occ_label_issue_stale_version_rejected
        """
        spine = setup_commercial_spine(shopper_email="so1@x.com")
        order = create_order(spine, method="COUNTER_DROP")
        stale_version = order["version"]

        label1 = issue_label(order, label_type="CARRIER_LABEL")
        assert label1["status"] == "ISSUED"

        # Replay with the pre-first-issue version -> 412.
        resp = api.issue_label(
            order["id"],
            issue_label_payload("QR_CODE", stale_version),
            spine["shopper_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestOccMethodChange:

    def test_occ_method_change_stale_version_rejected(self, api):
        """PRD §2.7: "Changing an order's fulfilment method likewise requires
        `expected_return_order_version` matching the order's current
        `version`, because the change voids the active label and releases the
        reservation whose existence the stale client could not have seen."
        PRD §3.3: "A method change applies the same dimension and feature
        gates as creation, voids any active label, releases any held
        reservation and empties its slot, returns the order to `INITIATED`,
        and increments the order's `version` by one."

        Design: Corner/cross_cutting_layers/occ_method_change_stale_version_rejected
        """
        spine = setup_commercial_spine(shopper_email="so2@x.com")
        order = create_order(spine, method="COUNTER_DROP")
        stale_version = order["version"]
        issue_label(order, label_type="CARRIER_LABEL")  # version advances

        blocked = api.change_return_order_method(
            order["id"],
            change_method_payload("HOME_PICKUP", stale_version),
            spine["shopper_headers"],
        )
        validate_error(blocked, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        # Fresh retry at the current version succeeds and returns the order
        # to INITIATED with the label voided.
        changed = validate_success(
            api.change_return_order_method(
                order["id"],
                change_method_payload("HOME_PICKUP", stale_version + 1),
                spine["shopper_headers"],
            )
        )
        assert changed["status"] == "INITIATED"
        assert changed["method"] == "HOME_PICKUP"
        assert changed["version"] == stale_version + 2


class TestOccToteMembership:

    def test_occ_tote_membership_stale_version_rejected(self, api):
        """PRD §2.7: "Adding a member order to a consolidation tote, and the
        symmetric removal, both require `expected_tote_version` matching the
        tote's current `version`: capacity decisions on unit and weight
        headroom were computed from a manifest that may since have changed."

        Design: Corner/cross_cutting_layers/occ_tote_membership_stale_version_rejected
        """
        spine = setup_commercial_spine(
            plan_overrides={"pickup_enabled": False}, shopper_email="so3@x.com"
        )
        location = create_location(name="L-O3", kind="COUNTER")
        route, tote = setup_tote_with_route(location)
        stale_tote_version = tote["version"]

        order1 = create_counter_order_dropped_off(spine, location)
        order2 = create_counter_order_dropped_off(
            spine, location,
            items=[create_return_item_line(sku="O3B")],
        )

        # First add advances the tote version.
        tote_mid = add_order_to_tote(tote, order1, location["id"])

        # Replay second add at the pre-first version -> 412.
        blocked = api.add_order_to_tote(
            tote["id"],
            tote_membership_payload(order2["id"], stale_tote_version),
            make_location_operator_headers(location["id"]),
        )
        validate_error(blocked, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        # Fresh retry succeeds.
        tote_after = add_order_to_tote(tote_mid, order2, location["id"])
        assert tote_after["manifest_units"] == 2


class TestOccExceptionResolve:

    def test_occ_exception_resolve_stale_version_rejected(self, api):
        """PRD §2.7: "Resolving an exception case requires
        `expected_exception_case_version` matching the case's current
        `version`: an appeal, a shopper response, or a prior resolution may
        have altered the case state on which the resolver based the
        decision."

        Design: Corner/cross_cutting_layers/occ_exception_resolve_stale_version_rejected
        """
        from test_helpers import resolve_exception_payload
        spine = setup_commercial_spine(shopper_email="so4@x.com", with_zone=True)
        order = create_order(spine, method="HOME_PICKUP", boxless=True,
                             items=[create_return_item_line(sku="O4")])
        appointment = book_pickup(order, spine["zone"])
        drive_pickup_collect(appointment["id"])

        case = open_exception(order["id"], "LOST_PARCEL", note="occ",
                              opener_headers=AGENT_A)
        stale_version = case["version"]
        case_investigating = start_investigation(case["id"], headers=AGENT_A)

        # Resolve carrying the pre-investigation version -> 412.
        blocked = api.resolve_exception_case(
            case["id"],
            resolve_exception_payload("APPROVED", stale_version),
            AGENT_B,
        )
        validate_error(blocked, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        # Fresh version resolves.
        resolved = validate_success(
            api.resolve_exception_case(
                case["id"],
                resolve_exception_payload(
                    "APPROVED", case_investigating["version"]
                ),
                AGENT_B,
            )
        )
        assert resolved["status"] == "RESOLVED_APPROVED"
