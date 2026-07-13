"""Corner: entities — creation defaults, not-found, required fields, computed fields."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    setup_actor_trio,
    setup_published_campaign,
    make_donation,
    create_campaign_payload,
    make_organizer_headers,
)


def test_campaign_create_returns_all_fields(api):
    """PRD §3.2: "A new campaign is born in lifecycle status DRAFT with payout posture OPEN
    and every money field at zero; its organizer_id is taken from the creator's X-User-ID,
    and the same creating organizer is simultaneously recorded as the campaign's initial team
    member with the owner role."
    PRD §3.2: "A campaign carries a public tax_disclosure string, TAX_DEDUCTIBLE when
    is_charity is true and NOT_TAX_DEDUCTIBLE otherwise, surfaced so donors are never misled
    about deductibility."

    Design: Corner/entities/campaign_create_returns_all_fields
    """
    org, ben, _ = setup_actor_trio(api)
    data = validate_success(
        api.create_campaign(create_campaign_payload(ben["id"]), make_organizer_headers(org["id"])),
        201,
    )
    assert data["lifecycle_status"] == "DRAFT"
    assert data["payout_posture"] == "OPEN"
    assert data["raised_cents"] == 0
    assert data["tax_disclosure"] == "NOT_TAX_DEDUCTIBLE"


def test_get_campaign_not_found(api, guest_headers):
    """PRD §2.10: "Every referenced resource — whether named in the URL path or in the
    request body — must exist; a missing resource yields ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_campaign_not_found
    """
    resp = api.get_campaign(NON_EXISTENT_UUID, guest_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_campaign_missing_goal_returns_invalid_request(api):
    """PRD §2.10: "Request-body well-formedness — required fields present, enums valid,
    integer and datetime types correct (ERR_INVALID_REQUEST, 400)."

    Design: Corner/entities/campaign_missing_goal_returns_invalid_request
    """
    org, ben, _ = setup_actor_trio(api)
    payload = {"beneficiary_id": ben["id"], "title": "T", "story": "S", "category": "MEDICAL"}
    resp = api.create_campaign(payload, make_organizer_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_donation_tax_receipt_status_deductible_for_charity(api):
    """PRD §3.4: "Its tax_receipt_status is computed from the parent campaign: DEDUCTIBLE
    when the campaign's is_charity is true, NON_DEDUCTIBLE otherwise."

    Design: Corner/entities/donation_tax_receipt_status_deductible_for_charity
    """
    b = setup_published_campaign(api, is_charity=True)
    don = make_donation(api, b["campaign"]["id"], b["donor"]["id"], 10000)
    assert don["tax_receipt_status"] == "DEDUCTIBLE", (
        f"is_charity true -> DEDUCTIBLE, got {don['tax_receipt_status']}"
    )


def test_donation_tip_defaults_zero(api):
    """PRD §3.4: "an optional tip_cents platform tip that goes to the platform rather than
    the campaign (defaulting to zero when omitted)"
    PRD §3.4: "Then compute total_charged_cents — the amount the donor's card is actually
    charged — by taking the subtotal plus a fixed 30-cent-per-transaction component, dividing
    that by one minus the processing rate of 0.029 (that is, dividing by 0.971), and rounding
    the quotient up to the next whole cent."

    Design: Corner/entities/donation_tip_defaults_zero
    """
    b = setup_published_campaign(api)
    don = make_donation(api, b["campaign"]["id"], b["donor"]["id"], 10000)  # tip omitted
    assert don["tip_cents"] == 0
    assert don["total_charged_cents"] == 10330, (
        f"ceil((10000+30)/0.971)=10330, got {don['total_charged_cents']}"
    )
    assert don["net_to_campaign_cents"] == 10000
