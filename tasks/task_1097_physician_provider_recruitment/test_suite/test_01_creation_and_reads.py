"""Creation, defaults, reads, and FK-reverse listings (corner breadth)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_account_manager, create_client_payload,
    make_account_manager_headers, make_platform_admin_headers,
    setup_open_opening, create_candidate_entity, create_application_entity,
    setup_offer_extended, setup_placement_pre_start,
)

ADMIN = make_platform_admin_headers()


def test_create_client_returns_201_with_defaults(api):
    """PRD §3.1: "A client starts ACTIVE with net_placement_fee_cents at 0".
    PRD §2.4: "When a resource is created it is returned with HTTP 201".

    Design: Corner/entities/client_create_returns_201_with_fields
    """
    am = create_account_manager()
    resp = api.create_client(
        create_client_payload(am["id"]), make_account_manager_headers(am["id"])
    )
    data = validate_success(resp, 201)
    assert data["net_placement_fee_cents"] == 0
    assert data["status"] == "ACTIVE"


def test_get_offer_unknown_id_not_found(api):
    """PRD §2.9: "a missing resource anywhere along the path — or a missing body
    foreign key — yields ERR_NOT_FOUND (HTTP 404)".

    Design: Corner/entities/get_offer_not_found
    """
    resp = api.get_offer(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_client_missing_guarantee_days_rejected(api):
    """PRD §2.10: "Request well-formedness — all required input fields present and
    correctly typed on mutating endpoints, else ERR_VALIDATION."
    PRD §3.1: "guarantee_days, the length in days of the placement guarantee window,
    which must be at least 1."

    Design: Corner/entities/create_client_missing_required_field
    """
    am = create_account_manager()
    payload = create_client_payload(am["id"])
    del payload["guarantee_days"]
    resp = api.create_client(payload, make_account_manager_headers(am["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_offer_sign_on_bonus_defaults_zero(api):
    """PRD §3.5: "it also accepts an optional sign_on_bonus_cents (defaulting to 0)
    ... and its offered_first_year_comp_cents is set to the sum of base_salary_cents
    and sign_on_bonus_cents."

    Design: Corner/entities/offer_sign_on_bonus_defaults_zero
    """
    # Default offer factory supplies base 24,000,000 and no sign_on_bonus_cents.
    ctx = setup_offer_extended(cand_overrides={"desired_comp_cents": 24_000_000})
    offer = ctx["offer"]
    assert offer["sign_on_bonus_cents"] == 0
    assert offer["offered_first_year_comp_cents"] == 24_000_000


def test_application_initial_state_sourced(api):
    """PRD §3.3: "the application's recruiter_id is copied from the candidate's
    owning recruiter at creation, its stage starts at SOURCED, and its match_score
    starts at 0."

    Design: Corner/entities/application_initial_state_sourced
    """
    ctx = setup_open_opening()
    cand = create_candidate_entity(ctx["rec_id"])
    app = create_application_entity(ctx["rec_id"], cand["id"], ctx["opening_id"])
    assert app["stage"] == "SOURCED"


def test_placements_filterable_by_client_id(api):
    """PRD §3.6: "Placements may be read individually and listed, filtered by
    opening_id, client_id, candidate_id, application_id, and offer_id."

    Design: Corner/endpoints/fk_reverse_placements_by_client
    """
    ctx = setup_placement_pre_start()
    resp = api.list_placements(
        make_account_manager_headers(ctx["am_id"]), params={"client_id": ctx["client_id"]}
    )
    data, meta = validate_paginated(resp)
    assert len(data) >= 1
    assert data[0]["client_id"] == ctx["client_id"]
