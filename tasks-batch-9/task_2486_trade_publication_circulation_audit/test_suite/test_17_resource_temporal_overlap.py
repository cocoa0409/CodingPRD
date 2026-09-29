"""Two contended calendars: a publication's statement periods and a recipient's qualification window."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_QUALIFICATION_WINDOW_OVERLAP,
    ERR_STATEMENT_PERIOD_OVERLAP,
)
from test_helpers.factories import certify_payload, verify_payload
from test_helpers.fixtures import (
    add_complete_rule_set,
    attach_source_document,
    certify_statement,
    move_clock,
    open_request,
    open_statement,
    qualify_subscriber,
    read_statement,
    read_subscriber,
    register_publication,
    review_request,
    verify_request,
)
from test_helpers.test_users import EXECUTIVE_HEADERS, MANAGER_HEADERS, SPECIALIST_HEADERS


def draft_over(publication_id, period_start, period_end):
    statement = open_statement(
        publication_id,
        period_start=period_start,
        period_end=period_end,
        basis="AS_OF_PERIOD_END",
    )
    # Creation never applies the period test, so a straddling draft comes into being.
    assert statement["status"] == "DRAFT"
    assert statement["total_qualified_copies"] == 0
    return statement


def refuse_certification(statement_id, note):
    return validate_error(
        api_client.certify_statement(
            statement_id, certify_payload(certification_note=note), EXECUTIVE_HEADERS
        ),
        ERR_STATEMENT_PERIOD_OVERLAP,
        409,
    )


def test_adjacent_statement_periods_certify_but_a_straddling_one_does_not():
    """Sharing an endpoint is not an overlap; covering the shared endpoint is.

    "Exact adjacency is explicitly permitted — one period ending at the instant the
    next begins is not an overlap — and the statement named by
    `restates_statement_id` is excluded from the candidate set, since a restatement is
    meant to cover the same period as the statement it replaces."

    Design: Difficulty/resource_temporal_overlap/statement_period_adjacency_allowed_overlap_rejected
    """
    publication = register_publication(
        name="Statement Calendar Monthly", industry_code="MANUFACTURING"
    )

    first = draft_over(publication["id"], "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z")
    filed_first = certify_statement(first["id"])
    assert filed_first["status"] == "FILED"

    second = draft_over(publication["id"], "2026-04-01T00:00:00Z", "2026-07-01T00:00:00Z")
    # The second period begins at the instant the first ends.
    filed_second = certify_statement(second["id"])
    assert filed_second["status"] == "FILED"
    assert filed_second["declared_total_copies"] == 0

    straddling = draft_over(
        publication["id"], "2026-03-01T00:00:00Z", "2026-06-01T00:00:00Z"
    )
    refuse_certification(straddling["id"], "straddles both filed periods")

    blocked = read_statement(straddling["id"])
    assert blocked["status"] == "DRAFT"
    assert blocked["filed_at"] is None
    assert blocked["certified_by_user_id"] is None

    # Neither neighbour was disturbed by the refusal.
    assert read_statement(first["id"])["status"] == "FILED"
    assert read_statement(second["id"])["status"] == "FILED"


def test_a_draft_neighbour_is_already_in_the_candidate_set():
    """The candidate set starts at DRAFT, so two overlapping drafts cannot both be sworn.

    "**Fourth**, periods may not overlap: the statement's half-open period must not
    intersect the period of any other statement of the same publication in `DRAFT`,
    `FILED`, `UNDER_AUDIT`, `FINDINGS_OPEN`, `AUDIT_CLEARED` or
    `RESTATEMENT_REQUIRED`."

    Design: Difficulty/resource_temporal_overlap/statement_period_adjacency_allowed_overlap_rejected
    """
    publication = register_publication(
        name="Draft Candidate Monthly", industry_code="MANUFACTURING"
    )

    earlier = draft_over(publication["id"], "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z")
    later = draft_over(publication["id"], "2026-02-01T00:00:00Z", "2026-05-01T00:00:00Z")

    # Nothing is FILED yet, and the refusal comes from the other DRAFT alone. The
    # candidate set is symmetric, so neither of the two overlapping drafts can be sworn.
    refuse_certification(later["id"], "overlaps a sibling draft")
    refuse_certification(earlier["id"], "overlaps a sibling draft")
    assert read_statement(later["id"])["status"] == "DRAFT"
    assert read_statement(earlier["id"])["status"] == "DRAFT"

    # On a publication with no overlapping draft in the way, the same refusal comes
    # from a FILED neighbour instead.
    other = register_publication(
        name="Filed Candidate Monthly", industry_code="MANUFACTURING"
    )
    filed = draft_over(other["id"], "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z")
    assert certify_statement(filed["id"])["status"] == "FILED"

    straddling = draft_over(other["id"], "2026-02-01T00:00:00Z", "2026-05-01T00:00:00Z")
    refuse_certification(straddling["id"], "overlaps a filed period")
    assert read_statement(straddling["id"])["status"] == "DRAFT"

    # Exact adjacency to the FILED period is permitted; the straddling draft is not
    # itself a candidate obstacle for a period it does not intersect.
    adjacent = draft_over(other["id"], "2026-05-01T00:00:00Z", "2026-08-01T00:00:00Z")
    assert certify_statement(adjacent["id"])["status"] == "FILED"


def renewal_request(subscriber_id, signed_at):
    """A fresh card and a reviewed renewal request against an already-qualified recipient."""
    recipient = read_subscriber(subscriber_id)
    document = attach_source_document(
        subscriber_id, MANAGER_HEADERS, captured_at=signed_at
    )
    request = open_request(
        subscriber_id,
        document["id"],
        recipient["version"],
        headers=SPECIALIST_HEADERS,
        signed_at=signed_at,
    )
    renewing = read_subscriber(subscriber_id)
    assert renewing["qualification_status"] == "PENDING_QUALIFICATION"
    # The running window keeps counting while the renewal is in flight.
    assert renewing["qualified_at"] == recipient["qualified_at"]
    assert renewing["qualification_expires_at"] == recipient["qualification_expires_at"]
    return review_request(request["id"])


def read_request(request_id):
    return validate_success(
        api_client.get_qualification_request(request_id, SPECIALIST_HEADERS), 200
    )


def test_early_renewal_collides_and_the_same_request_truncates_inside_the_grace_window():
    """The identical verify call is an error in 2026 and the expected shape of a renewal in 2029.

    "Any intersection is refused with `ERR_QUALIFICATION_WINDOW_OVERLAP` and HTTP 409
    — unless the renewal grace period is open, meaning the current logical clock has
    reached or passed `qualification_expires_at` moved back by the publication's
    `renewal_grace_days`."

    Design: Difficulty/resource_temporal_overlap/qualification_window_overlap_rejected_then_grace_renewal_truncates
    """
    publication = register_publication(
        name="Grace Window Monthly",
        industry_code="MANUFACTURING",
        qualification_validity_months=36,
        renewal_grace_days=90,
    )
    add_complete_rule_set(publication["id"])
    enrolled = qualify_subscriber(
        publication["id"],
        signed_at="2026-07-15T00:00:00Z",
        captured_at="2026-07-15T00:00:00Z",
        company_name="Quebec Renewal Works",
        subscription_class="CONTROLLED",
        copies=70,
    )
    recipient = enrolled["subscriber"]
    assert recipient["qualified_at"].startswith("2026-08-01T00:00:00")
    assert recipient["qualification_expires_at"].startswith("2029-08-01T00:00:00")

    move_clock("2026-09-01T00:00:00Z")
    renewal = renewal_request(recipient["id"], "2026-08-15T00:00:00Z")
    # Base 100 plus a 10-point DIRECT_MAIL bonus, clamped at the ceiling of 100.
    assert renewal["computed_score"] == 100

    validate_error(
        api_client.verify_qualification_request(
            renewal["id"],
            verify_payload(decision_reason="renewal attempted 35 months early"),
            SPECIALIST_HEADERS,
        ),
        ERR_QUALIFICATION_WINDOW_OVERLAP,
        409,
    )
    assert read_request(renewal["id"])["status"] == "UNDER_REVIEW"
    assert read_subscriber(recipient["id"])["qualification_score"] == 100

    # 2029-05-03 is ninety days before the expiry, so 2029-05-05 is inside the grace.
    move_clock("2029-05-05T00:00:00Z")
    renewed = verify_request(
        renewal["id"], decision_reason="renewal inside the 90-day grace window"
    )
    assert renewed["status"] == "VERIFIED"
    assert renewed["effective_from"].startswith("2029-05-05T00:00:00")
    assert renewed["effective_to"].startswith("2032-05-05T00:00:00")

    # The outgoing window is pulled back so that the two windows abut.
    predecessor = read_request(enrolled["request"]["id"])
    assert predecessor["status"] == "VERIFIED"
    assert predecessor["effective_to"].startswith("2029-05-05T00:00:00")

    requalified = read_subscriber(recipient["id"])
    assert requalified["qualification_status"] == "QUALIFIED"
    assert requalified["qualified_at"].startswith("2029-05-05T00:00:00")
    assert requalified["qualification_expires_at"].startswith("2032-05-05T00:00:00")


def test_touching_windows_collide_until_the_grace_period_opens_at_the_expiry_instant():
    """With no grace days at all the renewal must wait for the very instant of expiry.

    "Both intervals include their endpoints, so touching at a single instant counts as
    intersecting."

    Design: Difficulty/resource_temporal_overlap/qualification_window_overlap_rejected_then_grace_renewal_truncates
    """
    publication = register_publication(
        name="No Grace Monthly",
        industry_code="MANUFACTURING",
        qualification_validity_months=12,
        renewal_grace_days=0,
    )
    add_complete_rule_set(publication["id"])
    enrolled = qualify_subscriber(
        publication["id"],
        signed_at="2026-07-15T00:00:00Z",
        captured_at="2026-07-15T00:00:00Z",
        company_name="Romeo Renewal Works",
        subscription_class="CONTROLLED",
        copies=40,
    )
    recipient = enrolled["subscriber"]
    assert recipient["qualification_expires_at"].startswith("2027-08-01T00:00:00")

    move_clock("2027-07-31T00:00:00Z")
    renewal = renewal_request(recipient["id"], "2027-07-01T00:00:00Z")
    assert renewal["computed_score"] == 100

    # A window opening on 2027-07-31 sits inside the running one, and with zero grace
    # days the grace period does not open until 2027-08-01 itself.
    validate_error(
        api_client.verify_qualification_request(
            renewal["id"],
            verify_payload(decision_reason="one day before the expiry instant"),
            SPECIALIST_HEADERS,
        ),
        ERR_QUALIFICATION_WINDOW_OVERLAP,
        409,
    )
    waiting = read_subscriber(recipient["id"])
    assert waiting["qualification_status"] == "PENDING_QUALIFICATION"
    assert waiting["qualified_at"].startswith("2026-08-01T00:00:00")
    assert waiting["qualification_expires_at"].startswith("2027-08-01T00:00:00")

    move_clock("2027-08-01T00:00:00Z")
    renewed = verify_request(
        renewal["id"], decision_reason="renewal at the expiry instant"
    )
    assert renewed["status"] == "VERIFIED"
    assert renewed["effective_from"].startswith("2027-08-01T00:00:00")
    assert renewed["effective_to"].startswith("2028-08-01T00:00:00")

    # Truncation pulls the predecessor's end back to the clock, where it already sat.
    predecessor = read_request(enrolled["request"]["id"])
    assert predecessor["effective_to"].startswith("2027-08-01T00:00:00")

    requalified = read_subscriber(recipient["id"])
    assert requalified["qualification_status"] == "QUALIFIED"
    assert requalified["qualified_at"].startswith("2027-08-01T00:00:00")
    assert requalified["qualification_expires_at"].startswith("2028-08-01T00:00:00")
