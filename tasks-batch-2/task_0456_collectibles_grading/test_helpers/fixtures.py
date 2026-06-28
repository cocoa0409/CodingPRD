"""Composite setup helpers.

These helpers encapsulate the multi-step lifecycle sequences that most tests
need to reach a state worth asserting on. Each helper builds its preconditions
from scratch using only PRD-declared endpoints, because the server database is
empty at the start of every test. They use get_success_data() (lenient) so a
setup failure surfaces as a clear "Setup failed" rather than a confusing
assertion error.

The customer is entity-backed: ownership-gated calls (submit, add item, delete
item, open regrade request) thread the real Customer.id through
make_customer_headers(); the opaque roles use shared constants.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_receiver_headers,
    make_grader_headers,
    make_authenticator_headers,
    make_lab_admin_headers,
)
from . import factories


# Standard EXPRESS tier used across the design indices: base 5000, rate 200bps,
# cap 50000. Standard CARD_10PT: equal 2500bps weights, max 10, authentic_min 1.0.
LAB = TEST_USERS["lab_admin_headers"]
RECEIVER = TEST_USERS["receiver_headers"]
GRADER = TEST_USERS["grader_headers"]
AUTH = TEST_USERS["authenticator_headers"]


# ---------------------------------------------------------------------------
# Tier 0 — atomic creators
# ---------------------------------------------------------------------------
def create_customer(email="c@example.com", full_name="C One"):
    return get_success_data(
        api_client.create_customer(factories.create_customer_payload(email=email, full_name=full_name))
    )


def create_service_level(**overrides):
    return get_success_data(
        api_client.create_service_level(factories.create_service_level_payload(**overrides), LAB)
    )


def create_grading_standard(**overrides):
    return get_success_data(
        api_client.create_grading_standard(factories.create_grading_standard_payload(**overrides), LAB)
    )


# ---------------------------------------------------------------------------
# Tier 1 — base catalog + draft submission
# ---------------------------------------------------------------------------
def setup_catalog(email="c@example.com", sl_overrides=None, gs_overrides=None):
    """Customer + EXPRESS service level + CARD_10PT grading standard.
    Returns (customer, service_level, grading_standard)."""
    customer = create_customer(email=email)
    sl = create_service_level(**(sl_overrides or {}))
    gs = create_grading_standard(**(gs_overrides or {}))
    return customer, sl, gs


def setup_draft_submission(email="c@example.com", sl_overrides=None, gs_overrides=None):
    """Catalog + a DRAFT submission owned by the customer.
    Returns (customer, service_level, grading_standard, submission)."""
    customer, sl, gs = setup_catalog(email=email, sl_overrides=sl_overrides, gs_overrides=gs_overrides)
    cust_headers = make_customer_headers(customer["id"])
    sub = get_success_data(
        api_client.create_submission(
            factories.create_submission_payload(customer["id"], sl["id"]), cust_headers
        )
    )
    return customer, sl, gs, sub


def add_item(submission_id, customer_id, grading_standard_id, declared_value_cents=30000, title="Card"):
    cust_headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.add_item(
            submission_id,
            factories.create_item_payload(grading_standard_id, title=title,
                                          declared_value_cents=declared_value_cents),
            cust_headers,
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 — submitted submission with N items
# ---------------------------------------------------------------------------
def setup_submitted_submission(item_specs=None, email="c@example.com",
                               sl_overrides=None, gs_overrides=None):
    """Catalog + submission with the given items, then submit.

    item_specs is a list of dicts each with declared_value_cents (and optionally
    title). Defaults to one 30000 item. Returns
    (customer, service_level, grading_standard, submission, [items]).
    The submission is left SUBMITTED.
    """
    if item_specs is None:
        item_specs = [{"declared_value_cents": 30000, "title": "Card"}]
    customer, sl, gs, sub = setup_draft_submission(
        email=email, sl_overrides=sl_overrides, gs_overrides=gs_overrides
    )
    cust_headers = make_customer_headers(customer["id"])
    items = []
    for i, spec in enumerate(item_specs):
        items.append(
            get_success_data(
                api_client.add_item(
                    sub["id"],
                    factories.create_item_payload(
                        gs["id"],
                        title=spec.get("title", f"Card{i}"),
                        declared_value_cents=spec["declared_value_cents"],
                    ),
                    cust_headers,
                )
            )
        )
    get_success_data(api_client.submit_submission(sub["id"], cust_headers))
    sub = get_success_data(api_client.get_submission(sub["id"], cust_headers))
    return customer, sl, gs, sub, items


# ---------------------------------------------------------------------------
# Tier 3 — item lifecycle steps
# ---------------------------------------------------------------------------
def log_intake(item_id, matches_declaration=True):
    return get_success_data(
        api_client.log_intake(
            item_id, factories.create_intake_payload(matches_declaration=matches_declaration), RECEIVER
        )
    )


def grade_item(item_id, grading_standard_id, centering=9, corners=9, edges=9, surface=9):
    return get_success_data(
        api_client.create_grade_assessment(
            item_id,
            factories.create_grade_assessment_payload(
                grading_standard_id, centering=centering, corners=corners,
                edges=edges, surface=surface,
            ),
            GRADER,
        )
    )


def finalize_assessment(ga_id):
    return get_success_data(api_client.finalize_assessment(ga_id, GRADER))


def authenticate_item(item_id, verdict="GENUINE", alteration_note=None):
    payload = factories.create_authentication_payload(verdict=verdict)
    if alteration_note is not None:
        payload["alteration_note"] = alteration_note
    return get_success_data(api_client.authenticate_item(item_id, payload, AUTH))


def encapsulate_item(item_id, assessment_id):
    return get_success_data(
        api_client.encapsulate_item(
            item_id, factories.create_encapsulate_payload(assessment_id), AUTH
        )
    )


def carry_item_to_grading(item_id, grading_standard_id, subgrades=(9, 9, 9, 9)):
    """INTAKE_LOGGED item -> create assessment (item now GRADING). Returns assessment."""
    return grade_item(item_id, grading_standard_id, *subgrades)


def carry_item_to_authenticated(item_id, grading_standard_id, subgrades=(9, 9, 9, 9),
                                verdict="GENUINE", alteration_note=None):
    """INTAKE_LOGGED item -> grade -> finalize -> authenticate. Returns (assessment, auth)."""
    ga = grade_item(item_id, grading_standard_id, *subgrades)
    finalize_assessment(ga["id"])
    auth = authenticate_item(item_id, verdict=verdict, alteration_note=alteration_note)
    return ga, auth


def carry_item_to_encapsulated(item_id, grading_standard_id, subgrades=(9, 9, 9, 9)):
    """INTAKE_LOGGED item -> grade -> finalize -> authenticate GENUINE -> encapsulate.
    Returns (assessment, slab)."""
    ga, _auth = carry_item_to_authenticated(item_id, grading_standard_id, subgrades=subgrades)
    slab = encapsulate_item(item_id, ga["id"])
    return ga, slab


# ---------------------------------------------------------------------------
# Tier 4 — full single-item scenarios at a chosen lifecycle stage
# ---------------------------------------------------------------------------
def setup_item_intake_logged(declared_value_cents=30000, title="Card",
                             matches_declaration=True, email="c@example.com",
                             sl_overrides=None, gs_overrides=None):
    """One-item submission, submitted, item INTAKE_LOGGED.
    Returns (customer, service_level, grading_standard, submission, item)."""
    customer, sl, gs, sub, items = setup_submitted_submission(
        item_specs=[{"declared_value_cents": declared_value_cents, "title": title}],
        email=email, sl_overrides=sl_overrides, gs_overrides=gs_overrides,
    )
    log_intake(items[0]["id"], matches_declaration=matches_declaration)
    return customer, sl, gs, sub, items[0]


def setup_item_graded(declared_value_cents=30000, subgrades=(9, 9, 9, 9),
                      finalized=False, title="Card", email="c@example.com",
                      sl_overrides=None, gs_overrides=None):
    """One-item submission carried to GRADING (assessment created). If finalized,
    also finalize the assessment.
    Returns (customer, sl, gs, submission, item, assessment)."""
    customer, sl, gs, sub, item = setup_item_intake_logged(
        declared_value_cents=declared_value_cents, title=title, email=email,
        sl_overrides=sl_overrides, gs_overrides=gs_overrides,
    )
    ga = grade_item(item["id"], gs["id"], *subgrades)
    if finalized:
        finalize_assessment(ga["id"])
    return customer, sl, gs, sub, item, ga


def setup_item_authenticated(declared_value_cents=30000, subgrades=(9, 9, 9, 9),
                             verdict="GENUINE", alteration_note=None, title="Card",
                             email="c@example.com", sl_overrides=None, gs_overrides=None):
    """One-item submission carried to AUTHENTICATED.
    Returns (customer, sl, gs, submission, item, assessment, auth)."""
    customer, sl, gs, sub, item = setup_item_intake_logged(
        declared_value_cents=declared_value_cents, title=title, email=email,
        sl_overrides=sl_overrides, gs_overrides=gs_overrides,
    )
    ga, auth = carry_item_to_authenticated(
        item["id"], gs["id"], subgrades=subgrades, verdict=verdict, alteration_note=alteration_note
    )
    return customer, sl, gs, sub, item, ga, auth


def setup_item_encapsulated(declared_value_cents=30000, subgrades=(9, 9, 9, 9),
                            title="Card", email="c@example.com",
                            sl_overrides=None, gs_overrides=None):
    """One-item submission carried all the way to ENCAPSULATED with an active slab.
    Returns (customer, sl, gs, submission, item, assessment, slab)."""
    customer, sl, gs, sub, item = setup_item_intake_logged(
        declared_value_cents=declared_value_cents, title=title, email=email,
        sl_overrides=sl_overrides, gs_overrides=gs_overrides,
    )
    ga, slab = carry_item_to_encapsulated(item["id"], gs["id"], subgrades=subgrades)
    return customer, sl, gs, sub, item, ga, slab


def get_item_version(item_id, customer_id):
    cust_headers = make_customer_headers(customer_id)
    item = get_success_data(api_client.get_item(item_id, cust_headers))
    return item["version"]


def open_regrade_request(item_id, customer_id, prior_slab_id, expected_item_version, reason="recheck"):
    cust_headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_regrade_request(
            item_id,
            factories.create_regrade_request_payload(prior_slab_id, expected_item_version, reason=reason),
            cust_headers,
        )
    )


def setup_item_cracked(declared_value_cents=30000, subgrades=(9, 9, 9, 9),
                       title="Card", email="c@example.com",
                       sl_overrides=None, gs_overrides=None):
    """Carry an item to ENCAPSULATED then open a regrade request (item now
    CRACK_PENDING, slab cracked, version bumped).
    Returns (customer, sl, gs, submission, item, first_assessment, prior_slab, regrade_request)."""
    customer, sl, gs, sub, item, ga, slab = setup_item_encapsulated(
        declared_value_cents=declared_value_cents, subgrades=subgrades, title=title,
        email=email, sl_overrides=sl_overrides, gs_overrides=gs_overrides,
    )
    item_v = get_item_version(item["id"], customer["id"])
    rr = open_regrade_request(item["id"], customer["id"], slab["id"], item_v)
    return customer, sl, gs, sub, item, ga, slab, rr


def setup_item_regraded_and_reencapsulated(declared_value_cents=30000,
                                           first_subgrades=(9, 9, 9, 9),
                                           second_subgrades=(9, 9, 9, 9),
                                           title="Card", email="c@example.com",
                                           sl_overrides=None, gs_overrides=None):
    """Full crack-and-regrade cycle: encapsulate, crack, regrade, finalize,
    re-authenticate GENUINE, re-encapsulate. regrade_count becomes 1.
    Returns (customer, sl, gs, submission, item, first_slab, second_assessment, second_slab)."""
    customer, sl, gs, sub, item, ga1, slab1, _rr = setup_item_cracked(
        declared_value_cents=declared_value_cents, subgrades=first_subgrades, title=title,
        email=email, sl_overrides=sl_overrides, gs_overrides=gs_overrides,
    )
    # CRACK_PENDING -> GRADING via new assessment.
    ga2 = grade_item(item["id"], gs["id"], *second_subgrades)
    finalize_assessment(ga2["id"])
    authenticate_item(item["id"], verdict="GENUINE")
    slab2 = encapsulate_item(item["id"], ga2["id"])
    return customer, sl, gs, sub, item, slab1, ga2, slab2


# ---------------------------------------------------------------------------
# Tier 5 — shipment / terminal scenarios
# ---------------------------------------------------------------------------
def setup_ready_to_ship(declared_value_cents=30000, subgrades=(9, 9, 9, 9),
                        title="Card", email="c@example.com",
                        sl_overrides=None, gs_overrides=None):
    """One-item submission carried to READY_TO_SHIP (sole item ENCAPSULATED).
    Returns (customer, sl, gs, submission, item, slab)."""
    customer, sl, gs, sub, item, _ga, slab = setup_item_encapsulated(
        declared_value_cents=declared_value_cents, subgrades=subgrades, title=title,
        email=email, sl_overrides=sl_overrides, gs_overrides=gs_overrides,
    )
    return customer, sl, gs, sub, item, slab


def create_shipment(submission_id, carrier="UPS", tracking_number="1Z999"):
    return get_success_data(
        api_client.create_shipment(
            submission_id, factories.create_shipment_payload(carrier=carrier, tracking_number=tracking_number), LAB
        )
    )


def setup_shipment_in_transit(declared_value_cents=30000, carrier="UPS",
                              tracking_number="1Z999", email="c@example.com",
                              sl_overrides=None, gs_overrides=None):
    """One-item submission carried to READY_TO_SHIP, shipment created and dispatched
    (IN_TRANSIT). Returns (customer, sl, gs, submission, item, shipment)."""
    customer, sl, gs, sub, item, _slab = setup_ready_to_ship(
        declared_value_cents=declared_value_cents, email=email,
        sl_overrides=sl_overrides, gs_overrides=gs_overrides,
    )
    ship = create_shipment(sub["id"], carrier=carrier, tracking_number=tracking_number)
    get_success_data(api_client.dispatch_shipment(ship["id"], LAB))
    ship = get_success_data(api_client.get_shipment(ship["id"], LAB))
    return customer, sl, gs, sub, item, ship


def setup_multi_item_shipment_in_transit(item_specs, carrier="FEDEX",
                                         tracking_number="FX222", email="c@example.com",
                                         sl_overrides=None, gs_overrides=None):
    """Multi-item submission: every item carried to ENCAPSULATED, submission
    READY_TO_SHIP, shipment dispatched (IN_TRANSIT).
    Returns (customer, sl, gs, submission, [items], shipment)."""
    customer, sl, gs, sub, items = setup_submitted_submission(
        item_specs=item_specs, email=email, sl_overrides=sl_overrides, gs_overrides=gs_overrides
    )
    # PRD §3.3: intake is permitted only while the submission is SUBMITTED/RECEIVING.
    # Log intake on every item before any item advances the posture to IN_GRADING.
    for it in items:
        log_intake(it["id"], matches_declaration=True)
    for it in items:
        ga, _slab = carry_item_to_encapsulated(it["id"], gs["id"])
    ship = create_shipment(sub["id"], carrier=carrier, tracking_number=tracking_number)
    get_success_data(api_client.dispatch_shipment(ship["id"], LAB))
    ship = get_success_data(api_client.get_shipment(ship["id"], LAB))
    return customer, sl, gs, sub, items, ship


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_insurance_policy(submission_id, customer_id):
    cust_headers = make_customer_headers(customer_id)
    data = get_success_data(api_client.get_insurance_policy(submission_id, cust_headers))
    # The endpoint returns the policy; data may be a list or an object envelope.
    if isinstance(data, list):
        return data[0]
    return data


def get_population_bucket(grading_standard_id, title_key, grade_value):
    """Return the single population bucket matching standard + grade, or None.

    PRD §3.10 specifies `title_key` only by example ("1986-FLEER-JORDAN-57") and
    never pins the normalization algorithm, so it is not derivable and must not be
    used as a hardcoded filter. Under per-test-server isolation each test seeds a
    single item, so filtering by (grading_standard_id, grade_value) uniquely
    identifies the bucket.
    """
    resp = api_client.list_population_reports(
        LAB,
        params={
            "grading_standard_id": grading_standard_id,
            "grade_value": grade_value,
        },
    )
    data = get_success_data(resp)
    if isinstance(data, list):
        return data[0] if data else None
    return data
