"""Working a lead: contact ownership, quote creation, the revision loop, and
the lead's two parallel state dimensions."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_customer_headers, make_pro_headers,
    create_category, create_customer, create_verified_pro, create_request,
    distribute_once, lead_for, reset_clock,
    create_quote_payload, create_dispute_payload,
    setup_distributed_lead, setup_contacted_lead, setup_quoted_lead,
)

ADMIN = TEST_USERS["admin_headers"]


def test_quote_revision_round_trip_returns_to_sent(api):
    """PRD 3.4: "A customer who owns a SENT quote may request a revision, moving
    it to REVISION_REQUESTED and incrementing revision_count."
    PRD 3.4: "The owning pro then re-sends a revised quote, supplying a new
    amount_cents; this moves the quote from REVISION_REQUESTED back to SENT and
    updates the stored amount_cents."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_sent_revision_sent
    """
    ctx = setup_quoted_lead(api=api)
    q = ctx["quote"]
    api.request_revision(q["id"], make_customer_headers(ctx["customer"]["id"]))
    updated = validate_success(
        api.send_quote(q["id"], {"amount_cents": 9000}, make_pro_headers(ctx["pro"]["id"]))
    )
    assert updated["status"] == "SENT"
    assert updated["revision_count"] == 1
    assert updated["amount_cents"] == 9000


def test_request_revision_moves_quote_to_revision_requested(api):
    """PRD 3.4: "A customer who owns a SENT quote may request a revision, moving
    it to REVISION_REQUESTED and incrementing revision_count."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_sent_revision_sent
    """
    ctx = setup_quoted_lead(api=api)
    q = ctx["quote"]
    updated = validate_success(
        api.request_revision(q["id"], make_customer_headers(ctx["customer"]["id"]))
    )
    assert updated["status"] == "REVISION_REQUESTED"
    assert updated["revision_count"] == 1


def test_quote_on_uncontacted_lead_rejected(api):
    """PRD 3.4: "Creating the quote copies the lead's pro onto the quote as
    pro_id and the lead's requesting customer as customer_id, sets the quote's
    status to SENT with a revision_count of zero, and cascades the lead's
    contact_status from CONTACTED to QUOTED."
    PRD 2.9: "State — the target resource is in a state that permits the
    requested transition, else ERR_INVALID_STATE (409)."

    Design: Difficulty/cross_entity_state_dependency/quote_send_requires_lead_contacted
    """
    ctx = setup_distributed_lead(api=api)
    lead = ctx["lead"]
    resp = api.create_quote(create_quote_payload(lead["id"], amount_cents=10000),
                            make_pro_headers(ctx["pro"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_lead(lead["id"], ADMIN))
    assert after["contact_status"] == "DISTRIBUTED"


def test_quote_on_contacted_lead_succeeds_and_cascades_to_quoted(api):
    """PRD 3.4: "Creating the quote copies the lead's pro onto the quote as
    pro_id and the lead's requesting customer as customer_id, sets the quote's
    status to SENT with a revision_count of zero, and cascades the lead's
    contact_status from CONTACTED to QUOTED."

    Design: Difficulty/cross_entity_state_dependency/quote_send_requires_lead_contacted
    """
    ctx = setup_contacted_lead(api=api)
    lead = ctx["lead"]
    quote = validate_success(
        api.create_quote(create_quote_payload(lead["id"], amount_cents=10000),
                         make_pro_headers(ctx["pro"]["id"])),
        expected_status=201,
    )
    assert quote["status"] == "SENT"
    assert quote["revision_count"] == 0
    after = get_success_data(api.get_lead(lead["id"], ADMIN))
    assert after["contact_status"] == "QUOTED"


def test_send_on_already_sent_quote_returns_invalid_state(api):
    """PRD 3.4: "The owning pro then re-sends a revised quote, supplying a new
    amount_cents; this moves the quote from REVISION_REQUESTED back to SENT and
    updates the stored amount_cents."
    PRD 2.9: "State — the target resource is in a state that permits the
    requested transition, else ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/quote_send_from_sent_returns_invalid_state
    """
    ctx = setup_quoted_lead(api=api)
    resp = api.send_quote(ctx["quote"]["id"], {"amount_cents": 9000},
                          make_pro_headers(ctx["pro"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def _contacted_then_disputed(api):
    ctx = setup_distributed_lead(api=api)
    pid = ctx["pro"]["id"]
    get_success_data(api.contact_lead(ctx["lead"]["id"], make_pro_headers(pid)))
    get_success_data(api.create_dispute(create_dispute_payload(ctx["lead"]["id"], reason="WRONG_NUMBER"),
                                        make_pro_headers(pid)))
    ctx["lead"] = get_success_data(api.get_lead(ctx["lead"]["id"], ADMIN))
    return ctx


def test_contact_dimension_advances_independently_of_billing(api):
    """PRD 3.4: "The pro who owns a lead marks it contacted, advancing
    contact_status from DISTRIBUTED to CONTACTED; this is permitted only to the
    owning pro and only from DISTRIBUTED."
    PRD 3.4: "A lead carries two independent state dimensions on the same row: a
    contact_status tracking conversation and conversion, and a billing_status
    tracking money."

    Design: Difficulty/non_linear_state_machine/lead_parallel_contact_and_billing_dimensions_evolve_independently
    """
    ctx = _contacted_then_disputed(api)
    assert ctx["lead"]["contact_status"] == "CONTACTED"


def test_billing_dimension_advances_independently_of_contact(api):
    """PRD 3.7: "Raising the dispute records the pro as raised_by_pro_id, starts
    the dispute in status OPEN with refund_cents of zero and a null
    resolution_note, and cascades the lead's billing_status from CHARGED to DISPUTED."
    PRD 3.4: "A lead carries two independent state dimensions on the same row: a
    contact_status tracking conversation and conversion, and a billing_status
    tracking money."

    Design: Difficulty/non_linear_state_machine/lead_parallel_contact_and_billing_dimensions_evolve_independently
    """
    ctx = _contacted_then_disputed(api)
    assert ctx["lead"]["billing_status"] == "DISPUTED"


def test_pro_cannot_contact_another_pros_lead(api):
    """PRD 2.1: "When an entity-backed actor is authenticated and permitted for
    the operation as a class, but is not the owner of the specific targeted
    resource, the request is rejected with ERR_NOT_RESOURCE_OWNER."

    Design: Corner/rbac/pro_cannot_contact_another_pros_lead_returns_not_owner
    """
    reset_clock(api)
    cat = create_category(api, min_rating_to_receive_leads=0.0)
    cust = create_customer(api)
    pro_a = create_verified_pro(api, wallet=20000, category_ids=[cat["id"]], zip_codes=["94016"])
    # Pro B is a verified pro that does not serve the request zip, so the single
    # distribute deterministically grants the lead to Pro A.
    pro_b = create_verified_pro(api, wallet=20000, category_ids=[cat["id"]], zip_codes=["99999"])
    req = create_request(cust["id"], cat["id"], api=api, zip_code="94016")
    distribute_once(req["id"], req["version"], api=api)
    lead = lead_for(req["id"], pro_a["id"], api=api)
    resp = api.contact_lead(lead["id"], make_pro_headers(pro_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
