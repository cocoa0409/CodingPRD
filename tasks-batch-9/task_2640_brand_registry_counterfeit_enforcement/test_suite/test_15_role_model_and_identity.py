"""The role model and the two identity semantics of the brand-protection API.

Five roles carry opaque operator identifiers; `AuthorizedRepresentative` carries
the id of a designation row that the server resolves on every request.
"""

from test_helpers import (
    ApiErrorId,
    CASE_STATUS_IN_LITIGATION,
    CASE_STATUS_OPEN,
    CORRESPONDENCE_CD_RESPONDED,
    CORRESPONDENCE_CD_SENT,
    CORRESPONDENCE_NONE,
    DESIGNATION_STATUS_DESIGNATED,
    ENROLLMENT_STATUS_ACTIVE,
    ENROLLMENT_STATUS_SUBMITTED,
    LITIGATION_AUTHORIZED,
    LITIGATION_NONE,
    MARKETPLACE_EBY,
    RESPONSE_KIND_DENIAL,
    SCOPE_AUTHORIZE_LITIGATION,
    SCOPE_BOTH,
    SELLER_STATUS_ACTIVE,
    SELLER_STATUS_UNDER_INVESTIGATION,
    TEST_USERS,
    UNAUTHENTICATED_HEADERS,
    assertions,
    build_user_headers,
    factories,
    fixtures,
    make_authorized_representative_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["brand_administrator_headers"]
ANALYST = TEST_USERS["enforcement_analyst_headers"]
LIAISON = TEST_USERS["marketplace_liaison_headers"]
CUSTOMS = TEST_USERS["customs_coordinator_headers"]
COUNSEL = TEST_USERS["legal_counsel_headers"]
UNKNOWN_REPRESENTATIVE = TEST_USERS["authorized_representative_headers"]


def test_roles_cannot_perform_another_roles_exclusive_operations(api):
    """Three writes reserved to one role each are refused to a different role.

    Brand registration belongs to the administrator, enrolment activation to the
    marketplace liaison and seller registration to the analyst. Each refusal is
    a 403 that persists nothing, and the operation still succeeds for the role
    the PRD names.

    PRD §2.1: "If both headers are present and well-formed but the named role is not among the roles authorised for the requested endpoint (see the table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.1: "A `BrandAdministrator` registers the brand owner by supplying the `name` under which the brand appears on marketplaces (1 to 120 characters, not blank), the `owner_legal_entity` that owns the trademark portfolio (1 to 160 characters, not blank), the `home_jurisdiction` as an ISO 3166-1 alpha-2 code written as exactly two uppercase letters, and `authorized_msrp_cents`, the brand-level authorised reference price in cents, which must be at least 1 because it serves as the denominator of the price-deviation term in listing screening."
    PRD §3.2: "A `MarketplaceLiaison` performs the acceptance, and three cross-entity gates must hold on the asserted registration."
    PRD §3.3: "An `EnforcementAnalyst` registers each storefront under observation by supplying the `marketplace_code` on which the identity trades (`AMZ`, `EBY` or `WLM`), the marketplace-assigned `seller_ref` (1 to 40 characters), the `legal_name` obtained through seller identification (1 to 160 characters, not blank), and optionally the `jurisdiction` the seller declares, as exactly two uppercase letters."
    Design: Corner/rbac/roles_cannot_perform_another_roles_exclusive_operations
    """
    brand = fixtures.create_brand(api)
    registration = fixtures.create_registration(api, brand["id"])
    enrollment = fixtures.create_enrollment(api, brand["id"], registration["id"])

    validate_error(api.create_brand(factories.brand_payload(), headers=ANALYST),
                   ApiErrorId.UNAUTHORIZED)
    validate_error(api.activate_enrollment(enrollment["id"], headers=COUNSEL),
                   ApiErrorId.UNAUTHORIZED)
    seller_payload = factories.seller_payload()
    validate_error(api.create_seller(seller_payload, headers=LIAISON),
                   ApiErrorId.UNAUTHORIZED)

    brands, brand_meta = validate_paginated(api.list_brands(headers=ADMIN))
    assert brand_meta["total_count"] == 1, (
        f"Expected the refused brand create to persist nothing, got {brand_meta['total_count']} brands")
    assert brands[0]["id"] == brand["id"], (
        f"Expected only {brand['id']} in the registry, got {brands[0]['id']}")

    untouched = validate_success(api.get_enrollment(enrollment["id"], headers=LIAISON), 200)
    assert untouched["enrollment_status"] == ENROLLMENT_STATUS_SUBMITTED, (
        f"Expected the enrolment to stay {ENROLLMENT_STATUS_SUBMITTED}, "
        f"got {untouched['enrollment_status']}")
    assert untouched["activated_at"] is None, (
        f"Expected activated_at to stay null, got {untouched['activated_at']}")
    assertions.assert_unchanged(enrollment, untouched)

    created = validate_success(api.create_seller(seller_payload, headers=ANALYST), 201)
    assert created["status"] == SELLER_STATUS_ACTIVE, (
        f"Expected seller status {SELLER_STATUS_ACTIVE}, got {created['status']}")
    assert created["version"] == 1, f"Expected version 1, got {created['version']}"

    activated = validate_success(api.activate_enrollment(enrollment["id"], headers=LIAISON), 200)
    assert activated["enrollment_status"] == ENROLLMENT_STATUS_ACTIVE, (
        f"Expected enrollment_status {ENROLLMENT_STATUS_ACTIVE}, "
        f"got {activated['enrollment_status']}")


def test_unauthenticated_request_is_rejected_before_role_and_payload_checks(api):
    """Missing or unknown role headers give 401 before the body is examined.

    The seller payload carries an out-of-domain marketplace code and a blank
    seller reference, either of which would be a 400 on an authenticated
    request. Header resolution runs first, so the answer is 401 and nothing is
    written.

    PRD §2.1: "Every request to every endpoint must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role that principal is acting in."
    PRD §2.1: "If either header is absent, or if `X-User-Role` does not name one of the six roles below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined."
    PRD §2.1: "The six roles are `BrandAdministrator`, `EnforcementAnalyst`, `AuthorizedRepresentative`, `MarketplaceLiaison`, `CustomsCoordinator` and `LegalCounsel`."
    PRD §2.9: "Evaluation stops there and nothing is persisted — not even a value the server had already computed."
    Design: Corner/rbac/unauthenticated_request_is_rejected_before_role_and_payload_checks
    """
    brand = fixtures.create_brand(api)
    malformed = factories.seller_payload(marketplace_code="ZZZ", seller_ref="")

    validate_error(api.create_seller(malformed, headers=UNAUTHENTICATED_HEADERS),
                   ApiErrorId.UNAUTHENTICATED)
    validate_error(
        api.create_seller(malformed, headers=build_user_headers("op-77", "CounterfeitTsar")),
        ApiErrorId.UNAUTHENTICATED)
    validate_error(api.get_brand(brand["id"], headers=UNAUTHENTICATED_HEADERS),
                   ApiErrorId.UNAUTHENTICATED)
    validate_error(api.list_brands(headers=UNAUTHENTICATED_HEADERS), ApiErrorId.UNAUTHENTICATED)

    sellers, seller_meta = validate_paginated(api.list_sellers(headers=ANALYST))
    assert seller_meta["total_count"] == 0, (
        f"Expected no seller to be written by an unauthenticated create, got {seller_meta['total_count']}")
    assert sellers == [], f"Expected an empty seller index, got {sellers}"

    still_there = validate_success(api.get_brand(brand["id"], headers=ADMIN), 200)
    assertions.assert_unchanged(brand, still_there)


def test_representative_identity_naming_no_designation_row_returns_not_found(api):
    """A representative id that resolves to nothing is a 404, not a 403.

    The role is authorised for the letter endpoint, so header resolution is the
    first thing that can fail: the server looks the designation row up on every
    request the role makes and finds none.

    PRD §2.1: "When `X-User-Role` is `AuthorizedRepresentative`, `X-User-ID` is the `id` of an existing authorised-representative designation row."
    PRD §2.1: "The server resolves that row on every request the role makes; an `X-User-ID` that names no such row is rejected with `ERR_REPRESENTATIVE_NOT_FOUND` (HTTP 404)."
    PRD §3.9: "Sending the letter stamps `cease_desist_sent_by_rep_id` with the acting `X-User-ID` — this is the pin that the segregation-of-duties rule reads later — sets `cd_sent_at` from the logical clock, persists `letter_ref`, computes `cd_response_due_at` by advancing `cd_sent_at` by fourteen business days, and increments the case's `version` by 1."
    Design: Corner/rbac/representative_identity_naming_no_designation_row_returns_not_found
    """
    fixtures.set_clock(api, "2026-08-05T08:00:00Z")
    brand = fixtures.create_brand(api)
    seller = fixtures.create_seller(api)
    case = fixtures.create_case(api, brand["id"], seller["id"])
    assert case["case_status"] == CASE_STATUS_OPEN, (
        f"Expected case_status {CASE_STATUS_OPEN}, got {case['case_status']}")

    validate_error(api.send_cease_desist(case["id"], "CD-GHOST-1", headers=UNKNOWN_REPRESENTATIVE),
                   ApiErrorId.REPRESENTATIVE_NOT_FOUND)

    untouched = fixtures.read_case(api, case["id"])
    assert untouched["correspondence_status"] == CORRESPONDENCE_NONE, (
        f"Expected correspondence_status {CORRESPONDENCE_NONE}, got {untouched['correspondence_status']}")
    for field in ("cease_desist_sent_by_rep_id", "cd_sent_at", "cd_response_due_at", "letter_ref"):
        assert untouched[field] is None, f"Expected {field} to stay null, got {untouched[field]}"
    assertions.assert_unchanged(case, untouched)

    designations, designation_meta = validate_paginated(api.list_representatives(headers=ADMIN))
    assert designation_meta["total_count"] == 0, (
        f"Expected no designation row to exist, got {designation_meta['total_count']}")
    assert designations == [], f"Expected an empty designation index, got {designations}"


def test_a_both_scope_representative_cannot_authorise_its_own_letter(api):
    """A BOTH designation holds every power and still cannot self-authorise.

    The seller is escalated by a confirmed border diversion worth 25.15 points
    so that correspondence is permitted at all. The BOTH-scope designation sends
    the letter, and its own escalation attempt is refused on identity alone: a
    second designation under another active enrolment of the same brand then
    succeeds.

    PRD §3.3: "A **seizure confirmed** strike carries a base of 25.15 points — the heaviest single strike in the domain, enough to escalate a previously clean seller on its own."
    PRD §3.3: "At a cluster total of 60.00 or more the seller is `BLOCKED`; at a cluster total of at least 25.00 but below 60.00 the seller is `UNDER_INVESTIGATION`; below 25.00 the seller is `ACTIVE`."
    PRD §3.9: "And the case's seller must be `UNDER_INVESTIGATION` or `BLOCKED`, because correspondence may only be aimed at an escalated seller; a still-`ACTIVE` seller is refused with `ERR_SELLER_NOT_UNDER_INVESTIGATION` (HTTP 422)."
    PRD §2.1: "Ownership and attribution checks on any resource that references a representative compare that resource's representative reference against `X-User-ID` — most importantly, authorising litigation compares `X-User-ID` against the case's `cease_desist_sent_by_rep_id` and refuses a match, and it additionally requires the acting designation to sit under an `ACTIVE` enrolment of the case's brand."
    PRD §3.9: "The acting `X-User-ID` must differ from the case's `cease_desist_sent_by_rep_id`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
    PRD §3.9: "The practical consequence is that a brand which has designated only one representative simply cannot reach `AUTHORIZED`; it must designate a second one."
    PRD §3.9: "On success `litigation_authorized_by_rep_id` is stamped with the acting `X-User-ID`, the roll-up moves `case_status` `OPEN → IN_LITIGATION`, and `version` is incremented by 1."
    Design: Corner/rbac/a_both_scope_representative_cannot_authorise_its_own_letter
    """
    ctx = fixtures.setup_enrolled_brand(
        api, clock="2026-08-05T08:00:00Z",
        representative={"authority_scope": SCOPE_BOTH, "power_of_attorney_ref": "POA-BOTH"})
    rep_both = ctx["representative"]
    assert rep_both["authority_scope"] == SCOPE_BOTH, (
        f"Expected authority_scope {SCOPE_BOTH}, got {rep_both['authority_scope']}")

    second_enrollment = fixtures.create_enrollment(
        api, ctx["brand"]["id"], ctx["registration"]["id"], marketplace_code=MARKETPLACE_EBY)
    second_enrollment = fixtures.activate_enrollment(api, second_enrollment["id"])
    rep_other = fixtures.create_representative(
        api, second_enrollment["id"], authority_scope=SCOPE_AUTHORIZE_LITIGATION,
        power_of_attorney_ref="POA-SECOND")

    ctx["seller"] = fixtures.create_seller(api)
    ctx = fixtures.setup_escalated_seller_via_diversion(api, ctx)
    assertions.assert_seller_strikes(ctx["seller"], 25.15, 25.15, SELLER_STATUS_UNDER_INVESTIGATION)

    case = fixtures.create_case(api, ctx["brand"]["id"], ctx["seller"]["id"])
    sent = fixtures.send_cease_desist(api, case["id"], rep_both["id"], "CD-BOTH-1")
    assert sent["correspondence_status"] == CORRESPONDENCE_CD_SENT, (
        f"Expected correspondence_status {CORRESPONDENCE_CD_SENT}, got {sent['correspondence_status']}")
    assert sent["cease_desist_sent_by_rep_id"] == rep_both["id"], (
        f"Expected cease_desist_sent_by_rep_id {rep_both['id']}, got {sent['cease_desist_sent_by_rep_id']}")

    answered = fixtures.record_case_response(api, case["id"], "RESP-BOTH-1", RESPONSE_KIND_DENIAL)
    assert answered["correspondence_status"] == CORRESPONDENCE_CD_RESPONDED, (
        f"Expected correspondence_status {CORRESPONDENCE_CD_RESPONDED}, "
        f"got {answered['correspondence_status']}")

    validate_error(
        api.authorize_litigation(case["id"], "AUTH-SELF-1",
                                 headers=make_authorized_representative_headers(rep_both["id"])),
        ApiErrorId.SEGREGATION_OF_DUTIES)

    refused = fixtures.read_case(api, case["id"])
    assert refused["litigation_status"] == LITIGATION_NONE, (
        f"Expected litigation_status {LITIGATION_NONE}, got {refused['litigation_status']}")
    assert refused["litigation_authorized_by_rep_id"] is None, (
        f"Expected litigation_authorized_by_rep_id to stay null, "
        f"got {refused['litigation_authorized_by_rep_id']}")
    assert refused["case_status"] == CASE_STATUS_OPEN, (
        f"Expected case_status {CASE_STATUS_OPEN}, got {refused['case_status']}")
    assertions.assert_unchanged(answered, refused)

    escalated = validate_success(
        api.authorize_litigation(case["id"], "AUTH-SECOND-1",
                                 headers=make_authorized_representative_headers(rep_other["id"])), 200)
    assert escalated["litigation_status"] == LITIGATION_AUTHORIZED, (
        f"Expected litigation_status {LITIGATION_AUTHORIZED}, got {escalated['litigation_status']}")
    assert escalated["litigation_authorized_by_rep_id"] == rep_other["id"], (
        f"Expected litigation_authorized_by_rep_id {rep_other['id']}, "
        f"got {escalated['litigation_authorized_by_rep_id']}")
    assert escalated["case_status"] == CASE_STATUS_IN_LITIGATION, (
        f"Expected case_status {CASE_STATUS_IN_LITIGATION}, got {escalated['case_status']}")
    assert escalated["cease_desist_sent_by_rep_id"] == rep_both["id"], (
        f"Expected the letter's sender to stay {rep_both['id']}, "
        f"got {escalated['cease_desist_sent_by_rep_id']}")
    assert escalated["version"] == refused["version"] + 1, (
        f"Expected version {refused['version'] + 1}, got {escalated['version']}")

    unpunished = validate_success(api.get_representative(rep_both["id"], headers=ADMIN), 200)
    assert unpunished["authority_scope"] == SCOPE_BOTH, (
        f"Expected authority_scope {SCOPE_BOTH}, got {unpunished['authority_scope']}")
    assert unpunished["designation_status"] == DESIGNATION_STATUS_DESIGNATED, (
        f"Expected designation_status {DESIGNATION_STATUS_DESIGNATED}, "
        f"got {unpunished['designation_status']}")


def test_every_role_reads_the_shared_index_and_detail_endpoints(api):
    """All six roles read the brand detail and the seller index identically.

    The representative acts through a real designation row, the other five
    through opaque operator identifiers. Every read returns the same payload and
    leaves both rows untouched.

    PRD §2.1: "The six roles are `BrandAdministrator`, `EnforcementAnalyst`, `AuthorizedRepresentative`, `MarketplaceLiaison`, `CustomsCoordinator` and `LegalCounsel`."
    PRD §2.1: "When `X-User-Role` is `AuthorizedRepresentative`, `X-User-ID` is the `id` of an existing authorised-representative designation row."
    PRD §2.1: "When `X-User-Role` is `BrandAdministrator`, `EnforcementAnalyst`, `MarketplaceLiaison`, `CustomsCoordinator` or `LegalCounsel`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity."
    PRD §3.3: "Sellers are readable individually and listable with optional filters on `canonical_seller_id` — which is how an entire alias cluster is enumerated — on `marketplace_code` and on `status`."
    PRD §2.4: "Creating a new resource returns HTTP 201; every other successful operation, including every action that advances a lifecycle and every read, returns HTTP 200."
    PRD §3.3: "A new seller row starts with `status` `ACTIVE`, `canonical_seller_id` null, and both `standalone_strike_points` and `cluster_strike_points` at 0.00."
    Design: Corner/rbac/every_role_reads_the_shared_index_and_detail_endpoints
    """
    ctx = fixtures.setup_enrolled_brand(api, clock="2026-08-05T08:00:00Z")
    brand = fixtures.read_brand(api, ctx["brand"]["id"])
    seller = fixtures.create_seller(api)

    representative_headers = make_authorized_representative_headers(ctx["representative"]["id"])
    every_role = {
        "BrandAdministrator": ADMIN,
        "EnforcementAnalyst": ANALYST,
        "AuthorizedRepresentative": representative_headers,
        "MarketplaceLiaison": LIAISON,
        "CustomsCoordinator": CUSTOMS,
        "LegalCounsel": COUNSEL,
    }

    for role, headers in every_role.items():
        detail = validate_success(api.get_brand(brand["id"], headers=headers), 200)
        assert detail == brand, f"Expected {role} to read the same brand payload, got {detail}"

        rows, meta = validate_paginated(api.list_sellers(headers=headers))
        assert meta["total_count"] == 1, (
            f"Expected {role} to see 1 seller, got {meta['total_count']}")
        assert rows[0]["id"] == seller["id"], (
            f"Expected {role} to see seller {seller['id']}, got {rows[0]['id']}")
        assertions.assert_seller_strikes(rows[0], 0.00, 0.00, SELLER_STATUS_ACTIVE)

    assertions.assert_unchanged(brand, fixtures.read_brand(api, brand["id"]))
    assertions.assert_unchanged(seller, fixtures.read_seller(api, seller["id"]))
