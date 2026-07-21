"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared endpoints,
because the test harness restarts the server (empty DB) before every test. Setup calls
use get_success_data() (lenient) so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing assertion failure downstream.

Identity threading: helpers create a Fitter first and thread its id via
make_fitter_headers() into every ownership-sensitive Fitter call (sales, appointments
and their lifecycle), so ownership checks against a resource's fitter foreign key
compare equal.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client as api
from .test_users import TEST_USERS, make_fitter_headers

SM = TEST_USERS["store_manager_headers"]
BS = TEST_USERS["billing_specialist_headers"]


# --------------------------- primitives ---------------------------
def set_clock(iso="2026-07-01T00:00:00Z"):
    return get_success_data(api.set_clock({"to_iso8601": iso}, SM))


def create_product(**over):
    payload = {"name": "Shoe", "brand": "B", "category": "REGULAR", "base_price_cents": 9000}
    payload.update(over)
    return get_success_data(api.create_product(payload, SM))


def create_inventory(product_id, **over):
    payload = {"product_id": product_id, "size": 9.0, "width": "D",
               "lot_number": "L1", "quantity_on_hand": 5}
    payload.update(over)
    return get_success_data(api.create_inventory_item(payload, SM))


def create_customer(**over):
    payload = {"full_name": "Cust", "date_of_birth": "1960-01-01"}
    payload.update(over)
    return get_success_data(api.create_customer(payload, SM))


def create_fitter(**over):
    payload = {"full_name": "Fitter"}
    payload.update(over)
    return get_success_data(api.create_fitter(payload, SM))


def create_gait_lab(**over):
    payload = {"name": "Lab", "concurrent_capacity": 1}
    payload.update(over)
    return get_success_data(api.create_gait_lab(payload, SM))


def create_certification(customer_id, expected_version, **over):
    payload = {"certifying_physician_npi": "1234567890",
               "prescribing_practitioner_npi": "0987654321",
               "statement_date": "2026-06-01", "in_person_visit_date": "2026-05-01",
               "expected_customer_version": expected_version}
    payload.update(over)
    return get_success_data(api.create_certification(customer_id, payload, BS))


def open_sale(customer_id, fitter_id, fitter_headers, **over):
    payload = {"customer_id": customer_id, "fitter_id": fitter_id}
    payload.update(over)
    return get_success_data(api.create_sale(payload, fitter_headers))


def add_line(sale_id, inventory_item_id, fitter_headers, **over):
    payload = {"inventory_item_id": inventory_item_id, "quantity": 1}
    payload.update(over)
    return get_success_data(api.add_sale_line(sale_id, payload, fitter_headers))


def fulfill_sale(sale_id, fitter_headers):
    return get_success_data(api.fulfill_sale(sale_id, fitter_headers))


def get_customer(customer_id, headers=None):
    return get_success_data(api.get_customer(customer_id, headers or SM))


def get_inventory(inventory_item_id, headers=None):
    return get_success_data(api.get_inventory_item(inventory_item_id, headers or SM))


def get_sale(sale_id, headers=None):
    return get_success_data(api.get_sale(sale_id, headers or SM))


def get_sale_line(sale_line_id, headers=None):
    return get_success_data(api.get_sale_line(sale_line_id, headers or SM))


def get_claim(claim_id, headers=None):
    return get_success_data(api.get_claim(claim_id, headers or BS))


def get_return(return_id, headers=None):
    return get_success_data(api.get_return(return_id, headers or SM))


def get_certification(customer_id, cert_id):
    """Fetch a specific certification via the customer's certification list."""
    data, _meta = _list(api.list_certifications(customer_id, BS))
    for c in data:
        if c["id"] == cert_id:
            return c
    raise AssertionError(f"Setup failed: certification {cert_id} not found in list")


def _list(response):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)


# --------------------------- composites: Medicare ---------------------------
def setup_fulfilled_medicare_sale(*, price=30000, allowable=30000, hcpcs="A5500",
                                  dob="1950-01-01", mbi="1EG4TE5MK73",
                                  statement_date="2026-06-01", visit_date="2026-05-01",
                                  clock="2026-07-01T00:00:00Z"):
    """Diabetic product + stock, adult Medicare customer, COMPLETE cert, and a fulfilled
    one-unit sale. Returns a context dict with every id and the fitter headers."""
    set_clock(clock)
    prod = create_product(name="Dia Shoe", brand="Apex", category="DIABETIC",
                          base_price_cents=price, medicare_allowable_cents=allowable,
                          hcpcs_code=hcpcs)
    inv = create_inventory(prod["id"], lot_number="LM")
    cust = create_customer(full_name="Med Cust", date_of_birth=dob, medicare_beneficiary_id=mbi)
    fitter = create_fitter(full_name="Med Fit")
    fh = make_fitter_headers(fitter["id"])
    cert = create_certification(cust["id"], cust["version"],
                                statement_date=statement_date, in_person_visit_date=visit_date)
    sale = open_sale(cust["id"], fitter["id"], fh)
    add_line(sale["id"], inv["id"], fh)
    sale = fulfill_sale(sale["id"], fh)
    return {"product": prod, "inventory": inv, "customer": cust, "fitter": fitter,
            "fitter_headers": fh, "certification": cert, "sale": sale}


def create_draft_claim(ctx, *, hcpcs="A5500", billed=30000, sale_id=None, certification_id=None):
    payload = {"customer_id": ctx["customer"]["id"],
               "sale_id": sale_id or ctx["sale"]["id"],
               "certification_id": certification_id or ctx["certification"]["id"],
               "hcpcs_code": hcpcs, "billed_amount_cents": billed}
    return get_success_data(api.create_claim(payload, BS))


def submit_claim(claim_id):
    return get_success_data(api.submit_claim(claim_id, BS))


def adjudicate_claim(claim_id, decision):
    return get_success_data(api.adjudicate_claim(claim_id, {"payer_decision": decision}, BS))


def resubmit_claim(claim_id):
    return get_success_data(api.resubmit_claim(claim_id, BS))


def setup_paid_claim(*, price=32000, allowable=30000, hcpcs="A5500", billed=32000,
                     dob="1943-03-03", mbi="7MN0ZM1SQ39"):
    """Full lifecycle through a PAID claim. Returns (ctx, claim)."""
    ctx = setup_fulfilled_medicare_sale(price=price, allowable=allowable, hcpcs=hcpcs,
                                        dob=dob, mbi=mbi)
    claim = create_draft_claim(ctx, hcpcs=hcpcs, billed=billed)
    submit_claim(claim["id"])
    claim = adjudicate_claim(claim["id"], "PAID")
    return ctx, claim


def add_fulfilled_sale(ctx, *, inventory=None, hcpcs_item=None):
    """Open + line + fulfill another sale for the same customer/fitter/inventory of ctx.
    Returns the fulfilled sale."""
    fh = ctx["fitter_headers"]
    inv_id = (inventory or ctx["inventory"])["id"]
    sale = open_sale(ctx["customer"]["id"], ctx["fitter"]["id"], fh)
    add_line(sale["id"], inv_id, fh)
    return fulfill_sale(sale["id"], fh)


def setup_paid_then_superseded_second_claim(*, mbi="4HJ7WH8PN06", dob="1946-04-04"):
    """One PAID A5500 claim already exists (pairs_ytd=1) using cert1; cert2 then
    supersedes cert1; a second fulfilled sale carries a DRAFT claim2 that still cites the
    now-SUPERSEDED cert1. Submitting claim2 violates BOTH the certification-complete
    check and the annual pair limit. Returns a context dict with claim2."""
    set_clock()
    prod = create_product(name="Dia Prec", brand="Apex", category="DIABETIC",
                          base_price_cents=30000, medicare_allowable_cents=30000, hcpcs_code="A5500")
    inv = create_inventory(prod["id"], lot_number="LP", quantity_on_hand=5)
    cust = create_customer(full_name="Prec Cust", date_of_birth=dob, medicare_beneficiary_id=mbi)
    fitter = create_fitter(full_name="Prec Fit")
    fh = make_fitter_headers(fitter["id"])
    cert1 = create_certification(cust["id"], cust["version"],
                                 statement_date="2026-06-01", in_person_visit_date="2026-05-20")
    ctx = {"customer": cust, "fitter": fitter, "fitter_headers": fh, "inventory": inv,
           "certification": cert1, "product": prod}
    sale1 = add_fulfilled_sale(ctx)
    claim1 = create_draft_claim(ctx, hcpcs="A5500", billed=30000, sale_id=sale1["id"],
                                certification_id=cert1["id"])
    submit_claim(claim1["id"])
    adjudicate_claim(claim1["id"], "PAID")
    cust_v1 = get_customer(cust["id"], BS)["version"]
    cert2 = create_certification(cust["id"], cust_v1,
                                 statement_date="2026-06-25", in_person_visit_date="2026-06-20")
    sale2 = add_fulfilled_sale(ctx)
    claim2 = create_draft_claim(ctx, hcpcs="A5500", billed=30000, sale_id=sale2["id"],
                                certification_id=cert1["id"])
    ctx["cert1"] = cert1
    ctx["cert2"] = cert2
    ctx["claim2"] = claim2
    return ctx


def setup_customer_with_superseded_cert(*, mbi="6KL9YK0RP28", dob="1949-09-09"):
    """A5500 diabetic product + stock, adult Medicare customer, and TWO certifications
    where cert2 has superseded cert1 (cert1 -> SUPERSEDED, cert2 -> COMPLETE). No prior
    PAID claim, so only the certification-state dependency can block a submit that cites
    cert1. Returns a context dict with cert1 and cert2."""
    set_clock()
    prod = create_product(name="Dia Cross", brand="Apex", category="DIABETIC",
                          base_price_cents=30000, medicare_allowable_cents=30000, hcpcs_code="A5500")
    inv = create_inventory(prod["id"], lot_number="LS", quantity_on_hand=5)
    cust = create_customer(full_name="Cert Cust", date_of_birth=dob, medicare_beneficiary_id=mbi)
    fitter = create_fitter(full_name="Cert Fit")
    fh = make_fitter_headers(fitter["id"])
    cert1 = create_certification(cust["id"], cust["version"],
                                 statement_date="2026-06-01", in_person_visit_date="2026-05-15")
    cust_v1 = get_customer(cust["id"], BS)["version"]
    cert2 = create_certification(cust["id"], cust_v1,
                                 statement_date="2026-06-20", in_person_visit_date="2026-06-10")
    return {"product": prod, "inventory": inv, "customer": cust, "fitter": fitter,
            "fitter_headers": fh, "cert1": cert1, "cert2": cert2}


# --------------------------- composites: Sales / Loyalty ---------------------------
def setup_two_line_sale(*, priceA, priceB, invA_on_hand=5, invB_on_hand=5,
                        dob="1960-03-03", categoryA="THERAPEUTIC", categoryB="INSERT",
                        fulfill=True, clock="2026-07-01T00:00:00Z"):
    """BRONZE customer, two-line sale (line A price priceA, line B price priceB).
    Returns a context dict; when fulfill=True the returned sale is FULFILLED."""
    set_clock(clock)
    prodA = create_product(name="Prod A", brand="X", category=categoryA, base_price_cents=priceA)
    prodB = create_product(name="Prod B", brand="X", category=categoryB, base_price_cents=priceB)
    invA = create_inventory(prodA["id"], lot_number="LA", quantity_on_hand=invA_on_hand)
    invB = create_inventory(prodB["id"], lot_number="LB", quantity_on_hand=invB_on_hand)
    cust = create_customer(full_name="Two Line", date_of_birth=dob)
    fitter = create_fitter(full_name="TL Fit")
    fh = make_fitter_headers(fitter["id"])
    sale = open_sale(cust["id"], fitter["id"], fh)
    lineA = add_line(sale["id"], invA["id"], fh)
    lineB = add_line(sale["id"], invB["id"], fh)
    if fulfill:
        sale = fulfill_sale(sale["id"], fh)
    return {"productA": prodA, "productB": prodB, "invA": invA, "invB": invB,
            "customer": cust, "fitter": fitter, "fitter_headers": fh,
            "sale": sale, "lineA": lineA, "lineB": lineB}


def setup_one_line_sale(*, price=8000, on_hand=5, dob="1970-01-01", fulfill=False,
                        category="REGULAR", clock="2026-07-01T00:00:00Z", line_qty=1):
    """Single-line sale (PENDING/UNPAID by default). Returns a context dict."""
    set_clock(clock)
    prod = create_product(name="One Line", brand="X", category=category, base_price_cents=price)
    inv = create_inventory(prod["id"], lot_number="LO", quantity_on_hand=on_hand)
    cust = create_customer(full_name="One Cust", date_of_birth=dob)
    fitter = create_fitter(full_name="One Fit")
    fh = make_fitter_headers(fitter["id"])
    sale = open_sale(cust["id"], fitter["id"], fh)
    line = add_line(sale["id"], inv["id"], fh, quantity=line_qty)
    if fulfill:
        sale = fulfill_sale(sale["id"], fh)
    return {"product": prod, "inventory": inv, "customer": cust, "fitter": fitter,
            "fitter_headers": fh, "sale": sale, "line": line}


# --------------------------- composites: Returns ---------------------------
def create_and_approve_return(sale_id, sale_line_id, *, return_type="RETURN"):
    ret = get_success_data(api.create_return(
        {"sale_id": sale_id, "sale_line_id": sale_line_id, "return_type": return_type}, SM))
    ret = get_success_data(api.approve_return(ret["id"], SM))
    return ret


def refund_return(return_id):
    return get_success_data(api.refund_return(return_id, SM))


# --------------------------- composites: Recall / Special order ---------------------------
def setup_placed_special_order(*, deposit=5000, dob="1962-06-06", clock="2026-07-01T00:00:00Z",
                               with_stock=True):
    """Product (optionally with AVAILABLE stock, lot L1), customer, and an ORDERED
    special order with the given deposit. Returns a context dict."""
    set_clock(clock)
    prod = create_product(name="SO Prod", brand="Aetrex", category="THERAPEUTIC", base_price_cents=8000)
    inv = create_inventory(prod["id"], lot_number="L1", quantity_on_hand=3) if with_stock else None
    cust = create_customer(full_name="SO Cust", date_of_birth=dob)
    so = get_success_data(api.create_special_order(
        {"customer_id": cust["id"], "product_id": prod["id"], "requested_size": 9.0,
         "requested_width": "D", "deposit_cents": deposit}, SM))
    so = get_success_data(api.place_special_order(so["id"], SM))
    return {"product": prod, "inventory": inv, "customer": cust, "special_order": so}


def create_and_issue_recall(product_id, **over):
    payload = {"product_id": product_id, "reason": "recall"}
    payload.update(over)
    recall = get_success_data(api.create_recall(payload, SM))
    recall = get_success_data(api.issue_recall(recall["id"], SM))
    return recall


# --------------------------- composites: Appointments ---------------------------
def setup_fitter_and_customer(*, clock="2026-07-01T00:00:00Z"):
    set_clock(clock)
    cust = create_customer(full_name="Appt Cust", date_of_birth="1980-02-02")
    fitter = create_fitter(full_name="Appt Fit")
    return {"customer": cust, "fitter": fitter, "fitter_headers": make_fitter_headers(fitter["id"])}


def book_appointment(customer_id, fitter_id, fitter_headers, **over):
    payload = {"customer_id": customer_id, "fitter_id": fitter_id,
               "appointment_type": "FITTING",
               "start_time": "2026-07-02T10:00:00Z", "end_time": "2026-07-02T10:30:00Z"}
    payload.update(over)
    return get_success_data(api.create_appointment(payload, fitter_headers))
