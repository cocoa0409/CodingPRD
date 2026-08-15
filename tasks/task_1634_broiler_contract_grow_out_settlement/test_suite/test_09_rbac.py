"""Role-based access control and ownership checks (PRD §2.1, §4)."""
from test_helpers import (
    ANONYMOUS_HEADERS,
    ApiErrorId,
    TEST_USERS,
    create_biosecurity_audit_payload,
    create_contract_payload,
    create_feed_delivery_payload,
    create_grower_payload,
    create_house_payload,
    create_mortality_report_payload,
    create_settlement_group_payload,
    get_success_data,
    make_grower_headers,
    plan_flock,
    place_flock,
    set_logical_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def _placed_flock(api, *, grower_code, full_name, house_no, contract_no,
                  group_code, flock_no, head_count=1000):
    """Grower + house + ACTIVE contract + group + flock in PLACED."""
    set_logical_clock("2026-08-01T00:00:00Z")
    grower = get_success_data(
        api.create_grower(create_grower_payload(grower_code=grower_code,
                                                full_name=full_name), ADMIN))
    house = get_success_data(
        api.create_house(create_house_payload(grower["id"], house_no=house_no,
                                              capacity_birds=5000), ADMIN))
    contract = get_success_data(
        api.create_contract(create_contract_payload(grower["id"],
                                                    contract_no=contract_no),
                            ADMIN))
    get_success_data(api.activate_contract(contract["id"], ADMIN))
    group = get_success_data(
        api.create_settlement_group(
            create_settlement_group_payload(group_code=group_code,
                                            week_ending_date="2026-12-31"),
            ANALYST))
    flock = plan_flock(house["id"], contract["id"], group["id"], flock_no)
    place_flock(flock["id"], "2026-08-01", head_count)
    return grower, house, contract, group, flock


class TestRoleDenials:
    def test_grower_cannot_create_feed_delivery(self, api):
        """PRD §2.1: "A request whose role is not permitted to invoke the
        target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)".
        PRD §4: the record-feed-delivery endpoint is authorized for
        IntegratorAdmin only.

        Design: Corner/rbac/grower_cannot_create_feed_delivery
        """
        grower, _h, _c, _grp, flock = _placed_flock(
            api, grower_code="G-RB1", full_name="Rbac One", house_no="H1",
            contract_no="C-RB1", group_code="WK-RB1", flock_no="F-RB1")

        resp = api.record_feed_delivery(
            flock["id"],
            create_feed_delivery_payload(delivered_date="2026-08-05",
                                         feed_lbs=1000, feed_type="STARTER",
                                         ticket_no="FT-RB1"),
            make_grower_headers(grower["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

        deliveries = validate_success(
            api.list_feed_deliveries(flock["id"], ADMIN))
        assert deliveries == [], "the rejected call must not record a delivery"

    def test_settlement_analyst_cannot_record_audit(self, api, analyst_headers):
        """PRD §2.1: "A request whose role is not permitted to invoke the
        target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)".
        PRD §4: the record-biosecurity-audit endpoint is authorized for
        ServiceTech only.

        Design: Corner/rbac/settlement_analyst_cannot_record_audit
        """
        grower = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-RB3",
                                                    full_name="Rbac Three"),
                              ADMIN))
        house = get_success_data(
            api.create_house(create_house_payload(grower["id"], house_no="H1",
                                                  capacity_birds=5000), ADMIN))

        resp = api.record_audit(
            house["id"],
            create_biosecurity_audit_payload(audit_date="2026-08-10",
                                             result="PASS", quarantine_days=0),
            analyst_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestGrowerOwnership:
    def test_grower_cannot_touch_other_growers_flock_mortality(self, api):
        """PRD §2.1: "the same `ERR_UNAUTHORIZED` is raised when an
        entity-backed ownership check fails, such as a `Grower` attempting to
        act on a resource belonging to another grower."
        PRD §2.1: "When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of
        the acting `Grower` record; ownership checks on any resource that
        references a `Grower` (directly, or through the house-to-grower chain
        on a flock or settlement) compare that resource's foreign-key field to
        `X-User-ID`."

        Design: Corner/rbac/grower_cannot_touch_other_growers_flock_mortality
        """
        grower1, _h, _c, group, flock1 = _placed_flock(
            api, grower_code="G-RB2A", full_name="Rbac Two A", house_no="H1",
            contract_no="C-RB2A", group_code="WK-RB2", flock_no="F-RB2A")
        grower2 = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-RB2B",
                                                    full_name="Rbac Two B"),
                              ADMIN))

        resp = api.record_mortality_report(
            flock1["id"],
            create_mortality_report_payload(report_date="2026-08-10",
                                            dead_head=10, condemned_head=0),
            make_grower_headers(grower2["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

        flock = validate_success(api.get_flock(flock1["id"], ADMIN))
        assert flock["mortality_head"] == 0, \
            "the other grower's rejected report must not accumulate"


class TestAuthentication:
    def test_unauthenticated_request_rejected(self, api):
        """PRD §2.1: "Every request must include `X-User-ID` identifying the
        acting user and `X-User-Role` naming their operational capacity."
        PRD §2.1: "A request missing either header, or carrying an
        `X-User-Role` value outside this declared set, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/unauthenticated_request_rejected
        """
        grower = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-RB4",
                                                    full_name="Rbac Four"),
                              ADMIN))

        resp = api.get_grower(grower["id"], ANONYMOUS_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
