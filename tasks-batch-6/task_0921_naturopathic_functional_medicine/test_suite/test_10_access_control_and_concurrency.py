"""Authentication, role permission, segregation of duties and optimistic concurrency."""

from test_helpers import (
    NO_AUTH_HEADERS,
    UNKNOWN_UUID,
    ApiErrorId,
    make_coach_headers,
    make_director_headers,
    make_nd_headers,
    make_tech_headers,
    open_membership,
    protocol_version,
    read_membership,
    read_patient,
    register_coach,
    register_director,
    register_nd,
    register_patient,
    setup_active_protocol,
    setup_frozen_by_scope_review,
    set_clock,
    submit_and_attest,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN


def test_a_request_without_a_role_header_is_refused_before_anything_else(api):
    """PRD §2.1: "Every request to this API — without exception, including reads
    — must carry two headers. `X-User-ID` identifies the acting principal and
    `X-User-Role` names the capacity in which they are acting. If either header
    is missing or present but empty, the request is refused with
    `ERR_UNAUTHENTICATED` and HTTP 401 before anything else about the request is
    examined."

    Design: Corner/validations/request_without_role_header_is_unauthenticated
    """
    response = api.get_patient(UNKNOWN_UUID, NO_AUTH_HEADERS)
    error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert error["error_id"] != ApiErrorId.ERR_PATIENT_NOT_FOUND.value


def test_a_list_with_limit_zero_is_a_pagination_failure(api):
    """PRD §2.3: "`limit` controls page size: it defaults to 10 when absent, its
    minimum accepted value is 1 and its maximum accepted value is 100."
    PRD §2.3: "A `limit` that is not an integer or falls outside the range from
    1 to 100 inclusive, or an `offset` that is not an integer or is negative, is
    refused with `ERR_INVALID_PAGINATION` and HTTP 400."

    Design: Corner/validations/list_with_limit_zero_returns_invalid_pagination
    """
    nd = register_nd(api)
    register_patient(api, nd["id"])

    response = api.list_patients(ADMIN, params={"limit": 0, "offset": 0})
    validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)


def test_a_health_coach_may_not_order_a_functional_panel(api):
    """PRD §2.1: "A `HealthCoach` is a non-prescribing member of the clinical
    team. Coaches help patients complete intake, collect specimens, run and
    complete visits, and answer messages, but may never order a panel or touch a
    protocol."
    PRD §2.6: "The supplied `X-User-Role` appears in the addressed endpoint's
    declared role list, on every endpoint — otherwise `ERR_ROLE_NOT_PERMITTED`
    (403)."

    Design: Corner/rbac/health_coach_cannot_order_a_functional_lab_panel
    """
    nd = register_nd(api)
    coach = register_coach(api)
    patient = register_patient(api, nd["id"])

    response = api.create_lab_order(
        {
            "patient_id": patient["id"],
            "panel_code": "SERUM_METABOLIC",
            "funding_source": "CASH",
            "requested_collection_date": "2026-05-04",
            "fasting_attested": True,
        },
        make_coach_headers(coach["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    rows, meta = validate_paginated(
        api.list_lab_orders(make_nd_headers(nd["id"]), params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_a_director_may_not_close_a_scope_review_on_their_own_patient(api):
    """PRD §3.1: "Closing a review is where segregation of duties bites. The
    acting `ClinicalDirector`'s practitioner id must not be the patient's
    `primary_practitioner_id`; a director reviewing their own patient is refused
    with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.1: "A `UNDER_REVIEW → CLEARED` closure recomputes the gate: it
    re-opens to `OPEN` when `red_flag_referral_open` is false, but lands on
    `FROZEN_RED_FLAG` when a red flag is still outstanding, because clearing a
    scope concern does not clear a critical laboratory result."

    Design: Corner/rbac/clinical_director_cannot_close_a_scope_review_on_their_own_patient
    """
    own_director = register_director(api, full_name="Dr Ines Park", npi="1987654327")
    other_director = register_director(api, full_name="Dr Omar Vega", npi="1555666773")
    patient = register_patient(api, own_director["id"])

    validate_success(
        api.open_scope_review(
            patient["id"],
            {"reason": "supervision query"},
            make_director_headers(own_director["id"]),
        )
    )

    refused = api.close_scope_review(
        patient["id"], {"outcome": "CLEARED"}, make_director_headers(own_director["id"])
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert read_patient(api, patient["id"])["scope_review_status"] == "UNDER_REVIEW"

    cleared = validate_success(
        api.close_scope_review(
            patient["id"],
            {"outcome": "CLEARED", "notes": "scope confirmed appropriate"},
            make_director_headers(other_director["id"]),
        )
    )
    assert cleared["scope_review_status"] == "CLEARED"
    assert cleared["clinical_write_gate"] == "OPEN"


def test_a_stale_patient_version_is_refused_on_a_protocol_draft(api):
    """PRD §2.10: "Drafting a protocol requires `expected_patient_version`
    matching the target `Patient`'s current `version`. A revision may
    legitimately supersede whatever protocol the patient currently has, so no
    state precondition distinguishes a well-informed author from one working off
    a chart snapshot that has since moved; the patient version is the only thing
    that does."
    PRD §2.10: "In each case the request must carry an expected-version field
    naming the client's last observed `version` of the parent, the field is a
    required input rather than an optional one, and a value that does not equal
    the parent's current `version` is refused with `ERR_STALE_VERSION` and HTTP
    412."

    Design: Corner/cross_cutting_complexity_layers/stale_patient_version_rejects_a_protocol_create
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])
    stale_version = patient["version"]
    submit_and_attest(api, patient["id"], "CHIEF_COMPLAINT_TIMELINE")

    refused = api.create_protocol(
        {
            "patient_id": patient["id"],
            "title": "Repletion",
            "symptom_score_baseline": 28,
            "expected_patient_version": stale_version,
        },
        make_nd_headers(nd["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION.value, 412)

    current_version = read_patient(api, patient["id"])["version"]
    accepted = validate_success(
        api.create_protocol(
            {
                "patient_id": patient["id"],
                "title": "Repletion",
                "symptom_score_baseline": 28,
                "expected_patient_version": current_version,
            },
            make_nd_headers(nd["id"]),
        ),
        201,
    )
    assert accepted["status"] == "DRAFT"

    rows, meta = validate_paginated(
        api.list_protocols(make_nd_headers(nd["id"]), params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == accepted["id"]


def test_a_stale_protocol_version_is_refused_on_a_second_dispense(api):
    """PRD §2.10: "Creating a dispense requires `expected_protocol_version`
    matching the owning `Protocol`'s current `version`. Repeat fills of the same
    line are perfectly legitimate while stock lasts, so nothing else catches a
    dispenser who has not seen the titration decision or the line
    discontinuation that moved the protocol on."
    PRD §3.8: "A mismatched `expected_protocol_version` is refused with
    `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/stale_protocol_version_rejects_a_second_dispense
    """
    ctx = setup_active_protocol(api)
    nd, tech = ctx["nd"], ctx["tech"]
    stale_version = protocol_version(api, ctx["protocol"]["id"], nd["id"])

    first = validate_success(
        api.create_dispense(
            {
                "protocol_item_id": ctx["item"]["id"],
                "quantity": 2,
                "expected_protocol_version": stale_version,
            },
            make_tech_headers(tech["id"]),
        ),
        201,
    )

    second = api.create_dispense(
        {
            "protocol_item_id": ctx["item"]["id"],
            "quantity": 2,
            "expected_protocol_version": stale_version,
        },
        make_tech_headers(tech["id"]),
    )
    validate_error(second, ApiErrorId.ERR_STALE_VERSION.value, 412)

    lot = validate_success(api.get_product_lot(ctx["lot"]["id"], make_nd_headers(nd["id"])))
    assert lot["quantity_on_hand"] == 18

    rows, meta = validate_paginated(
        api.list_dispenses(
            make_nd_headers(nd["id"]), params={"protocol_item_id": ctx["item"]["id"]}
        )
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == first["id"]
    assert read_patient(api, ctx["patient"]["id"])["cash_charged_total_cents"] == 9990


def test_a_stale_membership_version_is_refused_on_a_tier_change(api):
    """PRD §2.10: "Changing a membership tier requires
    `expected_membership_version` matching that `Membership`'s current
    `version`. Consecutive tier changes are legitimate and each one re-prorates
    from the counters it finds, so a stale author would otherwise silently
    re-prorate against entitlement figures a prior change or an encounter
    reservation has already rewritten."
    PRD §3.2: "The request names the `new_tier` and carries
    `expected_membership_version`; a value that does not match the membership's
    current `version` is refused with `ERR_STALE_VERSION` before any arithmetic
    runs."

    Design: Corner/cross_cutting_complexity_layers/stale_membership_version_rejects_a_tier_change
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])
    membership = open_membership(
        api, patient["id"], tier="CORE", cycle_start_date="2026-05-01"
    )
    stale_version = membership["version"]

    set_clock(api, "2026-05-05T00:00:00Z")
    validate_success(api.pause_membership(membership["id"], ADMIN))
    set_clock(api, "2026-05-15T00:00:00Z")
    validate_success(api.resume_membership(membership["id"], ADMIN))

    response = api.change_membership_tier(
        membership["id"],
        {"new_tier": "PREMIER", "expected_membership_version": stale_version},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    unchanged = read_membership(api, patient["id"])
    assert unchanged["tier"] == "CORE"
    assert unchanged["last_proration_net_charge_cents"] == 0
    assert unchanged["visits_granted"] == 4
    assert read_patient(api, patient["id"])["cash_charged_total_cents"] == 0


def test_the_write_gate_pre_empts_the_missing_quantity_on_a_dispense(api):
    """PRD §2.5: "The gate is checked unusually early — earlier than payload
    shape and earlier than enum membership. On a gated endpoint, a request that
    is simultaneously malformed and aimed at a frozen patient is answered with
    `ERR_CLINICAL_WRITE_FROZEN`, not with a payload complaint: the server
    declines to tell a caller what is wrong with a payload it is not going to
    consider."
    PRD §2.6: "Note the two consequences of this ordering that are easy to get
    wrong. Because the gate sits at rung 6 while payload shape sits at rung 11,
    a frozen patient masks payload errors on gated endpoints."

    Design: Difficulty/priority_pair_validation_conflict/write_gate_pre_empts_payload_shape_on_a_dispense
    """
    ctx = setup_frozen_by_scope_review(api)
    nd, tech = ctx["nd"], ctx["tech"]
    version = protocol_version(api, ctx["protocol"]["id"], nd["id"])

    response = api.create_dispense(
        {
            "protocol_item_id": ctx["item"]["id"],
            "expected_protocol_version": version,
        },
        make_tech_headers(tech["id"]),
    )
    error = validate_error(response, ApiErrorId.ERR_CLINICAL_WRITE_FROZEN.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_VALIDATION.value


def test_the_frozen_chart_refuses_a_well_formed_dispense_and_moves_no_stock(api):
    """PRD §2.5: "While the gate is anything other than `OPEN`, exactly eight
    endpoint families are frozen and answer `ERR_CLINICAL_WRITE_FROZEN` with
    HTTP 409"
    PRD §2.6: "On the eight gated endpoints enumerated in §2.5, the implicated
    patient's `clinical_write_gate` must be `OPEN` — otherwise
    `ERR_CLINICAL_WRITE_FROZEN` (409). This rung pre-empts every rung below it,
    payload shape and enum membership included."

    Design: Difficulty/priority_pair_validation_conflict/write_gate_pre_empts_payload_shape_on_a_dispense
    """
    ctx = setup_frozen_by_scope_review(api)
    nd, tech = ctx["nd"], ctx["tech"]
    version = protocol_version(api, ctx["protocol"]["id"], nd["id"])

    validate_error(
        api.create_dispense(
            {
                "protocol_item_id": ctx["item"]["id"],
                "quantity": 1,
                "expected_protocol_version": version,
            },
            make_tech_headers(tech["id"]),
        ),
        ApiErrorId.ERR_CLINICAL_WRITE_FROZEN.value,
        409,
    )

    lot = validate_success(api.get_product_lot(ctx["lot"]["id"], make_nd_headers(nd["id"])))
    assert lot["quantity_on_hand"] == 20
    assert read_patient(api, ctx["patient"]["id"])["clinical_write_gate"] == "FROZEN_SCOPE_REVIEW"
