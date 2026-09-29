"""Who may call what: role denials, header failures, self-scope and peer reads.

Four exclusive operations closed to the wrong desk, a read closed to the
laboratory, the two header failures that land on 401 rather than 403, the
entity-backed supplier confined to its own record, one campaign read shared by
three peer roles, and the segregation-of-duties comparison on `X-User-ID`.
"""

from prd_bench_local_runner.testing import (
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ROLE_NOT_PERMITTED,
    ERR_RUN_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SUPPLIER_SCOPE_VIOLATION,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import assert_fields_null, assert_mass
from test_helpers.test_users import (
    ANALYST_HEADERS,
    OFFICER_A_HEADERS,
    OFFICER_A_USER_ID,
    OFFICER_B_HEADERS,
    OFFICER_B_USER_ID,
    OPERATOR_HEADERS,
    TRADER_HEADERS,
    VERIFIER_HEADERS,
    make_supplier_headers,
)
from test_helpers.types import (
    BLOCK_DRAFT,
    BLOCK_INTERNAL_SIGNED_OFF,
    CERT_DECISION_CERTIFY,
    DOC_CHAIN_OF_CUSTODY,
    FEEDSTOCK_TALLOW,
    FEEDSTOCK_UCO,
    ROLE_PLANT_OPERATOR,
    RUN_PLANNED,
)

FAKE_RUN_ID = "11111111-1111-1111-1111-111111111111"
FAKE_LOT_ID = "22222222-2222-2222-2222-222222222222"
FAKE_SUPPLIER_ID = "33333333-3333-3333-3333-333333333333"
FAKE_BATCH_ID = "44444444-4444-4444-4444-444444444444"
FAKE_PATHWAY_ID = "55555555-5555-5555-5555-555555555555"
FAKE_DECIDED_BATCH_ID = "66666666-6666-6666-6666-666666666666"


def test_the_plant_floor_cannot_compose_the_feedstock_charge(api):
    """PRD §2.1: "A `PlantOperator` may read units, campaigns, lots, batches, contracts and
    nominations, but may not create suppliers or feedstock lots, may not record quality
    dispositions, may not allocate feedstock to a campaign, may not reconcile a campaign, and may
    not touch pathways, credit blocks or hedge positions."
    PRD §2.1: "When the headers are well formed but the named role is not listed as an authorized
    role for the endpoint being called, the refusal is `ERR_ROLE_NOT_PERMITTED` with HTTP 403."
    PRD §2.7: "When a request violates two rules at once, the client always sees the error
    belonging to the earlier rung."

    Design: Corner/rbac/plant_operator_cannot_post_feedstock_allocations
    """
    response = api.create_allocation(
        FAKE_RUN_ID, f.allocation_payload(FAKE_LOT_ID, 100.000, 1), OPERATOR_HEADERS
    )

    validate_error(response, ERR_ROLE_NOT_PERMITTED, 403)
    assert response.json()["data"]["error_id"] != ERR_RUN_NOT_FOUND, (
        "the role rung sits above path existence, so the fabricated campaign is never resolved"
    )


def test_the_laboratory_cannot_book_a_delivered_lot(api):
    """PRD §2.1: "It may read lots, quality tests and suppliers, but may not create lots or
    suppliers, may not allocate feedstock, and may not touch certification, pathways, credits or
    hedging."
    PRD §2.1: "A `FeedstockTrader` is the buying desk: it onboards suppliers, uploads traceability
    evidence on their behalf, books delivered lots, allocates and releases feedstock against
    campaigns, buys hydrogen supply contracts, and manages the hedge book."

    Design: Corner/rbac/quality_analyst_cannot_create_feedstock_lots
    """
    supplier = fx.make_supplier(api, feedstock_types=[FEEDSTOCK_UCO])

    validate_error(
        api.create_feedstock_lot(
            f.feedstock_lot_payload(supplier["id"], mass_mt=100.000), ANALYST_HEADERS
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    _, meta = validate_paginated(
        api.list_feedstock_lots(TRADER_HEADERS, {"supplier_id": supplier["id"]})
    )
    assert meta["total_count"] == 0, f"no lot may survive the refusal, got {meta['total_count']}"

    validate_error(
        api.create_feedstock_lot(
            f.feedstock_lot_payload(FAKE_SUPPLIER_ID, mass_mt=100.000), ANALYST_HEADERS
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )


def test_the_verifier_cannot_mint_the_credit_block_it_will_judge(api):
    """PRD §2.1: "It creates no business objects of its own and is read-only everywhere else; in
    particular it may not create credit blocks, sign them off internally, retire credits, create
    or submit pathway registrations, or touch suppliers, lots, campaigns or hedge positions."
    PRD §3.8: "Once product has shipped, a `ComplianceOfficer` mints a credit block citing the
    finished-fuel batch through `batch_id` and the registered pathway through `pathway_id`."

    Design: Corner/rbac/independent_verifier_cannot_create_credit_blocks
    """
    validate_error(
        api.create_credit_block(
            f.credit_block_payload(FAKE_BATCH_ID, FAKE_PATHWAY_ID), VERIFIER_HEADERS
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    _, meta = validate_paginated(api.list_credit_blocks(OFFICER_A_HEADERS))
    assert meta["total_count"] == 0, f"got {meta['total_count']}"


def test_the_officer_files_the_certification_but_cannot_decide_it(api):
    """PRD §3.7: "The decision belongs to the `IndependentVerifier`, never to the officer who filed
    the request."
    PRD §2.1: "It may not make certification decisions, may not start or decide a pathway review,
    and may not make credit verification decisions — all four belong to the verifier."

    Design: Corner/rbac/compliance_officer_cannot_record_certification_decisions
    """
    validate_error(
        api.decide_certification(
            FAKE_DECIDED_BATCH_ID,
            f.certification_decision_payload(CERT_DECISION_CERTIFY),
            OFFICER_A_HEADERS,
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )


def test_the_laboratory_cannot_even_read_the_campaign_list(api):
    """PRD §2.1: "A `QualityAnalyst` is the laboratory: it draws samples, records free fatty acid,
    moisture, insolubles and phosphorus figures, orders pretreatment, and accepts lots for
    charging."
    PRD §2.1: "Every request must carry two headers. `X-User-ID` identifies the acting principal
    and `X-User-Role` names the role that principal is acting in."

    Design: Corner/rbac/quality_analyst_cannot_list_processing_runs
    """
    validate_error(
        api.list_processing_runs(ANALYST_HEADERS, {"limit": 10, "offset": 0}),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    _, meta = validate_paginated(
        api.list_processing_runs(OPERATOR_HEADERS, {"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0, f"the refused read is not a write, got {meta['total_count']}"


def test_a_missing_identity_and_an_invented_role_are_both_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` holds anything other than one of
    the six role names defined below, the request is refused with `ERR_UNAUTHENTICATED` and HTTP
    401 — before any path segment is resolved and before the body is inspected."
    PRD §2.7: "1. Identity headers present and the role recognized — `ERR_UNAUTHENTICATED`, 401."

    Design: Corner/rbac/missing_x_user_id_header_returns_unauthenticated
    """
    validate_error(
        api.list_processing_runs({"X-User-Role": ROLE_PLANT_OPERATOR}, {"limit": 10, "offset": 0}),
        ERR_UNAUTHENTICATED,
        401,
    )

    validate_error(
        api.list_processing_runs(build_user_headers("operator-1", "Auditor")),
        ERR_UNAUTHENTICATED,
        401,
    )

    validate_error(api.list_processing_runs({}), ERR_UNAUTHENTICATED, 401)

    rows, meta = validate_paginated(
        api.list_processing_runs(OPERATOR_HEADERS, {"limit": 10, "offset": 0})
    )
    assert rows == [], f"the three refusals wrote nothing, got {rows}"
    assert meta["total_count"] == 0, f"got {meta['total_count']}"


def test_a_supplier_is_confined_to_its_own_record_and_its_own_evidence(api):
    """PRD §2.1: "Concretely, a `Supplier` caller uploading or listing traceability documents, or
    reading a supplier record, must have an `X-User-ID` equal to the supplier id named in the path;
    a mismatch is refused with `ERR_SUPPLIER_SCOPE_VIOLATION` and HTTP 403, and that refusal is
    evaluated ahead of existence checks on nested resources."
    PRD §2.1: "A `Supplier` is an external feedstock supplier authenticated as its own supplier
    record. It may upload its own traceability documents and read its own record and its own
    documents, and nothing else."

    Design: Corner/rbac/supplier_cannot_read_another_suppliers_documents
    """
    sup_a = fx.make_supplier(api, feedstock_types=[FEEDSTOCK_UCO])
    sup_b = fx.make_supplier(
        api,
        legal_name="Prairie Tallow Partners",
        country_code="CA",
        feedstock_types=[FEEDSTOCK_TALLOW],
    )
    own_doc = fx.add_document(api, sup_a["id"])
    fx.add_document(api, sup_b["id"])

    headers_a = make_supplier_headers(sup_a["id"])

    validate_error(
        api.list_traceability_documents(sup_b["id"], headers_a),
        ERR_SUPPLIER_SCOPE_VIOLATION,
        403,
    )
    validate_error(api.get_supplier(sup_b["id"], headers_a), ERR_SUPPLIER_SCOPE_VIOLATION, 403)
    validate_error(
        api.create_traceability_document(
            sup_b["id"], f.traceability_document_payload(doc_type=DOC_CHAIN_OF_CUSTODY), headers_a
        ),
        ERR_SUPPLIER_SCOPE_VIOLATION,
        403,
    )

    mine, mine_meta = validate_paginated(
        api.list_traceability_documents(sup_a["id"], headers_a, {"limit": 10, "offset": 0})
    )
    assert mine_meta["total_count"] == 1, f"got {mine_meta['total_count']}"
    assert mine[0]["id"] == own_doc["id"]

    self_read = validate_success(api.get_supplier(sup_a["id"], headers_a))
    assert self_read["id"] == sup_a["id"]
    assert self_read["dd_document_type_count"] == 1, f"got {self_read['dd_document_type_count']}"

    _, other_meta = validate_paginated(
        api.list_traceability_documents(sup_b["id"], TRADER_HEADERS)
    )
    assert other_meta["total_count"] == 1, (
        f"the refused upload left no document behind, got {other_meta['total_count']}"
    )


def test_the_three_peer_roles_read_one_campaign_identically(api):
    """PRD §3.5: "Its `run_days` is the whole number of days between `window_start` and
    `window_end`."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increases by
    exactly one on every mutation of that row, including mutations caused by a cascade rather than
    by a direct request against the row."

    Design: Corner/rbac/shared_read_of_processing_runs_works_for_three_peer_roles
    """
    plant = fx.commissioned_unit(api)
    run = fx.make_run(
        api, plant["unit"]["id"], plant["charge"]["id"], target_saf_share_pct=0.00
    )

    bodies = [
        validate_success(api.get_processing_run(run["id"], headers))
        for headers in (OPERATOR_HEADERS, OFFICER_A_HEADERS, TRADER_HEADERS)
    ]

    for body in bodies:
        assert body["id"] == run["id"]
        assert body["status"] == RUN_PLANNED, f"got {body['status']}"
        assert body["run_days"] == 5, f"got {body['run_days']}"
        assert_mass(body["reserved_mass_mt"], 0.000, "reserved_mass_mt")
        assert_mass(body["consumed_mass_mt"], 0.000, "consumed_mass_mt")
        assert_fields_null(body, "blend_ci_gco2e_per_mj", "required_h2_kg_per_day")
        assert body["version"] == 1, f"a read mutates nothing, got {body['version']}"

    assert bodies[0] == bodies[1] == bodies[2], "the three roles must see the same representation"

    for headers in (OPERATOR_HEADERS, OFFICER_A_HEADERS, TRADER_HEADERS):
        rows, meta = validate_paginated(
            api.list_processing_runs(
                headers,
                {"unit_id": plant["unit"]["id"], "status": RUN_PLANNED, "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1, f"got {meta['total_count']}"
        assert meta["has_more"] is False
        assert rows[0]["version"] == 1, f"got {rows[0]['version']}"


def test_the_officer_who_registered_the_pathway_cannot_sign_its_block(api):
    """PRD §3.8: "The acting `X-User-ID` must differ from the cited pathway's
    `registered_by_user_id`; when the same officer who registered the pathway attempts to sign off
    a block claimed under it, the request is refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403."
    PRD §2.1: "The server does record it in two places where the business rules demand an audit
    anchor — as `registered_by_user_id` on a pathway registration when a `ComplianceOfficer`
    creates it, and as `signed_off_by_user_id` on a credit block when a `ComplianceOfficer`
    internally signs it off — and the segregation-of-duties rule compares those two recorded values
    to each other, but neither is resolved against a user table."

    Design: Corner/rbac/compliance_officer_cannot_sign_off_a_block_on_a_pathway_it_registered
    """
    ctx = fx.credit_ready_campaign(
        api, measured_rd_mt=320.123, measured_saf_mt=0.000, target_saf_share_pct=0.00
    )
    assert ctx["pathway"]["registered_by_user_id"] == OFFICER_A_USER_ID, (
        f"got {ctx['pathway']['registered_by_user_id']}"
    )

    block = fx.make_credit_block(api, ctx["batch"]["id"], ctx["pathway"]["id"])
    assert block["provisional_credits_mtco2e"] == 604.007, (
        f"got {block['provisional_credits_mtco2e']}"
    )

    validate_error(
        api.internal_signoff(block["id"], OFFICER_A_HEADERS), ERR_SEGREGATION_OF_DUTIES, 403
    )

    refused = validate_success(api.get_credit_block(block["id"], OFFICER_A_HEADERS))
    assert refused["status"] == BLOCK_DRAFT, f"got {refused['status']}"
    assert_fields_null(refused, "signed_off_by_user_id")
    assert refused["version"] == block["version"], f"got {refused['version']}"

    signed = validate_success(api.internal_signoff(block["id"], OFFICER_B_HEADERS))
    assert signed["status"] == BLOCK_INTERNAL_SIGNED_OFF, f"got {signed['status']}"
    assert signed["signed_off_by_user_id"] == OFFICER_B_USER_ID, (
        f"got {signed['signed_off_by_user_id']}"
    )
    assert signed["version"] == block["version"] + 1, f"got {signed['version']}"
    assert signed["provisional_credits_mtco2e"] == 604.007, (
        f"got {signed['provisional_credits_mtco2e']}"
    )
