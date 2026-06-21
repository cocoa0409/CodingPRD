"""Corner: listing/pagination/filtering, FK existence, duplicate serial, OCC
(stale and correct version), RBAC (forbidden role, unauthenticated), derived
collateral, GPS-fail cascade, and immediate consistency.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, api_client,
    setup_draft_surety_bond, setup_judgment_ready, enter_judgment_on,
    setup_active_bond_with_active_gps, setup_active_surety_bond,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

AGENT = TEST_USERS["bonds_agent_headers"]
COURT = TEST_USERS["court_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
RECOVERY = TEST_USERS["recovery_agent_headers"]


# Corner/endpoints/list_bonds_pagination_envelope
def test_list_bonds_returns_paginated_envelope(api):
    """PRD 2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_bonds_pagination_envelope
    """
    scen = setup_draft_surety_bond(bail_amount_cents=500000, bond_type_allowed="ANY",
                                   with_indemnity=False, with_collateral=False)
    get_success_data(api_client.create_bond(
        scen["def_id"], scen["order_id"], {"bond_type": "PR"}, scen["agent"]))
    data, meta = validate_paginated(api.list_bonds(AGENT))
    assert isinstance(data, list)
    assert "total_count" in meta and "has_more" in meta, meta


# Corner/endpoints/filtered_bonds_by_defendant
def test_filter_bonds_by_defendant(api):
    """PRD 3.2: "On creation the system records the originating order on the bond
    as `bail_order_id`, copies the order's face value into the bond's own
    `bail_amount_cents`, and denormalizes the `defendant_id` onto the bond so
    exposure can be rolled up without traversing the order."

    Filtering GET /bonds by defendant_id returns only that defendant's bonds, keyed
    on the denormalized defendant_id.

    Design: Corner/endpoints/filtered_bonds_by_defendant
    """
    scen = setup_draft_surety_bond(bail_amount_cents=500000, bond_type_allowed="ANY",
                                   with_indemnity=False, with_collateral=False)
    bond = get_success_data(api_client.create_bond(
        scen["def_id"], scen["order_id"], {"bond_type": "PR"}, scen["agent"]))
    data, _ = validate_paginated(api.list_bonds(AGENT, params={"defendant_id": scen["def_id"]}))
    assert data, data
    assert all(b["defendant_id"] == scen["def_id"] for b in data), data
    assert any(b["id"] == bond["id"] for b in data), data


# Corner/endpoints/fk_not_found_unknown_indemnitor
def test_fk_not_found_unknown_indemnitor(api):
    """PRD 2.5: "when a request body carries a foreign key — an `indemnitor_id`, a
    `bond_id`, a `device_id`, and the like — and that key points at a resource that
    does not exist, the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 404)."

    Design: Corner/endpoints/fk_not_found_unknown_indemnitor
    """
    scen = setup_draft_surety_bond(bail_amount_cents=1_000_000, with_indemnity=False,
                                   with_collateral=False)
    resp = api.create_indemnity_agreement(
        scen["def_id"], scen["bond_id"],
        {"indemnitor_id": NON_EXISTENT_UUID, "liability_share_cents": 1_000_000}, AGENT)
    validate_error(resp, "ERR_FK_NOT_FOUND")


# Corner/endpoints/pagination_limit_out_of_range_rejected
def test_pagination_limit_out_of_range_rejected(api):
    """PRD 2.3: "A list request whose `limit` falls outside the inclusive range of 1
    through 100, or whose `offset` is below 0, is rejected with `ERR_VALIDATION`
    (HTTP 422)."

    limit=101 exceeds the max of 100.

    Design: Corner/endpoints/pagination_limit_out_of_range_rejected
    """
    resp = api.list_defendants(AGENT, params={"limit": 101})
    validate_error(resp, "ERR_VALIDATION")


# Corner/errors/duplicate_serial_rejected
def test_duplicate_serial_rejected(api):
    """PRD 3.8: "A `BondsAgent` registers a device with a `serial_number` that must
    be globally unique; a duplicate serial is rejected with `ERR_DUPLICATE_SERIAL`
    (HTTP 409)."

    Design: Corner/errors/duplicate_serial_rejected
    """
    get_success_data(api_client.create_gps_device({"serial_number": "GPS-UNIQUE"}, AGENT))
    resp = api.create_gps_device({"serial_number": "GPS-UNIQUE"}, AGENT)
    validate_error(resp, "ERR_DUPLICATE_SERIAL")


# Corner/errors/stale_bond_version_on_judgment
def test_stale_bond_version_on_judgment_rejected(api):
    """PRD 2.9: "Before the judgment is applied, the server compares
    `expected_bond_version` against the bond's current `version`. If they differ —
    meaning some other writer has advanced the bond since the client last read it —
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Sending expected_bond_version one behind the bond's current version.

    Design: Corner/errors/stale_bond_version_on_judgment
    """
    scen = setup_judgment_ready(open_recovery=False, bail_amount_cents=1_000_000,
                                liability_share_cents=1_000_000, collateral_value_cents=250_000)
    stale = scen["bond_version_before"] - 1
    resp = api.enter_judgment(scen["def_id"], scen["proc_id"], {"expected_bond_version": stale}, OFFICER)
    validate_error(resp, "ERR_STALE_VERSION")


# Corner/rbac/court_cannot_post_bond_forbidden
def test_court_cannot_post_bond_forbidden(api):
    """PRD 2.1: "an authenticated caller acting outside their authorized operations
    is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 3.2: "A `BondsAgent` posts a `Bond` against a bail order."

    Posting a bond is a BondsAgent operation; a Court actor calling it ->
    ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/court_cannot_post_bond_forbidden
    """
    defendant = get_success_data(api_client.create_defendant(
        {"full_name": "No Op", "date_of_birth": "1984-03-27", "phone_e164": "+15551110036"}, COURT))
    order = get_success_data(api_client.create_bail_order(
        defendant["id"], {"case_number": "CR-X24", "bail_amount_cents": 500000, "bond_type_allowed": "ANY"}, COURT))
    resp = api.create_bond(defendant["id"], order["id"], {"bond_type": "PR"}, COURT)
    validate_error(resp, "ERR_FORBIDDEN_ROLE")


# Corner/rbac/bondsagent_cannot_exonerate_forbidden
def test_bondsagent_cannot_exonerate_forbidden(api):
    """PRD 2.1: "A `ComplianceOfficer` approves the financially consequential
    closures — exoneration, reinstatement, judgment, and remission — and is
    deliberately barred from posting bonds."
    PRD 3.7: "A `ComplianceOfficer` exonerates a bond, advancing it
    `ACTIVE → EXONERATED`."

    Exoneration is a ComplianceOfficer operation; a BondsAgent calling it ->
    ERR_FORBIDDEN_ROLE (role gate, before the same-user SoD check).

    Design: Corner/rbac/bondsagent_cannot_exonerate_forbidden
    """
    scen = setup_active_surety_bond(bail_amount_cents=1_000_000, liability_share_cents=1_000_000)
    resp = api.exonerate_bond(scen["def_id"], scen["bond_id"], scen["agent"])
    validate_error(resp, "ERR_FORBIDDEN_ROLE")


# Corner/rbac/missing_headers_unauthenticated
def test_missing_headers_unauthenticated(api):
    """PRD 2.1: "A request that omits either header, or supplies a malformed value,
    is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_headers_unauthenticated
    """
    resp = api.list_defendants(headers={})
    validate_error(resp, "ERR_UNAUTHENTICATED")


# Corner/cross_cutting_complexity_layers/occ_correct_version_judgment_succeeds
def test_correct_version_judgment_succeeds_and_bumps_version(api):
    """PRD 2.9: "The judgment request must carry `expected_bond_version`, a
    non-optional field whose value is the client's last observed `version` of the
    target `Bond`."
    PRD 3.6: "entering judgment increments the bond's `version` by one."

    Judgment with the current version succeeds (proceeding -> JUDGMENT, settlement
    -> JUDGMENT_ENTERED) and bumps Bond.version by 1.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_judgment_succeeds
    """
    scen = setup_judgment_ready(open_recovery=False, bail_amount_cents=1_000_000,
                                liability_share_cents=1_000_000, collateral_value_cents=250_000)
    before = scen["bond_version_before"]
    proc = enter_judgment_on(scen)
    assert proc["status"] == "JUDGMENT", proc["status"]
    bond = validate_success(api.get_bond(scen["bond_id"], OFFICER))
    assert bond["settlement_status"] == "JUDGMENT_ENTERED", bond["settlement_status"]
    assert bond["version"] == before + 1, (bond["version"], before)


# Corner/cross_cutting_complexity_layers/derived_collateral_held_after_pledge
def test_collateral_held_recomputes_after_each_pledge(api):
    """PRD 3.4: "Pledging an item recomputes the bond's `collateral_held_cents`,
    which at all times equals the sum of `pledged_value_cents` over the bond's items
    whose status is `HELD`."

    Two pledges (300,000 + 200,000) -> collateral_held_cents == 500,000.

    Design: Corner/cross_cutting_complexity_layers/derived_collateral_held_after_pledge
    """
    scen = setup_draft_surety_bond(bail_amount_cents=2_000_000, with_indemnity=False,
                                   with_collateral=False)
    get_success_data(api_client.create_collateral(
        scen["def_id"], scen["bond_id"], {"kind": "CASH", "pledged_value_cents": 300_000}, scen["agent"]))
    get_success_data(api_client.create_collateral(
        scen["def_id"], scen["bond_id"], {"kind": "VEHICLE_TITLE", "pledged_value_cents": 200_000}, scen["agent"]))
    bond = validate_success(api.get_bond(scen["bond_id"], scen["agent"]))
    assert bond["collateral_held_cents"] == 500_000, bond["collateral_held_cents"]


# Corner/cross_cutting_complexity_layers/gps_fail_increments_violation_and_tampers
def test_gps_fail_increments_violation_and_tampers(api):
    """PRD 3.8: "a `GPS` check-in whose result is `FAIL` is the very event that
    drives an `ACTIVE` GPS device on that bond into `TAMPER` and increments that
    device's `violation_count`."

    Design: Corner/cross_cutting_complexity_layers/gps_fail_increments_violation_and_tampers
    """
    scen = setup_active_bond_with_active_gps(bail_amount_cents=1_000_000, liability_share_cents=1_000_000,
                                             condition_codes=["GPS"])
    get_success_data(api_client.create_check_in(
        scen["def_id"], {"bond_id": scen["bond_id"], "condition_code": "GPS", "result": "FAIL"}, RECOVERY))
    device = validate_success(api.get_gps_device(scen["device_id"], RECOVERY))
    assert device["violation_count"] == 1, device["violation_count"]
    assert device["status"] == "TAMPER", device["status"]


# Corner/consistency_model/immediate_visibility_of_premium_on_activate
def test_premium_and_settlement_visible_in_activate_response(api):
    """PRD 2.8: "These derived recomputations are immediate and consistent — they
    happen within the same request that caused them, never on a deferred schedule."
    PRD 3.2: "and sets `settlement_status` to `PREMIUM_COLLECTED`."

    Activation response itself carries premium_cents == 100,000 and
    settlement_status == PREMIUM_COLLECTED for a 1,000,000c SURETY bond at 1000 bps.

    Design: Corner/consistency_model/immediate_visibility_of_premium_on_activate
    """
    scen = setup_draft_surety_bond(bail_amount_cents=1_000_000, liability_share_cents=1_000_000,
                                   collateral_value_cents=250_000)
    activated = validate_success(api.activate_bond(scen["def_id"], scen["bond_id"], scen["agent"]))
    assert activated["premium_cents"] == 100_000, activated["premium_cents"]
    assert activated["settlement_status"] == "PREMIUM_COLLECTED", activated["settlement_status"]
