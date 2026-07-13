"""Sites, artwork intake and installation, conservation, loans, and deaccession."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    make_artwork_payload, make_install_payload, make_deaccession_payload,
    make_conservation_payload, make_loan_payload,
    create_site, create_donation_artwork, install_donation_artwork, create_loan,
)

REG = TEST_USERS["registrar_headers"]


def test_site_create_missing_address_returns_validation(api):
    """PRD §3.6: "A `Registrar` registers a site with a `name`, an `address`, and
    an optional `capacity` that defaults to 1; sites in this system are
    single-occupancy, so capacity is always 1."
    PRD §2.9: "The generic body-validation failure (a missing or malformed required
    field, an out-of-range enum, or a missing required `expected_project_version`
    or `expected_contract_version`) surfaces as `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/site_create_missing_required_address_returns_validation
    """
    resp = api.create_site({"name": "Nameless"}, REG)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


def test_created_site_is_immediately_readable(api):
    """PRD §3.6: "A new site is `AVAILABLE` with a null `current_artwork_id`."

    Design: Corner/consistency_model/immediate_visibility_of_created_site
    """
    site = create_site(api, name="Instant", address="2 Now")
    data = validate_success(api.get_site(site["id"], REG), 200)
    assert data["status"] == "AVAILABLE"


def test_intake_commission_type_rejected(api):
    """PRD §3.6: "Direct intake accepts only an `acquisition_type` of `DONATION` or
    `LOAN`; a `COMMISSION` acquisition supplied here is rejected with
    `ERR_DONATION_TYPE_REQUIRED` (HTTP 422), because commission artworks may only
    arise from contract activation."

    Design: Corner/validations/intake_commission_type_rejected
    """
    resp = api.create_artwork(
        make_artwork_payload(title="Sneaky", acquisition_type="COMMISSION"), REG)
    validate_error(resp, ApiErrorId.ERR_DONATION_TYPE_REQUIRED.value, 422)


def test_deaccession_blocked_by_approved_loan(api):
    """PRD §3.7: "Deaccession is blocked while any loan on the artwork is in
    `APPROVED`; such an attempt is rejected with `ERR_DEACCESSION_BLOCKED_BY_LOAN`
    (HTTP 409)."

    Design: Corner/validations/deaccession_blocked_by_approved_loan
    """
    artwork = create_donation_artwork(api, title="OnLoan", appraised_value_cents=400000)
    loan = create_loan(api, artwork["id"], "Gallery Z", "2026-04-01T00:00:00Z",
                       "2026-04-20T00:00:00Z")
    validate_success(api.approve_loan(loan["id"], REG), 200)
    resp = api.deaccession_artwork(artwork["id"], make_deaccession_payload("SALE"), REG)
    validate_error(resp, ApiErrorId.ERR_DEACCESSION_BLOCKED_BY_LOAN.value, 409)
    refreshed = get_success_data(api.get_artwork(artwork["id"], REG))
    assert refreshed["location_status"] == "FABRICATED"


def test_condition_and_location_evolve_independently(api):
    """PRD §3.6: "Its `location_status` moves through `FABRICATION`, `FABRICATED`,
    `INSTALLED`, and the terminal `DEACCESSIONED`, while its `condition_status`
    moves independently across `GOOD`, `FAIR`, `POOR`, and `NEEDS_TREATMENT`,
    driven only by conservation events."
    PRD §3.6: "as a side effect the artwork's `condition_status` is set to the
    supplied `condition_after`."

    Design: Difficulty/non_linear_state_machine/artwork_location_and_condition_parallel_dimensions
    """
    site = create_site(api, name="North Plaza", address="1 North St")
    artwork = create_donation_artwork(api, title="Bronze Heron", appraised_value_cents=500000)
    validate_success(api.create_conservation_record(
        artwork["id"],
        make_conservation_payload("INSPECTION", "NEEDS_TREATMENT", notes="surface corrosion"),
        REG), 201)
    validate_success(api.install_artwork(
        artwork["id"], make_install_payload(site["id"], "2026-04-01T00:00:00Z"), REG), 200)
    refreshed = get_success_data(api.get_artwork(artwork["id"], REG))
    assert refreshed["location_status"] == "INSTALLED"
    assert refreshed["condition_status"] == "NEEDS_TREATMENT"


def test_conservation_condition_does_not_gate_installation(api):
    """PRD §3.6: "The two evolve in parallel and do not gate each other except
    where explicitly stated."
    PRD §3.6: "as a side effect the artwork's `condition_status` is set to the
    supplied `condition_after`."

    Design: Difficulty/non_linear_state_machine/artwork_location_and_condition_parallel_dimensions
    """
    site = create_site(api, name="South Plaza", address="2 South St")
    artwork = create_donation_artwork(api, title="Glass Vane", appraised_value_cents=500000)
    validate_success(api.create_conservation_record(
        artwork["id"], make_conservation_payload("INSPECTION", "NEEDS_TREATMENT"), REG), 201)
    installed = validate_success(api.install_artwork(
        artwork["id"], make_install_payload(site["id"], "2026-04-01T00:00:00Z"), REG), 200)
    assert installed["location_status"] == "INSTALLED"
    assert installed["condition_status"] == "NEEDS_TREATMENT"


def test_install_into_occupied_site_interval_conflict(api):
    """PRD §3.6: "The artwork must be `FABRICATED`, the target site must be
    `AVAILABLE`, and no already-installed artwork may occupy that site over an
    interval that contains the `install_date`. Site occupancy is treated as a
    half-open interval beginning at the install instant and extending forward
    indefinitely, with adjacency permitted; a colliding install is rejected with
    `ERR_SITE_INTERVAL_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/site_install_occupied_interval_conflict
    """
    occupied = install_donation_artwork(api, site_name="Center Court",
                                        install_date="2026-04-01T00:00:00Z",
                                        appraised_value_cents=200000)
    art2 = create_donation_artwork(api, title="Second Piece", appraised_value_cents=200000)
    resp = api.install_artwork(
        art2["id"], make_install_payload(occupied["site"]["id"], "2026-05-01T00:00:00Z"), REG)
    validate_error(resp, ApiErrorId.ERR_SITE_INTERVAL_CONFLICT.value, 409)


def test_conflicting_install_leaves_artwork_fabricated(api):
    """PRD §3.6: "The artwork must be `FABRICATED`, the target site must be
    `AVAILABLE`, and no already-installed artwork may occupy that site over an
    interval that contains the `install_date`. Site occupancy is treated as a
    half-open interval beginning at the install instant and extending forward
    indefinitely, with adjacency permitted; a colliding install is rejected with
    `ERR_SITE_INTERVAL_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/site_install_occupied_interval_conflict
    """
    occupied = install_donation_artwork(api, site_name="Plaza East",
                                        install_date="2026-04-01T00:00:00Z",
                                        appraised_value_cents=200000)
    art2 = create_donation_artwork(api, title="Second Piece", appraised_value_cents=200000)
    api.install_artwork(
        art2["id"], make_install_payload(occupied["site"]["id"], "2026-05-01T00:00:00Z"), REG)
    refreshed = get_success_data(api.get_artwork(art2["id"], REG))
    assert refreshed["location_status"] == "FABRICATED"


def test_loan_within_buffer_gap_rejected(api):
    """PRD §3.7: "The requested interval, treated as closed on both ends, must not
    overlap — and must not sit within 30 calendar days (the loan buffer) — of any
    non-returned loan on the same artwork, meaning any loan currently in
    `REQUESTED` or `APPROVED`; a violation is rejected with
    `ERR_LOAN_INTERVAL_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/loan_buffer_gap_conflict
    """
    artwork = create_donation_artwork(api, title="Traveling Totem", appraised_value_cents=600000)
    create_loan(api, artwork["id"], "Museum A", "2026-04-01T00:00:00Z", "2026-04-30T00:00:00Z")
    resp = api.create_loan(
        artwork["id"], make_loan_payload("Museum B", "2026-05-10T00:00:00Z",
                                         "2026-05-20T00:00:00Z"), REG)
    validate_error(resp, ApiErrorId.ERR_LOAN_INTERVAL_CONFLICT.value, 409)


def test_loan_ten_days_after_prior_still_conflicts(api):
    """PRD §3.7: "The requested interval, treated as closed on both ends, must not
    overlap — and must not sit within 30 calendar days (the loan buffer) — of any
    non-returned loan on the same artwork, meaning any loan currently in
    `REQUESTED` or `APPROVED`; a violation is rejected with
    `ERR_LOAN_INTERVAL_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/loan_buffer_gap_conflict
    """
    artwork = create_donation_artwork(api, title="Roaming Relic", appraised_value_cents=600000)
    create_loan(api, artwork["id"], "Museum A", "2026-04-01T00:00:00Z", "2026-04-30T00:00:00Z")
    resp = api.create_loan(
        artwork["id"], make_loan_payload("Museum C", "2026-05-10T00:00:00Z",
                                         "2026-05-20T00:00:00Z"), REG)
    validate_error(resp, ApiErrorId.ERR_LOAN_INTERVAL_CONFLICT.value, 409)


def test_loan_approve_blocked_when_artwork_deaccessioned(api):
    """PRD §3.7: "A `Registrar` approves a `REQUESTED` loan, moving it
    `REQUESTED → APPROVED`, provided the artwork's `location_status` is not
    `DEACCESSIONED`;"

    Design: Difficulty/cross_entity_state_dependency/loan_approve_requires_artwork_not_deaccessioned
    """
    artwork = create_donation_artwork(api, title="Glass Wave", appraised_value_cents=300000)
    loan = create_loan(api, artwork["id"], "City Museum", "2026-05-01T00:00:00Z",
                       "2026-05-20T00:00:00Z")
    validate_success(api.deaccession_artwork(
        artwork["id"], make_deaccession_payload("TRANSFER"), REG), 200)
    resp = api.approve_loan(loan["id"], REG)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_loan_stays_requested_after_blocked_approve(api):
    """PRD §3.7: "A `Registrar` approves a `REQUESTED` loan, moving it
    `REQUESTED → APPROVED`, provided the artwork's `location_status` is not
    `DEACCESSIONED`;"

    Design: Difficulty/cross_entity_state_dependency/loan_approve_requires_artwork_not_deaccessioned
    """
    artwork = create_donation_artwork(api, title="Amber Wave", appraised_value_cents=300000)
    loan = create_loan(api, artwork["id"], "City Museum", "2026-05-01T00:00:00Z",
                       "2026-05-20T00:00:00Z")
    validate_success(api.deaccession_artwork(
        artwork["id"], make_deaccession_payload("TRANSFER"), REG), 200)
    api.approve_loan(loan["id"], REG)
    loans = get_success_data(api.list_loans(artwork["id"], REG))
    assert loans[0]["status"] == "REQUESTED"


def test_deaccession_frees_site_slot(api):
    """PRD §3.7: "If the artwork was installed, its site is freed as a compensating
    action: the site moves `OCCUPIED → AVAILABLE` and its `current_artwork_id` is
    cleared to null."

    Design: Difficulty/compensating_invariant/site_slot_conserved_on_deaccession
    """
    ctx = install_donation_artwork(api, site_name="Harbor Point",
                                   install_date="2026-04-01T00:00:00Z",
                                   appraised_value_cents=700000)
    validate_success(api.deaccession_artwork(
        ctx["artwork"]["id"],
        make_deaccession_payload("SALE", deaccession_proceeds_cents=250000), REG), 200)
    site = get_success_data(api.get_site(ctx["site"]["id"], REG))
    assert site["status"] == "AVAILABLE"
    assert site["current_artwork_id"] is None


def test_installed_artwork_becomes_deaccessioned(api):
    """PRD §3.7: "On success the artwork moves to `DEACCESSIONED` with its
    `deaccession_method` and `deaccession_proceeds_cents` recorded."

    Design: Difficulty/compensating_invariant/site_slot_conserved_on_deaccession
    """
    ctx = install_donation_artwork(api, site_name="Tidal Point",
                                   install_date="2026-04-01T00:00:00Z",
                                   appraised_value_cents=700000)
    data = validate_success(api.deaccession_artwork(
        ctx["artwork"]["id"],
        make_deaccession_payload("SALE", deaccession_proceeds_cents=250000), REG), 200)
    assert data["location_status"] == "DEACCESSIONED"
