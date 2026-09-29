"""Role-based access control across the six declared roles.

Each endpoint publishes an authorized-role list, and a role outside that list is
refused before the body is ever inspected.  The exclusive writes (catalogue,
publication, evidence capture, countersignature, downstream shipment, the clock)
are checked from both sides, the two shared surfaces are checked for both of
their permitted roles, and the segregation-of-duties rule that separates the
counsel who suspends from the counsel who terminates is checked in both
directions.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    BCM_HEADERS,
    COUNSEL_2_HEADERS,
    COUNSEL_HEADERS,
    api_client,
)
from test_helpers.assertions import assert_same_instant, violation_points
from test_helpers.constants import EVIDENCE_HASH_1, EVIDENCE_HASH_3
from test_helpers.factories import (
    notice_payload,
    observation_payload,
    policy_publish_payload,
    product_payload,
    ship_downstream_payload,
)
from test_helpers.fixtures import (
    approve_exception,
    create_active_agreement,
    create_approved_policy,
    create_detected_violation,
    create_distributor,
    create_product,
    create_published_policy,
    create_reseller,
    create_sent_agreement,
    create_serial_unit,
    current_reseller_version,
    issue_notice,
    pin_clock,
    read_agreement,
    read_exception,
    read_policy,
    read_product,
    read_reseller,
    read_serial_unit,
    read_violation,
    request_exception,
)
from test_helpers.test_users import (
    ANALYST_1,
    COUNSEL_1,
    COUNSEL_2,
    make_distributor_headers,
    make_reseller_headers,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
CLOCK_AUG_25 = "2026-08-25T00:00:00Z"
CLOCK_AUG_31 = "2026-08-31T00:00:00Z"
CLOCK_SEP_30 = "2026-09-30T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"
OBSERVED_AUG_19 = "2026-08-19T00:00:00Z"
SUSPENSION_STARTS = "2026-09-01T00:00:00Z"
SUSPENSION_ENDS = "2026-09-10T00:00:00Z"
EXCEPTION_STARTS = "2026-08-10T00:00:00Z"
EXCEPTION_ENDS = "2026-08-25T00:00:00Z"

POLICY_CODE = "MAP-2026-A"
STANDARD_FLOOR = 15000
MSRP = 20000


# --------------------------------------------------------------------------- #
# Shared setup helpers
# --------------------------------------------------------------------------- #
def _setup_published_policy():
    """Policy MAP-2026-A PUBLISHED and effective at the default clock."""
    pin_clock(CLOCK_AUG_01)
    return create_published_policy(policy_code=POLICY_CODE)


def _setup_product(sku="SKU-AUDIO-1"):
    """A published policy plus one catalogue item with a 15000 standard floor."""
    policy = _setup_published_policy()
    product = create_product(
        policy["id"], sku=sku, msrp_cents=MSRP, standard_map_floor_cents=STANDARD_FLOOR
    )
    return policy, product


def _setup_authorized_reseller(policy_id):
    """Reseller Acme carried to AUTHORIZED / OPEN under an ACTIVE agreement."""
    reseller = create_reseller(
        legal_name="Acme Retail LLC",
        contact_email="ops@acme.example",
        primary_channel="MARKETPLACE",
    )
    agreement = create_active_agreement(
        reseller["id"], policy_id, permitted_channels=["MARKETPLACE", "OWN_WEBSITE"]
    )
    return read_reseller(reseller["id"]), agreement


def _setup_unit_with_distributor(sku="SKU-AUDIO-1", serial_number="SN-0002"):
    """Northwind holds one serialized unit; Acme is AUTHORIZED with supply OPEN."""
    policy, product = _setup_product(sku=sku)
    reseller, _agreement = _setup_authorized_reseller(policy["id"])
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    unit = create_serial_unit(
        product["id"], distributor["id"], serial_number=serial_number, lot_code="LOT-A"
    )
    return {
        "policy": policy,
        "product": product,
        "reseller": reseller,
        "distributor": distributor,
        "unit": unit,
    }


# --------------------------------------------------------------------------- #
# POST /products — the catalogue write and the role that holds it
# --------------------------------------------------------------------------- #
def test_the_brand_channel_manager_is_the_role_that_registers_a_product():
    """Catalogue registration succeeds for the one role the endpoint publishes.

    PRD: "If both headers are well formed but the named role does not appear in the
    authorized-role list published for the requested endpoint in §4, the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." "Creation endpoints — those
    that mint a brand-new row — return HTTP 201 on success." "`lifecycle_status` is
    the commercial stage and defaults to `ACTIVE`, with `CLEARANCE` and `DISCONTINUED`
    as its other values; it is the gate on which exception types may be approved."

    Design: Corner/rbac/rbac_brand_channel_manager_can_create_products
    """
    policy = _setup_published_policy()

    product = validate_success(
        api_client.create_product(
            product_payload(
                policy["id"],
                sku="SKU-RBAC-1",
                name="RBAC Probe",
                msrp_cents=MSRP,
                standard_map_floor_cents=STANDARD_FLOOR,
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )

    assert product["sku"] == "SKU-RBAC-1"
    assert product["lifecycle_status"] == "ACTIVE"
    assert product["governing_policy_id"] == policy["id"]
    assert read_product(product["id"])["lifecycle_status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# POST /products — refused for a role the endpoint does not list
# --------------------------------------------------------------------------- #
def test_a_monitoring_analyst_cannot_register_a_product_despite_a_valid_body():
    """A role outside the endpoint's list is refused before the body is used.

    PRD: "If both headers are well formed but the named role does not appear in the
    authorized-role list published for the requested endpoint in §4, the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." "Checks are evaluated in the
    following order, and the first failure short-circuits the request:"

    Design: Corner/rbac/rbac_monitoring_analyst_cannot_create_products_rejected
    """
    policy = _setup_published_policy()

    validate_error(
        api_client.create_product(
            product_payload(
                policy["id"],
                sku="SKU-RBAC-2",
                name="Analyst Probe",
                msrp_cents=MSRP,
                standard_map_floor_cents=STANDARD_FLOOR,
            ),
            ANALYST_HEADERS,
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    rows, meta = validate_paginated(api_client.list_products(BCM_HEADERS, params={"limit": 100}))
    assert meta["total_count"] == 0
    assert rows == []


# --------------------------------------------------------------------------- #
# Policy publication — counsel's exclusive act
# --------------------------------------------------------------------------- #
def test_brand_legal_counsel_publishes_and_is_stamped_as_the_publisher():
    """Publication is counsel's act and records the acting counsel's identifier.

    PRD: "Publication, also a `BrandLegalCounsel` act, moves the document `APPROVED →
    PUBLISHED`." "The transition stores `effective_from`, stamps
    `published_by_user_id` with the publishing counsel's `X-User-ID`, and advances the
    policy's `version`."

    Design: Corner/rbac/rbac_brand_legal_counsel_can_publish_policy
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_approved_policy(policy_code=POLICY_CODE)
    assert policy["status"] == "APPROVED"

    published = validate_success(
        api_client.publish_policy(
            policy["id"], policy_publish_payload(CLOCK_AUG_01), COUNSEL_2_HEADERS
        )
    )

    assert published["status"] == "PUBLISHED"
    assert published["published_by_user_id"] == COUNSEL_2
    assert_same_instant(published["effective_from"], CLOCK_AUG_01, "effective_from")


# --------------------------------------------------------------------------- #
# Policy publication — refused for the drafting manager
# --------------------------------------------------------------------------- #
def test_the_manager_who_drafted_the_policy_still_cannot_publish_it():
    """Publication stays counsel-exclusive even for the policy's own author.

    PRD: "If both headers are well formed but the named role does not appear in the
    authorized-role list published for the requested endpoint in §4, the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." "The new policy is born in
    status `DRAFT` with `revision_number` set to 1, and its `effective_from`,
    `legal_review_notes`, `reviewed_by_user_id`, `published_by_user_id`,
    `superseded_by_policy_id` and `withdrawn_reason` all null." "The transition stores
    `effective_from`, stamps `published_by_user_id` with the publishing counsel's
    `X-User-ID`, and advances the policy's `version`."

    Design: Corner/rbac/rbac_brand_channel_manager_cannot_publish_policy_rejected
    """
    pin_clock(CLOCK_AUG_01)
    policy = create_approved_policy(policy_code=POLICY_CODE)

    validate_error(
        api_client.publish_policy(
            policy["id"], policy_publish_payload(CLOCK_AUG_01), BCM_HEADERS
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    unchanged = read_policy(policy["id"])
    assert unchanged["status"] == "APPROVED"
    assert unchanged["effective_from"] is None
    assert unchanged["published_by_user_id"] is None


# --------------------------------------------------------------------------- #
# Evidence capture — the analyst's exclusive act
# --------------------------------------------------------------------------- #
def test_the_monitoring_analyst_captures_evidence_and_is_recorded_on_the_row():
    """Evidence capture succeeds for the analyst and stamps the capturing identity.

    PRD: "A `MonitoringAnalyst` is the only actor who may capture evidence." "The row
    is created with `evaluation_status` `CAPTURED`, `unauthorized_seller_confirmed`
    false, `evidence_captured_by_user_id` stamped from the capturing analyst's
    `X-User-ID`, and all five computed money fields —
    `allocated_component_price_cents`, `effective_advertised_price_cents`,
    `effective_map_floor_cents`, `deviation_cents` and `deviation_pct` — still null."

    Design: Corner/rbac/rbac_monitoring_analyst_can_capture_observations
    """
    _policy, product = _setup_product()
    pin_clock(CLOCK_AUG_20)

    observation = validate_success(
        api_client.create_observation(
            observation_payload(
                product["id"],
                channel="MARKETPLACE",
                seller_display_name="RBAC Store",
                listing_url="https://mkt.example/l/rbac",
                listed_price_cents=14000,
                observed_at=OBSERVED_AUG_18,
                evidence_hash=EVIDENCE_HASH_1,
            ),
            ANALYST_HEADERS,
        ),
        expected_status=201,
    )

    assert observation["evidence_captured_by_user_id"] == ANALYST_1
    assert observation["evaluation_status"] == "CAPTURED"
    assert observation["unauthorized_seller_confirmed"] is False
    assert observation["effective_advertised_price_cents"] is None


# --------------------------------------------------------------------------- #
# Evidence capture — refused for the monitored reseller
# --------------------------------------------------------------------------- #
def test_a_reseller_cannot_self_report_evidence_about_its_own_listing():
    """The evidence chain is closed to the party being monitored.

    PRD: "A `MonitoringAnalyst` is the only actor who may capture evidence." "If both
    headers are well formed but the named role does not appear in the authorized-role
    list published for the requested endpoint in §4, the request is rejected with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/rbac_reseller_cannot_capture_observations_rejected
    """
    policy, product = _setup_product()
    reseller, _agreement = _setup_authorized_reseller(policy["id"])
    assert reseller["authorization_status"] == "AUTHORIZED"
    pin_clock(CLOCK_AUG_20)

    validate_error(
        api_client.create_observation(
            observation_payload(
                product["id"],
                channel="MARKETPLACE",
                seller_display_name="Acme Store",
                listing_url="https://mkt.example/l/self",
                listed_price_cents=STANDARD_FLOOR,
                observed_at=OBSERVED_AUG_18,
                evidence_hash=EVIDENCE_HASH_1,
            ),
            make_reseller_headers(reseller["id"]),
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    rows, meta = validate_paginated(
        api_client.list_observations(ANALYST_HEADERS, params={"limit": 100})
    )
    assert meta["total_count"] == 0
    assert rows == []


# --------------------------------------------------------------------------- #
# Agreement response — the reseller's exclusive act
# --------------------------------------------------------------------------- #
def test_the_reseller_countersigns_its_own_agreement_and_is_recorded_as_signer():
    """Countersignature is the reseller's own act and records its identifier.

    PRD: "A `decision` of `COUNTERSIGN` moves it `SENT → COUNTERSIGNED`: it stamps
    `countersigned_at` with the current clock, records `countersigned_by_user_id` from
    the acting reseller's `X-User-ID`, and sets `non_negotiation_acknowledged` from the
    supplied `non_negotiation_acknowledged` flag."

    Design: Corner/rbac/rbac_reseller_can_respond_to_its_own_agreement
    """
    policy = _setup_published_policy()
    reseller = create_reseller(
        legal_name="Acme Retail LLC",
        contact_email="ops@acme.example",
        primary_channel="MARKETPLACE",
    )
    agreement = create_sent_agreement(
        reseller["id"], policy["id"], permitted_channels=["MARKETPLACE", "OWN_WEBSITE"]
    )
    assert agreement["status"] == "SENT"

    responded = validate_success(
        api_client.respond_agreement(
            agreement["id"],
            {"decision": "COUNTERSIGN", "non_negotiation_acknowledged": True},
            make_reseller_headers(reseller["id"]),
        )
    )

    assert responded["status"] == "COUNTERSIGNED"
    assert responded["countersigned_by_user_id"] == reseller["id"]
    assert responded["non_negotiation_acknowledged"] is True


# --------------------------------------------------------------------------- #
# Agreement response — refused for the brand side
# --------------------------------------------------------------------------- #
def test_the_brand_cannot_countersign_on_the_resellers_behalf():
    """Responding belongs to the reseller alone; the brand side is refused.

    PRD: "If both headers are well formed but the named role does not appear in the
    authorized-role list published for the requested endpoint in §4, the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." "Sending the agreement out for
    countersignature moves it `DRAFT → SENT`." "A fresh agreement is created in status
    `DRAFT` with `non_negotiation_acknowledged` false and with `sent_at`,
    `countersigned_at`, `countersigned_by_user_id`, `activated_at` and `closed_reason`
    all null."

    Design: Corner/rbac/rbac_brand_channel_manager_cannot_respond_to_agreement_rejected
    """
    policy = _setup_published_policy()
    reseller = create_reseller(
        legal_name="Acme Retail LLC",
        contact_email="ops@acme.example",
        primary_channel="MARKETPLACE",
    )
    agreement = create_sent_agreement(
        reseller["id"], policy["id"], permitted_channels=["MARKETPLACE", "OWN_WEBSITE"]
    )

    validate_error(
        api_client.respond_agreement(
            agreement["id"],
            {"decision": "COUNTERSIGN", "non_negotiation_acknowledged": True},
            BCM_HEADERS,
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    unchanged = read_agreement(agreement["id"])
    assert unchanged["status"] == "SENT"
    assert unchanged["non_negotiation_acknowledged"] is False
    assert unchanged["countersigned_by_user_id"] is None


# --------------------------------------------------------------------------- #
# Downstream shipment — the distributor's exclusive act
# --------------------------------------------------------------------------- #
def test_the_distributor_records_the_downstream_hop_for_its_own_unit():
    """The custody move succeeds for the distributor named on the shipping record.

    PRD: "Supplying a `downstream_reseller_id` moves a unit `SHIPPED_TO_DISTRIBUTOR →
    SHIPPED_TO_RESELLER`, setting `downstream_reseller_id` and stamping
    `shipped_downstream_at` with the current clock, and advancing the unit's
    `version`."

    Design: Corner/rbac/rbac_distributor_can_ship_downstream
    """
    world = _setup_unit_with_distributor()
    assert world["reseller"]["supply_status"] == "OPEN"
    assert world["unit"]["status"] == "SHIPPED_TO_DISTRIBUTOR"

    shipped = validate_success(
        api_client.ship_downstream(
            world["unit"]["id"],
            ship_downstream_payload(world["reseller"]["id"]),
            make_distributor_headers(world["distributor"]["id"]),
        )
    )

    assert shipped["status"] == "SHIPPED_TO_RESELLER"
    assert shipped["downstream_reseller_id"] == world["reseller"]["id"]
    assert_same_instant(shipped["shipped_downstream_at"], CLOCK_AUG_01, "shipped_downstream_at")


# --------------------------------------------------------------------------- #
# Downstream shipment — refused for a reader of the supply chain
# --------------------------------------------------------------------------- #
def test_a_monitoring_analyst_may_read_units_but_may_not_move_their_custody():
    """Reading the supply chain does not carry the right to move goods through it.

    PRD: "If both headers are well formed but the named role does not appear in the
    authorized-role list published for the requested endpoint in §4, the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." "The unit is created in custody
    state `SHIPPED_TO_DISTRIBUTOR` with `downstream_reseller_id`,
    `shipped_downstream_at` and `traced_at` all null, and the named distributor's
    `shipped_units_total` — which counts every unit whose `shipped_distributor_id` is
    that distributor, in any custody state — is increased accordingly."

    Design: Corner/rbac/rbac_monitoring_analyst_cannot_ship_downstream_rejected
    """
    world = _setup_unit_with_distributor()

    validate_error(
        api_client.ship_downstream(
            world["unit"]["id"],
            ship_downstream_payload(world["reseller"]["id"]),
            ANALYST_HEADERS,
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    unchanged = read_serial_unit(world["unit"]["id"], headers=ANALYST_HEADERS)
    assert unchanged["status"] == "SHIPPED_TO_DISTRIBUTOR"
    assert unchanged["downstream_reseller_id"] is None
    assert unchanged["shipped_downstream_at"] is None


# --------------------------------------------------------------------------- #
# The logical clock — the platform admin's exclusive capability
# --------------------------------------------------------------------------- #
def test_the_platform_admin_pins_the_logical_clock():
    """The clock capability answers for the one role that holds it.

    PRD: "A `PlatformAdmin` may pin the clock to an arbitrary instant by supplying a
    `to_iso8601` value; the response reports the new `current_utc` and the
    `previous_utc` it replaced."

    Design: Corner/rbac/rbac_platform_admin_can_set_the_clock
    """
    pin_clock(CLOCK_AUG_01)

    moved = validate_success(api_client.set_clock(CLOCK_AUG_31, ADMIN_HEADERS))

    assert_same_instant(moved["current_utc"], CLOCK_AUG_31, "current_utc")
    assert_same_instant(moved["previous_utc"], CLOCK_AUG_01, "previous_utc")


# --------------------------------------------------------------------------- #
# The logical clock — refused for every business role
# --------------------------------------------------------------------------- #
def test_no_business_role_may_move_the_logical_clock():
    """The manager who shares the sweep endpoint is still refused the clock.

    PRD: "If both headers are well formed but the named role does not appear in the
    authorized-role list published for the requested endpoint in §4, the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." "This is a test-driving
    capability, not a business operation, and it is the only way the clock ever moves."
    "The sweep responds with the `swept_at` instant it ran at and four counters:
    `expired_agreements`, `expired_exceptions`, `escalated_violations` and
    `reinstated_resellers`."

    Design: Corner/rbac/rbac_brand_channel_manager_cannot_set_the_clock_rejected
    """
    pin_clock(CLOCK_AUG_01)

    validate_error(
        api_client.set_clock(CLOCK_SEP_30, BCM_HEADERS),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    swept = validate_success(api_client.run_sweep(ADMIN_HEADERS))
    assert_same_instant(swept["swept_at"], CLOCK_AUG_01, "swept_at")


# --------------------------------------------------------------------------- #
# The policy read — a surface open to all six roles
# --------------------------------------------------------------------------- #
def test_the_distributor_can_read_the_published_rulebook():
    """The most restricted reader elsewhere still reads the policy document.

    PRD: "Policies may be read one at a time by every role, and the collection may be
    filtered by `status`, by `policy_code`, or by `superseded_by_policy_id` to find the
    revision a given policy displaced." "In the authorized-role column, **All roles**
    means all six of `BrandChannelManager`, `BrandLegalCounsel`, `MonitoringAnalyst`,
    `PlatformAdmin`, `Reseller` and `Distributor`; **Brand staff** means the four
    operator roles `BrandChannelManager`, `BrandLegalCounsel`, `MonitoringAnalyst` and
    `PlatformAdmin`."

    Design: Corner/rbac/rbac_policy_read_is_shared_by_all_six_roles
    """
    policy = _setup_published_policy()
    distributor = create_distributor(legal_name="Northwind Distribution")

    read = validate_success(
        api_client.get_pricing_policy(
            policy["id"], make_distributor_headers(distributor["id"])
        )
    )

    assert read["status"] == "PUBLISHED"
    assert read["policy_code"] == POLICY_CODE


def test_the_same_policy_read_answers_for_the_other_five_roles():
    """All six declared roles read the rulebook, not merely the brand staff.

    PRD: "Policies may be read one at a time by every role, and the collection may be
    filtered by `status`, by `policy_code`, or by `superseded_by_policy_id` to find the
    revision a given policy displaced." "The six roles are `BrandChannelManager`,
    `BrandLegalCounsel`, `MonitoringAnalyst`, `PlatformAdmin`, `Reseller` and
    `Distributor`."

    Design: Corner/rbac/rbac_policy_read_is_shared_by_all_six_roles
    """
    policy = _setup_published_policy()
    reseller = create_reseller(
        legal_name="Acme Retail LLC",
        contact_email="ops@acme.example",
        primary_channel="MARKETPLACE",
    )

    for headers in (
        BCM_HEADERS,
        COUNSEL_HEADERS,
        ANALYST_HEADERS,
        ADMIN_HEADERS,
        make_reseller_headers(reseller["id"]),
    ):
        read = validate_success(api_client.get_pricing_policy(policy["id"], headers))
        assert read["id"] == policy["id"]
        assert read["status"] == "PUBLISHED"
        assert read["policy_code"] == POLICY_CODE


# --------------------------------------------------------------------------- #
# The sweep — the one write shared by two roles
# --------------------------------------------------------------------------- #
def test_the_sweep_runs_for_the_manager_and_again_for_the_platform_admin():
    """Both declared sweep roles are accepted; the second run finds nothing due.

    PRD: "A `BrandChannelManager` or a `PlatformAdmin` runs it, and it processes four
    phases in the order given below, taking the affected rows within each phase in
    ascending `created_at` order so that the outcome is fully deterministic." "Second,
    exceptions in `APPROVED` whose `ends_at` is at or before the clock become `EXPIRED`
    and decrement their product's `open_exception_count`." "Running the sweep when
    nothing is due is legal and returns four zeroes."

    Design: Corner/rbac/rbac_sweep_is_shared_by_manager_and_admin
    """
    _policy, product = _setup_product()
    exception = request_exception(
        product["id"],
        exception_type="PROMOTIONAL_EVENT",
        starts_at=EXCEPTION_STARTS,
        ends_at=EXCEPTION_ENDS,
        channel_scope="ALL",
        requested_override_floor_cents=13000,
        dealer_input_source="BRAND_MARKETING_PLAN",
    )
    approved = approve_exception(exception["id"])
    assert approved["status"] == "APPROVED"
    assert read_product(product["id"])["open_exception_count"] == 1

    pin_clock(CLOCK_AUG_25)
    manager_sweep = validate_success(api_client.run_sweep(BCM_HEADERS))
    assert manager_sweep["expired_exceptions"] == 1
    assert_same_instant(manager_sweep["swept_at"], CLOCK_AUG_25, "swept_at")

    admin_sweep = validate_success(api_client.run_sweep(ADMIN_HEADERS))
    assert admin_sweep["expired_exceptions"] == 0
    assert_same_instant(admin_sweep["swept_at"], CLOCK_AUG_25, "swept_at")

    assert read_exception(exception["id"])["status"] == "EXPIRED"
    assert read_product(product["id"])["open_exception_count"] == 0


# --------------------------------------------------------------------------- #
# The violation list — closed to the distributor
# --------------------------------------------------------------------------- #
def test_the_violation_surface_is_closed_to_a_distributor():
    """A distributor probing for reseller enforcement data is refused.

    PRD: "If both headers are well formed but the named role does not appear in the
    authorized-role list published for the requested endpoint in §4, the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." "In the authorized-role column,
    **All roles** means all six of `BrandChannelManager`, `BrandLegalCounsel`,
    `MonitoringAnalyst`, `PlatformAdmin`, `Reseller` and `Distributor`; **Brand staff**
    means the four operator roles `BrandChannelManager`, `BrandLegalCounsel`,
    `MonitoringAnalyst` and `PlatformAdmin`."

    Design: Corner/rbac/rbac_distributor_cannot_read_violations_rejected
    """
    policy, product = _setup_product()
    reseller, _agreement = _setup_authorized_reseller(policy["id"])
    distributor = create_distributor(legal_name="Northwind Distribution")
    pin_clock(CLOCK_AUG_20)
    violation, _observation, _evaluation = create_detected_violation(
        product["id"],
        reseller["id"],
        listed_price_cents=14000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_18,
        listing_url="https://mkt.example/l/1",
    )
    assert violation["status"] == "DETECTED"

    params = {"reseller_id": reseller["id"], "limit": 10, "offset": 0}
    validate_error(
        api_client.list_violations(make_distributor_headers(distributor["id"]), params=params),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    rows, meta = validate_paginated(api_client.list_violations(ANALYST_HEADERS, params=params))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == violation["id"]


# --------------------------------------------------------------------------- #
# The serial-unit list — closed to the reseller
# --------------------------------------------------------------------------- #
def test_the_serial_unit_surface_is_closed_to_a_reseller():
    """The mirror-image exclusion: neither channel peer sees the other's data.

    PRD: "If both headers are well formed but the named role does not appear in the
    authorized-role list published for the requested endpoint in §4, the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." "Units are readable
    individually and as a collection filtered by `product_id`,
    `shipped_distributor_id`, `downstream_reseller_id`, `lot_code` or `status`."

    Design: Corner/rbac/rbac_reseller_cannot_read_serial_units_rejected
    """
    world = _setup_unit_with_distributor(serial_number="SN-0001")

    params = {"product_id": world["product"]["id"], "limit": 10, "offset": 0}
    validate_error(
        api_client.list_serial_units(
            make_reseller_headers(world["reseller"]["id"]), params=params
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    rows, meta = validate_paginated(
        api_client.list_serial_units(
            make_distributor_headers(world["distributor"]["id"]), params=params
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["serial_number"] == "SN-0001"


# --------------------------------------------------------------------------- #
# Termination — the four-eyes rule on who may issue it
# --------------------------------------------------------------------------- #
def _setup_suspension_issued_by_counsel_1():
    """Acme SUSPENDED behind a warning from bcm-1 and a suspension from counsel-1.

    A third violation worth 5 final points sits in DETECTED with the ledger at 14.
    """
    policy, product = _setup_product()
    reseller, _agreement = _setup_authorized_reseller(policy["id"])
    pin_clock(CLOCK_AUG_20)

    first, _obs1, _eval1 = create_detected_violation(
        product["id"],
        reseller["id"],
        listed_price_cents=14000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_18,
        listing_url="https://mkt.example/l/1",
        evidence_hash=EVIDENCE_HASH_1,
    )
    warning = issue_notice(reseller["id"], first["id"])
    assert warning["rung"] == "WARNING"

    second, _obs2, _eval2 = create_detected_violation(
        product["id"],
        reseller["id"],
        listed_price_cents=9000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_18,
        listing_url="https://mkt.example/l/2",
        evidence_hash=EVIDENCE_HASH_3,
    )
    suspension = issue_notice(
        reseller["id"],
        second["id"],
        headers=COUNSEL_HEADERS,
        rung="SUSPENSION",
        suspension_starts_at=SUSPENSION_STARTS,
        suspension_ends_at=SUSPENSION_ENDS,
    )
    assert suspension["rung"] == "SUSPENSION"
    assert suspension["issued_by_user_id"] == COUNSEL_1

    third, _obs3, _eval3 = create_detected_violation(
        product["id"],
        reseller["id"],
        listed_price_cents=14000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_19,
        listing_url="https://mkt.example/l/3",
        evidence_hash=EVIDENCE_HASH_1,
    )
    return {
        "product": product,
        "reseller": reseller,
        "warning": warning,
        "suspension": suspension,
        "violations": [first, second, third],
    }


def _termination_payload(world):
    return notice_payload(
        world["reseller"]["id"],
        world["violations"][2]["id"],
        current_reseller_version(world["reseller"]["id"]),
        delivery_channel="CERTIFIED_MAIL",
        rung="TERMINATION",
    )


def test_the_counsel_who_suspended_may_not_also_terminate():
    """Four eyes: the suspending identifier cannot issue the termination.

    PRD: "On top of that, the `X-User-ID` issuing the termination must be different
    from the `X-User-ID` recorded as `issued_by_user_id` on the reseller's governing
    suspension notice, so that the same individual cannot both suspend and then
    terminate the same partner; a match is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/rbac_termination_by_the_suspension_issuer_rejected
    """
    world = _setup_suspension_issued_by_counsel_1()
    ledger_before = read_reseller(world["reseller"]["id"])["violation_points_total"]
    assert ledger_before == (
        violation_points(STANDARD_FLOOR, 14000, "MARKETPLACE", 0)
        + violation_points(STANDARD_FLOOR, 9000, "MARKETPLACE", 1)
    ) == 14

    validate_error(
        api_client.issue_notice(_termination_payload(world), COUNSEL_HEADERS),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "SUSPENDED"
    assert reseller["violation_points_total"] == 14
    assert read_violation(world["violations"][2]["id"])["status"] == "DETECTED"


def test_a_second_counsel_may_terminate_the_same_reseller():
    """The positive half of the rule: a distinct counsel drives the termination.

    PRD: "On top of that, the `X-User-ID` issuing the termination must be different
    from the `X-User-ID` recorded as `issued_by_user_id` on the reseller's governing
    suspension notice, so that the same individual cannot both suspend and then
    terminate the same partner; a match is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    "Read the reseller's `violation_points_total` *before* this notice's points are
    added, then add the final points once to obtain the cumulative figure recorded on
    the notice as `cumulative_points_at_issue`."

    Design: Corner/rbac/rbac_termination_by_a_second_counsel_is_accepted
    """
    world = _setup_suspension_issued_by_counsel_1()

    notice = validate_success(
        api_client.issue_notice(_termination_payload(world), COUNSEL_2_HEADERS),
        expected_status=201,
    )

    final_points = violation_points(STANDARD_FLOOR, 14000, "MARKETPLACE", 2)
    assert final_points == 5
    assert notice["rung"] == "TERMINATION"
    assert notice["assessed_points"] == final_points
    assert notice["cumulative_points_at_issue"] == 14 + final_points == 19
    assert notice["issued_by_user_id"] == COUNSEL_2


def test_the_accepted_termination_drives_the_reseller_to_its_terminal_pair():
    """The termination the second counsel issued cuts supply off for good.

    PRD: "A `TERMINATION` notice — legal from `AUTHORIZED` or `SUSPENDED` — drives the
    reseller to `TERMINATED` on the authorization axis, `CUT_OFF` on the supply axis
    and `TERMINATION` as the `hold_reason`, stamps `terminated_at` with the current
    clock and clears `suspension_ends_at` to null."

    Design: Corner/rbac/rbac_termination_by_a_second_counsel_is_accepted
    """
    world = _setup_suspension_issued_by_counsel_1()

    validate_success(
        api_client.issue_notice(_termination_payload(world), COUNSEL_2_HEADERS),
        expected_status=201,
    )

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "TERMINATED"
    assert reseller["supply_status"] == "CUT_OFF"
    assert reseller["hold_reason"] == "TERMINATION"
    assert reseller["suspension_ends_at"] is None
    assert_same_instant(reseller["terminated_at"], CLOCK_AUG_20, "terminated_at")
