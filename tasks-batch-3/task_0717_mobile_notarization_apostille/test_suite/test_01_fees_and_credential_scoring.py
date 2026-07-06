"""Fee quoting, credential-trust scoring, and apostille fee calculations.

Covers the dual-variant fee/credential calculations, the min()-cap combinatorial
fee, the round-per-document loan aggregation, the credential-trust boundary, and
the apostille flat-fee branch.
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    create_fee_schedule_payload, create_account_payload, create_signer_payload,
    create_request_payload, create_document_payload, create_id_verification_payload,
    create_apostille_order_payload, create_loan_package_payload,
    create_ron_session_payload, create_journal_entry_payload,
    TEST_USERS, make_notary_headers,
    setup_world, setup_quoted_request, setup_completed_request, setup_loan_package,
    scrub_package, setup_submitted_apostille,
)

COORD = TEST_USERS["coordinator_headers"]
CLERK = TEST_USERS["apostille_clerk_headers"]
VIEWER = TEST_USERS["viewer_headers"]


# ─── Difficulty/dual_variant_calc/request_fee_estimate_vs_final_diverge ──────

def test_estimate_and_final_fee_diverge_on_same_request(api):
    """PRD §3.6: "the stamp count is the number of journal entries for the request
    whose `entry_status` is `COMPLETED` (voided entries are excluded), and the miles
    are `actual_travel_miles` — again treated as 0 when `delivery_mode` is `RON`."
    PRD §3.2: "For the estimate, the stamp count is `expected_stamp_count` and the
    miles are `estimated_travel_miles`".
    PRD §3.6: "Because the final inclusion set can differ from the declared figures,
    the final fee may diverge from the earlier estimate."

    Same MOBILE request: estimate uses 4 declared stamps + 10 declared miles ->
    4*1500 + 4000 + 10*100 = 11000. Final uses 2 COMPLETED acts + 18 actual miles ->
    2*1500 + 4000 + 18*100 = 8800.

    Design: Difficulty/dual_variant_calc/request_fee_estimate_vs_final_diverge
    """
    world = setup_world()
    request = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="GENERAL", delivery_mode="MOBILE",
                               expected_stamp_count=4, estimated_travel_miles=10),
        COORD))
    document = get_success_data(api.create_document(
        create_document_payload(request["id"], doc_type="AFFIDAVIT", signing_fee_cents=3000),
        COORD))
    quoted = get_success_data(api.quote_request(request["id"], COORD))
    assert quoted["estimate_fee_cents"] == 11000

    assigned = get_success_data(api.assign_request(
        request["id"],
        {"notary_id": world["notary"]["id"], "expected_request_version": quoted["version"]},
        COORD))
    nheaders = make_notary_headers(world["notary"]["id"])
    get_success_data(api.create_id_verification(
        create_id_verification_payload(request["id"], world["signer"]["id"],
                                       kba_score=80, credential_score=90, biometric_score=80),
        nheaders))
    get_success_data(api.create_ron_session(
        create_ron_session_payload(request["id"], "2026-03-02T10:00:00Z", "2026-03-02T11:00:00Z"),
        nheaders))
    get_success_data(api.start_session(request["id"], nheaders))
    get_success_data(api.create_journal_entry(
        create_journal_entry_payload(request["id"], document["id"], act_type="JURAT"), nheaders))
    get_success_data(api.create_journal_entry(
        create_journal_entry_payload(request["id"], document["id"], act_type="ACKNOWLEDGMENT"),
        nheaders))
    completed = get_success_data(api.complete_request(
        request["id"], {"actual_travel_miles": 18}, nheaders))

    assert completed["final_fee_cents"] == 8800
    assert completed["estimate_fee_cents"] == 11000
    assert completed["estimate_fee_cents"] != completed["final_fee_cents"]
    assert completed["status"] == "COMPLETED"


def test_final_fee_recomputed_from_actual_inputs(api):
    """PRD §3.6: "Completion accepts an optional `actual_travel_miles` figure and
    computes the reconciled final fee into `final_fee_cents`. The final fee uses the
    same arithmetic as the estimate and the same governing fee schedule, but with
    reconciled inputs".

    MOBILE, 1 COMPLETED act, 5 actual miles -> 1*1500 + 4000 + 5*100 = 6000.

    Design: Difficulty/dual_variant_calc/request_fee_estimate_vs_final_diverge
    """
    world, request, document, _ = setup_completed_request(
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "MOBILE",
                           "expected_stamp_count": 1, "estimated_travel_miles": 99},
        act_types=("JURAT",),
        complete_payload={"actual_travel_miles": 5})
    assert request["final_fee_cents"] == 6000


# ─── Difficulty/dual_variant_calc/credential_trust_standard_vs_enhanced_diverge

def test_same_scores_pass_standard_and_enhanced_with_different_scores(api):
    """PRD §3.3: "Under `STANDARD`, the weighted score is the KBA score times 0.5,
    plus the credential score times 0.3, plus the biometric score times 0.2, and the
    passing threshold is 70. Under `ENHANCED`, the weighted score is the KBA score
    times 0.3, plus the credential score times 0.4, plus the biometric score times
    0.3, and the passing threshold is 75."
    PRD §3.3: "The evaluation uses the `ENHANCED` variant when either the request's
    `doc_category` is `LOAN_SIGNING` or the governing fee schedule for the request's
    state has `enhanced_trust_required` set to true; otherwise it uses the `STANDARD`
    variant."

    kba=60, credential=95, biometric=75: STANDARD -> 0.5*60+0.3*95+0.2*75 = 73.50;
    ENHANCED -> 0.3*60+0.4*95+0.3*75 = 78.50.

    Design: Difficulty/dual_variant_calc/credential_trust_standard_vs_enhanced_diverge
    """
    world = setup_world()
    nheaders = make_notary_headers(world["notary"]["id"])
    req_std = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="GENERAL", delivery_mode="MOBILE",
                               expected_stamp_count=1), COORD))
    req_loan = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="LOAN_SIGNING", delivery_mode="MOBILE",
                               expected_stamp_count=1), COORD))

    idv_std = get_success_data(api.create_id_verification(
        create_id_verification_payload(req_std["id"], world["signer"]["id"],
                                       kba_score=60, credential_score=95, biometric_score=75),
        nheaders))
    idv_loan = get_success_data(api.create_id_verification(
        create_id_verification_payload(req_loan["id"], world["signer"]["id"],
                                       kba_score=60, credential_score=95, biometric_score=75),
        nheaders))

    assert idv_std["trust_variant"] == "STANDARD"
    assert idv_std["trust_score"] == 73.50
    assert idv_std["outcome"] == "PASS"
    assert idv_loan["trust_variant"] == "ENHANCED"
    assert idv_loan["trust_score"] == 78.50
    assert idv_loan["outcome"] == "PASS"


def test_loan_signing_request_forces_enhanced_variant(api):
    """PRD §3.3: "The evaluation uses the `ENHANCED` variant when either the request's
    `doc_category` is `LOAN_SIGNING` or the governing fee schedule for the request's
    state has `enhanced_trust_required` set to true; otherwise it uses the `STANDARD`
    variant."

    Design: Difficulty/dual_variant_calc/credential_trust_standard_vs_enhanced_diverge
    """
    world = setup_world()
    nheaders = make_notary_headers(world["notary"]["id"])
    req_loan = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="LOAN_SIGNING", delivery_mode="MOBILE",
                               expected_stamp_count=1), COORD))
    idv = get_success_data(api.create_id_verification(
        create_id_verification_payload(req_loan["id"], world["signer"]["id"],
                                       kba_score=60, credential_score=95, biometric_score=75),
        nheaders))
    assert idv["trust_variant"] == "ENHANCED"


# ─── Difficulty/combinatorial_formula/request_fee_min_cap_nonlinear_mode_a ───

def test_estimate_fee_clamped_by_state_cap(api):
    """PRD §3.2: "The final estimate is the lesser of this base amount and the
    schedule's `state_cap_cents`."
    PRD §2.5: "The cap is a hard limit: the total fee charged for a single signing in
    that state is the lesser of the computed base amount and `state_cap_cents`."

    RON, 12 stamps: base = 12*1500 + 4000 + 0(miles) + 2500(ron) = 24500, clamped to
    state_cap_cents 20000.

    Design: Difficulty/combinatorial_formula/request_fee_min_cap_nonlinear_mode_a
    """
    world = setup_world()
    request = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="GENERAL", delivery_mode="RON",
                               expected_stamp_count=12, estimated_travel_miles=50), COORD))
    get_success_data(api.create_document(
        create_document_payload(request["id"], doc_type="POA", signing_fee_cents=5000), COORD))
    quoted = get_success_data(api.quote_request(request["id"], COORD))
    assert quoted["estimate_fee_cents"] == 20000
    assert quoted["status"] == "QUOTED"


def test_estimate_fee_below_cap_is_uncapped_base(api):
    """PRD §3.2: "multiply the declared stamp count by `per_stamp_cents`, add the flat
    `travel_base_cents`, then add the mileage component, and finally — when delivery is
    remote — add `ron_surcharge_cents`."
    PRD §3.2: "however, when `delivery_mode` is `RON`, the mileage is treated as 0 (a
    remote signing incurs no travel) even if estimated miles were supplied."

    RON, 2 stamps: base = 2*1500 + 4000 + 0 + 2500 = 9500 < cap 20000.

    Design: Difficulty/combinatorial_formula/request_fee_min_cap_nonlinear_mode_a
    """
    world = setup_world()
    request = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="GENERAL", delivery_mode="RON",
                               expected_stamp_count=2, estimated_travel_miles=50), COORD))
    get_success_data(api.create_document(create_document_payload(request["id"]), COORD))
    quoted = get_success_data(api.quote_request(request["id"], COORD))
    assert quoted["estimate_fee_cents"] == 9500


# ─── Difficulty/combinatorial_formula/loan_package_round_per_doc_then_sum_mode_b

def test_loan_package_fee_rounds_per_document_then_sums(api):
    """PRD §3.9: "for each document, take its `signing_fee_cents`, multiply by one minus
    `package_discount_pct`, and round that discounted per-document amount half up to
    whole cents first; then sum the rounded per-document amounts. Rounding each document
    before summing — rather than summing then rounding once — is the contractually fixed
    order".

    Three docs at 4005 cents, 10% discount: each 4005*0.9 = 3604.5 -> round-half-up 3605;
    sum = 3605*3 = 10815 (sum-then-round would give 10814).

    Design: Difficulty/combinatorial_formula/loan_package_round_per_doc_then_sum_mode_b
    """
    world, request, documents, package = setup_loan_package(
        doc_specs=[
            {"title": "Deed of Trust", "doc_type": "DEED", "signing_fee_cents": 4005},
            {"title": "Note", "doc_type": "MORTGAGE", "signing_fee_cents": 4005},
            {"title": "Disclosure", "doc_type": "OTHER", "signing_fee_cents": 4005},
        ],
        package_overrides={"lender_ref": "LN-1", "package_discount_pct": 0.10})
    scrubbed = scrub_package(world, package)
    assert scrubbed["package_fee_cents"] == 10815
    assert scrubbed["scrub_passed"] is True
    assert scrubbed["status"] == "SCRUBBED"


def test_loan_package_fee_zero_discount_sums_face_values(api):
    """PRD §3.9: "That aggregation iterates over every `RequestDocument` of the wrapped
    request, ordered by `created_at` ascending. The rounding order is pinned: for each
    document, take its `signing_fee_cents`, multiply by one minus `package_discount_pct`,
    and round that discounted per-document amount half up to whole cents first; then sum
    the rounded per-document amounts."

    Two docs at 5000 and 2500, discount 0: sum = 7500.

    Design: Difficulty/combinatorial_formula/loan_package_round_per_doc_then_sum_mode_b
    """
    world, request, documents, package = setup_loan_package(
        doc_specs=[
            {"title": "Deed", "doc_type": "DEED", "signing_fee_cents": 5000},
            {"title": "Rider", "doc_type": "OTHER", "signing_fee_cents": 2500},
        ],
        package_overrides={"package_discount_pct": 0})
    scrubbed = scrub_package(world, package)
    assert scrubbed["package_fee_cents"] == 7500


# ─── Difficulty/boundary_precision_check/enhanced_trust_threshold_exactly_75_passes

def test_enhanced_trust_exactly_at_threshold_passes(api):
    """PRD §3.3: "Under `ENHANCED`, the weighted score is the KBA score times 0.3, plus
    the credential score times 0.4, plus the biometric score times 0.3, and the passing
    threshold is 75."
    PRD §3.3: "The `outcome` is `PASS` when `trust_score` is greater than or equal to the
    variant's threshold, and `FAIL` otherwise."

    LOAN_SIGNING forces ENHANCED. kba=70, credential=90, biometric=60 ->
    0.3*70 + 0.4*90 + 0.3*60 = 21 + 36 + 18 = 75.00 -> PASS (>= 75).

    Design: Difficulty/boundary_precision_check/enhanced_trust_threshold_exactly_75_passes
    """
    world = setup_world()
    nheaders = make_notary_headers(world["notary"]["id"])
    req = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="LOAN_SIGNING", delivery_mode="MOBILE",
                               expected_stamp_count=1), COORD))
    idv = get_success_data(api.create_id_verification(
        create_id_verification_payload(req["id"], world["signer"]["id"],
                                       kba_score=70, credential_score=90, biometric_score=60),
        nheaders))
    assert idv["trust_score"] == 75.00
    assert idv["outcome"] == "PASS"
    assert idv["trust_variant"] == "ENHANCED"


def test_enhanced_trust_one_point_below_threshold_fails(api):
    """PRD §3.3: "The `outcome` is `PASS` when `trust_score` is greater than or equal to
    the variant's threshold, and `FAIL` otherwise."

    LOAN_SIGNING forces ENHANCED, threshold 75. kba=65, credential=90, biometric=60 ->
    0.3*65 + 0.4*90 + 0.3*60 = 19.5 + 36 + 18 = 73.50 -> FAIL (< 75).

    Design: Difficulty/boundary_precision_check/enhanced_trust_threshold_exactly_75_passes
    """
    world = setup_world()
    nheaders = make_notary_headers(world["notary"]["id"])
    req = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="LOAN_SIGNING", delivery_mode="MOBILE",
                               expected_stamp_count=1), COORD))
    idv = get_success_data(api.create_id_verification(
        create_id_verification_payload(req["id"], world["signer"]["id"],
                                       kba_score=65, credential_score=90, biometric_score=60),
        nheaders))
    assert idv["trust_score"] == 73.50
    assert idv["outcome"] == "FAIL"


# ─── Corner/calculations/apostille_certification_fee_non_hague ───────────────

def test_apostille_non_hague_destination_is_certification(api):
    """PRD §3.8: "The `authentication_type` is `APOSTILLE` when the destination is a
    Hague-Convention member country and `CERTIFICATION` otherwise (the embassy chain);
    the member set is `FR`, `DE`, `JP`, `MX`, `IT`, `ES`, `GB`, and `NL`. The flat
    `fee_cents` follows that branch: 2000 cents for an `APOSTILLE`, 4000 cents for a
    `CERTIFICATION`."

    BR is not in the Hague member set -> CERTIFICATION / 4000.

    Design: Corner/calculations/apostille_certification_fee_non_hague
    """
    world = setup_world()
    request = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="APOSTILLE_BOUND", delivery_mode="MOBILE",
                               expected_stamp_count=1), COORD))
    document = get_success_data(api.create_document(
        create_document_payload(request["id"], title="Cert", doc_type="BIRTH_CERT",
                                requires_apostille=True, signing_fee_cents=1000), COORD))
    order = get_success_data(api.create_apostille_order(
        create_apostille_order_payload(document["id"], destination_country="BR",
                                       sos_office_state="CA"), CLERK))
    assert order["authentication_type"] == "CERTIFICATION"
    assert order["fee_cents"] == 4000


# ─── Corner/calculations/final_fee_excludes_voided_journal_entries ───────────

def test_final_fee_excludes_voided_journal_entries(api):
    """PRD §3.6: "the stamp count is the number of journal entries for the request whose
    `entry_status` is `COMPLETED` (voided entries are excluded), and the miles are
    `actual_travel_miles` — again treated as 0 when `delivery_mode` is `RON`."

    RON request, 3 acts recorded then 1 voided -> 2 COMPLETED acts:
    final = 2*1500 + 4000 + 0(ron miles) + 2500(ron) = 9500.

    Design: Corner/calculations/final_fee_excludes_voided_journal_entries
    """
    world = setup_world()
    nheaders = make_notary_headers(world["notary"]["id"])
    request = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="GENERAL", delivery_mode="RON",
                               expected_stamp_count=3), COORD))
    document = get_success_data(api.create_document(create_document_payload(request["id"]), COORD))
    quoted = get_success_data(api.quote_request(request["id"], COORD))
    get_success_data(api.assign_request(
        request["id"],
        {"notary_id": world["notary"]["id"], "expected_request_version": quoted["version"]},
        COORD))
    get_success_data(api.create_id_verification(
        create_id_verification_payload(request["id"], world["signer"]["id"],
                                       kba_score=80, credential_score=90, biometric_score=80),
        nheaders))
    get_success_data(api.create_ron_session(
        create_ron_session_payload(request["id"], "2026-03-02T10:00:00Z", "2026-03-02T11:00:00Z"),
        nheaders))
    get_success_data(api.start_session(request["id"], nheaders))
    je1 = get_success_data(api.create_journal_entry(
        create_journal_entry_payload(request["id"], document["id"], act_type="JURAT"), nheaders))
    get_success_data(api.create_journal_entry(
        create_journal_entry_payload(request["id"], document["id"], act_type="ACKNOWLEDGMENT"),
        nheaders))
    get_success_data(api.create_journal_entry(
        create_journal_entry_payload(request["id"], document["id"], act_type="OATH"), nheaders))
    get_success_data(api.void_journal_entry(je1["id"], COORD))
    completed = get_success_data(api.complete_request(
        request["id"], {"actual_travel_miles": 0}, nheaders))
    assert completed["final_fee_cents"] == 9500


# ─── Corner/consistency_model/quote_fee_visible_in_same_response ─────────────

def test_quote_returns_estimate_in_same_response(api):
    """PRD §3.2: "Quoting computes the provisional fee and writes it to
    `estimate_fee_cents`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."

    MOBILE, 3 stamps, 10 miles: base = 3*1500 + 4000 + 10*100 = 9500.

    Design: Corner/consistency_model/quote_fee_visible_in_same_response
    """
    world = setup_world()
    request = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="GENERAL", delivery_mode="MOBILE",
                               expected_stamp_count=3, estimated_travel_miles=10), COORD))
    get_success_data(api.create_document(create_document_payload(request["id"]), COORD))
    quoted = get_success_data(api.quote_request(request["id"], COORD))
    assert quoted["estimate_fee_cents"] == 9500
    assert quoted["status"] == "QUOTED"
