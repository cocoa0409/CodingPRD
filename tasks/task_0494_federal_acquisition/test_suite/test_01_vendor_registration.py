"""Vendor registration lifecycle, SAM eligibility, and the performance index.

Covers queue-B corner instances (entities / state_machines / calculations) for
VendorRegistration plus the queue-A boundary instance for the empty performance index.
"""
import pytest
from test_helpers import (
    api_client as _ac,
    validate_success, validate_error, validate_paginated,
    assert_vendor,
    create_vendor_payload,
    TEST_USERS, make_vendor_headers,
    NON_EXISTENT_UUID,
    set_clock, create_active_vendor, setup_active_ffp_contract,
    get_success_data,
)

CO = TEST_USERS["co_headers"]
VENDOR_FALLBACK = TEST_USERS["vendor_headers"]


def test_create_vendor_returns_201_draft_version_one(api):
    """PRD §3.1: "A new registration is born in `DRAFT` with `sam_status` defaulting
    to `DRAFT`." PRD §2.4: "The `version` field is an integer that begins at its
    initial value and increments by one on every mutation of the resource".

    Design: Corner/entities/create_vendor_returns_201_with_fields
    """
    res = api.create_vendor(create_vendor_payload(legal_name="Acme Corp", uei="ACME00000001",
                                                  employee_count=12), VENDOR_FALLBACK)
    vendor = validate_success(res, 201)
    assert_vendor(vendor)
    assert vendor["sam_status"] == "DRAFT", f"expected DRAFT, got {vendor['sam_status']}"
    assert vendor["version"] == 1, f"expected version 1, got {vendor['version']}"


def test_get_vendor_not_found(api):
    """PRD §2.6: "the first identifier that does not resolve to an existing resource
    yields `ERR_NOT_FOUND` before any later identifier is examined."

    Design: Corner/entities/get_vendor_not_found
    """
    res = api.get_vendor(NON_EXISTENT_UUID, CO)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_vendor_missing_uei_invalid_request(api):
    """PRD §3.8: "A malformed request body — a missing required field, a value outside
    its allowed enum, or an out-of-range number such as a `raw_score` outside 0 to 100,
    a `rating` not in its enum, or a `uei` that is not exactly 12 characters — is
    rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/vendor_missing_required_field_returns_invalid_request
    """
    payload = create_vendor_payload(legal_name="NoUei", employee_count=12)
    del payload["uei"]
    res = api.create_vendor(payload, VENDOR_FALLBACK)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_vendor_set_aside_defaults_to_empty_array(api):
    """PRD §3.1: "The `set_aside_certifications` field, when supplied, is a subset of the
    certifications `EIGHT_A`, `SDVOSB`, `WOSB`, and `HUBZONE`; when omitted it defaults
    to an empty list."

    Design: Corner/entities/vendor_set_aside_default_empty_array
    """
    payload = create_vendor_payload(legal_name="DefaultCerts", uei="DEFC00000001",
                                    employee_count=12)
    payload.pop("set_aside_certifications", None)
    vendor = validate_success(api.create_vendor(payload, VENDOR_FALLBACK), 201)
    assert vendor["set_aside_certifications"] == [], (
        f"expected [], got {vendor['set_aside_certifications']}"
    )


def test_vendor_computed_fields_minted_by_server(api):
    """PRD §3.1: "A new registration is born in `DRAFT` with `sam_status` defaulting to
    `DRAFT`." PRD §3.1: "A vendor's `performance_index` is a computed field that starts
    as `null`".

    Design: Corner/entities/vendor_system_fields_input_ignored
    """
    payload = create_vendor_payload(legal_name="IgnoreSys", uei="IGNS00000001",
                                    employee_count=12)
    vendor = validate_success(api.create_vendor(payload, VENDOR_FALLBACK), 201)
    assert vendor["sam_status"] == "DRAFT", f"expected DRAFT, got {vendor['sam_status']}"
    assert vendor["performance_index"] is None, (
        f"expected null performance_index, got {vendor['performance_index']}"
    )


def test_factor_score_out_of_range_invalid_request(api):
    """PRD §3.3: "each factor score names the `proposal_id` it belongs to, the `factor_id`
    it scores against, and a `raw_score` in the inclusive range 0 to 100. A factor score
    whose `raw_score` falls outside that range is rejected as a malformed request."

    Design: Corner/entities/vendor_raw_score_enum_out_of_range
    """
    from test_helpers import (
        create_draft_solicitation_with_factors, open_solicitation,
        create_proposal_payload, create_score_payload,
    )
    set_clock("2026-02-01T00:00:00Z")
    sol, factors = create_draft_solicitation_with_factors(
        open_at="2026-02-01T00:00:00Z", close_at="2026-03-01T00:00:00Z"
    )
    open_solicitation(sol["id"])
    vendor = get_success_data(
        api.create_vendor(create_vendor_payload(legal_name="ScoreVendor", uei="SCOR00000001",
                                                employee_count=5), VENDOR_FALLBACK)
    )
    vh = make_vendor_headers(vendor["id"])
    prop = get_success_data(
        api.create_proposal(create_proposal_payload(sol["id"], vendor["id"], 40000000), vh)
    )
    res = api.add_score(prop["id"], create_score_payload(factors["TECHNICAL"]["id"], 150), vh)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_list_vendors_pagination_envelope(api):
    """PRD §2.3: "List responses always carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_vendors_pagination_envelope
    """
    api.create_vendor(create_vendor_payload(legal_name="L1", uei="LST100000001",
                                            employee_count=1), VENDOR_FALLBACK)
    api.create_vendor(create_vendor_payload(legal_name="L2", uei="LST200000001",
                                            employee_count=1), VENDOR_FALLBACK)
    data, meta = validate_paginated(api.list_vendors(TEST_USERS["auditor_headers"]))
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']}"


# ─── State machine: VendorRegistration ─────────────────────────────
def test_activate_already_active_vendor_invalid_state(api):
    """PRD §3.8: "State validity comes fifth: a transition requested from a state in which
    it is not defined is rejected with `ERR_INVALID_STATE` (HTTP 409) on every
    state-transition endpoint."

    Design: Corner/state_machines/activate_already_active_vendor_invalid_state
    """
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("ALAC00000001", employee_count=5)
    vh = make_vendor_headers(vendor["id"])
    res = api.activate_vendor(vendor["id"], vh)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_expired_vendor_revival_cycle(api):
    """PRD §3.1: "A vendor may revive an expired registration back to `ACTIVE` by
    activating it again; on this revival path the vendor supplies a renewed
    `registration_expires_at` in the activate body, and the revival is permitted only
    when that renewed expiry lies strictly after the current logical clock and when no
    other registration holding the same UEI is in `ACTIVE` or `EXPIRED`."

    Design: Corner/state_machines/vendor_expired_revival_cycle
    """
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("REVV00000001", employee_count=5)
    get_success_data(api.expire_vendor(vendor["id"], CO))
    vh = make_vendor_headers(vendor["id"])
    revived = validate_success(
        api.activate_vendor(vendor["id"], vh, payload={"registration_expires_at": "2028-01-01T00:00:00Z"}),
        200,
    )
    assert revived["sam_status"] == "ACTIVE", f"expected ACTIVE, got {revived['sam_status']}"


def test_excluded_vendor_terminal_lockdown(api):
    """PRD §3.1: "`EXCLUDED` is terminal: an excluded registration has no further
    transitions."

    Design: Corner/state_machines/excluded_vendor_terminal_lockdown
    """
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("DEBR00000001", employee_count=5)
    get_success_data(api.exclude_vendor(vendor["id"], CO))
    vh = make_vendor_headers(vendor["id"])
    res = api.activate_vendor(vendor["id"], vh)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_duplicate_uei_on_activate_rejected(api):
    """PRD §3.1: "Activation is permitted only when the `uei` is exactly 12 alphanumeric
    characters, when no other registration holding the same UEI (compared
    case-insensitively) currently has a `sam_status` of either `ACTIVE` or `EXPIRED`, and
    when the `registration_expires_at` lies strictly after the current logical clock."
    PRD §3.1: "A duplicate UEI at activation is rejected with `ERR_DUPLICATE_UEI`."

    Design: Corner/validations/error_duplicate_uei_on_activate
    """
    set_clock("2026-02-01T00:00:00Z")
    create_active_vendor("DUPE00000001", employee_count=5)
    v2 = get_success_data(
        api.create_vendor(create_vendor_payload(legal_name="Dup2", uei="DUPE00000001",
                                                employee_count=5), VENDOR_FALLBACK)
    )
    res = api.activate_vendor(v2["id"], make_vendor_headers(v2["id"]))
    validate_error(res, "ERR_DUPLICATE_UEI", expected_status=409)


# ─── Performance index calculations ────────────────────────────────
def test_performance_index_empty_set_is_null(api):
    """PRD §3.7: "When that collection is empty, the `performance_index` is `null`."
    PRD §2.9: "A vendor's performance index, when the vendor has no qualifying
    performance report, is the explicit value `null` rather than zero."

    Design: Difficulty/boundary_precision_check/performance_index_empty_set
    """
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("NORP00000001", employee_count=5)
    fetched = validate_success(api.get_vendor(vendor["id"], CO), 200)
    assert fetched["performance_index"] is None, (
        f"expected null performance_index for a vendor with no CPARS reports, "
        f"got {fetched['performance_index']}"
    )


def test_performance_index_empty_set_other_metric(api):
    """PRD §3.7: "When that collection is empty, the `performance_index` is `null`."

    Second assertion of the empty-set boundary via a fresh, just-activated vendor.

    Design: Difficulty/boundary_precision_check/performance_index_empty_set
    """
    set_clock("2026-03-15T00:00:00Z")
    vendor = create_active_vendor("NORP00000002", employee_count=1)
    fetched = validate_success(api.get_vendor(vendor["id"], CO), 200)
    assert fetched["performance_index"] is None, (
        f"expected null, got {fetched['performance_index']}"
    )


def test_performance_index_two_reports_mean(api):
    """PRD §3.7: "Otherwise the `performance_index` is the mean of the `rating_value`
    across all collected reports, rounded half-up to two decimal places." PRD §3.7:
    "`EXCEPTIONAL` maps to 100, `VERY_GOOD` to 85".

    Design: Corner/calculations/performance_index_two_reports_mean
    """
    from test_helpers import create_cpars_payload, fresh_contract_version  # noqa: F401
    ctx = setup_active_ffp_contract(
        base_value_cents=40000000, with_clin=False,
        vendor_uei="TWOR00000001", total_price_cents=40000000,
        close_at="2026-02-05T00:00:00Z",
    )
    contract_id = ctx["contract"]["id"]
    get_success_data(api.create_cpars(contract_id, create_cpars_payload("EXCEPTIONAL"), CO))
    get_success_data(api.create_cpars(contract_id, create_cpars_payload("VERY_GOOD"), CO))
    get_success_data(api.complete_contract(contract_id, CO))
    get_success_data(api.closeout_contract(contract_id, CO))

    vendor = validate_success(api.get_vendor(ctx["vendor"]["id"], CO), 200)
    assert vendor["performance_index"] == 92.50, (
        f"expected 92.50 (mean of 100 and 85), got {vendor['performance_index']}"
    )
