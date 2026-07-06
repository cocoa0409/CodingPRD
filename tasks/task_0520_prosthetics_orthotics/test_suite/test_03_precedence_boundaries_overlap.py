"""Validation precedence conflicts, inclusive temporal/numeric boundaries, and
resource-temporal overlap rules.

Covers Queue A (Difficulty) instances: priority_pair_validation_conflict,
boundary_precision_check, resource_temporal_overlap.
"""
from test_helpers import validate_success, validate_error, validate_error_is_one_of
from test_helpers.test_users import TEST_USERS, make_physician_headers, make_practitioner_headers
from test_helpers.fixtures import (
    setup_cast, setup_order_at_intake, add_milestone, set_clock, create_physician,
    create_supplier, create_patient, create_signed_prescription, deliver,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_prescription_payload, create_device_order_payload, deliver_payload,
)


# ─── Queue A: priority_pair_validation_conflict ──────────────────────

def test_deliver_state_outranks_compliance_gate(api):
    """PRD §3.10: "State legality is checked fifth: a transition not defined from the
    resource's current state yields `ERR_INVALID_STATE`. Only after these structural
    checks do the domain-specific business rules apply — the compliance gate, segregation
    of duties, prescription validity and signing, PECOS enrollment, KX-without-auth,
    duplicate milestones, in-warranty replacement, billing-amount validity, the
    same-or-similar overlap, the single-active-authorization rule, the
    optimistic-concurrency version match, and the well-formedness of the request body."

    Design: Difficulty/priority_pair_validation_conflict/deliver_state_vs_compliance_conflict
    """
    # Order still in FABRICATION (not READY_FOR_FITTING) AND supplier UNACCREDITED.
    # State (p5) outranks the compliance gate (a business rule), so ERR_INVALID_STATE wins.
    cast = setup_order_at_intake(
        supplier_overrides={"legal_name": "Unaccred O&P", "accreditation_expiry": None,
                            "surety_bond_active": True})
    add_milestone(cast["ord_id"], cast["fit_id"], step="CASTING", weight=2)
    add_milestone(cast["ord_id"], cast["fit_id"], step="ASSEMBLY", weight=3)
    api.start_fabrication(cast["ord_id"], make_practitioner_headers(cast["fit_id"]))
    live = validate_success(
        api.get_device_order(cast["ord_id"], make_practitioner_headers(cast["fit_id"])), 200)
    assert live["status"] == "FABRICATION"
    res = api.deliver_order(cast["ord_id"], deliver_payload(live["version"]),
                            make_practitioner_headers(cast["fit_id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_deliver_state_conflict_leaves_order_in_fabrication(api):
    """PRD §3.5: "The delivery attestation is performed by a `Practitioner` on an order in
    `READY_FOR_FITTING`, advancing it to the terminal `DELIVERED` state."
    PRD §3.10: "State legality is checked fifth: a transition not defined from the
    resource's current state yields `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/deliver_state_vs_compliance_conflict
    """
    # Same dual-violation scenario; distinct observable: the rejected deliver leaves the
    # order in FABRICATION (no transition, no delivery_date stamped).
    cast = setup_order_at_intake(
        supplier_overrides={"legal_name": "Unaccred O&P", "accreditation_expiry": None,
                            "surety_bond_active": True})
    add_milestone(cast["ord_id"], cast["fit_id"], step="CASTING", weight=2)
    add_milestone(cast["ord_id"], cast["fit_id"], step="ASSEMBLY", weight=3)
    api.start_fabrication(cast["ord_id"], make_practitioner_headers(cast["fit_id"]))
    live = validate_success(
        api.get_device_order(cast["ord_id"], make_practitioner_headers(cast["fit_id"])), 200)
    api.deliver_order(cast["ord_id"], deliver_payload(live["version"]),
                      make_practitioner_headers(cast["fit_id"]))
    after = validate_success(
        api.get_device_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    assert after["status"] == "FABRICATION"
    assert after["delivery_date"] is None


def test_order_create_rx_validity_outranks_not_signed(api):
    """PRD §3.10: "When an operation is subject to several checks, they are evaluated in
    a fixed precedence so that the most fundamental failures surface first."
    PRD §3.10: "Only after these structural checks do the domain-specific business rules
    apply — the compliance gate, segregation of duties, prescription validity and
    signing, PECOS enrollment, KX-without-auth, duplicate milestones, in-warranty
    replacement, billing-amount validity, the same-or-similar overlap, the
    single-active-authorization rule, the optimistic-concurrency version match, and the
    well-formedness of the request body."

    Design: Difficulty/priority_pair_validation_conflict/order_create_rx_expired_vs_not_signed_conflict
    """
    # A DRAFT (never-signed) Rx whose face_to_face is also >6 months stale. Two PRD
    # sentences govern the relative precedence: §3.3 narrates the SIGNED-status check
    # (ERR_RX_NOT_SIGNED) before the validity-window check (ERR_RX_EXPIRED), while §3.10
    # groups "prescription validity and signing" with validity listed first. The PRD does
    # not pin a sub-order within that grouped concern, so both error_ids are PRD-faithful
    # outcomes for this combined precondition.
    set_clock("2026-06-01T00:00:00Z")
    rx_phys = create_physician(pecos=True, npi="1111111111", name="Dr Rx")
    fit = create_physician(pecos=True, npi="2222222222", name="Tech Fit")
    supplier = create_supplier()
    patient = create_patient(medicare=False)
    rx = validate_success(api.create_prescription(
        create_prescription_payload(
            patient["id"], rx_phys["id"], device_category="LOWER_EXTREMITY_ORTHOSIS",
            primary_diagnosis_code="M21.6X1", face_to_face_date="2025-01-01"),
        make_physician_headers(rx_phys["id"])), 201)
    assert rx["status"] == "DRAFT"  # never signed
    res = api.create_device_order(
        create_device_order_payload(rx["id"], supplier["id"], fit["id"]),
        TEST_USERS["billing_headers"])
    validate_error_is_one_of(res, ["ERR_RX_EXPIRED", "ERR_RX_NOT_SIGNED"])


def test_rx_expired_conflict_leaves_prescription_draft(api):
    """PRD §3.3: "The logical clock must fall at or before the prescription's
    face-to-face date plus six months; ordering against a prescription past that validity
    window is rejected with `ERR_RX_EXPIRED`."
    PRD §3.3: "Order creation also consumes the prescription as described in §3.2,
    advancing it from `SIGNED` to `CONSUMED` and incrementing the prescription's
    `version`."

    Design: Difficulty/priority_pair_validation_conflict/order_create_rx_expired_vs_not_signed_conflict
    """
    # Distinct observable: the rejected order creation does NOT consume the prescription,
    # which remains in DRAFT (never signed) rather than CONSUMED.
    set_clock("2026-06-01T00:00:00Z")
    rx_phys = create_physician(pecos=True, npi="1111111111", name="Dr Rx")
    fit = create_physician(pecos=True, npi="2222222222", name="Tech Fit")
    supplier = create_supplier()
    patient = create_patient(medicare=False)
    rx = validate_success(api.create_prescription(
        create_prescription_payload(
            patient["id"], rx_phys["id"], device_category="LOWER_EXTREMITY_ORTHOSIS",
            primary_diagnosis_code="M21.6X1", face_to_face_date="2025-01-01"),
        make_physician_headers(rx_phys["id"])), 201)
    api.create_device_order(
        create_device_order_payload(rx["id"], supplier["id"], fit["id"]),
        TEST_USERS["billing_headers"])
    after = validate_success(api.get_prescription(rx["id"], TEST_USERS["billing_headers"]), 200)
    assert after["status"] == "DRAFT"


# ─── Queue A: boundary_precision_check ───────────────────────────────

def test_supplier_accredited_at_exact_expiry_boundary(api):
    """PRD §2.8: "Otherwise, if the logical clock is at or before `accreditation_expiry`,
    the status is `ACCREDITED`; a clock value exactly equal to `accreditation_expiry` is
    still `ACCREDITED`."

    Design: Difficulty/boundary_precision_check/supplier_accreditation_inclusive_boundary
    """
    supplier = create_supplier(legal_name="Edge O&P",
                               accreditation_expiry="2026-06-01T00:00:00Z",
                               surety_bond_active=True)
    set_clock("2026-06-01T00:00:00Z")
    fetched = validate_success(
        api.get_supplier(supplier["id"], TEST_USERS["compliance_headers"]), 200)
    assert fetched["accreditation_status"] == "ACCREDITED"


def test_supplier_lapsed_one_second_past_expiry(api):
    """PRD §2.8: "Once the logical clock passes `accreditation_expiry`, the status is
    `LAPSED`."

    Design: Difficulty/boundary_precision_check/supplier_accreditation_inclusive_boundary
    """
    supplier = create_supplier(legal_name="Edge O&P",
                               accreditation_expiry="2026-06-01T00:00:00Z",
                               surety_bond_active=True)
    set_clock("2026-06-01T00:00:01Z")
    fetched = validate_success(
        api.get_supplier(supplier["id"], TEST_USERS["compliance_headers"]), 200)
    assert fetched["accreditation_status"] == "LAPSED"


def test_milestone_progress_zero_with_no_milestones(api):
    """PRD §3.4: "the progress percentage is the sum of the `weight` of completed
    milestones, multiplied by 100, divided by the sum of the `weight` of all milestones
    for the order, rounded half up to a whole percent; when the order has no milestones
    at all the percentage is 0."

    Design: Difficulty/boundary_precision_check/fabrication_progress_empty_milestone_set
    """
    cast = setup_order_at_intake()  # INTAKE, zero milestones
    order = validate_success(api.get_device_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    assert order["milestone_progress_pct"] == 0


def test_new_order_progress_zero_in_create_response(api):
    """PRD §3.3: "A newly created order carries `milestone_progress_pct` of 0,
    `allowed_total_cents` of 0, and null `delivery_date` and `warranty_expiry`."
    PRD §3.4: "when the order has no milestones at all the percentage is 0."

    Design: Difficulty/boundary_precision_check/fabrication_progress_empty_milestone_set
    """
    # Distinct observable: the empty-milestone-set 0 is already present in the order's
    # creation response (not only on a later GET).
    cast = setup_order_at_intake()
    assert cast["order"]["milestone_progress_pct"] == 0


# ─── Queue A: resource_temporal_overlap ──────────────────────────────

def test_same_similar_overlap_inside_five_year_window(api):
    """PRD §3.3: "Order creation is rejected with `ERR_SAME_SIMILAR_OVERLAP` when the
    same patient already has a `DELIVERED` device order of the same `device_category`
    whose reasonable-useful-lifetime window is still open — that is, when the logical
    clock falls within the closed interval that begins at the prior order's
    `delivery_date` and ends at that delivery date plus five years, inclusive of both
    endpoints."

    Design: Difficulty/resource_temporal_overlap/same_similar_5yr_rul_overlap_on_patient
    """
    # Prior order delivered 2026-06-01; clock advanced to 2027-06-01, inside
    # [2026-06-01, 2031-06-01]. A second same-category order for the same patient is
    # rejected.
    set_clock("2026-06-01T00:00:00Z")
    rx_phys = create_physician(pecos=True, npi="1111111111", name="Dr Rx")
    fit = create_physician(pecos=True, npi="2222222222", name="Tech Fit")
    supplier = create_supplier()
    patient = create_patient(medicare=False)
    rx1 = create_signed_prescription(patient["id"], rx_phys["id"],
                                     "LOWER_EXTREMITY_ORTHOSIS", "M21.6X1",
                                     face_to_face_date="2026-05-20")
    order1 = validate_success(api.create_device_order(
        create_device_order_payload(rx1["id"], supplier["id"], fit["id"]),
        TEST_USERS["billing_headers"]), 201)
    ms = add_milestone(order1["id"], fit["id"], step="ASSEMBLY", weight=1)
    api.start_fabrication(order1["id"], make_practitioner_headers(fit["id"]))
    api.complete_milestone(ms["id"], make_practitioner_headers(fit["id"]))
    live = validate_success(api.get_device_order(order1["id"], TEST_USERS["billing_headers"]), 200)
    deliver(order1["id"], fit["id"], live["version"])

    set_clock("2027-06-01T00:00:00Z")
    rx2 = create_signed_prescription(patient["id"], rx_phys["id"],
                                     "LOWER_EXTREMITY_ORTHOSIS", "M21.6X1",
                                     face_to_face_date="2027-05-20")
    res = api.create_device_order(
        create_device_order_payload(rx2["id"], supplier["id"], fit["id"]),
        TEST_USERS["billing_headers"])
    validate_error(res, "ERR_SAME_SIMILAR_OVERLAP")


def test_same_similar_overlap_requires_delivered_prior_order(api):
    """PRD §3.3: "Order creation is rejected with `ERR_SAME_SIMILAR_OVERLAP` when the same
    patient already has a `DELIVERED` device order of the same `device_category` whose
    reasonable-useful-lifetime window is still open — that is, when the logical clock
    falls within the closed interval that begins at the prior order's `delivery_date` and
    ends at that delivery date plus five years, inclusive of both endpoints."

    Design: Difficulty/resource_temporal_overlap/same_similar_5yr_rul_overlap_on_patient
    """
    # Distinct facet: the prior same-category order is NOT delivered (stays INTAKE), so it
    # has no delivery_date and the overlap rule does not trigger — a second same-category
    # order for the same patient is accepted.
    set_clock("2026-06-01T00:00:00Z")
    rx_phys = create_physician(pecos=True, npi="1111111111", name="Dr Rx")
    fit = create_physician(pecos=True, npi="2222222222", name="Tech Fit")
    supplier = create_supplier()
    patient = create_patient(medicare=False)
    rx1 = create_signed_prescription(patient["id"], rx_phys["id"],
                                     "LOWER_EXTREMITY_ORTHOSIS", "M21.6X1",
                                     face_to_face_date="2026-05-20")
    validate_success(api.create_device_order(
        create_device_order_payload(rx1["id"], supplier["id"], fit["id"]),
        TEST_USERS["billing_headers"]), 201)  # stays at INTAKE, never delivered
    rx2 = create_signed_prescription(patient["id"], rx_phys["id"],
                                     "LOWER_EXTREMITY_ORTHOSIS", "M21.6X1",
                                     face_to_face_date="2026-05-20")
    order2 = validate_success(api.create_device_order(
        create_device_order_payload(rx2["id"], supplier["id"], fit["id"]),
        TEST_USERS["billing_headers"]), 201)
    assert order2["status"] == "INTAKE"


def test_single_active_auth_occupation_rejected(api):
    """PRD §3.4: "The single-active-authorization rule means an order may hold at most one
    open authorization at a time: if the order already owns a `PriorAuth` whose status is
    `SUBMITTED`, `PENDED`, or `APPROVED`, the submission is rejected with
    `ERR_AUTH_ALREADY_OPEN`; only once an existing authorization has reached a terminal
    status of `DENIED` or `EXPIRED` is the slot freed for a fresh submission."

    Design: Difficulty/resource_temporal_overlap/single_active_auth_occupation_on_order
    """
    # The first submit advances the order INTAKE -> AUTH_PENDING, so by the time the
    # order owns an open (SUBMITTED) PriorAuth it has necessarily left INTAKE. §3.10 orders
    # state legality (ERR_INVALID_STATE, "checked fifth") strictly before the
    # single-active-authorization rule ("Only after these structural checks do the
    # domain-specific business rules apply — ... the single-active-authorization rule").
    # §3.4 names ERR_AUTH_ALREADY_OPEN for owning an open auth. The PRD therefore does not
    # uniquely pin which fires for the second submission; both are PRD-faithful.
    cast = setup_order_at_intake(device_category="LOWER_LIMB_PROSTHETIC",
                                 diagnosis="Z89.511", medicare=True)
    validate_success(api.submit_auth(cast["ord_id"], TEST_USERS["billing_headers"]), 201)
    res = api.submit_auth(cast["ord_id"], TEST_USERS["billing_headers"])
    validate_error_is_one_of(res, ["ERR_AUTH_ALREADY_OPEN", "ERR_INVALID_STATE"])


def test_single_active_auth_rejected_submit_does_not_create_second_auth(api):
    """PRD §3.4: "The single-active-authorization rule means an order may hold at most one
    open authorization at a time: if the order already owns a `PriorAuth` whose status is
    `SUBMITTED`, `PENDED`, or `APPROVED`, the submission is rejected with
    `ERR_AUTH_ALREADY_OPEN`; only once an existing authorization has reached a terminal
    status of `DENIED` or `EXPIRED` is the slot freed for a fresh submission."

    Design: Difficulty/resource_temporal_overlap/single_active_auth_occupation_on_order
    """
    # Distinct observable: the rejected second submit-auth does NOT create a second
    # PriorAuth — the order still owns exactly one.
    cast = setup_order_at_intake(device_category="LOWER_LIMB_PROSTHETIC",
                                 diagnosis="Z89.511", medicare=True)
    validate_success(api.submit_auth(cast["ord_id"], TEST_USERS["billing_headers"]), 201)
    api.submit_auth(cast["ord_id"], TEST_USERS["billing_headers"])  # rejected
    auths = validate_success(
        api.list_prior_auths(TEST_USERS["billing_headers"],
                             params={"device_order_id": cast["ord_id"]}), 200)
    assert len(auths) == 1
