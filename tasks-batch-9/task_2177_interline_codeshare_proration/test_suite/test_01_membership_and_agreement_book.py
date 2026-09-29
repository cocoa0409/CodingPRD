"""Carrier membership standing and the bilateral agreement book."""

from test_helpers import (
    ApiErrorId,
    OPERATOR,
    assert_agreement,
    assert_bare_uuid,
    assert_carrier,
    create_agreement_payload,
    create_carrier_payload,
    create_factor_payload,
    is_iso8601_timestamp,
    make_accountant_headers,
    new_carrier,
    read_agreement,
    read_carrier,
    setup_agreement,
    setup_three_carriers,
    setup_two_carriers,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Carrier registration
# --------------------------------------------------------------------------- #
def test_carrier_registration_opens_every_balance_and_counter_at_zero(api):
    """PRD §3.1: "A newly registered carrier opens in `ACTIVE` standing, with all four
    balances, `net_position_minor`, `period_accrued_miles`, `period_ffp_cost_estimate_minor`,
    `period_ffp_cost_trued_up_minor`, `ffp_true_up_delta_minor` and `open_reproration_count`
    at zero, and `audit_flag` false."
    PRD §2.4: "Most rows additionally carry `updated_at`, in the same ISO 8601 UTC format
    with three fractional digits, and `version`, an integer that begins at 1 when the row is
    created and increases by exactly 1 on every mutation of that row."

    Design: Corner/entities/carrier_registration_initialises_every_balance_and_counter
    """
    payload = create_carrier_payload("AA", credit_limit_minor=5000000)
    resp = api.create_carrier(payload, OPERATOR)
    carrier = validate_success(resp, 201)

    assert_carrier(carrier)
    assert carrier["status"] == "ACTIVE", f"expected ACTIVE, got {carrier['status']}"
    assert carrier["version"] == 1, f"expected version 1, got {carrier['version']}"
    for field in (
        "pending_receivable_minor",
        "pending_payable_minor",
        "settled_receivable_minor",
        "settled_payable_minor",
        "net_position_minor",
        "period_accrued_miles",
        "period_ffp_cost_estimate_minor",
        "period_ffp_cost_trued_up_minor",
        "ffp_true_up_delta_minor",
        "open_reproration_count",
    ):
        assert carrier[field] == 0, f"{field} should open at 0, got {carrier[field]}"
    assert carrier["audit_flag"] is False, "audit_flag should open false"
    assert carrier["credit_limit_minor"] == 5000000


def test_carrier_id_is_a_bare_uuid_and_reads_back_unchanged(api):
    """PRD §2.4: "Every stored row is addressed by an `id` that the server mints as a UUID
    at creation time. Identifiers carry no type prefix and no embedded meaning; clients must
    treat them as opaque."
    PRD §2.4: "Every row also carries `created_at`, an ISO 8601 UTC timestamp with three
    fractional digits recording when the row was inserted."

    Design: Corner/entities/carrier_id_is_a_bare_uuid_minted_by_the_server
    """
    created = new_carrier("BB", base_currency="EUR", credit_limit_minor=7500000)
    assert_bare_uuid(created["id"])
    assert not created["id"].startswith("car_"), "identifiers carry no type prefix"

    fetched = validate_success(api.get_carrier(created["id"], OPERATOR), 200)
    assert fetched["id"] == created["id"]
    assert fetched["iata_code"] == "BB"
    assert fetched["name"] == "Borealis Airways"
    assert fetched["base_currency"] == "EUR"
    assert fetched["credit_limit_minor"] == 7500000
    assert is_iso8601_timestamp(fetched["created_at"])
    assert is_iso8601_timestamp(fetched["updated_at"])


def test_suspending_an_already_suspended_carrier_is_refused(api):
    """PRD §2.7: "**Carrier state.** Suspension requires the carrier to be `ACTIVE`;
    reinstatement requires it to be `SUSPENDED` — otherwise `ERR_CARRIER_STATE_INVALID`
    (409). Applies to carrier suspend and carrier reinstate."

    Design: Corner/errors/suspending_an_already_suspended_carrier_returns_carrier_state_invalid
    """
    aa = new_carrier("AA")
    validate_success(api.suspend_carrier(aa["id"], OPERATOR), 200)

    resp = api.suspend_carrier(aa["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_CARRIER_STATE_INVALID.value)

    assert read_carrier(aa["id"])["status"] == "SUSPENDED"


# --------------------------------------------------------------------------- #
# Membership sweep into the agreement book
# --------------------------------------------------------------------------- #
def test_carrier_suspension_sweeps_only_its_own_active_agreements(api):
    """PRD §3.1: "Suspension is the clearing house's sanction against a defaulting or
    non-compliant member: it requires the carrier to be `ACTIVE`, sets `status` to
    `SUSPENDED`, bumps the carrier's `version`, and — this is the part implementers most
    often miss — sweeps out into the agreement book, moving *every* prorate agreement
    currently `ACTIVE` that names this carrier on either side, whether as
    `issuing_carrier_id` or as `partner_carrier_id`, into `SUSPENDED` with a
    `suspension_reason` of `CARRIER_SUSPENDED`, bumping each agreement's `version` in turn."

    Design: Corner/state_machines/carrier_suspension_cascades_to_its_active_agreements
    """
    aa, bb, cc = setup_three_carriers()
    ag1, _ = setup_agreement(aa["id"], bb["id"], "SPA_FLAT", activate=True)
    ag2, _ = setup_agreement(aa["id"], cc["id"], "SPA_PERCENT", activate=False)

    suspended = validate_success(api.suspend_carrier(bb["id"], OPERATOR), 200)
    assert suspended["status"] == "SUSPENDED"

    swept = read_agreement(ag1["id"])
    assert swept["status"] == "SUSPENDED", "the ACTIVE agreement naming BB must follow it out"
    assert swept["suspension_reason"] == "CARRIER_SUSPENDED"

    untouched = read_agreement(ag2["id"])
    assert untouched["status"] == "DRAFT", "BB is not a party to the AA->CC draft"
    assert untouched["suspension_reason"] == "NONE"

    assert read_carrier(aa["id"])["status"] == "ACTIVE"
    assert read_carrier(cc["id"])["status"] == "ACTIVE"


def test_reinstating_a_carrier_leaves_its_swept_agreements_suspended(api):
    """PRD §3.1: "Returning a `SUSPENDED` carrier to `ACTIVE` bumps its `version` and does
    nothing else: agreements that were swept out with `suspension_reason` of
    `CARRIER_SUSPENDED` are **not** reactivated by it."
    PRD §3.2: "A successful activation sets `status` to `ACTIVE`, resets `suspension_reason`
    to `NONE` and bumps `version`."

    Design: Corner/state_machines/reinstating_a_carrier_leaves_its_agreements_suspended
    """
    aa, bb = setup_two_carriers()
    ag, _ = setup_agreement(aa["id"], bb["id"], "SPA_FLAT", activate=True)
    validate_success(api.suspend_carrier(bb["id"], OPERATOR), 200)

    reinstated = validate_success(api.reinstate_carrier(bb["id"], OPERATOR), 200)
    assert reinstated["status"] == "ACTIVE"

    still_suspended = read_agreement(ag["id"])
    assert still_suspended["status"] == "SUSPENDED", (
        "reinstatement must not reactivate the swept agreement"
    )
    assert still_suspended["suspension_reason"] == "CARRIER_SUSPENDED"

    reactivated = validate_success(api.activate_agreement(ag["id"], OPERATOR), 200)
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["suspension_reason"] == "NONE"
    assert reactivated["version"] == 4, (
        "creation, activation, the membership sweep and re-activation each bump version"
    )


# --------------------------------------------------------------------------- #
# Sector rate cards
# --------------------------------------------------------------------------- #
def test_factor_value_field_must_match_the_parent_agreement_type(api):
    """PRD §3.2: "The other two must be omitted entirely; supplying the wrong one, supplying
    more than one, or omitting all three, is refused with `ERR_FACTOR_FIELD_MISMATCH`."
    PRD §3.2: "A fresh draft opens in `DRAFT` status with `suspension_reason` of `NONE` and
    `factor_count` of zero."

    Design: Corner/validations/factor_value_field_mismatched_to_agreement_type_returns_error
    """
    aa, bb = setup_two_carriers()
    agreement = validate_success(
        api.create_agreement(
            create_agreement_payload(aa["id"], bb["id"], agreement_type="SPA_FLAT"),
            make_accountant_headers(aa["id"]),
        ),
        201,
    )

    resp = api.create_factor(
        agreement["id"],
        create_factor_payload(percent_bp=1500),
        make_accountant_headers(aa["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FACTOR_FIELD_MISMATCH.value)

    assert read_agreement(agreement["id"])["factor_count"] == 0
    rows, meta = validate_paginated(
        api.list_factors(agreement["id"], OPERATOR, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0, f"expected no factors, got {meta['total_count']}"
    assert rows == []


def test_duplicate_sector_triple_on_one_agreement_is_refused(api):
    """PRD §3.2: "No two factors of the same agreement may share an identical `origin`,
    `destination` and `class_of_service` combination, on pain of `ERR_DUPLICATE_FACTOR_SECTOR`."
    PRD §3.2: "Attaching a factor bumps the parent agreement's `factor_count` and its `version`."

    Design: Corner/validations/duplicate_factor_sector_triple_returns_error
    """
    aa, bb = setup_two_carriers()
    agreement, factors = setup_agreement(
        aa["id"],
        bb["id"],
        "SPA_FLAT",
        factors=[create_factor_payload("LHR", "CDG", "ECONOMY", flat_amount_minor=12000)],
        activate=False,
    )

    resp = api.create_factor(
        agreement["id"],
        create_factor_payload("LHR", "CDG", "ECONOMY", flat_amount_minor=9000),
        make_accountant_headers(aa["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_FACTOR_SECTOR.value)

    assert read_agreement(agreement["id"])["factor_count"] == 1
    rows, meta = validate_paginated(api.list_factors(agreement["id"], OPERATOR))
    assert meta["total_count"] == 1
    assert rows[0]["flat_amount_minor"] == 12000, "the incumbent factor is not overwritten"


def test_factor_cannot_be_attached_to_an_active_agreement(api):
    """PRD §3.2: "The agreement's rate card is a list of sector-level factors, each attached
    individually while the agreement is still `DRAFT` — once an agreement has been activated
    its card is frozen, and any attempt to add to it is refused with
    `ERR_AGREEMENT_STATE_INVALID`."

    Design: Corner/validations/factor_creation_on_an_active_agreement_returns_agreement_state_invalid
    """
    aa, bb = setup_two_carriers()
    agreement, _ = setup_agreement(
        aa["id"],
        bb["id"],
        "SPA_FLAT",
        factors=[create_factor_payload("LHR", "CDG", "ECONOMY", flat_amount_minor=12000)],
        activate=True,
    )

    resp = api.create_factor(
        agreement["id"],
        create_factor_payload("CDG", "FCO", "BUSINESS", flat_amount_minor=20000),
        make_accountant_headers(aa["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_STATE_INVALID.value)

    frozen = read_agreement(agreement["id"])
    assert frozen["factor_count"] == 1
    assert frozen["status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# Closed-closed agreement windows
# --------------------------------------------------------------------------- #
def test_agreement_sharing_one_endpoint_date_collides(api):
    """PRD §3.2: "Sharing a single endpoint date is therefore a collision: an agreement
    running through the 30th and one starting on the 30th conflict, and the two windows must
    be separated by at least one clear calendar day. A collision is refused with
    `ERR_AGREEMENT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/agreement_windows_are_closed_closed_so_shared_end_day_conflicts
    """
    aa, bb = setup_two_carriers()
    setup_agreement(
        aa["id"],
        bb["id"],
        "SPA_FLAT",
        activate=True,
        effective_from="2026-08-01",
        effective_to="2026-08-31",
    )
    second, _ = setup_agreement(
        aa["id"],
        bb["id"],
        "SPA_PERCENT",
        activate=False,
        effective_from="2026-08-31",
        effective_to="2026-09-30",
    )

    resp = api.activate_agreement(second["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_PERIOD_OVERLAP.value)


def test_failed_agreement_activation_leaves_both_windows_where_they_were(api):
    """PRD §3.2: "Considering every other agreement for the same ordered pair whose `status`
    is `ACTIVE` or `SUSPENDED` — drafts are invisible to the test — a collision exists when
    the candidate's `effective_from` is on or before the other's `effective_to` **and** the
    other's `effective_from` is on or before the candidate's `effective_to`."
    PRD §2.7: "When a request violates more than one rule, the response is decided by the
    **first** rule that fails in the ordering below, and no side effect of the request has
    been applied when it does."

    Design: Difficulty/resource_temporal_overlap/agreement_windows_are_closed_closed_so_shared_end_day_conflicts
    """
    aa, bb = setup_two_carriers()
    incumbent, _ = setup_agreement(
        aa["id"],
        bb["id"],
        "SPA_FLAT",
        activate=True,
        effective_from="2026-08-01",
        effective_to="2026-08-31",
    )
    candidate, _ = setup_agreement(
        aa["id"],
        bb["id"],
        "SPA_PERCENT",
        activate=False,
        effective_from="2026-08-31",
        effective_to="2026-09-30",
    )

    validate_error(
        api.activate_agreement(candidate["id"], OPERATOR),
        ApiErrorId.ERR_AGREEMENT_PERIOD_OVERLAP.value,
    )

    rejected = read_agreement(candidate["id"])
    assert_agreement(rejected)
    assert rejected["status"] == "DRAFT", "the rejected activation applies no side effect"
    assert rejected["suspension_reason"] == "NONE"
    assert read_agreement(incumbent["id"])["status"] == "ACTIVE"

    rows, meta = validate_paginated(
        api.list_agreements(
            OPERATOR, params={"issuing_carrier_id": aa["id"], "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 1, f"expected one ACTIVE agreement, got {meta['total_count']}"
    assert rows[0]["id"] == incumbent["id"]
